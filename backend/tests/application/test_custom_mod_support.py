from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.core.event_bus import EventBus
from app.core.exceptions import InvalidJarError
from app.core.persistence.db import database
from app.modules.plugin.application.commands.install_modrinth_plugin import (
    InstallModrinthPluginCommand,
    InstallModrinthPluginHandler,
)
from app.modules.plugin.application.commands.reconcile_plugins import (
    ReconcilePluginsCommand,
    ReconcilePluginsHandler,
)
from app.modules.plugin.application.commands.toggle_mod_state import (
    ToggleModStateCommand,
    ToggleModStateHandler,
)
from app.modules.plugin.application.commands.upload_mod import (
    UploadModCommand,
    UploadModHandler,
)
from app.modules.plugin.domain.aggregate import PluginStatus
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
from app.modules.shared.value_objects import (
    MinecraftVersion,
    ServerId,
)

pytestmark = pytest.mark.usefixtures("init_test_db")



def _create_jar_bytes(files: dict[str, str | bytes]) -> bytes:
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for fname, content in files.items():
            if isinstance(content, str):
                content = content.encode("utf-8")
            zf.writestr(fname, content)
    return buf.getvalue()


async def _create_test_server(
    server_id: str = "srv-fabric-1",
    server_type: str = "fabric",
    root_path: str = "/data/servers/srv-fabric-1",
) -> Server:
    deployment = ServerDeployment(
        location_type=LocationType.LOCAL,
        root_path=root_path,
        working_directory=".",
    )
    server = Server.create(
        server_id=ServerId(server_id),
        name=f"Fabric Server {server_id}",
        server_type=ServerType(server_type),
        minecraft_version=MinecraftVersion.parse("1.20.4"),
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


@pytest.mark.asyncio
async def test_upload_mod_to_fabric_server(event_bus: EventBus, tmp_path: Path) -> None:
    srv_dir = tmp_path / "srv-fab-upload"
    srv_dir.mkdir(parents=True, exist_ok=True)
    server = await _create_test_server("srv-fab-upload", "fabric", str(srv_dir))

    jar_bytes = _create_jar_bytes(
        {
            "fabric.mod.json": (
                '{"id": "sodium", "name": "Sodium", "version": "0.5.8", '
                '"environment": "client", "authors": ["jellysquid3"]}'
            ),
        },
    )

    handler = UploadModHandler(event_bus)
    cmd = UploadModCommand(
        server_id=str(server.id),
        filename="sodium-fabric-mc1.20.4-0.5.8.jar",
        file_content=jar_bytes,
    )
    result = await handler.handle(cmd)

    assert result.success is True
    assert result.data["name"] == "Sodium"
    assert result.data["version"] == "0.5.8"
    assert result.data["loader"] == "fabric"
    assert result.data["is_client_only"] is True
    assert "Client-only mod detected" in result.data["warning"]

    # Verify file written to mods/ directory
    expected_path = srv_dir / "mods" / "sodium-fabric-mc1.20.4-0.5.8.jar"
    assert expected_path.exists()


@pytest.mark.asyncio
async def test_upload_mod_invalid_jar_raises(event_bus: EventBus, tmp_path: Path) -> None:
    srv_dir = tmp_path / "srv-fab-inv"
    srv_dir.mkdir(parents=True, exist_ok=True)
    server = await _create_test_server("srv-fab-invalid", "fabric", str(srv_dir))

    handler = UploadModHandler(event_bus)
    cmd = UploadModCommand(
        server_id=str(server.id),
        filename="malicious.jar",
        file_content=b"this is not a valid zip archive header",
    )
    with pytest.raises(InvalidJarError):
        await handler.handle(cmd)


@pytest.mark.asyncio
async def test_toggle_mod_state_renames_on_disk(event_bus: EventBus, tmp_path: Path) -> None:
    srv_dir = tmp_path / "srv-fab-tog"
    mods_dir = srv_dir / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    server = await _create_test_server("srv-fab-toggle", "fabric", str(srv_dir))

    # Upload or create plugin record
    upload_handler = UploadModHandler(event_bus)
    jar_bytes = _create_jar_bytes(
        {
            "fabric.mod.json": '{"id": "testmod", "name": "Test Mod", "version": "1.0.0"}',
        },
    )
    up_res = await upload_handler.handle(
        UploadModCommand(
            server_id=str(server.id),
            filename="testmod.jar",
            file_content=jar_bytes,
        ),
    )
    plugin_id = up_res.data["plugin_id"]
    active_path = mods_dir / "testmod.jar"
    disabled_path = mods_dir / "testmod.jar.disabled"

    assert active_path.exists()

    toggle_handler = ToggleModStateHandler(event_bus)

    # 1. Disable mod -> renames to .jar.disabled
    dis_res = await toggle_handler.handle(
        ToggleModStateCommand(
            server_id=str(server.id),
            plugin_id=plugin_id,
            enabled=False,
        ),
    )
    assert dis_res.success is True
    assert dis_res.data["enabled"] is False
    assert dis_res.data["is_disabled_on_disk"] is True
    assert not active_path.exists()
    assert disabled_path.exists()

    # 2. Enable mod -> renames back to .jar
    en_res = await toggle_handler.handle(
        ToggleModStateCommand(
            server_id=str(server.id),
            plugin_id=plugin_id,
            enabled=True,
        ),
    )
    assert en_res.success is True
    assert en_res.data["enabled"] is True
    assert en_res.data["is_disabled_on_disk"] is False
    assert active_path.exists()
    assert not disabled_path.exists()


@pytest.mark.asyncio
async def test_reconcile_mods_directory(event_bus: EventBus, tmp_path: Path) -> None:
    srv_dir = tmp_path / "srv-fab-recon"
    mods_dir = srv_dir / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    server = await _create_test_server("srv-fab-recon", "fabric", str(srv_dir))

    # Write one active mod and one disabled mod
    active_jar = _create_jar_bytes(
        {"fabric.mod.json": '{"id": "activemod", "name": "Active Mod", "version": "2.0.0"}'},
    )
    disabled_jar = _create_jar_bytes(
        {"fabric.mod.json": '{"id": "offmod", "name": "Off Mod", "version": "1.5.0"}'},
    )
    (mods_dir / "active.jar").write_bytes(active_jar)
    (mods_dir / "disabled.jar.disabled").write_bytes(disabled_jar)

    handler = ReconcilePluginsHandler(event_bus)
    res = await handler.handle(ReconcilePluginsCommand(server_id=str(server.id)))
    assert res.success is True
    assert "active.jar" in res.data["added"]
    assert "disabled.jar" in res.data["added"]

    async with database.session_factory() as session:
        repo = SQLPluginRepository(session)
        plugins = await repo.list_all_by_server(server.id)
        p_map = {p.filename: p for p in plugins}

        assert "active.jar" in p_map
        assert p_map["active.jar"].is_disabled_on_disk is False
        assert p_map["active.jar"].project_type == "mod"
        assert p_map["active.jar"].loader == "fabric"

        assert "disabled.jar" in p_map
        assert p_map["disabled.jar"].is_disabled_on_disk is True
        assert p_map["disabled.jar"].status == PluginStatus.DISABLED
        assert p_map["disabled.jar"].project_type == "mod"


class _FakeModProvider:
    name = "modrinth"

    async def get_version(self, version_id: str) -> PluginVersionInfo:
        return PluginVersionInfo(
            version_id=version_id,
            project_id="test-mod",
            name="Test Mod 1.0",
            version_number="1.0.0",
            game_versions=["1.20.4"],
            loaders=["fabric"],
            files=[PluginFile(url="https://fake.url/mod.jar", filename="mod.jar", size_bytes=10)],
            dependencies=[],
        )

    async def get_project_versions(
        self,
        project_id: str,  # noqa: ARG002
    ) -> PluginVersionsPage:
        v = await self.get_version("v1")
        return PluginVersionsPage(items=[v], total=1)

    async def get_project(self, project_id: str) -> object:  # noqa: ARG002
        class _Proj:
            icon_url = None

        return _Proj()

    async def download(
        self,
        url: str,  # noqa: ARG002
        expected_sha1=None,  # noqa: ARG002
        expected_sha512=None,  # noqa: ARG002
    ) -> bytes:
        return _create_jar_bytes(
            {"fabric.mod.json": '{"id": "mod", "name": "Downloaded Mod", "version": "1.0.0"}'},
        )


@pytest.mark.asyncio
async def test_install_modrinth_routes_to_mods_for_fabric(
    event_bus: EventBus,
    tmp_path: Path,
) -> None:
    srv_dir = tmp_path / "srv-fab-mr"
    srv_dir.mkdir(parents=True, exist_ok=True)
    server = await _create_test_server("srv-fab-modrinth", "fabric", str(srv_dir))

    handler = InstallModrinthPluginHandler(event_bus, provider=_FakeModProvider())
    cmd = InstallModrinthPluginCommand(
        server_id=str(server.id),
        project_id="test-mod",
        version_id="v1",
        minecraft_version="1.20.4",
    )
    result = await handler.handle(cmd)
    assert result.success is True
    assert result.data["filename"] == "mod.jar"
    assert result.data["loader"] == "fabric"

    # Confirms it was routed to mods/ folder
    assert (srv_dir / "mods" / "mod.jar").exists()
    assert not (srv_dir / "plugins" / "mod.jar").exists()
