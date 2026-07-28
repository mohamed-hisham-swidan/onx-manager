from __future__ import annotations

import pytest

from app.modules.health.domain.value_objects import (
    CrashClassification,
    EnvironmentReport,
    EvidenceBundle,
    HealthSignal,
    HealthStatusEnum,
    HealthTimelineEntry,
    HealthTrend,
    IntegrityCheck,
    IntegrityReport,
    SignalSeverity,
)


class TestHealthStatusEnum:
    def test_values(self) -> None:
        assert HealthStatusEnum.HEALTHY.value == "healthy"
        assert HealthStatusEnum.WARNING.value == "warning"
        assert HealthStatusEnum.CRITICAL.value == "critical"
        assert HealthStatusEnum.BROKEN.value == "broken"
        assert HealthStatusEnum.UNKNOWN.value == "unknown"
        assert HealthStatusEnum.PENDING.value == "pending"

    def test_transition_validity(self) -> None:
        assert HealthStatusEnum.HEALTHY != HealthStatusEnum.WARNING
        assert HealthStatusEnum.PENDING != HealthStatusEnum.HEALTHY


class TestHealthTrend:
    def test_values(self) -> None:
        assert HealthTrend.IMPROVING.value == "improving"
        assert HealthTrend.STABLE.value == "stable"
        assert HealthTrend.DECLINING.value == "declining"


class TestSignalSeverity:
    def test_values(self) -> None:
        assert SignalSeverity.INFO.value == "info"
        assert SignalSeverity.WARNING.value == "warning"
        assert SignalSeverity.CRITICAL.value == "critical"


class TestHealthSignal:
    def test_create(self) -> None:
        signal = HealthSignal(
            server_id="srv_1",
            signal_type="process",
            severity=SignalSeverity.CRITICAL,
            value="pid_not_found",
            details={"pid": 12345},
        )
        assert signal.server_id == "srv_1"
        assert signal.signal_type == "process"
        assert signal.severity == SignalSeverity.CRITICAL
        assert signal.value == "pid_not_found"
        assert signal.details == {"pid": 12345}
        assert signal.timestamp is not None


class TestIntegrityCheck:
    def test_create(self) -> None:
        check = IntegrityCheck(
            check_name="server_jar_exists",
            severity="critical",
            status="pass",
            detail="server.jar found at expected path",
        )
        assert check.check_name == "server_jar_exists"
        assert check.severity == "critical"
        assert check.status == "pass"


class TestIntegrityReport:
    def test_pass(self) -> None:
        checks = [IntegrityCheck("jar", "critical", "pass")]
        report = IntegrityReport(
            server_id="srv_1",
            checks=checks,
            overall_status="pass",
            scope="full",
        )
        assert report.passed is True
        assert report.has_warnings is False
        assert report.has_failures is False

    def test_warn(self) -> None:
        checks = [
            IntegrityCheck("jar", "critical", "pass"),
            IntegrityCheck("disk", "warning", "warn", "Low disk space"),
        ]
        report = IntegrityReport(server_id="srv_1", checks=checks, overall_status="warn")
        assert report.passed is False
        assert report.has_warnings is True
        assert report.has_failures is False

    def test_fail(self) -> None:
        checks = [IntegrityCheck("jar", "critical", "fail", "server.jar not found")]
        report = IntegrityReport(server_id="srv_1", checks=checks, overall_status="fail")
        assert report.passed is False
        assert report.has_failures is True


class TestEnvironmentReport:
    def test_defaults(self) -> None:
        report = EnvironmentReport()
        assert report.java_versions == []
        assert report.available_disk_mb == 0.0
        assert report.provider_ready is False
        assert report.errors == []
        assert report.is_capable is False

    def test_capable(self) -> None:
        report = EnvironmentReport(
            java_versions=["21.0.1"],
            available_disk_mb=10240,
            available_memory_mb=4096,
            provider_ready=True,
            prerequisites={"java": True, "tmux": True},
        )
        assert report.is_capable is True

    def test_not_capable_with_errors(self) -> None:
        report = EnvironmentReport(
            provider_ready=False,
            errors=["Java not found"],
        )
        assert report.is_capable is False


class TestEvidenceBundle:
    def test_create(self) -> None:
        bundle = EvidenceBundle(
            server_id="srv_1",
            evidence_id="ev_001",
            latest_log_tail=["line1", "line2"],
        )
        assert bundle.server_id == "srv_1"
        assert bundle.evidence_id == "ev_001"
        assert bundle.latest_log_tail == ["line1", "line2"]

    def test_defaults(self) -> None:
        bundle = EvidenceBundle(server_id="srv_1")
        assert bundle.latest_log_tail == []
        assert bundle.crash_reports == []
        assert bundle.system_snapshot == {}
        assert bundle.collection_errors == []


class TestCrashClassification:
    def test_create(self) -> None:
        classification = CrashClassification(
            evidence_id="ev_001",
            failure_code="MEMORY_EXHAUSTED",
            confidence=0.95,
            summary="OutOfMemoryError detected",
            suggested_action="Increase memory allocation",
        )
        assert classification.failure_code == "MEMORY_EXHAUSTED"
        assert classification.confidence == 0.95
        assert classification.summary == "OutOfMemoryError detected"


class TestHealthTimelineEntry:
    def test_create(self) -> None:
        entry = HealthTimelineEntry(
            server_id="srv_1",
            previous_status=HealthStatusEnum.PENDING,
            new_status=HealthStatusEnum.HEALTHY,
            contributing_factors=["all checks passed"],
        )
        assert entry.server_id == "srv_1"
        assert entry.previous_status == HealthStatusEnum.PENDING
        assert entry.new_status == HealthStatusEnum.HEALTHY
        assert entry.contributing_factors == ["all checks passed"]
