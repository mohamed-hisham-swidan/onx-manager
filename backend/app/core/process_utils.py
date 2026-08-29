from __future__ import annotations

import os
import sys

# ─── Windows constants (defined inline — NOT from subprocess module, which doesn't have them) ───
# From Win32 API (kernel32.dll):
# https://learn.microsoft.com/en-us/windows/win32/procthread/process-security-and-access-rights
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
# https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getexitcodeprocess
STILL_ACTIVE = 259


def platform_pid_alive(pid: int) -> bool:
    """Cross-platform process liveness check.

    POSIX: os.kill(pid, 0) — returns True if process exists and we have permission.
    Windows: OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION) + GetExitCodeProcess
             — returns True if process exists and exit code == STILL_ACTIVE (259).
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _windows_pid_alive(pid)
    return _posix_pid_alive(pid)


def _posix_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _windows_pid_alive(pid: int) -> bool:
    """Check if a Windows process is alive using OpenProcess + GetExitCodeProcess.

    Uses PROCESS_QUERY_LIMITED_INFORMATION (0x1000) which requires minimal privileges.
    Returns True if process exists and exit code == STILL_ACTIVE (259).
    """
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32

        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False

        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        # Any failure (import, ctypes, permissions) -> treat as not alive
        return False
