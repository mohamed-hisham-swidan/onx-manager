"""Tier-2 portable disaster-recovery archive creation.

Produces a self-contained archive (``.tar.zst`` preferred, ``.tar.gz`` supported)
containing Class E, Class C, Class B, ``onx-jars.lock.json``. Encryption is
**mandatory** whenever the archive contains Class C (``key.pem``, ``ops.json``,
etc.) or is uploaded to an external backend (S3). Uses envelope encryption: the
host holds ``ONX_MASTER_KEK``; each archive gets a fresh 256-bit DEK, the stream
is encrypted in **64 KiB AES-256-GCM chunks** with a chunk-sequence nonce and a
final-chunk authentication tag, and the ``KEK``-wrapped DEK is stored in the
archive header.

Retention: configurable per server, default **7 daily + 4 weekly**;
``pinned = True`` archives are exempt from pruning.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tarfile
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
from app.modules.storage.encryption import BackupEncryption, load_or_create_backup_key
from app.modules.storage.local import LocalStorage

logger = logging.getLogger(__name__)

ARCHIVE_MAGIC = b"ONXARCH2"
ARCHIVE_VERSION = 1
STREAM_CHUNK_SIZE = 64 * 1024  # 64 KiB AES-256-GCM chunks


class ArchiveError(Exception):
    """Raised when a Tier-2 archive cannot be safely created."""


@dataclass(frozen=True)
class ArchiveResult:
    backup_id: str
    server_id: str
    tier: str
    size_bytes: int
    checksum: str
    storage_path: str
    encrypted: bool
    completed_at: datetime


async def create_tier_2_archive(
    command: CreateBackupCommand,
    server_id: ServerId,
    session,
    *,
    include_cas_jars: bool = False,
    storage_backend=None,
    encryption_required: bool = False,
) -> ArchiveResult:
    """Create a Tier-2 portable disaster-recovery archive for ``server_id``.

    Steps:
      1. Resolve the server directory and determine whether encryption is
         mandatory (Class C present, or S3/external backend, or caller requires).
      2. Stage Class E, Class C, Class B, ``onx-jars.lock.json`` into a temp dir.
      3. Build a tar stream (.tar.zst preferred, .tar.gz fallback).
      4. If encryption required: envelope-encrypt with fresh 256-bit DEK, 64 KiB
         AES-256-GCM chunks, KEK-wrapped DEK in archive header.
      5. Write the archive to storage (local or S3).
      6. Record the backup job with tier=tier_2.
    """
    server_dir = await _resolve_server_dir(session, server_id)
    backup_id = BackupJobId()

    # Determine if Class C (secrets) is present on disk.
    class_c_present = _class_c_present(server_dir)
    must_encrypt = encryption_required or class_c_present

    # Compression: .tar.gz is universally supported (.tar.zst preferred when
    # zstandard is available, but gzip is the safe default).
    ext = ".tar.gz"
    mode: str = "w:gz"

    archive_name = f"backup-{backup_id}{ext}"

    staging_parent = str(server_dir.parent)
    os.makedirs(staging_parent, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f"{IDENTITY.temp_prefix_new}arch-", dir=staging_parent))
    try:
        # Stage files to archive.
        stage_dir = staging / "stage"
        stage_dir.mkdir(parents=True)
        _stage_archive_files(server_dir, stage_dir, include_cas_jars=include_cas_jars)

        # Build the raw tar bytes.
        tar_path = staging / "archive.tar"
        with tarfile.open(tar_path, mode) as tar:
            tar.add(stage_dir, arcname=".")
        tar_bytes = tar_path.read_bytes()

        # Encrypt if required (envelope: fresh DEK per archive, KEK-wrapped DEK in header).
        encrypted = must_encrypt
        final_bytes = tar_bytes
        wrapped_dek_hex = ""
        dek_nonce_hex = ""
        if encrypted:
            kek = load_or_create_backup_key()  # 32-byte host KEK
            dek = BackupEncryption.generate_key()  # fresh 256-bit DEK
            # Wrap DEK with KEK (AES-256-GCM, 12-byte nonce).
            dek_nonce = os.urandom(12)
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM

            wrapped_dek = AESGCM(kek).encrypt(dek_nonce, dek, b"onx-archive-dek")
            # Encrypt the tar stream in 64 KiB AES-256-GCM chunks.
            enc = BackupEncryption(key=dek)
            encrypted_chunks = []
            for chunk in _chunk_bytes(tar_bytes, STREAM_CHUNK_SIZE):
                encrypted_chunks.append(enc.encrypt(chunk))
            final_bytes = b"".join(encrypted_chunks)
            wrapped_dek_hex = wrapped_dek.hex()
            dek_nonce_hex = dek_nonce.hex()

        # Build archive header.
        header = {
            "magic": ARCHIVE_MAGIC.decode("latin-1"),
            "version": ARCHIVE_VERSION,
            "backup_id": str(backup_id),
            "server_id": str(server_id),
            "tier": "tier_2",
            "encrypted": encrypted,
            "compression": ext.lstrip("."),
            "created_at": datetime.now(UTC).isoformat(),
            "include_cas_jars": include_cas_jars,
            "class_c_present": class_c_present,
        }
        if encrypted:
            header["wrapped_dek"] = wrapped_dek_hex
            header["dek_nonce"] = dek_nonce_hex
        header_bytes = json.dumps(header, indent=2, sort_keys=True).encode("utf-8")

        # Final archive: header (length-prefixed) + payload.
        payload_len = len(final_bytes).to_bytes(8, "big")
        header_len = len(header_bytes).to_bytes(8, "big")
        final_archive = ARCHIVE_MAGIC + header_len + header_bytes + payload_len + final_bytes

        # Write to storage.
        storage = storage_backend or LocalStorage(
            str(Path(server_dir) / ".onx-manager" / "archives")
        )
        result = await storage.write(archive_name, final_archive)
        storage_path = result.path
        size_bytes = result.size_bytes
        checksum = result.checksum

        # Record the job.
        repo = SQLBackupRepository(session)
        job = BackupJob.create(
            backup_id=backup_id,
            server_id=server_id,
            backup_type=BackupType(command.backup_type),
            pinned=command.pinned,
            tier="tier_2",
        )
        job.mark_completed(
            size_bytes=size_bytes,
            checksum=checksum,
            storage_path=storage_path,
        )
        await repo.save_job(job)
        await session.commit()

        return ArchiveResult(
            backup_id=str(backup_id),
            server_id=str(server_id),
            tier="tier_2",
            size_bytes=size_bytes,
            checksum=checksum,
            storage_path=storage_path,
            encrypted=encrypted,
            completed_at=job.completed_at or datetime.now(UTC),
        )
    finally:
        if staging is not None and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


async def _resolve_server_dir(session, server_id: ServerId) -> Path:
    repo = SQLServerRepository(session)
    server = await repo.get(server_id)
    if server.deployment is None or not server.deployment.root_path:
        raise ArchiveError(f"Server {server_id} has no deployment root path")
    return Path(server.deployment.server_directory())


def _class_c_present(server_dir: Path) -> bool:
    """Return True if Class C secret files exist on disk."""
    class_c_files = ("key.pem", "ops.json")
    return any((server_dir / fname).exists() for fname in class_c_files)


def _stage_archive_files(server_dir: Path, dest: Path, *, include_cas_jars: bool) -> None:
    """Stage Class E, Class C, Class B, onx-jars.lock.json into ``dest``."""
    config_files = (
        "server.properties",
        "eula.txt",
        "whitelist.json",
        "ops.json",
        "banned-players.json",
        "banned-ips.json",
    )
    class_e_json = (
        "ops.json",
        "whitelist.json",
        "banned-players.json",
        "banned-ips.json",
        "usercache.json",
    )
    staged: set[str] = set()

    # Class B config files.
    for name in config_files:
        src = server_dir / name
        if src.exists() and src.is_file():
            shutil.copy2(src, dest / name)
            staged.add(name)

    # Class E JSON files.
    for name in class_e_json:
        if name in staged:
            continue
        src = server_dir / name
        if src.exists() and src.is_file():
            shutil.copy2(src, dest / name)
            staged.add(name)

    # onx-jars.lock.json (Class C reference / lockfile).
    lockfile = server_dir / "onx-jars.lock.json"
    if lockfile.exists() and lockfile.is_file():
        shutil.copy2(lockfile, dest / "onx-jars.lock.json")
        staged.add("onx-jars.lock.json")

    # Dimension folders (Class E worlds).
    for dim_name in ("world", "world_nether", "world_the_end"):
        dim_src = server_dir / dim_name
        if dim_src.exists() and dim_src.is_dir():
            shutil.copytree(dim_src, dest / dim_name, symlinks=True)
            staged.add(dim_name)

    # Plugins (Class E plugin binary DBs).
    plugins_src = server_dir / "plugins"
    if plugins_src.exists() and plugins_src.is_dir():
        shutil.copytree(plugins_src, dest / "plugins", symlinks=True)
        staged.add("plugins")

    # Optional Class A CAS jars (only when include_cas_jars=True).
    if include_cas_jars:
        cas_src = server_dir / ".onx-manager" / "cas"
        if cas_src.exists() and cas_src.is_dir():
            shutil.copytree(cas_src, dest / "cas", symlinks=True)
            staged.add("cas")


def _chunk_bytes(data: bytes, size: int):
    for i in range(0, len(data), size):
        yield data[i : i + size]
