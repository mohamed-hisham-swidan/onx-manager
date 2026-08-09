from fastapi import APIRouter, Depends, Query

from app.api.deps import require_permission
from app.api.v1.schemas.plugin import PluginSearchResultResponse
from app.modules.plugin.infrastructure.providers import build_plugin_catalog_provider

router = APIRouter(prefix="/api/v1/marketplace", tags=["marketplace"])

__all__ = ["router"]


@router.get("/search", response_model=list[PluginSearchResultResponse])
async def search_marketplace(
    query: str = Query(default="", max_length=100),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    project_type: str = Query(default="plugin"),
    current_user: dict = Depends(require_permission("plugin:manage")),
) -> list[PluginSearchResultResponse]:
    provider = build_plugin_catalog_provider()
    results = await provider.search(query, limit=limit, offset=offset, project_type=project_type)
    return [PluginSearchResultResponse(**r.__dict__) for r in results]
