from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class HealthStatusEnum(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    BROKEN = "broken"
    UNKNOWN = "unknown"
    PENDING = "pending"


class HealthTrend(str, Enum):
    IMPROVING = "improving"
    STABLE = "stable"
    DECLINING = "declining"


class SignalSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class HealthSignal:
    server_id: str
    signal_type: str
    severity: SignalSeverity
    value: str
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class IntegrityCheck:
    check_name: str
    severity: str
    status: str
    detail: str = ""


@dataclass(frozen=True)
class IntegrityReport:
    server_id: str
    checks: list[IntegrityCheck]
    overall_status: str
    scope: str = "full"
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def passed(self) -> bool:
        return self.overall_status == "pass"

    @property
    def has_warnings(self) -> bool:
        return self.overall_status == "warn"

    @property
    def has_failures(self) -> bool:
        return self.overall_status == "fail"


@dataclass(frozen=True)
class EnvironmentReport:
    java_versions: list[str] = field(default_factory=list)
    available_disk_mb: float = 0.0
    available_memory_mb: float = 0.0
    provider_ready: bool = False
    prerequisites: dict[str, bool] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_capable(self) -> bool:
        return self.provider_ready and not self.errors


@dataclass(frozen=True)
class EvidenceBundle:
    server_id: str
    evidence_id: str = ""
    latest_log_tail: list[str] = field(default_factory=list)
    crash_reports: list[dict[str, Any]] = field(default_factory=list)
    provider_diagnostics: dict[str, Any] | None = None
    system_snapshot: dict[str, Any] = field(default_factory=dict)
    collection_errors: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class CrashClassification:
    evidence_id: str
    failure_code: str
    confidence: float
    summary: str
    server_id: str = ""
    suggested_action: str = ""
    evidence_references: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class HealthTimelineEntry:
    server_id: str
    previous_status: HealthStatusEnum | None
    new_status: HealthStatusEnum
    contributing_factors: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
