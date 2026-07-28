from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import AppSettings

logger = logging.getLogger("mcs.discovery.scanner")


@dataclass
class DiscoveredDirectory:
    path: str
    dirname: str
    detected_type: str
    has_server_jar: bool
    has_world_dir: bool
    has_server_properties: bool
    has_eula: bool
    size_mb: float
    jar_name: str = "server.jar"
    properties: dict[str, str] = field(default_factory=dict)


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = text.replace("_", "-")
    text = re.sub(r"[\s-]+", "-", text)
    text = text.strip("-")
    return text or "server"


def parse_dirname_for_id(dirname: str) -> str | None:
    if re.match(r"^[0-9a-f]{32}$", dirname):
        return dirname
    parts = dirname.split("-")
    if len(parts) >= 2 and re.match(r"^[0-9a-f]{8}$", parts[-1]):
        return parts[-1]
    return None


def _detect_server_type(dir_path: Path) -> str:
    if (dir_path / "paper.yml").exists():
        return "paper"
    if (dir_path / "spigot.yml").exists():
        return "spigot"
    if (dir_path / "bukkit.yml").exists():
        return "bukkit"
    if (dir_path / "forge.jar").exists():
        return "forge"
    if (dir_path / "fabric-server-launch.jar").exists():
        return "fabric"
    mcmeta = dir_path / "usercache.json"
    if mcmeta.exists() or (dir_path / "server.jar").exists():
        return "vanilla"
    return "unknown"


def _read_properties(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    except (FileNotFoundError, PermissionError, OSError):
        pass
    return result


def _dir_size_mb(path: Path) -> float:
    total = 0
    try:
        for entry in path.rglob("*"):
            if entry.is_file():
                try:
                    total += entry.stat().st_size
                except (FileNotFoundError, PermissionError, OSError):
                    pass
        return total / (1024 * 1024)
    except (FileNotFoundError, PermissionError, OSError):
        return 0.0


def _dir_looks_like_server(dir_path: Path) -> bool:
    if not dir_path.is_dir():
        return False
    has_jar = any(f.name.endswith(".jar") for f in dir_path.iterdir() if f.is_file())
    has_world = (dir_path / "world").is_dir()
    has_props = (dir_path / "server.properties").is_file()
    return has_jar and (has_world or has_props)


class FilesystemScanner:
    def __init__(self, root_dir: str | None = None) -> None:
        self._root = Path(root_dir) if root_dir else Path(AppSettings().servers_data_dir)

    async def scan(self) -> list[DiscoveredDirectory]:
        results: list[DiscoveredDirectory] = []
        if not self._root.is_dir():
            logger.warning("Server data directory does not exist: %s", self._root)
            return results

        for entry in sorted(self._root.iterdir(), key=lambda x: x.name):
            if not _dir_looks_like_server(entry):
                continue

            try:
                props = _read_properties(entry / "server.properties") if (entry / "server.properties").is_file() else {}
                level_name = props.get("level-name", "world")
                has_world = (entry / level_name).is_dir()

                jar_candidates = [f for f in entry.iterdir() if f.is_file() and f.name.endswith(".jar")]
                jar_name = ""
                for jc in jar_candidates:
                    jc_lower = jc.name.lower()
                    if "server" in jc_lower:
                        jar_name = jc.name
                        break
                if not jar_name and jar_candidates:
                    jar_name = jar_candidates[0].name

                results.append(DiscoveredDirectory(
                    path=str(entry),
                    dirname=entry.name,
                    detected_type=_detect_server_type(entry),
                    has_server_jar=bool(jar_name),
                    has_world_dir=has_world,
                    has_server_properties=(entry / "server.properties").is_file(),
                    has_eula=(entry / "eula.txt").is_file(),
                    size_mb=_dir_size_mb(entry),
                    jar_name=jar_name,
                    properties=props,
                ))
            except (PermissionError, OSError) as exc:
                logger.warning("Cannot scan %s: %s", entry, exc)
                continue

        return results
