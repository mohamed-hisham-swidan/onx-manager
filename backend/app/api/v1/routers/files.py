import contextlib
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import get_query_bus, require_server_permission
from app.api.v1.schemas.files import (
    FileContentResponse,
    FileEntryResponse,
    WriteFileContentRequest,
)
from app.core.allowlist import classify
from app.core.config import AppSettings
from app.core.query_bus import QueryBus
from app.modules.server.application.queries.get_server import GetServerQuery
from app.modules.server.infrastructure.fs import local_fs
from app.modules.versioning.application import GetBranchFilesRootQuery

router = APIRouter(prefix="/api/v1/servers/{server_id}/files", tags=["files"])

__all__ = ["router"]

SENSITIVE_FILENAMES: frozenset[str] = frozenset({".env"})
PROTECTED_DIRNAMES: frozenset[str] = frozenset(
    {".git", ".onx", ".onx-manager", ".mcsmanager"}
)
RESERVED_ROOT_WRITE_NAMES: frozenset[str] = frozenset(
    {"onx-jars.lock.json", ".gitattributes"}
)


def _normalize_name(name: str) -> str:
    """Casefold a path component and strip trailing dots and spaces.

    Windows-style filesystems ignore trailing dots/spaces, so ``.env.`` or
    ``.onx `` would otherwise reach the protected entry.
    """
    return name.rstrip(". ").casefold()


def _is_protected_name(name: str) -> bool:
    return _normalize_name(name) in PROTECTED_DIRNAMES


def _assert_not_sensitive(target_path: Path) -> None:
    """Deny access to files carrying application secrets (e.g. .env).

    The comparison is case-insensitive and ignores trailing dots/spaces so the
    guard also holds on case-insensitive filesystems (macOS/Windows) where a
    differently-cased name resolves to the same file. The resolved basename is
    used, so ./.env and any normalized nested/.. form are covered too.
    """
    if _normalize_name(target_path.name) in {_normalize_name(n) for n in SENSITIVE_FILENAMES}:
        raise HTTPException(status_code=403, detail="File access denied for sensitive server file")


def _assert_not_protected_path(relative_path: str, target_path: Path, root: Path) -> None:
    """Deny any path having a metadata folder (.onx, .onx-manager, .mcsmanager) as a component."""
    raw_parts = [part for part in relative_path.replace("\\", "/").split("/") if part]
    try:
        resolved_parts = list(target_path.relative_to(root).parts)
    except ValueError:
        resolved_parts = []
    if any(_is_protected_name(part) for part in (*raw_parts, *resolved_parts)):
        raise HTTPException(status_code=403, detail="Access denied to protected server folder")


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
        raise HTTPException(
            status_code=403,
            detail="Branch 'main' is read-only; create a working branch to edit files",
        )

    parts = [part for part in relative_path.replace("\\", "/").split("/") if part]
    if len(parts) == 1 and _normalize_name(parts[0]) in RESERVED_ROOT_WRITE_NAMES:
        raise HTTPException(
            status_code=403,
            detail="This file is managed by the panel and cannot be modified through Files",
        )

    if git_scoped and not is_directory and classify(relative_path) != "B":
        raise HTTPException(
            status_code=403,
            detail=(
                "Only Class-B configuration files can be edited on an Advanced branch; "
                "Class-A binaries use the CAS lockfile and Class-C live files have "
                "their own view"
            ),
        )


async def _resolve_server_file_path(
    server_id: str,
    relative_path: str,
    query_bus: QueryBus,
    must_exist: bool = False,
    follow_symlink: bool = True,
    branch: str | None = None,
) -> tuple[Path, Path, str, bool, bool]:

    server = await query_bus.ask(GetServerQuery(server_id=server_id))
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")

    root_path = getattr(server, "root_path", None)
    if not root_path and hasattr(server, "deployment") and server.deployment:
        root_path = getattr(server.deployment, "root_path", None)

    if not root_path:
        raise HTTPException(
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
        raise HTTPException(status_code=403, detail="Path escapes server root directory")

    _assert_not_protected_path(clean_rel, target_path, resolved_root)

    exists = target_path.exists() if follow_symlink else os.path.lexists(target_path)
    if must_exist and not exists:
        # Do not reveal whether a normalized-equivalent secret name exists.
        _assert_not_sensitive(target_path)
        raise HTTPException(status_code=404, detail="Path does not exist")

    rel_str = str(target_path.relative_to(resolved_root))
    if rel_str == ".":
        rel_str = ""

    return resolved_root, target_path, rel_str, read_only, git_scoped


@router.get("", response_model=list[FileEntryResponse])
async def list_files(
    server_id: str,
    path: str = Query(default=""),
    branch: str | None = Query(default=None),
    query_bus: QueryBus = Depends(get_query_bus),
    _current_user: dict = Depends(require_server_permission("server.{id}.files")),
) -> list[FileEntryResponse]:
    resolved_root, target_path, _, _, _ = await _resolve_server_file_path(
        server_id, path, query_bus, must_exist=True, branch=branch
    )
    if not target_path.is_dir():
        raise HTTPException(status_code=400, detail="Target path is a file, not a directory")

    entries = local_fs.list_dir(str(target_path))
    results: list[FileEntryResponse] = []
    for item in entries:
        if _is_protected_name(item.name):
            continue
        try:
            item_rel = str(item.resolve().relative_to(resolved_root))
        except ValueError:
            # Skip if symlink points outside
            continue
        is_directory = item.is_dir()
        file_size = 0
        if not is_directory:
            try:
                file_size = item.stat().st_size
            except OSError:
                # Dangling symlink or unreadable entry: report the link itself.
                try:
                    file_size = item.lstat().st_size
                except OSError:
                    continue
        results.append(
            FileEntryResponse(
                name=item.name,
                path=item_rel,
                is_dir=is_directory,
                size=file_size,
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
    query_bus: QueryBus = Depends(get_query_bus),
    _current_user: dict = Depends(require_server_permission("server.{id}.files")),
) -> FileContentResponse:
    _, target_path, rel_str, _, _ = await _resolve_server_file_path(
        server_id, path, query_bus, must_exist=True, branch=branch
    )
    if target_path.is_dir():
        raise HTTPException(status_code=400, detail="Target path is a directory, not a file")

    _assert_not_sensitive(target_path)

    try:
        raw_bytes = local_fs.read_binary(str(target_path))
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
    query_bus: QueryBus = Depends(get_query_bus),
    _current_user: dict = Depends(require_server_permission("server.{id}.files")),
) -> FileContentResponse:
    _, target_path, rel_str, read_only, git_scoped = await _resolve_server_file_path(
        server_id, path, query_bus, must_exist=False, branch=branch
    )
    if target_path.exists() and target_path.is_dir():
        raise HTTPException(status_code=400, detail="Target path is a directory, not a file")

    _assert_file_mutation_allowed(rel_str, read_only, git_scoped=git_scoped)
    _assert_not_sensitive(target_path)

    # Use write_binary_atomic to prevent partial file writes on failure
    local_fs.write_binary_atomic(str(target_path), body.content.encode("utf-8"))
    return FileContentResponse(path=rel_str, content=body.content)


@router.delete("", status_code=204)
async def delete_file_or_dir(
    server_id: str,
    path: str = Query(...),
    branch: str | None = Query(default=None),
    query_bus: QueryBus = Depends(get_query_bus),
    _current_user: dict = Depends(require_server_permission("server.{id}.files")),
) -> None:
    resolved_root, target_path, rel_str, read_only, git_scoped = (
        await _resolve_server_file_path(
            server_id,
            path,
            query_bus,
            must_exist=True,
            follow_symlink=False,
            branch=branch,
        )
    )
    if target_path == resolved_root:
        raise HTTPException(status_code=400, detail="Cannot delete server root directory")

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
    file: UploadFile = File(...),
    query_bus: QueryBus = Depends(get_query_bus),
    _current_user: dict = Depends(require_server_permission("server.{id}.files")),
) -> FileEntryResponse:
    filename = file.filename or "uploaded_file"
    # Clean filename of any path components
    filename = Path(filename).name

    dest_rel_path = f"{path.strip('/')}/{filename}" if path.strip("/") else filename
    resolved_root, target_file_path, rel_str, read_only, git_scoped = (
        await _resolve_server_file_path(
            server_id, dest_rel_path, query_bus, must_exist=False, branch=branch
        )
    )
    if target_file_path.exists() and target_file_path.is_dir():
        raise HTTPException(status_code=400, detail="Target path is a directory, not a file")

    _assert_file_mutation_allowed(rel_str, read_only, git_scoped=git_scoped)
    _assert_not_sensitive(target_file_path)

    chunk_size = 64 * 1024
    max_mb = AppSettings().files_max_upload_size_mb
    max_bytes = max_mb * 1024 * 1024 if max_mb > 0 else 0

    total_bytes = 0
    parent = target_file_path.parent
    local_fs.ensure_dir(str(parent))
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
                    raise HTTPException(
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
    query_bus: QueryBus = Depends(get_query_bus),
    _current_user: dict = Depends(
        require_server_permission("server.{id}.files")
    ),
) -> FileResponse:

    _, target_path, _, _, _ = await _resolve_server_file_path(
        server_id, path, query_bus, must_exist=True, branch=branch
    )
    if target_path.is_dir():
        raise HTTPException(status_code=400, detail="Target path is a directory, not a file")

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
    query_bus: QueryBus = Depends(get_query_bus),
    _current_user: dict = Depends(require_server_permission("server.{id}.files")),
) -> FileEntryResponse:

    _, target_path, rel_str, read_only, git_scoped = await _resolve_server_file_path(
        server_id, path, query_bus, must_exist=False, branch=branch
    )
    if target_path.exists() and not target_path.is_dir():
        raise HTTPException(status_code=409, detail="A file already exists at this path")
    _assert_file_mutation_allowed(
        rel_str, read_only, git_scoped=git_scoped, is_directory=True
    )
    try:
        local_fs.ensure_dir(str(target_path))
    except (FileExistsError, NotADirectoryError) as exc:
        raise HTTPException(
            status_code=409, detail="A file already exists at this path"
        ) from exc
    return FileEntryResponse(
        name=target_path.name,
        path=rel_str,
        is_dir=True,
        size=0,
    )
