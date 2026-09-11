from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.event_bus import EventBus
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.modules.server.application.commands.create_server import (
    CreateServerCommand,
    CreateServerHandler,
)
from app.modules.server.domain.value_objects import (
    LocationType,
    default_provider_for_platform,
)
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId


@pytest.fixture(autouse=True)
async def app_db():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    database._engine = engine
    database._session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    yield
    await engine.dispose()
    database._engine = None
    database._session_factory = None


class TestCreateServerProviderSelection:
    @pytest.mark.asyncio
    async def test_create_server_with_docker_provider_success(
        self, tmp_path: Path
    ) -> None:
        event_bus = EventBus()
        handler = CreateServerHandler(event_bus)
        cmd = CreateServerCommand(
            name="docker-test-server",
            server_type="vanilla",
            minecraft_version="1.20.4",
            provider="docker",
        )

        with (
            patch(
                "app.modules.server.infrastructure.providers.provider_factory.get"
            ) as mock_factory_get,
            patch(
                "app.modules.server.application.services.jar_service.download_server_jar",
                AsyncMock(),
            ),
            patch(
                "app.modules.server.application.services.jar_service.resolve_server_dir",
                return_value=str(tmp_path / "srv-docker"),
            ),
        ):
            mock_docker = AsyncMock()
            mock_docker.ping.return_value = True
            mock_factory_get.return_value = mock_docker

            result = await handler.handle(cmd)

        assert result.success is True
        server_id = result.data["server_id"]

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            server = await repo.get(ServerId(server_id))
            assert server is not None
            assert server.deployment.location_type == LocationType.DOCKER
            assert server.runtime.provider == "docker"

    @pytest.mark.asyncio
    async def test_create_server_with_docker_provider_unavailable(self) -> None:
        event_bus = EventBus()
        handler = CreateServerHandler(event_bus)
        cmd = CreateServerCommand(
            name="docker-fail-server",
            server_type="vanilla",
            minecraft_version="1.20.4",
            provider="docker",
        )

        with patch(
            "app.modules.server.infrastructure.providers.provider_factory.get"
        ) as mock_factory_get:
            mock_docker = AsyncMock()
            mock_docker.ping.return_value = False
            mock_factory_get.return_value = mock_docker

            result = await handler.handle(cmd)

        assert result.success is False
        assert result.error_code == "DOCKER_UNAVAILABLE"
        assert "Docker daemon is unreachable" in (result.error or "")

        # Database atomicity: no rows created
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            servers = await repo.list()
            assert len(servers) == 0

    @pytest.mark.asyncio
    async def test_create_server_docker_windows_mode_actionable_error(self) -> None:
        event_bus = EventBus()
        handler = CreateServerHandler(event_bus)
        cmd = CreateServerCommand(
            name="docker-win-fail-server",
            server_type="vanilla",
            minecraft_version="1.20.4",
            provider="docker",
        )

        with patch(
            "app.modules.server.infrastructure.providers.provider_factory.get"
        ) as mock_factory_get:
            mock_docker = AsyncMock()
            mock_docker.ping.return_value = False
            mock_docker.last_ping_error = (
                "Docker daemon is running in 'windows' containers mode. "
                "ONX Manager requires Docker Desktop with WSL2 backend in Linux containers mode "
                "(switch via Docker Desktop tray menu -> 'Switch to Linux containers...')."
            )
            mock_factory_get.return_value = mock_docker

            result = await handler.handle(cmd)

        assert result.success is False
        assert result.error_code == "DOCKER_UNAVAILABLE"
        assert "'windows' containers mode" in (result.error or "")
        assert "Switch to Linux containers" in (result.error or "")

    @pytest.mark.asyncio
    async def test_create_server_docker_unavailable_atomicity_no_partial_state(
        self, tmp_path: Path
    ) -> None:
        """When docker ping fails, genuinely no database row or filesystem state is created."""
        event_bus = EventBus()
        handler = CreateServerHandler(event_bus)
        target_dir = tmp_path / "uncreated_server"
        cmd = CreateServerCommand(
            name="docker-atomic-fail-server",
            server_type="vanilla",
            minecraft_version="1.20.4",
            provider="docker",
            install_dir=str(target_dir),
        )

        with (
            patch(
                "app.modules.server.infrastructure.providers.provider_factory.get"
            ) as mock_factory_get,
            patch(
                "app.modules.server.application.services.jar_service.download_server_jar",
                AsyncMock(),
            ) as mock_download,
        ):
            mock_docker = AsyncMock()
            mock_docker.ping.return_value = False
            mock_factory_get.return_value = mock_docker

            result = await handler.handle(cmd)

        # 1. Error returned cleanly
        assert result.success is False
        assert result.error_code == "DOCKER_UNAVAILABLE"
        mock_download.assert_not_called()

        # 2. Filesystem assertion: directory was never created
        assert not target_dir.exists()

        # 3. Database assertion: zero server rows created
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            servers = await repo.list()
            assert len(servers) == 0

    @pytest.mark.asyncio
    async def test_create_server_default_provider_fallback(
        self, tmp_path: Path
    ) -> None:
        event_bus = EventBus()
        handler = CreateServerHandler(event_bus)
        cmd = CreateServerCommand(
            name="default-test-server",
            server_type="vanilla",
            minecraft_version="1.20.4",
            provider=None,
        )

        with (
            patch(
                "app.modules.server.application.services.jar_service.download_server_jar",
                AsyncMock(),
            ),
            patch(
                "app.modules.server.application.services.jar_service.resolve_server_dir",
                return_value=str(tmp_path / "srv-default"),
            ),
        ):
            result = await handler.handle(cmd)

        assert result.success is True
        server_id = result.data["server_id"]

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            server = await repo.get(ServerId(server_id))
            assert server is not None
            assert server.deployment.location_type == LocationType.LOCAL
            assert server.runtime.provider == default_provider_for_platform()

    @pytest.mark.asyncio
    async def test_create_server_explicit_local_provider(
        self, tmp_path: Path
    ) -> None:
        event_bus = EventBus()
        handler = CreateServerHandler(event_bus)
        cmd = CreateServerCommand(
            name="local-test-server",
            server_type="vanilla",
            minecraft_version="1.20.4",
            provider="local",
        )

        with (
            patch(
                "app.modules.server.application.services.jar_service.download_server_jar",
                AsyncMock(),
            ),
            patch(
                "app.modules.server.application.services.jar_service.resolve_server_dir",
                return_value=str(tmp_path / "srv-local"),
            ),
        ):
            result = await handler.handle(cmd)

        assert result.success is True
        server_id = result.data["server_id"]

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            server = await repo.get(ServerId(server_id))
            assert server is not None
            assert server.deployment.location_type == LocationType.LOCAL
            assert server.runtime.provider == "local"

    @pytest.mark.asyncio
    async def test_create_server_invalid_provider_rejected(self) -> None:
        event_bus = EventBus()
        handler = CreateServerHandler(event_bus)
        cmd = CreateServerCommand(
            name="invalid-test-server",
            server_type="vanilla",
            minecraft_version="1.20.4",
            provider="unsupported_provider",
        )

        result = await handler.handle(cmd)
        assert result.success is False
        assert result.error_code == "INVALID_PROVIDER"
