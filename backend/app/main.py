import logging
import sys
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.deps import init_buses, init_storage
from app.api.errors import register_error_handlers
from app.api.v1.middleware.audit import AuditMiddleware
from app.api.v1.middleware.auth import AuthMiddleware
from app.api.v1.middleware.rate_limit import RateLimitMiddleware
from app.api.v1.middleware.request_id import RequestIDMiddleware
from app.api.v1.routers import (
    auth,
    backups,
    exposure,
    files,
    health,
    invites,
    marketplace,
    monitoring,
    plugins,
    schedules,
    servers,
    settings,
    setup,
    software,
    users,
)
from app.core.command_bus import CommandBus
from app.core.config import ConfigFactory, init_active_panel_bind
from app.core.event_bus import EventBus
from app.core.http_client import close_http_client, init_http_client
from app.core.identity import IDENTITY
from app.core.persistence.db import database
from app.core.persistence.db_revision import check_database_compatibility
from app.core.platform_lock import set_cloexec_on_all_fds
from app.core.query_bus import QueryBus
from app.core.settings_store import get_live_settings, init_settings_store
from app.core.version import get_app_version
from app.modules.auth.infrastructure.jwt import init_jwt_from_settings
from app.modules.plugin.infrastructure.providers import validate_plugin_providers
from app.modules.server.application.migrate_import_arch import migrate_old_import_arch
from app.modules.server.application.reconciliation import reconcile_servers
from app.modules.server.application.runtime_reconciliation import (
    reconcile_all_runtimes,
    reconcile_orphans,
)
from app.modules.server.application.services.filesystem_reconciliation import (
    FilesystemReconciliationService,
)
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.registration import register_handlers
from app.websocket.endpoint import init_websocket, start_websocket_services, stop_websocket_services
from app.websocket.endpoint import router as ws_router

set_cloexec_on_all_fds()

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.main")

_start_time: float = 0.0


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _start_time
    _start_time = time.time()
    set_cloexec_on_all_fds()
    settings = ConfigFactory.global_settings()
    init_settings_store()
    init_active_panel_bind()
    database.init(settings)
    db_status = await check_database_compatibility()
    if not db_status.ok:
        raise RuntimeError(db_status.message)
    init_jwt_from_settings(settings)
    command_bus = CommandBus()
    query_bus = QueryBus()
    event_bus = EventBus()
    register_handlers(command_bus, query_bus, event_bus)
    init_buses(command_bus, query_bus, event_bus)
    init_storage(settings)
    validate_plugin_providers(settings.plugin_providers)
    init_http_client()
    init_websocket(event_bus)
    await start_websocket_services()

    async with database.session_factory() as session:
        if sys.platform == "win32":
            try:
                from sqlalchemy import select

                from app.modules.server.domain.value_objects import default_provider_for_platform
                from app.modules.server.infrastructure.models import ServerModel

                target_provider = default_provider_for_platform()
                stmt = select(ServerModel).where(ServerModel.provider == "local")
                result = await session.execute(stmt)
                servers_to_migrate = result.scalars().all()

                if servers_to_migrate:
                    for s in servers_to_migrate:
                        s.provider = target_provider
                    await session.commit()
                    logger.info(
                        "Migrated %d server(s) from provider='local' to '%s' for Windows host",
                        len(servers_to_migrate),
                        target_provider,
                    )
            except Exception as exc:
                logger.warning("Windows provider migration failed: %s", exc)

        repo = SQLServerRepository(session)
        try:
            results = await reconcile_servers(repo)
            if results:
                logger.info("Startup DB reconciliation results: %s", results)
        except Exception:
            logger.exception("Startup DB reconciliation failed")

        try:
            runtime_results = await reconcile_all_runtimes(repo)
            repaired = [r for r in runtime_results if r.repaired]
            if repaired:
                for r in repaired:
                    logger.info(
                        'Runtime reconciled server="%s" (%s): %s',
                        r.server_name,
                        r.server_id,
                        "; ".join(r.actions),
                    )
        except Exception:
            logger.exception("Startup runtime reconciliation failed")

        try:
            orphan_results = await reconcile_orphans(repo, scope="project_owned")
            if orphan_results:
                logger.info("Cleaned up %d orphan runtime artifacts", len(orphan_results))
        except Exception:
            logger.exception("Startup orphan cleanup failed")

        try:
            from app.modules.server.application.runtime_ownership import RuntimeOwnershipManager

            ownership_mgr = RuntimeOwnershipManager(repo)
            snapshot = await ownership_mgr.discover_all()
            if snapshot.total_orphans > 0 or snapshot.conflicts:
                logger.info(
                    "Startup ownership check: %d active servers, %d orphans, %d conflicts",
                    len(snapshot.active_servers),
                    snapshot.total_orphans,
                    len(snapshot.conflicts),
                )
                if snapshot.orphan_tmux:
                    logger.warning(
                        "Orphan tmux sessions on startup: %s",
                        [r.identifier for r in snapshot.orphan_tmux],
                    )
                if snapshot.orphan_processes:
                    logger.warning(
                        "Orphan Minecraft processes on startup: %s",
                        [r.identifier for r in snapshot.orphan_processes],
                    )
                if snapshot.conflicts:
                    for c in snapshot.conflicts:
                        logger.warning("Ownership conflict: %s — %s", c.reason.value, c.detail)
        except Exception:
            logger.exception("Startup ownership discovery failed")

        try:
            migrated = await migrate_old_import_arch(repo)
            if migrated:
                logger.info("Migrated %d old-arch servers", migrated)
        except Exception:
            logger.exception("Import architecture migration failed")

        try:
            from app.modules.exposure.application.commands import (
                _panel_encryption,
                _persist_playit_status,
                _reconcile_playit_tunnels,
            )
            from app.modules.exposure.infrastructure.playit_agent import get_playit_supervisor
            from app.modules.exposure.infrastructure.repository import SQLHostAgentRepository

            supervisor = get_playit_supervisor()
            reconciled_playit = await supervisor.reconcile_startup()
            if reconciled_playit:
                logger.info("Playit supervisor successfully re-attached to running daemon")
            else:
                agent_repo = SQLHostAgentRepository(session)
                agent = await agent_repo.get()
                if agent.is_claimed and agent.desired_agent_running and agent.secret_ciphertext:
                    try:
                        secret_bytes = _panel_encryption().decrypt(agent.secret_ciphertext)
                        await supervisor.start(
                            secret=secret_bytes,
                            on_status=_persist_playit_status,
                            on_reconcile=_reconcile_playit_tunnels,
                        )
                        logger.info("Playit supervisor successfully spawned daemon on startup")
                    except Exception as e:
                        logger.warning("Failed to spawn playit daemon on startup: %s", e)
        except Exception:
            logger.exception("Playit startup reconciliation failed")

        try:
            service = FilesystemReconciliationService(repo)
            fs_result = await service.reconcile()
            await session.commit()
            if fs_result.imported:
                logger.info("FS reconciliation imported %d server(s)", fs_result.total_imported)
            if fs_result.updated:
                logger.info("FS reconciliation updated %d server(s)", fs_result.total_updated)
            if fs_result.deleted:
                logger.info("FS reconciliation deleted %d stale record(s)", fs_result.total_deleted)
            if fs_result.missing:
                logger.warning(
                    "FS reconciliation marked %d server(s) as MISSING", fs_result.total_missing
                )
            if fs_result.broken:
                logger.warning(
                    "FS reconciliation found %d broken server(s)", fs_result.total_broken
                )
            if fs_result.ignored:
                logger.info(
                    "FS reconciliation ignored %d non-Minecraft directory(ies)",
                    fs_result.total_ignored,
                )
            if fs_result.invalid_identity:
                logger.warning(
                    "FS reconciliation found %d invalid identity file(s)",
                    fs_result.total_invalid_identity,
                )
            if fs_result.errors:
                logger.warning("FS reconciliation encountered %d error(s)", fs_result.total_errors)
        except Exception:
            logger.exception("Filesystem reconciliation failed")

    # ── Task Queue & Scheduler (wired up once, during startup) ──────────
    logger.info("Starting task queue and scheduler")
    from app.modules.monitoring.infrastructure.collector import MetricsCollector
    from app.tasks.definitions import (
        init_collector as init_metrics_collector,
    )
    from app.tasks.definitions import (
        run_backup_task,
        run_metrics_collection_task,
    )
    from app.tasks.queue import InProcessQueue, init_task_queue
    from app.tasks.scheduler import Scheduler

    async def _session_factory():
        return database.session_factory()

    # InProcessQueue — runs handler functions in-process when a task fires
    task_queue = InProcessQueue(_session_factory)
    task_queue.register("run_metrics_collection", run_metrics_collection_task)
    task_queue.register("run_backup_task", run_backup_task)
    init_task_queue(task_queue)

    # Reclaim PENDING tasks orphaned by a previous process restart, and fail
    # RUNNING rows that are stale (started before this boot or without started_at).
    try:
        reclaim_result = await task_queue.reclaim_pending()
        if reclaim_result["reclaimed"] or reclaim_result["skipped_unregistered"]:
            logger.info("Task queue reclaim: %s", reclaim_result)
        stale = await task_queue.mark_stale_running_failed()
        if stale:
            logger.warning("Task queue: marked %d stale RUNNING task(s) as FAILED", stale)
    except Exception:
        logger.exception("Task queue reclaim failed")

    # MetricsCollector — collects real-time data from running servers
    from app.modules.monitoring.infrastructure.metrics import (
        get_prometheus_metrics_registry,
    )

    metrics_collector = MetricsCollector(event_bus=event_bus)
    init_metrics_collector(metrics_collector, prometheus=get_prometheus_metrics_registry())

    # Scheduler — loads cron_jobs from DB and fires them on schedule
    from app.tasks.scheduler import init_global_scheduler

    scheduler = Scheduler(_session_factory)
    scheduler.set_task_queue(task_queue)
    init_global_scheduler(scheduler)
    await scheduler.start()

    # Register/ensure the metrics collection job using configured interval
    live_settings = get_live_settings()
    current_interval = live_settings.metrics_interval_seconds
    cron_expr = f"interval:{current_interval}s"

    try:
        async with await _session_factory() as sess:
            from sqlalchemy import select

            from app.tasks.scheduler import CronJobModel

            # Look for existing metrics collection job under any known name
            existing = await sess.execute(
                select(CronJobModel).where(
                    CronJobModel.name.in_(
                        (
                            "metrics_collect",
                            "metrics_collect_every_0.2s",
                            "metrics_collect_every_0.5s",
                            "metrics_collect_every_1s",
                        )
                    )
                )
            )
            existing_jobs = list(existing.scalars().all())
            if not existing_jobs:
                await scheduler.add_job(
                    name="metrics_collect",
                    cron_expression=cron_expr,
                    task_name="run_metrics_collection",
                    params={},
                )
                logger.info("Scheduler: metrics_collect registered (%s)", cron_expr)
            else:
                primary = existing_jobs[0]
                if primary.cron_expression != cron_expr or primary.name != "metrics_collect":
                    primary.name = "metrics_collect"
                    primary.cron_expression = cron_expr
                    await sess.commit()
                    scheduler._schedule_job(primary)
                    logger.info("Scheduler: metrics_collect updated to %s", cron_expr)
                for extra in existing_jobs[1:]:
                    await scheduler.remove_job(extra.id)
    except Exception:
        logger.exception("Failed to register metrics collection cron job")

    # Log the cron jobs now loaded from DB (including integrity_scan_hourly)
    async with await _session_factory() as sess:
        from sqlalchemy import select

        from app.tasks.scheduler import CronJobModel

        result = await sess.execute(select(CronJobModel).where(CronJobModel.enabled == 1))
        jobs = result.scalars().all()
        logger.info("Scheduler loaded %d cron job(s)", len(jobs))
        for j in jobs:
            logger.info("  cron job: %s (%s)", j.name, j.cron_expression)
    yield

    # ── Shutdown ────────────────────────────────────────────────────────
    try:
        from app.modules.exposure.infrastructure.playit_agent import get_playit_supervisor

        await get_playit_supervisor().stop()
    except Exception:
        logger.warning("Error stopping playit supervisor on shutdown", exc_info=True)

    try:
        from app.modules.exposure.infrastructure.cloudflared import (
            _server_supervisors,
            get_cloudflared_supervisor,
        )

        await get_cloudflared_supervisor().stop()
        for _sid, s_sup in list(_server_supervisors.items()):
            await s_sup.stop()
    except Exception:
        logger.warning("Error stopping cloudflared supervisor on shutdown", exc_info=True)

    await stop_websocket_services()
    await scheduler.stop()
    await metrics_collector.close()
    await close_http_client()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Minecraft Server Manager",
        version=get_app_version(),
        description="REST API for managing Minecraft server instances",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        license_info={
            "name": "MIT",
        },
    )

    app.add_middleware(AuditMiddleware)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)

    app.include_router(servers.router)
    app.include_router(exposure.router)
    app.include_router(backups.router)
    app.include_router(plugins.router)
    app.include_router(files.router)
    app.include_router(marketplace.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(setup.router)
    app.include_router(invites.router)
    app.include_router(monitoring.router)
    app.include_router(health.router)
    app.include_router(schedules.router)
    app.include_router(settings.router)
    app.include_router(software.router)
    app.include_router(ws_router)

    from app.modules.auth.infrastructure.jwt import get_jwks

    @app.get("/.well-known/jwks.json")
    async def jwks_endpoint():
        return get_jwks()

    @app.get("/health")
    async def health_check():
        db_status = "connected"
        try:
            _ = database.engine
        except RuntimeError:
            db_status = "disconnected"
        return {
            "status": "ok",
            "version": get_app_version(),
            "database": db_status,
            "uptime_seconds": time.time() - _start_time if _start_time else 0,
        }

    @app.get("/metrics")
    async def prometheus_metrics():
        try:
            from prometheus_client import REGISTRY, generate_latest
            from starlette.responses import Response

            return Response(
                content=generate_latest(REGISTRY),
                media_type="text/plain; charset=utf-8",
            )
        except ImportError:
            return JSONResponse(
                content={"message": "Prometheus client not installed"},
                status_code=501,
            )

    return app


app = create_app()
