# Minecraft Server Manager

[![Build Status](https://img.shields.io/badge/build-passing-brightgreen.svg)](#)
[![Tests](https://img.shields.io/badge/tests-2021%20backend%20%7C%20574%20frontend-brightgreen.svg)](#)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](#)
[![TypeScript](https://img.shields.io/badge/typescript-5%2B-blue.svg)](#)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](#)
[![Status](https://img.shields.io/badge/status-production%20ready-darkgreen.svg)](#)

A professional-grade Minecraft server management platform. Manage any number of servers across local, Docker, or remote providers from a single web dashboard. Ships with a plugin system, automated backups, RBAC auth, and full monitoring — all self-hosted. (Authorization is fully enforced for mutating and server-scoped routes; a small set of auth-only GET reads and Ops items are documented as residual gaps.)

---

## Features

- **Server Lifecycle** — Create, start, stop, restart, and configure Minecraft servers (vanilla, Paper, Forge, Fabric, NeoForge, etc.). Full provisioning with JAR validation, type-specific URL resolution, and background auto-retry for transient failures.
- **File Manager** — In-browser file explorer and text editor for server directories. Path-sandboxed REST API supporting file read/write, uploads, downloads, and directory creation.
- **Backup & Restore** — Automatic scheduled backups with AES-256-GCM encryption, integrity verification, and point-in-time restoration. Idempotent sagas with compensation rollbacks.
- **WebSocket Live Console** — Real-time server console and metrics streaming over WebSocket with channel-based subscriptions, auto-reconnect with exponential backoff, and state sync on recovery.
- **Plugin System** — Subprocess-isolated plugins with JSON-RPC over stdin/stdout. Filesystem and network sandboxing. Recursive dependency resolution. Full SDK with event hooks, command execution, and scoped HTTP client.
- **Auth & RBAC/ABAC** — JWT RS256 authentication with 900s access tokens and rotated refresh tokens. Role-based access with attribute-based policy evaluation. API key authentication (`mcs_`-prefixed, SHA-256 hashed).
- **Monitoring** — Prometheus metrics (TPS, players, RAM, CPU). Real-time WebSocket metrics push. Health check registry covering DB, disk, and provider backends. Configurable alert rules with Discord/Telegram/Email delivery.
- **Marketplace** — Browse and install Minecraft plugins from Modrinth, with filesystem-as-truth reconciliation between the database and the `plugins/` directory. First-class global `/marketplace` route with server picker.
- **REST API** — Auto-generated OpenAPI spec. Full CRUD for servers, backups, plugins, files, users, and settings. File-backed settings persistence (`config/settings.yaml`) with consumer hot-reload. Rate-limited, audited, and permission-checked.

## Architecture

```
Browser ──► FastAPI (Backend) ──► PostgreSQL / SQLite
CLI     ──►                     ──► In-process task queue
Plugins ──►  Command / Query / Event Buses ──► Subprocess Plugins
```

A **modular monolith** with hexagonal architecture. Every bounded context (Server, Backup, Plugin, Monitoring, User & Auth, etc.) defines ports in its domain layer and adapters in infrastructure. The core provides CQRS buses, Unit of Work, circuit breakers, feature flags, and saga orchestration consumed by all modules. See [Architecture Overview](docs/architecture/ARCHITECTURE.md).

## Quick Start

```bash
git clone <repo-url> onx-manager
cd onx-manager
python launcher.py
```

The launcher bootstraps the virtual environment, installs dependencies, runs migrations, and starts both backend and frontend. The first-run wizard creates your admin account.

```bash
# Optional flags
python launcher.py --swagger   # Also open Swagger API docs
python launcher.py --code      # Also open VS Code
python launcher.py --help      # Show all options
```

Detailed setup in [Getting Started](docs/getting-started.md).

## Screenshots

> Screenshots coming soon.

## Documentation

| Area | Link |
|---|---|
| Full Doc Index | [docs/README.md](docs/README.md) |
| Canonical Roadmap | [docs/roadmap/ROADMAP.md](docs/roadmap/ROADMAP.md) |
| Architecture | [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md) |
| API Reference | [docs/API.md](docs/API.md) |
| Database Schema | [docs/architecture/DATABASE.md](docs/architecture/DATABASE.md) |
| Security | [docs/architecture/SECURITY.md](docs/architecture/SECURITY.md) |
| Frontend | [docs/architecture/FRONTEND.md](docs/architecture/FRONTEND.md) |
| Development Guide | [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) |

## Project Structure

```
backend/            Python FastAPI application — core, domain modules, API, WebSocket, plugin SDK
frontend/           React 19 + TypeScript SPA — TanStack Query, Zustand, TailwindCSS
docs/               Architecture, API, security, database, development guides
scripts/            Utility scripts for dev, deployment, and maintenance
.onx/               Runtime state directory (PIDs, logs, sockets — gitignored)
launcher.py         Single-file entry point — bootstraps the full application
start.sh            Production startup script
```

## Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.12+, FastAPI, SQLAlchemy 2.0 (async), Alembic, Pydantic v2, structlog |
| **Frontend** | TypeScript 5+, React 19, Vite, TailwindCSS 4+, TanStack Query, Zustand |
| **Databases** | PostgreSQL 16 (production), SQLite 3 (embedded/desktop) |
| **Infrastructure** | Docker (optional provider), Prometheus (metrics), in-process task queue |

## Development

See [Development Guide](docs/DEVELOPMENT.md) for full setup, virtual environment, migration commands, testing strategy, and code conventions.

```bash
pytest                    # All backend tests (2021 passing)
pytest tests/unit/        # Unit tests only
cd frontend && npm test   # Frontend tests (574 passing)
```

## Contributing

See [Contributing](docs/CONTRIBUTING.md) for the contribution workflow, code conventions, git conventions, and cross-batch protocol.

## License

MIT — see LICENSE for details.

## Status

**Production-ready core.** Phases 0–7 complete (2026-08-23). Backend, API, WebSocket, plugin system, auth, monitoring, File Manager, Forge/NeoForge provisioning, Marketplace, and network exposure (Playit.gg tunnels) are all implemented and tested. Current: **2021 backend tests passing**, **574 frontend tests passing**. Phase 8 (Dynamic Endpoints & DNS) is next. Known residual gaps tracked in [`docs/current-state.md`](docs/current-state.md).
