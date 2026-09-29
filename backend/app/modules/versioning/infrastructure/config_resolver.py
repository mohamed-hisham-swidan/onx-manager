from __future__ import annotations

import json
from typing import Any

from app.core.exceptions import UnsupportedBotTechError, ValidationError
from app.core.settings_store import get_live_settings
from app.modules.versioning.domain.value_objects import (
    BotTech,
    BotVerificationConfig,
    PlacementMode,
)


class BotConfigResolver:
    """Resolves layered bot verification configuration per Design Spec §3.5.6.

    Precedence: (a) Global LiveSettings -> (b) Per-server JSON override -> (c) Per-run override.
    Enforces server-type-aware auto bot_tech selection and zero arbitrary numeric ceilings.
    """

    PAPER_FAMILY_TYPES: frozenset[str] = frozenset({"paper", "purpur"})

    @classmethod
    def resolve_config(
        cls,
        server_type: str,
        server_bot_settings: dict[str, Any] | str | None = None,
        run_overrides: dict[str, Any] | None = None,
    ) -> BotVerificationConfig:
        """Resolves the effective BotVerificationConfig from the three layers."""
        # 1. Global defaults (Layer A)
        try:
            live = get_live_settings()
            global_defaults = getattr(live, "bot_verify_defaults", {}) or {}
            def_join_stagger = getattr(live, "bot_join_stagger_seconds", 3.0)
            def_connect_grace = getattr(live, "bot_connect_grace_seconds", 60.0)
            def_watchdog = getattr(live, "bot_watchdog_overrun_seconds", None)
            if def_watchdog is None:
                def_watchdog = getattr(live, "bot_watchdog_overrun_minutes", 5.0) * 60.0
        except Exception:
            global_defaults = {}
            def_join_stagger = 3.0
            def_connect_grace = 60.0
            def_watchdog = 300.0

        bot_count = global_defaults.get("bot_count", 10)
        duration_seconds = global_defaults.get("duration_seconds")
        if duration_seconds is None:
            duration_minutes = global_defaults.get("duration_minutes", 15)
            duration_seconds = float(duration_minutes * 60)
        raw_tech = global_defaults.get("bot_tech", "auto")
        raw_placement = global_defaults.get("placement_mode", "sidecar")
        join_stagger = global_defaults.get("join_stagger_seconds", def_join_stagger)
        connect_grace = global_defaults.get("connect_grace_seconds", def_connect_grace)
        watchdog_overrun = global_defaults.get("watchdog_overrun_seconds")
        if watchdog_overrun is None:
            watchdog_overrun = global_defaults.get(
                "watchdog_overrun_minutes", def_watchdog / 60.0
            )
            if watchdog_overrun is not None:
                watchdog_overrun = float(watchdog_overrun) * 60.0
            else:
                watchdog_overrun = def_watchdog
        raw_assertion_rules = global_defaults.get("assertion_rules", {})

        # 2. Per-server overrides (Layer B)
        server_dict: dict[str, Any] = {}
        if server_bot_settings:
            if isinstance(server_bot_settings, str):
                try:
                    server_dict = json.loads(server_bot_settings)
                except Exception:
                    server_dict = {}
            elif isinstance(server_bot_settings, dict):
                server_dict = server_bot_settings

        if server_dict.get("bot_count") is not None:
            bot_count = int(server_dict["bot_count"])
        if server_dict.get("duration_seconds") is not None:
            duration_seconds = float(server_dict["duration_seconds"])
        elif server_dict.get("duration_minutes") is not None:
            duration_seconds = float(server_dict["duration_minutes"]) * 60.0
        if server_dict.get("bot_tech") is not None:
            raw_tech = str(server_dict["bot_tech"])
        if server_dict.get("placement_mode") is not None:
            raw_placement = str(server_dict["placement_mode"])
        if server_dict.get("join_stagger_seconds") is not None:
            join_stagger = float(server_dict["join_stagger_seconds"])
        if server_dict.get("connect_grace_seconds") is not None:
            connect_grace = float(server_dict["connect_grace_seconds"])
        if server_dict.get("watchdog_overrun_seconds") is not None:
            watchdog_overrun = float(server_dict["watchdog_overrun_seconds"])
        elif server_dict.get("watchdog_overrun_minutes") is not None:
            watchdog_overrun = float(server_dict["watchdog_overrun_minutes"]) * 60.0
        if server_dict.get("assertion_rules") is not None:
            raw_assertion_rules = server_dict["assertion_rules"]

        # 3. Per-run overrides (Layer C / Layer D)
        run_dict = run_overrides or {}
        if run_dict.get("bot_count") is not None:
            bot_count = int(run_dict["bot_count"])
        if run_dict.get("duration_seconds") is not None:
            duration_seconds = float(run_dict["duration_seconds"])
        elif run_dict.get("duration_minutes") is not None:
            duration_seconds = float(run_dict["duration_minutes"]) * 60.0
        if run_dict.get("bot_tech") is not None:
            raw_tech = str(run_dict["bot_tech"])
        if run_dict.get("placement_mode") is not None:
            raw_placement = str(run_dict["placement_mode"])
        if run_dict.get("join_stagger_seconds") is not None:
            join_stagger = float(run_dict["join_stagger_seconds"])
        if run_dict.get("connect_grace_seconds") is not None:
            connect_grace = float(run_dict["connect_grace_seconds"])
        if run_dict.get("watchdog_overrun_seconds") is not None:
            watchdog_overrun = float(run_dict["watchdog_overrun_seconds"])
        elif run_dict.get("watchdog_overrun_minutes") is not None:
            watchdog_overrun = float(run_dict["watchdog_overrun_minutes"]) * 60.0
        if run_dict.get("assertion_rules") is not None:
            raw_assertion_rules = run_dict["assertion_rules"]

        # Positive value assertions (NO upper ceiling, only physical sanity)
        if bot_count < 1:
            raise ValidationError(
                message=f"bot_count must be at least 1, got {bot_count}",
                field="bot_count",
            )
        if duration_seconds < 10.0:
            raise ValidationError(
                message=f"duration_seconds must be at least 10, got {duration_seconds}",
                field="duration_seconds",
            )

        from app.modules.versioning.domain.value_objects import AssertionRulesConfig

        if isinstance(raw_assertion_rules, AssertionRulesConfig):
            assertion_rules = raw_assertion_rules
        elif isinstance(raw_assertion_rules, dict):
            assertion_rules = AssertionRulesConfig.from_dict(raw_assertion_rules)
        else:
            assertion_rules = AssertionRulesConfig()

        # Parse placement mode
        try:
            placement_mode = PlacementMode(str(raw_placement).lower())
        except ValueError as exc:
            raise ValidationError(
                message=(
                    f"Invalid placement_mode '{raw_placement}'. "
                    "Must be 'sidecar' or 'in_container'."
                ),
                field="placement_mode",
            ) from exc

        # Parse bot technology
        raw_tech_str = str(raw_tech).lower()
        if raw_tech_str == "auto":
            # Server-type-aware auto resolution
            if server_type.lower() in cls.PAPER_FAMILY_TYPES:
                bot_tech = BotTech.FAKEPLAYER_NEXT
            else:
                bot_tech = BotTech.MINEFLAYER
        elif raw_tech_str == "fakeplayer_next":
            if server_type.lower() not in cls.PAPER_FAMILY_TYPES:
                supported_str = ", ".join(sorted(cls.PAPER_FAMILY_TYPES))
                raise UnsupportedBotTechError(
                    bot_tech="fakeplayer_next",
                    server_type=server_type,
                    message=(
                        "fakeplayer_next is only supported on Paper/Purpur family servers "
                        f"({supported_str}), not '{server_type}'. "
                        "Use 'mineflayer' or 'auto' instead."
                    ),
                )
            bot_tech = BotTech.FAKEPLAYER_NEXT
        elif raw_tech_str == "mineflayer":
            bot_tech = BotTech.MINEFLAYER
        elif raw_tech_str in ("none", "smoke_test"):
            bot_tech = BotTech.AUTO
        else:
            raise ValidationError(
                message=(
                    f"Invalid bot_tech '{raw_tech}'. "
                    "Must be 'auto', 'mineflayer', or 'fakeplayer_next'."
                ),
                field="bot_tech",
            )

        return BotVerificationConfig(
            bot_count=bot_count,
            duration_seconds=float(duration_seconds),
            bot_tech=bot_tech,
            placement_mode=placement_mode,
            join_stagger_seconds=float(join_stagger),
            connect_grace_seconds=float(connect_grace),
            watchdog_overrun_seconds=float(watchdog_overrun),
            assertion_rules=assertion_rules,
        )
