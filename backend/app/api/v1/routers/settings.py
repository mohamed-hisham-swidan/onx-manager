from typing import Any

from fastapi import APIRouter, Body, Depends

from app.api.deps import require_permission
from app.core.settings_store import (
    RESTART_REQUIRED_FIELDS,
    get_live_settings,
)
from app.core.settings_store import (
    update_settings as update_settings_store,
)
from app.core.version import get_app_version

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


@router.get("", response_model=dict)
async def get_settings_endpoint(
    _current_user: dict = Depends(require_permission("settings:read")),
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
        "panel_bind_host": live.panel_bind_host,
        "metrics_interval_seconds": live.metrics_interval_seconds,
        "requires_restart": sorted(list(RESTART_REQUIRED_FIELDS)),
    }


@router.patch("", response_model=dict)
async def update_settings(
    body: dict[str, Any] = Body(...),
    _current_user: dict = Depends(require_permission("settings:write")),
) -> dict:
    live, restart_fields = update_settings_store(body)

    # If metrics collection interval was updated, dynamically reload the scheduler & batcher
    if "metrics_interval_seconds" in body:
        try:
            from app.websocket.endpoint import get_metrics_batcher

            batcher = get_metrics_batcher()
            if batcher:
                batcher.set_window_seconds(live.metrics_interval_seconds)

            from app.tasks.scheduler import get_scheduler

            scheduler = get_scheduler()
            if scheduler:
                await scheduler.update_job_expression(
                    "metrics_collect",
                    f"interval:{live.metrics_interval_seconds}s",
                )
        except Exception:
            pass

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
            "panel_bind_host": live.panel_bind_host,
            "metrics_interval_seconds": live.metrics_interval_seconds,
        },
    }
