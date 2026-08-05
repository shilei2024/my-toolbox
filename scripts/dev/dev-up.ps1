#Requires -Version 5.1
<#
.SYNOPSIS
  Starts the full local Mavis Gallery dev stack.

.DESCRIPTION
  Starts Flask (8000), Gallery Web (3000), Generation API (3101), the outbox
  dispatcher and the generation worker. Redis is started in Docker unless
  -SkipRedis is used; -NoWorker skips the worker process.
#>
[CmdletBinding()]
param(
    [switch]$SkipRedis,
    [switch]$NoWorker
)
$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$tmp = Join-Path $root ".tmp"
$pidFile = Join-Path $tmp "dev.pids.json"
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

if (Test-Path $pidFile) {
    Write-Error "dev.pids.json already exists. Run .\scripts\dev\dev-down.ps1 first."
    exit 1
}

& (Join-Path $PSScriptRoot "setup-local-env.ps1")

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

if (-not $SkipRedis) {
    $redisAlreadyUp = $false
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect("127.0.0.1", [int]$redisPort)
        $client.Close()
        $redisAlreadyUp = $true
    }
    catch { $redisAlreadyUp = $false }
    try {
        if ($redisAlreadyUp) {
            Write-Host "[redis] already listening on 127.0.0.1:$redisPort"
        }
        else {
            $existing = docker ps -a --filter "name=mavis-dev-redis" --format "{{.Names}}" 2>$null
            if ($existing -match "mavis-dev-redis") {
                Write-Host "[redis] starting existing docker container mavis-dev-redis ..."
                docker start mavis-dev-redis | Out-Null
            }
            else {
                Write-Host "[redis] starting docker container mavis-dev-redis on $redisPort ..."
                docker run -d --name mavis-dev-redis --restart unless-stopped -p "${redisPort}:6379" redis:7-alpine | Out-Null
            }
            Start-Sleep -Seconds 3
            Write-Host "[redis] started on 127.0.0.1:$redisPort"
        }
    }
    catch {
        Write-Warning "Redis could not be started (is Docker running?). Generation queue stays disabled."
    }
}

function Start-DevProcess {
    param([string]$Name, [string]$FilePath, [string[]]$Arguments, [string]$WorkingDirectory)
    $out = Join-Path $tmp "dev-$Name.log"
    $err = Join-Path $tmp "dev-$Name.err.log"
    $command = (@($FilePath) + $Arguments) -join " "
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "cmd.exe"
    $psi.Arguments = "/c `"$command > `"$out`" 2> `"$err`"`""
    $psi.WorkingDirectory = $WorkingDirectory
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    $null = $process.Start()
    Write-Host "[started] $Name pid=$($process.Id)"
    return $process.Id
}

$flask = Start-DevProcess -Name "flask" -FilePath (Join-Path $root ".venv\Scripts\python.exe") -Arguments @("app.py") -WorkingDirectory $root
$gallery = Start-DevProcess -Name "gallery" -FilePath "npm.cmd" -Arguments @("run", "dev", "--", "-p", $galleryPort) -WorkingDirectory (Join-Path $root "apps\gallery-web")
$api = Start-DevProcess -Name "api" -FilePath "npm.cmd" -Arguments @("run", "gallery:start") -WorkingDirectory (Join-Path $root "services\generation-service")
$dispatcher = Start-DevProcess -Name "dispatcher" -FilePath "npm.cmd" -Arguments @("run", "generation:dispatcher") -WorkingDirectory (Join-Path $root "services\generation-service")
$worker = $null
if (-not $NoWorker) {
    $worker = Start-DevProcess -Name "worker" -FilePath "npm.cmd" -Arguments @("run", "generation:worker") -WorkingDirectory (Join-Path $root "services\generation-service")
}

$pids = [ordered]@{ flask = $flask; gallery = $gallery; api = $api; dispatcher = $dispatcher }
if ($worker) { $pids.worker = $worker }
$pids | ConvertTo-Json | Set-Content -Path $pidFile -Encoding utf8

function Wait-Http {
    param([string]$Url, [int]$TimeoutSeconds = 45)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -lt 500) { return $true }
        }
        catch { }
        Start-Sleep -Milliseconds 1500
    }
    return $false
}

$endpoints = @(
    @{ Name = "Flask"; Url = "http://127.0.0.1:$flaskPort/healthz" },
    @{ Name = "Gallery Web"; Url = "http://127.0.0.1:$galleryPort/" },
    @{ Name = "Generation API"; Url = "http://127.0.0.1:$apiPort/health" }
)
foreach ($endpoint in $endpoints) {
    $ok = Wait-Http -Url $endpoint.Url
    Write-Host ("[{0}] {1} {2}" -f $(if ($ok) { "ok" } else { "FAIL" }), $endpoint.Name, $endpoint.Url)
    if (-not $ok) { $failed = $true }
}

Write-Host ""
Write-Host "Logs: $tmp\dev-*.log"
Write-Host "Status: .\scripts\dev\dev-health.ps1"
Write-Host "Stop:   .\scripts\dev\dev-down.ps1"
if ($failed) { exit 1 }
