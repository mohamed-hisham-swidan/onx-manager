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


class TestModrinthProviderSearch:
    @pytest.mark.asyncio
    async def test_search_plugin_facets_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = ModrinthProvider()
        captured_params = {}

        async def mock_get_json(path: str, params: dict | None = None) -> dict:
            nonlocal captured_params
            captured_params = params or {}
            return {
                "hits": [
                    {
                        "project_id": "proj-1",
                        "slug": "paper-plugin",
                        "title": "Paper Plugin",
                        "all_project_types": ["plugin"],
                    },
                    {
                        "project_id": "proj-2",
                        "slug": "fabric-mod",
                        "title": "Fabric Mod",
                        "all_project_types": ["mod"],
                    },
                ]
            }

        monkeypatch.setattr(provider, "_get_json", mock_get_json)

        results = await provider.search("worldedit")
        assert len(results) == 1
        assert results[0].project_id == "proj-1"
        assert "project_type:plugin" in captured_params.get("facets", "")
        assert "categories:paper" in captured_params.get("facets", "")

    @pytest.mark.asyncio
    async def test_search_mod_facets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = ModrinthProvider()
        captured_params = {}

        async def mock_get_json(path: str, params: dict | None = None) -> dict:
            nonlocal captured_params
            captured_params = params or {}
            return {
                "hits": [
                    {
                        "project_id": "proj-1",
                        "slug": "paper-plugin",
                        "title": "Paper Plugin",
                        "all_project_types": ["plugin"],
                    },
                    {
                        "project_id": "proj-2",
                        "slug": "fabric-mod",
                        "title": "Fabric Mod",
                        "all_project_types": ["mod"],
                    },
                ]
            }

        monkeypatch.setattr(provider, "_get_json", mock_get_json)

        results = await provider.search("sodium", project_type="mod")
        assert len(results) == 1
        assert results[0].project_id == "proj-2"
        assert "project_type:mod" in captured_params.get("facets", "")
        assert "categories:fabric" in captured_params.get("facets", "")

