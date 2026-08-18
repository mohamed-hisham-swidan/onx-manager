from __future__ import annotations

import asyncio
import logging
import re
import zipfile
from io import BytesIO
from pathlib import Path

import aiohttp

from app.core.exceptions import (
    CorruptedDownloadError,
    DownloadError,
    DownloadTimeoutError,
    FilesystemOperationError,
    VersionNotFoundError,
)
from app.modules.server.domain.value_objects import ServerDeployment
from app.modules.server.infrastructure.fs import FileSystem, local_fs

logger = logging.getLogger(__name__)

JAR_DOWNLOAD_TIMEOUT: int = 120
JAR_MIN_SIZE_BYTES: int = 1_048_576
JAR_MAX_RETRIES: int = 2
JAR_MAGIC_BYTES: bytes = b"PK\x03\x04"

VANILLA_MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"

PAPER_BUILDS_URL = "https://api.papermc.io/v2/projects/paper/versions/{version}/builds"

FABRIC_LOADER_URL = "https://meta.fabricmc.net/v2/versions/loader/{version}"

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

SERVER_TYPES_REQUIRING_MANUAL_INSTALL: set[str] = {"forge"}


def _slugify(text: str) -> str:
    """Lowercase, strip non-alphanumeric (unicode-aware), collapse whitespace to hyphens."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = text.replace("_", "-")
    text = re.sub(r"[\s-]+", "-", text)
    text = text.strip("-")
    return text or "server"


def server_dir_name(name: str, server_id: str) -> str:
    """Human-readable directory name: <slug>-<first-8-chars-of-uuid> (e.g. oneblock-reborn-be193e92)."""
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


def resolver(deployment: ServerDeployment | None = None, server_id: str | None = None):
    if deployment and deployment.root_path:
        return deployment
    return None


async def fetch_vanilla_versions() -> list[str]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(VANILLA_MANIFEST_URL, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                versions = data.get("versions", [])
                return [v["id"] for v in versions if v["type"] == "release"][::-1]
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return []


async def fetch_paper_versions() -> list[str]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.papermc.io/v2/projects/paper", timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return data.get("versions", [])[::-1]
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return []


async def fetch_purpur_versions() -> list[str]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.purpurmc.org/v2/purpur", timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return data.get("versions", [])[::-1]
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return []


async def fetch_fabric_versions() -> list[str]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://meta.fabricmc.net/v2/versions/game", timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return [v["version"] for v in data if v.get("stable")][::-1]
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return []


async def fetch_forge_versions() -> list[str]:
    return []


async def fetch_spigot_versions() -> list[str]:
    return [
        "1.21.5", "1.21.4", "1.21.3", "1.21.1", "1.21",
        "1.20.6", "1.20.4", "1.20.2", "1.20.1", "1.20",
        "1.19.4", "1.19.3", "1.19.2", "1.19.1", "1.19",
    ]


async def fetch_bukkit_versions() -> list[str]:
    return await fetch_spigot_versions()


VERSION_FETCHERS: dict[str, callable] = {
    "vanilla": fetch_vanilla_versions,
    "paper": fetch_paper_versions,
    "purpur": fetch_purpur_versions,
    "fabric": fetch_fabric_versions,
    "forge": fetch_forge_versions,
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
    if (
        len(parts) > 1
        and len(parts[-1]) == 8
        and all(c in "0123456789abcdef" for c in parts[-1])
    ):
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
        raise CorruptedDownloadError(
            path, f"invalid ZIP/JAR header: {header.hex()!r}"
        )


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

    if server_type in SERVER_TYPES_REQUIRING_MANUAL_INSTALL:
        fs.ensure_dir(parent)
        logger.info(
            "Server %s (%s %s) requires manual JAR installation at %s",
            server_id, server_type, minecraft_version, dest,
        )
        return dest

    jar_url = await _resolve_download_url_async(server_type, minecraft_version)
    fs.ensure_dir(parent)

    last_exception: Exception | None = None
    for attempt in range(JAR_MAX_RETRIES + 1):
        try:
            content = await _do_download(jar_url)
        except (DownloadError, DownloadTimeoutError) as e:
            last_exception = e
            if attempt < JAR_MAX_RETRIES:
                wait = 1.0 * (2 ** attempt)
                logger.warning("Download attempt %d failed for %s, retrying in %.1fs", attempt + 1, jar_url, wait)
                await asyncio.sleep(wait)
                continue
            raise

    fs.write_binary_atomic(dest, content)
    fs.chmod(dest, 0o755)
    validate_jar(dest, fs)
    return dest


async def _do_download(url: str) -> bytes:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=JAR_DOWNLOAD_TIMEOUT),
            ) as resp:
                if resp.status != 200:
                    raise DownloadError(url, resp.status)
                buffer = bytearray()
                while True:
                    chunk = await resp.content.read(8192)
                    if not chunk:
                        break
                    buffer.extend(chunk)
                return bytes(buffer)
    except asyncio.TimeoutError as e:
        raise DownloadTimeoutError(url, JAR_DOWNLOAD_TIMEOUT) from e
    except aiohttp.ClientError as e:
        raise DownloadError(url, 0, str(e)) from e


async def _resolve_download_url_async(server_type: str, minecraft_version: str) -> str:
    resolver = _get_resolver(server_type)
    return await resolver(minecraft_version)


def _get_resolver(server_type: str) -> callable:
    resolvers = {
        "vanilla": _resolve_vanilla_url,
        "paper": _resolve_paper_url,
        "purpur": _resolve_purpur_url,
        "fabric": _resolve_fabric_url,
        "spigot": _resolve_spigot_url,
        "bukkit": _resolve_bukkit_url,
    }
    resolver = resolvers.get(server_type)
    if resolver is None:
        raise ValueError(f"Unknown server type: {server_type}")
    return resolver


async def _resolve_vanilla_url(version: str) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                VANILLA_MANIFEST_URL,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    raise DownloadError(VANILLA_MANIFEST_URL, resp.status, "cannot fetch version manifest")
                data = await resp.json()
                for entry in data.get("versions", []):
                    if entry["id"] == version:
                        version_url = entry["url"]
                        async with session.get(
                            version_url,
                            timeout=aiohttp.ClientTimeout(total=15),
                        ) as vresp:
                            if vresp.status != 200:
                                raise DownloadError(version_url, vresp.status, "cannot fetch version metadata")
                            vdata = await vresp.json()
                            jar_hash = vdata.get("downloads", {}).get("server", {}).get("sha1")
                            if not jar_hash:
                                raise VersionNotFoundError(version, "vanilla")
                            return f"https://piston-data.mojang.com/v1/objects/{jar_hash}/server.jar"
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
        raise DownloadError(VANILLA_MANIFEST_URL, 0, str(e)) from e
    raise VersionNotFoundError(version, "vanilla")


async def _resolve_paper_url(version: str) -> str:
    url = PAPER_BUILDS_URL.format(version=version)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    raise DownloadError(url, resp.status, "cannot fetch Paper builds list")
                data = await resp.json()
                builds = data.get("builds", [])
                if not builds:
                    raise VersionNotFoundError(version, "paper")
                latest = builds[-1]
                build_num = latest["build"]
                return (
                    f"https://api.papermc.io/v2/projects/paper/versions/{version}"
                    f"/builds/{build_num}/downloads/paper-{version}-{build_num}.jar"
                )
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
        raise DownloadError(url, 0, str(e)) from e


async def _resolve_purpur_url(version: str) -> str:
    return f"https://api.purpurmc.org/v2/purpur/{version}/latest/download"


async def _resolve_fabric_url(version: str) -> str:
    url = FABRIC_LOADER_URL.format(version=version)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
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
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
        raise DownloadError(url, 0, str(e)) from e


async def _resolve_spigot_url(version: str) -> str:
    return f"https://download.getbukkit.org/spigot/spigot-{version}.jar"


async def _resolve_bukkit_url(version: str) -> str:
    return f"https://download.getbukkit.org/craftbukkit/craftbukkit-{version}.jar"


def write_eula(
    server_id: str,
    deployment: ServerDeployment | None = None,
    fs: FileSystem | None = None,
) -> str:
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
    lines.extend([
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
        "",
    ])
    fs.write_text(dest, "\n".join(lines))
    return dest

