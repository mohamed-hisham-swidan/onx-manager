"""Branch-aware Files API tests for P2-4 acceptance #3."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core.host_state import ensure_host_state_layout
from app.core.persistence.db import database
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.domain.lockfile import LoaderRef, LockfileV21
from app.modules.versioning.infrastructure.git_branches import GitBranchService
from app.modules.versioning.infrastructure.git_repository import GitRepositoryService
from tests.api.test_api_endpoints import _seed_admin_api_key_header

pytest_plugins = ["tests.api.test_api_endpoints"]

SERVER_ID = "srv-branch-files"
SIMPLE_SERVER_ID = "srv-simple-files"


@pytest.fixture
def host_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ONX_HOST_STATE_DIR", str(tmp_path / "host-state"))
    monkeypatch.setenv("ONX_SERVERS_DATA_DIR", str(tmp_path / "servers"))
    return tmp_path


def _empty_lockfile() -> LockfileV21:
    return LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="paper", version="499"),
        base_overrides={},
        files=(),
    )


async def _seed_server(
    root: Path,
    *,
    mode: str = "advanced",
    server_id: str = SERVER_ID,
) -> None:
    async with database.session_factory() as session:
        session.add(
            ServerModel(
                id=server_id,
                name="Branch Files Server",
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


@pytest.fixture
async def advanced_server(
    client: AsyncClient,
    host_state: Path,
) -> tuple[Path, Path, dict[str, str]]:
    if os.name != "posix":
        pytest.skip("POSIX-only Git branch/worktree fixture; Windows = Simple-only")
    root = host_state / "server"
    root.mkdir()
    (root / "server.properties").write_text(
        "motd=Hello\nserver-port=25565\n",
        encoding="utf-8",
    )
    (root / "config").mkdir()
    (root / "config" / "app.yml").write_text("enabled: true\n", encoding="utf-8")
    await _seed_server(root)

    layout = ensure_host_state_layout()
    GitRepositoryService(layout).initialize(SERVER_ID, root, _empty_lockfile())
    GitBranchService(layout).create_branch(SERVER_ID, root, "dev")
    header = await _seed_admin_api_key_header(client)
    return root, layout, header


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.name != "posix",
    reason="POSIX-only Git branch/worktree API tests; Windows = Simple-only",
)
async def test_main_is_read_only_and_git_entry_is_hidden(
    client: AsyncClient,
    advanced_server: tuple[Path, Path, dict[str, str]],
) -> None:
    root, _, header = advanced_server
    main_worktree = root / ".onx" / "worktrees" / "main"

    resp = await client.get(f"/api/v1/servers/{SERVER_ID}/files", headers=header)
    assert resp.status_code == 200
    names = {entry["name"] for entry in resp.json()}
    assert "server.properties" in names
    assert ".git" not in names

    resp = await client.get(
        f"/api/v1/servers/{SERVER_ID}/files",
        params={"path": ".git"},
        headers=header,
    )
    assert resp.status_code == 403

    resp = await client.get(
        f"/api/v1/servers/{SERVER_ID}/files/content",
        params={"path": "server.properties", "branch": "main"},
        headers=header,
    )
    assert resp.status_code == 200

    resp = await client.put(
        f"/api/v1/servers/{SERVER_ID}/files/content",
        params={"path": "server.properties"},
        json={"content": "motd=Changed\n"},
        headers=header,
    )
    assert resp.status_code == 403
    assert "read-only" in resp.json()["detail"].lower()

    resp = await client.put(
        f"/api/v1/servers/{SERVER_ID}/files/content",
        params={"path": "config/app.yml", "branch": "main"},
        json={"content": "enabled: false\n"},
        headers=header,
    )
    assert resp.status_code == 403

    # The live deployment root is not the main worktree and stays untouched.
    assert (root / "server.properties").read_text(encoding="utf-8") == (
        "motd=Hello\nserver-port=25565\n"
    )
    assert (main_worktree / "config" / "app.yml").read_text(encoding="utf-8") == (
        "enabled: true\n"
    )


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.name != "posix",
    reason="POSIX-only Git branch/worktree API tests; Windows = Simple-only",
)
async def test_feature_branch_reads_and_writes_its_worktree(
    client: AsyncClient,
    advanced_server: tuple[Path, Path, dict[str, str]],
) -> None:
    root, _, header = advanced_server
    worktree = root / ".onx" / "worktrees" / "dev"

    resp = await client.put(
        f"/api/v1/servers/{SERVER_ID}/files/content",
        params={"path": "config/feature.yml", "branch": "dev"},
        json={"content": "feature: true\n"},
        headers=header,
    )
    assert resp.status_code == 200
    assert (worktree / "config" / "feature.yml").read_text(encoding="utf-8") == (
        "feature: true\n"
    )
    assert not (root / "config" / "feature.yml").exists()

    resp = await client.get(
        f"/api/v1/servers/{SERVER_ID}/files/content",
        params={"path": "config/feature.yml", "branch": "dev"},
        headers=header,
    )
    assert resp.status_code == 200
    assert resp.json()["content"] == "feature: true\n"

    resp = await client.get(
        f"/api/v1/servers/{SERVER_ID}/files",
        params={"path": "config", "branch": "dev"},
        headers=header,
    )
    assert resp.status_code == 200
    assert "feature.yml" in {entry["name"] for entry in resp.json()}

    resp = await client.post(
        f"/api/v1/servers/{SERVER_ID}/files/mkdir",
        params={"path": "newdir", "branch": "dev"},
        headers=header,
    )
    assert resp.status_code == 201
    assert (worktree / "newdir").is_dir()
    assert not (root / "newdir").exists()

    resp = await client.delete(
        f"/api/v1/servers/{SERVER_ID}/files",
        params={"path": "config/feature.yml", "branch": "dev"},
        headers=header,
    )
    assert resp.status_code == 204
    assert not (worktree / "config" / "feature.yml").exists()


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.name != "posix",
    reason="POSIX-only Git branch/worktree API tests; Windows = Simple-only",
)
async def test_only_class_b_files_are_editable_on_a_branch(
    client: AsyncClient,
    advanced_server: tuple[Path, Path, dict[str, str]],
) -> None:
    root, _, header = advanced_server
    worktree = root / ".onx" / "worktrees" / "dev"

    for path in ("mods/example.jar", "config/server.pem", "random.txt"):
        resp = await client.put(
            f"/api/v1/servers/{SERVER_ID}/files/content",
            params={"path": path, "branch": "dev"},
            json={"content": "payload\n"},
            headers=header,
        )
        assert resp.status_code == 403, path
        assert not (worktree / path).exists()


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.name != "posix",
    reason="POSIX-only Git branch/worktree API tests; Windows = Simple-only",
)
async def test_reserved_root_files_cannot_be_modified_on_branches(
    client: AsyncClient,
    advanced_server: tuple[Path, Path, dict[str, str]],
) -> None:
    root, _, header = advanced_server
    worktree = root / ".onx" / "worktrees" / "dev"

    for name in ("onx-jars.lock.json", ".gitattributes"):
        original = (worktree / name).read_bytes()

        resp = await client.put(
            f"/api/v1/servers/{SERVER_ID}/files/content",
            params={"path": name, "branch": "dev"},
            json={"content": "tampered\n"},
            headers=header,
        )
        assert resp.status_code == 403
        assert "managed by the panel" in resp.json()["detail"].lower()

        resp = await client.delete(
            f"/api/v1/servers/{SERVER_ID}/files",
            params={"path": name, "branch": "dev"},
            headers=header,
        )
        assert resp.status_code == 403

        resp = await client.post(
            f"/api/v1/servers/{SERVER_ID}/files/upload",
            params={"branch": "dev"},
            files={"file": (name, b"tampered", "application/octet-stream")},
            headers=header,
        )
        assert resp.status_code == 403

        assert (worktree / name).read_bytes() == original


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.name != "posix",
    reason="POSIX-only Git branch/worktree API tests; Windows = Simple-only",
)
async def test_unknown_or_archived_branch_is_rejected(
    client: AsyncClient,
    advanced_server: tuple[Path, Path, dict[str, str]],
) -> None:
    root, layout, header = advanced_server

    resp = await client.get(
        f"/api/v1/servers/{SERVER_ID}/files",
        params={"branch": "missing"},
        headers=header,
    )
    assert resp.status_code == 404

    GitBranchService(layout).archive_branch(SERVER_ID, root, "dev")

    resp = await client.get(
        f"/api/v1/servers/{SERVER_ID}/files",
        params={"branch": "dev"},
        headers=header,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_simple_server_keeps_live_root_files(
    client: AsyncClient,
    host_state: Path,
) -> None:
    root = host_state / "simple-server"
    root.mkdir()
    (root / "ops.txt").write_text("live-root\n", encoding="utf-8")
    await _seed_server(root, mode="simple", server_id=SIMPLE_SERVER_ID)
    header = await _seed_admin_api_key_header(client)

    resp = await client.get(
        f"/api/v1/servers/{SIMPLE_SERVER_ID}/files",
        params={"branch": "dev"},
        headers=header,
    )
    assert resp.status_code == 200
    assert "ops.txt" in {entry["name"] for entry in resp.json()}
