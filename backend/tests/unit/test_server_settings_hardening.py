from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.api.v1.schemas.server import ServerUpdateRequest
from app.core.config import AppSettings
from app.core.event_bus import EventBus
from app.core.exceptions import ConflictError, InvalidValueError, ValidationError
from app.core.host_state import ensure_host_state_layout
from app.core.persistence.db import database
from app.modules.server.application.branch_settings import (
    load_branch_runtime_overrides,
    save_branch_scoped_settings,
)
from app.modules.server.application.commands.update_server_config import (
    UpdateServerConfigCommand,
    UpdateServerConfigHandler,
)
from app.modules.server.application.read_models import resolve_display_name
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.value_objects import (
    CpuAllocation,
    JavaArguments,
    LaunchConfiguration,
    LocationType,
    MemoryAllocation,
    PortNumber,
    ServerDeployment,
    ServerMode,
    ServerProperties,
    ServerType,
)
from app.modules.server.infrastructure.providers.base import ServerRuntimeStatus
from app.modules.server.infrastructure.providers.docker import DockerProvider
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import MinecraftVersion, ServerId
from app.modules.versioning.domain.lockfile import LoaderRef, LockfileV21
from app.modules.versioning.domain.port_sets import HostPortSet
from app.modules.versioning.infrastructure.branch_runtime_service import (
    BranchRuntimeService,
    BranchStartRequest,
    build_branch_docker_create_args,
)
from app.modules.versioning.infrastructure.git_branches import GitBranchService
from app.modules.versioning.infrastructure.git_repository import GitRepositoryService


def _lockfile() -> LockfileV21:
    return LockfileV21(
        format=2,
        mc="1.21.1",
        loader=LoaderRef(id="paper", version="1"),
        base_overrides={},
        files=(),
    )


async def _create_server(
    server_id: str,
    root: Path,
    *,
    name: str = "Srv",
    port: int = 25565,
    mode: ServerMode = ServerMode.SIMPLE,
) -> Server:
    root.mkdir(parents=True, exist_ok=True)
    (root / "server.properties").write_text(
        f"server-port={port}\nmotd=Hello\n", encoding="utf-8"
    )
    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        srv = Server.create(
            server_id=ServerId(server_id),
            name=name,
            server_type=ServerType.PAPER,
            minecraft_version=MinecraftVersion.parse("1.21.1"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(port)),
            deployment=ServerDeployment(
                location_type=LocationType.DOCKER,
                root_path=str(root),
                working_directory=".",
                startup_jar="server.jar",
            ),
            cpu=CpuAllocation(cores=0, affinity=""),
            mode=mode,
        )
        await repo.save(srv)
        await session.commit()
        return srv


async def _load_server(server_id: str) -> Server:
    async with database.session_factory() as session:
        srv = await SQLServerRepository(session).get(ServerId(server_id))
        assert srv is not None
        return srv


@pytest.mark.usefixtures("init_test_db")
class TestServerPortHardening:
    @pytest.mark.asyncio
    async def test_simple_mode_port_update_checks_collisions_and_syncs_deployment_port(
        self, event_bus: EventBus, tmp_path: Path
    ) -> None:
        await _create_server("srv-port-1", tmp_path / "s1", name="One", port=25565)
        await _create_server("srv-port-2", tmp_path / "s2", name="Two", port=25566)

        handler = UpdateServerConfigHandler(event_bus)

        # Colliding with srv-port-2 in SQLite raises ConflictError (409)
        with pytest.raises(ConflictError, match="already in use"):
            await handler.handle(
                UpdateServerConfigCommand(
                    server_id="srv-port-1",
                    properties={"server-port": 25566},
                )
            )

        # Colliding with live Docker published port raises ConflictError
        with (
            patch(
                "app.modules.server.application.commands.update_server_config.async_get_live_docker_published_ports",
                AsyncMock(return_value={25570}),
            ),
            pytest.raises(ConflictError, match="published by a running container"),
        ):
            await handler.handle(
                UpdateServerConfigCommand(
                    server_id="srv-port-1",
                    properties={"server-port": 25570},
                )
            )

        # Colliding with OS socket bind probe raises ConflictError
        with (
            patch(
                "app.modules.server.application.commands.update_server_config.async_get_live_docker_published_ports",
                AsyncMock(return_value=set()),
            ),
            patch(
                "app.modules.server.application.commands.update_server_config.probe_os_port_free",
                return_value=False,
            ),
            pytest.raises(ConflictError, match="already bound"),
        ):
            await handler.handle(
                UpdateServerConfigCommand(
                    server_id="srv-port-1",
                    properties={"server-port": 25571},
                )
            )

        # Clean port updates BOTH server.properties.port, runtime.port (deployment_port), and disk
        with (
            patch(
                "app.modules.server.application.commands.update_server_config.async_get_live_docker_published_ports",
                AsyncMock(return_value=set()),
            ),
            patch(
                "app.modules.server.application.commands.update_server_config.probe_os_port_free",
                return_value=True,
            ),
        ):
            res = await handler.handle(
                UpdateServerConfigCommand(
                    server_id="srv-port-1",
                    properties={"server-port": 25572, "rcon.port": "25599", "enable-rcon": "false"},
                )
            )
        assert res.success is True
        loaded = await _load_server("srv-port-1")
        assert loaded.properties.port.value == 25572
        assert loaded.runtime is not None and loaded.runtime.port == 25572
        props_text = (tmp_path / "s1" / "server.properties").read_text(encoding="utf-8")
        assert "server-port=25572" in props_text
        # Non-port Class-D keys must not be written by customProperties echo
        assert "rcon.port=25599" not in props_text
        assert "enable-rcon=false" not in props_text

    @pytest.mark.asyncio
    async def test_advanced_mode_main_persists_port_without_empty_pending_branch(
        self, event_bus: EventBus, tmp_path: Path
    ) -> None:
        servers_dir = tmp_path / "servers"
        host_state_dir = tmp_path / "host_state"
        settings = AppSettings(
            servers_data_dir=str(servers_dir),
            host_state_dir=str(host_state_dir),
        )
        layout = ensure_host_state_layout(settings)
        srv_root = servers_dir / "srv_adv"
        srv_id = "srv-adv-port-1"
        await _create_server(srv_id, srv_root, name="AdvSrv", port=25565, mode=ServerMode.ADVANCED)

        GitRepositoryService(layout).initialize(srv_id, srv_root, _lockfile())

        handler = UpdateServerConfigHandler(event_bus)
        with (
            patch(
                "app.modules.server.application.branch_settings.resolve_host_state_layout",
                return_value=layout,
            ),
            patch(
                "app.modules.server.application.commands.update_server_config.async_get_live_docker_published_ports",
                AsyncMock(return_value=set()),
            ),
            patch(
                "app.modules.server.application.commands.update_server_config.probe_os_port_free",
                return_value=True,
            ),
        ):
            res = await handler.handle(
                UpdateServerConfigCommand(
                    server_id=srv_id,
                    branch_name="main",
                    name="AdvSrvRenamed",
                    properties={"server-port": 25580},
                )
            )
        assert res.success is True
        assert "branch_name" not in res.data
        assert "pending_settings_branch" not in res.data

        loaded = await _load_server(srv_id)
        assert loaded.name == "AdvSrvRenamed"
        assert loaded.properties.port.value == 25580
        assert loaded.runtime is not None and loaded.runtime.port == 25580

        # Non-main working branch port change must be rejected
        with pytest.raises(ValidationError, match="Host game port is server-wide"):
            await handler.handle(
                UpdateServerConfigCommand(
                    server_id=srv_id,
                    branch_name="feat-branch",
                    properties={"server-port": 25581},
                )
            )


@pytest.mark.usefixtures("init_test_db")
class TestBranchRuntimeSettingsHardening:
    @pytest.mark.asyncio
    async def test_save_branch_scoped_settings_validates_domain_vos_before_commit(
        self, tmp_path: Path
    ) -> None:
        servers_dir = tmp_path / "servers"
        host_state_dir = tmp_path / "host_state"
        layout = ensure_host_state_layout(
            AppSettings(
                servers_data_dir=str(servers_dir),
                host_state_dir=str(host_state_dir),
            )
        )
        srv_root = servers_dir / "srv_branch_val"
        srv_id = "srv-br-val-1"
        srv = await _create_server(srv_id, srv_root, mode=ServerMode.ADVANCED)
        GitRepositoryService(layout).initialize(srv_id, srv_root, _lockfile())
        GitBranchService(layout).create_branch(srv_id, srv_root, "dev", start_point="main")

        async with database.session_factory() as session:
            with pytest.raises(InvalidValueError, match="Disallowed JVM flag"):
                await save_branch_scoped_settings(
                    session=session,
                    server=srv,
                    branch_name="dev",
                    java_args=["-javaagent:/tmp/evil.jar"],
                    layout=layout,
                )

            with pytest.raises(ValidationError):
                await save_branch_scoped_settings(
                    session=session,
                    server=srv,
                    branch_name="dev",
                    min_memory_mb=4096,
                    max_memory_mb=1024,
                    layout=layout,
                )

            with pytest.raises(ValidationError):
                await save_branch_scoped_settings(
                    session=session,
                    server=srv,
                    branch_name="dev",
                    cpu_affinity="bad-mask",
                    layout=layout,
                )

            saved = await save_branch_scoped_settings(
                session=session,
                server=srv,
                branch_name="dev",
                min_memory_mb=1536,
                max_memory_mb=3072,
                cpu_cores=3,
                cpu_affinity="0-2",
                java_args=["-XX:+UseG1GC", "-XX:MaxGCPauseMillis=100"],
                layout=layout,
            )
            await session.commit()

        assert saved["target_branch"] == "dev"
        dev_info = GitBranchService(layout).get_branch(srv_id, srv_root, "dev")
        assert dev_info is not None and dev_info.worktree_path is not None
        overrides = load_branch_runtime_overrides(dev_info.worktree_path)
        assert overrides["min_memory_mb"] == 1536
        assert overrides["max_memory_mb"] == 3072
        assert overrides["cpu_cores"] == 3
        assert overrides["cpu_affinity"] == "0-2"
        assert "-XX:+UseG1GC" in overrides["java_args"]

    @pytest.mark.skipif(sys.platform == "win32", reason="Branch runtime requires POSIX")
    @pytest.mark.asyncio
    async def test_branch_runtime_applies_onx_runtime_json_overrides(
        self, tmp_path: Path
    ) -> None:
        servers_dir = tmp_path / "servers"
        host_state_dir = tmp_path / "host_state"
        layout = ensure_host_state_layout(
            AppSettings(
                servers_data_dir=str(servers_dir),
                host_state_dir=str(host_state_dir),
            )
        )
        srv_root = servers_dir / "srv_br_rt"
        srv_id = "srv-br-rt-1"
        srv = await _create_server(srv_id, srv_root, mode=ServerMode.ADVANCED)
        GitRepositoryService(layout).initialize(srv_id, srv_root, _lockfile())
        GitBranchService(layout).create_branch(srv_id, srv_root, "feat", start_point="main")

        async with database.session_factory() as session:
            await save_branch_scoped_settings(
                session=session,
                server=srv,
                branch_name="feat",
                min_memory_mb=2048,
                max_memory_mb=4096,
                cpu_cores=3,
                cpu_affinity="1-3",
                java_args=["-XX:+UseG1GC", "-XX:+AlwaysPreTouch"],
                layout=layout,
            )
            await session.commit()

        captured_calls: list[list[str]] = []

        async def _fake_docker(args: list[str]) -> tuple[int, str]:
            captured_calls.append(list(args))
            if args and args[0] == "create":
                return (0, "cid-branch-123\n")
            return (0, "")

        fake_admission = MagicMock()
        fake_admission.admit_branch_runtime = AsyncMock(
            return_value=MagicMock(
                port_set=HostPortSet(game_port=26665, rcon_port=26675),
                memory_max_mb=4096,
                memory_min_mb=1024,
                cpu_cores=3,
            )
        )

        service = BranchRuntimeService(
            layout=layout,
            session_factory=database.session_factory,
            admission_scheduler=fake_admission,
            docker_runner=_fake_docker,
        )

        with (
            patch(
                "app.modules.versioning.infrastructure.branch_runtime_service.ensure_versioning_allowed",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.modules.versioning.infrastructure.branch_runtime_service.prepare_data_ownership",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.modules.versioning.infrastructure.branch_runtime_service.resolve_host_mount_path",
                side_effect=lambda p: p,
            ),
            patch(
                "app.modules.versioning.infrastructure.branch_runtime_service.validate_data_only_mounts",
                return_value=None,
            ),
        ):
            res = await service.start_branch_runtime(
                BranchStartRequest(
                    server_id=srv_id,
                    server_root=str(srv_root),
                    branch_name="feat",
                    server_provider="docker",
                    server_mode="advanced",
                    requested_memory_mb=None,
                    requested_cpu_cores=None,
                    jvm_args="",
                    check_os_ports=False,
                )
            )

        assert res.memory_max_mb == 4096
        assert res.cpu_cores == 3
        admit_kwargs = fake_admission.admit_branch_runtime.call_args.kwargs
        assert admit_kwargs["requested_memory_mb"] == 4096
        assert admit_kwargs["requested_cpu_cores"] == 3

        create_call = next(c for c in captured_calls if c and c[0] == "create")
        assert "--cpuset-cpus" in create_call
        assert create_call[create_call.index("--cpuset-cpus") + 1] == "1-3"
        assert "--cpus" in create_call
        assert create_call[create_call.index("--cpus") + 1] == "3"
        assert "--memory" in create_call
        assert create_call[create_call.index("--memory") + 1] == f"{4096 + 512}m"

        jvm_txt = Path(res.export_path) / "user_jvm_args.txt"
        assert "-XX:+AlwaysPreTouch" in jvm_txt.read_text(encoding="utf-8")

    def test_build_branch_docker_create_args_includes_cpu_affinity_and_jvm_flags(
        self, tmp_path: Path
    ) -> None:
        args = build_branch_docker_create_args(
            container_name="onx-branch-test",
            image="eclipse-temurin:21-jre-jammy",
            export_root=tmp_path,
            host_mount=str(tmp_path),
            memory_min_mb=1536,
            memory_max_mb=3072,
            cpu_cores=2,
            cpu_affinity="0,2",
            jvm_flags=["-XX:+UseG1GC", "-XX:+AlwaysPreTouch"],
            port_set=HostPortSet(game_port=26600, rcon_port=26601),
            uid=1000,
            gid=1000,
        )
        assert "--cpuset-cpus" in args
        assert args[args.index("--cpuset-cpus") + 1] == "0,2"
        assert "-XX:+AlwaysPreTouch" in args
        assert "-Xms1536M" in args
        assert "-Xmx3072M" in args


class TestDockerProviderUserJvmArgsPrecedence:
    @pytest.mark.asyncio
    async def test_user_java_args_not_shadowed_by_launch_config_jvm_flags(
        self, tmp_path: Path
    ) -> None:
        provider = DockerProvider()
        srv_dir = tmp_path / "test_servers" / "srv-jvm-precedence"
        unix_args_rel = "libraries/net/neoforged/neoforge/21.1.0/unix_args.txt"
        unix_args_file = srv_dir / unix_args_rel
        unix_args_file.parent.mkdir(parents=True)
        unix_args_file.write_text("-cp libraries/neoforge.jar Main\n", encoding="utf-8")

        deployment = ServerDeployment(
            location_type=LocationType.DOCKER,
            root_path=str(srv_dir),
            startup_command=f"java @user_jvm_args.txt @{unix_args_rel} nogui",
        )
        launch_config = LaunchConfiguration(
            startup_command=["java", "@user_jvm_args.txt", f"@{unix_args_rel}", "nogui"],
            jvm_flags=(
                "--add-opens",
                "java.base/java.lang=ALL-UNNAMED",
                "-XX:+UseSerialGC",
            ),
        )
        config: dict[str, Any] = {
            "image": "eclipse-temurin:21-jre-jammy",
            "server_type": "neoforge",
            "port": 25575,
            "memory_min_mb": 2048,
            "memory_max_mb": 4096,
            "cpu_cores": 2,
            "java_args": ["-XX:+UseG1GC", "-XX:MaxGCPauseMillis=150"],
        }

        with (
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            mock_docker.side_effect = [
                (1, "No such container"),
                (0, ""),
                (0, ""),
                (0, "9999\n"),
            ]
            res = await provider.start(
                server_id="jvm-prec",
                config=config,
                deployment=deployment,
                launch_config=launch_config,
            )

        assert res.status == ServerRuntimeStatus.RUNNING
        user_jvm = (srv_dir / "user_jvm_args.txt").read_text(encoding="utf-8")
        assert "-XX:+UseG1GC" in user_jvm
        assert "-XX:MaxGCPauseMillis=150" in user_jvm
        assert "--add-opens" in user_jvm
        assert "java.base/java.lang=ALL-UNNAMED" in user_jvm
        assert "-XX:+UseSerialGC" not in user_jvm


class TestValidationAndDisplayName:
    def test_server_properties_validates_simulation_distance_and_spawn_protection(self) -> None:
        with pytest.raises(ValueError, match="simulation_distance"):
            ServerProperties(port=PortNumber(25565), simulation_distance=1)
        with pytest.raises(ValueError, match="simulation_distance"):
            ServerProperties(port=PortNumber(25565), simulation_distance=33)
        with pytest.raises(ValueError, match="spawn_protection"):
            ServerProperties(port=PortNumber(25565), spawn_protection=-1)
        with pytest.raises(ValueError, match="spawn_protection"):
            ServerProperties(port=PortNumber(25565), spawn_protection=1001)

    def test_server_update_request_validates_name_bounds(self) -> None:
        with pytest.raises(PydanticValidationError):
            ServerUpdateRequest(name="   ")
        with pytest.raises(PydanticValidationError):
            ServerUpdateRequest(name="a" * 129)
        ok = ServerUpdateRequest(name="  Trimmed Server  ")
        assert ok.name == "Trimmed Server"

    def test_resolve_display_name_prioritizes_db_name_over_properties_file(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "server.properties").write_text(
            "server-name=OldDiskName\n", encoding="utf-8"
        )
        srv = Server.create(
            server_id=ServerId("srv-name-1"),
            name="FreshDbName",
            server_type=ServerType.PAPER,
            minecraft_version=MinecraftVersion.parse("1.21.1"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25565)),
            deployment=ServerDeployment(location_type=LocationType.DOCKER, root_path=str(tmp_path)),
        )
        assert resolve_display_name(srv) == "FreshDbName"
