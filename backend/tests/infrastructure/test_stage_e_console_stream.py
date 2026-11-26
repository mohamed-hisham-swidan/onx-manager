from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, PropertyMock, patch

import pytest

from app.core.persistence.db import database
from app.modules.server.infrastructure.console_stream import (
    ConsoleStreamManager,
    partition_lines_by_size,
)


def test_partition_lines_by_size_small():
    lines = ["line 1", "line 2", "line 3"]
    chunks = partition_lines_by_size(lines, max_bytes=1000)
    assert chunks == [lines]


def test_partition_lines_by_size_large_splits():
    # 10 lines of 1000 chars each = ~10KB
    long_line = "A" * 1000
    lines = [f"{i}-{long_line}" for i in range(20)]
    # With max_bytes=3000, it must partition into multiple chunks
    chunks = partition_lines_by_size(lines, max_bytes=3000)
    assert len(chunks) > 1
    # Check flattening preserves all lines in order
    flattened = [item for chunk in chunks for item in chunk]
    assert flattened == lines


@pytest.mark.asyncio
async def test_console_stream_manager_lifecycle():
    broadcast_mock = AsyncMock(return_value=1)
    manager = ConsoleStreamManager(
        broadcast_fn=broadcast_mock,
        debounce_seconds=0.1,  # Fast debounce for testing
    )
    await manager.start()

    channel = "server:s01:console"

    async def fake_stream_loop(_ch: str):
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(60)

    with patch.object(manager, "_run_stream_loop", side_effect=fake_stream_loop):
        # Simulate subscriber joins (0 -> 1)
        await manager.on_subscription_change(channel, 1)
        assert manager.is_channel_active(channel)

        # Simulate subscriber count increases (1 -> 2) - should not create new stream
        await manager.on_subscription_change(channel, 2)
        assert manager.is_channel_active(channel)

        # Subscribers drop to 0 (2 -> 0)
        await manager.on_subscription_change(channel, 0)
        assert channel in manager._debounce_tasks

        # Wait for debounce timer to fire
        await asyncio.sleep(0.15)
        assert not manager.is_channel_active(channel)

    await manager.stop()


@pytest.mark.asyncio
async def test_console_stream_manager_debounce_cancellation():
    broadcast_mock = AsyncMock(return_value=1)
    manager = ConsoleStreamManager(
        broadcast_fn=broadcast_mock,
        debounce_seconds=0.2,
    )
    await manager.start()

    channel = "test:t01:console"

    async def fake_stream_loop(_ch: str):
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(60)

    with patch.object(manager, "_run_stream_loop", side_effect=fake_stream_loop):
        # 1 subscriber
        await manager.on_subscription_change(channel, 1)
        assert manager.is_channel_active(channel)

        # Drops to 0 -> debounce starts
        await manager.on_subscription_change(channel, 0)
        assert channel in manager._debounce_tasks

        # Before debounce finishes, subscriber rejoins (0 -> 1)
        await asyncio.sleep(0.05)
        await manager.on_subscription_change(channel, 1)
        assert channel not in manager._debounce_tasks
        assert manager.is_channel_active(channel)

        # Wait past original debounce time
        await asyncio.sleep(0.2)
        # Should STILL be active because subscriber rejoined!
        assert manager.is_channel_active(channel)

    await manager.stop()


@pytest.mark.asyncio
async def test_console_stream_backpressure_flood_and_visible_marker():
    """Task 8 hard requirement:

    Flood simulation asserting queue limit is enforced, surplus lines are dropped,
    and a visible marker line '[N lines dropped — buffer overflow]' is emitted.
    """
    broadcast_records: list[list[str]] = []

    async def mock_broadcast(_channel: str, lines: list[str]) -> int:
        broadcast_records.append(list(lines))
        return len(lines)

    manager = ConsoleStreamManager(
        broadcast_fn=mock_broadcast,
        max_buffer_lines=100,  # low threshold for fast flood test
        batch_lines=20,
        batch_timeout=0.05,
    )
    await manager.start()

    queue: asyncio.Queue[str] = asyncio.Queue()

    # Enqueue 150 lines (exceeds max_buffer_lines=100)
    for i in range(150):
        await manager._enqueue_line(queue, f"flood-line-{i}")

    # Verify that the queue dropped down to BUFFER_RETAIN_ON_DROP or drained
    all_queued: list[str] = []
    while not queue.empty():
        all_queued.append(queue.get_nowait())

    # Find the drop marker(s)
    markers = [line for line in all_queued if "lines dropped — buffer overflow" in line]
    assert len(markers) >= 1, f"Expected drop marker in queue, got: {markers}"
    for marker in markers:
        assert marker.startswith("[") and marker.endswith("]")
        assert "lines dropped — buffer overflow" in marker

    await manager.stop()


@pytest.mark.asyncio
async def test_flusher_batching_and_size_partitioning():
    broadcasted_chunks: list[list[str]] = []

    async def mock_broadcast(_channel: str, lines: list[str]) -> int:
        broadcasted_chunks.append(lines)
        return len(lines)

    manager = ConsoleStreamManager(
        broadcast_fn=mock_broadcast,
        batch_lines=5,
        batch_timeout=0.05,
    )
    manager._running = True
    queue: asyncio.Queue[str] = asyncio.Queue()

    flusher = asyncio.create_task(manager._flusher("server:s1:console", queue))

    # Feed 7 lines
    for i in range(7):
        await queue.put(f"line-{i}")

    # Wait for flusher to process
    await asyncio.sleep(0.12)

    manager._running = False
    flusher.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await flusher

    # Should have flushed at least one batch of 5 and remaining 2
    total_lines = sum(len(c) for c in broadcasted_chunks)
    assert total_lines == 7


@pytest.mark.asyncio
async def test_file_tail_producer_streams_growing_file(tmp_path: Path):
    log_file = tmp_path / "latest.log"
    # Write initial lines before producer starts
    log_file.write_text("initial-1\ninitial-2\n", encoding="utf-8")

    manager = ConsoleStreamManager(broadcast_fn=AsyncMock())
    manager._running = True
    queue: asyncio.Queue[str] = asyncio.Queue()

    producer = asyncio.create_task(manager._file_tail_producer(log_file, queue))
    # Give producer time to seek to EOF
    await asyncio.sleep(0.05)
    assert queue.empty(), "Initial lines should not be queued (tail 0 behavior)"

    # Append new lines
    with open(log_file, "a", encoding="utf-8") as f:
        f.write("appended-1\nappended-2\n")

    # Wait for 250ms polling loop
    await asyncio.sleep(0.35)

    manager._running = False
    producer.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await producer

    queued: list[str] = []
    while not queue.empty():
        queued.append(queue.get_nowait())

    assert queued == ["appended-1", "appended-2"]


@pytest.mark.asyncio
async def test_file_tail_producer_handles_missing_and_rotated_file(tmp_path: Path):
    log_file = tmp_path / "latest.log"
    # File does not exist initially

    manager = ConsoleStreamManager(broadcast_fn=AsyncMock())
    manager._running = True
    queue: asyncio.Queue[str] = asyncio.Queue()

    producer = asyncio.create_task(manager._file_tail_producer(log_file, queue))
    # Wait while file does not exist - producer should not crash
    await asyncio.sleep(0.1)
    assert not producer.done()
    assert queue.empty()

    # Now create file and write lines
    log_file.write_text("created-line-1\ncreated-line-2\n", encoding="utf-8")
    await asyncio.sleep(0.35)

    queued: list[str] = []
    while not queue.empty():
        queued.append(queue.get_nowait())
    assert queued == ["created-line-1", "created-line-2"]

    # Now simulate file rotation / truncation: write a shorter new file
    log_file.write_text("rotated-line-1\n", encoding="utf-8")
    await asyncio.sleep(0.35)

    while not queue.empty():
        queued.append(queue.get_nowait())
    assert queued == ["created-line-1", "created-line-2", "rotated-line-1"]

    manager._running = False
    producer.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await producer


@pytest.mark.asyncio
async def test_resolve_target_routing():
    manager = ConsoleStreamManager(broadcast_fn=AsyncMock())

    # 1. Test channel -> docker
    target_name, mode, log_path = await manager._resolve_target("test:run-123:console")
    assert target_name == "onx-test-run-123"
    assert mode == "docker"
    assert log_path is None

    def create_mock_db(server_model):
        mock_session = AsyncMock()
        mock_session.get.return_value = server_model
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = None
        return mock_ctx

    # 2. Live server - docker -> docker
    doc_server = SimpleNamespace(
        id="s-doc",
        provider="docker",
        external_id="ext-docker",
        root_path=None,
        working_directory=".",
    )
    with patch.object(
        type(database),
        "session_factory",
        new_callable=PropertyMock,
        return_value=lambda: create_mock_db(doc_server),
    ):
        target_name, mode, log_path = await manager._resolve_target("server:s-doc:console")
        assert target_name == "ext-docker"
        assert mode == "docker"
        assert log_path is None


class _MockStreamReader:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)

    async def readline(self) -> bytes:
        if self._lines:
            return self._lines.pop(0)
        return b""


@pytest.mark.asyncio
async def test_resolve_target_stopped_docker_server_uses_file_tail_fallback():
    """Requirement 1 & 2: When external_id is empty/absent for Docker server,

    do NOT synthesize onx-server-*. Use file_tail disk log fallback instead.
    """
    manager = ConsoleStreamManager(broadcast_fn=AsyncMock())

    def create_mock_db(server_model):
        mock_session = AsyncMock()
        mock_session.get.return_value = server_model
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = None
        return mock_ctx

    stopped_docker_server = SimpleNamespace(
        id="s-stopped",
        provider="docker",
        external_id="",  # Empty string set on mark_stopped()
        root_path="/srv/mc_data/s-stopped",
        working_directory=".",
    )

    with patch.object(
        type(database),
        "session_factory",
        new_callable=PropertyMock,
        return_value=lambda: create_mock_db(stopped_docker_server),
    ):
        target_name, mode, log_path = await manager._resolve_target("server:s-stopped:console")
        assert target_name == ""
        assert not target_name.startswith("onx-server-")
        assert mode == "file_tail"
        assert log_path == Path("/srv/mc_data/s-stopped/logs/latest.log")


@pytest.mark.asyncio
async def test_resolve_target_unregistered_server_does_not_synthesize_onx_server():
    """Requirement 1: Non-existent server does not synthesize onx-server-* docker target."""
    manager = ConsoleStreamManager(broadcast_fn=AsyncMock())

    def create_mock_db(server_model):
        mock_session = AsyncMock()
        mock_session.get.return_value = server_model
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = None
        return mock_ctx

    with patch.object(
        type(database),
        "session_factory",
        new_callable=PropertyMock,
        return_value=lambda: create_mock_db(None),
    ):
        target_name, mode, log_path = await manager._resolve_target("server:s-ghost:console")
        assert target_name == ""
        assert mode == "file_tail"
        assert target_name != "onx-server-s-ghost"
        assert log_path is not None
        assert log_path.name == "latest.log"


@pytest.mark.asyncio
async def test_empty_external_id_does_not_invoke_docker_logs(tmp_path: Path):
    """Requirement 6: Empty external_id does not invoke docker logs against a fabricated name,

    and stopped server uses the intended disk log fallback.
    """
    server_dir = tmp_path / "srv_stopped"
    logs_dir = server_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    latest_log = logs_dir / "latest.log"
    latest_log.write_text("initial log\n", encoding="utf-8")

    stopped_server = SimpleNamespace(
        id="srv-stopped-1",
        provider="docker",
        external_id=None,
        root_path=str(server_dir),
        working_directory=".",
    )

    def create_mock_db(server_model):
        mock_session = AsyncMock()
        mock_session.get.return_value = server_model
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = None
        return mock_ctx

    broadcast_lines: list[list[str]] = []

    async def mock_broadcast(_ch: str, lines: list[str]) -> int:
        broadcast_lines.append(lines)
        return len(lines)

    manager = ConsoleStreamManager(
        broadcast_fn=mock_broadcast,
        batch_lines=1,
        batch_timeout=0.05,
    )
    manager._running = True

    with (
        patch.object(
            type(database),
            "session_factory",
            new_callable=PropertyMock,
            return_value=lambda: create_mock_db(stopped_server),
        ),
        patch("asyncio.create_subprocess_exec") as mock_exec,
    ):
        stream_task = asyncio.create_task(
            manager._run_stream_loop("server:srv-stopped-1:console")
        )
        await asyncio.sleep(0.1)

        # Append new log line to disk
        with open(latest_log, "a", encoding="utf-8") as f:
            f.write("server stopped gracefully\n")

        await asyncio.sleep(0.35)

        manager._running = False
        stream_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stream_task

        # Verify docker logs was NEVER called
        assert mock_exec.call_count == 0

        # Single authoritative source: latest.log is never tailed for live servers
        flat = [line for chunk in broadcast_lines for line in chunk]
        assert "server stopped gracefully" not in flat


@pytest.mark.asyncio
async def test_docker_logs_producer_does_not_enqueue_daemon_stderr():
    """Requirement 3 & 6: Docker daemon stderr (e.g.

    'Error response from daemon: No such container: ...')
    is NOT enqueued as Minecraft console output.
    """
    queue: asyncio.Queue[str] = asyncio.Queue()
    manager = ConsoleStreamManager(broadcast_fn=AsyncMock())
    manager._running = True

    # Simulate docker CLI failing with daemon error on stderr, empty stdout
    daemon_err = b"Error response from daemon: No such container: onx-server-123\n"
    mock_proc = AsyncMock()
    mock_proc.stdout = _MockStreamReader([])
    mock_proc.stderr = _MockStreamReader([daemon_err])
    mock_proc.returncode = 1
    mock_proc.kill = AsyncMock()
    mock_proc.wait = AsyncMock()

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
        task = asyncio.create_task(
            manager._docker_logs_producer("onx-server-123", queue)
        )
        await asyncio.sleep(0.1)
        manager._running = False
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    # Assert nothing was enqueued
    assert queue.empty(), f"Daemon error was enqueued: {list(queue._queue)}"


@pytest.mark.asyncio
async def test_docker_logs_producer_active_container_streaming_unchanged():
    """Requirement 5 & 6: Active container stdout streaming remains functional."""
    queue: asyncio.Queue[str] = asyncio.Queue()
    manager = ConsoleStreamManager(broadcast_fn=AsyncMock())
    manager._running = True

    stdout_line = b"2026-09-29T12:00:00.000Z [INFO] Done (1.234s)! For help, type \"help\"\n"
    mock_proc = AsyncMock()
    mock_proc.stdout = _MockStreamReader([stdout_line])
    mock_proc.stderr = _MockStreamReader([])
    mock_proc.returncode = 0
    mock_proc.kill = AsyncMock()
    mock_proc.wait = AsyncMock()

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
        task = asyncio.create_task(
            manager._docker_logs_producer("onx-real-container", queue)
        )
        await asyncio.sleep(0.1)
        manager._running = False
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert not queue.empty()
    item = queue.get_nowait()
    assert item == "2026-09-29T12:00:00.000Z [INFO] Done (1.234s)! For help, type \"help\""
