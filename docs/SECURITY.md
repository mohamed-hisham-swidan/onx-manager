# Security Architecture

This document describes the authentication, authorization, audit, data protection, rate limiting, and session management systems. Cross-reference: `Implementation/Shared/Contracts/permissions.yaml` for the full permission and role definitions, `Implementation/Batch-08/DECISIONS.md` for design rationale.

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
| Access token | 15 minutes | In-memory (not localStorage) | Short-lived, stateless |
| Refresh token | 7 days | httpOnly cookie + DB (SHA-256 hash) | Individually revocable, rotated on use |

### Refresh Token Rotation

- Opaque 48-byte random tokens stored as SHA-256 hash in the database
- Each refresh operation revokes the old token and issues a new one
- DB storage enables immediate revocation — logout endpoint revokes by hash lookup
- Refresh without a valid token returns HTTP 401
- One refresh token per session

### API Keys

- Prefix: `mcs_`
- Storage: Argon2id hash — never stored in plaintext
- Display: Shown once at creation, never retrievable afterward

### Login Flow

```
1. Client sends credentials → /auth/login
2. Server validates credentials (Argon2id password verification)
3. Server generates access token (RS256, 15 min TTL)
4. Server generates opaque refresh token, stores SHA-256 hash in DB
5. Returns access token in body, refresh token in httpOnly cookie
6. Client uses access token for API calls (Authorization: Bearer <token>)
7. On expiration, client calls /auth/refresh with httpOnly cookie
8. Server rotates refresh token, issues new access token
```

---

## Authorization

### Model: RBAC + ABAC Hybrid

The authorization system uses Role-Based Access Control as the primary model with Attribute-Based Access Control extensions for resource-level checks.

**Flow**:

1. `PermissionEvaluator` checks role permissions first (RBAC)
2. Applies context rules such as resource ownership (ABAC)
3. Inactive users are rejected at evaluation time
4. All API endpoints check permissions before executing

### Permission Strings

Permission strings follow the `<resource>:<action>` format. Defined in `Implementation/Shared/Contracts/permissions.yaml`.

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

The ABAC extension evaluates resource-specific attributes:

- **Resource ownership**: A user can modify a resource if they are the `resource_owner_id`
- **Scope enforcement**: Server-scoped permissions (`server_id`) only apply to specific server resources; global-scoped permissions apply system-wide

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

- The database user has no `UPDATE` or `DELETE` privileges on audit tables
- Periodic chain integrity verification runs automatically

### Query Format

```
GET /audit?from=<ISO_timestamp>&to=<ISO_timestamp>&actor=<user_id>&action=<action_type>
```

Response includes each log entry with its hash, previous hash, and chain position for independent verification.

---

## Data Protection

### Encryption at Rest

| Data | Method |
|---|---|
| Backups | AES-256-GCM |
| Passwords | Argon2id (memory-hard, GPU-resistant) |
| API keys | Argon2id hash, never stored in plaintext |

### TLS

All communications use TLS 1.3. Protocol downgrade is rejected at the reverse proxy level.

### Secrets Management

- Secrets are loaded from environment variables or HashiCorp Vault
- **Never** hardcoded in source code, configuration files, or documentation
- Production deployments must use persistent key material (see JWT keys above)

---

## Rate Limiting

### Architecture

Rate limiting operates at two layers:

| Layer | Scope | Mechanism |
|---|---|---|
| Reverse proxy (nginx) | Global per-IP | Token bucket |
| Application | Per-user, per-endpoint | Token bucket |
| WebSocket | Per-connection message rate | 50 messages/second |

### Per-Route Limits

Route categories and their default limits:

| Route Category | Limit | Window |
|---|---|---|
| Authentication (`/auth/*`) | 10 requests | 1 minute |
| API endpoints | 100 requests | 1 minute |
| WebSocket messages | 50 messages | 1 second |

### Response Headers

All rate-limited endpoints return the following headers:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 87
X-RateLimit-Reset: 1627000000
```

On breach, the API responds with `429 Too Many Requests` and a `Retry-After` header.

---

## Session Management

### Session Tokens

- One refresh token per active session
- Stored as SHA-256 hash in the database
- Bound to a specific user agent and IP (optional, configurable)
- Rotated on each refresh — old token is revoked, new token is issued

### Revocation

| Mechanism | Scope | Method |
|---|---|---|
| User logout | Current session | Deletes refresh token by hash lookup |
| Admin force logout | All sessions for a user | Deletes all refresh tokens for that user |
| Token rotation | Single refresh | Old token hash replaced by new token hash |

### Inactive Session Cleanup

- Expired refresh tokens (past 7-day TTL) are pruned periodically
- No active session data survives token expiry

---

See `docs/API.md` for endpoint security details and `docs/ARCHITECTURE.md` for system-level security boundaries.
