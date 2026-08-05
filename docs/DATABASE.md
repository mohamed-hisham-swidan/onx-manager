# Database Architecture

## Technology

| Component | Choice |
|---|---|
| Primary database | PostgreSQL 16 |
| Cache | Redis 7 (declared in docs; **not used in the running system** — see note) |
| ORM | SQLAlchemy 2.0 async (repository pattern) |
| Migrations | Alembic (16 revisions) |
| Embedded mode | SQLite 3 (fallback via config) |

> **Redis note:** Redis appears in the documented stack but the running system
> never uses it. The task queue is in-process (`InProcessQueue`); the Arq/Redis
> queue is defined in code but not wired up or instantiated. There is no Redis
> cache, pub/sub, or presence store. See `docs/ARCHITECTURE.md`.

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
| `server_type` | `String(32)` | `"vanilla"` | vanilla, paper, purpur, fabric, spigot, bukkit, forge |
| `minecraft_version` | `String(16)` | — | |
| `memory_min_mb` | `Integer` | 1024 | |
| `memory_max_mb` | `Integer` | 2048 | |
| `group_id` | `String(64)` | `"default"` | Logical grouping |
| `status` | `String(16)` | `"created"` | created → installing → stopped → running |
| `port` | `Integer` | 25565 | |
| `motd`, `max_players`, `gamemode`, `difficulty`, `pvp`, etc. | varied | — | Direct server.properties mapping |
| `provider` | `String(32)` | `"local"` | local, docker, remote |
| `location_type` | `String(16)` | `"local"` | Filesystem placement |
| `root_path`, `working_directory`, `startup_jar`, `startup_command` | varied | — | Deployment paths |
| `launch_config_json` | `Text` | nullable | Full launch config snapshot |
| `uptime_seconds` | `Float` | 0 | |
| `external_id` | `String(255)` | nullable | Cloud provider instance ID |
| `missing_since` | `DateTime` | nullable | When server dir was detected missing (two-pass deletion) |

Server config properties (motd, difficulty, etc.) map to `server.properties` fields. The `server_type` column was added in migration `5a50140d37df`; deployment columns in `003`; `launch_config_json` in `fcc7545db19e`; `external_id` in `902b076bfa36`; `missing_since` in `a1b2c3d4e5f6`.

### Backups

`backup_jobs` — `backend/app/modules/backup/infrastructure/models.py:8`

| Column | Type | Notes |
|---|---|---|
| `id` | `String(36)` PK | UUID |
| `server_id` | `String(36)` | Indexed, FK to servers |
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
| `source` | `String(16)` | `detected` (found on disk) or `modrinth` (marketplace) |
| `external_project_id`, `external_version_id`, `external_url`, `checksum` | varied | Modrinth provenance for marketplace-installed plugins |
| `pending_deletion` | `Boolean` | Deferred deletion — file removed on next server start/restart |

> The `filename`/`source`/`pending_deletion` and Modrinth-provenance columns were
> added by migrations `3a42d373bb05` and `c4d5e6f7a8b9` (2026-08-04, plugin
> filesystem-tracking + marketplace work). See `docs/plugins-and-marketplace.md`.

### Monitoring

`metric_points` — `backend/app/modules/monitoring/infrastructure/models.py:8`

Time-series data for server performance: `tps`, `players`, `ram_used_mb`, `cpu_percent`. Indexed by `server_id`. Supports sliding-window chart queries.

`alert_rules` — threshold-based alerting per server per metric: condition (`>`, `<`, `>=`, `<=`), threshold, severity, cooldown. `updated_at` added in migration `a2b2c3d4e5f7`.

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
users   1──* api_keys
users   1──* refresh_tokens
users   *──* roles        (via user_roles)
```

## Migration Strategy

Alembic with async engine (`backend/alembic/env.py:34`). All models register on `Base.metadata`.

```bash
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

The application reads the database URL from the `MCS_DATABASE_URL` environment
variable.  If unset it falls back to `alembic.ini` → `sqlalchemy.url`.

```bash
export MCS_DATABASE_URL="sqlite+aiosqlite:///path/to/mcs.db"
alembic upgrade head
```

### Migration Chain (chronological)

| Revision | Description |
|----------|-------------|
| `001` | Initial schema |
| `002` | Batch-09 tables: task_queue, cron_jobs, metric_points, alert_rules |
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

### Current dev database state

- **File**: `backend/mcs.db`
- **Alembic version**: `c4d5e6f7a8b9` (head)
- **Tables**: 27 (including `alembic_version`)

### Current production database state

- **File**: `backend/data/servers/mcs.db`
- **Alembic version**: `a3b2c3d4e5f6` — 3 revisions behind head (`b5c6d7e8f9a0`, `3a42d373bb05`, `c4d5e6f7a8b9` pending)
- **Servers**: 0
- **Tables**: 27 (including `alembic_version`)

> Verified 2026-08-04. Production is intentionally not upgraded to head.

## Cross-References

- [Architecture](ARCHITECTURE.md) — system context, CQRS, Event Bus, Saga orchestration
- [Architecture](ARCHITECTURE.md) — module structure, core infrastructure patterns
- [Development guide](DEVELOPMENT.md) — setup, migration commands, testing
