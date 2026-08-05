#Requires -Version 5.1
<#
.SYNOPSIS
  Idempotently prepares local .env files for the Mavis Gallery dev stack.

.DESCRIPTION
  Adds the bridge variables required for the Flask -> Gallery Web -> Generation
  Service flow when they are missing. Never overwrites existing values except
  the two shared dev secrets when -ForceSecrets is used. Never prints values.
#>
[CmdletBinding()]
param(
    [int]$FlaskPort = 8100,
    [int]$GalleryPort = 3000,
    [int]$ApiPort = 3101,
    [int]$RedisPort = 6380,
    [switch]$ForceSecrets,
    [switch]$RefreshUrls
)
$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$tmpDir = Join-Path $root ".tmp"
New-Item -ItemType Directory -Force -Path (Join-Path $tmpDir "generation") | Out-Null

function Read-EnvKeys {
    param([string]$Path)
    $map = @{}
    if (Test-Path $Path) {
        foreach ($line in Get-Content $Path) {
            if ($line -match '^\s*([A-Za-z0-9_]+)\s*=(.*)$') {
                $map[$matches[1]] = $matches[2].Trim()
            }
        }
    }
    return $map
}

function Set-EnvValue {
    param([string]$Path, [string]$Key, [string]$Value)
    if (Test-Path $Path) {
        $pattern = "^$([regex]::Escape($Key))\s*="
        $lines = @(Get-Content $Path | Where-Object { $_ -notmatch $pattern })
        Set-Content -Path $Path -Value $lines -Encoding ASCII
    }
    else {
        New-Item -ItemType File -Force -Path $Path | Out-Null
    }
    Add-Content -Path $Path -Value "$Key=$Value" -Encoding ASCII
}

function New-DevSecret {
    $bytes = New-Object byte[] 36
    $rng = New-Object System.Security.Cryptography.RNGCryptoServiceProvider
    $rng.GetBytes($bytes)
    return [Convert]::ToBase64String($bytes)
}

function Ensure-EnvValue {
    param([string]$Path, [string]$Key, [string]$Value, [bool]$Force = $false)
    $map = Read-EnvKeys -Path $Path
    if ($map.ContainsKey($Key) -and -not $Force) {
        Write-Host "[skip] $Key"
        return
    }
    Set-EnvValue -Path $Path -Key $Key -Value $Value
    Write-Host "[$([char]0x2713)] $Key"
}

$flaskEnv = Join-Path $root ".env"
$galleryEnv = Join-Path $root "apps\gallery-web\.env"
$generationEnv = Join-Path $root "services\generation-service\.env"

# Shared secrets: HMAC must match the Generation Service; introspection must
# match between Flask and Gallery Web.
$genMap = Read-EnvKeys -Path $generationEnv
$hmac = $genMap["GALLERY_INTERNAL_HMAC_SECRET"]
if (-not $hmac -or $ForceSecrets) { $hmac = New-DevSecret }
$introspection = New-DevSecret
$flaskBase = "http://127.0.0.1:$FlaskPort"
$galleryBase = "http://127.0.0.1:$GalleryPort"
$apiBase = "http://127.0.0.1:$ApiPort"

Write-Host "== Flask (.env) =="
Ensure-EnvValue -Path $flaskEnv -Key "HOST" -Value "127.0.0.1" -Force $RefreshUrls
Ensure-EnvValue -Path $flaskEnv -Key "PORT" -Value "$FlaskPort" -Force $RefreshUrls
Ensure-EnvValue -Path $flaskEnv -Key "APP_BASE_URL" -Value $flaskBase -Force $RefreshUrls
Ensure-EnvValue -Path $flaskEnv -Key "AI_IMAGE_EXTERNAL_URL" -Value "$galleryBase/create" -Force $RefreshUrls
Ensure-EnvValue -Path $flaskEnv -Key "GALLERY_INTROSPECTION_SECRET" -Value $introspection -Force $ForceSecrets
Ensure-EnvValue -Path $flaskEnv -Key "GALLERY_SERVICE_BASE_URL" -Value $apiBase -Force $RefreshUrls
Ensure-EnvValue -Path $flaskEnv -Key "GALLERY_INTERNAL_HMAC_SECRET" -Value $hmac -Force $ForceSecrets

Write-Host "== Gallery Web (apps/gallery-web/.env) =="
Ensure-EnvValue -Path $galleryEnv -Key "GALLERY_SERVICE_BASE_URL" -Value $apiBase -Force $RefreshUrls
Ensure-EnvValue -Path $galleryEnv -Key "GALLERY_INTERNAL_HMAC_SECRET" -Value $hmac -Force $ForceSecrets
Ensure-EnvValue -Path $galleryEnv -Key "MAVIS_AUTH_INTROSPECTION_URL" -Value "$flaskBase/internal/gallery/session" -Force $RefreshUrls
Ensure-EnvValue -Path $galleryEnv -Key "GALLERY_INTROSPECTION_SECRET" -Value $introspection -Force $ForceSecrets
Ensure-EnvValue -Path $galleryEnv -Key "GALLERY_PUBLIC_ORIGIN" -Value $galleryBase -Force $RefreshUrls
Ensure-EnvValue -Path $galleryEnv -Key "MAVIS_AUTH_LOGIN_URL" -Value "$flaskBase/login" -Force $RefreshUrls
Ensure-EnvValue -Path $galleryEnv -Key "MAVIS_AUTH_LOGOUT_URL" -Value "$flaskBase/logout" -Force $RefreshUrls

Write-Host "== Generation Service (services/generation-service/.env) =="
Ensure-EnvValue -Path $generationEnv -Key "GALLERY_INTERNAL_HMAC_SECRET" -Value $hmac -Force $ForceSecrets
$runtimeDefaults = [ordered]@{
    APP_ENV = "development"
    GENERATION_ALLOW_MOCK_PROVIDER = "true"
    GENERATION_MOCK_LATENCY_MS = "1200"
    GALLERY_DEFAULT_MODERATION = "approved"
    REDIS_URL = "redis://127.0.0.1:$RedisPort/0"
    BULLMQ_PREFIX = "bull"
    BULLMQ_QUEUE_NAME = "generation"
    BULLMQ_CANCEL_CHANNEL = "generation-cancel"
    BULLMQ_CONCURRENCY = "2"
    BULLMQ_ATTEMPTS = "3"
    BULLMQ_BACKOFF_MS = "1000"
    BULLMQ_COMPLETED_RETENTION_COUNT = "1000"
    BULLMQ_FAILED_RETENTION_COUNT = "2000"
    BULLMQ_RETENTION_AGE_SECONDS = "1209600"
    BULLMQ_MAX_STALLED_COUNT = "2"
    BULLMQ_LOCK_DURATION_MS = "120000"
    BULLMQ_GRACEFUL_SHUTDOWN_MS = "15000"
    GENERATION_OUTBOX_BATCH_SIZE = "20"
    GENERATION_OUTBOX_RETRY_BASE_MS = "500"
    GENERATION_OUTBOX_RETRY_MAX_MS = "30000"
    GENERATION_OUTBOX_POLL_MS = "1000"
    GENERATION_DEFAULT_CREDIT_COST = "1"
    GENERATION_TEMP_DIR = "..\..\.tmp\generation"
    GENERATION_POLL_INTERVAL_MS = "1000"
    GENERATION_POLL_MAX_ATTEMPTS = "600"
    GENERATION_REMOTE_DOWNLOAD_TIMEOUT_MS = "60000"
    GENERATION_PROVIDER_RETRY_BASE_MS = "500"
    GENERATION_PROVIDER_MAX_TOTAL_CALLS = "6"
}
foreach ($entry in $runtimeDefaults.GetEnumerator()) {
    Ensure-EnvValue -Path $generationEnv -Key $entry.Key -Value $entry.Value -Force $RefreshUrls
}

Write-Host ""
Write-Host "Local env is ready. Start the stack with: .\scripts\dev\dev-up.ps1"
Write-Host "Re-run with -ForceSecrets to rotate the two shared dev secrets."
