from pydantic import BaseModel

from app.api.v1.schemas.common import BaseResponse


class FileEntryResponse(BaseResponse):
    name: str
    path: str
    is_dir: bool
    size: int


class FileContentResponse(BaseResponse):
    path: str
    content: str
    is_binary: bool = False


class WriteFileContentRequest(BaseModel):
    content: str
