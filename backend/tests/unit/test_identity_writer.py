from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

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
from app.modules.server.application.commands.import_server import (
    ImportServerCommand,
    ImportServerHandler,
)
from app.modules.server.application.services.identity_writer import (
    build_server_identity_doc,
    write_server_identity,
)
from app.modules.server.infrastructure.fs import local_fs


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


class TestIdentityWriter:
    def test_build_server_identity_doc_defaults(self):
        doc = build_server_identity_doc(uid="test-uuid-123")
        assert doc["uid"] == "test-uuid-123"
        assert doc["server_id"] == "test-uuid-123"
        assert doc["provider"] == "local"
        assert doc["version"] == IDENTITY.identity_version
        assert doc["manager"] == IDENTITY.manager_field_new
        assert doc["schema_version"] == IDENTITY.schema_version
        assert "created_at" in doc

    def test_build_server_identity_doc_custom_provider_and_time(self):
        created = "2026-09-13T00:00:00Z"
        doc = build_server_identity_doc(
            uid="docker-uuid-456",
            provider="docker",
            created_at=created,
        )
        assert doc["uid"] == "docker-uuid-456"
        assert doc["server_id"] == "docker-uuid-456"
        assert doc["provider"] == "docker"
        assert doc["created_at"] == created

    def test_write_server_identity_creates_dir_and_stamps_file(self, tmp_path: Path):
        server_dir = tmp_path / "test_server"
        server_dir.mkdir(parents=True, exist_ok=True)

        target_file = write_server_identity(
            dir_path=server_dir,
            uid="srv-001",
            provider="docker",
            fs=local_fs,
        )

        expected_path = server_dir / IDENTITY.identity_dir_new / IDENTITY.identity_file
        assert target_file == expected_path
        assert target_file.exists()

        # Verify legacy .mcsmanager directory is NOT created
        legacy_dir = server_dir / IDENTITY.identity_dir_legacy
        assert not legacy_dir.exists()

        data = json.loads(target_file.read_text(encoding="utf-8"))
        assert data["uid"] == "srv-001"
        assert data["server_id"] == "srv-001"
        assert data["provider"] == "docker"
        assert data["manager"] == IDENTITY.manager_field_new
        assert data["schema_version"] == IDENTITY.schema_version

    def test_write_server_identity_atomic_overwrite(self, tmp_path: Path):
        server_dir = tmp_path / "test_server"
        server_dir.mkdir(parents=True, exist_ok=True)

        # Initial write
        write_server_identity(server_dir, uid="srv-old", provider="local")
        # Overwrite with new metadata
        target_file = write_server_identity(server_dir, uid="srv-new", provider="docker")

        data = json.loads(target_file.read_text(encoding="utf-8"))
        assert data["uid"] == "srv-new"
        assert data["server_id"] == "srv-new"
        assert data["provider"] == "docker"


class TestCreateAndImportIdentityStamping:
    @pytest.mark.asyncio
    async def test_create_server_stamps_identity_file_docker(self, tmp_path: Path):
        event_bus = EventBus()
        handler = CreateServerHandler(event_bus)

        srv_dir = tmp_path / "srv-created-docker"
        cmd = CreateServerCommand(
            name="new-docker-srv",
            server_type="paper",
            minecraft_version="26.2",
            provider="docker",
        )

        mock_docker = AsyncMock()
        mock_docker.ping.return_value = True

        with (
            patch(
                "app.modules.server.infrastructure.providers.provider_factory.get",
                return_value=mock_docker,
            ),
            patch(
                "app.modules.server.application.services.jar_service.download_server_jar",
                new_callable=AsyncMock,
            ),
            patch(
                "app.modules.server.application.services.jar_service.resolve_server_dir",
                return_value=str(srv_dir),
            ),
        ):
            res = await handler.handle(cmd)
            assert res.success is True
            server_id = res.data["server_id"]

            identity_file = srv_dir / IDENTITY.identity_dir_new / IDENTITY.identity_file
            assert identity_file.exists()
            doc = json.loads(identity_file.read_text(encoding="utf-8"))
            assert doc["server_id"] == server_id
            assert doc["provider"] == "docker"

    @pytest.mark.asyncio
    async def test_create_server_stamps_identity_file_local(self, tmp_path: Path):
        event_bus = EventBus()
        handler = CreateServerHandler(event_bus)

        srv_dir = tmp_path / "srv-created-local"
        cmd = CreateServerCommand(
            name="new-local-srv",
            server_type="vanilla",
            minecraft_version="1.20.4",
            provider="local",
        )

        with (
            patch(
                "app.modules.server.application.services.jar_service.download_server_jar",
                new_callable=AsyncMock,
            ),
            patch(
                "app.modules.server.application.services.jar_service.resolve_server_dir",
                return_value=str(srv_dir),
            ),
        ):
            res = await handler.handle(cmd)
            assert res.success is True
            server_id = res.data["server_id"]

            identity_file = srv_dir / IDENTITY.identity_dir_new / IDENTITY.identity_file
            assert identity_file.exists()
            doc = json.loads(identity_file.read_text(encoding="utf-8"))
            assert doc["server_id"] == server_id
            assert doc["provider"] == "local"

    @pytest.mark.asyncio
    async def test_import_server_stamps_identity_and_removes_legacy_dir(self, tmp_path: Path):
        event_bus = EventBus()
        handler = ImportServerHandler(event_bus)

        srv_dir = tmp_path / "srv-imported"

        def fake_extract(_src, dst):
            dst_path = Path(dst)
            dst_path.mkdir(parents=True, exist_ok=True)
            stale_dir = dst_path / IDENTITY.identity_dir_legacy
            stale_dir.mkdir(parents=True, exist_ok=True)
            (stale_dir / IDENTITY.identity_file).write_text(
                '{"uid": "foreign-id"}', encoding="utf-8"
            )
            (dst_path / "server.jar").write_bytes(b"PK fake zip content")

        fake_zip = tmp_path / "server.zip"
        fake_zip.write_bytes(b"PK fake zip archive")

        cmd = ImportServerCommand(
            name="imported-srv",
            source_path=str(fake_zip),
            minecraft_version="1.20.4",
        )

        with (
            patch(
                "app.modules.server.application.commands.import_server.resolve_server_dir",
                return_value=str(srv_dir),
            ),
            patch(
                "app.modules.server.application.commands.import_server._safe_extract_zip",
                side_effect=fake_extract,
            ),
        ):
            res = await handler.handle(cmd)
            assert res.success is True
            server_id = res.data["server_id"]

            # Legacy folder must have been removed
            stale_legacy = srv_dir / IDENTITY.identity_dir_legacy
            assert not stale_legacy.exists()

            # Canonical identity file must be stamped
            identity_file = srv_dir / IDENTITY.identity_dir_new / IDENTITY.identity_file
            assert identity_file.exists()
            doc = json.loads(identity_file.read_text(encoding="utf-8"))
            assert doc["server_id"] == server_id
            assert doc["provider"] in ("local", "local_windows")
