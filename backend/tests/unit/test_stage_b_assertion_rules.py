from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.versioning.domain.value_objects import (
    AssertionRulesConfig,
    BotVerificationConfig,
)
from app.modules.versioning.infrastructure.verifiers import (
    FakePlayerVerifier,
    MineflayerVerifier,
    SmokeTestVerifier,
    evaluate_common_rules,
)


def test_assertion_rules_config_defaults() -> None:
    rules = AssertionRulesConfig()
    assert rules.min_connected_bots_ratio is None
    assert rules.max_disconnects == 0
    assert rules.min_boot_seconds == 0.0
    assert rules.max_boot_seconds is None
    assert rules.disallow_crash_reports is True
    assert rules.disallow_error_logs is False
    assert rules.required_log_markers == []
    assert rules.forbidden_log_markers == []


def test_assertion_rules_config_validation() -> None:
    # Invalid min_connected_bots_ratio
    with pytest.raises(ValueError, match="min_connected_bots_ratio must be between 0.0 and 1.0"):
        AssertionRulesConfig.from_dict({"min_connected_bots_ratio": 1.5})

    with pytest.raises(ValueError, match="min_connected_bots_ratio must be between 0.0 and 1.0"):
        AssertionRulesConfig.from_dict({"min_connected_bots_ratio": -0.1})

    # Negative max_disconnects
    with pytest.raises(ValueError, match="max_disconnects cannot be negative"):
        AssertionRulesConfig.from_dict({"max_disconnects": -1})

    # Negative min_boot_seconds
    with pytest.raises(ValueError, match="min_boot_seconds cannot be negative"):
        AssertionRulesConfig.from_dict({"min_boot_seconds": -5.0})

    # max_boot_seconds < min_boot_seconds
    with pytest.raises(ValueError, match="cannot be less than min_boot_seconds"):
        AssertionRulesConfig.from_dict({"min_boot_seconds": 30.0, "max_boot_seconds": 10.0})

    # Valid dictionary round-trip
    valid_data = {
        "min_connected_bots_ratio": 0.8,
        "max_disconnects": 2,
        "min_boot_seconds": 5.0,
        "max_boot_seconds": 120.0,
        "disallow_crash_reports": True,
        "disallow_error_logs": True,
        "required_log_markers": ["Server marked as running!"],
        "forbidden_log_markers": ["NullPointerException"],
    }
    cfg = AssertionRulesConfig.from_dict(valid_data)
    assert cfg.min_connected_bots_ratio == 0.8
    assert cfg.max_disconnects == 2
    assert cfg.to_dict() == valid_data


def test_evaluate_common_rules_markers_and_crashes() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir)

        # 1. Clean run with required marker present
        rules = AssertionRulesConfig(
            required_log_markers=["Done (1.234s)!"],
            forbidden_log_markers=["FATAL EXCEPTION"],
        )
        items, fail_reason, crash_info = evaluate_common_rules(
            rules, "Starting server\nDone (1.234s)!\nReady.", test_dir
        )
        assert fail_reason is None
        assert all(it.passed for it in items)

        # 2. Missing required marker
        items, fail_reason, _ = evaluate_common_rules(
            rules, "Starting server\nReady without done marker.", test_dir
        )
        assert fail_reason is not None
        assert "was not found in server logs" in fail_reason
        missing_item = next(it for it in items if it.name.startswith("required_marker:"))
        assert missing_item.passed is False

        # 3. Forbidden marker found
        items, fail_reason, _ = evaluate_common_rules(
            rules, "Starting server\nFATAL EXCEPTION in thread\nDone (1.234s)!", test_dir
        )
        assert fail_reason is not None
        assert "was detected in server logs" in fail_reason
        forbidden_item = next(it for it in items if it.name.startswith("forbidden_marker:"))
        assert forbidden_item.passed is False

        # 4. Crash report detected with culprit mod
        crash_dir = test_dir / "crash-reports"
        crash_dir.mkdir(parents=True, exist_ok=True)
        crash_file = crash_dir / "crash-2026-09-28_12.00.00-server.txt"
        crash_file.write_text(
            "net.minecraftforge.fml.ModLoadingException: "
            "Mod ironchests encountered an error\n"
            "Caused by: java.lang.NullPointerException\n"
            "\tat com.example.ironchests.Init.load(Init.java:42)\n"
        )
        items, fail_reason, crash_info = evaluate_common_rules(rules, "server log", test_dir)
        assert fail_reason is not None
        assert "Crash detected" in fail_reason
        assert crash_info["suspected_culprit_mods"] != []
        assert "ironchest" in crash_info["suspected_culprit_mods"][0].lower()


@pytest.mark.asyncio
async def test_smoke_test_verifier_no_bot_ratio_requirement() -> None:
    verifier = SmokeTestVerifier()
    spec = MagicMock()
    spec.bot_config = BotVerificationConfig(duration_seconds=10.0)
    spec.minecraft_version = "1.20.4"
    handle = MagicMock()
    strategy = MagicMock()
    strategy.downgraded_from = None

    with tempfile.TemporaryDirectory() as tmpdir:
        handle.test_dir = tmpdir
        handle.container_name = "test-container"

        with patch(
            "app.modules.versioning.infrastructure.verifiers.SmokeTestRunner.run_smoke_test",
            new_callable=AsyncMock,
        ) as mock_smoke:
            mock_smoke.return_value = MagicMock(
                passed=True, failure_reason=None, log_output="Booted"
            )
            verdict = await verifier.verify(
                spec=spec,
                handle=handle,
                rules=AssertionRulesConfig(),
                strategy=strategy,
                container_ip="127.0.0.1",
                rcon_password=None,
                on_log=lambda _msg: None,
            )
            assert verdict.passed is True
            # Verifies no synthetic bot ratio requirement
            assert not any("ratio" in item.name for item in verdict.assertions)


@pytest.mark.asyncio
async def test_zero_target_bot_count_handling() -> None:
    # 1. Mineflayer with bot_count=0 passes cleanly without spawning bots
    mineflayer_v = MineflayerVerifier()
    spec = MagicMock()
    spec.bot_config = BotVerificationConfig(bot_count=0, duration_seconds=5.0)
    handle = MagicMock()
    strategy = MagicMock()

    with tempfile.TemporaryDirectory() as tmpdir:
        handle.test_dir = tmpdir
        verdict = await mineflayer_v.verify(
            spec=spec,
            handle=handle,
            rules=AssertionRulesConfig(),
            strategy=strategy,
            container_ip="127.0.0.1",
            rcon_password=None,
            on_log=lambda _msg: None,
        )
        assert verdict.passed is True
        assert verdict.connected_bots == 0
        ratio_item = next(it for it in verdict.assertions if it.name == "bot_connection_ratio")
        assert ratio_item.passed is True

    # 2. FakePlayer with bot_count=0 passes cleanly
    fakeplayer_v = FakePlayerVerifier()
    with tempfile.TemporaryDirectory() as tmpdir:
        handle.test_dir = tmpdir
        handle.container_name = "fp-test"
        with patch("asyncio.to_thread") as mock_exec:
            # Container liveness check returns running=true
            liveness_res = MagicMock(returncode=0, stdout="true")
            mock_exec.return_value = liveness_res
            verdict = await fakeplayer_v.verify(
                spec=spec,
                handle=handle,
                rules=AssertionRulesConfig(),
                strategy=strategy,
                container_ip="127.0.0.1",
                rcon_password=None,
                on_log=lambda _msg: None,
            )
            assert verdict.passed is True
            assert verdict.connected_bots == 0
            spawn_item = next(it for it in verdict.assertions if it.name == "bot_spawn_exact")
            assert spawn_item.passed is True


@pytest.mark.asyncio
async def test_mineflayer_legacy_vs_tightened_ratio() -> None:
    mineflayer_v = MineflayerVerifier()
    spec = MagicMock()
    spec.test_id = "test-12345678"
    spec.bot_config = BotVerificationConfig(bot_count=10, duration_seconds=10.0)
    handle = MagicMock()
    strategy = MagicMock()

    with tempfile.TemporaryDirectory() as tmpdir:
        handle.test_dir = tmpdir
        with patch(
            "app.modules.versioning.infrastructure.verifiers.MineflayerBotDriver.run_mineflayer_verification",
            new_callable=AsyncMock,
        ) as mock_mf:
            # 2 out of 10 bots connected
            mock_mf.return_value = MagicMock(
                passed=True,  # >=1 bot connected satisfies legacy driver
                connected_bots=2,
                disconnects=0,
                logs=[],
            )

            # Legacy mode (no rules.min_connected_bots_ratio): passes
            verdict_legacy = await mineflayer_v.verify(
                spec=spec,
                handle=handle,
                rules=AssertionRulesConfig(min_connected_bots_ratio=None),
                strategy=strategy,
                container_ip="127.0.0.1",
                rcon_password=None,
                on_log=lambda _msg: None,
            )
            assert verdict_legacy.passed is True

            # Tightened mode requiring 80% (0.8): fails because 2/10 = 0.2 < 0.8
            verdict_tightened = await mineflayer_v.verify(
                spec=spec,
                handle=handle,
                rules=AssertionRulesConfig(min_connected_bots_ratio=0.8),
                strategy=strategy,
                container_ip="127.0.0.1",
                rcon_password=None,
                on_log=lambda _msg: None,
            )
            assert verdict_tightened.passed is False
            ratio_item = next(
                it for it in verdict_tightened.assertions if it.name == "bot_connection_ratio"
            )
            assert ratio_item.passed is False
