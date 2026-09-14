from unittest.mock import MagicMock, patch

import pytest

from app.core.exceptions import BotRunnerUnavailableError
from app.modules.versioning.infrastructure.bot_pool import BotRunnerPool, PooledRunner


@pytest.mark.asyncio
async def test_bot_runner_pool_acquire_and_release_clean() -> None:
    pool = BotRunnerPool()

    # Mock docker run to succeed
    mock_run_res = MagicMock(returncode=0, stdout="test-container-id\n", stderr="")

    with (
        patch("subprocess.run", return_value=mock_run_res),
        patch.object(PooledRunner, "is_alive", return_value=True),
        patch.object(PooledRunner, "execute_reset", return_value=True),
    ):
        # 1. Acquire runner
        runner = await pool.acquire()
        assert isinstance(runner, PooledRunner)
        assert runner.is_busy is True
        assert pool.active_count == 1
        assert pool.idle_count == 0

        # 2. Release cleanly
        await pool.release(runner, outcome="clean")
        assert pool.active_count == 0
        assert pool.idle_count == 1
        assert runner.is_busy is False

        # 3. Re-acquire should reuse the warm idle runner
        runner2 = await pool.acquire()
        assert runner2.runner_id == runner.runner_id
        assert pool.active_count == 1
        assert pool.idle_count == 0


@pytest.mark.asyncio
async def test_bot_runner_pool_unhealthy_release_destroys_container() -> None:
    pool = BotRunnerPool()

    mock_run_res = MagicMock(returncode=0)
    with (
        patch("subprocess.run", return_value=mock_run_res),
        patch.object(PooledRunner, "is_alive", return_value=True),
        patch.object(PooledRunner, "destroy") as mock_destroy,
    ):
        runner = await pool.acquire()
        assert pool.active_count == 1

        # Release with outcome="unhealthy"
        await pool.release(runner, outcome="unhealthy")
        assert pool.active_count == 0
        assert pool.idle_count == 0
        assert mock_destroy.called


@pytest.mark.asyncio
async def test_bot_runner_pool_acquire_failure_raises_unavailable() -> None:
    pool = BotRunnerPool()

    # Mock docker run failure
    mock_run_fail = MagicMock(returncode=1, stderr="docker daemon error")
    with patch("subprocess.run", return_value=mock_run_fail):
        with pytest.raises(BotRunnerUnavailableError) as exc_info:
            await pool.acquire()

        err = exc_info.value
        assert err.code == "BOT_RUNNER_UNAVAILABLE"
        assert err.http_status == 503
