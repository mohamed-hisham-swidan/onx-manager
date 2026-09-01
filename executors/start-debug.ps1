#Requires -Version 5.1
<#
.SYNOPSIS
    onx-manager Windows Launcher — Diagnostic Tracing Wrapper
.DESCRIPTION
    Wraps start.ps1 with full PowerShell transcript recording (Start-Transcript)
    and line-by-line execution tracing (Set-PSDebug -Trace 1).

    Zero-drift design: Directly dot-sources start.ps1's authoritative
    Start-OnxBootstrap function, ensuring debug tracing automatically stays
    in sync with start.ps1 without copy-paste code maintenance.

    Usage:
        powershell -NoProfile -ExecutionPolicy Bypass -File .\executors\start-debug.ps1 [args...]

    Output:
        Transcripts are written to: executors/logs/start-debug-<timestamp>.log
#>

$ErrorActionPreference = 'Stop'

$executorsDir = if ($PSScriptRoot) { $PSScriptRoot } elseif ($MyInvocation.MyCommand.Definition) { Split-Path -Parent $MyInvocation.MyCommand.Definition } else { (Get-Location).Path }
$repoRoot     = Split-Path -Parent $executorsDir
$startScript  = Join-Path $repoRoot 'start.ps1'

if (-not (Test-Path $startScript)) {
    throw "start.ps1 not found in repository root: $repoRoot"
}

# Ensure logs directory exists
$logsDir = Join-Path $executorsDir 'logs'
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
}

$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$logFile   = Join-Path $logsDir "start-debug-$timestamp.log"

Write-Host "========================================" -ForegroundColor Yellow
Write-Host "  onx-manager — Tracing Debug Launcher" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Yellow
Write-Host "  Directory : $repoRoot"
Write-Host "  Log File  : $logFile"
Write-Host "  Tracing   : Set-PSDebug -Trace 1 enabled"
Write-Host "========================================" -ForegroundColor Yellow

# Dot-source start.ps1 (defines Start-OnxBootstrap, Invoke-OnxProcessProbe, Invoke-OnxProcessSupervised without running)
. $startScript

$transcriptStarted = $false
$exitCode = 0

try {
    # Stop any abandoned transcript from prior interrupted sessions
    try { Stop-Transcript -ErrorAction SilentlyContinue | Out-Null } catch {}

    Start-Transcript -Path $logFile -Append -IncludeInvocationHeader | Out-Null
    $transcriptStarted = $true

    Set-PSDebug -Trace 1
    $env:ONX_DEBUG = '1'

    # Execute authoritative bootstrap logic with all forwarded arguments
    $exitCode = Start-OnxBootstrap @args
}
catch {
    Write-Warning "start-debug caught unhandled exception: $_"
    $exitCode = 1
}
finally {
    # Cleanly turn off tracing
    try { Set-PSDebug -Off } catch {}

    # Cleanly close transcript
    if ($transcriptStarted) {
        try { Stop-Transcript | Out-Null } catch {}
        Write-Host "  Debug transcript saved to: $logFile" -ForegroundColor Green
    }
}

exit $exitCode
