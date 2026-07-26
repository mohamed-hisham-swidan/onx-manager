# Database Architecture

## Technology

| Component | Choice |
|---|---|
| Primary database | PostgreSQL 16 |
| Cache | Redis 7 (sessions, rate limits, WebSocket presence) |
| ORM | SQLAlchemy 2.0 async (repository pattern) |
| Migrations | Alembic |
| Embedded mode | SQLite 3 (fallback via config) |

Connection pooling: 20 pool size, 10 max overflow, `pool_pre_ping=True` for PostgreSQL. SQLite mode skips pooling. See `backend/app/storage/db.py`.

The `DatabaseEngine` class (`backend/app/storage/db.py:16`) wraps `create_async_engine` and provides an `async_sessionmaker`. Sessions are injected via FastAPI `Depends(get_db)`.

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

Server config properties (motd, difficulty, etc.) map to `server.properties` fields. The `server_type` column was added in migration `5a50140d37df`; deployment columns in `003`; `launch_config_json` in `fcc7545db19e`; `external_id` in `902b076bfa36`.

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
- **`api_keys`** — machine credentials; `key_hash` stored as Argon2id hash; prefix for display
- **`refresh_tokens`** — JWT refresh token tracking; `token_hash` stored; revocable

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

### Monitoring

`metric_points` — `backend/app/modules/monitoring/infrastructure/models.py:8`

Time-series data for server performance: `tps`, `players`, `ram_used_mb`, `cpu_percent`. Indexed by `server_id`. Supports sliding-window chart queries.

`alert_rules` — threshold-based alerting per server per metric: condition (`>`, `<`, `>=`, `<=`), threshold, severity, cooldown.

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

All domain entities use `BaseRepository[T]` (`backend/app/storage/base.py:31`):

```python
await repo.add(entity)
await repo.get(id) -> T | None
await repo.list(**filters) -> list[T]
await repo.update(entity)
await repo.delete(entity)
```

### Unit of Work

All mutations run inside a `UnitOfWork` context (`backend/app/storage/unit_of_work.py:13`):

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

## Cross-References

- [Architecture](ARCHITECTURE.md) — system context, CQRS, Event Bus, Saga orchestration
- [Architecture](ARCHITECTURE.md) — module structure, core infrastructure patterns
- [Development guide](DEVELOPMENT.md) — setup, migration commands, testing
