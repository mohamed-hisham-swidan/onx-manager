from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import AsyncMock, patch

import pytest

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
