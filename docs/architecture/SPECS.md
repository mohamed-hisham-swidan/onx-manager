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
| Status | Phase 5 CLOSED — Post-Phase-5 Bug Remediation CLOSED — Phase 4 (Community Feature Pool) UP NEXT (Unblocked) — Canonical Roadmap: `docs/roadmap/ROADMAP_v1.1.md` |
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
| Migrations | Alembic `>=1.13` (30 revisions, head `b1e2100000010`) |
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
| Architecture | Modular monolith, 10 DDD modules, CQRS with Command/Query/Event buses |

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
| CI workflows | 6 `.github/workflows/`: `backend-tests` (incl. `docker-build-smoke`), `backend-version-ci`, `route-permission-ci`, `frontend-ci`, `verification-cadence`, `windows-ci` |
| Virtualization / deployment | Dockerfiles + `docker-compose.yml` (see `docs/DEPLOYMENT.md`) |
| Contracts | `contracts/`: `api.yaml`, `config.schema.json`, `events.yaml`, `permissions.yaml`, `plugin.yaml` |

---

## 3. Repository shape — counts

### Code size (measured 2026-09-13)

| Scope | Files | Lines | Command |
|---|---|---|---|
| Backend Python (app + tests + alembic) | 521 | **91,192** | `find backend/{app,tests,alembic} -name '*.py'` |
| — `backend/app` (production) | 309 | 44,530 | `find backend/app -name '*.py'` |
| — `backend/tests` | 181 (167 `test_*.py` + conftest etc.) | 44,682 | `find backend/tests -name '*.py'` |
| — `backend/alembic` (env + versions) | 31 | 1,980 | `find backend/alembic -name '*.py'` |
| Frontend `frontend/src` (TS + TSX + CSS) | 183 | **31,002** | `find frontend/src -name '*.ts*' -o -name '*.css'` |
| — `.tsx` | 125 | — | `find frontend/src -name '*.tsx'` |
| — `.ts` | 57 | — | `find frontend/src -name '*.ts'` |
| — `.css` | 1 | — | `find frontend/src -name '*.css'` |
| **TOTAL (backend + frontend source)** | **704** | **122,194** | — |
| Docs | 121 files | 33,243 lines of Markdown (`docs/`) | `find docs -name '*.md'` |

### By language (source files, backend + frontend)

| Extension | Files |
|---|---|
| `.py` | 521 |
| `.tsx` | 125 |
| `.ts` | 57 |
| `.css` | 1 |
| **Total** | **704** |

### Backend DDD modules (`backend/app/modules/`)

| Module | Files | Lines | Purpose |
|---|---|---|---|
| server | 55 | 9,527 | Aggregate, lifecycle, discovery, reconciliation |
| exposure | 19 | 5,943 | Playit/UPnP/Cloudflare tunnel + port-forward |
| plugin | 32 | 2,792 | Plugin lifecycle + Modrinth/CurseForge catalog |
| health | 28 | 2,488 | Health evidence, evaluation, crash analysis |
| auth | 31 | 2,421 | Users, RBAC/ABAC, JWT, invites |
| monitoring | 17 | 1,224 | Metrics, RCON, alert rules |
| backup | 18 | 1,097 | Backup/restore saga |
| event_store | 6 | 563 | Append-only event store + DLQ |
| storage | 5 | 441 | Storage backends (local/S3/encryption) |
| shared | 3 | 267 | Shared value objects / exceptions |

### Frontend breakdown (`frontend/src/` — 183 files / 31,002 lines)

| Area | Files | Lines |
|---|---|---|
| `server_manager/pages` | 25 | 7,527 |
| `server_manager/components` | 40 | 7,377 |
| `components/ui` | 16 | 918 |
| `components/layout` | 4 | 401 |
| `components/guards` | 4 | 233 |
| `server_manager/hooks` | 8 | 720 |
| `server_manager/utils` | 10 | 575 |
| `services` | 3 | 729 |
| `stores` (Zustand) | 13 | 912 |
| `types` | 1 | 540 |
| `websocket` | 8 | 1,866 |
| `layouts` | 4 | 382 |
| root (`main.tsx`, `App.tsx`, `index.css`, `test-setup.ts`) | 4 | 126 |

### Tests (measured 2026-09-13)

| Suite | Count | Detail |
|---|---|---|
| Backend | **2,568 passed / 6 skipped** (2,574 collected) | 167 `test_*.py` files across `backend/tests/` |
| Frontend | **665 passed across 75 test files** | `npm test` (`npx vitest run`) |
| Total | **3,233 passed (0 failed)** | Full regression verification & 5/5 CI quality gates PASS |
| Backend tests by area | — | `api`, `application`, `auth`, `core`, `domain`, `event_store`, `infrastructure`, `integration`, `monitoring`, `plugin`, `tasks`, `unit` |

---

## 4. Structure — trees

### Backend

```
backend/
├── app/
│   ├── api/v1/
│   │   ├── routers/          # 15 REST routers (96 route handlers)
│   │   └── schemas/          # Pydantic response/request models
│   ├── core/                 # settings, version, exceptions, buses, security
│   ├── modules/              # 9 DDD modules (server, exposure, plugin, health,
│   │   │                     #   auth, monitoring, backup, event_store, storage, shared)
│   │   └── <module>/{domain,application,infrastructure}/
│   ├── tasks/                # APScheduler jobs (metrics, health, backup, cleanup)
│   ├── websocket/            # /ws endpoint, handlers, connection registry
│   ├── services/             # orchestrators (server, backup)
│   └── registrations.py      # bus handler registration
├── alembic/                  # 27 migration revisions (head b1e2100000007)
├── tests/                    # api/ application/ auth/ core/ domain/ event_store/
│                             #   infrastructure/ monitoring/ plugin/ tasks/
├── config/                   # YAML settings
├── data/                     # runtime data (servers, playit, etc.)
├── plugins/sdk/              # plugin host SDK
├── Dockerfile
└── pyproject.toml
```

### Frontend

```
frontend/
└── src/
    ├── App.tsx, main.tsx, index.css
    ├── pages/                    # auth, dashboard, server list/detail/console,
    │                             #   backups, plugins, monitoring, settings...
    ├── components/
    │   ├── ui/                   # StatusBadge, EmptyState, PageHeader...
    │   ├── guards/               # route permission guards
    │   └── layout/
    ├── server_manager/
    │   ├── pages/                # 25 pages (server + plugin marketplace)
    │   ├── components/           # 40 components (CompatibilityCard,
    │   │                         #   ProjectCard, ProjectVersionsList, etc.)
    │   ├── hooks/                # 8 hooks (incl. usePlugins, useServerExposure)
    │   └── utils/                # versionMatching, format, etc.
    ├── services/                 # api.ts, queryClient.ts (+ tests)
    ├── stores/                   # Zustand (toast, lastUsedServer, ...)
    ├── types/                    # shared TS types
    └── websocket/                # WS client + state sync
```

### Docs

```
docs/
├── architecture/        # 9 (ARCHITECTURE, SPECS, DATABASE, FRONTEND, SECURITY,
│                        #   PROVISIONING, K5-review, plugins-and-marketplace, network-access)
├── decisions/           # 13 ADRs
├── history/             # 48 (features, phase-7, post-phase-7, archive)
├── roadmap/             # 1 (Blueprint V5; marketplace-pagination-v3 archived to history/features)
├── reference/           # 6
├── runtime/             # 8
├── status/              # 1 (history.md)
├── plans/               # 1
API.md, CONTRIBUTING.md, DEPLOYMENT.md, DEVELOPMENT.md, FEATURE_IDEAS.md,
README.md, VERSIONING.md, current-state.md, getting-started.md, testing.md
```

---

## 5. Specs & features

### Backend architecture / patterns

- **Modular monolith** with DDD: 9 bounded modules, each with
  `domain` / `application` / `infrastructure` layers (ADR `0001`).
- **CQRS**: `CommandBus`, `QueryBus`, `EventBus` (ADR `0002`); handlers in
  `application/commands|queries`; domain events drive sagas (backup, deployment,
  restart).
- **Unit of Work** + SQLAlchemy async sessions; session lifecycle hardened to
  close even on commit failure.
- **ABAC/RBAC authorization**: permission strings (`plugin:manage`, `server.x.view`, …)
  evaluated by `PermissionEvaluator`; enforced via `require_permission` /
  `require_server_permission` dependencies + route→permission contract check.
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
| Source lines (backend + frontend) | ~122,194 |
| Source files (backend + frontend) | 704 |
| Python files / lines | 521 / 91,192 |
| TS+TSX files / lines | 182 / ~31,000 |
| REST endpoints / live routes | 106 live routes (15 routers + app routes; 106/106 contract gate) |
| Alembic revisions | 30 (head `b1e2100000010`) |
| DB tables | 32 + (default dev DB at head) |
| CI workflows | 6 (backend-tests incl. docker-build-smoke, backend-version-ci, route-permission-ci, frontend-ci, verification-cadence, windows-ci) |
| Contracts | 6 (`api.yaml`, `config.schema.json`, `events.yaml`, `permissions.yaml`, `plugin.yaml`, `README.md`) |
| ADRs | 14 (`0001`–`0012` + `DECISION-2026-09-10-001` + `DECISION-2026-09-12-001`) |
| Backend tests | 2,568 passed / 6 skipped (2,574 collected, 0 failed) |
| Frontend tests | 665 passed across 75 test files (3,233 total tests across suites) |
| Docs Markdown | 121 files / 33,243+ lines |

---

_Keep counts honest: refresh this file with the same commands whenever scope
changes materially. See `docs/current-state.md` for verified-vs-claimed
discipline._