from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import (
    get_command_bus,
    get_current_user,
    get_query_bus,
    require_permission,
)
from app.api.errors import check_command_result
from app.api.v1.schemas.user import CreateUserRequest, UpdateUserRequest, UserResponse
from app.core.command_bus import CommandBus
from app.core.query_bus import QueryBus
from app.modules.auth.application.commands.create_user import CreateUserCommand
from app.modules.auth.application.commands.delete_user import DeleteUserCommand
from app.modules.auth.application.commands.update_user import UpdateUserCommand
from app.modules.auth.application.queries.list_users import ListUsersQuery
from app.modules.auth.application.queries.get_current_user import GetCurrentUserQuery

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("", response_model=list[UserResponse])
async def list_users(
    current_user: dict = Depends(get_current_user),
    query_bus: QueryBus = Depends(get_query_bus),
) -> list[UserResponse]:
    users = await query_bus.ask(ListUsersQuery())
    return [UserResponse(**u) for u in users]


from app.modules.auth.application.queries.get_system_status import GetSystemStatusQuery


@router.post("", response_model=UserResponse, status_code=201)
async def create_user(
    body: CreateUserRequest,
    command_bus: CommandBus = Depends(get_command_bus),
    query_bus: QueryBus = Depends(get_query_bus),
) -> UserResponse:
    status_data = await query_bus.ask(GetSystemStatusQuery())
    if not status_data.get("initialized"):
        raise HTTPException(
            status_code=403,
            detail="Instance uninitialized. Complete setup bootstrap first.",
        )
    if status_data.get("access_mode") == "GLOBAL":
        raise HTTPException(
            status_code=403,
            detail="Public self-registration is disabled in GLOBAL access mode. Use an invitation token to register.",
        )

    result = await command_bus.send(
        CreateUserCommand(email=body.email, password=body.password, display_name=body.display_name)
    )
    data = check_command_result(result)
    return UserResponse(**data)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    current_user: dict = Depends(get_current_user),
    query_bus: QueryBus = Depends(get_query_bus),
) -> UserResponse:
    user_data = await query_bus.ask(GetCurrentUserQuery(user_id=user_id))
    if user_data is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(**user_data)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    body: UpdateUserRequest,
    current_user: dict = Depends(require_permission("user:write")),
    command_bus: CommandBus = Depends(get_command_bus),
) -> UserResponse:
    result = await command_bus.send(
        UpdateUserCommand(
            user_id=user_id,
            email=body.email,
            display_name=body.display_name,
            is_active=body.is_active,
        )
    )
    data = check_command_result(result)
    return UserResponse(**data)


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    current_user: dict = Depends(require_permission("user:delete")),
    command_bus: CommandBus = Depends(get_command_bus),
) -> None:
    result = await command_bus.send(DeleteUserCommand(user_id=user_id))
    check_command_result(result)
