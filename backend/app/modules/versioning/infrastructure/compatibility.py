from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from pathlib import Path

from app.modules.server.application.services.jar_service import validate_jar
from app.modules.shared.value_objects import MinecraftVersion
from app.modules.versioning.domain.value_objects import BotTech


class VerificationMode(enum.StrEnum):
    FULL_BOT = "full_bot"
    SMOKE_TEST = "smoke_test"


@dataclass(frozen=True)
class StrategyResult:
    mode: VerificationMode
    driver: str
    reason: str
    downgraded_from: str | None = None
    artifact_ok: bool = True

    def __iter__(self):
        yield self.mode
        yield self.driver
        yield self.reason


PLACEHOLDER_ARTIFACT: bytes = b"PK\x03\x04fakeplayer-next-placeholder"


def is_fakeplayer_artifact_usable(path: Path | str | None) -> tuple[bool, str | None]:
    """Decides whether the FakePlayer plugin artifact is usable.

    Pure helper: checks that path exists, is not the placeholder, and passes
    existing validate_jar size and magic checks without raising.
    """
    if path is None:
        return False, "plugin artifact missing or placeholder; falling back to smoke test"
    try:
        p = Path(path)
        if not p.is_file():
            return False, "plugin artifact missing or placeholder; falling back to smoke test"
        if (
            p.stat().st_size == len(PLACEHOLDER_ARTIFACT)
            and p.read_bytes() == PLACEHOLDER_ARTIFACT
        ):
            return False, "plugin artifact missing or placeholder; falling back to smoke test"
        validate_jar(str(p))
        return True, None
    except Exception:
        return False, "plugin artifact missing or placeholder; falling back to smoke test"


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
    artifact_path: Path | str | None = None,
) -> StrategyResult:
    """Determines verification mode, bot driver, and rationale (§3.5).

    Returns StrategyResult with mode, driver, reason, downgraded_from, and artifact_ok.
    """
    tech = bot_tech if isinstance(bot_tech, BotTech) else BotTech(str(bot_tech).lower())
    st = (server_type or "vanilla").lower()
    v_tuple = _parse_version_tuple(minecraft_version or "1.20.4")

    # Paper / Purpur
    if st in ("paper", "purpur"):
        if tech in (BotTech.AUTO, BotTech.FAKEPLAYER_NEXT):
            if artifact_path is not None:
                usable, reason = is_fakeplayer_artifact_usable(artifact_path)
                if not usable:
                    return StrategyResult(
                        mode=VerificationMode.SMOKE_TEST,
                        driver="none",
                        reason=reason
                        or "plugin artifact missing or placeholder; falling back to smoke test",
                        downgraded_from="fakeplayer_next",
                        artifact_ok=False,
                    )
            return StrategyResult(
                mode=VerificationMode.FULL_BOT,
                driver="fakeplayer_next",
                reason=f"Paper-based server ({st}) supported via FakePlayer-Next driver",
                downgraded_from=None,
                artifact_ok=True,
            )
        if tech == BotTech.MINEFLAYER:
            return StrategyResult(
                mode=VerificationMode.FULL_BOT,
                driver="mineflayer",
                reason="Explicit Mineflayer protocol driver requested for Paper server",
                downgraded_from=None,
                artifact_ok=True,
            )

    # If caller specifically requested FakePlayer-Next on non-Paper:
    if tech == BotTech.FAKEPLAYER_NEXT and st not in ("paper", "purpur"):
        return StrategyResult(
            mode=VerificationMode.SMOKE_TEST,
            driver="none",
            reason=f"FakePlayer-Next is Paper-only; {st} falls back to smoke test mode",
            downgraded_from="fakeplayer_next",
            artifact_ok=False,
        )

    # Forge / NeoForge
    if st in ("forge", "neoforge"):
        if tech == BotTech.AUTO:
            return StrategyResult(
                mode=VerificationMode.SMOKE_TEST,
                driver="none",
                reason=(
                    f"Modded loader {st} requires custom protocol handshake; "
                    "using smoke test mode"
                ),
                downgraded_from=None,
                artifact_ok=True,
            )
        return StrategyResult(
            mode=VerificationMode.FULL_BOT,
            driver="mineflayer",
            reason=f"Explicit Mineflayer requested for modded loader {st}",
            downgraded_from=None,
            artifact_ok=True,
        )

    # Non-Java or exotic loaders (e.g. bedrock, sponge, proxies, unknown) fall back to smoke test
    known_java_loaders = ("vanilla", "fabric", "spigot", "bukkit", "quilt")
    if st not in known_java_loaders:
        return StrategyResult(
            mode=VerificationMode.SMOKE_TEST,
            driver="none",
            reason=f"Server type '{st}' is unsupported for bot connection; using smoke test mode",
            downgraded_from=None,
            artifact_ok=True,
        )

    # Vanilla / Fabric / Spigot / Bukkit / Quilt
    # Mineflayer reliably negotiates up to 1.20.4; 1.20.5+ has packet changes
    cutoff_1_20_4 = (1, 20, 4)
    if v_tuple <= cutoff_1_20_4:
        return StrategyResult(
            mode=VerificationMode.FULL_BOT,
            driver="mineflayer",
            reason=(
                f"Minecraft {minecraft_version} on {st} "
                "supported via Mineflayer protocol driver"
            ),
            downgraded_from=None,
            artifact_ok=True,
        )

    # 1.20.5+ or 1.21+
    if tech == BotTech.AUTO:
        return StrategyResult(
            mode=VerificationMode.SMOKE_TEST,
            driver="none",
            reason=(
                f"Minecraft {minecraft_version} protocol negotiation "
                "falls back to smoke test mode"
            ),
            downgraded_from=None,
            artifact_ok=True,
        )

    return StrategyResult(
        mode=VerificationMode.FULL_BOT,
        driver="mineflayer",
        reason=f"Explicit Mineflayer requested for Minecraft {minecraft_version}",
        downgraded_from=None,
        artifact_ok=True,
    )
