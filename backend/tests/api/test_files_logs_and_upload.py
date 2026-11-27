"""Tests for read-only scope=logs in Files API and hardened branch-aware upload."""

from __future__ import annotations

import gzip
import io
import os
import time
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core.host_state import ensure_host_state_layout
from app.core.persistence.db import database
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.domain.lockfile import LoaderRef, LockfileV21
from app.modules.versioning.infrastructure.git_branches import GitBranchService
from app.modules.versioning.infrastructure.git_repository import GitRepositoryService
from app.modules.versioning.infrastructure.models import (
    ServerBranchModel,
    ServerCommitModel,
    ServerRuntimeModel,
)
from tests.api.test_api_endpoints import _seed_admin_api_key_header

pytest_plugins = ["tests.api.test_api_endpoints"]


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


async def _seed_server(server_id: str, root: Path, *, mode: str = "simple") -> None:
    async with database.session_factory() as session:
        session.add(
            ServerModel(
                id=server_id,
                name="Logs Test Server",
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
async def test_logs_scope_listing_sorting_containment_and_readonly(
    client: AsyncClient,
    host_state: Path,
    tmp_path: Path,
) -> None:
    server_id = "srv-logs-simple"
    root = host_state / "simple-logs-srv"
    root.mkdir(parents=True)

    # Allowed log files
    (root / "logs").mkdir()
    latest_log = root / "logs" / "latest.log"
    latest_log.write_text("[12:00:00 INFO]: Done (1.2s)!\n", encoding="utf-8")
    old_log = root / "logs" / "2026-11-20-1.log"
    old_log.write_text("[10:00:00 WARN]: Old warning\n", encoding="utf-8")
    gz_log = root / "logs" / "2026-11-21-1.log.gz"
    gz_log.write_bytes(gzip.compress(b"[11:00:00 INFO]: Compressed line\n"))

    (root / "crash-reports").mkdir()
    crash_txt = root / "crash-reports" / "crash-2026-11-24.txt"
    crash_txt.write_text("---- Minecraft Crash Report ----\nError\n", encoding="utf-8")

    (root / "plugins" / "Essentials" / "logs").mkdir(parents=True)
    plugin_depth1 = root / "plugins" / "Essentials" / "plugin.log"
    plugin_depth1.write_text("[INFO] Essentials started\n", encoding="utf-8")
    plugin_depth2 = root / "plugins" / "Essentials" / "logs" / "debug.log"
    plugin_depth2.write_text("[WARN] Debug entry\n", encoding="utf-8")

    # Depth 3 must NOT be exposed
    (root / "plugins" / "Essentials" / "logs" / "nested").mkdir(parents=True)
    (root / "plugins" / "Essentials" / "logs" / "nested" / "too_deep.log").write_text(
        "hidden\n", encoding="utf-8"
    )

    # Secrets / unrelated files / symlink escapes must NOT be exposed
    (root / ".env").write_text("SECRET=123\n", encoding="utf-8")
    (root / "server.properties").write_text("motd=hi\n", encoding="utf-8")
    outside_secret = tmp_path / "outside.log"
    outside_secret.write_text("TOP_SECRET\n", encoding="utf-8")
    if os.name == "posix":
        os.symlink(outside_secret, root / "logs" / "escape.log")

    # Ensure deterministic mtimes: latest.log older than old_log to verify pinning
    now = time.time()
    os.utime(old_log, (now - 10, now - 10))
    os.utime(latest_log, (now - 1000, now - 1000))
    os.utime(crash_txt, (now - 2000, now - 2000))

    await _seed_server(server_id, root, mode="simple")
    header = await _seed_admin_api_key_header(client)

    resp = await client.get(
        f"/api/v1/servers/{server_id}/files",
        params={"scope": "logs"},
        headers=header,
    )
    assert resp.status_code == 200
    entries = resp.json()
    paths = [e["path"] for e in entries]

    assert "crash-reports/crash-2026-11-24.txt" in paths
    assert "logs/latest.log" in paths
    assert "logs/2026-11-20-1.log" in paths
    assert "logs/2026-11-21-1.log.gz" in paths
    assert "plugins/Essentials/plugin.log" in paths
    assert "plugins/Essentials/logs/debug.log" in paths
    assert "plugins/Essentials/logs/nested/too_deep.log" not in paths
    assert "logs/escape.log" not in paths
    assert ".env" not in paths
    assert "server.properties" not in paths

    # Pinning order: crash_report first, logs/latest.log second
    assert paths[0] == "crash-reports/crash-2026-11-24.txt"
    assert paths[1] == "logs/latest.log"

    by_path = {e["path"]: e for e in entries}
    assert by_path["crash-reports/crash-2026-11-24.txt"]["log_category"] == "crash_report"
    assert by_path["logs/latest.log"]["log_category"] == "server_log"
    assert by_path["plugins/Essentials/plugin.log"]["log_category"] == "plugin_log"
    assert all(e["editable"] is False for e in entries)

    # Reading plain log, compressed .log.gz, and blocking symlink/secret paths
    read_plain = await client.get(
        f"/api/v1/servers/{server_id}/files/content",
        params={"path": "logs/latest.log", "scope": "logs"},
        headers=header,
    )
    assert read_plain.status_code == 200
    assert "Done (1.2s)!" in read_plain.json()["content"]
    assert read_plain.json()["truncated"] is False

    read_gz = await client.get(
        f"/api/v1/servers/{server_id}/files/content",
        params={"path": "logs/2026-11-21-1.log.gz", "scope": "logs"},
        headers=header,
    )
    assert read_gz.status_code == 200
    assert read_gz.json()["is_compressed"] is True
    assert "Compressed line" in read_gz.json()["content"]

    if os.name == "posix":
        read_sym = await client.get(
            f"/api/v1/servers/{server_id}/files/content",
            params={"path": "logs/escape.log", "scope": "logs"},
            headers=header,
        )
        assert read_sym.status_code == 403

    read_env = await client.get(
        f"/api/v1/servers/{server_id}/files/content",
        params={"path": ".env", "scope": "logs"},
        headers=header,
    )
    assert read_env.status_code == 403

    # Hard read-only enforcement on all mutating endpoints
    for method, url, kwargs in [
        (
            "PUT",
            f"/api/v1/servers/{server_id}/files/content",
            {"params": {"path": "logs/latest.log", "scope": "logs"}, "json": {"content": "x"}},
        ),
        (
            "DELETE",
            f"/api/v1/servers/{server_id}/files",
            {"params": {"path": "logs/latest.log", "scope": "logs"}},
        ),
        (
            "POST",
            f"/api/v1/servers/{server_id}/files/upload",
            {
                "params": {"path": "logs", "scope": "logs"},
                "files": {"file": ("evil.log", io.BytesIO(b"x"), "text/plain")},
            },
        ),
        (
            "POST",
            f"/api/v1/servers/{server_id}/files/mkdir",
            {"params": {"path": "logs/sub", "scope": "logs"}},
        ),
    ]:
        mut_resp = await client.request(method, url, headers=header, **kwargs)
        assert mut_resp.status_code == 403
        assert mut_resp.json()["code"] == "LOGS_READ_ONLY"


@pytest.mark.asyncio
async def test_logs_scope_large_file_tail_and_download(
    client: AsyncClient,
    host_state: Path,
) -> None:
    server_id = "srv-logs-tail"
    root = host_state / "tail-logs-srv"
    (root / "logs").mkdir(parents=True)

    # Create a > 5 MB log file with a distinct tail marker
    padding = b"INFO padding line\n" * 300_000  # ~5.4 MB
    tail_marker = b"[12:34:56 ERROR]: FINAL_CRASH_TAIL_MARKER\n"
    (root / "logs" / "latest.log").write_bytes(padding + tail_marker)

    await _seed_server(server_id, root, mode="simple")
    header = await _seed_admin_api_key_header(client)

    resp = await client.get(
        f"/api/v1/servers/{server_id}/files/content",
        params={"path": "logs/latest.log", "scope": "logs"},
        headers=header,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["truncated"] is True
    assert body["total_size_bytes"] == len(padding) + len(tail_marker)
    assert "FINAL_CRASH_TAIL_MARKER" in body["content"]

    dl_resp = await client.get(
        f"/api/v1/servers/{server_id}/files/download",
        params={"path": "logs/latest.log", "scope": "logs"},
        headers=header,
    )
    assert dl_resp.status_code == 200
    assert len(dl_resp.content) == len(padding) + len(tail_marker)


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.name != "posix",
    reason="POSIX-only Git branch/worktree API tests",
)
async def test_logs_scope_advanced_branch_isolation_and_branch_upload(
    client: AsyncClient,
    host_state: Path,
) -> None:
    server_id = "srv-adv-logs-upload"
    root = host_state / "adv-srv"
    root.mkdir(parents=True)
    (root / "server.properties").write_text("motd=Hello\nserver-port=25565\n", encoding="utf-8")
    (root / "config").mkdir()
    (root / "config" / "app.yml").write_text("enabled: true\n", encoding="utf-8")
    (root / "logs").mkdir()
    (root / "logs" / "latest.log").write_text("[INFO] MAIN_RUNTIME_LOG\n", encoding="utf-8")

    await _seed_server(server_id, root, mode="advanced")
    layout = ensure_host_state_layout()
    GitRepositoryService(layout).initialize(server_id, root, _empty_lockfile())
    GitBranchService(layout).create_branch(server_id, root, "dev")
    header = await _seed_admin_api_key_header(client)

    # 1. main sees main's live logs
    main_logs = await client.get(
        f"/api/v1/servers/{server_id}/files",
        params={"branch": "main", "scope": "logs"},
        headers=header,
    )
    assert main_logs.status_code == 200
    assert [e["path"] for e in main_logs.json()] == ["logs/latest.log"]

    # 2. dev with NO provisioned runtime returns [] and NEVER leaks main's logs
    dev_logs_empty = await client.get(
        f"/api/v1/servers/{server_id}/files",
        params={"branch": "dev", "scope": "logs"},
        headers=header,
    )
    assert dev_logs_empty.status_code == 200
    assert dev_logs_empty.json() == []

    dev_read_missing = await client.get(
        f"/api/v1/servers/{server_id}/files/content",
        params={"path": "logs/latest.log", "branch": "dev", "scope": "logs"},
        headers=header,
    )
    assert dev_read_missing.status_code == 404

    # 3. Provision a branch runtime export dir under .onx/branch-exports/<id>
    runtime_id = uuid.uuid4().hex
    export_dir = root / ".onx" / "branch-exports" / runtime_id
    (export_dir / "logs").mkdir(parents=True)
    (export_dir / "logs" / "latest.log").write_text(
        "[INFO] DEV_BRANCH_RUNTIME_LOG\n", encoding="utf-8"
    )
    async with database.session_factory() as session:
        commit_id = "c" * 40
        session.add(
            ServerCommitModel(
                id=commit_id,
                server_id=server_id,
                message="init",
                manifest_json={},
            )
        )
        session.add(
            ServerBranchModel(
                id=uuid.uuid4().hex,
                server_id=server_id,
                name="dev",
                head_commit_id=commit_id,
                active_runtime_id=runtime_id,
            )
        )
        session.add(
            ServerRuntimeModel(
                id=runtime_id,
                server_id=server_id,
                commit_id=commit_id,
                status="running",
                branch_name="dev",
                export_path=str(export_dir),
            )
        )
        await session.commit()

    dev_logs = await client.get(
        f"/api/v1/servers/{server_id}/files",
        params={"branch": "dev", "scope": "logs"},
        headers=header,
    )
    assert dev_logs.status_code == 200
    assert [e["path"] for e in dev_logs.json()] == ["logs/latest.log"]

    dev_log_content = await client.get(
        f"/api/v1/servers/{server_id}/files/content",
        params={"path": "logs/latest.log", "branch": "dev", "scope": "logs"},
        headers=header,
    )
    assert dev_log_content.status_code == 200
    assert "DEV_BRANCH_RUNTIME_LOG" in dev_log_content.json()["content"]
    assert "MAIN_RUNTIME_LOG" not in dev_log_content.json()["content"]

    # 4. Branch-aware file upload: accepts valid Class-B into dev worktree
    up_ok = await client.post(
        f"/api/v1/servers/{server_id}/files/upload",
        params={"path": "config", "branch": "dev"},
        files={"file": ("feature.yml", io.BytesIO(b"feature: true\n"), "text/yaml")},
        headers=header,
    )
    assert up_ok.status_code == 201
    dev_worktree = root / ".onx" / "worktrees" / "dev"
    feature_yml = dev_worktree / "config" / "feature.yml"
    assert feature_yml.read_text(encoding="utf-8") == "feature: true\n"
    assert not (root / "config" / "feature.yml").exists()

    # 5. Rejects protected main upload (403)
    up_main = await client.post(
        f"/api/v1/servers/{server_id}/files/upload",
        params={"path": "config", "branch": "main"},
        files={"file": ("blocked.yml", io.BytesIO(b"x: 1\n"), "text/yaml")},
        headers=header,
    )
    assert up_main.status_code == 403

    # 6. Rejects Class-E (.db) and .jar (pointing to Plugins) on dev branch
    up_db = await client.post(
        f"/api/v1/servers/{server_id}/files/upload",
        params={"path": "config", "branch": "dev"},
        files={"file": ("bad.db", io.BytesIO(b"sqlite"), "application/octet-stream")},
        headers=header,
    )
    assert up_db.status_code == 403
    assert "tracked configuration files" in up_db.json()["detail"].lower()

    up_jar = await client.post(
        f"/api/v1/servers/{server_id}/files/upload",
        params={"path": "plugins", "branch": "dev"},
        files={"file": ("BadPlugin.jar", io.BytesIO(b"PK\x03\x04"), "application/java-archive")},
        headers=header,
    )
    assert up_jar.status_code == 403
    assert "plugins" in up_jar.json()["detail"].lower()
