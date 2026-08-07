# Module Map

> Cross-references: [Architecture](../architecture/ARCHITECTURE.md), [Dependency Graph](dependency-graph.md), [File Ownership](file-ownership.md)

Every backend module mapped to its purpose, path, and the batch that built it. Directories verified against the current filesystem at `backend/app/`.

---

## Foundation Layer — Batch 01

| Module | Path | Type | Description |
|---|---|---|---|
| Core | `backend/app/core/` | Foundation | Config factory, exception hierarchy, CQRS buses, idempotency, saga base, circuit breaker, feature flags, logging, security utils |
| Persistence | `backend/app/core/persistence/` | Foundation | SQLAlchemy engine, base ORM model, `BaseRepository`, `UnitOfWork` |
| Migrations | `backend/alembic/` | Foundation | Database migration scripts, env config |

## Domain Layer — Batch 02

| Module | Path | Type | Description |
|---|---|---|---|
| Server Domain | `backend/app/modules/server/domain/` | Domain | `Server` aggregate root, value objects (`ServerId`, `MinecraftVersion`, etc.), domain events, repository interface, domain service, diagnostics types |
| Backup Domain | `backend/app/modules/backup/domain/` | Domain | `BackupJob`, `BackupPolicy` aggregates, domain events, repository interface |
| Plugin Domain | `backend/app/modules/plugin/domain/` | Domain | `Plugin`, `PluginRegistry` aggregates, value objects, domain events, repository interface |
| Auth Domain | `backend/app/modules/auth/domain/` | Domain | `User`, `Role` aggregates, auth domain events |
| Monitoring Domain | `backend/app/modules/monitoring/domain/` | Domain | `MetricSeries`, `AlertRule` aggregates, monitoring events |
| Shared Domain | `backend/app/modules/shared/` | Domain | Cross-context value objects, shared aggregate base |

## Infrastructure Layer — Batch 03

| Module | Path | Type | Description |
|---|---|---|---|
| Server Infra | `backend/app/modules/server/infrastructure/` | Infrastructure | SQLAlchemy repository, `ServerProvider` interface + local/docker/remote/cloud providers, filesystem helpers, location tracking, ORM models |
| Backup Infra | `backend/app/modules/backup/infrastructure/` | Infrastructure | SQLAlchemy repository, ORM models |
| Plugin Infra | `backend/app/modules/plugin/infrastructure/` | Infrastructure | SQLAlchemy repository, ORM models, manifest validation, dependency resolver, sandbox, lifecycle state machine |
| Storage Backend | `backend/app/modules/storage/` | Infrastructure | `StorageBackend` interface, local filesystem adapter, S3 adapter, encryption helpers |

## Application Layer — Batch 04

| Module | Path | Type | Description |
|---|---|---|---|
| Server App | `backend/app/modules/server/application/` | Application | Commands (create/delete/start/stop/restart/import/update), queries, read models, supervisor, reconciliation, service layer |
| Backup App | `backend/app/modules/backup/application/` | Application | Commands (create/restore/delete/verify), queries |
| Plugin App | `backend/app/modules/plugin/application/` | Application | Commands (install/uninstall/enable/disable), queries |
| Monitoring App | `backend/app/modules/monitoring/application/` | Application | Commands (create/update alert rules), queries |
| Orchestrators | `backend/app/services/` | Application | Saga orchestrators for server lifecycle, backup, deployment provider selection |

## Interface Layer — Batch 05

| Module | Path | Type | Description |
|---|---|---|---|
| API Layer | `backend/app/api/` | Interface | FastAPI app factory, dependency injection, global error handlers |
| API v1 Routers | `backend/app/api/v1/routers/` | Interface | REST endpoints for servers, backups, plugins, users, auth, monitoring, health, schedules, settings, software |
| API v1 Schemas | `backend/app/api/v1/schemas/` | Interface | Pydantic request/response schemas |
| API v1 Middleware | `backend/app/api/v1/middleware/` | Interface | Auth, audit, request ID, rate-limit middleware |

## WebSocket Layer — Batch 06

| Module | Path | Type | Description |
|---|---|---|---|
| WebSocket | `backend/app/websocket/` | Interface | Connection manager, auth, authorization, event dispatcher, message handlers, serialization, offline buffer, rate limiter |
| WS Client | `frontend/src/websocket/` | Interface | TypeScript WS client, auto-reconnect, channel subscription, message dispatch |

## Plugin System — Batch 07

| Module | Path | Type | Description |
|---|---|---|---|
| Plugin Runner | `backend/app/modules/plugin/infrastructure/runner/` | Infrastructure | `PluginRunner` interface, subprocess runner, container runner |
| Plugin SDK | `backend/plugins/sdk/` | Platform | `BasePlugin` class, event/command decorators, config access, sandboxed storage, scoped HTTP client |

## Auth System — Batch 08

| Module | Path | Type | Description |
|---|---|---|---|
| Auth Infra | `backend/app/modules/auth/infrastructure/` | Infrastructure | SQLAlchemy repository, JWT (RS256), Argon2id password hashing, RBAC+ABAC policy engine, audit log writer |
| Auth App | `backend/app/modules/auth/application/` | Application | Commands (login/logout/refresh/api-key), queries |

## Monitoring & Tasks — Batch 09

| Module | Path | Type | Description |
|---|---|---|---|
| Tasks | `backend/app/tasks/` | Infrastructure | APScheduler setup, base task, task queue (in-process + ARQ/Redis), task definitions (backup, health check, metrics, cleanup) |
| Monitoring Infra | `backend/app/modules/monitoring/infrastructure/` | Infrastructure | Metrics registry, server metrics collector, health check registry, ORM models |
| Event Store | `backend/app/modules/event_store/` | Infrastructure | Event repository, cryptographic chain verification, dead letter queue |

## Health & Integrity Engine — post-Batch 10

| Module | Path | Type | Description |
|---|---|---|---|
| Health Domain | `backend/app/modules/health/domain/` | Domain | `ServerHealth` aggregate, `FailureCode` enum, domain events, repository interface |
| Health App | `backend/app/modules/health/application/` | Application | Commands (evaluate health, crash recovery), queries (status, timeline, dashboard), event handlers |
| Health Infra | `backend/app/modules/health/infrastructure/` | Infrastructure | Health calculator, crash analyzer, evidence collector, environment fingerprinting, integrity validation, recovery orchestrator, ORM models |

## Frontend — Batch 10

| Module | Path | Type | Description |
|---|---|---|---|
| Frontend App | `frontend/src/` | Interface | React SPA (Vite + TypeScript), stores, components, pages, services, hooks |
| App Entry | `frontend/src/main.tsx`, `App.tsx` | Interface | Root component and entry point |
| Pages | `frontend/src/pages/` | Interface | Login, Register |
| Server Manager Pages | `frontend/src/server_manager/pages/` | Interface | Dashboard, Servers, Create Server, Import Server, Server Detail, Backup List, Plugin List, Settings, API Keys |
| Components | `frontend/src/components/` | Interface | Shared UI: `WebSocketManager`, `ErrorBoundary`, `EmptyState`, `Skeleton`, `AuthGuard`, `Sidebar`, `TopNav` |
| Server Manager Components | `frontend/src/server_manager/components/` | Interface | Server-specific: `ServerConsole`, `ServerConfigEditor`, `ServerMetricsCharts`, `CreateBackupDialog`, `InstallPluginDialog`, `Sparkline` |

---

## Batch Allocation Summary

| Batch | Layer | Modules |
|---|---|---|
| 01 | Foundation | core, persistence, alembic |
| 02 | Domain | server/domain, backup/domain, plugin/domain, auth/domain, monitoring/domain, shared |
| 03 | Infrastructure | server/infrastructure, backup/infrastructure, plugin/infrastructure (repos), modules/storage |
| 04 | Application | server/application, backup/application, plugin/application, monitoring/application, services |
| 05 | Interface | api, main.py, openapi.yaml |
| 06 | Interface | websocket (backend + frontend/src/websocket) |
| 07 | Platform | plugin/infrastructure/runner, plugins/sdk |
| 08 | Infrastructure + App | auth/infrastructure, auth/application |
| 09 | Infrastructure | tasks, monitoring/infrastructure, event_store |
| 10 | Interface | frontend/src |
| health | Domain + App + Infra | health/domain, health/application, health/infrastructure |

---

See also: [Contract Registry](contract-registry.md) for shared interfaces between modules, [Event Catalog](event-catalog.md) for domain events.
