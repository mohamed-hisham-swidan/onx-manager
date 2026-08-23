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
                        "categories": ["paper", "economy"],
                    },
                    {
                        "project_id": "proj-2",
                        "slug": "fabric-mod",
                        "title": "Fabric Mod",
                        "all_project_types": ["mod"],
                    },
                ],
                "total_hits": 10,
            }

        monkeypatch.setattr(provider, "_get_json", mock_get_json)

        page = await provider.search("worldedit")
        assert len(page.items) == 1
        assert page.items[0].project_id == "proj-1"
        assert page.total_hits == 10
        assert "project_type:plugin" in captured_params.get("facets", "")
        assert "categories:paper" in captured_params.get("facets", "")

    @pytest.mark.asyncio
    async def test_search_parses_new_schema_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = ModrinthProvider()

        async def mock_get_json(_path: str, params: dict | None = None) -> dict:
            assert params and params.get("query") == "worldedit"
            return {
                "hits": [
                    {
                        "project_id": "proj-1",
                        "slug": "paper-plugin",
                        "title": "Paper Plugin",
                        "all_project_types": ["plugin"],
                        "categories": ["paper", "purpur", "economy"],
                        "client_side": "unsupported",
                        "server_side": "required",
                        "date_modified": "2025-01-01T00:00:00Z",
                        "color": 123456,
                    },
                ],
                "total_hits": 1,
            }

        monkeypatch.setattr(provider, "_get_json", mock_get_json)

        page = await provider.search("worldedit")
        assert len(page.items) == 1
        item = page.items[0]
        assert item.categories == ["paper", "purpur", "economy"]
        # loaders derived from categories — non-loader categories excluded
        assert item.loaders == ["paper", "purpur"]
        assert item.client_side == "unsupported"
        assert item.server_side == "required"
        assert item.date_modified == "2025-01-01T00:00:00Z"
        assert item.color == 123456

    @pytest.mark.asyncio
    async def test_search_total_hits_missing_defaults_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = ModrinthProvider()

        async def mock_get_json(_path: str, params: dict | None = None) -> dict:
            assert params and params.get("query") == "worldedit"
            return {"hits": []}

        monkeypatch.setattr(provider, "_get_json", mock_get_json)

        page = await provider.search("worldedit")
        assert page.items == []
        assert page.total_hits == 0

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
        assert len(results.items) == 1
        assert results.items[0].project_id == "proj-2"
        assert "project_type:mod" in captured_params.get("facets", "")
        assert "categories:fabric" in captured_params.get("facets", "")

    @pytest.mark.asyncio
    async def test_search_single_loader_facet(self, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = ModrinthProvider()
        captured_params = {}

        async def mock_get_json(_path: str, params: dict | None = None) -> dict:
            nonlocal captured_params
            captured_params = params or {}
            return {"hits": [], "total_hits": 0}

        monkeypatch.setattr(provider, "_get_json", mock_get_json)

        await provider.search("worldedit", loader="paper")
        facets = captured_params.get("facets", "")
        assert 'categories:paper' in facets
        # the OR-list of all server loaders must be replaced, not combined
        assert "categories:spigot" not in facets
        assert "categories:bukkit" not in facets
        assert '["categories:paper"]' in facets

        await provider.search("sodium", project_type="mod", loader="NeoForge")
        assert '["categories:neoforge"]' in captured_params.get("facets", "")

    @pytest.mark.asyncio
    async def test_search_invalid_loader_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = ModrinthProvider()
        captured_params = {}

        async def mock_get_json(_path: str, params: dict | None = None) -> dict:
            nonlocal captured_params
            captured_params = params or {}
            return {"hits": [], "total_hits": 0}

        monkeypatch.setattr(provider, "_get_json", mock_get_json)

        # facet-syntax payloads must be rejected, not interpolated
        await provider.search("worldedit", loader='"categories:paper"],["evil')
        facets = captured_params.get("facets", "")
        assert "evil" not in facets
        assert "categories:paper" in facets  # fell back to the full loader set
        assert "categories:spigot" in facets


class TestModrinthProviderGetProject:
    @pytest.mark.asyncio
    async def test_get_project_nullable_links_and_environments(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = ModrinthProvider()

        async def mock_get_json(_path: str, _params: dict | None = None) -> dict:
            return {
                "id": "proj-1",
                "slug": "test-project",
                "title": "Test Project",
                "description": "Test Desc",
                "body": "Test Body",
                "author": "Author",
                "project_type": "plugin",
                "loaders": ["paper"],
                "game_versions": ["1.21"],
                "downloads": 10,
                "follows": 2,
                "icon_url": None,
                "wiki_url": None,
                "source_url": None,
                "client_side": "optional",
                "server_side": "required",
            }

        monkeypatch.setattr(provider, "_get_json", mock_get_json)

        project = await provider.get_project("proj-1")
        assert project.project_id == "proj-1"
        assert project.wiki_url is None
        assert project.source_url is None
        assert project.client_side == "optional"
        assert project.server_side == "required"

    @pytest.mark.asyncio
    async def test_get_project_resolves_author_from_team(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = ModrinthProvider()
        calls: list[str] = []
        payloads = {
            "/project/proj-2": {
                "id": "proj-2",
                "slug": "team-project",
                "title": "Team Project",
                "description": "Desc",
                "team": "team-abc",
            },
            "/team/team-abc/members": [
                {"role": "Member", "user": {"username": "Contributor"}},
                {"role": "Owner", "user": {"username": "OwnerName"}},
            ],
        }

        async def mock_get_json(path: str, _params: dict | None = None) -> dict:
            calls.append(path)
            return payloads[path]

        monkeypatch.setattr(provider, "_get_json", mock_get_json)

        project = await provider.get_project("proj-2")
        assert calls == ["/project/proj-2", "/team/team-abc/members"]
        assert project.author == "OwnerName"

    @pytest.mark.asyncio
    async def test_get_project_team_failure_falls_back_to_empty_author(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.core.exceptions import DownloadError

        provider = ModrinthProvider()

        async def mock_get_json(path: str, _params: dict | None = None) -> dict:
            if path.startswith("/project/"):
                return {"id": "proj-3", "team": "team-xyz"}
            raise DownloadError(path, 500)

        monkeypatch.setattr(provider, "_get_json", mock_get_json)

        project = await provider.get_project("proj-3")
        assert project.author == ""


class TestModrinthProviderGetProjectVersions:
    @pytest.mark.asyncio
    async def test_returns_all_when_limit_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = ModrinthProvider()

        async def mock_get_json(_path: str, _params: dict | None = None) -> dict:
            return [
                {
                    "id": f"v{i}",
                    "project_id": "proj-1",
                    "name": f"v{i}",
                    "version_number": f"{i}.0.0",
                }
                for i in range(3)
            ]

        monkeypatch.setattr(provider, "_get_json", mock_get_json)

        page = await provider.get_project_versions("proj-1")
        assert len(page.items) == 3
        assert page.total == 3

    @pytest.mark.asyncio
    async def test_slices_fetch_all_then_slice(self, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = ModrinthProvider()

        async def mock_get_json(_path: str, _params: dict | None = None) -> dict:
            return [
                {
                    "id": f"v{i}",
                    "project_id": "proj-1",
                    "name": f"v{i}",
                    "version_number": f"{i}.0.0",
                }
                for i in range(25)
            ]

        monkeypatch.setattr(provider, "_get_json", mock_get_json)

        page = await provider.get_project_versions("proj-1", limit=10, offset=10)
        assert len(page.items) == 10
        assert page.items[0].version_id == "v10"
        assert page.items[-1].version_id == "v19"
        assert page.total == 25


