#Requires -Version 5.1
<#
.SYNOPSIS
  Stops the local Mavis Gallery dev stack started by dev-up.ps1.
#>
$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$pidFile = Join-Path $root ".tmp\dev.pids.json"
if (-not (Test-Path $pidFile)) {
    Write-Warning "No dev.pids.json found; nothing to stop."
    exit 0
}

$pids = Get-Content $pidFile | ConvertFrom-Json
foreach ($name in $pids.PSObject.Properties.Name) {
    $id = [int]$pids.$name
    if (-not (Get-Process -Id $id -ErrorAction SilentlyContinue)) {
        Write-Host "[skip] $name pid=$id already stopped"
        continue
    }
    Write-Host "[stop] $name pid=$id"
    & taskkill.exe /PID $id /T /F 2>&1 | Out-Null
}
Remove-Item -LiteralPath $pidFile -Force
Write-Host "Dev stack stopped. Redis container mavis-dev-redis is left running; stop it with: docker stop mavis-dev-redis"
