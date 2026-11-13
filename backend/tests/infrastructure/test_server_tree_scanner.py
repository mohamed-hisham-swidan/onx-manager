"""Tests for server tree scanner core and allow-list v2.3 integration."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.allowlist import SymlinkEscapeError
from app.core.exceptions import CaseCollisionError
from app.modules.versioning.infrastructure.server_tree_scanner import (
    ScanReport,
    scan_server_tree,
)


def _build_synthetic_tree(root: Path) -> None:
    """Populate root with the canonical B4c synthetic server tree."""
    # Files
    (root / "server.jar").write_bytes(b"server-jar")
    (root / "run.sh").write_bytes(b"run-script")
    (root / "eula.txt").write_bytes(b"eula=true")

    # Plugins
    plugins_dir = root / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    (plugins_dir / "a.jar").write_bytes(b"plugin-a")

    # Mods
    mods_dir = root / "mods"
    mods_nested = mods_dir / "nested"
    mods_nested.mkdir(parents=True, exist_ok=True)
    (mods_dir / "b.jar").write_bytes(b"mod-b")
    (mods_nested / "c.jar").write_bytes(b"mod-c")

    # Shaderpacks
    shader_dir = root / "shaderpacks"
    shader_dir.mkdir(parents=True, exist_ok=True)
    (shader_dir / "pack.zip").write_bytes(b"shaderpack-zip")

    # Config
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "settings.yml").write_bytes(b"settings: true")
    (config_dir / "evil.jar").write_bytes(b"evil-payload")

    # World
    world_region = root / "world" / "region"
    world_region.mkdir(parents=True, exist_ok=True)
    (world_region / "r.0.0.mca").write_bytes(b"region-data")

    # Pruned directories
    lib_dir = root / "libraries" / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    (lib_dir / "x.jar").write_bytes(b"library-x")


class TestServerTreeScanner:
    """Unit tests covering the server tree scanner contract."""

    def test_synthetic_tree_classification_and_quarantine(self, tmp_path: Path) -> None:
        root = tmp_path / "server"
        root.mkdir()
        _build_synthetic_tree(root)

        report = scan_server_tree(root)
        assert isinstance(report, ScanReport)
        assert report.root == root
        assert report.truncated is False

        # Quarantined file check
        assert report.quarantined == ("config/evil.jar",)
        evil_file = next(f for f in report.files if f.path == "config/evil.jar")
        assert evil_file.classification == "QUARANTINE"

        # Classification counts:
        # server.jar, plugins/a.jar, mods/b.jar, mods/nested/c.jar
        assert report.by_class["A-JAR"] == 4
        assert report.by_class["A-CAS"] == 1  # shaderpacks/pack.zip
        assert report.by_class["B"] == 1  # config/settings.yml
        assert report.by_class["E"] == 3  # run.sh, eula.txt, world/region/r.0.0.mca
        assert report.by_class["QUARANTINE"] == 1  # config/evil.jar
        assert report.by_class["A-LOCKFILE"] == 0
        assert report.by_class["C"] == 0

        # Exact total files: 10 files (libraries/lib/x.jar is pruned)
        assert len(report.files) == 10
        assert sum(report.by_class.values()) == 10
        assert report.total_bytes == sum(f.size for f in report.files)

    def test_pruned_directories(self, tmp_path: Path) -> None:
        root = tmp_path / "server"
        root.mkdir()
        _build_synthetic_tree(root)

        # Add more pruned dirs at different depths
        (root / ".git").mkdir()
        (root / ".git" / "config").write_bytes(b"git-config")
        (root / "plugins" / "cache").mkdir()
        (root / "plugins" / "cache" / "temp.dat").write_bytes(b"cache-data")

        report = scan_server_tree(root)

        assert "libraries" in report.skipped_dirs
        assert ".git" in report.skipped_dirs
        assert "plugins/cache" in report.skipped_dirs

        scanned_paths = [f.path for f in report.files]
        assert not any(p.startswith("libraries/") for p in scanned_paths)
        assert not any(p.startswith(".git/") for p in scanned_paths)
        assert not any(p.startswith("plugins/cache/") for p in scanned_paths)

    @pytest.mark.skipif(os.name != "posix", reason="POSIX symlinks only")
    def test_symlinked_file_and_directory_skipped_not_visited(self, tmp_path: Path) -> None:
        root = tmp_path / "server"
        root.mkdir()

        # Target outside root with sentinel
        outside_dir = tmp_path / "outside_dir"
        outside_dir.mkdir()
        sentinel_file = outside_dir / "sentinel.txt"
        sentinel_file.write_bytes(b"secret")

        outside_target_file = tmp_path / "outside_file.txt"
        outside_target_file.write_bytes(b"target-file")

        # Symlinks inside root
        os.symlink(outside_dir, root / "symlinked_dir")
        os.symlink(outside_target_file, root / "symlinked_file.txt")

        # Regular file inside root
        (root / "server.jar").write_bytes(b"server")

        report = scan_server_tree(root)

        assert "symlinked_dir" in report.skipped_symlinks
        assert "symlinked_file.txt" in report.skipped_symlinks
        # Symlinks are never recorded in skipped_dirs
        assert "symlinked_dir" not in report.skipped_dirs

        # Outside sentinel never visited
        scanned_paths = [f.path for f in report.files]
        assert not any("sentinel" in p for p in scanned_paths)
        assert not any("outside" in p for p in scanned_paths)
        assert len(report.files) == 1
        assert report.files[0].path == "server.jar"

    def test_casefold_collision_raises_case_collision_error(self, tmp_path: Path) -> None:
        root = tmp_path / "server"
        root.mkdir()

        # On case-sensitive filesystems, create Mods/A.jar and mods/a.jar
        mods_upper = root / "Mods"
        mods_upper.mkdir()
        (mods_upper / "A.jar").write_bytes(b"modA")

        mods_lower = root / "mods"
        try:
            mods_lower.mkdir()
            (mods_lower / "a.jar").write_bytes(b"moda")
        except OSError:
            pytest.skip("Filesystem does not support case-variant directory creation")

        with pytest.raises(CaseCollisionError) as exc_info:
            scan_server_tree(root)

        err = exc_info.value
        assert "Casefold collision" in str(err)
        paths = {err.path_a, err.path_b}
        assert paths == {"Mods/A.jar", "mods/a.jar"}

    def test_invalid_path_propagates_value_error(self, tmp_path: Path) -> None:
        root = tmp_path / "server"
        root.mkdir()

        # Trailing space in segment is legal on Linux POSIX but invalid per canonical rules
        bad_file = root / "trail .jar "
        try:
            bad_file.write_bytes(b"bad-trailing-space")
        except OSError:
            pytest.skip("Filesystem does not support trailing-space filenames")

        with pytest.raises(ValueError, match="trailing-dot/space segment"):
            scan_server_tree(root)

    def test_max_files_truncation_is_deterministic(self, tmp_path: Path) -> None:
        root = tmp_path / "server"
        root.mkdir()
        _build_synthetic_tree(root)

        report1 = scan_server_tree(root, max_files=2)
        report2 = scan_server_tree(root, max_files=2)

        assert report1.truncated is True
        assert report2.truncated is True
        assert len(report1.files) == 2
        assert len(report2.files) == 2
        assert [f.path for f in report1.files] == [f.path for f in report2.files]

    def test_max_total_bytes_truncation(self, tmp_path: Path) -> None:
        root = tmp_path / "server"
        root.mkdir()
        _build_synthetic_tree(root)

        # Set small byte limit below single file size
        report = scan_server_tree(root, max_total_bytes=5)
        assert report.truncated is True
        assert report.total_bytes >= 0
        for f in report.files:
            assert f.size >= 0

    def test_empty_directory_returns_empty_report(self, tmp_path: Path) -> None:
        root = tmp_path / "empty_server"
        root.mkdir()

        report = scan_server_tree(root)
        assert report.root == root
        assert report.files == ()
        assert report.quarantined == ()
        assert report.skipped_symlinks == ()
        assert report.skipped_dirs == ()
        assert report.case_collisions == ()
        assert report.total_bytes == 0
        assert report.truncated is False
        assert all(count == 0 for count in report.by_class.values())

    @pytest.mark.skipif(os.name != "posix", reason="POSIX symlinks only")
    def test_symlinked_root_rejected(self, tmp_path: Path) -> None:
        target_dir = tmp_path / "real_server"
        target_dir.mkdir()
        symlink_root = tmp_path / "symlink_server"
        os.symlink(target_dir, symlink_root)

        with pytest.raises(SymlinkEscapeError, match="Root itself is a symlink"):
            scan_server_tree(symlink_root)

    def test_dynamic_class_c_override(self, tmp_path: Path) -> None:
        root = tmp_path / "server"
        root.mkdir()
        _build_synthetic_tree(root)

        report = scan_server_tree(root, dynamic_class_c={"config/settings.yml"})
        settings_file = next(f for f in report.files if f.path == "config/settings.yml")
        assert settings_file.classification == "C"
        assert report.by_class["C"] == 1
        assert report.by_class["B"] == 0

    def test_relative_or_nonexistent_root_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Root must be an absolute path"):
            scan_server_tree("relative/path")

        with pytest.raises(ValueError, match="Root does not exist"):
            scan_server_tree(tmp_path / "does_not_exist")

        regular_file = tmp_path / "file.txt"
        regular_file.write_bytes(b"hello")
        with pytest.raises(ValueError, match="Root is not an existing directory"):
            scan_server_tree(regular_file)

    @pytest.mark.skipif(os.name != "posix", reason="POSIX permissions only")
    def test_unreadable_subdirectory_raises_value_error(self, tmp_path: Path) -> None:
        if os.geteuid() == 0:
            pytest.skip("Running as root bypasses directory permissions")

        root = tmp_path / "server"
        root.mkdir()
        (root / "server.jar").write_bytes(b"server")

        unreadable_dir = root / "unreadable"
        unreadable_dir.mkdir()
        (unreadable_dir / "secret.jar").write_bytes(b"secret")

        os.chmod(unreadable_dir, 0o000)
        try:
            with pytest.raises(ValueError, match="Cannot read directory"):
                scan_server_tree(root)
        finally:
            os.chmod(unreadable_dir, 0o755)

    @pytest.mark.skipif(os.name != "posix", reason="POSIX permissions only")
    def test_unreadable_root_raises_value_error(self, tmp_path: Path) -> None:
        if os.geteuid() == 0:
            pytest.skip("Running as root bypasses directory permissions")

        root = tmp_path / "unreadable_root"
        root.mkdir()
        (root / "server.jar").write_bytes(b"server")

        os.chmod(root, 0o000)
        try:
            with pytest.raises(ValueError, match="Cannot read directory"):
                scan_server_tree(root)
        finally:
            os.chmod(root, 0o755)

    def test_file_stat_failure_raises_value_error(self, tmp_path: Path) -> None:
        root = tmp_path / "server"
        root.mkdir()
        (root / "server.jar").write_bytes(b"content")

        real_stat = os.DirEntry.stat

        def failing_stat(
            self: os.DirEntry[str], *, follow_symlinks: bool = True
        ) -> os.stat_result:
            if self.name == "server.jar":
                raise OSError("Disk I/O error")
            return real_stat(self, follow_symlinks=follow_symlinks)

        with (
            patch.object(os.DirEntry, "stat", failing_stat),
            pytest.raises(ValueError, match="Cannot stat"),
        ):
            scan_server_tree(root)
