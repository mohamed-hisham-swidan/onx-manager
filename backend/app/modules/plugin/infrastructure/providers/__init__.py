from __future__ import annotations

from app.modules.plugin.infrastructure.providers.base import (
    PluginCatalogProvider,
    PluginFile,
    PluginProject,
    PluginSearchResult,
    PluginVersionInfo,
)
from app.modules.plugin.infrastructure.providers.modrinth import ModrinthProvider

__all__ = [
    "PluginCatalogProvider",
    "PluginFile",
    "PluginProject",
    "PluginSearchResult",
    "PluginVersionInfo",
    "ModrinthProvider",
    "build_plugin_catalog_provider",
]


def build_plugin_catalog_provider(name: str = "modrinth") -> PluginCatalogProvider:
    """Factory mirroring ``build_storage_backend`` (app/api/deps.py)."""
    provider = name.strip().lower()
    if provider == "modrinth":
        return ModrinthProvider()
    raise ValueError(f"Unknown plugin catalog provider: {name!r}")
