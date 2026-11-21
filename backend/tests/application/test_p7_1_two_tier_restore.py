from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.modules.backup.application.two_tier_restore import (
    TwoTierRestoreError,
    restore_tier1_snapshot,
    restore_tier2_archive,
)
from app.modules.backup.infrastructure.tier1_snapshot import create_tier1_snapshot
from app.modules.backup.infrastructure.tier2_archive import create_tier2_archive
from app.modules.storage.local import LocalStorage
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.vault_crypto import MasterKek


def _seed_server(server_dir: Path, cas: ArtifactCas) -> str:
    (server_dir / "world").mkdir(parents=True, exist_ok=True)
    (server_dir / "world" / "level.dat").write_bytes(b"original-world")
    (server_dir / "ops.json").write_text('[{"name":"orig"}]', encoding="utf-8")
    (server_dir / "server.properties").write_text("motd=Original\n", encoding="utf-8")
    (server_dir / "mods").mkdir(exist_ok=True)
    (server_dir / "mods" / "keep.jar").write_bytes(b"class-a-jar")
    user_sha = cas.put_bytes(b"user-jar-bytes")
    (server_dir / "onx-jars.lock.json").write_text(
        json.dumps({"files": [{"path": "mods/user.jar", "sha256": user_sha, "origin": "user"}]}),
        encoding="utf-8",
    )
    return user_sha


@pytest.mark.asyncio
async def test_tier1_and_tier2_restore_roundtrip_and_cas_repopulation(tmp_path: Path) -> None:
    server_dir = tmp_path / "srv"
    snaps_root = tmp_path / "snaps"
    cas = ArtifactCas(tmp_path / "cas")
    storage = LocalStorage(str(tmp_path / "backups"))
    kek = MasterKek(kek_version=1, key_bytes=b"\x55" * 32)
    user_sha = _seed_server(server_dir, cas)

    # Create Tier-1 + Tier-2 backups
    t1 = await create_tier1_snapshot(
        server_id="srv-1",
        server_dir=server_dir,
        snapshots_root=snaps_root,
        backup_id="t1-good",
    )
    t2 = await create_tier2_archive(
        server_id="srv-1",
        server_dir=server_dir,
        backup_id="t2-good",
        storage=storage,
        archive_format="tar.zst",
        include_cas_jars=True,
        kek=kek,
        cas=cas,
    )

    # Mutate live server
    (server_dir / "world" / "level.dat").write_bytes(b"corrupted-world")
    (server_dir / "ops.json").write_text("[]", encoding="utf-8")
    (server_dir / "server.properties").write_text("motd=Mutated\n", encoding="utf-8")

    # Restore Tier-1
    r1 = await restore_tier1_snapshot(
        server_id="srv-1",
        server_dir=server_dir,
        snapshot_dir=Path(t1.snapshot_dir),
        backup_id="t1-good",
    )
    assert r1.tier == "tier_1"
    assert (server_dir / "world" / "level.dat").read_bytes() == b"original-world"
    assert (server_dir / "mods" / "keep.jar").read_bytes() == b"class-a-jar"

    # Mutate again & restore Tier-2 into fresh CAS
    (server_dir / "world" / "level.dat").write_bytes(b"mutated-2")
    fresh_cas = ArtifactCas(tmp_path / "cas2")
    r2 = await restore_tier2_archive(
        server_id="srv-1",
        server_dir=server_dir,
        storage_path=t2.storage_path,
        backup_id="t2-good",
        storage=storage,
        expected_checksum=t2.checksum,
        kek=kek,
        cas=fresh_cas,
    )
    assert r2.tier == "tier_2"
    assert r2.cas_blobs_restored == 1
    assert fresh_cas.has(user_sha)
    assert (server_dir / "world" / "level.dat").read_bytes() == b"original-world"
    assert (server_dir / "server.properties").read_text(encoding="utf-8") == "motd=Original\n"


@pytest.mark.asyncio
async def test_tier2_restore_rejects_path_escape_wrong_kek_and_swap_rollback(tmp_path: Path) -> None:
    server_dir = tmp_path / "srv"
    cas = ArtifactCas(tmp_path / "cas")
    _seed_server(server_dir, cas)

    # 1. Path traversal archive
    evil_tar = tmp_path / "evil.tar.gz"
    with tarfile.open(evil_tar, "w:gz") as tf:
        info = tarfile.TarInfo(name="../escape.txt")
        info.size = 4
        tf.addfile(info, io.BytesIO(b"evil"))

    with pytest.raises(TwoTierRestoreError, match="Invalid path|unsafe|escape|Corrupt"):
        await restore_tier2_archive(
            server_id="srv-1",
            server_dir=server_dir,
            storage_path=str(evil_tar),
            backup_id="b-evil",
        )
    assert (server_dir / "world" / "level.dat").read_bytes() == b"original-world"
    assert not (tmp_path / "escape.txt").exists()

    # 2. Symlink archive entry
    sym_tar = tmp_path / "sym.tar.gz"
    with tarfile.open(sym_tar, "w:gz") as tf:
        info = tarfile.TarInfo(name="triad/class_e/world/link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tf.addfile(info)

    with pytest.raises(TwoTierRestoreError, match="unsafe link"):
        await restore_tier2_archive(
            server_id="srv-1",
            server_dir=server_dir,
            storage_path=str(sym_tar),
            backup_id="b-sym",
        )
    assert (server_dir / "world" / "level.dat").read_bytes() == b"original-world"

    # 3. Swap failure preserves live server cleanly
    snaps_root = tmp_path / "snaps"
    t1 = await create_tier1_snapshot(
        server_id="srv-1",
        server_dir=server_dir,
        snapshots_root=snaps_root,
        backup_id="t1-swapfail",
    )
    with (
        patch(
            "app.modules.backup.application.two_tier_restore.swap_directories",
            side_effect=OSError("disk error during swap"),
        ),
        pytest.raises(TwoTierRestoreError, match="disk error"),
    ):
        await restore_tier1_snapshot(
            server_id="srv-1",
            server_dir=server_dir,
            snapshot_dir=Path(t1.snapshot_dir),
            backup_id="t1-swapfail",
        )
    assert (server_dir / "world" / "level.dat").read_bytes() == b"original-world"
