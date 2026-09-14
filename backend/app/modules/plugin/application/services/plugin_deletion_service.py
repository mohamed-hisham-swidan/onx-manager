from __future__ import annotations

import logging
import os

from app.core.persistence.db import database
from app.modules.plugin.infrastructure.repository import SQLPluginRepository
from app.modules.server.infrastructure.fs import FileSystem, local_fs
from app.modules.shared.value_objects import ServerId

logger = logging.getLogger(__name__)


async def consume_pending_plugin_deletions(
    server_id: str,
    server_dir: str,
    fs: FileSystem | None = None,
) -> list[dict]:
    """Apply deferred plugin deletions for server_id, then delete their DB rows.

    For every PluginModel row for this server with ``pending_deletion=True``:
    delete the file from ``<server_dir>/plugins/`` if it exists (no-op if it is
    already gone), then hard-delete the DB row. A file already absent from disk
    is reported as ``deleted: True`` — the observable end-state (file gone, row
    gone) is achieved either way.

    A file deletion that fails at the OS level (e.g. the file is still locked
    despite the server being stopped) preserves the pending row so the intent is
    not silently lost, but never raises — server startup must not be blocked by
    a stale/locked plugin file. Returns a list of
    ``{"plugin_id", "filename", "deleted", "error"}`` records for observability.
    """
    fs = fs or local_fs

    async with database.session_factory() as session:
        repo = SQLPluginRepository(session)
        pending = await repo.list_pending_deletions(ServerId(server_id))

    results: list[dict] = []
    dirs_to_check = [
        os.path.join(server_dir, "plugins"),
        os.path.join(server_dir, "mods"),
    ]

    for plugin in pending:
        filename = plugin.filename
        if filename:
            file_candidates = [filename, f"{filename}.disabled"]
            if filename.endswith(".disabled"):
                file_candidates.append(filename[:-9])

            deleted_any = False
            deletion_error: str | None = None

            for d in dirs_to_check:
                for candidate in file_candidates:
                    path = os.path.join(d, candidate)
                    if fs.exists(path):
                        try:
                            fs.delete(path)
                            deleted_any = True
                        except OSError as exc:
                            deletion_error = str(exc)
                            logger.error(
                                "Pending addon deletion failed — plugin_id=%s file=%s "
                                "error=%s server_id=%s",
                                plugin.plugin_id,
                                path,
                                exc,
                                server_id,
                            )

            if deletion_error and not deleted_any:
                results.append(
                    {
                        "plugin_id": str(plugin.plugin_id),
                        "filename": filename,
                        "deleted": False,
                        "error": deletion_error,
                    },
                )
                continue

        async with database.session_factory() as session:
            repo = SQLPluginRepository(session)
            await repo.delete(plugin.plugin_id)
            await session.commit()

        results.append(
            {
                "plugin_id": str(plugin.plugin_id),
                "filename": filename,
                "deleted": True,
                "error": None,
            },
        )
        logger.info(
            "Pending plugin deletion applied — plugin_id=%s filename=%s server_id=%s",
            plugin.plugin_id,
            filename,
            server_id,
        )

    return results
