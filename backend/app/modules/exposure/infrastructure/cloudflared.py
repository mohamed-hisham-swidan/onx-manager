"""Orchestrated ``cloudflared`` child-subprocess supervision (Batch 7.2a).

Design constraints (Phase-7.2 spec §7 + §8.5):
  - Orchestrate-only: MCS never bundles the ``cloudflared`` binary.
  - ``--token-file <path>`` (never ``--token``) so the credential never appears
    in the process table (VULN-118896).
  - Token file: temporary, restricted (0o600), least-privilege directory,
    deleted when safe, never logged.
  - Linux/Docker: supervised child with bounded restart + exponential backoff
    and clean shutdown. Windows: bare child subprocess (dies with MCS).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from app.modules.exposure.domain.value_objects import ExposureStatus

logger = logging.getLogger(__name__)

HEALTH_INTERVAL_SECONDS = 30.0
STALE_AFTER_SECONDS = 90.0
MAX_RESTARTS = 5
BACKOFF_BASE_SECONDS = 2.0

# cloudflared metrics endpoints (127.0.0.1:20241..20245) probed for liveness.
_METRICS_PORTS = list(range(20241, 20246))

# Per-attempt TCP connect timeout so one unreachable port cannot stall the
# probe beyond the 30s cadence while the rest of the range is tried.
PROBE_CONNECT_TIMEOUT_SECONDS = 2.0

# stderr markers that indicate the token was rejected/revoked upstream.
_AUTH_FAILURE_MARKERS = (
    "unauthorized",
    "invalid token",
    "authentication failed",
    "access token",
    "tunnel token",
    "error code: 1033",
)


def is_windows() -> bool:
    return sys.platform == "win32"


class CloudflaredSupervisor:
    """Owns the ``cloudflared tunnel run --token-file`` child process.

    A single instance is reused per process (module-level singleton via
    :func:`get_cloudflared_supervisor`) so start/stop/reconcile share state.
    """

    def __init__(
        self,
        *,
        server_id: str | None = None,
        health_interval: float = HEALTH_INTERVAL_SECONDS,
        stale_after: float = STALE_AFTER_SECONDS,
        max_restarts: int = MAX_RESTARTS,
        backoff_base: float = BACKOFF_BASE_SECONDS,
    ) -> None:
        self._server_id = server_id
        self._health_interval = health_interval
        self._stale_after = stale_after
        self._max_restarts = max_restarts
        self._backoff_base = backoff_base

        self._lifecycle_lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None
        self._token_file: Path | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._stderr_reader: asyncio.Task[None] | None = None
        self._drain_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._restart_count = 0
        self._last_health_at = 0.0
        self._status = ExposureStatus.STOPPED
        self._error_message: str | None = None
        self._on_status: Callable[[ExposureStatus], Awaitable[None]] | None = None

    @property
    def server_id(self) -> str | None:
        return self._server_id

    @property
    def status(self) -> ExposureStatus:
        return self._status

    @property
    def error_message(self) -> str | None:
        return self._error_message

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def start(
        self,
        token: bytes,
        *,
        on_status: Callable[[ExposureStatus], Awaitable[None]] | None = None,
    ) -> None:
        async with self._lifecycle_lock:
            if on_status is not None:
                self._on_status = on_status
            if self.is_running:
                logger.info("cloudflared already running — ignoring duplicate start")
                return
            self._stop_event.clear()
            self._restart_count = 0
            await self._spawn(token)
            self._monitor_task = asyncio.create_task(
                self._monitor(),
                name=f"cloudflared-supervisor-{self._server_id or 'panel'}",
            )

    async def stop(self) -> None:
        async with self._lifecycle_lock:
            self._stop_event.set()
            await self._terminate_process()
            if self._monitor_task is not None and not self._monitor_task.done():
                self._monitor_task.cancel()
                try:
                    await self._monitor_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.warning("cloudflared monitor task raised during stop", exc_info=True)
                self._monitor_task = None
            if self._drain_task is not None and not self._drain_task.done():
                self._drain_task.cancel()
                try:
                    await self._drain_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.warning("cloudflared drain task raised during stop", exc_info=True)
                self._drain_task = None
            await self._delete_token_file()
            self._set_status(ExposureStatus.STOPPED)
            logger.info("cloudflared supervisor stopped")

    # -- lifecycle internals -----------------------------------------------

    async def _spawn(self, token: bytes) -> None:
        await self._delete_token_file()
        token_file = self._write_token_file(token)
        self._token_file = token_file
        self._last_health_at = time.monotonic()

        cmd = ["cloudflared", "tunnel", "run", "--token-file", str(token_file)]
        logger.info("spawning cloudflared (pid via subprocess), token via --token-file")

        kwargs: dict[str, object] = {
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
        }
        if not is_windows():
            kwargs["start_new_session"] = True  # own process group for clean shutdown

        self._process = await asyncio.create_subprocess_exec(*cmd, **kwargs)
        self._set_status(ExposureStatus.STARTING)
        logger.info("cloudflared spawned pid=%d", self._process.pid)

        if self._process.stderr is not None:
            self._stderr_reader = asyncio.create_task(
                self._read_stderr(self._process.stderr),
                name="cloudflared-stderr-reader",
            )

        if is_windows():
            # Windows: bare child — no supervision/restart, dies with MCS.
            self._drain_task = asyncio.create_task(
                self._drain_output(),
                name="cloudflared-drain-output",
            )

            def _log_drain_exception(task: asyncio.Task[None]) -> None:
                if not task.cancelled():
                    exc = task.exception()
                    if exc:
                        logger.warning("cloudflared drain task failed: %s", exc, exc_info=exc)

            self._drain_task.add_done_callback(_log_drain_exception)

    async def _read_stderr(self, stream: asyncio.StreamReader) -> None:
        """Continuously scan stderr for auth-failure evidence (RECLAIM_REQUIRED)."""
        try:
            while not self._stop_event.is_set():
                line = await stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").lower()
                if any(marker in text for marker in _AUTH_FAILURE_MARKERS):
                    logger.error(
                        "cloudflared reported an auth failure — surfacing RECLAIM_REQUIRED"
                    )
                    self._set_status(
                        ExposureStatus.RECLAIM_REQUIRED,
                        "cloudflared reported an invalid/revoked tunnel token",
                    )
                    await self._terminate_process()
                    self._stop_event.set()
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("cloudflared stderr reader failed", exc_info=True)

    async def _monitor(self) -> None:
        try:
            while not self._stop_event.is_set():
                if self.is_running:
                    healthy = await self._probe_health()
                    if healthy:
                        self._last_health_at = time.monotonic()
                        self._set_status(ExposureStatus.ACTIVE)
                    else:
                        if (
                            self._status == ExposureStatus.ACTIVE
                            and (time.monotonic() - self._last_health_at) > self._stale_after
                        ):
                            self._set_status(ExposureStatus.DEGRADED)
                else:
                    await self._handle_process_exit()
                await asyncio.sleep(self._health_interval)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("cloudflared monitor crashed")
            self._set_status(ExposureStatus.ERROR)

    async def _handle_process_exit(self) -> None:
        if self._stop_event.is_set():
            return
        if self._status == ExposureStatus.RECLAIM_REQUIRED:
            return
        if is_windows():
            self._set_status(ExposureStatus.ERROR, "cloudflared exited (Windows)")
            self._stop_event.set()
            return
        if self._restart_count >= self._max_restarts:
            self._set_status(
                ExposureStatus.ERROR,
                f"cloudflared restarted too many times ({self._restart_count})",
            )
            self._stop_event.set()
            return
        self._restart_count += 1
        delay = self._backoff_base * (2 ** (self._restart_count - 1))
        logger.warning(
            "cloudflared exited; restart %d/%d in %.0fs",
            self._restart_count,
            self._max_restarts,
            delay,
        )
        await asyncio.sleep(min(delay, 60.0))
        if not self._stop_event.is_set():
            await self._spawn(self._read_token())

    async def _probe_health(self) -> bool:
        """Try every documented metrics port; first reachable endpoint is healthy.

        Accepts any working port in ``_METRICS_PORTS`` (20241..20245). If none
        responds, the probe reports unhealthy and the monitor drives the
        30s/90s DEGRADED/ERROR semantics unchanged.
        """
        for port in _METRICS_PORTS:
            try:
                _reader, writer = await asyncio.wait_for(
                    asyncio.open_connection("127.0.0.1", port),
                    timeout=PROBE_CONNECT_TIMEOUT_SECONDS,
                )
                writer.close()
                await writer.wait_closed()
                return True
            except (TimeoutError, OSError, ConnectionError):
                continue
        return False

    async def _terminate_process(self) -> None:
        proc = self._process
        self._process = None
        if self._drain_task is not None and not self._drain_task.done():
            self._drain_task.cancel()
            try:
                await self._drain_task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug("cloudflared drain task cancellation failed", exc_info=True)
            self._drain_task = None
        if self._stderr_reader is not None and not self._stderr_reader.done():
            self._stderr_reader.cancel()
            try:
                await self._stderr_reader
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug("cloudflared stderr reader cancellation failed", exc_info=True)
            self._stderr_reader = None
        if proc is None:
            return
        self._process = None
        try:
            if proc.returncode is None:
                if is_windows():
                    proc.terminate()
                else:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                try:
                    await asyncio.wait_for(proc.wait(), timeout=10)
                except TimeoutError:
                    if is_windows():
                        proc.kill()
                    else:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    await proc.wait()
        except ProcessLookupError:
            pass
        except Exception:
            logger.warning("cloudflared terminate failed", exc_info=True)

    # -- token file management ---------------------------------------------

    def _write_token_file(self, token: bytes) -> Path:
        from app.core.identity import IDENTITY

        prefix = (
            f"{IDENTITY.temp_prefix_new}cf-srv-{self._server_id[:8]}-"
            if self._server_id
            else f"{IDENTITY.temp_prefix_new}cloudflared-"
        )
        fd, path = tempfile.mkstemp(prefix=prefix, suffix=".token")
        os.close(fd)
        token_file = Path(path)
        token_file.chmod(0o600)
        token_file.write_bytes(token)
        # Least-privilege: remove group/other perms on the parent dir if we own it.
        try:
            parent = token_file.parent
            current = parent.stat().st_mode
            if current & 0o077:
                parent.chmod(current & ~0o077)
        except OSError:
            pass
        return token_file

    async def _delete_token_file(self) -> None:
        if self._token_file is None:
            return
        try:
            self._token_file.unlink(missing_ok=True)
        except OSError:
            logger.debug("cloudflared token file already removed", exc_info=True)
        self._token_file = None

    def _read_token(self) -> bytes:
        if self._token_file is None:
            return b""
        try:
            return self._token_file.read_bytes()
        except OSError:
            return b""

    # -- status ------------------------------------------------------------

    def _set_status(self, status: ExposureStatus, error_message: str | None = None) -> None:
        self._status = status
        self._error_message = error_message
        if self._on_status is not None:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self._on_status(status))
            except RuntimeError:
                pass

    async def _drain_output(self) -> None:
        async def _drain(stream: asyncio.StreamReader | None) -> None:
            while stream is not None:
                line = await stream.readline()
                if not line:
                    break

        await asyncio.gather(
            _drain(self._process.stdout if self._process else None),
            _drain(self._process.stderr if self._process else None),
        )


_singleton: CloudflaredSupervisor | None = None
_server_supervisors: dict[str, CloudflaredSupervisor] = {}


def get_cloudflared_supervisor() -> CloudflaredSupervisor:
    """Module-level singleton so commands/reconcile share one supervisor."""
    global _singleton
    if _singleton is None:
        _singleton = CloudflaredSupervisor()
    return _singleton


def get_server_cloudflared_supervisor(server_id: str) -> CloudflaredSupervisor:
    """Per-server supervisor registry for isolated cloudflared processes."""
    if server_id not in _server_supervisors:
        _server_supervisors[server_id] = CloudflaredSupervisor(server_id=server_id)
    return _server_supervisors[server_id]


def reset_server_cloudflared_supervisors() -> None:
    """Test helper: clear all per-server supervisors so tests start fresh."""
    global _server_supervisors
    _server_supervisors.clear()


def reset_cloudflared_supervisor() -> None:
    """Test helper: drop the singleton so tests start fresh."""
    global _singleton, _server_supervisors
    _singleton = None
    _server_supervisors.clear()
