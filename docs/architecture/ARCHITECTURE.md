# Architecture Overview

**Last updated**: 2026-11-22
**Cross-references**: [ADR-0001](../decisions/0001-modular-monolith.md), [ADR-0002](../decisions/0002-command-query-event-buses.md), [ADR-0007](../decisions/0007-core-persistence-rename.md), [SPEC-2026-11-09-SIMPLE-ADVANCED-MODES-02](../design/SPEC-2026-11-09-SIMPLE-ADVANCED-MODES-02.md)

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
├── main.py                    # FastAPI app factory + startup lifespan
├── registration.py            # Module handler, middleware & event subscriber registration
├── api/                       # Interface layer (REST + WebSocket)
│   ├── deps.py                # FastAPI dependency injection & RBAC/ABAC guards
│   ├── errors.py              # Global exception handlers
│   └── v1/
│       ├── middleware/        # Auth, audit, rate-limit, request-id
│       ├── routers/           # 19 router files (215 live routes) + WebSocket
│       └── schemas/           # Pydantic request/response schemas (BaseResponse UTC normalization)
├── core/                      # Foundation layer
│   ├── command_bus.py         # CQRS command bus + DatabaseBusyRetryMiddleware
│   ├── query_bus.py           # CQRS query bus
│   ├── event_bus.py           # Async event bus with retry + DLQ
│   ├── persistence/           # Database engine, Base ORM, UoW, reconciler, db_revision
│   ├── allowlist.py           # Allow-list v2.3 normative classifier & open_safe_path_fd
│   ├── host_state.py          # Authoritative 0700 host-state layout & path validation
│   ├── container_hardening.py # Shared Docker hardening (--cap-drop=ALL, non-root, pids-limit, /data-only)
│   ├── saga.py                # Saga orchestrator
│   ├── circuit_breaker.py     # Circuit breaker pattern
│   ├── idempotency.py         # Idempotency keys
│   ├── feature_flags.py       # Feature flag system
│   ├── config.py              # Configuration (AppSettings, ONX_* / MCS_* sources)
│   ├── settings_store.py      # Runtime dynamic settings store
│   ├── identity.py            # Platform branding & path identity constants
│   ├── timeutil.py            # UTC ISO-8601 time normalization
│   ├── version.py             # Single-source app version
│   ├── platform_lock.py       # FD CLOEXEC & cross-platform file locking
│   ├── process_utils.py       # Cross-platform process inspection & tree kill
│   ├── security.py            # Hashing, token validation
│   ├── security_files.py      # Secret file permission guards (0600)
│   ├── exceptions.py          # MCSError / ONXError hierarchy
│   └── logging.py             # Structured logging
├── modules/                   # 13 DDD modules (10 full DDD + 3 flat support modules)
│   ├── server/                # Minecraft server domain, lifecycle leases, discovery, provisioners
│   ├── versioning/            # Git-native branching, CAS, LEC, vaults, merge, branch runtimes, GitHub sync, modpacks & upgrades
│   ├── operations/            # Multi-step asynchronous operations & recovery
│   ├── activity/              # Per-server & per-branch activity & audit logs
│   ├── backup/                # Backup/restore domain + pinned rollback protection
│   ├── auth/                  # User & auth domain (JWT RS256, RBAC/ABAC, invites)
│   ├── health/                # Health monitoring, evidence & crash diagnostics
│   ├── plugin/                # Plugin system & Modrinth/CurseForge catalog domain
│   ├── monitoring/            # Metrics, persistent RCON & alert rules
│   ├── event_store/           # Event store module (flat support module)
│   ├── shared/                # Shared value objects (flat support module)
│   ├── storage/               # File storage backends (flat support module)
│   └── exposure/              # Playit.gg / UPnP / Cloudflare network exposure domain
├── services/                  # Cross-module orchestration (server, backup, deployment)
├── tasks/                     # InProcessQueue task queue + APScheduler scheduling
└── websocket/                 # WebSocket connection manager, console stream & serializers
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

Standard DDD modules (`server`, `versioning`, `operations`, `activity`, `backup`, `auth`, `health`, `plugin`, `monitoring`, `exposure`) follow hexagonal boundaries:

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

*Note:* `event_store`, `shared`, and `storage` are flat support modules without layered subdirectories.

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

`CommandBus` executes handlers through an ordered middleware pipeline (`backend/app/registration.py`):
1. `IdempotencyMiddleware` — deduplicates retries by idempotency key
2. `DatabaseBusyRetryMiddleware` — retries transient SQLite lock contention
3. `ServerLifecycleLockMiddleware` — acquires DB-backed multi-worker server lifecycle leases (`server_lifecycle_leases`, 90s TTL, 25s heartbeat, reentrancy via `ContextVar`) before mutating server runtime state.

When both lifecycle and repository locks are held (e.g., during live refresh or rollback), the lock order is fixed: `ServerLifecycleLeaseManager` first, then `RepoLeaseManager` (host `flock` + monotonic `fencing_token`).

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

## Sandbox Isolation & Host State (ADR-0008, P2-1)

Testing and development are isolated from production via environment variables (`ONX_*` takes precedence with fallback to legacy `MCS_*`):

| Variable | Purpose | Default |
|----------|---------|---------|
| `ONX_DATABASE_URL` / `MCS_DATABASE_URL` | Database connection | `sqlite+aiosqlite:///data/onx.db` |
| `ONX_SERVERS_DATA_DIR` / `MCS_SERVERS_DATA_DIR` | Server file directory | `data/servers` |
| `ONX_HOST_STATE_DIR` | Authoritative host-state layout (`0700` on POSIX) | `<data>/host-state` (derived) |
| `ONX_HOST_STATE_HOST_DIR` | Host-visible bind path when panel runs containerized | `""` |

Both database and server data paths must be set together when running test/development backends. Because `setsid` drops environment variables, they must be passed in the same command invocation as the uvicorn process.

---

## Simple vs Advanced Modes & P1–P5.5 Architecture

Guided by `SPEC-2026-11-09-SIMPLE-ADVANCED-MODES-02` (v8.7), ONX Manager separates standard server operation (`ServerMode.SIMPLE`) from Git-backed declarative server engineering (`ServerMode.ADVANCED`):

- **Mode Gate & Platform Policy**: `mode_guard.py` and router dependencies enforce Simple vs Advanced boundaries across versioning commands and routes. Per owner decision `P2-6g` Option B, `advanced_mode_enabled` defaults to `os.name == "posix"`, keeping Windows Simple-only and fail-closed.
- **Authoritative Host-State Layout (`core/host_state.py`)**: Isolates panel-owned artifacts outside container-writable `/data` under `<host_state_dir>/`: `server-meta/` (authoritative Simple lockfiles), `cas/` (SHA-256 Artifact CAS), `lec/` (Loader Environment Cache), `class-c-vault/` (AES-256-GCM encrypted Class-C snapshots), `repos/` (native bare/worktree Git repos), `locks/` (`RepoLeaseManager` + `RepoWriteLock`), `journal/` (swap/refresh journals), `quarantine/`, and `data-templates/`.
- **Allow-list v2.3 (`core/allowlist.py`)**: Enforces TOCTOU-free descriptor-relative traversal (`open_safe_path_fd` with `O_DIRECTORY | O_NOFOLLOW` and `(st_dev, st_ino)` checks) and classifies every path into Class A (code/jars → CAS + `onx-jars.lock.json`), Class B (configs → Git; 1–16 MiB auto-routed to A-CAS), Class C (runtime/world/player state → encrypted Class-C vault), Class D (ignored ephemeral files), or Class E (forbidden/hostile paths).
- **Clean Export, Journaled Swap & Triad Rollback (`refresh_orchestrator.py`)**: Builds a deterministic staged `/data` tree (`CleanExportService` + `.onx-complete.json`), carries complement Class-C state, performs a crash-safe journaled directory swap (`renameat2(..., RENAME_EXCHANGE)` or journaled `live -> live.prev` + `staging -> live` with `RefreshStartupReconciler` recovery), and triggers automatic triad rollback (Class A+B, Class-C snapshot, pinned Class-E backup) if the health gate fails.
- **Protected `main`, Structured Merge & Vaults**: Enforces system-level `main` branch protection and removes Promote; provides key-level 3-way merge for YAML/TOML/JSON/Properties + `diff3` (`merge_engine.py`), `DynamicClassCRegistry`, AES-256-GCM Class-C snapshots (`format_version=2`, `ONX_MASTER_KEK`), `${ONX_SECRET_*}` secret vault (`server_secrets`), and Structured & Pattern Secret Scanner (`secret_scanner.py`).
- **Isolated Branch Runtimes & Data Templates**: Runs branch/test containers in parallel with production via `BranchRuntimeService`, atomic `HostPortSet` allocation, ephemeral Class-C overlays (`white-list=true`, `enforce-whitelist=true`), quiescent `DataTemplates` (60s-capped RCON `save-off` with startup `save-on` recovery), and live RCON branch console.
- **GitHub Sync & Webhook Queue**: `GitHubSyncService` provides fetch-first remote sync, non-fast-forward `main` guards, plain-jar gates, credential scrubbing, and an encrypted `GitHubVault`; `github_webhook_router` validates HMAC signatures and enqueues durable `github_webhook_deliveries`.
- **Modpacks, LEC & 1-Click Safe Upgrades**: `.mrpack` and CurseForge parsers with strict archive quarantine, loader gating (`fabric`, `forge`, `neoforge`, `quilt`), 19-host HTTPS download allow-list (`download_allowlist.py`), `LoaderEnvCache` (`lec_store.py` / `lec_builder.py`) for Paper (Fill v3 pre-warm), Forge (`1.17.1`–`1.20.1` bounds & argfile launch), NeoForge, Fabric, and Quilt, hash-only Modrinth compatibility matrix + transitive dependency BFS (`upgrade_matrix.py`), NBT `level.dat` `DataVersion` verification (`nbt_reader.py`), and a 4-step race-free `UpgradeHealthGateEvaluator` (stdout regex, TCP + RCON `save-all flush`, NBT `DataVersion`, dimension smoke).
- **Docker-Only Runtime, Resource Budgeting & Two-Tier Backups**: Runs all servers inside hardened Docker containers (`DockerProvider`) with profile-aware host RAM/CPU admission budgeting (`ResourceBudgetService`), Tier-1 snapshots (`tier1_snapshot.py`), chunked AES-256-GCM envelope-encrypted Tier-2 archives (`tier2_archive.py`, `envelope_crypto.py`), and Simple ↔ Advanced conversion endpoints (`/convert/to-advanced`, `/convert/to-simple`).
- **Container Hardening (`core/container_hardening.py`)**: All 4 Docker spawn paths (server, installer, isolated test, bot pool) enforce `--cap-drop=ALL`, `--security-opt=no-new-privileges:true`, `--pids-limit=2048`, non-root `--user`, and a single `/data` bind mount.

---

## Technology Stack

### Backend

| Component | Choice |
|-----------|--------|
| Language | Python 3.12 (installer-pinned; `requires-python = ">=3.12"`; CI runs 3.12) |
| Framework | FastAPI |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic (53 revisions, head `b1e2100000033`, floor `b1e2100000033`) |
| Version source | `backend/pyproject.toml` → `backend/app/core/version.py:get_app_version()` (runtime, OpenAPI, settings, health) |
| Validation | Pydantic v2 |
| Logging | structlog |
| Serialization | PyYAML, `tomli-w` (TOML merge), JSON |
| Cryptography | `cryptography` (JWT RS256, backup AEAD, AES-256-GCM Class-C & secret vaults) |
| Message Queue | InProcessQueue (in-process async queue; no Redis/Arq dependency) |
| Event Bus | In-process async bus + dead letter queue |
| WebSocket | FastAPI WebSocket + custom connection manager |

### Frontend

| Component | Choice |
|-----------|--------|
| Language | TypeScript 5.5+ |
| Framework | React 19+ (Vite 5.4+) |
| Styling | TailwindCSS 4+ (multi-skin semantic token engine, raw Tailwind primitives, no shadcn/ui) |
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
| `ONX_MASTER_KEK` / `ONX_MASTER_KEK_FILE` | No* | 32-byte master KEK for AES-256-GCM Class-C snapshots, `${ONX_SECRET_*}` vault, and panel integration secrets (*required for Advanced mode / encrypted snapshots) |
| `ONX_CURSEFORGE_API_KEY` | No | Optional CurseForge API key (also configurable via encrypted panel secrets UI) |
| `ONX_HOST_STATE_DIR` / `ONX_HOST_STATE_HOST_DIR` | No | Host-state directory override & container-visible host bind path |
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
2. **IdentityReader** — read/validate `.onx-manager/server.json` per dir (with `.mcsmanager/server.json` legacy fallback)
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
- The Prometheus metrics registry (`/metrics`) never updates
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

1. **Positive ownership marker** — Legacy host processes spawned with `MCS_MANAGED=1` / `ONX_MANAGED=1` in `/proc/{pid}/environ` (note: local host-process providers were removed in P6 in favor of Docker-only execution, while orphan ownership verification remains active for safety).
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

**Status**: Resolved — `MetricsCollector._resolve_server_properties_path` falls back to `AppSettings().servers_data_dir` when a legacy relative/nested `root_path` does not contain `server.properties`, and normalizes wildcard `rcon_host` addresses (`0.0.0.0`, `::`, `*`) to `127.0.0.1`.

---

## Testing

```bash
pytest                          # Backend suite (5,318 passed, 7 skipped across 328 test_*.py files)
pytest tests/ -x -q             # Quick run, stop on first failure
npm test                        # Frontend suite (1,353 passed across 139 test files)
```

Test isolation: sandbox database + sandbox server directory, set via `ONX_DATABASE_URL` / `MCS_DATABASE_URL` and `ONX_SERVERS_DATA_DIR` / `MCS_SERVERS_DATA_DIR`.

### CI

- **Backend CI** (`.github/workflows/backend-tests.yml`): full `pytest`, DB
  compatibility-floor check (`scripts/check-db-revision`, minimum
  `b1e2100000033`), PowerShell BOM check (`scripts/check-ps1-bom`), stray DB check
  (`scripts/check-stray-db`), and Ruff baseline regression gate
  (`scripts/check-ruff-baseline`).
- **Version propagation CI** (`.github/workflows/backend-version-ci.yml`):
  verifies `pyproject.toml`, runtime, and frontend package versions agree.
- **Route contract CI** (`.github/workflows/route-permission-ci.yml`): verifies
  215 live routes match `contracts/permissions.yaml`.
- **Frontend CI** (`.github/workflows/frontend-ci.yml`): typecheck, lint, test, build.
- **Docker build smoke** (`.github/workflows/docker-build-smoke.yml`): builds Docker image on backend Dockerfile/requirements changes.
- **Verification cadence & Windows CI** (`verification-cadence.yml`, `windows-ci.yml`): weekly scheduled cadence (`verification-cadence.yml`) and manual dispatch (`windows-ci.yml`).

Pyright is **advisory / local only** — not a CI gate.

### DB compatibility floor

`0.1.0` pins minimum Alembic revision `b1e2100000033`
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
| 0017 | 2026-10-20 | Branch-Head Compare-and-Swap (CAS) for Versioning |
| 0018 | 2026-10-20 | Atomic Promote Config Writes and Durability (F1-2a; Promote removed in P3-1) |
| 0019 | 2026-10-20 | Dynamic Backend Port Selection with Active-Port Reuse |
| 0020 | 2026-11-02 | Installer and Launcher Pin Python to Exactly 3.12 |
| 0021 | 2026-11-04 | Frontend UX/IA Overhaul and Design Token System |
| 0022 | 2026-11-08 | Brand Tokens and Favicon Architecture |
| 0023 | 2026-11-08 | Corner Style Setting and Radius Token Architecture |
