from app.modules.server.infrastructure.fs import FileSystem, local_fs
from app.modules.server.infrastructure.location import (
    LocationHandler,
    LocationHandlerRegistry,
    handler_registry,
)


class ServerInfrastructure:
    def __init__(
        self,
        fs: FileSystem | None = None,
        location_registry: LocationHandlerRegistry | None = None,
    ) -> None:
        self._fs = fs or local_fs
        self._location_registry = location_registry or handler_registry

    @property
    def fs(self) -> FileSystem:
        return self._fs

    @property
    def location_registry(self) -> LocationHandlerRegistry:
        return self._location_registry

    def get_location_handler(self, deployment) -> LocationHandler:
        return self._location_registry.get_for_deployment(deployment)


infra = ServerInfrastructure()
