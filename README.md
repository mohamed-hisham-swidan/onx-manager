# Minecraft Server Manager

[![Build Status](https://img.shields.io/badge/build-passing-brightgreen.svg)](#)
[![Tests](https://img.shields.io/badge/tests-984%20passing-brightgreen.svg)](#)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](#)
[![TypeScript](https://img.shields.io/badge/typescript-5%2B-blue.svg)](#)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](#)
[![Status](https://img.shields.io/badge/status-production%20ready-darkgreen.svg)](#)

A professional-grade Minecraft server management platform. Manage any number of servers across local, Docker, or remote providers from a single web dashboard. Ships with a plugin system, automated backups, real-time WebSocket console, RBAC+ABAC auth, and full monitoring — all self-hosted.

---

## Features

- **Server Lifecycle** — Create, start, stop, restart, and configure Minecraft servers (vanilla, Paper, Forge, Fabric, etc.). Full provisioning with JAR validation and type-specific URL resolution.
- **Backup & Restore** — Automatic scheduled backups with AES-256-GCM encryption, integrity verification, and point-in-time restoration. Idempotent sagas with compensation rollbacks.
- **WebSocket Live Console** — Real-time server console streaming with channel-based subscriptions, offline message buffering, auto-reconnect with exponential backoff, and state sync on recovery.
- **Plugin System** — Subprocess-isolated plugins with JSON-RPC over stdin/stdout. Filesystem and network sandboxing. Recursive dependency resolution. Full SDK with event hooks, command execution, and scoped HTTP client.
- **Auth & RBAC/ABAC** — JWT RS256 authentication with 900s access tokens and rotated refresh tokens. Role-based access with attribute-based policy evaluation. API key authentication (`mcs_`-prefixed, SHA-256 hashed).
- **Monitoring** — Prometheus metrics (TPS, players, RAM, CPU). Health check registry covering DB, Redis, disk, and provider backends. Configurable alert rules with Discord/Telegram/Email delivery.
- **REST API** — Auto-generated OpenAPI spec. Full CRUD for servers, backups, plugins, users, and settings. Rate-limited, audited, and permission-checked.

## Architecture

```
Browser ──► FastAPI (Backend) ──► PostgreSQL / SQLite
CLI     ──►                     ──► Redis (Cache + WS Pub/Sub)
Plugins ──►  Command / Query / Event Buses ──► Subprocess Plugins
```

A **modular monolith** with hexagonal architecture. Every bounded context (Server, Backup, Plugin, Monitoring, User & Auth, etc.) defines ports in its domain layer and adapters in infrastructure. The core provides CQRS buses, Unit of Work, circuit breakers, feature flags, and saga orchestration consumed by all modules. See [Architecture Overview](docs/ARCHITECTURE.md).

## Quick Start

```bash
git clone https://github.com/your-org/minecraft-server-manager.git
cd minecraft-server-manager
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
python launcher.py
```

Then open `http://localhost:8000` — the first-run wizard creates your admin account. Detailed setup in [Getting Started](docs/getting-started.md).

## Screenshots

> Screenshots coming soon.

## Documentation

| Area | Link |
|---|---|
| Full Doc Index | [docs/README.md](docs/README.md) |
| Architecture | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| API Reference | [docs/API.md](docs/API.md) |
| Database Schema | [docs/DATABASE.md](docs/DATABASE.md) |
| Security | [docs/SECURITY.md](docs/SECURITY.md) |
| Frontend | [docs/FRONTEND.md](docs/FRONTEND.md) |
| Development Guide | [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) |
| Roadmap | [docs/roadmap.md](docs/roadmap.md) |

## Project Structure

```
backend/            Python FastAPI application — core, domain modules, API, WebSocket, plugin SDK
frontend/           React 19 + TypeScript SPA — TanStack Query, Zustand, TailwindCSS
docs/               Architecture, API, security, database, development guides
scripts/            Utility scripts for dev, deployment, and maintenance
run/                Runtime artifacts (logs, sockets, PID files)
.mcs/               Local server manager state directory
launcher.py         Single-file entry point — bootstraps the application
start.sh            Production startup script
Implementation/     Project state tracking, module map, roadmap, vision
```

## Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.12+, FastAPI, SQLAlchemy 2.0 (async), Alembic, Pydantic v2, structlog |
| **Frontend** | TypeScript 5+, React 19, Vite, TailwindCSS 4+, shadcn/ui, TanStack Query, Zustand |
| **Databases** | PostgreSQL 16 (production), SQLite 3 (embedded/desktop), Redis (cache + WS + queue) |
| **Infrastructure** | Docker (optional provider), Prometheus (metrics), Arq/Redis (production task queue) |

## Development

See [Development Guide](docs/DEVELOPMENT.md) for full setup, virtual environment, migration commands, testing strategy, and code conventions.

```bash
pytest                    # All tests
pytest tests/unit/        # Unit tests
pytest tests/e2e/         # E2E tests (with Docker)
```

## Contributing

See [Contributing](docs/CONTRIBUTING.md) for the contribution workflow, code conventions, git conventions, and cross-batch protocol.

## License

MIT — see LICENSE for details.

## Status

**Production-ready.** 9 of 10 implementation batches complete (82% overall). Backend core, API, WebSocket, plugin system, auth, monitoring, and task scheduling are fully implemented and tested. Frontend (Batch 10) is the remaining scope. 280+ tests passing across all completed batches.
