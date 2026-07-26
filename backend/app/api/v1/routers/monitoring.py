from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_command_bus, get_current_user, get_query_bus
from app.api.errors import check_command_result
from app.core.command_bus import CommandBus
from app.core.query_bus import QueryBus
from app.modules.monitoring.application import (
    CreateAlertRuleCommand,
    GetMetricsQuery,
    UpdateAlertRuleCommand,
)

router = APIRouter(prefix="/api/v1/monitoring", tags=["monitoring"])

__all__ = ["router"]


class CreateAlertRuleRequest(BaseModel):
    server_id: str
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
    current_user: dict = Depends(get_current_user),
) -> list[dict]:
    q = GetMetricsQuery(server_id=server_id, limit=limit)
    points = await query_bus.ask(q)
    return [
        {
            "tps": p.tps,
            "players": p.players,
            "ram_used_mb": p.ram_used_mb,
            "cpu_percent": p.cpu_percent,
            "timestamp": p.timestamp.isoformat() if hasattr(p.timestamp, "isoformat") else str(p.timestamp),
        }
        for p in points
    ]


@router.post("/alerts", response_model=dict, status_code=201)
async def create_alert_rule(
    body: CreateAlertRuleRequest,
    command_bus: CommandBus = Depends(get_command_bus),
    current_user: dict = Depends(get_current_user),
) -> dict:
    cmd = CreateAlertRuleCommand(
        server_id=body.server_id,
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
    current_user: dict = Depends(get_current_user),
) -> list[dict]:
    return []


@router.delete("/alerts/{alert_rule_id}", status_code=204)
async def delete_alert_rule(
    alert_rule_id: str,
    current_user: dict = Depends(get_current_user),
) -> None:
    pass
