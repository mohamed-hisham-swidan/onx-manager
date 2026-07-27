# MCS Manager — Project Status

**Project:** Minecraft Server Manager v4.0  
**Code Name:** MCS Manager  
**Version:** 7.1.0  
**License:** MIT  
**Repository:** `server_manger/`

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Repository Structure](#repository-structure)
3. [Architecture](#architecture)
4. [Backend Specs](#backend-specs)
5. [Frontend Specs](#frontend-specs)
6. [API Reference](#api-reference)
7. [Database Schema](#database-schema)
8. [Domain Model](#domain-model)
9. [Server Lifecycle](#server-lifecycle)
10. [Provider System](#provider-system)
11. [Runtime System](#runtime-system)
12. [Plugin System](#plugin-system)
13. [Auth & Security](#auth--security)
14. [WebSocket Protocol](#websocket-protocol)
15. [Task Queue & Scheduling](#task-queue--scheduling)
16. [Monitoring & Metrics](#monitoring--metrics)
17. [Backup & Restore](#backup--restore)
18. [Storage Layer](#storage-layer)
19. [Event System](#event-system)
20. [Tests & Coverage](#tests--coverage)
21. [Deployment](#deployment)
22. [Project Status](#project-status)

---

## Project Overview

MCS Manager is a production-grade Minecraft server management platform. It provides a complete web UI and REST API to create, configure, start, stop, back up, and monitor Minecraft Java Edition servers. Servers can run on the local machine, inside Docker containers, on remote machines via SSH, or on cloud providers.

### Core Tenets

- Never lose a world (backup verification, audit trail)
- Zero surprise restarts (predictable lifecycle, graceful shutdown)
- Everything observable (metrics, health checks, structured logging)
- Plugin isolation (subprocess sandboxing, resource limits)
- Security-first (JWT RS256, RBAC/ABAC, audit hash chain, rate limiting)

---

## Repository Structure

```
server_manger/
├── README.md                          # Project homepage
├── launcher.py                        # CLI entry point
├── start.sh                           # Quick start script
├── run/                               # Runtime directory
│
├── .ai/                               # AI session governance
│   ├── AI_RULES.md                    # AI execution rules
│   ├── TOKEN_POLICY.md                # Token budget rules
│   ├── PROJECT_STATE.json             # Machine-readable progress
│   ├── locks/                         # Concurrent modification locks
│   ├── request-template.md            # Cross-batch request template
│   └── requests-readme.md             # Request protocol docs
│
├── _archive/                          # Historical development artifacts
│   └── Implementation/
│       ├── Batch-01/ through Batch-11/   # Per-batch execution logs
│       ├── MASTER_PLAN.md, ROADMAP.md, etc.
│       └── QA/                        # Empty QA templates
│
├── backend/                           # Python backend (FastAPI)
│   └── app/
│       ├── main.py                    # FastAPI app factory
│       ├── registration.py            # Module registration
│       ├── api/                       # REST + WebSocket layer
│       │   ├── deps.py               # DI dependencies
│       │   ├── errors.py             # Global exception handlers
│       │   ├── v1/
│       │   │   ├── middleware/        # Auth, audit, rate-limit, request-id
│       │   │   ├── routers/          # 9 REST endpoint groups
│       │   │   └── schemas/          # 7 Pydantic schema modules
│       ├── core/                      # Shared infrastructure
│       │   ├── command_bus.py        # Command bus (CQRS)
│       │   ├── query_bus.py          # Query bus
│       │   ├── event_bus.py          # Event bus
│       │   ├── saga.py               # Saga orchestrator
│       │   ├── circuit_breaker.py     # Circuit breaker pattern
│       │   ├── idempotency.py         # Idempotency keys
│       │   ├── feature_flags.py       # Feature flags
│       │   ├── config.py             # Configuration management
│       │   ├── security.py           # Password hashing, API keys
│       │   ├── auth_utils.py         # JWT utilities
│       │   ├── exceptions.py         # MCSError hierarchy
│       │   └── logging.py            # Structured logging
│       ├── modules/                   # 6 DDD modules
│       │   ├── server/               # Minecraft server domain
│       │   ├── backup/               # Backup/restore domain
│       │   ├── auth/                 # User & auth domain
│       │   ├── plugin/               # Plugin system domain
│       │   ├── monitoring/           # Health & metrics domain
│       │   └── event_store/          # Event store module
│       ├── services/                  # Orchestration services
│       │   ├── server_orchestrator.py
│       │   ├── backup_orchestrator.py
│       │   └── deployment_orchestrator.py
│       ├── core/persistence/          # DB persistence (ORM, UoW)
│       │   ├── base.py               # DeclarativeBase, BaseRepository
│       │   ├── db.py                 # DatabaseEngine, get_db
│       │   └── unit_of_work.py       # UnitOfWork pattern
│       ├── modules/storage/           # File storage backends
│       │   ├── base.py               # StorageBackend ABC
│       │   ├── local.py              # Local filesystem adapter
│       │   ├── s3.py                 # S3-compatible adapter
│       │   └── encryption.py         # AES-256-GCM encryption
│       ├── tasks/                     # Task queue & scheduling
│       │   ├── base.py               # Abstract Task
│       │   ├── queue.py              # InProcessQueue (SQLite)
│       │   ├── arq_queue.py          # ArqQueue (Redis)
│       │   ├── scheduler.py          # APScheduler integration
│       │   └── definitions/          # 5 task definitions
│       └── websocket/                # WebSocket layer
│           ├── manager.py            # Connection registry
│           ├── dispatcher.py          # Event → WS dispatcher
│           ├── authentication.py      # WS JWT verification
│           ├── authorization.py       # Channel permission check
│           ├── endpoint.py            # WS endpoint handler
│           ├── serializers.py         # Message serialization
│           ├── buffer.py             # Offline message buffer
│           ├── rate_limiter.py        # WS rate limiting
│           └── handlers.py           # Frontend event handlers
│
├── frontend/                          # React 19 + TypeScript
│   └── src/
│       ├── App.tsx                    # Root component + routing
│       ├── main.tsx                   # Entry point
│       ├── components/                # Shared UI components
│       ├── layouts/                   # Page layouts
│       ├── pages/                     # Auth pages
│       ├── server_manager/            # Main app module
│       │   ├── pages/                # 9 page components
│       │   ├── components/           # Domain-specific components
│       │   ├── hooks/                # React Query hooks
│       │   └── types/                # TypeScript types
│       ├── services/                  # API client
│       ├── stores/                    # Zustand stores
│       └── websocket/                 # WS client library
│
├── docs/                              # Professional documentation
│   ├── README.md                      # Documentation index
│   ├── STATUS.md                      # THIS FILE
│   ├── ARCHITECTURE.md                # System architecture
│   ├── API.md                         # REST API reference
│   ├── DATABASE.md                    # Database schema
│   ├── FRONTEND.md                    # Frontend architecture
│   ├── DEVELOPMENT.md                 # Dev setup guide
│   ├── CONTRIBUTING.md                # Contribution guide
│   ├── SECURITY.md                    # Security architecture
│   ├── PROVISIONING.md                # Server provisioning
│   ├── getting-started.md             # 5-minute quickstart
│   ├── roadmap.md                     # Past & future roadmap
│   ├── testing.md                     # Testing guide
│   ├── decisions/                     # 6 Architecture Decision Records
│   ├── runtime/                       # Runtime subsystem (7 docs)
│   └── reference/                     # Reference maps (5 docs)
│
├── contracts/                          # Shared contract schemas
│   ├── api.yaml                       # API conventions
│   ├── config.schema.json             # Server config JSON Schema
│   ├── events.yaml                    # Event payload schemas
│   ├── permissions.yaml               # Permission registry
│   └── plugin.yaml                    # Plugin manifest schema
│
├── events/                             # Domain event documentation
│   └── README.md                      # Event catalog
│
└── scripts/                            # Development toolchain
    ├── bootstrap                      # Environment setup
    ├── lint                           # ruff linter
    ├── format                         # ruff formatter
    ├── typecheck                      # pyright type check
    ├── test                           # pytest runner
    ├── check                          # lint + typecheck + test
    ├── build                          # Docker build
    ├── release                        # Tag + build + push
    └── preflight.sh                   # Pre-flight checks
```

---

## Architecture

### System Context

```
┌─────────┐     ┌──────────────┐     ┌──────────────┐
│ Browser ├────►│  FastAPI      │────►│  PostgreSQL  │
│         │     │  (Backend)    │     │              │
└─────────┘     │              │     └──────────────┘
                │  ┌──────────┐│
┌─────────┐     │  │ Command  ││     ┌──────────────┐
│  CLI    ├────►│  │  Bus     ││────►│  Redis       │
│         │     │  ├──────────┤│     │  (Cache+WS)  │
└─────────┘     │  │ Query    ││     └──────────────┘
                │  │  Bus     ││
┌─────────┐     │  ├──────────┤│     ┌──────────────┐
│ Plugins ├────►│  │ Event    ││────►│  Subprocess  │
│ (proc)  │     │  │  Bus     ││     │  Plugins     │
└─────────┘     │  └──────────┘│     └──────────────┘
                └──────────────┘
```

### Pattern Decisions

| Pattern | Implementation | Rationale (ADR) |
|---------|---------------|------------------|
| Modular Monolith | Hexagonal boundaries via DDD modules | 0001 — avoid microservice complexity |
| CQRS | Separate CommandBus, QueryBus | 0002 — clear read/write separation |
| Event-driven | EventBus with async dispatchers | 0002 — loose coupling |
| Saga Orchestrator | Compensation-based saga engine | Transactional multi-step operations |
| Repository | Aggregate-per-repository pattern | Data access abstraction |
| Unit of Work | Session-scoped transaction + event flush | Atomicity + event consistency |
| Circuit Breaker | Per-provider state machine | Prevent cascading failures |
| Plugin Isolation | Subprocess with JSON-RPC | 0003 — crash isolation, resource limits |
| Audit Hash Chain | SHA-256 linked list | Tamper-evident audit log |

### Bounded Contexts

| Context | Module | Responsibility |
|---------|--------|----------------|
| Server Management | `server/` | Minecraft server lifecycle |
| Backup/Restore | `backup/` | World backup, restore, verification |
| Plugin System | `plugin/` | Plugin install, isolation, SDK |
| User & Auth | `auth/` | Authentication, authorization, audit |
| Monitoring | `monitoring/` | Health checks, metrics collection |
| Event Store | `event_store/` | Append-only event log, DLQ |

### Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Runtime | Python | 3.14+ |
| Web Framework | FastAPI | 0.115+ |
| ASGI Server | Uvicorn | — |
| Database ORM | SQLAlchemy | 2.0+ (async) |
| Database Driver | asyncpg | — |
| Database | PostgreSQL | 16 |
| Cache | Redis | 7 |
| Validation | Pydantic | 2 |
| Task Queue | InProcessQueue / Arq | Dev / Prod |
| Scheduling | APScheduler | — |
| Frontend | React | 19 |
| Language | TypeScript | 5 |
| Build | Vite | — |
| Styling | TailwindCSS | 4 |
| State | TanStack Query + Zustand | — |
| Testing (BE) | pytest + pytest-asyncio | — |
| Testing (FE) | Vitest + Testing Library | — |
| Linting | Ruff | — |
| Container | Docker | — |

---

## Backend Specs

### Core Infrastructure

**CommandBus** — Synchronous command dispatch with middleware pipeline (logging, validation, idempotency, unit of work wrapping). Every command has exactly one handler. Returns result or raises `MCSError`.

**QueryBus** — Synchronous query dispatch with middleware pipeline. Read-only, no side effects. Returns read model or raises `MCSError`.

**EventBus** — In-process async event dispatch. Events published within a Unit of Work are flushed after commit. Middleware: audit log, DLQ, metrics.

**UnitOfWork** — Transaction scope. On commit: flush DB session, publish collected domain events, commit transaction. On rollback: discard session.

**SagaOrchestrator** — Compensation-based saga engine. Steps can define compensation actions. Failed sagas are persisted for manual recovery.

**CircuitBreaker** — Per-provider state machine: CLOSED → OPEN (on N failures) → HALF_OPEN (after timeout) → CLOSED (on success). `call_factory` for lazy coroutine creation.

**IdempotencyStore** — In-memory dict keyed by `IdempotencyKey`. 1-hour TTL with periodic cleanup.

**FeatureFlag** — In-memory dict with environment variable fallback. Flags: `backup_encryption`, `websocket_enabled`, `rate_limiting_enabled`, `maintenance_mode`.

### Module Structure (DDD)

Each module follows hexagonal architecture:

```
module/
├── domain/              # Core business logic
│   ├── aggregate.py     # Aggregate roots, entities, value objects
│   ├── events.py        # Domain events
│   └── repository.py    # Repository interfaces (ports)
├── application/         # Use cases
│   ├── commands/        # Command handlers
│   └── queries/         # Query handlers
└── infrastructure/      # Adapters
    ├── models.py        # SQLAlchemy ORM models
    ├── repository.py    # SQL repository implementations
    └── ...              # External adapters
```

### Server Module (`modules/server/`)

**Files:** 30+ Python files

| File | Purpose |
|------|---------|
| `domain/aggregate.py` | Server aggregate — state machine, config, runtime |
| `domain/value_objects.py` | ServerId, Port, Version, etc. |
| `domain/events.py` | server.created, server.started, server.crashed, etc. |
| `domain/repository.py` | ServerRepository interface |
| `domain/diagnostics.py` | Health check read models |
| `domain/runtime_exceptions.py` | Runtime error types |
| `application/supervisor.py` | Heartbeat-based liveness monitoring |
| `application/runtime_ownership.py` | RuntimeOwnershipManager — port/PID/tmux ownership |
| `application/runtime_reconciliation.py` | reconcile_orphans(), reconcile_all() |
| `application/reconciliation.py` | Legacy reconciliation |
| `application/commands/start_server.py` | Start command + port verification |
| `application/commands/stop_server.py` | Stop command + port release verification |
| `application/commands/restart_server.py` | Restart command |
| `application/commands/create_server.py` | Server provisioning |
| `application/commands/delete_server.py` | Server deletion |
| `application/commands/import_server.py` | Import existing server |
| `application/commands/update_server_config.py` | Config update |
| `application/queries/get_server.py` | Single server query |
| `application/queries/list_servers.py` | List servers query |
| `application/queries/get_server_console.py` | Console log stream |
| `application/queries/get_runtime_diagnostics.py` | Runtime health diagnostics |
| `infrastructure/providers/local.py` | LocalLinuxProvider |
| `infrastructure/providers/local_windows.py` | LocalWindowsProvider |
| `infrastructure/providers/docker.py` | DockerProvider |
| `infrastructure/providers/remote.py` | SSHProvider |
| `infrastructure/providers/cloud.py` | CloudProvider stub |
| `infrastructure/providers/base.py` | ServerProvider ABC |
| `infrastructure/providers/factory.py` | ProviderFactory |

### Auth Module (`modules/auth/`)

**Files:** 15 Python files

| File | Purpose |
|------|---------|
| `domain/aggregate.py` | User, Role, ApiKey aggregates |
| `domain/events.py` | user.login, user.logout events |
| `application/commands/login.py` | Login with password verification |
| `application/commands/logout.py` | Session invalidation |
| `application/commands/refresh_token.py` | Refresh token rotation |
| `application/commands/create_api_key.py` | API key generation |
| `application/commands/revoke_api_key.py` | API key revocation |
| `application/commands/create_user.py` | User registration |
| `application/commands/update_user.py` | Profile update |
| `application/commands/delete_user.py` | User deletion |
| `application/queries/get_current_user.py` | Current user info |
| `application/queries/list_users.py` | User list (admin) |
| `infrastructure/jwt.py` | RS256 JWT creation/verification |
| `infrastructure/permissions.py` | RBAC + ABAC evaluation |
| `infrastructure/audit.py` | SHA-256 chain audit log |

### Backup Module (`modules/backup/`)

**Files:** 10 Python files

| File | Purpose |
|------|---------|
| `domain/aggregate.py` | BackupJob aggregate |
| `domain/events.py` | backup.created, backup.completed events |
| `application/commands/create_backup.py` | Create backup (world + config) |
| `application/commands/restore_backup.py` | Restore from backup |
| `application/commands/delete_backup.py` | Delete backup |
| `application/commands/verify_backup.py` | Checksum verification |
| `application/queries/get_backup.py` | Single backup query |
| `application/queries/list_backups.py` | List backups query |

### Plugin Module (`modules/plugin/`)

**Files:** 14 Python files

| File | Purpose |
|------|---------|
| `domain/aggregate.py` | Plugin aggregate |
| `domain/events.py` | plugin.installed, plugin.enabled, etc. |
| `application/commands/install_plugin.py` | Plugin installation |
| `application/commands/uninstall_plugin.py` | Plugin removal |
| `application/commands/enable_plugin.py` | Plugin activation |
| `application/commands/disable_plugin.py` | Plugin deactivation |
| `infrastructure/manifest.py` | PluginManifest Pydantic model |
| `infrastructure/lifecycle.py` | PluginLifecycleManager |
| `infrastructure/dependency_resolver.py` | DFS dependency resolver |
| `infrastructure/sandbox.py` | Filesystem + network sandbox |
| `infrastructure/runner/base.py` | PluginRunner ABC |
| `infrastructure/runner/subprocess.py` | SubprocessPluginRunner (JSON-RPC) |
| `infrastructure/runner/container.py` | ContainerPluginRunner (stub) |

### Monitoring Module (`modules/monitoring/`)

**Files:** 10 Python files

| File | Purpose |
|------|---------|
| `domain/aggregate.py` | AlertRule aggregate |
| `domain/events.py` | Monitoring events |
| `infrastructure/health.py` | HealthCheckRegistry |
| `infrastructure/collector.py` | MetricsCollector |
| `infrastructure/metrics.py` | Prometheus metric definitions |
| `application/commands/create_alert_rule.py` | Alert rule creation |
| `application/commands/update_alert_rule.py` | Alert rule update |
| `application/queries/get_metrics.py` | Metrics query |

### Task Definitions

| Task | Schedule | Purpose |
|------|----------|---------|
| BackupTask | Per-server cron | Scheduled world backups |
| HealthCheckTask | 30s | Periodic system health checks |
| MetricsCollector | 15s | Server metrics polling |
| CleanupTask | Daily | Old log rotation, temp file cleanup |
| EventCleanup | Daily | Archive old events per retention |

---

## Frontend Specs

### Tech Stack

| Technology | Purpose |
|-----------|---------|
| React 19 | UI framework |
| TypeScript 5 | Type safety |
| Vite | Build tool |
| TailwindCSS 4 | Utility-first CSS |
| TanStack Query v5 | Server state, caching, pagination |
| Zustand | Client-side UI state |
| React Router v7 | Client-side routing |
| Vitest + Testing Library | Unit/integration tests |

### State Architecture

```
TanStack Query          Zustand            React Form
─────────────────      ──────────          ──────────
  Servers (list)        authStore           Server Config
  Backups (list)        uiStore             Login Form
  Plugins (list)        wsStore             Register Form
  Metrics (poll)                             Settings
  API Keys
```

### Pages & Routes

| Route | Component | Description |
|-------|-----------|-------------|
| `/login` | LoginPage | Authentication |
| `/register` | RegisterPage | Registration |
| `/` | DashboardPage | Overview with server cards |
| `/servers` | ServersPage | Server list with status |
| `/servers/new` | CreateServerPage | Server creation form |
| `/servers/import` | ImportServerPage | Import existing server |
| `/servers/:id` | ServerDetailPage | Server details + controls |
| `/backups` | BackupListPage | Backup management |
| `/plugins` | PluginListPage | Plugin management |
| `/settings` | SettingsPage | System settings |
| `/api-keys` | ApiKeysPage | API key management |

### Components

| Component | Purpose |
|-----------|---------|
| `Sidebar` | Navigation sidebar |
| `TopNav` | Top navigation bar |
| `AuthGuard` | Route protection |
| `EmptyState` | Empty state display |
| `ErrorBoundary` | Error boundary wrapper |
| `Skeleton` | Loading skeleton |
| `WebSocketManager` | WS connection lifecycle |
| `ServerConsole` | Live console output |
| `ServerMetricsCharts` | TPS, RAM, player charts |
| `Sparkline` | Mini sparkline chart |
| `ServerConfigEditor` | Config editing UI |
| `CreateBackupDialog` | Modal backup creation |
| `InstallPluginDialog` | Modal plugin installation |

### WebSocket Integration

- `useWebSocket()` hook provides connection lifecycle
- `wsStore` (Zustand) tracks connection state
- `client.ts` — auto-reconnect with exponential backoff (1s → 30s max)
- `handler.ts` — message routing + cache update callbacks
- `channels.ts` — channel subscription management
- WS → TanStack Query cache bridge for real-time updates

---

## API Reference

### Base

```
Base URL: /api/v1
Auth: Bearer <JWT access token>
Response Envelope:
  {
    "data": T | null,
    "error": { "code": str, "message": str, "details": ... } | null,
    "meta": { "page": int, "per_page": int, "total": int } | null
  }
```

### Endpoint Groups

#### Servers

| Method | Path | Description |
|--------|------|-------------|
| GET | `/servers` | List all servers |
| POST | `/servers` | Create server |
| GET | `/servers/{id}` | Get server details |
| PATCH | `/servers/{id}` | Update server config |
| DELETE | `/servers/{id}` | Delete server |
| POST | `/servers/{id}/start` | Start server |
| POST | `/servers/{id}/stop` | Stop server |
| POST | `/servers/{id}/restart` | Restart server |
| GET | `/servers/{id}/console` | Stream console output |
| GET | `/servers/{id}/runtime` | Runtime diagnostics |
| POST | `/servers/{id}/import` | Import existing server |

#### Runtime Ownership

| Method | Path | Description |
|--------|------|-------------|
| GET | `/runtime/ownership` | Full ownership snapshot |
| POST | `/runtime/ownership/claim` | Claim localhost ownership |
| GET | `/servers/{id}/runtime/validate` | Validate runtime state |

#### Backups

| Method | Path | Description |
|--------|------|-------------|
| GET | `/servers/{id}/backups` | List backups |
| POST | `/servers/{id}/backups` | Create backup |
| GET | `/backups/{id}` | Get backup details |
| DELETE | `/backups/{id}` | Delete backup |
| POST | `/backups/{id}/restore` | Restore backup |
| POST | `/backups/{id}/verify` | Verify backup checksum |

#### Plugins

| Method | Path | Description |
|--------|------|-------------|
| GET | `/servers/{id}/plugins` | List installed plugins |
| POST | `/servers/{id}/plugins` | Install plugin |
| GET | `/plugins/{id}` | Get plugin details |
| DELETE | `/plugins/{id}` | Uninstall plugin |
| POST | `/plugins/{id}/enable` | Enable plugin |
| POST | `/plugins/{id}/disable` | Disable plugin |

#### Auth

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/login` | Login (returns tokens) |
| POST | `/auth/logout` | Logout |
| POST | `/auth/refresh` | Refresh access token |
| GET | `/auth/me` | Current user info |
| POST | `/auth/api-keys` | Create API key |
| GET | `/auth/api-keys` | List API keys |
| DELETE | `/auth/api-keys/{id}` | Revoke API key |

#### Users

| Method | Path | Description |
|--------|------|-------------|
| GET | `/users` | List users (admin) |
| POST | `/users` | Create user (admin) |
| PATCH | `/users/{id}` | Update user (admin) |
| DELETE | `/users/{id}` | Delete user (admin) |

#### Monitoring

| Method | Path | Description |
|--------|------|-------------|
| GET | `/metrics` | Prometheus metrics |
| GET | `/health` | Health check status |
| GET | `/alerts` | Alert rules |
| POST | `/alerts` | Create alert rule |
| PATCH | `/alerts/{id}` | Update alert rule |

#### Tasks & Schedules

| Method | Path | Description |
|--------|------|-------------|
| GET | `/schedules` | List scheduled tasks |
| POST | `/schedules` | Create scheduled task |
| DELETE | `/schedules/{id}` | Delete scheduled task |

#### Settings

| Method | Path | Description |
|--------|------|-------------|
| GET | `/settings` | System settings |
| PATCH | `/settings` | Update settings |
| GET | `/software` | Available server software |

### Standard Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `NOT_FOUND` | 404 | Resource not found |
| `VALIDATION_ERROR` | 422 | Invalid input |
| `UNAUTHORIZED` | 401 | Missing/invalid auth |
| `FORBIDDEN` | 403 | Insufficient permissions |
| `CONFLICT` | 409 | State conflict |
| `RATE_LIMITED` | 429 | Too many requests |
| `SERVER_ERROR` | 500 | Internal error |
| `SERVICE_UNAVAILABLE` | 503 | Provider unavailable |

### Pagination

```
?page=1&per_page=20  ← default
Response meta: { page, per_page, total }
Headers: X-Total-Count, X-Page, X-Per-Page
```

### Rate Limiting

```
Per-route token bucket (default: 100 req/min)
Headers: X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset
```

---

## Database Schema

### Technology

- **Primary:** PostgreSQL 16 via asyncpg
- **Dev/Test:** SQLite via aiosqlite
- **ORM:** SQLAlchemy 2.0 async
- **Migrations:** Alembic (8 migration revisions)

### Key Tables (20+)

| Table | Module | Purpose |
|-------|--------|---------|
| `servers` | Server | Server aggregate (name, version, status, config, runtime) |
| `backup_jobs` | Backup | Backup records (size, checksum, status) |
| `users` | Auth | User accounts (hashed password, role) |
| `refresh_tokens` | Auth | Opaque refresh tokens (SHA-256 hash, single-use) |
| `api_keys` | Auth | API keys (mcs_ prefix, SHA-256 hash) |
| `roles` | Auth | Role definitions (viewer, operator, admin) |
| `audit_log` | Auth | Immutable audit log (SHA-256 chain) |
| `plugins` | Plugin | Installed plugin registry |
| `event_store` | EventStore | Append-only event log (SHA-256 chain) |
| `dead_letter_queue` | EventStore | Failed event storage |
| `alert_rules` | Monitoring | Alert threshold definitions |
| `metric_points` | Monitoring | Time-series metric storage |
| `cron_jobs` | Tasks | Scheduled task definitions |
| `task_queue` | Tasks | In-process task queue (SQLite) |
| `schema_migrations` | Core | Alembic migration tracking |

### Audit Log Design

```
audit_log
├── id (UUID PK)
├── timestamp (TIMESTAMPTZ)
├── actor_id (UUID FK → users)
├── action (VARCHAR)
├── resource_type (VARCHAR)
├── resource_id (VARCHAR)
├── details (JSONB)
├── ip_address (INET)
├── previous_hash (VARCHAR(64))   ← SHA-256 of previous row
├── hash (VARCHAR(64))            ← SHA-256(prev_hash + row_data)
└── verified (BOOLEAN)
```

### Event Store Design

```
event_store
├── id (BIGSERIAL PK)
├── event_id (UUID, UNIQUE)
├── event_type (VARCHAR)
├── version (INTEGER)
├── payload (JSONB)
├── metadata (JSONB)
├── previous_hash (VARCHAR(64))
├── hash (VARCHAR(64))
├── created_at (TIMESTAMPTZ)
└── archived (BOOLEAN, DEFAULT false)
```

---

## Domain Model

### Entity Hierarchy

```
EntityId (base)
├── ServerId
├── BackupId
├── PluginId
├── UserId
├── RoleId
├── ApiKeyId
├── AlertRuleId
└── CronJobId

AggregateRoot (base, extends EntityId)
├── Server
├── BackupJob
├── Plugin
├── User
├── Role
├── ApiKey
└── AlertRule
```

### Server Aggregate

```
Server (AggregateRoot)
├── id: ServerId
├── name: str
├── version: MinecraftVersion
├── status: ServerStatus
├── properties: ServerProperties (port, motd, max_players, etc.)
├── runtime: ServerRuntime | None
│   ├── provider: str
│   ├── external_id: str | None
│   ├── pid: int | None
│   ├── uptime_seconds: float
│   ├── restart_count: int
│   └── last_crash_time: float | None
├── events: List[DomainEvent] (collected on mutation)
│
├── create(name, version, properties) → Server
├── start(provider, external_id) → None
├── stop() → None
├── crash(exit_code, last_log_lines) → None
├── update_config(properties) → None
├── can_transition_to(target_status) → bool
└── validate_runtime_state() → ValidationResult
```

### Server Status Machine

```
                ┌─────────┐
                │ CREATED │
                └────┬────┘
                     │ start command
                     ▼
                ┌──────────┐
         ┌──────│ STARTING │──────┐
         │      └─────┬────┘      │
         │            │ provider   │ timeout
         │            ▼           │
         │       ┌─────────┐      │
         │       │ RUNNING │      │
         │       └────┬────┘      │
         │            │           ▼
         │       ┌──────────┐  ┌───────┐
         │       │ STOPPING │  │FAILED │
         │       └────┬────┘  └───────┘
         │            │
         │            ▼
         │       ┌─────────┐
         └───────│ STOPPED │
                 └─────────┘
                        │
                        ▼
                   ┌─────────┐
                   │ CRASHED │
                   └─────────┘

Transitions:
  CREATED   → STARTING  (start command)
  STARTING  → RUNNING   (provider reports running)
  STARTING  → FAILED    (provider timeout/error)
  RUNNING   → STOPPING  (stop command)
  RUNNING   → CRASHED   (process death detected)
  STOPPING  → STOPPED   (provider confirms stop)
  STOPPED   → STARTING  (start command)
  CRASHED   → STARTING  (restart command)
  FAILED    → STARTING  (retry)
  Any       → CREATED   (delete then recreate)
```

---

## Server Lifecycle

### Start Flow

```
1. Validate server can start (status check, port availability)
2. RunStartupValidationChain
3. Claim localhost ownership (RuntimeOwnershipManager.claim_localhost)
   a. Discover all running servers, tmux sessions, orphan PIDs
   b. Displace competing servers on same port
   c. Kill orphan tmux sessions
   d. Kill orphan Minecraft processes
   e. Verify port is free
4. Create RuntimeSupervisor (heartbeat monitoring)
5. Call provider.start()
   a. Local: create tmux session, run java -jar server.jar
   b. Docker: docker run ... 
   c. SSH: ssh ... java -jar server.jar
   d. Cloud: cloud provider API call
6. Wait for heartbeat (timeout: startup_timeout)
7. Verify port is listening
8. Mark server as RUNNING
9. Publish server.started event
```

### Stop Flow

```
1. Validate server can stop
2. Save current state (config, world)
3. Call provider.stop()
   a. Local: tmux send-keys "/stop" Enter, wait for process exit
   b. Docker: docker stop
   c. SSH: ssh ... "/stop"
4. Remove RuntimeSupervisor
5. Wait for port release (_wait_for_port_free, timeout: 5s)
6. Kill remaining process if any
7. Mark server as STOPPED
8. Publish server.stopped event
```

### Restart Flow

```
1. Stop (with port release verification)
2. Start (with ownership claim)
```

---

## Provider System

### Provider Interface

```python
class ServerProvider(ABC):
    async def start(self, handle: ServerHandle) -> ServerRuntimeStatus
    async def stop(self, handle: ServerHandle, force: bool = False) -> ServerRuntimeStatus
    async def status(self, handle: ServerHandle) -> ServerRuntimeStatus
    async def get_runtime_pid(self, handle: ServerHandle) -> int | None
    async def read_console(self, handle: ServerHandle) -> str
    async def send_command(self, handle: ServerHandle, command: str) -> None
    async def validate_environment(self) -> list[str]
```

### Available Providers

| Provider | Class | Status | Description |
|----------|-------|--------|-------------|
| Local Linux | `LocalLinuxProvider` | ✅ | tmux + Java subprocess |
| Local Windows | `LocalWindowsProvider` | ✅ | Windows process management |
| Docker | `DockerProvider` | ✅ | Docker container lifecycle |
| SSH Remote | `SSHProvider` | ✅ | Remote server via SSH |
| Cloud | `CloudProvider` | 🔶 Stub | Future cloud API |

### Provider Selection

```
ProviderFactory
├── register("local", LocalLinuxProvider)
├── register("local_windows", LocalWindowsProvider)
├── register("docker", DockerProvider)
├── register("ssh", SSHProvider)
└── get(name) → ServerProvider (wrapped in CircuitBreaker)
```

---

## Runtime System

### RuntimeSupervisor

Per-server heartbeat-based liveness monitor.

```
RuntimeSupervisor
├── start(server_id, heartbeat_interval=5)  → begin monitoring
├── stop(server_id)                          → stop monitoring
├── heartbeat(server_id)                     → update last heartbeat
├── is_running → bool
├── uptime → float (seconds since start)
├── get_for(server_id) → RuntimeSupervisor | None
└── is_supervised(server_id) → bool
```

**Crash Detection:** If heartbeat interval exceeds `missed_heartbeat_threshold` (3× interval), the server is considered crashed. `_handle_crash` is called which:
1. Cleans up OS resources (kills tmux session)
2. Calls `server.crash(exit_code=-1, ...)`
3. Publishes `server.crashed` event

### RuntimeOwnershipManager

Single-source-of-truth for every Minecraft runtime on the system.

```python
class RuntimeOwnershipManager:
    async def discover_all(self) -> OwnershipSnapshot
    async def claim_localhost(self, server_id: str) -> ClaimResult
    async def validate_runtime(self, server_id: str) -> ValidationResult
    async def cleanup_orphans(self) -> list[dict]
```

**discover_all()** scans:
- tmux sessions (find matching DB servers, orphan sessions)
- Java processes (match to DB servers, detect orphan PIDs)
- Listening ports (port ownership detection)
- DB records (find stale records with no OS process)
- Supervisors (find stale supervisors)

**Conflict Types:**

| Type | Auto-resolvable | Description |
|------|----------------|-------------|
| `DUPLICATE_PID` | Yes | PID claimed by multiple servers |
| `DUPLICATE_PORT` | Yes | Port claimed by multiple servers |
| `PORT_NOT_RELEASED` | No | Port still in use after stop |
| `PROCESS_NOT_TERMINATED` | No | Process still alive after kill |
| `STALE_SUPERVISOR` | Yes | Supervisor tracking non-existent process |
| `MULTIPLE_SERVERS_ACTIVE` | Yes | >1 server actively running |
| `ORPHAN_TMUX` | Yes | tmux session with no matching server |
| `ORPHAN_PROCESS` | Yes | Java PID with no matching server |

### RuntimeReconciliation

```
async def reconcile_server_runtime(server, provider) → ReconciliationResult
async def reconcile_all_runtimes(server_ids: list[str] | None) → dict
async def reconcile_orphans() → list[dict]
```

Checks:
- DB state vs actual tmux session existence
- DB state vs actual PID liveness
- Supervisor presence vs process state
- Orphaned Java PIDs (filtered by `_is_minecraft_java_pid()`)
- Orphaned tmux sessions

---

## Plugin System

### Plugin Lifecycle

```
INSTALLED → ENABLING → ENABLED → DISABLING → DISABLED
                                          → FAILED
```

### Plugin Manifest (`plugin.yaml`)

```yaml
id: my-plugin
name: My Plugin
version: 1.0.0
api_version: 1
main: main.py
description: Does something useful
author: Developer
dependencies:
  - other-plugin >= 1.0
permissions:
  network:
    - host: api.example.com
      port: 443
  storage:
    max_bytes: 10485760
```

### Isolation Architecture

```
┌──────────────────────────────────────┐
│            Host Process              │
│  ┌──────────────────────────────┐    │
│  │   PluginLifecycleManager     │    │
│  │   ┌────────────────────┐    │    │
│  │   │ SubprocessRunner   │    │    │
│  │   │  stdin/stdout      │    │    │
│  │   │  JSON-RPC 2.0      │    │    │
│  │   └────────┬───────────┘    │    │
│  └────────────┼─────────────────┘    │
└───────────────┼──────────────────────┘
                │ JSON-RPC over pipe
┌───────────────┼──────────────────────┐
│    Subprocess │  Plugin Process      │
│    ┌──────────▼───────────┐         │
│    │    BasePlugin        │         │
│    │  - Event subscription │         │
│    │  - Command execution  │         │
│    │  - Storage access     │         │
│    │  - HTTP client        │         │
│    └──────────────────────┘         │
│    Filesystem: plugin-data/ only    │
│    Network: manifest-whitelist only │
└──────────────────────────────────────┘
```

### SDK (`sdk/`)

| Component | Purpose |
|-----------|---------|
| `BasePlugin` | Main plugin class with lifecycle hooks |
| `@on_event(event_type)` | Event subscription decorator |
| `CommandExecutor` | Execute server commands |
| `Storage` | Scoped data/ directory access |
| `HttpClient` | Whitelisted HTTP client |

### Security Sandbox

- **Filesystem:** `Path.resolve()` prevents path traversal outside plugin directory
- **Network:** Only hosts/ports from manifest `permissions.network` are allowed
- **Process:** Separate subprocess, not in-process (memory/CPU isolation)
- **Container (future):** Docker-in-Docker isolation via `ContainerPluginRunner`

---

## Auth & Security

### Authentication Flow

```
Login
├── POST /auth/login { email, password }
├── Verify password (Argon2id)
├── Generate access token (RS256, 15m TTL)
├── Generate refresh token (opaque, SHA-256 stored, 7d TTL)
└── Return { access_token, refresh_token, expires_in }

Token Refresh
├── POST /auth/refresh { refresh_token }
├── Verify SHA-256 hash matches stored
├── Rotate: invalidate old, create new
└── Return new { access_token, refresh_token }

Logout
├── POST /auth/logout
└── Invalidate refresh token
```

### JWT Tokens

| Property | Access Token | Refresh Token |
|----------|-------------|---------------|
| Algorithm | RS256 | N/A (opaque) |
| TTL | 900s (15 min) | 604800s (7 days) |
| Storage | Client memory | DB (SHA-256 hash) |
| Rotation | Per-refresh | Single-use |
| Contains | user_id, role, permissions | token_id (random) |

### Authorization Model

RBAC + ABAC hybrid:

```
PermissionEvaluator
├── role_has_permission(role, permission) → bool    (RBAC)
└── context_allows(resource, context) → bool          (ABAC)
```

**Roles:**

| Role | Permissions |
|------|-------------|
| `viewer` | server:read, backup:read, plugin:read |
| `operator` | server CRUD + start/stop, backup CRUD, plugin install/manage |
| `admin` | admin:full (unrestricted) |

**Permission Strings:** 18 permissions across 6 groups (server, backup, plugin, user, settings, admin)

### Audit Log

```
audit_log table
├── SHA-256 hash chain: hash(previous_hash + json(row_data))
├── Every write operation is logged
├── verify_chain() → detects tampering
└── Queryable by actor, action, resource, time range
```

### Rate Limiting

| Layer | Mechanism | Default |
|-------|-----------|---------|
| API routes | Token bucket (in-memory) | 100 req/min per route |
| WebSocket | Token bucket | 60 msg/min per connection |
| Global | Nginx rate limiting (prod) | Configurable |

### API Keys

- Format: `mcs_` + 40 random hex chars
- Stored as SHA-256 hash (never plaintext)
- Scoped to permissions at creation
- Revocable (deleted from DB)

---

## WebSocket Protocol

### Connection

```
WebSocket: /api/v1/ws?token=<JWT>
```

### Server → Client Messages

| Type | Channel | Payload |
|------|---------|---------|
| `server.status` | `server:{id}` | `{ server_id, status, pid, uptime }` |
| `server.console` | `server:{id}:console` | `{ line, timestamp }` |
| `server.metrics` | `server:{id}:metrics` | `{ tps, players, ram, cpu }` |
| `backup.progress` | `server:{id}:backup` | `{ backup_id, progress_pct, stage }` |
| `plugin.event` | `server:{id}:plugin` | `{ plugin_id, event, version }` |
| `notification` | `user:{id}` | `{ title, message, type }` |

### Client → Server Messages

| Type | Purpose |
|------|---------|
| `subscribe` | `{ channels: ["server:1", "user:1"] }` |
| `unsubscribe` | `{ channels: ["server:1"] }` |
| `server.command` | `{ server_id, command: "say hello" }` |

### Reconnection

- Auto-reconnect with exponential backoff: 1s → 2s → 4s → ... → 30s max
- Pending messages queued during disconnect
- On reconnect: resubscribe to channels, replay missed events
- WS → TanStack Query cache bridge updates React state on reconnect

---

## Task Queue & Scheduling

### Task Queue

Two implementations sharing the same `TaskQueue` ABC:

| Implementation | Backend | Use Case |
|---------------|---------|----------|
| `InProcessQueue` | SQLite | Development, single-node |
| `ArqQueue` | Redis | Production, multi-node |

```python
class TaskQueue(ABC):
    async def enqueue(self, task: Task) -> str  # returns task_id
    async def dequeue(self) -> Task | None
    async def ack(self, task_id: str) -> None
    async def nack(self, task_id: str) -> None
    async def get_status(self, task_id: str) -> TaskStatus
    async def get_result(self, task_id: str) -> Any | None
```

### APScheduler Integration

- Cron schedules stored in `cron_jobs` table
- On startup: load all active schedules from DB
- Scheduler fires → enqueue task → worker executes
- Web UI to create/delete scheduled tasks

### Task Definitions

| Task | Purpose |
|------|---------|
| BackupTask | Create world backup on schedule |
| HealthCheckTask | Run health checks, update status |
| MetricsCollector | Poll servers, store metrics, publish |
| CleanupTask | Rotate old logs, clean temp files |
| EventCleanup | Archive old events per retention policy |

### Dead Letter Queue

- Events that exceed max retries (3) are stored in DLQ
- Manual replay via DLQ viewer commands
- Store-then-replay pattern: original event preserved, replay resubmits to bus

---

## Monitoring & Metrics

### Health Checks

```
HealthCheckRegistry
├── check_db()         → PostgreSQL/SQLite connectivity
├── check_redis()      → Redis connectivity (if configured)
├── check_disk()       → Free disk space health check_dlq()  → Dead letter queue depth
├── check_providers()  → Provider availability
└── run_all()          → Aggregate health status
```

### Prometheus Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `mcs_players_online` | Gauge | server_id | Current player count |
| `mcs_tps` | Gauge | server_id | Server ticks per second |
| `mcs_ram_used_bytes` | Gauge | server_id | JVM heap usage |
| `mcs_cpu_percent` | Gauge | server_id | CPU usage |
| `mcs_servers_total` | Gauge | status | Server count by status |
| `mcs_backup_size_bytes` | Gauge | server_id | Backup size |
| `mcs_api_requests_total` | Counter | method, route, status | API request count |
| `mcs_ws_messages_total` | Counter | channel, type | WebSocket message count |

### Metrics Pipeline

```
Collector (15s interval)
├── Poll each running server
├── Store metric_points in DB
├── Publish to Prometheus registry
└── Publish to WebSocket (2s batch window)

Retention (future):
  raw → 1m rollup → 1h rollup → 1d rollup
```

---

## Backup & Restore

### Backup Types

| Type | Contents |
|------|----------|
| Full | world/ + server.properties + plugins/ + logs/ |
| World-only | world/ directory only |
| Config-only | server.properties + whitelist + ops + bans |

### Backup Flow

```
1. Read server files from provider (local/Docker/SSH)
2. Stream to storage backend (local filesystem / S3)
3. Compute SHA-256 checksum during streaming
4. Encrypt with AES-256-GCM (if feature enabled)
5. Store backup record in DB
6. Publish backup.completed event
```

### Verification

```
POST /backups/{id}/verify
├── Read backup from storage
├── Recompute SHA-256 checksum
├── Compare with stored checksum
└── Return verification result
```

### Retention

- Configurable per-server retention policy
- CleanupTask removes old backups
- Minimum retention: 1 backup per server

---

## Storage Layer

### Storage Backends

| Backend | Class | Use Case |
|---------|-------|----------|
| Local | `LocalStorageBackend` | Development, single-server |
| S3 | `S3StorageBackend` | Production, off-site backup |

```python
class StorageBackend(ABC):
    async def stream_read(self, path: str) -> AsyncIterator[bytes]
    async def stream_write(self, path: str, stream: AsyncIterator[bytes]) -> str  # returns checksum
    async def delete(self, path: str) -> None
    async def exists(self, path: str) -> bool
    async def list(self, prefix: str) -> list[str]
    async def size(self, path: str) -> int
```

### Encryption

- AES-256-GCM via `cryptography.hazmat`
- Key derived from master key via Argon2id
- Per-backup random nonce stored alongside ciphertext
- Feature-flagged: `backup_encryption`

---

## Event System

### Event Envelope

```json
{
  "id": "uuid",
  "type": "server.crashed",
  "version": 1,
  "timestamp": "2026-07-26T12:00:00Z",
  "source": "runtime-supervisor",
  "correlation_id": "uuid",
  "payload": { "server_id": "srv_abc", "exit_code": -1 }
}
```

### Domain Events (21 total)

| Event | Version | Publisher | Subscribers |
|-------|---------|-----------|-------------|
| `server.created` | 1 | CreateServerHandler | Audit, WebSocket |
| `server.started` | 1 | StartServerHandler | Audit, WS, Metrics |
| `server.crashed` | 1 | Supervisor | Audit, WS, Recovery |
| `server.stopped` | 1 | StopServerHandler | Audit, WS |
| `server.config_updated` | 1 | UpdateConfigHandler | Audit |
| `backup.created` | 1 | CreateBackupHandler | Audit |
| `backup.completed` | 1, 2 | BackupOrchestrator | Audit, WS, Scheduler |
| `backup.restored` | 1 | RestoreBackupHandler | Audit |
| `backup.deleted` | 1 | DeleteBackupHandler | Audit |
| `plugin.installed` | 1 | InstallPluginHandler | Audit, WS |
| `plugin.enabled` | 1 | EnablePluginHandler | Audit, WS |
| `plugin.disabled` | 1 | DisablePluginHandler | Audit, WS |
| `plugin.uninstalled` | 1 | UninstallPluginHandler | Audit, WS |
| `user.login` | 1 | LoginHandler | Audit |
| `user.logout` | 1 | LogoutHandler | Audit |
| `user.created` | 1 | CreateUserHandler | Audit |
| `user.deleted` | 1 | DeleteUserHandler | Audit |
| `circuit.opened` | 1 | CircuitBreaker | Alert |
| `circuit.half_opened` | 1 | CircuitBreaker | Alert |
| `circuit.closed` | 1 | CircuitBreaker | Alert |
| `alert.triggered` | 1 | Monitor | WS, Notification |

### Event Store

- Append-only log with cryptographic chain (SHA-256)
- Queryable by event type, time range, correlation_id
- Archival policy: move old events to archive table
- DLQ: events that fail processing stored for replay

---

## Tests & Coverage

### Backend (781 passing)

| Test File | Tests | Group |
|-----------|-------|-------|
| `tests/test_command_bus.py` | 12 | Core |
| `tests/test_query_bus.py` | 14 | Core |
| `tests/test_event_bus.py` | 8 | Core |
| `tests/test_circuit_breaker.py` | 8 | Core |
| `tests/test_idempotency.py` | 5 | Core |
| `tests/test_saga.py` | 6 | Core |
| `tests/test_config.py` | 4 | Core |
| `tests/application/test_server_commands.py` | 40 | Server |
| `tests/application/test_server_queries.py` | 15 | Server |
| `tests/application/test_console.py` | 5 | Server |
| `tests/application/test_backup_commands.py` | 20 | Backup |
| `tests/application/test_restore_backup.py` | 8 | Backup |
| `tests/application/test_plugin_commands.py` | 25 | Plugin |
| `tests/application/test_plugin_manifest.py` | 12 | Plugin |
| `tests/application/test_auth_commands.py` | 37 | Auth |
| `tests/application/test_monitoring.py` | 20 | Monitoring |
| `tests/application/test_supervisor.py` | 15 | Runtime |
| `tests/application/test_runtime_ownership.py` | 38 | Runtime |
| `tests/application/test_runtime_reconciliation.py` | 13 | Runtime |
| `tests/application/test_import_service.py` | 10 | Services |
| `tests/domain/test_server_aggregate.py` | 30 | Domain |
| `tests/domain/test_value_objects.py` | 25 | Domain |
| `tests/domain/test_events.py` | 10 | Domain |
| `tests/infrastructure/test_providers.py` | 22 | Providers |
| `tests/infrastructure/test_sandbox.py` | 12 | Plugin |
| `tests/infrastructure/test_repositories.py` | 50 | Infra |
| `tests/websocket/test_ws_manager.py` | 15 | WS |
| `tests/websocket/test_ws_handlers.py` | 10 | WS |
| `tests/api/test_api_endpoints.py` | 60 | API |
| `tests/storage/test_storage.py` | 10 | Storage |
| `tests/tasks/test_queue.py` | 28 | Tasks |
| `tests/tasks/test_monitoring.py` | 20 | Monitoring |
| `tests/test_event_store.py` | 15 | Event Store |
| `tests/test_dead_letter.py` | 8 | Event Store |

### Frontend (148 passing)

| Test File | Tests | Group |
|-----------|-------|-------|
| `frontend/src/stores/*.test.ts` | 15 | Stores |
| `frontend/src/websocket/*.test.ts` | 25 | WebSocket |
| `frontend/src/components/*.test.tsx` | 30 | Components |
| `frontend/src/server_manager/components/*.test.tsx` | 25 | Domain Components |
| `frontend/src/server_manager/pages/*.test.tsx` | 35 | Pages |
| `frontend/src/services/*.test.ts` | 10 | Services |
| `frontend/src/hooks/*.test.ts` | 8 | Hooks |

**Total: 929 tests** (781 backend + 148 frontend)

---

## Deployment

### Docker

```bash
docker build -t mcs-manager .
docker run -d \
  -p 8000:8000 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /mnt/servers:/servers \
  -e DATABASE_URL=postgresql+asyncpg://user:pass@host/db \
  -e REDIS_URL=redis://host:6379 \
  -e JWT_PRIVATE_KEY=/run/secrets/jwt_private.pem \
  -e JWT_PUBLIC_KEY=/run/secrets/jwt_public.pem \
  mcs-manager
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite+aiosqlite:///data/mcs.db` | Database connection string |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection (optional) |
| `JWT_PRIVATE_KEY` | Auto-generated | RSA private key (PEM) |
| `JWT_PUBLIC_KEY` | Auto-generated | RSA public key (PEM) |
| `STORAGE_BACKEND` | `local` | `local` or `s3` |
| `S3_BUCKET` | — | S3 bucket name |
| `S3_REGION` | — | S3 region |
| `S3_ACCESS_KEY` | — | S3 access key |
| `S3_SECRET_KEY` | — | S3 secret key |
| `LOG_LEVEL` | `INFO` | Logging level |
| `MCS_SERVERS_DIR` | `/servers` | Server file storage |
| `MCS_STARTUP_TIMEOUT` | `120` | Max startup wait (s) |
| `MCS_BACKUP_RETENTION` | `7` | Days to keep backups |
| `RATE_LIMIT_PER_MINUTE` | `100` | API rate limit |

### Zero-Downtime Deployment

```
1. Health check passes on old container
2. Start new container (rolling update)
3. Health check on new container
4. Graceful shutdown of old container
   - Stop accepting requests
   - Drain active connections
   - Flush pending events
   - Close DB connections
```

---

## Project Status

### Build Status

| Check | Status |
|-------|--------|
| Backend tests | ✅ 781 passing |
| Frontend tests | ✅ 148 passing |
| Total tests | ✅ 929 passing |
| Linting (ruff) | ✅ No errors |
| Type check (pyright) | ⚠️ Pre-existing issues |
| Documentation | ✅ 31 files in `docs/` |
| Contracts | ✅ 5 schemas in `contracts/` |
| Docker build | ✅ |

### Deliverable Summary

| Batch | Name | Status | Files |
|-------|------|--------|-------|
| 01 | Core Foundation | ✅ Completed | 15 tasks |
| 02 | Domain Model | ✅ Completed | 9 tasks |
| 03 | Infrastructure Providers | ✅ Completed | 10 tasks |
| 04 | Application Layer | ✅ Completed | 16 tasks |
| 05 | API Layer | ✅ Completed | 20 tasks |
| 06 | WebSocket Layer | ✅ Completed | 13 tasks |
| 07 | Plugin System | ✅ Completed | 16 tasks |
| 08 | User & Auth | ✅ Completed | 15 tasks |
| 09 | Monitoring & Tasks | ✅ Completed | 16 tasks |
| 10 | Frontend | ✅ Completed | 28 tasks |
| 11 | Hardening Pass | ✅ Completed | 12 files fixed |

### Known Limitations

| Issue | Impact | Status |
|-------|--------|--------|
| ArqQueue.get_status/get_result return stubs | Cannot query task progress in prod | ⚠️ Known |
| Metrics retention rollups not implemented | Raw metrics only (no 1m/1h/1d aggregation) | 🔶 Future |
| ContainerPluginRunner is a stub | Plugins can't run in Docker isolation yet | 🔶 Future |
| Windows `_stdin_listener` untested | Plugin SDK may have issues on Windows | ⚠️ Known |
| JWT keys auto-generated in-process | Keys lost on restart unless PEM set explicitly | ⚠️ Documented |
| Permissions stored as comma-separated Text | Not normalized in DB | ⚠️ Known |

### Future Roadmap

| Item | Priority | Description |
|------|----------|-------------|
| Integration test suite | High | Full end-to-end test framework |
| Docker Compose quickstart | High | One-command dev environment |
| CI/CD pipeline (GitHub Actions) | High | Automated test/lint/build/deploy |
| S3 backup restore verification | Medium | Verify S3 backups can restore |
| Per-provider resource quotas | Medium | CPU/memory limits per server |
| Mobile push notifications | Low | Server crash/backup alerts to phone |
| Plugin marketplace UI | Low | Browse/install from curated registry |
| Mobile app | Low | React Native companion app |

---

*Generated: 2026-07-26 · Project: MCS Manager v4.0 (7.1.0)*
