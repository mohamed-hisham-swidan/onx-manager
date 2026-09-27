from __future__ import annotations

from typing import Any

from app.core.exceptions import ConflictError, MCSError, NotFoundError


class OperationError(MCSError):
    def __init__(
        self,
        message: str = "",
        *,
        code: str = "OPERATION_ERROR",
        details: dict[str, Any] | None = None,
        http_status: int = 500,
        retryable: bool = False,
    ) -> None:
        super().__init__(
            message or "Operation error",
            code=code,
            details=details,
            http_status=http_status,
            retryable=retryable,
        )


class OperationNotFoundError(NotFoundError):
    def __init__(self, operation_id: str) -> None:
        super().__init__(f"Operation '{operation_id}' not found")
        self.code = "OPERATION_NOT_FOUND"


class InvalidStateTransitionError(ConflictError):
    def __init__(self, from_status: str, to_status: str, reason: str = "") -> None:
        msg = f"Cannot transition operation from {from_status} to {to_status}"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)
        self.code = "INVALID_STATE_TRANSITION"


class OperationTerminalConflictError(ConflictError):
    def __init__(self, operation_id: str, status: str, action: str = "cancel") -> None:
        super().__init__(
            f"Operation '{operation_id}' is already terminal ({status}) and cannot be {action}led"
        )
        self.code = "OPERATION_ALREADY_TERMINAL"


class OperationConcurrencyConflictError(ConflictError):
    def __init__(
        self,
        target_type: str = "server",
        target_id: str = "",
        active_op_id: str = "",
        op_type: str = "",
        message: str = "",
    ) -> None:
        msg = message or (
            f"Target {target_type} '{target_id}' already has active "
            f"operation '{active_op_id or op_type}'"
        )
        super().__init__(msg)
        self.code = "OPERATION_CONCURRENCY_CONFLICT"


class OperationStepError(OperationError):
    def __init__(self, step_id: str, message: str = "") -> None:
        super().__init__(
            message or f"Operation step '{step_id}' error",
            code="OPERATION_STEP_ERROR",
            http_status=400,
        )
