import logging
from pathlib import Path

from app.modules.server.domain.repository import ServerRepository
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.core.config import AppSettings
from app.core.persistence.db import database

logger = logging.getLogger("mcs.migrate_import_arch")

MIGRATION_FLAG_KEY = "_import_arch_migrated"


async def migrate_old_import_arch(repo: ServerRepository | None = None) -> int:
    removed = 0
    if repo is None:
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            removed = await _do_migration(repo)
    else:
        removed = await _do_migration(repo)
    return removed


async def _do_migration(repo: ServerRepository) -> int:
    from app.modules.server.domain.repository import ServerFilters

    all_servers = await repo.list()
    new_data_dir = Path(AppSettings().servers_data_dir).resolve()

    removed = 0
    for server in all_servers:
        dep = server.deployment
        if dep is None or not dep.root_path:
            continue

        root = Path(dep.root_path).resolve()
        try:
            is_new_arch = root.is_relative_to(new_data_dir)
        except AttributeError:
            is_new_arch = str(root).startswith(str(new_data_dir))

        if is_new_arch:
            continue

        logger.warning(
            "Removing old-arch server %s (%s) — root_path=%s (outside %s)",
            server.id, server.name, root, new_data_dir,
        )
        await repo.delete(server.id)
        removed += 1

    if removed:
        logger.info(
            "Import architecture migration: removed %d old-arch server(s). "
            "Re-import them to use the new copy-based architecture.",
            removed,
        )
    else:
        logger.info("Import architecture migration: no old-arch servers found.")

    return removed
