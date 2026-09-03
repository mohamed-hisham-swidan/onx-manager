from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.exceptions import NotFoundError, ServerNotFoundError
from app.core.persistence.base import Base
from app.modules.auth.infrastructure.models import UserModel  # noqa: F401
from app.modules.backup.domain.aggregate import BackupJob, BackupPolicy, BackupType
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.monitoring.domain.aggregate import (
    AlertCondition,
    AlertRule,
    AlertSeverity,
    MetricPoint,
)
from app.modules.monitoring.infrastructure.repository import (
    SQLAlertRuleRepository,
    SQLMetricRepository,
)
from app.modules.plugin.domain.aggregate import Plugin
from app.modules.plugin.infrastructure.repository import SQLPluginRepository
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.value_objects import (
    JavaArguments,
    LaunchConfiguration,
    MemoryAllocation,
    PortNumber,
    ServerProperties,
    ServerType,
)
from app.modules.server.infrastructure.models import ServerModel
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import (
    BackupJobId,
    CronExpression,
    MinecraftVersion,
    PluginId,
    PluginVersion,
    ServerId,
)

TEST_DB_URL = "sqlite+aiosqlite://"


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def server_repo(db_session: AsyncSession) -> SQLServerRepository:
    return SQLServerRepository(db_session)


@pytest_asyncio.fixture
async def backup_repo(db_session: AsyncSession) -> SQLBackupRepository:
    return SQLBackupRepository(db_session)


@pytest_asyncio.fixture
async def plugin_repo(db_session: AsyncSession) -> SQLPluginRepository:
    return SQLPluginRepository(db_session)


class TestSQLServerRepository:
    @pytest.mark.asyncio
    async def test_save_and_get(self, server_repo: SQLServerRepository) -> None:
        server = Server.create(
            server_id=ServerId("test-1"),
            name="Test Server",
            server_type=ServerType.VANILLA,
            minecraft_version=MinecraftVersion.parse("1.21.4"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(["-Xmx2G"]),
            properties=ServerProperties(port=PortNumber(25565)),
        )
        server.collect_events()
        await server_repo.save(server)

        loaded = await server_repo.get(ServerId("test-1"))
        assert loaded.name == "Test Server"
        assert loaded.status.value == "created"

    @pytest.mark.asyncio
    async def test_save_and_reload_complex_jvm_args(self, server_repo: SQLServerRepository) -> None:
        """ISS-009: Complex JVM args with spaces and quotes roundtrip faithfully."""
        complex_args = [
            "-Xmx4G",
            '-Dproperty="hello world"',
            '-XX:OnOutOfMemoryError="kill -9 %p"',
            "-Dcustom.msg=welcome to minecraft",
        ]
        server = Server.create(
            server_id=ServerId("test-complex-jvm"),
            name="Complex JVM Server",
            server_type=ServerType.VANILLA,
            minecraft_version=MinecraftVersion.parse("1.21.4"),
            memory=MemoryAllocation(1024, 4096),
            java_args=JavaArguments(complex_args),
            properties=ServerProperties(port=PortNumber(25565)),
        )
        await server_repo.save(server)

        loaded = await server_repo.get(ServerId("test-complex-jvm"))
        assert list(loaded.java_args.args) == complex_args, (
            f"Expected {complex_args}, got {list(loaded.java_args.args)}"
        )

    @pytest.mark.asyncio
    async def test_get_not_found(self, server_repo: SQLServerRepository) -> None:
        with pytest.raises(ServerNotFoundError):
            await server_repo.get(ServerId("nonexistent"))

    @pytest.mark.asyncio
    async def test_save_and_list(self, server_repo: SQLServerRepository) -> None:
        s1 = Server.create(
            server_id=ServerId("s1"),
            name="Alpha",
            server_type=ServerType.VANILLA,
            minecraft_version=MinecraftVersion.parse("1.21"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25565)),
        )
        s2 = Server.create(
            server_id=ServerId("s2"),
            name="Beta",
            server_type=ServerType.VANILLA,
            minecraft_version=MinecraftVersion.parse("1.20"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25566)),
        )
        s1.collect_events()
        s2.collect_events()
        await server_repo.save(s1)
        await server_repo.save(s2)

        servers = await server_repo.list()
        assert len(servers) == 2

    @pytest.mark.asyncio
    async def test_save_and_delete(self, server_repo: SQLServerRepository) -> None:
        server = Server.create(
            server_id=ServerId("del"),
            name="ToDelete",
            server_type=ServerType.VANILLA,
            minecraft_version=MinecraftVersion.parse("1.21"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25565)),
        )
        server.collect_events()
        await server_repo.save(server)
        await server_repo.delete(ServerId("del"))
        with pytest.raises(ServerNotFoundError):
            await server_repo.get(ServerId("del"))

    @pytest.mark.asyncio
    async def test_save_updates_existing(self, server_repo: SQLServerRepository) -> None:
        server = Server.create(
            server_id=ServerId("upd"),
            name="Original",
            server_type=ServerType.VANILLA,
            minecraft_version=MinecraftVersion.parse("1.21"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25565)),
        )
        server.collect_events()
        await server_repo.save(server)

        server._name = "Updated"
        await server_repo.save(server)

        loaded = await server_repo.get(ServerId("upd"))
        assert loaded.name == "Updated"


class TestSQLServerRepositoryLaunchConfig:
    @pytest.mark.asyncio
    async def test_save_and_load_launch_config(self, server_repo: SQLServerRepository) -> None:
        lc = LaunchConfiguration(
            java_executable="/usr/bin/java",
            startup_command=None,
            startup_jar="purpur-1.21.jar",
            jvm_flags=("-Xms1024M", "-Xmx2048M", "-XX:+UseG1GC"),
            environment={"JAVA_HOME": "/usr/lib/jvm/java-21"},
            working_directory="",
        )
        server = Server(
            server_id=ServerId("lc-test-1"),
            name="LaunchConfig Test",
            server_type=ServerType.PAPER,
            minecraft_version=MinecraftVersion.parse("1.21"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(["-Xmx2G"]),
            properties=ServerProperties(port=PortNumber(25565)),
            launch_config=lc,
        )
        await server_repo.save(server)

        loaded = await server_repo.get(ServerId("lc-test-1"))
        assert loaded.launch_config is not None
        assert loaded.launch_config.java_executable == "/usr/bin/java"
        assert loaded.launch_config.startup_jar == "purpur-1.21.jar"
        assert loaded.launch_config.jvm_flags == ("-Xms1024M", "-Xmx2048M", "-XX:+UseG1GC")
        assert loaded.launch_config.environment == {"JAVA_HOME": "/usr/lib/jvm/java-21"}

    @pytest.mark.asyncio
    async def test_save_and_load_no_launch_config(self, server_repo: SQLServerRepository) -> None:
        server = Server(
            server_id=ServerId("lc-test-2"),
            name="No LaunchConfig",
            server_type=ServerType.VANILLA,
            minecraft_version=MinecraftVersion.parse("1.21"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25565)),
        )
        await server_repo.save(server)

        loaded = await server_repo.get(ServerId("lc-test-2"))
        assert loaded.launch_config is None

    @pytest.mark.asyncio
    async def test_load_corrupted_launch_config_json(self, db_session) -> None:
        model = ServerModel(
            id="lc-test-3",
            name="Corrupted LC",
            server_type="vanilla",
            minecraft_version="1.21",
            launch_config_json="{invalid json here}",
        )
        db_session.add(model)
        await db_session.commit()

        repo = SQLServerRepository(db_session)
        loaded = await repo.get(ServerId("lc-test-3"))
        assert loaded.launch_config is None


class TestSQLBackupRepository:
    @pytest.mark.asyncio
    async def test_save_and_get_job(self, backup_repo: SQLBackupRepository) -> None:
        job = BackupJob.create(
            backup_id=BackupJobId("b1"),
            server_id=ServerId("s1"),
            backup_type=BackupType.WORLD,
        )
        job.collect_events()
        await backup_repo.save_job(job)

        loaded = await backup_repo.get_job(BackupJobId("b1"))
        assert loaded.backup_type == BackupType.WORLD

    @pytest.mark.asyncio
    async def test_get_job_not_found(self, backup_repo: SQLBackupRepository) -> None:
        with pytest.raises(NotFoundError):
            await backup_repo.get_job(BackupJobId("nonexistent"))

    @pytest.mark.asyncio
    async def test_list_jobs(self, backup_repo: SQLBackupRepository) -> None:
        j1 = BackupJob.create(backup_id=BackupJobId("j1"), server_id=ServerId("s1"))
        j2 = BackupJob.create(backup_id=BackupJobId("j2"), server_id=ServerId("s1"))
        j3 = BackupJob.create(backup_id=BackupJobId("j3"), server_id=ServerId("s2"))
        j1.collect_events()
        j2.collect_events()
        j3.collect_events()
        await backup_repo.save_job(j1)
        await backup_repo.save_job(j2)
        await backup_repo.save_job(j3)

        all_jobs = await backup_repo.list_jobs()
        assert len(all_jobs) == 3

        s1_jobs = await backup_repo.list_jobs(server_id=ServerId("s1"))
        assert len(s1_jobs) == 2

    @pytest.mark.asyncio
    async def test_save_and_get_policy(self, backup_repo: SQLBackupRepository) -> None:
        policy = BackupPolicy(
            server_id=ServerId("s1"),
            schedule=CronExpression("0 */6 * * *"),
            retention_days=7,
        )
        await backup_repo.save_policy(policy)

        loaded = await backup_repo.get_policy(ServerId("s1"))
        assert loaded is not None
        assert loaded.retention_days == 7

    @pytest.mark.asyncio
    async def test_delete_job(self, backup_repo: SQLBackupRepository) -> None:
        job = BackupJob.create(backup_id=BackupJobId("del"), server_id=ServerId("s1"))
        job.collect_events()
        await backup_repo.save_job(job)
        await backup_repo.delete_job(BackupJobId("del"))

        with pytest.raises(NotFoundError):
            await backup_repo.get_job(BackupJobId("del"))


class TestSQLPluginRepository:
    @pytest.mark.asyncio
    async def test_save_and_get(self, plugin_repo: SQLPluginRepository) -> None:
        plugin = Plugin.install(
            plugin_id=PluginId("p1"),
            server_id=ServerId("s1"),
            name="Essentials",
            version=PluginVersion.parse("2.0.0"),
        )
        plugin.collect_events()
        await plugin_repo.save(plugin)

        loaded = await plugin_repo.get(PluginId("p1"))
        assert loaded.name == "Essentials"
        assert loaded.version == PluginVersion.parse("2.0.0")

    @pytest.mark.asyncio
    async def test_get_not_found(self, plugin_repo: SQLPluginRepository) -> None:
        with pytest.raises(NotFoundError):
            await plugin_repo.get(PluginId("nonexistent"))

    @pytest.mark.asyncio
    async def test_list_by_server(self, plugin_repo: SQLPluginRepository) -> None:
        p1 = Plugin.install(
            plugin_id=PluginId("a"),
            server_id=ServerId("s1"),
            name="A",
            version=PluginVersion.parse("1.0.0"),
        )
        p2 = Plugin.install(
            plugin_id=PluginId("b"),
            server_id=ServerId("s1"),
            name="B",
            version=PluginVersion.parse("1.0.0"),
        )
        p1.collect_events()
        p2.collect_events()
        await plugin_repo.save(p1)
        await plugin_repo.save(p2)

        plugins = await plugin_repo.list_by_server(ServerId("s1"))
        assert len(plugins) == 2

    @pytest.mark.asyncio
    async def test_delete(self, plugin_repo: SQLPluginRepository) -> None:
        plugin = Plugin.install(
            plugin_id=PluginId("del"),
            server_id=ServerId("s1"),
            name="Del",
            version=PluginVersion.parse("1.0.0"),
        )
        plugin.collect_events()
        await plugin_repo.save(plugin)
        await plugin_repo.delete(PluginId("del"))

        with pytest.raises(NotFoundError):
            await plugin_repo.get(PluginId("del"))


class TestSQLMetricRepository:
    @pytest.mark.asyncio
    async def test_record_and_get_series(self, db_session: AsyncSession) -> None:
        repo = SQLMetricRepository(db_session)
        point = MetricPoint(tps=20.0, players=5, ram_used_mb=1024.0, cpu_percent=45.0)

        await repo.record(ServerId("s1"), point)

        series = await repo.get_series(ServerId("s1"), limit=10)
        assert len(series) == 1
        assert series[0].tps == 20.0
        assert series[0].players == 5


class TestSQLAlertRuleRepository:
    @pytest.mark.asyncio
    async def test_save_and_get(self, db_session: AsyncSession) -> None:
        repo = SQLAlertRuleRepository(db_session)
        rule = AlertRule(
            server_id=ServerId("s1"),
            metric_name="tps",
            condition=AlertCondition.LESS_THAN,
            threshold=10.0,
            severity=AlertSeverity.WARNING,
        )
        await repo.save(rule)

        loaded = await repo.get(rule._alert_rule_id)
        assert loaded.metric_name == "tps"
        assert loaded.threshold == 10.0

    @pytest.mark.asyncio
    async def test_get_not_found(self, db_session: AsyncSession) -> None:
        repo = SQLAlertRuleRepository(db_session)
        with pytest.raises(NotFoundError):
            await repo.get("nonexistent")

    @pytest.mark.asyncio
    async def test_list_by_server(self, db_session: AsyncSession) -> None:
        repo = SQLAlertRuleRepository(db_session)
        r1 = AlertRule(
            server_id=ServerId("s1"),
            metric_name="tps",
            condition=AlertCondition.LESS_THAN,
            threshold=10.0,
        )
        r2 = AlertRule(
            server_id=ServerId("s1"),
            metric_name="players",
            condition=AlertCondition.GREATER_THAN,
            threshold=50.0,
        )
        await repo.save(r1)
        await repo.save(r2)

        rules = await repo.list_by_server(ServerId("s1"))
        assert len(rules) == 2

    @pytest.mark.asyncio
    async def test_delete(self, db_session: AsyncSession) -> None:
        repo = SQLAlertRuleRepository(db_session)
        rule = AlertRule(
            server_id=ServerId("s1"),
            metric_name="tps",
            condition=AlertCondition.LESS_THAN,
            threshold=10.0,
        )
        await repo.save(rule)
        await repo.delete(rule._alert_rule_id)

        with pytest.raises(NotFoundError):
            await repo.get(rule._alert_rule_id)
