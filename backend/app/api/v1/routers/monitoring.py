from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_command_bus,
    get_current_user,
    get_db,
    get_query_bus,
    require_permission,
    require_server_permission,
)
from app.api.errors import check_command_result
from app.core.command_bus import CommandBus
from app.core.query_bus import QueryBus
from app.core.timeutil import format_datetime_utc, normalize_iso_timestamp
from app.modules.monitoring.application import (
    CreateAlertRuleCommand,
    GetMetricsQuery,
)
from app.modules.monitoring.infrastructure.repository import SQLAlertRuleRepository
from app.modules.shared.value_objects import ServerId

router = APIRouter(prefix="/api/v1/monitoring", tags=["monitoring"])

__all__ = ["router"]


class CreateAlertRuleRequest(BaseModel):
    metric_name: str
    condition: str = "gt"
    threshold: float
    severity: str = "warning"
    cooldown_minutes: int = Field(default=15, ge=1)


@router.get("/metrics", response_model=list[dict])
async def get_metrics(
    server_id: str = Query(...),
    limit: int = Query(default=100, ge=1, le=10000),
    query_bus: QueryBus = Depends(get_query_bus),
    _current_user: dict = Depends(require_server_permission("server.{id}.view")),
) -> list[dict]:
    q = GetMetricsQuery(server_id=server_id, limit=limit)
    points = await query_bus.ask(q)
    return [
        {
            "tps": p.tps,
            "players": p.players,
            "ram_used_mb": p.ram_used_mb,
            "cpu_percent": p.cpu_percent,
            "timestamp": format_datetime_utc(p.timestamp)
            if isinstance(p.timestamp, datetime)
            else (
                normalize_iso_timestamp(p.timestamp.isoformat())
                if hasattr(p.timestamp, "isoformat")
                else normalize_iso_timestamp(str(p.timestamp))
            ),
        }
        for p in points
    ]


@router.post("/alerts/{server_id}", response_model=dict, status_code=201)
async def create_alert_rule(
    server_id: str,
    body: CreateAlertRuleRequest,
    command_bus: CommandBus = Depends(get_command_bus),
    _current_user: dict = Depends(require_server_permission("server.{id}.settings")),
) -> dict:
    cmd = CreateAlertRuleCommand(
        server_id=server_id,
        metric_name=body.metric_name,
        condition=body.condition,
        threshold=body.threshold,
        severity=body.severity,
        cooldown_minutes=body.cooldown_minutes,
    )
    result = await command_bus.send(cmd)
    return check_command_result(result)


@router.get("/alerts", response_model=list[dict])
async def list_alerts(
    server_id: str | None = None,
    session: AsyncSession = Depends(get_db),
    _current_user: dict = Depends(get_current_user),
) -> list[dict]:
    repo = SQLAlertRuleRepository(session)
    if server_id:
        rules = await repo.list_by_server(ServerId(server_id))
    else:
        rules = await repo.list_all()
    return [
        {
            "id": r._alert_rule_id,
            "server_id": str(r.server_id),
            "metric_name": r.metric_name,
            "condition": r.condition.value,
            "threshold": r.threshold,
            "severity": r.severity.value,
            "enabled": r.enabled,
            "cooldown_minutes": r.cooldown_minutes,
            "last_triggered_at": format_datetime_utc(r.last_triggered_at)
            if r.last_triggered_at
            else None,
        }
        for r in rules
    ]


@router.delete("/alerts/{alert_rule_id}", status_code=204)
async def delete_alert_rule(
    alert_rule_id: str,
    session: AsyncSession = Depends(get_db),
    _current_user: dict = Depends(require_permission("global.settings")),
) -> None:
    repo = SQLAlertRuleRepository(session)
    await repo.delete(alert_rule_id)
    await session.commit()
