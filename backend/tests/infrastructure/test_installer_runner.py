import asyncio
import contextlib
import sys
import time
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.server.domain.installer import (
    InstallerResult,
    InstallerRunner,
    ProgressLine,
)
from app.modules.server.infrastructure.installer import (
    ContainerInstallerRunner,
    SubprocessInstallerRunner,
    resolve_installer_runner,
)


async def _run_to_result(
    runner: InstallerRunner, command: str, timeout: float
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


@pytest.mark.asyncio
async def test_runner_platform_popen_kwargs_posix() -> None:
    """ISS-030: On POSIX platforms, start_new_session=True must be passed."""
    mock_reader = _MockHangingReader()
    mock_proc = AsyncMock()
    mock_proc.pid = 12345
    mock_proc.returncode = 0
    mock_proc.stdout = mock_reader

    runner = SubprocessInstallerRunner()
    with (
        patch("app.modules.server.infrastructure.installer.is_windows", return_value=False),
        patch("asyncio.create_subprocess_shell", return_value=mock_proc) as mock_spawn,
    ):
        gen = runner.run("dummy-cmd", timeout=1.0)
        task = asyncio.create_task(gen.asend(None))
        await asyncio.sleep(0.01)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        with contextlib.suppress(Exception):
            await gen.aclose()

    mock_spawn.assert_awaited_once()
    _, kwargs = mock_spawn.await_args
    assert kwargs.get("start_new_session") is True
    assert "creationflags" not in kwargs


@pytest.mark.asyncio
async def test_runner_platform_popen_kwargs_windows() -> None:
    """ISS-030: On Windows platforms, creationflags must include CREATE_NEW_PROCESS_GROUP."""
    mock_reader = _MockHangingReader()
    mock_proc = AsyncMock()
    mock_proc.pid = 12345
    mock_proc.returncode = 0
    mock_proc.stdout = mock_reader

    runner = SubprocessInstallerRunner()
    with (
        patch("app.modules.server.infrastructure.installer.is_windows", return_value=True),
        patch("asyncio.create_subprocess_shell", return_value=mock_proc) as mock_spawn,
    ):
        gen = runner.run("dummy-cmd", timeout=1.0)
        task = asyncio.create_task(gen.asend(None))
        await asyncio.sleep(0.01)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        with contextlib.suppress(Exception):
            await gen.aclose()

    mock_spawn.assert_awaited_once()
    _, kwargs = mock_spawn.await_args
    assert "start_new_session" not in kwargs
    assert kwargs.get("creationflags") == 0x00000200


@pytest.mark.asyncio
async def test_resolve_installer_runner_explicit() -> None:
    custom = SubprocessInstallerRunner()
    resolved = resolve_installer_runner(custom)
    assert resolved is custom


@pytest.mark.asyncio
async def test_resolve_installer_runner_java_present() -> None:
    with patch("shutil.which", return_value="/usr/bin/java"):
        resolved = resolve_installer_runner(None)
        assert isinstance(resolved, SubprocessInstallerRunner)


@pytest.mark.asyncio
async def test_resolve_installer_runner_fallback_to_container_when_java_absent() -> None:
    with patch("shutil.which", return_value=None):
        resolved = resolve_installer_runner(None)
        assert isinstance(resolved, ContainerInstallerRunner)
        assert resolved._image == "eclipse-temurin:21-jdk"


@pytest.mark.asyncio
async def test_container_installer_runner_command_construction() -> None:
    runner = ContainerInstallerRunner(
        image="eclipse-temurin:21-jdk",
        docker_host="tcp://127.0.0.1:2375",
    )
    mock_reader = _MockHangingReader()
    mock_proc = AsyncMock()
    mock_proc.pid = 9999
    mock_proc.returncode = 0
    mock_proc.stdout = mock_reader

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec,
        patch(
            "app.modules.server.infrastructure.installer.platform_kill_process_tree_async",
            AsyncMock(),
        ),
    ):
        gen = runner.run(
            "java -jar forge-installer.jar --installServer",
            timeout=1.0,
            cwd="/tmp/srv42",
        )
        task = asyncio.create_task(gen.asend(None))
        await asyncio.sleep(0.01)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        with contextlib.suppress(Exception):
            await gen.aclose()

    mock_exec.assert_awaited_once()
    call_args = list(mock_exec.await_args[0])
    assert call_args[0] == "docker"
    assert call_args[1] == "-H"
    assert call_args[2] == "tcp://127.0.0.1:2375"
    assert "run" in call_args
    assert "--rm" in call_args
    assert "-i" in call_args
    assert "-v" in call_args
    vol_idx = call_args.index("-v")
    assert call_args[vol_idx + 1].endswith(":/data")
    assert "-w" in call_args
    assert call_args[call_args.index("-w") + 1] == "/data"
    assert "eclipse-temurin:21-jdk" in call_args
    assert "java" in call_args
    assert "--installServer" in call_args


@pytest.mark.asyncio
async def test_container_installer_runner_parses_progress_and_success() -> None:
    runner = ContainerInstallerRunner()

    class _MockLineReader:
        def __init__(self, lines: list[str]) -> None:
            self._lines = [line.encode("utf-8") for line in lines]
            self._idx = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._idx >= len(self._lines):
                raise StopAsyncIteration
            line = self._lines[self._idx]
            self._idx += 1
            return line

    mock_reader = _MockLineReader([
        "Downloading libraries 25%\n",
        "Downloading forge 75%\n",
        "Success! Finished installation.\n",
    ])
    mock_proc = AsyncMock()
    mock_proc.pid = 8888
    mock_proc.returncode = 0
    mock_proc.stdout = mock_reader

    async def fake_wait():
        return 0

    mock_proc.wait = fake_wait

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        items: list[Any] = []
        async for item in runner.run("java -jar installer.jar", timeout=5.0, cwd="/data/srv"):
            items.append(item)

    progress_items = [i for i in items if isinstance(i, ProgressLine)]
    result_items = [i for i in items if isinstance(i, InstallerResult)]

    assert len(progress_items) >= 3
    stages = [p.stage for p in progress_items]
    assert "downloading_libraries" in stages
    assert "downloading_forge" in stages
    assert "success" in stages

    assert len(result_items) == 1
    assert result_items[0].exit_code == 0
    assert result_items[0].timed_out is False


