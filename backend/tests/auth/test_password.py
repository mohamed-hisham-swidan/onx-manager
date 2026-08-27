from __future__ import annotations

from app.core.security import hash_password, verify_password


class TestPasswordHashing:
    def test_hash_and_verify(self) -> None:
        password = "MySecureP@ssw0rd!"
        hashed = hash_password(password)
        assert hashed != password
        assert ":" in hashed
        assert verify_password(password, hashed) is True

    def test_wrong_password_fails(self) -> None:
        hashed = hash_password("correct-password")
        assert verify_password("wrong-password", hashed) is False

    def test_same_password_different_hashes(self) -> None:
        h1 = hash_password("same-password")
        h2 = hash_password("same-password")
        assert h1 != h2

    def test_empty_password(self) -> None:
        hashed = hash_password("")
        assert verify_password("", hashed) is True

    def test_invalid_hash_format(self) -> None:
        assert verify_password("password", "invalid-hash") is False

    def test_long_password(self) -> None:
        long_pw = "a" * 1000
        hashed = hash_password(long_pw)
        assert verify_password(long_pw, hashed) is True
