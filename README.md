<div align="center">

<img src="docs/assets/logo.svg" alt="ONX Manager" width="64" height="64" />

# ONX Manager

**Self-hosted Minecraft server management & declarative server engineering — from your browser.**

Manage multiple servers, monitor live telemetry, browse plugins and modpacks, isolate test branches in Docker, and run 1-click safe upgrades with automatic rollback. No cloud panel required.

[![Python](https://img.shields.io/badge/Python-3.12-3776ab?style=flat-square&logo=python&logoColor=white)](#)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.5+-3178c6?style=flat-square&logo=typescript&logoColor=white)](#)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?style=flat-square&logo=fastapi&logoColor=white)](#)
[![React](https://img.shields.io/badge/React-19-61dafb?style=flat-square&logo=react&logoColor=black)](#)
[![License](https://img.shields.io/badge/License-Apache_2.0-green?style=flat-square)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-5293_backend_%7C_137_frontend_suites-brightgreen?style=flat-square)](docs/testing.md)

</div>

<!-- TODO(HUMAN): Add demo GIF/video, screenshots, and community links (e.g., Discord, GitHub Discussions) -->

---

## What is this?

ONX Manager is a **self-hosted web dashboard** for running and engineering Minecraft servers on your own machine or VPS. Run everyday servers in **Simple Mode**, or enable **Advanced Mode** (POSIX hosts) for Git-backed configuration versioning, isolated branch runtimes, encrypted state vaults, GitHub sync, and 1-click safe modpack upgrades.

---

## Features

### 🖥️ Server Management & Provisioning
- Create, import (directory scan or `.zip` upload), start, stop, restart, and delete servers from the dashboard
- Supports **Vanilla, Paper (Fill v3), Spigot, Purpur, Fabric, Forge, NeoForge, and Quilt** — with automatic JAR/installer provisioning and deterministic Java floor resolution
- **Modpack Install Wizard**: Inspect and install `.mrpack` (Modrinth) and CurseForge modpacks via a strict 19-host HTTPS download allow-list and shared **Loader Environment Cache (LEC)**
- Isolated **Docker container** runtime (`DockerProvider` with `--cap-drop=ALL`, non-root `--user`, `--pids-limit=2048`, bridge networking, loopback RCON, and opt-in DooD support)

### 🌿 Simple/Advanced Modes & Git-Native Versioning
- **Simple vs Advanced Mode & Live Conversion**: Zero-friction server management in Simple Mode, or declarative Git-backed branches, commits, tags, protected `main`, and 3-way structured config merge (`YAML`, `TOML`, `JSON`, `.properties`, `diff3`) in Advanced Mode (POSIX hosts), with live Simple ↔ Advanced conversion endpoints
- **Encrypted Vaults & Secret Scanner**: AES-256-GCM Class-C state snapshots (`format_version=2`) and `${ONX_SECRET_*}` secret vault with structured secret scanning
- **Isolated Branch Runtimes & Bot Testing**: Spin up parallel branch test containers with atomic host port sets, ephemeral Class-C overlays, quiescent Data Templates, live RCON console, and FakePlayer/Mineflayer bot test drivers
- **GitHub Sync & Webhooks**: Fetch-first remote sync, non-fast-forward `main` guards, deploy-key credential vault, and HMAC-verified webhook ingress
- **1-Click Safe Upgrades & Triad Rollback**: Hash-only Modrinth compatibility matrix + transitive dependency BFS, NBT `level.dat` `DataVersion` verification, 4-step Health Gate, and automatic Triad Rollback on failure

### 📟 Live Console, Telemetry & File Manager
- Full live console over WebSocket with interactive command input and sub-second CPU, RAM, TPS, and player count graphs
- Browser File Manager with syntax-highlighted config editor, upload/download, and path-traversal sandboxing

### 💾 Two-Tier Backups, Marketplace & Network Exposure
- Scheduled and manual two-tier backups (Tier-1 snapshots + Tier-2 archives with chunked **AES-256-GCM envelope encryption**), SHA-256 verification, S3/local storage backends, and pinned rollback protection
- First-class **Modrinth Marketplace** with version compatibility matching, custom `.jar` upload, and on-disk reconciliation
- Built-in **Playit.gg tunnels**, **Cloudflare Named Tunnels**, and **UPnP** port forwarding

### 🔐 Auth, RBAC & Operations
- First-run Owner bootstrap wizard (`/setup`) with `LOCAL` and `GLOBAL` access modes and invitation links (`/invite/:token`)
- RS256 JWT authentication, Argon2id password hashing, scoped `onx_` API keys, and RBAC/ABAC verified across **213 live routes**
- Multi-step async `Operation` engine with idempotency keys, Prometheus `/metrics`, and configurable alerts

---

## Quick Start

### Option 1: Docker Compose

```bash
git clone https://github.com/mohamed-hisham-swidan/onx-manager.git
cd onx-manager
cp .env.example .env
docker compose up -d
```

For managing sibling Minecraft containers from inside Docker (Docker-outside-of-Docker), see the opt-in `docker-compose.dood.yml` profile and security guidance in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

### Option 2: Zero-Config Local Launcher

If Python 3.12 or Node.js is missing, the launcher installs them automatically (portable runtimes on Windows with zero administrator rights; package managers or `uv` on Linux/macOS).

```cmd
:: Windows
git clone https://github.com/mohamed-hisham-swidan/onx-manager.git
cd onx-manager
start.bat
```

```bash
# Linux / macOS
git clone https://github.com/mohamed-hisham-swidan/onx-manager.git
cd onx-manager
./start.sh
```

Open `http://localhost:5173` (local launcher) or `http://localhost:80` (Docker) to complete the first-run **Setup Wizard** and create your Owner account.

```bash
# Useful launcher flags (start.bat or ./start.sh)
./start.sh --stop          # Stop all running services
./start.sh --restart       # Restart backend and frontend
./start.sh --status        # View live process status & ports
./start.sh --logs          # View aggregated service logs
./start.sh --swagger       # Open Swagger API docs
./start.sh --help          # Show all options
```

---

## Tech Stack

| | |
|---|---|
| **Backend** | Python 3.12 · FastAPI · SQLAlchemy 2.0 async · Alembic (`52` revisions) · Pydantic v2 |
| **Frontend** | React 19 · TypeScript 5.5+ · Vite 5.4+ · TailwindCSS 4 · TanStack Query 5 · Zustand 5 |
| **Database** | SQLite (default, zero config) or PostgreSQL 16 |
| **Auth & Crypto** | JWT RS256 · Argon2id · RBAC/ABAC · AES-256-GCM vaults & backups |
| **Tunnels & Sync** | Playit.gg · Cloudflare Tunnels · UPnP · Git / GitHub |
| **Monitoring** | Prometheus `/metrics` · structlog · Persistent RCON |

---

## Project Layout

```text
backend/        FastAPI modular monolith — 13 DDD modules, CQRS, API, WebSocket
frontend/       React 19 SPA — multi-skin design system, dashboard, wizards
contracts/      OpenAPI, events, permissions (211 routes), plugin & config schemas
docs/           Architecture, API reference, database schema, runtime & guides
scripts/        Preflight cleanup, CI quality gates, bootstrap & dev utilities
executors/      Tracing and diagnostic launchers (Windows & Unix)
launcher.py     Unified launcher, prerequisite gate, and process manager
start.bat       Windows launcher entry point (delegates to scripts/start.ps1)
start.sh        Linux/macOS launcher entry point
```

---

## Documentation

Full documentation index: [`docs/README.md`](docs/README.md).

| | |
|---|---|
| [Getting Started](docs/getting-started.md) | Setup & quickstart guide |
| [Deployment Guide](docs/DEPLOYMENT.md) | Docker Compose, DooD & production env configuration |
| [Architecture](docs/architecture/ARCHITECTURE.md) | System architecture, DDD modules & P1–P5.5 overview |
| [Technical Specs](docs/architecture/SPECS.md) | Tech stack, repository metrics & feature inventory |
| [Database Architecture](docs/architecture/DATABASE.md) | Schema (`56` tables), `52` Alembic migrations & reconciler |
| [API Reference](docs/API.md) | REST endpoints (`19` router files, `213` routes) & WebSocket protocol |
| [Development Guide](docs/DEVELOPMENT.md) | Local development workflow & preflight reconciliation |
| [Testing Guide](docs/testing.md) | Test suites & CI verification gates |
| [Roadmap](docs/roadmap/ROADMAP.md) | Public post-launch roadmap |
| [Contributing](CONTRIBUTING.md) | Contribution guidelines, governance & quality gates |
| [Security Policy](SECURITY.md) | Vulnerability reporting & supported versions |
| [Changelog](CHANGELOG.md) | Release history |

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
