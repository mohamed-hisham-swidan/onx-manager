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
from app.core.persistence.db import database
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.shared.value_objects import BackupJobId, ServerId

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
    """Decrypt, verify and atomically apply dimension folders present in a backup archive.

    The archive is decrypted and fully extracted to a temp directory (never the live
    server dir). For each top-level dimension folder that exists in the extract, the
    corresponding live folder is atomically swapped in. Live dimension folders that are
    absent from the archive are left completely untouched. Returns the names of the
    dimension folders that were replaced.
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

    temp_dir = tempfile.mkdtemp(prefix="mcs-restore-")
    try:
        extract_dir = os.path.join(temp_dir, "extract")
        os.makedirs(extract_dir, exist_ok=True)
        with tarfile.open(fileobj=BytesIO(plaintext), mode="r:gz") as tar:
            tar.extractall(extract_dir)

        restored_dims: list[str] = []
        for dim in _dimension_names(base_world):
            src = os.path.join(extract_dir, dim)
            if not os.path.isdir(src):
                continue
            _atomic_replace_dir(src, os.path.join(server_dir, dim))
            restored_dims.append(dim)
        return restored_dims
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _atomic_replace_dir(src: str, dst: str) -> None:
    """Swap src into dst atomically, never leaving a half-written folder.

    The existing live folder (if any) is first moved aside to a sibling name, then the
    extracted folder is renamed into place. If the second rename fails the old folder is
    rolled back. Between the two renames dst is briefly absent but never half-written.
    """
    parent = os.path.dirname(dst)
    os.makedirs(parent, exist_ok=True)
    old_path = os.path.join(parent, f"{os.path.basename(dst)}.mcs-old")
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
