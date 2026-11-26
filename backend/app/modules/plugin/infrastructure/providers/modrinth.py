from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

try:
    import aiohttp
except ImportError:  # pragma: no cover
    aiohttp = None  # type: ignore[assignment]

from app.core.exceptions import (
    CorruptedDownloadError,
    DownloadError,
    DownloadTimeoutError,
    ValidationError,
)
from app.core.http_client import get_http_client
from app.core.version import get_app_version
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
MODRINTH_DOWNLOAD_READ_TIMEOUT_SECONDS: int = 60
MODRINTH_MAX_RETRIES: int = 2
MODRINTH_BATCH_CHUNK_SIZE: int = 200
MODRINTH_BATCH_MAX_RETRIES: int = 3
MODRINTH_MAX_RATELIMIT_SLEEP_SECONDS: float = 60.0
MODRINTH_CACHE_MAX_ENTRIES: int = 256
MODRINTH_SEARCH_TTL_SECONDS: float = 120.0
MODRINTH_PROJECT_TTL_SECONDS: float = 300.0
VALID_SORT_OPTIONS = frozenset({"relevance", "downloads", "follows", "newest", "updated"})
_GAME_VERSION_RE = re.compile(r"\A[A-Za-z0-9._+-]{1,32}\Z")
_CACHE_LOCK = threading.Lock()
_TTL_CACHE: OrderedDict[tuple[str, tuple[tuple[str, str], ...]], tuple[float, Any]] = OrderedDict()
_SHARED_RATELIMIT_NOT_BEFORE: float = 0.0
_DOWNLOAD_RETRYABLE_STATUS_CODES = frozenset({0, 429, 500, 502, 503, 504})
_RANGE_INITIAL_BYTES: int = 64 * 1024
_RANGE_CONCURRENCY: int = 6
_RANGE_MAX_PART_BYTES: int = 512 * 1024
_MAX_PLUGIN_DOWNLOAD_BYTES: int = 256 * 1024 * 1024
_CONTENT_RANGE_RE = re.compile(r"\Abytes\s+(\d+)-(\d+)/(\d+)\Z", re.IGNORECASE)
_DOWNLOAD_STREAM_TIMEOUT = (
    aiohttp.ClientTimeout(
        total=None,
        connect=MODRINTH_TIMEOUT_SECONDS,
        sock_connect=MODRINTH_TIMEOUT_SECONDS,
        sock_read=MODRINTH_DOWNLOAD_READ_TIMEOUT_SECONDS,
    )
    if aiohttp is not None
    else None
)

_SHA512_RE = re.compile(r"\A[0-9a-f]{128}\Z")
_SHA1_RE = re.compile(r"\A[0-9a-f]{40}\Z")


@dataclass(frozen=True)
class ModrinthDependency:
    version_id: str | None
    project_id: str | None
    file_name: str | None
    dependency_type: str


@dataclass(frozen=True)
class ModrinthVersionRecord:
    version_id: str
    project_id: str
    name: str
    version_number: str
    version_type: str
    game_versions: tuple[str, ...]
    loaders: tuple[str, ...]
    environment: str | None
    files: tuple[PluginFile, ...]
    dependencies: tuple[ModrinthDependency, ...]
    date_published: str = ""


@dataclass(frozen=True)
class ModrinthProjectMeta:
    project_id: str
    slug: str
    title: str
    project_type: str
    client_side: str | None
    server_side: str | None
    loaders: tuple[str, ...]
    game_versions: tuple[str, ...]

_PLUGIN_CATEGORIES = (
    "bukkit",
    "paper",
    "purpur",
    "spigot",
    "folia",
    "velocity",
    "bungeecord",
    "waterfall",
    "minestom",
)
_PLUGIN_FACET = '["project_type:plugin"]'
_PLUGIN_LOADER_FACETS = (
    '["categories:bukkit","categories:paper","categories:purpur","categories:spigot",'
    '"categories:folia","categories:velocity","categories:bungeecord",'
    '"categories:waterfall","categories:minestom"]'
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

    @classmethod
    def clear_cache(cls) -> None:
        """Clear the in-memory Modrinth response cache and rate-limit cooldown."""
        global _SHARED_RATELIMIT_NOT_BEFORE
        with _CACHE_LOCK:
            _TTL_CACHE.clear()
            _SHARED_RATELIMIT_NOT_BEFORE = 0.0

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

        # Platform tag filter: expand compatible server loaders into an OR facet
        # (e.g. purpur -> purpur|paper|spigot|bukkit) strictly within the requested
        # project_type family so project_type=plugin&loader=fabric never leaks mods.
        allowed_family_loaders = (
            set(_MOD_CATEGORIES) if target_type == "mod" else set(_PLUGIN_CATEGORIES)
        )
        loader_token = (loader or "").strip().lower()
        if loader_token and re.fullmatch(r"[a-z0-9-]{1,50}", loader_token):
            from app.modules.plugin.application.services.version_selector import (
                compatible_loaders_for_server,
            )

            compat_loaders = [
                ldr
                for ldr in compatible_loaders_for_server(loader_token)
                if re.fullmatch(r"[a-z0-9-]{1,50}", ldr) and ldr in allowed_family_loaders
            ]
            if not compat_loaders:
                return PluginSearchPage(items=[], total_hits=0, offset=offset, limit=limit)
            facet_loaders = (
                "[" + ",".join(f'"categories:{ldr}"' for ldr in compat_loaders) + "]"
            )

        facet_groups = [facet_type, facet_loaders]
        gv_token = (game_version or "").strip()
        if gv_token and _GAME_VERSION_RE.fullmatch(gv_token):
            facet_groups.append(f'["versions:{gv_token}"]')

        sort_token = (sort or "relevance").strip().lower()
        if sort_token not in VALID_SORT_OPTIONS:
            sort_token = "relevance"

        params = {
            "query": query,
            "limit": str(limit),
            "offset": str(offset),
            "index": sort_token,
            "facets": f"[{','.join(facet_groups)}]",
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
        raw_total = int(data.get("total_hits", 0))
        adjusted_total = len(results) if raw_total <= len(hits) else raw_total
        return PluginSearchPage(
            items=results,
            total_hits=adjusted_total,
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
        raw_followers = data.get("followers")
        follows = (
            int(raw_followers)
            if raw_followers is not None
            else int(data.get("follows", 0) or 0)
        )
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
            follows=follows,
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
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme.lower() != "https" or not (
            host == "modrinth.com" or host.endswith(".modrinth.com")
        ):
            raise DownloadError(
                url,
                0,
                f"Untrusted download URL: host '{host}' is not a valid Modrinth domain",
            )
        client = get_http_client()
        last_exception: Exception | None = None
        for attempt in range(MODRINTH_MAX_RETRIES + 1):
            try:
                content = await self._do_download(client, url)
                break
            except (DownloadError, DownloadTimeoutError) as e:
                if (
                    isinstance(e, DownloadError)
                    and e.status not in _DOWNLOAD_RETRYABLE_STATUS_CODES
                ):
                    raise
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
    async def _read_response_bytes(resp: Any, url: str) -> bytes:
        buffer = bytearray()
        while True:
            chunk = await resp.content.read(65536)
            if not chunk:
                break
            if len(buffer) + len(chunk) > _MAX_PLUGIN_DOWNLOAD_BYTES:
                raise DownloadError(
                    url,
                    0,
                    f"Download exceeded maximum allowed size ({_MAX_PLUGIN_DOWNLOAD_BYTES} bytes)",
                )
            buffer.extend(chunk)
        return bytes(buffer)

    @classmethod
    async def _download_range_part(
        cls,
        client: Any,
        url: str,
        start: int,
        end: int,
        semaphore: asyncio.Semaphore,
    ) -> bytes:
        expected_len = end - start + 1
        last_exc: Exception | None = None
        async with semaphore:
            for attempt in range(MODRINTH_MAX_RETRIES + 1):
                try:
                    kwargs: dict[str, Any] = {
                        "headers": {"Range": f"bytes={start}-{end}"},
                    }
                    if _DOWNLOAD_STREAM_TIMEOUT is not None:
                        kwargs["timeout"] = _DOWNLOAD_STREAM_TIMEOUT
                    async with client.get(url, **kwargs) as resp:
                        if resp.status not in (200, 206):
                            raise DownloadError(url, resp.status)
                        data = await cls._read_response_bytes(resp, url)
                        if resp.status == 200 and len(data) >= end + 1:
                            return data[start : end + 1]
                        if len(data) != expected_len:
                            raise DownloadError(
                                url,
                                0,
                                f"Incomplete byte range {start}-{end}: got {len(data)} bytes",
                            )
                        return data
                except TimeoutError as e:
                    last_exc = DownloadTimeoutError(
                        url, MODRINTH_DOWNLOAD_READ_TIMEOUT_SECONDS
                    )
                    last_exc.__cause__ = e
                except (DownloadError, DownloadTimeoutError) as e:
                    if (
                        isinstance(e, DownloadError)
                        and e.status not in _DOWNLOAD_RETRYABLE_STATUS_CODES
                    ):
                        raise
                    last_exc = e
                except Exception as e:
                    last_exc = DownloadError(url, 0, str(e))
                    last_exc.__cause__ = e
                if attempt < MODRINTH_MAX_RETRIES:
                    await asyncio.sleep(0.5 * (2**attempt))
            assert last_exc is not None
            raise last_exc

    @classmethod
    async def _do_download(cls, client: Any, url: str) -> bytes:
        try:
            if aiohttp is None or not isinstance(client, aiohttp.ClientSession):
                async with client.get(url) as resp:
                    if resp.status != 200:
                        raise DownloadError(url, resp.status)
                    return await cls._read_response_bytes(resp, url)

            probe_kwargs: dict[str, Any] = {
                "headers": {"Range": f"bytes=0-{_RANGE_INITIAL_BYTES - 1}"},
            }
            if _DOWNLOAD_STREAM_TIMEOUT is not None:
                probe_kwargs["timeout"] = _DOWNLOAD_STREAM_TIMEOUT

            async with client.get(url, **probe_kwargs) as resp:
                if resp.status == 200:
                    return await cls._read_response_bytes(resp, url)
                if resp.status == 416:
                    plain_kwargs = (
                        {"timeout": _DOWNLOAD_STREAM_TIMEOUT}
                        if _DOWNLOAD_STREAM_TIMEOUT is not None
                        else {}
                    )
                    async with client.get(url, **plain_kwargs) as plain_resp:
                        if plain_resp.status != 200:
                            raise DownloadError(url, plain_resp.status)
                        return await cls._read_response_bytes(plain_resp, url)
                if resp.status != 206:
                    raise DownloadError(url, resp.status)

                cr_raw = ""
                if hasattr(resp, "headers") and resp.headers is not None:
                    cr_raw = str(resp.headers.get("Content-Range") or "").strip()
                first_bytes = await cls._read_response_bytes(resp, url)

            m = _CONTENT_RANGE_RE.match(cr_raw)
            if not m:
                plain_kwargs = (
                    {"timeout": _DOWNLOAD_STREAM_TIMEOUT}
                    if _DOWNLOAD_STREAM_TIMEOUT is not None
                    else {}
                )
                async with client.get(url, **plain_kwargs) as plain_resp:
                    if plain_resp.status != 200:
                        raise DownloadError(url, plain_resp.status)
                    return await cls._read_response_bytes(plain_resp, url)

            start, end, total = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if (
                start != 0
                or total <= 0
                or total > _MAX_PLUGIN_DOWNLOAD_BYTES
                or end >= total
                or len(first_bytes) != (end - start + 1)
            ):
                raise DownloadError(url, 0, f"Malformed Content-Range header: {cr_raw!r}")

            if end + 1 >= total:
                return first_bytes

            remaining = total - (end + 1)
            per_worker = (remaining + _RANGE_CONCURRENCY - 1) // _RANGE_CONCURRENCY
            part_size = max(
                _RANGE_INITIAL_BYTES,
                min(_RANGE_MAX_PART_BYTES, per_worker),
            )
            ranges: list[tuple[int, int]] = []
            offset = end + 1
            while offset < total:
                part_end = min(total - 1, offset + part_size - 1)
                ranges.append((offset, part_end))
                offset = part_end + 1

            semaphore = asyncio.Semaphore(_RANGE_CONCURRENCY)
            parts = await asyncio.gather(
                *[
                    cls._download_range_part(client, url, r_start, r_end, semaphore)
                    for r_start, r_end in ranges
                ]
            )

            out = bytearray(total)
            out[0 : len(first_bytes)] = first_bytes
            for (r_start, r_end), part_bytes in zip(ranges, parts, strict=True):
                out[r_start : r_end + 1] = part_bytes
            return bytes(out)
        except TimeoutError as e:
            raise DownloadTimeoutError(url, MODRINTH_DOWNLOAD_READ_TIMEOUT_SECONDS) from e
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
        global _SHARED_RATELIMIT_NOT_BEFORE
        cache_key = (
            path,
            tuple(sorted((str(k), str(v)) for k, v in (params or {}).items())),
        )
        now = time.monotonic()
        cached_value = None
        with _CACHE_LOCK:
            cached = _TTL_CACHE.get(cache_key)
            if cached is not None:
                expires_at, val = cached
                if expires_at > now:
                    _TTL_CACHE.move_to_end(cache_key)
                    cached_value = val
                else:
                    _TTL_CACHE.pop(cache_key, None)
        if cached_value is not None:
            return copy.deepcopy(cached_value)

        client = get_http_client()
        url = f"{MODRINTH_API_BASE}{path}"
        last_exception: Exception | None = None
        for attempt in range(MODRINTH_MAX_RETRIES + 1):
            if attempt == 0:
                with _CACHE_LOCK:
                    not_before = max(self._ratelimit_not_before, _SHARED_RATELIMIT_NOT_BEFORE)
                cooldown = not_before - time.monotonic()
                if cooldown > 0:
                    await asyncio.sleep(min(cooldown, MODRINTH_MAX_RATELIMIT_SLEEP_SECONDS))

            try:
                result = await self._do_get_json(client, url, params)
                ttl = (
                    MODRINTH_SEARCH_TTL_SECONDS
                    if path == "/search"
                    else MODRINTH_PROJECT_TTL_SECONDS
                )
                stored_copy = copy.deepcopy(result)
                with _CACHE_LOCK:
                    _TTL_CACHE[cache_key] = (time.monotonic() + ttl, stored_copy)
                    _TTL_CACHE.move_to_end(cache_key)
                    while len(_TTL_CACHE) > MODRINTH_CACHE_MAX_ENTRIES:
                        _TTL_CACHE.popitem(last=False)
                return result
            except (DownloadError, DownloadTimeoutError) as e:
                if isinstance(e, DownloadError) and e.status in (400, 404):
                    raise
                last_exception = e
                if attempt < MODRINTH_MAX_RETRIES:
                    base_wait = 1.0 * (2**attempt)
                    cooldown_until = 0.0
                    if isinstance(e, DownloadError) and e.status == 429:
                        hint = e.details.get("retry_after") or e.details.get("ratelimit_reset") or 0
                        wait = min(
                            max(float(hint), base_wait),
                            MODRINTH_MAX_RATELIMIT_SLEEP_SECONDS,
                        )
                        cooldown_until = time.monotonic() + wait
                        with _CACHE_LOCK:
                            _SHARED_RATELIMIT_NOT_BEFORE = max(
                                _SHARED_RATELIMIT_NOT_BEFORE, cooldown_until
                            )
                    else:
                        wait = min(base_wait, MODRINTH_MAX_RATELIMIT_SLEEP_SECONDS)
                    logger.warning(
                        "Modrinth API attempt %d failed for %s, retrying in %.1fs",
                        attempt + 1,
                        url,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    if cooldown_until:
                        with _CACHE_LOCK:
                            if cooldown_until == _SHARED_RATELIMIT_NOT_BEFORE:
                                _SHARED_RATELIMIT_NOT_BEFORE = 0.0
                    continue
                raise
        raise last_exception  # type: ignore[misc]

    @staticmethod
    async def _do_get_json(client, url: str, params: dict | None) -> dict:
        global _SHARED_RATELIMIT_NOT_BEFORE
        try:
            req_kwargs: dict[str, Any] = {"params": params}
            if aiohttp is not None and isinstance(client, aiohttp.ClientSession):
                req_kwargs["headers"] = {"User-Agent": f"onx-manager/{get_app_version()}"}
            async with client.get(url, **req_kwargs) as resp:
                resp_headers = getattr(resp, "headers", None)
                remaining = (
                    ModrinthProvider._int_header(resp_headers, "X-Ratelimit-Remaining")
                    if resp_headers is not None
                    else None
                )
                reset = (
                    ModrinthProvider._int_header(resp_headers, "X-Ratelimit-Reset")
                    if resp_headers is not None
                    else None
                )
                if resp.status == 429:
                    retry_after = (
                        ModrinthProvider._int_header(resp_headers, "Retry-After")
                        if resp_headers is not None
                        else None
                    )
                    err = DownloadError(url, 429, "Modrinth rate limit exceeded")
                    if retry_after is not None:
                        err.details["retry_after"] = retry_after
                    if reset is not None:
                        err.details["ratelimit_reset"] = reset
                    raise err
                if resp.status != 200:
                    raise DownloadError(url, resp.status)
                data = await resp.json()
                if (
                    remaining is not None
                    and remaining <= 0
                    and reset is not None
                    and reset > 0
                ):
                    cooldown_until = time.monotonic() + min(
                        float(reset),
                        MODRINTH_MAX_RATELIMIT_SLEEP_SECONDS,
                    )
                    with _CACHE_LOCK:
                        _SHARED_RATELIMIT_NOT_BEFORE = max(
                            _SHARED_RATELIMIT_NOT_BEFORE,
                            cooldown_until,
                        )
                return data
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
        deps: list[str] = []
        req_deps: list[str] = []
        seen_req: set[str] = set()
        for d in data.get("dependencies") or []:
            if not isinstance(d, dict):
                continue
            pid = d.get("project_id")
            if not pid:
                continue
            pid_str = str(pid)
            deps.append(pid_str)
            dep_type = str(d.get("dependency_type") or "required").strip().lower()
            if dep_type == "required" and pid_str not in seen_req:
                seen_req.add(pid_str)
                req_deps.append(pid_str)
        raw_changelog = data.get("changelog")
        changelog = raw_changelog if isinstance(raw_changelog, str) else None
        return PluginVersionInfo(
            version_id=data.get("id", ""),
            project_id=data.get("project_id", ""),
            name=data.get("name", ""),
            version_number=data.get("version_number", ""),
            game_versions=data.get("game_versions") or [],
            loaders=data.get("loaders") or [],
            files=files,
            dependencies=deps,
            required_dependencies=req_deps,
            changelog=changelog,
            date_published=data.get("date_published", ""),
            version_type=(str(data.get("version_type") or "release").strip().lower() or "release"),
        )

    # ------------------------------------------------------------------
    # P5.5 hash-only batch identification (additive; no slug guessing)
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        self._ratelimit_not_before: float = 0.0

    @staticmethod
    def _header_value(headers, name: str) -> str | None:
        try:
            value = headers.get(name)
            if value is None:
                value = headers.get(name.lower())
        except AttributeError:
            return None
        return str(value) if value is not None else None

    @classmethod
    def _int_header(cls, headers, name: str) -> int | None:
        value = cls._header_value(headers, name)
        if value is None:
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _chunks(values: Sequence[str]) -> list[list[str]]:
        return [
            list(values[index : index + MODRINTH_BATCH_CHUNK_SIZE])
            for index in range(0, len(values), MODRINTH_BATCH_CHUNK_SIZE)
        ]

    @staticmethod
    def _dedupe(values: Sequence[str]) -> list[str]:
        return list(dict.fromkeys(values))

    async def _request_json_with_ratelimit(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
        max_retries: int = MODRINTH_BATCH_MAX_RETRIES,
    ) -> object:
        """Rate-limit-aware JSON request helper for batch endpoints."""
        global _SHARED_RATELIMIT_NOT_BEFORE
        url = f"{MODRINTH_API_BASE}{path}"
        client = get_http_client()
        headers = {"User-Agent": f"onx-manager/{get_app_version()}"}
        attempt = 0

        while True:
            if attempt == 0:
                with _CACHE_LOCK:
                    not_before = max(self._ratelimit_not_before, _SHARED_RATELIMIT_NOT_BEFORE)
                cooldown = not_before - time.monotonic()
                if cooldown > 0:
                    await asyncio.sleep(min(cooldown, MODRINTH_MAX_RATELIMIT_SLEEP_SECONDS))

            try:
                async with client.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=headers,
                ) as resp:
                    status = int(resp.status)
                    remaining = self._int_header(resp.headers, "X-Ratelimit-Remaining")
                    reset = self._int_header(resp.headers, "X-Ratelimit-Reset")

                    if status == 429:
                        retry_after = self._int_header(resp.headers, "Retry-After")
                        if attempt >= max_retries:
                            raise DownloadError(
                                url, 429, "Modrinth rate limit exceeded"
                            )
                        base_wait = max(float(retry_after or reset or 0), 1.0 * (2**attempt))
                        wait_s = min(base_wait, MODRINTH_MAX_RATELIMIT_SLEEP_SECONDS)
                        cooldown_until = time.monotonic() + wait_s
                        self._ratelimit_not_before = max(self._ratelimit_not_before, cooldown_until)
                        with _CACHE_LOCK:
                            _SHARED_RATELIMIT_NOT_BEFORE = max(
                                _SHARED_RATELIMIT_NOT_BEFORE,
                                cooldown_until,
                            )
                        await asyncio.sleep(wait_s)
                        with _CACHE_LOCK:
                            if cooldown_until == _SHARED_RATELIMIT_NOT_BEFORE:
                                _SHARED_RATELIMIT_NOT_BEFORE = 0.0
                        if self._ratelimit_not_before == cooldown_until:
                            self._ratelimit_not_before = 0.0
                        attempt += 1
                        continue

                    if status in (400, 404):
                        raise DownloadError(url, status)

                    if status != 200:
                        if 500 <= status < 600 and attempt < max_retries:
                            await asyncio.sleep(
                                min(
                                    1.0 * (2**attempt),
                                    MODRINTH_MAX_RATELIMIT_SLEEP_SECONDS,
                                )
                            )
                            attempt += 1
                            continue
                        raise DownloadError(url, status)

                    data = await resp.json()
                    if (
                        remaining is not None
                        and remaining <= 0
                        and reset is not None
                        and reset > 0
                    ):
                        cooldown_until = time.monotonic() + min(
                            float(reset),
                            MODRINTH_MAX_RATELIMIT_SLEEP_SECONDS,
                        )
                        self._ratelimit_not_before = max(
                            self._ratelimit_not_before,
                            cooldown_until,
                        )
                        with _CACHE_LOCK:
                            _SHARED_RATELIMIT_NOT_BEFORE = max(
                                _SHARED_RATELIMIT_NOT_BEFORE,
                                cooldown_until,
                            )
                    return data
            except TimeoutError as exc:
                if attempt >= max_retries:
                    raise DownloadError(
                        url, 0, "Modrinth request timed out"
                    ) from exc
                await asyncio.sleep(
                    min(1.0 * (2**attempt), MODRINTH_MAX_RATELIMIT_SLEEP_SECONDS)
                )
                attempt += 1
            except DownloadError:
                raise
            except Exception as exc:  # noqa: BLE001 - normalized into DownloadError
                if attempt >= max_retries:
                    raise DownloadError(url, 0, str(exc)[:200]) from exc
                await asyncio.sleep(
                    min(1.0 * (2**attempt), MODRINTH_MAX_RATELIMIT_SLEEP_SECONDS)
                )
                attempt += 1

    @staticmethod
    def _validate_hashes(hashes: Sequence[str], algorithm: str) -> list[str]:
        if algorithm not in ("sha512", "sha1"):
            raise ValidationError(
                "Unsupported Modrinth hash algorithm",
                field="algorithm",
                details={"algorithm": str(algorithm)[:16]},
            )
        pattern = _SHA512_RE if algorithm == "sha512" else _SHA1_RE
        cleaned: list[str] = []
        for value in hashes:
            if not isinstance(value, str) or not pattern.match(value):
                raise ValidationError(
                    "Invalid Modrinth hash",
                    field="hashes",
                    details={"algorithm": algorithm},
                )
            cleaned.append(value)
        return list(dict.fromkeys(cleaned))

    def _version_record(self, data: dict) -> ModrinthVersionRecord:
        parsed = self._parse_version(data)
        environment = data.get("environment")
        if not isinstance(environment, str):
            environment = None
        dependencies: list[ModrinthDependency] = []
        for item in data.get("dependencies") or []:
            if not isinstance(item, dict):
                continue
            dependencies.append(
                ModrinthDependency(
                    version_id=item.get("version_id"),
                    project_id=item.get("project_id"),
                    file_name=item.get("file_name"),
                    dependency_type=str(item.get("dependency_type") or ""),
                )
            )
        return ModrinthVersionRecord(
            version_id=str(parsed.version_id),
            project_id=str(parsed.project_id),
            name=str(parsed.name),
            version_number=str(parsed.version_number),
            version_type=str(data.get("version_type") or ""),
            game_versions=tuple(parsed.game_versions),
            loaders=tuple(parsed.loaders),
            environment=environment,
            files=tuple(parsed.files),
            dependencies=tuple(dependencies),
            date_published=str(parsed.date_published),
        )

    @staticmethod
    def _project_meta(data: dict) -> ModrinthProjectMeta:
        return ModrinthProjectMeta(
            project_id=str(data.get("id") or ""),
            slug=str(data.get("slug") or ""),
            title=str(data.get("title") or ""),
            project_type=str(data.get("project_type") or ""),
            client_side=data.get("client_side"),
            server_side=data.get("server_side"),
            loaders=tuple(data.get("loaders") or ()),
            game_versions=tuple(data.get("game_versions") or ()),
        )

    async def lookup_version_files_by_hashes(
        self,
        hashes: Sequence[str],
        *,
        algorithm: str = "sha512",
    ) -> dict[str, ModrinthVersionRecord]:
        cleaned = self._validate_hashes(hashes, algorithm)
        result: dict[str, ModrinthVersionRecord] = {}
        for chunk in self._chunks(cleaned):
            payload = await self._request_json_with_ratelimit(
                "POST",
                "/version_files",
                json_body={"hashes": chunk, "algorithm": algorithm},
            )
            if not isinstance(payload, dict):
                continue
            for digest, version_data in payload.items():
                if (
                    isinstance(digest, str)
                    and digest in chunk
                    and isinstance(version_data, dict)
                ):
                    result[digest] = self._version_record(version_data)
        return result

    async def lookup_version_updates_by_hashes(
        self,
        hashes: Sequence[str],
        *,
        loaders: Sequence[str],
        game_versions: Sequence[str],
        algorithm: str = "sha512",
        version_types: Sequence[str] = ("release",),
    ) -> dict[str, ModrinthVersionRecord]:
        cleaned = self._validate_hashes(hashes, algorithm)
        result: dict[str, ModrinthVersionRecord] = {}
        for chunk in self._chunks(cleaned):
            payload = await self._request_json_with_ratelimit(
                "POST",
                "/version_files/update",
                json_body={
                    "hashes": chunk,
                    "algorithm": algorithm,
                    "loaders": list(loaders),
                    "game_versions": list(game_versions),
                    "version_types": list(version_types),
                },
            )
            if not isinstance(payload, dict):
                continue
            for digest, version_data in payload.items():
                if (
                    isinstance(digest, str)
                    and digest in chunk
                    and isinstance(version_data, dict)
                ):
                    result[digest] = self._version_record(version_data)
        return result

    async def get_versions_by_ids(
        self,
        version_ids: Sequence[str],
    ) -> dict[str, ModrinthVersionRecord]:
        cleaned = list(dict.fromkeys(str(value) for value in version_ids if value))
        result: dict[str, ModrinthVersionRecord] = {}
        for chunk in self._chunks(cleaned):
            payload = await self._request_json_with_ratelimit(
                "GET",
                "/versions",
                params={"ids": json.dumps(chunk)},
            )
            if not isinstance(payload, list):
                continue
            for item in payload:
                if isinstance(item, dict):
                    record = self._version_record(item)
                    if record.version_id:
                        result[record.version_id] = record
        return result

    async def get_projects_by_ids(
        self,
        project_ids: Sequence[str],
    ) -> dict[str, ModrinthProjectMeta]:
        cleaned = list(dict.fromkeys(str(value) for value in project_ids if value))
        result: dict[str, ModrinthProjectMeta] = {}
        for chunk in self._chunks(cleaned):
            payload = await self._request_json_with_ratelimit(
                "GET",
                "/projects",
                params={"ids": json.dumps(chunk)},
            )
            if not isinstance(payload, list):
                continue
            for item in payload:
                if isinstance(item, dict):
                    meta = self._project_meta(item)
                    if meta.project_id:
                        result[meta.project_id] = meta
        return result

    async def classify_client_only_jars_by_sha512(
        self,
        sha512_hashes: Sequence[str],
    ) -> tuple[
        set[str],
        dict[str, ModrinthVersionRecord],
        dict[str, ModrinthProjectMeta],
    ]:
        """Identify client-only jars strictly from Version.environment and /projects."""
        matched = await self.lookup_version_files_by_hashes(
            sha512_hashes, algorithm="sha512"
        )
        client_only: set[str] = set()
        project_ids: list[str] = []
        for digest, record in matched.items():
            if record.environment == "client_only":
                client_only.add(digest)
            elif (
                record.environment not in ("server_only", "client_and_server")
                and record.project_id
            ):
                project_ids.append(record.project_id)

        matched_projects = (
            await self.get_projects_by_ids(project_ids) if project_ids else {}
        )
        for digest, record in matched.items():
            if digest in client_only:
                continue
            project = matched_projects.get(record.project_id)
            if project is not None and project.server_side == "unsupported":
                client_only.add(digest)
        return client_only, matched, matched_projects
