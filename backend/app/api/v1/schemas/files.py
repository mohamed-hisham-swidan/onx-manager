from pydantic import BaseModel


class FileEntryResponse(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int


class FileContentResponse(BaseModel):
    path: str
    content: str
    is_binary: bool = False


class WriteFileContentRequest(BaseModel):
    content: str
