from __future__ import annotations

from datetime import datetime

from app.core.persistence.db import database
from app.core.query_bus import Query, QueryHandler
from app.modules.health.infrastructure.repository import SQLHealthRepository


class HealthTimelineReadModel:
    def __init__(
        self,
        server_id: str,
        previous_status: str | None = None,
        new_status: str = "unknown",
        contributing_factors: list[str] | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        self.server_id = server_id
        self.previous_status = previous_status
        self.new_status = new_status
        self.contributing_factors = contributing_factors or []
        self.timestamp = timestamp


class GetHealthTimelineQuery(Query):
    server_id: str
    limit: int = 100
    since: datetime | None = None


class GetHealthTimelineHandler(QueryHandler[GetHealthTimelineQuery]):
    async def handle(self, query: GetHealthTimelineQuery) -> list[HealthTimelineReadModel]:
        async with database.session_factory() as session:
            repo = SQLHealthRepository(session)
            entries = await repo.get_timeline(
                server_id=query.server_id,
                limit=query.limit,
                since=query.since,
            )
            return [
                HealthTimelineReadModel(
                    server_id=e.server_id,
                    previous_status=e.previous_status.value if e.previous_status else None,
                    new_status=e.new_status.value,
                    contributing_factors=e.contributing_factors,
                    timestamp=e.timestamp,
                )
                for e in entries
            ]
