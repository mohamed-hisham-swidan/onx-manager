from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.core.persistence.db import database
from app.modules.auth.infrastructure.models import UserModel
from app.modules.server.infrastructure.models import ServerMembershipModel, ServerModel
from tests.api.test_api_endpoints import _seed_api_key_header

pytest_plugins = ["tests.api.test_api_endpoints"]


async def _seed_server(server_id: str, name: str, owner_id: str | None = None) -> None:
    async with database._session_factory() as session:
        server = ServerModel(
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
            root_path=None,
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
async def test_runtime_diagnostics_require_server_scope(
    client: AsyncClient, created_user: dict
) -> None:
    server_id = "srv-runtime-scope"
    owner_user_id = "u_rt_owner"
    viewer_user_id = "u_rt_viewer"

    await _seed_user(owner_user_id, "rt-owner@example.com", "Owner")
    await _seed_user(viewer_user_id, "rt-viewer@example.com", "Viewer")
    await _seed_server(server_id, "Runtime Scope Server", owner_id=owner_user_id)
    await _seed_membership("mem_rt_viewer", server_id, viewer_user_id, "viewer")

    with patch(
        "app.modules.server.application.runtime_ownership._find_all_tmux_sessions",
        return_value=[],
    ):
        # 1. Non-owner, non-member user -> 403 on both server-scoped runtime endpoints
        non_member_header = await _seed_api_key_header(client, created_user["user_id"], [])
        resp = await client.get(f"/api/v1/servers/{server_id}/runtime", headers=non_member_header)
        assert resp.status_code == 403
        resp = await client.get(
            f"/api/v1/servers/{server_id}/runtime/validate", headers=non_member_header
        )
        assert resp.status_code == 403

        # 2. Viewer membership -> 200 (server.{id}.view)
        viewer_header = await _seed_api_key_header(client, viewer_user_id, [])
        resp = await client.get(f"/api/v1/servers/{server_id}/runtime", headers=viewer_header)
        assert resp.status_code == 200
        resp = await client.get(
            f"/api/v1/servers/{server_id}/runtime/validate", headers=viewer_header
        )
        assert resp.status_code == 200

        # 3. Owner -> 200 (implicit owner_id access)
        owner_header = await _seed_api_key_header(client, owner_user_id, [])
        resp = await client.get(f"/api/v1/servers/{server_id}/runtime", headers=owner_header)
        assert resp.status_code == 200
        resp = await client.get(
            f"/api/v1/servers/{server_id}/runtime/validate", headers=owner_header
        )
        assert resp.status_code == 200

        # 4. Global admin -> 200 (admin:full short-circuit)
        admin_header = await _seed_api_key_header(client, created_user["user_id"], ["admin:full"])
        resp = await client.get(f"/api/v1/servers/{server_id}/runtime", headers=admin_header)
        assert resp.status_code == 200

        # 5. Missing server with valid auth -> 404 (not a permission leak)
        resp = await client.get("/api/v1/servers/does-not-exist/runtime", headers=admin_header)
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_runtime_ownership_requires_server_read(
    client: AsyncClient, created_user: dict
) -> None:
    with (
        patch(
            "app.modules.server.application.runtime_ownership._find_all_tmux_sessions",
            return_value=[],
        ),
        patch(
            "app.modules.server.application.runtime_ownership._find_all_java_pids",
            return_value=[],
        ),
    ):
        # 1. Authenticated user without server:read -> 403
        no_read_header = await _seed_api_key_header(client, created_user["user_id"], [])
        resp = await client.get("/api/v1/servers/runtime/ownership", headers=no_read_header)
        assert resp.status_code == 403

        # 2. Authenticated user with server:read -> 200
        read_header = await _seed_api_key_header(client, created_user["user_id"], ["server:read"])
        resp = await client.get("/api/v1/servers/runtime/ownership", headers=read_header)
        assert resp.status_code == 200

        # 3. Global admin -> 200
        admin_header = await _seed_api_key_header(client, created_user["user_id"], ["admin:full"])
        resp = await client.get("/api/v1/servers/runtime/ownership", headers=admin_header)
        assert resp.status_code == 200
