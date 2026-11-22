import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.api.v1.schemas.common import BaseResponse

EMAIL_PATTERN: str = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
EMAIL_COMPILED: re.Pattern[str] = re.compile(EMAIL_PATTERN)


class CreateUserRequest(BaseModel):
    username: str | None = None
    email: str | None = None
    password: str = Field(..., min_length=8)
    display_name: str | None = Field(default=None, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        if not cleaned:
            return None
        if not EMAIL_COMPILED.match(cleaned):
            raise ValueError(f"Invalid email address: {v!r}")
        return cleaned

    @model_validator(mode="after")
    def validate_identifier(self) -> "CreateUserRequest":
        if not (self.username or self.email or "").strip():
            raise ValueError("username is required")
        return self


class UpdateUserRequest(BaseModel):
    username: str | None = None
    email: str | None = None
    display_name: str | None = None
    is_active: bool | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str | None) -> str | None:
        if v is not None and v.strip() != "" and not EMAIL_COMPILED.match(v.strip()):
            raise ValueError(f"Invalid email address: {v!r}")
        return v


class UserResponse(BaseResponse):
    user_id: str
    username: str = ""
    email: str | None = None
    display_name: str
    is_active: bool
    roles: list[str] = []
    created_at: datetime
    last_login_at: datetime | None = None
