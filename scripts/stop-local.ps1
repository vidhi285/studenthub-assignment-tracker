<#
.SYNOPSIS
  Stop StudentHub's local containers WITHOUT deleting the database.

.DESCRIPTION
  Runs `docker compose down`, which removes the containers and network but keeps
  the named volume "studenthub_mysql_data", so all data is still there next time.
  It intentionally never passes -v.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\stop-local.ps1
#>
# "Continue" (not "Stop"): Windows PowerShell 5.1 would otherwise abort on harmless
# stderr output from docker/git. Every native command is checked via $LASTEXITCODE.
$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)

docker version --format "{{.Server.Version}}" *> $null
if ($LASTEXITCODE -ne 0) { Write-Host "Docker is not running, so StudentHub is already stopped." -ForegroundColor Yellow; exit 0 }

Write-Host "==> Stopping StudentHub (database volume is kept)" -ForegroundColor Cyan
docker compose --profile test down
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: docker compose down failed." -ForegroundColor Red; exit 1 }

docker volume inspect studenthub_mysql_data *> $null
if ($LASTEXITCODE -eq 0) {
  Write-Host "Stopped. Your data is safe in the Docker volume 'studenthub_mysql_data'." -ForegroundColor Green
} else {
  Write-Host "Stopped." -ForegroundColor Green
}
Write-Host "Start again with: docker compose up -d   (or .\scripts\run-local.ps1)"
