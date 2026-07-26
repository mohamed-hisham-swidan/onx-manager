from __future__ import annotations

from app.modules.server.domain.diagnostics import FailureCode, RuntimeDiagnostics


class TestRuntimeDiagnostics:
    def test_default_values(self) -> None:
        diag = RuntimeDiagnostics()
        assert diag.failure_timestamp == 0.0
        assert diag.provider == ""
        assert diag.runtime_handle is None
        assert diag.failure_code is None
        assert diag.failure_reason == ""

    def test_to_dict(self) -> None:
        diag = RuntimeDiagnostics(
            provider="local",
            pid=12345,
            failure_code=FailureCode.MEMORY_EXHAUSTED,
            failure_reason="OutOfMemoryError detected",
        )
        d = diag.to_dict()
        assert d["provider"] == "local"
        assert d["pid"] == 12345
        assert d["failure_code"] == "MEMORY_EXHAUSTED"
        assert d["failure_reason"] == "OutOfMemoryError detected"
        assert "failure_timestamp" in d

    def test_to_dict_no_failure_code(self) -> None:
        diag = RuntimeDiagnostics(provider="docker")
        d = diag.to_dict()
        assert d["failure_code"] is None

    def test_capture_with_exception(self) -> None:
        try:
            raise ValueError("test error")
        except ValueError as e:
            diag = RuntimeDiagnostics.capture(
                provider="local",
                operation="start",
                exception=e,
                pid=999,
                failure_code=FailureCode.PROVIDER_LAUNCH_FAILED,
                failure_reason="Provider failed to launch",
            )

        assert diag.provider == "local"
        assert diag.pid == 999
        assert diag.exception_type == "ValueError"
        assert diag.exception_message == "test error"
        assert diag.stack_trace is not None
        assert len(diag.stack_trace) > 0
        assert diag.failure_code == FailureCode.PROVIDER_LAUNCH_FAILED

    def test_capture_without_exception(self) -> None:
        diag = RuntimeDiagnostics.capture(
            provider="local",
            operation="stop",
            exit_code=137,
        )
        assert diag.provider == "local"
        assert diag.exit_code == 137
        assert diag.exception_type is None
        assert diag.stack_trace is None

    def test_failure_code_enum_values(self) -> None:
        assert FailureCode.STARTUP_TIMEOUT.value == "STARTUP_TIMEOUT"
        assert FailureCode.MEMORY_EXHAUSTED.value == "MEMORY_EXHAUSTED"
        assert FailureCode.PORT_CONFLICT.value == "PORT_CONFLICT"
        assert FailureCode.JAVA_VERSION_MISMATCH.value == "JAVA_VERSION_MISMATCH"
        assert FailureCode.TMUX_SESSION_LOST.value == "TMUX_SESSION_LOST"
        assert FailureCode.UNKNOWN_RUNTIME_FAILURE.value == "UNKNOWN_RUNTIME_FAILURE"
