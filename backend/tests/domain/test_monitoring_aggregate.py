from __future__ import annotations

import pytest

from app.modules.monitoring.domain.aggregate import (
    AlertCondition,
    AlertRule,
    AlertSeverity,
    MetricPoint,
    MetricSeries,
)
from app.modules.shared.value_objects import ServerId


class TestMetricPoint:
    def test_create(self) -> None:
        point = MetricPoint(tps=19.5, players=10, ram_used_mb=2048, cpu_percent=45.2)
        assert point.tps == 19.5
        assert point.players == 10
        assert point.ram_used_mb == 2048
        assert point.cpu_percent == 45.2

    def test_tps_too_high(self) -> None:
        with pytest.raises(ValueError):
            MetricPoint(tps=25, players=0, ram_used_mb=0, cpu_percent=0)

    def test_tps_negative(self) -> None:
        with pytest.raises(ValueError):
            MetricPoint(tps=-1, players=0, ram_used_mb=0, cpu_percent=0)

    def test_players_negative(self) -> None:
        with pytest.raises(ValueError):
            MetricPoint(tps=20, players=-1, ram_used_mb=0, cpu_percent=0)

    def test_cpu_out_of_range(self) -> None:
        with pytest.raises(ValueError):
            MetricPoint(tps=20, players=0, ram_used_mb=0, cpu_percent=101)

    def test_ram_negative(self) -> None:
        with pytest.raises(ValueError):
            MetricPoint(tps=20, players=0, ram_used_mb=-1, cpu_percent=0)


class TestMetricSeries:
    def test_empty(self) -> None:
        series = MetricSeries(ServerId("s1"))
        assert len(series.points) == 0
        assert series.latest is None

    def test_record_point(self) -> None:
        series = MetricSeries(ServerId("s1"))
        series.record(MetricPoint(tps=19.5, players=5, ram_used_mb=1024, cpu_percent=30))
        assert len(series.points) == 1
        assert series.latest is not None
        assert series.latest.tps == 19.5

    def test_max_points_enforced(self) -> None:
        series = MetricSeries(ServerId("s1"), max_points=3)
        for i in range(5):
            series.record(MetricPoint(tps=20, players=i, ram_used_mb=100, cpu_percent=10))
        assert len(series.points) == 3
        assert series.points[0].players == 2


class TestAlertRule:
    def test_greater_than_triggers(self) -> None:
        rule = AlertRule(
            server_id=ServerId("s1"),
            metric_name="cpu_percent",
            condition=AlertCondition.GREATER_THAN,
            threshold=90.0,
            severity=AlertSeverity.CRITICAL,
        )
        assert rule.evaluate(95.0) is True
        assert rule.evaluate(50.0) is False

    def test_less_than_triggers(self) -> None:
        rule = AlertRule(
            server_id=ServerId("s1"),
            metric_name="tps",
            condition=AlertCondition.LESS_THAN,
            threshold=10.0,
            severity=AlertSeverity.WARNING,
        )
        assert rule.evaluate(5.0) is True
        assert rule.evaluate(15.0) is False

    def test_equal_triggers(self) -> None:
        rule = AlertRule(
            server_id=ServerId("s1"),
            metric_name="players",
            condition=AlertCondition.EQUAL,
            threshold=0.0,
        )
        assert rule.evaluate(0.0) is True
        assert rule.evaluate(1.0) is False

    def test_disabled_rule(self) -> None:
        rule = AlertRule(
            server_id=ServerId("s1"),
            metric_name="cpu",
            condition=AlertCondition.GREATER_THAN,
            threshold=50.0,
            enabled=False,
        )
        assert rule.evaluate(100.0) is False

    def test_trigger_emits_event(self) -> None:
        rule = AlertRule(
            server_id=ServerId("s1"),
            metric_name="cpu",
            condition=AlertCondition.GREATER_THAN,
            threshold=90.0,
        )
        rule.trigger(95.0)
        from app.modules.monitoring.domain.events import AlertTriggeredEvent

        events = rule.collect_events()
        assert any(isinstance(e, AlertTriggeredEvent) for e in events)

    def test_cooldown(self) -> None:
        rule = AlertRule(
            server_id=ServerId("s1"),
            metric_name="cpu",
            condition=AlertCondition.GREATER_THAN,
            threshold=90.0,
            cooldown_minutes=60,
        )
        rule.trigger(95.0)
        events = rule.collect_events()
        assert len(events) == 1
        rule.trigger(96.0)
        events = rule.collect_events()
        assert len(events) == 0
