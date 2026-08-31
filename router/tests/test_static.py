#!/usr/bin/env python3
"""Static validation for the staged QWRT Campus Route deliverable."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

def read(rel):
    p = ROOT / rel
    assert p.is_file(), f"missing {rel}"
    return p.read_text(encoding="utf-8")

cfg = read("etc/config/campus_route")
main = read("usr/bin/campus-route")
accel = read("usr/bin/campus-route-accel")
update = read("usr/bin/campus-route-update")
controller = read("usr/lib/lua/luci/controller/campus_route.lua")
cbi = read("usr/lib/lua/luci/model/cbi/campus_route/main.lua")
acl = read("usr/share/rpcd/acl.d/luci-app-campus-route.json")
init = read("etc/init.d/campus-route")
hotplug = read("etc/hotplug.d/iface/95-campus-route")
usb_hotplug = read("etc/hotplug.d/net/95-campus-usb")
installer = read("install.sh")
rollback = read("usr/bin/campus-route-rollback")
cron = read("etc/cron.d/campus-route")

# Config defaults are fail-closed and default-off.
for line in ("option enabled '0'", "option usb_missing_fallback '0'",
             "option plugin_compat '0'", "option ipv6 '1'",
             "option unknown_policy 'usb'", "option domestic_precedence '1'",
             "option usb_missing_action 'reject'", "option campus_failover '1'",
             "option campus_healthcheck '1'", "list campus_probe_host '223.5.5.5'",
             "option campus_probe_timeout '2'", "option campus_fail_threshold '1'",
             "option campus_recover_threshold '2'"):
    assert line in cfg, line
for line in ("option accel_enabled '0'", "option bandwidth_cap_mbps '500'",
             "option accel_trigger_percent '85'", "option accel_release_percent '75'",
             "option accel_max_usb_share_percent '50'", "option accel_step_percent '10'"):
    assert line in cfg, line
for line in ("list encrypted_tcp '443'", "list encrypted_udp '443'",
             "option campus_iface 'wan'", "option usb_iface_primary 'wanusb'",
             "option usb_iface_fallback 'wwan'", "option geosite_file",
             "option insecure_fetch '0'"):
    assert line in cfg, line

# Data-plane invariants.
for token in ("CAMPUS_ROUTE_MANGLE", "CAMPUS_ROUTE_FILTER", "campus_cn4",
              "campus_cn6", "MARK_CAMPUS=0x1000", "MARK_USB=0x2000",
             "MARK_BLOCK=0x3000", "--restore-mark", "--save-mark",
              "iptables-legacy", "ip6tables-legacy", "ipset", "REJECT",
              "usb_missing_fallback", "PLUGIN_COMPAT", "blackhole default",
              "--match-set", "multiport", "PREROUTING", "OUTPUT", "FORWARD",
              "USB_MISSING_ACTION", "USB_ONLINE", "CAMPUS_ONLINE", "CAMPUS_FAILOVER",
              "USB_ONLINE4", "USB_ONLINE6", "campus_probe", "FORCE_RECLASSIFY", "campus_target", "probe_failed",
              "probe_recovering", "probe_drcom_status", "CAMPUS_PORTAL_HOSTS"):
    assert token in main, token
assert "scope" in main.lower()
assert "DOMESTIC_PRECEDENCE" in main
for token in ("CAMPUS_ROUTE_ACCEL_SELECT", "CAMPUS_ROUTE_ACCEL_DOWN",
              "CAMPUS_ROUTE_ACCEL_UP", "CAMPUS_ROUTE_ACCEL_LOCAL",
              "CAMPUS_ROUTE_ACCEL_NEW", "CAMPUS_ROUTE_ACCEL_MOVED",
              "xt_statistic", "/usr/bin/campus-route reconcile"):
    assert token in (main + accel), token
assert "fwmark \"$MARK_CAMPUS/$MASK\"" in main
assert "fwmark \"$MARK_USB/$MASK\"" in main
assert "fwmark \"$MARK_BLOCK/$MASK\"" in main
# Health probes are installed after policy tables and before campus marks are
# remapped, so they remain a reliable campus-path test during failover.
assert "-d \"$host\" -j MARK --set-xmark \"$MARK_CAMPUS/$MASK\"" in main
assert main.index("CONNMARK --restore-mark") < main.index("-d \"$host\" -j MARK")
assert main.index("-d \"$host\" -j MARK") < main.index("if [ \"$campus_target\" != \"$MARK_CAMPUS\" ]")
assert "CONNMARK --set-xmark 0x0/\"$MASK\"" in main
assert "FORCE_RECLASSIFY=0" in main
assert "--interface \"$CAMPUS_DEV\"" in main
assert "CAMPUS_STATUS_PATH" in main and "CAMPUS_STATUS_CALLBACK" in main
force_start = main.index("if [ \"$FORCE_RECLASSIFY\" -eq 1 ]")
force_block = main[force_start:main.index("fi\n\t", force_start) + 4]
assert "--set-mark 0" not in force_block
assert "setup_routes ||" in main and "setup_firewall ||" in main and "update_campus_health" in main
reconcile_body = main[main.index("reconcile()") :]
assert reconcile_body.index("setup_routes ||") < reconcile_body.index("update_campus_health")
status_body = main[main.index("\nstatus() {") : main.index("daemon_loop()")]
assert "update_campus_health" not in status_body
assert "health_get state" in status_body

# Atomic updater and last-known-good behaviour.
for token in ("find_plugin_file", "uclient-fetch", "curl -fsSL", "wget -q",
              "sha256sum", "mv -f", "validation failed; keeping previous cache",
              "download failed; keeping previous cache", "geosite-cn.txt"):
    assert token in update, token
assert "insecure_fetch" in update
assert "cfg cn4_file" in update and "cfg cn6_file" in update and "cfg geosite_file" in update
assert "Plugin-generated plain files are the preferred source" in update
assert "Only consume textual GeoSite exports" in update
assert "Count only usable records" in update

# LuCI only exposes fixed verbs; no generic shell endpoint.
for token in ("action_status", "action_apply", "action_refresh", "action_start", "action_stop",
              "campus_route", "luci-app-campus-route"):
    assert token in controller or token in cbi or token in acl, token
for token in ('io.open("/etc/config/campus_route", "r")', "f:close()"):
    assert token in controller, token
assert "config_exists" not in controller
assert "nixio.fs.access" not in controller
assert "sys.call(cmd .." in controller
assert "campus-route" in init and "procd_set_param command" in init
assert "ifup" in hotplug and "ifdown" in hotplug and "ifupdate" in hotplug
assert 'usb0' in usb_hotplug and 'wanusb' in usb_hotplug and 'readlink -f' in usb_hotplug
assert 'ubus call network.interface.wanusb up' in usb_hotplug
assert "rule_refresh" in cron and "grep -qx weekly" in cron
assert "grep -qx 1" in cron and "/usr/bin/campus-route reconcile" in cron
assert "DESTDIR" in installer and "--dry-run" in installer
assert "modemdata.@service[0].enabled=0" in installer
assert "network.interface.wwan" in installer
assert "manifest" in rollback and "campus_route.uci" in rollback
assert (ROOT / "snapshot.sh").is_file()

# Deliverable must not carry concrete portal credentials or management targets.
# Keep this shipped self-test free of the fixture values themselves: the package
# is distributable and should contain only typed placeholders.
all_text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in ROOT.rglob("*") if p.is_file() and "tests" not in p.parts)
for forbidden in ("ADMIN_SECRET", "ACCOUNT", "TOKEN", "ROUTER"):
    assert forbidden not in all_text, f"credential/target leaked: {forbidden}"

print("test_static: PASS")
