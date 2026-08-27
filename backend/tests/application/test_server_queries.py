import pytest

from app.core.persistence.db import database
from app.modules.server.application.queries.get_server import (
    GetServerHandler,
    GetServerQuery,
)
from app.modules.server.application.queries.list_servers import (
    ListServersHandler,
    ListServersQuery,
)
from app.modules.server.application.read_models import resolve_display_name
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
from app.modules.shared.value_objects import MinecraftVersion, ServerId


def _build_server(server_id: str, name: str, root_path: str | None = None) -> Server:
    deployment = None
    if root_path is not None:
        deployment = ServerDeployment(
            location_type=LocationType.LOCAL,
            root_path=root_path,
            working_directory=".",
            startup_jar="server.jar",
        )
    return Server.create(
        server_id=ServerId(server_id),
        name=name,
        server_type=ServerType.VANILLA,
        minecraft_version=MinecraftVersion.parse("1.21"),
        memory=MemoryAllocation(1024, 2048),
        java_args=JavaArguments(),
        properties=ServerProperties(port=PortNumber(25565)),
        deployment=deployment,
    )


@pytest.mark.usefixtures("init_test_db")
class TestGetServerHandler:
    @pytest.mark.asyncio
    async def test_get_existing_server(self) -> None:
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            server = Server.create(
                server_id=ServerId("get-test-1"),
                name="GetTest",
                server_type=ServerType.VANILLA,
                minecraft_version=MinecraftVersion.parse("1.21"),
                memory=MemoryAllocation(1024, 2048),
                java_args=JavaArguments(),
                properties=ServerProperties(port=PortNumber(25565)),
            )
            server.collect_events()
            await repo.save(server)
            await session.commit()

        handler = GetServerHandler()
        result = await handler.handle(GetServerQuery(server_id="get-test-1"))

        assert result is not None
        assert result.name == "GetTest"
        assert result.status == "created"

    @pytest.mark.asyncio
    async def test_get_nonexistent_server(self) -> None:
        handler = GetServerHandler()
        from app.core.exceptions import ServerNotFoundError

        with pytest.raises(ServerNotFoundError):
            await handler.handle(GetServerQuery(server_id="nonexistent"))


@pytest.mark.usefixtures("init_test_db")
class TestListServersHandler:
    @pytest.mark.asyncio
    async def test_list_all_servers(self) -> None:
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            for i in range(3):
                s = Server.create(
                    server_id=ServerId(f"list-{i}"),
                    name=f"Server-{i}",
                    server_type=ServerType.VANILLA,
                    minecraft_version=MinecraftVersion.parse("1.21"),
                    memory=MemoryAllocation(1024, 2048),
                    java_args=JavaArguments(),
                    properties=ServerProperties(port=PortNumber(25565 + i)),
                )
                s.collect_events()
                await repo.save(s)
            await session.commit()

        handler = ListServersHandler()
        result = await handler.handle(ListServersQuery())

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_list_with_filters(self) -> None:
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            s1 = Server.create(
                server_id=ServerId("flt-1"),
                name="Alpha",
                server_type=ServerType.VANILLA,
                minecraft_version=MinecraftVersion.parse("1.21"),
                memory=MemoryAllocation(1024, 2048),
                java_args=JavaArguments(),
                properties=ServerProperties(port=PortNumber(25565)),
            )
            s2 = Server.create(
                server_id=ServerId("flt-2"),
                name="Beta",
                server_type=ServerType.VANILLA,
                minecraft_version=MinecraftVersion.parse("1.20"),
                memory=MemoryAllocation(1024, 2048),
                java_args=JavaArguments(),
                properties=ServerProperties(port=PortNumber(25566)),
            )
            s1.collect_events()
            s2.collect_events()
            await repo.save(s1)
            await repo.save(s2)
            await session.commit()

        handler = ListServersHandler()
        result = await handler.handle(ListServersQuery(name_search="Alpha"))

        assert len(result) == 1
        assert result[0].name == "Alpha"


class TestResolveDisplayName:
    def test_uses_db_name_when_no_deployment(self) -> None:
        server = _build_server("rdn-1", "DbName")
        assert resolve_display_name(server) == "DbName"

    def test_uses_db_name_when_no_server_properties(self, tmp_path) -> None:
        server = _build_server("rdn-2", "DbName", root_path=str(tmp_path))
        assert resolve_display_name(server) == "DbName"

    def test_uses_server_name_from_properties_file(self, tmp_path) -> None:
        (tmp_path / "server.properties").write_text(
            "#Minecraft server properties\nserver-name=OnxMC Test Server\n",
            encoding="utf-8",
        )
        server = _build_server("rdn-3", "DbName", root_path=str(tmp_path))
        assert resolve_display_name(server) == "OnxMC Test Server"

    def test_ignores_empty_server_name_in_properties_file(self, tmp_path) -> None:
        (tmp_path / "server.properties").write_text(
            "#Minecraft server properties\nserver-name=\n",
            encoding="utf-8",
        )
        server = _build_server("rdn-4", "DbName", root_path=str(tmp_path))
        assert resolve_display_name(server) == "DbName"
