<#
.SYNOPSIS
  Run the pytest suite inside Docker against a disposable in-memory MySQL.

.DESCRIPTION
  Uses the "test" Compose profile: the db-test service keeps its data in tmpfs and
  is removed afterwards. Your development database is never touched.
  Exit code is 0 only when every test passes.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\run-tests.ps1
  powershell -ExecutionPolicy Bypass -File .\scripts\run-tests.ps1 -PytestArgs "-k assignments -v"
#>
param([string]$PytestArgs = "")

# "Continue" (not "Stop"): Windows PowerShell 5.1 would otherwise abort on harmless
# stderr output from docker/git. Every native command is checked via $LASTEXITCODE.
$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)

docker version --format "{{.Server.Version}}" *> $null
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: Docker is not running. Start Docker Desktop first." -ForegroundColor Red; exit 1 }

Write-Host "==> Building test image and running pytest" -ForegroundColor Cyan
if ($PytestArgs) {
  $extra = $PytestArgs -split ' ' | Where-Object { $_ }
  docker compose --profile test run --rm --build tests python -m pytest -p no:cacheprovider @extra
} else {
  docker compose --profile test run --rm --build tests
}
$code = $LASTEXITCODE

Write-Host "==> Removing the temporary test database" -ForegroundColor Cyan
docker compose --profile test rm --stop --force db-test *> $null

if ($code -eq 0) { Write-Host "All tests passed." -ForegroundColor Green }
else { Write-Host "Tests FAILED (exit code $code)." -ForegroundColor Red }
exit $code
