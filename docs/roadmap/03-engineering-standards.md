# MCS Manager — Engineering Standards

**Part III** of the Engineering Blueprint V4. Defines the *how* of writing code in this repository:
coding standards, the architecture-decision-record (ADR) process, the testing philosophy and quality
gate, and the non-functional requirements (NFRs) and performance targets the product must hold to.

These standards are not suggestions. They are enforced by tooling where possible (ruff, pyright,
ESLint, `tsc`, CI) and by review and the ADR process where enforcement must be a judgment call.

**Last updated:** 2026-08-06
**Supersedes:** the scattered code-conventions sections in `docs/DEVELOPMENT.md` (§Code Conventions,
§Script Conventions, §Testing Strategy) and `docs/testing.md` (§Quality Gates); it also formalizes the
ADR process that `docs/decisions/README.md` introduced informally and pulls the quality gate into one
place. Where this file and a source document disagree, this file is the definitive engineering
standard and the source document should be updated to match.

---

## 1. Scope and how this file is used

This is the reference for *how we write code*, not *what we build* (that is Parts II, IV, V) and not
*why we build it in this order* (Part I). A contributor should read this file before writing their
first line, and a reviewer should hold submissions against it.

The file is organized so that concrete, checkable rules come first (§2–§5), process and philosophy
come in the middle (§6–§8), and non-functional requirements are collected at the end (§9). Part IX
(`12-working-agreements.md`) covers the collaborative workflow *around* the code — how commits are
made, how AI is used — and is the companion to this file.

---

## 2. Backend coding standards

### 2.1 Language baseline

- **Python 3.12+.** This is declared in `backend/pyproject.toml` and assumed everywhere.
- **Type hints everywhere.** No untyped public functions, handlers, or domain contracts. The project
  runs `pyright` in the quality gate (§8), so new code must type-clean out of the gate.

### 2.2 Style and formatting (enforced by tooling)

- **Formatting:** `ruff format .` (see `scripts/format`). All code must be `ruff format`-clean.
- **Lint:** `ruff check .` (see `scripts/lint`). Zero lint errors allowed.
- **Function length:** a function should stay under ~40 lines. When it exceeds that, it is a signal
  the logic is doing more than one thing and should be split. (Not a hard rule — a long, linear,
  well-named computation may stay — but reviewers should ask why.)
- **Docstrings:** only where the "why" is not obvious from the code or name. Do not write docstrings
  that restate the code. This keeps noise low on a file-by-file basis.

### 2.3 Package/import hygiene

- **Module boundaries are enforced, not conventional.** A module must not import another module's
  internals; communication happens across the CQRS buses or shared value objects (§Part II). This is
  the DDD boundary rule and a review blocker.
- **Domain never imports infrastructure or the API layer.** `application` may import from `domain`
  (as interfaces) and `infrastructure` (as adapters the app wires); `api` wires everything. The
  dependency direction is one-way: `api → application → domain ← infrastructure`.
- **Exception hierarchy:** domain-specific exceptions live in the owning module and extend a shared
  base from `core`; the API layer maps them to HTTP status codes, never to raw 500s unless truly
  unexpected.

### 2.4 Async discipline

- The backend is **asyncio-native**. Blocking calls must not run on the event loop; filesystem,
  network, and subprocess work go through infrastructure adapters that are async or offloaded.
- **Shared async state is protected with an `asyncio.Lock`** (ADR-0004), never a bespoke
  synchronization primitive.
- A coroutine that awaits must be awaited; no dangling tasks without ownership and cancellation
  handling. Long-lived background loops are cancelled in the owning lifecycle's shutdown path.

### 2.5 Config and environment

- All runtime configuration flows through `AppSettings` (`backend/app/core/config.py`), sourced from
  environment variables with the `MCS_` prefix and `.env` support. Never read `os.environ` ad hoc in
  module code.
- **Sandbox-isolation variables are load-bearing** (`MCS_DATABASE_URL`, `MCS_SERVERS_DATA_DIR`),
  ADR-0008. Test and development processes that touch the database or server files MUST set both, in
  the same command as the process, so they never reach production state.

---

## 3. Frontend coding standards

### 3.1 Language baseline

- **TypeScript, strict mode**, with `tsc --noEmit` as the typecheck gate. No unchecked `any` in new
  code. (See `frontend/tsconfig.json` and `npm run typecheck`.)

### 3.2 Style and lint

- **ESLint** over `src/` (`npm run lint`) with the `react-hooks` and `react-refresh` plugins (§`rules-of-hooks`, `react-refresh/only-export-components`).
- Formatting follows the project's prettier/eslint configuration; generated code must be lint-clean.

### 3.3 State and data-fetch conventions

- **Remote state goes through TanStack Query** (React Query): queries are cached and keyed by
  endpoint; mutations invalidate the relevant queries. There is no hand-rolled HTTP state store.
- **Local/UI state uses Zustand stores** where the state is shared across the tree (auth, UI, WS);
  component-local state stays in `useState`/`useReducer`.
- **The WebSocket layer is the live-update bridge.** Incoming messages route to the cache-callback
  mechanism (ADR-0004) so TanStack Query caches stay fresh without polling. A page that can render
  live data must subscribe through the WS client, not poll.

### 3.4 Test conventions

- Tests use Vitest + jsdom + `@testing-library/react` + `userEvent` (prefer `userEvent` over
  `fireEvent`). Mocks are `vi.fn()`. Stores are reset between tests.

---

## 4. The quality gate (must pass before merge)

Every change must pass the full gate locally **and** in CI before it is merged or marked done. The
gate is linear and additive; a failure at any step halts the merge.

### 4.1 Backend gate

```
ruff check .          # lint
pyright               # type check
pytest                # full suite
```

Runnable in one step as `./scripts/check`, which runs lint + typecheck + test in order.

### 4.2 Frontend gate

```
npm run lint          # ESLint
npm run typecheck     # tsc --noEmit
npm test              # Vitest
```

### 4.3 Coverage rule

New code must maintain ≥ 90% coverage on the exercised paths. This applies to both the backend
(`pytest --cov=app`) and the frontend (`vitest run --coverage`). The project currently runs
**1070 backend tests / 236 frontend** (verified 2026-08-04); the two backend env failures are
tracked in `docs/current-state.md` §4, not silently waived (Part I "fail loud").

### 4.4 Verification, not declaration

A change is done only when its gate passes against **live** code. It is not acceptable to mark a
unit done because the previous batch's log said tests passed. This mirrors Part I's *evidence before
assertion* rule and is restated here because it is the single most common way "done" gets falsified
in this project's history.

---

## 5. Tests and the testing philosophy

### 5.1 The test pyramid

Backend tests are organized to mirror the module/DDD layer (from `docs/testing.md`):

- **Domain tests** — aggregates and value objects in pure isolation (`backend/tests/domain/`).
- **Application tests** — command/query handler behavior, sagas, idempotency
  (`backend/tests/application/`, `test_command_bus.py`, `test_saga.py`, `test_idempotency.py`).
- **Infrastructure tests** — providers and repositories mocked at interface boundaries; unit tests
  never call real Docker or filesystem APIs (`backend/tests/infrastructure/`).
- **API tests** — endpoint behavior via `httpx.AsyncClient` on FastAPI's `TestClient`
  (`backend/tests/api/`, `tests/test_integration.py`).
- **Cross-cutting** — buses, config, exceptions, logging, security, database, websocket, feature
  flags, circuit breaker.

Frontend tests mirror component structure (`frontend/src/**/*.test.*`): stores, services, websocket,
components, pages.

### 5.2 Fixtures and isolation

- Shared fixtures (event loop, buses, mock handler) live in `backend/tests/conftest.py`.
- Infrastructure providers are mocked at their interfaces; integration tests use SQLite in memory.
- **Tests MUST never touch production state** (ADR-0008): sandbox database and directory.
- A handler that can raise is tested for both success and failure; a stub that returns conditional
  behavior is tested for every branch, not just the happy path.

### 5.3 Where tests are written

A test accompanies a feature unless a test is genuinely impossible (a pure-presentation toggle with
no observable behavior, in which case the omission is called out in review, not assumed).

### 5.4 Integration / E2E (planned, not yet committed)

`backend/tests/e2e/` is planned to exercise the full stack (backend + PostgreSQL + Redis via Docker
Compose, headless frontend via Playwright, WebSocket reconnect, auth refresh, real plugin
subprocess). This is **future scope**, not a current requirement — it is tracked in Part V Phase 6.

---

## 6. The architecture-decision-record (ADR) process

### 6.1 What deserves an ADR

A decision deserves an ADR when it is **significant and hard to reverse** — it changes a public
contract, a security property, a data-integrity property, an isolation boundary, or a cross-cutting
behavior. Routine implementation choices (naming, internal helper factoring) do **not**.

Examples that *did* deserve ADRs (see `docs/decisions/`): modular monolith (0001), CQRS buses
(0002), all-plugins-as-subprocesses (0003), WS concurrency/permissions (0004), JWT RS256 (0005), task
queue dual impl (0006), persistence rename (0007), sandbox isolation (0008), pydantic field
validators (0009), commit-per-step (0010), orphan ownership verification (0011), same-filesystem
staging (0012).

### 6.2 The process

1. **Propose.** Document the ADR using the established template: `Context`, `Decision` (with date,
   author), `Consequences`. It must capture the options considered and the trade-offs, not just the
   conclusion.
2. **Number sequentially and append to the table in `docs/decisions/README.md`.**
3. **Never delete or rewrite history.** An ADR once accepted is never removed; it is superseded by a
   newer ADR that explicitly marks the prior one as superseded (Part I §9).
4. **Statuses:** `Accepted` (the norm), `Superseded` (a later ADR replaced it), `Rejected` (considered
   and deliberately not taken — worth recording). Finished/abandoned proposals are recorded with the
   reason.

### 6.3 When an ADR is out of date

When code drifts from an ADR, the ADR is authoritative unless and until a new ADR supersedes it. A
silent drift without an ADR is a defect to fix or document, not a de-facto decision to accept.

---

## 7. Releasablility and the versioning contract

Versioning strategy is described in `docs/VERSIONING.md` and scheduled as **Phase 5** within Part V.
The standards it imposes once landed, which the phase must satisfy:

1. **One source of truth:** `backend/pyproject.toml` is canonical; runtime (`AppSettings.version`),
   OpenAPI, and the frontend-displayed version derive from it rather than duplicating it.
2. **SemVer 2.0.0 semantics** with explicit meaning per segment (see `VERSIONING.md` §4.2); `v1.0`
   public-release naming is decoupled from internal app version.
3. **Migration/version compatibility rule:** every release pins the minimum Alembic revision; startup
   enforces or loudly reports the DB revision state vs. the app version.
4. **State-file discipline:** `.ai/CURRENT_STATE.json` and `.ai/PROJECT_STATE.json` align their
   `version` fields to the resolved value and note a verification date; docs never assert a version
   they can't justify from the code.

These become **requirements** for any code that touches versioning, release, or state files — the
standard to which Phase 5 closes out.

---

## 8. Repository & script discipline

### 8.1 Dev-loop scripts

All developer-facing commands are **canonical, named scripts in `scripts/`** (symlinked at project
root) `bootstrap`, `lint`, `format`, `typecheck`, `test`, `check`, `build`, `release`, plus
`scripts/preflight.sh`. Ad-hoc commands must not replace them.

### 8.2 Script conventions

Every script:
- Runs from the project root (`cd "$(dirname "$0")/.."`).
- Is executable (`chmod +x`).
- Follows `set -euo pipefail`.

### 8.3 CI

- **GitHub Actions** at `.github/workflows/frontend-ci.yml`. Today **only the frontend has a CI
  workflow** — the backend has none. That asymmetry is **a known gap (K6)** and closing it is part of
  Part V Phase 6. Until it is closed, the backend gate is enforced locally (`./scripts/check`) and by
  review.

---

## 9. Non-functional requirements (NFRs)

This section records the cross-cutting non-functional requirements and the performance targets the
product is expected to meet. Where a target is not yet measured, it is labeled. These apply to any
commit during execution (Part V), not only at specific phases.

### 9.1 Performance targets

| Target | Value | Status |
|---|---|---|
| API cold-start latency (interactive route) | p95 < 300 ms | Target (not yet baselined) |
| Backend boot time (modular monolith, warm) | < 5 s | Target |
| Concurrent live WS subscribers | 500 without connection-dropping | Target (currently singleton HPA) |
| Monitored-server metrics collection | On cadence without blocking server I/O | Target (λ poller design) |
| Acknowledge-then-process health/lifecycle events | No event lost on bounded-crash | Definition (event-store + DLQ) |

> These are *targets*, not commitments — a public baseline has not yet been published or measured. They
> exist so a performance regression in a later batch is detected against a *number*, not vibes.

### 9.2 Reliability and recoverability

- **Backups and restores are the lineage** (Part II, storage). The cost of any design change that
  makes backup/restore riskier is a review-blocking concern.
- **Automatic crashes escalate to a configurable stop** (default 3 crashes / 300 s) rather than a
  loop (Part I §8).
- **Reconciliation is idempotent, one-directional** (disk → DB cache), and its direction never
  reverses (Part I §2.3).
- **A operation that can't be rolled back atomically must fail before it mutates anything** (ADR
  0012 same-filesystem staging).

### 9.3 Observability

- Serve **Prometheus** metrics; the current `/metrics` endpoint is **public** — that is a known
  deferred risk (K10) to be closed in Phase 7, not a permanent design.
- Event-store and audit rows are append-only with a cryptographic chain (Part II, event_store).

### 9.4 Testability

- Every path a developer can permanently break is covered by the gate (§4). A feature must be
  testable to be shipped; untested surfaces are bugs waiting to be named.

### 9.5 Performance of the product over time

The metrics/retention pipeline and alerting are designed with **bounded retention and aggregation**
(four-tier rollup, ADR-0006) so the database does not grow without bound from monitoring.

---

## 10. Summary: the standard as a checklist

A change is "done" to this standard when all of the following hold:

1. Backend: `ruff check`, `pyright`, `pytest` green and coverage ≥ 90% on new code.
2. Frontend: `npm run lint`, `npm run typecheck`, `npm test` green.
3. Tests accompany non-trivial behavior, including the failure path.
4. Type-safe, no `any`, formatted per ruff/prettier.
5. No new rule or guideline was invented ad hoc — if a new convention emerged, it's recorded (ADR and
   update to this file), not just followed once.
6. No cross-module import violation; dependencies flow one direction.
7. Nothing blocks the event loop; shared async state uses `asyncio.Lock`.
8. Config is via `AppSettings`/`MCS_*`; test/dev processes sandbox their state.
9. The change is documented per the ADR/commit discipline, and history is never rewritten.

---

*Continue to [`04-phase0-1-2-current-reality-and-foundation.md`](./04-phase0-1-2-current-reality-and-foundation.md)
for the execution plan — Phase 0 (current-reality baseline, role of this document) and Phases 1–2
(structure & product foundation).*