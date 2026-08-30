<div align="center">

# ONX Manager

**Self-hosted Minecraft server management — from your browser.**

Manage multiple servers, monitor them live, handle backups, browse plugins, and expose them to the internet. All in one dashboard. No cloud required.

[![Python](https://img.shields.io/badge/Python-3.12+-3776ab?style=flat-square&logo=python&logoColor=white)](#)
[![TypeScript](https://img.shields.io/badge/TypeScript-5+-3178c6?style=flat-square&logo=typescript&logoColor=white)](#)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?style=flat-square&logo=fastapi&logoColor=white)](#)
[![React](https://img.shields.io/badge/React-19-61dafb?style=flat-square&logo=react&logoColor=black)](#)
[![License](https://img.shields.io/badge/License-Apache_2.0-green?style=flat-square)](#)
[![Tests](https://img.shields.io/badge/Tests-2021_backend_%7C_574_frontend-brightgreen?style=flat-square)](#)

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

## Quick Start

**Prerequisites:** Python 3.12+, Node.js 20+

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

Both scripts:
1. Create a Python virtual environment
2. Install all dependencies
3. Run database migrations
4. Start the backend + frontend
5. Open your browser to `http://localhost:5173`

On first run you'll be taken to the **setup wizard** to create your admin account.

```bash
# Useful flags (pass to start.bat or ./start.sh)
./start.sh --stop      # Stop everything
./start.sh --restart   # Restart
./start.sh --status    # Check what's running
./start.sh --swagger   # Also open API docs
./start.sh --help      # All options
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
backend/        FastAPI app — domain modules, API, WebSocket
frontend/       React SPA
docs/           Architecture, API reference, guides
scripts/        Dev utilities
launcher.py     One-file bootstrapper and process manager
```

---

## Documentation

| | |
|---|---|
| [Getting Started](docs/getting-started.md) | Full setup guide |
| [Architecture](docs/architecture/ARCHITECTURE.md) | How it's built |
| [API Reference](docs/API.md) | REST endpoints & WebSocket |
| [Development Guide](docs/DEVELOPMENT.md) | Contributing & workflow |

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
