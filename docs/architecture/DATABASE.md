# Database Architecture

## Technology

| Component | Choice |
|---|---|
| Primary database | SQLite 3 (`aiosqlite` async) default (`backend/data/onx.db`); PostgreSQL 16 (`asyncpg`) supported |
| Cache | Redis 7 (declared in docs; **not used in the running system** — see note) |
| ORM | SQLAlchemy 2.0 async (repository pattern) |
| Migrations | Alembic (53 revisions, head `b1e2100000033`, floor `b1e2100000033`) |
| Pre-Backend Reconciler | `backend/app/core/persistence/reconciler.py` (ACID backups & migration gate) |
| Embedded mode | SQLite 3 (fallback via config) |

> **Task queue note:** The runtime exclusively uses `InProcessQueue`. The legacy
> unused Arq/Redis queue (`tasks/arq_queue.py`) was removed and
> the `aredis` dependency eliminated. There is no Redis requirement, cache, or pub/sub.

Connection pooling: 20 pool size, 10 max overflow, `pool_pre_ping=True` for PostgreSQL. SQLite mode skips pooling. See `backend/app/core/persistence/db.py`.

The `DatabaseEngine` class (`backend/app/core/persistence/db.py:16`) wraps `create_async_engine` and provides an `async_sessionmaker`. Sessions are injected via FastAPI `Depends(get_db)`.

## Schema Design

```
schemas/
├── public    # Default schema — all transactional tables
├── audit     # (reserved) Immutable audit log, no UPDATE/DELETE
└── reporting # (reserved) Materialized views, analytics
```

## Key Tables

### Servers

`servers` — `backend/app/modules/server/infrastructure/models.py:11`

The central aggregate. Each row represents a single Minecraft server instance with its runtime configuration, deployment target, and state.

| Column | Type | Default | Notes |
|---|---|---|---|
| `id` | `String(36)` PK | — | UUID |
| `name` | `String(255)` | — | |
| `server_type` | `String(32)` | `"vanilla"` | vanilla, paper, purpur, fabric, forge, neoforge, spigot |
| `minecraft_version` | `String(16)` | — | |
| `memory_min_mb` | `Integer` | 1024 | |
| `memory_max_mb` | `Integer` | 2048 | |
| `group_id` | `String(64)` | `"default"` | Logical grouping |
| `status` | `String(32)` | `"created"` | created → installing → stopped → running (widened to String(32) in `b1e2100000008`) |
| `port` | `Integer` | 25565 | |
| `provisioning_error` | `Text` | `None` | Nullable error summary when status is `provisioning_failed` |
| `provisioning_retryable` | `Boolean` | `False` | True if transient error is auto-retryable |
| `motd`, `max_players`, `gamemode`, `difficulty`, `pvp`, etc. | varied | — | Direct server.properties mapping |
| `provider` | `String(32)` | `"docker"` / `"local"` | `docker` (sole active local runtime); `local`, `local_windows` (legacy/migrated), `remote` |
| `location_type` | `String(16)` | `"local"` | Filesystem placement |
| `root_path`, `working_directory`, `startup_jar`, `startup_command` | varied | — | Deployment paths |
| `launch_config_json` | `Text` | nullable | Full launch config snapshot |
| `uptime_seconds` | `Float` | 0 | |
| `running_start_time` | `Float` | nullable | Timestamp (epoch float) when server entered running state (`b1e2100000009`) |
| `cpu_cores` | `Integer` | 0 | Max logical processors (0 = unconstrained; `b1e2100000010`) |
| `cpu_affinity` | `String(64)` | `""` | Core affinity string (e.g. "0-3"; `b1e2100000010`) |
| `external_id` | `String(255)` | nullable | Cloud provider instance ID |
| `missing_since` | `DateTime` | nullable | When server dir was detected missing (two-pass deletion) |

Server config properties (motd, difficulty, etc.) map to `server.properties` fields. The `server_type` column was added in migration `5a50140d37df`; deployment columns in `003`; `launch_config_json` in `fcc7545db19e`; `external_id` in `902b076bfa36`; `missing_since` in `a1b2c3d4e5f6`; `running_start_time` in `b1e2100000009`; `cpu_cores` and `cpu_affinity` in `b1e2100000010`.

`server_lifecycle_leases` — `backend/app/modules/server/infrastructure/models.py:99`

Serializes multi-worker server lifecycle transitions (start, stop, promote) to prevent race conditions (`b1e2100000023`).

| Column | Type | Notes |
|---|---|---|
| `server_id` | `String(36)` PK | Scoped to individual server |
| `holder` | `String(128)` | Process/worker identification |
| `owner_token` | `String(64)` | Secret token for lease renewal and safe release |
| `acquired_at` | `DateTime(timezone=True)` | Timestamp acquired |
| `expires_at` | `DateTime(timezone=True)` | Timestamp expiration (heartbeat renewed) |
| `updated_at` | `DateTime(timezone=True)` | Last lease update |

### Backups

`backup_jobs` — `backend/app/modules/backup/infrastructure/models.py:8`

| Column | Type | Notes |
|---|---|---|
| `id` | `String(36)` PK | UUID |
| `server_id` | `String(36)` | Indexed (no FK constraint in model) |
| `backup_type` | `String(16)` | full, world, plugins |
| `status` | `String(16)` | pending, running, completed, failed |
| `size_bytes` | `Integer` | |
| `checksum` | `String(64)` | SHA-256 |
| `storage_path` | `String(512)` | Filesystem or remote path |

`backup_policies` — schedule, retention days, encryption toggle, max backups per server.

### Users & Auth

`users` — `backend/app/modules/auth/infrastructure/models.py:9`

| Column | Type | Notes |
|---|---|---|
| `id` | `String(36)` PK | UUID |
| `email` | `String(255)` | Unique |
| `password_hash` | `String(512)` | |
| `display_name` | `String(128)` | |
| `is_active` | `Boolean` | Soft disable |
| `last_login_at` | `DateTime` | |

Supporting tables:

- **`roles`** — RBAC roles with permission text field
- **`user_roles`** — many-to-many join table
- **`api_keys`** — machine credentials; `key_hash` stored as **SHA-256** via `hash_api_key()` (`backend/app/core/security.py:44`) — unsalted; prefix (`mcs_`) for display
- **`refresh_tokens`** — JWT refresh token tracking; `token_hash` stored as SHA-256; revocable
- **`server_memberships`** — server-scoped RBAC membership (`server_id`, `user_id`, `role` in `admin`/`dev`/`viewer`); FK to `servers`, FK to `users`, created by migration `5e2962848581`
- **`system_state`** — singleton instance row (`id` default `"default"`, `initialized`, `access_mode` `LOCAL`/`GLOBAL`); created by migration `a957791492a7`
- **`invitations`** — invitation tokens: `token_hash` (SHA-256, unique, indexed), `token_prefix` (for display), `creator_id` (FK `users`, SET NULL), `email` (nullable, indexed), `global_role` (default `member`), `server_id`/`server_role` (nullable; FK `servers` CASCADE), `status` (`ACTIVE`/`USED`/`REVOKED`/`EXPIRED`, default `ACTIVE`), `max_uses` (default 1), `use_count` (default 0), `expires_at`, `used_at`; created by migration `a957791492a7`

### Audit Log / Event Store

`event_store` — `backend/app/modules/event_store/models.py:8`

Append-only event log with cryptographic chain integrity.

| Column | Type | Notes |
|---|---|---|
| `id` | `Integer` PK | Auto-increment |
| `event_id` | `String(36)` | Unique, UUID |
| `event_type` | `String(128)` | Indexed |
| `correlation_id` | `String(36)` | Indexed, for traceability |
| `data_json` | `Text` | Full event payload |
| `schema_version` | `Integer` | Default 1 |
| `previous_hash` | `String(64)` | SHA-256 of the preceding row |
| `hash` | `String(64)` | SHA-256 of `(previous_hash + event_id + event_type + data_json + created_at)` |

No UPDATE, no DELETE — enforced at application layer. The hash chain is computed as:

```
hash = SHA-256(previous_hash + event_id + event_type + data_json + created_at_iso)
```

Integrity is verified by replaying the hash chain. Retention: 1 year (partitioned by month).

`dead_letter_events` — events that exhausted retry attempts (3 tries with backoff). Tracks `replay_count`, `last_replay_at`, and `resolved` status (migration `002`).

### Plugin Registry

`plugins` — `backend/app/modules/plugin/infrastructure/models.py:8`

| Column | Type | Notes |
|---|---|---|
| `id` | `String(36)` PK | |
| `server_id` | `String(36)` | Indexed |
| `name`, `version`, `author` | varied | Manifest fields |
| `dependencies` | `Text` | JSON list of dependent plugin IDs |
| `status` | `String(16)` | installed, enabled, disabled, error |
| `filename` | `String(255)` | On-disk `.jar` filename (filesystem reconciliation key) |
| `source` | `String(16)` | `manual`, `upload`, `detected` (found on disk), or `modrinth` (marketplace) |
| `external_project_id`, `external_version_id`, `external_url`, `checksum` | varied | Modrinth provenance for marketplace-installed plugins |
| `pending_deletion` | `Boolean` | Deferred deletion — file removed on next server start/restart |

> The `filename`/`source`/`pending_deletion` and Modrinth-provenance columns were
> added by migrations `3a42d373bb05` and `c4d5e6f7a8b9` (2026-08-04, plugin
> filesystem-tracking + marketplace work). See `docs/architecture/plugins-and-marketplace.md`.

### Monitoring

`metric_points` — `backend/app/modules/monitoring/infrastructure/models.py:8`

Time-series data for server performance: `tps`, `players`, `ram_used_mb`, `cpu_percent`. Indexed by `server_id`. Supports sliding-window chart queries.

`alert_rules` — threshold-based alerting per server per metric: condition (`>`, `<`, `>=`, `<=`), threshold, severity, cooldown. `updated_at` added in migration `a2b2c3d4e5f7`.

### Versioning & Enterprise Branch Runtime

`backend/app/modules/versioning/infrastructure/models.py`

Introduced in Stages A–G and Phase 5.5 (`b1e2100000013` through `b1e2100000022`) to support Git-inspired version control, filesystem worktrees, admission control, operations, and isolated test runs:

- **`server_branches`** — Server branches with lifecycle tracking and protection policies.
  - Columns: `id` (PK), `server_id` (indexed), `name`, `head_commit_id`, `status` (`created`, `active`, `archived`), `is_protected` (bool), `protection_policy` (JSON: `require_test_pass`, `allow_direct_commit`, `allow_force_bypass`, `prevent_deletion`), `created_at`.
  - Unique constraint: `(server_id, name)`.
- **`server_commits`** — Immutable commit snapshots.
  - Columns: `id` (PK), `server_id` (indexed), `branch_id`, `parent_commit_id`, `author_id`, `message`, `manifest_json`, `world_snapshot_id`, `created_at`.
- **`server_commit_parents`** — Commit DAG parent junction table (`b1e2100000015`).
  - Columns: `commit_id` (PK, indexed), `parent_commit_id` (PK, indexed), `parent_index` (int). Supports multi-parent merge commits and graph traversal with cycle detection.
- **`server_tags`** — Immutable symbolic tags (`b1e2100000015`).
  - Columns: `id` (PK), `server_id` (indexed), `name`, `commit_id` (indexed), `created_at`.
  - Unique constraint: `(server_id, name)`.
- **`server_materializations`** — Filesystem worktrees on disk (`b1e2100000016`).
  - Columns: `id` (PK), `server_id` (indexed), `commit_id` (indexed), `root_path`, `status` (`pending`, `ready`, `stale`, `removed`), `mode` (`readonly`, `edit`), `revision`, `path_classification` (JSON), `created_at`.
- **`server_import_reviews`** — Live filesystem changes review aggregate (`b1e2100000016`).
  - Columns: `id` (PK), `server_id` (indexed), `commit_id` (indexed), `parent_commit_id`, `branch_name`, `status` (`pending`, `confirmed`, `dismissed`, `reverted`), `changes` (JSON), `revert_commit_id`, `created_at`, `updated_at`.
- **`server_admission_lease`** — Concurrency & memory admission gate serialization (`b1e2100000017`).
  - Columns: `id` (PK, singleton CheckConstraint `id = 1`), `holder`, `acquired_at`.
- **`server_test_definitions`** — Reusable test run configurations (`b1e2100000018`).
  - Columns: `id` (PK), `server_id` (FK `servers.id`), `name`, `description`, `server_type`, `bot_technology`, `bot_count`, `duration_seconds`, `join_stagger_seconds`, `connect_grace_seconds`, `placement_mode`, `assertion_rules` (JSON), `timeout_seconds`, `created_at`, `updated_at`.
- **`server_runtimes`** — 1:1 container/process execution binding (`b1e2100000018`).
  - Columns: `id` (PK), `server_id` (FK `servers.id`), `commit_id` (FK `server_commits.id`), `materialization_id`, `provider_type`, `container_id`, `pid`, `port`, `status` (`starting`, `running`, `stopped`, `crashed`), `exit_code`, `oom_killed`, `started_at`, `stopped_at`, `created_at`.
- **`server_test_runs`** — Test run executions.
  - Columns: `id` (PK), `server_id` (indexed), `commit_id` (indexed), `node_id`, `status`, `ephemeral_port`, `log_output`, `failure_reason`, `bot_count`, `duration_minutes`, `placement_mode`, `bot_tech`, `reserved_ram_mb`, `reserved_cores`, `runtime_id` (FK `server_runtimes.id`), `test_definition_id` (FK `server_test_definitions.id`), `operation_id` (FK `operations.id`, `b1e2100000022`), `evidence_bundle` (JSON), `artifacts_purged` (bool), `created_at`, `expires_at`.

### Operations Subsystem

`backend/app/modules/operations/infrastructure/models.py`

Introduced in Phase 5.5 (`b1e2100000021`) for persistent, multi-step asynchronous operation tracking:

- **`operations`** — Top-level asynchronous operations (e.g. provisioning, test run pipelines).
  - Columns: `id` (PK), `type` (indexed), `target_type`, `target_id`, `actor_id`, `status` (indexed), `idempotency_key`, `current_step_id`, `last_event_seq`, `failure_code`, `error_message`, `cancellation_requested`, `timeout_seconds`, `created_at` (indexed), `started_at`, `finished_at`, `metadata_json`.
  - Indexes / Constraints: `(target_type, target_id)`, unique constraint `(target_type, target_id, idempotency_key)`.
- **`operation_steps`** — Individual step status and logs within an operation.
  - Columns: `id` (PK), `operation_id` (FK `operations.id`), `sequence` (int), `name`, `status`, `started_at`, `finished_at`, `error_code`, `error_message`, `result_json`.

### Exposure Subsystem

`backend/app/modules/exposure/infrastructure/models.py`

Introduced in `b1e2100000001` through `b1e2100000006`:

- **`host_playit_agent`** — Single-row host agent credential and claim state.
- **`panel_exposure`** — Web panel exposure method (Cloudflare, Playit, port forward).
- **`server_exposure`** — Per-server exposure configuration.
- **`server_exposure_target`** — Forwarding targets mapping local service ports to public tunnels.
- **`server_exposure_grants`** — Server exposure RBAC permissions (`id`, `server_id` FK, `user_id` FK, `can_manage`, `can_view`, unique `(server_id, user_id)`).
- **`server_registered_ports`** — Registered companion ports (`id`, `server_id` FK, `service_type`, `protocol`, `port`, `name`).

### Infrastructure Tables

| Table | Purpose |
|---|---|
| `idempotency_keys` | Deduplication — 24h TTL, stores result JSON |
| `feature_flags` | Boolean toggle + percentage rollout |
| `feature_flag_overrides` | Per-user override for flag values |
| `circuit_breaker_states` | Per-circuit state (closed/open/half-open), failure count, timestamps |
| `saga_instances` | Saga orchestration: type, status, current step, timeout |
| `saga_steps` | Per-step: index, name, status, error |
| `task_queue` | Delayed/background task execution with status tracking |
| `cron_jobs` | Scheduled task definitions with cron expressions |

## Entity-Relationship Summary

```
servers 1──* backup_jobs
servers 1──* plugins
servers 1──* metric_points
servers 1──* alert_rules
servers 1──* server_memberships   (user_id + server_id + role)
servers 1──* server_branches
servers 1──* server_commits
servers 1──* server_tags
servers 1──* server_materializations
servers 1──* server_import_reviews
servers 1──* server_test_definitions
servers 1──* server_runtimes
servers 1──* server_test_runs
users   1──* api_keys
users   1──* refresh_tokens
users   *──* roles        (via user_roles)
users   1──* server_memberships
users   1──* invitations   (issued invitations; token_hash unique)
servers 1──0..* invitations (server_id nullable, for server-scoped invites)
server_commits 1──* server_commit_parents
server_runtimes 1──0..1 server_test_runs
server_test_definitions 1──* server_test_runs
```

## Migration Strategy

Alembic with async engine (`backend/alembic/env.py:34`). All models register on `Base.metadata`.

```bash
cd backend
alembic revision --autogenerate -m "description"
alembic upgrade head
alembic downgrade -1
```

**Migration history:**

| Revision | Parent | Description |
|---|---|---|
| `001` | — | Initial schema: idempotency, feature flags, circuit breakers, saga tables, event store, dead letter |
| `002` | `001` | task_queue, cron_jobs, metric_points, alert_rules; hash chain columns on event_store |
| `16f9e2a1f2d6` | `002` | users table |
| `003` | `16f9e2a1f2d6` | Deployment columns on servers (location, paths, uptime) |
| `5a50140d37df` | `003` | server_type column on servers |
| `ff9c2b3a8e4d` | `5a50140d37df` | updated_at on metric_points |
| `fcc7545db19e` | `ff9c2b3a8e4d` | launch_config_json on servers |
| `902b076bfa36` | `fcc7545db19e` | external_id on servers |
| `876be46160d3` | `902b076bfa36` | ORM-only tables (servers*, api_keys, audit_log, etc.) |
| `876be46160d4` | `876be46160d3` | Health tables (health_status, timeline, evidence, diagnostics) |
| `a1b2c3d4e5f6` | `876be46160d4` | missing_since on servers |
| `a2b2c3d4e5f7` | `a1b2c3d4e5f6` | updated_at on alert_rules |
| `a3b2c3d4e5f6` | `a2b2c3d4e5f7` | deployment_start_time on servers (ownership verification) |
| `b5c6d7e8f9a0` | `a3b2c3d4e5f6` | pending_restores table |
| `3a42d373bb05` | `b5c6d7e8f9a0` | Modrinth source columns on plugins (external ids, url, checksum) |
| `c4d5e6f7a8b9` | `3a42d373bb05` | Plugin filesystem-tracking columns (filename, source, pending_deletion) |
| `784b5ba72077` | `c4d5e6f7a8b9` | `project_type` on plugins |
| `989743c08820` | `784b5ba72077` | `icon_url` on plugins |
| `5e2962848581` | `989743c08820` | **Server ownership/memberships** — `owner_id` FK on servers; `server_memberships` table |
| `a957791492a7` | `5e2962848581` | **System state & invitations** — `system_state`, `invitations` tables |
| `b1e2100000001` | `a957791492a7` | Exposure subsystem tables — `host_playit_agent`, `server_exposure`, `server_exposure_target`, `panel_exposure` |
| `b1e2100000002` | `b1e2100000001` | Panel Cloudflare columns (token, tunnel id, bind host/port) |
| `b1e2100000003` | `b1e2100000002` | Panel Playit/UPnP columns (`external_port`, `playit_tunnel_id`, `upnp_last_result`, `upnp_last_mapped_at`) |
| `b1e2100000004` | `b1e2100000003` | Server Cloudflare columns |
| `b1e2100000005` | `b1e2100000004` | `server_registered_ports` table |
| `b1e2100000006` | `b1e2100000005` | `server_exposure_target.playit_tunnel_id` |
| `b1e2100000007` | `b1e2100000006` | `metric_points.tps` nullable |
| `b1e2100000008` | `b1e2100000007` | `provisioning_error` & `provisioning_retryable` on servers |
| `b1e2100000009` | `b1e2100000008` | `running_start_time` on servers |
| `b1e2100000010` | `b1e2100000009` | `cpu_cores` and `cpu_affinity` on servers |
| `b1e2100000011` | `b1e2100000010` | Hash chain unique constraints on `event_store` |
| `b1e2100000012` | `b1e2100000011` | Custom mod support columns on `servers` |
| `b1e2100000013` | `b1e2100000012` | Initial versioning tables: `server_branches`, `server_commits`, `server_test_runs`, `server_world_snapshots` |
| `b1e2100000014` | `b1e2100000013` | `server_activity_logs` table |
| `b1e2100000015` | `b1e2100000014` | Stage B: `server_tags`, `server_commit_parents`, `server_branches.status` |
| `b1e2100000016` | `b1e2100000015` | Stage C: `server_materializations`, `server_import_reviews` |
| `b1e2100000017` | `b1e2100000016` | Stage D: `server_admission_lease`, `reserved_ram_mb`, `reserved_cores` on `server_test_runs` |
| `b1e2100000018` | `b1e2100000017` | Stage F: `server_test_definitions`, `server_runtimes`, `runtime_id`, `test_definition_id`, `evidence_bundle`, `artifacts_purged` |
| `b1e2100000019` | `b1e2100000018` | Stage G: `server_branches.is_protected`, `server_branches.protection_policy` |
| `b1e2100000020` | `b1e2100000019` | `server_startup_timeout_seconds` on `servers` |
| `b1e2100000021` | `b1e2100000020` | Phase 5.5 Stage A: `operations` and `operation_steps` tables |
| `b1e2100000022` | `b1e2100000021` | Phase 5.5 Stage B: `operation_id` on `server_test_runs` |
| `b1e2100000023` | `b1e2100000022` | Server Lifecycle Hardening: `server_lifecycle_leases` table — **head** |

### Per-release compatibility floor

The application refuses to start against a database whose schema revision is below
the release minimum — **fail closed**, never auto-upgraded.

| Release | Minimum DB revision |
|---------|---------------------|
| `0.1.0` | `b1e2100000023` (current head) |

- **Authoritative source:** `backend/app/core/persistence/db_revision.py`
  (`RELEASE_MINIMUM_DB_REVISION`).
- **Compatibility algorithm:** ancestry walk over the migration graph (each
  revision's `down_revision`). The DB revision is compatible iff the release
  minimum is reachable from it walking `down_revision` — i.e. the minimum is one
  of its ancestors (or the revision *is* the minimum). Revision ids are graph
  nodes; they are never compared as strings.
- **Allowed:** exact minimum, and any compatible *descendant* revision.
- **Rejected (startup aborts):** missing `alembic_version` table/row, unknown
  revision, revision behind the minimum, multiple/hostile branch revisions.
- **No auto-migration:** this check never runs Alembic. Deployment runs
  `alembic upgrade head` first (see `docs/DEPLOYMENT.md`).
- **Secret safety:** error messages report the revision ids and the minimum, never
  the database URL or credentials.

## Audit Log Implementation

The `event_store` table implements an append-only audit log:

- Inserts only — no application-layer UPDATE or DELETE paths
- Cryptographically chained: each row stores `previous_hash` and its own `hash`
- Periodic integrity verification replays the chain and recomputes hashes
- Partitioned by month for retention management (1-year retention)
- All domain events are persisted here before being dispatched via `EventBus`

The `StoredEventModel` is in `backend/app/modules/event_store/models.py`. Events flow through the `UnitOfWork` — they are collected during a transaction and flushed to the event store before the domain transaction commits.

## Query Patterns

### Base Repository

All domain entities use `BaseRepository[T]` (`backend/app/core/persistence/base.py:31`):

```python
await repo.add(entity)
await repo.get(id) -> T | None
await repo.list(**filters) -> list[T]
await repo.update(entity)
await repo.delete(entity)
```

### Unit of Work

All mutations run inside a `UnitOfWork` context (`backend/app/core/persistence/unit_of_work.py:13`):

```python
async with UnitOfWork(event_bus) as uow:
    repo = uow.get_repo("servers", ServerModel)
    await repo.add(server)
    uow.add_event(DomainEvent(...))
    # commit + publish events on success, rollback + run cleanup on error
```

The UoW collects domain events during the transaction and publishes them to `EventBus` after a successful commit.

### Connection Management

```python
# FastAPI dependency injection
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async for session in database.get_session():
        yield session
```

Config-driven URL: supports both PostgreSQL (`postgresql+asyncpg://...`) and SQLite (`sqlite+aiosqlite:///...`) via `AppSettings.database_url`.

## Migration Guide

### Connection

The application reads the database URL from the `ONX_DATABASE_URL` (or legacy `MCS_DATABASE_URL`) environment
variable. If unset it falls back to `alembic.ini` → `sqlalchemy.url`.

```bash
cd backend
export ONX_DATABASE_URL="sqlite+aiosqlite:///path/to/onx.db"
alembic upgrade head
```

### Migration Chain (chronological)

| Revision | Description |
|----------|-------------|
| `001` | Initial schema |
| `002` | Task scheduling & telemetry tables: task_queue, cron_jobs, metric_points, alert_rules |
| `16f9e2a1f2d6` | Auth users tables |
| `003` | **Deployment columns** on `servers` (location_type, …) |
| `5a50140d37df` | `server_type` on `servers` |
| `ff9c2b3a8e4d` | `updated_at` on `metric_points` |
| `fcc7545db19e` | `launch_config_json` on `servers` |
| `902b076bfa36` | `external_id` on `servers` |
| `876be46160d3` | ORM-only tables: servers*, api_keys, audit_log, backup_jobs, backup_policies, plugins, refresh_tokens, roles, user_roles |
| `876be46160d4` | Health tables: health_status, health_timeline, health_evidence, health_diagnostics |
| `a1b2c3d4e5f6` | `missing_since` on `servers` |
| `a2b2c3d4e5f7` | `updated_at` on `alert_rules` |
| `a3b2c3d4e5f6` | `deployment_start_time` on `servers` |
| `b5c6d7e8f9a0` | `pending_restores` table |
| `3a42d373bb05` | Modrinth source columns on `plugins` |
| `c4d5e6f7a8b9` | Plugin filesystem-tracking columns on `plugins` |
| `784b5ba72077` | `project_type` on `plugins` |
| `989743c08820` | `icon_url` on `plugins` |
| `5e2962848581` | **Server ownership & memberships** — `servers.owner_id` FK; `server_memberships` table |
| `a957791492a7` | **System state & invitations** — `system_state`, `invitations` tables |
| `b1e2100000001` | Exposure subsystem tables (`host_playit_agent`, `server_exposure`, `server_exposure_target`, `panel_exposure`) |
| `b1e2100000002` | Panel Cloudflare columns |
| `b1e2100000003` | Panel Playit/UPnP columns |
| `b1e2100000004` | Server Cloudflare columns |
| `b1e2100000005` | `server_registered_ports` table |
| `b1e2100000006` | `server_exposure_target.playit_tunnel_id` |
| `b1e2100000007` | `metric_points.tps` nullable |
| `b1e2100000008` | `provisioning_error` & `provisioning_retryable` on servers |
| `b1e2100000009` | `running_start_time` on servers |
| `b1e2100000010` | `cpu_cores` and `cpu_affinity` on servers |
| `b1e2100000011` | Hash chain unique constraints on `event_store` |
| `b1e2100000012` | Custom mod support columns on `servers` |
| `b1e2100000013` | Initial versioning tables: `server_branches`, `server_commits`, `server_test_runs`, `server_world_snapshots` |
| `b1e2100000014` | `server_activity_logs` table |
| `b1e2100000015` | Stage B: `server_tags`, `server_commit_parents`, `server_branches.status` |
| `b1e2100000016` | Stage C: `server_materializations`, `server_import_reviews` |
| `b1e2100000017` | Stage D: `server_admission_lease`, `reserved_ram_mb`, `reserved_cores` on `server_test_runs` |
| `b1e2100000018` | Stage F: `server_test_definitions`, `server_runtimes`, `runtime_id`, `test_definition_id`, `evidence_bundle`, `artifacts_purged` |
| `b1e2100000019` | Stage G: `server_branches.is_protected`, `server_branches.protection_policy` |
| `b1e2100000020` | `server_startup_timeout_seconds` on `servers` |
| `b1e2100000021` | Phase 5.5 Stage A: `operations` and `operation_steps` tables |
| `b1e2100000022` | Phase 5.5 Stage B: `operation_id` on `server_test_runs` |
| `b1e2100000023` | Server Lifecycle Hardening: `server_lifecycle_leases` table |
| `b1e2100000024` | `servers.mode` (`simple` / `advanced`) column |
| `b1e2100000025` | `backup_jobs.pinned` column for upgrade rollback protection |
| `b1e2100000026` | `refresh_journals` and `server_repo_leases` tables |
| `b1e2100000027` | `class_c_snapshots` and `server_secrets` tables (AES-256-GCM Class-C & secret vaults) |
| `b1e2100000028` | `server_dynamic_class_c` table (dynamic Class-C path registry) |
| `b1e2100000029` | `server_data_templates` table and P4 branch/port indexes |
| `b1e2100000030` | `server_github_connections` and `github_webhook_deliveries` tables |
| `b1e2100000031` | `server_upgrades`, `loader_env_cache_entries`, `panel_integration_secrets`, and P5.5 upgrade/LEC columns |
| `b1e2100000032` | Two-tier backups: `backup_jobs.tier` column and `ix_backup_jobs_server_tier` index |
| `b1e2100000033` | Make `users.email` nullable for username-only & `local` zero-login authentication (**head**) |

> \* `servers` is created by `003` on a fresh clone; `876be46160d3` is a
> no-op for it when replaying existing history.

### Fresh-clone bug (fixed)

#### Before

`alembic upgrade head` on an empty database failed at migration `003`:

```
sqlite3.OperationalError: no such table: servers
```

Nine tables (`servers`, `api_keys`, `audit_log`, `backup_jobs`,
`backup_policies`, `plugins`, `refresh_tokens`, `roles`, `user_roles`) were
historically created only via `Base.metadata.create_all()` during early
development and were never captured in any migration.

#### After (5-file fix)

| File | Change |
|------|--------|
| `003_add_deployment_columns.py` | Creates `servers` table if absent (all 39 columns); adds deployment columns individually (guarded) if table already exists |
| `5a50140d37df_add_server_type_to_servers.py` | Guards `add_column` with column-existence check |
| `fcc7545db19e_add_launch_config_json_to_servers.py` | Guards `add_column` with column-existence check |
| `902b076bfa36_add_external_id_to_servers.py` | Guards `add_column` with column-existence check |
| `876be46160d3_add_missing_orm_only_tables.py` | **New** — creates 8 ORM-only tables (excluding `servers`), each guarded by `_table_exists()` |

The 4 existing migrations were made **idempotent**: if replayed against a
database that already has the target column/table they silently skip the
redundant operation instead of crashing.  Behavior on already-migrated
databases is unchanged (verified by replay test against a pre-migration
backup — final schema matches production column-for-column).

### Database naming & legacy transition state

- **Primary Database**: `backend/data/onx.db`
- **Legacy Filename**: `mcs.db` was the pre-rename (MCS-Manager) database filename, fully superseded by `onx.db`. No live file with that name exists in the repository as of the cleanup in SPEC-2026-09-14-STRAY-DB-CLEANUP-01.
- **Migration & Auto-copy**: During transition, `DatabaseEngine` in `backend/app/core/persistence/db.py` checks anchored legacy candidates (`backend/data/mcs.db` and `backend/mcs.db`) to migrate existing installations if `onx.db` is missing. Unanchored cwd-relative copy logic has been removed to eliminate footguns, and stray root-level SQLite files are guarded against in CI and pre-push checks (`scripts/check-stray-db`).

## Cross-References

- [Architecture](../architecture/ARCHITECTURE.md) — system context, CQRS, Event Bus, Saga orchestration
- [Architecture](../architecture/ARCHITECTURE.md) — module structure, core infrastructure patterns
- [Development guide](../DEVELOPMENT.md) — setup, migration commands, testing
