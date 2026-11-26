from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.identity import IDENTITY
from app.modules.server.application.services.filesystem_reconciliation import (
    ActionType,
    FilesystemReconciliationService,
    PlanAction,
    ReconciliationResult,
    ScanCategory,
    ScanOutcome,
)
from app.modules.server.domain.aggregate import Server, ServerStatus
from app.modules.server.domain.value_objects import (
    JavaArguments,
    LocationType,
    MemoryAllocation,
    PortNumber,
    RuntimeInfo,
    ServerDeployment,
    ServerProperties,
    ServerType,
)
from app.modules.shared.value_objects import MinecraftVersion, ServerId


def _create_server(
    sid: str,
    name: str,
    root_path: Path,
    missing_since: datetime | None = None,
) -> Server:
    server = Server.create(
        server_id=ServerId(sid),
        name=name,
        server_type=ServerType.PAPER,
        minecraft_version=MinecraftVersion.parse("1.21"),
        memory=MemoryAllocation(1024, 2048),
        java_args=JavaArguments(),
        properties=ServerProperties(port=PortNumber(25565)),
        deployment=ServerDeployment(
            location_type=LocationType.LOCAL,
            root_path=str(root_path.resolve()),
            working_directory=".",
            startup_jar="server.jar",
        ),
        runtime=RuntimeInfo(provider="local"),
    )
    server._status = ServerStatus.STOPPED
    if missing_since is not None:
        server._missing_since = missing_since
    server.collect_events()
    return server


def _populate_mc_dir(server_dir: Path) -> None:
    server_dir.mkdir(parents=True, exist_ok=True)
    (server_dir / "server.properties").write_text("server-port=25565\n", encoding="utf-8")
    (server_dir / "eula.txt").write_text("eula=true\n", encoding="utf-8")
    (server_dir / "server.jar").write_bytes(b"PK fake server jar")


@pytest.mark.asyncio
async def test_two_consecutive_reconciliations_with_scan_error_keep_row(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "servers"
    data_dir.mkdir(parents=True, exist_ok=True)

    sid = "b1111111111111111111111111111111"
    server_dir = data_dir / "error-srv"
    server_dir.mkdir(parents=True, exist_ok=True)

    # Write identity so it matches by identity and path
    identity_dir = server_dir / IDENTITY.identity_dir_new
    identity_dir.mkdir(parents=True, exist_ok=True)
    (identity_dir / IDENTITY.identity_file).write_text(
        json.dumps({"version": 1, "uid": sid, "provider": "local"}),
        encoding="utf-8",
    )

    server = _create_server(sid, "error-srv", server_dir)

    repo = MagicMock()
    repo.list = AsyncMock(return_value=[server])
    repo.save = AsyncMock()
    repo.delete = AsyncMock()

    mock_settings = MagicMock()
    mock_settings.servers_data_dir = str(data_dir)

    service = FilesystemReconciliationService(repo=repo)

    # Mock _detect_single to simulate ScanCategory.SCAN_FAILED
    failed_scan = ScanOutcome(
        scanned=None,
        category=ScanCategory.SCAN_FAILED,
        is_minecraft=False,
        is_broken=False,
        broken_reasons=[],
        scan_error="Permission denied while reading directory",
    )

    with (
        patch(
            "app.modules.server.application.services.filesystem_reconciliation.AppSettings",
            return_value=mock_settings,
        ),
        patch.object(service, "_detect_single", return_value=failed_scan),
    ):
        # Pass 1
        res1 = await service.reconcile()
        assert res1.total_missing == 0
        assert res1.total_deleted == 0
        assert server.missing_since is None
        repo.delete.assert_not_called()

        # Pass 2
        res2 = await service.reconcile()
        assert res2.total_missing == 0
        assert res2.total_deleted == 0
        assert server.missing_since is None
        repo.delete.assert_not_called()


@pytest.mark.asyncio
async def test_healthy_server_with_missing_identity_file_is_healed_not_deleted(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "servers"
    data_dir.mkdir(parents=True, exist_ok=True)

    sid = "b2222222222222222222222222222222"
    server_dir = data_dir / "healthy-no-id"
    _populate_mc_dir(server_dir)

    server = _create_server(sid, "healthy-no-id", server_dir)

    repo = MagicMock()
    repo.list = AsyncMock(return_value=[server])
    repo.save = AsyncMock()
    repo.delete = AsyncMock()

    mock_settings = MagicMock()
    mock_settings.servers_data_dir = str(data_dir)

    service = FilesystemReconciliationService(repo=repo)

    with patch(
        "app.modules.server.application.services.filesystem_reconciliation.AppSettings",
        return_value=mock_settings,
    ):
        res = await service.reconcile()

    assert res.total_healed == 1
    assert res.total_missing == 0
    assert res.total_deleted == 0
    repo.delete.assert_not_called()

    id_file = server_dir / IDENTITY.identity_dir_new / IDENTITY.identity_file
    assert id_file.exists()
    data = json.loads(id_file.read_text(encoding="utf-8"))
    assert data["uid"] == sid


@pytest.mark.asyncio
async def test_really_removed_directory_is_marked_missing_and_then_deleted(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "servers"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Directory deliberately does NOT exist
    missing_dir = data_dir / "gone-srv"

    sid = "b333333333333333333333333333333"
    server = _create_server(sid, "gone-srv", missing_dir)

    # Need at least one dir in data_dir so scan_filesystem doesn't early-return
    dummy_dir = data_dir / "other-dir"
    dummy_dir.mkdir()

    repo = MagicMock()
    repo.list = AsyncMock(return_value=[server])
    repo.save = AsyncMock()
    repo.delete = AsyncMock()

    mock_settings = MagicMock()
    mock_settings.servers_data_dir = str(data_dir)

    service = FilesystemReconciliationService(repo=repo)

    with patch(
        "app.modules.server.application.services.filesystem_reconciliation.AppSettings",
        return_value=mock_settings,
    ):
        # Pass 1: directory missing -> marked missing
        res1 = await service.reconcile()
        assert res1.total_missing == 1
        assert res1.total_deleted == 0
        assert server.missing_since is not None
        repo.delete.assert_not_called()

        # Pass 2: directory still missing -> deleted
        res2 = await service.reconcile()
        assert res2.total_deleted == 1
        repo.delete.assert_awaited_once_with(server.id)


@pytest.mark.asyncio
async def test_delete_step_aborts_if_directory_exists_at_execution_time(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "servers"
    data_dir.mkdir(parents=True, exist_ok=True)

    existing_dir = data_dir / "reappeared-srv"
    existing_dir.mkdir(parents=True, exist_ok=True)

    sid = "b444444444444444444444444444444"
    server = _create_server(
        sid,
        "reappeared-srv",
        existing_dir,
        missing_since=datetime.now(UTC),
    )

    repo = MagicMock()
    repo.delete = AsyncMock()

    service = FilesystemReconciliationService(repo=repo)
    result = ReconciliationResult()

    pa = PlanAction(action=ActionType.DELETE, db_server=server)
    await service._handle_delete(pa, result)

    assert result.total_deleted == 0
    repo.delete.assert_not_called()


@pytest.mark.asyncio
async def test_reconcile_normalizes_relative_root_path_and_preserves_docker_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    from app.modules.server.application.services.identity_writer import write_server_identity
    from app.modules.server.domain.value_objects import LocationType, ServerDeployment

    monkeypatch.chdir(tmp_path)
    rel_data_dir = Path("data") / "servers"
    server_dir = (tmp_path / rel_data_dir / "adv-srv").resolve()
    _populate_mc_dir(server_dir)

    sid = "b555555555555555555555555555555"
    write_server_identity(server_dir, uid=sid, provider="docker")

    server = _create_server(sid, "adv-srv", server_dir)
    server.update_deployment(
        ServerDeployment(
            location_type=LocationType.DOCKER,
            root_path="data/servers/adv-srv",
            working_directory=".",
            startup_jar="server.jar",
        )
    )

    repo = MagicMock()
    repo.list = AsyncMock(return_value=[server])
    repo.save = AsyncMock()
    repo.delete = AsyncMock()

    mock_settings = MagicMock()
    mock_settings.servers_data_dir = str(rel_data_dir)

    service = FilesystemReconciliationService(repo=repo)
    with patch(
        "app.modules.server.application.services.filesystem_reconciliation.AppSettings",
        return_value=mock_settings,
    ):
        await service.reconcile()

    repo.save.assert_awaited()
    assert server.deployment is not None
    assert os.path.isabs(server.deployment.root_path)
    assert server.deployment.root_path == str(server_dir)
    assert server.deployment.location_type == LocationType.DOCKER
