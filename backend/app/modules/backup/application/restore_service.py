from __future__ import annotations

import logging
import os
import shutil
import tarfile
import tempfile
from io import BytesIO
from typing import TYPE_CHECKING

from app.api.deps import build_backup_encryption, build_storage_backend
from app.core.config import ConfigFactory
from app.core.identity import IDENTITY
from app.core.persistence.db import database
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.shared.value_objects import BackupJobId, ServerId
from app.services.backup_orchestrator import CONFIG_FILES

if TYPE_CHECKING:
    from app.modules.storage.base import StorageBackend
    from app.modules.storage.encryption import BackupEncryption

logger = logging.getLogger(__name__)


class RestoreError(Exception):
    """Raised when a restore cannot be safely applied."""


def _dimension_names(base_world: str) -> tuple[str, ...]:
    return (base_world, f"{base_world}_nether", f"{base_world}_the_end")


async def _load_job_storage(backup_id: BackupJobId) -> tuple[str, int, str]:
    async with database.session_factory() as session:
        repo = SQLBackupRepository(session)
        job = await repo.get_job(backup_id)
        if not job.storage_path:
            raise RestoreError(f"Backup {backup_id} has no stored artifact path")
        return job.storage_path, job.size_bytes, job.checksum


async def perform_safe_restore(
    backup_id: BackupJobId,
    server_dir: str,
    base_world: str = "world",
    storage: StorageBackend | None = None,
    encryption: BackupEncryption | None = None,
) -> list[str]:
    """Decrypt, verify and atomically apply the top-level entries present in a backup archive.

    The archive is decrypted and fully extracted to a temp directory (never the live
    server dir). For each dimension folder / plugins folder that exists in the extract,
    the corresponding live folder is atomically swapped in. Config files present in the
    extract are replaced at the file level. Playerdata pulled into the
    ``mcs_playerdata/<dim>/playerdata`` namespace is swapped onto only the live
    ``<dim>/playerdata`` subfolder. Live paths absent from the archive are left
    completely untouched. Returns the names of the replaced items.
    """
    settings = ConfigFactory.global_settings()
    storage = storage or build_storage_backend(settings)
    encryption = encryption or build_backup_encryption(settings.backup_encryption_key_path)

    storage_path, recorded_size, recorded_checksum = await _load_job_storage(backup_id)

    encrypted = await storage.read(storage_path)
    if not encrypted:
        raise RestoreError(f"Backup artifact missing at {storage_path}")
    if len(encrypted) != recorded_size:
        raise RestoreError(
            f"Backup {backup_id} size mismatch: recorded {recorded_size}, got {len(encrypted)}",
        )
    if encryption.checksum(encrypted) != recorded_checksum:
        raise RestoreError(f"Backup {backup_id} checksum mismatch — refusing to restore")

    plaintext = encryption.decrypt(encrypted)

    # Stage the extraction under server_dir's parent so the atomic directory swap
    # (os.replace inside _atomic_replace_dir) never crosses a mount boundary. The
    # OS temp dir (/tmp) is frequently a different filesystem (e.g. tmpfs) than
    # the server dir, and a cross-device rename fails with OSError EXDEV. A
    # sibling of server_dir is guaranteed to share its filesystem.
    staging_parent = os.path.dirname(os.path.abspath(server_dir))
    os.makedirs(staging_parent, exist_ok=True)
    temp_dir = tempfile.mkdtemp(prefix=f"{IDENTITY.temp_prefix_new}restore-", dir=staging_parent)
    try:
        extract_dir = os.path.join(temp_dir, "extract")
        os.makedirs(extract_dir, exist_ok=True)
        with tarfile.open(fileobj=BytesIO(plaintext), mode="r:gz") as tar:
            tar.extractall(extract_dir)

        restored_items: list[str] = []

        # 1. Whole dimension folders + plugins folder (same atomic dir swap).
        top_level_dirs = list(_dimension_names(base_world)) + ["plugins"]
        for name in top_level_dirs:
            src = os.path.join(extract_dir, name)
            if not os.path.isdir(src):
                continue
            _atomic_replace_dir(src, os.path.join(server_dir, name))
            restored_items.append(name)

        # 2. Config files at the file level (same-dir temp write + os.replace).
        for name in CONFIG_FILES:
            src = os.path.join(extract_dir, name)
            if not os.path.isfile(src):
                continue
            _atomic_replace_file(src, os.path.join(server_dir, name))
            restored_items.append(name)

        # 3. Playerdata namespace: swap only the live <dim>/playerdata subfolder.
        for dim in _dimension_names(base_world):
            src = os.path.join(extract_dir, "mcs_playerdata", dim, "playerdata")
            if not os.path.isdir(src):
                continue
            live_dim = os.path.join(server_dir, dim)
            if not os.path.isdir(live_dim):
                continue
            _atomic_replace_dir(src, os.path.join(live_dim, "playerdata"))
            restored_items.append(f"playerdata:{dim}")
        return restored_items
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _atomic_replace_file(src: str, dst: str) -> None:
    """Replace a single file atomically without crossing filesystem boundaries.

    The extracted bytes are written to a temp file inside dst's directory (guaranteed
    same filesystem), then os.replace()d onto the target. Avoids the EXDEV risk of
    renaming directly across mounts (e.g. /tmp extract dir -> server dir).
    """
    parent = os.path.dirname(dst)
    os.makedirs(parent, exist_ok=True)
    tmp_path = os.path.join(parent, f".{os.path.basename(dst)}.{IDENTITY.temp_prefix_new}tmp")
    with open(src, "rb") as f:
        data = f.read()
    with open(tmp_path, "wb") as f:
        f.write(data)
    os.replace(tmp_path, dst)


def _atomic_replace_dir(src: str, dst: str) -> None:
    """Swap src into dst atomically, never leaving a half-written folder.

    The existing live folder (if any) is first moved aside to a sibling name, then the
    extracted folder is renamed into place. If the second rename fails the old folder is
    rolled back. Between the two renames dst is briefly absent but never half-written.
    """
    parent = os.path.dirname(dst)
    os.makedirs(parent, exist_ok=True)
    old_path = os.path.join(parent, f"{os.path.basename(dst)}.{IDENTITY.temp_prefix_new}old")
    if os.path.lexists(dst):
        os.replace(dst, old_path)
    try:
        os.replace(src, dst)
    except BaseException:
        if os.path.lexists(old_path):
            os.replace(old_path, dst)
        raise
    finally:
        if os.path.lexists(old_path):
            shutil.rmtree(old_path, ignore_errors=True)


async def consume_pending_restore(
    server_id: str,
    server_dir: str,
    base_world: str = "world",
) -> str | None:
    """Apply a pending restore for server_id if one exists, then delete its row.

    Returns the applied backup_id, or None when no pending row existed. On failure the
    pending row is preserved so the intent is not silently lost.
    """
    async with database.session_factory() as session:
        repo = SQLBackupRepository(session)
        pending = await repo.get_pending_restore(ServerId(server_id))
        if pending is None:
            return None
        backup_id, _ = pending

    await perform_safe_restore(BackupJobId(backup_id), server_dir, base_world=base_world)

    async with database.session_factory() as session:
        repo = SQLBackupRepository(session)
        await repo.delete_pending_restore(ServerId(server_id))
        await session.commit()
    return backup_id
