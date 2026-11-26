from app.modules.plugin.application.services.version_selector import (
    _game_version_matches,
    select_best_version,
)
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
    # Purpur and Paper share the native Paper-API tier (no fallback warning).
    assert result.notice_kind == ""


def test_exact_loader_preferred_over_newer_parent_build():
    # A stale purpur-tagged build must NOT starve a newer native paper build;
    # on equal version/date ties, purpur wins.
    versions = [
        _ver("1.0.0", game_versions=["1.21"], loaders=["purpur"]),
        _ver("2.0.0", game_versions=["1.21"], loaders=["paper"]),
    ]
    result = select_best_version("purpur", "1.21", versions)
    assert result.selected is not None
    assert result.selected.version_number == "2.0.0"
    assert result.notice_kind == ""

    tied = [
        _ver("2.0.0", game_versions=["1.21"], loaders=["paper"]),
        _ver("2.0.0", game_versions=["1.21"], loaders=["purpur"]),
    ]
    tied_result = select_best_version("purpur", "1.21", tied)
    assert tied_result.selected is not None
    assert tied_result.selected.loaders == ["purpur"]


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


def test_semver_aware_sort_1_10_after_1_9():
    versions = [
        _ver(
            "1.2", game_versions=["1.21"], loaders=["paper"], date_published="2024-06-01T00:00:00Z"
        ),
        _ver(
            "1.9", game_versions=["1.21"], loaders=["paper"], date_published="2024-01-01T00:00:00Z"
        ),
        _ver(
            "1.10", game_versions=["1.21"], loaders=["paper"], date_published="2020-01-01T00:00:00Z"
        ),
    ]
    result = select_best_version("paper", "1.21", versions)
    assert [v.version_number for v in result.available] == ["1.10", "1.9", "1.2"]
    assert result.selected is not None
    assert result.selected.version_number == "1.10"


def test_malformed_version_number_does_not_crash():
    versions = [
        _ver("abc", game_versions=["1.21"], loaders=["paper"]),
        _ver("", game_versions=["1.21"], loaders=["paper"]),
        _ver("v1.2.3-beta+build", game_versions=["1.21"], loaders=["paper"]),
        _ver("1.11", game_versions=["1.21"], loaders=["paper"]),
    ]
    result = select_best_version("paper", "1.21", versions)
    assert result.selected is not None
    assert result.selected.version_number == "1.11"


# ────────────────────────────────────────────────────────────────────
# §3.6 v1.3 — _game_version_matches: prefix-collision fix test cases
# ────────────────────────────────────────────────────────────────────


class TestGameVersionMatchesV13:
    """13 required test cases for the v1.3 two-part gate matcher."""

    # Original collision fixes:
    def test_no_prefix_collision_1_21_11_vs_1_21_1(self):
        assert _game_version_matches("1.21.11", "1.21.1") is False

    def test_no_prefix_collision_1_21_4_vs_1_21_40(self):
        assert _game_version_matches("1.21.4", "1.21.40") is False

    def test_bare_line_coverage_preserved(self):
        assert _game_version_matches("1.21.11", "1.21") is True

    def test_exact_match_preserved(self):
        assert _game_version_matches("1.21.11", "1.21.11") is True

    def test_reverse_direction_collision(self):
        assert _game_version_matches("1.21.1", "1.21.11") is False

    # Suffixed/snapshot safety:
    def test_suffixed_rc_no_match(self):
        assert _game_version_matches("1.21.11", "1.21.11-rc3") is False

    def test_suffixed_rc_exact_match(self):
        assert _game_version_matches("1.21.11-rc3", "1.21.11-rc3") is True

    def test_snapshot_suffix_no_match(self):
        assert _game_version_matches("26.3", "26.3-snapshot-9") is False

    def test_legacy_id_exact_match(self):
        assert _game_version_matches("18w50a", "18w50a") is True

    # Segment-count overflow safety:
    def test_four_segment_no_collapse(self):
        assert _game_version_matches("1.21.11.2", "1.21.11.9") is False

    def test_four_segment_exact_match(self):
        assert _game_version_matches("1.21.11.2", "1.21.11.2") is True

    # Edge cases:
    def test_empty_segment_safe_fallback(self):
        assert _game_version_matches("1..21", "1.21") is False

    def test_degenerate_empty_match(self):
        assert _game_version_matches("", "") is True

    def test_empty_version_loaders_rejected(self):
        from app.modules.plugin.application.services.version_selector import (
            is_version_loader_compatible,
        )

        assert is_version_loader_compatible("paper", []) is False
        assert is_version_loader_compatible("fabric", [""]) is False
        assert is_version_loader_compatible("paper", ["spigot"]) is True
        assert is_version_loader_compatible("paper", ["fabric"]) is False
