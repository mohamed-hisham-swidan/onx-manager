import math
from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, SerializationInfo, field_serializer, model_validator

from app.core.timeutil import (
    NAIVE_ISO_REGEX,
    format_datetime_utc,
    is_timestamp_field,
)
from app.core.version import get_app_version

T = TypeVar("T")

def _normalize_response_value(val: Any, field_name: str | None = None) -> Any:
    if isinstance(val, datetime):
        return format_datetime_utc(val)
    if isinstance(val, str):
        if field_name and is_timestamp_field(field_name) and NAIVE_ISO_REGEX.match(val):
            return val.replace(" ", "T") + "Z"
        return val
    if isinstance(val, BaseModel):
        return val
    if isinstance(val, list):
        return [_normalize_response_value(x, field_name) for x in val]
    if isinstance(val, dict):
        return {
            k: _normalize_response_value(v, k if isinstance(k, str) else None)
            for k, v in val.items()
        }
    return val


class BaseResponse(BaseModel):
    """Base class for API responses ensuring ISO-8601 UTC ('Z') datetimes."""

    @field_serializer("*", mode="plain", when_used="json")
    def _serialize_response_fields(self, v: Any, info: SerializationInfo) -> Any:
        return _normalize_response_value(v, info.field_name)


class ErrorResponse(BaseResponse):
    code: str = ""
    message: str = ""
    details: dict[str, Any] | None = None
    request_id: str = ""
    retryable: bool = False
    documentation_url: str | None = None

    error: str = ""
    error_code: str = ""
    detail: dict[str, Any] | None = None
    timestamp: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def _sync_error_fields(cls, values: Any) -> Any:
        if isinstance(values, dict):
            if "code" in values and "error_code" not in values:
                values["error_code"] = values["code"]
            elif "error_code" in values and "code" not in values:
                values["code"] = values["error_code"]

            if "message" in values and "error" not in values:
                values["error"] = values["message"]
            elif "error" in values and "message" not in values:
                values["message"] = values["error"]

            if "details" in values and "detail" not in values:
                values["detail"] = values["details"]
            elif "detail" in values and "details" not in values:
                values["details"] = values["detail"]
        return values


class PaginationMeta(BaseResponse):
    page: int = 1
    per_page: int = 20
    total: int = 0
    total_pages: int = 1


class PaginatedResponse(BaseResponse, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    page_size: int = 20
    per_page: int = 20
    total_pages: int = 1
    data: list[T] | None = None
    pagination: PaginationMeta | None = None

    @model_validator(mode="before")
    @classmethod
    def _sync_fields(cls, values: Any) -> Any:
        if isinstance(values, dict):
            if "items" in values and "data" not in values:
                values["data"] = values["items"]
            elif "data" in values and "items" not in values:
                values["items"] = values["data"]

            if "per_page" in values and "page_size" not in values:
                values["page_size"] = values["per_page"]
            elif "page_size" in values and "per_page" not in values:
                values["per_page"] = values["page_size"]

            total = values.get("total", 0)
            per_page = values.get("per_page", values.get("page_size", 20))
            if "total_pages" not in values:
                values["total_pages"] = math.ceil(total / per_page) if per_page > 0 else 1
        return values


class SuccessResponse(BaseResponse):
    success: bool = True
    data: dict[str, Any] | None = None


class HealthResponse(BaseResponse):
    status: str = "ok"
    version: str = get_app_version()
    database: str = "connected"
    uptime_seconds: float | None = None
