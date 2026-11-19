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

SERVER_ID = "srv-mode-gate-1"
VERSIONING = f"/api/v1/servers/{SERVER_ID}/versioning"
FILES = f"/api/v1/servers/{SERVER_ID}/files"

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
    ("GET", "/refresh", None),
    ("POST", "/refresh", {}),
    ("POST", "/rollback", {}),
    ("POST", "/upgrade/confirm", {}),
    ("POST", "/refresh/release-pins", {}),
    ("GET", "/class-c/snapshots", None),
    ("POST", "/class-c/snapshots", {}),
    ("POST", "/class-c/snapshots/snap-1/restore", {}),
    ("DELETE", "/class-c/snapshots/snap-1", None),
    ("GET", "/class-c/dynamic", None),
    ("POST", "/class-c/dynamic/reset", {"path": "a.yml"}),
    ("GET", "/secrets", None),
    (
        "POST",
        "/secrets/extract",
        {"branch": "feat", "path": "config/a.yml", "key_name": "K", "secret_value": "v"},
    ),
    ("DELETE", "/secrets/K", None),
    # P4-3 routes
    ("GET", "/data-templates", None),
    ("POST", "/data-templates", {"name": "tmpl-1"}),
    ("DELETE", "/data-templates/tmpl-1", None),
    ("POST", "/branches/feat/port-set/allocate", {}),
    ("PUT", "/branches/feat/port-set", {"game_port": 25610, "rcon_port": 25611}),
    ("GET", "/branches/feat/runtime", None),
    ("POST", "/branches/feat/run", {}),
    ("POST", "/branches/feat/stop", {}),
    ("POST", "/branches/feat/save-data-template", {"name": "tmpl-1"}),
    ("GET", "/branches/feat/console", None),
    ("POST", "/branches/feat/console/command", {"command": "list"}),
]

LIVE_STATE_ROUTES: list[tuple[str, str, dict | None]] = [
    ("GET", "/live-state", None),
    ("GET", "/live-state/content?path=/whitelist.json", None),
    ("PUT", "/live-state/content", {"path": "/whitelist.json", "content": "x"}),
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
@pytest.mark.parametrize(
    ("method", "path", "body"), LIVE_STATE_ROUTES, ids=[f"{m} {p}" for m, p, _ in LIVE_STATE_ROUTES]
)
async def test_live_state_simple_server_is_blocked(
    method: str, path: str, body: dict | None
) -> None:
    await _seed_server()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        if body is None:
            resp = await client.request(
                method, f"{FILES}{path}", headers=_admin_headers()
            )
        else:
            resp = await client.request(
                method, f"{FILES}{path}", headers=_admin_headers(), json=body
            )
    payload = (
        resp.json()
        if resp.headers.get("content-type", "").startswith("application/json")
        else {}
    )
    assert resp.status_code == 409
    assert payload.get("code") in {
        "SERVER_MODE_VERSIONING_DISABLED",
        "VERSIONING_REQUIRES_ADVANCED_MODE",
        "ADVANCED_MODE_DISABLED",
    }


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.name != "posix",
    reason="Advanced-mode versioning is POSIX-only in this release; Windows fails closed with 409",
)
@pytest.mark.parametrize(("method", "path", "body"), ROUTES, ids=ROUTE_IDS)
async def test_advanced_server_is_not_blocked(method: str, path: str, body: dict | None) -> None:
    await _seed_server(mode="advanced")
    status, payload = await _request(method, path, body)
    assert not (status == 409 and payload.get("code") == "SERVER_MODE_VERSIONING_DISABLED")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/branches", None),
        ("POST", "/branches", {"name": "feature"}),
        ("GET", "/preflight", None),
        ("GET", "/data-templates", None),
        ("POST", "/data-templates", {"name": "tmpl-1"}),
        ("DELETE", "/data-templates/tmpl-1", None),
        ("POST", "/branches/feat/port-set/allocate", {}),
        ("PUT", "/branches/feat/port-set", {"game_port": 25610, "rcon_port": 25611}),
        ("GET", "/branches/feat/runtime", None),
        ("POST", "/branches/feat/run", {}),
        ("POST", "/branches/feat/stop", {}),
        ("POST", "/branches/feat/save-data-template", {"name": "tmpl-1"}),
        ("GET", "/branches/feat/console", None),
        ("POST", "/branches/feat/console/command", {"command": "list"}),
    ],
    ids=[
        "GET branches",
        "POST branches",
        "GET preflight",
        "GET data-templates",
        "POST data-templates",
        "DELETE data-templates",
        "POST port-set allocate",
        "PUT port-set",
        "GET branch runtime",
        "POST branch run",
        "POST branch stop",
        "POST save-data-template",
        "GET branch console",
        "POST branch console command",
    ],
)
async def test_advanced_server_is_blocked_with_409_on_non_posix(
    method: str, path: str, body: dict | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_server(mode="advanced")
    monkeypatch.setattr(os, "name", "nt")

    status, payload = await _request(method, path, body)

    assert status == 409
    assert payload.get("code") == "SERVER_MODE_VERSIONING_DISABLED"
    assert "non-POSIX" in payload.get("message", "")


@pytest.mark.asyncio
async def test_missing_server_keeps_404_on_non_posix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(os, "name", "nt")

    status, payload = await _request("GET", "/branches", None)

    assert status == 404
    assert payload.get("code") == "NOT_FOUND"
