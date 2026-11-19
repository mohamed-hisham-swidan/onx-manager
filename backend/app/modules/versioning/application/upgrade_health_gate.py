"""Four-step race-free upgrade health gate (P5.5).

Implements OD-v8.7-1:
1. Container stdout readiness regex via ``strict_stdout_only=True`` (no ``logs/latest.log``).
2. Game port TCP connect probe + RCON ``save-all flush`` + ``level.dat`` mtime check.
3. Pure-Python gzipped big-endian NBT ``DataVersion`` / ``Version.Id`` verification.
4. Optional dimension directory smoke check (``DIM-1``/``DIM1`` or ``dimensions/minecraft/*``).
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.exceptions import ValidationError
from app.modules.server.infrastructure.signal_detection import poll_boot_signals
from app.modules.versioning.application.refresh_orchestrator import HealthGateResult
from app.modules.versioning.infrastructure.nbt_reader import (
    NbtParseError,
    known_data_version_for_mc,
    verify_level_dat_target,
)

DEFAULT_HEALTH_GATE_BOOT_TIMEOUT_SECONDS = 300
MIN_HEALTH_GATE_BOOT_TIMEOUT_SECONDS = 300
MAX_HEALTH_GATE_BOOT_TIMEOUT_SECONDS = 900
LEVEL_DAT_MTIME_POLL_INTERVAL_SECONDS = 0.5
LEVEL_DAT_MTIME_MAX_WAIT_SECONDS = 15.0

STEP_1_STDOUT_DONE = "stdout_done_regex"
STEP_2_TCP_RCON_FLUSH = "tcp_and_rcon_flush"
STEP_3_NBT_DATA_VERSION = "nbt_data_version"
STEP_4_DIMENSION_SMOKE = "dimension_smoke"


def validate_health_gate_timeout(timeout_seconds: int) -> int:
    """Validate ``health_gate_boot_timeout_seconds`` is an integer in ``300..900``."""
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int):
        raise ValidationError(
            "health_gate_boot_timeout_seconds must be an integer",
            field="health_gate_boot_timeout_seconds",
        )
    if (
        timeout_seconds < MIN_HEALTH_GATE_BOOT_TIMEOUT_SECONDS
        or timeout_seconds > MAX_HEALTH_GATE_BOOT_TIMEOUT_SECONDS
    ):
        raise ValidationError(
            f"health_gate_boot_timeout_seconds must be between "
            f"{MIN_HEALTH_GATE_BOOT_TIMEOUT_SECONDS} and {MAX_HEALTH_GATE_BOOT_TIMEOUT_SECONDS}",
            field="health_gate_boot_timeout_seconds",
        )
    return timeout_seconds


def check_dimension_smoke_paths(world_dir: Path) -> bool:
    """Verify present Nether/End dimension directories are readable non-symlink dirs."""
    if not world_dir.is_dir() or world_dir.is_symlink():
        return False
    candidates = (
        world_dir / "DIM-1",
        world_dir / "DIM1",
        world_dir / "dimensions" / "minecraft" / "the_nether",
        world_dir / "dimensions" / "minecraft" / "the_end",
    )
    for path in candidates:
        if path.exists() and (path.is_symlink() or not path.is_dir()):
            return False
    return True


@dataclass(frozen=True)
class UpgradeHealthGateResult:
    """Outcome of the 4-step race-free upgrade health gate."""

    passed: bool
    failed_step: str | None = None
    reason: str | None = None
    data_version: int | None = None
    version_id: str | None = None
    elapsed_seconds: float = 0.0

    def to_health_gate_result(self) -> HealthGateResult:
        return HealthGateResult(
            passed=self.passed,
            failed_step=self.failed_step,
            reason=self.reason,
        )


class UpgradeHealthGateEvaluator:
    """Four-step race-free health gate bounded by a single overall timeout."""

    def __init__(
        self,
        *,
        container_started_at: datetime,
        server_root: Path | str,
        target_mc: str,
        get_stdout_since: Callable[[datetime], Awaitable[str | list[str]]],
        liveness_check: Callable[[], Awaitable[bool]],
        tcp_probe: Callable[[], Awaitable[bool]] | None = None,
        rcon_client: Any | None = None,
        expected_min_data_version: int | None = None,
        dimension_smoke_check: Callable[[Path], Awaitable[bool] | bool] | None = None,
        world_name: str = "world",
        host: str = "127.0.0.1",
        game_port: int = 25565,
        boot_timeout_seconds: int = DEFAULT_HEALTH_GATE_BOOT_TIMEOUT_SECONDS,
        poll_interval_seconds: float = 0.5,
        mtime_poll_interval_seconds: float = LEVEL_DAT_MTIME_POLL_INTERVAL_SECONDS,
        mtime_max_wait_seconds: float = LEVEL_DAT_MTIME_MAX_WAIT_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        _allow_test_timeout: bool = False,
    ) -> None:
        if _allow_test_timeout:
            if (
                isinstance(boot_timeout_seconds, bool)
                or not isinstance(boot_timeout_seconds, (int, float))
                or float(boot_timeout_seconds) <= 0
            ):
                raise ValidationError(
                    "boot_timeout_seconds must be positive",
                    field="health_gate_boot_timeout_seconds",
                )
        else:
            validate_health_gate_timeout(boot_timeout_seconds)

        self._container_started_at = container_started_at
        self._server_root = Path(server_root)
        self._target_mc = target_mc
        self._expected_min_data_version = (
            expected_min_data_version
            if expected_min_data_version is not None
            else known_data_version_for_mc(target_mc)
        )
        self._get_stdout_since = get_stdout_since
        self._liveness_check = liveness_check
        self._host = host
        self._game_port = game_port
        self._tcp_probe = tcp_probe or self._default_tcp_probe
        self._rcon_client = rcon_client
        self._dimension_smoke_check = dimension_smoke_check
        self._world_name = world_name
        self._boot_timeout_seconds = float(boot_timeout_seconds)
        self._poll_interval = float(poll_interval_seconds)
        self._mtime_poll_interval = float(mtime_poll_interval_seconds)
        self._mtime_max_wait = float(mtime_max_wait_seconds)
        self._sleep = sleep

    async def _default_tcp_probe(self) -> bool:
        try:
            reader, writer = await asyncio.open_connection(self._host, self._game_port)
        except OSError:
            return False
        del reader
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
        return True

    async def evaluate(self) -> UpgradeHealthGateResult:
        """Execute Steps 1..4 within one non-retryable overarching deadline."""
        loop = asyncio.get_running_loop()
        start_time = loop.time()
        current_step = STEP_1_STDOUT_DONE

        async def _run() -> UpgradeHealthGateResult:
            nonlocal current_step

            # Step 1: container stdout readiness regex (never reads logs/latest.log)
            current_step = STEP_1_STDOUT_DONE
            remaining = max(0.01, self._boot_timeout_seconds - (loop.time() - start_time))
            boot_res = await poll_boot_signals(
                timeout=remaining,
                poll_interval=self._poll_interval,
                container_name=None,
                liveness_check=self._liveness_check,
                crash_dir=self._server_root / "crash-reports",
                log_path=None,
                log_since=self._container_started_at,
                get_logs_since=self._get_stdout_since,
                use_strict_done_regex=True,
                strict_stdout_only=True,
            )
            if not boot_res.passed:
                return UpgradeHealthGateResult(
                    passed=False,
                    failed_step=STEP_1_STDOUT_DONE,
                    reason=boot_res.failure_reason or "Stdout readiness regex did not match",
                    elapsed_seconds=loop.time() - start_time,
                )

            # Step 2: game port TCP probe + RCON save-all flush + level.dat mtime
            current_step = STEP_2_TCP_RCON_FLUSH
            remaining_budget = max(0.05, self._boot_timeout_seconds - (loop.time() - start_time))
            tcp_deadline = loop.time() + min(15.0, remaining_budget)
            tcp_ok = False
            while True:
                try:
                    if await self._tcp_probe():
                        tcp_ok = True
                        break
                except Exception:
                    tcp_ok = False
                if loop.time() >= tcp_deadline:
                    break
                await self._sleep(self._poll_interval)
            if not tcp_ok:
                return UpgradeHealthGateResult(
                    passed=False,
                    failed_step=STEP_2_TCP_RCON_FLUSH,
                    reason="Game port TCP connectivity probe failed",
                    elapsed_seconds=loop.time() - start_time,
                )

            if self._rcon_client is not None:
                try:
                    resp = await self._rcon_client.send_command("save-all flush")
                except Exception as exc:
                    return UpgradeHealthGateResult(
                        passed=False,
                        failed_step=STEP_2_TCP_RCON_FLUSH,
                        reason=f"RCON save-all flush failed: {exc}",
                        elapsed_seconds=loop.time() - start_time,
                    )
                finally:
                    with contextlib.suppress(Exception):
                        await self._rcon_client.close()
                if resp is None or (
                    isinstance(resp, str)
                    and resp.strip().lower().startswith(("unknown command", "error:", "failed"))
                ):
                    return UpgradeHealthGateResult(
                        passed=False,
                        failed_step=STEP_2_TCP_RCON_FLUSH,
                        reason=f"RCON save-all flush returned error response: {resp!r}",
                        elapsed_seconds=loop.time() - start_time,
                    )

            level_dat_path = self._server_root / self._world_name / "level.dat"
            cutoff_ts = self._container_started_at.timestamp()
            mtime_deadline = loop.time() + self._mtime_max_wait
            mtime_ok = False
            while True:
                try:
                    st = os.stat(level_dat_path)
                    if st.st_mtime >= cutoff_ts:
                        mtime_ok = True
                        break
                except FileNotFoundError:
                    pass
                if loop.time() >= mtime_deadline:
                    break
                await self._sleep(self._mtime_poll_interval)

            if not mtime_ok:
                return UpgradeHealthGateResult(
                    passed=False,
                    failed_step=STEP_2_TCP_RCON_FLUSH,
                    reason="level.dat mtime was not updated after RCON save-all flush",
                    elapsed_seconds=loop.time() - start_time,
                )

            # Step 3: pure-Python NBT DataVersion / Version.Id verification
            current_step = STEP_3_NBT_DATA_VERSION
            try:
                info = verify_level_dat_target(
                    level_dat_path,
                    expected_min_data_version=self._expected_min_data_version,
                    target_mc=self._target_mc,
                )
            except (ValidationError, NbtParseError, OSError) as exc:
                return UpgradeHealthGateResult(
                    passed=False,
                    failed_step=STEP_3_NBT_DATA_VERSION,
                    reason=str(exc),
                    elapsed_seconds=loop.time() - start_time,
                )

            # Step 4: optional dimension smoke check
            current_step = STEP_4_DIMENSION_SMOKE
            if self._dimension_smoke_check is not None:
                world_dir = self._server_root / self._world_name
                try:
                    smoke_res = self._dimension_smoke_check(world_dir)
                    if inspect.isawaitable(smoke_res):
                        smoke_res = await smoke_res
                except Exception as exc:
                    return UpgradeHealthGateResult(
                        passed=False,
                        failed_step=STEP_4_DIMENSION_SMOKE,
                        reason=f"Dimension smoke check failed: {exc}",
                        elapsed_seconds=loop.time() - start_time,
                    )
                if not smoke_res:
                    return UpgradeHealthGateResult(
                        passed=False,
                        failed_step=STEP_4_DIMENSION_SMOKE,
                        reason="Dimension smoke check failed",
                        elapsed_seconds=loop.time() - start_time,
                    )

            return UpgradeHealthGateResult(
                passed=True,
                data_version=info.data_version,
                version_id=info.version_id,
                elapsed_seconds=loop.time() - start_time,
            )

        try:
            return await asyncio.wait_for(_run(), timeout=self._boot_timeout_seconds)
        except TimeoutError:
            timeout_int = (
                int(self._boot_timeout_seconds)
                if self._boot_timeout_seconds.is_integer()
                else self._boot_timeout_seconds
            )
            return UpgradeHealthGateResult(
                passed=False,
                failed_step=current_step,
                reason=f"Health gate timed out after {timeout_int}s at {current_step}",
                elapsed_seconds=loop.time() - start_time,
            )


__all__ = [
    "DEFAULT_HEALTH_GATE_BOOT_TIMEOUT_SECONDS",
    "LEVEL_DAT_MTIME_MAX_WAIT_SECONDS",
    "LEVEL_DAT_MTIME_POLL_INTERVAL_SECONDS",
    "MAX_HEALTH_GATE_BOOT_TIMEOUT_SECONDS",
    "MIN_HEALTH_GATE_BOOT_TIMEOUT_SECONDS",
    "STEP_1_STDOUT_DONE",
    "STEP_2_TCP_RCON_FLUSH",
    "STEP_3_NBT_DATA_VERSION",
    "STEP_4_DIMENSION_SMOKE",
    "UpgradeHealthGateEvaluator",
    "UpgradeHealthGateResult",
    "check_dimension_smoke_paths",
    "validate_health_gate_timeout",
]
