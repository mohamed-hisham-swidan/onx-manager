# BATCH 7.1 — DESIGN SPECIFICATION
# Data Model + API Contract Design (DESIGN ONLY — NO IMPLEMENTATION)

**Status:** DESIGN READY FOR REVIEW
**Date:** 2026-08-13
**Authoritative Phase-7 roadmap:** `docs/roadmap/MCS-Manager-Phase7-Network-Access-Roadmap-v3.1.md` — its internal status is **v3.2** and it records the Batch 7.0 RECON results and the three Phase 7.1 design decisions. (The task brief referenced `...v3.2.md`; no file by that exact name exists in the repo — the v3.1-named file is the authoritative one. This is a reference clarification, not a design change.)
**Base / prerequisite:** Phase 4 (Owner / Invitation / RBAC / Access Mode system) — COMPLETE. Files API IDOR — VERIFIED CLOSED (Batch 7.0 RECON).
**Batch 7.1 does NOT implement anything.** No code, no migrations, no routes, no frontend, no contracts changes are authorized in this batch.

---

## 1. Scope

Batch 7.1 designs, **and only designs**:

- The exact database schema for `host_playit_agent`, `server_exposure`, `server_exposure_target`, `panel_exposure`, and the explicit exposure-grant table `server_exposure_grants`.
- Exact state machines (enums + transitions + deterministic aggregate precedence).
- Exact authorization matrix (five permission strings + role boundaries).
- Exact REST API contracts (routes, request/response schemas, status codes, idempotency, concurrency).
- AES-GCM secret/credential contract via the existing `BackupEncryption`.
- Conceptual migration plan (no Alembic file).
- Domain / CQRS / repository plan reusing existing patterns.
- Test plan (design only, no tests written).
- Documentation/contracts impact list for later implementation batches.

Batch 7.1 explicitly does **NOT** implement: provider mechanics (Cloudflare, playit agent supervision, UPnP), any frontend UI, any Phase 8 (DNS) work, any change to `access_mode` semantics.

---

## 2. Locked Decisions (from v3.2 — DO NOT CHANGE)

1. **Credential encryption: AES-GCM** — reuse `BackupEncryption` / `load_or_create_backup_key` from `backend/app/modules/storage/encryption.py`. Fernet (`core/security.py`) is **excluded** for Phase 7 credentials.
2. **Exposure target scope v1 = JAVA GAME PORT ONLY.** Valid target port = `ServerModel.port` (the authoritative game port). Protocol = `tcp`. `service_type = java`. **No `server_registered_ports` table in 7.1.** Bedrock and companion ports deferred. BlueMap / Simple Voice Chat are not auto-exposable.
3. **UPnP library: `aioupnp`**, added **only at Batch 7.3b** implementation; not in 7.1 schema or dependencies.
4. **Access Mode = MODEL B.** `system_state.access_mode` stays registration/auth policy only. A separate `panel_exposure` controls network exposure. Changing `access_mode` never starts/stops exposure; exposure changes never touch `access_mode`.
5. Phases 8, 9, 11 are OUT OF SCOPE.
6. Existing authorization boundaries must never be weakened. No inference of exposure privileges from roles, `server.{id}.settings`, or `global.settings`.

---

## 3. Entity Model

Conventions (verified from repo):
- IDs: `String(36)` primary keys (UUID hex). Instance-level singletons use `id = "default"` (exactly like `SystemStateModel`).
- Timestamps: `TimestampMixin` (`created_at`/`updated_at`, `DateTime(timezone=True)`, server default `CURRENT_TIMESTAMP`).
- Enum values stored as **uppercase strings** in `String` columns (matching `LOCAL`/`GLOBAL` on `system_state`); enums are defined in the domain layer and their `.value` is persisted.
- FKs use `ondelete="CASCADE"` (matching `server_memberships` / `invitations` conventions).
- Model files live in a new module `backend/app/modules/exposure/infrastructure/models.py`; `Base` from `app.core.persistence.base`.

### 3.1 HostPlayitAgent — instance-level singleton

**Purpose:** one playit agent + one secret key pair per MCS Manager instance. **No `server_id`.**

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| `id` | String(36) PK | no | `"default"` | Singleton row, lazily created by repository (mirrors `SystemStateModel`) |
| `secret_ciphertext` | LargeBinary | yes | NULL | AES-GCM(nonce\|ciphertext) of the playit secret key; NULL → not claimed |
| `claim_code` | String(255) | yes | NULL | Transient; present only during an in-progress claim |
| `claim_expires_at` | DateTime(tz) | yes | NULL | Transient; bounded claim window |
| `process_status` | String(16) | no | `"STOPPED"` | `STOPPED \| STARTING \| RUNNING \| STOPPING \| ERROR` (live, reconciled) |
| `last_health_at` | DateTime(tz) | yes | NULL | Last successful provider inventory query |
| `desired_agent_running` | Boolean | no | `false` | **DERIVED cache** — recomputed, never authoritatively written by a handler |
| `created_at` / `updated_at` | per mixin | no | now | — |

**Authoritative `desired_agent_running` semantics:**
```
desired_agent_running ⇔ EXISTS(ServerExposure e
                 WHERE e.method = 'playit' AND e.desired_state = 'ENABLED')
```
- It is derived at read/reconcile time; the column is a cache only. The EXISTS expression is the single source of truth.
- **Credential removal:** `secret_ciphertext = NULL`, claim fields cleared, `process_status = STOPPED`, every playit target → `CLAIM_REQUIRED`. Never re-claims automatically.
- **Agent crash** (while ≥1 playit target ENABLED): supervisor restarts with bounded backoff; enabled targets show `STARTING` → `ACTIVE` or `ERROR` per health evidence.
- **Host restart:** startup reconcile recomputes `desired_agent_running` from persisted `desired_state` rows. ENABLED → start agent + re-establish; DISABLED → stay stopped; failures surface as `ERROR`, never a silent flip to `ACTIVE` (Core Principle #5).

**Claim data persistence decision — DECIDED:** `claim_code` and `claim_expires_at` ARE persisted (transient-sensitive), per roadmap §6c.2. Lifecycle:
- On `POST .../agent/claim`: generate claim, set `claim_code` + `claim_expires_at`.
- On successful exchange (secret verified and stored) AND on `reset` AND on `credentials/remove`: clear `claim_code` + `claim_expires_at`.
- On expiry (exchange timeout): stay in `CLAIM_REQUIRED`, allow a new claim (fields overwritable).

### 3.2 ServerExposure — per-server config

**Purpose:** exactly one exposure config per server, exactly one method.

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| `id` | String(36) PK | no | — | — |
| `server_id` | String(36) FK→`servers.id` CASCADE | no | — | **UNIQUE** — one exposure per server per policy |
| `method` | String(16) | no | — | `playit \| port_forward \| cloudflare_tcp` (**never** `none`; see §3.2 note) |
| `desired_state` | String(16) | no | `"DISABLED"` | `ENABLED \| DISABLED` — persisted user intent |
| `aggregate_status` | String(32) | no | `"DISABLED"` | **Derived cache** — recomputed by precedence, never accepted as write input |
| `created_at` / `updated_at` | per mixin | no | now | — |

**Uniqueness (decision):** `server_id UNIQUE`. Roadmap Core Principle #7 (one exposure method per server) + §2 decisions → a server has at most one active method. Repository evidence (`SystemStateModel`, `server_memberships` patterns) supports a unique FK.

**"Not exposed" representation — DECIDED:** absence of a `ServerExposure` row = not exposed (default). `method='none'` is **not persisted**; the network-equivalent of "none" is either (a) no row, or (b) a row with `desired_state='DISABLED'`. To return a server to "none", `DELETE` the exposure row (idempotent). The API accepts/returns `method` values from `playit | port_forward | cloudflare_tcp` only.

**Deletion behavior:** `ON DELETE CASCADE` cascades to `server_exposure_target` rows. When a server is deleted, its exposure + targets + grants cascade away.

### 3.3 ServerExposureTarget — per-target state under an exposure

**Purpose:** live per-port state under a server's single exposure.

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| `id` | String(36) PK | no | — | — |
| `exposure_id` | String(36) FK→`server_exposure.id` CASCADE | no | — | Indexed |
| `protocol` | String(8) | no | `"tcp"` | v1: `tcp` only |
| `service_type` | String(16) | no | `"java"` | v1: `java` only |
| `local_port` | Integer | no | — | **MUST equal the owning server's `ServerModel.port`** (authoritative, server-side validated) |
| `public_address` | String(512) | yes | NULL | Provider-assigned publicly once ACTIVE |
| `status` | String(32) | no | `"DISABLED"` | 9-state vocabulary (§4) |
| `error_code` | String(64) | yes | NULL | structured e.g. `PLAYIT_QUOTA_EXCEEDED` |
| `error_message` | Text | yes | NULL | provider/CLI message for UI display |
| `created_at` / `updated_at` | per mixin | no | now | — |

**Uniqueness (decision):** `UNIQUE(exposure_id, service_type, protocol)` — one target per (exposure, service type, protocol). In v1 exactly one (`java`,`tcp`) target is possible per exposure → satisfies "exactly one java target per server" while preserving the future-ready 1–N multi-target architecture. `local_port` is intentionally NOT part of the key.

**Target ownership / port source (decisions):**
- A target is owned by exactly one exposure (FK `exposure_id`); the exposure is owned by exactly one server.
- `local_port` is not user-enterable in the schema; it is derived from the owning server's `ServerModel.port` at creation and re-validated on reconcile. No arbitrary ports (roadmap §4.3 critical rule).
- Deny-list is enforced **server-side** at target creation AND at reconcile (RCON 25575 default, Panel HTTP/bind port, DB ports, metrics, any management/internal API port, any port not equal to `ServerModel.port`).

### 3.4 PanelExposure — instance-level singleton

**Purpose:** the separate Panel exposure switch (**MODEL B**). Never overrides or reads `access_mode`.

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| `id` | String(36) PK | no | `"default"` | Singleton (mirrors `SystemStateModel`) |
| `method` | String(32) | no | `"none"` | `none \| cloudflare_tunnel \| playit_http \| port_forward` |
| `desired_state` | String(16) | no | `"DISABLED"` | `ENABLED \| DISABLED` |
| `status` | String(32) | no | `"DISABLED"` | 9-state vocabulary (§4) |
| `public_address` | String(512) | yes | NULL | — |
| `error_code` | String(64) | yes | NULL | e.g. `RECLAIM_REQUIRED`-triggering revocation evidence |
| `error_message` | Text | yes | NULL | — |
| `created_at` / `updated_at` | per mixin | no | now | — |

**Phase 7.2 methods are designed here, not implemented here.** `cloudflare_tunnel` (Batch 7.2a), `playit_http` + `port_forward` (Batch 7.2b) map to the same rows; upstream credential revocation surfaces `RECLAIM_REQUIRED` (§6b, "never a silent retry loop").

### 3.5 server_exposure_grants — explicit exposure grants

**Purpose:** the explicit, deliberate grant mechanism for server-scoped exposure (roadmap §8.6: "no inference from roles"). Phase 4 `server_memberships.role` grants **nothing** by itself.

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| `id` | String(36) PK | no | — | — |
| `server_id` | String(36) FK→`servers.id` CASCADE | no | — | — |
| `user_id` | String(36) FK→`users.id` CASCADE | no | — | — |
| `can_manage` | Boolean | no | `false` | grants `server.{id}.exposure` |
| `can_view` | Boolean | no | `false` | grants `server.{id}.exposure.view` |
| `created_at` / `updated_at` | per mixin | no | now | — |

`UNIQUE(server_id, user_id)`. The server **Owner** (`servers.owner_id`) bypasses via the existing `require_server_permission` owner short-circuit — no grant row needed for the owner.

---

## 4. State Model

### 4.1 Enums (exact — roadmap terminology, no synonyms)

| Entity field | Values (exact) |
|---|---|
| `HostPlayitAgent.process_status` | `STOPPED \| STARTING \| RUNNING \| STOPPING \| ERROR` |
| `ServerExposure.desired_state` | `ENABLED \| DISABLED` |
| `ServerExposureTarget.status` | `DISABLED \| CLAIM_REQUIRED \| STARTING \| ACTIVE \| STOPPING \| STOPPED \| DEGRADED \| ERROR \| RECLAIM_REQUIRED` |
| `ServerExposure.aggregate_status` | same 9-state vocabulary as target status (incl. `DISABLED`) |
| `PanelExposure.desired_state` | `ENABLED \| DISABLED` |
| `PanelExposure.status` | same 9-state vocabulary |
| `ServerExposureTarget.protocol` | v1: `tcp` (`udp`, `both` reserved for future registry) |
| `ServerExposureTarget.service_type` | v1: `java` (`bedrock`, companion reserved) |
| `ServerExposure.method` | `playit \| port_forward \| cloudflare_tcp` |
| `PanelExposure.method` | `none \| cloudflare_tunnel \| playit_http \| port_forward` |
| `error_code` (target/exposure) | structured codes incl. `PLAYIT_QUOTA_EXCEEDED`, `NO_TARGETS` |

### 4.2 Per-target transition rules (v3.1 §6a, objective)

```
DISABLED → CLAIM_REQUIRED → STARTING → ACTIVE → STOPPING → STOPPED
                          ↓            ↓
                       DEGRADED      ERROR
                          ↓            ↓
                    RECLAIM_REQUIRED (credential revoked/reset upstream)
```

Health evidence thresholds: interval 30s; stale >90s → `DEGRADED`; 3 consecutive failed inventory queries → `DEGRADED`; hard failure → `ERROR` immediately; credential revocation → `RECLAIM_REQUIRED` (never silent re-mint); one fully healthy check → back to `ACTIVE`.

### 4.3 Aggregate status — deterministic precedence (v3.1 §6a.2)

`desired_state = DISABLED` → aggregate `DISABLED` (override, regardless of targets).

For `desired_state = ENABLED`, fold all targets with this fixed precedence (highest → lowest):

```
RECLAIM_REQUIRED > CLAIM_REQUIRED > ERROR > DEGRADED > STOPPING > STARTING > ACTIVE > STOPPED
```

Exact cases (must hold):

| Target state(s) | Aggregate |
|---|---|
| `desired_state=DISABLED`, any targets | `DISABLED` |
| 1× `CLAIM_REQUIRED` + 1× `ACTIVE` | `CLAIM_REQUIRED` |
| 1× `ERROR` + 1× `ACTIVE` | `ERROR` |
| 1× `DEGRADED` + 1× `ACTIVE` | `DEGRADED` |
| 1× `STARTING` + 1× `ACTIVE` | `STARTING` |
| 1× `RECLAIM_REQUIRED` + 1× `ACTIVE` | `RECLAIM_REQUIRED` |
| 1× `STOPPING` + 1× `ACTIVE` | `STOPPING` |
| all `ACTIVE` | `ACTIVE` |
| all `ERROR` | `ERROR` |
| no targets + `desired_state=DISABLED` | `DISABLED` (normal) |
| no targets + `desired_state=ENABLED` | Contract violation → `ERROR` + `error_code=NO_TARGETS`. API rejects enabling with zero targets. |

**Source of truth:** per-target `status` + `desired_state`, folded by the precedence table **at read time**. `aggregate_status` is a derived cache only; never accepted as write input, never authoritative. **No frontend invents precedence.**

`desired_agent_running` authority is the separate EXISTS expression (§3.1).

---

## 5. Authorization Matrix

Permission strings are the v3.1 §8.6 design contracts. **They do not exist in the codebase today** (verified: no `exposure` node in `deps.py`, `contracts/permissions.yaml`, or any model). Batch 7.1 **designs** their enforcement; later implementation registers them as `enforced`.

| ACTION | REQUIRED PERMISSION | Default grantee |
|---|---|---|
| Read host agent status / trigger agent reconcile | `exposure.credentials.manage` | **Owner only** |
| Generate claim link (`POST .../agent/claim`) | `exposure.credentials.manage` | **Owner only** (+ 5/hour rate limit, §8) |
| Reset playit agent | `exposure.credentials.manage` | **Owner only** |
| Remove credentials | `exposure.credentials.manage` | **Owner only** |
| View claim code / claim link | `exposure.credentials.manage` | **Owner only** (a claim link = account authorization) |
| Create/update/delete a game exposure for server X | `server.{id}.exposure` | Server Owner + users with `server_exposure_grants.can_manage` |
| Enable/disable a server's exposure | `server.{id}.exposure` | same |
| View exposure state / public address for server X | `server.{id}.exposure.view` | Server Owner + users with `server_exposure_grants.can_view` |
| Stop all exposures | `exposure.global.stop` | **Owner only** |
| Manage Panel exposure | `exposure.panel.manage` | **Owner only** |
| View/update Panel exposure state | `exposure.panel.manage` | **Owner only** |

**Role semantics (explicit):**

- **Owner** (`servers.owner_id`): full server exposure rights via existing `require_server_permission` owner short-circuit; full instance rights (`exposure.*`) via `require_owner()` / `global.*`.
- **Explicitly granted server exposure role**: users holding an `server_exposure_grants` row (`can_manage` → write, `can_view` → view-only).
- **Viewer/read-only**: only if an explicit `can_view` grant exists. Never inferred.
- **Admin/global roles**: `admin:full` / `global.*` / `global.servers.manage` continue to short-circuit `require_server_permission` (existing behavior). **But `global.settings` does NOT grant `exposure.panel.manage`; `server.{id}.settings` does NOT grant `server.{id}.exposure`** (roadmap §8.6 rules that cannot be inferred).

**Sensitivity rule:** claim code, credentials, and reset/remove actions are strictly more restricted than public-address reads. `public_address` → `server.{id}.exposure.view`.

---

## 6. API Contracts

Prefixes: instance/host/panel under `/api/v1/exposure`; per-server under `/api/v1/servers/{server_id}/exposure` (so the existing `require_server_permission` path/query/body `server_id` extraction is reused). All routes require a bearer token (`401` invalid/missing).

### 6.1 Routes

| # | Method & path | Permission | Request body | Success | Purpose |
|---|---|---|---|---|---|
| 1 | `GET /api/v1/exposure/agent` | `exposure.credentials.manage` | — | 200 `AgentStatusResponse` | host agent status (never secret) |
| 2 | `POST /api/v1/exposure/agent/claim` | `exposure.credentials.manage` | empty | 201 `ClaimResponse` | generate claim code+URL (5/hour) |
| 3 | `POST /api/v1/exposure/agent/reset` | `exposure.credentials.manage` | empty | 200 `AgentStatusResponse` | owner reset (clears secret, playit targets → CLAIM_REQUIRED) |
| 4 | `POST /api/v1/exposure/agent/reconcile` | `exposure.credentials.manage` | optional `{scope}` | 200 `{reconciled: true}` | manual descriptor/reconcile trigger |
| 5 | `POST /api/v1/exposure/stop-all` | `exposure.global.stop` | empty | 200 `{disabled_count}` | DISABLED across all exposures, keeps credentials |
| 6 | `POST /api/v1/exposure/credentials/remove` | `exposure.credentials.manage` | empty | 200 `{success: true}` | wipe secrets, stop agent/tunnel |
| 7 | `GET /api/v1/exposure/panel` | `exposure.panel.manage` | — | 200 `PanelExposureResponse` | panel exposure state |
| 8 | `PUT /api/v1/exposure/panel` | `exposure.panel.manage` | `PanelExposureUpdateRequest` | 200 `PanelExposureResponse` | set method + desired_state (idempotent) |
| 9 | `GET /api/v1/servers/{server_id}/exposure` | `server.{id}.exposure.view` | — | 200 `ServerExposureResponse` | exposure + aggregate + targets |
| 10 | `PUT /api/v1/servers/{server_id}/exposure` | `server.{id}.exposure` | `ServerExposureUpdateRequest` | 200 `ServerExposureResponse` | create/update exposure (method+desired_state) |
| 11 | `PATCH /api/v1/servers/{server_id}/exposure` | `server.{id}.exposure` | `{desired_state}` | 200 `ServerExposureResponse` | enable/disable (idempotent transition) |
| 12 | `DELETE /api/v1/servers/{server_id}/exposure` | `server.{id}.exposure` | — | 204 | remove exposure config (→ not exposed) |
| 13 | `GET /api/v1/servers/{server_id}/exposure/targets` | `server.{id}.exposure.view` | — | 200 `[TargetResponse]` | list targets |
| 14 | `POST /api/v1/servers/{server_id}/exposure/targets` | `server.{id}.exposure` | `TargetCreateRequest` | 201 `TargetResponse` | create the java target (validates port + deny-list) |

Routes 2–6, 8 are instance/Owner actions → `require_owner()`-style guard for `exposure.*` (mirror `require_owner` semantics; roles do not infer). Routes 9–14 use `require_server_permission(...)` + new exposure-grant checks.

### 6.2 Schemas (Pydantic)

- `AgentStatusResponse`: `{ claimed: bool, process_status, desired_agent_running, last_health_at, claim_active: bool, claim_expires_at }` — **never** includes `secret_ciphertext` or full `claim_code`; `claim_active` is a boolean only.
- `ClaimResponse`: `{ claim_code, claim_url, expires_at }` — returned ONLY here, ONLY on generation, Owner-only.
- `PanelExposureResponse`: `{ method, desired_state, status, public_address, error_code, error_message }`.
- `PanelExposureUpdateRequest`: `{ method: none|cloudflare_tunnel|playit_http|port_forward, desired_state: ENABLED|DISABLED }`.
- `ServerExposureResponse`: `{ server_id, method, desired_state, aggregate_status, targets: [TargetResponse], error_code, error_message }` — `aggregate_status` derived server-side.
- `ServerExposureUpdateRequest`: `{ method: playit|port_forward|cloudflare_tcp, desired_state: ENABLED|DISABLED }`. Enabling with zero targets → **422** (`NO_TARGETS` contract violation); the implementation auto-creates the single `java/tcp` target from `ServerModel.port` on enable (Flow 1). `port_forward` (game) is valid schema now but the provider mechanics land in Batch 7.3b.
- `TargetCreateRequest`: `{ }` (no user port). Server identifies `ServerModel.port`. Body is intentionally minimal so clients cannot submit arbitrary ports.
- `TargetResponse`: `{ id, exposure_id, protocol, service_type, local_port, public_address, status, error_code, error_message }`.

### 6.3 Status codes

| Code | Meaning |
|---|---|
| `401` | Missing/expired/invalid bearer token |
| `403` | Authenticated but missing the required permission / no grant |
| `404` | Server, exposure, agent, or target not found |
| `409` | Conflict (enabled already, or disabling already disabled when a state transition is required; claim already active under a different idempotency key) |
| `422` | Validation (bad enum, `NO_TARGETS`, port mismatch, deny-list hit) |
| `503` | Provider/infra unavailable (reconciler, agent subprocess), `retryable` |

### 6.4 Idempotency behavior

All mutating commands carry `IdempotencyKey` (existing `Command`/`IdempotencyMiddleware`, 24h TTL store).

| Situation | Behavior |
|---|---|
| Enable when already `ENABLED` | 200, no-op, idempotent (`desired_state` already matches) |
| Disable when already `DISABLED` | 200, no-op, idempotent |
| `PATCH` same `desired_state` replayed | same result via idempotency key |
| Reset while a reset ran | idempotency key returns the first result; a distinct reset re-runs safely (singleton row lock) |
| Claim while another claim active | 409 `CLAIM_ACTIVE` (unless same idempotency key → returns existing claim) |
| `DELETE` exposure already absent | 204 (idempotent) |
| `PUT` panel same values | 200, no-op |

### 6.5 Concurrency behavior

| Scenario | Rule |
|---|---|
| Two simultaneous exposure mutations (same server) | Serialized by the UoW transaction on the single `ServerExposure` row; second writer sees post-commit row (SQLite serializes; Postgres use `SELECT ... FOR UPDATE` on the row) |
| Two simultaneous target reconciliations | Host agent row (singleton `id='default'`) used as an in-process/DB mutex → reconcile is single-flight |
| Enable + Disable racing | Last committed `desired_state` wins; aggregate recomputed from the persisted state |
| Agent crash during reconcile | Reconciler restarts with bounded backoff; targets pass `STARTING` → `ACTIVE`/`ERROR`; never silently `ACTIVE` |
| Credential rotation during active tunnel | Rotation = reset: secret cleared, tunnel torn down, targets → `CLAIM_REQUIRED`; no re-claim without user action |

No Phase 8 (DNS) routes are added.

---

## 7. Secret / Credential Contract

- **Storage:** `secret_ciphertext` holds `BackupEncryption.encrypt(secret_bytes)` = `nonce(12B) + ciphertext` (AES-256-GCM). `secret_bytes = provider_secret.encode('utf-8')`. Decryption via `get_backup_encryption()` dependency (already wired in `deps.py`). Key lifecycle: `load_or_create_backup_key(settings.backup_encryption_key_path)` — one production-wired key flow.
- **Never stored:** plaintext provider secret; a long-lived claim code after successful exchange; API responses never contain `secret_ciphertext` or plaintext secret.
- **Client storage:** claim links/tokens are **never** persisted in `localStorage`/`sessionStorage` by the frontend; they are displayed transiently and discarded.
- **Response policy:**
  - `claim_code`/`claim_url`: returned only by `POST .../claim` to `exposure.credentials.manage` holders; never in list/status responses.
  - secret: **never** returned after persistence.
  - `public_address`: returned by per-server GET routes behind `server.{id}.exposure.view`; NOT returned by `GET /api/v1/exposure/agent` (instance-level, no address — it holds no per-server address).
- **AAD:** use `aad=None` (default) for the playit/CF secrets to match the backup-encryption call pattern; no cross-context AAD invented in 7.1.

---

## 8. Migration Plan (conceptual only — NO Alembic file)

**Revision:** single new revision whose `down_revision = a957791492a7` (current head). Version floor for the release bumps to the new head (per `db_revision.py` policy).

**Tables (create):**
1. `host_playit_agent` — §3.1 columns. `id` PK default `"default"`. `secret_ciphertext` LargeBinary nullable.
2. `server_exposure` — §3.2. `server_id` FK→`servers.id` ON DELETE CASCADE, **UNIQUE**, index. `method` CHECK in (`playit`,`port_forward`,`cloudflare_tcp`). `desired_state` default `DISABLED`. `aggregate_status` default `DISABLED`.
3. `server_exposure_target` — §3.3. `exposure_id` FK→`server_exposure.id` ON DELETE CASCADE, index. `protocol`/`service_type` defaults `tcp`/`java`. **UNIQUE(exposure_id, service_type, protocol)**. `status` default `DISABLED`. `local_port` NOT NULL (validated server-side; DB CHECK 1..65535).
4. `panel_exposure` — §3.4. `id` PK default `"default"`. `method` default `none`, `desired_state`/`status` default `DISABLED`.
5. `server_exposure_grants` — §3.5. FKs → `servers`/`users` CASCADE. **UNIQUE(server_id, user_id)**. `can_manage`/`can_view` default `false`.

**Indexes/FKs/delete behavior:** FK indexes on `server_exposure.server_id` (unique), `server_exposure_target.exposure_id` (plain), `server_exposure_grants.server_id`/`user_id` (unique pair). All child FKs `ON DELETE CASCADE`.

**Existing-data initialization:** **NO exposure rows are created for existing servers.** Existing servers get zero `server_exposure` / `server_exposure_target` / `server_exposure_grants` rows. The two singleton rows (`host_playit_agent`, `panel_exposure`) are created lazily by their repositories (matching `SystemStateModel` lazy creation at `auth/infrastructure/repository.py:190-198`) with defaults = not claimed / `none` / `DISABLED`.

**Backward compatibility:** pure additive — no existing column/table altered, no dropped data. `servers`, `system_state`, `server_memberships` untouched.

**Post-migration state:** all new exposure records default `desired_state=DISABLED`; nothing is auto-enabled.

---

## 9. Domain / CQRS / Repository Plan

**New module:** `backend/app/modules/exposure/` mirroring the `server` module structure. Reuses `Base`/`TimestampMixin`, `UnitOfWork`, `CommandBus`/`QueryBus`, `IdempotencyKey`, `BaseRepository`, and the CQRS hand registration in `app/registration.py`.

- **domain/aggregate.py** — `HostPlayitAgent`, `ServerExposure` (child: `ServerExposureTarget`), `PanelExposure` aggregates. The **ServerExposure aggregate owns lifecycle validation**: enable requires ≥1 target (rejects `NO_TARGETS`), method-change validation, target port equality (`== ServerModel.port`), deny-list checks, state-transition guards (`_transition_to` pattern like `Server`).
- **domain/value_objects.py** — `ExposureMethod`, `DesiredState`, `ExposureStatus`, `TargetProtocol`, `ServiceType`, `PrecedenceOrder`, `AgentProcessStatus`.
- **domain/repository.py** — interfaces `HostAgentRepository`, `ServerExposureRepository`, `PanelExposureRepository`, `ExposureGrantRepository`.
- **application/commands/** — `Create/SetServerExposureCommand`, `EnableServerExposureCommand`, `DisableServerExposureCommand`, `RemoveServerExposureCommand`, `CreateExposureTargetCommand`, `GenerateClaimCommand`, `ResetAgentCommand`, `RemoveCredentialsCommand`, `StopAllExposuresCommand`, `SetPanelExposureCommand`, `ReconcileExposureCommand`. Each handler: authorization already enforced by the route dependency → **domain validation in the aggregate** → **persistence via repository inside `UnitOfWork`** → aggregate-status cache recomputed → events via `uow.add_event`.
- **application/queries/** — `GetServerExposureQuery`, `GetAgentStatusQuery`, `GetPanelExposureQuery`, `ListTargetsQuery`. Queries rebuild the aggregate and **derive `aggregate_status` / `desired_agent_running` at read time** via the precedence function / EXISTS.
- **application/reconciliation.py** — `ReconcileExposureService`: recomputes `desired_agent_running` (EXISTS), folds aggregate cache, drives the supervisor seam. `desired_agent_running` derivation + aggregate precedence live here and in the read path (single source).
- **infrastructure/models.py + repository.py** — SQLAlchemy models (§3) + SQL repositories wrapping them.

**Responsibility split:**
- **Authorizé**: route dependency (`require_server_permission` + exposure-grant check; `exposure.*` → owner guard).
- **Domain validation**: aggregate (method, target port, deny-list, transitions, NO_TARGETS).
- **Persistence**: SQL repository under `UnitOfWork`.
- **Status derivation**: pure function + EXISTS in application layer (read & reconcile paths).
- **Provider reconciliation**: belongs to the supervisor seam (Batch 7.2a/7.3a). 7.1 defines the interface + the derived-state machinery only.

---

## 10. Test Plan (design only — no tests written in this batch)

Backend integration tests (new `backend/tests/api/test_exposure_*.py` + command tests):

1. default = no exposure (fresh server → GET exposure 404 / no row)
2. owner enables exposure (playit) → row created, target auto-created from `ServerModel.port`, aggregate `STARTING`/`ACTIVE` path
3. non-owner / non-granted user → 403
4. viewer with explicit `can_view` grant → read-only state OK; write 403
5. server exposure cannot target another server's port (port mismatch rejected)
6. arbitrary port rejected (deny-list / port ≠ `ServerModel.port`)
7. Java port accepted (exactly `ServerModel.port`)
8. disabled exposure never creates an active target
9. aggregate precedence → table-driven over all §4.3 rows (incl. mixed-state cases)
10. claim-required behavior (unclaimed → target `CLAIM_REQUIRED`)
11. reclaim-required behavior (upstream revocation → `RECLAIM_REQUIRED`)
12. credential removal (secret cleared, agent stopped, targets → `CLAIM_REQUIRED`)
13. claim expiration (expired claim → new claim allowed)
14. agent desired-state derivation (EXISTS over playit ENABLED exposures)
15. concurrent enable/disable (last-commit-wins, no deadlock)
16. idempotent enable (same `desired_state` → 200 no-op)
17. idempotent disable
18. secret never returned (assert no `secret_ciphertext`/plaintext in any response)
19. public-address permission (`server.{id}.exposure.view` gating)
20. cross-server isolation (server A grant cannot read server B exposure)
21. access-mode changes do not affect exposure (flip LOCAL↔GLOBAL → exposure unchanged)
22. exposure changes do not affect access-mode (`system_state.access_mode` untouched)

Host-level tests:
23. last playit target disabled → `desired_agent_running=false`
24. first enabled target → `desired_agent_running=true`
25. host restart reconciliation (from persisted `desired_state`; DISABLED stays down)
26. agent crash recovery state (`ERROR`/`STARTING` path, no silent ACTIVE)

---

## 11. Documentation / Contract Impact (later implementation batches)

Must-change list (do NOT modify now):

- `contracts/permissions.yaml` — register 5 new permission strings as `enforced`:
  `exposure.panel.manage`, `exposure.global.stop`, `exposure.credentials.manage`,
  `server.{id}.exposure`, `server.{id}.exposure.view`; add 14 new route entries; bump version.
- `docs/API.md` — new exposure section (routes/schemas/status codes from §6).
- `docs/architecture/SECURITY.md` — new surfaces, permission requirements, credential encryption approach, port deny-list, rate limiting (5/hr claims), audit logging, Windows child-subprocess known limitation (§6c.1). **Also fix the stale `:118-120` claim** (writes to `server.properties` are allowed; reads blocked) — scheduled for Batch 7.6.
- `docs/architecture/DATABASE.md` — 5 new tables, new migration revision, ER summary update.
- `docs/current-state.md` — canonical snapshot update when 7.1+ ships.
- Frontend architecture docs — Batch 7.4 (Panel Access UI) / 7.5 (Game Server Exposure UI).

Expected totals: +5 permissions, +14 routes (85 → 99), +1 migration, new UI section (Panel) + new per-server Network/Exposure section + Owner-only actions (Reset agent / Stop all / Remove credentials).

---

## 12. Phase 7.1 → 7.3 Boundary

- **Phase 7.1 (this batch):** schema + domain + contracts ONLY. No provider logic.
- **7.2a:** Cloudflare Panel Exposure (Named Tunnel flow, token intake, `RECLAIM_REQUIRED`).
- **7.2b:** Panel UPnP + playit HTTP alternative (uses `PanelExposure` rows; `port_forward` / `playit_http`).
- **7.3a:** playit Game Server host-agent core (supervision, claim exchange, Assisted Setup; uses `host_playit_agent` + agent seam).
- **7.3b:** UPnP implementation (`aioupnp` dependency added HERE, not 7.1).
- **7.3c/d:** Cloudflare TCP (game) + Bedrock/companion behavior per roadmap (7.3d blocked on companion registry).
- **7.4 / 7.5:** Panel Access UI / Game Server Exposure UI.
- **Phase 8 (OUT OF SCOPE):** Dynamic DNS / endpoint workflows.

Each batch is independently reviewable and never collapsed into one implementation batch.

---

## 13. Design Blockers

None — all roadmap requirements resolve to explicit decisions in this document (§3.5 grant table; §3.1 claim persistence; §3.2 non-persisted `none`; §3.2/§3.3 uniqueness; §8 no-seed migration).

**One flagged choice for reviewer confirmation (not a blocker):** the explicit grant mechanism is a dedicated `server_exposure_grants` table (§3.5) rather than adding columns to `server_memberships`. Rationale: preserves Phase 4 unchanged (no inference), keeps grants decoupled from membership roles, and matches the roadmap's "explicit deliberate grant." If the reviewer prefers grant columns on `server_memberships`, only §3.5/§5/§8/§9 change.

---

## FINAL VERDICT

**DESIGN READY FOR REVIEW**

- No ambiguity in: HostPlayitAgent ownership, `desired_agent_running` authority, ServerExposure uniqueness, target ownership/port source, status precedence/source of truth, secret storage, claim-code visibility, permission strings, owner vs server-role rights, public-address visibility, disable/reset semantics, idempotency, concurrency, migration defaults, Access Mode relation.
- No implementation performed. No migration created. No frontend/API code modified. No commit.