# ONX Manager — Project Specs

A single authoritative overview of the project's **tech stack, libraries,
repository shape, code statistics, structure, specs, and features.**

> Companion docs: `docs/current-state.md` (verified state + test counts),
> `docs/architecture/ARCHITECTURE.md` (design deep-dive), `docs/API.md`
> (endpoint reference), `docs/architecture/DATABASE.md` (schema).

---

## 1. Project identity

| Attribute | Value |
|---|---|
| Name | ONX Manager (Development & Self-Hosted Environment) |
| Version | `0.1.0` (single source: `backend/pyproject.toml:3` via `app/core/version.py`) |
| Status | Phase 0–5 CLOSED — Phase 4 CLOSED — Enterprise Branch Runtime (Stages A–G & Frontend UI Batch) CLOSED — Phase 6 (Final Installs & Wrap-up) UP NEXT — Canonical Roadmap: `docs/roadmap/ROADMAP_v1.1.md` |
| License | Apache 2.0 (`LICENSE`) |
| Primary docs | `docs/architecture/ARCHITECTURE.md`, `docs/current-state.md`, `docs/API.md` |

---

## 2. Technology stack

### Backend — Python 3.12+ (FastAPI modular monolith, CQRS)

| Category | Choice |
|---|---|
| Language | Python `>=3.12` (`requires-python = ">=3.12"`, targets `py312`, Python 3.14 compatible) |
| Web framework | FastAPI `>=0.115` (ASGI, via Uvicorn) |
| ASGI server | Uvicorn [`standard`] `>=0.30` |
| ORM / DB access | SQLAlchemy 2.0 async (`sqlalchemy[asyncio] >=2.0.30`) |
| DB dialect | SQLite (`aiosqlite`), PostgreSQL (`asyncpg`) |
| Migrations | Alembic `>=1.13` (39 revisions, head `b1e2100000019`) |
| Pre-Backend Reconciler | `backend/app/core/persistence/reconciler.py` (decoupled schema inspection, locks, and ACID backups) |
| Validation / config | Pydantic v2 `>=2.5`, `pydantic-settings >=2.1` |
| HTTP client | aiohttp `>=3.9` |
| Object storage | aioboto3 `>=15.5` (S3) |
| Scheduler | APScheduler `>=3.10` |
| NAT traversal (UPnP / port forward) | aioupnp `>=0.0.18` |
| Process/system monitoring | psutil `>=7.0` |
| Crypto | cryptography `>=42` |
| Prometheus metrics | prometheus-client `>=0.20` |
| Logging | structlog `>=24.1` |
| Serialization / misc | PyYAML `>=6` (config), python-multipart (uploads), packaging `>=23` |
| Architecture | Modular monolith, DDD modules (including `versioning` & `activity`), CQRS with Command/Query/Event buses |

Backend dev dependencies (`[project.optional-dependencies].dev`):
`httpx`, `pytest >=8`, `pytest-asyncio`, `pytest-cov`, `ruff`, `pyright`.

### Frontend — React 19 + TypeScript 5 (Vite)

| Category | Choice |
|---|---|
| Language | TypeScript 5+ (`tsc --noEmit` as typecheck) |
| Framework | React 19 (`react` / `react-dom` `^19`) |
| Build tool | Vite `^5.4` (with `@vitejs/plugin-react`, `@tailwindcss/vite`) |
| Routing | react-router-dom `^7.18` |
| Data fetching / server state | TanStack Query `@tanstack/react-query ^5` (+ devtools `^5.101`) |
| UI state | Zustand `^5.0` |
| Styling | Tailwind CSS v4 `^4.3` |
| Tests | Vitest `^2` + Testing Library (react, jest-dom, user-event) + jsdom `^29` |
| Lint | ESLint `^9` (typescript-eslint, react-hooks, react-refresh plugins) |

### Tooling / CI / tooling

| Category | Choice |
|---|---|
| Backend package manager | setuptools / `pyproject.toml` (build backend `setuptools.build_meta`) |
| Frontend package manager | npm (`package.json` / `package-lock.json`) |
| Lint gate | Ruff (`scripts/check-ruff-baseline` + `backend/ruff-baseline.json`, rule-preserving gate) |
| Type check | pyright (backend dev extra), `tsc --noEmit` (frontend) |
| CI workflows | 7 `.github/workflows/`: `backend-tests`, `docker-build-smoke`, `backend-version-ci`, `route-permission-ci`, `frontend-ci`, `verification-cadence`, `windows-ci` |
| Virtualization / deployment | Dockerfiles + `docker-compose.yml` (see `docs/DEPLOYMENT.md`) |
| Contracts | `contracts/`: `api.yaml`, `config.schema.json`, `events.yaml`, `permissions.yaml`, `plugin.yaml` |

---

## 3. Repository shape — counts

### Code size (measured 2026-10-02)

| Scope | Files | Lines | Command |
|---|---|---|---|
| Backend Python (app + tests + alembic) | 694 | **129,949** | `find backend/{app,tests,alembic} -name '*.py'` |
| — `backend/app` (production) | 412 | 64,892 | `find backend/app -name '*.py'` |
| — `backend/tests` | 239 | 62,129 | `find backend/tests -name '*.py'` |
| — `backend/alembic` (env + versions) | 43 | 2,928 | `find backend/alembic -name '*.py'` |
| Frontend `frontend/src` (TS + TSX + CSS) | 219 | **41,516** | `find frontend/src -name '*.ts*' -o -name '*.css'` |
| — `.tsx` | 156 | 32,829 | `find frontend/src -name '*.tsx'` |
| — `.ts` | 62 | 8,656 | `find frontend/src -name '*.ts'` |
| — `.css` | 1 | 31 | `find frontend/src -name '*.css'` |
| **TOTAL (backend + frontend source)** | **913** | **171,465** | — |
| Docs | 174 files | 43,680 lines of Markdown (`docs/`) | `find docs -name '*.md'` |

### By language (source files, backend + frontend)

| Extension | Files |
|---|---|
| `.py` | 694 |
| `.tsx` | 156 |
| `.ts` | 62 |
| `.css` | 1 |
| **Total** | **913** |

### Backend DDD modules (`backend/app/modules/`)

| Module | Files | Lines | Purpose |
|---|---|---|---|
| server | 64 | 15,820 | Aggregate, lifecycle, discovery, reconciliation, console stream |
| versioning | 66 | 12,664 | Git-inspired commits, DAG, tags, worktrees, test definitions, admission |
| exposure | 19 | 6,120 | Playit/UPnP/Cloudflare tunnel + port-forward |
| plugin | 35 | 3,935 | Plugin lifecycle + Modrinth/CurseForge catalog |
| health | 29 | 3,036 | Health evidence, evaluation, crash analysis |
| auth | 31 | 2,618 | Users, RBAC/ABAC, JWT, invites |
| operations | 14 | 2,304 | Multi-step operation state machine, steps, WS projection, idempotency |
| monitoring | 17 | 1,600 | Metrics, RCON, alert rules, unified container telemetry |
| backup | 18 | 1,182 | Backup/restore saga |
| event_store | 6 | 615 | Append-only event store + DLQ |
| activity | 11 | 485 | Persistent server activity logs & audit records |
| storage | 5 | 472 | Storage backends (local/S3/encryption) |
| shared | 3 | 282 | Shared value objects / exceptions |

### Tests (measured 2026-09-29)

| Suite | Count | Detail |
|---|---|---|
| Backend | **3,139 passed / 6 skipped** (3,145 collected) | 200+ `test_*.py` files across `backend/tests/` |
| Frontend | **752 passed across 89 test files** | `npm test` (`npx vitest run`) |
| Total | **3,891 total (3,885 passed, 0 failed, 6 skipped)** | Full regression verification & 6/6 CI quality gates PASS |
| Backend tests by area | — | `api`, `application`, `auth`, `core`, `domain`, `event_store`, `infrastructure`, `integration`, `monitoring`, `plugin`, `tasks`, `unit`, `versioning` |

---

## 4. Structure — trees

### Backend

```
backend/
├── app/
│   ├── api/v1/
│   │   ├── routers/          # 16 REST routers (144 route handlers + 11 system routes = 155 live routes)
│   │   └── schemas/          # Pydantic response/request models
│   ├── core/                 # settings, version, exceptions, buses, security
│   ├── modules/              # 13 DDD modules (server, versioning, activity, exposure,
│   │   │                     #   plugin, health, auth, operations, monitoring, backup, event_store, storage, shared)
│   │   └── <module>/{domain,application,infrastructure}/
│   ├── tasks/                # APScheduler jobs (metrics, health, backup, cleanup)
│   ├── websocket/            # /ws endpoint, handlers, connection registry
│   ├── services/             # orchestrators (server, backup)
│   └── registrations.py      # bus handler registration
├── alembic/                  # 42 migration revisions (head b1e2100000022)
├── tests/                    # api/ application/ auth/ core/ domain/ event_store/
│                             #   infrastructure/ monitoring/ plugin/ tasks/ versioning/
├── config/                   # YAML settings
├── data/                     # runtime data (servers, onx.db, etc.)
├── plugins/sdk/              # plugin host SDK
├── Dockerfile
└── pyproject.toml
```

### Frontend

```
frontend/
└── src/
    ├── App.tsx, main.tsx, index.css
    ├── pages/                    # auth, setup, invite, not-found...
    ├── components/
    │   ├── ui/                   # StatusBadge, EmptyState, PageHeader...
    │   ├── guards/               # route permission guards
    │   └── layout/
    ├── server_manager/
    │   ├── pages/                # 22 pages (server + versioning + marketplace)
    │   ├── components/           # 48+ components (BranchProtectionModal, TestEvidenceModal,
    │   │                         #   CommitDiffModal, MaterializationBrowserModal, etc.)
    │   ├── hooks/                # hooks (usePlugins, useServerExposure, etc.)
    │   └── utils/                # versionMatching, format, etc.
    ├── services/                 # api.ts, queryClient.ts (+ tests)
    ├── stores/                   # Zustand (toast, lastUsedServer, ...)
    ├── types/                    # shared TS types (types.ts)
    └── websocket/                # WS client + state sync
```

### Docs

```
docs/
├── architecture/        # ARCHITECTURE, SPECS, DATABASE, FRONTEND, SECURITY, PROVISIONING, etc.
├── decisions/           # 22 ADRs / DECISION records (0001–0016 + 6 DECISION records)
├── design/              # Design specs (incl. testing-system-refactor/ 01–08)
├── history/             # Historical features and bug remediation logs
├── roadmap/             # ROADMAP_v1.1.md
├── reference/           # module-map.md, event-catalog.md, etc.
├── runtime/             # providers.md, etc.
├── status/              # history.md
API.md, CONTRIBUTING.md, DEPLOYMENT.md, DEVELOPMENT.md, FEATURE_IDEAS.md,
README.md, VERSIONING.md, current-state.md, getting-started.md, testing.md
```

---

## 5. Specs & features

### Backend architecture / patterns

- **Modular monolith** with DDD: 11 bounded modules, each with
  `domain` / `application` / `infrastructure` layers (ADR `0001`, `0013`).
- **CQRS**: `CommandBus`, `QueryBus`, `EventBus` (ADR `0002`); handlers in
  `application/commands|queries`; domain events drive sagas (backup, deployment,
  restart).
- **Unit of Work** + SQLAlchemy async sessions; session lifecycle hardened to
  close even on commit failure.
- **ABAC/RBAC authorization**: permission strings (`plugin:manage`, `server.x.view`, …)
  evaluated by `PermissionEvaluator`; enforced via `require_permission` /
  `require_server_permission` dependencies + route→permission contract check (155/155 live routes).
- **WebSocket layer**: `/ws` endpoint, channel subscriptions, auth via token,
  metrics batching + domain-event dispatch, reconnect/backoff client.
- **Event store**: append-only SQLite table with SHA-256 cryptographic chain +
  dead-letter queue + replay.
- **Schedulers**: APScheduler jobs (metrics, health recalculation, backup,
  event cleanup) with sub-minute SQLite write bypass.

### Server lifecycle & runtime providers

- Explicit state machine (`STARTING` → `RUNNING` → `STOPPING` → `STOPPED`, plus
  `CRASHED`/`FAILED`), Start/Stop/Restart/Delete commands.
- Multi-runtime provider architecture (`ServerProvider` ABC):
  - `LocalLinuxProvider`: isolated tmux sessions (`mcs-{server_id}`) with `MCS_MANAGED=1` markers.
  - `LocalWindowsProvider`: Win32 detached process groups (`CREATE_NEW_PROCESS_GROUP`) with `taskkill /F /T` clean termination.
  - `DockerProvider`: isolated containers with async subprocess driver, bridge networking, dynamic local container IP extraction (`get_container_ip()`, `get_address()`), loopback RCON, Java 8/17/21/25 dynamic image resolution, container crash diagnostics collection, clean stop exit code mapping (`exited 0` $\rightarrow$ `STOPPED`), and broadened volume-filter container cleanup (`--filter volume={host_mount}`).
- Authoritative server identity stamping (`identity_writer.py`): Atomically stamps `.onx-manager/server.json` upon creation and import.
- Filesystem reconciliation engine (`FilesystemReconciliationService`): Synchronizes on-disk directories with DB, matches un-identified directories via normalized `root_path` with deterministic candidate scoring (+100 active, +50 running, +25 docker runtime, newest `updated_at` tiebreak), and performs in-place `ActionType.HEAL_IDENTITY`.
- Server console: streaming via WS, TPS validation w/ clamping, crash analyzer, health evidence collection.

### Network exposure (Phase 7)

- playit.gg real tunnel creation via control-plane API (`PlayitApiClient`),
  match-or-create, lifecycle teardown.
- UPnP (`aioupnp`) port-forward + Cloudflare tunnels; fallback precedence
  (playit > cloudflare > local).
- Deterministic tunnel runtime paths; socket-probe startup reconciliation.

### Plugin system

- Lifecycle manager (`INSTALLED→ENABLING→ENABLED→DISABLING→FAILED`), subprocess
  runner with JSON-RPC protocol, filesystem + network sandbox, dependency
  resolver, SDK (`BasePlugin`, event hooks, scoped HTTP).
- **Marketplace**: Modrinth catalog provider (search w/ paginated envelope
  `{items, total_hits, offset, limit}`, project detail, versions w/ fetch-all-
  then-slice `limit`/`offset`, Decision-8 schema fields `categories`, `loaders`,
  `client_side`, `server_side`, `date_modified`, `color`); install command selects
  best compatible version (strict two-part version matching); CompatibilityCard
  + ProjectVersionsList + detail tabs UI.
- CurseForge provider: **DEFERRED** (ADR/K16).

### Frontend features

- React 19 SPA: pages for auth, dashboard, servers (list/detail/console),
  plugins/marketplace, backups, monitoring, settings.
- TanStack Query data layer w/ typed query keys incl. pagination offset;
  Zustand for UI state; Tailwind v4 styling.
- First-class File Manager (`ServerFilesPage`) with reactive URL-`?path=` breadcrumb navigation and deep linking.
- Runtime provider badges (`server-provider-badge` in console and detail view).
- Dynamic local IP badges (`console-ip-badge`) displaying live container or host IP/port.
- Stop confirmation dialogs (`ConfirmDialog`) on single-click actions across dashboard, servers list, and server detail.
- Marketplace (SPEC-PLUGIN-PAGINATION-V3, fully shipped 2026-08-19):
  Modrinth-style ProjectCard list (loader/category/environment pills capped
  at 4 with a `+N` overflow link, downloads/follows, relative last-updated),
  driven by a reusable URL-`page`-param Pagination component (no prefetch);
  versions list paginated via the same offset contract.
- Live WebSocket console + server status invalidation; sub-second metric
  stream rendering (Sparkline, gauges).

### Versioning & Enterprise Branch Runtime (Stages A–G & Frontend Batch)

- **Git-inspired version control (Stage B)**: Persistent commit DAG with additive
  `server_commit_parents` junction table, DAG cycle detection, multi-parent merge history,
  immutable server tags (`server_tags`), deterministic tree and commit diffing (`diff_trees`, `diff_commits`),
  branch archiving (`ArchiveBranchCommand` and persistent `status` column on `server_branches`),
  revision resolution (`Revision.from_tag()`), and repository history queries.
- **Filesystem & materialization engine (Stage C)**: Domain `Materialization` aggregate (`PENDING`, `READY`, `STALE`, `REMOVED`),
  `ImportReview` aggregate with terminal state machine (`PENDING`, `CONFIRMED`, `DISMISSED`, `REVERTED`),
  atomic filesystem engine (`fs_atomic.py`, `tree_writer.py`) with root escape validation (`.onx/worktrees/`, `.onx/tests/`),
  and live changes review scanning (`POST /import-review/scan`).
- **Runtime scheduling & admission control (Stage D)**: Global admission scheduler (`RuntimeAdmissionScheduler`)
  with static + dynamic RAM/CPU headroom gating, FIFO run queue, concurrency caps, dynamic host headroom verification,
  and `server_admission_lease` serialization.
- **Console & observability (Stage E)**: Demand-driven `ConsoleStreamManager` (`docker logs -f --timestamps --tail 0`
  with tmux capture fallback, 5s subscriber debounce, batch flush at 50 lines / 100ms, 64KB frame partitioning,
  non-silent queue overflow drop marker); WS `exec_input` and `exec_resize` client messages with RBAC checks;
  additive `write_exec_input` provider extension; unified `docker stats` batch telemetry with multi-core CPU normalization
  clamped to 100%; frontend reconnect re-tail backfill and polling suppression when WS is connected.
- **Test platform & verification drivers (Stage F)**: Reusable `TestDefinition` configurations aggregate,
  1:1 `Runtime` entity container attach model via `server_runtimes` table, automated `PatternCrashAnalyzer`
  mod blame integration, structured `EvidenceBundle` generation, and lazy 24h debug artifact pruning in admission reaping.
- **Protected branches (Stage G)**: `BranchProtectionPolicy` frozen dataclass (`require_test_pass`, `allow_direct_commit`,
  `allow_force_bypass`, `prevent_deletion`), `ServerBranch` lifecycle methods (`protect`, `unprotect`, `can_commit_directly`, `can_archive`),
  `BranchProtectedError` (HTTP 409), `CreateCommitCommand` protection enforcement with administrative emergency bypass permission
  and audit logging, strict `AutoCommitLiveChangesCommand` and `ArchiveBranchCommand` rejection.
- **Dedicated frontend UI batch**: `BranchProtectionModal.tsx`, `TestDefinitionsModal.tsx`, `TestEvidenceModal.tsx`,
  `MaterializationBrowserModal.tsx`, `ImportReviewModal.tsx`, `ManageBranchesModal.tsx`, `CreateTagModal.tsx`, `CommitDiffModal.tsx`,
  and full page integration in `ServerVersioningPage.tsx` with all 22 versioning routes wired in `api.ts`.

### Backup & storage

- Backup restore/create/delete/verify commands, FULL/incremental suffix rules
  (tolerates missing world dir), BackupSaga with compensation, AES-256-GCM
  encryption, local + S3 (`aioboto3`) backends.

### High-reliability / ops features

- Prometheus metrics endpoint, health checks (DB, disk, DLQ, providers),
  request/audit/rate-limit middleware, structured logging (structlog),
  Docker deployment, settings hot-reload from `config/settings.yaml`.

---

## 6. Size & scope summary

| Metric | Value |
|---|---|
| Source lines (backend + frontend) | **171,282** |
| Source files (backend + frontend) | **913** |
| Python files / lines | 694 / 129,766 |
| TS+TSX files / lines | 218 / 41,485 |
| REST endpoints / live routes | 155 live routes (16 routers + app routes; 155/155 contract gate) |
| Alembic revisions | 42 (head `b1e2100000022`) |
| DB tables | 40+ (default dev DB at head) |
| CI workflows | 7 (backend-tests, docker-build-smoke, backend-version-ci, route-permission-ci, frontend-ci, verification-cadence, windows-ci) |
| Contracts | 6 (`api.yaml`, `config.schema.json`, `events.yaml`, `permissions.yaml`, `plugin.yaml`, `README.md`) |
| ADRs / Decisions | 28 (`0001`–`0016` + 12 formal `DECISION` records) |
| Backend tests | 3,139 passed / 6 skipped (3,145 collected, 0 failed) |
| Frontend tests | 752 passed across 89 test files (3,891 total tests across suites) |
| Docs Markdown | 174 files / 43,680 lines |

---

_Keep counts honest: refresh this file with the same commands whenever scope
changes materially. See `docs/current-state.md` for verified-vs-claimed
discipline._