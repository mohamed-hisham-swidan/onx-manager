# ONX Manager — Project Specs

A single authoritative overview of the project's **tech stack, libraries,
repository shape, code statistics, structure, specs, and features.**

> Companion docs: `docs/architecture/ARCHITECTURE.md` (design deep-dive),
> `docs/API.md` (endpoint reference), `docs/architecture/DATABASE.md` (schema),
> `docs/roadmap/ROADMAP.md` (public roadmap).

---

## 1. Project identity

| Attribute | Value |
|---|---|
| Name | ONX Manager (Development & Self-Hosted Environment) |
| Version | `0.1.0` (single source: `backend/pyproject.toml:3` via `app/core/version.py`) |
| Status | `v0.1.0` Ready — P1–P7 Complete (`SPEC-2026-11-09-SIMPLE-ADVANCED-MODES-02` v8.7: Simple/Advanced Modes, Docker-only Runtime, Two-Tier Envelope-Encrypted Backups, Mode Conversion, Enterprise Branch Runtime, Native Git + Vaults, Branch Runtimes, GitHub Sync, Modpacks + LEC + 1-Click Safe Upgrades) — Public Roadmap: `docs/roadmap/ROADMAP.md` |
| License | Apache 2.0 (`LICENSE`) |
| Primary docs | `docs/architecture/ARCHITECTURE.md`, `docs/API.md`, `docs/architecture/DATABASE.md` |

---

## 2. Technology stack

### Backend — Python 3.12 (installer-pinned; FastAPI modular monolith, CQRS)

| Category | Choice |
|---|---|
| Language | Python `>=3.12` (`requires-python = ">=3.12"`, targets `py312`, installer pins 3.12) |
| Web framework | FastAPI `>=0.115` (ASGI, via Uvicorn) |
| ASGI server | Uvicorn [`standard`] `>=0.30` |
| ORM / DB access | SQLAlchemy 2.0 async (`sqlalchemy[asyncio] >=2.0.30`) |
| DB dialect | SQLite (`aiosqlite`), PostgreSQL (`asyncpg`) |
| Migrations | Alembic `>=1.13` (52 revisions, head `b1e2100000032`, floor `b1e2100000032`) |
| Pre-Backend Reconciler | `backend/app/core/persistence/reconciler.py` (decoupled schema inspection, locks, and ACID backups) |
| Validation / config | Pydantic v2 `>=2.5`, `pydantic-settings >=2.1` |
| HTTP client | aiohttp `>=3.9` |
| Object storage | aioboto3 `>=15.5` (S3) |
| Scheduler | APScheduler `>=3.10` |
| NAT traversal (UPnP / port forward) | aioupnp `>=0.0.18` |
| Process/system monitoring | psutil `>=7.0` |
| Crypto | cryptography `>=42` (JWT RS256, backup AEAD, AES-256-GCM Class-C & secret vaults) |
| Prometheus metrics | prometheus-client `>=0.20` |
| Logging | structlog `>=24.1` |
| Serialization / misc | PyYAML `>=6` (config), `tomli-w==1.2.0` (TOML merge), python-multipart (uploads), packaging `>=23` |
| Architecture | Modular monolith, DDD modules (including `versioning` & `activity`), CQRS with Command/Query/Event buses |

Backend dev dependencies (`[project.optional-dependencies].dev`):
`httpx`, `pytest >=8`, `pytest-asyncio`, `pytest-cov`, `ruff==0.16.0`, `pyright`.

### Frontend — React 19 + TypeScript 5 (Vite)

| Category | Choice |
|---|---|
| Language | TypeScript 5.5+ (`tsc --noEmit` as typecheck) |
| Framework | React 19 (`react` / `react-dom` `^19`) |
| Build tool | Vite `^5.4` (with `@vitejs/plugin-react`, `@tailwindcss/vite`) |
| Routing | react-router-dom `^7.18` |
| Data fetching / server state | TanStack Query `@tanstack/react-query ^5` (+ devtools `^5.101`) |
| UI state | Zustand `^5.0` |
| Markdown rendering | `react-markdown ^10.1`, `remark-gfm ^4.0`, `rehype-raw ^7.0`, `rehype-sanitize ^6.0` |
| Styling | Tailwind CSS v4 `^4.3` (+ `@tailwindcss/typography`) |
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

### Code size (measured 2026-11-22)

| Scope | Files | Lines | Command |
|---|---|---|---|
| Backend Python (app + tests + alembic) | 872 | **229,177** | `find backend/{app,tests,alembic} -name '*.py'` |
| — `backend/app` (production) | 480 | 114,356 | `find backend/app -name '*.py'` |
| — `backend/tests` (325 `test_*.py` files) | 339 | 110,432 | `find backend/tests -name '*.py'` |
| — `backend/alembic` (env + 52 revisions) | 53 | 4,389 | `find backend/alembic -name '*.py'` |
| Frontend `frontend/src` (TS + TSX + CSS) | 318 | **75,264** | `find frontend/src -name '*.ts*' -o -name '*.css'` |
| — `.tsx` | 234 | 60,379 | `find frontend/src -name '*.tsx'` |
| — `.ts` | 83 | 14,050 | `find frontend/src -name '*.ts'` |
| — `.css` | 1 | 835 | `find frontend/src -name '*.css'` |
| **TOTAL (backend + frontend source)** | **1,190** | **304,441** | — |
| Docs | 64 `.md` files | 14,314 lines of Markdown (`docs/`) | `find docs -name '*.md'` |

### By language (source files, backend + frontend)

| Extension | Files |
|---|---|
| `.py` | 872 |
| `.tsx` | 234 |
| `.ts` | 83 |
| `.css` | 1 |
| **Total** | **1,190** |

### Backend DDD modules (`backend/app/modules/`)

| Module | Files | Lines | Purpose |
|---|---|---|---|
| versioning | 117 | 47,482 | Git-native versioning, lockfiles, CAS, LEC, vaults, merge engine, branch runtimes, GitHub sync, modpacks & safe upgrades |
| server | 64 | 17,656 | Aggregate, Simple/Advanced mode, lifecycle leases, discovery, reconciliation, provisioners, console stream |
| exposure | 19 | 6,128 | Playit/UPnP/Cloudflare tunnel + port-forward |
| plugin | 35 | 4,346 | Plugin lifecycle + Modrinth/CurseForge catalog |
| backup | 24 | 3,960 | Two-tier backup/restore (`tier1_snapshot`, `tier2_archive` envelope encryption), saga + pinned rollback protection |
| health | 29 | 3,033 | Health evidence, evaluation, crash analysis |
| auth | 31 | 2,648 | Users, RBAC/ABAC, JWT, invites |
| operations | 14 | 2,309 | Multi-step operation state machine, steps, WS projection, idempotency |
| monitoring | 17 | 1,601 | Metrics, RCON, alert rules, unified container telemetry |
| activity | 11 | 662 | Persistent server & branch activity logs + audit records |
| event_store | 6 | 633 | Append-only event store + DLQ |
| storage | 5 | 549 | Storage backends (local/S3/encryption) |
| shared | 3 | 282 | Shared value objects / exceptions |

### Tests (measured 2026-11-22)

| Suite | Count | Detail |
|---|---|---|
| Backend | **5,293 collected** across 325 `test_*.py` files | `pytest --collect-only -q` (`backend/tests/`, post-P6/P7 merge) |
| Frontend | **137 test files** on disk | `npx vitest run` (1,302 passed across 135 files at P5.5; P6/P7 added 2 test files) |
| CI Gates | **6/6 PASS** | `check-version-propagation`, `check-db-revision` (`b1e2100000032`), `check-ruff-baseline`, `check-route-contract` (`213/213`), `check-ps1-bom`, `check-stray-db` |
| Backend tests by area | — | `api`, `application`, `auth`, `core`, `domain`, `event_store`, `infrastructure`, `integration`, `monitoring`, `plugin`, `tasks`, `unit`, `versioning` |

---

## 4. Structure — trees

### Backend

```
backend/
├── app/
│   ├── api/v1/
│   │   ├── routers/          # 19 REST router files (213 live routes + WebSocket; 213/213 contract gate)
│   │   └── schemas/          # Pydantic response/request models
│   ├── core/                 # settings, version, exceptions, buses, security, allowlist, host_state, container_hardening
│   ├── modules/              # 13 DDD modules (server, versioning, activity, exposure,
│   │   │                     #   plugin, health, auth, operations, monitoring, backup, event_store, storage, shared)
│   │   └── <module>/{domain,application,infrastructure}/
│   ├── tasks/                # APScheduler jobs (metrics, health, backup, cleanup)
│   ├── websocket/            # /ws endpoint, handlers, connection registry
│   ├── services/             # orchestrators (server, backup, deployment)
│   └── registration.py       # bus handler & middleware registration
├── alembic/                  # 52 migration revisions (head b1e2100000032)
├── tests/                    # api/ application/ auth/ core/ domain/ event_store/
│                             #   infrastructure/ integration/ monitoring/ plugin/ tasks/ unit/ versioning/
├── config/                   # YAML settings
├── data/                     # runtime data (servers, onx.db, host-state, etc.)
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
    │   ├── ui/                   # 21 design-system primitives (Modal, ConfirmDialog, Table, Tabs, Banner, etc.)
    │   ├── brand/                # BrandLogo, VoxelBanner, SplashScreen
    │   ├── guards/               # route permission & system status guards
    │   └── layout/               # Sidebar, TopNav (shells in layouts/{AppShell,ServerShell}.tsx)
    ├── server_manager/
    │   ├── pages/                # 18 pages (server, versioning, mods/plugins, files, exposure, activity, settings)
    │   ├── components/           # Feature components + versioning/ (BranchRun*, GitHub*, CommitTimeline, TestRunList)
    │   │                         #   + p55/ (ModpackInstallWizardModal, SafeUpgradeWizardModal, UpgradePinnedBanner, settings)
    │   ├── context/, data/       # server context & static catalogs
    │   ├── hooks/                # hooks (usePlugins, useServerExposure, etc.)
    │   └── utils/                # versionMatching, serverMode, format, etc.
    ├── services/                 # api.ts, queryClient.ts (+ tests)
    ├── stores/                   # Zustand (auth, ui, ws, toast, activity, lastUsedServer, ...)
    ├── tokens/                   # multi-skin engine, dynamicFavicon, contrast & skin validator
    ├── types/                    # shared TS types (types.ts)
    └── websocket/                # WS client + state sync
```

### Docs

```
docs/
├── architecture/        # ARCHITECTURE, SPECS, DATABASE, FRONTEND, SECURITY, PROVISIONING, etc.
├── decisions/           # 24 md = 23 ADRs (0001–0023) + README
├── design/              # SPEC-2026-11-09-SIMPLE-ADVANCED-MODES-02 v8.7 + frontend-overhaul/ design system
├── governance/          # GOVERNANCE.md
├── reference/           # module-map.md, event-catalog.md, dependency-graph.md, contract-registry.md
├── roadmap/             # ROADMAP.md
├── runtime/             # lifecycle.md, providers.md, reconciliation.md, supervision.md, ownership.md, recovery.md
API.md, DEPLOYMENT.md, DEVELOPMENT.md, README.md, VERSIONING.md, getting-started.md, testing.md
```

---

## 5. Specs & features

### Backend architecture / patterns

- **Modular monolith** with DDD: 13 bounded modules (ADR `0001`, `0013`).
- **CQRS**: `CommandBus`, `QueryBus`, `EventBus` (ADR `0002`); handlers in
  `application/commands|queries`; domain events drive sagas (backup, deployment,
  restart).
- **Unit of Work** + SQLAlchemy async sessions; session lifecycle hardened to
  close even on commit failure.
- **ABAC/RBAC authorization**: permission strings (`plugin:manage`, `server.x.view`, …)
  evaluated by `PermissionEvaluator`; enforced via `require_permission` /
  `require_server_permission` dependencies + route→permission contract check (213/213 live routes).
- **WebSocket layer**: `/ws` endpoint, channel subscriptions, auth via token,
  metrics batching + domain-event dispatch, reconnect/backoff client.
- **Event store**: append-only SQLite table with SHA-256 cryptographic chain +
  dead-letter queue + replay.
- **Schedulers**: APScheduler jobs (metrics, health recalculation, backup,
  event cleanup) with sub-minute SQLite write bypass.

### Server lifecycle & runtime providers

- Explicit state machine (`STARTING` → `RUNNING` → `STOPPING` → `STOPPED`, plus
  `CRASHED`/`FAILED`), Start/Stop/Restart/Delete commands, serialized across workers by `ServerLifecycleLeaseManager` (`server_lifecycle_leases`) + `ServerLifecycleLockMiddleware` and fail-closed `stop_confirmed` gating.
- **Server Modes (`ServerMode`)**: `simple` vs `advanced`, enforced at router and command boundaries (`mode_guard.py`); `advanced_mode_enabled` defaults to POSIX-only (`os.name == "posix"`), with Windows kept Simple-only fail-closed (`P2-6g` Option B). Live Simple ↔ Advanced conversion endpoints shipped in P7-2 (`/convert/to-advanced`, `/convert/to-simple`).
- **Loaders & Provisioners (`ServerType`)**: `vanilla`, `paper` (Fill v3), `purpur`, `fabric`, `forge` (`1.17.1`–`1.20.1` bounds & argfile launch), `neoforge`, `quilt` (`P5.5`), `spigot`, `bukkit`, plus deterministic Java floor resolution (`java_floor.py`).
- **Docker-only runtime provider architecture (P6)** (`ServerProvider` ABC) with shared `container_hardening.py` across all 4 Docker spawn paths (`--cap-drop=ALL`, `--security-opt=no-new-privileges:true`, `--pids-limit=2048`, non-root `--user`, `/data`-only bind mount):
  - `DockerProvider` (sole active local runtime; local tmux/Win32 providers removed in `P6-2`, with local-to-Docker migration tooling in `P6-1`): isolated containers with async subprocess driver, bridge networking, dynamic local container IP extraction (`get_container_ip()`, `get_address()`), loopback RCON, Java 8/17/21/25 dynamic image resolution, config-fingerprint adoption, container crash diagnostics collection, clean stop exit code mapping (`exited 0` / `137` / `143` w/ OOM awareness $\rightarrow$ `STOPPED` or `ERROR`), and broadened volume-filter container cleanup (`--filter volume={host_mount}`). (`SSHProvider` / `CloudProvider` remain stubs.)
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
- CurseForge plugin-marketplace catalog provider: **DEFERRED** (ADR/K16); CurseForge modpack archive parsing & API integration (`curseforge_adapter.py`, `PanelSecretStore`) shipped in P5.5.

### Frontend features

- React 19 SPA with route-level `React.lazy` code-splitting across 18 feature pages + auth/setup/invite pages.
- Multi-skin semantic token engine (6 curated skins across Dark/Light modes, 7 accent colors, Rounded/Sharp corner styles, dynamic brand favicon & tokens per ADRs 0021–0023), 21 primitives in `components/ui/`, and unified `AppShell` / `ServerShell`.
- TanStack Query data layer w/ typed query keys incl. pagination offset;
  Zustand for UI/auth/WS/toast/activity state; Tailwind v4 styling.
- First-class File Manager (`ServerFilesPage`) with reactive URL-`?path=` breadcrumb navigation and deep linking.
- Runtime provider badges (`server-provider-badge` in console and detail view) and dynamic local IP badges (`console-ip-badge`).
- Stop confirmation dialogs (`ConfirmDialog`) on single-click actions across dashboard, servers list, and server detail.
- Marketplace (SPEC-PLUGIN-PAGINATION-V3, fully shipped 2026-08-19):
  Modrinth-style ProjectCard list (loader/category/environment pills capped
  at 4 with a `+N` overflow link, downloads/follows, relative last-updated),
  driven by a reusable URL-`page`-param Pagination component (no prefetch);
  versions list paginated via the same offset contract.
- Live WebSocket console + server status invalidation; sub-second metric
  stream rendering (Sparkline, gauges).
- P1–P5.5 UI surfaces: Simple/Advanced mode selection in server creation/import, native-Git Live State Files + AES-256-GCM Secret Vault UI, isolated Branch Runs & Data Templates (`BranchRunPanel`, `BranchRunModals`), GitHub Sync & webhook deliveries (`GitHubSyncPanel`, `GitHubModals`), and P5.5 Modpack Install / 1-Click Safe Upgrade wizards & settings (`ModpackInstallWizardModal`, `SafeUpgradeWizardModal`, `UpgradePinnedBanner`, `ServerP55SettingsCard`, `PanelP55IntegrationsSection`).

### Versioning, Simple/Advanced Modes & P1–P5.5 Platform

- **Enterprise Branch Runtime (Stages A–G)**: Persistent commit DAG (`server_commit_parents`), immutable tags (`server_tags`), branch archiving, `Materialization` & `ImportReview` aggregates, `RuntimeAdmissionScheduler` (`server_admission_lease`), demand-driven `ConsoleStreamManager` + WS `exec_input`/`exec_resize`, `TestDefinition` + 1:1 `Runtime` attach (`server_runtimes`), and `BranchProtectionPolicy` (`BranchProtectedError`).
- **P1/P2 Core Substrate, Allow-list v2.3 & Refresh Engine**:
  - `ServerMode` (`simple` / `advanced`) gate (`mode_guard.py`, POSIX-only `advanced_mode_enabled`), `BackupJobModel.pinned`, and `ensure_simple_baseline_lockfile()`.
  - Host-state layout (`host_state.py`, `0700` POSIX directories: `server-meta`, `class-c-vault`, `quarantine`, `lec`, `cas`, `repos`, `locks`, `journal`, `data-templates`).
  - **Allow-list v2.3** (`allowlist.py`): TOCTOU-free `open_safe_path_fd` descriptor traversal, canonical relpath checks, and 5 file classes (Class-A code jars, Class-B configs, Class-C runtime/state, Class-D ignored, Class-E forbidden).
  - **Lockfile Format 2.1 & CAS**: pure-domain parser/serializer (`lockfile.py`) + SHA-256 `ArtifactCas` + `CleanExportService` + `.onx-complete.json`.
  - **Native Git Engine & Refresh/Rollback**: `GitRunner`/`GitRepositoryService` (`repo.git` + `.onx/worktrees/<branch>`), `RepoWriteLock`, `RepoLeaseManager` (monotonic `fencing_token` + `flock`), two-tier `RefreshJournalRepository` + `RefreshStartupReconciler`, `DirectorySwapJournal` (`renameat2` / journaled `.prev`), `RefreshOrchestrator` (`1.10x` preflight, complement carry), `LiveRefreshService`, and `TriadRollbackService`.
- **P3 Protected `main`, Merge Engine & AES-256-GCM Vaults**:
  - System-level `main` branch protection & Promote removal; `merge_engine.py` (key-level 3-way merge for YAML/TOML/JSON/Properties + `diff3` + `SET_MERGEABLE_ARRAY_KEYS`); `DynamicClassCRegistry` (`server_dynamic_class_c`).
  - AES-256-GCM **Class-C Vault** (`class_c_snapshots`, `format_version=2`, `ONX_MASTER_KEK`), `${ONX_SECRET_*}` **Server Secret Vault** (`server_secrets`), and Structured & Pattern Secret Scanner (`secret_scanner.py` incl. multi-doc YAML & leaf `password` rules).
  - Native-Git Live State Files API and P3 frontend UI cutover.
- **P4 Branch Runtimes & Quiescent Data Templates**:
  - Isolated branch runtime engine (`BranchRuntimeService`), atomic `HostPortSet` allocation, ephemeral Class-C overlays (`white-list=true`, `enforce-whitelist=true`), quiescent `DataTemplates` (`server_data_templates`, 60s capped `save-off` + startup recovery), live RCON branch console, and branch activity logs.
- **P5 GitHub Sync & Webhooks**:
  - `GitHubSyncService` (`server_github_connections`, fetch-first sync, non-ff `main` guard, plain-jar gate, credential scrubber, encrypted `GitHubVault`, `RepoWriteLock`), HMAC-verified public webhook endpoint (`github_webhook_router`), durable `github_webhook_deliveries` queue, and frontend `GitHubSyncPanel` & modals.
- **P5.5 Modpacks, LEC & 1-Click Safe Upgrades**:
  - `.mrpack` & CurseForge parsers (`modpack_parser.py`, `curseforge_adapter.py`) with strict archive quarantine, 19-host `download_allowlist.py` (HTTPS, port 443, manual redirect validation), and `PanelSecretStore` (`panel_integration_secrets`).
  - **Loader Environment Cache (LEC)** (`lec_store.py`, `lec_builder.py`, `loader_env_cache_entries`) for Paper (Fill v3 pre-warm), Forge (`1.17.1`–`1.20.1` bounds & argfile launch), NeoForge, Fabric, and Quilt with reflink/copy attach and `java_floor.py`.
  - **Safe Upgrade Pipeline**: hash-only Modrinth compatibility matrix + transitive dependency BFS (`upgrade_matrix.py`), 3-way upgrade merge (`upgrade_merge.py`), pure-Python gzipped NBT `level.dat` DataVersion reader (`nbt_reader.py`), 4-step race-free `UpgradeHealthGateEvaluator` (stdout regex + TCP/RCON flush + NBT DataVersion + dimension smoke) with automatic triad rollback, `server_upgrades` tracking, `modpacks_upgrades.py` routes (`server_p55_router`, `lec_router`), and P5.5 frontend wizards (`ModpackInstallWizardModal`, `SafeUpgradeWizardModal`, `UpgradePinnedBanner`, `ServerP55SettingsCard`, `PanelP55IntegrationsSection`).

### Backup & storage (P7 Two-Tier Backups)

- **Tier-1 Snapshots** (`tier1_snapshot.py`) & **Tier-2 Archives** (`tier2_archive.py`) with chunked AES-256-GCM envelope encryption (`envelope_crypto.py`, `ONX_MASTER_KEK`-wrapped DEKs), `two_tier_restore.py`, `backup_jobs.tier` & `backup_jobs.pinned` rollback protection, FULL/incremental suffix rules, BackupSaga with compensation, and local + S3 (`aioboto3`) backends.

### High-reliability / ops features

- Prometheus metrics endpoint, health checks (DB, disk, DLQ, providers),
  request/audit/rate-limit middleware, structured logging (structlog),
  Docker deployment, settings hot-reload from `config/settings.yaml`.

---

## 6. Size & scope summary

| Metric | Value |
|---|---|
| Source lines (backend + frontend) | **301,861** |
| Source files (backend + frontend) | **1,171** |
| Python files / lines | 857 / 227,639 |
| TS+TSX files / lines | 313 / 73,387 (+ 1 CSS file, 835 lines) |
| REST endpoints / live routes | 213 live routes (19 router files + app routes; 213/213 contract gate) |
| Alembic revisions | 52 (head `b1e2100000032`) |
| DB tables | 56 ORM tables (`__tablename__`) |
| CI workflows | 7 (backend-tests, docker-build-smoke, backend-version-ci, route-permission-ci, frontend-ci, verification-cadence, windows-ci) |
| Contracts | 6 (`api.yaml`, `config.schema.json`, `events.yaml`, `permissions.yaml`, `plugin.yaml`, `README.md`) |
| ADRs | 23 ADRs (`0001`–`0023`) |
| Backend test files / collected | 325 `test_*.py` test files / 5,293 collected tests |
| Frontend test files | 137 test files |
| Docs | See `docs/README.md` for full documentation index |

---

_Keep counts honest: refresh this file with the same commands whenever scope
changes materially._