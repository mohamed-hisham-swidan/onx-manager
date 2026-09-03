import pytest
from httpx import AsyncClient

from app.core.persistence.db import database
from app.modules.auth.infrastructure.models import UserModel
from app.modules.server.infrastructure.models import ServerMembershipModel, ServerModel
from tests.api.test_api_endpoints import _seed_api_key_header, _seed_plugin

pytest_plugins = ["tests.api.test_api_endpoints"]


async def _seed_server(server_id: str, name: str, owner_id: str | None = None) -> None:
    async with database._session_factory() as session:
        server = ServerModel(
            id=server_id,
            name=name,
            server_type="paper",
            minecraft_version="1.21.1",
            status="stopped",
            group_id="default",
            port=25565,
            motd="Test Server",
            max_players=20,
            gamemode="survival",
            difficulty="normal",
            root_path="/tmp/fake-server",
            owner_id=owner_id,
        )
        session.add(server)
        await session.commit()


async def _seed_membership(membership_id: str, server_id: str, user_id: str, role: str) -> None:
    async with database._session_factory() as session:
        session.add(
            ServerMembershipModel(id=membership_id, server_id=server_id, user_id=user_id, role=role)
        )
        await session.commit()


async def _seed_user(user_id: str, email: str, name: str) -> None:
    async with database._session_factory() as session:
        session.add(
            UserModel(
                id=user_id, email=email, password_hash="hash", display_name=name, is_active=True
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_plugins_server_authorization(
    client: AsyncClient, created_user: dict  # noqa: ARG001
) -> None:
    server_a = "srv-plug-a"
    server_b = "srv-plug-b"
    owner_a = "u_owner_a"
    user_no_access = "u_no_access"
    user_with_manage = "u_with_manage"

    await _seed_user(owner_a, "owner_a@test.com", "Owner A")
    await _seed_user(user_no_access, "no_access@test.com", "No Access")
    await _seed_user(user_with_manage, "manage@test.com", "Global Plugin Manager")

    await _seed_server(server_a, "Server A", owner_id=owner_a)
    await _seed_server(server_b, "Server B", owner_id=user_with_manage)

    plugin_a = await _seed_plugin(server_a, "WorldEdit")

    # Header for user with no access to Server A
    no_access_header = await _seed_api_key_header(client, user_no_access, [])
    # Header for user with global plugin:manage but no membership on Server A
    manage_header = await _seed_api_key_header(client, user_with_manage, ["plugin:manage"])
    # Header for Server A owner who also has plugin:manage
    owner_header = await _seed_api_key_header(client, owner_a, ["plugin:manage"])

    # (a) User without access to Server A gets 403 when listing/getting server A's plugins
    resp_list = await client.get(f"/api/v1/servers/{server_a}/plugins", headers=no_access_header)
    assert resp_list.status_code == 403

    resp_get = await client.get(
        f"/api/v1/servers/{server_a}/plugins/{plugin_a}", headers=no_access_header
    )
    assert resp_get.status_code == 403

    # (b) User with global plugin:manage but no server-scoped permission on server A
    # gets 403 attempting to mutate plugins
    resp_uninstall = await client.delete(
        f"/api/v1/servers/{server_a}/plugins/{plugin_a}",
        headers=manage_header,
    )
    assert resp_uninstall.status_code == 403

    resp_enable = await client.post(
        f"/api/v1/servers/{server_a}/plugins/{plugin_a}/enable",
        headers=manage_header,
    )
    assert resp_enable.status_code == 403

    resp_disable = await client.post(
        f"/api/v1/servers/{server_a}/plugins/{plugin_a}/disable",
        headers=manage_header,
    )
    assert resp_disable.status_code == 403

    # (c) User who DOES have proper access (Owner of Server A with plugin:manage) succeeds
    resp_owner_list = await client.get(f"/api/v1/servers/{server_a}/plugins", headers=owner_header)
    assert resp_owner_list.status_code == 200

    resp_owner_get = await client.get(
        f"/api/v1/servers/{server_a}/plugins/{plugin_a}", headers=owner_header
    )
    assert resp_owner_get.status_code == 200

    resp_owner_disable = await client.post(
        f"/api/v1/servers/{server_a}/plugins/{plugin_a}/disable",
        headers=owner_header,
    )
    assert resp_owner_disable.status_code == 200

    resp_owner_enable = await client.post(
        f"/api/v1/servers/{server_a}/plugins/{plugin_a}/enable",
        headers=owner_header,
    )
    assert resp_owner_enable.status_code == 200
