import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.server.application.reconciliation import (
    cleanup_orphan_directory,
    reconcile_filesystem,
    reconcile_servers,
)
from app.modules.server.application.services.jar_service import server_dir_name
from app.modules.server.domain.aggregate import Server, ServerStatus
from app.modules.server.domain.value_objects import (
    JavaArguments,
    LocationType,
    MemoryAllocation,
    PortNumber,
    ServerDeployment,
    ServerProperties,
    ServerType,
)
from app.modules.server.infrastructure.providers.base import (
    ServerRuntimeStatus,
)
from app.modules.shared.value_objects import MinecraftVersion, ServerId


def _make_server(sid: str, status: ServerStatus, name: str | None = None) -> Server:
    server_name = name or f"Server-{sid}"
    s = Server.create(
        server_id=ServerId(sid),
        name=server_name,
        server_type=ServerType.VANILLA,
        minecraft_version=MinecraftVersion.parse("1.21"),
        memory=MemoryAllocation(1024, 2048),
        java_args=JavaArguments(),
        properties=ServerProperties(port=PortNumber(25565)),
    )
    s.collect_events()
    if status == ServerStatus.STARTING:
        s.start()
        s._runtime.external_id = "onx-s1"
        s.collect_events()
    elif status == ServerStatus.RUNNING:
        s.start()
        s.mark_running(pid=100, port=25565, external_id="onx-s1")
        s.collect_events()
    elif status == ServerStatus.STOPPING:
        s.start()
        s.mark_running(pid=100, port=25565, external_id="onx-s1")
        s.stop()
        s.collect_events()
    elif status == ServerStatus.STOPPED:
        s.start()
        s.mark_running(pid=100, port=25565)
        s.stop()
        s.mark_stopped()
        s.collect_events()
    elif status == ServerStatus.CRASHED:
        s.start()
        s.mark_running(pid=100, port=25565)
        s.crash(exit_code=1)
        s.collect_events()
    elif status == ServerStatus.PROVISIONING:
        s.begin_provisioning()
        s.collect_events()
    return s


@pytest.mark.asyncio
class TestReconciliation:
    async def test_no_stale_servers(self):
        servers = [
            _make_server("s1", ServerStatus.STOPPED),
            _make_server("s2", ServerStatus.CREATED),
        ]
        repo = MagicMock()
        repo.list = AsyncMock(return_value=servers)
        repo.save = AsyncMock()

        results = await reconcile_servers(repo)

        assert results == []
        repo.save.assert_not_called()

    async def test_running_server_confirmed(self):
        server = _make_server("s1", ServerStatus.RUNNING)
        repo = MagicMock()
        repo.list = AsyncMock(return_value=[server])
        repo.save = AsyncMock()

        with patch(
            "app.modules.server.application.reconciliation.provider_factory.get",
            return_value=MagicMock(status=AsyncMock(return_value=ServerRuntimeStatus.RUNNING)),
        ):
            results = await reconcile_servers(repo)

        assert len(results) == 1
        assert results[0]["action"] == "confirmed"
        assert results[0]["new_status"] == "running"
        repo.save.assert_not_called()

    async def test_running_server_marked_crashed(self):
        server = _make_server("s1", ServerStatus.RUNNING)
        repo = MagicMock()
        repo.list = AsyncMock(return_value=[server])
        repo.save = AsyncMock()

        with patch(
            "app.modules.server.application.reconciliation.provider_factory.get",
            return_value=MagicMock(status=AsyncMock(return_value=ServerRuntimeStatus.STOPPED)),
        ):
            results = await reconcile_servers(repo)

        assert len(results) == 1
        assert results[0]["action"] == "repaired"
        assert results[0]["new_status"] == "crashed"
        repo.save.assert_called_once()

    async def test_starting_server_marked_crashed(self):
        server = _make_server("s1", ServerStatus.STARTING)
        repo = MagicMock()
        repo.list = AsyncMock(return_value=[server])
        repo.save = AsyncMock()

        with patch(
            "app.modules.server.application.reconciliation.provider_factory.get",
            return_value=MagicMock(status=AsyncMock(return_value=ServerRuntimeStatus.ERROR)),
        ):
            results = await reconcile_servers(repo)

        assert len(results) == 1
        assert results[0]["action"] == "repaired"
        assert results[0]["new_status"] == "crashed"

    async def test_stopping_server_marked_stopped(self):
        server = _make_server("s1", ServerStatus.STOPPING)
        repo = MagicMock()
        repo.list = AsyncMock(return_value=[server])
        repo.save = AsyncMock()

        with patch(
            "app.modules.server.application.reconciliation.provider_factory.get",
            return_value=MagicMock(),
        ):
            results = await reconcile_servers(repo)

        assert len(results) == 1
        assert results[0]["action"] == "repaired"
        assert results[0]["new_status"] == "stopped"

    async def test_provisioning_server_marked_broken_when_stale(self):
        server = _make_server("s1", ServerStatus.PROVISIONING)
        server._deployment = ServerDeployment(
            location_type=LocationType.LOCAL,
            root_path="/tmp/srv-provisioning-stale",
            working_directory=".",
            startup_jar="server.jar",
        )
        repo = MagicMock()
        repo.list = AsyncMock(return_value=[server])
        repo.save = AsyncMock()

        with patch(
            "app.modules.server.application.reconciliation.local_fs.delete_dir"
        ) as mock_delete:
            results = await reconcile_servers(repo)

        assert server.status == ServerStatus.BROKEN
        assert len(results) == 1
        assert results[0]["action"] == "repaired"
        assert results[0]["new_status"] == "broken"
        assert results[0]["reason"] == "stale PROVISIONING state — backend restarted mid-install"
        mock_delete.assert_called_once_with(server.deployment.server_directory())
        repo.save.assert_called_once()

    async def test_crashed_server_recovered_when_running(self):
        server = _make_server("s1", ServerStatus.CRASHED)
        server._runtime.external_id = "onx-s1"
        repo = MagicMock()
        repo.list = AsyncMock(return_value=[server])
        repo.save = AsyncMock()

        with patch(
            "app.modules.server.application.reconciliation.provider_factory.get",
            return_value=MagicMock(status=AsyncMock(return_value=ServerRuntimeStatus.RUNNING)),
        ):
            results = await reconcile_servers(repo)

        assert len(results) == 1
        assert results[0]["action"] == "recovered"
        assert results[0]["new_status"] == "running"
        repo.save.assert_called_once()


@pytest.mark.asyncio
class TestReconcileFilesystem:
    async def test_no_orphans(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "data/servers")
            os.makedirs(data_dir, exist_ok=True)

            os.makedirs(os.path.join(data_dir, "server-1"), exist_ok=True)
            os.makedirs(os.path.join(data_dir, "server-2"), exist_ok=True)

            repo = MagicMock()
            repo.list = AsyncMock(
                return_value=[
                    _make_server("server-1", ServerStatus.STOPPED),
                    _make_server("server-2", ServerStatus.STOPPED),
                ]
            )

            with patch(
                "app.modules.server.application.reconciliation.SERVERS_DATA_DIR",
                data_dir,
            ):
                results = await reconcile_filesystem(repo)

            assert results == []

    async def test_orphan_directories_detected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "data/servers")
            os.makedirs(data_dir, exist_ok=True)

            os.makedirs(os.path.join(data_dir, "db-server-1"), exist_ok=True)
            os.makedirs(os.path.join(data_dir, "orphan-1"), exist_ok=True)
            os.makedirs(os.path.join(data_dir, "orphan-2"), exist_ok=True)

            repo = MagicMock()
            repo.list = AsyncMock(
                return_value=[
                    _make_server("db-server-1", ServerStatus.STOPPED),
                ]
            )

            with patch(
                "app.modules.server.application.reconciliation.SERVERS_DATA_DIR",
                data_dir,
            ):
                results = await reconcile_filesystem(repo)

            assert len(results) == 2
            orphan_ids = {r["server_id"] for r in results}
            assert orphan_ids == {"orphan-1", "orphan-2"}
            assert all(r["action"] == "pending" for r in results)

    async def test_non_uuid_dirs_ignored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "data/servers")
            os.makedirs(data_dir, exist_ok=True)

            os.makedirs(os.path.join(data_dir, "orphan-uuid"), exist_ok=True)
            with open(os.path.join(data_dir, "not-a-dir.txt"), "w") as f:
                f.write("file")

            repo = MagicMock()
            repo.list = AsyncMock(return_value=[])

            with patch(
                "app.modules.server.application.reconciliation.SERVERS_DATA_DIR",
                data_dir,
            ):
                results = await reconcile_filesystem(repo)

            assert len(results) == 1
            assert results[0]["server_id"] == "orphan-uuid"

    async def test_slug_uuid_dirs_not_orphaned(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "data/servers")
            os.makedirs(data_dir, exist_ok=True)

            sid = "be193e92e2aa4728a0854cad9e37cca1"
            name = "OneBlock Reborn"
            server = _make_server(sid, ServerStatus.STOPPED, name=name)
            slug_uuid_dir = server_dir_name(name, sid)
            os.makedirs(os.path.join(data_dir, slug_uuid_dir), exist_ok=True)

            repo = MagicMock()
            repo.list = AsyncMock(return_value=[server])

            with patch(
                "app.modules.server.application.reconciliation.SERVERS_DATA_DIR",
                data_dir,
            ):
                results = await reconcile_filesystem(repo)

            assert results == [], (
                f"slug+uuid dir '{slug_uuid_dir}' falsely flagged as orphan: {results}"
            )

    async def test_slug_uuid_orphan_still_detected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "data/servers")
            os.makedirs(data_dir, exist_ok=True)

            os.makedirs(os.path.join(data_dir, "no-match-aaaaaaaa"), exist_ok=True)

            repo = MagicMock()
            repo.list = AsyncMock(
                return_value=[
                    _make_server(
                        "be193e92e2aa4728a0854cad9e37cca1", ServerStatus.STOPPED, name="RealServer"
                    ),
                ]
            )

            with patch(
                "app.modules.server.application.reconciliation.SERVERS_DATA_DIR",
                data_dir,
            ):
                results = await reconcile_filesystem(repo)

            assert len(results) == 1
            assert results[0]["server_id"] == "no-match-aaaaaaaa"

    async def test_raw_uuid_dir_matched(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "data/servers")
            os.makedirs(data_dir, exist_ok=True)

            sid = "be193e92e2aa4728a0854cad9e37cca1"
            server = _make_server(sid, ServerStatus.STOPPED, name="AnyName")
            os.makedirs(os.path.join(data_dir, sid), exist_ok=True)

            repo = MagicMock()
            repo.list = AsyncMock(return_value=[server])

            with patch(
                "app.modules.server.application.reconciliation.SERVERS_DATA_DIR",
                data_dir,
            ):
                results = await reconcile_filesystem(repo)

            assert results == [], f"raw UUID dir '{sid}' falsely flagged as orphan"

    async def test_data_dir_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "does-not-exist")

            repo = MagicMock()
            repo.list = AsyncMock(return_value=[])

            with patch(
                "app.modules.server.application.reconciliation.SERVERS_DATA_DIR",
                data_dir,
            ):
                results = await reconcile_filesystem(repo)

            assert results == []

    async def test_cleanup_orphan_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            orphan_dir = os.path.join(tmpdir, "orphan-server")
            os.makedirs(orphan_dir, exist_ok=True)
            orphan_file = os.path.join(orphan_dir, "some-file.txt")
            with open(orphan_file, "w") as f:
                f.write("data")

            with patch(
                "app.modules.server.application.reconciliation.local_fs.delete_dir"
            ) as mock_delete:
                result = await cleanup_orphan_directory(orphan_dir)

            assert result["action"] == "deleted"
            assert result["success"] is True
            mock_delete.assert_called_once_with(orphan_dir)


class TestFilesystemReconciliationNameDrift:
    @pytest.mark.asyncio
    async def test_reconciliation_syncs_drifted_server_name(self, tmp_path) -> None:
        from app.modules.server.application.services.filesystem_reconciliation import (
            FilesystemReconciliationService,
        )

        data_dir = tmp_path / "servers"
        data_dir.mkdir(parents=True, exist_ok=True)

        sid = "c82221ba2c9c49d3a4c7068a6f053944"
        server_dir = data_dir / sid
        server_dir.mkdir(parents=True, exist_ok=True)
        (server_dir / "server.properties").write_text(
            "server-name=Drifted Disk Name\nserver-port=25565\n", encoding="utf-8"
        )
        (server_dir / "eula.txt").write_text("eula=true\n", encoding="utf-8")
        (server_dir / "server.jar").write_bytes(b"fake jar content")

        identity_dir = server_dir / ".mcsmanager"
        identity_dir.mkdir(parents=True, exist_ok=True)
        (identity_dir / "server.json").write_text(
            f'{{"version": 1, "uid": "{sid}", "created_at": "2026-08-19T00:00:00Z", "manager": "mcs", "schema_version": 1}}',
            encoding="utf-8",
        )

        server = _make_server(sid, ServerStatus.CREATED, name="Old Database Name")
        server._deployment = ServerDeployment(
            location_type=LocationType.LOCAL,
            root_path=str(server_dir),
            working_directory=".",
            startup_jar="server.jar",
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
            result = await service.reconcile()

        assert result.total_updated == 1
        assert server.name == "Drifted Disk Name"
        repo.save.assert_awaited_once_with(server)

    @pytest.mark.asyncio
    async def test_reconciliation_preserves_db_name_when_no_server_name_declared(
        self, tmp_path
    ) -> None:
        from app.modules.server.application.services.filesystem_reconciliation import (
            FilesystemReconciliationService,
        )

        data_dir = tmp_path / "servers"
        data_dir.mkdir(parents=True, exist_ok=True)

        sid = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
        server_dir = data_dir / sid
        server_dir.mkdir(parents=True, exist_ok=True)
        # File has NO server-name property (legacy / name-less server)
        (server_dir / "server.properties").write_text(
            "server-port=25565\nmotd=A Minecraft Server\n", encoding="utf-8"
        )
        (server_dir / "eula.txt").write_text("eula=true\n", encoding="utf-8")
        (server_dir / "server.jar").write_bytes(b"fake jar content")

        identity_dir = server_dir / ".mcsmanager"
        identity_dir.mkdir(parents=True, exist_ok=True)
        (identity_dir / "server.json").write_text(
            f'{{"version": 1, "uid": "{sid}", "created_at": "2026-08-19T00:00:00Z", "manager": "mcs", "schema_version": 1}}',
            encoding="utf-8",
        )

        server = _make_server(sid, ServerStatus.CREATED, name="Custom DB Server Name")
        server._deployment = ServerDeployment(
            location_type=LocationType.LOCAL,
            root_path=str(server_dir),
            working_directory=".",
            startup_jar="server.jar",
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
            result = await service.reconcile()

        assert result.total_updated == 0
        assert result.total_unchanged == 1
        assert server.name == "Custom DB Server Name"
        repo.save.assert_not_called()
