#Requires -Version 5.1
<#
.SYNOPSIS
  Checks the local Mavis Gallery dev stack and the Flask login bridge.
#>
$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$tmp = Join-Path $root ".tmp"
$checks = [System.Collections.Generic.List[object]]::new()

function Get-EnvValue {
    param([string]$Path, [string]$Key)
    if (-not (Test-Path $Path)) { return $null }
    $line = Get-Content $Path | Where-Object { $_ -match "^$([regex]::Escape($Key))=" } | Select-Object -First 1
    if (-not $line) { return $null }
    return ($line -split "=", 2)[1].Trim()
}

$flaskPort = Get-EnvValue -Path (Join-Path $root ".env") -Key "PORT"
if (-not $flaskPort) { $flaskPort = "8100" }
$galleryPort = "3000"
$apiPort = Get-EnvValue -Path (Join-Path $root "services\generation-service\.env") -Key "GALLERY_PORT"
if (-not $apiPort) { $apiPort = "3101" }
$redisPort = "6380"
$redisUrl = Get-EnvValue -Path (Join-Path $root "services\generation-service\.env") -Key "REDIS_URL"
if ($redisUrl -match ':(\d+)/') { $redisPort = $matches[1] }

function Add-Check {
    param([string]$Name, [bool]$Ok, [string]$Detail)
    $checks.Add([pscustomobject]@{ Name = $Name; Ok = $Ok; Detail = $Detail })
}

function Test-Url {
    param([string]$Url)
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
        return $response.StatusCode -lt 500
    }
    catch { return $false }
}

Add-Check "Flask /healthz" (Test-Url "http://127.0.0.1:$flaskPort/healthz") "http://127.0.0.1:$flaskPort/healthz"
Add-Check "Gallery Web" (Test-Url "http://127.0.0.1:$galleryPort/") "http://127.0.0.1:$galleryPort/"
Add-Check "Generation API /health" (Test-Url "http://127.0.0.1:$apiPort/health") "http://127.0.0.1:$apiPort/health"

$flaskEnv = Join-Path $root ".env"
$secret = ""
if (Test-Path $flaskEnv) {
    $secret = ((Get-Content $flaskEnv | Where-Object { $_ -match '^GALLERY_INTROSPECTION_SECRET=' }) -replace '^GALLERY_INTROSPECTION_SECRET=', '').Trim()
}
try {
    $introspection = Invoke-RestMethod -Uri "http://127.0.0.1:$flaskPort/internal/gallery/session" -Headers @{ "X-Mavis-Introspection-Secret" = $secret } -TimeoutSec 5
    Add-Check "Introspection endpoint" ($introspection.role -eq "guest") "role=$($introspection.role)"
}
catch {
    Add-Check "Introspection endpoint" $false "request failed: $($_.Exception.Message)"
}

try {
    $session = Invoke-RestMethod -Uri "http://127.0.0.1:$galleryPort/api/me/session" -TimeoutSec 5
    Add-Check "Gallery /api/me/session" ($null -ne $session.role) "role=$($session.role) bridge=$($session.bridge)"
}
catch {
    Add-Check "Gallery /api/me/session" $false "request failed: $($_.Exception.Message)"
}

try {
    $workflows = Invoke-RestMethod -Uri "http://127.0.0.1:$galleryPort/api/generation/workflows" -TimeoutSec 8
    Add-Check "Workflows via BFF" ($null -ne $workflows.items) "items=$($workflows.items.Count)"
}
catch {
    Add-Check "Workflows via BFF" $false "request failed: $($_.Exception.Message)"
}

$redisOk = $false
$redisDetail = "not checked"
try {
    $ping = docker exec mavis-dev-redis redis-cli ping 2>$null
    $redisOk = $ping -match "PONG"
    $redisDetail = $ping
}
catch {
    $redisDetail = "docker/redis unavailable"
}
Add-Check "Redis" $redisOk $redisDetail

$pidFile = Join-Path $tmp "dev.pids.json"
if (Test-Path $pidFile) {
    $pids = Get-Content $pidFile | ConvertFrom-Json
    foreach ($name in $pids.PSObject.Properties.Name) {
        $alive = Get-Process -Id ([int]$pids.$name) -ErrorAction SilentlyContinue
        Add-Check "Process $name" ($null -ne $alive) "pid=$($pids.$name)"
    }
}
else {
    Add-Check "Dev processes" $false "dev.pids.json not found (run dev-up.ps1)"
}

$checks | ForEach-Object {
    [pscustomobject]@{ Service = $_.Name; Status = $(if ($_.Ok) { "OK" } else { "FAIL" }); Detail = $_.Detail }
} | Format-Table -AutoSize

if ($checks | Where-Object { -not $_.Ok }) {
    Write-Host "Some checks failed. Inspect logs under $tmp\dev-*.log."
    exit 1
}
Write-Host "All checks passed."
