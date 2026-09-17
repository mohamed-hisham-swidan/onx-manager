import contextlib
import os
import shutil
import uuid
from pathlib import Path


def atomic_write_file(dst: str | Path, content: str | bytes) -> int:
    """Write content to a file atomically within the same directory.

    Avoids leaving half-written files by writing to a hidden sibling temporary file
    and replacing the destination with os.replace().
    """
    dst_path = Path(dst)
    parent = dst_path.parent
    parent.mkdir(parents=True, exist_ok=True)

    tmp_path = parent / f".{dst_path.name}.{uuid.uuid4().hex}.tmp"
    data = content.encode("utf-8") if isinstance(content, str) else content

    try:
        with open(tmp_path, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, dst_path)
    finally:
        if os.path.lexists(tmp_path):
            with contextlib.suppress(Exception):
                os.unlink(tmp_path)

    return len(data)


def atomic_replace_file(src: str | Path, dst: str | Path) -> None:
    """Replace a destination file with src atomically using same-parent staging."""
    src_path = Path(src)
    dst_path = Path(dst)
    parent = dst_path.parent
    parent.mkdir(parents=True, exist_ok=True)

    tmp_path = parent / f".{dst_path.name}.{uuid.uuid4().hex}.tmp"
    try:
        shutil.copy2(src_path, tmp_path)
        os.replace(tmp_path, dst_path)
    finally:
        if os.path.lexists(tmp_path):
            with contextlib.suppress(Exception):
                os.unlink(tmp_path)


def atomic_replace_dir(src: str | Path, dst: str | Path) -> None:
    """Swap src directory into dst atomically without leaving half-written folders.

    Stages src into dst's parent directory first (via shutil.move) to eliminate
    EXDEV errors when src is on a different mount. Then performs an atomic swap
    within the same parent folder with rollback on failure.
    """
    src_str = str(src)
    dst_str = str(dst)
    parent = os.path.dirname(os.path.abspath(dst_str))
    os.makedirs(parent, exist_ok=True)

    base = os.path.basename(dst_str)
    uid = uuid.uuid4().hex
    temp_stage = os.path.join(parent, f".{base}.stage_{uid}")
    old_path = os.path.join(parent, f".{base}.old_{uid}")

    if os.path.lexists(temp_stage):
        shutil.rmtree(temp_stage, ignore_errors=True)
    if os.path.lexists(old_path):
        shutil.rmtree(old_path, ignore_errors=True)

    shutil.move(src_str, temp_stage)
    try:
        if os.path.lexists(dst_str):
            os.replace(dst_str, old_path)
        try:
            os.replace(temp_stage, dst_str)
        except BaseException:
            if os.path.lexists(old_path):
                os.replace(old_path, dst_str)
            raise
    finally:
        if os.path.lexists(temp_stage):
            shutil.rmtree(temp_stage, ignore_errors=True)
        if os.path.lexists(old_path):
            shutil.rmtree(old_path, ignore_errors=True)

