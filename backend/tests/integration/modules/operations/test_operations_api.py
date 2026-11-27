from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import deps
from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.idempotency import reset_idempotency_store
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.core.query_bus import QueryBus
from app.main import app
from app.modules.auth.infrastructure.jwt import create_access_token
from app.modules.server.infrastructure.models import ServerMembershipModel, ServerModel
from app.registration import register_handlers


@pytest.fixture(autouse=True)
async def init_test_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    old_engine = database._engine
    old_factory = database._session_factory
    database._engine = engine
    database._session_factory = session_factory

    reset_idempotency_store()

    cb = CommandBus()
    qb = QueryBus()
    eb = EventBus()
    register_handlers(cb, qb, eb)
    deps.init_buses(cb, qb, eb)

    yield
    database._engine = old_engine
    database._session_factory = old_factory
    await engine.dispose()
    reset_idempotency_store()


def auth_headers(
    permissions: list[str],
    *,
    user_id: str = "usr-test-1",
    roles: list[str] | None = None,
) -> dict[str, str]:
    token = create_access_token(
        user_id=user_id,
        roles=roles or (["admin"] if "admin:full" in permissions else ["server_admin"]),
        permissions=permissions,
    )
    return {"Authorization": f"Bearer {token}"}


async def _seed_server_access(server_id: str, user_id: str = "usr-test-1", role: str = "server_admin") -> None:
    async with database.session_factory() as session:
        if await session.get(ServerModel, server_id) is None:
            session.add(
                ServerModel(
                    id=server_id,
                    name=server_id,
                    server_type="paper",
                    minecraft_version="1.21.4",
                    status="stopped",
                )
            )
            await session.flush()
        session.add(
            ServerMembershipModel(
                id=f"mem-{server_id}-{user_id}",
                server_id=server_id,
                user_id=user_id,
                role=role,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_operations_api_permissions():
    await _seed_server_access("srv-1", user_id="usr-test-1", role="server_admin")
    await _seed_server_access("srv-1", user_id="usr-viewer-1", role="viewer")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Unauthenticated -> 401
        res = await client.get("/api/v1/operations")
        assert res.status_code == 401

        # 2. Unassigned user filtered to target server -> 403; unfiltered -> []
        outsider = auth_headers(["backup:read"], user_id="usr-outsider", roles=["viewer"])
        res = await client.get(
            "/api/v1/operations?target_type=server&target_id=srv-1",
            headers=outsider,
        )
        assert res.status_code == 403
        res_unfiltered = await client.get("/api/v1/operations", headers=outsider)
        assert res_unfiltered.status_code == 200
        assert res_unfiltered.json() == []

        # 3. Viewer with server:read -> 200 []
        viewer = auth_headers(["server:read"], user_id="usr-viewer-1", roles=["viewer"])
        res = await client.get("/api/v1/operations", headers=viewer)
        assert res.status_code == 200
        assert res.json() == []

        # 4. POST by viewer (without write access) -> 403
        res = await client.post(
            "/api/v1/operations",
            json={"type": "BACKUP_RESTORE", "target_type": "server", "target_id": "srv-1"},
            headers=viewer,
        )
        assert res.status_code == 403

        # 5. POST by assigned server_admin -> 202
        res = await client.post(
            "/api/v1/operations",
            json={"type": "BACKUP_RESTORE", "target_type": "server", "target_id": "srv-1"},
            headers=auth_headers(["server:write"]),
        )
        assert res.status_code == 202
        op_data = res.json()
        op_id = op_data["id"]
        assert op_data["status"] == "QUEUED"
        assert op_data["type"] == "BACKUP_RESTORE"

        # 6. GET /api/v1/operations/{op_id}
        res = await client.get(f"/api/v1/operations/{op_id}", headers=viewer)
        assert res.status_code == 200
        assert res.json()["id"] == op_id


@pytest.mark.asyncio
async def test_operations_idempotency_and_headers():
    await _seed_server_access("srv-idem")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {**auth_headers(["server:write"]), "Idempotency-Key": "idem-key-123"}
        payload = {
            "type": "BACKUP_RESTORE",
            "target_type": "server",
            "target_id": "srv-idem",
        }

        # First request
        res1 = await client.post("/api/v1/operations", json=payload, headers=headers)
        assert res1.status_code == 202
        op1 = res1.json()

        # Duplicate request with same Idempotency-Key header -> idempotent replay
        res2 = await client.post("/api/v1/operations", json=payload, headers=headers)
        assert res2.status_code == 202
        op2 = res2.json()

        assert op1["id"] == op2["id"]


@pytest.mark.asyncio
async def test_operations_concurrency_and_run_test_exemption():
    await _seed_server_access("srv-shared")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = auth_headers(["server:write"])

        # 1. Start a BACKUP_RESTORE operation
        res1 = await client.post(
            "/api/v1/operations",
            json={"type": "BACKUP_RESTORE", "target_type": "server", "target_id": "srv-shared"},
            headers=headers,
        )
        assert res1.status_code == 202

        # 2. Second concurrent mutating operation on same target -> 409 Conflict
        res2 = await client.post(
            "/api/v1/operations",
            json={"type": "STOP_SERVER", "target_type": "server", "target_id": "srv-shared"},
            headers=headers,
        )
        assert res2.status_code == 409
        assert "is already active" in res2.json()["message"]

        # 3. RUN_TEST operation on the same target -> exempted by §15.1, must succeed (202)
        res3 = await client.post(
            "/api/v1/operations",
            json={"type": "RUN_TEST", "target_type": "server", "target_id": "srv-shared"},
            headers=headers,
        )
        assert res3.status_code == 202
        assert res3.json()["type"] == "RUN_TEST"

        # 4. Another RUN_TEST on the same target -> also exempted and allowed concurrently
        res4 = await client.post(
            "/api/v1/operations",
            json={"type": "RUN_TEST", "target_type": "server", "target_id": "srv-shared"},
            headers=headers,
        )
        assert res4.status_code == 202


@pytest.mark.asyncio
async def test_operation_cancel_and_retry_flow():
    await _seed_server_access("srv-lifecycle")
    await _seed_server_access("srv-failed-test")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        write_headers = auth_headers(["server:write"])
        read_headers = auth_headers(["server:read"])

        # 1. Create operation
        create_res = await client.post(
            "/api/v1/operations",
            json={"type": "SERVER_START", "target_type": "server", "target_id": "srv-lifecycle"},
            headers=write_headers,
        )
        assert create_res.status_code == 202
        op_id = create_res.json()["id"]

        # 2. Cancel operation
        cancel_res = await client.post(
            f"/api/v1/operations/{op_id}/cancel",
            headers=write_headers,
        )
        assert cancel_res.status_code == 202
        cancelled_op = cancel_res.json()
        assert cancelled_op["status"] in ("CANCEL_REQUESTED", "CANCELLED")

        # 3. Cancel idempotent replay
        cancel_res2 = await client.post(
            f"/api/v1/operations/{op_id}/cancel",
            headers=write_headers,
        )
        assert cancel_res2.status_code == 202

        # 4. Verify terminal/cancelled status via GET
        get_res = await client.get(f"/api/v1/operations/{op_id}", headers=read_headers)
        assert get_res.status_code == 200

        # 5. Retrying a CANCELLED op is rejected (only FAILED or TIMED_OUT can be retried)
        retry_cancel_res = await client.post(
            f"/api/v1/operations/{op_id}/retry",
            headers=write_headers,
        )
        assert retry_cancel_res.status_code in (400, 409)

        # 6. Retry a FAILED operation
        # Seed a failed operation directly in DB
        async with database.session_factory() as session:
            from app.modules.operations.domain.aggregate import Operation
            from app.modules.operations.infrastructure.repository import SQLOperationRepository
            repo = SQLOperationRepository(session)
            failed_op = Operation.create(
                type="BACKUP_RESTORE",
                target_type="server",
                target_id="srv-failed-test",
            )
            failed_op.prepare()
            failed_op.fail(
                failure_code="BACKUP_CORRUPTED",
                error_message="Backup checksum mismatch",
            )
            saved = await repo.save(failed_op)
            await session.commit()
            failed_op_id = saved.id

        retry_res = await client.post(
            f"/api/v1/operations/{failed_op_id}/retry",
            headers=write_headers,
        )
        assert retry_res.status_code == 202
        retried_op = retry_res.json()
        assert retried_op["id"] == failed_op_id
        assert retried_op["status"] == "PREPARING"


@pytest.mark.asyncio
async def test_stale_orphan_operation_reaped_and_live_conflict_returns_op_id():
    import asyncio
    import contextlib
    from datetime import UTC, datetime, timedelta

    from app.modules.operations.application.services import operation_service as op_svc_mod
    from app.modules.operations.domain.aggregate import Operation
    from app.modules.operations.domain.enums import OperationStatus
    from app.modules.operations.infrastructure.repository import SQLOperationRepository

    await _seed_server_access("srv-orphan-reap")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        write_headers = auth_headers(["server:write"])
        read_headers = auth_headers(["server:read"])

        # 1. Seed a stale pre-boot active SERVER_UPGRADE operation with no live task
        async with database.session_factory() as session:
            repo = SQLOperationRepository(session)
            stale_op = Operation.create(
                type="SERVER_UPGRADE",
                target_type="server",
                target_id="srv-orphan-reap",
            )
            stale_op.created_at = datetime.now(UTC) - timedelta(hours=2)
            stale_op.start(at=datetime.now(UTC) - timedelta(hours=2))
            saved_stale = await repo.save(stale_op)
            await session.commit()
            stale_id = saved_stale.id

        # 2. Creating a new mutating op on the same server reaps the dead-process row & succeeds
        res_new = await client.post(
            "/api/v1/operations",
            json={
                "type": "SERVER_UPGRADE",
                "target_type": "server",
                "target_id": "srv-orphan-reap",
            },
            headers=write_headers,
        )
        assert res_new.status_code == 202
        live_op_id = res_new.json()["id"]
        assert live_op_id != stale_id

        # Verify the orphaned row was marked FAILED with PROCESS_TERMINATED
        get_stale = await client.get(f"/api/v1/operations/{stale_id}", headers=read_headers)
        assert get_stale.status_code == 200
        assert get_stale.json()["status"] == OperationStatus.FAILED.value
        assert get_stale.json()["failure_code"] == "PROCESS_TERMINATED"

        # 3. Register a live task on the new operation -> genuine conflict returns operation_id
        svc = op_svc_mod.get_operation_service()
        live_task = asyncio.create_task(asyncio.sleep(30))
        svc.executor.register_task(live_op_id, live_task)
        try:
            res_conflict = await client.post(
                "/api/v1/operations",
                json={
                    "type": "SERVER_UPGRADE",
                    "target_type": "server",
                    "target_id": "srv-orphan-reap",
                },
                headers=write_headers,
            )
            assert res_conflict.status_code == 409
            body = res_conflict.json()
            assert "Mutating operation 'SERVER_UPGRADE' is already active" in body["message"]
            assert body["detail"]["operation_id"] == live_op_id
        finally:
            live_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await live_task
