"""Phase 2 tests: username-only auth, secure local zero-login, and fail-closed exposure gate."""

from __future__ import annotations

import json
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from alembic import command
from app.core import config as config_mod
from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.local_auth import (
    LOCAL_ADMIN_USER_ID,
    LOCAL_ADMIN_USERNAME,
    ensure_local_admin_provisioned,
)
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.core.query_bus import QueryBus
from app.core.settings_store import get_live_settings, init_settings_store
from app.main import create_app
from app.registration import register_handlers
from app.websocket import endpoint as ws_endpoint

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _make_alembic_cfg(db_path: Path) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    return cfg


class TestMigrationB1e2100000033:
    def test_migration_roundtrip_and_backfill(self, tmp_path: Path) -> None:
        db_path = tmp_path / "phase2_mig.db"
        cfg = _make_alembic_cfg(db_path)

        command.upgrade(cfg, "b1e2100000032")
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO users "
                "(id, email, password_hash, display_name, is_active, created_at, updated_at) "
                "VALUES ('u-1', 'owner@example.com', 'hash1', 'Owner', 1, "
                "'2026-11-22T00:00:00', '2026-11-22T00:00:00')"
            )
            conn.execute(
                "INSERT INTO users "
                "(id, email, password_hash, display_name, is_active, created_at, updated_at) "
                "VALUES ('u-2', 'other@example.com', 'hash2', 'Other', 1, "
                "'2026-11-22T00:00:00', '2026-11-22T00:00:00')"
            )
            conn.execute(
                "INSERT INTO system_state (id, initialized, access_mode, created_at, updated_at) "
                "VALUES ('default', 0, 'LOCAL', '2026-11-22T00:00:00', '2026-11-22T00:00:00')"
            )
            conn.commit()

        command.upgrade(cfg, "b1e2100000033")
        with sqlite3.connect(db_path) as conn:
            cols = {row[1]: row for row in conn.execute("PRAGMA table_info(users)").fetchall()}
            assert "username" in cols
            assert cols["username"][3] == 1  # notnull == 1
            assert cols["email"][3] == 0  # nullable == 1

            indexes = {row[1] for row in conn.execute("PRAGMA index_list(users)").fetchall()}
            assert "ix_users_username" in indexes

            rows = dict(conn.execute("SELECT id, username FROM users").fetchall())
            assert rows["u-1"] == "owner@example.com"
            assert rows["u-2"] == "other@example.com"

            sys_cols = {
                row[1]: row for row in conn.execute("PRAGMA table_info(system_state)").fetchall()
            }
            assert "password_configured" in sys_cols
            pw_cfg = conn.execute(
                "SELECT password_configured FROM system_state WHERE id='default'"
            ).fetchone()
            assert pw_cfg == (0,)

            conn.execute(
                "INSERT INTO users (id, username, email, password_hash, display_name, "
                "is_active, created_at, updated_at) "
                "VALUES ('u-3', 'alice', NULL, 'hash3', 'alice', 1, "
                "'2026-11-22T00:00:00', '2026-11-22T00:00:00')"
            )
            conn.commit()

        command.downgrade(cfg, "b1e2100000032")
        with sqlite3.connect(db_path) as conn:
            cols_down = {row[1]: row for row in conn.execute("PRAGMA table_info(users)").fetchall()}
            assert "username" not in cols_down
            assert cols_down["email"][3] == 1
            u3_email = conn.execute("SELECT email FROM users WHERE id='u-3'").fetchone()
            assert u3_email == ("alice@local.invalid",)

        command.upgrade(cfg, "b1e2100000033")


@pytest.fixture
async def isolated_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings_yaml = tmp_path / "settings.yaml"
    monkeypatch.setattr("app.core.settings_store._SETTINGS_FILE", settings_yaml)
    init_settings_store(settings_yaml)

    monkeypatch.setenv("ONX_SERVERS_DATA_DIR", str(tmp_path / "servers"))
    monkeypatch.delenv("ONX_PANEL_BIND_HOST", raising=False)
    monkeypatch.delenv("MCS_PANEL_BIND_HOST", raising=False)
    monkeypatch.setattr(config_mod, "_ACTIVE_PANEL_BIND_HOST", None)
    monkeypatch.setattr(config_mod, "_ACTIVE_PANEL_BIND_PORT", None)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    database._engine = engine
    database._session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )

    event_bus = EventBus()
    command_bus = CommandBus()
    query_bus = QueryBus()
    register_handlers(command_bus, query_bus, event_bus)

    app = create_app(static_dir="off")
    from app.api import deps

    async def get_cb() -> CommandBus:
        return command_bus

    async def get_qb() -> QueryBus:
        return query_bus

    async def get_eb() -> EventBus:
        return event_bus

    app.dependency_overrides[deps.get_command_bus] = get_cb
    app.dependency_overrides[deps.get_query_bus] = get_qb
    app.dependency_overrides[deps.get_event_bus] = get_eb

    try:
        yield app
    finally:
        await engine.dispose()
        database._engine = None
        database._session_factory = None


@pytest.mark.asyncio
class TestUsernameOnlyAuthAndVpsMode:
    async def test_vps_mode_bootstrap_login_users_and_invites_without_email(
        self, isolated_app, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ONX_DEPLOYMENT_PROFILE", "vps")

        async with AsyncClient(
            transport=ASGITransport(app=isolated_app, client=("127.0.0.1", 50000)),
            base_url="http://127.0.0.1:8000",
        ) as client:
            status_res = await client.get("/api/v1/setup/status")
            assert status_res.status_code == 200
            status_data = status_res.json()
            assert status_data["initialized"] is False
            assert status_data["password_configured"] is False
            assert status_data["auth_mode"] == "jwt"
            assert status_data["deployment_profile"] == "vps"

            # Loopback unauthenticated request in VPS mode must fail closed with 401
            unauth_res = await client.get("/api/v1/servers")
            assert unauth_res.status_code == 401

            # Bootstrap with username + password only (no email!)
            boot_res = await client.post(
                "/api/v1/setup/bootstrap",
                json={
                    "username": "vpsowner",
                    "password": "OwnerPassword123!",
                    "access_mode": "GLOBAL",
                },
            )
            assert boot_res.status_code == 201
            owner_token = boot_res.json()["access_token"]
            owner_headers = {"Authorization": f"Bearer {owner_token}"}

            status_after = await client.get("/api/v1/setup/status")
            assert status_after.json()["initialized"] is True
            assert status_after.json()["password_configured"] is True
            assert status_after.json()["auth_mode"] == "jwt"

            me_res = await client.get("/api/v1/auth/me", headers=owner_headers)
            assert me_res.status_code == 200
            assert me_res.json()["username"] == "vpsowner"
            assert me_res.json()["email"] is None

            # Login with username + password only
            login_res = await client.post(
                "/api/v1/auth/login",
                json={"username": "vpsowner", "password": "OwnerPassword123!"},
            )
            assert login_res.status_code == 200
            assert login_res.json()["access_token"]

            # Create & accept invite without email
            inv_res = await client.post(
                "/api/v1/invites",
                json={"global_role": "member"},
                headers=owner_headers,
            )
            assert inv_res.status_code == 201
            inv_token = inv_res.json()["token"]

            accept_res = await client.post(
                "/api/v1/invites/accept",
                json={
                    "token": inv_token,
                    "username": "invitedplayer",
                    "password": "InvitedPassword123!",
                },
            )
            assert accept_res.status_code == 201
            member_headers = {"Authorization": f"Bearer {accept_res.json()['access_token']}"}

            member_me = await client.get("/api/v1/auth/me", headers=member_headers)
            assert member_me.status_code == 200
            assert member_me.json()["username"] == "invitedplayer"
            assert member_me.json()["email"] is None

            # Switch to LOCAL mode and create user with username + password only
            mode_res = await client.put(
                "/api/v1/setup/access-mode",
                json={"access_mode": "LOCAL"},
                headers=owner_headers,
            )
            assert mode_res.status_code == 200

            user_res = await client.post(
                "/api/v1/users",
                json={"username": "localfriend", "password": "FriendPassword123!"},
            )
            assert user_res.status_code == 201
            assert user_res.json()["username"] == "localfriend"
            assert user_res.json()["email"] is None


@pytest.mark.asyncio
class TestLocalZeroLoginAndSecurityGate:
    async def test_local_zero_login_loopback_vs_non_loopback_and_spoofed_headers(
        self, isolated_app, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ONX_DEPLOYMENT_PROFILE", "local")

        # Simulate startup provisioning
        async with database._session_factory() as session:
            provisioned = await ensure_local_admin_provisioned(session)
            assert provisioned is True
            await session.commit()

        async with AsyncClient(
            transport=ASGITransport(app=isolated_app, client=("127.0.0.1", 50001)),
            base_url="http://127.0.0.1:8000",
        ) as loopback_client:
            status_res = await loopback_client.get("/api/v1/setup/status")
            assert status_res.status_code == 200
            status_data = status_res.json()
            assert status_data["initialized"] is True
            assert status_data["password_configured"] is False
            assert status_data["auth_mode"] == "local_zero_login"
            assert status_data["deployment_profile"] == "local"

            # Direct loopback access works without Authorization header
            me_res = await loopback_client.get("/api/v1/auth/me")
            assert me_res.status_code == 200
            assert me_res.json()["user_id"] == LOCAL_ADMIN_USER_ID
            assert me_res.json()["username"] == LOCAL_ADMIN_USERNAME

            servers_res = await loopback_client.get("/api/v1/servers")
            assert servers_res.status_code == 200

            # Spoofed forwarding or non-loopback Host headers from loopback MUST fail closed (401)
            for spoofed_headers in (
                {"X-Forwarded-For": "203.0.113.10"},
                {"X-Forwarded-For": "127.0.0.1"},
                {"Forwarded": "for=127.0.0.1"},
                {"Forwarded": "for=203.0.113.5"},
                {"X-Real-IP": "127.0.0.1"},
                {"Host": "evil.attacker.com:8000"},
                {"Host": "evil.attacker.com"},
            ):
                spoof_res = await loopback_client.get("/api/v1/servers", headers=spoofed_headers)
                assert spoof_res.status_code == 401

            # Invalid Bearer token must NOT fall back to local zero-login
            bad_token_res = await loopback_client.get(
                "/api/v1/servers", headers={"Authorization": "Bearer invalid.jwt.token"}
            )
            assert bad_token_res.status_code == 401

        # IPv6 loopback ::1 succeeds
        async with AsyncClient(
            transport=ASGITransport(app=isolated_app, client=("::1", 50002)),
            base_url="http://[::1]:8000",
        ) as ipv6_client:
            ipv6_res = await ipv6_client.get("/api/v1/servers")
            assert ipv6_res.status_code == 200

        # Non-loopback client IP MUST fail closed (401)
        async with AsyncClient(
            transport=ASGITransport(app=isolated_app, client=("192.168.1.50", 50003)),
            base_url="http://192.168.1.50:8000",
        ) as lan_client:
            lan_res = await lan_client.get("/api/v1/servers")
            assert lan_res.status_code == 401

        # Non-loopback bind host (0.0.0.0) disables zero-login even from 127.0.0.1
        monkeypatch.setenv("ONX_PANEL_BIND_HOST", "0.0.0.0")
        async with AsyncClient(
            transport=ASGITransport(app=isolated_app, client=("127.0.0.1", 50004)),
            base_url="http://127.0.0.1:8000",
        ) as bound_all_client:
            status_0000 = await bound_all_client.get("/api/v1/setup/status")
            assert status_0000.json()["auth_mode"] == "jwt"
            blocked_res = await bound_all_client.get("/api/v1/servers")
            assert blocked_res.status_code == 401

    async def test_passwordless_local_blocks_exposure_and_bind_until_configured(
        self, isolated_app, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ONX_DEPLOYMENT_PROFILE", "local")

        async with AsyncClient(
            transport=ASGITransport(app=isolated_app, client=("127.0.0.1", 50005)),
            base_url="http://127.0.0.1:8000",
        ) as client:
            # Create a server first in local zero-login mode
            with patch(
                "app.modules.server.application.services.jar_service.download_server_jar",
                AsyncMock(return_value="/tmp/mock-jar/server.jar"),
            ):
                srv_res = await client.post(
                    "/api/v1/servers",
                    json={
                        "name": "Local Server",
                        "minecraft_version": "1.21",
                        "min_memory_mb": 1024,
                        "max_memory_mb": 2048,
                        "port": 25565,
                        "gamemode": "survival",
                        "difficulty": "easy",
                    },
                )
            assert srv_res.status_code == 201
            server_id = srv_res.json()["server_id"]

            # 1. All external exposure & non-loopback settings MUST be blocked
            for method, url, payload in (
                (
                    "PUT",
                    "/api/v1/exposure/panel",
                    {
                        "method": "cloudflare_tunnel",
                        "desired_state": "ENABLED",
                        "cloudflare_token": "tok",
                        "hostname": "panel.example.com",
                    },
                ),
                (
                    "PUT",
                    "/api/v1/exposure/panel",
                    {"method": "playit_http", "desired_state": "ENABLED"},
                ),
                (
                    "PUT",
                    "/api/v1/exposure/panel",
                    {"method": "port_forward", "desired_state": "ENABLED"},
                ),
                (
                    "PUT",
                    f"/api/v1/servers/{server_id}/exposure",
                    {"method": "playit", "desired_state": "ENABLED"},
                ),
                (
                    "PUT",
                    f"/api/v1/servers/{server_id}/exposure",
                    {"method": "port_forward", "desired_state": "ENABLED"},
                ),
                (
                    "PUT",
                    f"/api/v1/servers/{server_id}/exposure",
                    {
                        "method": "cloudflare_tcp",
                        "desired_state": "ENABLED",
                        "cloudflare_token": "tok",
                        "hostname": "mc.example.com",
                        "acknowledged_warning": True,
                    },
                ),
                (
                    "PATCH",
                    f"/api/v1/servers/{server_id}/exposure",
                    {"desired_state": "ENABLED"},
                ),
                ("POST", "/api/v1/exposure/agent/claim", None),
                ("PATCH", "/api/v1/settings", {"panel_bind_host": "0.0.0.0"}),
                ("PUT", "/api/v1/setup/access-mode", {"access_mode": "GLOBAL"}),
            ):
                resp = await client.request(method, url, json=payload)
                assert resp.status_code == 403, (
                    f"Expected 403 for {method} {url}, got {resp.status_code}"
                )
                body = resp.json()
                assert body["error_code"] == "PASSWORD_REQUIRED_FOR_EXPOSURE"
                assert body["code"] == "PASSWORD_REQUIRED_FOR_EXPOSURE"

            # Verify port_forward block did NOT mutate panel_bind_host
            assert get_live_settings().panel_bind_host == "127.0.0.1"

            # 2. Configure Username + Password via /api/v1/setup/credentials
            cred_res = await client.post(
                "/api/v1/setup/credentials",
                json={"username": "localowner", "password": "SecureLocalPassword123!"},
            )
            assert cred_res.status_code == 200
            cred_data = cred_res.json()
            assert cred_data["access_token"]
            jwt_headers = {"Authorization": f"Bearer {cred_data['access_token']}"}

            # Status now reports password_configured=True, auth_mode="jwt"
            status_after = await client.get("/api/v1/setup/status")
            assert status_after.json()["password_configured"] is True
            assert status_after.json()["auth_mode"] == "jwt"

            # Passwordless auto-login is now permanently disabled even from 127.0.0.1
            unauth_after = await client.get("/api/v1/servers")
            assert unauth_after.status_code == 401

            # Standard JWT login works with configured username
            login_res = await client.post(
                "/api/v1/auth/login",
                json={"username": "localowner", "password": "SecureLocalPassword123!"},
            )
            assert login_res.status_code == 200

            # Second /setup/credentials attempt fails with 409 Conflict
            second_cred = await client.post(
                "/api/v1/setup/credentials",
                json={"username": "attacker", "password": "AnotherPassword123!"},
                headers=jwt_headers,
            )
            assert second_cred.status_code == 409

            # Exposure and panel_bind_host updates now succeed with JWT
            with patch(
                "app.modules.exposure.application.commands.get_playit_supervisor"
            ) as mock_sup_fn:
                mock_sup = AsyncMock()
                mock_sup.is_running = False
                mock_sup_fn.return_value = mock_sup

                expo_res = await client.put(
                    f"/api/v1/servers/{server_id}/exposure",
                    json={"method": "playit", "desired_state": "ENABLED"},
                    headers=jwt_headers,
                )
                assert expo_res.status_code == 200

            bind_res = await client.patch(
                "/api/v1/settings",
                json={"panel_bind_host": "0.0.0.0"},
                headers=jwt_headers,
            )
            assert bind_res.status_code == 200
            assert bind_res.json()["settings"]["panel_bind_host"] == "0.0.0.0"


def test_websocket_local_zero_login_and_proxy_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    @asynccontextmanager
    async def _noop_lifespan(_app):
        yield

    settings_yaml = tmp_path / "ws_settings.yaml"
    monkeypatch.setattr("app.core.settings_store._SETTINGS_FILE", settings_yaml)
    init_settings_store(settings_yaml)

    monkeypatch.setenv("ONX_DEPLOYMENT_PROFILE", "local")
    monkeypatch.delenv("ONX_PANEL_BIND_HOST", raising=False)
    monkeypatch.delenv("MCS_PANEL_BIND_HOST", raising=False)
    monkeypatch.setattr(config_mod, "_ACTIVE_PANEL_BIND_HOST", None)
    monkeypatch.setattr(config_mod, "_ACTIVE_PANEL_BIND_PORT", None)

    app = create_app(static_dir="off")
    app.router.lifespan_context = _noop_lifespan
    event_bus = EventBus()
    ws_endpoint.init_websocket(event_bus)

    from app.api import deps

    async def _get_event_bus() -> EventBus:
        return event_bus

    app.dependency_overrides[deps.get_event_bus] = _get_event_bus

    db_file = tmp_path / "ws_local_zero_login.db"

    async def _bind_db(create_tables: bool) -> object:
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", echo=False)
        if create_tables:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        database._engine = engine
        database._session_factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )
        return engine

    async def _unbind_db(engine: object) -> None:
        database._engine = None
        database._session_factory = None
        await engine.dispose()  # type: ignore[attr-defined]

    with TestClient(app, client=("127.0.0.1", 50010), base_url="http://127.0.0.1:8000") as tc:
        engine = tc.portal.call(_bind_db, True)
        try:
            with tc.websocket_connect("/ws", headers={"Host": "127.0.0.1:8000"}) as ws:
                ws.send_text('{"type": "ping"}')
                msg = json.loads(ws.receive_bytes().decode("utf-8"))
                assert msg["type"] == "pong"

            for spoofed_headers in (
                {"X-Forwarded-For": "198.51.100.1"},
                {"Forwarded": "for=203.0.113.5"},
                {"Host": "evil.attacker.com:8000"},
            ):
                with (
                    pytest.raises(WebSocketDisconnect),
                    tc.websocket_connect("/ws", headers=spoofed_headers),
                ):
                    pass
        finally:
            tc.portal.call(_unbind_db, engine)

    with TestClient(
        app, client=("198.51.100.5", 50011), base_url="http://127.0.0.1:8000"
    ) as remote_tc:
        remote_engine = remote_tc.portal.call(_bind_db, False)
        try:
            with pytest.raises(WebSocketDisconnect), remote_tc.websocket_connect("/ws"):
                pass
        finally:
            remote_tc.portal.call(_unbind_db, remote_engine)
