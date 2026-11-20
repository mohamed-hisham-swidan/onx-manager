from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.core.event_bus import EventBus
from app.core.persistence.db import database
from app.modules.server.application.commands.create_server import (
    CreateServerCommand,
    CreateServerHandler,
)
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId


async def _get_server(server_id: str):
    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        return await repo.get(ServerId(server_id))


async def _mock_jar_download() -> AsyncMock:
    """Write server.jar to whatever root_path the deployment carries."""

    def write_jar(
        server_id: str,
        server_type: str,  # noqa: ARG001 - mock signature
        minecraft_version: str,  # noqa: ARG001 - mock signature
        deployment=None,
        fs=None,  # noqa: ARG001 - mock signature
    ) -> str:
        dest = deployment.jar_path() if deployment else f"{server_id}/server.jar"
        p = Path(dest)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"PK\x03\x04" + b"\x00" * (1024 * 1024))
        return str(p)

    return AsyncMock(side_effect=write_jar)


class TestCreateServerProvisioning:
    @pytest.mark.asyncio
    async def test_vanilla_creates_all_files(
        self,
        event_bus: EventBus,
        init_test_db: None,  # noqa: ARG002 - fixture execution required
    ) -> None:
        mock = await _mock_jar_download()

        with patch(
            "app.modules.server.application.services.jar_service.download_server_jar",
            mock,
        ):
            handler = CreateServerHandler(event_bus)
            cmd = CreateServerCommand(
                name="Integration Vanilla",
                server_type="vanilla",
                minecraft_version="1.21.4",
            )

            result = await handler.handle(cmd)

        assert result.success is True
        sid = result.data["server_id"]
        server = await _get_server(sid)
        assert server.name == "Integration Vanilla"

        server_dir = Path(server.deployment.root_path)
        assert (server_dir / "server.jar").exists()
        assert (server_dir / "eula.txt").exists()
        assert (server_dir / "server.properties").exists()

    @pytest.mark.asyncio
    async def test_forge_creates_no_jar_but_has_eula_and_props(
        self,
        event_bus: EventBus,
        init_test_db: None,  # noqa: ARG002 - fixture execution required
    ) -> None:
        handler = CreateServerHandler(event_bus)
        cmd = CreateServerCommand(
            name="Integration Forge",
            server_type="forge",
            minecraft_version="1.20.1",
        )

        with patch(
            "app.modules.server.application.services.forge_provisioner.provision_forge_server",
        ) as mock_provision:
            result = await handler.handle(cmd)
            mock_provision.assert_called_once()

        assert result.success is True
        sid = result.data["server_id"]
        server = await _get_server(sid)
        assert server.name == "Integration Forge"
        assert str(server.server_type.value) == "forge"

        server_dir = Path(server.deployment.root_path)
        assert not (server_dir / "server.jar").exists()
        assert (server_dir / "eula.txt").exists()
        assert (server_dir / "server.properties").exists()

    @pytest.mark.asyncio
    async def test_neoforge_creates_server_and_begins_provisioning(
        self,
        event_bus: EventBus,
        init_test_db: None,  # noqa: ARG002 - fixture execution required
    ) -> None:
        handler = CreateServerHandler(event_bus)
        cmd = CreateServerCommand(
            name="Integration NeoForge",
            server_type="neoforge",
            minecraft_version="1.21.1",
        )

        with patch(
            "app.modules.server.application.services.neoforge_provisioner.provision_neoforge_server",
        ) as mock_provision:
            result = await handler.handle(cmd)
            mock_provision.assert_called_once()

        assert result.success is True
        sid = result.data["server_id"]
        server = await _get_server(sid)
        assert server.name == "Integration NeoForge"
        assert str(server.server_type.value) == "neoforge"

        server_dir = Path(server.deployment.root_path)
        assert not (server_dir / "server.jar").exists()
        assert (server_dir / "eula.txt").exists()
        assert (server_dir / "server.properties").exists()

    @pytest.mark.asyncio
    async def test_provisioning_failure_cleans_up_directory(
        self,
        event_bus: EventBus,
        init_test_db: None,  # noqa: ARG002 - fixture execution required
    ) -> None:
        from app.core.exceptions import ProvisioningError

        with patch(
            "app.modules.server.application.services.jar_service.download_server_jar",
            AsyncMock(
                side_effect=ProvisioningError(
                    message="cleanup test failure",
                    server_id="fail",
                )
            ),
        ):
            handler = CreateServerHandler(event_bus)
            cmd = CreateServerCommand(
                name="Integration Fail",
                server_type="vanilla",
                minecraft_version="1.21.4",
            )

            with pytest.raises(ProvisioningError):
                await handler.handle(cmd)

    @pytest.mark.asyncio
    async def test_provisioning_failure_does_not_commit_server(
        self,
        event_bus: EventBus,
        init_test_db: None,  # noqa: ARG002 - fixture execution required
    ) -> None:
        from app.core.exceptions import ProvisioningError

        with patch(
            "app.modules.server.application.services.jar_service.download_server_jar",
            AsyncMock(
                side_effect=ProvisioningError(
                    message="no-commit test",
                    server_id="nocommit",
                )
            ),
        ):
            handler = CreateServerHandler(event_bus)
            cmd = CreateServerCommand(
                name="No Commit Server",
                server_type="vanilla",
                minecraft_version="1.21.4",
            )

            with pytest.raises(ProvisioningError):
                await handler.handle(cmd)

        async with database.session_factory() as session:
            from sqlalchemy import text

            row = await session.execute(
                text("SELECT COUNT(*) FROM servers WHERE name = 'No Commit Server'"),
            )
            count = row.scalar()
        assert count == 0, "server must not exist in DB when provisioning fails"

    @pytest.mark.asyncio
    async def test_unknown_server_type_rejected(
        self,
        event_bus: EventBus,
        init_test_db: None,  # noqa: ARG002 - fixture execution required
    ) -> None:
        handler = CreateServerHandler(event_bus)
        cmd = CreateServerCommand(
            name="Unknown Type",
            server_type="nonexistent",
            minecraft_version="1.21",
        )

        with pytest.raises(ValueError, match="not a valid ServerType"):
            await handler.handle(cmd)

    @pytest.mark.asyncio
    async def test_paper_purpur_fabric_creates_files(
        self,
        event_bus: EventBus,
        init_test_db: None,  # noqa: ARG002 - fixture execution required
    ) -> None:
        for stype in ("paper", "purpur", "fabric"):
            mock = await _mock_jar_download()

            with patch(
                "app.modules.server.application.services.jar_service.download_server_jar",
                mock,
            ):
                handler = CreateServerHandler(event_bus)
                cmd = CreateServerCommand(
                    name=f"Integration {stype.title()}",
                    server_type=stype,
                    minecraft_version="1.21",
                )

                result = await handler.handle(cmd)

            assert result.success is True, f"{stype} creation failed"
            sid = result.data["server_id"]
            server = await _get_server(sid)
            server_dir = Path(server.deployment.root_path)
            assert (server_dir / "server.jar").exists(), f"{stype} missing server.jar"
            assert (server_dir / "eula.txt").exists(), f"{stype} missing eula.txt"
            assert (server_dir / "server.properties").exists(), f"{stype} missing server.properties"

    @pytest.mark.asyncio
    async def test_unexpected_exception_cleans_up(
        self,
        event_bus: EventBus,
        init_test_db: None,  # noqa: ARG002 - fixture execution required
    ) -> None:
        from app.core.exceptions import ProvisioningError

        with patch(
            "app.modules.server.application.services.jar_service.download_server_jar",
            AsyncMock(side_effect=RuntimeError("something broke")),
        ):
            handler = CreateServerHandler(event_bus)
            cmd = CreateServerCommand(
                name="Unexpected Error",
                server_type="vanilla",
                minecraft_version="1.21",
            )

            with pytest.raises(ProvisioningError):
                await handler.handle(cmd)

    @pytest.mark.asyncio
    async def test_provisioning_failure_unknown_type_also_cleans_up(
        self,
        event_bus: EventBus,
        init_test_db: None,  # noqa: ARG002 - fixture execution required
    ) -> None:
        handler = CreateServerHandler(event_bus)
        cmd = CreateServerCommand(
            name="Unknown Two",
            server_type="not-a-real-type",
            minecraft_version="1.21",
        )

        with pytest.raises(ValueError, match="not a valid ServerType"):
            await handler.handle(cmd)
