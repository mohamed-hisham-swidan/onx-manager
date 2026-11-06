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
from app.modules.versioning.domain.paths import resolve_test_dir
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
    PluginCheck,
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
    boot_timeout_seconds: int | float | None = None
    operation_id: str | None = None
    timeout_seconds: int | float | None = None


@dataclass
class TestHandle:
    __test__ = False

    test_id: str
    server_id: str
    container_name: str
    test_dir: str
    sidecar_runner: PooledRunner | None
    status: TestRunStatus
    server_dir: str = ""
    runtime_id: str | None = None
    evidence_bundle: dict[str, Any] | None = None
    operation_id: str | None = None
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
    async def cleanup_test(
        self,
        handle: TestHandle,
        *,
        passed: bool,
        cancelled: bool = False,
    ) -> None:
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

    @classmethod
    def _build_evidence_bundle(
        cls,
        handle: Any,
        runtime_data: dict[str, Any],
        verdict: Any,
        log_tail: list[str],
    ) -> dict[str, Any]:
        crash_info = getattr(verdict, "extra_context", {}).get("crash_info", {})
        blamed_mod = crash_info.get("blamed_mod")
        suspected = crash_info.get("suspected_culprit_mods") or ([blamed_mod] if blamed_mod else [])
        boot_passed = any(
            getattr(a, "passed", False)
            for a in getattr(verdict, "assertions", [])
            if getattr(a, "name", "") in ("boot_gate_passed", "boot_passed")
        )
        return {
            "schema_version": "1.0",
            "test_id": getattr(handle, "test_id", None),
            "server_id": getattr(handle, "server_id", None),
            "commit_id": getattr(handle, "commit_id", None),
            "operation_id": getattr(handle, "operation_id", None),
            "runtime": runtime_data,
            "assertions": {
                "container_started": True,
                "boot_passed": boot_passed,
                "boot_gate_passed": boot_passed,
                "clean_shutdown": getattr(verdict, "passed", False),
                "items": [
                    a.to_dict() if hasattr(a, "to_dict") else a
                    for a in getattr(verdict, "assertions", [])
                ],
            },
            "crash_analysis": {
                "blamed_mod": blamed_mod,
                "suspected_culprit_mods": suspected,
                "summary": crash_info.get("summary") or getattr(verdict, "failure_reason", None),
            },
            "log_tail": [line for line in log_tail[-100:] if line.strip()],
        }

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

        if spec.operation_id:
            from app.modules.operations.application import get_operation_service

            await get_operation_service().fail_step(
                spec.operation_id,
                "MATERIALIZE_STAGING",
                safe_to_retry=True,
                error=failure_reason,
            )

        evidence_bundle = {
            "schema_version": "1.0",
            "test_id": spec.test_id,
            "server_id": spec.server_id,
            "commit_id": spec.commit.id,
            "operation_id": spec.operation_id,
            "runtime": {
                "runtime_id": None,
                "container_name": container_name,
                "exit_code": 1,
                "oom_killed": False,
                "duration_seconds": 0.0,
            },
            "assertions": {
                "container_started": False,
                "boot_passed": False,
                "boot_gate_passed": False,
                "bots_spawned_target": spec.bot_config.bot_count,
                "bots_spawned_actual": 0,
                "connected_bots": 0,
                "crash_reports_found": 0,
                "clean_shutdown": False,
                "items": [],
            },
            "crash_analysis": {
                "blamed_mod": None,
                "suspected_culprit_mods": [],
                "failure_code": None,
                "summary": failure_reason,
                "crash_report_path": None,
            },
            "log_tail": [line for line in logs[-100:] if line.strip()],
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
            operation_id=spec.operation_id,
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

        test_root = resolve_test_dir(spec.server_dir, spec.test_id)
        test_dir_str = str(test_root.resolve())
        if spec.operation_id:
            from app.modules.operations.application import get_operation_service

            await get_operation_service().start_step(spec.operation_id, "MATERIALIZE_STAGING")

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
            await self._report_progress(
                spec.operation_id,
                "MATERIALIZE_STAGING",
                0.2,
                context={"phase": "preflight_checks_passed"},
            )

            # 3. Materialize test directory under .onx/tests/<test_id> (Class B)
            with _class_b_step("test dir creation/materialization"):
                test_root.mkdir(parents=True, exist_ok=True)

            # 4. COW world clone (Class B)
            with _class_b_step("world clone"):
                BtrfsZfsSnapshotDriver.clone_world(spec.server_dir, test_dir_str)
            await self._report_progress(
                spec.operation_id,
                "MATERIALIZE_STAGING",
                0.5,
                context={"phase": "world_cloned"},
            )

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
            await self._report_progress(
                spec.operation_id,
                "MATERIALIZE_STAGING",
                0.7,
                context={"phase": "configs_staged"},
            )

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
                force_itzg_entrypoint=(server_startup_cmd is None),
            )

            if spec.operation_id:
                from app.modules.operations.application import get_operation_service

                await get_operation_service().complete_step(
                    spec.operation_id, "MATERIALIZE_STAGING"
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
            server_dir=spec.server_dir,
            sidecar_runner=None,
            status=TestRunStatus.BOOTING,
            runtime_id=runtime_id,
            operation_id=spec.operation_id,
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
        # The task is registered with the OperationExecutor (§4.4) so that a
        # user cancellation reaches the running verification instead of
        # marking the Operation CANCELLED while the container keeps running.
        verify_task = asyncio.create_task(
            self._execute_verification(
                spec,
                handle,
                test_deployment,
                strategy=strat,
                rcon_password=rcon_password,
            )
        )
        if spec.operation_id:
            from app.modules.operations.application import get_operation_service

            try:
                op_service = get_operation_service()
                op_service.executor.register_task(spec.operation_id, verify_task)
                try:
                    op = await op_service.get_operation(spec.operation_id)
                    op_service.executor.schedule_timeout_watch(
                        spec.operation_id, op.timeout_seconds
                    )
                except Exception as timeout_err:
                    logger.debug(
                        "Timeout watch not armed for operation %s: %s",
                        spec.operation_id,
                        timeout_err,
                    )
            except Exception as reg_err:
                logger.debug(
                    "Operation task registration failed for %s: %s",
                    spec.operation_id,
                    reg_err,
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
        cancel_finalize = False
        connected_bots = 0
        duration_s = float(bot_cfg.duration_seconds)
        plugin_enabled: bool | None = None
        spawn_ok = 0
        spawn_failed = 0
        actions_ok = 0
        actions_failed = 0
        bot_names_prefix: str | None = None
        verdict: Any | None = None

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
            # SPEC-2026-09-23-UNIFIED-STARTING-MONITOR-01 (two-tier timeout, floor 120s).
            from app.core.settings_store import get_live_settings
            from app.modules.server.infrastructure.signal_detection import poll_boot_signals

            live_settings = get_live_settings()
            default_test_boot = float(live_settings.test_boot_timeout_seconds)
            configured_timeout = (
                float(spec.boot_timeout_seconds)
                if spec.boot_timeout_seconds is not None
                else default_test_boot
            )
            boot_timeout = max(
                getattr(bot_cfg, "connect_grace_seconds", 60.0),
                configured_timeout,
            )

            if spec.operation_id:
                from app.modules.operations.application import get_operation_service

                await get_operation_service().start_step(spec.operation_id, "BOOTSTRAP_VERIFY")

            boot_res = await poll_boot_signals(
                timeout=boot_timeout,
                container_name=handle.container_name,
                crash_dir=Path(handle.test_dir) / "crash-reports",
                log_path=Path(handle.test_dir) / "logs" / "latest.log",
                on_log=logs.append,
            )

            boot_passed = boot_res.passed
            boot_failure_reason = boot_res.failure_reason

            if not boot_passed:
                passed = False
                failure_reason = boot_failure_reason
                if spec.operation_id:
                    from app.modules.operations.application import get_operation_service

                    await get_operation_service().fail_step(
                        spec.operation_id,
                        "BOOTSTRAP_VERIFY",
                        safe_to_retry=True,
                        error=boot_failure_reason,
                    )
                # Skip verification drivers — fall through to finally block.
            else:
                if spec.operation_id:
                    from app.modules.operations.application import get_operation_service

                    await get_operation_service().complete_step(
                        spec.operation_id, "BOOTSTRAP_VERIFY"
                    )
                handle.status = TestRunStatus.RUNNING
                await self._persist_test_status(spec.test_id, TestRunStatus.RUNNING)
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

                # 4. Delegate to appropriate BaseVerifier
                if spec.operation_id:
                    from app.modules.operations.application import get_operation_service

                    await get_operation_service().start_step(
                        spec.operation_id, "SYNTHETIC_PLAYER"
                    )

                if bot_cfg.placement_mode == PlacementMode.SIDECAR and strat.driver == "mineflayer":
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

                from app.modules.versioning.infrastructure.verifiers import get_verifier

                verifier = get_verifier(
                    driver=strat.driver,
                    mode=strat.mode.value if hasattr(strat.mode, "value") else str(strat.mode),
                )

                async def _progress_cb(p: float, ctx: dict[str, Any] | None) -> None:
                    await self._report_progress(
                        spec.operation_id, "SYNTHETIC_PLAYER", p, context=ctx
                    )

                verdict = await verifier.verify(
                    spec=spec,
                    handle=handle,
                    rules=bot_cfg.assertion_rules,
                    strategy=strat,
                    container_ip=container_ip,
                    rcon_password=rcon_password,
                    on_log=logs.append,
                    on_progress=_progress_cb,
                )
                passed = verdict.passed
                failure_reason = verdict.failure_reason
                connected_bots = verdict.connected_bots
                if "spawn_ok" in verdict.extra_context:
                    spawn_ok = verdict.extra_context["spawn_ok"]
                    spawn_failed = verdict.extra_context["spawn_failed"]
                    actions_ok = verdict.extra_context["actions_ok"]
                    actions_failed = verdict.extra_context["actions_failed"]

        except asyncio.CancelledError:
            # Cooperative cancellation (§5.4 / §7.1.3):
            # A user cancel arrives here with cancellation requested.
            # A timeout arrives here without user cancellation requested.
            passed = False
            cancel_finalize = False
            try:
                if await self._is_operation_cancellation_requested(spec.operation_id):
                    cancel_finalize = True
                    failure_reason = "Test run cancelled by user"
                else:
                    run_budget = spec.timeout_seconds or 600
                    failure_reason = (
                        f"TEST_TIMED_OUT: Test run timed out after {run_budget}s budget"
                    )
            except asyncio.CancelledError:
                pass
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
            assertion_items = [a.to_dict() for a in verdict.assertions] if verdict else []
            boot_passed_val = boot_passed if "boot_passed" in locals() else False
            is_timed_out = (not cancel_finalize) and (
                failure_reason is not None and "TEST_TIMED_OUT" in failure_reason
            )
            failure_code_val = "TEST_TIMED_OUT" if is_timed_out else failure_code

            evidence_bundle = {
                "schema_version": "1.0",
                "test_id": spec.test_id,
                "server_id": spec.server_id,
                "commit_id": spec.commit.id,
                "operation_id": spec.operation_id,
                "runtime": {
                    "runtime_id": handle.runtime_id,
                    "container_name": handle.container_name,
                    "exit_code": inspect_exit_code,
                    "oom_killed": inspect_oom,
                    "duration_seconds": duration_s if passed else 0.0,
                },
                "assertions": {
                    "container_started": True,
                    "boot_passed": boot_passed_val,
                    "boot_gate_passed": boot_passed_val,
                    "bots_spawned_target": bot_cfg.bot_count,
                    "bots_spawned_actual": connected_bots,
                    "connected_bots": connected_bots,
                    "crash_reports_found": len(list(crash_dir.glob("crash-*.txt")))
                    if crash_dir.is_dir()
                    else 0,
                    "clean_shutdown": passed,
                    "strategy_driver": strat.driver,
                    "strategy_downgraded_from": strat.downgraded_from,
                    "items": assertion_items,
                    **(
                        {
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
                    "suspected_culprit_mods": [blamed_mod] if blamed_mod else [],
                    "failure_code": failure_code_val,
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
            # A cooperatively cancelled run is not a failure: no failure event.
            if not passed and not cancel_finalize and self._event_bus is not None:
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
            # A cancelled run is terminated by request, never crashed.
            runtime_terminal = passed or cancel_finalize
            if handle.runtime_id:
                try:
                    runtime = Runtime(
                        id=handle.runtime_id,
                        server_id=spec.server_id,
                        commit_id=spec.commit.id,
                        container_id=handle.container_name,
                        port=25565,
                        status=RuntimeStatus.TERMINATED
                        if runtime_terminal
                        else RuntimeStatus.CRASHED,
                        exit_code=inspect_exit_code,
                        oom_killed=inspect_oom,
                    )
                    if not runtime_terminal:
                        runtime.mark_crashed(exit_code=inspect_exit_code, oom_killed=inspect_oom)
                    else:
                        runtime.mark_terminated(exit_code=inspect_exit_code)
                    await self._persist_runtime(runtime)
                except Exception as rt_err:
                    logger.debug("Failed persisting final runtime state: %s", rt_err)

            handle.status = TestRunStatus.PASSED if passed else TestRunStatus.FAILED
            capped_log = cap_log_output("\n".join(logs))

            # 6. Persist Real Outcome to SQLite DB
            # A cooperatively cancelled run is recorded CANCELLED, never FAILED.
            if cancel_finalize:
                await self._persist_test_cancelled(
                    test_id=spec.test_id,
                    reason=failure_reason or "Test run cancelled by user",
                    log_output=capped_log,
                    runtime_id=handle.runtime_id,
                )
            else:
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

            if spec.operation_id and not cancel_finalize:
                from app.modules.operations.application import get_operation_service

                if passed:
                    await get_operation_service().complete_step(
                        spec.operation_id, "SYNTHETIC_PLAYER"
                    )
                else:
                    await get_operation_service().fail_step(
                        spec.operation_id,
                        "SYNTHETIC_PLAYER",
                        safe_to_retry=True,
                        error=failure_reason or "Verification failed",
                    )

            # 7. Cleanup & Retention (§f)
            # On cooperative cancel the CLEANUP step finalizes CANCELLED
            # (confirm_cancellation) instead of FAILED.
            try:
                await self.cleanup_test(handle, passed=passed, cancelled=cancel_finalize)
            except Exception as cleanup_exc:
                logger.warning(
                    "Test container cleanup failed for %s: %s",
                    spec.test_id,
                    cleanup_exc,
                )

    async def _report_progress(
        self,
        operation_id: str | None,
        step_id: str,
        progress: float | None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Best-effort OperationStep progress ping (Stage A §6.3).

        Progress reporting must never break verification: every failure
        (unknown operation, missing step, locked DB) is swallowed to debug.
        """
        if not operation_id:
            return
        try:
            from app.modules.operations.application import get_operation_service

            await get_operation_service().record_step_progress(
                operation_id, step_id, progress, context=context
            )
        except Exception as exc:
            logger.debug(
                "Progress ping failed for operation %s step %s: %s",
                operation_id,
                step_id,
                exc,
            )

    async def _is_operation_cancellation_requested(
        self, operation_id: str | None
    ) -> bool:
        """Best-effort read of the cooperative cancellation flag (§5.4)."""
        if not operation_id:
            return False
        try:
            from app.modules.operations.application import get_operation_service

            op = await get_operation_service().get_operation(operation_id)
            return bool(op.cancellation_requested)
        except Exception as exc:
            logger.debug(
                "Cancellation-flag read failed for operation %s: %s", operation_id, exc
            )
            return False

    async def _persist_test_status(self, test_id: str, status: TestRunStatus) -> None:
        """Persists intermediate test run status (e.g. RUNNING after BOOTING) with busy-retry."""
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
                    run = await repo.get_test_run(test_id)
                    if run and not run.is_terminal:
                        run.status = status
                        await repo.save_test_run(run)
                        await session.commit()
                break
            except Exception as exc:
                is_lock = "locked" in str(exc).lower() or "busy" in str(exc).lower()
                if is_lock and attempt < max_retries - 1:
                    await asyncio.sleep(0.05 * (2**attempt))
                    continue
                logger.debug("Failed updating intermediate test status for %s: %s", test_id, exc)
                break

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
        from sqlalchemy import update

        from app.core.persistence.db import database
        from app.modules.versioning.domain.entities import TestRunStatus
        from app.modules.versioning.infrastructure.models import ServerTestRunModel

        try:
            _ = database.session_factory
        except RuntimeError:
            logger.debug(
                "Database not initialized; skipping test outcome persistence for %s", test_id
            )
            return

        status = TestRunStatus.PASSED if passed else TestRunStatus.FAILED
        failure_text = None if passed else (failure_reason or "Verification failed")

        values_to_update: dict[str, Any] = {
            "status": status.value,
            "failure_reason": failure_text,
            "log_output": log_output,
        }
        if runtime_id is not None:
            values_to_update["runtime_id"] = runtime_id
        if evidence_bundle is not None:
            values_to_update["evidence_bundle"] = evidence_bundle

        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with database.session_factory() as session:
                    stmt = (
                        update(ServerTestRunModel)
                        .where(
                            ServerTestRunModel.id == test_id,
                            ServerTestRunModel.status.notin_([
                                TestRunStatus.PASSED.value,
                                TestRunStatus.FAILED.value,
                                TestRunStatus.CANCELLED.value,
                            ]),
                        )
                        .values(**values_to_update)
                    )
                    result = await session.execute(stmt)
                    if result.rowcount == 0:
                        logger.debug(
                            "Test run %s was already terminal in database; outcome update skipped",
                            test_id,
                        )
                    await session.commit()
                break
            except Exception as exc:
                is_lock = "locked" in str(exc).lower() or "busy" in str(exc).lower()
                if is_lock and attempt < max_retries - 1:
                    await asyncio.sleep(0.05 * (2**attempt))
                    continue
                logger.exception("Failed to persist test run outcome for %s: %s", test_id, exc)
                break

    async def _persist_test_cancelled(
        self,
        test_id: str,
        reason: str,
        log_output: str,
        runtime_id: str | None = None,
    ) -> None:
        """Persists a cooperatively cancelled run as CANCELLED (never FAILED)."""
        from sqlalchemy import update

        from app.core.persistence.db import database
        from app.modules.versioning.domain.entities import TestRunStatus
        from app.modules.versioning.infrastructure.models import ServerTestRunModel

        try:
            _ = database.session_factory
        except RuntimeError:
            logger.debug(
                "Database not initialized; skipping test cancel persistence for %s", test_id
            )
            return

        values_to_update: dict[str, Any] = {
            "status": TestRunStatus.CANCELLED.value,
            "failure_reason": reason,
            "log_output": log_output,
        }
        if runtime_id is not None:
            values_to_update["runtime_id"] = runtime_id

        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with database.session_factory() as session:
                    stmt = (
                        update(ServerTestRunModel)
                        .where(
                            ServerTestRunModel.id == test_id,
                            ServerTestRunModel.status.notin_([
                                TestRunStatus.PASSED.value,
                                TestRunStatus.FAILED.value,
                                TestRunStatus.CANCELLED.value,
                            ]),
                        )
                        .values(**values_to_update)
                    )
                    result = await session.execute(stmt)
                    if result.rowcount == 0:
                        logger.debug(
                            "Test run %s was already terminal in database; outcome update skipped",
                            test_id,
                        )
                    await session.commit()
                break
            except Exception as exc:
                is_lock = "locked" in str(exc).lower() or "busy" in str(exc).lower()
                if is_lock and attempt < max_retries - 1:
                    await asyncio.sleep(0.05 * (2**attempt))
                    continue
                logger.exception("Failed to persist test run cancel for %s: %s", test_id, exc)
                break

    async def cleanup_test(
        self,
        handle: TestHandle,
        *,
        passed: bool,
        cancelled: bool = False,
        server_dir: Path | str | None = None,
    ) -> None:
        """Removes test container, and test directory (unless failed and retention active).

        ``cancelled=True`` finalizes a cooperatively cancelled operation as
        CANCELLED (§5.4) instead of FAILED, after the container is removed.
        Terminal-state races (timeout/completion committed first) are left
        intact rather than overwritten.
        """
        from app.core.config import AppSettings
        from app.modules.operations.domain.exceptions import (
            InvalidStateTransitionError,
            OperationTerminalConflictError,
        )
        from app.modules.versioning.domain.cleanup import TestCleanupPlan
        from app.modules.versioning.infrastructure.cleanup import execute_cleanup_plan

        if handle.operation_id:
            try:
                from app.modules.operations.application import get_operation_service

                await get_operation_service().start_step(handle.operation_id, "CLEANUP")
            except (InvalidStateTransitionError, OperationTerminalConflictError) as term_err:
                logger.debug(
                    "CLEANUP step start skipped for operation %s: %s",
                    handle.operation_id,
                    term_err,
                )

        effective_server_dir = server_dir or getattr(handle, "server_dir", "")
        if not effective_server_dir:
            raise ValueError(
                f"Cannot cleanup test '{handle.test_id}': "
                "authoritative server_dir is required and was not provided"
            )

        settings = AppSettings()
        retention_hours = getattr(settings, "test_artifact_retention_hours", 24)

        plan = TestCleanupPlan.create(
            server_id=handle.server_id,
            test_id=handle.test_id,
            container_name=handle.container_name,
            test_dir=Path(handle.test_dir),
            server_dir=effective_server_dir,
            passed=passed,
            cancelled=cancelled,
            retention_hours=float(retention_hours),
        )
        await execute_cleanup_plan(plan)
        if not plan.purge_artifacts:
            logger.info(
                "Retaining failed test directory %s for %sh debugging retention",
                plan.test_dir,
                retention_hours,
            )

        if handle.operation_id:
            from app.modules.operations.application import get_operation_service

            op_service = get_operation_service()
            try:
                await op_service.complete_step(handle.operation_id, "CLEANUP")
                if cancelled:
                    await op_service.confirm_cancellation(handle.operation_id)
                elif passed:
                    await op_service.complete_operation(handle.operation_id)
                else:
                    await op_service.fail_operation(
                        handle.operation_id,
                        failure_code="TEST_FAILED",
                        error_message="Test run verification failed",
                    )
            except (InvalidStateTransitionError, OperationTerminalConflictError) as term_err:
                # Timeout, completion, or an earlier cancel already committed a
                # terminal state: first committed transition wins (§5.4).
                logger.debug(
                    "Operation %s already terminal at cleanup: %s",
                    handle.operation_id,
                    term_err,
                )
