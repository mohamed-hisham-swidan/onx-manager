import pytest
from unittest.mock import AsyncMock, patch

from app.tasks.definitions.cleanup_task import run_cleanup_task


@pytest.mark.asyncio
async def test_cleanup_task_requires_db() -> None:
    with pytest.raises(Exception):
        await run_cleanup_task({})


@pytest.mark.asyncio
async def test_cleanup_task_with_params() -> None:
    with pytest.raises(Exception):
        await run_cleanup_task({
            "cleanup_logs": True,
            "cleanup_idempotency": True,
            "cleanup_events": True,
            "cleanup_task_queue": True,
        })
