from datetime import datetime

from pydantic import BaseModel, Field


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
    filename: str | None = None
    pending_deletion: bool = False
    pending_deletion_requested_at: datetime | None = None
    external_project_id: str | None = None
    external_version_id: str | None = None
    external_url: str | None = None
    checksum: str | None = None
    icon_url: str | None = None
    loader: str | None = None
    mod_id: str | None = None
    is_disabled_on_disk: bool = False
    warning: str | None = None


class PluginSearchResultResponse(BaseModel):
    project_id: str
    slug: str
    title: str
    description: str = ""
    author: str = ""
    project_types: list[str] = []
    downloads: int = 0
    follows: int = 0
    icon_url: str | None = None
    latest_version_id: str = ""
    categories: list[str] = []
    loaders: list[str] = []
    client_side: str | None = None
    server_side: str | None = None
    date_modified: str = ""
    color: int | None = None


class PluginSearchResultsResponse(BaseModel):
    items: list[PluginSearchResultResponse]
    total_hits: int = 0
    offset: int = 0
    limit: int = 20


class PluginProjectResponse(BaseModel):
    project_id: str
    slug: str
    title: str
    description: str = ""
    body: str = ""
    author: str = ""
    project_types: list[str] = []
    loaders: list[str] = []
    game_versions: list[str] = []
    downloads: int = 0
    follows: int = 0
    icon_url: str | None = None
    wiki_url: str | None = None
    source_url: str | None = None
    client_side: str | None = None
    server_side: str | None = None


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
    total: int = 0


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


class ToggleModStateRequest(BaseModel):
    mod_id: str | None = None
    plugin_id: str | None = None
    enabled: bool

