# Contributing

This guide covers the contribution workflow for both human developers and AI agent sessions. Every contribution must follow the architecture-first principle: understand the system before modifying it.

---

## Architecture-First Workflow

Before writing any code, read the following in order:

1. **`AI_RULES.md`** — mandatory session rules for all contributors
2. **`TOKEN_POLICY.md`** — context optimization constraints
3. **`PROJECT_STATE.json`** — current state of every batch
4. Your batch's **`STATE.md`** — what was done and what is next
5. Your batch's **`PROMPT.md`** — complete context for the work unit
6. **`docs/reference/file-ownership.md`** — confirm which files you own
7. **`docs/reference/dependency-graph.md`** — understand inter-batch dependencies
8. **`docs/architecture/ARCHITECTURE.md`** — system architecture reference

Every file has exactly one owner (see [reference/file-ownership.md](reference/file-ownership.md)). A batch may only modify files it owns. Read access is unrestricted.

---

## Starting a Session

### For AI Agents

Read the following documents **in this exact order** at session start:

1. `AI_RULES.md`
2. `TOKEN_POLICY.md`
3. `PROJECT_STATE.json`
4. Your batch's `STATE.md`
5. Your batch's `PROMPT.md`
6. `docs/reference/file-ownership.md`

Then begin implementation. Do not skip any step.

### For Human Developers

1. Read `PROJECT_STATE.json` to understand the current overall progress
2. Read your batch's `STATE.md` for the latest completion state
3. Read your batch's `TASKS.md` for remaining work
4. Check `Requests/` for any open cross-batch dependencies
5. Verify no stale locks exist in `LOCKS/` before starting work

---

## Code Conventions

### Python

| Requirement | Standard |
|---|---|
| Runtime | Python 3.12+ |
| Linter | `ruff` — zero warnings |
| Type checker | `pyright` — strict mode, type hints everywhere |
| Testing | `pytest` — TDD workflow, coverage ≥ 90% for new code |
| Logging | `structlog` — never use `print()` |
| Error handling | Catch specific exception types — never bare `try/except` |
| Function size | Single responsibility, ≤ 40 lines |
| Configuration | `ConfigFactory` — never hardcode secrets, URLs, or config |

### TypeScript

| Requirement | Standard |
|---|---|
| Linter | `eslint` — zero warnings |
| Formatter | `prettier` |
| TypeScript | strict mode enabled |
| Testing | `vitest` |

### General

- No TODOs in production code — either implement or remove
- No dead code, commented-out code, or debug prints
- Follow conventions of neighboring files
- Use existing shared contracts instead of inventing new ones
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

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `style`, `ci`.

---

## Cross-Batch Request Protocol

When one batch needs an interface, change, or addition from another batch, file a numbered request in `Implementation/Requests/`.

### Workflow

```
1. Need from Batch-YY
2. Copy Requests/TEMPLATE.md → Requests/REQ-NNNN.md
3. Fill in details, set status to OPEN
4. Update PROJECT_STATE.json with new request count
5. When Batch-YY implements → set status to COMPLETED
6. If rejected → set status to REJECTED
7. Update PROJECT_STATE.json on status change
```

### Rules

- Never modify a file you do not own — file a Request instead
- Never assume what another batch provides — check `Requests/` or `Shared/Contracts/`
- Breaking interface changes require an ADR in `Shared/ADR/`
- New shared interfaces go in `Shared/Contracts/` before any batch implements them
- New domain events go in `Shared/Events/`
- Dependency additions require a Request to Batch 01
- Database schema changes require a Request to Batch 01 (owns Alembic migrations)

---

## Lock Protocol

Concurrent modification locks prevent two batches from editing the same file simultaneously. Locks live in `Implementation/LOCKS/`.

### Before Editing a File

1. **Check** if a lock exists:
   ```
   ls LOCKS/<escaped-path>.lock 2>/dev/null
   ```
   The path separator (`.`) replaces `/` — e.g., `backend/app/core/command_bus.py` → `LOCKS/backend.app.core.command_bus.lock`.

2. **If locked**: Do not touch the file. File a Request if you need the change.
3. **If unlocked**: Create the lock:
   ```
   echo "Batch-XX $(date -u)" > LOCKS/<escaped-path>.lock
   ```

### After Editing

Remove the lock:
```
rm LOCKS/<escaped-path>.lock
```

### Lock File Format

```
Batch-XX
YYYY-MM-DD HH:MM:SS UTC
<optional notes about what change is being made>
```

### Stale Locks

If a batch crashes with locks held:
1. Note the stale lock in the batch's `STATE.md`
2. Verify no changes are in progress
3. Remove the lock

---

## Quality Gates

Before marking any task complete, verify **all** of the following:

| Gate | Command | Requirement |
|---|---|---|
| Lint | `./scripts/lint` | Zero errors |
| Type check | `./scripts/typecheck` | Zero errors |
| Test | `./scripts/test` | All tests passing |
| Coverage | `./scripts/test --coverage` | ≥ 90% for new code |

### Checklist

- [ ] All tests pass
- [ ] No lint errors
- [ ] No type errors
- [ ] Coverage ≥ 90% for new code
- [ ] `STATE.md` updated
- [ ] No TODOs left in source code
- [ ] No dead code, commented-out code, or debug prints
- [ ] `DONE_CHECKLIST.md` filled for completed tasks

---

## Error Recovery

### Command Failures

1. Read the error message carefully
2. Fix the specific issue — do not change unrelated code
3. Re-run the exact same command
4. If it fails again after **3 attempts**, stop and file a Request describing the issue

### Architectural Inconsistencies

1. Verify the inconsistency is real — re-read the relevant docs
2. If confirmed, file a Request describing the inconsistency
3. Do not fix it yourself unless your batch's `PROMPT.md` explicitly authorizes it

---

## Session End Procedures

Every session ends with the following completed:

1. **All changes committed** to the batch file tree
2. **`STATE.md` updated** to reflect the latest completion state
3. **`DONE_CHECKLIST.md` filled** for any completed tasks
4. **`PROJECT_STATE.json` updated** — progress percentage, batch status, timestamp
5. **`CHANGELOG.md` updated** with a summary of changes
6. **Any Requests filed** that the next session or batch needs
7. **All locks released** — verify no stale locks remain
8. **`OUTPUT.md` written** — brief summary covering:
   - What was done
   - What was NOT done
   - What the next session needs
9. **QA reports filed** — `QA/REVIEW.md`, `QA/ARCHITECTURE_COMPLIANCE.md`, `QA/TESTING_REPORT.md`

### Completion Verification

- [ ] All changes committed
- [ ] `STATE.md` reflects current state
- [ ] `DONE_CHECKLIST.md` complete
- [ ] `PROJECT_STATE.json` updated (batch status, progress, timestamps)
- [ ] `CHANGELOG.md` updated
- [ ] Open Requests filed and closed where applicable
- [ ] All locks released
- [ ] `OUTPUT.md` written
- [ ] QA reports filed

---

See [DEVELOPMENT.md](DEVELOPMENT.md) for environment setup and [ARCHITECTURE.md](architecture/ARCHITECTURE.md) for system architecture.
