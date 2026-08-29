#requires -RunAsAdministrator
[CmdletBinding()]
param(
    [switch]$NoStart,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$SourceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProgramFiles = [Environment]::GetFolderPath('ProgramFiles')
$ProgramData = [Environment]::GetFolderPath('CommonApplicationData')
$AppRoot = Join-Path $ProgramFiles 'CampusRoute'
$DataRoot = Join-Path $ProgramData 'CampusRoute'
$Exe = Join-Path $AppRoot 'CampusRoute.exe'
$SourceExe = Join-Path $SourceRoot 'CampusRoute.exe'
$SourceDriver = Join-Path $SourceRoot 'drivers/WinDivert64.sys'
$SourceDll = Join-Path $SourceRoot 'drivers/WinDivert.dll'
$FirewallSnapshot = Join-Path $DataRoot 'firewall-before.wfw'
$RouteSnapshot = Join-Path $DataRoot 'routes-before.json'
$InstallManifest = Join-Path $DataRoot 'install-manifest.json'

function Assert-Admin {
    $p = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run this installer from an elevated PowerShell.' }
}
function Save-Snapshot {
    New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null
    if (Test-Path $FirewallSnapshot) {
        $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
        Copy-Item $FirewallSnapshot (Join-Path $DataRoot "firewall-before-$stamp.wfw") -Force
    }
    & netsh.exe advfirewall export $FirewallSnapshot | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Unable to export the Windows Firewall snapshot.' }
    $routeScript = "Get-NetRoute -AddressFamily IPv4,IPv6 -ErrorAction SilentlyContinue | Select-Object DestinationPrefix,NextHop,InterfaceIndex,RouteMetric,AddressFamily,PolicyStore | ConvertTo-Json -Depth 5"
    $routes = & powershell.exe -NoLogo -NoProfile -NonInteractive -Command $routeScript
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($routes -join ''))) { throw 'Unable to capture the route snapshot.' }
    $routes -join [Environment]::NewLine | Set-Content -LiteralPath $RouteSnapshot -Encoding UTF8
}
function Set-DataAcl {
    if (Test-Path $DataRoot) {
        & icacls.exe $DataRoot /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)(F)' '*S-1-5-32-544:(OI)(CI)(F)' '*S-1-5-32-545:(OI)(CI)(R)' | Out-Null
    }
}

Assert-Admin
if (-not (Test-Path $SourceExe)) { throw "CampusRoute.exe not found in $SourceRoot. Run build.ps1 first." }
if (-not (Test-Path $SourceDriver) -or -not (Test-Path $SourceDll)) { throw 'WinDivert DLL/SYS payload is missing.' }
$sig = Get-AuthenticodeSignature -LiteralPath $SourceDriver
if ($sig.Status -ne 'Valid') { throw "WinDivert64.sys signature status is $($sig.Status); installation stopped." }

New-Item -ItemType Directory -Force -Path $AppRoot,$DataRoot | Out-Null
Save-Snapshot
Copy-Item -LiteralPath $SourceExe -Destination $Exe -Force
New-Item -ItemType Directory -Force -Path (Join-Path $AppRoot 'drivers') | Out-Null
Copy-Item -LiteralPath $SourceDriver -Destination (Join-Path $AppRoot 'drivers/WinDivert64.sys') -Force
Copy-Item -LiteralPath $SourceDll -Destination (Join-Path $AppRoot 'drivers/WinDivert.dll') -Force
Set-DataAcl

$panic = Get-NetFirewallRule -DisplayName 'CampusRoute Panic Block' -ErrorAction SilentlyContinue
if (-not $panic) {
    New-NetFirewallRule -DisplayName 'CampusRoute Panic Block' -Group 'CampusRoute' -Direction Outbound -Action Block -Profile Any -Protocol Any -RemoteAddress Any -Enabled False | Out-Null
} else {
    Set-NetFirewallRule -DisplayName 'CampusRoute Panic Block' -Enabled False
}

$existing = Get-Service -Name CampusRoute -ErrorAction SilentlyContinue
if ($existing) {
    Stop-Service -Name CampusRoute -Force -ErrorAction SilentlyContinue
    & sc.exe delete CampusRoute | Out-Null
    Start-Sleep -Milliseconds 800
}
$binPath = '"{0}" --service' -f $Exe
New-Service -Name CampusRoute -BinaryPathName $binPath -DisplayName 'CampusRoute Policy Service' -Description 'Domestic campus / overseas USB policy and Dr.COM keepalive' -StartupType Automatic | Out-Null
& sc.exe config CampusRoute start= delayed-auto | Out-Null
& sc.exe failure CampusRoute reset= 86400 actions= restart/60000/restart/60000/'' | Out-Null

& schtasks.exe /Delete /TN 'CampusRoute Tray' /F 2>$null | Out-Null
$taskUser = "$env:USERDOMAIN\$env:USERNAME"
$taskRun = '"{0}" --gui --minimized' -f $Exe
& schtasks.exe /Create /TN 'CampusRoute Tray' /TR $taskRun /SC ONLOGON /DELAY 0001:00 /RL LIMITED /RU $taskUser /F | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Unable to create the CampusRoute tray startup task.' }

$manifest = [ordered]@{
    installed_utc = (Get-Date).ToUniversalTime().ToString('o')
    executable = @{ path = $Exe; sha256 = (Get-FileHash $Exe -Algorithm SHA256).Hash.ToLowerInvariant() }
    driver = @{ path = (Join-Path $AppRoot 'drivers/WinDivert64.sys'); sha256 = (Get-FileHash (Join-Path $AppRoot 'drivers/WinDivert64.sys') -Algorithm SHA256).Hash.ToLowerInvariant(); signature = $sig.Status.ToString(); signer = 'ORG' }
    firewall_snapshot = $FirewallSnapshot
    route_snapshot = $RouteSnapshot
    service = 'CampusRoute'
    tray_task = 'CampusRoute Tray'
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $InstallManifest -Encoding UTF8
Set-DataAcl

if (-not $NoStart) {
    try {
        Start-Service -Name CampusRoute
        $svc = Get-Service -Name CampusRoute
        if ($svc.Status -ne 'Running') { throw "service state is $($svc.Status)" }
    } catch {
        Set-NetFirewallRule -DisplayName 'CampusRoute Panic Block' -Enabled True -ErrorAction SilentlyContinue
        throw
    }
}
Write-Host "CampusRoute installed under $AppRoot"
Write-Host "Driver signature: $($sig.Status)"
Write-Host "Network snapshots: $FirewallSnapshot and $RouteSnapshot"

