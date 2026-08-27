from __future__ import annotations

import logging
import time
from collections import defaultdict

from app.core.identity import IDENTITY
from app.modules.health.domain.events import (
    RecoveryFailedEvent,
    RecoverySucceededEvent,
    RecoveryTriggeredEvent,
)
from app.modules.server.domain.diagnostics import FailureCode

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.health.recovery")

MIN_RESTART_INTERVAL: float = 30.0
MAX_RESTART_ATTEMPTS: int = 3
RESTART_WINDOW: float = 300.0

NON_RECOVERABLE_CODES: set[str] = {
    FailureCode.INVALID_JAR_PATH.value,
    FailureCode.INVALID_DEPLOYMENT.value,
    FailureCode.INVALID_LAUNCH_CONFIGURATION.value,
    FailureCode.JAVA_VERSION_MISMATCH.value,
    FailureCode.PERMISSION_ERROR.value,
    FailureCode.FILE_NOT_FOUND.value,
    FailureCode.MEMORY_CONFIGURATION_ERROR.value,
}


class RecoveryOrchestrator:
    def __init__(self) -> None:
        self._crash_history: dict[str, list[float]] = defaultdict(list)

    async def trigger(self, server_id: str, failure_code: str) -> RecoveryAction:
        self._record_crash(server_id)

        if failure_code in NON_RECOVERABLE_CODES:
            return RecoveryAction(
                action="none",
                reason=f"Non-recoverable failure: {failure_code}",
                events=[
                    RecoveryTriggeredEvent(
                        server_id=server_id,
                        recovery_action="none",
                        reason=f"Non-recoverable failure: {failure_code}",
                    )
                ],
            )

        attempts = self._attempts_in_window(server_id)
        if attempts > MAX_RESTART_ATTEMPTS:
            return RecoveryAction(
                action="escalate",
                reason=f"Too many crashes ({attempts}) in window",
                events=[
                    RecoveryTriggeredEvent(
                        server_id=server_id,
                        recovery_action="escalate",
                        reason=f"Crash loop detected: {attempts} crashes in {RESTART_WINDOW}s",
                    )
                ],
            )

        return RecoveryAction(
            action="restart",
            reason=f"Auto-restart after {failure_code}",
            events=[
                RecoveryTriggeredEvent(
                    server_id=server_id,
                    recovery_action="restart",
                    reason=f"Auto-restart after {failure_code}",
                )
            ],
        )

    async def report_success(
        self, server_id: str, action: str, duration: float
    ) -> RecoverySucceededEvent:
        return RecoverySucceededEvent(
            server_id=server_id,
            recovery_action=action,
            duration_seconds=duration,
        )

    async def report_failure(self, server_id: str, action: str, reason: str) -> RecoveryFailedEvent:
        return RecoveryFailedEvent(
            server_id=server_id,
            recovery_action=action,
            failure_reason=reason,
        )

    def _record_crash(self, server_id: str) -> None:
        now = time.time()
        self._crash_history[server_id].append(now)
        cutoff = now - RESTART_WINDOW
        self._crash_history[server_id] = [t for t in self._crash_history[server_id] if t > cutoff]

    def _attempts_in_window(self, server_id: str) -> int:
        now = time.time()
        recent = [t for t in self._crash_history.get(server_id, []) if now - t < RESTART_WINDOW]
        return len(recent)


class RecoveryAction:
    def __init__(
        self,
        action: str,
        reason: str,
        events: list | None = None,
    ) -> None:
        self.action = action
        self.reason = reason
        self.events = events or []
