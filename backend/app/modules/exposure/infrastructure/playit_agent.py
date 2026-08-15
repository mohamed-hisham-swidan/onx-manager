"""Orchestrated ``playit`` child-subprocess supervision (Batch 7.2b).

Supervises the host-level playit.gg agent process:
  - Non-interactive claim detection via stdout/stderr extraction
  - Secret key passed via temporary 0600 file (never on argv)
  - Process start/stop/restart with bounded exponential backoff
  - Health monitoring and state synchronization
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import signal
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from app.modules.exposure.domain.value_objects import ExposureStatus

logger = logging.getLogger("mcs.exposure.playit")

HEALTH_INTERVAL_SECONDS = 30.0
STALE_AFTER_SECONDS = 90.0
MAX_RESTARTS = 5
BACKOFF_BASE_SECONDS = 2.0

# Regex patterns for playit claim links and claim codes
_CLAIM_URL_PATTERN = re.compile(r"https?://playit\.gg/claim/([a-zA-Z0-9_-]+)")
_AUTH_FAILURE_MARKERS = (
    "invalid secret",
    "unauthorized",
    "secret rejected",
    "authentication failed",
    "claim expired",
)


def is_windows() -> bool:
    return sys.platform == "win32"


class PlayitAgentSupervisor:
    """Owns the host-level ``playit`` child process and claim/tunnel supervision."""

    def __init__(
        self,
        *,
        health_interval: float = HEALTH_INTERVAL_SECONDS,
        stale_after: float = STALE_AFTER_SECONDS,
        max_restarts: int = MAX_RESTARTS,
        backoff_base: float = BACKOFF_BASE_SECONDS,
    ) -> None:
        self._health_interval = health_interval
        self._stale_after = stale_after
        self._max_restarts = max_restarts
        self._backoff_base = backoff_base

        self._lifecycle_lock = asyncio.Lock()
        self._current_secret_bytes: bytes | None = None
        self._process: asyncio.subprocess.Process | None = None
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
        return self._process is not None and self._process.returncode is None

    @property
    def last_health_at(self) -> float:
        return self._last_health_at

    async def start(
        self,
        secret: bytes | str | None = None,
        on_status: Callable[[ExposureStatus], Awaitable[None]] | None = None,
    ) -> None:
        """Start the supervised playit agent child process with idempotency guard."""
        async with self._lifecycle_lock:
            if on_status is not None:
                self._on_status = on_status

            secret_bytes = (
                secret if isinstance(secret, bytes)
                else secret.encode("utf-8") if secret is not None
                else None
            )

            # Check if supervisor is already active/running
            if self.is_running or self._status in (
                ExposureStatus.STARTING,
                ExposureStatus.ACTIVE,
                ExposureStatus.CLAIM_REQUIRED,
            ):
                # If secret is being supplied to an unauthenticated instance, restart with secret
                if secret_bytes and secret_bytes != self._current_secret_bytes:
                    logger.info("Restarting playit supervisor with updated secret")
                    await self._stop_internal()
                else:
                    logger.debug(
                        "playit supervisor already active/starting; reusing running instance"
                    )
                    return

            self._stop_event.clear()
            self._restart_count = 0
            self._error_message = None
            self._current_secret_bytes = secret_bytes

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
        """Gracefully stop the supervisor and clean up secret files."""
        async with self._lifecycle_lock:
            await self._stop_internal()

    async def _stop_internal(self) -> None:
        self._stop_event.set()
        if self._monitor_task is not None and not self._monitor_task.done():
            self._monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._monitor_task
            self._monitor_task = None

        await self._terminate_process()
        self._cleanup_secret_file()
        self._current_secret_bytes = None
        self._set_status(ExposureStatus.STOPPED)

    async def restart(self, secret: bytes | str | None = None) -> None:
        """Restart supervisor with a fresh secret or claim."""
        await self.stop()
        await self.start(secret=secret, on_status=self._on_status)

    def _write_secret_file(self, secret: bytes) -> Path:
        """Write secret to a temporary file with restricted (0600) permissions."""
        fd, path = tempfile.mkstemp(prefix="mcs_playit_secret_", suffix=".secret")
        try:
            os.chmod(path, 0o600)
            os.write(fd, secret)
        finally:
            os.close(fd)
        return Path(path)

    def _cleanup_secret_file(self) -> None:
        """Securely remove temporary secret file."""
        if self._secret_file is not None and self._secret_file.exists():
            try:
                self._secret_file.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("Failed to remove playit secret file %s: %s", self._secret_file, exc)
            finally:
                self._secret_file = None

    async def _spawn_child(self) -> None:
        """Spawn the playit child process."""
        cmd = ["playit"]
        if self._secret_file:
            cmd.extend(["run", "--secret-path", str(self._secret_file)])
        else:
            cmd.extend(["claim", "url"])

        logger.info("Spawning playit subprocess (argv safe: secret passed via file)")

        extra_kwargs: dict = {}
        if not is_windows():
            extra_kwargs["preexec_fn"] = os.setsid

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **extra_kwargs,
        )

        self._output_reader = asyncio.create_task(
            self._read_output(self._process), name="playit-output-reader"
        )

    async def _read_output(self, proc: asyncio.subprocess.Process) -> None:
        """Read stdout and stderr lines for claim links or auth failure markers."""
        try:
            while not self._stop_event.is_set() and proc.returncode is None:
                line_b = b""
                if proc.stdout:
                    line_b = await proc.stdout.readline()
                if not line_b and proc.stderr:
                    line_b = await proc.stderr.readline()
                if not line_b:
                    if proc.returncode is not None:
                        break
                    await asyncio.sleep(0.1)
                    continue

                line = line_b.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                # Match claim URL
                match = _CLAIM_URL_PATTERN.search(line)
                if match:
                    self._claim_url = match.group(0)
                    self._claim_code = match.group(1)
                    self._set_status(ExposureStatus.CLAIM_REQUIRED)
                    logger.info("Playit claim URL captured: %s", self._claim_url)

                # Match auth failures
                line_lower = line.lower()
                if any(m in line_lower for m in _AUTH_FAILURE_MARKERS):
                    logger.warning("Playit auth failure marker detected: %s", line)
                    self._error_message = line
                    self._set_status(ExposureStatus.RECLAIM_REQUIRED)

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

        if self._restart_count >= self._max_restarts:
            self._error_message = f"playit exceeded max restarts ({self._max_restarts})"
            self._set_status(ExposureStatus.ERROR)
            return

        self._restart_count += 1
        delay = self._backoff_base**self._restart_count
        logger.warning(
            "playit exited unexpectedly; restart %d/%d in %.1fs",
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
        """Terminate the child subprocess cleanly."""
        proc = self._process
        self._process = None
        if self._output_reader is not None and not self._output_reader.done():
            self._output_reader.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._output_reader
            self._output_reader = None

        if proc is None or proc.returncode is not None:
            return

        pid = proc.pid
        logger.info("Terminating playit subprocess (PID %s)", pid)

        try:
            if not is_windows():
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            else:
                proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except TimeoutError:
            logger.warning("playit (PID %s) did not exit on SIGTERM; sending SIGKILL", pid)
            try:
                if not is_windows():
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                else:
                    proc.kill()
                await asyncio.wait_for(proc.wait(), timeout=3.0)
            except Exception as exc:
                logger.warning("Error killing playit process %s: %s", pid, exc)
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
                    asyncio.create_task(self._on_status(new_status))
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
