from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.api.deps import get_command_bus, get_query_bus, require_permission
from app.api.errors import check_command_result
from app.core.command_bus import CommandBus
from app.core.query_bus import QueryBus
from app.modules.auth.application import (
    AcceptInviteCommand,
    CreateInviteCommand,
    ListInvitesQuery,
    RevokeInviteCommand,
    VerifyInviteQuery,
)

router = APIRouter(prefix="/api/v1/invites", tags=["invites"])


class CreateInviteRequest(BaseModel):
    email: str | None = None
    global_role: str = "member"
    server_id: str | None = None
    server_role: str | None = None
    max_uses: int = 1
    expires_in_hours: int | None = 48


class CreateInviteResponse(BaseModel):
    invite_id: str
    token: str
    token_prefix: str
    email: str | None = None
    global_role: str
    server_id: str | None = None
    server_role: str | None = None
    status: str
    max_uses: int
    expires_at: str | None = None


class VerifyInviteResponse(BaseModel):
    valid: bool
    email: str | None = None
    expires_at: str | None = None


class AcceptInviteRequest(BaseModel):
    token: str
    email: str
    password: str = Field(min_length=8)
    display_name: str


class AcceptInviteResponse(BaseModel):
    user_id: str
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 900


@router.post("", response_model=CreateInviteResponse, status_code=201)
async def create_invite(
    body: CreateInviteRequest,
    current_user: dict = Depends(require_permission("user:write")),
    command_bus: CommandBus = Depends(get_command_bus),
) -> CreateInviteResponse:
    creator_id = current_user.get("sub") or current_user.get("user_id") or ""
    result = await command_bus.send(
        CreateInviteCommand(
            creator_id=creator_id,
            email=body.email,
            global_role=body.global_role,
            server_id=body.server_id,
            server_role=body.server_role,
            max_uses=body.max_uses,
            expires_in_hours=body.expires_in_hours,
        )
    )
    data = check_command_result(result)
    return CreateInviteResponse(**data)


@router.get("", response_model=list[dict[str, Any]])
async def list_invites(
    _current_user: dict = Depends(require_permission("user:write")),
    query_bus: QueryBus = Depends(get_query_bus),
) -> list[dict[str, Any]]:
    return await query_bus.ask(ListInvitesQuery())


@router.delete("/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(
    invite_id: str,
    _current_user: dict = Depends(require_permission("user:write")),
    command_bus: CommandBus = Depends(get_command_bus),
) -> None:
    result = await command_bus.send(RevokeInviteCommand(invitation_id=invite_id))
    check_command_result(result)


@router.get("/verify/{token}", response_model=VerifyInviteResponse)
async def verify_invite(
    token: str,
    query_bus: QueryBus = Depends(get_query_bus),
) -> VerifyInviteResponse:
    data = await query_bus.ask(VerifyInviteQuery(token=token))
    return VerifyInviteResponse(**data)


@router.post("/accept", response_model=AcceptInviteResponse, status_code=201)
async def accept_invite(
    body: AcceptInviteRequest,
    command_bus: CommandBus = Depends(get_command_bus),
) -> AcceptInviteResponse:
    result = await command_bus.send(
        AcceptInviteCommand(
            token=body.token,
            email=body.email,
            password=body.password,
            display_name=body.display_name,
        )
    )
    data = check_command_result(result)
    return AcceptInviteResponse(**data)
