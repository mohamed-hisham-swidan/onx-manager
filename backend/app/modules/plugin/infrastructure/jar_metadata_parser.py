from __future__ import annotations

import io
import json
import logging
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore

import yaml

from app.core.exceptions import InvalidJarError

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

CLIENT_ONLY_MOD_IDS = {
    "sodium",
    "iris",
    "optifine",
    "rubidium",
    "oculus",
    "modmenu",
    "entityculling",
    "reeses-sodium-options",
    "sodium-extra",
}

ZIP_MAGIC_HEADERS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


@dataclass(frozen=True)
class ModMetadata:
    mod_id: str | None = None
    name: str | None = None
    version: str | None = None
    description: str | None = None
    authors: list[str] = field(default_factory=list)
    website: str | None = None
    dependencies: list[str] = field(default_factory=list)
    loader: str | None = None
    environment: str | None = None
    is_client_only: bool = False
    warning: str | None = None


def parse_jar_metadata(
    jar_source: str | Path | bytes | bytearray | BinaryIO,
) -> ModMetadata:
    """Extract full typed metadata from a Minecraft plugin/mod .jar archive.

    Verifies ZIP header magic bytes (PK\\x03\\x04) and raises InvalidJarError if
    the file is corrupt, invalid, or cannot be parsed as a ZIP.

    Probes metadata files inside the ZIP archive in priority order:
    1. fabric.mod.json / quilt.mod.json (Fabric / Quilt)
    2. META-INF/neoforge.mods.toml / META-INF/mods.toml (NeoForge / Forge)
    3. mcmod.info (Legacy Forge)
    4. plugin.yml / paper-plugin.yml (Bukkit / Paper)
    5. META-INF/MANIFEST.MF (Fallback)
    """
    zip_target = _validate_and_prepare_zip_source(jar_source)

    try:
        with zipfile.ZipFile(zip_target, "r") as zf:
            namelist = zf.namelist()
            name_map = {name.lower(): name for name in namelist}

            # 1. Fabric or Quilt (fabric.mod.json / quilt.mod.json)
            for candidate in ("fabric.mod.json", "quilt.mod.json"):
                if candidate in name_map:
                    try:
                        raw_content = zf.read(name_map[candidate]).decode("utf-8", errors="replace")
                        data = json.loads(raw_content)
                        if isinstance(data, dict):
                            loader = "quilt" if candidate == "quilt.mod.json" else "fabric"
                            return _parse_fabric_metadata(data, loader, zf, name_map)
                    except Exception as e:
                        logger.debug("Failed to parse %s: %s", candidate, e)

            # 2. Forge or NeoForge (neoforge.mods.toml / mods.toml)
            for candidate in ("meta-inf/neoforge.mods.toml", "meta-inf/mods.toml"):
                if candidate in name_map:
                    try:
                        raw_content = zf.read(name_map[candidate]).decode("utf-8", errors="replace")
                        data = tomllib.loads(raw_content)
                        if isinstance(data, dict):
                            loader = "neoforge" if "neoforge" in candidate else "forge"
                            return _parse_forge_toml_metadata(data, loader, zf, name_map)
                    except Exception as e:
                        logger.debug("Failed to parse %s: %s", candidate, e)

            # 3. Legacy Forge (mcmod.info)
            if "mcmod.info" in name_map:
                try:
                    raw_content = zf.read(name_map["mcmod.info"]).decode("utf-8", errors="replace")
                    data = json.loads(raw_content)
                    return _parse_mcmod_info_metadata(data)
                except Exception as e:
                    logger.debug("Failed to parse mcmod.info: %s", e)

            # 4. Bukkit / Paper (plugin.yml / paper-plugin.yml)
            for candidate in ("paper-plugin.yml", "plugin.yml"):
                if candidate in name_map:
                    try:
                        raw_content = zf.read(name_map[candidate]).decode("utf-8", errors="replace")
                        data = yaml.safe_load(raw_content)
                        if isinstance(data, dict):
                            loader = "paper" if candidate == "paper-plugin.yml" else "bukkit"
                            return _parse_bukkit_metadata(data, loader)
                    except Exception as e:
                        logger.debug("Failed to parse %s: %s", candidate, e)

            # 5. Fallback: META-INF/MANIFEST.MF
            if "meta-inf/manifest.mf" in name_map:
                try:
                    raw_content = zf.read(name_map["meta-inf/manifest.mf"]).decode(
                        "utf-8", errors="replace"
                    )
                    ver = _parse_manifest_version(raw_content)
                    title = _parse_manifest_title(raw_content)
                    if ver or title:
                        return ModMetadata(
                            mod_id=title.lower().replace(" ", "-") if title else None,
                            name=title,
                            version=ver,
                            loader=None,
                        )
                except Exception as e:
                    logger.debug("Failed to parse MANIFEST.MF: %s", e)

    except zipfile.BadZipFile as e:
        raise InvalidJarError(f"Corrupted or invalid JAR file: {e}") from e
    except Exception as e:
        if isinstance(e, InvalidJarError):
            raise
        logger.warning("Failed to inspect .jar file: %s", e)

    fallback_name = None
    if isinstance(jar_source, (str, Path)):
        fallback_name = Path(jar_source).stem

    return ModMetadata(name=fallback_name)


def parse_jar_version(jar_path: str) -> str | None:
    """Extract version string from a Minecraft plugin/mod .jar archive.

    Maintained for backward compatibility. Returns extracted version string
    or None if unparsable/corrupted without raising.
    """
    try:
        meta = parse_jar_metadata(jar_path)
        return meta.version
    except Exception:
        return None


def _validate_and_prepare_zip_source(
    jar_source: str | Path | bytes | bytearray | BinaryIO,
) -> Any:
    """Validate ZIP magic bytes and return a source usable with zipfile.ZipFile."""
    if isinstance(jar_source, (str, Path)):
        p = Path(jar_source)
        if not p.is_file():
            raise InvalidJarError(f"JAR file not found: {p}")
        try:
            with p.open("rb") as f:
                header = f.read(4)
        except OSError as e:
            raise InvalidJarError(f"Cannot read JAR file: {e}") from e
        if len(header) < 4 or header not in ZIP_MAGIC_HEADERS:
            raise InvalidJarError("Invalid JAR file: missing ZIP header signature")
        return p

    if isinstance(jar_source, (bytes, bytearray)):
        if len(jar_source) < 4 or bytes(jar_source[:4]) not in ZIP_MAGIC_HEADERS:
            raise InvalidJarError("Invalid JAR file: missing ZIP header signature")
        return io.BytesIO(jar_source)

    # BinaryIO-like object
    try:
        jar_source.seek(0)
        header = jar_source.read(4)
        jar_source.seek(0)
    except Exception as e:
        raise InvalidJarError(f"Failed reading JAR stream: {e}") from e

    if len(header) < 4 or header not in ZIP_MAGIC_HEADERS:
        raise InvalidJarError("Invalid JAR file: missing ZIP header signature")
    return jar_source


def _parse_fabric_metadata(
    data: dict[str, Any],
    loader: str,
    zf: zipfile.ZipFile,
    name_map: dict[str, str],
) -> ModMetadata:
    mod_id = data.get("id")
    name = data.get("name") or mod_id
    version_val = data.get("version")
    version = str(version_val).strip() if version_val is not None else None
    if version and version.startswith("${"):
        version = None
    if not version and "meta-inf/manifest.mf" in name_map:
        version = _read_manifest_version_from_zip(zf, name_map["meta-inf/manifest.mf"])

    description = data.get("description")
    if isinstance(description, dict):
        description = str(description)

    authors: list[str] = []
    raw_authors = data.get("authors")
    if isinstance(raw_authors, list):
        for a in raw_authors:
            if isinstance(a, str):
                authors.append(a)
            elif isinstance(a, dict) and "name" in a:
                authors.append(str(a["name"]))
    elif isinstance(raw_authors, str):
        authors.append(raw_authors)

    contact = data.get("contact", {})
    website = None
    if isinstance(contact, dict):
        website = contact.get("homepage") or contact.get("sources")

    dependencies: list[str] = []
    depends = data.get("depends", {})
    if isinstance(depends, dict):
        dependencies.extend(depends.keys())
    elif isinstance(depends, list):
        dependencies.extend(str(d) for d in depends)

    environment = data.get("environment")
    if isinstance(environment, str):
        environment = environment.lower()

    is_client_only = False
    warning = None
    if environment == "client" or (mod_id and mod_id.lower() in CLIENT_ONLY_MOD_IDS):
        is_client_only = True
        warning = "Client-only mod detected — may fail or be ignored on dedicated server"

    return ModMetadata(
        mod_id=str(mod_id) if mod_id else None,
        name=str(name) if name else None,
        version=version,
        description=str(description) if description else None,
        authors=authors,
        website=str(website) if website else None,
        dependencies=dependencies,
        loader=loader,
        environment=environment,
        is_client_only=is_client_only,
        warning=warning,
    )


def _parse_forge_toml_metadata(
    data: dict[str, Any],
    loader: str,
    zf: zipfile.ZipFile,
    name_map: dict[str, str],
) -> ModMetadata:
    mods_list = data.get("mods")
    first_mod: dict[str, Any] = {}
    if isinstance(mods_list, list) and len(mods_list) > 0 and isinstance(mods_list[0], dict):
        first_mod = mods_list[0]

    mod_id = first_mod.get("modId")
    name = first_mod.get("displayName") or mod_id
    version_val = first_mod.get("version")
    version = str(version_val).strip() if version_val is not None else None

    if not version or version.startswith("${"):
        version = None
        if "meta-inf/manifest.mf" in name_map:
            version = _read_manifest_version_from_zip(zf, name_map["meta-inf/manifest.mf"])

    description = first_mod.get("description")
    authors: list[str] = []
    raw_authors = first_mod.get("authors") or data.get("authors")
    if isinstance(raw_authors, str):
        authors.extend(a.strip() for a in raw_authors.split(",") if a.strip())
    elif isinstance(raw_authors, list):
        authors.extend(str(a) for a in raw_authors)

    website = first_mod.get("displayURL") or data.get("issueTrackerURL")

    dependencies: list[str] = []
    raw_deps = data.get("dependencies", {})
    if isinstance(raw_deps, dict):
        for dep_list in raw_deps.values():
            if isinstance(dep_list, list):
                for dep in dep_list:
                    if isinstance(dep, dict) and "modId" in dep:
                        dependencies.append(str(dep["modId"]))

    display_test = first_mod.get("displayTest")
    client_side_only = first_mod.get("clientSideOnly") is True
    is_client_only = False
    warning = None

    if (
        client_side_only
        or display_test in ("IGNORE_ALL_VERSION", "NONE", "IGNORE_SERVER_VERSION")
        or (mod_id and mod_id.lower() in CLIENT_ONLY_MOD_IDS)
    ):
        is_client_only = True
        warning = "Client-only mod detected — may fail or be ignored on dedicated server"

    return ModMetadata(
        mod_id=str(mod_id) if mod_id else None,
        name=str(name) if name else None,
        version=version,
        description=str(description) if description else None,
        authors=authors,
        website=str(website) if website else None,
        dependencies=dependencies,
        loader=loader,
        environment="client" if is_client_only else "both",
        is_client_only=is_client_only,
        warning=warning,
    )


def _parse_mcmod_info_metadata(data: Any) -> ModMetadata:
    mod_list: Sequence[object] | None = None
    if isinstance(data, list):
        mod_list = data
    elif isinstance(data, dict):
        mod_list = data.get("modList") or data.get("modlist")  # type: ignore

    first_mod: dict[str, Any] = {}
    if isinstance(mod_list, list) and len(mod_list) > 0 and isinstance(mod_list[0], dict):
        first_mod = mod_list[0]

    mod_id = first_mod.get("modid")
    name = first_mod.get("name") or mod_id
    version_val = first_mod.get("version")
    version = str(version_val).strip() if version_val is not None else None
    if version and version.startswith("${"):
        version = None

    description = first_mod.get("description")
    authors: list[str] = []
    raw_authors = first_mod.get("authorList") or first_mod.get("authors")
    if isinstance(raw_authors, list):
        authors.extend(str(a) for a in raw_authors)
    elif isinstance(raw_authors, str):
        authors.append(raw_authors)

    website = first_mod.get("url")

    dependencies: list[str] = []
    raw_deps = first_mod.get("requiredMods") or first_mod.get("dependencies")
    if isinstance(raw_deps, list):
        dependencies.extend(str(d) for d in raw_deps)

    is_client_only = bool(mod_id and mod_id.lower() in CLIENT_ONLY_MOD_IDS)
    warning = (
        "Client-only mod detected — may fail or be ignored on dedicated server"
        if is_client_only
        else None
    )

    return ModMetadata(
        mod_id=str(mod_id) if mod_id else None,
        name=str(name) if name else None,
        version=version,
        description=str(description) if description else None,
        authors=authors,
        website=str(website) if website else None,
        dependencies=dependencies,
        loader="forge",
        environment="client" if is_client_only else "both",
        is_client_only=is_client_only,
        warning=warning,
    )


def _parse_bukkit_metadata(data: dict[str, Any], loader: str) -> ModMetadata:
    name = data.get("name")
    version_val = data.get("version")
    version = str(version_val).strip() if version_val is not None else None
    if version and version.startswith("${"):
        version = None

    description = data.get("description")
    authors: list[str] = []
    raw_authors = data.get("authors")
    if isinstance(raw_authors, list):
        authors.extend(str(a) for a in raw_authors)
    elif "author" in data and data["author"]:
        authors.append(str(data["author"]))

    website = data.get("website")

    dependencies: list[str] = []
    for dep_key in ("depend", "dependencies", "softdepend"):
        val = data.get(dep_key)
        if isinstance(val, list):
            dependencies.extend(str(d) for d in val)

    return ModMetadata(
        mod_id=str(name).lower() if name else None,
        name=str(name) if name else None,
        version=version,
        description=str(description) if description else None,
        authors=authors,
        website=str(website) if website else None,
        dependencies=dependencies,
        loader=loader,
        environment="server",
        is_client_only=False,
        warning=None,
    )


def _read_manifest_version_from_zip(zf: zipfile.ZipFile, manifest_name: str) -> str | None:
    try:
        raw = zf.read(manifest_name).decode("utf-8", errors="replace")
        return _parse_manifest_version(raw)
    except Exception:
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


def _parse_manifest_title(content: str) -> str | None:
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

    for k in ("implementation-title", "specification-title", "bundle-name"):
        if k in headers:
            title = headers[k].strip()
            if title and not title.startswith("${"):
                return title
    return None
