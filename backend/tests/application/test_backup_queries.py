import pytest

from app.core.persistence.db import database
from app.modules.backup.application.queries.get_backup import (
    GetBackupHandler,
    GetBackupQuery,
)
from app.modules.backup.application.queries.list_backups import (
    ListBackupsHandler,
    ListBackupsQuery,
)
from app.modules.backup.domain.aggregate import BackupJob
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.shared.value_objects import BackupJobId, ServerId


@pytest.mark.usefixtures("init_test_db")
class TestGetBackupHandler:
    @pytest.mark.asyncio
    async def test_get_backup(self) -> None:
        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            job = BackupJob.create(
                backup_id=BackupJobId("get-bak-1"),
                server_id=ServerId("srv-1"),
            )
            job.mark_completed(size_bytes=1000, checksum="chk")
            await repo.save_job(job)
            await session.commit()

        handler = GetBackupHandler()
        result = await handler.handle(GetBackupQuery(backup_id="get-bak-1"))

        assert result is not None
        assert result.backup_id == "get-bak-1"
        assert result.status == "completed"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self) -> None:
        handler = GetBackupHandler()
        from app.core.exceptions import NotFoundError

        with pytest.raises(NotFoundError):
            await handler.handle(GetBackupQuery(backup_id="nonexistent"))


@pytest.mark.usefixtures("init_test_db")
class TestListBackupsHandler:
    @pytest.mark.asyncio
    async def test_list_backups(self) -> None:
        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            for i in range(3):
                job = BackupJob.create(
                    backup_id=BackupJobId(f"list-bak-{i}"),
                    server_id=ServerId("srv-1"),
                )
                job.collect_events()
                await repo.save_job(job)
            await session.commit()

        handler = ListBackupsHandler()
        result = await handler.handle(ListBackupsQuery())

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_list_by_server(self) -> None:
        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            j1 = BackupJob.create(backup_id=BackupJobId("ls-srv-1"), server_id=ServerId("srv-a"))
            j2 = BackupJob.create(backup_id=BackupJobId("ls-srv-2"), server_id=ServerId("srv-b"))
            j1.collect_events()
            j2.collect_events()
            await repo.save_job(j1)
            await repo.save_job(j2)
            await session.commit()

        handler = ListBackupsHandler()
        result = await handler.handle(ListBackupsQuery(server_id="srv-a"))

        assert len(result) == 1
        assert result[0].server_id == "srv-a"

    @pytest.mark.asyncio
    async def test_list_and_get_backups_enrich_server_name_and_deleted_flag(self) -> None:
        from app.modules.server.infrastructure.models import ServerModel

        async with database.session_factory() as session:
            session.add(
                ServerModel(
                    id="srv-live",
                    name="Survival Prime",
                    server_type="paper",
                    minecraft_version="1.21.4",
                    port=25565,
                    memory_min_mb=512,
                    memory_max_mb=1024,
                )
            )
            repo = SQLBackupRepository(session)
            j_live = BackupJob.create(
                backup_id=BackupJobId("bak-live-1"),
                server_id=ServerId("srv-live"),
            )
            j_orphan = BackupJob.create(
                backup_id=BackupJobId("bak-orphan-1"),
                server_id=ServerId("srv-gone"),
            )
            j_live.collect_events()
            j_orphan.collect_events()
            await repo.save_job(j_live)
            await repo.save_job(j_orphan)
            await session.commit()

        list_handler = ListBackupsHandler()
        items = await list_handler.handle(ListBackupsQuery())
        by_id = {item.backup_id: item for item in items}

        assert by_id["bak-live-1"].server_name == "Survival Prime"
        assert by_id["bak-live-1"].server_deleted is False
        assert by_id["bak-orphan-1"].server_name is None
        assert by_id["bak-orphan-1"].server_deleted is True

        get_handler = GetBackupHandler()
        live_detail = await get_handler.handle(GetBackupQuery(backup_id="bak-live-1"))
        orphan_detail = await get_handler.handle(GetBackupQuery(backup_id="bak-orphan-1"))
        assert live_detail.server_name == "Survival Prime"
        assert live_detail.server_deleted is False
        assert orphan_detail.server_name is None
        assert orphan_detail.server_deleted is True
