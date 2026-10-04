import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.api.v1.schemas.common import BaseResponse

EMAIL_PATTERN: str = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
EMAIL_COMPILED: re.Pattern[str] = re.compile(EMAIL_PATTERN)


class CreateUserRequest(BaseModel):
    email: str
    password: str = Field(..., min_length=8)
    display_name: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if not EMAIL_COMPILED.match(v):
            raise ValueError(f"Invalid email address: {v!r}")
        return v


class UpdateUserRequest(BaseModel):
    email: str | None = None
    display_name: str | None = None
    is_active: bool | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str | None) -> str | None:
        if v is not None and not EMAIL_COMPILED.match(v):
            raise ValueError(f"Invalid email address: {v!r}")
        return v


class UserResponse(BaseResponse):
    user_id: str
    email: str
    display_name: str
    is_active: bool
    roles: list[str] = []
    created_at: datetime
    last_login_at: datetime | None = None
