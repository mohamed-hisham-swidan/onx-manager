from __future__ import annotations

from app.modules.health.domain.events import (
    AlertTriggeredEvent,
    CrashClassifiedEvent,
    EnvironmentDegradedEvent,
    EvidenceCollectedEvent,
    HealthReportGeneratedEvent,
    HealthStatusChangedEvent,
    IntegrityCheckFailedEvent,
    IntegrityCheckPassedEvent,
    RecoveryFailedEvent,
    RecoverySucceededEvent,
    RecoveryTriggeredEvent,
    RuntimeHealthSignalEvent,
    StartupValidationBlockedEvent,
    StartupValidationPassedEvent,
)


def assert_event_fields(event, expected: dict) -> None:
    for key, value in expected.items():
        assert getattr(event, key, None) == value, f"Field {key!r} expected {value!r}, got {getattr(event, key, None)!r}"


class TestHealthStatusChangedEvent:
    def test_create(self) -> None:
        event = HealthStatusChangedEvent(
            server_id="srv_1",
            previous_status="pending",
            new_status="healthy",
            contributing_factors=["all ok"],
            trend="improving",
        )
        assert event.server_id == "srv_1"
        assert event.previous_status == "pending"
        assert event.new_status == "healthy"
        assert event.contributing_factors == ["all ok"]
        assert event.trend == "improving"
        assert event.event_id
        assert event.timestamp > 0


class TestIntegrityCheckEvents:
    def test_passed(self) -> None:
        event = IntegrityCheckPassedEvent(server_id="srv_1", check_name="jar_exists", scope="quick")
        assert_event_fields(event, {"server_id": "srv_1", "check_name": "jar_exists", "scope": "quick"})

    def test_failed(self) -> None:
        event = IntegrityCheckFailedEvent(
            server_id="srv_1",
            check_name="jar_exists",
            severity="critical",
            detail="server.jar not found",
            scope="full",
        )
        assert_event_fields(event, {
            "server_id": "srv_1",
            "check_name": "jar_exists",
            "severity": "critical",
            "detail": "server.jar not found",
            "scope": "full",
        })


class TestEnvironmentDegradedEvent:
    def test_create(self) -> None:
        event = EnvironmentDegradedEvent(
            resource_type="disk_space",
            current_value=0.3,
            threshold=1.0,
            detail="Less than 1GB available",
        )
        assert_event_fields(event, {
            "resource_type": "disk_space",
            "current_value": 0.3,
            "threshold": 1.0,
            "detail": "Less than 1GB available",
        })


class TestStartupValidationEvents:
    def test_passed(self) -> None:
        event = StartupValidationPassedEvent(server_id="srv_1", validation_scope="full")
        assert_event_fields(event, {"server_id": "srv_1", "validation_scope": "full"})

    def test_blocked(self) -> None:
        event = StartupValidationBlockedEvent(
            server_id="srv_1",
            reasons=["Port 25565 already in use", "Insufficient memory"],
            severity="critical",
        )
        assert_event_fields(event, {
            "server_id": "srv_1",
            "reasons": ["Port 25565 already in use", "Insufficient memory"],
            "severity": "critical",
        })


class TestRuntimeHealthSignalEvent:
    def test_create(self) -> None:
        event = RuntimeHealthSignalEvent(
            server_id="srv_1",
            signal_type="process",
            severity="critical",
            value="not_found",
            details={"pid": 12345},
        )
        assert_event_fields(event, {
            "server_id": "srv_1",
            "signal_type": "process",
            "severity": "critical",
            "value": "not_found",
        })
        assert event.details == {"pid": 12345}


class TestEvidenceEvents:
    def test_collected(self) -> None:
        event = EvidenceCollectedEvent(
            server_id="srv_1",
            evidence_id="ev_001",
            collection_errors=["crash-reports dir missing"],
        )
        assert_event_fields(event, {
            "server_id": "srv_1",
            "evidence_id": "ev_001",
            "collection_errors": ["crash-reports dir missing"],
        })

    def test_classified(self) -> None:
        event = CrashClassifiedEvent(
            server_id="srv_1",
            evidence_id="ev_001",
            failure_code="MEMORY_EXHAUSTED",
            confidence=0.95,
            summary="OutOfMemoryError detected",
            suggested_action="Increase memory allocation",
        )
        assert_event_fields(event, {
            "server_id": "srv_1",
            "evidence_id": "ev_001",
            "failure_code": "MEMORY_EXHAUSTED",
            "confidence": 0.95,
            "summary": "OutOfMemoryError detected",
            "suggested_action": "Increase memory allocation",
        })


class TestRecoveryEvents:
    def test_triggered(self) -> None:
        event = RecoveryTriggeredEvent(
            server_id="srv_1",
            recovery_action="restart",
            reason="Crash detected with auto-restart enabled",
        )
        assert_event_fields(event, {"server_id": "srv_1", "recovery_action": "restart"})

    def test_failed(self) -> None:
        event = RecoveryFailedEvent(
            server_id="srv_1",
            recovery_action="restart",
            failure_reason="Max restart attempts exceeded",
        )
        assert_event_fields(event, {"server_id": "srv_1", "failure_reason": "Max restart attempts exceeded"})

    def test_succeeded(self) -> None:
        event = RecoverySucceededEvent(
            server_id="srv_1",
            recovery_action="restart",
            duration_seconds=12.5,
        )
        assert_event_fields(event, {"server_id": "srv_1", "recovery_action": "restart", "duration_seconds": 12.5})


class TestHealthReportGeneratedEvent:
    def test_create(self) -> None:
        event = HealthReportGeneratedEvent(server_id="srv_1", report_type="daily")
        assert_event_fields(event, {"server_id": "srv_1", "report_type": "daily"})


class TestAlertTriggeredEvent:
    def test_create(self) -> None:
        event = AlertTriggeredEvent(
            server_id="srv_1",
            alert_type="cpu_usage",
            current_value="95%",
            threshold="90%",
        )
        assert_event_fields(event, {"server_id": "srv_1", "alert_type": "cpu_usage", "current_value": "95%", "threshold": "90%"})
