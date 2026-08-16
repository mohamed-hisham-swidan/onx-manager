from __future__ import annotations

from abc import ABC, abstractmethod

from app.modules.exposure.domain.aggregate import (
    HostPlayitAgent,
    PanelExposure,
    ServerExposure,
)


class HostAgentRepository(ABC):
    @abstractmethod
    async def get(self, id: str = "default") -> HostPlayitAgent: ...

    @abstractmethod
    async def save(self, agent: HostPlayitAgent) -> None: ...


class ServerExposureRepository(ABC):
    @abstractmethod
    async def get(self, server_id: str) -> ServerExposure | None: ...

    @abstractmethod
    async def get_by_id(self, exposure_id: str) -> ServerExposure | None: ...

    @abstractmethod
    async def list(self) -> list[ServerExposure]: ...

    @abstractmethod
    async def list_playit_enabled(self) -> list[ServerExposure]: ...

    @abstractmethod
    async def save(self, exposure: ServerExposure) -> None: ...

    @abstractmethod
    async def delete(self, exposure: ServerExposure) -> None: ...

    @abstractmethod
    async def set_all_disabled(self) -> int: ...


class PanelExposureRepository(ABC):
    @abstractmethod
    async def get(self, id: str = "default") -> PanelExposure: ...

    @abstractmethod
    async def save(self, panel: PanelExposure) -> None: ...


class ExposureGrantRepository(ABC):
    @abstractmethod
    async def get_grant(self, server_id: str, user_id: str) -> object | None: ...

    @abstractmethod
    async def upsert_grant(
        self, server_id: str, user_id: str, can_manage: bool, can_view: bool
    ) -> object: ...

    @abstractmethod
    async def list_grants(self, server_id: str) -> list[object]: ...
