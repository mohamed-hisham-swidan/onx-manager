from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.api.v1.schemas.common import BaseResponse


class LoginRequest(BaseModel):
    username: str | None = None
    email: str | None = None
    password: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_identifier(self) -> "LoginRequest":
        if not (self.username or self.email or "").strip():
            raise ValueError("username is required")
        return self


class LoginResponse(BaseResponse):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 900


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    permissions: list[str] = []


class ApiKeyResponse(BaseResponse):
    api_key_id: str
    name: str
    prefix: str
    key: str | None = None
    permissions: list[str]
    expires_at: datetime | None = None
    is_revoked: bool
    created_at: datetime
