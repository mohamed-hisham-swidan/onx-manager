"""Tests for authoritative host lockfile service and atomic private write.

P2-1 Core Substrate — B4b
"""

from __future__ import annotations

import inspect
import json
import os
import stat
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.allowlist import SymlinkEscapeError
from app.core.config import AppSettings
from app.core.exceptions import (
    InvalidValueError,
    LockfileFormatError,
    LockfileInvalidError,
)
from app.core.host_state import HostStateLayout, resolve_host_state_layout
from app.modules.versioning.application.lockfile_service import (
    MAX_LOCKFILE_BYTES,
    LockfileService,
    LockfileServiceError,
)
from app.modules.versioning.domain.lockfile import (
    LockfileV21,
    dump_lockfile,
    parse_lockfile,
)
from app.modules.versioning.infrastructure.fs_atomic import atomic_write_private

SAMPLE_SHA256 = "a" * 64
SAMPLE_SHA512 = "b" * 128
SAMPLE_SHA1 = "c" * 40


@pytest.fixture
def layout(tmp_path: Path) -> HostStateLayout:
    """Return an initialized HostStateLayout rooted in a temporary directory."""
    settings = AppSettings(
        host_state_dir=str(tmp_path / "host-state"),
        servers_data_dir=str(tmp_path / "servers"),
    )
    return resolve_host_state_layout(settings)


@pytest.fixture
def service(layout: HostStateLayout) -> LockfileService:
    """Return a LockfileService bound to the temporary layout."""
    return LockfileService(layout)


@pytest.fixture
def sample_lockfile() -> LockfileV21:
    """Return a complete, valid LockfileV21 domain instance."""
    doc = {
        "format": 2,
        "mc": "1.20.4",
        "loader": {"id": "paper", "version": "499"},
        "lec": {"key": "paper/1.20.4/499"},
        "modpack": {
            "source": "modrinth",
            "project_id": "P7dR8mSH",
            "version_id": "998R2rNP",
            "version_label": "1.4.2",
            "index_sha256": SAMPLE_SHA256,
        },
        "base_overrides": {
            "config/fancymenu/options.txt": SAMPLE_SHA256,
        },
        "files": [
            {
                "path": "mods/example.jar",
                "sha256": SAMPLE_SHA256,
                "sha512": SAMPLE_SHA512,
                "sha1": SAMPLE_SHA1,
                "size": 1797522,
                "optional": False,
                "env_server": "required",
                "origin": "modrinth",
                "project_id": "P7dR8mSH",
                "version_id": "998R2rNP",
            }
        ],
    }
    return parse_lockfile(json.dumps(doc).encode("utf-8"))


class TestLockfileService:
    """Unit tests for LockfileService reading, writing, and security enforcement."""

    def test_missing_lockfile_returns_none(self, service: LockfileService) -> None:
        assert service.exists("srv-1") is False
        assert service.read("srv-1") is None

    def test_write_read_round_trip_preserves_all_fields(
        self, service: LockfileService, sample_lockfile: LockfileV21
    ) -> None:
        server_id = "srv-1"
        written_path = service.write(server_id, sample_lockfile)
        assert written_path.exists()
        assert service.exists(server_id) is True

        loaded = service.read(server_id)
        assert loaded is not None
        assert loaded.mc == sample_lockfile.mc
        assert loaded.loader == sample_lockfile.loader
        assert loaded.lec == sample_lockfile.lec
        assert loaded.modpack == sample_lockfile.modpack
        assert loaded.base_overrides == sample_lockfile.base_overrides
        assert loaded.files == sample_lockfile.files
        assert loaded == sample_lockfile

    @pytest.mark.skipif(os.name != "posix", reason="POSIX permissions only")
    def test_file_and_parent_modes_on_posix(
        self, service: LockfileService, sample_lockfile: LockfileV21
    ) -> None:
        server_id = "srv-perms"
        written_path = service.write(server_id, sample_lockfile)
        parent = written_path.parent

        assert stat.S_IMODE(written_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(parent.stat().st_mode) == 0o700

        # Existing directory with broader permissions is tightened to 0700 on subsequent write
        os.chmod(parent, 0o755)
        assert stat.S_IMODE(parent.stat().st_mode) == 0o755
        service.write(server_id, sample_lockfile)
        assert stat.S_IMODE(parent.stat().st_mode) == 0o700

    def test_deterministic_bytes(
        self, service: LockfileService, sample_lockfile: LockfileV21
    ) -> None:
        server_id = "srv-deterministic"
        path1 = service.write(server_id, sample_lockfile)
        bytes1 = path1.read_bytes()

        path2 = service.write(server_id, sample_lockfile)
        bytes2 = path2.read_bytes()

        assert bytes1 == bytes2
        assert bytes1 == dump_lockfile(sample_lockfile)

    def test_malformed_truncated_content_raises_domain_exception(
        self, service: LockfileService, sample_lockfile: LockfileV21
    ) -> None:
        server_id = "srv-malformed"
        written_path = service.write(server_id, sample_lockfile)
        original_bytes = written_path.read_bytes()

        # Write truncated/malformed JSON
        malformed_bytes = b'{"format": 2, "mc":'
        written_path.write_bytes(malformed_bytes)

        with pytest.raises((LockfileFormatError, LockfileInvalidError)):
            service.read(server_id)

        # File content on disk remains what was there (unchanged by read)
        assert written_path.read_bytes() == malformed_bytes

        # Restore original valid bytes
        written_path.write_bytes(original_bytes)
        assert service.read(server_id) == sample_lockfile

    def test_oversized_file_rejected(
        self, service: LockfileService, sample_lockfile: LockfileV21
    ) -> None:
        server_id = "srv-oversized"
        written_path = service.write(server_id, sample_lockfile)

        # Write oversized payload exceeding 16 MiB
        oversized = b" " * (MAX_LOCKFILE_BYTES + 1)
        written_path.write_bytes(oversized)

        with pytest.raises(LockfileServiceError, match="exceeds maximum size"):
            service.read(server_id)

        assert written_path.read_bytes() == oversized

    def test_atomic_replace_failure_preserves_existing_lockfile(
        self, service: LockfileService, sample_lockfile: LockfileV21
    ) -> None:
        server_id = "srv-atomic-fail"
        written_path = service.write(server_id, sample_lockfile)
        original_bytes = written_path.read_bytes()

        updated_doc = {
            "format": 2,
            "mc": "1.20.2",
            "loader": {"id": "paper", "version": "500"},
            "lec": {"key": "paper/1.20.2/500"},
            "base_overrides": {},
            "files": [],
        }
        updated_lockfile = parse_lockfile(json.dumps(updated_doc).encode("utf-8"))

        with (
            patch("os.replace", side_effect=OSError("Disk write error")),
            pytest.raises(LockfileServiceError, match="Failed to write lockfile"),
        ):
            service.write(server_id, updated_lockfile)

        # Original lockfile remains intact and valid
        assert written_path.read_bytes() == original_bytes
        assert service.read(server_id) == sample_lockfile

    def test_no_tmp_leftovers_after_success_and_failure(
        self, service: LockfileService, sample_lockfile: LockfileV21
    ) -> None:
        server_id = "srv-clean-tmp"
        written_path = service.write(server_id, sample_lockfile)
        parent = written_path.parent

        assert list(parent.glob(".*.tmp")) == []

        with (
            patch("os.replace", side_effect=OSError("Simulated rename error")),
            pytest.raises(LockfileServiceError, match="Failed to write lockfile"),
        ):
            service.write(server_id, sample_lockfile)

        assert list(parent.glob(".*.tmp")) == []

    def test_write_oserror_wrapped_in_lockfile_service_error(
        self, service: LockfileService, sample_lockfile: LockfileV21
    ) -> None:
        server_id = "srv-oserror-wrap"
        with (
            patch("os.replace", side_effect=OSError("Disk failure")),
            pytest.raises(LockfileServiceError, match="Failed to write lockfile"),
        ):
            service.write(server_id, sample_lockfile)

        parent = service.path_for(server_id).parent
        assert list(parent.glob(".*.tmp")) == []

    @pytest.mark.skipif(os.name != "posix", reason="POSIX symlinks only")
    def test_symlinked_parent_rejected_on_write(
        self,
        layout: HostStateLayout,
        service: LockfileService,
        sample_lockfile: LockfileV21,
        tmp_path: Path,
    ) -> None:
        server_id = "srv-sym-parent"
        parent = layout.server_meta_dir(server_id)
        parent.parent.mkdir(parents=True, exist_ok=True)
        target_dir = tmp_path / "outside_dir"
        target_dir.mkdir(parents=True, exist_ok=True)
        os.symlink(target_dir, parent)

        with pytest.raises(LockfileServiceError, match="Parent directory is a symlink"):
            service.write(server_id, sample_lockfile)

        assert list(parent.glob(".*.tmp")) == []
        assert list(target_dir.glob(".*.tmp")) == []

    @pytest.mark.skipif(os.name != "posix", reason="POSIX symlinks only")
    def test_symlinked_server_meta_rejected_on_write(
        self,
        layout: HostStateLayout,
        service: LockfileService,
        sample_lockfile: LockfileV21,
        tmp_path: Path,
    ) -> None:
        server_id = "srv-meta-sym"
        target_dir = tmp_path / "outside_meta"
        target_dir.mkdir(parents=True, exist_ok=True)
        layout.root.mkdir(parents=True, exist_ok=True)
        if layout.server_meta.exists():
            layout.server_meta.rmdir()
        os.symlink(target_dir, layout.server_meta)

        with pytest.raises(LockfileServiceError, match="server_meta is a symlink"):
            service.write(server_id, sample_lockfile)

        assert list(target_dir.glob(".*.tmp")) == []
        assert list(tmp_path.glob(".*.tmp")) == []

    @pytest.mark.skipif(os.name != "posix", reason="POSIX symlinks only")
    def test_symlinked_lockfile_rejected_on_read_and_write(
        self, service: LockfileService, sample_lockfile: LockfileV21, tmp_path: Path
    ) -> None:
        server_id = "srv-sym-file"
        lockfile_path = service.path_for(server_id)
        lockfile_path.parent.mkdir(parents=True, exist_ok=True)

        target_file = tmp_path / "outside.json"
        target_file.write_bytes(dump_lockfile(sample_lockfile))
        os.symlink(target_file, lockfile_path)

        assert service.exists(server_id) is False

        with pytest.raises(LockfileServiceError, match="Failed to open lockfile"):
            service.read(server_id)

        with pytest.raises(LockfileServiceError, match="Destination is a symlink"):
            service.write(server_id, sample_lockfile)

        assert list(lockfile_path.parent.glob(".*.tmp")) == []

    @pytest.mark.parametrize(
        "invalid_id",
        [
            "",
            "../escape",
            "a/b",
            "a\\b",
            "CON",
            "PRN",
            "AUX",
            "NUL",
            "COM1",
            "LPT1",
            "has space",
            ".hidden",
            "a" * 65,
        ],
    )
    def test_server_id_validation_rejects_illegal_segments(
        self, service: LockfileService, sample_lockfile: LockfileV21, invalid_id: str
    ) -> None:
        with pytest.raises(InvalidValueError):
            service.path_for(invalid_id)

        with pytest.raises(InvalidValueError):
            service.exists(invalid_id)

        with pytest.raises(InvalidValueError):
            service.read(invalid_id)

        with pytest.raises(InvalidValueError):
            service.write(invalid_id, sample_lockfile)


class TestAtomicWritePrivate:
    """Unit tests for atomic_write_private infrastructure function."""

    def test_byte_count_returned_and_modes(self, tmp_path: Path) -> None:
        target = tmp_path / "private.txt"
        content = "hello world \u2603"
        expected_len = len(content.encode("utf-8"))

        written_len = atomic_write_private(target, content, mode=0o600)
        assert written_len == expected_len
        assert target.read_text(encoding="utf-8") == content

        if os.name == "posix":
            assert stat.S_IMODE(target.stat().st_mode) == 0o600

    def test_atomic_overwrite(self, tmp_path: Path) -> None:
        target = tmp_path / "overwrite.txt"
        atomic_write_private(target, b"initial content")
        assert target.read_bytes() == b"initial content"

        atomic_write_private(target, b"new updated content")
        assert target.read_bytes() == b"new updated content"

    @pytest.mark.skipif(os.name != "posix", reason="POSIX symlinks only")
    def test_symlink_destination_rejected(self, tmp_path: Path) -> None:
        target = tmp_path / "target.txt"
        target.write_bytes(b"target")
        symlink = tmp_path / "link.txt"
        os.symlink(target, symlink)

        with pytest.raises(SymlinkEscapeError, match="Destination is a symlink"):
            atomic_write_private(symlink, b"exploit")

        assert target.read_bytes() == b"target"
        assert list(tmp_path.glob(".*.tmp")) == []

    @pytest.mark.skipif(os.name != "posix", reason="POSIX symlinks only")
    def test_symlink_parent_rejected(self, tmp_path: Path) -> None:
        real_dir = tmp_path / "real_dir"
        real_dir.mkdir()
        symlink_dir = tmp_path / "sym_dir"
        os.symlink(real_dir, symlink_dir)

        target = symlink_dir / "file.txt"
        with pytest.raises(SymlinkEscapeError, match="Parent directory is a symlink"):
            atomic_write_private(target, b"exploit")

        assert list(real_dir.glob(".*.tmp")) == []
        assert list(tmp_path.glob(".*.tmp")) == []

    def test_no_tmp_leftovers_on_write_failure(self, tmp_path: Path) -> None:
        target = tmp_path / "fail.txt"
        with (
            patch("os.replace", side_effect=OSError("Replace failed")),
            pytest.raises(OSError, match="Replace failed"),
        ):
            atomic_write_private(target, b"some content")

        assert list(tmp_path.glob(".*.tmp")) == []
        assert not target.exists()


class TestWindowsPortability:
    """Portability checks ensuring modules import and run without POSIX dependencies."""

    def test_no_posix_only_imports_at_module_level(self) -> None:
        import app.modules.versioning.application.lockfile_service as srv_mod
        import app.modules.versioning.infrastructure.fs_atomic as fs_mod

        forbidden = ("fcntl", "pwd", "grp", "termios", "resource")
        for mod in (srv_mod, fs_mod):
            for name in forbidden:
                assert not hasattr(mod, name), f"{mod.__name__} should not import {name}"
                assert name not in sys.modules or mod.__dict__.get(name) is None

            source = inspect.getsource(mod)
            for name in forbidden:
                assert f"import {name}" not in source

    def test_simulated_windows_read_write(
        self, layout: HostStateLayout, sample_lockfile: LockfileV21
    ) -> None:
        service = LockfileService(layout)
        server_id = "srv-win-test"

        with patch("os.name", "nt"):
            written_path = service.write(server_id, sample_lockfile)
            assert written_path.exists()
            assert service.exists(server_id) is True

            loaded = service.read(server_id)
            assert loaded is not None
            assert loaded == sample_lockfile
