from __future__ import annotations

from app.modules.health.domain.aggregate import DiagnosticsReport, HealthStatus
from app.modules.health.domain.events import (
    CrashClassifiedEvent,
    EvidenceCollectedEvent,
    HealthStatusChangedEvent,
)
from app.modules.health.domain.value_objects import (
    CrashClassification,
    EvidenceBundle,
    HealthStatusEnum,
    HealthTrend,
)


class TestHealthStatus:
    def test_create(self) -> None:
        status = HealthStatus.create("srv_abc123")
        assert status.server_id == "srv_abc123"
        assert status.classification == HealthStatusEnum.PENDING
        assert status.previous_classification is None
        assert status.contributing_factors == []
        assert status.trend == HealthTrend.STABLE
        assert status.confidence == 0.0

    def test_initial_no_events(self) -> None:
        status = HealthStatus.create("srv_abc123")
        events = status.collect_events()
        assert len(events) == 0

    def test_update_same_classification_no_event(self) -> None:
        status = HealthStatus.create("srv_abc123")
        status.update(
            new_classification=HealthStatusEnum.PENDING,
            contributing_factors=["checking"],
        )
        events = status.collect_events()
        assert len(events) == 0

    def test_update_triggers_event_on_change(self) -> None:
        status = HealthStatus.create("srv_abc123")
        status.update(
            new_classification=HealthStatusEnum.HEALTHY,
            contributing_factors=["All checks passed"],
            trend=HealthTrend.IMPROVING,
            confidence=0.95,
        )
        assert status.classification == HealthStatusEnum.HEALTHY
        assert status.previous_classification == HealthStatusEnum.PENDING
        assert status.contributing_factors == ["All checks passed"]
        assert status.trend == HealthTrend.IMPROVING
        assert status.confidence == 0.95

        events = status.collect_events()
        assert len(events) == 1
        event = events[0]
        assert isinstance(event, HealthStatusChangedEvent)
        assert event.server_id == "srv_abc123"
        assert event.previous_status == "pending"
        assert event.new_status == "healthy"
        assert event.contributing_factors == ["All checks passed"]
        assert event.trend == "improving"

    def test_multiple_updates_track_history(self) -> None:
        status = HealthStatus.create("srv_abc123")
        status.update(new_classification=HealthStatusEnum.HEALTHY, contributing_factors=["ok"])
        status.collect_events()

        status.update(
            new_classification=HealthStatusEnum.WARNING, contributing_factors=["high memory"]
        )
        assert status.previous_classification == HealthStatusEnum.HEALTHY
        assert status.classification == HealthStatusEnum.WARNING

    def test_reset(self) -> None:
        status = HealthStatus.create("srv_abc123")
        status.update(new_classification=HealthStatusEnum.HEALTHY, contributing_factors=["ok"])
        status.collect_events()

        status.reset()
        assert status.classification == HealthStatusEnum.PENDING
        assert status.previous_classification is None
        assert status.contributing_factors == []
        assert status.trend == HealthTrend.STABLE
        assert status.confidence == 0.0

    def test_to_timeline_entry(self) -> None:
        status = HealthStatus.create("srv_abc123")
        status.update(new_classification=HealthStatusEnum.HEALTHY, contributing_factors=["ok"])
        entry = status.to_timeline_entry()
        assert entry.server_id == "srv_abc123"
        assert entry.previous_status == HealthStatusEnum.PENDING
        assert entry.new_status == HealthStatusEnum.HEALTHY
        assert entry.contributing_factors == ["ok"]

    def test_update_no_factors_keeps_existing(self) -> None:
        status = HealthStatus.create("srv_abc123")
        status.update(
            new_classification=HealthStatusEnum.WARNING, contributing_factors=["disk full"]
        )
        status.collect_events()

        status.update(new_classification=HealthStatusEnum.CRITICAL)
        assert status.contributing_factors == ["disk full"]


class TestDiagnosticsReport:
    def test_create_from_evidence(self) -> None:
        evidence = EvidenceBundle(
            server_id="srv_abc123",
            evidence_id="ev_001",
            latest_log_tail=["line1", "line2"],
        )
        report = DiagnosticsReport.create_from_evidence("srv_abc123", evidence)
        assert report.server_id == "srv_abc123"
        assert report.evidence is not None
        assert report.evidence.evidence_id == "ev_001"
        assert report.classification is None

        events = report.collect_events()
        assert len(events) == 1
        assert isinstance(events[0], EvidenceCollectedEvent)
        assert events[0].evidence_id == "ev_001"

    def test_classify(self) -> None:
        evidence = EvidenceBundle(
            server_id="srv_abc123",
            evidence_id="ev_001",
            latest_log_tail=["OutOfMemoryError"],
        )
        report = DiagnosticsReport.create_from_evidence("srv_abc123", evidence)
        report.collect_events()

        classification = CrashClassification(
            evidence_id="ev_001",
            failure_code="MEMORY_EXHAUSTED",
            confidence=0.95,
            summary="OutOfMemoryError detected in server logs",
            suggested_action="Increase memory allocation or add swap space",
        )
        report.classify(classification)
        assert report.classification is not None
        assert report.classification.failure_code == "MEMORY_EXHAUSTED"
        assert report.classification.confidence == 0.95

        events = report.collect_events()
        assert len(events) == 1
        assert isinstance(events[0], CrashClassifiedEvent)
        assert events[0].failure_code == "MEMORY_EXHAUSTED"
        assert events[0].confidence == 0.95

    def test_report_id_unique(self) -> None:
        r1 = DiagnosticsReport(server_id="srv_a")
        r2 = DiagnosticsReport(server_id="srv_a")
        assert r1.report_id != r2.report_id
