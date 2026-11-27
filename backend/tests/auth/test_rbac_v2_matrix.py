"""Comprehensive RBAC v2 integration tests: migration, escalation guards, 4-tier matrix & WS."""

from __future__ import annotations

import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command
from app.api import deps
from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.local_auth import resolve_local_auto_auth
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.core.query_bus import QueryBus
from app.main import create_app
from app.modules.auth.infrastructure.jwt import create_access_token
from app.modules.server.infrastructure.models import ServerModel
from app.registration import register_handlers
from app.websocket import endpoint as ws_endpoint

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _make_alembic_cfg(db_path: Path) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    return cfg


class _FakeCloudflaredSupervisor:
    def __init__(self) -> None:
        self.is_running = False
        self.quick_url: str | None = None
        self.status = "DISABLED"

    async def stop(self) -> None:
        self.is_running = False
        self.quick_url = None
        self.status = "STOPPED"

    async def start_quick(self, target: str, on_status=None, on_url=None) -> None:  # noqa: ARG002
        from app.modules.exposure.domain.value_objects import ExposureStatus

        self.is_running = True
        self.quick_url = "https://rbac-v2-test.trycloudflare.com"
        self.status = "ACTIVE"
        if on_url:
            await on_url(self.quick_url)
        if on_status:
            await on_status(ExposureStatus.ACTIVE)


async def _build_isolated_app(tmp_path: Path):
    db_file = tmp_path / "rbac_v2.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    database._engine = engine
    database._session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    event_bus = EventBus()
    command_bus = CommandBus()
    query_bus = QueryBus()
    register_handlers(command_bus, query_bus, event_bus)

    @asynccontextmanager
    async def _noop_lifespan(_app):
        yield

    app = create_app()
    app.router.lifespan_context = _noop_lifespan
    deps.init_buses(command_bus, query_bus, event_bus)
    ws_endpoint.init_websocket(event_bus)

    async def _get_cb() -> CommandBus:
        return command_bus

    async def _get_qb() -> QueryBus:
        return query_bus

    async def _get_eb() -> EventBus:
        return event_bus

    app.dependency_overrides[deps.get_command_bus] = _get_cb
    app.dependency_overrides[deps.get_query_bus] = _get_qb
    app.dependency_overrides[deps.get_event_bus] = _get_eb

    return app, engine


async def _seed_server(server_id: str, name: str, root_dir: Path, port: int) -> None:
    root_dir.mkdir(parents=True, exist_ok=True)
    assert database._session_factory is not None
    async with database._session_factory() as session:
        srv = ServerModel(
            id=server_id,
            name=name,
            server_type="paper",
            minecraft_version="1.21.1",
            port=port,
            root_path=str(root_dir),
            mode="simple",
            created_at=datetime.now(UTC).replace(tzinfo=None),
            updated_at=datetime.now(UTC).replace(tzinfo=None),
        )
        session.add(srv)
        await session.commit()


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestMigrationB1e2100000035:
    @pytest.mark.no_isolated_db
    def test_upgrade_downgrade_roundtrip_and_backfill(self, tmp_path: Path) -> None:
        db_path = tmp_path / "rbac_mig.db"
        cfg = _make_alembic_cfg(db_path)

        command.upgrade(cfg, "b1e2100000034")
        now = "2026-11-26T18:00:00"
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO roles (id, name, description, permissions) VALUES (?, ?, ?, ?)",
                (
                    "r-member",
                    "member",
                    "Legacy member",
                    json.dumps(["server:read", "server:create"]),
                ),
            )
            conn.execute(
                "INSERT INTO roles (id, name, description, permissions) VALUES (?, ?, ?, ?)",
                ("r-admin", "admin", "Admin", json.dumps(["admin:full"])),
            )
            conn.execute(
                "INSERT INTO users (id, username, email, password_hash, display_name, is_active, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                ("u-sa", "opuser", "op@example.com", "h1", "Op", now, now),
            )
            conn.execute(
                "INSERT INTO users (id, username, email, password_hash, display_name, is_active, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                ("u-view", "viewuser", "view@example.com", "h2", "Viewer", now, now),
            )
            conn.execute(
                "INSERT INTO user_roles (user_id, role_id) VALUES ('u-sa', 'r-member')"
            )
            conn.execute(
                "INSERT INTO user_roles (user_id, role_id) VALUES ('u-view', 'r-member')"
            )
            conn.execute(
                "INSERT INTO servers (id, name, server_type, minecraft_version, memory_min_mb, "
                "memory_max_mb, java_args, group_id, status, provisioning_retryable, port, motd, "
                "max_players, gamemode, difficulty, spawn_protection, pvp, enable_command_block, "
                "online_mode, whitelist_enabled, view_distance, simulation_distance, mode, "
                "provider, location_type, working_directory, startup_jar, startup_command, "
                "primary_world, uptime_seconds, restart_count, created_at, updated_at) "
                "VALUES ('srv-1', 'Alpha', 'paper', '1.21.1', 1024, 2048, '', 'default', "
                "'created', 0, 25565, 'hi', 20, 'survival', 'easy', 16, 1, 0, 1, 0, 10, 10, "
                "'simple', '', 'local', '.', 'server.jar', '', 'world', 0.0, 0, ?, ?)",
                (now, now),
            )
            conn.execute(
                "INSERT INTO server_memberships "
                "(id, server_id, user_id, role, created_at, updated_at) "
                "VALUES ('m-1', 'srv-1', 'u-sa', 'dev', ?, ?)",
                (now, now),
            )
            conn.execute(
                "INSERT INTO invitations (id, token_hash, token_prefix, creator_id, email, "
                "global_role, server_id, server_role, status, max_uses, use_count, created_at, "
                "updated_at) VALUES ('inv-1', 'thash', 'mcis_a', 'u-sa', NULL, 'member', "
                "'srv-1', 'viewer', 'ACTIVE', 1, 0, ?, ?)",
                (now, now),
            )
            conn.commit()

        command.upgrade(cfg, "b1e2100000035")
        with sqlite3.connect(db_path) as conn:
            user_cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
            inv_cols = {row[1] for row in conn.execute("PRAGMA table_info(invitations)").fetchall()}
            assert {"denied_permissions", "all_servers_access"}.issubset(user_cols)
            assert {
                "server_ids_json",
                "denied_permissions_json",
                "all_servers_access",
            }.issubset(inv_cols)

            roles = {
                str(r[0]): json.loads(r[1])
                for r in conn.execute("SELECT name, permissions FROM roles").fetchall()
            }
            assert "owner" in roles and "global:*" in roles["owner"]
            assert roles["admin"] == ["admin:full"]
            assert "server_admin" in roles
            assert "viewer" in roles

            sa_role = conn.execute(
                "SELECT r.name FROM roles r JOIN user_roles ur ON r.id = ur.role_id "
                "WHERE ur.user_id = 'u-sa'"
            ).fetchall()
            assert "server_admin" in {r[0] for r in sa_role}

            view_role = conn.execute(
                "SELECT r.name FROM roles r JOIN user_roles ur ON r.id = ur.role_id "
                "WHERE ur.user_id = 'u-view'"
            ).fetchall()
            assert "viewer" in {r[0] for r in view_role}

            inv_ids_raw = conn.execute(
                "SELECT server_ids_json FROM invitations WHERE id = 'inv-1'"
            ).fetchone()[0]
            assert json.loads(inv_ids_raw) == ["srv-1"]

        command.downgrade(cfg, "b1e2100000034")
        with sqlite3.connect(db_path) as conn:
            user_cols_down = {
                row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()
            }
            assert "denied_permissions" not in user_cols_down

        command.upgrade(cfg, "b1e2100000035")
        with sqlite3.connect(db_path) as conn:
            user_cols_up = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
            assert "all_servers_access" in user_cols_up


class TestPrivilegeEscalationAndLocalTunnelHardening:
    @pytest.mark.asyncio
    async def test_escalation_blocks_forged_jwt_and_atomic_tunnel_global(
        self, tmp_path: Path
    ) -> None:
        app, engine = await _build_isolated_app(tmp_path)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                boot = await client.post(
                    "/api/v1/setup/bootstrap",
                    json={
                        "username": "rootowner",
                        "password": "owner-password-123",
                        "display_name": "Root Owner",
                        "access_mode": "LOCAL",
                    },
                )
                assert boot.status_code == 201
                owner_id = boot.json()["user_id"]
                owner_token = boot.json()["access_token"]

                # Owner creates an Admin account via /users/manage
                mk_admin = await client.post(
                    "/api/v1/users/manage",
                    headers=_auth_header(owner_token),
                    json={
                        "username": "secadmin",
                        "password": "admin-password-123",
                        "display_name": "Sec Admin",
                        "role": "admin",
                    },
                )
                assert mk_admin.status_code == 201
                login_admin = await client.post(
                    "/api/v1/auth/login",
                    json={"username": "secadmin", "password": "admin-password-123"},
                )
                admin_token = login_admin.json()["access_token"]

                # Owner creates a Viewer account to test forged JWT claim immunity
                mk_viewer = await client.post(
                    "/api/v1/users/manage",
                    headers=_auth_header(owner_token),
                    json={
                        "username": "viewer1",
                        "password": "viewer-password-123",
                        "role": "viewer",
                    },
                )
                assert mk_viewer.status_code == 201
                viewer_id = mk_viewer.json()["user_id"]

                # 1. Admin cannot mint Owner-level API keys
                for req_perms in (["global:*"], ["global.*"], ["panel.exposure.manage"]):
                    res = await client.post(
                        "/api/v1/auth/api-keys",
                        headers=_auth_header(admin_token),
                        json={"name": "escalated", "permissions": req_perms},
                    )
                    assert res.status_code == 403

                # 2. Admin cannot modify, deactivate, re-scope, or delete Owner
                assert (
                    await client.patch(
                        f"/api/v1/users/{owner_id}",
                        headers=_auth_header(admin_token),
                        json={"is_active": False},
                    )
                ).status_code == 403
                assert (
                    await client.put(
                        f"/api/v1/users/{owner_id}/access",
                        headers=_auth_header(admin_token),
                        json={"role": "viewer", "server_ids": [], "all_servers_access": False},
                    )
                ).status_code == 403
                assert (
                    await client.delete(
                        f"/api/v1/users/{owner_id}",
                        headers=_auth_header(admin_token),
                    )
                ).status_code == 403

                # 3. Admin cannot touch Owner-only exposure / access mode / setup credentials
                assert (
                    await client.get("/api/v1/exposure/panel", headers=_auth_header(admin_token))
                ).status_code == 403
                assert (
                    await client.put(
                        "/api/v1/exposure/panel",
                        headers=_auth_header(admin_token),
                        json={"method": "none", "desired_state": "DISABLED"},
                    )
                ).status_code == 403
                assert (
                    await client.put(
                        "/api/v1/setup/access-mode",
                        headers=_auth_header(admin_token),
                        json={"access_mode": "GLOBAL"},
                    )
                ).status_code == 403
                assert (
                    await client.post(
                        "/api/v1/setup/credentials",
                        headers=_auth_header(admin_token),
                        json={"username": "hijack", "password": "hijack-password-123"},
                    )
                ).status_code == 403
                assert (
                    await client.post(
                        "/api/v1/exposure/agent/claim",
                        headers=_auth_header(admin_token),
                    )
                ).status_code == 403

                # 4. Forged JWT claims on Viewer account are ignored because DB state wins
                forged_jwt = create_access_token(
                    user_id=viewer_id,
                    roles=["owner", "admin"],
                    permissions=["admin:full", "global:*", "user:write"],
                )
                assert (
                    await client.get("/api/v1/users", headers=_auth_header(forged_jwt))
                ).status_code == 403
                assert (
                    await client.get("/api/v1/exposure/panel", headers=_auth_header(forged_jwt))
                ).status_code == 403
                assert (
                    await client.post(
                        "/api/v1/servers",
                        headers=_auth_header(forged_jwt),
                        json={
                            "name": "forged",
                            "server_type": "vanilla",
                            "minecraft_version": "1.21.1",
                        },
                    )
                ).status_code == 403

                # 5. Enabling Cloudflare Quick Tunnel atomically transitions LOCAL -> GLOBAL
                fake_sup = _FakeCloudflaredSupervisor()
                with patch(
                    "app.modules.exposure.application.commands.get_cloudflared_supervisor",
                    return_value=fake_sup,
                ):
                    exp_res = await client.put(
                        "/api/v1/exposure/panel",
                        headers=_auth_header(owner_token),
                        json={
                            "method": "cloudflare_tunnel",
                            "cloudflare_mode": "quick",
                            "desired_state": "ENABLED",
                        },
                    )
                assert exp_res.status_code == 200

                status_res = await client.get("/api/v1/setup/status")
                assert status_res.status_code == 200
                assert status_res.json()["access_mode"] == "GLOBAL"

                # Public registration now rejected even without reboot
                pub_reg = await client.post(
                    "/api/v1/users",
                    json={"username": "stranger", "password": "stranger-password-123"},
                )
                assert pub_reg.status_code == 403

                # resolve_local_auto_auth strictly returns None when exposure enabled / GLOBAL
                assert database._session_factory is not None
                async with database._session_factory() as session:
                    assert (
                        await resolve_local_auto_auth(
                            "127.0.0.1", {"host": "127.0.0.1:8000"}, session
                        )
                        is None
                    )
        finally:
            await engine.dispose()
            database._engine = None


class TestFourTierRbacMatrixAndLiveRevocation:
    @pytest.mark.asyncio
    async def test_four_tier_isolation_invites_and_live_updates(self, tmp_path: Path) -> None:
        app, engine = await _build_isolated_app(tmp_path)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                boot = await client.post(
                    "/api/v1/setup/bootstrap",
                    json={
                        "username": "owner",
                        "password": "owner-password-123",
                        "access_mode": "GLOBAL",
                    },
                )
                owner_token = boot.json()["access_token"]

                await _seed_server("srv-a", "Survival A", tmp_path / "srv_a", 25565)
                await _seed_server("srv-b", "Creative B", tmp_path / "srv_b", 25566)

                # 1. Invite defaults to viewer when omitted
                default_inv = await client.post(
                    "/api/v1/invites",
                    headers=_auth_header(owner_token),
                    json={},
                )
                assert default_inv.status_code == 201
                assert default_inv.json()["global_role"] == "viewer"
                assert default_inv.json()["role"] == "viewer"

                # 2. Multi-server Server Admin invite (only srv-a, power denied)
                sa_inv = await client.post(
                    "/api/v1/invites",
                    headers=_auth_header(owner_token),
                    json={
                        "role": "server_admin",
                        "server_ids": ["srv-a"],
                        "denied_permissions": ["power"],
                    },
                )
                assert sa_inv.status_code == 201
                sa_accept = await client.post(
                    "/api/v1/invites/accept",
                    json={
                        "token": sa_inv.json()["token"],
                        "username": "op_a",
                        "password": "operator-password-123",
                    },
                )
                assert sa_accept.status_code == 201
                sa_token = sa_accept.json()["access_token"]
                sa_user_id = sa_accept.json()["user_id"]

                sa_me = await client.get("/api/v1/auth/me", headers=_auth_header(sa_token))
                assert sa_me.status_code == 200
                assert sa_me.json()["global_role"] == "server_admin"
                assert sa_me.json()["assigned_server_ids"] == ["srv-a"]
                assert sa_me.json()["denied_permissions"] == ["power"]

                # Scoped fleet visibility
                sa_list = await client.get("/api/v1/servers", headers=_auth_header(sa_token))
                assert sa_list.status_code == 200
                assert [s["server_id"] for s in sa_list.json()] == ["srv-a"]

                assert (
                    await client.get("/api/v1/servers/srv-a", headers=_auth_header(sa_token))
                ).status_code == 200
                assert (
                    await client.get("/api/v1/servers/srv-b", headers=_auth_header(sa_token))
                ).status_code == 403
                # Power denied on srv-a
                assert (
                    await client.post(
                        "/api/v1/servers/srv-a/start", headers=_auth_header(sa_token)
                    )
                ).status_code == 403
                # Files allowed on srv-a
                assert (
                    await client.get(
                        "/api/v1/servers/srv-a/files", headers=_auth_header(sa_token)
                    )
                ).status_code == 200
                # Cannot create/delete servers, read global settings, or manage users/invites
                assert (
                    await client.post(
                        "/api/v1/servers",
                        headers=_auth_header(sa_token),
                        json={"name": "s", "server_type": "vanilla", "minecraft_version": "1.21.1"},
                    )
                ).status_code == 403
                assert (
                    await client.delete("/api/v1/servers/srv-a", headers=_auth_header(sa_token))
                ).status_code == 403
                assert (
                    await client.get("/api/v1/settings", headers=_auth_header(sa_token))
                ).status_code == 403
                assert (
                    await client.get("/api/v1/users", headers=_auth_header(sa_token))
                ).status_code == 403
                assert (
                    await client.get("/api/v1/invites", headers=_auth_header(sa_token))
                ).status_code == 403

                # 3. Multi-server Viewer created via /users/manage
                mk_viewer = await client.post(
                    "/api/v1/users/manage",
                    headers=_auth_header(owner_token),
                    json={
                        "username": "viewer_a",
                        "password": "viewer-password-123",
                        "role": "viewer",
                        "server_ids": ["srv-a"],
                        "denied_permissions": [],
                    },
                )
                assert mk_viewer.status_code == 201
                viewer_id = mk_viewer.json()["user_id"]
                view_login = await client.post(
                    "/api/v1/auth/login",
                    json={"username": "viewer_a", "password": "viewer-password-123"},
                )
                view_token = view_login.json()["access_token"]

                view_list = await client.get("/api/v1/servers", headers=_auth_header(view_token))
                assert [s["server_id"] for s in view_list.json()] == ["srv-a"]

                # Viewer: general files blocked (403), logs allowed (200), read endpoints allowed
                assert (
                    await client.get(
                        "/api/v1/servers/srv-a/files", headers=_auth_header(view_token)
                    )
                ).status_code == 403
                assert (
                    await client.get(
                        "/api/v1/servers/srv-a/files?scope=logs", headers=_auth_header(view_token)
                    )
                ).status_code == 200
                assert (
                    await client.get(
                        "/api/v1/servers/srv-a/exposure", headers=_auth_header(view_token)
                    )
                ).status_code == 200
                assert (
                    await client.get(
                        "/api/v1/backups?server_id=srv-a", headers=_auth_header(view_token)
                    )
                ).status_code == 200

                # Viewer blocked on all mutations
                assert (
                    await client.post(
                        "/api/v1/servers/srv-a/start", headers=_auth_header(view_token)
                    )
                ).status_code == 403
                assert (
                    await client.put(
                        "/api/v1/servers/srv-a/files/content?path=eula.txt",
                        headers=_auth_header(view_token),
                        json={"content": "eula=true"},
                    )
                ).status_code == 403
                assert (
                    await client.post(
                        "/api/v1/backups",
                        headers=_auth_header(view_token),
                        json={"server_id": "srv-a", "tier": "tier_1", "scope": "full"},
                    )
                ).status_code == 403
                assert (
                    await client.put(
                        "/api/v1/servers/srv-a/exposure",
                        headers=_auth_header(view_token),
                        json={"method": "none", "desired_state": "DISABLED"},
                    )
                ).status_code == 403

                # 4. Live permission mutation via PUT /users/{id}/access takes effect immediately
                upd_view = await client.put(
                    f"/api/v1/users/{viewer_id}/access",
                    headers=_auth_header(owner_token),
                    json={
                        "role": "viewer",
                        "all_servers_access": True,
                        "server_ids": [],
                        "denied_permissions": ["files", "backups"],
                        "is_active": True,
                    },
                )
                assert upd_view.status_code == 200
                # Same token now sees srv-a AND srv-b, but logs & backups are immediately 403
                after_list = await client.get("/api/v1/servers", headers=_auth_header(view_token))
                assert {s["server_id"] for s in after_list.json()} == {"srv-a", "srv-b"}
                assert (
                    await client.get(
                        "/api/v1/servers/srv-a/files?scope=logs", headers=_auth_header(view_token)
                    )
                ).status_code == 403
                assert (
                    await client.get(
                        "/api/v1/backups?server_id=srv-a", headers=_auth_header(view_token)
                    )
                ).status_code == 403

                # 5. Live user deactivation immediately invalidates active JWT
                deact = await client.put(
                    f"/api/v1/users/{sa_user_id}/access",
                    headers=_auth_header(owner_token),
                    json={
                        "role": "server_admin",
                        "server_ids": ["srv-a"],
                        "all_servers_access": False,
                        "denied_permissions": [],
                        "is_active": False,
                    },
                )
                assert deact.status_code == 200
                assert (
                    await client.get("/api/v1/servers", headers=_auth_header(sa_token))
                ).status_code == 401
        finally:
            await engine.dispose()
            database._engine = None


class TestWebSocketRbacV2Enforcement:
    @pytest.mark.no_isolated_db
    def test_ws_wildcard_scope_and_exec_input_enforcement(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rbac_ws.db"
        event_bus = EventBus()
        command_bus = CommandBus()
        query_bus = QueryBus()
        register_handlers(command_bus, query_bus, event_bus)

        @asynccontextmanager
        async def _noop_lifespan(_app):
            yield

        app = create_app()
        app.router.lifespan_context = _noop_lifespan
        deps.init_buses(command_bus, query_bus, event_bus)
        ws_endpoint.init_websocket(event_bus)

        async def _get_cb() -> CommandBus:
            return command_bus

        async def _get_qb() -> QueryBus:
            return query_bus

        async def _get_eb() -> EventBus:
            return event_bus

        app.dependency_overrides[deps.get_command_bus] = _get_cb
        app.dependency_overrides[deps.get_query_bus] = _get_qb
        app.dependency_overrides[deps.get_event_bus] = _get_eb

        async def _bind() -> object:
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", echo=False)
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            database._engine = engine
            database._session_factory = async_sessionmaker(
                bind=engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            await _seed_server("srv-a", "WS Alpha", tmp_path / "ws_a", 25575)
            await _seed_server("srv-b", "WS Beta", tmp_path / "ws_b", 25576)
            return engine

        async def _unbind(engine: object) -> None:
            database._engine = None
            database._session_factory = None
            await engine.dispose()  # type: ignore[attr-defined]

        async def _get_user_id(username: str) -> str:
            from app.modules.auth.infrastructure.models import UserModel

            assert database._session_factory is not None
            async with database._session_factory() as session:
                row = (
                    await session.execute(select(UserModel).where(UserModel.username == username))
                ).scalar_one()
                return str(row.id)

        with TestClient(app) as ws_client:
            engine = ws_client.portal.call(_bind)
            try:
                boot = ws_client.post(
                    "/api/v1/setup/bootstrap",
                    json={
                        "username": "wsowner",
                        "password": "owner-password-123",
                        "access_mode": "GLOBAL",
                    },
                )
                assert boot.status_code == 201
                owner_token = boot.json()["access_token"]

                mk = ws_client.post(
                    "/api/v1/users/manage",
                    headers=_auth_header(owner_token),
                    json={
                        "username": "wsviewer",
                        "password": "viewer-password-123",
                        "role": "viewer",
                        "server_ids": ["srv-a"],
                        "denied_permissions": [],
                    },
                )
                assert mk.status_code == 201
                v_login = ws_client.post(
                    "/api/v1/auth/login",
                    json={"username": "wsviewer", "password": "viewer-password-123"},
                )
                assert v_login.status_code == 200
                viewer_token = v_login.json()["access_token"]
                viewer_id = ws_client.portal.call(_get_user_id, "wsviewer")

                with ws_client.websocket_connect(f"/ws?token={viewer_token}") as ws:
                    # 1. Wildcard channels blocked for Viewer
                    ws.send_text('{"type": "subscribe", "channels": ["server:*"]}')
                    msg_wild = ws.receive_bytes()
                    assert b"PERMISSION_DENIED" in msg_wild

                    # 2. Unassigned server blocked for Viewer
                    ws.send_text('{"type": "subscribe", "channels": ["server:srv-b"]}')
                    msg_unassigned = ws.receive_bytes()
                    assert b"PERMISSION_DENIED" in msg_unassigned

                    # 3. Assigned server read & console channels allowed for Viewer
                    ws.send_text(
                        json.dumps(
                            {
                                "type": "subscribe",
                                "channels": ["server:srv-a", "server:srv-a:console"],
                            }
                        )
                    )
                    ws.send_text('{"type": "ping"}')
                    pong_msg = ws.receive_bytes()
                    assert b"pong" in pong_msg
                    subs = ws_client.portal.call(
                        ws_endpoint._registry.get_by_channel, "server:srv-a"
                    )
                    console_subs = ws_client.portal.call(
                        ws_endpoint._registry.get_by_channel, "server:srv-a:console"
                    )
                    assert len(subs) == 1
                    assert len(console_subs) == 1

                    # 4. exec_input write action blocked for Viewer
                    ws.send_text(
                        json.dumps(
                            {
                                "type": "exec_input",
                                "target_type": "server",
                                "target_id": "srv-a",
                                "input": "say hi",
                            }
                        )
                    )
                    msg_exec = ws.receive_bytes()
                    assert b"PERMISSION_DENIED" in msg_exec

                    # 5. Live console denial revalidates & prunes console channel cleanly
                    revoke_console = ws_client.put(
                        f"/api/v1/users/{viewer_id}/access",
                        headers=_auth_header(owner_token),
                        json={
                            "role": "viewer",
                            "server_ids": ["srv-a"],
                            "all_servers_access": False,
                            "denied_permissions": ["console"],
                            "is_active": True,
                        },
                    )
                    assert revoke_console.status_code == 200
                    console_after = ws_client.portal.call(
                        ws_endpoint._registry.get_by_channel, "server:srv-a:console"
                    )
                    assert len(console_after) == 0

                    # 6. Live deactivation disconnects active WS sessions
                    ws_client.portal.call(ws_endpoint.disconnect_user_sessions, viewer_id)
                    active_after = ws_client.portal.call(
                        ws_endpoint._registry.get_by_channel, "server:srv-a"
                    )
                    assert len(active_after) == 0
            finally:
                ws_client.portal.call(_unbind, engine)


__all__ = [
    "TestFourTierRbacMatrixAndLiveRevocation",
    "TestMigrationB1e2100000035",
    "TestPrivilegeEscalationAndLocalTunnelHardening",
    "TestWebSocketRbacV2Enforcement",
]
