import pytest
from unittest.mock import AsyncMock, patch

from app.tasks.definitions.metrics_collector import run_metrics_collection_task


@pytest.mark.asyncio
async def test_metrics_task_requires_collector() -> None:
    with pytest.raises(KeyError):
        await run_metrics_collection_task({})


@pytest.mark.asyncio
async def test_metrics_task_with_collector() -> None:
    mock_collector = AsyncMock()
    mock_collector.collect_all.return_value = {}
    result = await run_metrics_collection_task({
        "collector": mock_collector,
    })
    assert result["server_count"] == 0
