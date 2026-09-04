import json

import pytest

from app.core.exceptions import AuthenticationError, TokenExpiredError
from app.modules.auth.infrastructure.jwt import (
    _unb64,
    create_access_token,
    create_refresh_token,
    get_key_id,
    verify_access_token,
    verify_ws_token,
)


class TestJWT:
    def test_create_and_verify_access_token(self) -> None:
        token = create_access_token(
            user_id="user_abc123",
            roles=["operator"],
            permissions=["server:read", "server:write"],
        )
        assert isinstance(token, str)
        assert len(token.split(".")) == 3

        claims = verify_access_token(token)
        assert claims["sub"] == "user_abc123"
        assert claims["roles"] == ["operator"]
        assert "server:read" in claims["permissions"]

    def test_access_token_header_includes_kid(self) -> None:
        token = create_access_token(user_id="user_kid_test")
        header_b64 = token.split(".")[0]
        header = json.loads(_unb64(header_b64).decode())
        assert "kid" in header
        assert header["kid"] == get_key_id()
        assert header["alg"] == "RS256"

    def test_token_expiration(self) -> None:
        token = create_access_token(user_id="test", ttl_seconds=0)
        with pytest.raises(TokenExpiredError):
            verify_access_token(token)

    def test_invalid_signature(self) -> None:
        token = create_access_token(user_id="test")
        parts = token.split(".")
        tampered = f"{parts[0]}.{parts[1]}.invalidsig"
        with pytest.raises(AuthenticationError):
            verify_access_token(tampered)

    def test_invalid_format(self) -> None:
        with pytest.raises(AuthenticationError):
            verify_access_token("not-a-jwt")

        with pytest.raises(AuthenticationError):
            verify_access_token("part1.part2")

    def test_empty_token(self) -> None:
        with pytest.raises(AuthenticationError):
            verify_access_token("")

    def test_verify_ws_token(self) -> None:
        token = create_access_token(
            user_id="user_xyz",
            permissions=["server:read", "backup:create"],
        )
        result = verify_ws_token(token)
        assert result["user_id"] == "user_xyz"
        assert "server:read" in result["permissions"]
        assert "backup:create" in result["permissions"]

    def test_create_refresh_token(self) -> None:
        token = create_refresh_token()
        assert isinstance(token, str)
        assert len(token) > 20
        token2 = create_refresh_token()
        assert token != token2

    def test_persisted_jwt_key_file_permissions_are_0600(self, tmp_path, monkeypatch) -> None:
        import sys

        from app.core.config import AppSettings
        from app.modules.auth.infrastructure import jwt

        key_file = tmp_path / "jwt_test_key.pem"
        monkeypatch.setattr(jwt, "_DEFAULT_KEY_PATH", key_file)
        monkeypatch.setattr(jwt, "_private_key", None)
        monkeypatch.setattr(jwt, "_public_key", None)
        monkeypatch.setattr(jwt, "_key_id", None)

        settings = AppSettings(
            jwt_private_key="",
            jwt_private_key_path="",
        )
        jwt.init_jwt_from_settings(settings)

        assert key_file.exists()
        if sys.platform != "win32":
            mode = key_file.stat().st_mode & 0o777
            assert mode == 0o600
