from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.event_store.dead_letter import DeadLetterService


class FakeSession:
    def __init__(self) -> None:
        self._store: dict[str, object] = {}

    async def get(self, _model_class: type, pk: object) -> object | None:
        for obj in self._store.values():
            if getattr(obj, "id", None) == pk:
                return obj
        return None

    async def execute(self, _stmt: object) -> MagicMock:
        from app.modules.event_store.models import DeadLetterEventModel

        result = MagicMock()
        values = list(self._store.values())

        scalar = None
        for obj in values:
            if isinstance(obj, DeadLetterEventModel):
                scalar = obj
                break
        result.scalar_one_or_none.return_value = scalar

        unresolved = [v for v in values if hasattr(v, "resolved") and v.resolved == 0]
        result.scalars.return_value.all.return_value = unresolved
        return result

    def add(self, obj: object) -> None:
        key = str(getattr(obj, "event_id", None) or getattr(obj, "id", "") or id(obj))
        self._store[key] = obj

    async def delete(self, obj: object) -> None:
        key = str(getattr(obj, "event_id", None) or getattr(obj, "id", "") or "")
        self._store.pop(key, None)

    async def flush(self) -> None:
        pass

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *args: object) -> None:
        pass


@pytest.mark.asyncio
async def test_dead_letter_replay_nonexistent() -> None:
    session = FakeSession()
    bus = AsyncMock()
    service = DeadLetterService(session, bus)
    ok = await service.replay("nonexistent")
    assert ok is False


@pytest.mark.asyncio
async def test_dead_letter_delete_nonexistent() -> None:
    session = FakeSession()
    bus = AsyncMock()
    service = DeadLetterService(session, bus)
    ok = await service.delete("nonexistent")
    assert ok is False


@pytest.mark.asyncio
async def test_dead_letter_resolve_nonexistent() -> None:
    session = FakeSession()
    bus = AsyncMock()
    service = DeadLetterService(session, bus)
    ok = await service.resolve("nonexistent")
    assert ok is True
