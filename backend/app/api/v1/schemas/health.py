from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class HealthStatusResponse(BaseModel):
    server_id: str
    status: str
    previous_status: str | None = None
    contributing_factors: list[str] = Field(default_factory=list)
    trend: str = "stable"
    confidence: float = 0.0
    last_updated: datetime | None = None


class HealthTimelineEntryResponse(BaseModel):
    server_id: str
    previous_status: str | None = None
    new_status: str
    contributing_factors: list[str] = Field(default_factory=list)
    timestamp: datetime | None = None


class HealthTimelineResponse(BaseModel):
    entries: list[HealthTimelineEntryResponse]


class ServerHealthSummaryResponse(BaseModel):
    server_id: str
    status: str
    trend: str
    contributing_factors: list[str]
    last_updated: datetime | None = None


class HealthDashboardResponse(BaseModel):
    total_servers: int = 0
    healthy: int = 0
    warning: int = 0
    critical: int = 0
    broken: int = 0
    unknown: int = 0
    pending: int = 0
    servers: list[ServerHealthSummaryResponse] = Field(default_factory=list)


class IntegrityCheckResponse(BaseModel):
    check_name: str
    severity: str
    status: str
    detail: str = ""
    file_path: str | None = None


class IntegrityReportResponse(BaseModel):
    server_id: str
    overall_status: str
    scope: str = "full"
    checks: list[IntegrityCheckResponse]
    timestamp: datetime | None = None


class IntegrityAuditResponse(BaseModel):
    audits: list[IntegrityReportResponse]
