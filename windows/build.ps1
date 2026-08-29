$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $PSScriptRoot
$Source = Join-Path $PSScriptRoot 'campusroute.py'
$DriverDir = Join-Path $PSScriptRoot 'drivers'
$Dist = Join-Path $Root 'dist'
$Version = if ($env:CAMPUSROUTE_VERSION) { $env:CAMPUSROUTE_VERSION } else { '1.0.0' }

if (-not [Environment]::Is64BitProcess) {
    throw 'Use a 64-bit Python process to build the x64 executable.'
}
if (-not (Test-Path $Source)) { throw "Missing source: $Source" }
$sys = Join-Path $DriverDir 'WinDivert64.sys'
$dll = Join-Path $DriverDir 'WinDivert.dll'
if (-not (Test-Path $sys) -or -not (Test-Path $dll)) {
    throw 'windows/drivers/WinDivert64.sys and WinDivert.dll are required.'
}
$sig = Get-AuthenticodeSignature -LiteralPath $sys
if ($sig.Status -ne 'Valid') {
    throw "WinDivert64.sys signature status is $($sig.Status); refusing to package an unsigned driver."
}

$mods = python -c "import importlib.util,sys; req=['PyInstaller','pystray','PIL']; miss=[m for m in req if importlib.util.find_spec(m) is None]; print(' '.join(miss)); sys.exit(1 if miss else 0)"
if ($LASTEXITCODE -ne 0) {
    throw "Build dependencies missing: $mods. Install PyInstaller, pystray and Pillow in the build environment."
}

$verFile = Join-Path $PSScriptRoot 'CampusRoute.version.txt'
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($($Version -replace '\.',', '), 0), prodvers=($($Version -replace '\.',', '), 0),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([
    StringTable('040904B0', [
      StringStruct('CompanyName', 'CampusRoute'),
      StringStruct('FileDescription', 'Campus network dual-uplink policy service'),
      StringStruct('FileVersion', '$Version'),
      StringStruct('InternalName', 'CampusRoute'),
      StringStruct('OriginalFilename', 'CampusRoute.exe'),
      StringStruct('ProductName', 'CampusRoute'),
      StringStruct('ProductVersion', '$Version')
    ])
  ]), VarFileInfo([VarStruct('Translation', [1033, 1200])])
])
"@ | Set-Content -LiteralPath $verFile -Encoding UTF8

Push-Location $Root
try {
    $args = @('-m','PyInstaller','--noconfirm','--clean','--onefile','--windowed',
        '--name','CampusRoute','--version-file',$verFile,
        '--add-binary',"$dll;drivers", '--add-binary',"$sys;drivers",
        '--hidden-import','pystray','--hidden-import','PIL', $Source)
    & python @args
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}

$distDrivers = Join-Path $Dist 'drivers'
New-Item -ItemType Directory -Force -Path $distDrivers | Out-Null
Copy-Item -LiteralPath $dll -Destination (Join-Path $distDrivers 'WinDivert.dll') -Force
Copy-Item -LiteralPath $sys -Destination (Join-Path $distDrivers 'WinDivert64.sys') -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'install.ps1') -Destination $Dist -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'uninstall.ps1') -Destination $Dist -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'rollback.ps1') -Destination $Dist -Force

$manifest = [ordered]@{
    product = 'CampusRoute'; version = $Version; architecture = 'x64';
    built_utc = (Get-Date).ToUniversalTime().ToString('o');
    executable = @{ path = 'CampusRoute.exe'; sha256 = (Get-FileHash (Join-Path $Dist 'CampusRoute.exe') -Algorithm SHA256).Hash.ToLowerInvariant() };
    driver = @{ path = 'drivers/WinDivert64.sys'; sha256 = (Get-FileHash $sys -Algorithm SHA256).Hash.ToLowerInvariant(); signer = 'ORG'; signature = $sig.Status.ToString() };
    dll = @{ path = 'drivers/WinDivert.dll'; sha256 = (Get-FileHash $dll -Algorithm SHA256).Hash.ToLowerInvariant() };
    single_file = $true; python_runtime_embedded = $true;
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $Dist 'CampusRoute.manifest.json') -Encoding UTF8
Write-Host "Built $([IO.Path]::GetFullPath((Join-Path $Dist 'CampusRoute.exe')))"
Write-Host "WinDivert64.sys signature: $($sig.Status)"

