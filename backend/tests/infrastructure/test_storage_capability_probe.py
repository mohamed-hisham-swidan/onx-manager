import builtins
import importlib
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.exceptions import StorageCowUnavailableError
from app.modules.versioning.infrastructure.storage_probe import StorageCapabilityProbe


def test_storage_capability_probe_success_path() -> None:
    with (
        tempfile.TemporaryDirectory() as tmpdir,
        patch.object(StorageCapabilityProbe, "probe_path", return_value=True),
    ):
        assert StorageCapabilityProbe.probe_path(tmpdir) is True
        # assert_supports_reflink should not raise
        StorageCapabilityProbe.assert_supports_reflink(tmpdir)


def test_storage_capability_probe_failure_raises_412() -> None:
    with (
        tempfile.TemporaryDirectory() as tmpdir,
        patch.object(StorageCapabilityProbe, "probe_path", return_value=False),
    ):
        assert StorageCapabilityProbe.probe_path(tmpdir) is False
        with pytest.raises(StorageCowUnavailableError) as exc_info:
            StorageCapabilityProbe.assert_supports_reflink(tmpdir)

            err = exc_info.value
            assert err.http_status == 412
            assert err.code == "STORAGE_COW_UNAVAILABLE"
            assert "Btrfs or ZFS" in err.message
            assert str(tmpdir) in err.message or err.details.get("path") == str(tmpdir)


def test_storage_capability_probe_real_filesystem_execution() -> None:
    """Runs the real probe against a real temp directory without mocks.

    Depending on whether the host filesystem supports reflink (e.g. Btrfs vs ext4),
    it will return True or False, but must NOT crash or leave dangling files.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        res = StorageCapabilityProbe.probe_path(tmpdir)
        assert isinstance(res, bool)
        # Probe files should be cleanly removed
        probe_dir = Path(tmpdir) / ".onx" / "probe"
        assert not (probe_dir / "probe_src.bin").exists()
        assert not (probe_dir / "probe_dst.bin").exists()


def test_storage_probe_imports_without_fcntl_simulated_windows() -> None:
    """Simulates Windows (no fcntl module): the probe module must still import,
    and probe_path must degrade to the `cp` CLI fallback instead of crashing.
    """
    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "fcntl":
            raise ImportError("No module named 'fcntl' (simulated Windows)")
        return real_import(name, *args, **kwargs)

    module_name = "app.modules.versioning.infrastructure.storage_probe"
    with patch.object(builtins, "__import__", side_effect=fake_import):
        saved = sys.modules.pop(module_name, None)
        try:
            module = importlib.import_module(module_name)
        finally:
            sys.modules.pop(module_name, None)
            if saved is not None:
                sys.modules[module_name] = saved
    assert module.fcntl is None
    # probe_path must not crash; returns a bool via the `cp` fallback path
    with tempfile.TemporaryDirectory() as tmpdir:
        assert isinstance(module.StorageCapabilityProbe.probe_path(tmpdir), bool)
