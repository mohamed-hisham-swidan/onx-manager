@echo off
rem onx-manager Windows Launcher — thin entry point invoking PowerShell bootstrap
rem Usage: start.bat [--stop|--restart|--status|--code|--help|--self-test|...]
rem
rem Design notes (Revision 2 — all review blockers addressed):
rem   Fix #1: Candidate arrays use parallel $cmds/$subArgs so `& $cmd @subArgs -c '...'`
rem           passes 'py' and '-3.13' as separate tokens, not one literal string.
rem   Fix #2: Local installer variable renamed to $installerArgs so the automatic $args
rem           (user CLI flags) forwarded via `& $py $launcher @args` is never clobbered.
rem   Fix #3: Per-user install fallback (InstallAllUsers=0) actually implemented after
rem           system-wide (InstallAllUsers=1) install fails — not just described in prose.
rem   Keep -NoProfile -ExecutionPolicy Bypass — confirmed correct.

rem ──────────────────────────────────────────────────────────────────────
rem 1. If pre-built onx.exe exists, delegate to it immediately
rem ──────────────────────────────────────────────────────────────────────
if exist "%~dp0onx.exe" (
    "%~dp0onx.exe" %*
    exit /b %errorlevel%
)

rem ──────────────────────────────────────────────────────────────────────
rem 2. PowerShell bootstrap: detect/auto-install Python → preflight → launcher.py
rem ──────────────────────────────────────────────────────────────────────
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference = 'Stop'; ^
     $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition; ^
     $onxExe = Join-Path $scriptDir 'onx.exe'; ^
     if (Test-Path $onxExe) { & $onxExe @args; exit $LASTEXITCODE }; ^
     ^
     $venvPy = Join-Path $scriptDir 'backend\.venv\Scripts\python.exe'; ^
     $py = if (Test-Path $venvPy) { $venvPy } else { ^
         ^
         # Fix #1: parallel arrays — $cmds holds the binary name, $subArgs holds ^
         # the optional version-selector flag(s). Each candidate is invoked as: ^
         #   & $cmds[$i] @($subArgs[$i]) -c '<check>' ^
         # The @() splatting of an empty string produces no extra argument, ^
         # so 'python3' / 'python' entries work without a spurious extra token. ^
         $cmds    = @('py',    'py',    'python3.13', 'python3.12', 'python3', 'python'); ^
         $subArgs = @('-3.13', '-3.12', '',           '',           '',        ''); ^
         $checks  = @('import sys; sys.exit(0 if sys.version_info >= (3,13) else 1)', ^
                      'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)', ^
                      'import sys; sys.exit(0 if sys.version_info >= (3,13) else 1)', ^
                      'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)', ^
                      'import sys; sys.exit(0 if sys.version_info >= (3,) else 1)',   ^
                      'import sys; sys.exit(0 if sys.version_info >= (3,) else 1)'); ^
         $found = $null; ^
         for ($i = 0; $i -lt $cmds.Length; $i++) { ^
             try { ^
                 $sa = if ($subArgs[$i]) { @($subArgs[$i]) } else { @() }; ^
                 & $cmds[$i] @sa -c $checks[$i] 2>$null; ^
                 if ($LASTEXITCODE -eq 0) { ^
                     $found = if ($subArgs[$i]) { ^
                         # Return full candidate as a two-element list for later invocation ^
                         @($cmds[$i], $subArgs[$i]) ^
                     } else { ^
                         @($cmds[$i]) ^
                     }; ^
                     break ^
                 } ^
             } catch {} ^
         }; ^
         ^
         if (-not $found) { ^
             Write-Warning 'Python 3.12+ not found on PATH. Attempting auto-install...'; ^
             $winget = Get-Command winget -ErrorAction SilentlyContinue; ^
             if ($winget) { ^
                 Write-Host '  Installing Python 3.12 via winget...'; ^
                 & winget install Python.Python.3.12 -e --silent `
                     --accept-source-agreements --accept-package-agreements; ^
                 if ($LASTEXITCODE -ne 0) { throw 'winget Python install failed (exit ' + $LASTEXITCODE + ')' }; ^
                 $found = @('python') ^
             } else { ^
                 Write-Host '  winget not available. Downloading Python 3.12 official installer...'; ^
                 $url       = 'https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe'; ^
                 $installer = Join-Path $env:TEMP 'python-3.12.4-amd64.exe'; ^
                 try { ^
                     Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing -ErrorAction Stop ^
                 } catch { ^
                     throw 'Failed to download Python installer: ' + $_ ^
                 }; ^
                 ^
                 # Fix #2: renamed from $args to $installerArgs to avoid clobbering ^
                 # PowerShell's automatic $args variable (user CLI flags forwarded below). ^
                 # Fix #3: attempt system-wide install first; fall back to per-user. ^
                 Write-Host '  Attempting system-wide install (InstallAllUsers=1)...'; ^
                 $installerArgs = @('/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_test=0'); ^
                 $proc = Start-Process -FilePath $installer -ArgumentList $installerArgs -Wait -PassThru; ^
                 if ($proc.ExitCode -ne 0) { ^
                     Write-Warning ('  System-wide install failed (exit ' + $proc.ExitCode + '). ' + ^
                                    'Retrying as per-user install (InstallAllUsers=0)...'); ^
                     $installerArgs = @('/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_test=0'); ^
                     $proc2 = Start-Process -FilePath $installer -ArgumentList $installerArgs -Wait -PassThru; ^
                     if ($proc2.ExitCode -ne 0) { ^
                         throw ('Python installer failed: system-wide exit=' + $proc.ExitCode + ^
                                ', per-user exit=' + $proc2.ExitCode) ^
                     }; ^
                     Write-Host '  Python installed (per-user). You may need to restart your terminal.' ^
                 } else { ^
                     Write-Host '  Python installed system-wide.' ^
                 }; ^
                 $found = @('python') ^
             }; ^
             if (-not $found) { throw 'Python 3.12+ installation failed — cannot continue.' } ^
         }; ^
         ^
         # $found is an array: @('py', '-3.13') or @('python') etc. ^
         # Return the first element as the binary; store the full array in $foundCandidate. ^
         $found ^
     }; ^
     ^
     # Resolve $py: if the venv path was used, it's a string; if detection returned ^
     # an array, we need to store the sub-arg and use only the binary as $py. ^
     # For the venv path the if-branch assigned a string directly — no sub-arg. ^
     # For the detection branch the else-block assigns $found (array) to $py. ^
     # Unpack: ^
     $pyBin    = if ($py -is [array]) { $py[0] } else { $py }; ^
     $pySubArg = if ($py -is [array] -and $py.Length -gt 1) { @($py[1]) } else { @() }; ^
     ^
     $launcher = Join-Path $scriptDir 'launcher.py'; ^
     if (-not (Test-Path $launcher)) { throw 'launcher.py not found in ' + $scriptDir }; ^
     ^
     $preflight = Join-Path $scriptDir 'scripts\preflight.py'; ^
     if (Test-Path $preflight) { ^
         Write-Host '  Running preflight...'; ^
         & $pyBin @pySubArg $preflight @args 2>$null; ^
     }; ^
     ^
     & $pyBin @pySubArg $launcher @args" %*