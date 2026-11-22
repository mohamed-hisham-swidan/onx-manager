import logging
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends

from app.api.deps import require_permission
from app.api.v1.schemas.modpacks_upgrades import (
    CurseForgeIntegrationKeySetRequest,
    CurseForgeIntegrationStatusResponse,
)
from app.core.config import AppSettings, ConfigFactory
from app.core.exceptions import PasswordRequiredForExposureError
from app.core.local_auth import (
    is_loopback_bind_host,
    require_password_configured_for_exposure,
)
from app.core.persistence.db import database
from app.core.settings_store import (
    RESTART_REQUIRED_FIELDS,
    get_live_settings,
)
from app.core.settings_store import (
    update_settings as update_settings_store,
)
from app.core.version import get_app_version
from app.modules.versioning.infrastructure.panel_secret_store import (
    CURSEFORGE_API_KEY_NAME,
    delete_panel_secret,
    get_panel_secret_status,
    set_panel_secret,
)

logger = logging.getLogger(__name__)

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
        "server_startup_timeout_seconds": live.server_startup_timeout_seconds,
        "test_boot_timeout_seconds": live.test_boot_timeout_seconds,
        "requires_restart": sorted(list(RESTART_REQUIRED_FIELDS)),
    }


@router.patch("", response_model=dict)
async def update_settings(
    body: dict[str, Any] = Body(...),
    _current_user: dict = Depends(require_permission("settings:write")),
) -> dict:
    if "panel_bind_host" in body:
        new_host = str(body["panel_bind_host"]).strip()
        if not is_loopback_bind_host(new_host):
            if ConfigFactory.global_settings().deployment_profile == "local":
                if database._session_factory is None:
                    raise PasswordRequiredForExposureError(
                        details={
                            "reason": "passwordless_local_mode",
                            "action": "panel_bind_host",
                        }
                    )
                async with database.session_factory() as session:
                    await require_password_configured_for_exposure(
                        session, action="panel_bind_host"
                    )

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
        except Exception as e:
            logger.warning("Failed to update metrics batcher or scheduler interval: %s", e)

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
            "server_startup_timeout_seconds": live.server_startup_timeout_seconds,
            "test_boot_timeout_seconds": live.test_boot_timeout_seconds,
        },
    }


@router.get(
    "/integrations/curseforge",
    response_model=CurseForgeIntegrationStatusResponse,
)
async def get_curseforge_integration_status(
    _current_user: Annotated[dict, Depends(require_permission("settings:read"))],
) -> CurseForgeIntegrationStatusResponse:
    async with database.session_factory() as session:
        status = await get_panel_secret_status(
            session,
            CURSEFORGE_API_KEY_NAME,
            settings=AppSettings(),
        )
    return CurseForgeIntegrationStatusResponse(
        configured=status.configured,
        source=status.source,
        hint=status.hint,
    )


@router.put(
    "/integrations/curseforge",
    response_model=CurseForgeIntegrationStatusResponse,
)
async def set_curseforge_integration_key(
    body: CurseForgeIntegrationKeySetRequest,
    _current_user: Annotated[dict, Depends(require_permission("settings:write"))],
) -> CurseForgeIntegrationStatusResponse:
    async with database.session_factory() as session:
        status = await set_panel_secret(
            session,
            CURSEFORGE_API_KEY_NAME,
            body.api_key,
            settings=AppSettings(),
        )
    return CurseForgeIntegrationStatusResponse(
        configured=status.configured,
        source=status.source,
        hint=status.hint,
    )


@router.delete(
    "/integrations/curseforge",
    response_model=CurseForgeIntegrationStatusResponse,
)
async def delete_curseforge_integration_key(
    _current_user: Annotated[dict, Depends(require_permission("settings:write"))],
) -> CurseForgeIntegrationStatusResponse:
    async with database.session_factory() as session:
        await delete_panel_secret(session, CURSEFORGE_API_KEY_NAME)
        status = await get_panel_secret_status(
            session,
            CURSEFORGE_API_KEY_NAME,
            settings=AppSettings(),
        )
    return CurseForgeIntegrationStatusResponse(
        configured=status.configured,
        source=status.source,
        hint=status.hint,
    )
