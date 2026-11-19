from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_query_bus, require_server_permission
from app.api.v1.schemas.activity import (
    ServerActivityLogListResponse,
    ServerActivityLogResponse,
)
from app.core.query_bus import QueryBus
from app.modules.activity.application.queries import (
    GetServerActivityQuery,
    PaginatedActivityLogs,
)

router = APIRouter(prefix="/api/v1/servers/{server_id}/activity", tags=["activity"])

__all__ = ["router"]


@router.get("", response_model=ServerActivityLogListResponse)
async def get_server_activity(
    server_id: str,
    query_bus: Annotated[QueryBus, Depends(get_query_bus)],
    _current_user: Annotated[dict, Depends(require_server_permission("server.{id}.view"))],
    limit: int = Query(50, ge=1, le=200, description="Number of logs to retrieve"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    event_type: str | None = Query(None, description="Optional event type filter"),
    from_date: float | None = Query(None, description="Optional start timestamp filter"),
    to_date: float | None = Query(None, description="Optional end timestamp filter"),
    branch: str | None = Query(None, description="Optional branch name filter"),
) -> ServerActivityLogListResponse:
    res: PaginatedActivityLogs = await query_bus.ask(
        GetServerActivityQuery(
            server_id=server_id,
            limit=limit,
            offset=offset,
            event_type=event_type,
            from_date=from_date,
            to_date=to_date,
            branch_name=branch,
        )
    )
    items = [
        ServerActivityLogResponse(
            id=item.id,
            server_id=item.server_id,
            timestamp=item.timestamp,
            event_type=item.event_type,
            actor_type=item.actor_type,
            actor_id=item.actor_id,
            summary=item.summary,
            details=item.details,
            branch_name=item.branch_name,
        )
        for item in res.items
    ]
    return ServerActivityLogListResponse(
        items=items,
        total=res.total,
        limit=res.limit,
        offset=res.offset,
    )
