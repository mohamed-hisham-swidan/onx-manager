"""P3-4 HTTP routes and live state end-to-end tests."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core.host_state import ensure_host_state_layout
from app.core.persistence.db import database
from app.modules.server.infrastructure.models import ServerModel
from app.modules.server.infrastructure.providers import provider_factory
from app.modules.server.infrastructure.providers.base import ServerHandle
from app.modules.versioning.domain.lockfile import LoaderRef, LockfileV21
from app.modules.versioning.infrastructure.git_branches import GitBranchService
from app.modules.versioning.infrastructure.git_repository import GitRepositoryService
from tests.api.test_api_endpoints import _seed_api_key_header

pytest_plugins = ["tests.api.test_api_endpoints"]

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="P3-4 Advanced-mode routes require a POSIX host",
)


SERVER_ID = "srv-p34"
WORKTREE = Path()


def _empty_lockfile() -> LockfileV21:
    return LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="paper", version="499"),
        base_overrides={},
        files=(),
    )


async def _seed_server(root: Path) -> None:
    async with database.session_factory() as session:
        session.add(
            ServerModel(
                id=SERVER_ID,
                name="P34 Server",
                server_type="paper",
                minecraft_version="1.20.4",
                status="STOPPED",
                root_path=str(root),
                working_directory=".",
                startup_jar="server.jar",
                deployment_host="127.0.0.1",
                port=29965,
                java_args="-Xmx1G",
                mode="advanced",
                provider="docker",
                bot_verification_settings={"bot_count": 5, "duration_minutes": 10},
            )
        )
        await session.commit()


@pytest.fixture
def host_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ONX_HOST_STATE_DIR", str(tmp_path / "host-state"))
    monkeypatch.setenv("ONX_SERVERS_DATA_DIR", str(tmp_path / "servers"))
    monkeypatch.setenv("ONX_MASTER_KEK", "01" * 32)
    return tmp_path


@pytest.fixture
async def advanced_server(
    client: AsyncClient,
    created_user: dict,
    host_state: Path,
) -> tuple[Path, dict[str, str]]:
    global WORKTREE
    root = host_state / "servers" / SERVER_ID
    root.mkdir(parents=True, exist_ok=True)
    (root / "server.properties").write_text("motd=Hello\n", encoding="utf-8")
    (root / "config").mkdir(exist_ok=True)
    (root / "config" / "app.yml").write_text("enabled: true\n", encoding="utf-8")
    (root / "whitelist.json").write_text("[]\n", encoding="utf-8")
    await _seed_server(root)
    layout = ensure_host_state_layout()
    GitRepositoryService(layout).initialize(SERVER_ID, root, _empty_lockfile())
    from app.modules.versioning.application.lockfile_service import LockfileService

    LockfileService(layout).write(SERVER_ID, _empty_lockfile())
    GitBranchService(layout).create_branch(SERVER_ID, root, "feat")
    WORKTREE = root / ".onx" / "worktrees" / "feat"
    header = await _seed_api_key_header(client, created_user["user_id"], ["admin:full"])
    try:
        yield root, header
    finally:
        handle = ServerHandle(
            provider="docker",
            server_id=SERVER_ID,
            external_id=f"onx-{SERVER_ID}",
        )
        with contextlib.suppress(Exception):
            await provider_factory.get("docker").destroy(handle)


# ---------- existing 5 tests ----------

@pytest.mark.asyncio
async def test_route_permissions(client: AsyncClient, advanced_server):
    root, header = advanced_server
    res = await client.get(f"/api/v1/servers/{SERVER_ID}/versioning/refresh")
    assert res.status_code == 401
    res = await client.get(
        f"/api/v1/servers/{SERVER_ID}/versioning/refresh",
        headers=header,
    )
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_settings_validation(client: AsyncClient, advanced_server):
    root, header = advanced_server
    res = await client.put(
        f"/api/v1/servers/{SERVER_ID}/versioning/settings",
        json={"previous_tree_retention": "until_confirm"},
        headers=header,
    )
    assert res.status_code == 200
    assert res.json()["previous_tree_retention"] == "until_confirm"
    res = await client.put(
        f"/api/v1/servers/{SERVER_ID}/versioning/settings",
        json={"previous_tree_retention": 0},
        headers=header,
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_live_state_list(client: AsyncClient, advanced_server):
    root, header = advanced_server
    res = await client.get(
        f"/api/v1/servers/{SERVER_ID}/files/live-state",
        headers=header,
    )
    assert res.status_code == 200
    paths = [i["path"] for i in res.json()["items"]]
    assert "/whitelist.json" in paths


@pytest.mark.asyncio
async def test_live_state_content_and_write_stopped(client: AsyncClient, advanced_server):
    root, header = advanced_server
    res = await client.get(
        f"/api/v1/servers/{SERVER_ID}/files/live-state/content",
        params={"path": "/whitelist.json"},
        headers=header,
    )
    assert res.status_code == 200
    res = await client.put(
        f"/api/v1/servers/{SERVER_ID}/files/live-state/content",
        json={"path": "/whitelist.json", "content": "[\"a\"]\n"},
        headers=header,
    )
    assert res.status_code == 200
    assert res.json()["rcon_flushed"] is False
    res = await client.get(
        f"/api/v1/servers/{SERVER_ID}/files/live-state/content",
        params={"path": "/server.properties"},
        headers=header,
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_secrets_extract_and_delete(client: AsyncClient, advanced_server):
    root, header = advanced_server
    target = WORKTREE / "config" / "paper-global.yml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("db-password: supersecret\n", encoding="utf-8")
    res = await client.post(
        f"/api/v1/servers/{SERVER_ID}/versioning/secrets/extract",
        json={
            "branch": "feat",
            "path": "config/paper-global.yml",
            "key_name": "DB_PASSWORD",
            "secret_value": "supersecret",
        },
        headers=header,
    )
    assert res.status_code in (200, 201), res.text
    assert "supersecret" not in res.text
    res = await client.get(
        f"/api/v1/servers/{SERVER_ID}/versioning/secrets",
        headers=header,
    )
    assert res.status_code == 200
    res = await client.delete(
        f"/api/v1/servers/{SERVER_ID}/versioning/secrets/DB_PASSWORD",
        headers=header,
    )
    assert res.status_code == 200
    res = await client.delete(
        f"/api/v1/servers/{SERVER_ID}/versioning/secrets/DB_PASSWORD",
        headers=header,
    )
    assert res.status_code == 404


# ---------- new tests ----------

@pytest.mark.asyncio
async def test_permissions_403_insufficient(client: AsyncClient, advanced_server, created_user):
    root, admin_header = advanced_server
    read_header = await _seed_api_key_header(
        client, created_user["user_id"], ["server:version:read"]
    )
    # unauth
    res = await client.post(
        f"/api/v1/servers/{SERVER_ID}/versioning/commits",
        json={"message": "x", "branch_name": "feat"},
    )
    assert res.status_code == 401
    # insufficient
    res = await client.post(
        f"/api/v1/servers/{SERVER_ID}/versioning/commits",
        json={"message": "x", "branch_name": "feat"},
        headers=read_header,
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_native_git_commit_history_merge_diff_and_tags(client: AsyncClient, advanced_server):
    root, header = advanced_server
    # edit class B file on feat
    res = await client.put(
        f"/api/v1/servers/{SERVER_ID}/files/content",
        params={"branch": "feat", "path": "config/app.yml"},
        json={"content": "enabled: false\n"},
        headers=header,
    )
    assert res.status_code == 200
    # commit
    res = await client.post(
        f"/api/v1/servers/{SERVER_ID}/versioning/commits",
        json={"message": "feat change", "branch_name": "feat"},
        headers=header,
    )
    assert res.status_code in (200, 201), res.text
    # history
    res = await client.get(
        f"/api/v1/servers/{SERVER_ID}/versioning/branches/feat/history",
        headers=header,
    )
    assert res.status_code == 200
    assert len(res.json()) >= 1
    commits_feat = res.json()
    feat_commit = commits_feat[0]["id"]
    # commits?branch=feat
    res = await client.get(
        f"/api/v1/servers/{SERVER_ID}/versioning/commits",
        params={"branch": "feat"},
        headers=header,
    )
    assert res.status_code == 200
    assert len(res.json()) >= 1
    # merge without force -> 409 (protected main)
    res = await client.post(
        f"/api/v1/servers/{SERVER_ID}/versioning/commits/merge",
        json={
            "target_branch_name": "main",
            "source_branch_name": "feat",
            "message": "merge feat",
        },
        headers=header,
    )
    assert res.status_code == 409
    # merge with bypass -> 201
    res = await client.post(
        f"/api/v1/servers/{SERVER_ID}/versioning/commits/merge",
        json={
            "target_branch_name": "main",
            "source_branch_name": "feat",
            "message": "merge feat",
            "force_bypass_protection": True,
        },
        headers=header,
    )
    assert res.status_code in (200, 201), res.text
    # main commit id from branches/main/history
    res = await client.get(
        f"/api/v1/servers/{SERVER_ID}/versioning/branches/main/history",
        headers=header,
    )
    assert res.status_code == 200
    main_commit = res.json()[0]["id"] if res.json() else feat_commit
    # diff
    res = await client.get(
        f"/api/v1/servers/{SERVER_ID}/versioning/commits/diff",
        params={"from": feat_commit, "to": main_commit},
        headers=header,
    )
    assert res.status_code == 200
    # tags
    res = await client.post(
        f"/api/v1/servers/{SERVER_ID}/versioning/tags",
        json={"name": "v1", "commit_id": main_commit},
        headers=header,
    )
    assert res.status_code in (200, 201), res.text
    res = await client.get(
        f"/api/v1/servers/{SERVER_ID}/versioning/tags",
        headers=header,
    )
    assert res.status_code == 200
    assert any(t["name"] == "v1" for t in res.json())


@pytest.mark.asyncio
async def test_refresh_rollback_from_completed_and_confirm(client: AsyncClient, advanced_server):
    root, header = advanced_server
    import base64
    import shutil
    import zipfile

    _boot_class = base64.b64decode(
        "yv66vgAAAD0ALAoAAgADBwAEDAAFAAYBABBqYXZhL2xhbmcvT2JqZWN0AQAGPGluaXQ+AQADKClWCQAIAAkHAAoMAAsADAEAEGphdmEvbGFuZy9TeXN0ZW0BAANvdXQBABVMamF2YS9pby9QcmludFN0cmVhbTsIAA4BACJEb25lICgwLjFzKSEgRm9yIGhlbHAsIHR5cGUgImhlbHAiCgAQABEHABIMABMAFAEAE2phdmEvaW8vUHJpbnRTdHJlYW0BAAdwcmludGxuAQAVKExqYXZhL2xhbmcvU3RyaW5nOylWCgAQABYMABcABgEABWZsdXNoBQAAAAAAAOpgCgAbABwHAB0MAB4AHwEAEGphdmEvbGFuZy9UaHJlYWQBAAVzbGVlcAEABChKKVYHACEBAARCb290AQAEQ29kZQEAD0xpbmVOdW1iZXJUYWJsZQEABG1haW4BABYoW0xqYXZhL2xhbmcvU3RyaW5nOylWAQANU3RhY2tNYXBUYWJsZQEACkV4Y2VwdGlvbnMHACkBABNqYXZhL2xhbmcvRXhjZXB0aW9uAQAKU291cmNlRmlsZQEACUJvb3QuamF2YQAhACAAAgAAAAAAAgABAAUABgABACIAAAAdAAEAAQAAAAUqtwABsQAAAAEAIwAAAAYAAQAAAAEACQAkACUAAgAiAAAAQAACAAEAAAAXsgAHEg22AA+yAAe2ABUUABi4ABqn//oAAAACACMAAAAOAAMAAAADAAgABAAOAAYAJgAAAAMAAQ4AJwAAAAQAAQAoAAEAKgAAAAIAKw=="
    )
    with zipfile.ZipFile(root / "server.jar", "w") as zf:
        zf.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\nMain-Class: Boot\n\n")
        zf.writestr("Boot.class", _boot_class)
    (root / "server.properties").write_text(
        "motd=Hello\nserver-port=29965\nlevel-name=world\ngamemode=survival\n",
        encoding="utf-8",
    )
    # ensure docker provider
    async with database.session_factory() as session:
        srv = await session.get(ServerModel, SERVER_ID)
        srv.provider = "docker"
        await session.commit()
    from app.modules.versioning.application.lockfile_service import LockfileService

    layout = ensure_host_state_layout()
    LockfileService(layout).write(SERVER_ID, _empty_lockfile())
    # clean staging/prev
    shutil.rmtree(Path(str(root) + ".staging"), ignore_errors=True)
    shutil.rmtree(Path(str(root) + ".prev"), ignore_errors=True)

    res = await client.post(
        f"/api/v1/servers/{SERVER_ID}/versioning/refresh",
        json={"retention_policy": "until_confirm"},
        headers=header,
    )
    assert res.status_code == 200, res.text
    journal_id = res.json().get("journal_id")

    res = await client.get(
        f"/api/v1/servers/{SERVER_ID}/versioning/refresh",
        headers=header,
    )
    assert res.status_code == 200
    assert res.json()["latest_journal"]["phase"] == "COMPLETED"
    assert res.json()["can_confirm_upgrade"] is True
    assert res.json()["can_rollback"] is True

    # rollback from completed
    res = await client.post(
        f"/api/v1/servers/{SERVER_ID}/versioning/rollback",
        json={"journal_id": journal_id},
        headers=header,
    )
    assert res.status_code == 200, res.text

    # second refresh for confirm
    shutil.rmtree(Path(str(root) + ".staging"), ignore_errors=True)
    shutil.rmtree(Path(str(root) + ".prev"), ignore_errors=True)
    res = await client.post(
        f"/api/v1/servers/{SERVER_ID}/versioning/refresh",
        json={"retention_policy": "until_confirm"},
        headers=header,
    )
    assert res.status_code == 200, res.text
    journal_id2 = res.json().get("journal_id")

    res = await client.post(
        f"/api/v1/servers/{SERVER_ID}/versioning/upgrade/confirm",
        json={"journal_id": journal_id2},
        headers=header,
    )
    assert res.status_code == 200, res.text
    assert res.json()["phase"] == "UPGRADE_CONFIRMED"

    # release pins on rolled-back journal
    res = await client.post(
        f"/api/v1/servers/{SERVER_ID}/versioning/refresh/release-pins",
        json={"journal_id": journal_id},
        headers=header,
    )
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_settings_retention_normalization(client: AsyncClient, advanced_server):
    root, header = advanced_server
    res = await client.get(
        f"/api/v1/servers/{SERVER_ID}/versioning/settings",
        headers=header,
    )
    assert res.status_code == 200
    assert res.json()["previous_tree_retention"] == "until_health_gate"

    for raw, expected in [( "until_confirm", "until_confirm"), (24, "24h"), ("48h", "48h")]:
        res = await client.put(
            f"/api/v1/servers/{SERVER_ID}/versioning/settings",
            json={"previous_tree_retention": raw},
            headers=header,
        )
        assert res.status_code == 200, res.text
        assert res.json()["previous_tree_retention"] == expected

    for bad in (169, "invalid"):
        res = await client.put(
            f"/api/v1/servers/{SERVER_ID}/versioning/settings",
            json={"previous_tree_retention": bad},
            headers=header,
        )
        assert res.status_code == 422


@pytest.mark.asyncio
async def test_live_state_rcon_flock_and_guards(client: AsyncClient, advanced_server, monkeypatch):
    root, header = advanced_server

    # list contains dynamic? at least whitelist
    res = await client.get(
        f"/api/v1/servers/{SERVER_ID}/files/live-state",
        headers=header,
    )
    assert res.status_code == 200
    paths = [i["path"] for i in res.json()["items"]]
    assert "/whitelist.json" in paths

    # content
    res = await client.get(
        f"/api/v1/servers/{SERVER_ID}/files/live-state/content",
        params={"path": "/whitelist.json"},
        headers=header,
    )
    assert res.status_code == 200
    res = await client.get(
        f"/api/v1/servers/{SERVER_ID}/files/live-state/content",
        params={"path": "/server.properties"},
        headers=header,
    )
    assert res.status_code == 403
    res = await client.get(
        f"/api/v1/servers/{SERVER_ID}/files/live-state/content",
        params={"path": "/.env"},
        headers=header,
    )
    assert res.status_code in (403, 422)

    # session.lock flock 409
    world = root / "world"
    world.mkdir(exist_ok=True)
    lock = world / "session.lock"
    lock.write_bytes(b"")
    import fcntl

    fh = open(lock, "rb")  # noqa: SIM115
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        res = await client.put(
            f"/api/v1/servers/{SERVER_ID}/files/live-state/content",
            json={"path": "/whitelist.json", "content": "[]\n"},
            headers=header,
        )
        assert res.status_code == 409
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()

    # STARTING -> 409
    async with database.session_factory() as session:
        srv = await session.get(ServerModel, SERVER_ID)
        srv.status = "STARTING"
        await session.commit()
    res = await client.put(
        f"/api/v1/servers/{SERVER_ID}/files/live-state/content",
        json={"path": "/whitelist.json", "content": "[]\n"},
        headers=header,
    )
    assert res.status_code == 409
    # reset status
    async with database.session_factory() as session:
        srv = await session.get(ServerModel, SERVER_ID)
        srv.status = "STOPPED"
        await session.commit()

    # RUNNING RCON success
    class FakeProv:
        def __init__(self):
            self.calls = []

        async def execute_command(self, _handle, cmd):
            self.calls.append(cmd)
            return "ok"

    fake = FakeProv()

    def fake_get(_name):
        return fake

    from app.modules.server.infrastructure import providers as provmod

    monkeypatch.setattr(provmod.provider_factory, "get", fake_get)

    async with database.session_factory() as session:
        srv = await session.get(ServerModel, SERVER_ID)
        srv.status = "RUNNING"
        await session.commit()

    res = await client.put(
        f"/api/v1/servers/{SERVER_ID}/files/live-state/content",
        json={"path": "/whitelist.json", "content": "[\"x\"]\n"},
        headers=header,
    )
    assert res.status_code == 200, res.text
    assert res.json()["rcon_flushed"] is True
    assert res.json()["rcon_reloaded"] is True
    assert res.json()["reload_command"] == "whitelist reload"
    assert "save-all flush" in fake.calls
    assert "whitelist reload" in fake.calls

    # flush-fail -> 409 no disk change
    class FailProv:
        async def execute_command(self, _handle, cmd):
            if cmd == "save-all flush":
                raise RuntimeError("boom")
            return "ok"

    fail_fake = FailProv()

    def fail_get(_name):
        return fail_fake

    monkeypatch.setattr(provmod.provider_factory, "get", fail_get)
    target = root / "whitelist.json"
    target.write_text("[\"x\"]\n", encoding="utf-8")
    before2 = target.read_text()
    res = await client.put(
        f"/api/v1/servers/{SERVER_ID}/files/live-state/content",
        json={"path": "/whitelist.json", "content": "[\"y\"]\n"},
        headers=header,
    )
    assert res.status_code == 409
    assert target.read_text() == before2

    # arbitrary reload_command -> 422
    monkeypatch.setattr(provmod.provider_factory, "get", fake_get)
    res = await client.put(
        f"/api/v1/servers/{SERVER_ID}/files/live-state/content",
        json={
            "path": "/whitelist.json",
            "content": "[\"z\"]\n",
            "reload_command": "op attacker",
        },
        headers=header,
    )
    assert res.status_code == 422

    # reset status
    async with database.session_factory() as session:
        srv = await session.get(ServerModel, SERVER_ID)
        srv.status = "STOPPED"
        await session.commit()


@pytest.mark.asyncio
async def test_class_c_snapshots_and_dynamic_reset(client: AsyncClient, advanced_server):
    root, header = advanced_server

    # create snapshot
    res = await client.post(
        f"/api/v1/servers/{SERVER_ID}/versioning/class-c/snapshots",
        json={"pinned": False},
        headers=header,
    )
    assert res.status_code in (200, 201), res.text
    snap_id = res.json()["snapshot_id"]

    # list
    res = await client.get(
        f"/api/v1/servers/{SERVER_ID}/versioning/class-c/snapshots",
        headers=header,
    )
    assert res.status_code == 200
    assert any(s["snapshot_id"] == snap_id for s in res.json())

    # restore while running -> 409
    async with database.session_factory() as session:
        srv = await session.get(ServerModel, SERVER_ID)
        srv.status = "RUNNING"
        await session.commit()
    res = await client.post(
        f"/api/v1/servers/{SERVER_ID}/versioning/class-c/snapshots/{snap_id}/restore",
        headers=header,
    )
    assert res.status_code == 409
    async with database.session_factory() as session:
        srv = await session.get(ServerModel, SERVER_ID)
        srv.status = "STOPPED"
        await session.commit()

    # restore while stopped -> 200
    res = await client.post(
        f"/api/v1/servers/{SERVER_ID}/versioning/class-c/snapshots/{snap_id}/restore",
        headers=header,
    )
    assert res.status_code == 200

    # pinned snapshot delete -> 409
    res = await client.post(
        f"/api/v1/servers/{SERVER_ID}/versioning/class-c/snapshots",
        json={"pinned": True},
        headers=header,
    )
    assert res.status_code in (200, 201)
    pinned_id = res.json()["snapshot_id"]
    res = await client.delete(
        f"/api/v1/servers/{SERVER_ID}/versioning/class-c/snapshots/{pinned_id}",
        headers=header,
    )
    assert res.status_code == 409

    # unpinned delete -> 200
    res = await client.delete(
        f"/api/v1/servers/{SERVER_ID}/versioning/class-c/snapshots/{snap_id}",
        headers=header,
    )
    assert res.status_code == 200

    # dynamic list
    res = await client.get(
        f"/api/v1/servers/{SERVER_ID}/versioning/class-c/dynamic",
        headers=header,
    )
    assert res.status_code == 200

    # reset invalid path -> 422
    res = await client.post(
        f"/api/v1/servers/{SERVER_ID}/versioning/class-c/dynamic/reset",
        json={"path": "../evil"},
        headers=header,
    )
    assert res.status_code == 422

    # reset valid path -> 200
    res = await client.post(
        f"/api/v1/servers/{SERVER_ID}/versioning/class-c/dynamic/reset",
        json={"path": "config/app.yml"},
        headers=header,
    )
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_secrets_file_replacement_and_metadata_fields(client: AsyncClient, advanced_server):
    root, header = advanced_server
    target = WORKTREE / "config" / "paper-global.yml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("db-password: supersecret\n", encoding="utf-8")
    res = await client.post(
        f"/api/v1/servers/{SERVER_ID}/versioning/secrets/extract",
        json={
            "branch": "feat",
            "path": "config/paper-global.yml",
            "key_name": "DB_PASSWORD",
            "secret_value": "supersecret",
        },
        headers=header,
    )
    assert res.status_code in (200, 201), res.text
    assert "supersecret" not in (WORKTREE / "config" / "paper-global.yml").read_text()
    assert "${ONX_SECRET_DB_PASSWORD}" in (WORKTREE / "config" / "paper-global.yml").read_text()

    res = await client.get(
        f"/api/v1/servers/{SERVER_ID}/versioning/secrets",
        headers=header,
    )
    assert res.status_code == 200
    body = res.text
    assert "supersecret" not in body
    for item in res.json():
        assert "ciphertext" not in item
        assert "plaintext" not in item
        assert "key_name" in item
        assert "placeholder" in item


@pytest.mark.asyncio
async def test_live_state_world_writable_false_and_content_error_codes(
    client: AsyncClient, advanced_server
):
    import uuid

    from app.modules.versioning.infrastructure.models import ServerDynamicClassCModel

    root, header = advanced_server
    # Add a world/* file to dynamic Class C: list_live_state must mark writable=False
    # to align with write_live_state_content's world/* 403 guard.
    world_dir = root / "world"
    world_dir.mkdir(parents=True, exist_ok=True)
    (world_dir / "custom.json").write_text('{"ok": true}\n', encoding="utf-8")
    async with database.session_factory() as session:
        session.add(
            ServerDynamicClassCModel(
                id=str(uuid.uuid4()),
                server_id=SERVER_ID,
                relpath="world/custom.json",
                reason="test",
            )
        )
        await session.commit()

    res = await client.get(
        f"/api/v1/servers/{SERVER_ID}/files/live-state",
        params={"path": "/world"},
        headers=header,
    )
    assert res.status_code == 200, res.text
    by_path = {item["path"]: item for item in res.json()["items"]}
    assert "/world/custom.json" in by_path
    assert by_path["/world/custom.json"]["writable"] is False

    # Symlink escape in read_live_state_content -> 403
    outside = root.parent / "outside-secret.json"
    outside.write_text('{"secret": 1}\n', encoding="utf-8")
    wl = root / "whitelist.json"
    wl.unlink()
    os.symlink(outside, wl)
    res_sym = await client.get(
        f"/api/v1/servers/{SERVER_ID}/files/live-state/content",
        params={"path": "/whitelist.json"},
        headers=header,
    )
    assert res_sym.status_code == 403

    # Directory target in read_live_state_content -> 400
    wl.unlink()
    wl.mkdir()
    res_dir = await client.get(
        f"/api/v1/servers/{SERVER_ID}/files/live-state/content",
        params={"path": "/whitelist.json"},
        headers=header,
    )
    assert res_dir.status_code == 400
