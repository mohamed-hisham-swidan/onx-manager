# REST API Reference

**Base URL:** `http://<host>:8000/api/v1`
**Content-Type:** `application/json` (responses and mutating requests)
**Auth:** `Authorization: Bearer <jwt>` or `Authorization: Bearer <api_key>` — see [Authentication](#authentication)

> Cross-references: [Architecture](ARCHITECTURE.md), [Security](SECURITY.md), [Frontend](FRONTEND.md)
>
> This document is generated from the router code (`backend/app/api/v1/routers/`).
> Every endpoint below was verified directly against its router function.

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
16. [App-level endpoints](#app-level-endpoints)
17. [WebSocket protocol](#websocket-protocol)

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
(see [Environment Variables](ARCHITECTURE.md#environment-variables-production)).

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
- `POST /api/v1/users` (registration)
- All `/api/v1/schedules/*`
- `/health`, `/metrics`, `/docs`, `/redoc`, `/openapi.json`, `/.well-known/jwks.json`

Every other route requires a valid Bearer token.

> **Known gap — authorization is only partially enforced.**
>
> Authentication is enforced globally, and since the "enforce authorization
> on highest-risk destructive endpoints" fix a small set of destructive
> routes gate on the caller's token claims via the `require_permission`
> dependency. But the rest of the request path is **not** gated: most
> endpoints check neither the caller's `permissions` nor `roles`, the
> command/query handlers do not gate operations on the caller's
> `permissions`, and `PermissionEvaluator.has_permission()` /
> `evaluate_abac()` are only called at login/refresh to build the token's
> claims — never to gate a request.
>
> **Currently enforced** (raise `PermissionDenied` → 403 when the caller
> lacks the permission; `admin:full` always passes):
>
> **servers** — `POST /servers` → `server:write`; `POST /servers/scan` →
> `server:write`; `POST /servers/import` → `server:write`;
> `PATCH /servers/{server_id}` → `server:write`; `DELETE /servers/{server_id}`
> → `server:delete`; `POST /servers/{server_id}/start` → `server:start`;
> `POST /servers/{server_id}/stop` and `/restart` → `server:stop`;
> `POST /servers/{server_id}/command` → `server:write`;
> `POST /servers/reconcile` → `server:write`;
> `POST /servers/runtime/ownership/claim` → `server:write`;
> `POST /servers/refresh` → `server:write`.
>
> **backups** — `POST /backups` → `backup:create`; `DELETE /backups/{backup_id}`
> → `backup:delete`; `POST /backups/{backup_id}/restore` → `backup:restore`;
> `POST /backups/{backup_id}/verify` → `backup:read`.
>
> **plugins** — `DELETE /servers/{server_id}/plugins/{plugin_id}` →
> `plugin:manage`;
> `GET /servers/{server_id}/plugins/marketplace/search`,
> `GET /servers/{server_id}/plugins/marketplace/projects/{id}/versions`,
> `POST /servers/{server_id}/plugins/marketplace/install` → `plugin:manage`.
>
> **users / auth** — `PATCH /users/{user_id}` → `user:write`;
> `DELETE /users/{user_id}` → `user:delete`;
> `POST /auth/api-keys` and `DELETE /auth/api-keys/{id}` → `user:write`.
>
> **Practical consequence: any authenticated user (any valid Bearer token,
> any role) can still call every other endpoint in the system** — including
> plugin enable/disable (K4), `PATCH /settings`, the alert-rule routes, the
> health-evaluate route, the schedule routes, and all reads (list/detail/
> console/runtime/metrics/users/settings). The remaining routes are a known
> security gap in the current implementation, not an intentional design choice,
> and are tracked in `docs/mcs-manager-roadmap-v2.md` Phase 4 §6.1.

### 401 vs 403

| Status | Meaning in this codebase |
|---|---|
| `401 AUTHENTICATION_ERROR` | Missing, malformed, expired, or invalid Bearer token; revoked/expired API key; deactivated account. No request reaches the route. |
| `403 PERMISSION_DENIED` | Caller authenticated but lacks the required permission. Produced by the `require_permission` dependency on the destructive endpoints listed in the authorization known gap above. Other routes never produce it (not yet enforced). |

---

## Status codes

| Status | Used for |
|---|---|
| `200` | Successful reads and non-creating writes |
| `201` | Resource created (`POST` list endpoints) |
| `204` | Deleted / void (no body) |
| `400` | Bad request (e.g. `POST /servers/scan` on a non-directory) |
| `401` | Authentication failure (see above) |
| `403` | Permission denied — raised by `require_permission` on the destructive endpoints listed in the authorization known gap above; not yet enforced on other routes |
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
`backend/app/api/errors.py` and is produced by the `require_permission`
dependency on the destructive endpoints listed in the authorization known
gap. It is still not raised for the majority of routes, which remain
unauthorized on the enforcement path.

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
| `GET` | `/api/v1/auth/api-keys` | Bearer | — | `200 list[ApiKeyResponse]` | Active keys for the current user (`key` is `null`) |
| `POST` | `/api/v1/auth/api-keys` | Bearer | `ApiKeyCreateRequest` | `201 ApiKeyResponse` | **Plaintext `key` returned only here** |
| `DELETE` | `/api/v1/auth/api-keys/{api_key_id}` | Bearer | — | `204` | Revokes an API key |

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
  "permissions": ["servers:read", "backups:read"],
  "expires_at": null,
  "is_revoked": false,
  "created_at": "2026-08-01T12:00:00"
}
```

---

## Servers

Prefix `/api/v1/servers`. All routes require a Bearer token.

| Method | Path | Request body | Query params | Response | Notes |
|---|---|---|---|---|---|
| `GET` | `/api/v1/servers/available-port` | — | — | `200 dict` | Returns `{"port": <int>}` — first free port ≥ 25565 |
| `GET` | `/api/v1/servers` | — | `status`, `group_id`, `name_search`, `minecraft_version` | `200 list[ServerResponse]` | Filterable list; no pagination |
| `POST` | `/api/v1/servers` | `ServerCreateRequest` | — | `201 dict` | Creates a server |
| `POST` | `/api/v1/servers/scan` | `ScanDirectoryRequest` | — | `200 ScanResult` | Scans a directory for an existing server; `400`/`403` on bad path/permission |
| `POST` | `/api/v1/servers/import` | `ImportServerRequest` | — | `201 dict` | Imports an existing server dir |
| `GET` | `/api/v1/servers/{server_id}` | — | — | `200 ServerDetailResponse` | Full server detail |
| `PATCH` | `/api/v1/servers/{server_id}` | `ServerUpdateRequest` | — | `200 dict` | Update properties/memory |
| `DELETE` | `/api/v1/servers/{server_id}` | — | — | `204` | Delete server |
| `POST` | `/api/v1/servers/{server_id}/start` | — | — | `200 dict` | Start the server |
| `POST` | `/api/v1/servers/{server_id}/stop` | `ServerActionRequest` | — | `200 dict` | Stop; body `reason` (default `""`) |
| `POST` | `/api/v1/servers/{server_id}/restart` | — | — | `200 dict` | Restart |
| `GET` | `/api/v1/servers/{server_id}/console` | — | `tail` (default `100`, 1–10000) | `200 ConsoleResponse` | Recent console lines |
| `POST` | `/api/v1/servers/{server_id}/command` | `CommandRequest` | — | `200 dict` | Sends a console command (`SERVER_NOT_RUNNING` if not running) |
| `GET` | `/api/v1/servers/{server_id}/runtime` | — | — | `200 RuntimeDiagnosticsResponse` | Live runtime diagnostics |
| `GET` | `/api/v1/servers/runtime/ownership` | — | — | `200 RuntimeOwnershipResponse` | Orphan/conflict snapshot |
| `POST` | `/api/v1/servers/runtime/ownership/claim` | — | `server_id` (query) | `200 ClaimLocalhostResponse` | Claim localhost ownership for a server |
| `GET` | `/api/v1/servers/{server_id}/runtime/validate` | — | — | `200 ValidationChainResponse` | Runs the ownership validation chain |
| `POST` | `/api/v1/servers/reconcile` | `ReconcileRequest` (optional body) | — | `200 dict` | Runtime reconciliation + orphan cleanup; `scope` defaults `project_owned` |
| `POST` | `/api/v1/servers/refresh` | — | `dry_run` (bool, default `false`) | `200 ReconciliationResultResponse` | Filesystem reconciliation (DB ↔ disk) |

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

| Method | Path | Request body | Query params | Response | Notes |
|---|---|---|---|---|---|
| `GET` | `/api/v1/backups` | — | `server_id` (optional filter) | `200 list[BackupResponse]` | |
| `POST` | `/api/v1/backups` | `CreateBackupRequest` | — | `201 dict` | Starts a backup job |
| `GET` | `/api/v1/backups/{backup_id}` | — | — | `200 BackupResponse` | |
| `DELETE` | `/api/v1/backups/{backup_id}` | — | — | `204` | |
| `POST` | `/api/v1/backups/{backup_id}/restore` | — | — | `200 dict` | Restore from backup |
| `POST` | `/api/v1/backups/{backup_id}/verify` | — | — | `200 VerifyBackupResponse` | Checksum/size verification |

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
| `GET` | `/api/v1/servers/{server_id}/plugins` | Bearer | — | `200 list[PluginResponse]` | **Triggers filesystem reconciliation first** — on-disk `.jar` files become `detected` rows, deleted files are pruned |
| `GET` | `/api/v1/servers/{server_id}/plugins/marketplace/search` | `plugin:manage` | — | `200 list[PluginSearchResultResponse]` | Modrinth catalog search (`query`, `limit`, `offset` query params) |
| `GET` | `/api/v1/servers/{server_id}/plugins/marketplace/projects/{project_id}/versions` | `plugin:manage` | — | `200 PluginVersionsResponse` | Versions + best-version selection for the server (with `selected`, `notice`, `notice_kind`) |
| `POST` | `/api/v1/servers/{server_id}/plugins/marketplace/install` | `plugin:manage` | `InstallModrinthPluginRequest` | `201 InstallModrinthPluginResponse` | Downloads the `.jar` (SHA-1/SHA-512 verified) into the server's `plugins/` folder |
| `GET` | `/api/v1/servers/{server_id}/plugins/{plugin_id}` | Bearer | — | `200 PluginResponse` | |
| `DELETE` | `/api/v1/servers/{server_id}/plugins/{plugin_id}` | `plugin:manage` | — | `204` | Uninstall — sets `pending_deletion`; file removed on next server start/restart |
| `POST` | `/api/v1/servers/{server_id}/plugins/{plugin_id}/enable` | Bearer | — | `200 dict` | ⚠️ Auth-only; no `require_permission` (K4) |
| `POST` | `/api/v1/servers/{server_id}/plugins/{plugin_id}/disable` | Bearer | — | `200 dict` | ⚠️ Auth-only; no `require_permission` (K4) |

> **Note:** the marketplace routes carry `require_permission("plugin:manage")`
> while the plain list/get/enable/disable routes use `Depends(get_current_user)`
> only. Closing the enable/disable gap is tracked as K4 in
> `docs/mcs-manager-roadmap-v2.md` Phase 4 §6.1. See `docs/plugins-and-marketplace.md`.

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

## Users

Prefix `/api/v1/users`. `POST /api/v1/users` is public (registration); all
other routes require a Bearer token.

| Method | Path | Auth | Request body | Response | Notes |
|---|---|---|---|---|---|
| `GET` | `/api/v1/users` | Bearer | — | `200 list[UserResponse]` | |
| `POST` | `/api/v1/users` | Public | `CreateUserRequest` | `201 UserResponse` | Registration |
| `GET` | `/api/v1/users/{user_id}` | Bearer | — | `200 UserResponse` | `404` if not found |
| `PATCH` | `/api/v1/users/{user_id}` | Bearer | `UpdateUserRequest` | `200 UserResponse` | |
| `DELETE` | `/api/v1/users/{user_id}` | Bearer | — | `204` | |

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

Prefix `/api/v1/health`. All routes require a Bearer token.

| Method | Path | Query params | Response | Notes |
|---|---|---|---|---|
| `GET` | `/api/v1/health/status/{server_id}` | — | `200 HealthStatusResponse` | `status` is `"unknown"` when no record exists |
| `POST` | `/api/v1/health/evaluate/{server_id}` | — | `200 dict` | Triggers a health evaluation |
| `GET` | `/api/v1/health/timeline/{server_id}` | `limit` (default `100`, 1–10000) | `200 HealthTimelineResponse` | State-change history |
| `GET` | `/api/v1/health/dashboard` | — | `200 HealthDashboardResponse` | Aggregated counts + per-server summaries |

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

Prefix `/api/v1/monitoring`. All routes require a Bearer token.

| Method | Path | Request body | Query params | Response | Notes |
|---|---|---|---|---|---|
| `GET` | `/api/v1/monitoring/metrics` | — | `server_id` (required), `limit` (default `100`, 1–10000) | `200 list[dict]` | Metric points: `tps`, `players`, `ram_used_mb`, `cpu_percent`, `timestamp` |
| `POST` | `/api/v1/monitoring/alerts` | `CreateAlertRuleRequest` | — | `201 dict` | Create an alert rule |
| `GET` | `/api/v1/monitoring/alerts` | — | — | `200 list[dict]` | **Stub** — always returns `[]` |
| `DELETE` | `/api/v1/monitoring/alerts/{alert_rule_id}` | — | — | `204` | **Stub** — no-op |

`CreateAlertRuleRequest` (defined inline in the router, not in `schemas/`):
`server_id` (string, required), `metric_name` (string, required),
`condition` (`"gt"` default), `threshold` (float, required), `severity`
(`"warning"` default), `cooldown_minutes` (int, default `15`, ≥ 1).

---

## Schedules

Prefix `/api/v1/schedules`. **Public** (no auth).

| Method | Path | Response | Notes |
|---|---|---|---|
| `GET` | `/api/v1/schedules` | `200 list` | **Stub** — always returns `[]` |
| `POST` | `/api/v1/schedules` | `201 dict` | **Stub** — returns `{"success": true, "schedule_id": "stub-schedule-id"}` |
| `DELETE` | `/api/v1/schedules/{schedule_id}` | `204` | **Stub** — no-op |

---

## Settings

Prefix `/api/v1/settings`. All routes require a Bearer token.

| Method | Path | Response | Notes |
|---|---|---|---|
| `GET` | `/api/v1/settings` | `200 dict` | Read-only settings snapshot |
| `PATCH` | `/api/v1/settings` | `200 dict` | **Stub** — returns `{"success": true, "message": "Settings updated (stub)"}` |

`GET /api/v1/settings` returns:
```json
{
  "app_name": "MCS Manager",
  "version": "4.0.0",
  "debug": false,
  "log_level": "info",
  "rate_limit_per_minute": 60,
  "idempotency_ttl_hours": 24,
  "circuit_breaker_max_failures": 5,
  "circuit_breaker_timeout_seconds": 30,
  "event_bus_retry_attempts": 3,
  "saga_timeout_seconds": 60
}
```

---

## Software

Prefix `/api/v1/software`. All routes require a Bearer token.

| Method | Path | Response | Notes |
|---|---|---|---|
| `GET` | `/api/v1/software` | `200 list[dict]` | Supported software types (`type`, `name`, `description`, `url`, `supports_versions`) |
| `GET` | `/api/v1/software/{software_type}/versions` | `200 list[string]` | Fetched versions; `404` for unknown `software_type` |

---

## App-level endpoints

These are defined directly on the app in `backend/app/main.py` and are all public:

| Method | Path | Response | Notes |
|---|---|---|---|
| `GET` | `/health` | `200 dict` | Liveness: `{"status": "ok", "version": "4.0.0", "database": "connected", "uptime_seconds": 0}` |
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

Channel authorization is permission-based at subscribe time. **The channel gate
currently fails closed for every real client** — `CHANNEL_PATTERNS` requires
plural permission strings (`servers:read`, …) while JWT/api-key claims carry
singular REST permissions (`server:read`, …), so every `subscribe` returns
`PERMISSION_DENIED` and no channel can be subscribed. Additionally, the
`EventDispatcher`/`MetricsBatcher` are never instantiated, so even a valid
subscription would never receive pushed events. See
`docs/PERMISSIONS_FUTURE_IDEAS.md` §4 (traced 2026-08-02) and roadmap v2 K1/K2.

The channel table below documents the **intended** mapping:

| Channel | Required permission |
|---|---|
| `server:*` | `servers:read`, `servers:write` |
| `server:{server_id}` | `servers:read` |
| `server:{server_id}:console` | `servers:console` |
| `backup:*` / `backup:{backup_id}` | `backups:read` |
| `plugin:*` / `plugin:{plugin_id}` | `plugins:read` |
| `monitoring:*` / `monitoring:{server_id}` | `monitoring:read` |
| `metrics:*` / `metrics:{server_id}` | `monitoring:read` |
| `auth:*` | `auth:read` |
| `user:{user_id}` | `users:read` |

Maximum **50 channel subscriptions** per connection. WebSocket messages are
rate-limited per connection; exceeding the limit yields an `error`
(`RATE_LIMITED`) rather than a close frame. The session token is treated as
valid for 1 hour after connect and must be refreshed via `refresh_token`
before expiry.
