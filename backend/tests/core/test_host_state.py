"""Tests for host-state contract and layout resolution (P2-1 B4a)."""

from __future__ import annotations

import inspect
import os
import stat
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.config import AppSettings
from app.core.exceptions import InvalidValueError, ValidationError
from app.core.host_state import (
    HostStateContainmentError,
    HostStateError,
    HostStateLayout,
    HostStateSymlinkError,
    _ensure_directory,
    _ensure_marker,
    check_not_symlink_or_reparse,
    ensure_host_state_layout,
    is_lexically_absolute,
    normalize_host_root_path,
    resolve_host_state_layout,
    validate_server_segment,
)


class TestPanelRootResolution:
    def test_explicit_absolute_panel_root_wins(self, tmp_path: Path) -> None:
        explicit = tmp_path / "custom" / "host-state"
        servers_dir = tmp_path / "servers"
        settings = AppSettings(
            host_state_dir=str(explicit),
            servers_data_dir=str(servers_dir),
        )
        layout = resolve_host_state_layout(settings)
        assert layout.root == Path(os.path.realpath(explicit))
        assert layout.root == explicit

    def test_explicit_relative_panel_root_resolves_against_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        settings = AppSettings(
            host_state_dir="relative-host-state",
            servers_data_dir=str(tmp_path / "servers"),
        )
        layout = ensure_host_state_layout(settings)
        expected = tmp_path / "relative-host-state"
        assert layout.root == expected
        assert layout.root.exists()

    def test_fallback_panel_root_is_sibling_of_servers_dir(self, tmp_path: Path) -> None:
        servers_dir = tmp_path / "data" / "servers"
        servers_dir.mkdir(parents=True)
        settings = AppSettings(
            host_state_dir="",
            servers_data_dir=str(servers_dir),
        )
        layout = resolve_host_state_layout(settings)
        expected = Path(os.path.realpath(tmp_path / "data" / "host-state"))
        assert layout.root == expected
        assert layout.root != servers_dir
        with pytest.raises(ValueError):
            layout.root.relative_to(servers_dir)

    def test_panel_root_equal_to_servers_data_dir_rejected(self, tmp_path: Path) -> None:
        servers_dir = tmp_path / "servers"
        servers_dir.mkdir(parents=True)
        settings = AppSettings(
            host_state_dir=str(servers_dir),
            servers_data_dir=str(servers_dir),
        )
        with pytest.raises(HostStateContainmentError):
            resolve_host_state_layout(settings)

    def test_panel_root_inside_servers_data_dir_rejected(self, tmp_path: Path) -> None:
        servers_dir = tmp_path / "servers"
        inside = servers_dir / "host-state"
        settings = AppSettings(
            host_state_dir=str(inside),
            servers_data_dir=str(servers_dir),
        )
        with pytest.raises(HostStateContainmentError):
            resolve_host_state_layout(settings)

    def test_servers_data_dir_inside_panel_root_rejected(self, tmp_path: Path) -> None:
        parent = tmp_path / "data"
        servers_dir = parent / "servers"
        settings = AppSettings(
            host_state_dir=str(parent),
            servers_data_dir=str(servers_dir),
        )
        with pytest.raises(HostStateContainmentError):
            resolve_host_state_layout(settings)

    def test_explicit_root_symlink_alias_resolves_inside_servers_dir_rejected(
        self, tmp_path: Path
    ) -> None:
        servers_dir = tmp_path / "servers"
        servers_dir.mkdir(parents=True)
        alias = tmp_path / "servers_alias"
        alias.symlink_to(servers_dir)
        settings = AppSettings(
            host_state_dir=str(alias / "host-state"),
            servers_data_dir=str(servers_dir),
        )
        with pytest.raises(HostStateContainmentError):
            resolve_host_state_layout(settings)

    def test_explicit_root_under_symlinked_parent(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir(parents=True)
        intended = tmp_path / "intended"
        intended.mkdir(parents=True)
        link = intended / "link"
        link.symlink_to(outside)

        settings = AppSettings(
            host_state_dir=str(link / "host-state"),
            servers_data_dir=str(tmp_path / "servers"),
        )
        layout = ensure_host_state_layout(settings)
        expected = outside / "host-state"
        assert layout.root == expected
        assert layout.root.exists()
        assert not (intended / "link" / "host-state").is_symlink()


class TestHostRootResolution:
    def test_unset_leaves_none(self, tmp_path: Path) -> None:
        settings = AppSettings(
            host_state_host_dir="",
            host_data_dir="",
            servers_data_dir=str(tmp_path / "servers"),
        )
        layout = resolve_host_state_layout(settings)
        assert layout.host_root is None

    def test_relative_host_state_host_dir_raises_validation_error(self, tmp_path: Path) -> None:
        for rel in ("relative/path", "./host-state", "../state"):
            settings = AppSettings(
                host_state_host_dir=rel,
                servers_data_dir=str(tmp_path / "servers"),
            )
            with pytest.raises(ValidationError):
                resolve_host_state_layout(settings)

    def test_absolute_posix_path_normalized_lexically(self, tmp_path: Path) -> None:
        settings = AppSettings(
            host_state_host_dir="/opt/onx//state/../host-state",
            servers_data_dir=str(tmp_path / "servers"),
        )
        layout = resolve_host_state_layout(settings)
        assert layout.host_root == "/opt/onx/host-state"

    def test_absolute_windows_drive_preserved_lexically(self, tmp_path: Path) -> None:
        settings = AppSettings(
            host_state_host_dir=r"D:\docker\data\host-state",
            servers_data_dir=str(tmp_path / "servers"),
        )
        layout = resolve_host_state_layout(settings)
        assert layout.host_root == "D:/docker/data/host-state"

    def test_fallback_from_absolute_host_data_dir(self, tmp_path: Path) -> None:
        settings = AppSettings(
            host_state_host_dir="",
            host_data_dir="/opt/docker/servers",
            servers_data_dir=str(tmp_path / "servers"),
        )
        layout = resolve_host_state_layout(settings)
        assert layout.host_root == "/opt/docker/host-state"

    def test_fallback_from_relative_host_data_dir_leaves_none(self, tmp_path: Path) -> None:
        settings = AppSettings(
            host_state_host_dir="",
            host_data_dir="relative/servers",
            servers_data_dir=str(tmp_path / "servers"),
        )
        layout = resolve_host_state_layout(settings)
        assert layout.host_root is None


class TestLayoutCreationAndPermissions:
    def test_ensure_layout_creates_all_eight_directories_with_0700(self, tmp_path: Path) -> None:
        root = tmp_path / "state"
        settings = AppSettings(
            host_state_dir=str(root),
            servers_data_dir=str(tmp_path / "servers"),
        )
        layout = ensure_host_state_layout(settings)

        expected_dirs = [
            layout.root,
            layout.server_meta,
            layout.class_c_vault,
            layout.quarantine,
            layout.lec,
            layout.cas,
            layout.repos,
            layout.locks,
            layout.journal,
        ]
        for d in expected_dirs:
            assert d.exists(), f"Directory {d} should exist"
            assert d.is_dir(), f"{d} should be a directory"
            if os.name == "posix":
                mode = stat.S_IMODE(d.lstat().st_mode)
                assert mode == 0o700, f"{d} mode should be 0700, got {oct(mode)}"

    def test_deepest_newly_created_ancestor_is_0700(self, tmp_path: Path) -> None:
        if os.name != "posix":
            pytest.skip("POSIX permissions test")

        base = tmp_path / "base"
        base.mkdir(parents=True)
        os.chmod(base, 0o755)

        root = base / "new_p1" / "new_p2" / "host-state"
        settings = AppSettings(
            host_state_dir=str(root),
            servers_data_dir=str(tmp_path / "servers"),
        )
        layout = ensure_host_state_layout(settings)

        assert stat.S_IMODE(base.lstat().st_mode) == 0o755
        assert stat.S_IMODE((base / "new_p1").lstat().st_mode) == 0o700
        assert stat.S_IMODE((base / "new_p1" / "new_p2").lstat().st_mode) == 0o700
        assert stat.S_IMODE(layout.root.lstat().st_mode) == 0o700

    def test_existing_directory_broader_permissions_tightened_if_owned(
        self, tmp_path: Path
    ) -> None:
        if os.name != "posix":
            pytest.skip("POSIX permissions test")

        root = tmp_path / "state"
        root.mkdir(parents=True)
        os.chmod(root, 0o755)

        settings = AppSettings(
            host_state_dir=str(root),
            servers_data_dir=str(tmp_path / "servers"),
        )
        layout = ensure_host_state_layout(settings)
        assert stat.S_IMODE(layout.root.lstat().st_mode) == 0o700

    def test_existing_directory_broader_permissions_fails_if_not_owned(
        self, tmp_path: Path
    ) -> None:
        if os.name != "posix":
            pytest.skip("POSIX permissions test")

        root = tmp_path / "state"
        root.mkdir(parents=True)
        os.chmod(root, 0o755)

        settings = AppSettings(
            host_state_dir=str(root),
            servers_data_dir=str(tmp_path / "servers"),
        )
        with patch("os.geteuid", return_value=99999), pytest.raises(HostStateError):
            ensure_host_state_layout(settings)

    def test_symlinked_root_rejected(self, tmp_path: Path) -> None:
        real_dir = tmp_path / "real_state"
        real_dir.mkdir(parents=True)
        symlink_root = tmp_path / "sym_state"
        symlink_root.symlink_to(real_dir)

        settings = AppSettings(
            host_state_dir=str(symlink_root),
            servers_data_dir=str(tmp_path / "servers"),
        )
        with pytest.raises(HostStateSymlinkError):
            ensure_host_state_layout(settings)

    def test_symlinked_layout_subdir_rejected(self, tmp_path: Path) -> None:
        root = tmp_path / "state"
        root.mkdir(parents=True)
        external = tmp_path / "external_server_meta"
        external.mkdir(parents=True)
        (root / "server-meta").symlink_to(external)

        settings = AppSettings(
            host_state_dir=str(root),
            servers_data_dir=str(tmp_path / "servers"),
        )
        with pytest.raises(HostStateSymlinkError):
            ensure_host_state_layout(settings)

    def test_file_as_root_rejected(self, tmp_path: Path) -> None:
        root_file = tmp_path / "file_root"
        root_file.write_text("not a directory")

        settings = AppSettings(
            host_state_dir=str(root_file),
            servers_data_dir=str(tmp_path / "servers"),
        )
        with pytest.raises(HostStateError):
            ensure_host_state_layout(settings)


class TestServerSegmentValidation:
    @pytest.mark.parametrize(
        "valid_id",
        [
            "srv1",
            "srv-123",
            "server_abc",
            "A",
            "a" * 64,
            "00000000-0000-0000-0000-000000000000",
        ],
    )
    def test_valid_segments(self, tmp_path: Path, valid_id: str) -> None:
        assert validate_server_segment(valid_id) == valid_id
        layout = HostStateLayout(
            root=tmp_path,
            server_meta=tmp_path / "server-meta",
            class_c_vault=tmp_path / "class-c-vault",
            quarantine=tmp_path / "quarantine",
            lec=tmp_path / "lec",
            cas=tmp_path / "cas",
            repos=tmp_path / "repos",
            locks=tmp_path / "locks",
            journal=tmp_path / "journal",
        )
        assert layout.server_meta_dir(valid_id) == layout.server_meta / valid_id
        assert layout.quarantine_dir(valid_id) == layout.quarantine / valid_id
        assert layout.class_c_vault_dir(valid_id) == layout.class_c_vault / valid_id
        assert layout.repo_dir(valid_id) == layout.repos / valid_id

    @pytest.mark.parametrize(
        "invalid_id",
        [
            "bad/../id",
            "../x",
            "",
            "con",
            "CON",
            "prn",
            "aux",
            "nul",
            "com1",
            "com9",
            "lpt1",
            "-invalid-start",
            "_invalid-start",
            "a" * 65,
            "server\0null",
            "server/sub",
            "server\\sub",
            ".",
            "..",
        ],
    )
    def test_invalid_segments_rejected(self, tmp_path: Path, invalid_id: str) -> None:
        with pytest.raises(InvalidValueError):
            validate_server_segment(invalid_id)

        layout = HostStateLayout(
            root=tmp_path,
            server_meta=tmp_path / "server-meta",
            class_c_vault=tmp_path / "class-c-vault",
            quarantine=tmp_path / "quarantine",
            lec=tmp_path / "lec",
            cas=tmp_path / "cas",
            repos=tmp_path / "repos",
            locks=tmp_path / "locks",
            journal=tmp_path / "journal",
        )
        with pytest.raises(InvalidValueError):
            layout.server_meta_dir(invalid_id)
        with pytest.raises(InvalidValueError):
            layout.quarantine_dir(invalid_id)
        with pytest.raises(InvalidValueError):
            layout.class_c_vault_dir(invalid_id)
        with pytest.raises(InvalidValueError):
            layout.repo_dir(invalid_id)


class TestMarker:
    def test_marker_creation_and_round_trip(self, tmp_path: Path) -> None:
        root = tmp_path / "state"
        settings = AppSettings(
            host_state_dir=str(root),
            servers_data_dir=str(tmp_path / "servers"),
        )
        layout1 = ensure_host_state_layout(settings)
        marker_file = layout1.root / ".onx-host-state-id"
        assert marker_file.exists()
        assert len(layout1.marker_id) == 32
        if os.name == "posix":
            assert stat.S_IMODE(marker_file.lstat().st_mode) == 0o600

        layout2 = ensure_host_state_layout(settings)
        assert layout2.marker_id == layout1.marker_id

    def test_existing_marker_mode_tightened_to_0600(self, tmp_path: Path) -> None:
        if os.name != "posix":
            pytest.skip("POSIX mode test")
        root = tmp_path / "state"
        root.mkdir(parents=True)
        marker = root / ".onx-host-state-id"
        marker.write_text("0123456789abcdef0123456789abcdef\n")
        os.chmod(marker, 0o644)
        assert stat.S_IMODE(marker.lstat().st_mode) == 0o644

        settings = AppSettings(
            host_state_dir=str(root),
            servers_data_dir=str(tmp_path / "servers"),
        )
        layout = ensure_host_state_layout(settings)
        assert layout.marker_id == "0123456789abcdef0123456789abcdef"
        assert stat.S_IMODE(marker.lstat().st_mode) == 0o600

    def test_symlinked_marker_file_rejected_on_read(self, tmp_path: Path) -> None:
        root = tmp_path / "state"
        root.mkdir(parents=True)
        external = tmp_path / "external_marker"
        external.write_text("0123456789abcdef0123456789abcdef\n")
        (root / ".onx-host-state-id").symlink_to(external)

        settings = AppSettings(
            host_state_dir=str(root),
            servers_data_dir=str(tmp_path / "servers"),
        )
        with pytest.raises(HostStateError):
            ensure_host_state_layout(settings)

    def test_symlinked_marker_file_rejected_on_create(self, tmp_path: Path) -> None:
        root = tmp_path / "state"
        root.mkdir(parents=True)
        (root / ".onx-host-state-id").symlink_to(tmp_path / "nonexistent")

        settings = AppSettings(
            host_state_dir=str(root),
            servers_data_dir=str(tmp_path / "servers"),
        )
        with pytest.raises(HostStateError):
            ensure_host_state_layout(settings)

    def test_corrupt_marker_fails_closed(self, tmp_path: Path) -> None:
        root = tmp_path / "state"
        root.mkdir(parents=True)
        (root / ".onx-host-state-id").write_text("corrupted-non-uuid-content\n")

        settings = AppSettings(
            host_state_dir=str(root),
            servers_data_dir=str(tmp_path / "servers"),
        )
        with pytest.raises(HostStateError, match="Corrupt or invalid"):
            ensure_host_state_layout(settings)

    def test_binary_garbage_marker_fails_closed(self, tmp_path: Path) -> None:
        root = tmp_path / "state"
        root.mkdir(parents=True)
        (root / ".onx-host-state-id").write_bytes(b"\xff\xfe")

        settings = AppSettings(
            host_state_dir=str(root),
            servers_data_dir=str(tmp_path / "servers"),
        )
        with pytest.raises(HostStateError) as exc_info:
            ensure_host_state_layout(settings)
        assert not isinstance(exc_info.value, UnicodeDecodeError)

    def test_invisible_host_path_is_unverified(self, tmp_path: Path) -> None:
        settings = AppSettings(
            host_state_dir=str(tmp_path / "state"),
            host_state_host_dir="/var/lib/docker/daemon-only-path",
            servers_data_dir=str(tmp_path / "servers"),
        )
        layout = ensure_host_state_layout(settings)
        assert layout.marker_status == "unverified"

    def test_windows_host_root_spelling_on_posix_is_unverified(self, tmp_path: Path) -> None:
        settings = AppSettings(
            host_state_dir=str(tmp_path / "state"),
            host_state_host_dir=r"C:\docker\host-state",
            servers_data_dir=str(tmp_path / "servers"),
        )
        layout = ensure_host_state_layout(settings)
        assert layout.marker_status == "unverified"

    def test_visible_host_path_matching_is_verified(self, tmp_path: Path) -> None:
        host_dir = tmp_path / "host_visible"
        host_dir.mkdir(parents=True)
        settings = AppSettings(
            host_state_dir=str(tmp_path / "state"),
            host_state_host_dir=str(host_dir),
            servers_data_dir=str(tmp_path / "servers"),
        )
        layout = ensure_host_state_layout(settings)
        assert layout.marker_status == "verified"
        host_marker = host_dir / ".onx-host-state-id"
        assert host_marker.exists()
        assert host_marker.read_text(encoding="utf-8").strip() == layout.marker_id

    def test_visible_host_path_mismatched_fails_closed(self, tmp_path: Path) -> None:
        host_dir = tmp_path / "host_visible"
        host_dir.mkdir(parents=True)
        (host_dir / ".onx-host-state-id").write_text("0123456789abcdef0123456789abcdef\n")

        settings = AppSettings(
            host_state_dir=str(tmp_path / "state"),
            host_state_host_dir=str(host_dir),
            servers_data_dir=str(tmp_path / "servers"),
        )
        with pytest.raises(HostStateError, match="Host state marker mismatch"):
            ensure_host_state_layout(settings)


class TestWindowsPortability:
    def test_no_posix_only_imports_at_module_level(self) -> None:
        import app.core.host_state as mod

        forbidden = ("fcntl", "pwd", "grp", "termios", "resource")
        for name in forbidden:
            assert not hasattr(mod, name), f"Module should not have {name}"
            assert name not in sys.modules or mod.__dict__.get(name) is None

        source = inspect.getsource(mod)
        for name in forbidden:
            assert f"import {name}" not in source
        assert "dir_fd" not in source
        for token in ("os.O_DIRECTORY", "os.O_NOFOLLOW"):
            assert token not in source

    def test_simulated_windows_branch(self, tmp_path: Path) -> None:
        root = tmp_path / "win_state"
        with patch("os.name", "nt"):
            _ensure_directory(root)
            assert root.exists()
            assert root.is_dir()

            marker_id, status = _ensure_marker(root, None)
            marker_file = root / ".onx-host-state-id"
            assert marker_file.exists()
            assert len(marker_id) == 32
            assert status == "unverified"

    def test_check_not_symlink_or_reparse_with_reparse_attribute(self, tmp_path: Path) -> None:
        target = tmp_path / "file.txt"
        target.write_text("hello")

        fake_stat = types.SimpleNamespace(
            st_file_attributes=0x400, st_mode=stat.S_IFREG | 0o644
        )
        with (
            patch("pathlib.Path.lstat", return_value=fake_stat),
            pytest.raises(HostStateSymlinkError, match="Reparse point"),
        ):
            check_not_symlink_or_reparse(target)

    def test_lexical_helpers(self) -> None:
        assert is_lexically_absolute("/var/log") is True
        assert is_lexically_absolute(r"C:\Windows") is True
        assert is_lexically_absolute("D:/data") is True
        assert is_lexically_absolute(r"\\server\share") is True
        assert is_lexically_absolute("relative/path") is False
        assert is_lexically_absolute("") is False

        assert normalize_host_root_path(r"C:\docker\data\host-state") == "C:/docker/data/host-state"
        assert normalize_host_root_path("/opt/onx//data/../data") == "/opt/onx/data"
