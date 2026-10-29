<#
.SYNOPSIS
  Run the tests, then commit and push your changes to main (which triggers CI/CD).

.DESCRIPTION
  Nothing is pushed unless you run this script yourself AND every test passes.
  Steps: check branch -> run tests in Docker -> git add -> git commit -> git push origin main.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\publish.ps1 -Message "Add priority filter to calendar"
#>
param([Parameter(Mandatory = $true)][string]$Message)

# "Continue" (not "Stop"): Windows PowerShell 5.1 would otherwise abort on harmless
# stderr output from docker/git. Every native command is checked via $LASTEXITCODE.
$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Fail($m) { Write-Host "ERROR: $m" -ForegroundColor Red; exit 1 }

git rev-parse --is-inside-work-tree *> $null
if ($LASTEXITCODE -ne 0) { Fail "This folder is not a Git repository. See README section 22." }

$branch = (git branch --show-current).Trim()
if ($branch -ne "main") { Fail "You are on branch '$branch'. Switch with: git switch main" }

if (git ls-files --error-unmatch .env 2>$null) { Fail ".env is tracked by Git! Run: git rm --cached .env   then commit again." }

$pending = git status --porcelain
if (-not $pending) { Write-Host "Nothing to commit. Working tree is clean." -ForegroundColor Yellow; exit 0 }

Write-Host "==> Running tests before publishing" -ForegroundColor Cyan
& "$PSScriptRoot\run-tests.ps1"
if ($LASTEXITCODE -ne 0) { Fail "Tests failed. Nothing was committed or pushed." }

Write-Host "==> Committing" -ForegroundColor Cyan
git add .
git commit -m $Message
if ($LASTEXITCODE -ne 0) { Fail "git commit failed." }

Write-Host "==> Pushing to origin/main" -ForegroundColor Cyan
git push origin main
if ($LASTEXITCODE -ne 0) { Fail "git push failed. If the remote has new commits, run: git pull --rebase origin main" }

Write-Host "Pushed. Watch the pipeline under the 'Actions' tab of your GitHub repository." -ForegroundColor Green
Write-Host "The live site updates only after the 'Deploy to cloud server' job finishes successfully."
