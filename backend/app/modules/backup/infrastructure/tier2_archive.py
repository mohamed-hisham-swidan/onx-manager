"""Tier-2 portable disaster-recovery archive engine for P7-1 (OD-v8.6-2, OD-v8.7-7)."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from app.core.allowlist import classify, open_safe_path_fd, validate_canonical_relpath
from app.core.exceptions import ValidationError
from app.core.host_state import validate_server_segment
from app.modules.backup.infrastructure.envelope_crypto import (
    BackupEncryptionError,
    EnvelopeBackupCipher,
    load_or_create_master_kek,
    requires_archive_encryption,
)
from app.modules.backup.infrastructure.tier1_snapshot import CLASS_C_FILENAMES
from app.modules.storage.base import StorageBackend
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.vault_crypto import MasterKek

ArchiveFormat = Literal["tar.zst", "tar.gz"]


class Tier2ArchiveError(Exception):
    """Raised when Tier-2 archive creation fails."""


@dataclass(frozen=True)
class Tier2ArchiveResult:
    backup_id: str
    server_id: str
    archive_format: ArchiveFormat
    storage_path: str
    size_bytes: int
    checksum: str
    encrypted: bool
    has_class_c: bool
    include_cas_jars: bool
    bundled_cas_digests: tuple[str, ...]
    lockfile_cas_digests: tuple[str, ...]


def _detect_storage_kind(storage: StorageBackend) -> str:
    explicit = getattr(storage, "backend_type", None)
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip().lower()
    if "s3" in type(storage).__name__.lower():
        return "s3"
    return "local"


def _compress_tar_to_zst(tar_path: Path, zst_path: Path) -> None:
    try:
        import zstandard as zstd  # type: ignore[import-not-found]

        cctx = zstd.ZstdCompressor(level=3)
        with tar_path.open("rb") as src, zst_path.open("wb") as dst:
            cctx.copy_stream(src, dst)
        return
    except ImportError:
        pass

    zstd_bin = shutil.which("zstd")
    if not zstd_bin:
        raise Tier2ArchiveError(
            "zstd compression requested but neither zstandard nor zstd binary is installed"
        )
    with tar_path.open("rb") as src, zst_path.open("wb") as dst:
        proc = subprocess.run(
            [zstd_bin, "-q", "-3", "-c"],
            stdin=src,
            stdout=dst,
            stderr=subprocess.PIPE,
            check=False,
        )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise Tier2ArchiveError(f"zstd compression failed: {err}")


def _sha256_file(path: Path) -> tuple[int, str]:
    hasher = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        while chunk := fh.read(65536):
            size += len(chunk)
            hasher.update(chunk)
    return size, hasher.hexdigest()


def _collect_server_archive_files(server_dir: Path) -> tuple[list[tuple[str, str]], bool]:
    """Collect ``[(bucket, canonical_relpath)]`` and whether any Class C files exist."""
    entries: list[tuple[str, str]] = []
    has_class_c = False
    for root, dirs, files in os.walk(server_dir, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in (".git", ".onx-manager"))
        root_path = Path(root)
        for fname in sorted(files):
            full = root_path / fname
            if full.is_symlink() or not full.is_file():
                continue
            rel = full.relative_to(server_dir).as_posix()
            norm = validate_canonical_relpath(rel)
            cls_name = classify(norm)
            if norm == "onx-jars.lock.json":
                entries.append(("lockfile", norm))
            elif norm in CLASS_C_FILENAMES or cls_name == "C":
                entries.append(("class_c", norm))
                has_class_c = True
            elif cls_name == "E":
                entries.append(("class_e", norm))
            elif cls_name == "B":
                entries.append(("class_b", norm))
    return entries, has_class_c


def _extract_user_cas_entries(server_dir: Path) -> tuple[list[dict[str, str]], tuple[str, ...]]:
    """Return ``(user_origin_entries, all_lockfile_digests)`` from ``onx-jars.lock.json``."""
    lock_path = server_dir / "onx-jars.lock.json"
    if not lock_path.is_file():
        return [], ()
    try:
        doc = json.loads(lock_path.read_text(encoding="utf-8"))
    except Exception:
        return [], ()

    user_blobs: list[dict[str, str]] = []
    all_digests: set[str] = set()
    seen_user: set[str] = set()

    for entry in doc.get("files", []) or []:
        if not isinstance(entry, dict):
            continue
        sha = entry.get("sha256")
        if isinstance(sha, str) and sha:
            all_digests.add(sha)
            origin = str(entry.get("origin") or "").strip().lower()
            if origin == "user" and sha not in seen_user:
                seen_user.add(sha)
                user_blobs.append(
                    {
                        "sha256": sha,
                        "path": str(entry.get("path") or ""),
                        "origin": "user",
                    }
                )
    for entry in doc.get("base_overrides", []) or []:
        if isinstance(entry, dict) and isinstance(entry.get("sha256"), str):
            all_digests.add(entry["sha256"])

    return user_blobs, tuple(sorted(all_digests))


def collect_tier2_gc_roots(server_dirs_or_lockfiles: list[Path]) -> set[str]:
    """Collect CAS SHA-256 digests referenced by retained Tier-2 lockfiles/manifests."""
    roots: set[str] = set()
    for path in server_dirs_or_lockfiles:
        target = path / "onx-jars.lock.json" if path.is_dir() else path
        if not target.is_file():
            continue
        try:
            doc = json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            continue
        for entry in doc.get("files", []) or []:
            if isinstance(entry, dict) and isinstance(entry.get("sha256"), str):
                roots.add(entry["sha256"])
        for entry in doc.get("base_overrides", []) or []:
            if isinstance(entry, dict) and isinstance(entry.get("sha256"), str):
                roots.add(entry["sha256"])
    return roots


async def create_tier2_archive(
    *,
    server_id: str,
    server_dir: Path,
    backup_id: str,
    storage: StorageBackend,
    archive_format: ArchiveFormat = "tar.zst",
    include_cas_jars: bool = False,
    encrypt: bool | None = None,
    kek: MasterKek | None = None,
    kek_file_path: Path | None = None,
    cas: ArtifactCas | None = None,
) -> Tier2ArchiveResult:
    """Build and store a portable Tier-2 archive (`.tar.zst` or `.tar.gz`) with mandatory AEAD."""
    segment = validate_server_segment(server_id)
    if not server_dir.is_dir():
        raise ValidationError(f"Server directory does not exist: {server_dir}")
    if archive_format not in ("tar.zst", "tar.gz"):
        raise ValidationError(f"Unsupported archive_format: {archive_format!r}")

    entries, has_class_c = _collect_server_archive_files(server_dir)
    storage_kind = _detect_storage_kind(storage)
    must_encrypt = requires_archive_encryption(
        has_class_c=has_class_c, storage_backend=storage_kind
    )
    if must_encrypt and encrypt is False:
        raise ValidationError(
            "Tier-2 encryption is mandatory when Class C files are present or using S3 storage",
            field="encrypt",
        )
    should_encrypt = True if must_encrypt else (True if encrypt is None else bool(encrypt))

    user_blobs_meta, all_lock_digests = _extract_user_cas_entries(server_dir)
    bundled_blobs: list[dict[str, str]] = []

    with tempfile.TemporaryDirectory(prefix="onx-tier2-") as tmp_str:
        tmp_dir = Path(tmp_str)
        raw_archive_path = tmp_dir / f"{backup_id}.{archive_format}"
        tar_mode = "w:gz" if archive_format == "tar.gz" else "w"
        uncompressed_tar = (
            tmp_dir / f"{backup_id}.tar" if archive_format == "tar.zst" else raw_archive_path
        )

        with tarfile.open(uncompressed_tar, tar_mode) as tf:
            for bucket, rel in entries:
                fd = open_safe_path_fd(str(server_dir), rel)
                with os.fdopen(fd, "rb", closefd=True) as src_fh:
                    data = src_fh.read()
                arcname = f"triad/{bucket}/{rel}"
                info = tarfile.TarInfo(name=arcname)
                info.size = len(data)
                info.mode = 0o644
                tf.addfile(info, io.BytesIO(data))

            if include_cas_jars and cas is not None:
                for meta in user_blobs_meta:
                    digest = meta["sha256"]
                    if not cas.has(digest):
                        raise Tier2ArchiveError(
                            f"Missing user CAS blob '{digest}' during Tier-2 export"
                        )
                    blob_fd = open_safe_path_fd(
                        str(cas.root), f"sha256/{digest[:2]}/{digest}"
                    )
                    with os.fdopen(blob_fd, "rb", closefd=True) as blob_fh:
                        blob_bytes = blob_fh.read()
                    arcname = f"cas_blobs/{digest}"
                    info = tarfile.TarInfo(name=arcname)
                    info.size = len(blob_bytes)
                    info.mode = 0o644
                    tf.addfile(info, io.BytesIO(blob_bytes))
                    bundled_blobs.append(meta)

            manifest_doc: dict[str, Any] = {
                "schema_version": 1,
                "tier": "tier_2",
                "backup_id": backup_id,
                "server_id": segment,
                "archive_format": archive_format,
                "contains_class_c": has_class_c,
                "include_cas_jars": bool(include_cas_jars),
                "cas_blobs": bundled_blobs,
                "lockfile_cas_digests": list(all_lock_digests),
                "created_at": datetime.now(UTC).isoformat(),
            }
            manifest_bytes = json.dumps(manifest_doc, indent=2, sort_keys=True).encode("utf-8")
            m_info = tarfile.TarInfo(name="manifest.json")
            m_info.size = len(manifest_bytes)
            m_info.mode = 0o644
            tf.addfile(m_info, io.BytesIO(manifest_bytes))

        if archive_format == "tar.zst":
            _compress_tar_to_zst(uncompressed_tar, raw_archive_path)

        final_artifact = raw_archive_path
        ext = f"{archive_format}.enc" if should_encrypt else archive_format
        if should_encrypt:
            active_kek = kek
            if active_kek is None:
                try:
                    active_kek = load_or_create_master_kek(
                        kek_file_path=kek_file_path,
                        allow_create=kek_file_path is not None,
                    )
                except BackupEncryptionError as exc:
                    raise Tier2ArchiveError(str(exc)) from exc
            enc_path = tmp_dir / f"{backup_id}.{ext}"
            EnvelopeBackupCipher(active_kek).encrypt_file(raw_archive_path, enc_path)
            final_artifact = enc_path

        size_bytes, checksum = _sha256_file(final_artifact)
        storage_key = f"{segment}/tier2/{backup_id}.{ext}"

        store_result = await storage.write(storage_key, final_artifact.read_bytes())
        stored_path = getattr(store_result, "path", None) or storage_key

        with contextlib.suppress(OSError):
            if raw_archive_path.exists():
                raw_archive_path.unlink()

        return Tier2ArchiveResult(
            backup_id=backup_id,
            server_id=segment,
            archive_format=archive_format,
            storage_path=str(stored_path),
            size_bytes=size_bytes,
            checksum=checksum,
            encrypted=should_encrypt,
            has_class_c=has_class_c,
            include_cas_jars=bool(include_cas_jars),
            bundled_cas_digests=tuple(b["sha256"] for b in bundled_blobs),
            lockfile_cas_digests=all_lock_digests,
        )
