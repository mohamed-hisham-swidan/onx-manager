from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command
from app.core.config import ServerConfig
from app.core.persistence.base import Base
from app.core.settings_store import (
    _DEFAULTS,
    _coerce,
    get_live_settings,
    init_settings_store,
)
from app.modules.auth.infrastructure.models import UserModel  # noqa: F401 - registers users table
from app.modules.server.domain.aggregate import Server, ServerStatus
from app.modules.server.domain.value_objects import (
    JavaArguments,
    MemoryAllocation,
    PortNumber,
    RuntimeInfo,
    ServerProperties,
    ServerType,
    default_provider_for_platform,
)
from app.modules.server.infrastructure.models import ServerModel
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import MinecraftVersion, ServerId

# ─── 1. Provider Default Tests ───


class TestPlatformProviderDefault:
    def test_default_provider_for_platform(self):
        with patch.object(sys, "platform", "win32"):
            assert default_provider_for_platform() == "local_windows"

        with patch.object(sys, "platform", "linux"):
            assert default_provider_for_platform() == "local"

        with patch.object(sys, "platform", "darwin"):
            assert default_provider_for_platform() == "local"

    def test_runtime_info_default_empty(self):
        info = RuntimeInfo()
        assert info.provider == ""
        assert info.running_start_time is None

    def test_server_aggregate_default_provider_on_linux(self):
        with patch(
            "app.modules.server.domain.aggregate.default_provider_for_platform",
            return_value="local",
        ):
            server = Server(
                server_id=ServerId("srv-linux"),
                name="Linux Server",
                server_type=ServerType("vanilla"),
                minecraft_version=MinecraftVersion.parse("1.20.4"),
                memory=MemoryAllocation(1024, 2048),
                java_args=JavaArguments(),
                properties=ServerProperties(port=PortNumber(25565)),
            )
            assert server.runtime.provider == "local"

    def test_server_aggregate_default_provider_on_windows(self):
        with patch(
            "app.modules.server.domain.aggregate.default_provider_for_platform",
            return_value="local_windows",
        ):
            server = Server(
                server_id=ServerId("srv-win"),
                name="Win Server",
                server_type=ServerType("vanilla"),
                minecraft_version=MinecraftVersion.parse("1.20.4"),
                memory=MemoryAllocation(1024, 2048),
                java_args=JavaArguments(),
                properties=ServerProperties(port=PortNumber(25565)),
            )
            assert server.runtime.provider == "local_windows"

    def test_server_config_default_provider(self):
        with patch(
            "app.modules.server.domain.value_objects.sys.platform",
            "win32",
        ):
            cfg_win = ServerConfig(server_id="s1", name="Win")
            assert cfg_win.provider == "local_windows"

        with patch(
            "app.modules.server.domain.value_objects.sys.platform",
            "linux",
        ):
            cfg_linux = ServerConfig(server_id="s2", name="Linux")
            assert cfg_linux.provider == "local"


# ─── 2. Startup Migration Tests ───


class TestWindowsStartupMigration:
    @pytest_asyncio.fixture
    async def db_session(self) -> AsyncSession:
        engine = create_async_engine("sqlite+aiosqlite://", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            yield session

        await engine.dispose()

    @pytest.mark.asyncio
    async def test_migration_updates_local_to_local_windows_on_win32(
        self, db_session: AsyncSession
    ):
        # Seed servers with provider="local" and provider="custom"
        s1 = ServerModel(
            id="s1",
            name="Server 1",
            server_type="vanilla",
            minecraft_version="1.20.4",
            provider="local",
        )
        s2 = ServerModel(
            id="s2",
            name="Server 2",
            server_type="paper",
            minecraft_version="1.20.4",
            provider="docker",
        )
        db_session.add_all([s1, s2])
        await db_session.commit()

        # Run migration logic as in main.py under sys.platform="win32"
        with patch.object(sys, "platform", "win32"):
            if sys.platform == "win32":
                target_provider = default_provider_for_platform()  # "local_windows"
                stmt = select(ServerModel).where(ServerModel.provider == "local")
                result = await db_session.execute(stmt)
                servers_to_migrate = result.scalars().all()

                if servers_to_migrate:
                    for s in servers_to_migrate:
                        s.provider = target_provider
                    await db_session.commit()

        # Verify
        re_s1 = await db_session.get(ServerModel, "s1")
        re_s2 = await db_session.get(ServerModel, "s2")
        assert re_s1.provider == "local_windows"
        assert re_s2.provider == "docker"

    @pytest.mark.asyncio
    async def test_migration_noop_on_linux(self, db_session: AsyncSession):
        s1 = ServerModel(
            id="s1",
            name="Server 1",
            server_type="vanilla",
            minecraft_version="1.20.4",
            provider="local",
        )
        db_session.add(s1)
        await db_session.commit()

        with patch.object(sys, "platform", "linux"):
            if sys.platform == "win32":
                target_provider = default_provider_for_platform()
                stmt = select(ServerModel).where(ServerModel.provider == "local")
                result = await db_session.execute(stmt)
                for s in result.scalars().all():
                    s.provider = target_provider
                await db_session.commit()

        re_s1 = await db_session.get(ServerModel, "s1")
        assert re_s1.provider == "local"

    @pytest.mark.asyncio
    async def test_migration_idempotent(self, db_session: AsyncSession):
        s1 = ServerModel(
            id="s1",
            name="Server 1",
            server_type="vanilla",
            minecraft_version="1.20.4",
            provider="local",
        )
        db_session.add(s1)
        await db_session.commit()

        for _ in range(2):
            with patch.object(sys, "platform", "win32"):
                target_provider = default_provider_for_platform()
                stmt = select(ServerModel).where(ServerModel.provider == "local")
                result = await db_session.execute(stmt)
                servers_to_migrate = result.scalars().all()
                for s in servers_to_migrate:
                    s.provider = target_provider
                await db_session.commit()

        re_s1 = await db_session.get(ServerModel, "s1")
        assert re_s1.provider == "local_windows"


# ─── 3. running_start_time Persistence & mark_running Tests ───


class TestRunningStartTimePersistenceChain:
    @pytest_asyncio.fixture
    async def db_session(self) -> AsyncSession:
        engine = create_async_engine("sqlite+aiosqlite://", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            yield session

        await engine.dispose()

    @pytest.mark.asyncio
    async def test_repository_roundtrip_preserves_running_start_time(
        self, db_session: AsyncSession
    ):
        repo = SQLServerRepository(db_session)
        expected_rst = 1724912345.678

        server = Server(
            server_id=ServerId("srv-rst-1"),
            name="RST Server",
            server_type=ServerType("vanilla"),
            minecraft_version=MinecraftVersion.parse("1.20.4"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25565)),
            runtime=RuntimeInfo(
                status="running",
                provider="local_windows",
                host="127.0.0.1",
                port=25565,
                pid=1234,
                start_time=1724912300,
                running_start_time=expected_rst,
            ),
        )

        await repo.save(server)
        await db_session.commit()

        loaded = await repo.get(ServerId("srv-rst-1"))
        assert loaded is not None
        assert loaded.runtime is not None
        assert loaded.runtime.provider == "local_windows"
        assert loaded.runtime.start_time == 1724912300
        assert loaded.runtime.running_start_time == pytest.approx(expected_rst, 0.001)

    def test_mark_running_sets_wall_clock_running_start_time(self):
        server = Server(
            server_id=ServerId("srv-mr"),
            name="MR Server",
            server_type=ServerType("vanilla"),
            minecraft_version=MinecraftVersion.parse("1.20.4"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25565)),
        )

        server.start()
        before = time.time()
        server.mark_running(pid=999, port=25565, start_time=1000)
        after = time.time()

        assert server.status == ServerStatus.RUNNING
        assert server.runtime.pid == 999
        assert server.runtime.start_time == 1000
        assert server.runtime.running_start_time is not None
        assert before <= server.runtime.running_start_time <= after

    def test_mark_running_explicit_running_start_time(self):
        server = Server(
            server_id=ServerId("srv-mr-exp"),
            name="MR Server Exp",
            server_type=ServerType("vanilla"),
            minecraft_version=MinecraftVersion.parse("1.20.4"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25565)),
        )

        server.start()
        server.mark_running(pid=999, port=25565, start_time=1000, running_start_time=12345.6)
        assert server.runtime.running_start_time == 12345.6


# ─── 4. post_running_grace_seconds Setting Tests ───


class TestPostRunningGraceSecondsSetting:
    def test_defaults(self, tmp_path, monkeypatch):
        test_yaml = tmp_path / "settings.yaml"
        monkeypatch.setattr("app.core.settings_store._SETTINGS_FILE", test_yaml)
        init_settings_store(test_yaml)

        assert _DEFAULTS["post_running_grace_seconds"] == 30.0
        live = get_live_settings()
        assert live.post_running_grace_seconds == 30.0

    def test_clamping_and_coercion(self):
        assert _coerce("post_running_grace_seconds", 0.5) == 1.0
        assert _coerce("post_running_grace_seconds", -10) == 1.0
        assert _coerce("post_running_grace_seconds", 450.0) == 300.0
        assert _coerce("post_running_grace_seconds", 45.678) == 45.7
        assert _coerce("post_running_grace_seconds", "60.0") == 60.0
        assert _coerce("post_running_grace_seconds", "invalid") == 30.0
        assert _coerce("post_running_grace_seconds", None) == 30.0


# ─── 5. Alembic Migration Tests ───


class TestAlembicMigration:
    def test_alembic_upgrade_and_downgrade(self, tmp_path):
        backend_dir = Path(__file__).resolve().parent.parent
        ini_path = backend_dir / "alembic.ini"
        script_dir = backend_dir / "alembic"
        db_file = tmp_path / "alembic_test.db"

        alembic_cfg = Config(str(ini_path))
        alembic_cfg.attributes["configure_logger"] = False
        alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_file}")
        alembic_cfg.set_main_option("script_location", str(script_dir))

        # Upgrade all the way to head
        command.upgrade(alembic_cfg, "head")

        # Downgrade 1 revision (reverts running_start_time)
        command.downgrade(alembic_cfg, "-1")

        # Upgrade back to head
        command.upgrade(alembic_cfg, "head")
