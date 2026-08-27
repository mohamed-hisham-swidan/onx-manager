from datetime import datetime

from app.core.persistence.db import database
from app.core.query_bus import Query, QueryHandler
from app.modules.monitoring.infrastructure.repository import SQLMetricRepository
from app.modules.shared.value_objects import ServerId


class MetricPointReadModel:
    def __init__(
        self,
        tps: float,
        players: int,
        ram_used_mb: float,
        cpu_percent: float,
        timestamp: datetime,
    ) -> None:
        self.tps = tps
        self.players = players
        self.ram_used_mb = ram_used_mb
        self.cpu_percent = cpu_percent
        self.timestamp = timestamp


class GetMetricsQuery(Query):
    server_id: str
    limit: int = 100
    since: datetime | None = None


class GetMetricsHandler(QueryHandler[GetMetricsQuery]):
    async def handle(self, query: GetMetricsQuery) -> list[MetricPointReadModel]:
        server_id = ServerId(query.server_id)
        async with database.session_factory() as session:
            repo = SQLMetricRepository(session)
            points = await repo.get_series(
                server_id=server_id,
                limit=query.limit,
                since=query.since,
            )
            return [
                MetricPointReadModel(
                    tps=p.tps,
                    players=p.players,
                    ram_used_mb=p.ram_used_mb,
                    cpu_percent=p.cpu_percent,
                    timestamp=p.timestamp,
                )
                for p in points
            ]
