from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from collections.abc import Awaitable, Callable

from app.core.exceptions import ProviderError
from app.core.identity import IDENTITY
from app.modules.server.application.logging_utils import (
    add_timeline_milestone,
    log_crash_diagnostics,
)
from app.modules.server.domain.aggregate import Server, ServerStatus
from app.modules.server.domain.diagnostics import FailureCode, RuntimeDiagnostics
from app.modules.server.infrastructure.providers.base import (
    ServerHandle,
    ServerProvider,
    ServerRuntimeStatus,
)
from app.modules.shared.value_objects import ServerId

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.supervisor")


class RuntimeSupervisor:
    _instances: dict[str, RuntimeSupervisor] = {}

    def __init__(
        self,
        server: Server,
        provider: ServerProvider,
        handle: ServerHandle,
        repo_get: Callable[[ServerId], Awaitable[Server]],
        repo_save: Callable[[Server], Awaitable[None]],
        on_crash: Callable[[str, RuntimeDiagnostics], None] | None = None,
        health_interval: float = 5.0,
        startup_timeout: float = 120.0,
    ) -> None:
        self._server_id = str(server.id)
        self._server_name = server.name
        self._provider = provider
        self._handle = handle
        self._repo_get = repo_get
        self._repo_save = repo_save
        self._on_crash = on_crash
        self._health_interval = health_interval
        self._startup_timeout = startup_timeout
        self._task: asyncio.Task[None] | None = None
        # Invariant: _active and _stop_event move in lockstep:
        # - When running/supervising: _active is True and _stop_event is clear.
        # - When shutting down, stopped, or crashed: _active is False and _stop_event is set.
        # In _handle_crash(), _active is cleared immediately to False upon entry so concurrent
        # start_for() calls immediately recognize the dying instance as inactive and construct
        # a fresh supervisor, even while async diagnostics persistence and OS cleanup are in-flight.
        self._active = False
        self._started_at = time.monotonic()
        self._last_heartbeat = time.time()
        self._start_duration: float | None = None
        persisted_running_start = (
            server.runtime.running_start_time
            if (
                server.status == ServerStatus.RUNNING
                and server.runtime is not None
                and server.runtime.running_start_time is not None
            )
            else None
        )
        self._initial_ready_at_wall: float | None = persisted_running_start
        self._ready_at_wall: float | None = persisted_running_start
        self._running_persisted: bool = False
        self._stop_event = asyncio.Event()

    @property
    def server_id(self) -> str:
        return self._server_id

    @property
    def server_name(self) -> str:
        return self._server_name

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def last_heartbeat(self) -> float:
        return self._last_heartbeat

    @property
    def start_duration(self) -> float | None:
        return self._start_duration

    @property
    def uptime(self) -> float:
        if self._ready_at_wall is not None:
            return max(0.0, time.time() - self._ready_at_wall)
        return 0.0

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            logger.warning(
                'Supervisor already running for server "%s" (%s)',
                self._server_name,
                self._server_id,
            )
            return
        self._stop_event.clear()
        self._started_at = time.monotonic()
        self._start_duration = None
        self._ready_at_wall = self._initial_ready_at_wall
        self._last_heartbeat = time.time()
        self._active = True
        self._task = asyncio.create_task(
            self._run(),
            name=f"supervisor-{self._server_id}",
        )

    async def stop(self, timeout: float = 10.0) -> None:
        self._active = False
        self._stop_event.set()
        task = self._task
        if task is None or task.done():
            if self._instances.get(self._server_id) is self:
                self._instances.pop(self._server_id, None)
            return
        task.cancel()
        try:
            # Shield: the waiter must NOT await the task directly. Cancelling
            # the waiter while it awaits a cancellation-swallowing task cancels
            # the inner task instead of waking the waiter, losing the timeout
            # wakeup and hanging forever (asyncio Task._fut_waiter mechanics,
            # all versions). The shield completes promptly when cancelled, so
            # the timeout always fires; the already-cancelled inner task is
            # left to exit on its own via the stop event set above.
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except TimeoutError:
            # The task is not observing cancellation (wedged in a
            # non-cancellable await or a foreign-loop limbo). The stop event
            # is already set so a well-behaved _run exits on its own; never
            # let a wedged task hang the stop flow (and the whole test/CI
            # job) forever. See DECISION-2026-09-10 follow-up: Windows CI
            # stalled ~39 min in TestServers::test_stop_server with the only
            # unbounded await in the path being this one.
            logger.warning(
                'Supervisor task for server "%s" did not exit within %.1fs — detaching (task=%s sid=%s)',
                self._server_name,
                timeout,
                task.get_name() if hasattr(task, "get_name") else "?",
                self._server_id,
            )
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.warning(
                'Supervisor stop task raised server="%s" sid=%s provider=%s handle=%s phase=stop',
                self._server_name,
                self._server_id,
                self._provider.provider_type
                if hasattr(self._provider, "provider_type")
                else "?",
                self._handle.external_id if hasattr(self._handle, "external_id") else "?",
                exc_info=True,
            )
        if self._instances.get(self._server_id) is self:
            self._instances.pop(self._server_id, None)

    async def _run(self) -> None:
        logger.info(
            'Supervisor started for server "%s" (%s)',
            self._server_name,
            self._server_id,
        )
        try:
            add_timeline_milestone(
                None, "Supervisor _run started", self._server_name, self._server_id
            )
            await self._verify_startup()
            health_checks = 0
            while not self._stop_event.is_set():
                health_checks += 1
                await self._health_check()
                await asyncio.sleep(self._health_interval)
            logger.info(
                'Supervisor exiting run loop — server="%s" health_checks=%d sid=%s',
                self._server_name,
                health_checks,
                self._server_id,
            )
        except asyncio.CancelledError:
            logger.info(
                'Supervisor cancelled for server "%s" (%s)',
                self._server_name,
                self._server_id,
            )
        except Exception:
            logger.exception(
                'Supervisor crashed server="%s" sid=%s provider=%s handle=%s phase=_run',
                self._server_name,
                self._server_id,
                self._provider.provider_type if hasattr(self._provider, "provider_type") else "?",
                self._handle.external_id if hasattr(self._handle, "external_id") else "?",
            )
        finally:
            self._active = False
            if self._instances.get(self._server_id) is self:
                self._instances.pop(self._server_id, None)
            logger.info(
                'Supervisor stopped for server "%s" (%s)',
                self._server_name,
                self._server_id,
            )

    async def _persist_running_transition(self, ready_reason: str = "") -> bool:
        backoffs = [0.5, 1.0, 2.0]
        for attempt in range(len(backoffs)):
            try:
                server = await self._repo_get(ServerId(self._server_id))
                if self._stop_event.is_set():
                    logger.info(
                        'Concurrent stop detected during RUNNING transition for server "%s" — skipping sid=%s',
                        self._server_name,
                        self._server_id,
                    )
                    return False
                if server.status != ServerStatus.STARTING:
                    if server.status == ServerStatus.RUNNING:
                        self._running_persisted = True
                        return True
                    return False

                pid = (
                    self._handle.metadata.get("pid", 0)
                    if hasattr(self._handle, "metadata") and self._handle.metadata
                    else (server.runtime.pid or 0)
                )
                port = (
                    self._handle.metadata.get("port", server.properties.port.value)
                    if hasattr(self._handle, "metadata") and self._handle.metadata
                    else (server.runtime.port or server.properties.port.value)
                )
                external_id = self._handle.external_id or server.runtime.external_id
                start_time = server.runtime.start_time
                try:
                    live_addr = await self._provider.get_address(self._handle)
                except Exception:
                    live_addr = None
                host = live_addr or server.runtime.host or "127.0.0.1"

                server.mark_running(
                    pid=pid,
                    port=port,
                    host=host,
                    external_id=external_id,
                    start_time=start_time,
                )
                await self._repo_save(server)
                self._running_persisted = True
                if server.deployment and server.deployment.root_path:
                    try:
                        from pathlib import Path

                        from app.modules.backup.application.two_tier_restore import (
                            cleanup_pre_restore_backups,
                        )

                        srv_dir = Path(server.deployment.server_directory())
                        await asyncio.to_thread(
                            cleanup_pre_restore_backups, str(server.id), srv_dir
                        )
                        if srv_dir.name != str(server.id):
                            await asyncio.to_thread(
                                cleanup_pre_restore_backups, srv_dir.name, srv_dir
                            )
                    except Exception:
                        pass
                add_timeline_milestone(
                    None,
                    f"Server marked running{f' ({ready_reason})' if ready_reason else ''}",
                    self._server_name,
                    self._server_id,
                )
                return True
            except Exception as exc:
                logger.warning(
                    'Attempt %d/3 to persist RUNNING for server "%s" failed: %s',
                    attempt + 1,
                    self._server_name,
                    exc,
                )
                if attempt < len(backoffs) - 1:
                    await asyncio.sleep(backoffs[attempt])

        logger.error(
            'Failed to transition server "%s" to RUNNING after 3 attempts — sid=%s',
            self._server_name,
            self._server_id,
        )
        return False

    async def _verify_startup(self) -> None:
        deadline = self._started_at + self._startup_timeout
        iteration = 0
        while time.monotonic() < deadline:
            if self._stop_event.is_set():
                return
            remaining = deadline - time.monotonic()
            ready = await self._provider.wait_ready(
                server_id=self._server_id,
                handle=self._handle,
                timeout=max(remaining, 5.0),
            )
            if ready:
                elapsed = time.monotonic() - self._started_at
                self._start_duration = elapsed
                self._ready_at_wall = self._initial_ready_at_wall or time.time()
                self._last_heartbeat = time.time()
                logger.info(
                    'Server "%s" ready after %.1fs — sid=%s',
                    self._server_name,
                    elapsed,
                    self._server_id,
                )
                add_timeline_milestone(
                    None,
                    "Startup verification passed",
                    self._server_name,
                    self._server_id,
                )
                await self._persist_running_transition(ready_reason="startup verified")
                return

            iteration += 1
            alive = await self._provider.verify_process(self._handle)
            logger.info(
                'Server "%s" verify_process=%s remaining=%.0fs iter=%d sid=%s',
                self._server_name,
                alive,
                remaining,
                iteration,
                self._server_id,
            )
            if not alive:
                diag = await self._provider.collect_diagnostics(self._handle)
                logger.info(
                    'Server "%s" crash diag: pid=%s exit=%s lines=%d sid=%s',
                    self._server_name,
                    diag.pid,
                    diag.exit_code,
                    len(diag.last_log_lines or []),
                    self._server_id,
                )
                if not diag.failure_code:
                    diag.failure_code = FailureCode.STARTUP_TIMEOUT
                if not diag.failure_reason:
                    diag.failure_reason = "Process died during startup verification"
                await self._handle_crash(diag)
                return
            await asyncio.sleep(2)

        elapsed = time.monotonic() - self._started_at
        alive = await self._provider.verify_process(self._handle)
        if alive:
            logger.info(
                'Server "%s" startup deadline elapsed=%.1fs but process still alive — continuing sid=%s',
                self._server_name,
                elapsed,
                self._server_id,
            )
            await self._persist_running_transition(ready_reason="deadline continue")
            return
        diag = await self._provider.collect_diagnostics(self._handle)
        log_crash_diagnostics(
            message="Startup deadline exceeded",
            server_name=self._server_name,
            server_id=self._server_id,
            pid=diag.pid,
            exit_code=diag.exit_code,
            log_lines=diag.last_log_lines,
            failure_code=FailureCode.STARTUP_TIMEOUT.value,
            failure_reason=f"Startup timeout after {elapsed:.1f}s",
        )
        diag.failure_code = FailureCode.STARTUP_TIMEOUT
        diag.failure_reason = (
            f"Startup timeout after {elapsed:.1f}s while waiting for readiness probe"
        )
        diag.startup_duration = elapsed
        await self._handle_crash(diag)

    async def _health_check(self) -> None:
        try:
            alive = await self._provider.verify_process(self._handle)
            if not alive:
                if self._stop_event.is_set():
                    return

                status = await self._provider.status(self._handle)
                diag = await self._provider.collect_diagnostics(self._handle)

                is_crash = (
                    status != ServerRuntimeStatus.STOPPED
                    or (diag and diag.failure_code is not None)
                    or (diag and diag.exit_code is not None and diag.exit_code != 0)
                )

                if is_crash:
                    if diag and not diag.failure_code:
                        diag.failure_code = FailureCode.RUNTIME_PROCESS_LOST
                        pid = (
                            self._handle.metadata.get("pid")
                            if hasattr(self._handle, "metadata")
                            else None
                        )
                        diag.failure_reason = (
                            f"Runtime process lost during RUNNING state (pid={pid})"
                        )
                    await self._handle_crash(diag)
                    return

                logger.info(
                    'health_check server="%s" sid=%s provider=%s handle=%s '
                    "phase=health_check status=stopped",
                    self._server_name,
                    self._server_id,
                    self._provider.provider_type
                    if hasattr(self._provider, "provider_type")
                    else "?",
                    self._handle.external_id if hasattr(self._handle, "external_id") else "?",
                )
                add_timeline_milestone(
                    None,
                    "Health check — process stopped",
                    self._server_name,
                    self._server_id,
                )
                try:
                    server = await self._repo_get(ServerId(self._server_id))
                    server.mark_stopped()
                    await self._repo_save(server)
                    add_timeline_milestone(
                        None,
                        "Server marked stopped",
                        self._server_name,
                        self._server_id,
                    )
                except Exception:
                    logger.exception(
                        'Failed to persist stopped state for server "%s" — sid=%s',
                        self._server_name,
                        self._server_id,
                    )
                finally:
                    self._active = False
                    self._stop_event.set()
                return
            if not self._running_persisted:
                await self._persist_running_transition(ready_reason="health_check_self_heal")
            self._last_heartbeat = time.time()
        except ProviderError as exc:
            # Provider explicitly cannot verify (e.g., tmux missing, job not found)
            # Treat as process lost — fail-safe
            logger.warning(
                'health_check provider error — treating as process lost server="%s" sid=%s: %s',
                self._server_name,
                self._server_id,
                exc,
            )
            diag = None
            try:
                diag = await self._provider.collect_diagnostics(self._handle)
            except Exception as diag_exc:
                logger.error(
                    "collect_diagnostics failed during ProviderError handling "
                    'server="%s" sid=%s: %s',
                    self._server_name,
                    self._server_id,
                    diag_exc,
                )
                diag = RuntimeDiagnostics(
                    provider=self._provider.provider_type,
                    runtime_handle=str(self._handle),
                )
            diag.failure_code = FailureCode.RUNTIME_PROCESS_LOST
            pid = self._handle.metadata.get("pid") if hasattr(self._handle, "metadata") else None
            diag.failure_reason = f"Provider error during health check: {exc} (pid={pid})"
            await self._handle_crash(diag)
        except Exception:
            # Truly unexpected error — log full trace AND treat as crash (fail-safe)
            logger.exception(
                "health_check unexpected error — treating as process lost "
                'server="%s" sid=%s provider=%s handle=%s',
                self._server_name,
                self._server_id,
                self._provider.provider_type if hasattr(self._provider, "provider_type") else "?",
                self._handle.external_id if hasattr(self._handle, "external_id") else "?",
            )
            diag = None
            try:
                diag = await self._provider.collect_diagnostics(self._handle)
            except Exception as diag_exc:
                logger.error(
                    "collect_diagnostics failed during exception handling "
                    'server="%s" sid=%s: %s',
                    self._server_name,
                    self._server_id,
                    diag_exc,
                )
                diag = RuntimeDiagnostics(
                    provider=self._provider.provider_type,
                    runtime_handle=str(self._handle),
                )
            diag.failure_code = FailureCode.RUNTIME_PROCESS_LOST
            pid = self._handle.metadata.get("pid") if hasattr(self._handle, "metadata") else None
            diag.failure_reason = f"Unexpected error during health check (pid={pid})"
            await self._handle_crash(diag)

    async def _stop_runtime_on_crash(self) -> None:
        still_running = False
        try:
            status = await self._provider.status(self._handle)
            if status == ServerRuntimeStatus.RUNNING:
                still_running = True
        except Exception:
            still_running = True

        if not still_running:
            try:
                alive = await self._provider.verify_process(self._handle)
                if alive:
                    still_running = True
            except Exception:
                pass

        if still_running:
            logger.warning(
                'Server "%s" still running during crash handling — stopping runtime sid=%s',
                self._server_name,
                self._server_id,
            )
            try:
                await asyncio.wait_for(
                    self._provider.stop(self._handle, force=False),
                    timeout=20.0,
                )
            except Exception:
                try:
                    await asyncio.wait_for(
                        self._provider.stop(self._handle, force=True),
                        timeout=10.0,
                    )
                except Exception as exc:
                    logger.warning(
                        'Force stop during crash failed for server "%s" sid=%s: %s',
                        self._server_name,
                        self._server_id,
                        exc,
                    )

    async def _cleanup_os_resources(self) -> None:
        session_name = self._handle.external_id if hasattr(self._handle, "external_id") else ""
        if not session_name:
            return
        try:
            res = subprocess.run(
                ["tmux", "has-session", "-t", session_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=5,
            )
            if res.returncode == 0:
                logger.info(
                    'Cleaning up tmux session after crash — server="%s" session=%s sid=%s',
                    self._server_name,
                    session_name,
                    self._server_id,
                )
                subprocess.run(
                    ["tmux", "kill-session", "-t", session_name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=5,
                )
        except subprocess.TimeoutExpired:
            logger.warning(
                'tmux cleanup timed out server="%s" session=%s sid=%s',
                self._server_name,
                session_name,
                self._server_id,
            )
        except (FileNotFoundError, OSError):
            pass
        except Exception:
            logger.debug(
                'tmux cleanup after crash failed server="%s" sid=%s',
                self._server_name,
                self._server_id,
            )

    async def _handle_crash(self, diag: RuntimeDiagnostics) -> None:
        # Clear _active immediately upon entry so concurrent start_for() calls recognize this
        # crashing instance as dead/dying and never reuse it while crash handling is in flight.
        self._active = False
        if self._stop_event.is_set():
            logger.info(
                'Server "%s" stop already requested — crash suppressed (%s)',
                self._server_name,
                self._server_id,
            )
            return

        prov_type = (
            self._provider.provider_type if hasattr(self._provider, "provider_type") else "?"
        )
        handle_ext = self._handle.external_id if hasattr(self._handle, "external_id") else "?"

        log_crash_diagnostics(
            message="Runtime process lost",
            server_name=self._server_name,
            server_id=self._server_id,
            pid=self._handle.metadata.get("pid") if hasattr(self._handle, "metadata") else None,
            exit_code=diag.exit_code,
            log_lines=diag.last_log_lines,
            failure_code=diag.failure_code.value if diag.failure_code else None,
            failure_reason=diag.failure_reason,
        )

        await self._stop_runtime_on_crash()
        await self._cleanup_os_resources()

        try:
            server = await self._repo_get(ServerId(self._server_id))
            server.crash(
                exit_code=diag.exit_code or -1,
                last_log_lines=diag.last_log_lines or [],
            )
            await self._repo_save(server)
        except Exception:
            logger.critical(
                'Failed to persist crash state for server "%s" — crash data will be LOST. '
                "sid=%s provider=%s handle=%s phase=_handle_crash persist diag=%s",
                self._server_name,
                self._server_id,
                prov_type,
                handle_ext,
                diag.to_dict(),
                exc_info=True,
            )

        if self._on_crash:
            try:
                self._on_crash(self._server_id, diag)
            except Exception:
                logger.exception(
                    'Crash callback failed server="%s" sid=%s provider=%s handle=%s phase=_handle_crash callback',
                    self._server_name,
                    self._server_id,
                    prov_type,
                    handle_ext,
                )

        self._active = False
        self._stop_event.set()

    @classmethod
    def start_for(
        cls,
        server: Server,
        provider: ServerProvider,
        handle: ServerHandle,
        repo_get: Callable[[ServerId], Awaitable[Server]],
        repo_save: Callable[[Server], Awaitable[None]],
        on_crash: Callable[[str, RuntimeDiagnostics], None] | None = None,
        health_interval: float = 5.0,
        startup_timeout: float = 120.0,
    ) -> RuntimeSupervisor:
        sid = str(server.id)
        existing = cls._instances.get(sid)
        if existing is not None:
            is_dead_or_dying = (
                not existing._active
                or existing._stop_event.is_set()
                or (existing._task is not None and existing._task.done())
            )
            if is_dead_or_dying:
                cls._instances.pop(sid, None)
            elif existing._handle == handle and existing._provider == provider:
                logger.warning(
                    'Supervisor already active for server "%s" (%s), returning existing',
                    server.name,
                    sid,
                )
                return existing
            else:
                logger.info(
                    'Supervisor handle/provider changed for server "%s" (%s) — '
                    "stopping existing and constructing fresh",
                    server.name,
                    sid,
                )
                existing._active = False
                existing._stop_event.set()
                if existing._task is not None and not existing._task.done():
                    existing._task.cancel()
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(existing.stop())
                except RuntimeError:
                    pass
                cls._instances.pop(sid, None)

        supervisor = cls(
            server=server,
            provider=provider,
            handle=handle,
            repo_get=repo_get,
            repo_save=repo_save,
            on_crash=on_crash,
            health_interval=health_interval,
            startup_timeout=startup_timeout,
        )
        supervisor._active = True
        cls._instances[sid] = supervisor
        asyncio.ensure_future(supervisor.start())
        return supervisor

    @classmethod
    async def stop_for(cls, server_id: str) -> None:
        supervisor = cls._instances.get(server_id)
        if supervisor:
            await supervisor.stop()

    @classmethod
    def get_for(cls, server_id: str) -> RuntimeSupervisor | None:
        return cls._instances.get(server_id)

    @classmethod
    def is_supervised(cls, server_id: str) -> bool:
        return server_id in cls._instances
