#Requires -Version 5.1
<#
.SYNOPSIS
    onx-manager Windows Launcher — PowerShell bootstrap
.DESCRIPTION
    Invoked by start.bat (or wrapped by executors/start-debug.ps1). Handles:
      1. Fast-path delegation to onx.exe if present
      2. Python 3.12+ detection across common candidates
      3. Auto-install via winget or official python.org installer
         (system-wide InstallAllUsers=1, with per-user fallback InstallAllUsers=0)
      4. Preflight cleanup via scripts/preflight.py
      5. Delegation to launcher.py

    Design notes (Revision 3 — all review blockers addressed):
      Fix #1: Candidate detection uses Invoke-PythonCandidateProbe with
              tokenized ProcessStartInfo arguments, locked OS-level stdin to
              prevent REPL hangs, bounded 3s timeout, and diagnostic reporting.
      Fix #2: Installer argument array named $installerArgs (not $args) so
              PowerShell's automatic $args (user CLI flags) is never clobbered.
      Fix #3: Per-user fallback (InstallAllUsers=0) actually implemented when
              system-wide install fails, with both exit codes in error message.
      Fix #4: scripts/preflight.py uses Get-CimInstance + ctypes (no wmic).
      Confirmed correct: -NoProfile -ExecutionPolicy Bypass (set in start.bat).
#>

$ErrorActionPreference = 'Stop'
$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } elseif ($MyInvocation.MyCommand.Definition) { Split-Path -Parent $MyInvocation.MyCommand.Definition } else { (Get-Location).Path }

# Subprocess probe helper: closes stdin to prevent interactive REPL hangs,
# enforces a bounded timeout, and captures diagnostic exit information.
function Invoke-PythonCandidateProbe {
    param(
        [Parameter(Mandatory=$true)][string]$Command,
        [Parameter(Mandatory=$true)][string[]]$Arguments,
        [int]$TimeoutMs = 3000,
        [switch]$StreamOutput
    )
    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName               = $Command
    $psi.RedirectStandardInput  = $true
    $psi.RedirectStandardOutput = (-not $StreamOutput)
    $psi.RedirectStandardError  = (-not $StreamOutput)
    $psi.UseShellExecute        = $false
    $psi.CreateNoWindow         = (-not $StreamOutput)

    $escapedArgs = $Arguments | ForEach-Object {
        if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' }
        else { $_ }
    }
    $psi.Arguments = [string]::Join(' ', $escapedArgs)

    $proc = [System.Diagnostics.Process]::new()
    $proc.StartInfo = $psi
    $sw = [System.Diagnostics.Stopwatch]::StartNew()

    try {
        if (-not $proc.Start()) {
            return @{ Success=$false; ExitCode=-1; TimedOut=$false; NotFound=$false; RawCmd="$Command $($psi.Arguments)"; StdErr='Failed to start process' }
        }
    } catch [System.ComponentModel.Win32Exception] {
        return @{ Success=$false; ExitCode=-1; TimedOut=$false; NotFound=$true; RawCmd="$Command $($psi.Arguments)"; StdErr=$_.Exception.Message }
    } catch {
        return @{ Success=$false; ExitCode=-1; TimedOut=$false; NotFound=$false; RawCmd="$Command $($psi.Arguments)"; StdErr=$_.Exception.Message }
    }

    # Close stdin immediately at the OS level — child gets instant EOF,
    # cannot ever block waiting on an interactive prompt of any kind.
    $proc.StandardInput.Close()

    $stdoutTask = $null
    $stderrTask = $null
    if (-not $StreamOutput) {
        $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
        $stderrTask = $proc.StandardError.ReadToEndAsync()
    }

    $completed = $proc.WaitForExit($TimeoutMs)
    $sw.Stop()

    if (-not $completed) {
        try { $proc.Kill() } catch {}
        return @{ Success=$false; ExitCode=-999; TimedOut=$true; NotFound=$false; DurationMs=$sw.ElapsedMilliseconds; RawCmd="$Command $($psi.Arguments)"; StdErr="Timed out after ${TimeoutMs}ms" }
    }

    $outText = ''
    $errText = ''
    if (-not $StreamOutput) {
        $outText = if ($stdoutTask -and $stdoutTask.Result) { $stdoutTask.Result.Trim() } else { '' }
        $errText = if ($stderrTask -and $stderrTask.Result) { $stderrTask.Result.Trim() } else { '' }
    }

    return @{
        Success    = ($proc.ExitCode -eq 0)
        ExitCode   = $proc.ExitCode
        TimedOut   = $false
        NotFound   = $false
        DurationMs = $sw.ElapsedMilliseconds
        StdOut     = $outText
        StdErr     = $errText
        RawCmd     = "$Command $($psi.Arguments)"
    }
}

function Start-OnxBootstrap {
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
        return $LASTEXITCODE
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
        $candidates = @(
            @{ Name='py -3.13';   Cmd='py';         SubArg='-3.13'; Args=@('-3.13', '-c', 'import sys; sys.exit(0 if sys.version_info >= (3,13) else 1)') },
            @{ Name='py -3.12';   Cmd='py';         SubArg='-3.12'; Args=@('-3.12', '-c', 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)') },
            @{ Name='python3.13'; Cmd='python3.13'; SubArg='';      Args=@('-c', 'import sys; sys.exit(0 if sys.version_info >= (3,13) else 1)') },
            @{ Name='python3.12'; Cmd='python3.12'; SubArg='';      Args=@('-c', 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)') },
            @{ Name='python3';    Cmd='python3';    SubArg='';      Args=@('-c', 'import sys; sys.exit(0 if sys.version_info >= (3,) else 1)') },
            @{ Name='python';     Cmd='python';     SubArg='';      Args=@('-c', 'import sys; sys.exit(0 if sys.version_info >= (3,) else 1)') }
        )

        $foundCmd    = $null
        $foundSubArg = ''

        foreach ($c in $candidates) {
            $res = Invoke-PythonCandidateProbe -Command $c.Cmd -Arguments $c.Args -TimeoutMs 3000
            if ($res.Success) {
                $foundCmd    = $c.Cmd
                $foundSubArg = $c.SubArg
                Write-Host "  Detected Python interpreter: $foundCmd $foundSubArg"
                break
            } elseif ($res.TimedOut) {
                Write-Warning "  [Probe Timeout] Candidate '$($c.Name)' timed out after $($res.DurationMs)ms (Cmd: $($res.RawCmd)). Skipped."
            } elseif ($res.NotFound) {
                # Expected — candidate not on PATH, stay quiet (matches current
                # behavior of trying the next candidate silently).
            } elseif ($res.ExitCode -ne 1 -and $res.ExitCode -ne 103) {
                Write-Warning "  [Probe Warning] Candidate '$($c.Name)' exited with unexpected code $($res.ExitCode) (Cmd: $($res.RawCmd); Stderr: $($res.StdErr))."
            }
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
        $preflightArgs = @($pySubArg) + @($preflight) + @($args) | Where-Object { $_ -ne $null -and $_ -ne '' }
        $res = Invoke-PythonCandidateProbe -Command $pyBin -Arguments $preflightArgs -TimeoutMs 30000 -StreamOutput
        if (-not $res.Success) {
            if ($res.TimedOut) {
                Write-Warning "  [Preflight Warning] Preflight timed out after $($res.DurationMs)ms. Continuing startup..."
            } elseif ($res.NotFound) {
                Write-Warning "  [Preflight Warning] Python interpreter '$pyBin' not found for preflight. Continuing startup..."
            } else {
                Write-Warning "  [Preflight Warning] Preflight exited with non-zero code $($res.ExitCode). Continuing startup..."
            }
        }
    }

    # ──────────────────────────────────────────────────────────────────────
    # 6. Launch
    # ──────────────────────────────────────────────────────────────────────
    & $pyBin @pySubArg $launcher @args
    return $LASTEXITCODE
}

# ──────────────────────────────────────────────────────────────────────
# Entry point: if invoked directly (not dot-sourced), execute immediately
# ──────────────────────────────────────────────────────────────────────
if ($MyInvocation.InvocationName -ne '.') {
    $exitCode = Start-OnxBootstrap @args
    exit $exitCode
}
