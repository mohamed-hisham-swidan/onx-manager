from __future__ import annotations

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, model_validator

from app.api.deps import get_command_bus, get_query_bus, require_permission
from app.api.errors import check_command_result
from app.api.v1.schemas.common import BaseResponse
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


class CreateInviteResponse(BaseResponse):
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


class VerifyInviteRequest(BaseModel):
    token: str


class VerifyInviteResponse(BaseResponse):
    valid: bool
    email: str | None = None
    expires_at: str | None = None


class AcceptInviteRequest(BaseModel):
    token: str
    username: str | None = None
    email: str | None = None
    password: str = Field(min_length=8)
    display_name: str | None = None

    @model_validator(mode="after")
    def validate_identifier(self) -> AcceptInviteRequest:
        if not (self.username or self.email or "").strip():
            raise ValueError("username is required")
        return self


class AcceptInviteResponse(BaseResponse):
    user_id: str
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 900


class InviteListItemResponse(BaseResponse):
    invite_id: str
    token_prefix: str
    creator_id: str
    email: str | None = None
    global_role: str
    server_id: str | None = None
    server_role: str | None = None
    status: str
    max_uses: int
    use_count: int
    expires_at: str | None = None
    used_at: str | None = None
    created_at: str | None = None


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


@router.get("", response_model=list[InviteListItemResponse])
async def list_invites(
    _current_user: dict = Depends(require_permission("user:write")),
    query_bus: QueryBus = Depends(get_query_bus),
) -> list[InviteListItemResponse]:
    items = await query_bus.ask(ListInvitesQuery())
    return [InviteListItemResponse(**item) for item in items]


@router.delete("/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(
    invite_id: str,
    _current_user: dict = Depends(require_permission("user:write")),
    command_bus: CommandBus = Depends(get_command_bus),
) -> None:
    result = await command_bus.send(RevokeInviteCommand(invitation_id=invite_id))
    check_command_result(result)


@router.post("/verify", response_model=VerifyInviteResponse)
async def verify_invite(
    body: VerifyInviteRequest,
    query_bus: QueryBus = Depends(get_query_bus),
) -> VerifyInviteResponse:
    data = await query_bus.ask(VerifyInviteQuery(token=body.token))
    return VerifyInviteResponse(**data)


@router.post("/accept", response_model=AcceptInviteResponse, status_code=201)
async def accept_invite(
    body: AcceptInviteRequest,
    command_bus: CommandBus = Depends(get_command_bus),
) -> AcceptInviteResponse:
    result = await command_bus.send(
        AcceptInviteCommand(
            token=body.token,
            username=body.username,
            email=body.email,
            password=body.password,
            display_name=body.display_name,
        )
    )
    data = check_command_result(result)
    return AcceptInviteResponse(**data)
