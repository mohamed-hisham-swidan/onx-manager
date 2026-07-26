from app.core.security import (
    decrypt_data,
    encrypt_data,
    generate_api_key,
    generate_encryption_key,
    hash_api_key,
    hash_password,
    verify_api_key,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_and_verify(self) -> None:
        hashed = hash_password("correct-horse-battery-staple")
        assert verify_password("correct-horse-battery-staple", hashed) is True

    def test_wrong_password_fails(self) -> None:
        hashed = hash_password("real-password")
        assert verify_password("wrong-password", hashed) is False

    def test_different_salts(self) -> None:
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2


class TestApiKeyHashing:
    def test_hash_and_verify(self) -> None:
        key = "mcs_test-key-123"
        hashed = hash_api_key(key)
        assert verify_api_key(key, hashed) is True

    def test_wrong_key_fails(self) -> None:
        hashed = hash_api_key("real-key")
        assert verify_api_key("fake-key", hashed) is False

    def test_generate_key_format(self) -> None:
        key = generate_api_key()
        assert key.startswith("mcs_")
        assert len(key) > 32


class TestEncryption:
    def test_encrypt_decrypt(self) -> None:
        key = generate_encryption_key()
        original = b"sensitive backup data"
        encrypted = encrypt_data(original, key)
        assert encrypted != original
        decrypted = decrypt_data(encrypted, key)
        assert decrypted == original

    def test_wrong_key_fails(self) -> None:
        key1 = generate_encryption_key()
        key2 = generate_encryption_key()
        encrypted = encrypt_data(b"secret", key1)
        import pytest
        with pytest.raises(Exception):
            decrypt_data(encrypted, key2)
