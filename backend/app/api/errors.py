import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.core.exceptions import (
    AuthenticationError,
    ConflictError,
    InfrastructureError,
    InternalError,
    MCSError,
    NotFoundError,
    PermissionDenied,
    RateLimitExceeded,
    ValidationError,
)

logger = logging.getLogger(__name__)


_ERROR_STATUS_MAP: dict[str, int] = {
    "NOT_FOUND": 404,
    "SERVER_NOT_RUNNING": 404,
    "OPERATION_NOT_FOUND": 404,
    "CONFLICT": 409,
    "CLAIM_ACTIVE": 409,
    "DUPLICATE_TARGET": 409,
    "PORT_ALREADY_REGISTERED": 409,
    "OPERATION_CONCURRENCY_CONFLICT": 409,
    "SERVER_BUSY": 409,
    "PORT_OCCUPIED": 409,
    "SERVER_STOP_FAILED": 409,
    "SERVER_STOP_UNCONFIRMED": 409,
    "RESTART_STOP_FAILED": 409,
    "DELETE_STOP_NOT_CONFIRMED": 409,
    "DELETE_PROVISIONING_ACTIVE": 409,
    "RESTORE_SERVER_ACTIVE": 409,
    "OPERATION_ALREADY_TERMINAL": 409,
    "INVALID_STATE_TRANSITION": 409,
    "SERVER_MODE_VERSIONING_DISABLED": 409,
    "DUPLICATE_PORT_SET": 409,
    "PORT_ALLOCATION_EXHAUSTED": 409,
    "HOT_CLONE_REFUSED": 409,
    "BRANCH_RUNTIME_ACTIVE": 409,
    "BRANCH_CONCURRENCY_LIMIT": 409,
    "BOT_RUN_INSUFFICIENT_RESOURCES": 422,
    "GIT_REPOSITORY_STATE": 409,
    "DIRTY_WORKTREE": 409,
    "MERGE_CONFLICT": 409,
    "GIT_REF_INVALID": 422,
    "GIT_REMOTE_URL_INVALID": 422,
    "GIT_TRACKED_FILE_TOO_LARGE": 413,
    "SECRET_FILE_IN_GIT_FORBIDDEN": 422,
    "CASE_COLLISION": 422,
    "GIT_CONFIGURATION_ERROR": 500,
    "GIT_UNSUPPORTED_PLATFORM": 501,
    "GIT_UNAVAILABLE": 503,
    "GIT_TIMEOUT": 504,
    "MASTER_KEK_MISSING": 503,
    "MASTER_KEK_INVALID": 503,
    "MASTER_KEK_VERSION_MISMATCH": 409,
    "SECURITY_PERMISSION_ERROR": 503,
    "CAS_UNSUPPORTED_PLATFORM": 501,
    "BACKUP_PINNED": 409,
    "INSUFFICIENT_STORAGE": 507,
    "FENCING_TOKEN_MISMATCH": 409,
    "REFRESH_RECOVERY_REQUIRED": 409,
    "REPO_LEASE_TIMEOUT": 409,
    "UNSUPPORTED_FORGE_VERSION": 422,
    "CURSEFORGE_API_KEY_MISSING": 409,
    "HOSTILE_EXECUTABLE_REJECTED": 422,
    "UNTRUSTED_DOWNLOAD_HOST": 422,
    "MANUAL_DOWNLOAD_REQUIRED": 409,
    "UPGRADE_BLOCKED": 409,
    "LEC_MISSING": 409,
    "HEALTH_GATE_FAILED": 502,
    "MODPACK_FORMAT_INVALID": 422,
    "VALIDATION_ERROR": 422,
    "INVALID_SERVER_STATE": 422,
    "WARNING_NOT_ACKNOWLEDGED": 422,
    "METHOD_PROTOCOL_INCOMPATIBLE": 422,
    "UNREGISTERED_PORT": 422,
    "INVALID_SERVICE_TYPE": 422,
    "AUTHENTICATION_ERROR": 401,
    "PERMISSION_DENIED": 403,
    "PASSWORD_REQUIRED_FOR_EXPOSURE": 403,
    "RATE_LIMIT_EXCEEDED": 429,
    "INFRASTRUCTURE_ERROR": 503,
    "FILESYSTEM_CLEANUP_FAILED": 500,
    "INTERNAL_ERROR": 500,
    "GUARD_CONFIGURATION_ERROR": 500,
    "HANDLER_NOT_FOUND": 500,
    "UNEXPECTED_ERROR": 500,
}


def check_command_result(result: "CommandResult") -> dict[str, Any]:  # noqa: F821
    """Raise proper HTTP errors from a CommandResult based on its error_code."""
    if result.success:
        return result.data or result.details or {}
    status = _ERROR_STATUS_MAP.get(result.error_code or "", 400)
    raise MCSError(
        message=result.error or "",
        code=result.error_code or "UNEXPECTED_ERROR",
        details=result.details,
        http_status=status,
    )


def _error_response(
    status: int,
    error: str,
    code: str,
    detail: dict | None = None,
    request: Request | None = None,
    retryable: bool | None = None,
) -> JSONResponse:
    req_id = ""
    if request is not None:
        req_id = getattr(request.state, "request_id", "") or request.headers.get("X-Request-ID", "")

    is_retryable = retryable if retryable is not None else (status in (429, 503, 504))

    return JSONResponse(
        status_code=status,
        content={
            # Contract specification keys (contracts/api.yaml)
            "code": code,
            "message": error,
            "details": detail,
            "request_id": req_id,
            "retryable": is_retryable,
            # Legacy keys (backward-compatible)
            "error": error,
            "error_code": code,
            "detail": detail,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )


async def mcs_error_handler(request: Request, exc: MCSError) -> JSONResponse:
    logger.warning(
        "MCSError: code=%s message=%s path=%s detail=%s",
        exc.code,
        exc.message,
        request.url.path,
        exc.details,
    )
    return _error_response(
        status=exc.http_status,
        error=exc.message,
        code=exc.code,
        detail=exc.details,
        request=request,
    )


async def validation_error_handler(request: Request, exc: ValidationError) -> JSONResponse:
    return _error_response(
        status=422,
        error=exc.message,
        code=exc.code,
        detail=exc.details,
        request=request,
    )


async def authentication_error_handler(request: Request, exc: AuthenticationError) -> JSONResponse:
    return _error_response(status=401, error=exc.message, code=exc.code, request=request)


async def permission_denied_handler(request: Request, exc: PermissionDenied) -> JSONResponse:
    return _error_response(status=403, error=exc.message, code=exc.code, request=request)


async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return _error_response(status=404, error=exc.message, code=exc.code, request=request)


async def conflict_error_handler(request: Request, exc: ConflictError) -> JSONResponse:
    return _error_response(
        status=409,
        error=exc.message,
        code=exc.code,
        detail=jsonable_encoder(exc.details or None),
        request=request,
    )


async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    retry_after = exc.details.get("retry_after", 60) if exc.details else 60
    req_id = getattr(request.state, "request_id", "") or request.headers.get("X-Request-ID", "")
    return JSONResponse(
        status_code=429,
        content={
            "code": exc.code,
            "message": exc.message,
            "details": exc.details,
            "request_id": req_id,
            "retryable": True,
            "error": exc.message,
            "error_code": exc.code,
            "detail": exc.details,
            "timestamp": datetime.now(UTC).isoformat(),
        },
        headers={"Retry-After": str(retry_after)},
    )


async def infrastructure_error_handler(request: Request, exc: InfrastructureError) -> JSONResponse:
    logger.error("InfrastructureError: code=%s path=%s", exc.code, request.url.path)
    return _error_response(
        status=503, error=exc.message, code=exc.code, request=request, retryable=True
    )


async def internal_error_handler(request: Request, exc: InternalError) -> JSONResponse:
    logger.exception("InternalError: path=%s", request.url.path)
    return _error_response(status=500, error=exc.message, code=exc.code, request=request)


async def unhandled_error_handler(request: Request, _exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception: path=%s", request.url.path)
    return _error_response(
        status=500,
        error="Internal server error",
        code="INTERNAL_ERROR",
        request=request,
    )


def register_error_handlers(app: "FastAPI") -> None:  # noqa: F821

    app.add_exception_handler(ValidationError, validation_error_handler)
    app.add_exception_handler(AuthenticationError, authentication_error_handler)
    app.add_exception_handler(PermissionDenied, permission_denied_handler)
    app.add_exception_handler(NotFoundError, not_found_handler)
    app.add_exception_handler(ConflictError, conflict_error_handler)
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
    app.add_exception_handler(InfrastructureError, infrastructure_error_handler)
    app.add_exception_handler(InternalError, internal_error_handler)
    app.add_exception_handler(MCSError, mcs_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
