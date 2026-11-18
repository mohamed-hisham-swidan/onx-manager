"""Quiescent data template storage and cloning for P4."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.core.allowlist import SymlinkEscapeError, classify, open_safe_path_fd
from app.core.exceptions import (
    HotCloneRefusedError,
    InsufficientStorageError,
    ServerModeVersioningDisabledError,
    ValidationError,
)
from app.core.host_state import HostStateLayout, validate_server_segment

_FICLONE = 0x40049409
_SKIP_NAMES = {".git", ".onx", ".onx-manager", ".onx-complete.json", "session.lock"}
_MARKER_NAME = ".onx-complete.json"


class RconQuiescePort(Protocol):
    async def save_off(self) -> Any: ...

    async def save_all_flush(self, timeout: float = 30.0) -> str: ...

    async def save_on(self) -> Any: ...


class ContainerStatePort(Protocol):
    def is_running(self) -> bool: ...


class SaveOffStateStore(Protocol):
    async def set_save_off_active(self, server_id: str, active: bool) -> Any: ...


def _is_async_callable(obj: Any) -> bool:
    return asyncio.iscoroutinefunction(obj)


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value) or asyncio.isfuture(value):
        return await value
    return value


async def _call_method(target: Any, names: tuple[str, ...], *args: Any, **kwargs: Any) -> Any:
    for name in names:
        method = getattr(target, name, None)
        if method is None:
            continue
        result = method(*args, **kwargs)
        return await _maybe_await(result)
    raise AttributeError(f"None of {names} found on {target!r}")


async def _is_running(container_state: Any) -> bool:
    result = container_state.is_running()
    value = await _maybe_await(result)
    return bool(value)


def _probe_reflink_support(source_root: Path, staging_dir: Path) -> bool:  # noqa: ARG001
    """Probe whether FICLONE works on the target st_dev."""
    import fcntl

    src = None
    dst = None
    try:
        staging_dir.mkdir(parents=True, exist_ok=True)
        src = staging_dir / f".probe-src-{uuid.uuid4().hex[:8]}"
        dst = staging_dir / f".probe-dst-{uuid.uuid4().hex[:8]}"
        src.write_bytes(b"probe")
        src_fd = os.open(src, os.O_RDONLY)
        try:
            dst_fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
            try:
                fcntl.ioctl(dst_fd, _FICLONE, src_fd)
                return os.fstat(dst_fd).st_size == os.fstat(src_fd).st_size
            except OSError:
                return False
            finally:
                os.close(dst_fd)
        finally:
            os.close(src_fd)
    except Exception:
        return False
    finally:
        for p in (src, dst):
            if p is not None:
                with contextlib.suppress(OSError):
                    p.unlink(missing_ok=True)


def _iter_class_e_files(source_root: Path) -> list[str]:
    result: list[str] = []
    if not source_root.exists():
        return result
    for dirpath, dirnames, filenames in os.walk(source_root, followlinks=False):
        # Prune forbidden dirs.
        dirnames[:] = [d for d in dirnames if d not in _SKIP_NAMES]
        for filename in filenames:
            if filename in _SKIP_NAMES:
                continue
            full = Path(dirpath) / filename
            relpath = full.relative_to(source_root).as_posix()
            if classify(relpath) != "E":
                continue
            if full.is_symlink():
                raise SymlinkEscapeError(
                    f"Symlink inside Class-E data template source: {full}"
                )
            if not full.is_file(follow_symlinks=False):
                continue
            result.append(relpath)
        for dname in list(dirnames):
            dir_rel = (Path(dirpath) / dname).relative_to(source_root).as_posix()
            candidate = Path(dirpath) / dname
            if candidate.is_symlink() and classify(dir_rel + "/x") == "E":
                raise SymlinkEscapeError(
                    f"Symlink inside Class-E data template source: {candidate}"
                )
    return result


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _write_marker(
    template_root: Path,
    file_count: int,
    total_bytes: int,
    source_commit_sha: str | None,
    template_id: str,
) -> None:
    completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    marker = {
        "completed_at": completed_at,
        "file_count": file_count,
        "source_commit_sha": source_commit_sha,
        "template_id": template_id,
        "total_bytes": total_bytes,
    }
    canonical = json.dumps(marker, sort_keys=True, separators=(",", ":"))
    marker_path = template_root / _MARKER_NAME
    fd = os.open(marker_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, canonical.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_dir(template_root)


def _verify_nlink(template_root: Path) -> None:
    for dirpath, _dirnames, filenames in os.walk(template_root, followlinks=False):
        for filename in filenames:
            full = Path(dirpath) / filename
            if full.is_symlink():
                raise ValidationError("Symlink in template", field="path")
            st = full.stat()
            if getattr(st, "st_nlink", 1) != 1:
                raise ValidationError("Hardlink detected in template", field="path")


def _copy_file_reflink(source_root: Path, staging_root: Path, relpath: str) -> int:
    source_fd = open_safe_path_fd(str(source_root), relpath, flags=os.O_RDONLY)
    try:
        st = os.fstat(source_fd)
        size = st.st_size
        dest_fd = open_safe_path_fd(
            str(staging_root),
            relpath,
            flags=os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            mode=0o644,
            allow_create_parents=True,
        )
        try:
            os.ftruncate(dest_fd, 0)
            if not _try_reflink_fd(source_fd, dest_fd, size):
                raise HotCloneRefusedError("Reflink failed during hot clone")
            return size
        finally:
            os.close(dest_fd)
    finally:
        os.close(source_fd)


def _try_reflink_fd(source_fd: int, dest_fd: int, size: int) -> bool:
    import fcntl

    try:
        fcntl.ioctl(dest_fd, _FICLONE, source_fd)
    except OSError:
        return False
    if os.fstat(dest_fd).st_size != size:
        with __import__("contextlib").suppress(OSError):
            os.ftruncate(dest_fd, 0)
        return False
    return True


def _copy_file_plain(source_root: Path, staging_root: Path, relpath: str, lock_path: Path) -> int:
    import fcntl

    source_fd = open_safe_path_fd(str(source_root), relpath, flags=os.O_RDONLY)
    try:
        st = os.fstat(source_fd)
        size = st.st_size
        # free space check
        dest_parent = staging_root / Path(relpath).parent
        dest_parent.mkdir(parents=True, exist_ok=True)
        probe_fd = os.open(dest_parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            vfs = os.fstatvfs(probe_fd)
            free = vfs.f_bavail * vfs.f_frsize
            if free < size * 1.10:
                raise InsufficientStorageError(details={"required": size * 1.10, "free": free})
        finally:
            os.close(probe_fd)

        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            dest_fd = open_safe_path_fd(
                str(staging_root),
                relpath,
                flags=os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                mode=0o644,
                allow_create_parents=True,
            )
            try:
                os.ftruncate(dest_fd, 0)
                os.lseek(source_fd, 0, os.SEEK_SET)
                os.lseek(dest_fd, 0, os.SEEK_SET)
                remaining = size
                while remaining > 0:
                    chunk = os.read(source_fd, min(1024 * 1024, remaining))
                    if not chunk:
                        raise OSError("unexpected EOF")
                    os.write(dest_fd, chunk)
                    remaining -= len(chunk)
            finally:
                os.close(dest_fd)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        return size
    finally:
        os.close(source_fd)


@dataclass
class DataTemplateService:
    layout: HostStateLayout
    rcon: Any = None
    container_state: Any = None
    save_off_store: Any = None
    clock: Callable[[], float] = time.monotonic
    db_session: Any = None
    # aliases
    rcon_quiesce: Any = None
    container_state_port: Any = None
    save_off_state_store: Any = None
    host_state_dir: Any = None

    def __post_init__(self) -> None:
        if self.rcon is None and self.rcon_quiesce is not None:
            self.rcon = self.rcon_quiesce
        if self.container_state is None and self.container_state_port is not None:
            self.container_state = self.container_state_port
        if self.save_off_store is None and self.save_off_state_store is not None:
            self.save_off_store = self.save_off_state_store

    def _template_root(self, server_id: str, template_id: str) -> Path:
        seg = validate_server_segment(server_id)
        return self.layout.data_templates / seg / template_id

    def _staging_root(self, server_id: str, template_id: str) -> Path:
        seg = validate_server_segment(server_id)
        return (
            self.layout.data_templates
            / seg
            / f".onx-template-{template_id}-{uuid.uuid4().hex[:8]}"
        )

    def _lock_path(self, st_dev: int) -> Path:
        return self.layout.locks / f"copy-{st_dev}.lock"

    async def clone(
        self,
        server_id: str,
        source_root: str | Path,
        template_id: str,
        *,
        source_commit_sha: str | None = None,
        source_branch_name: str | None = None,  # noqa: ARG002
        rcon: Any = None,
        container_state: Any = None,
        save_off_store: Any = None,
        clock: Callable[[], float] | None = None,
        db_session: Any = None,
        session: Any = None,
        **kwargs: Any,  # noqa: ARG002
    ) -> Path:
        if os.name != "posix":
            raise ServerModeVersioningDisabledError()
        source_root = Path(source_root)
        if rcon is not None:
            self.rcon = rcon
        if container_state is not None:
            self.container_state = container_state
        if save_off_store is not None:
            self.save_off_store = save_off_store
        if clock is not None:
            self.clock = clock
        if db_session is not None:
            self.db_session = db_session
        if session is not None:
            self.db_session = session

        container_state = self.container_state
        rcon = self.rcon
        save_off_store = self.save_off_store
        clock = self.clock

        running = False
        if container_state is not None:
            running = await _is_running(container_state)

        server_seg = validate_server_segment(server_id)
        final_root = self.layout.data_templates / server_seg / template_id
        staging = self._staging_root(server_id, template_id)

        if running:
            probe = _probe_reflink_support(source_root, self.layout.data_templates / server_seg)
            if probe:
                await self._clone_running_reflink(
                    server_id, source_root, template_id, staging, final_root,
                    rcon, save_off_store, clock, source_commit_sha,
                )
            else:
                await self._clone_running_two_pass(
                    server_id, source_root, template_id, staging, final_root,
                    rcon, save_off_store, clock, source_commit_sha,
                )
        else:
            # stopped container path
            # verify session.lock absent or not locked
            session_lock = source_root / "world" / "session.lock"
            if session_lock.exists():
                # attempt flock check
                import fcntl

                try:
                    fd = os.open(session_lock, os.O_RDONLY)
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        fcntl.flock(fd, fcntl.LOCK_UN)
                    except (BlockingIOError, OSError):
                        raise HotCloneRefusedError("Container session.lock is held") from None
                    finally:
                        os.close(fd)
                except OSError:
                    pass
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True, exist_ok=True)
            files = _iter_class_e_files(source_root)
            total_bytes = 0
            for relpath in files:
                size = _copy_file_plain(
                    source_root,
                    staging,
                    relpath,
                    self._lock_path(os.stat(staging).st_dev),
                )
                total_bytes += size
            _verify_nlink(staging)
            _write_marker(staging, len(files), total_bytes, source_commit_sha, template_id)
            final_root.parent.mkdir(parents=True, exist_ok=True)
            if final_root.exists():
                shutil.rmtree(final_root, ignore_errors=True)
            os.replace(staging, final_root)
            _fsync_dir(final_root.parent)
            await _persist_template_async(
                self.db_session,
                server_id,
                template_id,
                final_root,
                len(files),
                total_bytes,
                source_commit_sha,
                source_branch_name,
                "ready",
            )
        return final_root

    async def _clone_running_reflink(
        self,
        server_id: str,
        source_root: Path,
        template_id: str,
        staging: Path,
        final_root: Path,
        rcon: Any,
        save_off_store: Any,
        clock: Callable[[], float],  # noqa: ARG002
        source_commit_sha: str | None,
    ) -> None:
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=True)
        save_off_attempted = False
        try:
            if save_off_store is not None:
                await _maybe_await(save_off_store.set_save_off_active(server_id, True))
            save_off_attempted = True
            if rcon is not None:
                try:
                    await _call_method(rcon, ("save_off",))
                except Exception as exc:
                    raise HotCloneRefusedError(
                        "RCON unavailable for hot clone; stop the container first"
                    ) from exc
                confirm = await _call_method(rcon, ("save_all_flush", "save_all"), 30.0)
                if not confirm:
                    raise HotCloneRefusedError("save-all flush unconfirmed")
                text = str(confirm)
                has_saved = any(
                    tok in text for tok in ("Saved the game", "Saved the world")
                )
                pred = getattr(rcon, "confirm_predicate", None)
                if pred is not None:
                    if not pred(text):
                        raise HotCloneRefusedError("save-all flush unconfirmed")
                elif not has_saved:
                    raise HotCloneRefusedError("save-all flush unconfirmed")
            # reflink files
            files = _iter_class_e_files(source_root)
            snapshot_before = {}
            for relpath in files:
                st = (source_root / relpath).stat()
                snapshot_before[relpath] = (st.st_mtime_ns, st.st_size)
            total_bytes = 0
            for relpath in files:
                size = _copy_file_reflink(source_root, staging, relpath)
                total_bytes += size
                st = (source_root / relpath).stat()
                if snapshot_before.get(relpath) != (st.st_mtime_ns, st.st_size):
                    raise HotCloneRefusedError("File modified during reflink")
            _verify_nlink(staging)
            _write_marker(staging, len(files), total_bytes, source_commit_sha, template_id)
            final_root.parent.mkdir(parents=True, exist_ok=True)
            if final_root.exists():
                shutil.rmtree(final_root, ignore_errors=True)
            os.replace(staging, final_root)
            _fsync_dir(final_root.parent)
            await _persist_template_async(
                self.db_session,
                server_id,
                template_id,
                final_root,
                len(files),
                total_bytes,
                source_commit_sha,
                None,
                "ready",
            )
        finally:
            if rcon is not None and save_off_attempted:
                with __import__("contextlib").suppress(Exception):
                    await _call_method(rcon, ("save_on",))
            if save_off_store is not None:
                with __import__("contextlib").suppress(Exception):
                    await _maybe_await(save_off_store.set_save_off_active(server_id, False))

    async def _clone_running_two_pass(
        self,
        server_id: str,
        source_root: Path,
        template_id: str,
        staging: Path,
        final_root: Path,
        rcon: Any,
        save_off_store: Any,
        clock: Callable[[], float],
        source_commit_sha: str | None,
    ) -> None:
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=True)
        # Pass 1 online copy with save-on active
        files = _iter_class_e_files(source_root)
        pass1_manifest: dict[str, tuple[int, int]] = {}
        for relpath in files:
            full = source_root / relpath
            st = full.stat()
            _copy_file_plain(
                source_root,
                staging,
                relpath,
                self._lock_path(os.stat(staging).st_dev),
            )
            pass1_manifest[relpath] = (st.st_mtime_ns, st.st_size)
        # Pass 2
        save_off_started = None
        save_off_attempted = False
        try:
            if save_off_store is not None:
                await _maybe_await(save_off_store.set_save_off_active(server_id, True))
            save_off_attempted = True
            save_off_started = clock()
            if rcon is not None:
                try:
                    await _call_method(rcon, ("save_off",))
                except Exception as exc:
                    raise HotCloneRefusedError(
                        "RCON unavailable for hot clone; stop the container first"
                    ) from exc
                confirm = await _call_method(rcon, ("save_all_flush", "save_all"), 30.0)
                text = str(confirm) if confirm is not None else ""
                if not confirm:
                    shutil.rmtree(staging, ignore_errors=True)
                    raise HotCloneRefusedError("save-all flush failed")
                if not any(tok in text for tok in ("Saved the game", "Saved the world")):
                    pred = getattr(rcon, "confirm_predicate", None)
                    if pred is None or not pred(text):
                        shutil.rmtree(staging, ignore_errors=True)
                        raise HotCloneRefusedError("save-all flush unconfirmed")
                if clock() - save_off_started > 30.0:
                    shutil.rmtree(staging, ignore_errors=True)
                    raise HotCloneRefusedError("save-all flush exceeded 30s")
            if save_off_started is None:
                save_off_started = clock()

            # check total save-off cap 30s for flush? flush timeout handled by rcon fake
            # delta sync
            current_files = set(_iter_class_e_files(source_root))
            # delete removed
            for relpath in list(pass1_manifest.keys()):
                if relpath not in current_files:
                    target = staging / relpath
                    with contextlib.suppress(OSError):
                        target.unlink(missing_ok=True)
                    del pass1_manifest[relpath]
            for relpath in current_files:
                full = source_root / relpath
                st = full.stat()
                old = pass1_manifest.get(relpath)
                if old is None or old != (st.st_mtime_ns, st.st_size):
                    # check cap before
                    if clock() - save_off_started > 60.0:
                        shutil.rmtree(staging, ignore_errors=True)
                        raise HotCloneRefusedError(
                            "Two-pass hot clone exceeded the 60s save-off cap; "
                            "stop the container to clone"
                        )
                    _copy_file_plain(
                source_root,
                staging,
                relpath,
                self._lock_path(os.stat(staging).st_dev),
            )
                    pass1_manifest[relpath] = (st.st_mtime_ns, st.st_size)
                    if clock() - save_off_started > 60.0:
                        shutil.rmtree(staging, ignore_errors=True)
                        raise HotCloneRefusedError(
                            "Two-pass hot clone exceeded the 60s save-off cap; "
                            "stop the container to clone"
                        )
        finally:
            if rcon is not None and save_off_attempted:
                with __import__("contextlib").suppress(Exception):
                    await _call_method(rcon, ("save_on",))
            if save_off_store is not None:
                with __import__("contextlib").suppress(Exception):
                    await _maybe_await(save_off_store.set_save_off_active(server_id, False))

        # finalize
        _verify_nlink(staging)
        files = _iter_class_e_files(source_root)
        total_bytes = sum((source_root / r).stat().st_size for r in files)
        _write_marker(staging, len(files), total_bytes, source_commit_sha, template_id)
        final_root.parent.mkdir(parents=True, exist_ok=True)
        if final_root.exists():
            shutil.rmtree(final_root, ignore_errors=True)
        os.replace(staging, final_root)
        _fsync_dir(final_root.parent)
        await _persist_template_async(
            self.db_session,
            server_id,
            template_id,
            final_root,
            len(files),
            total_bytes,
            source_commit_sha,
            None,
            "ready",
        )

def _persist_template_sync(
    session: Any,
    server_id: str,
    template_id: str,
    storage_path: Path,
    file_count: int,
    total_bytes: int,
    source_commit_sha: str | None,
    source_branch_name: str | None,
    status: str,
) -> None:
    if session is None:
        return
    try:
        from app.modules.versioning.infrastructure.models import ServerDataTemplateModel

        row = None
        try:
            getter = getattr(session, "get", None)
            if asyncio.iscoroutinefunction(getter):
                # AsyncSession must use _persist_template_async
                return
            row = session.get(ServerDataTemplateModel, template_id)
        except Exception:
            row = None
        if row is None:
            row = ServerDataTemplateModel(
                id=template_id,
                server_id=server_id,
                name=template_id,
                storage_path=str(storage_path),
                file_count=file_count,
                total_bytes=total_bytes,
                status=status,
                source_commit_sha=source_commit_sha,
                source_branch_name=source_branch_name,
            )
            session.add(row)
        else:
            row.server_id = server_id
            row.storage_path = str(storage_path)
            row.file_count = file_count
            row.total_bytes = total_bytes
            row.status = status
            row.source_commit_sha = source_commit_sha
            row.source_branch_name = source_branch_name
        if hasattr(session, "flush") and not asyncio.iscoroutinefunction(
            getattr(session, "flush", None)
        ):
            session.flush()
    except Exception:
        pass


async def _persist_template_async(
    session: Any,
    server_id: str,
    template_id: str,
    storage_path: Path,
    file_count: int,
    total_bytes: int,
    source_commit_sha: str | None,
    source_branch_name: str | None,
    status: str,
) -> None:
    if session is None:
        return
    try:
        from app.modules.versioning.infrastructure.models import ServerDataTemplateModel

        row = None
        try:
            getter = getattr(session, "get", None)
            if asyncio.iscoroutinefunction(getter):
                row = await session.get(ServerDataTemplateModel, template_id)
            elif getter is not None:
                row = session.get(ServerDataTemplateModel, template_id)
        except Exception:
            row = None
        if row is None:
            row = ServerDataTemplateModel(
                id=template_id,
                server_id=server_id,
                name=template_id,
                storage_path=str(storage_path),
                file_count=file_count,
                total_bytes=total_bytes,
                status=status,
                source_commit_sha=source_commit_sha,
                source_branch_name=source_branch_name,
            )
            session.add(row)
        else:
            row.server_id = server_id
            row.storage_path = str(storage_path)
            row.file_count = file_count
            row.total_bytes = total_bytes
            row.status = status
            row.source_commit_sha = source_commit_sha
            row.source_branch_name = source_branch_name
        if hasattr(session, "commit"):
            committer = session.commit
            if asyncio.iscoroutinefunction(committer):
                await session.commit()
            else:
                session.commit()
        elif hasattr(session, "flush"):
            flusher = session.flush
            if asyncio.iscoroutinefunction(flusher):
                await session.flush()
            else:
                session.flush()
    except Exception:
        pass


# Back-compat alias: async-capable template persistence
_persist_template = _persist_template_async


# Module-level aliases for constructors
DataTemplateService.clone_async = DataTemplateService.clone
DataTemplateService.__name__ = "DataTemplateService"


def reconcile_data_templates_and_save_off(
    layout: HostStateLayout,
    *,
    rcon_callback: Any = None,
    get_rcon: Any = None,
    db_session: Any = None,
    session: Any = None,
    **kwargs: Any,  # noqa: ARG001
) -> None:
    """Startup reconciliation."""
    if os.name != "posix":
        raise ServerModeVersioningDisabledError()
    # 1. scan data-templates
    base = layout.data_templates
    if base.exists():
        for server_dir in base.iterdir():
            if not server_dir.is_dir():
                continue
            for template_dir in list(server_dir.iterdir()):
                marker = template_dir / _MARKER_NAME
                staging = template_dir.name.startswith(".onx-template-")
                incomplete = False
                if staging:
                    incomplete = True
                else:
                    if not marker.is_file():
                        incomplete = True
                    else:
                        try:
                            data = json.loads(marker.read_text(encoding="utf-8"))
                            if not all(
                                k in data
                                for k in ("completed_at", "total_bytes", "file_count")
                            ):
                                incomplete = True
                        except Exception:
                            incomplete = True
                if incomplete:
                    shutil.rmtree(template_dir, ignore_errors=True)
                    sess = db_session or session
                    if sess is not None:
                        try:
                            from app.modules.versioning.infrastructure.models import (
                                ServerDataTemplateModel,
                            )

                            tid = template_dir.name
                            if tid.startswith(".onx-template-"):
                                tid = tid[len(".onx-template-"):].rsplit("-", 1)[0]
                            row = sess.get(ServerDataTemplateModel, tid)
                            if row is not None:
                                row.status = (
                                    "failed" if row.status == "cloning" else "missing"
                                )
                        except Exception:
                            pass
    # 2. save-off active servers
    sess = db_session or session
    if sess is not None:
        try:
            import sqlalchemy

            from app.modules.server.infrastructure.models import ServerModel

            result = sess.execute(
                sqlalchemy.select(ServerModel).where(
                    ServerModel.rcon_save_off_active == True  # noqa: E712
                )
            )
            servers = result.scalars().all() if hasattr(result, "scalars") else []
        except Exception:
            servers = []
        for srv in servers:
            rcon = None
            if rcon_callback is not None:
                rcon = rcon_callback(srv.id) if callable(rcon_callback) else rcon_callback
            elif get_rcon is not None:
                rcon = get_rcon(srv.id) if callable(get_rcon) else get_rcon
            save_on_ok = False
            if rcon is not None:
                try:
                    if asyncio.iscoroutinefunction(getattr(rcon, "save_on", None)):
                        asyncio.get_event_loop().run_until_complete(rcon.save_on())
                    elif hasattr(rcon, "save_on"):
                        rcon.save_on()
                    save_on_ok = True
                except Exception:
                    save_on_ok = False
            container_confirmed_stopped = False
            if not save_on_ok:
                container_state = None
                for key in (
                    "container_state",
                    "container_state_callback",
                    "get_container_state",
                    "container_state_port",
                    "container",
                ):
                    if key in kwargs:
                        value = kwargs.get(key)
                        if callable(value):
                            try:
                                container_state = value(srv.id)
                            except TypeError:
                                try:
                                    container_state = value()
                                except Exception:
                                    container_state = None
                        else:
                            container_state = value
                        break
                if isinstance(container_state, dict):
                    container_state = container_state.get(
                        srv.id, container_state.get("running")
                    )
                running = None
                if container_state is not None:
                    if hasattr(container_state, "is_running"):
                        try:
                            result = container_state.is_running()
                            if not asyncio.iscoroutine(result):
                                running = bool(result)
                        except Exception:
                            running = None
                    elif isinstance(container_state, bool):
                        running = container_state
                    elif isinstance(container_state, str):
                        running = container_state.lower() in (
                            "running",
                            "true",
                            "1",
                            "up",
                            "started",
                        )
                if running is False:
                    container_confirmed_stopped = True
            if save_on_ok or container_confirmed_stopped:
                with contextlib.suppress(Exception):
                    srv.rcon_save_off_active = False
        with contextlib.suppress(Exception):
            sess.commit()


async def reconcile_data_templates_and_save_off_async(
    layout: HostStateLayout,
    *,
    rcon_callback: Any = None,
    get_rcon: Any = None,
    db_session: Any = None,
    session: Any = None,
    **kwargs: Any,  # noqa: ARG001
) -> None:
    if os.name != "posix":
        raise ServerModeVersioningDisabledError()
    base = layout.data_templates
    if base.exists():
        for server_dir in base.iterdir():
            if not server_dir.is_dir():
                continue
            for template_dir in list(server_dir.iterdir()):
                marker = template_dir / _MARKER_NAME
                staging = template_dir.name.startswith(".onx-template-")
                incomplete = staging
                if not staging:
                    if not marker.is_file():
                        incomplete = True
                    else:
                        try:
                            data = json.loads(marker.read_text(encoding="utf-8"))
                            if not all(
                                k in data
                                for k in ("completed_at", "total_bytes", "file_count")
                            ):
                                incomplete = True
                        except Exception:
                            incomplete = True
                if incomplete:
                    shutil.rmtree(template_dir, ignore_errors=True)
                    sess = db_session or session
                    if sess is not None:
                        try:
                            from app.modules.versioning.infrastructure.models import (
                                ServerDataTemplateModel,
                            )

                            tid = template_dir.name
                            if tid.startswith(".onx-template-"):
                                tid = tid[len(".onx-template-"):].rsplit("-", 1)[0]
                            row = await sess.get(ServerDataTemplateModel, tid)
                            if row is not None:
                                row.status = (
                                    "failed" if row.status == "cloning" else "missing"
                                )
                        except Exception:
                            pass
    sess = db_session or session
    if sess is not None:
        try:
            from sqlalchemy import select

            from app.modules.server.infrastructure.models import ServerModel

            result = await sess.execute(
                select(ServerModel).where(
                    ServerModel.rcon_save_off_active == True  # noqa: E712
                )
            )
            servers = result.scalars().all()
            for srv in servers:
                rcon = None
                if rcon_callback is not None:
                    rcon = (
                        rcon_callback(srv.id)
                        if callable(rcon_callback)
                        else rcon_callback
                    )
                elif get_rcon is not None:
                    rcon = get_rcon(srv.id) if callable(get_rcon) else get_rcon
                save_on_ok = False
                if rcon is not None:
                    try:
                        await _call_method(rcon, ("save_on",))
                        save_on_ok = True
                    except Exception:
                        save_on_ok = False
                container_confirmed_stopped = False
                if not save_on_ok:
                    container_state = None
                    for key in (
                        "container_state",
                        "container_state_callback",
                        "get_container_state",
                        "container_state_port",
                        "container",
                    ):
                        if key in kwargs:
                            value = kwargs.get(key)
                            if callable(value):
                                try:
                                    container_state = value(srv.id)
                                except TypeError:
                                    try:
                                        container_state = value()
                                    except Exception:
                                        container_state = None
                            else:
                                container_state = value
                            break
                    if isinstance(container_state, dict):
                        container_state = container_state.get(
                            srv.id, container_state.get("running")
                        )
                    running = None
                    if container_state is not None:
                        if hasattr(container_state, "is_running"):
                            try:
                                result = container_state.is_running()
                                if asyncio.iscoroutine(result):
                                    result = await result
                                running = bool(result)
                            except Exception:
                                running = None
                        elif isinstance(container_state, bool):
                            running = container_state
                        elif isinstance(container_state, str):
                            running = container_state.lower() in (
                                "running",
                                "true",
                                "1",
                                "up",
                                "started",
                            )
                    if running is False:
                        container_confirmed_stopped = True
                if save_on_ok or container_confirmed_stopped:
                    srv.rcon_save_off_active = False
            await sess.commit()
        except Exception:
            pass


# Alias names
reconcile_data_templates = reconcile_data_templates_and_save_off
reconcile = reconcile_data_templates_and_save_off
reconcile_async = reconcile_data_templates_and_save_off_async
