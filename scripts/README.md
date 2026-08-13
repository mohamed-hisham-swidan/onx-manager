# Scripts

Standardized scripts for all development tasks.
Every AI session uses these scripts — never invent ad-hoc commands.

## Available Scripts

| Script | Command | Purpose |
|---|---|---|
| `scripts/bootstrap` | Set up development environment | Install deps, create venv, run migrations |
| `scripts/lint` | `ruff check .` | Python linting |
| `scripts/format` | `ruff format .` | Python code formatting |
| `scripts/typecheck` | `pyright` | Python type checking |
| `scripts/test` | `pytest` | Run test suite |
| `scripts/build` | `docker build` | Build production image |
| `scripts/release` | Tag version, build, push | Create a release |
| `scripts/check-version-propagation` | `python scripts/check-version-propagation` | Verify pyproject.toml, package.json, and runtime versions agree |
| `scripts/check-route-contract` | `python scripts/check-route-contract` | Verify `contracts/permissions.yaml` route→permission matrix matches the live FastAPI route table (CI: route-permission-ci.yml) |
| `scripts/reverify` | `./scripts/reverify` | Re-verification cadence — run the exact authoritative check set (version, DB head, ruff baseline, route contract, backend pytest, frontend typecheck/lint/test/build). Local twin of `.github/workflows/verification-cadence.yml` (weekly, see `docs/current-state.md` §7) |

## Usage

```bash
./scripts/lint
./scripts/test --cov
./scripts/build
```

## Adding a Script

1. Create the script in this directory
2. Make it executable: `chmod +x scripts/<name>`
3. Update this README
