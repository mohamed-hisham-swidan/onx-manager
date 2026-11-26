from __future__ import annotations

from unittest.mock import patch

import pytest

from app.core.event_bus import EventBus
from app.core.persistence.db import database
from app.modules.auth.infrastructure.models import UserModel  # noqa: F401
from app.modules.monitoring.domain.aggregate import MetricPoint
from app.modules.monitoring.infrastructure.collector import (
    MetricsCollector,
    _parse_forge_tps,
    _parse_tick_query,
)
from app.modules.monitoring.infrastructure.rcon_client import parse_tps
from app.modules.monitoring.infrastructure.repository import SQLMetricRepository
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.value_objects import (
    JavaArguments,
    MemoryAllocation,
    PortNumber,
    ServerProperties,
    ServerType,
)
from app.modules.server.infrastructure.models import ServerModel  # noqa: F401
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import MinecraftVersion, ServerId


class TestParseTpsClamping:
    def test_parse_tps_overshoot_5s_clamped(self) -> None:
        raw = "§6TPS from last 5s, 1m, 5m, 15m: §a20.1§r, §a20.0§r, §a20.0§r, §a20.0"
        parsed = parse_tps(raw)
        assert parsed == 20.0

    def test_parse_tps_overshoot_1m_clamped(self) -> None:
        raw = "TPS from last 1m, 5m, 15m: 20.05, 20.0, 20.0"
        parsed = parse_tps(raw)
        assert parsed == 20.0

    def test_parse_tps_overclocked_30_clamped(self) -> None:
        raw = "TPS from last 5s: 30.0, 30.0, 30.0"
        parsed = parse_tps(raw)
        assert parsed == 20.0

    def test_parse_tps_negative_unchanged_for_domain_rejection(self) -> None:
        raw = "TPS from last 5s: -3.2, 20.0, 20.0"
        parsed = parse_tps(raw)
        assert parsed == -3.2

    def test_parse_tps_normal_unchanged(self) -> None:
        raw = "TPS from last 5s, 1m, 5m, 15m: 19.99, 19.85, 20.0, 20.0"
        parsed = parse_tps(raw)
        assert parsed == 19.99

    def test_parse_tps_overall_clamped(self) -> None:
        raw = "Overall TPS = 20.35"
        parsed = parse_tps(raw)
        assert parsed == 20.0

    def test_parse_tps_average_regex_clamped(self) -> None:
        raw = "Average: 20.25"
        parsed = parse_tps(raw)
        assert parsed == 20.0

    def test_parse_tps_average_negative_unchanged(self) -> None:
        raw = "Average: -2.5"
        parsed = parse_tps(raw)
        assert parsed == -2.5

    def test_parse_tick_query_overshoot_20_1_clamped(self) -> None:
        raw = (
            "The target tick rate is 20.0 per second. The average tick time is 0.1ms "
            "(target 50.0ms), with 20.1 ticks per second (100% of target)."
        )
        parsed = _parse_tick_query(raw)
        assert parsed == 20.0

    def test_parse_tick_query_overclocked_30_clamped(self) -> None:
        # Static "Target tick rate: ..." alone must NOT report fake TPS.
        assert _parse_tick_query("Target tick rate: 30.0 per second.") is None
        # Real MSPT derives actual lagging TPS (1000 / 125 = 8.0 TPS).
        assert (
            _parse_tick_query(
                "Target tick rate: 20.0 per second.\nAverage time per tick: 125.0ms"
            )
            == 8.0
        )
        # Explicit overclocked tick rate still clamps to 20.0.
        assert _parse_tick_query("The average tick time is 10.0ms, with 30.0 ticks per second") == 20.0

    def test_parse_forge_tps_overshoot_20_1_clamped(self) -> None:
        raw = "Dim minecraft:overworld: Mean tick time: 0.109 ms. Mean TPS: 20.100"
        parsed = _parse_forge_tps(raw)
        assert parsed == 20.0

    def test_parse_forge_tps_overclocked_30_clamped(self) -> None:
        raw = "Overworld: 30.000 TPS (0.140 ms/tick)"
        parsed = _parse_forge_tps(raw)
        assert parsed == 20.0


class TestMetricPointTpsValidation:
    def test_metric_point_legit_overshoot_constructs_clamped_to_20(self) -> None:
        point = MetricPoint(tps=20.1, players=5, ram_used_mb=1024.0, cpu_percent=25.0)
        assert point.tps == 20.0
        assert point.players == 5
        assert point.ram_used_mb == 1024.0
        assert point.cpu_percent == 25.0

    def test_metric_point_boundary_20_5_constructs_clamped(self) -> None:
        point = MetricPoint(tps=20.5, players=0, ram_used_mb=512.0, cpu_percent=10.0)
        assert point.tps == 20.0

    def test_metric_point_normal_values_unaffected(self) -> None:
        point = MetricPoint(tps=19.99, players=2, ram_used_mb=2048.0, cpu_percent=45.0)
        assert point.tps == 19.99

        point_exact_20 = MetricPoint(tps=20.0, players=0, ram_used_mb=100.0, cpu_percent=5.0)
        assert point_exact_20.tps == 20.0

        point_zero = MetricPoint(tps=0.0, players=0, ram_used_mb=100.0, cpu_percent=0.0)
        assert point_zero.tps == 0.0

    def test_metric_point_beyond_ceiling_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"TPS out of sane range \[0, 20.5\], got 20.51"):
            MetricPoint(tps=20.51, players=0, ram_used_mb=0, cpu_percent=0)

        with pytest.raises(ValueError, match=r"TPS out of sane range \[0, 20.5\], got 999"):
            MetricPoint(tps=999, players=0, ram_used_mb=0, cpu_percent=0)

    def test_metric_point_negative_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"TPS out of sane range \[0, 20.5\], got -1"):
            MetricPoint(tps=-1, players=0, ram_used_mb=0, cpu_percent=0)

    def test_metric_point_non_finite_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"TPS out of sane range"):
            MetricPoint(tps=float("nan"), players=0, ram_used_mb=0, cpu_percent=0)

        with pytest.raises(ValueError, match=r"TPS out of sane range"):
            MetricPoint(tps=float("inf"), players=0, ram_used_mb=0, cpu_percent=0)

        with pytest.raises(ValueError, match=r"TPS out of sane range"):
            MetricPoint(tps=float("-inf"), players=0, ram_used_mb=0, cpu_percent=0)

    def test_metric_point_none_tps_constructs(self) -> None:
        point = MetricPoint(tps=None, players=0, ram_used_mb=500.0, cpu_percent=10.0)
        assert point.tps is None
        assert point.players == 0
        assert point.ram_used_mb == 500.0
        assert point.cpu_percent == 10.0

        point_default = MetricPoint()
        assert point_default.tps is None
        assert point_default.players == 0


@pytest.mark.usefixtures("init_test_db")
class TestMetricsCollectorAndRepositoryIntegration:
    @pytest.mark.asyncio
    async def test_collector_persists_clamped_tps_and_emits_event(self) -> None:
        from app.modules.server.domain.value_objects import ServerDeployment

        server_id = ServerId("srv-tps-1")
        server = Server.create(
            server_id=server_id,
            name="TPS Server",
            server_type=ServerType.VANILLA,
            minecraft_version=MinecraftVersion.parse("1.21"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25565)),
            deployment=ServerDeployment(root_path="/tmp/srv-tps-1"),
        )
        server.start()
        server.mark_running(pid=12345, port=25565, host="127.0.0.1")

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            await repo.save(server)
            await session.commit()

        events: list[object] = []
        event_bus = EventBus()
        from app.core.event_bus import DomainEvent, EventHandler
        from app.modules.monitoring.infrastructure.collector import MetricCollectedEvent

        class TestHandler(EventHandler):
            async def handle(self, event: DomainEvent) -> None:
                events.append(event)

        event_bus.subscribe("MetricCollectedEvent", TestHandler())

        collector = MetricsCollector(event_bus=event_bus)

        # Mock _collect_rcon_metrics returning 20.1 TPS and process metrics returning 15% CPU / 1024MB RAM
        with (
            patch(
                "app.modules.monitoring.infrastructure.collector._collect_rcon_metrics",
                return_value=(20.1, 5),
            ),
            patch(
                "app.modules.monitoring.infrastructure.collector._read_server_properties",
                return_value={"enable-rcon": "true", "rcon.password": "secret"},
            ),
            patch(
                "app.modules.monitoring.infrastructure.collector._collect_process_metrics",
                return_value=(1024.0, 15.0),
            ),
        ):
            metric = await collector.collect("srv-tps-1")

        # Verify ServerMetrics returned has clamped 20.0 TPS (or point clamped)
        assert metric.tps == 20.0
        assert metric.cpu_percent == 15.0
        assert metric.ram_used_mb == 1024.0

        # Verify DB persistence via SQLMetricRepository
        async with database.session_factory() as session:
            metric_repo = SQLMetricRepository(session)
            points = await metric_repo.get_series(server_id)
            assert len(points) == 1
            latest = points[0]
            assert latest.tps == 20.0
            assert latest.cpu_percent == 15.0
            assert latest.ram_used_mb == 1024.0

        # Verify event publication
        assert len(events) == 1
        recorded_event = events[0]
        assert isinstance(recorded_event, MetricCollectedEvent)
        assert recorded_event.tps == 20.0

    @pytest.mark.asyncio
    async def test_garbage_tps_isolated_and_does_not_abort_other_servers(self) -> None:
        # Server 1 has garbage RCON response (e.g. 999.0)
        from app.modules.server.domain.value_objects import ServerDeployment

        s1 = Server.create(
            server_id=ServerId("srv-bad-1"),
            name="Bad Server",
            server_type=ServerType.VANILLA,
            minecraft_version=MinecraftVersion.parse("1.21"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25565)),
            deployment=ServerDeployment(root_path="/tmp/srv-bad-1"),
        )
        s1.start()
        s1.mark_running(pid=12346, port=25565, host="127.0.0.1")

        # Server 2 has legitimate 20.1 catch-up response
        s2 = Server.create(
            server_id=ServerId("srv-good-1"),
            name="Good Server",
            server_type=ServerType.VANILLA,
            minecraft_version=MinecraftVersion.parse("1.21"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25566)),
            deployment=ServerDeployment(root_path="/tmp/srv-good-1"),
        )
        s2.start()
        s2.mark_running(pid=12347, port=25566, host="127.0.0.1")

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            await repo.save(s1)
            await repo.save(s2)
            await session.commit()

        collector = MetricsCollector(
            event_bus=EventBus(), known_servers=["srv-bad-1", "srv-good-1"]
        )

        async def mock_collect_rcon(client: any) -> tuple[float, int]:
            if client.password == "secret-bad":
                return (999.0, 0)
            return (20.1, 3)

        def mock_read_properties(path: str) -> dict[str, str]:
            if "srv-bad-1" in str(path):
                return {"enable-rcon": "true", "rcon.password": "secret-bad"}
            return {"enable-rcon": "true", "rcon.password": "secret-good"}

        with (
            patch(
                "app.modules.monitoring.infrastructure.collector._collect_rcon_metrics",
                side_effect=mock_collect_rcon,
            ),
            patch(
                "app.modules.monitoring.infrastructure.collector._read_server_properties",
                side_effect=mock_read_properties,
            ),
            patch(
                "app.modules.monitoring.infrastructure.collector._collect_process_metrics",
                return_value=(500.0, 10.0),
            ),
        ):
            results = await collector.collect_all()

        # srv-bad-1 returned default/fallback metrics and did not persist anything due to real collector swallow
        assert "srv-bad-1" in results
        async with database.session_factory() as session:
            metric_repo = SQLMetricRepository(session)
            s1_points = await metric_repo.get_series(ServerId("srv-bad-1"))
            assert len(s1_points) == 0

            # srv-good-1 was persisted successfully with clamped 20.0 TPS
            s2_points = await metric_repo.get_series(ServerId("srv-good-1"))
            assert len(s2_points) == 1
            assert s2_points[0].tps == 20.0

    @pytest.mark.asyncio
    async def test_collector_persists_none_tps_when_no_rcon(self) -> None:
        server_id = ServerId("srv-no-rcon")
        server = Server.create(
            server_id=server_id,
            name="Vanilla No RCON",
            server_type=ServerType.VANILLA,
            minecraft_version=MinecraftVersion.parse("1.21"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25565)),
        )
        server.start()
        server.mark_running(pid=12348, port=25565, host="127.0.0.1")

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            await repo.save(server)
            await session.commit()

        events: list[object] = []
        event_bus = EventBus()
        from app.core.event_bus import DomainEvent, EventHandler
        from app.modules.monitoring.infrastructure.collector import MetricCollectedEvent

        class TestHandler(EventHandler):
            async def handle(self, event: DomainEvent) -> None:
                events.append(event)

        event_bus.subscribe("MetricCollectedEvent", TestHandler())
        collector = MetricsCollector(event_bus=event_bus)

        with (
            patch(
                "app.modules.monitoring.infrastructure.collector._read_server_properties",
                return_value={"enable-rcon": "false"},
            ),
            patch(
                "app.modules.monitoring.infrastructure.collector._collect_process_metrics",
                return_value=(512.0, 5.0),
            ),
        ):
            metric = await collector.collect("srv-no-rcon")

        assert metric.tps is None
        assert metric.players == 0
        assert metric.ram_used_mb == 512.0
        assert metric.cpu_percent == 5.0

        async with database.session_factory() as session:
            metric_repo = SQLMetricRepository(session)
            points = await metric_repo.get_series(server_id)
            assert len(points) == 1
            assert points[0].tps is None

        assert len(events) == 1
        assert isinstance(events[0], MetricCollectedEvent)
        assert events[0].tps is None

    @pytest.mark.asyncio
    async def test_collector_persists_none_tps_on_rcon_failure(self) -> None:
        server_id = ServerId("srv-rcon-fail")
        server = Server.create(
            server_id=server_id,
            name="RCON Fail Server",
            server_type=ServerType.VANILLA,
            minecraft_version=MinecraftVersion.parse("1.21"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25565)),
        )
        server.start()
        server.mark_running(pid=12349, port=25565, host="127.0.0.1")

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            await repo.save(server)
            await session.commit()

        collector = MetricsCollector(event_bus=EventBus())

        async def fail_rcon(_client: any) -> tuple[float, int]:
            raise ConnectionRefusedError("RCON not yet up")

        with (
            patch(
                "app.modules.monitoring.infrastructure.collector._collect_rcon_metrics",
                side_effect=fail_rcon,
            ),
            patch(
                "app.modules.monitoring.infrastructure.collector._read_server_properties",
                return_value={"enable-rcon": "true", "rcon.password": "pass"},
            ),
            patch(
                "app.modules.monitoring.infrastructure.collector._collect_process_metrics",
                return_value=(256.0, 2.0),
            ),
        ):
            metric = await collector.collect("srv-rcon-fail")

        assert metric.tps is None
        async with database.session_factory() as session:
            metric_repo = SQLMetricRepository(session)
            points = await metric_repo.get_series(server_id)
            assert len(points) == 1
            assert points[0].tps is None

    @pytest.mark.asyncio
    async def test_sql_metric_repository_roundtrip_with_none_tps(self) -> None:
        server_id = ServerId("srv-repo-none")
        point = MetricPoint(tps=None, players=4, ram_used_mb=1024.0, cpu_percent=20.0)

        async with database.session_factory() as session:
            metric_repo = SQLMetricRepository(session)
            await metric_repo.record(server_id, point)
            await session.commit()

        async with database.session_factory() as session:
            metric_repo = SQLMetricRepository(session)
            points = await metric_repo.get_series(server_id)
            assert len(points) == 1
            assert points[0].tps is None
            assert points[0].players == 4
            assert points[0].ram_used_mb == 1024.0
            assert points[0].cpu_percent == 20.0
