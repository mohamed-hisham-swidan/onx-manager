# Development & Verification Scripts

Authoritative scripts for quality gates, preflight cleanup, and development tasks.

## CI & Verification Gates

| Script | Purpose |
|---|---|
| `scripts/check-version-propagation` | Verifies `pyproject.toml`, `package.json`, and runtime version match (`4.0.0`) |
| `scripts/check-db-revision` | Verifies current database schema matches minimum compatibility revision |
| `scripts/check-ruff-baseline` | Enforces zero-regression lint gate against `scripts/ruff-baseline.json` baseline |
| `scripts/check-route-contract` | Validates all 105 live FastAPI routes against `contracts/permissions.yaml` contract |
| `scripts/check-ps1-bom` | Verifies all `.ps1` files contain valid UTF-8 BOM encoding |
| `scripts/reverify` | Runs the full local CI verification cadence |

## Runtime & Preflight Utilities

| Script | Platform | Purpose |
|---|---|---|
| `scripts/preflight.sh` | Linux / macOS | Smart preflight process reconciliation, zombie cleanup, and lock validation |
| `scripts/preflight.py` | Cross-Platform / Windows | Python preflight runner with protected PID scanning and ASCII fallback |
| `scripts/bootstrap` | Linux / macOS | One-step virtualenv creation, dependency installation, and migration runner |
| `scripts/lint` | Cross-Platform | Runs `ruff check` |
| `scripts/format` | Cross-Platform | Runs `ruff format` |
| `scripts/typecheck` | Cross-Platform | Runs `pyright` |
| `scripts/test` | Cross-Platform | Runs `pytest` |
| `scripts/build` | Cross-Platform | Builds production Docker image |

## Running Quality Gates

```bash
python3 scripts/check-version-propagation
python3 scripts/check-db-revision
python3 scripts/check-ruff-baseline
python3 scripts/check-route-contract
python3 scripts/check-ps1-bom
```
