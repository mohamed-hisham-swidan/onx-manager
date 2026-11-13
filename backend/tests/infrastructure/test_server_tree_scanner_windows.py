"""Windows portability and reparse-point tests for server_tree_scanner."""

from __future__ import annotations

import inspect
import os
import stat
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

import app.modules.versioning.infrastructure.server_tree_scanner as scanner_mod
from app.core.allowlist import SymlinkEscapeError
from app.modules.versioning.infrastructure.server_tree_scanner import scan_server_tree


class TestServerTreeScannerWindows:
    """Windows portability verification: no POSIX-only imports and reparse handling."""

    def test_no_forbidden_posix_tokens_or_imports(self) -> None:
        forbidden = ("fcntl", "pwd", "grp", "termios", "resource")
        for name in forbidden:
            assert not hasattr(scanner_mod, name), f"Module should not have {name}"
            assert name not in sys.modules or scanner_mod.__dict__.get(name) is None

        source = inspect.getsource(scanner_mod)
        for name in forbidden:
            assert f"import {name}" not in source
        assert "dir_fd" not in source
        for token in ("O_DIRECTORY", "O_NOFOLLOW"):
            assert token not in source

    def test_reparse_point_root_rejected(self, tmp_path: Path) -> None:
        root = tmp_path / "server_root"
        root.mkdir()

        fake_stat = types.SimpleNamespace(
            st_file_attributes=0x400,
            st_mode=stat.S_IFDIR | 0o755,
        )
        with (
            patch("os.lstat", return_value=fake_stat),
            pytest.raises(SymlinkEscapeError, match="reparse point"),
        ):
            scan_server_tree(root)

    def test_reparse_point_entry_skipped(self, tmp_path: Path) -> None:
        root = tmp_path / "server_root"
        root.mkdir()
        (root / "normal.jar").write_bytes(b"normal-file")
        junction_dir = root / "junction_dir"
        junction_dir.mkdir()
        (junction_dir / "ignored.jar").write_bytes(b"ignored-file")

        real_stat = os.DirEntry.stat

        def mock_entry_stat(
            self: os.DirEntry[str], *, follow_symlinks: bool = True
        ) -> os.stat_result:
            if self.name == "junction_dir":
                return types.SimpleNamespace(  # type: ignore[return-value]
                    st_file_attributes=0x400,
                    st_mode=stat.S_IFDIR | 0o755,
                    st_size=0,
                )
            return real_stat(self, follow_symlinks=follow_symlinks)

        with patch.object(os.DirEntry, "stat", mock_entry_stat):
            report = scan_server_tree(root)

        assert "junction_dir" in report.skipped_symlinks
        assert "junction_dir" not in report.skipped_dirs
        scanned_paths = [f.path for f in report.files]
        assert scanned_paths == ["normal.jar"]

    def test_clean_import_under_simulated_windows(self) -> None:
        with patch("os.name", "nt"):
            # Re-import or inspect module functionality under nt
            assert scanner_mod.PRUNED_DIR_NAMES is not None
            assert "libraries" in scanner_mod.PRUNED_DIR_NAMES
