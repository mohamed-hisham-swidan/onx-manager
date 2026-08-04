from app.modules.plugin.application.services.version_selector import select_best_version
from app.modules.plugin.infrastructure.providers.base import PluginVersionInfo


def _ver(
    version_number: str,
    *,
    game_versions: list[str] | None = None,
    loaders: list[str] | None = None,
    date_published: str = "",
) -> PluginVersionInfo:
    return PluginVersionInfo(
        version_id=f"v-{version_number}",
        project_id="p-1",
        name=version_number,
        version_number=version_number,
        game_versions=game_versions or ["1.21"],
        loaders=loaders or ["paper"],
        date_published=date_published,
    )


def test_exact_match_selected():
    versions = [
        _ver("1.0.0", game_versions=["1.20"], loaders=["paper"]),
        _ver("2.0.0", game_versions=["1.21"], loaders=["paper"]),
    ]
    result = select_best_version("paper", "1.21", versions)
    assert result.selected is not None
    assert result.selected.version_number == "2.0.0"
    assert result.notice_kind == ""


def test_bare_major_minor_covers_patch_releases():
    versions = [
        _ver("1.0.0", game_versions=["1.21"], loaders=["paper"]),
        _ver("2.0.0", game_versions=["1.21.5"], loaders=["paper"]),
    ]
    result = select_best_version("paper", "1.21.5", versions)
    assert result.selected is not None
    assert result.selected.version_number == "2.0.0"


def test_loader_fallback_to_paper_from_purpur():
    versions = [
        _ver("2.0.0", game_versions=["1.21"], loaders=["paper"]),
    ]
    result = select_best_version("purpur", "1.21", versions)
    assert result.selected is not None
    assert result.selected.version_number == "2.0.0"
    assert result.notice_kind == "loader_fallback"


def test_exact_loader_preferred_over_newer_parent_build():
    versions = [
        _ver("1.0.0", game_versions=["1.21"], loaders=["purpur"]),
        _ver("2.0.0", game_versions=["1.21"], loaders=["paper"]),
    ]
    result = select_best_version("purpur", "1.21", versions)
    assert result.selected is not None
    assert result.selected.version_number == "1.0.0"
    assert result.notice_kind == ""


def test_loader_fallback_to_bukkit():
    versions = [
        _ver("1.0.0", game_versions=["1.21"], loaders=["bukkit"]),
    ]
    result = select_best_version("paper", "1.21", versions)
    assert result.selected is not None
    assert result.selected.loaders == ["bukkit"]
    assert result.notice_kind == "loader_fallback"


def test_loader_incompatible_picks_nothing():
    versions = [
        _ver("1.0.0", game_versions=["1.21"], loaders=["fabric"]),
    ]
    result = select_best_version("paper", "1.21", versions)
    assert result.selected is None
    assert result.notice_kind == "incompatible"


def test_version_mismatch_warns_but_selects():
    versions = [
        _ver("1.0.0", game_versions=["1.20"], loaders=["paper"]),
    ]
    result = select_best_version("paper", "1.21", versions)
    assert result.selected is not None
    assert result.selected.version_number == "1.0.0"
    assert result.notice_kind == "version_mismatch"


def test_no_versions():
    result = select_best_version("paper", "1.21", [])
    assert result.selected is None
    assert result.notice_kind == "no_versions"


def test_newest_published_wins():
    versions = [
        _ver(
            "1.0.0",
            game_versions=["1.21"],
            loaders=["paper"],
            date_published="2024-01-01T00:00:00Z",
        ),
        _ver(
            "2.0.0",
            game_versions=["1.21"],
            loaders=["paper"],
            date_published="2025-01-01T00:00:00Z",
        ),
    ]
    result = select_best_version("paper", "1.21", versions)
    assert result.selected.version_number == "2.0.0"


def test_available_sorted_newest_first():
    versions = [
        _ver(
            "1.0.0",
            game_versions=["1.21"],
            loaders=["paper"],
            date_published="2024-01-01T00:00:00Z",
        ),
        _ver(
            "2.0.0",
            game_versions=["1.21"],
            loaders=["paper"],
            date_published="2025-01-01T00:00:00Z",
        ),
    ]
    result = select_best_version("paper", "1.21", versions)
    assert [v.version_number for v in result.available] == ["2.0.0", "1.0.0"]


def test_folia_chain():
    versions = [
        _ver("1.0.0", game_versions=["1.21"], loaders=["folia"]),
    ]
    result = select_best_version("folia", "1.21", versions)
    assert result.selected is not None
    assert result.notice_kind == ""
