from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from app.api.deps import get_command_bus, get_query_bus, require_operation_permission
from app.api.errors import check_command_result
from app.api.v1.schemas.operation import (
    CreateOperationRequest,
    OperationDetailResponse,
    OperationSummaryResponse,
)
from app.core.authorization import authorize_server_action, is_admin_or_owner_context
from app.core.command_bus import CommandBus
from app.core.idempotency import IdempotencyKey
from app.core.query_bus import QueryBus
from app.modules.operations.application import (
    CancelOperationCommand,
    CreateOperationCommand,
    GetOperationQuery,
    ListOperationsQuery,
    RetryOperationCommand,
)

router = APIRouter(prefix="/api/v1", tags=["operations"])

__all__ = ["router"]


@router.post("/operations", response_model=OperationDetailResponse, status_code=202)
async def create_operation(
    request: CreateOperationRequest,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    current_user: Annotated[dict, Depends(require_operation_permission("server:write"))],
    idempotency_header: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> OperationDetailResponse:
    raw_key = idempotency_header or request.idempotency_key
    idem_key = IdempotencyKey(raw_key) if raw_key else None
    command = CreateOperationCommand(
        type=request.type,
        target_type=request.target_type,
        target_id=request.target_id,
        actor_id=current_user.get("user_id"),
        idempotency_key=idem_key,
        timeout_seconds=request.timeout_seconds,
        metadata=request.metadata,
        initial_steps=request.initial_steps,
    )
    result = await command_bus.send(command)
    check_command_result(result)
    return OperationDetailResponse.from_domain(result.data)


@router.get("/operations/{operation_id}", response_model=OperationDetailResponse, status_code=200)
async def get_operation(
    operation_id: str,
    query_bus: Annotated[QueryBus, Depends(get_query_bus)],
    _current_user: Annotated[dict, Depends(require_operation_permission("server:read"))],
) -> OperationDetailResponse:
    query = GetOperationQuery(operation_id=operation_id)
    op = await query_bus.ask(query)
    return OperationDetailResponse.from_domain(op)


@router.get("/operations", response_model=list[OperationSummaryResponse], status_code=200)
async def list_operations(
    query_bus: Annotated[QueryBus, Depends(get_query_bus)],
    current_user: Annotated[dict, Depends(require_operation_permission("server:read"))],
    target_type: str | None = None,
    target_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[OperationSummaryResponse]:
    if (
        not is_admin_or_owner_context(current_user)
        and target_type == "server"
        and target_id
        and not authorize_server_action(current_user, target_id, "view")
    ):
        raise HTTPException(status_code=403, detail="Permission denied")
    query = ListOperationsQuery(
        target_type=target_type,
        target_id=target_id,
        status=status,
        limit=limit,
    )
    ops = await query_bus.ask(query)
    if not is_admin_or_owner_context(current_user):
        ops = [
            op
            for op in ops
            if str(op.target_type) == "server"
            and op.target_id
            and authorize_server_action(current_user, str(op.target_id), "view")
        ]
    return [OperationSummaryResponse.from_domain(op) for op in ops]


@router.post(
    "/operations/{operation_id}/cancel",
    response_model=OperationDetailResponse,
    status_code=202,
)
async def cancel_operation(
    operation_id: str,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    _current_user: Annotated[dict, Depends(require_operation_permission("server:write"))],
    idempotency_header: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> OperationDetailResponse:
    idem_key = IdempotencyKey(idempotency_header) if idempotency_header else None
    command = CancelOperationCommand(
        operation_id=operation_id,
        idempotency_key=idem_key,
    )
    result = await command_bus.send(command)
    check_command_result(result)
    return OperationDetailResponse.from_domain(result.data)


@router.post(
    "/operations/{operation_id}/retry",
    response_model=OperationDetailResponse,
    status_code=202,
)
async def retry_operation(
    operation_id: str,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    _current_user: Annotated[dict, Depends(require_operation_permission("server:write"))],
    idempotency_header: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> OperationDetailResponse:
    idem_key = IdempotencyKey(idempotency_header) if idempotency_header else None
    command = RetryOperationCommand(
        operation_id=operation_id,
        idempotency_key=idem_key,
    )
    result = await command_bus.send(command)
    check_command_result(result)
    return OperationDetailResponse.from_domain(result.data)
