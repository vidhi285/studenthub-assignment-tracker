<#
.SYNOPSIS
  Restore the local StudentHub database from a .sql backup made by backup-db.ps1.

.DESCRIPTION
  This REPLACES the current tables with the contents of the backup. A safety backup
  of the current state is taken first. You must type RESTORE to confirm.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\restore-db.ps1 -File .\backups\studenthub-20261029-210000.sql
#>
param([Parameter(Mandatory = $true)][string]$File)

# "Continue" (not "Stop"): Windows PowerShell 5.1 would otherwise abort on harmless
# stderr output from docker/git. Every native command is checked via $LASTEXITCODE.
$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Test-Path $File)) { Write-Host "ERROR: file not found: $File" -ForegroundColor Red; exit 1 }
$id = (docker compose ps -q db) | Select-Object -First 1
if (-not $id) { Write-Host "ERROR: the db container is not running. Start it with: docker compose up -d" -ForegroundColor Red; exit 1 }

Write-Host "This will overwrite the current StudentHub database with $File" -ForegroundColor Yellow
$answer = Read-Host "Type RESTORE to continue"
if ($answer -ne "RESTORE") { Write-Host "Cancelled."; exit 0 }

Write-Host "==> Taking a safety backup of the current data first" -ForegroundColor Cyan
& "$PSScriptRoot\backup-db.ps1"
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: safety backup failed; nothing was restored." -ForegroundColor Red; exit 1 }

Write-Host "==> Restoring" -ForegroundColor Cyan
docker compose cp $File db:/tmp/studenthub-restore.sql
docker compose exec -T db sh -c 'MYSQL_PWD=$MYSQL_ROOT_PASSWORD mysql -uroot $MYSQL_DATABASE < /tmp/studenthub-restore.sql && rm -f /tmp/studenthub-restore.sql'
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: restore failed. Your safety backup is in .\backups" -ForegroundColor Red; exit 1 }

Write-Host "==> Restarting the web container (applies any newer migrations)" -ForegroundColor Cyan
docker compose restart web | Out-Null
Write-Host "Restore complete." -ForegroundColor Green
