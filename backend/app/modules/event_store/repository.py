from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.event_bus import DomainEvent
from app.modules.event_store.models import DeadLetterEventModel, StoredEventModel


@dataclass
class EventFilters:
    event_type: str | None = None
    correlation_id: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int = 100
    offset: int = 0


@dataclass
class StoredEvent:
    id: int
    event_id: str
    event_type: str
    correlation_id: str
    data_json: str
    schema_version: int
    created_at: datetime
    previous_hash: str | None = None
    hash: str | None = None


@dataclass
class DeadLetterEntry:
    id: int
    event_id: str
    event_type: str
    data_json: str
    error: str
    created_at: datetime
    replay_count: int = 0
    last_replay_at: datetime | None = None
    resolved: bool = False


class SQLEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, event: DomainEvent, *, hash_value: str = "", previous_hash: str = "") -> StoredEvent:
        now = datetime.fromtimestamp(event.timestamp, tz=timezone.utc) if event.timestamp else datetime.now(timezone.utc)
        model = StoredEventModel(
            event_id=event.event_id,
            event_type=event.event_type,
            correlation_id=event.correlation_id,
            data_json=event.model_dump_json(),
            schema_version=event.schema_version,
            created_at=now,
            hash=hash_value or "",
            previous_hash=previous_hash or None,
        )
        self._session.add(model)
        await self._session.flush()
        return self._model_to_dto(model)

    async def get(self, event_id: str) -> StoredEvent | None:
        stmt = select(StoredEventModel).where(StoredEventModel.event_id == event_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._model_to_dto(model) if model else None

    async def query(self, filters: EventFilters) -> list[StoredEvent]:
        stmt = select(StoredEventModel)

        conditions: list[Any] = []
        if filters.event_type:
            conditions.append(StoredEventModel.event_type == filters.event_type)
        if filters.correlation_id:
            conditions.append(StoredEventModel.correlation_id == filters.correlation_id)
        if filters.since:
            conditions.append(StoredEventModel.created_at >= filters.since)
        if filters.until:
            conditions.append(StoredEventModel.created_at <= filters.until)

        if conditions:
            stmt = stmt.where(and_(*conditions))

        stmt = stmt.order_by(desc(StoredEventModel.created_at)).offset(filters.offset).limit(filters.limit)
        result = await self._session.execute(stmt)
        return [self._model_to_dto(m) for m in result.scalars().all()]

    async def list_by_type(
        self,
        event_type: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[StoredEvent]:
        filters = EventFilters(event_type=event_type, limit=limit, offset=offset)
        return await self.query(filters)

    async def list_recent(self, limit: int = 100) -> list[StoredEvent]:
        stmt = (
            select(StoredEventModel)
            .order_by(desc(StoredEventModel.created_at))
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [self._model_to_dto(m) for m in result.scalars().all()]

    async def count(self) -> int:
        stmt = select(func.count()).select_from(StoredEventModel)
        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def get_last_event(self) -> StoredEvent | None:
        stmt = (
            select(StoredEventModel)
            .order_by(desc(StoredEventModel.id))
            .limit(1)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._model_to_dto(model) if model else None

    # Dead letter operations
    async def append_dead_letter(
        self,
        event: DomainEvent,
        error: str,
    ) -> None:
        model = DeadLetterEventModel(
            event_id=event.event_id,
            event_type=event.event_type,
            data_json=event.model_dump_json(),
            error=error,
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(model)
        await self._session.flush()

    async def list_dead_letters(self, limit: int = 100, offset: int = 0) -> list[DeadLetterEntry]:
        stmt = (
            select(DeadLetterEventModel)
            .order_by(desc(DeadLetterEventModel.created_at))
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [self._dead_letter_to_dto(m) for m in result.scalars().all()]

    async def get_dead_letter(self, event_id: str) -> DeadLetterEntry | None:
        stmt = select(DeadLetterEventModel).where(DeadLetterEventModel.event_id == event_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._dead_letter_to_dto(model) if model else None

    async def get_dead_letter_count(self) -> int:
        stmt = select(func.count()).select_from(DeadLetterEventModel)
        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def resolve_dead_letter(self, event_id: str) -> None:
        stmt = select(DeadLetterEventModel).where(DeadLetterEventModel.event_id == event_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model:
            model.resolved = 1
            model.last_replay_at = datetime.now(timezone.utc)
            await self._session.flush()

    async def increment_replay_count(self, event_id: str) -> None:
        stmt = select(DeadLetterEventModel).where(DeadLetterEventModel.event_id == event_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model:
            model.replay_count += 1
            model.last_replay_at = datetime.now(timezone.utc)
            await self._session.flush()

    async def replay_dead_letter(self, event_id: str) -> bool:
        from json import loads as json_loads
        entry = await self.get_dead_letter(event_id)
        if entry is None or entry.resolved:
            return False

        event_data = json_loads(entry.data_json)
        event = DomainEvent(**event_data)
        event.event_type = entry.event_type

        try:
            from app.core.persistence.db import database
            from app.core.event_bus import EventBus

            bus = EventBus()
            await bus.publish(event)
            await self.increment_replay_count(event_id)
            return True
        except Exception:
            return False

    def _model_to_dto(self, model: StoredEventModel) -> StoredEvent:
        return StoredEvent(
            id=model.id,
            event_id=model.event_id,
            event_type=model.event_type,
            correlation_id=model.correlation_id,
            data_json=model.data_json,
            schema_version=model.schema_version,
            created_at=model.created_at,
            previous_hash=model.previous_hash,
            hash=model.hash,
        )

    def _dead_letter_to_dto(self, model: DeadLetterEventModel) -> DeadLetterEntry:
        return DeadLetterEntry(
            id=model.id,
            event_id=model.event_id,
            event_type=model.event_type,
            data_json=model.data_json,
            error=model.error,
            created_at=model.created_at,
            replay_count=model.replay_count,
            last_replay_at=model.last_replay_at,
            resolved=bool(model.resolved),
        )
