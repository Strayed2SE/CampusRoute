# CampusRoute Windows 1.0

CampusRoute is a single-file x64 Windows 10/11 application for the current host:

- CampusRoute.exe --service runs the elevated policy/Dr.COM keepalive service.
- CampusRoute.exe --gui --minimized runs the ordinary-user Tk/pystray tray UI.
- CampusRoute.exe --status queries the fixed named-pipe RPC (status).
- CampusRoute.exe --snapshot and --rollback manage the pre-install network snapshots.
- CampusRoute.exe --purge-credentials removes the CampusRoute/DrCOM Credential Manager entry.

The service never enables ICS, bridging or LAN forwarding. Interface selection uses
interface index/LUID, default gateway and metric; the UI can lock a discovered
interface by name, index or LUID. The packet backend uses the bundled WinDivert
network-layer DLL/SYS and supports IPv4/IPv6. The signed SYS payload is checked by
both the build and install scripts; a missing or failed backend keeps the panic
firewall rule enabled so public traffic does not leak over the campus default.

## Build

Run powershell -ExecutionPolicy Bypass -File windows/build.ps1 from the repository
with 64-bit Python. The build script checks WinDivert64.sys Authenticode status,
embeds WinDivert.dll and WinDivert64.sys into the one-file executable, bundles
Tk/pystray/Pillow, and writes dist/CampusRoute.manifest.json with SHA-256 values.
The dist/drivers copies are retained for signature inspection and installation;
the EXE itself contains the runtime and driver payload.

## Install / uninstall

Copy the complete dist directory to the target Windows host and run install.ps1
elevated. It creates a delayed-auto LocalSystem service, a one-minute per-user
tray task, the disabled panic firewall rule, and route/firewall snapshots under
%ProgramData%\\CampusRoute. The service starts with enabled=false; set policy
options and credentials from the tray UI.

Run uninstall.ps1 elevated to stop/delete the service and task, remove the
CampusRoute firewall rule and driver service created from this installation, remove
the Credential Manager entry, and restore the saved firewall/routes unless
-KeepNetworkState is supplied. -PurgeData removes retained snapshots and state
files after verification.

## Policy

Domestic/private and cached CN destinations are sent through the campus adapter
before encrypted-port matching. Overseas, unknown and configured TLS/QUIC/DoH/DoT
ports prefer USB. When USB is offline the default action is reject; enabling
usb_missing_fallback changes only that path to campus. IPv6 follows the same
policy. plugin_compat is retained for deployments that hand off marked traffic;
it defaults to false and does not enable third-party proxy plugins.

Dr.COM credentials are stored through Windows Credential Manager and are never
written to config.json, command lines or normal logs. config.json only stores
policy, portal URL, polling interval and adapter selections.

## Verification checklist

1. python -m py_compile windows/campusroute.py
2. python -m unittest discover -s windows/tests -v
3. Get-AuthenticodeSignature windows/drivers/WinDivert64.sys returns Valid.
4. python -m PyInstaller.utils.cliutils.archive_viewer dist/CampusRoute.exe lists
   drivers/WinDivert.dll and drivers/WinDivert64.sys.
5. After installation, test domestic/overseas/unknown/TCP-443/UDP-443/IPv6 with USB
   online and offline, then toggle fallback and use the tray rollback button.

