import io
import os
import stat
import time
import zipfile
from pathlib import Path

import pytest

from app.modules.server.application.services.import_service import (
    _safe_extract_zip,
    cleanup_old_staging_directories,
)
from app.modules.server.infrastructure.fs import LocalFileSystem

pytest_plugins = ["tests.api.test_api_endpoints"]


def _make_zip(entries: dict[str, bytes | zipfile.ZipInfo]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            if isinstance(data, zipfile.ZipInfo):
                zf.writestr(data, b"")
            else:
                zf.writestr(name, data)
    return buf.getvalue()


def test_zip_extract_rejects_symlink(tmp_path: Path):
    zinfo = zipfile.ZipInfo("link_entry")
    zinfo.external_attr = (stat.S_IFLNK | 0o777) << 16
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(zinfo, b"/etc/passwd")
    zip_bytes = buf.getvalue()
    zp = tmp_path / "symlink.zip"
    zp.write_bytes(zip_bytes)
    out = tmp_path / "out"
    out.mkdir()

    with pytest.raises(ValueError, match="symlink|device|unsafe|forbidden"):
        _safe_extract_zip(zp, out)


def test_zip_extract_rejects_zip_bomb_ratio(tmp_path: Path):
    # Highly compressible stream exceeding ratio
    large_zeros = b"\x00" * 2_000_000
    zip_bytes = _make_zip({"zeros.bin": large_zeros})
    zp = tmp_path / "bomb.zip"
    zp.write_bytes(zip_bytes)
    out = tmp_path / "out"
    out.mkdir()

    with pytest.raises(ValueError, match="compression ratio|exceeds limit"):
        _safe_extract_zip(zp, out)


def test_zip_extract_rejects_absolute_path(tmp_path: Path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("/etc/passwd", b"root:x:0:0")
    zp = tmp_path / "abs.zip"
    zp.write_bytes(buf.getvalue())
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(ValueError, match="Absolute path|traversal|unsafe"):
        _safe_extract_zip(zp, out)


def test_zip_extract_rejects_traversal(tmp_path: Path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("sub/../../escaped.txt", b"evil")
    zp = tmp_path / "trav.zip"
    zp.write_bytes(buf.getvalue())
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(ValueError, match="traversal|Path traversal"):
        _safe_extract_zip(zp, out)


def test_zip_extract_rejects_member_cap(tmp_path: Path, monkeypatch):
    import app.modules.server.application.services.import_service as srv_mod
    monkeypatch.setattr(srv_mod, "MAX_ZIP_MEMBERS", 3)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i in range(5):
            zf.writestr(f"f_{i}.txt", b"ok")
    zp = tmp_path / "many.zip"
    zp.write_bytes(buf.getvalue())
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(ValueError, match="member count .* exceeds limit"):
        _safe_extract_zip(zp, out)


def test_zip_extract_rejects_uncompressed_bytes_cap(tmp_path: Path, monkeypatch):
    import app.modules.server.application.services.import_service as srv_mod
    monkeypatch.setattr(srv_mod, "MAX_ZIP_UNCOMPRESSED_BYTES", 50)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("f.txt", b"A" * 100)
    zp = tmp_path / "big.zip"
    zp.write_bytes(buf.getvalue())
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(ValueError, match="uncompressed size exceeds limit"):
        _safe_extract_zip(zp, out)


def test_copy_dir_never_follows_symlink(tmp_path: Path):
    src = tmp_path / "staging"
    src.mkdir()
    (src / "real.txt").write_text("hello")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")

    # Create symlink inside staging pointing outside
    link = src / "link.txt"
    link.symlink_to(outside)

    dest = tmp_path / "dest"
    fs = LocalFileSystem()
    fs.copy_dir(str(src), str(dest))

    assert (dest / "real.txt").read_text() == "hello"
    # The symlink target content must NOT be copied as a normal file
    assert not (dest / "link.txt").is_file() or (dest / "link.txt").is_symlink()
    if (dest / "link.txt").exists():
        assert (dest / "link.txt").is_symlink()


def test_staging_cleanup_sweep_removes_old_dirs(tmp_path: Path):
    staging = tmp_path / "staging"
    staging.mkdir()
    old_dir = staging / "old_import"
    old_dir.mkdir()
    new_dir = staging / "new_import"
    new_dir.mkdir()

    # Artificially age old_dir to 25 hours ago
    past = time.time() - (25 * 3600)
    os.utime(old_dir, (past, past))

    cleaned = cleanup_old_staging_directories(staging, max_age_seconds=24 * 3600)
    assert cleaned == 1
    assert not old_dir.exists()
    assert new_dir.exists()


def test_staging_cleanup_sweep_safe_when_dir_missing(tmp_path: Path):
    non_existent = tmp_path / "does_not_exist"
    cleaned = cleanup_old_staging_directories(non_existent)
    assert cleaned == 0
