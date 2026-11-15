from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.persistence.db import database
from app.core.query_bus import QueryBus
from app.main import app
from app.modules.auth.infrastructure.jwt import create_access_token
from app.modules.server.infrastructure.models import ServerModel
from app.registration import register_handlers

MISSING_SERVER_ID = "srv-missing-ordering"
SIMPLE_SERVER_ID = "srv-simple-ordering"
ADVANCED_SERVER_ID = "srv-advanced-ordering"


@pytest.fixture(autouse=True)
def _register_buses() -> None:
    command_bus = CommandBus()
    query_bus = QueryBus()
    event_bus = EventBus()
    register_handlers(command_bus, query_bus, event_bus)
    deps.init_buses(command_bus, query_bus, event_bus)


async def _seed_server(server_id: str, mode: str = "simple") -> None:
    async with database.session_factory() as session:
        session.add(
            ServerModel(
                id=server_id,
                name=f"server-{server_id}",
                server_type="vanilla",
                minecraft_version="1.20.4",
                status="STOPPED",
                port=25565,
                mode=mode,
            )
        )
        await session.commit()


def _make_headers(permissions: list[str], roles: list[str] | None = None) -> dict[str, str]:
    token = create_access_token(
        user_id="usr-ordering-test",
        roles=roles or ["user"],
        permissions=permissions,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "server_id,mode",
    [
        (MISSING_SERVER_ID, None),
        (SIMPLE_SERVER_ID, "simple"),
        (ADVANCED_SERVER_ID, "advanced"),
    ],
)
@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/versioning/branches", None),
        ("POST", "/versioning/branches", {"name": "feat"}),
        ("GET", "", None),
    ],
)
async def test_unauthenticated_cannot_distinguish_server(
    server_id: str, mode: str | None, method: str, path: str, body: dict | None
) -> None:
    if mode is not None:
        await _seed_server(server_id, mode=mode)

    url = f"/api/v1/servers/{server_id}{path}"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.request(method, url, json=body)

    assert resp.status_code == 401
    payload = resp.json()
    assert payload.get("error_code") == "AUTHENTICATION_ERROR"


@pytest.mark.asyncio
async def test_authenticated_nonowner_simple_409_advanced_not_409() -> None:
    await _seed_server(SIMPLE_SERVER_ID, mode="simple")
    await _seed_server(ADVANCED_SERVER_ID, mode="advanced")

    headers = _make_headers(["server:version:read", "server:version:commit"])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Simple server versioning read and mutate return 409
        r_simple_read = await client.get(
            f"/api/v1/servers/{SIMPLE_SERVER_ID}/versioning/branches", headers=headers
        )
        assert r_simple_read.status_code == 409
        assert r_simple_read.json().get("code") == "SERVER_MODE_VERSIONING_DISABLED"

        r_simple_mutate = await client.post(
            f"/api/v1/servers/{SIMPLE_SERVER_ID}/versioning/branches",
            headers=headers,
            json={"name": "feature-test"},
        )
        assert r_simple_mutate.status_code == 409
        assert r_simple_mutate.json().get("code") == "SERVER_MODE_VERSIONING_DISABLED"

        # Advanced versioning routes are POSIX-only in this release: on POSIX they
        # do not return 409; on non-POSIX hosts require_advanced_mode fails closed.
        r_adv_read = await client.get(
            f"/api/v1/servers/{ADVANCED_SERVER_ID}/versioning/branches", headers=headers
        )

        r_adv_mutate = await client.post(
            f"/api/v1/servers/{ADVANCED_SERVER_ID}/versioning/branches",
            headers=headers,
            json={"name": "feature-test"},
        )

        if os.name == "posix":
            assert r_adv_read.status_code != 409
            assert r_adv_mutate.status_code != 409
        else:
            assert r_adv_read.status_code == 409
            assert r_adv_read.json().get("code") == "SERVER_MODE_VERSIONING_DISABLED"
            assert r_adv_mutate.status_code == 409
            assert r_adv_mutate.json().get("code") == "SERVER_MODE_VERSIONING_DISABLED"

        # Non-versioning read: verify status not in (401, 409) per Card Amendment 1
        # Observed contract is 200 (server exists, user authenticated)
        r_nonv = await client.get(f"/api/v1/servers/{SIMPLE_SERVER_ID}", headers=headers)
        assert r_nonv.status_code not in (401, 409)


@pytest.mark.asyncio
async def test_authenticated_missing_server_404() -> None:
    headers = _make_headers(["server:version:read", "server:version:commit"])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r_v = await client.get(
            f"/api/v1/servers/{MISSING_SERVER_ID}/versioning/branches", headers=headers
        )
        assert r_v.status_code == 404

        r_nonv = await client.get(f"/api/v1/servers/{MISSING_SERVER_ID}", headers=headers)
        assert r_nonv.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_body", [{}, {"name": 123}])
async def test_simple_invalid_body_returns_409_not_422(invalid_body: dict) -> None:
    await _seed_server(SIMPLE_SERVER_ID, mode="simple")
    admin_headers = _make_headers(["admin:full"], roles=["admin"])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/servers/{SIMPLE_SERVER_ID}/versioning/branches",
            headers=admin_headers,
            json=invalid_body,
        )
        assert resp.status_code == 409
        assert resp.json().get("code") == "SERVER_MODE_VERSIONING_DISABLED"


@pytest.mark.asyncio
async def test_simple_lacking_route_permission_returns_409_not_403() -> None:
    await _seed_server(SIMPLE_SERVER_ID, mode="simple")
    # Token has read permission but lacks server:version:commit
    read_only_headers = _make_headers(["server:version:read"])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/servers/{SIMPLE_SERVER_ID}/versioning/branches",
            headers=read_only_headers,
            json={"name": "feature-branch"},
        )
        # Router-level require_advanced_mode runs before route require_permission
        assert resp.status_code == 409
        assert resp.json().get("code") == "SERVER_MODE_VERSIONING_DISABLED"
