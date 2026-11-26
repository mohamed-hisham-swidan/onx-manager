from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.api.v1.schemas.common import BaseResponse

BackupTypeValue = Literal["full", "worlds", "world", "nether", "end", "plugins", "config"]
BackupTierValue = Literal["tier_1", "tier_2"]
ArchiveFormatValue = Literal["tar.zst", "tar.gz"]


class CreateBackupRequest(BaseModel):
    server_id: str
    backup_type: BackupTypeValue = Field(default="full")
    tier: BackupTierValue = Field(default="tier_1")
    archive_format: ArchiveFormatValue = Field(default="tar.zst")
    include_cas_jars: bool = Field(default=False)


class RestoreBackupRequest(BaseModel):
    server_id: str | None = None


class BackupResponse(BaseResponse):
    backup_id: str
    server_id: str
    server_name: str | None = None
    server_deleted: bool = False
    backup_type: str
    status: str
    size_bytes: int
    checksum: str
    error_message: str
    created_at: datetime
    completed_at: datetime | None = None
    tier: str = "tier_1"
    pinned: bool = False


class VerifyBackupResponse(BaseResponse):
    backup_id: str
    valid: bool
    checksum_valid: bool
    size_valid: bool
    artifact_present: bool | None = None
    artifact_matches: bool | None = None
    artifact_error: str | None = None
