"""Interim plain Class-C snapshot store (P2-5d0, D-P25-9).

The vault lives at ``<host_state>/class-c-vault/<server_id>/<snapshot_id>`` and
holds plain (unencrypted) copies of the live Class-C files plus a SHA-256
manifest. Snapshots are staged in a hidden sibling directory, fsynced, marked
complete, and only then renamed into place. Restore verifies the completion
marker, the manifest format, and every digest before writing anything.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.allowlist import classify, open_safe_path_fd, validate_canonical_relpath
from app.core.exceptions import (
    BackupPinnedError,
    CasUnsupportedPlatformError,
    ConflictError,
    ValidationError,
)
from app.core.host_state import HostStateLayout, validate_server_segment
from app.modules.versioning.infrastructure.fs_atomic import atomic_write_private

MANIFEST_FILENAME = "manifest.json"
COMPLETE_MARKER_NAME = ".onx-complete.json"
FORMAT_VERSION = 1

_COPY_CHUNK = 1024 * 1024
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class ClassCSnapshotResult:
    snapshot_id: str
    root: Path
    manifest_path: Path
    file_count: int
    total_bytes: int
    pinned: bool


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _fsync_dir(path: Path) -> None:
    if os.name != "posix":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _require_posix_host() -> None:
    if os.name != "posix":
        raise CasUnsupportedPlatformError("Class-C snapshots require a POSIX host")


def _mkdir_private(path: Path) -> None:
    if path.is_symlink():
        raise ValidationError("Snapshot directory must not be a symlink", field="path")
    if path.exists():
        if not path.is_dir():
            raise ValidationError("Snapshot path must be a directory", field="path")
        return

    missing: list[Path] = []
    current = path
    while not current.exists() and not current.is_symlink():
        missing.append(current)
        if current.parent == current:
            break
        current = current.parent
    if current.is_symlink():
        raise ValidationError("Snapshot path must not traverse a symlink", field="path")

    for item in reversed(missing):
        item.mkdir(mode=0o700)
        if os.name == "posix":
            os.chmod(item, 0o700)


def _read_fd(fd: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, _COPY_CHUNK)
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def _write_fd(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short write")
        view = view[written:]


def _read_json(root: Path, name: str) -> dict[str, Any]:
    try:
        fd = open_safe_path_fd(str(root), name)
    except FileNotFoundError as exc:
        raise ValidationError(f"Snapshot is missing {name}", field="snapshot") from exc
    except (OSError, ValueError) as exc:
        raise ValidationError(f"Unable to open snapshot file '{name}'", field="snapshot") from exc
    try:
        raw = _read_fd(fd)
    finally:
        os.close(fd)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(
            f"Snapshot file '{name}' is not valid JSON", field="snapshot"
        ) from exc
    if not isinstance(payload, dict):
        raise ValidationError(f"Snapshot file '{name}' must be a JSON object", field="snapshot")
    return payload


def _manifest_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list):
        raise ValidationError("Snapshot manifest 'files' must be a list", field="snapshot")

    entries: list[dict[str, Any]] = []
    for raw in raw_files:
        if not isinstance(raw, dict):
            raise ValidationError("Snapshot manifest entry must be an object", field="snapshot")
        relpath = raw.get("relpath")
        digest = raw.get("sha256")
        mode = raw.get("mode")
        size = raw.get("size")
        if not isinstance(relpath, str):
            raise ValidationError("Snapshot manifest entry has no relpath", field="snapshot")
        try:
            validate_canonical_relpath(relpath)
        except ValueError as exc:
            raise ValidationError(
                "Snapshot manifest has an unsafe relpath", field="snapshot"
            ) from exc
        if not isinstance(digest, str) or not _SHA256_RE.match(digest):
            raise ValidationError("Snapshot manifest has an invalid sha256", field="snapshot")
        if not isinstance(mode, int) or isinstance(mode, bool) or mode < 0:
            raise ValidationError("Snapshot manifest has an invalid mode", field="snapshot")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ValidationError("Snapshot manifest has an invalid size", field="snapshot")
        entries.append(
            {"relpath": relpath, "sha256": digest, "mode": mode, "size": size}
        )
    return entries


def _iter_class_c_files(live: Path, dynamic_class_c: frozenset[str]) -> Iterator[str]:
    for dirpath, dirnames, filenames in os.walk(live, topdown=True, followlinks=False):
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.is_symlink() or not path.is_file():
                continue
            relpath = path.relative_to(live).as_posix()
            try:
                validate_canonical_relpath(relpath)
            except ValueError:
                continue
            if classify(relpath, dynamic_class_c=dynamic_class_c) == "C":
                yield relpath


def _hash_snapshot_file(root: Path, relpath: str) -> tuple[str, int]:
    try:
        fd = open_safe_path_fd(str(root), relpath)
    except FileNotFoundError as exc:
        raise ValidationError(
            "Snapshot file is missing", field="snapshot", details={"relpath": relpath}
        ) from exc
    except (OSError, ValueError) as exc:
        raise ValidationError(
            "Snapshot file is unsafe", field="snapshot", details={"relpath": relpath}
        ) from exc
    digest = hashlib.sha256()
    size = 0
    try:
        while True:
            chunk = os.read(fd, _COPY_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    finally:
        os.close(fd)
    return digest.hexdigest(), size


class ClassCSnapshotService:
    """Create, restore, unpin, and delete interim Class-C snapshots."""

    def __init__(self, layout: HostStateLayout) -> None:
        self._layout = layout

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_snapshot(
        self,
        server_id: str,
        live_dir: str | os.PathLike[str],
        *,
        dynamic_class_c: Iterable[str] = (),
        pinned: bool = True,
        snapshot_id: str | None = None,
    ) -> ClassCSnapshotResult:
        _require_posix_host()
        segment = validate_server_segment(server_id)
        snapshot = validate_server_segment(snapshot_id or uuid.uuid4().hex)
        live = Path(live_dir)
        if live.is_symlink() or not live.is_dir():
            raise ValidationError(
                "live_dir must be an existing plain directory", field="live_dir"
            )

        vault = self._layout.class_c_vault_dir(segment)
        _mkdir_private(vault)
        target = vault / snapshot
        if os.path.lexists(target):
            raise ConflictError(f"Snapshot '{snapshot}' already exists")

        staging = vault / f".onx-snapshot-{snapshot}-{uuid.uuid4().hex}"
        staging.mkdir(mode=0o700)
        if os.name == "posix":
            os.chmod(staging, 0o700)

        dynamic = frozenset(str(item) for item in dynamic_class_c)
        files: list[dict[str, Any]] = []
        total_bytes = 0
        try:
            for relpath in _iter_class_c_files(live, dynamic):
                try:
                    src_fd = open_safe_path_fd(str(live), relpath)
                except (OSError, ValueError) as exc:
                    raise ValidationError(
                        "Class-C file is unsafe",
                        field="live_dir",
                        details={"relpath": relpath},
                    ) from exc
                try:
                    source_stat = os.fstat(src_fd)
                    if not stat.S_ISREG(source_stat.st_mode):
                        continue
                    dest = staging / relpath
                    _mkdir_private(dest.parent)
                    mode = stat.S_IMODE(source_stat.st_mode) & 0o777
                    dest_fd = os.open(
                        dest,
                        os.O_WRONLY
                        | os.O_CREAT
                        | os.O_EXCL
                        | getattr(os, "O_NOFOLLOW", 0),
                        0o600,
                    )
                    digest = hashlib.sha256()
                    size = 0
                    try:
                        while True:
                            chunk = os.read(src_fd, _COPY_CHUNK)
                            if not chunk:
                                break
                            digest.update(chunk)
                            _write_fd(dest_fd, chunk)
                            size += len(chunk)
                        if os.name == "posix":
                            os.fchmod(dest_fd, mode)
                        os.fsync(dest_fd)
                    finally:
                        os.close(dest_fd)
                finally:
                    os.close(src_fd)

                files.append(
                    {
                        "relpath": relpath,
                        "sha256": digest.hexdigest(),
                        "mode": mode,
                        "size": size,
                    }
                )
                total_bytes += size

            files.sort(key=lambda item: item["relpath"])
            manifest = {
                "format_version": FORMAT_VERSION,
                "snapshot_id": snapshot,
                "server_id": segment,
                "created_at": _utc_now(),
                "pinned": bool(pinned),
                "files": files,
            }
            atomic_write_private(
                staging / MANIFEST_FILENAME, _json_bytes(manifest), mode=0o600
            )
            marker = {
                "snapshot_id": snapshot,
                "server_id": segment,
                "format_version": FORMAT_VERSION,
                "file_count": len(files),
                "completed_at": _utc_now(),
            }
            atomic_write_private(
                staging / COMPLETE_MARKER_NAME, _json_bytes(marker), mode=0o600
            )
            _fsync_dir(staging)
            os.rename(staging, target)
            _fsync_dir(vault)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

        return ClassCSnapshotResult(
            snapshot_id=snapshot,
            root=target,
            manifest_path=target / MANIFEST_FILENAME,
            file_count=len(files),
            total_bytes=total_bytes,
            pinned=bool(pinned),
        )

    # ------------------------------------------------------------------
    # Read / validate
    # ------------------------------------------------------------------

    def _load_snapshot(
        self,
        server_id: str,
        snapshot_id: str,
        *,
        require_marker: bool,
    ) -> tuple[str, str, Path, dict[str, Any]]:
        segment = validate_server_segment(server_id)
        snapshot = validate_server_segment(snapshot_id)
        root = self._layout.class_c_vault_dir(segment) / snapshot
        if root.is_symlink() or not root.is_dir():
            raise ValidationError(
                f"Snapshot '{snapshot}' not found", field="snapshot_id"
            )
        if require_marker:
            marker = _read_json(root, COMPLETE_MARKER_NAME)
            if marker.get("format_version") != FORMAT_VERSION:
                raise ValidationError(
                    "Unsupported snapshot format_version", field="format_version"
                )
            if marker.get("snapshot_id") != snapshot:
                raise ValidationError(
                    "Snapshot marker id does not match its directory",
                    field="snapshot_id",
                )
            if marker.get("server_id") != segment:
                raise ValidationError(
                    "Snapshot marker server_id does not match its directory",
                    field="server_id",
                )

        manifest = _read_json(root, MANIFEST_FILENAME)
        if manifest.get("format_version") != FORMAT_VERSION:
            raise ValidationError(
                "Unsupported snapshot format_version", field="format_version"
            )
        if manifest.get("snapshot_id") != snapshot:
            raise ValidationError(
                "Snapshot manifest id does not match its directory", field="snapshot_id"
            )
        if manifest.get("server_id") != segment:
            raise ValidationError(
                "Snapshot manifest server_id does not match its directory",
                field="server_id",
            )
        return segment, snapshot, root, manifest

    # ------------------------------------------------------------------
    # Restore
    # ------------------------------------------------------------------

    def restore_snapshot(
        self,
        server_id: str,
        snapshot_id: str,
        target_dir: str | os.PathLike[str],
    ) -> int:
        _require_posix_host()
        _segment, snapshot, root, manifest = self._load_snapshot(
            server_id, snapshot_id, require_marker=True
        )
        entries = _manifest_entries(manifest)
        target = Path(target_dir)
        if target.is_symlink() or not target.is_dir():
            raise ValidationError(
                "target_dir must be an existing plain directory", field="target_dir"
            )

        # Verify every file before writing the first one.
        for entry in entries:
            digest, size = _hash_snapshot_file(root, entry["relpath"])
            if digest != entry["sha256"] or size != entry["size"]:
                raise ValidationError(
                    "Snapshot file digest mismatch",
                    field="sha256",
                    details={"relpath": entry["relpath"]},
                )

        restored = 0
        for entry in entries:
            relpath = entry["relpath"]
            src_fd = open_safe_path_fd(str(root), relpath)
            try:
                data = _read_fd(src_fd)
            finally:
                os.close(src_fd)
            if len(data) != entry["size"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise ValidationError(
                    "Snapshot file changed after verification",
                    field="sha256",
                    details={"relpath": relpath},
                )

            parent_rel = relpath.rpartition("/")[0]
            if parent_rel:
                _mkdir_private(target / parent_rel)
            tmp_rel = f"{relpath}.onx-restore-{uuid.uuid4().hex}.tmp"
            tmp_fd = open_safe_path_fd(
                str(target),
                tmp_rel,
                flags=os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                mode=0o600,
                allow_create_parents=True,
            )
            try:
                _write_fd(tmp_fd, data)
                if os.name == "posix":
                    os.fchmod(tmp_fd, entry["mode"] & 0o777)
                os.fsync(tmp_fd)
            finally:
                os.close(tmp_fd)

            tmp_path = target / tmp_rel
            dest_path = target / relpath
            os.replace(tmp_path, dest_path)
            _fsync_dir(dest_path.parent)
            restored += 1

        return restored

    # ------------------------------------------------------------------
    # Pin / unpin / delete
    # ------------------------------------------------------------------

    def unpin_snapshot(self, server_id: str, snapshot_id: str) -> None:
        _require_posix_host()
        _segment, _snapshot, root, manifest = self._load_snapshot(
            server_id, snapshot_id, require_marker=True
        )
        manifest["pinned"] = False
        atomic_write_private(
            root / MANIFEST_FILENAME, _json_bytes(manifest), mode=0o600
        )

    def delete_snapshot(self, server_id: str, snapshot_id: str) -> None:
        _require_posix_host()
        _segment, snapshot, root, manifest = self._load_snapshot(
            server_id, snapshot_id, require_marker=False
        )
        if bool(manifest.get("pinned")):
            raise BackupPinnedError(
                snapshot,
                message=f"Snapshot '{snapshot}' is pinned and cannot be deleted",
            )
        shutil.rmtree(root)
        _fsync_dir(root.parent)


__all__ = [
    "COMPLETE_MARKER_NAME",
    "FORMAT_VERSION",
    "MANIFEST_FILENAME",
    "ClassCSnapshotResult",
    "ClassCSnapshotService",
]
