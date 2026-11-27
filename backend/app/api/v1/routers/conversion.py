"""Server mode conversion API routes (Simple <-> Advanced)."""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.api.deps import require_versioning_permission
from app.api.v1.schemas.conversion import (
    ConvertToAdvancedRequest,
    ConvertToAdvancedResponse,
    ConvertToSimpleRequest,
    ConvertToSimpleResponse,
)
from app.core.host_state import ensure_host_state_layout
from app.modules.backup.application.services.conversion_service import (
    ConversionError,
    ConversionService,
)

router = APIRouter(prefix="/api/v1/servers", tags=["conversion"])

__all__ = ["router"]


def _build_conversion_service() -> ConversionService:
    layout = ensure_host_state_layout()
    return ConversionService(layout)


@router.post(
    "/{server_id}/convert/to-advanced",
    response_model=ConvertToAdvancedResponse,
    status_code=status.HTTP_200_OK,
)
async def convert_to_advanced(
    server_id: Annotated[str, Path(description="Server ID")],
    _current_user: Annotated[
        dict[str, Any], Depends(require_versioning_permission("server.versioning.manage"))
    ],
    conversion: Annotated[ConversionService, Depends(_build_conversion_service)],
    _body: ConvertToAdvancedRequest | None = None,
) -> ConvertToAdvancedResponse:
    actor_id = _current_user.get("user_id")
    try:
        result = await conversion.convert_simple_to_advanced(
            server_id, actor_id=actor_id, actor_type="user"
        )
    except ConversionError as exc:
        raise HTTPException(
            status_code=exc.http_status,
            detail={"error": exc.message, "error_code": exc.code},
        ) from exc
    return ConvertToAdvancedResponse(
        server_id=result.server_id,
        mode=result.to_mode,
        main_commit_sha=result.details.get("main_commit_sha", "") if result.details else "",
        backup_id=result.backup_id,
        class_c_snapshot_id=result.class_c_snapshot_id,
        lockfile_path=str(result.details["lockfile_path"]) if result.details else "",
        files_count=result.details.get("files_count", 0) if result.details else 0,
        cas_ingested=result.details.get("cas_ingested", 0) if result.details else 0,
        worktree_path=(
            str(result.details["worktree_path"])
            if result.details and result.details.get("worktree_path")
            else None
        ),
    )


@router.post(
    "/{server_id}/convert/to-simple",
    response_model=ConvertToSimpleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def convert_to_simple(
    server_id: Annotated[str, Path(description="Server ID")],
    _current_user: Annotated[
        dict[str, Any], Depends(require_versioning_permission("server.versioning.manage"))
    ],
    conversion: Annotated[ConversionService, Depends(_build_conversion_service)],
    body: ConvertToSimpleRequest | None = None,
) -> ConvertToSimpleResponse:
    actor_id = _current_user.get("user_id")
    name = body.name if body is not None else None
    port = body.port if body is not None else None
    try:
        result = await conversion.convert_advanced_to_simple(
            server_id,
            new_name=name,
            new_port=port,
            actor_id=actor_id,
            actor_type="user",
        )
    except ConversionError as exc:
        raise HTTPException(
            status_code=exc.http_status,
            detail={"error": exc.message, "error_code": exc.code},
        ) from exc
    return ConvertToSimpleResponse(
        source_server_id=result.server_id,
        new_server_id=cast(str, result.new_server_id),
        name=result.details.get("name", "") if result.details else "",
        mode=result.to_mode,
        root_path=result.details.get("root_path", "") if result.details else "",
        lockfile_path=(
            str(result.details["lockfile_path"])
            if result.details and result.details.get("lockfile_path")
            else ""
        ),
        files_count=result.details.get("files_count", 0) if result.details else 0,
    )
