import pytest

from app.core.event_bus import DomainEvent, EventBus
from app.storage.unit_of_work import UnitOfWork


class TestUnitOfWork:
    async def test_add_event_collects(self) -> None:
        uow = UnitOfWork()
        event = DomainEvent(event_type="TestEvent")
        uow.add_event(event)
        assert len(uow._events) == 1

    async def test_add_multiple_events(self) -> None:
        uow = UnitOfWork()
        uow.add_event(DomainEvent(event_type="A"))
        uow.add_event(DomainEvent(event_type="B"))
        assert len(uow._events) == 2

    async def test_rollback_clears_events(self) -> None:
        uow = UnitOfWork()
        uow.add_event(DomainEvent(event_type="Test"))
        await uow.rollback()
        assert len(uow._events) == 0

    async def test_session_raises_if_not_started(self) -> None:
        uow = UnitOfWork()
        with pytest.raises(RuntimeError, match="not started"):
            _ = uow.session

    async def test_defer_cleanup_runs_on_rollback(self) -> None:
        uow = UnitOfWork()
        calls: list[str] = []

        async def cleanup_a() -> None:
            calls.append("a")

        async def cleanup_b() -> None:
            calls.append("b")

        uow.defer_cleanup(cleanup_a)
        uow.defer_cleanup(cleanup_b)
        await uow.rollback()

        assert calls == ["b", "a"]

    async def test_defer_cleanup_cleared_on_commit(self) -> None:
        uow = UnitOfWork()
        calls: list[str] = []

        async def cleanup() -> None:
            calls.append("fired")

        uow.defer_cleanup(cleanup)
        await uow.commit()

        assert calls == []

    async def test_defer_cleanup_suppresses_exceptions(self) -> None:
        uow = UnitOfWork()
        calls: list[str] = []

        async def failing() -> None:
            msg = "cleanup failure"
            raise RuntimeError(msg)

        async def succeeding() -> None:
            calls.append("ok")

        uow.defer_cleanup(failing)
        uow.defer_cleanup(succeeding)
        await uow.rollback()

        assert calls == ["ok"]
