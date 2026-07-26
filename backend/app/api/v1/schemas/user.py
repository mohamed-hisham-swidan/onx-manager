from datetime import datetime

from pydantic import BaseModel, Field


class CreateUserRequest(BaseModel):
    email: str
    password: str = Field(..., min_length=8)
    display_name: str = Field(..., min_length=1, max_length=128)


class UpdateUserRequest(BaseModel):
    email: str | None = None
    display_name: str | None = None
    is_active: bool | None = None


class UserResponse(BaseModel):
    user_id: str
    email: str
    display_name: str
    is_active: bool
    roles: list[str] = []
    created_at: datetime
    last_login_at: datetime | None = None
