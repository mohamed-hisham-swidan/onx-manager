from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AgentStatusResponse(BaseModel):
    claimed: bool
    process_status: str
    desired_agent_running: bool
    last_health_at: datetime | None = None
    claim_active: bool
    claim_expires_at: datetime | None = None


class ClaimResponse(BaseModel):
    claim_code: str
    claim_url: str
    expires_at: datetime


class PanelExposureResponse(BaseModel):
    method: str
    desired_state: str
    status: str
    public_address: str | None = None
    tls: bool = True
    protocol: str = "https"
    external_port: int | None = None
    cloudflare_tunnel_id: str | None = None
    playit_tunnel_id: str | None = None
    upnp_last_result: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    fix_hint: str | None = None
    auto_fixed: bool = False
    security_advisory: str | None = None


class PanelExposureUpdateRequest(BaseModel):
    method: str = Field(pattern="^(none|cloudflare_tunnel|playit_http|port_forward)$")
    desired_state: str = Field(pattern="^(ENABLED|DISABLED)$")
    cloudflare_token: str = Field(default="", max_length=8192)
    hostname: str = Field(default="", max_length=253)
    external_port: int | None = Field(default=None, ge=1, le=65535)


class TargetResponse(BaseModel):
    id: str | None = None
    exposure_id: str | None = None
    protocol: str
    service_type: str
    local_port: int
    public_address: str | None = None
    status: str
    error_code: str | None = None
    error_message: str | None = None


class ServerExposureResponse(BaseModel):
    server_id: str
    method: str
    desired_state: str
    aggregate_status: str
    error_code: str | None = None
    error_message: str | None = None
    targets: list[TargetResponse] = []


class ServerExposureUpdateRequest(BaseModel):
    method: str = Field(pattern="^(playit|port_forward|cloudflare_tcp)$")
    desired_state: str = Field(pattern="^(ENABLED|DISABLED)$")


class ServerExposureStateUpdateRequest(BaseModel):
    desired_state: str = Field(pattern="^(ENABLED|DISABLED)$")


class TargetCreateRequest(BaseModel):
    pass


class ReconcileRequest(BaseModel):
    scope: str = Field(default="server", pattern="^(server|all)$")


class StopAllResponse(BaseModel):
    disabled_count: int
