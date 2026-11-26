from sqlalchemy import select

from app.core.persistence.db import database
from app.core.query_bus import Query, QueryHandler
from app.modules.backup.application.queries.list_backups import BackupReadModel
from app.modules.backup.domain.repository import BackupRepository
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.server.infrastructure.models import ServerModel
from app.modules.shared.value_objects import BackupJobId


class GetBackupQuery(Query):
    backup_id: str


class GetBackupHandler(QueryHandler[GetBackupQuery]):
    async def handle(self, query: GetBackupQuery) -> BackupReadModel:
        async with database.session_factory() as session:
            repo: BackupRepository = SQLBackupRepository(session)
            job = await repo.get_job(BackupJobId(query.backup_id))
            stmt = select(ServerModel.name).where(ServerModel.id == str(job.server_id))
            server_name = (await session.execute(stmt)).scalar_one_or_none()
            return BackupReadModel.from_domain(
                job,
                server_name=server_name,
                server_deleted=server_name is None,
            )
