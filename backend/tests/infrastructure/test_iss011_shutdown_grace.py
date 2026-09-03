from __future__ import annotations

import signal
import sys
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.server.infrastructure.providers.base import ServerHandle
from app.modules.server.infrastructure.providers.local import (
    SHUTDOWN_GRACE_PERIOD_SECONDS,
    LocalLinuxProvider,
)


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="LocalLinuxProvider is POSIX-only",
)
class TestShutdownGracePeriod:
    @pytest.mark.asyncio
    async def test_process_exits_within_grace_period_no_sigkill(self) -> None:
        """ISS-011: Process exits within grace period; SIGKILL is never sent."""
        provider = LocalLinuxProvider()
        handle = ServerHandle(provider="local", server_id="s1", external_id="onx-s1")
        pid = 12345

        signals_sent: list[int] = []

        def mock_kill(_target_pid: int, sig: int):
            signals_sent.append(sig)

        liveness_responses = [True, False]

        async def mock_is_pid_alive(_check_pid: int) -> bool:
            if liveness_responses:
                return liveness_responses.pop(0)
            return False

        with (
            patch.object(provider, "_get_tmux_pid", AsyncMock(return_value=pid)),
            patch.object(provider, "_run_command", AsyncMock(return_value=0)),
            patch.object(provider, "_is_pid_alive", side_effect=mock_is_pid_alive),
            patch(
                "app.modules.server.infrastructure.providers.local.os.kill",
                side_effect=mock_kill,
            ),
            patch("asyncio.sleep", AsyncMock()),
        ):
            await provider.stop(handle, force=True)

        assert signal.SIGTERM in signals_sent
        assert signal.SIGKILL not in signals_sent

    @pytest.mark.asyncio
    async def test_process_never_exits_sigkill_sent_after_grace_period(self) -> None:
        """ISS-011: Process never exits; SIGKILL sent after grace period expires."""
        provider = LocalLinuxProvider()
        handle = ServerHandle(provider="local", server_id="s2", external_id="onx-s2")
        pid = 12345

        signals_sent: list[int] = []
        sleep_durations: list[float] = []

        def mock_kill(_target_pid: int, sig: int):
            signals_sent.append(sig)

        current_time = 100.0

        def fake_monotonic():
            nonlocal current_time
            return current_time

        async def fake_sleep(duration: float):
            nonlocal current_time
            sleep_durations.append(duration)
            current_time += duration

        with (
            patch.object(provider, "_get_tmux_pid", AsyncMock(return_value=pid)),
            patch.object(provider, "_run_command", AsyncMock(return_value=0)),
            patch.object(provider, "_is_pid_alive", AsyncMock(return_value=True)),
            patch(
                "app.modules.server.infrastructure.providers.local.os.kill",
                side_effect=mock_kill,
            ),
            patch("time.monotonic", side_effect=fake_monotonic),
            patch("asyncio.sleep", side_effect=fake_sleep),
        ):
            await provider.stop(handle, force=True)

        assert signal.SIGTERM in signals_sent
        assert signal.SIGKILL in signals_sent
        total_slept = sum(sleep_durations)
        assert total_slept >= SHUTDOWN_GRACE_PERIOD_SECONDS
