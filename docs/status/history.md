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
| WebSocket channel auth & metrics push (K1/K2a) | Plural `servers:read` vs singular `server:read` permission mismatch; client subscription wiring; real-time metrics batch push | ✅ Fixed 2026-08-08 (`b98da77` [singular permissions], `d096f75` [frontend subscriptions], `db1889d` [metrics push], `2978eed` [dynamic token]) |
| WebSocket domain-event delivery & crash handler dormancy (K2b) | `EventDispatcher` (`dispatcher.py:16`) is implemented but never instantiated or subscribed in `start_websocket_services()` (`endpoint.py:64`); all non-metric domain events (server lifecycle, crash, backup, invite, tunnel) are dropped at `EventBus`; `OfflineMessageBuffer` is unfed. Adjacent gap: `HandleServerCrashHandler` and `HealthSignalHandler` are never subscribed anywhere (crash→health pipeline dormant). | ⚠️ Partially Fixed / Open Gap — Pending Design Spec & EventDispatcher wiring |
| Plugin `enable`/`disable` routes have no `require_permission` | Auth-only; only `uninstall` + marketplace routes gate on `plugin:manage` | ⚠️ K4 in roadmap v2 Phase 4 |
| Marketplace not a first-class frontend section | ~~No sidebar entry; reachable only from Plugins page Install button~~ **Resolved 2026-08-06 (K5)** — own `/marketplace` route + sidebar entry + global search (`GET /api/v1/marketplace/search`) + install-time server picker | ✅ Done |
| No backend CI workflow | Only `.github/workflows/frontend-ci.yml` exists; route-coverage not CI-enforced | ⚠️ K6 in roadmap v2 Phase 4 |

---

### Batch 10 — Authorization Coverage: Batch 2 (backups module) — 2 commits (2026-08-03)

| Commit | Step | What changed |
|--------|------|-------------|
| `*(this commit)*` | Batch 2 | `require_permission(...)` enforced on 2 previously-unprotected mutating routes in `backups.py`, replacing bare `Depends(get_current_user)`: `POST /api/v1/backups` (backup:create), `POST /api/v1/backups/{backup_id}/verify` (backup:read). `DELETE /api/v1/backups/{backup_id}` (backup:delete) and `POST /api/v1/backups/{backup_id}/restore` (backup:restore) were already enforced and are unchanged. |
| `*(this commit)*` | Test fix | `privileged_header` fixture gains `backup:create`, `backup:read` (additive, nothing removed). 10 tests swapped `auth_header` → `privileged_header` (they perform the now-gated actions). `test_delete_backup_without_permission_denied` and `test_restore_backup_without_permission_denied` restructured: the backup is created with `privileged_header` (setup), and only the denied action itself is attempted with `auth_header` (zero perms) so the `403 PERMISSION_DENIED` assertion still proves what it claims. No new test functions added — backend total unchanged at 997. |
| `*(this commit)*` | Docs | Flip the 2 Batch 2 routes to `status: enforced` in `contracts/permissions.yaml` (v1.2 → v1.3; summary header counts updated, 19 → 21 enforced, 15 → 13 unprotected). |

---

### Phase 1 — Plugins / Marketplace Separation — Closed (2026-08-07)

| Commit | Step | What changed |
|--------|------|-------------|
| `1c12e0c` | Phase 1 | Closed Phase 1 — resolved D4 (marketplace routes remain server-scoped with global discovery exception). Marketplace first-class sidebar entry (K5). |

---

### Phase 2 — Product Foundation & UI Stabilization — Closed (2026-08-07)

| Commit | Step | What changed |
|--------|------|-------------|
| `311a524` | Phase 2 | Settings page honesty pass — rendered read-only warning banner and disabled non-persisted controls. |
| `9e8ae1b` | Phase 2 | Added non-committed Settings UX redesign vision (`09b-vision-settings-ux.md`). |
| `a958293` | Phase 2 | CreateServerPage: distinguished version-fetch failure from empty version list. |
| `75a8401` | Phase 2 | ServerDetailPage: added distinct not-found state for missing servers. |
| `50a0466` | Phase 2 | Extracted shared ErrorState component across 9 pages. |
| `04d92cd` | Phase 2 | Surfaced WebSocket connection state honestly across the UI (DEGRADED state). |
| `7347471` | Phase 2 | Closed Phase 2 — marked Phase 2 completed in project state tracking. |

---

### Phase 3 — Backend/Frontend Reliability, WebSocket Fixes, Real-time Metrics & Settings Persistence — Closed (2026-08-09)

| Commit | Step | What changed |
|--------|------|-------------|
| `181ef37` | Recon | Documented 5 confirmed Marketplace UX/feature gaps with screenshot evidence. |
| `b98da77` | Phase 3 | Fix K1/K2 (backend): corrected channel permissions from plural to singular (`server:read`), added `admin:full` bypass, fixed 3-part channel validation. |
| `d096f75` | Phase 3 | Fix K1/K2 (frontend): wired active channel subscriptions on mount/route change in `ServerDetailPage` and `WebSocketManager`. |
| `db1889d` | Side-quest | Wired real-time metrics push over WebSocket (`MetricsBridgeHandler` + `MetricsBatcher` every ~2s). |
| `2437590` | Phase 3 | Settings persistence (backend): file-backed `config/settings.yaml`, live `settings_store.py`, consumer hot-reload across 6 services, `requires_restart` response array. 1115/1115 tests passing. |
| `789dcbd` | Phase 3 | Settings persistence (frontend): removed read-only banner, wired real `PATCH` mutation, added restart badges, 4 card sections redesign, full accessibility, 332/332 tests passing. |

---

### Phase 4 — Authorization & Security Cleanup — Closed (2026-08-11)

| Commit | Step | What changed |
|--------|------|-------------|
| `a47daa8` | Phase 4 | Server-scoped authorization layer (ServerModel.owner_id + ServerMembershipModel), require_server_permission dependency with path/query/body defense-in-depth conflict checking, full Files API wiring, gating of 5 remaining mutating routes, monitoring alerts IDOR fix (/alerts/{server_id}), permissions.yaml contract and frontend client updates. 1158/1158 tests passing. |

*Generated: 2026-08-11 · Project: MCS Manager v4.0 (4.0.0) · Phase 4 Closed*

> **2026-08-11 reconciliation:** this document is the historical narrative.
> Verified current facts (version `4.0.0`, test counts, DB state, router /
> migration / ADR / contract counts, known issues) live in
> [`docs/current-state.md`](../current-state.md). The governing roadmap is
> [`docs/roadmap/MCS-Manager-Engineering-Blueprint-V5.md`](../roadmap/MCS-Manager-Engineering-Blueprint-V5.md).
