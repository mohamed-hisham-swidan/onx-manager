@echo off
chcp 65001 >nul
rem onx-manager Windows Launcher — thin entry point
rem Usage: start.bat [--stop|--restart|--status|--code|--help|--self-test|...]
rem
rem Invokes scripts/start.ps1 (PowerShell bootstrap) which handles Python detection,
rem auto-install, preflight, and launcher.py delegation.
rem
rem Keeping complex logic in scripts/start.ps1 (not inline here) avoids all batch
rem caret-continuation and comment-character escaping footguns.

rem ──────────────────────────────────────────────────────────────────────
rem Delegate to PowerShell bootstrap script
rem    -NoProfile  : skip user profile (faster, no side effects)
rem    -ExecutionPolicy Bypass : allow running unsigned local scripts
rem    -File       : pass remaining %* args to scripts/start.ps1 as $args
rem ──────────────────────────────────────────────────────────────────────
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" %*
exit /b %errorlevel%