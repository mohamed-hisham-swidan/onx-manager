<div align="center">

# ONX Manager

**Self-hosted Minecraft server management — from your browser.**

Manage multiple servers, monitor them live, handle backups, browse plugins, and expose them to the internet. All in one dashboard. No cloud required.

[![Python](https://img.shields.io/badge/Python-3.12+-3776ab?style=flat-square&logo=python&logoColor=white)](#)
[![TypeScript](https://img.shields.io/badge/TypeScript-5+-3178c6?style=flat-square&logo=typescript&logoColor=white)](#)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?style=flat-square&logo=fastapi&logoColor=white)](#)
[![React](https://img.shields.io/badge/React-19-61dafb?style=flat-square&logo=react&logoColor=black)](#)
[![License](https://img.shields.io/badge/License-Apache_2.0-green?style=flat-square)](#)
[![Tests](https://img.shields.io/badge/Tests-2346_backend_%7C_642_frontend-brightgreen?style=flat-square)](#)

</div>

---

## What is this?

ONX Manager is a **self-hosted web dashboard** for running Minecraft servers on your own machine or VPS. You get a clean UI to create and control servers, watch the live console, manage files, set up automated backups, and even expose your server to the internet through tunnels — all without touching the command line after setup.

It's built for people who want full control over their servers without relying on paid hosting panels.

---

## Features

### 🖥️ Server Management
- Create, start, stop, restart, and delete servers from the dashboard
- Supports **Vanilla, Paper, Spigot, Purpur, Fabric, Forge, NeoForge** — with automatic JAR download and version selection
- Multi-runtime execution: host processes (tmux on Linux, native Win32 on Windows) and isolated Docker containers (Phase 5 in progress)
- Real-time status updates — no page refresh needed
- Server provisioning with automatic retry on network failures

### 📟 Live Console & Metrics
- Full live console with command input — just type and hit enter
- Real-time CPU, RAM, TPS, and player count graphs
- WebSocket-based — sub-second latency

### 📁 File Manager
- Browse, edit, upload, and download server files directly from the browser
- Syntax-highlighted text editor for configs (`server.properties`, etc.)
- Protected against path traversal and sensitive file access

### 💾 Backups
- Scheduled and manual backups with **AES-256-GCM encryption**
- Point-in-time restore — pick any backup and restore in one click
- Integrity verification built in

### 🧩 Plugin Marketplace
- Browse and install plugins from **Modrinth** directly from the dashboard
- Filter by Minecraft version, loader, category
- Installed plugins tracked and synced to disk

### 🌐 Network & Exposure
- Expose your server to the internet via **Playit.gg tunnels** — no port forwarding needed
- See your public address from the dashboard
- Works behind NAT, CGNAT, and firewalls

### 🔐 Auth & Multi-User
- JWT-based authentication (RS256, 15-min access tokens + 7-day refresh)
- Role-based access control — Owner, Admin, Member
- Invitation system for private servers (LOCAL vs GLOBAL access modes)
- API key support for automation

### 📊 Monitoring & Alerts
- Prometheus metrics endpoint
- Configurable alerts — Discord, Telegram, Email
- Health checks for DB, disk, and all provider backends

---

## Quick Start (Zero Config)

**Automated Setup**: If Python 3.12+ or Node.js 22 LTS is missing, the launcher will **automatically install** them with zero administrator rights required.

### Windows

```cmd
git clone https://github.com/mohamed-hisham-swidan/onx-manager.git
cd onx-manager
start.bat
```

### Linux / macOS

```bash
git clone https://github.com/mohamed-hisham-swidan/onx-manager.git
cd onx-manager
./start.sh
```

### What the Launcher Does Automatically:
1. **Prerequisite Gate**: Probes and verifies Python 3.12+, Node.js 22 LTS, and npm upfront before starting any server.
2. **Auto-Installation**: Automatically downloads and configures Python and portable Node.js 22 LTS if not present on your system.
3. **Dependency Management**: Creates the Python virtual environment and installs backend/frontend dependencies (`pip` & `npm install`).
4. **Database Readiness**: Automatically reconciles and applies database schema migrations to the latest revision.
5. **Service Lifecycle**: Starts the FastAPI async backend and React 19 frontend with real-time health checks.
6. **Instant Launch**: Opens your browser directly to `http://localhost:5173`.

On first run you'll be taken to the **setup wizard** to create your admin account.

```bash
# Useful flags (pass to start.bat or ./start.sh)
./start.sh --stop          # Stop all running services
./start.sh --restart       # Restart backend and frontend
./start.sh --status        # View live process status & ports
./start.sh --logs          # View aggregated service logs
./start.sh --install-node  # Install Node.js 22 LTS
./start.sh --swagger       # Open Swagger API docs
./start.sh --help          # Show all options
```

---

## Tech Stack

| | |
|---|---|
| **Backend** | Python 3.12 · FastAPI · SQLAlchemy 2.0 async · Alembic · Pydantic v2 |
| **Frontend** | React 19 · TypeScript 5 · Vite · TailwindCSS 4 · TanStack Query · Zustand |
| **Database** | SQLite (default, zero config) or PostgreSQL |
| **Auth** | JWT RS256 · RBAC/ABAC · API keys |
| **Tunnels** | Playit.gg |
| **Monitoring** | Prometheus |

---

## Project Layout

```
backend/        FastAPI app — domain modules, CQRS, API, WebSocket
frontend/       React 19 SPA — Blade Hosting dashboard
docs/           Architecture, API reference, database schema, guides
scripts/        Preflight cleanup, CI baseline gates, and dev utilities
executors/      Tracing and diagnostic launchers (Windows & Unix)
launcher.py     Unified launcher, prerequisite gate, and process manager
start.bat       Windows launcher entry point (UTF-8, VT processing)
start.ps1       PowerShell bootstrap engine with candidate probes
start.sh        Linux/macOS launcher entry point (auto Node.js installer)
```

---

## Documentation

| | |
|---|---|
| [Getting Started](docs/getting-started.md) | Full setup & quickstart guide |
| [Architecture](docs/architecture/ARCHITECTURE.md) | System architecture & DDD modular monolith |
| [Database Architecture](docs/architecture/DATABASE.md) | Schema, migrations & pre-backend reconciliation |
| [API Reference](docs/API.md) | REST endpoints (15 routers) & WebSocket protocols |
| [Development Guide](docs/DEVELOPMENT.md) | Development workflow & preflight reconciliation |
| [Testing Guide](docs/testing.md) | Test suites & CI verification gates |

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
