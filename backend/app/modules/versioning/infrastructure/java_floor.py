"""Deterministic Java floor resolution for Minecraft server launches (P5.5).

The Java major version is resolved from authoritative metadata (Mojang
``version_manifest_v2.json`` / Paper Fill v3) and always falls back to a
contiguous Minecraft-version table. Fabric's ``launcherMeta.min_java_version``
is deliberately never consulted (spec L1536-1537, L3276-3277).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from app.modules.shared.value_objects import MinecraftVersion
from app.modules.versioning.infrastructure.download_allowlist import (
    download_verified_bytes,
)

logger = logging.getLogger(__name__)

VANILLA_MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
PAPER_VERSION_URL = "https://fill.papermc.io/v3/projects/paper/versions/{version}"

_TEMURIN_IMAGES: dict[int, str] = {
    8: "eclipse-temurin:8-jre-jammy",
    17: "eclipse-temurin:17-jre-jammy",
    21: "eclipse-temurin:21-jre-jammy",
    25: "eclipse-temurin:25-jre",
}


def _as_positive_int(value: object) -> int | None:
    if type(value) is int and value > 0:
        return value
    return None


def resolve_java_floor_from_mc_version(minecraft_version: str | MinecraftVersion) -> int:
    """Return the contiguous fallback Java major for a Minecraft version."""
    parsed = (
        minecraft_version
        if isinstance(minecraft_version, MinecraftVersion)
        else MinecraftVersion.parse(str(minecraft_version))
    )
    if parsed.major >= 26:
        return 25
    if parsed.major == 1:
        if parsed >= MinecraftVersion(1, 20, 5):
            return 21
        if parsed >= MinecraftVersion(1, 18, 0):
            return 17
        if parsed >= MinecraftVersion(1, 17, 1):
            return 16
        return 8
    # Unknown modern numbering: conservatively use the Java 21 floor.
    return 21


def _extract_paper_java_major(payload: Mapping[str, Any]) -> int | None:
    version = payload.get("version")
    candidates: list[object] = []
    if isinstance(version, Mapping):
        java = version.get("java")
        if isinstance(java, Mapping):
            java_version = java.get("version")
            if isinstance(java_version, Mapping):
                candidates.append(java_version.get("minimum"))
            candidates.append(java.get("minimum"))
    java_top = payload.get("java")
    if isinstance(java_top, Mapping):
        java_version = java_top.get("version")
        if isinstance(java_version, Mapping):
            candidates.append(java_version.get("minimum"))
        candidates.append(java_top.get("minimum"))
    for candidate in candidates:
        major = _as_positive_int(candidate)
        if major is not None:
            return major
    return None


def _extract_mojang_java_major(payload: Mapping[str, Any]) -> int | None:
    java_version = payload.get("javaVersion")
    if isinstance(java_version, Mapping):
        return _as_positive_int(java_version.get("majorVersion"))
    return None


async def _fetch_paper_version_json(minecraft_version: str) -> Mapping[str, Any] | None:
    url = PAPER_VERSION_URL.format(version=minecraft_version)
    try:
        raw, _result = await download_verified_bytes(url)
        data = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 - metadata is best-effort
        logger.warning("Paper Java metadata fetch failed for %s (%s)", minecraft_version, exc)
        return None
    return data if isinstance(data, Mapping) else None


async def _fetch_mojang_version_json(minecraft_version: str) -> Mapping[str, Any] | None:
    try:
        raw, _result = await download_verified_bytes(VANILLA_MANIFEST_URL)
        manifest = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 - metadata is best-effort
        logger.warning("Mojang manifest fetch failed (%s)", exc)
        return None
    if not isinstance(manifest, Mapping):
        return None
    versions = manifest.get("versions")
    if not isinstance(versions, list):
        return None
    version_url: str | None = None
    for entry in versions:
        if isinstance(entry, Mapping) and entry.get("id") == minecraft_version:
            candidate = entry.get("url")
            if isinstance(candidate, str):
                version_url = candidate
            break
    if version_url is None:
        return None
    try:
        raw, _result = await download_verified_bytes(version_url)
        data = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 - metadata is best-effort
        logger.warning("Mojang version metadata fetch failed for %s (%s)", minecraft_version, exc)
        return None
    return data if isinstance(data, Mapping) else None


async def resolve_java_major(
    minecraft_version: str,
    *,
    loader_id: str | None = None,
    mojang_version_json: Mapping[str, Any] | None = None,
    paper_version_json: Mapping[str, Any] | None = None,
    fetch_remote: bool = False,
) -> int:
    """Resolve the authoritative Java major, falling back to the MC floor."""
    if paper_version_json is not None:
        major = _extract_paper_java_major(paper_version_json)
        if major is not None:
            return major
    if mojang_version_json is not None:
        major = _extract_mojang_java_major(mojang_version_json)
        if major is not None:
            return major

    if fetch_remote and paper_version_json is None and mojang_version_json is None:
        if loader_id == "paper":
            remote = await _fetch_paper_version_json(minecraft_version)
            if remote is not None:
                major = _extract_paper_java_major(remote)
                if major is not None:
                    return major
        remote = await _fetch_mojang_version_json(minecraft_version)
        if remote is not None:
            major = _extract_mojang_java_major(remote)
            if major is not None:
                return major

    return resolve_java_floor_from_mc_version(minecraft_version)


def map_java_major_to_temurin_tag(java_major: int) -> int:
    """Map any Java major onto one of the four supported Temurin tags."""
    if java_major <= 8:
        return 8
    if java_major <= 17:
        return 17
    if java_major <= 21:
        return 21
    return 25


def temurin_docker_image_for_java_major(java_major: int) -> str:
    tag = map_java_major_to_temurin_tag(java_major)
    return _TEMURIN_IMAGES[tag]


__all__ = [
    "PAPER_VERSION_URL",
    "VANILLA_MANIFEST_URL",
    "map_java_major_to_temurin_tag",
    "resolve_java_floor_from_mc_version",
    "resolve_java_major",
    "temurin_docker_image_for_java_major",
]
