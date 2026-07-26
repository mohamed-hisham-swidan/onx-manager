from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.event_store.models import StoredEventModel
from app.modules.event_store.repository import SQLEventRepository, StoredEvent


def compute_hash(
    event_id: str,
    event_type: str,
    correlation_id: str,
    data_json: str,
    schema_version: int,
    timestamp: float,
    previous_hash: str,
) -> str:
    payload = b"|".join([
        event_id.encode(),
        event_type.encode(),
        correlation_id.encode(),
        data_json.encode(),
        str(schema_version).encode(),
        str(timestamp).encode(),
        previous_hash.encode(),
    ])
    return hashlib.sha256(payload).hexdigest()


class EventChain:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = SQLEventRepository(session)

    async def append_chain(self, event: Any) -> StoredEvent:
        previous = await self._repo.get_last_event()
        prev_hash = previous.hash if previous else ""

        chain_hash = compute_hash(
            event_id=event.event_id,
            event_type=event.event_type,
            correlation_id=event.correlation_id,
            data_json=event.model_dump_json(),
            schema_version=event.schema_version,
            timestamp=event.timestamp,
            previous_hash=prev_hash,
        )

        stored = await self._repo.append(
            event,
            hash_value=chain_hash,
            previous_hash=prev_hash,
        )

        return stored

    async def verify_chain(self, from_id: int = 1, to_id: int | None = None) -> bool:
        stmt = (
            select(StoredEventModel)
            .where(StoredEventModel.id >= from_id)
            .order_by(StoredEventModel.id.asc())
        )
        if to_id is not None:
            stmt = stmt.where(StoredEventModel.id <= to_id)

        result = await self._session.execute(stmt)
        events = list(result.scalars().all())

        if not events:
            return True

        prev_hash = ""
        for model in events:
            expected = compute_hash(
                event_id=model.event_id,
                event_type=model.event_type,
                correlation_id=model.correlation_id,
                data_json=model.data_json,
                schema_version=model.schema_version,
                timestamp=model.created_at.timestamp(),
                previous_hash=prev_hash,
            )
            if model.hash != expected:
                return False
            prev_hash = model.hash

        return True

    async def verify_chain_from_id(self, event_id: str) -> bool:
        stmt = (
            select(StoredEventModel)
            .where(StoredEventModel.event_id == event_id)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return False
        return await self.verify_chain(from_id=model.id)
