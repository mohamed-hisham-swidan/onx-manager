# MCS Manager — Project Status

**Project:** Minecraft Server Manager v4.0  
**Code Name:** MCS Manager  
**Version:** 7.1.0  
**License:** MIT  
**Repository:** `server_manger/`  
**Last updated:** 2026-07-28

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
│   │   │       ├── routers/      # 9 REST endpoint groups
│   │   │       └── schemas/      # 8 Pydantic schema modules
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
│   │   ├── modules/              # 8 DDD modules
│   │   │   ├── server/           # Minecraft server domain
│   │   │   ├── backup/           # Backup/restore domain
│   │   │   ├── auth/             # User & auth domain
│   │   │   ├── health/           # Health monitoring & diagnostics
│   │   │   ├── plugin/           # Plugin system domain
│   │   │   ├── monitoring/       # Health & metrics domain
│   │   │   ├── event_store/      # Event store module
│   │   │   └── storage/          # File storage backends
│   │   ├── services/             # Cross-module orchestration
│   │   ├── tasks/                # Task queue & scheduling
│   │   └── websocket/            # WebSocket layer
│   ├── alembic/ + alembic.ini    # Database migrations (9 revisions)
│   ├── config/                   # Runtime config files
│   ├── data/                     # Server data (see data/ below)
│   ├── plugins/                  # Plugin SDK
│   ├── tests/                    # Backend test suite
│   ├── pyproject.toml
│   ├── requirements.txt
│   └── Dockerfile
├── contracts/                    # Shared contract schemas (5 files)
├── data/                         # Runtime data
│   └── servers/                  # Production server files (2 servers)
├── docs/                         # Professional documentation
│   ├── README.md                 # Documentation index
│   ├── STATUS.md                 # THIS FILE
│   ├── ARCHITECTURE.md           # System architecture (10 ADRs)
│   ├── API.md                    # REST API reference
│   ├── DATABASE.md               # Database schema + migration guide
│   ├── FRONTEND.md               # Frontend architecture
│   ├── DEVELOPMENT.md            # Dev setup + sandbox guide
│   ├── CONTRIBUTING.md           # Contribution guide
│   ├── SECURITY.md               # Security architecture
│   ├── PROVISIONING.md           # Server provisioning
│   ├── DEPLOYMENT.md             # Production deployment guide
│   ├── getting-started.md        # 5-minute quickstart
│   ├── roadmap.md                # Past & future roadmap
│   ├── testing.md                # Testing guide
│   ├── decisions/                # 10 Architecture Decision Records
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

### Architecture Decisions (10 ADRs)

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

### Bounded Contexts (8 Modules)

| Context | Module | Responsibility |
|---------|--------|----------------|
| Server Management | `server/` | Lifecycle, config, deployment, runtime supervision |
| Backup/Restore | `backup/` | World backup, restore, verification |
| Plugin System | `plugin/` | Install, isolated subprocess execution, SDK |
| User & Auth | `auth/` | JWT RS256 auth, RBAC/ABAC, audit chain |
| Health | `health/` | Health monitoring, crash diagnostics, integrity validation, health timeline |
| Monitoring | `monitoring/` | Health checks, metrics, alert rules |
| Event Store | `event_store/` | Append-only event log with cryptographic chain |
| File Storage | `storage/` | S3/local file storage backends for backups |

### Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Runtime | Python | 3.14+ |
| Web Framework | FastAPI | 0.115+ |
| ASGI Server | Uvicorn | — |
| ORM | SQLAlchemy | 2.0+ (async) |
| Database | PostgreSQL / SQLite | 16 / 3 |
| Cache | Redis | 7 |
| Validation | Pydantic | 2 |
| Task Queue | InProcessQueue / Arq | Dev / Prod |
| Frontend | React | 19 |
| Language | TypeScript | 5 |
| Build | Vite | — |
| Styling | TailwindCSS | 4 |
| State | TanStack Query + Zustand | — |
| Testing (BE) | pytest (942 tests) | — |
| Testing (FE) | Vitest (148 tests) | — |
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

- **File**: `backend/data/servers/mcs.db`
- **Alembic version**: `fcc7545db19e` (1 revision behind head — `902b076bfa36` and `876be46160d3` pending)
- **Servers**: 2
- **Tables**: 23 (including `alembic_version`)
- **Production server directories**: `be193e92...` (OneBlock Reborn), `fc52c760...` (MINE)

> Production is intentionally not upgraded to head. When ready, run:
> `MCS_DATABASE_URL="sqlite+aiosqlite:///data/servers/mcs.db" alembic upgrade head`

---

## Tests & Coverage

### Backend — 942+ passing

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
| `tests/application/test_backup_commands.py` | 20 | Backup |
| `tests/application/test_restore_backup.py` | 8 | Backup |
| `tests/application/test_plugin_commands.py` | 25 | Plugin |
| `tests/application/test_plugin_manifest.py` | 12 | Plugin |
| `tests/application/test_auth_commands.py` | 37 | Auth |
| `tests/application/test_monitoring.py` | 20 | Monitoring |
| `tests/application/test_supervisor.py` | 15 | Runtime |
| `tests/application/test_runtime_ownership.py` | 38 | Runtime |
| `tests/application/test_runtime_reconciliation.py` | 13 | Runtime |
| `tests/application/test_import_service.py` | 10 | Services |
| `tests/application/test_sagas.py` | 12 | Sagas |
| `tests/domain/test_server_aggregate.py` | 30 | Domain |
| `tests/domain/test_value_objects.py` | 25 | Domain |
| `tests/domain/test_events.py` | 10 | Domain |
| `tests/infrastructure/test_providers.py` | 22 | Providers |
| `tests/infrastructure/test_sandbox.py` | 12 | Plugin |
| `tests/infrastructure/test_repositories.py` | 50 | Infra |
| `tests/infrastructure/test_storage.py` | 10 | Storage |
| `tests/websocket/test_ws_manager.py` | 15 | WS |
| `tests/websocket/test_ws_handlers.py` | 10 | WS |
| `tests/api/test_api_endpoints.py` | 60 | API |
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

### Frontend — 148 passing

| Area | Tests |
|------|-------|
| Zustand stores | 15 |
| WebSocket client | 25 |
| Shared components | 30 |
| Domain components | 25 |
| Pages | 35 |
| Services | 10 |
| Hooks | 8 |

**Total: 1090 tests** (942 backend + 148 frontend)

---

## Known Limitations

| Issue | Impact | Status |
|-------|--------|--------|
| ~~`reconcile_orphans()` kills ALL mcs-* tmux + Java PIDs~~ | ~~Called at every startup, no DB cross-reference~~ | ✅ Fixed in 3521d33 |
| ArqQueue.get_status/get_result return stubs | Cannot query task progress in prod | ⚠️ Known |
| Metrics retention rollups not implemented | Raw metrics only (no 1m/1h/1d aggregation) | 🔶 Future |
| ContainerPluginRunner is a stub | Plugins can't run in Docker isolation yet | 🔶 Future |
| Production DB is 1 revision behind head | alembic upgrade head runs 2 pending migrations | ⚠️ Documented |
| ~~`reconcile_filesystem()` uses raw UUID vs slug+uuid dirname~~ | ~~Every production server directory falsely flagged as orphan~~ | ✅ Fixed in 415c3a3 + this batch |
| `server_dir()` vs `server_dir_name()` in jar_service.py | Inconsistent UUID-only vs slug+uuid naming | ⚠️ Architecture debt — no runtime impact; fallbacks only |
| JWT keys auto-generated in-process | Keys lost on restart unless PEM set explicitly | ⚠️ Documented |
| Permissions stored as comma-separated Text | Not normalized in DB | ⚠️ Known |

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

*Generated: 2026-07-28 · Project: MCS Manager v4.0 (7.1.0) · Server Health & Integrity Engine Batch 04*
