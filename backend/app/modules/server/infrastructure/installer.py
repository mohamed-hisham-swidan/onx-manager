from __future__ import annotations

import asyncio
import contextlib
import re
import subprocess
from collections.abc import AsyncGenerator
from typing import Any

from app.core.process_utils import platform_kill_process_tree_async
from app.modules.server.domain.installer import InstallerResult, InstallerRunner, ProgressLine


def is_windows() -> bool:
    import sys

    return sys.platform == "win32"


POST_KILL_DRAIN_TIMEOUT: float = 10.0

_FORGE_STAGE_PATTERNS = [
    (re.compile(r"Downloading\s+library", re.IGNORECASE), "downloading_libraries"),
    (re.compile(r"Downloading\s+forge", re.IGNORECASE), "downloading_forge"),
    (re.compile(r"Installing\s+profile", re.IGNORECASE), "installing_profile"),
    (re.compile(r"Installing\s+minecraft", re.IGNORECASE), "installing_minecraft"),
    (re.compile(r"Success", re.IGNORECASE), "success"),
    (re.compile(r"Failed|Error|Exception", re.IGNORECASE), "failed"),
]

_PERCENT_PATTERN = re.compile(r"(\d{1,3})%")


def _parse_progress_line(line: str) -> tuple[str, int | None, str]:
    """Parse a single line of Forge installer output.

    Returns (stage, percent, message). Stage is one of the known stages
    or "unknown". Percent is None if not found. Message is the cleaned line.
    """
    stage = "unknown"
    for pattern, stage_name in _FORGE_STAGE_PATTERNS:
        if pattern.search(line):
            stage = stage_name
            break

    percent_match = _PERCENT_PATTERN.search(line)
    percent = int(percent_match.group(1)) if percent_match else None

    return stage, percent, line.strip()


# Union type for generator output - either ProgressLine or final InstallerResult
RunnerOutput = ProgressLine | InstallerResult


class SubprocessInstallerRunner(InstallerRunner):
    """Local-shell subprocess implementation of :class:`InstallerRunner`."""

    async def run(
        self,
        command: str,
        *,
        timeout: float,
        cwd: str | None = None,
    ) -> AsyncGenerator[RunnerOutput, None]:
        popen_kwargs: dict[str, Any] = {}
        if not is_windows():
            popen_kwargs["start_new_session"] = True
        else:
            # On Windows, start_new_session raises ValueError.
            # Use CREATE_NEW_PROCESS_GROUP for signal and process isolation.
            create_new_process_group = getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
            )
            popen_kwargs["creationflags"] = create_new_process_group

        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # Merge stderr into stdout for simpler parsing
            cwd=cwd,
            close_fds=True,
            **popen_kwargs,
        )

        all_output: list[str] = []
        stdout_queue: asyncio.Queue[ProgressLine | None] = asyncio.Queue()

        async def read_stdout() -> None:
            """Read stdout line by line and put progress into queue."""
            assert proc.stdout is not None
            async for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n\r")
                all_output.append(line)

                stage, percent, message = _parse_progress_line(line)
                if stage != "unknown" or percent is not None:
                    await stdout_queue.put(
                        ProgressLine(stage=stage, percent=percent, message=message, raw_line=line)
                    )
            await stdout_queue.put(None)  # Signal EOF

        async def wait_with_timeout() -> bool:
            """Wait for process with timeout. Returns True if timed out."""
            try:
                await asyncio.wait_for(proc.wait(), timeout=timeout)
                return False
            except TimeoutError:
                return True

        read_task = asyncio.create_task(read_stdout())
        wait_task = asyncio.create_task(wait_with_timeout())

        timed_out = False
        process_done = False

        try:
            while not process_done and not timed_out:
                # Check for progress from stdout
                try:
                    progress = await asyncio.wait_for(stdout_queue.get(), timeout=0.1)
                    if progress is None:
                        # EOF reached
                        break
                    yield progress
                except TimeoutError:
                    pass

                # Check if process wait completed
                if wait_task.done():
                    timed_out = wait_task.result()
                    process_done = True
                    break

        except (asyncio.CancelledError, GeneratorExit):
            # Clean up on cancellation
            read_task.cancel()
            wait_task.cancel()
            await platform_kill_process_tree_async(proc.pid, proc=proc)
            raise

        # If we timed out, kill the process group
        if timed_out:
            read_task.cancel()
            await platform_kill_process_tree_async(proc.pid, proc=proc)
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await read_task

            result = InstallerResult(
                exit_code=proc.returncode,
                output="\n".join(all_output),
                timed_out=True,
            )
            yield ProgressLine(
                stage="timeout", percent=None, message="Installation timed out", raw_line=""
            )
            yield result
            return

        # Wait for stdout reader to finish if it hasn't
        if not read_task.done():
            await read_task

        # Normal completion - drain any remaining queue items
        while not stdout_queue.empty():
            progress = stdout_queue.get_nowait()
            if progress is None:
                break
            yield progress

        # Normal completion - ensure process has exited and returncode is populated
        if not wait_task.done():
            await wait_task
        elif proc.returncode is None:
            await proc.wait()

        exit_code = proc.returncode
        stage = "failed" if exit_code != 0 else "success"

        # Yield final status
        yield ProgressLine(
            stage=stage,
            percent=100 if exit_code == 0 else None,
            message=f"Process exited with code {exit_code}",
            raw_line="",
        )

        result = InstallerResult(
            exit_code=exit_code,
            output="\n".join(all_output),
            timed_out=False,
        )
        yield result
