from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.health.domain.aggregate import DiagnosticsReport, HealthStatus
from app.modules.health.domain.repository import DiagnosticsRepository, HealthRepository
from app.modules.health.domain.value_objects import (
    CrashClassification,
    EvidenceBundle,
    HealthStatusEnum,
    HealthTimelineEntry,
    HealthTrend,
)
from app.modules.health.infrastructure.models import (
    DiagnosticsReportModel,
    EvidenceBundleModel,
    HealthStatusModel,
    HealthTimelineModel,
)


class SQLHealthRepository(HealthRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, server_id: str) -> HealthStatus | None:
        model = await self._session.get(HealthStatusModel, server_id)
        if model is None:
            return None
        return self._model_to_domain(model)

    async def save(self, status: HealthStatus) -> None:
        model = await self._session.get(HealthStatusModel, status.server_id)
        if model is None:
            model = HealthStatusModel(server_id=status.server_id)
            self._session.add(model)

        model.classification = status.classification.value
        model.previous_classification = (
            status.previous_classification.value if status.previous_classification else None
        )
        model.contributing_factors = json.dumps(status.contributing_factors)
        model.trend = status.trend.value
        model.confidence = status.confidence
        model.last_updated = status.last_updated
        await self._session.flush()

    async def list_all(self) -> list[HealthStatus]:
        stmt = select(HealthStatusModel).order_by(HealthStatusModel.last_updated.desc())
        result = await self._session.execute(stmt)
        return [self._model_to_domain(m) for m in result.scalars().all()]

    async def list_by_classification(self, classification: str) -> list[HealthStatus]:
        stmt = (
            select(HealthStatusModel)
            .where(HealthStatusModel.classification == classification)
            .order_by(HealthStatusModel.last_updated.desc())
        )
        result = await self._session.execute(stmt)
        return [self._model_to_domain(m) for m in result.scalars().all()]

    async def append_timeline(self, entry: HealthTimelineEntry) -> None:
        model = HealthTimelineModel(
            server_id=entry.server_id,
            previous_status=entry.previous_status.value if entry.previous_status else None,
            new_status=entry.new_status.value,
            contributing_factors=json.dumps(entry.contributing_factors),
            entry_timestamp=entry.timestamp,
        )
        self._session.add(model)
        await self._session.flush()

    async def get_timeline(
        self,
        server_id: str,
        limit: int = 100,
        since: datetime | None = None,
    ) -> list[HealthTimelineEntry]:
        stmt = (
            select(HealthTimelineModel)
            .where(HealthTimelineModel.server_id == server_id)
            .order_by(HealthTimelineModel.entry_timestamp.desc(), HealthTimelineModel.id.desc())
            .limit(limit)
        )
        if since:
            stmt = stmt.where(HealthTimelineModel.entry_timestamp >= since)
        result = await self._session.execute(stmt)
        return [self._timeline_model_to_domain(m) for m in result.scalars().all()]

    async def get_timeline_by_status(
        self,
        status: str,
        limit: int = 100,
    ) -> list[HealthTimelineEntry]:
        stmt = (
            select(HealthTimelineModel)
            .where(HealthTimelineModel.new_status == status)
            .order_by(HealthTimelineModel.entry_timestamp.desc(), HealthTimelineModel.id.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [self._timeline_model_to_domain(m) for m in result.scalars().all()]

    def _model_to_domain(self, model: HealthStatusModel) -> HealthStatus:
        factors: list[str] = []
        if model.contributing_factors:
            try:
                factors = json.loads(model.contributing_factors)
            except (json.JSONDecodeError, TypeError):
                factors = []
        prev: HealthStatusEnum | None = None
        if model.previous_classification:
            try:
                prev = HealthStatusEnum(model.previous_classification)
            except ValueError:
                prev = None
        return HealthStatus(
            server_id=model.server_id,
            classification=HealthStatusEnum(model.classification),
            previous_classification=prev,
            contributing_factors=factors,
            trend=HealthTrend(model.trend),
            confidence=model.confidence,
            last_updated=model.last_updated,
        )

    def _timeline_model_to_domain(self, model: HealthTimelineModel) -> HealthTimelineEntry:
        factors: list[str] = []
        if model.contributing_factors:
            try:
                factors = json.loads(model.contributing_factors)
            except (json.JSONDecodeError, TypeError):
                factors = []
        prev: HealthStatusEnum | None = None
        if model.previous_status:
            try:
                prev = HealthStatusEnum(model.previous_status)
            except ValueError:
                prev = None
        return HealthTimelineEntry(
            server_id=model.server_id,
            previous_status=prev,
            new_status=HealthStatusEnum(model.new_status),
            contributing_factors=factors,
            timestamp=model.entry_timestamp,
        )


class SQLDiagnosticsRepository(DiagnosticsRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_evidence(self, bundle: EvidenceBundle) -> None:
        model = EvidenceBundleModel(
            id=bundle.evidence_id,
            server_id=bundle.server_id,
            latest_log_tail=json.dumps(bundle.latest_log_tail) if bundle.latest_log_tail else None,
            crash_reports=json.dumps(bundle.crash_reports) if bundle.crash_reports else None,
            provider_diagnostics=json.dumps(bundle.provider_diagnostics)
            if bundle.provider_diagnostics
            else None,
            system_snapshot=json.dumps(bundle.system_snapshot) if bundle.system_snapshot else None,
            collection_errors=json.dumps(bundle.collection_errors)
            if bundle.collection_errors
            else None,
            recorded_at=bundle.timestamp,
        )
        self._session.add(model)
        await self._session.flush()

    async def save_classification(
        self,
        classification: CrashClassification,
        server_id: str | None = None,
    ) -> None:
        effective_server_id = server_id or getattr(classification, "server_id", None)
        if not effective_server_id:
            ev = await self._session.get(EvidenceBundleModel, classification.evidence_id)
            if ev:
                effective_server_id = ev.server_id
        model = DiagnosticsReportModel(
            id=classification.evidence_id,
            server_id=effective_server_id or classification.evidence_id,
            evidence_id=classification.evidence_id,
            failure_code=classification.failure_code,
            confidence=classification.confidence,
            summary=classification.summary,
            suggested_action=classification.suggested_action,
            recorded_at=classification.timestamp,
        )
        self._session.add(model)
        await self._session.flush()

    async def save_report(self, report: DiagnosticsReport) -> None:
        model = DiagnosticsReportModel(
            id=report.report_id,
            server_id=report.server_id,
            evidence_id=report.evidence.evidence_id if report.evidence else None,
            failure_code=report.classification.failure_code if report.classification else None,
            confidence=report.classification.confidence if report.classification else None,
            summary=report.classification.summary if report.classification else None,
            suggested_action=report.classification.suggested_action
            if report.classification
            else None,
            recorded_at=report.created_at,
        )
        self._session.add(model)
        await self._session.flush()

    async def get_report(self, report_id: str) -> DiagnosticsReport | None:
        model = await self._session.get(DiagnosticsReportModel, report_id)
        if model is None:
            return None
        return self._model_to_domain(model)

    async def list_reports(
        self,
        server_id: str,
        limit: int = 50,
    ) -> list[DiagnosticsReport]:
        stmt = (
            select(DiagnosticsReportModel)
            .where(DiagnosticsReportModel.server_id == server_id)
            .order_by(DiagnosticsReportModel.recorded_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [self._model_to_domain(m) for m in result.scalars().all()]

    def _model_to_domain(self, model: DiagnosticsReportModel) -> DiagnosticsReport:
        classification: CrashClassification | None = None
        if model.failure_code:
            classification = CrashClassification(
                evidence_id=model.evidence_id or model.id,
                server_id=model.server_id or "",
                failure_code=model.failure_code,
                confidence=model.confidence or 0.0,
                summary=model.summary or "",
                suggested_action=model.suggested_action or "",
                timestamp=model.recorded_at,
            )
        return DiagnosticsReport(
            server_id=model.server_id,
            report_id=model.id,
            classification=classification,
            created_at=model.recorded_at,
        )
