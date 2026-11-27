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

from app.core.config import AppSettings
from app.core.exceptions import InvalidJarError, InvalidPluginJarError, MCSError
from app.modules.plugin.infrastructure.addon_fs import is_mod_server

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

PLUGIN_ROOT_DESCRIPTORS = (
    "paper-plugin.yml",
    "plugin.yml",
    "bungee.yml",
    "velocity-plugin.json",
)
MOD_DESCRIPTORS = (
    "fabric.mod.json",
    "quilt.mod.json",
    "meta-inf/neoforge.mods.toml",
    "meta-inf/mods.toml",
    "mcmod.info",
)
_MAX_DESCRIPTOR_BYTES = 1 * 1024 * 1024  # 1 MiB cap against descriptor zip bombs


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


_PLUGIN_SERVER_TYPES = frozenset({
    "paper",
    "purpur",
    "spigot",
    "bukkit",
    "craftbukkit",
    "folia",
    "velocity",
    "bungeecord",
    "waterfall",
    "minestom",
})


def _ordered_plugin_descriptors(preferred_server_type: str | None) -> tuple[str, ...]:
    st = (preferred_server_type or "").strip().lower()
    if st == "velocity":
        return ("velocity-plugin.json", "bungee.yml", "paper-plugin.yml", "plugin.yml")
    if st in ("bungeecord", "waterfall"):
        return ("bungee.yml", "velocity-plugin.json", "paper-plugin.yml", "plugin.yml")
    if st in ("spigot", "bukkit", "craftbukkit"):
        return ("plugin.yml", "paper-plugin.yml", "bungee.yml", "velocity-plugin.json")
    return PLUGIN_ROOT_DESCRIPTORS


def _ordered_mod_descriptors(preferred_server_type: str | None) -> tuple[str, ...]:
    st = (preferred_server_type or "").strip().lower()
    if st == "neoforge":
        return (
            "meta-inf/neoforge.mods.toml",
            "meta-inf/mods.toml",
            "fabric.mod.json",
            "quilt.mod.json",
            "mcmod.info",
        )
    if st == "forge":
        return (
            "meta-inf/mods.toml",
            "meta-inf/neoforge.mods.toml",
            "mcmod.info",
            "fabric.mod.json",
            "quilt.mod.json",
        )
    if st == "quilt":
        return (
            "quilt.mod.json",
            "fabric.mod.json",
            "meta-inf/neoforge.mods.toml",
            "meta-inf/mods.toml",
            "mcmod.info",
        )
    return MOD_DESCRIPTORS


def _probe_plugin_descriptors(
    zf: zipfile.ZipFile,
    name_map: dict[str, str],
    preferred_server_type: str | None = None,
) -> ModMetadata | None:
    """Extract Bukkit/Paper/Bungee/Velocity metadata prioritizing server_type's descriptor."""
    for candidate in _ordered_plugin_descriptors(preferred_server_type):
        if candidate not in name_map:
            continue
        if candidate == "velocity-plugin.json":
            try:
                raw_content = zf.read(name_map[candidate]).decode("utf-8", errors="replace")
                data = json.loads(raw_content)
                if isinstance(data, dict):
                    return _parse_velocity_metadata(data)
            except Exception as e:
                logger.debug("Failed to parse velocity-plugin.json: %s", e)
            continue
        try:
            raw_content = zf.read(name_map[candidate]).decode("utf-8", errors="replace")
            data = yaml.safe_load(raw_content)
            if isinstance(data, dict):
                loader = (
                    "paper"
                    if candidate == "paper-plugin.yml"
                    else "bungeecord"
                    if candidate == "bungee.yml"
                    else "bukkit"
                )
                return _parse_bukkit_metadata(data, loader)
        except Exception as e:
            logger.debug("Failed to parse %s: %s", candidate, e)

    return None


def _probe_mod_descriptors(
    zf: zipfile.ZipFile,
    name_map: dict[str, str],
    preferred_server_type: str | None = None,
) -> ModMetadata | None:
    """Extract Fabric/Quilt/Forge/NeoForge metadata prioritizing server_type's descriptor."""
    for candidate in _ordered_mod_descriptors(preferred_server_type):
        if candidate not in name_map:
            continue
        try:
            raw_content = zf.read(name_map[candidate]).decode("utf-8", errors="replace")
            if candidate == "quilt.mod.json":
                data = json.loads(raw_content)
                if isinstance(data, dict):
                    return _parse_quilt_metadata(data, zf, name_map)
            elif candidate == "fabric.mod.json":
                data = json.loads(raw_content)
                if isinstance(data, dict):
                    return _parse_fabric_metadata(data, "fabric", zf, name_map)
            elif candidate in ("meta-inf/neoforge.mods.toml", "meta-inf/mods.toml"):
                data = tomllib.loads(raw_content)
                if isinstance(data, dict):
                    loader = "neoforge" if "neoforge" in candidate else "forge"
                    return _parse_forge_toml_metadata(data, loader, zf, name_map)
            elif candidate == "mcmod.info":
                data = json.loads(raw_content)
                return _parse_mcmod_info_metadata(data)
        except Exception as e:
            logger.debug("Failed to parse %s: %s", candidate, e)
    return None


def parse_jar_metadata(
    jar_source: str | Path | bytes | bytearray | BinaryIO,
    *,
    preferred_server_type: str | None = None,
) -> ModMetadata:
    """Extract full typed metadata from a Minecraft plugin/mod .jar archive.

    Verifies ZIP header magic bytes (PK\\x03\\x04) and raises InvalidJarError if
    the file is corrupt, invalid, or cannot be parsed as a ZIP.

    When ``preferred_server_type`` is a plugin/proxy server (Paper, Purpur, Spigot,
    Bukkit, Folia, Velocity, BungeeCord, Waterfall), plugin descriptors are probed
    BEFORE Fabric/Quilt/Forge descriptors so universal multi-loader JARs report
    the matching plugin identity instead of the bundled Fabric entrypoint.
    """
    zip_target = _validate_and_prepare_zip_source(jar_source)
    prefer_plugins = (
        preferred_server_type is not None
        and preferred_server_type.strip().lower() in _PLUGIN_SERVER_TYPES
    )

    try:
        with zipfile.ZipFile(zip_target, "r") as zf:
            namelist = zf.namelist()
            name_map = {name.lower(): name for name in namelist}

            if prefer_plugins:
                plugin_meta = _probe_plugin_descriptors(zf, name_map, preferred_server_type)
                if plugin_meta is not None:
                    return plugin_meta

            mod_meta = _probe_mod_descriptors(zf, name_map, preferred_server_type)
            if mod_meta is not None:
                return mod_meta

            if not prefer_plugins:
                plugin_meta = _probe_plugin_descriptors(zf, name_map, preferred_server_type)
                if plugin_meta is not None:
                    return plugin_meta

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


def _parse_quilt_metadata(
    data: dict[str, Any],
    zf: zipfile.ZipFile,
    name_map: dict[str, str],
) -> ModMetadata:
    ql = data.get("quilt_loader")
    if not isinstance(ql, dict):
        return _parse_fabric_metadata(data, "quilt", zf, name_map)

    meta_block = ql.get("metadata") if isinstance(ql.get("metadata"), dict) else {}
    mod_id = ql.get("id")
    name = meta_block.get("name") or mod_id
    version_val = ql.get("version")
    version = str(version_val).strip() if version_val is not None else None
    if version and version.startswith("${"):
        version = None
    if not version and "meta-inf/manifest.mf" in name_map:
        version = _read_manifest_version_from_zip(zf, name_map["meta-inf/manifest.mf"])

    description = meta_block.get("description")
    authors: list[str] = []
    contributors = meta_block.get("contributors")
    if isinstance(contributors, dict):
        authors.extend(str(k) for k in contributors)
    elif isinstance(contributors, list):
        authors.extend(str(a) for a in contributors)

    contact = meta_block.get("contact") if isinstance(meta_block.get("contact"), dict) else {}
    website = contact.get("homepage") or contact.get("sources")

    dependencies: list[str] = []
    raw_deps = ql.get("depends")
    if isinstance(raw_deps, list):
        for dep in raw_deps:
            if isinstance(dep, str) and dep.strip():
                dependencies.append(dep.strip())
            elif isinstance(dep, dict) and dep.get("id") and not dep.get("optional"):
                dependencies.append(str(dep["id"]))

    mc_block = data.get("minecraft") if isinstance(data.get("minecraft"), dict) else {}
    environment = mc_block.get("environment") or data.get("environment")
    if isinstance(environment, str):
        environment = environment.lower()

    is_client_only = environment == "client" or bool(
        mod_id and str(mod_id).lower() in CLIENT_ONLY_MOD_IDS
    )
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
        loader="quilt",
        environment=environment if isinstance(environment, str) else None,
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
                    if not isinstance(dep, dict) or "modId" not in dep:
                        continue
                    if dep.get("mandatory") is False:
                        continue
                    dep_type = str(dep.get("type") or "").strip().lower()
                    if dep_type and dep_type != "required":
                        continue
                    dependencies.append(str(dep["modId"]))

    display_test = first_mod.get("displayTest")
    client_side_only = (
        data.get("clientSideOnly") is True or first_mod.get("clientSideOnly") is True
    )
    is_client_only = False
    warning = None

    if (
        client_side_only
        or display_test == "NONE"
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
    for dep_key in ("depend", "dependencies"):
        val = data.get(dep_key)
        if isinstance(val, list):
            dependencies.extend(str(d) for d in val if d)
        elif isinstance(val, dict):
            # Paper paper-plugin.yml format: dependencies: { server: { Vault: { required: true } } }
            for scope_val in val.values():
                if isinstance(scope_val, dict):
                    for dep_name, dep_cfg in scope_val.items():
                        if isinstance(dep_cfg, dict) and dep_cfg.get("required") is False:
                            continue
                        dependencies.append(str(dep_name))

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


def _parse_velocity_metadata(data: dict[str, Any]) -> ModMetadata:
    mod_id = data.get("id")
    name = data.get("name") or mod_id
    version_val = data.get("version")
    version = str(version_val).strip() if version_val is not None else None
    if version and version.startswith("${"):
        version = None

    description = data.get("description")
    authors: list[str] = []
    raw_authors = data.get("authors")
    if isinstance(raw_authors, list):
        authors.extend(str(a) for a in raw_authors if a)
    elif isinstance(raw_authors, str) and raw_authors.strip():
        authors.append(raw_authors.strip())

    website = data.get("url")
    dependencies: list[str] = []
    raw_deps = data.get("dependencies")
    if isinstance(raw_deps, list):
        for dep in raw_deps:
            if isinstance(dep, dict) and dep.get("id"):
                if dep.get("optional") is True:
                    continue
                dependencies.append(str(dep["id"]))
            elif isinstance(dep, str) and dep.strip():
                dependencies.append(dep.strip())

    return ModMetadata(
        mod_id=str(mod_id) if mod_id else None,
        name=str(name) if name else None,
        version=version,
        description=str(description) if description else None,
        authors=authors,
        website=str(website) if website else None,
        dependencies=dependencies,
        loader="velocity",
        environment="server",
        is_client_only=False,
        warning=None,
    )


def _read_bounded_zip_entry(zf: zipfile.ZipFile, entry_name: str) -> bytes:
    info = zf.getinfo(entry_name)
    if info.file_size > _MAX_DESCRIPTOR_BYTES:
        raise InvalidPluginJarError(
            f"Not a valid plugin JAR: descriptor '{entry_name}' exceeds maximum size"
        )
    with zf.open(entry_name, "r") as fh:
        data = fh.read(_MAX_DESCRIPTOR_BYTES + 1)
    if len(data) > _MAX_DESCRIPTOR_BYTES:
        raise InvalidPluginJarError(
            f"Not a valid plugin JAR: descriptor '{entry_name}' exceeds maximum size"
        )
    return data


def validate_addon_jar(
    filename: str,
    file_content: bytes,
    *,
    server_type: str | None = None,
    max_bytes: int | None = None,
) -> ModMetadata:
    """Validate an uploaded plugin/mod .jar archive before staging or CAS ingest."""
    normalized_server_type = (server_type or "").strip().lower()
    if normalized_server_type == "vanilla":
        raise InvalidPluginJarError(
            "Vanilla servers do not support plugins or mods."
        )

    if not filename or "\x00" in filename:
        raise InvalidPluginJarError("Invalid plugin file: filename must end with .jar")
    base_name = Path(filename.strip().replace("\\", "/")).name
    if not base_name.lower().endswith(".jar"):
        raise InvalidPluginJarError("Invalid plugin file: filename must end with .jar")

    if not file_content:
        raise InvalidPluginJarError("Invalid plugin JAR: file is empty")

    effective_max = (
        max_bytes
        if max_bytes is not None
        else max(0, AppSettings().files_max_upload_size_mb) * 1024 * 1024
    )
    if effective_max > 0 and len(file_content) > effective_max:
        max_mb = max(1, effective_max // (1024 * 1024))
        raise MCSError(
            message=f"Uploaded plugin exceeds maximum allowed size of {max_mb} MB",
            code="FILE_TOO_LARGE",
            http_status=413,
        )

    if len(file_content) < 4 or file_content[:4] not in ZIP_MAGIC_HEADERS:
        raise InvalidPluginJarError("Not a valid plugin JAR: corrupted or non-ZIP archive")

    try:
        with zipfile.ZipFile(io.BytesIO(file_content), "r") as zf:
            namelist = zf.namelist()
            root_name_map = {
                n.lower(): n for n in namelist if "/" not in n and not n.endswith("/")
            }
            full_name_map = {n.lower(): n for n in namelist}

            if is_mod_server(server_type):
                ordered_mods = _ordered_mod_descriptors(normalized_server_type)
                matched_mod = next((c for c in ordered_mods if c in full_name_map), None)
                if matched_mod is None:
                    raise InvalidPluginJarError(
                        "Not a valid mod JAR: missing fabric.mod.json / quilt.mod.json / "
                        "META-INF/mods.toml / META-INF/neoforge.mods.toml"
                    )
                _read_bounded_zip_entry(zf, full_name_map[matched_mod])
                meta = parse_jar_metadata(file_content, preferred_server_type=server_type)
                if not meta.loader or not (
                    (meta.name and meta.name.strip()) or (meta.mod_id and meta.mod_id.strip())
                ):
                    raise InvalidPluginJarError(
                        f"Not a valid mod JAR: invalid or incomplete {matched_mod}"
                    )
                if normalized_server_type and meta.loader:
                    from app.modules.plugin.application.services.version_selector import (
                        compatible_loaders_for_server,
                    )

                    allowed = compatible_loaders_for_server(normalized_server_type)
                    if allowed and meta.loader.strip().lower() not in allowed:
                        raise InvalidPluginJarError(
                            f"Mod JAR targets loader '{meta.loader}', which is incompatible "
                            f"with '{normalized_server_type}' servers."
                        )
                return meta

            ordered_plugins = _ordered_plugin_descriptors(normalized_server_type)
            matched_plugin = next(
                (c for c in ordered_plugins if c in root_name_map),
                None,
            )
            if matched_plugin is None:
                raise InvalidPluginJarError(
                    "Not a valid plugin JAR: missing plugin.yml / paper-plugin.yml / "
                    "bungee.yml / velocity-plugin.json"
                )

            raw_bytes = _read_bounded_zip_entry(zf, root_name_map[matched_plugin])
            raw_text = raw_bytes.decode("utf-8", errors="replace")

            if matched_plugin == "velocity-plugin.json":
                try:
                    parsed = json.loads(raw_text)
                except Exception as exc:
                    raise InvalidPluginJarError(
                        "Not a valid plugin JAR: invalid or incomplete velocity-plugin.json"
                    ) from exc
                if not isinstance(parsed, dict):
                    raise InvalidPluginJarError(
                        "Not a valid plugin JAR: invalid or incomplete velocity-plugin.json"
                    )
                raw_id = parsed.get("id")
                raw_name = parsed.get("name")
                has_id = isinstance(raw_id, str) and bool(raw_id.strip())
                has_name = isinstance(raw_name, str) and bool(raw_name.strip())
                if not (has_id or has_name):
                    raise InvalidPluginJarError(
                        "Not a valid plugin JAR: invalid or incomplete velocity-plugin.json"
                    )
                meta = _parse_velocity_metadata(parsed)
                if normalized_server_type and meta.loader:
                    from app.modules.plugin.application.services.version_selector import (
                        compatible_loaders_for_server,
                    )

                    allowed = compatible_loaders_for_server(normalized_server_type)
                    if allowed and meta.loader.strip().lower() not in allowed:
                        raise InvalidPluginJarError(
                            f"Plugin JAR targets loader '{meta.loader}', which is incompatible "
                            f"with '{normalized_server_type}' servers."
                        )
                return meta

            try:
                parsed = yaml.safe_load(raw_text)
            except Exception as exc:
                raise InvalidPluginJarError(
                    f"Not a valid plugin JAR: invalid or incomplete {matched_plugin}"
                ) from exc
            if not isinstance(parsed, dict):
                raise InvalidPluginJarError(
                    f"Not a valid plugin JAR: invalid or incomplete {matched_plugin}"
                )
            raw_name = parsed.get("name")
            if not isinstance(raw_name, str) or not raw_name.strip():
                raise InvalidPluginJarError(
                    f"Not a valid plugin JAR: invalid or incomplete {matched_plugin}"
                )
            loader = (
                "paper"
                if matched_plugin == "paper-plugin.yml"
                else "bungeecord"
                if matched_plugin == "bungee.yml"
                else "bukkit"
            )
            meta = _parse_bukkit_metadata(parsed, loader)
            if normalized_server_type and meta.loader:
                from app.modules.plugin.application.services.version_selector import (
                    compatible_loaders_for_server,
                )

                allowed = compatible_loaders_for_server(normalized_server_type)
                if allowed and meta.loader.strip().lower() not in allowed:
                    raise InvalidPluginJarError(
                        f"Plugin JAR targets loader '{meta.loader}', which is incompatible "
                        f"with '{normalized_server_type}' servers."
                    )
            return meta
    except InvalidPluginJarError:
        raise
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise InvalidPluginJarError("Not a valid plugin JAR: corrupted or non-ZIP archive") from exc


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
