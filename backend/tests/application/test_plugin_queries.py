import pytest

from app.core.persistence.db import database
from app.modules.plugin.application.queries.get_plugin import (
    GetPluginHandler,
    GetPluginQuery,
)
from app.modules.plugin.application.queries.list_plugins import (
    ListPluginsHandler,
    ListPluginsQuery,
)
from app.modules.plugin.domain.aggregate import Plugin
from app.modules.plugin.infrastructure.repository import SQLPluginRepository
from app.modules.shared.value_objects import PluginId, PluginVersion, ServerId


@pytest.mark.usefixtures("init_test_db")
class TestGetPluginHandler:
    @pytest.mark.asyncio
    async def test_get_plugin(self) -> None:
        async with database.session_factory() as session:
            repo = SQLPluginRepository(session)
            plugin = Plugin.install(
                plugin_id=PluginId("get-plg-1"),
                server_id=ServerId("srv-1"),
                name="GetPlugin",
                version=PluginVersion.parse("1.0.0"),
            )
            plugin.collect_events()
            await repo.save(plugin)
            await session.commit()

        handler = GetPluginHandler()
        result = await handler.handle(GetPluginQuery(plugin_id="get-plg-1"))

        assert result is not None
        assert result.name == "GetPlugin"


@pytest.mark.usefixtures("init_test_db")
class TestListPluginsHandler:
    @pytest.mark.asyncio
    async def test_list_by_server(self) -> None:
        async with database.session_factory() as session:
            repo = SQLPluginRepository(session)
            for i in range(3):
                plugin = Plugin.install(
                    plugin_id=PluginId(f"list-plg-{i}"),
                    server_id=ServerId("srv-1"),
                    name=f"Plugin-{i}",
                    version=PluginVersion.parse("1.0.0"),
                )
                plugin.collect_events()
                await repo.save(plugin)
            await session.commit()

        handler = ListPluginsHandler()
        result = await handler.handle(ListPluginsQuery(server_id="srv-1"))

        assert len(result) == 3
