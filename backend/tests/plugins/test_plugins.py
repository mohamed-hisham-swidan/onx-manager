from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

import pytest

from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.exceptions import InvalidJarError, InvalidValueError
from app.core.persistence.db import database
from app.modules.plugin.application.commands.disable_plugin import (
    DisablePluginCommand,
    DisablePluginHandler,
)
from app.modules.plugin.application.commands.enable_plugin import (
    EnablePluginCommand,
    EnablePluginHandler,
)
from app.modules.plugin.application.commands.reconcile_plugins import (
    ReconcilePluginsCommand,
    ReconcilePluginsHandler,
)
from app.modules.plugin.application.commands.toggle_mod_state import (
    ToggleModStateCommand,
    ToggleModStateHandler,
)
from app.modules.plugin.application.commands.uninstall_plugin import (
    UninstallPluginCommand,
    UninstallPluginHandler,
)
from app.modules.plugin.application.commands.upload_mod import (
    UploadModCommand,
    UploadModHandler,
)
from app.modules.plugin.application.queries.get_plugin import (
    GetPluginHandler,
    GetPluginQuery,
)
from app.modules.plugin.application.queries.list_plugins import (
    ListPluginsHandler,
    ListPluginsQuery,
)
from app.modules.plugin.application.services.plugin_deletion_service import (
    consume_pending_plugin_deletions,
)
from app.modules.plugin.domain.aggregate import (
    DependencyStatus,
    Plugin,
    PluginRegistry,
    PluginStatus,
)
from app.modules.plugin.domain.events import (
    PluginDisabledEvent,
    PluginEnabledEvent,
    PluginInstalledEvent,
    PluginUninstalledEvent,
    PluginUpdatedEvent,
)
from app.modules.plugin.infrastructure.addon_fs import (
    get_addon_dir_name,
    is_mod_server,
    sanitize_addon_filename,
    toggle_addon_file,
)
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
from app.modules.server.infrastructure.fs import LocalFileSystem
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import (
    MinecraftVersion,
    PluginId,
    PluginVersion,
    ServerId,
)


def _create_jar_bytes(files: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for fname, content in files.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            zf.writestr(fname, data)
    return buf.getvalue()


async def _create_server(
    server_id: str,
    root_path: str,
    server_type: ServerType = ServerType.PAPER,
) -> Server:
    deployment = ServerDeployment(
        location_type=LocationType.LOCAL,
        root_path=root_path,
        working_directory=".",
    )
    server = Server.create(
        server_id=ServerId(server_id),
        name=f"Server {server_id}",
        server_type=server_type,
        minecraft_version=MinecraftVersion.parse("1.21"),
        memory=MemoryAllocation(1024, 2048),
        java_args=JavaArguments(),
        properties=ServerProperties(port=PortNumber(25565)),
        deployment=deployment,
    )
    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        await repo.save(server)
        await session.commit()
    return server


async def _seed_plugin(
    plugin_id: str,
    server_id: str,
    name: str = "TestPlugin",
    *,
    filename: str | None = None,
    source: str = "detected",
    enabled: bool = False,
    pending_deletion: bool = False,
) -> Plugin:
    async with database.session_factory() as session:
        repo = SQLPluginRepository(session)
        plugin = Plugin.install(
            plugin_id=PluginId(plugin_id),
            server_id=ServerId(server_id),
            name=name,
            version=PluginVersion.parse("1.0.0"),
            filename=filename,
            source=source,
        )
        if enabled:
            plugin.enable()
        if pending_deletion:
            plugin.request_deletion()
        plugin.collect_events()
        await repo.save(plugin)
        await session.commit()
        return plugin


class _FailDeleteFS(LocalFileSystem):
    def delete(self, _path: str) -> None:
        raise OSError("simulated locked file")


class TestPluginAggregate:
    @pytest.fixture
    def sample_plugin(self) -> Plugin:
        return Plugin.install(
            plugin_id=PluginId("essentialsx"),
            server_id=ServerId("s1"),
            name="EssentialsX",
            version=PluginVersion.parse("2.20.0"),
            description="Essential commands",
            author="Essentials Team",
        )

    def test_install_emits_event_and_sets_initial_status(self, sample_plugin: Plugin) -> None:
        events = sample_plugin.collect_events()
        assert len(events) == 1
        assert isinstance(events[0], PluginInstalledEvent)
        assert events[0].version == "2.20.0"
        assert sample_plugin.status == PluginStatus.INSTALLED

    def test_enable_and_disable_transitions_and_idempotency(self, sample_plugin: Plugin) -> None:
        sample_plugin.collect_events()
        sample_plugin.enable()
        assert sample_plugin.status == PluginStatus.ENABLED
        assert any(isinstance(e, PluginEnabledEvent) for e in sample_plugin.collect_events())

        # Redundant enable is a noop
        sample_plugin.enable()
        assert sample_plugin.status == PluginStatus.ENABLED
        assert sample_plugin.collect_events() == []

        sample_plugin.disable()
        assert sample_plugin.status == PluginStatus.DISABLED
        assert any(isinstance(e, PluginDisabledEvent) for e in sample_plugin.collect_events())

        # Redundant disable is a noop
        sample_plugin.disable()
        assert sample_plugin.status == PluginStatus.DISABLED
        assert sample_plugin.collect_events() == []

    def test_disable_from_installed(self, sample_plugin: Plugin) -> None:
        sample_plugin.disable()
        assert sample_plugin.status == PluginStatus.DISABLED

    def test_mark_error_requires_enabled(self, sample_plugin: Plugin) -> None:
        with pytest.raises(InvalidValueError):
            sample_plugin.mark_error()

        sample_plugin.enable()
        sample_plugin.mark_error()
        assert sample_plugin.status == PluginStatus.ERROR

    def test_update_version_and_uninstall_events(self, sample_plugin: Plugin) -> None:
        sample_plugin.collect_events()
        new_version = PluginVersion.parse("2.21.0")
        sample_plugin.update_version(new_version)
        assert sample_plugin.version == new_version
        assert any(isinstance(e, PluginUpdatedEvent) for e in sample_plugin.collect_events())

        sample_plugin.mark_uninstalled()
        assert any(isinstance(e, PluginUninstalledEvent) for e in sample_plugin.collect_events())

    def test_dependencies_preserved(self) -> None:
        plugin = Plugin.install(
            plugin_id=PluginId("vault"),
            server_id=ServerId("s1"),
            name="Vault",
            version=PluginVersion.parse("1.7.3"),
            dependencies=["EssentialsX"],
        )
        assert plugin.dependencies == ["EssentialsX"]


class TestPluginRegistry:
    @pytest.fixture
    def registry(self) -> PluginRegistry:
        return PluginRegistry(server_id=ServerId("s1"))

    def test_add_get_remove_plugin(self, registry: PluginRegistry) -> None:
        assert len(registry.plugins) == 0
        plugin = Plugin.install(
            plugin_id=PluginId("p1"),
            server_id=ServerId("s1"),
            name="TestPlugin",
            version=PluginVersion.parse("1.0.0"),
        )
        registry.add_plugin(plugin)
        assert registry.get_plugin(PluginId("p1")) is not None
        assert registry.get_by_name("TestPlugin") is not None
        assert registry.get_by_name("Missing") is None

        registry.remove_plugin(PluginId("p1"))
        assert registry.get_plugin(PluginId("p1")) is None

    def test_dependency_checks_and_circular_detection(self, registry: PluginRegistry) -> None:
        missing = Plugin.install(
            plugin_id=PluginId("p1"),
            server_id=ServerId("s1"),
            name="NeedsDep",
            version=PluginVersion.parse("1.0.0"),
            dependencies=["MissingDep"],
        )
        registry.add_plugin(missing)
        assert registry.check_dependencies(missing)["MissingDep"] == DependencyStatus.MISSING
        assert registry.can_enable(missing) is False

        dep = Plugin.install(
            plugin_id=PluginId("dep1"),
            server_id=ServerId("s1"),
            name="BaseLib",
            version=PluginVersion.parse("1.0.0"),
        )
        dep.enable()
        registry.add_plugin(dep)
        satisfied = Plugin.install(
            plugin_id=PluginId("p2"),
            server_id=ServerId("s1"),
            name="MainPlugin",
            version=PluginVersion.parse("1.0.0"),
            dependencies=["BaseLib"],
        )
        registry.add_plugin(satisfied)
        assert registry.check_dependencies(satisfied)["BaseLib"] == DependencyStatus.SATISFIED
        assert registry.can_enable(satisfied) is True

        a = Plugin.install(
            plugin_id=PluginId("a"),
            server_id=ServerId("s1"),
            name="PluginA",
            version=PluginVersion.parse("1.0.0"),
            dependencies=["PluginB"],
        )
        b = Plugin.install(
            plugin_id=PluginId("b"),
            server_id=ServerId("s1"),
            name="PluginB",
            version=PluginVersion.parse("1.0.0"),
            dependencies=["PluginA"],
        )
        a.enable()
        b.enable()
        registry.add_plugin(a)
        registry.add_plugin(b)
        assert DependencyStatus.CIRCULAR in registry.check_dependencies(a).values()

    def test_registry_ignores_platform_runtime_deps_and_matches_mod_id(
        self, registry: PluginRegistry
    ) -> None:
        dep = Plugin.install(
            plugin_id=PluginId(),
            server_id=ServerId("s1"),
            name="Fabric API",
            version=PluginVersion(1, 0, 0),
            mod_id="fabric-api",
        )
        dep._status = PluginStatus.ENABLED
        mod = Plugin.install(
            plugin_id=PluginId(),
            server_id=ServerId("s1"),
            name="CoolMod",
            version=PluginVersion(1, 0, 0),
            dependencies=["minecraft", "java", "fabricloader", "fabric-api"],
        )
        registry.add_plugin(dep)
        registry.add_plugin(mod)
        assert registry.can_enable(mod) is True


class TestAddonFilesystem:
    def test_addon_dir_and_mod_server_classification(self) -> None:
        for mod_loader in ("fabric", "forge", "neoforge", "quilt"):
            assert get_addon_dir_name(mod_loader) == "mods"
            assert is_mod_server(mod_loader) is True
        for plugin_loader in ("paper", "purpur", "spigot", "bukkit", "vanilla", None):
            assert get_addon_dir_name(plugin_loader) == "plugins"
            assert is_mod_server(plugin_loader) is False

    def test_sanitize_addon_filename_strips_traversal_and_rejects_bad_extensions(
        self, tmp_path: Path
    ) -> None:
        assert (
            sanitize_addon_filename("test-mod-1.0.jar", tmp_path) == tmp_path / "test-mod-1.0.jar"
        )
        assert sanitize_addon_filename("../../test.jar", tmp_path) == tmp_path / "test.jar"

        with pytest.raises(InvalidValueError) as exc:
            sanitize_addon_filename("malicious.sh", tmp_path)
        assert exc.value.details["field"] == "filename"

        for bad_name in ("", "evil.jar\x00.exe"):
            with pytest.raises(InvalidValueError):
                sanitize_addon_filename(bad_name, tmp_path)

    def test_toggle_addon_file_is_idempotent_and_rejects_missing(self, tmp_path: Path) -> None:
        mod_file = tmp_path / "my-mod.jar"
        mod_file.write_bytes(b"dummy")

        disabled_path, renamed = toggle_addon_file(tmp_path, "my-mod.jar", enabled=False)
        assert renamed is True
        assert disabled_path == tmp_path / "my-mod.jar.disabled"
        assert not mod_file.exists() and disabled_path.exists()

        disabled_again, renamed2 = toggle_addon_file(tmp_path, "my-mod.jar", enabled=False)
        assert renamed2 is False
        assert disabled_again == disabled_path

        active_path, renamed3 = toggle_addon_file(tmp_path, "my-mod.jar.disabled", enabled=True)
        assert renamed3 is True
        assert active_path == mod_file
        assert mod_file.exists() and not disabled_path.exists()

        active_again, renamed4 = toggle_addon_file(tmp_path, "my-mod.jar", enabled=True)
        assert renamed4 is False
        assert active_again == mod_file

        with pytest.raises(FileNotFoundError):
            toggle_addon_file(tmp_path, "nonexistent.jar", enabled=False)
        with pytest.raises(FileNotFoundError):
            toggle_addon_file(tmp_path, "nonexistent.jar", enabled=True)


class TestPluginCommandsAndQueries:
    async def test_uninstall_marks_pending_deletion_and_missing_fails(
        self, event_bus: EventBus
    ) -> None:
        await _seed_plugin("uninst-1", "srv-1", "ToUninstall", filename="ToUninstall.jar")

        result = await UninstallPluginHandler(event_bus).handle(
            UninstallPluginCommand(plugin_id="uninst-1")
        )
        assert result.success is True
        assert result.data["pending_deletion"] is True

        async with database.session_factory() as session:
            plugin = await SQLPluginRepository(session).get(PluginId("uninst-1"))
            assert plugin.pending_deletion is True
            assert plugin.pending_deletion_requested_at is not None
            assert plugin.filename == "ToUninstall.jar"

        bus = CommandBus()
        bus.register(UninstallPluginCommand, UninstallPluginHandler(event_bus))
        missing = await bus.send(UninstallPluginCommand(plugin_id="nonexistent"))
        assert missing.success is False

    async def test_enable_and_disable_handlers(self, event_bus: EventBus) -> None:
        await _seed_plugin("enable-1", "srv-1", "ToEnable")
        await _seed_plugin("disable-1", "srv-1", "ToDisable", enabled=True)

        assert (
            await EnablePluginHandler(event_bus).handle(EnablePluginCommand(plugin_id="enable-1"))
        ).success is True
        assert (
            await DisablePluginHandler(event_bus).handle(
                DisablePluginCommand(plugin_id="disable-1")
            )
        ).success is True

        bus = CommandBus()
        bus.register(EnablePluginCommand, EnablePluginHandler(event_bus))
        bus.register(DisablePluginCommand, DisablePluginHandler(event_bus))
        assert (await bus.send(EnablePluginCommand(plugin_id="missing"))).success is False
        assert (await bus.send(DisablePluginCommand(plugin_id="missing"))).success is False

    async def test_get_and_list_plugin_queries(self) -> None:
        await _seed_plugin("get-plg-1", "srv-q1", "GetPlugin")
        for i in range(3):
            await _seed_plugin(f"list-plg-{i}", "srv-q2", f"Plugin-{i}")

        got = await GetPluginHandler().handle(GetPluginQuery(plugin_id="get-plg-1"))
        assert got is not None
        assert got.name == "GetPlugin"

        listed = await ListPluginsHandler().handle(ListPluginsQuery(server_id="srv-q2"))
        assert len(listed) == 3


class TestPendingPluginDeletions:
    async def test_consume_pending_deletions_covers_noop_hit_missing_locked_and_no_filename(
        self, tmp_path: Path
    ) -> None:
        # 1. No pending deletions
        assert await consume_pending_plugin_deletions("del-none", str(tmp_path / "del-none")) == []

        # 2. Deletes file on disk and clears DB row
        hit_dir = tmp_path / "del-hit"
        (hit_dir / "plugins").mkdir(parents=True)
        jar_path = hit_dir / "plugins" / "Old.jar"
        jar_path.write_bytes(b"PK\x03\x04fake-jar")
        await _seed_plugin("del-hit-1", "del-hit", "Old", filename="Old.jar", pending_deletion=True)

        res_hit = await consume_pending_plugin_deletions("del-hit", str(hit_dir))
        assert res_hit == [
            {"plugin_id": "del-hit-1", "filename": "Old.jar", "deleted": True, "error": None}
        ]
        assert not jar_path.exists()
        async with database.session_factory() as session:
            assert await SQLPluginRepository(session).list_all_by_server(ServerId("del-hit")) == []

        # 3. Missing file on disk still removes DB row
        await _seed_plugin(
            "del-absent-1", "del-absent", "Gone", filename="Gone.jar", pending_deletion=True
        )
        res_absent = await consume_pending_plugin_deletions(
            "del-absent", str(tmp_path / "del-absent")
        )
        assert res_absent[0]["deleted"] is True

        # 4. OSError keeps pending row intact
        locked_dir = tmp_path / "del-locked"
        (locked_dir / "plugins").mkdir(parents=True)
        locked_jar = locked_dir / "plugins" / "Locked.jar"
        locked_jar.write_bytes(b"PK\x03\x04fake-jar")
        await _seed_plugin(
            "del-locked-1", "del-locked", "Locked", filename="Locked.jar", pending_deletion=True
        )
        res_locked = await consume_pending_plugin_deletions(
            "del-locked", str(locked_dir), fs=_FailDeleteFS()
        )
        assert res_locked[0]["deleted"] is False
        assert res_locked[0]["error"] == "simulated locked file"
        assert locked_jar.exists()
        async with database.session_factory() as session:
            rows = await SQLPluginRepository(session).list_all_by_server(ServerId("del-locked"))
            assert len(rows) == 1 and rows[0].pending_deletion is True

        # 5. Row without filename is cleared
        await _seed_plugin(
            "del-nofname-1", "del-nofname", "NoFname", filename=None, pending_deletion=True
        )
        res_nofname = await consume_pending_plugin_deletions(
            "del-nofname", str(tmp_path / "del-nofname")
        )
        assert res_nofname[0]["deleted"] is True


class TestReconcilePlugins:
    async def test_no_deployment_noop(self, event_bus: EventBus, tmp_path: Path) -> None:
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

        res = await ReconcilePluginsHandler(event_bus).handle(
            ReconcilePluginsCommand(server_id="rec-nodeploy")
        )
        assert res.success is True
        assert res.data["added"] == [] and res.data["removed"] == []

    async def test_detects_ignores_non_jar_and_removes_deleted(
        self, event_bus: EventBus, tmp_path: Path
    ) -> None:
        srv_dir = tmp_path / "rec-det"
        plugins_dir = srv_dir / "plugins"
        plugins_dir.mkdir(parents=True)
        (plugins_dir / "MyPlugin.jar").write_bytes(b"PK\x03\x04fake-jar")
        (plugins_dir / "readme.txt").write_bytes(b"ignore")
        await _create_server("rec-det", str(srv_dir))

        handler = ReconcilePluginsHandler(event_bus)
        first = await handler.handle(ReconcilePluginsCommand(server_id="rec-det"))
        assert first.data["added"] == ["MyPlugin.jar"]
        assert first.data["removed"] == []

        second = await handler.handle(ReconcilePluginsCommand(server_id="rec-det"))
        assert second.data["added"] == [] and second.data["removed"] == []

        os.unlink(plugins_dir / "MyPlugin.jar")
        removed = await handler.handle(ReconcilePluginsCommand(server_id="rec-det"))
        assert removed.data["removed"] == ["MyPlugin.jar"]
        async with database.session_factory() as session:
            assert await SQLPluginRepository(session).list_all_by_server(ServerId("rec-det")) == []

    async def test_preserves_pending_deletion_and_no_filename_rows(
        self, event_bus: EventBus, tmp_path: Path
    ) -> None:
        srv_dir = tmp_path / "rec-preserve"
        await _create_server("rec-preserve", str(srv_dir))
        await _seed_plugin(
            "rec-pend-1", "rec-preserve", "Gone", filename="Gone.jar", pending_deletion=True
        )
        await _seed_plugin("rec-nofn-1", "rec-preserve", "NoFile", filename=None)

        res = await ReconcilePluginsHandler(event_bus).handle(
            ReconcilePluginsCommand(server_id="rec-preserve")
        )
        assert res.success is True
        assert res.data["removed"] == []
        async with database.session_factory() as session:
            plugins = await SQLPluginRepository(session).list_all_by_server(
                ServerId("rec-preserve")
            )
            assert len(plugins) == 2

    async def test_parses_jar_version_self_heals_and_preserves_known(
        self, event_bus: EventBus, tmp_path: Path
    ) -> None:
        srv_dir = tmp_path / "rec-heal"
        plugins_dir = srv_dir / "plugins"
        plugins_dir.mkdir(parents=True)
        await _create_server("rec-heal", str(srv_dir))

        # Unknown jar first, then replaced with real descriptor -> self-heals
        (plugins_dir / "HealPlugin.jar").write_bytes(b"PK\x03\x04fake-jar")
        handler = ReconcilePluginsHandler(event_bus)
        await handler.handle(ReconcilePluginsCommand(server_id="rec-heal"))

        (plugins_dir / "HealPlugin.jar").write_bytes(
            _create_jar_bytes({"plugin.yml": "name: HealPlugin\nversion: 2.5.0\n"})
        )
        # Known versioned row should NOT be overwritten by JAR version
        await _seed_plugin("rec-known-1", "rec-heal", "KnownPlugin", filename="KnownPlugin.jar")
        (plugins_dir / "KnownPlugin.jar").write_bytes(
            _create_jar_bytes({"plugin.yml": "name: KnownPlugin\nversion: 9.9.9\n"})
        )

        res = await handler.handle(ReconcilePluginsCommand(server_id="rec-heal"))
        assert res.success is True
        async with database.session_factory() as session:
            by_file = {
                p.filename: p
                for p in await SQLPluginRepository(session).list_all_by_server(ServerId("rec-heal"))
            }
            assert by_file["HealPlugin.jar"].display_version == "2.5.0"
            assert by_file["KnownPlugin.jar"].display_version == "1.0.0"


class TestCustomModSupport:
    async def test_upload_mod_to_fabric_server_and_rejects_invalid_jar(
        self, event_bus: EventBus, tmp_path: Path
    ) -> None:
        srv_dir = tmp_path / "srv-fab-upload"
        srv_dir.mkdir(parents=True)
        await _create_server("srv-fab-upload", str(srv_dir), ServerType.FABRIC)

        jar_bytes = _create_jar_bytes(
            {
                "fabric.mod.json": (
                    '{"id": "sodium", "name": "Sodium", "version": "0.5.8", '
                    '"environment": "client", "authors": ["jellysquid3"]}'
                )
            }
        )
        handler = UploadModHandler(event_bus)
        res = await handler.handle(
            UploadModCommand(
                server_id="srv-fab-upload",
                filename="sodium-fabric-mc1.20.4-0.5.8.jar",
                file_content=jar_bytes,
            )
        )
        assert res.success is True
        assert res.data["name"] == "Sodium"
        assert res.data["version"] == "0.5.8"
        assert res.data["loader"] == "fabric"
        assert res.data["is_client_only"] is True
        assert "Client-only mod detected" in res.data["warning"]
        assert (srv_dir / "mods" / "sodium-fabric-mc1.20.4-0.5.8.jar").exists()

        with pytest.raises(InvalidJarError):
            await handler.handle(
                UploadModCommand(
                    server_id="srv-fab-upload",
                    filename="malicious.jar",
                    file_content=b"not a zip",
                )
            )

    async def test_toggle_mod_state_renames_on_disk(
        self, event_bus: EventBus, tmp_path: Path
    ) -> None:
        srv_dir = tmp_path / "srv-fab-tog"
        mods_dir = srv_dir / "mods"
        mods_dir.mkdir(parents=True)
        await _create_server("srv-fab-toggle", str(srv_dir), ServerType.FABRIC)

        up_res = await UploadModHandler(event_bus).handle(
            UploadModCommand(
                server_id="srv-fab-toggle",
                filename="testmod.jar",
                file_content=_create_jar_bytes(
                    {"fabric.mod.json": '{"id": "testmod", "name": "Test Mod", "version": "1.0.0"}'}
                ),
            )
        )
        plugin_id = up_res.data["plugin_id"]
        toggle_handler = ToggleModStateHandler(event_bus)

        dis_res = await toggle_handler.handle(
            ToggleModStateCommand(server_id="srv-fab-toggle", plugin_id=plugin_id, enabled=False)
        )
        assert dis_res.data["enabled"] is False
        assert dis_res.data["is_disabled_on_disk"] is True
        assert not (mods_dir / "testmod.jar").exists()
        assert (mods_dir / "testmod.jar.disabled").exists()

        en_res = await toggle_handler.handle(
            ToggleModStateCommand(server_id="srv-fab-toggle", plugin_id=plugin_id, enabled=True)
        )
        assert en_res.data["enabled"] is True
        assert en_res.data["is_disabled_on_disk"] is False
        assert (mods_dir / "testmod.jar").exists()
        assert not (mods_dir / "testmod.jar.disabled").exists()

    async def test_reconcile_mods_directory_tracks_active_and_disabled(
        self, event_bus: EventBus, tmp_path: Path
    ) -> None:
        srv_dir = tmp_path / "srv-fab-rec"
        mods_dir = srv_dir / "mods"
        mods_dir.mkdir(parents=True)
        await _create_server("srv-fab-rec", str(srv_dir), ServerType.FABRIC)

        (mods_dir / "active.jar").write_bytes(
            _create_jar_bytes(
                {"fabric.mod.json": '{"id": "activemod", "name": "Active Mod", "version": "2.0.0"}'}
            )
        )
        (mods_dir / "disabled.jar.disabled").write_bytes(
            _create_jar_bytes(
                {"fabric.mod.json": '{"id": "offmod", "name": "Off Mod", "version": "1.5.0"}'}
            )
        )

        res = await ReconcilePluginsHandler(event_bus).handle(
            ReconcilePluginsCommand(server_id="srv-fab-rec")
        )
        assert "active.jar" in res.data["added"]
        assert "disabled.jar" in res.data["added"]

        async with database.session_factory() as session:
            p_map = {
                p.filename: p
                for p in await SQLPluginRepository(session).list_all_by_server(
                    ServerId("srv-fab-rec")
                )
            }
            assert p_map["active.jar"].is_disabled_on_disk is False
            assert p_map["active.jar"].project_type == "mod"
            assert p_map["active.jar"].loader == "fabric"
            assert p_map["disabled.jar"].is_disabled_on_disk is True
            assert p_map["disabled.jar"].status == PluginStatus.DISABLED
            assert p_map["disabled.jar"].project_type == "mod"
