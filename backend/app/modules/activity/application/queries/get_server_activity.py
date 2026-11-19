from __future__ import annotations

from dataclasses import dataclass

from app.core.query_bus import Query, QueryHandler
from app.modules.activity.domain.entities import ServerActivityLog
from app.modules.activity.domain.repository import ActivityRepository


class GetServerActivityQuery(Query):
    server_id: str
    limit: int = 50
    offset: int = 0
    event_type: str | None = None
    from_date: float | None = None
    to_date: float | None = None
    branch_name: str | None = None


@dataclass
class PaginatedActivityLogs:
    items: list[ServerActivityLog]
    total: int
    limit: int
    offset: int


class GetServerActivityHandler(QueryHandler[GetServerActivityQuery]):
    def __init__(self, repository: ActivityRepository | None = None) -> None:
        self._repository = repository

    async def handle(self, query: GetServerActivityQuery) -> PaginatedActivityLogs:
        repo = self._repository
        if repo is None:
            from app.modules.activity.infrastructure.repository import SQLActivityRepository

            repo = SQLActivityRepository()

        items, total = await repo.list_by_server(
            server_id=query.server_id,
            limit=query.limit,
            offset=query.offset,
            event_type=query.event_type,
            from_date=query.from_date,
            to_date=query.to_date,
            branch_name=query.branch_name,
        )
        return PaginatedActivityLogs(
            items=items,
            total=total,
            limit=query.limit,
            offset=query.offset,
        )
