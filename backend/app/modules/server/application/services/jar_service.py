from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import secrets
import string
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp

from app.core.exceptions import (
    CorruptedDownloadError,
    DownloadError,
    DownloadTimeoutError,
    UnsupportedForgeVersionError,
    VersionNotFoundError,
)
from app.modules.server.domain.runtime_exceptions import (
    BuildResolutionError,
    InstallerDownloadError,
    MetadataFetchError,
)
from app.modules.server.domain.value_objects import ServerDeployment
from app.modules.server.infrastructure.fs import FileSystem, local_fs
from app.modules.shared.value_objects import MinecraftVersion

logger = logging.getLogger(__name__)

METADATA_CACHE_TTL_SECONDS: float = 300.0


@dataclass
class _MetadataCacheEntry:
    entries: list[Any]
    timestamp: float


_METADATA_CACHE: dict[str, _MetadataCacheEntry] = {}


def _get_cached_metadata(provider: str) -> list[Any] | None:
    entry = _METADATA_CACHE.get(provider)
    if entry is not None and (time.monotonic() - entry.timestamp) < METADATA_CACHE_TTL_SECONDS:
        return entry.entries
    return None


def _set_cached_metadata(provider: str, entries: list[Any]) -> None:
    _METADATA_CACHE[provider] = _MetadataCacheEntry(entries=entries, timestamp=time.monotonic())


def clear_metadata_cache(provider: str | None = None) -> None:
    if provider:
        _METADATA_CACHE.pop(provider, None)
    else:
        _METADATA_CACHE.clear()


JAR_DOWNLOAD_SOCK_READ_TIMEOUT: int = 30
JAR_DOWNLOAD_CONNECT_TIMEOUT: int = 15
JAR_DOWNLOAD_TIMEOUT: int = 120  # backward-compatibility alias
JAR_MIN_SIZE_BYTES: int = 1_048_576
JAR_MAX_RETRIES: int = 2
JAR_MAGIC_BYTES: bytes = b"PK\x03\x04"

VANILLA_MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"

PAPER_PROJECT_URL = "https://fill.papermc.io/v3/projects/paper"
PAPER_BUILDS_URL = "https://fill.papermc.io/v3/projects/paper/versions/{version}/builds"

FABRIC_LOADER_URL = "https://meta.fabricmc.net/v2/versions/loader/{version}"

QUILT_GAME_VERSIONS_URL = "https://meta.quiltmc.org/v3/versions/game"
QUILT_LOADER_VERSIONS_URL = "https://meta.quiltmc.org/v3/versions/loader/{version}"
QUILT_SERVER_JSON_URL = (
    "https://meta.quiltmc.org/v3/versions/loader/{mc_version}/{loader_version}/server/json"
)

FORGE_MAVEN_METADATA_URL = (
    "https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml"
)

FORGE_MAVEN_BASE_URL = "https://maven.minecraftforge.net/net/minecraftforge/forge"

NEOFORGE_MAVEN_METADATA_URL = (
    "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml"
)
NEOFORGE_MAVEN_BASE_URL = "https://maven.neoforged.net/releases/net/neoforged/neoforge"
NEOFORGE_FORGE_MAVEN_METADATA_URL = (
    "https://maven.neoforged.net/releases/net/neoforged/forge/maven-metadata.xml"
)
NEOFORGE_FORGE_MAVEN_BASE_URL = "https://maven.neoforged.net/releases/net/neoforged/forge"

FORGE_INSTALLER_MIN_VERSION = MinecraftVersion(1, 17, 1)
FORGE_MIN_SUPPORTED_VERSION = MinecraftVersion(1, 17, 1)
FORGE_MAX_SUPPORTED_VERSION = MinecraftVersion(1, 20, 1)
NEOFORGE_INSTALLER_MIN_VERSION = MinecraftVersion(1, 17, 0)

SOFTWARE_METADATA: dict[str, dict] = {
    "vanilla": {
        "name": "Vanilla",
        "description": "The official Minecraft server from Mojang.",
        "url": "https://minecraft.net",
        "supports_versions": True,
    },
    "paper": {
        "name": "Paper",
        "description": "High-performance fork of Spigot with extensive optimizations and API.",
        "url": "https://papermc.io",
        "supports_versions": True,
    },
    "purpur": {
        "name": "Purpur",
        "description": "Fork of Paper with more configuration options and features.",
        "url": "https://purpurmc.org",
        "supports_versions": True,
    },
    "fabric": {
        "name": "Fabric",
        "description": "Lightweight modding toolchain for Minecraft.",
        "url": "https://fabricmc.net",
        "supports_versions": True,
    },
    "forge": {
        "name": "Forge",
        "description": "The original Minecraft modding API. Requires manual JAR installation.",
        "url": "https://minecraftforge.net",
        "supports_versions": True,
        "needs_manual_install": True,
    },
    "neoforge": {
        "name": "NeoForge",
        "description": "Community-driven fork of Forge for modern Minecraft versions.",
        "url": "https://neoforged.net",
        "supports_versions": True,
        "needs_manual_install": True,
    },
    "quilt": {
        "name": "Quilt",
        "description": "Open modding toolchain for Minecraft with a generated argfile launch.",
        "url": "https://quiltmc.org",
        "supports_versions": True,
        "needs_manual_install": True,
    },
    "spigot": {
        "name": "Spigot",
        "description": "Most widely-used Minecraft server software with plugin support.",
        "url": "https://spigotmc.org",
        "supports_versions": True,
    },
    "bukkit": {
        "name": "Bukkit",
        "description": "Original plugin API for Minecraft servers.",
        "url": "https://bukkit.org",
        "supports_versions": True,
    },
}

SERVER_TYPES_REQUIRING_MANUAL_INSTALL: set[str] = {"forge", "neoforge", "quilt"}


def _slugify(text: str) -> str:
    """Lowercase, strip non-alphanumeric (unicode-aware), collapse whitespace to hyphens."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = text.replace("_", "-")
    text = re.sub(r"[\s-]+", "-", text)
    text = text.strip("-")
    return text or "server"


def server_dir_name(name: str, server_id: str) -> str:
    """Human-readable directory name: <slug>-<first-8-of-uuid>."""
    return f"{_slugify(name)}-{server_id[:8]}"


def _default_data_dir() -> Path:
    from app.core.config import AppSettings

    return Path(AppSettings().servers_data_dir)


def server_dir(server_id: str) -> Path:
    return _default_data_dir() / server_id


def resolve_server_dir(
    server_id: str,
    name: str | None = None,
    deployment: ServerDeployment | None = None,
) -> str:
    if deployment and deployment.root_path:
        return deployment.server_directory()
    if name:
        return str(_default_data_dir() / server_dir_name(name, server_id))
    return str(server_dir(server_id))


def jar_path(server_id: str) -> Path:
    return server_dir(server_id) / "server.jar"


def properties_path(server_id: str) -> Path:
    return server_dir(server_id) / "server.properties"


def eula_path(server_id: str) -> Path:
    return server_dir(server_id) / "eula.txt"


async def fetch_vanilla_versions() -> list[str]:
    try:
        async with aiohttp.ClientSession() as session, session.get(
            VANILLA_MANIFEST_URL, timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            versions = data.get("versions", [])
            return [v["id"] for v in versions if v["type"] == "release"]
    except (TimeoutError, aiohttp.ClientError, ValueError):
        return []


async def fetch_paper_versions() -> list[str]:
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(PAPER_PROJECT_URL, timeout=aiohttp.ClientTimeout(total=15)) as resp,
        ):
            if resp.status != 200:
                return []
            data = await resp.json()
            groups = data.get("versions", {})
            versions: list[str] = []
            seen: set[str] = set()
            for group in groups.values():
                for vid in group:
                    if vid not in seen:
                        seen.add(vid)
                        versions.append(vid)
            return versions
    except (TimeoutError, aiohttp.ClientError, ValueError):
        return []


async def fetch_purpur_versions() -> list[str]:
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(
                "https://api.purpurmc.org/v2/purpur", timeout=aiohttp.ClientTimeout(total=15)
            ) as resp,
        ):
            if resp.status != 200:
                return []
            data = await resp.json()
            return data.get("versions", [])[::-1]
    except (TimeoutError, aiohttp.ClientError, ValueError):
        return []


async def fetch_fabric_versions() -> list[str]:
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(
                "https://meta.fabricmc.net/v2/versions/game",
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp,
        ):
            if resp.status != 200:
                return []
            data = await resp.json()
            return [v["version"] for v in data if v.get("stable")]
    except (TimeoutError, aiohttp.ClientError, ValueError):
        return []


@dataclass(frozen=True)
class ForgeVersionEntry:
    minecraft: str
    build: tuple[int, ...]
    version: str


def _parse_forge_metadata(xml_text: str) -> list[ForgeVersionEntry]:
    entries: list[ForgeVersionEntry] = []
    for full in re.findall(r"<version>([^<]+)</version>", xml_text):
        mc, sep, build_part = full.partition("-")
        if not sep or not mc or not build_part:
            continue
        entries.append(
            ForgeVersionEntry(
                minecraft=mc,
                build=tuple(int(d) for d in re.findall(r"\d+", build_part)),
                version=full,
            ),
        )
    return entries


async def _fetch_xml_with_retries(url: str, max_retries: int = JAR_MAX_RETRIES) -> str:
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            async with (
                aiohttp.ClientSession() as session,
                session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp,
            ):
                if resp.status != 200:
                    raise DownloadError(url, resp.status, f"HTTP {resp.status}")
                return await resp.text()
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                wait = 1.0 * (2**attempt)
                logger.warning(
                    "Metadata fetch attempt %d failed for %s (%s: %s), retrying in %.1fs",
                    attempt + 1,
                    url,
                    type(exc).__name__,
                    exc,
                    wait,
                )
                await asyncio.sleep(wait)
                continue
            logger.error(
                "Metadata fetch permanently failed for %s (%s: %s) after %d attempts",
                url,
                type(exc).__name__,
                exc,
                max_retries + 1,
            )
            raise MetadataFetchError(
                detail=f"Failed to fetch metadata from {url}: {exc}",
                original_error=f"{type(exc).__name__}: {exc}",
            ) from exc
    raise MetadataFetchError(
        detail=f"Failed to fetch metadata from {url}: {last_exc}",
        original_error=f"{type(last_exc).__name__}: {last_exc}",
    )


async def _fetch_forge_metadata() -> list[ForgeVersionEntry]:
    xml_text = await _fetch_xml_with_retries(FORGE_MAVEN_METADATA_URL)
    return _parse_forge_metadata(xml_text)


def _is_real_forge_minecraft(mc: str) -> bool:
    """Whether ``mc`` is an actual Minecraft version.

    Forge's Maven metadata also carries its own unified artifact revisions
    (e.g. ``26.2-65.1.2``) whose first component is a Forge version number,
    not a Minecraft version. Every real Minecraft release is ``1.x``, so
    anything that does not parse with major==1 is excluded from version
    selection.
    """
    try:
        return MinecraftVersion.parse(mc).major == 1
    except ValueError:
        return False


def validate_forge_supported_version(minecraft_version: str) -> MinecraftVersion:
    """Validate the strict Forge supported range ``1.17.1 <= mc <= 1.20.1``."""
    try:
        parsed = MinecraftVersion.parse(minecraft_version)
    except ValueError as exc:
        raise UnsupportedForgeVersionError(minecraft_version=minecraft_version) from exc
    if parsed < FORGE_MIN_SUPPORTED_VERSION or parsed > FORGE_MAX_SUPPORTED_VERSION:
        raise UnsupportedForgeVersionError(minecraft_version=minecraft_version)
    return parsed


async def fetch_forge_versions() -> list[str]:
    """Latest Forge build available for each supported Minecraft version, newest-first.

    Forge publishes its artifacts to Maven; the server JAR is produced by an
    installer at install time, so the version list maps to Minecraft versions.
    Only the normative ``1.17.1 .. 1.20.1`` range is exposed (OD-v8.4-9).
    """
    cached = _get_cached_metadata("forge")
    if cached is not None:
        entries = cached
    else:
        try:
            entries = await _fetch_forge_metadata()
            _set_cached_metadata("forge", entries)
        except Exception as exc:
            logger.error("Failed to fetch Forge versions (%s: %s)", type(exc).__name__, exc)
            return []
    seen: set[str] = set()
    mc_versions: list[tuple[MinecraftVersion, str]] = []
    for entry in entries:
        if not _is_real_forge_minecraft(entry.minecraft):
            continue
        if entry.minecraft in seen:
            continue
        try:
            parsed = MinecraftVersion.parse(entry.minecraft)
        except ValueError:
            continue
        if parsed < FORGE_MIN_SUPPORTED_VERSION or parsed > FORGE_MAX_SUPPORTED_VERSION:
            continue
        seen.add(entry.minecraft)
        mc_versions.append((parsed, entry.minecraft))
    mc_versions.sort(key=lambda entry: entry[0], reverse=True)
    return [mc for _version, mc in mc_versions]


def forge_requires_installer(minecraft_version: str) -> bool:
    """Modern Forge (>= 1.17) needs the installer flow; legacy uses a plain jar."""
    try:
        return MinecraftVersion.parse(minecraft_version) >= FORGE_INSTALLER_MIN_VERSION
    except ValueError:
        return True


async def resolve_forge_build(
    minecraft_version: str,
    *,
    entries: list[ForgeVersionEntry] | None = None,
) -> str | None:
    """Return the full raw artifact version string (e.g. ``1.20.1-47.4.23``) for the
    highest numeric-tuple build matching ``minecraft_version``, or ``None``.

    Build numbers are compared as numeric tuples, never lexically (e.g.
    ``58.0.10`` must sort above ``58.0.2``). The returned string is the version
    exactly as it appeared in the metadata, not a reconstructed ``{mc}-{build}``
    concatenation — this preserves anomalies such as ``1.9-12.16.1.1938-1.9.0``.
    """
    if entries is None:
        cached = _get_cached_metadata("forge")
        if cached is not None:
            entries = cached
        else:
            try:
                entries = await _fetch_forge_metadata()
                _set_cached_metadata("forge", entries)
            except Exception as exc:
                raise BuildResolutionError(
                    detail=(
                        "Could not fetch Forge metadata for Minecraft "
                        f"{minecraft_version}: {exc}"
                    ),
                    underlying_fetch_failed=True,
                ) from exc
    best: ForgeVersionEntry | None = None
    for entry in entries:
        if not _is_real_forge_minecraft(entry.minecraft):
            continue
        if entry.minecraft != minecraft_version:
            continue
        if best is None or entry.build > best.build:
            best = entry
    return best.version if best is not None else None


def forge_universal_url(full_version: str) -> str:
    return f"{FORGE_MAVEN_BASE_URL}/{full_version}/forge-{full_version}-universal.jar"


def forge_installer_url(full_version: str) -> str:
    return f"{FORGE_MAVEN_BASE_URL}/{full_version}/forge-{full_version}-installer.jar"


@dataclass(frozen=True)
class NeoForgeVersionEntry:
    minecraft: str
    build: tuple[int, ...]
    version: str


def _parse_neoforge_metadata(
    xml_text: str, *, is_forge_artifact: bool = False
) -> list[NeoForgeVersionEntry]:
    entries: list[NeoForgeVersionEntry] = []
    for full in re.findall(r"<version>([^<]+)</version>", xml_text):
        if is_forge_artifact:
            mc, sep, build_part = full.partition("-")
            if not sep or not mc or not build_part:
                continue
            entries.append(
                NeoForgeVersionEntry(
                    minecraft=mc,
                    build=tuple(int(d) for d in re.findall(r"\d+", build_part)),
                    version=full,
                ),
            )
        else:
            if full.startswith("0."):
                continue
            parts = re.split(r"[.-]", full)
            if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
                continue
            maj, min_ = int(parts[0]), int(parts[1])
            if maj >= 26:
                mc = f"{maj}.{min_}"
            elif maj in (20, 21):
                mc = "1.21.0" if maj == 21 and min_ == 0 else f"1.{maj}.{min_}"
            else:
                continue
            entries.append(
                NeoForgeVersionEntry(
                    minecraft=mc,
                    build=tuple(int(d) for d in re.findall(r"\d+", full)),
                    version=full,
                ),
            )
    return entries


async def _fetch_neoforge_metadata() -> list[NeoForgeVersionEntry]:
    xml_text_neo = await _fetch_xml_with_retries(NEOFORGE_MAVEN_METADATA_URL)
    entries = _parse_neoforge_metadata(xml_text_neo, is_forge_artifact=False)
    try:
        xml_text_forge = await _fetch_xml_with_retries(NEOFORGE_FORGE_MAVEN_METADATA_URL)
        entries.extend(_parse_neoforge_metadata(xml_text_forge, is_forge_artifact=True))
    except Exception as exc:
        logger.warning(
            "Failed to fetch secondary NeoForge Forge metadata from %s (%s: %s)",
            NEOFORGE_FORGE_MAVEN_METADATA_URL,
            type(exc).__name__,
            exc,
        )
    return entries


def _is_real_neoforge_minecraft(mc: str) -> bool:
    """Whether ``mc`` is a valid NeoForge / Minecraft version."""
    try:
        parsed = MinecraftVersion.parse(mc)
        return parsed.major == 1 or parsed.major >= 20
    except ValueError:
        return False


async def fetch_neoforge_versions() -> list[str]:
    """Latest NeoForge build available for each Minecraft version, newest-first."""
    cached = _get_cached_metadata("neoforge")
    if cached is not None:
        entries = cached
    else:
        try:
            entries = await _fetch_neoforge_metadata()
            _set_cached_metadata("neoforge", entries)
        except Exception as exc:
            logger.error("Failed to fetch NeoForge versions (%s: %s)", type(exc).__name__, exc)
            return []
    seen: set[str] = set()
    mc_versions: list[tuple[MinecraftVersion, str]] = []
    for entry in entries:
        if not _is_real_neoforge_minecraft(entry.minecraft):
            continue
        if entry.minecraft in seen:
            continue
        seen.add(entry.minecraft)
        try:
            mc_versions.append((MinecraftVersion.parse(entry.minecraft), entry.minecraft))
        except ValueError:
            continue
    mc_versions.sort(key=lambda entry: entry[0], reverse=True)
    return [mc for _version, mc in mc_versions]


def neoforge_requires_installer(minecraft_version: str) -> bool:
    """Modern NeoForge (>= 1.17) needs the installer flow; legacy uses a plain jar."""
    try:
        return MinecraftVersion.parse(minecraft_version) >= NEOFORGE_INSTALLER_MIN_VERSION
    except ValueError:
        return True


async def resolve_neoforge_build(
    minecraft_version: str,
    *,
    entries: list[NeoForgeVersionEntry] | None = None,
) -> str | None:
    """Return the full raw artifact version string for the highest numeric-tuple build
    matching ``minecraft_version``, or ``None``.

    Build numbers are compared as numeric tuples, never lexically.
    """
    if entries is None:
        cached = _get_cached_metadata("neoforge")
        if cached is not None:
            entries = cached
        else:
            try:
                entries = await _fetch_neoforge_metadata()
                _set_cached_metadata("neoforge", entries)
            except Exception as exc:
                raise BuildResolutionError(
                    detail=(
                        "Could not fetch NeoForge metadata for Minecraft "
                        f"{minecraft_version}: {exc}"
                    ),
                    underlying_fetch_failed=True,
                ) from exc
    best: NeoForgeVersionEntry | None = None
    target = "1.21.0" if minecraft_version == "1.21" else minecraft_version
    for entry in entries:
        if not _is_real_neoforge_minecraft(entry.minecraft):
            continue
        if entry.minecraft != target and entry.minecraft != minecraft_version:
            continue
        if best is None or entry.build > best.build:
            best = entry
    return best.version if best is not None else None


def neoforge_universal_url(full_version: str) -> str:
    if full_version.startswith("1.20.1-"):
        return f"{NEOFORGE_FORGE_MAVEN_BASE_URL}/{full_version}/forge-{full_version}-universal.jar"
    return f"{NEOFORGE_MAVEN_BASE_URL}/{full_version}/neoforge-{full_version}-universal.jar"


def neoforge_installer_url(full_version: str) -> str:
    if full_version.startswith("1.20.1-"):
        return f"{NEOFORGE_FORGE_MAVEN_BASE_URL}/{full_version}/forge-{full_version}-installer.jar"
    return f"{NEOFORGE_MAVEN_BASE_URL}/{full_version}/neoforge-{full_version}-installer.jar"


async def fetch_spigot_versions() -> list[str]:
    return [
        "1.21.5",
        "1.21.4",
        "1.21.3",
        "1.21.1",
        "1.21",
        "1.20.6",
        "1.20.4",
        "1.20.2",
        "1.20.1",
        "1.20",
        "1.19.4",
        "1.19.3",
        "1.19.2",
        "1.19.1",
        "1.19",
    ]


async def fetch_bukkit_versions() -> list[str]:
    return await fetch_spigot_versions()


async def fetch_quilt_versions() -> list[str]:
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(
                QUILT_GAME_VERSIONS_URL,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp,
        ):
            if resp.status != 200:
                return []
            data = await resp.json()
            return [v["version"] for v in data if v.get("stable")]
    except (TimeoutError, aiohttp.ClientError, ValueError, KeyError, TypeError):
        return []


async def resolve_quilt_loader_version(minecraft_version: str) -> str | None:
    url = QUILT_LOADER_VERSIONS_URL.format(version=minecraft_version)
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp,
        ):
            if resp.status != 200:
                return None
            data = await resp.json()
            if not isinstance(data, list) or not data:
                return None
            loader = data[0].get("loader", {})
            version = loader.get("version")
            return str(version) if version else None
    except (TimeoutError, aiohttp.ClientError, ValueError, KeyError, TypeError):
        return None


VERSION_FETCHERS: dict[str, Callable[[], Awaitable[list[str]]]] = {
    "vanilla": fetch_vanilla_versions,
    "paper": fetch_paper_versions,
    "purpur": fetch_purpur_versions,
    "fabric": fetch_fabric_versions,
    "quilt": fetch_quilt_versions,
    "forge": fetch_forge_versions,
    "neoforge": fetch_neoforge_versions,
    "spigot": fetch_spigot_versions,
    "bukkit": fetch_bukkit_versions,
}


async def get_versions_for(server_type: str) -> list[str]:
    fetcher = VERSION_FETCHERS.get(server_type)
    if fetcher is None:
        return []
    return await fetcher()


def parse_server_dir_name(dirname: str) -> str | None:
    """Extract the server ID prefix from a directory name.

    Supports two formats:
    - Raw UUID: ``be193e92e2aa4728a0854cad9e37cca1`` → full ID
    - Slug+short-uuid: ``my-server-be193e92`` → ``be193e92`` (first 8 chars)

    Returns the extracted prefix (full ID or first 8 chars), or *None* if the
    name matches neither format.
    """
    if re.match(r"^[0-9a-f]{32}$", dirname):
        return dirname
    parts = dirname.split("-")
    if len(parts) > 1 and len(parts[-1]) == 8 and all(c in "0123456789abcdef" for c in parts[-1]):
        return parts[-1]
    return None


def _resolve_jar_dest(deployment: ServerDeployment | None, server_id: str | None) -> str:
    if deployment and deployment.root_path:
        return deployment.jar_path()
    return str(jar_path(server_id or "unknown"))


def _resolve_properties_dest(deployment: ServerDeployment | None, server_id: str | None) -> str:
    if deployment and deployment.root_path:
        return deployment.properties_path()
    return str(properties_path(server_id or "unknown"))


def _resolve_eula_dest(deployment: ServerDeployment | None, server_id: str | None) -> str:
    if deployment and deployment.root_path:
        return deployment.eula_path()
    return str(eula_path(server_id or "unknown"))


_JAR_MAGIC = b"PK\x03\x04"
_MIN_JAR_SIZE = 1_048_576


def validate_jar(path: str, fs: FileSystem | None = None) -> None:
    fs = fs or local_fs
    if not fs.exists(path):
        raise CorruptedDownloadError(path, "file not found")
    size = fs.size(path)
    if size < _MIN_JAR_SIZE:
        raise CorruptedDownloadError(
            path, f"file too small: {size} bytes (minimum {_MIN_JAR_SIZE})"
        )
    try:
        header = fs.read_binary(path)[:4]
    except OSError as e:
        raise CorruptedDownloadError(path, f"cannot read: {e}") from e
    if header != _JAR_MAGIC:
        raise CorruptedDownloadError(path, f"invalid ZIP/JAR header: {header.hex()!r}")


async def download_server_jar(
    server_id: str,
    server_type: str,
    minecraft_version: str,
    deployment: ServerDeployment | None = None,
    fs: FileSystem | None = None,
) -> str:
    fs = fs or local_fs
    dest = _resolve_jar_dest(deployment, server_id)
    parent = str(Path(dest).parent)

    if server_type == "forge":
        validate_forge_supported_version(minecraft_version)

    if server_type in SERVER_TYPES_REQUIRING_MANUAL_INSTALL:
        if server_type == "forge" and not forge_requires_installer(minecraft_version):
            # Legacy Forge (< 1.17.1) is outside the supported range; defensive only.
            pass
        elif server_type == "neoforge" and not neoforge_requires_installer(minecraft_version):
            # Legacy NeoForge (< 1.17) uses a plain universal jar — download it.
            pass
        else:
            fs.ensure_dir(parent)
            logger.info(
                "Server %s (%s %s) requires manual JAR installation at %s",
                server_id,
                server_type,
                minecraft_version,
                dest,
            )
            return dest

    jar_url = await _resolve_download_url_async(server_type, minecraft_version)
    fs.ensure_dir(parent)

    content: bytes | None = None
    for attempt in range(JAR_MAX_RETRIES + 1):
        try:
            content = await _do_download(jar_url, dest=dest)
        except (DownloadError, DownloadTimeoutError) as e:
            if attempt < JAR_MAX_RETRIES:
                wait = 1.0 * (2**attempt)
                logger.warning(
                    "Download attempt %d failed for %s (%s: %s), retrying in %.1fs",
                    attempt + 1,
                    jar_url,
                    type(e).__name__,
                    e,
                    wait,
                )
                await asyncio.sleep(wait)
                continue
            logger.error(
                "Download permanently failed for %s (%s: %s)",
                jar_url,
                type(e).__name__,
                e,
            )
            raise e
        else:
            break

    if content is not None:
        fs.write_binary_atomic(dest, content)
    fs.chmod(dest, 0o755)
    validate_jar(dest, fs)
    return dest


async def download_installer_jar(
    url: str,
    dest: str,
    fs: FileSystem | None = None,
) -> str:
    """Download an arbitrary server-related JAR (e.g. the Forge installer) to
    ``dest`` using the same timeout/retry/validation pattern as server JARs.
    """
    fs = fs or local_fs
    parent = str(Path(dest).parent)
    fs.ensure_dir(parent)

    content: bytes | None = None
    for attempt in range(JAR_MAX_RETRIES + 1):
        try:
            content = await _do_download(url, dest=dest)
        except (TimeoutError, DownloadError, DownloadTimeoutError) as exc:
            if attempt < JAR_MAX_RETRIES:
                wait = 1.0 * (2**attempt)
                logger.warning(
                    "Download attempt %d failed for %s (%s: %s), retrying in %.1fs",
                    attempt + 1,
                    url,
                    type(exc).__name__,
                    exc,
                    wait,
                )
                await asyncio.sleep(wait)
                continue
            logger.error(
                "Download permanently failed for %s (%s: %s)", url, type(exc).__name__, exc
            )
            raise InstallerDownloadError(
                detail=f"Download failed for {url}: {exc}", url=url
            ) from exc
        else:
            break

    if content is not None:
        fs.write_binary_atomic(dest, content)
    fs.chmod(dest, 0o755)
    validate_jar(dest, fs)
    return dest


async def _do_download(url: str, dest: str | None = None) -> bytes | None:
    timeout = aiohttp.ClientTimeout(
        total=None,
        connect=JAR_DOWNLOAD_CONNECT_TIMEOUT,
        sock_connect=JAR_DOWNLOAD_CONNECT_TIMEOUT,
        sock_read=JAR_DOWNLOAD_SOCK_READ_TIMEOUT,
    )
    part_path = f"{dest}.part" if dest else None
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(url, timeout=timeout) as resp,
        ):
            if resp.status != 200:
                raise DownloadError(url, resp.status)
            if dest is not None:
                assert part_path is not None
                parent = Path(dest).parent
                parent.mkdir(parents=True, exist_ok=True)
                with open(part_path, "wb") as f:
                    while True:
                        chunk = await resp.content.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                os.replace(part_path, dest)
                return None
            buffer = bytearray()
            while True:
                chunk = await resp.content.read(65536)
                if not chunk:
                    break
                buffer.extend(chunk)
            return bytes(buffer)
    except TimeoutError as e:
        if part_path and os.path.exists(part_path):
            with contextlib.suppress(OSError):
                os.unlink(part_path)
        raise DownloadTimeoutError(url, JAR_DOWNLOAD_SOCK_READ_TIMEOUT) from e
    except aiohttp.ClientError as e:
        if part_path and os.path.exists(part_path):
            with contextlib.suppress(OSError):
                os.unlink(part_path)
        raise DownloadError(url, 0, str(e)) from e
    except BaseException:
        if part_path and os.path.exists(part_path):
            with contextlib.suppress(OSError):
                os.unlink(part_path)
        raise


async def _resolve_download_url_async(server_type: str, minecraft_version: str) -> str:
    resolver = _get_resolver(server_type)
    return await resolver(minecraft_version)


def _get_resolver(server_type: str) -> Callable[[str], Awaitable[str]]:
    resolvers = {
        "vanilla": _resolve_vanilla_url,
        "paper": _resolve_paper_url,
        "purpur": _resolve_purpur_url,
        "fabric": _resolve_fabric_url,
        "quilt": _resolve_quilt_url,
        "spigot": _resolve_spigot_url,
        "bukkit": _resolve_bukkit_url,
        "forge": _resolve_forge_url,
        "neoforge": _resolve_neoforge_url,
    }
    resolver = resolvers.get(server_type)
    if resolver is None:
        raise ValueError(f"Unknown server type: {server_type}")
    return resolver


async def _resolve_vanilla_url(version: str) -> str:
    try:
        async with aiohttp.ClientSession() as session, session.get(
            VANILLA_MANIFEST_URL,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status != 200:
                raise DownloadError(
                    VANILLA_MANIFEST_URL, resp.status, "cannot fetch version manifest"
                )
            data = await resp.json()
            for entry in data.get("versions", []):
                if entry["id"] == version:
                    version_url = entry["url"]
                    async with session.get(
                        version_url,
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as vresp:
                        if vresp.status != 200:
                            raise DownloadError(
                                version_url, vresp.status, "cannot fetch version metadata"
                            )
                        vdata = await vresp.json()
                        jar_hash = vdata.get("downloads", {}).get("server", {}).get("sha1")
                        if not jar_hash:
                            raise VersionNotFoundError(version, "vanilla")
                        return (
                            f"https://piston-data.mojang.com/v1/objects/{jar_hash}/server.jar"
                        )
    except (TimeoutError, aiohttp.ClientError, ValueError) as e:
        raise DownloadError(VANILLA_MANIFEST_URL, 0, str(e)) from e
    raise VersionNotFoundError(version, "vanilla")


@dataclass(frozen=True)
class PaperBuildResolution:
    mc_version: str
    build_id: int
    channel: str
    download_url: str
    sha256: str | None = None
    size: int | None = None
    java_min_major: int | None = None


def _iter_paper_version_groups(
    versions: object,
) -> dict[str, list[str]]:
    if isinstance(versions, dict):
        groups: dict[str, list[str]] = {}
        for group, values in versions.items():
            if isinstance(values, list):
                groups[str(group)] = [str(v) for v in values if isinstance(v, str)]
        return groups
    if isinstance(versions, list):
        flat = [str(v) for v in versions if isinstance(v, str)]
        return {"": flat}
    return {}


def _resolve_paper_version_group(version: str, versions: object) -> str | None:
    groups = _iter_paper_version_groups(versions)
    for values in groups.values():
        if version in values:
            return version
    for group, values in groups.items():
        if group and (group == version or group.startswith(f"{version}.")) and values:
            try:
                return max(values, key=MinecraftVersion.parse)
            except ValueError:
                return values[0]
        prefixed = [value for value in values if value.startswith(f"{version}.")]
        if prefixed:
            try:
                return max(prefixed, key=MinecraftVersion.parse)
            except ValueError:
                return prefixed[0]
    return None


def _paper_build_java_minimum(build: dict[str, Any]) -> int | None:
    java = build.get("java")
    if isinstance(java, dict):
        version = java.get("version")
        if isinstance(version, dict):
            minimum = version.get("minimum")
            if type(minimum) is int and minimum > 0:
                return minimum
        minimum = java.get("minimum")
        if type(minimum) is int and minimum > 0:
            return minimum
    return None


async def resolve_paper_build(
    version: str,
    *,
    allow_experimental_paper_builds: bool = False,
) -> PaperBuildResolution:
    """Resolve a Paper Fill v3 version group to the highest allowed build."""
    request_url = PAPER_PROJECT_URL
    builds_payload: object = None
    resolved_mc = version
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                request_url, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    raise DownloadError(request_url, resp.status, "cannot fetch Paper project")
                project = await resp.json()
            if isinstance(project, list):
                builds_payload = project
            else:
                versions = project.get("versions") if isinstance(project, dict) else None
                resolved = _resolve_paper_version_group(version, versions)
                if resolved is None:
                    raise VersionNotFoundError(version, "paper")
                resolved_mc = resolved
                builds_url = PAPER_BUILDS_URL.format(version=resolved_mc)
                async with session.get(
                    builds_url, timeout=aiohttp.ClientTimeout(total=15)
                ) as builds_resp:
                    if builds_resp.status != 200:
                        raise DownloadError(
                            builds_url, builds_resp.status, "cannot fetch Paper builds list"
                        )
                    builds_payload = await builds_resp.json()
    except (TimeoutError, aiohttp.ClientError, ValueError) as exc:
        raise DownloadError(request_url, 0, str(exc)) from exc

    if isinstance(builds_payload, dict):
        builds_obj = builds_payload.get("builds", [])
    else:
        builds_obj = builds_payload
    if not isinstance(builds_obj, list) or not builds_obj:
        raise VersionNotFoundError(version, "paper")

    builds = [b for b in builds_obj if isinstance(b, dict)]

    def channel_of(build: dict[str, Any]) -> str:
        return str(build.get("channel", "STABLE")).upper()

    stable = [b for b in builds if channel_of(b) == "STABLE"]
    if stable:
        matching = stable
    elif allow_experimental_paper_builds:
        matching = [b for b in builds if channel_of(b) in ("BETA", "ALPHA")]
    else:
        matching = []
    if not matching:
        raise VersionNotFoundError(version, "paper")

    selected = max(matching, key=lambda b: int(b.get("id", 0) or 0))
    downloads = selected.get("downloads", {})
    download = None
    if isinstance(downloads, dict):
        download = downloads.get("server:default")
        if not isinstance(download, dict):
            download = next((v for v in downloads.values() if isinstance(v, dict)), None)
    download_url = download.get("url") if isinstance(download, dict) else None
    if not isinstance(download_url, str) or not download_url:
        raise VersionNotFoundError(version, "paper")

    checksums = (
        download.get("checksums")
        if isinstance(download, dict) and isinstance(download.get("checksums"), dict)
        else selected.get("checksums", {})
    )
    sha256 = checksums.get("sha256") if isinstance(checksums, dict) else None
    download_size = download.get("size") if isinstance(download, dict) else None
    size = download_size if type(download_size) is int else selected.get("size")
    return PaperBuildResolution(
        mc_version=resolved_mc,
        build_id=int(selected.get("id", 0) or 0),
        channel=channel_of(selected),
        download_url=download_url,
        sha256=str(sha256) if sha256 else None,
        size=size if type(size) is int else None,
        java_min_major=_paper_build_java_minimum(selected),
    )


async def _resolve_paper_url(
    version: str,
    *,
    allow_experimental_paper_builds: bool = False,
) -> str:
    resolution = await resolve_paper_build(
        version, allow_experimental_paper_builds=allow_experimental_paper_builds
    )
    return resolution.download_url


async def _resolve_purpur_url(version: str) -> str:
    return f"https://api.purpurmc.org/v2/purpur/{version}/latest/download"


async def _resolve_fabric_url(version: str) -> str:
    url = FABRIC_LOADER_URL.format(version=version)
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp,
        ):
            if resp.status != 200:
                raise DownloadError(url, resp.status, "cannot fetch Fabric loaders")
            loaders = await resp.json()
            if not loaders:
                raise VersionNotFoundError(version, "fabric")
            loader = loaders[0]
            loader_ver = loader["loader"]["version"]
            installer_ver = loader.get("launcher", {}).get("version", "1.0.1")
            return (
                f"https://meta.fabricmc.net/v2/versions/loader/{version}"
                f"/{loader_ver}/{installer_ver}/server/jar"
            )
    except (TimeoutError, aiohttp.ClientError, ValueError) as e:
        raise DownloadError(url, 0, str(e)) from e


async def _resolve_quilt_url(version: str) -> str:
    loader_version = await resolve_quilt_loader_version(version)
    if loader_version is None:
        raise VersionNotFoundError(version, "quilt")
    return QUILT_SERVER_JSON_URL.format(
        mc_version=version, loader_version=loader_version
    )


async def _resolve_spigot_url(version: str) -> str:
    return f"https://download.getbukkit.org/spigot/spigot-{version}.jar"


async def _resolve_bukkit_url(version: str) -> str:
    return f"https://download.getbukkit.org/craftbukkit/craftbukkit-{version}.jar"


async def _resolve_forge_url(version: str) -> str:
    validate_forge_supported_version(version)
    full_version = await resolve_forge_build(version)
    if full_version is None:
        raise VersionNotFoundError(version, "forge")
    return forge_universal_url(full_version)


async def _resolve_neoforge_url(version: str) -> str:
    full_version = await resolve_neoforge_build(version)
    if full_version is None:
        raise VersionNotFoundError(version, "neoforge")
    return neoforge_universal_url(full_version)


def write_eula(
    server_id: str,
    deployment: ServerDeployment | None = None,
    fs: FileSystem | None = None,
) -> str:
    """Write eula=true to eula.txt for the target server deployment.

    POLICY NOTE (ISS-031):
    Mojang's Minecraft End User License Agreement (EULA) requires players and server
    operators to explicitly read and agree to the EULA (https://account.mojang.com/documents/minecraft_eula)
    before running the server software.

    Currently, ONX automatically accepts the EULA (`eula=true`) on behalf of the user
    during server initialization to ensure unattended/automated server deployment workflows.
    This represents a known policy gap: upstream server creation flows in the API and UI
    should ideally present an explicit EULA acceptance confirmation checkbox from the user
    prior to server provisioning. Automated acceptance remains in place here to preserve
    backwards compatibility and automation until explicit upstream consent UI is introduced.
    """
    fs = fs or local_fs
    dest = _resolve_eula_dest(deployment, server_id)
    fs.ensure_dir(str(Path(dest).parent))
    fs.write_text(dest, "eula=true\n")
    return dest


def update_server_properties_key(
    dest_path: str,
    key: str,
    value: str,
    fs: FileSystem | None = None,
) -> bool:
    """Update or insert a key=value line in an on-disk server.properties file.

    Preserves other existing configuration and comments.
    """
    fs = fs or local_fs
    if not fs.exists(dest_path):
        fs.ensure_dir(str(Path(dest_path).parent))
        fs.write_text(dest_path, f"#Minecraft server properties\n{key}={value}\n")
        return True

    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(.*)$")
    matched = False
    new_lines = []
    for line in fs.read_text(dest_path).splitlines():
        if pattern.match(line):
            new_lines.append(f"{key}={value}")
            matched = True
        else:
            new_lines.append(line)
    if not matched:
        new_lines.append(f"{key}={value}")

    fs.write_text(dest_path, "\n".join(new_lines) + "\n")
    return True


def write_server_properties(
    server_id: str,
    props: dict,
    deployment: ServerDeployment | None = None,
    fs: FileSystem | None = None,
) -> str:
    fs = fs or local_fs
    dest = _resolve_properties_dest(deployment, server_id)
    fs.ensure_dir(str(Path(dest).parent))

    lines = [
        "#Minecraft server properties",
    ]
    name_val = props.get("server_name") or props.get("server-name") or props.get("name")
    if name_val:
        lines.append(f"server-name={name_val}")
    lines.extend(
        [
            f"server-port={props.get('port', 25565)}",
            f"motd={props.get('motd', 'A Minecraft Server')}",
            f"max-players={props.get('max_players', 20)}",
            f"gamemode={props.get('gamemode', 'survival')}",
            f"difficulty={props.get('difficulty', 'easy')}",
            f"spawn-protection={props.get('spawn_protection', 16)}",
            f"pvp={str(props.get('pvp', True)).lower()}",
            f"enable-command-block={str(props.get('enable_command_block', False)).lower()}",
            f"online-mode={str(props.get('online_mode', True)).lower()}",
            f"white-list={str(props.get('whitelist', False)).lower()}",
            f"view-distance={props.get('view_distance', 10)}",
            f"simulation-distance={props.get('simulation_distance', 10)}",
            # Auto-enable RCON for metrics collection (TPS, player count)
            "enable-rcon=true",
            f"rcon.port={props.get('rcon_port', 25575)}",
            f"rcon.password={props.get('rcon_password', _generate_rcon_password())}",
            "",
        ]
    )
    fs.write_text(dest, "\n".join(lines))
    return dest


def generate_rcon_password() -> str:
    """Generate a secure random RCON password."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(32))


_generate_rcon_password = generate_rcon_password
