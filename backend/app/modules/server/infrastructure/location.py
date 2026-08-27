from __future__ import annotations

from abc import ABC, abstractmethod

from app.modules.server.domain.value_objects import (
    LocationType,
    ServerDeployment,
)
from app.modules.server.infrastructure.fs import FileSystem, local_fs


class LocationHandler(ABC):
    @abstractmethod
    def resolve_server_dir(self, deployment: ServerDeployment) -> str: ...

    @abstractmethod
    def resolve_jar_path(self, deployment: ServerDeployment) -> str: ...

    @abstractmethod
    def resolve_properties_path(self, deployment: ServerDeployment) -> str: ...

    @abstractmethod
    def resolve_eula_path(self, deployment: ServerDeployment) -> str: ...

    @abstractmethod
    def resolve_world_path(
        self, deployment: ServerDeployment, world_name: str | None = None
    ) -> str: ...

    @abstractmethod
    def ensure_server_dir(self, deployment: ServerDeployment) -> str: ...

    @abstractmethod
    def remove_server_dir(self, deployment: ServerDeployment) -> None: ...

    @abstractmethod
    def supports(self, location_type: LocationType) -> bool: ...


class LocalLocationHandler(LocationHandler):
    def __init__(self, fs: FileSystem | None = None) -> None:
        self._fs = fs or local_fs

    def resolve_server_dir(self, deployment: ServerDeployment) -> str:
        return deployment.server_directory()

    def resolve_jar_path(self, deployment: ServerDeployment) -> str:
        return deployment.jar_path()

    def resolve_properties_path(self, deployment: ServerDeployment) -> str:
        return deployment.properties_path()

    def resolve_eula_path(self, deployment: ServerDeployment) -> str:
        return deployment.eula_path()

    def resolve_world_path(
        self, deployment: ServerDeployment, world_name: str | None = None
    ) -> str:
        return deployment.world_path(world_name)

    def ensure_server_dir(self, deployment: ServerDeployment) -> str:
        path = deployment.server_directory()
        self._fs.ensure_dir(path)
        return path

    def remove_server_dir(self, deployment: ServerDeployment) -> None:
        path = deployment.server_directory()
        self._fs.delete_dir(path)

    def supports(self, location_type: LocationType) -> bool:
        return location_type == LocationType.LOCAL


class LocationHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[LocationType, LocationHandler] = {}

    def register(self, handler: LocationHandler) -> None:
        for lt in LocationType:
            if handler.supports(lt):
                self._handlers[lt] = handler

    def get(self, location_type: LocationType) -> LocationHandler:
        handler = self._handlers.get(location_type)
        if handler is None:
            raise ValueError(f"No LocationHandler registered for {location_type.value}")
        return handler

    def get_for_deployment(self, deployment: ServerDeployment) -> LocationHandler:
        return self.get(deployment.location_type)


local_handler = LocalLocationHandler()
handler_registry = LocationHandlerRegistry()
handler_registry.register(local_handler)
