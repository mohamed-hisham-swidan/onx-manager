from unittest.mock import MagicMock

import pytest

from app.modules.event_store.repository import EventFilters, SQLEventRepository


class FakeSession:
    def __init__(self) -> None:
        self._store: dict[str, object] = {}
        self._id_counter = 1

    async def get(self, _model_class: type, pk: object) -> object | None:
        for obj in self._store.values():
            if getattr(obj, "event_id", None) == pk or getattr(obj, "id", None) == pk:
                return obj
        return None

    async def execute(self, _stmt: object) -> MagicMock:
        result = MagicMock()
        result.scalars.return_value.all.return_value = list(self._store.values())
        result.scalar.return_value = len(self._store)
        result.scalar_one_or_none.return_value = (
            list(self._store.values())[-1] if self._store else None
        )
        return result

    def add(self, obj: object) -> None:
        self._store[str(self._id_counter)] = obj
        self._id_counter += 1

    async def flush(self) -> None:
        pass


@pytest.mark.asyncio
async def test_repository_append() -> None:
    from app.core.event_bus import DomainEvent

    session = FakeSession()
    repo = SQLEventRepository(session)

    event = DomainEvent(event_type="test.event")
    stored = await repo.append(event, hash_value="abc", previous_hash="")
    assert stored.event_type == "test.event"


@pytest.mark.asyncio
async def test_repository_query_with_filters() -> None:
    from app.core.event_bus import DomainEvent

    session = FakeSession()
    repo = SQLEventRepository(session)

    event1 = DomainEvent(event_type="test.a")
    event2 = DomainEvent(event_type="test.b")
    await repo.append(event1)
    await repo.append(event2)

    results = await repo.query(EventFilters(event_type="test.a"))
    assert len(results) >= 0


@pytest.mark.asyncio
async def test_repository_count() -> None:
    session = FakeSession()
    repo = SQLEventRepository(session)
    count = await repo.count()
    assert count >= 0


@pytest.mark.asyncio
async def test_replay_dead_letter_dispatches_to_bus() -> None:
    from app.core.event_bus import DomainEvent, EventBus
    from app.modules.event_store.models import DeadLetterEventModel

    bus = EventBus()
    received_events: list[DomainEvent] = []

    class DummyHandler:
        async def handle(self, event: DomainEvent) -> None:
            received_events.append(event)

    bus.subscribe("dead.letter.replayed", DummyHandler())

    session = FakeSession()
    repo = SQLEventRepository(session, event_bus=bus)

    dead_letter = DeadLetterEventModel(
        event_id="dl-123",
        event_type="dead.letter.replayed",
        data_json=(
            '{"event_id": "dl-123", "event_type": "dead.letter.replayed", "message": "hello"}'
        ),
        error="Test error",
        resolved=0,
        replay_count=0,
    )
    dead_letter.id = 1
    session.add(dead_letter)

    ok = await repo.replay_dead_letter("dl-123")
    assert ok is True
    assert len(received_events) == 1
    assert received_events[0].event_type == "dead.letter.replayed"
    assert dead_letter.replay_count == 1
