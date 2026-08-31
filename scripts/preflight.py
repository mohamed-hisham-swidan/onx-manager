#!/usr/bin/env python3
"""
onx-manager — Windows Preflight Process Cleanup
================================================
Runs BEFORE every backend/frontend start to prevent duplicate processes,
orphaned services, and stale SQLite locks.  Idempotent — safe to run
anytime, even on a clean system.

Usage:
    python scripts/preflight.py [--stop|--restart|--force|--clean|-f]

On success: exits 0 (system clean or cleaned).
On failure: exits 1 (something unclean could not be resolved).

Platform: Windows only.
Requires: Python 3.12+ standard library only (no third-party packages,
          no backend imports — this runs before the venv is activated).

WHY THIS EXISTS
---------------
The Linux equivalent is scripts/preflight.sh (bash).  On Windows, bash is
not reliably available, so this Python script provides the same function.
We hit a real incident where a background uvicorn process outlived its
parent and a second backend launched on top of it, causing two processes
fighting over the same SQLite database file.  This script is the permanent
Windows-side fix.

FIX #4 NOTES (Review Revision 2)
---------------------------------
- wmic is deprecated/removed starting Windows 11 24H2 / Server 2025.
  All process queries now use Get-CimInstance Win32_Process via PowerShell.
- handle.exe / openfiles are not present on clean Windows machines.
  SQLite lock detection uses ctypes CreateFileW with exclusive open attempt
  instead.  Trade-off: we can detect WHETHER the file is locked but cannot
  report WHICH PID holds the lock (CreateFileW does not expose that).
  This is acceptable since preflight's job is cleanup/reporting, not
  precise PID attribution — if the DB is locked by a foreign process we
  cannot kill, we report it and exit 1.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────
# Guard: Windows only
# ──────────────────────────────────────────────────────────────────────

if sys.platform != "win32":
    print("preflight.py: Windows only — skipping on this platform.")
    sys.exit(0)

# ──────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

BACKEND_PORT: int = int(os.environ.get("ONX_BACKEND_PORT") or os.environ.get("MCS_BACKEND_PORT") or 8000)
FRONTEND_PORT: int = int(os.environ.get("ONX_FRONTEND_PORT") or os.environ.get("MCS_FRONTEND_PORT") or 5173)
BACKEND_DIR = PROJECT_ROOT / "backend"
ONX_DB = BACKEND_DIR / "data" / "onx.db"
KILL_WAIT = 5  # seconds to wait for graceful termination before force-kill

# ──────────────────────────────────────────────────────────────────────
# ANSI colours & Unicode detection
# ──────────────────────────────────────────────────────────────────────

_TTY = sys.stdout.isatty() if hasattr(sys.stdout, "isatty") else False
BOLD   = "\033[1m"  if _TTY else ""
DIM    = "\033[2m"  if _TTY else ""
GREEN  = "\033[92m" if _TTY else ""
YELLOW = "\033[93m" if _TTY else ""
RED    = "\033[91m" if _TTY else ""
RESET  = "\033[0m"  if _TTY else ""


def _detect_unicode_support() -> bool:
    if os.environ.get("ONX_FORCE_ASCII", "").lower() in ("1", "true", "yes"):
        return False
    if os.environ.get("ONX_FORCE_UNICODE", "").lower() in ("1", "true", "yes"):
        return True
    if any(k in os.environ for k in ("WT_SESSION", "TERM_PROGRAM", "ConEmuPID")):
        return True
    if sys.platform != "win32":
        return "utf" in (getattr(sys.stdout, "encoding", "") or "").lower()
    try:
        kernel32_temp = ctypes.windll.kernel32
        cp = kernel32_temp.GetConsoleOutputCP()
        if cp != 65001:
            return False
        h_out = kernel32_temp.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if kernel32_temp.GetConsoleMode(h_out, ctypes.byref(mode)):
            return bool(mode.value & 0x0004)
    except Exception:
        pass
    return False


_UNICODE_SUPPORTED = _detect_unicode_support()

SYM_OK   = "✔" if _UNICODE_SUPPORTED else "[OK]"
SYM_INFO = "▪" if _UNICODE_SUPPORTED else "*"
SYM_WARN = "⚠" if _UNICODE_SUPPORTED else "[!]"
SYM_ERR  = "✖" if _UNICODE_SUPPORTED else "[X]"


# ──────────────────────────────────────────────────────────────────────
# Logging helpers
# ──────────────────────────────────────────────────────────────────────

def log_info(msg: str) -> None:
    print(f"  {DIM}{SYM_INFO}{RESET} {msg}")

def log_warn(msg: str) -> None:
    print(f"  {YELLOW}{SYM_WARN}{RESET} {msg}")

def log_ok(msg: str) -> None:
    print(f"  {GREEN}{SYM_OK}{RESET} {msg}")

def log_error(msg: str) -> None:
    print(f"  {RED}{SYM_ERR}{RESET} {msg}")

def log_bold(msg: str) -> None:
    print(f"{BOLD}{msg}{RESET}")

def log_dim(msg: str) -> None:
    print(f"{DIM}{msg}{RESET}")

# ──────────────────────────────────────────────────────────────────────
# Win32 constants (inlined — no backend imports)
# ──────────────────────────────────────────────────────────────────────

# Process access rights
PROCESS_TERMINATE                  = 0x0001
PROCESS_QUERY_LIMITED_INFORMATION  = 0x1000
# GetExitCodeProcess sentinel
STILL_ACTIVE = 259
# CreateFileW access / share flags
GENERIC_READ                       = 0x80000000
GENERIC_WRITE                      = 0x40000000
FILE_SHARE_READ                    = 0x00000001
OPEN_EXISTING                      = 3
INVALID_HANDLE_VALUE               = ctypes.c_void_p(-1).value

kernel32 = ctypes.windll.kernel32

# ──────────────────────────────────────────────────────────────────────
# PID liveness (ctypes — no wmic, no subprocess)
# ──────────────────────────────────────────────────────────────────────

def _pid_alive(pid: int) -> bool:
    """Return True if the Windows process with given PID is alive and still running."""
    if pid <= 0:
        return False
    try:
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD(0)
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return False


def _terminate_pid(pid: int) -> bool:
    """Send TerminateProcess to a PID.  Returns True if the call succeeded."""
    try:
        handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
        if not handle:
            return False
        try:
            return bool(kernel32.TerminateProcess(handle, 1))
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return False

# ──────────────────────────────────────────────────────────────────────
# Process information via Get-CimInstance Win32_Process (replaces wmic)
# ──────────────────────────────────────────────────────────────────────
# FIX #4: wmic is deprecated/removed in Windows 11 24H2+.
# We shell out to powershell.exe with Get-CimInstance instead.
# All ps calls use -NoProfile for speed and to avoid profile side-effects.
# ──────────────────────────────────────────────────────────────────────

def _run_ps(script: str) -> str:
    """Run a PowerShell one-liner and return its stdout, or '' on error."""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def get_all_processes() -> list[dict]:
    """
    Return a list of dicts with keys: pid, ppid, name, cmdline, executable_path.
    Uses Get-CimInstance Win32_Process — available on all Windows versions.
    """
    ps_script = (
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId, ParentProcessId, Name, CommandLine, ExecutablePath | "
        "ConvertTo-Json -Compress -Depth 2"
    )
    raw = _run_ps(ps_script)
    if not raw:
        return []
    try:
        data = json.loads(raw)
        # PowerShell returns a single object (not array) when there is only one process.
        if isinstance(data, dict):
            data = [data]
        result: list[dict] = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            result.append({
                "pid":             int(entry.get("ProcessId") or 0),
                "ppid":            int(entry.get("ParentProcessId") or 0),
                "name":            str(entry.get("Name") or ""),
                "cmdline":         str(entry.get("CommandLine") or ""),
                "executable_path": str(entry.get("ExecutablePath") or ""),
            })
        return result
    except (json.JSONDecodeError, TypeError, ValueError):
        return []


def get_pids_on_port(port: int) -> list[int]:
    """Return PIDs listening on the given TCP port (via netstat)."""
    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True, timeout=10,
        )
        pids: list[int] = []
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 5 and f":{port}" in parts[1] and parts[3] in ("LISTENING", "ABHÖREN"):
                try:
                    pid = int(parts[4])
                    if pid > 0 and pid not in pids:
                        pids.append(pid)
                except ValueError:
                    pass
        return pids
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []

# ──────────────────────────────────────────────────────────────────────
# SQLite lock detection via CreateFileW (replaces handle.exe / openfiles)
# ──────────────────────────────────────────────────────────────────────
# FIX #4: handle.exe requires Sysinternals; openfiles requires an optional
# Windows feature.  Neither is available on a clean machine.
#
# We instead attempt to open the DB file with exclusive write access
# (FILE_SHARE_READ only — no FILE_SHARE_WRITE).  If another process holds
# the file open for writing (as SQLite does), CreateFileW returns
# INVALID_HANDLE_VALUE.
#
# Trade-off: we can detect WHETHER the DB is locked but NOT which PID
# holds it.  This is acceptable — preflight's job is to detect and report
# the condition, not perform forensic attribution.  If the DB is locked by
# a process we cannot identify (e.g. the healthy backend we're protecting),
# the check_db_lock() caller decides whether to treat that as acceptable.
# ──────────────────────────────────────────────────────────────────────

def _db_is_locked(db_path: Path) -> bool:
    """
    Return True if the SQLite DB file is locked by another process.

    Uses CreateFileW with GENERIC_READ|GENERIC_WRITE and FILE_SHARE_READ
    only (no write-share).  If the file opens successfully, it is NOT
    locked; the handle is closed immediately.  If CreateFileW returns
    INVALID_HANDLE_VALUE, the file IS locked.

    NOTE: This test cannot identify WHICH process holds the lock.
    See module docstring for the accepted trade-off.
    """
    if not db_path.is_file():
        return False
    try:
        kernel32.CreateFileW.restype = ctypes.c_void_p
        kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,  # lpFileName
            wintypes.DWORD,    # dwDesiredAccess
            wintypes.DWORD,    # dwShareMode
            ctypes.c_void_p,   # lpSecurityAttributes
            wintypes.DWORD,    # dwCreationDisposition
            wintypes.DWORD,    # dwFlagsAndAttributes
            ctypes.c_void_p,   # hTemplateFile
        ]
        handle = kernel32.CreateFileW(
            str(db_path),
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ,   # no write-share → exclusive write test
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        raw_invalid = INVALID_HANDLE_VALUE
        if handle == raw_invalid or handle == 0 or handle is None:
            return True  # locked
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        return False
    except Exception:
        # If ctypes call itself fails, we cannot determine lock state — assume unlocked
        # to avoid a false-positive block.
        return False

# ──────────────────────────────────────────────────────────────────────
# Project membership check
# ──────────────────────────────────────────────────────────────────────

_PROJECT_ROOT_STR = str(PROJECT_ROOT).lower()
_SERVER_DATA_STR  = str(PROJECT_ROOT / "backend" / "data" / "servers").lower()

_DAEMON_KEYWORDS = ("playit", "cloudflared", "java")
_PROJECT_MARKERS = ("onx-frontend", "mcs-frontend", "onx-manager", "mcs-manager", "app.main:app")


def _belongs_to_project(proc: dict) -> bool:
    """
    Return True if this process belongs to onx-manager (not a daemon/game/foreign process).

    Mirrors the logic in scripts/preflight.sh belongs_to_project() using
    cmdline/executable_path instead of /proc/<PID>/cmdline and /proc/<PID>/cwd.
    """
    cmdline_lower = proc["cmdline"].lower()
    exe_lower     = proc["executable_path"].lower()

    # Exclude background daemons and game servers
    for kw in _DAEMON_KEYWORDS:
        if kw in cmdline_lower or kw in exe_lower:
            return False

    # Exclude processes whose executable path is under a Minecraft server data dir
    if _SERVER_DATA_STR and _SERVER_DATA_STR in exe_lower:
        return False
    if _SERVER_DATA_STR and _SERVER_DATA_STR in cmdline_lower:
        return False

    # Match by executable path being under project root (but not server data)
    if _PROJECT_ROOT_STR and _PROJECT_ROOT_STR in exe_lower:
        return True

    # Match by cmdline containing project root path
    if _PROJECT_ROOT_STR and _PROJECT_ROOT_STR in cmdline_lower:
        if _SERVER_DATA_STR not in cmdline_lower:
            return True

    # Match by unique project identifiers in cmdline
    for marker in _PROJECT_MARKERS:
        if marker in cmdline_lower:
            return True

    return False

# ──────────────────────────────────────────────────────────────────────
# State
# ──────────────────────────────────────────────────────────────────────

_protected_pids: set[int] = {os.getpid()}
try:
    if hasattr(os, "getppid"):
        _ppid = os.getppid()
        if _ppid > 0:
            _protected_pids.add(_ppid)
except Exception:
    pass

_found_any    = False
_killed_any   = False
_failed_any   = False
_summary: list[str] = []

_force_clean = any(a in sys.argv for a in ("--stop", "--restart", "--force", "--clean", "-f"))

# ──────────────────────────────────────────────────────────────────────
# Protection helpers
# ──────────────────────────────────────────────────────────────────────

def _protect_family(pid: int, all_procs: list[dict]) -> None:
    """Mark pid and its direct children (and parent if project-owned) as protected."""
    if pid <= 0:
        return
    _protected_pids.add(pid)
    # Children
    for p in all_procs:
        if p["ppid"] == pid and p["pid"] > 0:
            _protected_pids.add(p["pid"])
    # Parent
    for p in all_procs:
        if p["pid"] == pid:
            ppid = p["ppid"]
            if ppid > 1 and ppid not in _protected_pids:
                for pp in all_procs:
                    if pp["pid"] == ppid and _belongs_to_project(pp):
                        _protected_pids.add(ppid)
            break

# ──────────────────────────────────────────────────────────────────────
# Health checks (HTTP — no curl dependency on Windows)
# ──────────────────────────────────────────────────────────────────────

def _http_ok(url: str) -> bool:
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=2) as resp:
            return resp.status in (200, 302, 304)
    except Exception:
        return False


def _backend_healthy() -> bool:
    return (
        _http_ok(f"http://127.0.0.1:{BACKEND_PORT}/health")
        or _http_ok(f"http://127.0.0.1:{BACKEND_PORT}/api/v1/health")
    )


def _frontend_healthy() -> bool:
    return _http_ok(f"http://127.0.0.1:{FRONTEND_PORT}")

# ──────────────────────────────────────────────────────────────────────
# Kill helper
# ──────────────────────────────────────────────────────────────────────

def _kill_safe(pid: int, source_desc: str, all_procs: list[dict]) -> bool:
    """
    Kill a process if it belongs to the project and is not protected.
    Returns True if the process is gone after the call, False if it could not be killed.
    """
    global _found_any, _killed_any, _failed_any

    if not _pid_alive(pid):
        return True

    # Find proc info
    proc_info = next((p for p in all_procs if p["pid"] == pid), None)
    if proc_info is None:
        log_warn(f"PID {pid} ({source_desc}): no process info — skipping.")
        return True

    if not _belongs_to_project(proc_info):
        log_warn(f"PID {pid} ({source_desc}) does NOT appear to belong to this project.")
        log_warn("  cmdline: " + proc_info["cmdline"][:120])
        log_warn("  Will NOT kill — review manually.")
        _summary.append(f"{YELLOW}⚠{RESET} PID {pid}  {source_desc}  skipped (unknown owner)")
        return False

    if pid in _protected_pids:
        log_info(f"PID {pid} ({source_desc}) is protected — skipping.")
        return True

    log_info(f"Terminating PID {pid} ({source_desc})...")
    log_info(f"  name: {proc_info['name']}  cmdline: {proc_info['cmdline'][:100]}")
    _found_any = True

    _terminate_pid(pid)

    # Wait up to KILL_WAIT seconds
    for _ in range(KILL_WAIT):
        if not _pid_alive(pid):
            break
        time.sleep(1)

    # Force if still alive — taskkill /F /T also kills child tree
    if _pid_alive(pid):
        log_warn(f"PID {pid} did not exit after {KILL_WAIT}s — using taskkill /F /T")
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        time.sleep(1)

    if _pid_alive(pid):
        log_error(f"Failed to kill PID {pid} even with taskkill /F /T")
        _failed_any = True
        _summary.append(f"{RED}✖{RESET} PID {pid}  {source_desc}  {RED}could not kill{RESET}")
        return False

    _killed_any = True
    _summary.append(f"{RED}✖{RESET} PID {pid}  {source_desc}  {GREEN}killed{RESET}")
    return True

# ──────────────────────────────────────────────────────────────────────
# Checks
# ──────────────────────────────────────────────────────────────────────

def check_services(all_procs: list[dict]) -> None:
    """Check backend and frontend ports; protect healthy services or clean stale ones."""

    # Backend port
    be_pids = get_pids_on_port(BACKEND_PORT)
    if be_pids:
        if not _force_clean and _backend_healthy():
            for pid in be_pids:
                _protect_family(pid, all_procs)
                log_ok(f"Healthy backend on port {BACKEND_PORT} (PID {pid}) — preserving")
                _summary.append(f"{GREEN}✔{RESET} Backend  PID {pid} (port {BACKEND_PORT})  {GREEN}active & healthy{RESET}")
        else:
            for pid in be_pids:
                _kill_safe(pid, f"backend port {BACKEND_PORT}", all_procs)

    # Frontend port
    fe_pids = get_pids_on_port(FRONTEND_PORT)
    if fe_pids:
        if not _force_clean and _frontend_healthy():
            for pid in fe_pids:
                _protect_family(pid, all_procs)
                log_ok(f"Healthy frontend on port {FRONTEND_PORT} (PID {pid}) — preserving")
                _summary.append(f"{GREEN}✔{RESET} Frontend PID {pid} (port {FRONTEND_PORT})  {GREEN}active & healthy{RESET}")
        else:
            for pid in fe_pids:
                _kill_safe(pid, f"frontend port {FRONTEND_PORT}", all_procs)


def check_db_lock(all_procs: list[dict]) -> None:
    """
    Detect stale SQLite locks on the onx.db file.

    FIX #4: Uses CreateFileW exclusive-open test instead of handle.exe/openfiles.
    If the DB appears locked, we check if there is a live, healthy backend holding
    it (in which case we treat it as acceptable).  If locked by an unknown/dead
    process, we report it and set _failed_any so preflight exits 1.

    NOTE: We cannot determine WHICH PID holds the lock from CreateFileW alone.
    If the DB is locked and no healthy backend is detected, we report the
    condition but cannot kill the locking process — the operator must resolve it
    manually or the healthy-backend protection check serves as the proxy.
    """
    global _failed_any

    if not ONX_DB.is_file():
        return

    locked = _db_is_locked(ONX_DB)
    if not locked:
        return

    # If a healthy backend is running and protected, the lock is expected — allow it.
    be_pids = get_pids_on_port(BACKEND_PORT)
    if be_pids and _backend_healthy():
        live_be_protected = any(p in _protected_pids for p in be_pids)
        if live_be_protected:
            log_info(f"SQLite lock on {ONX_DB.name} held by active healthy backend — preserved")
            return

    # Lock is held by an unknown or stale process.
    log_warn(f"SQLite DB is locked: {ONX_DB}")
    log_warn("  Cannot determine which PID holds the lock (CreateFileW limitation — see module docstring).")
    log_warn("  If a stale process is holding this lock, kill it manually or use --force.")
    _summary.append(f"{RED}✖{RESET} SQLite DB  {ONX_DB.name}  {RED}locked (stale){RESET}")
    _failed_any = True


def scan_orphans(all_procs: list[dict]) -> None:
    """Scan for inactive/duplicate orphan project processes not holding an active port."""
    orphan_name_patterns = ("uvicorn", "vite", "node", "python", "py", "npm")
    seen: set[int] = set()

    for proc in all_procs:
        pid = proc["pid"]
        if pid <= 0 or pid in seen:
            continue
        if pid in _protected_pids:
            continue
        if pid == os.getpid() or (hasattr(os, "getppid") and pid == os.getppid()):
            continue

        cmdline_lower = proc["cmdline"].lower()
        # Never target running preflight scripts
        if "preflight.py" in cmdline_lower or "preflight.sh" in cmdline_lower:
            continue

        name_lower = proc["name"].lower()
        if not any(pat in name_lower for pat in orphan_name_patterns):
            continue

        # Must be recognisably related to this project
        is_project = (
            (_PROJECT_ROOT_STR and _PROJECT_ROOT_STR in cmdline_lower
             and _SERVER_DATA_STR not in cmdline_lower)
            or any(m in cmdline_lower for m in _PROJECT_MARKERS)
        )
        if not is_project:
            continue

        seen.add(pid)
        _kill_safe(pid, f"inactive/duplicate orphan ({proc['name']})", all_procs)


def cleanup_pid_files(all_procs: list[dict]) -> None:
    """Remove stale PID files from .onx/ and .mcs/ directories."""
    alive_pids = {p["pid"] for p in all_procs if p["pid"] > 0}

    for dir_name in (".onx", ".mcs"):
        pid_dir = PROJECT_ROOT / dir_name
        if not pid_dir.is_dir():
            continue

        # Sync live PIDs if protected
        be_pids = get_pids_on_port(BACKEND_PORT)
        fe_pids = get_pids_on_port(FRONTEND_PORT)
        if be_pids:
            live_be = be_pids[0]
            if live_be in _protected_pids:
                try:
                    (pid_dir / "backend.pid").write_text(str(live_be))
                except OSError:
                    pass
        if fe_pids:
            live_fe = fe_pids[0]
            if live_fe in _protected_pids:
                try:
                    (pid_dir / "frontend.pid").write_text(str(live_fe))
                except OSError:
                    pass

        cleaned = 0
        for pid_file in pid_dir.glob("*.pid"):
            try:
                old_pid_str = pid_file.read_text().strip()
                if not old_pid_str:
                    pid_file.unlink(missing_ok=True)
                    cleaned += 1
                    continue
                old_pid = int(old_pid_str)
                if old_pid not in alive_pids or not _pid_alive(old_pid):
                    pid_file.unlink(missing_ok=True)
                    cleaned += 1
            except (ValueError, OSError):
                try:
                    pid_file.unlink(missing_ok=True)
                    cleaned += 1
                except OSError:
                    pass

        if cleaned > 0:
            log_info(f"Cleaned {cleaned} stale PID file(s) from {dir_name}/")

# ──────────────────────────────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────────────────────────────

def print_summary() -> int:
    """Print summary table and return 0 (clean) or 1 (unclean)."""
    sep = "─" * 44
    print()
    log_dim(sep)
    log_bold("  Preflight Summary")
    log_dim(sep)

    for line in _summary:
        print(f"  {line}")
    if _summary:
        print()

    any_unclean = False

    # Backend port final state
    be_pids = get_pids_on_port(BACKEND_PORT)
    if be_pids:
        first_be = be_pids[0]
        if first_be in _protected_pids or _backend_healthy():
            be_status = f"{GREEN}running (healthy){RESET}"
        else:
            be_status = f"{RED}in use (unclean){RESET}"
            any_unclean = True
    else:
        be_status = f"{GREEN}free{RESET}"
    print(f"     {BOLD}Backend port {BACKEND_PORT}:{RESET} {be_status}")

    # Frontend port final state
    fe_pids = get_pids_on_port(FRONTEND_PORT)
    if fe_pids:
        first_fe = fe_pids[0]
        if first_fe in _protected_pids or _frontend_healthy():
            fe_status = f"{GREEN}running (healthy){RESET}"
        else:
            fe_status = f"{RED}in use (unclean){RESET}"
            any_unclean = True
    else:
        fe_status = f"{GREEN}free{RESET}"
    print(f"     {BOLD}Frontend port {FRONTEND_PORT}:{RESET} {fe_status}")

    # SQLite DB final state
    db_locked = _db_is_locked(ONX_DB)
    if ONX_DB.is_file() and db_locked:
        be_healthy_and_protected = (
            bool(be_pids)
            and _backend_healthy()
            and any(p in _protected_pids for p in be_pids)
        )
        if be_healthy_and_protected:
            db_status = f"{GREEN}active (healthy backend){RESET}"
        else:
            db_status = f"{RED}locked (stale){RESET}"
            any_unclean = True
    else:
        db_status = f"{GREEN}free{RESET}"
    print(f"     {BOLD}SQLite DB:{RESET} {db_status}")

    print()

    if any_unclean or _failed_any:
        log_error("Preflight FAILED — cannot guarantee clean state.")
        print()
        return 1

    if _killed_any:
        log_ok("Preflight complete — cleaned dead/duplicate item(s).")
    else:
        log_ok("System is healthy and ready. Proceed.")
    print()
    return 0

# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

def main() -> int:
    print()
    log_bold("═══ onx-manager — Windows Preflight ═══")
    log_dim(f"Project root: {PROJECT_ROOT}")
    if _force_clean:
        log_dim("Mode: Force cleanup (stop/restart)")
    else:
        log_dim("Mode: Smart reconciliation (preserve healthy, kill stale/duplicate orphans)")
    print()

    log_info("Enumerating all processes via Get-CimInstance Win32_Process...")
    all_procs = get_all_processes()
    if not all_procs:
        log_warn("Could not enumerate processes (PowerShell unavailable?). Skipping process checks.")
    else:
        log_info(f"Found {len(all_procs)} processes.")

    check_services(all_procs)
    check_db_lock(all_procs)
    scan_orphans(all_procs)
    cleanup_pid_files(all_procs)

    return print_summary()


if __name__ == "__main__":
    sys.exit(main())
