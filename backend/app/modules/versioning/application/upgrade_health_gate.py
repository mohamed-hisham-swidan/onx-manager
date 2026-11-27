"""Five-check race-free upgrade health gate (P5.5).

Checks executed within a single bounded wall-clock timeout:
1. ``startup_log`` — Container stdout readiness regex via ``strict_stdout_only=True``.
2. ``local_slp`` — Pure-Python Minecraft Server List Ping (SLP) probe on ``127.0.0.1:<game_port>``
   (or injected TCP probe for legacy unit tests).
3. ``rcon_flush`` — RCON ``save-all flush`` (skipped cleanly when RCON is disabled).
4. ``world_nbt`` — Pure-Python gzipped big-endian NBT ``level.dat`` integrity & version check
   (+ optional dimension smoke check).
5. ``network_reachability`` — Optional external tunnel/public IP SLP probe (non-destructive:
   warns without rollback when Checks 1-4 all passed).
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
from app.modules.versioning.infrastructure.mc_slp import (
    SlpProbeResult,
    probe_minecraft_slp,
    slp_version_matches_mc,
)
from app.modules.versioning.infrastructure.nbt_reader import (
    NbtParseError,
    known_data_version_for_mc,
    read_level_dat_version,
    verify_level_dat_target,
)

DEFAULT_HEALTH_GATE_BOOT_TIMEOUT_SECONDS = 300
MIN_HEALTH_GATE_BOOT_TIMEOUT_SECONDS = 300
MAX_HEALTH_GATE_BOOT_TIMEOUT_SECONDS = 900
LEVEL_DAT_MTIME_POLL_INTERVAL_SECONDS = 0.5
LEVEL_DAT_MTIME_MAX_WAIT_SECONDS = 15.0
RCON_COMMAND_TIMEOUT_SECONDS = 5.0
EXTERNAL_SLP_MAX_ATTEMPTS = 3
EXTERNAL_SLP_TIMEOUT_SECONDS = 5.0
EXTERNAL_SLP_BACKOFF_SECONDS = 2.0

STEP_1_STDOUT_DONE = "stdout_done_regex"
STEP_2_TCP_RCON_FLUSH = "tcp_and_rcon_flush"
STEP_3_NBT_DATA_VERSION = "nbt_data_version"
STEP_4_DIMENSION_SMOKE = "dimension_smoke"

CHECK_STARTUP_LOG = "startup_log"
CHECK_LOCAL_SLP = "local_slp"
CHECK_RCON_FLUSH = "rcon_flush"
CHECK_WORLD_NBT = "world_nbt"
CHECK_NETWORK_REACHABILITY = "network_reachability"


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
    """Outcome of the race-free upgrade health gate."""

    passed: bool
    failed_step: str | None = None
    reason: str | None = None
    data_version: int | None = None
    version_id: str | None = None
    elapsed_seconds: float = 0.0
    checks: tuple[dict[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()
    slp_version: str | None = None
    slp_latency_ms: int | None = None

    def to_health_gate_result(self) -> HealthGateResult:
        return HealthGateResult(
            passed=self.passed,
            failed_step=self.failed_step,
            reason=self.reason,
        )


def _initial_checks() -> list[dict[str, Any]]:
    return [
        {
            "id": CHECK_STARTUP_LOG,
            "label": "Container Boot & Ready Signal",
            "status": "pending",
            "detail": None,
        },
        {
            "id": CHECK_LOCAL_SLP,
            "label": "Local Server Ping (SLP)",
            "status": "pending",
            "detail": None,
        },
        {
            "id": CHECK_RCON_FLUSH,
            "label": "RCON World Flush",
            "status": "pending",
            "detail": None,
        },
        {
            "id": CHECK_WORLD_NBT,
            "label": "World Save Integrity (NBT)",
            "status": "pending",
            "detail": None,
        },
        {
            "id": CHECK_NETWORK_REACHABILITY,
            "label": "Public Network / Tunnel Probe",
            "status": "pending",
            "detail": None,
        },
    ]


class UpgradeHealthGateEvaluator:
    """Five-check race-free health gate bounded by a single overall timeout."""

    def __init__(
        self,
        *,
        container_started_at: datetime,
        server_root: Path | str,
        target_mc: str,
        get_stdout_since: Callable[[datetime], Awaitable[str | list[str]]],
        liveness_check: Callable[[], Awaitable[bool]],
        tcp_probe: Callable[[], Awaitable[bool]] | None = None,
        slp_probe: Callable[..., Awaitable[SlpProbeResult]] | None = None,
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
        external_target: tuple[str, int, str] | None = None,
        verify_public_network: bool | None = None,
        external_slp_probe: Callable[..., Awaitable[SlpProbeResult]] | None = None,
        external_backoff_seconds: float = EXTERNAL_SLP_BACKOFF_SECONDS,
        on_check: Callable[[list[dict[str, Any]], float], Awaitable[None] | None] | None = None,
        on_log: Callable[[str], Awaitable[None] | None] | None = None,
        refresh_state: Callable[[], Awaitable[dict[str, Any]] | dict[str, Any]] | None = None,
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
        self._use_slp = slp_probe is not None or tcp_probe is None
        self._slp_probe = slp_probe or probe_minecraft_slp
        self._tcp_probe = tcp_probe or self._default_tcp_probe
        self._rcon_client = rcon_client
        self._dimension_smoke_check = dimension_smoke_check
        self._world_name = world_name
        self._boot_timeout_seconds = float(boot_timeout_seconds)
        self._poll_interval = float(poll_interval_seconds)
        self._mtime_poll_interval = float(mtime_poll_interval_seconds)
        self._mtime_max_wait = float(mtime_max_wait_seconds)
        self._sleep = sleep
        self._external_target = external_target
        self._verify_public_network = verify_public_network
        self._external_slp_probe = external_slp_probe or probe_minecraft_slp
        self._external_backoff_seconds = float(external_backoff_seconds)
        self._on_check = on_check
        self._on_log = on_log
        self._refresh_state = refresh_state
        self.last_result: UpgradeHealthGateResult | None = None

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

    async def _emit_log(self, message: str) -> None:
        if self._on_log is None:
            return
        with contextlib.suppress(Exception):
            res = self._on_log(message)
            if inspect.isawaitable(res):
                await res

    async def _emit_checks(self, checks: list[dict[str, Any]], progress: float) -> None:
        if self._on_check is None:
            return
        snapshot = [dict(c) for c in checks]
        with contextlib.suppress(Exception):
            res = self._on_check(snapshot, progress)
            if inspect.isawaitable(res):
                await res

    async def _call_slp_probe(
        self,
        probe_fn: Callable[..., Awaitable[SlpProbeResult]],
        host: str,
        port: int,
        timeout_seconds: float,
    ) -> SlpProbeResult:
        try:
            return await probe_fn(host, port, timeout_seconds=timeout_seconds)
        except TypeError:
            return await probe_fn(host, port)

    async def evaluate(
        self,
        *,
        on_check: Callable[[list[dict[str, Any]], float], Awaitable[None] | None] | None = None,
    ) -> UpgradeHealthGateResult:
        """Execute Checks 1..5 within one non-retryable overarching deadline."""
        if on_check is not None:
            self._on_check = on_check

        # Lazy post-swap refresh so container_started_at & server.properties are always live.
        if self._refresh_state is not None:
            with contextlib.suppress(Exception):
                refreshed = self._refresh_state()
                if inspect.isawaitable(refreshed):
                    refreshed = await refreshed
                if isinstance(refreshed, dict):
                    if refreshed.get("container_started_at") is not None:
                        self._container_started_at = refreshed["container_started_at"]
                    if "rcon_client" in refreshed:
                        self._rcon_client = refreshed["rcon_client"]
                    if refreshed.get("host"):
                        self._host = str(refreshed["host"])
                    if refreshed.get("game_port") is not None:
                        self._game_port = int(refreshed["game_port"])
                    if refreshed.get("world_name"):
                        self._world_name = str(refreshed["world_name"])
                    if "external_target" in refreshed:
                        self._external_target = refreshed["external_target"]
                    if "verify_public_network" in refreshed:
                        self._verify_public_network = refreshed["verify_public_network"]

        loop = asyncio.get_running_loop()
        start_time = loop.time()
        current_step = STEP_1_STDOUT_DONE
        checks = _initial_checks()
        check_index = {c["id"]: idx for idx, c in enumerate(checks)}
        warnings: list[str] = []

        def _set_check(check_id: str, status: str, detail: str | None = None) -> None:
            idx = check_index[check_id]
            checks[idx]["status"] = status
            checks[idx]["detail"] = detail

        async def _run() -> UpgradeHealthGateResult:
            nonlocal current_step

            # Check 1: Container Boot & Ready Signal (strict stdout only)
            current_step = STEP_1_STDOUT_DONE
            _set_check(CHECK_STARTUP_LOG, "running", "Waiting for server ready signal...")
            await self._emit_checks(checks, 0.05)
            await self._emit_log(
                "Health Gate 1/5: Waiting for container boot & Done (...)! signal..."
            )

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
                reason = boot_res.failure_reason or "Stdout readiness regex did not match"
                _set_check(CHECK_STARTUP_LOG, "failed", reason)
                await self._emit_checks(checks, 0.1)
                await self._emit_log(f"Health Gate 1/5 failed: {reason}")
                return UpgradeHealthGateResult(
                    passed=False,
                    failed_step=STEP_1_STDOUT_DONE,
                    reason=reason,
                    elapsed_seconds=loop.time() - start_time,
                    checks=tuple(dict(c) for c in checks),
                )

            _set_check(
                CHECK_STARTUP_LOG,
                "passed",
                f"Done in {boot_res.elapsed_seconds:.1f}s",
            )
            await self._emit_checks(checks, 0.2)
            await self._emit_log(
                f"Health Gate 1/5 passed: Server booted in {boot_res.elapsed_seconds:.1f}s."
            )

            # Check 2: Local Server Ping (SLP) or injected TCP probe
            current_step = STEP_2_TCP_RCON_FLUSH
            _set_check(
                CHECK_LOCAL_SLP,
                "running",
                f"Probing {self._host}:{self._game_port}...",
            )
            await self._emit_checks(checks, 0.25)
            await self._emit_log(
                f"Health Gate 2/5: Probing local server on {self._host}:{self._game_port}..."
            )

            remaining_budget = max(0.05, self._boot_timeout_seconds - (loop.time() - start_time))
            probe_deadline = loop.time() + min(15.0, remaining_budget)
            slp_res: SlpProbeResult | None = None
            local_ok = False
            last_probe_error: str | None = None

            if self._use_slp:
                while True:
                    per_try_timeout = min(4.0, max(0.5, probe_deadline - loop.time()))
                    try:
                        slp_res = await self._call_slp_probe(
                            self._slp_probe,
                            self._host,
                            self._game_port,
                            per_try_timeout,
                        )
                        if slp_res.reachable:
                            local_ok = True
                            break
                        last_probe_error = slp_res.error
                    except Exception as exc:
                        last_probe_error = str(exc)
                    if loop.time() >= probe_deadline:
                        break
                    await self._sleep(self._poll_interval)
            else:
                while True:
                    try:
                        if await self._tcp_probe():
                            local_ok = True
                            break
                    except Exception as exc:
                        last_probe_error = str(exc)
                    if loop.time() >= probe_deadline:
                        break
                    await self._sleep(self._poll_interval)

            if not local_ok:
                reason = last_probe_error or "Game port TCP connectivity probe failed"
                _set_check(CHECK_LOCAL_SLP, "failed", reason)
                await self._emit_checks(checks, 0.3)
                await self._emit_log(f"Health Gate 2/5 failed: {reason}")
                return UpgradeHealthGateResult(
                    passed=False,
                    failed_step=STEP_2_TCP_RCON_FLUSH,
                    reason=reason,
                    elapsed_seconds=loop.time() - start_time,
                    checks=tuple(dict(c) for c in checks),
                )

            if slp_res is not None:
                ver_label = slp_res.version_name or self._target_mc
                rtt_part = f" · {slp_res.latency_ms}ms" if slp_res.latency_ms is not None else ""
                slp_detail = f"{ver_label}{rtt_part}"
            else:
                slp_detail = f"TCP {self._host}:{self._game_port} reachable"
            _set_check(CHECK_LOCAL_SLP, "passed", slp_detail)
            await self._emit_checks(checks, 0.4)
            await self._emit_log(f"Health Gate 2/5 passed: {slp_detail}.")

            # Check 3: RCON World Flush
            level_dat_path = self._server_root / self._world_name / "level.dat"
            cutoff_ts = self._container_started_at.timestamp()

            if self._rcon_client is None:
                _set_check(CHECK_RCON_FLUSH, "skipped", "RCON disabled in server.properties")
                await self._emit_checks(checks, 0.6)
                await self._emit_log(
                    "Health Gate 3/5 skipped: RCON disabled in server.properties."
                )
            else:
                _set_check(CHECK_RCON_FLUSH, "running", "Sending save-all flush via RCON...")
                await self._emit_checks(checks, 0.45)
                await self._emit_log("Health Gate 3/5: Flushing world state via RCON...")
                try:
                    resp = await asyncio.wait_for(
                        self._rcon_client.send_command("save-all flush"),
                        timeout=RCON_COMMAND_TIMEOUT_SECONDS,
                    )
                    if (
                        isinstance(resp, str)
                        and resp.strip().lower().startswith("unknown command")
                    ):
                        resp = await asyncio.wait_for(
                            self._rcon_client.send_command("save-all"),
                            timeout=RCON_COMMAND_TIMEOUT_SECONDS,
                        )
                except Exception as exc:
                    reason = f"RCON save-all flush failed: {exc}"
                    _set_check(CHECK_RCON_FLUSH, "failed", reason)
                    await self._emit_checks(checks, 0.5)
                    await self._emit_log(f"Health Gate 3/5 failed: {reason}")
                    return UpgradeHealthGateResult(
                        passed=False,
                        failed_step=STEP_2_TCP_RCON_FLUSH,
                        reason=reason,
                        elapsed_seconds=loop.time() - start_time,
                        checks=tuple(dict(c) for c in checks),
                        slp_version=slp_res.version_name if slp_res else None,
                        slp_latency_ms=slp_res.latency_ms if slp_res else None,
                    )
                finally:
                    with contextlib.suppress(Exception):
                        await self._rcon_client.close()

                if resp is None or (
                    isinstance(resp, str)
                    and resp.strip().lower().startswith(("unknown command", "error:", "failed"))
                ):
                    reason = f"RCON save-all flush returned error response: {resp!r}"
                    _set_check(CHECK_RCON_FLUSH, "failed", reason)
                    await self._emit_checks(checks, 0.5)
                    await self._emit_log(f"Health Gate 3/5 failed: {reason}")
                    return UpgradeHealthGateResult(
                        passed=False,
                        failed_step=STEP_2_TCP_RCON_FLUSH,
                        reason=reason,
                        elapsed_seconds=loop.time() - start_time,
                        checks=tuple(dict(c) for c in checks),
                        slp_version=slp_res.version_name if slp_res else None,
                        slp_latency_ms=slp_res.latency_ms if slp_res else None,
                    )

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
                    reason = "level.dat mtime was not updated after RCON save-all flush"
                    _set_check(CHECK_RCON_FLUSH, "failed", reason)
                    await self._emit_checks(checks, 0.55)
                    await self._emit_log(f"Health Gate 3/5 failed: {reason}")
                    return UpgradeHealthGateResult(
                        passed=False,
                        failed_step=STEP_2_TCP_RCON_FLUSH,
                        reason=reason,
                        elapsed_seconds=loop.time() - start_time,
                        checks=tuple(dict(c) for c in checks),
                        slp_version=slp_res.version_name if slp_res else None,
                        slp_latency_ms=slp_res.latency_ms if slp_res else None,
                    )

                _set_check(CHECK_RCON_FLUSH, "passed", "World flushed via RCON")
                await self._emit_checks(checks, 0.6)
                await self._emit_log("Health Gate 3/5 passed: World flushed via RCON.")

            # Check 4: World Save Integrity (NBT) + optional dimension smoke
            current_step = STEP_3_NBT_DATA_VERSION
            _set_check(CHECK_WORLD_NBT, "running", "Inspecting world/level.dat NBT...")
            await self._emit_checks(checks, 0.65)
            await self._emit_log("Health Gate 4/5: Verifying world/level.dat NBT integrity...")

            if self._rcon_client is None:
                wait_deadline = loop.time() + min(2.0, self._mtime_max_wait)
                while not level_dat_path.exists() and loop.time() < wait_deadline:
                    await self._sleep(self._mtime_poll_interval)

            try:
                parsed_info = read_level_dat_version(level_dat_path)
            except (ValidationError, NbtParseError, OSError) as exc:
                reason = str(exc)
                _set_check(CHECK_WORLD_NBT, "failed", reason)
                await self._emit_checks(checks, 0.7)
                await self._emit_log(f"Health Gate 4/5 failed: {reason}")
                return UpgradeHealthGateResult(
                    passed=False,
                    failed_step=STEP_3_NBT_DATA_VERSION,
                    reason=reason,
                    elapsed_seconds=loop.time() - start_time,
                    checks=tuple(dict(c) for c in checks),
                    slp_version=slp_res.version_name if slp_res else None,
                    slp_latency_ms=slp_res.latency_ms if slp_res else None,
                )

            nbt_detail: str
            try:
                info = verify_level_dat_target(
                    level_dat_path,
                    expected_min_data_version=self._expected_min_data_version,
                    target_mc=self._target_mc,
                )
                nbt_detail = (
                    f"DataVersion {info.data_version}"
                    if info.data_version is not None
                    else f"Version {info.version_name or info.version_id or self._target_mc}"
                )
            except (ValidationError, NbtParseError) as exc:
                # Without RCON flush, Purpur/Paper may not flush level.dat until its 5-min
                # autosave. If level.dat is valid non-corrupt NBT AND live SLP confirmed the
                # exact target MC version, accept without a false-positive rollback.
                if (
                    self._rcon_client is None
                    and slp_res is not None
                    and slp_res.reachable
                    and slp_version_matches_mc(slp_res.version_name, self._target_mc)
                ):
                    info = parsed_info
                    nbt_detail = (
                        f"Valid NBT; live SLP confirmed MC {self._target_mc} (autosave pending)"
                    )
                elif (
                    self._expected_min_data_version is None
                    and parsed_info.data_version is not None
                    and (
                        slp_res is None
                        or slp_version_matches_mc(slp_res.version_name, self._target_mc)
                    )
                ):
                    info = parsed_info
                    nbt_detail = f"Valid NBT (DataVersion {parsed_info.data_version})"
                else:
                    reason = str(exc)
                    if (
                        slp_res is not None
                        and slp_res.version_name
                        and not slp_version_matches_mc(slp_res.version_name, self._target_mc)
                    ):
                        reason = (
                            f"Live server reported '{slp_res.version_name}' instead of "
                            f"target MC {self._target_mc}; {reason}"
                        )
                    _set_check(CHECK_WORLD_NBT, "failed", reason)
                    await self._emit_checks(checks, 0.7)
                    await self._emit_log(f"Health Gate 4/5 failed: {reason}")
                    return UpgradeHealthGateResult(
                        passed=False,
                        failed_step=STEP_3_NBT_DATA_VERSION,
                        reason=reason,
                        elapsed_seconds=loop.time() - start_time,
                        checks=tuple(dict(c) for c in checks),
                        slp_version=slp_res.version_name if slp_res else None,
                        slp_latency_ms=slp_res.latency_ms if slp_res else None,
                    )

            # Optional dimension smoke check
            current_step = STEP_4_DIMENSION_SMOKE
            if self._dimension_smoke_check is not None:
                world_dir = self._server_root / self._world_name
                try:
                    smoke_res = self._dimension_smoke_check(world_dir)
                    if inspect.isawaitable(smoke_res):
                        smoke_res = await smoke_res
                except Exception as exc:
                    reason = f"Dimension smoke check failed: {exc}"
                    _set_check(CHECK_WORLD_NBT, "failed", reason)
                    await self._emit_checks(checks, 0.75)
                    await self._emit_log(f"Health Gate 4/5 failed: {reason}")
                    return UpgradeHealthGateResult(
                        passed=False,
                        failed_step=STEP_4_DIMENSION_SMOKE,
                        reason=reason,
                        elapsed_seconds=loop.time() - start_time,
                        checks=tuple(dict(c) for c in checks),
                        slp_version=slp_res.version_name if slp_res else None,
                        slp_latency_ms=slp_res.latency_ms if slp_res else None,
                    )
                if not smoke_res:
                    reason = "Dimension smoke check failed"
                    _set_check(CHECK_WORLD_NBT, "failed", reason)
                    await self._emit_checks(checks, 0.75)
                    await self._emit_log(f"Health Gate 4/5 failed: {reason}")
                    return UpgradeHealthGateResult(
                        passed=False,
                        failed_step=STEP_4_DIMENSION_SMOKE,
                        reason=reason,
                        elapsed_seconds=loop.time() - start_time,
                        checks=tuple(dict(c) for c in checks),
                        slp_version=slp_res.version_name if slp_res else None,
                        slp_latency_ms=slp_res.latency_ms if slp_res else None,
                    )

            _set_check(CHECK_WORLD_NBT, "passed", nbt_detail)
            await self._emit_checks(checks, 0.8)
            await self._emit_log(f"Health Gate 4/5 passed: {nbt_detail}.")

            # Check 5: Public Network / Tunnel Probe (non-destructive)
            if self._verify_public_network is False:
                _set_check(CHECK_NETWORK_REACHABILITY, "skipped", "Skipped by operator")
                await self._emit_checks(checks, 1.0)
                await self._emit_log("Health Gate 5/5 skipped by operator.")
            elif self._external_target is None:
                _set_check(
                    CHECK_NETWORK_REACHABILITY,
                    "skipped",
                    "Local only — no active public tunnel",
                )
                await self._emit_checks(checks, 1.0)
                await self._emit_log(
                    "Health Gate 5/5 skipped: Local only — no active public tunnel."
                )
            else:
                ext_host, ext_port, ext_provider = self._external_target
                _set_check(
                    CHECK_NETWORK_REACHABILITY,
                    "running",
                    f"Probing {ext_provider} ({ext_host}:{ext_port})...",
                )
                await self._emit_checks(checks, 0.85)
                await self._emit_log(
                    f"Health Gate 5/5: Probing public address via {ext_provider} "
                    f"({ext_host}:{ext_port})..."
                )
                ext_res: SlpProbeResult | None = None
                for attempt in range(EXTERNAL_SLP_MAX_ATTEMPTS):
                    rem = self._boot_timeout_seconds - (loop.time() - start_time)
                    if rem <= 0.2:
                        break
                    per_timeout = min(EXTERNAL_SLP_TIMEOUT_SECONDS, max(0.5, rem))
                    try:
                        ext_res = await self._call_slp_probe(
                            self._external_slp_probe,
                            ext_host,
                            ext_port,
                            per_timeout,
                        )
                    except Exception as exc:
                        ext_res = SlpProbeResult(reachable=False, error=str(exc))
                    if ext_res.reachable:
                        break
                    if attempt + 1 < EXTERNAL_SLP_MAX_ATTEMPTS:
                        backoff = min(
                            self._external_backoff_seconds,
                            max(0.0, self._boot_timeout_seconds - (loop.time() - start_time) - 0.5),
                        )
                        if backoff > 0:
                            await self._sleep(backoff)

                if ext_res is not None and ext_res.reachable:
                    ver_str = ext_res.version_name or self._target_mc
                    ms_str = f"{ext_res.latency_ms}ms" if ext_res.latency_ms is not None else "ok"
                    detail = (
                        f"Reachable via {ext_provider} ({ext_host}:{ext_port}) "
                        f"in {ms_str} · {ver_str}"
                    )
                    _set_check(CHECK_NETWORK_REACHABILITY, "passed", detail)
                    await self._emit_checks(checks, 1.0)
                    await self._emit_log(f"Health Gate 5/5 passed: {detail}.")
                else:
                    warn_detail = (
                        f"Local server {self._target_mc} is healthy, but public address "
                        f"{ext_host}:{ext_port} was unreachable after "
                        f"{EXTERNAL_SLP_MAX_ATTEMPTS} attempts"
                    )
                    warnings.append(warn_detail)
                    _set_check(CHECK_NETWORK_REACHABILITY, "warned", warn_detail)
                    await self._emit_checks(checks, 1.0)
                    await self._emit_log(f"Health Gate 5/5 warning: {warn_detail}")

            return UpgradeHealthGateResult(
                passed=True,
                data_version=info.data_version,
                version_id=info.version_id,
                elapsed_seconds=loop.time() - start_time,
                checks=tuple(dict(c) for c in checks),
                warnings=tuple(warnings),
                slp_version=slp_res.version_name if slp_res else None,
                slp_latency_ms=slp_res.latency_ms if slp_res else None,
            )

        try:
            res = await asyncio.wait_for(_run(), timeout=self._boot_timeout_seconds)
            self.last_result = res
            return res
        except TimeoutError:
            timeout_int = (
                int(self._boot_timeout_seconds)
                if self._boot_timeout_seconds.is_integer()
                else self._boot_timeout_seconds
            )
            reason = f"Health gate timed out after {timeout_int}s at {current_step}"
            for c in checks:
                if c["status"] == "running":
                    c["status"] = "failed"
                    c["detail"] = reason
            await self._emit_checks(checks, 1.0)
            await self._emit_log(f"Health Gate timed out: {reason}")
            res = UpgradeHealthGateResult(
                passed=False,
                failed_step=current_step,
                reason=reason,
                elapsed_seconds=loop.time() - start_time,
                checks=tuple(dict(c) for c in checks),
                warnings=tuple(warnings),
            )
            self.last_result = res
            return res


__all__ = [
    "CHECK_LOCAL_SLP",
    "CHECK_NETWORK_REACHABILITY",
    "CHECK_RCON_FLUSH",
    "CHECK_STARTUP_LOG",
    "CHECK_WORLD_NBT",
    "DEFAULT_HEALTH_GATE_BOOT_TIMEOUT_SECONDS",
    "EXTERNAL_SLP_BACKOFF_SECONDS",
    "EXTERNAL_SLP_MAX_ATTEMPTS",
    "EXTERNAL_SLP_TIMEOUT_SECONDS",
    "LEVEL_DAT_MTIME_MAX_WAIT_SECONDS",
    "LEVEL_DAT_MTIME_POLL_INTERVAL_SECONDS",
    "MAX_HEALTH_GATE_BOOT_TIMEOUT_SECONDS",
    "MIN_HEALTH_GATE_BOOT_TIMEOUT_SECONDS",
    "RCON_COMMAND_TIMEOUT_SECONDS",
    "STEP_1_STDOUT_DONE",
    "STEP_2_TCP_RCON_FLUSH",
    "STEP_3_NBT_DATA_VERSION",
    "STEP_4_DIMENSION_SMOKE",
    "UpgradeHealthGateEvaluator",
    "UpgradeHealthGateResult",
    "check_dimension_smoke_paths",
    "validate_health_gate_timeout",
]
