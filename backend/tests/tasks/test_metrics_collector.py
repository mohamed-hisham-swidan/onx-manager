from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tasks.definitions.metrics_collector import run_metrics_collection_task


@pytest.mark.asyncio
async def test_metrics_task_without_collector_skips() -> None:
    result = await run_metrics_collection_task({})
    assert result["server_count"] == 0
    assert result["results"] == {}


@pytest.mark.asyncio
async def test_metrics_task_with_collector() -> None:
    mock_collector = AsyncMock()
    mock_collector.collect_all.return_value = {}
    result = await run_metrics_collection_task({
        "collector": mock_collector,
    })
    assert result["server_count"] == 0


def test_collect_process_metrics_fresh_pid_takes_real_cpu_sample() -> None:
    from app.modules.monitoring.infrastructure import collector as mod

    fake_proc = MagicMock()
    fake_proc.create_time.return_value = 123.0
    fake_proc.memory_info.return_value = MagicMock(rss=1024 * 1024 * 300)
    fake_proc.cpu_percent.return_value = 42.0

    with patch.object(mod, "_HAS_PSUTIL", True), \
         patch.object(mod, "_psutil", MagicMock(
             Process=lambda _pid: fake_proc,
             cpu_count=lambda: 2,
         )):
        cache: dict[int, tuple[float, object]] = {}
        ram_mb, cpu = mod._collect_process_metrics(777, cache)

    assert ram_mb == 300.0
    assert cpu == 21.0
    assert fake_proc.cpu_percent.call_args.kwargs == {"interval": 0.1}
    assert 777 in cache


def test_collect_process_metrics_cached_pid_uses_instant_baseline() -> None:
    from app.modules.monitoring.infrastructure import collector as mod

    fake_proc = MagicMock()
    fake_proc.is_running.return_value = True
    fake_proc.create_time.return_value = 123.0
    fake_proc.memory_info.return_value = MagicMock(rss=1024 * 1024 * 300)
    fake_proc.cpu_percent.return_value = 7.0

    with patch.object(mod, "_HAS_PSUTIL", True), \
         patch.object(mod, "_psutil", MagicMock(cpu_count=lambda: 2)):
        cache: dict[int, tuple[float, object]] = {777: (123.0, fake_proc)}
        ram_mb, cpu = mod._collect_process_metrics(777, cache)

    assert ram_mb == 300.0
    assert cpu == 3.5
    assert fake_proc.cpu_percent.call_args.kwargs == {"interval": 0}


def test_collect_process_metrics_stale_pid_refreshes_and_resamples() -> None:
    from app.modules.monitoring.infrastructure import collector as mod

    old_proc = MagicMock()
    old_proc.is_running.return_value = False
    old_proc.create_time.return_value = 100.0
    new_proc = MagicMock()
    new_proc.create_time.return_value = 200.0
    new_proc.memory_info.return_value = MagicMock(rss=0)
    new_proc.cpu_percent.return_value = 12.0

    with patch.object(mod, "_HAS_PSUTIL", True), \
         patch.object(mod, "_psutil", MagicMock(
             Process=lambda _pid: new_proc,
             cpu_count=lambda: 2,
         )):
        cache: dict[int, tuple[float, object]] = {777: (100.0, old_proc)}
        ram_mb, cpu = mod._collect_process_metrics(777, cache)

    assert ram_mb == 0.0
    assert cpu == 6.0
    assert new_proc.cpu_percent.call_args.kwargs == {"interval": 0.1}


def test_collect_process_metrics_without_psutil_returns_zeros() -> None:
    from app.modules.monitoring.infrastructure import collector as mod

    with patch.object(mod, "_HAS_PSUTIL", False):
        ram_mb, cpu = mod._collect_process_metrics(777, {})

    assert ram_mb == 0.0
    assert cpu == 0.0
