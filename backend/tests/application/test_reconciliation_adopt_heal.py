from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.identity import IDENTITY
from app.modules.server.application.services.filesystem_reconciliation import (
    FilesystemReconciliationService,
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


def _create_server_entity(
    sid: str,
    name: str,
    root_path: Path,
    provider: str = "docker",
    status: ServerStatus = ServerStatus.STOPPED,
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
            location_type=LocationType.DOCKER if provider == "docker" else LocationType.LOCAL,
            root_path=str(root_path.resolve()),
            working_directory=".",
            startup_jar="server.jar",
        ),
        runtime=RuntimeInfo(provider=provider),
    )
    server._status = status
    if status == ServerStatus.RUNNING:
        server._runtime = RuntimeInfo(
            provider=provider, pid=1234, port=25565, external_id=f"onx-{sid}"
        )
    elif status == ServerStatus.STOPPED:
        server._runtime = RuntimeInfo(provider=provider, external_id=f"onx-{sid}")

    if missing_since is not None:
        server._missing_since = missing_since

    server.collect_events()
    return server


def _populate_mc_dir(server_dir: Path, with_jar: bool = True) -> None:
    server_dir.mkdir(parents=True, exist_ok=True)
    (server_dir / "server.properties").write_text("server-port=25565\n", encoding="utf-8")
    (server_dir / "eula.txt").write_text("eula=true\n", encoding="utf-8")
    if with_jar:
        (server_dir / "server.jar").write_bytes(b"PK fake server jar")


class TestReconciliationAdoptHeal:
    @pytest.mark.asyncio
    async def test_missing_identity_with_matching_db_row_heals_without_duplicate(
        self, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "servers"
        data_dir.mkdir(parents=True, exist_ok=True)

        sid = "a1111111111111111111111111111111"
        server_dir = data_dir / "test-docker-server"
        _populate_mc_dir(server_dir)

        # No identity file exists on disk (simulating bug 3 scenario)
        identity_file = server_dir / IDENTITY.identity_dir_new / IDENTITY.identity_file
        assert not identity_file.exists()

        server = _create_server_entity(
            sid=sid,
            name="test-docker-server",
            root_path=server_dir,
            provider="docker",
            status=ServerStatus.STOPPED,
        )

        repo = MagicMock()
        repo.list = AsyncMock(return_value=[server])
        repo.save = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.servers_data_dir = str(data_dir)

        service = FilesystemReconciliationService(repo=repo)
        with patch(
            "app.modules.server.application.services.filesystem_reconciliation.AppSettings",
            return_value=mock_settings,
        ):
            res = await service.reconcile()

        # Must have healed 1 identity, 0 imported, 0 deleted, 0 missing
        assert res.total_healed == 1
        assert res.total_imported == 0
        assert res.total_deleted == 0
        assert res.total_missing == 0

        # Identity file must now exist and record provider="docker" and original UUID
        assert identity_file.exists()
        doc = json.loads(identity_file.read_text(encoding="utf-8"))
        assert doc["server_id"] == sid
        assert doc["uid"] == sid
        assert doc["provider"] == "docker"

        # Server DB entity must still have original ID and provider
        assert str(server.id) == sid
        assert server.runtime.provider == "docker"
        # Since server was not missing or broken, no DB update was required
        repo.save.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_identity_with_no_matching_db_row_imports_as_new(
        self, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "servers"
        data_dir.mkdir(parents=True, exist_ok=True)

        server_dir = data_dir / "unmanaged-server"
        _populate_mc_dir(server_dir)

        repo = MagicMock()
        repo.list = AsyncMock(return_value=[])  # Empty DB
        repo.save = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.servers_data_dir = str(data_dir)

        service = FilesystemReconciliationService(repo=repo)
        with patch(
            "app.modules.server.application.services.filesystem_reconciliation.AppSettings",
            return_value=mock_settings,
        ):
            res = await service.reconcile()

        # Must have imported 1 new server, 0 healed
        assert res.total_imported == 1
        assert res.total_healed == 0

        identity_file = server_dir / IDENTITY.identity_dir_new / IDENTITY.identity_file
        assert identity_file.exists()
        doc = json.loads(identity_file.read_text(encoding="utf-8"))
        # An unmanaged server imported by reconciliation gets a newly minted UUID
        assert len(doc["server_id"]) == 32
        repo.save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_duplicate_db_rows_for_same_root_path_resolves_deterministically(
        self, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "servers"
        data_dir.mkdir(parents=True, exist_ok=True)

        server_dir = data_dir / "conflicting-server"
        _populate_mc_dir(server_dir)

        active_sid = "22222222222222222222222222222222"
        stale_sid = "33333333333333333333333333333333"

        # Active server row (running, provider docker, not missing)
        active_server = _create_server_entity(
            sid=active_sid,
            name="Conflicting Server Active",
            root_path=server_dir,
            provider="docker",
            status=ServerStatus.RUNNING,
        )

        # Stale server row (stopped, lower priority)
        stale_server = _create_server_entity(
            sid=stale_sid,
            name="Conflicting Server Stale",
            root_path=server_dir,
            provider="local",
            status=ServerStatus.STOPPED,
            missing_since=None,
        )

        repo = MagicMock()
        repo.list = AsyncMock(return_value=[stale_server, active_server])
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

        # Active server must be healed and adopted
        assert res.total_healed == 1
        assert res.identity_healed[0]["server_id"] == active_sid

        # Stale server must remain missing / not adopted
        assert res.total_missing == 1
        assert res.missing[0]["server_id"] == stale_sid

        # Identity stamped on disk must correspond to active_sid with provider=docker
        identity_file = server_dir / IDENTITY.identity_dir_new / IDENTITY.identity_file
        doc = json.loads(identity_file.read_text(encoding="utf-8"))
        assert doc["server_id"] == active_sid
        assert doc["provider"] == "docker"

    @pytest.mark.asyncio
    async def test_corrupted_identity_with_matching_db_row_heals_with_original_uuid(
        self, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "servers"
        data_dir.mkdir(parents=True, exist_ok=True)

        sid = "44444444444444444444444444444444"
        server_dir = data_dir / "corrupted-id-server"
        _populate_mc_dir(server_dir)

        # Write corrupt JSON to identity file
        identity_dir = server_dir / IDENTITY.identity_dir_new
        identity_dir.mkdir(parents=True, exist_ok=True)
        (identity_dir / IDENTITY.identity_file).write_text("{corrupt-not-json", encoding="utf-8")

        server = _create_server_entity(
            sid=sid,
            name="Corrupted Id Server",
            root_path=server_dir,
            provider="docker",
            status=ServerStatus.STOPPED,
        )

        repo = MagicMock()
        repo.list = AsyncMock(return_value=[server])
        repo.save = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.servers_data_dir = str(data_dir)

        service = FilesystemReconciliationService(repo=repo)
        with patch(
            "app.modules.server.application.services.filesystem_reconciliation.AppSettings",
            return_value=mock_settings,
        ):
            res = await service.reconcile()

        # Must be planned and executed as HEAL_IDENTITY, not imported with a foreign UUID
        assert res.total_healed == 1
        assert res.total_imported == 0

        doc = json.loads((identity_dir / IDENTITY.identity_file).read_text(encoding="utf-8"))
        assert doc["server_id"] == sid
        assert doc["provider"] == "docker"

    @pytest.mark.asyncio
    async def test_pre_fix_damaged_server_missing_since_cleared_on_heal(
        self, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "servers"
        data_dir.mkdir(parents=True, exist_ok=True)

        sid = "55555555555555555555555555555555"
        server_dir = data_dir / "damaged-server"
        _populate_mc_dir(server_dir)

        # Previously marked MISSING before the bug was fixed
        server = _create_server_entity(
            sid=sid,
            name="Damaged Server",
            root_path=server_dir,
            provider="docker",
            status=ServerStatus.STOPPED,
            missing_since=datetime.now(UTC),
        )
        assert server.missing_since is not None

        repo = MagicMock()
        repo.list = AsyncMock(return_value=[server])
        repo.save = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.servers_data_dir = str(data_dir)

        service = FilesystemReconciliationService(repo=repo)
        with patch(
            "app.modules.server.application.services.filesystem_reconciliation.AppSettings",
            return_value=mock_settings,
        ):
            res = await service.reconcile()

        assert res.total_healed == 1
        # missing_since must be cleared
        assert server.missing_since is None
        # provider preserved
        assert server.runtime.provider == "docker"
        repo.save.assert_awaited_once_with(server)
