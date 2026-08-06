# MCS Manager — Architecture & Domain Model

**Part II** of the Engineering Blueprint V4. The complete engineering architecture: system context,
module structure, the CQRS buses, runtime model, storage model, and per-subsystem design. A senior
engineer should be able to make correct changes after reading this document alone.

**Last updated:** 2026-08-06
**Supersedes:** `docs/ARCHITECTURE.md` and `docs/DATABASE.md` as the primary architecture reference.
Those files remain in `docs/` for cross-reference; this document is the canonical description.

---

## 1. System Context

### 1.1 Logical view

```
┌─────────────┐        ┌───────────────────────────────────────────────────────────┐
│  Browser     │◄─HTTP─┤                        FastAPI (single process)            │
│  (React SPA) │        │                                                           │
└─────────────┘        │  API layer ──► Application layer ──► Domain layer           │
        │              │       │                │                │                   │
        │        ┌─────┼───────┘                │                ▼                   │
        │        │  WS  │            Command/Query buses     Event Bus ──► Event Store│
┌─────────────┐  │  /ws │                │                        │         (hash chain)
│  CLI / curl  │◄─┤      │                ▼                        ▼                   │
└─────────────┘  │      │        Infrastructure adapters    (audit, DLQ, WS push)     │
        │        │      │                │                                            │
        │        │      │                ▼                                            │
┌─────────────┐  │      │   ┌──────────┐  ┌───────────┐  ┌───────────────────────┐   │
│ Plugin SDK   │◄─┼──────┼──►│ Providers│  │ Repos     │  │ Storage backends      │   │
│ subprocesses │  │      │   │ (tmux/   │  │ (SQLAlch) │  │ (local, S3)           │   │
└─────────────┘  │      │   │  docker/  │  │           │  └───────────────────────┘   │
                 │      │   │  ssh)     │  └─────┬─────┘                              │
                 │      │   └──────────┘        │                                     │
                 │      │                       ▼                                     │
                 │      │              ┌─────────────────┐      ┌────────────────┐    │
                 │      │              │  PostgreSQL 16 / │      │  Minecraft     │    │
                 │      │              │  SQLite 3        │      │  server data   │    │
                 │      │              └─────────────────┘      └────────────────┘    │
                 └──────┴────────────────────────────────────────────────────────────┘
```

### 1.2 Deployment topology

- **Single process, modular monolith** (ADR-0001). One uvicorn worker serves REST, WebSocket, and
  the scheduler. There is no separate worker process in the current production shape.
- **Frontend** is a static React build served by nginx, which proxies `/api`, `/ws`, `/health`,
  `/docs`, `/openapi.json` to the backend (see `docs/DEPLOYMENT.md`).
- **Database** is SQLite in the current deployment (`backend/mcs.db` dev, `backend/data/servers/mcs.db`
  production); PostgreSQL 16 is the supported upgrade path. Redis is *not* used by the running
  system despite appearing in early stack documentation (see §5.4).
- **Minecraft servers** run on the same host (local providers) or a reachable host (SSH provider),
  managed through tmux sessions by default.

### 1.3 Clients

| Client | Transport | Auth | Purpose |
|---|---|---|---|
| Browser SPA | HTTP + WebSocket | Bearer JWT + WS token query param | Primary admin UI |
| CLI / curl | HTTP | Bearer JWT or `mcs_` API key | Scripting, debugging |
| Plugin subprocess | JSON-RPC over stdin/stdout | host-issued (socket/process identity) | Plugin ↔ host communication |
| External scrapers | HTTP | none (`GET /metrics` public — K10) | Prometheus scraping |

---

## 2. Module Structure & Layering

### 2.1 Directory layout

```
backend/app/
├── main.py                 # FastAPI app factory, lifespan (all wiring), middleware, health/metrics
├── registration.py         # Command/Query/Event handler registration, infrastructure init
├── api/                    # Interface layer
│   ├── deps.py             # FastAPI dependency injection (buses, storage, auth deps)
│   ├── errors.py           # Global exception handlers → error envelope
│   └── v1/
│       ├── middleware/     # RequestID, Auth, Audit, RateLimit (in that order)
│       ├── routers/        # 11 routers: auth, backups, health, marketplace, monitoring, plugins,
│       │                   #   schedules, servers, settings, software, users
│       └── schemas/        # Pydantic request/response schemas
├── core/                   # Foundation layer
│   ├── persistence/        # DatabaseEngine, BaseRepository, UnitOfWork, DeclarativeBase
│   ├── command_bus.py      # CQRS command bus
│   ├── query_bus.py        # CQRS query bus
│   ├── event_bus.py        # Async event bus with retry + dead-letter
│   ├── saga.py             # Saga orchestrator
│   ├── circuit_breaker.py  # Circuit breaker pattern
│   ├── idempotency.py      # Idempotency keys
│   ├── feature_flags.py    # Feature flag system
│   ├── config.py           # AppSettings + ConfigFactory
│   ├── exceptions.py       # MCSError hierarchy
│   ├── security.py         # Argon2id, API key hashing
│   ├── http_client.py      # Shared aiohttp client
│   └── logging.py          # Structured logging
├── modules/                # 9 DDD bounded contexts (see §3)
├── services/               # Cross-module saga orchestrations (server lifecycle, backup)
├── tasks/                  # TaskQueue, Scheduler, task definitions
└── websocket/              # Connection manager, auth, authorization, dispatcher, handlers
```

### 2.2 Dependency direction (hexagonal / ports-adapters)

```
api/ ──► application/ ──► domain/
  │                         │
  └────────────────► infrastructure/
                        │
core/ ───────────────────┘
```

- **Domain** never imports infrastructure, application, or API.
- **Application** never imports API.
- **Infrastructure** never imports API.
- Cross-module communication is only via buses (`core/`) or shared value objects (`modules/shared/`).
- The `core/` layer is shared infrastructure consumed by all layers.

This was verified clean in the Batch 4 architecture audit (2026-07-27) and is enforced by ruff
import rules and review. Phase 6 (§06) hardens enforcement with CI.

### 2.3 Validation: two-layer defense (ADR-0009)

1. **Pydantic schema layer** (HTTP boundary): `@field_validator` on request schemas rejects invalid
   input at HTTP 422 with a structured `detail` list.
2. **Handler safety-net** (domain boundary): try/except around domain value-object constructors
   catches `ValueError` and re-raises `InvalidValueError` (MCSError) for a consistent
   `VALIDATION_ERROR` code.

Applied today to `minecraft_version`, `email`, port ranges, memory minimums, and JVM args. Any new
domain value object that validates input must have a matching Pydantic validator — this is a standing
rule (ADR-0009), not a one-time fix.

---

## 3. The Nine Bounded Contexts

Each module is a complete hexagonal slice: `domain/` (aggregates, value objects, events, repository
interfaces), `application/` (command/query handlers), `infrastructure/` (SQLAlchemy models,
repository implementations, adapters). The per-module detail below covers the parts a changing
engineer needs.

### 3.1 `server` — Server Lifecycle & Deployment

**Purpose.** Owns the server aggregate — the central entity of the product — and its runtime lifecycle:
create, configure, import, start, stop, restart, delete, console, diagnostics, and filesystem
reconciliation.

**Domain objects.** `Server` aggregate root; value objects `ServerId`, `MinecraftVersion`,
`ServerType`, memory bounds, port, `ServerStatus` state machine
(`created → installing → stopped → running`, plus crash states). Domain events: `server.created`,
`server.starting`, `server.running`, `server.stopping`, `server.stopped`, `server.crashed`,
`server.config_changed`.

**State machine.** All transitions go through aggregate methods (`mark_running()`, `mark_stopped()`,
`mark_crashed()`, `mark_missing()`), never through private field writes. `Server.crash(exit_code,
last_log_lines)` records crash data and emits `server.crashed`.

**Key application services.**

- `FilesystemReconciliationService` — 6-stage pipeline reconciling DB ↔ disk (see §6.2).
- `RuntimeSupervisor` — per-server asyncio watchdog (see §6.3).
- `RuntimeOwnershipManager` / `reconcile_orphans` — ownership-verified OS resource cleanup (see §6.4).
- `migrate_old_import_arch` — one-time migration of legacy import-layout servers.

**Lifecycle.** Servers are created either explicitly (`CreateServerCommand`) or auto-imported by
filesystem reconciliation. Deletion is DB-row-delete plus directory removal after commit (verified in
Batch 2.5 fix 4). Runtime reconciliation at startup repairs DB/OS mismatches.

**Dependencies.** `core/` buses + persistence; `shared/` value objects; `storage/` for nothing
directly (backups are a separate module); providers in `server/infrastructure/providers/`.

**Extension points.** New deployment providers (see §6.1). New scan categories in reconciliation.

**Failure modes / recovery.** Server start failures are diagnosed by `RuntimeSupervisor` and surfaced
as `server.crashed` with diagnostics. Crash recovery is handled by the `health` module (§3.5). The
startup guard (`StartServerHandler`) pre-flights Java, disk, memory, and provider availability before
launch.

**Security.** Start/stop/command/refresh/import/delete are permission-gated (`server:write`,
`server:start`, `server:stop`, `server:delete`) — enforced since Batch 9. Commands are validated
against a whitelist to avoid injecting arbitrary console commands with elevated context.

**Testing.** 40 command tests, 15 query tests, 5 console tests, 30 aggregate tests, 25 runtime
reconciliation tests, 38 runtime ownership tests, 22 provider tests.

### 3.2 `backup` — Backup & Restore

**Purpose.** Create, restore, verify, and delete backups of Minecraft server data. Multiple granular
backup types (full, world, plugins, config) with matching restore.

**Domain objects.** `BackupJob` and `BackupPolicy` aggregates. `backup.job` columns: `backup_type`,
`status` (`pending/running/completed/failed`), `size_bytes`, `checksum` (SHA-256), `storage_path`.
Events: `backup.started`, `backup.completed` (v1 + v2 schemas), `backup.failed`.

**Pipeline (CreateBackupHandler → BackupSaga).**
1. **Save-world** (`_save_world`): if the server is running, send `save-all` and poll provider
   console output (≤30s) for `saved the (game|world)` before proceeding; timeout marks the job
   `FAILED`. **K14: this regex is unverified against a real Purpur server** — see Phase 3.
2. **Archive**: tar.gz of the world/config/plugin directories.
3. **Encrypt**: AES-256-GCM (`cryptography.hazmat`), producing `{backup_id}.tar.gz.enc`.
4. **Upload** to the configured `StorageBackend` with size + checksum.
5. **Verify**: re-read the artifact and compare checksums.
6. **Persist** `BackupJob` with `storage_path` tracked end-to-end.

**Restore pipeline.** Decrypt → extract to a **same-filesystem staging directory** (ADR-0012 —
staging must share a filesystem with the target or `os.replace` fails with EXDEV) → atomically swap
folders/files onto the live server directory, deferred-until-restart for the running JVM.

**Delete order.** Delete the storage artifact **before** deleting the DB row; on failure keep the
row and return `success=False`. This prevents orphaned encrypted files (Batch 8 fix 1). Also note the
`artifact_path()` fix: returns `f"{backup_id}.tar.gz.enc"` without a duplicated `backups/` prefix.

**Saga.** `BackupSaga` orchestrates the multi-step pipeline with compensation (a failed step cleans
up partial artifacts). Saga state lives in `saga_instances`/`saga_steps` tables.

**Dependencies.** `storage/` for backends; `server/` for console and directory paths; `core/` buses.

**Failure modes.** Save-world timeout → job FAILED. Checksum mismatch at verify → failed, artifact
removed. Staging on wrong filesystem → EXDEV (fixed by ADR-0012). **Known limitation:** saga step
failures store only `"Failed at step '<step_name>'"` in `job.error_message`; the underlying cause is
visible only in server logs — see Phase 3 (§05) and the `backup_saga_error_detail` backlog item.

**Security.** Backup artifacts are encrypted at rest. Restore/delete/create are permission-gated
(`backup:restore`, `backup:delete`, `backup:create`); verify is `backup:read`.

**Testing.** 9 command tests, 6 saga tests, 21 storage tests. Regression coverage exists for
delete-order and artifact-path issues.

### 3.3 `plugin` — Plugin Registry, Lifecycle, Marketplace

**Purpose.** Two distinct responsibilities (a product decision — see Phase 1):

1. **Server-scoped plugin management** — installed `.jar` files on a selected server, their state,
   enable/disable/uninstall.
2. **Global marketplace** — discover and install plugins from a catalog provider (Modrinth today).

**Filesystem is the source of truth.** `ReconcilePluginsHandler` runs on every
`GET /servers/{id}/plugins`: `.jar` files on disk with no DB row → new `source="detected"` rows; DB
rows whose file is gone → pruned (unless pending deletion). The `plugins` table is a metadata cache.

**Plugin row columns.** `filename` (reconciliation key), `source` (`detected` | `modrinth`),
`external_project_id`/`external_version_id`/`external_url`/`checksum` (Modrinth provenance),
`pending_deletion` (deferred deletion — file removed on next server start/restart so the JVM never
loses a loaded `.jar`).

**Deferred deletion.** `UninstallPluginHandler` sets `pending_deletion=True`; the file is removed at
the next server start/restart. This prevents removing a `.jar` out from under a running JVM.

**Catalog provider abstraction (K16A).** `PluginCatalogProvider` ABC:
`search`, `get_project`, `get_project_versions`, `get_version`, `download(url, expected_sha1,
expected_sha512)`. `ModrinthProvider` is the only registered provider. Selection is
**configuration-driven** via `MCS_PLUGIN_PROVIDERS` (default `modrinth`), validated fail-fast at
startup by `validate_plugin_providers`. **K16A accepts exactly one active provider**; list syntax is
preserved for future multi-provider work, but multi-provider config currently fails at startup.

**Version selection.** `select_best_version()` ranks: exact game version + exact loader → exact game
version on nearest compatible parent loader (`purpur → paper → spigot → bukkit`, with a
`loader_fallback` notice) → closest available game version (with a `version_mismatch` warning, never
hard-blocking). Always returns the full version list newest-first for manual override.

**Install flow.** `InstallModrinthPluginHandler`: resolve server deployment root (rejects
`vanilla`/`fabric`/`forge` as manual-only) → resolve version (explicit or best-version) → download
with SHA-1/SHA-512 verification → atomic write into `<server_dir>/plugins/` (existing filename →
`FILE_CONFLICT`) → create `modrinth` row → commit.

**Plugin subprocess execution (ADR-0003).** Plugins the product itself runs (distinct from
Minecraft plugins) run as isolated subprocesses communicating via JSON-RPC over stdin/stdout. This is
the plugin *system* (Batch 07), separate from the marketplace concept. Filesystem sandbox restricts
writes to the plugin directory; network sandbox allows only hosts from the manifest.
`ContainerPluginRunner` is a stub (`NotImplementedError`) — future Docker-in-Docker isolation.
**Note:** this subsystem is currently dormant — no first-party plugins ship — but it is complete and
tested (60 tests across 6 files).

**Permissions.** Delete + all three marketplace routes require `plugin:manage`; **enable/disable are
auth-only (K4, no `require_permission`)** — a Phase 4 gap. `GET /plugins` list triggers
reconciliation. The global marketplace search (`GET /api/v1/marketplace/search`, new router
`marketplace.py`) requires `plugin:manage`.

**Testing.** 25 command tests, 12 manifest tests, 12 runner tests, 12 sandbox tests, 14 provider
tests, plus dependency-resolver and lifecycle tests.

### 3.4 `auth` — Users, Roles, JWT, Authorization

**Purpose.** Identity (login/logout/refresh), credentials (API keys), authorization (RBAC+ABAC),
and audit.

**Domain objects.** `User` aggregate (email, Argon2id password hash, `is_active`, `last_login_at`),
`Role` aggregate (permissions text field), `RefreshTokenModel`, `ApiKeyModel`.

**Authentication (ADR-0005).**
- **JWT RS256**, 2048-bit RSA, 15-min access tokens. Keypair auto-generated in-process by default;
  production must load persistent PEM via `set_private_key()` / `MCS_JWT_PRIVATE_KEY` /
  `MCS_JWT_PRIVATE_KEY_PATH`. **K11: ephemeral auto-generated keys are lost on restart** unless set.
- **Refresh tokens**: opaque 48-byte random, stored as SHA-256 hash, single-use rotation, 7-day TTL,
  individually revocable (logout revokes by hash lookup).
- **API keys**: `mcs_` prefix, SHA-256 hash via `hash_api_key()` (**unsalted** — documented), shown
  once at creation.
- **Argon2id** password hashing.

**Authorization (RBAC + ABAC hybrid).**
- 17 `resource:action` permission strings; three roles: `viewer`, `operator`, `admin`.
- `PermissionEvaluator` (RBAC) + `evaluate_abac()` (ownership/scope rules).
- **Known gap:** the evaluator builds token claims at login/refresh but is **not** invoked to gate
  requests on most routes. Only 24 routes are gated by `require_permission` (as of the Phase 4
  volume snapshot): 22 mutating + 2 read-only marketplace. 9 mutating routes + 23 sensitive GET
  routes remain auth-only. This is the central Phase 4 work (§05).

**Audit log.** `audit_log` table, append-only, SHA-256 hash chain over JSON-serialized content
(`_fmt_ts()` normalizes timestamps). `verify_chain()` exists but **nothing schedules it** — automatic
periodic verification is Phase 3/6 scope. No audit query endpoint exists yet.

**Permission storage debt (K12).** Roles/API keys store permissions as comma-separated `Text`
(non-normalized); `SQLUserRepository.save()` performs an async lazy-load on `model.roles`
(`MissingGreenlet` risk) at `repository.py:55` — currently unreachable (no code path assigns roles),
but sits in the exact code Phase 4 expands.

**WebSocket auth.** `verify_ws_token()` validates the JWT before `accept()`. Channel authorization
exists but always denies (K1, §6.6).

**Testing.** 37 auth command tests, 15 login-flow tests, 8 audit tests, plus jwt/password/api-key/
permissions tests.

### 3.5 `health` — Health Evaluation, Crash Diagnostics, Integrity

**Purpose.** Evaluate a server's health from signals (runtime, integrity, crashes), diagnose crashes,
and orchestrate recovery. This is the newest module (post-Batch-10), built from
`architecture/health-engine-design.md`.

**Pipeline.**

1. **Evidence collection**: `EvidenceCollector` gathers log tail, crash-report parsing, system
   snapshot.
2. **Crash analysis**: `PatternCrashAnalyzer` maps 18 failure patterns to `FailureCode`s.
3. **Health calculation**: `SignalHealthCalculator` — sliding window, signal weighting, transition
   constraints, trend detection.
4. **Recovery**: `RecoveryOrchestrator` — auto-restart with escalation after 3 crashes / 300s.
5. **Event flow**: `ServerCrashedEvent` → collect → classify → recover. `HealthSignalHandler`
   subscribes to `RuntimeHealthSignal`/`IntegrityCheckFailed`/`CrashClassified` and re-computes
   health. `GenerateHealthReport` query produces uptime %, crash frequency, worst status.

**Health tables.** `health_status`, `health_timeline`, `health_evidence`, `health_diagnostics`
(migration `876be46160d4`).

**Dependencies.** `server/` (crash events, diagnostics types), `monitoring/` (runtime signals),
`core/` buses.

**Extension points.** New `FailureCode`s, new crash patterns, new health signals, new recovery
strategies.

**Failure modes.** Evidence collection can fail (unreadable logs) — the pipeline degrades to the
best available evidence. Recovery orchestrator must not loop (escalation cap).

**Testing.** 15 aggregate, 20 event, 30 value-object, 6 command, 6 query, 12 repository, 22
calculator, 11 evidence, 18 crash-analyzer, 13 recovery-orchestrator tests.

### 3.6 `monitoring` — Metrics & Alerts

**Purpose.** Collect time-series performance data (TPS, players, RAM, CPU) per server; define and
evaluate threshold alert rules.

**Data sources (in priority order, each with honest fallback).**

| Source | Provides | Fallback when unavailable |
|---|---|---|
| `psutil.Process(pid)` | RAM (RSS→MB), CPU% | `0.0` values |
| RCON (`/tps`, `/list`) | TPS, player count | `tps=20.0, players=0` |
| Hardcoded defaults | — | Baseline |

**Important honesty note:** `metric_points` rows can contain functionally default values even when
the pipeline runs correctly — the data source (PID reachable, RCON enabled + password set) may simply
not be reachable. A zero isn't necessarily a broken collector.

**Persistent RCON.** `PersistentRCONClient` reuses a single long-lived TCP session per server instead
of reconnecting every tick (each connect forces the Minecraft server to spawn/destroy a thread).
`send_command()` serializes under an `asyncio.Lock`, retries with backoff, reconnects between
retries; the re-acquire deadlock bug (double-lock on close) was fixed — use `_close_unlocked()` when
the lock is already held. The pool lives only as long as the worker process (matches single-worker
deployment).

**Metrics registry.** Prometheus gauges (TPS, players, RAM, CPU) updated by `MetricsCollector`;
exposed at `GET /metrics` (public — K10, deferred decision).

**Task wiring.** `MetricsCollector` is instantiated in `main.py` lifespan and passed to
`init_collector()`. The scheduler registers the `metrics_collect_every_60s` cron job. **If this
wiring is removed, metric_points silently stop growing** — there is no second-chance init path
(ADR-0006 post-hoc finding).

**Alert rules.** `alert_rules` table: per-server, per-metric threshold rules (`>`, `<`, `>=`, `<=`),
severity, cooldown. **Known limitation:** the alerts/schedules REST routes are stubs (K13).

**Retention (ADR-0006 decision 4).** Four-tier pipeline is *designed* (raw→1m→1h→1d with retention
1h/30d/1y/forever) but **rollups are not implemented** — raw `metric_points` only.

**Testing.** 20 monitoring tests, 15 collector tests, 20 task tests.

### 3.7 `event_store` — Append-Only Event Log

**Purpose.** Persist every domain event as an immutable, tamper-evident log; provide query,
pagination, and dead-letter handling.

**Design.** `event_store` table: `event_id`, `event_type`, `correlation_id`, `data_json`,
`schema_version`, `previous_hash`, `hash`. Hash = `SHA-256(previous_hash + event_id + event_type +
data_json + created_at_iso)`. No UPDATE/DELETE at the application layer. Retention 1 year (partitioned
by month). Integrity verified by replaying the chain (`verify_chain()`).

**Write path.** Events are collected during a transaction by `UnitOfWork` and flushed to the event
store before the domain transaction commits; they are then published to the `EventBus`. Event-store
persistence is therefore *atomic with the transaction* — this is the load-bearing distinction from
the (currently uninstantiated) WS dispatcher (K2).

**Dead letter queue.** `dead_letter_events` — events that exhausted the EventBus's 3 retries. Admin
replays via DLQ commands (re-publish to the bus); never auto-retried.

**Security.** The chain detects tampering but does not prevent it. `GET /metrics`-style public
exposure of the event store is not implemented and must not be added without auth.

**Testing.** 15 event-store tests, 8 dead-letter tests.

### 3.8 `storage` — File Storage Backends

**Purpose.** Abstract object/file storage for backups (and future artifacts) behind one interface.

**Design.** `StorageBackend` ABC with `stream_read`/`stream_write` defaults; `LocalStorage` and
`S3Storage` adapters. Encryption helpers (`BackupEncryption`, AES-256-GCM) live here or in backup
infra (see `docs/DATABASE.md`); selected via `MCS_STORAGE_BACKEND` (`local` default, `s3` optional).

**Failure modes.** S3 unavailability → backup upload fails with a clear error; the saga
compensates. **Important:** this module is unrelated to the old `app/storage/` directory (renamed to
`app/core/persistence/` by ADR-0007) — the naming collision is resolved and documented.

**Testing.** 21 storage tests.

### 3.9 `shared` — Cross-Context Value Objects

**Purpose.** Types that more than one module needs, defined once: `EntityId` base (`ServerId`,
`PluginId`, etc.), `Permission`, `AggregateRoot` base with event collection, `MinecraftVersion`
semantics where shared, domain event base.

**Dependency rule.** `shared` may be imported by any module; it imports nothing from modules.

---

## 4. The CQRS Buses (ADR-0002)

### 4.1 CommandBus

- **Synchronous**, returns `CommandResult(success, data, error, error_code)`.
- **Transactional** — handlers create `UnitOfWork` internally and use SQL repositories via the UoW
  session.
- **Idempotency** — commands carry idempotency keys; duplicates return cached results
  (`idempotency_keys` table, 24h TTL).
- Dispatch: `await command_bus.dispatch(CommandType, payload)` → registered handler.
- Errors are caught at the bus boundary and mapped to `MCSError`; unexpected exceptions become
  `UNEXPECTED_ERROR`.

### 4.2 QueryBus

- **Synchronous**, returns `QueryResult(data, total)` for paginated queries.
- **No idempotency, no transactions** — reads only.
- Caching is described in ADR-0002 as a middleware option; in practice read caching is handled at
  the frontend layer (TanStack Query), not in the query bus.

### 4.3 EventBus

- **Asynchronous**, fire-and-forget, with **retry (3 attempts, exponential backoff 2^n) + per-handler
  timeout (10s) + dead-letter queue**.
- Subscriptions are **exact event-type match** — the bus has no wildcard support. Subscribers must
  register per event type (this is why the WS `EventDispatcher` must be started with an explicit
  event-type list — K2).
- Priority ordering via `Priority` IntEnum (CRITICAL/HIGH/NORMAL/LOW).
- `UnitOfWork.commit()` publishes collected events **after** the DB commit, in order.

**Cross-module communication rule:** modules publish domain events; they never call each other's
services. This is what keeps the modular monolith's boundaries real.

---

## 5. Persistence & Storage Model

### 5.1 DatabaseEngine and sessions

`DatabaseEngine` (`core/persistence/db.py:16`) wraps `create_async_engine` (SQLAlchemy 2.0 async)
and provides an `async_sessionmaker`. Sessions are injected via FastAPI `Depends(get_db)`. Pooling:
20 pool size / 10 max overflow / `pool_pre_ping=True` for PostgreSQL; SQLite mode skips pooling
(`pool_size` params disabled for SQLite compatibility).

URL from `MCS_DATABASE_URL`; supports `postgresql+asyncpg://` and `sqlite+aiosqlite:///`. Alembic
reads the same URL (via env or `alembic.ini` fallback).

### 5.2 UnitOfWork

```
async with UnitOfWork(event_bus) as uow:
    repo = uow.get_repo("servers", ServerModel)
    await repo.add(server)
    uow.add_event(DomainEvent(...))
    # __aexit__: commit → publish events on success; rollback + run cleanups on exception
```

- Sessions are created inside `__aenter__` (not reused across requests — no request-scoped session
  leak).
- `defer_cleanup(fn)` registers async cleanups run on rollback (used for temp file cleanup).
- Events are published **only after a successful commit**, in insertion order.

### 5.3 Key tables (schema highlights)

See `docs/DATABASE.md` for the full column listing; the architecture-relevant subset:

| Table | Purpose | Notable columns |
|---|---|---|
| `servers` | Central aggregate | `root_path`, `launch_config_json`, `missing_since`, `deployment_start_time`, `external_id` |
| `backup_jobs` | Backup metadata | `storage_path`, `checksum`, `backup_type`, `status` |
| `backup_policies` | Retention/schedule | retention days, max backups |
| `plugins` | Plugin registry cache | `filename`, `source`, `pending_deletion`, Modrinth provenance |
| `users` / `roles` / `user_roles` | Identity + RBAC | password_hash (Argon2id), permissions (Text) |
| `api_keys` / `refresh_tokens` | Credentials | `key_hash`/`token_hash` (SHA-256) |
| `event_store` | Append-only event log | hash chain columns |
| `dead_letter_events` | Failed events | replay metadata |
| `metric_points` / `alert_rules` | Monitoring | TPS, players, RAM, CPU |
| `idempotency_keys` / `feature_flags` / `circuit_breaker_states` | Infrastructure | — |
| `saga_instances` / `saga_steps` | Saga orchestration | — |
| `task_queue` / `cron_jobs` | Scheduling | cron expressions, task name |
| `health_status` / `health_timeline` / `health_evidence` / `health_diagnostics` | Health engine | — |
| `pending_restores` | Restore queue | deferred restores |

### 5.4 What Redis is *supposed* to do vs. what runs

| Claimed (docs) | Reality |
|---|---|
| Redis cache | Not used. No Redis cache exists. |
| Arq/Redis task queue | `ArqQueue` defined in `tasks/arq_queue.py`, **never instantiated or wired**. `aredis` isn't a declared dependency, so importing it would fail. Runtime always uses `InProcessQueue`. |
| Redis pub/sub for events | Not used. Events flow through the in-process `EventBus`. |

Phase 6 explicitly asks whether `ArqQueue` and the Redis story should be **implemented, removed, or
formally declared a non-goal** rather than remaining half-documented (§06).

### 5.5 Migration strategy

Alembic with async engine (`alembic/env.py:34`). 16 revisions at time of verification
(2026-08-04), head `c4d5e6f7a8b9`. The production DB (`backend/data/servers/mcs.db`) is **3
revisions behind head** (K9) — see Phase 3. A documented fresh-clone bug (9 ORM-only tables never
migrated) was fixed with idempotent migrations; replay against pre-migration backup is
column-for-column identical (see `docs/DATABASE.md` §Migration Guide).

---

## 6. Runtime Model & OS Interaction

### 6.1 Server providers (Strategy pattern)

`ServerProvider` ABC (`modules/server/infrastructure/providers/base.py`) abstracts OS-level server
lifecycle. Implementations:

| Provider | `provider_type` | Mechanism |
|---|---|---|
| `LocalLinuxProvider` | `local` | tmux sessions, process-tree JVM PID resolution |
| `LocalWindowsProvider` | `local_windows` | PowerShell background jobs |
| `DockerProvider` | `docker` | `itzg/minecraft-server` image, `docker create/start/stop` |
| `SSHProvider` | `ssh` | remote tmux via asyncssh, connection pooling |
| `CloudProvider` (abstract) + `CloudProviderStub` | `cloud` | VM provisioning (AWS/GCP/Azure/DO/Hetzner); `start/stop` raise `NotImplementedError` |

`ProviderFactory` is a registry singleton (`providers/__init__.py`); `CircuitBreakerProviderWrapper`
wraps any provider with the circuit breaker (5 failures, 30s cooldown by default).

**JVM PID resolution.** tmux's pane PID is the wrapper shell, not the Java process.
`LocalLinuxProvider._resolve_server_pid()` walks the process tree (up to 4 levels via
`ps -o pid=,ppid=,comm= --ppid`) and returns the first `java` descendant; falls back to pane PID if
none found. This is what makes metrics/RAM/CPU reflect the real server rather than a near-empty
shell.

### 6.2 Filesystem reconciliation (disk = truth)

`FilesystemReconciliationService` (`server/application/services/filesystem_reconciliation.py`),
6-stage pipeline:

1. **FilesystemScanner** — list directories only.
2. **IdentityReader** — read/validate `.mcsmanager/server.json` (every dir gets a UID, even
   non-Minecraft).
3. **MinecraftDetector** — `scan_server_directory()` with `ScanCategory` (MINECRAFT_VALID /
   MINECRAFT_BROKEN / NOT_MINECRAFT / SCAN_FAILED).
4. **ReconciliationPlanner** — pure logic, builds a `Plan`, no I/O.
5. **TransactionExecutor** — write identity **first** (write-ahead), then DB writes.
6. **IdentityWriter** — called during execution, not post-commit.

**Properties:** identity belongs to the directory, not the server (renaming folders is safe);
identity files written *before* each DB write (write-ahead — a failure rolls back cleanly and the
next run is idempotent); self-healing for corrupted identity files; two-pass deletion via
`mark_missing()`/`missing_since` (prevents data loss on transient moves); `dry_run` support;
servers deployed outside `data/servers/` skipped.

**Runs:** at application startup (after runtime reconciliation) and via
`POST /api/v1/servers/refresh?dry_run=true`.

### 6.3 RuntimeSupervisor (per-server watchdog)

`RuntimeSupervisor` (created via `start_for()` after a server launch):

- `_verify_startup()` — polls `provider.wait_ready()` (log line `Done (`) until deadline (120s
  default); process dies → collect diagnostics → `_handle_crash()` with `failure_code=STARTUP_TIMEOUT`.
- `_health_check()` every 5s — `provider.verify_process()`; dead process with non-STOPPED status →
  `RUNTIME_PROCESS_LOST` → `_handle_crash()`.
- `_handle_crash()` — suppression check (stop requested?), log diagnostics, tmux cleanup, persist
  `server.crash(...)`, fire `_on_crash` callback, stop the loop.
- Class-level `_instances` registry prevents duplicate supervisors; `stop_for()`/`get_for()`
  support command lookup.

### 6.4 Runtime ownership & orphan cleanup

`reconcile_orphans(scope="project_owned")` kills stale OS resources **only** if ownership is proven:

1. **`MCS_MANAGED=1` env marker** on the process (spawned by `LocalLinuxProvider`).
2. **cwd inside `MCS_SERVERS_DATA_DIR`** (`/proc/{pid}/cwd`).
3. **DB cross-reference** + `deployment_start_time` comparison (PID-reuse protection).

Any check that cannot complete with certainty → **skip** (fail-safe). `scope="system_wide"` is the
legacy kill-by-heuristic mode, available only via explicit API call. Every decision logs a
`KILL_DECISION` structured line. This is what guarantees startup never kills an untracked real
Minecraft server (ADR-0011).

### 6.5 Task queue & scheduler

- `TaskQueue` ABC with `InProcessQueue` (SQLite-backed `task_queue` table, `asyncio.ensure_future`)
  and `ArqQueue` (defined, unused).
- `Scheduler` loads `cron_jobs` from DB into APScheduler; `add_job()` persists + schedules.
- Wired **only** in `main.py` lifespan: queue → registered handlers → `init_task_queue` →
  `reclaim_pending()` (reclaims tasks orphaned by restart) → `mark_stale_running_failed()` →
  `MetricsCollector` → `scheduler.start()` → idempotent cron registration
  (`metrics_collect_every_60s`).
- **Vulnerability:** this wiring is the only place these systems are created. Removing it silently
  kills metrics and scheduling (ADR-0006 post-hoc finding). Phase 6 must make this resilient.

### 6.6 WebSocket layer

Files: `websocket/` — `manager.py` (registry), `authentication.py`, `authorization.py`, `endpoint.py`,
`dispatcher.py`, `handlers.py`, `serializers.py`, `buffer.py`, `rate_limiter.py`.

**Working today:**
- Handshake validates the JWT **before** `accept()` (`endpoint.py:51-62`); invalid → WS close 1008.
- `ConnectionManager` registry guarded by `asyncio.Lock` (ADR-0004).
- Message serialization/deserialization, offline message buffer, WS rate limiter (50 msg/s).
- Frontend client with auto-reconnect/backoff, ping keepalive, message queue flush, channel
  resubscribe — fully implemented.

**Broken today (Phase 3 must-fix):**
- **K1** — `CHANNEL_PATTERNS` requires *plural* permission strings (`servers:read`, `backups:read`),
  but JWT/api-key claims carry *singular* REST permissions (`server:read`). `set() is subset` fails
  for every real claim set, and `admin:full` is in no required set. Every `subscribe` is denied —
  fail-closed but dead.
- **K2** — `EventDispatcher` and `MetricsBatcher` are never instantiated in production. There is no
  event-bus subscription, so no domain event ever reaches a client, even with a valid subscription.
- Secondary gaps (see `docs/PERMISSIONS_FUTURE_IDEAS.md` §4): `refresh_token` accepts any non-empty
  string without validation; idle timeout defined but never invoked; dispatcher never re-checks
  authorization per pushed message; expiry set to `now + 3600` regardless of the 900s access-token
  TTL.

**Channel auth model (intended).** Channel patterns map to permissions:
`server:*`/`server:{id}` → `servers:read`, `server:{id}:console` → `servers:console`, etc. The
frontend channel manager validates prefixes (`server`/`backup`/`plugin`/`monitoring`/`metrics`/
`health`/`auth`/`user`), max 50 channels.

**Frontend bridge.** `WebSocketManager` maps WS `onCacheUpdate` keys to TanStack Query keys
(`"servers:list"` → `["servers","list"]`, etc.). Invalidation events derive from domain event types.

### 6.7 Rate limiting

`RateLimitMiddleware` — in-memory sliding window keyed by **`client_ip:path`**, 60 req/min, returns
429 with `Retry-After: 60`. No `X-RateLimit-*` headers, not per-route configurable. WS rate limiter:
50 msg/s per connection. **Already per-client** (corrects an earlier "process-global" claim).

---

## 7. API Layer

### 7.1 Middleware stack (order matters)

```
RequestIDMiddleware → AuthMiddleware → AuditMiddleware → RateLimitMiddleware
```

- **RequestID** — attaches `X-Request-ID`; propagated to logs and error responses.
- **Auth** — parses Bearer JWT / API key; writes `request.state.user`, `request.state.permissions`;
  allows a small public allow-list (login, refresh, users POST, health, metrics, docs).
- **Audit** — records mutating requests to the audit log (hash-chained).
- **RateLimit** — per `client_ip:path`.

### 7.2 Routers (11 as of 2026-08-06)

`auth`, `backups`, `health`, `marketplace`, `monitoring`, `plugins`, `schedules`, `servers`,
`settings`, `software`, `users` — plus the WebSocket router. Phase 0 in `04-...` carries the live
counts; note that `marketplace.py` (global `GET /api/v1/marketplace/search`, K5) is newer than the
earlier 10-router counts.

### 7.3 Error contract

`{ code, message, details, request_id, retryable, documentation_url }` (defined in
`contracts/api.yaml` and enforced by `api/errors.py`). Status mapping: `VALIDATION_ERROR` → 422,
`NOT_FOUND` → 404, `PERMISSION_DENIED` → 403, `UNAUTHORIZED` → 401, domain errors → 4xx per code,
unexpected → 500. DELETE endpoints return 204 (no body). Route-count introspection requires forcing
`app.openapi()` for lazy `_IncludedRouter` materialization (FastAPI 0.139 quirk) — relevant to the
Phase 4/6 route-coverage CI check.

### 7.4 OpenAPI

`backend/openapi.json` generated from the app. `docs/API.md` is the maintained reference.

---

## 8. Frontend Architecture

### 8.1 Stack

React 19, TypeScript 5 (strict), Vite 5, TailwindCSS 4 (raw components, **no shadcn/ui** — an
intentional dependency-avoidance decision), TanStack Query 5 (server data), Zustand 5 (UI state),
React Router v7, custom chart components (no chart library).

### 8.2 State layers

| Layer | Responsibility |
|---|---|
| TanStack Query | Server data; centralized query keys in `services/queryClient.ts`; default `staleTime: 10s`, `retry: 1`, `refetchOnWindowFocus: false` |
| Zustand | Client-only state: `authStore` (tokens in localStorage `mcs_auth`), `uiStore` (theme `mcs_theme`), `wsStore` (WS connection state) |
| Local component state | Selected server in marketplace page, forms |

### 8.3 API client

`services/api.ts` — typed fetch wrapper: Bearer injection, automatic refresh on 401
(deduplicated via a `refreshing` promise guard), `ApiError` with status/code/message/detail.

### 8.4 WebSocket client

Fully implemented client: `wss://<host>/ws?token=<jwt>`, reconnect backoff (1s→30s, max 10),
30s ping, message queue flush on reconnect, channel resubscribe. **Behaviorally non-functional
against the current backend** (K1/K2) — a Phase 2/3 concern (§04/§05). The `metrics` snapshot
ordering contract: `GET /monitoring/metrics` returns newest-first; consumers must pick the max
`timestamp`, never `[length - 1]` (fixed with regression coverage in
`ServerMetricsCharts.test.tsx`).

### 8.5 Pages/routes

`/login`, `/register`, and guarded: `/` (Dashboard), `/servers`, `/servers/create`,
`/servers/import`, `/servers/:serverId`, `/backups`, `/plugins`, `/plugins/marketplace`,
`/marketplace` (K5, top-level), `/settings`, `/settings/api-keys`. Sidebar:
Dashboard / Servers / Backups / Plugins / **Marketplace** / Settings. AuthGuard wraps authenticated
routes.

---

## 9. Security Architecture (summary; see `docs/SECURITY.md`)

| Concern | Mechanism | Status |
|---|---|---|
| Password | Argon2id | Implemented |
| Access token | RS256 JWT, 15 min | Implemented (ephemeral keys — K11) |
| Refresh token | Opaque, SHA-256 hash, rotation, revocable | Implemented |
| API key | `mcs_` + SHA-256 (unsalted) | Implemented |
| Authorization | RBAC+ABAC `require_permission` | **Partially enforced** (24 routes; 9 mutating + 23 GET gaps — Phase 4) |
| WS auth | JWT before accept + channel gate | Handshake works; channel gate always denies (K1) |
| Audit | SHA-256 hash chain | Implemented; no scheduled verify; no query endpoint |
| Backups at rest | AES-256-GCM | Implemented |
| TLS | TLS 1.3 at reverse proxy | Deployment-level |
| Rate limiting | `client_ip:path` in-memory, 60/min | Implemented |
| `/metrics` | Public | Deliberately public (K10, deferred) |

---

## 10. Cross-Cutting Concerns

### 10.1 Circuit breaker

`CircuitBreaker` wraps provider calls (and other external boundaries). States
closed/open/half-open persisted in `circuit_breaker_states`. `call_factory` supports lazy coroutine
creation. Default 5 failures, 30s cooldown via `CircuitBreakerProviderWrapper`.

### 10.2 Idempotency

`idempotency.py` + `idempotency_keys` table (24h TTL). Applied at the command bus. Duplicates return
the cached result rather than re-executing. This protects against client retries on flaky networks
(especially relevant once Phase 7 exposes the API to the internet).

### 10.3 Feature flags

`feature_flags.py` + tables (`feature_flags`, `feature_flag_overrides`) — boolean + percentage
rollout, per-user overrides. Used for rolling out risky behavior without redeploys.

### 10.4 Structured logging

`core/logging.py` (structlog-style, with the Python 3.14 keyword-args caveat recorded in Batch 1).
`X-Request-ID` correlation; `KILL_DECISION`, `Event moved to dead letter queue`, and cron-wiring
lines are the important operational signals.

---

## 11. Failure Modes & Recovery — the patterns inventory

| Failure | Detection | Recovery | Owner |
|---|---|---|---|
| Server crash | RuntimeSupervisor health check | Crash diagnostics + health recovery orchestration (3/300s cap) | `health` |
| Server start timeout | `_verify_startup` deadline | Diagnostics + `_handle_crash` | `server`/`health` |
| Provider unavailable | Circuit breaker open | Calls fail fast; UI surfaces provider status | `server`/`monitoring` |
| Backup save-world timeout | `_save_world` 30s poll | Job `FAILED` | `backup` |
| Restore cross-device move | `os.replace` EXDEV | **Prevented** by same-FS staging (ADR-0012) | `backup` |
| Event handler failure | EventBus retry (3×backoff) | Dead-letter queue + manual replay | `event_store` |
| Plugin install checksum mismatch | SHA-1/SHA-512 verify | Install refused | `plugin` |
| Stale server dir (transient) | First-pass `mark_missing()` | Second-pass delete; grace period | `server` |
| Orphan OS resources | Ownership-verified reconcile | Kill only on proven ownership | `server` |
| SQLite lock contention | `database is locked` | Preflight script kills stale processes | ops |
| Queue orphaned by restart | `reclaim_pending()` at boot | Re-queue PENDING, fail stale RUNNING | `tasks` |
| Metrics collector silently dead | Cron rows stop growing | Wiring is in one place (main.py) — Phase 6 hardens | `tasks` |
| WS delivery dead | (K1/K2) | Phase 3 wiring | `websocket` |

---

*Continue to [`03-engineering-standards.md`](./03-engineering-standards.md) for coding standards,
ADR process, testing philosophy, and non-functional requirements.*
