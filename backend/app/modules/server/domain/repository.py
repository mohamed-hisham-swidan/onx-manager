from __future__ import annotations

from abc import ABC, abstractmethod

from app.modules.server.domain.aggregate import Server
from app.modules.shared.value_objects import ServerId


class ServerFilters:
    def __init__(
        self,
        status: str | None = None,
        group_id: str | None = None,
        name_search: str | None = None,
        minecraft_version: str | None = None,
    ) -> None:
        self.status = status
        self.group_id = group_id
        self.name_search = name_search
        self.minecraft_version = minecraft_version


class ServerRepository(ABC):
    @abstractmethod
    async def get(self, id: ServerId) -> Server: ...

    @abstractmethod
    async def list(self, filters: ServerFilters | None = None) -> list[Server]: ...

    @abstractmethod
    async def save(self, server: Server) -> None: ...

    @abstractmethod
    async def delete(self, id: ServerId) -> None: ...
