# Development & Verification Scripts

Authoritative developer utilities and CI quality gates for ONX Manager.

> **End-User Installation vs. Developer Scripts:**
> - **End Users:** Use `install.sh` (Linux/macOS), `install.ps1` (Windows), `docker compose up -d`, or the `desktop/` app.
> - **Developers & CI:** Use the tools below under `scripts/`.

## CI & Verification Gates

| Script | Purpose |
|---|---|
| `scripts/check-version-propagation` | Verifies `backend/pyproject.toml`, `frontend/package.json`, and runtime version match (`0.1.0`) |
| `scripts/check-db-revision` | Verifies Alembic migration head matches release compatibility floor (`b1e2100000034`) |
| `scripts/check-ruff-baseline` | Enforces zero-regression Ruff lint gate against `backend/ruff-baseline.json` |
| `scripts/check-route-contract` | Validates all 217 live FastAPI routes against `contracts/permissions.yaml` |
| `scripts/check-ps1-bom` | Verifies all tracked `.ps1` files contain a UTF-8 BOM (`EF BB BF`) |
| `scripts/check-stray-db` | Verifies no stray SQLite files (`*.db`, `*.db-wal`, `*.db-shm`) exist at repo or backend root |
| `scripts/reverify` / `reverify.ps1` | Runs the full local CI verification cadence (Linux / Windows) |
| `scripts/pre-push-check.sh` | Pre-push hygiene and CI gate sanity check |

## Developer & Preflight Utilities

| Script | Platform | Purpose |
|---|---|---|
| `scripts/preflight.sh` | Linux / macOS | Smart preflight process reconciliation, zombie cleanup, and lock validation |
| `scripts/preflight.py` | Windows | Windows Python preflight runner with protected PID scanning and ASCII fallback |
| `scripts/bootstrap` | Linux / macOS | Developer virtualenv creation (`.venv`, Python 3.12), dependency install, and migration runner |
| `scripts/start.ps1` | Windows | Developer PowerShell bootstrap helper (`powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start.ps1`) |
| `scripts/check` / `check.ps1` | Linux / Windows | Runs lint → typecheck → test |
| `scripts/lint` | Cross-Platform | Runs `ruff check` |
| `scripts/format` | Cross-Platform | Runs `ruff format` |
| `scripts/typecheck` | Cross-Platform | Runs `pyright` |
| `scripts/test` / `test.ps1` | Linux / Windows | Runs `pytest` |
| `scripts/build` | Cross-Platform | Builds production Docker image |
| `scripts/release` | Linux / macOS | Tags and builds release Docker image |

## Running Quality Gates

```bash
python3 scripts/check-version-propagation
python3 scripts/check-db-revision
python3 scripts/check-ruff-baseline
python3 scripts/check-route-contract
python3 scripts/check-ps1-bom
python3 scripts/check-stray-db
```
