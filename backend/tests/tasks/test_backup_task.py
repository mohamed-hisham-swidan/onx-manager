import pytest
from unittest.mock import AsyncMock, patch

from app.tasks.definitions.backup_task import run_backup_task


@pytest.mark.asyncio
async def test_backup_task_requires_server_id() -> None:
    with pytest.raises(KeyError):
        await run_backup_task({})


@pytest.mark.asyncio
async def test_backup_task_params_validation() -> None:
    with pytest.raises(KeyError):
        await run_backup_task({"server_id": "srv-1"})
