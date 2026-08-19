# Deployment Guide (Docker)

## Prerequisites

- **Docker** ≥ 24.0 (with Compose plugin v2 or standalone `docker-compose`)
- **Git** (to clone the repo)

Verify:

```bash
docker --version
docker compose version
```

## Quick start

```bash
# 1. Clone the repo
git clone <repo-url> && cd mcs-manager

# 2. Set up environment
cp .env.example .env
# Edit .env — at minimum change MCS_SECRET_KEY to a long random string

# 3. Build and start
docker compose up -d

# 4. Check status
docker compose ps
curl http://localhost:8000/health
curl http://localhost:80/
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MCS_DATABASE_URL` | `sqlite+aiosqlite:///data/mcs.db` | Database connection string |
| `MCS_SECRET_KEY` | `change-me…` | App secret key (change in production!) |
| `MCS_DEBUG` | `false` | Enable debug mode |
| `MCS_LOG_LEVEL` | `INFO` | Logging level |
| `MCS_JWT_PRIVATE_KEY` | *(auto-generated)* | PEM-encoded RSA private key for JWT signing. If omitted, a key is generated on first start and persisted to `config/jwt_private_key.pem` inside the container — all JWTs are invalidated if the container is recreated without preserving this file. |

## Persistent data

Docker Compose creates two named volumes:

| Volume | Mount point | Contents |
|--------|-------------|----------|
| `mcs-db-data` | `/data/` | SQLite database (`mcs.db`) |
| `mcs-server-data` | `/app/data/servers/` | Minecraft server files (worlds, JARs, plugins) |

Data survives container restarts and upgrades. To wipe everything (including the database):

```bash
docker compose down -v
```

## After first start — Owner bootstrap

A fresh deployment starts **uninitialized**; all protected API routes are
blocked until an Owner is created. Two equivalent ways to bootstrap:

**Via the UI (recommended):** open the frontend — the `/setup` wizard is shown
automatically. Create the Owner account and choose the access mode.

**Via the API:**

```bash
# 1. Confirm the instance is uninitialized
curl http://localhost:8000/api/v1/setup/status
# → {"initialized": false, "access_mode": "LOCAL", "user_count": 0, "version": "4.0.0"}

# 2. Bootstrap (single-use — this must succeed exactly once)
curl -X POST http://localhost:8000/api/v1/setup/bootstrap \
  -H "Content-Type: application/json" \
  -d '{
    "email": "owner@example.com",
    "password": "a-long-password",
    "display_name": "Instance Owner",
    "access_mode": "GLOBAL"
  }'
```

This creates the Owner (with the `owner` role and `admin:full`/`global.*`
claims) and marks the instance initialized. After bootstrap:

- **`LOCAL`** mode keeps open self-registration available at `/register`.
- **`GLOBAL`** mode disables self-registration (`403` on `POST /api/v1/users`),
  so the Owner must create invitations (UI: **Settings → Invitations**, or
  `POST /api/v1/invites` with a Bearer token carrying `user:write`) and share
  the invite links (`/invite/<token>`) with users.

If the app is redeployed on the same database volume, **do not** run bootstrap
again — `POST /api/v1/setup/bootstrap` returns `409 Conflict` on a second
attempt, and `PUT /api/v1/setup/access-mode` can be used later to flip
`LOCAL` ↔ `GLOBAL`.

## Common commands

```bash
# Start
docker compose up -d

# Stop (keep data)
docker compose down

# Stop and delete volumes (WARNING: destroys DB + server data)
docker compose down -v

# View logs
docker compose logs -f
docker compose logs backend -f
docker compose logs frontend -f

# Rebuild after code changes
docker compose build
docker compose up -d

# Restart a single service
docker compose restart backend
```

## Architecture

```
                        ┌─────────────┐
                        │  nginx:80   │  ← frontend service
                        │  (static)   │
                        └──────┬──────┘
                               │  /api/*  /ws  /health
                               ▼
                        ┌─────────────┐
                        │  uvicorn    │  ← backend service
                        │  :8000      │
                        └──────┬──────┘
                               │
                    ┌──────────┴──────────┐
                    │  mcs-db-data        │
                    │  mcs-server-data    │  ← named volumes
                    └─────────────────────┘
```

The frontend nginx serves the compiled Vite SPA and proxies API/WebSocket
requests to the backend container. The backend runs the Alembic migration step
in its container command and will not start against an incompatible schema
(see below).

## Database migrations & compatibility floor

**MCS Manager 4.0.0 requires DB compatibility with Alembic revision
`b1e2100000007`.** The version-conditional floor is declared once in
`backend/app/core/persistence/db_revision.py`
(`RELEASE_MINIMUM_DB_REVISION`); it is **never auto-applied** and **never read
from the DB URL config**.

Each deployment must follow this sequence:

```bash
# 1. Apply migrations (container entrypoint does this; you may run it explicitly)
alembic upgrade head

# 2. Verify the database reached the required revision
alembic current
#   → should show b1e2100000007 (or a compatible descendant for later releases)

# 3. Start the application
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- **Migrations are a deployment step, not a startup behavior.** The Docker image
  runs `alembic upgrade head && uvicorn app.main:app`, but the application itself
  performs **no** automatic migration.
- **Startup fails closed.** On start the backend reads `alembic_version` from the
  live database and aborts if the revision is missing, unknown, **behind
  `b1e2100000007`**, or on an incompatible branch. The error names the current
  revision, the required minimum, and the fix (`alembic upgrade head`) — without
  exposing the database URL or credentials.
- A fresh database migrated with `alembic upgrade head` starts normally; a
  database left below the floor (e.g. the legacy secondary SQLite file
  described in `docs/architecture/DATABASE.md`) is rejected with an actionable
  error.

## Production considerations

1. **Change `MCS_SECRET_KEY`** in `.env` to a long (≥32 chars) random string.
2. **Provide a JWT private key** — either set `MCS_JWT_PRIVATE_KEY` in `.env`, or mount a PEM file and set `MCS_JWT_PRIVATE_KEY_PATH`. Without this, JWTs are invalidated on every container restart.
3. **Back up the volumes** regularly — especially `mcs-db-data` and `mcs-server-data`.
4. **Resource limits** — Minecraft servers can use significant RAM. Consider adding `deploy.resources.limits` in `docker-compose.yml` if running on constrained hardware.

## Local dev (non-Docker) alternative

The project also supports a local development path:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload
```

```bash
cd frontend
npm install
npm run dev
```

Use the Docker path for deployment and CI. Use the local path for
active development (hot-reload, debugger access, test runner).
