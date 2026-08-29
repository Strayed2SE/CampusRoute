#requires -RunAsAdministrator
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProgramFiles = [Environment]::GetFolderPath('ProgramFiles')
$Exe = Join-Path (Join-Path $ProgramFiles 'CampusRoute') 'CampusRoute.exe'
if (-not (Test-Path $Exe)) { throw "CampusRoute.exe not found at $Exe" }
$result = & $Exe --rollback
if ($LASTEXITCODE -ne 0) { throw "CampusRoute rollback failed with exit code $LASTEXITCODE" }
Write-Host $result
Write-Host 'CampusRoute policy disabled and pre-install firewall/routes restore requested.'

