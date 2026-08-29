Windows implementation handoff (2026-08-28)

Files:
- windows/campusroute.py: single-file service/GUI/Tray client, fixed AF_PIPE RPC,
  Dr.COM login/keepalive, Credential Manager, interface index/LUID discovery,
  IPv4/IPv6 policy and WinDivert Open/Recv/Send/Close backend.
- windows/build.ps1: x64 PyInstaller build, signed SYS preflight, embedded DLL/SYS,
  Tk/pystray/Pillow bundle, version and SHA-256 manifest.
- windows/install.ps1 / windows/uninstall.ps1: one-time elevated setup, delayed-auto
  LocalSystem service, delayed ONLOGON tray task, firewall panic rule, route/firewall
  snapshots, ACLs, credential cleanup and rollback.
- windows/tests/test_policy.py: policy and Dr.COM response tests.

Verified on 2026-08-28:
- python -m py_compile windows/campusroute.py
- python -m unittest discover -s windows/tests -v (5 tests OK)
- powershell parser check for install.ps1 and uninstall.ps1
- dist/CampusRoute.exe is a one-file x64 PyInstaller build; archive lists
  drivers/WinDivert.dll and drivers/WinDivert64.sys
- WinDivert64.sys Authenticode status is Valid

Defaults: enabled=false, IPv6=true, unknown/encrypted=>USB, USB missing=>reject,
usb_missing_fallback=false, plugin_compat=false, no ICS/bridge/LAN forwarding.
The GUI starts minimized to the tray when launched by the scheduled task. Credentials
are stored only in Windows Credential Manager; config/state files are ACL protected.

