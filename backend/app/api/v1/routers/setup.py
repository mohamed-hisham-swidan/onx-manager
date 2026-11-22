from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator

from app.api.deps import get_command_bus, get_query_bus, require_owner
from app.api.errors import check_command_result
from app.core.command_bus import CommandBus
from app.core.config import ConfigFactory
from app.core.local_auth import compute_auth_mode
from app.core.query_bus import QueryBus
from app.core.version import get_app_version
from app.modules.auth.application import (
    BootstrapInstanceCommand,
    ConfigureCredentialsCommand,
    GetSystemStatusQuery,
    UpdateAccessModeCommand,
)

router = APIRouter(prefix="/api/v1/setup", tags=["setup"])


class SystemStatusResponse(BaseModel):
    initialized: bool
    access_mode: str
    user_count: int
    version: str = get_app_version()
    advanced_mode_enabled: bool = False
    deployment_profile: Literal["local", "vps"] = "vps"
    password_configured: bool = False
    auth_mode: Literal["local_zero_login", "jwt"] = "jwt"


class BootstrapRequest(BaseModel):
    username: str | None = None
    email: str | None = None
    password: str = Field(min_length=8)
    display_name: str | None = None
    access_mode: str = Field(default="LOCAL", description="LOCAL or GLOBAL")

    @model_validator(mode="after")
    def validate_identifier(self) -> BootstrapRequest:
        if not (self.username or self.email or "").strip():
            raise ValueError("username is required")
        return self


class ConfigureCredentialsRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8)
    display_name: str | None = Field(default=None, max_length=128)
    email: str | None = None


class UpdateAccessModeRequest(BaseModel):
    access_mode: str = Field(description="LOCAL or GLOBAL")


class BootstrapResponse(BaseModel):
    success: bool = True
    message: str
    user_id: str
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 900


def _enrich_system_status(data: dict) -> SystemStatusResponse:
    live_settings = ConfigFactory.global_settings()
    data["advanced_mode_enabled"] = live_settings.advanced_mode_enabled
    data["deployment_profile"] = live_settings.deployment_profile
    password_configured = bool(
        data.get("password_configured", bool(data.get("initialized", False)))
    )
    data["password_configured"] = password_configured
    data["auth_mode"] = compute_auth_mode(password_configured, live_settings)
    return SystemStatusResponse(**data)


@router.get("/status", response_model=SystemStatusResponse)
async def get_setup_status(
    query_bus: QueryBus = Depends(get_query_bus),  # noqa: B008
) -> SystemStatusResponse:
    data = dict(await query_bus.ask(GetSystemStatusQuery()))
    return _enrich_system_status(data)


@router.post("/bootstrap", response_model=BootstrapResponse, status_code=201)
async def bootstrap_instance(
    body: BootstrapRequest,
    command_bus: CommandBus = Depends(get_command_bus),  # noqa: B008
) -> BootstrapResponse:
    result = await command_bus.send(
        BootstrapInstanceCommand(
            username=body.username,
            email=body.email,
            password=body.password,
            display_name=body.display_name,
            access_mode=body.access_mode,
        )
    )
    data = check_command_result(result)
    return BootstrapResponse(**data)


@router.post("/credentials", response_model=BootstrapResponse)
async def configure_credentials(
    body: ConfigureCredentialsRequest,
    current_user: dict = Depends(require_owner()),  # noqa: B008
    command_bus: CommandBus = Depends(get_command_bus),  # noqa: B008
) -> BootstrapResponse:
    result = await command_bus.send(
        ConfigureCredentialsCommand(
            actor_user_id=current_user.get("user_id", ""),
            username=body.username,
            password=body.password,
            display_name=body.display_name,
            email=body.email,
        )
    )
    data = check_command_result(result)
    return BootstrapResponse(**data)


@router.put("/access-mode", response_model=SystemStatusResponse)
async def update_access_mode(
    body: UpdateAccessModeRequest,
    current_user: dict = Depends(require_owner()),  # noqa: B008
    command_bus: CommandBus = Depends(get_command_bus),  # noqa: B008
) -> SystemStatusResponse:
    result = await command_bus.send(
        UpdateAccessModeCommand(
            access_mode=body.access_mode,
            requester_roles=current_user.get("roles", []),
            requester_permissions=current_user.get("permissions", []),
        )
    )
    data = dict(check_command_result(result))
    return _enrich_system_status(data)
