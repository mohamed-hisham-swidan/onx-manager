from datetime import UTC
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.core.query_bus import QueryBus
from tests.api.test_api_endpoints import _seed_api_key_header


@pytest.fixture(scope="session")
def buses():
    from app.registration import register_handlers

    event_bus = EventBus()
    command_bus = CommandBus()
    query_bus = QueryBus()
    register_handlers(command_bus, query_bus, event_bus)
    return command_bus, query_bus, event_bus


@pytest.fixture(autouse=True)
def _override_deps(buses) -> None:
    command_bus, query_bus, event_bus = buses
    from app.api import deps
    from app.main import app

    async def get_cb() -> CommandBus:
        return command_bus

    async def get_qb() -> QueryBus:
        return query_bus

    async def get_eb() -> EventBus:
        return event_bus

    app.dependency_overrides[deps.get_command_bus] = get_cb
    app.dependency_overrides[deps.get_query_bus] = get_qb
    app.dependency_overrides[deps.get_event_bus] = get_eb


@pytest.fixture(autouse=True)
async def _reset_supervisor_singleton():
    from app.modules.exposure.infrastructure.cloudflared import (
        get_cloudflared_supervisor,
        reset_cloudflared_supervisor,
    )
    from app.modules.exposure.infrastructure.playit_agent import (
        get_playit_supervisor,
        reset_playit_supervisor,
    )

    await get_cloudflared_supervisor().stop()
    await get_playit_supervisor().stop()
    reset_cloudflared_supervisor()
    reset_playit_supervisor()
    yield
    await get_cloudflared_supervisor().stop()
    await get_playit_supervisor().stop()
    reset_cloudflared_supervisor()
    reset_playit_supervisor()


@pytest.fixture(autouse=True)
def _mock_playit_subprocess() -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_proc = AsyncMock()
    mock_proc.pid = 99999
    mock_proc.returncode = None
    mock_proc.wait = AsyncMock(return_value=0)
    mock_proc.terminate = MagicMock()
    mock_proc.kill = MagicMock()
    mock_proc.stdout = AsyncMock(readline=AsyncMock(return_value=b""))
    mock_proc.stderr = AsyncMock(readline=AsyncMock(return_value=b""))

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        patch("os.kill"),
        patch("os.killpg"),
        patch("os.getpgid", return_value=99999),
    ):
        yield


@pytest.fixture
async def exposure_client(tmp_path):
    import os

    from httpx import ASGITransport, AsyncClient

    from app.api.v1.middleware.rate_limit import InMemoryRateLimitStore
    from app.main import app

    stack = getattr(app, "middleware_stack", None)
    while stack is not None:
        if isinstance(stack, InMemoryRateLimitStore):
            stack._hits.clear()
        store = getattr(stack, "_store", None)
        if isinstance(store, InMemoryRateLimitStore):
            store._hits.clear()
        stack = getattr(stack, "app", None)

    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    database._engine = engine
    database._session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )

    async with database._session_factory() as sess:
        from app.modules.auth.infrastructure.models import SystemStateModel
        sess.add(SystemStateModel(id="default", initialized=True, access_mode="LOCAL"))
        await sess.commit()

    old_data_dir = os.environ.get("MCS_SERVERS_DATA_DIR")
    test_servers_dir = tmp_path / "test_servers"
    test_servers_dir.mkdir(parents=True, exist_ok=True)
    os.environ["MCS_SERVERS_DATA_DIR"] = str(test_servers_dir)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await engine.dispose()
    database._engine = None
    database._session_factory = None
    if old_data_dir is not None:
        os.environ["MCS_SERVERS_DATA_DIR"] = old_data_dir
    else:
        os.environ.pop("MCS_SERVERS_DATA_DIR", None)


_user_counter = 0


async def _seed_user(client) -> dict:
    global _user_counter
    _user_counter += 1
    resp = await client.post(
        "/api/v1/users",
        json={
            "email": f"expo{_user_counter}@test.com",
            "password": "password123",
            "display_name": "Expo User",
        },
    )
    assert resp.status_code == 201
    return resp.json()


async def _owner_header(_client, user: dict) -> dict[str, str]:
    from app.modules.auth.infrastructure.jwt import create_access_token

    token = create_access_token(
        user_id=user["user_id"],
        roles=["owner"],
        permissions=["server:create", "server:write", "server:delete", "server:read"],
    )
    return {"Authorization": f"Bearer {token}"}


async def _create_server(client, header: dict[str, str]) -> dict:
    from unittest.mock import AsyncMock, patch

    payload = {
        "name": "Expo Test Server",
        "minecraft_version": "1.21",
        "min_memory_mb": 1024,
        "max_memory_mb": 2048,
        "port": 25565,
        "gamemode": "survival",
        "difficulty": "easy",
    }
    with patch(
        "app.modules.server.application.services.jar_service.download_server_jar",
        AsyncMock(return_value="/tmp/mock-jar/server.jar"),
    ):
        resp = await client.post("/api/v1/servers", json=payload, headers=header)
    assert resp.status_code == 201
    return resp.json()


async def _grant_exposure(
    _client, server_id: str, user_id: str, *, can_manage: bool, can_view: bool
) -> None:
    import uuid
    from datetime import datetime

    from app.modules.exposure.infrastructure.models import ServerExposureGrantModel

    now = datetime.now(UTC)
    async with database._session_factory() as session:
        session.add(
            ServerExposureGrantModel(
                id=uuid.uuid4().hex,
                server_id=server_id,
                user_id=user_id,
                can_manage=can_manage,
                can_view=can_view,
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()


async def _seed_user_with_perm(client, permissions: list[str]) -> dict:
    user = await _seed_user(client)
    header = await _seed_api_key_header(client, user["user_id"], permissions)
    return user, header


async def test_exposure_agent_status_requires_permission(exposure_client) -> None:
    user, header = await _seed_user_with_perm(exposure_client, ["exposure.credentials.manage"])
    resp = await exposure_client.get("/api/v1/exposure/agent", headers=header)
    assert resp.status_code == 200
    data = resp.json()
    assert data["claimed"] is False
    assert data["claim_active"] is False
    assert "secret_ciphertext" not in data


async def test_exposure_agent_claim_requires_owner(exposure_client) -> None:
    user = await _seed_user(exposure_client)
    non_owner = await _seed_api_key_header(
        exposure_client, user["user_id"], ["exposure.credentials.manage"]
    )
    resp = await exposure_client.post("/api/v1/exposure/agent/claim", headers=non_owner)
    assert resp.status_code == 403

    owner = await _owner_header(exposure_client, user)
    resp = await exposure_client.post("/api/v1/exposure/agent/claim", headers=owner)
    assert resp.status_code == 201
    data = resp.json()
    assert data["claim_code"]
    assert data["claim_url"]
    assert "expires_at" in data


async def test_exposure_agent_claim_active_conflict(exposure_client) -> None:
    user = await _seed_user(exposure_client)
    owner = await _owner_header(exposure_client, user)
    resp = await exposure_client.post("/api/v1/exposure/agent/claim", headers=owner)
    assert resp.status_code == 201

    resp2 = await exposure_client.post("/api/v1/exposure/agent/claim", headers=owner)
    assert resp2.status_code == 409
    assert resp2.json()["error_code"] == "CLAIM_ACTIVE"


async def test_exposure_agent_reset_and_remove_credentials(exposure_client) -> None:
    user = await _seed_user(exposure_client)
    owner = await _owner_header(exposure_client, user)
    resp = await exposure_client.post("/api/v1/exposure/agent/reset", headers=owner)
    assert resp.status_code == 200
    assert resp.json()["claimed"] is False

    resp2 = await exposure_client.post("/api/v1/exposure/credentials/remove", headers=owner)
    assert resp2.status_code == 200
    assert resp2.json()["success"] is True


async def test_exposure_agent_reconcile(exposure_client) -> None:
    user = await _seed_user(exposure_client)
    header = await _seed_api_key_header(
        exposure_client, user["user_id"], ["exposure.credentials.manage"]
    )
    resp = await exposure_client.post("/api/v1/exposure/agent/reconcile", headers=header)
    assert resp.status_code == 200
    assert resp.json()["reconciled"] is True


async def test_exposure_stop_all(exposure_client) -> None:
    user = await _seed_user(exposure_client)
    owner = await _owner_header(exposure_client, user)
    resp = await exposure_client.post("/api/v1/exposure/stop-all", headers=owner)
    assert resp.status_code == 200
    assert resp.json()["disabled_count"] == 0


async def _mock_supervisor() -> object:
    from unittest.mock import AsyncMock

    supervisor = AsyncMock()
    supervisor.start = AsyncMock()
    supervisor.stop = AsyncMock()
    supervisor.is_running = False
    return supervisor


async def _mock_cloudflare() -> object:
    from unittest.mock import AsyncMock

    client = AsyncMock()
    client.create_named_tunnel = AsyncMock(
        return_value=type(
            "TunnelProvisionResult",
            (),
            {"tunnel_id": "tun-abc123", "token": "fake-tunnel-token-123"},
        )()
    )
    client.configure_ingress = AsyncMock(return_value=None)
    client.create_cname = AsyncMock(return_value=None)
    return client


async def test_panel_exposure_roundtrip(exposure_client) -> None:
    from unittest.mock import patch

    from app.modules.exposure.application import commands as exposure_commands

    user = await _seed_user(exposure_client)
    owner = await _owner_header(exposure_client, user)

    resp = await exposure_client.get("/api/v1/exposure/panel", headers=owner)
    assert resp.status_code == 200
    assert resp.json()["method"] == "none"

    mock_client = await _mock_cloudflare()
    supervisor = await _mock_supervisor()
    with (
        patch.object(exposure_commands, "CloudflareClient", return_value=mock_client),
        patch(
            "app.modules.exposure.application.commands.get_cloudflared_supervisor",
            return_value=supervisor,
        ),
    ):
        resp = await exposure_client.put(
            "/api/v1/exposure/panel",
            json={
                "method": "cloudflare_tunnel",
                "desired_state": "ENABLED",
                "cloudflare_token": "token-123",
                "hostname": "panel.example.com",
            },
            headers=owner,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["method"] == "cloudflare_tunnel"
    assert data["desired_state"] == "ENABLED"
    assert data["status"] == "STARTING"
    assert data["cloudflare_tunnel_id"] == "tun-abc123"
    assert data["public_address"] == "panel.example.com"
    assert "token" not in data
    mock_client.create_named_tunnel.assert_awaited_once()
    mock_client.create_cname.assert_awaited_once()
    supervisor.start.assert_awaited_once()

    # Idempotent re-issue does not re-provision.
    mock_client.reset_mock()
    with patch.object(exposure_commands, "CloudflareClient", return_value=mock_client):
        resp = await exposure_client.put(
            "/api/v1/exposure/panel",
            json={
                "method": "cloudflare_tunnel",
                "desired_state": "ENABLED",
                "cloudflare_token": "token-123",
                "hostname": "panel.example.com",
            },
            headers=owner,
        )
    assert resp.status_code == 200
    mock_client.create_named_tunnel.assert_not_awaited()


async def test_panel_exposure_requires_owner(exposure_client) -> None:
    user = await _seed_user(exposure_client)
    # A granted non-owner with the panel permission is still denied.
    header = await _seed_api_key_header(
        exposure_client, user["user_id"], ["exposure.panel.manage"]
    )
    resp = await exposure_client.get("/api/v1/exposure/panel", headers=header)
    assert resp.status_code == 403

    resp = await exposure_client.put(
        "/api/v1/exposure/panel",
        json={"method": "cloudflare_tunnel", "desired_state": "ENABLED"},
        headers=header,
    )
    assert resp.status_code == 403


async def test_panel_exposure_owner_allowed(exposure_client) -> None:
    user = await _seed_user(exposure_client)
    owner = await _owner_header(exposure_client, user)

    resp = await exposure_client.get("/api/v1/exposure/panel", headers=owner)
    assert resp.status_code == 200
    assert resp.json()["method"] == "none"

    resp = await exposure_client.put(
        "/api/v1/exposure/panel",
        json={"method": "none", "desired_state": "DISABLED"},
        headers=owner,
    )
    assert resp.status_code == 200


async def test_panel_exposure_admin_full_without_owner_denied(exposure_client) -> None:
    """Decision 4: admin:full alone is NOT sufficient for panel exposure."""
    user = await _seed_user(exposure_client)
    admin_header = await _seed_api_key_header(exposure_client, user["user_id"], ["admin:full"])

    resp = await exposure_client.get("/api/v1/exposure/panel", headers=admin_header)
    assert resp.status_code == 403

    resp = await exposure_client.put(
        "/api/v1/exposure/panel",
        json={"method": "cloudflare_tunnel", "desired_state": "ENABLED"},
        headers=admin_header,
    )
    assert resp.status_code == 403


async def test_panel_exposure_ordinary_member_denied(exposure_client) -> None:
    user = await _seed_user(exposure_client)
    member_header = await _seed_api_key_header(exposure_client, user["user_id"], ["server:read"])

    resp = await exposure_client.get("/api/v1/exposure/panel", headers=member_header)
    assert resp.status_code == 403

    resp = await exposure_client.put(
        "/api/v1/exposure/panel",
        json={"method": "cloudflare_tunnel", "desired_state": "ENABLED"},
        headers=member_header,
    )
    assert resp.status_code == 403


async def test_panel_exposure_enable_requires_token_and_hostname(exposure_client) -> None:
    user = await _seed_user(exposure_client)
    owner = await _owner_header(exposure_client, user)

    resp = await exposure_client.put(
        "/api/v1/exposure/panel",
        json={"method": "cloudflare_tunnel", "desired_state": "ENABLED"},
        headers=owner,
    )
    assert resp.status_code == 422

    resp = await exposure_client.put(
        "/api/v1/exposure/panel",
        json={
            "method": "cloudflare_tunnel",
            "desired_state": "ENABLED",
            "cloudflare_token": "token-123",
        },
        headers=owner,
    )
    assert resp.status_code == 422


async def test_panel_exposure_auth_error_maps_to_reclaim(exposure_client) -> None:
    from unittest.mock import AsyncMock, patch

    from app.modules.exposure.application import commands as exposure_commands
    from app.modules.exposure.infrastructure.cloudflare import CloudflareAuthError

    user = await _seed_user(exposure_client)
    owner = await _owner_header(exposure_client, user)

    mock_client = AsyncMock()
    mock_client.create_named_tunnel = AsyncMock(
        side_effect=CloudflareAuthError("invalid token")
    )
    with patch.object(exposure_commands, "CloudflareClient", return_value=mock_client):
        resp = await exposure_client.put(
            "/api/v1/exposure/panel",
            json={
                "method": "cloudflare_tunnel",
                "desired_state": "ENABLED",
                "cloudflare_token": "bad-token",
                "hostname": "panel.example.com",
            },
            headers=owner,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "RECLAIM_REQUIRED"
    assert data["error_code"] == "RECLAIM_REQUIRED"
    assert data["cloudflare_tunnel_id"] is None
    assert data["public_address"] is None


async def test_panel_exposure_disable_clears_credentials(exposure_client) -> None:
    from unittest.mock import patch

    from app.modules.exposure.application import commands as exposure_commands

    user = await _seed_user(exposure_client)
    owner = await _owner_header(exposure_client, user)

    mock_client = await _mock_cloudflare()
    supervisor = await _mock_supervisor()
    with (
        patch.object(exposure_commands, "CloudflareClient", return_value=mock_client),
        patch(
            "app.modules.exposure.application.commands.get_cloudflared_supervisor",
            return_value=supervisor,
        ),
    ):
        resp = await exposure_client.put(
            "/api/v1/exposure/panel",
            json={
                "method": "cloudflare_tunnel",
                "desired_state": "ENABLED",
                "cloudflare_token": "token-123",
                "hostname": "panel.example.com",
            },
            headers=owner,
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "STARTING"

    with (
        patch.object(exposure_commands, "CloudflareClient", return_value=mock_client),
        patch(
            "app.modules.exposure.application.commands.get_cloudflared_supervisor",
            return_value=supervisor,
        ),
    ):
        resp = await exposure_client.put(
            "/api/v1/exposure/panel",
            json={"method": "cloudflare_tunnel", "desired_state": "DISABLED"},
            headers=owner,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["desired_state"] == "DISABLED"
    assert data["status"] == "DISABLED"
    assert data["cloudflare_tunnel_id"] is None
    assert data["public_address"] is None
    assert data["error_code"] is None
    supervisor.stop.assert_awaited_once()


async def test_server_exposure_requires_grant(exposure_client) -> None:
    owner_user = await _seed_user(exposure_client)
    owner = await _owner_header(exposure_client, owner_user)
    server = await _create_server(exposure_client, owner)

    stranger_user = await _seed_user(exposure_client)
    stranger = await _seed_api_key_header(
        exposure_client, stranger_user["user_id"], ["server.{id}.exposure"]
    )

    resp = await exposure_client.get(
        f"/api/v1/servers/{server['server_id']}/exposure", headers=stranger
    )
    assert resp.status_code == 403


async def test_server_exposure_owner_bypass_and_target_flow(exposure_client) -> None:
    owner_user = await _seed_user(exposure_client)
    owner = await _owner_header(exposure_client, owner_user)
    server = await _create_server(exposure_client, owner)
    sid = server["server_id"]

    resp = await exposure_client.get(f"/api/v1/servers/{sid}/exposure", headers=owner)
    assert resp.status_code == 404

    resp = await exposure_client.post(f"/api/v1/servers/{sid}/exposure/targets", headers=owner)
    assert resp.status_code == 201
    target = resp.json()
    assert target["local_port"] == 25565
    assert target["service_type"] == "java"
    assert target["protocol"] == "tcp"

    resp = await exposure_client.put(
        f"/api/v1/servers/{sid}/exposure",
        json={"method": "playit", "desired_state": "ENABLED"},
        headers=owner,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["desired_state"] == "ENABLED"
    assert data["aggregate_status"] == "CLAIM_REQUIRED"
    assert len(data["targets"]) == 1

    resp = await exposure_client.get(f"/api/v1/servers/{sid}/exposure", headers=owner)
    assert resp.status_code == 200
    assert resp.json()["targets"][0]["local_port"] == 25565

    resp = await exposure_client.get(f"/api/v1/servers/{sid}/exposure/targets", headers=owner)
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp = await exposure_client.patch(
        f"/api/v1/servers/{sid}/exposure",
        json={"desired_state": "DISABLED"},
        headers=owner,
    )
    assert resp.status_code == 200
    assert resp.json()["desired_state"] == "DISABLED"

    resp = await exposure_client.delete(f"/api/v1/servers/{sid}/exposure", headers=owner)
    assert resp.status_code == 204

    resp = await exposure_client.get(f"/api/v1/servers/{sid}/exposure", headers=owner)
    assert resp.status_code == 404


async def test_server_exposure_grant_holder_manage(exposure_client) -> None:
    owner_user = await _seed_user(exposure_client)
    owner = await _owner_header(exposure_client, owner_user)
    server = await _create_server(exposure_client, owner)
    sid = server["server_id"]

    grantee_user = await _seed_user(exposure_client)
    grantee = await _seed_api_key_header(
        exposure_client,
        grantee_user["user_id"],
        ["server.{id}.exposure", "server.{id}.exposure.view"],
    )
    await _grant_exposure(
        exposure_client, sid, grantee_user["user_id"], can_manage=True, can_view=True
    )

    resp = await exposure_client.post(f"/api/v1/servers/{sid}/exposure/targets", headers=grantee)
    assert resp.status_code == 201

    resp = await exposure_client.get(f"/api/v1/servers/{sid}/exposure", headers=grantee)
    assert resp.status_code == 200


async def test_server_exposure_deny_list_port(exposure_client) -> None:
    from unittest.mock import AsyncMock, patch

    owner_user = await _seed_user(exposure_client)
    owner = await _owner_header(exposure_client, owner_user)

    with patch(
        "app.modules.server.application.services.jar_service.download_server_jar",
        AsyncMock(return_value="/tmp/mock-jar/server.jar"),
    ):
        resp = await exposure_client.post(
            "/api/v1/servers",
            json={
                "name": "Deny List Server",
                "minecraft_version": "1.21",
                "min_memory_mb": 1024,
                "max_memory_mb": 2048,
                "port": 25575,
                "gamemode": "survival",
                "difficulty": "easy",
            },
            headers=owner,
        )
    assert resp.status_code == 201
    sid = resp.json()["server_id"]

    resp = await exposure_client.post(f"/api/v1/servers/{sid}/exposure/targets", headers=owner)
    assert resp.status_code == 422


async def test_server_exposure_no_targets_on_enable(exposure_client) -> None:
    owner_user = await _seed_user(exposure_client)
    owner = await _owner_header(exposure_client, owner_user)
    server = await _create_server(exposure_client, owner)
    sid = server["server_id"]

    resp = await exposure_client.put(
        f"/api/v1/servers/{sid}/exposure",
        json={"method": "playit", "desired_state": "ENABLED"},
        headers=owner,
    )
    assert resp.status_code == 422


async def test_panel_exposure_playit_http_api(exposure_client) -> None:
    owner_user = await _seed_user(exposure_client)
    owner = await _owner_header(exposure_client, owner_user)

    with patch("app.modules.exposure.application.commands.get_playit_supervisor") as mock_sup:
        mock_sup.return_value = AsyncMock()
        resp = await exposure_client.put(
            "/api/v1/exposure/panel",
            json={"method": "playit_http", "desired_state": "ENABLED"},
            headers=owner,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["method"] == "playit_http"
        assert data["status"] == "CLAIM_REQUIRED"
        assert data["tls"] is True
        assert data["protocol"] == "https"


async def test_panel_exposure_port_forward_api(exposure_client) -> None:
    owner_user = await _seed_user(exposure_client)
    owner = await _owner_header(exposure_client, owner_user)

    from app.modules.exposure.infrastructure.upnp import UPnPResult

    mock_result = UPnPResult(
        success=True,
        external_ip="198.51.100.99",
        external_port=8080,
        internal_port=8000,
    )

    with (
        patch(
            "app.modules.exposure.application.commands.get_active_panel_bind",
            return_value=("0.0.0.0", 8000),
        ),
        patch(
            "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
            return_value=mock_result,
        ),
    ):
        resp = await exposure_client.put(
            "/api/v1/exposure/panel",
            json={"method": "port_forward", "desired_state": "ENABLED", "external_port": 8080},
            headers=owner,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["method"] == "port_forward"
        assert data["desired_state"] == "ENABLED"
        assert data["status"] == "ACTIVE"
        assert data["public_address"] == "http://198.51.100.99:8080"
        assert data["tls"] is False
        assert data["protocol"] == "http"
        assert data["external_port"] == 8080


async def test_server_exposure_port_forward_api(exposure_client) -> None:
    owner_user = await _seed_user(exposure_client)
    owner = await _owner_header(exposure_client, owner_user)
    server = await _create_server(exposure_client, owner)
    sid = server["server_id"]

    await exposure_client.post(f"/api/v1/servers/{sid}/exposure/targets", headers=owner)

    from app.modules.exposure.infrastructure.upnp import UPnPResult

    mock_result = UPnPResult(
        success=True,
        external_ip="198.51.100.4",
        external_port=25565,
        internal_port=25565,
    )

    with patch(
        "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
        return_value=mock_result,
    ):
        resp = await exposure_client.put(
            f"/api/v1/servers/{sid}/exposure",
            json={"method": "port_forward", "desired_state": "ENABLED"},
            headers=owner,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["method"] == "port_forward"
        assert data["desired_state"] == "ENABLED"
        assert data["aggregate_status"] == "ACTIVE"
        assert len(data["targets"]) == 1
        assert data["targets"][0]["status"] == "ACTIVE"
        assert data["targets"][0]["public_address"] == "198.51.100.4:25565"


async def test_server_exposure_port_forward_disable_api(exposure_client) -> None:
    owner_user = await _seed_user(exposure_client)
    owner = await _owner_header(exposure_client, owner_user)
    server = await _create_server(exposure_client, owner)
    sid = server["server_id"]

    await exposure_client.post(f"/api/v1/servers/{sid}/exposure/targets", headers=owner)

    from app.modules.exposure.infrastructure.upnp import UPnPResult

    mock_result = UPnPResult(
        success=True,
        external_ip="198.51.100.4",
        external_port=25565,
        internal_port=25565,
    )

    with patch(
        "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
        return_value=mock_result,
    ):
        await exposure_client.put(
            f"/api/v1/servers/{sid}/exposure",
            json={"method": "port_forward", "desired_state": "ENABLED"},
            headers=owner,
        )

    with patch(
        "app.modules.exposure.application.commands.AsyncUPnPService.delete_mapping",
        return_value=True,
    ) as mock_delete:
        resp = await exposure_client.patch(
            f"/api/v1/servers/{sid}/exposure",
            json={"desired_state": "DISABLED"},
            headers=owner,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["desired_state"] == "DISABLED"
        assert data["aggregate_status"] == "DISABLED"
        assert mock_delete.called
