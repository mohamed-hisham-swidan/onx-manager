"""P5.5-3 tests for pure-Python NBT reader, cross-loader regex, and 4-step Health Gate."""

from __future__ import annotations

import asyncio
import gzip
import os
import struct
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core.exceptions import ValidationError
from app.modules.server.infrastructure.signal_detection import (
    matches_boot_done_regex,
    poll_boot_signals,
)
from app.modules.versioning.application.upgrade_health_gate import (
    STEP_1_STDOUT_DONE,
    STEP_2_TCP_RCON_FLUSH,
    STEP_3_NBT_DATA_VERSION,
    STEP_4_DIMENSION_SMOKE,
    UpgradeHealthGateEvaluator,
    check_dimension_smoke_paths,
    validate_health_gate_timeout,
)
from app.modules.versioning.infrastructure.nbt_reader import (
    MAX_NBT_UNCOMPRESSED_BYTES,
    TAG_BYTE,
    TAG_BYTE_ARRAY,
    TAG_COMPOUND,
    TAG_DOUBLE,
    TAG_END,
    TAG_FLOAT,
    TAG_INT,
    TAG_INT_ARRAY,
    TAG_LIST,
    TAG_LONG,
    TAG_LONG_ARRAY,
    TAG_SHORT,
    TAG_STRING,
    NbtParseError,
    known_data_version_for_mc,
    parse_nbt_bytes,
    read_level_dat_version,
    verify_level_dat_target,
)


def _nbt_str(text: str) -> bytes:
    raw = text.encode("utf-8")
    return struct.pack(">H", len(raw)) + raw


def _nbt_tag(tag_id: int, name: str, payload: bytes) -> bytes:
    return struct.pack(">B", tag_id) + _nbt_str(name) + payload


def _build_full_level_dat_bytes(
    *,
    data_version: int = 3955,
    version_id: str = "1.21.1",
    version_name: str = "1.21.1",
    level_name: str = "world",
    compress: bool = True,
) -> bytes:
    version_compound = (
        _nbt_tag(TAG_STRING, "Id", _nbt_str(version_id))
        + _nbt_tag(TAG_STRING, "Name", _nbt_str(version_name))
        + _nbt_tag(TAG_BYTE, "Snapshot", struct.pack(">b", 0))
        + struct.pack(">B", TAG_END)
    )
    data_compound = (
        _nbt_tag(TAG_INT, "DataVersion", struct.pack(">i", data_version))
        + _nbt_tag(TAG_STRING, "LevelName", _nbt_str(level_name))
        + _nbt_tag(TAG_COMPOUND, "Version", version_compound)
        + _nbt_tag(TAG_BYTE, "byteVal", struct.pack(">b", -5))
        + _nbt_tag(TAG_SHORT, "shortVal", struct.pack(">h", 1234))
        + _nbt_tag(TAG_LONG, "longVal", struct.pack(">q", 9_999_999_999))
        + _nbt_tag(TAG_FLOAT, "floatVal", struct.pack(">f", 1.5))
        + _nbt_tag(TAG_DOUBLE, "doubleVal", struct.pack(">d", 3.25))
        + _nbt_tag(TAG_BYTE_ARRAY, "bytesVal", struct.pack(">i", 3) + b"\x01\x02\x03")
        + _nbt_tag(
            TAG_LIST,
            "listVal",
            struct.pack(">Bi", TAG_STRING, 2) + _nbt_str("a") + _nbt_str("b"),
        )
        + _nbt_tag(
            TAG_INT_ARRAY,
            "intsVal",
            struct.pack(">i2i", 2, 10, -20),
        )
        + _nbt_tag(
            TAG_LONG_ARRAY,
            "longsVal",
            struct.pack(">i2q", 2, 100, -200),
        )
        + struct.pack(">B", TAG_END)
    )
    root = _nbt_tag(
        TAG_COMPOUND,
        "",
        _nbt_tag(TAG_COMPOUND, "Data", data_compound) + struct.pack(">B", TAG_END),
    )
    return gzip.compress(root) if compress else root


def test_nbt_reader_parses_all_tag_types_and_rejects_corrupt(tmp_path: Path) -> None:
    gz_bytes = _build_full_level_dat_bytes(data_version=3955, version_id="1.21.1")
    parsed = parse_nbt_bytes(gz_bytes)
    data = parsed["Data"]
    assert data["DataVersion"] == 3955
    assert data["LevelName"] == "world"
    assert data["byteVal"] == -5
    assert data["shortVal"] == 1234
    assert data["longVal"] == 9_999_999_999
    assert data["floatVal"] == pytest.approx(1.5)
    assert data["doubleVal"] == pytest.approx(3.25)
    assert data["bytesVal"] == b"\x01\x02\x03"
    assert data["listVal"] == ["a", "b"]
    assert data["intsVal"] == [10, -20]
    assert data["longsVal"] == [100, -200]

    level_dat = tmp_path / "level.dat"
    level_dat.write_bytes(gz_bytes)
    info = read_level_dat_version(level_dat)
    assert info.data_version == 3955
    assert info.version_id == "1.21.1"
    assert info.version_name == "1.21.1"
    assert info.level_name == "world"

    assert known_data_version_for_mc("1.21.1") == 3955
    assert known_data_version_for_mc("26.1") == 4500
    assert known_data_version_for_mc("99.99") is None

    verified = verify_level_dat_target(
        level_dat, expected_min_data_version=3955, target_mc="1.21.1"
    )
    assert verified.data_version == 3955

    with pytest.raises(NbtParseError):
        verify_level_dat_target(level_dat, expected_min_data_version=4500, target_mc="26.1")

    # Truncated gzip / truncated NBT / wrong root tag / oversized uncompressed bomb
    with pytest.raises(NbtParseError):
        parse_nbt_bytes(b"")
    with pytest.raises(NbtParseError):
        parse_nbt_bytes(gz_bytes[:-5])
    with pytest.raises(NbtParseError):
        raw_int = struct.pack(">B", TAG_INT) + _nbt_str("x") + struct.pack(">i", 1)
        parse_nbt_bytes(gzip.compress(raw_int))
    with pytest.raises(NbtParseError):
        parse_nbt_bytes(b"\x0a" * (MAX_NBT_UNCOMPRESSED_BYTES + 1))

    # Gzip bomb exceeding MAX_NBT_UNCOMPRESSED_BYTES
    huge_payload = gzip.compress(b"\x00" * (MAX_NBT_UNCOMPRESSED_BYTES + 64))
    with pytest.raises(NbtParseError):
        parse_nbt_bytes(huge_payload)


def test_cross_loader_readiness_regex_matches_all_four_loaders() -> None:
    lines = [
        '[12:34:56 INFO]: Done (3.456s)! For help, type "help"',
        "[12:34:56] [Server thread/INFO]: Done (1,234s)! For help, type 'help'",
        (
            '[12:34:56] [ServerMain/INFO] [minecraft/DedicatedServer]: '
            'Done (12.3s)! For help, type "help"'
        ),
        (
            '[12:34:56] [Server thread/INFO] [minecraft/DedicatedServer]: '
            'Done (8.1s)! For help, type "help"'
        ),
    ]
    for line in lines:
        assert matches_boot_done_regex(line) is True

    non_matching = [
        "Done (1.0s)!",
        '[12:34:56 WARN]: Done (1.0s)! For help, type "help"',
        '[12:34:56 INFO]: Preparing spawn area: 99%',
    ]
    for bad in non_matching:
        assert matches_boot_done_regex(bad) is False


@pytest.mark.asyncio
async def test_poll_boot_signals_strict_stdout_only_ignores_latest_log(
    tmp_path: Path,
) -> None:
    latest_log = tmp_path / "logs" / "latest.log"
    latest_log.parent.mkdir(parents=True)
    # Even a fresh logs/latest.log on disk must NEVER satisfy strict_stdout_only=True
    latest_log.write_text(
        '[12:34:56 INFO]: Done (1.0s)! For help, type "help"\n',
        encoding="utf-8",
    )

    started_at = datetime.now(UTC)
    stdout_ticks = 0

    async def get_stdout_since(since: datetime) -> list[str]:
        nonlocal stdout_ticks
        assert since == started_at
        stdout_ticks += 1
        return ["[12:34:57 INFO]: Still loading..."]

    res = await poll_boot_signals(
        timeout=0.05,
        poll_interval=0.01,
        log_path=latest_log,
        log_since=started_at,
        get_logs_since=get_stdout_since,
        use_strict_done_regex=True,
        strict_stdout_only=True,
    )
    assert res.passed is False
    assert stdout_ticks >= 1


class _FakeRcon:
    def __init__(self, response: str = "Saved the game", *, fail: bool = False) -> None:
        self.response = response
        self.fail = fail
        self.commands: list[str] = []
        self.closed = False

    async def send_command(self, cmd: str) -> str:
        self.commands.append(cmd)
        if self.fail:
            raise RuntimeError("RCON socket error")
        return self.response

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_upgrade_health_gate_4_steps_mtime_retry_and_failures(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError):
        validate_health_gate_timeout(299)
    with pytest.raises(ValidationError):
        validate_health_gate_timeout(901)
    with pytest.raises(ValidationError):
        validate_health_gate_timeout(True)  # type: ignore[arg-type]
    assert validate_health_gate_timeout(300) == 300
    assert validate_health_gate_timeout(900) == 900

    server_root = tmp_path / "srv"
    world_dir = server_root / "world"
    world_dir.mkdir(parents=True)
    (world_dir / "dimensions" / "minecraft" / "the_nether").mkdir(parents=True)
    (world_dir / "dimensions" / "minecraft" / "the_end").mkdir(parents=True)

    started_at = datetime.now(UTC)
    level_dat = world_dir / "level.dat"
    # Pre-upgrade old level.dat
    level_dat.write_bytes(_build_full_level_dat_bytes(data_version=3700, version_id="1.20.4"))
    old_ts = (started_at - timedelta(minutes=5)).timestamp()
    os.utime(level_dat, (old_ts, old_ts))

    rcon = _FakeRcon()
    sleep_calls = 0

    async def fake_sleep(_sec: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        # Simulate atomic level.dat_new -> level.dat rename completing on 2nd poll!
        if sleep_calls == 2:
            level_dat.write_bytes(
                _build_full_level_dat_bytes(data_version=3955, version_id="1.21.1")
            )
            new_ts = (started_at + timedelta(seconds=1)).timestamp()
            os.utime(level_dat, (new_ts, new_ts))

    async def stdout_ok(_since: datetime) -> list[str]:
        return ['[12:34:56 INFO]: Done (2.5s)! For help, type "help"']

    async def alive() -> bool:
        return True

    async def tcp_ok() -> bool:
        return True

    evaluator = UpgradeHealthGateEvaluator(
        container_started_at=started_at,
        server_root=server_root,
        target_mc="1.21.1",
        get_stdout_since=stdout_ok,
        liveness_check=alive,
        tcp_probe=tcp_ok,
        rcon_client=rcon,
        dimension_smoke_check=check_dimension_smoke_paths,
        boot_timeout_seconds=5,
        poll_interval_seconds=0.01,
        mtime_poll_interval_seconds=0.01,
        mtime_max_wait_seconds=1.0,
        sleep=fake_sleep,
        _allow_test_timeout=True,
    )
    res = await evaluator.evaluate()
    assert res.passed is True
    assert res.data_version == 3955
    assert res.version_id == "1.21.1"
    assert rcon.commands == ["save-all flush"]
    assert rcon.closed is True
    assert sleep_calls >= 2

    # Failure at Step 2 (RCON error still closes client in finally)
    bad_rcon = _FakeRcon(fail=True)
    eval_s2 = UpgradeHealthGateEvaluator(
        container_started_at=started_at,
        server_root=server_root,
        target_mc="1.21.1",
        get_stdout_since=stdout_ok,
        liveness_check=alive,
        tcp_probe=tcp_ok,
        rcon_client=bad_rcon,
        boot_timeout_seconds=2,
        poll_interval_seconds=0.01,
        _allow_test_timeout=True,
    )
    res_s2 = await eval_s2.evaluate()
    assert res_s2.passed is False
    assert res_s2.failed_step == STEP_2_TCP_RCON_FLUSH
    assert bad_rcon.closed is True

    # Failure at Step 3 (stale DataVersion in level.dat even though mtime is fresh)
    level_dat.write_bytes(_build_full_level_dat_bytes(data_version=3700, version_id="1.20.4"))
    new_ts = (started_at + timedelta(seconds=2)).timestamp()
    os.utime(level_dat, (new_ts, new_ts))
    eval_s3 = UpgradeHealthGateEvaluator(
        container_started_at=started_at,
        server_root=server_root,
        target_mc="1.21.1",
        get_stdout_since=stdout_ok,
        liveness_check=alive,
        tcp_probe=tcp_ok,
        rcon_client=_FakeRcon(),
        boot_timeout_seconds=2,
        poll_interval_seconds=0.01,
        _allow_test_timeout=True,
    )
    res_s3 = await eval_s3.evaluate()
    assert res_s3.passed is False
    assert res_s3.failed_step == STEP_3_NBT_DATA_VERSION

    # Failure at Step 4 (dimension smoke check returns False)
    level_dat.write_bytes(_build_full_level_dat_bytes(data_version=3955, version_id="1.21.1"))
    os.utime(level_dat, (new_ts, new_ts))
    eval_s4 = UpgradeHealthGateEvaluator(
        container_started_at=started_at,
        server_root=server_root,
        target_mc="1.21.1",
        get_stdout_since=stdout_ok,
        liveness_check=alive,
        tcp_probe=tcp_ok,
        rcon_client=_FakeRcon(),
        dimension_smoke_check=lambda _p: False,
        boot_timeout_seconds=2,
        poll_interval_seconds=0.01,
        _allow_test_timeout=True,
    )
    res_s4 = await eval_s4.evaluate()
    assert res_s4.passed is False
    assert res_s4.failed_step == STEP_4_DIMENSION_SMOKE

    # Overarching timeout failure at Step 1 (non-retryable)
    async def never_done(_since: datetime) -> list[str]:
        await asyncio.sleep(0.2)
        return []

    eval_to = UpgradeHealthGateEvaluator(
        container_started_at=started_at,
        server_root=server_root,
        target_mc="1.21.1",
        get_stdout_since=never_done,
        liveness_check=alive,
        boot_timeout_seconds=0.04,  # type: ignore[arg-type]
        poll_interval_seconds=0.01,
        _allow_test_timeout=True,
    )
    res_to = await eval_to.evaluate()
    assert res_to.passed is False
    assert res_to.failed_step == STEP_1_STDOUT_DONE
    assert "timed out" in (res_to.reason or "").lower()
