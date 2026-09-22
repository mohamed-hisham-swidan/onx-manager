from __future__ import annotations

import logging
import re
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.versioning.domain.entities import CommitManifest, ServerCommit
from app.modules.versioning.domain.value_objects import BotTech, BotVerificationConfig
from app.modules.versioning.infrastructure.bot_drivers import (
    BotCommandGroup,
    FakePlayerNextDriver,
    check_plugin_enabled,
    generate_bot_names,
    generate_bot_names_prefix,
)
from app.modules.versioning.infrastructure.resource_probe import ResourcePreflightProbe
from app.modules.versioning.infrastructure.storage_probe import StorageCapabilityProbe
from app.modules.versioning.infrastructure.test_runner import (
    DockerTestExecutionRunner,
    TestRunStatus,
    TestSpec,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


# ---------------------------------------------------------------------------
# 1. check_plugin_enabled unit tests
# ---------------------------------------------------------------------------


def test_check_plugin_enabled_golden_success() -> None:
    log_text = (FIXTURES_DIR / "golden_fp_success.log").read_text(encoding="utf-8")
    res = check_plugin_enabled(log_text, plugin_name="fakeplayer")
    assert res.enabled is True
    assert res.marker is None


def test_check_plugin_enabled_golden_missing_dependency() -> None:
    log_text = (FIXTURES_DIR / "golden_fp_missing_dep.log").read_text(encoding="utf-8")
    res = check_plugin_enabled(log_text, plugin_name="fakeplayer")
    assert res.enabled is False
    assert res.marker == "plugin failed to load: missing dependency"


def test_check_plugin_enabled_golden_corrupt_jar() -> None:
    log_text = (FIXTURES_DIR / "golden_fp_corrupt_jar.log").read_text(encoding="utf-8")
    res = check_plugin_enabled(log_text, plugin_name="fakeplayer")
    assert res.enabled is False
    assert res.marker == "plugin failed to load: corrupt jar"


def test_check_plugin_enabled_golden_ambiguous_plugin() -> None:
    log_text = (FIXTURES_DIR / "golden_fp_ambiguous_plugin.log").read_text(encoding="utf-8")
    res = check_plugin_enabled(log_text, plugin_name="fakeplayer")
    assert res.enabled is False
    assert res.marker == "plugin failed to load: ambiguous plugin name"


def test_check_plugin_enabled_could_not_load_generic() -> None:
    log_text = "[ERROR]: Could not load 'plugins/fakeplayer-0.4.4.jar' in 'plugins'\nSome error"
    res = check_plugin_enabled(log_text, plugin_name="fakeplayer")
    assert res.enabled is False
    assert res.marker == "plugin failed to load: could not load"


def test_check_plugin_enabled_invalid_plugin_yml() -> None:
    log_text = (
        "[ERROR]: Could not load 'plugins/fakeplayer.jar': Invalid plugin.yml\n"
        "org.bukkit.plugin.InvalidDescriptionException: Invalid plugin.yml"
    )
    res = check_plugin_enabled(log_text, plugin_name="fakeplayer")
    assert res.enabled is False
    assert res.marker == "plugin failed to load: invalid plugin.yml"


def test_check_plugin_enabled_empty_log() -> None:
    res = check_plugin_enabled("", plugin_name="fakeplayer")
    assert res.enabled is False
    assert res.marker == "plugin not enabled after boot"


def test_check_plugin_enabled_enabling_without_enabled() -> None:
    log_text = (
        "[21:50:21 INFO]: [fakeplayer] Enabling fakeplayer v0.4.4\n"
        "[21:50:22 INFO]: Server hanging or crashed before enabled\n"
    )
    res = check_plugin_enabled(log_text, plugin_name="fakeplayer")
    assert res.enabled is False
    assert res.marker == "plugin not enabled after boot"


def test_check_plugin_enabled_different_plugin_enabled() -> None:
    log_text = (
        "[21:50:21 INFO]: [CommandAPI] Enabling CommandAPI v12.0.0\n"
        "[21:50:23 INFO]: [CommandAPI] Enabled in 150 ms\n"
    )
    res = check_plugin_enabled(log_text, plugin_name="fakeplayer")
    assert res.enabled is False
    assert res.marker == "plugin not enabled after boot"


def test_check_plugin_enabled_windows_line_endings() -> None:
    log_text = (
        "[21:50:21 INFO]: [fakeplayer] Enabling fakeplayer v0.4.4\r\n"
        "[21:50:23 INFO]: [fakeplayer] Enabled in 15296 ms\r\n"
    )
    res = check_plugin_enabled(log_text, plugin_name="fakeplayer")
    assert res.enabled is True
    assert res.marker is None


def test_check_plugin_enabled_large_log_performance() -> None:
    padding = "line of harmless log text without any keywords\n" * 20000  # ~1MB
    log_text = padding + "[fakeplayer] Enabled in 1234 ms\n"
    start = time.perf_counter()
    res = check_plugin_enabled(log_text, plugin_name="fakeplayer")
    elapsed = time.perf_counter() - start
    assert res.enabled is True
    assert res.marker is None
    assert elapsed < 0.2, f"Expected <0.2s, took {elapsed:.4f}s"


# ---------------------------------------------------------------------------
# 2. generate_bot_names unit tests
# ---------------------------------------------------------------------------


def test_generate_bot_names_rules() -> None:
    run_id = "testrun42"
    names = generate_bot_names(run_id, count=5)
    assert len(names) == 5
    assert len(set(names)) == 5  # unique within run

    prefix = generate_bot_names_prefix(run_id)
    assert prefix.startswith("onx")

    for name in names:
        assert len(name) <= 16
        assert re.match(r"^[a-z0-9]+$", name) is not None
        assert not name[0].isdigit()
        assert "-" not in name
        assert "_" not in name
        assert "." not in name
        assert name.startswith(prefix)

    # Determinism
    assert generate_bot_names(run_id, count=5) == names


def test_generate_bot_names_refuses_out_of_bounds() -> None:
    with pytest.raises(ValueError, match="between 1 and 999"):
        generate_bot_names("testrun", count=1000)

    with pytest.raises(ValueError, match="between 1 and 999"):
        generate_bot_names("testrun", count=0)

    with pytest.raises(ValueError, match="between 1 and 999"):
        generate_bot_names("testrun", count=-1)


# ---------------------------------------------------------------------------
# 3. Command grammar & format_spawn_commands
# ---------------------------------------------------------------------------


def test_format_spawn_commands_new_grammar() -> None:
    run_id = "runabc"
    groups = FakePlayerNextDriver.format_spawn_commands(run_id=run_id, bot_count=3)
    assert len(groups) == 3
    assert isinstance(groups[0], BotCommandGroup)

    for _i, grp in enumerate(groups, start=1):
        assert re.match(r"^[a-z0-9]+$", grp.name)
        assert len(grp.name) <= 16
        assert "-" not in grp.name
        assert grp.spawn == f"fp spawn {grp.name}"
        assert grp.actions == [
            f"fp move forward {grp.name}",
            f"fp jump continuous {grp.name}",
        ]
        assert grp.stop == f"fp stop {grp.name}"

        # Must NEVER contain 'fp action'
        for cmd in grp.all_commands:
            assert "fp action" not in cmd
        assert "fp action" not in grp.stop


# ---------------------------------------------------------------------------
# Helper for test runner mock setup
# ---------------------------------------------------------------------------


def _setup_runner_spec(tmpdir: str) -> tuple[TestSpec, Path]:
    srv_dir = Path(tmpdir) / "srv"
    srv_dir.mkdir(parents=True, exist_ok=True)
    test_id = "fp-verify-test-1"
    test_dir = srv_dir / ".onx" / "tests" / test_id
    test_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = test_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    plugins_dir = test_dir / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)

    # Put a valid non-placeholder jar in plugins so pre-launch passes
    jar_path = plugins_dir / "fakeplayer-0.4.4.jar"
    jar_path.write_bytes(b"PK\x03\x04" + b"\x00" * 1_048_576)

    manifest = CommitManifest(
        server_type="paper",
        minecraft_version="1.21.1",
        configs={"server.properties": "motd=TestServer\nonline-mode=false\n"},
    )
    spec = TestSpec(
        test_id=test_id,
        server_id="srv-fp-1",
        commit=ServerCommit(
            id="commit-fp-1",
            server_id="srv-fp-1",
            message="fp test",
            manifest=manifest,
        ),
        server_dir=str(srv_dir),
        bot_config=BotVerificationConfig(
            bot_tech=BotTech.FAKEPLAYER_NEXT,
            bot_count=5,
            duration_minutes=0.01,
        ),
        minecraft_version="1.21.1",
    )
    return spec, test_dir


# ---------------------------------------------------------------------------
# 4. Wiring: post-boot log check downgrade & pass
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fakeplayer_wiring_plugin_enabled_proceeds_to_spawn() -> None:
    """When check_plugin_enabled succeeds, run stays fakeplayer_next and spawns bots."""
    runner = DockerTestExecutionRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        spec, test_dir = _setup_runner_spec(tmpdir)
        (test_dir / "logs" / "latest.log").write_text(
            "Done (1.234s)! For help, type 'help'\n"
            "[fakeplayer] Enabling fakeplayer v0.4.4\n"
            "[fakeplayer] Enabled in 15296 ms\n",
            encoding="utf-8",
        )

        executed_cmds: list[list[str]] = []

        def mock_subprocess(cmd, **_kwargs):
            cmd_list = cmd if isinstance(cmd, list) else [str(cmd)]
            executed_cmds.append(cmd_list)
            cmd_str = " ".join(cmd_list)

            if "inspect" in cmd_str:
                if "State.Running" in cmd_str:
                    return MagicMock(returncode=0, stdout="true\n", stderr="")
                return MagicMock(returncode=0, stdout="172.17.0.2\n", stderr="")
            if "rcon-cli" in cmd_str:
                return MagicMock(returncode=0, stdout="Done\n", stderr="")
            return MagicMock(returncode=0, stdout="container-123\n", stderr="")

        with (
            patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
            patch.object(ResourcePreflightProbe, "assert_sufficient_resources", return_value=None),
            patch.object(runner, "_persist_test_outcome", new_callable=AsyncMock),
            patch.object(runner, "_persist_runtime", new_callable=AsyncMock),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch("subprocess.run", side_effect=mock_subprocess),
        ):
            handle = await runner.run_test(spec)
            res = await handle.wait_for_completion()

        assert res.passed is True
        assert res.connected_bots == 5
        assert handle.status == TestRunStatus.PASSED

        # Check evidence assertions
        evidence = runner._evidence_store.get(spec.test_id, {})
        assertions = evidence.get("assertions", {})
        assert assertions.get("plugin_enabled") is True
        assert assertions.get("spawn_ok") == 5
        assert assertions.get("spawn_failed") == 0
        assert assertions.get("actions_ok") == 10  # 2 actions per bot * 5 bots
        assert assertions.get("actions_failed") == 0
        assert "bot_names_prefix" in assertions

        # Check command structure in executed rcon commands
        rcon_calls = [c for c in executed_cmds if "rcon-cli" in c]
        assert len(rcon_calls) >= 15  # 5 spawns + 10 actions + cleanup stops
        for c in rcon_calls:
            # Must NEVER contain "fp action"
            assert "fp action" not in " ".join(c)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "log_content,expected_marker",
    [
        (
            "Done (1.234s)!\n"
            "UnknownDependencyException: Unknown/missing dependency plugins: [CommandAPI].\n",
            "plugin failed to load: missing dependency",
        ),
        (
            "Done (1.234s)!\njava.util.zip.ZipException: zip END header not found\n",
            "plugin failed to load: corrupt jar",
        ),
        (
            "Done (1.234s)!\nAmbiguous plugin name 'CommandAPI' for files\n",
            "plugin failed to load: ambiguous plugin name",
        ),
        (
            "Done (1.234s)!\nCould not load 'plugins/fakeplayer-0.4.4.jar' in 'plugins'\n",
            "plugin failed to load: could not load",
        ),
        (
            "Done (1.234s)!\nServer booted but fakeplayer was never enabled\n",
            "plugin not enabled after boot",
        ),
    ],
)
async def test_fakeplayer_wiring_downgrade_on_plugin_failure(
    log_content: str, expected_marker: str
) -> None:
    """When check_plugin_enabled fails, run downgrades to SMOKE_TEST without restart."""
    runner = DockerTestExecutionRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        spec, test_dir = _setup_runner_spec(tmpdir)
        (test_dir / "logs" / "latest.log").write_text(log_content, encoding="utf-8")

        rcon_called = False

        def mock_subprocess(cmd, **_kwargs):
            nonlocal rcon_called
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "rcon-cli" in cmd_str:
                rcon_called = True
            if "inspect" in cmd_str:
                if "State.Running" in cmd_str:
                    return MagicMock(returncode=0, stdout="true\n", stderr="")
                return MagicMock(returncode=0, stdout="172.17.0.2\n", stderr="")
            return MagicMock(returncode=0, stdout="container-123\n", stderr="")

        with (
            patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
            patch.object(ResourcePreflightProbe, "assert_sufficient_resources", return_value=None),
            patch.object(runner, "_persist_test_outcome", new_callable=AsyncMock),
            patch.object(runner, "_persist_runtime", new_callable=AsyncMock),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch("subprocess.run", side_effect=mock_subprocess),
        ):
            handle = await runner.run_test(spec)
            res = await handle.wait_for_completion()

        # Downgrades to SMOKE_TEST, smoke test passes because Done line is present
        assert res.passed is True
        assert res.connected_bots == 0
        assert rcon_called is False  # No fp spawn attempted on downgrade

        # Check downgrade reason
        expected_reason = f"plugin verification failed: {expected_marker}"
        assert res.failure_reason == expected_reason

        evidence = runner._evidence_store.get(spec.test_id, {})
        assertions = evidence.get("assertions", {})
        assert assertions.get("strategy_downgraded_from") == "fakeplayer_next"
        assert assertions.get("downgrade_reason") == expected_reason
        assert assertions.get("plugin_enabled") is False


@pytest.mark.asyncio
async def test_fakeplayer_wiring_unreadable_log_downgrades() -> None:
    """Unreadable log file triggers class-A downgrade with 'plugin log unreadable'."""
    runner = DockerTestExecutionRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        spec, test_dir = _setup_runner_spec(tmpdir)
        log_file = test_dir / "logs" / "latest.log"
        log_file.write_text("Done (1.234s)!\n", encoding="utf-8")

        def mock_subprocess(cmd, **_kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "inspect" in cmd_str:
                if "State.Running" in cmd_str:
                    return MagicMock(returncode=0, stdout="true\n", stderr="")
                return MagicMock(returncode=0, stdout="172.17.0.2\n", stderr="")
            return MagicMock(returncode=0, stdout="container-123\n", stderr="")

        # Make reading the log raise after boot check
        original_read_text = Path.read_text
        call_count = 0

        def flaky_read_text(self, *args, **kwargs):
            nonlocal call_count
            if "latest.log" in str(self):
                call_count += 1
                if call_count == 2:
                    raise OSError("Simulated disk read error")
            return original_read_text(self, *args, **kwargs)

        with (
            patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
            patch.object(ResourcePreflightProbe, "assert_sufficient_resources", return_value=None),
            patch.object(runner, "_persist_test_outcome", new_callable=AsyncMock),
            patch.object(runner, "_persist_runtime", new_callable=AsyncMock),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch("subprocess.run", side_effect=mock_subprocess),
            patch.object(Path, "read_text", new=flaky_read_text),
        ):
            handle = await runner.run_test(spec)
            res = await handle.wait_for_completion()

        assert res.passed is True
        expected_reason = "plugin verification failed: plugin log unreadable"
        assert res.failure_reason == expected_reason


# ---------------------------------------------------------------------------
# 5. Spawn accounting: failures, online, invalid name
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fakeplayer_accounting_partial_and_online_replies() -> None:
    """Spawns count iff rc == 0 and stdout does not contain 'is online' / 'Invalid name' etc."""
    runner = DockerTestExecutionRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        spec, test_dir = _setup_runner_spec(tmpdir)
        (test_dir / "logs" / "latest.log").write_text(
            "Done (1.234s)!\n"
            "[fakeplayer] Enabling fakeplayer v0.4.4\n"
            "[fakeplayer] Enabled in 15296 ms\n",
            encoding="utf-8",
        )

        call_idx = 0

        def mock_subprocess(cmd, **_kwargs):
            nonlocal call_idx
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "inspect" in cmd_str:
                if "State.Running" in cmd_str:
                    return MagicMock(returncode=0, stdout="true\n", stderr="")
                return MagicMock(returncode=0, stdout="172.17.0.2\n", stderr="")
            if "rcon-cli" in cmd_str:
                parts = cmd_str.split("rcon-cli")[-1].strip().split()
                if len(parts) >= 2 and parts[1] == "spawn":
                    call_idx += 1
                    # Bot 1: OK
                    if call_idx == 1:
                        return MagicMock(
                            returncode=0, stdout="Spawned bot successfully\n", stderr=""
                        )
                    # Bot 2: "Name ... is online"
                    if call_idx == 2:
                        return MagicMock(returncode=0, stdout="Name onx... is online\n", stderr="")
                    # Bot 3: "Invalid name"
                    if call_idx == 3:
                        return MagicMock(returncode=0, stdout="Invalid name\n", stderr="")
                    # Bot 4: "Incorrect argument for command"
                    if call_idx == 4:
                        return MagicMock(
                            returncode=0, stdout="Incorrect argument for command\n", stderr=""
                        )
                    # Bot 5: rc != 0
                    if call_idx == 5:
                        return MagicMock(returncode=1, stdout="", stderr="RCON error\n")
                return MagicMock(returncode=0, stdout="Done\n", stderr="")
            return MagicMock(returncode=0, stdout="container-123\n", stderr="")

        with (
            patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
            patch.object(ResourcePreflightProbe, "assert_sufficient_resources", return_value=None),
            patch.object(runner, "_persist_test_outcome", new_callable=AsyncMock),
            patch.object(runner, "_persist_runtime", new_callable=AsyncMock),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch("subprocess.run", side_effect=mock_subprocess),
        ):
            handle = await runner.run_test(spec)
            res = await handle.wait_for_completion()

        assert res.passed is False
        assert res.connected_bots == 1  # only bot 1 counted!
        assert "Spawned 1/5" in (res.failure_reason or "")

        evidence = runner._evidence_store.get(spec.test_id, {})
        assertions = evidence.get("assertions", {})
        assert assertions.get("spawn_ok") == 1
        assert assertions.get("spawn_failed") == 4


@pytest.mark.asyncio
async def test_fakeplayer_action_failures_do_not_fail_run() -> None:
    """Action command failures do not by themselves fail the run, but are tracked in evidence."""
    runner = DockerTestExecutionRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        spec, test_dir = _setup_runner_spec(tmpdir)
        (test_dir / "logs" / "latest.log").write_text(
            "Done (1.234s)!\n"
            "[fakeplayer] Enabling fakeplayer v0.4.4\n"
            "[fakeplayer] Enabled in 15296 ms\n",
            encoding="utf-8",
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
                    return MagicMock(returncode=0, stdout="Done\n", stderr="")
                # Actions fail!
                return MagicMock(returncode=1, stdout="", stderr="Action failed")
            return MagicMock(returncode=0, stdout="container-123\n", stderr="")

        with (
            patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
            patch.object(ResourcePreflightProbe, "assert_sufficient_resources", return_value=None),
            patch.object(runner, "_persist_test_outcome", new_callable=AsyncMock),
            patch.object(runner, "_persist_runtime", new_callable=AsyncMock),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch("subprocess.run", side_effect=mock_subprocess),
        ):
            handle = await runner.run_test(spec)
            res = await handle.wait_for_completion()

        assert res.passed is True  # 5/5 spawns succeeded!
        assert res.connected_bots == 5

        evidence = runner._evidence_store.get(spec.test_id, {})
        assertions = evidence.get("assertions", {})
        assert assertions.get("spawn_ok") == 5
        assert assertions.get("spawn_failed") == 0
        assert assertions.get("actions_ok") == 0
        assert assertions.get("actions_failed") == 10


@pytest.mark.asyncio
async def test_fakeplayer_accounting_unknown_stdout_rejected() -> None:
    """A spawn command whose stdout contains 'Unknown' should NOT count as a spawn."""
    runner = DockerTestExecutionRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        spec, test_dir = _setup_runner_spec(tmpdir)
        (test_dir / "logs" / "latest.log").write_text(
            "Done (1.234s)!\n"
            "[fakeplayer] Enabling fakeplayer v0.4.4\n"
            "[fakeplayer] Enabled in 15296 ms\n",
            encoding="utf-8",
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
                    return MagicMock(
                        returncode=0, stdout="Unknown or incomplete command\n", stderr=""
                    )
                return MagicMock(returncode=0, stdout="Done\n", stderr="")
            return MagicMock(returncode=0, stdout="container-123\n", stderr="")

        with (
            patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
            patch.object(ResourcePreflightProbe, "assert_sufficient_resources", return_value=None),
            patch.object(runner, "_persist_test_outcome", new_callable=AsyncMock),
            patch.object(runner, "_persist_runtime", new_callable=AsyncMock),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch("subprocess.run", side_effect=mock_subprocess),
        ):
            handle = await runner.run_test(spec)
            res = await handle.wait_for_completion()

        assert res.passed is False
        assert res.connected_bots == 0
        assert "Spawned 0/5" in (res.failure_reason or "")

        evidence = runner._evidence_store.get(spec.test_id, {})
        assertions = evidence.get("assertions", {})
        assert assertions.get("spawn_ok") == 0
        assert assertions.get("spawn_failed") == 5


# ---------------------------------------------------------------------------
# 6. Secret hygiene: RCON password never in argv / logs / failure_reason / evidence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fakeplayer_rcon_password_scrubbing(caplog: pytest.LogCaptureFixture) -> None:
    """RCON password must never be in argv, failure_reason, evidence, logs, or caplog."""
    caplog.set_level(logging.DEBUG)
    runner = DockerTestExecutionRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        spec, test_dir = _setup_runner_spec(tmpdir)
        (test_dir / "logs" / "latest.log").write_text(
            "Done (1.234s)!\n"
            "[fakeplayer] Enabling fakeplayer v0.4.4\n"
            "[fakeplayer] Enabled in 15296 ms\n",
            encoding="utf-8",
        )

        fake_secret: str | None = None
        executed_argvs: list[list[str]] = []

        def mock_subprocess(cmd, **kwargs):
            nonlocal fake_secret
            env = kwargs.get("env") or {}
            if "RCON_PASSWORD" in env:
                fake_secret = env["RCON_PASSWORD"]

            cmd_list = cmd if isinstance(cmd, list) else [str(cmd)]
            executed_argvs.append(cmd_list)
            cmd_str = " ".join(cmd_list)

            if "inspect" in cmd_str:
                if "State.Running" in cmd_str:
                    return MagicMock(returncode=0, stdout="true\n", stderr="")
                return MagicMock(returncode=0, stdout="172.17.0.2\n", stderr="")
            if "rcon-cli" in cmd_str:
                # Intentionally leak secret in stdout/stderr to test scrubbing!
                leaked = f"Error with password {fake_secret or 'topsecret'}"
                return MagicMock(returncode=1, stdout=leaked, stderr=leaked)
            return MagicMock(returncode=0, stdout="container-123\n", stderr="")

        with (
            patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
            patch.object(ResourcePreflightProbe, "assert_sufficient_resources", return_value=None),
            patch.object(runner, "_persist_test_outcome", new_callable=AsyncMock),
            patch.object(runner, "_persist_runtime", new_callable=AsyncMock),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch("subprocess.run", side_effect=mock_subprocess),
        ):
            handle = await runner.run_test(spec)
            res = await handle.wait_for_completion()

        assert fake_secret is not None, "Expected RCON_PASSWORD to have been set in env"

        # Assert password never in any subprocess argv
        for argv in executed_argvs:
            for arg in argv:
                assert fake_secret not in arg

        # Assert password never in failure_reason
        assert fake_secret not in (res.failure_reason or "")

        # Assert password never in logs
        for log_line in res.logs:
            assert fake_secret not in log_line

        # Assert password never in evidence_bundle
        evidence = runner._evidence_store.get(spec.test_id, {})
        evidence_str = str(evidence)
        assert fake_secret not in evidence_str

        # Assert password never in caplog
        assert fake_secret not in caplog.text
