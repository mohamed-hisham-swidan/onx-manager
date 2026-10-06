import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.exceptions import SecurityPermissionError
from app.core.security_files import ensure_private_key_permissions


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode tests")
def test_startup_tightens_existing_0644_key_file(tmp_path: Path) -> None:
    key_file = tmp_path / "test_key.pem"
    key_file.write_bytes(b"dummy-key-content")
    os.chmod(key_file, 0o644)
    assert (key_file.stat().st_mode & 0o077) != 0

    ensure_private_key_permissions(key_file)
    assert (key_file.stat().st_mode & 0o777) == 0o600


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode tests")
def test_startup_leaves_0400_key_file_alone(tmp_path: Path) -> None:
    key_file = tmp_path / "read_only_key.pem"
    key_file.write_bytes(b"dummy-key-content")
    os.chmod(key_file, 0o400)
    assert (key_file.stat().st_mode & 0o777) == 0o400

    ensure_private_key_permissions(key_file)
    assert (key_file.stat().st_mode & 0o777) == 0o400


def test_startup_skips_on_windows(tmp_path: Path) -> None:
    key_file = tmp_path / "win_key.pem"
    key_file.write_bytes(b"dummy-key-content")

    with patch("app.core.security_files.os.name", "nt"):
        # Even if stat returns 0o666, it should return cleanly without raising
        ensure_private_key_permissions(key_file)


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode tests")
def test_startup_raises_and_bypass_flag(tmp_path: Path) -> None:
    key_file = tmp_path / "stubborn_key.pem"
    key_file.write_bytes(b"dummy-key-content")
    os.chmod(key_file, 0o644)

    # Simulate a filesystem that does not change permissions (e.g. read-only mount)
    with patch("os.chmod", return_value=None):
        with pytest.raises(SecurityPermissionError):
            ensure_private_key_permissions(key_file, allow_insecure=False)

        # With allow_insecure=True, it logs CRITICAL and does not raise
        ensure_private_key_permissions(key_file, allow_insecure=True)
