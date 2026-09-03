import pytest

from app.core.event_bus import EventBus
from app.core.persistence.db import database
from app.modules.plugin.application.commands.install_modrinth_plugin import (
    InstallModrinthPluginCommand,
    InstallModrinthPluginHandler,
)
from app.modules.plugin.infrastructure.providers.base import (
    PluginFile,
    PluginVersionInfo,
    PluginVersionsPage,
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
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import MinecraftVersion, PluginId, ServerId


def _version(
    version_number: str = "2.21.0",
    filename: str = "EssentialsX.jar",
) -> PluginVersionInfo:
    return PluginVersionInfo(
        version_id="ver-1",
        project_id="proj-1",
        name="EssentialsX",
        version_number=version_number,
        game_versions=["1.21"],
        loaders=["paper"],
        files=[
            PluginFile(
                url="https://cdn.modrinth.com/data/proj-1/ver-1/EssentialsX.jar",
                filename=filename,
                size_bytes=1024,
                sha1="deadbeef",
                primary=True,
            ),
        ],
        date_published="2025-01-01T00:00:00Z",
    )


class _FakeProvider:
    name = "modrinth"

    def __init__(self, version: PluginVersionInfo | None = None) -> None:
        self._version = version
        self.downloaded_url: str | None = None

    async def get_project_versions(
        self,
        _project_id: str,
        **kwargs: object,  # noqa: ARG002
    ) -> PluginVersionsPage:
        return PluginVersionsPage(
            items=[self._version] if self._version else [],
            total=1 if self._version else 0,
        )

    async def get_version(self, _version_id: str) -> PluginVersionInfo:
        return self._version

    async def download(
        self,
        url: str,
        expected_sha1: str | None = None,  # noqa: ARG002
        expected_sha512: str | None = None,  # noqa: ARG002
    ) -> bytes:
        self.downloaded_url = url
        return b"PK\x03\x04fake-jar-content"


async def _create_server(
    server_id: str, root_path: str, server_type: ServerType = ServerType.PAPER
) -> None:
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
            server_type=server_type,
            minecraft_version=MinecraftVersion.parse("1.21"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25565)),
            deployment=deployment,
        )
        await repo.save(server)
        await session.commit()


@pytest.mark.usefixtures("init_test_db")
class TestInstallModrinthPluginHandler:
    @pytest.mark.asyncio
    async def test_install_modrinth_plugin(self, event_bus: EventBus, tmp_path) -> None:
        await _create_server("srv-modrinth-1", str(tmp_path / "srv-modrinth-1"))
        provider = _FakeProvider(_version())
        handler = InstallModrinthPluginHandler(event_bus, provider=provider)

        result = await handler.handle(
            InstallModrinthPluginCommand(server_id="srv-modrinth-1", project_id="proj-1")
        )

        assert result.success is True
        assert result.data["source"] == "modrinth"
        assert result.data["filename"] == "EssentialsX.jar"
        assert provider.downloaded_url is not None

        async with database.session_factory() as session:
            repo = SQLPluginRepository(session)
            plugin = await repo.get(PluginId(result.data["plugin_id"]))
            assert plugin.source == "modrinth"
            assert plugin.external_project_id == "proj-1"
            assert plugin.external_version_id == "ver-1"
            assert plugin.checksum == "deadbeef"
            assert plugin.display_version == "2.21.0"

    @pytest.mark.asyncio
    async def test_install_non_semver_version_stores_raw(
        self, event_bus: EventBus, tmp_path
    ) -> None:
        await _create_server("srv-modrinth-raw", str(tmp_path / "srv-modrinth-raw"))
        provider = _FakeProvider(_version(version_number="v2.21-RC1"))
        handler = InstallModrinthPluginHandler(event_bus, provider=provider)

        result = await handler.handle(
            InstallModrinthPluginCommand(server_id="srv-modrinth-raw", project_id="proj-1")
        )

        assert result.success is True
        async with database.session_factory() as session:
            repo = SQLPluginRepository(session)
            plugin = await repo.get(PluginId(result.data["plugin_id"]))
            assert plugin.display_version == "v2.21-RC1"

    @pytest.mark.asyncio
    async def test_no_deployment_rejected(self, event_bus: EventBus, tmp_path) -> None:
        await _create_server("srv-modrinth-nodeploy", str(tmp_path / "srv-modrinth-nodeploy"))
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            server = await repo.get(ServerId("srv-modrinth-nodeploy"))
            server.update_deployment(
                ServerDeployment(
                    location_type=LocationType.LOCAL,
                    root_path="",
                    working_directory=".",
                )
            )
            await repo.save(server)
            await session.commit()

        handler = InstallModrinthPluginHandler(event_bus, provider=_FakeProvider(_version()))
        result = await handler.handle(
            InstallModrinthPluginCommand(server_id="srv-modrinth-nodeploy", project_id="proj-1")
        )
        assert result.success is False
        assert result.error_code == "NO_DEPLOYMENT"

    @pytest.mark.asyncio
    async def test_unsupported_server_type_rejected(self, event_bus: EventBus, tmp_path) -> None:
        await _create_server(
            "srv-modrinth-vanilla",
            str(tmp_path / "srv-modrinth-vanilla"),
            server_type=ServerType.VANILLA,
        )
        handler = InstallModrinthPluginHandler(event_bus, provider=_FakeProvider(_version()))
        result = await handler.handle(
            InstallModrinthPluginCommand(server_id="srv-modrinth-vanilla", project_id="proj-1")
        )
        assert result.success is False
        assert result.error_code == "PLUGINS_UNSUPPORTED"

    @pytest.mark.asyncio
    async def test_no_compatible_version_rejected(self, event_bus: EventBus, tmp_path) -> None:
        await _create_server("srv-modrinth-nover", str(tmp_path / "srv-modrinth-nover"))
        provider = _FakeProvider(None)
        handler = InstallModrinthPluginHandler(event_bus, provider=provider)
        result = await handler.handle(
            InstallModrinthPluginCommand(server_id="srv-modrinth-nover", project_id="proj-1")
        )
        assert result.success is False
        assert result.error_code == "NO_COMPATIBLE_VERSION"

    @pytest.mark.asyncio
    async def test_malicious_filename_path_traversal_rejected(
        self, event_bus: EventBus, tmp_path
    ) -> None:
        await _create_server("srv-modrinth-evil", str(tmp_path / "srv-modrinth-evil"))
        provider = _FakeProvider(_version(filename="../../../etc/evil.jar"))
        handler = InstallModrinthPluginHandler(event_bus, provider=provider)

        result = await handler.handle(
            InstallModrinthPluginCommand(
                server_id="srv-modrinth-evil",
                project_id="proj-1",
            )
        )
        assert result.success is False
        assert result.error_code == "INVALID_FILENAME"
        assert "path traversal" in result.error.lower()
