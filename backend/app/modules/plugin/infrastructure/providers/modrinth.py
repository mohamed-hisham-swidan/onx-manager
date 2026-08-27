from __future__ import annotations

import asyncio
import hashlib
import logging
import re

from app.core.exceptions import CorruptedDownloadError, DownloadError, DownloadTimeoutError
from app.core.http_client import get_http_client
from app.modules.plugin.infrastructure.providers.base import (
    PluginCatalogProvider,
    PluginFile,
    PluginProject,
    PluginSearchPage,
    PluginSearchResult,
    PluginVersionInfo,
    PluginVersionsPage,
)

logger = logging.getLogger(__name__)

MODRINTH_API_BASE = "https://api.modrinth.com/v2"

MODRINTH_TIMEOUT_SECONDS: int = 30
MODRINTH_MAX_RETRIES: int = 2

_PLUGIN_CATEGORIES = ("bukkit", "paper", "purpur", "spigot", "folia")
_PLUGIN_FACET = '["project_type:plugin"]'
_PLUGIN_LOADER_FACETS = (
    '["categories:bukkit","categories:paper","categories:purpur","categories:spigot",'
    '"categories:folia"]'
)

_MOD_CATEGORIES = ("fabric", "forge", "neoforge", "quilt")
_MOD_FACET = '["project_type:mod"]'
_MOD_LOADER_FACETS = (
    '["categories:fabric","categories:forge","categories:neoforge","categories:quilt"]'
)

_LOADER_CATEGORY_NAMES = frozenset(
    {
        *_PLUGIN_CATEGORIES,
        *_MOD_CATEGORIES,
        "velocity",
        "bungeecord",
        "waterfall",
        "minestom",
    }
)


class ModrinthProvider(PluginCatalogProvider):
    name = "modrinth"

    async def search(
        self,
        query: str,
        *,
        project_type: str = "plugin",
        loader: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> PluginSearchPage:
        pt = (project_type or "").strip().lower()
        if pt == "mod":
            facet_type = _MOD_FACET
            facet_loaders = _MOD_LOADER_FACETS
            target_type = "mod"
        else:
            facet_type = _PLUGIN_FACET
            facet_loaders = _PLUGIN_LOADER_FACETS
            target_type = "plugin"

        # Single-platform tag filter: "?loader=paper" narrows the search to
        # projects published for that one platform. The loader token is
        # validated against a conservative charset so it can never inject
        # extra facet-syntax fragments; an invalid value is ignored.
        loader_token = (loader or "").strip().lower()
        if loader_token and re.fullmatch(r"[a-z0-9-]{1,50}", loader_token):
            facet_loaders = f'["categories:{loader_token}"]'

        params = {
            "query": query,
            "limit": str(limit),
            "offset": str(offset),
            "facets": f"[{facet_type},{facet_loaders}]",
        }
        data = await self._get_json("/search", params=params)
        hits = data.get("hits") or []
        results: list[PluginSearchResult] = []
        for hit in hits:
            project_types = hit.get("all_project_types") or [hit.get("project_type", "")]
            if target_type not in project_types:
                continue
            categories = [c for c in (hit.get("categories") or []) if c]
            results.append(
                PluginSearchResult(
                    project_id=hit.get("project_id", ""),
                    slug=hit.get("slug", ""),
                    title=hit.get("title", ""),
                    description=hit.get("description", ""),
                    author=hit.get("author", ""),
                    project_types=[t for t in project_types if t],
                    downloads=hit.get("downloads", 0),
                    follows=hit.get("follows", 0),
                    icon_url=hit.get("icon_url", ""),
                    latest_version_id=hit.get("latest_version", ""),
                    categories=categories,
                    loaders=[c for c in categories if c in _LOADER_CATEGORY_NAMES],
                    client_side=hit.get("client_side"),
                    server_side=hit.get("server_side"),
                    date_modified=hit.get("date_modified", ""),
                    color=hit.get("color"),
                ),
            )
        return PluginSearchPage(
            items=results,
            total_hits=int(data.get("total_hits", 0)),
            offset=offset,
            limit=limit,
        )

    async def get_project(self, project_id: str) -> PluginProject:
        data = await self._get_json(f"/project/{project_id}")
        author = data.get("author") or ""
        team_id = data.get("team")
        if not author and team_id:
            # Modrinth v2/v3 project payloads carry a team id instead of the
            # author; resolve the team's owner for the canonical author name.
            try:
                members = await self._get_json(f"/team/{team_id}/members")
                if not isinstance(members, list):
                    members = []
                owner = next(
                    (m for m in members if m.get("role") == "Owner"),
                    (members or [{}])[0],
                )
                author = (owner.get("user") or {}).get("username", "")
            except (DownloadError, DownloadTimeoutError):
                author = ""
        return PluginProject(
            project_id=data.get("id", project_id),
            slug=data.get("slug", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            body=data.get("body", ""),
            author=author,
            project_types=data.get("all_project_types") or [data.get("project_type", "")],
            loaders=data.get("loaders") or [],
            game_versions=data.get("game_versions") or [],
            downloads=data.get("downloads", 0),
            follows=data.get("follows", 0),
            icon_url=data.get("icon_url", ""),
            wiki_url=data.get("wiki_url"),
            source_url=data.get("source_url"),
            client_side=data.get("client_side"),
            server_side=data.get("server_side"),
        )

    async def get_project_versions(
        self,
        project_id: str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> PluginVersionsPage:
        data = await self._get_json(f"/project/{project_id}/version")
        all_versions = [self._parse_version(v) for v in data]
        if limit is None:
            return PluginVersionsPage(items=all_versions, total=len(all_versions))
        return PluginVersionsPage(
            items=all_versions[offset : offset + limit],
            total=len(all_versions),
        )

    async def get_version(self, version_id: str) -> PluginVersionInfo:
        data = await self._get_json(f"/version/{version_id}")
        return self._parse_version(data)

    async def download(
        self,
        url: str,
        expected_sha1: str | None = None,
        expected_sha512: str | None = None,
    ) -> bytes:
        client = get_http_client()
        last_exception: Exception | None = None
        for attempt in range(MODRINTH_MAX_RETRIES + 1):
            try:
                content = await self._do_download(client, url)
                break
            except (DownloadError, DownloadTimeoutError) as e:
                last_exception = e
                if attempt < MODRINTH_MAX_RETRIES:
                    wait = 1.0 * (2**attempt)
                    logger.warning(
                        "Modrinth download attempt %d failed for %s, retrying in %.1fs",
                        attempt + 1,
                        url,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                raise
        else:
            raise last_exception  # type: ignore[misc]

        self._verify_checksum(url, content, expected_sha1, expected_sha512)
        return content

    @staticmethod
    async def _do_download(client, url: str) -> bytes:
        try:
            async with client.get(url) as resp:
                if resp.status != 200:
                    raise DownloadError(url, resp.status)
                buffer = bytearray()
                while True:
                    chunk = await resp.content.read(8192)
                    if not chunk:
                        break
                    buffer.extend(chunk)
                return bytes(buffer)
        except TimeoutError as e:
            raise DownloadTimeoutError(url, MODRINTH_TIMEOUT_SECONDS) from e
        except (DownloadError, DownloadTimeoutError):
            raise
        except Exception as e:
            raise DownloadError(url, 0, str(e)) from e

    @staticmethod
    def _verify_checksum(
        url: str,
        content: bytes,
        expected_sha1: str | None,
        expected_sha512: str | None,
    ) -> None:
        if expected_sha1:
            actual = hashlib.sha1(content).hexdigest()
            if actual.lower() != expected_sha1.lower():
                raise CorruptedDownloadError(
                    url,
                    f"sha1 mismatch: expected {expected_sha1}, got {actual}",
                )
        if expected_sha512:
            actual = hashlib.sha512(content).hexdigest()
            if actual.lower() != expected_sha512.lower():
                raise CorruptedDownloadError(
                    url,
                    f"sha512 mismatch: expected {expected_sha512}, got {actual}",
                )

    async def _get_json(self, path: str, params: dict | None = None) -> dict:
        client = get_http_client()
        url = f"{MODRINTH_API_BASE}{path}"
        last_exception: Exception | None = None
        for attempt in range(MODRINTH_MAX_RETRIES + 1):
            try:
                return await self._do_get_json(client, url, params)
            except (DownloadError, DownloadTimeoutError) as e:
                last_exception = e
                if attempt < MODRINTH_MAX_RETRIES:
                    wait = 1.0 * (2**attempt)
                    logger.warning(
                        "Modrinth API attempt %d failed for %s, retrying in %.1fs",
                        attempt + 1,
                        url,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                raise
        raise last_exception  # type: ignore[misc]

    @staticmethod
    async def _do_get_json(client, url: str, params: dict | None) -> dict:
        try:
            async with client.get(url, params=params) as resp:
                if resp.status != 200:
                    raise DownloadError(url, resp.status)
                return await resp.json()
        except TimeoutError as e:
            raise DownloadTimeoutError(url, MODRINTH_TIMEOUT_SECONDS) from e
        except (DownloadError, DownloadTimeoutError):
            raise
        except Exception as e:
            raise DownloadError(url, 0, str(e)) from e

    @staticmethod
    def _parse_version(data: dict) -> PluginVersionInfo:
        files: list[PluginFile] = []
        for f in data.get("files") or []:
            hashes = f.get("hashes") or {}
            files.append(
                PluginFile(
                    url=f.get("url", ""),
                    filename=f.get("filename", ""),
                    size_bytes=f.get("size", 0),
                    sha1=hashes.get("sha1", ""),
                    sha512=hashes.get("sha512", ""),
                    primary=bool(f.get("primary", False)),
                ),
            )
        deps = [
            d.get("project_id", "") for d in (data.get("dependencies") or []) if d.get("project_id")
        ]
        return PluginVersionInfo(
            version_id=data.get("id", ""),
            project_id=data.get("project_id", ""),
            name=data.get("name", ""),
            version_number=data.get("version_number", ""),
            game_versions=data.get("game_versions") or [],
            loaders=data.get("loaders") or [],
            files=files,
            dependencies=deps,
            date_published=data.get("date_published", ""),
        )
