"""CampusRoute Windows service and tray client.

The service captures outbound IPv4/IPv6 packets with the bundled signed
WinDivert payload, classifies each destination, and reinjects packets through
the selected campus or USB interface.  Missing driver/DLL or an open failure
keeps a fail-closed firewall state instead of silently using the default route.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from multiprocessing.connection import Client, Listener
from pathlib import Path
from typing import Any, Iterable, Optional

APP_NAME = "CampusRoute"
SERVICE_NAME = "CampusRoute"
PROGRAM_DATA = Path(os.environ.get("PROGRAMDATA", Path.home()))
BASE_DIR = PROGRAM_DATA / APP_NAME
CONFIG_PATH = BASE_DIR / "config.json"
RULES_DIR = BASE_DIR / "rules"
CN4_PATH = RULES_DIR / "cn4.txt"
CN6_PATH = RULES_DIR / "cn6.txt"
RULES_PATH = CN4_PATH  # compatibility alias for existing tests/tools
IPC_TOKEN_PATH = BASE_DIR / "ipc.token"
LOG_PATH = BASE_DIR / "campusroute.log"
PIPE_NAME = r"\\.\pipe\CampusRoute"
FIREWALL_SNAPSHOT = BASE_DIR / "firewall-before.wfw"
ROUTE_SNAPSHOT = BASE_DIR / "routes-before.json"
STATE_PATH = BASE_DIR / "state.json"

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    BUNDLE_DIR = Path(sys._MEIPASS)  # type: ignore[attr-defined]
else:
    BUNDLE_DIR = Path(__file__).resolve().parent
DRIVER_DIR = BUNDLE_DIR / "drivers"
DRIVER_PATH = DRIVER_DIR / "WinDivert64.sys"
DLL_PATH = DRIVER_DIR / "WinDivert.dll"

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": False,
    "campus_interface": "auto",
    "usb_interface": "auto",
    "usb_missing_action": "reject",
    "usb_missing_fallback": False,
    "plugin_compat": False,
    "ipv6": True,
    "unknown_policy": "usb",
    "domestic_precedence": True,
    "encrypted_tcp": [443, 853, 8443],
    "encrypted_udp": [443, 784, 8853],
    "portal_url": "http://HOST/drcom/login",
    "poll_seconds": 60,
    "autostart": True,
}

try:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    RULES_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=str(LOG_PATH), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
except Exception:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _run_powershell(script: str, timeout: float = 15) -> subprocess.CompletedProcess[str]:
    """Run a fixed PowerShell operation and never interpolate credentials."""
    return subprocess.run(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, timeout=timeout, check=False,
    )


def _harden_file(path: Path) -> None:
    """Restrict ProgramData secrets to SYSTEM, Administrators and the owner."""
    if os.name != "nt" or not path.exists():
        return
    try:
        # Keep the current user able to run the tray client while removing
        # inherited read/write access for the Users group.
        _run_powershell(
            f"$p={json.dumps(str(path))}; icacls.exe $p /inheritance:r /grant:r '*S-1-5-18:(F)' '*S-1-5-32-544:(F)' '*S-1-5-32-545:(R)' | Out-Null",
            timeout=8,
        )
    except Exception:
        logging.exception("ACL hardening failed for %s", path)


def snapshot_system_state() -> dict[str, Any]:
    """Save firewall and route state before installation or a rollback."""
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"ok": True, "firewall": str(FIREWALL_SNAPSHOT), "routes": str(ROUTE_SNAPSHOT)}
    if os.name != "nt":
        result["ok"] = False
        result["error"] = "Windows is required for system snapshots"
        return result
    try:
        fw = _run_powershell(f"netsh.exe advfirewall export {json.dumps(str(FIREWALL_SNAPSHOT))}", timeout=20)
        result["firewall_exit"] = fw.returncode
        if fw.returncode != 0:
            result["ok"] = False
        route_script = (
            "Get-NetRoute -AddressFamily IPv4,IPv6 -ErrorAction SilentlyContinue | "
            "Where-Object { $_.PolicyStore -ne 'ActiveStore' -or $_.RouteMetric -ge 0 } | "
            "Select-Object DestinationPrefix,NextHop,InterfaceIndex,RouteMetric,AddressFamily,PolicyStore | "
            "ConvertTo-Json -Depth 5"
        )
        routes = _run_powershell(route_script, timeout=20)
        if routes.returncode == 0 and routes.stdout.strip():
            _atomic_write(ROUTE_SNAPSHOT, routes.stdout.encode("utf-8"))
        else:
            result["ok"] = False
            result["route_error"] = routes.stderr.strip()[:240]
        _harden_file(FIREWALL_SNAPSHOT)
        _harden_file(ROUTE_SNAPSHOT)
    except Exception as exc:
        result["ok"] = False
        result["error"] = str(exc)
    return result


def restore_system_state() -> dict[str, Any]:
    """Best-effort restore of the pre-install firewall/routes snapshot."""
    result: dict[str, Any] = {"ok": True, "firewall_restored": False, "routes_restored": 0}
    if os.name != "nt":
        result.update(ok=False, error="Windows is required for system restore")
        return result
    try:
        if FIREWALL_SNAPSHOT.exists():
            fw = _run_powershell(f"netsh.exe advfirewall import {json.dumps(str(FIREWALL_SNAPSHOT))}", timeout=20)
            result["firewall_restored"] = fw.returncode == 0
            if fw.returncode != 0:
                result["ok"] = False
        if ROUTE_SNAPSHOT.exists():
            data = json.loads(ROUTE_SNAPSHOT.read_text(encoding="utf-8"))
            entries = data if isinstance(data, list) else [data]
            restored = 0
            # Routes are recreated only when absent; this avoids deleting VPN or
            # administrator-managed routes added after installation.
            for route in entries:
                if not isinstance(route, dict):
                    continue
                prefix = str(route.get("DestinationPrefix") or "")
                nexthop = str(route.get("NextHop") or "")
                index = int(route.get("InterfaceIndex") or 0)
                metric = int(route.get("RouteMetric") or 0)
                family = int(route.get("AddressFamily") or 0)
                if not prefix or not index or family not in (2, 23):
                    continue
                ps = (
                    "$r=Get-NetRoute -DestinationPrefix {p} -InterfaceIndex {i} "
                    "-AddressFamily {af} -ErrorAction SilentlyContinue; "
                    "if(-not $r){{New-NetRoute -DestinationPrefix {p} -NextHop {g} "
                    "-InterfaceIndex {i} -RouteMetric {m} -PolicyStore ActiveStore "
                    "-ErrorAction SilentlyContinue | Out-Null; exit 0}}; exit 1"
                ).format(
                    p=json.dumps(prefix), g=json.dumps(nexthop), i=index, m=max(0, metric),
                    af="IPv4" if family == 2 else "IPv6",
                )
                if _run_powershell(ps, timeout=8).returncode == 0:
                    restored += 1
            result["routes_restored"] = restored
    except Exception as exc:
        result["ok"] = False
        result["error"] = str(exc)
    return result


def _json_dump(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _valid_port_list(value: Any, fallback: list[int]) -> list[int]:
    if not isinstance(value, list):
        return list(fallback)
    out: list[int] = []
    for item in value:
        try:
            port = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= port <= 65535 and port not in out:
            out.append(port)
    return out or list(fallback)


def load_config() -> dict[str, Any]:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        _atomic_write(CONFIG_PATH, _json_dump(DEFAULT_CONFIG))
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cfg = {**DEFAULT_CONFIG, **raw} if isinstance(raw, dict) else dict(DEFAULT_CONFIG)
    except Exception:
        logging.exception("configuration parse failed; using defaults")
        cfg = dict(DEFAULT_CONFIG)
    cfg["encrypted_tcp"] = _valid_port_list(cfg.get("encrypted_tcp"), DEFAULT_CONFIG["encrypted_tcp"])
    cfg["encrypted_udp"] = _valid_port_list(cfg.get("encrypted_udp"), DEFAULT_CONFIG["encrypted_udp"])
    cfg["enabled"] = bool(cfg.get("enabled"))
    cfg["ipv6"] = bool(cfg.get("ipv6", True))
    cfg["usb_missing_fallback"] = bool(cfg.get("usb_missing_fallback", False))
    cfg["plugin_compat"] = bool(cfg.get("plugin_compat", False))
    cfg["domestic_precedence"] = bool(cfg.get("domestic_precedence", True))
    if cfg.get("unknown_policy") not in {"usb", "campus", "reject"}:
        cfg["unknown_policy"] = "usb"
    try:
        cfg["poll_seconds"] = max(15, min(3600, int(cfg.get("poll_seconds", 60))))
    except (TypeError, ValueError):
        cfg["poll_seconds"] = 60
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    _atomic_write(CONFIG_PATH, _json_dump(cfg))
    _harden_file(CONFIG_PATH)


def _ipc_authkey() -> bytes:
    try:
        token = IPC_TOKEN_PATH.read_bytes()
        if len(token) >= 16:
            _harden_file(IPC_TOKEN_PATH)
            return token
    except OSError:
        pass
    token = secrets.token_bytes(32)
    try:
        _atomic_write(IPC_TOKEN_PATH, token)
        _harden_file(IPC_TOKEN_PATH)
    except OSError:
        pass
    return token


class CredentialManager:
    """ctypes wrapper; the password never enters config or logs."""

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wt.DWORD), ("Type", wt.DWORD), ("TargetName", wt.LPWSTR),
            ("Comment", wt.LPWSTR), ("LastWritten", wt.FILETIME),
            ("CredentialBlobSize", wt.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wt.DWORD), ("AttributeCount", wt.DWORD),
            ("Attributes", ctypes.c_void_p), ("TargetAlias", wt.LPWSTR),
            ("UserName", wt.LPWSTR),
        ]

    def __init__(self, target: str = "CampusRoute/DrCOM"):
        self.target = target
        self.advapi = ctypes.WinDLL("advapi32", use_last_error=True) if os.name == "nt" else None
        if self.advapi:
            self.advapi.CredWriteW.argtypes = [ctypes.POINTER(self.CREDENTIAL), wt.DWORD]
            self.advapi.CredWriteW.restype = wt.BOOL
            self.advapi.CredReadW.argtypes = [wt.LPWSTR, wt.DWORD, wt.DWORD, ctypes.POINTER(ctypes.POINTER(self.CREDENTIAL))]
            self.advapi.CredReadW.restype = wt.BOOL
            self.advapi.CredFree.argtypes = [ctypes.c_void_p]
            self.advapi.CredDeleteW.argtypes = [wt.LPWSTR, wt.DWORD, wt.DWORD]

    def write(self, username: str, password: str) -> bool:
        if not self.advapi or not username or not password:
            return False
        encoded = password.encode("utf-8")
        blob = ctypes.create_string_buffer(encoded)
        cred = self.CREDENTIAL()
        cred.Type = self.CRED_TYPE_GENERIC
        cred.TargetName = self.target
        cred.CredentialBlobSize = len(encoded)
        cred.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
        cred.Persist = self.CRED_PERSIST_LOCAL_MACHINE
        cred.UserName = username
        return bool(self.advapi.CredWriteW(ctypes.byref(cred), 0))

    def read(self) -> tuple[str, str]:
        if not self.advapi:
            return "", ""
        ptr = ctypes.POINTER(self.CREDENTIAL)()
        if not self.advapi.CredReadW(self.target, self.CRED_TYPE_GENERIC, 0, ctypes.byref(ptr)):
            return "", ""
        try:
            c = ptr.contents
            password = ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize).decode("utf-8", "replace") if c.CredentialBlob else ""
            return c.UserName or "", password
        finally:
            self.advapi.CredFree(ptr)

    def delete(self) -> bool:
        return bool(self.advapi and self.advapi.CredDeleteW(self.target, self.CRED_TYPE_GENERIC, 0))


@dataclass
class Interface:
    name: str
    index: int = 0
    gateway: str = ""
    online: bool = False
    metric: int = 0
    luid: str = ""
    description: str = ""
    kind: str = ""
    ipv6_gateway: str = ""


class InterfaceDiscovery:
    """Prefer interface index/LUID and default route over display-name guesses."""

    _USB_RE = re.compile(r"usb|rndis|tether|android|iphone|mobile|cellular|wwan|lte|5g", re.I)
    _VIRTUAL_RE = re.compile(r"vpn|virtual|hyper-v|docker|wsl|loopback|teredo|tap|tun", re.I)

    @staticmethod
    def _index_to_luid(index: int) -> str:
        if os.name != "nt" or not index:
            return ""
        try:
            value = ctypes.c_ulonglong()
            fn = ctypes.WinDLL("iphlpapi").ConvertInterfaceIndexToLuid
            fn.argtypes = [wt.ULONG, ctypes.POINTER(ctypes.c_ulonglong)]
            fn.restype = wt.ULONG
            if fn(index, ctypes.byref(value)) == 0:
                return f"0x{value.value:016x}"
        except Exception:
            pass
        return ""

    @staticmethod
    def _ps_json() -> Any:
        if os.name != "nt":
            return []
        script = r"""
$a = Get-NetAdapter -IncludeHidden -ErrorAction SilentlyContinue
$out = foreach ($x in $a) {
  $c = Get-NetIPConfiguration -InterfaceIndex $x.ifIndex -ErrorAction SilentlyContinue
  $g = $c.IPv4DefaultGateway | Select-Object -First 1
  $g6 = $c.IPv6DefaultGateway | Select-Object -First 1
  [pscustomobject]@{
    Name=$x.Name; InterfaceIndex=$x.ifIndex; Status=[string]$x.Status
    Description=$x.InterfaceDescription; HardwareInterface=$x.HardwareInterface
    MediaType=[string]$x.MediaType; PhysicalMediaType=[string]$x.PhysicalMediaType
    InterfaceGuid=[string]$x.InterfaceGuid; Gateway=if($g){$g.NextHop}else{''}
    Gateway6=if($g6){$g6.NextHop}else{''}; InterfaceMetric=if($c.NetProfile){$c.NetProfile.InterfaceMetric}else{0}
  }
}
$out | ConvertTo-Json -Depth 4
"""
        try:
            p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True, timeout=10)
            data = json.loads(p.stdout or "[]")
            return [data] if isinstance(data, dict) else data
        except Exception as exc:
            logging.warning("interface discovery failed: %s", exc)
            return []

    def list(self) -> list[Interface]:
        result: list[Interface] = []
        for row in self._ps_json():
            try:
                index = int(row.get("InterfaceIndex") or 0)
            except (TypeError, ValueError):
                index = 0
            text = " ".join(str(row.get(k) or "") for k in ("Name", "Description", "MediaType", "PhysicalMediaType"))
            is_usb = bool(self._USB_RE.search(text))
            is_virtual = bool(self._VIRTUAL_RE.search(text))
            kind = "usb" if is_usb else ("virtual" if is_virtual else "campus")
            status = str(row.get("Status") or "").lower()
            gateway = str(row.get("Gateway") or "")
            gateway6 = str(row.get("Gateway6") or "")
            try:
                metric = int(row.get("InterfaceMetric") or 0)
            except (TypeError, ValueError):
                metric = 0
            result.append(Interface(str(row.get("Name") or ""), index, gateway,
                                    bool(gateway and status in {"up", "connected"}), metric,
                                    self._index_to_luid(index), str(row.get("Description") or ""),
                                    kind, gateway6))
        return result

    def choose(self, configured: Any, usb: bool = False) -> Interface:
        items = self.list()
        selected = str(configured or "auto")
        if selected.lower() != "auto":
            for item in items:
                if selected.lower() in {item.name.lower(), str(item.index), item.luid.lower(), f"luid:{item.luid.lower()}"}:
                    return item
            return Interface(selected, kind="usb" if usb else "campus")
        candidates = [i for i in items if i.online and i.kind == ("usb" if usb else "campus")]
        if not candidates and not usb:
            candidates = [i for i in items if i.online and i.kind != "virtual"]
        if not candidates:
            candidates = [i for i in items if i.kind == ("usb" if usb else "campus")]
        candidates.sort(key=lambda i: (i.metric or 999999, i.index))
        return candidates[0] if candidates else Interface("auto", kind="usb" if usb else "campus")

    def best_route(self, destination: str) -> Interface:
        # Native callers can use IP Helper GetBestRoute2; this deterministic
        # fallback exposes the same index/LUID result to the Python service.
        items = [i for i in self.list() if i.online]
        return sorted(items, key=lambda i: (i.metric or 999999, i.index))[0] if items else Interface("auto")


class PortalClient:
    def __init__(self, url: str):
        self.url = url

    @staticmethod
    def _result(body: str) -> bool:
        match = re.search(r"\{.*\}", body, re.S)
        if match:
            try:
                if str(json.loads(match.group(0)).get("result")) == "1":
                    return True
            except Exception:
                pass
        return bool(re.search(r"(?:result|res)\s*[=:]\s*['\"]?1\b", body, re.I))

    def login(self, username: str, password: str) -> tuple[bool, str]:
        if not username or not password:
            return False, "missing credentials"
        query = {"callback": "dr1003", "DDDDD": username, "upass": password, "0MKKey": "123456",
                 "R1": "0", "R2": "", "R3": "0", "R6": "1", "para": "00", "v6ip": "",
                 "terminal_type": "2", "lang": "zh-cn", "jsVersion": "4.2.1", "v": "1224"}
        try:
            request = urllib.request.Request(self.url + "?" + urllib.parse.urlencode(query), headers={"Cache-Control": "no-cache"})
            with urllib.request.urlopen(request, timeout=8) as response:
                body = response.read(4096).decode("utf-8", "ignore")
            return self._result(body), body[:160]
        except Exception as exc:
            return False, str(exc)

    def status(self) -> tuple[bool, str]:
        try:
            base = self.url.rsplit("/", 1)[0]
            request = urllib.request.Request(base + "/chkstatus?callback=dr1003", headers={"Cache-Control": "no-cache"})
            with urllib.request.urlopen(request, timeout=5) as response:
                body = response.read(2048).decode("utf-8", "ignore")
            return self._result(body), body[:160]
        except Exception as exc:
            return False, str(exc)


def _parse_packet(packet: bytes) -> tuple[str, str, int] | None:
    if not packet:
        return None
    version = packet[0] >> 4
    try:
        if version == 4 and len(packet) >= 20:
            header_len = (packet[0] & 0x0F) * 4
            proto_num = packet[9]
            dst = str(ipaddress.IPv4Address(packet[16:20]))
            proto = {6: "tcp", 17: "udp"}.get(proto_num, str(proto_num))
            port = int.from_bytes(packet[header_len + 2:header_len + 4], "big") if proto_num in (6, 17) and len(packet) >= header_len + 4 else 0
            return dst, proto, port
        if version == 6 and len(packet) >= 40:
            next_header = packet[6]
            offset = 40
            # Walk common IPv6 extension headers so encrypted TCP/UDP rules
            # also cover QUIC and networks that insert a Fragment/Routing
            # header before the transport header.
            for _ in range(8):
                if next_header in (0, 43, 60):  # Hop-by-hop/Routing/Destination
                    if len(packet) < offset + 2:
                        break
                    hdr_len = (packet[offset + 1] + 1) * 8
                    next_header = packet[offset]
                    offset += hdr_len
                    continue
                if next_header == 44:  # Fragment header
                    if len(packet) < offset + 8:
                        break
                    next_header = packet[offset]
                    offset += 8
                    continue
                if next_header in (50, 51):  # ESP/AH; ports are unavailable
                    break
                break
            dst = str(ipaddress.IPv6Address(packet[24:40]))
            proto = {6: "tcp", 17: "udp"}.get(next_header, str(next_header))
            port = int.from_bytes(packet[offset + 2:offset + 4], "big") if next_header in (6, 17) and len(packet) >= offset + 4 else 0
            return dst, proto, port
    except (ValueError, IndexError):
        return None
    return None


class WinDivertBackend:
    """WinDivert network-layer ctypes backend with packet reinjection."""

    IFIDX_OFFSET = 16  # WINDIVERT_ADDRESS.IfIdx for network-layer captures

    def __init__(self, driver_path: Path | None = None, dll_path: Path | None = None):
        self.driver_path = Path(driver_path or DRIVER_PATH)
        self.dll_path = Path(dll_path or DLL_PATH)
        self.available = self.driver_path.exists() and self.dll_path.exists() and os.name == "nt"
        self.running = False
        self.handle: Optional[int] = None
        self.dll: Any = None
        if self.available:
            try:
                self.dll = ctypes.WinDLL(str(self.dll_path))
                self.dll.WinDivertOpen.argtypes = [ctypes.c_char_p, wt.UINT, ctypes.c_short, wt.UINT]
                self.dll.WinDivertOpen.restype = ctypes.c_void_p
                self.dll.WinDivertRecv.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.UINT, ctypes.POINTER(wt.UINT), ctypes.c_void_p]
                self.dll.WinDivertRecv.restype = wt.BOOL
                self.dll.WinDivertSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.UINT, ctypes.POINTER(wt.UINT), ctypes.c_void_p]
                self.dll.WinDivertSend.restype = wt.BOOL
                self.dll.WinDivertClose.argtypes = [ctypes.c_void_p]
                self.dll.WinDivertHelperCalcChecksums.argtypes = [ctypes.c_void_p, wt.UINT, wt.UINT]
            except Exception:
                logging.exception("WinDivert DLL load failed (FAIL-CLOSED)")
                self.available = False

    def start(self, filter_expr: str = "outbound and !loopback") -> bool:
        if not self.available or not self.dll:
            logging.error("FAIL-CLOSED: signed WinDivert payload missing or not loadable")
            return False
        try:
            self.handle = int(self.dll.WinDivertOpen(filter_expr.encode("ascii"), 0, 0, 0) or 0)
            self.running = bool(self.handle)
            if not self.running:
                logging.error("WinDivertOpen failed (FAIL-CLOSED), winerror=%s", ctypes.get_last_error())
            return self.running
        except Exception:
            logging.exception("WinDivertOpen failed (FAIL-CLOSED)")
            return False

    def stop(self) -> None:
        if self.handle and self.dll:
            try:
                self.dll.WinDivertClose(ctypes.c_void_p(self.handle))
            except Exception:
                logging.exception("WinDivertClose failed")
        self.handle = None
        self.running = False

    def recv(self, max_len: int = 65535) -> tuple[bytes, ctypes.Array[Any]] | None:
        if not self.running or not self.dll or not self.handle:
            return None
        packet = (ctypes.c_ubyte * max_len)()
        address = (ctypes.c_ubyte * 64)()
        length = wt.UINT(0)
        try:
            if self.dll.WinDivertRecv(ctypes.c_void_p(self.handle), packet, max_len, ctypes.byref(length), address):
                return bytes(packet[:length.value]), address
        except Exception:
            logging.exception("WinDivertRecv failed")
        return None

    def send(self, packet: bytes, address: ctypes.Array[Any], if_index: int = 0) -> bool:
        if not self.running or not self.dll or not self.handle:
            return False
        if if_index:
            address[self.IFIDX_OFFSET:self.IFIDX_OFFSET + 4] = int(if_index).to_bytes(4, "little")
        buffer = ctypes.create_string_buffer(packet)
        length = wt.UINT(0)
        try:
            self.dll.WinDivertHelperCalcChecksums(buffer, len(packet), 0)
            return bool(self.dll.WinDivertSend(ctypes.c_void_p(self.handle), buffer, len(packet), ctypes.byref(length), address))
        except Exception:
            logging.exception("WinDivertSend failed")
            return False

    def packet_loop(self, engine: "PolicyEngine", stop_event: threading.Event) -> None:
        while self.running and not stop_event.is_set():
            item = self.recv()
            if not item:
                continue
            packet, address = item
            parsed = _parse_packet(packet)
            if not parsed:
                iface = engine.campus
                if iface and iface.online and self.send(packet, address, iface.index):
                    continue
                logging.error("dropping non-IP packet: campus interface unavailable")
                continue
            dst, proto, port = parsed
            decision = engine.decide(dst, proto, port)
            if decision == "reject":
                continue
            iface = engine.campus if decision == "campus" else engine.usb
            if not iface or not iface.online or not self.send(packet, address, iface.index):
                logging.error("dropping packet: decision=%s interface unavailable", decision)


class PolicyEngine:
    def __init__(self, config: dict[str, Any], backend: WinDivertBackend | None = None,
                 discover: InterfaceDiscovery | None = None):
        self.config = config
        self.discover = discover or InterfaceDiscovery()
        self.backend = backend or WinDivertBackend()
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.packet_thread: Optional[threading.Thread] = None
        self.last: dict[str, Any] = {}
        self.campus: Interface | None = None
        self.usb: Interface | None = None
        self._network_signature: tuple[tuple[str, int, int], ...] = ()
        self._networks: list[ipaddress._BaseNetwork] = []

    def _record_state(self, value: dict[str, Any]) -> None:
        self.last = dict(value)
        try:
            _atomic_write(STATE_PATH, _json_dump(self.last))
            _harden_file(STATE_PATH)
        except Exception:
            logging.exception("state write failed")

    @staticmethod
    def _network_files() -> Iterable[Path]:
        for path in (CN4_PATH, CN6_PATH, RULES_PATH):
            if path.exists():
                yield path

    def domestic(self, ip: str) -> bool:
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            return False
        if address.is_private or address.is_loopback or address.is_link_local or address.is_unspecified:
            return True
        signature: list[tuple[str, int, int]] = []
        for path in self._network_files():
            try:
                stat = path.stat()
                signature.append((str(path), stat.st_mtime_ns, stat.st_size))
            except OSError:
                signature.append((str(path), 0, 0))
        sig = tuple(signature)
        if sig != self._network_signature:
            networks: list[ipaddress._BaseNetwork] = []
            for path in self._network_files():
                try:
                    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                        line = line.split("#", 1)[0].strip()
                        if not line:
                            continue
                        try:
                            networks.append(ipaddress.ip_network(line, strict=False))
                        except ValueError:
                            continue
                except OSError:
                    continue
            self._networks = networks
            self._network_signature = sig
        return any(address.version == net.version and address in net for net in self._networks)

    def usb_online(self) -> bool:
        # Packet classification runs for every outbound packet; use the last
        # reconciled adapter state instead of spawning PowerShell per packet.
        if self.usb is not None:
            return bool(self.usb.online)
        return bool(self.discover.choose(self.config.get("usb_interface", "auto"), True).online)

    def decide(self, dst: str, proto: str = "tcp", port: int = 0) -> str:
        is_v6 = ":" in dst
        if is_v6 and not self.config.get("ipv6", True):
            try:
                if not ipaddress.ip_address(dst).is_private:
                    return "reject"
            except ValueError:
                return "reject"
        if self.config.get("domestic_precedence", True) and self.domestic(dst):
            return "campus"
        proto = str(proto).lower()
        if proto == "tcp":
            encrypted_ports = self.config.get("encrypted_tcp", [])
        elif proto == "udp":
            encrypted_ports = self.config.get("encrypted_udp", [])
        else:
            encrypted_ports = []
        encrypted = int(port or 0) in {int(p) for p in encrypted_ports}
        policy = self.config.get("unknown_policy", "usb")
        target = "usb" if encrypted or policy == "usb" else policy
        if target == "usb" and not self.usb_online():
            return "campus" if self.config.get("usb_missing_fallback", False) else "reject"
        return target if target in {"campus", "usb", "reject"} else "reject"

    def _firewall(self, enable: bool, campus_alias: str = "") -> None:
        if os.name != "nt":
            return
        # The panic rule is deliberately broad: if WinDivert cannot open,
        # blocking public egress is safer than allowing traffic to leak over
        # the campus default route.  It is disabled again as soon as the
        # packet backend is active or the feature is stopped.
        block = "True" if enable else "False"
        script = (
            "$b=Get-NetFirewallRule -DisplayName 'CampusRoute Panic Block' -ErrorAction SilentlyContinue; "
            "if(-not $b){New-NetFirewallRule -DisplayName 'CampusRoute Panic Block' -Direction Outbound "
            "-Action Block -Profile Any -Protocol Any -RemoteAddress Any -Enabled False | Out-Null}; "
            f"Set-NetFirewallRule -DisplayName 'CampusRoute Panic Block' -Enabled {block}"
        )
        try:
            _run_powershell(script, timeout=10)
        except Exception:
            logging.exception("panic firewall update failed")

    def apply(self) -> dict[str, Any]:
        with self.lock:
            if not self.config.get("enabled", False):
                self.backend.stop()
                self.stop_event.set()
                self._firewall(False)
                value = {"ok": True, "enabled": False, "backend": "stopped", "fail_closed": False}
                self._record_state(value)
                return dict(value)
            self.stop_event.clear()
            self.campus = self.discover.choose(self.config.get("campus_interface", "auto"), False)
            self.usb = self.discover.choose(self.config.get("usb_interface", "auto"), True)
            started = self.backend.start()
            if started and (not self.packet_thread or not self.packet_thread.is_alive()):
                self.packet_thread = threading.Thread(target=self.backend.packet_loop, args=(self, self.stop_event), daemon=True)
                self.packet_thread.start()
            fail_closed = not started
            self._firewall(fail_closed, self.campus.name if self.campus else "")
            value = {
                "ok": True, "enabled": True, "backend": "active" if started else "placeholder",
                "fail_closed": fail_closed, "campus": asdict(self.campus), "usb": asdict(self.usb),
                "usb_online": bool(self.usb.online), "route_plan": self.route_plan(),
            }
            self._record_state(value)
            return dict(value)

    def route_plan(self) -> list[dict[str, Any]]:
        plan: list[dict[str, Any]] = []
        if self.campus and self.campus.gateway:
            plan.append({"op": "route-campus", "interface_index": self.campus.index, "luid": self.campus.luid})
        if self.usb and self.usb.online and self.usb.gateway:
            plan.append({"op": "route-usb", "interface_index": self.usb.index, "luid": self.usb.luid})
        if self.usb and not self.usb.online and not self.config.get("usb_missing_fallback", False):
            plan.append({"op": "reject-usb-selected", "reason": "usb-offline"})
        return plan


class Service:
    ALLOWED_CONFIG = set(DEFAULT_CONFIG)

    def __init__(self):
        self.config = load_config()
        self.engine = PolicyEngine(self.config)
        self.credentials = CredentialManager()
        self.username, self.password = self.credentials.read()
        self.stop_event = threading.Event()

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict):
            return {"ok": False, "error": "invalid request"}
        command = request.get("cmd")
        if command == "status":
            if self.engine.last:
                return {"ok": True, **self.engine.last}
            try:
                return {"ok": True, **json.loads(STATE_PATH.read_text(encoding="utf-8"))}
            except Exception:
                return {"ok": True, "enabled": bool(self.config.get("enabled")), "backend": "not-started"}
        if command == "snapshot":
            return snapshot_system_state()
        if command == "rollback":
            self.config["enabled"] = False
            save_config(self.config)
            self.engine.config = self.config
            self.engine.apply()
            return restore_system_state()
        if command in {"apply", "start", "stop"}:
            if command == "start":
                self.config["enabled"] = True
            elif command == "stop":
                self.config["enabled"] = False
            save_config(self.config)
            self.engine.config = self.config
            return self.engine.apply()
        if command == "login":
            self.username, self.password = self.credentials.read()
            ok, message = PortalClient(str(self.config.get("portal_url", DEFAULT_CONFIG["portal_url"]))).login(self.username, self.password)
            return {"ok": ok, "message": message}
        if command == "set_credentials":
            username = str(request.get("username") or "").strip()
            password = str(request.get("password") or "")
            ok = self.credentials.write(username, password)
            if ok:
                self.username, self.password = username, password
            return {"ok": ok, "message": "credentials stored in Windows Credential Manager" if ok else "credential write failed"}
        if command == "config":
            values = request.get("values") if isinstance(request.get("values"), dict) else {}
            for key, value in values.items():
                if key in self.ALLOWED_CONFIG:
                    self.config[key] = value
            self.config = {**load_config(), **{k: self.config[k] for k in self.config if k in self.ALLOWED_CONFIG}}
            save_config(self.config)
            self.engine.config = self.config
            return self.engine.apply()
        return {"ok": False, "error": "unknown command"}

    def _serve(self) -> None:
        authkey = _ipc_authkey()
        while not self.stop_event.is_set():
            try:
                listener = Listener(PIPE_NAME, family="AF_PIPE", authkey=authkey)
                with listener:
                    while not self.stop_event.is_set():
                        conn = listener.accept()
                        try:
                            conn.send(self.handle(conn.recv()))
                        except Exception:
                            logging.exception("named-pipe request failed")
                        finally:
                            conn.close()
            except Exception as exc:
                logging.warning("named-pipe listener: %s", exc)
                time.sleep(2)

    def run(self) -> None:
        self.engine.apply()
        threading.Thread(target=self._serve, daemon=True).start()
        try:
            while not self.stop_event.wait(float(self.config.get("poll_seconds", 60))):
                try:
                    self.username, self.password = self.credentials.read()
                    portal = PortalClient(str(self.config.get("portal_url", DEFAULT_CONFIG["portal_url"])))
                    online, _ = portal.status()
                    if not online and self.username and self.password:
                        portal.login(self.username, self.password)
                    self.engine.apply()
                except Exception:
                    logging.exception("keepalive iteration failed")
        finally:
            self.engine.backend.stop()
            self.engine._firewall(False)


class PipeClient:
    @staticmethod
    def call(request: dict[str, Any], timeout: float = 8) -> dict[str, Any]:
        conn = Client(PIPE_NAME, family="AF_PIPE", authkey=_ipc_authkey())
        try:
            conn.send(request)
            return conn.recv()
        finally:
            conn.close()


def _tray_icon(root: Any) -> Any:
    try:
        import pystray  # type: ignore
        from PIL import Image, ImageDraw  # type: ignore
        image = Image.new("RGB", (64, 64), "#1f6feb")
        ImageDraw.Draw(image).text((17, 18), "CR", fill="white")
        icon = pystray.Icon(APP_NAME, image, APP_NAME,
                            pystray.Menu(pystray.MenuItem("显示", lambda *_: root.after(0, root.deiconify)),
                                         pystray.MenuItem("退出", lambda *_: root.after(0, root.destroy))))
        threading.Thread(target=icon.run, daemon=True).start()
        return icon
    except Exception:
        return None


def run_gui(start_hidden: bool = False) -> None:
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("CampusRoute")
    root.geometry("700x540")
    config = load_config()
    status_var = tk.StringVar(value="正在连接服务…")
    ttk.Label(root, text="校园网 / USB 双出口策略", font=("Segoe UI", 16, "bold")).pack(pady=12)
    ttk.Label(root, textvariable=status_var, justify="left").pack(fill="x", padx=20, pady=6)
    form = ttk.Frame(root); form.pack(fill="x", padx=20, pady=4)
    enabled = tk.BooleanVar(value=bool(config.get("enabled")))
    fallback = tk.BooleanVar(value=bool(config.get("usb_missing_fallback")))
    compat = tk.BooleanVar(value=bool(config.get("plugin_compat")))
    ipv6 = tk.BooleanVar(value=bool(config.get("ipv6", True)))
    ttk.Checkbutton(form, text="启用策略（首次关闭）", variable=enabled).grid(row=0, column=0, sticky="w")
    ttk.Checkbutton(form, text="USB 缺失时回退校园网", variable=fallback).grid(row=1, column=0, sticky="w")
    ttk.Checkbutton(form, text="OpenClash/Passwall 兼容", variable=compat).grid(row=2, column=0, sticky="w")
    ttk.Checkbutton(form, text="IPv6", variable=ipv6).grid(row=3, column=0, sticky="w")
    ttk.Label(form, text="校园网接口（auto/名称/索引/LUID）").grid(row=0, column=1, sticky="e", padx=8)
    campus_entry = ttk.Entry(form, width=24); campus_entry.insert(0, str(config.get("campus_interface", "auto"))); campus_entry.grid(row=0, column=2)
    ttk.Label(form, text="USB 接口（auto/名称/索引/LUID）").grid(row=1, column=1, sticky="e", padx=8)
    usb_entry = ttk.Entry(form, width=24); usb_entry.insert(0, str(config.get("usb_interface", "auto"))); usb_entry.grid(row=1, column=2)
    ttk.Label(form, text="认证账号").grid(row=4, column=1, sticky="e", padx=8)
    user_entry = ttk.Entry(form, width=24); user_entry.grid(row=4, column=2)
    ttk.Label(form, text="认证密码").grid(row=5, column=1, sticky="e", padx=8)
    pass_entry = ttk.Entry(form, width=24, show="•"); pass_entry.grid(row=5, column=2)
    ttk.Label(form, text="门户登录 URL").grid(row=6, column=1, sticky="e", padx=8)
    portal_entry = ttk.Entry(form, width=36); portal_entry.insert(0, str(config.get("portal_url", DEFAULT_CONFIG["portal_url"]))); portal_entry.grid(row=6, column=2, columnspan=2, sticky="w")
    output = tk.Text(root, height=14, width=84, state="disabled"); output.pack(fill="both", expand=True, padx=20, pady=10)

    def show(value: Any) -> None:
        text = json.dumps(value, ensure_ascii=False, indent=2)
        status_var.set(text)
        output.configure(state="normal"); output.delete("1.0", "end"); output.insert("end", text); output.configure(state="disabled")

    def call(command: str, values: Optional[dict[str, Any]] = None) -> None:
        try:
            request = {"cmd": command}
            if values is not None:
                request["values"] = values
            show(PipeClient.call(request))
        except Exception as exc:
            show({"ok": False, "error": str(exc)})

    def apply_config() -> None:
        call("config", {"enabled": enabled.get(), "usb_missing_fallback": fallback.get(), "plugin_compat": compat.get(),
                         "ipv6": ipv6.get(), "campus_interface": campus_entry.get().strip() or "auto",
                         "usb_interface": usb_entry.get().strip() or "auto",
                         "portal_url": portal_entry.get().strip() or DEFAULT_CONFIG["portal_url"]})

    buttons = ttk.Frame(root); buttons.pack(pady=4)
    ttk.Button(buttons, text="应用", command=apply_config).grid(row=0, column=0, padx=4)
    ttk.Button(buttons, text="启动", command=lambda: call("start")).grid(row=0, column=1, padx=4)
    ttk.Button(buttons, text="停止", command=lambda: call("stop")).grid(row=0, column=2, padx=4)
    ttk.Button(buttons, text="登录/保活", command=lambda: call("login")).grid(row=0, column=3, padx=4)
    ttk.Button(buttons, text="保存凭据", command=lambda: call("set_credentials", {"username": user_entry.get(), "password": pass_entry.get()})).grid(row=0, column=4, padx=4)
    ttk.Button(buttons, text="刷新状态", command=lambda: call("status")).grid(row=0, column=5, padx=4)
    ttk.Button(buttons, text="保存快照", command=lambda: call("snapshot")).grid(row=1, column=0, padx=4, pady=4)
    ttk.Button(buttons, text="回滚", command=lambda: call("rollback")).grid(row=1, column=1, padx=4, pady=4)
    tray = _tray_icon(root)
    root.protocol("WM_DELETE_WINDOW", lambda: root.withdraw() if tray else root.destroy())
    call("status")
    if start_hidden and tray:
        root.withdraw()
    root.mainloop()


def run_as_windows_service() -> None:
    """Register the worker with SCM; fall back to console mode when run manually."""
    service = Service()
    if os.name != "nt":
        service.run()
        return
    try:
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        SERVICE_MAIN = ctypes.WINFUNCTYPE(None, wt.DWORD, ctypes.POINTER(wt.LPWSTR))
        HANDLER_EX = ctypes.WINFUNCTYPE(wt.DWORD, wt.DWORD, wt.DWORD, wt.LPVOID, wt.LPVOID)

        class SERVICE_STATUS(ctypes.Structure):
            _fields_ = [
                ("dwServiceType", wt.DWORD), ("dwCurrentState", wt.DWORD),
                ("dwControlsAccepted", wt.DWORD), ("dwWin32ExitCode", wt.DWORD),
                ("dwServiceSpecificExitCode", wt.DWORD), ("dwCheckPoint", wt.DWORD),
                ("dwWaitHint", wt.DWORD),
            ]

        class SERVICE_TABLE_ENTRY(ctypes.Structure):
            _fields_ = [("lpServiceName", wt.LPWSTR), ("lpServiceProc", SERVICE_MAIN)]

        advapi.RegisterServiceCtrlHandlerExW.argtypes = [wt.LPWSTR, HANDLER_EX, wt.LPVOID]
        advapi.RegisterServiceCtrlHandlerExW.restype = wt.LPVOID
        advapi.SetServiceStatus.argtypes = [wt.LPVOID, ctypes.POINTER(SERVICE_STATUS)]
        advapi.SetServiceStatus.restype = wt.BOOL
        advapi.StartServiceCtrlDispatcherW.argtypes = [ctypes.POINTER(SERVICE_TABLE_ENTRY)]
        advapi.StartServiceCtrlDispatcherW.restype = wt.BOOL

        status_handle = ctypes.c_void_p()

        def publish(state: int, code: int = 0, checkpoint: int = 0) -> None:
            status = SERVICE_STATUS(0x00000010, state, 0x00000005, code, 0, checkpoint, 5000)
            if status_handle:
                advapi.SetServiceStatus(status_handle, ctypes.byref(status))

        @HANDLER_EX
        def handler(control, _event_type, _event_data, _context):
            if control in (0x00000001, 0x00000005):  # STOP / SHUTDOWN
                service.stop_event.set()
                return 0
            return 0

        @SERVICE_MAIN
        def service_main(_argc, _argv):
            nonlocal status_handle
            status_handle = ctypes.c_void_p(advapi.RegisterServiceCtrlHandlerExW(SERVICE_NAME, handler, None))
            if not status_handle:
                return
            publish(0x00000002, checkpoint=1)  # START_PENDING
            publish(0x00000004)  # RUNNING
            try:
                service.run()
            except Exception:
                logging.exception("service worker crashed")
                publish(0x00000001, code=1)
                return
            publish(0x00000003)  # STOP_PENDING
            publish(0x00000001)  # STOPPED

        table = (SERVICE_TABLE_ENTRY * 2)()
        table[0].lpServiceName = SERVICE_NAME
        table[0].lpServiceProc = service_main
        table[1].lpServiceName = None
        table[1].lpServiceProc = SERVICE_MAIN()
        if advapi.StartServiceCtrlDispatcherW(table):
            return
        error = ctypes.get_last_error()
        if error == 1063:  # ERROR_FAILED_SERVICE_CONTROLLER_CONNECT
            service.run()
        else:
            raise OSError(error, "StartServiceCtrlDispatcherW failed")
    except Exception:
        logging.exception("SCM registration failed; running worker in console mode")
        service.run()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", action="store_true")
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--snapshot", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--minimized", action="store_true")
    parser.add_argument("--purge-credentials", action="store_true")
    args = parser.parse_args()
    if args.service:
        run_as_windows_service()
    elif args.snapshot:
        print(json.dumps(snapshot_system_state(), ensure_ascii=False, indent=2))
    elif args.rollback:
        try:
            result = PipeClient.call({"cmd": "rollback"})
        except Exception:
            result = restore_system_state()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.purge_credentials:
        print(json.dumps({"ok": CredentialManager().delete()}, ensure_ascii=False))
    elif args.status:
        try:
            print(json.dumps(PipeClient.call({"cmd": "status"}), ensure_ascii=False, indent=2))
        except Exception as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
    else:
        run_gui(start_hidden=args.minimized)


if __name__ == "__main__":
    main()
