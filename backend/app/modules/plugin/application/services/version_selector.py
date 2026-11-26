from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.modules.plugin.infrastructure.providers.base import PluginVersionInfo

# Server platform -> loaders the server can run, most-specific first.
# e.g. Purpur is a fork of Paper, which is a fork of Spigot, which implements
# the Bukkit API — so a Purpur server can run paper/spigot/bukkit builds.
LOADER_COMPATIBILITY: dict[str, tuple[str, ...]] = {
    "purpur": ("purpur", "paper", "spigot", "bukkit"),
    "paper": ("paper", "spigot", "bukkit"),
    "spigot": ("spigot", "bukkit"),
    "bukkit": ("bukkit",),
    "folia": ("folia",),
    "waterfall": ("waterfall", "bungeecord"),
    "bungeecord": ("bungeecord",),
    "velocity": ("velocity",),
    "minestom": ("minestom",),
    "quilt": ("quilt", "fabric"),
    "fabric": ("fabric",),
    "forge": ("forge",),
    "neoforge": ("neoforge",),
}

# Native loader tiers: Purpur and Paper share the native Paper-API tier (0) so
# an ancient purpur-tagged release never starves a newer native Paper build,
# while both strictly outrank Spigot (1) and Bukkit (2).
_LOADER_TIERS: dict[str, tuple[tuple[str, ...], ...]] = {
    "purpur": (("purpur", "paper"), ("spigot",), ("bukkit",)),
    "paper": (("paper",), ("spigot",), ("bukkit",)),
    "spigot": (("spigot",), ("bukkit",)),
    "bukkit": (("bukkit",),),
    "folia": (("folia",),),
    "waterfall": (("waterfall",), ("bungeecord",)),
    "bungeecord": (("bungeecord",),),
    "velocity": (("velocity",),),
    "minestom": (("minestom",),),
    "quilt": (("quilt", "fabric"),),
    "fabric": (("fabric",),),
    "forge": (("forge",),),
    "neoforge": (("neoforge",),),
}

_VERSION_TYPE_RANK: dict[str, int] = {
    "release": 2,
    "beta": 1,
    "alpha": 0,
}

_LOADER_PREFIX_RE = re.compile(
    r"^(?:(?:purpur|paper|spigot|bukkit|folia|fabric|quilt|forge|neoforge|velocity|bungeecord|bungee|waterfall|minestom)[-_+ ]+)+",
    re.IGNORECASE,
)


def loader_tiers_for_server(server_type: str) -> tuple[tuple[str, ...], ...]:
    """Return ordered compatibility tiers (native tier first) for a server software type."""
    st = (server_type or "").strip().lower()
    if not st:
        return ()
    if st in _LOADER_TIERS:
        return _LOADER_TIERS[st]
    return ((st,),)


def loader_tier_index(server_type: str, version_loaders: Sequence[str]) -> int:
    """Return best (lowest) loader tier index for ``version_loaders`` on ``server_type``."""
    normalized = {
        str(loader).strip().lower()
        for loader in (version_loaders or ())
        if str(loader).strip()
    }
    if not normalized:
        return 999
    for idx, tier in enumerate(loader_tiers_for_server(server_type)):
        if not normalized.isdisjoint(tier):
            return idx
    return 999


def version_type_rank(version_type: str | None) -> int:
    """Rank release (2) > beta (1) > alpha (0); empty/unknown defaults to release."""
    vt = (version_type or "").strip().lower()
    if not vt:
        return 2
    return _VERSION_TYPE_RANK.get(vt, 1)


def is_mc26_incompatible_for_server(
    server_version: str,
    game_versions: Sequence[str],
) -> bool:
    """True when a version exclusively targets MC 26.x+ (Java 25) on a pre-26 server."""
    server_major = _parse_mc(server_version)[0] if server_version else 0
    non_empty = [gv.strip() for gv in (game_versions or ()) if str(gv).strip()]
    return bool(
        0 < server_major < 26
        and non_empty
        and all(_parse_mc(gv)[0] >= 26 for gv in non_empty)
    )


def compatible_loaders_for_server(server_type: str) -> tuple[str, ...]:
    """Return ordered compatible loaders for a server software type."""
    st = (server_type or "").strip().lower()
    if not st:
        return ()
    return LOADER_COMPATIBILITY.get(st, (st,))


def is_version_loader_compatible(
    server_type: str,
    version_loaders: Sequence[str],
) -> bool:
    """True when the version declares at least one loader supported by the server.

    Empty loader metadata is tolerated for legacy/minimal test fixtures.
    """
    normalized_version_loaders = {
        str(loader).strip().lower()
        for loader in (version_loaders or ())
        if str(loader).strip()
    }
    if not normalized_version_loaders:
        return False
    allowed = compatible_loaders_for_server(server_type)
    if not allowed:
        return True
    return not normalized_version_loaders.isdisjoint(allowed)

_EMPTY_DATE = "1970-01-01T00:00:00Z"


@dataclass(frozen=True)
class VersionSelection:
    selected: PluginVersionInfo | None
    available: tuple[PluginVersionInfo, ...] = field(default_factory=tuple)
    notice: str = ""
    notice_kind: str = ""


def _parse_mc(version: str) -> tuple[int, int, int]:
    parts = version.strip().split(".")
    nums: list[int] = []
    for p in parts:
        try:
            nums.append(int(p))
        except ValueError:
            break
    while len(nums) < 3:
        nums.append(0)
    return (nums[0], nums[1], nums[2])


def _mc_distance(a: str, b: str) -> int:
    pa, pb = _parse_mc(a), _parse_mc(b)
    return abs(pa[0] - pb[0]) * 10000 + abs(pa[1] - pb[1]) * 100 + abs(pa[2] - pb[2])


def _game_version_matches(server_version: str, listed_version: str) -> bool:
    """True when the plugin's listed game version covers the server's version.

    A bare major.minor (e.g. "1.21") covers all patch releases of that line, and
    an exact string matches directly.  Uses a two-part gate (numeric purity AND
    segment-count bounds) to prevent prefix collisions (e.g. 1.21.1 vs 1.21.11).
    """
    server_raw_segments = server_version.strip().split(".")
    listed_raw_segments = listed_version.strip().split(".")

    def _is_safe_numeric_version(segments: list[str]) -> bool:
        # Safe to run through _parse_mc's tuple comparison ONLY when:
        #   (a) every segment is a plain non-negative integer string
        #       (isdigit() — excludes suffixes like "11-rc3", "3-snapshot-9",
        #       excludes empty segments from "1..21" or "1.21.", excludes
        #       negative-looking segments), AND
        #   (b) there are exactly 2 or 3 segments — _parse_mc silently
        #       truncates anything longer (e.g. "1.21.11.2" → (1,21,11)).
        return len(segments) in (2, 3) and all(seg.isdigit() for seg in segments)

    if not (
        _is_safe_numeric_version(server_raw_segments)
        and _is_safe_numeric_version(listed_raw_segments)
    ):
        # Any suffix, wrong segment count, or non-numeric value on either
        # side: exact string equality only. Do NOT run it through _parse_mc.
        return server_version.strip() == listed_version.strip()

    # Both sides are confirmed-safe 2-or-3-segment pure-numeric dotted
    # strings — _parse_mc is predictable and lossless here.
    server_parts = _parse_mc(server_version)
    listed_parts = _parse_mc(listed_version)

    if len(listed_raw_segments) == 2:
        # Bare major.minor covers the whole line (e.g. "1.21" covers every
        # 1.21.x patch). Bareness is read from the RAW segment count.
        return server_parts[:2] == listed_parts[:2]

    # Exact numeric value requires exact equality — no prefix collision.
    return server_parts == listed_parts


def _published_at(version: PluginVersionInfo) -> str:
    return version.date_published or _EMPTY_DATE


def _normalize_semver_tuple(version_number: str) -> tuple[int, ...]:
    """Extract numeric version tokens after stripping common loader/v prefixes."""
    raw = (version_number or "").strip()
    cleaned = _LOADER_PREFIX_RE.sub("", raw)
    cleaned = re.sub(r"^v(?=\d)", "", cleaned, flags=re.IGNORECASE)
    # Strip build metadata like +1.21.11 or +mc1.21.4 before tokenizing
    core = cleaned.split("+", 1)[0]
    nums = [int(m) for m in re.findall(r"\d+", core)]
    return tuple(nums[:6]) if nums else (0,)


def _is_prerelease_string(version_number: str) -> bool:
    low = (version_number or "").strip().lower()
    return bool(re.search(r"(?:^|[-._+])(alpha|beta|rc|dev|snapshot|pre|canary)(?:[-._+\d]|$)", low))


def _effective_version_type_rank(version: PluginVersionInfo) -> int:
    raw_vt = (getattr(version, "version_type", None) or "").strip().lower()
    if raw_vt in _VERSION_TYPE_RANK:
        base = _VERSION_TYPE_RANK[raw_vt]
        if base == 2 and _is_prerelease_string(version.version_number):
            return 1
        return base
    if _is_prerelease_string(version.version_number):
        return 1
    return 2


def _version_sort_key(
    version: PluginVersionInfo,
    *,
    server_type: str = "",
) -> tuple[int, int, tuple[int, ...], str, int]:
    """Rank higher = better: version_type > loader_tier > semver > date_published > exact_loader."""
    vt_rank = _effective_version_type_rank(version)
    tier_score = -loader_tier_index(server_type, version.loaders) if server_type else 0
    exact_tiebreak = 0
    if server_type:
        st = server_type.strip().lower()
        normalized = {str(ldr).strip().lower() for ldr in (version.loaders or ())}
        exact_tiebreak = 1 if st in normalized else 0
    return (
        vt_rank,
        tier_score,
        _normalize_semver_tuple(version.version_number),
        _published_at(version),
        exact_tiebreak,
    )


def _best_in(group: list[PluginVersionInfo], server_type: str = "") -> PluginVersionInfo:
    """Pick the highest-ranked version (release > beta > alpha, newest date, highest semver)."""
    return max(group, key=lambda v: _version_sort_key(v, server_type=server_type))


def select_best_version(
    server_type: str,
    minecraft_version: str,
    versions: list[PluginVersionInfo],
) -> VersionSelection:
    """Select the best plugin version for a server.

    Preference order:
    1. Exact game version on the native loader tier (Purpur+Paper > Spigot > Bukkit;
       Quilt+Fabric; Folia-only for Folia), preferring release > beta > alpha,
       newest publication date, highest semver, and exact loader on ties.
    2. Exact game version on the nearest compatible fallback loader tier —
       substitution notice emitted.
    3. Closest available game version (weighted major/minor/patch distance) on a
       compatible loader, preserving loader-tier specificity and release preference —
       version-mismatch warning emitted (never crosses MC 26.x / Java 25 boundary
       onto older servers).
    Always returns the full version list sorted best-first for manual override.
    """
    if not versions:
        return VersionSelection(
            selected=None,
            available=(),
            notice="No versions available for this project.",
            notice_kind="no_versions",
        )

    server_type = (server_type or "").strip().lower()
    chain = LOADER_COMPATIBILITY.get(server_type, (server_type,))
    tiers = loader_tiers_for_server(server_type)
    server_version = (minecraft_version or "").strip()

    available = tuple(
        sorted(
            versions,
            key=lambda v: _version_sort_key(v, server_type=server_type),
            reverse=True,
        )
    )

    def loader_matches(version: PluginVersionInfo, loader: str) -> bool:
        return loader in [name.strip().lower() for name in version.loaders]

    # Candidates: versions listing a game version that covers the server's.
    candidates = [
        v
        for v in versions
        if any(_game_version_matches(server_version, gv) for gv in v.game_versions)
    ]

    if candidates:
        for tier_idx, tier_loaders in enumerate(tiers):
            group = [
                v
                for v in candidates
                if any(loader_matches(v, ldr) for ldr in tier_loaders)
            ]
            if not group:
                continue
            selected = _best_in(group, server_type=server_type)
            notice = ""
            kind = ""
            if tier_idx > 0:
                matched_ldr = next(
                    (ldr for ldr in tier_loaders if loader_matches(selected, ldr)),
                    tier_loaders[0],
                )
                display = server_type or matched_ldr
                notice = (
                    f"No {display} build found for Minecraft {server_version} — "
                    f"using the {matched_ldr} build, which {display} supports."
                )
                kind = "loader_fallback"
            return VersionSelection(
                selected=selected, available=available, notice=notice, notice_kind=kind
            )

    # No compatible-loader match for the exact game version: pick the closest
    # game version on a compatible loader, preserving loader-tier specificity.
    # Never cross the MC 26.x / Java 25 boundary onto an older (Java <=21) server.
    compatible = [
        v
        for v in versions
        if v.game_versions
        and any(gv.strip() for gv in v.game_versions)
        and any(loader_matches(v, loader) for loader in chain)
        and not is_mc26_incompatible_for_server(server_version, v.game_versions)
    ]
    if compatible:
        compatible_sorted = sorted(
            compatible,
            key=lambda v: _version_sort_key(v, server_type=server_type),
            reverse=True,
        )
        selected = min(
            compatible_sorted,
            key=lambda v: (
                min(
                    _mc_distance(server_version, gv)
                    for gv in v.game_versions
                    if gv.strip()
                ),
                loader_tier_index(server_type, v.loaders),
                -_effective_version_type_rank(v),
            ),
        )
        return VersionSelection(
            selected=selected,
            available=available,
            notice=(
                f"No build of this plugin supports Minecraft {server_version} "
                f"on {'/'.join(chain)} — using the closest available version "
                f"({selected.version_number})."
            ),
            notice_kind="version_mismatch",
        )

    # Nothing loader-compatible at all; still return the full list for manual pick.
    return VersionSelection(
        selected=None,
        available=available,
        notice=(
            f"This project has no build compatible with "
            f"{server_type or 'this server'} ({'/'.join(chain)})."
        ),
        notice_kind="incompatible",
    )
