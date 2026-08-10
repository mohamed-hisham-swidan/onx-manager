from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import get_current_user, get_query_bus, require_permission
from app.api.v1.schemas.files import (
    FileContentResponse,
    FileEntryResponse,
    WriteFileContentRequest,
)
from app.core.query_bus import QueryBus
from app.modules.server.application.queries.get_server import GetServerQuery
from app.modules.server.infrastructure.fs import local_fs

router = APIRouter(prefix="/api/v1/servers/{server_id}/files", tags=["files"])

__all__ = ["router"]


async def _resolve_server_file_path(
    server_id: str,
    relative_path: str,
    query_bus: QueryBus,
    must_exist: bool = False,
) -> tuple[Path, Path, str]:

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

    resolved_root = Path(root_path).resolve()
    clean_rel = relative_path.lstrip("/") if relative_path else ""
    target_path = (resolved_root / clean_rel).resolve()

    try:
        target_path.relative_to(resolved_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Path escapes server root directory")

    if must_exist and not target_path.exists():
        raise HTTPException(status_code=404, detail="Path does not exist")

    rel_str = str(target_path.relative_to(resolved_root))
    if rel_str == ".":
        rel_str = ""

    return resolved_root, target_path, rel_str


@router.get("", response_model=list[FileEntryResponse])
async def list_files(
    server_id: str,
    path: str = Query(default=""),
    query_bus: QueryBus = Depends(get_query_bus),
    current_user: dict = Depends(get_current_user),
) -> list[FileEntryResponse]:
    resolved_root, target_path, _ = await _resolve_server_file_path(
        server_id, path, query_bus, must_exist=True
    )
    if not target_path.is_dir():
        raise HTTPException(status_code=400, detail="Target path is a file, not a directory")

    entries = local_fs.list_dir(str(target_path))
    results: list[FileEntryResponse] = []
    for item in entries:
        try:
            item_rel = str(item.resolve().relative_to(resolved_root))
        except ValueError:
            # Skip if symlink points outside
            continue
        is_directory = item.is_dir()
        file_size = item.stat().st_size if not is_directory else 0
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
    query_bus: QueryBus = Depends(get_query_bus),
    current_user: dict = Depends(get_current_user),
) -> FileContentResponse:
    _, target_path, rel_str = await _resolve_server_file_path(
        server_id, path, query_bus, must_exist=True
    )
    if target_path.is_dir():
        raise HTTPException(status_code=400, detail="Target path is a directory, not a file")

    content = local_fs.read_text(str(target_path))
    return FileContentResponse(path=rel_str, content=content)


@router.put("/content", response_model=FileContentResponse)
async def write_file_content(
    server_id: str,
    body: WriteFileContentRequest,
    path: str = Query(...),
    query_bus: QueryBus = Depends(get_query_bus),
    current_user: dict = Depends(require_permission("server:write")),
) -> FileContentResponse:
    _, target_path, rel_str = await _resolve_server_file_path(
        server_id, path, query_bus, must_exist=False
    )
    if target_path.exists() and target_path.is_dir():
        raise HTTPException(status_code=400, detail="Target path is a directory, not a file")

    # Use write_binary_atomic to prevent partial file writes on failure
    local_fs.write_binary_atomic(str(target_path), body.content.encode("utf-8"))
    return FileContentResponse(path=rel_str, content=body.content)


@router.delete("", status_code=204)
async def delete_file_or_dir(
    server_id: str,
    path: str = Query(...),
    query_bus: QueryBus = Depends(get_query_bus),
    current_user: dict = Depends(require_permission("server:delete")),
) -> None:
    resolved_root, target_path, _ = await _resolve_server_file_path(
        server_id, path, query_bus, must_exist=True
    )
    if target_path == resolved_root:
        raise HTTPException(status_code=400, detail="Cannot delete server root directory")

    if target_path.is_dir():
        local_fs.delete_dir(str(target_path))
    else:
        local_fs.delete(str(target_path))


@router.post("/upload", response_model=FileEntryResponse, status_code=201)
async def upload_file(
    server_id: str,
    path: str = Query(default=""),
    file: UploadFile = File(...),
    query_bus: QueryBus = Depends(get_query_bus),
    current_user: dict = Depends(require_permission("server:write")),
) -> FileEntryResponse:
    filename = file.filename or "uploaded_file"
    # Clean filename of any path components
    filename = Path(filename).name

    dest_rel_path = f"{path.strip('/')}/{filename}" if path.strip('/') else filename
    resolved_root, target_file_path, rel_str = await _resolve_server_file_path(
        server_id, dest_rel_path, query_bus, must_exist=False
    )

    contents = await file.read()
    local_fs.write_binary_atomic(str(target_file_path), contents)

    return FileEntryResponse(
        name=target_file_path.name,
        path=rel_str,
        is_dir=False,
        size=len(contents),
    )


@router.get("/download")
async def download_file(
    server_id: str,
    path: str = Query(...),
    query_bus: QueryBus = Depends(get_query_bus),
    current_user: dict = Depends(get_current_user),
) -> FileResponse:
    _, target_path, _ = await _resolve_server_file_path(
        server_id, path, query_bus, must_exist=True
    )
    if target_path.is_dir():
        raise HTTPException(status_code=400, detail="Target path is a directory, not a file")

    return FileResponse(
        path=str(target_path),
        filename=target_path.name,
        media_type="application/octet-stream",
    )


@router.post("/mkdir", response_model=FileEntryResponse, status_code=201)
async def create_directory(
    server_id: str,
    path: str = Query(...),
    query_bus: QueryBus = Depends(get_query_bus),
    current_user: dict = Depends(require_permission("server:write")),
) -> FileEntryResponse:
    _, target_path, rel_str = await _resolve_server_file_path(
        server_id, path, query_bus, must_exist=False
    )
    local_fs.ensure_dir(str(target_path))
    return FileEntryResponse(
        name=target_path.name,
        path=rel_str,
        is_dir=True,
        size=0,
    )
