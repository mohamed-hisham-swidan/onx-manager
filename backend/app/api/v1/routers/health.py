from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_command_bus, get_current_user, get_event_bus, get_query_bus
from app.api.errors import check_command_result
from app.api.v1.schemas.health import (
    BaselineEntryResponse,
    BaselineListResponse,
    HealthDashboardResponse,
    HealthStatusResponse,
    HealthTimelineEntryResponse,
    HealthTimelineResponse,
    IntegrityAuditResponse,
    IntegrityCheckResponse,
    IntegrityReportResponse,
    OrphanCheckResponse,
    ServerHealthSummaryResponse,
)
from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.persistence.db import database
from app.core.query_bus import QueryBus
from app.modules.health.application import (
    EvaluateHealthCommand,
    GetHealthStatusQuery,
    GetHealthTimelineQuery,
)
from app.modules.health.infrastructure.integrity import FilesystemIntegrityChecker
from app.modules.health.infrastructure.repository import SQLIntegrityRepository

router = APIRouter(prefix="/api/v1/health", tags=["health"])

__all__ = ["router"]


@router.get("/status/{server_id}", response_model=HealthStatusResponse)
async def get_health_status(
    server_id: str,
    query_bus: QueryBus = Depends(get_query_bus),
    current_user: dict = Depends(get_current_user),
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
    current_user: dict = Depends(get_current_user),
) -> dict:
    result = await command_bus.send(EvaluateHealthCommand(server_id=server_id))
    return check_command_result(result)


@router.get("/timeline/{server_id}", response_model=HealthTimelineResponse)
async def get_health_timeline(
    server_id: str,
    limit: int = Query(default=100, ge=1, le=10000),
    query_bus: QueryBus = Depends(get_query_bus),
    current_user: dict = Depends(get_current_user),
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
    query_bus: QueryBus = Depends(get_query_bus),
    current_user: dict = Depends(get_current_user),
) -> HealthDashboardResponse:
    statuses = await query_bus.ask(GetHealthStatusQuery(server_id=""))

    from app.modules.health.infrastructure.repository import SQLHealthRepository
    from app.core.persistence.db import database

    async with database.session_factory() as session:
        repo = SQLHealthRepository(session)
        all_statuses = await repo.list_all()

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


@router.get("/integrity/{server_id}", response_model=IntegrityReportResponse)
async def run_integrity_check(
    server_id: str,
    scope: str = Query(default="full", pattern="^(full|quick)$"),
    event_bus: EventBus = Depends(get_event_bus),
    current_user: dict = Depends(get_current_user),
) -> IntegrityReportResponse:
    async with database.session_factory() as session:
        repo = SQLIntegrityRepository(session)
        checker = FilesystemIntegrityChecker(event_bus=event_bus, integrity_repo=repo)
        report = await checker.check(server_id, scope=scope)
        await repo.save_audit(report)
    return _report_to_response(report)


@router.get("/integrity/{server_id}/history", response_model=IntegrityAuditResponse)
async def get_integrity_history(
    server_id: str,
    limit: int = Query(default=50, ge=1, le=1000),
    current_user: dict = Depends(get_current_user),
) -> IntegrityAuditResponse:
    async with database.session_factory() as session:
        repo = SQLIntegrityRepository(session)
        audits = await repo.list_audits(server_id, limit=limit)
    return IntegrityAuditResponse(
        audits=[_report_to_response(r) for r in audits],
    )


@router.post("/integrity/{server_id}/baseline", response_model=IntegrityReportResponse)
async def capture_baseline(
    server_id: str,
    current_user: dict = Depends(get_current_user),
) -> IntegrityReportResponse:
    async with database.session_factory() as session:
        repo = SQLIntegrityRepository(session)
        checker = FilesystemIntegrityChecker(integrity_repo=repo)
        report = await checker.capture_baseline(server_id)
    return _report_to_response(report)


@router.get("/integrity/{server_id}/baseline", response_model=BaselineListResponse)
async def list_baselines(
    server_id: str,
    current_user: dict = Depends(get_current_user),
) -> BaselineListResponse:
    async with database.session_factory() as session:
        repo = SQLIntegrityRepository(session)
        entries = await repo.get_baselines(server_id)
    return BaselineListResponse(entries=[BaselineEntryResponse(**e) for e in entries])


def _report_to_response(report: object) -> IntegrityReportResponse:
    from app.modules.health.domain.value_objects import IntegrityReport
    r: IntegrityReport = report
    return IntegrityReportResponse(
        server_id=r.server_id,
        overall_status=r.overall_status,
        scope=r.scope,
        checks=[
            IntegrityCheckResponse(
                check_name=c.check_name,
                severity=c.severity,
                status=c.status,
                detail=c.detail,
                file_path=c.file_path,
            )
            for c in r.checks
        ],
        timestamp=r.timestamp,
    )
