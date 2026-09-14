import pytest

from app.core.exceptions import UnsupportedBotTechError, ValidationError
from app.modules.versioning.domain.value_objects import BotTech, PlacementMode
from app.modules.versioning.infrastructure.config_resolver import BotConfigResolver


def test_config_layering_precedence() -> None:
    # 1. Global default layer only
    cfg1 = BotConfigResolver.resolve_config("vanilla")
    assert cfg1.bot_count == 10
    assert cfg1.duration_minutes == 15
    assert cfg1.placement_mode == PlacementMode.SIDECAR
    assert cfg1.bot_tech == BotTech.MINEFLAYER  # vanilla auto -> mineflayer

    # 2. Per-server layer overrides global
    server_settings = {"bot_count": 25, "duration_minutes": 30}
    cfg2 = BotConfigResolver.resolve_config("vanilla", server_bot_settings=server_settings)
    assert cfg2.bot_count == 25
    assert cfg2.duration_minutes == 30

    # 3. Per-run layer overrides per-server
    run_overrides = {"bot_count": 50, "duration_minutes": 60, "placement_mode": "in_container"}
    cfg3 = BotConfigResolver.resolve_config(
        "vanilla",
        server_bot_settings=server_settings,
        run_overrides=run_overrides,
    )
    assert cfg3.bot_count == 50
    assert cfg3.duration_minutes == 60
    assert cfg3.placement_mode == PlacementMode.IN_CONTAINER


def test_no_numeric_ceilings_on_bot_count_and_duration() -> None:
    """Design Spec §3.5.6 Invariant: NO artificial numeric ceilings on bot count or duration."""
    huge_run = {"bot_count": 500, "duration_minutes": 240}
    cfg = BotConfigResolver.resolve_config("vanilla", run_overrides=huge_run)
    assert cfg.bot_count == 500
    assert cfg.duration_minutes == 240

    # Negative or 0 must fail validation
    with pytest.raises(ValidationError):
        BotConfigResolver.resolve_config("vanilla", run_overrides={"bot_count": 0})

    with pytest.raises(ValidationError):
        BotConfigResolver.resolve_config("vanilla", run_overrides={"duration_minutes": -5})


def test_server_type_aware_auto_resolution() -> None:
    """Design Spec §3.5.2: auto resolves to fakeplayer_next on Paper family,
    mineflayer on others.
    """
    # Paper-family servers -> fakeplayer_next
    for s_type in ["paper", "purpur", "folia", "pufferfish"]:
        cfg = BotConfigResolver.resolve_config(s_type, run_overrides={"bot_tech": "auto"})
        assert cfg.bot_tech == BotTech.FAKEPLAYER_NEXT

    # Other server types -> mineflayer
    for s_type in ["vanilla", "forge", "fabric", "neoforge", "spigot", "bukkit"]:
        cfg = BotConfigResolver.resolve_config(s_type, run_overrides={"bot_tech": "auto"})
        assert cfg.bot_tech == BotTech.MINEFLAYER


def test_explicit_fakeplayer_next_on_unsupported_server_fails() -> None:
    """Explicit fakeplayer_next on Forge/Fabric must immediately fail with
    UnsupportedBotTechError.
    """
    with pytest.raises(UnsupportedBotTechError) as exc_info:
        BotConfigResolver.resolve_config("forge", run_overrides={"bot_tech": "fakeplayer_next"})

    err = exc_info.value
    assert err.code == "UNSUPPORTED_BOT_TECH_FOR_SERVER_TYPE"
    assert err.http_status == 400
    assert "fakeplayer_next" in err.message
    assert "forge" in err.message

    with pytest.raises(UnsupportedBotTechError):
        BotConfigResolver.resolve_config("fabric", run_overrides={"bot_tech": "fakeplayer_next"})


def test_explicit_mineflayer_allowed_on_paper() -> None:
    """Users may explicitly force mineflayer on Paper servers if desired."""
    cfg = BotConfigResolver.resolve_config("paper", run_overrides={"bot_tech": "mineflayer"})
    assert cfg.bot_tech == BotTech.MINEFLAYER


def test_invalid_bot_tech_and_placement_mode() -> None:
    with pytest.raises(ValidationError):
        BotConfigResolver.resolve_config("vanilla", run_overrides={"bot_tech": "invalid_tech"})

    with pytest.raises(ValidationError):
        BotConfigResolver.resolve_config("vanilla", run_overrides={"placement_mode": "floating"})
