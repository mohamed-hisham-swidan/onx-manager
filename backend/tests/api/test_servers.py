from pathlib import Path

import pytest
from httpx import AsyncClient

pytest_plugins = ["tests.api.test_api_endpoints"]


@pytest.mark.asyncio
async def test_get_server_detail_omits_secret_keys(
    client: AsyncClient,
    privileged_header: dict[str, str],
    created_server: dict,
) -> None:
    server_id = created_server["server_id"]
    get_resp = await client.get(f"/api/v1/servers/{server_id}", headers=privileged_header)
    assert get_resp.status_code == 200
    root_path = Path(get_resp.json()["root_path"])
    props_file = root_path / "server.properties"

    props_content = (
        "rcon.password=secret1\n"
        "serverPassword=secret2\n"
        "api-key=secret3\n"
        "difficulty=hard\n"
        "motd=A Great Server\n"
        "monkey=fun\n"
        "turkey=dinner\n"
        "level-seed=12345\n"
        "query.port=25565\n"
    )
    props_file.write_text(props_content)

    get_resp = await client.get(f"/api/v1/servers/{server_id}", headers=privileged_header)
    assert get_resp.status_code == 200
    data = get_resp.json()
    raw = data.get("raw_properties", {})

    assert "rcon.password" not in raw
    assert "serverPassword" not in raw
    assert "api-key" not in raw
    assert raw.get("difficulty") == "hard"
    assert raw.get("motd") == "A Great Server"
    assert raw.get("monkey") == "fun"
    assert raw.get("turkey") == "dinner"
    assert raw.get("level-seed") == "12345"
    assert raw.get("query.port") == "25565"


@pytest.mark.asyncio
async def test_update_server_does_not_clobber_omitted_secrets(
    client: AsyncClient,
    privileged_header: dict[str, str],
    created_server: dict,
) -> None:
    server_id = created_server["server_id"]
    get_resp = await client.get(f"/api/v1/servers/{server_id}", headers=privileged_header)
    root_path = Path(get_resp.json()["root_path"])
    props_file = root_path / "server.properties"
    props_file.write_text("rcon.password=secret123\nmotd=Original Motd\n")

    resp = await client.patch(
        f"/api/v1/servers/{server_id}",
        json={"properties": {"motd": "Updated Motd"}},
        headers=privileged_header,
    )
    assert resp.status_code == 200

    content = props_file.read_text()
    assert "rcon.password=secret123" in content


@pytest.mark.asyncio
async def test_update_server_drops_secret_writes(
    client: AsyncClient,
    privileged_header: dict[str, str],
    created_server: dict,
) -> None:
    server_id = created_server["server_id"]
    get_resp = await client.get(f"/api/v1/servers/{server_id}", headers=privileged_header)
    root_path = Path(get_resp.json()["root_path"])
    props_file = root_path / "server.properties"
    props_file.write_text("rcon.password=original-secret\nmotd=Original\n")

    # Attempt masked write
    resp = await client.patch(
        f"/api/v1/servers/{server_id}",
        json={"properties": {"rcon.password": "********"}},
        headers=privileged_header,
    )
    assert resp.status_code == 200
    assert "rcon.password=original-secret" in props_file.read_text()
    assert "********" not in props_file.read_text()

    # Attempt real-value overwrite
    resp2 = await client.patch(
        f"/api/v1/servers/{server_id}",
        json={"properties": {"rcon.password": "new-real-value"}},
        headers=privileged_header,
    )
    assert resp2.status_code == 200
    assert "rcon.password=original-secret" in props_file.read_text()
    assert "new-real-value" not in props_file.read_text()


@pytest.mark.asyncio
async def test_create_server_rejects_invalid_java_args(
    client: AsyncClient,
    privileged_header: dict[str, str],
) -> None:
    payload = {
        "name": "Invalid Args Server",
        "minecraft_version": "1.21",
        "java_args": ["-Xmx1G;calc"],
    }
    resp = await client.post("/api/v1/servers", json=payload, headers=privileged_header)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_server_rejects_invalid_java_args(
    client: AsyncClient,
    privileged_header: dict[str, str],
    created_server: dict,
) -> None:
    server_id = created_server["server_id"]
    resp = await client.patch(
        f"/api/v1/servers/{server_id}",
        json={"java_args": ["-Xmx1G$(id)"]},
        headers=privileged_header,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_servers_returns_additive_live_and_icon_fields(
    client: AsyncClient,
    privileged_header: dict[str, str],
    created_server: dict,
) -> None:
    import base64

    server_id = created_server["server_id"]
    get_resp = await client.get(f"/api/v1/servers/{server_id}", headers=privileged_header)
    assert get_resp.status_code == 200
    root_path = Path(get_resp.json()["root_path"])

    # Initially no icon exists -> icon_data_url is None, max_memory_mb is populated
    list_resp = await client.get("/api/v1/servers", headers=privileged_header)
    assert list_resp.status_code == 200
    items = list_resp.json()
    match = next(item for item in items if item["server_id"] == server_id)
    assert match["max_memory_mb"] == get_resp.json()["max_memory_mb"]
    assert match["uptime_seconds"] is None
    assert match["icon_data_url"] is None
    assert "deployment_host" in match

    # Write a valid PNG server-icon.png -> base64 data URL returned
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    icon_file = root_path / "server-icon.png"
    icon_file.write_bytes(png_bytes)

    list_resp_with_icon = await client.get("/api/v1/servers", headers=privileged_header)
    assert list_resp_with_icon.status_code == 200
    match_icon = next(
        item for item in list_resp_with_icon.json() if item["server_id"] == server_id
    )
    expected_b64 = base64.b64encode(png_bytes).decode("ascii")
    assert match_icon["icon_data_url"] == f"data:image/png;base64,{expected_b64}"

    # Invalid PNG signature -> icon_data_url falls back to None
    icon_file.write_bytes(b"NOT_A_PNG_DATA")
    list_resp_invalid = await client.get("/api/v1/servers", headers=privileged_header)
    assert list_resp_invalid.status_code == 200
    match_invalid = next(
        item for item in list_resp_invalid.json() if item["server_id"] == server_id
    )
    assert match_invalid["icon_data_url"] is None

    # Oversized PNG (> 128 KB) -> icon_data_url falls back to None
    icon_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * (128 * 1024 + 10))
    list_resp_big = await client.get("/api/v1/servers", headers=privileged_header)
    assert list_resp_big.status_code == 200
    match_big = next(
        item for item in list_resp_big.json() if item["server_id"] == server_id
    )
    assert match_big["icon_data_url"] is None
