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
async def client(buses):
    command_bus, query_bus, event_bus = buses
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.api import deps
    from app.core.persistence.base import Base
    from app.core.persistence.db import database

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

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.mark.asyncio
class TestBatch2SetupAndInvites:
    async def test_setup_status_initial(self, client: AsyncClient) -> None:
        res = await client.get("/api/v1/setup/status")
        assert res.status_code == 200
        data = res.json()
        assert data["initialized"] is False
        assert data["access_mode"] == "LOCAL"
        assert data["user_count"] == 0

    async def test_legacy_user_registration_blocked_when_uninitialized(
        self, client: AsyncClient
    ) -> None:
        res = await client.post(
            "/api/v1/users",
            json={
                "email": "early@example.com",
                "password": "Password123!",
                "display_name": "Early User",
            },
        )
        assert res.status_code == 403
        assert "uninitialized" in res.json()["detail"].lower()

    async def test_bootstrap_instance_success(self, client: AsyncClient) -> None:
        res = await client.post(
            "/api/v1/setup/bootstrap",
            json={
                "email": "owner@example.com",
                "password": "OwnerPassword123!",
                "display_name": "Instance Owner",
                "access_mode": "GLOBAL",
            },
        )
        assert res.status_code == 201
        data = res.json()
        assert data["success"] is True
        assert "access_token" in data
        assert "refresh_token" in data

        # Verify setup status is now initialized
        res_status = await client.get("/api/v1/setup/status")
        assert res_status.json()["initialized"] is True
        assert res_status.json()["access_mode"] == "GLOBAL"
        assert res_status.json()["user_count"] == 1

    async def test_bootstrap_instance_double_attempt_fails(self, client: AsyncClient) -> None:
        # First attempt
        await client.post(
            "/api/v1/setup/bootstrap",
            json={
                "email": "owner@example.com",
                "password": "OwnerPassword123!",
                "display_name": "Instance Owner",
                "access_mode": "LOCAL",
            },
        )
        # Second attempt
        res = await client.post(
            "/api/v1/setup/bootstrap",
            json={
                "email": "owner2@example.com",
                "password": "OwnerPassword123!",
                "display_name": "Owner 2",
                "access_mode": "LOCAL",
            },
        )
        assert res.status_code == 409 or res.status_code == 400

    async def test_legacy_registration_in_global_mode_blocked(self, client: AsyncClient) -> None:
        # Bootstrap in GLOBAL mode
        await client.post(
            "/api/v1/setup/bootstrap",
            json={
                "email": "owner@example.com",
                "password": "OwnerPassword123!",
                "display_name": "Instance Owner",
                "access_mode": "GLOBAL",
            },
        )
        res = await client.post(
            "/api/v1/users",
            json={
                "email": "random@example.com",
                "password": "Password123!",
                "display_name": "Random User",
            },
        )
        assert res.status_code == 403
        assert "disabled in global" in res.json()["detail"].lower()

    async def test_invite_lifecycle(self, client: AsyncClient) -> None:
        # 1. Bootstrap instance to obtain owner tokens
        b_res = await client.post(
            "/api/v1/setup/bootstrap",
            json={
                "email": "owner@example.com",
                "password": "OwnerPassword123!",
                "display_name": "Instance Owner",
                "access_mode": "GLOBAL",
            },
        )
        token = b_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 2. Create Invite as Owner
        inv_res = await client.post(
            "/api/v1/invites",
            json={
                "email": "invited@example.com",
                "global_role": "member",
                "expires_in_hours": 24,
            },
            headers=headers,
        )
        assert inv_res.status_code == 201
        inv_data = inv_res.json()
        raw_invite_token = inv_data["token"]
        invite_id = inv_data["invite_id"]

        # 3. List Invites
        list_res = await client.get("/api/v1/invites", headers=headers)
        assert list_res.status_code == 200
        assert len(list_res.json()) == 1

        # 4. Verify Invite Token (Public)
        verify_res = await client.get(f"/api/v1/invites/verify/{raw_invite_token}")
        assert verify_res.status_code == 200
        assert verify_res.json()["valid"] is True
        assert verify_res.json()["email"] == "invited@example.com"

        # 5. Accept Invite (Public)
        accept_res = await client.post(
            "/api/v1/invites/accept",
            json={
                "token": raw_invite_token,
                "email": "invited@example.com",
                "password": "InvitedUserPassword123!",
                "display_name": "Invited Member",
            },
        )
        assert accept_res.status_code == 201
        assert "access_token" in accept_res.json()

        # 6. Verify token is now invalid / consumed
        v2_res = await client.get(f"/api/v1/invites/verify/{raw_invite_token}")
        assert v2_res.json()["valid"] is False

    async def test_revoke_invite(self, client: AsyncClient) -> None:
        b_res = await client.post(
            "/api/v1/setup/bootstrap",
            json={
                "email": "owner@example.com",
                "password": "OwnerPassword123!",
                "display_name": "Instance Owner",
                "access_mode": "GLOBAL",
            },
        )
        token = b_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        inv_res = await client.post(
            "/api/v1/invites",
            json={"global_role": "member"},
            headers=headers,
        )
        inv_data = inv_res.json()
        raw_invite_token = inv_data["token"]
        invite_id = inv_data["invite_id"]

        # Revoke invite
        del_res = await client.delete(f"/api/v1/invites/{invite_id}", headers=headers)
        assert del_res.status_code == 204

        # Verify token is invalid
        v_res = await client.get(f"/api/v1/invites/verify/{raw_invite_token}")
        assert v_res.json()["valid"] is False

    async def test_local_registration_assigns_viewer_role(self, client: AsyncClient) -> None:
        # Bootstrap in LOCAL mode
        await client.post(
            "/api/v1/setup/bootstrap",
            json={
                "email": "owner@example.com",
                "password": "OwnerPassword123!",
                "display_name": "Instance Owner",
                "access_mode": "LOCAL",
            },
        )
        reg_res = await client.post(
            "/api/v1/users",
            json={
                "email": "localuser@example.com",
                "password": "LocalPassword123!",
                "display_name": "Local Viewer",
            },
        )
        assert reg_res.status_code == 201
        data = reg_res.json()
        assert "viewer" in data["roles"]

    async def test_privilege_escalation_role_grant_authorization(self, client: AsyncClient) -> None:
        # 1. Bootstrap in LOCAL mode
        b_res = await client.post(
            "/api/v1/setup/bootstrap",
            json={
                "email": "owner@example.com",
                "password": "OwnerPassword123!",
                "display_name": "Instance Owner",
                "access_mode": "LOCAL",
            },
        )
        owner_token = b_res.json()["access_token"]
        owner_headers = {"Authorization": f"Bearer {owner_token}"}

        # 2. Register normal user in LOCAL mode (gets viewer role)
        reg_res = await client.post(
            "/api/v1/users",
            json={
                "email": "viewer@example.com",
                "password": "ViewerPassword123!",
                "display_name": "Viewer User",
            },
        )
        assert reg_res.status_code == 201

        # 3. Create a member invite as Owner for member@example.com
        member_inv = await client.post(
            "/api/v1/invites",
            json={"email": "member@example.com", "global_role": "member"},
            headers=owner_headers,
        )
        assert member_inv.status_code == 201
        member_token = member_inv.json()["token"]

        # 4. Accept member invite
        acc_res = await client.post(
            "/api/v1/invites/accept",
            json={
                "token": member_token,
                "email": "member@example.com",
                "password": "MemberPassword123!",
                "display_name": "Member User",
            },
        )
        assert acc_res.status_code == 201
        member_access_token = acc_res.json()["access_token"]
        member_headers = {"Authorization": f"Bearer {member_access_token}"}

        # 5. Member attempts to create an Owner invitation -> Expect rejection (403)
        esc_owner_res = await client.post(
            "/api/v1/invites",
            json={"global_role": "owner"},
            headers=member_headers,
        )
        assert esc_owner_res.status_code == 403

        # 6. Member attempts to create an Admin invitation -> Expect rejection (403)
        esc_admin_res = await client.post(
            "/api/v1/invites",
            json={"global_role": "admin"},
            headers=member_headers,
        )
        assert esc_admin_res.status_code == 403

        # 7. Member attempts to create a Server Admin invitation without server admin rights -> Expect rejection (403)
        esc_server_res = await client.post(
            "/api/v1/invites",
            json={"server_id": "nonexistent_server", "server_role": "admin"},
            headers=member_headers,
        )
        assert (
            esc_server_res.status_code == 403
            or esc_server_res.status_code == 422
            or esc_server_res.status_code == 404
        )

        # 8. Owner creates an Owner invitation -> Expect success (201)
        owner_inv_res = await client.post(
            "/api/v1/invites",
            json={"global_role": "owner"},
            headers=owner_headers,
        )
        assert owner_inv_res.status_code == 201
