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
    source: str = "manual"
    external_project_id: str | None = None
    external_version_id: str | None = None
    external_url: str | None = None
    checksum: str | None = None


class PluginSearchResultResponse(BaseModel):
    project_id: str
    slug: str
    title: str
    description: str = ""
    author: str = ""
    project_types: list[str] = []
    downloads: int = 0
    follows: int = 0
    icon_url: str = ""
    latest_version_id: str = ""


class PluginFileResponse(BaseModel):
    url: str
    filename: str
    size_bytes: int
    sha1: str = ""
    sha512: str = ""
    primary: bool = False


class PluginVersionResponse(BaseModel):
    version_id: str
    project_id: str
    name: str
    version_number: str
    game_versions: list[str] = []
    loaders: list[str] = []
    files: list[PluginFileResponse] = []
    dependencies: list[str] = []
    date_published: str = ""


class PluginVersionsResponse(BaseModel):
    project_id: str
    versions: list[PluginVersionResponse]
    selected: PluginVersionResponse | None = None
    notice: str = ""
    notice_kind: str = ""


class InstallModrinthPluginRequest(BaseModel):
    project_id: str = Field(..., min_length=1)
    version_id: str | None = None
    minecraft_version: str | None = None


class InstallModrinthPluginResponse(BaseModel):
    plugin_id: str
    version: str
    filename: str
    source: str = "modrinth"
    notice: str = ""
    notice_kind: str = ""
