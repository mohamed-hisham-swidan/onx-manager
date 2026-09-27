from __future__ import annotations

from typing import Any

from pydantic import Field

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.idempotency import IdempotencyKey
from app.modules.operations.application.services.operation_service import (
    OperationService,
    get_operation_service,
)


class CreateOperationCommand(Command):
    type: str
    target_type: str = "server"
    target_id: str | None = None
    actor_id: str | None = None
    idempotency_key: IdempotencyKey | None = None
    timeout_seconds: int = 600
    metadata: dict[str, Any] = Field(default_factory=dict)
    initial_steps: list[dict[str, Any]] | None = None


class CreateOperationHandler(CommandHandler[CreateOperationCommand]):
    def __init__(self, operation_service: OperationService | None = None) -> None:
        self._service = operation_service or get_operation_service()

    async def handle(self, command: CreateOperationCommand) -> CommandResult:
        idem_key = command.idempotency_key.value if command.idempotency_key else None
        op = await self._service.create_operation(
            type=command.type,
            target_type=command.target_type,
            target_id=command.target_id,
            actor_id=command.actor_id,
            idempotency_key=idem_key,
            timeout_seconds=command.timeout_seconds,
            metadata=command.metadata,
            initial_steps=command.initial_steps,
        )
        return CommandResult(
            success=True,
            entity_id=op.id,
            data=op,
            details={"operation_id": op.id, "status": op.status.value},
        )


class CancelOperationCommand(Command):
    operation_id: str
    idempotency_key: IdempotencyKey | None = None


class CancelOperationHandler(CommandHandler[CancelOperationCommand]):
    def __init__(self, operation_service: OperationService | None = None) -> None:
        self._service = operation_service or get_operation_service()

    async def handle(self, command: CancelOperationCommand) -> CommandResult:
        op = await self._service.request_cancellation(command.operation_id)
        return CommandResult(
            success=True,
            entity_id=op.id,
            data=op,
            details={"operation_id": op.id, "status": op.status.value},
        )


class RetryOperationCommand(Command):
    operation_id: str
    idempotency_key: IdempotencyKey | None = None


class RetryOperationHandler(CommandHandler[RetryOperationCommand]):
    def __init__(self, operation_service: OperationService | None = None) -> None:
        self._service = operation_service or get_operation_service()

    async def handle(self, command: RetryOperationCommand) -> CommandResult:
        op = await self._service.retry_operation(command.operation_id)
        return CommandResult(
            success=True,
            entity_id=op.id,
            data=op,
            details={"operation_id": op.id, "status": op.status.value},
        )
