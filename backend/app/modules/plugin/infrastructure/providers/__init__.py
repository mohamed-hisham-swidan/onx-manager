from __future__ import annotations

from app.core.config import AppSettings, ConfigFactory
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
    "validate_plugin_providers",
]

_PROVIDERS = {ModrinthProvider.name: ModrinthProvider}


def validate_plugin_providers(providers: str) -> list[str]:
    """Normalize and validate a configured provider list.

    Returns the normalized provider names. Raises ``ValueError`` for any
    provider that has no registered implementation, or when more than one
    provider is configured, so misconfiguration fails fast during startup
    rather than at request time. K16A supports exactly one active provider.
    """
    names = [name.strip().lower() for name in providers.split(",") if name.strip()]
    unknown = [name for name in names if name not in _PROVIDERS]
    if unknown:
        raise ValueError(f"Unknown plugin catalog provider(s): {', '.join(unknown)}")
    if not names:
        raise ValueError("plugin_providers setting must name at least one provider")
    if len(names) > 1:
        raise ValueError(
            "plugin_providers setting must name exactly one provider "
            f"(got {len(names)}: {', '.join(names)})"
        )
    return names


def build_plugin_catalog_provider(
    name: str | None = None,
    settings: AppSettings | None = None,
) -> PluginCatalogProvider:
    """Factory mirroring ``build_storage_backend`` (app/api/deps.py).

    Provider selection is configuration-driven: ``plugin_providers``
    (default ``modrinth``). An explicit ``name`` wins over settings when given.
    """
    if name is None:
        settings = settings or ConfigFactory.global_settings()
        name = validate_plugin_providers(settings.plugin_providers)[0]
    provider = name.strip().lower()
    provider_cls = _PROVIDERS.get(provider)
    if provider_cls is None:
        raise ValueError(f"Unknown plugin catalog provider: {name!r}")
    return provider_cls()
