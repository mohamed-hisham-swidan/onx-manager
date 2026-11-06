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
    assert ok is False


@pytest.mark.asyncio
async def test_dead_letter_replay_reconstructs_concrete_type_and_resolves() -> None:
    import json

    from app.core.event_bus import DomainEvent
    from app.modules.event_store.models import DeadLetterEventModel

    class ConcreteDeadLetterTestEvent(DomainEvent):
        event_type: str = "ConcreteDeadLetterTestEvent"
        extra_data: str = ""

    payload = {"extra_data": "payload_val", "event_type": "ConcreteDeadLetterTestEvent"}
    model = DeadLetterEventModel(
        id="dl-1",
        event_id="evt-1",
        event_type="ConcreteDeadLetterTestEvent",
        data_json=json.dumps(payload),
        error="failure",
        resolved=0,
        replay_count=0,
    )

    session = FakeSession()
    session.add(model)

    bus = AsyncMock()
    service = DeadLetterService(session, bus)

    ok = await service.replay("evt-1")
    assert ok is True

    # Concrete event type reconstructed
    dispatched = bus.publish.call_args[0][0]
    assert isinstance(dispatched, ConcreteDeadLetterTestEvent)
    assert dispatched.extra_data == "payload_val"

    # Marked resolved and replay count incremented
    assert model.resolved == 1
    assert model.replay_count == 1
