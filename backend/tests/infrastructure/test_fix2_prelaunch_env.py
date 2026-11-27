from __future__ import annotations

import asyncio
import logging
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import AppSettings
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.modules.server.application.services.jar_service import generate_rcon_password
from app.modules.versioning.domain.deployment import TestServerDeployment
from app.modules.versioning.domain.entities import ServerCommit, ServerTestRun
from app.modules.versioning.domain.value_objects import (
    BotTech,
    BotVerificationConfig,
    CommitManifest,
    TestRunStatus,
)
from app.modules.versioning.infrastructure.compatibility import (
    StrategyResult,
    VerificationMode,
)
from app.modules.versioning.infrastructure.config_writer import write_test_server_properties
from app.modules.versioning.infrastructure.models import ServerTestRunModel
from app.modules.versioning.infrastructure.repository import SQLVersioningRepository
from app.modules.versioning.infrastructure.resource_probe import ResourcePreflightProbe
from app.modules.versioning.infrastructure.storage_probe import StorageCapabilityProbe
from app.modules.versioning.infrastructure.test_env import (
    build_test_container_env,
    clean_test_plugins_dir,
    resolve_test_docker_image,
)
from app.modules.versioning.infrastructure.test_runner import (
    DockerTestExecutionRunner,
    TestSpec,
)


def test_build_test_container_env_fakeplayer_next() -> None:
    strat = StrategyResult(
        mode=VerificationMode.FULL_BOT,
        driver="fakeplayer_next",
        reason="Paper server with FakePlayer-Next artifact",
        downgraded_from=None,
        artifact_ok=True,
    )
    env = build_test_container_env(
        server_type="paper",
        minecraft_version="26.2",
        strategy=strat,
    )

    assert env["EULA"] == "TRUE"
    assert env["ONLINE_MODE"] == "FALSE"
    assert env["TYPE"] == "PAPER"
    assert env["VERSION"] == "26.2"
    assert env["MODRINTH_PROJECTS"] == "commandapi"
    assert env["ENABLE_RCON"] == "true"
    assert env["RCON_PORT"] == "25575"
    # RCON_PASSWORD must NOT be in the returned env mapping for -e NAME=value argv construction
    assert "RCON_PASSWORD" not in env


def test_build_test_container_env_smoke_or_mineflayer() -> None:
    strat = StrategyResult(
        mode=VerificationMode.SMOKE_TEST,
        driver="smoke_test",
        reason="Downgraded due to missing artifact",
        downgraded_from="fakeplayer_next",
        artifact_ok=False,
    )
    env = build_test_container_env(
        server_type="paper",
        minecraft_version="1.21.1",
        strategy=strat,
    )

    assert env["EULA"] == "TRUE"
    assert env["ONLINE_MODE"] == "FALSE"
    assert env["TYPE"] == "PAPER"
    assert env["VERSION"] == "1.21.1"
    assert "MODRINTH_PROJECTS" not in env
    assert "ENABLE_RCON" not in env
    assert "RCON_PORT" not in env
    assert "RCON_PASSWORD" not in env


def test_generate_rcon_password_properties() -> None:
    pw1 = generate_rcon_password()
    pw2 = generate_rcon_password()
    assert len(pw1) >= 32
    assert pw1.isalnum()
    assert pw1 != pw2


# ── Fix B3 Tests ─────────────────────────────────────────────────────────────


def test_docker_test_image_setting_aligned_with_java25_tag() -> None:
    expected = (
        "itzg/minecraft-server:java25@sha256:"
        "dc7913a69c878594ff7b568862b2cd5541fac6e409d1dc86f0313b1ef7a4d9d4"
    )
    settings = AppSettings()
    assert settings.docker_test_image == expected


def test_resolve_test_docker_image_fakeplayer_uses_itzg() -> None:
    strat = StrategyResult(
        mode=VerificationMode.FULL_BOT,
        driver="fakeplayer_next",
        reason="Paper server with FakePlayer-Next artifact",
        downgraded_from=None,
        artifact_ok=True,
    )
    resolved_img, resolved_strat = resolve_test_docker_image(
        minecraft_version="26.2",
        strategy=strat,
    )
    assert "itzg/minecraft-server" in resolved_img
    assert resolved_strat == strat


def test_resolve_test_docker_image_non_fakeplayer_uses_temurin() -> None:
    strat = StrategyResult(
        mode=VerificationMode.SMOKE_TEST,
        driver="smoke_test",
        reason="Vanilla smoke test",
        downgraded_from=None,
        artifact_ok=False,
    )
    resolved_img, resolved_strat = resolve_test_docker_image(
        minecraft_version="1.21.1",
        strategy=strat,
    )
    assert resolved_img == "eclipse-temurin:21-jre-jammy"
    assert resolved_strat == strat


def test_resolve_test_docker_image_fakeplayer_empty_config_downgrades_to_smoke() -> None:
    strat = StrategyResult(
        mode=VerificationMode.FULL_BOT,
        driver="fakeplayer_next",
        reason="Paper server with FakePlayer-Next artifact",
        downgraded_from=None,
        artifact_ok=True,
    )
    with patch("app.modules.versioning.infrastructure.test_env.AppSettings") as mock_settings_cls:
        mock_settings_cls.return_value.docker_test_image = ""
        resolved_img, resolved_strat = resolve_test_docker_image(
            minecraft_version="26.2",
            strategy=strat,
        )
        assert resolved_img == "eclipse-temurin:25-jre"
        assert resolved_strat.mode == VerificationMode.SMOKE_TEST
        assert resolved_strat.downgraded_from == "fakeplayer_next"
        assert resolved_strat.reason == "itzg image not configured"


# ── Fix B2 Tests ─────────────────────────────────────────────────────────────


def test_clean_test_plugins_dir_symlinked_plugins_refused() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir) / "test_run_1"
        test_dir.mkdir()
        real_plugins = Path(tmpdir) / "real_plugins"
        real_plugins.mkdir()
        canary = real_plugins / "commandapi-12.0.jar"
        canary.write_text("canary", encoding="utf-8")

        symlink_plugins = test_dir / "plugins"
        symlink_plugins.symlink_to(real_plugins)

        clean_test_plugins_dir(test_dir)

        # Symlinked plugins dir must NOT have its contents deleted
        assert canary.exists()


def test_clean_test_plugins_dir_traversal_refused() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir) / "test_run_2"
        test_dir.mkdir()
        victim_dir = Path(tmpdir) / "other_dir"
        victim_dir.mkdir()
        victim_file = victim_dir / "commandapi.jar"
        victim_file.write_text("victim", encoding="utf-8")

        traversal_path = test_dir / ".." / "other_dir"
        clean_test_plugins_dir(traversal_path)

        assert victim_file.exists()


def test_clean_test_plugins_dir_retention_and_removal() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir) / "test_run_3"
        test_dir.mkdir()
        plugins_dir = test_dir / "plugins"
        plugins_dir.mkdir()

        # 1. Non-fakeplayer, non-commandapi jar (e.g. real plugin under test) MUST BE KEPT
        user_plugin = plugins_dir / "EssentialsX-2.20.jar"
        user_plugin.write_text("essentials", encoding="utf-8")

        # 2. CommandAPI jar MUST BE REMOVED
        cmd_api = plugins_dir / "CommandAPI-12.0.0-Paper.jar"
        cmd_api.write_text("cmdapi", encoding="utf-8")

        # 3. .part file MUST BE REMOVED
        part_file = plugins_dir / "download.jar.part"
        part_file.write_text("part", encoding="utf-8")

        # 4. Jar with 'stale' in name MUST BE REMOVED
        stale_jar = plugins_dir / "old_stale_plugin.jar"
        stale_jar.write_text("stale", encoding="utf-8")

        # 5. Duplicate fakeplayer jars MUST BE REDUCED TO ONE
        fp1 = plugins_dir / "fakeplayer-0.4.3.jar"
        fp1.write_text("fp1", encoding="utf-8")
        fp2 = plugins_dir / "fakeplayer-0.4.4.jar"
        fp2.write_text("fp2", encoding="utf-8")

        # 6. Candidate symlink inside plugins MUST BE SKIPPED
        target_file = Path(tmpdir) / "target.jar"
        target_file.write_text("target", encoding="utf-8")
        symlinked_jar = plugins_dir / "commandapi-symlink.jar"
        symlinked_jar.symlink_to(target_file)

        clean_test_plugins_dir(test_dir)

        assert user_plugin.exists(), "User plugins under test must be preserved"
        assert not cmd_api.exists(), "CommandAPI jar must be removed"
        assert not part_file.exists(), ".part file must be removed"
        assert not stale_jar.exists(), "Stale jar must be removed"

        remaining_fp = list(plugins_dir.glob("fakeplayer*.jar"))
        assert len(remaining_fp) == 1, (
            f"Expected exactly 1 fakeplayer jar, found {len(remaining_fp)}"
        )

        assert symlinked_jar.exists(), "Symlinked entries must be skipped"
        assert target_file.exists()


# ── Fix B1 Tests ─────────────────────────────────────────────────────────────


def test_write_test_server_properties_keeps_rcon_disabled() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir) / ".onx" / "tests" / "test-rcon-hygiene"
        test_dir.mkdir(parents=True, exist_ok=True)
        deployment = TestServerDeployment(test_id="test-rcon-hygiene", test_dir=str(test_dir))

        write_test_server_properties(
            deployment=deployment,
            base_properties={"motd": "TestMOTD", "enable-rcon": "true"},
            server_port=25565,
            bot_count=5,
            rcon_password="should_not_be_written",
        )

        props_content = (test_dir / "server.properties").read_text(encoding="utf-8")
        assert "enable-rcon=false" in props_content
        assert "rcon.password" not in props_content
        assert "should_not_be_written" not in props_content


@pytest.mark.asyncio
async def test_run_test_rcon_password_out_of_argv_and_in_env_kwarg() -> None:
    runner = DockerTestExecutionRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        srv_dir = Path(tmpdir) / "server"
        srv_dir.mkdir(parents=True, exist_ok=True)
        (srv_dir / "server.properties").write_text("motd=ProdServer\n", encoding="utf-8")

        manifest = CommitManifest(
            server_type="paper",
            minecraft_version="26.2",
            configs={"server.properties": "motd=TestServer\n"},
        )
        commit = ServerCommit(
            id="c-456", server_id="srv-1", message="test update", manifest=manifest
        )
        bot_cfg = BotVerificationConfig(
            bot_count=3, duration_minutes=1, bot_tech=BotTech.FAKEPLAYER_NEXT
        )

        spec = TestSpec(
            test_id="t-envtest1",
            server_id="srv-1",
            commit=commit,
            server_dir=str(srv_dir),
            bot_config=bot_cfg,
        )

        test_dir = srv_dir / ".onx" / "tests" / "t-envtest1"
        plugins_dir = test_dir / "plugins"
        plugins_dir.mkdir(parents=True, exist_ok=True)
        (plugins_dir / "fakeplayer-0.4.4.jar").write_bytes(b"PK\x03\x04" + b"\x00" * 1_048_576)

        logs_dir = test_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        (logs_dir / "latest.log").write_text(
            "[12:00:10] [Server thread/INFO]: Done (3.5s)! For help, type 'help'\n",
            encoding="utf-8",
        )

        captured_calls: list[dict] = []

        def fake_run(cmd, **kwargs):
            captured_calls.append({"cmd": list(cmd), "kwargs": kwargs})
            if "inspect" in cmd and "State.Running" in " ".join(cmd):
                return MagicMock(returncode=0, stdout="true\n", stderr="")
            return MagicMock(returncode=0, stdout="container-id\n", stderr="")

        with (
            patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
            patch.object(ResourcePreflightProbe, "assert_sufficient_resources", return_value=None),
            patch("subprocess.run", side_effect=fake_run),
        ):
            handle = await runner.run_test(spec)
            await handle.wait_for_completion()

            docker_runs = [c for c in captured_calls if c["cmd"][:2] == ["docker", "run"]]
            assert docker_runs, "docker run must be invoked"
            call = docker_runs[0]
            cmd = call["cmd"]
            kwargs = call["kwargs"]

            # (i) docker argv contains "-e", "RCON_PASSWORD" (without value)
            # and NO "RCON_PASSWORD=" and NO plaintext password in argv
            rcon_idx = [i for i, tok in enumerate(cmd) if tok == "RCON_PASSWORD"]
            assert rcon_idx, "expected '-e RCON_PASSWORD' flag in argv"
            assert cmd[rcon_idx[0] - 1] == "-e"
            assert not any("RCON_PASSWORD=" in tok for tok in cmd), (
                "RCON_PASSWORD must not have =value in argv"
            )

            # (ii) env kwarg carries the RCON_PASSWORD value
            proc_env = kwargs.get("env")
            assert proc_env is not None, "env parameter must be passed to subprocess.run"
            rcon_pass = proc_env.get("RCON_PASSWORD")
            assert rcon_pass is not None and len(rcon_pass) >= 32
            assert rcon_pass not in cmd, "RCON_PASSWORD value must NOT be in argv"


@pytest.mark.asyncio
async def test_run_test_docker_run_timeout_scrubs_password_and_argv() -> None:
    runner = DockerTestExecutionRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        srv_dir = Path(tmpdir) / "server"
        srv_dir.mkdir(parents=True, exist_ok=True)
        manifest = CommitManifest(server_type="paper", minecraft_version="26.2")
        commit = ServerCommit(id="c-789", server_id="srv-1", message="test", manifest=manifest)
        bot_cfg = BotVerificationConfig(bot_count=1, bot_tech=BotTech.FAKEPLAYER_NEXT)
        spec = TestSpec(
            test_id="t-timeout",
            server_id="srv-1",
            commit=commit,
            server_dir=str(srv_dir),
            bot_config=bot_cfg,
        )

        secret_marker = "SUPER_SECRET_RCON_PASSWORD_12345"

        def timeout_run(cmd, **_kwargs):
            if cmd[:2] == ["docker", "run"]:
                raise subprocess.TimeoutExpired(cmd=cmd, timeout=30)
            return MagicMock(returncode=0, stdout="", stderr="")

        with (
            patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
            patch.object(ResourcePreflightProbe, "assert_sufficient_resources", return_value=None),
            patch(
                "app.modules.versioning.infrastructure.test_runner.generate_rcon_password",
                return_value=secret_marker,
            ),
            patch("subprocess.run", side_effect=timeout_run),
        ):
            with pytest.raises(Exception) as exc_info:
                await runner.run_test(spec)

            err_msg = str(exc_info.value)
            assert secret_marker not in err_msg, (
                "Secret RCON password must not appear in exception message"
            )
            assert secret_marker not in err_msg
            assert "TimeoutExpired" in err_msg or "timed out" in err_msg.lower()


# ── Fix B4 Pre-launch Fail-safe Tests ─────────────────────────────────────────

CLASS_A_STEPS = [
    (
        "clean_test_plugins_dir",
        "app.modules.versioning.infrastructure.test_runner.clean_test_plugins_dir",
    ),
    (
        "artifact staging/check",
        "app.modules.versioning.infrastructure.bot_drivers.FakePlayerNextDriver.get_artifact_path",
    ),
    (
        "resolve_verification_strategy",
        "app.modules.versioning.infrastructure.test_runner.resolve_verification_strategy",
    ),
    (
        "resolve_test_docker_image",
        "app.modules.versioning.infrastructure.test_runner.resolve_test_docker_image",
    ),
    (
        "generate_rcon_password + env build",
        "app.modules.versioning.infrastructure.test_runner.generate_rcon_password",
    ),
]


def _create_test_spec(tmp_path: Path, test_id: str = "t-b4-test") -> tuple[TestSpec, Path]:
    srv_dir = tmp_path / f"server-{test_id}"
    srv_dir.mkdir(parents=True, exist_ok=True)
    (srv_dir / "server.properties").write_text("motd=ProdServer\n", encoding="utf-8")
    (srv_dir / "server.jar").write_bytes(b"dummy jar content")

    manifest = CommitManifest(
        server_type="paper",
        minecraft_version="26.2",
        configs={"server.properties": "motd=TestServer\n"},
    )
    commit = ServerCommit(
        id=f"c-{test_id}", server_id="srv-b4", message="test commit", manifest=manifest
    )
    bot_cfg = BotVerificationConfig(
        bot_count=2, duration_minutes=1, bot_tech=BotTech.FAKEPLAYER_NEXT
    )

    spec = TestSpec(
        test_id=test_id,
        server_id="srv-b4",
        commit=commit,
        server_dir=str(srv_dir),
        bot_config=bot_cfg,
    )
    return spec, srv_dir


@pytest.mark.asyncio
@pytest.mark.parametrize("step_name, patch_target", CLASS_A_STEPS)
async def test_b4_class_a_step_failure_downgrades_to_smoke(
    tmp_path: Path, step_name: str, patch_target: str
) -> None:
    runner = DockerTestExecutionRunner()
    run_tag = f"t-a-{step_name.replace(' ', '-').replace('/', '-')}"
    spec, srv_dir = _create_test_spec(tmp_path, run_tag)

    test_dir = srv_dir / ".onx" / "tests" / spec.test_id
    plugins_dir = test_dir / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    (plugins_dir / "fakeplayer-0.4.4.jar").write_bytes(b"PK\x03\x04" + b"\x00" * 1_048_576)

    logs_dir = test_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "latest.log").write_text(
        "[12:00:10] [Server thread/INFO]: Done (2.5s)! For help, type 'help'\n",
        encoding="utf-8",
    )

    captured_calls: list[dict] = []

    def fake_run(cmd, **kwargs):
        captured_calls.append({"cmd": list(cmd), "kwargs": kwargs})
        cmd_str = " ".join(str(c) for c in cmd)
        if "inspect" in cmd_str and "State.Running" in cmd_str:
            return MagicMock(returncode=0, stdout="true\n", stderr="")
        if "inspect" in cmd_str and "State.ExitCode" in cmd_str:
            return MagicMock(returncode=0, stdout="0\n", stderr="")
        return MagicMock(returncode=0, stdout="container-id\n", stderr="")

    with (
        patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
        patch.object(ResourcePreflightProbe, "assert_sufficient_resources", return_value=None),
        patch("subprocess.run", side_effect=fake_run),
        patch(patch_target, side_effect=RuntimeError(f"Simulated error in {step_name}")),
    ):
        handle = await runner.run_test(spec)
        res = await handle.wait_for_completion()

        assert res.passed is True
        assert f"pre-launch step failed: {step_name}: RuntimeError" in (res.failure_reason or "")

        docker_runs = [c for c in captured_calls if c["cmd"][:2] == ["docker", "run"]]
        assert len(docker_runs) == 1, "Docker container should be started for SMOKE run"
        run_cmd = docker_runs[0]["cmd"]

        assert "MODRINTH_PROJECTS=commandapi" not in run_cmd
        assert not any("RCON" in str(tok) for tok in run_cmd)
        assert "eclipse-temurin:25-jre" in run_cmd


CLASS_B_STEPS = [
    (
        "ResourcePreflightProbe",
        "app.modules.versioning.infrastructure.resource_probe.ResourcePreflightProbe.assert_sufficient_resources",
    ),
    (
        "world clone",
        "app.modules.versioning.infrastructure.btrfs_zfs_driver.BtrfsZfsSnapshotDriver.clone_world",
    ),
    (
        "config/mod staging",
        "app.modules.versioning.infrastructure.test_runner.stage_file_reflink_or_copy",
    ),
    (
        "write_test_server_properties",
        "app.modules.versioning.infrastructure.test_runner.write_test_server_properties",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("step_name, patch_target", CLASS_B_STEPS)
async def test_b4_class_b_step_failure_persists_failed_no_docker_run(
    tmp_path: Path, step_name: str, patch_target: str
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    old_engine = database._engine
    old_factory = database._session_factory
    database._engine = engine
    database._session_factory = session_factory

    try:
        runner = DockerTestExecutionRunner()
        run_tag = f"t-b-{step_name.replace(' ', '-').replace('/', '-')}"
        spec, _srv_dir = _create_test_spec(tmp_path, run_tag)

        async with session_factory() as session:
            init_run = ServerTestRun(
                id=spec.test_id,
                server_id=spec.server_id,
                commit_id=spec.commit.id,
                status=TestRunStatus.RUNNING,
            )
            repo = SQLVersioningRepository(session)
            await repo.save_test_run(init_run)
            await session.commit()

        captured_calls: list[dict] = []

        def fake_run(cmd, **kwargs):
            captured_calls.append({"cmd": list(cmd), "kwargs": kwargs})
            return MagicMock(returncode=0, stdout="", stderr="")

        with (
            patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
            patch.object(ResourcePreflightProbe, "assert_sufficient_resources", return_value=None),
            patch("subprocess.run", side_effect=fake_run),
            patch(patch_target, side_effect=RuntimeError(f"Simulated fatal error in {step_name}")),
        ):
            handle = await runner.run_test(spec)
            assert handle.status == TestRunStatus.FAILED

            res = await handle.wait_for_completion()
            assert res.passed is False
            expected_reason = f"pre-launch failed: {step_name}: RuntimeError"
            assert res.failure_reason == expected_reason

            docker_runs = [c for c in captured_calls if c["cmd"][:2] == ["docker", "run"]]
            assert len(docker_runs) == 0, "docker run MUST NEVER be called on Class B failure"

            async with session_factory() as session:
                db_run = await session.get(ServerTestRunModel, spec.test_id)
                assert db_run is not None
                assert db_run.status == "FAILED"
                assert db_run.failure_reason == expected_reason
                assert db_run.evidence_bundle is not None
                assert db_run.evidence_bundle["assertions"]["container_started"] is False
    finally:
        database._engine = old_engine
        database._session_factory = old_factory
        await engine.dispose()


@pytest.mark.asyncio
async def test_b4_class_b_test_dir_materialization_failure(tmp_path: Path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    old_engine = database._engine
    old_factory = database._session_factory
    database._engine = engine
    database._session_factory = session_factory

    try:
        runner = DockerTestExecutionRunner()
        spec, _ = _create_test_spec(tmp_path, "t-b-mkdir")

        async with session_factory() as session:
            init_run = ServerTestRun(
                id=spec.test_id,
                server_id=spec.server_id,
                commit_id=spec.commit.id,
                status=TestRunStatus.RUNNING,
            )
            repo = SQLVersioningRepository(session)
            await repo.save_test_run(init_run)
            await session.commit()

        captured_calls: list[dict] = []

        def fake_run(cmd, **kwargs):
            captured_calls.append({"cmd": list(cmd), "kwargs": kwargs})
            return MagicMock(returncode=0, stdout="", stderr="")

        def failing_mkdir(*_args, **_kwargs):
            raise OSError("Simulated disk error in test dir creation")

        with (
            patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
            patch.object(ResourcePreflightProbe, "assert_sufficient_resources", return_value=None),
            patch("subprocess.run", side_effect=fake_run),
            patch.object(Path, "mkdir", side_effect=failing_mkdir),
        ):
            handle = await runner.run_test(spec)
            assert handle.status == TestRunStatus.FAILED

            res = await handle.wait_for_completion()
            assert res.passed is False
            expected_reason = "pre-launch failed: test dir creation/materialization: OSError"
            assert res.failure_reason == expected_reason

            docker_runs = [c for c in captured_calls if c["cmd"][:2] == ["docker", "run"]]
            assert len(docker_runs) == 0

            async with session_factory() as session:
                db_run = await session.get(ServerTestRunModel, spec.test_id)
                assert db_run is not None
                assert db_run.status == "FAILED"
                assert db_run.failure_reason == expected_reason
    finally:
        database._engine = old_engine
        database._session_factory = old_factory
        await engine.dispose()


@pytest.mark.asyncio
async def test_b4_secrets_never_appear_in_reasons_logs_or_evidence(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    old_engine = database._engine
    old_factory = database._session_factory
    database._engine = engine
    database._session_factory = session_factory

    secret_leak = "S3CR3T_PW_NEVER_LEAK_ME_123"

    try:
        runner = DockerTestExecutionRunner()
        spec, _ = _create_test_spec(tmp_path, "t-b-secret")

        async with session_factory() as session:
            init_run = ServerTestRun(
                id=spec.test_id,
                server_id=spec.server_id,
                commit_id=spec.commit.id,
                status=TestRunStatus.RUNNING,
            )
            repo = SQLVersioningRepository(session)
            await repo.save_test_run(init_run)
            await session.commit()

        with (
            caplog.at_level(logging.DEBUG),
            patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
            patch.object(ResourcePreflightProbe, "assert_sufficient_resources", return_value=None),
            patch(
                "app.modules.versioning.infrastructure.btrfs_zfs_driver.BtrfsZfsSnapshotDriver.clone_world",
                side_effect=RuntimeError(f"Cloning failed with secret key: {secret_leak}"),
            ),
        ):
            handle = await runner.run_test(spec)
            res = await handle.wait_for_completion()

            assert secret_leak not in (res.failure_reason or "")
            assert secret_leak not in caplog.text

            async with session_factory() as session:
                db_run = await session.get(ServerTestRunModel, spec.test_id)
                assert db_run is not None
                assert secret_leak not in (db_run.failure_reason or "")
                assert secret_leak not in str(db_run.evidence_bundle)
    finally:
        database._engine = old_engine
        database._session_factory = old_factory
        await engine.dispose()


@pytest.mark.asyncio
async def test_b4_cancelled_error_propagates_unswallowed(tmp_path: Path) -> None:
    runner = DockerTestExecutionRunner()
    spec, _ = _create_test_spec(tmp_path, "t-cancel-a")

    with (
        patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
        patch.object(ResourcePreflightProbe, "assert_sufficient_resources", return_value=None),
        patch(
            "app.modules.versioning.infrastructure.test_runner.clean_test_plugins_dir",
            side_effect=asyncio.CancelledError(),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await runner.run_test(spec)

    spec_b, _ = _create_test_spec(tmp_path, "t-cancel-b")
    with (
        patch.object(
            ResourcePreflightProbe,
            "assert_sufficient_resources",
            side_effect=asyncio.CancelledError(),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await runner.run_test(spec_b)
