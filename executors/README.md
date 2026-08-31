# Executors — Auxiliary & Diagnostic Launcher Tooling

This directory contains auxiliary and diagnostic execution tooling for `onx-manager`.

> [!NOTE]
> **Primary Launchers**: The primary entry points for end users (`start.bat`, `start.ps1`, `start.sh`) remain located at the repository root.

## Files

- `start-debug.ps1`: Diagnostic launcher that wraps `start.ps1`'s authoritative bootstrap logic (`Start-OnxBootstrap`) with full PowerShell transcript recording (`Start-Transcript`) and line-by-line tracing (`Set-PSDebug -Trace 1`).
  - **Zero-Drift Architecture**: Directly dot-sources `start.ps1` rather than maintaining a duplicate copy.
  - **Logs**: Output is saved to `executors/logs/start-debug-<timestamp>.log` (gitignored).

## Usage

Run from the repository root:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\executors\start-debug.ps1 [args...]
```
