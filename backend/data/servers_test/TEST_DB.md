# Test Database — `test_onx.db`

## Connection mechanism

The app reads its database URL from `AppSettings.database_url`, which
defaults to `"sqlite+aiosqlite:///data/onx.db"`. Because `AppSettings`
extends `pydantic-settings.BaseSettings`, you can override this at runtime
via the environment variable:

```
ONX_DATABASE_URL=sqlite+aiosqlite:///./data/servers_test/test_onx.db
```

**Alembic also respects this env var.** `alembic/env.py` checks
`ONX_DATABASE_URL` / `MCS_DATABASE_URL` first, falling back to `alembic.ini`'s hardcoded
value. Alembic prints which database it's targeting at the start of
every migration run — always check that line before confirming.

---

## One-time setup — create the schema

A fresh `test_onx.db` is an empty SQLite file with no tables. You must
create the schema before starting the app:

```bash
cd backend/

# Create all ORM tables and Alembic-only tables, then stamp Alembic head
ONX_DATABASE_URL="sqlite+aiosqlite:///./data/servers_test/test_onx.db" \
  python3 -c "
import asyncio, os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.persistence.base import Base
import app.modules.server.infrastructure.models
import app.modules.backup.infrastructure.models
import app.modules.plugin.infrastructure.models
import app.modules.monitoring.infrastructure.models
import app.modules.auth.infrastructure.models
import app.modules.auth.infrastructure.audit
import app.modules.event_store.models

ALEMBIC_ONLY_DDL = [
    'CREATE TABLE IF NOT EXISTS idempotency_keys (key VARCHAR(128) NOT NULL PRIMARY KEY, result_json TEXT NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, expires_at DATETIME NOT NULL)',
    'CREATE TABLE IF NOT EXISTS feature_flags (key VARCHAR(128) NOT NULL PRIMARY KEY, enabled BOOLEAN NOT NULL DEFAULT 0, percentage INTEGER NOT NULL DEFAULT 0, description TEXT NOT NULL DEFAULT \"\", updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)',
    'CREATE TABLE IF NOT EXISTS circuit_breaker_states (name VARCHAR(128) NOT NULL PRIMARY KEY, state VARCHAR(16) NOT NULL, failure_count INTEGER NOT NULL DEFAULT 0, last_failure_time REAL NOT NULL DEFAULT 0.0, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)',
    'CREATE TABLE IF NOT EXISTS saga_instances (saga_id VARCHAR(36) NOT NULL PRIMARY KEY, saga_type VARCHAR(128) NOT NULL, status VARCHAR(32) NOT NULL, current_step INTEGER NOT NULL DEFAULT 0, error TEXT, started_at REAL NOT NULL DEFAULT 0.0, timeout_seconds REAL NOT NULL DEFAULT 300.0, created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)',
    'CREATE TABLE IF NOT EXISTS saga_steps (id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, saga_id VARCHAR(36) NOT NULL REFERENCES saga_instances(saga_id) ON DELETE CASCADE, step_index INTEGER NOT NULL, name VARCHAR(128) NOT NULL, status VARCHAR(32) NOT NULL)',
    'CREATE TABLE IF NOT EXISTS feature_flag_overrides (id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, flag_key VARCHAR(128) NOT NULL REFERENCES feature_flags(key) ON DELETE CASCADE, user_id VARCHAR(128) NOT NULL, enabled BOOLEAN NOT NULL)',
    'CREATE TABLE IF NOT EXISTS task_queue (id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, task_id VARCHAR(36) NOT NULL UNIQUE, task_type VARCHAR(64) NOT NULL, payload TEXT, status VARCHAR(16) NOT NULL DEFAULT \"pending\", priority INTEGER NOT NULL DEFAULT 0, max_retries INTEGER NOT NULL DEFAULT 3, retry_count INTEGER NOT NULL DEFAULT 0, error TEXT, scheduled_at REAL, started_at REAL, completed_at REAL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)',
    'CREATE TABLE IF NOT EXISTS cron_jobs (id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, job_id VARCHAR(36) NOT NULL UNIQUE, name VARCHAR(128) NOT NULL, task_type VARCHAR(64) NOT NULL, cron_expression VARCHAR(64) NOT NULL, payload TEXT, enabled BOOLEAN NOT NULL DEFAULT 1, last_run_at REAL, next_run_at REAL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)',
]

async def main():
    db_url = os.environ.get(\"ONX_DATABASE_URL\") or os.environ.get(\"MCS_DATABASE_URL\")
    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for ddl in ALEMBIC_ONLY_DDL:
            await conn.execute(text(ddl))
    await engine.dispose()

asyncio.run(main())
"

# Stamp the test DB so Alembic knows it is at the latest schema version
ONX_DATABASE_URL="sqlite+aiosqlite:///./data/servers_test/test_onx.db" \
  alembic stamp head
```

---

## Running with the test DB

### Run pytest against the test DB

```bash
cd backend/
ONX_DATABASE_URL="sqlite+aiosqlite:///./data/servers_test/test_onx.db" \
ONX_SERVERS_DATA_DIR="data/servers_test" \
  pytest
```

### Start the backend against the test DB

```bash
cd backend/
ONX_DATABASE_URL="sqlite+aiosqlite:///./data/servers_test/test_onx.db" \
ONX_SERVERS_DATA_DIR="data/servers_test" \
  ./run.sh
```

### Start the backend with the default DB (normal)

```bash
cd backend/
./run.sh
```

No env var needed — default uses `backend/data/onx.db`.

---

## Safety — Alembic targets the right DB

`alembic/env.py` checks `ONX_DATABASE_URL` / `MCS_DATABASE_URL` before reading `alembic.ini`.
Every migration run prints a line like:

```
Alembic target DB: sqlite+aiosqlite:///./data/servers_test/test_onx.db  (test_onx.db)
```

or, for default:

```
Alembic target DB: sqlite+aiosqlite:///data/onx.db  (onx.db)
```

Always check this line before confirming a migration. If you see the
wrong database, stop — `ONX_DATABASE_URL` is not set correctly.

---

## Rules

1. **Any server created while `ONX_DATABASE_URL` is set** must have its
   filesystem directory created under `backend/data/servers_test/`,
   **never** under `backend/data/servers/`. This is enforced by setting
   `MCS_SERVERS_DATA_DIR=data/servers_test` alongside
   `MCS_DATABASE_URL` — see "How it works under the hood" below.

2. **Clean up when done.** The test database and its server directories
   are ephemeral. Delete every test server directory and either drop
   `test_mcs.db` entirely or reset its tables before ending your session:

   ```bash
   rm -f backend/data/servers_test/test_mcs.db*
   rm -rf backend/data/servers_test/*/
   ```

3. **Never mix test and production data.** Test server IDs (UUIDs)
   should never appear in the production DB or the production servers
   directory. The separate database and directory enforce this.

4. **Ad-hoc test & recon scripts must use `tmp_path` or explicit `/tmp`.**
   Ad-hoc recon/test scripts must construct SQLite paths via `tmp_path`
   (pytest fixture) or an explicit `/tmp` location (e.g. `tempfile.TemporaryDirectory()`).
   Never use a bare relative filename (such as `test_audit_recon.db` or
   `sqlite+aiosqlite:///test.db`) that resolves to whatever working directory (CWD)
   the script happens to be launched from. Bare relative filenames pollute the
   repository root and are blocked by `scripts/check-stray-db` and `scripts/pre-push-check.sh`.

---

## How it works under the hood

In `backend/app/core/config.py`, `AppSettings` uses the env prefix
`MCS_` to map:
- `MCS_DATABASE_URL` → `database_url`
- `MCS_SERVERS_DATA_DIR` → `servers_data_dir`

The global singleton `database = DatabaseEngine()` in
`backend/app/core/persistence/db.py` reads `AppSettings().database_url` when
`init()` is called.

Similarly, `jar_service._default_data_dir()` now reads
`AppSettings().servers_data_dir` instead of using a hardcoded
`"data/servers"` path. This means setting
`MCS_SERVERS_DATA_DIR=data/servers_test` redirects ALL server file
operations (directory creation, JAR downloads, properties, eula) to
the test directory alongside the test database.

**Always set both** for sandbox sessions:
```bash
MCS_DATABASE_URL="sqlite+aiosqlite:///./data/servers_test/test_mcs.db" \
MCS_SERVERS_DATA_DIR="data/servers_test" \
  ./run.sh
```

Without `MCS_SERVERS_DATA_DIR`, server files would still leak into
`data/servers/` even though the database is isolated.

For Alembic, `backend/alembic/env.py` was modified to check
`os.environ.get("MCS_DATABASE_URL")` before falling back to
`alembic.ini`'s `sqlalchemy.url`. This prevents silent production
migrations when targeting the test DB.
