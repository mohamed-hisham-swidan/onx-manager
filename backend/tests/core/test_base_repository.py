from unittest.mock import AsyncMock

import pytest

from app.core.persistence.base import BaseRepository


class DummyModel:
    id = "1"
    name = "original"


@pytest.mark.asyncio
async def test_base_repository_update_returns_merged_entity() -> None:
    session = AsyncMock()
    original_entity = DummyModel()
    merged_entity = DummyModel()
    merged_entity.name = "merged"

    session.merge.return_value = merged_entity

    repo = BaseRepository(session, DummyModel)
    result = await repo.update(original_entity)

    session.merge.assert_awaited_once_with(original_entity)
    session.flush.assert_awaited_once()
    assert result is merged_entity
    assert result is not original_entity
