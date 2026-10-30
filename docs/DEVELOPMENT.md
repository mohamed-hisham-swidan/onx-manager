# Development Guide

## Prerequisites

- **Python** 3.12+ (3.14+ supported)
- **Node.js** 20+ (Node.js 22 LTS portable auto-installed on Windows if missing)
- **PostgreSQL 16+** (optional — SQLite with WAL mode is the zero-config default)
- **Git**

## Quick Start (Automated)

The project includes unified launchers that handle virtual environments, dependencies, migrations, preflight process cleanup, and service supervision:

```bash
# Windows
start.bat

# Linux / macOS
./start.sh
```

### Useful Launcher Options
```bash
./start.sh --stop          # Stop all running services
./start.sh --restart       # Clean restart
./start.sh --status        # Show active processes and port allocation
./start.sh --logs          # Show aggregated service logs
./start.sh --self-test     # Validate prerequisites upfront
./start.sh --ascii         # Force clean ASCII output mode
./start.sh --swagger       # Open Swagger API documentation
```

### Debug & Tracing Launchers
For deep troubleshooting and process tracing:
- Windows: `executors/start-debug.bat` (or PowerShell `executors/start-debug.ps1`)
- Unix: `executors/start-debug.sh`

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
uvicorn app.main:app --reload --port 8000  # Default port; launcher resolves preferred port (precedence: ONX_BACKEND_PORT > MCS_BACKEND_PORT > .onx/config.json > 8000)

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
# Note: port 8000 is default; use the active backend port from .onx/backend.port if running on a dynamic fallback port
curl -X POST http://localhost:8000/api/v1/servers/reconcile \
  -H "Content-Type: application/json" \
  -d '{"scope": "system_wide"}'
```

> ⚠️ **Warning**: `scope="system_wide"` will kill any process on the machine
> that looks like a Minecraft server (matches cmdline pattern) and is not in
> this project's DB. Use with extreme care on shared or production hosts.

### Preflight Process Reconciliation

Before starting, the project runs `scripts/preflight.sh` automatically to ensure a clean, reliable runtime environment without terminating healthy processes:

1. **Smart Reconciliation Mode (Default)**:
   - Resolves preferred port via `ONX_BACKEND_PORT` > `MCS_BACKEND_PORT` > `.onx/config.json` > `8000` (invalid values warn and fall through), checking `.onx/backend.port` for an active fallback port.
   - Probes backend panel health (`http://127.0.0.1:<port>/health`, requiring valid signature `status == "ok"` and `version`) and frontend (`http://127.0.0.1:5173`).
   - If a service is already running and healthy, it **preserves** the process and protects its child/parent process families.
   - Preserves active SQLite locks owned by the healthy backend.
   - Detects and terminates only inactive, stale, or dead duplicate processes that do not hold an active listening port.
2. **Daemon & Game Exclusions**:
   - Background daemons (`playitd`, `cloudflared`) and live Minecraft game servers (`tmux`, `java` under `data/servers/`) are strictly exempt from preflight cleanup.
3. **Force Cleanup Mode (`--stop`, `--restart`, `--force`, `--clean`, `-f`)**:
   - Forcibly terminates all project-related backend and frontend processes, clears stale SQLite locks, and cleans `.mcs/*.pid` files.
4. **Ownership Verification**:
   - Verifies ownership via `/proc/<PID>/cwd` and strict `/proc/<PID>/cmdline` project identifiers (`app.main:app`, `mcs-frontend`, `mcs-manager`) before any kill action.
5. **Summary Reporting**:
   - Prints a real-time status table of active ports, SQLite DB lock state, and actions taken.

This prevents duplicate instances and `sqlite3.OperationalError: database is locked` while ensuring live services and background tunnels are never interrupted.

Configuration via environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `ONX_BACKEND_PORT` | `8000` (or `.onx/config.json`) | Preferred backend port (highest priority env override; range `1024..65535`) |
| `MCS_BACKEND_PORT` | `8000` (or `.onx/config.json`) | Legacy backend port override (checked after `ONX_BACKEND_PORT`) |
| `MCS_FRONTEND_PORT` | `5173` | Frontend port to check |
| `MCS_PROJECT_ROOT` | auto-detected | Root dir for ownership checks |

> **Dynamic Backend Port Behavior & Persistence:**
> - Preferred port precedence: `ONX_BACKEND_PORT` > `MCS_BACKEND_PORT` > `.onx/config.json` `configured_backend_port` > `8000`. Invalid or out-of-range (`1024..65535`) values log a warning and fall through to the next source.
> - Runtime active port is stored in `.onx/backend.port` (valid port range `1..65535`) upon successful health check; removed on stop or clean exit.
> - `ConfigManager.save()` persists only `configured_backend_port` to `.onx/config.json`. Environment variable overrides are never written to config files.

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
npm run dev          # Vite dev server (:5173, proxies /api and /ws to active backend port, default :8000)
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

See [Database docs](architecture/DATABASE.md) for full schema reference.

## Testing Strategy

### Backend

```bash
cd backend
python -m pytest tests/ -q          # All tests (2,906 passed, 6 skipped)
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

730 frontend tests across 83 files (measured 2026-09-18). Vitest with jsdom environment.

## Docker Development

```bash
docker compose up --build    # Build and start full stack
docker compose build         # Rebuild images after dependency changes
```

Both backend (uvicorn on :8000) and frontend (nginx on :80) are defined in
`docker-compose.yml` at the repository root. Backend health checks are
configured with a 30s interval and 5s timeout.

## Verification & CI Quality Gates

Run the authoritative verification suite before pushing:

```bash
# Authoritative CI Verification Gates (Linux / macOS / WSL)
python3 scripts/check-version-propagation
python3 scripts/check-db-revision
python3 scripts/check-ruff-baseline
python3 scripts/check-route-contract
python3 scripts/check-ps1-bom
python3 scripts/check-stray-db

# Full Test Suites
(cd backend && pytest -v)
(cd frontend && npm run typecheck && npm run lint && npm test)
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

See [Architecture docs](architecture/ARCHITECTURE.md) for the full system design.

## Debugging Tips

- **Database lock errors**: Run `scripts/preflight.sh` to kill stale processes
- **WebSocket not connecting**: Check Vite proxy config — `/ws` proxies to the active backend port (reads `ONX_BACKEND_PORT` propagated from `.onx/backend.port`, default `ws://localhost:8000`)
- **Migration conflicts**: `alembic merge` to resolve branch points
- **Stale query cache**: TanStack Query devtools (`@tanstack/react-query-devtools`) are included in the frontend
- **401 on API calls**: Check auth store — tokens expire after 15 minutes; refresh is automatic but requires a valid refresh token
- **FastAPI auto-docs**: Available at `http://localhost:<port>/docs` (where `<port>` is the active port from `.onx/backend.port`, default 8000; proxied from frontend dev server)

## Cross-References

- [Architecture](architecture/ARCHITECTURE.md) — system context, core patterns, bounded contexts
- [Database](architecture/DATABASE.md) — schema design, migrations, query patterns
- [Frontend](architecture/FRONTEND.md) — React app structure, state management, WS integration
- [API docs](API.md) — REST endpoints, WebSocket protocol, error codes
- [Provisioning](architecture/PROVISIONING.md) — server creation flow, JAR validation, supported types
