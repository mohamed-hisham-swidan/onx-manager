"""P2-6a2 runtime/export adapters, Option B routing, and fail-closed guards."""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.core.command_bus import CommandResult
from app.core.config import AppSettings
from app.core.exceptions import (
    ConflictError,
    ServerModeVersioningDisabledError,
    ValidationError,
)
from app.core.host_state import ensure_host_state_layout
from app.modules.server.application.commands.start_server import StartServerCommand
from app.modules.server.application.commands.stop_server import StopServerCommand
from app.modules.versioning.application.refresh_orchestrator import (
    STEP_READINESS,
    HealthGateEvaluator,
    LiveRefreshService,
)
from app.modules.versioning.domain.lockfile import (
    LecRef,
    LoaderRef,
    LockfileV21,
)
from app.modules.versioning.infrastructure.clean_export import CleanExportResult
from app.modules.versioning.infrastructure.runtime_adapters import (
    CleanExportStageAdapter,
    DockerServerRuntimeAdapter,
    require_docker_provider,
)

SERVER_ID = "srv-adapters"
LEC_KEY = "paper/1.20.4/499"
TARGET_SHA = "b" * 40


def _layout(tmp_path: Path):
    return ensure_host_state_layout(
        AppSettings(
            host_state_dir=str(tmp_path / "host-state"),
            servers_data_dir=str(tmp_path / "servers"),
        )
    )


def _lockfile() -> LockfileV21:
    return LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="paper", version="499"),
        base_overrides={},
        files=(),
        lec=LecRef(key=LEC_KEY),
    )


class _FakeRepo:
    def __init__(self, dialect: str) -> None:
        self.dialect_name = dialect


def test_require_docker_provider_fails_closed() -> None:
    with pytest.raises(ServerModeVersioningDisabledError, match="Docker"):
        require_docker_provider("podman")
    assert require_docker_provider("docker") == "docker"


def test_docker_runtime_adapter_rejects_non_docker_provider(tmp_path: Path) -> None:
    async def run() -> None:
        with pytest.raises(ServerModeVersioningDisabledError, match="Docker"):
            DockerServerRuntimeAdapter(
                server_id=SERVER_ID,
                loop=asyncio.get_running_loop(),
                start_handler=cast(Any, None),
                stop_handler=cast(Any, None),
                server_dir=tmp_path,
                startup_timeout_seconds=30,
                provider_name="podman",
            )

    asyncio.run(run())


def test_live_refresh_rejects_non_sqlite_dialect(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    with pytest.raises(ServerModeVersioningDisabledError, match="SQLite"):
        LiveRefreshService(
            layout,
            repository=cast(Any, _FakeRepo("postgresql")),
            repo_lease=cast(Any, object()),
        )


def test_live_refresh_accepts_sqlite_and_uses_runtime_timeout(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    runtime = SimpleNamespace(
        startup_timeout_seconds=77,
        process_alive=lambda: True,
        boot_log=lambda: "",
        ready=lambda: True,
    )
    service = LiveRefreshService(
        layout,
        repository=cast(Any, _FakeRepo("sqlite")),
        runtime=cast(Any, runtime),
        repo_lease=cast(Any, object()),
    )

    evaluator = service._evaluator(cast(Any, runtime))

    assert evaluator.timeout == 77.0


@pytest.mark.asyncio
async def test_docker_runtime_adapter_routes_start_and_stop_through_handlers() -> None:
    start_commands: list[StartServerCommand] = []
    stop_commands: list[StopServerCommand] = []

    async def start_handler(command: StartServerCommand) -> CommandResult:
        start_commands.append(command)
        return CommandResult(success=True)

    async def stop_handler(command: StopServerCommand) -> CommandResult:
        stop_commands.append(command)
        return CommandResult(success=True, data={"stop_confirmed": True})

    adapter = DockerServerRuntimeAdapter(
        server_id=SERVER_ID,
        loop=asyncio.get_running_loop(),
        start_handler=start_handler,
        stop_handler=stop_handler,
        server_dir=Path("/tmp"),
        startup_timeout_seconds=30,
        provider_name="docker",
    )
    adapter.mark_refresh_start(datetime.now(UTC))
    adapter.prepare_start("journal-own")

    assert await asyncio.to_thread(adapter.start) is True
    assert await asyncio.to_thread(adapter.stop) is True

    assert adapter.refresh_start is not None
    assert start_commands[0].server_id == SERVER_ID
    assert start_commands[0].allow_journal_id == "journal-own"
    assert stop_commands[0].server_id == SERVER_ID


@pytest.mark.asyncio
async def test_docker_runtime_adapter_start_failure_raises_conflict() -> None:
    async def start_handler(_command: StartServerCommand) -> CommandResult:
        return CommandResult(success=False, error="boom")

    async def stop_handler(_command: StopServerCommand) -> CommandResult:
        return CommandResult(success=True)

    adapter = DockerServerRuntimeAdapter(
        server_id=SERVER_ID,
        loop=asyncio.get_running_loop(),
        start_handler=start_handler,
        stop_handler=stop_handler,
        server_dir=Path("/tmp"),
        startup_timeout_seconds=30,
        provider_name="docker",
    )
    adapter.prepare_start("journal-own")

    with pytest.raises(ConflictError, match="boom"):
        await asyncio.to_thread(adapter.start)


class _RecordingExportService:
    def __init__(self) -> None:
        self.requests = []
        self.thread_ids: list[int] = []

    def export(self, request: Any, *, fencing_verifier: Any = None) -> CleanExportResult:
        self.requests.append(request)
        self.thread_ids.append(threading.get_ident())
        if fencing_verifier is not None:
            fencing_verifier()
        destination = Path(request.destination)
        return CleanExportResult(
            root=destination,
            marker_path=destination / ".onx-complete.json",
            file_count=0,
            total_bytes=0,
            export_id=request.export_id,
        )


@pytest.mark.asyncio
async def test_clean_export_adapter_runs_off_loop_and_forwards_request(
    tmp_path: Path,
) -> None:
    layout = _layout(tmp_path)
    service = _RecordingExportService()
    adapter = CleanExportStageAdapter(
        layout,
        server_id=SERVER_ID,
        server_root=tmp_path,
        lockfile=_lockfile(),
        loop=asyncio.get_running_loop(),
        export_service=cast(Any, service),
        panel_properties={"rcon.password": "secret"},
        jvm_args="-Xmx2G",
        lec_root=tmp_path / "lec",
    )
    fencing_calls: list[str] = []
    loop_thread = threading.get_ident()

    result = await adapter(
        tmp_path / "staging",
        TARGET_SHA,
        export_id="exp-adapter",
        fencing_verifier=lambda: fencing_calls.append("checked"),
    )

    assert result.export_id == "exp-adapter"
    assert service.thread_ids[0] != loop_thread
    assert fencing_calls == ["checked"]
    request = service.requests[0]
    assert request.export_id == "exp-adapter"
    assert request.secrets == {}
    assert request.panel_properties == {"rcon.password": "secret"}
    assert request.jvm_args == "-Xmx2G"
    assert Path(request.lec_root) == tmp_path / "lec"


@pytest.mark.asyncio
async def test_clean_export_adapter_requires_authoritative_lockfile(
    tmp_path: Path,
) -> None:
    layout = _layout(tmp_path)
    adapter = CleanExportStageAdapter(
        layout,
        server_id=SERVER_ID,
        server_root=tmp_path,
        lockfile=None,
        loop=asyncio.get_running_loop(),
        export_service=cast(Any, _RecordingExportService()),
    )

    with pytest.raises(ValidationError, match="lockfile"):
        await adapter(
            tmp_path / "staging",
            TARGET_SHA,
            export_id="exp-adapter",
            fencing_verifier=lambda: None,
        )


@pytest.mark.asyncio
async def test_health_gate_timeout_bounds_readiness() -> None:
    def slow_ready() -> bool:
        import time

        time.sleep(0.2)
        return True

    result = await HealthGateEvaluator(
        process_alive=lambda: True,
        ready=slow_ready,
        timeout=0.01,
    ).evaluate()

    assert result.passed is False
    assert result.failed_step == STEP_READINESS
