import io

import pytest
from httpx import AsyncClient

from tests.api.test_api_endpoints import _seed_api_key_header
from tests.api.test_files_api import _seed_server

pytest_plugins = ["tests.api.test_api_endpoints"]

PROTECTED_PATHS = [
    ".onx",
    ".ONX",
    ".onx.",
    ".onx ",
    ".onx/tests/t1/server.properties",
    ".onx-manager/server.json",
    ".Onx-Manager./server.json",
    ".mcsmanager/server.json",
    ".MCSMANAGER /server.json",
    "world/.onx/data.txt",
]


async def _setup(client: AsyncClient, created_user: dict, tmp_path, server_id: str):
    root = tmp_path / server_id
    root.mkdir(parents=True)
    (root / ".onx" / "tests" / "t1").mkdir(parents=True)
    (root / ".onx" / "tests" / "t1" / "server.properties").write_text("a=b")
    (root / ".onx-manager").mkdir()
    (root / ".onx-manager" / "server.json").write_text("{}")
    (root / ".mcsmanager").mkdir()
    (root / ".mcsmanager" / "server.json").write_text("{}")
    (root / "world" / ".onx").mkdir(parents=True)
    (root / "world" / ".onx" / "data.txt").write_text("x")
    (root / "ops.txt").write_text("ok")
    await _seed_server(server_id, server_id, root_path=str(root))
    header = await _seed_api_key_header(client, created_user["user_id"], ["admin:full"])
    return root, header


@pytest.mark.asyncio
@pytest.mark.parametrize("rel", PROTECTED_PATHS)
async def test_protected_folders_denied_for_every_operation(
    client: AsyncClient, created_user: dict, tmp_path, rel: str
):
    server_id = "srv-prot-ops"
    root = tmp_path / server_id
    if not root.exists():
        root, header = await _setup(client, created_user, tmp_path, server_id)
    else:
        header = await _seed_api_key_header(client, created_user["user_id"], ["admin:full"])
    base = f"/api/v1/servers/{server_id}/files"
    params = {"path": rel}

    responses = [
        await client.get(base, params=params, headers=header),
        await client.get(f"{base}/content", params=params, headers=header),
        await client.get(f"{base}/download", params=params, headers=header),
        await client.put(f"{base}/content", params=params, json={"content": "x"}, headers=header),
        await client.delete(base, params=params, headers=header),
        await client.post(f"{base}/mkdir", params=params, headers=header),
        await client.post(
            f"{base}/upload",
            params={"path": rel},
            files={"file": ("a.txt", io.BytesIO(b"x"))},
            headers=header,
        ),
    ]
    assert [r.status_code for r in responses] == [403] * len(responses)
    assert (root / ".onx" / "tests" / "t1" / "server.properties").read_text() == "a=b"
    assert (root / ".onx-manager" / "server.json").exists()
    assert (root / ".mcsmanager" / "server.json").exists()


@pytest.mark.asyncio
async def test_protected_folders_hidden_from_listing(
    client: AsyncClient, created_user: dict, tmp_path
):
    _, header = await _setup(client, created_user, tmp_path, "srv-prot-list")
    resp = await client.get("/api/v1/servers/srv-prot-list/files", headers=header)
    assert resp.status_code == 200
    assert [e["name"] for e in resp.json()] == ["world", "ops.txt"]


@pytest.mark.asyncio
@pytest.mark.parametrize("name", [".env", ".env.", ".env ", ".ENV", ".Env. ."])
async def test_env_variants_blocked(client: AsyncClient, created_user: dict, tmp_path, name: str):
    root, header = await _setup(client, created_user, tmp_path, "srv-prot-env")
    (root / ".env").write_text("SECRET=1")
    base = "/api/v1/servers/srv-prot-env/files"
    params = {"path": name}
    assert (await client.get(f"{base}/content", params=params, headers=header)).status_code == 403
    assert (await client.get(f"{base}/download", params=params, headers=header)).status_code == 403
    put = await client.put(f"{base}/content", params=params, json={"content": "x"}, headers=header)
    assert put.status_code == 403
    assert (await client.delete(base, params=params, headers=header)).status_code == 403
    assert (root / ".env").read_text() == "SECRET=1"


@pytest.mark.asyncio
async def test_listing_survives_dangling_symlink(
    client: AsyncClient, created_user: dict, tmp_path
):
    root, header = await _setup(client, created_user, tmp_path, "srv-dangling")
    (root / "broken").symlink_to(root / "does-not-exist")
    resp = await client.get("/api/v1/servers/srv-dangling/files", headers=header)
    assert resp.status_code == 200
    assert "broken" in [e["name"] for e in resp.json()]


@pytest.mark.asyncio
async def test_delete_symlink_removes_link_not_target(
    client: AsyncClient, created_user: dict, tmp_path
):
    root, header = await _setup(client, created_user, tmp_path, "srv-del-link")
    (root / "real").mkdir()
    (root / "real" / "keep.txt").write_text("keep")
    (root / "link").symlink_to(root / "real", target_is_directory=True)
    (root / "flink").symlink_to(root / "ops.txt")
    base = "/api/v1/servers/srv-del-link/files"
    assert (await client.delete(base, params={"path": "link"}, headers=header)).status_code == 204
    assert (await client.delete(base, params={"path": "flink"}, headers=header)).status_code == 204
    assert not (root / "link").is_symlink()
    assert not (root / "flink").is_symlink()
    assert (root / "real" / "keep.txt").read_text() == "keep"
    assert (root / "ops.txt").read_text() == "ok"


@pytest.mark.asyncio
async def test_delete_dangling_symlink_removes_link(
    client: AsyncClient, created_user: dict, tmp_path
):
    root, header = await _setup(client, created_user, tmp_path, "srv-del-dangling")
    (root / "broken").symlink_to(root / "nope")
    base = "/api/v1/servers/srv-del-dangling/files"
    resp = await client.delete(base, params={"path": "broken"}, headers=header)
    assert resp.status_code == 204
    assert not (root / "broken").is_symlink()


@pytest.mark.asyncio
async def test_delete_symlink_in_escaping_directory_denied(
    client: AsyncClient, created_user: dict, tmp_path
):
    root, header = await _setup(client, created_user, tmp_path, "srv-del-escape")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "victim.txt").write_text("v")
    (root / "esc").symlink_to(outside, target_is_directory=True)
    base = "/api/v1/servers/srv-del-escape/files"
    resp = await client.delete(base, params={"path": "esc/victim.txt"}, headers=header)
    assert resp.status_code == 403
    assert (outside / "victim.txt").exists()


@pytest.mark.asyncio
async def test_mkdir_on_existing_file_returns_409(
    client: AsyncClient, created_user: dict, tmp_path
):
    root, header = await _setup(client, created_user, tmp_path, "srv-mkdir-409")
    base = "/api/v1/servers/srv-mkdir-409/files/mkdir"
    resp = await client.post(base, params={"path": "ops.txt"}, headers=header)
    assert resp.status_code == 409
    resp = await client.post(base, params={"path": "ops.txt/sub"}, headers=header)
    assert resp.status_code == 409
    assert (root / "ops.txt").read_text() == "ok"
