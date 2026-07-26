from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str = Field(pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 900


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str = ""


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    permissions: list[str] = []


class ApiKeyResponse(BaseModel):
    api_key_id: str
    name: str
    prefix: str
    key: str | None = None
    permissions: list[str]
    expires_at: datetime | None = None
    is_revoked: bool
    created_at: datetime
