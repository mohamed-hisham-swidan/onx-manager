import datetime
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.encoders import ENCODERS_BY_TYPE
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.deps import init_buses, init_storage
from app.api.errors import register_error_handlers
from app.api.v1.middleware.audit import AuditMiddleware
from app.api.v1.middleware.auth import AuthMiddleware
from app.api.v1.middleware.rate_limit import RateLimitMiddleware
from app.api.v1.middleware.request_id import RequestIDMiddleware
from app.api.v1.middleware.spa_static import SpaStaticMiddleware
from app.api.v1.routers import (
    activity,
    auth,
    backups,
    conversion,
    exposure,
    files,
    health,
    invites,
    marketplace,
    modpacks_upgrades,
    monitoring,
    operations,
    plugins,
    schedules,
    servers,
    settings,
    setup,
    software,
    users,
    versioning,
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
from app.core.timeutil import format_datetime_utc
from app.core.version import get_app_version
from app.modules.auth.infrastructure.jwt import init_jwt_from_settings
from app.modules.plugin.infrastructure.providers import validate_plugin_providers
from app.modules.server.application.migrate_import_arch import migrate_old_import_arch
from app.modules.server.application.reconciliation import reconcile_servers
from app.modules.server.application.runtime_reconciliation import (
    reconcile_all_runtimes,
    reconcile_orphans,
)
from app.modules.server.application.services.docker_migration import (
    migrate_all_local_servers_to_docker,
)
from app.modules.server.application.services.filesystem_reconciliation import (
    FilesystemReconciliationService,
)
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.registration import register_handlers
from app.websocket.endpoint import init_websocket, start_websocket_services, stop_websocket_services
from app.websocket.endpoint import router as ws_router

set_cloexec_on_all_fds()

ENCODERS_BY_TYPE[datetime.datetime] = format_datetime_utc

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
    from app.modules.versioning.infrastructure.vault_crypto import ensure_master_kek_file

    ensure_master_kek_file(settings)
    validate_plugin_providers(settings.plugin_providers)
    init_http_client()
    init_websocket(event_bus)
    await start_websocket_services()

    async with database.session_factory() as session:
        try:
            from app.core.local_auth import ensure_local_admin_provisioned

            if await ensure_local_admin_provisioned(session, settings):
                await session.commit()
                logger.info("Local zero-login admin account provisioned for loopback local mode")
        except Exception:
            logger.exception("Local zero-login startup provisioning failed")

        try:
            migration_report = await migrate_all_local_servers_to_docker(session)
            if migration_report.migrated_count:
                logger.info(
                    "Migrated %d local server(s) to Docker on startup",
                    migration_report.migrated_count,
                )
            for record in migration_report.migrated:
                for warning in record.warnings:
                    logger.warning(
                        "Local-to-Docker migration warning for %s: %s",
                        record.server_id,
                        warning,
                    )
            if migration_report.errors:
                logger.warning(
                    "Local-to-Docker migration errors: %s",
                    migration_report.errors,
                )
        except Exception:
            logger.exception("Local-to-Docker migration failed")

        try:
            from app.core.host_state import ensure_host_state_layout
            from app.modules.versioning.application.refresh_recovery import (
                RefreshStartupReconciler,
            )
            from app.modules.versioning.infrastructure.refresh_journal import (
                RefreshJournalRepository,
            )

            layout = ensure_host_state_layout(settings)
            journal_repository = RefreshJournalRepository(
                layout, session_factory=database.session_factory
            )
            recovery = await RefreshStartupReconciler(
                layout,
                repository=journal_repository,
                servers_data_dir=settings.servers_data_dir,
            ).reconcile()
            if recovery.changed:
                logger.info(
                    "Refresh startup recovery: %d swap(s), %d journal(s), "
                    "%d staging dir(s), %d previous tree(s)",
                    len(recovery.recovered_swaps),
                    len(recovery.transitioned_journals),
                    len(recovery.removed_staging),
                    len(recovery.pruned_previous_trees),
                )
            if recovery.errors:
                logger.warning("Refresh startup recovery errors: %s", recovery.errors)
        except Exception:
            logger.exception("Refresh startup recovery failed")

        try:
            from app.core.host_state import ensure_host_state_layout
            from app.modules.versioning.infrastructure.data_templates import (
                reconcile_data_templates_and_save_off_async,
            )

            layout = ensure_host_state_layout(settings)
            await reconcile_data_templates_and_save_off_async(
                layout, db_session=session
            )
        except Exception:
            logger.exception("Data template startup reconciliation failed")

        repo = SQLServerRepository(session)
        try:
            from app.modules.server.application.services.import_service import (
                cleanup_old_staging_directories,
            )

            cleaned_staging = cleanup_old_staging_directories()
            if cleaned_staging:
                logger.info(
                    "Cleaned %d stale staging directory(ies) on startup",
                    cleaned_staging,
                )
        except Exception as exc:
            logger.warning("Startup staging directory cleanup failed: %s", exc)

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
            if fs_result.identity_healed:
                logger.info(
                    "FS reconciliation healed %d server identity file(s)", fs_result.total_healed
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

    # Reconcile operations interrupted by previous process termination
    try:
        from app.modules.operations.application import OperationRecoveryReconciler

        op_reconciler = OperationRecoveryReconciler(event_bus=event_bus)
        await op_reconciler.reconcile_on_startup()
    except Exception:
        logger.exception("Operation startup reconciliation failed")

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
        from app.modules.operations.application import get_operation_service

        await get_operation_service().executor.shutdown(grace_seconds=10.0)
    except Exception:
        logger.warning("Error shutting down operation executor", exc_info=True)

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


def create_app(static_dir: str | Path | None = None) -> FastAPI:
    app = FastAPI(
        title="ONX Manager",
        version=get_app_version(),
        description="REST API for managing Minecraft server instances",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        license_info={
            "name": "Apache-2.0",
        },
    )

    app.add_middleware(AuditMiddleware)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestIDMiddleware)
    # Origins come from settings (cors_origins). Authentication is Bearer-token
    # based (no cookies), so credentialed CORS is only enabled for an explicit
    # origin allowlist; a wildcard origin must never be combined with
    # allow_credentials=True (Starlette would reflect any Origin with credentials).
    cors_origins = ConfigFactory.global_settings().cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials="*" not in cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)

    app.include_router(servers.router)
    app.include_router(exposure.router)
    app.include_router(backups.router)
    app.include_router(conversion.router)
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
    app.include_router(versioning.router)
    app.include_router(versioning.github_webhook_router)
    app.include_router(modpacks_upgrades.server_p55_router)
    app.include_router(modpacks_upgrades.lec_router)
    app.include_router(activity.router)
    app.include_router(operations.router)
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
        docker_available = False
        try:
            from app.modules.server.infrastructure.providers import provider_factory

            docker_available = await provider_factory.get("docker").ping()
        except Exception:
            pass
        return {
            "status": "ok",
            "version": get_app_version(),
            "deployment_profile": ConfigFactory.global_settings().deployment_profile,
            "database": db_status,
            "uptime_seconds": time.time() - _start_time if _start_time else 0,
            "docker": docker_available,
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

    app.add_middleware(SpaStaticMiddleware, static_dir=static_dir)

    return app


app = create_app()
