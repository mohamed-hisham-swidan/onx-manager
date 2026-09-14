import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.exceptions import ConflictError
from app.modules.versioning.domain.entities import ServerCommit
from app.modules.versioning.domain.value_objects import (
    BotTech,
    BotVerificationConfig,
    CommitManifest,
    TestRunStatus,
)
from app.modules.versioning.infrastructure.storage_probe import StorageCapabilityProbe
from app.modules.versioning.infrastructure.test_runner import (
    DockerTestExecutionRunner,
    TestHandle,
    TestSpec,
)


@pytest.mark.asyncio
async def test_docker_test_runner_successful_execution_pipeline() -> None:
    runner = DockerTestExecutionRunner()

    with tempfile.TemporaryDirectory() as tmpdir:
        srv_dir = Path(tmpdir) / "server"
        srv_dir.mkdir()
        (srv_dir / "server.properties").write_text(
            "motd=ProdServer\nonline-mode=true\n", encoding="utf-8"
        )

        manifest = CommitManifest(
            server_type="paper",
            minecraft_version="1.21.1",
            configs={"server.properties": "motd=TestServer\nonline-mode=true\n"},
        )
        commit = ServerCommit(
            id="c-123", server_id="srv-1", message="test update", manifest=manifest
        )
        bot_cfg = BotVerificationConfig(
            bot_count=10, duration_minutes=1, bot_tech=BotTech.FAKEPLAYER_NEXT
        )

        spec = TestSpec(
            test_id="t-abc12345",
            server_id="srv-1",
            commit=commit,
            server_dir=str(srv_dir),
            bot_config=bot_cfg,
        )

        mock_subproc = MagicMock(returncode=0, stdout="container-id\n", stderr="")

        with (
            patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
            patch("subprocess.run", return_value=mock_subproc),
        ):
            handle = await runner.run_test(spec)
            assert isinstance(handle, TestHandle)
            assert handle.test_id == "t-abc12345"

            # Await verification completion
            res = await handle.wait_for_completion()
            assert res.passed is True
            assert res.connected_bots == 10
            assert handle.status == TestRunStatus.PASSED

            # Verify test server.properties had online-mode=false
            test_props = Path(handle.test_dir) / "server.properties"
            assert test_props.exists()
            content = test_props.read_text(encoding="utf-8")
            assert "online-mode=false" in content

            # Verify cleanup
            await runner.cleanup_test(handle)


@pytest.mark.asyncio
async def test_docker_test_runner_concurrent_runs_rejected_with_conflict() -> None:
    runner = DockerTestExecutionRunner()

    with tempfile.TemporaryDirectory() as tmpdir:
        srv_dir = Path(tmpdir) / "server"
        srv_dir.mkdir()

        manifest = CommitManifest(server_type="vanilla", minecraft_version="1.21.1")
        commit = ServerCommit(id="c-123", server_id="srv-1", message="test", manifest=manifest)
        bot_cfg = BotVerificationConfig()

        spec1 = TestSpec(
            test_id="t-1",
            server_id="srv-1",
            commit=commit,
            server_dir=str(srv_dir),
            bot_config=bot_cfg,
        )
        spec2 = TestSpec(
            test_id="t-2",
            server_id="srv-1",
            commit=commit,
            server_dir=str(srv_dir),
            bot_config=bot_cfg,
        )

        mock_subproc = MagicMock(returncode=0, stdout="id\n", stderr="")

        with (
            patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
            patch("subprocess.run", return_value=mock_subproc),
        ):
            handle1 = await runner.run_test(spec1)

            # Attempt second run on same server while first is active
            with pytest.raises(ConflictError) as exc_info:
                await runner.run_test(spec2)

            assert "already active" in str(exc_info.value)
            await handle1.wait_for_completion()


@pytest.mark.asyncio
async def test_docker_test_runner_crash_report_blaming_integration() -> None:
    runner = DockerTestExecutionRunner()

    with tempfile.TemporaryDirectory() as tmpdir:
        srv_dir = Path(tmpdir) / "server"
        srv_dir.mkdir()

        manifest = CommitManifest(server_type="forge", minecraft_version="1.21.1")
        commit = ServerCommit(
            id="c-crash", server_id="srv-crash", message="crash test", manifest=manifest
        )
        bot_cfg = BotVerificationConfig(
            bot_count=1, duration_minutes=1, bot_tech=BotTech.MINEFLAYER
        )

        spec = TestSpec(
            test_id="t-crash99",
            server_id="srv-crash",
            commit=commit,
            server_dir=str(srv_dir),
            bot_config=bot_cfg,
        )

        # Hook to drop a simulated Forge crash report during test execution
        def fake_run(cmd, **_kwargs):
            if "docker" in cmd and "run" in cmd:
                # Materialize crash report in test directory
                test_crash_dir = srv_dir / ".onx" / "tests" / "t-crash99" / "crash-reports"
                test_crash_dir.mkdir(parents=True, exist_ok=True)
                crash_file = test_crash_dir / "crash-2026-09-14.txt"
                crash_file.write_text(
                    "net.minecraftforge.fml.ModLoadingException: "
                    "Mod ironchests encountered an error\n"
                    "Caused by: java.lang.NullPointerException\n"
                    "\tat com.example.ironchests.Init.load(Init.java:42)\n",
                    encoding="utf-8",
                )
            return MagicMock(returncode=0, stdout="id\n", stderr="")

        with (
            patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
            patch("subprocess.run", side_effect=fake_run),
        ):
            handle = await runner.run_test(spec)
            res = await handle.wait_for_completion()

            assert res.passed is False
            assert handle.status == TestRunStatus.FAILED
            assert "ironchests" in str(res.failure_reason)
            await runner.cleanup_test(handle)
