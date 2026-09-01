from __future__ import annotations

from pathlib import Path

from app.modules.server.domain.value_objects import (
    LocationType,
    ServerDeployment,
)
from app.modules.server.infrastructure.location import (
    LocalLocationHandler,
    LocationHandlerRegistry,
    handler_registry,
    local_handler,
)


def test_local_location_handler_resolves_server_dir() -> None:
    deployment = ServerDeployment(
        location_type=LocationType.LOCAL,
        root_path="/opt/minecraft/servers/my-server",
        working_directory=".",
    )
    handler = LocalLocationHandler()
    assert (
        Path(handler.resolve_server_dir(deployment)).as_posix()
        == "/opt/minecraft/servers/my-server"
    )


def test_local_location_handler_resolves_jar_path() -> None:
    deployment = ServerDeployment(
        location_type=LocationType.LOCAL,
        root_path="/opt/minecraft/servers/my-server",
        startup_jar="paper.jar",
    )
    handler = LocalLocationHandler()
    assert (
        Path(handler.resolve_jar_path(deployment)).as_posix()
        == "/opt/minecraft/servers/my-server/paper.jar"
    )


def test_local_location_handler_resolves_properties_path() -> None:
    deployment = ServerDeployment(
        location_type=LocationType.LOCAL,
        root_path="/opt/minecraft/servers/my-server",
    )
    handler = LocalLocationHandler()
    assert (
        Path(handler.resolve_properties_path(deployment)).as_posix()
        == "/opt/minecraft/servers/my-server/server.properties"
    )


def test_local_location_handler_resolves_eula_path() -> None:
    deployment = ServerDeployment(
        location_type=LocationType.LOCAL,
        root_path="/opt/minecraft/servers/my-server",
    )
    handler = LocalLocationHandler()
    assert (
        Path(handler.resolve_eula_path(deployment)).as_posix()
        == "/opt/minecraft/servers/my-server/eula.txt"
    )


def test_local_location_handler_resolves_world_path() -> None:
    deployment = ServerDeployment(
        location_type=LocationType.LOCAL,
        root_path="/opt/minecraft/servers/my-server",
        primary_world="my-world",
    )
    handler = LocalLocationHandler()
    assert (
        Path(handler.resolve_world_path(deployment)).as_posix()
        == "/opt/minecraft/servers/my-server/my-world"
    )
    assert (
        Path(handler.resolve_world_path(deployment, "other-world")).as_posix()
        == "/opt/minecraft/servers/my-server/other-world"
    )


def test_local_location_handler_ensure_dir() -> None:
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        deployment = ServerDeployment(
            location_type=LocationType.LOCAL,
            root_path=tmp,
            working_directory="nested/sub",
        )
        handler = LocalLocationHandler()
        result = handler.ensure_server_dir(deployment)
        assert Path(result).exists()
        assert Path(result).is_dir()


def test_local_location_handler_supports() -> None:
    handler = LocalLocationHandler()
    assert handler.supports(LocationType.LOCAL) is True
    assert handler.supports(LocationType.DOCKER) is False
    assert handler.supports(LocationType.SSH) is False


def test_registry_register_and_get() -> None:
    registry = LocationHandlerRegistry()
    handler = LocalLocationHandler()
    registry.register(handler)
    retrieved = registry.get(LocationType.LOCAL)
    assert retrieved is handler


def test_registry_get_for_deployment() -> None:
    registry = LocationHandlerRegistry()
    handler = LocalLocationHandler()
    registry.register(handler)
    deployment = ServerDeployment(location_type=LocationType.LOCAL)
    retrieved = registry.get_for_deployment(deployment)
    assert retrieved is handler


def test_global_handler_registry_has_local() -> None:
    handler = handler_registry.get(LocationType.LOCAL)
    assert handler is not None
    assert isinstance(handler, LocalLocationHandler)


def test_global_local_handler_is_initialized() -> None:
    assert local_handler is not None
    assert isinstance(local_handler, LocalLocationHandler)
