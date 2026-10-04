from __future__ import annotations

from typing import Any

from pydantic import Field

from app.api.v1.schemas.common import BaseResponse


class ServerActivityLogResponse(BaseResponse):
    id: str
    server_id: str
    timestamp: float
    event_type: str
    actor_type: str
    actor_id: str | None = None
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)


class ServerActivityLogListResponse(BaseResponse):
    items: list[ServerActivityLogResponse]
    total: int
    limit: int
    offset: int
