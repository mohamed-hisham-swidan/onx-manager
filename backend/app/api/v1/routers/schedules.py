from fastapi import APIRouter, Depends

from app.api.deps import get_current_user

router = APIRouter(prefix="/api/v1/schedules", tags=["schedules"])

__all__ = ["router"]


@router.get("", response_model=list)
async def list_schedules(
    current_user: dict = Depends(get_current_user),
) -> list:
    return []


@router.post("", response_model=dict, status_code=201)
async def create_schedule(
    current_user: dict = Depends(get_current_user),
) -> dict:
    return {"success": True, "schedule_id": "stub-schedule-id"}


@router.delete("/{schedule_id}", status_code=204)
async def delete_schedule(
    schedule_id: str,
    current_user: dict = Depends(get_current_user),
) -> None:
    pass
