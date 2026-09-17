from __future__ import annotations

import enum
import re

from app.modules.shared.value_objects import MinecraftVersion
from app.modules.versioning.domain.value_objects import BotTech


class VerificationMode(enum.StrEnum):
    FULL_BOT = "full_bot"
    SMOKE_TEST = "smoke_test"


def _parse_version_tuple(version_str: str | MinecraftVersion) -> tuple[int, ...]:
    """Parse version string into tuple of integers for comparison, e.g. '1.20.4' -> (1, 20, 4).

    Accepts a raw string or a MinecraftVersion domain object (rendered via str()).
    """
    parts = re.findall(r"\d+", str(version_str))
    return tuple(int(p) for p in parts) if parts else (0,)


def resolve_verification_strategy(
    server_type: str,
    minecraft_version: str | MinecraftVersion,
    bot_tech: BotTech | str = BotTech.AUTO,
) -> tuple[VerificationMode, str, str]:
    """Determines verification mode, bot driver, and rationale (§3.5).

    Returns:
        (VerificationMode, driver_name, rationale)
        driver_name is one of 'fakeplayer_next', 'mineflayer', or 'none'.
    """
    tech = bot_tech if isinstance(bot_tech, BotTech) else BotTech(str(bot_tech).lower())
    st = (server_type or "vanilla").lower()
    v_tuple = _parse_version_tuple(minecraft_version or "1.20.4")

    # Paper / Purpur
    if st in ("paper", "purpur"):
        if tech in (BotTech.AUTO, BotTech.FAKEPLAYER_NEXT):
            return (
                VerificationMode.FULL_BOT,
                "fakeplayer_next",
                f"Paper-based server ({st}) supported via in-process FakePlayer-Next driver",
            )
        if tech == BotTech.MINEFLAYER:
            return (
                VerificationMode.FULL_BOT,
                "mineflayer",
                "Explicit Mineflayer protocol driver requested for Paper server",
            )

    # If caller specifically requested FakePlayer-Next on non-Paper:
    if tech == BotTech.FAKEPLAYER_NEXT and st not in ("paper", "purpur"):
        return (
            VerificationMode.SMOKE_TEST,
            "none",
            f"FakePlayer-Next is Paper-only; {st} falls back to smoke test mode",
        )

    # Forge / NeoForge
    if st in ("forge", "neoforge"):
        if tech == BotTech.AUTO:
            return (
                VerificationMode.SMOKE_TEST,
                "none",
                f"Modded loader {st} requires custom protocol handshake; using smoke test mode",
            )
        return (
            VerificationMode.FULL_BOT,
            "mineflayer",
            f"Explicit Mineflayer requested for modded loader {st}",
        )

    # Non-Java or exotic loaders (e.g. bedrock, sponge, proxies, unknown) fall back to smoke test
    known_java_loaders = ("vanilla", "fabric", "spigot", "bukkit", "quilt")
    if st not in known_java_loaders:
        return (
            VerificationMode.SMOKE_TEST,
            "none",
            f"Server type '{st}' is unsupported for bot connection; using smoke test mode",
        )

    # Vanilla / Fabric / Spigot / Bukkit / Quilt
    # Mineflayer reliably negotiates up to 1.20.4; 1.20.5+ has packet changes
    cutoff_1_20_4 = (1, 20, 4)
    if v_tuple <= cutoff_1_20_4:
        return (
            VerificationMode.FULL_BOT,
            "mineflayer",
            f"Minecraft {minecraft_version} on {st} supported via Mineflayer protocol driver",
        )

    # 1.20.5+ or 1.21+
    if tech == BotTech.AUTO:
        return (
            VerificationMode.SMOKE_TEST,
            "none",
            f"Minecraft {minecraft_version} protocol negotiation falls back to smoke test mode",
        )

    return (
        VerificationMode.FULL_BOT,
        "mineflayer",
        f"Explicit Mineflayer requested for Minecraft {minecraft_version}",
    )
