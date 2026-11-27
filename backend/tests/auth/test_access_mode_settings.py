import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.core.query_bus import QueryBus
from app.main import create_app
from app.modules.auth.infrastructure.jwt import create_access_token
from app.modules.auth.infrastructure.models import RoleModel, SystemStateModel, UserModel
from app.registration import register_handlers


@pytest.fixture(scope="module")
def buses():
    event_bus = EventBus()
    command_bus = CommandBus()
    query_bus = QueryBus()
    register_handlers(command_bus, query_bus, event_bus)
    return command_bus, query_bus, event_bus


@pytest.fixture
async def client(buses):
    command_bus, query_bus, event_bus = buses
    from app.api import deps

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

    async with database._session_factory() as db_session:
        sys_state = SystemStateModel(id="default", initialized=True, access_mode="LOCAL")
        db_session.add(sys_state)

        owner_role = RoleModel(id="r_owner", name="owner", description="Owner")
        db_session.add(owner_role)
        owner_user = UserModel(
            id="u_owner",
            email="owner@example.com",
            password_hash="hash",
            display_name="Owner User",
            is_active=True,
        )
        owner_user.roles.append(owner_role)
        db_session.add(owner_user)

        admin_role = RoleModel(id="r_admin", name="admin", description="Admin")
        db_session.add(admin_role)
        admin_user = UserModel(
            id="u_admin",
            email="admin@example.com",
            password_hash="hash",
            display_name="Admin User",
            is_active=True,
        )
        admin_user.roles.append(admin_role)
        db_session.add(admin_user)

        member_role = RoleModel(id="r_member", name="member", description="Member")
        db_session.add(member_role)
        member_user = UserModel(
            id="u_member",
            email="member@example.com",
            password_hash="hash",
            display_name="Member User",
            is_active=True,
        )
        member_user.roles.append(member_role)
        db_session.add(member_user)

        await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.fixture
def auth_tokens():
    owner_token = create_access_token(
        user_id="u_owner",
        roles=["owner"],
        permissions=["admin:full", "global.*"],
    )
    admin_token = create_access_token(
        user_id="u_admin",
        roles=["admin"],
        permissions=["admin:full"],
    )
    member_token = create_access_token(
        user_id="u_member",
        roles=["member"],
        permissions=["user:read"],
    )
    return {
        "owner": owner_token,
        "admin": admin_token,
        "member": member_token,
    }


@pytest.mark.asyncio
async def test_owner_can_change_access_mode(client: AsyncClient, auth_tokens: dict):
    # 1. Change LOCAL -> GLOBAL
    res = await client.put(
        "/api/v1/setup/access-mode",
        json={"access_mode": "GLOBAL"},
        headers={"Authorization": f"Bearer {auth_tokens['owner']}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["access_mode"] == "GLOBAL"
    assert data["initialized"] is True

    # Verify status endpoint reflects GLOBAL
    res_status = await client.get("/api/v1/setup/status")
    assert res_status.json()["access_mode"] == "GLOBAL"

    # 2. Change GLOBAL -> LOCAL
    res_local = await client.put(
        "/api/v1/setup/access-mode",
        json={"access_mode": "LOCAL"},
        headers={"Authorization": f"Bearer {auth_tokens['owner']}"},
    )
    assert res_local.status_code == 200
    assert res_local.json()["access_mode"] == "LOCAL"


@pytest.mark.asyncio
async def test_non_owner_cannot_change_access_mode(client: AsyncClient, auth_tokens: dict):
    # Admin attempt -> 403
    res_admin = await client.put(
        "/api/v1/setup/access-mode",
        json={"access_mode": "GLOBAL"},
        headers={"Authorization": f"Bearer {auth_tokens['admin']}"},
    )
    assert res_admin.status_code == 403

    # Member attempt -> 403
    res_member = await client.put(
        "/api/v1/setup/access-mode",
        json={"access_mode": "GLOBAL"},
        headers={"Authorization": f"Bearer {auth_tokens['member']}"},
    )
    assert res_member.status_code == 403

    # Unauthenticated attempt -> 401
    res_unauth = await client.put(
        "/api/v1/setup/access-mode",
        json={"access_mode": "GLOBAL"},
    )
    assert res_unauth.status_code == 401


@pytest.mark.asyncio
async def test_require_owner_semantics_boundary(client: AsyncClient):
    """Explicit regression test for require_owner() boundary semantics.

    The access-mode operation is Owner-only: satisfied only by a live DB `owner` role.
    `admin:full` and forged JWT `global.*` claims on non-owner DB accounts are rejected.
    """
    cases = {
        "owner role only (no admin:full, no global.*)": create_access_token(
            user_id="u_owner",
            roles=["owner"],
            permissions=[],
        ),
        "owner with admin:full": create_access_token(
            user_id="u_owner",
            roles=["owner"],
            permissions=["admin:full"],
        ),
    }
    for label, token in cases.items():
        res = await client.put(
            "/api/v1/setup/access-mode",
            json={"access_mode": "GLOBAL"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200, f"{label} should be allowed: {res.status_code} {res.text}"

    denied_cases = {
        "forged global.* claim on admin account": create_access_token(
            user_id="u_admin",
            roles=["admin"],
            permissions=["global.*"],
        ),
        "admin:full only (no owner, no global.*)": create_access_token(
            user_id="u_admin",
            roles=["admin"],
            permissions=["admin:full"],
        ),
        "member only": create_access_token(
            user_id="u_member",
            roles=["member"],
            permissions=["user:read"],
        ),
    }
    for label, token in denied_cases.items():
        res = await client.put(
            "/api/v1/setup/access-mode",
            json={"access_mode": "GLOBAL"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 403, f"{label} should be denied: {res.status_code} {res.text}"


@pytest.mark.asyncio
async def test_invalid_access_mode_rejected(client: AsyncClient, auth_tokens: dict):
    res = await client.put(
        "/api/v1/setup/access-mode",
        json={"access_mode": "INVALID_MODE"},
        headers={"Authorization": f"Bearer {auth_tokens['owner']}"},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_registration_reflects_new_access_mode(client: AsyncClient, auth_tokens: dict):
    # In LOCAL mode: POST /api/v1/users registration succeeds
    reg_local = await client.post(
        "/api/v1/users",
        json={
            "email": "newuser1@example.com",
            "password": "Password123!",
            "display_name": "New Local User",
        },
    )
    assert reg_local.status_code == 201

    # Switch to GLOBAL mode
    await client.put(
        "/api/v1/setup/access-mode",
        json={"access_mode": "GLOBAL"},
        headers={"Authorization": f"Bearer {auth_tokens['owner']}"},
    )

    # In GLOBAL mode: POST /api/v1/users registration is rejected (403)
    reg_global = await client.post(
        "/api/v1/users",
        json={
            "email": "newuser2@example.com",
            "password": "Password123!",
            "display_name": "New Global User",
        },
    )
    assert reg_global.status_code == 403

    # Switch back to LOCAL mode
    await client.put(
        "/api/v1/setup/access-mode",
        json={"access_mode": "LOCAL"},
        headers={"Authorization": f"Bearer {auth_tokens['owner']}"},
    )

    # In LOCAL mode: registration succeeds again
    reg_local_again = await client.post(
        "/api/v1/users",
        json={
            "email": "newuser3@example.com",
            "password": "Password123!",
            "display_name": "New Local User 3",
        },
    )
    assert reg_local_again.status_code == 201


@pytest.mark.asyncio
async def test_existing_users_unaffected_by_mode_switch(client: AsyncClient, auth_tokens: dict):
    # Switch LOCAL -> GLOBAL
    await client.put(
        "/api/v1/setup/access-mode",
        json={"access_mode": "GLOBAL"},
        headers={"Authorization": f"Bearer {auth_tokens['owner']}"},
    )

    # Existing member user can still fetch their profile / interact
    res = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {auth_tokens['member']}"},
    )
    assert res.status_code == 200
    assert res.json()["email"] == "member@example.com"
