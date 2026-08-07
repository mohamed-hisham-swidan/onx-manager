# MCS Manager — Project Status

**Project:** Minecraft Server Manager v4.0  
**Code Name:** MCS Manager  
**Version:** 4.0.0 (authoritative — the version reported by the app; planning
docs that once said "7.1.0" are stale)  
**License:** MIT  
**Repository:** `server_manger/`  
**Last updated:** 2026-08-04

> **Factual baseline:** This document is the **historical narrative** (batch
> history, session changelog, known-limitations log). It is **not** the source
> of truth for current counts. For verified, current numbers (version, tests,
> DB state, routers/migrations/ADRs/contracts, known issues) see
> **[`docs/current-state.md`](../current-state.md)**, which was verified
> 2026-08-04 and supersedes any conflicting number in this file.

---

## Full Project History

### Pre-existing Codebase — `ee67851` (2026-07-24)

Initial commit. The project was already at a mature state with:
- Full FastAPI backend with modular monolith architecture
- React 19 frontend with Vite, TanStack Query, Zustand
- SQLAlchemy 2.0 async ORM with Alembic migrations
- CQRS with Command/Query/Event buses
- 6 DDD modules (server, backup, plugin, auth, monitoring, event_store)
- WebSocket layer
- Task queue + scheduling
- RBAC/ABAC auth, JWT RS256, audit hash chain
- Plugin subprocess isolation
- Docker setup (in-progress)
- 781 tests passing

### Batch 1 — Docker Setup — `850be67` (2026-07-26)

**What was done:**
- Created `Dockerfile` (backend + frontend multi-stage builds)
- Created `docker-compose.yml` with health checks and volumes
- Created `.dockerignore`, `requirements.txt`, `requirements-dev.txt`
- Created `.env.example` with all configuration variables
- Created `docs/DEPLOYMENT.md` with production deployment guide
- Verified end-to-end: `docker compose build` + `docker compose up` + health check

**Files changed:** 9 files in total.

### Batch 2 — Real Test Suite Against Sandbox (2026-07-26)

**What was done:**
- Set up sandbox test environment (isolated DB + server directory)
- Ran test suite: S1 (create server), S2 (list), S3 (details), S4 (delete), S5 (delete nonexistent), S6 (invalid version), S7 (post-delete checks)
- **Production incident**: production DB got polluted (server creation + deletion leaked from test) and production directories were accidentally deleted during cleanup
- **Recovery**: recreated missing directories (`eula.txt` + `server.properties`) matching production DB records

**Bugs discovered:**
1. `MCS_SERVERS_DATA_DIR` env var not wired through the app — files written to hardcoded `data/servers/`
2. `minecraft_version` returns HTTP 500 instead of 422 for invalid input
3. DELETE returns 204 for non-existent servers
4. Orphan directories: server directory persists after DB row delete

### Batch 2.5 — Bug Fixes — 4 commits (2026-07-27)

| Commit | Fix | Before | After |
|--------|-----|--------|-------|
| `e765390` | Fix 1: `MCS_SERVERS_DATA_DIR` env var | Files written to hardcoded `data/servers/` | Configurable via env var; sandbox uses `data/servers_test/` |
| `43a8ca6` | Fix 2: `minecraft_version` validation | Invalid versions returned HTTP 500 | Returns 422 with explicit error message |
| `4b4f097` | Fix 3: DELETE 404 for missing servers | Deleting nonexistent server returned 204 | Returns 404 with `NOT_FOUND` error code |
| *(built-in)* | Fix 4: orphan directory cleanup | Already correctly implemented — directory removed after DB commit | Verified in sandbox test |

**Retest:** 11/11 scenarios passing. Production directories untouched.

### Batch 3 — Reorganize File Structure — 3 commits (2026-07-27)

| Commit | Step | What changed |
|--------|------|-------------|
| `40fd4b9` | Step 2 | Renamed `app/storage/` → `app/core/persistence/` (87 imports, 2 tests updated) |
| `20bd07e` | Step 3 | Consolidated `backend/docs/DATABASE.md` into `docs/DATABASE.md` |
| `d4f11b8` | Step 4 | Fixed `STATUS.md` directory listing (incorrectly merged two "storage" directories) |

**Verification:** 781 tests passing, app boots, frontend builds, Docker builds.

### Batch 4 — Architecture Hardening + Docs Rewrite — 6 commits (2026-07-27)

**Phase A — Architecture Audit & Fixes:**

| Commit | Step | What changed |
|--------|------|-------------|
| `01beca4` | A2 | Added `field_validator("email")` to CreateUserRequest/UpdateUserRequest — same class of bug as the minecraft_version fix (invalid email returned 500 instead of 422). Added handler safety-net. |
| *(built-in)* | A1 | Read-only audit — found: hexagonal boundaries clean, no dead code/TODOs, error handling consistent, 3 unmajor untested query handlers (low-risk), 1 validation gap (email, fixed above) |

**Phase A verification:**
- 781 tests passing ✅
- Bad email → 422 ✅
- All Batch 2.5 regressions preserved ✅
- App boots, frontend builds, Docker builds ✅

**Phase B — Documentation:**

| Commit | Step | What changed |
|--------|------|-------------|
| `9906ff8` | ADRs | Added 4 new ADRs (ADR-0007 through ADR-0010) |
| `3dddb68` | B2 | Full rewrite of `docs/ARCHITECTURE.md` — current module structure, dependency diagram, validation strategy, sandbox isolation, ADR index |
| `7a4f443` | B3 | Updated `docs/API.md` (DELETE 404), `docs/DEVELOPMENT.md` (sandbox pattern, Docker) |
| *(this commit)* | B4 | Full rewrite of `docs/STATUS.md` — complete history, accurate tree, known limitations |
| *(next commit)* | B5 | Updated `.ai/PROJECT_STATE.json` and `.ai/AI_RULES.md` |
| *(next commit)* | B6 | Updated `docs/README.md` index, cross-reference check |

---

## Current Repository Structure

```
server_manger/
├── .ai/                          # AI session governance
│   ├── AI_RULES.md               # AI execution rules
│   ├── TOKEN_POLICY.md           # Token budget rules
│   ├── PROJECT_STATE.json        # Machine-readable project state
│   ├── locks/                    # Concurrent modification locks
│   └── README.md                 # AI directory overview
├── _archive/                     # Historical batch artifacts
│   └── Implementation/
│       ├── Batch-01/ through Batch-11/   # Per-batch execution logs
│       └── QA/                   # QA templates
├── backend/                      # Python FastAPI backend
│   ├── app/
│   │   ├── main.py               # FastAPI app factory + startup
│   │   ├── registration.py       # Module registration
│   │   ├── api/                  # REST + WebSocket layer
│   │   │   ├── deps.py           # DI dependencies
│   │   │   ├── errors.py         # Global exception handlers
│   │   │   └── v1/
│   │   │       ├── middleware/   # Auth, audit, rate-limit, request-id
│   │   │       ├── routers/      # 10 REST endpoint groups
│   │   │       └── schemas/      # Pydantic schema modules
│   │   ├── core/                 # Shared infrastructure
│   │   │   ├── command_bus.py    # Command bus (CQRS)
│   │   │   ├── query_bus.py      # Query bus
│   │   │   ├── event_bus.py      # Event bus
│   │   │   ├── saga.py           # Saga orchestrator
│   │   │   ├── circuit_breaker.py# Circuit breaker pattern
│   │   │   ├── idempotency.py    # Idempotency keys
│   │   │   ├── feature_flags.py  # Feature flags
│   │   │   ├── config.py         # Configuration (AppSettings)
│   │   │   ├── exceptions.py     # MCSError hierarchy
│   │   │   ├── security.py       # Password hashing, API keys
│   │   │   ├── logging.py        # Structured logging
│   │   │   └── persistence/      # DB persistence layer (ADR-0007)
│   │   │       ├── base.py       # DeclarativeBase, BaseRepository
│   │   │       ├── db.py         # DatabaseEngine, get_db
│   │   │       └── unit_of_work.py  # UnitOfWork
│   │   ├── modules/              # 9 DDD modules
│   │   │   ├── server/           # Minecraft server domain
│   │   │   ├── backup/           # Backup/restore domain
│   │   │   ├── auth/             # User & auth domain
│   │   │   ├── health/           # Health monitoring & diagnostics
│   │   │   ├── plugin/           # Plugin system domain
│   │   │   ├── monitoring/       # Health & metrics domain
│   │   │   ├── event_store/      # Event store module
│   │   │   ├── shared/           # Shared value objects
│   │   │   └── storage/          # File storage backends
│   │   ├── services/             # Cross-module orchestration
│   │   ├── tasks/                # Task queue & scheduling
│   │   └── websocket/            # WebSocket layer
│   ├── alembic/ + alembic.ini    # Database migrations (16 revisions)
│   ├── config/                   # Runtime config files
│   ├── data/                     # Server data (see data/ below)
│   ├── plugins/                  # Plugin SDK
│   ├── tests/                    # Backend test suite
│   ├── pyproject.toml
│   ├── requirements.txt
│   └── Dockerfile
├── contracts/                    # Shared contract schemas (6 files)
├── data/                         # Runtime data
│   └── servers/                  # Production server files (0 servers currently)
├── docs/                         # Professional documentation
│   ├── README.md                 # Documentation index
│   ├── STATUS.md                 # THIS FILE (historical narrative; see current-state.md for facts)
│   ├── ARCHITECTURE.md           # System architecture (12 ADRs)
│   ├── API.md                    # REST API reference
│   ├── DATABASE.md               # Database schema + migration guide
│   ├── FRONTEND.md               # Frontend architecture
│   ├── DEVELOPMENT.md            # Dev setup + sandbox guide
│   ├── CONTRIBUTING.md           # Contribution guide
│   ├── SECURITY.md               # Security architecture
│   ├── PROVISIONING.md           # Server provisioning
│   ├── DEPLOYMENT.md             # Production deployment guide
│   ├── getting-started.md        # 5-minute quickstart
│   ├── roadmap.md                # LEGACY roadmap v0 (superseded)
│   ├── testing.md                # Testing guide
│   ├── decisions/                # 12 Architecture Decision Records
│   ├── runtime/                  # Runtime subsystem (7 docs)
│   └── reference/                # Reference maps (5 docs)
├── events/                       # Domain event catalog
├── frontend/                     # React 19 + TypeScript + Vite
│   ├── src/                      # Main app code
│   ├── Dockerfile
│   └── nginx.conf
├── scripts/                      # Dev toolchain (10 scripts)
├── .env.example
├── docker-compose.yml
├── launcher.py
├── README.md
└── start.sh
```

---

## Architecture Summary

### Architecture Decisions (12 ADRs)

| ADR | Date | Title |
|-----|------|-------|
| 0001 | 2026-07-22 | Modular Monolith with Hexagonal Boundaries |
| 0002 | 2026-07-22 | Separate Command, Query, and Event Buses |
| 0003 | 2026-07-22 | All Plugins Run as Subprocesses |
| 0004 | 2026-07-22 | WebSocket — asyncio.Lock, EventDispatcher, Channel Permissions |
| 0005 | 2026-07-22 | JWT RS256 Authentication |
| 0006 | 2026-07-23 | Task Queue — Dual Implementation, Event Store Chain, DLQ |
| 0007 | 2026-07-27 | Rename app/storage/ to app/core/persistence/ |
| 0008 | 2026-07-27 | Environment-Variable-Driven Sandbox Isolation |
| 0009 | 2026-07-27 | Pydantic Field Validators for Domain Value-Object Inputs |
| 0010 | 2026-07-27 | Commit-per-Step Discipline for Structural Changes |
| 0011 | 2026-07-27 | Orphan Reconciliation — Ownership Verification |
| 0012 | 2026-08-04 | Same-Filesystem Staging for Atomic File Swaps |

### Bounded Contexts (9 Modules)

| Context | Module | Responsibility |
|---------|--------|----------------|
| Server Management | `server/` | Lifecycle, config, deployment, runtime supervision |
| Backup/Restore | `backup/` | World backup, restore, verification |
| Plugin System | `plugin/` | Install, registry, marketplace, isolated subprocess execution, SDK |
| User & Auth | `auth/` | JWT RS256 auth, RBAC/ABAC, audit chain |
| Health | `health/` | Health monitoring, crash diagnostics, integrity validation, health timeline |
| Monitoring | `monitoring/` | Health checks, metrics, alert rules |
| Event Store | `event_store/` | Append-only event log with cryptographic chain |
| Shared | `shared/` | Shared value objects (IDs, permissions, versions) |
| File Storage | `storage/` | S3/local file storage backends for backups |

### Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Runtime | Python | 3.14+ |
| Web Framework | FastAPI | 0.115+ |
| ASGI Server | Uvicorn | — |
| ORM | SQLAlchemy | 2.0+ (async) |
| Database | PostgreSQL / SQLite | 16 / 3 |
| Validation | Pydantic | 2 |
| Task Queue | InProcessQueue (only implementation in use; Arq/Redis exists as unused code) | — |
| Frontend | React | 19 |
| Language | TypeScript | 5 |
| Build | Vite | — |
| Styling | TailwindCSS | 4 |
| State | TanStack Query + Zustand | — |
| Testing (BE) | pytest (1070 collected; 1068 passing, 2 pre-existing env failures) | — |
| Testing (FE) | Vitest (236 tests) | — |
| Linting | Ruff | — |
| Container | Docker | — |

---

## Key Patterns

- **CQRS**: CommandBus (sync, idempotent, transactional) + QueryBus (sync, cached) + EventBus (async, retry + DLQ) — ADR-0002
- **Hexagonal/DDD**: Each module has domain/application/infrastructure layers; domain never imports infrastructure — verified clean in Phase A audit
- **Unit of Work**: Collects domain events during transaction, publishes after commit on success, rolls back on failure
- **Validation**: Two-layer defense — Pydantic field validators at HTTP boundary, handler safety-nets at domain boundary (ADR-0009)
- **Sandbox Isolation**: MCS_DATABASE_URL + MCS_SERVERS_DATA_DIR env vars isolate test/dev from production (ADR-0008)
- **Idempotency**: All commands carry idempotency keys; duplicates return cached results
- **Audit Hash Chain**: SHA-256 linked list for tamper-evident audit log
- **Plugin Isolation**: Subprocess with JSON-RPC, never in-process (ADR-0003)

---

## Current Production Database State

> Verified 2026-08-04. This supersedes the earlier state recorded below in the
> batch history (production was intentionally not upgraded to head at the time
> those entries were written).

- **File**: `backend/data/servers/mcs.db`
- **Alembic version**: `a3b2c3d4e5f6` (3 revisions behind head — `b5c6d7e8f9a0`, `3a42d373bb05`, `c4d5e6f7a8b9` pending)
- **Servers**: 0
- **Tables**: 27 (including `alembic_version`)
- **Head revision**: `c4d5e6f7a8b9` (the dev DB `backend/mcs.db` is at head)

> The 3 pending migrations are the pending_restores table plus the Modrinth /
> filesystem-tracking plugin columns. Production is intentionally not upgraded
> to head. When ready, run:
> `MCS_DATABASE_URL="sqlite+aiosqlite:///data/servers/mcs.db" alembic upgrade head`

---

## Tests & Coverage

> **Verified 2026-08-04:** `python -m pytest tests/` from `backend/` collects
> **1070** tests — **1068 passing, 2 pre-existing environment failures**
> (`test_start_server` closed-database rollback; `test_metrics_task_requires_collector`
> stale expectation vs graceful handler). Frontend: **236 passing across 41 files**.
> The file-by-file table below reflects the historical layout from Batch 10 and
> is retained for reference; the authoritative counts are above.

### Backend — 1070 collected (1068 passing, 2 pre-existing test environment failures)

| Test File | Tests | Group |
|-----------|-------|-------|
| `tests/test_command_bus.py` | 12 | Core |
| `tests/test_query_bus.py` | 14 | Core |
| `tests/test_event_bus.py` | 8 | Core |
| `tests/test_circuit_breaker.py` | 8 | Core |
| `tests/test_idempotency.py` | 5 | Core |
| `tests/test_saga.py` | 6 | Core |
| `tests/test_config.py` | 4 | Core |
| `tests/test_database.py` | 8 | Core |
| `tests/test_unit_of_work.py` | 6 | Core |
| `tests/application/test_server_commands.py` | 40 | Server |
| `tests/application/test_server_queries.py` | 15 | Server |
| `tests/application/test_console.py` | 5 | Server |
| `tests/application/test_backup_commands.py` | 9 | Backup |
| `tests/infrastructure/test_backup_saga.py` | 6 | Backup |
| `tests/application/test_plugin_commands.py` | 25 | Plugin |
| `tests/application/test_plugin_manifest.py` | 12 | Plugin |
| `tests/application/test_auth_commands.py` | 37 | Auth |
| `tests/application/test_monitoring.py` | 20 | Monitoring |
| `tests/application/test_supervisor.py` | 15 | Runtime |
| `tests/application/test_runtime_ownership.py` | 38 | Runtime |
| `tests/application/test_runtime_reconciliation.py` | 25 | Runtime |
| `tests/application/test_import_service.py` | 10 | Services |
| `tests/application/test_sagas.py` | 6 | Sagas |
| `tests/domain/test_server_aggregate.py` | 30 | Domain |
| `tests/domain/test_value_objects.py` | 25 | Domain |
| `tests/domain/test_events.py` | 10 | Domain |
| `tests/infrastructure/test_providers.py` | 22 | Providers |
| `tests/infrastructure/test_sandbox.py` | 12 | Plugin |
| `tests/infrastructure/test_repositories.py` | 50 | Infra |
| `tests/infrastructure/test_storage.py` | 21 | Storage |
| `tests/websocket/test_ws_manager.py` | 15 | WS |
| `tests/websocket/test_ws_handlers.py` | 10 | WS |
| `tests/api/test_api_endpoints.py` | 65 | API |
| `tests/auth/test_login_flow.py` | 15 | Auth |
| `tests/auth/test_audit.py` | 8 | Auth |
| `tests/tasks/test_queue.py` | 28 | Tasks |
| `tests/tasks/test_monitoring.py` | 20 | Monitoring |
| `tests/monitoring/test_collector.py` | 15 | Monitoring |
| `tests/domain/test_health_aggregate.py` | 15 | Health |
| `tests/domain/test_health_events.py` | 20 | Health |
| `tests/domain/test_health_value_objects.py` | 30 | Health |
| `tests/application/test_health_commands.py` | 6 | Health |
| `tests/application/test_health_queries.py` | 6 | Health |
| `tests/infrastructure/test_health_repository.py` | 12 | Health |
| `tests/infrastructure/test_scanner.py` | 10 | Discovery |
| `tests/infrastructure/test_integrity.py` | 9 | Integrity |
| `tests/infrastructure/test_environment.py` | 5 | Environment |
| `tests/application/test_discovery_engine.py` | 3 | Discovery |
| `tests/application/test_registration_engine.py` | 2 | Discovery |
| `tests/application/test_startup_guard.py` | 4 | Startup |
| `tests/infrastructure/test_evidence_collector.py` | 11 | Diagnostics |
| `tests/infrastructure/test_crash_analyzer.py` | 18 | Diagnostics |
| `tests/infrastructure/test_recovery_orchestrator.py` | 13 | Diagnostics |
| `tests/infrastructure/test_health_calculator.py` | 22 | Health Calculator |
| `tests/event_store/test_event_store.py` | 15 | Event Store |
| `tests/event_store/test_dead_letter.py` | 8 | Event Store |
| `tests/plugin/test_plugin_runner.py` | 12 | Plugin |

### Frontend — 236 passing

| Area | Tests |
|------|-------|
| Zustand stores | 15 |
| WebSocket client | 25 |
| Shared components | 30 |
| Domain components | 25 |
| Pages | 35 |
| Services | 10 |
| Hooks | 8 |

> The area breakdown above is historical (from Batch 10). The verified total is
> **236 tests across 41 files** (measured 2026-08-04). The earlier 148-test
> count and the "1145 total" figure are stale.

> The backend count here (984 in the prior revision, corrected to 997 in the
> original Batch 10 update) was stale before the reconciliation session began:
> earlier enforcement work in commit `33336e0` and subsequent batches added
> tests that were never reflected in this document's total. This reconciliation
> session added **no new test functions** — the verified count is 1070
> collected, from the actual test run.

---

## Known Limitations

| Issue | Impact | Status |
|-------|--------|--------|
| ~~`reconcile_orphans()` / `claim_localhost()` / `cleanup_orphans()` kill heuristically~~ | ~~Called at startup/pre-start, no ownership verification~~ | ✅ Fixed — `reconcile_orphans()` (4a6b9f3, Batch 6): ownership marker + cwd check + scope + audit + fail-safe. `claim_localhost()` / `cleanup_orphans()` (6d99146, Batch 7): shared `ownership_verifier.py`, PID-reuse protection via `start_time` (a66f322). |
| ArqQueue.get_status/get_result return stubs | Cannot query task progress in prod | ⚠️ Known |
| Metrics retention rollups not implemented | Raw metrics only (no 1m/1h/1d aggregation) | 🔶 Future |
| ContainerPluginRunner is a stub | Plugins can't run in Docker isolation yet | 🔶 Future |
| Production DB is 3 revisions behind head | alembic upgrade head runs 3 pending migrations | ⚠️ Documented (verified 2026-08-04) |
| ~~`reconcile_filesystem()` uses raw UUID vs slug+uuid dirname~~ | ~~Every production server directory falsely flagged as orphan~~ | ✅ Fixed in 415c3a3 + this batch |
| `server_dir()` vs `server_dir_name()` in jar_service.py | Inconsistent UUID-only vs slug+uuid naming | ⚠️ Architecture debt — no runtime impact; fallbacks only |
| JWT keys auto-generated in-process | Keys lost on restart unless PEM set explicitly | ⚠️ Documented |
| Permissions stored as comma-separated Text | Not normalized in DB | ⚠️ Known |
| Backup `save-all` completion regex unverified | `_save_world()` confirms save via console polling matching `saved the (game|world)` — written from general Minecraft-fork behavior, no confirmed Purpur log sample in repo | ⚠️ Verify against a real Purpur server |
| Backup saga step failures lose exception detail | `job.error_message` stores only `Failed at step '<step_name>'` (e.g. `save_world`); underlying cause visible only in server-side logs | ⚠️ Known |
| `SQLUserRepository.save()` triggers async lazy-load on `model.roles` (`MissingGreenlet`) | `repository.py:55` — `role_model not in model.roles` performs a lazy load with no active greenlet context; raises `MissingGreenlet` when saving a user that has roles. Currently unreachable (no code path assigns roles), but sits in the auth repository that Phase 4 authorization work is expanding | ⚠️ Found during 2026-08-02 WS audit — not yet triaged |
| Repo-root `data/` directory (gitignored, unused) | `data/` + `data/servers/` predate the `backend/` restructure (born 2026-07-26); `data/backups/` born 2026-08-03 from an init_storage repro run at repo root; stray `data/servers/mcs.db` was residue from a manual repo-root-relative alembic run (11:37:48, since removed). Live backend never touches it — no open fd, no writes; all real data lives under `backend/data/servers/`. Does NOT indicate stale DB rows: the two servers shown in the frontend are real and confirmed present under `backend/data/servers/` via dry-run reconcile | ⚠️ Found during 2026-08-03 investigation — awaiting Mohamed's decision on removal |
| WebSocket channel auth always denies (plural `servers:read` patterns vs singular `server:read` claims) | Every `subscribe` fails closed — no channel can ever be subscribed; server-push events never delivered (`EventDispatcher` never wired) | ⚠️ Verified 2026-08-02 — deferred to Phases 3–4 (see `PERMISSIONS_FUTURE_IDEAS.md` §4); tracked as K1/K2 in roadmap v2 (Phase 3) |
| `PATCH /api/v1/settings` is a stub | Returns `{"success": true, "message": "Settings updated (stub)"}`; nothing persists | ⚠️ K3 in roadmap v2 Phase 3 |
| Plugin `enable`/`disable` routes have no `require_permission` | Auth-only; only `uninstall` + marketplace routes gate on `plugin:manage` | ⚠️ K4 in roadmap v2 Phase 4 |
| Marketplace not a first-class frontend section | ~~No sidebar entry; reachable only from Plugins page Install button~~ **Resolved 2026-08-06 (K5)** — own `/marketplace` route + sidebar entry + global search (`GET /api/v1/marketplace/search`) + install-time server picker | ✅ Done |
| No backend CI workflow | Only `.github/workflows/frontend-ci.yml` exists; route-coverage not CI-enforced | ⚠️ K6 in roadmap v2 Phase 4 |

---

## Changelog — This Session (Batches 1–5)

| Date | Batch | Commits | Summary |
|------|-------|---------|---------|
| 2026-07-26 | 1 | `850be67` | Docker setup: Dockerfiles, docker-compose, requirements, .env.example, deployment docs |
| 2026-07-26 | 2 | *(test run)* | Real test suite against sandbox; discovered 4 production bugs; production data incident + recovery |
| 2026-07-27 | 2.5 | `e765390`, `43a8ca6`, `4b4f097` | Fix 1: MCS_SERVERS_DATA_DIR isolation. Fix 2: minecraft_version 422. Fix 3: DELETE 404. All verified 11/11. |
| 2026-07-27 | 3 | `40fd4b9`, `20bd07e`, `d4f11b8` | Reorganize: app/storage/ → app/core/persistence/, docs consolidation, STATUS.md fix |
| 2026-07-27 | 4 | `01beca4`, `9906ff8`, `3dddb68`, `7a4f443`, *(this)*, *(B5)*, *(B6)* | Phase A: architecture audit + email validation fix. Phase B: full docs rewrite, 4 new ADRs |
| 2026-07-27 | 5 | `4b48281` | Fix 5: reconcile_filesystem() directory naming mismatch — refactored to explicit `server_dir_name()` comparison + 3 regression tests. Removed stale Known Limitation. |
| 2026-07-27 | *investigation* | *(docs only)* | Investigated actual process-killing logic (runtime_reconciliation.py + runtime_ownership.py). Found: `reconcile_orphans()` kills ALL `mcs-*` tmux sessions + ALL Minecraft Java PIDs with zero DB cross-reference — called at every backend startup and via POST `/reconcile`. Added to Known Limitations. |
| 2026-07-28 | *architecture* | *(design doc)* | Designed Server Health & Integrity Engine architecture (13-section design document in `architecture/health-engine-design.md`) |
| 2026-07-28 | BATCH-01 | `18effba` | Created health bounded context foundation: domain aggregates/value objects/events/repository interfaces/domain services, application commands/queries/handlers, infrastructure ORM models/repository implementations, API router + schemas, Alembic migration, unit tests, documented integration. |
| 2026-07-28 | BATCH-02a | `3521d33` | `reconcile_orphans()` fix — now cross-references DB before killing. Running/starting servers protected. |
| 2026-07-28 | BATCH-02b | `2fc5938` | Discovery Engine (FilesystemScanner + DiscoveryEngine + periodic scan task), Registration Engine (consumes ServerDiscoveredEvent, creates Server aggregate), Integrity Validator (file/config checks), Environment Scanner (Java/disk/memory/provider), Startup Guard (pre-flight in StartServerHandler). 845→878 tests. |
| 2026-07-28 | BATCH-03 | `40e8571` | Crash Diagnostics & Recovery — EvidenceCollector (log reader + crash report parser + system snapshot), PatternCrashAnalyzer (18 patterns mapped to FailureCode), RecoveryOrchestrator (auto-restart with escalation after 3 crashes/300s), ServerCrashedEvent handler (collect→classify→recover pipeline). 878→920 tests. |
| 2026-07-28 | BATCH-04 | *(this commit)* | Health Calculator Engine — SignalHealthCalculator (sliding window, signal weighting, transition constraints, trend detection), EvaluateHealthCommand refactored to use real computation, HealthSignalHandler (subscribes to RuntimeHealthSignal/IntegrityCheckFailed/CrashClassified events, re-computes health), GenerateHealthReport query (uptime %, crash frequency, worst status), periodic health recalculation task. 920→942 tests. |

---

### Batch 6 — Orphan Reconciliation Ownership Verification — 2 commits (2026-07-30)

| Commit | Step | What changed |
|--------|------|-------------|
| `cb39233` | Phase 1 | Docs: correct Known Limitations entry — reconcile_orphans gap confirmed for untracked servers |
| `4a6b9f3` | Fix 6 | reconcile_orphans(): ownership marker (MCS_MANAGED=1) at process spawn, cwd verification vs project data dir, scope param (project_owned/system_wide), structured audit logging, fail-safe default on check uncertainty. main.py + API route updated. 13→25 tests (+12). |

**Verification:** 950 backend tests (948 passing, 2 pre-existing env failures), 148 frontend tests, lint clean.

---

### Batch 7 — Runtime Ownership Verification — 3 commits (2026-07-30)

| Commit | Step | What changed |
|--------|------|-------------|
| `6d99146` | Gap 1 | `ownership_verifier.py` (shared module): ownership check before kill in `claim_localhost()` + `cleanup_orphans()`; `scope` param; `KILL_DECISION` audit logging. +13 tests for verifier; +4 existing patched. |
| `a66f322` | Gap 2 | Store process `start_time` in DB (`RuntimeInfo.start_time`, `ServerModel.deployment_start_time`, Alembic migration). Capture in local provider. Compare in `verify_ownership()` — rejects recycled PIDs on start_time mismatch. +2 tests. |
| `433f982` | Gap 2b | Test: cwd-only ownership detection — verifies pre-fix servers (no env marker, correct cwd) are identified as owned and cleaned up. +1 test. |

**Known Limitations changes:** `⚠️ Partially fixed` → `✅ Fixed` (both `reconcile_orphans()` in Batch 6 and `runtime_ownership.py` in Batch 7 now verify ownership before killing).

**Verification:** 966 backend tests (964 passing, 2 pre-existing env failures — `test_start_server` startup guard, `test_metrics_task_requires_collector` graceful handler), 148 frontend tests. Docker build + up: both containers healthy.

### Batch 8 — Real Backup Pipeline — 4 commits (2026-08-01)

| Commit | Step | What changed |
|--------|------|-------------|
| `71b1626` | Phase 2 | Real backup pipeline: tar.gz world + config, AES-256-GCM encryption, upload with size/checksum, verify re-reads the artifact. `BackupJob.storage_path` tracked end-to-end. Encrypted on disk. Backend: 942→950 tests. |
| `775a457` | Fix 1 | Delete storage artifact **before** DB row deletion; on failure keep the row and return `success=False` — no more orphaned encrypted files. |
| `e5d4cb6` | Fix 2 | `artifact_path()` returns `f"{backup_id}.tar.gz.enc"` (no duplicated `backups/` prefix; `data/backups` base provides scoping). One historical row `1eb2ed72…` retains the old prefixed path, intentionally not migrated. |
| `0195589` | Fix 3 | `_save_world()` on a running server sends `save-all` and polls provider console output (up to 30s) for `saved the (game|world)` before backing up; timeout marks the job FAILED. Stopped server → no-op. |

**Verification:** 984 backend tests (982 passing, 2 pre-existing env failures — `test_start_server` startup guard, `test_metrics_task_requires_collector` graceful handler), 148 frontend tests. Two broken historical rows (`19089a12…`, `85b82fbe…`) are known stale test artifacts with NULL `storage_path`, not an open bug.

### K16A — Plugin Catalog Provider Configuration (2026-08-05)

| Commit | What changed |
|--------|-------------|
| *(uncommitted)* | Provider selection is now configuration-driven via `MCS_PLUGIN_PROVIDERS` (default `modrinth`), validated at startup in `main.py` lifespan (fail-fast on unknown/empty/multiple providers). **K16A accepts exactly one active provider**; the variable's comma-separated list syntax is intentionally preserved for forward compatibility with the remaining K16 work (multiple providers). Provider identity (`name`) lives on `PluginCatalogProvider`/`ModrinthProvider`; the install handler no longer hardcodes `"modrinth"` for `source`/`ProviderError`. Factory `build_plugin_catalog_provider(name=None, settings=None)` builds from the `_PROVIDERS` registry (single source of truth). New tests: `tests/infrastructure/test_plugin_catalog_providers.py` (+14). |

**Verification:** full backend suite — 1084 passed, 2 pre-existing env failures (`test_start_server`, `test_metrics_task_requires_collector`), unchanged from baseline. This is the first self-contained slice (K16A) of roadmap K16; remaining K16 work: inspecting the configured list via API + a second provider.

### Batch 9 — Authorization Coverage: Batch 1 (servers module) — 3 commits (2026-08-03)

| Commit | Step | What changed |
|--------|------|-------------|
| `5c58ea9` | Batch 1 | `require_permission(...)` enforced on 7 previously-unprotected mutating routes in `servers.py`, replacing bare `Depends(get_current_user)`: `POST /api/v1/servers` (server:write), `POST /api/v1/servers/scan` (server:write), `POST /api/v1/servers/import` (server:write), `PATCH /api/v1/servers/{server_id}` (server:write), `POST /api/v1/servers/{server_id}/start` (server:start), `POST /api/v1/servers/{server_id}/command` (server:write), `POST /api/v1/servers/refresh` (server:write). Tests updated to use `privileged_header` (no assertion changes). |
| `4a9d8eb` | Test fix | Pin test process cwd to `backend/` (`_sandbox_cwd` autouse fixture) so CWD-relative key defaults in `encryption.py`/`jwt.py` never write a stray root-level `config/` when the suite runs from the repo root. Test-only; production code untouched. |
| `04305b2` | Docs | Flip the 7 Batch 1 routes to `status: enforced` in `contracts/permissions.yaml` (summary header counts updated, 12 → 19 enforced). |

**Verification:** full backend suite from the repo root — 997 tests (995 passing, 2 pre-existing env failures — `test_start_server` startup guard, `test_metrics_task_requires_collector` graceful handler), 148 frontend. `contracts/permissions.yaml` re-diffed against the live route table: 0 gaps, 0 stale entries. `backend/config/` (real, gitignored) confirmed byte-identical after the run — no stray root-level `config/` or `mcs.db` artifacts.

### Batch 10 — Authorization Coverage: Batch 2 (backups module) — 2 commits (2026-08-03)

| Commit | Step | What changed |
|--------|------|-------------|
| `*(this commit)*` | Batch 2 | `require_permission(...)` enforced on 2 previously-unprotected mutating routes in `backups.py`, replacing bare `Depends(get_current_user)`: `POST /api/v1/backups` (backup:create), `POST /api/v1/backups/{backup_id}/verify` (backup:read). `DELETE /api/v1/backups/{backup_id}` (backup:delete) and `POST /api/v1/backups/{backup_id}/restore` (backup:restore) were already enforced and are unchanged. |
| `*(this commit)*` | Test fix | `privileged_header` fixture gains `backup:create`, `backup:read` (additive, nothing removed). 10 tests swapped `auth_header` → `privileged_header` (they perform the now-gated actions). `test_delete_backup_without_permission_denied` and `test_restore_backup_without_permission_denied` restructured: the backup is created with `privileged_header` (setup), and only the denied action itself is attempted with `auth_header` (zero perms) so the `403 PERMISSION_DENIED` assertion still proves what it claims. No new test functions added — backend total unchanged at 997. |
| `*(this commit)*` | Docs | Flip the 2 Batch 2 routes to `status: enforced` in `contracts/permissions.yaml` (v1.2 → v1.3; summary header counts updated, 19 → 21 enforced, 15 → 13 unprotected). |

**Verification:** full backend suite — 997 tests (995 passing, 2 pre-existing env failures — `test_start_server` startup guard, `test_metrics_task_requires_collector` graceful handler), 148 frontend; **unchanged from Batch 1** (no new test functions). `contracts/permissions.yaml` re-diffed against the live route table: 0 gaps, 0 stale entries (66/66). Note: FastAPI 0.139 defers router inclusion via lazy `_IncludedRouter`, so the live-table diff requires forcing materialization via `app.openapi()` before iterating routes — unlike Batch 1's simpler introspection; direct dependency-closure inspection confirmed all 4 backups mutating routes bind the correct permission string (`backup:create`/`backup:read`/`backup:delete`/`backup:restore`).

*Generated: 2026-08-01 · Project: MCS Manager v4.0 (4.0.0) · Batch 8 — Backup Pipeline*

> **2026-08-04 reconciliation:** this document is the historical narrative.
> Verified current facts (version `4.0.0`, test counts, DB state, router /
> migration / ADR / contract counts, known issues) live in
> [`docs/current-state.md`](../current-state.md). The governing roadmap is
> [`docs/roadmap/MCS-Manager-Engineering-Blueprint-V5.md`](../roadmap/MCS-Manager-Engineering-Blueprint-V5.md).
