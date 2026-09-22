from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.modules.health.infrastructure.crash_analyzer import PatternCrashAnalyzer
from app.modules.server.application.services.jar_service import generate_rcon_password
from app.modules.server.infrastructure.providers.docker import (
    build_docker_server_cmd,
    resolve_docker_image,
    resolve_host_mount_path,
)
from app.modules.versioning.domain.deployment import TestServerDeployment
from app.modules.versioning.domain.entities import Runtime, ServerCommit
from app.modules.versioning.domain.value_objects import (
    BotTech,
    BotVerificationConfig,
    PlacementMode,
    RuntimeStatus,
    TestRunStatus,
)
from app.modules.versioning.infrastructure.bot_drivers import (
    BotVerificationResult,
    FakePlayerNextDriver,
    MineflayerBotDriver,
    PluginCheck,
    SmokeTestRunner,
    cap_log_output,
    check_plugin_enabled,
    generate_bot_names_prefix,
)
from app.modules.versioning.infrastructure.bot_pool import (
    PooledRunner,
    get_bot_runner_pool,
)
from app.modules.versioning.infrastructure.btrfs_zfs_driver import BtrfsZfsSnapshotDriver
from app.modules.versioning.infrastructure.compatibility import (
    StrategyResult,
    VerificationMode,
    is_fakeplayer_artifact_usable,
    resolve_verification_strategy,
)
from app.modules.versioning.infrastructure.config_writer import write_test_server_properties
from app.modules.versioning.infrastructure.resource_probe import ResourcePreflightProbe
from app.modules.versioning.infrastructure.storage_probe import StorageCapabilityProbe
from app.modules.versioning.infrastructure.test_env import (
    build_test_container_env,
    clean_test_plugins_dir,
    resolve_test_docker_image,
)

logger = logging.getLogger(__name__)


def stage_file_reflink_or_copy(src: Path, dst: Path) -> None:
    """Copy src → dst preferring reflink, falling back to shutil.copy2.

    SPEC-2026-09-15-ISOLATED-TEST-BOOT-CONTRACT-01 §2.2 — Return-Code Safety Rule:
    Checks the subprocess return code explicitly.  A cp that is *found* on PATH
    but exits non-zero (e.g. MSYS2 cp without --reflink support) would previously
    pass the `except Exception` guard silently — this helper closes that gap.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        res = subprocess.run(
            ["cp", "--reflink=auto", str(src), str(dst)],
            capture_output=True,
            check=False,
        )
        if res.returncode != 0 or not dst.exists():
            shutil.copy2(src, dst)
    except Exception:
        shutil.copy2(src, dst)


class _PrelaunchFatalError(Exception):
    def __init__(self, step_name: str, original_exc: Exception) -> None:
        super().__init__(f"pre-launch failed: {step_name}: {type(original_exc).__name__}")
        self.step_name = step_name
        self.original_exc = original_exc


@contextlib.contextmanager
def _class_b_step(step_name: str):
    try:
        yield
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        raise _PrelaunchFatalError(step_name, exc) from None


@dataclass(frozen=True)
class TestSpec:
    __test__ = False

    test_id: str
    server_id: str
    commit: ServerCommit
    server_dir: str
    bot_config: BotVerificationConfig
    node_id: str = "local"
    minecraft_version: str = "1.21.1"


@dataclass
class TestHandle:
    __test__ = False

    test_id: str
    server_id: str
    container_name: str
    test_dir: str
    sidecar_runner: PooledRunner | None
    status: TestRunStatus
    runtime_id: str | None = None
    evidence_bundle: dict[str, Any] | None = None
    _completion_future: asyncio.Future[BotVerificationResult] = field(
        default_factory=asyncio.Future
    )

    async def wait_for_completion(self) -> BotVerificationResult:
        return await self._completion_future

    def set_result(
        self,
        res: BotVerificationResult,
        evidence_bundle: dict[str, Any] | None = None,
    ) -> None:
        if evidence_bundle is not None:
            self.evidence_bundle = evidence_bundle
        if not self._completion_future.done():
            self._completion_future.set_result(res)


class TestExecutionRunner(ABC):
    """Abstract interface for test execution runners (Multi-node groundwork §3.7)."""

    @abstractmethod
    async def run_test(self, spec: TestSpec) -> TestHandle:
        pass

    @abstractmethod
    async def cleanup_test(self, handle: TestHandle, passed: bool = True) -> None:
        pass


class DockerTestExecutionRunner(TestExecutionRunner):
    """Docker-based isolated test container and bot verification runner.

    Enforces Design Spec §3.4, §3.5, §3.6, §3.7:
    - COW world clone via reflink block cloning.
    - Test server.properties written strictly via TestServerDeployment.
    - Isolated bridge network mode, unmapped ports.
    - Automated bot runtime sanity verification.
    """

    def __init__(self, event_bus: Any | None = None) -> None:
        self._active_runs: dict[str, TestHandle] = {}
        self._event_bus = event_bus
        self._evidence_store: dict[str, Any] = {}

    async def _persist_runtime(self, runtime: Runtime) -> None:
        from app.core.persistence.db import database
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        try:
            _ = database.session_factory
        except RuntimeError:
            return

        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with database.session_factory() as session:
                    repo = SQLVersioningRepository(session)
                    await repo.save_runtime(runtime)
                    await session.commit()
                break
            except Exception as exc:
                is_lock = "locked" in str(exc).lower() or "busy" in str(exc).lower()
                if is_lock and attempt < max_retries - 1:
                    await asyncio.sleep(0.05 * (2**attempt))
                    continue
                logger.debug("Failed to persist runtime %s: %s", runtime.id, exc)
                break

    def _downgrade_to_smoke(
        self,
        step_name: str,
        exc: Exception,
        prior_strat: StrategyResult | None,
        bot_cfg: BotVerificationConfig,
        server_type: str,
        reason: str | None = None,
    ) -> StrategyResult:
        exc_type = type(exc).__name__
        logger.warning("Pre-launch step %s failed: %s", step_name, exc_type)
        was_fakeplayer = (
            prior_strat is not None
            and (
                prior_strat.driver == "fakeplayer_next"
                or prior_strat.downgraded_from == "fakeplayer_next"
            )
        ) or (
            prior_strat is None
            and (
                bot_cfg.bot_tech == BotTech.FAKEPLAYER_NEXT
                or (
                    bot_cfg.bot_tech == BotTech.AUTO
                    and (server_type or "").lower() in ("paper", "purpur")
                )
            )
        )
        msg = reason or f"pre-launch step failed: {step_name}: {exc_type}"
        return StrategyResult(
            mode=VerificationMode.SMOKE_TEST,
            driver="none",
            reason=msg,
            downgraded_from="fakeplayer_next" if was_fakeplayer else None,
            artifact_ok=False,
        )

    async def _handle_prelaunch_fatal_failure(
        self,
        spec: TestSpec,
        step_name: str,
        exc: Exception,
        test_dir_str: str,
    ) -> TestHandle:
        exc_type = type(exc).__name__
        logger.warning("Pre-launch step %s failed: %s", step_name, exc_type)
        failure_reason = f"pre-launch failed: {step_name}: {exc_type}"
        logs = [f"[PRE-LAUNCH FAILURE] {failure_reason}"]
        container_name = f"onx-test-{spec.test_id}"

        evidence_bundle = {
            "test_id": spec.test_id,
            "server_id": spec.server_id,
            "commit_id": spec.commit.id,
            "runtime": {
                "runtime_id": None,
                "container_name": container_name,
                "exit_code": 1,
                "oom_killed": False,
                "duration_seconds": 0.0,
            },
            "assertions": {
                "container_started": False,
                "boot_gate_passed": False,
                "bots_spawned_target": spec.bot_config.bot_count,
                "bots_spawned_actual": 0,
                "crash_reports_found": 0,
                "clean_shutdown": False,
            },
            "crash_analysis": {
                "blamed_mod": None,
                "failure_code": None,
                "summary": failure_reason,
                "crash_report_path": None,
            },
            "log_tail": logs,
        }

        if self._event_bus is not None:
            try:
                from app.modules.versioning.domain.events import TestRunFailedEvent

                await self._event_bus.publish(
                    TestRunFailedEvent(
                        server_id=spec.server_id,
                        test_id=spec.test_id,
                        commit_id=spec.commit.id,
                        failure_code=None,
                        blamed_mod=None,
                    )
                )
            except Exception as eb_err:
                logger.debug("Failed publishing TestRunFailedEvent: %s", eb_err)

        capped_log = cap_log_output("\n".join(logs))
        await self._persist_test_outcome(
            test_id=spec.test_id,
            passed=False,
            failure_reason=failure_reason,
            log_output=capped_log,
            runtime_id=None,
            evidence_bundle=evidence_bundle,
        )

        handle = TestHandle(
            test_id=spec.test_id,
            server_id=spec.server_id,
            container_name=container_name,
            test_dir=test_dir_str,
            sidecar_runner=None,
            status=TestRunStatus.FAILED,
            runtime_id=None,
        )
        result = BotVerificationResult(
            passed=False,
            connected_bots=0,
            total_bots=spec.bot_config.bot_count,
            disconnects=0,
            survived_duration_seconds=0.0,
            failure_reason=failure_reason,
            logs=logs,
        )
        self._evidence_store[spec.test_id] = evidence_bundle
        handle.set_result(result, evidence_bundle=evidence_bundle)

        try:
            await self.cleanup_test(handle, passed=False)
        except Exception as cleanup_exc:
            logger.warning(
                "Test container cleanup failed for %s: %s",
                spec.test_id,
                cleanup_exc,
            )

        return handle

    async def run_test(self, spec: TestSpec) -> TestHandle:
        # Stage D: concurrency is governed by the global admission gate
        # (RunIsolatedTestHandler → admit()), not by a per-server lock.
        # This runner is a plain executor: materialize → launch → verify.
        manifest = spec.commit.manifest
        server_type = manifest.server_type
        mc_version = manifest.minecraft_version or spec.minecraft_version

        test_root = Path(spec.server_dir) / ".onx" / "tests" / spec.test_id
        test_dir_str = str(test_root.resolve())

        try:
            # 1. Check storage COW capability (Class B)
            with _class_b_step("StorageCapabilityProbe"):
                StorageCapabilityProbe.assert_supports_reflink(spec.server_dir)

            # 2. Check physical system headroom (Class B)
            with _class_b_step("ResourcePreflightProbe"):
                ResourcePreflightProbe.assert_sufficient_resources(
                    bot_count=spec.bot_config.bot_count,
                    server_type=server_type,
                )

            # 3. Materialize test directory under .onx/tests/<test_id> (Class B)
            with _class_b_step("test dir creation/materialization"):
                test_root.mkdir(parents=True, exist_ok=True)

            # 4. COW world clone (Class B)
            with _class_b_step("world clone"):
                BtrfsZfsSnapshotDriver.clone_world(spec.server_dir, test_dir_str)

            # 5. Write manifest configs & mod jars into test directory (Class B)
            staged_startup_jar: str | None = None
            server_startup_cmd: list[str] | None = None
            with _class_b_step("config/mod staging"):
                for rel_path, content in manifest.configs.items():
                    if rel_path != "server.properties":
                        tgt = test_root / rel_path
                        tgt.parent.mkdir(parents=True, exist_ok=True)
                        tgt.write_text(content, encoding="utf-8")

                # Copy mods
                live_mods = Path(spec.server_dir) / "mods"
                test_mods = test_root / "mods"
                if live_mods.is_dir():
                    test_mods.mkdir(parents=True, exist_ok=True)
                    for mod_ref in manifest.mods:
                        src_mod = Path(spec.server_dir) / mod_ref["filename"]
                        if src_mod.is_file():
                            dst_mod = test_root / mod_ref["filename"]
                            stage_file_reflink_or_copy(src_mod, dst_mod)

                # 5b. Stage server executable (jar or run.sh / user_jvm_args.txt)
                run_sh_src = Path(spec.server_dir) / "run.sh"
                if run_sh_src.is_file():
                    run_sh_dst = test_root / "run.sh"
                    stage_file_reflink_or_copy(run_sh_src, run_sh_dst)
                    run_sh_dst.chmod(0o755)
                    jvm_args_src = Path(spec.server_dir) / "user_jvm_args.txt"
                    if jvm_args_src.is_file():
                        stage_file_reflink_or_copy(jvm_args_src, test_root / "user_jvm_args.txt")
                    server_startup_cmd = ["bash", "run.sh", "nogui"]
                else:
                    candidate_jar: Path | None = None
                    default_jar = Path(spec.server_dir) / "server.jar"
                    if default_jar.is_file():
                        candidate_jar = default_jar
                    else:
                        jars = sorted(Path(spec.server_dir).glob("*.jar"))
                        if jars:
                            candidate_jar = jars[0]
                    if candidate_jar is not None:
                        staged_startup_jar = candidate_jar.name
                        stage_file_reflink_or_copy(candidate_jar, test_root / candidate_jar.name)

            test_deployment = TestServerDeployment(test_id=spec.test_id, test_dir=test_dir_str)

            # Class A: clean_test_plugins_dir
            strat: StrategyResult | None = None
            try:
                clean_test_plugins_dir(Path(test_deployment.server_dir))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                strat = self._downgrade_to_smoke(
                    "clean_test_plugins_dir", exc, strat, spec.bot_config, server_type
                )

            # Class A: artifact staging/check
            artifact_path: Path | str | None = None
            if strat is None:
                try:
                    candidate = FakePlayerNextDriver.get_artifact_path(test_deployment)
                    is_usable, _ = is_fakeplayer_artifact_usable(candidate)
                    if is_usable:
                        artifact_path = candidate
                    else:
                        is_fp_eligible = (
                            spec.bot_config.bot_tech in (BotTech.AUTO, BotTech.FAKEPLAYER_NEXT)
                        ) and ((server_type or "").lower() in ("paper", "purpur"))
                        if is_fp_eligible:
                            from app.core.config import AppSettings
                            from app.modules.versioning.infrastructure.plugin_artifact import (
                                ArtifactFailure,
                                ensure_plugin_artifact,
                                stage_plugin_artifact,
                            )

                            settings = AppSettings()
                            data_root = Path(settings.servers_data_dir).parent
                            art_res = await ensure_plugin_artifact(data_root=data_root)
                            if isinstance(art_res, ArtifactFailure):
                                strat = self._downgrade_to_smoke(
                                    "artifact staging/check",
                                    RuntimeError(art_res.reason),
                                    strat,
                                    spec.bot_config,
                                    server_type,
                                    reason=(
                                        f"pre-launch step failed: artifact staging/check: "
                                        f"{art_res.reason}"
                                    ),
                                )
                            else:
                                staged_jar = stage_plugin_artifact(
                                    cached=art_res,
                                    test_dir=Path(test_deployment.server_dir),
                                )
                                artifact_path = staged_jar
                        else:
                            artifact_path = candidate
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    strat = self._downgrade_to_smoke(
                        "artifact staging/check", exc, strat, spec.bot_config, server_type
                    )

            # Class A: resolve_verification_strategy
            if strat is None:
                try:
                    strat = resolve_verification_strategy(
                        server_type=server_type,
                        minecraft_version=mc_version,
                        bot_tech=spec.bot_config.bot_tech,
                        artifact_path=artifact_path,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    strat = self._downgrade_to_smoke(
                        "resolve_verification_strategy", exc, strat, spec.bot_config, server_type
                    )

            # Class A: resolve_test_docker_image
            image: str
            try:
                image, strat = resolve_test_docker_image(
                    minecraft_version=mc_version,
                    strategy=strat,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                strat = self._downgrade_to_smoke(
                    "resolve_test_docker_image", exc, strat, spec.bot_config, server_type
                )
                image = resolve_docker_image(minecraft_version=mc_version)

            # Class B: write_test_server_properties
            base_props = {}
            if "server.properties" in manifest.configs:
                for line in manifest.configs["server.properties"].splitlines():
                    if "=" in line and not line.strip().startswith("#"):
                        k, v = line.split("=", 1)
                        base_props[k.strip()] = v.strip()

            with _class_b_step("write_test_server_properties"):
                write_test_server_properties(
                    deployment=test_deployment,
                    base_properties=base_props,
                    server_port=25565,
                    bot_count=spec.bot_config.bot_count,
                )

            # Class A: generate_rcon_password + env build
            rcon_password: str | None = None
            proc_env: dict[str, str] | None = None
            container_env: dict[str, str]
            try:
                if strat.driver == "fakeplayer_next":
                    rcon_password = generate_rcon_password()
                    proc_env = {**os.environ, "RCON_PASSWORD": rcon_password}

                container_env = build_test_container_env(
                    server_type=server_type,
                    minecraft_version=mc_version,
                    strategy=strat,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                strat = self._downgrade_to_smoke(
                    "generate_rcon_password + env build",
                    exc,
                    strat,
                    spec.bot_config,
                    server_type,
                )
                image = resolve_docker_image(minecraft_version=mc_version)
                rcon_password = None
                proc_env = None
                container_env = build_test_container_env(
                    server_type=server_type,
                    minecraft_version=mc_version,
                    strategy=strat,
                )

            container_name = f"onx-test-{spec.test_id}"
            host_mount = resolve_host_mount_path(test_dir_str)

            # Build server CMD — startup_command passed explicitly (no disk detection in helper).
            # SPEC-2026-09-15-ISOLATED-TEST-BOOT-CONTRACT-01 §2.1
            server_cmd = build_docker_server_cmd(
                startup_command=server_startup_cmd,
                startup_jar=staged_startup_jar,
                image=image,
            )

        except _PrelaunchFatalError as fatal_err:
            return await self._handle_prelaunch_fatal_failure(
                spec, fatal_err.step_name, fatal_err.original_exc, test_dir_str
            )
        except asyncio.CancelledError:
            raise
        except Exception as unexpected_exc:
            return await self._handle_prelaunch_fatal_failure(
                spec, "pre-launch", unexpected_exc, test_dir_str
            )

        # Memory budget: 2 GB min / 4 GB max, with 512 MB Docker headroom.
        memory_max_mb = 4096
        docker_cmd = [
            "docker",
            "run",
            "-d",
            "--name",
            container_name,
            "--network",
            "bridge",
            "-v",
            f"{host_mount}:/data",
            "-w",
            "/data",
            "--memory",
            f"{memory_max_mb + 512}m",
            # Host UID mapping (Must-Fix 5): match the regular-server launch contract
            # (docker.py --user uid:gid) so container writes land on disk as the
            # host user. Without this, a root-owned boot (e.g. auto-created
            # plugins/) denies later host-side writes (PermissionError, run 61d84dd5).
            # Must precede IMAGE: everything after IMAGE is the container CMD,
            # and a misplaced --user there kills the entrypoint (run 6f354058).
            *(
                ["--user", f"{os.getuid()}:{os.getgid()}"]
                if hasattr(os, "getuid") and hasattr(os, "getgid") and sys.platform != "win32"
                else []
            ),
        ]
        for env_k, env_v in container_env.items():
            docker_cmd.extend(["-e", f"{env_k}={env_v}"])

        # Fix B1: RCON_PASSWORD is passed without value in argv; value is in proc_env
        if strat.driver == "fakeplayer_next":
            docker_cmd.extend(["-e", "RCON_PASSWORD"])

        docker_cmd.append(image)
        docker_cmd.extend(server_cmd)

        try:
            res = await asyncio.to_thread(
                subprocess.run,
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=30,
                env=proc_env,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("Docker test container startup timed out after 30s") from None
        except subprocess.CalledProcessError as cpe:
            raise RuntimeError(
                f"Docker test container startup failed with exit code {cpe.returncode}"
            ) from None
        except Exception as exc:
            err_msg = str(exc)
            if rcon_password and rcon_password in err_msg:
                err_msg = err_msg.replace(rcon_password, "[REDACTED]")
            raise RuntimeError(f"Failed to launch test container: {err_msg}") from None

        if res.returncode != 0:
            err_msg = res.stderr.strip()[:200]
            if rcon_password and rcon_password in err_msg:
                err_msg = err_msg.replace(rcon_password, "[REDACTED]")
            raise RuntimeError(f"Failed to start isolated test container: {err_msg}")

        runtime_id = f"rt-{spec.test_id[:12]}"
        handle = TestHandle(
            test_id=spec.test_id,
            server_id=spec.server_id,
            container_name=container_name,
            test_dir=test_dir_str,
            sidecar_runner=None,
            status=TestRunStatus.RUNNING,
            runtime_id=runtime_id,
        )
        self._active_runs[spec.test_id] = handle

        runtime = Runtime(
            id=runtime_id,
            server_id=spec.server_id,
            commit_id=spec.commit.id,
            container_id=container_name,
            port=25565,
            status=RuntimeStatus.RUNNING,
        )
        try:
            await self._persist_runtime(runtime)
        except Exception as rt_err:
            logger.debug("Initial runtime persistence skipped: %s", rt_err)

        # Launch background verification execution (no lock is held: admission
        # owns concurrency policy; failures surface via handle + DB outcome).
        asyncio.create_task(
            self._execute_verification(
                spec,
                handle,
                test_deployment,
                strategy=strat,
                rcon_password=rcon_password,
            )
        )
        return handle

    async def _execute_verification(
        self,
        spec: TestSpec,
        handle: TestHandle,
        test_deployment: TestServerDeployment,
        strategy: StrategyResult | None = None,
        rcon_password: str | None = None,
    ) -> None:
        """Background execution of bot verification against the test container."""
        bot_cfg = spec.bot_config
        logs: list[str] = []
        failure_reason: str | None = None
        passed = False
        connected_bots = 0
        duration_s = bot_cfg.duration_minutes * 60.0
        plugin_enabled: bool | None = None
        spawn_ok = 0
        spawn_failed = 0
        actions_ok = 0
        actions_failed = 0
        bot_names_prefix: str | None = None

        def _scrub(s: str | None) -> str:
            if not s:
                return ""
            if rcon_password:
                return s.replace(rcon_password, "***")
            return s

        sidecar: PooledRunner | None = None
        pool = get_bot_runner_pool()

        try:
            # 1. Resolve loader and version strategy (defensive post-launch re-check)
            server_type = spec.commit.manifest.server_type
            mc_version = spec.commit.manifest.minecraft_version or spec.minecraft_version
            if strategy is not None and strategy.mode == VerificationMode.SMOKE_TEST:
                strat = strategy
            else:
                try:
                    art_path = FakePlayerNextDriver.get_artifact_path(test_deployment)
                except Exception:
                    art_path = None
                current_strat = resolve_verification_strategy(
                    server_type=server_type,
                    minecraft_version=mc_version,
                    bot_tech=bot_cfg.bot_tech,
                    artifact_path=art_path,
                )
                if strategy is not None:
                    if (
                        strategy.mode == VerificationMode.FULL_BOT
                        and current_strat.mode == VerificationMode.SMOKE_TEST
                    ):
                        strat = current_strat
                    else:
                        strat = strategy
                else:
                    strat = current_strat
            mode = strat.mode
            driver = strat.driver
            explanation = strat.reason
            logs.append(
                f"[BOT-VERIFY] Strategy: mode={mode.value}, driver={driver}, reason={explanation}"
            )

            # 2. Inspect container IP on bridge network
            inspect_res = await asyncio.to_thread(
                subprocess.run,
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                    handle.container_name,
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            has_ip = inspect_res.returncode == 0 and inspect_res.stdout.strip()
            container_ip = inspect_res.stdout.strip() if has_ip else "127.0.0.1"

            # 3. Boot-gate: poll <test_dir>/logs/latest.log for "Done (" before verification.
            # SPEC-2026-09-15-ISOLATED-TEST-BOOT-CONTRACT-01 §2.4
            # Must-Fix 6B: floor raised 60s -> 120s. A real Paper 26.2 boot took
            # ~65s wall-clock live (run c4273f97); Forge/modded boots take longer.
            # Dead containers still fail fast via the liveness check below, so a
            # higher ceiling does not slow the common failure case.
            # Documented connect_grace_seconds default remains 60.0 everywhere;
            # this floor is deliberately above it.
            boot_timeout = max(getattr(bot_cfg, "connect_grace_seconds", 60.0), 120.0)
            logs.append(
                f"[BOOT-GATE] Waiting up to {boot_timeout:.0f}s for server boot "
                "(polling logs/latest.log for 'Done (')..."
            )
            boot_poll_start = asyncio.get_event_loop().time()
            boot_passed = False
            boot_failure_reason: str | None = None

            while True:
                # Check crash reports
                crash_dir_check = Path(handle.test_dir) / "crash-reports"
                if crash_dir_check.exists() and any(crash_dir_check.glob("crash-*.txt")):
                    first_crash = next(crash_dir_check.glob("crash-*.txt"))
                    try:
                        content = first_crash.read_text(encoding="utf-8", errors="replace")
                        analyzer = PatternCrashAnalyzer()
                        analysis = analyzer.analyze_crash_content(content)
                        blamed = analysis.blamed_mod or "Unknown mod"
                        boot_failure_reason = (
                            f"Server crashed during boot. Blamed mod: {blamed} "
                            f"({analysis.failure_code.value})"
                        )
                    except Exception:
                        boot_failure_reason = f"Server crashed during boot: {first_crash.name}"
                    logs.append(f"[BOOT-GATE] {boot_failure_reason}")
                    break

                # Check container liveness
                liveness_check = await asyncio.to_thread(
                    subprocess.run,
                    [
                        "docker",
                        "inspect",
                        "-f",
                        "{{.State.Running}}",
                        handle.container_name,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                is_alive = (
                    liveness_check.returncode == 0 and "true" in liveness_check.stdout.lower()
                )
                if not is_alive:
                    boot_failure_reason = (
                        "Test server container terminated unexpectedly before completing boot"
                    )
                    logs.append(f"[BOOT-GATE] {boot_failure_reason}")
                    break

                # Check latest.log
                latest_log_path = Path(handle.test_dir) / "logs" / "latest.log"
                if latest_log_path.exists():
                    log_text = latest_log_path.read_text(encoding="utf-8", errors="replace")
                    if "Done (" in log_text:
                        boot_passed = True
                        logs.append("[BOOT-GATE] Server boot confirmed ('Done (' found in logs).")
                        break

                elapsed = asyncio.get_event_loop().time() - boot_poll_start
                if elapsed >= boot_timeout:
                    boot_failure_reason = (
                        f"Server did not complete boot within {boot_timeout:.0f}s "
                        "(no 'Done (' found in logs/latest.log)"
                    )
                    logs.append(f"[BOOT-GATE] Timeout: {boot_failure_reason}")
                    break

                await asyncio.sleep(0.5)

            if not boot_passed:
                passed = False
                failure_reason = boot_failure_reason
                # Skip verification drivers — fall through to finally block.
            else:
                if strat.driver == "fakeplayer_next":
                    bot_names_prefix = generate_bot_names_prefix(spec.test_id[:8])
                    plugin_log_path = Path(handle.test_dir) / "logs" / "latest.log"
                    try:
                        log_text = plugin_log_path.read_text(encoding="utf-8", errors="replace")
                        plugin_check = check_plugin_enabled(log_text, plugin_name="fakeplayer")
                    except Exception:
                        plugin_check = PluginCheck(enabled=False, marker="plugin log unreadable")

                    if not plugin_check.enabled:
                        marker = plugin_check.marker or "plugin not enabled after boot"
                        strat = StrategyResult(
                            mode=VerificationMode.SMOKE_TEST,
                            driver="none",
                            reason=f"plugin verification failed: {marker}",
                            downgraded_from="fakeplayer_next",
                            artifact_ok=strat.artifact_ok,
                        )
                        mode = strat.mode
                        driver = strat.driver
                        plugin_enabled = False
                    else:
                        plugin_enabled = True

                # 4. Branch by verification mode & driver
                if mode == VerificationMode.SMOKE_TEST:
                    logs.append(
                        f"[BOT-VERIFY] Smoke Test Mode: {server_type} ({spec.minecraft_version})"
                    )
                    smoke_res = await SmokeTestRunner.run_smoke_test(
                        test_dir=Path(handle.test_dir),
                        container_name=handle.container_name,
                        timeout_seconds=min(duration_s, 60.0),
                    )
                    passed = smoke_res.passed
                    connected_bots = smoke_res.connected_bots
                    failure_reason = smoke_res.failure_reason
                    if strat.downgraded_from is not None:
                        if failure_reason:
                            failure_reason = f"{strat.reason}; {failure_reason}"
                        else:
                            failure_reason = strat.reason
                    if smoke_res.log_output:
                        logs.append(smoke_res.log_output)

                elif driver == "fakeplayer_next":
                    logs.append(
                        f"[BOT-VERIFY] Spawning {bot_cfg.bot_count} "
                        "RCON-driven FakePlayer-Next plugin bots"
                    )

                    # Execute /fp spawn commands via docker exec or RCON
                    cmd_groups = FakePlayerNextDriver.format_spawn_commands(
                        run_id=spec.test_id[:8],
                        bot_count=bot_cfg.bot_count,
                    )
                    successful_spawns = 0
                    spawned_bots = 0
                    last_error: str | None = None
                    disallowed_stdout_markers = (
                        "is online",
                        "Invalid name",
                        "Incorrect argument",
                        "Unknown",
                    )

                    for grp in cmd_groups:
                        scmd = grp.spawn
                        tokens = scmd.strip().split()
                        is_spawn = len(tokens) >= 2 and tokens[1] == "spawn"
                        try:
                            res = await asyncio.to_thread(
                                subprocess.run,
                                ["docker", "exec", handle.container_name, "rcon-cli", scmd],
                                capture_output=True,
                                text=True,
                                timeout=5,
                            )
                            out_scrubbed = _scrub(res.stdout)
                            err_scrubbed = _scrub(res.stderr)
                            has_disallowed = any(
                                m in out_scrubbed for m in disallowed_stdout_markers
                            )
                            if res.returncode == 0 and not has_disallowed:
                                successful_spawns += 1
                                if is_spawn:
                                    spawned_bots += 1
                                    spawn_ok += 1
                            else:
                                if is_spawn:
                                    spawn_failed += 1
                                last_error = (
                                    err_scrubbed.strip()
                                    or out_scrubbed.strip()
                                    or f"rcon-cli exit code {res.returncode}"
                                )
                                logger.debug("FakePlayer RCON spawn command failed: %s", last_error)
                        except Exception as e:
                            if is_spawn:
                                spawn_failed += 1
                            last_error = _scrub(str(e))
                            logger.debug("Failed injecting fakeplayer command: %s", e)

                        for acmd in grp.actions:
                            try:
                                res_act = await asyncio.to_thread(
                                    subprocess.run,
                                    ["docker", "exec", handle.container_name, "rcon-cli", acmd],
                                    capture_output=True,
                                    text=True,
                                    timeout=5,
                                )
                                if res_act.returncode == 0:
                                    actions_ok += 1
                                else:
                                    actions_failed += 1
                            except Exception:
                                actions_failed += 1

                    for grp in cmd_groups:
                        with contextlib.suppress(Exception):
                            await asyncio.to_thread(
                                subprocess.run,
                                ["docker", "exec", handle.container_name, "rcon-cli", grp.stop],
                                capture_output=True,
                                text=True,
                                timeout=5,
                            )

                    await asyncio.sleep(min(duration_s, 1.0))

                    # Check container liveness before declaring outcome
                    liveness = await asyncio.to_thread(
                        subprocess.run,
                        ["docker", "inspect", "-f", "{{.State.Running}}", handle.container_name],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    is_alive = liveness.returncode == 0 and "true" in liveness.stdout.lower()

                    if not is_alive:
                        passed = False
                        connected_bots = spawned_bots
                        failure_reason = (
                            "Test server container terminated during FakePlayer bot verification"
                        )
                    else:
                        passed = spawned_bots == bot_cfg.bot_count
                        connected_bots = spawned_bots
                        if not passed:
                            err_msg = _scrub(last_error or "Unknown RCON error")
                            failure_reason = (
                                f"Spawned {spawned_bots}/{bot_cfg.bot_count} "
                                f"FakePlayer bots via RCON: {err_msg}"
                            )

                else:
                    # Mineflayer bot technology
                    if bot_cfg.placement_mode == PlacementMode.SIDECAR:
                        try:
                            sidecar = await pool.acquire(timeout=5.0)
                            handle.sidecar_runner = sidecar
                            logs.append(
                                f"[BOT-VERIFY] Acquired pooled sidecar {sidecar.container_name}"
                            )
                        except Exception as e:
                            logger.warning(
                                "Could not acquire pooled runner: %s; falling back to host runner",
                                e,
                            )

                    bot_dir = Path(handle.test_dir) / "bots"
                    logs.append(
                        f"[BOT-VERIFY] Starting Mineflayer harness against "
                        f"{container_ip}:25565 ({bot_cfg.bot_count} bots)"
                    )
                    verify_res = await MineflayerBotDriver.run_mineflayer_verification(
                        bot_dir=bot_dir,
                        host=container_ip,
                        port=25565,
                        run_id=spec.test_id[:8],
                        bot_count=bot_cfg.bot_count,
                        duration_minutes=bot_cfg.duration_minutes,
                        stagger_seconds=bot_cfg.join_stagger_seconds,
                        connect_grace_seconds=bot_cfg.connect_grace_seconds,
                    )
                    logs.extend(verify_res.logs)
                    passed = verify_res.passed
                    connected_bots = verify_res.connected_bots
                    if not passed and not failure_reason:
                        failure_reason = verify_res.failure_reason

                # 5. Post-verification crash check
                crash_dir = Path(handle.test_dir) / "crash-reports"
                if crash_dir.is_dir() and any(crash_dir.glob("crash-*.txt")):
                    passed = False
                    first_crash = next(crash_dir.glob("crash-*.txt"))
                    try:
                        content = first_crash.read_text(encoding="utf-8", errors="replace")
                        analyzer = PatternCrashAnalyzer()
                        analysis = analyzer.analyze_crash_content(content)
                        blamed = analysis.blamed_mod or "Unknown mod"
                        failure_reason = (
                            f"Crash detected in test run. Blamed mod: {blamed} "
                            f"({analysis.failure_code.value})"
                        )
                    except Exception:
                        failure_reason = f"Crash report detected: {first_crash.name}"

        except asyncio.CancelledError:
            failure_reason = "Test run cancelled"
            passed = False
        except Exception as e:
            logger.exception("Test run encountered exception: %s", e)
            failure_reason = str(e)
            passed = False
        finally:
            if sidecar:
                outcome = "clean" if passed else "unhealthy"
                await pool.release(sidecar, outcome=outcome)

            # 1. Container-Level Diagnostics (§c)
            inspect_exit_code = 0 if passed else 1
            inspect_oom = False
            try:
                insp = await asyncio.to_thread(
                    subprocess.run,
                    ["docker", "inspect", handle.container_name],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if insp.returncode == 0:
                    try:
                        insp_data = json.loads(insp.stdout)
                        if isinstance(insp_data, list) and insp_data:
                            state = insp_data[0].get("State", {})
                            inspect_exit_code = state.get("ExitCode", inspect_exit_code)
                            inspect_oom = bool(state.get("OOMKilled", False))
                            if inspect_oom:
                                failure_reason = (
                                    "Test server container was killed by OOM killer "
                                    "(exit code 137). Earmarked RAM exceeded."
                                )
                                passed = False
                            elif inspect_exit_code != 0 and not failure_reason:
                                failure_reason = (
                                    f"Test server container terminated unexpectedly with "
                                    f"exit code {inspect_exit_code}."
                                )
                                passed = False
                    except Exception as json_err:
                        logger.debug(
                            "Failed parsing docker inspect json for %s: %s",
                            handle.container_name,
                            json_err,
                        )
            except Exception as insp_exc:
                logger.debug("Failed docker inspect for %s: %s", handle.container_name, insp_exc)

            if not passed:
                try:
                    c_logs = await asyncio.to_thread(
                        subprocess.run,
                        ["docker", "logs", "--tail", "100", "--timestamps", handle.container_name],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if c_logs.stdout:
                        logs.append(f"[CONTAINER STDERR/LOGS]\n{c_logs.stdout}")
                except Exception as log_tail_err:
                    logger.debug("Failed capturing container stderr tail: %s", log_tail_err)

            # 2. Crash Correlation & Mod Blame (§d)
            blamed_mod: str | None = None
            failure_code: str | None = None
            crash_summary: str | None = None
            crash_report_rel_path: str | None = None
            crash_dir = Path(handle.test_dir) / "crash-reports"
            if crash_dir.is_dir():
                crash_files = list(crash_dir.glob("crash-*.txt"))
                if crash_files:
                    first_crash = crash_files[0]
                    crash_report_rel_path = f"crash-reports/{first_crash.name}"
                    try:
                        content = first_crash.read_text(encoding="utf-8", errors="replace")
                        analyzer = PatternCrashAnalyzer()
                        analysis = analyzer.analyze_crash_content(content)
                        blamed_mod = analysis.blamed_mod
                        failure_code = (
                            analysis.failure_code.value
                            if hasattr(analysis.failure_code, "value")
                            else str(analysis.failure_code)
                        )
                        crash_summary = analysis.summary
                        if not failure_reason:
                            blamed_str = blamed_mod or "Unknown mod"
                            failure_reason = (
                                f"Crash detected in test run. Blamed mod: {blamed_str} "
                                f"({failure_code})"
                            )
                    except Exception as crash_err:
                        logger.debug("Failed analyzing crash content: %s", crash_err)

            # 3. Structured Assertions & Evidence Bundle Schema (§e)
            evidence_bundle = {
                "test_id": spec.test_id,
                "server_id": spec.server_id,
                "commit_id": spec.commit.id,
                "runtime": {
                    "runtime_id": handle.runtime_id,
                    "container_name": handle.container_name,
                    "exit_code": inspect_exit_code,
                    "oom_killed": inspect_oom,
                    "duration_seconds": duration_s if passed else 0.0,
                },
                "assertions": {
                    "container_started": True,
                    "boot_gate_passed": boot_passed if "boot_passed" in locals() else False,
                    "bots_spawned_target": bot_cfg.bot_count,
                    "bots_spawned_actual": connected_bots,
                    "crash_reports_found": len(list(crash_dir.glob("crash-*.txt")))
                    if crash_dir.is_dir()
                    else 0,
                    "clean_shutdown": passed,
                    **(
                        {
                            "strategy_downgraded_from": strat.downgraded_from,
                            "downgrade_reason": strat.reason,
                        }
                        if strat.downgraded_from
                        else {}
                    ),
                    **(
                        {
                            "plugin_enabled": plugin_enabled,
                            "spawn_ok": spawn_ok,
                            "spawn_failed": spawn_failed,
                            "actions_ok": actions_ok,
                            "actions_failed": actions_failed,
                            "bot_names_prefix": bot_names_prefix,
                        }
                        if plugin_enabled is not None
                        else {}
                    ),
                },
                "crash_analysis": {
                    "blamed_mod": blamed_mod,
                    "failure_code": failure_code,
                    "summary": crash_summary or failure_reason,
                    "crash_report_path": crash_report_rel_path,
                },
                "log_tail": [line for line in logs[-100:] if line.strip()],
            }

            # Scrub secrets from failure_reason, logs, and evidence_bundle before persisting
            if failure_reason and rcon_password:
                failure_reason = failure_reason.replace(rcon_password, "***")
            if rcon_password:
                logs = [line.replace(rcon_password, "***") for line in logs]
                evidence_bundle["log_tail"] = [
                    line.replace(rcon_password, "***") for line in evidence_bundle["log_tail"]
                ]
                crash_sum = evidence_bundle.get("crash_analysis", {}).get("summary")
                if crash_sum:
                    evidence_bundle["crash_analysis"]["summary"] = crash_sum.replace(
                        rcon_password, "***"
                    )

            self._evidence_store[spec.test_id] = evidence_bundle
            handle.evidence_bundle = evidence_bundle

            # 4. Dispatch TestRunFailedEvent if failed (§d.3)
            if not passed and self._event_bus is not None:
                try:
                    from app.modules.versioning.domain.events import TestRunFailedEvent

                    await self._event_bus.publish(
                        TestRunFailedEvent(
                            server_id=spec.server_id,
                            test_id=spec.test_id,
                            commit_id=spec.commit.id,
                            failure_code=failure_code,
                            blamed_mod=blamed_mod,
                        )
                    )
                except Exception as eb_err:
                    logger.debug("Failed publishing TestRunFailedEvent: %s", eb_err)

            # 5. Update Runtime Entity (§b)
            if handle.runtime_id:
                try:
                    runtime = Runtime(
                        id=handle.runtime_id,
                        server_id=spec.server_id,
                        commit_id=spec.commit.id,
                        container_id=handle.container_name,
                        port=25565,
                        status=RuntimeStatus.TERMINATED if passed else RuntimeStatus.CRASHED,
                        exit_code=inspect_exit_code,
                        oom_killed=inspect_oom,
                    )
                    if not passed:
                        runtime.mark_crashed(exit_code=inspect_exit_code, oom_killed=inspect_oom)
                    else:
                        runtime.mark_terminated(exit_code=inspect_exit_code)
                    await self._persist_runtime(runtime)
                except Exception as rt_err:
                    logger.debug("Failed persisting final runtime state: %s", rt_err)

            handle.status = TestRunStatus.PASSED if passed else TestRunStatus.FAILED
            capped_log = cap_log_output("\n".join(logs))

            # 6. Persist Real Outcome to SQLite DB
            await self._persist_test_outcome(
                test_id=spec.test_id,
                passed=passed,
                failure_reason=failure_reason,
                log_output=capped_log,
                runtime_id=handle.runtime_id,
                evidence_bundle=evidence_bundle,
            )

            result = BotVerificationResult(
                passed=passed,
                connected_bots=connected_bots,
                total_bots=bot_cfg.bot_count,
                disconnects=0 if passed else 1,
                survived_duration_seconds=duration_s if passed else 0.0,
                failure_reason=failure_reason,
                logs=logs,
            )
            handle.set_result(result, evidence_bundle=evidence_bundle)
            self._active_runs.pop(spec.test_id, None)

            # 7. Cleanup & Retention (§f)
            try:
                await self.cleanup_test(handle, passed=passed)
            except Exception as cleanup_exc:
                logger.warning(
                    "Test container cleanup failed for %s: %s",
                    spec.test_id,
                    cleanup_exc,
                )

    async def _persist_test_outcome(
        self,
        test_id: str,
        passed: bool,
        failure_reason: str | None,
        log_output: str,
        runtime_id: str | None = None,
        evidence_bundle: dict[str, Any] | None = None,
    ) -> None:
        """Persists the terminal verification outcome to SQLite using busy-retry resilience."""
        from app.core.persistence.db import database
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        try:
            _ = database.session_factory
        except RuntimeError:
            logger.debug(
                "Database not initialized; skipping test outcome persistence for %s", test_id
            )
            return

        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with database.session_factory() as session:
                    repo = SQLVersioningRepository(session)
                    run = await repo.get_test_run(test_id)
                    if run:
                        if passed:
                            run.mark_passed(log_output=log_output)
                        else:
                            run.mark_failed(
                                reason=failure_reason or "Verification failed",
                                log_output=log_output,
                            )
                        if runtime_id is not None:
                            run.runtime_id = runtime_id
                        if evidence_bundle is not None:
                            run.evidence_bundle = evidence_bundle
                        await repo.save_test_run(run)
                        await session.commit()
                break
            except Exception as exc:
                is_lock = "locked" in str(exc).lower() or "busy" in str(exc).lower()
                if is_lock and attempt < max_retries - 1:
                    await asyncio.sleep(0.05 * (2**attempt))
                    continue
                logger.exception("Failed to persist test run outcome for %s: %s", test_id, exc)
                break

    async def cleanup_test(self, handle: TestHandle, passed: bool = True) -> None:
        """Removes test container, and test directory (unless failed and retention active)."""
        from app.core.config import AppSettings

        settings = AppSettings()
        retention_hours = getattr(settings, "test_artifact_retention_hours", 24)

        # 1. Unconditionally remove the container
        try:
            await asyncio.to_thread(
                subprocess.run,
                ["docker", "rm", "-f", handle.container_name],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except Exception as e:
            logger.debug("Failed to remove test container %s: %s", handle.container_name, e)

        # 2. Retain failed test directory for retention_hours if active
        if passed or retention_hours <= 0:
            try:
                if os.path.exists(handle.test_dir):
                    shutil.rmtree(handle.test_dir, ignore_errors=True)
                    if os.path.exists(handle.test_dir):
                        logger.warning(
                            "Test directory %s still exists after cleanup; "
                            "likely root-owned leftovers from a pre-parity run",
                            handle.test_dir,
                        )
            except Exception as e:
                logger.warning("Failed to remove test directory %s: %s", handle.test_dir, e)
        else:
            logger.info(
                "Retaining failed test directory %s for %sh debugging retention",
                handle.test_dir,
                retention_hours,
            )
