from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core.persistence.db import database
from app.modules.server.infrastructure.models import ServerModel
from tests.api.test_api_endpoints import _seed_api_key_header

pytest_plugins = ["tests.api.test_api_endpoints"]


@pytest.mark.asyncio
async def test_read_binary_file_returns_is_binary_flag(
    client: AsyncClient, created_user: dict, tmp_path: Path
) -> None:
    server_id = "srv-files-bin"
    server_dir = tmp_path / "server_files_bin"
    server_dir.mkdir(parents=True, exist_ok=True)

    # Write a binary file containing non-UTF8 bytes
    bin_file = server_dir / "corrupt_or_binary.dat"
    bin_file.write_bytes(b"\x80\x81\xff\xfe\x00\x01\x02\x03")

    async with database._session_factory() as session:
        session.add(
            ServerModel(
                id=server_id,
                name="Binary Test Server",
                server_type="vanilla",
                minecraft_version="1.21.1",
                status="stopped",
                group_id="default",
                port=25565,
                motd="Test",
                max_players=20,
                gamemode="survival",
                difficulty="normal",
                root_path=str(server_dir),
                owner_id=created_user["user_id"],
            )
        )
        await session.commit()

    header = await _seed_api_key_header(client, created_user["user_id"], ["admin:full"])

    resp = await client.get(
        f"/api/v1/servers/{server_id}/files/content",
        params={"path": "corrupt_or_binary.dat"},
        headers=header,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["path"] == "corrupt_or_binary.dat"
    assert data["is_binary"] is True
    assert data["content"] == ""
