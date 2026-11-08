from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.identity import IDENTITY
from app.modules.server.application.services.filesystem_reconciliation import (
    ActionType,
    FilesystemReconciliationService,
    PlanAction,
    ReconciliationResult,
)
from app.modules.server.domain.aggregate import Server
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
from app.modules.server.infrastructure.providers.base import ServerHandle
from app.modules.server.infrastructure.providers.docker import DockerProvider
from app.modules.shared.value_objects import MinecraftVersion, ServerId


class TestDockerContainerCleanup:
    @pytest.mark.asyncio
    async def test_docker_destroy_removes_by_name_labels_and_volume_filter(self) -> None:
        provider = DockerProvider()
        sid = "abc12345678901234567890123456789"
        container_name = f"onx-{sid}"
        server_dir = "/var/minecraft/servers/my-server"

        handle = ServerHandle(
            provider="docker",
            server_id=sid,
            external_id=container_name,
            metadata={"root_path": server_dir},
        )

        removed_targets: list[str] = []

        async def mock_docker_cmd(*args, **_kwargs):
            cmd = args[0]
            if cmd == "ps":
                # If querying by label or volume, return orphaned container IDs
                filter_arg = args[args.index("--filter") + 1]
                if f"label={IDENTITY.docker_label_prefix_new}.server_id=" in filter_arg:
                    return 0, "cid_label_new_1 cid_label_new_2\n"
                if f"label={IDENTITY.docker_label_prefix_legacy}.server_id=" in filter_arg:
                    return 0, "cid_label_leg_1\n"
                if "volume=" in filter_arg:
                    return 0, "cid_vol_1\n"
                return 0, ""
            elif cmd == "rm":
                target = args[2]
                removed_targets.append(target)
                return 0, ""
            return 0, ""

        with patch.object(provider, "_docker_command", side_effect=mock_docker_cmd) as mock_cmd:
            await provider.destroy(handle)

        # Assert that Docker CLI was queried for labels and volumes
        calls = [c[0] for c in mock_cmd.call_args_list]
        filter_queries = [
            c[args_idx + 1]
            for c in calls
            if "--filter" in c
            for args_idx in [c.index("--filter")]
        ]
        label_new = f"label={IDENTITY.docker_label_prefix_new}.server_id={sid}"
        label_legacy = f"label={IDENTITY.docker_label_prefix_legacy}.server_id={sid}"
        assert any(label_new in q for q in filter_queries)
        assert any(label_legacy in q for q in filter_queries)
        assert any("volume=" in q for q in filter_queries)

        # Assert all collected targets were removed with rm -f
        assert container_name in removed_targets
        assert f"{IDENTITY.temp_prefix_legacy}{sid}" in removed_targets
        assert "cid_label_new_1" in removed_targets
        assert "cid_label_new_2" in removed_targets
        assert "cid_label_leg_1" in removed_targets
        assert "cid_vol_1" in removed_targets

    @pytest.mark.asyncio
    async def test_docker_destroy_tolerates_daemon_unreachable(self) -> None:
        provider = DockerProvider()
        handle = ServerHandle(
            provider="docker",
            server_id="unreachable-sid",
            external_id="onx-unreachable-sid",
            metadata={"root_path": "/var/servers/foo"},
        )

        with patch.object(
            provider, "_docker_command", side_effect=FileNotFoundError("docker not found")
        ):
            # Must not raise an exception
            await provider.destroy(handle)

    @pytest.mark.asyncio
    async def test_reconciliation_handle_delete_calls_provider_destroy_with_root_path(
        self, tmp_path: Path
    ) -> None:
        sid = "del11111111111111111111111111111"
        server_dir = tmp_path / "deleted-server"
        # Root directory must not exist so reconciliation proceeds with deletion

        server = Server.create(
            server_id=ServerId(sid),
            name="To-Be-Deleted",
            server_type=ServerType.PAPER,
            minecraft_version=MinecraftVersion.parse("1.21"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25565)),
            deployment=ServerDeployment(
                location_type=LocationType.DOCKER,
                root_path=str(server_dir),
                working_directory=".",
                startup_jar="server.jar",
            ),
            runtime=RuntimeInfo(provider="docker", external_id=f"onx-{sid}"),
        )

        repo = MagicMock()
        repo.delete = AsyncMock()

        mock_provider = AsyncMock()
        mock_factory = MagicMock()
        mock_factory.get.return_value = mock_provider

        service = FilesystemReconciliationService(
            repo=repo,
            provider_factory=mock_factory,
        )

        pa = PlanAction(action=ActionType.DELETE, db_server=server)
        result = ReconciliationResult()

        with patch(
            "app.modules.server.application.supervisor.RuntimeSupervisor.stop_for",
            new_callable=AsyncMock,
        ) as mock_supervisor_stop:
            await service._handle_delete(pa, result)

        # 1. Supervisor stop was invoked
        mock_supervisor_stop.assert_awaited_once_with(sid)

        # 2. Provider factory obtained provider="docker"
        mock_factory.get.assert_called_once_with("docker")

        # 3. Provider destroy was awaited with root_path metadata
        mock_provider.destroy.assert_awaited_once()
        called_handle: ServerHandle = mock_provider.destroy.call_args[0][0]
        assert called_handle.server_id == sid
        assert called_handle.provider == "docker"
        assert called_handle.metadata["root_path"] == str(server_dir)

        # 4. Repo delete was awaited
        repo.delete.assert_awaited_once_with(server.id)
        assert len(result.deleted) == 1

    @pytest.mark.asyncio
    async def test_reconciliation_handle_delete_aborts_when_directory_still_exists(
        self, tmp_path: Path
    ) -> None:
        sid = "abort1111111111111111111111111111"
        server_dir = tmp_path / "existing-server"
        server_dir.mkdir(parents=True, exist_ok=True)

        server = Server.create(
            server_id=ServerId(sid),
            name="Still-Present",
            server_type=ServerType.PAPER,
            minecraft_version=MinecraftVersion.parse("1.21"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25565)),
            deployment=ServerDeployment(
                location_type=LocationType.DOCKER,
                root_path=str(server_dir),
                working_directory=".",
                startup_jar="server.jar",
            ),
            runtime=RuntimeInfo(provider="docker", external_id=f"onx-{sid}"),
        )

        repo = MagicMock()
        repo.delete = AsyncMock()

        mock_provider = AsyncMock()
        mock_factory = MagicMock()
        mock_factory.get.return_value = mock_provider

        service = FilesystemReconciliationService(
            repo=repo,
            provider_factory=mock_factory,
        )

        pa = PlanAction(action=ActionType.DELETE, db_server=server)
        result = ReconciliationResult()

        with patch(
            "app.modules.server.application.supervisor.RuntimeSupervisor.stop_for",
            new_callable=AsyncMock,
        ) as mock_supervisor_stop:
            await service._handle_delete(pa, result)

        mock_supervisor_stop.assert_not_called()
        mock_factory.get.assert_not_called()
        mock_provider.destroy.assert_not_called()
        repo.delete.assert_not_called()
        assert len(result.deleted) == 0
