"""Stage F Test Definitions and Evidence API Test Suite.

Verifies:
- POST /api/v1/servers/{server_id}/versioning/test-definitions (server:test:configure)
- GET /api/v1/servers/{server_id}/versioning/test-definitions (server:version:read)
- GET /api/v1/servers/{server_id}/versioning/test-definitions/{id} (server:version:read)
- PUT /api/v1/servers/{server_id}/versioning/test-definitions/{id} (server:test:configure)
- DELETE /api/v1/servers/{server_id}/versioning/test-definitions/{id} (server:test:configure)
- GET /api/v1/servers/{server_id}/versioning/tests/{test_id}/evidence (server:version:read)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import deps
from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.core.query_bus import QueryBus
from app.main import app
from app.modules.auth.infrastructure.jwt import create_access_token
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.domain.entities import Runtime, ServerTestRun
from app.modules.versioning.domain.value_objects import RuntimeStatus, TestRunStatus
from app.modules.versioning.infrastructure.repository import SQLVersioningRepository
from app.registration import register_handlers

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="P2 Advanced versioning routes require a POSIX host; Windows remains Simple-only",
)


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

    cb = CommandBus()
    qb = QueryBus()
    eb = EventBus()
    register_handlers(cb, qb, eb)
    deps.init_buses(cb, qb, eb)

    yield
    database._engine = old_engine
    database._session_factory = old_factory
    await engine.dispose()


@pytest.fixture
async def seed_stage_f_server(tmp_path: Path):
    server_dir = tmp_path / "stage_f_server"
    server_dir.mkdir(parents=True, exist_ok=True)
    srv_id = "srv-stage-f"

    async with database.session_factory() as session:
        server = ServerModel(
            id=srv_id,
            name="StageFServer",
            server_type="vanilla",
            minecraft_version="1.21.1",
            status="STOPPED",
            root_path=str(server_dir),
            deployment_host="127.0.0.1",
            port=25565,
            mode="advanced",
        )
        session.add(server)

        repo = SQLVersioningRepository(session)
        rt = Runtime(
            id="rt-f-001",
            commit_id="c-f-001",
            server_id=srv_id,
            container_id="cont-f-123",
            status=RuntimeStatus.TERMINATED,
            exit_code=0,
        )
        await repo.save_runtime(rt)

        run = ServerTestRun(
            id="tr-f-001",
            server_id=srv_id,
            commit_id="c-f-001",
            status=TestRunStatus.PASSED,
            runtime_id=rt.id,
            evidence_bundle={
                "test_id": "tr-f-001",
                "server_id": srv_id,
                "commit_id": "c-f-001",
                "runtime": {
                    "runtime_id": rt.id,
                    "container_id": "cont-f-123",
                    "status": "TERMINATED",
                    "exit_code": 0,
                    "oom_killed": False,
                },
                "assertions": {"clean_shutdown": True},
                "crash_analysis": {},
                "log_tail": ["[Server thread/INFO]: Done!"],
            },
        )
        await repo.save_test_run(run)
        await session.commit()

    return srv_id


def auth_headers(permissions: list[str]) -> dict[str, str]:
    token = create_access_token(
        user_id="usr-test",
        roles=["operator"],
        permissions=permissions,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_test_definitions_crud_api(seed_stage_f_server):
    srv_id = seed_stage_f_server

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. POST without auth -> 401
        res = await client.post(
            f"/api/v1/servers/{srv_id}/versioning/test-definitions",
            json={"name": "Nightly Regression"},
        )
        assert res.status_code == 401

        # 2. POST with wrong permission -> 403
        res = await client.post(
            f"/api/v1/servers/{srv_id}/versioning/test-definitions",
            json={"name": "Nightly Regression"},
            headers=auth_headers(["server:version:read"]),
        )
        assert res.status_code == 403

        # 3. POST with server:test:configure -> 201
        res = await client.post(
            f"/api/v1/servers/{srv_id}/versioning/test-definitions",
            json={
                "name": "Nightly Regression",
                "description": "5 bots for 60 seconds",
                "bot_technology": "mineflayer",
                "bot_count": 8,
                "duration_seconds": 90,
            },
            headers=auth_headers(["server:test:configure"]),
        )
        assert res.status_code == 201
        created_data = res.json()
        def_id = created_data["id"]
        assert def_id.startswith("td-")

        # 4. GET /test-definitions -> 200 list
        res = await client.get(
            f"/api/v1/servers/{srv_id}/versioning/test-definitions",
            headers=auth_headers(["server:version:read"]),
        )
        assert res.status_code == 200
        defs = res.json()
        assert len(defs) == 1
        assert defs[0]["id"] == def_id
        assert defs[0]["bot_count"] == 8
        assert defs[0]["duration_seconds"] == 90

        # 5. GET /test-definitions/{id} -> 200 detail
        res = await client.get(
            f"/api/v1/servers/{srv_id}/versioning/test-definitions/{def_id}",
            headers=auth_headers(["server:version:read"]),
        )
        assert res.status_code == 200
        assert res.json()["name"] == "Nightly Regression"

        # 6. PUT /test-definitions/{id} -> 200 update
        res = await client.put(
            f"/api/v1/servers/{srv_id}/versioning/test-definitions/{def_id}",
            json={"name": "Updated Regression Name", "bot_count": 15},
            headers=auth_headers(["server:test:configure"]),
        )
        assert res.status_code == 200

        # Verify update persisted
        res = await client.get(
            f"/api/v1/servers/{srv_id}/versioning/test-definitions/{def_id}",
            headers=auth_headers(["server:version:read"]),
        )
        assert res.status_code == 200
        assert res.json()["name"] == "Updated Regression Name"
        assert res.json()["bot_count"] == 15

        # 7. DELETE /test-definitions/{id} -> 200 delete
        res = await client.delete(
            f"/api/v1/servers/{srv_id}/versioning/test-definitions/{def_id}",
            headers=auth_headers(["server:test:configure"]),
        )
        assert res.status_code == 200

        # Verify 404 after delete
        res = await client.get(
            f"/api/v1/servers/{srv_id}/versioning/test-definitions/{def_id}",
            headers=auth_headers(["server:version:read"]),
        )
        assert res.status_code == 404


@pytest.mark.asyncio
async def test_get_evidence_api(seed_stage_f_server):
    srv_id = seed_stage_f_server

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # GET evidence with server:version:read
        res = await client.get(
            f"/api/v1/servers/{srv_id}/versioning/tests/tr-f-001/evidence",
            headers=auth_headers(["server:version:read"]),
        )
        assert res.status_code == 200
        evidence = res.json()
        assert evidence["test_id"] == "tr-f-001"
        assert evidence["runtime"]["runtime_id"] == "rt-f-001"
        assert evidence["runtime"]["status"] == "TERMINATED"
        assert evidence["assertions"]["clean_shutdown"] is True
        assert "[Server thread/INFO]: Done!" in evidence["log_tail"]

        # GET evidence for nonexistent test -> 404
        res = await client.get(
            f"/api/v1/servers/{srv_id}/versioning/tests/tr-nonexistent/evidence",
            headers=auth_headers(["server:version:read"]),
        )
        assert res.status_code == 404
