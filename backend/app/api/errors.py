import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, Request
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
    "CONFLICT": 409,
    "VALIDATION_ERROR": 422,
    "AUTHENTICATION_ERROR": 401,
    "PERMISSION_DENIED": 403,
    "RATE_LIMIT_EXCEEDED": 429,
    "INFRASTRUCTURE_ERROR": 503,
    "INTERNAL_ERROR": 500,
    "HANDLER_NOT_FOUND": 500,
    "UNEXPECTED_ERROR": 500,
}


def check_command_result(result: "CommandResult") -> dict[str, Any]:  # noqa: F821
    """Raise proper HTTP errors from a CommandResult based on its error_code."""
    if result.success:
        return result.data or {}
    status = _ERROR_STATUS_MAP.get(result.error_code or "", 400)
    raise MCSError(
        message=result.error or "",
        code=result.error_code or "UNEXPECTED_ERROR",
        http_status=status,
    )


def _error_response(status: int, error: str, code: str, detail: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": error,
            "error_code": code,
            "detail": detail,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


async def mcs_error_handler(request: Request, exc: MCSError) -> JSONResponse:
    logger.warning("MCSError: code=%s path=%s detail=%s", exc.code, request.url.path, exc.details)
    return _error_response(
        status=exc.http_status,
        error=exc.message,
        code=exc.code,
        detail=exc.details,
    )


async def validation_error_handler(request: Request, exc: ValidationError) -> JSONResponse:
    return _error_response(status=422, error=exc.message, code=exc.code, detail=exc.details)


async def authentication_error_handler(request: Request, exc: AuthenticationError) -> JSONResponse:
    return _error_response(status=401, error=exc.message, code=exc.code)


async def permission_denied_handler(request: Request, exc: PermissionDenied) -> JSONResponse:
    return _error_response(status=403, error=exc.message, code=exc.code)


async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return _error_response(status=404, error=exc.message, code=exc.code)


async def conflict_error_handler(request: Request, exc: ConflictError) -> JSONResponse:
    return _error_response(status=409, error=exc.message, code=exc.code)


async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    retry_after = exc.details.get("retry_after", 60) if exc.details else 60
    return JSONResponse(
        status_code=429,
        content={
            "error": exc.message,
            "error_code": exc.code,
            "detail": exc.details,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        headers={"Retry-After": str(retry_after)},
    )


async def infrastructure_error_handler(request: Request, exc: InfrastructureError) -> JSONResponse:
    logger.error("InfrastructureError: code=%s path=%s", exc.code, request.url.path)
    return _error_response(status=503, error=exc.message, code=exc.code)


async def internal_error_handler(request: Request, exc: InternalError) -> JSONResponse:
    logger.exception("InternalError: path=%s", request.url.path)
    return _error_response(status=500, error=exc.message, code=exc.code)


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception: path=%s", request.url.path)
    return _error_response(status=500, error="Internal server error", code="INTERNAL_ERROR")


def register_error_handlers(app: "FastAPI") -> None:  # noqa: F821
    from fastapi import FastAPI

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
