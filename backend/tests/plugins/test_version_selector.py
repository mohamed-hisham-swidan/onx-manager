from __future__ import annotations

import pytest

from app.modules.plugin.application.services.version_selector import (
    _game_version_matches,
    _mc_distance,
    is_version_loader_compatible,
    select_best_version,
)
from app.modules.plugin.infrastructure.providers.base import PluginVersionInfo


def _ver(
    version_number: str,
    *,
    game_versions: list[str] | None = None,
    loaders: list[str] | None = None,
    version_type: str = "release",
    date_published: str = "",
) -> PluginVersionInfo:
    return PluginVersionInfo(
        version_id=f"v-{version_number}-{'-'.join(loaders or ['paper'])}",
        project_id="p-1",
        name=version_number,
        version_number=version_number,
        game_versions=["1.21"] if game_versions is None else game_versions,
        loaders=["paper"] if loaders is None else loaders,
        version_type=version_type,
        date_published=date_published,
    )


def test_exact_match_and_bare_major_minor_coverage() -> None:
    versions = [
        _ver("1.0.0", game_versions=["1.20"], loaders=["paper"]),
        _ver("2.0.0", game_versions=["1.21"], loaders=["paper"]),
    ]
    res = select_best_version("paper", "1.21", versions)
    assert res.selected is not None
    assert res.selected.version_number == "2.0.0"
    assert res.notice_kind == ""

    patch_versions = [
        _ver("1.0.0", game_versions=["1.21"], loaders=["paper"]),
        _ver("2.0.0", game_versions=["1.21.5"], loaders=["paper"]),
    ]
    patch_res = select_best_version("paper", "1.21.5", patch_versions)
    assert patch_res.selected is not None
    assert patch_res.selected.version_number == "2.0.0"


def test_loader_compatibility_fallback_and_tie_breaking() -> None:
    # Purpur and Paper share native Paper-API tier (no fallback warning)
    purpur_res = select_best_version("purpur", "1.21", [_ver("2.0.0", loaders=["paper"])])
    assert purpur_res.selected is not None and purpur_res.notice_kind == ""

    # Newer native Paper build beats stale purpur-tagged build; ties prefer exact purpur
    newer_paper = select_best_version(
        "purpur",
        "1.21",
        [_ver("1.0.0", loaders=["purpur"]), _ver("2.0.0", loaders=["paper"])],
    )
    assert newer_paper.selected is not None and newer_paper.selected.version_number == "2.0.0"

    tied = select_best_version(
        "purpur",
        "1.21",
        [_ver("2.0.0", loaders=["paper"]), _ver("2.0.0", loaders=["purpur"])],
    )
    assert tied.selected is not None and tied.selected.loaders == ["purpur"]

    # Bukkit fallback warns; Folia exact succeeds; Fabric on Paper incompatible
    bukkit_res = select_best_version("paper", "1.21", [_ver("1.0.0", loaders=["bukkit"])])
    assert bukkit_res.selected is not None and bukkit_res.notice_kind == "loader_fallback"

    folia_res = select_best_version("folia", "1.21", [_ver("1.0.0", loaders=["folia"])])
    assert folia_res.selected is not None and folia_res.notice_kind == ""

    incompat = select_best_version("paper", "1.21", [_ver("1.0.0", loaders=["fabric"])])
    assert incompat.selected is None and incompat.notice_kind == "incompatible"


def test_version_mismatch_empty_and_weighted_mc_distance() -> None:
    empty_res = select_best_version("paper", "1.21", [])
    assert empty_res.selected is None and empty_res.notice_kind == "no_versions"

    mismatch = select_best_version("paper", "1.21", [_ver("1.0.0", game_versions=["1.20"])])
    assert mismatch.selected is not None and mismatch.notice_kind == "version_mismatch"

    versions = [
        _ver(
            "1.4.40",
            loaders=["bukkit"],
            game_versions=["1.21.4"],
            date_published="2026-02-02T00:00:00Z",
        ),
        _ver(
            "paper-1.5.66",
            loaders=["paper"],
            game_versions=["1.21.4"],
            date_published="2026-02-01T00:00:00Z",
        ),
        _ver("1.0.0", loaders=["paper"], game_versions=[]),
    ]
    res = select_best_version("purpur", "1.21.11", versions)
    assert res.selected is not None
    assert res.selected.version_number == "paper-1.5.66"
    assert res.notice_kind == "version_mismatch"
    assert _mc_distance("1.21.1", "1.21.4") < _mc_distance("1.21.1", "1.20.1")


def test_sorting_release_preference_and_malformed_versions() -> None:
    dated = [
        _ver("1.0.0", date_published="2024-01-01T00:00:00Z"),
        _ver("2.0.0", date_published="2025-01-01T00:00:00Z"),
    ]
    res_dated = select_best_version("paper", "1.21", dated)
    assert [v.version_number for v in res_dated.available] == ["2.0.0", "1.0.0"]

    semver = [
        _ver("1.2", date_published="2024-06-01T00:00:00Z"),
        _ver("1.9", date_published="2024-01-01T00:00:00Z"),
        _ver("1.10", date_published="2020-01-01T00:00:00Z"),
    ]
    res_semver = select_best_version("paper", "1.21", semver)
    assert [v.version_number for v in res_semver.available] == ["1.10", "1.9", "1.2"]
    assert res_semver.selected is not None and res_semver.selected.version_number == "1.10"

    prefixed = [
        _ver("2.6.7", loaders=["bukkit"], game_versions=["1.21.11"]),
        _ver("bukkit-2.6.21", loaders=["bukkit"], game_versions=["1.21.11"]),
        _ver(
            "3.0.0-alpha.1",
            loaders=["bukkit"],
            game_versions=["1.21.11"],
            version_type="alpha",
        ),
    ]
    res_pref = select_best_version("paper", "1.21.11", prefixed)
    assert res_pref.selected is not None and res_pref.selected.version_number == "bukkit-2.6.21"

    malformed = [
        _ver("abc"),
        _ver(""),
        _ver("v1.2.3-beta+build"),
        _ver("1.11"),
    ]
    res_mal = select_best_version("paper", "1.21", malformed)
    assert res_mal.selected is not None and res_mal.selected.version_number == "1.11"


@pytest.mark.parametrize(
    ("target", "candidate", "expected"),
    [
        ("1.21.11", "1.21.1", False),
        ("1.21.4", "1.21.40", False),
        ("1.21.11", "1.21", True),
        ("1.21.11", "1.21.11", True),
        ("1.21.1", "1.21.11", False),
        ("1.21.11", "1.21.11-rc3", False),
        ("1.21.11-rc3", "1.21.11-rc3", True),
        ("26.3", "26.3-snapshot-9", False),
        ("18w50a", "18w50a", True),
        ("1.21.11.2", "1.21.11.9", False),
        ("1.21.11.2", "1.21.11.2", True),
        ("1..21", "1.21", False),
        ("", "", True),
    ],
)
def test_game_version_matches_matrix(target: str, candidate: str, expected: bool) -> None:
    assert _game_version_matches(target, candidate) is expected


def test_is_version_loader_compatible_rejects_empty() -> None:
    assert is_version_loader_compatible("paper", []) is False
    assert is_version_loader_compatible("fabric", [""]) is False
    assert is_version_loader_compatible("paper", ["spigot"]) is True
    assert is_version_loader_compatible("paper", ["fabric"]) is False
