from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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
    payload = b"|".join(
        [
            event_id.encode(),
            event_type.encode(),
            correlation_id.encode(),
            data_json.encode(),
            str(schema_version).encode(),
            str(timestamp).encode(),
            previous_hash.encode(),
        ]
    )
    return hashlib.sha256(payload).hexdigest()


class EventChain:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = SQLEventRepository(session)

    async def append_chain(self, event: Any, max_retries: int = 5) -> StoredEvent:
        for attempt in range(max_retries):
            previous = await self._repo.get_last_event()
            prev_hash = previous.hash if previous else ""

            now = (
                datetime.fromtimestamp(event.timestamp, tz=UTC)
                if getattr(event, "timestamp", None)
                else datetime.now(UTC)
            )
            ts = now.timestamp()
            if hasattr(event, "timestamp"):
                event.timestamp = ts

            chain_hash = compute_hash(
                event_id=event.event_id,
                event_type=event.event_type,
                correlation_id=event.correlation_id,
                data_json=event.model_dump_json(),
                schema_version=event.schema_version,
                timestamp=ts,
                previous_hash=prev_hash,
            )

            try:
                if hasattr(self._session, "begin_nested"):
                    async with self._session.begin_nested():
                        stored = await self._repo.append(
                            event,
                            hash_value=chain_hash,
                            previous_hash=prev_hash,
                        )
                else:
                    stored = await self._repo.append(
                        event,
                        hash_value=chain_hash,
                        previous_hash=prev_hash,
                    )
                return stored
            except IntegrityError:
                if attempt == max_retries - 1:
                    raise RuntimeError(
                        f"EventChain.append_chain failed after {max_retries} attempts "
                        "due to concurrent append conflicts"
                    )
                await asyncio.sleep(0.01 * (attempt + 1))

        raise RuntimeError("EventChain.append_chain retry loop exhausted")

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

        if from_id > 1:
            prev_stmt = (
                select(StoredEventModel)
                .where(StoredEventModel.id < from_id)
                .order_by(StoredEventModel.id.desc())
                .limit(1)
            )
            prev_res = await self._session.execute(prev_stmt)
            prev_model = prev_res.scalar_one_or_none()
            prev_hash = prev_model.hash if prev_model else (events[0].previous_hash or "")
        else:
            prev_hash = ""
        for model in events:
            created_at = (
                model.created_at.replace(tzinfo=UTC)
                if model.created_at.tzinfo is None
                else model.created_at
            )
            expected = compute_hash(
                event_id=model.event_id,
                event_type=model.event_type,
                correlation_id=model.correlation_id,
                data_json=model.data_json,
                schema_version=model.schema_version,
                timestamp=created_at.timestamp(),
                previous_hash=prev_hash,
            )
            if model.hash != expected:
                return False
            prev_hash = model.hash

        return True

    async def verify_chain_from_id(self, event_id: str) -> bool:
        stmt = select(StoredEventModel).where(StoredEventModel.event_id == event_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return False
        return await self.verify_chain(from_id=model.id)
