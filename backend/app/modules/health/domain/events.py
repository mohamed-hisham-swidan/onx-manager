from __future__ import annotations

from typing import Any

from app.core.event_bus import DomainEvent


class HealthStatusChangedEvent(DomainEvent):
    server_id: str
    previous_status: str
    new_status: str
    contributing_factors: list[str]
    trend: str

    def __init__(
        self,
        server_id: str,
        previous_status: str,
        new_status: str,
        contributing_factors: list[str] | None = None,
        trend: str = "stable",
        **data: Any,
    ) -> None:
        super().__init__(
            server_id=server_id,
            previous_status=previous_status,
            new_status=new_status,
            contributing_factors=contributing_factors or [],
            trend=trend,
            **data,
        )


class IntegrityCheckPassedEvent(DomainEvent):
    server_id: str
    check_name: str
    scope: str

    def __init__(self, server_id: str, check_name: str, scope: str = "full", **data: Any) -> None:
        super().__init__(server_id=server_id, check_name=check_name, scope=scope, **data)


class IntegrityCheckFailedEvent(DomainEvent):
    server_id: str
    check_name: str
    severity: str
    detail: str
    scope: str

    def __init__(
        self,
        server_id: str,
        check_name: str,
        severity: str,
        detail: str = "",
        scope: str = "full",
        **data: Any,
    ) -> None:
        super().__init__(
            server_id=server_id,
            check_name=check_name,
            severity=severity,
            detail=detail,
            scope=scope,
            **data,
        )


class EnvironmentDegradedEvent(DomainEvent):
    resource_type: str
    current_value: float
    threshold: float
    detail: str

    def __init__(
        self,
        resource_type: str,
        current_value: float,
        threshold: float,
        detail: str = "",
        **data: Any,
    ) -> None:
        super().__init__(
            resource_type=resource_type,
            current_value=current_value,
            threshold=threshold,
            detail=detail,
            **data,
        )


class StartupValidationPassedEvent(DomainEvent):
    server_id: str
    validation_scope: str

    def __init__(self, server_id: str, validation_scope: str = "full", **data: Any) -> None:
        super().__init__(server_id=server_id, validation_scope=validation_scope, **data)


class StartupValidationBlockedEvent(DomainEvent):
    server_id: str
    reasons: list[str]
    severity: str

    def __init__(
        self, server_id: str, reasons: list[str], severity: str = "critical", **data: Any
    ) -> None:
        super().__init__(server_id=server_id, reasons=reasons, severity=severity, **data)


class RuntimeHealthSignalEvent(DomainEvent):
    server_id: str
    signal_type: str
    severity: str
    value: str
    details: dict[str, Any] | None = None

    def __init__(
        self,
        server_id: str,
        signal_type: str,
        severity: str,
        value: str,
        details: dict[str, Any] | None = None,
        **data: Any,
    ) -> None:
        super().__init__(
            server_id=server_id,
            signal_type=signal_type,
            severity=severity,
            value=value,
            details=details,
            **data,
        )


class EvidenceCollectedEvent(DomainEvent):
    server_id: str
    evidence_id: str
    collection_errors: list[str]

    def __init__(
        self,
        server_id: str,
        evidence_id: str,
        collection_errors: list[str] | None = None,
        **data: Any,
    ) -> None:
        super().__init__(
            server_id=server_id,
            evidence_id=evidence_id,
            collection_errors=collection_errors or [],
            **data,
        )


class CrashClassifiedEvent(DomainEvent):
    server_id: str
    evidence_id: str
    failure_code: str
    confidence: float
    summary: str
    suggested_action: str

    def __init__(
        self,
        server_id: str,
        evidence_id: str,
        failure_code: str,
        confidence: float,
        summary: str,
        suggested_action: str = "",
        **data: Any,
    ) -> None:
        super().__init__(
            server_id=server_id,
            evidence_id=evidence_id,
            failure_code=failure_code,
            confidence=confidence,
            summary=summary,
            suggested_action=suggested_action,
            **data,
        )


class AlertTriggeredEvent(DomainEvent):
    server_id: str
    alert_type: str
    current_value: str
    threshold: str

    def __init__(
        self, server_id: str, alert_type: str, current_value: str, threshold: str, **data: Any
    ) -> None:
        super().__init__(
            server_id=server_id,
            alert_type=alert_type,
            current_value=current_value,
            threshold=threshold,
            **data,
        )


class RecoveryTriggeredEvent(DomainEvent):
    server_id: str
    recovery_action: str
    reason: str

    def __init__(self, server_id: str, recovery_action: str, reason: str, **data: Any) -> None:
        super().__init__(
            server_id=server_id, recovery_action=recovery_action, reason=reason, **data
        )


class RecoveryFailedEvent(DomainEvent):
    server_id: str
    recovery_action: str
    failure_reason: str

    def __init__(
        self, server_id: str, recovery_action: str, failure_reason: str, **data: Any
    ) -> None:
        super().__init__(
            server_id=server_id,
            recovery_action=recovery_action,
            failure_reason=failure_reason,
            **data,
        )


class RecoverySucceededEvent(DomainEvent):
    server_id: str
    recovery_action: str
    duration_seconds: float

    def __init__(
        self, server_id: str, recovery_action: str, duration_seconds: float = 0.0, **data: Any
    ) -> None:
        super().__init__(
            server_id=server_id,
            recovery_action=recovery_action,
            duration_seconds=duration_seconds,
            **data,
        )


class HealthReportGeneratedEvent(DomainEvent):
    server_id: str
    report_type: str

    def __init__(self, server_id: str, report_type: str, **data: Any) -> None:
        super().__init__(server_id=server_id, report_type=report_type, **data)
