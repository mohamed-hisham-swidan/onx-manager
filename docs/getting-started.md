# Getting Started

A 5-minute quickstart for running the Minecraft Server Manager on your local machine.

## Prerequisites

- **Python** 3.12+ (3.14+ recommended)
- **Node.js** 20+
- **Docker** (optional — the app runs standalone on SQLite with an in-process task queue; Docker/PostgreSQL is an alternative production deployment)
- **Git**

## Quick Start

```bash
# 1. Clone the repository
git clone <repo-url> mcs-manager
cd mcs-manager

# 2. Bootstrap everything (venv, deps, migrations)
./scripts/bootstrap
```

The bootstrap script runs:
1. Creates a Python virtual environment in `backend/.venv`
2. Installs backend dependencies (including `python-multipart` for form/file endpoints)
3. Installs frontend dependencies
4. Runs database migrations

## Start the Backend

```bash
source backend/.venv/bin/activate
pip install python-multipart # Note: required for FastAPI file upload & form endpoints
uvicorn app.main:app --reload --port 8000
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

Navigate to `http://localhost:5173`. You will see the login page. Register an account from the login page to get started.

## First Steps

1. **Register an account** — click "Register" and create your first user
2. **Create a server** — navigate to Servers → Create Server; choose a name, type (e.g. Vanilla), and version
3. **Start the server** — click the play button on the server row; the server status will update in real-time via WebSocket
4. **View the console** — click the server name to open the Blade Hosting-style detail page with live console output and metrics
5. **Manage server files** — click Files in the server sidebar to view, edit, upload, or create server configuration files
6. **Stop the server** — click the stop button; the server will shut down gracefully

## What's Next

| Topic | Document |
|---|---|
| Detailed setup & development loop | [Development Guide](DEVELOPMENT.md) |
| Architecture overview | [Architecture](architecture/ARCHITECTURE.md) |
| REST API reference | [API Documentation](API.md) |
| Frontend architecture | [Frontend](architecture/FRONTEND.md) |
| Running tests | [Testing Guide](testing.md) |
| Project roadmap | [Roadmap](roadmap/MCS-Manager-Engineering-Blueprint-V5.md) |

## Troubleshooting

**Port already in use**: Run `scripts/preflight.sh` to kill stale processes.

**Database locked**: Run `scripts/preflight.sh` — it detects and releases SQLite locks from orphaned processes.

**WS connection fails**: Confirm the Vite proxy forwards `/ws` to `ws://localhost:8000`. In development, this is configured by default.

**Token expires**: Access tokens last 15 minutes. The frontend refreshes automatically using the refresh token (7-day TTL).
