import io
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.modules.server.application.services.import_service import (
    _safe_extract_zip,
    get_effective_server_dir,
)
from tests.api.test_api_endpoints import _seed_admin_api_key_header

pytest_plugins = ["tests.api.test_api_endpoints"]


def _build_zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Unit tests for _safe_extract_zip and get_effective_server_dir
# ---------------------------------------------------------------------------


def test_safe_extract_zip_normal(tmp_path: Path) -> None:
    zip_bytes = _build_zip_bytes({
        "server.properties": b"server-port=25565\n",
        "nested/config.yml": b"key: value\n",
    })
    zip_file = tmp_path / "test.zip"
    zip_file.write_bytes(zip_bytes)

    target_dir = tmp_path / "extracted"
    target_dir.mkdir()
    _safe_extract_zip(zip_file, target_dir)

    assert (target_dir / "server.properties").read_bytes() == b"server-port=25565\n"
    assert (target_dir / "nested" / "config.yml").read_bytes() == b"key: value\n"


def test_safe_extract_zip_traversal_relative(tmp_path: Path) -> None:
    # Create zip with ../evil.txt entry
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.txt", b"evil")
    zip_file = tmp_path / "evil.zip"
    zip_file.write_bytes(buf.getvalue())

    target_dir = tmp_path / "extracted"
    target_dir.mkdir()

    with pytest.raises(ValueError, match="Path traversal detected"):
        _safe_extract_zip(zip_file, target_dir)

    assert not (tmp_path / "evil.txt").exists()


def test_safe_extract_zip_traversal_absolute(tmp_path: Path) -> None:
    # Create zip with /etc/evil.txt entry
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("/etc/evil.txt", b"evil")
    zip_file = tmp_path / "evil_abs.zip"
    zip_file.write_bytes(buf.getvalue())

    target_dir = tmp_path / "extracted"
    target_dir.mkdir()

    with pytest.raises(ValueError, match="Path traversal detected"):
        _safe_extract_zip(zip_file, target_dir)


def test_get_effective_server_dir_flat(tmp_path: Path) -> None:
    base = tmp_path / "extracted_flat"
    base.mkdir()
    (base / "server.jar").touch()
    (base / "server.properties").touch()
    assert get_effective_server_dir(base) == base


def test_get_effective_server_dir_nested(tmp_path: Path) -> None:
    base = tmp_path / "extracted_nested"
    base.mkdir()
    inner = base / "MyServer"
    inner.mkdir()
    (inner / "server.jar").touch()
    assert get_effective_server_dir(base) == inner


def test_get_effective_server_dir_nested_with_mac_meta(tmp_path: Path) -> None:
    base = tmp_path / "extracted_mac"
    base.mkdir()
    inner = base / "MyServer"
    inner.mkdir()
    (inner / "server.jar").touch()
    macosx = base / "__MACOSX"
    macosx.mkdir()
    (base / ".DS_Store").touch()
    assert get_effective_server_dir(base) == inner


# ---------------------------------------------------------------------------
# API Integration tests for POST /api/v1/servers/import/upload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_rejects_non_zip(client: AsyncClient) -> None:
    headers = await _seed_admin_api_key_header(client, permissions=["server:write"])
    files = {"file": ("server.tar.gz", b"fake tar content", "application/gzip")}
    resp = await client.post("/api/v1/servers/import/upload", files=files, headers=headers)
    assert resp.status_code == 400
    assert "Only .zip archives are supported" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_upload_rejects_corrupted_zip(client: AsyncClient) -> None:
    headers = await _seed_admin_api_key_header(client, permissions=["server:write"])
    files = {"file": ("server.zip", b"not a valid zip binary", "application/zip")}
    resp = await client.post("/api/v1/servers/import/upload", files=files, headers=headers)
    assert resp.status_code == 400
    assert "Corrupted or invalid zip file" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_upload_exceeds_size_limit(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = await _seed_admin_api_key_header(client, permissions=["server:write"])
    monkeypatch.setenv("MCS_IMPORT_MAX_ZIP_SIZE_MB", "1")

    # 1MB limit, upload 2MB payload
    big_payload = b"x" * (2 * 1024 * 1024)
    files = {"file": ("big_server.zip", big_payload, "application/zip")}
    resp = await client.post("/api/v1/servers/import/upload", files=files, headers=headers)
    assert resp.status_code == 413
    assert "exceeds the maximum allowed size" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_upload_insufficient_disk_space(client: AsyncClient) -> None:
    headers = await _seed_admin_api_key_header(client, permissions=["server:write"])
    zip_bytes = _build_zip_bytes({"server.properties": b"server-port=25565\n"})
    files = {"file": ("server.zip", zip_bytes, "application/zip")}

    import collections
    Usage = collections.namedtuple("usage", ["total", "used", "free"])
    with patch("shutil.disk_usage", return_value=Usage(total=1000, used=999, free=1)):
        resp = await client.post("/api/v1/servers/import/upload", files=files, headers=headers)
        assert resp.status_code == 507
        assert "Insufficient disk space" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_upload_and_import_success(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staging_root = tmp_path / "staging"
    staging_root.mkdir()
    monkeypatch.setenv("MCS_IMPORT_STAGING_DIR", str(staging_root))

    headers = await _seed_admin_api_key_header(client, permissions=["server:write"])
    zip_bytes = _build_zip_bytes({
        "server.properties": (
            b"server-port=25577\nmotd=Upload Test Server\nserver-name=UploadedServer\n"
        ),
        "eula.txt": b"eula=true\n",
        "server.jar": b"PK\x03\x04fakejarcontent",
    })
    files = {"file": ("server.zip", zip_bytes, "application/zip")}

    # 1. Upload and scan
    resp = await client.post("/api/v1/servers/import/upload", files=files, headers=headers)
    assert resp.status_code == 200, resp.text
    scan_data = resp.json()
    assert scan_data["name"] == "UploadedServer"
    assert scan_data["properties"]["port"] == 25577
    assert scan_data["properties"]["motd"] == "Upload Test Server"
    assert scan_data["eula_accepted"] is True
    assert scan_data["server_jar"] == "server.jar"

    extracted_path = Path(scan_data["path"])
    assert extracted_path.exists()
    assert (extracted_path / "server.properties").exists()

    # 2. Complete import using the scanned import_id
    import_payload = {
        "import_id": scan_data["import_id"],
        "name": "Imported From Upload",
        "server_type": "vanilla",
        "minecraft_version": "1.20.1",
        "min_memory_mb": 1024,
        "max_memory_mb": 2048,
        "port": 25577,
    }
    import_resp = await client.post("/api/v1/servers/import", json=import_payload, headers=headers)
    assert import_resp.status_code == 201, import_resp.text

    # 3. Verify the staging import folder was cleaned up after successful import
    import_staging_dirs = list(staging_root.iterdir())
    assert len(import_staging_dirs) == 0


@pytest.mark.asyncio
async def test_scan_local_zip_file(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staging_root = tmp_path / "staging_scan"
    staging_root.mkdir()
    monkeypatch.setenv("MCS_IMPORT_STAGING_DIR", str(staging_root))

    headers = await _seed_admin_api_key_header(client, permissions=["server:write"])
    zip_bytes = _build_zip_bytes({
        "server.properties": (
            b"server-port=25588\nmotd=Local Zip Test\nserver-name=LocalZipServer\n"
        ),
        "eula.txt": b"eula=true\n",
        "purpur.jar": b"PK\x03\x04fakejarcontent",
    })
    files = {"file": ("server.zip", zip_bytes, "application/zip")}
    upload_resp = await client.post("/api/v1/servers/import/upload", files=files, headers=headers)
    assert upload_resp.status_code == 200
    import_id = upload_resp.json()["import_id"]

    resp = await client.post(
        "/api/v1/servers/scan",
        json={"import_id": import_id},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    scan_data = resp.json()
    assert scan_data["name"] == "LocalZipServer"
    assert scan_data["properties"]["port"] == 25588
    assert scan_data["server_jar"] == "purpur.jar"


@pytest.mark.asyncio
async def test_import_direct_from_zip(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staging_root = tmp_path / "staging_direct"
    staging_root.mkdir()
    monkeypatch.setenv("MCS_IMPORT_STAGING_DIR", str(staging_root))

    headers = await _seed_admin_api_key_header(client, permissions=["server:write"])
    zip_bytes = _build_zip_bytes({
        "server.properties": (
            b"server-port=25589\nmotd=Direct Zip Import\nserver-name=DirectZip\n"
        ),
        "eula.txt": b"eula=true\n",
        "server.jar": b"PK\x03\x04fakejarcontent",
    })
    files = {"file": ("direct.zip", zip_bytes, "application/zip")}
    upload_resp = await client.post("/api/v1/servers/import/upload", files=files, headers=headers)
    assert upload_resp.status_code == 200
    import_id = upload_resp.json()["import_id"]

    # Passing raw path is rejected with 422
    bad_payload = {
        "source_path": "/some/path",
        "name": "Direct Zip Imported",
        "server_type": "vanilla",
        "minecraft_version": "1.20.1",
        "port": 25589,
    }
    bad_resp = await client.post(
        "/api/v1/servers/import",
        json=bad_payload,
        headers=headers,
    )
    assert bad_resp.status_code == 422

    # Passing valid import_id succeeds
    import_payload = {
        "import_id": import_id,
        "name": "Direct Zip Imported",
        "server_type": "vanilla",
        "minecraft_version": "1.20.1",
        "port": 25589,
    }
    resp = await client.post(
        "/api/v1/servers/import",
        json=import_payload,
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    imported_data = resp.json()
    assert "server_id" in imported_data

