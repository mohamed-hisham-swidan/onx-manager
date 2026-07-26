import pytest

from app.core.exceptions import (
    AuthenticationError,
    ConflictError,
    DatabaseConnectionError,
    DuplicateResourceError,
    FieldRequiredError,
    InfrastructureError,
    InternalError,
    InvalidCredentialsError,
    InvalidValueError,
    MCSError,
    NotFoundError,
    PermissionDenied,
    ProviderError,
    RateLimitExceeded,
    ServerNotFoundError,
    TokenExpiredError,
    ValidationError,
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
        err = MCSError("test", code="CUSTOM", details={"key": "val"}, http_status=400, retryable=True)
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
        err = InfrastructureError("db down")
        assert err.http_status == 503
        assert err.retryable is True

    def test_database_connection_error(self) -> None:
        err = DatabaseConnectionError("timeout")
        assert "timeout" in str(err)

    def test_provider_error(self) -> None:
        err = ProviderError("docker", "start", "port conflict")
        assert "docker" in str(err)
        assert "start" in str(err)


class TestInternalError:
    def test_internal_error(self) -> None:
        err = InternalError("unexpected")
        assert err.http_status == 500
        assert err.code == "INTERNAL_ERROR"
