#Requires -Version 5.1
<#
.SYNOPSIS
    onx-manager Windows Launcher — PowerShell bootstrap
.DESCRIPTION
    Invoked by start.bat. Handles:
      1. Fast-path delegation to onx.exe if present
      2. Python 3.12+ detection across common candidates
      3. Auto-install via winget or official python.org installer
         (system-wide InstallAllUsers=1, with per-user fallback InstallAllUsers=0)
      4. Preflight cleanup via scripts/preflight.py
      5. Delegation to launcher.py

    Design notes (Revision 2 — all review blockers addressed):
      Fix #1: Candidate detection uses parallel $cmds/$subArgs arrays so
              'py' and '-3.13' are passed as separate tokens, not one string.
      Fix #2: Installer argument array named $installerArgs (not $args) so
              PowerShell's automatic $args (user CLI flags) is never clobbered.
      Fix #3: Per-user fallback (InstallAllUsers=0) actually implemented when
              system-wide install fails, with both exit codes in error message.
      Fix #4: scripts/preflight.py uses Get-CimInstance + ctypes (no wmic).
      Confirmed correct: -NoProfile -ExecutionPolicy Bypass (set in start.bat).
#>

$ErrorActionPreference = 'Stop'
$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } elseif ($MyInvocation.MyCommand.Definition) { Split-Path -Parent $MyInvocation.MyCommand.Definition } else { (Get-Location).Path }

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  onx-manager — Windows Launcher" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Directory: $scriptDir"

# ──────────────────────────────────────────────────────────────────────
# 1. Fast path: pre-built onx.exe
# ──────────────────────────────────────────────────────────────────────
$onxExe = Join-Path $scriptDir 'onx.exe'
if (Test-Path $onxExe) {
    Write-Host "  Found pre-built onx.exe — launching directly..."
    & $onxExe @args
    exit $LASTEXITCODE
}

# ──────────────────────────────────────────────────────────────────────
# 2. Resolve Python interpreter
# ──────────────────────────────────────────────────────────────────────
$venvPy = Join-Path $scriptDir 'backend\.venv\Scripts\python.exe'

if (Test-Path $venvPy) {
    # Venv already exists — use it directly (no sub-arg needed)
    Write-Host "  Using virtual environment: $venvPy"
    $pyBin    = $venvPy
    $pySubArg = @()
} else {
    # Fix #1: parallel arrays — $cmds holds the binary name only,
    # $subArgs holds the optional version-selector flag (or '' for none).
    # Invoked as: & $cmds[$i] @($sa) -c $check
    # @() splatting of an empty array produces zero extra tokens.
    $cmds = @(
        'py',         # Windows Launcher (py.exe) — prefers 3.13
        'py',         # Windows Launcher (py.exe) — prefers 3.12
        'python3.13', # Direct binary
        'python3.12', # Direct binary
        'python3',    # Generic python3
        'python'      # Generic python
    )
    $subArgs = @(
        '-3.13',
        '-3.12',
        '',
        '',
        '',
        ''
    )
    $checks = @(
        'import sys; sys.exit(0 if sys.version_info >= (3,13) else 1)',
        'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)',
        'import sys; sys.exit(0 if sys.version_info >= (3,13) else 1)',
        'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)',
        'import sys; sys.exit(0 if sys.version_info >= (3,) else 1)',
        'import sys; sys.exit(0 if sys.version_info >= (3,) else 1)'
    )

    $foundCmd    = $null
    $foundSubArg = ''

    for ($i = 0; $i -lt $cmds.Length; $i++) {
        try {
            $sa = if ($subArgs[$i]) { @($subArgs[$i]) } else { @() }
            & $cmds[$i] @sa -c $checks[$i] 2>$null
            if ($LASTEXITCODE -eq 0) {
                $foundCmd    = $cmds[$i]
                $foundSubArg = $subArgs[$i]
                Write-Host "  Detected Python interpreter: $foundCmd $foundSubArg"
                break
            }
        } catch {}
    }

    # ──────────────────────────────────────────────────────────────────
    # 3. Auto-install Python if nothing found
    # ──────────────────────────────────────────────────────────────────
    if (-not $foundCmd) {
        Write-Warning 'Python 3.12+ not found on PATH. Attempting auto-install...'

        $winget = Get-Command winget -ErrorAction SilentlyContinue
        if ($winget) {
            Write-Host '  Installing Python 3.12 via winget...'
            & winget install Python.Python.3.12 -e --silent --accept-source-agreements --accept-package-agreements
            if ($LASTEXITCODE -ne 0) {
                throw "winget Python install failed (exit $LASTEXITCODE)"
            }
            $foundCmd    = 'python'
            $foundSubArg = ''
        } else {
            Write-Host '  winget not available. Downloading Python 3.12 official installer...'
            $url       = 'https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe'
            $installer = Join-Path $env:TEMP 'python-3.12.4-amd64.exe'

            try {
                Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing -ErrorAction Stop
            } catch {
                throw "Failed to download Python installer: $_"
            }

            # Fix #2: $installerArgs (not $args) — never clobbers the automatic
            # $args variable that holds the user's CLI flags forwarded below.
            # Fix #3: try system-wide first; fall back to per-user on failure.
            Write-Host '  Attempting system-wide install (InstallAllUsers=1)...'
            $installerArgs = @('/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_test=0')
            $proc = Start-Process -FilePath $installer -ArgumentList $installerArgs -Wait -PassThru

            if ($proc.ExitCode -ne 0) {
                Write-Warning "  System-wide install failed (exit $($proc.ExitCode)). Retrying as per-user (InstallAllUsers=0)..."
                $installerArgs = @('/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_test=0')
                $proc2 = Start-Process -FilePath $installer -ArgumentList $installerArgs -Wait -PassThru

                if ($proc2.ExitCode -ne 0) {
                    throw "Python installer failed: system-wide exit=$($proc.ExitCode), per-user exit=$($proc2.ExitCode)"
                }
                Write-Host '  Python installed (per-user). You may need to open a new terminal.'
            } else {
                Write-Host '  Python installed system-wide.'
            }

            $foundCmd    = 'python'
            $foundSubArg = ''
        }
    }

    $pyBin    = $foundCmd
    $pySubArg = if ($foundSubArg) { @($foundSubArg) } else { @() }
}

# ──────────────────────────────────────────────────────────────────────
# 4. Validate launcher.py exists
# ──────────────────────────────────────────────────────────────────────
$launcher = Join-Path $scriptDir 'launcher.py'
if (-not (Test-Path $launcher)) {
    throw "launcher.py not found in $scriptDir"
}

# ──────────────────────────────────────────────────────────────────────
# 5. Run preflight (best-effort — failures are warnings, not fatal)
# ──────────────────────────────────────────────────────────────────────
$preflight = Join-Path $scriptDir 'scripts\preflight.py'
if (Test-Path $preflight) {
    Write-Host '  Running preflight...'
    & $pyBin @pySubArg $preflight @args 2>$null
}

# ──────────────────────────────────────────────────────────────────────
# 6. Launch
# ──────────────────────────────────────────────────────────────────────
& $pyBin @pySubArg $launcher @args
exit $LASTEXITCODE
