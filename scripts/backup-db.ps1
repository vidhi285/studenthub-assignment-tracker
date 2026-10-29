<#
.SYNOPSIS
  Back up the local StudentHub database to .\backups\studenthub-<timestamp>.sql

.DESCRIPTION
  The dump is created inside the MySQL container and copied out with `docker compose cp`,
  which avoids PowerShell changing the file encoding. Requires the stack to be running.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\backup-db.ps1
#>
# "Continue" (not "Stop"): Windows PowerShell 5.1 would otherwise abort on harmless
# stderr output from docker/git. Every native command is checked via $LASTEXITCODE.
$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)

$id = (docker compose ps -q db) | Select-Object -First 1
if (-not $id) { Write-Host "ERROR: the db container is not running. Start it with: docker compose up -d" -ForegroundColor Red; exit 1 }

New-Item -ItemType Directory -Force -Path "backups" | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$target = "backups\studenthub-$stamp.sql"

Write-Host "==> Dumping database" -ForegroundColor Cyan
docker compose exec -T db sh -c 'MYSQL_PWD=$MYSQL_ROOT_PASSWORD mysqldump -uroot --single-transaction --routines --triggers --no-tablespaces $MYSQL_DATABASE > /tmp/studenthub-backup.sql'
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: mysqldump failed." -ForegroundColor Red; exit 1 }
docker compose cp db:/tmp/studenthub-backup.sql $target
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: could not copy the backup out of the container." -ForegroundColor Red; exit 1 }
docker compose exec -T db rm -f /tmp/studenthub-backup.sql | Out-Null

$size = [math]::Round((Get-Item $target).Length / 1KB, 1)
Write-Host "Backup written to $target ($size KB)" -ForegroundColor Green
