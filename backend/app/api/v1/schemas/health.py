from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.api.v1.schemas.common import BaseResponse


class HealthStatusResponse(BaseResponse):
    server_id: str
    status: str
    previous_status: str | None = None
    contributing_factors: list[str] = Field(default_factory=list)
    trend: str = "stable"
    confidence: float = 0.0
    last_updated: datetime | None = None


class HealthTimelineEntryResponse(BaseResponse):
    server_id: str
    previous_status: str | None = None
    new_status: str
    contributing_factors: list[str] = Field(default_factory=list)
    timestamp: datetime | None = None


class HealthTimelineResponse(BaseResponse):
    entries: list[HealthTimelineEntryResponse]


class ServerHealthSummaryResponse(BaseResponse):
    server_id: str
    status: str
    trend: str
    contributing_factors: list[str]
    last_updated: datetime | None = None


class HealthDashboardResponse(BaseResponse):
    total_servers: int = 0
    healthy: int = 0
    warning: int = 0
    critical: int = 0
    broken: int = 0
    unknown: int = 0
    pending: int = 0
    servers: list[ServerHealthSummaryResponse] = Field(default_factory=list)
