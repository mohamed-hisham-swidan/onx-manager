from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.modules.server.infrastructure.signal_detection import (
    check_container_liveness,
    check_crash_reports,
    check_log_markers,
    check_pid_liveness,
    poll_boot_signals,
)


def test_check_log_markers_string() -> None:
    assert check_log_markers("Server started in 15s. Done (! For help, type help") is True
    assert check_log_markers("Loading libraries, please wait...") is False
    assert (
        check_log_markers(
            "Custom ready marker reached", markers=("Custom ready marker",)
        )
        is True
    )


def test_check_log_markers_list() -> None:
    lines = [
        "[00:00:01 INFO] Starting minecraft server version 1.21.1",
        "[00:00:05 INFO] Preparing level world",
        "[00:00:10 INFO] Done (10.234s)! For help, type help",
    ]
    assert check_log_markers(lines) is True

    lines_pending = [
        "[00:00:01 INFO] Starting minecraft server version 1.21.1",
        "[00:00:05 INFO] Preparing spawn area: 54%",
    ]
    assert check_log_markers(lines_pending) is False


def test_check_crash_reports_empty_and_missing(tmp_path: Path) -> None:
    has_crashed, reason, blamed = check_crash_reports(tmp_path / "nonexistent")
    assert has_crashed is False
    assert reason is None
    assert blamed is None

    empty_dir = tmp_path / "crash-reports"
    empty_dir.mkdir()
    has_crashed, reason, blamed = check_crash_reports(empty_dir)
    assert has_crashed is False


def test_check_crash_reports_with_report(tmp_path: Path) -> None:
    crash_dir = tmp_path / "crash-reports"
    crash_dir.mkdir()
    crash_file = crash_dir / "crash-2026-09-23_12.00.00-server.txt"
    crash_file.write_text(
        "---- Minecraft Crash Report ----\n"
        "// Don't do that.\n"
        "Time: 2026-09-23 12:00:00\n"
        "Description: Exception in server tick loop\n"
        "Suspected Mod: testmod\n"
        "java.lang.NullPointerException: Mod initialization failed\n"
        "\tat com.example.testmod.init(testmod.java:42)\n",
        encoding="utf-8",
    )

    has_crashed, reason, blamed = check_crash_reports(crash_dir)
    assert has_crashed is True
    assert reason is not None
    assert "Server crashed during boot" in reason


@pytest.mark.asyncio
async def test_check_container_liveness() -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="true\n")
        assert await check_container_liveness("test-container") is True

        mock_run.return_value = MagicMock(returncode=0, stdout="false\n")
        assert await check_container_liveness("test-container") is False

        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert await check_container_liveness("test-container") is False

    assert await check_container_liveness("") is False


@pytest.mark.allow_real_signals
@pytest.mark.asyncio
async def test_check_pid_liveness() -> None:
    assert await check_pid_liveness(0) is False
    assert await check_pid_liveness(-1) is False

    import os

    current_pid = os.getpid()
    assert await check_pid_liveness(current_pid) is True


@pytest.mark.asyncio
async def test_poll_boot_signals_marker_success() -> None:
    call_count = 0

    async def mock_get_logs() -> list[str]:
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            return ["[INFO] Done (5.0s)!"]
        return ["[INFO] Loading worlds..."]

    result = await poll_boot_signals(
        timeout=5.0,
        poll_interval=0.01,
        get_logs=mock_get_logs,
    )

    assert result.passed is True
    assert result.failure_reason is None
    assert result.blamed_mod is None


@pytest.mark.asyncio
async def test_poll_boot_signals_liveness_failure() -> None:
    call_count = 0

    async def mock_liveness() -> bool:
        nonlocal call_count
        call_count += 1
        return call_count <= 1

    async def mock_get_logs() -> list[str]:
        return ["[INFO] Loading worlds..."]

    result = await poll_boot_signals(
        timeout=5.0,
        poll_interval=0.01,
        liveness_check=mock_liveness,
        get_logs=mock_get_logs,
    )

    assert result.passed is False
    assert result.failure_reason is not None
    assert "terminated unexpectedly" in result.failure_reason


@pytest.mark.asyncio
async def test_poll_boot_signals_crash_detected(tmp_path: Path) -> None:
    crash_dir = tmp_path / "crash-reports"
    crash_dir.mkdir()
    crash_file = crash_dir / "crash-2026-09-23_12.00.00-server.txt"
    crash_file.write_text(
        "---- Minecraft Crash Report ----\n"
        "Description: Server initialization failed\n"
        "Suspected Mod: badmod\n"
        "java.lang.RuntimeException: Crash on startup\n",
        encoding="utf-8",
    )

    result = await poll_boot_signals(
        timeout=5.0,
        poll_interval=0.01,
        crash_dir=crash_dir,
        get_logs=lambda: iter([]),
    )

    assert result.passed is False
    assert result.failure_reason is not None
    assert "Server crashed during boot" in result.failure_reason


@pytest.mark.asyncio
async def test_poll_boot_signals_timeout() -> None:
    async def mock_get_logs() -> list[str]:
        return ["[INFO] Loading spawn area..."]

    result = await poll_boot_signals(
        timeout=0.05,
        poll_interval=0.01,
        get_logs=mock_get_logs,
    )

    assert result.passed is False
    assert result.failure_reason is not None
    assert "Server did not complete boot within" in result.failure_reason
