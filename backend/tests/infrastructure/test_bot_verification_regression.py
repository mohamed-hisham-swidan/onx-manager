from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.exceptions import UnsupportedBotTechError
from app.modules.versioning.domain.entities import ServerCommit
from app.modules.versioning.domain.value_objects import (
    BotTech,
    BotVerificationConfig,
    CommitManifest,
    TestRunStatus,
)
from app.modules.versioning.infrastructure.bot_drivers import (
    FakePlayerNextDriver,
)
from app.modules.versioning.infrastructure.compatibility import (
    VerificationMode,
    resolve_verification_strategy,
)
from app.modules.versioning.infrastructure.config_resolver import BotConfigResolver
from app.modules.versioning.infrastructure.resource_probe import ResourcePreflightProbe
from app.modules.versioning.infrastructure.storage_probe import StorageCapabilityProbe
from app.modules.versioning.infrastructure.test_runner import (
    DockerTestExecutionRunner,
    TestSpec,
)


def _setup_test_spec(
    tmpdir: str,
    test_id: str,
    server_type: str = "paper",
    bot_count: int = 5,
    bot_tech: BotTech = BotTech.FAKEPLAYER_NEXT,
    with_valid_artifact: bool = True,
) -> tuple[TestSpec, Path]:
    srv_dir = Path(tmpdir) / "server"
    srv_dir.mkdir(parents=True, exist_ok=True)
    (srv_dir / "server.properties").write_text(
        "motd=ProdServer\nonline-mode=true\n", encoding="utf-8"
    )

    test_dir = srv_dir / ".onx" / "tests" / test_id
    logs_dir = test_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "latest.log").write_text(
        "[12:00:10] [Server thread/INFO]: Done (4.20s)! For help, type 'help'\n",
        encoding="utf-8",
    )

    plugins_dir = test_dir / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    if with_valid_artifact:
        valid_jar = b"PK\x03\x04" + b"\x00" * 1_048_576
        (plugins_dir / "fakeplayer-next.jar").write_bytes(valid_jar)

    manifest = CommitManifest(
        server_type=server_type,
        minecraft_version="1.21.1",
        configs={"server.properties": "motd=TestServer\nonline-mode=true\n"},
    )
    commit = ServerCommit(
        id=f"c-{test_id}",
        server_id="srv-1",
        message="verification test",
        manifest=manifest,
    )
    bot_cfg = BotVerificationConfig(
        bot_count=bot_count,
        duration_minutes=1,
        bot_tech=bot_tech,
    )
    spec = TestSpec(
        test_id=test_id,
        server_id="srv-1",
        commit=commit,
        server_dir=str(srv_dir),
        bot_config=bot_cfg,
    )
    return spec, test_dir


@pytest.mark.asyncio
async def test_fakeplayer_partial_spawn_zero_spawns_fails() -> None:
    """Regression test 1: bot_count=5, action commands succeed (rc=0), but ALL

    spawn commands fail (rc!=0).
    Must result in FAILED, connected_bots == 0.
    """
    runner = DockerTestExecutionRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        spec, _ = _setup_test_spec(
            tmpdir,
            test_id="t-partial-zero",
            bot_count=5,
            with_valid_artifact=True,
        )

        def mock_subprocess(cmd, **_kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "inspect" in cmd_str:
                if "State.Running" in cmd_str:
                    return MagicMock(returncode=0, stdout="true\n", stderr="")
                return MagicMock(returncode=0, stdout="172.17.0.2\n", stderr="")
            if "rcon-cli" in cmd_str:
                # "spawn" command fails, "action" commands return 0
                parts = cmd_str.split("rcon-cli")[-1].strip().split()
                if len(parts) >= 2 and parts[1] == "spawn":
                    return MagicMock(returncode=1, stdout="", stderr="Error: cannot spawn bot")
                return MagicMock(returncode=0, stdout="OK\n", stderr="")
            return MagicMock(returncode=0, stdout="container-123\n", stderr="")

        with (
            patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
            patch.object(
                ResourcePreflightProbe, "assert_sufficient_resources", return_value=None
            ),
            patch("subprocess.run", side_effect=mock_subprocess),
        ):
            handle = await runner.run_test(spec)
            res = await handle.wait_for_completion()

        assert res.passed is False, f"Expected FAILED outcome, got passed={res.passed}"
        assert res.connected_bots == 0, f"Expected connected_bots=0, got {res.connected_bots}"
        assert handle.status == TestRunStatus.FAILED


@pytest.mark.asyncio
async def test_fakeplayer_partial_spawn_three_of_five_fails() -> None:
    """Regression test 2: bot_count=5, exactly 3/5 spawn commands return rc=0,

    2 fail.
    Must result in FAILED, connected_bots == 3, failure_reason states spawned/expected.
    """
    runner = DockerTestExecutionRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        spec, _ = _setup_test_spec(
            tmpdir,
            test_id="t-partial-three",
            bot_count=5,
            with_valid_artifact=True,
        )

        def mock_subprocess(cmd, **_kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "inspect" in cmd_str:
                if "State.Running" in cmd_str:
                    return MagicMock(returncode=0, stdout="true\n", stderr="")
                return MagicMock(returncode=0, stdout="172.17.0.2\n", stderr="")
            if "rcon-cli" in cmd_str:
                parts = cmd_str.split("rcon-cli")[-1].strip().split()
                if len(parts) >= 2 and parts[1] == "spawn":
                    # Bot username has index, e.g. onx-bot-t-partia-4 or -5 fail
                    bot_name = parts[2] if len(parts) > 2 else ""
                    if bot_name.endswith("-4") or bot_name.endswith("-5"):
                        return MagicMock(returncode=1, stdout="", stderr="Spawn limit reached")
                    return MagicMock(returncode=0, stdout="Bot spawned\n", stderr="")
                return MagicMock(returncode=0, stdout="OK\n", stderr="")
            return MagicMock(returncode=0, stdout="container-123\n", stderr="")

        with (
            patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
            patch.object(
                ResourcePreflightProbe, "assert_sufficient_resources", return_value=None
            ),
            patch("subprocess.run", side_effect=mock_subprocess),
        ):
            handle = await runner.run_test(spec)
            res = await handle.wait_for_completion()

        assert res.passed is False, f"Expected FAILED outcome, got passed={res.passed}"
        assert res.connected_bots == 3, f"Expected connected_bots=3, got {res.connected_bots}"
        assert handle.status == TestRunStatus.FAILED
        assert res.failure_reason is not None
        assert "3/5" in res.failure_reason, (
            f"Expected '3/5' in failure_reason: {res.failure_reason}"
        )


@pytest.mark.asyncio
async def test_fakeplayer_all_spawns_succeed() -> None:
    """Regression test 3: bot_count=5, 5/5 spawn ok -> PASSED, connected_bots == 5."""
    runner = DockerTestExecutionRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        spec, _ = _setup_test_spec(
            tmpdir,
            test_id="t-all-five",
            bot_count=5,
            with_valid_artifact=True,
        )

        def mock_subprocess(cmd, **_kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "inspect" in cmd_str:
                if "State.Running" in cmd_str:
                    return MagicMock(returncode=0, stdout="true\n", stderr="")
                return MagicMock(returncode=0, stdout="172.17.0.2\n", stderr="")
            if "rcon-cli" in cmd_str:
                return MagicMock(returncode=0, stdout="OK\n", stderr="")
            return MagicMock(returncode=0, stdout="container-123\n", stderr="")

        with (
            patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
            patch.object(
                ResourcePreflightProbe, "assert_sufficient_resources", return_value=None
            ),
            patch("subprocess.run", side_effect=mock_subprocess),
        ):
            handle = await runner.run_test(spec)
            res = await handle.wait_for_completion()

        assert res.passed is True
        assert res.connected_bots == 5
        assert handle.status == TestRunStatus.PASSED


def test_format_spawn_commands_three_per_bot_invariant() -> None:
    """Regression test 4: format_spawn_commands invariant: exactly 3 commands per bot

    (1 spawn, 2 actions). Pins the denominator.
    """
    bot_count = 5
    run_id = "testrun"
    cmds = FakePlayerNextDriver.format_spawn_commands(run_id=run_id, bot_count=bot_count)
    assert len(cmds) == bot_count * 3

    spawn_cmds = [c for c in cmds if c.split()[1] == "spawn"]
    action_cmds = [c for c in cmds if c.split()[1] == "action"]

    assert len(spawn_cmds) == bot_count
    assert len(action_cmds) == bot_count * 2

    for i in range(1, bot_count + 1):
        expected_bot = f"onx-bot-{run_id}-{i}"
        assert f"fp spawn {expected_bot}" in cmds
        assert f"fp action {expected_bot} forward" in cmds
        assert f"fp action {expected_bot} jump" in cmds


@pytest.mark.asyncio
async def test_fakeplayer_placeholder_or_missing_artifact_downgrades_to_smoke() -> None:
    """Regression test 5: FakePlayerNextDriver artifact missing or placeholder

    (30-byte) must downgrade to SMOKE_TEST with a non-empty reason mentioning
    'plugin artifact' that surfaces in failure_reason / evidence_bundle.assertions,
    without raising.
    """
    runner = DockerTestExecutionRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. Missing artifact case
        spec_missing, test_dir_missing = _setup_test_spec(
            tmpdir,
            test_id="t-art-missing",
            bot_count=5,
            with_valid_artifact=False,
        )
        missing_plugin = test_dir_missing / "plugins" / "fakeplayer-next.jar"
        if missing_plugin.exists():
            missing_plugin.unlink()

        strat = resolve_verification_strategy(
            server_type="paper",
            minecraft_version="1.21.1",
            bot_tech=BotTech.AUTO,
            artifact_path=missing_plugin,
        )
        assert strat.mode == VerificationMode.SMOKE_TEST
        assert strat.driver == "none"
        assert "plugin artifact" in strat.reason.lower()
        assert strat.downgraded_from == "fakeplayer_next"
        assert strat.artifact_ok is False

        # 2. Placeholder artifact case (30 bytes)
        spec_placeholder, test_dir_ph = _setup_test_spec(
            tmpdir,
            test_id="t-art-ph",
            bot_count=5,
            with_valid_artifact=False,
        )
        ph_plugin = test_dir_ph / "plugins" / "fakeplayer-next.jar"
        ph_plugin.write_bytes(b"PK\x03\x04fakeplayer-next-placeholder")

        strat_ph = resolve_verification_strategy(
            server_type="paper",
            minecraft_version="1.21.1",
            bot_tech=BotTech.AUTO,
            artifact_path=ph_plugin,
        )
        assert strat_ph.mode == VerificationMode.SMOKE_TEST
        assert strat_ph.driver == "none"
        assert "plugin artifact" in strat_ph.reason.lower()
        assert strat_ph.downgraded_from == "fakeplayer_next"
        assert strat_ph.artifact_ok is False

        # 3. Integration through runner: must not raise, surfaces downgrade in evidence
        def mock_subprocess(cmd, **_kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "inspect" in cmd_str:
                if "State.Running" in cmd_str:
                    return MagicMock(returncode=0, stdout="true\n", stderr="")
                return MagicMock(returncode=0, stdout="172.17.0.2\n", stderr="")
            return MagicMock(returncode=0, stdout="container-123\n", stderr="")

        with (
            patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
            patch.object(
                ResourcePreflightProbe, "assert_sufficient_resources", return_value=None
            ),
            patch("subprocess.run", side_effect=mock_subprocess),
        ):
            handle = await runner.run_test(spec_placeholder)
            res = await handle.wait_for_completion()

        assert res is not None
        assert res.connected_bots == 0
        assert res.failure_reason is not None
        assert "plugin artifact" in res.failure_reason.lower()


def test_folia_pufferfish_config_resolution_and_rejection() -> None:
    """Regression test 6: folia/pufferfish AUTO -> MINEFLAYER;

    explicit fakeplayer_next on folia/pufferfish -> UnsupportedBotTechError.
    """
    for server_type in ["folia", "pufferfish"]:
        # Auto resolution must be MINEFLAYER, NOT fakeplayer_next
        cfg = BotConfigResolver.resolve_config(server_type, run_overrides={"bot_tech": "auto"})
        assert cfg.bot_tech == BotTech.MINEFLAYER, (
            f"Expected {server_type} AUTO to resolve to MINEFLAYER, got {cfg.bot_tech}"
        )

        # Explicit fakeplayer_next must raise UnsupportedBotTechError with 400
        with pytest.raises(UnsupportedBotTechError) as exc_info:
            BotConfigResolver.resolve_config(
                server_type, run_overrides={"bot_tech": "fakeplayer_next"}
            )
        err = exc_info.value
        assert err.code == "UNSUPPORTED_BOT_TECH_FOR_SERVER_TYPE"
        assert err.http_status == 400
        assert "fakeplayer_next" in err.message
        assert server_type in err.message
