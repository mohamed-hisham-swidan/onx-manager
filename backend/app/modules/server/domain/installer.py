from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class InstallerResult:
    exit_code: int | None
    output: str
    timed_out: bool = False


@dataclass(frozen=True)
class ProgressLine:
    stage: str
    percent: int | None
    message: str
    raw_line: str


RunnerOutput = ProgressLine | InstallerResult


class InstallerRunner(Protocol):
    """Port for executing a single command and capturing its output.

    Kept deliberately minimal and scoped to provisioning work (e.g. the
    Forge ``--installServer`` step). Implementations own the subprocess
    transport (local shell today, container exec once Phase 11 lands).
    """

    async def run(
        self,
        command: str,
        *,
        timeout: float,
        cwd: str | None = None,
    ) -> AsyncGenerator[RunnerOutput, None]: ...
