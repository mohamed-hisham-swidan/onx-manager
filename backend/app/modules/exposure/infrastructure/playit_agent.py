"""Orchestrated ``playit`` child-subprocess supervision.

Supervises the host-level playit.gg agent process:
  - Non-interactive claim detection via stdout/stderr extraction
  - Secret key passed via deterministic 0600 file (never on argv)
  - Cross-process mutual exclusion via atomic file locking (fcntl.flock)
  - Startup orphan reconciliation with dual PID + socket liveness probe
  - Process start/stop/restart with bounded exponential backoff
  - Health monitoring and state synchronization
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import secrets
import shutil
import signal
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from app.core.config import AppSettings
from app.core.identity import IDENTITY
from app.core.platform_lock import FileLock
from app.core.process_utils import platform_pid_alive
from app.modules.exposure.domain.value_objects import ExposureStatus

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.exposure.playit")

HEALTH_INTERVAL_SECONDS = 30.0
STALE_AFTER_SECONDS = 90.0
MAX_RESTARTS = 5
BACKOFF_BASE_SECONDS = 2.0
RECONCILE_TIMEOUT_SECONDS = 2.0
SOCKET_PROBE_TIMEOUT_SECONDS = 0.2
SIGTERM_WAIT_SECONDS = 5.0
SIGKILL_WAIT_SECONDS = 3.0

# Regex patterns for playit claim links, secret keys, and auth errors
_CLAIM_URL_PATTERN = re.compile(r"https?://playit\.gg/claim/([a-zA-Z0-9_-]+)")
_SECRET_PATTERNS = (
    re.compile(r"secret:\s*([a-zA-Z0-9_\-\.\:\=]+)", re.IGNORECASE),
    re.compile(r'secret\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r"secret_key:\s*([a-zA-Z0-9_\-\.\:\=]+)", re.IGNORECASE),
    re.compile(r"^([0-9a-fA-F]{64})$"),
)
_AUTH_FAILURE_MARKERS = (
    "invalid secret",
    "unauthorized",
    "secret rejected",
    "authentication failed",
    "claim expired",
)


_PROJECT_ROOT = Path(__file__).resolve().parents[5]
_BACKEND_DIR = Path(__file__).resolve().parents[4]


def _get_default_run_dir() -> Path:
    """Return canonical absolute runtime directory for playit process state."""
    try:
        raw_servers_dir = AppSettings().servers_data_dir
        servers_dir = Path(raw_servers_dir)
        if not servers_dir.is_absolute():
            if (_PROJECT_ROOT / raw_servers_dir).exists():
                servers_dir = _PROJECT_ROOT / raw_servers_dir
            elif (_BACKEND_DIR / raw_servers_dir).exists():
                servers_dir = _BACKEND_DIR / raw_servers_dir
            else:
                servers_dir = _PROJECT_ROOT / raw_servers_dir
        return (servers_dir.parent / "run" / "playit").resolve()
    except Exception:
        return (_PROJECT_ROOT / "data" / "run" / "playit").resolve()


def _get_playitd_cmd() -> list[str]:
    """Return the command prefix to spawn the playit daemon."""
    playitd = shutil.which("playitd")
    if playitd:
        return [playitd]
    if Path("/opt/playit/playitd").is_file():
        return ["/opt/playit/playitd"]
    return ["playitd"]


def _get_playit_cli_cmd() -> list[str]:
    """Return the command prefix to spawn the playit CLI."""
    playit = shutil.which("playit")
    if playit:
        return [playit]
    if Path("/opt/playit/agent").is_file():
        return ["/opt/playit/agent"]
    return ["playit"]


async def generate_playit_claim_code(*, timeout: float = 10.0) -> tuple[str, str]:
    """Generate a real 10-character hex claim code and claim URL via `playit claim generate`.

    Falls back to a 10-hex token (secrets.token_hex(5)) if playit binary is unavailable
    or times out (e.g., in lightweight CI / unit test environments).
    """
    proc: asyncio.subprocess.Process | None = None
    try:
        cmd = [*_get_playit_cli_cmd(), "claim", "generate"]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode == 0 and stdout:
            code = stdout.decode("utf-8").strip()
            if code and len(code) <= 64:
                return code, f"https://playit.gg/claim/{code}"
    except TimeoutError:
        logger.warning("playit claim generate timed out after %.1fs", timeout)
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            with contextlib.suppress(Exception):
                await proc.wait()
    except (FileNotFoundError, OSError) as exc:
        logger.warning("playit binary not available during claim generate: %s", exc)
    except Exception as exc:
        logger.warning("Error running playit claim generate: %s", exc)

    fallback_code = secrets.token_hex(5)
    return fallback_code, f"https://playit.gg/claim/{fallback_code}"


def is_windows() -> bool:
    return sys.platform == "win32"


def _is_pid_alive(pid: int) -> bool:
    """Check if process with given PID exists and is accessible."""
    if pid <= 0:
        return False
    return platform_pid_alive(pid)


def _is_pid_alive_and_playit(pid: int) -> bool:
    """Verify PID exists and is actually a playit/playitd process (prevents recycled PID reuse)."""
    if not _is_pid_alive(pid):
        return False
    if is_windows():
        return True

    # Inspect /proc/{pid}/cmdline on Linux
    try:
        cmdline_path = Path(f"/proc/{pid}/cmdline")
        if cmdline_path.exists():
            raw = cmdline_path.read_bytes()
            cmdline = raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").lower()
            return "playit" in cmdline or "playitd" in cmdline
    except Exception:
        pass
    return True


async def _probe_unix_socket(
    socket_path: Path, timeout: float = SOCKET_PROBE_TIMEOUT_SECONDS
) -> bool:
    """Perform a rapid connect probe on the Unix domain socket to verify active liveness."""
    if not socket_path.exists():
        return False
    if is_windows():
        return True
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(str(socket_path)),
            timeout=timeout,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


class PlayitAgentSupervisor:
    """Owns the host-level ``playit`` child process and claim/tunnel supervision."""

    def __init__(
        self,
        *,
        run_dir: Path | None = None,
        health_interval: float = HEALTH_INTERVAL_SECONDS,
        stale_after: float = STALE_AFTER_SECONDS,
        max_restarts: int = MAX_RESTARTS,
        backoff_base: float = BACKOFF_BASE_SECONDS,
    ) -> None:
        self._run_dir = run_dir or _get_default_run_dir()
        self._health_interval = health_interval
        self._stale_after = stale_after
        self._max_restarts = max_restarts
        self._backoff_base = backoff_base

        self._lifecycle_lock = asyncio.Lock()
        self._current_secret_bytes: bytes | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._external_pid: int | None = None
        self._secret_file: Path | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._output_reader: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._restart_count = 0
        self._last_health_at = 0.0
        self._status = ExposureStatus.STOPPED
        self._error_message: str | None = None
        self._claim_code: str | None = None
        self._claim_url: str | None = None
        self._on_status: Callable[[ExposureStatus], Awaitable[None]] | None = None
        self._on_secret: Callable[[str], Awaitable[None]] | None = None
        self._on_reconcile: Callable[[], Awaitable[None]] | None = None
        self._background_tasks: set[asyncio.Task[Any]] = set()

    def _spawn_background_task(self, coro: Awaitable[Any]) -> asyncio.Task[Any]:
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    @property
    def run_dir(self) -> Path:
        return self._run_dir

    @property
    def secret_file_path(self) -> Path:
        return self._run_dir / "agent.secret"

    @property
    def socket_path(self) -> Path:
        return self._run_dir / "agent.sock"

    @property
    def pid_file_path(self) -> Path:
        return self._run_dir / "agent.pid"

    @property
    def lock_file_path(self) -> Path:
        return self._run_dir / "agent.lock"

    @property
    def pid(self) -> int | None:
        if self._process is not None and self._process.returncode is None:
            return self._process.pid
        return self._external_pid

    @property
    def status(self) -> ExposureStatus:
        return self._status

    @property
    def error_message(self) -> str | None:
        return self._error_message

    @property
    def claim_code(self) -> str | None:
        return self._claim_code

    @property
    def claim_url(self) -> str | None:
        return self._claim_url

    @property
    def is_running(self) -> bool:
        if self._process is not None and self._process.returncode is None:
            return True
        if self._external_pid is not None:
            return _is_pid_alive_and_playit(self._external_pid)
        return False

    @property
    def last_health_at(self) -> float:
        return self._last_health_at

    async def reconcile_startup(self) -> bool:
        """Startup reconciliation: inspects PID and socket paths to re-attach or clean orphans."""
        try:
            return await asyncio.wait_for(
                self._reconcile_startup_internal(),
                timeout=RECONCILE_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.warning(
                "Playit startup reconciliation timed out after %.1fs", RECONCILE_TIMEOUT_SECONDS
            )
            return False
        except Exception:
            logger.exception("Error during playit startup reconciliation")
            return False

    async def _reconcile_startup_internal(self) -> bool:
        lock = FileLock(self.lock_file_path)
        if not lock.acquire(timeout=1.0):
            logger.warning("Could not acquire playit startup reconciliation lock; skipping")
            return False

        try:
            if not self.pid_file_path.exists():
                self._cleanup_stale_artifacts(clean_pid=False)
                return False

            pid_str = ""
            try:
                pid_str = self.pid_file_path.read_text(encoding="utf-8").strip()
                pid = int(pid_str)
            except (ValueError, OSError):
                logger.warning("Corrupted playit PID file containing '%s'; cleaning up", pid_str)
                self._cleanup_stale_artifacts(clean_pid=True)
                return False

            if not _is_pid_alive_and_playit(pid):
                logger.info(
                    "Found stale playit PID file pointing to dead or recycled PID %d; cleaning up",
                    pid,
                )
                self._cleanup_stale_artifacts(clean_pid=True)
                return False

            # Stage 2: Verify socket responsiveness
            socket_alive = await _probe_unix_socket(
                self.socket_path, timeout=SOCKET_PROBE_TIMEOUT_SECONDS
            )
            if socket_alive:
                logger.info(
                    "Playit startup reconciliation: re-attached to running daemon (PID %d)",
                    pid,
                )
                self._external_pid = pid
                if self.secret_file_path.exists():
                    self._secret_file = self.secret_file_path
                self._last_health_at = time.monotonic()
                self._set_status(ExposureStatus.ACTIVE)
                self._stop_event.clear()
                if self._monitor_task is None or self._monitor_task.done():
                    self._monitor_task = asyncio.create_task(
                        self._monitor_loop(), name="playit-supervisor-monitor"
                    )
                return True

            logger.warning(
                "Playit daemon PID %d is alive but socket is unresponsive; terminating orphan",
                pid,
            )
            await self._terminate_pid_direct(pid)
            self._cleanup_stale_artifacts(clean_pid=True)
            return False
        finally:
            lock.release()

    async def start(
        self,
        secret: bytes | str | None = None,
        claim_code: str | None = None,
        on_status: Callable[[ExposureStatus], Awaitable[None]] | None = None,
        on_secret: Callable[[str], Awaitable[None]] | None = None,
        on_reconcile: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Start supervised playit agent child process with atomic idempotency and paths."""
        async with self._lifecycle_lock:
            if on_status is not None:
                self._on_status = on_status
            if on_secret is not None:
                self._on_secret = on_secret
            if on_reconcile is not None:
                self._on_reconcile = on_reconcile

            secret_bytes = (
                secret
                if isinstance(secret, bytes)
                else secret.encode("utf-8")
                if secret is not None
                else None
            )

            # Check if supervisor is already active/running
            if self.is_running:
                if secret_bytes and secret_bytes != self._current_secret_bytes:
                    logger.info("Restarting playit supervisor with updated secret")
                    await self._stop_internal()
                elif claim_code and claim_code != self._claim_code:
                    logger.info("Restarting playit supervisor with updated claim code")
                    await self._stop_internal()
                else:
                    logger.debug(
                        "playit supervisor already active/running with matching config; reusing"
                    )
                    return
            else:
                await self._stop_internal()

            # Ensure runtime directory permissions and prepare paths
            try:
                self._run_dir.mkdir(parents=True, exist_ok=True)
                if not is_windows():
                    with contextlib.suppress(OSError):
                        os.chmod(self._run_dir, 0o700)
            except (PermissionError, OSError) as exc:
                err_msg = f"Failed to initialize runtime state directory at {self._run_dir}: {exc}"
                logger.error(err_msg)
                self._error_message = err_msg
                self._set_status(ExposureStatus.ERROR)
                raise

            self._stop_event.clear()
            self._restart_count = 0
            self._error_message = None
            self._current_secret_bytes = secret_bytes
            self._claim_code = claim_code

            if secret_bytes:
                self._secret_file = self._write_secret_file(secret_bytes)
            else:
                self._secret_file = None

            await self._spawn_child()
            self._last_health_at = time.monotonic()

            if self._secret_file:
                self._set_status(ExposureStatus.STARTING)
            else:
                self._set_status(ExposureStatus.CLAIM_REQUIRED)

            self._monitor_task = asyncio.create_task(
                self._monitor_loop(), name="playit-supervisor-monitor"
            )

    async def stop(self) -> None:
        """Gracefully stop the supervisor and clean up deterministic files."""
        async with self._lifecycle_lock:
            await self._stop_internal()

    async def _stop_internal(self) -> None:
        self._stop_event.set()
        if self._monitor_task is not None and not self._monitor_task.done():
            self._monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._monitor_task
            self._monitor_task = None

        if self._background_tasks:
            for task in list(self._background_tasks):
                if not task.done():
                    task.cancel()
            await asyncio.gather(*list(self._background_tasks), return_exceptions=True)
            self._background_tasks.clear()

        await self._terminate_process()
        self._cleanup_secret_file()
        self._cleanup_pid_file()
        self._cleanup_socket_file()
        self._current_secret_bytes = None
        self._set_status(ExposureStatus.STOPPED)

    async def restart(
        self,
        secret: bytes | str | None = None,
        claim_code: str | None = None,
        on_status: Callable[[ExposureStatus], Awaitable[None]] | None = None,
        on_secret: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        """Restart supervisor with a fresh secret or claim."""
        await self.stop()
        await self.start(
            secret=secret,
            claim_code=claim_code,
            on_status=on_status or self._on_status,
            on_secret=on_secret or self._on_secret,
        )

    def _write_secret_file(self, secret: bytes) -> Path:
        """Write secret to a deterministic file with restricted (0600) permissions."""
        self._run_dir.mkdir(parents=True, exist_ok=True)
        if not is_windows():
            with contextlib.suppress(OSError):
                os.chmod(self._run_dir, 0o700)

        path = self.secret_file_path
        fd = os.open(str(path), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        try:
            os.write(fd, secret)
        finally:
            os.close(fd)

        if not is_windows():
            with contextlib.suppress(OSError):
                os.chmod(path, 0o600)
        return path

    def _cleanup_secret_file(self) -> None:
        """Securely remove deterministic secret file."""
        if self.secret_file_path.exists():
            try:
                self.secret_file_path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning(
                    "Failed to remove playit secret file %s: %s", self.secret_file_path, exc
                )
        self._secret_file = None

    def _write_pid_file(self, pid: int) -> None:
        try:
            self._run_dir.mkdir(parents=True, exist_ok=True)
            self.pid_file_path.write_text(str(pid), encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to write playit PID file %s: %s", self.pid_file_path, exc)

    def _cleanup_pid_file(self) -> None:
        with contextlib.suppress(OSError):
            self.pid_file_path.unlink(missing_ok=True)

    def _cleanup_socket_file(self) -> None:
        with contextlib.suppress(OSError):
            self.socket_path.unlink(missing_ok=True)

    def _cleanup_stale_artifacts(self, *, clean_pid: bool = True) -> None:
        if clean_pid:
            self._cleanup_pid_file()
        self._cleanup_secret_file()
        self._cleanup_socket_file()

    async def _spawn_child(self) -> None:
        """Spawn the playit child process using deterministic paths."""
        self._cleanup_socket_file()
        if self._secret_file:
            cmd = list(_get_playitd_cmd())
            cmd.extend(
                [
                    "--secret-path",
                    str(self._secret_file),
                    "--socket-path",
                    str(self.socket_path),
                ]
            )
        elif self._claim_code:
            cmd = list(_get_playit_cli_cmd())
            cmd.extend(["claim", "exchange", self._claim_code])
        else:
            cmd = list(_get_playit_cli_cmd())
            cmd.extend(["claim", "url"])

        logger.info("Spawning playit subprocess (argv safe: secret passed via deterministic file)")

        extra_kwargs: dict = {}
        if not is_windows():
            extra_kwargs["preexec_fn"] = os.setsid

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            close_fds=True,
            **extra_kwargs,
        )

        if self._process.pid:
            self._write_pid_file(self._process.pid)

        self._output_reader = asyncio.create_task(
            self._read_output(self._process), name="playit-output-reader"
        )

    async def _read_stream(self, stream: asyncio.StreamReader | None, stream_name: str) -> None:
        """Continuously read lines from a single stream (stdout or stderr)."""
        if stream is None:
            return
        try:
            while not self._stop_event.is_set():
                line_b = await stream.readline()
                if not line_b:
                    break
                line = line_b.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                await self._process_output_line(line, stream_name)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("Playit %s reader exited: %s", stream_name, exc)

    async def _process_output_line(self, line: str, stream_name: str) -> None:
        """Process a decoded output line from stdout or stderr."""
        # Match claim URL
        match = _CLAIM_URL_PATTERN.search(line)
        if match:
            self._claim_url = match.group(0)
            self._claim_code = match.group(1)
            self._set_status(ExposureStatus.CLAIM_REQUIRED)
            logger.info("Playit claim URL captured: %s", self._claim_url)
            return

        # Match auth failures
        line_lower = line.lower()
        if any(m in line_lower for m in _AUTH_FAILURE_MARKERS):
            logger.warning("Playit auth failure marker detected on %s: %s", stream_name, line)
            self._error_message = line
            self._set_status(ExposureStatus.RECLAIM_REQUIRED)
            return

        # Match secret from claim exchange (unauthenticated claim mode)
        if not self._secret_file:
            for pattern in _SECRET_PATTERNS:
                sec_match = pattern.search(line)
                if sec_match:
                    captured_secret = sec_match.group(1).strip()
                    if captured_secret and len(captured_secret) >= 10:
                        logger.info("Playit agent secret key captured from claim exchange")
                        self._claim_code = None
                        self._set_status(ExposureStatus.STARTING)
                        if self._on_secret:
                            try:
                                self._spawn_background_task(self._on_secret(captured_secret))
                            except Exception as exc:
                                logger.exception("Error invoking on_secret callback: %s", exc)
                        break

    async def _read_output(self, proc: asyncio.subprocess.Process) -> None:
        """Read stdout and stderr lines for claim links, secret keys, or auth failure markers."""
        try:
            await asyncio.gather(
                self._read_stream(proc.stdout, "stdout"),
                self._read_stream(proc.stderr, "stderr"),
            )
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("Playit output reader exited: %s", exc)

    async def _monitor_loop(self) -> None:
        """Periodic health monitoring and crash recovery."""
        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(self._health_interval)
                if self._stop_event.is_set():
                    break

                if self.is_running:
                    self._last_health_at = time.monotonic()
                    if self._status in (ExposureStatus.STARTING, ExposureStatus.DEGRADED):
                        self._set_status(ExposureStatus.ACTIVE)
                    if self._on_reconcile:
                        try:
                            await self._on_reconcile()
                        except Exception as exc:
                            logger.debug("Playit reconciliation callback failed: %s", exc)
                else:
                    await self._handle_process_exit()

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("Unexpected error in playit monitor loop: %s", exc)

    async def _handle_process_exit(self) -> None:
        """Handle unexpected child exit and apply restart backoff."""
        if self._status == ExposureStatus.RECLAIM_REQUIRED:
            return

        if not self._secret_file:
            logger.info(
                "Playit claim exchange process exited (returncode %s)",
                self._process.returncode if self._process else None,
            )
            return

        if self._restart_count >= self._max_restarts:
            self._error_message = f"playit exceeded max restarts ({self._max_restarts})"
            self._set_status(ExposureStatus.ERROR)
            return

        self._restart_count += 1
        delay = self._backoff_base**self._restart_count
        logger.warning(
            "playit daemon exited unexpectedly; restart %d/%d in %.1fs",
            self._restart_count,
            self._max_restarts,
            delay,
        )
        self._set_status(ExposureStatus.DEGRADED)

        try:
            await asyncio.sleep(delay)
            if not self._stop_event.is_set():
                await self._spawn_child()
        except asyncio.CancelledError:
            pass

    async def _terminate_process(self) -> None:
        """Terminate the child subprocess or re-attached external process cleanly."""
        proc = self._process
        ext_pid = self._external_pid
        self._process = None
        self._external_pid = None

        if self._output_reader is not None and not self._output_reader.done():
            self._output_reader.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._output_reader
            self._output_reader = None

        pid = proc.pid if proc is not None and proc.returncode is None else ext_pid
        if pid is None:
            return

        await self._terminate_pid_direct(pid)

    async def _terminate_pid_direct(self, pid: int) -> None:
        """Send direct SIGTERM then bounded SIGKILL fallback to a specific PID."""
        logger.info("Terminating playit process (PID %s)", pid)
        if is_windows():
            import subprocess

            try:
                await asyncio.to_thread(
                    subprocess.run,
                    ["taskkill", "/F", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except Exception as exc:
                logger.warning("Error terminating playit process %s on Windows: %s", pid, exc)
            return

        try:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                return

            start = time.monotonic()
            while time.monotonic() - start < SIGTERM_WAIT_SECONDS:
                if not _is_pid_alive(pid):
                    return
                await asyncio.sleep(0.1)

            logger.warning("playit (PID %s) did not exit on SIGTERM; sending SIGKILL", pid)
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                return

            start_kill = time.monotonic()
            while time.monotonic() - start_kill < SIGKILL_WAIT_SECONDS:
                if not _is_pid_alive(pid):
                    return
                await asyncio.sleep(0.1)
        except ProcessLookupError:
            pass
        except Exception as exc:
            logger.warning("Error terminating playit process %s: %s", pid, exc)

    def _set_status(self, new_status: ExposureStatus) -> None:
        """Transition status and dispatch async notification callback."""
        if self._status != new_status:
            logger.info("Playit status changed: %s -> %s", self._status, new_status)
            self._status = new_status
            if self._on_status is not None:
                try:
                    self._spawn_background_task(self._on_status(new_status))
                except Exception as exc:
                    logger.warning("Failed to dispatch on_status callback: %s", exc)


_GLOBAL_PLAYIT_SUPERVISOR: PlayitAgentSupervisor | None = None


def get_playit_supervisor() -> PlayitAgentSupervisor:
    """Module-level singleton accessor for PlayitAgentSupervisor."""
    global _GLOBAL_PLAYIT_SUPERVISOR
    if _GLOBAL_PLAYIT_SUPERVISOR is None:
        _GLOBAL_PLAYIT_SUPERVISOR = PlayitAgentSupervisor()
    return _GLOBAL_PLAYIT_SUPERVISOR


def reset_playit_supervisor() -> None:
    """Reset the module-level singleton (intended for hermetic test teardown)."""
    global _GLOBAL_PLAYIT_SUPERVISOR
    _GLOBAL_PLAYIT_SUPERVISOR = None
