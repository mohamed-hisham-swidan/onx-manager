from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
from typing import Any

from app.core.identity import IDENTITY

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.core.process_utils")

# ─── Windows constants (defined inline — NOT from subprocess module, which doesn't have them) ───
# From Win32 API (kernel32.dll):
# https://learn.microsoft.com/en-us/windows/win32/procthread/process-security-and-access-rights
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001
# https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getexitcodeprocess
STILL_ACTIVE = 259


def platform_pid_alive(pid: int) -> bool:
    """Cross-platform process liveness check.

    POSIX: os.kill(pid, 0) — returns True if process exists and we have permission.
    Windows: OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION) + GetExitCodeProcess
             — returns True if process exists and exit code == STILL_ACTIVE (259).
    """
    if not isinstance(pid, int) or pid <= 0:
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


def platform_force_kill(pid: int) -> None:
    """Forcefully terminate a single process by PID without caller signal leaks.

    POSIX: os.kill(pid, signal.SIGKILL) (traps ProcessLookupError silently).
    Windows: OpenProcess(PROCESS_TERMINATE) + TerminateProcess (traps errors cleanly).
    """
    if not isinstance(pid, int) or pid <= 0:
        return
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
            if not handle:
                err = kernel32.GetLastError()
                # 87: ERROR_INVALID_PARAMETER (PID dead), 5: ERROR_ACCESS_DENIED
                if err == 5:
                    logger.warning("platform_force_kill: Access denied for pid=%d", pid)
                return
            try:
                if not kernel32.TerminateProcess(handle, 1):
                    err = kernel32.GetLastError()
                    if err == 5:
                        logger.warning("platform_force_kill: Access denied terminating pid=%d", pid)
            finally:
                kernel32.CloseHandle(handle)
        except (OSError, AttributeError) as exc:
            logger.warning("platform_force_kill failed for pid=%d: %s", pid, exc)
    else:
        try:
            import signal

            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            logger.warning("platform_force_kill: Permission denied for pid=%d", pid)
        except OSError as exc:
            logger.warning("platform_force_kill failed for pid=%d: %s", pid, exc)


def platform_kill_process_tree_sync(pid: int, proc: Any | None = None) -> None:
    """Synchronously terminate a process tree (process and all child processes)."""
    if not isinstance(pid, int) or pid <= 0:
        return
    if sys.platform == "win32":
        import subprocess

        try:
            res = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if res.returncode not in (0, 128):
                logger.warning("taskkill returned code %d for pid=%d", res.returncode, pid)
                if proc is not None and hasattr(proc, "kill"):
                    with contextlib.suppress(Exception):
                        proc.kill()
        except FileNotFoundError:
            logger.warning("taskkill executable not found in PATH")
            if proc is not None and hasattr(proc, "kill"):
                with contextlib.suppress(Exception):
                    proc.kill()
        except Exception as exc:
            logger.warning("platform_kill_process_tree_sync error for pid=%d: %s", pid, exc)
            if proc is not None and hasattr(proc, "kill"):
                with contextlib.suppress(Exception):
                    proc.kill()
    else:
        try:
            import signal

            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        except (PermissionError, OSError) as exc:
            logger.warning("os.killpg failed for pid=%d: %s", pid, exc)
            if proc is not None and hasattr(proc, "kill"):
                with contextlib.suppress(Exception):
                    proc.kill()


async def platform_kill_process_tree_async(pid: int, proc: Any | None = None) -> None:
    """Asynchronously terminate a process tree (process and all child processes)."""
    if not isinstance(pid, int) or pid <= 0:
        return
    if sys.platform == "win32":
        try:
            proc_tk = await asyncio.create_subprocess_exec(
                "taskkill",
                "/F",
                "/T",
                "/PID",
                str(pid),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc_tk.wait()
            if proc_tk.returncode not in (0, 128):
                logger.warning("taskkill returned code %d for pid=%d", proc_tk.returncode, pid)
                if proc is not None and hasattr(proc, "kill"):
                    with contextlib.suppress(Exception):
                        proc.kill()
        except FileNotFoundError:
            logger.warning("taskkill executable not found in PATH")
            if proc is not None and hasattr(proc, "kill"):
                with contextlib.suppress(Exception):
                    proc.kill()
        except asyncio.CancelledError:
            if proc is not None and hasattr(proc, "kill"):
                with contextlib.suppress(Exception):
                    proc.kill()
            raise
        except Exception as exc:
            logger.warning("platform_kill_process_tree_async error for pid=%d: %s", pid, exc)
            if proc is not None and hasattr(proc, "kill"):
                with contextlib.suppress(Exception):
                    proc.kill()
    else:
        try:
            import signal

            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        except (PermissionError, OSError) as exc:
            logger.warning("os.killpg failed for pid=%d: %s", pid, exc)
            if proc is not None and hasattr(proc, "kill"):
                with contextlib.suppress(Exception):
                    proc.kill()
