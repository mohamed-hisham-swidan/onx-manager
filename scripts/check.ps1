#Requires -Version 5.1
# Windows equivalent of scripts/check (bash): runs lint -> typecheck -> test, stopping at the first failure.

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $repoRoot "backend")

Write-Host "==> lint (ruff check .)" -ForegroundColor Cyan
ruff check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> typecheck (pyright)" -ForegroundColor Cyan
pyright
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> test (pytest)" -ForegroundColor Cyan
python -m pytest
exit $LASTEXITCODE
