from __future__ import annotations

import time

import pytest

from app.core.exceptions import AuthenticationError, TokenExpiredError
from app.modules.auth.infrastructure.jwt import (
    create_access_token,
    create_refresh_token,
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
