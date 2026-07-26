from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from app.modules.monitoring.domain.events import (
    AlertResolvedEvent,
    AlertTriggeredEvent,
    MetricRecordedEvent,
)
from app.modules.shared.aggregate import AggregateRoot
from app.modules.shared.value_objects import ServerId


class MetricPoint:
    def __init__(
        self,
        tps: float,
        players: int,
        ram_used_mb: float,
        cpu_percent: float,
        timestamp: datetime | None = None,
    ) -> None:
        if tps < 0 or tps > 20:
            raise ValueError(f"TPS must be between 0 and 20, got {tps}")
        if players < 0:
            raise ValueError(f"Players must be non-negative, got {players}")
        if ram_used_mb < 0:
            raise ValueError(f"RAM used must be non-negative, got {ram_used_mb}")
        if cpu_percent < 0 or cpu_percent > 100:
            raise ValueError(f"CPU percent must be 0-100, got {cpu_percent}")
        self.tps = tps
        self.players = players
        self.ram_used_mb = ram_used_mb
        self.cpu_percent = cpu_percent
        self.timestamp = timestamp or datetime.now(timezone.utc)


class MetricSeries(AggregateRoot):
    def __init__(self, server_id: ServerId, max_points: int = 1000) -> None:
        super().__init__()
        self._server_id = server_id
        self._points: list[MetricPoint] = []
        self._max_points = max_points

    @property
    def server_id(self) -> ServerId:
        return self._server_id

    @property
    def points(self) -> list[MetricPoint]:
        return list(self._points)

    @property
    def latest(self) -> MetricPoint | None:
        return self._points[-1] if self._points else None

    def record(self, point: MetricPoint) -> None:
        self._points.append(point)
        if len(self._points) > self._max_points:
            self._points.pop(0)
        self._add_event(
            MetricRecordedEvent(
                server_id=str(self._server_id),
                metric_name="tps",
                value=point.tps,
            ),
        )


class AlertSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertCondition(Enum):
    GREATER_THAN = "gt"
    LESS_THAN = "lt"
    EQUAL = "eq"


import uuid


class AlertRule(AggregateRoot):
    def __init__(
        self,
        server_id: ServerId,
        metric_name: str,
        condition: AlertCondition,
        threshold: float,
        severity: AlertSeverity = AlertSeverity.WARNING,
        enabled: bool = True,
        cooldown_minutes: int = 15,
    ) -> None:
        super().__init__()
        self._alert_rule_id = uuid.uuid4().hex[:12]
        self._server_id = server_id
        self._metric_name = metric_name
        self._condition = condition
        self._threshold = threshold
        self._severity = severity
        self._enabled = enabled
        self._cooldown_minutes = cooldown_minutes
        self._last_triggered_at: datetime | None = None

    @property
    def server_id(self) -> ServerId:
        return self._server_id

    @property
    def metric_name(self) -> str:
        return self._metric_name

    @property
    def condition(self) -> AlertCondition:
        return self._condition

    @property
    def threshold(self) -> float:
        return self._threshold

    @property
    def severity(self) -> AlertSeverity:
        return self._severity

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def cooldown_minutes(self) -> int:
        return self._cooldown_minutes

    def evaluate(self, value: float) -> bool:
        if not self._enabled:
            return False
        if self._condition == AlertCondition.GREATER_THAN:
            return value > self._threshold
        if self._condition == AlertCondition.LESS_THAN:
            return value < self._threshold
        if self._condition == AlertCondition.EQUAL:
            return abs(value - self._threshold) < 0.001
        return False

    def trigger(self, value: float) -> None:
        now = datetime.now(timezone.utc)
        if self._last_triggered_at:
            elapsed = (now - self._last_triggered_at).total_seconds() / 60
            if elapsed < self._cooldown_minutes:
                return
        self._last_triggered_at = now
        self._add_event(
            AlertTriggeredEvent(
                alert_rule_id=self._alert_rule_id,
                server_id=str(self._server_id),
                metric_name=self._metric_name,
                value=value,
                threshold=self._threshold,
                severity=self._severity.value,
            ),
        )

    def resolve(self) -> None:
        self._add_event(
            AlertResolvedEvent(
                alert_rule_id=self._alert_rule_id,
                server_id=str(self._server_id),
            ),
        )
