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
