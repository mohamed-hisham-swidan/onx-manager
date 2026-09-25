import asyncio
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.modules.server.infrastructure.providers.docker import build_docker_server_cmd
from app.modules.versioning.domain.entities import ServerCommit
from app.modules.versioning.domain.value_objects import (
    BotTech,
    BotVerificationConfig,
    CommitManifest,
    TestRunStatus,
)
from app.modules.versioning.infrastructure.resource_probe import ResourcePreflightProbe
from app.modules.versioning.infrastructure.storage_probe import StorageCapabilityProbe
from app.modules.versioning.infrastructure.test_runner import (
    DockerTestExecutionRunner,
    TestHandle,
    TestSpec,
    stage_file_reflink_or_copy,
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

        # Simulate subprocess calls:
        # - cp: staging mods/executables (returncode=0)
        # - docker run -d: launch container (returncode=0, stdout="container-id\n")
        # - docker inspect State.Running: liveness check (returncode=0, stdout="true\n")
        # - docker exec rcon-cli: fakeplayer spawn injection (returncode=0)
        def fake_run(cmd, **_kwargs):
            if "inspect" in cmd and "State.Running" in " ".join(cmd):
                return MagicMock(returncode=0, stdout="true\n", stderr="")
            return MagicMock(returncode=0, stdout="container-id\n", stderr="")

        # Write boot-gate trigger: boot-gate polls <test_dir>/logs/latest.log for "Done ("
        # We also need to write it BEFORE _execute_verification runs, since subprocess is mocked.
        # The test_dir is determined by spec.test_id inside run_test; we replicate the path here.
        test_dir_path = Path(tmpdir) / "server" / ".onx" / "tests" / "t-abc12345"
        logs_dir = test_dir_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        plugins_dir = test_dir_path / "plugins"
        plugins_dir.mkdir(parents=True, exist_ok=True)
        (plugins_dir / "fakeplayer-next.jar").write_bytes(
            b"PK\x03\x04" + b"\x00" * 1_048_576
        )
        (logs_dir / "latest.log").write_text(
            "[12:00:09] [Server thread/INFO]: [fakeplayer] Enabling fakeplayer v0.4.4\n"
            "[12:00:09] [Server thread/INFO]: [fakeplayer] Enabled in 15296 ms\n"
            "[12:00:10] [Server thread/INFO]: Done (5.12s)! For help, type 'help'\n",
            encoding="utf-8",
        )

        with (
            patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
            patch.object(
                ResourcePreflightProbe, "assert_sufficient_resources", return_value=None
            ),
            patch("subprocess.run", side_effect=fake_run),
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
async def test_docker_test_runner_concurrent_runs_no_longer_rejected() -> None:
    """Stage D: the runner holds no per-server lock; admission owns the policy.

    Two same-server run_test() calls are both accepted here (concurrency is
    governed by application/scheduling/admission.admit, not by the runner).
    """
    runner = DockerTestExecutionRunner()
    assert not hasattr(runner, "_server_locks")

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
            patch.object(
                ResourcePreflightProbe, "assert_sufficient_resources", return_value=None
            ),
            patch("subprocess.run", return_value=mock_subproc),
        ):
            handle1 = await runner.run_test(spec1)

            # Second run on the same server is accepted (was ConflictError pre-Stage-D).
            handle2 = await runner.run_test(spec2)

            assert handle1.test_id == "t-1"
            assert handle2.test_id == "t-2"
            assert handle1.container_name != handle2.container_name
            await handle1.wait_for_completion()
            await handle2.wait_for_completion()
            await runner.cleanup_test(handle1)
            await runner.cleanup_test(handle2)


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
            patch.object(
                ResourcePreflightProbe, "assert_sufficient_resources", return_value=None
            ),
            patch("subprocess.run", side_effect=fake_run),
        ):
            handle = await runner.run_test(spec)
            res = await handle.wait_for_completion()

            assert res.passed is False
            assert handle.status == TestRunStatus.FAILED
            assert "ironchests" in str(res.failure_reason)
            await runner.cleanup_test(handle)


# ──────────────────────────────────────────────────────────────────────────────
# MUST-FIX 2 — Direct unit tests for build_docker_server_cmd
# ──────────────────────────────────────────────────────────────────────────────




def test_build_docker_server_cmd_script_shape() -> None:
    """Startup command containing run.sh → bash /data/run.sh nogui."""
    cmd = build_docker_server_cmd(startup_command=["bash", "run.sh", "nogui"])
    assert cmd == ["bash", "/data/run.sh", "nogui"]


def test_build_docker_server_cmd_script_shape_run_bat() -> None:
    """run.bat in startup_command also triggers script path."""
    cmd = build_docker_server_cmd(startup_command=["cmd", "/c", "run.bat"])
    assert cmd == ["bash", "/data/run.sh", "nogui"]


def test_build_docker_server_cmd_itzg_entrypoint_passthrough() -> None:
    """itzg image + force_itzg_entrypoint=True → empty list (use image entrypoint)."""
    cmd = build_docker_server_cmd(image="itzg/minecraft-server:latest", force_itzg_entrypoint=True)
    assert cmd == []


def test_build_docker_server_cmd_itzg_without_force_builds_java_cmd() -> None:
    """itzg image + force_itzg_entrypoint=False → explicit java CMD (launch_config present)."""
    cmd = build_docker_server_cmd(
        startup_jar="paper-1.21.1-123.jar",
        image="itzg/minecraft-server:latest",
        force_itzg_entrypoint=False,
        memory_min_mb=1024,
        memory_max_mb=2048,
    )
    assert cmd == [
        "java",
        "-Xms1024M",
        "-Xmx2048M",
        "-jar",
        "/data/paper-1.21.1-123.jar",
        "nogui",
    ]


def test_build_docker_server_cmd_explicit_jar() -> None:
    """Explicit jar name → java -jar /data/<jar> nogui."""
    cmd = build_docker_server_cmd(
        startup_jar="custom-server.jar",
        memory_min_mb=2048,
        memory_max_mb=4096,
        cpu_cores=2,
    )
    assert cmd == [
        "java",
        "-Xms2048M",
        "-Xmx4096M",
        "-XX:ActiveProcessorCount=2",
        "-jar",
        "/data/custom-server.jar",
        "nogui",
    ]


def test_build_docker_server_cmd_default_jar_fallback() -> None:
    """No jar supplied → defaults to server.jar (verbatim old-code behaviour)."""
    cmd = build_docker_server_cmd(memory_min_mb=1024, memory_max_mb=2048)
    assert cmd == ["java", "-Xms1024M", "-Xmx2048M", "-jar", "/data/server.jar", "nogui"]


def test_build_docker_server_cmd_jvm_flags_included() -> None:
    """jvm_flags are inserted before -Xms/-Xmx."""
    cmd = build_docker_server_cmd(
        jvm_flags=["-Dfml.readTimeout=180"],
        memory_min_mb=1024,
        memory_max_mb=2048,
    )
    assert cmd == [
        "java",
        "-Dfml.readTimeout=180",
        "-Xms1024M",
        "-Xmx2048M",
        "-jar",
        "/data/server.jar",
        "nogui",
    ]


# ──────────────────────────────────────────────────────────────────────────────
# MUST-FIX 2 — stage_file_reflink_or_copy: MSYS-cp-fails fallback test
# ──────────────────────────────────────────────────────────────────────────────


def test_stage_file_reflink_or_copy_falls_back_when_cp_exits_nonzero(
    tmp_path: Path,
) -> None:
    """If cp --reflink=auto exits non-zero (MSYS2 without reflink support),
    the helper must fall back to shutil.copy2 and produce a correct destination.

    This is the exact Windows-safety case the Design Review required as a
    blocking change: cp found on PATH but fails silently with nonzero returncode.
    """
    src = tmp_path / "source.jar"
    src.write_bytes(b"fake-jar-content")
    dst = tmp_path / "dest" / "source.jar"

    # Simulate cp found on PATH but exiting non-zero (MSYS2 without --reflink support).
    mock_failed_cp = MagicMock(returncode=1, stdout=b"", stderr=b"unsupported option")

    with patch("subprocess.run", return_value=mock_failed_cp):
        stage_file_reflink_or_copy(src, dst)

    assert dst.exists(), "Destination must exist after fallback copy"
    assert dst.read_bytes() == b"fake-jar-content", "Destination content must match source"


def test_stage_file_reflink_or_copy_succeeds_when_cp_exits_zero(tmp_path: Path) -> None:
    """When cp --reflink=auto exits 0 and dst exists, no shutil.copy2 fallback fires."""
    import shutil as shutil_mod

    src = tmp_path / "source.jar"
    src.write_bytes(b"jar-bytes")
    dst = tmp_path / "dest" / "source.jar"
    dst.parent.mkdir()

    def fake_cp(_cmd, **_kwargs):
        # Simulate a successful reflink by doing the actual copy.
        shutil_mod.copy2(str(src), str(dst))
        return MagicMock(returncode=0, stdout=b"", stderr=b"")

    with patch("subprocess.run", side_effect=fake_cp) as mock_run:
        stage_file_reflink_or_copy(src, dst)

    mock_run.assert_called_once()
    assert dst.read_bytes() == b"jar-bytes"


# ──────────────────────────────────────────────────────────────────────────────
# MUST-FIX 3 — Runner-level boot-gate failure: dead container → passed=False
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_docker_runner_boot_gate_dead_container_never_passes() -> None:
    """Core spec claim: a container that never boots MUST produce passed=False.

    Simulates a container that starts (docker run returns container-id) but
    immediately terminates before the server prints 'Done (' — docker inspect
    returns is_alive=False on the very first boot-gate iteration.
    No logs/latest.log is created. Result must be FAILED with a failure_reason.
    """
    runner = DockerTestExecutionRunner()

    with tempfile.TemporaryDirectory() as tmpdir:
        srv_dir = Path(tmpdir) / "server"
        srv_dir.mkdir()
        (srv_dir / "server.properties").write_text(
            "online-mode=true\n", encoding="utf-8"
        )

        manifest = CommitManifest(
            server_type="paper",
            minecraft_version="1.21.1",
            configs={"server.properties": "online-mode=true\n"},
        )
        commit = ServerCommit(
            id="c-dead", server_id="srv-dead", message="dead boot test", manifest=manifest
        )
        bot_cfg = BotVerificationConfig(
            bot_count=2, duration_minutes=1, bot_tech=BotTech.FAKEPLAYER_NEXT
        )
        spec = TestSpec(
            test_id="t-deadboot",
            server_id="srv-dead",
            commit=commit,
            server_dir=str(srv_dir),
            bot_config=bot_cfg,
        )

        def dead_container_run(cmd, **_kwargs):
            if isinstance(cmd, list) and "inspect" in cmd:
                # Container terminated immediately — not running.
                return MagicMock(returncode=0, stdout="false\n", stderr="")
            # docker run -d: succeed, return container ID.
            return MagicMock(returncode=0, stdout="deadcontainerid\n", stderr="")

        with (
            patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
            patch.object(ResourcePreflightProbe, "assert_sufficient_resources", return_value=None),
            patch("subprocess.run", side_effect=dead_container_run),
        ):
            handle = await runner.run_test(spec)
            res = await handle.wait_for_completion()

        assert res.passed is False, "Dead container must never produce passed=True"
        assert handle.status == TestRunStatus.FAILED
        assert res.failure_reason is not None
        assert len(res.failure_reason) > 0, "failure_reason must be non-empty"


# ── Must-Fix 5: --user uid:gid parity ─────────────────────────────────────────
@pytest.mark.asyncio
async def test_test_container_launch_includes_user_uid_gid() -> None:
    """Must-Fix 5 (run 61d84dd5 PermissionError): the isolated test-container
    launch must pass --user {uid}:{gid} on non-Windows hosts, mirroring the
    regular-server contract (docker.py --user uid:gid).

    Same-UID CI cannot exercise the live collision, so this asserts the flag
    is present and correctly formed on the constructed docker run command.

    Correction (run 6f354058): presence is NOT enough — the flag must precede
    IMAGE, because everything after IMAGE is the container CMD. A post-image
    --user kills the entrypoint (exit 2) instead of setting the UID.
    """
    if sys.platform == "win32" or not hasattr(os, "getuid"):
        pytest.skip("POSIX-only UID mapping assertion")
    runner = DockerTestExecutionRunner()

    with tempfile.TemporaryDirectory() as tmpdir:
        srv_dir = Path(tmpdir) / "server"
        srv_dir.mkdir()
        (srv_dir / "server.properties").write_text(
            "online-mode=true\n", encoding="utf-8"
        )

        manifest = CommitManifest(
            server_type="paper",
            minecraft_version="1.21.1",
            configs={"server.properties": "online-mode=true\n"},
        )
        commit = ServerCommit(
            id="c-uid", server_id="srv-uid", message="uid parity test", manifest=manifest
        )
        bot_cfg = BotVerificationConfig(
            bot_count=2, duration_minutes=1, bot_tech=BotTech.FAKEPLAYER_NEXT
        )
        spec = TestSpec(
            test_id="t-uidparity",
            server_id="srv-uid",
            commit=commit,
            server_dir=str(srv_dir),
            bot_config=bot_cfg,
        )

        captured_cmds: list[list[str]] = []

        def capture_run(cmd, **_kwargs):
            if isinstance(cmd, list):
                captured_cmds.append(cmd)
            if "inspect" in cmd:
                return MagicMock(returncode=0, stdout="false\n", stderr="")
            return MagicMock(returncode=0, stdout="uidparitycontainer\n", stderr="")

        with (
            patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
            patch.object(ResourcePreflightProbe, "assert_sufficient_resources", return_value=None),
            patch("subprocess.run", side_effect=capture_run),
        ):
            handle = await runner.run_test(spec)
            await handle.wait_for_completion()

        docker_runs = [c for c in captured_cmds if c[:2] == ["docker", "run"]]
        assert docker_runs, "expected a docker run invocation to be captured"
        run_cmd = docker_runs[0]
        expected = f"{os.getuid()}:{os.getgid()}"
        assert "--user" in run_cmd, "test launch must include --user flag"
        user_idx = run_cmd.index("--user")
        assert run_cmd[user_idx + 1] == expected
        # POSITION (run 6f354058): --user must precede IMAGE. Everything after
        # IMAGE is the container CMD — a post-image --user is passed to the
        # entrypoint as an argument (exec: --: invalid option, exit 2).
        image_candidates = [
            i
            for i, tok in enumerate(run_cmd)
            if "temurin" in tok or "eclipse" in tok or tok.startswith("itzg/")
        ]
        assert image_candidates, "expected a resolved JRE image in the run command"
        image_idx = image_candidates[0]
        assert user_idx < image_idx, (
            f"--user (idx {user_idx}) must precede IMAGE (idx {image_idx}); "
            f"cmd={run_cmd}"
        )
        # The token immediately after IMAGE, if present, must be the server CMD (java/bash),
        # never a docker flag. When itzg entrypoint is forced, no trailing CMD is appended.
        if len(run_cmd) > image_idx + 1:
            assert run_cmd[image_idx + 1] in ("java", "bash"), (
                f"token after IMAGE must start the server CMD, got {run_cmd[image_idx + 1]!r}"
            )
        else:
            assert "itzg" in run_cmd[image_idx], "only itzg images may omit trailing CMD"



# ── Must-Fix 6A: container cleanup on exception paths ─────────────────────────
@pytest.mark.asyncio
async def test_verification_exception_still_removes_container() -> None:
    """Must-Fix 6A: when _execute_verification exits via an exception path,
    the test container must still be removed (docker rm -f), not leaked.

    Forces a driver exception AFTER a successful boot-gate (seeded Done log +
    live inspect), then asserts a `docker rm -f <container>` call was issued
    for this test's container — not just that passed=False was recorded.
    """
    runner = DockerTestExecutionRunner()

    with tempfile.TemporaryDirectory() as tmpdir:
        srv_dir = Path(tmpdir) / "server"
        srv_dir.mkdir()
        (srv_dir / "server.properties").write_text(
            "online-mode=true\n", encoding="utf-8"
        )

        manifest = CommitManifest(
            server_type="forge",
            minecraft_version="1.20.1",
            configs={"server.properties": "online-mode=true\n"},
        )
        commit = ServerCommit(
            id="c-cleanup",
            server_id="srv-cleanup",
            message="cleanup test",
            manifest=manifest,
        )
        bot_cfg = BotVerificationConfig(
            bot_count=2, duration_minutes=1, bot_tech=BotTech.AUTO
        )
        spec = TestSpec(
            test_id="t-cleanup",
            server_id="srv-cleanup",
            commit=commit,
            server_dir=str(srv_dir),
            bot_config=bot_cfg,
        )

        # Seed boot-gate trigger so execution reaches the driver branch.
        test_dir_path = Path(tmpdir) / "server" / ".onx" / "tests" / spec.test_id
        logs_dir = test_dir_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        (logs_dir / "latest.log").write_text(
            "[12:00:10] [Server thread/INFO]: Done (5.12s)! For help, type 'help'\n",
            encoding="utf-8",
        )

        captured_cmds: list[list[str]] = []

        def capture_run(cmd, **_kwargs):
            if isinstance(cmd, list):
                captured_cmds.append(cmd)
            if "inspect" in cmd:
                return MagicMock(returncode=0, stdout="true\n", stderr="")
            return MagicMock(returncode=0, stdout="cleanupcontainer\n", stderr="")

        async def boom(*_args, **_kwargs):
            raise RuntimeError("injected driver failure")

        with (
            patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
            patch.object(ResourcePreflightProbe, "assert_sufficient_resources", return_value=None),
            patch("subprocess.run", side_effect=capture_run),
            patch(
                "app.modules.versioning.infrastructure.test_runner.SmokeTestRunner.run_smoke_test",
                side_effect=boom,
            ),
        ):
            handle = await runner.run_test(spec)
            res = await handle.wait_for_completion()

        assert res.passed is False
        assert "injected driver failure" in (res.failure_reason or "")
        # NOTE: set_result() resolves before the finally block reaches
        # cleanup_test, so poll briefly for the rm call instead of asserting
        # immediately (avoids a waiter-vs-background-task race).
        rm_calls: list[list[str]] = []
        for _ in range(100):
            rm_calls = [
                c
                for c in captured_cmds
                if c[:3] == ["docker", "rm", "-f"] and handle.container_name in c
            ]
            if rm_calls:
                break
            await asyncio.sleep(0.1)
        assert rm_calls, (
            f"expected docker rm -f {handle.container_name} after exception-path "
            f"completion; captured: {captured_cmds}"
        )


@pytest.mark.asyncio
async def test_fakeplayer_next_rcon_failure_fails_test_run() -> None:
    """Reproduction test: when FakePlayer RCON injection fails, the test run

    MUST fail, not falsely pass.
    """
    runner = DockerTestExecutionRunner()

    with tempfile.TemporaryDirectory() as tmpdir:
        srv_dir = Path(tmpdir) / "server"
        srv_dir.mkdir()
        (srv_dir / "server.properties").write_text(
            "online-mode=true\n", encoding="utf-8"
        )

        manifest = CommitManifest(
            server_type="paper",
            minecraft_version="1.21.1",
            configs={"server.properties": "online-mode=true\n"},
        )
        commit = ServerCommit(
            id="c-fp-fail",
            server_id="srv-fp-fail",
            message="fakeplayer fail test",
            manifest=manifest,
        )
        bot_cfg = BotVerificationConfig(
            bot_count=5, duration_minutes=1, bot_tech=BotTech.FAKEPLAYER_NEXT
        )
        spec = TestSpec(
            test_id="t-fp-fail",
            server_id="srv-fp-fail",
            commit=commit,
            server_dir=str(srv_dir),
            bot_config=bot_cfg,
        )

        test_dir_path = Path(tmpdir) / "server" / ".onx" / "tests" / spec.test_id
        logs_dir = test_dir_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        plugins_dir = test_dir_path / "plugins"
        plugins_dir.mkdir(parents=True, exist_ok=True)
        (plugins_dir / "fakeplayer-next.jar").write_bytes(
            b"PK\x03\x04" + b"\x00" * 1_048_576
        )
        (logs_dir / "latest.log").write_text(
            "[12:00:09] [Server thread/INFO]: [fakeplayer] Enabling fakeplayer v0.4.4\n"
            "[12:00:09] [Server thread/INFO]: [fakeplayer] Enabled in 15296 ms\n"
            "[12:00:10] [Server thread/INFO]: Done (2.1s)! For help, type 'help'\n",
            encoding="utf-8",
        )

        def mock_subprocess(cmd, **_kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "rcon-cli" in cmd_str:
                return MagicMock(returncode=1, stdout="", stderr="Error: connection refused\n")
            if "inspect" in cmd_str:
                if "State.Running" in cmd_str:
                    return MagicMock(returncode=0, stdout="true\n", stderr="")
                return MagicMock(returncode=0, stdout="172.17.0.5\n", stderr="")
            return MagicMock(returncode=0, stdout="container-id\n", stderr="")

        with (
            patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
            patch.object(ResourcePreflightProbe, "assert_sufficient_resources", return_value=None),
            patch("subprocess.run", side_effect=mock_subprocess),
        ):
            handle = await runner.run_test(spec)
            res = await handle.wait_for_completion()

        assert res.passed is False, f"Expected passed=False on RCON failure, got {res.passed}"
        assert handle.status == TestRunStatus.FAILED
        failure_msg = res.failure_reason or ""
        assert "Error: connection refused" in failure_msg or "Failed to spawn" in failure_msg

