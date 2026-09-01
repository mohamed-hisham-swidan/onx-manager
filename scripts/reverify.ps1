#Requires -Version 5.1
# Windows equivalent of scripts/reverify (bash): a local one-shot runner
# mirroring .github/workflows/verification-cadence.yml exactly —
# all 5 check scripts + full backend pytest, then frontend
# typecheck/lint/test/build.
#
# NOTE: this mirrors the CHECKS verification-cadence.yml runs. It does not
# modify or replace that workflow (Linux-only, scheduled weekly). Keep this
# script's step list in sync with verification-cadence.yml by hand if that
# workflow's steps change — there is currently no single source both
# generate from.

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

function Step($name, $scriptBlock) {
    Write-Host "==> $name" -ForegroundColor Cyan
    & $scriptBlock
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $name" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

Set-Location (Join-Path $repoRoot "backend")

Step "check-version-propagation" { python ../scripts/check-version-propagation }
Step "check-db-revision"         { python ../scripts/check-db-revision }
Step "check-ruff-baseline"       { python ../scripts/check-ruff-baseline }
Step "check-route-contract"      { python ../scripts/check-route-contract }

Set-Location $repoRoot
Step "check-ps1-bom" { python scripts/check-ps1-bom }

Set-Location (Join-Path $repoRoot "backend")
Step "backend pytest (full suite)" { python -m pytest }

Set-Location (Join-Path $repoRoot "frontend")
Step "frontend typecheck" { npm run typecheck }
Step "frontend lint"      { npm run lint }
Step "frontend test"      { npm run test }
Step "frontend build"     { npm run build }

Set-Location $repoRoot
Write-Host "All checks passed." -ForegroundColor Green
