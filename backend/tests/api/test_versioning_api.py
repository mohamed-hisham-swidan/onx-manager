from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

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
from app.modules.versioning.domain.value_objects import TestRunStatus
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
async def seed_server():
    async with database.session_factory() as session:
        server = ServerModel(
            id="srv-vers-1",
            name="VersioningTestServer",
            server_type="vanilla",
            minecraft_version="1.21.1",
            status="STOPPED",
            root_path="/tmp/test_srv_vers_1",
            deployment_host="127.0.0.1",
            port=25565,
            java_args="-Xmx2G",
            bot_verification_settings={"bot_count": 5, "duration_minutes": 10},
            mode="advanced",
        )
        session.add(server)
        await session.commit()
    return "srv-vers-1"


def auth_headers(permissions: list[str]) -> dict[str, str]:
    token = create_access_token(
        user_id="usr-1",
        roles=["operator"],
        permissions=permissions,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_branches_permissions(seed_server):
    srv_id = seed_server
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Without auth -> 401
        res = await client.get(f"/api/v1/servers/{srv_id}/versioning/branches")
        assert res.status_code == 401

        # 2. Missing server:version:read -> 403
        res = await client.get(
            f"/api/v1/servers/{srv_id}/versioning/branches",
            headers=auth_headers(["server:read"]),
        )
        assert res.status_code == 403

        # 3. With server:version:read -> 200 []
        res = await client.get(
            f"/api/v1/servers/{srv_id}/versioning/branches",
            headers=auth_headers(["server:version:read"]),
        )
        assert res.status_code == 200
        assert res.json() == []

        # 4. Create branch without server:version:commit -> 403
        res = await client.post(
            f"/api/v1/servers/{srv_id}/versioning/branches",
            json={"name": "feat-test"},
            headers=auth_headers(["server:version:read"]),
        )
        assert res.status_code == 403

        # 5. Create branch with server:version:commit -> 201
        res = await client.post(
            f"/api/v1/servers/{srv_id}/versioning/branches",
            json={"name": "feat-test"},
            headers=auth_headers(["server:version:commit"]),
        )
        assert res.status_code == 201
        data = res.json()
        assert data["name"] == "feat-test"

        # 6. Branch list now contains feat-test
        res = await client.get(
            f"/api/v1/servers/{srv_id}/versioning/branches",
            headers=auth_headers(["server:version:read"]),
        )
        assert res.status_code == 200
        branches = res.json()
        assert len(branches) == 1
        assert branches[0]["name"] == "feat-test"


@pytest.mark.asyncio
async def test_bot_settings_endpoints(seed_server):
    srv_id = seed_server
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # GET settings
        res = await client.get(
            f"/api/v1/servers/{srv_id}/versioning/settings",
            headers=auth_headers(["server:version:read"]),
        )
        assert res.status_code == 200
        data = res.json()
        assert data["bot_count"] == 5
        assert data["duration_minutes"] == 10
        assert data["effective_bot_count"] == 5

        # PUT settings without server:test:configure -> 403
        res = await client.put(
            f"/api/v1/servers/{srv_id}/versioning/settings",
            json={"bot_count": 20, "duration_minutes": 30},
            headers=auth_headers(["server:version:read"]),
        )
        assert res.status_code == 403

        # PUT settings with server:test:configure -> 200
        res = await client.put(
            f"/api/v1/servers/{srv_id}/versioning/settings",
            json={"bot_count": 20, "duration_minutes": 30},
            headers=auth_headers(["server:test:configure"]),
        )
        assert res.status_code == 200
        data = res.json()
        assert data["bot_count"] == 20
        assert data["duration_minutes"] == 30
        assert data["effective_bot_count"] == 20


@pytest.mark.asyncio
async def test_preflight_endpoint(seed_server):
    srv_id = seed_server
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch(
            "app.modules.versioning.infrastructure.storage_probe.StorageCapabilityProbe.probe_path",
            return_value=True,
        ):
            res = await client.get(
                f"/api/v1/servers/{srv_id}/versioning/preflight?bot_count=10",
                headers=auth_headers(["server:version:read"]),
            )
            assert res.status_code == 200
            data = res.json()
            assert data["reflink_supported"] is True
            assert "available_ram_mb" in data
            assert "available_cores" in data


@pytest.mark.asyncio
async def test_commits_endpoints(seed_server, tmp_path):
    srv_id = seed_server
    server_dir = tmp_path / "server_root"
    server_dir.mkdir(parents=True, exist_ok=True)
    (server_dir / "server.properties").write_text("server-port=25565\nmotd=Versioning\n")

    async with database.session_factory() as session:
        srv_model = await session.get(ServerModel, srv_id)
        srv_model.root_path = str(server_dir)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with (
            patch(
                "app.modules.versioning.infrastructure.storage_probe.StorageCapabilityProbe.assert_supports_reflink"
            ),
            patch(
                "app.modules.versioning.infrastructure.btrfs_zfs_driver.BtrfsZfsSnapshotDriver.create_snapshot",
                return_value=1024,
            ),
        ):
            # 1. POST commit without server:version:commit -> 403
            res = await client.post(
                f"/api/v1/servers/{srv_id}/versioning/commits",
                json={"message": "Initial commit", "branch_name": "main"},
                headers=auth_headers(["server:version:read"]),
            )
            assert res.status_code == 403

            # 2. POST commit with server:version:commit -> 201
            res = await client.post(
                f"/api/v1/servers/{srv_id}/versioning/commits",
                json={"message": "Initial commit", "branch_name": "main"},
                headers=auth_headers(["server:version:commit"]),
            )
            assert res.status_code == 201
            commit_data = res.json()
            assert "commit_id" in commit_data
            commit_id = commit_data["commit_id"]

            # 3. GET commits without server:version:read -> 403
            res = await client.get(
                f"/api/v1/servers/{srv_id}/versioning/commits",
                headers=auth_headers([]),
            )
            assert res.status_code == 403

            # 4. GET commits with server:version:read -> 200
            res = await client.get(
                f"/api/v1/servers/{srv_id}/versioning/commits",
                headers=auth_headers(["server:version:read"]),
            )
            assert res.status_code == 200
            commits = res.json()
            assert len(commits) == 1
            assert commits[0]["id"] == commit_id
            assert commits[0]["message"] == "Initial commit"


@pytest.mark.asyncio
async def test_test_runs_and_lifecycle_endpoints(seed_server, tmp_path):
    srv_id = seed_server
    server_dir = tmp_path / "server_root_test"
    server_dir.mkdir(parents=True, exist_ok=True)
    (server_dir / "server.properties").write_text("server-port=25565\n")

    async with database.session_factory() as session:
        srv_model = await session.get(ServerModel, srv_id)
        srv_model.root_path = str(server_dir)
        await session.commit()

    # Pre-seed a branch and a commit in DB
    with (
        patch(
            "app.modules.versioning.infrastructure.storage_probe.StorageCapabilityProbe.assert_supports_reflink"
        ),
        patch(
            "app.modules.versioning.infrastructure.btrfs_zfs_driver.BtrfsZfsSnapshotDriver.create_snapshot",
            return_value=2048,
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.post(
                f"/api/v1/servers/{srv_id}/versioning/commits",
                json={"message": "Commit for test", "branch_name": "main"},
                headers=auth_headers(["server:version:commit"]),
            )
            assert res.status_code == 201
            commit_id = res.json()["commit_id"]

            # Run test without server:test:execute -> 403
            res = await client.post(
                f"/api/v1/servers/{srv_id}/versioning/tests",
                json={"commit_id": commit_id, "bot_count": 5, "duration_minutes": 2},
                headers=auth_headers(["server:version:read"]),
            )
            assert res.status_code == 403

            # Run test with server:test:execute -> 202
            from app.modules.versioning.infrastructure.test_runner import TestHandle

            with (
                patch(
                    "app.modules.versioning.infrastructure.test_runner.DockerTestExecutionRunner.run_test",
                    new_callable=AsyncMock,
                ) as mock_run_fn,
                patch(
                    "app.modules.versioning.infrastructure.test_runner.DockerTestExecutionRunner.cleanup_test",
                    new_callable=AsyncMock,
                ),
            ):
                mock_run_fn.return_value = TestHandle(
                    test_id="test-run-api-1",
                    server_id=srv_id,
                    container_name="onx-test-test-run-api-1",
                    test_dir=str(server_dir),
                    sidecar_runner=None,
                    status=TestRunStatus.RUNNING,
                )

                res = await client.post(
                    f"/api/v1/servers/{srv_id}/versioning/tests",
                    json={"commit_id": commit_id, "bot_count": 5, "duration_minutes": 2},
                    headers=auth_headers(["server:test:execute"]),
                )
                assert res.status_code == 202
                test_id = res.json()["test_id"]

                # GET test status
                res = await client.get(
                    f"/api/v1/servers/{srv_id}/versioning/tests/{test_id}",
                    headers=auth_headers(["server:version:read"]),
                )
                assert res.status_code == 200
                status_data = res.json()
                assert status_data["id"] == test_id
                assert status_data["status"] in ("BOOTING", "RUNNING")

                # GET test runs list without server:version:read -> 403
                res = await client.get(
                    f"/api/v1/servers/{srv_id}/versioning/tests",
                    headers=auth_headers(["server:read"]),
                )
                assert res.status_code == 403

                # GET test runs list with server:version:read -> 200
                res = await client.get(
                    f"/api/v1/servers/{srv_id}/versioning/tests",
                    headers=auth_headers(["server:version:read"]),
                )
                assert res.status_code == 200
                runs_list = res.json()
                assert len(runs_list) >= 1
                assert runs_list[0]["id"] == test_id

                # Discard test without server:test:execute -> 403
                res = await client.post(
                    f"/api/v1/servers/{srv_id}/versioning/tests/{test_id}/discard",
                    headers=auth_headers(["server:version:read"]),
                )
                assert res.status_code == 403

                # Discard test with server:test:execute -> 200
                res = await client.post(
                    f"/api/v1/servers/{srv_id}/versioning/tests/{test_id}/discard",
                    headers=auth_headers(["server:test:execute"]),
                )
                assert res.status_code == 200
