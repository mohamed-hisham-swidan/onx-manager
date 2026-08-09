import pytest

from app.core.event_bus import EventBus
from app.core.persistence.db import database
from app.modules.plugin.application.commands.reconcile_plugins import (
    ReconcilePluginsCommand,
    ReconcilePluginsHandler,
)
from app.modules.plugin.domain.aggregate import Plugin
from app.modules.plugin.infrastructure.repository import SQLPluginRepository
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.value_objects import (
    JavaArguments,
    LocationType,
    MemoryAllocation,
    PortNumber,
    ServerDeployment,
    ServerProperties,
    ServerType,
)
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import MinecraftVersion, PluginId, PluginVersion, ServerId


async def _create_server(server_id: str, root_path: str) -> None:
    deployment = ServerDeployment(
        location_type=LocationType.LOCAL,
        root_path=root_path,
        working_directory=".",
    )
    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        server = Server.create(
            server_id=ServerId(server_id),
            name=f"Server {server_id}",
            server_type=ServerType.PAPER,
            minecraft_version=MinecraftVersion.parse("1.21"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25565)),
            deployment=deployment,
        )
        await repo.save(server)
        await session.commit()


async def _drop_jar(server_dir: str, filename: str) -> None:
    import os

    plugins_dir = os.path.join(server_dir, "plugins")
    os.makedirs(plugins_dir, exist_ok=True)
    with open(os.path.join(plugins_dir, filename), "wb") as f:
        f.write(b"PK\x03\x04fake-jar")


async def _drop_real_jar(server_dir: str, filename: str, version: str) -> None:
    import os
    import zipfile

    plugins_dir = os.path.join(server_dir, "plugins")
    os.makedirs(plugins_dir, exist_ok=True)
    jar_path = os.path.join(plugins_dir, filename)
    with zipfile.ZipFile(jar_path, "w") as zf:
        zf.writestr("plugin.yml", f"name: Test\nversion: {version}\n")


async def _seed_plugin_row(
    plugin_id: str,
    server_id: str,
    filename: str | None,
    *,
    pending_deletion: bool = False,
) -> None:
    async with database.session_factory() as session:
        repo = SQLPluginRepository(session)
        plugin = Plugin.install(
            plugin_id=PluginId(plugin_id),
            server_id=ServerId(server_id),
            name=(filename.rsplit(".", 1)[0] if filename else plugin_id),
            version=PluginVersion.parse("1.0.0"),
            filename=filename,
            source="detected",
        )
        if pending_deletion:
            plugin.request_deletion()
        plugin.collect_events()
        await repo.save(plugin)
        await session.commit()


@pytest.mark.usefixtures("init_test_db")
class TestReconcilePluginsHandler:
    @pytest.mark.asyncio
    async def test_no_deployment_noop(self, event_bus: EventBus, tmp_path) -> None:
        await _create_server("rec-nodeploy", str(tmp_path / "rec-nodeploy"))
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            server = await repo.get(ServerId("rec-nodeploy"))
            server.update_deployment(
                ServerDeployment(
                    location_type=LocationType.LOCAL,
                    root_path="",
                    working_directory=".",
                )
            )
            await repo.save(server)
            await session.commit()

        handler = ReconcilePluginsHandler(event_bus)
        result = await handler.handle(ReconcilePluginsCommand(server_id="rec-nodeploy"))
        assert result.success is True
        assert result.data["added"] == []
        assert result.data["removed"] == []

    @pytest.mark.asyncio
    async def test_detects_jar_on_disk_and_is_idempotent(
        self, event_bus: EventBus, tmp_path
    ) -> None:
        server_dir = str(tmp_path / "rec-det")
        await _create_server("rec-det", server_dir)
        await _drop_jar(server_dir, "MyPlugin.jar")

        handler = ReconcilePluginsHandler(event_bus)
        first = await handler.handle(ReconcilePluginsCommand(server_id="rec-det"))
        assert first.success is True
        assert first.data["added"] == ["MyPlugin.jar"]
        assert first.data["removed"] == []

        async with database.session_factory() as session:
            repo = SQLPluginRepository(session)
            plugins = await repo.list_all_by_server(ServerId("rec-det"))
            assert len(plugins) == 1
            assert plugins[0].filename == "MyPlugin.jar"
            assert plugins[0].source == "detected"
            assert plugins[0].name == "MyPlugin"
            assert plugins[0].display_version == "unknown"

        second = await handler.handle(ReconcilePluginsCommand(server_id="rec-det"))
        assert second.success is True
        assert second.data["added"] == []
        assert second.data["removed"] == []

    @pytest.mark.asyncio
    async def test_ignores_non_jar_files(self, event_bus: EventBus, tmp_path) -> None:
        server_dir = str(tmp_path / "rec-nonjar")
        await _create_server("rec-nonjar", server_dir)
        await _drop_jar(server_dir, "readme.txt")

        handler = ReconcilePluginsHandler(event_bus)
        result = await handler.handle(ReconcilePluginsCommand(server_id="rec-nonjar"))
        assert result.success is True
        assert result.data["added"] == []

    @pytest.mark.asyncio
    async def test_removes_row_when_file_deleted_directly(
        self, event_bus: EventBus, tmp_path
    ) -> None:
        import os

        server_dir = str(tmp_path / "rec-gone")
        await _create_server("rec-gone", server_dir)
        await _drop_jar(server_dir, "Removed.jar")

        handler = ReconcilePluginsHandler(event_bus)
        await handler.handle(ReconcilePluginsCommand(server_id="rec-gone"))

        os.unlink(os.path.join(server_dir, "plugins", "Removed.jar"))
        result = await handler.handle(ReconcilePluginsCommand(server_id="rec-gone"))
        assert result.success is True
        assert result.data["removed"] == ["Removed.jar"]

        async with database.session_factory() as session:
            repo = SQLPluginRepository(session)
            assert await repo.list_all_by_server(ServerId("rec-gone")) == []

    @pytest.mark.asyncio
    async def test_preserves_pending_deletion_row(self, event_bus: EventBus, tmp_path) -> None:
        server_dir = str(tmp_path / "rec-pending")
        await _create_server("rec-pending", server_dir)
        await _seed_plugin_row("rec-pending-1", "rec-pending", "Gone.jar", pending_deletion=True)

        handler = ReconcilePluginsHandler(event_bus)
        result = await handler.handle(ReconcilePluginsCommand(server_id="rec-pending"))
        assert result.success is True
        assert result.data["removed"] == []

        async with database.session_factory() as session:
            repo = SQLPluginRepository(session)
            plugins = await repo.list_all_by_server(ServerId("rec-pending"))
            assert len(plugins) == 1
            assert plugins[0].pending_deletion is True

    @pytest.mark.asyncio
    async def test_keeps_row_without_filename(self, event_bus: EventBus, tmp_path) -> None:
        server_dir = str(tmp_path / "rec-nofname")
        await _create_server("rec-nofname", server_dir)
        await _seed_plugin_row("rec-nofname-1", "rec-nofname", None)

        handler = ReconcilePluginsHandler(event_bus)
        result = await handler.handle(ReconcilePluginsCommand(server_id="rec-nofname"))
        assert result.success is True
        assert result.data["removed"] == []

        async with database.session_factory() as session:
            repo = SQLPluginRepository(session)
            plugins = await repo.list_all_by_server(ServerId("rec-nofname"))
            assert len(plugins) == 1

    @pytest.mark.asyncio
    async def test_reconcile_parses_jar_version_when_available(
        self, event_bus: EventBus, tmp_path
    ) -> None:
        server_dir = str(tmp_path / "rec-ver")
        await _create_server("rec-ver", server_dir)
        await _drop_real_jar(server_dir, "ParsedPlugin.jar", "1.2.3")

        handler = ReconcilePluginsHandler(event_bus)
        res = await handler.handle(ReconcilePluginsCommand(server_id="rec-ver"))
        assert res.success is True
        assert res.data["added"] == ["ParsedPlugin.jar"]

        async with database.session_factory() as session:
            repo = SQLPluginRepository(session)
            plugins = await repo.list_all_by_server(ServerId("rec-ver"))
            assert len(plugins) == 1
            assert plugins[0].display_version == "1.2.3"

    @pytest.mark.asyncio
    async def test_self_heals_existing_unknown_version_row(
        self, event_bus: EventBus, tmp_path
    ) -> None:
        server_dir = str(tmp_path / "rec-heal")
        await _create_server("rec-heal", server_dir)
        # First drop dummy jar without metadata
        await _drop_jar(server_dir, "HealPlugin.jar")

        handler = ReconcilePluginsHandler(event_bus)
        await handler.handle(ReconcilePluginsCommand(server_id="rec-heal"))

        async with database.session_factory() as session:
            repo = SQLPluginRepository(session)
            plugins = await repo.list_all_by_server(ServerId("rec-heal"))
            assert len(plugins) == 1
            assert plugins[0].display_version == "unknown"

        # Replace file with valid jar containing version 2.5.0
        await _drop_real_jar(server_dir, "HealPlugin.jar", "2.5.0")

        # Run reconcile again - should self-heal existing row
        res2 = await handler.handle(ReconcilePluginsCommand(server_id="rec-heal"))
        assert res2.success is True
        assert res2.data["added"] == []

        async with database.session_factory() as session:
            repo = SQLPluginRepository(session)
            plugins = await repo.list_all_by_server(ServerId("rec-heal"))
            assert len(plugins) == 1
            assert plugins[0].display_version == "2.5.0"

    @pytest.mark.asyncio
    async def test_preserves_already_versioned_row(
        self, event_bus: EventBus, tmp_path
    ) -> None:
        server_dir = str(tmp_path / "rec-known")
        await _create_server("rec-known", server_dir)
        await _seed_plugin_row("rec-known-1", "rec-known", "KnownPlugin.jar")
        # Put real jar with different version on disk
        await _drop_real_jar(server_dir, "KnownPlugin.jar", "9.9.9")

        handler = ReconcilePluginsHandler(event_bus)
        res = await handler.handle(ReconcilePluginsCommand(server_id="rec-known"))
        assert res.success is True

        async with database.session_factory() as session:
            repo = SQLPluginRepository(session)
            plugins = await repo.list_all_by_server(ServerId("rec-known"))
            assert len(plugins) == 1
            assert plugins[0].display_version == "1.0.0"

