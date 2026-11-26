import contextlib
import gzip
import os
import stat
import tempfile
import zlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from app.api.deps import get_query_bus, require_server_permission
from app.api.v1.dependencies.server_mode import require_advanced_mode
from app.api.v1.schemas.files import (
    FileContentResponse,
    FileEntryResponse,
    LiveStateFileContentResponse,
    LiveStateFileEntryResponse,
    LiveStateFileListResponse,
    LiveStateWriteRequest,
    LiveStateWriteResponse,
    WriteFileContentRequest,
)
from app.core.allowlist import (
    SymlinkEscapeError,
    classify,
    open_safe_path_fd,
    resolve_safe_disk_path,
    validate_canonical_relpath,
)
from app.core.config import AppSettings
from app.core.exceptions import MCSError
from app.core.query_bus import QueryBus
from app.modules.server.application.queries.get_server import GetServerQuery
from app.modules.server.infrastructure.fs import local_fs
from app.modules.versioning.application import GetBranchFilesRootQuery

router = APIRouter(prefix="/api/v1/servers/{server_id}/files", tags=["files"])

__all__ = ["router"]

MAX_EDITABLE_FILE_BYTES: int = 5 * 1024 * 1024
SENSITIVE_FILENAMES: frozenset[str] = frozenset({".env"})
PROTECTED_DIRNAMES: frozenset[str] = frozenset({".git", ".onx", ".onx-manager", ".mcsmanager"})
RESERVED_ROOT_WRITE_NAMES: frozenset[str] = frozenset({"onx-jars.lock.json", ".gitattributes"})
NON_EDITABLE_FILE_EXTENSIONS: frozenset[str] = frozenset(
    {
        "dat",
        "dat_old",
        "mca",
        "mcr",
        "sqlite",
        "sqlite3",
        "db",
        "nbt",
        "jar",
        "zip",
        "tar",
        "gz",
        "7z",
        "rar",
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp",
        "ico",
        "class",
        "exe",
        "dll",
        "so",
        "dylib",
        "bin",
        "litematic",
        "schem",
        "schematic",
        "ogg",
        "mp3",
        "wav",
        "ttf",
        "otf",
    }
)


def _normalize_name(name: str) -> str:
    """Casefold a path component and strip trailing dots and spaces.

    Windows-style filesystems ignore trailing dots/spaces, so ``.env.`` or
    ``.onx `` would otherwise reach the protected entry.
    """
    return name.rstrip(". ").casefold()


def _is_protected_name(name: str) -> bool:
    return _normalize_name(name) in PROTECTED_DIRNAMES


def _is_sensitive_name(name: str) -> bool:
    norm = _normalize_name(name)
    return norm in {_normalize_name(n) for n in SENSITIVE_FILENAMES} or norm.startswith(".env.")


def _normalize_file_class(raw_class: str) -> str | None:
    if raw_class in {"A-JAR", "A-CAS", "A-LOCKFILE"}:
        return "A"
    if raw_class in {"B", "C", "D", "E"}:
        return raw_class
    return None


def _is_binary_extension(name: str) -> bool:
    if "." not in name:
        return False
    ext = name.rsplit(".", 1)[-1].casefold()
    return ext in NON_EDITABLE_FILE_EXTENSIONS


def _assert_not_sensitive(target_path: Path) -> None:
    """Deny access to files carrying application secrets (e.g. .env, .env.*).

    The comparison is case-insensitive and ignores trailing dots/spaces so the
    guard also holds on case-insensitive filesystems (macOS/Windows) where a
    differently-cased name resolves to the same file. The resolved basename is
    used, so ./.env and any normalized nested/.. form are covered too.
    """
    if _is_sensitive_name(target_path.name):
        raise HTTPException(status_code=403, detail="File access denied for sensitive server file")  # noqa: B904


def _assert_not_protected_path(relative_path: str, target_path: Path, root: Path) -> None:
    """Deny any path having a metadata folder (.onx, .onx-manager, .mcsmanager) as a component."""
    raw_parts = [part for part in relative_path.replace("\\", "/").split("/") if part]
    try:
        resolved_parts = list(target_path.relative_to(root).parts)
    except ValueError:
        resolved_parts = []
    if any(_is_protected_name(part) for part in (*raw_parts, *resolved_parts)):
        raise HTTPException(status_code=403, detail="Access denied to protected server folder")  # noqa: B904


def _assert_file_mutation_allowed(
    relative_path: str,
    read_only: bool,
    *,
    git_scoped: bool,
    is_directory: bool = False,
) -> None:
    """Enforce branch write policy before any Files mutation.

    ``main`` is protected saved state and must be edited through a working
    branch. The authoritative lockfile and the panel-generated attributes file
    are panel-managed even on feature branches. Inside a Git worktree only
    Class-B allow-listed files are editable; Class-A/C/E paths are rejected
    instead of becoming untracked or misclassified content.
    """
    if read_only:
        raise HTTPException(  # noqa: B904
            status_code=403,
            detail="Branch 'main' is read-only; create a working branch to edit files",
        )

    parts = [part for part in relative_path.replace("\\", "/").split("/") if part]
    if len(parts) == 1 and _normalize_name(parts[0]) in RESERVED_ROOT_WRITE_NAMES:
        raise HTTPException(  # noqa: B904
            status_code=403,
            detail="This file is managed by the panel and cannot be modified through Files",
        )

    if git_scoped and is_directory:
        top = _normalize_name(parts[0]) if parts else ""
        if top in {
            "world",
            "world_nether",
            "world_the_end",
            "logs",
            "crash-reports",
            "libraries",
            "versions",
            "bundler",
            "cache",
        } or classify(relative_path) in {"C", "QUARANTINE"}:
            raise HTTPException(  # noqa: B904
                status_code=403,
                detail=(
                    f"Directory '{relative_path}' is not editable on an Advanced Git branch "
                    "(Class A/C or runtime-managed directory)."
                ),
            )

    if git_scoped and not is_directory:
        raw_class = classify(relative_path)
        if raw_class != "B":
            if raw_class == "A-JAR" or relative_path.casefold().endswith(".jar"):
                detail = (
                    "JAR files cannot be uploaded in Files on an Advanced branch (Class A). "
                    "Use the Plugins page to upload and validate .jar plugins."
                )
            elif raw_class == "QUARANTINE":
                detail = f"Blocked executable or hostile file '{relative_path}' in Advanced Mode."
            elif raw_class == "C":
                detail = (
                    f"File '{relative_path}' is a Live State (Class C) file and cannot be edited "
                    "on a Git branch; use the Live State view on 'main'."
                )
            else:
                detail = (
                    f"File '{relative_path}' is blocked by Allow-list v2.3 (Class {raw_class}) "
                    "on an Advanced branch. Only Class-B configuration files and "
                    "server-icon.png are allowed here."
                )
            raise HTTPException(status_code=403, detail=detail)  # noqa: B904


MAX_COMPRESSED_LOG_INPUT_BYTES: int = 50 * 1024 * 1024
_DIR_OPEN_FLAGS: int = (
    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
)


def _normalize_scope(scope: str | None) -> str | None:
    if not isinstance(scope, str) or not scope.strip():
        return None
    normalized = scope.strip().lower()
    if normalized == "logs":
        return "logs"
    raise HTTPException(status_code=422, detail=f"Unsupported files scope: {scope!r}")


def _assert_not_logs_write(scope: str | None) -> None:
    if _normalize_scope(scope) == "logs":
        raise MCSError(
            message=(
                "Logs scope is strictly read-only; runtime logs cannot be modified "
                "or committed to Git."
            ),
            code="LOGS_READ_ONLY",
            http_status=403,
        )


def _open_dir_nofollow(parent_fd: int | None, target: str) -> int | None:
    try:
        if parent_fd is None:
            return os.open(target, _DIR_OPEN_FLAGS)
        return os.open(target, _DIR_OPEN_FLAGS, dir_fd=parent_fd)
    except OSError:
        return None


def _classify_allowed_log_relpath(
    raw_path: str,
) -> tuple[str, Literal["server_log", "crash_report", "plugin_log"]]:
    try:
        relpath = validate_canonical_relpath(raw_path.lstrip("/"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    parts = relpath.split("/")
    if any(_is_protected_name(part) or _is_sensitive_name(part) for part in parts):
        raise HTTPException(status_code=403, detail="Access denied to protected or sensitive file")

    low = parts[-1].casefold()
    if len(parts) == 2 and parts[0] == "logs" and low.endswith((".log", ".log.gz", ".txt")):
        return relpath, "server_log"
    if len(parts) == 2 and parts[0] == "crash-reports" and low.endswith((".txt", ".log")):
        return relpath, "crash_report"
    if len(parts) in (3, 4) and parts[0] == "plugins" and low.endswith(".log"):
        return relpath, "plugin_log"

    raise HTTPException(
        status_code=403,
        detail="Path is outside the allowed read-only logs locations",
    )


async def _resolve_logs_runtime_root(
    server_id: str,
    branch: str | None,
    query_bus: QueryBus,
) -> Path | None:
    server = await query_bus.ask(GetServerQuery(server_id=server_id))
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")  # noqa: B904

    live_root_str = getattr(server, "root_path", None)
    if not live_root_str and hasattr(server, "deployment") and server.deployment:
        live_root_str = getattr(server.deployment, "root_path", None)
    if not live_root_str:
        raise HTTPException(  # noqa: B904
            status_code=400,
            detail="Server deployment root path is not configured",
        )

    mode_raw = getattr(server, "mode", "simple")
    mode = str(getattr(mode_raw, "value", mode_raw) or "simple").lower()
    eff_branch = (branch or "").strip() or None

    if mode != "advanced" or eff_branch is None or eff_branch == "main":
        candidate = Path(live_root_str)
        if candidate.is_symlink() or not candidate.is_dir():
            return None
        return candidate.resolve()

    from sqlalchemy import select

    from app.core.persistence.db import database
    from app.modules.versioning.infrastructure.models import (
        ServerBranchModel,
        ServerRuntimeModel,
    )

    export_path: str | None = None
    async with database.session_factory() as session:
        br_res = await session.execute(
            select(ServerBranchModel).where(
                ServerBranchModel.server_id == server_id,
                ServerBranchModel.name == eff_branch,
            )
        )
        br_row = br_res.scalars().first()
        if br_row is not None and br_row.active_runtime_id:
            rt_row = await session.get(ServerRuntimeModel, br_row.active_runtime_id)
            if rt_row is not None and getattr(rt_row, "export_path", None):
                export_path = rt_row.export_path
        if not export_path:
            rt_res = await session.execute(
                select(ServerRuntimeModel)
                .where(
                    ServerRuntimeModel.server_id == server_id,
                    ServerRuntimeModel.branch_name == eff_branch,
                    ServerRuntimeModel.status.in_(("running", "starting", "stopped", "crashed")),
                )
                .order_by(ServerRuntimeModel.started_at.desc())
            )
            rt_row = rt_res.scalars().first()
            if rt_row is not None and getattr(rt_row, "export_path", None):
                export_path = rt_row.export_path

    if not export_path:
        return None

    cand = Path(export_path)
    if cand.is_symlink() or not cand.is_dir():
        return None

    exports_root = Path(live_root_str).resolve() / ".onx" / "branch-exports"
    try:
        cand_real = Path(os.path.realpath(cand))
        exports_real = Path(os.path.realpath(exports_root))
        if (
            os.path.commonpath([str(cand_real), str(exports_real)]) != str(exports_real)
            or cand_real == exports_real
        ):
            return None
    except ValueError:
        return None
    return cand_real


def _scan_logs_entries(runtime_root: Path) -> list[FileEntryResponse]:
    root_fd = _open_dir_nofollow(None, str(runtime_root))
    if root_fd is None:
        return []

    collected: list[tuple[float, FileEntryResponse]] = []

    def _collect_dir_files(
        dir_fd: int,
        prefix_rel: str,
        allowed_exts: tuple[str, ...],
        category: Literal["server_log", "crash_report", "plugin_log"],
    ) -> None:
        try:
            names = os.listdir(dir_fd)
        except OSError:
            return
        for name in names:
            if _is_protected_name(name) or _is_sensitive_name(name):
                continue
            if not name.casefold().endswith(allowed_exts):
                continue
            try:
                st = os.lstat(name, dir_fd=dir_fd)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            try:
                rel = validate_canonical_relpath(f"{prefix_rel}/{name}")
            except ValueError:
                continue
            collected.append(
                (
                    st.st_mtime,
                    FileEntryResponse(
                        name=name,
                        path=rel,
                        is_dir=False,
                        size=st.st_size,
                        modified_at=datetime.fromtimestamp(st.st_mtime, tz=UTC).isoformat(),
                        file_class="E",
                        editable=False,
                        log_category=category,
                    ),
                )
            )

    try:
        logs_fd = _open_dir_nofollow(root_fd, "logs")
        if logs_fd is not None:
            try:
                _collect_dir_files(logs_fd, "logs", (".log", ".log.gz", ".txt"), "server_log")
            finally:
                os.close(logs_fd)

        crashes_fd = _open_dir_nofollow(root_fd, "crash-reports")
        if crashes_fd is not None:
            try:
                _collect_dir_files(crashes_fd, "crash-reports", (".txt", ".log"), "crash_report")
            finally:
                os.close(crashes_fd)

        plugins_fd = _open_dir_nofollow(root_fd, "plugins")
        if plugins_fd is not None:
            try:
                try:
                    plugin_entries = os.listdir(plugins_fd)
                except OSError:
                    plugin_entries = []
                for plugin_name in plugin_entries:
                    if _is_protected_name(plugin_name) or _is_sensitive_name(plugin_name):
                        continue
                    plugin_fd = _open_dir_nofollow(plugins_fd, plugin_name)
                    if plugin_fd is None:
                        continue
                    try:
                        _collect_dir_files(
                            plugin_fd, f"plugins/{plugin_name}", (".log",), "plugin_log"
                        )
                        try:
                            sub_entries = os.listdir(plugin_fd)
                        except OSError:
                            sub_entries = []
                        for sub_name in sub_entries:
                            if _is_protected_name(sub_name) or _is_sensitive_name(sub_name):
                                continue
                            sub_fd = _open_dir_nofollow(plugin_fd, sub_name)
                            if sub_fd is None:
                                continue
                            try:
                                _collect_dir_files(
                                    sub_fd,
                                    f"plugins/{plugin_name}/{sub_name}",
                                    (".log",),
                                    "plugin_log",
                                )
                            finally:
                                os.close(sub_fd)
                    finally:
                        os.close(plugin_fd)
            finally:
                os.close(plugins_fd)
    finally:
        os.close(root_fd)

    def _sort_key(item: tuple[float, FileEntryResponse]) -> tuple[int, float, str]:
        mtime, entry = item
        if entry.log_category == "crash_report":
            priority = 0
        elif entry.path == "logs/latest.log":
            priority = 1
        else:
            priority = 2
        return (priority, -mtime, entry.path.lower())

    collected.sort(key=_sort_key)
    return [entry for _, entry in collected]


def _read_log_file_content(runtime_root: Path, raw_path: str) -> FileContentResponse:
    relpath, _ = _classify_allowed_log_relpath(raw_path)
    try:
        fd = open_safe_path_fd(str(runtime_root), relpath, flags=os.O_RDONLY)
    except SymlinkEscapeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Log file not found") from exc
    except IsADirectoryError as exc:
        raise HTTPException(
            status_code=400, detail="Target path is a directory, not a file"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise HTTPException(status_code=400, detail="Target path is not a regular file")
        total_size = st.st_size

        if relpath.casefold().endswith(".log.gz"):
            if total_size > MAX_COMPRESSED_LOG_INPUT_BYTES:
                return FileContentResponse(
                    path=relpath,
                    content="",
                    is_binary=True,
                    is_compressed=True,
                    total_size_bytes=total_size,
                )
            fp = os.fdopen(fd, "rb")
            fd = -1  # Ownership transferred to fp
            try:
                chunks: list[bytes] = []
                decompressed_bytes = 0
                truncated = False
                with gzip.GzipFile(fileobj=fp, mode="rb") as gz:
                    while decompressed_bytes <= MAX_EDITABLE_FILE_BYTES:
                        chunk = gz.read(65536)
                        if not chunk:
                            break
                        chunks.append(chunk)
                        decompressed_bytes += len(chunk)
                raw = b"".join(chunks)
                if len(raw) > MAX_EDITABLE_FILE_BYTES:
                    raw = raw[:MAX_EDITABLE_FILE_BYTES]
                    truncated = True
            except (OSError, EOFError, zlib.error):
                return FileContentResponse(
                    path=relpath,
                    content="",
                    is_binary=True,
                    is_compressed=True,
                    total_size_bytes=total_size,
                )
            finally:
                fp.close()

            text = raw.decode("utf-8", errors="replace")
            return FileContentResponse(
                path=relpath,
                content=text,
                is_binary=False,
                truncated=truncated,
                total_size_bytes=total_size,
                is_compressed=True,
            )

        if total_size > MAX_EDITABLE_FILE_BYTES:
            os.lseek(fd, total_size - MAX_EDITABLE_FILE_BYTES, os.SEEK_SET)
            chunks = []
            remaining = MAX_EDITABLE_FILE_BYTES
            while remaining > 0:
                chunk = os.read(fd, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            if b"\x00" in raw[:8192]:
                return FileContentResponse(
                    path=relpath,
                    content="",
                    is_binary=True,
                    truncated=True,
                    total_size_bytes=total_size,
                )
            text = raw.decode("utf-8", errors="replace")
            nl_idx = text.find("\n")
            if 0 <= nl_idx < 4096:
                text = text[nl_idx + 1 :]
            return FileContentResponse(
                path=relpath,
                content=text,
                is_binary=False,
                truncated=True,
                total_size_bytes=total_size,
                is_compressed=False,
            )

        chunks = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
        if b"\x00" in raw[:8192]:
            return FileContentResponse(
                path=relpath,
                content="",
                is_binary=True,
                total_size_bytes=total_size,
            )
        text = raw.decode("utf-8", errors="replace")
        return FileContentResponse(
            path=relpath,
            content=text,
            is_binary=False,
            truncated=False,
            total_size_bytes=total_size,
            is_compressed=False,
        )
    finally:
        if fd >= 0:
            os.close(fd)


def _stream_log_file_download(runtime_root: Path, raw_path: str) -> StreamingResponse:
    relpath, _ = _classify_allowed_log_relpath(raw_path)
    try:
        fd = open_safe_path_fd(str(runtime_root), relpath, flags=os.O_RDONLY)
    except SymlinkEscapeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Log file not found") from exc
    except IsADirectoryError as exc:
        raise HTTPException(
            status_code=400, detail="Target path is a directory, not a file"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise HTTPException(status_code=400, detail="Target path is not a regular file")
        fp = os.fdopen(fd, "rb")
        fd = -1
    except Exception:
        if fd >= 0:
            os.close(fd)
        raise

    def _iter_chunks():
        try:
            while True:
                chunk = fp.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            fp.close()

    safe_filename = Path(relpath).name.replace('"', "")
    return StreamingResponse(
        _iter_chunks(),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename}"',
            "Content-Length": str(st.st_size),
        },
    )


async def _resolve_server_file_path(
    server_id: str,
    relative_path: str,
    query_bus: QueryBus,
    must_exist: bool = False,
    follow_symlink: bool = True,
    branch: str | None = None,
) -> tuple[Path, Path, str, bool, bool]:

    if branch == "live-state":
        raise HTTPException(  # noqa: B904
            status_code=422,
            detail="Use /files/live-state endpoints to access Live State Class-C files",
        )
    server = await query_bus.ask(GetServerQuery(server_id=server_id))
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")  # noqa: B904

    root_path = getattr(server, "root_path", None)
    if not root_path and hasattr(server, "deployment") and server.deployment:
        root_path = getattr(server.deployment, "root_path", None)

    if not root_path:
        raise HTTPException(  # noqa: B904
            status_code=400,
            detail="Server deployment root path is not configured",
        )

    read_only = False
    git_scoped = False
    branch_root = await query_bus.ask(
        GetBranchFilesRootQuery(server_id=server_id, branch=branch or None)
    )
    if branch_root is not None:
        root_path = str(branch_root.root_path)
        read_only = branch_root.read_only
        git_scoped = True

    resolved_root = Path(root_path).resolve()
    clean_rel = relative_path.lstrip("/") if relative_path else ""
    if follow_symlink:
        target_path = (resolved_root / clean_rel).resolve()
    else:
        # Keep the final component unresolved so an in-root symlink is addressed itself.
        lexical = Path(os.path.normpath(resolved_root / clean_rel))
        if lexical == resolved_root:
            target_path = lexical
        else:
            target_path = lexical.parent.resolve() / lexical.name

    try:
        target_path.relative_to(resolved_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Path escapes server root directory")  # noqa: B904

    _assert_not_protected_path(clean_rel, target_path, resolved_root)

    exists = target_path.exists() if follow_symlink else os.path.lexists(target_path)
    if must_exist and not exists:
        # Do not reveal whether a normalized-equivalent secret name exists.
        _assert_not_sensitive(target_path)
        raise HTTPException(status_code=404, detail="Path does not exist")  # noqa: B904

    rel_str = str(target_path.relative_to(resolved_root))
    if rel_str == ".":
        rel_str = ""

    return resolved_root, target_path, rel_str, read_only, git_scoped


@router.get("", response_model=list[FileEntryResponse])
async def list_files(
    server_id: str,
    path: str = Query(default=""),
    branch: str | None = Query(default=None),
    scope: str | None = Query(default=None),
    query_bus: QueryBus = Depends(get_query_bus),  # noqa: B008
    _current_user: dict = Depends(require_server_permission("server.{id}.files")),  # noqa: B008
) -> list[FileEntryResponse]:
    if _normalize_scope(scope) == "logs":
        runtime_root = await _resolve_logs_runtime_root(server_id, branch, query_bus)
        if runtime_root is None:
            return []
        return _scan_logs_entries(runtime_root)

    resolved_root, target_path, _, read_only, git_scoped = await _resolve_server_file_path(
        server_id, path, query_bus, must_exist=True, branch=branch
    )
    if not target_path.is_dir():
        raise HTTPException(status_code=400, detail="Target path is a file, not a directory")  # noqa: B904

    entries = local_fs.list_dir(str(target_path))
    results: list[FileEntryResponse] = []
    for item in entries:
        if _is_protected_name(item.name) or _is_sensitive_name(item.name):
            continue
        try:
            item_rel = item.resolve().relative_to(resolved_root).as_posix()
        except ValueError:
            # Skip if symlink points outside
            continue
        is_directory = item.is_dir()
        file_size = 0
        modified_at: str | None = None
        try:
            st = item.stat()
            modified_at = datetime.fromtimestamp(st.st_mtime, tz=UTC).isoformat()
            if not is_directory:
                file_size = st.st_size
        except OSError:
            # Dangling symlink or unreadable entry: report the link itself.
            try:
                lst = item.lstat()
                modified_at = datetime.fromtimestamp(lst.st_mtime, tz=UTC).isoformat()
                if not is_directory:
                    file_size = lst.st_size
            except OSError:
                continue

        file_class: str | None = None
        editable: bool | None = False if is_directory else None
        if not is_directory:
            raw_class = classify(item_rel)
            file_class = _normalize_file_class(raw_class)
            is_reserved_root = (
                "/" not in item_rel and _normalize_name(item.name) in RESERVED_ROOT_WRITE_NAMES
            )
            if read_only or is_reserved_root or _is_binary_extension(item.name):
                editable = False
            elif git_scoped:
                editable = raw_class == "B"
            else:
                editable = True

        results.append(
            FileEntryResponse(
                name=item.name,
                path=item_rel,
                is_dir=is_directory,
                size=file_size,
                modified_at=modified_at,
                file_class=file_class,
                editable=editable,
            )
        )

    # Sort directories first, then files alphabetically
    results.sort(key=lambda x: (not x.is_dir, x.name.lower()))
    return results


@router.get("/content", response_model=FileContentResponse)
async def read_file_content(
    server_id: str,
    path: str = Query(...),
    branch: str | None = Query(default=None),
    scope: str | None = Query(default=None),
    query_bus: QueryBus = Depends(get_query_bus),  # noqa: B008
    _current_user: dict = Depends(require_server_permission("server.{id}.files")),  # noqa: B008
) -> FileContentResponse:
    if _normalize_scope(scope) == "logs":
        runtime_root = await _resolve_logs_runtime_root(server_id, branch, query_bus)
        if runtime_root is None:
            raise HTTPException(
                status_code=404,
                detail="No runtime logs available for this branch",
            )
        return _read_log_file_content(runtime_root, path)

    _, target_path, rel_str, _, _ = await _resolve_server_file_path(
        server_id, path, query_bus, must_exist=True, branch=branch
    )
    if target_path.is_dir():
        raise HTTPException(status_code=400, detail="Target path is a directory, not a file")  # noqa: B904

    _assert_not_sensitive(target_path)

    with contextlib.suppress(OSError):
        file_size = target_path.stat().st_size
        if file_size > MAX_EDITABLE_FILE_BYTES:
            raise MCSError(
                message="File is too large to edit in browser (max 5 MB). Download it instead.",
                code="FILE_TOO_LARGE",
                details={
                    "path": rel_str,
                    "size_bytes": file_size,
                    "max_bytes": MAX_EDITABLE_FILE_BYTES,
                },
                http_status=413,
            )

    try:
        raw_bytes = local_fs.read_binary(str(target_path))
        if len(raw_bytes) > MAX_EDITABLE_FILE_BYTES:
            raise MCSError(
                message="File is too large to edit in browser (max 5 MB). Download it instead.",
                code="FILE_TOO_LARGE",
                details={
                    "path": rel_str,
                    "size_bytes": len(raw_bytes),
                    "max_bytes": MAX_EDITABLE_FILE_BYTES,
                },
                http_status=413,
            )
        if b"\x00" in raw_bytes[:8192]:
            return FileContentResponse(path=rel_str, content="", is_binary=True)
        content = raw_bytes.decode("utf-8")
        return FileContentResponse(path=rel_str, content=content, is_binary=False)
    except (UnicodeDecodeError, ValueError):
        return FileContentResponse(path=rel_str, content="", is_binary=True)


@router.put("/content", response_model=FileContentResponse)
async def write_file_content(
    server_id: str,
    body: WriteFileContentRequest,
    path: str = Query(...),
    branch: str | None = Query(default=None),
    scope: str | None = Query(default=None),
    query_bus: QueryBus = Depends(get_query_bus),  # noqa: B008
    _current_user: dict = Depends(require_server_permission("server.{id}.files")),  # noqa: B008
) -> FileContentResponse:
    _assert_not_logs_write(scope)
    _, target_path, rel_str, read_only, git_scoped = await _resolve_server_file_path(
        server_id, path, query_bus, must_exist=False, branch=branch
    )
    if target_path.exists() and target_path.is_dir():
        raise HTTPException(status_code=400, detail="Target path is a directory, not a file")  # noqa: B904

    _assert_file_mutation_allowed(rel_str, read_only, git_scoped=git_scoped)
    _assert_not_sensitive(target_path)

    encoded = body.content.encode("utf-8")
    if len(encoded) > MAX_EDITABLE_FILE_BYTES:
        raise MCSError(
            message="File is too large to edit in browser (max 5 MB). Download it instead.",
            code="FILE_TOO_LARGE",
            details={
                "path": rel_str,
                "size_bytes": len(encoded),
                "max_bytes": MAX_EDITABLE_FILE_BYTES,
            },
            http_status=413,
        )

    # Use write_binary_atomic to prevent partial file writes on failure
    local_fs.write_binary_atomic(str(target_path), encoded)
    return FileContentResponse(path=rel_str, content=body.content)


@router.delete("", status_code=204)
async def delete_file_or_dir(
    server_id: str,
    path: str = Query(...),
    branch: str | None = Query(default=None),
    scope: str | None = Query(default=None),
    query_bus: QueryBus = Depends(get_query_bus),  # noqa: B008
    _current_user: dict = Depends(require_server_permission("server.{id}.files")),  # noqa: B008
) -> None:
    _assert_not_logs_write(scope)
    resolved_root, target_path, rel_str, read_only, git_scoped = await _resolve_server_file_path(
        server_id,
        path,
        query_bus,
        must_exist=True,
        follow_symlink=False,
        branch=branch,
    )
    if target_path == resolved_root:
        raise HTTPException(status_code=400, detail="Cannot delete server root directory")  # noqa: B904

    _assert_file_mutation_allowed(
        rel_str,
        read_only,
        git_scoped=git_scoped,
        is_directory=target_path.is_dir(),
    )
    _assert_not_sensitive(target_path)

    if target_path.is_symlink():
        # Remove the link only; its target is never touched.
        target_path.unlink()
    elif target_path.is_dir():
        local_fs.delete_dir(str(target_path), root=str(resolved_root))
    else:
        local_fs.delete(str(target_path))


@router.post("/upload", response_model=FileEntryResponse, status_code=201)
async def upload_file(
    server_id: str,
    path: str = Query(default=""),
    branch: str | None = Query(default=None),
    scope: str | None = Query(default=None),
    file: UploadFile = File(...),  # noqa: B008
    query_bus: QueryBus = Depends(get_query_bus),  # noqa: B008
    _current_user: dict = Depends(require_server_permission("server.{id}.files")),  # noqa: B008
) -> FileEntryResponse:
    _assert_not_logs_write(scope)
    filename = file.filename or "uploaded_file"
    # Clean filename of any path components
    filename = Path(filename).name

    dest_rel_path = f"{path.strip('/')}/{filename}" if path.strip("/") else filename
    (
        resolved_root,
        target_file_path,
        rel_str,
        read_only,
        git_scoped,
    ) = await _resolve_server_file_path(
        server_id, dest_rel_path, query_bus, must_exist=False, branch=branch
    )
    if target_file_path.exists() and target_file_path.is_dir():
        raise HTTPException(status_code=400, detail="Target path is a directory, not a file")  # noqa: B904

    _assert_file_mutation_allowed(rel_str, read_only, git_scoped=git_scoped)
    _assert_not_sensitive(target_file_path)

    try:
        safe_target_str = resolve_safe_disk_path(
            str(resolved_root), rel_str, allow_create_parents=True
        )
    except SymlinkEscapeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    target_file_path = Path(safe_target_str)
    if target_file_path.is_symlink():
        raise HTTPException(status_code=403, detail="Target path must not be a symlink")

    chunk_size = 64 * 1024
    max_mb = AppSettings().files_max_upload_size_mb
    max_bytes = max_mb * 1024 * 1024 if max_mb > 0 else 0

    total_bytes = 0
    parent = target_file_path.parent
    try:
        parent_fd = os.open(str(parent), _DIR_OPEN_FLAGS)
    except OSError as exc:
        raise HTTPException(
            status_code=403, detail="Upload directory is not safe or accessible"
        ) from exc

    fd, tmp_path_str = tempfile.mkstemp(dir=str(parent), suffix=".tmp")
    tmp_path = Path(tmp_path_str)
    replaced = False

    try:
        with os.fdopen(fd, "wb") as out_fp:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if max_bytes > 0 and total_bytes > max_bytes:
                    raise HTTPException(  # noqa: B904
                        status_code=413,
                        detail=f"Uploaded file exceeds maximum allowed size of {max_mb} MB",
                    )
                out_fp.write(chunk)
            out_fp.flush()
            os.fsync(out_fp.fileno())

        os.replace(str(tmp_path), str(target_file_path))
        replaced = True
        local_fs._fsync_parent_dir(parent)
    finally:
        os.close(parent_fd)
        if not replaced and tmp_path.exists():
            with contextlib.suppress(OSError):
                tmp_path.unlink()

    return FileEntryResponse(
        name=target_file_path.name,
        path=rel_str,
        is_dir=False,
        size=total_bytes,
    )


@router.get("/download")
async def download_file(
    server_id: str,
    path: str = Query(...),
    branch: str | None = Query(default=None),
    scope: str | None = Query(default=None),
    query_bus: QueryBus = Depends(get_query_bus),  # noqa: B008
    _current_user: dict = Depends(  # noqa: B008
        require_server_permission("server.{id}.files")  # noqa: B008
    ),
) -> Response:
    if _normalize_scope(scope) == "logs":
        runtime_root = await _resolve_logs_runtime_root(server_id, branch, query_bus)
        if runtime_root is None:
            raise HTTPException(
                status_code=404,
                detail="No runtime logs available for this branch",
            )
        return _stream_log_file_download(runtime_root, path)

    _, target_path, _, _, _ = await _resolve_server_file_path(
        server_id, path, query_bus, must_exist=True, branch=branch
    )
    if target_path.is_dir():
        raise HTTPException(status_code=400, detail="Target path is a directory, not a file")  # noqa: B904

    _assert_not_sensitive(target_path)

    return FileResponse(
        path=str(target_path),
        filename=target_path.name,
        media_type="application/octet-stream",
    )


@router.post("/mkdir", response_model=FileEntryResponse, status_code=201)
async def create_directory(
    server_id: str,
    path: str = Query(...),
    branch: str | None = Query(default=None),
    scope: str | None = Query(default=None),
    query_bus: QueryBus = Depends(get_query_bus),  # noqa: B008
    _current_user: dict = Depends(require_server_permission("server.{id}.files")),  # noqa: B008
) -> FileEntryResponse:
    _assert_not_logs_write(scope)

    _, target_path, rel_str, read_only, git_scoped = await _resolve_server_file_path(
        server_id, path, query_bus, must_exist=False, branch=branch
    )
    if target_path.exists() and not target_path.is_dir():
        raise HTTPException(status_code=409, detail="A file already exists at this path")  # noqa: B904
    _assert_file_mutation_allowed(rel_str, read_only, git_scoped=git_scoped, is_directory=True)
    try:
        local_fs.ensure_dir(str(target_path))
    except (FileExistsError, NotADirectoryError) as exc:
        raise HTTPException(status_code=409, detail="A file already exists at this path") from exc  # noqa: B904
    return FileEntryResponse(
        name=target_path.name,
        path=rel_str,
        is_dir=True,
        size=0,
    )


# --- P3-4 Live State endpoints ---


@router.get("/live-state", response_model=LiveStateFileListResponse)
async def list_live_state(
    server_id: str,
    _current_user: Annotated[dict, Depends(require_server_permission("server.{id}.files"))],
    _advanced: Annotated[dict, Depends(require_advanced_mode)],
    path: str = Query(default="/"),
) -> LiveStateFileListResponse:
    from app.core.allowlist import classify, validate_canonical_relpath
    from app.core.host_state import resolve_host_state_layout
    from app.core.persistence.db import database
    from app.modules.server.infrastructure.repository import SQLServerRepository
    from app.modules.shared.value_objects import ServerId
    from app.modules.versioning.infrastructure.dynamic_class_c import DynamicClassCService

    async with database.session_factory() as session:
        server_repo = SQLServerRepository(session)
        server = await server_repo.get(ServerId(server_id))
        if server is None:
            raise HTTPException(status_code=404, detail="Server not found")  # noqa: B904
        live_root = Path(
            getattr(server, "deployment", None).root_path
            if getattr(server, "deployment", None) is not None
            else getattr(server, "root_path", "")
        ).resolve()

    layout = resolve_host_state_layout()
    dyn = DynamicClassCService(layout)
    dynamic_paths = dyn.list_paths(server_id)
    dynamic_set = set(dynamic_paths)

    raw_rel = (path or "").strip("/")
    if raw_rel:
        try:
            rel_dir = validate_canonical_relpath(raw_rel)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    else:
        rel_dir = ""
    if rel_dir:
        try:
            target_dir = Path(resolve_safe_disk_path(str(live_root), rel_dir))
        except SymlinkEscapeError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    else:
        target_dir = live_root
    if not target_dir.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")  # noqa: B904

    deny = {".env", ".git", ".onx", ".onx-manager", ".mcsmanager"}
    items = []
    for entry in sorted(target_dir.iterdir(), key=lambda p: p.name):
            if entry.name in deny or entry.name.startswith(".env"):
                continue
            if entry.is_symlink():
                continue
            entry_rel = (Path(rel_dir) / entry.name).as_posix() if rel_dir else entry.name
            if entry_rel.startswith("./"):
                entry_rel = entry_rel[2:]
            cls = classify(entry_rel, dynamic_class_c=dynamic_set)
            # directories: include if class C or contains class C
            include = False
            if entry.is_dir():
                if cls == "C":
                    include = True
                else:
                    # contains class C?
                    for sub in entry.rglob("*"):
                        if sub.is_symlink():
                            continue
                        sub_rel = sub.relative_to(live_root).as_posix()
                        if classify(sub_rel, dynamic_class_c=dynamic_set) == "C":
                            include = True
                            break
            else:
                if cls == "C":
                    include = True
            if not include:
                continue
            st = entry.stat()
            if entry.is_dir() or entry_rel.startswith(
                ("world/", "world_nether/", "world_the_end/")
            ) or entry_rel.lower().endswith((".mca", ".dat", ".dat_old", ".mcr", ".lock")):
                writable = False
            else:
                writable = (entry_rel in dynamic_set) or (cls == "C")
            items.append(
                LiveStateFileEntryResponse(
                    name=entry.name,
                    path=f"/{entry_rel}",
                    is_dir=entry.is_dir(),
                    size=st.st_size if entry.is_file() else 0,
                    modified_at=st.st_mtime,
                    file_class="C",
                    is_dynamic_class_c=entry_rel in dynamic_set,
                    writable=writable,
                )
            )
    return LiveStateFileListResponse(items=items)


@router.get("/live-state/content", response_model=LiveStateFileContentResponse)
async def read_live_state_content(
    server_id: str,
    _current_user: Annotated[dict, Depends(require_server_permission("server.{id}.files"))],
    _advanced: Annotated[dict, Depends(require_advanced_mode)],
    path: str = Query(...),
) -> LiveStateFileContentResponse:
    from app.core.allowlist import classify, open_safe_path_fd, validate_canonical_relpath
    from app.core.host_state import resolve_host_state_layout
    from app.core.persistence.db import database
    from app.modules.server.infrastructure.repository import SQLServerRepository
    from app.modules.shared.value_objects import ServerId
    from app.modules.versioning.infrastructure.dynamic_class_c import DynamicClassCService

    try:
        relpath = validate_canonical_relpath(path.lstrip("/"))
    except ValueError as exc:
        from app.core.exceptions import ValidationError

        raise ValidationError(str(exc)) from exc
    async with database.session_factory() as session:
        server_repo = SQLServerRepository(session)
        server = await server_repo.get(ServerId(server_id))
        if server is None:
            raise HTTPException(status_code=404, detail="Server not found")  # noqa: B904
        live_root = Path(
            getattr(server, "deployment", None).root_path
            if getattr(server, "deployment", None) is not None
            else getattr(server, "root_path", "")
        ).resolve()

    layout = resolve_host_state_layout()
    dyn = DynamicClassCService(layout)
    dynamic_set = set(dyn.list_paths(server_id))
    cls = classify(relpath, dynamic_class_c=dynamic_set)
    if cls != "C":
        raise HTTPException(  # noqa: B904
            status_code=403, detail=f"Path '{relpath}' is Class {cls}, not Live State Class C"
        )

    import os as _os

    try:
        fd = open_safe_path_fd(str(live_root), relpath, flags=_os.O_RDONLY)
    except SymlinkEscapeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except IsADirectoryError as exc:
        raise HTTPException(
            status_code=400, detail="Target path is a directory, not a file"
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        st = _os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise HTTPException(status_code=400, detail="Target path is not a regular file")
        data = _os.read(fd, 2 * 1024 * 1024 + 1)
    except IsADirectoryError as exc:
        raise HTTPException(
            status_code=400, detail="Target path is a directory, not a file"
        ) from exc
    finally:
        _os.close(fd)
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large")  # noqa: B904
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="Binary file cannot be edited")  # noqa: B904
    return LiveStateFileContentResponse(
        server_id=server_id,
        path=f"/{relpath}",
        content=content,
        encoding="utf-8",
        size=len(data),
        is_dynamic_class_c=relpath in dynamic_set,
    )


@router.put("/live-state/content", response_model=LiveStateWriteResponse)
async def write_live_state_content(
    server_id: str,
    body: LiveStateWriteRequest,
    _current_user: Annotated[dict, Depends(require_server_permission("server.{id}.files"))],
    _advanced: Annotated[dict, Depends(require_advanced_mode)],
) -> LiveStateWriteResponse:

    from app.core.allowlist import (
        classify,
        resolve_safe_disk_path,
        validate_canonical_relpath,
    )
    from app.core.host_state import resolve_host_state_layout
    from app.core.persistence.db import database
    from app.modules.server.infrastructure.repository import SQLServerRepository
    from app.modules.shared.value_objects import ServerId
    from app.modules.versioning.infrastructure.dynamic_class_c import DynamicClassCService
    from app.modules.versioning.infrastructure.fs_atomic import atomic_write_private

    try:
        relpath = validate_canonical_relpath(body.path.lstrip("/"))
    except ValueError as exc:
        from app.core.exceptions import ValidationError

        raise ValidationError(str(exc)) from exc
    async with database.session_factory() as session:
        server_repo = SQLServerRepository(session)
        server = await server_repo.get(ServerId(server_id))
        if server is None:
            raise HTTPException(status_code=404, detail="Server not found")  # noqa: B904
        live_root = Path(
            getattr(server, "deployment", None).root_path
            if getattr(server, "deployment", None) is not None
            else getattr(server, "root_path", "")
        ).resolve()

    from app.modules.versioning.application.repo_lease import RepoLeaseManager
    layout = resolve_host_state_layout()
    async with RepoLeaseManager(locks_dir=layout.locks).acquire(server_id, holder="live-state-content"):  # noqa: E501
        dyn = DynamicClassCService(layout)
        dynamic_set = set(dyn.list_paths(server_id))
        cls = classify(relpath, dynamic_class_c=dynamic_set)
        if cls != "C":
            raise HTTPException(  # noqa: B904
                status_code=403, detail=f"Path '{relpath}' is not a Live State Class C file"
            )
        if relpath.startswith(("world/", "world_nether/", "world_the_end/")) or relpath.endswith(
            (".dat", ".dat_old", ".mca", ".mcr", ".lock")
        ):
            raise HTTPException(  # noqa: B904
                status_code=403, detail="Binary world data cannot be edited via live-state content API"  # noqa: E501
        )

        encoded = body.content.encode("utf-8")
        if len(encoded) > 2 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Payload too large")  # noqa: B904

        # runtime status
        status = str(getattr(server.status, "value", server.status)).upper()

        # Case transitional
        if status in {"STARTING", "STOPPING", "PROVISIONING", "ERROR"}:
            raise HTTPException(  # noqa: B904
                status_code=409,
                detail=f"Cannot edit live state while server is in {server.status} state",
            )

        target_path = resolve_safe_disk_path(str(live_root), relpath, allow_create_parents=True)

        if status in {"STOPPED", "CREATED", "CRASHED"}:
            # session.lock check
            lock = live_root / "world" / "session.lock"
            if lock.exists():
                try:
                    import fcntl

                    with open(lock, "rb") as fh:
                        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                except (BlockingIOError, OSError):
                    raise HTTPException(  # noqa: B904
                        status_code=409,
                        detail="Server world session.lock is active; cannot write live state",
                    ) from None
            atomic_write_private(target_path, encoded)
            return LiveStateWriteResponse(
                status="written",
                server_id=server_id,
                path=f"/{relpath}",
                rcon_flushed=False,
                rcon_reloaded=False,
                reload_command=None,
            )

        # RUNNING
        safe = {"whitelist reload", "minecraft:reload", "reload"}
        if body.reload_command is not None and body.reload_command not in safe:
            raise HTTPException(  # noqa: B904
                status_code=422, detail="Unsupported reload_command for live-state write"
            )
        effective_reload = body.reload_command or (
            "whitelist reload" if relpath == "whitelist.json" else "minecraft:reload"
        )

        # RCON flush
        # resolve provider
        from app.modules.server.domain.value_objects import (
            build_server_handle,
            default_provider_for_platform,
        )
        from app.modules.server.infrastructure.providers import provider_factory
        from app.modules.server.infrastructure.repository import SQLServerRepository

        provider_name = getattr(server, "provider", None) or default_provider_for_platform()
        if getattr(server, "runtime", None) is not None and getattr(server.runtime, "provider", None):  # noqa: E501
            provider_name = server.runtime.provider
        try:
            _got = provider_factory.get(provider_name)
            if hasattr(_got, "__await__"):
                provider = await _got
            else:
                provider = _got
        except Exception:
            provider = None
        try:
            handle = build_server_handle(server, provider_name, server_dir=live_root)
        except Exception:
            handle = None

        rcon_flushed = False
        # Step1 flush
        try:
            if provider is not None and handle is not None and hasattr(provider, "execute_command"):
                await provider.execute_command(handle, "save-all flush")
                rcon_flushed = True
        except Exception:
            raise HTTPException(  # noqa: B904
                status_code=409, detail="RCON save-all flush failed; live-state write aborted"
            )

        # Step2 write with rollback buffer
        previous_bytes = None
        try:
            if target_path.exists():
                previous_bytes = target_path.read_bytes()
        except Exception:
            previous_bytes = None
        atomic_write_private(target_path, encoded)

        rcon_reloaded = False
        # Step3 reload
        try:
            if provider is not None and handle is not None and hasattr(provider, "execute_command"):
                await provider.execute_command(handle, effective_reload)
                rcon_reloaded = True
        except Exception:
            # restore
            if previous_bytes is None:
                with contextlib.suppress(Exception):
                    target_path.unlink(missing_ok=True)
            else:
                atomic_write_private(target_path, previous_bytes)
            raise HTTPException(  # noqa: B904
                status_code=409,
                detail="RCON reload failed after live-state write; previous file restored",
            )

        return LiveStateWriteResponse(
            status="written",
            server_id=server_id,
            path=f"/{relpath}",
            rcon_flushed=rcon_flushed,
            rcon_reloaded=rcon_reloaded,
            reload_command=effective_reload,
        )
