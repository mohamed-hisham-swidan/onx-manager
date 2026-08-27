import logging

from app.core.persistence.unit_of_work import UnitOfWork
from app.core.saga import SagaOrchestrator, SagaStep
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.infrastructure.providers.base import ServerProvider
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId

logger = logging.getLogger(__name__)


class DeploymentSaga:
    def __init__(self, saga_orchestrator: SagaOrchestrator) -> None:
        self._saga = saga_orchestrator

    async def execute(self, server_id: ServerId, provider: ServerProvider, config: dict) -> None:
        steps = [
            SagaStep(
                name="provision_infrastructure",
                forward=self._provision(server_id, provider, config),
                compensate=self._deprovision(server_id, provider),
            ),
            SagaStep(
                name="register_server",
                forward=self._register(server_id, config),
                compensate=self._unregister(server_id),
            ),
        ]

        instance = await self._saga.create_saga("deployment", steps)
        await self._saga.execute(instance.saga_id)

    def _provision(self, server_id: ServerId, provider: ServerProvider, config: dict):
        async def fn() -> None:
            result = await provider.start(str(server_id), config)
            logger.info("Server provisioned: %s on %s:%d", server_id, result.address, result.port)

        return fn

    def _deprovision(self, server_id: ServerId, provider: ServerProvider):
        async def fn() -> None:
            handle = _make_handle(provider, server_id)
            await provider.destroy(handle)
            logger.info("Server deprovisioned: %s", server_id)

        return fn

    def _register(self, server_id: ServerId, config: dict):
        async def fn() -> None:
            logger.info("Server registered: %s", server_id)

        return fn

    def _unregister(self, server_id: ServerId):
        async def fn() -> None:
            async with UnitOfWork() as uow:
                repo: ServerRepository = SQLServerRepository(uow.session)
                server = await repo.get(server_id)
                server.mark_deleted()
                await repo.delete(server_id)
                await uow.commit()
            logger.info("Server unregistered: %s", server_id)

        return fn


class RestartSaga:
    def __init__(self, saga_orchestrator: SagaOrchestrator) -> None:
        self._saga = saga_orchestrator

    async def execute(self, server: Server, provider: ServerProvider) -> None:
        handle = _make_handle(provider, server.id)

        steps = [
            SagaStep(
                name="warn_players",
                forward=self._warn_players(provider, handle),
                compensate=None,
            ),
            SagaStep(
                name="save_world",
                forward=self._save_world(provider, handle),
                compensate=None,
            ),
            SagaStep(
                name="stop_server",
                forward=self._stop_server(provider, handle),
                compensate=None,
            ),
            SagaStep(
                name="start_server",
                forward=self._start_server(server, provider),
                compensate=self._stop_server_after_fail(provider, handle),
            ),
            SagaStep(
                name="verify_online",
                forward=self._verify_online(provider, handle),
                compensate=self._stop_server_after_fail(provider, handle),
            ),
        ]

        instance = await self._saga.create_saga("restart", steps, timeout_seconds=120.0)
        await self._saga.execute(instance.saga_id)

    def _warn_players(self, provider: ServerProvider, handle: object):
        async def fn() -> None:
            await provider.execute_command(handle, "say Server is restarting in 10 seconds...")

        return fn

    def _save_world(self, provider: ServerProvider, handle: object):
        async def fn() -> None:
            await provider.execute_command(handle, "save-all")
            logger.info("World saved")

        return fn

    def _stop_server(self, provider: ServerProvider, handle: object):
        async def fn() -> None:
            await provider.stop(handle, force=False)
            logger.info("Server stopped for restart")

        return fn

    def _start_server(self, server: Server, provider: ServerProvider):
        async def fn() -> None:
            config = {
                "name": server.name,
                "minecraft_version": str(server.minecraft_version),
                "memory_min_mb": server.memory.min_mb,
                "memory_max_mb": server.memory.max_mb,
                "port": server.properties.port.value,
            }
            await provider.start(str(server.id), config)
            logger.info("Server started after restart")

        return fn

    def _stop_server_after_fail(self, provider: ServerProvider, handle: object):
        async def fn() -> None:
            try:
                await provider.stop(handle, force=True)
            except Exception:
                logger.exception("Force stop failed during restart compensation")

        return fn

    def _verify_online(self, provider: ServerProvider, handle: object):
        async def fn() -> None:
            import asyncio

            for attempt in range(5):
                status = await provider.status(handle)
                if status.value == "running":
                    logger.info("Restart verified: server is running")
                    return
                await asyncio.sleep(2)
            raise RuntimeError("Server did not come online after restart")

        return fn


def _make_handle(provider: ServerProvider, server_id: ServerId) -> object:
    from app.modules.server.infrastructure.providers.base import ServerHandle

    return ServerHandle(
        provider=provider.provider_type,
        server_id=str(server_id),
        external_id=str(server_id),
    )
