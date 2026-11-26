from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.api.v1.schemas.common import BaseResponse


class LiveStateFileEntryResponse(BaseResponse):
    name: str
    path: str
    is_dir: bool
    size: int
    modified_at: float
    file_class: Literal["C"] = "C"
    is_dynamic_class_c: bool = False
    writable: bool = False


class LiveStateFileListResponse(BaseResponse):
    items: list[LiveStateFileEntryResponse] = Field(default_factory=list)


class LiveStateFileContentResponse(BaseResponse):
    server_id: str
    path: str
    content: str
    encoding: str = "utf-8"
    size: int
    is_dynamic_class_c: bool = False


class LiveStateWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., min_length=1)
    content: str
    reload_command: str | None = Field(default=None, max_length=64)


class LiveStateWriteResponse(BaseResponse):
    status: str = "written"
    server_id: str
    path: str
    rcon_flushed: bool = False
    rcon_reloaded: bool = False
    reload_command: str | None = None


class FileEntryResponse(BaseResponse):
    name: str
    path: str
    is_dir: bool
    size: int
    modified_at: str | None = None
    file_class: str | None = None
    editable: bool | None = None
    log_category: Literal["server_log", "crash_report", "plugin_log"] | None = None


class FileContentResponse(BaseResponse):
    path: str
    content: str
    is_binary: bool = False
    truncated: bool = False
    total_size_bytes: int | None = None
    is_compressed: bool = False


class WriteFileContentRequest(BaseModel):
    content: str
