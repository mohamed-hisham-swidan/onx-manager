"""Regression tests for Red-Team Kill-List Remediations (Waves 1-3)."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.requests import Request
from starlette.websockets import WebSocketDisconnect

from app.api import deps
from app.api.v1.middleware.rate_limit import resolve_client_ip
from app.core.auth_utils import _resolve_api_key
from app.core.command_bus import CommandBus
from app.core.config import AppSettings
from app.core.event_bus import EventBus
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.core.query_bus import QueryBus
from app.core.security import hash_api_key
from app.main import create_app, ensure_cleanup_cron_job
from app.modules.auth.infrastructure.jwt import create_access_token
from app.modules.auth.infrastructure.models import (
    ApiKeyModel,
    RoleModel,
    UserModel,
    UserRoleModel,
)
from app.modules.backup.application.commands.restore_backup import (
    RestoreBackupCommand,
    RestoreBackupHandler,
)
from app.modules.backup.application.two_tier_restore import (
    cleanup_pre_restore_backups,
    restore_tier1_snapshot,
)
from app.modules.backup.domain.aggregate import BackupJob
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.backup.infrastructure.tier1_snapshot import create_tier1_snapshot
from app.modules.exposure.infrastructure.models import (
    ServerExposureModel,
    ServerExposureTargetModel,
)
from app.modules.server.application.commands.delete_server import (
    DeleteServerCommand,
    DeleteServerHandler,
)
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.value_objects import (
    JavaArguments,
    LocationType,
    MemoryAllocation,
    PortNumber,
    ServerDeployment,
    ServerProperties,
    ServerType,
)
from app.modules.server.infrastructure.models import ServerModel
from app.modules.server.infrastructure.providers.base import ServerRuntimeStatus
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import BackupJobId, MinecraftVersion, ServerId
from app.registration import register_handlers
from app.tasks.base import TaskQueue, TaskStatus
from app.tasks.definitions.cleanup_task import run_cleanup_task
from app.tasks.scheduler import CronJobModel, Scheduler
from app.websocket import endpoint as ws_endpoint
from app.websocket.authentication import WSAuthenticator
from app.websocket.authorization import ChannelAuthorizer
from app.websocket.buffer import OfflineMessageBuffer
from app.websocket.handlers import WSConnectionHandler
from app.websocket.manager import ConnectionRegistry
from app.websocket.rate_limiter import WSRateLimiter


async def _build_isolated_app(tmp_path: Path):
    db_file = tmp_path / "rt_remediation.db"
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


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_1_scheduler_lockdown_task_allowlist_interval_and_retention(tmp_path: Path) -> None:
    app, engine = await _build_isolated_app(tmp_path)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, client=("127.0.0.1", 50001)),
            base_url="http://test",
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

            # Seed server and server_admin user
            async with database._session_factory() as sess:
                sess.add(
                    ServerModel(
                        id="srv-1",
                        name="Alpha",
                        server_type="paper",
                        minecraft_version="1.21.1",
                        port=25565,
                        root_path=str(tmp_path / "srv-1"),
                        mode="simple",
                        created_at=datetime.now(UTC).replace(tzinfo=None),
                        updated_at=datetime.now(UTC).replace(tzinfo=None),
                    )
                )
                await sess.commit()

            sa_create = await client.post(
                "/api/v1/users/manage",
                headers=_auth(owner_token),
                json={
                    "username": "srvadmin",
                    "password": "srvadmin-password-123",
                    "role": "server_admin",
                    "server_ids": ["srv-1"],
                },
            )
            assert sa_create.status_code == 201
            sa_login = await client.post(
                "/api/v1/auth/login",
                json={"username": "srvadmin", "password": "srvadmin-password-123"},
            )
            sa_token = sa_login.json()["access_token"]

            # 1a. server_admin blocked from scheduling run_cleanup_task (403)
            r_cleanup = await client.post(
                "/api/v1/schedules",
                headers=_auth(sa_token),
                json={
                    "cron_expression": "0 0 * * *",
                    "task_name": "run_cleanup_task",
                    "params": {"server_id": "srv-1", "metrics_retention_days": 7},
                },
            )
            assert r_cleanup.status_code == 403

            # 1b. server_admin allowed to schedule run_backup_task for assigned server
            r_ok = await client.post(
                "/api/v1/schedules",
                headers=_auth(sa_token),
                json={
                    "cron_expression": "0 2 * * *",
                    "task_name": "run_backup_task",
                    "params": {"server_id": "srv-1"},
                },
            )
            assert r_ok.status_code == 201

            # 1c. interval:0.01s rejected (400)
            r_dos = await client.post(
                "/api/v1/schedules",
                headers=_auth(owner_token),
                json={
                    "cron_expression": "interval:0.01s",
                    "task_name": "run_backup_task",
                    "params": {"server_id": "srv-1"},
                },
            )
            assert r_dos.status_code == 400

            # 1d. retention_days=0 / metrics_retention_days=0 rejected (400)
            for bad_params in (
                {"retention_days": 0},
                {"metrics_retention_days": 0},
                {"log_retention_days": -1},
            ):
                r_ret = await client.post(
                    "/api/v1/schedules",
                    headers=_auth(owner_token),
                    json={
                        "cron_expression": "0 3 * * *",
                        "task_name": "run_cleanup_task",
                        "params": bad_params,
                    },
                )
                assert r_ret.status_code == 400

            # 1e. Arbitrary unknown task rejected for owner (400)
            r_arb = await client.post(
                "/api/v1/schedules",
                headers=_auth(owner_token),
                json={
                    "cron_expression": "0 3 * * *",
                    "task_name": "os.system",
                    "params": {},
                },
            )
            assert r_arb.status_code == 400

            with pytest.raises(ValueError, match=">= 1"):
                await run_cleanup_task({"metrics_retention_days": 0})
    finally:
        await engine.dispose()
        database._engine = None


@pytest.mark.asyncio
async def test_2_demoting_admin_revokes_and_intersects_api_keys(tmp_path: Path) -> None:
    app, engine = await _build_isolated_app(tmp_path)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, client=("127.0.0.1", 50002)),
            base_url="http://test",
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

            mk = await client.post(
                "/api/v1/users/manage",
                headers=_auth(owner_token),
                json={
                    "username": "demote_admin",
                    "password": "admin-password-123",
                    "role": "admin",
                },
            )
            assert mk.status_code == 201
            target_uid = mk.json()["user_id"]

            login = await client.post(
                "/api/v1/auth/login",
                json={"username": "demote_admin", "password": "admin-password-123"},
            )
            admin_jwt = login.json()["access_token"]

            key_res = await client.post(
                "/api/v1/auth/api-keys",
                headers=_auth(admin_jwt),
                json={"name": "admin-ci-key", "permissions": ["admin:full", "server:read"]},
            )
            assert key_res.status_code == 201
            raw_key = key_res.json()["key"]

            # Works while still admin
            assert (await client.get("/api/v1/users", headers=_auth(raw_key))).status_code == 200

            # Demote admin -> viewer via PUT /users/{id}/access
            demote = await client.put(
                f"/api/v1/users/{target_uid}/access",
                headers=_auth(owner_token),
                json={
                    "role": "viewer",
                    "server_ids": [],
                    "all_servers_access": False,
                    "denied_permissions": ["backups"],
                    "is_active": True,
                },
            )
            assert demote.status_code == 200

            # Old admin API key is immediately revoked (401)
            assert (await client.get("/api/v1/users", headers=_auth(raw_key))).status_code == 401

            # Even if an API key row is unrevoked in DB directly, live-role intersection
            # strips admin:full and backup:read (due to denied_permissions=["backups"]).
            async with database._session_factory() as sess:
                unrevoked = ApiKeyModel(
                    id="ak-stale-direct",
                    user_id=target_uid,
                    name="stale",
                    prefix="onx_st",
                    key_hash=hash_api_key("onx_stale_direct_key_999"),
                    permissions="admin:full,server:write,backup:read,server:read",
                    is_revoked=False,
                )
                sess.add(unrevoked)
                await sess.commit()

                ctx = await _resolve_api_key("onx_stale_direct_key_999", sess)
                assert "admin:full" not in ctx["permissions"]
                assert "server:write" not in ctx["permissions"]
                assert "backup:read" not in ctx["permissions"]
                assert ctx["permissions"] == ["server:read"]
                assert ctx["denied_permissions"] == ["backups"]
    finally:
        await engine.dispose()
        database._engine = None


@pytest.mark.no_isolated_db
def test_12_websocket_auth_fails_closed_on_db_error(tmp_path: Path) -> None:
    db_file = tmp_path / "ws_failclosed.db"
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

    async def _bind():
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        database._engine = engine
        database._session_factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )
        async with database._session_factory() as sess:
            sess.add(RoleModel(id="r-view", name="viewer", permissions="server:read"))
            sess.add(
                UserModel(
                    id="u-ws",
                    username="wsuser",
                    password_hash="h",
                    display_name="WS",
                    is_active=True,
                )
            )
            await sess.flush()
            sess.add(UserRoleModel(user_id="u-ws", role_id="r-view"))
            await sess.commit()
        return engine

    async def _unbind(engine) -> None:
        database._engine = None
        database._session_factory = None
        await engine.dispose()

    with TestClient(app) as client:
        engine = client.portal.call(_bind)
        try:
            # 12a. Handshake fails closed when DB lookup raises OperationalError
            token = create_access_token(
                user_id="u-ws", roles=["admin"], permissions=["admin:full"]
            )
            with (
                patch(
                    "app.core.authorization.load_user_model_with_roles",
                    side_effect=OperationalError("stmt", {}, Exception("database is locked")),
                ),
                pytest.raises(WebSocketDisconnect) as exc_info,
                client.websocket_connect(f"/ws?token={token}") as ws,
            ):
                ws.receive_bytes()
            assert exc_info.value.code == 1008
        finally:
            client.portal.call(_unbind, engine)


@pytest.mark.asyncio
async def test_12b_ws_handler_subscribe_and_exec_fail_closed_on_db_error() -> None:
    reg = ConnectionRegistry()
    auth = WSAuthenticator()
    authz = ChannelAuthorizer()
    buf = OfflineMessageBuffer()
    handler = WSConnectionHandler(reg, auth, authz, buf, WSRateLimiter())

    frames: list[dict] = []

    class _FakeWS:
        async def send_bytes(self, raw: bytes) -> None:
            frames.append(json.loads(raw.decode("utf-8")))

        async def close(self, **_kwargs) -> None:
            pass

    ws = _FakeWS()
    await reg.register("c1", ws)
    authz.set_user_context(
        "u-1",
        {
            "user_id": "u-1",
            "is_active": True,
            "db_resolved": True,
            "roles": ["admin"],
            "permissions": ["admin:full"],
        },
    )

    with patch(
        "app.websocket.handlers.load_user_model_with_roles",
        side_effect=OperationalError("stmt", {}, Exception("database is locked")),
    ):
        await handler._handle_message(
            ws, "c1", "u-1", {"type": "subscribe", "channels": ["server:srv-1"]}
        )
        await handler._handle_message(
            ws,
            "c1",
            "u-1",
            {
                "type": "exec_input",
                "target_type": "server",
                "target_id": "srv-1",
                "input": "stop",
            },
        )

    assert len(frames) == 2
    assert all(f["code"] == "PERMISSION_DENIED" for f in frames)
    assert await reg.get_by_channel("server:srv-1") == []


@pytest.mark.asyncio
async def test_3_and_4_restore_keeps_pre_restore_copy_off_loop_and_stopped_stale_ext_id(
    tmp_path: Path,
) -> None:
    server_dir = tmp_path / "servers" / "srv-1"
    snaps_root = tmp_path / "snaps"
    (server_dir / "world").mkdir(parents=True)
    (server_dir / "world" / "level.dat").write_bytes(b"v1-original")
    (server_dir / "server.properties").write_text("motd=V1\n", encoding="utf-8")

    snap = await create_tier1_snapshot(
        server_id="srv-1",
        server_dir=server_dir,
        snapshots_root=snaps_root,
        backup_id="bak-v1",
    )

    # Mutate live world before restore
    (server_dir / "world" / "level.dat").write_bytes(b"v2-before-restore")

    with patch(
        "app.modules.backup.application.two_tier_restore.asyncio.to_thread",
        wraps=asyncio.to_thread,
    ) as spy_to_thread:
        res = await restore_tier1_snapshot(
            server_id="srv-1",
            server_dir=server_dir,
            snapshot_dir=Path(snap.snapshot_dir),
            backup_id="bak-v1",
        )
        assert spy_to_thread.await_count >= 1

    assert res.restored_files >= 1
    assert (server_dir / "world" / "level.dat").read_bytes() == b"v1-original"

    # Pre-restore rollback copy must be preserved outside active server_dir
    retained_copies = list((tmp_path / "servers").glob(".onx-pre-restore-srv-1-*"))
    assert len(retained_copies) == 1
    assert (retained_copies[0] / "world" / "level.dat").read_bytes() == b"v2-before-restore"

    # Cleanup helper removes retained copy after clean start
    assert cleanup_pre_restore_backups("srv-1", server_dir) == 1
    assert list((tmp_path / "servers").glob(".onx-pre-restore-srv-1-*")) == []

    # #4: Stopped server with stale external_id must restore immediately (not defer)
    async with database._session_factory() as sess:
        s_repo = SQLServerRepository(sess)
        srv = Server.create(
            server_id=ServerId("srv-stale"),
            name="Stale",
            server_type=ServerType.PAPER,
            minecraft_version=MinecraftVersion.parse("1.21.1"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25565)),
            deployment=ServerDeployment(
                location_type=LocationType.LOCAL,
                root_path=str(tmp_path / "servers" / "srv-stale"),
                working_directory=".",
            ),
        )
        srv.start()
        srv.mark_running(pid=999999, port=25565, external_id="onx-stale-container")
        srv.stop(reason="test")
        srv.mark_stopped()
        srv.collect_events()
        await s_repo.save(srv)
        # Re-inject stale external_id onto the stopped DB row to simulate legacy/stale state
        row = await sess.get(ServerModel, "srv-stale")
        row.external_id = "onx-stale-container"
        await sess.commit()

        b_repo = SQLBackupRepository(sess)
        job = BackupJob.create(backup_id=BackupJobId("bak-stale"), server_id=ServerId("srv-stale"))
        job.mark_completed(size_bytes=123, checksum="abc", storage_path="bak.tar.gz.enc")
        await b_repo.save_job(job)
        await sess.commit()

    fake_provider = MagicMock()
    fake_provider.status = AsyncMock(return_value=ServerRuntimeStatus.STOPPED)
    with (
        patch(
            "app.modules.server.infrastructure.providers.provider_factory.get",
            return_value=fake_provider,
        ),
        patch(
            "app.modules.backup.application.commands.restore_backup._port_is_listening",
            return_value=False,
        ),
        patch(
            "app.modules.backup.application.commands.restore_backup.perform_safe_restore",
            AsyncMock(return_value=["world"]),
        ),
    ):
        handler = RestoreBackupHandler(EventBus())
        cmd_res = await handler.handle(RestoreBackupCommand(backup_id="bak-stale"))
    assert cmd_res.success is True
    assert cmd_res.data["deferred"] is False


def test_6_rate_limiter_proxy_aware_ip_resolution() -> None:
    def _req(peer: str, headers: dict[str, str]) -> Request:
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/auth/login",
            "client": (peer, 12345),
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        }
        return Request(scope)

    # Trusted proxy (loopback / Docker bridge) honors CF-Connecting-IP first
    assert (
        resolve_client_ip(
            _req(
                "127.0.0.1",
                {"CF-Connecting-IP": "198.51.100.77", "X-Forwarded-For": "203.0.113.9"},
            )
        )
        == "198.51.100.77"
    )
    # Trusted proxy honors right-most untrusted IP in X-Forwarded-For
    assert (
        resolve_client_ip(
            _req(
                "172.18.0.3",
                {"X-Forwarded-For": "9.9.9.9, 203.0.113.42, 10.0.0.2"},
            )
        )
        == "203.0.113.42"
    )
    # Untrusted public IP CANNOT spoof forwarding headers
    assert (
        resolve_client_ip(
            _req(
                "198.51.100.10",
                {
                    "CF-Connecting-IP": "1.1.1.1",
                    "X-Forwarded-For": "2.2.2.2",
                    "X-Real-IP": "3.3.3.3",
                },
            )
        )
        == "198.51.100.10"
    )


@pytest.mark.asyncio
async def test_7_and_8_vps_lockdown_metrics_docs_host_resources_and_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONX_DEPLOYMENT_PROFILE", "vps")
    monkeypatch.setenv("ONX_PANEL_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("ONX_DEBUG", "false")
    app, engine = await _build_isolated_app(tmp_path)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, client=("198.51.100.50", 54321)),
            base_url="http://test",
        ) as client:
            # Docs/OpenAPI hidden (404) in non-debug VPS mode
            assert (await client.get("/docs")).status_code == 404
            assert (await client.get("/openapi.json")).status_code == 404

            # /metrics blocked for unauthenticated remote/proxied caller
            assert (await client.get("/metrics")).status_code == 401

            # Bootstrap defaults to GLOBAL (invite-only) in VPS profile
            boot = await client.post(
                "/api/v1/setup/bootstrap",
                json={"username": "vpsowner", "password": "owner-password-123"},
            )
            assert boot.status_code == 201
            owner_token = boot.json()["access_token"]

            status_res = await client.get("/api/v1/setup/status")
            assert status_res.status_code == 200
            assert status_res.json()["access_mode"] == "GLOBAL"

            # Anonymous self-registration blocked
            reg = await client.post(
                "/api/v1/users",
                json={"username": "attacker", "password": "attacker-password-123"},
            )
            assert reg.status_code == 403

            # Create viewer & server_admin
            v_mk = await client.post(
                "/api/v1/users/manage",
                headers=_auth(owner_token),
                json={"username": "v1", "password": "viewer-password-123", "role": "viewer"},
            )
            assert v_mk.status_code == 201
            v_tok = (
                await client.post(
                    "/api/v1/auth/login",
                    json={"username": "v1", "password": "viewer-password-123"},
                )
            ).json()["access_token"]

            sa_mk = await client.post(
                "/api/v1/users/manage",
                headers=_auth(owner_token),
                json={
                    "username": "sa1",
                    "password": "sa-password-123",
                    "role": "server_admin",
                },
            )
            assert sa_mk.status_code == 201
            sa_tok = (
                await client.post(
                    "/api/v1/auth/login",
                    json={"username": "sa1", "password": "sa-password-123"},
                )
            ).json()["access_token"]

            # Viewer blocked from /metrics (403) and /monitoring/host-resources (403)
            assert (await client.get("/metrics", headers=_auth(v_tok))).status_code == 403
            assert (
                await client.get("/api/v1/monitoring/host-resources", headers=_auth(v_tok))
            ).status_code == 403

            # server_admin and owner allowed on /monitoring/host-resources
            assert (
                await client.get("/api/v1/monitoring/host-resources", headers=_auth(sa_tok))
            ).status_code == 200
            assert (
                await client.get("/api/v1/monitoring/host-resources", headers=_auth(owner_token))
            ).status_code == 200

            # Owner allowed on /metrics
            assert (await client.get("/metrics", headers=_auth(owner_token))).status_code in (
                200,
                501,
            )
    finally:
        await engine.dispose()
        database._engine = None


@pytest.mark.asyncio
async def test_9_delete_server_tears_down_exposures_and_upnp(tmp_path: Path) -> None:
    srv_dir = tmp_path / "servers" / "srv-del"
    srv_dir.mkdir(parents=True)
    async with database._session_factory() as sess:
        s_repo = SQLServerRepository(sess)
        srv = Server.create(
            server_id=ServerId("srv-del"),
            name="ToDelete",
            server_type=ServerType.PAPER,
            minecraft_version=MinecraftVersion.parse("1.21.1"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25565)),
            deployment=ServerDeployment(
                location_type=LocationType.LOCAL,
                root_path=str(srv_dir),
                working_directory=".",
            ),
        )
        srv.collect_events()
        await s_repo.save(srv)

        exp = ServerExposureModel(
            id="exp-del-1",
            server_id="srv-del",
            branch_name="main",
            method="port_forward",
            desired_state="ENABLED",
            aggregate_status="ACTIVE",
        )
        tgt = ServerExposureTargetModel(
            id="tgt-del-1",
            exposure_id="exp-del-1",
            service_type="java",
            protocol="tcp",
            local_port=25565,
            public_address="198.51.100.1:25565",
            status="ACTIVE",
        )
        sess.add(exp)
        sess.add(tgt)
        await sess.commit()

    mock_upnp = MagicMock()
    mock_upnp.delete_mapping = AsyncMock(return_value=True)
    mock_cf = MagicMock()
    mock_cf.stop = AsyncMock()
    mock_provider = MagicMock()
    mock_provider.status = AsyncMock(return_value=ServerRuntimeStatus.STOPPED)
    mock_provider.destroy = AsyncMock()
    mock_factory = MagicMock()
    mock_factory.get = MagicMock(return_value=mock_provider)

    with (
        patch("app.modules.exposure.infrastructure.upnp.AsyncUPnPService", return_value=mock_upnp),
        patch(
            "app.modules.exposure.infrastructure.cloudflared.get_server_cloudflared_supervisor",
            return_value=mock_cf,
        ),
        patch(
            "app.modules.server.application.commands.delete_server.AppSettings",
            return_value=AppSettings(servers_data_dir=str(tmp_path / "servers")),
        ),
    ):
        handler = DeleteServerHandler(EventBus(), provider_factory=mock_factory)
        res = await handler.handle(DeleteServerCommand(server_id="srv-del"))

    assert res.success is True
    mock_upnp.delete_mapping.assert_awaited_once_with(25565, protocol="TCP")


@pytest.mark.asyncio
async def test_11_startup_ensures_cleanup_cron_job_idempotently() -> None:
    async def _sf():
        return database.session_factory()

    scheduler = Scheduler(_sf)

    class _DummyQueue(TaskQueue):
        async def enqueue(self, _name: str, _params: dict | None = None, _delay: int = 0) -> str:
            return "tid"

        async def cancel(self, _task_id: str) -> bool:
            return True

        async def get_status(self, _task_id: str) -> TaskStatus:
            return TaskStatus.PENDING

        async def get_result(self, _task_id: str):
            return None

    scheduler.set_task_queue(_DummyQueue())
    await scheduler.start()
    try:
        created_first = await ensure_cleanup_cron_job(scheduler, _sf)
        created_second = await ensure_cleanup_cron_job(scheduler, _sf)
        assert created_first is True
        assert created_second is False

        async with database.session_factory() as sess:
            rows = (
                await sess.execute(
                    select(CronJobModel).where(CronJobModel.task_name == "run_cleanup_task")
                )
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0].name == "system_cleanup_daily"
            assert rows[0].cron_expression == "interval:86400s"
    finally:
        await scheduler.stop()
