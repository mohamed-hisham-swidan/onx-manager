import pytest
from httpx import ASGITransport, AsyncClient

from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.query_bus import QueryBus
from app.main import create_app
from app.registration import register_handlers


@pytest.fixture(scope="session")
def buses():
    event_bus = EventBus()
    command_bus = CommandBus()
    query_bus = QueryBus()
    register_handlers(command_bus, query_bus, event_bus)
    return command_bus, query_bus, event_bus


@pytest.fixture
async def client(buses, tmp_path) -> AsyncClient:
    import os

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.api import deps
    from app.core.persistence.base import Base
    from app.core.persistence.db import database

    command_bus, query_bus, event_bus = buses

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    database._engine = engine
    database._session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )

    app = create_app()

    async def get_cb() -> CommandBus:
        return command_bus

    async def get_qb() -> QueryBus:
        return query_bus

    async def get_eb() -> EventBus:
        return event_bus

    app.dependency_overrides[deps.get_command_bus] = get_cb
    app.dependency_overrides[deps.get_query_bus] = get_qb
    app.dependency_overrides[deps.get_event_bus] = get_eb

    old_data_dir = os.environ.get("MCS_SERVERS_DATA_DIR")
    test_servers_dir = tmp_path / "test_servers"
    test_servers_dir.mkdir(parents=True, exist_ok=True)
    os.environ["MCS_SERVERS_DATA_DIR"] = str(test_servers_dir)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    await engine.dispose()
    database._engine = None
    database._session_factory = None
    if old_data_dir is not None:
        os.environ["MCS_SERVERS_DATA_DIR"] = old_data_dir
    else:
        os.environ.pop("MCS_SERVERS_DATA_DIR", None)


async def _seed_user(user_id: str, email: str, name: str) -> None:
    from app.core.persistence.db import database
    from app.modules.auth.infrastructure.models import UserModel

    async with database._session_factory() as session:
        session.add(
            UserModel(
                id=user_id, email=email, password_hash="hash", display_name=name, is_active=True
            )
        )
        await session.commit()


async def _seed_server(
    server_id: str, name: str, root_path: str, owner_id: str | None = None
) -> None:
    from app.core.persistence.db import database
    from app.modules.server.infrastructure.models import ServerModel

    async with database._session_factory() as session:
        session.add(
            ServerModel(
                id=server_id,
                name=name,
                server_type="vanilla",
                minecraft_version="1.20.4",
                status="stopped",
                group_id="default",
                port=25565,
                motd="Test Server",
                max_players=20,
                gamemode="survival",
                difficulty="normal",
                root_path=root_path,
                owner_id=owner_id,
            )
        )
        await session.commit()


async def _seed_membership(membership_id: str, server_id: str, user_id: str, role: str) -> None:
    from app.core.persistence.db import database
    from app.modules.server.infrastructure.models import ServerMembershipModel

    async with database._session_factory() as session:
        session.add(
            ServerMembershipModel(id=membership_id, server_id=server_id, user_id=user_id, role=role)
        )
        await session.commit()


async def _seed_api_key_header(user_id: str, permissions: list[str]) -> dict[str, str]:
    import hashlib

    from app.core.persistence.db import database
    from app.core.security import generate_api_key, hash_api_key
    from app.modules.auth.infrastructure.models import ApiKeyModel

    raw_key = generate_api_key()
    async with database._session_factory() as session:
        session.add(
            ApiKeyModel(
                id="test-" + hashlib.sha1(raw_key.encode()).hexdigest()[:16],
                user_id=user_id,
                name="test-seeded-key",
                prefix=raw_key[:8],
                key_hash=hash_api_key(raw_key),
                permissions=",".join(sorted(permissions)),
                expires_at=None,
                is_revoked=False,
            )
        )
        await session.commit()
    return {"Authorization": f"Bearer {raw_key}"}


async def _seed_metric_points(server_id: str, count: int = 3) -> None:
    from datetime import UTC, datetime, timedelta

    from app.core.persistence.db import database
    from app.modules.monitoring.infrastructure.models import MetricPointModel

    now = datetime.now(UTC)
    async with database._session_factory() as session:
        for i in range(count):
            session.add(
                MetricPointModel(
                    server_id=server_id,
                    tps=20.0 - i,
                    players=5,
                    ram_used_mb=1024.0,
                    cpu_percent=10.0,
                    recorded_at=now - timedelta(minutes=i),
                )
            )
        await session.commit()


def _create_payload(name: str = "Second Pass Server", port: int = 25566) -> dict:
    return {
        "name": name,
        "minecraft_version": "1.21",
        "min_memory_mb": 1024,
        "max_memory_mb": 2048,
        "port": port,
        "gamemode": "survival",
        "difficulty": "easy",
    }


async def _owner_server_id(
    client: AsyncClient, header: dict[str, str], name: str = "Owner Created"
) -> str:
    from unittest.mock import AsyncMock, patch

    from app.modules.server.application.services import jar_service

    payload = _create_payload(name=name)
    with patch.object(
        jar_service,
        "download_server_jar",
        AsyncMock(return_value="/tmp/mock-jar/server.jar"),
    ):
        resp = await client.post("/api/v1/servers", json=payload, headers=header)
    assert resp.status_code == 201
    return resp.json()["server_id"]


@pytest.mark.asyncio
async def test_create_server_sets_creator_as_owner(client: AsyncClient) -> None:
    await _seed_user("u_creator_1", "creator@b7.test", "Creator")
    header = await _seed_api_key_header("u_creator_1", ["server:create"])

    server_id = await _owner_server_id(client, header, name="Creator Server")

    from sqlalchemy import select

    from app.core.persistence.db import database
    from app.modules.server.infrastructure.models import ServerModel

    async with database._session_factory() as session:
        stmt = select(ServerModel).where(ServerModel.id == server_id)
        server = (await session.execute(stmt)).scalar_one()
        assert server.owner_id == "u_creator_1"


@pytest.mark.asyncio
async def test_created_server_owner_can_start_outsider_denied(client: AsyncClient) -> None:
    from unittest.mock import AsyncMock, patch

    from app.modules.server.application.runtime_ownership import ClaimResult
    from app.modules.server.infrastructure.providers.base import (
        DeploymentResult,
        ServerRuntimeStatus,
    )

    await _seed_user("u_owner_a", "ownera@b7.test", "Owner A")
    await _seed_user("u_outsider_b", "outsiderb@b7.test", "Outsider B")
    owner_header = await _seed_api_key_header("u_owner_a", ["server:create"])
    outsider_header = await _seed_api_key_header("u_outsider_b", ["server:write", "server:start"])

    server_id = await _owner_server_id(client, owner_header, name="Isolation Server")

    mock_provider = AsyncMock()
    mock_provider.provider_type = "local"
    mock_provider.start.return_value = DeploymentResult(
        status=ServerRuntimeStatus.RUNNING,
        address="127.0.0.1",
        port=25565,
        pid=99999,
        metadata={"session_name": "onx-test-isolation"},
    )
    mock_provider.wait_ready = AsyncMock(return_value=True)

    start_mod = "app.modules.server.application.commands.start_server"
    with (
        patch(
            f"{start_mod}.provider_factory.get",
            return_value=mock_provider,
        ),
        patch(
            f"{start_mod}.RuntimeOwnershipManager.claim_localhost",
            AsyncMock(return_value=ClaimResult(success=True)),
        ),
    ):
        resp = await client.post(f"/api/v1/servers/{server_id}/start", headers=owner_header)
        assert resp.status_code != 403

        resp = await client.post(f"/api/v1/servers/{server_id}/start", headers=outsider_header)
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_member_with_server_create_can_create_and_becomes_owner(client: AsyncClient) -> None:
    await _seed_user("u_member_2", "member2@b7.test", "Member")
    header = await _seed_api_key_header("u_member_2", ["server:create", "user:read"])

    server_id = await _owner_server_id(client, header, name="Member Created")

    from sqlalchemy import select

    from app.core.persistence.db import database
    from app.modules.server.infrastructure.models import ServerModel

    async with database._session_factory() as session:
        stmt = select(ServerModel).where(ServerModel.id == server_id)
        server = (await session.execute(stmt)).scalar_one()
        assert server.owner_id == "u_member_2"


@pytest.mark.asyncio
async def test_user_without_server_create_denied_create(client: AsyncClient) -> None:
    await _seed_user("u_viewer_only", "vieweronly@b7.test", "Viewer Only")
    header = await _seed_api_key_header("u_viewer_only", ["user:read"])

    resp = await client.post("/api/v1/servers", json=_create_payload(), headers=header)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_power_role_matrix(client: AsyncClient, tmp_path) -> None:
    owner_id, admin_id, dev_id, viewer_id, outsider_id = (
        "u_pw_owner",
        "u_pw_admin",
        "u_pw_dev",
        "u_pw_viewer",
        "u_pw_out",
    )
    for uid, email, name in (
        (owner_id, "pw-owner@b7.test", "Owner"),
        (admin_id, "pw-admin@b7.test", "Admin"),
        (dev_id, "pw-dev@b7.test", "Dev"),
        (viewer_id, "pw-viewer@b7.test", "Viewer"),
        (outsider_id, "pw-out@b7.test", "Outsider"),
    ):
        await _seed_user(uid, email, name)

    await _seed_server("srv-power", "Power Server", str(tmp_path / "srv-power"), owner_id=owner_id)
    await _seed_membership("m_pw_admin", "srv-power", admin_id, "admin")
    await _seed_membership("m_pw_dev", "srv-power", dev_id, "dev")
    await _seed_membership("m_pw_viewer", "srv-power", viewer_id, "viewer")

    owner_header = await _seed_api_key_header(owner_id, [])
    admin_header = await _seed_api_key_header(admin_id, [])
    dev_header = await _seed_api_key_header(dev_id, [])
    viewer_header = await _seed_api_key_header(viewer_id, [])
    outsider_header = await _seed_api_key_header(outsider_id, [])

    for endpoint in ("start", "stop", "restart"):
        base = f"/api/v1/servers/srv-power/{endpoint}"
        for header in (owner_header, admin_header, dev_header):
            resp = await client.post(base, json={"reason": "test"}, headers=header)
            assert resp.status_code != 403, f"{endpoint} should pass auth for this role"
        for header in (viewer_header, outsider_header):
            resp = await client.post(base, json={"reason": "test"}, headers=header)
            assert resp.status_code == 403, f"{endpoint} must 403 for this role"


@pytest.mark.asyncio
async def test_power_cross_server_isolation(client: AsyncClient, tmp_path) -> None:
    await _seed_user("u_pw_dev2", "pw-dev2@b7.test", "Dev 2")
    await _seed_server("srv-a", "Server A", str(tmp_path / "srv-a"))
    await _seed_server("srv-b", "Server B", str(tmp_path / "srv-b"))
    await _seed_membership("m_pw_dev_a", "srv-a", "u_pw_dev2", "dev")

    dev_header = await _seed_api_key_header("u_pw_dev2", [])

    resp = await client.post(
        "/api/v1/servers/srv-a/start", json={"reason": "test"}, headers=dev_header
    )
    assert resp.status_code != 403

    resp = await client.post(
        "/api/v1/servers/srv-b/start", json={"reason": "test"}, headers=dev_header
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_owner_power_isolated_to_own_server(client: AsyncClient, tmp_path) -> None:
    """Owner of Server A must not gain power over Server B.

    The `owner_id` bypass in `require_server_permission` is scoped to the
    target server only — a creator of one server must not control others.
    """
    await _seed_user("u_own_x", "own-x@b7.test", "Owner X")
    await _seed_server("srv-own-a", "Owned A", str(tmp_path / "srv-own-a"), owner_id="u_own_x")
    await _seed_server("srv-own-b", "Other B", str(tmp_path / "srv-own-b"), owner_id="u_own_y")

    owner_header = await _seed_api_key_header("u_own_x", [])

    for endpoint in ("start", "stop", "restart"):
        own_resp = await client.post(
            f"/api/v1/servers/srv-own-a/{endpoint}", json={"reason": "test"}, headers=owner_header
        )
        assert own_resp.status_code != 403, f"owner should control own server: {endpoint}"

        other_resp = await client.post(
            f"/api/v1/servers/srv-own-b/{endpoint}", json={"reason": "test"}, headers=owner_header
        )
        assert other_resp.status_code == 403, f"owner must not control foreign server: {endpoint}"


@pytest.mark.asyncio
async def test_metrics_authorization_matrix(client: AsyncClient, tmp_path) -> None:
    owner_id, admin_id, dev_id, viewer_id, outsider_id, other_id = (
        "u_met_owner",
        "u_met_admin",
        "u_met_dev",
        "u_met_viewer",
        "u_met_out",
        "u_met_other",
    )
    for uid, email, name in (
        (owner_id, "met-owner@b7.test", "Owner"),
        (admin_id, "met-admin@b7.test", "Admin"),
        (dev_id, "met-dev@b7.test", "Dev"),
        (viewer_id, "met-viewer@b7.test", "Viewer"),
        (outsider_id, "met-out@b7.test", "Outsider"),
        (other_id, "met-other@b7.test", "Other Member"),
    ):
        await _seed_user(uid, email, name)

    await _seed_server("srv-met", "Metrics Server", str(tmp_path / "srv-met"), owner_id=owner_id)
    await _seed_server("srv-met-2", "Metrics Server 2", str(tmp_path / "srv-met-2"))
    await _seed_membership("m_met_admin", "srv-met", admin_id, "admin")
    await _seed_membership("m_met_dev", "srv-met", dev_id, "dev")
    await _seed_membership("m_met_viewer", "srv-met", viewer_id, "viewer")
    await _seed_membership("m_met_other", "srv-met-2", other_id, "dev")
    await _seed_metric_points("srv-met")

    admin_global = await _seed_api_key_header(admin_id, ["admin:full"])
    owner_header = await _seed_api_key_header(owner_id, [])
    dev_header = await _seed_api_key_header(dev_id, [])
    viewer_header = await _seed_api_key_header(viewer_id, [])
    outsider_header = await _seed_api_key_header(outsider_id, [])
    other_header = await _seed_api_key_header(other_id, [])

    url = "/api/v1/monitoring/metrics"
    for label, header in (
        ("owner", owner_header),
        ("admin", admin_global),
        ("dev", dev_header),
        ("viewer", viewer_header),
    ):
        resp = await client.get(url, params={"server_id": "srv-met"}, headers=header)
        assert resp.status_code == 200, f"{label} should read metrics"
        assert len(resp.json()) == 3

    resp = await client.get(url, params={"server_id": "srv-met"}, headers=outsider_header)
    assert resp.status_code == 403

    resp = await client.get(url, params={"server_id": "srv-met"}, headers=other_header)
    assert resp.status_code == 403

    resp = await client.get(url, params={"server_id": "srv-met"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_metrics_cross_server_isolation(client: AsyncClient, tmp_path) -> None:
    await _seed_user("u_met_viewer2", "met-viewer2@b7.test", "Viewer 2")
    await _seed_server("srv-isol-a", "Isolation A", str(tmp_path / "srv-isol-a"))
    await _seed_server("srv-isol-b", "Isolation B", str(tmp_path / "srv-isol-b"))
    await _seed_membership("m_isol_a", "srv-isol-a", "u_met_viewer2", "dev")
    await _seed_metric_points("srv-isol-a")
    await _seed_metric_points("srv-isol-b")

    viewer_header = await _seed_api_key_header("u_met_viewer2", [])

    url = "/api/v1/monitoring/metrics"
    resp = await client.get(url, params={"server_id": "srv-isol-a"}, headers=viewer_header)
    assert resp.status_code == 200

    resp = await client.get(url, params={"server_id": "srv-isol-b"}, headers=viewer_header)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_server_properties_download_denied_other_files_ok(
    client: AsyncClient, tmp_path
) -> None:
    await _seed_user("u_props_owner", "props-owner@b7.test", "Props Owner")

    server_root = tmp_path / "server_props"
    server_root.mkdir(parents=True, exist_ok=True)
    (server_root / ".env").write_text("SECRET=secret123\n")
    (server_root / "server.properties").write_text("rcon.password=secret123\neenable-rcon=true\n")
    (server_root / "eula.txt").write_text("eula=true")
    (server_root / "logs").mkdir(exist_ok=True)
    (server_root / "logs" / "latest.log").write_text("info line")

    await _seed_server("srv-props", "Props Server", str(server_root), owner_id="u_props_owner")
    header = await _seed_api_key_header("u_props_owner", [])

    base = "/api/v1/servers/srv-props/files/download"

    resp = await client.get(base, params={"path": ".env"}, headers=header)
    assert resp.status_code == 403

    resp = await client.get(base, params={"path": "server.properties"}, headers=header)
    assert resp.status_code == 200

    resp = await client.get(base, params={"path": "eula.txt"}, headers=header)
    assert resp.status_code == 200

    resp = await client.get(base, params={"path": "logs/latest.log"}, headers=header)
    assert resp.status_code == 200
