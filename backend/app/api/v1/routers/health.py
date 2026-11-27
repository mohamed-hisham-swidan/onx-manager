from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    get_command_bus,
    get_current_user,
    get_query_bus,
    require_server_permission,
)
from app.api.errors import check_command_result
from app.api.v1.schemas.health import (
    HealthDashboardResponse,
    HealthStatusResponse,
    HealthTimelineEntryResponse,
    HealthTimelineResponse,
    ServerHealthSummaryResponse,
)
from app.core.authorization import accessible_server_ids_for_user
from app.core.command_bus import CommandBus
from app.core.query_bus import QueryBus
from app.modules.health.application import (
    EvaluateHealthCommand,
    GetHealthStatusQuery,
    GetHealthTimelineQuery,
)

router = APIRouter(prefix="/api/v1/health", tags=["health"])

__all__ = ["router"]


@router.get("/status/{server_id}", response_model=HealthStatusResponse)
async def get_health_status(
    server_id: str,
    query_bus: QueryBus = Depends(get_query_bus),
    _current_user: dict = Depends(require_server_permission("server.{id}.view")),
) -> HealthStatusResponse:
    result = await query_bus.ask(GetHealthStatusQuery(server_id=server_id))
    if result is None:
        return HealthStatusResponse(server_id=server_id, status="unknown")
    return HealthStatusResponse(
        server_id=result.server_id,
        status=result.status,
        previous_status=result.previous_status,
        contributing_factors=result.contributing_factors,
        trend=result.trend,
        confidence=result.confidence,
        last_updated=result.last_updated,
    )


@router.post("/evaluate/{server_id}", response_model=dict)
async def evaluate_health(
    server_id: str,
    command_bus: CommandBus = Depends(get_command_bus),
    _current_user: dict = Depends(require_server_permission("server.{id}.view")),
) -> dict:
    result = await command_bus.send(EvaluateHealthCommand(server_id=server_id))
    return check_command_result(result)


@router.get("/timeline/{server_id}", response_model=HealthTimelineResponse)
async def get_health_timeline(
    server_id: str,
    limit: int = Query(default=100, ge=1, le=10000),
    query_bus: QueryBus = Depends(get_query_bus),
    _current_user: dict = Depends(require_server_permission("server.{id}.view")),
) -> HealthTimelineResponse:
    entries = await query_bus.ask(GetHealthTimelineQuery(server_id=server_id, limit=limit))
    return HealthTimelineResponse(
        entries=[
            HealthTimelineEntryResponse(
                server_id=e.server_id,
                previous_status=e.previous_status,
                new_status=e.new_status,
                contributing_factors=e.contributing_factors,
                timestamp=e.timestamp,
            )
            for e in entries
        ],
    )


@router.get("/dashboard", response_model=HealthDashboardResponse)
async def get_health_dashboard(
    current_user: dict = Depends(get_current_user),
) -> HealthDashboardResponse:
    from app.core.persistence.db import database
    from app.modules.health.infrastructure.repository import SQLHealthRepository

    allowed = accessible_server_ids_for_user(current_user)
    async with database.session_factory() as session:
        repo = SQLHealthRepository(session)
        all_statuses = await repo.list_active()

    if allowed is not None:
        all_statuses = [s for s in all_statuses if str(s.server_id) in allowed]

    counts: dict[str, int] = {
        "healthy": 0,
        "warning": 0,
        "critical": 0,
        "broken": 0,
        "unknown": 0,
        "pending": 0,
    }
    servers: list[ServerHealthSummaryResponse] = []
    for s in all_statuses:
        key = s.classification.value
        if key in counts:
            counts[key] += 1
        servers.append(
            ServerHealthSummaryResponse(
                server_id=s.server_id,
                status=s.classification.value,
                trend=s.trend.value,
                contributing_factors=s.contributing_factors,
                last_updated=s.last_updated,
            ),
        )

    return HealthDashboardResponse(
        total_servers=len(all_statuses),
        healthy=counts["healthy"],
        warning=counts["warning"],
        critical=counts["critical"],
        broken=counts["broken"],
        unknown=counts["unknown"],
        pending=counts["pending"],
        servers=servers,
    )
