from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.modules.server.application.services.jar_service import (
    SOFTWARE_METADATA,
    VERSION_FETCHERS,
)

router = APIRouter(prefix="/api/v1/software", tags=["software"])

__all__ = ["router"]


@router.get("")
async def list_software(_current_user: dict = Depends(get_current_user)) -> list[dict]:
    return [
        {
            "type": key,
            "name": meta["name"],
            "description": meta["description"],
            "url": meta["url"],
            "supports_versions": meta["supports_versions"],
        }
        for key, meta in SOFTWARE_METADATA.items()
    ]


@router.get("/{software_type}/versions")
async def list_versions(
    software_type: str,
    _current_user: dict = Depends(get_current_user),
) -> list[str]:
    fetcher = VERSION_FETCHERS.get(software_type)
    if fetcher is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"Unknown software type: {software_type}")
    versions = await fetcher()
    if not versions:
        return []
    return versions
