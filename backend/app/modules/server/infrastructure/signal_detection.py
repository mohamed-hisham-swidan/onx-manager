"""Shared signal detection layer for server boot readiness and test containers.

Pure DB-free functions and async polling loop unifying:
1. Log marker inspection (e.g. "Done (").
2. Container / process liveness probes.
3. Crash correlation and mod blaming via PatternCrashAnalyzer.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.modules.health.infrastructure.crash_analyzer import PatternCrashAnalyzer

logger = logging.getLogger(__name__)

DEFAULT_BOOT_MARKERS: tuple[str, ...] = ("Done (",)


@dataclass(frozen=True)
class BootSignalResult:
    """Result of boot signal polling."""

    passed: bool
    failure_reason: str | None = None
    blamed_mod: str | None = None
    elapsed_seconds: float = 0.0
    logs: list[str] = field(default_factory=list)


def check_log_markers(
    log_content: str | list[str],
    markers: tuple[str, ...] = DEFAULT_BOOT_MARKERS,
) -> bool:
    """Check whether any of the expected boot completion markers appear in log content."""
    if isinstance(log_content, list):
        for line in log_content:
            for marker in markers:
                if marker in line:
                    return True
        return False

    return any(marker in log_content for marker in markers)


def check_crash_reports(
    crash_dir: Path | str,
) -> tuple[bool, str | None, str | None]:
    """Check for crash reports in the specified directory.

    Returns:
        (has_crashed, failure_reason, blamed_mod)
    """
    path = Path(crash_dir)
    if not path.exists() or not path.is_dir():
        return False, None, None

    crash_files = sorted(path.glob("crash-*.txt"))
    if not crash_files:
        return False, None, None

    first_crash = crash_files[0]
    try:
        content = first_crash.read_text(encoding="utf-8", errors="replace")
        analyzer = PatternCrashAnalyzer()
        analysis = analyzer.analyze_crash_content(content)
        blamed = analysis.blamed_mod or "Unknown mod"
        failure_reason = (
            f"Server crashed during boot. Blamed mod: {blamed} "
            f"({analysis.failure_code.value})"
        )
        return True, failure_reason, analysis.blamed_mod
    except Exception:
        failure_reason = f"Server crashed during boot: {first_crash.name}"
        return True, failure_reason, None


async def check_container_liveness(container_name: str, timeout: float = 5.0) -> bool:
    """Check if a Docker container is running via `docker inspect`."""
    if not container_name:
        return False
    try:
        res = await asyncio.to_thread(
            subprocess.run,
            [
                "docker",
                "inspect",
                "-f",
                "{{.State.Running}}",
                container_name,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return res.returncode == 0 and "true" in res.stdout.lower()
    except Exception as exc:
        logger.debug("Failed container liveness check for %s: %s", container_name, exc)
        return False


async def check_pid_liveness(pid: int) -> bool:
    """Check if an OS process PID is alive."""
    if pid <= 0:
        return False
    try:
        import psutil

        return psutil.pid_exists(pid)
    except Exception:
        import os

        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


async def poll_boot_signals(
    timeout: float,
    poll_interval: float = 0.5,
    markers: tuple[str, ...] = DEFAULT_BOOT_MARKERS,
    container_name: str | None = None,
    liveness_check: Callable[[], Awaitable[bool]] | None = None,
    crash_dir: Path | str | None = None,
    log_path: Path | str | None = None,
    get_logs: Callable[[], Awaitable[str | list[str]]] | None = None,
    on_log: Callable[[str], None] | None = None,
) -> BootSignalResult:
    """Poll for server boot completion using the crash / liveness / marker signal triple.

    Exits early when:
    - Crash report detected -> returns passed=False with blamed mod / failure reason.
    - Container or process dies -> returns passed=False with unexpected termination reason.
    - Expected log marker (e.g. 'Done (') appears in logs -> returns passed=True.
    - Timeout expires -> returns passed=False with timeout reason.
    """
    recorded_logs: list[str] = []

    def _log(msg: str) -> None:
        recorded_logs.append(msg)
        if on_log:
            import contextlib

            with contextlib.suppress(Exception):
                on_log(msg)

    _log(
        f"[BOOT-GATE] Waiting up to {timeout:.0f}s for server boot "
        f"(polling for {markers})..."
    )

    loop = asyncio.get_event_loop()
    start_time = loop.time()

    while True:
        # 1. Crash correlation check
        if crash_dir is not None:
            crashed, failure_reason, blamed_mod = check_crash_reports(crash_dir)
            if crashed:
                _log(f"[BOOT-GATE] {failure_reason}")
                elapsed = loop.time() - start_time
                return BootSignalResult(
                    passed=False,
                    failure_reason=failure_reason,
                    blamed_mod=blamed_mod,
                    elapsed_seconds=elapsed,
                    logs=recorded_logs,
                )

        # 2. Liveness probe check
        is_alive = True
        if liveness_check is not None:
            try:
                is_alive = await liveness_check()
            except Exception:
                is_alive = False
        elif container_name:
            is_alive = await check_container_liveness(container_name)

        if not is_alive:
            fail_reason = (
                "Server process or container terminated unexpectedly before completing boot"
            )
            _log(f"[BOOT-GATE] {fail_reason}")
            elapsed = loop.time() - start_time
            return BootSignalResult(
                passed=False,
                failure_reason=fail_reason,
                elapsed_seconds=elapsed,
                logs=recorded_logs,
            )

        # 3. Log marker check
        # First check log_path if present on disk
        marker_found = False
        if log_path is not None:
            p = Path(log_path)
            if p.exists() and p.is_file():
                try:
                    content = p.read_text(encoding="utf-8", errors="replace")
                    if check_log_markers(content, markers):
                        marker_found = True
                except Exception as read_err:
                    logger.debug("Error reading log file %s: %s", log_path, read_err)

        # Fallback or additional check via get_logs callable
        if not marker_found and get_logs is not None:
            try:
                dynamic_logs = await get_logs()
                if check_log_markers(dynamic_logs, markers):
                    marker_found = True
            except Exception as get_err:
                logger.debug("Error retrieving dynamic logs: %s", get_err)

        if marker_found:
            _log("[BOOT-GATE] Server boot confirmed (expected marker found in logs).")
            elapsed = loop.time() - start_time
            return BootSignalResult(
                passed=True,
                elapsed_seconds=elapsed,
                logs=recorded_logs,
            )

        # 4. Timeout check
        elapsed = loop.time() - start_time
        if elapsed >= timeout:
            fail_reason = (
                f"Server did not complete boot within {timeout:.0f}s "
                f"(no {markers} found in logs)"
            )
            _log(f"[BOOT-GATE] Timeout: {fail_reason}")
            return BootSignalResult(
                passed=False,
                failure_reason=fail_reason,
                elapsed_seconds=elapsed,
                logs=recorded_logs,
            )

        await asyncio.sleep(poll_interval)
