import logging
import time
from contextlib import asynccontextmanager

logger = logging.getLogger("mcs.main")

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.deps import init_buses
from app.api.errors import register_error_handlers
from app.api.v1.middleware.audit import AuditMiddleware
from app.api.v1.middleware.auth import AuthMiddleware
from app.api.v1.middleware.rate_limit import RateLimitMiddleware
from app.api.v1.middleware.request_id import RequestIDMiddleware
from app.api.v1.routers import auth, backups, health, monitoring, plugins, schedules, servers, settings, software, users
from app.core.command_bus import CommandBus
from app.core.config import AppSettings, ConfigFactory
from app.core.event_bus import EventBus
from app.core.query_bus import QueryBus
from app.modules.auth.infrastructure.jwt import init_jwt_from_settings
from app.registration import register_handlers
from app.modules.server.application.reconciliation import reconcile_servers
from app.modules.server.application.runtime_reconciliation import (
    reconcile_all_runtimes,
    reconcile_orphans,
)
from app.modules.server.application.services.filesystem_reconciliation import reconcile as fs_reconcile
from app.modules.server.application.migrate_import_arch import migrate_old_import_arch
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.core.persistence.db import database
from app.websocket.endpoint import init_websocket, router as ws_router

_start_time: float = 0.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _start_time
    _start_time = time.time()
    settings = ConfigFactory.global_settings()
    database.init(settings)
    init_jwt_from_settings(settings)
    command_bus = CommandBus()
    query_bus = QueryBus()
    event_bus = EventBus()
    register_handlers(command_bus, query_bus, event_bus)
    init_buses(command_bus, query_bus, event_bus)
    init_websocket(event_bus)

    async with database.session_factory() as session:
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
                        r.server_name, r.server_id, "; ".join(r.actions),
                    )
        except Exception:
            logger.exception("Startup runtime reconciliation failed")

        try:
            orphan_results = await reconcile_orphans(repo)
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
                    len(snapshot.active_servers), snapshot.total_orphans, len(snapshot.conflicts),
                )
                if snapshot.orphan_tmux:
                    logger.warning("Orphan tmux sessions on startup: %s",
                                   [r.identifier for r in snapshot.orphan_tmux])
                if snapshot.orphan_processes:
                    logger.warning("Orphan Minecraft processes on startup: %s",
                                   [r.identifier for r in snapshot.orphan_processes])
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
            fs_result = await fs_reconcile(repo)
            await session.commit()
            if fs_result.imported:
                logger.info("FS reconciliation imported %d server(s)", len(fs_result.imported))
            if fs_result.updated:
                logger.info("FS reconciliation updated %d server(s)", len(fs_result.updated))
            if fs_result.deleted:
                logger.info("FS reconciliation deleted %d stale record(s)", len(fs_result.deleted))
            if fs_result.missing:
                logger.warning("FS reconciliation marked %d server(s) as MISSING", len(fs_result.missing))
            if fs_result.broken:
                logger.warning("FS reconciliation found %d broken server(s)", len(fs_result.broken))
            if fs_result.ignored:
                logger.info("FS reconciliation ignored %d non-Minecraft directory(ies)", len(fs_result.ignored))
            if fs_result.errors:
                logger.warning("FS reconciliation encountered %d error(s)", len(fs_result.errors))
        except Exception:
            logger.exception("Filesystem reconciliation failed")

    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Minecraft Server Manager",
        version="4.0.0",
        description="REST API for managing Minecraft server instances",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        license_info={
            "name": "MIT",
        },
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(AuditMiddleware)
    app.add_middleware(RateLimitMiddleware)

    register_error_handlers(app)

    app.include_router(servers.router)
    app.include_router(backups.router)
    app.include_router(plugins.router)
    app.include_router(auth.router)
    app.include_router(users.router)
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
            database.engine
        except RuntimeError:
            db_status = "disconnected"
        return {
            "status": "ok",
            "version": "4.0.0",
            "database": db_status,
            "uptime_seconds": time.time() - _start_time if _start_time else 0,
        }

    @app.get("/metrics")
    async def prometheus_metrics():
        try:
            from prometheus_client import generate_latest, REGISTRY
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
