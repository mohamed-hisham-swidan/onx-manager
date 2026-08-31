# Contributing

Thanks for your interest in contributing to ONX Manager! This guide covers the development workflow, code conventions, and quality expectations.

---

## Getting Started

1. Fork the repository and clone your fork
2. Run `./scripts/bootstrap` to set up the environment (venv, deps, migrations)
3. Start the dev environment: `python launcher.py`
4. Read [docs/architecture/ARCHITECTURE.md](architecture/ARCHITECTURE.md) before making changes

---

## Code Conventions

### Python

| Requirement | Standard |
|---|---|
| Runtime | Python 3.12+ |
| Linter | `ruff` — no new violations beyond baseline (`./scripts/check-ruff-baseline`) |
| Type checker | `pyright` — strict mode, type hints everywhere (`./scripts/typecheck`) |
| Testing | `pytest` — TDD preferred, coverage ≥ 90% for new code |
| Logging | `structlog` — never use `print()` in production code |
| Error handling | Catch specific exception types — never bare `try/except` |
| Function size | Single responsibility, ≤ 40 lines per function |
| Configuration | Use `ConfigFactory` — never hardcode secrets, URLs, or config values |

### TypeScript

| Requirement | Standard |
|---|---|
| Linter | `eslint` — zero warnings (`npm run lint` in `frontend/`) |
| Formatter | `prettier` |
| TypeScript | strict mode enabled |
| Testing | `vitest` |

### General

- No TODOs in production code — implement or remove
- No dead code, commented-out code, or debug prints
- Follow conventions of the neighboring files
- Use existing shared types and utilities before creating new ones
- Type hints everywhere (Python) / strict types (TypeScript)

---

## Git Commit Conventions

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
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

## Quality Gates

Before submitting a PR, verify all of the following:

| Gate | Command | Requirement |
|---|---|---|
| Version Propagation | `python3 scripts/check-version-propagation` | All versions match `4.0.0` |
| Database Revision | `python3 scripts/check-db-revision` | Database matches head `b1e2100000009` |
| Backend Lint Baseline | `python3 scripts/check-ruff-baseline` | Zero new violations beyond baseline |
| Route/Permission Contract | `python3 scripts/check-route-contract` | 105 / 105 routes match `contracts/permissions.yaml` |
| PowerShell UTF-8 BOM | `python3 scripts/check-ps1-bom` | All `.ps1` scripts have valid UTF-8 BOM |
| Backend Tests | `cd backend && pytest` | All 2,131 tests passing |
| Frontend Quality | `cd frontend && npm run typecheck && npm run lint && npm test` | Typecheck, lint & tests passing |

### PR Checklist

- [ ] All tests pass
- [ ] Backend lint within baseline / frontend lint zero errors
- [ ] No type errors introduced
- [ ] Coverage ≥ 90% for new code
- [ ] No TODOs left in source code
- [ ] No dead code, commented-out code, or debug prints

---

## Architecture Overview

The project follows a **modular monolith with hexagonal architecture**. Before changing any module, read its domain layer (`domain/aggregate.py`, `domain/events.py`) to understand its contracts.

See [Architecture Overview](architecture/ARCHITECTURE.md) for the full picture.

---

## Need Help?

- Check [Getting Started](getting-started.md) for environment setup
- Check [Development Guide](DEVELOPMENT.md) for common workflows
- Open an issue or reach out directly
