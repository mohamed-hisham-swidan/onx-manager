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
    dashboard_url: str | None = None
    setup_instructions: str | None = None


class ServerExposureResponse(BaseModel):
    server_id: str
    method: str
    desired_state: str
    aggregate_status: str
    error_code: str | None = None
    error_message: str | None = None
    cloudflare_tunnel_id: str | None = None
    has_cloudflare_credentials: bool = False
    targets: list[TargetResponse] = []


class ServerExposureUpdateRequest(BaseModel):
    method: str = Field(pattern="^(playit|port_forward|cloudflare_tcp)$")
    desired_state: str = Field(pattern="^(ENABLED|DISABLED)$")
    cloudflare_token: str = Field(default="", max_length=8192)
    hostname: str = Field(default="", max_length=253)
    acknowledged_warning: bool = Field(default=False)


class ServerExposureStateUpdateRequest(BaseModel):
    desired_state: str = Field(pattern="^(ENABLED|DISABLED)$")
    cloudflare_token: str = Field(default="", max_length=8192)
    hostname: str = Field(default="", max_length=253)
    acknowledged_warning: bool = Field(default=False)


class TargetCreateRequest(BaseModel):
    service_type: str = Field(default="java", pattern="^(java|bedrock|voice|bluemap)$")
    protocol: str | None = Field(default=None, pattern="^(tcp|udp)$")
    local_port: int | None = Field(default=None, ge=1, le=65535)
    public_address: str | None = Field(default=None, max_length=512)


class TargetUpdateRequest(BaseModel):
    public_address: str | None = Field(default=None, max_length=512)


class RegisteredPortCreateRequest(BaseModel):
    service_type: str = Field(pattern="^(bedrock|voice|bluemap)$")
    protocol: str = Field(pattern="^(tcp|udp)$")
    port: int = Field(ge=1, le=65535)
    name: str | None = Field(default=None, max_length=64)


class RegisteredPortResponse(BaseModel):
    id: str
    server_id: str
    service_type: str
    protocol: str
    port: int
    name: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ReconcileRequest(BaseModel):
    scope: str = Field(default="server", pattern="^(server|all)$")


class StopAllResponse(BaseModel):
    disabled_count: int
