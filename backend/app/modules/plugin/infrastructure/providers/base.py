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
    date_published: str = ""


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
    wiki_url: str = ""
    source_url: str = ""


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


class PluginCatalogProvider(ABC):
    name: str = ""

    @abstractmethod
    async def search(
        self,
        query: str,
        *,
        project_type: str = "plugin",
        limit: int = 20,
        offset: int = 0,
    ) -> list[PluginSearchResult]:
        ...

    @abstractmethod
    async def get_project(self, project_id: str) -> PluginProject:
        ...

    @abstractmethod
    async def get_project_versions(self, project_id: str) -> list[PluginVersionInfo]:
        ...

    @abstractmethod
    async def get_version(self, version_id: str) -> PluginVersionInfo:
        ...

    @abstractmethod
    async def download(
        self,
        url: str,
        expected_sha1: str | None = None,
        expected_sha512: str | None = None,
    ) -> bytes:
        ...
