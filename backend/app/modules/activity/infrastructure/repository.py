from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.activity.domain.entities import ServerActivityLog
from app.modules.activity.domain.repository import ActivityRepository
from app.modules.activity.infrastructure.models import ServerActivityLogModel


class SQLActivityRepository(ActivityRepository):
    """SQLAlchemy implementation of ActivityRepository."""

    def __init__(
        self,
        session: AsyncSession | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._session = session
        self._session_factory = session_factory

    @asynccontextmanager
    async def _get_session(self) -> AsyncGenerator[AsyncSession, None]:
        if self._session is not None:
            yield self._session
        elif self._session_factory is not None:
            async with self._session_factory() as s:
                yield s
        else:
            from app.core.persistence.db import database

            async with database.session_factory() as s:
                yield s

    async def save(self, log: ServerActivityLog) -> None:
        details_str = json.dumps(log.details) if log.details else None
        model = ServerActivityLogModel(
            id=log.id,
            server_id=log.server_id,
            timestamp=log.timestamp,
            event_type=log.event_type,
            actor_type=log.actor_type,
            actor_id=log.actor_id,
            summary=log.summary,
            details_json=details_str,
        )
        async with self._get_session() as s:
            s.add(model)
            await s.commit()

    async def list_by_server(
        self,
        server_id: str,
        limit: int = 50,
        offset: int = 0,
        event_type: str | None = None,
        from_date: float | None = None,
        to_date: float | None = None,
    ) -> tuple[list[ServerActivityLog], int]:
        filters: list[Any] = [ServerActivityLogModel.server_id == server_id]
        if event_type:
            filters.append(ServerActivityLogModel.event_type == event_type)
        if from_date is not None:
            filters.append(ServerActivityLogModel.timestamp >= from_date)
        if to_date is not None:
            filters.append(ServerActivityLogModel.timestamp <= to_date)

        async with self._get_session() as s:
            count_stmt = select(func.count()).select_from(ServerActivityLogModel).where(*filters)
            count_res = await s.execute(count_stmt)
            total = count_res.scalar_one() or 0

            stmt = (
                select(ServerActivityLogModel)
                .where(*filters)
                .order_by(desc(ServerActivityLogModel.timestamp))
                .limit(limit)
                .offset(offset)
            )
            res = await s.execute(stmt)
            models = res.scalars().all()
            items = [self._model_to_domain(m) for m in models]
            return items, total

    async def delete_older_than(self, cutoff_timestamp: float) -> int:
        stmt = delete(ServerActivityLogModel).where(
            ServerActivityLogModel.timestamp < cutoff_timestamp
        )
        async with self._get_session() as s:
            res = await s.execute(stmt)
            await s.commit()
            return res.rowcount or 0

    @staticmethod
    def _model_to_domain(model: ServerActivityLogModel) -> ServerActivityLog:
        return ServerActivityLog(
            id=model.id,
            server_id=model.server_id,
            timestamp=model.timestamp,
            event_type=model.event_type,
            actor_type=model.actor_type,
            actor_id=model.actor_id,
            summary=model.summary,
            details=model.to_details_dict(),
        )
