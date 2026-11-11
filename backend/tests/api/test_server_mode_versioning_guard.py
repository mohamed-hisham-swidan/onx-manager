from __future__ import annotations

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

SERVER_ID = "srv-mode-gate-1"
VERSIONING = f"/api/v1/servers/{SERVER_ID}/versioning"

# (method, path suffix, body) — every versioning operation in P1's route list.
ROUTES: list[tuple[str, str, dict | None]] = [
    ("GET", "/branches", None),
    ("POST", "/branches", {"name": "feature"}),
    ("POST", "/branches/main/archive", {}),
    ("GET", "/branches/main/protection", None),
    ("PUT", "/branches/main/protection", {"policy": {}}),
    ("DELETE", "/branches/main/protection", None),
    ("GET", "/branches/main/history", None),
    ("GET", "/commits", None),
    ("GET", "/commits/diff", None),
    ("POST", "/commits", {"message": "m", "branch_name": "main"}),
    ("POST", "/commits/merge", {"target_branch_name": "main", "message": "m"}),
    ("POST", "/tags", {"name": "v1", "commit_id": "c1"}),
    ("GET", "/tags", None),
    ("GET", "/tags/v1", None),
    ("POST", "/tests", {}),
    ("GET", "/tests", None),
    ("GET", "/tests/test-1", None),
    ("GET", "/tests/test-1/evidence", None),
    ("POST", "/tests/test-1/promote", {}),
    ("POST", "/tests/test-1/discard", {}),
    ("GET", "/test-definitions", None),
    ("POST", "/test-definitions", {"name": "def"}),
    ("GET", "/test-definitions/def-1", None),
    ("PUT", "/test-definitions/def-1", {}),
    ("DELETE", "/test-definitions/def-1", None),
    ("GET", "/settings", None),
    ("PUT", "/settings", {}),
    ("GET", "/preflight", None),
    ("POST", "/materializations", {"revision_type": "commit", "ref": "c1"}),
    ("GET", "/materializations", None),
    ("GET", "/materializations/mat-1/tree", None),
    ("GET", "/materializations/mat-1/files", None),
    ("POST", "/materializations/mat-1/edit-mode", {"enabled": True}),
    ("PUT", "/materializations/mat-1/files", {"path": "a.txt", "content": "x"}),
    ("DELETE", "/materializations/mat-1", None),
    ("POST", "/import-review/scan", {}),
    ("POST", "/import-review/auto-commit", {}),
    ("POST", "/import-review/rev-1/confirm", {}),
    ("POST", "/import-review/rev-1/dismiss", {}),
    ("POST", "/import-review/rev-1/revert", {}),
]

ROUTE_IDS = [f"{method} {path}" for method, path, _ in ROUTES]


@pytest.fixture(autouse=True)
def _register_buses() -> None:
    command_bus = CommandBus()
    query_bus = QueryBus()
    event_bus = EventBus()
    register_handlers(command_bus, query_bus, event_bus)
    deps.init_buses(command_bus, query_bus, event_bus)


async def _seed_server(mode: str | None = None) -> None:
    async with database.session_factory() as session:
        kwargs = {} if mode is None else {"mode": mode}
        session.add(
            ServerModel(
                id=SERVER_ID,
                name="mode-gate",
                server_type="vanilla",
                minecraft_version="1.20.4",
                status="STOPPED",
                port=25565,
                **kwargs,
            )
        )
        await session.commit()


def _admin_headers() -> dict[str, str]:
    token = create_access_token(
        user_id="usr-mode-gate",
        roles=["admin"],
        permissions=["admin:full"],
    )
    return {"Authorization": f"Bearer {token}"}


async def _request(method: str, path: str, body: dict | None) -> tuple[int, dict]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        if body is None:
            response = await client.request(method, f"{VERSIONING}{path}", headers=_admin_headers())
        else:
            response = await client.request(
                method, f"{VERSIONING}{path}", headers=_admin_headers(), json=body
            )
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    return response.status_code, payload


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path", "body"), ROUTES, ids=ROUTE_IDS)
async def test_simple_server_is_blocked_with_409(method: str, path: str, body: dict | None) -> None:
    await _seed_server()
    status, payload = await _request(method, path, body)
    assert status == 409
    assert payload.get("code") == "SERVER_MODE_VERSIONING_DISABLED"


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path", "body"), ROUTES, ids=ROUTE_IDS)
async def test_advanced_server_is_not_blocked(method: str, path: str, body: dict | None) -> None:
    await _seed_server(mode="advanced")
    status, payload = await _request(method, path, body)
    assert not (status == 409 and payload.get("code") == "SERVER_MODE_VERSIONING_DISABLED")
