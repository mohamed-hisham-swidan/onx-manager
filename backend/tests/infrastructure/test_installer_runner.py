from __future__ import annotations

import time

import pytest

from app.modules.server.domain.installer import InstallerResult, ProgressLine
from app.modules.server.infrastructure.installer import SubprocessInstallerRunner


async def _run_to_result(runner: SubprocessInstallerRunner, command: str, timeout: float) -> InstallerResult:
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
    result = await _run_to_result(runner, "echo hello-world", timeout=5.0)
    assert result.timed_out is False
    assert result.exit_code == 0
    assert "hello-world" in result.output


@pytest.mark.asyncio
async def test_runner_reports_nonzero_exit() -> None:
    runner = SubprocessInstallerRunner()
    result = await _run_to_result(runner, "echo boom >&2; exit 3", timeout=5.0)
    assert result.exit_code == 3
    assert not result.timed_out
    assert "boom" in result.output


@pytest.mark.asyncio
async def test_runner_timeout_kills_process_group() -> None:
    """On timeout the whole process group (shell + child) must be killed so
    the post-kill drain returns quickly instead of hanging on inherited pipes."""
    runner = SubprocessInstallerRunner()
    start = time.monotonic()
    result = await _run_to_result(runner, "sleep 30", timeout=0.2)
    elapsed = time.monotonic() - start

    assert result.timed_out is True
    assert elapsed < 5.0, f"drain hung for {elapsed:.1f}s after kill"