from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PluginFile:
    url: str
    filename: str
    size_bytes: int
    sha1: str = ""
    sha512: str = ""
    primary: bool = False


@dataclass(frozen=True)
class PluginVersionInfo:
    version_id: str
    project_id: str
    name: str
    version_number: str
    game_versions: list[str] = field(default_factory=list)
    loaders: list[str] = field(default_factory=list)
    files: list[PluginFile] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    required_dependencies: list[str] = field(default_factory=list)
    changelog: str | None = None
    date_published: str = ""
    version_type: str = "release"


@dataclass(frozen=True)
class PluginProject:
    project_id: str
    slug: str
    title: str
    description: str = ""
    body: str = ""
    author: str = ""
    project_types: list[str] = field(default_factory=list)
    loaders: list[str] = field(default_factory=list)
    game_versions: list[str] = field(default_factory=list)
    downloads: int = 0
    follows: int = 0
    icon_url: str = ""
    wiki_url: str | None = None
    source_url: str | None = None
    client_side: str | None = None
    server_side: str | None = None


@dataclass(frozen=True)
class PluginSearchResult:
    project_id: str
    slug: str
    title: str
    description: str = ""
    author: str = ""
    project_types: list[str] = field(default_factory=list)
    downloads: int = 0
    follows: int = 0
    icon_url: str = ""
    latest_version_id: str = ""
    categories: list[str] = field(default_factory=list)
    loaders: list[str] = field(default_factory=list)
    client_side: str | None = None
    server_side: str | None = None
    date_modified: str = ""
    color: int | None = None


@dataclass(frozen=True)
class PluginSearchPage:
    items: list[PluginSearchResult]
    total_hits: int = 0
    offset: int = 0
    limit: int = 20


@dataclass(frozen=True)
class PluginVersionsPage:
    items: list[PluginVersionInfo]
    total: int = 0


class PluginCatalogProvider(ABC):
    name: str = ""

    @abstractmethod
    async def search(
        self,
        query: str,
        *,
        project_type: str = "plugin",
        loader: str | None = None,
        sort: str = "relevance",
        game_version: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> PluginSearchPage: ...

    @abstractmethod
    async def get_project(self, project_id: str) -> PluginProject: ...

    @abstractmethod
    async def get_project_versions(
        self,
        project_id: str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> PluginVersionsPage: ...

    @abstractmethod
    async def get_version(self, version_id: str) -> PluginVersionInfo: ...

    @abstractmethod
    async def download(
        self,
        url: str,
        expected_sha1: str | None = None,
        expected_sha512: str | None = None,
    ) -> bytes: ...
