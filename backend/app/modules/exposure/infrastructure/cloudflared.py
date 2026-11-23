"""Orchestrated ``cloudflared`` child-subprocess supervision.

Design & security invariants:
  - Orchestrate-only: ONX Manager never bundles the ``cloudflared`` binary; it
    detects ``cloudflared`` on PATH via :meth:`CloudflaredSupervisor.is_installed`
    and surfaces a clear actionable error if missing.
  - Permanent Mode (``start_token``): runs ``cloudflared tunnel --no-autoupdate run``
    passing the Tunnel Token strictly via the ``TUNNEL_TOKEN`` environment
    variable, NEVER as a plaintext ``--token`` CLI argument (VULN-118896).
  - Token-file mode (``start``): runs ``cloudflared tunnel run --token-file <path>``
    with a mode-0600 file and also provides ``TUNNEL_TOKEN`` via environment.
  - Quick Preview Mode (``start_quick``): runs
    ``cloudflared tunnel --no-autoupdate --url http://127.0.0.1:<panel_port>``
    and streams ``stderr``/``stdout`` to extract the ephemeral
    ``https://*.trycloudflare.com`` URL.
  - Subprocess lifecycle: tracked per supervisor instance and terminated cleanly
    via ``SIGTERM`` -> grace timeout -> ``SIGKILL`` on stop or shutdown.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import shutil
import signal
import sys
import tempfile
import time
from collections import deque
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

_STDLIB_CREATE_SUBPROCESS_EXEC = asyncio.create_subprocess_exec

# Regex to capture ephemeral Quick Tunnel URL emitted by cloudflared on stderr/stdout.
_TRYCLOUDFLARE_URL_RE = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

# stderr markers that indicate the token was rejected/revoked upstream.
_AUTH_FAILURE_MARKERS = (
    "unauthorized",
    "invalid token",
    "invalid tunnel token",
    "authentication failed",
    "access token",
    "tunnel token is invalid",
    "not a valid jwt",
    "failed to parse tunnel token",
    "error code: 1033",
)

# Output markers indicating cloudflared established at least one edge connection.
_CONNECTION_READY_MARKERS = (
    "registered tunnel connection",
    "connection registered",
)


def is_windows() -> bool:
    return sys.platform == "win32"


class CloudflaredSupervisor:
    """Owns the ``cloudflared`` child process lifecycle for panel or server tunnels.

    A single instance is reused per process for the panel (via
    :func:`get_cloudflared_supervisor`) and per server (via
    :func:`get_server_cloudflared_supervisor`).
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
        self._token_secret: bytes = b""
        self._mode: str = "token_file"  # "token_file" | "token_env" | "quick"
        self._quick_local_url: str | None = None
        self._quick_url: str | None = None
        self._error_code: str | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._stderr_reader: asyncio.Task[None] | None = None
        self._stdout_reader: asyncio.Task[None] | None = None
        self._drain_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._restart_count = 0
        self._last_health_at = 0.0
        self._last_stderr_lines: deque[str] = deque(maxlen=10)
        self._status = ExposureStatus.STOPPED
        self._error_message: str | None = None
        self._on_status: Callable[[ExposureStatus], Awaitable[None]] | None = None
        self._on_url: Callable[[str], Awaitable[None]] | None = None

    @staticmethod
    def is_installed() -> bool:
        """Return True if ``cloudflared`` binary is discoverable on PATH."""
        return shutil.which("cloudflared") is not None

    @property
    def server_id(self) -> str | None:
        return self._server_id

    @property
    def status(self) -> ExposureStatus:
        return self._status

    @property
    def error_code(self) -> str | None:
        return self._error_code

    @property
    def error_message(self) -> str | None:
        return self._error_message

    @property
    def quick_url(self) -> str | None:
        return self._quick_url

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def start(
        self,
        token: bytes,
        *,
        on_status: Callable[[ExposureStatus], Awaitable[None]] | None = None,
    ) -> None:
        """Start ``cloudflared tunnel run`` using a restricted token file + TUNNEL_TOKEN env."""
        async with self._lifecycle_lock:
            if on_status is not None:
                self._on_status = on_status
            self._on_url = None
            if self.is_running:
                logger.info("cloudflared already running — ignoring duplicate start")
                return
            self._mode = "token_file"
            self._quick_local_url = None
            self._quick_url = None
            self._token_secret = token
            self._error_code = None
            self._error_message = None
            self._last_stderr_lines.clear()
            self._stop_event.clear()
            self._restart_count = 0
            spawned = await self._spawn(token)
            if spawned:
                self._monitor_task = asyncio.create_task(
                    self._monitor(),
                    name=f"cloudflared-supervisor-{self._server_id or 'panel'}",
                )

    async def start_token(
        self,
        token: bytes,
        *,
        on_status: Callable[[ExposureStatus], Awaitable[None]] | None = None,
    ) -> None:
        """Start Permanent Mode: ``cloudflared tunnel run`` via ``TUNNEL_TOKEN`` env."""
        async with self._lifecycle_lock:
            if on_status is not None:
                self._on_status = on_status
            self._on_url = None
            if self.is_running:
                await self._terminate_process()
            self._mode = "token_env"
            self._quick_local_url = None
            self._quick_url = None
            self._token_secret = token
            self._error_code = None
            self._error_message = None
            self._last_stderr_lines.clear()
            self._stop_event.clear()
            self._restart_count = 0
            spawned = await self._spawn_token_env(token)
            if spawned:
                self._monitor_task = asyncio.create_task(
                    self._monitor(),
                    name=f"cloudflared-supervisor-{self._server_id or 'panel'}",
                )

    async def start_quick(
        self,
        local_url: str,
        *,
        on_status: Callable[[ExposureStatus], Awaitable[None]] | None = None,
        on_url: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        """Start Quick Preview Mode: ``cloudflared tunnel --no-autoupdate --url <local_url>``."""
        async with self._lifecycle_lock:
            if on_status is not None:
                self._on_status = on_status
            self._on_url = on_url
            if self.is_running:
                await self._terminate_process()
            self._mode = "quick"
            self._quick_local_url = local_url
            self._quick_url = None
            self._token_secret = b""
            self._error_code = None
            self._error_message = None
            self._last_stderr_lines.clear()
            self._stop_event.clear()
            self._restart_count = 0
            spawned = await self._spawn_quick(local_url)
            if spawned:
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
            self._token_secret = b""
            self._quick_url = None
            self._error_code = None
            self._set_status(ExposureStatus.STOPPED)
            logger.info("cloudflared supervisor stopped")

    # -- lifecycle internals -----------------------------------------------

    async def _spawn_cmd(
        self,
        cmd: list[str],
        *,
        extra_env: dict[str, str] | None = None,
        use_drain_on_windows: bool = True,
    ) -> bool:
        """Execute cloudflared cleanly without leaking secrets on argv."""
        self._last_health_at = time.monotonic()

        kwargs: dict[str, object] = {
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
        }
        if extra_env:
            merged_env = os.environ.copy()
            merged_env.update(extra_env)
            kwargs["env"] = merged_env
        if not is_windows():
            kwargs["start_new_session"] = True  # own process group for clean shutdown

        try:
            if (
                cmd
                and cmd[0] == "cloudflared"
                and asyncio.create_subprocess_exec is _STDLIB_CREATE_SUBPROCESS_EXEC
                and not self.is_installed()
            ):
                raise FileNotFoundError("cloudflared binary not found on PATH")
            self._process = await asyncio.create_subprocess_exec(*cmd, **kwargs)
        except (FileNotFoundError, OSError) as exc:
            err_msg = (
                "cloudflared binary is not installed or not executable. "
                "Install cloudflared on this host and try again."
            )
            logger.error("Failed to spawn cloudflared: %s", exc)
            self._error_code = "CLOUDFLARED_NOT_FOUND"
            self._stop_event.set()
            self._set_status(ExposureStatus.ERROR, err_msg)
            return False

        self._set_status(ExposureStatus.STARTING)
        logger.info("cloudflared spawned pid=%d mode=%s", self._process.pid, self._mode)

        if self._process.stderr is not None:
            self._stderr_reader = asyncio.create_task(
                self._read_stderr(self._process.stderr),
                name="cloudflared-stderr-reader",
            )
        if self._mode == "quick" and self._process.stdout is not None:
            self._stdout_reader = asyncio.create_task(
                self._read_stderr(self._process.stdout),
                name="cloudflared-stdout-reader",
            )

        if is_windows() and use_drain_on_windows:
            # Windows: drain non-active streams cleanly so buffers do not stall.
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

        return True

    async def _spawn(self, token: bytes) -> bool:
        await self._delete_token_file()
        token_file = self._write_token_file(token)
        self._token_file = token_file
        token_str = token.decode("utf-8", errors="ignore").strip()

        cmd = ["cloudflared", "tunnel", "run", "--token-file", str(token_file)]
        logger.info("spawning cloudflared (pid via subprocess), token via --token-file")
        extra_env = {"TUNNEL_TOKEN": token_str} if token_str else None
        return await self._spawn_cmd(cmd, extra_env=extra_env)

    async def _spawn_token_env(self, token: bytes) -> bool:
        await self._delete_token_file()
        token_str = token.decode("utf-8", errors="ignore").strip()
        cmd = ["cloudflared", "tunnel", "--no-autoupdate", "run"]
        logger.info("spawning cloudflared permanent tunnel (token via TUNNEL_TOKEN env)")
        return await self._spawn_cmd(
            cmd,
            extra_env={"TUNNEL_TOKEN": token_str},
            use_drain_on_windows=False,
        )

    async def _spawn_quick(self, local_url: str) -> bool:
        await self._delete_token_file()
        cmd = ["cloudflared", "tunnel", "--no-autoupdate", "--url", local_url]
        logger.info("spawning cloudflared quick preview tunnel -> %s", local_url)
        return await self._spawn_cmd(cmd, use_drain_on_windows=False)

    async def _read_stderr(self, stream: asyncio.StreamReader) -> None:
        """Scan stream output for auth errors, connection readiness, or Quick Tunnel URLs."""
        try:
            while not self._stop_event.is_set():
                line = await stream.readline()
                if not line:
                    break
                raw_line = line.decode("utf-8", errors="replace").strip()
                if raw_line:
                    self._last_stderr_lines.append(raw_line)
                lower = raw_line.lower()

                if self._mode == "quick" and not self._quick_url:
                    url_match = _TRYCLOUDFLARE_URL_RE.search(raw_line)
                    if url_match:
                        captured_url = url_match.group(0)
                        self._quick_url = captured_url
                        logger.info("cloudflared quick tunnel URL captured: %s", captured_url)
                        if self._on_url is not None:
                            with contextlib.suppress(Exception):
                                await self._on_url(captured_url)
                        self._set_status(ExposureStatus.ACTIVE)

                if any(marker in lower for marker in _AUTH_FAILURE_MARKERS):
                    logger.error(
                        "cloudflared reported an auth failure — surfacing RECLAIM_REQUIRED"
                    )
                    self._error_code = "RECLAIM_REQUIRED"
                    self._set_status(
                        ExposureStatus.RECLAIM_REQUIRED,
                        "cloudflared reported an invalid or revoked tunnel token",
                    )
                    await self._terminate_process()
                    self._stop_event.set()
                    return

                if self._mode != "quick" and any(
                    marker in lower for marker in _CONNECTION_READY_MARKERS
                ):
                    self._last_health_at = time.monotonic()
                    if self._status != ExposureStatus.ACTIVE:
                        self._set_status(ExposureStatus.ACTIVE)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("cloudflared stderr reader failed", exc_info=True)

    async def _monitor(self) -> None:
        try:
            while not self._stop_event.is_set():
                if self.is_running:
                    if self._mode == "quick":
                        if self._quick_url is not None:
                            self._last_health_at = time.monotonic()
                            if self._status != ExposureStatus.ACTIVE:
                                self._set_status(ExposureStatus.ACTIVE)
                    else:
                        healthy = await self._probe_health()
                        if healthy:
                            self._last_health_at = time.monotonic()
                            self._set_status(ExposureStatus.ACTIVE)
                        elif (
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
            self._set_status(
                ExposureStatus.ERROR, "cloudflared health monitor encountered an error"
            )

    async def _handle_process_exit(self) -> None:
        if self._stop_event.is_set():
            return
        if self._status == ExposureStatus.RECLAIM_REQUIRED:
            return

        stderr_hint = (
            self._last_stderr_lines[-1] if self._last_stderr_lines else None
        )

        if is_windows():
            msg = stderr_hint or "cloudflared exited unexpectedly"
            self._error_code = "CLOUDFLARED_EXITED"
            self._set_status(ExposureStatus.ERROR, msg)
            self._stop_event.set()
            return
        if self._restart_count >= self._max_restarts:
            msg = (
                f"cloudflared exited repeatedly ({self._restart_count} restarts): {stderr_hint}"
                if stderr_hint
                else f"cloudflared restarted too many times ({self._restart_count})"
            )
            self._error_code = "CLOUDFLARED_EXITED"
            self._set_status(ExposureStatus.ERROR, msg)
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
            if self._mode == "quick" and self._quick_local_url:
                self._quick_url = None
                await self._spawn_quick(self._quick_local_url)
            elif self._mode == "token_env" and self._token_secret:
                await self._spawn_token_env(self._token_secret)
            else:
                await self._spawn(self._read_token() or self._token_secret)

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
        if self._stdout_reader is not None and not self._stdout_reader.done():
            self._stdout_reader.cancel()
            try:
                await self._stdout_reader
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug("cloudflared stdout reader cancellation failed", exc_info=True)
            self._stdout_reader = None
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
        if error_message is not None or status == ExposureStatus.ACTIVE:
            self._error_message = error_message
        if status == ExposureStatus.ACTIVE:
            self._error_code = None
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
