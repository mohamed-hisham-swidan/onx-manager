"""Tests for validated plugin JAR upload on Simple and Advanced working branches."""

from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core.host_state import ensure_host_state_layout
from app.core.persistence.db import database
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.domain.lockfile import LoaderRef, LockfileV21, parse_lockfile
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.git_branches import GitBranchService
from app.modules.versioning.infrastructure.git_repository import GitRepositoryService
from tests.api.test_api_endpoints import _seed_api_key_header

pytest_plugins = ["tests.api.test_api_endpoints"]


@pytest.fixture
def host_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ONX_HOST_STATE_DIR", str(tmp_path / "host-state"))
    monkeypatch.setenv("ONX_SERVERS_DATA_DIR", str(tmp_path / "servers"))
    return tmp_path


def _make_jar_bytes(files: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content.encode("utf-8") if isinstance(content, str) else content)
    return buf.getvalue()


def _empty_lockfile() -> LockfileV21:
    return LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="paper", version="499"),
        base_overrides={},
        files=(),
    )


async def _seed_server(server_id: str, root: Path, *, mode: str = "simple") -> None:
    async with database.session_factory() as session:
        session.add(
            ServerModel(
                id=server_id,
                name="Plugin Upload Test Server",
                server_type="paper",
                minecraft_version="1.20.4",
                status="STOPPED",
                root_path=str(root),
                working_directory=".",
                startup_jar="server.jar",
                deployment_host="127.0.0.1",
                port=25565,
                java_args="-Xmx1G",
                mode=mode,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_simple_plugin_upload_validates_descriptors_and_rejects_invalid_jars(
    client: AsyncClient,
    created_user: dict,
    host_state: Path,
) -> None:
    server_id = "srv-simple-jar-upload"
    root = host_state / "simple-jar-srv"
    root.mkdir(parents=True)
    await _seed_server(server_id, root, mode="simple")
    header = await _seed_api_key_header(client, created_user["user_id"], ["admin:full"])

    # 1. Rejects non-.jar extension
    bad_ext = await client.post(
        f"/api/v1/servers/{server_id}/plugins/upload",
        files={"file": ("not-a-jar.txt", io.BytesIO(b"hello"), "text/plain")},
        headers=header,
    )
    assert bad_ext.status_code == 422
    assert bad_ext.json()["code"] == "INVALID_PLUGIN_JAR"

    # 2. Rejects non-ZIP / corrupted archive
    bad_zip = await client.post(
        f"/api/v1/servers/{server_id}/plugins/upload",
        files={"file": ("fake.jar", io.BytesIO(b"plain text not zip"), "application/java-archive")},
        headers=header,
    )
    assert bad_zip.status_code == 422
    assert bad_zip.json()["code"] == "INVALID_PLUGIN_JAR"
    assert not (root / "plugins" / "fake.jar").exists()

    # 3. Rejects valid ZIP missing plugin descriptor
    no_desc_jar = _make_jar_bytes({"META-INF/MANIFEST.MF": "Manifest-Version: 1.0\n"})
    missing_desc = await client.post(
        f"/api/v1/servers/{server_id}/plugins/upload",
        files={"file": ("nodesc.jar", io.BytesIO(no_desc_jar), "application/java-archive")},
        headers=header,
    )
    assert missing_desc.status_code == 422
    assert missing_desc.json()["code"] == "INVALID_PLUGIN_JAR"
    assert "plugin.yml" in missing_desc.json()["message"]
    assert not (root / "plugins" / "nodesc.jar").exists()

    # 4. Accepts valid plugin.yml, paper-plugin.yml, and velocity-plugin.json
    for fname, files, expected_loader in [
        (
            "bukkit-plugin.jar",
            {"plugin.yml": "name: BukkitTest\nversion: 1.0.0\nmain: com.example.Main\n"},
            "bukkit",
        ),
        (
            "paper-plugin.jar",
            {"paper-plugin.yml": "name: PaperTest\nversion: 2.0.0\nmain: com.example.Paper\n"},
            "paper",
        ),
    ]:
        jar_bytes = _make_jar_bytes(files)
        ok_resp = await client.post(
            f"/api/v1/servers/{server_id}/plugins/upload",
            files={"file": (fname, io.BytesIO(jar_bytes), "application/java-archive")},
            headers=header,
        )
        assert ok_resp.status_code == 201, ok_resp.text
        assert ok_resp.json()["loader"] == expected_loader
        assert (root / "plugins" / fname).is_file()

    # 5. Rejects incompatible loader JAR (velocity-plugin.json on a paper server)
    vel_jar = _make_jar_bytes(
        {
            "velocity-plugin.json": json.dumps(
                {"id": "veltest", "name": "VelTest", "version": "3.1.0"}
            )
        }
    )
    incompat_resp = await client.post(
        f"/api/v1/servers/{server_id}/plugins/upload",
        files={"file": ("velocity-plugin.jar", io.BytesIO(vel_jar), "application/java-archive")},
        headers=header,
    )
    assert incompat_resp.status_code == 422
    assert incompat_resp.json()["code"] == "INVALID_PLUGIN_JAR"


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.name != "posix",
    reason="POSIX-only Git branch/worktree API tests",
)
async def test_advanced_branch_plugin_upload_validates_and_ingests_to_cas(
    client: AsyncClient,
    created_user: dict,
    host_state: Path,
) -> None:
    server_id = "srv-adv-jar-upload"
    root = host_state / "adv-jar-srv"
    root.mkdir(parents=True)
    (root / "server.properties").write_text("motd=Hello\nserver-port=25565\n", encoding="utf-8")
    await _seed_server(server_id, root, mode="advanced")

    layout = ensure_host_state_layout()
    GitRepositoryService(layout).initialize(server_id, root, _empty_lockfile())
    GitBranchService(layout).create_branch(server_id, root, "dev")
    header = await _seed_api_key_header(client, created_user["user_id"], ["admin:full"])

    valid_jar = _make_jar_bytes(
        {"paper-plugin.yml": "name: BranchPaperPlugin\nversion: 1.2.3\nmain: com.ex.Main\n"}
    )

    # 1. Protected main rejects upload with 409
    main_resp = await client.post(
        f"/api/v1/servers/{server_id}/plugins/upload",
        params={"branch": "main"},
        files={
            "file": (
                "BranchPaperPlugin.jar",
                io.BytesIO(valid_jar),
                "application/java-archive",
            )
        },
        headers=header,
    )
    assert main_resp.status_code == 409

    # 2. Invalid JAR on dev branch rejected cleanly without touching CAS or lockfile
    bad_jar = _make_jar_bytes({"readme.txt": "not a plugin"})
    bad_resp = await client.post(
        f"/api/v1/servers/{server_id}/plugins/upload",
        params={"branch": "dev"},
        files={"file": ("Invalid.jar", io.BytesIO(bad_jar), "application/java-archive")},
        headers=header,
    )
    assert bad_resp.status_code == 422
    assert bad_resp.json()["code"] == "INVALID_PLUGIN_JAR"
    dev_lockfile_path = root / ".onx" / "worktrees" / "dev" / "onx-jars.lock.json"
    dev_lockfile_before = parse_lockfile(dev_lockfile_path.read_bytes())
    assert len(dev_lockfile_before.files) == 0

    # 3. Valid JAR on dev branch ingests into CAS and updates dev lockfile only
    ok_resp = await client.post(
        f"/api/v1/servers/{server_id}/plugins/upload",
        params={"branch": "dev"},
        files={
            "file": (
                "BranchPaperPlugin.jar",
                io.BytesIO(valid_jar),
                "application/java-archive",
            )
        },
        headers=header,
    )
    assert ok_resp.status_code == 201, ok_resp.text
    payload = ok_resp.json()
    assert payload["name"] == "BranchPaperPlugin"
    assert payload["version"] == "1.2.3"
    assert payload["loader"] == "paper"
    assert payload["branch_name"] == "dev"

    cas = ArtifactCas(layout.cas)
    assert cas.has(payload["checksum"])

    dev_lockfile_after = parse_lockfile(dev_lockfile_path.read_bytes())
    assert [f.path for f in dev_lockfile_after.files] == ["plugins/BranchPaperPlugin.jar"]
    main_lockfile_path = root / ".onx" / "worktrees" / "main" / "onx-jars.lock.json"
    main_lockfile = parse_lockfile(main_lockfile_path.read_bytes())
    assert len(main_lockfile.files) == 0
    assert not (root / "plugins" / "BranchPaperPlugin.jar").exists()
