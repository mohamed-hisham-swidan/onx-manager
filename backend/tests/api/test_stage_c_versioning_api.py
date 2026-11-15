from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import deps
from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.core.query_bus import QueryBus
from app.main import app
from app.modules.auth.infrastructure.jwt import create_access_token
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.domain.entities import ServerBranch, ServerCommit
from app.modules.versioning.domain.value_objects import (
    BranchStatus,
    CommitManifest,
)
from app.modules.versioning.infrastructure.repository import SQLVersioningRepository
from app.registration import register_handlers

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="P2 Advanced versioning routes require a POSIX host; Windows remains Simple-only",
)


@pytest.fixture(autouse=True)
async def init_test_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    old_engine = database._engine
    old_factory = database._session_factory
    database._engine = engine
    database._session_factory = session_factory

    cb = CommandBus()
    qb = QueryBus()
    eb = EventBus()
    register_handlers(cb, qb, eb)
    deps.init_buses(cb, qb, eb)

    yield
    database._engine = old_engine
    database._session_factory = old_factory
    await engine.dispose()


@pytest.fixture
async def seed_api_server(tmp_path: Path):
    server_dir = tmp_path / "server_api_dir"
    server_dir.mkdir(parents=True, exist_ok=True)
    (server_dir / "server.properties").write_text("difficulty=easy\nmotd=API\n")
    (server_dir / "config").mkdir(parents=True, exist_ok=True)
    (server_dir / "config" / "paper-global.yml").write_text("timings: false\n")

    srv_id = "srv-c-api"
    async with database.session_factory() as session:
        server = ServerModel(
            id=srv_id,
            name="StageCApiServer",
            server_type="paper",
            minecraft_version="1.21.1",
            status="STOPPED",
            root_path=str(server_dir),
            deployment_host="127.0.0.1",
            port=25565,
            java_args="-Xmx2G",
            bot_verification_settings={"bot_count": 5, "duration_minutes": 10},
            mode="advanced",
        )
        session.add(server)

        repo = SQLVersioningRepository(session)
        manifest = CommitManifest(
            server_type="paper",
            minecraft_version="1.21.1",
            configs={
                "server.properties": "difficulty=easy\nmotd=InitialAPI\n",
                "config/paper-global.yml": "timings: false\n",
            },
            mods=[],
            env_vars={"JAVA_ARGS": "-Xmx2G"},
        )
        commit = ServerCommit(
            id="c-api-initial",
            server_id=srv_id,
            message="Initial API commit",
            manifest=manifest,
            parent_commit_ids=[],
        )
        await repo.save_commit(commit)

        branch = ServerBranch(
            id="b-api-main",
            server_id=srv_id,
            name="main",
            head_commit_id="c-api-initial",
            status=BranchStatus.ACTIVE,
        )
        await repo.save_branch(branch)
        await session.commit()

    return srv_id, server_dir


def auth_headers(permissions: list[str]) -> dict[str, str]:
    token = create_access_token(
        user_id="usr-test",
        roles=["operator"],
        permissions=permissions,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_materialization_api_lifecycle(seed_api_server):
    srv_id, _ = seed_api_server

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. POST /materializations without auth -> 401
        res = await client.post(
            f"/api/v1/servers/{srv_id}/versioning/materializations",
            json={"revision_type": "commit", "ref": "c-api-initial", "mode": "readonly"},
        )
        assert res.status_code == 401

        # 2. POST /materializations with server:version:commit -> 201
        res = await client.post(
            f"/api/v1/servers/{srv_id}/versioning/materializations",
            json={"revision_type": "commit", "ref": "c-api-initial", "mode": "readonly"},
            headers=auth_headers(["server:version:commit"]),
        )
        assert res.status_code == 201
        data = res.json()
        mat_id = data["materialization_id"]
        assert data["mode"] == "readonly"
        assert data["status"] == "ready"

        # 3. GET /materializations with server:version:read -> 200
        res = await client.get(
            f"/api/v1/servers/{srv_id}/versioning/materializations",
            headers=auth_headers(["server:version:read"]),
        )
        assert res.status_code == 200
        items = res.json()
        assert len(items) == 1
        assert items[0]["id"] == mat_id

        # 4. GET /materializations/{mat_id}/tree -> 200
        res = await client.get(
            f"/api/v1/servers/{srv_id}/versioning/materializations/{mat_id}/tree",
            headers=auth_headers(["server:version:read"]),
        )
        assert res.status_code == 200
        tree = res.json()
        assert "entries" in tree
        assert any(e["path"] == "server.properties" for e in tree["entries"])

        # 5. GET /materializations/{mat_id}/files?path=server.properties -> 200
        res = await client.get(
            f"/api/v1/servers/{srv_id}/versioning/materializations/{mat_id}/files?path=server.properties",
            headers=auth_headers(["server:version:read"]),
        )
        assert res.status_code == 200
        file_data = res.json()
        assert file_data["path"] == "server.properties"
        assert file_data["encoding"] == "utf-8"
        assert "InitialAPI" in file_data["content"]

        # 6. PUT /materializations/{mat_id}/files when readonly -> 409 Conflict
        res = await client.put(
            f"/api/v1/servers/{srv_id}/versioning/materializations/{mat_id}/files",
            json={"path": "server.properties", "content": "difficulty=peaceful\n"},
            headers=auth_headers(["server:version:commit"]),
        )
        assert res.status_code == 409

        # 7. POST /materializations/{mat_id}/edit-mode -> 200
        res = await client.post(
            f"/api/v1/servers/{srv_id}/versioning/materializations/{mat_id}/edit-mode",
            json={"enabled": True},
            headers=auth_headers(["server:version:commit"]),
        )
        assert res.status_code == 200
        assert res.json()["mode"] == "editable"

        # 8. PUT /materializations/{mat_id}/files when editable -> 200
        res = await client.put(
            f"/api/v1/servers/{srv_id}/versioning/materializations/{mat_id}/files",
            json={"path": "server.properties", "content": "difficulty=peaceful\n"},
            headers=auth_headers(["server:version:commit"]),
        )
        assert res.status_code == 200
        assert res.json()["path"] == "server.properties"

        # 9. DELETE /materializations/{mat_id} -> 200
        res = await client.delete(
            f"/api/v1/servers/{srv_id}/versioning/materializations/{mat_id}",
            headers=auth_headers(["server:version:commit"]),
        )
        assert res.status_code == 200


@pytest.mark.asyncio
async def test_materialization_file_size_cap_413(seed_api_server):
    srv_id, _ = seed_api_server
    big_content = "x" * (1024 * 1024 + 1)

    async with database.session_factory() as session:
        repo = SQLVersioningRepository(session)
        big_manifest = CommitManifest(
            server_type="paper",
            minecraft_version="1.21.1",
            configs={"big.dat": big_content},
            mods=[],
            env_vars={},
        )
        await repo.save_commit(
            ServerCommit(
                id="c-api-big",
                server_id=srv_id,
                message="Big file commit",
                manifest=big_manifest,
                parent_commit_ids=["c-api-initial"],
            )
        )
        await session.commit()

    url_base = f"/api/v1/servers/{srv_id}/versioning/materializations"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        res = await c.post(
            url_base,
            json={"revision_type": "commit", "ref": "c-api-big", "mode": "readonly"},
            headers=auth_headers(["server:version:commit"]),
        )
        assert res.status_code == 201
        mat_id = res.json()["materialization_id"]

        res = await c.get(
            f"{url_base}/{mat_id}/files?path=big.dat",
            headers=auth_headers(["server:version:read"]),
        )
        assert res.status_code == 413
        assert "big.dat" in res.json()["detail"]


@pytest.mark.asyncio
async def test_import_review_api_lifecycle(seed_api_server):
    srv_id, server_dir = seed_api_server

    # Modify live server.properties
    (server_dir / "server.properties").write_text("difficulty=hard\nmotd=LiveAPIMod\n")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. POST /import-review/scan -> 200
        res = await client.post(
            f"/api/v1/servers/{srv_id}/versioning/import-review/scan",
            json={"source": "main"},
            headers=auth_headers(["server:version:read"]),
        )
        assert res.status_code == 200
        scan_data = res.json()
        assert any(c["path"] == "server.properties" for c in scan_data["changes"])

        # 2. POST /import-review/auto-commit -> 201
        with (
            patch(
                "app.modules.versioning.infrastructure.storage_probe.StorageCapabilityProbe.assert_supports_reflink"
            ),
            patch(
                "app.modules.versioning.infrastructure.btrfs_zfs_driver.BtrfsZfsSnapshotDriver.create_snapshot",
                return_value=1024,
            ),
        ):
            res = await client.post(
                f"/api/v1/servers/{srv_id}/versioning/import-review/auto-commit",
                json={"branch": "main"},
                headers=auth_headers(["server:version:commit"]),
            )
        assert res.status_code == 201
        ac_data = res.json()
        review_id = ac_data["review_id"]
        assert review_id is not None

        # 3. POST /import-review/{review_id}/confirm -> 200
        res = await client.post(
            f"/api/v1/servers/{srv_id}/versioning/import-review/{review_id}/confirm",
            headers=auth_headers(["server:version:commit"]),
        )
        assert res.status_code == 200
        assert res.json()["status"] == "confirmed"

        # 4. Confirming again fails with 409 Conflict
        res = await client.post(
            f"/api/v1/servers/{srv_id}/versioning/import-review/{review_id}/confirm",
            headers=auth_headers(["server:version:commit"]),
        )
        assert res.status_code == 409


@pytest.mark.asyncio
async def test_import_review_api_dismiss_and_revert(seed_api_server):
    srv_id, server_dir = seed_api_server

    # Cycle 1: Dismiss
    (server_dir / "server.properties").write_text("difficulty=hard\nmotd=DismissMe\n")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with (
            patch(
                "app.modules.versioning.infrastructure.storage_probe.StorageCapabilityProbe.assert_supports_reflink"
            ),
            patch(
                "app.modules.versioning.infrastructure.btrfs_zfs_driver.BtrfsZfsSnapshotDriver.create_snapshot",
                return_value=1024,
            ),
        ):
            res_ac = await client.post(
                f"/api/v1/servers/{srv_id}/versioning/import-review/auto-commit",
                json={"branch": "main"},
                headers=auth_headers(["server:version:commit"]),
            )
        assert res_ac.status_code == 201
        review_id_1 = res_ac.json()["review_id"]

        res_dis = await client.post(
            f"/api/v1/servers/{srv_id}/versioning/import-review/{review_id_1}/dismiss",
            headers=auth_headers(["server:version:commit"]),
        )
        assert res_dis.status_code == 200
        assert res_dis.json()["status"] == "dismissed"

        # Cycle 2: Revert
        (server_dir / "server.properties").write_text("difficulty=hard\nmotd=RevertMe\n")
        with (
            patch(
                "app.modules.versioning.infrastructure.storage_probe.StorageCapabilityProbe.assert_supports_reflink"
            ),
            patch(
                "app.modules.versioning.infrastructure.btrfs_zfs_driver.BtrfsZfsSnapshotDriver.create_snapshot",
                return_value=1024,
            ),
        ):
            res_ac2 = await client.post(
                f"/api/v1/servers/{srv_id}/versioning/import-review/auto-commit",
                json={"branch": "main"},
                headers=auth_headers(["server:version:commit"]),
            )
            assert res_ac2.status_code == 201
            review_id_2 = res_ac2.json()["review_id"]

            res_rev = await client.post(
                f"/api/v1/servers/{srv_id}/versioning/import-review/{review_id_2}/revert",
                headers=auth_headers(["server:version:commit"]),
            )
        assert res_rev.status_code == 200
        assert res_rev.json()["status"] == "reverted"
