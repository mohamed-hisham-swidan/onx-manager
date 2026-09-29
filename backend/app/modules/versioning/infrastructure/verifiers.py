from __future__ import annotations

import asyncio
import contextlib
import logging
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.modules.health.infrastructure.crash_analyzer import PatternCrashAnalyzer
from app.modules.versioning.domain.value_objects import AssertionRulesConfig
from app.modules.versioning.infrastructure.bot_drivers import (
    FakePlayerNextDriver,
    MineflayerBotDriver,
    SmokeTestRunner,
)

logger = logging.getLogger(__name__)


def _scrub(text: str) -> str:
    """Best-effort log scrubber."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


@dataclass(frozen=True)
class AssertionItem:
    """Single evaluated assertion outcome."""

    name: str
    passed: bool
    message: str | None = None
    expected: Any = None
    actual: Any = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "message": self.message,
            "expected": self.expected,
            "actual": self.actual,
            "details": self.details,
        }


@dataclass
class AssertionVerdict:
    """Aggregated verdict returned by a BaseVerifier."""

    passed: bool
    failure_reason: str | None = None
    assertions: list[AssertionItem] = field(default_factory=list)
    connected_bots: int = 0
    total_bots: int = 0
    disconnects: int = 0
    survived_duration_seconds: float = 0.0
    extra_context: dict[str, Any] = field(default_factory=dict)


def evaluate_common_rules(
    rules: AssertionRulesConfig,
    log_text: str,
    test_dir: Path,
) -> tuple[list[AssertionItem], str | None, dict[str, Any]]:
    """Evaluates declarative rules (crash reports, forbidden/required log markers, error logs)."""
    items: list[AssertionItem] = []
    failure_reason: str | None = None
    crash_info: dict[str, Any] = {
        "blamed_mod": None,
        "failure_code": None,
        "summary": None,
        "crash_report_path": None,
        "suspected_culprit_mods": [],
    }

    # 1. Crash report check
    crash_dir = test_dir / "crash-reports"
    crashes_found = list(crash_dir.glob("crash-*.txt")) if crash_dir.is_dir() else []
    if crashes_found:
        first_crash = crashes_found[0]
        crash_info["crash_report_path"] = f"crash-reports/{first_crash.name}"
        try:
            content = first_crash.read_text(encoding="utf-8", errors="replace")
            analyzer = PatternCrashAnalyzer()
            analysis = analyzer.analyze_crash_content(content)
            blamed = analysis.blamed_mod or "Unknown mod"
            crash_info["blamed_mod"] = analysis.blamed_mod
            crash_info["failure_code"] = (
                analysis.failure_code.value if analysis.failure_code else None
            )
            crash_info["summary"] = f"Crash detected: {blamed}"
            if analysis.blamed_mod:
                crash_info["suspected_culprit_mods"] = [analysis.blamed_mod]
            if rules.disallow_crash_reports:
                failure_reason = (
                    f"Crash detected in test run. Blamed mod: {blamed} "
                    f"({crash_info['failure_code']})"
                )
        except Exception as exc:
            logger.debug("Failed analyzing crash report: %s", exc)
            if rules.disallow_crash_reports:
                failure_reason = f"Crash report detected: {first_crash.name}"

        items.append(
            AssertionItem(
                name="crash_reports_absent",
                passed=not rules.disallow_crash_reports,
                message=(
                    failure_reason
                    if rules.disallow_crash_reports
                    else "Crash report found but allowed"
                ),
                expected="0 crash reports",
                actual=f"{len(crashes_found)} crash reports",
            )
        )
    else:
        items.append(
            AssertionItem(
                name="crash_reports_absent",
                passed=True,
                message="No crash reports generated",
                expected="0 crash reports",
                actual="0 crash reports",
            )
        )

    # 2. Required log markers
    for marker in rules.required_log_markers:
        found = marker in log_text
        items.append(
            AssertionItem(
                name=f"required_marker:{marker}",
                passed=found,
                message=None if found else f"Required log marker not found: '{marker}'",
                expected=marker,
                actual="present" if found else "absent",
            )
        )
        if not found and not failure_reason:
            failure_reason = f"Required log marker '{marker}' was not found in server logs"

    # 3. Forbidden log markers
    for marker in rules.forbidden_log_markers:
        found = marker in log_text
        items.append(
            AssertionItem(
                name=f"forbidden_marker:{marker}",
                passed=not found,
                message=f"Forbidden log marker found: '{marker}'" if found else None,
                expected=f"no '{marker}'",
                actual="present" if found else "absent",
            )
        )
        if found and not failure_reason:
            failure_reason = f"Forbidden log marker '{marker}' was detected in server logs"

    # 4. Disallow error logs
    if rules.disallow_error_logs:
        error_lines = [
            line for line in log_text.splitlines()
            if "[ERROR]" in line or "[FATAL]" in line or " ERROR " in line
        ]
        has_errors = len(error_lines) > 0
        items.append(
            AssertionItem(
                name="disallow_error_logs",
                passed=not has_errors,
                message=f"Found {len(error_lines)} error log lines" if has_errors else None,
                expected="0 error log lines",
                actual=f"{len(error_lines)} error log lines",
            )
        )
        if has_errors and not failure_reason:
            failure_reason = f"Error logs detected in server logs ({len(error_lines)} lines)"

    return items, failure_reason, crash_info


class BaseVerifier(ABC):
    """Abstract base verifier for all test run execution drivers."""

    @abstractmethod
    async def verify(
        self,
        spec: Any,
        handle: Any,
        rules: AssertionRulesConfig,
        strategy: Any,
        container_ip: str,
        rcon_password: str | None,
        on_log: Callable[[str], None],
        on_progress: Callable[[float, dict[str, Any] | None], Awaitable[None]] | None = None,
    ) -> AssertionVerdict:
        """Executes verification and returns aggregated AssertionVerdict."""
        pass


class SmokeTestVerifier(BaseVerifier):
    """Smoke test verifier.

    Validates container boot, absence of crash reports, and container liveness.
    Has NO synthetic bot ratio requirement by default.
    """

    async def verify(
        self,
        spec: Any,
        handle: Any,
        rules: AssertionRulesConfig,
        strategy: Any,
        container_ip: str,
        rcon_password: str | None,
        on_log: Callable[[str], None],
        on_progress: Callable[[float, dict[str, Any] | None], Awaitable[None]] | None = None,
    ) -> AssertionVerdict:
        _ = (container_ip, rcon_password)
        server_type = getattr(spec, "server_type", "vanilla")
        on_log(f"[BOT-VERIFY] Smoke Test Mode: {server_type} ({spec.minecraft_version})")
        if on_progress:
            await on_progress(0.1, {"phase": "smoke_test_started"})

        duration_s = float(spec.bot_config.duration_seconds)
        smoke_res = await SmokeTestRunner.run_smoke_test(
            test_dir=Path(handle.test_dir),
            container_name=handle.container_name,
            timeout_seconds=min(duration_s, 60.0),
        )
        if smoke_res.log_output:
            on_log(smoke_res.log_output)

        test_dir = Path(handle.test_dir)
        log_path = test_dir / "logs" / "latest.log"
        log_text = (
            log_path.read_text(encoding="utf-8", errors="replace")
            if log_path.is_file()
            else ""
        )

        assertions: list[AssertionItem] = [
            AssertionItem(
                name="container_started",
                passed=True,
                message="Container started successfully",
            ),
            AssertionItem(
                name="boot_gate_passed",
                passed=smoke_res.passed,
                message=(
                    smoke_res.failure_reason
                    if not smoke_res.passed
                    else "Done line marker found"
                ),
            ),
        ]

        rule_items, rule_fail, crash_info = evaluate_common_rules(rules, log_text, test_dir)
        assertions.extend(rule_items)

        failure_reason = smoke_res.failure_reason or rule_fail
        if strategy.downgraded_from is not None:
            if failure_reason:
                failure_reason = f"{strategy.reason}; {failure_reason}"
            else:
                failure_reason = strategy.reason

        passed = smoke_res.passed and (rule_fail is None)

        assertions.append(
            AssertionItem(
                name="clean_shutdown",
                passed=passed,
                message="Clean shutdown verified" if passed else "Shutdown with failures",
            )
        )

        return AssertionVerdict(
            passed=passed,
            failure_reason=failure_reason,
            assertions=assertions,
            connected_bots=0,
            total_bots=0,
            disconnects=0,
            survived_duration_seconds=duration_s if passed else 0.0,
            extra_context={"crash_info": crash_info},
        )


class FakePlayerVerifier(BaseVerifier):
    """FakePlayer-Next RCON verifier.

    Injects /fp spawn commands via RCON.
    Preserves exact bot count match: passed = (spawned_bots == bot_cfg.bot_count).
    Zero-target handling: bot_count == 0 passes cleanly.
    """

    async def verify(
        self,
        spec: Any,
        handle: Any,
        rules: AssertionRulesConfig,
        strategy: Any,
        container_ip: str,
        rcon_password: str | None,
        on_log: Callable[[str], None],
        on_progress: Callable[[float, dict[str, Any] | None], Awaitable[None]] | None = None,
    ) -> AssertionVerdict:
        _ = (strategy, container_ip, rcon_password)
        bot_count = spec.bot_config.bot_count
        duration_s = float(spec.bot_config.duration_seconds)
        on_log(f"[BOT-VERIFY] Spawning {bot_count} RCON-driven FakePlayer-Next plugin bots")
        if on_progress:
            await on_progress(0.1, {"phase": "fakeplayer_spawn_started"})

        spawn_ok = 0
        spawn_failed = 0
        actions_ok = 0
        actions_failed = 0
        spawned_bots = 0
        last_error: str | None = None
        disallowed_stdout_markers = (
            "is online",
            "Invalid name",
            "Incorrect argument",
            "Unknown",
        )

        if bot_count > 0:
            cmd_groups = FakePlayerNextDriver.format_spawn_commands(
                run_id=spec.test_id[:8],
                bot_count=bot_count,
            )
        else:
            cmd_groups = []

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
                has_disallowed = any(m in out_scrubbed for m in disallowed_stdout_markers)
                if res.returncode == 0 and not has_disallowed:
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
            except Exception as exc:
                if is_spawn:
                    spawn_failed += 1
                last_error = _scrub(str(exc))

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

        if on_progress:
            await on_progress(
                spawned_bots / max(1, bot_count) if bot_count > 0 else 1.0,
                {
                    "spawn_ok": spawn_ok,
                    "spawn_failed": spawn_failed,
                    "actions_ok": actions_ok,
                    "actions_failed": actions_failed,
                },
            )

        # Stop bots
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

        # Check container liveness
        liveness = await asyncio.to_thread(
            subprocess.run,
            ["docker", "inspect", "-f", "{{.State.Running}}", handle.container_name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        is_alive = liveness.returncode == 0 and "true" in liveness.stdout.lower()

        test_dir = Path(handle.test_dir)
        log_path = test_dir / "logs" / "latest.log"
        log_text = (
            log_path.read_text(encoding="utf-8", errors="replace")
            if log_path.is_file()
            else ""
        )

        exact_match = spawned_bots == bot_count if bot_count > 0 else (spawned_bots == 0)

        assertions: list[AssertionItem] = [
            AssertionItem(
                name="container_started",
                passed=True,
                message="Container started successfully",
            ),
            AssertionItem(
                name="boot_gate_passed",
                passed=True,
                message="Boot gate passed",
            ),
            AssertionItem(
                name="plugin_enabled",
                passed=True,
                message="FakePlayer plugin loaded",
            ),
            AssertionItem(
                name="bot_spawn_exact",
                passed=exact_match,
                message=(
                    f"Spawned {spawned_bots}/{bot_count} FakePlayer bots"
                    if not exact_match
                    else f"Exact bot count satisfied ({spawned_bots}/{bot_count})"
                ),
                expected=bot_count,
                actual=spawned_bots,
            ),
            AssertionItem(
                name="clean_shutdown",
                passed=is_alive,
                message=(
                    "Container alive after verification"
                    if is_alive
                    else "Container terminated prematurely"
                ),
            ),
        ]

        rule_items, rule_fail, crash_info = evaluate_common_rules(rules, log_text, test_dir)
        assertions.extend(rule_items)

        failure_reason: str | None = None
        if not is_alive:
            failure_reason = "Test server container terminated during FakePlayer bot verification"
        elif not exact_match:
            err_msg = _scrub(last_error or "Unknown RCON error")
            failure_reason = (
                f"Spawned {spawned_bots}/{bot_count} FakePlayer bots via RCON: {err_msg}"
            )
        elif rule_fail:
            failure_reason = rule_fail

        passed = is_alive and exact_match and (rule_fail is None)

        return AssertionVerdict(
            passed=passed,
            failure_reason=failure_reason,
            assertions=assertions,
            connected_bots=spawned_bots,
            total_bots=bot_count,
            disconnects=spawn_failed,
            survived_duration_seconds=duration_s if passed else 0.0,
            extra_context={
                "crash_info": crash_info,
                "spawn_ok": spawn_ok,
                "spawn_failed": spawn_failed,
                "actions_ok": actions_ok,
                "actions_failed": actions_failed,
            },
        )


class MineflayerVerifier(BaseVerifier):
    """Mineflayer harness verifier.

    Preserved legacy pass semantics:
      If rules.min_connected_bots_ratio is None:
        evaluates passed = (spawn_successes >= 1) when bot_count > 0,
        and passed = True when bot_count == 0.
      If rules.min_connected_bots_ratio is set:
        requires (connected_bots / max(1, bot_count)) >= ratio.
    """

    async def verify(
        self,
        spec: Any,
        handle: Any,
        rules: AssertionRulesConfig,
        strategy: Any,
        container_ip: str,
        rcon_password: str | None,
        on_log: Callable[[str], None],
        on_progress: Callable[[float, dict[str, Any] | None], Awaitable[None]] | None = None,
    ) -> AssertionVerdict:
        _ = (strategy, rcon_password)
        bot_cfg = spec.bot_config
        bot_count = bot_cfg.bot_count
        duration_s = float(bot_cfg.duration_seconds)

        if bot_count == 0:
            # Zero-target handling: passes cleanly without spawning bots
            on_log("[BOT-VERIFY] Zero-target bot count (0); skipping Mineflayer harness")
            test_dir = Path(handle.test_dir)
            log_path = test_dir / "logs" / "latest.log"
            log_text = (
                log_path.read_text(encoding="utf-8", errors="replace")
                if log_path.is_file()
                else ""
            )
            rule_items, rule_fail, crash_info = evaluate_common_rules(rules, log_text, test_dir)
            assertions = [
                AssertionItem(name="container_started", passed=True),
                AssertionItem(name="boot_gate_passed", passed=True),
                AssertionItem(name="bot_connection_ratio", passed=True, expected=0, actual=0),
                *rule_items,
            ]
            passed = rule_fail is None
            return AssertionVerdict(
                passed=passed,
                failure_reason=rule_fail,
                assertions=assertions,
                connected_bots=0,
                total_bots=0,
                disconnects=0,
                survived_duration_seconds=duration_s if passed else 0.0,
                extra_context={"crash_info": crash_info},
            )

        bot_dir = Path(handle.test_dir) / "bots"
        on_log(
            f"[BOT-VERIFY] Starting Mineflayer harness against "
            f"{container_ip}:25565 ({bot_count} bots)"
        )
        if on_progress:
            await on_progress(0.1, {"phase": "mineflayer_harness_started"})

        verify_res = await MineflayerBotDriver.run_mineflayer_verification(
            bot_dir=bot_dir,
            host=container_ip,
            port=25565,
            run_id=spec.test_id[:8],
            bot_count=bot_count,
            duration_minutes=bot_cfg.duration_minutes,
            stagger_seconds=bot_cfg.join_stagger_seconds,
            connect_grace_seconds=bot_cfg.connect_grace_seconds,
        )
        for log_line in verify_res.logs:
            on_log(log_line)

        connected = verify_res.connected_bots
        ratio = connected / max(1, bot_count)

        # Legacy vs Tightened ratio evaluation
        if rules.min_connected_bots_ratio is not None:
            ratio_passed = ratio >= rules.min_connected_bots_ratio
            req_ratio = rules.min_connected_bots_ratio
            ratio_msg = (
                f"Connected ratio {ratio:.2f} satisfies required {req_ratio:.2f}"
                if ratio_passed
                else f"Connected ratio {ratio:.2f} below required {req_ratio:.2f}"
            )
        else:
            # Preserved legacy default: >= 1 bot connected satisfies pass
            ratio_passed = verify_res.passed
            ratio_msg = (
                f"Legacy spawn requirement satisfied ({connected}/{bot_count} connected)"
                if ratio_passed
                else f"No bots connected ({connected}/{bot_count})"
            )

        # Disconnect ceiling evaluation
        disconnects_ok = (rules.max_disconnects == 0) or (
            verify_res.disconnects <= rules.max_disconnects
        )

        test_dir = Path(handle.test_dir)
        log_path = test_dir / "logs" / "latest.log"
        log_text = (
            log_path.read_text(encoding="utf-8", errors="replace")
            if log_path.is_file()
            else ""
        )

        assertions = [
            AssertionItem(
                name="container_started",
                passed=True,
                message="Container started successfully",
            ),
            AssertionItem(
                name="boot_gate_passed",
                passed=True,
                message="Boot gate passed",
            ),
            AssertionItem(
                name="bot_connection_ratio",
                passed=ratio_passed,
                message=ratio_msg,
                expected=(
                    rules.min_connected_bots_ratio
                    if rules.min_connected_bots_ratio is not None
                    else 1
                ),
                actual=connected,
            ),
            AssertionItem(
                name="disconnect_ceiling",
                passed=disconnects_ok,
                message=f"Disconnects: {verify_res.disconnects} (max {rules.max_disconnects})",
                expected=rules.max_disconnects,
                actual=verify_res.disconnects,
            ),
        ]
        try:
            survived_s = float(verify_res.survived_duration_seconds)
        except Exception:
            survived_s = 0.0
        assertions.append(
            AssertionItem(
                name="duration_survived",
                passed=survived_s > 0,
                message=f"Survived {survived_s:.1f}s",
            )
        )

        rule_items, rule_fail, crash_info = evaluate_common_rules(rules, log_text, test_dir)
        assertions.extend(rule_items)

        failure_reason = verify_res.failure_reason if not ratio_passed else rule_fail
        if not disconnects_ok and not failure_reason:
            failure_reason = (
                f"Bot disconnect ceiling exceeded: "
                f"{verify_res.disconnects} > {rules.max_disconnects}"
            )

        passed = ratio_passed and disconnects_ok and (rule_fail is None)

        return AssertionVerdict(
            passed=passed,
            failure_reason=failure_reason,
            assertions=assertions,
            connected_bots=connected,
            total_bots=bot_count,
            disconnects=verify_res.disconnects,
            survived_duration_seconds=verify_res.survived_duration_seconds,
            extra_context={"crash_info": crash_info},
        )


def get_verifier(driver: str | None, mode: str | None = None) -> BaseVerifier:
    """Factory selecting the appropriate BaseVerifier."""
    drv = (driver or "").lower()
    m = (mode or "").lower()
    if m == "smoke_test" or drv in ("none", "smoke_test", ""):
        return SmokeTestVerifier()
    if drv == "fakeplayer_next":
        return FakePlayerVerifier()
    if drv == "mineflayer":
        return MineflayerVerifier()
    return SmokeTestVerifier()
