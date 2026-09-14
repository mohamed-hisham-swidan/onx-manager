from __future__ import annotations

import contextlib
import logging
import os
import shutil
import subprocess
from pathlib import Path

from app.core.exceptions import StorageCowUnavailableError

logger = logging.getLogger(__name__)


class BtrfsZfsSnapshotDriver:
    """Driver for instant copy-on-write (COW) snapshotting on Btrfs and ZFS filesystems.

    Enforces Design Spec §3.3 & §3.4:
    World cloning must execute near-instantaneously via reflink block cloning
    (cp --reflink=always -r). Hardlinking (os.link) is strictly prohibited to
    prevent silent write-through corruption between test and production instances.
    """

    DEFAULT_WORLD_NAMES: list[str] = ["world", "world_nether", "world_the_end"]

    @classmethod
    def clone_world(
        cls,
        src_dir: str | Path,
        dst_dir: str | Path,
        world_names: list[str] | None = None,
    ) -> None:
        """Clones world directories from src_dir to dst_dir using reflink block cloning."""
        src_path = Path(src_dir).resolve()
        dst_path = Path(dst_dir).resolve()
        targets = world_names or cls.DEFAULT_WORLD_NAMES

        dst_path.mkdir(parents=True, exist_ok=True)

        cloned_any = False
        for w_name in targets:
            w_src = src_path / w_name
            if w_src.is_dir():
                w_dst = dst_path / w_name
                if w_dst.exists():
                    shutil.rmtree(w_dst)

                cmd = ["cp", "--reflink=always", "-r", str(w_src), str(w_dst)]
                res = subprocess.run(cmd, capture_output=True, text=True)
                if res.returncode != 0:
                    logger.error(
                        "Reflink world clone failed from %s to %s: %s",
                        w_src,
                        w_dst,
                        res.stderr,
                    )
                    raise StorageCowUnavailableError(
                        path=str(dst_dir),
                        message=(
                            f"Reflink world clone failed from '{w_src}' to '{w_dst}'. "
                            "Filesystem must support copy-on-write block cloning: "
                            f"{res.stderr.strip()}"
                        ),
                    )
                cloned_any = True

        if not cloned_any:
            logger.debug("No world directories found in %s matching %s", src_path, targets)

    @classmethod
    def create_snapshot(
        cls,
        server_dir: str | Path,
        snapshot_dir: str | Path,
        world_names: list[str] | None = None,
    ) -> int:
        """Creates a snapshot of world state into snapshot_dir. Returns size in bytes."""
        cls.clone_world(server_dir, snapshot_dir, world_names=world_names)

        total_size = 0
        s_path = Path(snapshot_dir)
        if s_path.is_dir():
            for root, _, files in os.walk(s_path):
                for f in files:
                    with contextlib.suppress(OSError):
                        total_size += (Path(root) / f).stat().st_size
        return total_size

    @classmethod
    def restore_snapshot(
        cls,
        snapshot_dir: str | Path,
        target_dir: str | Path,
        world_names: list[str] | None = None,
    ) -> None:
        """Restores world directories from snapshot_dir into target_dir using reflink clone."""
        cls.clone_world(snapshot_dir, target_dir, world_names=world_names)
