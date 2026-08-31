# MCS Manager — Canonical Engineering Roadmap
**Status:** CANONICAL LIVING ROADMAP  
**Last Synchronized:** 2026-08-23  
**Governing Authority:** Independent Zero-Trust Reality Check & Redoc Reconciliation  
**Next Active Phase:** Phase 8 (Dynamic Endpoints & DNS Architecture)

---

## 1. Ground-Truth Phase Summary

| Phase | Name | Ground-Truth Status | Verification Evidence Summary | Next Action |
|---|---|---|---|---|
| **Phase 0** | Architecture & Modular Monolith Foundation | ✅ **VERIFIED DONE** | Modular DDD layout (9 modules), CQRS buses, SQLite WAL | Complete |
| **Phase 1** | Plugins & Marketplace Separation | ✅ **VERIFIED DONE** | Dedicated Marketplace route, Modrinth provider, plugin isolation | Complete |
| **Phase 2** | Product Foundation & UI Stabilization | ✅ **VERIFIED DONE** | React 19 UI, TanStack Query, Blade-Hosting style layout | Complete |
| **Phase 3** | Backend/Frontend Bug Fixing & Reliability | ✅ **VERIFIED DONE** | STARTING lifecycle, non-destructive retry, WAL busy_timeout | Complete |
| **Phase 4** | Authorization & Security Cleanup | ✅ **VERIFIED DONE** | Server-scoped permissions, Files API path sandboxing, RS256 JWT | Complete |
| **Phase 5** | Versioning & State Consistency | ✅ **VERIFIED DONE** | Single version source `4.0.0`, SemVer checks, DB revision floor | Complete |
| **Phase 6** | Testing / CI / Documentation Reliability | ✅ **VERIFIED DONE** | 2,131 backend + 574 frontend tests, 6 CI workflow gates | Complete (cadence active) |
| **Phase 7** | Network Access & Port Forwarding | ✅ **VERIFIED DONE** | Playit live tunnels, Cloudflare TCP/HTTP, UPnP, multi-target UI | Complete |
| **Post-Phase 7** | Fast Fixes & Provisioner Consolidation | ✅ **VERIFIED DONE** | Commits `2f6eb36`, `3fe7190`, `ad0973e`, `ac79d65`, `a73b743` | Complete |
| **Windows & Launcher** | Windows Lifecycle, Pre-Backend Reconciler & Upfront Prerequisite Gate | ✅ **VERIFIED DONE** | LocalWindowsProvider, reconciler.py, portable Node 22 LTS, Unicode/ASCII fallback, npm retry | Complete |
| **Phase 8** | Dynamic Endpoints & DNS Architecture | 🔶 **PLANNED NEXT** | Cloudflare / DNS provider automation for custom domains | Ready to begin |
| **Phase 9** | Final Stabilization & Performance | 🔶 **PLANNED** | Metric rollups, Redis/Arq queue, UI performance profiling | Post-Phase 8 |
| **Phase 10** | AI Operations & Natural Language Tooling | 🔶 **PLANNED (DEFERRED)** | Safe NL operator commands, health diagnostics AI assistant | Deferred |
| **Phase 11** | Cross-Platform Containerization | 🔶 **PLANNED** | Unified Docker execution model across host platforms | Post-Phase 8/9 |

---

## 2. Phase-by-Phase Verified Reality

### Phase 0: Architecture & Foundation ✅
- **Domain Boundaries:** 9 distinct DDD domain modules in [`backend/app/modules/`](file:///mnt/D/files/server_manger/backend/app/modules/) (`server`, `backup`, `auth`, `health`, `plugin`, `monitoring`, `event_store`, `shared`, `exposure`).
- **Buses:** Asynchronous `CommandBus`, `QueryBus`, and `EventBus` in [`backend/app/core/`](file:///mnt/D/files/server_manger/backend/app/core/).
- **Persistence:** SQLAlchemy 2.0 async engine with Alembic migration graph (28 revisions).

### Phase 1: Plugins & Marketplace Separation ✅
- **Global Marketplace:** Standalone `/marketplace` route independent of individual server instances.
- **Provider Abstraction:** `ModrinthPluginCatalogProvider` supporting version resolution, search, and asset downloads.
- **Evidence:** Commits `1c12e0c`, `e26c38b`, `a192656`, `a5c3917`, `14c2f96`, `9de865a`, `5a207a9`; 37 passing catalog provider tests.

### Phase 2: Product Foundation & UI Stabilization ✅
- **Frontend Architecture:** React 19 + TypeScript + Vite + TailwindCSS v4 with TanStack Query and Zustand stores.
- **Server Shell & Detail:** Blade-Hosting-inspired responsive shell with live metrics graphs, live console, and file manager.
- **Evidence:** Commits `adbf556`, `72e8c1c`, `e96f902`, `79d18d7`; 69 frontend test suites passing.

### Phase 3: Reliability & Runtime Supervision ✅
- **Server Lifecycle:** Intermediate `STARTING` status with cooperative cancellation, 30s restart cap, and DB WAL lock resilience.
- **Real-Time Streaming:** Sub-second metric streaming (0.2s–1.5s configurable window) via `MetricsBatcher`.
- **WebSocket Event Pipeline:** Fully wired `EventDispatcher` distributing 31 domain event types; crash handler recovery.
- **Evidence:** Commits `f23843b`, `f4fd254`, `e2a18fe`, `a3d02fd`, `5c8c9d4`; [`backend/tests/test_ws_delivery.py`](file:///mnt/D/files/server_manger/backend/tests/test_ws_delivery.py) (18/18 pass).

### Phase 4: Authorization & Security Cleanup ✅
- **Server-Scoped Security:** `require_server_permission` dependency validating server ownership and memberships.
- **Files API Sandboxing:** Path traversal enforcement (`Path.resolve().relative_to(root)`) and sensitive-file protection (`server.properties` 403 denied).
- **Owner System:** Single-use owner bootstrap (`/api/v1/setup/bootstrap`) and cryptographically signed invitations.
- **Evidence:** Commits `a47daa8`, `14a0d32`, `22f135f`; 105/105 live routes validated in [`contracts/permissions.yaml`](file:///mnt/D/files/server_manger/contracts/permissions.yaml).

### Phase 5: Versioning & State Consistency ✅
- **Single Source of Truth:** `get_app_version()` resolving version `4.0.0` from `pyproject.toml`.
- **Database Floor Enforcement:** `RELEASE_MINIMUM_DB_REVISION` ensuring fail-closed protection against stale databases.
- **Evidence:** Commit `408fadf`; `scripts/check-version-propagation` (PASS); `scripts/check-db-revision` (PASS).

### Phase 6: Testing / CI / Documentation Reliability ✅
- **Test Volume:** 2,019 passed backend unit/integration tests + 574 passed frontend unit/integration tests.
- **CI Workflows:** 5 automated workflows configured in `.github/workflows/` (backend-tests, backend-version-ci, route-permission-ci, frontend-ci, verification-cadence).
- **Evidence:** Commit `9d904ff`; live test runs observed this session.

### Phase 7: Network Access & Port Forwarding ✅
- **Subsystem Architecture:** Dedicated `exposure` DDD module in [`backend/app/modules/exposure/`](file:///mnt/D/files/server_manger/backend/app/modules/exposure/).
- **Exposure Providers:** Live Playit.gg tunnel agent lifecycle, Cloudflare TCP/HTTP tunneling, UPnP port forwarding.
- **Multi-Target Port Management:** Companion service registration (Bedrock UDP, BlueMap, Dynmap, VoiceChat).
- **UI:** Panel Access Exposure and Game Server Network Exposure views.
- **Evidence:** Commits [`56cd384`](file:///mnt/D/files/server_manger/) through [`dece81f`](file:///mnt/D/files/server_manger/); archived specs in [`docs/history/phase-7/`](file:///mnt/D/files/server_manger/docs/history/phase-7/).

---

## 3. In-Flight Work (Uncommitted Working Tree — Pending Disposition) 🔄

The following 3 logical workstreams currently reside uncommitted in the working tree (50 modified + 7 untracked files):

### Workstream A: Plugin Description Markdown & Platform System
- **Scope:** Real Markdown + HTML description rendering via `react-markdown` and `rehype-sanitize`; official brand SVG icons for 12 loaders; single source of truth [`platforms.ts`](file:///mnt/D/files/server_manger/frontend/src/server_manager/data/platforms.ts); clickable `?loader=` search tags.
- **Status:** Complete and tested (44 frontend tests, 37 backend tests). Ready for commit.

### Workstream B: Server Runtime & Diagnostics Leak Prevention
- **Scope:** Isolated session lifecycle in [`get_runtime_diagnostics.py`](file:///mnt/D/files/server_manger/backend/app/modules/server/application/queries/get_runtime_diagnostics.py) eliminating 194 SAWarning connection leaks per 40s; `LocalLinuxProvider` script execution support (`run.sh`/`user_jvm_args.txt`) and tmux session pre-check.
- **Status:** Complete and verified in live runtime tests. Ready for commit.

### Workstream C: Forge/NeoForge Provisioner & Missing Commit Files
- **Scope:** Complete staging of the 4 files omitted from commit [`e392672`](file:///mnt/D/files/server_manger/) (Alembic migration `b1e2100000008`, `installer.py`, `test_installer_runner.py`) + fixing Finding F-RC-02 (`exit_code=None` in `SubprocessInstallerRunner`).
- **Status:** Requires F-RC-02 fix and commit to repair master branch integrity.

---

## 4. Next Planned Phases (Realistically Next)

### Phase 8: Dynamic Endpoints & Custom DNS Architecture 🔶
- **Goal:** Allow operators to bind their own domain names (e.g. `play.mydomain.com`) to dynamic tunnel endpoints automatically.
- **Key Deliverables:**
  1. DNS provider abstraction (`CloudflareDnsProvider`, `NamecheapDnsProvider`, `Route53DnsProvider`).
  2. Automatic SRV and A/CNAME record synchronization matching active Playit/Cloudflare tunnel addresses.
  3. Domain verification and TLS certificate status reporting in panel UI.
- **Prerequisites:** Phase 7 (Complete).

### Phase 9: Final Stabilization & Performance Optimization 🔶
- **Goal:** Close remaining technical debt, optimize long-running resource utilization, and harden production telemetry.
- **Key Deliverables:**
  1. Resolve frontend TypeScript compilation debt (9 errors in 4 files) to re-enable strict `tsc` CI enforcement.
  2. Reconcile Ruff baseline regressions (16 rule categories).
  3. Metric data rollup pipeline (raw 0.2s → 1m → 1h aggregations) to prevent database growth.
  4. Real Redis/Arq task queue backend for high-volume deployments.
- **Prerequisites:** In-Flight Workstreams + Phase 8.

### Phase 10: AI Operations & Natural Language Tooling 🔶 (Deferred)
- **Goal:** Safe, natural-language operational copilot for server troubleshooting, log analysis, and automated plugin recommendations.
- **Key Deliverables:**
  1. Sandboxed read-only log analysis and crash dump interpretation engine.
  2. Operator action confirmation flows (human-in-the-loop for any mutating server command).
- **Prerequisites:** Phase 9.

### Phase 11: Cross-Platform Unified Docker Containerization 🔶
- **Goal:** Replace host-level tmux/process execution with isolated per-server Docker containers across Linux, macOS, and Windows.
- **Key Deliverables:**
  1. Standardized `DockerProvider` implementation implementing `ServerProvider` interface.
  2. Automated volume mounting, memory limits, and network bridge management per server instance.
  3. Host-agnostic game server execution model.
- **Prerequisites:** Phase 9.
