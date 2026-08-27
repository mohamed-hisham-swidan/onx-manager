from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class FailureCode(str, Enum):
    STARTUP_TIMEOUT = "STARTUP_TIMEOUT"
    READINESS_PROBE_FAILED = "READINESS_PROBE_FAILED"
    RUNTIME_HANDLE_MISSING = "RUNTIME_HANDLE_MISSING"
    RUNTIME_PROCESS_LOST = "RUNTIME_PROCESS_LOST"
    PROVIDER_LAUNCH_FAILED = "PROVIDER_LAUNCH_FAILED"
    PROVIDER_STOP_FAILED = "PROVIDER_STOP_FAILED"
    PROVIDER_RESTART_FAILED = "PROVIDER_RESTART_FAILED"
    PROVIDER_CONSOLE_UNAVAILABLE = "PROVIDER_CONSOLE_UNAVAILABLE"
    TMUX_SESSION_LOST = "TMUX_SESSION_LOST"
    JAVA_PROCESS_NOT_FOUND = "JAVA_PROCESS_NOT_FOUND"
    INVALID_DEPLOYMENT = "INVALID_DEPLOYMENT"
    INVALID_LAUNCH_CONFIGURATION = "INVALID_LAUNCH_CONFIGURATION"
    MEMORY_EXHAUSTED = "MEMORY_EXHAUSTED"
    PORT_CONFLICT = "PORT_CONFLICT"
    PORT_ALREADY_BOUND = "PORT_ALREADY_BOUND"
    JAVA_VERSION_MISMATCH = "JAVA_VERSION_MISMATCH"
    INVALID_JAR_PATH = "INVALID_JAR_PATH"
    MEMORY_CONFIGURATION_ERROR = "MEMORY_CONFIGURATION_ERROR"
    NETWORK_BIND_FAILURE = "NETWORK_BIND_FAILURE"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    PERMISSION_ERROR = "PERMISSION_ERROR"
    UNKNOWN_RUNTIME_FAILURE = "UNKNOWN_RUNTIME_FAILURE"


@dataclass
class RuntimeDiagnostics:
    failure_timestamp: float = 0.0
    provider: str = ""
    runtime_handle: str | None = None
    pid: int | None = None
    exit_code: int | None = None
    signal: int | None = None
    startup_duration: float | None = None
    last_successful_heartbeat: float | None = None
    provider_operation: str = ""
    exception_type: str | None = None
    exception_message: str | None = None
    stack_trace: list[str] | None = None
    last_runtime_status: str | None = None
    last_known_uptime: float | None = None
    last_log_lines: list[str] | None = None
    failure_code: FailureCode | None = None
    failure_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_timestamp": self.failure_timestamp,
            "provider": self.provider,
            "runtime_handle": self.runtime_handle,
            "pid": self.pid,
            "exit_code": self.exit_code,
            "signal": self.signal,
            "startup_duration": self.startup_duration,
            "last_successful_heartbeat": self.last_successful_heartbeat,
            "provider_operation": self.provider_operation,
            "exception_type": self.exception_type,
            "exception_message": self.exception_message,
            "stack_trace": self.stack_trace,
            "last_runtime_status": self.last_runtime_status,
            "last_known_uptime": self.last_known_uptime,
            "last_log_lines": self.last_log_lines,
            "failure_code": self.failure_code.value if self.failure_code else None,
            "failure_reason": self.failure_reason,
        }

    @classmethod
    def capture(
        cls,
        provider: str = "",
        operation: str = "",
        exception: Exception | None = None,
        pid: int | None = None,
        exit_code: int | None = None,
        last_log_lines: list[str] | None = None,
        runtime_handle: str | None = None,
        failure_code: FailureCode | None = None,
        failure_reason: str = "",
        last_runtime_status: str | None = None,
    ) -> RuntimeDiagnostics:
        import traceback

        d = cls(
            failure_timestamp=datetime.now(UTC).timestamp(),
            provider=provider,
            runtime_handle=runtime_handle,
            pid=pid,
            exit_code=exit_code,
            provider_operation=operation,
            last_log_lines=last_log_lines,
            failure_code=failure_code,
            failure_reason=failure_reason,
            last_runtime_status=last_runtime_status,
        )
        if exception:
            d.exception_type = type(exception).__name__
            d.exception_message = str(exception)
            d.stack_trace = traceback.format_exc().splitlines()
        return d
