import asyncio
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
    result = await run_metrics_collection_task(
        {
            "collector": mock_collector,
        }
    )
    assert result["server_count"] == 0


@pytest.mark.asyncio
async def test_metrics_task_skips_overlapping_cycles() -> None:
    from app.tasks.definitions import metrics_collector as mod

    started = asyncio.Event()
    release = asyncio.Event()
    calls: list[int] = []

    async def slow_collect_all() -> dict[str, object]:
        calls.append(1)
        started.set()
        await release.wait()
        return {}

    mock_collector = MagicMock()
    mock_collector.collect_all = slow_collect_all
    mod._collector = mock_collector

    first = asyncio.ensure_future(mod.run_metrics_collection_task({}))
    await started.wait()

    second = asyncio.ensure_future(mod.run_metrics_collection_task({}))
    result = await second
    assert result["skipped"] is True

    release.set()
    first_result = await first
    assert "skipped" not in first_result
    assert calls == [1]

    mod._collector = None


def test_collect_process_metrics_fresh_pid_takes_real_cpu_sample() -> None:
    from app.modules.monitoring.infrastructure import collector as mod

    fake_proc = MagicMock()
    fake_proc.create_time.return_value = 123.0
    fake_proc.memory_info.return_value = MagicMock(rss=1024 * 1024 * 300)
    fake_proc.cpu_percent.return_value = 42.0

    with (
        patch.object(mod, "_HAS_PSUTIL", True),
        patch.object(
            mod,
            "_psutil",
            MagicMock(
                Process=lambda _pid: fake_proc,
                cpu_count=lambda: 2,
            ),
        ),
    ):
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

    with (
        patch.object(mod, "_HAS_PSUTIL", True),
        patch.object(mod, "_psutil", MagicMock(cpu_count=lambda: 2)),
    ):
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

    with (
        patch.object(mod, "_HAS_PSUTIL", True),
        patch.object(
            mod,
            "_psutil",
            MagicMock(
                Process=lambda _pid: new_proc,
                cpu_count=lambda: 2,
            ),
        ),
    ):
        cache: dict[int, tuple[float, object]] = {777: (100.0, old_proc)}
        ram_mb, cpu = mod._collect_process_metrics(777, cache)

    assert ram_mb == 0.0
    assert cpu == 6.0
    assert new_proc.cpu_percent.call_args.kwargs == {"interval": 0.1}


@pytest.mark.asyncio
async def test_collect_all_bounds_slow_server() -> None:
    from app.modules.monitoring.infrastructure import collector as mod

    collected: list[str] = []

    async def slow_collect(server_id: str) -> mod.ServerMetrics:
        collected.append(server_id)
        await asyncio.sleep(5)
        return mod.ServerMetrics(server_id=server_id)

    instance = mod.MetricsCollector(known_servers=["s1", "s2"], per_server_timeout=0.05)
    instance.collect = slow_collect  # type: ignore[method-assign]
    results = await instance.collect_all()

    assert set(collected) == {"s1", "s2"}
    assert len(results) == 2
    assert all(isinstance(m, mod.ServerMetrics) for m in results.values())


@pytest.mark.asyncio
async def test_collect_all_runs_servers_concurrently() -> None:
    """One slow/broken server must not delay collection for healthy servers."""
    from app.modules.monitoring.infrastructure import collector as mod

    completion_order: list[str] = []

    async def collect(server_id: str) -> mod.ServerMetrics:
        if server_id == "slow":
            await asyncio.sleep(1.0)
            completion_order.append(server_id)
            return mod.ServerMetrics(server_id="slow")
        completion_order.append(server_id)
        return mod.ServerMetrics(server_id=server_id)

    instance = mod.MetricsCollector(known_servers=["slow", "fast"], per_server_timeout=5.0)
    instance.collect = collect  # type: ignore[method-assign]
    results = await instance.collect_all()

    assert set(results) == {"slow", "fast"}
    assert completion_order[0] == "fast", "healthy server was delayed by the slow one"


def test_collect_process_metrics_without_psutil_returns_zeros() -> None:
    from app.modules.monitoring.infrastructure import collector as mod

    with patch.object(mod, "_HAS_PSUTIL", False):
        ram_mb, cpu = mod._collect_process_metrics(777, {})

    assert ram_mb == 0.0
    assert cpu == 0.0


@pytest.mark.asyncio
async def test_collect_rebuilds_rcon_client_when_config_changes() -> None:
    """Changed rcon password must rebuild the client instead of reusing a stale one."""
    from app.modules.monitoring.infrastructure import collector as mod

    instance = mod.MetricsCollector(known_servers=["s1"], per_server_timeout=5.0)

    def make_client(host: str, port: int, password: str) -> MagicMock:
        client = MagicMock()
        client.host = host
        client.port = port
        client.password = password
        client.close = AsyncMock()
        return client

    fake_server = MagicMock()
    fake_server.runtime.pid = None
    fake_server.runtime.host = "127.0.0.1"
    fake_server.deployment.root_path = "/srv"
    fake_server.deployment.properties_path.return_value = "/srv/server.properties"

    session_ctx = AsyncMock()
    session_ctx.__aenter__.return_value = session_ctx
    session_ctx.add = MagicMock()
    repo = MagicMock()
    repo.get = AsyncMock(return_value=fake_server)

    async def run_collect(password: str) -> MagicMock:
        props = {"enable-rcon": "true", "rcon.port": "25575", "rcon.password": password}
        fake_db = MagicMock()
        fake_db.session_factory = lambda: session_ctx
        fake_repo = MagicMock()
        fake_repo.get = AsyncMock(return_value=fake_server)
        with (
            patch.object(mod, "database", fake_db),
            patch.object(mod, "SQLServerRepository", return_value=fake_repo),
            patch.object(mod, "_read_server_properties", side_effect=lambda _p: props),
            patch.object(
                mod,
                "PersistentRCONClient",
                side_effect=lambda h, p, pw: make_client(h, p, pw),
            ),
            patch.object(mod, "_collect_rcon_metrics", new=AsyncMock(return_value=(20.0, 0))),
        ):
            await instance.collect("s1")
        return instance._rcon_clients["s1"]

    client1 = await run_collect("old-secret")
    assert client1.password == "old-secret"

    client2 = await run_collect("new-secret")
    assert client2 is not client1
    assert client2.password == "new-secret"
    client1.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_collect_evicts_rcon_client_when_rcon_disabled() -> None:
    """Disabling RCON must close and evict the cached client."""
    from app.modules.monitoring.infrastructure import collector as mod

    instance = mod.MetricsCollector(known_servers=["s1"], per_server_timeout=5.0)

    stale = MagicMock()
    stale.host = "127.0.0.1"
    stale.port = 25575
    stale.password = "secret"
    stale.close = AsyncMock()
    instance._rcon_clients["s1"] = stale

    fake_server = MagicMock()
    fake_server.runtime.pid = None
    fake_server.runtime.host = "127.0.0.1"
    fake_server.deployment.root_path = "/srv"
    fake_server.deployment.properties_path.return_value = "/srv/server.properties"

    session_ctx = AsyncMock()
    session_ctx.__aenter__.return_value = session_ctx
    session_ctx.add = MagicMock()
    repo = MagicMock()
    repo.get = AsyncMock(return_value=fake_server)

    def fake_props(_path: str) -> dict[str, str]:
        return {"enable-rcon": "false"}

    fake_db = MagicMock()
    fake_db.session_factory = lambda: session_ctx
    fake_repo = MagicMock()
    fake_repo.get = AsyncMock(return_value=fake_server)
    with (
        patch.object(mod, "database", fake_db),
        patch.object(mod, "SQLServerRepository", return_value=fake_repo),
        patch.object(mod, "_read_server_properties", side_effect=fake_props),
        patch.object(mod, "PersistentRCONClient"),
        patch.object(mod, "_collect_rcon_metrics", new=AsyncMock(return_value=(20.0, 0))),
    ):
        await instance.collect("s1")

    assert "s1" not in instance._rcon_clients
    stale.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_default_metrics_interval_is_safe_five_seconds() -> None:
    """Default metrics collection interval must be 5.0s to safely exceed docker stats runtime."""
    from app.core.config import AppSettings
    from app.core.settings_store import LiveSettings, get_live_settings

    app_settings = AppSettings()
    assert app_settings.metrics_interval_seconds == 5.0

    live_settings = get_live_settings()
    assert live_settings.metrics_interval_seconds == 5.0

    ls = LiveSettings()
    assert ls.metrics_interval_seconds == 5.0


@pytest.mark.asyncio
async def test_scheduler_configures_five_second_interval() -> None:
    """Scheduler must configure interval:5.0s with direct dispatch and max_instances=1."""
    from unittest.mock import MagicMock

    from app.tasks.scheduler import CronJobModel, Scheduler

    mock_session_factory = MagicMock()
    scheduler = Scheduler(mock_session_factory)
    mock_aps = MagicMock()
    scheduler._aps = mock_aps

    job_model = CronJobModel(
        id="job-metrics-5s",
        name="metrics_collect",
        cron_expression="interval:5.0s",
        task_name="run_metrics_collection",
        params_json="{}",
    )

    scheduler._schedule_job(job_model)

    mock_aps.add_job.assert_called_once()
    _, kwargs = mock_aps.add_job.call_args
    assert kwargs["trigger"] == "interval"
    assert kwargs["seconds"] == 5.0
    assert kwargs["max_instances"] == 1
    assert kwargs["coalesce"] is True


@pytest.mark.asyncio
async def test_fetch_docker_stats_cancellation_kills_and_reaps_process() -> None:
    """Verify cancellation terminates running docker stats process without leak."""
    from app.modules.monitoring.infrastructure.collector import MetricsCollector

    collector = MetricsCollector()
    mock_proc = AsyncMock()
    mock_proc.kill = MagicMock()
    mock_proc.returncode = None
    mock_proc.communicate.side_effect = asyncio.CancelledError()

    with (
        patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)),
        pytest.raises(asyncio.CancelledError),
    ):
        await collector.fetch_docker_stats()

    mock_proc.kill.assert_called_once()
    mock_proc.wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_docker_stats_timeout_kills_and_reaps_process() -> None:
    """Verify timeout terminates running docker stats process without leak."""
    from app.modules.monitoring.infrastructure.collector import MetricsCollector

    collector = MetricsCollector()
    mock_proc = AsyncMock()
    mock_proc.kill = MagicMock()
    mock_proc.returncode = None

    with (
        patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)),
        patch("asyncio.wait_for", AsyncMock(side_effect=TimeoutError())),
    ):
        result = await collector.fetch_docker_stats()

    assert result == {}
    mock_proc.kill.assert_called_once()
    mock_proc.wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_metrics_collection_task_cancellation_releases_lock() -> None:
    """Verify task cancellation releases _collection_lock so subsequent runs proceed."""
    from app.tasks.definitions import metrics_collector as mod

    started = asyncio.Event()

    async def cancelling_collect_all() -> dict[str, object]:
        started.set()
        await asyncio.sleep(10)
        return {}

    mock_collector = MagicMock()
    mock_collector.collect_all = cancelling_collect_all
    mod._collector = mock_collector

    task = asyncio.create_task(mod.run_metrics_collection_task({}))
    await started.wait()

    assert mod._collection_lock.locked()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    # Lock must be released
    assert not mod._collection_lock.locked()

    # Next run should not be skipped due to lock
    async def fast_collect_all(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {}

    mock_collector.collect_all = fast_collect_all
    second_result = await mod.run_metrics_collection_task({})
    assert "skipped" not in second_result
    mod._collector = None


def test_backend_dir_resolves_to_backend_root() -> None:
    from app.modules.monitoring.infrastructure import collector as mod

    assert mod._BACKEND_DIR.name == "backend"
    assert (mod._BACKEND_DIR / "app").is_dir()


def test_resolve_server_properties_path_falls_back_on_stale_root_path(tmp_path) -> None:
    from app.modules.monitoring.infrastructure import collector as mod

    servers_dir = tmp_path / "servers"
    sid = "deadbeef111122223333444455556666"
    named_dir = servers_dir / f"my-smp-{sid[:8]}"
    named_dir.mkdir(parents=True)
    real_props = named_dir / "server.properties"
    real_props.write_text("enable-rcon=true\nrcon.password=topsecret\n", encoding="utf-8")

    mock_settings = MagicMock(servers_data_dir=str(servers_dir))
    with patch("app.core.config.AppSettings", return_value=mock_settings):
        resolved = mod._resolve_server_properties_path(
            sid,
            "/stale/data/servers/server/server.properties",
            server_name="My SMP",
        )

    assert resolved == str(real_props)


@pytest.mark.asyncio
async def test_collect_normalizes_wildcard_rcon_host(tmp_path) -> None:
    from app.modules.monitoring.infrastructure import collector as mod

    props_file = tmp_path / "server.properties"
    props_file.write_text(
        "enable-rcon=true\nrcon.port=25575\nrcon.password=secret\n", encoding="utf-8"
    )

    fake_server = MagicMock()
    fake_server.name = "SMP"
    fake_server.runtime.pid = None
    fake_server.runtime.external_id = None
    fake_server.runtime.host = "0.0.0.0"
    fake_server.deployment.root_path = str(tmp_path)
    fake_server.deployment.properties_path.return_value = str(props_file)

    session_ctx = AsyncMock()
    session_ctx.__aenter__.return_value = session_ctx
    session_ctx.add = MagicMock()
    fake_db = MagicMock()
    fake_db.session_factory = lambda: session_ctx
    fake_repo = MagicMock()
    fake_repo.get = AsyncMock(return_value=fake_server)

    seen_hosts: list[str] = []

    def make_client(host: str, port: int, password: str) -> MagicMock:
        seen_hosts.append(host)
        client = MagicMock()
        client.host = host
        client.port = port
        client.password = password
        client.close = AsyncMock()
        return client

    collector = mod.MetricsCollector(known_servers=["deadbeef"], per_server_timeout=5.0)
    with (
        patch.object(mod, "database", fake_db),
        patch.object(mod, "SQLServerRepository", return_value=fake_repo),
        patch.object(mod, "PersistentRCONClient", side_effect=make_client),
        patch.object(mod, "_collect_rcon_metrics", new=AsyncMock(return_value=(20.0, 2))),
    ):
        metric = await collector.collect("deadbeef")

    assert seen_hosts == ["127.0.0.1"]
    assert metric.players == 2


@pytest.mark.asyncio
async def test_collect_skips_synthetic_zero_on_docker_stats_timeout() -> None:
    """When docker stats misses a running container, never emit synthetic 0.0 MB drops."""
    from app.modules.monitoring.infrastructure import collector as mod

    event_bus = MagicMock()
    event_bus.publish = AsyncMock()
    collector = mod.MetricsCollector(
        event_bus=event_bus, known_servers=["srv-docker-1"], per_server_timeout=5.0
    )

    fake_server = MagicMock()
    fake_server.name = "DockerSMP"
    fake_server.status.value = "running"
    fake_server.runtime.pid = None
    fake_server.runtime.external_id = "onx-srv-docker-1"
    fake_server.runtime.host = "172.17.0.5"
    fake_server.deployment.root_path = None

    session_ctx = AsyncMock()
    session_ctx.__aenter__.return_value = session_ctx
    session_ctx.add = MagicMock()
    fake_db = MagicMock()
    fake_db.session_factory = lambda: session_ctx
    fake_repo = MagicMock()
    fake_repo.get = AsyncMock(return_value=fake_server)
    metric_repo = MagicMock()
    metric_repo.record = AsyncMock()

    # 1. Cold timeout (no cached valid stats yet): must NOT persist or publish 0.0 MB
    collector._docker_stats_cache = {}
    with (
        patch.object(mod, "database", fake_db),
        patch.object(mod, "SQLServerRepository", return_value=fake_repo),
        patch.object(mod, "SQLMetricRepository", return_value=metric_repo),
    ):
        await collector.collect("srv-docker-1")

    metric_repo.record.assert_not_awaited()
    event_bus.publish.assert_not_awaited()

    # 2. Valid sample recorded and cached
    collector._docker_stats_cache = {
        "onx-srv-docker-1": mod.ContainerStats(
            name="onx-srv-docker-1",
            cpu_percent=18.5,
            ram_used_mb=1536.0,
        )
    }
    with (
        patch.object(mod, "database", fake_db),
        patch.object(mod, "SQLServerRepository", return_value=fake_repo),
        patch.object(mod, "SQLMetricRepository", return_value=metric_repo),
    ):
        valid_metric = await collector.collect("srv-docker-1")

    assert valid_metric.ram_used_mb == 1536.0
    assert valid_metric.cpu_percent == 18.5
    assert metric_repo.record.await_count == 1

    # 3. Subsequent transient docker stats timeout carries forward recent valid sample (never 0.0!)
    collector._docker_stats_cache = {}
    with (
        patch.object(mod, "database", fake_db),
        patch.object(mod, "SQLServerRepository", return_value=fake_repo),
        patch.object(mod, "SQLMetricRepository", return_value=metric_repo),
    ):
        carried = await collector.collect("srv-docker-1")

    assert carried.ram_used_mb == 1536.0
    assert carried.cpu_percent == 18.5
    assert metric_repo.record.await_count == 2

