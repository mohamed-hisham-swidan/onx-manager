# Deployment Guide

ONX Manager supports three primary deployment topologies:

1. **Docker Compose (`docker-compose.yml`)** — Recommended for VPS & home servers
2. **Docker-outside-of-Docker (`docker-compose.dood.yml`)** — Opt-in override when running ONX inside Docker while managing sibling Minecraft containers on the host daemon
3. **Bare-Metal VPS (`./install.sh --mode=vps`)** — Single-process `systemd` service with FastAPI serving the built SPA directly

---

## Panel Deployment Profiles (`ONX_DEPLOYMENT_PROFILE`)

`ONX_DEPLOYMENT_PROFILE` controls the panel UX surface (separate from per-server `ServerMode` `simple` vs `advanced`):

| Value | Default In | Behavior |
|---|---|---|
| `vps` | Docker, `./install.sh --mode=vps` | Exposes the full server panel: networking topology, multi-user invitations/RBAC, API keys, full diagnostics, and Advanced GitOps workflows. |
| `local` | `./install.sh --mode=local`, `install.ps1`, Desktop App | Streamlines onboarding (`/setup`), keeps core server controls, console, mods/plugins, and quick sharing (Playit.gg / Cloudflare Tunnel) front-and-center, and collapses VPS-only sections behind an opt-in toggle. |

---

## Option 1: Docker Compose (VPS)

### Prerequisites

- **Docker** ≥ 24.0 (with Compose plugin ≥ v2.24 supporting long `env_file` syntax)
- **Git**

```bash
git clone https://github.com/mohamed-hisham-swidan/onx-manager.git
cd onx-manager
cp .env.example .env
# Edit .env if you want custom host ports (ONX_PANEL_PORT / ONX_API_PORT) or explicit keys
docker compose up -d
```

Verify health:

```bash
docker compose ps
curl http://localhost:8000/health
curl http://localhost:80/
```

### Standard `docker-compose.yml` vs `docker-compose.dood.yml`

| Feature | `docker-compose.yml` (Standard) | `docker-compose.yml` + `docker-compose.dood.yml` (DooD) |
|---|---|---|
| **Use Case** | Standard panel deployment | Containerized panel spawning sibling Minecraft & Branch Runtime containers on host Docker |
| **Socket Access** | None (isolated) | Mounts `/var/run/docker.sock` (`user: root`) |
| **Server Data Storage** | Named volume `onx-server-data` | Host bind mounts `${ONX_HOST_DATA_DIR:-./backend/data/servers}` & `${ONX_HOST_STATE_HOST_DIR:-./backend/data/host-state}` |
| **Security Footprint** | Least-privilege non-root container | **Opt-in root-equivalent host Docker access** — see security caution below |

---

## Option 2: Bare-Metal VPS (`./install.sh --mode=vps`)

For Ubuntu/Debian/Fedora/Arch VPS hosts where you want zero container overhead for the panel itself and direct host Docker access for Minecraft servers:

```bash
curl -fsSL https://raw.githubusercontent.com/mohamed-hisham-swidan/onx-manager/master/install.sh | bash -s -- --mode=vps --yes
```

What this configures automatically:
- Isolated **Python 3.12** virtual environment via `uv` (`backend/.venv`)
- Compiled production SPA (`frontend/dist`) served directly by FastAPI on a single port (`ONX_STATIC_DIR`) — no Nginx or Node.js daemon needed
- Auto-generated `0600` secrets in `backend/config/`: `jwt_private_key.pem`, `backup_encryption_key.bin`, and `master_kek.key`
- Database schema migrated to head (`alembic upgrade head`)
- Enabled `systemd` unit (`onx-manager.service`) + `onx` CLI (`onx start|stop|restart|status|logs|update`)

Put Nginx, Caddy, or a Cloudflare Tunnel in front of port `8000` for HTTPS in production.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `ONX_DEPLOYMENT_PROFILE` | `vps` | Panel UI profile (`vps` or `local`) |
| `ONX_PANEL_PORT` / `ONX_API_PORT` | `80` / `8000` | Host port mappings used by `docker-compose.yml` |
| `ONX_PANEL_BIND_HOST` / `ONX_PANEL_BIND_PORT` | `127.0.0.1` (`0.0.0.0` in Docker/VPS) / `8000` | Uvicorn bind address and port |
| `ONX_STATIC_DIR` | *(auto-detects `frontend/dist`)* | Built SPA path for single-process serving (`off` disables static serving) |
| `ONX_DATABASE_URL` | `sqlite+aiosqlite:///data/onx.db` (`/app/data/onx.db` in Docker) | SQLite or PostgreSQL (`postgresql+asyncpg://...`) URL |
| `ONX_JWT_PRIVATE_KEY` / `ONX_JWT_PRIVATE_KEY_PATH` | *(auto-generated `0600`)* | RSA private key for JWT signing; auto-created on first boot if omitted |
| `ONX_BACKUP_ENCRYPTION_KEY_PATH` | `config/backup_encryption_key.bin` *(auto-generated `0600`)* | 32-byte AES key for Tier-2 backup encryption |
| `ONX_MASTER_KEK` / `ONX_MASTER_KEK_FILE` | *(auto-generated `0600` at `config/master_kek.key` on POSIX)* | 256-bit Master KEK for Class-C state snapshots and secret vault |
| `ONX_HOST_DATA_DIR` / `ONX_HOST_STATE_HOST_DIR` | *(unset)* | Absolute host paths required for DooD sibling container volume mounts |
| `ONX_CURSEFORGE_API_KEY` | *(unset)* | Optional CurseForge API key (can also be set in Settings UI) |
| `ONX_HOST_RAM_RESERVE_MB` / `ONX_HOST_CPU_RESERVE` | *(profile-derived)* | Override OS RAM reserve (MB) and CPU core reserve (`local` defaults to at least `4096 MB` / `25%` RAM; `vps` to `1024 MB` / `15%` RAM) |
| `ONX_DEBUG` / `ONX_LOG_LEVEL` | `false` / `INFO` | Debug flag and logging verbosity |

> **Important Security Note on Auto-Generated Keys:** On first boot, ONX Manager generates `jwt_private_key.pem`, `backup_encryption_key.bin`, and (on POSIX) `master_kek.key` with strict `0600` permissions if not already configured. Always back up `onx-config` (Docker volume) or `backend/config/` — losing `backup_encryption_key.bin` or `master_kek.key` makes existing encrypted backups/snapshots unrecoverable.

---

## Persistent Volumes (Docker)

| Volume | Mount Point | Contents |
|---|---|---|
| `onx-db-data` | `/app/data/` | SQLite database (`onx.db`) |
| `onx-server-data` | `/app/data/servers/` | Minecraft server files (worlds, JARs, plugins) |
| `onx-config` | `/app/config/` | `jwt_private_key.pem`, `backup_encryption_key.bin`, `master_kek.key`, `settings.yaml` |

```bash
# Common Docker Compose operations
docker compose up -d
docker compose down          # Stop while keeping volumes
docker compose logs -f       # Tail logs
docker compose build && docker compose up -d
```

---

## First-Boot Owner Bootstrap (`/setup`)

- In **`vps`** profile, every fresh deployment starts uninitialized and redirects browser visitors to `/setup`.
- In **`local`** profile bound strictly to loopback (`127.0.0.1` / `::1`), `auth_mode` starts as `local_zero_login` (non-loopback requests or spoofed `X-Forwarded-For`/`Host` headers fail closed with `401`). External tunnels and non-loopback binding return `403 PASSWORD_REQUIRED_FOR_EXPOSURE` until credentials are set via `POST /api/v1/setup/credentials` or the UI exposure modal.

You can bootstrap a `vps` instance in the browser GUI (recommended) or via API:

```bash
curl -s http://localhost:8000/api/v1/setup/status
# {"initialized":false,"access_mode":"LOCAL","user_count":0,"version":"0.1.0","advanced_mode_enabled":true,"deployment_profile":"vps","password_configured":false,"auth_mode":"jwt"}

curl -X POST http://localhost:8000/api/v1/setup/bootstrap \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "a-strong-password",
    "access_mode": "GLOBAL"
  }'
```

---

## Database Migrations & Compatibility Floor

**ONX Manager 0.1.0 requires Alembic revision `b1e2100000033`** (enforced fail-closed at startup via `app.core.persistence.db_revision`).

- Docker entrypoint and `./install.sh` run `alembic upgrade head` automatically.
- For manual upgrades:

```bash
cd backend
alembic upgrade head
alembic current
```

---

## Docker-outside-of-Docker (DooD) Details

```bash
export ONX_HOST_DATA_DIR=$(pwd)/backend/data/servers
export ONX_HOST_STATE_HOST_DIR=$(pwd)/backend/data/host-state
docker compose -f docker-compose.yml -f docker-compose.dood.yml up -d
```

> [!CAUTION]
> **Host Privilege Escalation Risk:** Mounting `/var/run/docker.sock` grants the backend container root-equivalent access to the host Docker daemon. Never expose a DooD instance directly to untrusted networks without TLS, strong auth, and strict firewall rules. For native VPS installations, `./install.sh --mode=vps` avoids Docker socket forwarding altogether.

On Windows with Docker Desktop (WSL2 backend), ensure Linux containers mode is enabled and set `ONX_HOST_DATA_DIR` using forward slashes (e.g. `D:/onx-manager/data/servers` or `/mnt/d/onx-manager/data/servers`).
