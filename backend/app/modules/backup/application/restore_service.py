from __future__ import annotations

import errno
import logging
import os
import shutil
import tarfile
import tempfile
import uuid
from typing import TYPE_CHECKING

from app.api.deps import build_backup_encryption, build_storage_backend
from app.core.config import ConfigFactory
from app.core.exceptions import InsufficientStorageError
from app.core.identity import IDENTITY
from app.core.persistence.db import database
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.shared.value_objects import BackupJobId, ServerId
from app.services.backup_orchestrator import CONFIG_FILES

if TYPE_CHECKING:
    from app.modules.storage.base import StorageBackend
    from app.modules.storage.encryption import BackupEncryption

logger = logging.getLogger(__name__)

# Class-E runtime JSONs that must survive a restore exactly as archived.
CLASS_E_JSON_FILES: tuple[str, ...] = (
    "ops.json",
    "whitelist.json",
    "banned-players.json",
    "banned-ips.json",
    "usercache.json",
)


class RestoreError(Exception):
    """Raised when a restore cannot be safely applied."""


def _dimension_names(base_world: str) -> tuple[str, ...]:
    return (base_world, f"{base_world}_nether", f"{base_world}_the_end")


def _level_name(server_dir: str, base_world: str) -> str:
    """Resolve ``level-name`` from server.properties when using the default world."""
    if base_world != "world":
        return base_world
    path = os.path.join(server_dir, "server.properties")
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                if key.strip() != "level-name":
                    continue
                name = value.strip()
                if (
                    name
                    and name not in (".", "..")
                    and "/" not in name
                    and "\\" not in name
                    and "\x00" not in name
                ):
                    return name
    except OSError:
        pass
    return "world"


def _ensure_extract_space(server_dir: str, tar: tarfile.TarFile) -> None:
    """Refuse extraction when the archive cannot fit on the target filesystem."""
    try:
        stats = os.statvfs(server_dir)
    except OSError:  # pragma: no cover - defensive
        return
    free_bytes = stats.f_bavail * stats.f_frsize
    needed = 0
    for member in tar.getmembers():
        if member.isfile():
            needed += member.size
        elif member.isdir():
            needed += 4096
    # Keep 5% headroom so replacement staging does not itself fill the disk.
    if needed and needed > int(free_bytes * 0.95):
        raise InsufficientStorageError(
            details={"needed_bytes": needed, "free_bytes": free_bytes}
        )


def _stash_path(dst: str, backup_dir: str) -> str:
    """Move an existing live path into the restore backup dir (same filesystem)."""
    os.makedirs(backup_dir, exist_ok=True)
    backup = os.path.join(
        backup_dir, f"{uuid.uuid4().hex}-{os.path.basename(dst)}"
    )
    os.replace(dst, backup)
    return backup


def _rollback_applied(applied: list[tuple[str, str | None]]) -> None:
    """Restore every already-replaced item after a mid-restore failure."""
    for dst, backup in reversed(applied):
        try:
            if os.path.isdir(dst) and not os.path.islink(dst):
                shutil.rmtree(dst)
            elif os.path.lexists(dst):
                os.unlink(dst)
        except OSError:
            logger.exception("Failed to remove partially restored path %s", dst)
        if backup is not None and os.path.lexists(backup):
            try:
                os.replace(backup, dst)
            except OSError:
                logger.exception("Failed to restore original path %s", dst)


async def _load_job_storage(backup_id: BackupJobId) -> tuple[str, int, str]:
    async with database.session_factory() as session:
        repo = SQLBackupRepository(session)
        job = await repo.get_job(backup_id)
        if not job.storage_path:
            raise RestoreError(f"Backup {backup_id} has no stored artifact path")
        return job.storage_path, job.size_bytes, job.checksum


def _safe_extract_tar(tar: tarfile.TarFile, target_dir: str) -> None:
    """Safely extract tar archive preventing directory traversal (tar slip / CVE-2007-4559)."""
    resolved_target = os.path.abspath(target_dir)
    for member in tar.getmembers():
        member_path = os.path.abspath(os.path.join(resolved_target, member.name))
        if os.path.commonpath([resolved_target, member_path]) != resolved_target:
            raise RestoreError(f"Path traversal detected in backup archive: {member.name}")
        if member.issym() or member.islnk():
            link_target = os.path.abspath(
                os.path.join(os.path.dirname(member_path), member.linkname)
            )
            if os.path.commonpath([resolved_target, link_target]) != resolved_target:
                raise RestoreError(
                    f"Symlink traversal detected in backup archive: "
                    f"{member.name} -> {member.linkname}"
                )

    if hasattr(tarfile, "data_filter"):
        tar.extractall(target_dir, filter="data")
    else:
        tar.extractall(target_dir)


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

    # Drop the encrypted buffer as soon as it has been decrypted so both copies
    # never sit in memory together.
    plaintext = encryption.decrypt(encrypted)
    del encrypted

    # Stage the extraction under server_dir's parent so the atomic directory swap
    # (os.replace inside _atomic_replace_dir) never crosses a mount boundary. The
    # OS temp dir (/tmp) is frequently a different filesystem (e.g. tmpfs) than
    # the server dir, and a cross-device rename fails with OSError EXDEV. A
    # sibling of server_dir is guaranteed to share its filesystem.
    staging_parent = os.path.dirname(os.path.abspath(server_dir))
    os.makedirs(staging_parent, exist_ok=True)
    temp_dir = tempfile.mkdtemp(prefix=f"{IDENTITY.temp_prefix_new}restore-", dir=staging_parent)
    try:
        archive_path = os.path.join(temp_dir, "backup.tar.gz")
        with open(archive_path, "wb") as handle:
            handle.write(plaintext)
        del plaintext

        extract_dir = os.path.join(temp_dir, "extract")
        os.makedirs(extract_dir, exist_ok=True)
        with tarfile.open(archive_path, mode="r:gz") as tar:
            _ensure_extract_space(server_dir, tar)
            _safe_extract_tar(tar, extract_dir)

        effective_base = _level_name(server_dir, base_world)
        backup_dir = os.path.join(temp_dir, "prev")
        applied: list[tuple[str, str | None]] = []
        restored_items: list[str] = []
        try:
            # 1. Whole dimension folders + plugins folder (same atomic dir swap).
            top_level_dirs = list(_dimension_names(effective_base)) + ["plugins"]
            for name in top_level_dirs:
                src = os.path.join(extract_dir, name)
                if not os.path.isdir(src):
                    continue
                dst = os.path.join(server_dir, name)
                backup = _atomic_replace_dir(src, dst, backup_dir)
                applied.append((dst, backup))
                restored_items.append(name)

            # 2. Config files and Class-E runtime JSONs at the file level.
            for name in dict.fromkeys((*CONFIG_FILES, *CLASS_E_JSON_FILES)):
                src = os.path.join(extract_dir, name)
                if not os.path.isfile(src):
                    continue
                dst = os.path.join(server_dir, name)
                backup = _atomic_replace_file(src, dst, backup_dir)
                applied.append((dst, backup))
                restored_items.append(name)

            # 3. Playerdata namespace: swap only the live <dim>/playerdata subfolder.
            for dim in _dimension_names(effective_base):
                src = os.path.join(extract_dir, "mcs_playerdata", dim, "playerdata")
                if not os.path.isdir(src):
                    continue
                live_dim = os.path.join(server_dir, dim)
                if not os.path.isdir(live_dim):
                    continue
                dst = os.path.join(live_dim, "playerdata")
                backup = _atomic_replace_dir(src, dst, backup_dir)
                applied.append((dst, backup))
                restored_items.append(f"playerdata:{dim}")
            return restored_items
        except OSError as exc:
            # Undo already-replaced items from temp_dir/prev so a mid-restore
            # ENOSPC never leaves the server half-restored.
            _rollback_applied(applied)
            if exc.errno == errno.ENOSPC:
                raise InsufficientStorageError(
                    details={"path": server_dir, "reason": "restore ran out of space"}
                ) from exc
            raise
    except OSError as exc:
        if exc.errno == errno.ENOSPC:
            raise InsufficientStorageError(
                details={"path": server_dir, "reason": "restore ran out of space"}
            ) from exc
        raise
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _atomic_replace_file(
    src: str, dst: str, backup_dir: str | None = None
) -> str | None:
    """Replace a single file atomically and retain the old file in ``backup_dir``.

    The extracted bytes are written to a temp file inside dst's directory (guaranteed
    same filesystem), then os.replace()d onto the target. Avoids the EXDEV risk of
    renaming directly across mounts (e.g. /tmp extract dir -> server dir). When
    ``backup_dir`` is omitted the old file is simply overwritten (legacy callers).
    """
    parent = os.path.dirname(dst)
    os.makedirs(parent, exist_ok=True)
    unique_id = uuid.uuid4().hex
    tmp_path = os.path.join(
        parent, f".{os.path.basename(dst)}.{IDENTITY.temp_prefix_new}{unique_id}.tmp"
    )
    shutil.copyfile(src, tmp_path)
    backup: str | None = None
    try:
        if backup_dir is not None and os.path.lexists(dst):
            backup = _stash_path(dst, backup_dir)
        os.replace(tmp_path, dst)
    except BaseException:
        if os.path.lexists(tmp_path):
            os.unlink(tmp_path)
        if backup is not None and os.path.lexists(backup) and not os.path.lexists(dst):
            os.replace(backup, dst)
        raise
    return backup


def _atomic_replace_dir(
    src: str, dst: str, backup_dir: str | None = None
) -> str | None:
    """Swap src into dst atomically and retain the old tree in ``backup_dir``.

    Stages src into dst's parent directory first (via shutil.move) to eliminate
    EXDEV (cross-device link) errors when src is in a temp directory on a different
    mount. Then performs an atomic swap within the same parent folder. When
    ``backup_dir`` is omitted the old tree is discarded after a successful swap
    (legacy callers).
    """
    parent = os.path.dirname(dst)
    os.makedirs(parent, exist_ok=True)
    unique_id = uuid.uuid4().hex
    temp_stage = os.path.join(
        parent, f".{os.path.basename(dst)}.{IDENTITY.temp_prefix_new}{unique_id}.stage"
    )
    if os.path.lexists(temp_stage):
        shutil.rmtree(temp_stage, ignore_errors=True)

    shutil.move(src, temp_stage)
    if backup_dir is None:
        old_path = os.path.join(
            parent, f".{os.path.basename(dst)}.{IDENTITY.temp_prefix_new}{unique_id}.old"
        )
        if os.path.lexists(old_path):
            shutil.rmtree(old_path, ignore_errors=True)
        try:
            if os.path.lexists(dst):
                os.replace(dst, old_path)
            try:
                os.replace(temp_stage, dst)
            except BaseException:
                if os.path.lexists(old_path):
                    os.replace(old_path, dst)
                raise
        finally:
            if os.path.lexists(temp_stage):
                shutil.rmtree(temp_stage, ignore_errors=True)
            if os.path.lexists(old_path):
                shutil.rmtree(old_path, ignore_errors=True)
        return None

    backup: str | None = None
    try:
        if os.path.lexists(dst):
            backup = _stash_path(dst, backup_dir)
        os.replace(temp_stage, dst)
    except BaseException:
        if os.path.lexists(temp_stage):
            shutil.rmtree(temp_stage, ignore_errors=True)
        if backup is not None and os.path.lexists(backup) and not os.path.lexists(dst):
            os.replace(backup, dst)
        raise
    return backup


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
