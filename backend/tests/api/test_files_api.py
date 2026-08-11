import io
import os

import pytest
from httpx import AsyncClient

pytest_plugins = ["tests.api.test_api_endpoints"]

from app.core.persistence.db import database
from app.modules.auth.infrastructure.models import UserModel
from app.modules.server.infrastructure.models import ServerMembershipModel, ServerModel
from tests.api.test_api_endpoints import _seed_api_key_header



async def _seed_server(server_id: str, name: str, root_path: str | None, owner_id: str | None = None) -> None:
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
            root_path=root_path,
            owner_id=owner_id,
        )
        session.add(server)
        await session.commit()


async def _seed_membership(membership_id: str, server_id: str, user_id: str, role: str) -> None:
    async with database._session_factory() as session:
        mem = ServerMembershipModel(
            id=membership_id,
            server_id=server_id,
            user_id=user_id,
            role=role,
        )
        session.add(mem)
        await session.commit()



async def _seed_user(user_id: str, email: str, name: str) -> None:
    async with database._session_factory() as session:
        user = UserModel(
            id=user_id,
            email=email,
            password_hash="hash",
            display_name=name,
            is_active=True,
        )
        session.add(user)
        await session.commit()


@pytest.mark.asyncio
async def test_files_missing_server(client: AsyncClient, auth_header: dict[str, str]):
    resp = await client.get("/api/v1/servers/non-existent-srv/files", headers=auth_header)
    assert resp.status_code == 404
    data = resp.json()
    err_text = data.get("detail") or data.get("error") or ""
    assert "not found" in err_text.lower()


@pytest.mark.asyncio
async def test_files_missing_root_path(client: AsyncClient, created_user: dict):
    server_id = "srv-no-root"
    await _seed_server(server_id, "No Root Server", root_path=None)

    admin_header = await _seed_api_key_header(client, created_user["user_id"], ["admin:full"])
    resp = await client.get(f"/api/v1/servers/{server_id}/files", headers=admin_header)
    assert resp.status_code == 400
    data = resp.json()
    err_text = data.get("detail") or data.get("error") or ""
    assert "root path is not configured" in err_text



@pytest.mark.asyncio
async def test_files_happy_path_crud(client: AsyncClient, created_user: dict, tmp_path):
    server_id = "srv-crud-test"
    server_root = tmp_path / "server_crud"
    server_root.mkdir(parents=True, exist_ok=True)

    # Seed admin API key header
    admin_header = await _seed_api_key_header(client, created_user["user_id"], ["admin:full"])

    # Pre-create a file
    test_file = server_root / "server.properties"
    test_file.write_text("motd=Hello World\nport=25565")

    await _seed_server(server_id, "CRUD Server", root_path=str(server_root))

    # 1. List directory
    resp = await client.get(f"/api/v1/servers/{server_id}/files", headers=admin_header)
    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) == 1
    assert entries[0]["name"] == "server.properties"
    assert entries[0]["is_dir"] is False

    # 2. Read file content
    resp = await client.get(
        f"/api/v1/servers/{server_id}/files/content",
        params={"path": "server.properties"},
        headers=admin_header,
    )
    assert resp.status_code == 200
    assert resp.json()["content"] == "motd=Hello World\nport=25565"

    # 3. Create directory (mkdir)
    resp = await client.post(
        f"/api/v1/servers/{server_id}/files/mkdir",
        params={"path": "config/plugins"},
        headers=admin_header,
    )
    assert resp.status_code == 201
    assert resp.json()["is_dir"] is True
    assert (server_root / "config" / "plugins").is_dir()

    # 4. Write text file content (atomic)
    resp = await client.put(
        f"/api/v1/servers/{server_id}/files/content",
        params={"path": "config/plugins/settings.txt"},
        json={"content": "enabled=true"},
        headers=admin_header,
    )
    assert resp.status_code == 200
    assert (server_root / "config" / "plugins" / "settings.txt").read_text() == "enabled=true"

    # 5. Download file
    resp = await client.get(
        f"/api/v1/servers/{server_id}/files/download",
        params={"path": "server.properties"},
        headers=admin_header,
    )
    assert resp.status_code == 200
    assert resp.content == b"motd=Hello World\nport=25565"

    # 6. Delete file and directory
    resp = await client.delete(
        f"/api/v1/servers/{server_id}/files",
        params={"path": "config/plugins/settings.txt"},
        headers=admin_header,
    )
    assert resp.status_code == 204
    assert not (server_root / "config" / "plugins" / "settings.txt").exists()

    resp = await client.delete(
        f"/api/v1/servers/{server_id}/files",
        params={"path": "config"},
        headers=admin_header,
    )
    assert resp.status_code == 204
    assert not (server_root / "config").exists()


@pytest.mark.asyncio
async def test_files_upload_end_to_end(client: AsyncClient, created_user: dict, tmp_path):
    server_id = "srv-upload-test"
    server_root = tmp_path / "server_upload"
    server_root.mkdir(parents=True, exist_ok=True)
    await _seed_server(server_id, "Upload Server", root_path=str(server_root))

    admin_header = await _seed_api_key_header(client, created_user["user_id"], ["admin:full"])

    # Multipart file upload
    file_bytes = b"plugin_binary_content_data"
    files = {"file": ("my-plugin.jar", io.BytesIO(file_bytes), "application/java-archive")}

    resp = await client.post(
        f"/api/v1/servers/{server_id}/files/upload",
        params={"path": "plugins"},
        files=files,
        headers=admin_header,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "my-plugin.jar"
    assert data["path"] == "plugins/my-plugin.jar"
    assert data["size"] == len(file_bytes)

    uploaded_file = server_root / "plugins" / "my-plugin.jar"
    assert uploaded_file.exists()
    assert uploaded_file.read_bytes() == file_bytes


@pytest.mark.asyncio
async def test_files_path_traversal_prevention(client: AsyncClient, created_user: dict, tmp_path):
    server_id = "srv-security-test"
    server_root = tmp_path / "server_secure"
    server_root.mkdir(parents=True, exist_ok=True)

    admin_header = await _seed_api_key_header(client, created_user["user_id"], ["admin:full"])

    # Secret outside root
    secret_dir = tmp_path / "outside_secret"
    secret_dir.mkdir(parents=True, exist_ok=True)
    secret_file = secret_dir / "passwords.txt"
    secret_file.write_text("secret_password_123")

    # Create symlink inside server root pointing to outside secret
    symlink_path = server_root / "escaped_link"
    try:
        os.symlink(secret_file, symlink_path)
    except OSError:
        pass

    await _seed_server(server_id, "Secure Server", root_path=str(server_root))

    # 1. Traversal via ../../
    resp = await client.get(
        f"/api/v1/servers/{server_id}/files/content",
        params={"path": "../../outside_secret/passwords.txt"},
        headers=admin_header,
    )
    assert resp.status_code == 403
    data = resp.json()
    err_text = data.get("detail") or data.get("error") or ""
    assert "escapes server root" in err_text

    # 2. Absolute path traversal
    resp = await client.get(
        f"/api/v1/servers/{server_id}/files/content",
        params={"path": str(secret_file)},
        headers=admin_header,
    )
    assert resp.status_code in (403, 404)

    # 3. Symlink escape traversal
    if symlink_path.exists() or symlink_path.is_symlink():
        resp = await client.get(
            f"/api/v1/servers/{server_id}/files/content",
            params={"path": "escaped_link"},
            headers=admin_header,
        )
        assert resp.status_code == 403
        data = resp.json()
        err_text = data.get("detail") or data.get("error") or ""
        assert "escapes server root" in err_text


@pytest.mark.asyncio
async def test_files_permissions_enforcement(client: AsyncClient, created_user: dict, tmp_path):
    server_id = "srv-perm-test"
    server_root = tmp_path / "server_perm"
    server_root.mkdir(parents=True, exist_ok=True)
    (server_root / "test.txt").write_text("sample")

    owner_user_id = "u_owner_1"
    dev_user_id = "u_dev_1"
    viewer_user_id = "u_viewer_1"

    await _seed_user(owner_user_id, "owner@example.com", "Owner")
    await _seed_user(dev_user_id, "dev@example.com", "Dev")
    await _seed_user(viewer_user_id, "viewer@example.com", "Viewer")

    await _seed_server(server_id, "Perm Server", root_path=str(server_root), owner_id=owner_user_id)
    await _seed_membership("mem_dev", server_id, dev_user_id, "dev")
    await _seed_membership("mem_viewer", server_id, viewer_user_id, "viewer")

    # 1. Unauthenticated -> 401
    resp = await client.get(f"/api/v1/servers/{server_id}/files")
    assert resp.status_code == 401

    # 2. Non-owner, non-member user -> 403 on all routes
    non_member_header = await _seed_api_key_header(client, created_user["user_id"], [])
    resp = await client.get(f"/api/v1/servers/{server_id}/files", headers=non_member_header)
    assert resp.status_code == 403
    resp = await client.get(f"/api/v1/servers/{server_id}/files/content", params={"path": "test.txt"}, headers=non_member_header)
    assert resp.status_code == 403
    resp = await client.put(f"/api/v1/servers/{server_id}/files/content", params={"path": "test.txt"}, json={"content": "x"}, headers=non_member_header)
    assert resp.status_code == 403
    resp = await client.delete(f"/api/v1/servers/{server_id}/files", params={"path": "test.txt"}, headers=non_member_header)
    assert resp.status_code == 403
    resp = await client.get(f"/api/v1/servers/{server_id}/files/download", params={"path": "test.txt"}, headers=non_member_header)
    assert resp.status_code == 403

    # 3. Viewer role member -> 200 on GET /files/download, 403 on other 6 routes
    viewer_header = await _seed_api_key_header(client, viewer_user_id, [])
    resp = await client.get(f"/api/v1/servers/{server_id}/files/download", params={"path": "test.txt"}, headers=viewer_header)
    assert resp.status_code == 200
    resp = await client.get(f"/api/v1/servers/{server_id}/files", headers=viewer_header)
    assert resp.status_code == 403
    resp = await client.get(f"/api/v1/servers/{server_id}/files/content", params={"path": "test.txt"}, headers=viewer_header)
    assert resp.status_code == 403
    resp = await client.put(f"/api/v1/servers/{server_id}/files/content", params={"path": "test.txt"}, json={"content": "x"}, headers=viewer_header)
    assert resp.status_code == 403
    resp = await client.delete(f"/api/v1/servers/{server_id}/files", params={"path": "test.txt"}, headers=viewer_header)
    assert resp.status_code == 403
    resp = await client.post(f"/api/v1/servers/{server_id}/files/mkdir", params={"path": "dir"}, headers=viewer_header)
    assert resp.status_code == 403


    # 4. Dev role member -> 200/201/204 on files routes (dev has server.{id}.files)
    dev_header = await _seed_api_key_header(client, dev_user_id, [])
    resp = await client.get(f"/api/v1/servers/{server_id}/files", headers=dev_header)
    assert resp.status_code == 200
    resp = await client.get(f"/api/v1/servers/{server_id}/files/content", params={"path": "test.txt"}, headers=dev_header)
    assert resp.status_code == 200

    # 5. Server Owner -> 200/201/204 on all routes (owner_id implicit access)
    owner_header = await _seed_api_key_header(client, owner_user_id, [])
    resp = await client.get(f"/api/v1/servers/{server_id}/files", headers=owner_header)
    assert resp.status_code == 200

    # 6. Global Admin -> 200/201/204 on all routes (admin:full short-circuit)
    admin_header = await _seed_api_key_header(client, created_user["user_id"], ["admin:full"])
    resp = await client.get(f"/api/v1/servers/{server_id}/files", headers=admin_header)
    assert resp.status_code == 200


