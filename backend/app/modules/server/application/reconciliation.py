from __future__ import annotations

import logging
import os
import time

from app.modules.server.application.services.jar_service import parse_server_dir_name
from app.modules.server.domain.aggregate import Server, ServerStatus
from app.modules.server.domain.repository import ServerRepository, ServerFilters
from app.modules.server.infrastructure.fs import local_fs
from app.modules.server.infrastructure.providers import provider_factory
from app.modules.server.infrastructure.providers.base import ServerHandle, ServerProvider, ServerRuntimeStatus
from app.modules.shared.value_objects import ServerId

logger = logging.getLogger("mcs.reconciliation")

def _servers_data_dir() -> str:
    from app.core.config import AppSettings
    return AppSettings().servers_data_dir

SERVERS_DATA_DIR = _servers_data_dir()


async def reconcile_filesystem(repo: ServerRepository) -> list[dict]:
    results: list[dict] = []
    data_dir = os.path.abspath(SERVERS_DATA_DIR)

    if not os.path.isdir(data_dir):
        logger.info("Servers data directory %s does not exist — skipping fs reconciliation", data_dir)
        return results

    try:
        all_servers = await repo.list()
    except Exception:
        logger.exception("Failed to list servers for filesystem reconciliation")
        return results

    db_ids: set[str] = {str(s.id) for s in all_servers}
    db_short_ids: set[str] = {str(s.id)[:8] for s in all_servers}

    orphan_count = 0
    for entry in os.listdir(data_dir):
        entry_path = os.path.join(data_dir, entry)
        if not os.path.isdir(entry_path):
            continue
        if entry in db_ids:
            continue
        dir_prefix = parse_server_dir_name(entry)
        if dir_prefix is not None and dir_prefix in db_short_ids:
            continue
        orphan_count += 1
        logger.warning("Orphan directory detected: %s (no matching DB record)", entry_path)
        results.append({
            "path": entry_path,
            "server_id": entry,
            "action": "pending",
        })

    logger.info(
        "Filesystem reconciliation complete: %d orphan directories found",
        orphan_count,
    )
    return results


async def cleanup_orphan_directory(dir_path: str) -> dict:
    try:
        local_fs.delete_dir(dir_path)
        logger.info("Cleaned up orphan directory: %s", dir_path)
        return {"path": dir_path, "action": "deleted", "success": True}
    except Exception as exc:
        logger.exception("Failed to clean up orphan directory: %s", dir_path)
        return {"path": dir_path, "action": "delete_failed", "success": False, "error": str(exc)}


STALE_STATUSES = {
    ServerStatus.STARTING,
    ServerStatus.RUNNING,
    ServerStatus.STOPPING,
}


async def reconcile_servers(repo: ServerRepository) -> list[dict]:
    results: list[dict] = []

    all_servers = await repo.list()

    stale_servers = [s for s in all_servers if s.status in STALE_STATUSES]
    if not stale_servers:
        logger.info("No stale runtime states found during reconciliation")
        return results

    logger.info(
        "Reconciling %d servers with stale runtime states",
        len(stale_servers),
    )

    for server in stale_servers:
        sid = str(server.id)
        label = f'"{server.name}" ({sid})'
        provider: ServerProvider | None = None
        handle: ServerHandle | None = None

        try:
            provider_type = server.runtime.provider if server.runtime else "local"
            provider = provider_factory.get(provider_type)

            if server.runtime and server.runtime.external_id:
                handle = ServerHandle(
                    provider=provider_type,
                    server_id=sid,
                    external_id=server.runtime.external_id,
                )

            status = ServerRuntimeStatus.STOPPED
            if handle:
                try:
                    status = await provider.status(handle)
                except Exception:
                    status = ServerRuntimeStatus.ERROR

            old_status = server.status.value

            if server.status == ServerStatus.STARTING:
                if status == ServerRuntimeStatus.RUNNING:
                    logger.info(
                        'Server %s was STARTING but found RUNNING — updating',
                        label,
                    )
                    server.mark_running(
                        pid=server.runtime.pid or 0,
                        port=server.runtime.port,
                        host=server.runtime.host,
                        external_id=server.runtime.external_id,
                    )
                    await repo.save(server)
                    results.append({
                        "server_id": sid,
                        "old_status": old_status,
                        "new_status": "running",
                        "action": "corrected",
                    })
                else:
                    logger.info(
                        'Server %s was STARTING but no runtime — marking CRASHED',
                        label,
                    )
                    server.crash(
                        exit_code=-1,
                        last_log_lines=[
                            "Backend restart: server was in STARTING state but no runtime found",
                        ],
                    )
                    await repo.save(server)
                    results.append({
                        "server_id": sid,
                        "old_status": old_status,
                        "new_status": "crashed",
                        "action": "repaired",
                        "reason": "stale STARTING state — no runtime process detected",
                    })

            elif server.status == ServerStatus.RUNNING:
                if status == ServerRuntimeStatus.RUNNING:
                    logger.info('Server %s confirmed RUNNING during reconciliation', label)
                    results.append({
                        "server_id": sid,
                        "old_status": old_status,
                        "new_status": "running",
                        "action": "confirmed",
                    })
                else:
                    logger.info(
                        'Server %s was RUNNING but no runtime — marking CRASHED',
                        label,
                    )
                    server.crash(
                        exit_code=-1,
                        last_log_lines=[
                            "Backend restart: server was in RUNNING state but no runtime found",
                        ],
                    )
                    await repo.save(server)
                    results.append({
                        "server_id": sid,
                        "old_status": old_status,
                        "new_status": "crashed",
                        "action": "repaired",
                        "reason": "stale RUNNING state — no runtime process detected",
                    })

            elif server.status == ServerStatus.STOPPING:
                logger.info(
                    'Server %s was STOPPING — marking STOPPED',
                    label,
                )
                server.mark_stopped()
                await repo.save(server)
                results.append({
                    "server_id": sid,
                    "old_status": old_status,
                    "new_status": "stopped",
                    "action": "repaired",
                    "reason": "stale STOPPING state — backend restarted",
                })

        except Exception:
            logger.exception("Reconciliation failed for server %s", label)
            results.append({
                "server_id": sid,
                "old_status": server.status.value if server.status else "unknown",
                "new_status": "error",
                "action": "failed",
                "reason": "reconciliation error",
            })

    logger.info(
        "Reconciliation complete: %d servers processed",
        len(results),
    )
    return results
