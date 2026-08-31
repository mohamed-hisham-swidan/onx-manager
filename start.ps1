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

    Design notes (Revision 5 — Task-based stream draining for PowerShell 5.1):
      Fix #1: Candidate detection uses Invoke-PythonCandidateProbe with
              tokenized ProcessStartInfo arguments, locked OS-level stdin to
              prevent REPL hangs, bounded 3s timeout, and diagnostic reporting.
      Fix #2: Installer argument array named $installerArgs (not $args) so
              PowerShell's automatic $args (user CLI flags) is never clobbered.
      Fix #3: Per-user fallback (InstallAllUsers=0) actually implemented when
              system-wide install fails, with both exit codes in error message.
      Fix #4: scripts/preflight.py uses Get-CimInstance + ctypes (no wmic).
      Fix #5: Long-running launcher.py executed via Invoke-OnxPythonProcess
              (System.Diagnostics.Process with stdin closed, Task-based live
              stdout/stderr streaming avoiding threadpool runspace crashes,
              unbuffered output via PYTHONUNBUFFERED=1, Ctrl+C tree cleanup,
              and diagnostic logging).
      Confirmed correct: -NoProfile -ExecutionPolicy Bypass (set in start.bat).
#>

$ErrorActionPreference = 'Stop'
$env:PYTHONUNBUFFERED  = '1'
$env:PYTHONIOENCODING  = 'utf-8'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding  = [System.Text.Encoding]::UTF8

# Enable Win32 Virtual Terminal Processing (ANSI color & UTF-8 control codes) on Windows
if ($IsWindows -or $env:OS -eq 'Windows_NT') {
    try {
        $kernel32 = Add-Type -MemberDefinition @"
            [DllImport("kernel32.dll", SetLastError = true)]
            public static extern IntPtr GetStdHandle(int nStdHandle);

            [DllImport("kernel32.dll", SetLastError = true)]
            public static extern bool GetConsoleMode(IntPtr hConsoleHandle, out uint lpMode);

            [DllImport("kernel32.dll", SetLastError = true)]
            public static extern bool SetConsoleMode(IntPtr hConsoleHandle, uint dwMode);

            [DllImport("kernel32.dll", SetLastError = true)]
            public static extern bool SetConsoleOutputCP(uint wCodePageID);

            [DllImport("kernel32.dll", SetLastError = true)]
            public static extern bool SetConsoleCP(uint wCodePageID);
"@ -Name "Win32ConsoleHelper" -Namespace "OnxWin32" -PassThru

        $null = $kernel32::SetConsoleOutputCP(65001)
        $null = $kernel32::SetConsoleCP(65001)

        $stdOutHandle = $kernel32::GetStdHandle(-11) # STD_OUTPUT_HANDLE
        $outMode = 0
        if ($kernel32::GetConsoleMode($stdOutHandle, [ref]$outMode)) {
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            $null = $kernel32::SetConsoleMode($stdOutHandle, $outMode -bor 0x0004)
        }
    } catch {}
}

$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } elseif ($MyInvocation.MyCommand.Definition) { Split-Path -Parent $MyInvocation.MyCommand.Definition } else { (Get-Location).Path }

# Dedicated argument escaping helper for Windows CLI (CommandLineToArgvW convention)
# Handles: spaces/tabs, inner quotes, trailing backslashes, and empty strings.
function Format-OnxProcessArgument {
    param([string]$Arg)
    if ([string]::IsNullOrEmpty($Arg)) {
        return '""'
    }
    if ($Arg -notmatch '[\s\t\n\v"]') {
        return $Arg
    }
    # Double backslashes preceding quotes: 2N backslashes + \"
    $escaped = [System.Text.RegularExpressions.Regex]::Replace($Arg, '(\\*)(")', {
        param($m)
        return ('\' * ($m.Groups[1].Length * 2)) + '\"'
    })
    # Double trailing backslashes at end of string before enclosing quotes: 2N backslashes
    $escaped = [System.Text.RegularExpressions.Regex]::Replace($escaped, '(\\+)$', {
        param($m)
        return '\' * ($m.Groups[1].Length * 2)
    })
    return '"' + $escaped + '"'
}

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
    $psi.RedirectStandardOutput = if ($StreamOutput) { $false } else { $true }
    $psi.RedirectStandardError  = if ($StreamOutput) { $false } else { $true }
    $psi.UseShellExecute        = $false
    $psi.CreateNoWindow         = if ($StreamOutput) { $false } else { $true }
    $psi.EnvironmentVariables['PYTHONUNBUFFERED'] = '1'
    $psi.EnvironmentVariables['PYTHONIOENCODING'] = 'utf-8'

    $escapedArgs = $Arguments | ForEach-Object { Format-OnxProcessArgument $_ }
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

# Dedicated process execution helper for long-running launcher.py
function Invoke-OnxPythonProcess {
    param(
        [Parameter(Mandatory=$true)][string]$Command,
        [Parameter(Mandatory=$true)][string[]]$Arguments,
        [string]$WorkingDirectory = $scriptDir
    )

    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName               = $Command
    $psi.WorkingDirectory       = $WorkingDirectory
    $psi.RedirectStandardInput  = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError  = $true
    $psi.UseShellExecute        = $false
    $psi.CreateNoWindow         = $true
    $psi.EnvironmentVariables['PYTHONUNBUFFERED'] = '1'
    $psi.EnvironmentVariables['PYTHONIOENCODING'] = 'utf-8'

    $escapedArgs = $Arguments | ForEach-Object { Format-OnxProcessArgument $_ }
    $psi.Arguments = [string]::Join(' ', $escapedArgs)

    if ($env:ONX_DEBUG -eq '1') {
        Write-Host "  [Launcher] executable: $Command" -ForegroundColor Cyan
        Write-Host "  [Launcher] arguments: $($psi.Arguments)" -ForegroundColor Cyan
        Write-Host "  [Launcher] working directory: $WorkingDirectory" -ForegroundColor Cyan
    }

    $proc = [System.Diagnostics.Process]::new()
    $proc.StartInfo = $psi
    $sw = [System.Diagnostics.Stopwatch]::StartNew()

    try {
        if (-not $proc.Start()) {
            Write-Error "  [Launcher] Failed to start process for '$Command' with arguments '$($psi.Arguments)'"
            return 1
        }
    } catch {
        Write-Error "  [Launcher] Exception starting process '$Command' with arguments '$($psi.Arguments)' in '$WorkingDirectory': $_"
        return 1
    }

    if ($env:ONX_DEBUG -eq '1') {
        Write-Host "  [Launcher] PID: $($proc.Id)" -ForegroundColor Cyan
    }

    # Close stdin immediately — launcher.py does not read from stdin,
    # preventing any accidental interactive prompt or REPL hang.
    $proc.StandardInput.Close()

    $outReader = $proc.StandardOutput
    $errReader = $proc.StandardError
    $outTask   = $outReader.ReadLineAsync()
    $errTask   = $errReader.ReadLineAsync()

    try {
        # Stream stdout and stderr live on the main thread while process runs
        while ($outTask -ne $null -or $errTask -ne $null) {
            $didWork = $false

            if ($outTask -ne $null -and $outTask.IsCompleted) {
                $line = $outTask.Result
                if ($line -ne $null) {
                    [Console]::Out.WriteLine($line)
                    $outTask = $outReader.ReadLineAsync()
                } else {
                    $outTask = $null
                }
                $didWork = $true
            }

            if ($errTask -ne $null -and $errTask.IsCompleted) {
                $line = $errTask.Result
                if ($line -ne $null) {
                    [Console]::Error.WriteLine($line)
                    $errTask = $errReader.ReadLineAsync()
                } else {
                    $errTask = $null
                }
                $didWork = $true
            }

            if (-not $didWork) {
                [System.Threading.Thread]::Sleep(10)
            }
        }

        # Ensure process has fully exited
        $proc.WaitForExit()
    } finally {
        # If interrupted (e.g. Ctrl+C), allow child graceful exit grace window or clean up process tree
        if (-not $proc.HasExited) {
            $exited = $proc.WaitForExit(3000)
            if (-not $exited -and -not $proc.HasExited) {
                Write-Warning "  [Launcher] Process PID $($proc.Id) did not exit cleanly; terminating process tree..."
                try {
                    & taskkill /F /T /PID $proc.Id 2>$null | Out-Null
                } catch {}
                try { $proc.Kill() } catch {}
            }
        }
    }

    $sw.Stop()
    $exitCode = $proc.ExitCode
    if ($env:ONX_DEBUG -eq '1') {
        Write-Host "  [Launcher] exit code: $exitCode" -ForegroundColor Cyan
        Write-Host "  [Launcher] duration: $($sw.ElapsedMilliseconds)ms" -ForegroundColor Cyan
    }

    return $exitCode
}

function Start-OnxBootstrap {
    if ($env:ONX_DEBUG -eq '1') {
        Write-Host "========================================" -ForegroundColor Cyan
        Write-Host "  onx-manager — Windows Launcher" -ForegroundColor Cyan
        Write-Host "========================================" -ForegroundColor Cyan
        Write-Host "  Directory: $scriptDir"
    }

    # ──────────────────────────────────────────────────────────────────────
    # 1. Fast path: pre-built onx.exe
    # ──────────────────────────────────────────────────────────────────────
    $onxExe = Join-Path $scriptDir 'onx.exe'
    if (Test-Path $onxExe) {
        if ($env:ONX_DEBUG -eq '1') {
            Write-Host "  Found pre-built onx.exe — launching directly..."
        }
        & $onxExe @args
        return $LASTEXITCODE
    }

    # ──────────────────────────────────────────────────────────────────────
    # 2. Resolve Python interpreter
    # ──────────────────────────────────────────────────────────────────────
    $venvPy = Join-Path $scriptDir 'backend\.venv\Scripts\python.exe'

    if (Test-Path $venvPy) {
        # Venv already exists — use it directly (no sub-arg needed)
        if ($env:ONX_DEBUG -eq '1') {
            Write-Host "  Using virtual environment: $venvPy"
        }
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
                if ($env:ONX_DEBUG -eq '1') {
                    Write-Host "  Detected Python interpreter: $foundCmd $foundSubArg"
                }
                break
            } elseif ($res.TimedOut) {
                Write-Warning "  [Probe Timeout] Candidate '$($c.Name)' timed out after $($res.DurationMs)ms (Cmd: $($res.RawCmd)). Skipped."
            } elseif ($res.NotFound) {
                # Expected — candidate not on PATH, stay quiet
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

        # ──────────────────────────────────────────────────────────────────
        # 3b. Probe for Node.js 18+ and npm
        # ──────────────────────────────────────────────────────────────────
        $localNode = Join-Path $scriptDir '.onx\node'
        if (Test-Path (Join-Path $localNode 'node.exe')) {
            $env:Path = "$localNode;$($env:Path)"
        }

        $nodeProbe = Invoke-PythonCandidateProbe -Command 'node' -Arguments @('-v') -TimeoutMs 2000
        if ($nodeProbe.Success) {
            if ($env:ONX_DEBUG -eq '1') {
                $nodeVer = ($nodeProbe.StdOut).Trim()
                Write-Host "  Detected Node.js runtime: $nodeVer"
            }
        }
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
        $preflightArgs = @($pySubArg) + @($preflight) + @($args) | Where-Object { $_ -ne $null -and $_ -ne '' }
        $streamPreflight = ($env:ONX_DEBUG -eq '1')
        $res = Invoke-PythonCandidateProbe -Command $pyBin -Arguments $preflightArgs -TimeoutMs 30000 -StreamOutput:$streamPreflight
        if (-not $res.Success) {
            if ($res.TimedOut) {
                Write-Warning "  [Preflight Warning] Preflight timed out after $($res.DurationMs)ms. Continuing startup..."
            } elseif ($res.NotFound) {
                Write-Warning "  [Preflight Warning] Python interpreter '$pyBin' not found for preflight. Continuing startup..."
            } else {
                Write-Warning "  [Preflight Warning] Preflight exited with non-zero code $($res.ExitCode). Continuing startup..."
                if ($res.StdErr) {
                    Write-Warning "  $($res.StdErr)"
                }
            }
        }
    }

    # ──────────────────────────────────────────────────────────────────────
    # 6. Launch
    # ──────────────────────────────────────────────────────────────────────
    $launcherArgs = @($pySubArg) + @($launcher) + @($args) | Where-Object { $_ -ne $null -and $_ -ne '' }
    $exitCode = Invoke-OnxPythonProcess -Command $pyBin -Arguments $launcherArgs -WorkingDirectory $scriptDir
    return $exitCode
}

# ──────────────────────────────────────────────────────────────────────
# Entry point: if invoked directly (not dot-sourced), execute immediately
# ──────────────────────────────────────────────────────────────────────
if ($MyInvocation.InvocationName -ne '.') {
    $exitCode = Start-OnxBootstrap @args
    exit $exitCode
}
