from app.core.persistence.db import database
from app.core.query_bus import Query, QueryHandler
from app.modules.backup.application.queries.list_backups import BackupReadModel
from app.modules.backup.domain.repository import BackupRepository
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.shared.value_objects import BackupJobId


class GetBackupQuery(Query):
    backup_id: str


class GetBackupHandler(QueryHandler[GetBackupQuery]):
    async def handle(self, query: GetBackupQuery) -> BackupReadModel:
        async with database.session_factory() as session:
            repo: BackupRepository = SQLBackupRepository(session)
            job = await repo.get_job(BackupJobId(query.backup_id))
            return BackupReadModel.from_domain(job)
