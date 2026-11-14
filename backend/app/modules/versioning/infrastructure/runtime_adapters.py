"""Per-request Docker runtime and clean-export adapters for live refresh.

P2-6a2 keeps the refresh/rollback domain free of server-module imports while
still driving lifecycle through the canonical command handlers:

* :class:`DockerServerRuntimeAdapter` dispatches ``StartServerCommand`` and
  ``StopServerCommand`` through ``StartServerHandler`` / ``StopServerHandler``
  (Option B), so DB state, the runtime supervisor, port claims, and events stay
  in sync. Only the active refresh/rollback's own ``journal_id`` is exempted
  from the boot guard.
* :class:`CleanExportStageAdapter` runs ``CleanExportService.export`` inside
  ``asyncio.to_thread`` and fails closed when an unresolved ``${ONX_SECRET_*}``
  placeholder reaches the export.

Both adapters assert that their blocking half never executes on the event-loop
thread. A non-Docker runtime provider fails closed with
:class:`ServerModeVersioningDisabledError` (HTTP 409).
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from app.core.allowlist import CLASS_D_PANEL_KEYS
from app.core.command_bus import CommandResult
from app.core.exceptions import (
    ConflictError,
    ServerModeVersioningDisabledError,
    ServerNotRunningError,
    ValidationError,
)
from app.core.host_state import HostStateLayout
from app.core.identity import IDENTITY
from app.modules.server.application.commands.start_server import StartServerCommand
from app.modules.server.application.commands.stop_server import (
    StopServerCommand,
    is_stop_confirmed,
)
from app.modules.server.domain.value_objects import default_provider_for_platform
from app.modules.server.infrastructure.signal_detection import poll_boot_signals
from app.modules.versioning.domain.lockfile import LockfileV21
from app.modules.versioning.infrastructure.clean_export import (
    CleanExportRequest,
    CleanExportResult,
    CleanExportService,
)

logger = logging.getLogger(__name__)

DEFAULT_COMMAND_TIMEOUT_SECONDS = 240.0
DEFAULT_DOCKER_TIMEOUT_SECONDS = 15.0
DOCKER_STOP_VERIFY_TIMEOUT_SECONDS = 10.0
DOCKER_STOP_POLL_INTERVAL_SECONDS = 0.2


def require_docker_provider(provider: str | None) -> str:
    """Return the effective provider name or fail closed for non-Docker hosts."""
    effective = (provider or default_provider_for_platform()).strip() or "unknown"
    if effective != "docker":
        raise ServerModeVersioningDisabledError(
            "Live refresh requires the Docker runtime provider; "
            f"this server uses '{effective}'"
        )
    return effective


def _assert_off_loop(loop_thread_id: int, adapter_name: str) -> None:
    if threading.get_ident() == loop_thread_id:
        raise RuntimeError(
            f"{adapter_name} must be invoked off the event-loop thread"
        )


class DockerServerRuntimeAdapter:
    """Synchronous runtime port that routes all lifecycle work through commands."""

    def __init__(
        self,
        *,
        server_id: str,
        loop: asyncio.AbstractEventLoop,
        start_handler: Callable[[StartServerCommand], Awaitable[CommandResult]],
        stop_handler: Callable[[StopServerCommand], Awaitable[CommandResult]],
        server_dir: str | Path,
        startup_timeout_seconds: float,
        provider_name: str | None = None,
        container_name: str | None = None,
        docker_command: Callable[[list[str], float], str] | None = None,
        command_timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    ) -> None:
        require_docker_provider(provider_name)
        if startup_timeout_seconds <= 0:
            raise ValidationError(
                "startup_timeout_seconds must be positive",
                field="startup_timeout_seconds",
            )
        self._server_id = server_id
        self._loop = loop
        self._loop_thread_id = threading.get_ident()
        self._start_handler = start_handler
        self._stop_handler = stop_handler
        self._server_dir = Path(server_dir)
        self._startup_timeout_seconds = float(startup_timeout_seconds)
        explicit_name = str(container_name).strip() if container_name else ""
        self._explicit_container_name = explicit_name
        self._configured_container_name = (
            explicit_name or f"{IDENTITY.temp_prefix_new}{server_id}"
        )
        self._container_name = self._configured_container_name
        self._resolved_container_name: str | None = None
        self._docker_command = docker_command or _default_docker_command
        self._command_timeout_seconds = float(command_timeout_seconds)
        self._refresh_start: datetime | None = None
        self._allow_journal_id: str | None = None

    # ------------------------------------------------------------------
    # Refresh-scoped state (called on the loop before start())
    # ------------------------------------------------------------------

    @property
    def startup_timeout_seconds(self) -> float:
        return self._startup_timeout_seconds

    @property
    def refresh_start(self) -> datetime | None:
        return self._refresh_start

    def mark_refresh_start(self, started_at: datetime) -> None:
        """Record the cutoff used by every boot-log / crash-report probe."""
        self._refresh_start = started_at

    def prepare_start(self, journal_id: str) -> None:
        """Bind the exact journal whose boot guard exemption applies."""
        if not journal_id:
            raise ValidationError("journal_id must be non-empty", field="journal_id")
        self._allow_journal_id = journal_id

    # ------------------------------------------------------------------
    # ServerRuntimePort
    # ------------------------------------------------------------------

    def is_running(self) -> bool:
        self._assert_worker_thread()
        return self._container_running_unchecked()

    def process_alive(self) -> bool:
        self._assert_worker_thread()
        return self._container_running_unchecked()

    def boot_log(self) -> str:
        self._assert_worker_thread()
        try:
            return self._docker_logs(self._refresh_start)
        except Exception as exc:  # noqa: BLE001 - a missing log is not alive evidence
            logger.warning("Unable to read Docker logs for %s: %s", self._server_id, exc)
            return ""

    def start(self) -> bool:
        self._assert_worker_thread()
        if self._refresh_start is None:
            self._refresh_start = datetime.now(UTC)
        command = StartServerCommand(
            server_id=self._server_id,
            allow_journal_id=self._allow_journal_id,
        )
        try:
            result = self._dispatch(
                self._start_handler(command), timeout=self._command_timeout_seconds
            )
        except BaseException:
            # B-2: a cancelled/timed-out handler may already have executed
            # ``docker start``. Never leave the failed new container running
            # with the new tree bind-mounted.
            self._cleanup_failed_start()
            raise
        if not result.success:
            self._cleanup_failed_start()
            raise ConflictError(
                result.error
                or f"Server '{self._server_id}' failed to start after the swap"
            )
        return True

    def stop(self) -> bool:
        self._assert_worker_thread()
        container_name = self._active_container_name()
        command = StopServerCommand(server_id=self._server_id, reason="live refresh")
        confirmed = False
        try:
            result = self._dispatch(
                self._stop_handler(command), timeout=self._command_timeout_seconds
            )
            confirmed = is_stop_confirmed(result)
        except ServerNotRunningError:
            # B-1: the handler derives this from DB status only. Docker may
            # still be running, so fall through to a fresh inspect + force kill.
            confirmed = False
        except TimeoutError:
            confirmed = False

        if confirmed and not self._is_container_running(container_name):
            return True

        if self._is_container_running(container_name):
            logger.warning(
                "Stop command did not stop container %s; forcing kill/remove",
                container_name,
            )
            self._force_remove_container(container_name)
        return not self._is_container_running(container_name)

    def ready(self) -> bool:
        self._assert_worker_thread()
        if self._refresh_start is None:
            return False
        # Resolve/cache the real container name here, off the event loop.
        self._active_container_name()
        future = asyncio.run_coroutine_threadsafe(self._ready_async(), self._loop)
        try:
            return bool(
                future.result(timeout=self._startup_timeout_seconds + 30.0)
            )
        except Exception as exc:  # noqa: BLE001 - readiness is a boolean port
            logger.warning("Docker readiness probe failed for %s: %s", self._server_id, exc)
            future.cancel()
            return False

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _assert_worker_thread(self) -> None:
        _assert_off_loop(self._loop_thread_id, "DockerServerRuntimeAdapter")

    def _dispatch(self, coro: Awaitable[CommandResult], *, timeout: float) -> CommandResult:
        future = asyncio.run_coroutine_threadsafe(cast(Any, coro), self._loop)
        try:
            return future.result(timeout=timeout)
        except BaseException:
            future.cancel()
            raise

    def _container_candidates(self) -> list[str]:
        candidates = [self._configured_container_name]
        for name in (
            f"{IDENTITY.temp_prefix_new}{self._server_id}",
            f"{IDENTITY.temp_prefix_legacy}{self._server_id}",
        ):
            if name not in candidates:
                candidates.append(name)
        return candidates

    def _inspect_state(self, name: str) -> dict[str, Any] | None:
        """Return Docker's ``State`` object for ``name``, or ``None`` if absent."""
        if not name:
            return None
        try:
            output = self._docker_command(
                ["inspect", "--format", "{{json .State}}", name],
                DEFAULT_DOCKER_TIMEOUT_SECONDS,
            )
        except Exception:  # noqa: BLE001 - absent container is a valid state
            return None
        text = output.strip().strip("'\"")
        if not text:
            return None
        if text.lower() in ("true", "false"):
            return {"Running": text.lower() == "true"}
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            return None
        if isinstance(parsed, bool):
            return {"Running": parsed}
        if isinstance(parsed, dict):
            return cast(dict[str, Any], parsed)
        return None

    def _is_container_running(self, name: str) -> bool:
        state = self._inspect_state(name)
        return bool(state and state.get("Running"))

    def _active_container_name(self) -> str:
        """Resolve the real container name, honouring legacy ``mcs-`` names.

        B-3: the DB handle (``server.runtime.external_id``) is authoritative.
        When Docker only knows a different managed name, fail closed instead of
        acting on a container that is not the one the panel recorded.
        """
        if self._resolved_container_name is not None:
            return self._resolved_container_name
        found = [
            name
            for name in self._container_candidates()
            if self._inspect_state(name) is not None
        ]
        if found:
            if self._explicit_container_name:
                if self._explicit_container_name not in found:
                    raise ConflictError(
                        f"Server '{self._server_id}' runtime handle points at "
                        f"'{self._explicit_container_name}' but Docker only knows "
                        f"'{found[0]}'; refusing to act on a mismatched container"
                    )
                chosen = self._explicit_container_name
            else:
                chosen = found[0]
        else:
            chosen = self._configured_container_name
        self._resolved_container_name = chosen
        self._container_name = chosen
        return chosen

    def _run_docker_quiet(self, args: list[str]) -> bool:
        try:
            self._docker_command(args, DEFAULT_DOCKER_TIMEOUT_SECONDS)
            return True
        except Exception as exc:  # noqa: BLE001 - cleanup is best effort
            logger.debug("docker %s failed during cleanup: %s", " ".join(args[:2]), exc)
            return False

    def _wait_until_not_running(self, name: str) -> bool:
        deadline = time.monotonic() + DOCKER_STOP_VERIFY_TIMEOUT_SECONDS
        while True:
            if not self._is_container_running(name):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(DOCKER_STOP_POLL_INTERVAL_SECONDS)

    def _force_remove_container(self, name: str) -> None:
        if self._is_container_running(name):
            self._run_docker_quiet(["kill", name])
        self._run_docker_quiet(["rm", "-f", name])
        self._wait_until_not_running(name)

    def _cleanup_failed_start(self) -> None:
        """B-2: provider-level kill/rm after a failed or timed-out start."""
        try:
            name = self._active_container_name()
        except ConflictError:
            name = self._configured_container_name
        self._force_remove_container(name)
        # A later start may create the container afresh; re-resolve next time.
        self._resolved_container_name = None

    def _container_running_unchecked(self) -> bool:
        return self._is_container_running(self._active_container_name())

    async def _container_running_async(self) -> bool:
        return await asyncio.to_thread(self._container_running_unchecked)

    def _docker_logs(self, since: datetime | None) -> str:
        container_name = self._active_container_name()
        args = ["logs", "--tail", "200"]
        if since is not None:
            args.extend(["--since", since.astimezone(UTC).isoformat()])
        args.extend(["--timestamps", container_name])
        return self._docker_command(args, DEFAULT_DOCKER_TIMEOUT_SECONDS)

    async def _ready_async(self) -> bool:
        assert self._refresh_start is not None
        since = self._refresh_start

        async def _logs_since(_since: datetime) -> str:
            return await asyncio.to_thread(self._docker_logs, since)

        result = await poll_boot_signals(
            timeout=self._startup_timeout_seconds,
            container_name=self._container_name,
            liveness_check=self._container_running_async,
            crash_dir=self._server_dir / "crash-reports",
            log_path=self._server_dir / "logs" / "latest.log",
            log_since=since,
            get_logs_since=_logs_since,
        )
        return result.passed


class CleanExportStageAdapter:
    """``stage_export`` port that keeps clean export off the event loop."""

    def __init__(
        self,
        layout: HostStateLayout,
        *,
        server_id: str,
        server_root: str | Path,
        lockfile: LockfileV21 | None,
        loop: asyncio.AbstractEventLoop,
        export_service: CleanExportService | None = None,
        panel_properties: Mapping[str, str] | None = None,
        jvm_args: str | None = None,
        lec_root: str | Path | None = None,
    ) -> None:
        self._layout = layout
        self._server_id = server_id
        self._server_root = Path(server_root)
        self._lockfile = lockfile
        self._loop = loop
        self._loop_thread_id = threading.get_ident()
        self._service = export_service or CleanExportService(layout)
        self._panel_properties = (
            dict(panel_properties) if panel_properties is not None else None
        )
        self._jvm_args = jvm_args
        self._lec_root = Path(lec_root) if lec_root is not None else None

    async def __call__(
        self,
        staging: Path,
        commit_sha: str,
        *,
        export_id: str,
        fencing_verifier: Callable[[], None],
    ) -> CleanExportResult:
        return await asyncio.to_thread(
            self._stage_sync,
            Path(staging),
            commit_sha,
            export_id,
            fencing_verifier,
        )

    def assert_no_unresolved_secrets(
        self,
        server_id: str,
        server_root: str | Path,
        commit_sha: str,
    ) -> None:
        """M-5: fail before quiesce when the committed tree has placeholders."""
        _assert_off_loop(self._loop_thread_id, "CleanExportStageAdapter")
        self._service.assert_no_unresolved_secrets(
            server_id, server_root, commit_sha
        )

    def _stage_sync(
        self,
        staging: Path,
        commit_sha: str,
        export_id: str,
        fencing_verifier: Callable[[], None],
    ) -> CleanExportResult:
        _assert_off_loop(self._loop_thread_id, "CleanExportStageAdapter")
        if self._lockfile is None:
            raise ValidationError(
                "Clean export requires an authoritative server lockfile",
                field="lockfile",
            )
        panel_properties = self._panel_properties
        if panel_properties is None:
            panel_properties = _read_panel_properties(self._server_root)
        jvm_args = self._jvm_args
        if jvm_args is None:
            jvm_args = _read_jvm_args(self._server_root)
        lec_root = self._lec_root
        if lec_root is None and self._lockfile.lec is not None:
            lec_root = self._layout.lec / self._lockfile.lec.key
        request = CleanExportRequest(
            server_id=self._server_id,
            server_root=self._server_root,
            commit_sha=commit_sha,
            destination=staging,
            lockfile=self._lockfile,
            panel_properties=panel_properties,
            jvm_args=jvm_args,
            secrets={},
            lec_root=lec_root,
            export_id=export_id,
        )
        return self._service.export(request, fencing_verifier=fencing_verifier)


def _read_panel_properties(server_root: Path) -> dict[str, str]:
    """Return only Class-D panel-owned keys from ``server.properties``."""
    path = server_root / "server.properties"
    if path.is_symlink():
        raise ValidationError("server.properties must not be a symlink", field="path")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ValidationError(
            f"Unable to read server.properties: {exc}", field="path"
        ) from exc
    props: dict[str, str] = {}
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line or line.startswith(("#", "!")):
            continue
        if "=" not in line:
            raise ValidationError(
                "server.properties contains a line that is not key=value",
                field="path",
            )
        key, value = line.split("=", 1)
        key = key.strip()
        if key in CLASS_D_PANEL_KEYS or key.startswith("management-server-"):
            props[key] = value.strip()
    return props


def _read_jvm_args(server_root: Path) -> str:
    path = server_root / "user_jvm_args.txt"
    if path.is_symlink():
        raise ValidationError("user_jvm_args.txt must not be a symlink", field="path")
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except OSError as exc:
        raise ValidationError(
            f"Unable to read user_jvm_args.txt: {exc}", field="path"
        ) from exc


def _default_docker_command(args: list[str], timeout: float) -> str:
    completed = subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"docker {' '.join(args[:2])} failed: "
            f"{(completed.stderr or completed.stdout).strip()[:256]}"
        )
    return completed.stdout


__all__ = [
    "CleanExportStageAdapter",
    "DockerServerRuntimeAdapter",
    "require_docker_provider",
]
