from __future__ import annotations

from app.core.query_bus import Query, QueryHandler
from app.modules.operations.application.services.operation_service import (
    OperationService,
    get_operation_service,
)
from app.modules.operations.domain.aggregate import Operation


class GetOperationQuery(Query):
    operation_id: str


class GetOperationHandler(QueryHandler[GetOperationQuery]):
    def __init__(self, operation_service: OperationService | None = None) -> None:
        self._service = operation_service or get_operation_service()

    async def handle(self, query: GetOperationQuery) -> Operation:
        return await self._service.get_operation(query.operation_id)


class ListOperationsQuery(Query):
    target_type: str | None = None
    target_id: str | None = None
    status: str | None = None
    limit: int = 50


class ListOperationsHandler(QueryHandler[ListOperationsQuery]):
    def __init__(self, operation_service: OperationService | None = None) -> None:
        self._service = operation_service or get_operation_service()

    async def handle(self, query: ListOperationsQuery) -> list[Operation]:
        return await self._service.list_operations(
            target_type=query.target_type,
            target_id=query.target_id,
            status=query.status,
            limit=query.limit,
        )
