"""Comprehensive tests for pure-Python MC SLP, 5-check Health Gate, terminal sync & progress."""

from __future__ import annotations

import asyncio
import gzip
import json
import os
import struct
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1.schemas.operation import OperationDetailResponse, OperationStepResponse
from app.core.persistence.base import Base
from app.modules.operations.application.services.executor import OperationRecoveryReconciler
from app.modules.operations.domain.aggregate import Operation
from app.modules.operations.domain.enums import OperationStatus, StepStatus
from app.modules.operations.infrastructure.models import OperationModel, OperationStepModel
from app.modules.server.infrastructure.signal_detection import (
    matches_boot_done_regex,
    strip_ansi_codes,
)
from app.modules.versioning.application.modpack_upgrade_service import ModpackUpgradeService
from app.modules.versioning.application.upgrade_health_gate import (
    CHECK_LOCAL_SLP,
    CHECK_NETWORK_REACHABILITY,
    CHECK_RCON_FLUSH,
    CHECK_STARTUP_LOG,
    CHECK_WORLD_NBT,
    STEP_3_NBT_DATA_VERSION,
    UpgradeHealthGateEvaluator,
)
from app.modules.versioning.domain.lockfile import (
    EnvServer,
    LoaderRef,
    LockfileFile,
    LockfileV21,
    Origin,
)
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.btrfs_zfs_driver import BtrfsZfsSnapshotDriver
from app.modules.versioning.infrastructure.download_allowlist import VerifiedDownloadResult
from app.modules.versioning.infrastructure.mc_slp import (
    SlpProbeResult,
    _encode_varint,
    _pack_packet,
    _read_varint,
    probe_minecraft_slp,
    slp_version_matches_mc,
)
from app.modules.versioning.infrastructure.models import ServerUpgradeModel
from app.modules.versioning.infrastructure.upgrade_matrix import (
    CompatibilityMatrix,
    MatrixEntry,
    MatrixStatus,
)


def _build_level_dat_bytes(*, data_version: int, version_name: str) -> bytes:
    """Build a valid gzipped big-endian NBT level.dat payload."""
    buf = bytearray()

    def _w_str(s: str) -> None:
        raw = s.encode("utf-8")
        buf.extend(struct.pack(">H", len(raw)))
        buf.extend(raw)

    # Root TAG_Compound ""
    buf.append(10)
    _w_str("")
    # Child TAG_Compound "Data"
    buf.append(10)
    _w_str("Data")
    # TAG_Int "DataVersion"
    buf.append(3)
    _w_str("DataVersion")
    buf.extend(struct.pack(">i", data_version))
    # TAG_Compound "Version"
    buf.append(10)
    _w_str("Version")
    buf.append(8)
    _w_str("Name")
    _w_str(version_name)
    buf.append(3)
    _w_str("Id")
    buf.extend(struct.pack(">i", data_version))
    buf.append(0)  # End Version
    buf.append(0)  # End Data
    buf.append(0)  # End Root
    return gzip.compress(bytes(buf))


def _write_level_dat(server_root: Path, *, data_version: int, version_name: str) -> Path:
    world_dir = server_root / "world"
    world_dir.mkdir(parents=True, exist_ok=True)
    lvl = world_dir / "level.dat"
    lvl.write_bytes(_build_level_dat_bytes(data_version=data_version, version_name=version_name))
    return lvl


# ---------------------------------------------------------------------------
# 1. Pure-Python Minecraft SLP Helper Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mc_slp_status_and_ping_pong_roundtrip() -> None:
    status_payload = {
        "version": {"name": "Purpur 1.21.11", "protocol": 770},
        "players": {"max": 20, "online": 3},
        "description": {"text": "Welcome ", "extra": [{"text": "Home"}]},
    }

    async def _handle_client(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            # Read Handshake packet
            hs_len = await _read_varint(reader)
            assert hs_len > 0
            hs_id = await _read_varint(reader)
            assert hs_id == 0x00
            _proto = await _read_varint(reader)
            host_len = await _read_varint(reader)
            await reader.readexactly(host_len)
            await reader.readexactly(2)  # port
            next_state = await _read_varint(reader)
            assert next_state == 1

            # Read Status Request
            req_len = await _read_varint(reader)
            assert req_len == 1
            req_id = await _read_varint(reader)
            assert req_id == 0x00

            # Send Status Response
            encoded = json.dumps(status_payload).encode("utf-8")
            resp_body = _encode_varint(len(encoded)) + encoded
            writer.write(_pack_packet(0x00, resp_body))
            await writer.drain()

            # Read Ping (0x01) + 8 bytes and echo Pong (0x01)
            ping_len = await _read_varint(reader)
            assert ping_len == 9
            ping_id = await _read_varint(reader)
            assert ping_id == 0x01
            token_bytes = await reader.readexactly(8)
            writer.write(_pack_packet(0x01, token_bytes))
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(_handle_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        res = await probe_minecraft_slp("127.0.0.1", port, timeout_seconds=3.0)

    assert res.reachable is True
    assert res.version_name == "Purpur 1.21.11"
    assert res.protocol_version == 770
    assert res.players_online == 3
    assert res.players_max == 20
    assert res.motd == "Welcome Home"
    assert res.latency_ms is not None and res.latency_ms >= 0
    assert res.error is None


@pytest.mark.asyncio
async def test_mc_slp_bounded_timeout_on_hanging_socket() -> None:
    async def _hang_client(
        _reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            await asyncio.sleep(5.0)
        except asyncio.CancelledError:
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(_hang_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    t0 = time.monotonic()
    res = await probe_minecraft_slp("127.0.0.1", port, timeout_seconds=0.25)
    elapsed = time.monotonic() - t0
    server.close()

    assert res.reachable is False
    assert res.error is not None and "timed out" in res.error
    assert elapsed < 1.5


def test_slp_version_matches_mc_variants() -> None:
    assert slp_version_matches_mc("Purpur 1.21.11", "1.21.11") is True
    assert slp_version_matches_mc("Paper 1.21.11-R0.1", "1.21.11") is True
    assert slp_version_matches_mc("1.21.11", "1.21.11") is True
    assert slp_version_matches_mc("26.3", "26.3") is True
    assert slp_version_matches_mc("Purpur 1.21.4", "1.21.11") is False
    assert slp_version_matches_mc("Purpur 1.21.1", "1.21.11") is False
    assert slp_version_matches_mc(None, "1.21.11") is False


def test_signal_detection_strips_ansi_escape_codes() -> None:
    ansi_line = (
        "\x1b[32m[12:34:56 INFO]\x1b[0m: Done (14.221s)! For help, type \"help\""
    )
    assert strip_ansi_codes(ansi_line).startswith("[12:34:56 INFO]: Done")
    assert matches_boot_done_regex([ansi_line]) is True


# ---------------------------------------------------------------------------
# 2. Five-Check UpgradeHealthGateEvaluator Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_gate_lazy_refresh_and_no_false_rollback_when_rcon_disabled(
    tmp_path: Path,
) -> None:
    # Pre-upgrade level.dat (autosave hasn't flushed 4671 yet), RCON disabled
    _write_level_dat(tmp_path, data_version=4189, version_name="1.21.4")
    stale_started_at = datetime.now(UTC) - timedelta(minutes=5)
    seen_since: list[datetime] = []
    recorded_progress: list[tuple[list[dict[str, Any]], float]] = []

    async def _stdout_since(since: datetime) -> list[str]:
        seen_since.append(since)
        return ['\x1b[36m[12:00:01 INFO]\x1b[0m: Done (9.420s)! For help, type "help"']

    async def _refresh_state() -> dict[str, Any]:
        return {
            "container_started_at": datetime.now(UTC) - timedelta(seconds=1),
            "rcon_client": None,
        }

    async def _fake_slp(_host: str, _port: int, **_kw: Any) -> SlpProbeResult:
        return SlpProbeResult(reachable=True, latency_ms=4, version_name="Purpur 1.21.11")

    evaluator = UpgradeHealthGateEvaluator(
        container_started_at=stale_started_at,
        server_root=tmp_path,
        target_mc="1.21.11",
        get_stdout_since=_stdout_since,
        liveness_check=AsyncMock(return_value=True),
        slp_probe=_fake_slp,
        rcon_client=MagicMock(),  # should be replaced by None during refresh_state
        boot_timeout_seconds=10,
        poll_interval_seconds=0.05,
        mtime_max_wait_seconds=0.2,
        refresh_state=_refresh_state,
        on_check=lambda checks, prog: recorded_progress.append((checks, prog)),
        _allow_test_timeout=True,
    )

    res = await evaluator.evaluate()

    assert res.passed is True
    assert seen_since and seen_since[0] > stale_started_at + timedelta(minutes=4)
    check_map = {c["id"]: c for c in res.checks}
    assert check_map[CHECK_STARTUP_LOG]["status"] == "passed"
    assert check_map[CHECK_LOCAL_SLP]["status"] == "passed"
    assert "Purpur 1.21.11" in (check_map[CHECK_LOCAL_SLP]["detail"] or "")
    assert check_map[CHECK_RCON_FLUSH]["status"] == "skipped"
    assert check_map[CHECK_WORLD_NBT]["status"] == "passed"
    assert "autosave pending" in (check_map[CHECK_WORLD_NBT]["detail"] or "")
    assert check_map[CHECK_NETWORK_REACHABILITY]["status"] == "skipped"
    assert recorded_progress[-1][1] == 1.0


@pytest.mark.asyncio
async def test_health_gate_rejects_stale_slp_version_or_corrupt_level_dat(
    tmp_path: Path,
) -> None:
    _write_level_dat(tmp_path, data_version=4189, version_name="1.21.4")

    async def _stale_slp(_host: str, _port: int, **_kw: Any) -> SlpProbeResult:
        return SlpProbeResult(reachable=True, latency_ms=5, version_name="Purpur 1.21.4")

    evaluator = UpgradeHealthGateEvaluator(
        container_started_at=datetime.now(UTC) - timedelta(seconds=1),
        server_root=tmp_path,
        target_mc="1.21.11",
        get_stdout_since=AsyncMock(
            return_value=['[12:00:01 INFO]: Done (4.0s)! For help, type "help"']
        ),
        liveness_check=AsyncMock(return_value=True),
        slp_probe=_stale_slp,
        rcon_client=None,
        boot_timeout_seconds=10,
        poll_interval_seconds=0.05,
        mtime_max_wait_seconds=0.2,
        _allow_test_timeout=True,
    )
    res = await evaluator.evaluate()
    assert res.passed is False
    assert res.failed_step == STEP_3_NBT_DATA_VERSION

    # Corrupt level.dat must also always fail even if SLP reports 1.21.11
    (tmp_path / "world" / "level.dat").write_bytes(b"not-valid-nbt")
    evaluator_corrupt = UpgradeHealthGateEvaluator(
        container_started_at=datetime.now(UTC) - timedelta(seconds=1),
        server_root=tmp_path,
        target_mc="1.21.11",
        get_stdout_since=AsyncMock(
            return_value=['[12:00:01 INFO]: Done (4.0s)! For help, type "help"']
        ),
        liveness_check=AsyncMock(return_value=True),
        slp_probe=AsyncMock(
            return_value=SlpProbeResult(reachable=True, latency_ms=3, version_name="Purpur 1.21.11")
        ),
        rcon_client=None,
        boot_timeout_seconds=10,
        poll_interval_seconds=0.05,
        mtime_max_wait_seconds=0.2,
        _allow_test_timeout=True,
    )
    res_corrupt = await evaluator_corrupt.evaluate()
    assert res_corrupt.passed is False
    assert res_corrupt.failed_step == STEP_3_NBT_DATA_VERSION


@pytest.mark.asyncio
async def test_health_gate_rcon_auto_connect_and_flush(tmp_path: Path) -> None:
    lvl = _write_level_dat(tmp_path, data_version=4671, version_name="1.21.11")
    started = datetime.now(UTC) - timedelta(seconds=2)
    os.utime(lvl, (time.time(), time.time()))

    calls: list[str] = []

    class _AutoConnectRcon:
        def __init__(self) -> None:
            self.connected = False

        async def connect(self) -> None:
            self.connected = True
            calls.append("connect")

        async def send_command(self, cmd: str) -> str:
            if not self.connected:
                await self.connect()
            calls.append(f"cmd:{cmd}")
            return "Saved the game"

        async def close(self) -> None:
            calls.append("close")

    evaluator = UpgradeHealthGateEvaluator(
        container_started_at=started,
        server_root=tmp_path,
        target_mc="1.21.11",
        get_stdout_since=AsyncMock(
            return_value=['[12:00:01 INFO]: Done (4.0s)! For help, type "help"']
        ),
        liveness_check=AsyncMock(return_value=True),
        slp_probe=AsyncMock(
            return_value=SlpProbeResult(reachable=True, latency_ms=2, version_name="Purpur 1.21.11")
        ),
        rcon_client=_AutoConnectRcon(),
        boot_timeout_seconds=10,
        poll_interval_seconds=0.05,
        _allow_test_timeout=True,
    )
    res = await evaluator.evaluate()
    assert res.passed is True
    assert calls == ["connect", "cmd:save-all flush", "close"]
    assert {c["id"]: c["status"] for c in res.checks}[CHECK_RCON_FLUSH] == "passed"


@pytest.mark.asyncio
async def test_health_gate_check5_external_pass_and_non_destructive_warn(
    tmp_path: Path,
) -> None:
    _write_level_dat(tmp_path, data_version=4671, version_name="1.21.11")

    # Case A: External SLP passes
    eval_pass = UpgradeHealthGateEvaluator(
        container_started_at=datetime.now(UTC) - timedelta(seconds=1),
        server_root=tmp_path,
        target_mc="1.21.11",
        get_stdout_since=AsyncMock(
            return_value=['[12:00:01 INFO]: Done (3.0s)! For help, type "help"']
        ),
        liveness_check=AsyncMock(return_value=True),
        slp_probe=AsyncMock(
            return_value=SlpProbeResult(reachable=True, latency_ms=3, version_name="Purpur 1.21.11")
        ),
        external_target=("demo.joinmc.link", 25565, "playit"),
        verify_public_network=True,
        external_slp_probe=AsyncMock(
            return_value=SlpProbeResult(
                reachable=True, latency_ms=64, version_name="Purpur 1.21.11"
            )
        ),
        external_backoff_seconds=0.01,
        boot_timeout_seconds=10,
        poll_interval_seconds=0.05,
        _allow_test_timeout=True,
    )
    res_pass = await eval_pass.evaluate()
    assert res_pass.passed is True
    assert res_pass.warnings == ()
    chk5 = {c["id"]: c for c in res_pass.checks}[CHECK_NETWORK_REACHABILITY]
    assert chk5["status"] == "passed"
    assert "playit" in (chk5["detail"] or "")
    assert "64ms" in (chk5["detail"] or "")

    # Case B: External SLP times out -> warned + passed=True (NO rollback)
    eval_warn = UpgradeHealthGateEvaluator(
        container_started_at=datetime.now(UTC) - timedelta(seconds=1),
        server_root=tmp_path,
        target_mc="1.21.11",
        get_stdout_since=AsyncMock(
            return_value=['[12:00:01 INFO]: Done (3.0s)! For help, type "help"']
        ),
        liveness_check=AsyncMock(return_value=True),
        slp_probe=AsyncMock(
            return_value=SlpProbeResult(reachable=True, latency_ms=3, version_name="Purpur 1.21.11")
        ),
        external_target=("demo.joinmc.link", 25565, "playit"),
        verify_public_network=True,
        external_slp_probe=AsyncMock(
            return_value=SlpProbeResult(reachable=False, error="timed out")
        ),
        external_backoff_seconds=0.01,
        boot_timeout_seconds=10,
        poll_interval_seconds=0.05,
        _allow_test_timeout=True,
    )
    res_warn = await eval_warn.evaluate()
    assert res_warn.passed is True
    assert len(res_warn.warnings) == 1
    assert "demo.joinmc.link:25565" in res_warn.warnings[0]
    chk5_warn = {c["id"]: c for c in res_warn.checks}[CHECK_NETWORK_REACHABILITY]
    assert chk5_warn["status"] == "warned"


@pytest.mark.asyncio
async def test_health_gate_hard_timeout_aborts_hanging_probe(tmp_path: Path) -> None:
    async def _hanging_stdout(_since: datetime) -> list[str]:
        await asyncio.sleep(5.0)
        return []

    evaluator = UpgradeHealthGateEvaluator(
        container_started_at=datetime.now(UTC),
        server_root=tmp_path,
        target_mc="1.21.11",
        get_stdout_since=_hanging_stdout,
        liveness_check=AsyncMock(return_value=True),
        boot_timeout_seconds=0.2,
        poll_interval_seconds=0.05,
        _allow_test_timeout=True,
    )
    res = await evaluator.evaluate()
    assert res.passed is False
    assert "timed out" in (res.reason or "").lower()


# ---------------------------------------------------------------------------
# 3. Operation / Step / Upgrade Terminal Sync & Startup Reconciliation Tests
# ---------------------------------------------------------------------------


def test_operation_fail_and_timeout_close_in_progress_steps_and_freeze_elapsed() -> None:
    op = Operation.create(type="SERVER_UPGRADE", target_type="server", target_id="srv-1")
    op.add_step("PREPARE_AND_DOWNLOAD", sequence=1)
    op.add_step("HEALTH_GATE", sequence=2)
    t0 = datetime.now(UTC) - timedelta(seconds=120)
    op.prepare()
    op.start(at=t0)
    op.start_step("PREPARE_AND_DOWNLOAD", at=t0)
    op.complete_step("PREPARE_AND_DOWNLOAD", at=t0 + timedelta(seconds=10))
    op.start_step("HEALTH_GATE", at=t0 + timedelta(seconds=10))

    finish_at = t0 + timedelta(seconds=45)
    op.fail("UPGRADE_ROLLED_BACK", "Boot failed", failed_step_id="HEALTH_GATE", at=finish_at)

    hg = op.get_step("HEALTH_GATE")
    assert hg is not None
    assert hg.status == StepStatus.FAILED
    assert hg.completed_at == finish_at
    assert hg.elapsed_ms == 35_000

    # Even if a legacy step row was somehow still IN_PROGRESS on a terminal op,
    # OperationStepResponse.from_domain must freeze elapsed_ms instead of ticking live.
    hg.status = StepStatus.IN_PROGRESS
    hg.completed_at = None
    hg.elapsed_ms = 0
    resp = OperationDetailResponse.from_domain(op)
    hg_resp = next(s for s in resp.steps if s.step_id == "HEALTH_GATE")
    assert hg_resp.elapsed_ms == 35_000

    # Also verify direct OperationStepResponse with parent_terminal=True
    direct_resp = OperationStepResponse.from_domain(
        hg, parent_terminal=True, parent_finished_at=finish_at
    )
    assert direct_resp.elapsed_ms == 35_000

    # Verify time_out() closes IN_PROGRESS steps
    op2 = Operation.create(type="SERVER_UPGRADE", target_type="server", target_id="srv-1")
    op2.add_step("HEALTH_GATE", sequence=1)
    op2.prepare()
    op2.start(at=t0)
    op2.start_step("HEALTH_GATE", at=t0)
    op2.time_out(at=finish_at)
    hg2 = op2.get_step("HEALTH_GATE")
    assert hg2 is not None
    assert hg2.status == StepStatus.FAILED
    assert hg2.completed_at == finish_at


@pytest.mark.asyncio
async def test_startup_reconciler_closes_stranded_steps_and_applying_upgrades(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "reconcile.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    started = datetime.now(UTC) - timedelta(minutes=10)
    finished = started + timedelta(seconds=300)

    async with session_factory() as session:
        # Reproduce exact stranded state of 50a45deb + c0f738f1
        op_row = OperationModel(
            id="op-stranded-1",
            type="SERVER_UPGRADE",
            target_type="server",
            target_id="srv-5a206ead",
            status=OperationStatus.FAILED.value,
            current_step_id="HEALTH_GATE",
            failure_code="PROCESS_TERMINATED",
            error_message="Backend restarted",
            created_at=started,
            started_at=started,
            finished_at=finished,
        )
        step_row = OperationStepModel(
            id="step-stranded-hg",
            operation_id="op-stranded-1",
            step_id="HEALTH_GATE",
            sequence=4,
            status=StepStatus.IN_PROGRESS.value,
            elapsed_ms=0,
            started_at=started + timedelta(seconds=60),
            completed_at=None,
        )
        upg_row = ServerUpgradeModel(
            id="upg-stranded-1",
            server_id="srv-5a206ead",
            kind="server_upgrade",
            mode="simple",
            status="applying",
            source_mc="1.21.4",
            target_mc="1.21.11",
            target_loader_id="purpur",
            target_loader_version="latest",
            operation_id="op-stranded-1",
            pinned_until_confirm=False,
            health_gate_passed=False,
            created_at=started,
            updated_at=started,
        )
        session.add_all([op_row, step_row, upg_row])
        await session.commit()

    fake_db = MagicMock()
    fake_db.session_factory = session_factory

    with patch(
        "app.modules.operations.application.services.executor.database",
        fake_db,
    ):
        reconciler = OperationRecoveryReconciler(event_bus=None)
        await reconciler.reconcile_on_startup()

    async with session_factory() as session:
        healed_step = (
            await session.execute(
                select(OperationStepModel).where(OperationStepModel.id == "step-stranded-hg")
            )
        ).scalar_one()
        healed_upg = await session.get(ServerUpgradeModel, "upg-stranded-1")

    await engine.dispose()

    assert healed_step.status == StepStatus.FAILED.value
    assert healed_step.completed_at is not None
    assert healed_step.elapsed_ms == 240_000
    assert healed_upg is not None
    assert healed_upg.status == "failed"
    assert healed_upg.error_code == "PROCESS_TERMINATED"


# ---------------------------------------------------------------------------
# 4. Artifact Progress Telemetry & Reflink Fallback Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_cas_and_lec_emits_structured_artifact_progress(
    tmp_path: Path,
) -> None:
    from app.core.config import AppSettings
    from app.core.host_state import ensure_host_state_layout

    layout = ensure_host_state_layout(AppSettings(host_state_dir=str(tmp_path / "state")))
    cas = ArtifactCas(layout.cas)
    cached_digest = cas.put_bytes(b"cached-plugin-bytes")

    async def _fake_download(
        url: str,
        target_cas: ArtifactCas,
        *,
        on_progress: Any = None,
        **_kw: Any,
    ) -> VerifiedDownloadResult:
        if on_progress is not None:
            await on_progress(500, 1000)
        digest = target_cas.put_bytes(b"downloaded-plugin-bytes")
        return VerifiedDownloadResult(
            sha256=digest,
            sha512="0" * 128,
            sha1="0" * 40,
            size=23,
            final_url=url,
            redirect_count=0,
        )

    svc = ModpackUpgradeService(
        layout,
        session_factory=MagicMock(),
        cas=cas,
        download_to_cas=_fake_download,
    )
    current_lf = LockfileV21(
        format=2,
        mc="1.21.4",
        loader=LoaderRef(id="purpur", version="latest"),
        base_overrides={},
        files=(
            LockfileFile(
                path="plugins/Cached.jar",
                sha256=cached_digest,
                size=19,
                optional=False,
                env_server=EnvServer.REQUIRED,
                origin=Origin.MODRINTH,
            ),
        ),
    )
    matrix = CompatibilityMatrix(
        source_mc="1.21.4",
        target_mc="1.21.11",
        source_loader=LoaderRef(id="purpur", version="latest"),
        target_loader=LoaderRef(id="purpur", version="latest"),
        entries=(
            MatrixEntry(
                path="plugins/Cached.jar",
                status=MatrixStatus.UNCHANGED,
                origin="modrinth",
                source_sha256=cached_digest,
            ),
            MatrixEntry(
                path="plugins/Updated.jar",
                status=MatrixStatus.CARRIED,
                origin="modrinth",
                download_url="https://cdn.modrinth.com/data/abc/Updated-2.jar",
                target_filename="Updated-2.jar",
                target_size=1000,
            ),
        ),
    )

    snapshots: list[tuple[float, dict[str, Any]]] = []

    async def _on_progress(prog: float, ctx: dict[str, Any]) -> None:
        snapshots.append((prog, ctx))

    await svc._ensure_cas_and_lec(
        matrix,
        current_lockfile=current_lf,
        target_lec_key=None,
        extra_allowed_hosts=(),
        target_mc="1.21.11",
        target_loader=LoaderRef(id="purpur", version="latest"),
        on_progress=_on_progress,
    )

    assert len(snapshots) >= 3
    final_artifacts = {a["name"]: a for a in snapshots[-1][1]["artifacts"]}
    assert final_artifacts["Cached.jar"]["status"] == "cached"
    assert final_artifacts["Updated-2.jar"]["status"] == "ready"
    assert final_artifacts["Purpur 1.21.11"]["status"] == "ready"


def test_btrfs_driver_copy_fallback_succeeds_when_reflink_unsupported(
    tmp_path: Path,
) -> None:
    src = tmp_path / "srv"
    (src / "world").mkdir(parents=True)
    (src / "world" / "level.dat").write_bytes(b"hello-world")
    dst = tmp_path / "snap"

    fake_proc = MagicMock(returncode=1, stderr="cp: failed to clone: Operation not supported")
    with patch("subprocess.run", return_value=fake_proc):
        size = BtrfsZfsSnapshotDriver.create_snapshot(src, dst, allow_copy_fallback=True)

    assert size == len(b"hello-world")
    assert (dst / "world" / "level.dat").read_bytes() == b"hello-world"
