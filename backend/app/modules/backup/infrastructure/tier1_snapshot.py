"""Tier-1 fast local operational snapshot engine for P7-1 (OD-v8.6-2, OD-v8.7-8)."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]

from app.core.allowlist import (
    SymlinkEscapeError,
    classify,
    open_safe_path_fd,
    resolve_safe_disk_path,
    validate_canonical_relpath,
)
from app.core.exceptions import InsufficientStorageError, ValidationError
from app.core.host_state import validate_server_segment
from app.core.platform_lock import FileLock
from app.modules.versioning.infrastructure.fs_atomic import atomic_write_private

TIER1_MARKER_FILENAME = ".onx-complete.json"
SAVE_OFF_MARKER_FILENAME = ".onx-save-off-active.json"
MAX_SAVE_OFF_SECONDS = 60.0
_FICLONE = 0x40049409
_SPACE_HEADROOM_FACTOR = 1.10

CLASS_C_FILENAMES = frozenset(
    {
        "ops.json",
        "whitelist.json",
        "banned-players.json",
        "banned-ips.json",
        "usercache.json",
    }
)


class Tier1SnapshotError(Exception):
    """Raised when Tier-1 snapshot creation or validation fails."""


@dataclass(frozen=True)
class Tier1SnapshotResult:
    backup_id: str
    server_id: str
    snapshot_dir: str
    marker_path: str
    size_bytes: int
    checksum: str
    used_reflink: bool
    quiesced: bool
    lockfile_sha256: str | None
    cas_digests: tuple[str, ...]


def _fsync_dir(path: Path) -> None:
    if os.name != "posix":
        return
    try:
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _try_reflink_file(src: Path, dst: Path) -> bool:
    """Attempt Linux Btrfs/XFS FICLONE copy; return False if unsupported."""
    if os.name != "posix" or fcntl is None:
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        with src.open("rb") as s_fh, dst.open("wb") as d_fh:
            fcntl.ioctl(d_fh.fileno(), _FICLONE, s_fh.fileno())
            shutil.copystat(src, dst, follow_symlinks=False)
            return True
    except OSError:
        with contextlib.suppress(OSError):
            dst.unlink()
        return False


def resolve_safe_child_path(
    root_dir: Path,
    relpath: str,
    *,
    allow_create_parents: bool = False,
) -> Path:
    """Resolve ``relpath`` safely under ``root_dir`` (dir_fd on POSIX; symlink check on Windows)."""
    norm = validate_canonical_relpath(relpath)
    if os.name == "posix":
        return Path(
            resolve_safe_disk_path(str(root_dir), norm, allow_create_parents=allow_create_parents)
        )
    if root_dir.is_symlink():
        raise SymlinkEscapeError(f"Root itself is a symlink: {root_dir!r}")
    root_real = os.path.realpath(root_dir)
    curr = root_dir
    for seg in norm.split("/"):
        curr = curr / seg
        if curr.is_symlink():
            raise SymlinkEscapeError(f"Symlink component rejected: {seg!r}")
    target_real = os.path.realpath(root_dir / norm)
    if target_real == root_real or os.path.commonpath([root_real, target_real]) != root_real:
        raise SymlinkEscapeError(f"Path escapes root after resolution: {norm!r}")
    if allow_create_parents:
        safe_target = root_dir.joinpath(*norm.split("/"))
        safe_target.parent.mkdir(parents=True, exist_ok=True)
        return safe_target
    return root_dir.joinpath(*norm.split("/"))


def open_safe_read_handle(root_dir: Path, relpath: str) -> BinaryIO:
    """Open ``relpath`` under ``root_dir`` for reading (``open_safe_path_fd`` on POSIX)."""
    norm = validate_canonical_relpath(relpath)
    if os.name == "posix":
        fd = open_safe_path_fd(str(root_dir), norm)
        return os.fdopen(fd, "rb", closefd=True)
    safe_path = resolve_safe_child_path(root_dir, norm)
    return safe_path.open("rb")


def _copy_file_safe(src_root: Path, relpath: str, dst_file: Path, *, allow_reflink: bool) -> bool:
    """Safely open source via ``open_safe_read_handle`` and copy into ``dst_file``.

    Returns True if FICLONE reflink succeeded.
    """
    src_file = src_root / relpath
    dst_file.parent.mkdir(parents=True, exist_ok=True)
    if allow_reflink and _try_reflink_file(src_file, dst_file):
        return True

    try:
        with open_safe_read_handle(src_root, relpath) as s_fh, dst_file.open("wb") as d_fh:
            shutil.copyfileobj(s_fh, d_fh, length=65536)
    except Exception:
        with contextlib.suppress(OSError):
            dst_file.unlink()
        raise
    shutil.copystat(src_file, dst_file, follow_symlinks=False)
    return False


def _collect_triad_files(server_dir: Path) -> list[tuple[str, str, int]]:
    """Return ``[(bucket, canonical_relpath, size_bytes)]`` for Class E, C, B, and lockfile."""
    entries: list[tuple[str, str, int]] = []
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
            bucket: str | None = None
            if norm == "onx-jars.lock.json":
                bucket = "lockfile"
            elif norm in CLASS_C_FILENAMES or cls_name == "C":
                bucket = "class_c"
            elif cls_name == "E":
                bucket = "class_e"
            elif cls_name == "B":
                bucket = "class_b"
            if bucket is not None:
                entries.append((bucket, norm, full.stat().st_size))
    return entries


def _directory_checksum_and_size(snapshot_dir: Path) -> tuple[int, str]:
    hasher = hashlib.sha256()
    total = 0
    for root, dirs, files in os.walk(snapshot_dir, followlinks=False):
        dirs[:] = sorted(dirs)
        for fname in sorted(files):
            if fname == TIER1_MARKER_FILENAME:
                continue
            fpath = Path(root) / fname
            rel = fpath.relative_to(snapshot_dir).as_posix()
            hasher.update(rel.encode("utf-8"))
            data = fpath.read_bytes()
            total += len(data)
            hasher.update(data)
    return total, hasher.hexdigest()


def _extract_lockfile_gc_refs(server_dir: Path) -> tuple[str | None, tuple[str, ...]]:
    lock_path = server_dir / "onx-jars.lock.json"
    if not lock_path.is_file():
        return None, ()
    raw = lock_path.read_bytes()
    lock_sha = hashlib.sha256(raw).hexdigest()
    digests: set[str] = set()
    try:
        doc = json.loads(raw.decode("utf-8"))
        for entry in doc.get("files", []) or []:
            if isinstance(entry, dict) and isinstance(entry.get("sha256"), str):
                digests.add(entry["sha256"])
        for entry in doc.get("base_overrides", []) or []:
            if isinstance(entry, dict) and isinstance(entry.get("sha256"), str):
                digests.add(entry["sha256"])
    except Exception:
        pass
    return lock_sha, tuple(sorted(digests))


def validate_tier1_complete_marker(snapshot_dir: Path) -> dict[str, Any]:
    """Validate and return parsed ``.onx-complete.json``; raise if missing/corrupt."""
    marker = snapshot_dir / TIER1_MARKER_FILENAME
    if not marker.is_file() or marker.is_symlink():
        raise Tier1SnapshotError(f"Incomplete Tier-1 snapshot (missing {TIER1_MARKER_FILENAME})")
    try:
        doc = json.loads(marker.read_text(encoding="utf-8"))
    except Exception as exc:
        raise Tier1SnapshotError(f"Corrupt Tier-1 marker in {snapshot_dir}: {exc}") from exc
    if not isinstance(doc, dict) or doc.get("tier") != "tier_1" or not doc.get("backup_id"):
        raise Tier1SnapshotError(f"Invalid Tier-1 marker fields in {snapshot_dir}")
    expected_sha = doc.get("checksum")
    if isinstance(expected_sha, str) and expected_sha:
        _, actual_sha = _directory_checksum_and_size(snapshot_dir)
        if actual_sha != expected_sha:
            raise Tier1SnapshotError(f"Tier-1 snapshot checksum mismatch in {snapshot_dir}")
    return doc


def discard_incomplete_snapshots(server_snapshots_dir: Path) -> list[str]:
    """Remove any staging directories or snapshot dirs missing a valid ``.onx-complete.json``."""
    if not server_snapshots_dir.is_dir():
        return []
    removed: list[str] = []
    for child in sorted(server_snapshots_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith(".staging-"):
            shutil.rmtree(child, ignore_errors=True)
            removed.append(child.name)
            continue
        try:
            validate_tier1_complete_marker(child)
        except Tier1SnapshotError:
            shutil.rmtree(child, ignore_errors=True)
            removed.append(child.name)
    return removed


def collect_tier1_gc_roots(server_snapshots_dir: Path) -> set[str]:
    """Collect CAS SHA-256 digests referenced by valid Tier-1 snapshots for GC retention."""
    roots: set[str] = set()
    if not server_snapshots_dir.is_dir():
        return roots
    for child in server_snapshots_dir.iterdir():
        if not child.is_dir() or child.name.startswith(".staging-"):
            continue
        try:
            doc = validate_tier1_complete_marker(child)
        except Tier1SnapshotError:
            continue
        for d in doc.get("cas_digests", []) or []:
            if isinstance(d, str) and d:
                roots.add(d)
    return roots


async def recover_save_off_state(
    meta_dir: Path,
    rcon_send: Callable[[str], Awaitable[str]],
) -> bool:
    """Issue ``save-on`` on startup if an interrupted snapshot left ``rcon_save_off_active``."""
    marker = meta_dir / SAVE_OFF_MARKER_FILENAME
    if not marker.is_file():
        return False
    await rcon_send("save-on")
    with contextlib.suppress(OSError):
        marker.unlink()
    return True


async def create_tier1_snapshot(
    *,
    server_id: str,
    server_dir: Path,
    snapshots_root: Path,
    backup_id: str,
    is_running: bool = False,
    rcon_send: Callable[[str], Awaitable[str]] | None = None,
    locks_dir: Path | None = None,
    max_save_off_seconds: float = MAX_SAVE_OFF_SECONDS,
    force_no_reflink: bool = False,
) -> Tier1SnapshotResult:
    """Create a quiescent Tier-1 snapshot with per-st_dev lock, space check, and fsynced marker."""
    segment = validate_server_segment(server_id)
    if not server_dir.is_dir():
        raise ValidationError(f"Server directory does not exist: {server_dir}")
    if max_save_off_seconds <= 0 or max_save_off_seconds > MAX_SAVE_OFF_SECONDS:
        raise ValidationError("max_save_off_seconds must be in (0, 60]")

    server_snap_dir = snapshots_root / segment
    server_snap_dir.mkdir(parents=True, exist_ok=True)
    final_dir = server_snap_dir / backup_id
    staging_dir = server_snap_dir / f".staging-{backup_id}-{uuid.uuid4().hex[:8]}"

    lock_root = locks_dir or snapshots_root
    st_dev = os.stat(server_snap_dir).st_dev
    lock = FileLock(lock_root / f".tier1-copy-{st_dev}.lock")
    if not lock.acquire(timeout=30.0):
        raise Tier1SnapshotError("Timed out acquiring storage copy lock")

    try:
        entries = _collect_triad_files(server_dir)
        needed_bytes = sum(size for _, _, size in entries)
        free_bytes = shutil.disk_usage(server_snap_dir).free
        if free_bytes < int(needed_bytes * _SPACE_HEADROOM_FACTOR):
            raise InsufficientStorageError(
                details={
                    "required_bytes": int(needed_bytes * _SPACE_HEADROOM_FACTOR),
                    "free_bytes": free_bytes,
                }
            )

        staging_dir.mkdir(parents=True, exist_ok=True)
        used_reflink = False
        quiesced = False

        if not is_running or rcon_send is None:
            for bucket, rel, _ in entries:
                dst = staging_dir / bucket / rel
                if _copy_file_safe(server_dir, rel, dst, allow_reflink=not force_no_reflink):
                    used_reflink = True
        else:
            # Pass 1: online pre-copy while world continues running (no save-off yet)
            for bucket, rel, _ in entries:
                dst = staging_dir / bucket / rel
                if _copy_file_safe(server_dir, rel, dst, allow_reflink=not force_no_reflink):
                    used_reflink = True

            # Pass 2: quiesced save-off -> save-all flush -> delta copy -> save-on in finally
            meta_dir = server_dir / ".onx-manager"
            meta_dir.mkdir(parents=True, exist_ok=True)
            save_off_marker = meta_dir / SAVE_OFF_MARKER_FILENAME
            atomic_write_private(
                save_off_marker,
                json.dumps(
                    {
                        "rcon_save_off_active": True,
                        "server_id": segment,
                        "backup_id": backup_id,
                        "started_at": datetime.now(UTC).isoformat(),
                    }
                ).encode("utf-8"),
            )
            save_off_sent = False
            try:
                await rcon_send("save-off")
                save_off_sent = True
                await rcon_send("save-all flush")
                quiesced = True
                started_monotonic = time.monotonic()

                fresh_entries = _collect_triad_files(server_dir)
                for bucket, rel, _ in fresh_entries:
                    if time.monotonic() - started_monotonic > max_save_off_seconds:
                        raise Tier1SnapshotError(
                            f"Quiesced delta copy exceeded {max_save_off_seconds:.0f}s save-off cap"
                        )
                    src_file = server_dir / rel
                    dst_file = staging_dir / bucket / rel
                    if dst_file.exists():
                        s_stat = src_file.stat()
                        d_stat = dst_file.stat()
                        if (
                            s_stat.st_size == d_stat.st_size
                            and s_stat.st_mtime_ns == d_stat.st_mtime_ns
                        ):
                            continue
                    if _copy_file_safe(
                        server_dir, rel, dst_file, allow_reflink=not force_no_reflink
                    ):
                        used_reflink = True
            finally:
                if save_off_sent:
                    with contextlib.suppress(Exception):
                        await rcon_send("save-on")
                with contextlib.suppress(OSError):
                    save_off_marker.unlink()

        if final_dir.exists():
            shutil.rmtree(final_dir)
        os.replace(staging_dir, final_dir)

        size_bytes, checksum = _directory_checksum_and_size(final_dir)
        lock_sha, cas_digests = _extract_lockfile_gc_refs(server_dir)
        marker_doc = {
            "schema_version": 1,
            "tier": "tier_1",
            "backup_id": backup_id,
            "server_id": segment,
            "created_at": datetime.now(UTC).isoformat(),
            "size_bytes": size_bytes,
            "checksum": checksum,
            "used_reflink": used_reflink,
            "quiesced": quiesced,
            "lockfile_sha256": lock_sha,
            "cas_digests": list(cas_digests),
            "files": [{"bucket": b, "path": r} for b, r, _ in _collect_triad_files(server_dir)],
        }
        atomic_write_private(
            final_dir / TIER1_MARKER_FILENAME,
            json.dumps(marker_doc, indent=2, sort_keys=True).encode("utf-8"),
        )
        _fsync_dir(final_dir)
        _fsync_dir(server_snap_dir)

        return Tier1SnapshotResult(
            backup_id=backup_id,
            server_id=segment,
            snapshot_dir=str(final_dir),
            marker_path=str(final_dir / TIER1_MARKER_FILENAME),
            size_bytes=size_bytes,
            checksum=checksum,
            used_reflink=used_reflink,
            quiesced=quiesced,
            lockfile_sha256=lock_sha,
            cas_digests=cas_digests,
        )
    except Exception:
        with contextlib.suppress(Exception):
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    finally:
        lock.release()
