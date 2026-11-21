from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.core.exceptions import InsufficientStorageError
from app.modules.backup.infrastructure.tier1_snapshot import (
    SAVE_OFF_MARKER_FILENAME,
    TIER1_MARKER_FILENAME,
    Tier1SnapshotError,
    collect_tier1_gc_roots,
    create_tier1_snapshot,
    discard_incomplete_snapshots,
    recover_save_off_state,
    validate_tier1_complete_marker,
)


def _seed_server(server_dir: Path) -> None:
    (server_dir / "world").mkdir(parents=True, exist_ok=True)
    (server_dir / "world" / "level.dat").write_bytes(b"level-data")
    (server_dir / "ops.json").write_text('[{"name":"alice"}]', encoding="utf-8")
    (server_dir / "server.properties").write_text("motd=Hello\n", encoding="utf-8")
    (server_dir / "onx-jars.lock.json").write_text(
        json.dumps({"files": [{"path": "mods/a.jar", "sha256": "a" * 64, "origin": "modrinth"}]}),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_tier1_quiescent_snapshot_and_marker_and_gc_roots(tmp_path: Path) -> None:
    server_dir = tmp_path / "srv"
    snaps_root = tmp_path / "snaps"
    _seed_server(server_dir)

    rcon_cmds: list[str] = []

    async def fake_rcon(cmd: str) -> str:
        rcon_cmds.append(cmd)
        if cmd == "save-all flush":
            (server_dir / "world" / "level.dat").write_bytes(b"level-data-flushed")
        return "ok"

    res = await create_tier1_snapshot(
        server_id="srv-1",
        server_dir=server_dir,
        snapshots_root=snaps_root,
        backup_id="snap-1",
        is_running=True,
        rcon_send=fake_rcon,
        force_no_reflink=True,
    )
    assert rcon_cmds == ["save-off", "save-all flush", "save-on"]
    assert res.quiesced is True
    assert not (server_dir / ".onx-manager" / SAVE_OFF_MARKER_FILENAME).exists()
    snap_dir = Path(res.snapshot_dir)
    assert (snap_dir / "class_e" / "world" / "level.dat").read_bytes() == b"level-data-flushed"
    marker = validate_tier1_complete_marker(snap_dir)
    assert marker["backup_id"] == "snap-1"
    assert collect_tier1_gc_roots(snaps_root / "srv-1") == {"a" * 64}


@pytest.mark.asyncio
async def test_tier1_save_on_guaranteed_on_failure_and_startup_recovery(tmp_path: Path) -> None:
    server_dir = tmp_path / "srv"
    snaps_root = tmp_path / "snaps"
    _seed_server(server_dir)
    rcon_cmds: list[str] = []

    async def fail_on_flush(cmd: str) -> str:
        rcon_cmds.append(cmd)
        if cmd == "save-all flush":
            raise RuntimeError("flush boom")
        return "ok"

    with pytest.raises(RuntimeError, match="flush boom"):
        await create_tier1_snapshot(
            server_id="srv-1",
            server_dir=server_dir,
            snapshots_root=snaps_root,
            backup_id="snap-fail",
            is_running=True,
            rcon_send=fail_on_flush,
            force_no_reflink=True,
        )
    assert rcon_cmds == ["save-off", "save-all flush", "save-on"]

    # Startup save-off recovery helper
    meta = server_dir / ".onx-manager"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / SAVE_OFF_MARKER_FILENAME).write_text('{"rcon_save_off_active": true}', encoding="utf-8")
    rec_cmds: list[str] = []

    async def rec_rcon(cmd: str) -> str:
        rec_cmds.append(cmd)
        return "ok"

    assert await recover_save_off_state(meta, rec_rcon) is True
    assert rec_cmds == ["save-on"]
    assert not (meta / SAVE_OFF_MARKER_FILENAME).exists()


@pytest.mark.asyncio
async def test_tier1_space_check_and_incomplete_marker_discard(tmp_path: Path) -> None:
    server_dir = tmp_path / "srv"
    snaps_root = tmp_path / "snaps"
    _seed_server(server_dir)

    with (
        patch(
            "app.modules.backup.infrastructure.tier1_snapshot.shutil.disk_usage",
            return_value=SimpleNamespace(free=1),
        ),
        pytest.raises(InsufficientStorageError),
    ):
        await create_tier1_snapshot(
            server_id="srv-1",
            server_dir=server_dir,
            snapshots_root=snaps_root,
            backup_id="snap-nospace",
        )

    incomplete = snaps_root / "srv-1" / "incomplete-1"
    incomplete.mkdir(parents=True, exist_ok=True)
    (incomplete / "class_e").mkdir()
    with pytest.raises(Tier1SnapshotError):
        validate_tier1_complete_marker(incomplete)
    assert TIER1_MARKER_FILENAME not in [p.name for p in incomplete.iterdir()]
    removed = discard_incomplete_snapshots(snaps_root / "srv-1")
    assert removed == ["incomplete-1"]
    assert not incomplete.exists()
