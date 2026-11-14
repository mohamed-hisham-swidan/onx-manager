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


class GuardConfigurationError(MCSError):
    def __init__(self, message: str = "") -> None:
        super().__init__(
            message or "Mode guard requires exactly one mode source",
            code="GUARD_CONFIGURATION_ERROR",
            http_status=500,
        )


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
            f"Versioning and isolated testing requires a Btrfs or ZFS filesystem supporting "
            f"copy-on-write on the server data path. Your server data directory ({path or 'unknown'}) "
            f"does not support reflink cloning. Standard server management remains fully available."
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
