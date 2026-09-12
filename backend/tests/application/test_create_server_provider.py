from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.errors import check_command_result, mcs_error_handler
from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.exceptions import DownloadTimeoutError, MCSError
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
        mock_docker.ensure_image.assert_awaited_once_with("eclipse-temurin:17-jre-jammy")

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

    @pytest.mark.asyncio
    async def test_create_server_download_failure_propagates_details_end_to_end(
        self, tmp_path: Path
    ) -> None:
        event_bus = EventBus()
        bus = CommandBus()
        handler = CreateServerHandler(event_bus)
        bus.register(CreateServerCommand, handler)

        srv_dir = tmp_path / "srv-fail-timeout"
        download_err = DownloadTimeoutError(
            url="https://fill-data.papermc.io/v1/objects/test/paper-26.2.jar",
            timeout_seconds=30,
        )

        cmd = CreateServerCommand(
            name="timeout-test-server",
            server_type="paper",
            minecraft_version="26.2",
            provider="local",
        )

        with (
            patch(
                "app.modules.server.application.services.jar_service.download_server_jar",
                side_effect=download_err,
            ),
            patch(
                "app.modules.server.application.services.jar_service.resolve_server_dir",
                return_value=str(srv_dir),
            ),
        ):
            # 1. CommandBus level verification
            result = await bus.send(cmd)
            assert result.success is False
            assert result.error_code == "INFRASTRUCTURE_ERROR"
            assert "timed out after 30s" in (result.error or "")
            assert result.details is not None
            assert result.details["url"] == (
                "https://fill-data.papermc.io/v1/objects/test/paper-26.2.jar"
            )
            assert result.details["timeout_seconds"] == 30

            # 2. check_command_result level verification
            with pytest.raises(MCSError) as exc_info:
                check_command_result(result)
            assert exc_info.value.code == "INFRASTRUCTURE_ERROR"
            assert exc_info.value.http_status == 503
            assert exc_info.value.details == result.details

            # 3. HTTP response envelope verification
            mock_request = MagicMock(spec=Request)
            mock_request.url.path = "/api/v1/servers"
            mock_request.state.request_id = "req-test-123"
            response = await mcs_error_handler(mock_request, exc_info.value)
            assert response.status_code == 503
            body = json.loads(response.body.decode())
            assert body["code"] == "INFRASTRUCTURE_ERROR"
            assert body["details"]["url"] == (
                "https://fill-data.papermc.io/v1/objects/test/paper-26.2.jar"
            )
            assert body["details"]["timeout_seconds"] == 30
            assert body["detail"]["url"] == (
                "https://fill-data.papermc.io/v1/objects/test/paper-26.2.jar"
            )
            assert "timed out after 30s" in body["message"]

        # 4. State cleanup verification (no orphaned DB row, directory cleaned up)
        assert not srv_dir.exists()
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            servers = await repo.list()
            assert len(servers) == 0
