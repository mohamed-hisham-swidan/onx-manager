#Requires -Version 5.1
# Windows equivalent of scripts/test (bash): cd backend && python -m pytest "$@"

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $repoRoot "backend")

python -m pytest @args
exit $LASTEXITCODE
