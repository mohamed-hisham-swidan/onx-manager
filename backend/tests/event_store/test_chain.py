import pytest

from app.modules.event_store.chain import EventChain, compute_hash


class FakeSession:
    def __init__(self) -> None:
        self._store: dict[int, object] = {}
        self._id_counter = 1

    async def get(self, _model_class: type, pk: object) -> object | None:
        for obj in self._store.values():
            if getattr(obj, "event_id", None) == pk or getattr(obj, "id", None) == pk:
                return obj
        return None

    async def execute(self, _stmt: object) -> object:
        from unittest.mock import MagicMock

        result = MagicMock()
        result.scalars.return_value.all.return_value = sorted(
            self._store.values(), key=lambda x: getattr(x, "id", 0)
        )
        result.scalar_one_or_none.return_value = (
            list(self._store.values())[-1] if self._store else None
        )
        return result

    def add(self, obj: object) -> None:
        obj.id = self._id_counter
        self._store[self._id_counter] = obj
        self._id_counter += 1

    async def flush(self) -> None:
        pass


def test_compute_hash_consistency() -> None:
    h1 = compute_hash(
        event_id="a",
        event_type="t",
        correlation_id="c",
        data_json="{}",
        schema_version=1,
        timestamp=100.0,
        previous_hash="",
    )
    h2 = compute_hash(
        event_id="a",
        event_type="t",
        correlation_id="c",
        data_json="{}",
        schema_version=1,
        timestamp=100.0,
        previous_hash="",
    )
    assert h1 == h2
    assert len(h1) == 64


def test_compute_hash_different() -> None:
    h1 = compute_hash(
        event_id="a",
        event_type="t",
        correlation_id="c",
        data_json="{}",
        schema_version=1,
        timestamp=100.0,
        previous_hash="",
    )
    h2 = compute_hash(
        event_id="b",
        event_type="t",
        correlation_id="c",
        data_json="{}",
        schema_version=1,
        timestamp=100.0,
        previous_hash="",
    )
    assert h1 != h2


@pytest.mark.asyncio
async def test_chain_verify_empty() -> None:
    session = FakeSession()
    chain = EventChain(session)
    assert await chain.verify_chain() is True


@pytest.mark.asyncio
async def test_chain_verify_from_id_greater_than_one() -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.event_bus import DomainEvent
    from app.core.persistence.base import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine)
    async with session_factory() as session:
        chain = EventChain(session)
        e1 = DomainEvent(event_type="event.one", event_id="id-1")
        await chain.append_chain(e1)
        e2 = DomainEvent(event_type="event.two", event_id="id-2")
        await chain.append_chain(e2)
        e3 = DomainEvent(event_type="event.three", event_id="id-3")
        await chain.append_chain(e3)
        await session.commit()

        # F019: verify_chain for from_id > 1 must verify True using preceding event hash
        assert await chain.verify_chain(from_id=1) is True
        assert await chain.verify_chain(from_id=2) is True
        assert await chain.verify_chain(from_id=3) is True
        assert await chain.verify_chain_from_id("id-2") is True
        assert await chain.verify_chain_from_id("id-3") is True
    await engine.dispose()
