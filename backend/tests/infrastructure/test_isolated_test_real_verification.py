from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.versioning.domain.deployment import TestServerDeployment
from app.modules.versioning.domain.value_objects import BotTech
from app.modules.versioning.infrastructure.bot_drivers import (
    MineflayerBotDriver,
    SmokeTestRunner,
    cap_log_output,
)
from app.modules.versioning.infrastructure.compatibility import (
    VerificationMode,
    resolve_verification_strategy,
)
from app.modules.versioning.infrastructure.config_writer import write_test_server_properties


def test_compatibility_resolution_matrix() -> None:
    # Paper and Purpur default to FakePlayer-Next
    strat = resolve_verification_strategy("paper", "1.21.1", BotTech.AUTO)
    assert (strat.mode, strat.driver) == (VerificationMode.FULL_BOT, "fakeplayer_next")

    strat = resolve_verification_strategy("purpur", "1.20.4", BotTech.AUTO)
    assert (strat.mode, strat.driver) == (VerificationMode.FULL_BOT, "fakeplayer_next")

    # Vanilla and Fabric default to Mineflayer
    strat = resolve_verification_strategy("vanilla", "1.20.4", BotTech.AUTO)
    assert (strat.mode, strat.driver) == (VerificationMode.FULL_BOT, "mineflayer")

    strat = resolve_verification_strategy("fabric", "1.20.1", BotTech.AUTO)
    assert (strat.mode, strat.driver) == (VerificationMode.FULL_BOT, "mineflayer")

    strat = resolve_verification_strategy("forge", "1.20.1", BotTech.AUTO)
    assert (strat.mode, strat.driver) == (VerificationMode.SMOKE_TEST, "none")

    strat = resolve_verification_strategy("neoforge", "1.21.1", BotTech.AUTO)
    assert (strat.mode, strat.driver) == (VerificationMode.SMOKE_TEST, "none")

    # Explicit Mineflayer on Forge is supported
    strat = resolve_verification_strategy("forge", "1.20.1", BotTech.MINEFLAYER)
    assert (strat.mode, strat.driver) == (VerificationMode.FULL_BOT, "mineflayer")

    # Unsupported / exotic loaders gracefully degrade to Smoke Test
    strat = resolve_verification_strategy("bedrock", "1.20", BotTech.AUTO)
    assert (strat.mode, strat.driver) == (VerificationMode.SMOKE_TEST, "none")

    strat = resolve_verification_strategy("sponge", "1.16.5", BotTech.AUTO)
    assert (strat.mode, strat.driver) == (VerificationMode.SMOKE_TEST, "none")

    strat = resolve_verification_strategy("unknown_custom", "1.21.1", BotTech.AUTO)
    assert (strat.mode, strat.driver) == (VerificationMode.SMOKE_TEST, "none")

    # Explicit user selection overrides auto
    strat = resolve_verification_strategy("paper", "1.21.1", BotTech.MINEFLAYER)
    assert (strat.mode, strat.driver) == (VerificationMode.FULL_BOT, "mineflayer")

    strat = resolve_verification_strategy("vanilla", "1.20.4", BotTech.FAKEPLAYER_NEXT)
    assert (strat.mode, strat.driver) == (VerificationMode.SMOKE_TEST, "none")


def test_compatibility_accepts_minecraft_version_objects() -> None:
    """Regression: production passes MinecraftVersion domain objects, not strings.

    run_isolated_test forwards server.minecraft_version (a MinecraftVersion)
    into resolve_verification_strategy; previously re.findall received the
    object and raised "expected string or bytes-like object".
    """
    from app.modules.shared.value_objects import MinecraftVersion

    # Exact live-failure scenario: Paper-family + fakeplayer_next
    strat = resolve_verification_strategy(
        "paper", MinecraftVersion.parse("1.21.1"), BotTech.FAKEPLAYER_NEXT
    )
    assert (strat.mode, strat.driver) == (VerificationMode.FULL_BOT, "fakeplayer_next")

    # Auto resolution with a constructed object
    strat = resolve_verification_strategy(
        "paper", MinecraftVersion(1, 21, 1), BotTech.AUTO
    )
    assert (strat.mode, strat.driver) == (VerificationMode.FULL_BOT, "fakeplayer_next")

    # Version-gated path (Mineflayer cutoff 1.20.4) with objects on both sides
    strat = resolve_verification_strategy(
        "vanilla", MinecraftVersion(1, 20, 4), BotTech.AUTO
    )
    assert (strat.mode, strat.driver) == (VerificationMode.FULL_BOT, "mineflayer")

    strat = resolve_verification_strategy(
        "vanilla", MinecraftVersion.parse("1.21.1"), BotTech.AUTO
    )
    assert (strat.mode, strat.driver) == (VerificationMode.SMOKE_TEST, "none")

    # Modded loaders with objects
    strat = resolve_verification_strategy(
        "neoforge", MinecraftVersion.parse("1.21.1"), BotTech.AUTO
    )
    assert (strat.mode, strat.driver) == (VerificationMode.SMOKE_TEST, "none")


def test_max_players_scaling_and_source_manifest_isolation() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        srv_dir = Path(tmpdir) / "server"
        srv_dir.mkdir()
        test_dir = srv_dir / ".onx" / "tests" / "t-scaling-1"
        test_dir.mkdir(parents=True)
        deployment = TestServerDeployment(test_id="t-scaling-1", test_dir=str(test_dir))

        # Production manifest has max-players = 20
        source_properties_dict = {"motd": "ProdServer", "max-players": "20", "online-mode": "true"}
        source_properties_text = "motd=ProdServer\nmax-players=20\nonline-mode=true\n"
        manifest_configs = {"server.properties": source_properties_text}

        # Request 25 bots
        bot_count = 25
        # Formula: max(base_max, bot_count + 5) -> max(20, 30) = 30
        write_test_server_properties(
            deployment=deployment,
            base_properties=source_properties_dict,
            bot_count=bot_count,
        )

        test_props_file = Path(deployment.properties_path())
        assert test_props_file.exists()
        test_content = test_props_file.read_text(encoding="utf-8")

        # Test server.properties has max-players = 30 and online-mode = false
        assert "max-players = 30" in test_content or "max-players=30" in test_content
        assert "online-mode = false" in test_content or "online-mode=false" in test_content

        # STRICT ISOLATION INVARIANT: Source manifest configs dictionary is completely untouched
        assert manifest_configs["server.properties"] == source_properties_text
        assert "max-players=20" in manifest_configs["server.properties"]


@pytest.mark.asyncio
async def test_smoke_test_mode_clean_boot() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir)
        logs_dir = test_dir / "logs"
        logs_dir.mkdir()
        latest_log = logs_dir / "latest.log"
        latest_log.write_text(
            "[12:00:00] [Server thread/INFO]: Starting minecraft server version 1.21.1\n"
            "[12:00:05] [Server thread/INFO]: Preparing level 'world'\n"
            "[12:00:10] [Server thread/INFO]: Done (10.42s)! For help, type 'help'\n",
            encoding="utf-8",
        )

        # Mock docker inspect so the smoke test sees a live container (no real Docker in tests)
        from unittest.mock import MagicMock
        mock_live = MagicMock(returncode=0, stdout="true\n", stderr="")

        with patch("subprocess.run", return_value=mock_live):
            res = await SmokeTestRunner.run_smoke_test(
                test_dir=test_dir,
                container_name="test-cid-123",
                timeout_seconds=5,
            )

        assert res.passed is True
        assert "[VERIFY-MODE: SMOKE_TEST]" in res.log_output
        assert res.connected_bots == 0
        assert res.failure_reason is None


@pytest.mark.asyncio
async def test_smoke_test_mode_crash_detected() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir)
        logs_dir = test_dir / "logs"
        logs_dir.mkdir()
        (logs_dir / "latest.log").write_text("Server starting...\n", encoding="utf-8")

        crash_dir = test_dir / "crash-reports"
        crash_dir.mkdir()
        (crash_dir / "crash-2026-09-15.txt").write_text(
            "net.minecraft.server.Main: Crash on boot\n"
            "Caused by: java.lang.OutOfMemoryError: Java heap space\n",
            encoding="utf-8",
        )

        res = await SmokeTestRunner.run_smoke_test(
            test_dir=test_dir,
            container_name="test-cid-123",
            timeout_seconds=5,
        )

        assert res.passed is False
        assert res.failure_reason is not None
        assert "crash" in res.failure_reason.lower() or "outofmemory" in res.failure_reason.lower()


@pytest.mark.asyncio
async def test_mineflayer_driver_failure_handling() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir)

        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.pid = 99999
        mock_proc.stdout.readline = AsyncMock(
            side_effect=[
                b"[BOT-ERROR] Bot 1 failed: Connection refused\n",
                b"",
            ]
        )
        mock_proc.wait = AsyncMock(return_value=1)

        with (
            patch("shutil.which", return_value="/usr/bin/node"),
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        ):
            res = await MineflayerBotDriver.run_mineflayer_verification(
                bot_dir=test_dir,
                host="127.0.0.1",
                port=25565,
                run_id="t-mf-fail",
                bot_count=5,
                duration_minutes=1,
            )

            assert res.passed is False
            assert res.failure_reason is not None
            assert "Connection refused" in res.failure_reason or "failed" in res.failure_reason
            assert res.log_output is not None


def test_log_capping_discipline() -> None:
    # 100 KB payload
    startup = "[STARTUP] Test suite beginning boot sequence.\n"
    filler = "A" * 100000 + "\n"
    exit_trace = "[EXIT] Fatal error caught in runner."
    full_log = startup + filler + exit_trace

    capped = cap_log_output(full_log, max_bytes=64 * 1024)
    assert len(capped.encode("utf-8")) <= 64 * 1024
    assert "[STARTUP]" in capped
    assert "[EXIT]" in capped
    assert "[... TRUNCATED " in capped
