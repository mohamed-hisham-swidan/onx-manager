<div align="center">

<img src="docs/assets/logo.svg" alt="ONX Manager" width="64" height="64" />

# ONX Manager

**Self-hosted Minecraft server panel and Git-backed server workspace — no Redis, no multi-daemon sprawl.**

Run servers in Docker containers, stream live console & metrics, manage Plugins and Mods natively from Modrinth, isolate config changes in Git branches, and run 1-click safe upgrades with automatic rollback — as a **VPS web panel**, **native host install**, or **Desktop app**.

<p align="center">
  <a href="https://github.com/mohamed-hisham-swidan/onx-manager/releases">
    <img src="https://img.shields.io/badge/v0.1.0-0ea5e9?style=flat&logo=git&logoColor=white" alt="v0.1.0" />
  </a>
  &nbsp;&nbsp;
  <a href="https://github.com/mohamed-hisham-swidan/onx-manager/actions/workflows/ci-linux.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/mohamed-hisham-swidan/onx-manager/ci-linux.yml?style=flat&logo=githubactions&logoColor=white&label=Tests" alt="Tests" />
  </a>
  &nbsp;&nbsp;
  <a href="#quick-start">
    <img src="https://img.shields.io/badge/Docker-2496ED?style=flat&logo=docker&logoColor=white" alt="Docker" />
  </a>
  &nbsp;&nbsp;
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/Apache--2.0-D22128?style=flat&logo=apache&logoColor=white" alt="Apache-2.0" />
  </a>
  &nbsp;&nbsp;
  <a href="https://discord.gg/8AfQMv4CH">
    <img src="https://img.shields.io/badge/Discord-5865F2?style=flat&logo=discord&logoColor=white" alt="Discord" />
  </a>
</p>

</div>

---

## Why ONX Manager?

Most self-hosted Minecraft panels either wrap a bare shell process or require running a separate database, Redis cluster, and daemon agents just to change a config safely.

ONX Manager ships as a **single modular monolith** (SQLite + in-process async task queue, zero Redis, zero Node.js runtime needed in production) built with practical safety rails for everyday and advanced hosts:

- **Simple Mode & Advanced Git Mode**: Start fast in zero-friction **Simple Mode**, or switch any POSIX server into **Advanced Mode** for per-server Git branches, protected `main`, structured 3-way config merges (`YAML`, `TOML`, `JSON`, `.properties`), secret extraction (`${ONX_SECRET_*}`), and live **Simple ↔ Advanced** conversion.
- **1-Click Safe Upgrades with 5-Check Health Gate**: Checks Modrinth plugin/mod compatibility before touching your live server, runs a 5-check verification gate (process boot log, live Minecraft Server List Ping + version check, RCON world flush, `level.dat` integrity, and optional external reachability), and automatically rolls back to the pinned pre-upgrade backup on failure.
- **Native Plugins & Mods Management**: Strict separation between plugin servers (`Paper`, `Purpur`, `Spigot`, `Bukkit`, `Folia`, `Velocity`, `BungeeCord`, `Waterfall`) and modded servers (`Fabric`, `Forge`, `NeoForge`, `Quilt`), dual-platform project support, Modrinth version/loader pickers, one-click required dependency installs, and validated `.jar` uploads.
- **Built-in Network Exposure**: Manage **Playit.gg** tunnels, **Cloudflare Named Tunnels**, and **UPnP** port forwarding directly in the panel — with companion ports (e.g., Simple Voice Chat, Geyser, Dynmap) and an SSRF-safe live reachability probe.
- **Automated Encrypted Backups**: Fast local snapshots and AES-256-GCM envelope-encrypted archives with SHA-256 checksums, cron scheduling, upgrade-pinned delete protection, and local or S3-compatible storage.
- **Web Panel & Desktop App**: Run headless on a VPS (`systemd` or Docker) or launch the lightweight Electron desktop wrapper (`desktop/`) with Local auto-supervision and instant switching (`Ctrl+Shift+K`) to remote VPS panels.

---

## Requirements

- **Docker Engine** (Docker Desktop on macOS/Windows, or Docker CE on Linux) — all Minecraft servers run in hardened containers.
- **Python 3.12** (provisioned automatically via `uv` when using `install.sh` / `install.ps1`).
- **Node.js 20+** (Node.js 22 LTS recommended) — only needed during installation/builds or development.
- **Git** — required for Advanced Mode branching and GitHub sync on Linux/macOS.

---

## Quick Start

### 1. Native Host Install (Recommended)

`install.sh` / `install.ps1` provisions an isolated Python 3.12 virtual environment via `uv`, builds the static frontend bundle (`frontend/dist`) so FastAPI serves both UI and API in one process, generates `0600` cryptographic keys, and runs Alembic migrations.

**Linux / macOS:**

```bash
git clone https://github.com/mohamed-hisham-swidan/onx-manager.git
cd onx-manager

# Interactive (choose VPS Mode or Local Desktop Mode):
./install.sh

# Non-interactive VPS Mode (installs systemd service + `onx` CLI):
./install.sh --mode=vps --port=8000 --yes

# Non-interactive Local Desktop Mode (installs ~/.local/bin/onx + .desktop launcher):
./install.sh --mode=local --port=8000 --yes
```

**Windows (PowerShell — Local Desktop Mode):**

```powershell
git clone https://github.com/mohamed-hisham-swidan/onx-manager.git
cd onx-manager
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```

Manage a native installation with the `onx` CLI:

```bash
onx start     # Start ONX Manager
onx stop      # Stop cleanly
onx restart   # Restart service
onx status    # Show live status and port
onx logs      # Follow logs
onx open      # Ensure running and open browser UI
onx update    # Pull updates and re-run migrations
```

---

### 2. Desktop App (`desktop/` — Linux, macOS & Windows)

A lightweight Electron shell with system tray controls and zero duplicated UI code. By default it supervises your local backend; press `Ctrl+Shift+K` (or use the tray menu) to switch to any remote VPS panel URL.

```bash
cd desktop
npm install
npm start

# Or from the repository root:
npm run desktop
```

Build native installers (`desktop/dist/`) with `npm run build:linux` (`AppImage`) or `npm run build:win` (Windows NSIS `.exe`). See [desktop/README.md](desktop/README.md).

---

### 3. Docker Compose (Containerized Panel + DooD)

Because ONX Manager runs Minecraft servers as Docker containers, a containerized panel needs the opt-in **Docker-outside-of-Docker (`docker-compose.dood.yml`)** override so it can spawn sibling Minecraft containers on the host Docker daemon:

```bash
git clone https://github.com/mohamed-hisham-swidan/onx-manager.git
cd onx-manager
cp .env.example .env

# Export absolute host paths for sibling Minecraft container mounts:
export ONX_HOST_DATA_DIR="$(pwd)/backend/data/servers"
export ONX_HOST_STATE_HOST_DIR="$(pwd)/backend/data/host-state"

docker compose -f docker-compose.yml -f docker-compose.dood.yml up -d
```

Open `http://<your-server-ip>/` (or `http://localhost/`) to complete the `/setup` Owner wizard.

> **Security note:** Mounting `/var/run/docker.sock` gives the backend container root-equivalent access to the host Docker daemon. Running ONX Manager natively on the host (`install.sh`) avoids mounting the socket into a container. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for details.

---

## Platform Support Matrix

| Platform | Installation Options | Server Modes | Notes |
|---|---|---|---|
| **Linux (x86_64 / arm64)** | `install.sh` (`vps` / `local`), Desktop App, Docker Compose + DooD | **Simple + Advanced Git Mode** | Full feature set: branch sandboxes, 3-way config merge, encrypted vaults, safe upgrades |
| **macOS** | `install.sh --mode=local`, Desktop App, Docker Compose + DooD | **Simple + Advanced Git Mode** | Requires Docker Desktop for Minecraft containers |
| **Windows 10/11** | `install.ps1` (`local`), Desktop App (Local or Remote Client) | **Simple Mode** (or Remote Client to a Linux VPS for Advanced) | Windows hosts run Simple Mode natively (`ONX_ADVANCED_MODE_ENABLED=false`). `.mrpack` import and 1-click Safe Upgrades require a POSIX/Linux Docker host |

---

## Feature Matrix

| Area | Capabilities |
|---|---|
| **Server Provisioning** | `Paper` (Fill v3), `Purpur`, `Spigot`, `Vanilla`, `Fabric`, `Forge`, `NeoForge`, `Quilt` + `.mrpack` & CurseForge modpack import, live step/ETA telemetry, automatic Java runtime selection, and `spawn-protection=0` default |
| **Container Runtime & Safety** | Hardened Docker execution (`--cap-drop=ALL`, `no-new-privileges`, `--pids-limit`, non-root UID/GID, loopback-only RCON, memory/CPU caps), host resource budget admission control, and multi-worker lifecycle leases |
| **Console, Files & History** | Live WebSocket console (`stdout` + `stderr` deduplicated) + RCON execution, real-time CPU/RAM/TPS/player metrics, sandboxed file & log browser with syntax editor, and branch-aware Change History |
| **Plugins & Mods** | In-shell Modrinth marketplace & project detail pages, strict Plugins vs Mods separation, dual `Plugin · Mod` support, Modrinth-style version/loader pickers, one-click dependency installs, and validated `.jar` uploads |
| **Safe Upgrades & GitOps** | Per-server Git branches, protected `main`, 3-way structured merge, secret vault & scanner, GitHub sync/webhooks, isolated branch test containers, and 1-click Safe Upgrades with 5-check SLP Health Gate & automatic rollback |
| **Backups & Exposure** | Local snapshots & AES-256-GCM envelope-encrypted archives (local or S3), cron schedules, upgrade-pinned delete locks, plus Playit.gg, Cloudflare Tunnels, UPnP (with CGNAT detection), and live SLP reachability probing |
| **Security & Access Control** | Username-based `/setup` (`LOCAL` or invite-only `GLOBAL`), loopback desktop auto-login with fail-closed password gate before external exposure, RS256 JWT, Argon2id passwords, scoped `onx_` API keys, and RBAC/ABAC verified across `219` routes |

---

## Architecture & Tech Stack

| Layer | Technologies |
|---|---|
| **Backend** | Python 3.12 · FastAPI · SQLAlchemy 2.0 (async) · Alembic (`55` migrations, head `b1e2100000035`) · Pydantic v2 |
| **Frontend** | React 19 · TypeScript 5.5+ · Vite · Tailwind CSS v4 · TanStack Query 5 · Zustand 5 |
| **Database** | SQLite with WAL mode (default) or PostgreSQL 16 |
| **Desktop Shell** | Electron (`desktop/`, sandboxed preload with launcher-scoped IPC) |
| **Auth & Encryption** | RS256 JWT · Argon2id · RBAC/ABAC · AES-256-GCM envelope encryption |

```text
install.sh              Linux/macOS installer (VPS systemd or Local Desktop)
install.ps1             Windows PowerShell installer (Local Desktop)
launcher.py             Unified CLI supervisor & developer launcher
docker-compose.yml      Production web + API compose stack
docker-compose.dood.yml Opt-in DooD override for sibling Minecraft containers
desktop/                Electron desktop shell (Local auto-supervisor & Remote client)
backend/                FastAPI modular monolith (DDD modules, CQRS buses, REST & WS API)
frontend/               React 19 SPA (semantic token design system, multi-skin themes)
contracts/              Route permission contract (219 routes) & schemas
docs/                   Architecture, deployment, API, database, runtime & dev guides
scripts/                CI quality gates, bootstrap & developer helpers
```

---

## Development & Testing

```bash
# Bootstrap backend (.venv on Python 3.12), frontend deps, and DB migrations
./scripts/bootstrap

# Start hot-reloading dev servers (backend :8000, frontend :5173)
python3 launcher.py --dev
```

Run quality gates and test suites:

```bash
# Repository contract & hygiene gates
python3 scripts/check-route-contract
python3 scripts/check-db-revision
python3 scripts/check-ruff-baseline
python3 scripts/check-stray-db
python3 scripts/check-version-propagation

# Backend tests
cd backend && .venv/bin/pytest tests/ -q

# Frontend typecheck, lint, tests, and production build
cd frontend && npx tsc --noEmit && npm run lint && npx vitest run && npm run build

# Desktop tests
cd desktop && npm test
```

---

## `v0.1.0` Scope & Known Limitations

- **Runtime:** Docker is the sole supported Minecraft server runtime (host `tmux` / bare Windows Java execution is not supported).
- **Advanced Git Mode & Safe Upgrades:** Supported on POSIX hosts (Linux/macOS). Windows hosts run Simple Mode natively (`.mrpack` import and 1-click Safe Upgrades require a POSIX/Linux Docker host) and can manage remote Linux Advanced servers via the Desktop Remote client.
- **Modpack Discovery:** Uploading `.mrpack` and CurseForge `.zip` archives is supported today; in-panel Modrinth modpack browsing is planned for `v0.2.0`.
- **Proxy Software (`Velocity`, `BungeeCord`, `Waterfall`):** Container lifecycle and log detection work for imported proxy servers; automated first-class proxy provisioning and upgrades are planned for `v0.2.0`.

---

## Documentation

Full documentation index: [docs/README.md](docs/README.md)

- [Getting Started](docs/getting-started.md) · [Deployment Guide](docs/DEPLOYMENT.md) · [Development Guide](docs/DEVELOPMENT.md)
- [Desktop Wrapper](desktop/README.md) · [API Reference](docs/API.md) · [Testing Guide](docs/testing.md)
- [Architecture](docs/architecture/ARCHITECTURE.md) · [Database](docs/architecture/DATABASE.md) · [Security](docs/architecture/SECURITY.md)
- [Contributing](CONTRIBUTING.md) · [Code of Conduct](CODE_OF_CONDUCT.md) · [Security Policy](SECURITY.md) · [Changelog](CHANGELOG.md)

## Community & Support

- **Discord:** Join the [ONX Manager Discord](https://discord.gg/8AfQMv4CH) for help, feedback, and release updates.
- **Issues & Feature Requests:** Open an issue on [GitHub Issues](https://github.com/mohamed-hisham-swidan/onx-manager/issues).
- **Contributing:** See [CONTRIBUTING.md](CONTRIBUTING.md) and our [Code of Conduct](CODE_OF_CONDUCT.md).

## License

Apache 2.0 — see [LICENSE](LICENSE).
