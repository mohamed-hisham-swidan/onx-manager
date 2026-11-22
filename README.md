<div align="center">

<img src="docs/assets/logo.svg" alt="ONX Manager" width="64" height="64" />

# ONX Manager

**Self-hosted Minecraft server panel & declarative GitOps engine — without cloud bloat or Redis.**

Manage multiple servers, stream live console & telemetry, isolate plugin/mod changes in ephemeral branch containers, and execute 1-click safe upgrades with automatic rollback — in a **VPS panel**, **one-line native install**, or **Desktop app**.

[![Python](https://img.shields.io/badge/Python-3.12-3776ab?style=flat-square&logo=python&logoColor=white)](#)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.5+-3178c6?style=flat-square&logo=typescript&logoColor=white)](#)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?style=flat-square&logo=fastapi&logoColor=white)](#)
[![React](https://img.shields.io/badge/React-19-61dafb?style=flat-square&logo=react&logoColor=black)](#)
[![License](https://img.shields.io/badge/License-Apache_2.0-green?style=flat-square)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-5296_backend_%7C_1338_frontend_%7C_138_suites-brightgreen?style=flat-square)](docs/testing.md)

</div>

<!-- TODO(HUMAN): Add a short demo GIF or walkthrough video showing Create Server, Branch Testing, and 1-Click Safe Upgrade -->
<!-- TODO(HUMAN): Add 2-3 high-resolution UI screenshots (Command Center, Branch Graph, Exposure/Playit) -->
<!-- TODO(HUMAN): Add community links (Discord / Matrix / GitHub Discussions) before posting publicly -->

---

## Why ONX Manager?

Most Minecraft panels either give you a bare process wrapper or require multi-container infrastructure (databases + Redis + separate Wings daemons) just to edit configs safely.

ONX Manager ships as a **single modular monolith** (SQLite + in-process async task queue, zero Redis, zero runtime Node.js required in production) built for server admins who want real engineering safety nets:

- **Simple Mode vs. Advanced GitOps Mode**: Run everyday servers in zero-friction **Simple Mode**, or enable **Advanced Mode** (POSIX hosts) for Git-backed config branches, protected `main`, and live **Simple ↔ Advanced** conversion.
- **Isolated Branch Runtimes & Bot Testing**: Spin up parallel branch test containers with atomic port sets, ephemeral AES-256-GCM state overlays, quiescent Data Templates, live RCON console, and FakePlayer/Mineflayer bot test drivers — without risking production players or worlds.
- **1-Click Safe Upgrades & Automatic Triad Rollback**: Hash-verified Modrinth compatibility matrix + transitive dependency BFS, NBT `level.dat` `DataVersion` verification, 4-step Health Gate, and automatic **Triad Rollback** if an upgrade fails health checks.
- **3-Way Structured Config Merge**: Semantic 3-way merge across `YAML`, `TOML`, `JSON`, `.properties`, and `diff3` — plus secret extraction (`${ONX_SECRET_*}`) and a structured secret scanner so tokens never leak into Git commits.
- **Built-in Zero-Port-Forward Exposure**: First-class **Playit.gg** tunnels, **Cloudflare Named Tunnels**, and **UPnP** management directly in the panel.
- **Two-Tier Envelope-Encrypted Backups**: Tier-1 snapshots + Tier-2 chunked **AES-256-GCM envelope-encrypted** archives, SHA-256 verification, and local or S3 storage.
- **GUI-First Onboarding (`local` vs `vps` Profiles)**: Auto-generates `0600` cryptographic keys on first boot and opens straight into the `/setup` Owner wizard — zero terminal user creation required. Run as a full **VPS panel** (`ONX_DEPLOYMENT_PROFILE=vps`) or a streamlined **Local Desktop panel** (`ONX_DEPLOYMENT_PROFILE=local`).

---

## Quick Start

### 1. Docker Compose (Recommended for VPS)

```bash
git clone https://github.com/mohamed-hisham-swidan/onx-manager.git
cd onx-manager
cp .env.example .env
docker compose up -d
```

Open `http://<your-server-ip>/` (or `http://localhost/`) in your browser to create your Owner account in `/setup`.

> **Standard Compose vs. Docker-outside-of-Docker (`docker-compose.dood.yml`):**
> - **`docker-compose.yml`**: Runs the Nginx frontend + FastAPI backend in two clean containers with persistent volumes (`onx-db-data`, `onx-server-data`, `onx-config`).
> - **`docker-compose.dood.yml`**: Opt-in override (`docker compose -f docker-compose.yml -f docker-compose.dood.yml up -d`) that mounts `/var/run/docker.sock` and translates `ONX_HOST_DATA_DIR` / `ONX_HOST_STATE_HOST_DIR` so a containerized panel can spawn isolated sibling Minecraft containers and Branch Runtimes on the host Docker daemon. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the security model and exact env configuration.

---

### 2. One-Line Native Installer (`install.sh` / `install.ps1`)

Provisions an isolated **Python 3.12** runtime via `uv`, builds the static SPA bundle (single-process FastAPI serving with zero Node.js runtime dependency afterward), auto-generates `0600` keys, and runs Alembic migrations.

**Linux / macOS (interactive choice between VPS Mode and Local Desktop Mode):**

```bash
curl -fsSL https://raw.githubusercontent.com/mohamed-hisham-swidan/onx-manager/master/install.sh | bash
```

Or run non-interactively from a local clone:

```bash
# VPS Mode: installs systemd unit (onx-manager.service) + `onx` CLI
./install.sh --mode=vps --port=8000 --yes

# Local Desktop Mode: installs ~/.local/bin/onx + native .desktop app launcher
./install.sh --mode=local --port=8000 --yes
```

**Windows (PowerShell — Local Desktop Mode):**

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```

Manage a native install with the unified `onx` CLI:

```bash
onx start     # Start ONX Manager (systemd on VPS or background supervisor locally)
onx stop      # Stop cleanly
onx restart   # Restart service
onx status    # Show live status and ports
onx logs      # Follow logs
onx open      # Ensure running and open browser GUI
onx update    # Pull updates and re-run migrations
```

---

### 3. Desktop App (`desktop/` — Windows & Linux)

A lightweight, single-window Electron wrapper with system tray controls and zero duplicated UI code:

- **Local Mode (Default)**: Silently starts and supervises your local Python 3.12 ONX backend in the background (no console popups), waits for `/health`, and loads the panel directly inside the app.
- **Remote Mode**: Connect to any VPS or a friend's shared ONX Manager URL (including Cloudflare Tunnels) and switch targets anytime with `Ctrl+Shift+K`.

```bash
cd desktop
npm install
npm start

# Or directly from the repository root:
npm run desktop
```

Build native installers (`desktop/dist/`) with `npm run build:win` (Windows NSIS `.exe`) or `npm run build:linux` (Linux `AppImage`). See [desktop/README.md](desktop/README.md).

---

## Platform Support Matrix

| Platform | Deployment Options | ServerMode Support | Notes |
|---|---|---|---|
| **Linux (x86_64 / arm64)** | Docker Compose, DooD, `install.sh` (`vps` / `local`), Desktop App | **Simple Mode + Advanced GitOps Mode** | Full feature set: Branch Runtimes, 3-way merge, encrypted Class-C vaults, Safe Upgrades |
| **macOS** | `install.sh --mode=local`, Docker Compose, Desktop App | **Simple Mode + Advanced GitOps Mode** | Uses `onx` CLI; Docker Desktop required for Docker server runtime |
| **Windows 10/11** | `install.ps1` (`local`), Desktop App (Local or Remote Client), WSL2 Docker | **Simple Mode** (+ Desktop Remote Client to Linux VPS for Advanced) | Windows host is intentionally Simple-only & fail-closed (`ONX_ADVANCED_MODE_ENABLED=false`) |

---

## Key Capabilities

| Area | Highlights |
|---|---|
| **Server Provisioning** | Vanilla, Paper (Fill v3), Spigot, Purpur, Fabric, Forge, NeoForge, Quilt + `.mrpack` & CurseForge modpack wizard with strict 19-host download allow-list and Loader Environment Cache (LEC) |
| **GitOps & Testing** | Per-server Git branches/commits/tags, protected `main`, 3-way structured merge, Class-C encrypted snapshots (`format_version=2`), secret vault, GitHub sync/webhooks, FakePlayer/Mineflayer bot test runs |
| **Console & Files** | WebSocket live console, real-time CPU/RAM/TPS/player telemetry, syntax-highlighted browser file editor, directory/ZIP import |
| **Backups & Plugins** | Two-tier backups (Tier-1 snapshot + Tier-2 AES-256-GCM envelope archive), S3 or local storage, Modrinth marketplace, custom `.jar` upload |
| **Security & Auth** | GUI `/setup` bootstrap (`LOCAL` or `GLOBAL` invite-only access), RS256 JWT, Argon2id passwords, `onx_` API keys, RBAC/ABAC verified across `213` live routes, Prometheus `/metrics` |

---

## Tech Stack

| | |
|---|---|
| **Backend** | Python 3.12 · FastAPI · SQLAlchemy 2.0 async · Alembic (`52` revisions) · Pydantic v2 |
| **Frontend** | React 19 · TypeScript 5.5+ · Vite 5.4+ · TailwindCSS 4 · TanStack Query 5 · Zustand 5 |
| **Database** | SQLite with WAL mode (default, zero config) or PostgreSQL 16 |
| **Desktop Wrapper** | Electron (`desktop/`, optional thin shell with Local & Remote switcher) |
| **Auth & Crypto** | RS256 JWT · Argon2id · RBAC/ABAC · AES-256-GCM vaults & two-tier backups |
| **Tunnels & Sync** | Playit.gg · Cloudflare Tunnels · UPnP · Git / GitHub |

---

## Project Layout

```text
install.sh              POSIX installer (VPS systemd mode or Local Desktop mode)
install.ps1             Windows PowerShell installer (Local Desktop mode + shortcuts)
docker-compose.yml      Production Docker Compose stack (Nginx + FastAPI)
docker-compose.dood.yml Opt-in Docker-outside-of-Docker override for container runtimes
desktop/                Thin Electron desktop shell (Local auto-supervisor & Remote client)
backend/                FastAPI modular monolith — 13 DDD modules, CQRS, API, WebSocket
frontend/               React 19 SPA — multi-skin design system, dashboard, wizards
contracts/              OpenAPI, events, permissions (213 routes), plugin & config schemas
docs/                   Architecture, deployment, API, database, runtime & dev guides
scripts/                CI quality gates, preflight cleanup, bootstrap & developer utilities
launcher.py             Unified CLI service supervisor & developer launcher
```

---

## Documentation

Full index: [`docs/README.md`](docs/README.md)

| Guide | Description |
|---|---|
| [Getting Started](docs/getting-started.md) | 5-minute quickstart (Docker, `install.sh` / `install.ps1`, Desktop App, or Manual) |
| [Deployment Guide](docs/DEPLOYMENT.md) | Docker Compose, DooD, bare-metal VPS `systemd`, `ONX_DEPLOYMENT_PROFILE` & env vars |
| [Development Guide](docs/DEVELOPMENT.md) | Local dev workflow (`launcher.py --dev`), preflight, migrations & debugging |
| [Desktop Wrapper](desktop/README.md) | Running, testing, and building Windows/Linux desktop packages |
| [Architecture](docs/architecture/ARCHITECTURE.md) | Modular monolith, 13 DDD bounded contexts & Simple/Advanced architecture |
| [Database Architecture](docs/architecture/DATABASE.md) | Schema (`56` tables), `52` Alembic migrations (`b1e2100000032`) & reconciler |
| [API Reference](docs/API.md) | REST endpoints (`213` live routes) & `/ws` WebSocket protocol |
| [Testing Guide](docs/testing.md) | Backend, frontend, desktop & 6 CI quality gates |
| [Contributing](CONTRIBUTING.md) | Contribution workflow, governance & code conventions |
| [Security Policy](SECURITY.md) | Vulnerability reporting & key-handling practices |
| [Changelog](CHANGELOG.md) | Release history |

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
