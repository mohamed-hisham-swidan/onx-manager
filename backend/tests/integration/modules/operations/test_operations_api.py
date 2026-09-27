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


def auth_headers(permissions: list[str]) -> dict[str, str]:
    token = create_access_token(
        user_id="usr-test-1",
        roles=["operator"],
        permissions=permissions,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_operations_api_permissions():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Unauthenticated -> 401
        res = await client.get("/api/v1/operations")
        assert res.status_code == 401

        # 2. Missing server:read -> 403
        res = await client.get("/api/v1/operations", headers=auth_headers(["backup:read"]))
        assert res.status_code == 403

        # 3. With server:read -> 200 []
        res = await client.get("/api/v1/operations", headers=auth_headers(["server:read"]))
        assert res.status_code == 200
        assert res.json() == []

        # 4. POST without server:write -> 403
        res = await client.post(
            "/api/v1/operations",
            json={"type": "BACKUP_RESTORE", "target_type": "server", "target_id": "srv-1"},
            headers=auth_headers(["server:read"]),
        )
        assert res.status_code == 403

        # 5. POST with server:write -> 202
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
        res = await client.get(f"/api/v1/operations/{op_id}", headers=auth_headers(["server:read"]))
        assert res.status_code == 200
        assert res.json()["id"] == op_id


@pytest.mark.asyncio
async def test_operations_idempotency_and_headers():
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
