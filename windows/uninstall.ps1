#requires -RunAsAdministrator
[CmdletBinding()]
param(
    [switch]$KeepNetworkState,
    [switch]$PurgeData
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$ProgramFiles = [Environment]::GetFolderPath('ProgramFiles')
$ProgramData = [Environment]::GetFolderPath('CommonApplicationData')
$AppRoot = Join-Path $ProgramFiles 'CampusRoute'
$DataRoot = Join-Path $ProgramData 'CampusRoute'
$Exe = Join-Path $AppRoot 'CampusRoute.exe'
$FirewallSnapshot = Join-Path $DataRoot 'firewall-before.wfw'
$RouteSnapshot = Join-Path $DataRoot 'routes-before.json'

function Restore-Snapshot {
    if ($KeepNetworkState) { return }
    if (Test-Path $FirewallSnapshot) {
        & netsh.exe advfirewall import $FirewallSnapshot | Out-Null
        if ($LASTEXITCODE -ne 0) { Write-Warning 'Firewall snapshot restore failed; leaving the panic rule enabled.' }
    }
    if ((Test-Path $RouteSnapshot) -and (Test-Path $Exe)) {
        & $Exe --rollback | Out-Null
    }
}

$svc = Get-Service -Name CampusRoute -ErrorAction SilentlyContinue
if ($svc) { Stop-Service -Name CampusRoute -Force -ErrorAction SilentlyContinue }
if (Test-Path $Exe) {
    # Remove the Credential Manager entry before deleting the executable.
    & $Exe --purge-credentials | Out-Null
}
Restore-Snapshot
& schtasks.exe /Delete /TN 'CampusRoute Tray' /F 2>$null | Out-Null
& sc.exe delete CampusRoute 2>$null | Out-Null
Start-Sleep -Milliseconds 800
Get-NetFirewallRule -DisplayName 'CampusRoute Panic Block' -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue

# WinDivert creates its driver service on first open.  Remove only services whose
# image path points at this installation, avoiding unrelated WinDivert users.
Get-CimInstance Win32_SystemDriver -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like 'WinDivert*' -and $_.PathName -and $_.PathName -like "*$AppRoot*" } |
    ForEach-Object {
        Stop-Service -Name $_.Name -Force -ErrorAction SilentlyContinue
        & sc.exe delete $_.Name 2>$null | Out-Null
    }

if (Test-Path $AppRoot) { Remove-Item -LiteralPath $AppRoot -Recurse -Force }
if ($PurgeData -and (Test-Path $DataRoot)) { Remove-Item -LiteralPath $DataRoot -Recurse -Force }
Write-Host 'CampusRoute service, tray task, driver payload and firewall rule removed.'
if ($KeepNetworkState) { Write-Host 'Existing firewall/routes were left unchanged.' }
elseif (Test-Path $FirewallSnapshot) { Write-Host "Restored firewall snapshot: $FirewallSnapshot" }
if (-not $PurgeData -and (Test-Path $DataRoot)) { Write-Host "Snapshots retained in $DataRoot; use -PurgeData after verification." }

