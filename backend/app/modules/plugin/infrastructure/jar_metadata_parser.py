from __future__ import annotations

import json
import logging
import zipfile
from typing import TYPE_CHECKING

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore

import yaml

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


def parse_jar_version(jar_path: str) -> str | None:
    """Extract version string from a Minecraft plugin/mod .jar archive.

    Probes metadata files inside the ZIP archive in priority order:
    1. plugin.yml / paper-plugin.yml (YAML) -> top-level "version"
    2. fabric.mod.json / quilt.mod.json (JSON) -> top-level "version"
    3. META-INF/mods.toml / META-INF/neoforge.mods.toml (TOML) -> mods[0].version
       (falls through to MANIFEST.MF if version is a placeholder like "${file.jarVersion}")
    4. META-INF/MANIFEST.MF -> Implementation-Version / Specification-Version / Bundle-Version
    5. mcmod.info (JSON array or object) -> version

    Returns extracted version string or None if unparsable.
    """
    try:
        with zipfile.ZipFile(jar_path, "r") as zf:
            namelist = zf.namelist()
            name_map = {name.lower(): name for name in namelist}

            # 1. plugin.yml or paper-plugin.yml
            for candidate in ("plugin.yml", "paper-plugin.yml"):
                if candidate in name_map:
                    try:
                        raw_content = zf.read(name_map[candidate]).decode("utf-8", errors="replace")
                        data = yaml.safe_load(raw_content)
                        if isinstance(data, dict) and "version" in data and data["version"] is not None:
                            ver = str(data["version"]).strip()
                            if ver and not ver.startswith("${"):
                                return ver
                    except Exception as e:
                        logger.debug("Failed to parse %s in %s: %s", candidate, jar_path, e)

            # 2. fabric.mod.json or quilt.mod.json
            for candidate in ("fabric.mod.json", "quilt.mod.json"):
                if candidate in name_map:
                    try:
                        raw_content = zf.read(name_map[candidate]).decode("utf-8", errors="replace")
                        data = json.loads(raw_content)
                        if isinstance(data, dict) and "version" in data and data["version"] is not None:
                            ver = str(data["version"]).strip()
                            if ver and not ver.startswith("${"):
                                return ver
                    except Exception as e:
                        logger.debug("Failed to parse %s in %s: %s", candidate, jar_path, e)

            # 3. META-INF/mods.toml or META-INF/neoforge.mods.toml
            for candidate in ("meta-inf/mods.toml", "meta-inf/neoforge.mods.toml"):
                if candidate in name_map:
                    try:
                        raw_content = zf.read(name_map[candidate]).decode("utf-8", errors="replace")
                        data = tomllib.loads(raw_content)
                        if isinstance(data, dict) and "mods" in data and isinstance(data["mods"], list) and len(data["mods"]) > 0:
                            first_mod = data["mods"][0]
                            if isinstance(first_mod, dict) and "version" in first_mod and first_mod["version"] is not None:
                                ver = str(first_mod["version"]).strip()
                                if ver and not ver.startswith("${"):
                                    return ver
                    except Exception as e:
                        logger.debug("Failed to parse %s in %s: %s", candidate, jar_path, e)

            # 4. META-INF/MANIFEST.MF
            if "meta-inf/manifest.mf" in name_map:
                try:
                    raw_content = zf.read(name_map["meta-inf/manifest.mf"]).decode("utf-8", errors="replace")
                    ver = _parse_manifest_version(raw_content)
                    if ver:
                        return ver
                except Exception as e:
                    logger.debug("Failed to parse MANIFEST.MF in %s: %s", jar_path, e)

            # 5. mcmod.info (legacy Forge)
            if "mcmod.info" in name_map:
                try:
                    raw_content = zf.read(name_map["mcmod.info"]).decode("utf-8", errors="replace")
                    data = json.loads(raw_content)
                    mod_list: Sequence[object] | None = None
                    if isinstance(data, list):
                        mod_list = data
                    elif isinstance(data, dict):
                        mod_list = data.get("modList") or data.get("modlist")  # type: ignore
                    if isinstance(mod_list, list) and len(mod_list) > 0:
                        first_mod = mod_list[0]
                        if isinstance(first_mod, dict) and "version" in first_mod and first_mod["version"] is not None:
                            ver = str(first_mod["version"]).strip()
                            if ver and not ver.startswith("${"):
                                return ver
                except Exception as e:
                    logger.debug("Failed to parse mcmod.info in %s: %s", jar_path, e)

    except Exception as e:
        logger.warning("Failed to inspect .jar file %s: %s", jar_path, e)

    return None


def _parse_manifest_version(content: str) -> str | None:
    lines = content.splitlines()
    headers: dict[str, str] = {}
    current_key: str | None = None

    for line in lines:
        if line.startswith(" ") and current_key:
            headers[current_key] += line.strip()
        elif ":" in line:
            key, val = line.split(":", 1)
            current_key = key.strip().lower()
            headers[current_key] = val.strip()

    for k in ("implementation-version", "specification-version", "bundle-version"):
        if k in headers:
            ver = headers[k].strip()
            if ver and not ver.startswith("${"):
                return ver
    return None
