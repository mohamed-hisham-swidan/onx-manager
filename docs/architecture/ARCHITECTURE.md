# Architecture Overview

**Last updated**: 2026-09-11
**Cross-references**: [ADR-0001](../decisions/0001-modular-monolith.md), [ADR-0002](../decisions/0002-command-query-event-buses.md), [ADR-0007](../decisions/0007-core-persistence-rename.md)

---

## System Context

```
┌─────────┐     ┌──────────────┐     ┌──────────────┐
│ Browser ├────►│  FastAPI      │────►│  PostgreSQL  │
│         │     │  (Backend)    │     │              │
└─────────┘     │              │     └──────────────┘
                │  ┌──────────┐│
┌─────────┐     │  │ Command  ││     ┌──────────────┐
│  CLI    ├────►│  │  Bus     ││────►│  SQLite      │
│         │     │  ├──────────┤│     │ (data store) │
└─────────┘     │  │ Query    ││     └──────────────┘
                │  │  Bus     ││
┌─────────┐     │  ├──────────┤│     ┌──────────────┐
│ Plugins ├────►│  │ Event    ││────►│  Subprocess  │
│ (proc)  │     │  │  Bus     ││     │  Plugins     │
└─────────┘     │  └──────────┘│     └──────────────┘
                └──────────────┘
```

Three client types (browser, CLI, plugin subprocesses) interact with a FastAPI backend. The backend dispatches through Command, Query, and Event buses backed by PostgreSQL (primary) and subprocess-isolated plugins. SQLite is supported as an embedded/development fallback. There is no Redis cache or pub/sub: the task queue is in-process (`InProcessQueue`).

---

## Module Architecture

### Layered Structure

```
backend/app/
├── main.py                    # FastAPI app factory + startup
├── registration.py            # Module registration
├── api/                       # Interface layer (REST + WebSocket)
│   ├── deps.py                # FastAPI dependency injection
│   ├── errors.py              # Global exception handlers
│   └── v1/
│       ├── middleware/        # Auth, audit, rate-limit, request-id
│       ├── routers/           # 16 endpoint groups + WebSocket
│       └── schemas/           # Pydantic request/response schemas
├── core/                      # Foundation layer
│   ├── command_bus.py         # CQRS command bus
│   ├── query_bus.py           # CQRS query bus
│   ├── event_bus.py           # Async event bus with retry + DLQ
│   ├── persistence/           # Database engine, Base ORM, UoW, reconciler
│   ├── saga.py                # Saga orchestrator
│   ├── circuit_breaker.py     # Circuit breaker pattern
│   ├── idempotency.py         # Idempotency keys
│   ├── feature_flags.py       # Feature flag system
│   ├── config.py              # Configuration (AppSettings)
│   ├── exceptions.py          # MCSError hierarchy
│   └── logging.py             # Structured logging
├── modules/                   # 11 DDD modules
│   ├── server/                # Minecraft server domain & lifecycle
│   ├── versioning/            # Git-inspired branching, snapshotting, tags, materialization
│   ├── backup/                # Backup/restore domain
│   ├── auth/                  # User & auth domain
│   ├── health/                # Health monitoring & diagnostics
│   ├── plugin/                # Plugin system domain
│   ├── monitoring/            # Health & metrics domain
│   ├── event_store/           # Event store module
│   ├── shared/                # Shared value objects (IDs, permissions, versions)
│   ├── storage/               # File storage backends (S3/local)
│   └── exposure/              # Playit.gg network tunneling domain
├── services/                  # Cross-module orchestration
├── tasks/                     # Task queue + scheduling
└── websocket/                 # WebSocket connection manager
```

### Dependency Direction

Hexagonal (ports/adapters) architecture — verified clean in Batch 4 audit:

```
api/ ──► application/ ──► domain/
  │                          │
  └──────────────────────► infrastructure/
                                │
core/ ──────────────────────────┘
```

- **Domain** never imports from infrastructure, application, or API
- **Application** never imports from API
- **Infrastructure** never imports from API
- Cross-module communication happens only through domain events (EventBus) or shared value objects (`app/modules/shared/`)
- The `core/` layer provides reusable infrastructure consumed by all layers

### Each DDD Module

```
module/
├── domain/              # Core business logic
│   ├── aggregate.py     # Aggregate roots, entities
│   ├── events.py        # Domain events
│   └── repository.py    # Repository interfaces (ports)
├── application/         # Use cases
│   ├── commands/        # Command handlers
│   └── queries/         # Query handlers
└── infrastructure/      # Adapters
    ├── models.py        # SQLAlchemy ORM models
    └── repository.py    # SQL repository implementations
```

---

## Key Patterns

### CQRS (ADR-0002)

Commands and queries are segregated at the bus level:

```
CommandBus          QueryBus           EventBus
──────────          ────────           ────────
Synchronous         Synchronous        Asynchronous
Returns result      Returns data       Fire-and-forget
With transaction    With cache         With retry + DLQ
Idempotency keys    No idempotency     No idempotency
```

Every command handler returns `CommandResult(success, data, error, error_code)`. Every query handler returns `QueryResult(data, total)` for paginated queries.

### Unit of Work

All mutations run inside a `UnitOfWork` context (`core/persistence/unit_of_work.py`). The UoW collects domain events during a transaction and publishes them to the EventBus after a successful commit. On failure, the session is rolled back and no events are published.

### Event Bus

Modules communicate exclusively via domain events dispatched through an in-process async event bus (ADR-0002). Events are delivered concurrently with retry (exponential backoff, 3 attempts) and overflow to a dead letter queue.

### Saga Orchestration

Multi-step operations (server provisioning, backup workflows) are managed by saga process managers with compensation actions. The `SagaOrchestrator` coordinates long-running workflows across bounded contexts.

### Repository Pattern

Each aggregate root has a dedicated repository interface in its domain layer with a SQLAlchemy implementation in its infrastructure layer. The generic `BaseRepository[T]` (`core/persistence/base.py`) provides common CRUD operations.

---

## Validation Strategy (ADR-0009)

Input validation follows a two-layer defense:

1. **Pydantic schema layer** (HTTP boundary): `@field_validator` on request schemas in `api/v1/schemas/` ensures invalid input is rejected at HTTP 422 with a structured error detail list.
2. **Handler safety-net** (domain boundary): Try/except around domain value-object constructors catches `ValueError` and raises `InvalidValueError` (MCSError subclass) for a consistent `VALIDATION_ERROR` code.

This pattern was applied to `minecraft_version` (Batch 2.5) and `email` (Batch 4). Any future domain value object that validates input must have a matching Pydantic validator.

---

## Sandbox Isolation (ADR-0008)

Testing and development are isolated from production via environment variables:

| Variable | Purpose | Default |
|----------|---------|---------|
| `MCS_DATABASE_URL` | Database connection | `sqlite+aiosqlite:///data/mcs.db` |
| `MCS_SERVERS_DATA_DIR` | Server file directory | `data/servers` |

Both must be set together when running test/development backends. Because `setsid` drops environment variables, they must be passed in the same command invocation as the uvicorn process.

---

## Technology Stack

### Backend

| Component | Choice |
|-----------|--------|
| Language | Python 3.12+ (`requires-python = ">=3.12"`; CI runs 3.12) |
| Framework | FastAPI |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic (39 revisions, head `b1e2100000019`) |
| Version source | `backend/pyproject.toml` → `backend/app/core/version.py:get_app_version()` (runtime, OpenAPI, settings, health) |
| Validation | Pydantic v2 |
| Logging | structlog |
| Message Queue | InProcessQueue (only implementation in use; Arq/Redis exists as unused code) |
| Event Bus | In-process async bus + dead letter queue |
| WebSocket | FastAPI WebSocket + custom connection manager |

### Frontend

| Component | Choice |
|-----------|--------|
| Language | TypeScript 5+ |
| Framework | React 19+ (Vite) |
| Styling | TailwindCSS 4+ (raw Tailwind components, no shadcn/ui) |
| Data Fetching | TanStack Query |
| State | Zustand |

### Data Stores

| Store | Purpose |
|-------|---------|
| PostgreSQL 16 | Primary database (design; see note) |
| SQLite 3 | Default dev/test and current deployment store |

### Containerization

| Component | Details |
|-----------|---------|
| Dockerfile (backend) | Multi-stage: deps → app → runtime |
| Dockerfile (frontend) | Build → nginx static serving |
| docker-compose.yml | Backend + frontend services, health checks, volumes |

---

## Production Deployment

### Docker

```
docker compose up --build    # Full stack
docker compose build         # Rebuild images
```

Both Dockerfiles and `docker-compose.yml` are at the repository root. The backend exposes port 8000; the frontend nginx proxy serves on port 80 and proxies `/api`, `/ws`, `/health`, `/docs` to the backend.

### Environment Variables (production)

The application supports dual environment variable prefixes (`ONX_*` takes precedence with fallback to legacy `MCS_*`):

| Variable | Required | Description |
|----------|----------|-------------|
| `ONX_DATABASE_URL` (or `MCS_DATABASE_URL`) | Yes | SQLite or PostgreSQL connection string |
| `ONX_JWT_PRIVATE_KEY` (or `MCS_JWT_PRIVATE_KEY`) | Yes* | RSA private key PEM (*auto-generated if absent) |
| `ONX_JWT_PRIVATE_KEY_PATH` (or `MCS_JWT_PRIVATE_KEY_PATH`) | No | Path to a PEM file to load instead of the env/auto-generated key |
| `ONX_STORAGE_BACKEND` (or `MCS_STORAGE_BACKEND`) | No | `local` or `s3` (default: `local`) |

The RSA public key is derived from the private key at runtime — no public-key
env var is needed.

Task queue: The runtime exclusively uses `InProcessQueue` (`backend/app/main.py`) in all environments. The legacy unused Arq/Redis queue (`tasks/arq_queue.py`) was removed in Batch 4 (F072) and the `aredis` dependency eliminated. There is no Arq/Redis deployment.

---

## File Ownership & Conventions (ADR-0010)

Every source file belongs to exactly one batch. No shared ownership. Changes are committed one logical step at a time — each commit is independently verifiable and has a clear message explaining the change, rationale, and verification results.

---

## Filesystem Reconciliation

A class-based service (`FilesystemReconciliationService` in
`server/application/services/filesystem_reconciliation.py`) keeps the database
in sync with the filesystem. It treats the disk as the single **Source of
Truth** — any directory under `data/servers/` is real, and any DB record
without a matching directory is stale.

The service implements a 6-stage pipeline with strict separation:

1. **FilesystemScanner** — list directories only
2. **IdentityReader** — read/validate `.mcsmanager/server.json` per dir
3. **MinecraftDetector** — reuse `scan_server_directory()` with `ScanCategory`
   (MINECRAFT_VALID / MINECRAFT_BROKEN / NOT_MINECRAFT / SCAN_FAILED)
4. **ReconciliationPlanner** — pure logic, builds Plan, no I/O
   (includes REPAIR_IDENTITY for self-healing corrupt identity files)
5. **TransactionExecutor** — write identity first (write-ahead), then DB writes
6. **IdentityWriter** — called during execution, not post-commit

Key properties:
- Every directory gets a UID (even non-Minecraft dirs)
- Identity files are written **before** each DB write (write-ahead safety)
- If identity write fails → exception → session rollback → clean state
- If DB write fails → identity file exists, idempotent on next reconciliation
- Self-healing: corrupted identity files are repaired and directory re-scanned
- Shared builder `_build_server_from_scan()` centralizes Server construction
- Supports `dry_run` mode for previewing changes
- All domain mutations go through aggregate methods, never private fields

- **Startup**: runs after runtime reconciliation in `main.py` lifespan
- **Refresh**: `POST /api/v1/servers/refresh?dry_run=true` endpoint
- **Auto-import**: new directories are imported with type/version detection
- **Cleanup**: stale DB records are deleted when their directory is gone

See [runtime/filesystem-reconciliation.md](../runtime/filesystem-reconciliation.md)
for full details.

---

## Task Queue & Scheduler

The task system is wired up in `main.py`'s `lifespan()` function, **not** in
any module's startup — this was the root cause of the metrics pipeline being
dead: the classes existed, but nothing ever instantiated or started them.

### Wiring (main.py lifespan)

```
InProcessQueue            ← instantiated, handlers registered
  └─ register("run_metrics_collection", handler)
MetricsCollector          ← instantiated, passed to init_collector()
Scheduler                 ← instantiated, given queue, started
  └─ start()              → loads cron_jobs from DB via _load_jobs()
  └─ add_job()            → persists to DB + schedules in APScheduler
```

### What breaks if this wiring is removed

- No cron jobs fire (including `metrics_collect_every_0.5s` and
  `integrity_scan_hourly`)
- `run_metrics_collection_task` is never called → no rows in `metric_points`
- The Prometheus metrics registry (`/monitor/metrics`) never updates
- There is no second-chance wiring — if `lifespan()` doesn't do it, nothing
  does.

### Data Sources — Monitoring

The `MetricsCollector.collect(server_id)` method consults three data sources
in priority order, each with an honest fallback when unavailable:

| Source | What it provides | When available | Fallback |
|--------|-----------------|----------------|----------|
| `psutil.Process(pid)` | RAM (RSS → MB), CPU % | When `server.runtime.pid` is set AND the process exists | `ram_used_mb=0.0, cpu_percent=0.0` |
| RCON (`/tps`, `/list`) | TPS, player count | When `server.properties` has `enable-rcon=true` AND `rcon.password` is set | `tps=20.0, players=0` |
| Hardcoded defaults | — | Always used as baseline | `tps=20.0, players=0, ram_used_mb=0.0, cpu_percent=0.0` |

This means `metric_points` rows can contain **functionally default values**
even though the pipeline runs correctly — the data source (PID, RCON) may
simply not be reachable for a given server.

### Persistent RCON connections

Every RCON TCP session makes the Minecraft server spawn a thread ("Thread RCON
Client started / shutting down" in the console). The original
`AsyncRCONClient` was created, authenticated, and closed on **every**
collection tick, producing one connect/disconnect cycle per minute per server.

`PersistentRCONClient` (`backend/app/modules/monitoring/infrastructure/rcon_client.py`)
reuses a single long-lived TCP session instead:

- `MetricsCollector` keeps a `dict[server_id, PersistentRCONClient]` and reuses
  the client across ticks; the pool is torn down in `close()` on shutdown.
- `ensure_connected()` returns the live client or transparently reconnects
  (creating a fresh `AsyncRCONClient`, clearing it on auth failure).
- `send_command()` serializes requests under an `asyncio.Lock`, retries up to
  `max_retries` with backoff, and re-establishes the connection between
  retries so a server restart or dropped socket self-heals without waiting for
  the next tick. Each response is validated against the request-id and packet
  type; a mismatch (a desynced connection) raises instead of returning stale
  data. If the task is cancelled mid-command (e.g. a collector timeout), the
  connection is dropped before propagating the cancel so the desynced socket is
  never reused.
- `close()` and `_close_unlocked()` both release the socket exactly once.
  `send_command` uses the unlocked variant to avoid re-acquiring the lock it
  already holds — re-acquiring there caused a permanent deadlock (every cron
  tick enqueued a task with `started_at` set but never completing).
- The collector cache is invalidated when a server's RCON host/port/password
  changes and evicted when RCON is disabled, so stale credentials never linger
  on a long-lived connection.
- `collect_all()` runs each server's collection concurrently with an
  individual `per_server_timeout`, so one slow or broken server cannot delay
  collection for healthy servers.

Connection state is intentionally short-lived in scope: the persistent client
only survives the lifetime of the worker process (uvicorn reload drops it),
which matches the single-worker deployment.

---

## Orphan Reconciliation Ownership Verification

`reconcile_orphans()` in `runtime_reconciliation.py` cleans up stale OS resources
(tmux sessions, Java processes) that belong to the project but have no matching
DB record. To prevent killing untracked real Minecraft servers, it uses a
**multi-factor ownership verification** system:

### Factors (checked in order)

1. **Positive ownership marker** — Every process spawned by `LocalLinuxProvider`
   gets `MCS_MANAGED=1` in its environment (`/proc/{pid}/environ`). Presence of
   this marker proves project ownership.
2. **cwd inside project data directory** — `/proc/{pid}/cwd` is resolved and
   compared against `MCS_SERVERS_DATA_DIR`. If the process's working directory
   is within the project's server data directory, it's treated as owned.
3. **DB cross-reference** — PID/session name matched against running/starting
   servers in the database (existing behavior from 3521d33).

### Scope separation

| Scope | Startup default | Behavior |
|-------|----------------|----------|
| `project_owned` | ✅ | Kills only if ≥1 ownership check passes AND not in DB as running/starting. Uncertain → skip (fail-safe). |
| `system_wide` | ❌ (manual API only) | Legacy: kills any `mcs-*` tmux session or Minecraft Java PID not in DB. |

### Fail-safe default

If any ownership check cannot be completed with certainty (`PermissionError`,
`OSError`, missing PID, etc.), the process is **not killed**, a warning is
logged, and the scanner moves on. This ensures startup never kills an untracked
server due to transient filesystem errors.

### Audit logging

Every kill decision produces a structured log line:
```
KILL_DECISION pid=12345 scope=project_owned marker=True cwd=/data/servers/abc start_time=98765 decision=KILL reason="orphan tmux session"
KILL_DECISION pid=99999 scope=project_owned marker=None cwd=None decision=SKIP reason="not-project-owned"
```

---

## Known Issues

### Nested-directory root_path (`data/servers/server` vs `data/servers/<uuid>`)

Some servers have `root_path = "data/servers/server"` (a single flat directory
name) instead of the expected UUID-based path `data/servers/<uuid>`. This was
likely caused by an older import or reconciliation version.

**Impact on monitoring**: Since the metrics collector resolves
`server.properties` via `deployment.properties_path()` →
`os.path.join(root_path, "server.properties")`, a mismatched root_path means
the properties file (and thus RCON config) is never found. This blocks TPS
and player-count collection for affected servers even if RCON is enabled on
disk.

**Status**: Deferred — the pipeline completes correctly; the data source just
isn't reachable until root_path is fixed.

---

## Testing

```bash
pytest                          # All tests (2,906 passed; 6 skipped; 0 failures)
pytest tests/ -x -q             # Quick run, stop on first failure
```

Test isolation: sandbox database + sandbox server directory, set via `MCS_DATABASE_URL` and `MCS_SERVERS_DATA_DIR`.

### CI

- **Backend CI** (`.github/workflows/backend-tests.yml`): full `pytest`, a DB
  compatibility-floor check (`scripts/check-db-revision`, minimum
  `b1e2100000019`), and a Ruff baseline regression gate
  (`scripts/check-ruff-baseline`). New Ruff violations fail; the 1738
  pre-existing violations / 42 rules baseline stays tracked.
- **Version propagation CI** (`.github/workflows/backend-version-ci.yml`):
  verifies `pyproject.toml`, runtime, and frontend package versions agree.
- **Frontend CI** (`.github/workflows/frontend-ci.yml`): typecheck, lint, test, build.

Pyright is **advisory / local only** — not a CI gate.

### DB compatibility floor

`0.1.0` pins minimum Alembic revision `b1e2100000019`
(`backend/app/core/persistence/db_revision.py`, `RELEASE_MINIMUM_DB_REVISION`).
Startup fails closed if the live DB is below the floor; the application never
auto-runs migrations (see `docs/VERSIONING.md` §4.3).

---

## Architectural Decision Records

Full decision records are maintained under [`docs/decisions/`](../decisions/README.md).

| ADR | Date | Title |
|-----|------|-------|
| 0001 | 2026-07-22 | Modular Monolith with Hexagonal Boundaries |
| 0002 | 2026-07-22 | Separate Command, Query, and Event Buses |
| 0003 | 2026-07-22 | All Plugins Run as Subprocesses |
| 0004 | 2026-07-22 | WebSocket — asyncio.Lock, EventDispatcher, Channel Permissions |
| 0005 | 2026-07-22 | JWT RS256 Authentication |
| 0006 | 2026-07-23 | Task Queue — Dual Implementation, Event Store Chain, DLQ |
| 0007 | 2026-07-27 | Rename app/storage/ to app/core/persistence/ |
| 0008 | 2026-07-27 | Environment-Variable-Driven Sandbox Isolation |
| 0009 | 2026-07-27 | Pydantic Field Validators for Domain Value-Object Inputs |
| 0010 | 2026-07-27 | Commit-per-Step Discipline for Structural Changes |
| 0011 | 2026-07-27 | Orphan Reconciliation with Ownership Verification |
| 0012 | 2026-08-04 | Same-Filesystem Staging for Atomic File Swaps |
| 0013 | 2026-09-17 | Domain-Model-First for Stage A Entities |
| 0014 | 2026-09-17 | Shared Commit DAG Migration Strategy and Branch Lifecycle |
| 0015 | 2026-09-17 | Runtime Domain Entity and ServerProvider Relationship |
| 0016 | 2026-09-17 | PersistentDataset Boundary and Non-Mutation Isolation |
