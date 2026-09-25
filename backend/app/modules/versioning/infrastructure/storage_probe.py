from __future__ import annotations

import contextlib
import logging
import os
import subprocess
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows has no fcntl; ioctl probe is skipped, `cp` fallback still runs
    fcntl = None  # type: ignore[assignment]

from app.core.exceptions import StorageCowUnavailableError

logger = logging.getLogger(__name__)

# Linux FICLONE ioctl constant (man 2 ioctl_ficlone)
# _IOW(0x94, 9, int) on 32/64-bit Linux is 0x40049409
FICLONE = 0x40049409


class StorageCapabilityProbe:
    """Preflight probe for copy-on-write (COW) reflink capability.

    Enforces Design Spec §3.3:
    Versioning and isolated testing requires a filesystem supporting reflink block cloning
    (Btrfs or ZFS). Hardlinks (os.link) are strictly forbidden for world files.
    """

    @classmethod
    def probe_path(cls, base_dir: str | Path) -> bool:
        """Probes whether base_dir supports instant copy-on-write reflink cloning.

        Returns True if FICLONE / reflink succeeds, False otherwise.
        """
        probe_dir = Path(base_dir) / ".onx" / "probe"
        try:
            probe_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("Could not create probe directory %s: %s", probe_dir, e)
            return False

        src_file = probe_dir / "probe_src.bin"
        dst_file = probe_dir / "probe_dst.bin"

        try:
            # 1. Write 4KB test pattern
            test_data = b"ONX_COW_PROBE_DATA" * 256  # 4608 bytes (~4.5KB)
            with open(src_file, "wb") as f:
                f.write(test_data)
                f.flush()
                os.fsync(f.fileno())

            # 2. Attempt FICLONE ioctl first (pure Python, lowest overhead on Linux)
            if fcntl is not None and hasattr(fcntl, "ioctl"):
                try:
                    with open(src_file, "rb") as s_fd, open(dst_file, "wb") as d_fd:
                        fcntl.ioctl(d_fd.fileno(), FICLONE, s_fd.fileno())
                    # Check size matches
                    if dst_file.stat().st_size == len(test_data):
                        return True
                except OSError as ioctl_err:
                    logger.debug("FICLONE ioctl failed on %s: %s", probe_dir, ioctl_err)

            # 3. Fallback to `cp --reflink=always` CLI execution
            if dst_file.exists():
                with contextlib.suppress(OSError):
                    dst_file.unlink()

            res = subprocess.run(
                ["cp", "--reflink=always", str(src_file), str(dst_file)],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return res.returncode == 0
        except Exception as e:
            logger.debug("Reflink probe failed for %s: %s", base_dir, e)
            return False
        finally:
            for p in (src_file, dst_file):
                try:
                    if p.exists():
                        p.unlink()
                except OSError:
                    pass
            try:
                if probe_dir.exists() and not any(probe_dir.iterdir()):
                    probe_dir.rmdir()
            except OSError:
                pass

    @classmethod
    def assert_supports_reflink(cls, base_dir: str | Path) -> None:
        """Asserts that base_dir supports reflink, raising
        StorageCowUnavailableError (HTTP 412) if not.
        """
        if not cls.probe_path(base_dir):
            raise StorageCowUnavailableError(path=str(base_dir))
