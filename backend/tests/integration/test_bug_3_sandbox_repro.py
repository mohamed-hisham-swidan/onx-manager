from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.event_bus import EventBus
from app.core.identity import IDENTITY
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.modules.server.application.commands.create_server import (
    CreateServerCommand,
    CreateServerHandler,
)
from app.modules.server.application.services.filesystem_reconciliation import (
    FilesystemReconciliationService,
)
from app.modules.server.infrastructure.repository import SQLServerRepository


@pytest.fixture
async def sqlite_db():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    database._engine = engine
    database._session_factory = session_factory

    yield session_factory

    await engine.dispose()
    database._engine = None
    database._session_factory = None


class TestBug3SandboxRepro:
    @pytest.mark.asyncio
    async def test_bug_3_repro_and_permanent_prevention(
        self, sqlite_db, tmp_path: Path
    ) -> None:
        """Exact sandbox reproduction of Bug 3 and verification of its fix:
        1. Create a Docker server ('provider=docker').
        2. Verify .onx-manager/server.json is authoritatively stamped upon creation.
        3. Run lifespan reconciliation: assert provider is still 'docker', row count is 1.
        4. Delete .onx-manager/server.json (simulating pre-fix server or lost identity).
        5. Run lifespan reconciliation: assert adopt-vs-heal heals identity on disk,
           preserves provider='docker', preserves UUID, and prevents provider-badge flip.
        """
        data_dir = tmp_path / "servers"
        data_dir.mkdir(parents=True, exist_ok=True)
        server_dir = data_dir / "sandbox-srv"

        event_bus = EventBus()
        create_handler = CreateServerHandler(event_bus)

        mock_docker = AsyncMock()
        mock_docker.ping.return_value = True

        async def fake_download(*_args, **kwargs):
            deployment = kwargs.get("deployment")
            if deployment is not None:
                srv_path = Path(deployment.root_path)
                srv_path.mkdir(parents=True, exist_ok=True)
                (srv_path / "server.jar").write_bytes(b"PK fake server jar")

        # -------------------------------------------------------------
        # Step 1: Create Docker server
        # -------------------------------------------------------------
        cmd = CreateServerCommand(
            name="sandbox-srv",
            server_type="paper",
            minecraft_version="26.2",
            provider="docker",
        )

        with (
            patch(
                "app.modules.server.infrastructure.providers.provider_factory.get",
                return_value=mock_docker,
            ),
            patch(
                "app.modules.server.application.services.jar_service.download_server_jar",
                side_effect=fake_download,
            ),
            patch(
                "app.modules.server.application.services.jar_service.resolve_server_dir",
                return_value=str(server_dir),
            ),
        ):
            res = await create_handler.handle(cmd)
            assert res.success is True, f"Server creation failed: {res.error}"
            server_id = res.data["server_id"]

        # -------------------------------------------------------------
        # Step 2: Verify identity stamping on disk immediately upon creation
        # -------------------------------------------------------------
        identity_path = server_dir / IDENTITY.identity_dir_new / IDENTITY.identity_file
        assert identity_path.exists(), "Identity file was not stamped on creation"
        initial_doc = json.loads(identity_path.read_text(encoding="utf-8"))
        assert initial_doc["server_id"] == server_id
        assert initial_doc["provider"] == "docker"

        # -------------------------------------------------------------
        # Step 3: Run reconciliation on freshly created Docker server
        # -------------------------------------------------------------
        mock_settings = MagicMock()
        mock_settings.servers_data_dir = str(data_dir)

        async with sqlite_db() as session:
            repo = SQLServerRepository(session)
            service = FilesystemReconciliationService(repo=repo)
            with patch(
                "app.modules.server.application.services.filesystem_reconciliation.AppSettings",
                return_value=mock_settings,
            ):
                recon_res1 = await service.reconcile()

            assert recon_res1.total_imported == 0
            assert recon_res1.total_deleted == 0
            assert recon_res1.total_missing == 0
            assert recon_res1.total_errors == 0

            # Verify DB state in same session
            servers = await repo.list()
            assert len(servers) == 1
            assert str(servers[0].id) == server_id
            assert servers[0].runtime.provider == "docker"

        # -------------------------------------------------------------
        # Step 4: Simulate pre-fix state (delete .onx-manager/server.json)
        # -------------------------------------------------------------
        identity_path.unlink()
        assert not identity_path.exists(), "Failed to delete identity file for simulation"

        # -------------------------------------------------------------
        # Step 5: Run reconciliation with missing identity file
        # -------------------------------------------------------------
        async with sqlite_db() as session:
            repo = SQLServerRepository(session)
            service = FilesystemReconciliationService(repo=repo)
            with patch(
                "app.modules.server.application.services.filesystem_reconciliation.AppSettings",
                return_value=mock_settings,
            ):
                recon_res2 = await service.reconcile()

            # Pre-fix Bug: would have planned ActionType.IMPORT, minted new UUID,
            # overwritten/broken DB record, flipped provider to "local".
            # Post-fix: Must plan ActionType.HEAL_IDENTITY!
            assert recon_res2.total_healed == 1
            assert recon_res2.total_imported == 0
            assert recon_res2.total_missing == 0
            assert recon_res2.total_deleted == 0

            # ---------------------------------------------------------
            # Step 6: Verify identity restored on disk and DB unchanged
            # ---------------------------------------------------------
            assert identity_path.exists()
            restored_doc = json.loads(identity_path.read_text(encoding="utf-8"))
            assert restored_doc["server_id"] == server_id
            assert restored_doc["provider"] == "docker"

            servers_post = await repo.list()
            assert len(servers_post) == 1
            assert str(servers_post[0].id) == server_id
            # Provider badge flip PREVENTED:
            assert servers_post[0].runtime.provider == "docker"
