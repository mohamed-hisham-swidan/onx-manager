import pytest

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
from app.storage.db import database


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
