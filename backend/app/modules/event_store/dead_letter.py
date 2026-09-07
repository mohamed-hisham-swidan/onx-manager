from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.event_bus import DomainEvent, EventBus
from app.modules.event_store.models import DeadLetterEventModel
from app.modules.event_store.repository import SQLEventRepository

logger = logging.getLogger(__name__)


class DeadLetterService:
    def __init__(self, session: AsyncSession, event_bus: EventBus) -> None:
        self._session = session
        self._repo = SQLEventRepository(session)
        self._event_bus = event_bus

    async def list_all(self, limit: int = 100) -> list[DeadLetterEventModel]:
        stmt = (
            select(DeadLetterEventModel)
            .order_by(DeadLetterEventModel.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_unresolved(self, limit: int = 100) -> list[DeadLetterEventModel]:
        stmt = (
            select(DeadLetterEventModel)
            .where(DeadLetterEventModel.resolved == 0)
            .order_by(DeadLetterEventModel.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def replay(self, event_id: str) -> bool:
        entry = await self._repo.get_dead_letter(event_id)
        if entry is None or entry.resolved:
            return False

        from json import loads as json_loads

        payload = json_loads(entry.data_json)
        domain_event = DomainEvent(**payload)

        try:
            await self._event_bus.publish(domain_event)
            await self._repo.increment_replay_count(event_id)
            return True
        except Exception as e:
            logger.warning("Replay failed for dead letter %s: %s", event_id, e)
            return False

    async def replay_all(self) -> dict[str, int]:
        entries = await self.list_unresolved()
        succeeded = 0
        failed = 0

        for entry in entries:
            ok = await self.replay(entry.event_id)
            if ok:
                succeeded += 1
            else:
                failed += 1

        return {"succeeded": succeeded, "failed": failed}

    async def resolve(self, event_id: str) -> bool:
        return await self._repo.resolve_dead_letter(event_id)

    async def delete(self, event_id: str) -> bool:
        entry = await self._repo.get_dead_letter(event_id)
        if entry is None:
            return False
        model = await self._session.get(DeadLetterEventModel, entry.id)
        if model:
            await self._session.delete(model)
            await self._session.flush()
        return True
