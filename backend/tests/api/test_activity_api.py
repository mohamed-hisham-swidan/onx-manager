from __future__ import annotations

import time

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
from app.modules.activity.domain.entities import ServerActivityLog
from app.modules.activity.infrastructure.repository import SQLActivityRepository
from app.modules.auth.infrastructure.jwt import create_access_token
from app.modules.server.infrastructure.models import ServerMembershipModel, ServerModel
from app.registration import register_handlers


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
async def seed_data():
    now = time.time()
    async with database.session_factory() as session:
        server = ServerModel(
            id="srv-act-1",
            name="ActivityServer",
            server_type="vanilla",
            minecraft_version="1.21.1",
            status="RUNNING",
            root_path="/tmp/test_srv_act_1",
            deployment_host="127.0.0.1",
            port=25565,
            owner_id="usr-owner",
        )
        membership = ServerMembershipModel(
            id="mem-act-1",
            server_id="srv-act-1",
            user_id="usr-viewer",
            role="viewer",
        )
        session.add_all([server, membership])
        await session.commit()

    repo = SQLActivityRepository()
    for i in range(15):
        await repo.save(
            ServerActivityLog(
                server_id="srv-act-1",
                event_type="server.started" if i % 2 == 0 else "plugin.installed",
                summary=f"Activity log entry {i}",
                timestamp=now - (15 - i) * 10,
                actor_type="user" if i % 2 == 0 else "system",
                actor_id="usr-owner" if i % 2 == 0 else None,
                details={"index": i},
            )
        )


@pytest.fixture
def owner_headers():
    token = create_access_token(
        user_id="usr-owner",
        roles=["user"],
        permissions=["server:read"],
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def viewer_headers():
    token = create_access_token(
        user_id="usr-viewer",
        roles=["user"],
        permissions=["server:read"],
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def non_member_headers():
    token = create_access_token(
        user_id="usr-other",
        roles=["user"],
        permissions=["server:read"],
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_get_activity_auth_and_permissions(
    seed_data: None,
    owner_headers: dict[str, str],
    viewer_headers: dict[str, str],
    non_member_headers: dict[str, str],
) -> None:
    _ = seed_data
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 401 without auth
        res_no_auth = await client.get("/api/v1/servers/srv-act-1/activity")
        assert res_no_auth.status_code == 401

        # 403 for non-member
        res_non_member = await client.get(
            "/api/v1/servers/srv-act-1/activity",
            headers=non_member_headers,
        )
        assert res_non_member.status_code == 403

        # 200 for member (viewer)
        res_viewer = await client.get(
            "/api/v1/servers/srv-act-1/activity",
            headers=viewer_headers,
        )
        assert res_viewer.status_code == 200

        # 200 for owner
        res_owner = await client.get(
            "/api/v1/servers/srv-act-1/activity",
            headers=owner_headers,
        )
        assert res_owner.status_code == 200


@pytest.mark.asyncio
async def test_get_activity_pagination(
    seed_data: None,
    owner_headers: dict[str, str],
) -> None:
    _ = seed_data
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(
            "/api/v1/servers/srv-act-1/activity?limit=5&offset=0",
            headers=owner_headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 15
        assert data["limit"] == 5
        assert data["offset"] == 0
        assert len(data["items"]) == 5
        # Newest first
        assert data["items"][0]["summary"] == "Activity log entry 14"

        res_p2 = await client.get(
            "/api/v1/servers/srv-act-1/activity?limit=5&offset=5",
            headers=owner_headers,
        )
        assert res_p2.status_code == 200
        data_p2 = res_p2.json()
        assert len(data_p2["items"]) == 5
        assert data_p2["items"][0]["summary"] == "Activity log entry 9"


@pytest.mark.asyncio
async def test_get_activity_filters(
    seed_data: None,
    owner_headers: dict[str, str],
) -> None:
    _ = seed_data
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Filter by event_type
        res = await client.get(
            "/api/v1/servers/srv-act-1/activity?event_type=plugin.installed",
            headers=owner_headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 7
        for item in data["items"]:
            assert item["event_type"] == "plugin.installed"


@pytest.mark.asyncio
async def test_get_activity_server_not_found(owner_headers):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/servers/srv-nonexistent/activity", headers=owner_headers)
        assert res.status_code == 404
