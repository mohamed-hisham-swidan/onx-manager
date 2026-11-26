from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.api.deps import require_permission
from app.api.v1.schemas.plugin import (
    PluginFileResponse,
    PluginProjectResponse,
    PluginSearchResultResponse,
    PluginSearchResultsResponse,
    PluginVersionResponse,
    PluginVersionsResponse,
)
from app.core.exceptions import (
    DownloadError,
    NotFoundError,
    RateLimitExceeded,
    ValidationError,
)
from app.modules.plugin.infrastructure.providers import build_plugin_catalog_provider
from app.modules.plugin.infrastructure.providers.base import PluginVersionInfo

router = APIRouter(prefix="/api/v1/marketplace", tags=["marketplace"])

__all__ = ["router"]


def _translate_download_error(exc: DownloadError, *, not_found_msg: str) -> None:
    if exc.status == 404:
        raise NotFoundError(not_found_msg) from exc
    if exc.status == 400:
        raise ValidationError(str(exc)) from exc
    if exc.status == 429:
        retry_after = exc.details.get("retry_after") or exc.details.get("ratelimit_reset") or 60
        raise RateLimitExceeded(
            message="Upstream marketplace rate limit exceeded",
            details={"retry_after": retry_after},
        ) from exc
    raise exc


@router.get("/search", response_model=PluginSearchResultsResponse)
async def search_marketplace(
    query: str = Query(default="", max_length=100),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    project_type: str = Query(default="plugin"),
    loader: str = Query(default="", max_length=50),
    sort: Literal["relevance", "downloads", "follows", "newest", "updated"] = Query(
        default="relevance"
    ),
    game_version: str | None = Query(default=None, max_length=32),
    _current_user: dict = Depends(require_permission("plugin:manage")),
) -> PluginSearchResultsResponse:
    provider = build_plugin_catalog_provider()
    cleaned_gv = game_version.strip() if game_version and game_version.strip() else None
    try:
        page = await provider.search(
            query,
            limit=limit,
            offset=offset,
            project_type=project_type,
            loader=loader or None,
            sort=sort,
            game_version=cleaned_gv,
        )
    except DownloadError as e:
        _translate_download_error(e, not_found_msg="Marketplace search failed")
    return PluginSearchResultsResponse(
        items=[PluginSearchResultResponse(**r.__dict__) for r in page.items],
        total_hits=page.total_hits,
        offset=offset,
        limit=limit,
    )


@router.get("/projects/{project_id}", response_model=PluginProjectResponse)
async def get_marketplace_project(
    project_id: str,
    _current_user: dict = Depends(require_permission("plugin:manage")),
) -> PluginProjectResponse:
    provider = build_plugin_catalog_provider()
    try:
        project = await provider.get_project(project_id)
    except DownloadError as e:
        _translate_download_error(
            e, not_found_msg=f"Marketplace project '{project_id}' not found"
        )
    return PluginProjectResponse(**project.__dict__)


def _to_version_response(v: PluginVersionInfo) -> PluginVersionResponse:
    return PluginVersionResponse(
        version_id=v.version_id,
        project_id=v.project_id,
        name=v.name,
        version_number=v.version_number,
        game_versions=v.game_versions,
        loaders=v.loaders,
        files=[PluginFileResponse(**f.__dict__) for f in v.files],
        dependencies=v.dependencies,
        required_dependencies=list(getattr(v, "required_dependencies", []) or []),
        changelog=getattr(v, "changelog", None),
        date_published=v.date_published,
        version_type=getattr(v, "version_type", "release") or "release",
    )


@router.get("/projects/{project_id}/versions", response_model=PluginVersionsResponse)
async def get_marketplace_project_versions(
    project_id: str,
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    _current_user: dict = Depends(require_permission("plugin:manage")),
) -> PluginVersionsResponse:
    provider = build_plugin_catalog_provider()
    try:
        page = await provider.get_project_versions(project_id, limit=limit, offset=offset)
    except DownloadError as e:
        _translate_download_error(
            e, not_found_msg=f"Marketplace project '{project_id}' not found"
        )
    return PluginVersionsResponse(
        project_id=project_id,
        versions=[_to_version_response(v) for v in page.items],
        selected=None,  # no server context — always null (D1/D6)
        notice="",  # B2 — NOT None: strict str at plugin.py:83
        notice_kind="",  # B2 — NOT None: strict str at plugin.py:84
        total=page.total,
    )
