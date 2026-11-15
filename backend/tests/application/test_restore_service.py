import errno
import io
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
from app.modules.backup.application.restore_service import (
    RestoreError,
    _ensure_extract_space,
    _safe_extract_tar,
    _validate_tar_member_link,
    _validate_tar_member_name,
    consume_pending_restore,
    perform_safe_restore,
)
from app.modules.backup.domain.aggregate import BackupJob
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.shared.value_objects import BackupJobId, ServerId
from app.modules.storage.base import StorageBackend, StorageResult
from app.modules.storage.encryption import BackupEncryption


class FakeStorage(StorageBackend):
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
    """Build a .tar.gz from ``(name, data)`` pairs; ``data is None`` means directory."""
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


def _write(tmp_path: Path, rel: str, content: str = "") -> Path:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
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
        repo = SQLBackupRepository(session)
        return await repo.get_pending_restore(ServerId(server_id))


@pytest.mark.usefixtures("init_test_db")
class TestPerformSafeRestore:
    async def _build_artifact(
        self,
        source_dir: str,
        names: list[str],
    ) -> tuple[FakeStorage, BackupEncryption, str, int, str]:
        encryption = BackupEncryption()
        plaintext = _make_archive(source_dir, names)
        encrypted = encryption.encrypt(plaintext)
        storage = FakeStorage()
        path = "res-svc.tar.gz.enc"
        await storage.write(path, encrypted)
        return storage, encryption, path, len(encrypted), encryption.checksum(encrypted)

    @pytest.mark.asyncio
    async def test_swaps_present_dimensions_and_leaves_others(self, tmp_path) -> None:
        server_dir = tmp_path / "server"
        _write(server_dir, "world/level.dat", "old-world")
        _write(server_dir, "world_nether/DIM1.dat", "old-nether")
        _write(server_dir, "plugins/p.jar", "keep-me")

        source = tmp_path / "src"
        _write(source, "world/level.dat", "new-world")
        _write(source, "world_nether/DIM1.dat", "new-nether")

        storage, encryption, path, size, checksum = await self._build_artifact(
            str(source),
            ["world", "world_nether"],
        )
        await _seed_job("res-svc-ok", "srv-1", path, size, checksum)

        restored = await perform_safe_restore(
            BackupJobId("res-svc-ok"),
            str(server_dir),
            storage=storage,
            encryption=encryption,
        )

        assert restored == ["world", "world_nether"]
        assert (server_dir / "world" / "level.dat").read_text() == "new-world"
        assert (server_dir / "world_nether" / "DIM1.dat").read_text() == "new-nether"
        assert (server_dir / "plugins" / "p.jar").read_text() == "keep-me"
        assert not (server_dir / "world.onx-old").exists()
        assert not (server_dir / "world.mcs-old").exists()

    @pytest.mark.asyncio
    async def test_stages_extraction_on_same_filesystem_as_server(self, tmp_path) -> None:
        """Regression: extraction must be staged under server_dir's parent.

        Directory restore failed in production with OSError [Errno 18] EXDEV because
        the extract temp dir defaulted to /tmp (tmpfs) while the live server dir sits
        on a different mount — os.replace cannot rename across filesystems. The fix
        creates the extract temp dir as a sibling of server_dir so the atomic swap
        never crosses a mount.
        """
        server_dir = tmp_path / "server"
        _write(server_dir, "world/level.dat", "old-world")
        source = tmp_path / "src"
        _write(source, "world/level.dat", "new-world")

        storage, encryption, path, size, checksum = await self._build_artifact(
            str(source),
            ["world"],
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
        assert (server_dir / "world" / "level.dat").read_text() == "new-world"

        assert captured_dir == [os.path.dirname(os.path.abspath(str(server_dir)))]
        assert os.stat(captured_dir[0]).st_dev == os.stat(str(server_dir)).st_dev
        assert not list(tmp_path.glob("onx-restore-*"))
        assert not list(tmp_path.glob("mcs-restore-*"))

    @pytest.mark.asyncio
    async def test_custom_primary_world(self, tmp_path) -> None:
        server_dir = tmp_path / "server"
        _write(server_dir, "mypvp/level.dat", "old")

        source = tmp_path / "src"
        _write(source, "mypvp/level.dat", "new")

        storage, encryption, path, size, checksum = await self._build_artifact(
            str(source),
            ["mypvp"],
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
        assert (server_dir / "mypvp" / "level.dat").read_text() == "new"

    @pytest.mark.asyncio
    async def test_checksum_mismatch_refuses(self, tmp_path) -> None:
        server_dir = tmp_path / "server"
        _write(server_dir, "world/level.dat", "old")

        source = tmp_path / "src"
        _write(source, "world/level.dat", "new")

        storage, encryption, path, size, _ = await self._build_artifact(str(source), ["world"])
        await _seed_job("res-svc-checksum", "srv-1", path, size, "deadbeef")
        with pytest.raises(RestoreError, match="checksum"):
            await perform_safe_restore(
                BackupJobId("res-svc-checksum"),
                str(server_dir),
                storage=storage,
                encryption=encryption,
            )

        assert (server_dir / "world" / "level.dat").read_text() == "old"

    @pytest.mark.asyncio
    async def test_size_mismatch_refuses(self, tmp_path) -> None:
        server_dir = tmp_path / "server"
        _write(server_dir, "world/level.dat", "old")

        source = tmp_path / "src"
        _write(source, "world/level.dat", "new")

        storage, encryption, path, size, checksum = await self._build_artifact(
            str(source),
            ["world"],
        )
        await _seed_job("res-svc-size", "srv-1", path, size + 100, checksum)

        with pytest.raises(RestoreError, match="size"):
            await perform_safe_restore(
                BackupJobId("res-svc-size"),
                str(server_dir),
                storage=storage,
                encryption=encryption,
            )

        assert (server_dir / "world" / "level.dat").read_text() == "old"

    @pytest.mark.asyncio
    async def test_missing_artifact_refuses(self, tmp_path) -> None:
        server_dir = tmp_path / "server"
        _write(server_dir, "world/level.dat", "old")

        storage = FakeStorage()
        encryption = BackupEncryption()
        await _seed_job("res-svc-missing", "srv-1", "gone.tar.gz.enc", 0, "x")

        with pytest.raises(RestoreError, match="missing"):
            await perform_safe_restore(
                BackupJobId("res-svc-missing"),
                str(server_dir),
                storage=storage,
                encryption=encryption,
            )

    @pytest.mark.asyncio
    async def test_swaps_plugins_folder_and_leaves_it_when_absent(self, tmp_path) -> None:
        server_dir = tmp_path / "server"
        _write(server_dir, "plugins/old.jar", "old-plugin")
        _write(server_dir, "world/level.dat", "keep-world")

        source = tmp_path / "src"
        _write(source, "plugins/new.jar", "new-plugin")

        storage, encryption, path, size, checksum = await self._build_artifact(
            str(source),
            ["plugins"],
        )
        await _seed_job("res-svc-plugins", "srv-1", path, size, checksum)

        restored = await perform_safe_restore(
            BackupJobId("res-svc-plugins"),
            str(server_dir),
            storage=storage,
            encryption=encryption,
        )

        assert restored == ["plugins"]
        assert (server_dir / "plugins" / "new.jar").read_text() == "new-plugin"
        assert not (server_dir / "plugins" / "old.jar").exists()
        assert (server_dir / "world" / "level.dat").read_text() == "keep-world"

    @pytest.mark.asyncio
    async def test_swaps_config_files_at_file_level(self, tmp_path) -> None:
        server_dir = tmp_path / "server"
        _write(server_dir, "server.properties", "old-motd")
        _write(server_dir, "eula.txt", "old-eula")
        _write(server_dir, "world/level.dat", "keep-world")

        source = tmp_path / "src"
        _write(source, "server.properties", "new-motd")

        storage, encryption, path, size, checksum = await self._build_artifact(
            str(source),
            ["server.properties"],
        )
        await _seed_job("res-svc-config", "srv-1", path, size, checksum)

        restored = await perform_safe_restore(
            BackupJobId("res-svc-config"),
            str(server_dir),
            storage=storage,
            encryption=encryption,
        )

        assert restored == ["server.properties"]
        assert (server_dir / "server.properties").read_text() == "new-motd"
        assert (server_dir / "eula.txt").read_text() == "old-eula"
        assert (server_dir / "world" / "level.dat").read_text() == "keep-world"

    @pytest.mark.asyncio
    async def test_playerdata_namespace_swaps_only_nested_subfolder(self, tmp_path) -> None:
        server_dir = tmp_path / "server"
        _write(server_dir, "world/level.dat", "old-level")
        _write(server_dir, "world/playerdata/abc.dat", "old-pd")
        _write(server_dir, "world_nether/DIM-1/region.dat", "old-nether")

        source = tmp_path / "src"
        _write(source, "mcs_playerdata/world/playerdata/abc.dat", "new-pd")

        storage, encryption, path, size, checksum = await self._build_artifact(
            str(source),
            ["mcs_playerdata/world/playerdata"],
        )
        await _seed_job("res-svc-pd", "srv-1", path, size, checksum)

        restored = await perform_safe_restore(
            BackupJobId("res-svc-pd"),
            str(server_dir),
            storage=storage,
            encryption=encryption,
        )

        assert restored == ["playerdata:world"]
        assert (server_dir / "world" / "playerdata" / "abc.dat").read_text() == "new-pd"
        assert (server_dir / "world" / "level.dat").read_text() == "old-level"
        assert (server_dir / "world_nether" / "DIM-1" / "region.dat").read_text() == "old-nether"

    @pytest.mark.asyncio
    async def test_playerdata_namespace_skips_when_live_dimension_absent(self, tmp_path) -> None:
        server_dir = tmp_path / "server"
        _write(server_dir, "world/level.dat", "keep-level")

        source = tmp_path / "src"
        _write(source, "mcs_playerdata/world_nether/playerdata/abc.dat", "orphan-pd")

        storage, encryption, path, size, checksum = await self._build_artifact(
            str(source),
            ["mcs_playerdata/world_nether/playerdata"],
        )
        await _seed_job("res-svc-pd-skip", "srv-1", path, size, checksum)

        restored = await perform_safe_restore(
            BackupJobId("res-svc-pd-skip"),
            str(server_dir),
            storage=storage,
            encryption=encryption,
        )

        assert restored == []
        assert not (server_dir / "world_nether").exists()

    @pytest.mark.asyncio
    async def test_full_archive_restores_dims_plugins_config_together(self, tmp_path) -> None:
        server_dir = tmp_path / "server"
        _write(server_dir, "world/level.dat", "old-level")
        _write(server_dir, "world_nether/DIM-1/region.dat", "old-nether")
        _write(server_dir, "world_the_end/DIM1/region.dat", "old-end")
        _write(server_dir, "plugins/old.jar", "old-plugin")
        _write(server_dir, "server.properties", "old-motd")

        source = tmp_path / "src"
        _write(source, "world/level.dat", "new-level")
        _write(source, "world_nether/DIM-1/region.dat", "new-nether")
        _write(source, "world_the_end/DIM1/region.dat", "new-end")
        _write(source, "plugins/new.jar", "new-plugin")
        _write(source, "server.properties", "new-motd")
        _write(source, "eula.txt", "new-eula")

        storage, encryption, path, size, checksum = await self._build_artifact(
            str(source),
            ["world", "world_nether", "world_the_end", "plugins", "server.properties", "eula.txt"],
        )
        await _seed_job("res-svc-full", "srv-1", path, size, checksum)

        restored = await perform_safe_restore(
            BackupJobId("res-svc-full"),
            str(server_dir),
            storage=storage,
            encryption=encryption,
        )

        assert set(restored) == {
            "world",
            "world_nether",
            "world_the_end",
            "plugins",
            "server.properties",
            "eula.txt",
        }
        assert (server_dir / "world" / "level.dat").read_text() == "new-level"
        assert (server_dir / "world_nether" / "DIM-1" / "region.dat").read_text() == "new-nether"
        assert (server_dir / "world_the_end" / "DIM1" / "region.dat").read_text() == "new-end"
        assert (server_dir / "plugins" / "new.jar").read_text() == "new-plugin"
        assert (server_dir / "server.properties").read_text() == "new-motd"
        assert (server_dir / "eula.txt").read_text() == "new-eula"

    @pytest.mark.asyncio
    async def test_level_name_property_restores_custom_world(self, tmp_path) -> None:
        """M-4: server.properties level-name selects the world folder to restore."""
        server_dir = tmp_path / "server"
        _write(server_dir, "server.properties", "motd=x\nlevel-name=mypvp\n")
        _write(server_dir, "mypvp/level.dat", "old-custom")

        source = tmp_path / "src"
        _write(source, "mypvp/level.dat", "new-custom")

        storage, encryption, path, size, checksum = await self._build_artifact(
            str(source), ["mypvp"]
        )
        await _seed_job("res-svc-level-name", "srv-1", path, size, checksum)

        restored = await perform_safe_restore(
            BackupJobId("res-svc-level-name"),
            str(server_dir),
            storage=storage,
            encryption=encryption,
        )

        assert restored == ["mypvp"]
        assert (server_dir / "mypvp" / "level.dat").read_text() == "new-custom"

    @pytest.mark.asyncio
    async def test_level_name_traversal_falls_back_to_world(self, tmp_path) -> None:
        """M-4: a traversal-shaped level-name is ignored (default world)."""
        server_dir = tmp_path / "server"
        _write(server_dir, "server.properties", "level-name=../escape\n")
        _write(server_dir, "world/level.dat", "old-world")

        source = tmp_path / "src"
        _write(source, "world/level.dat", "new-world")

        storage, encryption, path, size, checksum = await self._build_artifact(
            str(source), ["world"]
        )
        await _seed_job("res-svc-level-traversal", "srv-1", path, size, checksum)

        restored = await perform_safe_restore(
            BackupJobId("res-svc-level-traversal"),
            str(server_dir),
            storage=storage,
            encryption=encryption,
        )

        assert restored == ["world"]
        assert (server_dir / "world" / "level.dat").read_text() == "new-world"
        assert not (tmp_path / "escape").exists()

    @pytest.mark.asyncio
    async def test_enospc_mid_restore_rolls_back_applied_dimensions(
        self, tmp_path
    ) -> None:
        """M-4/MINOR 2: a mid-loop ENOSPC restores items from temp_dir/prev."""
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

        from app.modules.backup.application import restore_service as restore_module

        real_replace = restore_module._atomic_replace_dir
        applied: list[str] = []

        def flaky_replace(
            src: str, dst: str, backup_dir: str | None = None
        ) -> str | None:
            if applied:
                raise OSError(errno.ENOSPC, "injected disk full")
            applied.append(dst)
            return real_replace(src, dst, backup_dir)

        with (
            patch.object(
                restore_module, "_atomic_replace_dir", side_effect=flaky_replace
            ),
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
        assert (server_dir / "world" / "level.dat").read_text() == "old-world"
        assert (server_dir / "world_nether" / "DIM1.dat").read_text() == "old-nether"

    @pytest.mark.asyncio
    async def test_trailing_dot_member_fails_closed_before_live_dir_changes(
        self, tmp_path
    ) -> None:
        """Reject an anomalous legacy archive before the live server dir is touched."""
        server_dir = tmp_path / "server"
        _write(server_dir, "world/level.dat", "old-world")

        source = tmp_path / "src"
        _write(source, "world/level.dat", "new-world")

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            tar.add(os.path.join(str(source), "world"), arcname="world")
            info = tarfile.TarInfo(name="plugins/bad.yml.")
            data = b"bad"
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        plaintext = buf.getvalue()

        encryption = BackupEncryption()
        encrypted = encryption.encrypt(plaintext)
        storage = FakeStorage()
        path = "bad-member.tar.gz.enc"
        await storage.write(path, encrypted)
        await _seed_job(
            "res-svc-bad-member",
            "srv-1",
            path,
            len(encrypted),
            encryption.checksum(encrypted),
        )

        with pytest.raises(
            RestoreError,
            match="Unsafe or trailing-dot/space member path in backup archive",
        ):
            await perform_safe_restore(
                BackupJobId("res-svc-bad-member"),
                str(server_dir),
                storage=storage,
                encryption=encryption,
            )

        assert (server_dir / "world" / "level.dat").read_text() == "old-world"
        assert not (server_dir / "plugins").exists()
        assert not list(tmp_path.glob("onx-restore-*"))
        assert not list(tmp_path.glob("mcs-restore-*"))


@pytest.mark.usefixtures("init_test_db")
class TestConsumePendingRestore:
    async def _build_ready_restore(
        self,
        tmp_path: Path,
    ) -> tuple[str, FakeStorage, BackupEncryption]:
        server_dir = tmp_path / "server"
        _write(server_dir, "world/level.dat", "old")
        source = tmp_path / "src"
        _write(source, "world/level.dat", "new")

        encryption = BackupEncryption()
        plaintext = _make_archive(str(source), ["world"])
        encrypted = encryption.encrypt(plaintext)
        storage = FakeStorage()
        await storage.write("ready.tar.gz.enc", encrypted)
        await _seed_job(
            "res-consume-ok",
            "srv-consume",
            "ready.tar.gz.enc",
            len(encrypted),
            encryption.checksum(encrypted),
        )
        return str(server_dir), storage, encryption

    @pytest.mark.asyncio
    async def test_no_pending_returns_none(self, tmp_path) -> None:
        result = await consume_pending_restore("srv-none", str(tmp_path))
        assert result is None

    @pytest.mark.asyncio
    async def test_applies_and_deletes_pending(self, tmp_path) -> None:
        server_dir, storage, encryption = await self._build_ready_restore(tmp_path)

        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            await repo.upsert_pending_restore(
                ServerId("srv-consume"),
                BackupJobId("res-consume-ok"),
                datetime.now(UTC),
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
            result = await consume_pending_restore("srv-consume", server_dir)

        assert result == "res-consume-ok"
        assert (Path(server_dir) / "world" / "level.dat").read_text() == "new"
        assert await _pending("srv-consume") is None

    @pytest.mark.asyncio
    async def test_failure_preserves_pending_row(self, tmp_path) -> None:
        server_dir, storage, encryption = await self._build_ready_restore(tmp_path)

        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            await repo.upsert_pending_restore(
                ServerId("srv-consume-fail"),
                BackupJobId("res-consume-fail"),
                datetime.now(UTC),
            )
            await session.commit()

        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            job = BackupJob.create(
                backup_id=BackupJobId("res-consume-fail"),
                server_id=ServerId("srv-consume-fail"),
            )
            job.mark_completed(size_bytes=10, checksum="zzz", storage_path="missing.tar.gz.enc")
            await repo.save_job(job)
            await session.commit()

        with (
            patch(
                "app.modules.backup.application.restore_service.build_storage_backend",
                return_value=FakeStorage(),
            ),
            patch(
                "app.modules.backup.application.restore_service.build_backup_encryption",
                return_value=BackupEncryption(),
            ),
            pytest.raises(RestoreError),
        ):
            await consume_pending_restore("srv-consume-fail", server_dir)

        pending = await _pending("srv-consume-fail")
        assert pending is not None
        assert pending[0] == "res-consume-fail"


class TestEnsureExtractSpace:
    """Cross-platform regression coverage for ``shutil.disk_usage`` preflight."""

    def _tar_with_size(self, size: int) -> tarfile.TarFile:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo(name="world/level.dat")
            info.size = size
            tar.addfile(info, io.BytesIO(b"x" * size))
        buf.seek(0)
        return tarfile.open(fileobj=buf, mode="r:gz")

    def test_routes_free_space_through_disk_usage(self, tmp_path: Path, monkeypatch) -> None:
        """Windows has no os.statvfs; the preflight must call shutil.disk_usage."""
        from app.modules.backup.application import restore_service as restore_module

        def _forbidden(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("os.statvfs must not be used directly")

        calls: list[str] = []
        monkeypatch.setattr(os, "statvfs", _forbidden, raising=False)
        monkeypatch.setattr(
            restore_module.shutil,
            "disk_usage",
            lambda path: calls.append(str(path)) or SimpleNamespace(free=10**12),
        )
        tar = self._tar_with_size(1)
        try:
            _ensure_extract_space(str(tmp_path), tar)
        finally:
            tar.close()

        assert calls == [str(tmp_path)]

    @pytest.mark.skipif(
        os.name == "posix",
        reason="POSIX shutil.disk_usage itself calls os.statvfs",
    )
    def test_works_on_native_windows_without_statvfs(self, tmp_path: Path) -> None:
        assert not hasattr(os, "statvfs")
        tar = self._tar_with_size(1)
        try:
            _ensure_extract_space(str(tmp_path), tar)
        finally:
            tar.close()

    def test_insufficient_space_raises(self, tmp_path: Path, monkeypatch) -> None:
        from app.modules.backup.application import restore_service as restore_module

        monkeypatch.delattr(os, "statvfs", raising=False)
        monkeypatch.setattr(
            restore_module.shutil,
            "disk_usage",
            lambda _path: SimpleNamespace(free=1000),
        )
        tar = self._tar_with_size(1000)
        try:
            with pytest.raises(InsufficientStorageError) as excinfo:
                _ensure_extract_space(str(tmp_path), tar)
        finally:
            tar.close()

        assert excinfo.value.http_status == 507
        assert excinfo.value.details == {"needed_bytes": 1000, "free_bytes": 1000}

    def test_disk_usage_oserror_passes_through(self, tmp_path: Path, monkeypatch) -> None:
        from app.modules.backup.application import restore_service as restore_module

        def _raise(_path: str):
            raise OSError(errno.ENOENT, "missing mount")

        monkeypatch.setattr(restore_module.shutil, "disk_usage", _raise)
        tar = self._tar_with_size(1000)
        try:
            _ensure_extract_space(str(tmp_path), tar)
        finally:
            tar.close()


class TestSafeTarExtract:
    def test_tar_slip_relative_path_traversal_raises_restore_error(self, tmp_path) -> None:
        target_dir = tmp_path / "extract_target"
        target_dir.mkdir()
        evil_file = tmp_path / "evil.txt"

        # Create an in-memory tar with a member attempting path traversal
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            data = b"malicious content"
            info = tarfile.TarInfo(name="../../evil.txt")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

        buf.seek(0)
        with (
            tarfile.open(fileobj=buf, mode="r:gz") as tar,
            pytest.raises(RestoreError, match="Path traversal detected in backup archive"),
        ):
            _safe_extract_tar(tar, str(target_dir))

        assert not evil_file.exists()

    def test_tar_slip_absolute_path_traversal_raises_restore_error(self, tmp_path) -> None:
        target_dir = tmp_path / "extract_target"
        target_dir.mkdir()

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            data = b"malicious content"
            info = tarfile.TarInfo(name="/etc/passwd")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

        buf.seek(0)
        with (
            tarfile.open(fileobj=buf, mode="r:gz") as tar,
            pytest.raises(RestoreError, match="Path traversal detected in backup archive"),
        ):
            _safe_extract_tar(tar, str(target_dir))

    def test_tar_slip_symlink_traversal_raises_restore_error(self, tmp_path) -> None:
        target_dir = tmp_path / "extract_target"
        target_dir.mkdir()

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo(name="symlink_escape")
            info.type = tarfile.SYMTYPE
            info.linkname = "../../some_system_file"
            tar.addfile(info)

        buf.seek(0)
        with (
            tarfile.open(fileobj=buf, mode="r:gz") as tar,
            pytest.raises(RestoreError, match="Symlink traversal detected in backup archive"),
        ):
            _safe_extract_tar(tar, str(target_dir))

    @pytest.mark.parametrize(
        "bad_name",
        [
            "plugins/bad.yml.",
            "plugins/bad./ok.yml",
            "plugins/bad.yml ",
            "plugins/bad /ok.yml",
        ],
    )
    def test_rejects_trailing_dot_or_space_members(
        self, tmp_path: Path, bad_name: str
    ) -> None:
        """Trailing dot/space fails for files AND intermediate dirs on every platform."""
        target_dir = tmp_path / "extract_target"
        target_dir.mkdir()

        payload = _raw_tar([(bad_name, b"bad")])
        with (
            tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar,
            pytest.raises(
                RestoreError,
                match="Unsafe or trailing-dot/space member path in backup archive",
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

        assert list(target_dir.iterdir()) == []

    @pytest.mark.parametrize("root_name", [".", "./"])
    def test_benign_root_directory_member_extracts_siblings(
        self, tmp_path: Path, root_name: str
    ) -> None:
        """A benign archive root entry (``.`` / ``./``) must not block valid siblings."""
        target_dir = tmp_path / "extract_target"
        target_dir.mkdir()

        payload = _raw_tar([(root_name, None), ("plugins/ok.yml", b"ok")])
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar:
            _safe_extract_tar(tar, str(target_dir))

        assert (target_dir / "plugins" / "ok.yml").read_bytes() == b"ok"

    def test_root_named_regular_file_member_rejected(self, tmp_path: Path) -> None:
        """Only directory entries may use the benign root/empty name form."""
        target_dir = tmp_path / "extract_target"
        target_dir.mkdir()

        payload = _raw_tar([(".", b"not-a-directory")])
        with (
            tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar,
            pytest.raises(
                RestoreError,
                match="Unsafe or trailing-dot/space member path in backup archive",
            ),
        ):
            _safe_extract_tar(tar, str(target_dir))

    def test_link_target_with_parent_reference_inside_root_allowed(self) -> None:
        """A ``../`` link that still resolves inside the extraction root must not fail."""
        member = tarfile.TarInfo(name="config/link.yml")
        member.type = tarfile.SYMTYPE
        member.linkname = "../plugins/ok.yml"

        _validate_tar_member_link(member)

    def test_hardlink_root_relative_target_inside_root_allowed(self) -> None:
        """M-1: LNKTYPE targets are archive-root-relative inside the extraction root."""
        member = tarfile.TarInfo(name="plugins/a/b/hard.yml")
        member.type = tarfile.LNKTYPE
        member.linkname = "world/level.dat"

        _validate_tar_member_link(member)

    @pytest.mark.parametrize("link_type", [tarfile.SYMTYPE, tarfile.LNKTYPE])
    @pytest.mark.parametrize("linkname", ["../plugins/bad.", "../plugins/bad "])
    def test_link_target_with_trailing_dot_or_space_rejected(
        self, link_type: bytes, linkname: str
    ) -> None:
        """B-1: trailing dot/space must fail before any host path normalization."""
        member = tarfile.TarInfo(name="plugins/a/link.yml")
        member.type = link_type
        member.linkname = linkname

        with pytest.raises(
            RestoreError,
            match="Unsafe or trailing-dot/space link target in backup archive",
        ):
            _validate_tar_member_link(member)

    def test_link_target_with_collapsing_bad_segment_rejected(self) -> None:
        """M-1: ``bad./..`` must not let normpath hide the non-canonical segment."""
        member = tarfile.TarInfo(name="config/link.yml")
        member.type = tarfile.SYMTYPE
        member.linkname = "bad./../ok.yml"

        with pytest.raises(
            RestoreError,
            match="Unsafe or trailing-dot/space link target in backup archive",
        ):
            _validate_tar_member_link(member)

    def test_link_validation_does_not_use_host_abspath(self) -> None:
        """B-1: Windows abspath strips trailing dot/space, so it must not be used."""
        from app.modules.backup.application import restore_service as restore_module

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

        member = tarfile.TarInfo(name="plugins/a/link.yml")
        member.type = tarfile.SYMTYPE
        member.linkname = "../plugins/bad."

        with (
            patch.object(restore_module, "os", _OsProxy()),
            pytest.raises(
                RestoreError,
                match="Unsafe or trailing-dot/space link target in backup archive",
            ),
        ):
            _validate_tar_member_link(member)

    @pytest.mark.parametrize("linkname", ["", "."])
    def test_empty_or_dot_link_target_rejected(self, linkname: str) -> None:
        """L-2: empty and ``.`` link targets are rejected up front."""
        member = tarfile.TarInfo(name="plugins/a/link.yml")
        member.type = tarfile.SYMTYPE
        member.linkname = linkname

        with pytest.raises(
            RestoreError, match="Unsafe or empty link target in backup archive"
        ):
            _validate_tar_member_link(member)

    def test_hardlink_root_relative_escape_rejected(self, tmp_path: Path) -> None:
        """M-1: LNKTYPE targets are root-relative; ``../ok.yml`` escapes the root."""
        target_dir = tmp_path / "extract_target"
        target_dir.mkdir()

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo(name="plugins/a/b/hard.yml")
            info.type = tarfile.LNKTYPE
            info.linkname = "../ok.yml"
            tar.addfile(info)

        with (
            tarfile.open(fileobj=io.BytesIO(buf.getvalue()), mode="r:gz") as tar,
            pytest.raises(
                RestoreError, match="Symlink traversal detected in backup archive"
            ),
        ):
            _safe_extract_tar(tar, str(target_dir))

    def test_commonpath_value_error_is_restore_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L-2: Windows cross-drive names make commonpath raise ValueError."""
        target_dir = tmp_path / "extract_target"
        target_dir.mkdir()

        def _raise(_paths: object) -> str:
            raise ValueError("Paths don't have the same drive")

        monkeypatch.setattr(os.path, "commonpath", _raise)

        payload = _raw_tar([("plugins/ok.yml", b"ok")])
        with (
            tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar,
            pytest.raises(RestoreError, match="Path traversal detected in backup archive"),
        ):
            _safe_extract_tar(tar, str(target_dir))

    def test_atomic_replace_file_uses_uuid(self, tmp_path, monkeypatch) -> None:
        from app.modules.backup.application.restore_service import _atomic_replace_file

        src = tmp_path / "src.txt"
        src.write_text("hello")
        dst = tmp_path / "dst.txt"

        replaced_paths = []
        real_replace = os.replace

        def mock_replace(src_p, dst_p):
            replaced_paths.append((src_p, dst_p))
            return real_replace(src_p, dst_p)

        monkeypatch.setattr(os, "replace", mock_replace)
        _atomic_replace_file(str(src), str(dst))

        assert len(replaced_paths) == 1
        tmp_used = replaced_paths[0][0]
        assert dst.read_text() == "hello"
        assert len(os.path.basename(tmp_used)) > 32

    def test_atomic_replace_dir_uses_uuid(self, tmp_path, monkeypatch) -> None:
        from app.modules.backup.application.restore_service import _atomic_replace_dir

        src = tmp_path / "src_dir"
        src.mkdir()
        (src / "data.txt").write_text("dir data")
        dst = tmp_path / "dst_dir"

        replaced_paths = []
        real_replace = os.replace

        def mock_replace(src_p, dst_p):
            replaced_paths.append((src_p, dst_p))
            return real_replace(src_p, dst_p)

        monkeypatch.setattr(os, "replace", mock_replace)
        _atomic_replace_dir(str(src), str(dst))

        assert dst.exists()
        assert (dst / "data.txt").read_text() == "dir data"
        assert len(replaced_paths) >= 1
        assert any(".stage" in src_p for src_p, _ in replaced_paths)

