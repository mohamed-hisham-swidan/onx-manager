from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from app.modules.health.infrastructure.crash_analyzer import PatternCrashAnalyzer
from app.modules.server.infrastructure.providers.docker import (
    build_docker_server_cmd,
    resolve_docker_image,
    resolve_host_mount_path,
)
from app.modules.versioning.domain.deployment import TestServerDeployment
from app.modules.versioning.domain.entities import ServerCommit
from app.modules.versioning.domain.value_objects import (
    BotVerificationConfig,
    PlacementMode,
    TestRunStatus,
)
from app.modules.versioning.infrastructure.bot_drivers import (
    BotVerificationResult,
    FakePlayerNextDriver,
    MineflayerBotDriver,
    SmokeTestRunner,
    cap_log_output,
)
from app.modules.versioning.infrastructure.bot_pool import (
    PooledRunner,
    get_bot_runner_pool,
)
from app.modules.versioning.infrastructure.btrfs_zfs_driver import BtrfsZfsSnapshotDriver
from app.modules.versioning.infrastructure.compatibility import (
    VerificationMode,
    resolve_verification_strategy,
)
from app.modules.versioning.infrastructure.config_writer import write_test_server_properties
from app.modules.versioning.infrastructure.resource_probe import ResourcePreflightProbe
from app.modules.versioning.infrastructure.storage_probe import StorageCapabilityProbe

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
    _completion_future: asyncio.Future[BotVerificationResult] = field(
        default_factory=asyncio.Future
    )

    async def wait_for_completion(self) -> BotVerificationResult:
        return await self._completion_future

    def set_result(self, res: BotVerificationResult) -> None:
        if not self._completion_future.done():
            self._completion_future.set_result(res)


class TestExecutionRunner(ABC):
    """Abstract interface for test execution runners (Multi-node groundwork §3.7)."""

    @abstractmethod
    async def run_test(self, spec: TestSpec) -> TestHandle:
        pass

    @abstractmethod
    async def cleanup_test(self, handle: TestHandle) -> None:
        pass


class DockerTestExecutionRunner(TestExecutionRunner):
    """Docker-based isolated test container and bot verification runner.

    Enforces Design Spec §3.4, §3.5, §3.6, §3.7:
    - COW world clone via reflink block cloning.
    - Test server.properties written strictly via TestServerDeployment.
    - Isolated bridge network mode, unmapped ports.
    - Automated bot runtime sanity verification.
    """

    def __init__(self) -> None:
        self._active_runs: dict[str, TestHandle] = {}

    async def run_test(self, spec: TestSpec) -> TestHandle:
        # Stage D: concurrency is governed by the global admission gate
        # (RunIsolatedTestHandler → admit()), not by a per-server lock.
        # This runner is a plain executor: materialize → launch → verify.
        # 1. Check storage COW capability
        StorageCapabilityProbe.assert_supports_reflink(spec.server_dir)

        # 2. Check physical system headroom (second-line defense; admission
        # already earmarked headroom before this call)
        server_type = spec.commit.manifest.server_type
        ResourcePreflightProbe.assert_sufficient_resources(
            bot_count=spec.bot_config.bot_count,
            server_type=server_type,
        )

        # 3. Materialize test directory under .onx/tests/<test_id>
        test_root = Path(spec.server_dir) / ".onx" / "tests" / spec.test_id
        test_dir_str = str(test_root.resolve())
        test_root.mkdir(parents=True, exist_ok=True)

        # 4. COW world clone
        BtrfsZfsSnapshotDriver.clone_world(spec.server_dir, test_dir_str)

        # 5. Write manifest configs & mod jars into test directory
        manifest = spec.commit.manifest
        for rel_path, content in manifest.configs.items():
            if rel_path != "server.properties":  # server.properties written via test writer
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
                    # FOLLOW-UP (SPEC-2026-09-15-ISOLATED-TEST-BOOT-CONTRACT-01 §2.2):
                    # Now uses stage_file_reflink_or_copy which checks returncode.
                    # Previously: subprocess.run([...], check=False) + except Exception fallback
                    # did NOT catch a found-but-failing cp (e.g. MSYS2 without --reflink),
                    # silently leaving mod jars absent.  This call is now safe.
                    stage_file_reflink_or_copy(src_mod, dst_mod)

        # 5b. Stage server executable (jar or run.sh / user_jvm_args.txt)
        # SPEC-2026-09-15-ISOLATED-TEST-BOOT-CONTRACT-01 §2.2 — Executable Staging.
        staged_startup_jar: str | None = None
        server_startup_cmd: list[str] | None = None
        run_sh_src = Path(spec.server_dir) / "run.sh"
        if run_sh_src.is_file():
            run_sh_dst = test_root / "run.sh"
            stage_file_reflink_or_copy(run_sh_src, run_sh_dst)
            run_sh_dst.chmod(0o755)
            jvm_args_src = Path(spec.server_dir) / "user_jvm_args.txt"
            if jvm_args_src.is_file():
                stage_file_reflink_or_copy(jvm_args_src, test_root / "user_jvm_args.txt")
            # Explicit startup command — build_docker_server_cmd does no disk detection.
            server_startup_cmd = ["bash", "run.sh", "nogui"]
        else:
            # Resolve the startup jar to stage.
            # CommitManifest has no startup_jar field; always fall through to "server.jar"
            # default then glob. (getattr guard removed — was permanently dead code.)
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

        # 6. Safety-Critical: Write test server.properties via TestServerDeployment
        test_deployment = TestServerDeployment(test_id=spec.test_id, test_dir=test_dir_str)
        base_props = {}
        if "server.properties" in manifest.configs:
            for line in manifest.configs["server.properties"].splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    base_props[k.strip()] = v.strip()

        write_test_server_properties(
            deployment=test_deployment,
            base_properties=base_props,
            server_port=25565,
            bot_count=spec.bot_config.bot_count,
        )

        # 7. Resolve Docker image + build startup CMD and launch container
        image = resolve_docker_image(minecraft_version=spec.minecraft_version)
        container_name = f"onx-test-{spec.test_id}"
        host_mount = resolve_host_mount_path(test_dir_str)

        # Build server CMD — startup_command passed explicitly (no disk detection in helper).
        # SPEC-2026-09-15-ISOLATED-TEST-BOOT-CONTRACT-01 §2.1
        server_cmd = build_docker_server_cmd(
            startup_command=server_startup_cmd,
            startup_jar=staged_startup_jar,
            image=image,
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
                if hasattr(os, "getuid")
                and hasattr(os, "getgid")
                and sys.platform != "win32"
                else []
            ),
            "-e",
            "EULA=TRUE",
            "-e",
            "ONLINE_MODE=FALSE",
            image,
        ]
        docker_cmd.extend(server_cmd)

        res = await asyncio.to_thread(
            subprocess.run, docker_cmd, capture_output=True, text=True, timeout=30
        )
        if res.returncode != 0:
            raise RuntimeError(f"Failed to start isolated test container: {res.stderr.strip()}")

        handle = TestHandle(
            test_id=spec.test_id,
            server_id=spec.server_id,
            container_name=container_name,
            test_dir=test_dir_str,
            sidecar_runner=None,
            status=TestRunStatus.RUNNING,
        )
        self._active_runs[spec.test_id] = handle

        # Launch background verification execution (no lock is held: admission
        # owns concurrency policy; failures surface via handle + DB outcome).
        asyncio.create_task(self._execute_verification(spec, handle, test_deployment))
        return handle

    async def _execute_verification(
        self,
        spec: TestSpec,
        handle: TestHandle,
        test_deployment: TestServerDeployment,
    ) -> None:
        """Background execution of bot verification against the test container."""
        bot_cfg = spec.bot_config
        logs: list[str] = []
        failure_reason: str | None = None
        passed = False
        connected_bots = 0
        duration_s = bot_cfg.duration_minutes * 60.0

        sidecar: PooledRunner | None = None
        pool = get_bot_runner_pool()

        try:
            # 1. Resolve loader and version strategy
            server_type = spec.commit.manifest.server_type
            mode, driver, explanation = resolve_verification_strategy(
                server_type=server_type,
                minecraft_version=spec.minecraft_version,
                bot_tech=bot_cfg.bot_tech,
            )
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
                        boot_failure_reason = (
                            f"Server crashed during boot: {first_crash.name}"
                        )
                    logs.append(f"[BOOT-GATE] {boot_failure_reason}")
                    break

                # Check container liveness
                liveness_check = await asyncio.to_thread(
                    subprocess.run,
                    [
                        "docker", "inspect", "-f", "{{.State.Running}}",
                        handle.container_name,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                is_alive = (
                    liveness_check.returncode == 0
                    and "true" in liveness_check.stdout.lower()
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
                    if smoke_res.log_output:
                        logs.append(smoke_res.log_output)

                elif driver == "fakeplayer_next":
                    logs.append(
                        f"[BOT-VERIFY] Spawning {bot_cfg.bot_count} fakeplayer-next bots in-process"
                    )
                    FakePlayerNextDriver.install_plugin_into_test_directory(test_deployment)

                    # Execute /fp spawn commands via docker exec or RCON
                    spawn_cmds = FakePlayerNextDriver.format_spawn_commands(
                        run_id=spec.test_id[:8],
                        bot_count=bot_cfg.bot_count,
                    )
                    for scmd in spawn_cmds:
                        try:
                            await asyncio.to_thread(
                                subprocess.run,
                                ["docker", "exec", handle.container_name, "rcon-cli", scmd],
                                capture_output=True,
                                text=True,
                                timeout=5,
                            )
                        except Exception as e:
                            logger.debug("Failed injecting fakeplayer command: %s", e)

                    await asyncio.sleep(min(duration_s, 1.0))
                    passed = True
                    connected_bots = bot_cfg.bot_count

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

            handle.status = TestRunStatus.PASSED if passed else TestRunStatus.FAILED
            capped_log = cap_log_output("\n".join(logs))

            # Persist real outcome to SQLite DB
            await self._persist_test_outcome(
                test_id=spec.test_id,
                passed=passed,
                failure_reason=failure_reason,
                log_output=capped_log,
            )

            result = BotVerificationResult(
                passed=passed,
                connected_bots=connected_bots if passed else 0,
                total_bots=bot_cfg.bot_count,
                disconnects=0 if passed else 1,
                survived_duration_seconds=duration_s if passed else 0.0,
                failure_reason=failure_reason,
                logs=logs,
            )
            handle.set_result(result)
            self._active_runs.pop(spec.test_id, None)
            # Must-Fix 6A: remove the test container on EVERY exit path
            # (success, timeout, exception, cancellation). Previously the
            # container leaked (e.g. still Up 8h after a crashed run).
            try:
                await self.cleanup_test(handle)
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

    async def cleanup_test(self, handle: TestHandle) -> None:
        """Removes test container and test directory."""
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

        try:
            if os.path.exists(handle.test_dir):
                shutil.rmtree(handle.test_dir, ignore_errors=True)
                if os.path.exists(handle.test_dir):
                    # Stale root-owned leftovers (pre---user-parity runs) are not
                    # removable by the host user — warn loudly instead of swallowing.
                    logger.warning(
                        "Test directory %s still exists after cleanup; "
                        "likely root-owned leftovers from a pre-parity run",
                        handle.test_dir,
                    )
        except Exception as e:
            logger.warning("Failed to remove test directory %s: %s", handle.test_dir, e)
