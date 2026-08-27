from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from app.core.exceptions import MCSError

logger = logging.getLogger(__name__)


class Query(BaseModel):
    pass


TQuery = TypeVar("TQuery", bound=Query)


class QueryHandler(ABC, Generic[TQuery]):
    @abstractmethod
    async def handle(self, query: TQuery) -> Any: ...


class QueryMiddleware(ABC):
    @abstractmethod
    async def __call__(
        self,
        query: Query,
        next_middleware: Any,
    ) -> Any: ...


class QueryBus:
    def __init__(self) -> None:
        self._handlers: dict[type[Query], QueryHandler] = {}
        self._middleware: list[QueryMiddleware] = []

    def register(self, query_type: type[Query], handler: QueryHandler) -> None:
        self._handlers[query_type] = handler

    def add_middleware(self, middleware: QueryMiddleware) -> None:
        self._middleware.append(middleware)

    async def ask(self, query: Query) -> Any:
        handler = self._handlers.get(type(query))
        if handler is None:
            raise MCSError(
                f"No handler registered for {type(query).__name__}",
                code="HANDLER_NOT_FOUND",
                http_status=500,
            )

        async def final_handler(q: Query) -> Any:
            return await handler.handle(q)

        async def chain(q: Query, idx: int) -> Any:
            if idx < len(self._middleware):
                return await self._middleware[idx](q, lambda c: chain(c, idx + 1))
            return await final_handler(q)

        return await chain(query, 0)
