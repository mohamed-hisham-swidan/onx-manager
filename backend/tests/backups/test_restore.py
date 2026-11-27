"""Consolidated tests for safe archive restore, two-tier restore, pending restores, and tar safety."""

from __future__ import annotations

import errno
import io
import json
import os
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.core.exceptions import InsufficientStorageError
from app.core.persistence.db import database
from app.modules.backup.application import restore_service as restore_module
from app.modules.backup.application.restore_service import (
    RestoreError,
    _atomic_replace_dir,
    _atomic_replace_file,
    _ensure_extract_space,
    _safe_extract_tar,
    _validate_tar_member_link,
    _validate_tar_member_name,
    consume_pending_restore,
    perform_safe_restore,
)
from app.modules.backup.application.two_tier_restore import (
    TwoTierRestoreError,
    restore_tier1_snapshot,
    restore_tier2_archive,
)
from app.modules.backup.domain.aggregate import BackupJob
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.backup.infrastructure.tier1_snapshot import create_tier1_snapshot
from app.modules.backup.infrastructure.tier2_archive import create_tier2_archive
from app.modules.shared.value_objects import BackupJobId, ServerId
from app.modules.storage.base import StorageBackend, StorageResult
from app.modules.storage.encryption import BackupEncryption
from app.modules.storage.local import LocalStorage
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.vault_crypto import MasterKek


class _FakeStorage(StorageBackend):
    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    async def write(self, path: str, data: bytes) -> StorageResult:
        self._store[path] = data
        return StorageResult(path=path, size_bytes=len(data), checksum="")

    async def read(self, path: str) -> bytes:
        return self._store.get(path, b"")

    async def delete(self, path: str) -> bool:
        return self._store.pop(path, None) is not None

    async def exists(self, path: str) -> bool:
        return path in self._store

    async def list_files(self, prefix: str) -> list:
        del prefix
        return []

    async def info(self, path: str):
        del path
        return None

    async def copy(self, source: str, destination: str) -> StorageResult:
        data = await self.read(source)
        return await self.write(destination, data)


def _make_archive(source_dir: str, names: list[str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name in names:
            tar.add(os.path.join(source_dir, name), arcname=name)
    return buf.getvalue()


def _raw_tar(members: list[tuple[str, bytes | None]]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in members:
            info = tarfile.TarInfo(name=name)
            if data is None:
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                tar.addfile(info)
            else:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _write(base: Path, rel: str, content: str = "") -> Path:
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


async def _seed_job(
    backup_id: str,
    server_id: str,
    storage_path: str,
    size: int,
    checksum: str,
) -> None:
    async with database.session_factory() as session:
        repo = SQLBackupRepository(session)
        job = BackupJob.create(backup_id=BackupJobId(backup_id), server_id=ServerId(server_id))
        job.mark_completed(size_bytes=size, checksum=checksum, storage_path=storage_path)
        await repo.save_job(job)
        await session.commit()


async def _pending(server_id: str) -> tuple[str, datetime] | None:
    async with database.session_factory() as session:
        return await SQLBackupRepository(session).get_pending_restore(ServerId(server_id))


# ---------------------------------------------------------------------------
# Safe Archive Restore
# ---------------------------------------------------------------------------


class TestPerformSafeRestore:
    async def _build_artifact(
        self, source_dir: str, names: list[str]
    ) -> tuple[_FakeStorage, BackupEncryption, str, int, str]:
        encryption = BackupEncryption()
        encrypted = encryption.encrypt(_make_archive(source_dir, names))
        storage = _FakeStorage()
        path = "res-svc.tar.gz.enc"
        await storage.write(path, encrypted)
        return storage, encryption, path, len(encrypted), encryption.checksum(encrypted)

    async def test_swaps_present_dimensions_and_leaves_others(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "server"
        _write(server_dir, "world/level.dat", "old-world")
        _write(server_dir, "world_nether/DIM1.dat", "old-nether")
        _write(server_dir, "plugins/p.jar", "keep-me")

        source = tmp_path / "src"
        _write(source, "world/level.dat", "new-world")
        _write(source, "world_nether/DIM1.dat", "new-nether")

        storage, encryption, path, size, checksum = await self._build_artifact(
            str(source), ["world", "world_nether"]
        )
        await _seed_job("res-svc-ok", "srv-1", path, size, checksum)

        restored = await perform_safe_restore(
            BackupJobId("res-svc-ok"), str(server_dir), storage=storage, encryption=encryption
        )
        assert restored == ["world", "world_nether"]
        assert (server_dir / "world" / "level.dat").read_text(encoding="utf-8") == "new-world"
        assert (server_dir / "world_nether" / "DIM1.dat").read_text(
            encoding="utf-8"
        ) == "new-nether"
        assert (server_dir / "plugins" / "p.jar").read_text(encoding="utf-8") == "keep-me"
        assert not (server_dir / "world.onx-old").exists()
        assert not (server_dir / "world.mcs-old").exists()

    async def test_stages_extraction_on_same_filesystem_as_server(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "server"
        _write(server_dir, "world/level.dat", "old-world")
        source = tmp_path / "src"
        _write(source, "world/level.dat", "new-world")

        storage, encryption, path, size, checksum = await self._build_artifact(
            str(source), ["world"]
        )
        await _seed_job("res-svc-stage-fs", "srv-1", path, size, checksum)

        captured_dir: list[str] = []
        real_mkdtemp = tempfile.mkdtemp

        def _mkdtemp(*args, **kwargs):
            captured_dir.append(kwargs.get("dir") or "")
            return real_mkdtemp(*args, **kwargs)

        with patch(
            "app.modules.backup.application.restore_service.tempfile.mkdtemp",
            side_effect=_mkdtemp,
        ):
            restored = await perform_safe_restore(
                BackupJobId("res-svc-stage-fs"),
                str(server_dir),
                storage=storage,
                encryption=encryption,
            )

        assert restored == ["world"]
        assert (server_dir / "world" / "level.dat").read_text(encoding="utf-8") == "new-world"
        assert captured_dir == [os.path.dirname(os.path.abspath(str(server_dir)))]
        assert os.stat(captured_dir[0]).st_dev == os.stat(str(server_dir)).st_dev
        assert not list(tmp_path.glob("onx-restore-*"))
        assert not list(tmp_path.glob("mcs-restore-*"))

    async def test_custom_primary_world_and_level_name_selection(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "server"
        _write(server_dir, "mypvp/level.dat", "old")
        source = tmp_path / "src"
        _write(source, "mypvp/level.dat", "new")
        storage, encryption, path, size, checksum = await self._build_artifact(
            str(source), ["mypvp"]
        )
        await _seed_job("res-svc-pvp", "srv-1", path, size, checksum)

        restored = await perform_safe_restore(
            BackupJobId("res-svc-pvp"),
            str(server_dir),
            base_world="mypvp",
            storage=storage,
            encryption=encryption,
        )
        assert restored == ["mypvp"]
        assert (server_dir / "mypvp" / "level.dat").read_text(encoding="utf-8") == "new"

        # server.properties level-name
        srv2 = tmp_path / "server2"
        _write(srv2, "server.properties", "motd=x\nlevel-name=mypvp\n")
        _write(srv2, "mypvp/level.dat", "old-custom")
        src2 = tmp_path / "src2"
        _write(src2, "mypvp/level.dat", "new-custom")
        st2, enc2, p2, sz2, cs2 = await self._build_artifact(str(src2), ["mypvp"])
        await _seed_job("res-svc-ln", "srv-1", p2, sz2, cs2)
        assert await perform_safe_restore(
            BackupJobId("res-svc-ln"), str(srv2), storage=st2, encryption=enc2
        ) == ["mypvp"]
        assert (srv2 / "mypvp" / "level.dat").read_text(encoding="utf-8") == "new-custom"

        # Traversal-shaped level-name falls back to default "world"
        srv3 = tmp_path / "server3"
        _write(srv3, "server.properties", "level-name=../escape\n")
        _write(srv3, "world/level.dat", "old-world")
        src3 = tmp_path / "src3"
        _write(src3, "world/level.dat", "new-world")
        st3, enc3, p3, sz3, cs3 = await self._build_artifact(str(src3), ["world"])
        await _seed_job("res-svc-ln-esc", "srv-1", p3, sz3, cs3)
        assert await perform_safe_restore(
            BackupJobId("res-svc-ln-esc"), str(srv3), storage=st3, encryption=enc3
        ) == ["world"]
        assert (srv3 / "world" / "level.dat").read_text(encoding="utf-8") == "new-world"
        assert not (tmp_path / "escape").exists()

    async def test_rejects_checksum_size_and_missing_artifact(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "server"
        _write(server_dir, "world/level.dat", "old")
        source = tmp_path / "src"
        _write(source, "world/level.dat", "new")
        storage, encryption, path, size, checksum = await self._build_artifact(
            str(source), ["world"]
        )

        await _seed_job("res-bad-cs", "srv-1", path, size, "deadbeef")
        with pytest.raises(RestoreError, match="checksum"):
            await perform_safe_restore(
                BackupJobId("res-bad-cs"), str(server_dir), storage=storage, encryption=encryption
            )

        await _seed_job("res-bad-sz", "srv-1", path, size + 100, checksum)
        with pytest.raises(RestoreError, match="size"):
            await perform_safe_restore(
                BackupJobId("res-bad-sz"), str(server_dir), storage=storage, encryption=encryption
            )

        await _seed_job("res-miss", "srv-1", "gone.tar.gz.enc", 0, "x")
        with pytest.raises(RestoreError, match="missing"):
            await perform_safe_restore(
                BackupJobId("res-miss"),
                str(server_dir),
                storage=_FakeStorage(),
                encryption=encryption,
            )
        assert (server_dir / "world" / "level.dat").read_text(encoding="utf-8") == "old"

    async def test_swaps_plugins_configs_playerdata_and_full_archive(self, tmp_path: Path) -> None:
        # Plugins
        srv_plug = tmp_path / "srv_plug"
        _write(srv_plug, "plugins/old.jar", "old-plugin")
        _write(srv_plug, "world/level.dat", "keep-world")
        src_plug = tmp_path / "src_plug"
        _write(src_plug, "plugins/new.jar", "new-plugin")
        st, enc, p, sz, cs = await self._build_artifact(str(src_plug), ["plugins"])
        await _seed_job("res-plug", "srv-1", p, sz, cs)
        assert await perform_safe_restore(
            BackupJobId("res-plug"), str(srv_plug), storage=st, encryption=enc
        ) == ["plugins"]
        assert (srv_plug / "plugins" / "new.jar").read_text(encoding="utf-8") == "new-plugin"
        assert not (srv_plug / "plugins" / "old.jar").exists()
        assert (srv_plug / "world" / "level.dat").read_text(encoding="utf-8") == "keep-world"

        # Config files
        srv_cfg = tmp_path / "srv_cfg"
        _write(srv_cfg, "server.properties", "old-motd")
        _write(srv_cfg, "eula.txt", "old-eula")
        _write(srv_cfg, "world/level.dat", "keep-world")
        src_cfg = tmp_path / "src_cfg"
        _write(src_cfg, "server.properties", "new-motd")
        st, enc, p, sz, cs = await self._build_artifact(str(src_cfg), ["server.properties"])
        await _seed_job("res-cfg", "srv-1", p, sz, cs)
        assert await perform_safe_restore(
            BackupJobId("res-cfg"), str(srv_cfg), storage=st, encryption=enc
        ) == ["server.properties"]
        assert (srv_cfg / "server.properties").read_text(encoding="utf-8") == "new-motd"
        assert (srv_cfg / "eula.txt").read_text(encoding="utf-8") == "old-eula"

        # Playerdata namespace swaps only nested subfolder and skips missing dimension
        srv_pd = tmp_path / "srv_pd"
        _write(srv_pd, "world/level.dat", "old-level")
        _write(srv_pd, "world/playerdata/abc.dat", "old-pd")
        _write(srv_pd, "world_nether/DIM-1/region.dat", "old-nether")
        src_pd = tmp_path / "src_pd"
        _write(src_pd, "mcs_playerdata/world/playerdata/abc.dat", "new-pd")
        st, enc, p, sz, cs = await self._build_artifact(
            str(src_pd), ["mcs_playerdata/world/playerdata"]
        )
        await _seed_job("res-pd", "srv-1", p, sz, cs)
        assert await perform_safe_restore(
            BackupJobId("res-pd"), str(srv_pd), storage=st, encryption=enc
        ) == ["playerdata:world"]
        assert (srv_pd / "world" / "playerdata" / "abc.dat").read_text(encoding="utf-8") == "new-pd"
        assert (srv_pd / "world" / "level.dat").read_text(encoding="utf-8") == "old-level"

        srv_pd_skip = tmp_path / "srv_pd_skip"
        _write(srv_pd_skip, "world/level.dat", "keep-level")
        src_pd_skip = tmp_path / "src_pd_skip"
        _write(src_pd_skip, "mcs_playerdata/world_nether/playerdata/abc.dat", "orphan-pd")
        st, enc, p, sz, cs = await self._build_artifact(
            str(src_pd_skip), ["mcs_playerdata/world_nether/playerdata"]
        )
        await _seed_job("res-pd-skip", "srv-1", p, sz, cs)
        assert (
            await perform_safe_restore(
                BackupJobId("res-pd-skip"), str(srv_pd_skip), storage=st, encryption=enc
            )
            == []
        )
        assert not (srv_pd_skip / "world_nether").exists()

        # Full archive restores dims, plugins, configs together
        srv_full = tmp_path / "srv_full"
        _write(srv_full, "world/level.dat", "old")
        _write(srv_full, "plugins/old.jar", "old")
        src_full = tmp_path / "src_full"
        _write(src_full, "world/level.dat", "new-level")
        _write(src_full, "world_nether/DIM-1/region.dat", "new-nether")
        _write(src_full, "world_the_end/DIM1/region.dat", "new-end")
        _write(src_full, "plugins/new.jar", "new-plugin")
        _write(src_full, "server.properties", "new-motd")
        _write(src_full, "eula.txt", "new-eula")
        st, enc, p, sz, cs = await self._build_artifact(
            str(src_full),
            ["world", "world_nether", "world_the_end", "plugins", "server.properties", "eula.txt"],
        )
        await _seed_job("res-full", "srv-1", p, sz, cs)
        restored_full = await perform_safe_restore(
            BackupJobId("res-full"), str(srv_full), storage=st, encryption=enc
        )
        assert set(restored_full) == {
            "world",
            "world_nether",
            "world_the_end",
            "plugins",
            "server.properties",
            "eula.txt",
        }
        assert (srv_full / "eula.txt").read_text(encoding="utf-8") == "new-eula"

    async def test_enospc_mid_restore_rolls_back_applied_dimensions(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "server"
        _write(server_dir, "world/level.dat", "old-world")
        _write(server_dir, "world_nether/DIM1.dat", "old-nether")
        source = tmp_path / "src"
        _write(source, "world/level.dat", "new-world")
        _write(source, "world_nether/DIM1.dat", "new-nether")
        storage, encryption, path, size, checksum = await self._build_artifact(
            str(source), ["world", "world_nether"]
        )
        await _seed_job("res-svc-enospc", "srv-1", path, size, checksum)

        real_replace = restore_module._atomic_replace_dir
        applied: list[str] = []

        def flaky_replace(src: str, dst: str, backup_dir: str | None = None) -> str | None:
            if applied:
                raise OSError(errno.ENOSPC, "injected disk full")
            applied.append(dst)
            return real_replace(src, dst, backup_dir)

        with (
            patch.object(restore_module, "_atomic_replace_dir", side_effect=flaky_replace),
            pytest.raises(InsufficientStorageError) as excinfo,
        ):
            await perform_safe_restore(
                BackupJobId("res-svc-enospc"),
                str(server_dir),
                storage=storage,
                encryption=encryption,
            )

        assert excinfo.value.http_status == 507
        assert applied == [os.path.join(str(server_dir), "world")]
        assert (server_dir / "world" / "level.dat").read_text(encoding="utf-8") == "old-world"
        assert (server_dir / "world_nether" / "DIM1.dat").read_text(
            encoding="utf-8"
        ) == "old-nether"

    async def test_trailing_dot_member_fails_closed_before_live_dir_changes(
        self, tmp_path: Path
    ) -> None:
        server_dir = tmp_path / "server"
        _write(server_dir, "world/level.dat", "old-world")
        source = tmp_path / "src"
        _write(source, "world/level.dat", "new-world")

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            tar.add(os.path.join(str(source), "world"), arcname="world")
            info = tarfile.TarInfo(name="plugins/bad.yml.")
            info.size = 3
            tar.addfile(info, io.BytesIO(b"bad"))

        encryption = BackupEncryption()
        encrypted = encryption.encrypt(buf.getvalue())
        storage = _FakeStorage()
        await storage.write("bad-member.tar.gz.enc", encrypted)
        await _seed_job(
            "res-bad-member",
            "srv-1",
            "bad-member.tar.gz.enc",
            len(encrypted),
            encryption.checksum(encrypted),
        )

        with pytest.raises(
            RestoreError, match="Unsafe or trailing-dot/space member path in backup archive"
        ):
            await perform_safe_restore(
                BackupJobId("res-bad-member"),
                str(server_dir),
                storage=storage,
                encryption=encryption,
            )

        assert (server_dir / "world" / "level.dat").read_text(encoding="utf-8") == "old-world"
        assert not (server_dir / "plugins").exists()
        assert not list(tmp_path.glob("onx-restore-*"))


class TestConsumePendingRestore:
    async def test_no_pending_and_apply_and_failure_cleanup(self, tmp_path: Path) -> None:
        assert await consume_pending_restore("srv-none", str(tmp_path)) is None

        server_dir = tmp_path / "server"
        _write(server_dir, "world/level.dat", "old")
        source = tmp_path / "src"
        _write(source, "world/level.dat", "new")
        encryption = BackupEncryption()
        encrypted = encryption.encrypt(_make_archive(str(source), ["world"]))
        storage = _FakeStorage()
        await storage.write("ready.tar.gz.enc", encrypted)
        await _seed_job(
            "res-consume-ok",
            "srv-consume",
            "ready.tar.gz.enc",
            len(encrypted),
            encryption.checksum(encrypted),
        )

        async with database.session_factory() as session:
            await SQLBackupRepository(session).upsert_pending_restore(
                ServerId("srv-consume"), BackupJobId("res-consume-ok"), datetime.now(UTC)
            )
            await session.commit()

        with (
            patch(
                "app.modules.backup.application.restore_service.build_storage_backend",
                return_value=storage,
            ),
            patch(
                "app.modules.backup.application.restore_service.build_backup_encryption",
                return_value=encryption,
            ),
        ):
            assert await consume_pending_restore("srv-consume", str(server_dir)) == "res-consume-ok"
        assert (server_dir / "world" / "level.dat").read_text(encoding="utf-8") == "new"
        assert await _pending("srv-consume") is None

        # Failure clears pending row and raises RestoreError
        await _seed_job("res-consume-fail", "srv-consume-fail", "missing.tar.gz.enc", 10, "zzz")
        async with database.session_factory() as session:
            await SQLBackupRepository(session).upsert_pending_restore(
                ServerId("srv-consume-fail"), BackupJobId("res-consume-fail"), datetime.now(UTC)
            )
            await session.commit()
        with (
            patch(
                "app.modules.backup.application.restore_service.build_storage_backend",
                return_value=_FakeStorage(),
            ),
            patch(
                "app.modules.backup.application.restore_service.build_backup_encryption",
                return_value=BackupEncryption(),
            ),
            pytest.raises(RestoreError),
        ):
            await consume_pending_restore("srv-consume-fail", str(server_dir))
        assert await _pending("srv-consume-fail") is None


# ---------------------------------------------------------------------------
# Preflight Disk Space, Safe Tar Extract, & Atomic Swap
# ---------------------------------------------------------------------------


class TestTarSafetyAndAtomicSwap:
    def _tar_with_size(self, size: int) -> tarfile.TarFile:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo(name="world/level.dat")
            info.size = size
            tar.addfile(info, io.BytesIO(b"x" * size))
        buf.seek(0)
        return tarfile.open(fileobj=buf, mode="r:gz")

    def test_extract_space_uses_disk_usage_and_raises_507(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _forbidden(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("os.statvfs must not be used directly")

        calls: list[str] = []
        monkeypatch.setattr(os, "statvfs", _forbidden, raising=False)
        monkeypatch.setattr(
            restore_module.shutil,
            "disk_usage",
            lambda path: calls.append(str(path)) or SimpleNamespace(free=10**12),
        )
        with self._tar_with_size(1) as tar:
            _ensure_extract_space(str(tmp_path), tar)
        assert calls == [str(tmp_path)]

        monkeypatch.setattr(
            restore_module.shutil, "disk_usage", lambda _p: SimpleNamespace(free=1000)
        )
        with self._tar_with_size(1000) as tar, pytest.raises(InsufficientStorageError) as exc:
            _ensure_extract_space(str(tmp_path), tar)
        assert exc.value.http_status == 507
        assert exc.value.details == {"needed_bytes": 1000, "free_bytes": 1000}

        def _raise_os(_path: str):
            raise OSError(errno.ENOENT, "missing mount")

        monkeypatch.setattr(restore_module.shutil, "disk_usage", _raise_os)
        with self._tar_with_size(1000) as tar:
            _ensure_extract_space(str(tmp_path), tar)

    @pytest.mark.parametrize(
        ("member_name", "is_symlink", "linkname", "match"),
        [
            ("../../evil.txt", False, "", "Path traversal detected in backup archive"),
            ("/etc/passwd", False, "", "Path traversal detected in backup archive"),
            (
                "symlink_escape",
                True,
                "../../some_system_file",
                "Symlink traversal detected in backup archive",
            ),
        ],
    )
    def test_tar_slip_traversal_rejected(
        self,
        tmp_path: Path,
        member_name: str,
        is_symlink: bool,
        linkname: str,
        match: str,
    ) -> None:
        target_dir = tmp_path / "extract_target"
        target_dir.mkdir()
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo(name=member_name)
            if is_symlink:
                info.type = tarfile.SYMTYPE
                info.linkname = linkname
                tar.addfile(info)
            else:
                info.size = 4
                tar.addfile(info, io.BytesIO(b"evil"))

        buf.seek(0)
        with (
            tarfile.open(fileobj=buf, mode="r:gz") as tar,
            pytest.raises(RestoreError, match=match),
        ):
            _safe_extract_tar(tar, str(target_dir))
        assert not (tmp_path / "evil.txt").exists()

    @pytest.mark.parametrize(
        "bad_name",
        ["plugins/bad.yml.", "plugins/bad./ok.yml", "plugins/bad.yml ", "plugins/bad /ok.yml"],
    )
    def test_rejects_trailing_dot_or_space_members(self, tmp_path: Path, bad_name: str) -> None:
        target_dir = tmp_path / "extract_target"
        target_dir.mkdir()
        payload = _raw_tar([(bad_name, b"bad")])
        with (
            tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar,
            pytest.raises(
                RestoreError, match="Unsafe or trailing-dot/space member path in backup archive"
            ),
        ):
            _safe_extract_tar(tar, str(target_dir))
        assert list(target_dir.iterdir()) == []

    def test_rejects_backslash_and_nul_member_names(self, tmp_path: Path) -> None:
        target_dir = tmp_path / "extract_target"
        target_dir.mkdir()
        payload = _raw_tar([("plugins/evil\\name.yml", b"bad")])
        with (
            tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar,
            pytest.raises(RestoreError, match="Unsafe member path"),
        ):
            _safe_extract_tar(tar, str(target_dir))
        with pytest.raises(RestoreError, match="Unsafe member path"):
            _validate_tar_member_name(tarfile.TarInfo(name="plugins/evil\x00name.yml"))

    @pytest.mark.parametrize("root_name", [".", "./"])
    def test_benign_root_directory_and_regular_file_root_rejection(
        self, tmp_path: Path, root_name: str
    ) -> None:
        target_dir = tmp_path / "extract_target"
        target_dir.mkdir()
        payload = _raw_tar([(root_name, None), ("plugins/ok.yml", b"ok")])
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar:
            _safe_extract_tar(tar, str(target_dir))
        assert (target_dir / "plugins" / "ok.yml").read_bytes() == b"ok"

        bad_root = _raw_tar([(".", b"not-a-directory")])
        with (
            tarfile.open(fileobj=io.BytesIO(bad_root), mode="r:gz") as tar,
            pytest.raises(
                RestoreError, match="Unsafe or trailing-dot/space member path in backup archive"
            ),
        ):
            _safe_extract_tar(tar, str(tmp_path / "extract2"))

    def test_link_validation_rules(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Allowed relative symlink & root-relative hardlink inside root
        sym_ok = tarfile.TarInfo(name="config/link.yml")
        sym_ok.type = tarfile.SYMTYPE
        sym_ok.linkname = "../plugins/ok.yml"
        _validate_tar_member_link(sym_ok)

        hard_ok = tarfile.TarInfo(name="plugins/a/b/hard.yml")
        hard_ok.type = tarfile.LNKTYPE
        hard_ok.linkname = "world/level.dat"
        _validate_tar_member_link(hard_ok)

        # Rejected trailing dot/space, collapsing bad segment, empty/dot targets, hardlink escape
        for ltype, lname in [
            (tarfile.SYMTYPE, "../plugins/bad."),
            (tarfile.SYMTYPE, "../plugins/bad "),
            (tarfile.LNKTYPE, "../plugins/bad."),
            (tarfile.SYMTYPE, "bad./../ok.yml"),
        ]:
            m = tarfile.TarInfo(name="plugins/a/link.yml")
            m.type = ltype
            m.linkname = lname
            with pytest.raises(
                RestoreError, match="Unsafe or trailing-dot/space link target in backup archive"
            ):
                _validate_tar_member_link(m)

        for empty_name in ("", "."):
            m = tarfile.TarInfo(name="plugins/a/link.yml")
            m.type = tarfile.SYMTYPE
            m.linkname = empty_name
            with pytest.raises(RestoreError, match="Unsafe or empty link target in backup archive"):
                _validate_tar_member_link(m)

        # Link validation must never use os.path.abspath (strips trailing dots on Windows)
        class _PathProxy:
            def __getattr__(self, name: str):
                return getattr(os.path, name)

            def abspath(self, _path: object) -> str:
                raise AssertionError("os.path.abspath must not be used for link validation")

        class _OsProxy:
            def __init__(self) -> None:
                self.path = _PathProxy()

            def __getattr__(self, name: str):
                return getattr(os, name)

        sym_bad = tarfile.TarInfo(name="plugins/a/link.yml")
        sym_bad.type = tarfile.SYMTYPE
        sym_bad.linkname = "../plugins/bad."
        with (
            patch.object(restore_module, "os", _OsProxy()),
            pytest.raises(
                RestoreError, match="Unsafe or trailing-dot/space link target in backup archive"
            ),
        ):
            _validate_tar_member_link(sym_bad)

        # Hardlink escaping root rejected
        target_dir = tmp_path / "extract_hard"
        target_dir.mkdir()
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo(name="plugins/a/b/hard.yml")
            info.type = tarfile.LNKTYPE
            info.linkname = "../ok.yml"
            tar.addfile(info)
        with (
            tarfile.open(fileobj=io.BytesIO(buf.getvalue()), mode="r:gz") as tar,
            pytest.raises(RestoreError, match="Symlink traversal detected in backup archive"),
        ):
            _safe_extract_tar(tar, str(target_dir))

        # Windows cross-drive commonpath ValueError raises RestoreError
        def _raise_drive(_paths: object) -> str:
            raise ValueError("Paths don't have the same drive")

        monkeypatch.setattr(os.path, "commonpath", _raise_drive)
        with (
            tarfile.open(
                fileobj=io.BytesIO(_raw_tar([("plugins/ok.yml", b"ok")])), mode="r:gz"
            ) as tar,
            pytest.raises(RestoreError, match="Path traversal detected in backup archive"),
        ):
            _safe_extract_tar(tar, str(target_dir))

    def test_atomic_replace_file_and_dir_use_uuid_and_clean_src(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        src_file = tmp_path / "src.txt"
        src_file.write_text("hello", encoding="utf-8")
        dst_file = tmp_path / "dst.txt"

        replaced: list[tuple[str, str]] = []
        real_replace = os.replace

        def tracked_replace(src_p, dst_p):
            replaced.append((src_p, dst_p))
            return real_replace(src_p, dst_p)

        monkeypatch.setattr(os, "replace", tracked_replace)
        _atomic_replace_file(str(src_file), str(dst_file))
        assert len(replaced) == 1
        assert len(os.path.basename(replaced[0][0])) > 32
        assert dst_file.read_text(encoding="utf-8") == "hello"

        replaced.clear()
        src_dir = tmp_path / "src_dir"
        src_dir.mkdir()
        (src_dir / "data.txt").write_text("restored data", encoding="utf-8")
        dst_dir = tmp_path / "target_dir" / "live"
        dst_dir.parent.mkdir()
        dst_dir.mkdir()
        (dst_dir / "data.txt").write_text("old data", encoding="utf-8")

        _atomic_replace_dir(str(src_dir), str(dst_dir))
        assert (dst_dir / "data.txt").read_text(encoding="utf-8") == "restored data"
        assert not src_dir.exists()
        assert any(".stage" in s for s, _ in replaced)


# ---------------------------------------------------------------------------
# Two-Tier Restore (Tier-1 Snapshot & Tier-2 Archive)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name != "posix", reason="ArtifactCas requires POSIX")
class TestTwoTierRestore:
    def _seed_server(self, server_dir: Path, cas: ArtifactCas) -> str:
        (server_dir / "world").mkdir(parents=True, exist_ok=True)
        (server_dir / "world" / "level.dat").write_bytes(b"original-world")
        (server_dir / "ops.json").write_text('[{"name":"orig"}]', encoding="utf-8")
        (server_dir / "server.properties").write_text("motd=Original\n", encoding="utf-8")
        (server_dir / "mods").mkdir(exist_ok=True)
        (server_dir / "mods" / "keep.jar").write_bytes(b"class-a-jar")
        user_sha = cas.put_bytes(b"user-jar-bytes")
        (server_dir / "onx-jars.lock.json").write_text(
            json.dumps(
                {"files": [{"path": "mods/user.jar", "sha256": user_sha, "origin": "user"}]}
            ),
            encoding="utf-8",
        )
        return user_sha

    async def test_tier1_and_tier2_restore_roundtrip_and_cas_repopulation(
        self, tmp_path: Path
    ) -> None:
        server_dir = tmp_path / "srv"
        snaps_root = tmp_path / "snaps"
        cas = ArtifactCas(tmp_path / "cas")
        storage = LocalStorage(str(tmp_path / "backups"))
        kek = MasterKek(kek_version=1, key_bytes=b"\x55" * 32)
        user_sha = self._seed_server(server_dir, cas)

        t1 = await create_tier1_snapshot(
            server_id="srv-1", server_dir=server_dir, snapshots_root=snaps_root, backup_id="t1-good"
        )
        t2 = await create_tier2_archive(
            server_id="srv-1",
            server_dir=server_dir,
            backup_id="t2-good",
            storage=storage,
            archive_format="tar.zst",
            include_cas_jars=True,
            kek=kek,
            cas=cas,
        )

        (server_dir / "world" / "level.dat").write_bytes(b"corrupted-world")
        (server_dir / "ops.json").write_text("[]", encoding="utf-8")
        (server_dir / "server.properties").write_text("motd=Mutated\n", encoding="utf-8")

        r1 = await restore_tier1_snapshot(
            server_id="srv-1",
            server_dir=server_dir,
            snapshot_dir=Path(t1.snapshot_dir),
            backup_id="t1-good",
        )
        assert r1.tier == "tier_1"
        assert (server_dir / "world" / "level.dat").read_bytes() == b"original-world"
        assert (server_dir / "mods" / "keep.jar").read_bytes() == b"class-a-jar"

        (server_dir / "world" / "level.dat").write_bytes(b"mutated-2")
        fresh_cas = ArtifactCas(tmp_path / "cas2")
        r2 = await restore_tier2_archive(
            server_id="srv-1",
            server_dir=server_dir,
            storage_path=t2.storage_path,
            backup_id="t2-good",
            storage=storage,
            expected_checksum=t2.checksum,
            kek=kek,
            cas=fresh_cas,
        )
        assert r2.tier == "tier_2" and r2.cas_blobs_restored == 1
        assert fresh_cas.has(user_sha)
        assert (server_dir / "world" / "level.dat").read_bytes() == b"original-world"
        assert (server_dir / "server.properties").read_text(encoding="utf-8") == "motd=Original\n"

    async def test_tier2_rejects_path_escape_symlinks_and_swap_rollback(
        self, tmp_path: Path
    ) -> None:
        server_dir = tmp_path / "srv"
        self._seed_server(server_dir, ArtifactCas(tmp_path / "cas"))

        evil_tar = tmp_path / "evil.tar.gz"
        with tarfile.open(evil_tar, "w:gz") as tf:
            info = tarfile.TarInfo(name="../escape.txt")
            info.size = 4
            tf.addfile(info, io.BytesIO(b"evil"))
        with pytest.raises(TwoTierRestoreError, match="Invalid path|unsafe|escape|Corrupt"):
            await restore_tier2_archive(
                server_id="srv-1",
                server_dir=server_dir,
                storage_path=str(evil_tar),
                backup_id="b-evil",
            )
        assert not (tmp_path / "escape.txt").exists()

        sym_tar = tmp_path / "sym.tar.gz"
        with tarfile.open(sym_tar, "w:gz") as tf:
            info = tarfile.TarInfo(name="triad/class_e/world/link")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tf.addfile(info)
        with pytest.raises(TwoTierRestoreError, match="unsafe link"):
            await restore_tier2_archive(
                server_id="srv-1",
                server_dir=server_dir,
                storage_path=str(sym_tar),
                backup_id="b-sym",
            )

        t1 = await create_tier1_snapshot(
            server_id="srv-1",
            server_dir=server_dir,
            snapshots_root=tmp_path / "snaps",
            backup_id="t1-swapfail",
        )
        with (
            patch(
                "app.modules.backup.application.two_tier_restore.swap_directories",
                side_effect=OSError("disk error during swap"),
            ),
            pytest.raises(TwoTierRestoreError, match="disk error"),
        ):
            await restore_tier1_snapshot(
                server_id="srv-1",
                server_dir=server_dir,
                snapshot_dir=Path(t1.snapshot_dir),
                backup_id="t1-swapfail",
            )
        assert (server_dir / "world" / "level.dat").read_bytes() == b"original-world"
