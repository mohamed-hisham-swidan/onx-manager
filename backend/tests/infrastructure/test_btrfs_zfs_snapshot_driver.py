import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.exceptions import StorageCowUnavailableError
from app.modules.versioning.infrastructure.btrfs_zfs_driver import BtrfsZfsSnapshotDriver


def test_btrfs_zfs_driver_clone_world_invokes_reflink() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "src"
        dst = Path(tmpdir) / "dst"
        world_dir = src / "world"
        world_dir.mkdir(parents=True)
        (world_dir / "level.dat").write_bytes(b"worlddata")

        # Mock subprocess.run to simulate success
        mock_proc = MagicMock(returncode=0)
        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            BtrfsZfsSnapshotDriver.clone_world(src, dst, world_names=["world"])

            assert mock_run.called
            args = mock_run.call_args[0][0]
            assert args[0] == "cp"
            assert "--reflink=always" in args
            assert "-r" in args
            assert str(world_dir) in args
            assert str(dst / "world") in args


def test_btrfs_zfs_driver_clone_world_failure_raises_storage_cow_error() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "src"
        dst = Path(tmpdir) / "dst"
        world_dir = src / "world"
        world_dir.mkdir(parents=True)

        mock_proc = MagicMock(
            returncode=1,
            stderr="cp: failed to clone: Operation not supported",
        )
        with patch("subprocess.run", return_value=mock_proc):
            with pytest.raises(StorageCowUnavailableError) as exc_info:
                BtrfsZfsSnapshotDriver.clone_world(src, dst, world_names=["world"])

            err = exc_info.value
            assert err.code == "STORAGE_COW_UNAVAILABLE"
            assert "reflink" in err.message.lower() or "copy-on-write" in err.message.lower()


def test_btrfs_zfs_driver_snapshot_creation_and_restore_cycle() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "live"
        snapshot = Path(tmpdir) / "snapshot"
        restored = Path(tmpdir) / "restored"

        world = src / "world"
        world.mkdir(parents=True)
        (world / "level.dat").write_bytes(b"12345678")

        def fake_cp(cmd, **_kwargs):
            # cmd is ["cp", "--reflink=always", "-r", src_w, dst_w]
            dst_w = Path(cmd[4])
            dst_w.mkdir(parents=True, exist_ok=True)
            (dst_w / "level.dat").write_bytes(b"cloned")
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=fake_cp) as mock_run:
            # Create snapshot
            size = BtrfsZfsSnapshotDriver.create_snapshot(src, snapshot, world_names=["world"])
            assert isinstance(size, int)
            assert (snapshot / "world").is_dir()

            # Restore snapshot
            BtrfsZfsSnapshotDriver.restore_snapshot(snapshot, restored, world_names=["world"])
            assert (restored / "world").is_dir()
            assert mock_run.call_count == 2


def test_btrfs_zfs_driver_clone_world_timeout_raises_storage_cow_error() -> None:
    import subprocess

    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "src"
        dst = Path(tmpdir) / "dst"
        world_dir = src / "world"
        world_dir.mkdir(parents=True)

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="cp", timeout=300)):
            with pytest.raises(StorageCowUnavailableError) as exc_info:
                BtrfsZfsSnapshotDriver.clone_world(src, dst, world_names=["world"])

            err = exc_info.value
            assert err.code == "STORAGE_COW_UNAVAILABLE"
            assert "timed out" in err.message.lower()
