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


class InvalidValueError(ValidationError, ValueError):
    def __init__(self, field: str, value: Any, reason: str = "") -> None:
        msg = f"Invalid value for '{field}': {value}"
        if reason:
            msg += f" — {reason}"
        super().__init__(msg, field=field, details={"value": value, "reason": reason})


class InvalidJarError(ValidationError):
    def __init__(
        self,
        message: str = "Invalid or corrupt JAR file",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message or "Invalid or corrupt JAR file",
            field="file",
            details=details,
        )
        self.code = "INVALID_JAR"
        self.http_status = 400


class MaterializationFileTooLargeError(ValidationError):
    def __init__(self, path: str, size_bytes: int, max_bytes: int) -> None:
        super().__init__(
            f"File '{path}' exceeds maximum read size of {max_bytes} bytes "
            f"(actual: {size_bytes} bytes)",
            field="path",
            details={"path": path, "size_bytes": size_bytes, "max_bytes": max_bytes},
        )
        self.code = "FILE_TOO_LARGE"
        self.http_status = 413


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


class PermissionDenied(MCSError):  # noqa: N818 - public error name is stable
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


class BranchProtectedError(ConflictError):
    def __init__(self, message: str = "") -> None:
        super().__init__(message or "Branch is protected")


class ServerModeVersioningDisabledError(ConflictError):
    def __init__(self, message: str = "") -> None:
        MCSError.__init__(
            self,
            message or "Versioning operations are disabled for servers in simple mode",
            code="SERVER_MODE_VERSIONING_DISABLED",
            http_status=409,
        )


class DuplicatePortSetError(ConflictError):
    def __init__(
        self,
        message: str = "",
        *,
        conflicting_ports: list[Any] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged: dict[str, Any] = {"conflicting_ports": list(conflicting_ports or [])}
        if details:
            merged.update(details)
        MCSError.__init__(
            self,
            message or "Duplicate port set",
            code="DUPLICATE_PORT_SET",
            http_status=409,
            details=merged,
        )


class PortAllocationExhaustedError(ConflictError):
    def __init__(
        self,
        message: str = "",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        MCSError.__init__(
            self,
            message or "Port allocation exhausted",
            code="PORT_ALLOCATION_EXHAUSTED",
            http_status=409,
            details=details or {},
        )


class HotCloneRefusedError(ConflictError):
    def __init__(
        self,
        message: str = "",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        MCSError.__init__(
            self,
            message or "Hot clone refused",
            code="HOT_CLONE_REFUSED",
            http_status=409,
            details=details or {},
        )


class BranchRuntimeActiveError(ConflictError):
    def __init__(
        self,
        message: str = "",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        MCSError.__init__(
            self,
            message or "Branch runtime active",
            code="BRANCH_RUNTIME_ACTIVE",
            http_status=409,
            details=details or {},
        )


class BranchConcurrencyLimitError(ConflictError):
    def __init__(
        self,
        message: str = "",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        MCSError.__init__(
            self,
            message or "Branch concurrency limit exceeded",
            code="BRANCH_CONCURRENCY_LIMIT",
            http_status=409,
            details=details or {},
        )


class RefreshRecoveryRequiredError(ConflictError):
    """A non-terminal refresh journal must be reconciled before boot."""

    def __init__(
        self,
        server_id: str,
        *,
        journal_id: str = "",
        phase: str = "",
    ) -> None:
        details: dict[str, Any] = {"server_id": server_id}
        if journal_id:
            details["journal_id"] = journal_id
        if phase:
            details["phase"] = phase
        MCSError.__init__(
            self,
            (
                f"Server '{server_id}' has an unresolved refresh journal"
                f"{f' ({phase})' if phase else ''}; run refresh recovery/rollback "
                "before starting the server"
            ),
            code="REFRESH_RECOVERY_REQUIRED",
            http_status=409,
            details=details,
        )


class FencingTokenMismatchError(ConflictError):
    def __init__(
        self,
        message: str = "",
        *,
        server_id: str | None = None,
        expected_token: int | None = None,
        actual_token: int | None = None,
    ) -> None:
        details: dict[str, Any] = {}
        if server_id is not None:
            details["server_id"] = server_id
        if expected_token is not None:
            details["expected_token"] = expected_token
        if actual_token is not None:
            details["actual_token"] = actual_token
        MCSError.__init__(
            self,
            message or "Fencing token mismatch",
            code="FENCING_TOKEN_MISMATCH",
            http_status=409,
            details=details,
        )


class BackupPinnedError(ConflictError):
    def __init__(self, backup_id: str, message: str = "") -> None:
        MCSError.__init__(
            self,
            message or f"Backup '{backup_id}' is pinned and cannot be deleted",
            code="BACKUP_PINNED",
            http_status=409,
            details={"backup_id": backup_id},
        )


class MasterKekMissingError(ValidationError):
    """The Advanced vault requires a master KEK that is not configured."""

    def __init__(
        self,
        message: str = "",
        *,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message or "Master KEK is not configured",
            field=field,
            details=details,
        )
        self.code = "MASTER_KEK_MISSING"
        self.http_status = 503


class MasterKekInvalidError(ValidationError):
    """The configured master KEK cannot be decoded as a 256-bit key."""

    def __init__(
        self,
        message: str = "",
        *,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message or "Master KEK is invalid",
            field=field,
            details=details,
        )
        self.code = "MASTER_KEK_INVALID"
        self.http_status = 503


class MasterKekVersionMismatchError(ValidationError):
    """A wrapped DEK was produced by a different KEK version."""

    def __init__(
        self,
        *,
        stored_kek_version: int,
        active_kek_version: int,
        message: str = "",
    ) -> None:
        super().__init__(
            message
            or (
                "KEK version mismatch: stored kek_version="
                f"{stored_kek_version} does not match active kek_version="
                f"{active_kek_version}"
            ),
            details={
                "stored_kek_version": stored_kek_version,
                "active_kek_version": active_kek_version,
            },
        )
        # The contract exposes exactly the two version fields (no ``field`` key).
        self.details = {
            "stored_kek_version": stored_kek_version,
            "active_kek_version": active_kek_version,
        }
        self.code = "MASTER_KEK_VERSION_MISMATCH"
        self.http_status = 409


class GuardConfigurationError(MCSError):
    def __init__(self, message: str = "") -> None:
        super().__init__(
            message or "Mode guard requires exactly one mode source",
            code="GUARD_CONFIGURATION_ERROR",
            http_status=500,
        )


class RateLimitExceeded(MCSError):  # noqa: N818 - public error name is stable
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
    def __init__(
        self,
        provider: str,
        operation: str,
        detail: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        msg = f"{provider} {operation} failed"
        if detail:
            msg += f": {detail}"
        d: dict[str, Any] = {"provider": provider, "operation": operation}
        if detail:
            d["detail"] = detail
        if details:
            d.update(details)
        super().__init__(msg, retryable=True, details=d)
        self.provider = provider
        self.operation = operation
        self.detail = detail


class SecurityPermissionError(InfrastructureError):
    """Raised when critical security permissions on files or resources cannot be established."""

    def __init__(self, message: str = "", details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message or "Security permission check failed",
            retryable=False,
            details=details or {},
        )
        self.code = "SECURITY_PERMISSION_ERROR"


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


class PathContainmentError(MCSError):
    def __init__(self, path: str, root: str) -> None:
        super().__init__(
            f"Path '{path}' must be strictly inside '{root}'",
            code="PATH_CONTAINMENT_VIOLATION",
            http_status=403,
            details={"path": path, "root": root},
        )
        self.path = path
        self.root = root


class StorageCowUnavailableError(MCSError):
    def __init__(
        self,
        path: str = "",
        message: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        default_msg = (
            "Versioning and isolated testing requires a Btrfs or ZFS filesystem "
            "supporting copy-on-write on the server data path. Your server data "
            f"directory ({path or 'unknown'}) does not support reflink cloning. "
            "Standard server management remains fully available."
        )
        super().__init__(
            message or default_msg,
            code="STORAGE_COW_UNAVAILABLE",
            http_status=412,
            details={"path": path, **(details or {})},
        )


class BotRunInsufficientResourcesError(MCSError):
    def __init__(
        self,
        message: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message or "Insufficient system headroom to execute isolated bot verification",
            code="BOT_RUN_INSUFFICIENT_RESOURCES",
            http_status=422,
            details=details or {},
        )


class TestIsolationViolationError(MCSError):
    __test__ = False

    def __init__(
        self,
        message: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message or "Test execution violated offline-mode or directory isolation invariant",
            code="TEST_ISOLATION_VIOLATION",
            http_status=500,
            details=details or {},
        )


class UnsupportedBotTechError(ValidationError):
    def __init__(
        self,
        bot_tech: str,
        server_type: str,
        message: str = "",
    ) -> None:
        msg = (
            message
            or f"Bot technology '{bot_tech}' is unsupported for server type '{server_type}'."
        )
        super().__init__(
            msg,
            field="bot_tech",
            details={"bot_tech": bot_tech, "server_type": server_type},
        )
        self.code = "UNSUPPORTED_BOT_TECH_FOR_SERVER_TYPE"
        self.http_status = 400


class BotRunnerUnavailableError(MCSError):
    def __init__(
        self,
        message: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message or "No healthy bot runner could be acquired from the pool",
            code="BOT_RUNNER_UNAVAILABLE",
            http_status=503,
            retryable=True,
            details=details or {},
        )


# --- P2 B2/B3 Lockfile Format 2.1 & SHA-256 CAS Exceptions ---


class LockfileFormatError(ValidationError):
    def __init__(
        self,
        message: str = "Lockfile format unsupported",
        *,
        field: str | None = "format",
        details: dict[str, Any] | None = None,
    ) -> None:
        t_field = str(field)[:128] if field is not None else None
        merged: dict[str, Any] | None = None
        if details is not None:
            merged = {
                str(k)[:128]: (str(v)[:128] if isinstance(v, str) else v)
                for k, v in details.items()
            }
        super().__init__(
            message or "Lockfile format unsupported",
            field=t_field,
            details=merged,
        )
        self.code = "LOCKFILE_FORMAT_UNSUPPORTED"
        self.http_status = 422


class LockfileInvalidError(ValidationError):
    def __init__(
        self,
        message: str = "Lockfile content is invalid",
        *,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        t_field = str(field)[:128] if field is not None else None
        merged: dict[str, Any] | None = None
        if details is not None:
            merged = {
                str(k)[:128]: (str(v)[:128] if isinstance(v, str) else v)
                for k, v in details.items()
            }
        super().__init__(
            message or "Lockfile content is invalid",
            field=t_field,
            details=merged,
        )
        self.code = "LOCKFILE_INVALID"
        self.http_status = 422


class CaseCollisionError(ValidationError):
    def __init__(
        self,
        message: str = "Casefold collision detected",
        *,
        path_a: str = "",
        path_b: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        t_path_a = str(path_a)[:128]
        t_path_b = str(path_b)[:128]
        merged = {"path_a": t_path_a, "path_b": t_path_b}
        if details:
            for k, v in details.items():
                merged[str(k)[:128]] = str(v)[:128] if isinstance(v, str) else v
        super().__init__(
            message or "Casefold collision detected",
            field="path",
            details=merged,
        )
        self.code = "CASE_COLLISION"
        self.http_status = 422
        self.path_a = t_path_a
        self.path_b = t_path_b


class InsufficientStorageError(MCSError):
    def __init__(
        self,
        message: str = "Insufficient storage space",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message or "Insufficient storage space",
            code="INSUFFICIENT_STORAGE",
            http_status=507,
            retryable=True,
            details=details or {},
        )


class CasError(MCSError):
    def __init__(
        self,
        message: str = "CAS operation failed",
        *,
        code: str = "CAS_ERROR",
        http_status: int = 500,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message or "CAS operation failed",
            code=code,
            http_status=http_status,
            retryable=retryable,
            details=details or {},
        )


class CasInvalidDigestError(CasError):
    def __init__(
        self,
        message: str = "Invalid CAS digest",
        *,
        digest: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        truncated = str(digest)[:128]
        merged = {"digest": truncated}
        if details:
            merged.update(details)
        super().__init__(
            message or "Invalid CAS digest",
            code="CAS_INVALID_DIGEST",
            http_status=422,
            details=merged,
        )
        self.digest = truncated


class CasInvalidSourceError(CasError):
    def __init__(
        self,
        message: str = "Invalid CAS source file",
        *,
        path: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        truncated = str(path)[:128]
        merged = {"path": truncated}
        if details:
            merged.update(details)
        super().__init__(
            message or "Invalid CAS source file",
            code="CAS_INVALID_SOURCE",
            http_status=422,
            details=merged,
        )
        self.path = truncated


class CasBlobNotFoundError(CasError):
    def __init__(
        self,
        message: str = "CAS blob not found",
        *,
        digest: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        truncated = str(digest)[:128]
        merged = {"digest": truncated}
        if details:
            merged.update(details)
        super().__init__(
            message or "CAS blob not found",
            code="CAS_BLOB_NOT_FOUND",
            http_status=404,
            details=merged,
        )
        self.digest = truncated


class CasCorruptionError(CasError):
    def __init__(
        self,
        message: str = "CAS blob corruption detected",
        *,
        digest: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        truncated = str(digest)[:128]
        merged = {"digest": truncated}
        if details:
            merged.update(details)
        super().__init__(
            message or "CAS blob corruption detected",
            code="CAS_CORRUPTION",
            http_status=500,
            details=merged,
        )
        self.digest = truncated


class CasContainmentError(CasError):
    def __init__(
        self,
        message: str = "CAS path containment violation",
        *,
        path: str = "",
        root: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        t_path = str(path)[:128]
        t_root = str(root)[:128]
        merged = {"path": t_path, "root": t_root}
        if details:
            merged.update(details)
        super().__init__(
            message or "CAS path containment violation",
            code="CAS_PATH_CONTAINMENT",
            http_status=403,
            details=merged,
        )
        self.path = t_path
        self.root = t_root


class CasWriteError(CasError):
    def __init__(
        self,
        message: str = "CAS write operation failed",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message or "CAS write operation failed",
            code="CAS_WRITE_FAILED",
            http_status=500,
            details=details or {},
        )


class CasUnsupportedPlatformError(CasError):
    def __init__(
        self,
        message: str = "CAS is not supported on this platform",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message or "CAS is not supported on this platform",
            code="CAS_UNSUPPORTED_PLATFORM",
            http_status=501,
            details=details or {},
        )


# --- P2-2 Native Git repository engine exceptions ---


class GitError(MCSError):
    """Base error for hardened native Git operations."""

    def __init__(
        self,
        message: str = "Git operation failed",
        *,
        code: str = "GIT_ERROR",
        http_status: int = 500,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message or "Git operation failed",
            code=code,
            http_status=http_status,
            retryable=retryable,
            details=details or {},
        )


class GitConfigurationError(GitError):
    """Raised when the isolated Git configuration cannot be created or read."""

    def __init__(
        self,
        message: str = "Git configuration error",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message or "Git configuration error",
            code="GIT_CONFIGURATION_ERROR",
            http_status=500,
            details=details or {},
        )


class GitUnsupportedPlatformError(GitError):
    """Raised when native Git is requested on a platform the engine does not support."""

    def __init__(
        self,
        message: str = "Native Git is not supported on this platform",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message or "Native Git is not supported on this platform",
            code="GIT_UNSUPPORTED_PLATFORM",
            http_status=501,
            details=details or {},
        )


class GitUnavailableError(GitError):
    """Raised when the configured Git executable cannot be executed."""

    def __init__(
        self,
        message: str = "Git executable is unavailable",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message or "Git executable is unavailable",
            code="GIT_UNAVAILABLE",
            http_status=503,
            retryable=True,
            details=details or {},
        )


class GitCommandError(GitError):
    """Raised when a Git command exits non-zero."""

    def __init__(
        self,
        message: str = "Git command failed",
        *,
        command: str = "",
        returncode: int | None = None,
        stderr: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        merged: dict[str, Any] = dict(details or {})
        if command:
            merged["command"] = command[:256]
        if returncode is not None:
            merged["returncode"] = returncode
        if stderr:
            merged["stderr"] = stderr[:2000]
        super().__init__(
            message or "Git command failed",
            code="GIT_COMMAND_FAILED",
            http_status=500,
            details=merged,
        )
        self.command = command
        self.returncode = returncode
        self.stderr = stderr


class GitTimeoutError(GitCommandError):
    """Raised when a Git command exceeds its timeout."""

    def __init__(
        self,
        message: str = "Git command timed out",
        *,
        command: str = "",
        timeout_seconds: float = 0.0,
        stderr: str = "",
    ) -> None:
        super().__init__(
            message or "Git command timed out",
            command=command,
            stderr=stderr,
            details={"timeout_seconds": timeout_seconds},
        )
        self.code = "GIT_TIMEOUT"
        self.http_status = 504
        self.retryable = True
        self.timeout_seconds = timeout_seconds


class GitRefValidationError(ValidationError):
    """Raised when a branch name fails the hardened validation contract."""

    def __init__(
        self,
        message: str = "Invalid Git branch name",
        *,
        ref: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message or "Invalid Git branch name",
            field="branch",
            details={"ref": ref[:256], **(details or {})},
        )
        self.code = "GIT_REF_INVALID"
        self.http_status = 422


class GitRemoteUrlError(ValidationError):
    """Raised when a Git remote URL does not match the approved GitHub forms."""

    def __init__(
        self,
        message: str = "Invalid Git remote URL",
        *,
        url: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message or "Invalid Git remote URL",
            field="remote_url",
            details={"url": url[:256], **(details or {})},
        )
        self.code = "GIT_REMOTE_URL_INVALID"
        self.http_status = 422


class GitRepositoryStateError(GitError):
    """Raised when an existing repository or worktree is not in the expected state."""

    def __init__(
        self,
        message: str = "Git repository state is invalid",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message or "Git repository state is invalid",
            code="GIT_REPOSITORY_STATE",
            http_status=409,
            details=details,
        )


class OversizedGitTrackedFileError(ValidationError):
    """Raised when a Git-tracked Class-B file exceeds the 1 MiB cap."""

    def __init__(
        self,
        path: str = "",
        size_bytes: int = 0,
        max_bytes: int = 1024 * 1024,
    ) -> None:
        super().__init__(
            f"Git-tracked file '{path}' exceeds the {max_bytes} byte limit "
            f"(actual: {size_bytes} bytes)",
            field="path",
            details={
                "path": path[:128],
                "size_bytes": size_bytes,
                "max_bytes": max_bytes,
            },
        )
        self.code = "GIT_TRACKED_FILE_TOO_LARGE"
        self.http_status = 413


class SecretFileInGitForbiddenError(ValidationError):
    """Raised when staged Class-B content contains secret material.

    ``findings`` must contain only kind/key metadata. Detected secret values are
    never included in the error message or details.
    """

    def __init__(
        self,
        path: str = "",
        *,
        findings: list[dict[str, Any]] | None = None,
    ) -> None:
        safe_findings = [
            {"kind": str(item.get("kind", "unknown"))[:64], "key": str(item.get("key", ""))[:128]}
            for item in (findings or [])
        ]
        super().__init__(
            f"File '{path}' contains secret material and cannot be committed",
            field="path",
            details={"path": path[:128], "findings": safe_findings},
        )
        self.code = "SECRET_FILE_IN_GIT_FORBIDDEN"
        self.http_status = 422


class DirtyWorktreeError(ConflictError):
    def __init__(
        self,
        branch: str = "",
        message: str = "",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        msg = message or (
            f"Branch '{branch}' has uncommitted changes in its worktree; commit or discard them before merging"  # noqa: E501
            if branch
            else "Branch worktree has uncommitted changes"
        )
        if branch:
            merged_details = {"branch": branch[:128], **(details or {})}
        else:
            merged_details = dict(details or {})
        MCSError.__init__(
            self,
            msg,
            code="DIRTY_WORKTREE",
            http_status=409,
            details=merged_details,
        )
        self.branch = branch


class MergeConflictError(ConflictError):
    def __init__(
        self,
        message: str = "Merge failed due to conflicts",
        *,
        conflicts: list[dict[str, Any]] | None = None,
        warnings: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.conflicts = list(conflicts or [])
        self.warnings = list(warnings or [])
        self.details = {"conflicts": self.conflicts, "warnings": self.warnings, **(details or {})}
        MCSError.__init__(
            self,
            message or "Merge failed due to conflicts",
            code="MERGE_CONFLICT",
            http_status=409,
            details=self.details,
        )


# --- P5 GitHub sync exceptions ---


class NonFastForwardMainError(ConflictError):
    """Raised when a GitHub sync would rewrite ``main`` non-fast-forward."""

    code = "GITHUB_NON_FAST_FORWARD_MAIN"
    http_status = 409

    def __init__(
        self,
        message: str = "",
        *,
        local_sha: str = "",
        remote_sha: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        merged: dict[str, Any] = {"branch": "main", **(details or {})}
        if local_sha:
            merged["local_sha"] = str(local_sha)[:64]
        if remote_sha:
            merged["remote_sha"] = str(remote_sha)[:64]
        MCSError.__init__(
            self,
            message
            or (
                "Remote 'main' cannot be fast-forwarded cleanly; force-push "
                "and non-fast-forward updates to main are rejected"
            ),
            code="GITHUB_NON_FAST_FORWARD_MAIN",
            http_status=409,
            details=merged,
        )
        self.local_sha = local_sha
        self.remote_sha = remote_sha


class GitHubNotConnectedError(ConflictError):
    """Raised when a server has no configured GitHub repository connection."""

    code = "GITHUB_NOT_CONNECTED"
    http_status = 409

    def __init__(
        self,
        server_id: str = "",
        message: str = "",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged: dict[str, Any] = dict(details or {})
        if server_id:
            merged["server_id"] = str(server_id)[:64]
            default_message = (
                f"Server '{server_id}' is not connected to a GitHub repository"
            )
        else:
            default_message = "Server is not connected to a GitHub repository"
        MCSError.__init__(
            self,
            message or default_message,
            code="GITHUB_NOT_CONNECTED",
            http_status=409,
            details=merged,
        )
        self.server_id = server_id


class GitHubAuthFailedError(ConflictError):
    """Raised when GitHub rejects the stored credential.

    Deliberately HTTP 409 (not 401): the frontend treats HTTP 401 on
    authenticated API endpoints as an expired panel JWT and would log the
    operator out instead of prompting for a GitHub re-connect.
    """

    code = "GITHUB_AUTH_FAILED"
    http_status = 409

    def __init__(
        self,
        message: str = "",
        *,
        needs_reauth: bool = True,
        auth_method: str = "",
        reason: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        merged: dict[str, Any] = {
            **(details or {}),
            "needs_reauth": bool(needs_reauth),
        }
        if auth_method:
            merged["auth_method"] = str(auth_method)[:32]
        if reason:
            merged["reason"] = str(reason)[:256]
        MCSError.__init__(
            self,
            message
            or "GitHub authentication failed; reconnect or rotate your GitHub credential",
            code="GITHUB_AUTH_FAILED",
            http_status=409,
            details=merged,
        )
        self.needs_reauth = bool(needs_reauth)


class WebhookSignatureError(AuthenticationError):
    """Raised when an inbound GitHub webhook signature is invalid or missing."""

    code = "GITHUB_WEBHOOK_SIGNATURE_INVALID"
    http_status = 401

    def __init__(
        self,
        message: str = "",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        MCSError.__init__(
            self,
            message or "Invalid or missing GitHub webhook signature",
            code="GITHUB_WEBHOOK_SIGNATURE_INVALID",
            http_status=401,
            details=dict(details or {}),
        )


class GitHubPushRejectedError(ConflictError):
    """Raised when GitHub rejects a branch push."""

    code = "GITHUB_PUSH_REJECTED"
    http_status = 409

    def __init__(
        self,
        message: str = "",
        *,
        branch: str = "",
        reason: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        merged: dict[str, Any] = dict(details or {})
        if branch:
            merged["branch"] = str(branch)[:128]
        if reason:
            merged["reason"] = str(reason)[:256]
        MCSError.__init__(
            self,
            message or "GitHub push was rejected",
            code="GITHUB_PUSH_REJECTED",
            http_status=409,
            details=merged,
        )
        self.branch = branch


# --- P5.5 Modpack, LEC & 1-Click Safe Upgrade exceptions ---


class UnsupportedForgeVersionError(ValidationError):
    """Forge is only supported for Minecraft 1.17.1 through 1.20.1."""

    code = "UNSUPPORTED_FORGE_VERSION"
    http_status = 422

    def __init__(
        self,
        minecraft_version: str = "",
        message: str = "",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged: dict[str, Any] = {
            "minecraft_version": str(minecraft_version)[:32],
            "supported_min": "1.17.1",
            "supported_max": "1.20.1",
            **(details or {}),
        }
        super().__init__(
            message
            or (
                "Forge is only supported for Minecraft 1.17.1 through 1.20.1 "
                f"(got '{str(minecraft_version)[:32]}')"
            ),
            field="minecraft_version",
            details=merged,
        )
        self.code = "UNSUPPORTED_FORGE_VERSION"
        self.http_status = 422
        self.details = merged


class CurseForgeApiKeyMissingError(ConflictError):
    """CurseForge requires an operator-configured API key.

    Deliberately HTTP 409 (never 401): the frontend treats HTTP 401 on
    authenticated panel endpoints as an expired JWT and would log the operator
    out instead of prompting for the key.
    """

    code = "CURSEFORGE_API_KEY_MISSING"
    http_status = 409

    def __init__(
        self,
        message: str = "",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        MCSError.__init__(
            self,
            message
            or (
                "CurseForge API key is not configured; set curseforge_api_key in "
                "panel settings or ONX_CURSEFORGE_API_KEY"
            ),
            code="CURSEFORGE_API_KEY_MISSING",
            http_status=409,
            details=dict(details or {}),
        )


class HostileExecutableError(ValidationError):
    """An archive member would place an executable outside an allowed jar root."""

    code = "HOSTILE_EXECUTABLE_REJECTED"
    http_status = 422

    def __init__(
        self,
        path: str = "",
        message: str = "",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        safe_path = str(path)[:128]
        merged: dict[str, Any] = {"path": safe_path, **(details or {})}
        super().__init__(
            message or f"Hostile executable rejected: '{safe_path}'",
            field="path",
            details=merged,
        )
        self.code = "HOSTILE_EXECUTABLE_REJECTED"
        self.http_status = 422
        self.details = merged
        self.path = safe_path


class UntrustedDownloadHostError(ValidationError):
    """A download URL host is not on the normative allow-list."""

    code = "UNTRUSTED_DOWNLOAD_HOST"
    http_status = 422

    def __init__(
        self,
        host: str = "",
        reason: str = "",
        message: str = "",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        safe_host = str(host)[:128]
        safe_reason = str(reason)[:256]
        merged: dict[str, Any] = {
            "host": safe_host,
            "reason": safe_reason,
            **(details or {}),
        }
        super().__init__(
            message
            or f"Untrusted download host '{safe_host}'"
            + (f": {safe_reason}" if safe_reason else ""),
            field="host",
            details=merged,
        )
        self.code = "UNTRUSTED_DOWNLOAD_HOST"
        self.http_status = 422
        self.details = merged
        self.host = safe_host
        self.reason = safe_reason


class ManualDownloadRequiredError(ConflictError):
    """A CurseForge file requires an operator drag-and-drop upload."""

    code = "MANUAL_DOWNLOAD_REQUIRED"
    http_status = 409

    def __init__(
        self,
        filename: str = "",
        webpage_url: str = "",
        message: str = "",
        *,
        expected_size: int | None = None,
        expected_sha1: str | None = None,
        expected_sha512: str | None = None,
        project_id: int | None = None,
        file_id: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        safe_filename = str(filename)[:128]
        safe_url = str(webpage_url)[:256]
        merged: dict[str, Any] = {
            "filename": safe_filename,
            "webpage_url": safe_url,
        }
        if expected_size is not None:
            merged["expected_size"] = expected_size
        if expected_sha1 is not None:
            merged["expected_sha1"] = str(expected_sha1)[:40]
        if expected_sha512 is not None:
            merged["expected_sha512"] = str(expected_sha512)[:128]
        if project_id is not None:
            merged["project_id"] = project_id
        if file_id is not None:
            merged["file_id"] = file_id
        merged.update(details or {})
        MCSError.__init__(
            self,
            message
            or (
                f"Manual download required for '{safe_filename or 'unknown file'}'; "
                "upload the verified file in the upgrade wizard"
            ),
            code="MANUAL_DOWNLOAD_REQUIRED",
            http_status=409,
            details=merged,
        )
        self.filename = safe_filename
        self.webpage_url = safe_url


class UpgradeBlockerError(ConflictError):
    """One or more upgrade-matrix blockers prevent the operation."""

    code = "UPGRADE_BLOCKED"
    http_status = 409

    def __init__(
        self,
        message: str = "",
        *,
        blockers: list[dict[str, Any]] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.blockers = list(blockers or [])
        merged: dict[str, Any] = {"blockers": self.blockers, **(details or {})}
        MCSError.__init__(
            self,
            message or "Upgrade is blocked by unresolved compatibility issues",
            code="UPGRADE_BLOCKED",
            http_status=409,
            details=merged,
        )


class LecMissingError(ConflictError):
    """A required Loader Environment Cache entry is not pre-warmed."""

    code = "LEC_MISSING"
    http_status = 409

    def __init__(
        self,
        lec_key: str = "",
        message: str = "",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        safe_key = str(lec_key)[:256]
        merged: dict[str, Any] = {"lec_key": safe_key, **(details or {})}
        MCSError.__init__(
            self,
            message or f"LEC missing: '{safe_key}' is not pre-warmed on this host",
            code="LEC_MISSING",
            http_status=409,
            details=merged,
        )
        self.lec_key = safe_key


class HealthGateFailedError(MCSError):
    """The 4-step upgrade Health Gate failed."""

    code = "HEALTH_GATE_FAILED"
    http_status = 502
    retryable = False

    def __init__(
        self,
        step: str = "",
        reason: str = "",
        message: str = "",
        *,
        rolled_back: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        safe_step = str(step)[:64]
        safe_reason = str(reason)[:256]
        merged: dict[str, Any] = {
            "step": safe_step,
            "reason": safe_reason,
            "rolled_back": bool(rolled_back),
            **(details or {}),
        }
        super().__init__(
            message or f"Health gate failed at step '{safe_step}': {safe_reason}",
            code="HEALTH_GATE_FAILED",
            http_status=502,
            retryable=False,
            details=merged,
        )


class ModpackFormatError(ValidationError):
    """A modpack archive or its index/manifest is structurally invalid."""

    code = "MODPACK_FORMAT_INVALID"
    http_status = 422

    def __init__(
        self,
        message: str = "Invalid modpack archive",
        *,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message or "Invalid modpack archive",
            field=field,
            details=details,
        )
        self.code = "MODPACK_FORMAT_INVALID"
        self.http_status = 422


class PasswordRequiredForExposureError(MCSError):
    """External exposure and non-loopback binding require configured credentials."""

    def __init__(
        self,
        message: str = "",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged: dict[str, Any] = {
            "reason": "passwordless_local_mode",
            "action": "configure_credentials",
            **(details or {}),
        }
        super().__init__(
            message
            or "An administrator username and password must be configured before enabling "
            "external tunnels or binding to a non-loopback address.",
            code="PASSWORD_REQUIRED_FOR_EXPOSURE",
            http_status=403,
            details=merged,
        )
