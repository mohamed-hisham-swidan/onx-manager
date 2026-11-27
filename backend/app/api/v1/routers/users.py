from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import (
    get_command_bus,
    get_current_user,
    get_query_bus,
    require_admin_or_owner,
)
from app.api.errors import check_command_result
from app.api.v1.schemas.user import (
    AdminCreateUserRequest,
    CreateUserRequest,
    UpdateUserAccessRequest,
    UpdateUserRequest,
    UserResponse,
)
from app.core.authorization import is_admin_or_owner_context, is_owner_context
from app.core.command_bus import CommandBus
from app.core.query_bus import QueryBus
from app.modules.auth.application.commands.admin_create_user import AdminCreateUserCommand
from app.modules.auth.application.commands.create_user import CreateUserCommand
from app.modules.auth.application.commands.delete_user import DeleteUserCommand
from app.modules.auth.application.commands.update_user import UpdateUserCommand
from app.modules.auth.application.commands.update_user_access import UpdateUserAccessCommand
from app.modules.auth.application.queries.get_current_user import GetCurrentUserQuery
from app.modules.auth.application.queries.get_system_status import GetSystemStatusQuery
from app.modules.auth.application.queries.list_users import ListUsersQuery

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("", response_model=list[UserResponse])
async def list_users(
    _current_user: dict = Depends(require_admin_or_owner("user:read")),
    query_bus: QueryBus = Depends(get_query_bus),
) -> list[UserResponse]:
    users = await query_bus.ask(ListUsersQuery())
    return [UserResponse(**u) for u in users]


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
    if status_data.get("access_mode") != "LOCAL":
        raise HTTPException(
            status_code=403,
            detail=(
                "Public self-registration is disabled in GLOBAL access mode. "
                "Use an invitation token to register."
            ),
        )

    result = await command_bus.send(
        CreateUserCommand(
            username=body.username,
            email=body.email,
            password=body.password,
            display_name=body.display_name,
        )
    )
    data = check_command_result(result)
    return UserResponse(**data)


@router.post("/manage", response_model=UserResponse, status_code=201)
async def admin_create_user(
    body: AdminCreateUserRequest,
    current_user: dict = Depends(require_admin_or_owner("user:write")),
    command_bus: CommandBus = Depends(get_command_bus),
) -> UserResponse:
    requester_roles = (
        ["owner"] if is_owner_context(current_user) else list(current_user.get("roles", []))
    )
    result = await command_bus.send(
        AdminCreateUserCommand(
            username=body.username,
            email=body.email,
            password=body.password,
            display_name=body.display_name,
            role=body.role,
            server_ids=body.server_ids,
            all_servers_access=body.all_servers_access,
            denied_permissions=body.denied_permissions,
            is_active=body.is_active,
            requester_id=current_user.get("user_id"),
            requester_roles=requester_roles,
        )
    )
    data = check_command_result(result)
    return UserResponse(**data)


@router.put("/{user_id}/access", response_model=UserResponse)
async def update_user_access(
    user_id: str,
    body: UpdateUserAccessRequest,
    current_user: dict = Depends(require_admin_or_owner("user:write")),
    command_bus: CommandBus = Depends(get_command_bus),
) -> UserResponse:
    requester_roles = (
        ["owner"] if is_owner_context(current_user) else list(current_user.get("roles", []))
    )
    result = await command_bus.send(
        UpdateUserAccessCommand(
            user_id=user_id,
            role=body.role,
            server_ids=body.server_ids,
            all_servers_access=body.all_servers_access,
            denied_permissions=body.denied_permissions,
            is_active=body.is_active,
            requester_id=current_user.get("user_id"),
            requester_roles=requester_roles,
        )
    )
    data = check_command_result(result)
    return UserResponse(**data)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    current_user: dict = Depends(get_current_user),
    query_bus: QueryBus = Depends(get_query_bus),
) -> UserResponse:
    if (
        not is_admin_or_owner_context(current_user)
        and current_user.get("user_id") != user_id
    ):
        raise HTTPException(status_code=403, detail="Permission denied")
    user_data = await query_bus.ask(GetCurrentUserQuery(user_id=user_id))
    if user_data is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(**user_data)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    body: UpdateUserRequest,
    current_user: dict = Depends(require_admin_or_owner("user:write")),
    command_bus: CommandBus = Depends(get_command_bus),
) -> UserResponse:
    result = await command_bus.send(
        UpdateUserCommand(
            user_id=user_id,
            username=body.username,
            email=body.email,
            display_name=body.display_name,
            is_active=body.is_active,
            requester_id=current_user.get("user_id"),
            requester_roles=(
                ["owner"]
                if is_admin_or_owner_context(current_user)
                and current_user.get("is_owner_db")
                else list(current_user.get("roles", []))
            ),
            requester_permissions=list(current_user.get("permissions", [])),
        )
    )
    data = check_command_result(result)
    return UserResponse(**data)


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    current_user: dict = Depends(require_admin_or_owner("user:delete")),
    command_bus: CommandBus = Depends(get_command_bus),
) -> None:
    requester_roles = (
        ["owner"]
        if current_user.get("is_owner_db")
        else list(current_user.get("roles", []))
    )
    result = await command_bus.send(
        DeleteUserCommand(
            user_id=user_id,
            requester_id=current_user.get("user_id"),
            requester_roles=requester_roles,
        )
    )
    check_command_result(result)
