# Security Architecture

This document describes the authentication, authorization, audit, data protection, rate limiting, and session management systems. Cross-reference: `contracts/permissions.yaml` for the full permission and role definitions.

---

## Authentication

### JWT RS256 (Asymmetric)

Tokens use RS256 (RSA Signature with SHA-256). The private key signs tokens; the public key verifies them. This enables service separation — verification services never hold the signing key.

| Property | Value |
|---|---|
| Algorithm | RS256 |
| Key size | 2048-bit RSA |
| Key generation | Auto-generated in-process by default |
| External keys | `set_private_key()` / `set_public_key()` for loading PEM files |
| Production | Must load persistent keys — auto-generated keys are ephemeral |

**Design rationale**: RS256 was chosen over HS256 so that Batch-05 and Batch-06 can verify tokens without holding the private key. Asymmetric signing adds slight computational overhead but enables key separation across services.

### Token Format

| Token | TTL | Storage | Notes |
|---|---|---|---|
| Access token | 15 minutes | Persisted in the frontend `authStore` (localStorage key `mcs_auth`) | Short-lived, stateless |
| Refresh token | 7 days | Returned in the login body and stored in the same frontend `authStore`; DB keeps only the SHA-256 hash | Individually revocable, rotated on use |

### Refresh Token Rotation

- Opaque 48-byte random tokens stored as SHA-256 hash in the database
- Each refresh operation revokes the old token and issues a new one
- DB storage enables immediate revocation — logout endpoint revokes by hash lookup
- Refresh without a valid token returns HTTP 401
- One refresh token per session

### API Keys

- Prefix: `mcs_`
- Storage: SHA-256 hash via `hash_api_key()` (`backend/app/core/security.py`) — **unsalted** (not currently salted or peppered)
- Display: Shown once at creation, never retrievable afterward

### Login Flow

```
1. Client sends credentials → /auth/login
2. Server validates credentials (Argon2id password verification)
3. Server generates access token (RS256, 15 min TTL)
4. Server generates opaque refresh token, stores SHA-256 hash in DB
5. Returns access + refresh tokens in the response body; client persists both in `authStore` (localStorage) — **no httpOnly cookie is used**
6. Client uses access token for API calls (Authorization: Bearer <token>)
7. On expiration, client calls /auth/refresh sending the refresh token in the JSON body
8. Server rotates refresh token, issues new access token
```

---

## Authorization

### Model: RBAC + ABAC Hybrid

The authorization system *defines* Role-Based Access Control as the primary model with Attribute-Based Access Control extensions for resource-level checks. **However, authorization is only partially enforced in the request path.** See the known-gap callout in [`docs/API.md`](../API.md) — the practical consequence is that any authenticated user can call most endpoints regardless of their token's `permissions` or `roles`, with only a small set of destructive endpoints gated.

What exists today:

1. `PermissionEvaluator` (`backend/app/modules/auth/infrastructure/permissions.py`) can evaluate role permissions (RBAC) and apply ABAC rules such as resource ownership
2. Inactive users are rejected at evaluation time (`has_permission`/`evaluate_abac` return `False` for inactive users)
3. The evaluator is only called at **login/refresh** to build the token's claims — it is **not** invoked by any command/query handler, router, or middleware to gate a request
4. **Only a small set of destructive API endpoints checks permissions before executing** (via the `require_permission` dependency — see the callout below); every other endpoint does not

> **Known gap — authorization is only partially enforced.** `PermissionDenied` is defined and mapped to HTTP 403 in `backend/app/api/errors.py`. A `require_permission` dependency gates the following 24 routes today (22 mutating + 2 read-only marketplace; verified 2026-08-04, `contracts/permissions.yaml` v1.4):
>
> - **servers:** `POST /servers`, `POST /servers/scan`, `POST /servers/import`, `PATCH /servers/{server_id}`, `DELETE /servers/{server_id}` (`server:write`/`server:delete`), `POST /servers/{id}/start` (`server:start`), `POST /servers/{id}/stop` + `/restart` (`server:stop`), `POST /servers/{id}/command`, `POST /servers/reconcile`, `POST /servers/runtime/ownership/claim`, `POST /servers/refresh` (`server:write`)
> - **backups:** `POST /backups` (`backup:create`), `DELETE /backups/{id}` (`backup:delete`), `POST /backups/{id}/restore` (`backup:restore`), `POST /backups/{id}/verify` (`backup:read`)
> - **plugins:** `DELETE /servers/{server_id}/plugins/{id}` + the three `/servers/{server_id}/plugins/marketplace/*` routes (`plugin:manage`) — but **not** `enable`/`disable` (K4)
> - **users:** `PATCH /users/{id}` (`user:write`), `DELETE /users/{id}` (`user:delete`)
> - **auth:** `POST /auth/api-keys`, `DELETE /auth/api-keys/{id}` (`user:write`)
>
> The vast majority of routes — including plugin enable/disable, `PATCH /settings`, the alert-rule routes, health-evaluate, the schedule routes, and all reads (list/detail/console/runtime/metrics/users/settings) — still do not check permissions (`request.state.permissions` is written by `AuthMiddleware` but never read outside the gated routes). This is a real security gap that needs a dedicated fix, not an intentional design choice. Tracked as Phase 4 §6.1 in `docs/roadmap/MCS-Manager-Engineering-Blueprint-V5.md`.

### Permission Strings

Permission strings follow the `<resource>:<action>` format. Defined in `contracts/permissions.yaml`.

| Permission | Description | Scope |
|---|---|---|
| `server:read` | View server details and status | `server_id` |
| `server:write` | Modify server configuration | `server_id` |
| `server:start` | Start a server | `server_id` |
| `server:stop` | Stop a server | `server_id` |
| `server:delete` | Delete a server | `server_id` |
| `backup:read` | View backup list and details | `server_id` |
| `backup:create` | Create backups | `server_id` |
| `backup:restore` | Restore from backup | `server_id` |
| `backup:delete` | Delete backups | `server_id` |
| `plugin:read` | View installed plugins | `server_id` |
| `plugin:install` | Install new plugins | `server_id` |
| `plugin:manage` | Enable/disable/uninstall plugins | `server_id` |
| `user:read` | View user list | `global` |
| `user:write` | Create/edit users | `global` |
| `user:delete` | Delete users | `global` |
| `settings:read` | View system settings | `global` |
| `settings:write` | Modify system settings | `global` |
| `admin:full` | Unrestricted access | `global` |

### Role Definitions

| Role | Permissions | Typical User |
|---|---|---|
| `viewer` | `server:read`, `backup:read`, `plugin:read` | Read-only monitoring |
| `operator` | `server:read`, `server:write`, `server:start`, `server:stop`, `backup:read`, `backup:create`, `plugin:read`, `plugin:install`, `plugin:manage` | Day-to-day server management |
| `admin` | `admin:full` (unrestricted) | System administration |

### ABAC Context Rules

The ABAC extension (as implemented in `PermissionEvaluator.evaluate_abac()`) defines resource-specific rules:

- **Resource ownership**: A user can modify a resource if they are the `resource_owner_id`
- **Scope enforcement**: Server-scoped permissions (`server_id`) only apply to specific server resources; global-scoped permissions apply system-wide

These rules are **not enforced** — `evaluate_abac()` exists but is never called in any request path (see the known-gap callout above). The permission strings above *are* enforced on the small set of destructive routes gated by `require_permission`; the ABAC ownership/scope rules are not. Together they describe the intended model, not current behavior.

### WebSocket channel authorization

The WebSocket handshake validates the JWT **before** `accept()` (`backend/app/websocket/endpoint.py:51-62`), and per-channel authorization is checked at subscribe time (`ChannelAuthorizer.can_subscribe`). **However, the channel gate currently fails closed for every real client:** `CHANNEL_PATTERNS` (`backend/app/websocket/authorization.py:3-17`) requires **plural** permission strings (`servers:read`, `backups:read`, …) while JWT/api-key claims carry **singular** REST permissions (`server:read`, …) built at login. Every `subscribe` therefore returns `PERMISSION_DENIED` and no channel can be subscribed. Separately, `EventDispatcher`/`MetricsBatcher` are never instantiated, so no server-push events reach connected clients. This is safe (fail-closed) but non-functional; full trace in `docs/PERMISSIONS_FUTURE_IDEAS.md` §4, tracked as K1/K2 in `docs/roadmap/MCS-Manager-Engineering-Blueprint-V5.md`.

---

## Audit Log

### Cryptographic Hash Chain

The audit log uses a SHA-256 hash chain to ensure tamper evidence.

```
Row N-1: hash = SHA-256(JSON(content_{N-1}) + hash_{N-2})
Row N:   hash = SHA-256(JSON(content_N) + hash_{N-1})
```

Each row's hash includes the previous row's hash, computed over JSON-serialized content. This creates an immutable chain — altering any row breaks all subsequent hashes.

| Property | Detail |
|---|---|
| Algorithm | SHA-256 |
| Chain method | Previous hash included in current hash computation |
| Serialization | JSON (normalized via `_fmt_ts()` for consistent timestamps) |
| Verification | `verify_chain()` recomputes all hashes and reports mismatches |
| Detection | Tampering is detected but not prevented — hash collisions are infeasible with SHA-256 |

### Timestamp Normalization

The `_fmt_ts()` function normalizes timestamps to ISO 8601 with Z suffix:
```
YYYY-MM-DDTHH:MM:SS.ffffffZ
```
This ensures identical hashes across write and verification reads regardless of SQLite's string-based datetime storage.

### Database Enforcement

- No database-level privilege restrictions exist: the default SQLite deployment has no per-user `UPDATE`/`DELETE` restrictions on audit tables, and no migration defines any
- Chain integrity verification: `verify_chain()` exists (it recomputes all hashes and reports mismatches), but **nothing schedules or calls it** — there is currently no automatic periodic integrity check running

### Query Format

There is currently **no audit query endpoint** — the `audit_log` table and its writer exist, but no read API (`GET /audit` is not implemented in any router). A future endpoint could expose each log entry with its hash, previous hash, and chain position for independent verification.

---

## Data Protection

### Encryption at Rest

| Data | Method |
|---|---|
| Backups | AES-256-GCM |
| Passwords | Argon2id (memory-hard, GPU-resistant) |
| API keys | SHA-256 hash (unsalted) via `hash_api_key()`, never stored in plaintext |

### TLS

All communications use TLS 1.3. Protocol downgrade is rejected at the reverse proxy level.

### Secrets Management

- Secrets are loaded from environment variables only (there is no HashiCorp Vault / `hvac` integration in the codebase)
- **Never** hardcoded in source code, configuration files, or documentation
- Production deployments must use persistent key material (see JWT keys above)

---

## Rate Limiting

### Architecture

Rate limiting is a single `RateLimitMiddleware` keyed per `client_ip:path`:

| Layer | Scope | Mechanism |
|---|---|---|
| Application (REST) | Per `client_ip:path` pair | In-memory sliding window — **60 requests per minute**, not configurable per route, no per-user/per-endpoint tiers |
| WebSocket | Per-connection message rate | 50 messages/second (`WSRateLimiter`) |

There are no `X-RateLimit-*` headers. On exceeding the limit the middleware returns `429 Too Many Requests` with a `Retry-After` header.

The same behavior is described (and matches the implementation) in [`docs/API.md`](../API.md) — rate limiting. Earlier per-route tiers (e.g. 10/min for `/auth/*`, 100/min for API endpoints) and a reverse-proxy/nginx token-bucket layer do **not** exist in the current implementation.

---

## Session Management

### Session Tokens

- One refresh token per active session
- Stored as SHA-256 hash in the database
- Rotated on each refresh — old token is revoked, new token is issued
- Not bound to a user agent or IP: the `refresh_tokens` table stores only `token_hash`, `expires_at`, and `user_id` (IP/user-agent fields exist only on `audit_log`, for a different purpose)

### Revocation

| Mechanism | Scope | Method |
|---|---|---|
| User logout | Current session | Revokes refresh token by hash lookup |
| Admin force logout | All sessions for a user | Revokes all refresh tokens for that user |
| Token rotation | Single refresh | Old token hash replaced by new token hash |

### Inactive Session Cleanup

- Expired refresh tokens (past 7-day TTL) are **not** currently pruned: a cleanup task exists in code (`run_cleanup_task`), but it is not registered with the scheduler and never runs automatically
- No active session data survives token expiry

---

See `docs/API.md` for endpoint security details and `docs/architecture/ARCHITECTURE.md` for system-level security boundaries.
