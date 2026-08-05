# MCS Manager — Current State (Verified)

**Status:** Authoritative, evidence-based snapshot of the codebase as of
2026-08-04. Every claim below was verified against source code, the database,
and a live test run. This document supersedes the stale counts and claims in
`STATUS.md` and is the baseline that `mcs-manager-roadmap-v2.md` is built on.

**Last verified:** 2026-08-04
**App version (code):** `4.0.0` (`backend/app/main.py:216`, `backend/pyproject.toml:3`)

> Note on version numbers: the application reports `4.0.0` everywhere in code
> and OpenAPI. Internal planning documents have at various times referenced
> "7.1.0" as a project/session version; that number does **not** appear
> anywhere in the codebase. The authoritative version is `4.0.0`.

---

## 1. Repository shape

| Item | Count | Evidence |
|------|-------|----------|
| Backend Python source files | 261 | `find backend/app -name "*.py"` |
| Backend test files | 90 | `find backend/tests -name "test_*.py"` |
| Frontend test files | 41 | `find frontend/src -name "*.test.*"` |
| REST routers (`api/v1/routers/`) | 10 | `auth, backups, health, monitoring, plugins, schedules, servers, settings, software, users` |
| Alembic migration revisions | 16 | `backend/alembic/versions/` |
| Architecture Decision Records | 12 | `docs/decisions/0001`–`0012` |
| Contract files | 6 | `contracts/{api.yaml, config.schema.json, events.yaml, permissions.yaml, plugin.yaml, README.md}` |
| DDD modules | 9 | `auth, backup, event_store, health, monitoring, plugin, server, shared, storage` |
| CI workflows | 1 (frontend only) | `.github/workflows/frontend-ci.yml` — no backend CI workflow exists |

---

## 2. Test suite (measured 2026-08-04)

### Backend — `backend/` `python -m pytest tests/`

| Metric | Value |
|--------|-------|
| Collected | **1070** |
| Passed | **1068** |
| Failed | **2** (pre-existing environment failures) |

The 2 failing tests, and their cause:

1. `tests/api/test_api_endpoints.py::TestServers::test_start_server` — the test
   triggers a database session teardown that hits a
   `sqlite3.ProgrammingError: Cannot operate on a closed database` on rollback.
   Environment/teardown issue, not an application logic failure.
2. `tests/tasks/test_metrics_collector.py::test_metrics_task_requires_collector`
   — expects `KeyError` when the metrics collector is uninitialized, but the
   task now logs a warning (`MetricsCollector not initialized — skipping
   collection`) and returns instead. Test expectation is stale relative to the
   current graceful-handler behavior.

Both failures are documented throughout `STATUS.md` and prior batches. Neither
blocks a release claim — but they are **open test-suite defects** that should be
closed (either fixed or formally re-baselined).

### Frontend — `frontend/` `npx vitest run`

| Metric | Value |
|--------|-------|
| Test files | **41** |
| Tests | **236** (all passing) |

---

## 3. Database state

### Production DB — `backend/data/servers/mcs.db`

| Property | Value |
|----------|-------|
| Alembic revision | `a3b2c3d4e5f6` — **3 revisions behind head** (`b5c6d7e8f9a0`, `3a42d373bb05`, `c4d5e6f7a8b9` pending) |
| Head revision | `c4d5e6f7a8b9` (`backend/mcs.db` dev DB is at head) |
| Servers | **0** (production currently has no servers) |
| Tables | 27 (including `alembic_version`) |

The 3 pending migrations: `b5c6d7e8f9a0` (pending_restores table),
`3a42d373bb05` (Modrinth source columns on `plugins`), `c4d5e6f7a8b9` (plugin
filesystem-tracking columns). None of these have been applied to the
production DB.

### Dev DB — `backend/mcs.db`

At head (`c4d5e6f7a8b9`).

---

## 4. What exists and works

### 4.1 Server lifecycle, runtime, backups (implemented)

- Create / delete / start / stop / restart / console / logs / version
  management; import and scan flows; `MCS_SERVERS_DATA_DIR` isolation
  (Batch 2.5 fix).
- Real backup pipeline: tar.gz + AES-256-GCM + checksum + verify; delete
  artifact before DB row (Batch 8); `save-all` console confirmation with
  timeout-fail.
- Runtime ownership verification (`reconcile_orphans` / `claim_localhost` /
  `cleanup_orphans`) with `MCS_MANAGED=1` marker + cwd + start_time checks
  (Batches 6–7).
- Filesystem reconciliation service (`FilesystemReconciliationService`) — disk
  is the source of truth; runs at startup and via `POST /servers/refresh`.

### 4.2 Auth & authorization (implemented, partially enforced)

- JWT RS256 (15-min access tokens), refresh-token rotation (7-day opaque
  tokens, SHA-256 hash in DB), API keys (`mcs_` prefix, SHA-256 hashed),
  Argon2id password hashing.
- `require_permission(...)` dependency enforced on **24 routes** per
  `contracts/permissions.yaml` (v1.4, verified against code 2026-08-04): 22
  mutating (servers 12, backups 4, plugins delete + marketplace install, users
  2, auth/api-keys 2) + 2 read-only marketplace routes (search, versions).
  Permission catalog: 17 `resource:action` strings; roles `viewer`,
  `operator`, `admin`.
- **Known gap:** most read routes and several mutating routes remain auth-only
  without a permission check (see `contracts/permissions.yaml`
  `route_permissions` for the full per-route matrix: 13 mutating routes
  unprotected, 21 sensitive GETs auth-only). Full detail in `SECURITY.md`.

### 4.3 WebSocket (real gate, non-functional in practice)

- Handshake validates the token **before** `accept()`.
- Per-channel authorization exists at subscribe time but **always denies**
  (fail-closed): `CHANNEL_PATTERNS` requires **plural** permission strings
  (`servers:read`, `backups:read`, …) while JWT/api-key claims carry
  **singular** REST permissions (`server:read`, …). Every `subscribe` is
  rejected with `PERMISSION_DENIED`.
- `EventDispatcher` / `MetricsBatcher` are defined but **never instantiated**
  anywhere in production code (`init_websocket` creates only the registry,
  authenticator, authorizer, buffer, rate limiter, and handler). No event-bus
  subscription wiring exists, so even a valid subscription would never receive
  pushed events.
- Net effect: **no channel can currently be subscribed and no server-push
  events are delivered.** Safe (fail-closed) but dead. See
  `docs/PERMISSIONS_FUTURE_IDEAS.md` §4 for the full trace.

### 4.4 Plugin system & marketplace (implemented, frontend not first-class)

- Plugin registry is DB-backed with per-row `filename` and `source`
  (`detected` / `modrinth`) tracking; the filesystem is the source of truth:
  on every `GET /plugins` a `ReconcilePluginsCommand` reconciles on-disk
  `.jar` files against the DB (creates `detected` rows, prunes deleted files).
- Marketplace routes (under `/api/v1/servers/{server_id}/plugins`):
  - `GET /marketplace/search` → Modrinth catalog search
  - `GET /marketplace/projects/{project_id}/versions` → versions + best-version
    selection for the server (with loader-fallback / version-mismatch notices)
  - `POST /marketplace/install` → download `.jar` to the server's `plugins/`
    folder with SHA-1/SHA-512 checksum verification + atomic write
- Provider abstraction: `PluginCatalogProvider` ABC + `ModrinthProvider`
  (`api.modrinth.com/v2`), factory `build_plugin_catalog_provider()` hardcoded
  default `"modrinth"`. Hardcoded loader facet list
  (`bukkit/paper/purpur/spigot/folia`).
- Version selection: `select_best_version()` ranks exact game-version+loader →
  compatible parent loader → closest game version (never hard-blocks).
- **Frontend status:** the marketplace exists only as `/plugins/marketplace`
  reached from the Plugins page's Install button
  (`?server=<id>`). It is **not** a first-class section: no sidebar entry, no
  top-level route in `App.tsx` beyond the plugin page, no standalone nav item.
  See `docs/plugins-and-marketplace.md`.

### 4.5 Task queue, monitoring, health (implemented; some stubs)

- `InProcessQueue` wired in `main.py` lifespan; scheduler loads `cron_jobs`
  from DB; `MetricsCollector`, Prometheus gauges, event store + DLQ, health
  calculator, crash diagnostics, recovery orchestrator all functional.
- Stubs / known-open items: `ArqQueue` defined but unused and uninstantiated;
  `GET/POST/DELETE /schedules` return stubs; `GET /monitoring/alerts` and
  `DELETE /monitoring/alerts/{id}` are stubs; `PATCH /settings` is a stub
  (`{"success": true, "message": "Settings updated (stub)"}` — nothing is
  persisted); metrics retention rollups not implemented.

### 4.6 Rate limiting

`RateLimitMiddleware` keys its in-memory sliding window by **`client_ip:path`**
(`backend/app/api/v1/middleware/rate_limit.py:41-42`), 60 requests/minute,
not configurable per route, no `X-RateLimit-*` headers; on limit it returns
`429` with a `Retry-After: 60` header. This is **already
per-client** — earlier roadmap text claiming a single process-global counter
was inaccurate and has been corrected in the v2 roadmap.

---

## 5. Known issues carried forward

Classification used by `mcs-manager-roadmap-v2.md`:

| ID | Issue | Severity | Kind |
|----|-------|----------|------|
| K1 | WS channel authorization always denies (plural/singular permission mismatch) | High | Bug (must fix) |
| K2 | `EventDispatcher`/`MetricsBatcher` never wired — no WS server-push | High | Bug (must fix) |
| K3 | `PATCH /settings` stub — nothing persists | Medium | Bug (should fix) |
| K4 | Plugin enable/disable routes use only `get_current_user` (no `require_permission`) | Medium | Bug (should fix) |
| K5 | Marketplace is not a first-class frontend section (no sidebar entry, no standalone nav) | Medium | Feature (Phase 1) |
| K6 | No backend CI workflow (only `frontend-ci.yml`); the permissions route-coverage matrix is not CI-enforced | High | Process (Phase 4) |
| K7 | 13 mutating routes + 21 sensitive GET routes lack permission enforcement (per `contracts/permissions.yaml`) | High | Bug (Phase 4) |
| K8 | `test_start_server` + `test_metrics_task_requires_collector` fail in the suite | Low | Test debt |
| K9 | Production DB 3 revisions behind head; no servers | Medium | Ops |
| K10 | `GET /metrics` public/unauthenticated (documented deferred decision) | Medium | Security (Phase 7) |
| K11 | JWT keys auto-generated in-process (lost on restart unless PEM set) | Medium | Architecture debt (Phase 4) |
| K12 | Permissions stored as comma-separated Text; `SQLUserRepository.save()` `MissingGreenlet` risk on role assignment | Medium | Architecture debt (Phase 4) |
| K13 | `ArqQueue.get_status/get_result` stubs; schedules/alerts stubs | Low | Known limitation |
| K14 | Backup `save-all` completion regex unverified against a real Purpur server | Low | Verify |
| K15 | Repo-root `data/` directory (gitignored, unused, awaiting cleanup decision) | Low | Housekeeping |
| K16 | Plugin marketplace provider list hardcoded to Modrinth (facet list, factory default) | Low | Architecture debt (Phase 1) |

---

## 6. Files that define this state

- `backend/app/main.py` — app factory, version, middleware, router registration
- `backend/app/api/v1/routers/plugins.py` — plugin list + marketplace routes
- `backend/app/api/v1/routers/settings.py` — settings GET + PATCH stub
- `backend/app/websocket/authorization.py`, `endpoint.py`, `dispatcher.py`,
  `handlers.py` — WS auth, channels, dispatch (see §4.3)
- `backend/app/api/v1/middleware/rate_limit.py` — per `client_ip:path` limiter
- `backend/app/modules/plugin/infrastructure/providers/` — provider ABC +
  Modrinth implementation
- `backend/app/modules/plugin/application/services/version_selector.py` —
  best-version selection
- `contracts/permissions.yaml` — live route→permission coverage matrix
- `backend/data/servers/mcs.db` / `backend/mcs.db` — production / dev databases
- `.github/workflows/frontend-ci.yml` — the only CI workflow
