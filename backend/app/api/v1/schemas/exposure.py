from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.api.v1.schemas.common import BaseResponse


class AgentStatusResponse(BaseResponse):
    claimed: bool
    process_status: str
    desired_agent_running: bool
    last_health_at: datetime | None = None
    claim_active: bool
    claim_expires_at: datetime | None = None


class ClaimResponse(BaseResponse):
    claim_code: str
    claim_url: str
    expires_at: datetime


class PanelExposureResponse(BaseResponse):
    method: str
    desired_state: str
    status: str
    public_address: str | None = None
    tls: bool = True
    protocol: str = "https"
    external_port: int | None = None
    cloudflare_tunnel_id: str | None = None
    cloudflare_mode: Literal["token", "quick"] | None = None
    token_configured: bool = False
    ephemeral: bool = False
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
    cloudflare_mode: Literal["token", "quick"] | None = None
    cloudflare_token: str = Field(default="", max_length=8192)
    hostname: str = Field(default="", max_length=253)
    external_port: int | None = Field(default=None, ge=1, le=65535)

    @field_validator("external_port", mode="before")
    @classmethod
    def _validate_external_port_strict(cls, value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, (bool, float)):
            raise ValueError("External port must be an integer between 1 and 65535.")
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped.isdigit():
                raise ValueError("External port must contain digits only between 1 and 65535.")
            port = int(stripped)
        elif isinstance(value, int):
            port = value
        else:
            raise ValueError("External port must be an integer between 1 and 65535.")
        if port < 1 or port > 65535:
            raise ValueError("External port must be between 1 and 65535.")
        return port


class TargetResponse(BaseResponse):
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


class ReachabilityProbeResult(BaseModel):
    reachable: bool
    target_address: str
    latency_ms: int | None = None
    version_name: str | None = None
    protocol_version: int | None = None
    players_online: int | None = None
    players_max: int | None = None
    motd: str | None = None
    error: str | None = None


class ServerExposureResponse(BaseResponse):
    server_id: str
    branch_name: str = "main"
    branch_runtime_status: str | None = None
    allocated_game_port: int | None = None
    allocated_port_set: dict[str, Any] | None = None
    method: str
    desired_state: str
    aggregate_status: str
    error_code: str | None = None
    error_message: str | None = None
    cloudflare_tunnel_id: str | None = None
    has_cloudflare_credentials: bool = False
    cloudflare_mode: str | None = None
    subdomain_prefix: str | None = None
    base_domain: str | None = None
    srv_record_enabled: bool = False
    srv_record_hint: str | None = None
    ephemeral: bool = False
    upnp_status: str | None = None
    detected_wan_ip: str | None = None
    targets: list[TargetResponse] = []
    reachability: ReachabilityProbeResult | None = None


class ServerExposureUpdateRequest(BaseModel):
    method: str = Field(pattern="^(none|host_port|playit|port_forward|cloudflare_tcp)$")
    desired_state: str = Field(pattern="^(ENABLED|DISABLED)$")
    cloudflare_mode: Literal["quick", "subdomain", "tcp"] | None = None
    cloudflare_token: str = Field(default="", max_length=8192)
    hostname: str = Field(default="", max_length=253)
    subdomain_prefix: str | None = Field(default=None, max_length=63)
    base_domain: str | None = Field(default=None, max_length=253)
    srv_record_enabled: bool = False
    external_port: int | None = Field(default=None, ge=1, le=65535)
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


class RegisteredPortResponse(BaseResponse):
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


class StopAllResponse(BaseResponse):
    disabled_count: int
