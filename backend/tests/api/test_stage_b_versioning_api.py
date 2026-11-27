from __future__ import annotations

import os

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
from app.modules.versioning.domain.entities import ServerBranch, ServerCommit
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
async def seed_server():
    async with database.session_factory() as session:
        server = ServerModel(
            id="srv-b-api",
            name="StageBApiServer",
            server_type="vanilla",
            minecraft_version="1.21.1",
            status="STOPPED",
            root_path="/tmp/test_stage_b_api",
            deployment_host="127.0.0.1",
            port=25565,
            java_args="-Xmx2G",
            bot_verification_settings={"bot_count": 5, "duration_minutes": 10},
            mode="advanced",
        )
        session.add(server)
        session.add(
            ServerMembershipModel(
                id="mem-b-admin", server_id="srv-b-api", user_id="usr-test", role="server_admin"
            )
        )
        session.add(
            ServerMembershipModel(
                id="mem-b-viewer", server_id="srv-b-api", user_id="usr-viewer", role="viewer"
            )
        )
        await session.commit()
    return "srv-b-api"


def auth_headers(permissions: list[str]) -> dict[str, str]:
    user_id = "usr-viewer" if permissions == ["server:version:read"] else "usr-test"
    roles = ["viewer"] if user_id == "usr-viewer" else ["server_admin"]
    token = create_access_token(
        user_id=user_id,
        roles=roles,
        permissions=permissions,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_archive_branch_api(seed_server):
    srv_id = seed_server
    # Seed branch
    async with database.session_factory() as session:
        repo = SQLVersioningRepository(session)
        branch = ServerBranch(id="br-1", server_id=srv_id, name="dev", status=BranchStatus.CREATED)
        await repo.save_branch(branch)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. No auth -> 401
        res = await client.post(f"/api/v1/servers/{srv_id}/versioning/branches/dev/archive")
        assert res.status_code == 401

        # 2. Missing server:version:commit -> 403
        res = await client.post(
            f"/api/v1/servers/{srv_id}/versioning/branches/dev/archive",
            headers=auth_headers(["server:version:read"]),
        )
        assert res.status_code == 403

        # 3. With server:version:commit -> 200
        res = await client.post(
            f"/api/v1/servers/{srv_id}/versioning/branches/dev/archive",
            headers=auth_headers(["server:version:commit"]),
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "archived"
        assert data["name"] == "dev"


@pytest.mark.asyncio
async def test_tags_api_lifecycle(seed_server):
    srv_id = seed_server
    # Seed commit
    async with database.session_factory() as session:
        repo = SQLVersioningRepository(session)
        c = ServerCommit(
            id="c-api-1",
            server_id=srv_id,
            message="Commit 1",
            manifest=CommitManifest(server_type="vanilla", minecraft_version="1.21.1"),
        )
        await repo.save_commit(c)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create tag without auth -> 401
        res = await client.post(
            f"/api/v1/servers/{srv_id}/versioning/tags",
            json={"name": "v1.0.0", "commit_id": "c-api-1"},
        )
        assert res.status_code == 401

        # Create tag with permission -> 201
        res = await client.post(
            f"/api/v1/servers/{srv_id}/versioning/tags",
            json={"name": "v1.0.0", "commit_id": "c-api-1"},
            headers=auth_headers(["server:version:commit"]),
        )
        assert res.status_code == 201

        # List tags
        res = await client.get(
            f"/api/v1/servers/{srv_id}/versioning/tags",
            headers=auth_headers(["server:version:read"]),
        )
        assert res.status_code == 200
        tags = res.json()
        assert len(tags) == 1
        assert tags[0]["name"] == "v1.0.0"

        # Get tag by name
        res = await client.get(
            f"/api/v1/servers/{srv_id}/versioning/tags/v1.0.0",
            headers=auth_headers(["server:version:read"]),
        )
        assert res.status_code == 200
        assert res.json()["commit_id"] == "c-api-1"

        # Get non-existent tag -> 404
        res = await client.get(
            f"/api/v1/servers/{srv_id}/versioning/tags/v9.9.9",
            headers=auth_headers(["server:version:read"]),
        )
        assert res.status_code == 404


@pytest.mark.asyncio
async def test_diff_commits_api(seed_server):
    srv_id = seed_server
    async with database.session_factory() as session:
        repo = SQLVersioningRepository(session)
        c1 = ServerCommit(
            id="c-diff-1",
            server_id=srv_id,
            message="Commit 1",
            manifest=CommitManifest(
                server_type="vanilla",
                minecraft_version="1.21.1",
                configs={"server.properties": "motd=Old"},
            ),
        )
        c2 = ServerCommit(
            id="c-diff-2",
            server_id=srv_id,
            message="Commit 2",
            manifest=CommitManifest(
                server_type="vanilla",
                minecraft_version="1.21.1",
                configs={"server.properties": "motd=New", "extra.txt": "added"},
            ),
        )
        await repo.save_commit(c1)
        await repo.save_commit(c2)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get(
            f"/api/v1/servers/{srv_id}/versioning/commits/diff?from=c-diff-1&to=c-diff-2",
            headers=auth_headers(["server:version:read"]),
        )
        assert res.status_code == 200
        data = res.json()
        assert data["has_changes"] is True
        assert data["configs"]["modified"]["server.properties"] == {
            "old": "motd=Old",
            "new": "motd=New",
        }
        assert data["configs"]["added"]["extra.txt"] == "added"


@pytest.mark.asyncio
async def test_merge_commits_api(seed_server):
    srv_id = seed_server
    async with database.session_factory() as session:
        repo = SQLVersioningRepository(session)
        c1 = ServerCommit(
            id="c-m-1",
            server_id=srv_id,
            message="Commit 1",
            manifest=CommitManifest(server_type="vanilla", minecraft_version="1.21.1"),
        )
        c2 = ServerCommit(
            id="c-m-2",
            server_id=srv_id,
            message="Commit 2",
            manifest=CommitManifest(server_type="vanilla", minecraft_version="1.21.1"),
        )
        branch = ServerBranch(
            id="br-release-api", server_id=srv_id, name="release", head_commit_id=c1.id
        )
        await repo.save_commit(c1)
        await repo.save_commit(c2)
        await repo.save_branch(branch)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Merge without auth -> 401
        res = await client.post(
            f"/api/v1/servers/{srv_id}/versioning/commits/merge",
            json={
                "target_branch_name": "release",
                "parent_commit_ids": ["c-m-1", "c-m-2"],
                "message": "Merge via API",
            },
        )
        assert res.status_code == 401

        # Merge with permission -> 201
        res = await client.post(
            f"/api/v1/servers/{srv_id}/versioning/commits/merge",
            json={
                "target_branch_name": "release",
                "parent_commit_ids": ["c-m-1", "c-m-2"],
                "message": "Merge via API",
            },
            headers=auth_headers(["server:version:commit"]),
        )
        assert res.status_code == 201
        data = res.json()
        assert "commit_id" in data
        assert data["branch_name"] == "release"

        # Verify branch history API
        res = await client.get(
            f"/api/v1/servers/{srv_id}/versioning/branches/release/history",
            headers=auth_headers(["server:version:read"]),
        )
        assert res.status_code == 200
        history = res.json()
        assert len(history) == 3
