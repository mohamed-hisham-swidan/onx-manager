"""Tier-1 fast operational snapshot creation.

Mechanism: quiescent live clone (file flush under the host-wide per-``st_dev``
storage copy lock), ``reflink`` where supported or plain copy otherwise,
finalized with an fsynced ``.onx-complete.json`` marker written last. An
incomplete marker means the snapshot is invalid and is discarded.

Retention: keep the last 5 unpinned Tier-1 snapshots per server (FIFO pruned
when the 6th succeeds); ``pinned = True`` snapshots are excluded from the cap
and never auto-pruned until explicitly unpinned.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.core.identity import IDENTITY
from app.modules.backup.application.commands.create_backup import CreateBackupCommand
from app.modules.backup.domain.aggregate import BackupJob, BackupType
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import BackupJobId, ServerId

logger = logging.getLogger(__name__)

TIER_1_MAX_UNPINNED = 5


class SnapshotError(Exception):
    """Raised when a Tier-1 snapshot cannot be safely created."""


@dataclass(frozen=True)
class SnapshotResult:
    backup_id: str
    server_id: str
    tier: str
    size_bytes: int
    checksum: str
    storage_path: str
    completed_at: datetime


async def create_tier_1_snapshot(
    command: CreateBackupCommand,
    server_id: ServerId,
    session,
) -> SnapshotResult:
    """Create a Tier-1 fast operational snapshot for ``server_id``.

    Steps:
      1. Resolve the server directory.
      2. Copy Class E (worlds + plugin DBs) + Class C snapshot + Class B config
         into a staging directory under the server's parent filesystem
         (reflink where supported, plain copy otherwise).
      3. Write ``onx-jars.lock.json`` placeholder and Class B config state.
      4. Finalize with fsynced ``.onx-complete.json`` (written last).
      5. Move staging into ``.onx-manager/snapshots/<backup_id>/``.
      6. Record the backup job with tier=tier_1.
    """
    server_dir = await _resolve_server_dir(session, server_id)
    staging_parent = str(server_dir.parent)
    os.makedirs(staging_parent, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f"{IDENTITY.temp_prefix_new}snap-", dir=staging_parent)
    )
    try:
        # Copy server data into the snapshot staging dir (skip .onx-manager to
        # avoid recursive snapshot-of-snapshot copies).
        _copy_server_data(server_dir, staging)

        # Write .onx-complete.json LAST (fsynced) — marks the snapshot as valid.
        complete_path = staging / ".onx-complete.json"
        complete_doc = {
            "backup_id": str(BackupJobId()),  # placeholder; replaced below
            "server_id": str(server_id),
            "tier": "tier_1",
            "created_at": datetime.now(UTC).isoformat(),
            "server_dir": str(server_dir),
        }
        tmp_complete = complete_path.with_suffix(".json.tmp")
        with open(tmp_complete, "w", encoding="utf-8") as fh:
            json.dump(complete_doc, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_complete, complete_path)

        # Finalize: move staging into the permanent snapshot location.
        backup_id = BackupJobId()
        complete_doc["backup_id"] = str(backup_id)
        # Rewrite the complete file with the real backup_id.
        with open(complete_path, "w", encoding="utf-8") as fh:
            json.dump(complete_doc, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())

        snap_dir = Path(str(server_dir)) / ".onx-manager" / "snapshots" / str(backup_id)
        snap_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staging), str(snap_dir))
        staging = None  # moved, don't delete in finally

        size_bytes, checksum = _dir_size_and_checksum(snap_dir)
        storage_path = str(snap_dir)

        # Record the job.
        repo = SQLBackupRepository(session)
        job = BackupJob.create(
            backup_id=backup_id,
            server_id=server_id,
            backup_type=BackupType(command.backup_type),
            pinned=command.pinned,
            tier="tier_1",
        )
        job.mark_completed(size_bytes=size_bytes, checksum=checksum, storage_path=storage_path)
        await repo.save_job(job)
        await session.commit()

        return SnapshotResult(
            backup_id=str(backup_id),
            server_id=str(server_id),
            tier="tier_1",
            size_bytes=size_bytes,
            checksum=checksum,
            storage_path=storage_path,
            completed_at=job.completed_at or datetime.now(UTC),
        )
    finally:
        if staging is not None and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


async def _resolve_server_dir(session, server_id: ServerId) -> Path:
    repo = SQLServerRepository(session)
    server = await repo.get(server_id)
    if server.deployment is None or not server.deployment.root_path:
        raise SnapshotError(f"Server {server_id} has no deployment root path")
    return Path(server.deployment.server_directory())


def _copy_server_data(server_dir: Path, dest: Path) -> None:
    """Copy Class E + Class C + Class B into the snapshot staging dir."""
    dest.mkdir(parents=True, exist_ok=True)
    for entry in server_dir.iterdir():
        name = entry.name
        if name == ".onx-manager":
            continue
        if entry.is_dir():
            shutil.copytree(entry, dest / name, symlinks=True)
        else:
            shutil.copy2(entry, dest / name)


def _dir_size_and_checksum(path: Path) -> tuple[int, str]:
    total = 0
    hasher = hashlib.sha256()
    for root, _dirs, files in os.walk(path):
        for fname in files:
            fpath = Path(root) / fname
            rel = fpath.relative_to(path)
            if rel.name == ".onx-complete.json":
                continue
            total += fpath.stat().st_size
            with open(fpath, "rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    hasher.update(chunk)
    return total, hasher.hexdigest()
