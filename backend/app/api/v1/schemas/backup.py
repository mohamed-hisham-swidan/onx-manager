from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.api.v1.schemas.common import BaseResponse

BackupTypeValue = Literal["full", "worlds", "world", "nether", "end", "plugins", "config"]


class CreateBackupRequest(BaseModel):
    server_id: str
    backup_type: BackupTypeValue = Field(default="full")


class RestoreBackupRequest(BaseModel):
    server_id: str | None = None


class BackupResponse(BaseResponse):
    backup_id: str
    server_id: str
    backup_type: str
    status: str
    size_bytes: int
    checksum: str
    error_message: str
    created_at: datetime
    completed_at: datetime | None = None


class VerifyBackupResponse(BaseResponse):
    backup_id: str
    valid: bool
    checksum_valid: bool
    size_valid: bool
