from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.query_bus import QueryBus
from app.main import app
from app.registration import register_handlers


@pytest.fixture(scope="module")
def buses():
    event_bus = EventBus()
    command_bus = CommandBus()
    query_bus = QueryBus()
    register_handlers(command_bus, query_bus, event_bus)
    return command_bus, query_bus, event_bus


@pytest.fixture(autouse=True)
def _override_deps(buses) -> None:
    command_bus, query_bus, event_bus = buses
    from app.api import deps

    async def get_cb() -> CommandBus:
        return command_bus

    async def get_qb() -> QueryBus:
        return query_bus

    async def get_eb() -> EventBus:
        return event_bus

    app.dependency_overrides[deps.get_command_bus] = get_cb
    app.dependency_overrides[deps.get_query_bus] = get_qb
    app.dependency_overrides[deps.get_event_bus] = get_eb


@pytest.fixture
async def client() -> AsyncClient:
    from app.core.persistence.base import Base
    from app.core.persistence.db import database
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    database._engine = engine
    database._session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await engine.dispose()
    database._engine = None
    database._session_factory = None


class TestLoginFlow:
    async def test_full_login_flow(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/users",
            json={"email": "flow@test.com", "password": "SecurePass1", "display_name": "Flow Test"},
        )
        assert resp.status_code == 201

        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "flow@test.com", "password": "SecurePass1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"]
        assert data["refresh_token"]
        assert data["token_type"] == "bearer"
        assert data["expires_in"] == 900

        access_token = data["access_token"]
        resp = await client.get(
            "/api/v1/servers",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert resp.status_code == 200

    async def test_login_wrong_password(self, client: AsyncClient) -> None:
        await client.post(
            "/api/v1/users",
            json={"email": "wrongpw@test.com", "password": "CorrectPass1", "display_name": "Wrong PW"},
        )
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "wrongpw@test.com", "password": "WrongPassword"},
        )
        assert resp.status_code == 401

    async def test_login_nonexistent_user(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "ghost@test.com", "password": "anypassword"},
        )
        assert resp.status_code == 401

    async def test_token_refresh_flow(self, client: AsyncClient) -> None:
        await client.post(
            "/api/v1/users",
            json={"email": "refresh@test.com", "password": "Pass12345", "display_name": "Refresh"},
        )
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "refresh@test.com", "password": "Pass12345"},
        )
        refresh_token = login_resp.json()["refresh_token"]

        resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"]
        assert data["refresh_token"] != refresh_token

    async def test_refresh_with_revoked_token_fails(self, client: AsyncClient) -> None:
        await client.post(
            "/api/v1/users",
            json={"email": "revoke@test.com", "password": "Pass12345", "display_name": "Revoke"},
        )
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "revoke@test.com", "password": "Pass12345"},
        )
        refresh_token = login_resp.json()["refresh_token"]

        await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert resp.status_code == 401

    async def test_access_protected_endpoint_without_token(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/servers")
        assert resp.status_code == 401

    async def test_access_protected_endpoint_with_invalid_token(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/servers", headers={"Authorization": "Bearer invalidtoken"})
        assert resp.status_code == 401
