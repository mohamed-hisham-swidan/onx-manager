from __future__ import annotations

from typing import Any


class RuntimeError_(Exception):
    def __init__(
        self,
        message: str = "",
        *,
        code: str = "",
        server_id: str = "",
        provider: str = "",
        operation: str = "",
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        self.code = code or self.__class__.__name__
        self.server_id = server_id
        self.provider = provider
        self.operation = operation
        self.diagnostics = diagnostics or {}
        super().__init__(message)


class StartupTimeoutError(RuntimeError_):
    def __init__(
        self,
        server_id: str = "",
        timeout: float = 0,
        stage: str = "",
    ) -> None:
        msg = f"Startup timed out after {timeout}s"
        if stage:
            msg += f" during {stage}"
        super().__init__(
            msg,
            code="STARTUP_TIMEOUT",
            server_id=server_id,
            operation="start",
            diagnostics={"timeout": timeout, "stage": stage},
        )


class ReadinessProbeFailed(RuntimeError_):
    def __init__(
        self,
        server_id: str = "",
        probe: str = "",
        detail: str = "",
    ) -> None:
        msg = f"Readiness probe '{probe}' failed"
        if detail:
            msg += f": {detail}"
        super().__init__(
            msg,
            code="READINESS_PROBE_FAILED",
            server_id=server_id,
            operation="verify",
            diagnostics={"probe": probe, "detail": detail},
        )


class RuntimeHandleMissing(RuntimeError_):
    def __init__(self, server_id: str = "") -> None:
        super().__init__(
            f"No runtime handle for server '{server_id}'",
            code="RUNTIME_HANDLE_MISSING",
            server_id=server_id,
            operation="status",
        )


class RuntimeProcessLost(RuntimeError_):
    def __init__(
        self,
        server_id: str = "",
        pid: int | None = None,
        last_known_status: str = "",
    ) -> None:
        msg = f"Runtime process lost (pid={pid})"
        super().__init__(
            msg,
            code="RUNTIME_PROCESS_LOST",
            server_id=server_id,
            operation="health_check",
            diagnostics={"pid": pid, "last_known_status": last_known_status},
        )


class ProviderLaunchFailed(RuntimeError_):
    def __init__(
        self,
        provider: str = "",
        server_id: str = "",
        detail: str = "",
    ) -> None:
        super().__init__(
            f"Provider '{provider}' launch failed: {detail}",
            code="PROVIDER_LAUNCH_FAILED",
            server_id=server_id,
            provider=provider,
            operation="start",
            diagnostics={"detail": detail},
        )


class ProviderStopFailed(RuntimeError_):
    def __init__(
        self,
        provider: str = "",
        server_id: str = "",
        detail: str = "",
        force: bool = False,
    ) -> None:
        super().__init__(
            f"Provider '{provider}' stop failed: {detail}",
            code="PROVIDER_STOP_FAILED",
            server_id=server_id,
            provider=provider,
            operation="stop",
            diagnostics={"detail": detail, "force": force},
        )


class ProviderRestartFailed(RuntimeError_):
    def __init__(
        self,
        provider: str = "",
        server_id: str = "",
        stage: str = "",
        detail: str = "",
    ) -> None:
        super().__init__(
            f"Provider '{provider}' restart failed at stage '{stage}': {detail}",
            code="PROVIDER_RESTART_FAILED",
            server_id=server_id,
            provider=provider,
            operation="restart",
            diagnostics={"stage": stage, "detail": detail},
        )


class ProviderConsoleUnavailable(RuntimeError_):
    def __init__(
        self,
        provider: str = "",
        server_id: str = "",
        detail: str = "",
    ) -> None:
        super().__init__(
            f"Provider '{provider}' console unavailable: {detail}",
            code="PROVIDER_CONSOLE_UNAVAILABLE",
            server_id=server_id,
            provider=provider,
            operation="console",
            diagnostics={"detail": detail},
        )


class TmuxSessionLost(RuntimeError_):
    def __init__(
        self,
        server_id: str = "",
        session_name: str = "",
    ) -> None:
        super().__init__(
            f"tmux session '{session_name}' lost",
            code="TMUX_SESSION_LOST",
            server_id=server_id,
            operation="health_check",
            diagnostics={"session_name": session_name},
        )


class JavaProcessNotFound(RuntimeError_):
    def __init__(
        self,
        server_id: str = "",
        pid: int | None = None,
    ) -> None:
        msg = f"Java process not found (pid={pid})" if pid else "Java process not found"
        super().__init__(
            msg,
            code="JAVA_PROCESS_NOT_FOUND",
            server_id=server_id,
            operation="health_check",
            diagnostics={"pid": pid},
        )


class InvalidDeployment(RuntimeError_):
    def __init__(self, server_id: str = "", detail: str = "") -> None:
        super().__init__(
            f"Invalid deployment for server '{server_id}': {detail}",
            code="INVALID_DEPLOYMENT",
            server_id=server_id,
            operation="start",
            diagnostics={"detail": detail},
        )


class InvalidLaunchConfiguration(RuntimeError_):
    def __init__(self, server_id: str = "", detail: str = "") -> None:
        super().__init__(
            f"Invalid launch configuration for server '{server_id}': {detail}",
            code="INVALID_LAUNCH_CONFIGURATION",
            server_id=server_id,
            operation="start",
            diagnostics={"detail": detail},
        )


class UnknownRuntimeFailure(RuntimeError_):
    def __init__(
        self,
        server_id: str = "",
        operation: str = "",
        detail: str = "",
        exception_type: str = "",
        exception_message: str = "",
    ) -> None:
        super().__init__(
            f"Unknown runtime failure during {operation}: {detail}",
            code="UNKNOWN_RUNTIME_FAILURE",
            server_id=server_id,
            operation=operation,
            diagnostics={
                "detail": detail,
                "exception_type": exception_type,
                "exception_message": exception_message,
            },
        )
