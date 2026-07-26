from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_settings
from app.core.config import AppSettings

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


@router.get("", response_model=dict)
async def get_settings_endpoint(
    current_user: dict = Depends(get_current_user),
) -> dict:
    settings = await get_settings()
    return {
        "app_name": settings.app_name,
        "version": settings.version,
        "debug": settings.debug,
        "log_level": settings.log_level,
        "rate_limit_per_minute": settings.rate_limit_per_minute,
        "idempotency_ttl_hours": settings.idempotency_ttl_hours,
        "circuit_breaker_max_failures": settings.circuit_breaker_max_failures,
        "circuit_breaker_timeout_seconds": settings.circuit_breaker_timeout_seconds,
        "event_bus_retry_attempts": settings.event_bus_retry_attempts,
        "saga_timeout_seconds": settings.saga_timeout_seconds,
    }


@router.patch("", response_model=dict)
async def update_settings(
    current_user: dict = Depends(get_current_user),
) -> dict:
    return {"success": True, "message": "Settings updated (stub)"}
