from __future__ import annotations

from app.core.security import generate_api_key, hash_api_key, verify_api_key


class TestApiKeyGeneration:
    def test_generate_api_key(self) -> None:
        key = generate_api_key()
        assert key.startswith("mcs_")
        assert len(key) > 10

    def test_hash_and_verify(self) -> None:
        key = generate_api_key()
        hashed = hash_api_key(key)
        assert isinstance(hashed, str)
        assert len(hashed) == 64
        assert verify_api_key(key, hashed) is True

    def test_wrong_key_fails_verification(self) -> None:
        key = generate_api_key()
        hashed = hash_api_key(key)
        assert verify_api_key("wrong-key", hashed) is False

    def test_unique_keys(self) -> None:
        keys = {generate_api_key() for _ in range(100)}
        assert len(keys) == 100
