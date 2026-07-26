# Database Schema & Migration Guide

## Connection

The application reads the database URL from the `MCS_DATABASE_URL` environment
variable.  If unset it falls back to `alembic.ini` → `sqlalchemy.url`.

```bash
export MCS_DATABASE_URL="sqlite+aiosqlite:///path/to/mcs.db"
alembic upgrade head
```

## Migration Chain (chronological)

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

> \* `servers` is created by `003` on a fresh clone; `876be46160d3` is a
> no-op for it when replaying existing history.

## Fresh-clone bug (fixed)

### Before

`alembic upgrade head` on an empty database failed at migration `003`:

```
sqlite3.OperationalError: no such table: servers
```

Nine tables (`servers`, `api_keys`, `audit_log`, `backup_jobs`,
`backup_policies`, `plugins`, `refresh_tokens`, `roles`, `user_roles`) were
historically created only via `Base.metadata.create_all()` during early
development and were never captured in any migration.

### After (5-file fix, committed YYYY-MM-DD)

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

### Verified on fresh clone

```
Running upgrade  -> 001
Running upgrade 001 -> 002
Running upgrade 002 -> 16f9e2a1f2d6
Running upgrade 16f9e2a1f2d6 -> 003
Running upgrade 003 -> 5a50140d37df
Running upgrade 5a50140d37df -> ff9c2b3a8e4d
Running upgrade ff9c2b3a8e4d -> fcc7545db19e
Running upgrade fcc7545db19e -> 902b076bfa36
Running upgrade 902b076bfa36 -> 876be46160d3
```

Result: 23 tables, head `876be46160d3`.

## Current production state

- **File**: `backend/mcs.db`
- **SHA256**: `7c8439fa85e77848b6c1e2b944777867d492c8718a0eb993877e9d404f1ade9b`
- **Alembic version**: `fcc7545db19e` (1 revision behind head)
- **Servers**: 2
- **Tables**: 23 (including `alembic_version`)

Production is intentionally not upgraded to head in this commit; that is
tracked as a separate, explicitly scheduled operation.

When production is ready to advance, run:

```bash
cd backend
MCS_DATABASE_URL="sqlite+aiosqlite:///mcs.db" alembic upgrade head
```

This will run exactly 2 migrations:

1. `902b076bfa36` → adds `external_id` to `servers` (guarded, safe)
2. `876be46160d3` → no-op (all ORM-only tables already exist)
