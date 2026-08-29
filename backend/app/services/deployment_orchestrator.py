import logging

from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.value_objects import default_provider_for_platform
from app.modules.server.infrastructure.providers.base import (
    ProviderFactory,
    ServerHandle,
    ServerProvider,
    ServerRuntimeStatus,
)
from app.modules.server.infrastructure.providers.circuit_breaker_wrapper import (
    CircuitBreakerProviderWrapper,
)

logger = logging.getLogger(__name__)


class DeploymentOrchestrator:
    def __init__(self, provider_factory: ProviderFactory) -> None:
        self._factory = provider_factory

    def get_provider(self, provider_type: str) -> ServerProvider:
        raw = self._factory.get(provider_type)
        return CircuitBreakerProviderWrapper(raw)

    async def provision(
        self,
        server: Server,
        provider_type: str = "",
    ) -> dict:
        actual_provider_type = provider_type or default_provider_for_platform()
        provider = self.get_provider(actual_provider_type)

        config = {
            "name": server.name,
            "minecraft_version": str(server.minecraft_version),
            "memory_min_mb": server.memory.min_mb,
            "memory_max_mb": server.memory.max_mb,
            "port": server.properties.port.value,
            "motd": server.properties.motd,
            "max_players": server.properties.max_players,
            "gamemode": server.properties.gamemode,
            "difficulty": server.properties.difficulty,
            "java_args": str(server.java_args),
        }

        result = await provider.start(str(server.id), config)
        logger.info(
            "Server %s provisioned via %s: %s:%d",
            server.id,
            actual_provider_type,
            result.address,
            result.port,
        )
        return {
            "provider": actual_provider_type,
            "address": result.address,
            "port": result.port,
            "pid": result.pid,
            "status": result.status.value,
        }

    async def health_check(self, server: Server) -> ServerRuntimeStatus:
        provider_type = (
            server.runtime.provider
            if (server.runtime and server.runtime.provider)
            else (
                getattr(server.deployment, "provider", None)
                or default_provider_for_platform()
            )
        )
        provider = self.get_provider(provider_type)
        handle = ServerHandle(
            provider=provider.provider_type,
            server_id=str(server.id),
            external_id=str(server.id),
        )
        return await provider.status(handle)
