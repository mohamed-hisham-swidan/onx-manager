from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.command_bus import CommandBus
from app.core.config import AppSettings
from app.core.event_bus import EventBus
from app.core.query_bus import QueryBus
from app.main import app
from app.registration import register_handlers


@pytest.fixture(scope="session")
def buses():
    event_bus = EventBus()
    command_bus = CommandBus()
    query_bus = QueryBus()
    register_handlers(command_bus, query_bus, event_bus)
    return command_bus, query_bus, event_bus


@pytest.fixture(autouse=True)
def _override_deps(buses) -> None:
    command_bus, query_bus, event_bus = buses
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


@pytest.fixture
async def client(tmp_path) -> AsyncClient:
    import os

    from app.core.persistence.base import Base
    from app.core.persistence.db import database
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    database._engine = engine
    database._session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    old_data_dir = os.environ.get("MCS_SERVERS_DATA_DIR")
    test_servers_dir = tmp_path / "test_servers"
    test_servers_dir.mkdir(parents=True, exist_ok=True)
    os.environ["MCS_SERVERS_DATA_DIR"] = str(test_servers_dir)

    transport = ASGITransport(app=app)
    with patch(
        "app.modules.server.application.services.jar_service.download_server_jar",
        AsyncMock(return_value="/tmp/mock-jar/server.jar"),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    await engine.dispose()
    database._engine = None
    database._session_factory = None
    if old_data_dir is not None:
        os.environ["MCS_SERVERS_DATA_DIR"] = old_data_dir
    else:
        os.environ.pop("MCS_SERVERS_DATA_DIR", None)


@pytest.fixture
async def created_user(client: AsyncClient) -> dict:
    resp = await client.post(
        "/api/v1/users",
        json={"email": "test@test.com", "password": "password123", "display_name": "Test User"},
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture
async def auth_token(client: AsyncClient, created_user: dict) -> str:
    resp = await client.post("/api/v1/auth/login", json={"email": "test@test.com", "password": "password123"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture
def auth_header(auth_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture
async def created_server(client: AsyncClient, auth_header: dict[str, str]) -> dict:
    payload = {
        "name": "API Test Server",
        "minecraft_version": "1.21",
        "min_memory_mb": 1024,
        "max_memory_mb": 2048,
        "port": 25565,
        "gamemode": "survival",
        "difficulty": "easy",
    }
    resp = await client.post("/api/v1/servers", json=payload, headers=auth_header)
    assert resp.status_code == 201
    return resp.json()


class TestHealth:
    async def test_health_check(self, client: AsyncClient) -> None:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "database" in data

    async def test_health_has_request_id(self, client: AsyncClient) -> None:
        resp = await client.get("/health")
        assert resp.headers.get("x-request-id") is not None


class TestAuth:
    async def test_create_user_and_login(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/users",
            json={"email": "new@test.com", "password": "password123", "display_name": "New User"},
        )
        assert resp.status_code == 201
        resp = await client.post("/api/v1/auth/login", json={"email": "new@test.com", "password": "password123"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"]
        assert data["token_type"] == "bearer"

    async def test_login_invalid_credentials(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/auth/login", json={"email": "nonexistent@test.com", "password": "wrong"})
        assert resp.status_code == 401

    async def test_login_missing_fields(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/auth/login", json={"email": "", "password": ""})
        assert resp.status_code == 422

    async def test_login_invalid_email_format(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/auth/login", json={"email": "not-an-email", "password": "password"})
        assert resp.status_code == 422

    async def test_refresh_token(self, client: AsyncClient, created_user: dict) -> None:
        login_resp = await client.post("/api/v1/auth/login", json={"email": "test@test.com", "password": "password123"})
        assert login_resp.status_code == 200
        refresh_token = login_resp.json()["refresh_token"]
        resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"]
        assert data["refresh_token"]

    async def test_refresh_invalid_token(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "invalid-token"})
        assert resp.status_code == 401

    async def test_logout(self, client: AsyncClient, auth_header: dict[str, str]) -> None:
        resp = await client.post("/api/v1/auth/logout", headers=auth_header)
        assert resp.status_code == 200

    async def test_list_api_keys(self, client: AsyncClient, auth_header: dict[str, str]) -> None:
        resp = await client.get("/api/v1/auth/api-keys", headers=auth_header)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_create_api_key(self, client: AsyncClient, auth_header: dict[str, str]) -> None:
        resp = await client.post("/api/v1/auth/api-keys", json={"name": "test-key"}, headers=auth_header)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "test-key"
        assert data["key"] is not None
        assert data["key"].startswith("mcs_")

    async def test_revoke_api_key(self, client: AsyncClient, auth_header: dict[str, str]) -> None:
        resp = await client.post("/api/v1/auth/api-keys", json={"name": "test-key"}, headers=auth_header)
        assert resp.status_code == 201
        key_id = resp.json()["api_key_id"]
        resp = await client.delete(f"/api/v1/auth/api-keys/{key_id}", headers=auth_header)
        assert resp.status_code == 204


class TestServers:
    async def test_list_servers_empty(self, client: AsyncClient, auth_header: dict[str, str]) -> None:
        resp = await client.get("/api/v1/servers", headers=auth_header)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_create_server(self, client: AsyncClient, auth_header: dict[str, str]) -> None:
        payload = {
            "name": "My Server",
            "minecraft_version": "1.21",
            "min_memory_mb": 1024,
            "max_memory_mb": 2048,
            "port": 25565,
            "gamemode": "survival",
            "difficulty": "easy",
        }
        resp = await client.post("/api/v1/servers", json=payload, headers=auth_header)
        assert resp.status_code == 201
        data = resp.json()
        assert "server_id" in data

    async def test_create_and_get_server(self, client: AsyncClient, auth_header: dict[str, str]) -> None:
        payload = {
            "name": "Get Test",
            "minecraft_version": "1.21",
            "min_memory_mb": 1024,
            "max_memory_mb": 2048,
            "port": 25565,
            "gamemode": "survival",
            "difficulty": "easy",
        }
        create_resp = await client.post("/api/v1/servers", json=payload, headers=auth_header)
        server_id = create_resp.json()["server_id"]
        get_resp = await client.get(f"/api/v1/servers/{server_id}", headers=auth_header)
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["name"] == "Get Test"
        assert data["status"] == "created"

    async def test_update_server(self, client: AsyncClient, auth_header: dict[str, str], created_server: dict) -> None:
        server_id = created_server["server_id"]
        resp = await client.patch(
            f"/api/v1/servers/{server_id}",
            json={"properties": {"motd": "Updated MOTD"}, "min_memory_mb": 2048},
            headers=auth_header,
        )
        assert resp.status_code == 200
        get_resp = await client.get(f"/api/v1/servers/{server_id}", headers=auth_header)
        data = get_resp.json()
        assert data["min_memory_mb"] == 2048

    async def test_start_server(self, client: AsyncClient, auth_header: dict[str, str], created_server: dict) -> None:
        from app.modules.server.infrastructure.providers.base import (
            DeploymentResult,
            ServerRuntimeStatus,
        )
        mock_provider = AsyncMock()
        mock_provider.provider_type = "local"
        mock_provider.start.return_value = DeploymentResult(
            status=ServerRuntimeStatus.RUNNING,
            address="127.0.0.1",
            port=25565,
            pid=12345,
            metadata={"session_name": "mcs-test-start"},
        )

        server_id = created_server["server_id"]
        with patch("app.modules.server.application.commands.start_server.provider_factory.get", return_value=mock_provider):
            resp = await client.post(f"/api/v1/servers/{server_id}/start", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data["server_id"] == server_id

    async def test_stop_server(self, client: AsyncClient, auth_header: dict[str, str], created_server: dict) -> None:
        from app.core.persistence.db import database
        from sqlalchemy import text
        from app.modules.server.infrastructure.providers.base import (
            DeploymentResult,
            ServerRuntimeStatus,
        )

        server_id = created_server["server_id"]
        mock_provider = AsyncMock()
        mock_provider.provider_type = "local"
        mock_provider.start.return_value = DeploymentResult(
            status=ServerRuntimeStatus.RUNNING,
            address="127.0.0.1",
            port=25565,
            pid=12345,
            metadata={"session_name": "mcs-test-stop"},
        )
        mock_provider.status.return_value = ServerRuntimeStatus.STOPPED
        mock_provider.stop.return_value = None

        with patch("app.modules.server.application.commands.start_server.provider_factory.get", return_value=mock_provider):
            await client.post(f"/api/v1/servers/{server_id}/start", headers=auth_header)
        async with database._session_factory() as session:
            await session.execute(text("UPDATE servers SET status = 'running' WHERE id = :id"), {"id": server_id})
            await session.commit()
        with patch("app.modules.server.application.commands.stop_server.provider_factory.get", return_value=mock_provider):
            resp = await client.post(f"/api/v1/servers/{server_id}/stop", json={"reason": "test"}, headers=auth_header)
        assert resp.status_code == 200

    async def test_delete_server(self, client: AsyncClient, auth_header: dict[str, str], created_server: dict) -> None:
        server_id = created_server["server_id"]
        resp = await client.delete(f"/api/v1/servers/{server_id}", headers=auth_header)
        assert resp.status_code == 204

    async def test_unauthorized_access(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/servers")
        assert resp.status_code == 401

    async def test_console_endpoint(self, client: AsyncClient, auth_header: dict[str, str], created_server: dict) -> None:
        server_id = created_server["server_id"]
        resp = await client.get(f"/api/v1/servers/{server_id}/console?tail=50", headers=auth_header)
        assert resp.status_code == 404


class TestBackups:
    async def test_list_backups_empty(self, client: AsyncClient, auth_header: dict[str, str]) -> None:
        resp = await client.get("/api/v1/backups", headers=auth_header)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_create_backup(self, client: AsyncClient, auth_header: dict[str, str], created_server: dict) -> None:
        server_id = created_server["server_id"]
        resp = await client.post(
            "/api/v1/backups",
            json={"server_id": server_id, "backup_type": "full"},
            headers=auth_header,
        )
        assert resp.status_code == 201
        assert "backup_id" in resp.json()

    async def test_create_and_get_backup(self, client: AsyncClient, auth_header: dict[str, str], created_server: dict) -> None:
        server_id = created_server["server_id"]
        create_resp = await client.post(
            "/api/v1/backups",
            json={"server_id": server_id, "backup_type": "full"},
            headers=auth_header,
        )
        backup_id = create_resp.json()["backup_id"]
        get_resp = await client.get(f"/api/v1/backups/{backup_id}", headers=auth_header)
        assert get_resp.status_code == 200

    async def test_verify_backup(self, client: AsyncClient, auth_header: dict[str, str], created_server: dict) -> None:
        server_id = created_server["server_id"]
        create_resp = await client.post(
            "/api/v1/backups",
            json={"server_id": server_id, "backup_type": "full"},
            headers=auth_header,
        )
        backup_id = create_resp.json()["backup_id"]
        verify_resp = await client.post(f"/api/v1/backups/{backup_id}/verify", headers=auth_header)
        assert verify_resp.status_code == 200
        data = verify_resp.json()
        assert "valid" in data

    async def test_delete_backup(self, client: AsyncClient, auth_header: dict[str, str], created_server: dict) -> None:
        server_id = created_server["server_id"]
        create_resp = await client.post(
            "/api/v1/backups",
            json={"server_id": server_id, "backup_type": "full"},
            headers=auth_header,
        )
        backup_id = create_resp.json()["backup_id"]
        resp = await client.delete(f"/api/v1/backups/{backup_id}", headers=auth_header)
        assert resp.status_code == 204

    @pytest.mark.parametrize("invalid_type", ["incremental", "world_only", "FULL", ""])
    async def test_create_backup_rejects_invalid_type_with_422(
        self,
        client: AsyncClient,
        auth_header: dict[str, str],
        created_server: dict,
        invalid_type: str,
    ) -> None:
        server_id = created_server["server_id"]
        resp = await client.post(
            "/api/v1/backups",
            json={"server_id": server_id, "backup_type": invalid_type},
            headers=auth_header,
        )
        assert resp.status_code == 422

    @pytest.mark.parametrize("valid_type", ["full", "world", "plugins"])
    async def test_create_backup_accepts_valid_types(
        self,
        client: AsyncClient,
        auth_header: dict[str, str],
        created_server: dict,
        valid_type: str,
    ) -> None:
        server_id = created_server["server_id"]
        resp = await client.post(
            "/api/v1/backups",
            json={"server_id": server_id, "backup_type": valid_type},
            headers=auth_header,
        )
        assert resp.status_code == 201


class TestPlugins:
    async def test_list_plugins_empty(self, client: AsyncClient, auth_header: dict[str, str], created_server: dict) -> None:
        server_id = created_server["server_id"]
        resp = await client.get(f"/api/v1/servers/{server_id}/plugins", headers=auth_header)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_install_plugin(self, client: AsyncClient, auth_header: dict[str, str], created_server: dict) -> None:
        server_id = created_server["server_id"]
        payload = {"server_id": server_id, "name": "EssentialsX", "version": "2.21.0"}
        resp = await client.post(
            f"/api/v1/servers/{server_id}/plugins",
            json=payload,
            headers=auth_header,
        )
        assert resp.status_code == 201
        assert "plugin_id" in resp.json()

    async def test_get_plugin(self, client: AsyncClient, auth_header: dict[str, str], created_server: dict) -> None:
        server_id = created_server["server_id"]
        install_resp = await client.post(
            f"/api/v1/servers/{server_id}/plugins",
            json={"server_id": server_id, "name": "WorldEdit", "version": "7.3.0"},
            headers=auth_header,
        )
        plugin_id = install_resp.json()["plugin_id"]
        resp = await client.get(f"/api/v1/servers/{server_id}/plugins/{plugin_id}", headers=auth_header)
        assert resp.status_code == 200
        assert resp.json()["name"] == "WorldEdit"

    async def test_enable_plugin(self, client: AsyncClient, auth_header: dict[str, str], created_server: dict) -> None:
        server_id = created_server["server_id"]
        install_resp = await client.post(
            f"/api/v1/servers/{server_id}/plugins",
            json={"server_id": server_id, "name": "LuckPerms", "version": "5.4.0"},
            headers=auth_header,
        )
        plugin_id = install_resp.json()["plugin_id"]
        resp = await client.post(
            f"/api/v1/servers/{server_id}/plugins/{plugin_id}/enable",
            headers=auth_header,
        )
        assert resp.status_code == 200

    async def test_disable_plugin(self, client: AsyncClient, auth_header: dict[str, str], created_server: dict) -> None:
        server_id = created_server["server_id"]
        install_resp = await client.post(
            f"/api/v1/servers/{server_id}/plugins",
            json={"server_id": server_id, "name": "Vault", "version": "1.7.3"},
            headers=auth_header,
        )
        plugin_id = install_resp.json()["plugin_id"]
        resp = await client.post(
            f"/api/v1/servers/{server_id}/plugins/{plugin_id}/disable",
            headers=auth_header,
        )
        assert resp.status_code == 200

    async def test_uninstall_plugin(self, client: AsyncClient, auth_header: dict[str, str], created_server: dict) -> None:
        server_id = created_server["server_id"]
        install_resp = await client.post(
            f"/api/v1/servers/{server_id}/plugins",
            json={"server_id": server_id, "name": "Dynmap", "version": "3.7.0"},
            headers=auth_header,
        )
        plugin_id = install_resp.json()["plugin_id"]
        resp = await client.delete(
            f"/api/v1/servers/{server_id}/plugins/{plugin_id}",
            headers=auth_header,
        )
        assert resp.status_code == 204


class TestUsers:
    async def test_list_users(self, client: AsyncClient, auth_header: dict[str, str], created_user: dict) -> None:
        resp = await client.get("/api/v1/users", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1

    async def test_create_user(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/users",
            json={"email": "new@test.com", "password": "password123", "display_name": "New User"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["email"] == "new@test.com"
        assert data["display_name"] == "New User"

    async def test_create_duplicate_user(self, client: AsyncClient, created_user: dict) -> None:
        resp = await client.post(
            "/api/v1/users",
            json={"email": "test@test.com", "password": "password123", "display_name": "Duplicate"},
        )
        assert resp.status_code == 409

    async def test_get_user(self, client: AsyncClient, auth_header: dict[str, str], created_user: dict) -> None:
        user_id = created_user["user_id"]
        resp = await client.get(f"/api/v1/users/{user_id}", headers=auth_header)
        assert resp.status_code == 200
        assert resp.json()["email"] == "test@test.com"

    async def test_update_user(self, client: AsyncClient, auth_header: dict[str, str], created_user: dict) -> None:
        user_id = created_user["user_id"]
        resp = await client.patch(
            f"/api/v1/users/{user_id}",
            json={"display_name": "Updated Name"},
            headers=auth_header,
        )
        assert resp.status_code == 200
        assert resp.json()["display_name"] == "Updated Name"

    async def test_delete_user(self, client: AsyncClient, auth_header: dict[str, str], created_user: dict) -> None:
        user_id = created_user["user_id"]
        resp = await client.delete(f"/api/v1/users/{user_id}", headers=auth_header)
        assert resp.status_code == 204


class TestMonitoring:
    async def test_get_metrics(self, client: AsyncClient, auth_header: dict[str, str], created_server: dict) -> None:
        server_id = created_server["server_id"]
        resp = await client.get(f"/api/v1/monitoring/metrics?server_id={server_id}", headers=auth_header)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_alerts(self, client: AsyncClient, auth_header: dict[str, str]) -> None:
        resp = await client.get("/api/v1/monitoring/alerts", headers=auth_header)
        assert resp.status_code == 200

    async def test_create_alert_rule(self, client: AsyncClient, auth_header: dict[str, str], created_server: dict) -> None:
        server_id = created_server["server_id"]
        resp = await client.post(
            "/api/v1/monitoring/alerts",
            json={
                "server_id": server_id,
                "metric_name": "tps",
                "condition": "gt",
                "threshold": 10.0,
                "severity": "warning",
            },
            headers=auth_header,
        )
        assert resp.status_code == 201


class TestSettings:
    async def test_get_settings(self, client: AsyncClient, auth_header: dict[str, str]) -> None:
        resp = await client.get("/api/v1/settings", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data["app_name"] == "mcs-manager"

    async def test_update_settings(self, client: AsyncClient, auth_header: dict[str, str]) -> None:
        resp = await client.patch("/api/v1/settings", headers=auth_header)
        assert resp.status_code == 200


class TestSchedules:
    async def test_list_schedules(self, client: AsyncClient, auth_header: dict[str, str]) -> None:
        resp = await client.get("/api/v1/schedules", headers=auth_header)
        assert resp.status_code == 200

    async def test_create_schedule(self, client: AsyncClient, auth_header: dict[str, str]) -> None:
        resp = await client.post("/api/v1/schedules", json={}, headers=auth_header)
        assert resp.status_code == 201

    async def test_delete_schedule(self, client: AsyncClient, auth_header: dict[str, str]) -> None:
        resp = await client.delete("/api/v1/schedules/sched-1", headers=auth_header)
        assert resp.status_code == 204


class TestEdgeCases:
    async def test_unauthorized_schedule_access(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/schedules")
        assert resp.status_code == 401

    async def test_send_command(self, client: AsyncClient, auth_header: dict[str, str], created_server: dict) -> None:
        server_id = created_server["server_id"]
        resp = await client.post(
            f"/api/v1/servers/{server_id}/command",
            json={"command": "say hello"},
            headers=auth_header,
        )
        assert resp.status_code == 400

    async def test_metrics_endpoint(self, client: AsyncClient) -> None:
        resp = await client.get("/metrics")
        assert resp.status_code in (200, 501)


class TestRuntimeOwnershipAPI:
    async def test_runtime_ownership_empty(self, client: AsyncClient, auth_header: dict[str, str]) -> None:
        with patch(
            "app.modules.server.application.runtime_ownership._find_all_tmux_sessions",
            return_value=[],
        ):
            with patch(
                "app.modules.server.application.runtime_ownership._find_all_java_pids",
                return_value=[],
            ):
                resp = await client.get("/api/v1/servers/runtime/ownership", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_orphans"] == 0
        assert len(data["active_servers"]) == 0

    async def test_runtime_ownership_with_orphan(self, client: AsyncClient, auth_header: dict[str, str]) -> None:
        with patch(
            "app.modules.server.application.runtime_ownership._find_all_tmux_sessions",
            return_value=[("mcs-orphan-x", 12345)],
        ):
            with patch(
                "app.modules.server.application.runtime_ownership._find_minecraft_child_pids",
                return_value=[],
            ):
                with patch(
                    "app.modules.server.application.runtime_ownership._find_all_java_pids",
                    return_value=[12345],
                ):
                    resp = await client.get("/api/v1/servers/runtime/ownership", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_orphans"] >= 1
        assert len(data["orphan_tmux"]) >= 1

    async def test_runtime_ownership_unauthorized(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/servers/runtime/ownership")
        assert resp.status_code == 401

    async def test_claim_localhost_unauthorized(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/servers/runtime/ownership/claim?server_id=s1")
        assert resp.status_code == 401

    async def test_validate_runtime_unauthorized(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/servers/s1/runtime/validate")
        assert resp.status_code == 401


class TestErrorHandling:
    async def test_unauthorized_access(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/servers/123")
        assert resp.status_code == 401

    async def test_health_returns_uptime(self, client: AsyncClient) -> None:
        resp = await client.get("/health")
        data = resp.json()
        assert data["uptime_seconds"] >= 0

    async def test_unauthorized_backup_access(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/backups")
        assert resp.status_code == 401

    async def test_expired_token_returns_401(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/servers", headers={"Authorization": "Bearer invalid.token.here"})
        assert resp.status_code == 401
