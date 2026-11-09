# Deployment Guide (Docker)

## Prerequisites

- **Docker** ≥ 24.0 (with Compose plugin ≥ v2.24 supporting long `env_file` syntax)
- **Git** (to clone the repo)

Verify:

```bash
docker --version
docker compose version
```

## Quick start

```bash
# 1. Clone the repo
git clone https://github.com/mohamed-hisham-swidan/onx-manager.git
cd onx-manager

# 2. Set up environment
cp .env.example .env
# Edit .env to customize ports, database URL, or keys if desired

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
| `ONX_DATABASE_URL` (or `MCS_DATABASE_URL`) | `sqlite+aiosqlite:////app/data/onx.db` | Database connection string inside container |
| `ONX_DEBUG` | `false` | Enable debug mode |
| `ONX_LOG_LEVEL` | `INFO` | Logging level |
| `ONX_FORCE_ASCII` | `0` | Set `1` to force ASCII console output |
| `ONX_JWT_PRIVATE_KEY` (or `MCS_JWT_PRIVATE_KEY`) | *(auto-generated)* | PEM-encoded RSA private key for JWT signing. If omitted, a key is generated on first start and persisted to `/app/config/jwt_private_key.pem` inside the container (`onx-config` volume). |
| `ONX_JWT_PRIVATE_KEY_PATH` (or `MCS_JWT_PRIVATE_KEY_PATH`) | No | Path to a PEM file to load instead of the env/auto-generated key |

## Persistent data

Docker Compose creates three named volumes:

| Volume | Mount point | Contents |
|--------|-------------|----------|
| `onx-db-data` | `/app/data/` | SQLite database (`onx.db`) |
| `onx-server-data` | `/app/data/servers/` | Minecraft server files (worlds, JARs, plugins) |
| `onx-config` | `/app/config/` | JWT signing key, backup encryption key, `settings.yaml` |

Data survives container restarts and upgrades. To wipe everything (including the database and persistent keys):

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
# → {"initialized": false, "access_mode": "LOCAL", "user_count": 0, "version": "0.1.0"}

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
                    │  onx-db-data        │
                    │  onx-server-data    │  ← named volumes
                    └─────────────────────┘
```

The frontend nginx serves the compiled Vite SPA and proxies API/WebSocket
requests to the backend container. The backend runs the Alembic migration step
in its container command and will not start against an incompatible schema
(see below).

## Database migrations & compatibility floor

**ONX Manager 0.1.0 requires DB compatibility with Alembic revision
`b1e2100000023`.** The version-conditional floor is declared once in
`backend/app/core/persistence/db_revision.py`
(`RELEASE_MINIMUM_DB_REVISION`); it is **never auto-applied** and **never read
from the DB URL config**.

Each deployment must follow this sequence:

```bash
cd backend

# 1. Apply migrations (container entrypoint does this; you may run it explicitly)
alembic upgrade head

# 2. Verify the database reached the required revision
alembic current
#   → should show b1e2100000023 (or a compatible descendant for later releases)

# 3. Start the application
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- **Migrations are a deployment step, not a startup behavior.** The Docker image
  runs `alembic upgrade head && uvicorn app.main:app`, but the application itself
  performs **no** automatic migration.
- **Startup fails closed.** On start the backend reads `alembic_version` from the
  live database and aborts if the revision is missing, unknown, **behind
  `b1e2100000023`**, or on an incompatible branch. The error names the current
  revision, the required minimum, and the fix (`alembic upgrade head`) — without
  exposing the database URL or credentials.
- A fresh database migrated with `alembic upgrade head` starts normally; a
  database left below the floor (e.g. the legacy secondary SQLite file
  described in `docs/architecture/DATABASE.md`) is rejected with an actionable
  error.

## Production considerations

1. **Provide a persistent JWT private key** — set `ONX_JWT_PRIVATE_KEY` (or `MCS_JWT_PRIVATE_KEY`) in `.env`, or mount a PEM file and set `ONX_JWT_PRIVATE_KEY_PATH` (or `MCS_JWT_PRIVATE_KEY_PATH`). Alternatively, ensure the `onx-config` volume is preserved across deployments so auto-generated keys in `/app/config/` remain intact. JWTs are only invalidated if the `onx-config` volume is removed or recreated.
2. **Back up the volumes** regularly — especially `onx-db-data`, `onx-server-data`, and `onx-config`.
3. **Resource limits** — Minecraft servers can use significant RAM. Consider adding `deploy.resources.limits` in `docker-compose.yml` if running on constrained hardware.

## Local dev (non-Docker) alternative

The project also supports a local development path:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -e ".[dev]"
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

## Docker-outside-of-Docker (DooD) Profile

When running ONX Manager itself inside Docker, controlling host Minecraft containers
requires the **Docker-outside-of-Docker (DooD)** opt-in override:

```bash
docker compose -f docker-compose.yml -f docker-compose.dood.yml up -d
```

### Security Considerations & Host Privilege Escalation Risk

> [!CAUTION]
> **Host Privilege Escalation Risk:** Mounting `/var/run/docker.sock` grants the
> container root-equivalent access to the host Docker daemon. Any attacker or process
> that compromises the backend container can execute arbitrary Docker commands on the host,
> mount the host filesystem root (`-v /:/host`), and achieve complete host takeover.
>
> - **Never** expose a DooD-enabled ONX Manager instance to untrusted networks without
>   authentication, TLS, and strict firewall rules.
> - **Do not** use this override in untrusted multi-tenant environments.
> - Native host deployment (running ONX Manager directly on the host) remains the
>   **Primary Supported Tier** and does not require mounting `/var/run/docker.sock`.

### Host Sibling Mounts & Path Translation (`ONX_HOST_DATA_DIR`)

Because sibling Minecraft containers are created by the **host** Docker daemon, the host
daemon resolves volume paths against the host's filesystem, not internal container paths.

To ensure sibling containers mount server files correctly:
1. `docker-compose.dood.yml` replaces the named volume with a host bind mount:
   `${ONX_HOST_DATA_DIR:-./backend/data/servers}:/app/data/servers`
2. Set the `ONX_HOST_DATA_DIR` environment variable to the absolute host directory where
   servers are stored:
   ```bash
   export ONX_HOST_DATA_DIR=$(pwd)/backend/data/servers
   ```
3. `DockerProvider` translates internal `/app/data/servers/{server_id}` paths to
   `${ONX_HOST_DATA_DIR}/{server_id}` when issuing `docker run -v` commands to the host daemon.

### Windows & WSL2 Hosts

On Windows hosts running Docker Desktop with the WSL2 backend:
- The Docker daemon socket is available at `/var/run/docker.sock` inside WSL2 and is bridged
  by Docker Desktop into Linux containers.
- Sibling Minecraft containers run in Linux containers mode (itzg images require Linux).
- Set `ONX_HOST_DATA_DIR` using forward slashes (e.g. `D:/onx-manager/data/servers` or
  `/mnt/d/onx-manager/data/servers`).

