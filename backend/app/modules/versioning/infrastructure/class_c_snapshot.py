"""Encrypted Class-C snapshot vault (P3-3, ``FORMAT_VERSION = 2``).

Snapshots live at ``<host_state>/class-c-vault/<server_id>/<snapshot_id>``.
Every Class-C file is encrypted with AES-256-GCM in 64 KiB plaintext chunks
under a fresh per-snapshot DEK; the DEK is wrapped by the active master KEK and
recorded in ``manifest.json``. The ``class_c_snapshots`` SQL table is the
authoritative ledger: creation writes the snapshot to disk first and inserts the
row last, while restore verifies the on-disk manifest SHA-256 against the row
before decrypting anything.

``FORMAT_VERSION = 1`` plain snapshots are retired. They fail closed with
``ValidationError`` and must be removed by the operator before upgrading to
Alembic ``b1e2100000027`` (see ``vault_crypto.py`` for the runbook).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import stat
import uuid
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import Engine, create_engine, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, sessionmaker

from app.core.allowlist import classify, open_safe_path_fd, validate_canonical_relpath
from app.core.exceptions import (
    BackupPinnedError,
    CasUnsupportedPlatformError,
    ConflictError,
    MasterKekVersionMismatchError,
    ValidationError,
)
from app.core.host_state import HostStateLayout, validate_server_segment
from app.core.persistence.base import Base
from app.modules.versioning.infrastructure.fs_atomic import atomic_write_private
from app.modules.versioning.infrastructure.models import (
    ClassCSnapshotModel,
)
from app.modules.versioning.infrastructure.vault_crypto import load_master_kek

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "manifest.json"
COMPLETE_MARKER_NAME = ".onx-complete.json"
BLOBS_DIRNAME = "blobs"
FORMAT_VERSION = 2
CHUNK_SIZE = 65536
MAX_UNPINNED_SNAPSHOTS = 10
_STAGING_PREFIX = ".onx-snapshot-"
MAX_CHUNK_CIPHERTEXT = CHUNK_SIZE + 16
MIN_CHUNK_CIPHERTEXT = 16

_COPY_CHUNK = 1024 * 1024
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_HEX24_RE = re.compile(r"\A[0-9a-f]{24}\Z")
_HEX96_RE = re.compile(r"\A[0-9a-f]{96}\Z")
_STATUSES = frozenset({"active", "missing"})


@dataclass(frozen=True)
class ClassCSnapshotResult:
    snapshot_id: str
    root: Path
    manifest_path: Path
    file_count: int
    total_bytes: int
    pinned: bool
    manifest_sha256: str = ""
    kek_version: int = 0


@dataclass(frozen=True)
class ClassCSnapshotRow:
    snapshot_id: str
    server_id: str
    created_at: datetime | None
    manifest_sha256: str
    kek_version: int
    file_count: int
    total_bytes: int
    pinned: bool
    status: str


@dataclass(frozen=True)
class ClassCReconcileSummary:
    removed_directories: tuple[str, ...] = ()
    marked_missing: tuple[str, ...] = ()

    @property
    def removed_dirs(self) -> tuple[str, ...]:
        return self.removed_directories

    @property
    def missing_snapshots(self) -> tuple[str, ...]:
        return self.marked_missing


@dataclass(frozen=True)
class ClassCGcRoots:
    snapshot_ids: frozenset[str]
    snapshot_dirs: frozenset[Path]
    manifest_sha256s: frozenset[str]
    blob_paths: frozenset[Path]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _to_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _aad_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def derive_chunk_nonce(base_nonce: bytes, chunk_index: int) -> bytes:
    """Derive a deterministic per-chunk nonce from a random 96-bit base nonce."""
    if len(base_nonce) != 12 or chunk_index < 0 or chunk_index >= (1 << 32):
        raise ValidationError("Invalid chunk nonce parameters", field="nonce")
    low32 = int.from_bytes(base_nonce[8:12], "big") ^ chunk_index
    return base_nonce[:8] + low32.to_bytes(4, "big")


def chunk_aad(
    server_id: str,
    snapshot_id: str,
    relpath: str,
    chunk_index: int,
    *,
    is_final: bool,
) -> bytes:
    return _aad_bytes(
        {
            "chunk_index": chunk_index,
            "format_version": FORMAT_VERSION,
            "is_final": is_final,
            "relpath": relpath,
            "server_id": server_id,
            "snapshot_id": snapshot_id,
        }
    )


def dek_wrap_aad(server_id: str, snapshot_id: str, kek_version: int) -> bytes:
    return _aad_bytes(
        {
            "format_version": FORMAT_VERSION,
            "kek_version": kek_version,
            "purpose": "class_c_snapshot_dek",
            "server_id": server_id,
            "snapshot_id": snapshot_id,
        }
    )


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


def _read_raw(root: Path, name: str) -> bytes:
    try:
        fd = open_safe_path_fd(str(root), name)
    except FileNotFoundError as exc:
        raise ValidationError(f"Snapshot is missing {name}", field="snapshot") from exc
    except (OSError, ValueError) as exc:
        raise ValidationError(f"Unable to open snapshot file '{name}'", field="snapshot") from exc
    try:
        return _read_fd(fd)
    finally:
        os.close(fd)


def _read_json(root: Path, name: str) -> dict[str, Any]:
    raw = _read_raw(root, name)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(
            f"Snapshot file '{name}' is not valid JSON", field="snapshot"
        ) from exc
    if not isinstance(payload, dict):
        raise ValidationError(f"Snapshot file '{name}' must be a JSON object", field="snapshot")
    return payload


def _canonical_relpath(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError("Snapshot manifest has an invalid path", field=field)
    try:
        return validate_canonical_relpath(value)
    except ValueError as exc:
        raise ValidationError("Snapshot manifest has an unsafe path", field=field) from exc


def _manifest_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list):
        raise ValidationError("Snapshot manifest 'files' must be a list", field="snapshot")

    entries: list[dict[str, Any]] = []
    for raw in raw_files:
        if not isinstance(raw, dict):
            raise ValidationError("Snapshot manifest entry must be an object", field="snapshot")
        relpath = _canonical_relpath(raw.get("relpath"), field="snapshot")
        blob_relpath = _canonical_relpath(raw.get("blob_relpath"), field="snapshot")
        if not blob_relpath.startswith(f"{BLOBS_DIRNAME}/") or not blob_relpath.endswith(".enc"):
            raise ValidationError("Snapshot blob path is invalid", field="snapshot")
        digest = raw.get("sha256")
        ciphertext_digest = raw.get("ciphertext_sha256")
        base_nonce = raw.get("base_nonce")
        chunk_count = raw.get("chunk_count")
        ciphertext_size = raw.get("ciphertext_size")
        mode = raw.get("mode")
        size = raw.get("size")
        if not isinstance(digest, str) or not _SHA256_RE.match(digest):
            raise ValidationError("Snapshot manifest has an invalid sha256", field="snapshot")
        if not isinstance(ciphertext_digest, str) or not _SHA256_RE.match(ciphertext_digest):
            raise ValidationError(
                "Snapshot manifest has an invalid ciphertext_sha256", field="snapshot"
            )
        if not isinstance(base_nonce, str) or not _HEX24_RE.match(base_nonce):
            raise ValidationError("Snapshot manifest has an invalid base_nonce", field="snapshot")
        if (
            not isinstance(chunk_count, int)
            or isinstance(chunk_count, bool)
            or chunk_count < 1
        ):
            raise ValidationError("Snapshot manifest has an invalid chunk_count", field="snapshot")
        if (
            not isinstance(ciphertext_size, int)
            or isinstance(ciphertext_size, bool)
            or ciphertext_size < MIN_CHUNK_CIPHERTEXT
        ):
            raise ValidationError(
                "Snapshot manifest has an invalid ciphertext_size", field="snapshot"
            )
        if not isinstance(mode, int) or isinstance(mode, bool) or mode < 0:
            raise ValidationError("Snapshot manifest has an invalid mode", field="snapshot")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ValidationError("Snapshot manifest has an invalid size", field="snapshot")
        entries.append(
            {
                "relpath": relpath,
                "blob_relpath": blob_relpath,
                "base_nonce": bytes.fromhex(base_nonce),
                "chunk_count": chunk_count,
                "ciphertext_sha256": ciphertext_digest,
                "ciphertext_size": ciphertext_size,
                "mode": mode,
                "sha256": digest,
                "size": size,
            }
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


def _row_from_model(model: ClassCSnapshotModel) -> ClassCSnapshotRow:
    return ClassCSnapshotRow(
        snapshot_id=str(model.snapshot_id),
        server_id=str(model.server_id),
        created_at=_to_utc(model.created_at),
        manifest_sha256=str(model.manifest_sha256),
        kek_version=int(model.kek_version or 1),
        file_count=int(model.file_count or 0),
        total_bytes=int(model.total_bytes or 0),
        pinned=bool(model.pinned),
        status=str(model.status or "active"),
    )


def _create_tables_sync(bind: Engine | Any) -> None:
    # Importing the server and auth models keeps ``servers`` (and its
    # ``users.owner_id`` target) in Base.metadata so the
    # ``ForeignKey("servers.id")`` on both P3-3 tables always resolves.
    import app.modules.auth.infrastructure.models  # noqa: F401
    import app.modules.server.infrastructure.models  # noqa: F401

    Base.metadata.create_all(bind=bind)


def _run_async(coro_factory: Callable[[], Any]) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_factory())
    with ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="class-c-ledger"
    ) as pool:
        return pool.submit(lambda: asyncio.run(coro_factory())).result()


class _LedgerRunner:
    """Resolve a usable SQL session binding for the P3-3 ledger tables.

    Resolution order (D-P33-3): explicit sync factory, file-backed SQLite via a
    derived sync engine, in-memory SQLite through the async factory, then a
    standalone file-backed fallback under ``layout.root``.
    """

    def __init__(
        self,
        layout: HostStateLayout,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        sync_session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self._layout = layout
        self._session_factory = session_factory
        self._sync_session_factory = sync_session_factory
        self._owned_engine: Engine | None = None
        self._mode: str | None = None
        self._async_ready = False
        self._sync_ready = False

    # -- binding resolution -------------------------------------------------

    def _global_url(self) -> Any:
        from app.core.persistence.db import database

        try:
            return database.engine.url
        except RuntimeError:
            return None

    def _derive_sync(self, url: Any) -> None:
        self._owned_engine = create_engine(
            url.set(drivername="sqlite"),
            connect_args={"check_same_thread": False, "timeout": 30.0},
        )
        self._sync_session_factory = sessionmaker(
            bind=self._owned_engine, expire_on_commit=False
        )

    def _standalone(self) -> None:
        db_path = self._layout.root / "class-c-vault.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._owned_engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False, "timeout": 30.0},
        )
        self._sync_session_factory = sessionmaker(
            bind=self._owned_engine, expire_on_commit=False
        )

    @property
    def mode(self) -> str:
        if self._mode is not None:
            return self._mode

        if self._sync_session_factory is not None:
            self._mode = "sync"
            return self._mode

        url = None
        if self._session_factory is not None:
            bind = self._session_factory.kw.get("bind")
            if bind is not None:
                url = bind.url
        if url is None and self._session_factory is not None:
            url = self._global_url()
        if url is None:
            url = self._global_url()

        if url is None:
            self._standalone()
            self._mode = "sync"
            return self._mode

        backend = url.get_backend_name()
        if backend == "sqlite":
            database = url.database or ""
            if database not in (None, "", ":memory:"):
                self._derive_sync(url)
                self._mode = "sync"
                return self._mode
            if self._session_factory is None:
                from app.core.persistence.db import database as global_db

                self._session_factory = global_db.session_factory
            self._mode = "async"
            return self._mode

        raise RuntimeError(
            "Snapshot ledger requires a sync_session_factory for non-SQLite backends"
        )

    @property
    def sync_factory(self) -> sessionmaker[Session]:
        if self._sync_session_factory is None:
            self._derive_sync(self._global_url())
        assert self._sync_session_factory is not None
        if not self._sync_ready:
            _create_tables_sync(self._sync_session_factory.kw["bind"])
            self._sync_ready = True
        return self._sync_session_factory

    @property
    def async_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            from app.core.persistence.db import database

            self._session_factory = database.session_factory
        assert self._session_factory is not None
        if not self._async_ready:
            factory = self._session_factory

            async def _create() -> None:
                async with factory() as session:
                    connection = await session.connection()
                    await connection.run_sync(_create_tables_sync)
                    await session.commit()

            _run_async(lambda: _create())
            self._async_ready = True
        return self._session_factory

    @contextmanager
    def sync_session(self) -> Iterator[Session]:
        with self.sync_factory() as session:
            yield session

    def close(self) -> None:
        if self._owned_engine is not None:
            self._owned_engine.dispose()
            self._owned_engine = None


class ClassCSnapshotRepository:
    """SQL ledger for encrypted Class-C snapshots."""

    def __init__(
        self,
        layout: HostStateLayout,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        sync_session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self._layout = layout
        self._session_factory = session_factory
        self._sync_session_factory = sync_session_factory
        self._ledger = _LedgerRunner(
            layout,
            session_factory=session_factory,
            sync_session_factory=sync_session_factory,
        )

    @property
    def _is_async(self) -> bool:
        return self._ledger.mode == "async"

    def close(self) -> None:
        self._ledger.close()

    # -- writes -------------------------------------------------------------

    def create_snapshot(
        self,
        *,
        server_id: str,
        snapshot_id: str,
        manifest_sha256: str,
        kek_version: int,
        file_count: int,
        total_bytes: int,
        pinned: bool,
        created_at: datetime | None = None,
    ) -> ClassCSnapshotRow:
        segment = validate_server_segment(server_id)
        moment = _to_utc(created_at) or datetime.now(UTC)
        values = {
            "snapshot_id": snapshot_id,
            "server_id": segment,
            "created_at": moment,
            "manifest_sha256": manifest_sha256,
            "kek_version": int(kek_version),
            "file_count": int(file_count),
            "total_bytes": int(total_bytes),
            "pinned": bool(pinned),
            "status": "active",
        }
        if self._is_async:
            factory = self._ledger.async_factory

            async def _create() -> ClassCSnapshotRow:
                async with factory() as session:
                    session.add(ClassCSnapshotModel(**values))
                    await session.commit()
                return ClassCSnapshotRow(
                    snapshot_id=snapshot_id,
                    server_id=segment,
                    created_at=moment,
                    manifest_sha256=manifest_sha256,
                    kek_version=int(kek_version),
                    file_count=int(file_count),
                    total_bytes=int(total_bytes),
                    pinned=bool(pinned),
                    status="active",
                )

            return _run_async(_create)

        with self._ledger.sync_session() as session:
            session.add(ClassCSnapshotModel(**values))
            session.commit()
        return ClassCSnapshotRow(
            snapshot_id=snapshot_id,
            server_id=segment,
            created_at=moment,
            manifest_sha256=manifest_sha256,
            kek_version=int(kek_version),
            file_count=int(file_count),
            total_bytes=int(total_bytes),
            pinned=bool(pinned),
            status="active",
        )

    def update_snapshot(
        self,
        server_id: str,
        snapshot_id: str,
        *,
        pinned: bool | None = None,
        manifest_sha256: str | None = None,
        status: str | None = None,
    ) -> ClassCSnapshotRow | None:
        segment = validate_server_segment(server_id)
        values: dict[str, Any] = {}
        if pinned is not None:
            values["pinned"] = bool(pinned)
        if manifest_sha256 is not None:
            values["manifest_sha256"] = manifest_sha256
        if status is not None:
            if status not in _STATUSES:
                raise ValidationError("Unknown Class-C snapshot status", field="status")
            values["status"] = status
        if not values:
            return self.get_snapshot(segment, snapshot_id)

        if self._is_async:
            factory = self._ledger.async_factory

            async def _update() -> ClassCSnapshotRow | None:
                async with factory() as session:
                    await session.execute(
                        update(ClassCSnapshotModel)
                        .where(
                            ClassCSnapshotModel.server_id == segment,
                            ClassCSnapshotModel.snapshot_id == snapshot_id,
                        )
                        .values(**values)
                        .execution_options(synchronize_session=False)
                    )
                    row = (
                        await session.execute(
                            select(ClassCSnapshotModel).where(
                                ClassCSnapshotModel.server_id == segment,
                                ClassCSnapshotModel.snapshot_id == snapshot_id,
                            )
                        )
                    ).scalar_one_or_none()
                    await session.commit()
                return None if row is None else _row_from_model(row)

            return _run_async(_update)

        with self._ledger.sync_session() as session:
            session.execute(
                update(ClassCSnapshotModel)
                .where(
                    ClassCSnapshotModel.server_id == segment,
                    ClassCSnapshotModel.snapshot_id == snapshot_id,
                )
                .values(**values)
                .execution_options(synchronize_session=False)
            )
            row = session.execute(
                select(ClassCSnapshotModel).where(
                    ClassCSnapshotModel.server_id == segment,
                    ClassCSnapshotModel.snapshot_id == snapshot_id,
                )
            ).scalar_one_or_none()
            session.commit()
        return None if row is None else _row_from_model(row)

    def delete_snapshot(self, server_id: str, snapshot_id: str) -> bool:
        segment = validate_server_segment(server_id)
        if self._is_async:
            factory = self._ledger.async_factory

            async def _delete() -> bool:
                async with factory() as session:
                    result = await session.execute(
                        delete(ClassCSnapshotModel).where(
                            ClassCSnapshotModel.server_id == segment,
                            ClassCSnapshotModel.snapshot_id == snapshot_id,
                        )
                    )
                    await session.commit()
                    return bool(result.rowcount)

            return _run_async(_delete)

        with self._ledger.sync_session() as session:
            result = session.execute(
                delete(ClassCSnapshotModel).where(
                    ClassCSnapshotModel.server_id == segment,
                    ClassCSnapshotModel.snapshot_id == snapshot_id,
                )
            )
            session.commit()
        return bool(result.rowcount)

    # -- reads --------------------------------------------------------------

    def get_snapshot(self, server_id: str, snapshot_id: str) -> ClassCSnapshotRow | None:
        segment = validate_server_segment(server_id)
        if self._is_async:
            factory = self._ledger.async_factory

            async def _get() -> ClassCSnapshotRow | None:
                async with factory() as session:
                    row = (
                        await session.execute(
                            select(ClassCSnapshotModel).where(
                                ClassCSnapshotModel.server_id == segment,
                                ClassCSnapshotModel.snapshot_id == snapshot_id,
                            )
                        )
                    ).scalar_one_or_none()
                return None if row is None else _row_from_model(row)

            return _run_async(_get)

        with self._ledger.sync_session() as session:
            row = session.execute(
                select(ClassCSnapshotModel).where(
                    ClassCSnapshotModel.server_id == segment,
                    ClassCSnapshotModel.snapshot_id == snapshot_id,
                )
            ).scalar_one_or_none()
        return None if row is None else _row_from_model(row)

    def list_active(self, server_id: str | None = None) -> list[ClassCSnapshotRow]:
        segment = None if server_id is None else validate_server_segment(server_id)
        if self._is_async:
            factory = self._ledger.async_factory

            async def _list() -> list[ClassCSnapshotRow]:
                async with factory() as session:
                    statement = select(ClassCSnapshotModel).where(
                        ClassCSnapshotModel.status == "active"
                    )
                    if segment is not None:
                        statement = statement.where(
                            ClassCSnapshotModel.server_id == segment
                        )
                    rows = (
                        (
                            await session.execute(
                                statement.order_by(
                                    ClassCSnapshotModel.created_at.desc(),
                                    ClassCSnapshotModel.snapshot_id.desc(),
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                return [_row_from_model(row) for row in rows]

            return _run_async(_list)

        with self._ledger.sync_session() as session:
            statement = select(ClassCSnapshotModel).where(
                ClassCSnapshotModel.status == "active"
            )
            if segment is not None:
                statement = statement.where(ClassCSnapshotModel.server_id == segment)
            rows = (
                session.execute(
                    statement.order_by(
                        ClassCSnapshotModel.created_at.desc(),
                        ClassCSnapshotModel.snapshot_id.desc(),
                    )
                )
                .scalars()
                .all()
            )
        return [_row_from_model(row) for row in rows]

    # -- retention ----------------------------------------------------------

    def prune_unpinned_snapshots(
        self,
        server_id: str,
        *,
        max_unpinned: int = MAX_UNPINNED_SNAPSHOTS,
        vault_root: Path | None = None,
    ) -> list[str]:
        if max_unpinned < 0:
            raise ValidationError("max_unpinned must be non-negative", field="max_unpinned")
        segment = validate_server_segment(server_id)
        root = vault_root or self._layout.class_c_vault_dir(segment)
        unpinned = [row for row in self.list_active(segment) if not row.pinned]
        victims = unpinned[max_unpinned:]
        removed: list[str] = []
        for row in victims:
            snapshot_dir = root / row.snapshot_id
            if snapshot_dir.is_symlink():
                raise ValidationError(
                    "Snapshot directory must not be a symlink", field="path"
                )
            shutil.rmtree(snapshot_dir, ignore_errors=True)
            self.delete_snapshot(segment, row.snapshot_id)
            removed.append(row.snapshot_id)
        return removed


class ClassCSnapshotService:
    """Create, restore, unpin, prune, and reconcile encrypted Class-C snapshots."""

    def __init__(
        self,
        layout: HostStateLayout,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        sync_session_factory: sessionmaker[Session] | None = None,
        repository: ClassCSnapshotRepository | None = None,
    ) -> None:
        self._layout = layout
        self._repository = repository or ClassCSnapshotRepository(
            layout,
            session_factory=session_factory,
            sync_session_factory=sync_session_factory,
        )

    @property
    def repository(self) -> ClassCSnapshotRepository:
        return self._repository

    def close(self) -> None:
        self._repository.close()

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

        kek = load_master_kek()
        vault = self._layout.class_c_vault_dir(segment)
        _mkdir_private(vault)
        target = vault / snapshot
        if os.path.lexists(target):
            raise ConflictError(f"Snapshot '{snapshot}' already exists")

        staging = vault / f"{_STAGING_PREFIX}{snapshot}-{uuid.uuid4().hex}"
        staging.mkdir(mode=0o700)
        if os.name == "posix":
            os.chmod(staging, 0o700)

        dynamic = frozenset(str(item) for item in dynamic_class_c)
        dek = os.urandom(32)
        dek_wrap_nonce = os.urandom(12)
        wrapped_dek = AESGCM(kek.key_bytes).encrypt(
            dek_wrap_nonce,
            dek,
            dek_wrap_aad(segment, snapshot, kek.kek_version),
        )
        seen_nonces: set[bytes] = set()
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
                    mode = stat.S_IMODE(source_stat.st_mode) & 0o777
                    blob_relpath = f"{BLOBS_DIRNAME}/{relpath}.enc"
                    dest = staging / blob_relpath
                    _mkdir_private(dest.parent)
                    dest_fd = os.open(
                        dest,
                        os.O_WRONLY
                        | os.O_CREAT
                        | os.O_EXCL
                        | getattr(os, "O_NOFOLLOW", 0),
                        0o600,
                    )
                    base_nonce = os.urandom(12)
                    if base_nonce in seen_nonces:
                        raise ValidationError(
                            "Duplicate snapshot nonce detected", field="nonce"
                        )
                    seen_nonces.add(base_nonce)
                    plain_digest = hashlib.sha256()
                    cipher_digest = hashlib.sha256()
                    size = 0
                    ciphertext_size = 0
                    chunk_count = 0
                    try:
                        current = os.read(src_fd, CHUNK_SIZE)
                        while True:
                            following = os.read(src_fd, CHUNK_SIZE) if current else b""
                            is_final = not following
                            nonce = derive_chunk_nonce(base_nonce, chunk_count)
                            aad = chunk_aad(
                                segment,
                                snapshot,
                                relpath,
                                chunk_count,
                                is_final=is_final,
                            )
                            ciphertext = AESGCM(dek).encrypt(nonce, current, aad)
                            frame = len(ciphertext).to_bytes(4, "big") + ciphertext
                            _write_fd(dest_fd, frame)
                            plain_digest.update(current)
                            cipher_digest.update(frame)
                            size += len(current)
                            ciphertext_size += len(frame)
                            chunk_count += 1
                            if is_final:
                                break
                            current = following
                        if os.name == "posix":
                            os.fchmod(dest_fd, 0o600)
                        os.fsync(dest_fd)
                    finally:
                        os.close(dest_fd)
                finally:
                    os.close(src_fd)

                files.append(
                    {
                        "base_nonce": base_nonce.hex(),
                        "blob_relpath": blob_relpath,
                        "chunk_count": chunk_count,
                        "ciphertext_sha256": cipher_digest.hexdigest(),
                        "ciphertext_size": ciphertext_size,
                        "mode": mode,
                        "relpath": relpath,
                        "sha256": plain_digest.hexdigest(),
                        "size": size,
                    }
                )
                total_bytes += size

            files.sort(key=lambda item: item["relpath"])
            manifest = {
                "created_at": _utc_now(),
                "dek_wrap_nonce": dek_wrap_nonce.hex(),
                "files": files,
                "format_version": FORMAT_VERSION,
                "kek_version": kek.kek_version,
                "pinned": bool(pinned),
                "server_id": segment,
                "snapshot_id": snapshot,
                "wrapped_dek": wrapped_dek.hex(),
            }
            manifest_bytes = _json_bytes(manifest)
            atomic_write_private(
                staging / MANIFEST_FILENAME, manifest_bytes, mode=0o600
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

        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        try:
            self._repository.create_snapshot(
                server_id=segment,
                snapshot_id=snapshot,
                manifest_sha256=manifest_sha256,
                kek_version=kek.kek_version,
                file_count=len(files),
                total_bytes=total_bytes,
                pinned=bool(pinned),
            )
        except BaseException:
            shutil.rmtree(target, ignore_errors=True)
            raise

        if not pinned:
            self.prune_unpinned_snapshots(
                segment,
                max_unpinned=MAX_UNPINNED_SNAPSHOTS,
                vault_root=vault,
            )

        return ClassCSnapshotResult(
            snapshot_id=snapshot,
            root=target,
            manifest_path=target / MANIFEST_FILENAME,
            file_count=len(files),
            total_bytes=total_bytes,
            pinned=bool(pinned),
            manifest_sha256=manifest_sha256,
            kek_version=kek.kek_version,
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
    ) -> tuple[str, str, Path, dict[str, Any], bytes]:
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

        raw_manifest = _read_raw(root, MANIFEST_FILENAME)
        try:
            manifest = json.loads(raw_manifest.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError(
                "Snapshot file 'manifest.json' is not valid JSON", field="snapshot"
            ) from exc
        if not isinstance(manifest, dict):
            raise ValidationError(
                "Snapshot file 'manifest.json' must be a JSON object", field="snapshot"
            )
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
        return segment, snapshot, root, manifest, raw_manifest

    def _load_active_row(
        self, segment: str, snapshot: str
    ) -> ClassCSnapshotRow:
        row = self._repository.get_snapshot(segment, snapshot)
        if row is None:
            raise ValidationError(
                "Snapshot has no active database ledger row", field="snapshot"
            )
        if row.status != "active":
            raise ValidationError(
                "Snapshot is not active in the database ledger",
                field="snapshot",
                details={"status": row.status},
            )
        return row

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
        segment, snapshot, root, manifest, raw_manifest = self._load_snapshot(
            server_id, snapshot_id, require_marker=True
        )
        target = Path(target_dir)
        if target.is_symlink() or not target.is_dir():
            raise ValidationError(
                "target_dir must be an existing plain directory", field="target_dir"
            )

        disk_manifest_sha256 = hashlib.sha256(raw_manifest).hexdigest()
        row = self._load_active_row(segment, snapshot)
        if row.manifest_sha256 != disk_manifest_sha256:
            raise ValidationError(
                "Snapshot manifest digest does not match the database ledger",
                field="manifest_sha256",
                details={"snapshot_id": snapshot},
            )

        kek = load_master_kek()
        stored_manifest_version = manifest.get("kek_version")
        if stored_manifest_version != kek.kek_version:
            raise MasterKekVersionMismatchError(
                stored_kek_version=int(stored_manifest_version or 0),
                active_kek_version=kek.kek_version,
            )
        if row.kek_version != kek.kek_version:
            raise MasterKekVersionMismatchError(
                stored_kek_version=row.kek_version,
                active_kek_version=kek.kek_version,
            )

        wrap_nonce_hex = manifest.get("dek_wrap_nonce")
        wrapped_dek_hex = manifest.get("wrapped_dek")
        if (
            not isinstance(wrap_nonce_hex, str)
            or not _HEX24_RE.match(wrap_nonce_hex)
            or not isinstance(wrapped_dek_hex, str)
            or not _HEX96_RE.match(wrapped_dek_hex)
        ):
            raise ValidationError("Snapshot DEK envelope is invalid", field="kek")
        try:
            dek = AESGCM(kek.key_bytes).decrypt(
                bytes.fromhex(wrap_nonce_hex),
                bytes.fromhex(wrapped_dek_hex),
                dek_wrap_aad(segment, snapshot, kek.kek_version),
            )
        except (InvalidTag, ValueError) as exc:
            raise ValidationError(
                "Snapshot DEK authentication failed", field="kek"
            ) from exc

        entries = _manifest_entries(manifest)
        panic = ValidationError(
            "Snapshot file digest mismatch", field="sha256"
        )
        verified: list[tuple[dict[str, Any], bytes]] = []
        for entry in entries:
            relpath = entry["relpath"]
            try:
                fd = open_safe_path_fd(str(root), entry["blob_relpath"])
            except FileNotFoundError as exc:
                raise ValidationError(
                    "Snapshot blob is missing",
                    field="snapshot",
                    details={"relpath": relpath},
                ) from exc
            except (OSError, ValueError) as exc:
                raise ValidationError(
                    "Snapshot blob is unsafe",
                    field="snapshot",
                    details={"relpath": relpath},
                ) from exc
            try:
                ciphertext = _read_fd(fd)
            finally:
                os.close(fd)
            if (
                len(ciphertext) != entry["ciphertext_size"]
                or hashlib.sha256(ciphertext).hexdigest()
                != entry["ciphertext_sha256"]
            ):
                raise panic

            offset = 0
            plaintext_chunks: list[bytes] = []
            chunk_index = 0
            while chunk_index < entry["chunk_count"]:
                if offset + 4 > len(ciphertext):
                    raise ValidationError(
                        "Snapshot blob is truncated",
                        field="snapshot",
                        details={"relpath": relpath, "chunk_index": chunk_index},
                    )
                length = int.from_bytes(ciphertext[offset : offset + 4], "big")
                offset += 4
                if (
                    length < MIN_CHUNK_CIPHERTEXT
                    or length > MAX_CHUNK_CIPHERTEXT
                    or offset + length > len(ciphertext)
                ):
                    raise ValidationError(
                        "Snapshot chunk framing is invalid",
                        field="snapshot",
                        details={"relpath": relpath, "chunk_index": chunk_index},
                    )
                frame = ciphertext[offset : offset + length]
                offset += length
                is_final = chunk_index == entry["chunk_count"] - 1
                try:
                    plaintext_chunks.append(
                        AESGCM(dek).decrypt(
                            derive_chunk_nonce(entry["base_nonce"], chunk_index),
                            frame,
                            chunk_aad(
                                segment,
                                snapshot,
                                relpath,
                                chunk_index,
                                is_final=is_final,
                            ),
                        )
                    )
                except InvalidTag as exc:
                    raise ValidationError(
                        "Snapshot chunk authentication failed",
                        field="ciphertext",
                        details={"relpath": relpath, "chunk_index": chunk_index},
                    ) from exc
                chunk_index += 1
            if offset != len(ciphertext):
                raise ValidationError(
                    "Snapshot blob has trailing bytes",
                    field="snapshot",
                    details={"relpath": relpath},
                )

            plaintext = b"".join(plaintext_chunks)
            if (
                len(plaintext) != entry["size"]
                or hashlib.sha256(plaintext).hexdigest() != entry["sha256"]
            ):
                raise ValidationError(
                    "Snapshot file digest mismatch",
                    field="sha256",
                    details={"relpath": relpath},
                )
            verified.append((entry, plaintext))

        restored = 0
        for entry, plaintext in verified:
            relpath = entry["relpath"]
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
                _write_fd(tmp_fd, plaintext)
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
        segment, snapshot, root, manifest, raw_manifest = self._load_snapshot(
            server_id, snapshot_id, require_marker=True
        )
        row = self._load_active_row(segment, snapshot)
        current_sha256 = hashlib.sha256(raw_manifest).hexdigest()
        if row.manifest_sha256 != current_sha256:
            raise ValidationError(
                "Snapshot manifest digest does not match the database ledger",
                field="manifest_sha256",
                details={"snapshot_id": snapshot},
            )
        manifest["pinned"] = False
        new_bytes = _json_bytes(manifest)
        atomic_write_private(root / MANIFEST_FILENAME, new_bytes, mode=0o600)
        self._repository.update_snapshot(
            segment,
            snapshot,
            pinned=False,
            manifest_sha256=hashlib.sha256(new_bytes).hexdigest(),
        )
        self.prune_unpinned_snapshots(segment, vault_root=root.parent)

    def delete_snapshot(self, server_id: str, snapshot_id: str) -> None:
        _require_posix_host()
        segment, snapshot, root, manifest, _raw = self._load_snapshot(
            server_id, snapshot_id, require_marker=False
        )
        row = self._repository.get_snapshot(segment, snapshot)
        if bool(manifest.get("pinned")) or (row is not None and row.pinned):
            raise BackupPinnedError(
                snapshot,
                message=f"Snapshot '{snapshot}' is pinned and cannot be deleted",
            )
        shutil.rmtree(root)
        _fsync_dir(root.parent)
        self._repository.delete_snapshot(segment, snapshot)

    def prune_unpinned_snapshots(
        self,
        server_id: str,
        *,
        max_unpinned: int = MAX_UNPINNED_SNAPSHOTS,
        vault_root: Path | None = None,
    ) -> list[str]:
        segment = validate_server_segment(server_id)
        root = vault_root or self._layout.class_c_vault_dir(segment)
        return self._repository.prune_unpinned_snapshots(
            segment, max_unpinned=max_unpinned, vault_root=root
        )

    # ------------------------------------------------------------------
    # Reconciliation and GC roots
    # ------------------------------------------------------------------

    def reconcile_snapshots(
        self, server_id: str | None = None
    ) -> ClassCReconcileSummary:
        if os.name != "posix":
            return ClassCReconcileSummary()

        vault = self._layout.class_c_vault
        if vault.is_symlink():
            raise ValidationError(
                "Class-C vault root must not be a symlink", field="path"
            )

        rows = self._repository.list_active(server_id)
        known = {(row.server_id, row.snapshot_id) for row in rows}
        removed: list[str] = []
        marked: list[str] = []

        server_dirs: list[Path]
        if not vault.is_dir():
            # A deleted vault root must still orphan the DB ledger rows below.
            server_dirs = []
        elif server_id is not None:
            segment = validate_server_segment(server_id)
            candidate = vault / segment
            server_dirs = [candidate] if candidate.is_dir() else []
        else:
            server_dirs = sorted(
                entry for entry in vault.iterdir() if entry.is_dir() and not entry.is_symlink()
            )

        for server_dir in server_dirs:
            try:
                segment = validate_server_segment(server_dir.name)
            except Exception:
                continue
            for entry in sorted(server_dir.iterdir()):
                if entry.is_symlink() or not entry.is_dir():
                    continue
                if entry.name.startswith(_STAGING_PREFIX):
                    shutil.rmtree(entry, ignore_errors=True)
                    removed.append(f"{segment}/{entry.name}")
                    continue
                try:
                    snapshot = validate_server_segment(entry.name)
                except Exception:
                    continue
                incomplete = True
                try:
                    marker = _read_json(entry, COMPLETE_MARKER_NAME)
                    manifest = _read_json(entry, MANIFEST_FILENAME)
                    incomplete = (
                        marker.get("format_version") != FORMAT_VERSION
                        or manifest.get("format_version") != FORMAT_VERSION
                    )
                except ValidationError:
                    incomplete = True
                if incomplete or (segment, snapshot) not in known:
                    shutil.rmtree(entry, ignore_errors=True)
                    removed.append(f"{segment}/{snapshot}")

        for row in rows:
            root = self._layout.class_c_vault_dir(row.server_id) / row.snapshot_id
            if root.is_symlink() or not root.is_dir():
                missing = True
            else:
                missing = not (
                    os.path.lexists(root / COMPLETE_MARKER_NAME)
                    and os.path.lexists(root / MANIFEST_FILENAME)
                )
            if missing:
                self._repository.update_snapshot(
                    row.server_id, row.snapshot_id, status="missing"
                )
                marked.append(f"{row.server_id}/{row.snapshot_id}")

        return ClassCReconcileSummary(
            removed_directories=tuple(sorted(removed)),
            marked_missing=tuple(sorted(marked)),
        )

    def collect_gc_roots(self, server_id: str | None = None) -> ClassCGcRoots:
        rows = self._repository.list_active(server_id)
        snapshot_ids: set[str] = set()
        snapshot_dirs: set[Path] = set()
        manifest_sha256s: set[str] = set()
        blob_paths: set[Path] = set()
        for row in rows:
            root = self._layout.class_c_vault_dir(row.server_id) / row.snapshot_id
            snapshot_ids.add(row.snapshot_id)
            snapshot_dirs.add(root)
            manifest_sha256s.add(row.manifest_sha256)
            blobs = root / BLOBS_DIRNAME
            if blobs.is_dir() and not blobs.is_symlink():
                for dirpath, _dirnames, filenames in os.walk(blobs, followlinks=False):
                    for name in filenames:
                        candidate = Path(dirpath) / name
                        if candidate.is_file() and not candidate.is_symlink():
                            blob_paths.add(candidate)
        return ClassCGcRoots(
            snapshot_ids=frozenset(snapshot_ids),
            snapshot_dirs=frozenset(snapshot_dirs),
            manifest_sha256s=frozenset(manifest_sha256s),
            blob_paths=frozenset(blob_paths),
        )


__all__ = [
    "BLOBS_DIRNAME",
    "CHUNK_SIZE",
    "COMPLETE_MARKER_NAME",
    "FORMAT_VERSION",
    "MANIFEST_FILENAME",
    "MAX_UNPINNED_SNAPSHOTS",
    "ClassCGcRoots",
    "ClassCReconcileSummary",
    "ClassCSnapshotRepository",
    "ClassCSnapshotResult",
    "ClassCSnapshotRow",
    "ClassCSnapshotService",
    "chunk_aad",
    "dek_wrap_aad",
    "derive_chunk_nonce",
]
