#Requires -Version 5.1
<#
.SYNOPSIS
    onx-manager Windows Developer Launcher — PowerShell bootstrap
.DESCRIPTION
    Developer-only PowerShell bootstrap helper (`powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start.ps1`).
    End users should use the root `install.ps1` installer instead.
    Lives in scripts/start.ps1; derives $repoRoot from $PSScriptRoot parent.
    Handles:
      1. Python 3.12 detection across common candidates
      2. Auto-install via winget or official python.org installer
         (per-user InstallAllUsers=0 first, with system-wide fallback InstallAllUsers=1)
      3. Preflight cleanup via scripts/preflight.py
      4. Delegation to launcher.py

    Design notes (Revision 6 — Hardened Process-Execution Boundary):
      Spec: SPEC-2026-09-01-WIN-LAUNCHER-01

      New-OnxProcessStartInfo: Shared PSI factory — eliminates duplicated
              process configuration logic; enforces RedirectStandardInput=$true,
              RedirectStandardOutput/Error=$true, UseShellExecute=$false,
              PYTHONUNBUFFERED=1, PYTHONIOENCODING=utf-8, and
              CommandLineToArgvW argument escaping on every invocation.

      Invoke-OnxProcessProbe (replaces Invoke-PythonCandidateProbe):
              Bounded, buffered execution for short-lived processes (interpreter
              probes, Node probe, preflight). Enforces mandatory stdin lockdown,
              TimeoutMs hard limit, and process-tree kill via taskkill /F /T /PID
              on timeout (not only $proc.Kill(), which only kills the direct PID).
              Returns a full standardised result hashtable per spec section 7.

      Invoke-OnxProcessSupervised (replaces Invoke-OnxPythonProcess):
              Long-running launcher.py supervisor. Shares New-OnxProcessStartInfo;
              main-thread async ReadLineAsync() pump; graceful Ctrl+C tree cleanup.

      Fix #1: Candidate detection uses Invoke-OnxProcessProbe with
              tokenized ProcessStartInfo arguments, locked OS-level stdin to
              prevent REPL hangs, bounded 3s timeout, and diagnostic reporting.
      Fix #2: Installer argument array named $installerArgs (not $args) so
              PowerShell's automatic $args (user CLI flags) is never clobbered.
      Fix #3: Per-user install (InstallAllUsers=0) attempted first, with
              system-wide fallback (InstallAllUsers=1).
      Fix #4: scripts/preflight.py uses Get-CimInstance + ctypes (no wmic).
      Fix #5: Long-running launcher.py executed via Invoke-OnxProcessSupervised
              (System.Diagnostics.Process with stdin closed, Task-based live
              stdout/stderr streaming avoiding threadpool runspace crashes,
              unbuffered output via PYTHONUNBUFFERED=1, Ctrl+C tree cleanup,
              and diagnostic logging).
      Confirmed correct: -NoProfile -ExecutionPolicy Bypass (when invoked via powershell.exe).
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
$repoRoot  = Split-Path -Parent $scriptDir

# ------------------------------------------------------------------------------
# Format-OnxProcessArgument
# Dedicated argument escaping helper for Windows CLI (CommandLineToArgvW
# convention). Handles: spaces/tabs, inner quotes, trailing backslashes, and
# empty strings.
# ------------------------------------------------------------------------------
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

# ------------------------------------------------------------------------------
# New-OnxProcessStartInfo
# Shared PSI factory -- builds a standardised System.Diagnostics.ProcessStartInfo
# object with mandatory stdin/stdout/stderr redirection, UseShellExecute=$false,
# PYTHONUNBUFFERED=1, PYTHONIOENCODING=utf-8, and CommandLineToArgvW argument
# escaping. All subprocess creation in this launcher MUST go through this factory.
# ------------------------------------------------------------------------------
function New-OnxProcessStartInfo {
    param(
        [Parameter(Mandatory=$true)][string]$Command,
        [Parameter(Mandatory=$true)][string[]]$Arguments,
        [string]$WorkingDirectory = $repoRoot,
        [switch]$CreateNoWindow
    )

    [System.Diagnostics.ProcessStartInfo]$psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName               = $Command
    $psi.WorkingDirectory       = $WorkingDirectory
    $psi.RedirectStandardInput  = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError  = $true
    $psi.UseShellExecute        = $false
    $psi.CreateNoWindow         = if ($CreateNoWindow) { $true } else { $false }
    $psi.EnvironmentVariables['PYTHONUNBUFFERED'] = '1'
    $psi.EnvironmentVariables['PYTHONIOENCODING'] = 'utf-8'

    $escapedArgs = $Arguments | ForEach-Object { Format-OnxProcessArgument $_ }
    $psi.Arguments = [string]::Join(' ', $escapedArgs)

    return $psi
}

# ------------------------------------------------------------------------------
# Invoke-OnxProcessProbe
# Bounded, buffered execution for short-lived subprocesses (interpreter candidate
# probes, Node probe, preflight). Mandatory stdin lockdown, hard TimeoutMs limit,
# process-tree kill via taskkill /F /T /PID on timeout (reaps orphaned children
# such as py.exe spawning python.exe). Returns a standardised result hashtable
# per spec section 7.
# ------------------------------------------------------------------------------
function Invoke-OnxProcessProbe {
    param(
        [Parameter(Mandatory=$true)][string]$Command,
        [Parameter(Mandatory=$true)][string[]]$Arguments,
        [int]$TimeoutMs = 3000,
        [string]$WorkingDirectory = $repoRoot,
        [switch]$StreamOutput
    )

    [System.Diagnostics.ProcessStartInfo]$psi = New-OnxProcessStartInfo `
        -Command $Command `
        -Arguments $Arguments `
        -WorkingDirectory $WorkingDirectory `
        -CreateNoWindow

    # When streaming is requested we still keep stdin redirected (mandatory
    # lockdown) but allow stdout/stderr to flow directly to the console.
    if ($StreamOutput) {
        $psi.RedirectStandardOutput = $false
        $psi.RedirectStandardError  = $false
        $psi.CreateNoWindow         = $false
    }

    if ($env:ONX_DEBUG -eq '1') {
        Write-Host "  [Probe] executable:        $Command" -ForegroundColor Cyan
        Write-Host "  [Probe] arguments:         $($psi.Arguments)" -ForegroundColor Cyan
        Write-Host "  [Probe] working directory: $WorkingDirectory" -ForegroundColor Cyan
    }

    [System.Diagnostics.Process]$proc = [System.Diagnostics.Process]::new()
    $proc.StartInfo = $psi
    [System.Diagnostics.Stopwatch]$sw = [System.Diagnostics.Stopwatch]::StartNew()

    try {
        if (-not $proc.Start()) {
            return @{
                Success    = $false
                ExitCode   = -1
                TimedOut   = $false
                NotFound   = $false
                DurationMs = $sw.ElapsedMilliseconds
                StdOut     = ''
                StdErr     = 'Failed to start process'
                RawCmd     = "$Command $($psi.Arguments)"
            }
        }
    } catch [System.ComponentModel.Win32Exception] {
        return @{
            Success    = $false
            ExitCode   = -1
            TimedOut   = $false
            NotFound   = $true
            DurationMs = $sw.ElapsedMilliseconds
            StdOut     = ''
            StdErr     = $_.Exception.Message
            RawCmd     = "$Command $($psi.Arguments)"
        }
    } catch {
        return @{
            Success    = $false
            ExitCode   = -1
            TimedOut   = $false
            NotFound   = $false
            DurationMs = $sw.ElapsedMilliseconds
            StdOut     = ''
            StdErr     = $_.Exception.Message
            RawCmd     = "$Command $($psi.Arguments)"
        }
    }

    if ($env:ONX_DEBUG -eq '1') {
        Write-Host "  [Probe] PID: $($proc.Id)" -ForegroundColor Cyan
    }

    # Mandatory OS-level stdin lockdown -- child receives immediate EOF;
    # it cannot block waiting on an interactive prompt of any kind.
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
        # Process-tree kill: terminate the entire tree rooted at the spawned PID
        # so orphaned child processes (e.g. py.exe spawning python.exe) are reaped.
        try { & taskkill /F /T /PID $proc.Id 2>$null | Out-Null } catch {}
        try { $proc.Kill() } catch {}
        return @{
            Success    = $false
            ExitCode   = -999
            TimedOut   = $true
            NotFound   = $false
            DurationMs = $sw.ElapsedMilliseconds
            StdOut     = ''
            StdErr     = "Timed out after ${TimeoutMs}ms"
            RawCmd     = "$Command $($psi.Arguments)"
        }
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

# ------------------------------------------------------------------------------
# Invoke-OnxProcessSupervised
# Long-running launcher.py supervisor. Shares New-OnxProcessStartInfo factory.
# Main-thread async ReadLineAsync() pump provides live stdout/stderr streaming
# without PowerShell 5.1 threadpool runspace crashes. Graceful Ctrl+C cleanup
# terminates the full process tree via taskkill /F /T /PID.
# ------------------------------------------------------------------------------
function Invoke-OnxProcessSupervised {
    param(
        [Parameter(Mandatory=$true)][string]$Command,
        [Parameter(Mandatory=$true)][string[]]$Arguments,
        [string]$WorkingDirectory = $repoRoot
    )

    [System.Diagnostics.ProcessStartInfo]$psi = New-OnxProcessStartInfo `
        -Command $Command `
        -Arguments $Arguments `
        -WorkingDirectory $WorkingDirectory `
        -CreateNoWindow

    if ($env:ONX_DEBUG -eq '1') {
        Write-Host "  [Launcher] executable:        $Command" -ForegroundColor Cyan
        Write-Host "  [Launcher] arguments:         $($psi.Arguments)" -ForegroundColor Cyan
        Write-Host "  [Launcher] working directory: $WorkingDirectory" -ForegroundColor Cyan
    }

    [System.Diagnostics.Process]$proc = [System.Diagnostics.Process]::new()
    $proc.StartInfo = $psi
    [System.Diagnostics.Stopwatch]$sw = [System.Diagnostics.Stopwatch]::StartNew()

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

    # Mandatory OS-level stdin lockdown -- launcher.py does not read from stdin;
    # prevents any accidental interactive prompt or REPL hang.
    $proc.StandardInput.Close()

    $outReader = $proc.StandardOutput
    $errReader = $proc.StandardError
    $outTask   = $outReader.ReadLineAsync()
    $errTask   = $errReader.ReadLineAsync()

    try {
        # Stream stdout and stderr live on the main thread while process runs.
        # Task-based ReadLineAsync() avoids PowerShell 5.1 threadpool runspace bug.
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
        # If interrupted (e.g. Ctrl+C), allow child graceful exit grace window
        # then terminate the full process tree to prevent orphaned processes.
        if (-not $proc.HasExited) {
            $exited = $proc.WaitForExit(3000)
            if (-not $exited -and -not $proc.HasExited) {
                Write-Warning "  [Launcher] Process PID $($proc.Id) did not exit cleanly; terminating process tree..."
                try { & taskkill /F /T /PID $proc.Id 2>$null | Out-Null } catch {}
                try { $proc.Kill() } catch {}
            }
        }
    }

    $sw.Stop()
    $exitCode = $proc.ExitCode
    if ($env:ONX_DEBUG -eq '1') {
        Write-Host "  [Launcher] exit code: $exitCode" -ForegroundColor Cyan
        Write-Host "  [Launcher] duration:  $($sw.ElapsedMilliseconds)ms" -ForegroundColor Cyan
    }

    return $exitCode
}

function Start-OnxBootstrap {
    if ($env:ONX_DEBUG -eq '1') {
        Write-Host "========================================" -ForegroundColor Cyan
        Write-Host "  onx-manager -- Windows Launcher" -ForegroundColor Cyan
        Write-Host "========================================" -ForegroundColor Cyan
        Write-Host "  Directory: $repoRoot"
    }

    # ----------------------------------------------------------------------
    # 1. Resolve Python interpreter
    # ----------------------------------------------------------------------
    $venvPy    = Join-Path $repoRoot 'backend\.venv\Scripts\python.exe'
    $venvValid = $false

    if (Test-Path $venvPy) {
        $res = Invoke-OnxProcessProbe -Command $venvPy -Arguments @('-c', 'import sys; sys.exit(0 if sys.version_info[:2] == (3,12) else 1)') -TimeoutMs 3000
        if ($res.Success) {
            # Venv already exists and is Python 3.12 -- use it directly (no sub-arg needed)
            if ($env:ONX_DEBUG -eq '1') {
                Write-Host "  Using virtual environment: $venvPy"
            }
            $pyBin     = $venvPy
            $pySubArg  = @()
            $venvValid = $true
        } else {
            Write-Warning "Existing virtual environment ($venvPy) is not a functional Python 3.12 interpreter. Falling through to system Python..."
        }
    }

    if (-not $venvValid) {
        $candidates = @(
            @{ Name='py -3.12';   Cmd='py';         SubArg='-3.12'; Args=@('-3.12', '-c', 'import sys; sys.exit(0 if sys.version_info[:2] == (3,12) else 1)') },
            @{ Name='python3.12'; Cmd='python3.12'; SubArg='';      Args=@('-c', 'import sys; sys.exit(0 if sys.version_info[:2] == (3,12) else 1)') },
            @{ Name='python';     Cmd='python';     SubArg='';      Args=@('-c', 'import sys; sys.exit(0 if sys.version_info[:2] == (3,12) else 1)') },
            @{ Name='python3';    Cmd='python3';    SubArg='';      Args=@('-c', 'import sys; sys.exit(0 if sys.version_info[:2] == (3,12) else 1)') }
        )

        $foundCmd    = $null
        $foundSubArg = ''

        foreach ($c in $candidates) {
            $res = Invoke-OnxProcessProbe -Command $c.Cmd -Arguments $c.Args -TimeoutMs 3000
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
                # Expected -- candidate not on PATH, stay quiet
            } elseif ($res.ExitCode -ne 1 -and $res.ExitCode -ne 103) {
                Write-Warning "  [Probe Warning] Candidate '$($c.Name)' exited with unexpected code $($res.ExitCode) (Cmd: $($res.RawCmd); Stderr: $($res.StdErr))."
            }
        }

        if ($foundCmd) {
            $pyBin    = $foundCmd
            $pySubArg = if ($foundSubArg) { @($foundSubArg) } else { @() }
        } else {
            # ------------------------------------------------------------------
            # 2. Auto-install Python if nothing found
            # ------------------------------------------------------------------
            Write-Warning 'Python 3.12 not found on PATH. Attempting auto-install...'

            $pythonInstallerVersion = '3.12.8'
            $url       = "https://www.python.org/ftp/python/$pythonInstallerVersion/python-$pythonInstallerVersion-amd64.exe"
            $installer = Join-Path $env:TEMP "python-$pythonInstallerVersion-amd64.exe"

            $winget = Get-Command winget -ErrorAction SilentlyContinue
            $wingetInstalled = $false
            if ($winget) {
                Write-Host '  Installing Python 3.12 via winget...'
                & winget install Python.Python.3.12 -e --silent --accept-source-agreements --accept-package-agreements
                if ($LASTEXITCODE -eq 0) {
                    $wingetInstalled = $true
                } else {
                    Write-Warning "  winget Python install failed (exit $LASTEXITCODE). Falling back to official installer..."
                }
            }

            if (-not $wingetInstalled) {
                Write-Host '  Downloading Python 3.12 official installer...'
                try {
                    Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing -ErrorAction Stop
                } catch {
                    throw "Failed to download Python installer: $_"
                }

                Write-Host '  Attempting per-user install (InstallAllUsers=0)...'
                $installerArgs = @('/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_test=0')
                $proc = Start-Process -FilePath $installer -ArgumentList $installerArgs -Wait -PassThru

                if ($proc.ExitCode -ne 0) {
                    Write-Warning "  Per-user install failed (exit $($proc.ExitCode)). Retrying system-wide (InstallAllUsers=1)..."
                    $installerArgs = @('/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_test=0')
                    $proc2 = Start-Process -FilePath $installer -ArgumentList $installerArgs -Wait -PassThru

                    if ($proc2.ExitCode -ne 0) {
                        Write-Warning "  Python installer failed: per-user exit=$($proc.ExitCode), system-wide exit=$($proc2.ExitCode)"
                    } else {
                        Write-Host '  Python installed system-wide.'
                    }
                } else {
                    Write-Host '  Python installed (per-user). You may need to open a new terminal.'
                }
            }

            # ------------------------------------------------------------------
            # Re-probe for exact Python 3.12 interpreter
            # ------------------------------------------------------------------
            $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
            $userPath    = [Environment]::GetEnvironmentVariable('Path', 'User')
            if ($machinePath -or $userPath) {
                $env:Path = "$userPath;$machinePath;$($env:Path)"
            }

            $reprobePaths = @()
            if ($env:LOCALAPPDATA) {
                $reprobePaths += (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe')
            }
            if ($env:ProgramFiles) {
                $reprobePaths += (Join-Path $env:ProgramFiles 'Python312\python.exe')
            }
            $progFilesX86 = ${env:ProgramFiles(x86)}
            if ($progFilesX86) {
                $reprobePaths += (Join-Path $progFilesX86 'Python312\python.exe')
            }
            $reprobePaths += 'C:\Python312\python.exe'

            foreach ($cmdCandidate in @(
                @{ Cmd = 'py'; Args = @('-3.12', '-c', 'import sys; print(sys.executable)') },
                @{ Cmd = 'python3.12'; Args = @('-c', 'import sys; print(sys.executable)') }
            )) {
                $execRes = Invoke-OnxProcessProbe -Command $cmdCandidate.Cmd -Arguments $cmdCandidate.Args -TimeoutMs 3000
                if ($execRes.Success -and $execRes.StdOut) {
                    $resolvedPath = ($execRes.StdOut).Trim()
                    if ($resolvedPath -and -not ($reprobePaths -contains $resolvedPath)) {
                        $reprobePaths += $resolvedPath
                    }
                }
            }

            $reprobeSuccess = $false
            foreach ($target in $reprobePaths) {
                if (Test-Path $target) {
                    $probeRes = Invoke-OnxProcessProbe -Command $target -Arguments @('-c', 'import sys; sys.exit(0 if sys.version_info[:2] == (3,12) else 1)') -TimeoutMs 3000
                    if ($probeRes.Success) {
                        $pyBin          = $target
                        $pySubArg       = @()
                        $reprobeSuccess = $true
                        if ($env:ONX_DEBUG -eq '1') {
                            Write-Host "  Re-probed Python 3.12 interpreter: $pyBin"
                        }
                        break
                    }
                }
            }

            if (-not $reprobeSuccess) {
                throw "Python 3.12.x was not found or could not be installed. onx-manager requires exactly Python 3.12. Install Python 3.12 using 'winget install Python.Python.3.12' or the python.org $pythonInstallerVersion installer, then re-run scripts\start.ps1 (or install.ps1)."
            }
        }

        # ----------------------------------------------------------------------
        # 2b. Probe for Node.js 18+ and npm
        # ----------------------------------------------------------------------
        $localNode = Join-Path $repoRoot '.onx\node'
        if (Test-Path (Join-Path $localNode 'node.exe')) {
            $env:Path = "$localNode;$($env:Path)"
        }

        $nodeProbe = Invoke-OnxProcessProbe -Command 'node' -Arguments @('-v') -TimeoutMs 2000
        if ($nodeProbe.Success) {
            if ($env:ONX_DEBUG -eq '1') {
                $nodeVer = ($nodeProbe.StdOut).Trim()
                Write-Host "  Detected Node.js runtime: $nodeVer"
            }
        }
    }

    # ----------------------------------------------------------------------
    # 3. Validate launcher.py exists
    # ----------------------------------------------------------------------
    $launcher = Join-Path $repoRoot 'launcher.py'
    if (-not (Test-Path $launcher)) {
        throw "launcher.py not found in $repoRoot"
    }

    # ----------------------------------------------------------------------
    # 4. Run preflight (best-effort -- failures are warnings, not fatal)
    # ----------------------------------------------------------------------
    $preflight = Join-Path $repoRoot 'scripts\preflight.py'
    if (Test-Path $preflight) {
        $preflightArgs = @($pySubArg) + @($preflight) + @($args) | Where-Object { $_ -ne $null -and $_ -ne '' }
        $streamPreflight = ($env:ONX_DEBUG -eq '1')
        $res = Invoke-OnxProcessProbe -Command $pyBin -Arguments $preflightArgs -TimeoutMs 30000 -StreamOutput:$streamPreflight
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

    # ----------------------------------------------------------------------
    # 5. Launch
    # ----------------------------------------------------------------------
    $launcherArgs = @($pySubArg) + @($launcher) + @($args) | Where-Object { $_ -ne $null -and $_ -ne '' }
    $exitCode = Invoke-OnxProcessSupervised -Command $pyBin -Arguments $launcherArgs -WorkingDirectory $repoRoot
    return $exitCode
}

# ------------------------------------------------------------------------------
# Entry point: if invoked directly (not dot-sourced), execute immediately
# ------------------------------------------------------------------------------
if ($MyInvocation.InvocationName -ne '.') {
    $exitCode = Start-OnxBootstrap @args
    exit $exitCode
}
