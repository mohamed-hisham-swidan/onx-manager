import pytest

from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.persistence.db import database
from app.modules.plugin.application.commands.disable_plugin import (
    DisablePluginCommand,
    DisablePluginHandler,
)
from app.modules.plugin.application.commands.enable_plugin import (
    EnablePluginCommand,
    EnablePluginHandler,
)
from app.modules.plugin.application.commands.uninstall_plugin import (
    UninstallPluginCommand,
    UninstallPluginHandler,
)
from app.modules.plugin.domain.aggregate import Plugin
from app.modules.plugin.infrastructure.repository import SQLPluginRepository
from app.modules.shared.value_objects import PluginId, PluginVersion, ServerId


def _bus(event_bus: EventBus) -> CommandBus:
    return CommandBus()


@pytest.mark.usefixtures("init_test_db")
class TestUninstallPluginHandler:
    @pytest.mark.asyncio
    async def test_uninstall_marks_pending_deletion(self, event_bus: EventBus) -> None:
        async with database.session_factory() as session:
            repo = SQLPluginRepository(session)
            plugin = Plugin.install(
                plugin_id=PluginId("uninst-1"),
                server_id=ServerId("srv-1"),
                name="ToUninstall",
                version=PluginVersion.parse("1.0.0"),
                filename="ToUninstall.jar",
            )
            plugin.collect_events()
            await repo.save(plugin)
            await session.commit()

        handler = UninstallPluginHandler(event_bus)
        result = await handler.handle(UninstallPluginCommand(plugin_id="uninst-1"))

        assert result.success is True
        assert result.data["pending_deletion"] is True

        async with database.session_factory() as session:
            repo = SQLPluginRepository(session)
            plugin = await repo.get(PluginId("uninst-1"))
            assert plugin.pending_deletion is True
            assert plugin.pending_deletion_requested_at is not None
            assert plugin.filename == "ToUninstall.jar"

    @pytest.mark.asyncio
    async def test_uninstall_nonexistent(self, event_bus: EventBus) -> None:
        bus = _bus(event_bus)
        bus.register(UninstallPluginCommand, UninstallPluginHandler(event_bus))
        result = await bus.send(UninstallPluginCommand(plugin_id="nonexistent"))
        assert result.success is False


@pytest.mark.usefixtures("init_test_db")
class TestEnablePluginHandler:
    @pytest.mark.asyncio
    async def test_enable_plugin(self, event_bus: EventBus) -> None:
        async with database.session_factory() as session:
            repo = SQLPluginRepository(session)
            plugin = Plugin.install(
                plugin_id=PluginId("enable-1"),
                server_id=ServerId("srv-1"),
                name="ToEnable",
                version=PluginVersion.parse("1.0.0"),
            )
            plugin.collect_events()
            await repo.save(plugin)
            await session.commit()

        handler = EnablePluginHandler(event_bus)
        result = await handler.handle(EnablePluginCommand(plugin_id="enable-1"))

        assert result.success is True

    @pytest.mark.asyncio
    async def test_enable_nonexistent(self, event_bus: EventBus) -> None:
        bus = _bus(event_bus)
        bus.register(EnablePluginCommand, EnablePluginHandler(event_bus))
        result = await bus.send(EnablePluginCommand(plugin_id="nonexistent"))
        assert result.success is False


@pytest.mark.usefixtures("init_test_db")
class TestDisablePluginHandler:
    @pytest.mark.asyncio
    async def test_disable_plugin(self, event_bus: EventBus) -> None:
        async with database.session_factory() as session:
            repo = SQLPluginRepository(session)
            plugin = Plugin.install(
                plugin_id=PluginId("disable-1"),
                server_id=ServerId("srv-1"),
                name="ToDisable",
                version=PluginVersion.parse("1.0.0"),
            )
            plugin.collect_events()
            await repo.save(plugin)

            plugin2 = await repo.get(PluginId("disable-1"))
            plugin2.enable()
            await repo.save(plugin2)
            await session.commit()

        handler = DisablePluginHandler(event_bus)
        result = await handler.handle(DisablePluginCommand(plugin_id="disable-1"))

        assert result.success is True

    @pytest.mark.asyncio
    async def test_disable_nonexistent(self, event_bus: EventBus) -> None:
        bus = _bus(event_bus)
        bus.register(DisablePluginCommand, DisablePluginHandler(event_bus))
        result = await bus.send(DisablePluginCommand(plugin_id="nonexistent"))
        assert result.success is False
