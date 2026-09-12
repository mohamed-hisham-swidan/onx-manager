from __future__ import annotations

import contextlib
import inspect
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.event_bus import DomainEvent, EventBus
from app.core.persistence.base import BaseRepository
from app.core.persistence.db import database

logger = logging.getLogger(__name__)


class UnitOfWork:
    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._session: AsyncSession | None = None
        self._event_bus = event_bus
        self._events: list[DomainEvent] = []
        self._repositories: dict[str, BaseRepository[Any]] = {}
        self._cleanups: list[Callable[[], Any]] = []

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("UnitOfWork not started. Use 'async with'.")
        return self._session

    def _get_or_create_repo(self, key: str, model: type[Any]) -> BaseRepository[Any]:
        if key not in self._repositories:
            self._repositories[key] = BaseRepository(self.session, model)
        return self._repositories[key]

    def defer_cleanup(self, fn: Callable[[], Any]) -> None:
        self._cleanups.append(fn)

    async def __aenter__(self) -> UnitOfWork:
        self._session = await database.session_factory().__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        try:
            if exc_type is not None:
                await self.rollback()
            else:
                await self.commit()
        finally:
            if self._session:
                await self._session.close()

    def add_event(self, event: DomainEvent) -> None:
        self._events.append(event)

    async def commit(self) -> None:
        if self._session:
            await self._session.commit()
        if self._event_bus and self._events:
            events_to_publish = list(self._events)
            self._events.clear()
            errors: list[Exception] = []
            for event in events_to_publish:
                try:
                    await self._event_bus.publish(event)
                except Exception as exc:
                    logger.error("Failed to publish domain event %s: %s", event, exc)
                    errors.append(exc)
            if errors:
                raise errors[0]

    async def rollback(self) -> None:
        if self._session:
            await self._session.rollback()
        self._events.clear()
        for fn in reversed(self._cleanups):
            with contextlib.suppress(Exception):
                res = fn()
                if inspect.isawaitable(res):
                    await res
        self._cleanups.clear()
