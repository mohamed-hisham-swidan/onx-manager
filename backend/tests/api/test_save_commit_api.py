"""API tests for native Git Save & Commit (P2-4)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core.host_state import ensure_host_state_layout
from app.core.persistence.db import database
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.domain.lockfile import LoaderRef, LockfileV21
from app.modules.versioning.infrastructure.git_branches import GitBranchService
from app.modules.versioning.infrastructure.git_repository import GitRepositoryService
from tests.api.test_api_endpoints import _seed_api_key_header

pytest_plugins = ["tests.api.test_api_endpoints"]

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="P2 Advanced-mode native Git is POSIX-only; Windows remains Simple-only",
)

SERVER_ID = "srv-save-commit-api"
WORKTREE = Path()


def _empty_lockfile() -> LockfileV21:
    return LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="paper", version="499"),
        base_overrides={},
        files=(),
    )


def _head(worktree: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "HEAD"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()


async def _seed_server(root: Path) -> None:
    async with database.session_factory() as session:
        session.add(
            ServerModel(
                id=SERVER_ID,
                name="Save Commit Server",
                server_type="paper",
                minecraft_version="1.20.4",
                status="STOPPED",
                root_path=str(root),
                working_directory=".",
                startup_jar="server.jar",
                deployment_host="127.0.0.1",
                port=25565,
                java_args="-Xmx1G",
                mode="advanced",
            )
        )
        await session.commit()


@pytest.fixture
def host_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ONX_HOST_STATE_DIR", str(tmp_path / "host-state"))
    monkeypatch.setenv("ONX_SERVERS_DATA_DIR", str(tmp_path / "servers"))
    return tmp_path


@pytest.fixture
async def advanced_server(
    client: AsyncClient,
    created_user: dict,
    host_state: Path,
) -> tuple[Path, dict[str, str]]:
    global WORKTREE
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
    WORKTREE = root / ".onx" / "worktrees" / "dev"
    header = await _seed_api_key_header(client, created_user["user_id"], ["admin:full"])
    return root, header


@pytest.mark.asyncio
async def test_save_commit_commits_branch_worktree(
    client: AsyncClient,
    advanced_server: tuple[Path, dict[str, str]],
) -> None:
    root, header = advanced_server

    resp = await client.put(
        f"/api/v1/servers/{SERVER_ID}/files/content",
        params={"path": "config/app.yml", "branch": "dev"},
        json={"content": "enabled: false\n"},
        headers=header,
    )
    assert resp.status_code == 200

    resp = await client.post(
        f"/api/v1/servers/{SERVER_ID}/versioning/commits",
        json={"message": "Toggle feature", "branch_name": "dev"},
        headers=header,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body["commit_id"]) == 40
    assert body["branch_name"] == "dev"
    assert body["engine"] == "native-git"
    assert "config/app.yml" in body["files"]
    assert (WORKTREE / "config" / "app.yml").read_text(encoding="utf-8") == (
        "enabled: false\n"
    )
    assert (root / "config" / "app.yml").read_text(encoding="utf-8") == (
        "enabled: true\n"
    )


@pytest.mark.asyncio
async def test_save_commit_rejects_secret_without_advancing_head(
    client: AsyncClient,
    advanced_server: tuple[Path, dict[str, str]],
) -> None:
    _, header = advanced_server
    resp = await client.put(
        f"/api/v1/servers/{SERVER_ID}/files/content",
        params={"path": "config/api.yml", "branch": "dev"},
        json={"content": "api-key: very-secret-value\n"},
        headers=header,
    )
    assert resp.status_code == 200

    before = _head(WORKTREE)
    resp = await client.post(
        f"/api/v1/servers/{SERVER_ID}/versioning/commits",
        json={"message": "Add API config", "branch_name": "dev"},
        headers=header,
    )
    assert resp.status_code == 422, resp.text
    assert "very-secret-value" not in resp.text
    assert _head(WORKTREE) == before


@pytest.mark.asyncio
async def test_save_commit_on_main_requires_actual_changes(
    client: AsyncClient,
    advanced_server: tuple[Path, dict[str, str]],
) -> None:
    _, header = advanced_server
    resp = await client.post(
        f"/api/v1/servers/{SERVER_ID}/versioning/commits",
        json={"message": "No changes", "branch_name": "main"},
        headers=header,
    )
    assert resp.status_code == 409, resp.text
