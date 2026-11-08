from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.identity import IDENTITY

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.core.process_utils")


@dataclass(frozen=True)
class ProcessIdentityCheck:
    verified: bool
    reason: str
    create_time: float | None = None
    cmdline: tuple[str, ...] = ()
    cwd: str | None = None


_MINECRAFT_KEYWORDS: tuple[str, ...] = (
    ".jar",
    "@libraries",
    "net.minecraft",
    "cpw.mods",
    "neoforged",
    "fabric-server",
    "forge",
    "spigot",
    "paper",
    "purpur",
    "mohist",
    "sponge",
    "server.jar",
    "minecraft",
)

_WRAPPER_SCRIPTS: tuple[str, ...] = (
    "run.bat",
    "run.sh",
    "start.sh",
    "user_jvm_args.txt",
    "run.cmd",
    "run.ps1",
)

_SHELL_EXECUTABLES: tuple[str, ...] = (
    "cmd",
    "cmd.exe",
    "powershell",
    "powershell.exe",
    "pwsh",
    "pwsh.exe",
    "bash",
    "sh",
    "zsh",
)


def _path_inside_or_equal(target: str | Path | None, base: str | Path) -> bool:
    if not target:
        return False
    try:
        t = Path(target).resolve()
        b = Path(base).resolve()
        return t == b or b in t.parents
    except Exception:
        return False


def _is_minecraft_java_invocation(cmdline: tuple[str, ...], proc: Any | None = None) -> bool:
    if not cmdline:
        return False
    cmd_lower = [arg.lower() for arg in cmdline]
    proc_name = ""
    if proc is not None and hasattr(proc, "name"):
        with contextlib.suppress(Exception):
            proc_name = (proc.name() or "").lower()

    # Verify java executable signature
    java_names = ("java", "java.exe", "javaw", "javaw.exe")
    first_token_name = Path(cmdline[0]).name.lower()
    java_present = (
        first_token_name in java_names
        or proc_name in java_names
        or any(Path(arg).name.lower() in java_names for arg in cmdline[:3])
    )
    if not java_present:
        return False

    # Verify Minecraft keyword signature in arguments
    return any(sig in arg for arg in cmd_lower for sig in _MINECRAFT_KEYWORDS)


def _is_wrapper_shell_invocation(cmdline: tuple[str, ...], proc: Any | None = None) -> bool:
    if not cmdline:
        return False
    cmd_lower = [arg.lower() for arg in cmdline]
    proc_name = ""
    if proc is not None and hasattr(proc, "name"):
        with contextlib.suppress(Exception):
            proc_name = (proc.name() or "").lower()

    first_token_name = Path(cmdline[0]).name.lower()
    shell_present = (
        first_token_name in _SHELL_EXECUTABLES
        or proc_name in _SHELL_EXECUTABLES
    )

    # Check for direct wrapper script mention in cmdline
    has_wrapper_script = any(
        any(script in arg for script in _WRAPPER_SCRIPTS)
        or arg.endswith((".bat", ".sh", ".cmd", ".ps1"))
        for arg in cmd_lower
    )
    if has_wrapper_script:
        return True

    # Check for Minecraft script/keyword in shell args
    if shell_present:
        has_mc_arg = any(
            any(sig in arg for sig in _MINECRAFT_KEYWORDS)
            for arg in cmd_lower
        )
        if has_mc_arg:
            return True

        # Check if process has a Java child process running Minecraft
        if proc is not None and hasattr(proc, "children"):
            with contextlib.suppress(Exception):
                for child in proc.children(recursive=True):
                    try:
                        child_cmd = tuple(child.cmdline())
                        if _is_minecraft_java_invocation(child_cmd, child):
                            return True
                    except Exception:
                        continue
    return False


def verify_process_identity(
    pid: int,
    *,
    expected_create_time: int | float | None = None,
    expected_server_dir: str | Path | None = None,
    servers_data_dir: str | Path | None = None,
    allow_wrapper_shell: bool = False,
    create_time_tolerance_seconds: float = 5.0,
) -> ProcessIdentityCheck:
    """Verify process create_time, Java/Minecraft cmdline, and server directory before any kill."""
    if not isinstance(pid, int) or pid <= 0:
        return ProcessIdentityCheck(verified=False, reason="no_such_process")

    try:
        import psutil

        try:
            proc = psutil.Process(pid)
        except (psutil.NoSuchProcess, ProcessLookupError, ValueError):
            return ProcessIdentityCheck(verified=False, reason="no_such_process")

        try:
            proc_create_time = float(proc.create_time())
        except (psutil.NoSuchProcess, ProcessLookupError):
            return ProcessIdentityCheck(verified=False, reason="no_such_process")
        except Exception:
            proc_create_time = None
    except ImportError:
        # Fallback if psutil is not available
        proc = None
        proc_create_time = None

    # Check 1: create_time check
    if expected_create_time is not None and float(expected_create_time) > 0:
        if proc_create_time is not None:
            if abs(proc_create_time - float(expected_create_time)) > create_time_tolerance_seconds:
                return ProcessIdentityCheck(
                    verified=False,
                    reason="create_time_mismatch",
                    create_time=proc_create_time,
                )
        else:
            return ProcessIdentityCheck(
                verified=False,
                reason="create_time_mismatch",
                create_time=None,
            )

    # Read cmdline
    cmdline_list: list[str] = []
    if proc is not None:
        try:
            cmdline_list = list(proc.cmdline())
        except (psutil.NoSuchProcess, ProcessLookupError):
            return ProcessIdentityCheck(verified=False, reason="no_such_process")
        except Exception:
            cmdline_list = []
    else:
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                raw = f.read().decode("utf-8", errors="replace")
                cmdline_list = [part for part in raw.split("\0") if part]
        except (ProcessLookupError, FileNotFoundError):
            return ProcessIdentityCheck(verified=False, reason="no_such_process")
        except Exception:
            pass

    cmdline_tuple = tuple(cmdline_list)

    # Read cwd and environ
    cwd: str | None = None
    if proc is not None:
        try:
            cwd = proc.cwd()
        except (psutil.NoSuchProcess, ProcessLookupError):
            return ProcessIdentityCheck(verified=False, reason="no_such_process")
        except Exception:
            cwd = None
    else:
        try:
            cwd = os.readlink(f"/proc/{pid}/cwd")
        except (ProcessLookupError, FileNotFoundError):
            return ProcessIdentityCheck(verified=False, reason="no_such_process")
        except Exception:
            cwd = None

    environ: dict[str, str] = {}
    if proc is not None:
        try:
            environ = dict(proc.environ())
        except (psutil.NoSuchProcess, ProcessLookupError):
            return ProcessIdentityCheck(verified=False, reason="no_such_process")
        except Exception:
            environ = {}
    else:
        try:
            with open(f"/proc/{pid}/environ", "rb") as f:
                raw = f.read().decode("utf-8", errors="replace")
                for item in raw.split("\0"):
                    if "=" in item:
                        k, v = item.split("=", 1)
                        environ[k] = v
        except (ProcessLookupError, FileNotFoundError):
            return ProcessIdentityCheck(verified=False, reason="no_such_process")
        except Exception:
            pass

    # Check 2: cmdline check
    is_mc_java = _is_minecraft_java_invocation(cmdline_tuple, proc)
    is_wrapper = allow_wrapper_shell and _is_wrapper_shell_invocation(cmdline_tuple, proc)

    if not (is_mc_java or is_wrapper):
        return ProcessIdentityCheck(
            verified=False,
            reason="cmdline_mismatch",
            create_time=proc_create_time,
            cmdline=cmdline_tuple,
            cwd=cwd,
        )

    # Check 3: server_dir / servers_data_dir / ONX_MANAGED=1 check
    env_managed = (
        environ.get("ONX_MANAGED") == "1"
        or environ.get("MCS_MANAGED") == "1"
        or environ.get(IDENTITY.process_marker_new) == "1"
        or environ.get(IDENTITY.process_marker_legacy) == "1"
    )

    if expected_server_dir is not None:
        exp_dir = Path(expected_server_dir).resolve()
        cwd_matches = _path_inside_or_equal(cwd, exp_dir)
        cmd_matches = any(
            _path_inside_or_equal(arg, exp_dir) or str(exp_dir) in arg
            for arg in cmdline_tuple
        )
        if not (cwd_matches or cmd_matches or env_managed):
            return ProcessIdentityCheck(
                verified=False,
                reason="server_dir_mismatch",
                create_time=proc_create_time,
                cmdline=cmdline_tuple,
                cwd=cwd,
            )
    elif servers_data_dir is not None:
        data_dir = Path(servers_data_dir).resolve()
        cwd_matches = _path_inside_or_equal(cwd, data_dir)
        cmd_matches = any(
            _path_inside_or_equal(arg, data_dir) or str(data_dir) in arg
            for arg in cmdline_tuple
        )
        if not (cwd_matches or cmd_matches or env_managed):
            return ProcessIdentityCheck(
                verified=False,
                reason="servers_data_dir_mismatch",
                create_time=proc_create_time,
                cmdline=cmdline_tuple,
                cwd=cwd,
            )

    return ProcessIdentityCheck(
        verified=True,
        reason="verified",
        create_time=proc_create_time,
        cmdline=cmdline_tuple,
        cwd=cwd,
    )

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


def _is_self_or_ancestor(pid: int) -> bool:
    """Check if target pid is the current process or any of its ancestors."""
    current_pid = os.getpid()
    if pid == current_pid:
        return True
    try:
        import psutil

        current = psutil.Process(current_pid)
        for parent in current.parents():
            if parent.pid == pid:
                return True
    except Exception:
        with contextlib.suppress(Exception):
            if hasattr(os, "getppid") and pid == os.getppid():
                return True
    return False


def _verify_process_identity(pid: int, expected_create_time: float | None) -> bool:
    """Verify target process create_time matches expected_create_time if provided.

    Guards against killing an unrelated process that reused the PID after target exit.
    """
    if expected_create_time is None:
        return True
    try:
        import psutil

        proc_obj = psutil.Process(pid)
        if abs(proc_obj.create_time() - expected_create_time) > 0.5:
            logger.warning(
                "Process create_time mismatch for pid=%d (expected %s, got %s) — skipping kill",
                pid,
                expected_create_time,
                proc_obj.create_time(),
            )
            return False
    except Exception as exc:
        logger.warning(
            "Could not verify process identity for pid=%d: %s — skipping kill", pid, exc
        )
        return False
    return True


def _extract_expected_create_time(
    proc: Any | None, expected_create_time: float | None
) -> float | None:
    if expected_create_time is not None:
        return expected_create_time
    if proc is not None:
        if hasattr(proc, "expected_create_time") and isinstance(
            proc.expected_create_time, (int, float)
        ):
            return float(proc.expected_create_time)
        if hasattr(proc, "create_time"):
            import inspect

            ct = proc.create_time
            if callable(ct) and not inspect.iscoroutinefunction(ct):
                with contextlib.suppress(Exception):
                    res = ct()
                    if not inspect.iscoroutine(res) and isinstance(res, (int, float)):
                        return float(res)
            elif isinstance(ct, (int, float)):
                return float(ct)
    return None


def _get_safe_descendants(pid: int) -> list[int] | None:
    """Collect descendant PIDs using psutil.

    Returns None if target descendants include the current process or an ancestor.
    """
    try:
        import psutil

        current_pid = os.getpid()
        try:
            current = psutil.Process(current_pid)
            protected_pids = {p.pid for p in current.parents()} | {current_pid}
        except Exception:
            protected_pids = {current_pid}
            if hasattr(os, "getppid"):
                protected_pids.add(os.getppid())

        target_proc = psutil.Process(pid)
        children = target_proc.children(recursive=True)
        child_pids = [c.pid for c in children]

        if any(p in protected_pids for p in child_pids):
            logger.error(
                "Descendants of pid=%d include current process or ancestor — aborting tree kill",
                pid,
            )
            return None
        return child_pids
    except Exception:
        return []


def platform_kill_process_tree_sync(
    pid: int,
    proc: Any | None = None,
    expected_create_time: float | None = None,
) -> None:
    """Synchronously terminate a process tree (process and all child processes)."""
    if not isinstance(pid, int) or pid <= 0:
        return

    # ISS-005 Guard 1: Never target current process or any of its ancestors
    if _is_self_or_ancestor(pid):
        logger.error(
            "platform_kill_process_tree_sync: Refusing to kill self or ancestor pid=%d",
            pid,
        )
        return

    # ISS-005 Guard 2: Verify process identity (create_time) to avoid PID reuse race
    effective_create_time = _extract_expected_create_time(proc, expected_create_time)
    if not _verify_process_identity(pid, effective_create_time):
        return

    # ISS-005 Guard 3: Ensure descendants do not include current process or ancestors
    descendant_pids = _get_safe_descendants(pid)
    if descendant_pids is None:
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

            # ISS-005 Guard 4: If target pid shares pgrp with backend, killpg would kill backend!
            target_pgid = os.getpgid(pid)
            if hasattr(os, "getpgrp") and target_pgid == os.getpgrp():
                logger.warning(
                    "Target pid=%d is in backend pgrp (%d); skipping killpg to protect backend",
                    pid,
                    target_pgid,
                )
                if descendant_pids:
                    for child_pid in reversed(descendant_pids):
                        with contextlib.suppress(Exception):
                            os.kill(child_pid, signal.SIGKILL)
                with contextlib.suppress(Exception):
                    os.kill(pid, signal.SIGKILL)
                if proc is not None and hasattr(proc, "kill"):
                    with contextlib.suppress(Exception):
                        proc.kill()
                return

            os.killpg(target_pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except (PermissionError, OSError) as exc:
            logger.warning("os.killpg failed for pid=%d: %s", pid, exc)
            if proc is not None and hasattr(proc, "kill"):
                with contextlib.suppress(Exception):
                    proc.kill()


async def platform_kill_process_tree_async(
    pid: int,
    proc: Any | None = None,
    expected_create_time: float | None = None,
) -> None:
    """Asynchronously terminate a process tree (process and all child processes)."""
    if not isinstance(pid, int) or pid <= 0:
        return

    # ISS-005 Guard 1: Never target current process or any of its ancestors
    if _is_self_or_ancestor(pid):
        logger.error(
            "platform_kill_process_tree_async: Refusing to kill self or ancestor pid=%d",
            pid,
        )
        return

    # ISS-005 Guard 2: Verify process identity (create_time) to avoid PID reuse race
    effective_create_time = _extract_expected_create_time(proc, expected_create_time)
    if not _verify_process_identity(pid, effective_create_time):
        return

    # ISS-005 Guard 3: Ensure descendants do not include current process or ancestors
    descendant_pids = _get_safe_descendants(pid)
    if descendant_pids is None:
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

            # ISS-005 Guard 4: If target pid shares pgrp with backend, killpg would kill backend!
            target_pgid = os.getpgid(pid)
            if hasattr(os, "getpgrp") and target_pgid == os.getpgrp():
                logger.warning(
                    "Target pid=%d is in backend pgrp (%d); skipping killpg to protect backend",
                    pid,
                    target_pgid,
                )
                if descendant_pids:
                    for child_pid in reversed(descendant_pids):
                        with contextlib.suppress(Exception):
                            os.kill(child_pid, signal.SIGKILL)
                with contextlib.suppress(Exception):
                    os.kill(pid, signal.SIGKILL)
                if proc is not None and hasattr(proc, "kill"):
                    with contextlib.suppress(Exception):
                        proc.kill()
                return

            os.killpg(target_pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except (PermissionError, OSError) as exc:
            logger.warning("os.killpg failed for pid=%d: %s", pid, exc)
            if proc is not None and hasattr(proc, "kill"):
                with contextlib.suppress(Exception):
                    proc.kill()

