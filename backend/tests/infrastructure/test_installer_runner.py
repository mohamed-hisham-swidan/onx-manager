import asyncio
import contextlib
import sys
import time
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.server.domain.installer import InstallerResult
from app.modules.server.infrastructure.installer import SubprocessInstallerRunner


async def _run_to_result(
    runner: SubprocessInstallerRunner, command: str, timeout: float
) -> InstallerResult:
    """Consume the async generator and return the final InstallerResult."""
    result: InstallerResult | None = None
    async for item in runner.run(command, timeout=timeout):
        if isinstance(item, InstallerResult):
            result = item
    if result is None:
        raise RuntimeError("Runner did not yield an InstallerResult")
    return result


@pytest.mark.asyncio
async def test_runner_captures_output_and_exit_code() -> None:
    runner = SubprocessInstallerRunner()
    cmd = f'"{sys.executable}" -c "print(\'hello-world\')"'
    result = await _run_to_result(runner, cmd, timeout=5.0)
    assert result.timed_out is False
    assert result.exit_code == 0
    assert "hello-world" in result.output


@pytest.mark.asyncio
async def test_runner_reports_nonzero_exit() -> None:
    runner = SubprocessInstallerRunner()
    cmd = f'"{sys.executable}" -c "import sys; sys.stderr.write(\'boom\\n\'); sys.exit(3)"'
    result = await _run_to_result(runner, cmd, timeout=5.0)
    assert result.exit_code == 3
    assert not result.timed_out
    assert "boom" in result.output


@pytest.mark.asyncio
async def test_runner_timeout_kills_process_group() -> None:
    """On timeout the whole process group (shell + child) must be killed so
    the post-kill drain returns quickly instead of hanging on inherited pipes."""
    runner = SubprocessInstallerRunner()
    cmd = f'"{sys.executable}" -c "import time; time.sleep(30)"'
    start = time.monotonic()
    result = await _run_to_result(runner, cmd, timeout=0.2)
    elapsed = time.monotonic() - start

    assert result.timed_out is True
    assert elapsed < 5.0, f"drain hung for {elapsed:.1f}s after kill"


class _MockHangingReader:
    def __aiter__(self):
        return self

    async def __anext__(self):
        await asyncio.sleep(10)
        raise StopAsyncIteration


@pytest.mark.asyncio
async def test_runner_timeout_calls_platform_kill_process_tree() -> None:
    """Verify on timeout, cleanup delegates to platform_kill_process_tree_async."""
    mock_reader = _MockHangingReader()
    mock_proc = AsyncMock()
    mock_proc.pid = 12345
    mock_proc.returncode = -9
    mock_proc.stdout = mock_reader

    async def fake_wait():
        await asyncio.sleep(10)

    mock_proc.wait = fake_wait

    runner = SubprocessInstallerRunner()

    with (
        patch("asyncio.create_subprocess_shell", return_value=mock_proc),
        patch(
            "app.modules.server.infrastructure.installer.platform_kill_process_tree_async",
            new_callable=AsyncMock,
        ) as mock_kill_tree,
        patch("os.killpg", create=True) as mock_killpg,
    ):
        result = await _run_to_result(runner, "dummy-command", timeout=0.01)

    assert result.timed_out is True
    mock_kill_tree.assert_awaited_once_with(12345, proc=mock_proc)
    mock_killpg.assert_not_called()


@pytest.mark.asyncio
async def test_runner_cancelled_calls_platform_kill_process_tree() -> None:
    """Verify on cancellation, cleanup delegates to platform_kill_process_tree_async."""
    mock_reader = _MockHangingReader()
    mock_proc = AsyncMock()
    mock_proc.pid = 12345
    mock_proc.stdout = mock_reader

    async def fake_wait():
        await asyncio.sleep(10)

    mock_proc.wait = fake_wait

    runner = SubprocessInstallerRunner()

    with (
        patch("asyncio.create_subprocess_shell", return_value=mock_proc),
        patch(
            "app.modules.server.infrastructure.installer.platform_kill_process_tree_async",
            new_callable=AsyncMock,
        ) as mock_kill_tree,
        patch("os.killpg", create=True) as mock_killpg,
    ):
        gen = runner.run("dummy", timeout=10.0)
        task = asyncio.create_task(gen.asend(None))
        await asyncio.sleep(0.01)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        with contextlib.suppress(Exception):
            await gen.aclose()

    mock_kill_tree.assert_awaited_once_with(12345, proc=mock_proc)
    mock_killpg.assert_not_called()
