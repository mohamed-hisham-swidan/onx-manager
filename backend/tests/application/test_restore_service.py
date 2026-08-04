import io
import os
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.persistence.db import database
from app.modules.backup.application.restore_service import (
    RestoreError,
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

    async def list_files(self, _prefix: str) -> list:
        return []

    async def info(self, _path: str):
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
        self, source_dir: str, names: list[str],
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
