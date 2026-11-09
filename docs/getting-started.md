# Getting Started

A 5-minute quickstart for running ONX Manager on your machine.

## Prerequisites

- **Python** 3.12 (exact; 3.13/3.14 are not supported by the installer)
- **Node.js** 18+ (Node.js 22 LTS recommended; portable 22 LTS auto-installed on Windows if missing)
- **Git**

## Quick Start (Automated)

The unified launcher handles Python environment creation, dependency installation, portable Node.js setup, preflight cleanup, database migrations, and service supervision automatically:

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

---

## Manual Step-by-Step Setup

If you prefer to start components individually:

### 1. Backend

```bash
python3 -m venv backend/.venv
source backend/.venv/bin/activate
pip install -r backend/requirements.txt
cd backend && alembic upgrade head && cd ..
python -m uvicorn app.main:app --app-dir backend --reload --port 8000
```

The API is available at `http://localhost:8000`. Auto-generated docs at `http://localhost:8000/docs`.

## Start the Frontend

Open a second terminal:

```bash
cd frontend
npm run dev
```

The frontend is available at `http://localhost:5173`. It proxies `/api` and `/ws` requests to the backend at `:8000`.

## Open the Browser

Navigate to `http://localhost:5173`.

**First run:** a fresh instance starts **uninitialized**, so you'll be
redirected to the `/setup` wizard (`SetupPage`). Create the **Owner** account
and choose the access mode before you can log in. See "First Steps" below.

## First Steps

1. **Create the Owner (first run only)** — on `/setup`, enter the Owner
   email/password and choose the access mode:
   - **`LOCAL`** (default) — home-lab/LAN. After bootstrap, open
     self-registration stays available (`Register`), and the Owner can issue
     invitations from **Settings → Invitations** (and flip the mode from
     Settings → Access).
   - **`GLOBAL`** — VPS/remote. Self-registration is disabled; new users must
     register through an invitation link (`/invite/:token`).
2. **Register an account** (LOCAL) or **accept an invitation** (GLOBAL) — the
   Owner can also create additional users directly.
3. **Create a server** — navigate to Servers → Create Server; choose a name, type (e.g. Vanilla), and version
4. **Start the server** — click the play button on the server row; the server status will update in real-time via WebSocket
5. **View the console** — click the server name to open the Blade Hosting-style detail page with live console output and metrics
6. **Manage server files** — click Files in the server sidebar to view, edit, upload, or create server configuration files
7. **Stop the server** — click the stop button; the server will shut down gracefully

## What's Next

| Topic | Document |
|---|---|
| Detailed setup & development loop | [Development Guide](DEVELOPMENT.md) |
| Architecture overview | [Architecture](architecture/ARCHITECTURE.md) |
| REST API reference | [API Documentation](API.md) |
| Frontend architecture | [Frontend](architecture/FRONTEND.md) |
| Running tests | [Testing Guide](testing.md) |
| Project roadmap | [Roadmap](roadmap/ROADMAP_v1.1.md) |

## Troubleshooting

**Port already in use**: Run `scripts/preflight.sh` to kill stale processes.

**Database locked**: Run `scripts/preflight.sh` — it detects and releases SQLite locks from orphaned processes.

**WS connection fails**: Confirm the Vite proxy forwards `/ws` to `ws://localhost:8000`. In development, this is configured by default.

**Token expires**: Access tokens last 15 minutes. The frontend refreshes automatically using the refresh token (7-day TTL).
