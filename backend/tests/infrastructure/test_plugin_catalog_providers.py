from __future__ import annotations

import pytest

from app.modules.plugin.infrastructure.providers import (
    ModrinthProvider,
    build_plugin_catalog_provider,
    validate_plugin_providers,
)


class TestValidatePluginProviders:
    def test_single_known_provider(self) -> None:
        assert validate_plugin_providers("modrinth") == ["modrinth"]

    def test_case_and_whitespace_normalized(self) -> None:
        assert validate_plugin_providers(" Modrinth ") == ["modrinth"]

    def test_multiple_providers_rejected(self) -> None:
        with pytest.raises(ValueError, match="exactly one provider"):
            validate_plugin_providers("modrinth,modrinth")

    def test_unknown_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown plugin catalog provider"):
            validate_plugin_providers("curseforge")

    def test_mixed_known_and_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="curseforge"):
            validate_plugin_providers("modrinth,curseforge")

    def test_empty_list(self) -> None:
        with pytest.raises(ValueError, match="at least one provider"):
            validate_plugin_providers("")


class TestBuildPluginCatalogProvider:
    def test_default_provider_is_modrinth(self) -> None:
        provider = build_plugin_catalog_provider()
        assert isinstance(provider, ModrinthProvider)
        assert provider.name == "modrinth"

    def test_explicit_name(self) -> None:
        provider = build_plugin_catalog_provider(name="modrinth")
        assert isinstance(provider, ModrinthProvider)

    def test_settings_drive_provider(self) -> None:
        from app.core.config import AppSettings

        provider = build_plugin_catalog_provider(settings=AppSettings(plugin_providers="modrinth"))
        assert isinstance(provider, ModrinthProvider)

    def test_unknown_name_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown plugin catalog provider"):
            build_plugin_catalog_provider(name="curseforge")

    def test_unknown_settings_value_raises(self) -> None:
        from app.core.config import AppSettings

        with pytest.raises(ValueError, match="Unknown plugin catalog provider"):
            build_plugin_catalog_provider(
                settings=AppSettings(plugin_providers="curseforge")
            )

    def test_empty_settings_value_raises(self) -> None:
        from app.core.config import AppSettings

        with pytest.raises(ValueError, match="at least one provider"):
            build_plugin_catalog_provider(settings=AppSettings(plugin_providers=""))

    def test_multiple_settings_values_raises(self) -> None:
        from app.core.config import AppSettings

        with pytest.raises(ValueError, match="exactly one provider"):
            build_plugin_catalog_provider(
                settings=AppSettings(plugin_providers="modrinth,modrinth")
            )
