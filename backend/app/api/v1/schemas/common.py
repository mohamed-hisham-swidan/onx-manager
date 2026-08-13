from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from app.core.version import get_app_version

T = TypeVar("T")


class ErrorResponse(BaseModel):
    error: str
    error_code: str
    detail: dict[str, Any] | None = None
    timestamp: datetime | None = None


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    page_size: int = 20


class SuccessResponse(BaseModel):
    success: bool = True
    data: dict[str, Any] | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = get_app_version()
    database: str = "connected"
    uptime_seconds: float | None = None
