# Development Guide

## Prerequisites

- Python 3.12+
- Node.js 20+
- PostgreSQL 16+ (or SQLite for embedded mode)
- Redis 7+ (cache, WebSocket pub/sub, production message queue)

## Quick Start

```bash
# Clone and set up everything with one command
./scripts/bootstrap
```

Which runs:

```bash
# 1. Backend virtual environment
python3 -m venv backend/.venv
source backend/.venv/bin/activate
pip install -r backend/requirements.txt

# 2. Frontend dependencies
cd frontend && npm install && cd ..

# 3. Database migrations
alembic upgrade head
```

## Manual Setup

### Backend

```bash
python3 -m venv backend/.venv
source backend/.venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env   # configure database URL, secrets
alembic upgrade head
```

### Frontend

```bash
cd frontend
npm install
npm run dev            # Vite dev server on :5173
```

## Development Loop

```bash
# Terminal 1 — Backend (auto-reload on file change)
source backend/.venv/bin/activate
uvicorn app.main:app --reload --port 8000

# Terminal 2 — Frontend (HMR on file change)
cd frontend && npm run dev

# Terminal 3 — Tests (watch mode)
pytest-watch           # backend
cd frontend && npm run test:watch  # frontend
```

### POST /api/v1/servers/reconcile (Orphan Cleanup)

The `/reconcile` endpoint triggers both runtime reconciliation (repairs DB/OS
state mismatches for tracked servers) and orphan cleanup (kills stale OS resources).

By default, orphan cleanup uses **safe `project_owned` scope** — it will only
kill processes that can be positively identified as belonging to this project
(via `MCS_MANAGED=1` env marker or cwd inside `MCS_SERVERS_DATA_DIR`). An
untracked real Minecraft server will not be touched.

To force legacy behavior (kill any `mcs-*` session or Minecraft PID not in DB):

```bash
curl -X POST http://localhost:8000/api/v1/servers/reconcile \
  -H "Content-Type: application/json" \
  -d '{"scope": "system_wide"}'
```

> ⚠️ **Warning**: `scope="system_wide"` will kill any process on the machine
> that looks like a Minecraft server (matches cmdline pattern) and is not in
> this project's DB. Use with extreme care on shared or production hosts.

### Preflight Cleanup

Before starting, the project runs `scripts/preflight.sh` automatically to:

1. Kill any existing process on the backend port (default 8000)
2. Kill any existing process on the frontend port (default 5173)
3. Check for SQLite locks on `backend/mcs.db` and release them
4. Scan for orphaned `uvicorn`, `vite`, or `node` processes
5. Verify ownership via `/proc/<PID>/cwd` before killing
6. Print a summary table of actions taken

This prevents `sqlite3.OperationalError: database is locked` from stale processes.

Configuration via environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `MCS_BACKEND_PORT` | `8000` | Backend port to check |
| `MCS_FRONTEND_PORT` | `5173` | Frontend port to check |
| `MCS_PROJECT_ROOT` | auto-detected | Root dir for ownership checks |

## Available Scripts

All scripts are in `scripts/` (symlinked from project root):

| Script | Command | Purpose |
|---|---|---|
| `scripts/bootstrap` | — | Install deps, create venv, run migrations |
| `scripts/lint` | `ruff check .` | Python linting |
| `scripts/format` | `ruff format .` | Python code formatting |
| `scripts/typecheck` | `pyright` | Python type checking |
| `scripts/test` | `pytest` | Run Python test suite |
| `scripts/build` | `docker build` + `npm run build` | Build production images |
| `scripts/release` | `./scripts/release <version>` | Tag, build, push Docker image |
| `scripts/check` | lint + typecheck + test | Full pre-PR gate |

### Script Conventions

- Every script runs from the project root (`cd "$(dirname "$0")/.."`)
- All are executable (`chmod +x`)
- Follow `set -euo pipefail`
- Standardized across all development tasks — never use ad-hoc commands

## Frontend Commands

```bash
npm run dev          # Vite dev server (:5173, proxies /api and /ws to :8000)
npm run build        # tsc && vite build
npm run preview      # Vite preview
npm run test         # Vitest run
npm run test:watch   # Vitest watch
npm run lint         # ESLint src/
npm run typecheck    # tsc --noEmit
```

## Database Migrations

```bash
# Create a new migration
alembic revision --autogenerate -m "description"

# Apply all pending
alembic upgrade head

# Rollback one step
alembic downgrade -1

# View history
alembic history
```

See [Database docs](DATABASE.md) for full schema reference.

## Testing Strategy

### Backend

```bash
cd backend
python -m pytest tests/ -q          # All tests (984 passing)
python -m pytest tests/ -x -q       # Stop on first failure
```

### Sandbox Isolation

Tests MUST use a sandbox database and sandbox server directory to avoid
affecting production data:

```bash
MCS_DATABASE_URL="sqlite+aiosqlite:///data/servers_test/test.db" \
MCS_SERVERS_DATA_DIR="data/servers_test" \
  python -m uvicorn app.main:app --host 0.0.0.0 --port 8002
```

Both variables must be passed in the same command as the process (setsid
does not propagate inherited environment variables). See ADR-0008 for
details.

### Test Database Setup

```python
from app.core.persistence.base import Base
from app.core.persistence.db import database
# Create all tables via Base.metadata.create_all()
# Then alembic stamp head for migration-dependent tables
```

### Frontend

```bash
cd frontend && npm test            # All frontend tests
cd frontend && npm run test:watch  # Watch mode
```

148 frontend tests across 27 files. Vitest with jsdom environment.

## Docker Development

```bash
docker compose up --build    # Build and start full stack
docker compose build         # Rebuild images after dependency changes
```

Both backend (uvicorn on :8000) and frontend (nginx on :80) are defined in
`docker-compose.yml` at the repository root. Backend health checks are
configured with a 30s interval and 5s timeout.

## Code Conventions

- **Python**: type hints everywhere, functions ≤ 40 lines, ruff format + ruff check
- **TypeScript**: strict mode, no unchecked `any`, ESLint with `react-hooks` + `react-refresh` plugins
- **Documentation**: docstrings only when the "why" isn't obvious from the code
- **PR gate**: every PR must pass lint → typecheck → test → coverage

Run the full check suite before pushing:

```bash
./scripts/check         # Backend: lint + pyright + pytest
cd frontend && npm run typecheck && npm run lint && npm test
```

## Module Structure

```
backend/
├── app/
│   ├── core/               # CommandBus, QueryBus, EventBus, UoW, ConfigFactory
│   ├── modules/
│   │   ├── server/         # Server lifecycle, provisioning
│   │   ├── backup/         # Backup/restore
│   │   ├── plugin/         # Plugin system
│   │   ├── auth/           # Users, roles, API keys
│   │   ├── health/         # Health monitoring, crash diagnostics, integrity validation
│   │   ├── monitoring/     # Metrics, alerts
│   │   ├── event_store/    # Immutable event log
│   │   └── ...             # Other bounded contexts
│   └── core/persistence/   # Database engine, UoW, base repository
├── alembic/                # Migrations
└── tests/                  # Test suite
```

Each module follows: `domain/` → aggregates, value objects, interfaces; `application/` → command/query handlers, sagas; `infrastructure/` → repository implementations, adapters.

See [Architecture docs](ARCHITECTURE.md) for the full system design.

## Debugging Tips

- **Database lock errors**: Run `scripts/preflight.sh` to kill stale processes
- **WebSocket not connecting**: Check Vite proxy config — `/ws` must proxy to `ws://localhost:8000` in development
- **Migration conflicts**: `alembic merge` to resolve branch points
- **Stale query cache**: TanStack Query devtools (`@tanstack/react-query-devtools`) are included in the frontend
- **401 on API calls**: Check auth store — tokens expire after 15 minutes; refresh is automatic but requires a valid refresh token
- **FastAPI auto-docs**: Available at `http://localhost:8000/docs` (proxied from frontend dev server)

## Cross-References

- [Architecture](ARCHITECTURE.md) — system context, core patterns, bounded contexts
- [Database](DATABASE.md) — schema design, migrations, query patterns
- [Frontend](FRONTEND.md) — React app structure, state management, WS integration
- [API docs](API.md) — REST endpoints, WebSocket protocol, error codes
- [Provisioning](PROVISIONING.md) — server creation flow, JAR validation, supported types
