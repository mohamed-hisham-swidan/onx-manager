from __future__ import annotations

from typing import Any

from app.core.event_bus import DomainEvent


class MetricRecordedEvent(DomainEvent):
    server_id: str
    metric_name: str
    value: float

    def __init__(self, server_id: str, metric_name: str, value: float, **data: Any) -> None:
        super().__init__(server_id=server_id, metric_name=metric_name, value=value, **data)


class AlertTriggeredEvent(DomainEvent):
    alert_rule_id: str
    server_id: str
    metric_name: str
    value: float
    threshold: float
    severity: str

    def __init__(self, alert_rule_id: str, server_id: str, metric_name: str, value: float, threshold: float, severity: str, **data: Any) -> None:
        super().__init__(
            alert_rule_id=alert_rule_id,
            server_id=server_id,
            metric_name=metric_name,
            value=value,
            threshold=threshold,
            severity=severity,
            **data,
        )


class AlertResolvedEvent(DomainEvent):
    alert_rule_id: str
    server_id: str

    def __init__(self, alert_rule_id: str, server_id: str, **data: Any) -> None:
        super().__init__(alert_rule_id=alert_rule_id, server_id=server_id, **data)
