"""Safe cross-tier restore with crash-safe triad swap for P7-1 (OD-v8.6-2, OD-v8.7-2)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.allowlist import (
    classify,
    validate_canonical_relpath,
)
from app.core.host_state import validate_server_segment
from app.modules.backup.infrastructure.envelope_crypto import (
    ENVELOPE_MAGIC,
    BackupEncryptionError,
    EnvelopeBackupCipher,
    load_or_create_master_kek,
)
from app.modules.backup.infrastructure.tier1_snapshot import (
    open_safe_read_handle,
    resolve_safe_child_path,
    validate_tier1_complete_marker,
)
from app.modules.storage.base import StorageBackend
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.directory_swap import (
    DirectorySwapJournal,
    swap_directories,
)
from app.modules.versioning.infrastructure.vault_crypto import MasterKek

_TRIAD_BUCKETS = ("class_e", "class_c", "class_b", "lockfile")


class TwoTierRestoreError(Exception):
    """Raised when a Tier-1 or Tier-2 restore fails validation, decryption, or swap."""


@dataclass(frozen=True)
class TwoTierRestoreResult:
    backup_id: str
    server_id: str
    tier: str
    restored_files: int
    used_exchange: bool
    cas_blobs_restored: int = 0


def _decompress_zst_to_tar(zst_path: Path, tar_path: Path) -> None:
    try:
        import zstandard as zstd  # type: ignore[import-not-found]

        dctx = zstd.ZstdDecompressor()
        with zst_path.open("rb") as src, tar_path.open("wb") as dst:
            dctx.copy_stream(src, dst)
        return
    except ImportError:
        pass

    zstd_bin = shutil.which("zstd")
    if not zstd_bin:
        raise TwoTierRestoreError(
            "zstd archive cannot be extracted: no zstandard library or zstd binary"
        )
    with zst_path.open("rb") as src, tar_path.open("wb") as dst:
        proc = subprocess.run(
            [zstd_bin, "-d", "-q", "-c"],
            stdin=src,
            stdout=dst,
            stderr=subprocess.PIPE,
            check=False,
        )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise TwoTierRestoreError(f"zstd decompression failed: {err}")


def _validate_and_extract_tar(tar_file: Path, extract_dir: Path, *, is_gzip: bool) -> None:
    """Safely extract tar archive after validating every member with ``resolve_safe_disk_path``."""
    mode = "r:gz" if is_gzip else "r:"
    try:
        with tarfile.open(tar_file, mode) as tf:
            members = tf.getmembers()
            for member in members:
                if (
                    member.issym()
                    or member.islnk()
                    or member.ischr()
                    or member.isblk()
                    or member.isfifo()
                ):
                    raise TwoTierRestoreError(
                        f"Archive contains unsafe link/device entry: {member.name!r}"
                    )
                raw_name = member.name.rstrip("/")
                if not raw_name or raw_name == ".":
                    continue
                if raw_name.startswith("/") or "\\" in raw_name or "\x00" in raw_name:
                    raise TwoTierRestoreError(f"Archive contains unsafe path: {member.name!r}")
                norm = validate_canonical_relpath(raw_name)
                dest = resolve_safe_child_path(extract_dir, norm)
                if member.isdir():
                    dest.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    src_fh = tf.extractfile(member)
                    if src_fh is None:
                        raise TwoTierRestoreError(f"Could not extract file member: {norm}")
                    with src_fh, dest.open("wb") as out_fh:
                        shutil.copyfileobj(src_fh, out_fh, length=65536)
                else:
                    raise TwoTierRestoreError(f"Unsupported tar member type for {member.name!r}")
    except TwoTierRestoreError:
        raise
    except Exception as exc:
        raise TwoTierRestoreError(f"Corrupt or invalid archive: {exc}") from exc


def _build_staged_live_tree(
    *,
    server_dir: Path,
    triad_root: Path,
    staging_tree: Path,
) -> int:
    """Stage replacement tree on ``server_dir`` FS (keep Class A, swap triad)."""
    staging_tree.mkdir(parents=True, exist_ok=True)

    # 1. Carry over non-triad files (Class A mods/plugins, server.jar, .onx-manager, etc.)
    for root, dirs, files in os.walk(server_dir, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d != ".git")
        root_path = Path(root)
        for fname in sorted(files):
            src = root_path / fname
            if src.is_symlink() or not src.is_file():
                continue
            rel = src.relative_to(server_dir).as_posix()
            if rel.startswith(".onx-manager/"):
                dst = staging_tree / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                continue
            norm = validate_canonical_relpath(rel)
            cls_name = classify(norm)
            if norm == "onx-jars.lock.json" or cls_name in ("E", "C", "B"):
                # Replaced by snapshot/archive triad below
                continue
            dst = resolve_safe_child_path(staging_tree, norm)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    # 2. Copy validated triad files from snapshot/extracted staging via open_safe_path_fd
    restored_count = 0
    for bucket in _TRIAD_BUCKETS:
        bucket_dir = triad_root / bucket
        if not bucket_dir.is_dir():
            continue
        for root, dirs, files in os.walk(bucket_dir, followlinks=False):
            dirs[:] = sorted(dirs)
            root_path = Path(root)
            for fname in sorted(files):
                fpath = root_path / fname
                if fpath.is_symlink():
                    raise TwoTierRestoreError(f"Symlink detected in triad bucket {bucket}: {fname}")
                if not fpath.is_file():
                    continue
                rel_in_bucket = fpath.relative_to(bucket_dir).as_posix()
                norm_rel = validate_canonical_relpath(rel_in_bucket)
                dst = resolve_safe_child_path(staging_tree, norm_rel)
                dst.parent.mkdir(parents=True, exist_ok=True)
                with open_safe_read_handle(bucket_dir, norm_rel) as s_fh, dst.open("wb") as d_fh:
                    shutil.copyfileobj(s_fh, d_fh, length=65536)
                restored_count += 1

    return restored_count


def _execute_triad_swap(
    *,
    server_id: str,
    server_dir: Path,
    staging_tree: Path,
    journal_dir: Path,
    backup_id: str,
    exchange_supported: bool | None = None,
) -> bool:
    journal = DirectorySwapJournal(journal_dir / f"restore-{backup_id}.json")
    result = swap_directories(
        server_dir,
        staging_tree,
        journal,
        server_id=server_id,
        pre_upgrade_backup_id=backup_id,
        keep_previous=False,
        exchange_supported=exchange_supported,
    )
    # Clean up old tree left behind at previous_tree_path
    old_tree = result.previous_tree_path
    if old_tree.exists():
        shutil.rmtree(old_tree, ignore_errors=True)
    return result.used_exchange


async def restore_tier1_snapshot(
    *,
    server_id: str,
    server_dir: Path,
    snapshot_dir: Path,
    backup_id: str,
    journal_dir: Path | None = None,
    exchange_supported: bool | None = None,
) -> TwoTierRestoreResult:
    """Validate Tier-1 snapshot marker/paths, stage on target FS, and triad-swap."""
    segment = validate_server_segment(server_id)
    if not server_dir.is_dir():
        raise TwoTierRestoreError(f"Target server directory does not exist: {server_dir}")
    try:
        validate_tier1_complete_marker(snapshot_dir)
    except Exception as exc:
        raise TwoTierRestoreError(str(exc)) from exc

    staging_tree = server_dir.parent / f".onx-restore-stage-{segment}-{uuid.uuid4().hex[:8]}"
    active_journal_dir = journal_dir or (server_dir.parent / ".onx-restore-journals")
    try:
        restored_count = _build_staged_live_tree(
            server_dir=server_dir,
            triad_root=snapshot_dir,
            staging_tree=staging_tree,
        )
        used_exchange = _execute_triad_swap(
            server_id=segment,
            server_dir=server_dir,
            staging_tree=staging_tree,
            journal_dir=active_journal_dir,
            backup_id=backup_id,
            exchange_supported=exchange_supported,
        )
        return TwoTierRestoreResult(
            backup_id=backup_id,
            server_id=segment,
            tier="tier_1",
            restored_files=restored_count,
            used_exchange=used_exchange,
        )
    except TwoTierRestoreError:
        if staging_tree.exists():
            shutil.rmtree(staging_tree, ignore_errors=True)
        raise
    except Exception as exc:
        if staging_tree.exists():
            shutil.rmtree(staging_tree, ignore_errors=True)
        raise TwoTierRestoreError(f"Tier-1 restore failed: {exc}") from exc


async def restore_tier2_archive(
    *,
    server_id: str,
    server_dir: Path,
    storage_path: str,
    backup_id: str,
    storage: StorageBackend | None = None,
    expected_checksum: str | None = None,
    kek: MasterKek | None = None,
    kek_file_path: Path | None = None,
    cas: ArtifactCas | None = None,
    journal_dir: Path | None = None,
    exchange_supported: bool | None = None,
) -> TwoTierRestoreResult:
    """Verify, decrypt, safely extract, populate CAS blobs, and atomically swap Tier-2 archive."""
    segment = validate_server_segment(server_id)
    if not server_dir.is_dir():
        raise TwoTierRestoreError(f"Target server directory does not exist: {server_dir}")

    with tempfile.TemporaryDirectory(prefix="onx-tier2-restore-") as tmp_str:
        tmp_dir = Path(tmp_str)
        raw_download = tmp_dir / "artifact.bin"
        if storage is not None:
            data = await storage.read(storage_path)
            raw_download.write_bytes(data)
        else:
            src_local = Path(storage_path)
            if not src_local.is_file():
                raise TwoTierRestoreError(f"Tier-2 archive not found: {storage_path}")
            shutil.copy2(src_local, raw_download)

        if expected_checksum:
            actual_sha = hashlib.sha256(raw_download.read_bytes()).hexdigest()
            if actual_sha != expected_checksum:
                raise TwoTierRestoreError("Tier-2 archive SHA-256 checksum mismatch")

        with raw_download.open("rb") as fh:
            prefix = fh.read(len(ENVELOPE_MAGIC))

        archive_path = raw_download
        if prefix == ENVELOPE_MAGIC or storage_path.endswith(".enc"):
            active_kek = kek
            if active_kek is None:
                try:
                    active_kek = load_or_create_master_kek(
                        kek_file_path=kek_file_path,
                        allow_create=False,
                    )
                except BackupEncryptionError as exc:
                    raise TwoTierRestoreError(f"Cannot load Master KEK: {exc}") from exc
            decrypted = tmp_dir / "decrypted.archive"
            try:
                EnvelopeBackupCipher(active_kek).decrypt_file(raw_download, decrypted)
            except BackupEncryptionError as exc:
                raise TwoTierRestoreError(f"Envelope decryption failed: {exc}") from exc
            archive_path = decrypted

        extract_dir = tmp_dir / "extracted"
        extract_dir.mkdir(parents=True, exist_ok=True)
        magic_hdr = archive_path.read_bytes()[:6]
        is_gzip = magic_hdr[:2] == b"\x1f\x8b" or storage_path.endswith(
            (".tar.gz", ".tar.gz.enc")
        )
        is_zst = magic_hdr[:4] == b"\x28\xb5\x2f\xfd" or storage_path.endswith(
            (".tar.zst", ".tar.zst.enc")
        )

        if is_gzip:
            _validate_and_extract_tar(archive_path, extract_dir, is_gzip=True)
        elif is_zst:
            uncompressed_tar = tmp_dir / "archive.tar"
            _decompress_zst_to_tar(archive_path, uncompressed_tar)
            _validate_and_extract_tar(uncompressed_tar, extract_dir, is_gzip=False)
        else:
            _validate_and_extract_tar(archive_path, extract_dir, is_gzip=False)

        manifest_path = extract_dir / "manifest.json"
        if not manifest_path.is_file():
            raise TwoTierRestoreError("Tier-2 archive missing manifest.json")
        try:
            manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise TwoTierRestoreError(f"Invalid manifest.json in Tier-2 archive: {exc}") from exc
        if manifest.get("tier") != "tier_2":
            raise TwoTierRestoreError(f"Unexpected archive tier: {manifest.get('tier')!r}")

        cas_restored = 0
        if cas is not None:
            for entry in manifest.get("cas_blobs", []) or []:
                digest = str(entry.get("sha256") or "")
                if not digest:
                    raise TwoTierRestoreError("Invalid CAS blob entry in manifest.json")
                blob_file = resolve_safe_child_path(extract_dir, f"cas_blobs/{digest}")
                if not blob_file.is_file():
                    raise TwoTierRestoreError(f"Missing bundled CAS blob {digest} in archive")
                blob_bytes = blob_file.read_bytes()
                if hashlib.sha256(blob_bytes).hexdigest() != digest:
                    raise TwoTierRestoreError(f"CAS blob SHA-256 mismatch for {digest}")
                cas.put_bytes(blob_bytes)
                cas_restored += 1

        triad_root = extract_dir / "triad"
        if not triad_root.is_dir():
            raise TwoTierRestoreError("Tier-2 archive missing triad/ directory")

        staging_tree = server_dir.parent / f".onx-restore-stage-{segment}-{uuid.uuid4().hex[:8]}"
        active_journal_dir = journal_dir or (server_dir.parent / ".onx-restore-journals")
        try:
            restored_count = _build_staged_live_tree(
                server_dir=server_dir,
                triad_root=triad_root,
                staging_tree=staging_tree,
            )
            used_exchange = _execute_triad_swap(
                server_id=segment,
                server_dir=server_dir,
                staging_tree=staging_tree,
                journal_dir=active_journal_dir,
                backup_id=backup_id,
                exchange_supported=exchange_supported,
            )
            return TwoTierRestoreResult(
                backup_id=backup_id,
                server_id=segment,
                tier="tier_2",
                restored_files=restored_count,
                used_exchange=used_exchange,
                cas_blobs_restored=cas_restored,
            )
        except TwoTierRestoreError:
            if staging_tree.exists():
                shutil.rmtree(staging_tree, ignore_errors=True)
            raise
        except Exception as exc:
            if staging_tree.exists():
                shutil.rmtree(staging_tree, ignore_errors=True)
            raise TwoTierRestoreError(f"Tier-2 restore failed: {exc}") from exc
