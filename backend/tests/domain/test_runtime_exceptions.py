from __future__ import annotations

import pytest

from app.modules.server.domain.runtime_exceptions import (
    InvalidDeployment,
    InvalidLaunchConfiguration,
    JavaProcessNotFound,
    ProviderConsoleUnavailable,
    ProviderLaunchFailed,
    ProviderRestartFailed,
    ProviderStopFailed,
    ReadinessProbeFailed,
    RuntimeHandleMissing,
    RuntimeProcessLost,
    RuntimeError_,
    StartupTimeoutError,
    TmuxSessionLost,
    UnknownRuntimeFailure,
)


class TestRuntimeExceptions:
    def test_runtime_error_base(self) -> None:
        exc = RuntimeError_("test", code="TEST_CODE", server_id="srv-1", operation="start")
        assert str(exc) == "test"
        assert exc.code == "TEST_CODE"
        assert exc.server_id == "srv-1"
        assert exc.operation == "start"
        assert exc.diagnostics == {}

    def test_startup_timeout(self) -> None:
        exc = StartupTimeoutError(server_id="srv-1", timeout=60, stage="readiness")
        assert "timed out" in str(exc)
        assert exc.code == "STARTUP_TIMEOUT"
        assert exc.diagnostics["timeout"] == 60
        assert exc.diagnostics["stage"] == "readiness"

    def test_startup_timeout_no_stage(self) -> None:
        exc = StartupTimeoutError(timeout=30)
        assert "30s" in str(exc)

    def test_readiness_probe_failed(self) -> None:
        exc = ReadinessProbeFailed(server_id="srv-1", probe="port_check", detail="Port 25565 not listening")
        assert "port_check" in str(exc)
        assert exc.code == "READINESS_PROBE_FAILED"
        assert exc.diagnostics["probe"] == "port_check"

    def test_runtime_handle_missing(self) -> None:
        exc = RuntimeHandleMissing(server_id="srv-1")
        assert "No runtime handle" in str(exc)

    def test_runtime_process_lost(self) -> None:
        exc = RuntimeProcessLost(server_id="srv-1", pid=12345, last_known_status="running")
        assert "pid=12345" in str(exc)
        assert exc.diagnostics["pid"] == 12345
        assert exc.diagnostics["last_known_status"] == "running"

    def test_provider_launch_failed(self) -> None:
        exc = ProviderLaunchFailed(provider="local", server_id="srv-1", detail="tmux not found")
        assert "local" in str(exc)
        assert exc.code == "PROVIDER_LAUNCH_FAILED"

    def test_provider_stop_failed(self) -> None:
        exc = ProviderStopFailed(provider="local", server_id="srv-1", detail="timeout", force=True)
        assert "timeout" in str(exc)
        assert exc.diagnostics["force"] is True

    def test_provider_restart_failed(self) -> None:
        exc = ProviderRestartFailed(provider="local", server_id="srv-1", stage="STOP", detail="process still alive")
        assert "STOP" in str(exc)
        assert exc.code == "PROVIDER_RESTART_FAILED"

    def test_provider_console_unavailable(self) -> None:
        exc = ProviderConsoleUnavailable(provider="local", server_id="srv-1", detail="tmux session gone")
        assert "console unavailable" in str(exc).lower()

    def test_tmux_session_lost(self) -> None:
        exc = TmuxSessionLost(server_id="srv-1", session_name="mcs-srv-1")
        assert "mcs-srv-1" in str(exc)

    def test_java_process_not_found(self) -> None:
        exc = JavaProcessNotFound(server_id="srv-1", pid=12345)
        assert "12345" in str(exc)

    def test_java_process_not_found_no_pid(self) -> None:
        exc = JavaProcessNotFound(server_id="srv-1")
        assert "not found" in str(exc)

    def test_invalid_deployment(self) -> None:
        exc = InvalidDeployment(server_id="srv-1", detail="missing root_path")
        assert "missing root_path" in str(exc)

    def test_invalid_launch_configuration(self) -> None:
        exc = InvalidLaunchConfiguration(server_id="srv-1", detail="invalid JVM flags")
        assert exc.code == "INVALID_LAUNCH_CONFIGURATION"

    def test_unknown_runtime_failure(self) -> None:
        exc = UnknownRuntimeFailure(
            server_id="srv-1",
            operation="start",
            detail="Something unexpected happened",
            exception_type="ValueError",
            exception_message="bad value",
        )
        assert "Something unexpected" in str(exc)
        assert exc.diagnostics["exception_type"] == "ValueError"
        assert exc.diagnostics["exception_message"] == "bad value"

    def test_all_exceptions_have_nonempty_code(self) -> None:
        for exc_cls in [
            StartupTimeoutError, ReadinessProbeFailed, RuntimeHandleMissing,
            RuntimeProcessLost, ProviderLaunchFailed, ProviderStopFailed,
            ProviderRestartFailed, ProviderConsoleUnavailable, TmuxSessionLost,
            JavaProcessNotFound, InvalidDeployment, InvalidLaunchConfiguration,
            UnknownRuntimeFailure,
        ]:
            exc = exc_cls()
            assert exc.code, f"{exc_cls.__name__} has empty code"
