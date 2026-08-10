from pydantic import BaseModel


class FileEntryResponse(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int


class FileContentResponse(BaseModel):
    path: str
    content: str


class WriteFileContentRequest(BaseModel):
    content: str
