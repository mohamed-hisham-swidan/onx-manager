"""Tests for profile-aware ResourceBudgetService, admission enforcement, and Docker caps."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core import resource_budget as rb_mod
from app.core.command_bus import CommandBus
from app.core.config import AppSettings
from app.core.event_bus import EventBus
from app.core.exceptions import InsufficientHostResourcesError
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.core.query_bus import QueryBus
from app.core.resource_budget import ResourceBudgetService
from app.core.settings_store import init_settings_store, update_settings
from app.main import create_app
from app.modules.auth.infrastructure.jwt import create_access_token
from app.modules.server.application.commands.create_server import (
    CreateServerCommand,
    CreateServerHandler,
)
from app.modules.server.application.commands.start_server import (
    StartServerCommand,
    StartServerHandler,
)
from app.modules.server.domain.value_objects import (
    LocationType,
    ServerDeployment,
)
from app.modules.server.infrastructure.models import ServerModel
from app.modules.server.infrastructure.providers.docker import DockerProvider
from app.modules.versioning.application.scheduling.admission import admit_branch_runtime
from app.modules.versioning.infrastructure.branch_runtime_service import (
    build_branch_docker_create_args,
)
from app.modules.versioning.infrastructure.models import (
    ServerCommitModel,
    ServerRuntimeModel,
)
from app.modules.versioning.infrastructure.port_allocator import HostPortSet
from app.registration import register_handlers


class TestOsReserveAndCgroupDetection:
    def test_local_vs_vps_reserve_policies(self) -> None:
        # 16 GB, 8 cores host
        local_ram, local_cpu = ResourceBudgetService.compute_os_reserve(16384, 8.0, "local")
        vps_ram, vps_cpu = ResourceBudgetService.compute_os_reserve(16384, 8.0, "vps")
        assert local_ram == 4096
        assert local_cpu == 2.0
        assert vps_ram == 2457
        assert vps_cpu == 0.8

        # Small 4 GB desktop should cap reserve cleanly at 60% instead of starving
        small_local_ram, _ = ResourceBudgetService.compute_os_reserve(4096, 4.0, "local")
        small_vps_ram, _ = ResourceBudgetService.compute_os_reserve(4096, 4.0, "vps")
        assert small_local_ram == 2457
        assert small_vps_ram == 1024

        # Explicit overrides take priority
        ovr_ram, ovr_cpu = ResourceBudgetService.compute_os_reserve(
            16384, 8.0, "local", ram_override_mb=6144, cpu_override=3.0
        )
        assert ovr_ram == 6144
        assert ovr_cpu == 3.0

    def test_cgroup_limits_cap_host_capacity(self, tmp_path: Path, monkeypatch) -> None:
        mem = SimpleNamespace(total=64 * 1024 * 1024 * 1024)
        monkeypatch.setattr("psutil.virtual_memory", lambda: mem)
        monkeypatch.setattr("os.cpu_count", lambda: 16)
        monkeypatch.setattr("os.name", "posix")
        monkeypatch.setattr(rb_mod, "_read_cgroup_memory_limit_mb", lambda: 8192)
        monkeypatch.setattr(rb_mod, "_read_cgroup_cpu_limit", lambda: 4.0)

        ram_mb, cpus = ResourceBudgetService.detect_host_capacity()
        assert ram_mb == 8192
        assert cpus == 4.0


@pytest.mark.asyncio
class TestHostBudgetAdmissionAndApi:
    @pytest.fixture
    async def isolated_budget_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        settings_yaml = tmp_path / "settings.yaml"
        monkeypatch.setattr("app.core.settings_store._SETTINGS_FILE", settings_yaml)
        init_settings_store(settings_yaml)
        monkeypatch.setenv("ONX_SERVERS_DATA_DIR", str(tmp_path / "servers"))
        monkeypatch.setenv("ONX_DEPLOYMENT_PROFILE", "local")
        monkeypatch.setattr(
            "psutil.virtual_memory",
            lambda: SimpleNamespace(total=10240 * 1024 * 1024),  # 10 GB host -> 4096 reserve
        )
        monkeypatch.setattr("os.cpu_count", lambda: 8)
        monkeypatch.setattr(rb_mod, "_read_cgroup_memory_limit_mb", lambda: None)
        monkeypatch.setattr(rb_mod, "_read_cgroup_cpu_limit", lambda: None)

        engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        database._engine = engine
        database._session_factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )
        try:
            yield engine
        finally:
            await engine.dispose()
            database._engine = None
            database._session_factory = None

    async def test_endpoint_counts_servers_and_branch_runtimes(self, isolated_budget_env) -> None:
        async with database._session_factory() as session:
            session.add_all(
                [
                    ServerModel(
                        id="srv-run",
                        name="Survival",
                        server_type="paper",
                        minecraft_version="1.21",
                        memory_min_mb=1024,
                        memory_max_mb=3072,
                        cpu_cores=2,
                        status="running",
                    ),
                    ServerModel(
                        id="srv-stop",
                        name="Stopped One",
                        server_type="vanilla",
                        minecraft_version="1.21",
                        memory_min_mb=1024,
                        memory_max_mb=4096,
                        cpu_cores=4,
                        status="stopped",
                    ),
                    ServerModel(
                        id="srv-adv",
                        name="Modded Dev",
                        server_type="fabric",
                        minecraft_version="1.21",
                        memory_min_mb=1024,
                        memory_max_mb=2048,
                        cpu_cores=2,
                        status="stopped",
                        mode="advanced",
                    ),
                ]
            )
            await session.flush()
            session.add(
                ServerCommitModel(
                    id="c-1",
                    server_id="srv-adv",
                    message="init",
                    manifest_json={},
                )
            )
            await session.flush()
            session.add(
                ServerRuntimeModel(
                    id="rt-1",
                    server_id="srv-adv",
                    commit_id="c-1",
                    branch_name="exp-feature",
                    status="running",
                )
            )
            await session.commit()

        app = create_app(static_dir="off")
        deps_cb, deps_qb, deps_eb = CommandBus(), QueryBus(), EventBus()
        register_handlers(deps_cb, deps_qb, deps_eb)
        token = create_access_token(user_id="owner-1", roles=["owner"], permissions=["admin:full"])

        async with AsyncClient(
            transport=ASGITransport(app=app, client=("127.0.0.1", 50020)),
            base_url="http://127.0.0.1:8000",
        ) as client:
            res = await client.get(
                "/api/v1/monitoring/host-resources",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert res.status_code == 200
            data = res.json()
            assert data["total_ram_mb"] == 10240
            assert data["os_reserve_ram_mb"] == 4096
            assert data["allocatable_ram_mb"] == 6144
            # Running server (3072) + branch runtime on Modded Dev (2048) = 5120
            assert data["allocated_ram_mb"] == 5120
            assert data["available_ram_mb"] == 1024
            assert data["allocated_cpus"] == 4.0
            assert data["profile"] == "local"
            kinds = {item["kind"] for item in data["allocations"]}
            assert kinds == {"server", "branch_runtime"}

            # Custom settings override shrinks allocatable pool cleanly
            patch_res = await client.patch(
                "/api/v1/settings",
                json={"host_ram_reserve_mb": 5120, "host_cpu_reserve": 3.0},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert patch_res.status_code == 200
            res2 = await client.get(
                "/api/v1/monitoring/host-resources",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert res2.json()["os_reserve_ram_mb"] == 5120
            assert res2.json()["available_ram_mb"] == 0
            update_settings({"host_ram_reserve_mb": 0, "host_cpu_reserve": 0.0})

    async def test_create_and_start_server_enforce_budget_and_release_on_stop(
        self, isolated_budget_env, tmp_path: Path
    ) -> None:
        bus = EventBus()
        create_handler = CreateServerHandler(bus)

        # 10 GB local host -> 4096 reserve -> 6144 allocatable. Requesting 8192 must fail.
        with pytest.raises(InsufficientHostResourcesError) as exc_info:
            await create_handler.handle(
                CreateServerCommand(
                    name="TooBig",
                    server_type="vanilla",
                    minecraft_version="1.21",
                    min_memory_mb=1024,
                    max_memory_mb=8192,
                )
            )
        assert exc_info.value.code == "INSUFFICIENT_HOST_RESOURCES"

        # Seed two 4096 MB servers; starting both sequentially fails on the second
        s1_dir = tmp_path / "servers" / "s1"
        s2_dir = tmp_path / "servers" / "s2"
        for d in (s1_dir, s2_dir):
            d.mkdir(parents=True, exist_ok=True)
            (d / "eula.txt").write_text("eula=true\n")
            (d / "server.jar").write_bytes(b"fake-jar")

        async with database._session_factory() as session:
            session.add_all(
                [
                    ServerModel(
                        id="s1",
                        name="First",
                        server_type="vanilla",
                        minecraft_version="1.21",
                        memory_min_mb=1024,
                        memory_max_mb=4096,
                        cpu_cores=4,
                        port=25565,
                        provider="docker",
                        location_type="docker",
                        root_path=str(s1_dir),
                        working_directory=".",
                        startup_jar="server.jar",
                        status="running",
                    ),
                    ServerModel(
                        id="s2",
                        name="Second",
                        server_type="vanilla",
                        minecraft_version="1.21",
                        memory_min_mb=1024,
                        memory_max_mb=4096,
                        cpu_cores=2,
                        port=25566,
                        provider="docker",
                        location_type="docker",
                        root_path=str(s2_dir),
                        working_directory=".",
                        startup_jar="server.jar",
                        status="stopped",
                    ),
                ]
            )
            await session.commit()

        start_handler = StartServerHandler(bus)
        with (
            patch(
                "app.modules.server.application.commands.start_server.check_startup_readiness",
                AsyncMock(return_value=SimpleNamespace(allowed=True, reasons=[], warnings=[])),
            ),
            pytest.raises(InsufficientHostResourcesError) as start_exc,
        ):
            await start_handler.handle(StartServerCommand(server_id="s2"))
        assert start_exc.value.code == "INSUFFICIENT_HOST_RESOURCES"

        # Stopping s1 releases the 4096 MB budget immediately
        async with database._session_factory() as session:
            srv1 = await session.get(ServerModel, "s1")
            assert srv1 is not None
            srv1.status = "stopped"
            await session.commit()

        async with database._session_factory() as session:
            budget_after_stop = await ResourceBudgetService.get_budget(session)
            assert budget_after_stop.allocated_ram_mb == 0
            assert budget_after_stop.available_ram_mb == 6144

    @pytest.mark.skipif(
        Path("/").anchor != "/", reason="Branch runtime admission requires POSIX paths"
    )
    async def test_branch_runtime_admission_checks_host_reserve_budget(
        self, isolated_budget_env, tmp_path: Path
    ) -> None:
        async with database._session_factory() as session:
            session.add_all(
                [
                    ServerModel(
                        id="srv-busy",
                        name="Busy",
                        server_type="vanilla",
                        minecraft_version="1.21",
                        memory_min_mb=1024,
                        memory_max_mb=4096,
                        cpu_cores=4,
                        status="running",
                    ),
                    ServerModel(
                        id="srv-adv",
                        name="Adv",
                        server_type="fabric",
                        minecraft_version="1.21",
                        memory_min_mb=1024,
                        memory_max_mb=3072,
                        cpu_cores=4,
                        status="stopped",
                        mode="advanced",
                        root_path=str(tmp_path / "srv-adv"),
                    ),
                ]
            )
            await session.commit()

        # 6144 allocatable - 4096 running = 2048 free; requesting 3072 MB branch run fails closed
        with (
            patch(
                "app.modules.versioning.infrastructure.resource_probe.ResourcePreflightProbe.check_headroom",
                return_value=SimpleNamespace(
                    passed=True, available_ram_mb=16384, available_cores=16, required_ram_mb=3072,
                    required_cores=2, message="ok",
                ),
            ),
            pytest.raises(InsufficientHostResourcesError),
        ):
            await admit_branch_runtime(
                server_id="srv-adv",
                branch_name="exp-heavy",
                commit_sha="b" * 40,
                requested_memory_mb=3072,
                requested_cpu_cores=2,
                engine=isolated_budget_env,
            )


@pytest.mark.asyncio
async def test_docker_and_branch_providers_emit_memory_swap_and_cpus(tmp_path: Path) -> None:
    provider = DockerProvider()
    captured: list[tuple[str, ...]] = []

    async def fake_cmd(*args: str, **_kwargs: object) -> tuple[int, str]:
        captured.append(args)
        if args and args[0] == "create":
            return 0, "container-123"
        if args and args[0] == "inspect":
            if "--format" in args and "{{json .}}" in args:
                return 1, "No such object"
            return 0, "172.17.0.2"
        return 0, ""

    server_dir = tmp_path / "srv"
    server_dir.mkdir()
    (server_dir / "server.jar").write_bytes(b"jar")
    deployment = ServerDeployment(
        location_type=LocationType.DOCKER,
        root_path=str(server_dir),
        working_directory=".",
        startup_jar="server.jar",
    )

    with (
        patch.object(provider, "_docker_command", side_effect=fake_cmd),
        patch.object(provider, "_ensure_image", AsyncMock()),
        patch("app.modules.server.infrastructure.providers.docker.AppSettings") as mock_cfg,
    ):
        mock_cfg.return_value = AppSettings(servers_data_dir=str(tmp_path))
        await provider.start(
            "srv-docker",
            {
                "server_dir": str(server_dir),
                "memory_min_mb": 1024,
                "memory_max_mb": 3072,
                "cpu_cores": 2,
                "minecraft_version": "1.21",
                "port": 25565,
            },
            deployment=deployment,
        )

    create_args = next(c for c in captured if c and c[0] == "create")
    assert create_args[create_args.index("--memory") + 1] == "3584m"
    assert create_args[create_args.index("--memory-swap") + 1] == "3584m"
    assert create_args[create_args.index("--cpus") + 1] == "2"

    branch_args = build_branch_docker_create_args(
        container_name="onx-branch-1",
        image="eclipse-temurin:21-jre-jammy",
        network="bridge",
        port_set=HostPortSet(game_port=25600, rcon_port=25601),
        memory_min_mb=1024,
        memory_max_mb=2048,
        cpu_cores=2,
        export_root=str(server_dir),
        host_mount=str(server_dir),
        uid=1000,
        gid=1000,
        server_id="srv-docker",
        branch_name="exp",
        runtime_id="rt-1",
        commit_sha="a" * 40,
    )
    assert branch_args[branch_args.index("--memory") + 1] == "2560m"
    assert branch_args[branch_args.index("--memory-swap") + 1] == "2560m"
    assert branch_args[branch_args.index("--cpus") + 1] == "2"
