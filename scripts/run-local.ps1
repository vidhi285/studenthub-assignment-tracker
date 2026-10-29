<#
.SYNOPSIS
  Start StudentHub locally with Docker Compose and wait until it is healthy.

.DESCRIPTION
  * Checks that Docker Desktop is running.
  * Creates .env from .env.example on first run and replaces the "change-me"
    placeholders with strong random values (existing values are never touched).
  * Runs: docker compose up -d --build
  * Waits for the web container health check and prints the URL.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\run-local.ps1
  powershell -ExecutionPolicy Bypass -File .\scripts\run-local.ps1 -Open
#>
param(
  [switch]$Open,
  [int]$TimeoutSeconds = 240
)

# "Continue" (not "Stop"): Windows PowerShell 5.1 would otherwise abort on harmless
# stderr output from docker/git. Every native command is checked via $LASTEXITCODE.
$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Write-Step($message) { Write-Host "==> $message" -ForegroundColor Cyan }
function Fail($message) { Write-Host "ERROR: $message" -ForegroundColor Red; exit 1 }

function New-RandomSecret([int]$Length = 48) {
  $result = ""
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  while ($result.Length -lt $Length) {
    $bytes = New-Object byte[] 64
    $rng.GetBytes($bytes)
    $result += ([Convert]::ToBase64String($bytes) -replace '[^A-Za-z0-9]', '')
  }
  return $result.Substring(0, $Length)
}

Write-Step "Checking Docker"
docker version --format "{{.Server.Version}}" *> $null
if ($LASTEXITCODE -ne 0) { Fail "Docker is not running. Start Docker Desktop, wait until it says 'Engine running', then retry." }
docker compose version *> $null
if ($LASTEXITCODE -ne 0) { Fail "Docker Compose v2 is not available. Update Docker Desktop." }

if (-not (Test-Path ".env")) {
  Write-Step "Creating .env from .env.example"
  Copy-Item ".env.example" ".env" -ErrorAction Stop
}

$envText = [System.IO.File]::ReadAllText((Resolve-Path ".env"))
$replacements = @{
  "SECRET_KEY=change-me-to-a-long-random-string" = "SECRET_KEY=$(New-RandomSecret 64)"
  "MYSQL_PASSWORD=change-me-app-password"          = "MYSQL_PASSWORD=$(New-RandomSecret 24)"
  "MYSQL_ROOT_PASSWORD=change-me-root-password"    = "MYSQL_ROOT_PASSWORD=$(New-RandomSecret 24)"
}
$changed = $false
foreach ($placeholder in $replacements.Keys) {
  if ($envText.Contains($placeholder)) {
    $envText = $envText.Replace($placeholder, $replacements[$placeholder])
    $changed = $true
  }
}
if ($changed) {
  [System.IO.File]::WriteAllText((Join-Path (Get-Location) ".env"), $envText, (New-Object System.Text.UTF8Encoding $false))
  Write-Host "    Generated random SECRET_KEY / MySQL passwords in .env" -ForegroundColor DarkGray
}

$port = "5000"
$match = [regex]::Match($envText, '(?m)^APP_PORT=(\d+)')
if ($match.Success) { $port = $match.Groups[1].Value }

Write-Step "Building and starting containers (first run downloads images; this can take a few minutes)"
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { Fail "docker compose up failed. See the messages above, then run: docker compose logs --tail=50" }

Write-Step "Waiting for the application to become healthy"
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$status = ""
while ((Get-Date) -lt $deadline) {
  $id = (docker compose ps -q web) | Select-Object -First 1
  if ($id) { $status = (docker inspect -f "{{if .State.Health}}{{.State.Health.Status}}{{end}}" $id) 2>$null }
  if ($status -eq "healthy") { break }
  if ($status -eq "unhealthy") { break }
  Start-Sleep -Seconds 3
  Write-Host "." -NoNewline
}
Write-Host ""

if ($status -ne "healthy") {
  Write-Host "The web container is not healthy (status: '$status'). Recent logs:" -ForegroundColor Yellow
  docker compose logs --tail=40 web
  Fail "Startup did not complete. Fix the issue above and run this script again."
}

$url = "http://localhost:$port"
Write-Host ""
Write-Host "StudentHub is running at $url" -ForegroundColor Green
Write-Host "  Status:  docker compose ps"
Write-Host "  Logs:    docker compose logs -f web"
Write-Host "  Stop:    .\scripts\stop-local.ps1   (keeps your data)"
if ($Open) { Start-Process $url }
