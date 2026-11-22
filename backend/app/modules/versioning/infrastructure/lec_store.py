"""Loader Environment Cache (LEC) store with atomic publish and safe attach (P5.5).

The LEC is a host-level cache of pre-warmed loader trees. Entries are immutable
once published, contain only the loader payload subtrees, never hardlinks or
symlinks, and are attached to exports via a probe-verified reflink or a plain
copy under a per-device storage lock (OD-v8.4-2, OD-v8.6-8).
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]

from sqlalchemy import select

from app.core.allowlist import open_safe_path_fd, validate_canonical_relpath
from app.core.config import AppSettings
from app.core.exceptions import (
    InsufficientStorageError,
    LecMissingError,
    ValidationError,
)
from app.core.host_state import HostStateLayout, ensure_host_state_layout
from app.modules.versioning.domain.lockfile import (
    LecKeyParts,
    LockfileV21,
    parse_lec_key,
    parse_lockfile,
)
from app.modules.versioning.infrastructure.models import LoaderEnvCacheEntryModel

EXPORT_MARKER_NAME = ".onx-complete.json"
DEFAULT_GC_MIN_AGE_DAYS = 7
_COPY_HEADROOM = 1.10
_CHUNK_SIZE = 1024 * 1024
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")

ALLOWED_LEC_TREES: dict[str, tuple[str, ...]] = {
    "fabric": ("libraries", ".fabric/server"),
    "quilt": ("libraries",),
    "forge": ("libraries",),
    "neoforge": ("libraries",),
    "paper": ("cache", "versions", "libraries"),
}

FORBIDDEN_LEC_ROOT_FILES: frozenset[str] = frozenset(
    {
        "run.sh",
        "run.bat",
        "user_jvm_args.txt",
        "eula.txt",
        "installer.jar",
        "installer.jar.log",
        "forge-installer.jar",
        "neoforge-installer.jar",
        "server.jar",
        "ServerStarterJar",
        "serverstarter.jar",
    }
)


@dataclass(frozen=True)
class LecEntryMetadata:
    lec_key: str
    java_major: int
    file_count: int
    total_bytes: int
    complete_manifest_sha256: str
    completed_at: str


@dataclass(frozen=True)
class CacheGcReport:
    pruned_lec_keys: tuple[str, ...]
    pruned_cas_digests: tuple[str, ...]
    freed_bytes: int


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fsync_dir(path: Path) -> None:
    if os.name != "posix":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        with contextlib.suppress(OSError):
            os.fsync(fd)
    finally:
        os.close(fd)


def _read_fd(fd: int, max_bytes: int = 64 * 1024 * 1024) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(fd, _CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise OSError(errno.EFBIG, "file exceeds size limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _unix_args_relpath(parts: LecKeyParts) -> str:
    if parts.loader == "neoforge":
        if parts.version.startswith("1.20.1-"):
            return (
                f"libraries/net/minecraftforge/forge/{parts.version}/unix_args.txt"
            )
        return f"libraries/net/neoforged/neoforge/{parts.version}/unix_args.txt"
    if parts.loader == "forge":
        return f"libraries/net/minecraftforge/forge/{parts.mc}-{parts.version}/unix_args.txt"
    if parts.loader == "quilt":
        return f"libraries/org/quiltmc/quilt-loader/{parts.version}/unix_args.txt"
    raise ValidationError("Loader has no unix_args.txt contract", field="lec")


def _relative_to(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _allowed_relpath(relpath: str, trees: tuple[str, ...]) -> bool:
    return any(relpath == tree or relpath.startswith(f"{tree}/") for tree in trees)


def _remove_tree(path: Path) -> int:
    freed = 0
    if path.is_symlink() or path.is_file():
        with contextlib.suppress(OSError):
            freed += path.stat(follow_symlinks=False).st_size
        path.unlink(missing_ok=True)
        return freed
    for current, dirs, files in os.walk(path, topdown=False, followlinks=False):
        for name in files:
            target = Path(current) / name
            with contextlib.suppress(OSError):
                freed += target.lstat().st_size
            with contextlib.suppress(OSError):
                target.unlink()
        for name in dirs:
            with contextlib.suppress(OSError):
                (Path(current) / name).rmdir()
    with contextlib.suppress(OSError):
        path.rmdir()
    return freed


class LecStore:
    """Host Loader Environment Cache store."""

    def __init__(
        self,
        layout: HostStateLayout | None = None,
        *,
        settings: AppSettings | None = None,
    ) -> None:
        self._settings = settings
        self._layout = layout or ensure_host_state_layout(settings or AppSettings())

    @property
    def layout(self) -> HostStateLayout:
        return self._layout

    def entry_dir(self, lec_key: str) -> Path:
        norm = validate_canonical_relpath(lec_key)
        parse_lec_key(norm)
        return self._layout.lec / norm

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def is_ready(self, lec_key: str) -> bool:
        try:
            self.verify_entry(lec_key)
        except Exception:
            return False
        return True

    def verify_entry(self, lec_key: str) -> LecEntryMetadata:
        norm = validate_canonical_relpath(lec_key)
        parts = parse_lec_key(norm)
        entry = self._layout.lec / norm
        if entry.is_symlink() or not entry.is_dir():
            raise LecMissingError(lec_key=norm)
        marker_path = entry / EXPORT_MARKER_NAME
        if marker_path.is_symlink() or not marker_path.is_file():
            raise LecMissingError(lec_key=norm)
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValidationError("LEC completion marker is invalid", field="lec") from exc
        if not isinstance(marker, Mapping):
            raise ValidationError("LEC completion marker is invalid", field="lec")
        if marker.get("lec_key") != norm:
            raise ValidationError("LEC completion marker key mismatch", field="lec")

        payload = self._validate_payload(entry, parts, require_marker=True)
        if marker.get("complete_manifest_sha256") != payload.complete_manifest_sha256:
            raise ValidationError("LEC manifest hash mismatch", field="lec")
        if marker.get("file_count") != payload.file_count:
            raise ValidationError("LEC file count mismatch", field="lec")
        if marker.get("total_bytes") != payload.total_bytes:
            raise ValidationError("LEC total bytes mismatch", field="lec")
        completed_at = marker.get("completed_at")
        java_major = marker.get("java_major")
        if not isinstance(completed_at, str) or not isinstance(java_major, int):
            raise ValidationError("LEC completion marker is invalid", field="lec")
        return LecEntryMetadata(
            lec_key=norm,
            java_major=java_major,
            file_count=payload.file_count,
            total_bytes=payload.total_bytes,
            complete_manifest_sha256=payload.complete_manifest_sha256,
            completed_at=completed_at,
        )

    @dataclass(frozen=True)
    class _Payload:
        file_count: int
        total_bytes: int
        complete_manifest_sha256: str

    def _validate_payload(
        self,
        entry: Path,
        parts: LecKeyParts,
        *,
        require_marker: bool,
    ) -> LecStore._Payload:
        trees = ALLOWED_LEC_TREES.get(parts.loader)
        if not trees:
            raise ValidationError("Unsupported loader for LEC", field="lec")
        if entry.is_symlink():
            raise ValidationError("LEC tree must not contain symlinks", field="lec")

        lines: list[str] = []
        file_count = 0
        total_bytes = 0
        for current, dirs, files in os.walk(entry, topdown=True, followlinks=False):
            current_path = Path(current)
            for name in list(dirs) + list(files):
                candidate = current_path / name
                if candidate.is_symlink():
                    raise ValidationError("LEC tree must not contain symlinks", field="lec")
            for name in files:
                file_path = current_path / name
                rel = _relative_to(entry, file_path)
                stat_result = file_path.lstat()
                if not stat.S_ISREG(stat_result.st_mode):
                    raise ValidationError("LEC tree contains a non-regular file", field="lec")
                if stat_result.st_nlink != 1:
                    raise ValidationError("LEC files must not be hardlinked", field="lec")
                if rel == EXPORT_MARKER_NAME:
                    if require_marker:
                        continue
                    raise ValidationError("LEC staging tree must not contain a marker", field="lec")
                if not _allowed_relpath(rel, trees):
                    raise ValidationError("LEC payload boundary violated", field="lec")
                fd = open_safe_path_fd(str(entry), rel, flags=os.O_RDONLY)
                try:
                    digest = _sha256_bytes(_read_fd(fd))
                finally:
                    os.close(fd)
                lines.append(f"{rel}:{digest}")
                file_count += 1
                total_bytes += stat_result.st_size

        if parts.loader in {"forge", "neoforge", "quilt"}:
            unix_rel = _unix_args_relpath(parts)
            unix_path = entry / unix_rel
            if (
                unix_path.is_symlink()
                or not unix_path.is_file()
                or unix_path.stat().st_size <= 0
            ):
                raise ValidationError("LEC entry has no non-empty unix_args.txt", field="lec")

        if file_count == 0:
            raise ValidationError("LEC entry contains no loader payload files", field="lec")

        lines.sort()
        manifest = _sha256_bytes("\n".join(lines).encode("utf-8"))
        return LecStore._Payload(
            file_count=file_count,
            total_bytes=total_bytes,
            complete_manifest_sha256=manifest,
        )

    # ------------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------------

    def create_staging_dir(self, lec_key: str) -> Path:
        norm = validate_canonical_relpath(lec_key)
        parse_lec_key(norm)
        tmp_root = self._layout.lec / ".tmp"
        tmp_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        staging = tmp_root / f"build-{uuid.uuid4().hex}"
        staging.mkdir(mode=0o700)
        return staging

    @contextlib.contextmanager
    def _key_lock(self, lec_key: str):
        digest = hashlib.sha256(lec_key.encode("utf-8")).hexdigest()[:16]
        lock_path = self._layout.locks / f"lec-{digest}.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            if fcntl is not None:
                with contextlib.suppress(OSError):
                    fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _purge_builder_root(self, staging: Path, parts: LecKeyParts) -> None:
        trees = ALLOWED_LEC_TREES[parts.loader]

        def prune(directory: Path) -> None:
            for child in list(directory.iterdir()):
                rel = _relative_to(staging, child)
                if any(tree == rel or tree.startswith(f"{rel}/") for tree in trees):
                    if child.is_dir() and not child.is_symlink():
                        prune(child)
                    continue
                if any(rel == tree or rel.startswith(f"{tree}/") for tree in trees):
                    if child.is_dir() and not child.is_symlink():
                        prune(child)
                    continue
                _remove_tree(child)

        prune(staging)
        marker = staging / EXPORT_MARKER_NAME
        if marker.exists() or marker.is_symlink():
            _remove_tree(marker)
        for forbidden in FORBIDDEN_LEC_ROOT_FILES:
            target = staging / forbidden
            if target.exists() or target.is_symlink():
                _remove_tree(target)

    def _fsync_tree(self, entry: Path) -> None:
        if os.name != "posix":
            return
        for current, _dirs, files in os.walk(entry, topdown=False, followlinks=False):
            for name in files:
                file_path = Path(current) / name
                fd = os.open(file_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            _fsync_dir(Path(current))

    def _write_marker(
        self,
        entry: Path,
        *,
        lec_key: str,
        java_major: int,
        payload: LecStore._Payload,
        completed_at: datetime,
    ) -> None:
        marker = {
            "completed_at": _iso(completed_at),
            "complete_manifest_sha256": payload.complete_manifest_sha256,
            "file_count": payload.file_count,
            "java_major": int(java_major),
            "lec_key": lec_key,
            "total_bytes": payload.total_bytes,
        }
        data = json.dumps(marker, sort_keys=True, separators=(",", ":")).encode("utf-8")
        fd = open_safe_path_fd(
            str(entry),
            EXPORT_MARKER_NAME,
            flags=os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            mode=0o644,
        )
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        _fsync_dir(entry)

    async def publish_staged_entry(
        self,
        staging_dir: str | Path,
        lec_key: str,
        *,
        java_major: int,
        session: Any | None = None,
        completed_at: datetime | None = None,
    ) -> LecEntryMetadata:
        norm = validate_canonical_relpath(lec_key)
        parts = parse_lec_key(norm)
        staging = Path(staging_dir)
        if staging.is_symlink() or not staging.is_dir():
            raise ValidationError("LEC staging directory is missing", field="lec")

        with self._key_lock(norm):
            self._purge_builder_root(staging, parts)
            payload = self._validate_payload(staging, parts, require_marker=False)
            self._fsync_tree(staging)
            timestamp = completed_at or _utc_now()
            self._write_marker(
                staging,
                lec_key=norm,
                java_major=java_major,
                payload=payload,
                completed_at=timestamp,
            )

            self._layout.lec.mkdir(parents=True, exist_ok=True, mode=0o700)
            target = self._layout.lec / norm
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            displaced: Path | None = None
            if target.exists() or target.is_symlink():
                displaced = self._layout.lec / ".tmp" / f"old-{uuid.uuid4().hex}"
                displaced.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                os.replace(target, displaced)
            try:
                os.replace(staging, target)
            except BaseException:
                if displaced is not None and not target.exists():
                    with contextlib.suppress(OSError):
                        os.replace(displaced, target)
                raise
            _fsync_dir(target.parent)
            if displaced is not None:
                _remove_tree(displaced)

        if session is not None:
            await self._upsert_row(
                session,
                lec_key=norm,
                parts=parts,
                java_major=java_major,
                payload=payload,
                last_used_at=timestamp,
            )

        return LecEntryMetadata(
            lec_key=norm,
            java_major=int(java_major),
            file_count=payload.file_count,
            total_bytes=payload.total_bytes,
            complete_manifest_sha256=payload.complete_manifest_sha256,
            completed_at=_iso(timestamp),
        )

    async def _upsert_row(
        self,
        session: Any,
        *,
        lec_key: str,
        parts: LecKeyParts,
        java_major: int,
        payload: LecStore._Payload,
        last_used_at: datetime,
    ) -> None:
        row = await session.get(LoaderEnvCacheEntryModel, lec_key)
        if row is None:
            row = LoaderEnvCacheEntryModel(
                lec_key=lec_key,
                loader_id=parts.loader,
                mc_version=parts.mc,
                loader_version=parts.version,
                installer_version=parts.installer,
            )
            session.add(row)
        # Legacy SQLAlchemy ``Column`` attributes are typed as ``Column[T]``;
        # cast for ORM writes until the models migrate to ``Mapped[T]``.
        writable = cast(Any, row)
        writable.status = "ready"
        writable.size_bytes = payload.total_bytes
        writable.file_count = payload.file_count
        writable.java_major = int(java_major)
        writable.complete_manifest_sha256 = payload.complete_manifest_sha256
        writable.last_used_at = last_used_at
        writable.updated_at = last_used_at
        await session.flush()

    async def touch_last_used(self, session: Any, lec_key: str) -> None:
        norm = validate_canonical_relpath(lec_key)
        parse_lec_key(norm)
        row = await session.get(LoaderEnvCacheEntryModel, norm)
        if row is None:
            return
        now = _utc_now()
        row.last_used_at = now
        row.updated_at = now
        await session.flush()

    # ------------------------------------------------------------------
    # Attach
    # ------------------------------------------------------------------

    @contextlib.contextmanager
    def _copy_lock(self, st_dev: int):
        lock_path = self._layout.locks / f"copy-{st_dev}.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            if fcntl is not None:
                with contextlib.suppress(OSError):
                    fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def attach_to_target(self, lec_key: str, target_dir: str | Path) -> int:
        norm = validate_canonical_relpath(lec_key)
        parts = parse_lec_key(norm)
        self.verify_entry(norm)
        entry = self._layout.lec / norm
        trees = ALLOWED_LEC_TREES[parts.loader]
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)

        required = 0
        sources: list[tuple[str, Path]] = []
        for tree in trees:
            source = entry / tree
            if source.is_symlink():
                raise ValidationError("LEC tree must not contain symlinks", field="lec")
            if not source.is_dir():
                continue
            for current, _dirs, files in os.walk(source, topdown=True, followlinks=False):
                for name in files:
                    file_path = Path(current) / name
                    if file_path.is_symlink():
                        raise ValidationError(
                            "LEC tree must not contain symlinks", field="lec"
                        )
                    rel = _relative_to(entry, file_path)
                    sources.append((rel, file_path))
                    required += file_path.lstat().st_size
        if not sources:
            raise LecMissingError(
                lec_key=norm,
                message=f"LEC missing: '{norm}' does not contain required loader files",
            )

        copied = 0
        st_dev = target.stat().st_dev
        with self._copy_lock(st_dev):
            free = shutil.disk_usage(target).free
            if free < int(required * _COPY_HEADROOM) + 1:
                raise InsufficientStorageError(
                    details={"required_bytes": int(required * _COPY_HEADROOM), "free_bytes": free}
                )
            for rel, source in sources:
                dest = target / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists() or dest.is_symlink():
                    _remove_tree(dest)
                src_fd = open_safe_path_fd(str(entry), rel, flags=os.O_RDONLY)
                try:
                    dst_fd = open_safe_path_fd(
                        str(target),
                        rel,
                        flags=os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                        mode=0o644,
                        allow_create_parents=True,
                    )
                    try:
                        self._copy_fd(src_fd, dst_fd, source.lstat().st_size)
                        if os.fstat(dst_fd).st_nlink != 1:
                            raise ValidationError(
                                "Attached LEC files must not be hardlinked", field="lec"
                            )
                    finally:
                        os.close(dst_fd)
                finally:
                    os.close(src_fd)
                copied += 1
        return copied

    @staticmethod
    def _copy_fd(source_fd: int, destination_fd: int, size: int) -> None:
        if fcntl is not None:
            try:
                fcntl.ioctl(destination_fd, 0x40049409, source_fd)
                if os.fstat(destination_fd).st_size == size:
                    return
            except OSError:
                pass
        with contextlib.suppress(OSError):
            os.ftruncate(destination_fd, 0)
        os.lseek(destination_fd, 0, os.SEEK_SET)
        os.lseek(source_fd, 0, os.SEEK_SET)
        remaining = size
        while remaining > 0:
            chunk = os.read(source_fd, min(_CHUNK_SIZE, remaining))
            if not chunk:
                raise OSError(errno.EIO, "unexpected end of source file")
            written = 0
            while written < len(chunk):
                n = os.write(destination_fd, chunk[written:])
                if n <= 0:
                    raise OSError(errno.EIO, "short write")
                written += n
            remaining -= len(chunk)
        if os.fstat(destination_fd).st_size != size:
            raise OSError(errno.EIO, "copied file has the wrong size")

    # ------------------------------------------------------------------
    # Eviction
    # ------------------------------------------------------------------

    def _collect_lockfile_references(
        self, lockfiles: Iterable[Path]
    ) -> tuple[set[str], set[str]]:
        lec_keys: set[str] = set()
        cas_digests: set[str] = set()
        for path in lockfiles:
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            lockfile = self._parse_lockfile_bytes(raw)
            if lockfile is None:
                continue
            self._accumulate_refs(lockfile, lec_keys, cas_digests)
        return lec_keys, cas_digests

    @staticmethod
    def _parse_lockfile_bytes(raw: bytes) -> LockfileV21 | None:
        try:
            return parse_lockfile(raw)
        except Exception:
            return None

    @staticmethod
    def _accumulate_refs(
        lockfile: LockfileV21, lec_keys: set[str], cas_digests: set[str]
    ) -> None:
        if lockfile.lec is not None:
            with contextlib.suppress(Exception):
                parse_lec_key(lockfile.lec.key)
                lec_keys.add(lockfile.lec.key)
        for entry in lockfile.files:
            if _SHA256_RE.match(entry.sha256):
                cas_digests.add(entry.sha256)
        for digest in lockfile.base_overrides.values():
            if _SHA256_RE.match(digest):
                cas_digests.add(digest)

    def _git_lockfiles(self) -> list[bytes]:
        blobs: list[bytes] = []
        repos_root = self._layout.repos
        if not repos_root.is_dir():
            return blobs
        for repo in sorted(repos_root.iterdir()):
            if not repo.is_dir() or repo.is_symlink():
                continue
            try:
                refs = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(repo),
                        "for-each-ref",
                        "--format=%(refname)",
                        "refs/heads",
                    ],
                    check=False,
                    capture_output=True,
                    timeout=30,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            if refs.returncode != 0:
                continue
            for ref in refs.stdout.decode("utf-8", "replace").splitlines():
                ref = ref.strip()
                if not ref:
                    continue
                try:
                    blob = subprocess.run(
                        ["git", "-C", str(repo), "show", f"{ref}:onx-jars.lock.json"],
                        check=False,
                        capture_output=True,
                        timeout=30,
                    )
                except (OSError, subprocess.SubprocessError):
                    continue
                if blob.returncode == 0 and blob.stdout:
                    blobs.append(blob.stdout)
        return blobs

    def _iter_lec_entry_dirs(self) -> list[tuple[str, Path]]:
        entries: list[tuple[str, Path]] = []
        if not self._layout.lec.is_dir():
            return entries
        for current, dirs, _files in os.walk(self._layout.lec, topdown=True, followlinks=False):
            current_path = Path(current)
            dirs[:] = sorted(
                d
                for d in dirs
                if not (current_path == self._layout.lec and d == ".tmp")
                and not (current_path / d).is_symlink()
            )
            if current_path == self._layout.lec:
                continue
            rel = _relative_to(self._layout.lec, current_path)
            try:
                norm = validate_canonical_relpath(rel)
                parse_lec_key(norm)
            except Exception:
                continue
            entries.append((norm, current_path))
            dirs[:] = []
        return entries

    def _prune_empty_lec_parents(self, removed: Path) -> None:
        parent = removed.parent
        while parent != self._layout.lec and self._layout.lec in parent.parents:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent

    def _collect_all_references(self, settings: AppSettings) -> tuple[set[str], set[str]]:
        lockfiles: list[Path] = []
        server_meta = self._layout.server_meta
        if server_meta.is_dir():
            lockfiles.extend(sorted(server_meta.glob("*/onx-jars.lock.json")))
        servers_dir = Path(settings.servers_data_dir)
        if servers_dir.is_dir():
            lockfiles.extend(sorted(servers_dir.glob("*/.onx-manager/onx-jars.lock.json")))
            lockfiles.extend(sorted(servers_dir.glob("*/onx-jars.lock.json")))
        lec_keys, cas_digests = self._collect_lockfile_references(lockfiles)
        for raw in self._git_lockfiles():
            lockfile = self._parse_lockfile_bytes(raw)
            if lockfile is not None:
                self._accumulate_refs(lockfile, lec_keys, cas_digests)
        return lec_keys, cas_digests

    async def gc_unused_caches(
        self,
        *,
        min_age_days: int = DEFAULT_GC_MIN_AGE_DAYS,
        session: Any | None = None,
        now: datetime | None = None,
        settings: AppSettings | None = None,
    ) -> CacheGcReport:
        active_settings = settings or self._settings or AppSettings()
        current = now or _utc_now()
        cutoff = current - timedelta(days=min_age_days)
        referenced_lec_keys, referenced_cas = self._collect_all_references(active_settings)

        rows: dict[str, LoaderEnvCacheEntryModel] = {}
        if session is not None:
            result = await session.execute(select(LoaderEnvCacheEntryModel))
            rows = {
                row.lec_key: row
                for row in result.scalars().all()
            }

        pruned_lec: list[str] = []
        freed = 0
        for norm, entry in self._iter_lec_entry_dirs():
            if norm in referenced_lec_keys:
                continue
            row = rows.get(norm)
            last_used: datetime | None = None
            if row is not None:
                raw_last_used = cast(Any, row).last_used_at
                if isinstance(raw_last_used, datetime):
                    last_used = (
                        raw_last_used
                        if raw_last_used.tzinfo
                        else raw_last_used.replace(tzinfo=UTC)
                    )
            if last_used is None:
                marker = entry / EXPORT_MARKER_NAME
                try:
                    stamp = marker.stat().st_mtime
                except OSError:
                    try:
                        stamp = entry.stat().st_mtime
                    except OSError:
                        stamp = current.timestamp()
                last_used = datetime.fromtimestamp(stamp, tz=UTC)
            if last_used > cutoff:
                continue
            freed += _remove_tree(entry)
            self._prune_empty_lec_parents(entry)
            pruned_lec.append(norm)
            if session is not None and row is not None:
                await session.delete(row)

        pruned_cas: list[str] = []
        sha_root = self._layout.cas / "sha256"
        if sha_root.is_dir():
            for prefix in sorted(sha_root.iterdir()):
                if not prefix.is_dir() or prefix.is_symlink():
                    continue
                for blob in sorted(prefix.iterdir()):
                    if blob.is_symlink() or not blob.is_file():
                        continue
                    digest = blob.name
                    if not _SHA256_RE.match(digest) or digest in referenced_cas:
                        continue
                    try:
                        mtime = blob.lstat().st_mtime
                    except OSError:
                        continue
                    if datetime.fromtimestamp(mtime, tz=UTC) > cutoff:
                        continue
                    size = blob.lstat().st_size
                    with contextlib.suppress(OSError):
                        blob.unlink()
                        freed += size
                        pruned_cas.append(digest)

        if session is not None:
            await session.flush()

        return CacheGcReport(
            pruned_lec_keys=tuple(sorted(pruned_lec)),
            pruned_cas_digests=tuple(sorted(pruned_cas)),
            freed_bytes=freed,
        )


__all__ = [
    "ALLOWED_LEC_TREES",
    "CacheGcReport",
    "DEFAULT_GC_MIN_AGE_DAYS",
    "EXPORT_MARKER_NAME",
    "FORBIDDEN_LEC_ROOT_FILES",
    "LecEntryMetadata",
    "LecStore",
]
