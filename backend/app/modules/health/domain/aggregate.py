from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.modules.health.domain.events import (
    CrashClassifiedEvent,
    EvidenceCollectedEvent,
    HealthStatusChangedEvent,
)
from app.modules.health.domain.value_objects import (
    CrashClassification,
    EvidenceBundle,
    HealthStatusEnum,
    HealthTimelineEntry,
    HealthTrend,
)
from app.modules.shared.aggregate import AggregateRoot


class HealthStatus(AggregateRoot):
    def __init__(
        self,
        server_id: str,
        classification: HealthStatusEnum = HealthStatusEnum.PENDING,
        previous_classification: HealthStatusEnum | None = None,
        contributing_factors: list[str] | None = None,
        trend: HealthTrend = HealthTrend.STABLE,
        confidence: float = 0.0,
        last_updated: datetime | None = None,
    ) -> None:
        super().__init__()
        self._server_id = server_id
        self._classification = classification
        self._previous_classification = previous_classification
        self._contributing_factors = contributing_factors or []
        self._trend = trend
        self._confidence = confidence
        self._last_updated = last_updated or datetime.now(timezone.utc)

    @property
    def server_id(self) -> str:
        return self._server_id

    @property
    def classification(self) -> HealthStatusEnum:
        return self._classification

    @property
    def previous_classification(self) -> HealthStatusEnum | None:
        return self._previous_classification

    @property
    def contributing_factors(self) -> list[str]:
        return list(self._contributing_factors)

    @property
    def trend(self) -> HealthTrend:
        return self._trend

    @property
    def confidence(self) -> float:
        return self._confidence

    @property
    def last_updated(self) -> datetime:
        return self._last_updated

    def update(
        self,
        new_classification: HealthStatusEnum,
        contributing_factors: list[str] | None = None,
        trend: HealthTrend = HealthTrend.STABLE,
        confidence: float = 0.0,
    ) -> None:
        if new_classification == self._classification and not contributing_factors:
            return

        self._previous_classification = self._classification
        old_status = self._classification
        self._classification = new_classification
        self._contributing_factors = contributing_factors or self._contributing_factors
        self._trend = trend
        self._confidence = confidence
        self._last_updated = datetime.now(timezone.utc)

        if new_classification != old_status:
            self._add_event(
                HealthStatusChangedEvent(
                    server_id=self._server_id,
                    previous_status=old_status.value,
                    new_status=new_classification.value,
                    contributing_factors=self._contributing_factors,
                    trend=trend.value,
                ),
            )

    def reset(self) -> None:
        self._classification = HealthStatusEnum.PENDING
        self._previous_classification = None
        self._contributing_factors = []
        self._trend = HealthTrend.STABLE
        self._confidence = 0.0
        self._last_updated = datetime.now(timezone.utc)

    def to_timeline_entry(self) -> HealthTimelineEntry:
        return HealthTimelineEntry(
            server_id=self._server_id,
            previous_status=self._previous_classification,
            new_status=self._classification,
            contributing_factors=self._contributing_factors,
            timestamp=self._last_updated,
        )

    @classmethod
    def create(cls, server_id: str) -> HealthStatus:
        return cls(
            server_id=server_id,
            classification=HealthStatusEnum.PENDING,
            confidence=0.0,
        )


class DiagnosticsReport(AggregateRoot):
    def __init__(
        self,
        server_id: str,
        report_id: str | None = None,
        evidence: EvidenceBundle | None = None,
        classification: CrashClassification | None = None,
        created_at: datetime | None = None,
    ) -> None:
        super().__init__()
        self._report_id = report_id or uuid.uuid4().hex
        self._server_id = server_id
        self._evidence = evidence
        self._classification = classification
        self._created_at = created_at or datetime.now(timezone.utc)

    @property
    def report_id(self) -> str:
        return self._report_id

    @property
    def server_id(self) -> str:
        return self._server_id

    @property
    def evidence(self) -> EvidenceBundle | None:
        return self._evidence

    @property
    def classification(self) -> CrashClassification | None:
        return self._classification

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @classmethod
    def create_from_evidence(cls, server_id: str, evidence: EvidenceBundle) -> DiagnosticsReport:
        report = cls(server_id=server_id, evidence=evidence)
        report._add_event(
            EvidenceCollectedEvent(
                server_id=server_id,
                evidence_id=evidence.evidence_id,
                collection_errors=evidence.collection_errors,
            ),
        )
        return report

    def classify(self, classification: CrashClassification) -> None:
        self._classification = classification
        self._add_event(
            CrashClassifiedEvent(
                server_id=self._server_id,
                evidence_id=classification.evidence_id,
                failure_code=classification.failure_code,
                confidence=classification.confidence,
                summary=classification.summary,
                suggested_action=classification.suggested_action,
            ),
        )
