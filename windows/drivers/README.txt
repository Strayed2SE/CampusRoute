Signed WinDivert payload slot

Place the vendor-supplied, Authenticode-signed WinDivert64.sys and matching
WinDivert.dll for the target Windows x64 release in this directory before build.
The application verifies that both files exist and can load WinDivertOpen;
when either is absent or load fails, policy stays FAIL-CLOSED and status reports
backend=placeholder (no packet is forwarded as if enforcement were active).
Record vendor version and SHA-256 here for release packaging.

Expected files:
  WinDivert64.sys
  WinDivert.dll
