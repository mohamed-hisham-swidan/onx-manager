"""Authoritative loader identity derivation for Minecraft servers.

P2-1 Core Substrate — B4d
"""

from __future__ import annotations

import os
import re
import warnings
from pathlib import Path

from app.modules.server.domain.aggregate import Server, ServerType
from app.modules.versioning.domain.lockfile import (
    _LOADER_ID_RE,
    _VERSION_TOKEN_RE,
    LoaderRef,
)

_PAPER_PURPUR_RE = re.compile(
    r"^(?:paper|purpur)-(?:[A-Za-z0-9._+-]+)-([A-Za-z0-9._+-]+)\.jar$",
    re.IGNORECASE,
)
_FABRIC_JAR_RE = re.compile(
    r"fabric-server-mc\..+-loader\.(.+?)(?:-|\.jar$)",
    re.IGNORECASE,
)


def _is_valid_token(value: str) -> bool:
    return bool(value and _VERSION_TOKEN_RE.match(value))


def _is_valid_id(value: str) -> bool:
    return bool(value and _LOADER_ID_RE.match(value))


def derive_loader_ref_from_parts(
    server_type: ServerType,
    minecraft_version: str,
    startup_jar: str | None = None,
    server_root: str | Path | None = None,
) -> LoaderRef:
    """Derive an honest LoaderRef without a database schema change (D-B4-4)."""
    mc_str = str(minecraft_version).strip() if minecraft_version else "1.0"
    fallback_version = mc_str if _is_valid_token(mc_str) else "1.0"

    type_value = server_type.value if isinstance(server_type, ServerType) else str(server_type)

    if type_value in ("vanilla", "spigot", "bukkit"):
        loader_id = type_value
        version = fallback_version

    elif type_value in ("paper", "purpur"):
        loader_id = type_value
        version = fallback_version
        if startup_jar:
            base = os.path.basename(startup_jar)
            m = re.match(
                rf"^(?:paper|purpur)-{re.escape(mc_str)}-([A-Za-z0-9._+-]+)\.jar$",
                base,
                re.IGNORECASE,
            )
            if not m:
                m = _PAPER_PURPUR_RE.match(base)
            if m and _is_valid_token(m.group(1)):
                version = m.group(1)

    elif type_value == "fabric":
        loader_id = "fabric"
        version = None
        if server_root:
            lib_dir = Path(server_root) / "libraries" / "net" / "fabricmc" / "fabric-loader"
            try:
                if lib_dir.is_dir():
                    candidates = sorted(
                        [
                            d.name
                            for d in lib_dir.iterdir()
                            if d.is_dir() and _is_valid_token(d.name)
                        ]
                    )
                    if candidates:
                        version = candidates[0]
            except OSError:
                pass

        if version is None and startup_jar:
            base = os.path.basename(startup_jar)
            m = _FABRIC_JAR_RE.search(base)
            if m and _is_valid_token(m.group(1)):
                version = m.group(1)

        if version is None:
            version = fallback_version

    elif type_value == "quilt":
        loader_id = "quilt"
        version = None
        if server_root:
            lib_dir = Path(server_root) / "libraries" / "org" / "quiltmc" / "quilt-loader"
            try:
                if lib_dir.is_dir():
                    candidates = sorted(
                        [
                            d.name
                            for d in lib_dir.iterdir()
                            if d.is_dir() and _is_valid_token(d.name)
                        ]
                    )
                    if candidates:
                        version = candidates[0]
            except OSError:
                pass

        if version is None:
            version = fallback_version

    elif type_value == "forge":
        loader_id = "forge"
        version = None
        if server_root:
            forge_dir = Path(server_root) / "libraries" / "net" / "minecraftforge" / "forge"
            try:
                if forge_dir.is_dir():
                    candidates = sorted([d.name for d in forge_dir.iterdir() if d.is_dir()])
                    prefix = f"{mc_str}-"
                    # Unprefixed legacy names are accepted verbatim or fall back to the MC version.
                    for name in candidates:
                        cand = name[len(prefix):] if name.startswith(prefix) else name
                        if _is_valid_token(cand):
                            version = cand
                            break
            except OSError:
                pass

        if version is None:
            version = fallback_version

    elif type_value == "neoforge":
        loader_id = "neoforge"
        version = None
        if server_root:
            neo_dir = Path(server_root) / "libraries" / "net" / "neoforged" / "neoforge"
            try:
                if neo_dir.is_dir():
                    candidates = sorted(
                        [
                            d.name
                            for d in neo_dir.iterdir()
                            if d.name and d.is_dir() and _is_valid_token(d.name)
                        ]
                    )
                    if candidates:
                        version = candidates[0]
            except OSError:
                pass

        if version is None:
            version = fallback_version

    else:
        warnings.warn(
            f"Unknown or missing server type {server_type!r}; falling back to vanilla",
            UserWarning,
            stacklevel=2,
        )
        loader_id = "vanilla"
        version = fallback_version

    if not _is_valid_id(loader_id):
        loader_id = "vanilla"
    if not _is_valid_token(version):
        version = fallback_version

    return LoaderRef(id=loader_id, version=version)


def derive_loader_ref(server: Server) -> LoaderRef:
    """Derive an authoritative LoaderRef for a server from its aggregate attributes."""
    startup_jar = server.deployment.startup_jar if server.deployment else None
    server_root = server.deployment.server_directory() if server.deployment else None
    mc_version = str(server.minecraft_version) if server.minecraft_version else "1.0"
    return derive_loader_ref_from_parts(
        server_type=server.server_type,
        minecraft_version=mc_version,
        startup_jar=startup_jar,
        server_root=server_root,
    )
