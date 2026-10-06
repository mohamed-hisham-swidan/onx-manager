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
