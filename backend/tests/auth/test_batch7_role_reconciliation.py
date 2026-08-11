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


@pytest.mark.asyncio
async def test_admin_global_bypass_console_and_command(client: AsyncClient, tmp_path) -> None:
    await _seed_user("u_admin_b7", "admin@b7.test", "Admin")
    await _seed_server("srv-bypass", "Bypass Server", root_path=str(tmp_path / "srv-bypass"))

    admin_header = await _seed_api_key_header("u_admin_b7", ["admin:full"])

    # Authorization passed via admin:full short-circuit; server is stopped -> 404
    resp = await client.get("/api/v1/servers/srv-bypass/console", headers=admin_header)
    assert resp.status_code == 404

    resp = await client.post(
        "/api/v1/servers/srv-bypass/command",
        json={"command": "say hi"},
        headers=admin_header,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_non_member_denied_console_and_command(client: AsyncClient, tmp_path) -> None:
    await _seed_user("u_out_b7", "out@b7.test", "Outsider")
    await _seed_server("srv-denied", "Denied Server", root_path=str(tmp_path / "srv-denied"))

    non_member_header = await _seed_api_key_header("u_out_b7", [])

    resp = await client.get("/api/v1/servers/srv-denied/console", headers=non_member_header)
    assert resp.status_code == 403

    resp = await client.post(
        "/api/v1/servers/srv-denied/command",
        json={"command": "say hi"},
        headers=non_member_header,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_server_role_matrix_console_and_command(client: AsyncClient, tmp_path) -> None:
    server_root = str(tmp_path / "srv-matrix")

    owner_id, admin_id, dev_id, viewer_id = (
        "u_owner_b7",
        "u_admin_b7",
        "u_dev_b7",
        "u_viewer_b7",
    )
    for uid, email, name in (
        (owner_id, "owner@b7.test", "Owner"),
        (admin_id, "admin@b7.test", "Admin"),
        (dev_id, "dev@b7.test", "Dev"),
        (viewer_id, "viewer@b7.test", "Viewer"),
    ):
        await _seed_user(uid, email, name)

    await _seed_server("srv-matrix", "Matrix Server", root_path=server_root, owner_id=owner_id)
    await _seed_membership("m_admin_b7", "srv-matrix", admin_id, "admin")
    await _seed_membership("m_dev_b7", "srv-matrix", dev_id, "dev")
    await _seed_membership("m_viewer_b7", "srv-matrix", viewer_id, "viewer")

    owner_header = await _seed_api_key_header(owner_id, [])
    admin_header = await _seed_api_key_header(admin_id, [])
    dev_header = await _seed_api_key_header(dev_id, [])
    viewer_header = await _seed_api_key_header(viewer_id, [])

    # Owner (owner_id implicit access): console read + command allowed
    resp = await client.get("/api/v1/servers/srv-matrix/console", headers=owner_header)
    assert resp.status_code == 404
    resp = await client.post(
        "/api/v1/servers/srv-matrix/command", json={"command": "say x"}, headers=owner_header
    )
    assert resp.status_code == 404

    # Server admin (server.{id}.* wildcard): console read + command allowed
    resp = await client.get("/api/v1/servers/srv-matrix/console", headers=admin_header)
    assert resp.status_code == 404
    resp = await client.post(
        "/api/v1/servers/srv-matrix/command", json={"command": "say x"}, headers=admin_header
    )
    assert resp.status_code == 404

    # Server dev: console read + command allowed
    resp = await client.get("/api/v1/servers/srv-matrix/console", headers=dev_header)
    assert resp.status_code == 404
    resp = await client.post(
        "/api/v1/servers/srv-matrix/command", json={"command": "say x"}, headers=dev_header
    )
    assert resp.status_code == 404

    # Server viewer: console read allowed, command denied
    resp = await client.get("/api/v1/servers/srv-matrix/console", headers=viewer_header)
    assert resp.status_code == 404
    resp = await client.post(
        "/api/v1/servers/srv-matrix/command", json={"command": "say x"}, headers=viewer_header
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_invited_member_gains_target_server_access(client: AsyncClient, tmp_path) -> None:
    await _seed_server("srv-target", "Target Server", root_path=str(tmp_path / "srv-target"))
    await _seed_server("srv-other", "Other Server", root_path=str(tmp_path / "srv-other"))

    # 1. Bootstrap owner
    b_res = await client.post(
        "/api/v1/setup/bootstrap",
        json={
            "email": "owner@b7.test",
            "password": "OwnerPassword123!",
            "display_name": "Owner",
            "access_mode": "GLOBAL",
        },
    )
    assert b_res.status_code == 201
    owner_headers = {"Authorization": f"Bearer {b_res.json()['access_token']}"}

    # 2. Owner creates an invite targeting srv-target with dev role
    inv_res = await client.post(
        "/api/v1/invites",
        json={
            "email": "invited@b7.test",
            "global_role": "member",
            "server_id": "srv-target",
            "server_role": "dev",
        },
        headers=owner_headers,
    )
    assert inv_res.status_code == 201
    raw_token = inv_res.json()["token"]

    # 3. Invitee accepts and gets a membership on srv-target
    acc_res = await client.post(
        "/api/v1/invites/accept",
        json={
            "token": raw_token,
            "email": "invited@b7.test",
            "password": "InvitedPassword123!",
            "display_name": "Invited Member",
        },
    )
    assert acc_res.status_code == 201
    member_headers = {"Authorization": f"Bearer {acc_res.json()['access_token']}"}

    # 4. Invitee can reach target server console + command (auth passed -> server not running 404)
    resp = await client.get("/api/v1/servers/srv-target/console", headers=member_headers)
    assert resp.status_code == 404
    resp = await client.post(
        "/api/v1/servers/srv-target/command", json={"command": "say x"}, headers=member_headers
    )
    assert resp.status_code == 404

    # 5. Invitee denied on unassigned server
    resp = await client.get("/api/v1/servers/srv-other/console", headers=member_headers)
    assert resp.status_code == 403
    resp = await client.post(
        "/api/v1/servers/srv-other/command", json={"command": "say x"}, headers=member_headers
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_docker_execute_command_escapes_single_quotes() -> None:
    from app.modules.server.infrastructure.providers.base import ServerHandle
    from app.modules.server.infrastructure.providers.docker import DockerProvider

    provider = DockerProvider()
    handle = ServerHandle(provider="docker", server_id="s1", external_id="mcs-s1")

    captured: dict[str, str] = {}

    async def fake_docker_command(args: str) -> tuple[int, str]:
        captured["args"] = args
        return 0, "ok"

    provider._docker_command = fake_docker_command  # type: ignore[method-assign]

    await provider.execute_command(handle, "say 'hello'; touch /tmp/pwned")

    assert captured["args"] == "exec mcs-s1 rcon-cli 'say '\\''hello'\\''; touch /tmp/pwned'"
