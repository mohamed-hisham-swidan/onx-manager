from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.modules.server.domain.diagnostics import RuntimeDiagnostics
from app.modules.server.domain.value_objects import (
    LaunchConfiguration,
    ServerDeployment,
)


class ServerRuntimeStatus(Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ServerHandle:
    provider: str
    server_id: str
    external_id: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.provider}/{self.server_id}:{self.external_id}"


@dataclass(frozen=True)
class DeploymentResult:
    status: ServerRuntimeStatus
    address: str
    port: int
    pid: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ServerProvider(ABC):
    @property
    @abstractmethod
    def provider_type(self) -> str: ...

    @abstractmethod
    async def ping(self) -> bool: ...

    @abstractmethod
    async def start(
        self,
        server_id: str,
        config: dict[str, Any] | None = None,
        deployment: ServerDeployment | None = None,
        launch_config: LaunchConfiguration | None = None,
    ) -> DeploymentResult: ...

    @abstractmethod
    async def stop(self, handle: ServerHandle, force: bool = False) -> None: ...

    @abstractmethod
    async def status(self, handle: ServerHandle) -> ServerRuntimeStatus: ...

    @abstractmethod
    async def console(self, handle: ServerHandle, tail: int = 100) -> list[str]: ...

    @abstractmethod
    async def execute_command(self, handle: ServerHandle, command: str) -> str: ...

    @abstractmethod
    async def destroy(self, handle: ServerHandle) -> None: ...

    def capabilities(self) -> list[str]:
        """Return the list of public, externally usable capabilities supported by this provider.

        A capability represents an operational feature that callers (such as sagas, supervisors,
        or API routers) can rely on through the public `ServerProvider` contract.

        Canonical capability vocabulary:
        - "process": Provider manages the execution lifecycle of the server process or container
                     (start, stop, status, get_runtime_pid).
        - "console": Provider captures and streams live/historical console and log output via `console()`.
        - "exec":    Provider supports executing interactive commands on the running server via `execute_command()`.

        Rules for capability strings:
        - Names represent public API contracts, not internal implementation mechanisms (e.g. do not expose
          "tmux", "powershell", "filesystem", or specific runtime type identities like "docker" as capabilities;
          runtime identity is exposed via `provider_type`).
        - Callers may safely branch on capabilities (e.g. `if "exec" in provider.capabilities(): ...`).
        - Unknown or future capabilities must be ignored by callers that do not recognize them.
        - The default implementation returns an empty list `[]`, indicating a minimal or stub provider
          with no declared operational capabilities.
        """
        return []

    async def wait_ready(
        self,
        server_id: str,
        handle: ServerHandle,
        timeout: float = 60.0,
    ) -> bool:
        return True

    async def collect_diagnostics(
        self,
        handle: ServerHandle,
    ) -> RuntimeDiagnostics:
        return RuntimeDiagnostics(
            provider=self.provider_type,
            runtime_handle=str(handle),
        )

    async def verify_process(self, handle: ServerHandle) -> bool:
        status = await self.status(handle)
        return status == ServerRuntimeStatus.RUNNING

    async def get_runtime_pid(self, handle: ServerHandle) -> int | None:
        return None


class ProviderFactory:
    def __init__(self) -> None:
        self._providers: dict[str, ServerProvider] = {}

    def register(self, provider: ServerProvider) -> None:
        self._providers[provider.provider_type] = provider

    def get(self, provider_type: str) -> ServerProvider:
        provider = self._providers.get(provider_type)
        if provider is None:
            raise ValueError(f"No provider registered for type: {provider_type!r}")
        return provider

    def list_types(self) -> list[str]:
        return list(self._providers.keys())


provider_factory = ProviderFactory()
