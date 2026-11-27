from __future__ import annotations

import os
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
from app.modules.server.infrastructure.models import ServerMembershipModel, ServerModel
from app.modules.versioning.domain.entities import BranchProtectionPolicy, ServerBranch
from app.modules.versioning.domain.value_objects import BranchStatus, CommitManifest
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
async def seed_server(tmp_path):
    srv_dir = tmp_path / "srv-g-api"
    srv_dir.mkdir(parents=True, exist_ok=True)
    async with database.session_factory() as session:
        server = ServerModel(
            id="srv-g-api",
            name="StageGApiServer",
            server_type="vanilla",
            minecraft_version="1.21.1",
            status="STOPPED",
            root_path=str(srv_dir),
            deployment_host="127.0.0.1",
            port=25565,
            java_args="-Xmx2G",
            bot_verification_settings={"bot_count": 5, "duration_minutes": 10},
            mode="advanced",
        )
        session.add(server)
        session.add(
            ServerMembershipModel(
                id="mem-g-admin", server_id="srv-g-api", user_id="usr-test", role="server_admin"
            )
        )
        session.add(
            ServerMembershipModel(
                id="mem-g-viewer", server_id="srv-g-api", user_id="usr-viewer", role="viewer"
            )
        )
        await session.commit()
    return "srv-g-api"


def auth_headers(permissions: list[str]) -> dict[str, str]:
    if permissions == ["server:other"]:
        user_id = "usr-outsider"
        roles = ["viewer"]
    elif permissions == ["server:version:read"]:
        user_id = "usr-viewer"
        roles = ["viewer"]
    else:
        user_id = "usr-test"
        roles = ["server_admin"]
    token = create_access_token(
        user_id=user_id,
        roles=roles,
        permissions=permissions,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_get_branch_protection_api(seed_server):
    srv_id = seed_server
    # Seed branch
    async with database.session_factory() as session:
        repo = SQLVersioningRepository(session)
        branch = ServerBranch(
            id="br-g1", server_id=srv_id, name="main", status=BranchStatus.CREATED
        )
        await repo.save_branch(branch)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. No auth -> 401
        res = await client.get(f"/api/v1/servers/{srv_id}/versioning/branches/main/protection")
        assert res.status_code == 401

        # 2. Missing server:version:read -> 403
        res = await client.get(
            f"/api/v1/servers/{srv_id}/versioning/branches/main/protection",
            headers=auth_headers(["server:other"]),
        )
        assert res.status_code == 403

        # 3. Success -> 200 with is_protected=False
        res = await client.get(
            f"/api/v1/servers/{srv_id}/versioning/branches/main/protection",
            headers=auth_headers(["server:version:read"]),
        )
        assert res.status_code == 200
        data = res.json()
        assert data["server_id"] == srv_id
        assert data["branch_name"] == "main"
        assert data["is_protected"] is False
        assert data["policy"] is None


@pytest.mark.asyncio
async def test_put_and_delete_branch_protection_api(seed_server):
    srv_id = seed_server
    async with database.session_factory() as session:
        repo = SQLVersioningRepository(session)
        branch = ServerBranch(
            id="br-g2", server_id=srv_id, name="release", status=BranchStatus.CREATED
        )
        await repo.save_branch(branch)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # PUT no auth -> 401
        res = await client.put(
            f"/api/v1/servers/{srv_id}/versioning/branches/release/protection",
            json={"policy": {"require_test_pass": True}},
        )
        assert res.status_code == 401

        # PUT missing server:version:branch:protect -> 403
        res = await client.put(
            f"/api/v1/servers/{srv_id}/versioning/branches/release/protection",
            headers=auth_headers(["server:version:read"]),
            json={"policy": {"require_test_pass": True}},
        )
        assert res.status_code == 403

        # PUT success -> 200
        res = await client.put(
            f"/api/v1/servers/{srv_id}/versioning/branches/release/protection",
            headers=auth_headers(["server:version:branch:protect"]),
            json={
                "policy": {
                    "require_test_pass": True,
                    "allow_direct_commit": False,
                    "allow_force_bypass": True,
                    "prevent_deletion": True,
                }
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["is_protected"] is True
        assert data["policy"]["require_test_pass"] is True
        assert data["policy"]["allow_direct_commit"] is False

        # Verify via GET
        res = await client.get(
            f"/api/v1/servers/{srv_id}/versioning/branches/release/protection",
            headers=auth_headers(["server:version:read"]),
        )
        assert res.status_code == 200
        assert res.json()["is_protected"] is True

        # DELETE missing permission -> 403
        res = await client.delete(
            f"/api/v1/servers/{srv_id}/versioning/branches/release/protection",
            headers=auth_headers(["server:version:read"]),
        )
        assert res.status_code == 403

        # DELETE success -> 200
        res = await client.delete(
            f"/api/v1/servers/{srv_id}/versioning/branches/release/protection",
            headers=auth_headers(["server:version:branch:protect"]),
        )
        assert res.status_code == 200
        assert res.json()["is_protected"] is False


@pytest.mark.asyncio
async def test_commit_to_protected_branch_api_gating(seed_server):
    srv_id = seed_server
    # Seed protected branch
    async with database.session_factory() as session:
        repo = SQLVersioningRepository(session)
        branch = ServerBranch(
            id="br-g3",
            server_id=srv_id,
            name="prod",
            status=BranchStatus.CREATED,
            is_protected=True,
            protection_policy=BranchProtectionPolicy(allow_direct_commit=False),
        )
        await repo.save_branch(branch)
        await session.commit()

    sample_manifest = CommitManifest(server_type="vanilla", minecraft_version="1.21.1")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with (
            patch("os.path.exists", return_value=True),
            patch(
                "app.modules.versioning.infrastructure.storage_probe."
                "StorageCapabilityProbe.assert_supports_reflink"
            ),
            patch(
                "app.modules.versioning.infrastructure.btrfs_zfs_driver."
                "BtrfsZfsSnapshotDriver.create_snapshot",
                return_value=1024,
            ),
            patch(
                "app.modules.versioning.infrastructure.manifest_builder."
                "ManifestBuilder.build_manifest",
                return_value=sample_manifest,
            ),
        ):
            # 1. Direct commit without force -> 409 Conflict
            res = await client.post(
                f"/api/v1/servers/{srv_id}/versioning/commits",
                headers=auth_headers(["server:version:commit"]),
                json={"branch_name": "prod", "message": "Direct commit"},
            )
            assert res.status_code == 409
            assert "Direct commits to protected branch" in res.json().get("message", "")

            # 2. Force commit without bypass permission -> 403 Forbidden
            res = await client.post(
                f"/api/v1/servers/{srv_id}/versioning/commits",
                headers=auth_headers(["server:version:commit"]),
                json={
                    "branch_name": "prod",
                    "message": "Forced commit",
                    "force": True,
                    "force_reason": "Emergency",
                },
            )
            assert res.status_code == 403

            # 3. Force commit with bypass permission -> 201 Created
            res = await client.post(
                f"/api/v1/servers/{srv_id}/versioning/commits",
                headers=auth_headers(
                    ["server:version:commit", "server:version:branch:bypass_protection"]
                ),
                json={
                    "branch_name": "prod",
                    "message": "Forced commit",
                    "force": True,
                    "force_reason": "Emergency fix",
                },
            )
            assert res.status_code == 201
            data = res.json()
            assert data["message"] == "Forced commit"
