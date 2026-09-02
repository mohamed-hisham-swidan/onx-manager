# REST API Reference

**Base URL:** `http://<host>:8000/api/v1`
**Content-Type:** `application/json` (responses and mutating requests)
**Auth:** `Authorization: Bearer <jwt>` or `Authorization: Bearer <api_key>` — see [Authentication](#authentication)

> Cross-references: [Architecture](architecture/ARCHITECTURE.md), [Security](architecture/SECURITY.md), [Frontend](architecture/FRONTEND.md)
>
> This document is generated from the router code (`backend/app/api/v1/routers/`).
> Every endpoint below was verified directly against its router function (the
> 15 routers: `auth, backups, exposure, files, health, invites, marketplace,
> monitoring, plugins, schedules, servers, settings, setup, software, users`).

---

## Table of Contents

1. [Authentication](#authentication)
2. [Status codes](#status-codes)
3. [Error format](#error-format)
4. [Rate limiting](#rate-limiting)
5. [Conventions](#conventions)
6. [Auth endpoints](#auth-endpoints)
7. [Servers](#servers)
8. [Backups](#backups)
9. [Plugins](#plugins)
10. [Users](#users)
11. [Health](#health)
12. [Monitoring](#monitoring)
13. [Schedules](#schedules)
14. [Settings](#settings)
15. [Software](#software)
16. [Files](#files)
17. [Setup & access mode](#setup--access-mode)
18. [Invites](#invites)
19. [App-level endpoints](#app-level-endpoints)
20. [WebSocket protocol](#websocket-protocol)
21. [Exposure](#exposure)

---

## Authentication

Two authentication mechanisms are accepted, both via the same `Authorization` header:

```
Authorization: Bearer <jwt>
Authorization: Bearer <api_key>
```

**JWTs** are RS256-signed (`alg: RS256`, `kid` header). The access token is
short-lived (15 minutes, `exp` in payload); claims include `sub`, `roles`,
`permissions`, and `scope`. Public keys are published at
`GET /.well-known/jwks.json`. The RSA keypair is auto-generated in-process on
first run unless `MCS_JWT_PRIVATE_KEY` / `MCS_JWT_PRIVATE_KEY_PATH` are set
(see [Environment Variables](architecture/ARCHITECTURE.md#environment-variables-production)).

**API keys** are long-lived credentials beginning with `mcs_`. A token that
starts with `mcs_` is resolved against the stored (hashed) API keys table
instead of being verified as a JWT. API keys carry their own `permissions`
list. They are created via the [auth endpoints](#auth-endpoints) and their
plaintext value is returned **only at creation time**.

### Scope of authentication

Authentication is enforced globally by an `AuthMiddleware` (plus the
`get_current_user` dependency on every router). The following routes are
**public** (no token required):

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `GET /api/v1/setup/status` (instance initialization state — used by the setup wizard / `SystemStatusGuard`)
- `POST /api/v1/setup/bootstrap` (single-use, first-run Owner creation)
- `GET /api/v1/invites/verify/{token}` (pre-registration token validity, no user data returned)
- `POST /api/v1/invites/accept` (invite-token-based registration)
- `GET /health`, `/metrics`, `/docs`, `/redoc`, `/openapi.json`, `/.well-known/jwks.json`

`POST /api/v1/users` is **not** unconditionally public: it is rejected
(`403`) while the instance is uninitialized and while access mode is
`GLOBAL` (where registration must go through `POST /api/v1/invites/accept`).
See [Users](#users) and [Setup & access mode](#setup--access-mode).

Every other route requires a valid Bearer token.

### Authorization model (verified 2026-08-19)

Authorization is enforced at the route dependency layer in two forms:

1. **Global permissions** — `require_permission(...)` checks the caller's
   token `permissions` claim (with an `admin:full` bypass). Used for
   instance-wide operations: `server:create`, `server:write`, `server:delete`,
   `server:read` (host-wide runtime snapshot), `backup:*`, `plugin:manage`,
   `user:*`, `settings:*`, `global.settings`.
2. **Server-scoped RBAC** — `require_server_permission(...)` reads the
   `server_id` from path/query/body (rejecting conflicting values with `400`),
   verifies the server exists (`404`), and grants access to the server's
   **owner** (via `ServerModel.owner_id`), a **member** whose
   `ServerMembershipModel` role includes the required node, or any caller with
   a global claim (`admin:full`, `global.*`, `global.servers.manage`). Operates
   on dynamic permission nodes such as `server.{id}.view`, `server.{id}.power`,
   `server.{id}.console`, `server.{id}.files`, `server.{id}.settings`.

> The pre-Phase-4 state described in older revisions of this document — most
> routes auth-only, Files API reads/downloads with an open **IDOR gap**, plugin
> enable/disable ungated — is **resolved**. All 7 Files routes are gated on
> `server.{id}.files` (download additionally allows `server.{id}.view`), plugin
> enable/disable gate on `plugin:manage`, settings/schedules/alerts/health
> routes gate on their permissions, and the runtime diagnostics routes gate on
> `server.{id}.view` / `server:read`. The complete route→permission matrix is
> the source of truth in `../contracts/permissions.yaml`.
>
> The full list of enforced routes is maintained in
> [`../contracts/permissions.yaml`](../contracts/permissions.yaml) (v1.5, 85
> effective routes), not duplicated inline here.

### 401 vs 403

| Status | Meaning in this codebase |
|---|---|
| `401 AUTHENTICATION_ERROR` | Missing, malformed, expired, or invalid Bearer token; revoked/expired API key; deactivated account. No request reaches the route. |
| `403 PERMISSION_DENIED` | Caller authenticated but lacks the required permission. Produced by the `require_permission` / `require_server_permission` / `require_owner` dependencies and by access-mode registration blocks. |

---

## Status codes

| Status | Used for |
|---|---|
| `200` | Successful reads and non-creating writes |
| `201` | Resource created (`POST` list endpoints) |
| `204` | Deleted / void (no body) |
| `400` | Bad request (e.g. `POST /servers/scan` on a non-directory) |
| `401` | Authentication failure (see above) |
| `403` | Permission denied — raised by `require_permission` / `require_server_permission` / `require_owner` on all gated endpoints (see the authorization section under Authentication), and by the access-mode registration blocks |
| `404` | Resource not found (e.g. unknown software type) |
| `409` | Conflict (raised from command handlers) |
| `415` | Mutating request without `Content-Type: application/json` |
| `422` | Validation error |
| `429` | Rate limit exceeded |
| `500` / `503` | Internal / infrastructure error |

---

## Error format

All errors (except middleware-level 401/415/429 and the 422 FastAPI
validation handler) are returned by `backend/app/api/errors.py` in the
following shape:

```json
{
  "error": "Server with id 'abc' not found",
  "error_code": "NOT_FOUND",
  "detail": null,
  "timestamp": "2026-08-01T12:34:56.789012+00:00"
}
```

| Field | Type | Description |
|---|---|---|
| `error` | `string` | Human-readable message |
| `error_code` | `string` | Machine-readable code (`SCREAMING_SNAKE_CASE`) |
| `detail` | `object\|null` | Optional structured context |
| `timestamp` | `string` | UTC ISO-8601 timestamp |

Middleware-level responses are abbreviated and omit `timestamp`:

- `401` (middleware): `{"error": "...", "error_code": "AUTHENTICATION_ERROR"}`
- `415`: `{"error": "Content-Type must be application/json", "error_code": "VALIDATION_ERROR"}`
- `429` (middleware): `{"error": "Rate limit exceeded", "error_code": "RATE_LIMIT_EXCEEDED", "detail": {"retry_after": 60}}` + `Retry-After` header

Pydantic request-validation failures return FastAPI's default `422` shape
(`{"detail": [...]}`).

### Error codes → HTTP status mapping

| `error_code` | HTTP |
|---|---|
| `NOT_FOUND` | 404 |
| `CONFLICT` | 409 |
| `VALIDATION_ERROR` | 422 |
| `AUTHENTICATION_ERROR` | 401 |
| `PERMISSION_DENIED` | 403 |
| `RATE_LIMIT_EXCEEDED` | 429 |
| `INFRASTRUCTURE_ERROR` | 503 |
| `INTERNAL_ERROR`, `UNEXPECTED_ERROR`, `HANDLER_NOT_FOUND` | 500 |
| anything else | 400 |

The `PERMISSION_DENIED` entry above is wired to a handler in
`backend/app/api/errors.py` and is produced by the `require_permission`,
`require_server_permission`, and `require_owner` dependencies on the enforced
routes described in the [authorization model](#authorization-model-verified-2026-08-12)
under Authentication.

Domain error codes produced by command handlers (e.g. `SERVER_NOT_RUNNING`,
`SERVER_NOT_FOUND`, `BACKUP_IN_PROGRESS`, `INVALID_CREDENTIALS`) are returned
in the `error_code` field with the HTTP status from the table above.

---

## Rate limiting

A `RateLimitMiddleware` allows **60 requests per minute per
`client_ip:path`** pair (not per user). The limit is not configurable per
route. On exceeding the limit the middleware returns `429` with a
`Retry-After: 60` header. No `X-RateLimit-*` headers are emitted.

WebSocket message rate limiting is separate (see [WebSocket protocol](#websocket-protocol)).

---

## Conventions

- **No response envelope.** Endpoints return the raw object, array, or dict —
  there is no `data`/`pagination` wrapper.
- **No pagination.** List endpoints are not paginated; some accept filter or
  `limit` query parameters (documented per endpoint).
- **Resource IDs** are UUID-style strings generated server-side; clients
  reference them via path parameters.
- **Timestamps** are ISO-8601.
- Mutating commands return the command handler's result dict via
  `check_command_result()` — on failure the handler error is raised as an
  HTTP error with the mapped status. A successful mutating response is
  typically `{"success": true, ...}` plus command-specific fields.

---

## Auth endpoints

All routes under `POST /api/v1/auth/*` except `login`/`refresh` require a Bearer token.

| Method | Path | Auth | Request body | Response | Notes |
|---|---|---|---|---|---|
| `POST` | `/api/v1/auth/login` | Public | `LoginRequest` | `200 LoginResponse` | Email + password → token pair |
| `POST` | `/api/v1/auth/refresh` | Public | `RefreshTokenRequest` | `200 LoginResponse` | Refresh token → new pair |
| `POST` | `/api/v1/auth/logout` | Bearer | `LogoutRequest` (optional) | `200 dict` | Revokes refresh token |
| `GET` | `/api/v1/auth/me` | Bearer | — | `200 dict` | Current user info; `404` if not found |
| `GET` | `/api/v1/auth/api-keys` | Bearer (auth-only) | — | `200 list[ApiKeyResponse]` | Active keys for the current user (`key` is `null`); auth-only — part of the documented residual auth-only reads (see Security architecture) |
| `POST` | `/api/v1/auth/api-keys` | `user:write` | `ApiKeyCreateRequest` | `201 ApiKeyResponse` | **Plaintext `key` returned only here** |
| `DELETE` | `/api/v1/auth/api-keys/{api_key_id}` | `user:write` | — | `204` | Revokes an API key |

### Request / response schemas

`LoginRequest`: `email` (valid email), `password` (min 1 char).

`LoginResponse`:
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 900
}
```

`RefreshTokenRequest`: `refresh_token` (string).

`LogoutRequest`: `refresh_token` (string, default `""`).

`ApiKeyCreateRequest`: `name` (required, min 1), `permissions` (list of
permission strings, default `[]`).

`ApiKeyResponse`:
```json
{
  "api_key_id": "uuid",
  "name": "CI/CD Pipeline",
  "prefix": "mcs_xxxx",
  "key": null,
  "permissions": ["server:read", "backup:read"],
  "expires_at": null,
  "is_revoked": false,
  "created_at": "2026-08-01T12:00:00"
}
```

---

## Servers

Prefix `/api/v1/servers`. All routes require a Bearer token. Routes touching a
specific server enforce server-scoped RBAC via `require_server_permission(...)`
(owner / member-with-role / global claim); these operate on the dynamic
`server.{id}.*` permission nodes.

| Method | Path | Auth | Request body | Query params | Response | Notes |
|---|---|---|---|---|---|---|
| `GET` | `/api/v1/servers/available-port` | Bearer | — | — | `200 dict` | Returns `{"port": <int>}` — first free port ≥ 25565 |
| `GET` | `/api/v1/servers` | Bearer | — | `status`, `group_id`, `name_search`, `minecraft_version` | `200 list[ServerResponse]` | Filterable list; no pagination |
| `POST` | `/api/v1/servers` | `server:create` | `ServerCreateRequest` | — | `201 dict` | Creates a server; the creator becomes `owner_id` |
| `POST` | `/api/v1/servers/scan` | `server:write` | `ScanDirectoryRequest` | — | `200 ScanResult` | Scans a directory for an existing server; `400`/`403` on bad path/permission |
| `POST` | `/api/v1/servers/import` | `server:write` | `ImportServerRequest` | — | `201 dict` | Imports an existing server dir |
| `GET` | `/api/v1/servers/{server_id}` | Bearer | — | — | `200 ServerDetailResponse` | Full server detail (auth-only; no permission node) |
| `PATCH` | `/api/v1/servers/{server_id}` | `server:write` | `ServerUpdateRequest` | — | `200 dict` | Update properties/memory |
| `DELETE` | `/api/v1/servers/{server_id}` | `server:delete` | — | — | `204` | Delete server |
| `POST` | `/api/v1/servers/{server_id}/start` | `server.{id}.power` | — | — | `200 dict` | Start the server |
| `POST` | `/api/v1/servers/{server_id}/stop` | `server.{id}.power` | `ServerActionRequest` | — | `200 dict` | Stop; body `reason` (default `""`) |
| `POST` | `/api/v1/servers/{server_id}/restart` | `server.{id}.power` | — | — | `200 dict` | Restart |
| `GET` | `/api/v1/servers/{server_id}/console` | `server.{id}.view` | — | `tail` (default `100`, 1–10000) | `200 ConsoleResponse` | Recent console lines |
| `POST` | `/api/v1/servers/{server_id}/command` | `server.{id}.console` | `CommandRequest` | — | `200 dict` | Sends a console command (`SERVER_NOT_RUNNING` if not running) |
| `GET` | `/api/v1/servers/{server_id}/runtime` | `server.{id}.view` | — | — | `200 RuntimeDiagnosticsResponse` | Live runtime diagnostics |
| `GET` | `/api/v1/servers/runtime/ownership` | `server:read` (global) | — | — | `200 RuntimeOwnershipResponse` | Orphan/conflict snapshot (host-wide PID/tmux data) |
| `POST` | `/api/v1/servers/runtime/ownership/claim` | `server:write` | — | `server_id` (query) | `200 ClaimLocalhostResponse` | Claim localhost ownership for a server |
| `GET` | `/api/v1/servers/{server_id}/runtime/validate` | `server.{id}.view` | — | — | `200 ValidationChainResponse` | Runs the ownership validation chain |
| `POST` | `/api/v1/servers/reconcile` | `server:write` | `ReconcileRequest` (optional body) | — | `200 dict` | Runtime reconciliation + orphan cleanup; `scope` defaults `project_owned` |
| `POST` | `/api/v1/servers/refresh` | `server:write` | — | `dry_run` (bool, default `false`) | `200 ReconciliationResultResponse` | Filesystem reconciliation (DB ↔ disk) |

> Note: static routes (`/available-port`, `/runtime/ownership`,
> `/reconcile`, `/refresh`) and parameterized routes (`/{server_id}`) coexist
> under the same prefix; FastAPI matches by segment count, so
> `/api/v1/servers/runtime/ownership` never collides with
> `/api/v1/servers/{server_id}`.

### Request schemas

`ServerCreateRequest` (all defaults shown):

| Field | Type | Default | Constraints |
|---|---|---|---|
| `name` | string | — | required, 1–128 chars |
| `server_type` | string | `"vanilla"` | |
| `minecraft_version` | string | `"1.20.4"` | regex `^\d+\.\d+(\.\d+)?$` |
| `min_memory_mb` | int | `1024` | ≥ 128 |
| `max_memory_mb` | int | `2048` | ≥ 128 |
| `port` | int | `25565` | 1–65535 |
| `motd` | string | `"A Minecraft Server"` | |
| `max_players` | int | `20` | 1–500 |
| `gamemode` | string | `"survival"` | |
| `difficulty` | string | `"easy"` | |
| `spawn_protection` | int | `16` | ≥ 0 |
| `pvp` | bool | `true` | |
| `enable_command_block` | bool | `false` | |
| `online_mode` | bool | `true` | |
| `whitelist` | bool | `false` | |
| `view_distance` | int | `10` | 2–32 |
| `simulation_distance` | int | `10` | 2–32 |
| `java_args` | list[string] | `null` | |
| `group_id` | string | `"default"` | |
| `install_dir` | string | `null` | |

`ServerUpdateRequest`: `properties` (dict, default `{}`), `min_memory_mb`
(int\|null), `max_memory_mb` (int\|null).

`ServerActionRequest`: `reason` (string, default `""`).

`CommandRequest`: `command` (string, required, min 1).

`ReconcileRequest`: `scope` (string, default `"project_owned"`, one of
`project_owned`\|`system_wide`). `project_owned` only kills processes verified
owned; `system_wide` is the legacy heuristic behavior.

`ScanDirectoryRequest`: `path` (string, required, 1–4096 chars).

`ImportServerRequest`: same field set as `ServerCreateRequest` plus
`source_path` (required, 1–4096 chars).

### Response schemas

`ServerResponse`:
```json
{
  "server_id": "uuid",
  "name": "Survival World",
  "server_type": "vanilla",
  "minecraft_version": "1.20.4",
  "status": "stopped",
  "group_id": "default",
  "port": 25565,
  "motd": "A Minecraft Server",
  "max_players": 20,
  "gamemode": "survival",
  "difficulty": "easy",
  "created_at": "2026-08-01T12:00:00",
  "updated_at": "2026-08-01T12:00:00"
}
```

`ServerDetailResponse` = `ServerResponse` + `min_memory_mb`, `max_memory_mb`,
`java_args` (string), `spawn_protection`, `pvp`, `enable_command_block`,
`online_mode`, `whitelist`, `view_distance`, `simulation_distance`, and the
nullable deployment fields `provider`, `deployment_host`, `deployment_port`,
`deployment_pid`, `location_type`, `location_uri`, `root_path`,
`working_directory`, `startup_jar`, `startup_command`, `primary_world`.

`ConsoleResponse`: `{"server_id": "uuid", "lines": ["...", "..."]}`.

`RuntimeDiagnosticsResponse` (subset — all nullable except core fields):
`server_id`, `server_name`, `status`, `alive`, `pid`, `provider`,
`uptime_seconds`, `heartbeat_age_seconds`, `startup_duration_seconds`,
`restart_count`, `failure_code`, `failure_reason`, `last_logs`,
`last_exception`, `last_verification_timestamp`, `supervised`,
`runtime_handle`, `provider_status`, `last_crash_time`, `port`, `port_owner`,
`tmux_session`, `jvm_command`, `owner_conflicts`, `validation_chain`.

`RuntimeOwnershipResponse`: `timestamp`, `active_servers`, `orphan_tmux`,
`orphan_processes`, `stale_db_records`, `conflicts` (each with `reason`,
`detail`, `auto_resolvable`), `localhost_owner`, `total_orphans`.

`ClaimLocalhostResponse`: `success` (bool), `actions` (list[string]),
`conflicts_resolved` (int).

`ValidationChainResponse`: `server_id`, `healthy` (bool), `chain` (list[string]).

`ReconciliationResultResponse`: `imported`, `updated`, `deleted`, `missing`,
`broken`, `unchanged`, `ignored`, `invalid_identity`, `errors`,
`identity_written` (lists of dicts) plus `total_*` counters,
`total_dirs_found`, `total_minecraft_dirs`, `started_at`, `finished_at`,
`duration_ms`, `dry_run`.

---

## Backups

Prefix `/api/v1/backups`. All routes require a Bearer token.

| Method | Path | Auth | Request body | Query params | Response | Notes |
|---|---|---|---|---|---|---|
| `GET` | `/api/v1/backups` | Bearer | — | `server_id` (optional filter) | `200 list[BackupResponse]` | |
| `POST` | `/api/v1/backups` | `backup:create` | `CreateBackupRequest` | — | `201 dict` | Starts a backup job |
| `GET` | `/api/v1/backups/{backup_id}` | Bearer | — | — | `200 BackupResponse` | |
| `DELETE` | `/api/v1/backups/{backup_id}` | `backup:delete` | — | — | `204` | |
| `POST` | `/api/v1/backups/{backup_id}/restore` | `backup:restore` | — | — | `200 dict` | Restore from backup (`202` when deferred) |
| `POST` | `/api/v1/backups/{backup_id}/verify` | `backup:read` | — | — | `200 VerifyBackupResponse` | Checksum/size verification |

### Schemas

`CreateBackupRequest`: `server_id` (string, required), `backup_type`
(enum `full`\|`world`\|`plugins`, default `"full"`).

`BackupResponse`:
```json
{
  "backup_id": "uuid",
  "server_id": "uuid",
  "backup_type": "full",
  "status": "completed",
  "size_bytes": 524288000,
  "checksum": "sha256:...",
  "error_message": "",
  "created_at": "2026-08-01T12:00:00",
  "completed_at": null
}
```

`VerifyBackupResponse`: `backup_id`, `valid` (bool), `checksum_valid` (bool),
`size_valid` (bool).

---

## Plugins

Prefix `/api/v1/servers/{server_id}/plugins`. All routes require a Bearer token.

| Method | Path | Auth | Request body | Response | Notes |
|---|---|---|---|---|---|
| `GET` | `/api/v1/servers/{server_id}/plugins` | Bearer | — | `200 list[PluginResponse]` | **Triggers filesystem reconciliation first** — on-disk `.jar` files become `detected` rows, deleted files are pruned (auth-only) |
| `GET` | `/api/v1/servers/{server_id}/plugins/marketplace/search` | `plugin:manage` | — | `200 PluginSearchResultsResponse` | Modrinth catalog search (`query`, `limit`, `offset` query params) — paginated envelope `{items, total_hits, offset, limit}` (Batch 1, SPEC-PLUGIN-PAGINATION-V3) |
| `GET` | `/api/v1/servers/{server_id}/plugins/marketplace/projects/{project_id}/versions` | `plugin:manage` | `limit`, `offset` | `200 PluginVersionsResponse` | Versions + best-version selection for the server (with `selected`, `notice`, `notice_kind`); optional `limit`/`offset` slicing, `total` = full count (Batch 1, SPEC-PLUGIN-PAGINATION-V3) |
| `POST` | `/api/v1/servers/{server_id}/plugins/marketplace/install` | `plugin:manage` | `InstallModrinthPluginRequest` | `201 InstallModrinthPluginResponse` | Downloads the `.jar` (SHA-1/SHA-512 verified) into the server's `plugins/` folder |
| `GET` | `/api/v1/servers/{server_id}/plugins/{plugin_id}` | Bearer | — | `200 PluginResponse` | Auth-only |
| `DELETE` | `/api/v1/servers/{server_id}/plugins/{plugin_id}` | `plugin:manage` | — | `204` | Uninstall — sets `pending_deletion`; file removed on next server start/restart |
| `POST` | `/api/v1/servers/{server_id}/plugins/{plugin_id}/enable` | `plugin:manage` | — | `200 dict` | K4 resolved in Phase 4 (`a47daa8`) — now gated |
| `POST` | `/api/v1/servers/{server_id}/plugins/{plugin_id}/disable` | `plugin:manage` | — | `200 dict` | K4 resolved in Phase 4 (`a47daa8`) — now gated |

> **Note:** plugin lifecycle and marketplace routes (enable/disable/uninstall/
> marketplace) gate on `plugin:manage` (K4 resolved in Phase 4, commit
> `a47daa8`). The list/get routes remain **auth-only** (`get_current_user`).
> See `docs/architecture/plugins-and-marketplace.md`.

### Schemas

`InstallModrinthPluginRequest`: `server_id`, `project_id` (required),
`version_id` (optional), `minecraft_version` (optional).

`InstallModrinthPluginResponse`: `plugin_id`, `version`, `filename`, `source`,
`notice`, `notice_kind`.

`PluginSearchResultResponse`: `project_id`, `slug`, `title`, `description`,
`author`, `project_types`, `downloads`, `follows`, `icon_url`,
`latest_version_id`.

`PluginVersionsResponse`: `project_id`, `versions` (list of `PluginVersionResponse`),
`selected` (nullable `PluginVersionResponse`), `notice`, `notice_kind`.

`PluginVersionResponse`: `version_id`, `project_id`, `name`, `version_number`,
`game_versions`, `loaders`, `files` (list of `PluginFileResponse`),
`dependencies`, `date_published`.

`PluginFileResponse`: `url`, `filename`, `size_bytes`, `sha1`, `sha512`,
`primary`.

`PluginResponse`:
```json
{
  "plugin_id": "uuid",
  "server_id": "uuid",
  "name": "EssentialsX",
  "version": "1.0.0",
  "description": "",
  "author": "",
  "status": "installed",
  "source": "modrinth",
  "filename": "essentialsx.jar",
  "dependencies": [],
  "installed_at": "2026-08-01T12:00:00",
  "updated_at": "2026-08-01T12:00:00"
}
```

---

## Marketplace (server-independent)

Prefix `/api/v1/marketplace`. Global catalog routes — no `server_id` context.
All routes require a Bearer token and gate on `plugin:manage`.

| Method | Path | Auth | Request body | Response | Notes |
|---|---|---|---|---|---|
| `GET` | `/api/v1/marketplace/search` | `plugin:manage` | — | `200 PluginSearchResultsResponse` | Modrinth catalog search (`query`, `limit`, `offset`, `project_type` query params). Paginated envelope `{items, total_hits, offset, limit}` (Batch 1, SPEC-PLUGIN-PAGINATION-V3). Global search distinct from the server-scoped one (K5, `useMarketplaceSearchGlobal`). |
| `GET` | `/api/v1/marketplace/projects/{project_id}` | `plugin:manage` | — | `200 PluginProjectResponse` | Full project detail (`description`, `body` Markdown, `game_versions`, `loaders`, `client_side`, `server_side`, nullable `wiki_url`/`source_url`). Null-`wiki_url`/`source_url` no longer 500s (SPEC-PLUGIN-DETAIL-TABS-001). |
| `GET` | `/api/v1/marketplace/projects/{project_id}/versions` | `plugin:manage` | `limit`, `offset` | `200 PluginVersionsResponse` | All versions for a project, raw and unsorted, **`selected` always `null`** (no server context, D1/D6). Accepts optional `limit` (default 20, max 50) / `offset` (default 0); `total` = full version count (Decision 6 fetch-all-then-slice). Recommended is computed client-side from the last-used server. Batch 1, SPEC-PLUGIN-PAGINATION-V3. |

> **Note:** the server-scoped marketplace routes (search/versions/install under
> `/api/v1/servers/{server_id}/plugins/marketplace/...`) remain available and
> keep their best-version selection (`selected`, `notice`, `notice_kind`).
> The server-independent `/api/v1/marketplace/...` routes intentionally return
> `selected=null` and empty `notice`/`notice_kind`.

### Schemas

`PluginProjectResponse`: `project_id`, `slug`, `title`, `description`, `body`,
`author`, `project_types`, `downloads`, `follows`, `icon_url`,
`latest_version_id`, `game_versions`, `loaders`, `client_side` (nullable),
`server_side` (nullable), `wiki_url` (nullable), `source_url` (nullable).

`PluginVersionsResponse`: `project_id`, `versions` (list of `PluginVersionResponse`),
`selected` (always `null`), `notice` (empty string), `notice_kind` (empty string).

`PluginVersionResponse`: `version_id`, `project_id`, `name`, `version_number`,
`game_versions`, `loaders`, `files` (list of `PluginFileResponse`),
`dependencies`, `date_published`.

---

## Users

Prefix `/api/v1/users`. Registration semantics depend on instance state and
access mode (see [Setup & access mode](#setup--access-mode)):

- While the instance is **uninitialized**, `POST /api/v1/users` is rejected
  with `403 Forbidden ("Instance uninitialized. Complete setup bootstrap first.")`.
- In **`GLOBAL`** access mode, `POST /api/v1/users` is rejected with
  `403 Forbidden ("Public self-registration is disabled in GLOBAL access
  mode. Use an invitation token to register.")` — registration happens via
  `POST /api/v1/invites/accept`.
- In **`LOCAL`** access mode (default), `POST /api/v1/users` accepts open
  self-registration; the created user gets the default `viewer` role.

All other routes require a Bearer token, and `PATCH`/`DELETE` gate on
`user:write` / `user:delete`.

| Method | Path | Auth | Request body | Response | Notes |
|---|---|---|---|---|---|
| `GET` | `/api/v1/users` | Bearer | — | `200 list[UserResponse]` | |
| `POST` | `/api/v1/users` | Public* | `CreateUserRequest` | `201 UserResponse` | Registration — **public only in `LOCAL` mode on an initialized instance** (`403` otherwise) |
| `GET` | `/api/v1/users/{user_id}` | Bearer | — | `200 UserResponse` | `404` if not found |
| `PATCH` | `/api/v1/users/{user_id}` | Bearer (`user:write`) | `UpdateUserRequest` | `200 UserResponse` | |
| `DELETE` | `/api/v1/users/{user_id}` | Bearer (`user:delete`) | — | `204` | |

### Schemas

`CreateUserRequest`: `email` (validated), `password` (min 8 chars),
`display_name` (1–128 chars).

`UpdateUserRequest`: `email` (string\|null), `display_name` (string\|null),
`is_active` (bool\|null). Email validated when present.

`UserResponse`:
```json
{
  "user_id": "uuid",
  "email": "user@example.com",
  "display_name": "Alex",
  "is_active": true,
  "roles": ["admin"],
  "created_at": "2026-08-01T12:00:00",
  "last_login_at": null
}
```

---

## Health

Prefix `/api/v1/health`. All routes require a Bearer token. Only
`POST /evaluate/{server_id}` enforces server-scoped RBAC via
`require_server_permission("server.{id}.view")`; the read routes use
`get_current_user` (auth-only, no permission node).

| Method | Path | Auth | Query params | Response | Notes |
|---|---|---|---|---|---|
| `GET` | `/api/v1/health/status/{server_id}` | Bearer | — | `200 HealthStatusResponse` | `status` is `"unknown"` when no record exists |
| `POST` | `/api/v1/health/evaluate/{server_id}` | `server.{id}.view` | — | `200 dict` | Triggers a health evaluation |
| `GET` | `/api/v1/health/timeline/{server_id}` | Bearer | `limit` (default `100`, 1–10000) | `200 HealthTimelineResponse` | State-change history |
| `GET` | `/api/v1/health/dashboard` | Bearer | — | `200 HealthDashboardResponse` | Aggregated counts + per-server summaries |

### Schemas

`HealthStatusResponse`:
```json
{
  "server_id": "uuid",
  "status": "healthy",
  "previous_status": "warning",
  "contributing_factors": [],
  "trend": "stable",
  "confidence": 0.95,
  "last_updated": "2026-08-01T12:00:00"
}
```

Status values: `healthy`, `warning`, `critical`, `broken`, `unknown`, `pending`.

`HealthTimelineResponse`: `{"entries": [{"server_id", "previous_status",
"new_status", "contributing_factors", "timestamp"}]}`.

`HealthDashboardResponse`: `total_servers`, `healthy`, `warning`, `critical`,
`broken`, `unknown`, `pending` (ints) and `servers` (list of
`{"server_id", "status", "trend", "contributing_factors", "last_updated"}`).

---

## Monitoring

Prefix `/api/v1/monitoring`. All routes require a Bearer token. Per-server
routes enforce server-scoped RBAC via `require_server_permission(...)`.

| Method | Path | Auth | Request body | Query params | Response | Notes |
|---|---|---|---|---|---|---|
| `GET` | `/api/v1/monitoring/metrics` | `server.{id}.view` | — | `server_id` (required), `limit` (default `100`, 1–10000) | `200 list[dict]` | Metric points: `tps`, `players`, `ram_used_mb`, `cpu_percent`, `timestamp` |
| `POST` | `/api/v1/monitoring/alerts/{server_id}` | `server.{id}.settings` | `CreateAlertRuleRequest` | — | `201 dict` | Create an alert rule — `server_id` **path-based** (refactored to eliminate IDOR / parameter-pollution) |
| `GET` | `/api/v1/monitoring/alerts` | Bearer | — | — | `200 list[dict]` | **Stub** — always returns `[]` |
| `DELETE` | `/api/v1/monitoring/alerts/{alert_rule_id}` | `global.settings` | — | — | `204` | **Stub** — no-op |

`CreateAlertRuleRequest` (defined inline in the router, not in `schemas/`):
`server_id` (string, required), `metric_name` (string, required),
`condition` (`"gt"` default), `threshold` (float, required), `severity`
(`"warning"` default), `cooldown_minutes` (int, default `15`, ≥ 1).

---

## Schedules

Prefix `/api/v1/schedules`. Requires a Bearer token; mutating routes gate on
`global.settings`. All three are **stubs** (see `docs/current-state.md` §4.5).

| Method | Path | Auth | Response | Notes |
|---|---|---|---|---|
| `GET` | `/api/v1/schedules` | Bearer | `200 list` | **Stub** — always returns `[]` |
| `POST` | `/api/v1/schedules` | `global.settings` | `201 dict` | **Stub** — returns `{"success": true, "schedule_id": "stub-schedule-id"}` |
| `DELETE` | `/api/v1/schedules/{schedule_id}` | `global.settings` | `204` | **Stub** — no-op |

---

## Settings

Prefix `/api/v1/settings`. All routes require a Bearer token.

| Method | Path | Auth | Response | Notes |
|---|---|---|---|---|
| `GET` | `/api/v1/settings` | `settings:read` | `200 dict` | Current live settings and `requires_restart` field list |
| `PATCH` | `/api/v1/settings` | `settings:write` | `200 dict` | Persists updates to `config/settings.yaml`, updates live in-memory store, and hot-reloads running consumers |

`GET /api/v1/settings` returns:
```json
{
  "app_name": "onx-manager",
  "version": "0.1.0",
  "debug": false,
  "log_level": "INFO",
  "rate_limit_per_minute": 60,
  "idempotency_ttl_hours": 24,
  "circuit_breaker_max_failures": 5,
  "circuit_breaker_timeout_seconds": 30,
  "event_bus_retry_attempts": 3,
  "saga_timeout_seconds": 300,
  "requires_restart": ["app_name", "debug", "log_level"]
}
```

---

## Software

Prefix `/api/v1/software`. All routes require a Bearer token.

| Method | Path | Auth | Response | Notes |
|---|---|---|---|---|
| `GET` | `/api/v1/software` | Bearer | `200 list[dict]` | Supported software types (`type`, `name`, `description`, `url`, `supports_versions`) |
| `GET` | `/api/v1/software/{software_type}/versions` | Bearer | `200 list[string]` | Fetched versions; `404` for unknown `software_type` |

---

## Files

Prefix `/api/v1/servers/{server_id}/files`. All routes require a Bearer token
**and** server-scoped authorization via `require_server_permission(...)`
(owner, a member with the required role, or a global claim). A member with
the `viewer` server role can download files (`server.{id}.view`) but cannot
list/read/write/delete/upload/mkdir (those need `server.{id}.files`).

> **Sensitive-file guard:** `server.properties` carries `rcon.password`.
> All access to it is denied for **everyone** — reads (`GET /files`,
> `GET /files/content`, `GET /files/download`) and writes (`PUT /files/content`)
> return `403` for this filename (case-insensitive). This is enforced in
> `backend/app/api/v1/routers/files.py` (`SENSITIVE_FILENAMES` /
> `_assert_not_sensitive`).

| Method | Path | Auth | Request body | Response | Notes |
|---|---|---|---|---|---|
| `GET` | `/api/v1/servers/{server_id}/files` | `server.{id}.files` | — | `200 list[FileEntryResponse]` | List directory contents (`path` query param, default `""`); 403 on path traversal or sensitive file |
| `GET` | `/api/v1/servers/{server_id}/files/content` | `server.{id}.files` | — | `200 FileContentResponse` | Read text file content (`path` query param required) |
| `PUT` | `/api/v1/servers/{server_id}/files/content` | `server.{id}.files` | `WriteFileContentRequest` | `200 FileContentResponse` | Write text file content (`path` query param required) — uses atomic write |
| `DELETE` | `/api/v1/servers/{server_id}/files` | `server.{id}.files` | — | `204` | Delete file or directory (`path` query param required); cannot delete server root |
| `POST` | `/api/v1/servers/{server_id}/files/upload` | `server.{id}.files` | `multipart/form-data` | `201 FileEntryResponse` | Upload file (`file` form parameter, `path` query param default `""`) |
| `GET` | `/api/v1/servers/{server_id}/files/download` | `server.{id}.files` **or** `server.{id}.view` | — | `200 FileResponse` | Download file as `application/octet-stream` (`path` query param required) |
| `POST` | `/api/v1/servers/{server_id}/files/mkdir` | `server.{id}.files` | — | `201 FileEntryResponse` | Create directory (`path` query param required) |

### Schemas

`FileEntryResponse`:
```json
{
  "name": "server.properties",
  "path": "server.properties",
  "is_dir": false,
  "size": 1024
}
```

`FileContentResponse`:
```json
{
  "path": "server.properties",
  "content": "motd=A Minecraft Server\n..."
}
```

`WriteFileContentRequest`: `content` (string, required).

---

## Setup & access mode

The setup subsystem (`backend/app/api/v1/routers/setup.py`) manages instance
initialization and the access mode. Every fresh deployment starts
**uninitialized** — all protected routes are blocked (except the public
setup/invite/verify/login/health paths) until the Owner is created.

### Endpoints

| Method | Path | Auth | Request body | Response | Notes |
|---|---|---|---|---|---|
| `GET` | `/api/v1/setup/status` | Public | — | `200 SystemStatusResponse` | `{"initialized": bool, "access_mode": "LOCAL"/"GLOBAL", "user_count": int, "version": str}` — consumed by the setup wizard and `SystemStatusGuard` |
| `POST` | `/api/v1/setup/bootstrap` | Public | `BootstrapRequest` | `201 BootstrapResponse` | **Single-use** first-run: creates the Owner user and marks the instance initialized with the chosen access mode. Rejected `409 Conflict` once initialized. |
| `PUT` | `/api/v1/setup/access-mode` | **Owner only** (`require_owner()`) | `AccessModeRequest` | `200 SystemStatusResponse` | Flips `LOCAL` ↔ `GLOBAL`. `admin:full` alone is **not** sufficient — the caller needs the `owner` role or a `global.*` permission claim. Rejected `400` if the instance is not initialized. |

> **Owner authority:** the Owner is the bootstrap-created user who receives
> the `owner` role plus `admin:full` / `global.*` permission claims. Only the
> Owner (or a `global.*`-equipped claim) may change the access mode.

### Registration behavior by access mode

| Access mode | `POST /api/v1/users` self-registration | Invitations | Typical deployment |
|---|---|---|---|
| `LOCAL` (default) | ✅ Public — new users get the `viewer` role | Optional | Single-owner home-lab / LAN |
| `GLOBAL` | ❌ `403` — registration via invite token only (`POST /api/v1/invites/accept`) | Required | VPS / remote multi-user |

The access mode can be changed at any time after bootstrap via
`PUT /api/v1/setup/access-mode`.

### Schemas

`BootstrapRequest`: `email`, `password` (min 8 chars), `display_name`,
`access_mode` (default `"LOCAL"`).

`AccessModeRequest`: `access_mode` (`"LOCAL"` or `"GLOBAL"`).

`BootstrapResponse`: `success`, `message`, `user_id`, `access_token`,
`refresh_token`, `token_type`, `expires_in` (900).

`SystemStatusResponse`:
```json
{
  "initialized": true,
  "access_mode": "LOCAL",
  "user_count": 1,
  "version": "0.1.0"
}
```

---

## Invites

The invitation system (`backend/app/api/v1/routers/invites.py`) is the
registration path in `GLOBAL` access mode and the role-granting mechanism for
both modes. Invitations are stateful: their lifecycle status is `ACTIVE`,
`USED`, `REVOKED`, or `EXPIRED`. Acceptance atomically creates the user (and,
when the invite carries `server_id`/`server_role`, provisions the
`ServerMembershipModel` row).

| Method | Path | Auth | Request body | Response | Notes |
|---|---|---|---|---|---|
| `POST` | `/api/v1/invites` | `user:write` | `CreateInviteRequest` | `201 CreateInviteResponse` | Issue an invitation (can scope a global role and/or a server membership). Handler enforces Owner/Admin privilege checks on requested roles. |
| `GET` | `/api/v1/invites` | `user:write` | — | `200 list[...]` | List invitations (token hash never returned). |
| `DELETE` | `/api/v1/invites/{invite_id}` | `user:write` | — | `204` | Revoke an invitation (`status → REVOKED`). |
| `GET` | `/api/v1/invites/verify/{token}` | Public | — | `200 VerifyInviteResponse` | Pre-registration token validity check (returns the claimed role/display name so the InvitePage can render; no user account is created). |
| `POST` | `/api/v1/invites/accept` | Public | `AcceptInviteRequest` | `201 AcceptInviteResponse` | Redeem the token to register. Rejected for unknown/expired/revoked/used tokens. |

> Invite tokens are stored as **SHA-256 hashes** (`InvitationModel.token_hash`)
> in the `invitations` table; the plaintext token is returned only at creation
> time.

### Schemas

`CreateInviteRequest`: `email` (optional), `global_role` (optional default
`"member"`), `server_id` (optional), `server_role` (optional), `max_uses`
(default `1`).

`AcceptInviteRequest`: `token`, `email`, `password`, `display_name`.

---

## App-level endpoints

These are defined directly on the app in `backend/app/main.py` and are all public:

| Method | Path | Response | Notes |
|---|---|---|---|
| `GET` | `/health` | `200 dict` | Liveness: `{"status": "ok", "version": "0.1.0", "database": "connected", "uptime_seconds": 0}` |
| `GET` | `/metrics` | `200 text/plain` | Prometheus metrics (`501` if `prometheus_client` not installed) |
| `GET` | `/.well-known/jwks.json` | `200` | JWKS for RS256 public keys |
| `GET` | `/docs`, `/redoc`, `/openapi.json` | — | Swagger UI / ReDoc / OpenAPI schema |

---

## WebSocket protocol

**Endpoint:** `/ws?token=<jwt>`

- The access token is passed as the `token` query parameter (or as the
  first WebSocket subprotocol token). Missing/invalid tokens are rejected
  with a `1008 POLICY_VIOLATION` close frame **before** the connection is
  accepted.
- Messages are **binary JSON** frames (UTF-8 encoded), max **256 KiB**.
- Every message is an object with a `type` field. Channels are
  dot-scoped strings.

### Client → server messages

| `type` | Payload | Description |
|---|---|---|
| `ping` | `{}` | Keepalive; server replies `pong` |
| `subscribe` | `{"channels": ["server:abc", "metrics:*"]}` | Subscribe to up to 50 channels |
| `unsubscribe` | `{"channels": ["metrics:*"]}` | Unsubscribe |
| `refresh_token` | `{"token": "<new-jwt>"}` | Rotate the session token in place |

Unknown message types and invalid payloads produce an `error` message
(`UNKNOWN_TYPE`, `INVALID_PAYLOAD`, `PARSE_ERROR`).

### Server → client messages

| `type` | Payload | Description |
|---|---|---|
| `pong` | `{}` | Reply to `ping` |
| `state` | `{"server_id", "status"}` | Server state change |
| `state_sync` | `{"events": [...]}` | Replayed buffered events on connect |
| `event` | `{"event": {...}}` | Domain event payload |
| `metrics` | `{"server_id", "tps", "players", "ram_mb"}` | Periodic metrics tick |
| `metrics_batch` | `{"server_id", "samples": [...]}` | Batched metrics samples |
| `error` | `{"code", "message"}` | Error (e.g. `CHANNEL_LIMIT`, `INVALID_CHANNEL`, `PERMISSION_DENIED`, `RATE_LIMITED`) |
| `auth_expired` | `{}` | Token expired — client should reconnect with a fresh token |

### Channels

Channel authorization is permission-based at subscribe time
(`backend/app/websocket/authorization.py`). **WebSocket channel delivery is
fully functional (Phase 3 resolved)** — per-channel authorization enforces
**singular** REST permissions with an `admin:full` bypass (fixed in commit
`b98da77`). Frontend `WebSocketManager` handles active channel subscriptions
on route change (commit `d096f75`). `MetricsBridgeHandler` subscribes to
domain events and flushes batched metrics over `metrics:<serverId>` channel
every ~2s (commit `db1889d`).

The channel mapping:

| Channel | Required permission |
|---|---|
| `server:*` | `server:read`, `server:write` |
| `server:{server_id}` | `server:read` |
| `server:{server_id}:console` | `server:read` |
| `backup:*` / `backup:{backup_id}` | `backup:read` |
| `plugin:*` / `plugin:{plugin_id}` | `plugin:read` |
| `monitoring:*` / `monitoring:{server_id}` | `server:read` |
| `metrics:*` / `metrics:{server_id}` | `server:read` |
| `auth:*` | `user:read` |
| `user:{user_id}` | `user:read` |

> Note: channel authorization reads the caller's **global** permission claims
> (the `server:read`, `user:read`, etc. tokens on the account). Server-scoped
> membership does not open a channel on its own; the account's global claims
> gate subscription.

Maximum **50 channel subscriptions** per connection. WebSocket messages are
rate-limited per connection; exceeding the limit yields an `error`
(`RATE_LIMITED`) rather than a close frame. The session token is treated as
valid for 1 hour after connect and must be refreshed via `refresh_token`
before expiry.


---

## Exposure

Public panel and game server network exposure management (Cloudflare Tunnels, Playit.gg agent daemon, and UPnP port forwarding).

### `GET /api/v1/exposure/panel`

Get current web panel public exposure status (Cloudflare Named Tunnel or Playit.gg tunnel).

- **Auth:** Required (`admin` role or `exposure:read`)
- **Response `200 OK`:**
  ```json
  {
    "provider": "cloudflare",
    "is_enabled": true,
    "public_url": "https://panel.example.com",
    "status": "active"
  }
  ```

### `POST /api/v1/exposure/panel/cloudflare`

Configure and enable Cloudflare Tunnel public exposure for the web panel.

- **Auth:** Required (`owner` role)
- **Body:**
  ```json
  {
    "tunnel_token": "eyJhIjoi..."
  }
  ```

### `POST /api/v1/exposure/panel/playit`

Enable Playit.gg tunnel public exposure for the web panel.

- **Auth:** Required (`owner` role)

### `DELETE /api/v1/exposure/panel`

Disable public panel exposure and terminate running tunnel agents.

- **Auth:** Required (`owner` role)

### `GET /api/v1/exposure/playit/claim`

Generate or retrieve a Playit.gg account claim link.

- **Auth:** Required (`admin` role)
- **Response `200 OK`:**
  ```json
  {
    "claim_url": "https://playit.gg/claim/abc123xyz"
  }
  ```

### `DELETE /api/v1/exposure/playit/credentials`

Remove stored Playit.gg agent authentication credentials.

- **Auth:** Required (`owner` role)

### `POST /api/v1/exposure/playit/reset`

Reset local Playit daemon agent state.

- **Auth:** Required (`owner` role)

### `GET /api/v1/servers/{server_id}/exposure`

Get game server network exposure configuration and active public address.

- **Auth:** Required (`servers:read`)
- **Response `200 OK`:**
  ```json
  {
    "server_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "exposure_type": "playit",
    "public_address": "auto-mc.playit.gg",
    "public_port": 25565,
    "is_active": true
  }
  ```

### `POST /api/v1/servers/{server_id}/exposure/playit`

Enable Playit.gg tunnel for a specific Minecraft server.

- **Auth:** Required (`servers:write`)

### `DELETE /api/v1/servers/{server_id}/exposure`

Disable public exposure for a Minecraft server.

- **Auth:** Required (`servers:write`)

### `GET /api/v1/servers/{server_id}/exposure/ports`

List additional forwarded companion ports (e.g. BlueMap, Dynmap, Voice Chat).

- **Auth:** Required (`servers:read`)

### `POST /api/v1/servers/{server_id}/exposure/ports`

Add a companion port forwarding rule.

- **Auth:** Required (`servers:write`)
- **Body:**
  ```json
  {
    "port": 8100,
    "protocol": "tcp",
    "label": "Dynmap Web"
  }
  ```

### `DELETE /api/v1/servers/{server_id}/exposure/ports/{port_id}`

Remove a companion port forwarding rule.

- **Auth:** Required (`servers:write`)
