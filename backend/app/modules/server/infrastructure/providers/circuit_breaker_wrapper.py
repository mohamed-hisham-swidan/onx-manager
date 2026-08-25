from __future__ import annotations

from typing import Any

from app.core.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from app.core.exceptions import ProviderError
from app.modules.server.infrastructure.providers.base import (
    DeploymentResult,
    ServerHandle,
    ServerProvider,
    ServerRuntimeStatus,
)


class CircuitBreakerProviderWrapper(ServerProvider):
    def __init__(self, wrapped: ServerProvider, breaker: CircuitBreaker | None = None) -> None:
        self._wrapped = wrapped
        self._breaker = breaker or CircuitBreaker(
            name=f"provider:{wrapped.provider_type}",
            max_failures=5,
            timeout_seconds=30.0,
        )

    @property
    def breaker(self) -> CircuitBreaker:
        return self._breaker

    @property
    def wrapped(self) -> ServerProvider:
        return self._wrapped

    @property
    def provider_type(self) -> str:
        return self._wrapped.provider_type

    def capabilities(self) -> list[str]:
        return self._wrapped.capabilities()

    async def ping(self) -> bool:
        try:
            return await self._breaker.call_factory(self._wrapped.ping)
        except CircuitBreakerOpenError:
            return False
        except ProviderError:
            return False

    async def start(self, server_id: str, config: dict[str, Any]) -> DeploymentResult:
        return await self._breaker.call_factory(lambda: self._wrapped.start(server_id, config))

    async def stop(self, handle: ServerHandle, force: bool = False) -> None:
        await self._breaker.call_factory(lambda: self._wrapped.stop(handle, force=force))

    async def status(self, handle: ServerHandle) -> ServerRuntimeStatus:
        try:
            return await self._breaker.call_factory(lambda: self._wrapped.status(handle))
        except CircuitBreakerOpenError:
            return ServerRuntimeStatus.UNKNOWN

    async def console(self, handle: ServerHandle, tail: int = 100) -> list[str]:
        return await self._breaker.call_factory(lambda: self._wrapped.console(handle, tail=tail))

    async def execute_command(self, handle: ServerHandle, command: str) -> str:
        return await self._breaker.call_factory(lambda: self._wrapped.execute_command(handle, command))

    async def destroy(self, handle: ServerHandle) -> None:
        await self._breaker.call_factory(lambda: self._wrapped.destroy(handle))

    async def get_runtime_pid(self, handle: ServerHandle) -> int | None:
        return await self._wrapped.get_runtime_pid(handle)
