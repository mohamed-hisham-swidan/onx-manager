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

### Model: RBAC + ABAC Hybrid (enforced)

Authorization uses Role-Based Access Control over global instance permissions
plus Attribute-Based Access Control for server-scoped resources. Since Phase 4
(commit `a47daa8`, 2026-08-11) authorization is enforced in the request path
through FastAPI dependencies; it is no longer a ticket-time-only model.

**Enforcement points** (all defined in `backend/app/api/deps.py`):

1. `require_permission(...)` — checks global permission claims from the token
   (with an `admin:full` bypass). Used for instance-wide operations:
   `server:create`, `server:write`, `server:delete`, `server:read`
   (host-wide runtime snapshot), `backup:*`, `plugin:manage`, `user:*`,
   `settings:*`, `global.settings`.
2. `require_server_permission(...)` — server-scoped RBAC. Resolves
   `server_id` from the request (path/query/body; conflicting values return
   `400`), verifies the server exists (`404` when the caller cannot see it),
   then grants access to the server **owner** (`ServerModel.owner_id`), a
   **member** whose `ServerMembershipModel` role includes the required node,
   or any caller with a global bypass claim (`admin:full`, `global.*`,
   `global.servers.manage`). Operates on dynamic nodes such as
   `server.{id}.view`, `server.{id}.power`, `server.{id}.console`,
   `server.{id}.files`, `server.{id}.settings`, `server.{id}.backup`,
   `server.{id}.players`.
3. `require_owner()` — Owner-only guard for access-mode changes. Satisfied
   only by the `owner` role or a `global.*` permission claim; `admin:full`
   alone is **not** sufficient.

`PermissionEvaluator` (`backend/app/modules/auth/infrastructure/permissions.py`)
evaluates role permissions and ABAC ownership rules when tokens are issued
(login/refresh), and inactive users are rejected at evaluation time. Denials
surface as `403 PERMISSION_DENIED` via `backend/app/api/errors.py`.

The live route→permission matrix is the single source of truth:
`contracts/permissions.yaml` (v1.5, 85 effective routes), regenerated from
runtime introspection of the route table and CI-enforced via
`scripts/check-route-contract` (`.github/workflows/route-permission-ci.yml`).

> **Remaining auth-only reads (no permission node).** The following endpoints
> are authenticated (`get_current_user`) but still carry no permission check;
> the contract marks them `missing` with a required permission listed:
> `GET /servers`, `GET /servers/{server_id}`, `GET /auth/me`,
> `GET /auth/api-keys`, `GET /users`, `GET /users/{user_id}`,
> `GET /backups`, `GET /backups/{backup_id}`, `GET /plugins`,
> `GET /plugins/{plugin_id}`, `GET /schedules`, `GET /health/status/{id}`,
> `GET /health/timeline/{id}`, `GET /health/dashboard`,
> `GET /monitoring/alerts`. These are the accepted residual gap of
> Batch 7/7.1 — they do not expose secrets that Auth-only routes already
> guarded (e.g. `GET /servers/{server_id}` was already auth-only pre-Phase-4),
> but they are candidates for a future `server:read`/`user:read`/`backup:read`
> pass.

### Server-scoped files & the sensitive-file guard

All 7 Files API routes gate on `server.{id}.files`; download additionally
accepts `server.{id}.view` (so `viewer` server members can download but not
list/read/write/mkdir/upload/delete). Application secret files (e.g. `.env`)
are protected via `SENSITIVE_FILENAMES` / `_assert_not_sensitive` in
`backend/app/api/v1/routers/files.py` (case-insensitive match returning `403`).
Standard server configuration files (`server.properties`, `eula.txt`) are
editable by authorized server managers.

### Permission Strings

Permission strings follow the `<resource>:<action>` format. Defined in `contracts/permissions.yaml`.

Global permissions (checked by `require_permission`):

| Permission | Description | Scope |
|---|---|---|
| `server:read` | View server details, status, host runtime snapshot | `global` |
| `server:write` | Create/manage servers (config, import/scan, reconcile, runtime claim) | `global` |
| `server:delete` | Delete a server | `global` |
| `server:create` | Create a server (creator becomes `owner_id`) | `global` |
| `backup:create` | Create backups | `global` |
| `backup:restore` | Restore from backup | `global` |
| `backup:delete` | Delete backups | `global` |
| `backup:read` | Verify a backup | `global` |
| `plugin:manage` | Enable/disable/uninstall plugins + marketplace | `global` |
| `user:write` | Create/update users, manage API keys, issue invitations | `global` |
| `user:delete` | Delete users | `global` |
| `settings:read` | View system settings | `global` |
| `settings:write` | Modify system settings | `global` |
| `global.settings` | Modify schedules and alert-rule stubs | `global` |
| `admin:full` | Unrestricted access | `global` |

Server-scoped permission nodes (checked by `require_server_permission`):

| Node | Description |
|---|---|
| `server.{id}.view` | Read server detail, console, runtime diagnostics, health/metrics |
| `server.{id}.power` | Start/stop/restart the server |
| `server.{id}.console` | Send console commands |
| `server.{id}.files` | List/read/write/upload/delete server files |
| `server.{id}.settings` | Manage per-server alert rules |
| `server.{id}.backup`, `server.{id}.players` | Reserved nodes (granted by `admin`/`dev` roles) |

### Role Definitions

Global instance roles (defined in `contracts/permissions.yaml`):

| Role | Permissions | Typical User |
|---|---|---|
| `viewer` | `server:read`, `backup:read`, `plugin:read` | Read-only monitoring |
| `operator` | `server:read`, `server:write`, `server:start`, `server:stop`, `backup:read`, `backup:create`, `plugin:read`, `plugin:install`, `plugin:manage` | Day-to-day server management |
| `admin` | `admin:full` (unrestricted) | System administration |
| `owner` | `owner` role + `global.*` claims (granted at bootstrap) | The single instance Owner |

Server-scoped membership roles (granted via `server_memberships` /
invitations; `SERVER_ROLE_PERMISSIONS` in `backend/app/api/deps.py`):

| Role | Permission nodes |
|---|---|
| `admin` | `server.{id}.*` (all) |
| `dev` | `server.{id}.view|power|console|files|backup|players|settings` |
| `viewer` | `server.{id}.view` |

Owners bypass server-scoped checks entirely (`require_server_permission`
short-circuits for `owner_id`, `admin:full`, `global.*`,
`global.servers.manage`).

### Access mode & invitations

The instance starts **uninitialized**; protected routes are blocked until
`POST /api/v1/setup/bootstrap` creates the Owner (single-use; `409` once
initialized). `GET /api/v1/setup/status` reports
`initialized` / `access_mode` / `user_count` publicly for the setup wizard.

- **`LOCAL`** (default): `POST /api/v1/users` allows open self-registration
  (new users get the `viewer` role).
- **`GLOBAL`**: open self-registration is disabled with `403`; users register
  through invitations — `POST /api/v1/invites/accept` with a token from
  `POST /api/v1/invites`.

The mode flips via `PUT /api/v1/setup/access-mode` (Owner/`global.*` only).
Invitation tokens are stored as SHA-256 hashes (`invitations.token_hash`);
lifecycle status is `ACTIVE` / `USED` / `REVOKED` / `EXPIRED`. See
`docs/history/features/owner-invite-system-roadmap.md` for the original design.

### ABAC Context Rules

`PermissionEvaluator.evaluate_abac()` defines resource-ownership and
scope-enforcement rules. In the current request path the server-scoped
equivalents are enforced directly by `require_server_permission` (owner via
`ServerModel.owner_id`, members via `ServerMembershipModel` roles) rather than
through the generic evaluator.

### WebSocket channel authorization

The WebSocket handshake validates the JWT **before** `accept()` (`backend/app/websocket/endpoint.py:51-62`), and per-channel authorization is checked at subscribe time (`ChannelAuthorizer.can_subscribe`). **WebSocket channel delivery is fully functional (Phase 3 resolved):** per-channel authorization enforces singular REST permissions (`server:read`, `backup:read`, etc.) with `admin:full` bypass (fixed in commit `b98da77`). Frontend `WebSocketManager` handles active channel subscriptions on route change (commit `d096f75`), and `MetricsBridgeHandler` flushes real-time metrics push events every ~2s over WebSocket (commit `db1889d`).

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
