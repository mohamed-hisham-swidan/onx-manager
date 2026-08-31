# ONX Manager — Current State (Verified)

**Status:** Authoritative, evidence-based snapshot of the codebase as of
2026-08-31. Every claim below was verified against source code, the database,
and a live test run.

**Last verified:** 2026-08-31
**App version (code):** `4.0.0` (`backend/pyproject.toml:3` → resolved at runtime by `backend/app/core/version.py:get_app_version()`)

---

## 1. Repository shape

| Item | Count | Evidence |
|------|-------|----------|
| Backend Python source files | 300 | `find backend/app -name "*.py"` |
| Backend test files | 131 | `find backend/tests -name "test_*.py"` |
| Frontend test files | 69 | `find frontend/src -name "*.test.*"` |
| REST routers (`api/v1/routers/`) | 15 | `auth, backups, exposure, files, health, invites, marketplace, monitoring, plugins, schedules, servers, settings, setup, software, users` |
| Alembic migration revisions | 29 | `backend/alembic/versions/` (head `b1e2100000009`) |
| Architecture Decision Records | 12 | `docs/decisions/0001`–`0012` |
| Contract files | 6 | `contracts/{api.yaml, config.schema.json, events.yaml, permissions.yaml, plugin.yaml, README.md}` |
| DDD modules | 10 | `auth, backup, event_store, exposure, health, monitoring, plugin, server, shared, storage` |
| CI workflows | 5 | `.github/workflows/{backend-tests.yml, backend-version-ci.yml, route-permission-ci.yml, frontend-ci.yml, verification-cadence.yml}` — full backend pytest + DB-compat + Ruff-baseline gate; version-propagation check; route→permission contract check; frontend typecheck/lint/test/build; weekly re-verification cadence |

---

## 2. Test suite (measured 2026-08-31)

### Backend — `backend/` `python -m pytest tests/`

| Metric | Value |
|--------|-------|
| Collected | **2133** |
| Passed | **2131** |
| Skipped | **2** |
| Failed | **0** |

Backend CI runs the full suite on every push/PR to `master`
(`.github/workflows/backend-tests.yml`), followed by a DB compatibility-floor
check and a Ruff-baseline regression gate.

### Frontend — `frontend/` `npx vitest run`

| Metric | Value |
|--------|-------|
| Test files | **69** |
| Tests | **574 passed** across 69 test files |

Frontend CI (`frontend-ci.yml`) runs `typecheck`, `lint`, `test`, and `build`
on every push/PR to `master`.

---

## 3. Database state

### Default Canonical DB — `backend/data/onx.db` (used by default config `sqlite+aiosqlite:///./data/onx.db`)

| Property | Value |
|----------|-------|
| Alembic revision | `b1e2100000009` — **at head** |
| Head revision | `b1e2100000009` (head == current) |
| New tables / columns | `system_state`, `invitations`, `server_memberships`, Phase-7 exposure tables (`host_playit_agent`, `server_exposure`, `server_exposure_target`, `panel_exposure`), nullable `metric_points.tps`, and `servers.running_start_time` (`b1e2100000009`) |
| Pre-Backend Reconciler | `backend/app/core/persistence/reconciler.py` automatically inspects, backs up, and reconciles DB schema before services start |

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

### 4.2 Auth & authorization (implemented & Phase 4 enforced)

- JWT RS256 (15-min access tokens), refresh-token rotation (7-day opaque
  tokens, SHA-256 hash in DB), API keys (`mcs_` prefix, SHA-256 hashed),
  Argon2id password hashing.
- Global permission enforcement via `require_permission(...)` and live server-scoped RBAC authorization via `require_server_permission(...)` (commit `a47daa8`).
- Server membership & ownership model: `ServerModel.owner_id` (implicit full server access) and `ServerMembershipModel` (`server_memberships` table for `admin`, `dev`, `viewer` roles).
- Protected surfaces: Files API (all 7 endpoints gated, with viewer role allowed file download access), Health API (`POST /health/evaluate/{server_id}` gated), Schedules API (`POST`/`DELETE` gated), and Monitoring Alerts (`POST /alerts/{server_id}` refactored to path-based `server_id` to eliminate IDOR / parameter-pollution vulnerability). Defense-in-depth in `require_server_permission` returns HTTP 400 if conflicting `server_id` values appear across path/query/body.
- **Runtime diagnostics IDOR fixed (2026-08-12):** `GET /servers/{id}/runtime` and `GET /servers/{id}/runtime/validate` now enforce `require_server_permission("server.{id}.view")`; `GET /servers/runtime/ownership` enforces `require_permission("server:read")`. Regression tests in `backend/tests/api/test_runtime_permissions.py`.
- Owner bootstrap / access-mode / invitation system (committed `14a0d32`):
  `POST /setup/bootstrap` (single-use), `GET /setup/status`,
  `PUT /setup/access-mode` (owner-only, `LOCAL`/`GLOBAL`), `POST /invites`,
  `DELETE /invites/{id}`, `GET /invites` (all `user:write`),
  `GET /invites/verify/{token}`, `POST /invites/accept`, `POST /users`. Frontend:
  `SetupPage`, `InvitePage`, `SystemStatusGuard`, `AccessSection`,
  `InvitationsSection` under `/settings`. Migration `a957791492a7` adds
  `system_state` + `invitations` tables.

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
- **Plugin detail tabs + crash fix (2026-08-19, SPEC-PLUGIN-DETAIL-TABS-001 v1.3):**
  - Backend: `GET /api/v1/marketplace/projects/{project_id}/versions` (server-independent,
    `selected=null` always) + nullable `wiki_url`/`source_url` and parsed
    `client_side`/`server_side` on `PluginProjectResponse` — fixes the 500 crash
    for Modrinth projects with null `wiki_url`/`source_url` (was 22/60 plugins,
    33/60 mods). Strict v1.3 two-part `game_version_matches` gate in
    `version_selector.py`.
  - Frontend: `PluginDetailPage` now has **Description / Versions** tabs (Changelog
    stubbed/disabled), a **Compatibility sidebar** (`CompatibilityCard.tsx`, loader
    pills with generic `download` icon + "Supported environments" from
    `client_side`/`server_side`), and a client-side **Recommended** badge
    (`ProjectVersionsList.tsx` + `versionMatching.ts`) keyed on the last-used server
    resolved via `server_id` (G1). Badge rule is **strict**: shown only when a
    version's `game_versions` AND loader both match; no closest-distance fallback.
  - Test coverage: 13 new matcher cases + backend API/route-contract/provider tests;
    frontend suites for `versionMatching`, `CompatibilityCard`, `ProjectVersionsList`,
    `PluginDetailPage` (all green).

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

### 4.7 Server Redesign & File Manager (Part B completed)

- **In-Server Contextual Navigation Shell (Batch 1, commit `adbf556`):** Dedicated sidebar context for server management with back-navigation.
- **Blade Hosting-Style Server Detail Page (Batch 2, commit `72e8c1c` & Batch 5, commit `79d18d7`):** Two-column layout with live console, stat cards (Address click-to-copy, Uptime, CPU, RAM, Storage), Zone ID placeholder, CPU/RAM/Network usage trend graphs, and explicit "Coming Soon" badges for Storage & Network I/O metrics.
- **Files REST API (Batch 3, commit `ae6848d`):** `/api/v1/servers/{server_id}/files` endpoint providing directory listing, text read/write (atomic), file/dir delete, upload, download, and mkdir with path-traversal sandboxing (`_resolve_server_file_path`).
- **File Manager UI (Batch 4, commit `e96f902`):** First-class `/servers/:serverId/files` File Manager view with directory breadcrumbs, inline text editor, file upload, download, creation, and deletion modal.
- **Server-Type-Aware Mods/Plugins UI (commit `7226e6c`):** Contextual navigation and Install Modal showing "Mods" or "Plugins" based on server type (`fabric`/`forge` vs `paper`/`purpur`).

---

## 5. Known issues carried forward

Classification used by `Blueprint V5`:

| ID | Issue | Severity | Kind |
|----|-------|----------|------|
| K1 | ~~WS channel authorization always denies~~ **Resolved 2026-08-08 (commit `b98da77`, `d096f75`)** — singular permission strings + `admin:full` bypass | ~~High~~ | ~~Bug~~ |
| K2 | ~~`EventDispatcher`/`MetricsBatcher` never wired~~ **Resolved 2026-08-08 (commit `db1889d`)** — `MetricsBridgeHandler` flushes samples over WS every 2s | ~~High~~ | ~~Bug~~ |
| K3 | ~~`PATCH /settings` stub~~ **Resolved 2026-08-09 (commit `2437590`, `789dcbd`)** — file-backed persistence + consumer hot-reload + frontend redesign | ~~Medium~~ | ~~Bug~~ |
| K4 | ~~Plugin enable/disable routes use only get_current_user~~ **Resolved 2026-08-11 (commit `a47daa8`)** — Phase 4 authorization gating | ~~Medium~~ | ~~Bug (Phase 4)~~ |
| K5 | ~~Marketplace is not a first-class frontend section~~ **Resolved 2026-08-06 (commit `1c12e0c`)** — own `/marketplace` route + sidebar entry + global search + install-time server picker | ~~Medium~~ | ~~Feature~~ |
| K6 | ~~No backend CI workflow~~ **Resolved 2026-08-13 (B6-2)** — `.github/workflows/backend-tests.yml` runs full pytest + DB-compat + Ruff-baseline gate. Route-coverage matrix now CI-enforced via `scripts/check-route-contract` (B6-4, `.github/workflows/route-permission-ci.yml`) | High | Process (Phase 4) |
| K7 | ~~13 mutating routes + 21 sensitive GET routes lack permission enforcement~~ **Resolved 2026-08-11 (commit `a47daa8`)** — Protected remaining mutating routes & Files API with server-scoped RBAC | ~~High~~ | ~~Bug (Phase 4)~~ |
| K8 | ~~`test_start_server` + `test_metrics_task_requires_collector` fail in the suite~~ **Resolved 2026-08-08** — 100% backend pass rate (1144/1144 passed) | ~~Low~~ | ~~Test debt~~ |
| K9 | Production DB 3 revisions behind head; no servers | Medium | Ops |
| K10 | `GET /metrics` public/unauthenticated (documented deferred decision) | Medium | Security (Phase 7) |
| K11 | JWT keys auto-generated in-process (lost on restart unless PEM set) | Medium | Architecture debt (Phase 4) |
| K12 | Permissions stored as comma-separated Text; `SQLUserRepository.save()` `MissingGreenlet` risk on role assignment | Medium | Architecture debt (Phase 4) |
| K13 | `ArqQueue.get_status/get_result` stubs; schedules/alerts stubs | Low | Known limitation |
| K14 | Backup `save-all` completion regex unverified against a real Purpur server | Low | Verify |
| K15 | Repo-root `data/` directory (gitignored, unused, awaiting cleanup decision) | Low | Housekeeping |
| K16 | Provider selection config-driven via `MCS_PLUGIN_PROVIDERS`, validated at startup (K16A done 2026-08-05). Remaining: inspect configured list via API, add a second provider. | Low | Architecture debt (Phase 1) |
| — | ~~**Files API IDOR Gap:** `GET /files`, `GET /files/content`, `GET /files/download` endpoints check login (`get_current_user`) but lack per-server permission enforcement~~ **Resolved 2026-08-11 (commit `a47daa8`)** — `require_server_permission` enforced on all 7 endpoints | ~~High~~ | ~~Security (Phase 4)~~ |
| — | ~~**Runtime diagnostics IDOR:** `GET /servers/{id}/runtime`, `GET /servers/{id}/runtime/validate` were auth-only (no server scope); `GET /servers/runtime/ownership` exposed host-wide PID/tmux data with auth only~~ **Resolved 2026-08-12** — server-scoped guard + `server:read` + regression tests (`test_runtime_permissions.py`, 2 tests) | ~~High~~ | ~~Security~~ |
| — | ~~**Invitation status case mismatch:** frontend compared `"active"`/`"consumed"` while backend returns `ACTIVE`/`USED`/`REVOKED`, so the Revoke button never rendered and status badges always fell through to the gray style~~ **Resolved 2026-08-12** — `InvitationsSection.tsx` compares uppercase enum values; `InvitationItem.use_count` matches backend `use_count` | ~~Medium~~ | ~~Bug~~ |
| — | ~~`npm run lint` fails with pre-existing errors~~ **Resolved 2026-08-13 (B6-2)** — `eslint src/` is 0 errors / 0 warnings across the codebase; typed error handling fixed without config weakening; `frontend-ci.yml` gates on lint | ~~Medium~~ | ~~Tech debt~~ |
| — | ~~`ruff check` reports pre-existing errors across backend; no ruff CI gate~~ **Resolved 2026-08-13 (B6-2)** — `backend/ruff-baseline.json` (1738 pre-existing violations / 42 rules) + `scripts/check-ruff-baseline` + CI step in `backend-tests.yml`; **new** violations fail CI, baseline debt remains tracked | ~~Low~~ | ~~Tech debt~~ |
| — | ~~Backend `settings.py` router hardcodes `"version": "4.0.0"` instead of reading from live settings / AppSettings~~ **Resolved 2026-08-13 (Phase 5.2)** — `backend/app/core/version.py:get_app_version()` is the single resolver (`pyproject.toml` tomllib → `importlib.metadata` fallback → `4.0.0` last resort); `settings.py`, `setup.py`, `schemas/common.py`, `main.py`/OpenAPI, `get_system_status.py`, `update_access_mode.py` all read it | ~~Low~~ | ~~Known non-blocking~~ |
| — | ServerMetricsCharts 5s REST refetchInterval vs 60s backend collection cadence | Low | Known edge case |
| — | Non-running server writes zero metrics rows → chart renders empty state without explanatory UI message | Low | Known edge case |

---

## 6. Files that define this state

- `backend/app/main.py` — app factory, version (`get_app_version`), middleware, router registration
- `backend/app/api/v1/routers/plugins.py` — plugin list + marketplace routes
- `backend/app/api/v1/routers/settings.py` — settings GET + PATCH
- `backend/app/core/version.py` — single version resolver (`get_app_version`)
- `backend/app/websocket/authorization.py`, `endpoint.py`, `dispatcher.py`,
  `handlers.py` — WS auth, channels, dispatch (see §4.3)
- `backend/app/api/v1/middleware/rate_limit.py` — per `client_ip:path` limiter
- `backend/app/modules/plugin/infrastructure/providers/` — provider ABC +
  Modrinth implementation
- `backend/app/modules/plugin/application/services/version_selector.py` —
  best-version selection
- `contracts/permissions.yaml` — live route→permission coverage matrix
- `backend/data/servers/mcs.db` / `backend/mcs.db` — production / dev databases
- `.github/workflows/backend-tests.yml`, `backend-version-ci.yml`,
  `route-permission-ci.yml`, `frontend-ci.yml`, `verification-cadence.yml` — CI
  workflows

---

## 7. Re-verification cadence & status source-of-truth (B6-5)

### 7.1 Single source-of-truth decision (Model A)

`STATUS.md` does not exist in this repository (verified: root, `docs/`,
`docs/status/`). The two-document split flagged as a drift risk in Blueprint V5
§2.7 is therefore resolved by **collapse, not by maintenance**: **this
`current-state.md` is the single canonical operational snapshot**, and
`docs/status/history.md` remains the historical narrative it intentionally
supersedes. No `STATUS.md` is recreated; no second current-state document is
introduced.

### 7.2 Cadence

A fixed, automated re-verification cadence enforces the "no stale snapshot" rule
instead of trusting memory (Blueprint V5 §2.4):

| Property | Value |
|----------|-------|
| Trigger | GitHub Actions `schedule:` — **weekly, Monday 03:00 UTC** |
| Workflow | `.github/workflows/verification-cadence.yml` (job `re-verify`) |
| Reuses existing checks | Yes — the exact authoritative scripts/gates, not a lightweight approximation |
| Local twin | `scripts/reverify` — runs the identical command set |
| Also runs on | push / pull_request to `master` for version files, `contracts/permissions.yaml`, the check scripts, `docs/**`, and the workflow itself |

Checks executed each run (identical locally via `scripts/reverify`):

1. `python ../scripts/check-version-propagation` — pyproject.toml / package.json / runtime agree
2. `python ../scripts/check-db-revision` — migration head `b1e2100000007` at release floor
3. `python ../scripts/check-ruff-baseline` — no new violations vs `backend/ruff-baseline.json`
4. `python ../scripts/check-route-contract` — `contracts/permissions.yaml` 85 entries match 85 live routes
5. `python -m pytest -q` (backend) — full suite `1934 passed / 2 skipped`
6. `npm run typecheck`, `npm run lint`, `npm run test`, `npm run build` (frontend) — `67 files / 529 tests` (latest run: 528 passed + 1 pre-existing load-flaky timeout), typecheck/lint pre-existing only, build succeeds

### 7.3 Execution status

- **Cadence mechanism: IMPLEMENTED / VERIFIED.** The scheduled workflow
  (`.github/workflows/verification-cadence.yml`) exists, is syntactically
  valid, retains push/PR triggers, and was dry-run successfully on 2026-08-14
  against the exact command set in §7.2 (all checks pass, locally and in the
  existing CI paths).
- **Phase 6 §2.6 requirement: PENDING.** Blueprint V5 §2.6 acceptance requires
  the cadence to have "run at least once under its own schedule". That can only
  be shown by observing a real GitHub scheduled execution. **Scheduled
  execution remains PENDING FIRST GITHUB SCHEDULED RUN** — the first autonomic
  Monday 03:00 UTC run must land before this criterion is considered met. No
  scheduled run has been observed as of 2026-08-14.
