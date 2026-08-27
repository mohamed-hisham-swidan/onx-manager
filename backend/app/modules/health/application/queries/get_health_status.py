from __future__ import annotations

from datetime import datetime

from app.core.persistence.db import database
from app.core.query_bus import Query, QueryHandler
from app.modules.health.infrastructure.repository import SQLHealthRepository


class HealthStatusReadModel:
    def __init__(
        self,
        server_id: str,
        status: str,
        previous_status: str | None = None,
        contributing_factors: list[str] | None = None,
        trend: str = "stable",
        confidence: float = 0.0,
        last_updated: datetime | None = None,
    ) -> None:
        self.server_id = server_id
        self.status = status
        self.previous_status = previous_status
        self.contributing_factors = contributing_factors or []
        self.trend = trend
        self.confidence = confidence
        self.last_updated = last_updated


class GetHealthStatusQuery(Query):
    server_id: str


class GetHealthStatusHandler(QueryHandler[GetHealthStatusQuery]):
    async def handle(self, query: GetHealthStatusQuery) -> HealthStatusReadModel | None:
        async with database.session_factory() as session:
            repo = SQLHealthRepository(session)
            status = await repo.get(query.server_id)
            if status is None:
                return None
            return HealthStatusReadModel(
                server_id=status.server_id,
                status=status.classification.value,
                previous_status=status.previous_classification.value
                if status.previous_classification
                else None,
                contributing_factors=status.contributing_factors,
                trend=status.trend.value,
                confidence=status.confidence,
                last_updated=status.last_updated,
            )
