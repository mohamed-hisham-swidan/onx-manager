from __future__ import annotations

import logging
import os

from app.core.identity import IDENTITY
from app.modules.server.application.services.jar_service import server_dir_name
from app.modules.server.domain.aggregate import Server, ServerStatus
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.domain.value_objects import (
    build_server_handle,
    default_provider_for_platform,
)
from app.modules.server.infrastructure.fs import local_fs
from app.modules.server.infrastructure.providers import provider_factory
from app.modules.server.infrastructure.providers.base import (
    ServerHandle,
    ServerProvider,
    ServerRuntimeStatus,
)
from app.modules.shared.value_objects import ServerId

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.reconciliation")


def _servers_data_dir() -> str:
    from app.core.config import AppSettings

    return AppSettings().servers_data_dir


SERVERS_DATA_DIR = _servers_data_dir()


async def reconcile_filesystem(repo: ServerRepository) -> list[dict]:
    results: list[dict] = []
    data_dir = os.path.abspath(SERVERS_DATA_DIR)

    if not os.path.isdir(data_dir):
        logger.info(
            "Servers data directory %s does not exist — skipping fs reconciliation", data_dir
        )
        return results

    try:
        all_servers = await repo.list()
    except Exception:
        logger.exception("Failed to list servers for filesystem reconciliation")
        return results

    known_dirs: set[str] = set()
    for s in all_servers:
        sid = str(s.id)
        known_dirs.add(sid)
        known_dirs.add(server_dir_name(s.name, sid))

    orphan_count = 0
    for entry in os.listdir(data_dir):
        entry_path = os.path.join(data_dir, entry)
        if not os.path.isdir(entry_path):
            continue
        if entry in known_dirs:
            continue
        orphan_count += 1
        logger.warning("Orphan directory detected: %s (no matching DB record)", entry_path)
        results.append(
            {
                "path": entry_path,
                "server_id": entry,
                "action": "pending",
            }
        )

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
    ServerStatus.PROVISIONING,
    ServerStatus.STARTING,
    ServerStatus.RUNNING,
    ServerStatus.STOPPING,
    ServerStatus.CRASHED,
}


async def reconcile_servers(repo: ServerRepository) -> list[dict]:
    results: list[dict] = []
    reconciled_running = 0

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
            provider_type = (
                server.runtime.provider
                if (server.runtime and server.runtime.provider)
                else default_provider_for_platform()
            )
            provider = provider_factory.get(provider_type)

            server_dir = (
                server.deployment.server_directory() if server.deployment is not None else None
            )
            handle = build_server_handle(server, provider_type, server_dir=server_dir)

            status = ServerRuntimeStatus.STOPPED
            if handle:
                try:
                    status = await provider.status(handle)
                except Exception:
                    status = ServerRuntimeStatus.ERROR

            old_status = server.status.value

            if server.status == ServerStatus.PROVISIONING:
                logger.info(
                    "Server %s was PROVISIONING — marking BROKEN (incomplete install)",
                    label,
                )
                provisioning_dir = (
                    server.deployment.server_directory() if server.deployment is not None else None
                )
                if provisioning_dir:
                    try:
                        local_fs.delete_dir(provisioning_dir)
                    except Exception:
                        logger.exception(
                            "Failed to clean up in-progress install directory %s",
                            provisioning_dir,
                        )
                server.fail_provisioning(
                    error="stale PROVISIONING state — backend restarted mid-install",
                    fatal=True,
                )
                await repo.save(server)
                results.append(
                    {
                        "server_id": sid,
                        "old_status": old_status,
                        "new_status": "broken",
                        "action": "repaired",
                        "reason": "stale PROVISIONING state — backend restarted mid-install",
                    }
                )

            elif server.status == ServerStatus.STARTING:
                if status == ServerRuntimeStatus.RUNNING:
                    logger.info(
                        "Server %s was STARTING but found RUNNING — updating",
                        label,
                    )
                    server.mark_running(
                        pid=server.runtime.pid or 0,
                        port=server.runtime.port,
                        host=server.runtime.host,
                        external_id=server.runtime.external_id,
                    )
                    await repo.save(server)
                    results.append(
                        {
                            "server_id": sid,
                            "old_status": old_status,
                            "new_status": "running",
                            "action": "corrected",
                        }
                    )
                else:
                    logger.info(
                        "Server %s was STARTING but no runtime — marking CRASHED",
                        label,
                    )
                    server.crash(
                        exit_code=-1,
                        last_log_lines=[
                            "Backend restart: server was in STARTING state but no runtime found",
                        ],
                    )
                    await repo.save(server)
                    results.append(
                        {
                            "server_id": sid,
                            "old_status": old_status,
                            "new_status": "crashed",
                            "action": "repaired",
                            "reason": "stale STARTING state — no runtime process detected",
                        }
                    )

            elif server.status == ServerStatus.RUNNING:
                if status == ServerRuntimeStatus.RUNNING:
                    logger.info("Server %s confirmed RUNNING during reconciliation", label)
                    results.append(
                        {
                            "server_id": sid,
                            "old_status": old_status,
                            "new_status": "running",
                            "action": "confirmed",
                        }
                    )
                else:
                    logger.info(
                        "Server %s was RUNNING but no runtime — marking CRASHED",
                        label,
                    )
                    server.crash(
                        exit_code=-1,
                        last_log_lines=[
                            "Backend restart: server was in RUNNING state but no runtime found",
                        ],
                    )
                    await repo.save(server)
                    results.append(
                        {
                            "server_id": sid,
                            "old_status": old_status,
                            "new_status": "crashed",
                            "action": "repaired",
                            "reason": "stale RUNNING state — no runtime process detected",
                        }
                    )

            elif server.status == ServerStatus.CRASHED:
                if status == ServerRuntimeStatus.RUNNING:
                    logger.info(
                        "Server %s was CRASHED in DB but runtime is RUNNING"
                        " — recovering to RUNNING",
                        label,
                    )
                    server.mark_running(
                        pid=server.runtime.pid or 0,
                        port=server.runtime.port,
                        host=server.runtime.host,
                        external_id=server.runtime.external_id,
                    )
                    await repo.save(server)
                    results.append(
                        {
                            "server_id": sid,
                            "old_status": old_status,
                            "new_status": "running",
                            "action": "recovered",
                        }
                    )

            elif server.status == ServerStatus.STOPPING:
                has_handle = bool(server.runtime and server.runtime.external_id)
                if status == ServerRuntimeStatus.STOPPED and has_handle:
                    logger.info(
                        "Server %s was STOPPING and confirmed STOPPED by provider"
                        " — marking STOPPED",
                        label,
                    )
                    server.mark_stopped()
                    await repo.save(server)
                    results.append(
                        {
                            "server_id": sid,
                            "old_status": old_status,
                            "new_status": "stopped",
                            "action": "repaired",
                            "reason": "confirmed stopped by provider",
                        }
                    )
                elif status == ServerRuntimeStatus.RUNNING:
                    logger.info(
                        "Server %s was STOPPING but provider reports RUNNING"
                        " — reverting to RUNNING",
                        label,
                    )
                    server.revert_to_running()
                    await repo.save(server)
                    from app.core.settings_store import get_live_settings
                    from app.modules.server.application.supervisor import RuntimeSupervisor

                    active_sup = RuntimeSupervisor.get_for(sid)
                    if not active_sup or not active_sup.is_running:
                        try:
                            handle = build_server_handle(
                                server, provider_type, server_dir=server_dir
                            )
                            startup_timeout = float(
                                server.startup_timeout_seconds
                                or get_live_settings().server_startup_timeout_seconds
                            )
                            RuntimeSupervisor.start_for(
                                server=server,
                                provider=provider,
                                handle=handle,
                                repo_get=lambda s_id: sql_get_server(s_id),
                                repo_save=lambda s: sql_save_server(s),
                                startup_timeout=startup_timeout,
                            )
                        except Exception as exc:
                            logger.warning(
                                "Failed to attach supervisor for %s in reconciliation: %s",
                                sid,
                                exc,
                            )
                    reconciled_running += 1
                    results.append(
                        {
                            "server_id": sid,
                            "old_status": old_status,
                            "new_status": "running",
                            "action": "reverted",
                            "reason": "runtime still running after unconfirmed stop",
                        }
                    )
                else:
                    logger.warning(
                        "Server %s is STOPPING with unconfirmed runtime status %s"
                        " (has_handle=%s) — leaving STOPPING",
                        label,
                        status.value if hasattr(status, "value") else status,
                        has_handle,
                    )
                    results.append(
                        {
                            "server_id": sid,
                            "old_status": old_status,
                            "new_status": "stopping",
                            "action": "skipped",
                            "reason": f"unconfirmed runtime status: {status}",
                        }
                    )

        except Exception:
            logger.exception("Reconciliation failed for server %s", label)
            results.append(
                {
                    "server_id": sid,
                    "old_status": server.status.value if server.status else "unknown",
                    "new_status": "error",
                    "action": "failed",
                    "reason": "reconciliation error",
                }
            )

    logger.info(
        "Reconciliation complete: %d servers processed",
        len(results),
    )
    return results


async def sql_get_server(sid: ServerId) -> Server:
    from app.core.persistence.db import database
    from app.modules.server.infrastructure.repository import SQLServerRepository

    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        return await repo.get(sid)


async def sql_save_server(server: Server) -> None:
    from app.core.persistence.db import database
    from app.modules.server.infrastructure.repository import SQLServerRepository

    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        await repo.save(server)
        await session.commit()

