import hashlib
from datetime import UTC
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.query_bus import QueryBus
from app.main import app
from app.registration import register_handlers


def _reset_rate_limits() -> None:
    from app.api.v1.middleware.rate_limit import InMemoryRateLimitStore

    stack = getattr(app, "middleware_stack", None)
    while stack is not None:
        if isinstance(stack, InMemoryRateLimitStore):
            stack._hits.clear()
        store = getattr(stack, "_store", None)
        if isinstance(store, InMemoryRateLimitStore):
            store._hits.clear()
        stack = getattr(stack, "app", None)


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
    from typing import Any

    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.core.persistence.base import Base
    from app.core.persistence.db import database

    _reset_rate_limits()

    db_file = tmp_path / "test_api.sqlite3"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_file.as_posix()}",
        echo=False,
        connect_args={"timeout": 30.0, "check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            pass
        finally:
            cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    database._engine = engine
    database._session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )

    async with database._session_factory() as sess:
        from app.modules.auth.infrastructure.models import SystemStateModel

        sess.add(SystemStateModel(id="default", initialized=True, access_mode="LOCAL"))
        await sess.commit()

    old_data_dir = os.environ.get("MCS_SERVERS_DATA_DIR")
    test_servers_dir = tmp_path / "test_servers"
    test_servers_dir.mkdir(parents=True, exist_ok=True)
    os.environ["MCS_SERVERS_DATA_DIR"] = str(test_servers_dir)

    try:
        transport = ASGITransport(app=app)
        with patch(
            "app.modules.server.application.services.jar_service.download_server_jar",
            AsyncMock(return_value="/tmp/mock-jar/server.jar"),
        ):
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ac
    finally:
        await engine.dispose()
        database._engine = None
        database._session_factory = None
        if db_file.exists():
            db_file.unlink()
        for extra in (tmp_path / f"{db_file.name}-wal", tmp_path / f"{db_file.name}-shm"):
            if extra.exists():
                extra.unlink()
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
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "test@test.com", "password": "password123"}
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture
def auth_header(auth_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_token}"}


async def _seed_api_key_header(
    client: AsyncClient,
    user_id: str,
    permissions: list[str],
) -> dict[str, str]:
    from app.core.persistence.db import database
    from app.core.security import generate_api_key, hash_api_key
    from app.modules.auth.infrastructure.models import ApiKeyModel

    raw_key = generate_api_key()
    async with database._session_factory() as session:
        session.add(
            ApiKeyModel(
                id="test-" + hashlib.sha1(raw_key.encode()).hexdigest()[:16],
                user_id=user_id,
                name="test-seeded-key",
                prefix=raw_key[:8],
                key_hash=hash_api_key(raw_key),
                permissions=",".join(sorted(permissions)),
                expires_at=None,
                is_revoked=False,
            )
        )
        await session.commit()
    return {"Authorization": f"Bearer {raw_key}"}


async def _seed_plugin(
    server_id: str,
    name: str,
    *,
    version: str = "1.0.0",
    source: str = "detected",
    filename: str | None = None,
    status: str = "installed",
) -> str:
    import uuid
    from datetime import datetime

    from app.core.persistence.db import database
    from app.modules.plugin.infrastructure.models import PluginModel

    plugin_id = "plg-" + uuid.uuid4().hex[:12]
    now = datetime.now(UTC)
    async with database._session_factory() as session:
        session.add(
            PluginModel(
                id=plugin_id,
                server_id=server_id,
                name=name,
                version=version,
                description="",
                author="",
                website="",
                dependencies="",
                status=status,
                source=source,
                filename=filename,
                installed_at=now,
                updated_at=now,
            )
        )
        await session.commit()
    return plugin_id


@pytest.fixture
async def privileged_header(client: AsyncClient, created_user: dict) -> dict[str, str]:
    return await _seed_api_key_header(
        client,
        created_user["user_id"],
        [
            "server:create",
            "server:delete",
            "server:stop",
            "server:start",
            "server:write",
            "backup:create",
            "backup:read",
            "backup:delete",
            "backup:restore",
            "plugin:manage",
            "user:write",
            "user:delete",
        ],
    )


@pytest.fixture
async def admin_header(client: AsyncClient, created_user: dict) -> dict[str, str]:
    return await _seed_api_key_header(client, created_user["user_id"], ["admin:full"])


@pytest.fixture
async def created_server(client: AsyncClient, privileged_header: dict[str, str]) -> dict:
    payload = {
        "name": "API Test Server",
        "minecraft_version": "1.21",
        "min_memory_mb": 1024,
        "max_memory_mb": 2048,
        "port": 25565,
        "gamemode": "survival",
        "difficulty": "easy",
    }
    resp = await client.post("/api/v1/servers", json=payload, headers=privileged_header)
    assert resp.status_code == 201
    data = resp.json()

    import os

    from app.core.persistence.db import database
    from app.modules.server.infrastructure.repository import SQLServerRepository
    from app.modules.shared.value_objects import ServerId

    server_id = data["server_id"]
    async with database.session_factory() as session:
        server = await SQLServerRepository(session).get(ServerId(server_id))
        if server and server.deployment and server.deployment.root_path:
            server_dir = server.deployment.root_path
            os.makedirs(server_dir, exist_ok=True)
            with open(os.path.join(server_dir, "server.jar"), "wb") as f:
                f.write(b"PK\x03\x04fake-jar")

    return data


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
        resp = await client.post(
            "/api/v1/auth/login", json={"email": "new@test.com", "password": "password123"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"]
        assert data["token_type"] == "bearer"

    async def test_login_invalid_credentials(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/auth/login", json={"email": "nonexistent@test.com", "password": "wrong"}
        )
        assert resp.status_code == 401

    async def test_login_missing_fields(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/auth/login", json={"email": "", "password": ""})
        assert resp.status_code == 422

    async def test_login_invalid_email_format(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/auth/login", json={"email": "not-an-email", "password": "password"}
        )
        assert resp.status_code == 422

    async def test_refresh_token(self, client: AsyncClient, created_user: dict) -> None:
        login_resp = await client.post(
            "/api/v1/auth/login", json={"email": "test@test.com", "password": "password123"}
        )
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

    async def test_logout(self, client: AsyncClient, created_user: dict) -> None:
        login_resp = await client.post(
            "/api/v1/auth/login", json={"email": "test@test.com", "password": "password123"}
        )
        assert login_resp.status_code == 200
        login_data = login_resp.json()
        headers = {"Authorization": f"Bearer {login_data['access_token']}"}
        resp = await client.post(
            "/api/v1/auth/logout",
            headers=headers,
            json={"refresh_token": login_data["refresh_token"]},
        )
        assert resp.status_code == 200

    async def test_logout_requires_refresh_token(
        self, client: AsyncClient, auth_header: dict[str, str]
    ) -> None:
        resp = await client.post("/api/v1/auth/logout", headers=auth_header)
        assert resp.status_code == 422

    async def test_logout_revokes_refresh_token(
        self, client: AsyncClient, created_user: dict
    ) -> None:
        login_resp = await client.post(
            "/api/v1/auth/login", json={"email": "test@test.com", "password": "password123"}
        )
        assert login_resp.status_code == 200
        login_data = login_resp.json()
        headers = {"Authorization": f"Bearer {login_data['access_token']}"}
        resp = await client.post(
            "/api/v1/auth/logout",
            headers=headers,
            json={"refresh_token": login_data["refresh_token"]},
        )
        assert resp.status_code == 200
        refresh_resp = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": login_data["refresh_token"]}
        )
        assert refresh_resp.status_code == 401

    async def test_list_api_keys(self, client: AsyncClient, auth_header: dict[str, str]) -> None:
        resp = await client.get("/api/v1/auth/api-keys", headers=auth_header)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_create_api_key(
        self, client: AsyncClient, privileged_header: dict[str, str]
    ) -> None:
        resp = await client.post(
            "/api/v1/auth/api-keys", json={"name": "test-key"}, headers=privileged_header
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "test-key"
        assert data["key"] is not None
        assert data["key"].startswith("mcs_")

    async def test_revoke_api_key(
        self, client: AsyncClient, privileged_header: dict[str, str]
    ) -> None:
        resp = await client.post(
            "/api/v1/auth/api-keys", json={"name": "test-key"}, headers=privileged_header
        )
        assert resp.status_code == 201
        key_id = resp.json()["api_key_id"]
        resp = await client.delete(f"/api/v1/auth/api-keys/{key_id}", headers=privileged_header)
        assert resp.status_code == 204


class TestServers:
    async def test_list_servers_empty(
        self, client: AsyncClient, auth_header: dict[str, str]
    ) -> None:
        resp = await client.get("/api/v1/servers", headers=auth_header)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_create_server(
        self, client: AsyncClient, privileged_header: dict[str, str]
    ) -> None:
        payload = {
            "name": "My Server",
            "minecraft_version": "1.21",
            "min_memory_mb": 1024,
            "max_memory_mb": 2048,
            "port": 25565,
            "gamemode": "survival",
            "difficulty": "easy",
        }
        resp = await client.post("/api/v1/servers", json=payload, headers=privileged_header)
        assert resp.status_code == 201
        data = resp.json()
        assert "server_id" in data

    async def test_create_and_get_server(
        self, client: AsyncClient, privileged_header: dict[str, str]
    ) -> None:
        payload = {
            "name": "Get Test",
            "minecraft_version": "1.21",
            "min_memory_mb": 1024,
            "max_memory_mb": 2048,
            "port": 25565,
            "gamemode": "survival",
            "difficulty": "easy",
        }
        create_resp = await client.post("/api/v1/servers", json=payload, headers=privileged_header)
        server_id = create_resp.json()["server_id"]
        get_resp = await client.get(f"/api/v1/servers/{server_id}", headers=privileged_header)
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["name"] == "Get Test"
        assert data["status"] == "created"

    async def test_update_server(
        self, client: AsyncClient, privileged_header: dict[str, str], created_server: dict
    ) -> None:
        server_id = created_server["server_id"]
        resp = await client.patch(
            f"/api/v1/servers/{server_id}",
            json={
                "name": "Renamed Via API",
                "properties": {"motd": "Updated MOTD"},
                "min_memory_mb": 2048,
            },
            headers=privileged_header,
        )
        assert resp.status_code == 200
        get_resp = await client.get(f"/api/v1/servers/{server_id}", headers=privileged_header)
        data = get_resp.json()
        assert data["name"] == "Renamed Via API"
        assert data["min_memory_mb"] == 2048

    async def test_start_server(
        self, client: AsyncClient, privileged_header: dict[str, str], created_server: dict
    ) -> None:
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
            metadata={"session_name": "onx-test-start"},
        )

        server_id = created_server["server_id"]
        with (
            patch(
                "app.modules.server.application.commands.start_server.provider_factory.get",
                return_value=mock_provider,
            ),
            patch(
                "app.modules.server.application.commands.start_server._port_is_listening",
                return_value=False,
            ),
        ):
            resp = await client.post(
                f"/api/v1/servers/{server_id}/start", headers=privileged_header
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["server_id"] == server_id

    async def test_stop_server(
        self,
        client: AsyncClient,
        auth_header: dict[str, str],
        privileged_header: dict[str, str],
        created_server: dict,
    ) -> None:
        from sqlalchemy import text

        from app.core.persistence.db import database
        from app.modules.server.infrastructure.providers.base import (
            DeploymentResult,
            ServerRuntimeStatus,
        )

        server_id = created_server["server_id"]
        mock_provider = AsyncMock()
        mock_provider.provider_type = "local"
        mock_provider.get_address = AsyncMock(return_value="127.0.0.1")
        mock_provider.start.return_value = DeploymentResult(
            status=ServerRuntimeStatus.RUNNING,
            address="127.0.0.1",
            port=25565,
            pid=12345,
            metadata={"session_name": "onx-test-stop"},
        )
        mock_provider.status.return_value = ServerRuntimeStatus.STOPPED
        mock_provider.stop.return_value = None

        with (
            patch(
                "app.modules.server.application.commands.start_server.provider_factory.get",
                return_value=mock_provider,
            ),
            patch(
                "app.modules.server.application.commands.start_server._port_is_listening",
                return_value=False,
            ),
        ):
            await client.post(f"/api/v1/servers/{server_id}/start", headers=privileged_header)
        async with database._session_factory() as session:
            await session.execute(
                text("UPDATE servers SET status = 'running' WHERE id = :id"), {"id": server_id}
            )
            await session.commit()
        with (
            patch(
                "app.modules.server.application.commands.stop_server.provider_factory.get",
                return_value=mock_provider,
            ),
            patch(
                "app.modules.server.application.commands.stop_server._port_is_listening",
                return_value=False,
            ),
            patch(
                "app.modules.server.application.commands.stop_server._wait_for_port_free",
                return_value=True,
            ),
        ):
            resp = await client.post(
                f"/api/v1/servers/{server_id}/stop",
                json={"reason": "test"},
                headers=privileged_header,
            )
        assert resp.status_code == 200

    async def test_delete_server(
        self,
        client: AsyncClient,
        privileged_header: dict[str, str],
        created_server: dict,
    ) -> None:
        server_id = created_server["server_id"]
        with patch(
            "app.modules.server.application.commands.delete_server._port_is_listening",
            return_value=False,
        ):
            resp = await client.delete(f"/api/v1/servers/{server_id}", headers=privileged_header)
        assert resp.status_code == 204

    async def test_unauthorized_access(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/servers")
        assert resp.status_code == 401

    async def test_retry_provisioning_rejected_when_not_failed(
        self,
        client: AsyncClient,
        privileged_header: dict[str, str],
        created_server: dict,
    ) -> None:
        server_id = created_server["server_id"]
        # created_server is in status 'created', not 'provisioning_failed'
        resp = await client.post(
            f"/api/v1/servers/{server_id}/retry-provisioning",
            headers=privileged_header,
        )
        assert resp.status_code == 400
        data = resp.json()
        error_msg = data.get("error") or str(data.get("detail", ""))
        assert "expected 'provisioning_failed'" in error_msg.lower()
        assert data.get("error_code") == "INVALID_STATUS"

    async def test_retry_provisioning_succeeds_when_failed(
        self,
        client: AsyncClient,
        privileged_header: dict[str, str],
        created_server: dict,
    ) -> None:
        from sqlalchemy import update

        from app.core.persistence.db import database
        from app.modules.server.infrastructure.models import ServerModel

        server_id = created_server["server_id"]
        # Update server to forge server in PROVISIONING_FAILED status
        async with database.session_factory() as session:
            await session.execute(
                update(ServerModel)
                .where(ServerModel.id == server_id)
                .values(
                    server_type="forge",
                    status="provisioning_failed",
                    provisioning_error="Connection timed out",
                    provisioning_retryable=False,
                )
            )
            await session.commit()

        with patch(
            "app.modules.server.application.services.forge_provisioner.provision_forge_server"
        ) as mock_prov:
            resp = await client.post(
                f"/api/v1/servers/{server_id}/retry-provisioning",
                headers=privileged_header,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["server_id"] == server_id
            assert data["status"] == "provisioning"
            mock_prov.assert_called_once()


class TestBackups:
    async def test_list_backups_empty(
        self, client: AsyncClient, auth_header: dict[str, str]
    ) -> None:
        resp = await client.get("/api/v1/backups", headers=auth_header)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_create_backup(
        self, client: AsyncClient, privileged_header: dict[str, str], created_server: dict
    ) -> None:
        server_id = created_server["server_id"]
        resp = await client.post(
            "/api/v1/backups",
            json={"server_id": server_id, "backup_type": "full"},
            headers=privileged_header,
        )
        assert resp.status_code == 201
        assert "backup_id" in resp.json()

    async def test_create_and_get_backup(
        self, client: AsyncClient, privileged_header: dict[str, str], created_server: dict
    ) -> None:
        server_id = created_server["server_id"]
        create_resp = await client.post(
            "/api/v1/backups",
            json={"server_id": server_id, "backup_type": "full"},
            headers=privileged_header,
        )
        backup_id = create_resp.json()["backup_id"]
        get_resp = await client.get(f"/api/v1/backups/{backup_id}", headers=privileged_header)
        assert get_resp.status_code == 200

    async def test_verify_backup(
        self, client: AsyncClient, privileged_header: dict[str, str], created_server: dict
    ) -> None:
        server_id = created_server["server_id"]
        create_resp = await client.post(
            "/api/v1/backups",
            json={"server_id": server_id, "backup_type": "full"},
            headers=privileged_header,
        )
        backup_id = create_resp.json()["backup_id"]
        verify_resp = await client.post(
            f"/api/v1/backups/{backup_id}/verify", headers=privileged_header
        )
        assert verify_resp.status_code == 200
        data = verify_resp.json()
        assert "valid" in data

    async def test_delete_backup(
        self,
        client: AsyncClient,
        privileged_header: dict[str, str],
        created_server: dict,
    ) -> None:
        server_id = created_server["server_id"]
        create_resp = await client.post(
            "/api/v1/backups",
            json={"server_id": server_id, "backup_type": "full"},
            headers=privileged_header,
        )
        backup_id = create_resp.json()["backup_id"]
        resp = await client.delete(f"/api/v1/backups/{backup_id}", headers=privileged_header)
        assert resp.status_code == 204

    @pytest.mark.parametrize("invalid_type", ["incremental", "world_only", "FULL", ""])
    async def test_create_backup_rejects_invalid_type_with_422(
        self,
        client: AsyncClient,
        privileged_header: dict[str, str],
        created_server: dict,
        invalid_type: str,
    ) -> None:
        server_id = created_server["server_id"]
        resp = await client.post(
            "/api/v1/backups",
            json={"server_id": server_id, "backup_type": invalid_type},
            headers=privileged_header,
        )
        assert resp.status_code == 422

    @pytest.mark.parametrize(
        "valid_type",
        ["full", "worlds", "world", "nether", "end", "plugins", "config"],
    )
    async def test_create_backup_accepts_valid_types(
        self,
        client: AsyncClient,
        privileged_header: dict[str, str],
        created_server: dict,
        valid_type: str,
    ) -> None:
        server_id = created_server["server_id"]
        resp = await client.post(
            "/api/v1/backups",
            json={"server_id": server_id, "backup_type": valid_type},
            headers=privileged_header,
        )
        assert resp.status_code == 201


class TestPlugins:
    async def test_list_plugins_empty(
        self, client: AsyncClient, auth_header: dict[str, str], created_server: dict
    ) -> None:
        server_id = created_server["server_id"]
        resp = await client.get(f"/api/v1/servers/{server_id}/plugins", headers=auth_header)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_plugins_returns_seeded_detected_row(
        self, client: AsyncClient, privileged_header: dict[str, str], created_server: dict
    ) -> None:
        import os

        from app.core.persistence.db import database
        from app.modules.server.infrastructure.repository import SQLServerRepository
        from app.modules.shared.value_objects import ServerId

        server_id = created_server["server_id"]
        async with database.session_factory() as session:
            server = await SQLServerRepository(session).get(ServerId(server_id))
            server_dir = server.deployment.root_path

        plugins_dir = os.path.join(server_dir, "plugins")
        os.makedirs(plugins_dir, exist_ok=True)
        jar_path = os.path.join(plugins_dir, "EssentialsX.jar")
        with open(jar_path, "wb") as f:
            f.write(b"PK\x03\x04fake-jar")

        resp = await client.get(f"/api/v1/servers/{server_id}/plugins", headers=privileged_header)
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["name"] == "EssentialsX"
        assert body[0]["filename"] == "EssentialsX.jar"
        assert body[0]["source"] == "detected"
        assert body[0]["pending_deletion"] is False

    async def test_get_plugin(
        self, client: AsyncClient, privileged_header: dict[str, str], created_server: dict
    ) -> None:
        server_id = created_server["server_id"]
        plugin_id = await _seed_plugin(server_id, "WorldEdit")
        resp = await client.get(
            f"/api/v1/servers/{server_id}/plugins/{plugin_id}", headers=privileged_header
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "WorldEdit"

    async def test_enable_plugin(
        self, client: AsyncClient, privileged_header: dict[str, str], created_server: dict
    ) -> None:
        server_id = created_server["server_id"]
        plugin_id = await _seed_plugin(server_id, "LuckPerms")
        resp = await client.post(
            f"/api/v1/servers/{server_id}/plugins/{plugin_id}/enable",
            headers=privileged_header,
        )
        assert resp.status_code == 200

    async def test_disable_plugin(
        self, client: AsyncClient, privileged_header: dict[str, str], created_server: dict
    ) -> None:
        server_id = created_server["server_id"]
        plugin_id = await _seed_plugin(server_id, "Vault")
        resp = await client.post(
            f"/api/v1/servers/{server_id}/plugins/{plugin_id}/disable",
            headers=privileged_header,
        )
        assert resp.status_code == 200

    async def test_uninstall_plugin_marks_pending_and_hides_from_list(
        self,
        client: AsyncClient,
        privileged_header: dict[str, str],
        created_server: dict,
    ) -> None:
        server_id = created_server["server_id"]
        plugin_id = await _seed_plugin(server_id, "Dynmap", filename="Dynmap.jar")
        resp = await client.delete(
            f"/api/v1/servers/{server_id}/plugins/{plugin_id}",
            headers=privileged_header,
        )
        assert resp.status_code == 204
        list_resp = await client.get(
            f"/api/v1/servers/{server_id}/plugins", headers=privileged_header
        )
        assert list_resp.status_code == 200
        assert list_resp.json() == []


class TestPluginMarketplace:
    async def test_marketplace_search(
        self, client: AsyncClient, privileged_header: dict[str, str], created_server: dict
    ) -> None:
        server_id = created_server["server_id"]
        resp = await client.get(
            f"/api/v1/servers/{server_id}/plugins/marketplace/search",
            params={"query": "essentials"},
            headers=privileged_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "items" in data
        assert "total_hits" in data
        assert "offset" in data
        assert "limit" in data

    async def test_global_marketplace_search(
        self, client: AsyncClient, privileged_header: dict[str, str]
    ) -> None:
        from app.modules.plugin.infrastructure.providers.base import (
            PluginSearchPage,
            PluginSearchResult,
        )

        class _FakeProvider:
            async def search(
                self,
                _query: str,
                **kwargs: object,  # noqa: ARG002
            ) -> PluginSearchPage:
                return PluginSearchPage(
                    items=[
                        PluginSearchResult(
                            project_id="proj1",
                            slug="essentialsx",
                            title="EssentialsX",
                            description="Essential commands",
                            author="Essentials",
                            project_types=["plugin"],
                            downloads=1000,
                            follows=10,
                            icon_url="",
                            latest_version_id="v1",
                            categories=[],
                            loaders=[],
                            client_side=None,
                            server_side=None,
                            date_modified="",
                            color=None,
                        )
                    ],
                    total_hits=1,
                    offset=0,
                    limit=20,
                )

        with patch(
            "app.api.v1.routers.marketplace.build_plugin_catalog_provider",
            return_value=_FakeProvider(),
        ):
            resp = await client.get(
                "/api/v1/marketplace/search",
                params={"query": "essentials"},
                headers=privileged_header,
            )
        assert resp.status_code == 200
        assert resp.json() == {
            "items": [
                {
                    "project_id": "proj1",
                    "slug": "essentialsx",
                    "title": "EssentialsX",
                    "description": "Essential commands",
                    "author": "Essentials",
                    "project_types": ["plugin"],
                    "downloads": 1000,
                    "follows": 10,
                    "icon_url": "",
                    "latest_version_id": "v1",
                    "categories": [],
                    "loaders": [],
                    "client_side": None,
                    "server_side": None,
                    "date_modified": "",
                    "color": None,
                }
            ],
            "total_hits": 1,
            "offset": 0,
            "limit": 20,
        }

    async def test_global_marketplace_search_project_type(
        self, client: AsyncClient, privileged_header: dict[str, str]
    ) -> None:
        from app.modules.plugin.infrastructure.providers.base import PluginSearchPage

        passed_kwargs = {}

        class _FakeProvider:
            async def search(self, _query: str, **kwargs: object) -> PluginSearchPage:
                nonlocal passed_kwargs
                passed_kwargs = kwargs
                return PluginSearchPage(items=[], total_hits=0, offset=0, limit=20)

        with patch(
            "app.api.v1.routers.marketplace.build_plugin_catalog_provider",
            return_value=_FakeProvider(),
        ):
            resp = await client.get(
                "/api/v1/marketplace/search",
                params={"query": "sodium", "project_type": "mod"},
                headers=privileged_header,
            )
        assert resp.status_code == 200
        assert passed_kwargs.get("project_type") == "mod"

    async def test_global_marketplace_search_loader(
        self, client: AsyncClient, privileged_header: dict[str, str]
    ) -> None:
        from app.modules.plugin.infrastructure.providers.base import PluginSearchPage

        passed_kwargs = {}

        class _FakeProvider:
            async def search(self, _query: str, **kwargs: object) -> PluginSearchPage:
                nonlocal passed_kwargs
                passed_kwargs = kwargs
                return PluginSearchPage(items=[], total_hits=0, offset=0, limit=20)

        with patch(
            "app.api.v1.routers.marketplace.build_plugin_catalog_provider",
            return_value=_FakeProvider(),
        ):
            resp = await client.get(
                "/api/v1/marketplace/search",
                params={"query": "sodium", "loader": "neoforge"},
                headers=privileged_header,
            )
        assert resp.status_code == 200
        assert passed_kwargs.get("loader") == "neoforge"
        # omitted loader must pass through as None, not ""
        passed_kwargs.clear()
        with patch(
            "app.api.v1.routers.marketplace.build_plugin_catalog_provider",
            return_value=_FakeProvider(),
        ):
            resp = await client.get(
                "/api/v1/marketplace/search",
                params={"query": "sodium"},
                headers=privileged_header,
            )
        assert resp.status_code == 200
        assert passed_kwargs.get("loader") is None

    async def test_get_marketplace_project(
        self, client: AsyncClient, privileged_header: dict[str, str]
    ) -> None:
        from app.modules.plugin.infrastructure.providers.base import PluginProject

        class _FakeProvider:
            name = "modrinth"

            async def get_project(self, project_id: str) -> PluginProject:
                return PluginProject(
                    project_id=project_id,
                    slug="essentialsx",
                    title="EssentialsX",
                    description="Essential commands",
                    body="# EssentialsX\nFull description here",
                    author="Essentials Team",
                    project_types=["plugin"],
                    loaders=["paper", "spigot"],
                    game_versions=["1.21"],
                    downloads=1000,
                    follows=50,
                    icon_url="https://example.com/icon.png",
                    wiki_url="https://example.com/wiki",
                    source_url="https://example.com/source",
                )

        with patch(
            "app.api.v1.routers.marketplace.build_plugin_catalog_provider",
            return_value=_FakeProvider(),
        ):
            resp = await client.get(
                "/api/v1/marketplace/projects/essentialsx",
                headers=privileged_header,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == "essentialsx"
        assert data["title"] == "EssentialsX"
        assert data["body"] == "# EssentialsX\nFull description here"
        assert data["wiki_url"] == "https://example.com/wiki"

    async def test_get_marketplace_project_requires_permission(
        self, client: AsyncClient, auth_header: dict[str, str]
    ) -> None:
        resp = await client.get(
            "/api/v1/marketplace/projects/essentialsx",
            headers=auth_header,
        )
        assert resp.status_code == 403

    async def test_global_marketplace_search_requires_permission(
        self, client: AsyncClient, auth_header: dict[str, str]
    ) -> None:
        resp = await client.get(
            "/api/v1/marketplace/search",
            headers=auth_header,
        )
        assert resp.status_code == 403

    async def test_marketplace_search_requires_permission(
        self, client: AsyncClient, auth_header: dict[str, str], created_server: dict
    ) -> None:
        server_id = created_server["server_id"]
        resp = await client.get(
            f"/api/v1/servers/{server_id}/plugins/marketplace/search",
            headers=auth_header,
        )
        assert resp.status_code == 403

    async def test_install_from_marketplace_requires_permission(
        self, client: AsyncClient, auth_header: dict[str, str], created_server: dict
    ) -> None:
        server_id = created_server["server_id"]
        resp = await client.post(
            f"/api/v1/servers/{server_id}/plugins/marketplace/install",
            json={"project_id": "essentialsx"},
            headers=auth_header,
        )
        assert resp.status_code == 403

    async def test_marketplace_versions_returns_files(
        self, client: AsyncClient, privileged_header: dict[str, str], created_server: dict
    ) -> None:
        from app.modules.plugin.infrastructure.providers.base import (
            PluginFile,
            PluginVersionInfo,
            PluginVersionsPage,
        )

        class _FakeProvider:
            name = "modrinth"

            async def get_project_versions(
                self,
                _project_id: str,
                **kwargs: object,  # noqa: ARG002
            ) -> PluginVersionsPage:
                return PluginVersionsPage(
                    items=[
                        PluginVersionInfo(
                            version_id="v1",
                            project_id="proj1",
                            name="Build 1",
                            version_number="1.0.0",
                            game_versions=["1.21"],
                            loaders=["paper"],
                            files=[
                                PluginFile(
                                    url="https://example.com/plug.jar",
                                    filename="plug.jar",
                                    size_bytes=10,
                                    sha1="a" * 40,
                                    primary=True,
                                )
                            ],
                            dependencies=["dep"],
                            date_published="2024-01-01T00:00:00Z",
                        )
                    ],
                    total=1,
                )

        server_id = created_server["server_id"]
        with patch(
            "app.api.v1.routers.plugins.build_plugin_catalog_provider",
            return_value=_FakeProvider(),
        ):
            resp = await client.get(
                f"/api/v1/servers/{server_id}/plugins/marketplace/projects/proj1/versions",
                headers=privileged_header,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["versions"]) == 1
        assert data["total"] == 1
        version = data["versions"][0]
        assert version["version_id"] == "v1"
        assert version["files"] == [
            {
                "url": "https://example.com/plug.jar",
                "filename": "plug.jar",
                "size_bytes": 10,
                "sha1": "a" * 40,
                "sha512": "",
                "primary": True,
            }
        ]

    async def test_marketplace_project_versions_returns_selected_null(
        self, client: AsyncClient, privileged_header: dict[str, str]
    ) -> None:
        """§3.5 / §4.6: server-independent versions endpoint returns 200 with selected=null."""
        from app.modules.plugin.infrastructure.providers.base import (
            PluginFile,
            PluginVersionInfo,
            PluginVersionsPage,
        )

        class _FakeProvider:
            name = "modrinth"

            async def get_project_versions(
                self,
                _project_id: str,
                **kwargs: object,  # noqa: ARG002
            ) -> PluginVersionsPage:
                return PluginVersionsPage(
                    items=[
                        PluginVersionInfo(
                            version_id="v1",
                            project_id="proj1",
                            name="Build 1",
                            version_number="1.0.0",
                            game_versions=["1.21"],
                            loaders=["paper"],
                            files=[
                                PluginFile(
                                    url="https://example.com/plug.jar",
                                    filename="plug.jar",
                                    size_bytes=42,
                                    sha1="a" * 40,
                                    primary=True,
                                )
                            ],
                            dependencies=[],
                            date_published="2024-06-01T00:00:00Z",
                        )
                    ],
                    total=1,
                )

        with patch(
            "app.api.v1.routers.marketplace.build_plugin_catalog_provider",
            return_value=_FakeProvider(),
        ):
            resp = await client.get(
                "/api/v1/marketplace/projects/proj1/versions",
                headers=privileged_header,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == "proj1"
        assert len(data["versions"]) == 1
        assert data["total"] == 1
        assert data["versions"][0]["version_id"] == "v1"
        assert data["selected"] is None
        assert data["notice"] == ""
        assert data["notice_kind"] == ""

    async def test_marketplace_project_versions_requires_permission(
        self, client: AsyncClient, auth_header: dict[str, str]
    ) -> None:
        """§3.5 / §4.6: versions endpoint enforces plugin:manage permission."""
        resp = await client.get(
            "/api/v1/marketplace/projects/proj1/versions",
            headers=auth_header,
        )
        assert resp.status_code == 403

    async def test_marketplace_project_versions_accepts_limit_offset(
        self, client: AsyncClient, privileged_header: dict[str, str]
    ) -> None:
        """Decision 6: versions endpoint threads real limit/offset server-side."""
        from app.modules.plugin.infrastructure.providers.base import (
            PluginVersionInfo,
            PluginVersionsPage,
        )

        class _FakeProvider:
            name = "modrinth"

            async def get_project_versions(
                self, _project_id: str, **kwargs: object
            ) -> PluginVersionsPage:
                limit_val = kwargs.get("limit")
                offset_val = kwargs.get("offset", 0)
                items = [
                    PluginVersionInfo(
                        version_id=f"v{i}",
                        project_id="proj1",
                        name=f"Build {i}",
                        version_number=f"{i}.0.0",
                        game_versions=["1.21"],
                        loaders=["paper"],
                        date_published="2024-06-01T00:00:00Z",
                    )
                    for i in range(3)
                ]
                if limit_val is not None:
                    items = items[offset_val : offset_val + limit_val]
                return PluginVersionsPage(items=items, total=3)

        with patch(
            "app.api.v1.routers.marketplace.build_plugin_catalog_provider",
            return_value=_FakeProvider(),
        ):
            resp = await client.get(
                "/api/v1/marketplace/projects/proj1/versions",
                params={"limit": 2, "offset": 1},
                headers=privileged_header,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert [v["version_id"] for v in data["versions"]] == ["v1", "v2"]
        assert data["total"] == 3

    async def test_marketplace_project_null_wiki_url(
        self, client: AsyncClient, privileged_header: dict[str, str]
    ) -> None:
        """§3.1 / §4.6: project with null wiki_url does NOT 500 (closes RP-13)."""
        from app.modules.plugin.infrastructure.providers.base import PluginProject

        class _FakeProvider:
            name = "modrinth"

            async def get_project(self, project_id: str) -> PluginProject:
                return PluginProject(
                    project_id=project_id,
                    slug="veinminer",
                    title="VeinMiner",
                    description="Mine entire veins",
                    body="# VeinMiner",
                    author="Someone",
                    project_types=["plugin"],
                    loaders=["paper"],
                    game_versions=["1.21"],
                    downloads=500,
                    follows=10,
                    icon_url="https://example.com/icon.png",
                    wiki_url=None,
                    source_url=None,
                )

        with patch(
            "app.api.v1.routers.marketplace.build_plugin_catalog_provider",
            return_value=_FakeProvider(),
        ):
            resp = await client.get(
                "/api/v1/marketplace/projects/veinminer",
                headers=privileged_header,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == "veinminer"
        assert data["wiki_url"] is None
        assert data["source_url"] is None

    async def test_marketplace_project_client_server_side_parsed(
        self, client: AsyncClient, privileged_header: dict[str, str]
    ) -> None:
        """§3.4 / §4.6: client_side/server_side fields are passed through."""
        from app.modules.plugin.infrastructure.providers.base import PluginProject

        class _FakeProvider:
            name = "modrinth"

            async def get_project(self, project_id: str) -> PluginProject:
                return PluginProject(
                    project_id=project_id,
                    slug="essentialsx",
                    title="EssentialsX",
                    description="Essential commands",
                    body="# EssentialsX",
                    author="Essentials Team",
                    project_types=["plugin"],
                    loaders=["paper"],
                    game_versions=["1.21"],
                    downloads=1000,
                    follows=50,
                    icon_url="https://example.com/icon.png",
                    wiki_url="https://example.com/wiki",
                    source_url="https://example.com/source",
                    client_side="optional",
                    server_side="required",
                )

        with patch(
            "app.api.v1.routers.marketplace.build_plugin_catalog_provider",
            return_value=_FakeProvider(),
        ):
            resp = await client.get(
                "/api/v1/marketplace/projects/essentialsx",
                headers=privileged_header,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["client_side"] == "optional"
        assert data["server_side"] == "required"


class TestUsers:
    async def test_list_users(
        self, client: AsyncClient, auth_header: dict[str, str], created_user: dict
    ) -> None:
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

    async def test_get_user(
        self, client: AsyncClient, auth_header: dict[str, str], created_user: dict
    ) -> None:
        user_id = created_user["user_id"]
        resp = await client.get(f"/api/v1/users/{user_id}", headers=auth_header)
        assert resp.status_code == 200
        assert resp.json()["email"] == "test@test.com"

    async def test_update_user(
        self,
        client: AsyncClient,
        privileged_header: dict[str, str],
        created_user: dict,
    ) -> None:
        user_id = created_user["user_id"]
        resp = await client.patch(
            f"/api/v1/users/{user_id}",
            json={"display_name": "Updated Name"},
            headers=privileged_header,
        )
        assert resp.status_code == 200
        assert resp.json()["display_name"] == "Updated Name"

    async def test_delete_user(
        self,
        client: AsyncClient,
        privileged_header: dict[str, str],
        created_user: dict,
    ) -> None:
        user_id = created_user["user_id"]
        resp = await client.delete(f"/api/v1/users/{user_id}", headers=privileged_header)
        assert resp.status_code == 204


class TestMonitoring:
    async def test_get_metrics(
        self, client: AsyncClient, auth_header: dict[str, str], created_server: dict
    ) -> None:
        server_id = created_server["server_id"]
        resp = await client.get(
            f"/api/v1/monitoring/metrics?server_id={server_id}", headers=auth_header
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_get_metrics_with_nullable_tps(
        self, client: AsyncClient, auth_header: dict[str, str], created_server: dict
    ) -> None:
        from app.core.persistence.db import database
        from app.modules.monitoring.domain.aggregate import MetricPoint
        from app.modules.monitoring.infrastructure.repository import SQLMetricRepository
        from app.modules.shared.value_objects import ServerId

        server_id = created_server["server_id"]
        async with database.session_factory() as session:
            repo = SQLMetricRepository(session)
            await repo.record(
                ServerId(server_id),
                MetricPoint(tps=None, players=0, ram_used_mb=256, cpu_percent=5),
            )
            await session.commit()

        resp = await client.get(
            f"/api/v1/monitoring/metrics?server_id={server_id}&limit=5", headers=auth_header
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["tps"] is None

    async def test_list_alerts(self, client: AsyncClient, auth_header: dict[str, str]) -> None:
        resp = await client.get("/api/v1/monitoring/alerts", headers=auth_header)
        assert resp.status_code == 200

    async def test_create_alert_rule_unauthorized(
        self, client: AsyncClient, created_server: dict
    ) -> None:
        from app.core.persistence.db import database
        from app.modules.auth.infrastructure.models import UserModel

        async with database._session_factory() as session:
            session.add(
                UserModel(
                    id="u_outsider_alerts",
                    email="outsider-alerts@test.com",
                    password_hash="hash",
                    display_name="Outsider",
                    is_active=True,
                )
            )
            await session.commit()
        outsider_header = await _seed_api_key_header(client, "u_outsider_alerts", [])

        server_id = created_server["server_id"]
        resp = await client.post(
            f"/api/v1/monitoring/alerts/{server_id}",
            json={
                "metric_name": "tps",
                "condition": "gt",
                "threshold": 10.0,
                "severity": "warning",
            },
            headers=outsider_header,
        )
        assert resp.status_code == 403

    async def test_create_alert_rule_authorized(
        self, client: AsyncClient, admin_header: dict[str, str], created_server: dict
    ) -> None:
        server_id = created_server["server_id"]
        resp = await client.post(
            f"/api/v1/monitoring/alerts/{server_id}",
            json={
                "metric_name": "tps",
                "condition": "gt",
                "threshold": 10.0,
                "severity": "warning",
            },
            headers=admin_header,
        )
        assert resp.status_code == 201

    async def test_delete_alert_rule(
        self, client: AsyncClient, auth_header: dict[str, str], admin_header: dict[str, str]
    ) -> None:
        resp = await client.delete("/api/v1/monitoring/alerts/rule-1", headers=auth_header)
        assert resp.status_code == 403

        resp = await client.delete("/api/v1/monitoring/alerts/rule-1", headers=admin_header)
        assert resp.status_code == 204


class TestSettings:
    async def test_get_settings(self, client: AsyncClient, admin_header: dict[str, str]) -> None:
        resp = await client.get("/api/v1/settings", headers=admin_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data["app_name"] == "onx-manager"
        assert "requires_restart" in data

    async def test_update_settings(self, client: AsyncClient, admin_header: dict[str, str]) -> None:
        resp = await client.patch(
            "/api/v1/settings", json={"rate_limit_per_minute": 100}, headers=admin_header
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["settings"]["rate_limit_per_minute"] == 100


class TestSchedules:
    async def test_list_schedules(self, client: AsyncClient, auth_header: dict[str, str]) -> None:
        resp = await client.get("/api/v1/schedules", headers=auth_header)
        assert resp.status_code == 200

    async def test_create_schedule_unauthorized(
        self, client: AsyncClient, auth_header: dict[str, str]
    ) -> None:
        resp = await client.post("/api/v1/schedules", json={}, headers=auth_header)
        assert resp.status_code == 403

    async def test_create_schedule_authorized(
        self, client: AsyncClient, admin_header: dict[str, str]
    ) -> None:
        resp = await client.post("/api/v1/schedules", json={}, headers=admin_header)
        assert resp.status_code == 201

    async def test_delete_schedule_unauthorized(
        self, client: AsyncClient, auth_header: dict[str, str]
    ) -> None:
        resp = await client.delete("/api/v1/schedules/sched-1", headers=auth_header)
        assert resp.status_code == 403

    async def test_delete_schedule_authorized(
        self, client: AsyncClient, admin_header: dict[str, str]
    ) -> None:
        resp = await client.delete("/api/v1/schedules/sched-1", headers=admin_header)
        assert resp.status_code == 204

    async def test_schedules_full_crud_and_persistence(
        self, client: AsyncClient, admin_header: dict[str, str], auth_header: dict[str, str]
    ) -> None:
        """ISS-034: Create a schedule, verify in list, delete, and verify gone."""
        list_resp = await client.get("/api/v1/schedules", headers=auth_header)
        assert list_resp.status_code == 200
        initial_count = len(list_resp.json())

        create_payload = {
            "name": "daily-world-backup",
            "cron_expression": "0 2 * * *",
            "task_name": "backup",
            "params": {"backup_type": "full"},
            "enabled": True,
        }
        create_resp = await client.post(
            "/api/v1/schedules", json=create_payload, headers=admin_header
        )
        assert create_resp.status_code == 201
        created = create_resp.json()
        assert created["success"] is True
        sched_id = created["schedule_id"]
        assert sched_id is not None
        assert created["name"] == "daily-world-backup"
        assert created["cron_expression"] == "0 2 * * *"
        assert created["params"] == {"backup_type": "full"}

        dup_resp = await client.post(
            "/api/v1/schedules", json=create_payload, headers=admin_header
        )
        assert dup_resp.status_code == 400
        assert "already exists" in dup_resp.json()["detail"]

        list_after = await client.get("/api/v1/schedules", headers=auth_header)
        assert list_after.status_code == 200
        jobs = list_after.json()
        assert len(jobs) == initial_count + 1
        matched = next((j for j in jobs if j["id"] == sched_id), None)
        assert matched is not None
        assert matched["name"] == "daily-world-backup"
        assert matched["cron_expression"] == "0 2 * * *"
        assert matched["task_name"] == "backup"
        assert matched["params"] == {"backup_type": "full"}
        assert matched["enabled"] is True

        del_resp = await client.delete(f"/api/v1/schedules/{sched_id}", headers=admin_header)
        assert del_resp.status_code == 204

        list_final = await client.get("/api/v1/schedules", headers=auth_header)
        assert list_final.status_code == 200
        final_jobs = list_final.json()
        assert len(final_jobs) == initial_count
        assert not any(j["id"] == sched_id for j in final_jobs)


class TestHealthEvaluatePermissions:
    async def test_evaluate_health_unauthorized(
        self, client: AsyncClient, created_server: dict
    ) -> None:
        from app.core.persistence.db import database
        from app.modules.auth.infrastructure.models import UserModel

        async with database._session_factory() as session:
            session.add(
                UserModel(
                    id="u_outsider_health",
                    email="outsider-health@test.com",
                    password_hash="hash",
                    display_name="Outsider",
                    is_active=True,
                )
            )
            await session.commit()
        outsider_header = await _seed_api_key_header(client, "u_outsider_health", [])

        server_id = created_server["server_id"]
        resp = await client.post(f"/api/v1/health/evaluate/{server_id}", headers=outsider_header)
        assert resp.status_code == 403

    async def test_evaluate_health_authorized(
        self, client: AsyncClient, admin_header: dict[str, str], created_server: dict
    ) -> None:
        server_id = created_server["server_id"]
        resp = await client.post(f"/api/v1/health/evaluate/{server_id}", headers=admin_header)
        assert resp.status_code == 200


class TestEdgeCases:
    async def test_unauthorized_schedule_access(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/schedules")
        assert resp.status_code == 401

    async def test_send_command(
        self, client: AsyncClient, admin_header: dict[str, str], created_server: dict
    ) -> None:
        server_id = created_server["server_id"]
        resp = await client.post(
            f"/api/v1/servers/{server_id}/command",
            json={"command": "say hello"},
            headers=admin_header,
        )
        assert resp.status_code == 404

    async def test_metrics_endpoint(self, client: AsyncClient) -> None:
        resp = await client.get("/metrics")
        assert resp.status_code in (200, 501)


class TestRuntimeOwnershipAPI:
    async def test_runtime_ownership_empty(
        self, client: AsyncClient, auth_header: dict[str, str]
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
            resp = await client.get("/api/v1/servers/runtime/ownership", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_orphans"] == 0
        assert len(data["active_servers"]) == 0

    async def test_runtime_ownership_with_orphan(
        self, client: AsyncClient, auth_header: dict[str, str]
    ) -> None:
        with (
            patch(
                "app.modules.server.application.runtime_ownership._find_all_tmux_sessions",
                return_value=[("onx-orphan-x", 12345)],
            ),
            patch(
                "app.modules.server.application.runtime_ownership._find_minecraft_child_pids",
                return_value=[],
            ),
            patch(
                "app.modules.server.application.runtime_ownership._find_all_java_pids",
                return_value=[12345],
            ),
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
        resp = await client.get(
            "/api/v1/servers", headers={"Authorization": "Bearer invalid.token.here"}
        )
        assert resp.status_code == 401


class TestAuthorizationEnforcement:
    async def test_delete_server_without_permission_denied(
        self, client: AsyncClient, auth_header: dict[str, str], created_server: dict
    ) -> None:
        server_id = created_server["server_id"]
        resp = await client.delete(f"/api/v1/servers/{server_id}", headers=auth_header)
        assert resp.status_code == 403
        assert resp.json()["error_code"] == "PERMISSION_DENIED"

    async def test_delete_server_admin_allowed(
        self, client: AsyncClient, admin_header: dict[str, str], created_server: dict
    ) -> None:
        server_id = created_server["server_id"]
        with patch(
            "app.modules.server.application.commands.delete_server._port_is_listening",
            return_value=False,
        ):
            resp = await client.delete(f"/api/v1/servers/{server_id}", headers=admin_header)
        assert resp.status_code == 204

    async def test_stop_server_without_permission_denied(
        self, client: AsyncClient, created_server: dict
    ) -> None:
        from app.core.persistence.db import database
        from app.modules.auth.infrastructure.models import UserModel

        async with database._session_factory() as session:
            session.add(
                UserModel(
                    id="u_outsider_stop",
                    email="outsider-stop@test.com",
                    password_hash="hash",
                    display_name="Outsider",
                    is_active=True,
                )
            )
            await session.commit()
        outsider_header = await _seed_api_key_header(client, "u_outsider_stop", [])

        server_id = created_server["server_id"]
        resp = await client.post(
            f"/api/v1/servers/{server_id}/stop", json={"reason": "test"}, headers=outsider_header
        )
        assert resp.status_code == 403
        err_text = resp.json().get("detail") or resp.json().get("error") or ""
        assert "permission" in err_text.lower()

    async def test_reconcile_without_permission_denied(
        self, client: AsyncClient, auth_header: dict[str, str]
    ) -> None:
        resp = await client.post("/api/v1/servers/reconcile", json={}, headers=auth_header)
        assert resp.status_code == 403
        assert resp.json()["error_code"] == "PERMISSION_DENIED"

    async def test_delete_backup_without_permission_denied(
        self,
        client: AsyncClient,
        auth_header: dict[str, str],
        privileged_header: dict[str, str],
        created_server: dict,
    ) -> None:
        server_id = created_server["server_id"]
        # setup with privileges: create the backup
        create_resp = await client.post(
            "/api/v1/backups",
            json={"server_id": server_id, "backup_type": "full"},
            headers=privileged_header,
        )
        backup_id = create_resp.json()["backup_id"]
        # attempt with zero perms: delete must be denied
        resp = await client.delete(f"/api/v1/backups/{backup_id}", headers=auth_header)
        assert resp.status_code == 403
        assert resp.json()["error_code"] == "PERMISSION_DENIED"

    async def test_delete_backup_admin_allowed(
        self, client: AsyncClient, admin_header: dict[str, str], created_server: dict
    ) -> None:
        server_id = created_server["server_id"]
        create_resp = await client.post(
            "/api/v1/backups",
            json={"server_id": server_id, "backup_type": "full"},
            headers=admin_header,
        )
        backup_id = create_resp.json()["backup_id"]
        resp = await client.delete(f"/api/v1/backups/{backup_id}", headers=admin_header)
        assert resp.status_code == 204

    async def test_restore_backup_without_permission_denied(
        self,
        client: AsyncClient,
        auth_header: dict[str, str],
        privileged_header: dict[str, str],
        created_server: dict,
    ) -> None:
        server_id = created_server["server_id"]
        # setup with privileges: create the backup
        create_resp = await client.post(
            "/api/v1/backups",
            json={"server_id": server_id, "backup_type": "full"},
            headers=privileged_header,
        )
        backup_id = create_resp.json()["backup_id"]
        # attempt with zero perms: restore must be denied
        resp = await client.post(f"/api/v1/backups/{backup_id}/restore", headers=auth_header)
        assert resp.status_code == 403
        assert resp.json()["error_code"] == "PERMISSION_DENIED"

    async def test_update_user_without_permission_denied(
        self, client: AsyncClient, auth_header: dict[str, str], created_user: dict
    ) -> None:
        user_id = created_user["user_id"]
        resp = await client.patch(
            f"/api/v1/users/{user_id}",
            json={"display_name": "Hacker"},
            headers=auth_header,
        )
        assert resp.status_code == 403
        assert resp.json()["error_code"] == "PERMISSION_DENIED"

    async def test_delete_user_without_permission_denied(
        self, client: AsyncClient, auth_header: dict[str, str], created_user: dict
    ) -> None:
        user_id = created_user["user_id"]
        resp = await client.delete(f"/api/v1/users/{user_id}", headers=auth_header)
        assert resp.status_code == 403
        assert resp.json()["error_code"] == "PERMISSION_DENIED"

    async def test_create_api_key_without_permission_denied(
        self, client: AsyncClient, auth_header: dict[str, str]
    ) -> None:
        resp = await client.post(
            "/api/v1/auth/api-keys",
            json={"name": "test-key"},
            headers=auth_header,
        )
        assert resp.status_code == 403
        assert resp.json()["error_code"] == "PERMISSION_DENIED"

    async def test_create_api_key_admin_allowed(
        self, client: AsyncClient, admin_header: dict[str, str]
    ) -> None:
        resp = await client.post(
            "/api/v1/auth/api-keys",
            json={"name": "test-key"},
            headers=admin_header,
        )
        assert resp.status_code == 201

    async def test_uninstall_plugin_without_permission_denied(
        self,
        client: AsyncClient,
        privileged_header: dict[str, str],
        auth_header: dict[str, str],
        created_server: dict,
    ) -> None:
        server_id = created_server["server_id"]
        plugin_id = await _seed_plugin(server_id, "Dynmap")
        resp = await client.delete(
            f"/api/v1/servers/{server_id}/plugins/{plugin_id}",
            headers=auth_header,
        )
        assert resp.status_code == 403
        assert resp.json()["error_code"] == "PERMISSION_DENIED"

    async def test_enable_plugin_without_permission_denied(
        self,
        client: AsyncClient,
        privileged_header: dict[str, str],
        auth_header: dict[str, str],
        created_server: dict,
    ) -> None:
        server_id = created_server["server_id"]
        plugin_id = await _seed_plugin(server_id, "LuckPerms")
        resp = await client.post(
            f"/api/v1/servers/{server_id}/plugins/{plugin_id}/enable",
            headers=auth_header,
        )
        assert resp.status_code == 403
        assert resp.json()["error_code"] == "PERMISSION_DENIED"

    async def test_disable_plugin_without_permission_denied(
        self,
        client: AsyncClient,
        privileged_header: dict[str, str],
        auth_header: dict[str, str],
        created_server: dict,
    ) -> None:
        server_id = created_server["server_id"]
        plugin_id = await _seed_plugin(server_id, "Vault")
        resp = await client.post(
            f"/api/v1/servers/{server_id}/plugins/{plugin_id}/disable",
            headers=auth_header,
        )
        assert resp.status_code == 403
        assert resp.json()["error_code"] == "PERMISSION_DENIED"

    async def test_uninstall_plugin_admin_allowed(
        self, client: AsyncClient, admin_header: dict[str, str], created_server: dict
    ) -> None:
        server_id = created_server["server_id"]
        plugin_id = await _seed_plugin(server_id, "Dynmap")
        resp = await client.delete(
            f"/api/v1/servers/{server_id}/plugins/{plugin_id}",
            headers=admin_header,
        )
        assert resp.status_code == 204
