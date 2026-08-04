from __future__ import annotations

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
    "folia": ("folia", "paper", "spigot", "bukkit"),
}

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
    return (pa[0] - pb[0]) ** 2 + (pa[1] - pb[1]) ** 2 + (pa[2] - pb[2]) ** 2


def _game_version_matches(server_version: str, listed_version: str) -> bool:
    """True when the plugin's listed game version covers the server's version.

    A bare major.minor (e.g. "1.21") covers all patch releases of that line, and
    an exact string matches directly.
    """
    if listed_version == server_version:
        return True
    return listed_version.startswith(server_version) or server_version.startswith(listed_version)


def _published_at(version: PluginVersionInfo) -> str:
    return version.date_published or _EMPTY_DATE


def _best_in(group: list[PluginVersionInfo]) -> PluginVersionInfo:
    """Pick the newest published version; tie-break on version_number."""
    return max(group, key=lambda v: (_published_at(v), v.version_number or ""))


def select_best_version(
    server_type: str,
    minecraft_version: str,
    versions: list[PluginVersionInfo],
) -> VersionSelection:
    """Select the best plugin version for a server.

    Preference order:
    1. Exact game version + exact loader.
    2. Exact game version on the nearest compatible parent loader
       (purpur -> paper -> spigot -> bukkit) — substitution notice emitted.
    3. Closest available game version (same major.minor preferred) on a
       compatible loader — version-mismatch warning emitted (never blocks).
    Always returns the full version list sorted newest-first for manual override.
    """
    if not versions:
        return VersionSelection(
            selected=None,
            available=(),
            notice="No versions available for this project.",
            notice_kind="no_versions",
        )

    available = tuple(
        sorted(versions, key=lambda v: (_published_at(v), v.version_number or ""), reverse=True)
    )
    server_type = (server_type or "").strip().lower()
    chain = LOADER_COMPATIBILITY.get(server_type, (server_type,))
    server_version = (minecraft_version or "").strip()

    def loader_matches(version: PluginVersionInfo, loader: str) -> bool:
        return loader in [name.strip().lower() for name in version.loaders]

    # Candidates: versions listing a game version that covers the server's.
    candidates = [
        v
        for v in versions
        if any(_game_version_matches(server_version, gv) for gv in v.game_versions)
    ]

    if candidates:
        for idx, loader in enumerate(chain):
            group = [v for v in candidates if loader_matches(v, loader)]
            if not group:
                continue
            selected = _best_in(group)
            notice = ""
            kind = ""
            if idx > 0:
                display = server_type or loader
                notice = (
                    f"No {display} build found for Minecraft {server_version} — "
                    f"using the {loader} build, which {display} supports."
                )
                kind = "loader_fallback"
            return VersionSelection(
                selected=selected, available=available, notice=notice, notice_kind=kind
            )

    # No compatible-loader match for the exact game version: pick the closest
    # game version on a compatible loader. Never hard-block (J4).
    compatible = [v for v in versions if any(loader_matches(v, loader) for loader in chain)]
    if compatible:
        selected = min(
            compatible,
            key=lambda v: (
                min(_mc_distance(server_version, gv) for gv in v.game_versions),
                _published_at(v),
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
