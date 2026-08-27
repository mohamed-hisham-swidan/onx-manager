from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import get_command_bus, get_query_bus, require_owner
from app.api.errors import check_command_result
from app.core.command_bus import CommandBus
from app.core.query_bus import QueryBus
from app.core.version import get_app_version
from app.modules.auth.application import (
    BootstrapInstanceCommand,
    GetSystemStatusQuery,
    UpdateAccessModeCommand,
)

router = APIRouter(prefix="/api/v1/setup", tags=["setup"])


class SystemStatusResponse(BaseModel):
    initialized: bool
    access_mode: str
    user_count: int
    version: str = get_app_version()


class BootstrapRequest(BaseModel):
    email: str
    password: str = Field(min_length=8)
    display_name: str
    access_mode: str = Field(default="LOCAL", description="LOCAL or GLOBAL")


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


@router.get("/status", response_model=SystemStatusResponse)
async def get_setup_status(
    query_bus: QueryBus = Depends(get_query_bus),
) -> SystemStatusResponse:
    data = await query_bus.ask(GetSystemStatusQuery())
    return SystemStatusResponse(**data)


@router.post("/bootstrap", response_model=BootstrapResponse, status_code=201)
async def bootstrap_instance(
    body: BootstrapRequest,
    command_bus: CommandBus = Depends(get_command_bus),
) -> BootstrapResponse:
    result = await command_bus.send(
        BootstrapInstanceCommand(
            email=body.email,
            password=body.password,
            display_name=body.display_name,
            access_mode=body.access_mode,
        )
    )
    data = check_command_result(result)
    return BootstrapResponse(**data)


@router.put("/access-mode", response_model=SystemStatusResponse)
async def update_access_mode(
    body: UpdateAccessModeRequest,
    current_user: dict = Depends(require_owner()),
    command_bus: CommandBus = Depends(get_command_bus),
) -> SystemStatusResponse:
    result = await command_bus.send(
        UpdateAccessModeCommand(
            access_mode=body.access_mode,
            requester_roles=current_user.get("roles", []),
            requester_permissions=current_user.get("permissions", []),
        )
    )
    data = check_command_result(result)
    return SystemStatusResponse(**data)
