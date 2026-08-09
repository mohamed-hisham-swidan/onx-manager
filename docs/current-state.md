# MCS Manager — Current State (Verified)

**Status:** Authoritative, evidence-based snapshot of the codebase as of
2026-08-09. Every claim below was verified against source code, the database,
and a live test run. This document supersedes the stale counts and claims in
`docs/status/history.md` (the historical narrative) and is the baseline that the
Blueprint V5 governing plan is built on.

**Last verified:** 2026-08-09
**App version (code):** `4.0.0` (`backend/app/main.py:216`, `backend/pyproject.toml:3`)

> Note on version numbers: the application reports `4.0.0` everywhere in code
> and OpenAPI. Internal planning documents have at various times referenced
> "7.1.0" as a project/session version; that number does **not** appear
> anywhere in the codebase. The authoritative version is `4.0.0`.

---

## 1. Repository shape

| Item | Count | Evidence |
|------|-------|----------|
| Backend Python source files | 262 | `find backend/app -name "*.py"` |
| Backend test files | 91 | `find backend/tests -name "test_*.py"` |
| Frontend test files | 44 | `find frontend/src -name "*.test.*"` |
| REST routers (`api/v1/routers/`) | 10 | `auth, backups, health, monitoring, plugins, schedules, servers, settings, software, users` |
| Alembic migration revisions | 16 | `backend/alembic/versions/` |
| Architecture Decision Records | 12 | `docs/decisions/0001`–`0012` |
| Contract files | 6 | `contracts/{api.yaml, config.schema.json, events.yaml, permissions.yaml, plugin.yaml, README.md}` |
| DDD modules | 9 | `auth, backup, event_store, health, monitoring, plugin, server, shared, storage` |
| CI workflows | 1 (frontend only) | `.github/workflows/frontend-ci.yml` — no backend CI workflow exists |

---

## 2. Test suite (measured 2026-08-09)

### Backend — `backend/` `python -m pytest tests/`

| Metric | Value |
|--------|-------|
| Collected | **1115** |
| Passed | **1115** |
| Failed | **0** (100% pass rate across entire backend test suite) |

### Frontend — `frontend/` `npx vitest run`

| Metric | Value |
|--------|-------|
| Test files | **44** |
| Tests | **332** (all passing) |


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
  unprotected, 21 sensitive GETs auth-only). Full detail in `architecture/SECURITY.md`.

### 4.3 WebSocket (fully functional & wired — Phase 3 closed)

- Handshake validates the token **before** `accept()`.
- Per-channel authorization enforces singular REST permissions (`server:read`, `backup:read`, etc.) with `admin:full` bypass (**K1 resolved in commit `b98da77`**).
- Active subscriptions (`server:*`, `metrics:<serverId>`) wired on component mount/route change in `WebSocketManager.tsx` and `ServerDetailPage.tsx` (**frontend wiring resolved in commit `d096f75`**).
- Real-time metrics push pipeline (**K2 resolved in commit `db1889d`**): `MetricsBridgeHandler` subscribes to `MetricCollectedEvent` on the `EventBus` and feeds `MetricsBatcher.add_sample()`, flushing batched samples over WebSocket channel `metrics:<serverId>` every ~2s. Frontend `WebSocketManager` merges incoming samples into the TanStack Query cache.

### 4.4 Plugin system & marketplace (implemented, frontend first-class)

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
  (`api.modrinth.com/v2`). Provider selection is configuration-driven via
  `MCS_PLUGIN_PROVIDERS` (default `"modrinth"`), validated at startup by
  `build_plugin_catalog_provider()` / `validate_plugin_providers()` — unknown,
  empty, or multiple configured providers fail fast. **K16A accepts exactly
  one active provider.** The variable keeps comma-separated list syntax for
  forward compatibility with the remaining K16 work (multiple providers), but
  configuring more than one is currently rejected. Provider identity (`name`)
  lives on the implementation. Hardcoded loader facet list
  (`bukkit/paper/purpur/spigot/folia`) remains inside `ModrinthProvider`.
- Version selection: `select_best_version()` ranks exact game-version+loader →
  compatible parent loader → closest game version (never hard-blocks).
- **Frontend status:** marketplace is a **first-class section (K5 done, 2026-08-06)** — own
  top-level route (`/marketplace`, `App.tsx`) and sidebar entry with a `store` glyph
  (`Icon.tsx`), plus a global search endpoint `GET /api/v1/marketplace/search`
  (`useMarketplaceSearchGlobal`) distinct from the server-scoped one. The install flow reworked
  into a global browse + server picker (pre-select: deep link → last-used server → first
  compatible → any). The server-scoped `/plugins/marketplace` (`?server=<id>`) surface remains
  for installs within a specific server's context. See `docs/architecture/plugins-and-marketplace.md`.

### 4.5 Task queue, monitoring, health, settings persistence (implemented)

- `InProcessQueue` wired in `main.py` lifespan; scheduler loads `cron_jobs`
  from DB; `MetricsCollector`, Prometheus gauges, event store + DLQ, health
  calculator, crash diagnostics, recovery orchestrator all functional.
- **Settings persistence & hot-reload (K3 resolved in commits `2437590` / `789dcbd`):**
  - Backend: file-backed at `config/settings.yaml` via `settings_store.py` (`LiveSettings`). Live settings load at startup and update on `PATCH /api/v1/settings`.
  - Hot-reload: updates immediately affect running instances of `RateLimitMiddleware`, `CircuitBreaker`, `EventBus`, `SagaOrchestrator`, and `cleanup_task`.
  - Restart flags: fields `app_name`, `log_level`, `debug` are persisted but require a backend service restart to affect runtime behavior; returned in the API's `requires_restart` response array.
  - Frontend: `SettingsPage.tsx` fully editable with 4 card sections, `PageHeader`, `RestartBadge`, and `role="alert"` / `role="status"` save feedback.
- Stubs / known-open items: `ArqQueue` defined but unused and uninstantiated;
  `GET/POST/DELETE /schedules` return stubs; `GET /monitoring/alerts` and
  `DELETE /monitoring/alerts/{id}` are stubs; metrics retention rollups not implemented.

### 4.6 Rate limiting

`RateLimitMiddleware` keys its in-memory sliding window by **`client_ip:path`**
(`backend/app/api/v1/middleware/rate_limit.py:40-54`), dynamically reloads max requests from `get_live_settings().rate_limit_per_minute`, no `X-RateLimit-*` headers; on limit it returns
`429` with a `Retry-After: 60` header.

---

## 5. Known issues carried forward

Classification used by `Blueprint V5`:

| ID | Issue | Severity | Kind |
|----|-------|----------|------|
| K1 | ~~WS channel authorization always denies~~ **Resolved 2026-08-08 (commit `b98da77`, `d096f75`)** — singular permission strings + `admin:full` bypass | ~~High~~ | ~~Bug~~ |
| K2 | ~~`EventDispatcher`/`MetricsBatcher` never wired~~ **Resolved 2026-08-08 (commit `db1889d`)** — `MetricsBridgeHandler` flushes samples over WS every 2s | ~~High~~ | ~~Bug~~ |
| K3 | ~~`PATCH /settings` stub~~ **Resolved 2026-08-09 (commit `2437590`, `789dcbd`)** — file-backed persistence + consumer hot-reload + frontend redesign | ~~Medium~~ | ~~Bug~~ |
| K4 | Plugin enable/disable routes use only `get_current_user` (no `require_permission`) | Medium | Bug (Phase 4) |
| K5 | ~~Marketplace is not a first-class frontend section~~ **Resolved 2026-08-06 (commit `1c12e0c`)** — own `/marketplace` route + sidebar entry + global search + install-time server picker | ~~Medium~~ | ~~Feature~~ |
| K6 | No backend CI workflow (only `frontend-ci.yml`); the permissions route-coverage matrix is not CI-enforced | High | Process (Phase 4) |
| K7 | 13 mutating routes + 21 sensitive GET routes lack permission enforcement (per `contracts/permissions.yaml`) | High | Bug (Phase 4) |
| K8 | ~~`test_start_server` + `test_metrics_task_requires_collector` fail in the suite~~ **Resolved 2026-08-08** — 100% backend pass rate (1115/1115 passed) | ~~Low~~ | ~~Test debt~~ |
| K9 | Production DB 3 revisions behind head; no servers | Medium | Ops |
| K10 | `GET /metrics` public/unauthenticated (documented deferred decision) | Medium | Security (Phase 7) |
| K11 | JWT keys auto-generated in-process (lost on restart unless PEM set) | Medium | Architecture debt (Phase 4) |
| K12 | Permissions stored as comma-separated Text; `SQLUserRepository.save()` `MissingGreenlet` risk on role assignment | Medium | Architecture debt (Phase 4) |
| K13 | `ArqQueue.get_status/get_result` stubs; schedules/alerts stubs | Low | Known limitation |
| K14 | Backup `save-all` completion regex unverified against a real Purpur server | Low | Verify |
| K15 | Repo-root `data/` directory (gitignored, unused, awaiting cleanup decision) | Low | Housekeeping |
| K16 | Provider selection config-driven via `MCS_PLUGIN_PROVIDERS`, validated at startup (K16A done 2026-08-05). Remaining: inspect configured list via API, add a second provider. | Low | Architecture debt (Phase 1) |
| — | Backend `settings.py` router hardcodes `"version": "4.0.0"` instead of reading from live settings / AppSettings | Low | Known non-blocking |
| — | ServerMetricsCharts 5s REST refetchInterval vs 60s backend collection cadence | Low | Known edge case |
| — | Non-running server writes zero metrics rows → chart renders empty state without explanatory UI message | Low | Known edge case |

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
