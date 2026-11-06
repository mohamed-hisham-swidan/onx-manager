from __future__ import annotations

from datetime import UTC, datetime

from app.core.persistence.db import database
from app.core.query_bus import Query, QueryHandler
from app.modules.health.domain.value_objects import HealthStatusEnum
from app.modules.health.infrastructure.health_calculator import SignalHealthCalculator
from app.modules.health.infrastructure.repository import SQLHealthRepository


class HealthReportReadModel:
    def __init__(
        self,
        server_id: str,
        current_status: str,
        uptime_percentage: float = 0.0,
        crash_count: int = 0,
        total_entries: int = 0,
        time_window_hours: float = 0.0,
        trend: str = "stable",
        confidence: float = 0.0,
        worst_status: str = "unknown",
        contributing_factors: list[str] | None = None,
    ) -> None:
        self.server_id = server_id
        self.current_status = current_status
        self.uptime_percentage = uptime_percentage
        self.crash_count = crash_count
        self.total_entries = total_entries
        self.time_window_hours = time_window_hours
        self.trend = trend
        self.confidence = confidence
        self.worst_status = worst_status
        self.contributing_factors = contributing_factors or []


class GenerateHealthReportQuery(Query):
    server_id: str
    hours: float = 24.0


class GenerateHealthReportHandler(QueryHandler[GenerateHealthReportQuery]):
    async def handle(self, query: GenerateHealthReportQuery) -> HealthReportReadModel | None:
        since = datetime.now(UTC).timestamp() - (query.hours * 3600)
        since_dt = datetime.fromtimestamp(since, tz=UTC)

        async with database.session_factory() as session:
            repo = SQLHealthRepository(session)

            status = await repo.get(query.server_id)
            if status is None:
                return None

            timeline = await repo.get_timeline(
                server_id=query.server_id,
                limit=1000,
                since=since_dt,
            )

            total_entries = len(timeline)
            crash_count = sum(1 for e in timeline if e.new_status == HealthStatusEnum.CRITICAL)
            broken_count = sum(1 for e in timeline if e.new_status == HealthStatusEnum.BROKEN)

            healthy_count = sum(1 for e in timeline if e.new_status == HealthStatusEnum.HEALTHY)
            healthy_weighted = healthy_count * 1.0
            uptime_pct = 0.0
            if total_entries > 0:
                uptime_pct = (healthy_weighted / max(total_entries, 1)) * 100

            worst = timeline[0].new_status if timeline else status.classification
            for e in timeline[1:]:
                es = e.new_status
                if SignalHealthCalculator.status_score(es) > SignalHealthCalculator.status_score(
                    worst
                ):
                    worst = es

        return HealthReportReadModel(
            server_id=query.server_id,
            current_status=status.classification.value,
            uptime_percentage=round(uptime_pct, 1),
            crash_count=crash_count + broken_count,
            total_entries=total_entries,
            time_window_hours=query.hours,
            trend=status.trend.value,
            confidence=status.confidence,
            worst_status=worst.value,
            contributing_factors=status.contributing_factors,
        )
