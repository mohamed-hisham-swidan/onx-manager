from app.core.exceptions import (
    AuthenticationError,
    ConflictError,
    CorruptedDownloadError,
    DatabaseConnectionError,
    DownloadError,
    DownloadTimeoutError,
    DuplicateResourceError,
    FieldRequiredError,
    FilesystemOperationError,
    InfrastructureError,
    InternalError,
    InvalidCredentialsError,
    InvalidValueError,
    MCSError,
    NotFoundError,
    PermissionDenied,
    ProviderError,
    ProvisioningError,
    RateLimitExceeded,
    ServerNotFoundError,
    TokenExpiredError,
    ValidationError,
    VersionNotFoundError,
)


class TestMCSError:
    def test_base_error_defaults(self) -> None:
        err = MCSError()
        assert err.code == "MCSError"
        assert err.message == ""
        assert err.details == {}
        assert err.http_status == 500
        assert err.retryable is False

    def test_base_error_custom(self) -> None:
        err = MCSError(
            "test", code="CUSTOM", details={"key": "val"}, http_status=400, retryable=True
        )
        assert err.code == "CUSTOM"
        assert err.message == "test"
        assert err.details == {"key": "val"}
        assert err.http_status == 400
        assert err.retryable is True

    def test_str_representation(self) -> None:
        err = MCSError("something broke")
        assert str(err) == "something broke"


class TestValidationErrors:
    def test_validation_error(self) -> None:
        err = ValidationError("bad input", field="name")
        assert err.code == "VALIDATION_ERROR"
        assert err.http_status == 422
        assert err.details["field"] == "name"

    def test_field_required(self) -> None:
        err = FieldRequiredError("email")
        assert "email" in str(err)
        assert err.details["field"] == "email"

    def test_invalid_value(self) -> None:
        err = InvalidValueError("age", -5, "must be positive")
        assert str(err) != ""
        assert err.details["field"] == "age"
        assert err.details["value"] == -5


class TestAuthenticationErrors:
    def test_authentication_error(self) -> None:
        err = AuthenticationError()
        assert err.http_status == 401

    def test_invalid_credentials(self) -> None:
        err = InvalidCredentialsError()
        assert "Invalid credentials" in str(err)

    def test_token_expired(self) -> None:
        err = TokenExpiredError()
        assert "expired" in str(err)


class TestPermissionDenied:
    def test_default_message(self) -> None:
        err = PermissionDenied()
        assert err.http_status == 403
        assert "Permission denied" in str(err)

    def test_custom_message(self) -> None:
        err = PermissionDenied("no access")
        assert "no access" in str(err)


class TestNotFoundErrors:
    def test_not_found(self) -> None:
        err = NotFoundError()
        assert err.http_status == 404

    def test_server_not_found(self) -> None:
        err = ServerNotFoundError("srv-1")
        assert "srv-1" in str(err)


class TestConflictErrors:
    def test_conflict_error(self) -> None:
        err = ConflictError()
        assert err.http_status == 409

    def test_duplicate_resource(self) -> None:
        err = DuplicateResourceError("Server", "srv-1")
        assert "srv-1" in str(err)


class TestRateLimit:
    def test_rate_limit_exceeded(self) -> None:
        err = RateLimitExceeded(retry_after=30)
        assert err.http_status == 429
        assert err.details["retry_after"] == 30


class TestInfrastructureErrors:
    def test_infrastructure_error(self) -> None:
        err = InfrastructureError("db down", details={"reason": "unreachable"})
        assert err.http_status == 503
        assert err.retryable is True
        assert err.details == {"reason": "unreachable"}

    def test_database_connection_error(self) -> None:
        err = DatabaseConnectionError("timeout")
        assert "timeout" in str(err)
        assert err.details == {"detail": "timeout"}

    def test_provider_error(self) -> None:
        err = ProviderError("docker", "start", "port conflict")
        assert "docker" in str(err)
        assert "start" in str(err)
        assert err.details["provider"] == "docker"
        assert err.details["operation"] == "start"
        assert err.details["detail"] == "port conflict"

    def test_provisioning_error_details(self) -> None:
        err = ProvisioningError("disk full", server_id="srv-123")
        assert err.details["server_id"] == "srv-123"

    def test_download_error_details(self) -> None:
        err = DownloadError("https://example.com/srv.jar", 404, "not found")
        assert err.details["url"] == "https://example.com/srv.jar"
        assert err.details["status"] == 404
        assert err.details["detail"] == "not found"

    def test_download_timeout_error_details(self) -> None:
        err = DownloadTimeoutError("https://example.com/srv.jar", 30)
        assert err.details["url"] == "https://example.com/srv.jar"
        assert err.details["timeout_seconds"] == 30

    def test_corrupted_download_error_details(self) -> None:
        err = CorruptedDownloadError("/path/to/jar", "bad header")
        assert err.details["path"] == "/path/to/jar"
        assert err.details["reason"] == "bad header"

    def test_filesystem_operation_error_details(self) -> None:
        err = FilesystemOperationError("/path/to/dir", "delete", "permission denied")
        assert err.details["path"] == "/path/to/dir"
        assert err.details["operation"] == "delete"
        assert err.details["detail"] == "permission denied"

    def test_version_not_found_error_details(self) -> None:
        err = VersionNotFoundError("1.99", "paper")
        assert err.details["minecraft_version"] == "1.99"
        assert err.details["server_type"] == "paper"


class TestInternalError:
    def test_internal_error(self) -> None:
        err = InternalError("unexpected")
        assert err.http_status == 500
        assert err.code == "INTERNAL_ERROR"
