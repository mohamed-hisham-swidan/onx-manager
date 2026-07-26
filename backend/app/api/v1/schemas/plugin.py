from datetime import datetime

from pydantic import BaseModel, Field


class InstallPluginRequest(BaseModel):
    server_id: str
    name: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    description: str = ""
    author: str = ""
    website: str = ""
    dependencies: list[str] = []


class PluginResponse(BaseModel):
    plugin_id: str
    server_id: str
    name: str
    version: str
    description: str
    author: str
    status: str
    dependencies: list[str]
    installed_at: datetime
    updated_at: datetime
