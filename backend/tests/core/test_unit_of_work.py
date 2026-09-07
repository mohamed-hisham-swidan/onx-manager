from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.core.persistence.unit_of_work import UnitOfWork


def _patched_uow(session: AsyncMock) -> UnitOfWork:
    mocker = patch("app.core.persistence.unit_of_work.database")
    mock_database = mocker.start()
    msf = AsyncMock()
    msf.__aenter__ = AsyncMock(return_value=session)
    mock_database.session_factory.return_value = msf
    uow = UnitOfWork()
    try:
        yield uow
    finally:
        mocker.stop()


@pytest.mark.asyncio
async def test_uow_closes_session_when_commit_raises() -> None:
    session = AsyncMock()
    session.close = AsyncMock()
    session.commit.side_effect = RuntimeError("boom")

    for uow in _patched_uow(session):
        with pytest.raises(RuntimeError):
            async with uow:
                pass

    session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_uow_closes_session_on_success() -> None:
    session = AsyncMock()
    session.is_active = True
    session.close = AsyncMock()

    for uow in _patched_uow(session):
        async with uow:
            pass

    session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_uow_partial_event_publishing_failure_clears_events() -> None:
    from app.core.event_bus import DomainEvent, EventBus

    event_bus = EventBus()
    published_events: list[DomainEvent] = []

    async def failing_publish(event: DomainEvent) -> None:
        published_events.append(event)
        if event.event_type == "event.fail":
            raise RuntimeError("Publish failed")

    event_bus.publish = failing_publish  # type: ignore[method-assign]

    session = AsyncMock()
    session.commit = AsyncMock()
    session.close = AsyncMock()

    mocker = patch("app.core.persistence.unit_of_work.database")
    mock_database = mocker.start()
    msf = AsyncMock()
    msf.__aenter__ = AsyncMock(return_value=session)
    mock_database.session_factory.return_value = msf

    try:
        uow = UnitOfWork(event_bus=event_bus)
        e1 = DomainEvent(event_type="event.fail")
        e2 = DomainEvent(event_type="event.success")
        uow.add_event(e1)
        uow.add_event(e2)

        with pytest.raises(RuntimeError, match="Publish failed"):
            await uow.commit()

        # Both events were attempted in order
        assert len(published_events) == 2
        assert published_events[0] is e1
        assert published_events[1] is e2
        # Events were cleared and not stranded
        assert len(uow._events) == 0
    finally:
        mocker.stop()
