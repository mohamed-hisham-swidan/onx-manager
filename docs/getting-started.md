# Getting Started

Get ONX Manager up and running in under 5 minutes.

---

## Choose Your Installation Path

### Option A: Docker Compose (Containerized Panel + DooD)

Because ONX Manager launches Minecraft servers inside Docker containers, use the **Docker-outside-of-Docker (`docker-compose.dood.yml`)** override so a containerized panel can spawn sibling Minecraft containers on the host Docker daemon:

```bash
git clone https://github.com/mohamed-hisham-swidan/onx-manager.git
cd onx-manager
cp .env.example .env
export ONX_HOST_DATA_DIR="$(pwd)/backend/data/servers"
export ONX_HOST_STATE_HOST_DIR="$(pwd)/backend/data/host-state"
docker compose -f docker-compose.yml -f docker-compose.dood.yml up -d
```

Open `http://<your-server-ip>/` (or `http://localhost/`). See the [Deployment Guide](DEPLOYMENT.md) for the DooD security model and bare-metal alternatives.

---

### Option B: Standard Installer (`install.sh` / `install.ps1`)

The standard installers provision an isolated **Python 3.12** runtime via `uv`, build the static frontend bundle (`frontend/dist`) so FastAPI serves both the UI and API from a single process, auto-generate `0600` cryptographic keys, and run Alembic migrations.

**Linux / macOS (interactive VPS vs Local choice):**

```bash
./install.sh
# Or non-interactively:
./install.sh --mode=vps --port=8000 --yes      # Full server panel + systemd service + onx CLI
./install.sh --mode=local --port=8000 --yes    # Personal machine + ~/.local/bin/onx + desktop icon
```

**Windows (PowerShell — Local Mode):**

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```

Once installed, launch or manage ONX Manager using:

```bash
onx open      # Start (if stopped) and open the browser UI
onx status    # View status
onx logs      # Tail service logs
onx stop      # Stop cleanly
```

---

### Option C: Desktop App (`desktop/`)

Run ONX Manager as a native desktop window on **Windows** or **Linux** with a system tray icon and built-in switcher (`Ctrl+Shift+K`) between your **Local backend** and any **Remote VPS / friend's panel URL**:

```bash
cd desktop
npm install
npm start
```

See [`desktop/README.md`](../desktop/README.md) for packaging instructions (`AppImage` / Windows `.exe`).

---

## Manual Developer Setup

If you want hot-reloading backend + Vite dev servers:

- **Python** 3.12 (exact)
- **Node.js** 18+ (Node.js 22 LTS recommended)
- **Git**

```bash
./scripts/bootstrap
python3 launcher.py --dev
```

Or manually in two terminals:

```bash
# Terminal 1 — Backend
cd backend
source .venv/bin/activate
alembic upgrade head
python -m uvicorn app.main:app --reload --port 8000

# Terminal 2 — Frontend
cd frontend
npm run dev
```

Dev UI runs at `http://localhost:5173` (proxying `/api` and `/ws` to `:8000`).

---

## First-Run GUI Onboarding (`/setup`)

A fresh instance starts **uninitialized** — no terminal registration step is needed:

1. Open the panel URL in your browser (or launch the Desktop App):
   - In **`local`** profile on loopback (`127.0.0.1` / `::1`), the dashboard opens directly without a login screen; you will be prompted to set a **Username** and **Password** before enabling any external tunnel or binding to `0.0.0.0`.
   - In **`vps`** profile (or once credentials are configured), you are redirected to **`/setup`** to create the **Owner** account (**Username** and **Password**; email is optional).
2. Choose the **Access Mode** (or keep the default **`LOCAL`** in Local Desktop profile):
   - **`LOCAL`**: Home-lab / LAN.
   - **`GLOBAL`**: Public VPS. Registration is invite-only via `/invite/:token` links created by the Owner under **Settings → Invitations**.
3. **Create a server** — go to **Servers → Create Server**, pick software (Vanilla, Paper, Purpur, Fabric, Forge, NeoForge, Quilt, or Modpack), and click **Create**.
4. **Start & share** — start the server from the dashboard, open the live console, or configure **Playit.gg** / **Cloudflare Tunnel** under **Network & Exposure**.

---

## What's Next

| Topic | Document |
|---|---|
| Production deployment, DooD & `systemd` | [Deployment Guide](DEPLOYMENT.md) |
| Local dev loop, preflight & debugging | [Development Guide](DEVELOPMENT.md) |
| Architecture overview | [Architecture](architecture/ARCHITECTURE.md) |
| REST API reference | [API Documentation](API.md) |
| Running tests & CI gates | [Testing Guide](testing.md) |
