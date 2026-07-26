from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_command_bus, get_current_user, get_db, get_query_bus
from app.api.errors import check_command_result
from app.api.v1.schemas.auth import (
    ApiKeyCreateRequest,
    ApiKeyResponse,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    RefreshTokenRequest,
)
from app.core.command_bus import CommandBus
from app.core.query_bus import QueryBus
from app.modules.auth.application.commands.create_api_key import CreateApiKeyCommand
from app.modules.auth.application.commands.login import LoginCommand
from app.modules.auth.application.commands.logout import LogoutCommand
from app.modules.auth.application.commands.refresh_token import RefreshTokenCommand
from app.modules.auth.application.commands.revoke_api_key import RevokeApiKeyCommand
from app.modules.auth.application.queries.get_current_user import GetCurrentUserQuery
from app.modules.auth.application.queries.list_users import ListUsersQuery
from app.modules.auth.infrastructure.models import ApiKeyModel

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    command_bus: CommandBus = Depends(get_command_bus),
    request: Request = None,
) -> LoginResponse:
    client_ip = request.client.host if request and request.client else ""
    result = await command_bus.send(
        LoginCommand(email=body.email, password=body.password, ip_address=client_ip)
    )
    data = check_command_result(result)
    return LoginResponse(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        token_type="bearer",
        expires_in=900,
    )


@router.post("/refresh", response_model=LoginResponse)
async def refresh_token(
    body: RefreshTokenRequest,
    command_bus: CommandBus = Depends(get_command_bus),
) -> LoginResponse:
    result = await command_bus.send(RefreshTokenCommand(refresh_token=body.refresh_token))
    data = check_command_result(result)
    return LoginResponse(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        token_type="bearer",
        expires_in=900,
    )


@router.post("/logout", response_model=dict)
async def logout(
    current_user: dict = Depends(get_current_user),
    command_bus: CommandBus = Depends(get_command_bus),
    body: LogoutRequest | None = None,
) -> dict:
    refresh_token = body.refresh_token if body else ""
    result = await command_bus.send(
        LogoutCommand(user_id=current_user["user_id"], refresh_token=refresh_token)
    )
    return check_command_result(result)


@router.get("/me", response_model=dict)
async def get_current_user_info(
    current_user: dict = Depends(get_current_user),
    query_bus: QueryBus = Depends(get_query_bus),
) -> dict:
    user_data = await query_bus.ask(GetCurrentUserQuery(user_id=current_user["user_id"]))
    if user_data is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user_data


@router.get("/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ApiKeyResponse]:
    stmt = (
        select(ApiKeyModel)
        .where(ApiKeyModel.user_id == current_user["user_id"])
        .where(ApiKeyModel.is_revoked == False)
        .order_by(ApiKeyModel.created_at.desc())
    )
    result = await db.execute(stmt)
    keys = result.scalars().all()
    return [
        ApiKeyResponse(
            api_key_id=k.id,
            name=k.name,
            prefix=k.prefix,
            key=None,
            permissions=k.permissions.split(",") if k.permissions else [],
            expires_at=k.expires_at,
            is_revoked=k.is_revoked,
            created_at=k.created_at,
        )
        for k in keys
    ]


@router.post("/api-keys", response_model=ApiKeyResponse, status_code=201)
async def create_api_key(
    body: ApiKeyCreateRequest,
    current_user: dict = Depends(get_current_user),
    command_bus: CommandBus = Depends(get_command_bus),
) -> ApiKeyResponse:
    result = await command_bus.send(
        CreateApiKeyCommand(
            user_id=current_user["user_id"],
            name=body.name,
            permissions=body.permissions,
        )
    )
    data = check_command_result(result)
    return ApiKeyResponse(
        api_key_id=data["api_key_id"],
        name=data["name"],
        prefix=data["prefix"],
        key=data["key"],
        permissions=data["permissions"],
        expires_at=data.get("expires_at"),
        is_revoked=data["is_revoked"],
        created_at=data["created_at"],
    )


@router.delete("/api-keys/{api_key_id}", status_code=204)
async def revoke_api_key(
    api_key_id: str,
    current_user: dict = Depends(get_current_user),
    command_bus: CommandBus = Depends(get_command_bus),
) -> None:
    await command_bus.send(
        RevokeApiKeyCommand(
            user_id=current_user["user_id"],
            api_key_id=api_key_id,
        )
    )
