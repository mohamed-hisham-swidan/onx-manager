from __future__ import annotations

import time

import pytest

from app.modules.health.infrastructure.recovery_orchestrator import (
    NON_RECOVERABLE_CODES,
    RESTART_WINDOW,
    RecoveryOrchestrator,
)
from app.modules.server.domain.diagnostics import FailureCode


pytestmark = pytest.mark.asyncio


class TestRecoveryOrchestrator:
    async def test_non_recoverable_returns_none_action(self):
        orch = RecoveryOrchestrator()
        result = await orch.trigger("srv-1", FailureCode.INVALID_JAR_PATH.value)
        assert result.action == "none"
        assert "Non-recoverable" in result.reason

    async def test_non_recoverable_codes_list(self):
        assert FailureCode.INVALID_JAR_PATH.value in NON_RECOVERABLE_CODES
        assert FailureCode.INVALID_DEPLOYMENT.value in NON_RECOVERABLE_CODES
        assert FailureCode.INVALID_LAUNCH_CONFIGURATION.value in NON_RECOVERABLE_CODES
        assert FailureCode.JAVA_VERSION_MISMATCH.value in NON_RECOVERABLE_CODES
        assert FailureCode.PERMISSION_ERROR.value in NON_RECOVERABLE_CODES
        assert FailureCode.FILE_NOT_FOUND.value in NON_RECOVERABLE_CODES
        assert FailureCode.MEMORY_CONFIGURATION_ERROR.value in NON_RECOVERABLE_CODES

    async def test_recoverable_returns_restart_action(self):
        orch = RecoveryOrchestrator()
        result = await orch.trigger("srv-2", FailureCode.MEMORY_EXHAUSTED.value)
        assert result.action == "restart"
        assert "Auto-restart" in result.reason

    async def test_crash_loop_detected_after_max_attempts(self):
        orch = RecoveryOrchestrator()
        for _ in range(4):
            result = await orch.trigger("srv-3", FailureCode.MEMORY_EXHAUSTED.value)
        assert result.action == "escalate"
        assert "Too many crashes" in result.reason

    async def test_crash_loop_resets_after_window(self):
        orch = RecoveryOrchestrator()
        for _ in range(2):
            await orch.trigger("srv-4", FailureCode.MEMORY_EXHAUSTED.value)

        recent = [t for t in orch._crash_history["srv-4"] if time.time() - t < RESTART_WINDOW]
        assert len(recent) >= 2

    async def test_no_crash_history_returns_restart(self):
        orch = RecoveryOrchestrator()
        result = await orch.trigger("srv-5", FailureCode.PORT_CONFLICT.value)
        assert result.action == "restart"

    async def test_recoverable_codes_return_restart(self):
        orch = RecoveryOrchestrator()
        for code in [FailureCode.RUNTIME_PROCESS_LOST.value, FailureCode.TMUX_SESSION_LOST.value]:
            result = await orch.trigger("srv-6", code)
            assert result.action == "restart", f"Expected restart for {code}"

    async def test_report_success_creates_event(self):
        orch = RecoveryOrchestrator()
        event = await orch.report_success("srv-7", "restart", 12.5)
        assert event.server_id == "srv-7"
        assert event.recovery_action == "restart"
        assert event.duration_seconds == 12.5

    async def test_report_failure_creates_event(self):
        orch = RecoveryOrchestrator()
        event = await orch.report_failure("srv-8", "restart", "OOM again")
        assert event.server_id == "srv-8"
        assert event.recovery_action == "restart"
        assert "OOM" in event.failure_reason

    async def test_trigger_emits_recovery_event(self):
        orch = RecoveryOrchestrator()
        result = await orch.trigger("srv-9", FailureCode.MEMORY_EXHAUSTED.value)
        assert len(result.events) == 1
        event = result.events[0]
        assert event.server_id == "srv-9"
        assert event.recovery_action == "restart"

    async def test_mixed_codes_escalate_after_threshold(self):
        orch = RecoveryOrchestrator()
        for code in [
            FailureCode.MEMORY_EXHAUSTED.value,
            FailureCode.PORT_CONFLICT.value,
            FailureCode.RUNTIME_PROCESS_LOST.value,
            FailureCode.MEMORY_EXHAUSTED.value,
        ]:
            result = await orch.trigger("srv-10", code)
        assert result.action == "escalate"

    async def test_individual_server_tracking(self):
        orch = RecoveryOrchestrator()
        for _ in range(3):
            await orch.trigger("srv-a", FailureCode.MEMORY_EXHAUSTED.value)
        await orch.trigger("srv-b", FailureCode.MEMORY_EXHAUSTED.value)

        assert len(orch._crash_history["srv-a"]) == 3
        assert len(orch._crash_history["srv-b"]) == 1

    async def test_non_recoverable_still_records_crash(self):
        orch = RecoveryOrchestrator()
        await orch.trigger("srv-c", FailureCode.INVALID_JAR_PATH.value)
        assert len(orch._crash_history["srv-c"]) == 1
