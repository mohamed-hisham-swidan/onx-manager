from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any

from app.modules.server.infrastructure.fs import FileSystem, LocalFileSystem, local_fs

PROPERTIES_PATTERN = re.compile(r"^\s*([^#= ]+)\s*=\s*(.*?)\s*$")
PLUGIN_YML_PATTERN = re.compile(r"^\s*([\w-]+)\s*:\s*(.*?)\s*$")


def _read_properties(path: str, fs: FileSystem) -> dict[str, str]:
    if not fs.exists(path):
        return {}
    props: dict[str, str] = {}
    for line in fs.read_text(path).splitlines():
        m = PROPERTIES_PATTERN.match(line)
        if m:
            props[m.group(1)] = m.group(2)
    return props


def _read_eula(path: str, fs: FileSystem) -> bool:
    if not fs.exists(path):
        return False
    content = fs.read_text(path).strip().lower()
    return "eula=true" in content


def _detect_server_type(jar_name: str | None, props: dict[str, str]) -> str:
    if jar_name:
        name = jar_name.lower()
        if "paper" in name:
            return "paper"
        if "purpur" in name:
            return "purpur"
        if "fabric" in name:
            return "fabric"
        if "forge" in name or "neoforge" in name:
            return "forge"
        if "spigot" in name:
            return "spigot"
        if "craftbukkit" in name or "bukkit" in name:
            return "bukkit"
        if name == "server.jar" or "vanilla" in name:
            return "vanilla"

    settings_type = props.get("settings-type", "")
    if settings_type in ("paper", "purpur", "fabric", "forge", "spigot", "bukkit"):
        return settings_type

    if props.get("paper-config") and props.get("paper-config") != "false":
        return "paper"

    return "vanilla"


def _detect_version(props: dict[str, str], jar_name: str | None) -> str:
    v = props.get("version", "").strip()
    if re.match(r"^\d+\.\d+(\.\d+)?$", v):
        return v

    if jar_name:
        m = re.search(r"-(\d+\.\d+(?:\.\d+)?)", jar_name)
        if m:
            return m.group(1)

    for mc_key in ("minecraft_version", "mcversion", "release"):
        v = props.get(mc_key, "")
        if re.match(r"^\d+\.\d+(\.\d+)?$", v):
            return v

    return ""


def _find_server_jar(server_dir: str, fs: FileSystem) -> str | None:
    for entry in fs.list_dir(server_dir):
        name = entry.name
        if entry.suffix == ".jar" and entry.is_file():
            name_lower = name.lower()
            if any(kw in name_lower for kw in ("server", "paper", "purpur", "fabric", "forge", "spigot", "bukkit", "craftbukkit")):
                return name

    jars = [e.name for e in fs.list_dir(server_dir) if e.suffix == ".jar" and e.is_file()]
    if jars:
        return jars[0]
    return None


def _parse_jar_metadata(jar_path: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    try:
        with zipfile.ZipFile(jar_path, "r") as zf:
            if "plugin.yml" in zf.namelist():
                content = zf.read("plugin.yml").decode("utf-8", errors="replace")
                for line in content.splitlines():
                    m = PLUGIN_YML_PATTERN.match(line)
                    if m:
                        metadata[m.group(1)] = m.group(2).strip("\"'")
    except (zipfile.BadZipFile, FileNotFoundError, KeyError):
        pass
    return metadata


def _scan_plugins(server_dir: str, fs: FileSystem) -> list[dict[str, Any]]:
    plugins_dir = str(Path(server_dir) / "plugins")
    if not fs.is_dir(plugins_dir):
        return []
    plugins: list[dict[str, Any]] = []
    for entry in fs.list_dir(plugins_dir):
        if entry.suffix != ".jar" or not entry.is_file():
            continue
        meta = _parse_jar_metadata(str(entry))
        plugins.append({
            "filename": entry.name,
            "size_bytes": fs.size(str(entry)),
            "name": meta.get("name", entry.stem),
            "version": meta.get("version", ""),
            "main": meta.get("main", ""),
            "api_version": meta.get("api-version", ""),
        })
    return plugins


def _scan_mods(server_dir: str, fs: FileSystem) -> list[dict[str, Any]]:
    mods_dir = str(Path(server_dir) / "mods")
    if not fs.is_dir(mods_dir):
        return []
    mods: list[dict[str, Any]] = []
    for entry in fs.list_dir(mods_dir):
        if entry.suffix != ".jar" or not entry.is_file():
            continue
        meta = _parse_jar_metadata(str(entry))
        mods.append({
            "filename": entry.name,
            "size_bytes": fs.size(str(entry)),
            "name": meta.get("name", entry.stem),
            "version": meta.get("version", ""),
        })
    return mods


def _detect_worlds(server_dir: str, props: dict[str, str], fs: FileSystem) -> list[dict[str, Any]]:
    worlds: list[dict[str, Any]] = []
    level_name = props.get("level-name", "world")
    world_path = str(Path(server_dir) / level_name)

    if fs.is_dir(world_path):
        total_size = sum(fs.size(f) for f in fs.walk(world_path))
        worlds.append({
            "name": level_name,
            "path": world_path,
            "size_bytes": total_size,
        })

    for entry in fs.list_dir(server_dir):
        if entry.is_dir() and entry.name != level_name:
            level_dat = str(entry / "level.dat")
            if fs.exists(level_dat):
                total_size = sum(fs.size(f) for f in fs.walk(str(entry)))
                worlds.append({
                    "name": entry.name,
                    "path": str(entry),
                    "size_bytes": total_size,
                })

    return worlds


def _detect_icon(server_dir: str, fs: FileSystem) -> str | None:
    icon = str(Path(server_dir) / "server-icon.png")
    return icon if fs.exists(icon) else None


def _read_json_list(path: str, fs: FileSystem, key: str = "name") -> list[str]:
    if not fs.exists(path):
        return []
    try:
        data = json.loads(fs.read_text(path))
        if isinstance(data, list):
            return [entry.get(key, "") for entry in data if isinstance(entry, dict) and entry.get(key)]
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _safe_parse_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _safe_parse_bool(value: str, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "yes", "1")
    return default


def scan_server_directory(path: str, fs: FileSystem | None = None) -> dict[str, Any]:
    fs = fs or local_fs
    server_dir = str(Path(path).expanduser().resolve())

    if not fs.is_dir(server_dir):
        raise NotADirectoryError(f"Path is not a directory: {path}")
    if not fs.list_dir(server_dir):
        raise ValueError(f"Directory is empty: {path}")

    props_path = str(Path(server_dir) / "server.properties")
    eula_path = str(Path(server_dir) / "eula.txt")
    props = _read_properties(props_path, fs)
    eula = _read_eula(eula_path, fs)
    jar_name = _find_server_jar(server_dir, fs)
    server_type = _detect_server_type(jar_name, props)

    raw_server_name = (props.get("server-name") or "").strip()
    server_name_declared = bool(raw_server_name)
    name = raw_server_name or Path(server_dir).name
    jar_full_path = str(Path(server_dir) / jar_name) if jar_name else None

    return {
        "path": server_dir,
        "name": name,
        "server_name_declared": server_name_declared,
        "server_type": server_type,
        "minecraft_version": _detect_version(props, jar_name) or "",
        "eula_accepted": eula,
        "server_jar": jar_name,
        "jar_size_bytes": fs.size(jar_full_path) if jar_full_path and fs.exists(jar_full_path) else 0,
        "properties": {
            "port": _safe_parse_int(props.get("server-port", "25565"), 25565),
            "motd": props.get("motd", "A Minecraft Server"),
            "max_players": _safe_parse_int(props.get("max-players", "20"), 20),
            "gamemode": props.get("gamemode", "survival"),
            "difficulty": props.get("difficulty", "easy"),
            "spawn_protection": _safe_parse_int(props.get("spawn-protection", "16"), 16),
            "pvp": _safe_parse_bool(props.get("pvp", "true"), True),
            "enable_command_block": _safe_parse_bool(props.get("enable-command-block", "false"), False),
            "online_mode": _safe_parse_bool(props.get("online-mode", "true"), True),
            "whitelist": _safe_parse_bool(props.get("white-list", "false"), False),
            "view_distance": _safe_parse_int(props.get("view-distance", "10"), 10),
            "simulation_distance": _safe_parse_int(props.get("simulation-distance", "10"), 10),
        },
        "plugins": _scan_plugins(server_dir, fs),
        "mods": _scan_mods(server_dir, fs),
        "worlds": _detect_worlds(server_dir, props, fs),
        "icon": _detect_icon(server_dir, fs),
        "ops": _read_json_list(str(Path(server_dir) / "ops.json"), fs),
        "banned_players": _read_json_list(str(Path(server_dir) / "banned-players.json"), fs),
        "whitelisted_players": _read_json_list(str(Path(server_dir) / "whitelist.json"), fs),
    }