from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.event_bus import EventBus
from app.core.persistence.db import database
from app.modules.auth.infrastructure.models import UserModel
from app.modules.monitoring.domain.aggregate import MetricPoint, MetricSeries
from app.modules.monitoring.domain.events import MetricRecordedEvent
from app.modules.monitoring.infrastructure.collector import MetricsCollector
from app.modules.monitoring.infrastructure.models import MetricPointModel
from app.modules.monitoring.infrastructure.rcon_client import parse_tps
from app.modules.monitoring.infrastructure.repository import SQLMetricRepository
from app.modules.server.domain.aggregate import Server, ServerStatus
from app.modules.server.domain.value_objects import (
    JavaArguments,
    MemoryAllocation,
    PortNumber,
    ServerProperties,
    ServerType,
)
from app.modules.server.infrastructure.models import ServerModel
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


@pytest.mark.usefixtures("init_test_db")
class TestMetricsCollectorAndRepositoryIntegration:
    @pytest.mark.asyncio
    async def test_collector_persists_clamped_tps_and_emits_event(self) -> None:
        server_id = ServerId("srv-tps-1")
        server = Server.create(
            server_id=server_id,
            name="TPS Server",
            server_type=ServerType.VANILLA,
            minecraft_version=MinecraftVersion.parse("1.21"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25565)),
        )
        server.start()
        server.mark_running(pid=12345, port=25565, host="127.0.0.1")

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            await repo.save(server)
            await session.commit()

        events: list[object] = []
        event_bus = EventBus()
        from app.core.event_bus import EventHandler, DomainEvent
        from app.modules.monitoring.infrastructure.collector import MetricCollectedEvent

        class TestHandler(EventHandler):
            async def handle(self, event: DomainEvent) -> None:
                events.append(event)

        event_bus.subscribe("MetricCollectedEvent", TestHandler())

        collector = MetricsCollector(event_bus=event_bus)

        # Mock _collect_rcon_metrics returning 20.1 TPS and process metrics returning 15% CPU / 1024MB RAM
        with patch("app.modules.monitoring.infrastructure.collector._collect_rcon_metrics", return_value=(20.1, 5)), \
             patch("app.modules.monitoring.infrastructure.collector._read_server_properties", return_value={"enable-rcon": "true", "rcon.password": "secret"}), \
             patch("app.modules.monitoring.infrastructure.collector._collect_process_metrics", return_value=(1024.0, 15.0)):
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

        collector = MetricsCollector(event_bus=EventBus(), known_servers=["srv-bad-1", "srv-good-1"])

        async def mock_collect_rcon(client: any) -> tuple[float, int]:
            if client.password == "secret-bad":
                return (999.0, 0)
            return (20.1, 3)

        def mock_read_properties(path: str) -> dict[str, str]:
            if "srv-bad-1" in str(path):
                return {"enable-rcon": "true", "rcon.password": "secret-bad"}
            return {"enable-rcon": "true", "rcon.password": "secret-good"}

        with patch("app.modules.monitoring.infrastructure.collector._collect_rcon_metrics", side_effect=mock_collect_rcon), \
             patch("app.modules.monitoring.infrastructure.collector._read_server_properties", side_effect=mock_read_properties), \
             patch("app.modules.monitoring.infrastructure.collector._collect_process_metrics", return_value=(500.0, 10.0)):
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
