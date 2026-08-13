from typing import Any
from fastapi import APIRouter, Body, Depends

from app.api.deps import require_permission
from app.core.settings_store import (
    RESTART_REQUIRED_FIELDS,
    get_live_settings,
    update_settings as update_settings_store,
)
from app.core.version import get_app_version

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


@router.get("", response_model=dict)
async def get_settings_endpoint(
    current_user: dict = Depends(require_permission("settings:read")),
) -> dict:
    live = get_live_settings()
    return {
        "app_name": live.app_name,
        "version": get_app_version(),
        "debug": live.debug,
        "log_level": live.log_level,
        "rate_limit_per_minute": live.rate_limit_per_minute,
        "idempotency_ttl_hours": live.idempotency_ttl_hours,
        "circuit_breaker_max_failures": live.circuit_breaker_max_failures,
        "circuit_breaker_timeout_seconds": live.circuit_breaker_timeout_seconds,
        "event_bus_retry_attempts": live.event_bus_retry_attempts,
        "saga_timeout_seconds": live.saga_timeout_seconds,
        "requires_restart": sorted(list(RESTART_REQUIRED_FIELDS)),
    }


@router.patch("", response_model=dict)
async def update_settings(
    body: dict[str, Any] = Body(...),
    current_user: dict = Depends(require_permission("settings:write")),
) -> dict:
    live, restart_fields = update_settings_store(body)
    return {
        "success": True,
        "message": "Settings updated",
        "requires_restart": sorted(restart_fields),
        "settings": {
            "app_name": live.app_name,
            "version": get_app_version(),
            "debug": live.debug,
            "log_level": live.log_level,
            "rate_limit_per_minute": live.rate_limit_per_minute,
            "idempotency_ttl_hours": live.idempotency_ttl_hours,
            "circuit_breaker_max_failures": live.circuit_breaker_max_failures,
            "circuit_breaker_timeout_seconds": live.circuit_breaker_timeout_seconds,
            "event_bus_retry_attempts": live.event_bus_retry_attempts,
            "saga_timeout_seconds": live.saga_timeout_seconds,
        },
    }
