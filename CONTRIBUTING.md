# Contributing

Thanks for your interest in contributing to ONX Manager! This guide covers the development workflow, code conventions, governance basics, and quality gates.

---

## Getting Started

1. Fork the repository and clone your fork.
2. Run `./scripts/bootstrap` to set up the environment (venv, dependencies, migrations), or follow [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).
3. Start the dev environment via `python3 launcher.py --dev` (or run backend `uvicorn` + frontend `npm run dev` directly).
4. Read [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md) and [docs/reference/dependency-graph.md](docs/reference/dependency-graph.md) before making cross-module changes.

---

## Code Conventions

### Python

| Requirement | Standard |
|---|---|
| Runtime | Python 3.12 (`requires-python = ">=3.12"`, launcher pins 3.12) |
| Linter | `ruff` (`0.16.0`) — zero new violations beyond baseline (`./scripts/check-ruff-baseline`) |
| Type checker | `pyright` — advisory locally (`./scripts/typecheck`) |
| Testing | `pytest` (`pytest-asyncio`) — write regression tests for fixes and new behavior |
| Logging | `structlog` / `logging` — never use `print()` in production code |
| Error handling | Catch specific exception types — never bare `try/except` |
| Configuration | Use `ConfigFactory` / `AppSettings` (`ONX_*`) — never hardcode secrets or URLs |

### TypeScript

| Requirement | Standard |
|---|---|
| Linter | `eslint` — zero errors or warnings (`npm run lint` in `frontend/`) |
| TypeScript | strict mode (`npm run typecheck`) |
| Design Tokens | Use semantic CSS tokens and `components/ui/` primitives (see [docs/design/frontend-overhaul/README.md](docs/design/frontend-overhaul/README.md)) |
| Testing | `vitest` + Testing Library |

### General

- No dead code, commented-out code, or debug prints
- Respect hexagonal module boundaries (domain must never import infrastructure or API)
- Follow conventions of neighboring files and reuse existing shared utilities

---

## Git Commit Conventions

Use [Conventional Commits](https://www.conventionalcommits.org/):

```text
feat: add server backup scheduling
fix: correct token expiration check
docs: update API reference for rate limiting
refactor: extract permission evaluator
test: add audit chain verification tests
chore: update ruff configuration
```

Format: `<type>: <short description in imperative mood>`

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `style`, `ci`

---

## Governance & Decision Process

- **Routine fixes & small features**: Open a pull request against `master` with tests and passing quality gates.
- **Significant architectural or contract changes**: Open an issue first to discuss design trade-offs. Accepted architectural decisions are documented as ADRs under [`docs/decisions/`](docs/decisions/README.md).
- **Versioning**: Public releases follow SemVer 2.0.0 ([`docs/VERSIONING.md`](docs/VERSIONING.md)).


---

## Quality Gates

Before submitting a PR, verify all of the following:

| Gate | Command | Requirement |
|---|---|---|
| Version Propagation | `python3 scripts/check-version-propagation` | All versions match `0.1.0` |
| Database Revision | `python3 scripts/check-db-revision` | Database matches compatible head `b1e2100000034` |
| Backend Lint Baseline | `python3 scripts/check-ruff-baseline` | Zero new violations beyond baseline |
| Route/Permission Contract | `python3 scripts/check-route-contract` | 217 / 217 routes match `contracts/permissions.yaml` |
| PowerShell UTF-8 BOM | `python3 scripts/check-ps1-bom` | All `.ps1` scripts have valid UTF-8 BOM |
| Stray DB Check | `python3 scripts/check-stray-db` | No stray SQLite `.db` files at repo root or backend root |
| Backend Tests | `cd backend && pytest` | All tests passing (`cd backend && .venv/bin/pytest tests/ -q`) |
| Frontend Quality | `cd frontend && npm run typecheck && npm run lint && npm test && npm run build` | Typecheck, lint (0 warnings), tests, and production build passing |

### PR Checklist

- [ ] Relevant backend/frontend tests added and passing
- [ ] All 6 repo CI quality gates pass
- [ ] Frontend `typecheck`, `lint`, `test`, and `build` pass cleanly
- [ ] Documentation updated if API routes, env vars, or architecture changed

---

## Need Help?

- Check [Getting Started](docs/getting-started.md) for environment setup
- Check [Development Guide](docs/DEVELOPMENT.md) for common workflows
- Review our [Code of Conduct](CODE_OF_CONDUCT.md) and [Security Policy](SECURITY.md)
