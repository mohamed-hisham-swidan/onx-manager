from typing import Any


class MCSError(Exception):
    def __init__(
        self,
        message: str = "",
        *,
        code: str = "",
        details: dict[str, Any] | None = None,
        http_status: int = 500,
        retryable: bool = False,
    ) -> None:
        self.code = code or self.__class__.__name__
        self.message = message
        self.details = details or {}
        self.http_status = http_status
        self.retryable = retryable
        super().__init__(self.message)


class ValidationError(MCSError):
    def __init__(
        self,
        message: str = "",
        *,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message or "Validation failed",
            code="VALIDATION_ERROR",
            http_status=422,
            details={"field": field, **(details or {})},
        )


class FieldRequiredError(ValidationError):
    def __init__(self, field: str) -> None:
        super().__init__(f"Field '{field}' is required", field=field)


class InvalidValueError(ValidationError):
    def __init__(self, field: str, value: Any, reason: str = "") -> None:
        msg = f"Invalid value for '{field}': {value}"
        if reason:
            msg += f" — {reason}"
        super().__init__(msg, field=field, details={"value": value, "reason": reason})


class AuthenticationError(MCSError):
    def __init__(self, message: str = "") -> None:
        super().__init__(
            message or "Authentication failed",
            code="AUTHENTICATION_ERROR",
            http_status=401,
        )


class InvalidCredentialsError(AuthenticationError):
    def __init__(self) -> None:
        super().__init__("Invalid credentials")


class TokenExpiredError(AuthenticationError):
    def __init__(self) -> None:
        super().__init__("Token has expired")


class PermissionDenied(MCSError):
    def __init__(self, message: str = "") -> None:
        super().__init__(
            message or "Permission denied",
            code="PERMISSION_DENIED",
            http_status=403,
        )


class NotFoundError(MCSError):
    def __init__(self, message: str = "") -> None:
        super().__init__(
            message or "Resource not found",
            code="NOT_FOUND",
            http_status=404,
        )


class ServerNotFoundError(NotFoundError):
    def __init__(self, server_id: str) -> None:
        super().__init__(f"Server '{server_id}' not found")


class ServerNotRunningError(MCSError):
    def __init__(self, server_id: str) -> None:
        super().__init__(
            f"Server '{server_id}' is not running",
            code="SERVER_NOT_RUNNING",
            http_status=404,
        )


class ConflictError(MCSError):
    def __init__(self, message: str = "") -> None:
        super().__init__(
            message or "Resource conflict",
            code="CONFLICT",
            http_status=409,
        )


class DuplicateResourceError(ConflictError):
    def __init__(self, resource_type: str, identifier: str) -> None:
        super().__init__(f"{resource_type} '{identifier}' already exists")


class RateLimitExceeded(MCSError):
    def __init__(self, retry_after: int = 60) -> None:
        super().__init__(
            "Rate limit exceeded",
            code="RATE_LIMIT_EXCEEDED",
            http_status=429,
            details={"retry_after": retry_after},
        )


class InfrastructureError(MCSError):
    def __init__(
        self,
        message: str = "",
        retryable: bool = True,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message or "Infrastructure error",
            code="INFRASTRUCTURE_ERROR",
            http_status=503,
            retryable=retryable,
            details=details or {},
        )


class DatabaseConnectionError(InfrastructureError):
    def __init__(self, detail: str = "") -> None:
        msg = f"Database connection failed: {detail}" if detail else "Database connection failed"
        d = {"detail": detail} if detail else {}
        super().__init__(msg, retryable=True, details=d)


class ProviderError(InfrastructureError):
    def __init__(self, provider: str, operation: str, detail: str = "") -> None:
        msg = f"{provider} {operation} failed"
        if detail:
            msg += f": {detail}"
        d = {"provider": provider, "operation": operation}
        if detail:
            d["detail"] = detail
        super().__init__(msg, retryable=True, details=d)
        self.provider = provider
        self.operation = operation
        self.detail = detail


class InternalError(MCSError):
    def __init__(self, message: str = "") -> None:
        super().__init__(
            message or "Internal error",
            code="INTERNAL_ERROR",
            http_status=500,
        )


class ProvisioningError(InfrastructureError):
    def __init__(
        self,
        message: str = "",
        server_id: str = "",
        retryable: bool = True,
        details: dict[str, Any] | None = None,
    ) -> None:
        d = dict(details or {})
        if server_id:
            d["server_id"] = server_id
        super().__init__(
            message or "Server provisioning failed",
            retryable=retryable,
            details=d,
        )
        self.server_id = server_id


class VersionNotFoundError(ProvisioningError):
    def __init__(self, minecraft_version: str, server_type: str) -> None:
        super().__init__(
            message=f"Version {minecraft_version} not found for {server_type}",
            retryable=False,
            details={
                "minecraft_version": minecraft_version,
                "server_type": server_type,
            },
        )
        self.minecraft_version = minecraft_version
        self.server_type = server_type


class DownloadError(ProvisioningError):
    def __init__(self, url: str, status: int, detail: str = "") -> None:
        msg = f"Download failed: HTTP {status} for {url}"
        if detail:
            msg += f" — {detail}"
        d: dict[str, Any] = {"url": url, "status": status}
        if detail:
            d["detail"] = detail
        super().__init__(msg, retryable=True, details=d)
        self.url = url
        self.status = status


class DownloadTimeoutError(ProvisioningError):
    def __init__(self, url: str, timeout_seconds: int) -> None:
        super().__init__(
            message=f"Download timed out after {timeout_seconds}s for {url}",
            retryable=True,
            details={"url": url, "timeout_seconds": timeout_seconds},
        )
        self.url = url
        self.timeout_seconds = timeout_seconds


class CorruptedDownloadError(ProvisioningError):
    def __init__(self, path: str, reason: str) -> None:
        super().__init__(
            message=f"Downloaded file is corrupted: {path} — {reason}",
            retryable=False,
            details={"path": path, "reason": reason},
        )
        self.path = path
        self.reason = reason


class FilesystemOperationError(ProvisioningError):
    def __init__(self, path: str, operation: str, detail: str = "") -> None:
        msg = f"Filesystem {operation} failed for {path}"
        if detail:
            msg += f": {detail}"
        d: dict[str, Any] = {"path": path, "operation": operation}
        if detail:
            d["detail"] = detail
        super().__init__(msg, retryable=False, details=d)
        self.path = path
        self.operation = operation
