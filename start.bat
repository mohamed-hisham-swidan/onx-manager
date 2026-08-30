@echo off
rem onx-manager Windows Launcher — thin entry point
rem Usage: start.bat [--stop|--restart|--status|--code|--help|--self-test|...]
rem
rem Delegates immediately to onx.exe (pre-built) if present, otherwise
rem invokes start.ps1 (PowerShell bootstrap) which handles Python detection,
rem auto-install, preflight, and launcher.py delegation.
rem
rem Keeping complex logic in start.ps1 (not inline here) avoids all batch
rem caret-continuation and comment-character escaping footguns.

rem ──────────────────────────────────────────────────────────────────────
rem 1. If pre-built onx.exe exists, delegate to it immediately
rem ──────────────────────────────────────────────────────────────────────
if exist "%~dp0onx.exe" (
    "%~dp0onx.exe" %*
    exit /b %errorlevel%
)

rem ──────────────────────────────────────────────────────────────────────
rem 2. Delegate to PowerShell bootstrap script
rem    -NoProfile  : skip user profile (faster, no side effects)
rem    -ExecutionPolicy Bypass : allow running unsigned local scripts
rem    -File       : pass remaining %* args to start.ps1 as $args
rem ──────────────────────────────────────────────────────────────────────
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
exit /b %errorlevel%