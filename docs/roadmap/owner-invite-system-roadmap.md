# Owner Bootstrap, Access Mode & Invitation System — Engineering Blueprint & Roadmap

**Document Status:** ✅ **IMPLEMENTED** (2026-08-12)
**Date:** 2026-08-11  
**Author:** MCS Manager Engineering Team  
**Prerequisite Base Commit:** `a47daa8` (Phase 4 Authorization & Security Cleanup, alembic head `5e2962848581`)

> **Implementation status:** the design in this document is **shipped**. The
> body below is preserved as the original design intent. Where the shipped
> implementation differs, the implementation is authoritative:
>
> - Router paths are `/api/v1/setup/*` and `/api/v1/invites/*` (not
>   `/api/v1/auth/invites/*`).
> - `POST /api/v1/users` is **not** categorically disabled: it is blocked
>   (`403`) while the instance is uninitialized and while access mode is
>   `GLOBAL`; in `LOCAL` mode it still allows open self-registration (the
>   plan's "permanently disabled" rigid reading does not match the shipped
>   gating — see `docs/API.md` §Users).
> - `POST /api/v1/setup/bootstrap` is single-use and rejects with **`409`**
>   (not `400`) once initialized.
> - Access mode is toggled via `PUT /api/v1/setup/access-mode`
>   (`require_owner()`), **not** via `PATCH /api/v1/settings`.
> - `POST /api/v1/invites`, `GET /api/v1/invites`, and
>   `DELETE /api/v1/invites/{id}` all gate on `require_permission("user:write")`.
> - Frontend: `SetupPage` (`/setup`) and `InvitePage` (`/invite/:token`) are
>   wrapped by `SystemStatusGuard`; `AccessSection` and `InvitationsSection`
>   live in `SettingsPage` under `/settings`.
> - Invitation raw tokens are `mcis_<secrets.token_urlsafe(24)>`; prefix is the
>   first 10 chars (`token_prefix` column), matching the design.
>
> Implemented backend modules: `bootstrap_instance.py`,
> `create_invite.py`, `accept_invite.py`, `list_invites.py`,
> `revoke_invite.py`, `verify_invite.py`, `update_access_mode.py`,
> `get_system_status.py` under `backend/app/modules/auth/application/`;
> routers `setup.py` + `invites.py`; migrations `5e2962848581`
> (`servers.owner_id`, `server_memberships`) and `a957791492a7`
> (`system_state`, `invitations`).

---

## 1. Executive Summary & Vision

MCS Manager is transitioning from an open-registration model to an enterprise-grade, secure access control architecture designed for both self-hosted home-lab deployments (Local Panel) and multi-user VPS / cloud deployments (Global Panel).

Currently, `POST /api/v1/users` is an unauthenticated, unguarded endpoint allowing arbitrary self-registration with empty global roles (`roles = []`). This creates a significant security risk for internet-facing instances.

This blueprint defines the architecture for:
1. **Instance Lifecycle State Machine:** `UNINITIALIZED` (awaiting initial owner setup) → `INITIALIZED` (fully configured & operational).
2. **First-Run Owner Bootstrap:** A single-use setup wizard that claims the instance, provisions the primary Owner user account with full global administrative rights (`admin:full` / `global.*`), configures the Access Mode, and transitions the instance state to `INITIALIZED`.
3. **Access Mode Control (`LOCAL` vs `GLOBAL`):**
   - **`LOCAL` (LAN / Self-Hosted Mode):** Single-owner instance for local network management. Self-registration is strictly disabled; additional users can only be created via direct Owner creation or invitation.
   - **`GLOBAL` (VPS / Remote Management Mode):** Multi-tenant or team management instance. Self-registration is strictly replaced by a cryptographically secure, token-based **Invitation System**.
4. **Invitation Lifecycle & System:** A stateful invitation entity (`CREATED` → `ACTIVE` → `USED` / `EXPIRED` / `REVOKED`) that grants specific global roles/permissions or server memberships upon registration via an invite token.
5. **Seamless Phase 4 Authorization Integration:** Full reconciliation between instance-level global roles (`admin`, `operator`, `viewer`) and the Phase 4 server-scoped RBAC layer (`ServerModel.owner_id`, `ServerMembershipModel`, `require_server_permission`).

---

## 2. Architecture & System Integration

### 2.1 Alignment with Phase 4 Authorization Baseline

The new Owner & Invitation system builds directly on top of the Phase 4 authorization architecture (commit `a47daa8`):

| Component | Phase 4 State | Owner & Invite System Integration |
|---|---|---|
| **Server Ownership** | `ServerModel.owner_id` (nullable FK to `users.id`) | Server creators are automatically assigned as `owner_id`. Global Owner/Admin users bypass per-server checks via `require_server_permission()`. |
| **Server Memberships** | `server_memberships` table (`admin`, `dev`, `viewer`) | Invites can target specific servers, automatically creating a `ServerMembershipModel` row upon invite acceptance. |
| **Global Claims** | `admin:full`, `global.*`, `global.servers.manage`, `global.settings` | The instance Owner account created during Bootstrap receives the `admin:full` and `global.*` permission claims in their JWT. |
| **Permission Dependency** | `require_permission()`, `require_server_permission()` | All invite management and instance setup APIs will be gated using these standard dependencies. |

### 2.2 Role Model Reconciliation

To resolve ambiguity between global instance roles and server-scoped membership roles:

1. **Global Instance Roles (Stored in `roles` & `user_roles`):**
   - **`owner` / `admin` (`admin:full`):** Full instance control. Bypasses all server-scoped checks, can create/delete servers, manage instance settings, create invitations, and manage users.
   - **`member` / `user` (`user:read`, `server:create`):** Standard registered user. Can create servers (becoming `owner_id` of those servers) or accept server invitations.
   - **`read_only` (`viewer`):** Restricted global viewer.
2. **Server-Scoped Membership Roles (Stored in `server_memberships.role`):**
   - **`admin`:** Full administrative control over target server (`server.{id}.*`).
   - **`dev`:** Technical management access (`power`, `console`, `files`, `backup`, `players`, `settings`).
   - **`viewer`:** Read-only access (`server.{id}.view` and file download).

---

## 3. Instance Lifecycle & State Machine

### 3.1 Instance States

```
                 +-------------------+
                 |   UNINITIALIZED   |  (No Owner account exists)
                 +---------+---------+
                           |
                           |  POST /api/v1/setup/bootstrap
                           v
                 +-------------------+
                 |    INITIALIZED    |  (Owner provisioned, operational)
                 +-------------------+
```

1. **`UNINITIALIZED`:**
   - Database has zero users (`SELECT COUNT(*) FROM users == 0`), OR `instance_state.initialized == False`.
   - Access to all protected REST API routes is blocked (except `GET /api/v1/setup/status` and `POST /api/v1/setup/bootstrap`).
   - `POST /api/v1/users` (open registration) returns `403 FORBIDDEN (Instance uninitialized. Run setup bootstrap first.)`.
   - Frontend automatically redirects all traffic to `/setup` (Owner Bootstrap Wizard).

2. **`INITIALIZED`:**
   - Owner user created, `admin:full` role assigned, `instance_state.initialized == True`.
   - REST API operational.
   - Open registration (`POST /api/v1/users`) is **permanently disabled**. Registration requires a valid `invite_token` via `POST /api/v1/auth/invites/accept`.

---

## 4. Access Mode Architecture (`LOCAL` vs `GLOBAL`)

| Feature | `LOCAL` (Self-Hosted / LAN) | `GLOBAL` (VPS / Remote) |
|---|---|---|
| **Intended Environment** | LAN, single-user home lab | Public IP / VPS, team/multi-tenant |
| **Public Registration** | **DISABLED** | **DISABLED** (Requires Invitation) |
| **User Creation** | Owner directly creates users or issues Invites | Invites only (`POST /api/v1/invites`) |
| **Server Creation** | Owner owns all servers | Users can create servers (becoming `owner_id`) |
| **Authentication** | Local login / JWT | JWT + Mandated Secure Password Rules |

Access Mode is configured during Owner Bootstrap and can be toggled in `SettingsPage.tsx` by an Owner user (`PATCH /api/v1/settings`).

---

## 5. Invitation System Lifecycle & Data Model

### 5.1 Invitation State Machine

```
   +---------+     Expires / Revokes     +------------+ / +-----------+
   | CREATED | ------------------------> |  EXPIRED   | / |  REVOKED  |
   +----+----+                           +------------+   +-----------+
        |
        |  Send / Activate
        v
   +----+----+     Accept & Register     +------------+
   | ACTIVE  | ------------------------> |    USED    |
   +---------+                           +------------+
```

### 5.2 Invitation Entity Schema (`invitations` table)

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `String(36)` | Primary Key | Unique invitation ID (UUIDv4) |
| `token_hash` | `String(128)` | Non-nullable, Unique, Indexed | SHA-256 hash of secret invite token |
| `token_prefix` | `String(16)` | Non-nullable | Public prefix for identification (`mcis_...`) |
| `creator_id` | `String(36)` | FK `users.id` (SET NULL), Nullable | User ID of the invitation issuer |
| `email` | `String(255)` | Nullable, Indexed | Optional target email filter |
| `global_role` | `String(32)` | Non-nullable, Default `"member"` | Global role assigned upon registration |
| `server_id` | `String(36)` | FK `servers.id` (CASCADE), Nullable | Optional server to attach membership |
| `server_role` | `String(32)` | Nullable | Server membership role (`admin`, `dev`, `viewer`) |
| `status` | `String(32)` | Non-nullable, Default `"ACTIVE"` | `ACTIVE`, `USED`, `EXPIRED`, `REVOKED` |
| `max_uses` | `Integer` | Non-nullable, Default `1` | Maximum allowed registrations |
| `use_count` | `Integer` | Non-nullable, Default `0` | Current registration count |
| `expires_at` | `DateTime(TZ)` | Nullable | Optional expiration timestamp |
| `used_at` | `DateTime(TZ)` | Nullable | Timestamp of first/last usage |
| `created_at` | `DateTime(TZ)` | Non-nullable | Created timestamp |
| `updated_at` | `DateTime(TZ)` | Non-nullable | Updated timestamp |

---

## 6. REST API Specifications

### 6.1 Setup & Bootstrap Router (`/api/v1/setup`)

#### `GET /api/v1/setup/status`
- **Auth:** Public
- **Description:** Returns instance state and setup status.
- **Response `200 OK`:**
  ```json
  {
    "initialized": false,
    "access_mode": "LOCAL",
    "user_count": 0,
    "version": "4.0.0"
  }
  ```

#### `POST /api/v1/setup/bootstrap`
- **Auth:** Public (Gated: fails with `400 Bad Request` if `initialized == true` or `user_count > 0`)
- **Request Body:**
  ```json
  {
    "email": "owner@example.com",
    "password": "SecureOwnerPassword123!",
    "display_name": "Instance Owner",
    "access_mode": "GLOBAL"
  }
  ```
- **Response `201 Created`:**
  ```json
  {
    "success": true,
    "message": "Instance bootstrapped successfully",
    "user_id": "usr_owner_uuid",
    "access_token": "eyJhbG...",
    "refresh_token": "mcrt_...",
    "expires_in": 900
  }
  ```

---

### 6.2 Invitation Router (`/api/v1/invites`)

#### `POST /api/v1/invites`
- **Auth:** `require_permission("user:write")` or `require_permission("admin:full")`
- **Request Body:**
  ```json
  {
    "email": "dev@example.com",
    "global_role": "member",
    "server_id": "srv_12345",
    "server_role": "dev",
    "max_uses": 1,
    "expires_in_hours": 48
  }
  ```
- **Response `201 Created`:**
  ```json
  {
    "invite_id": "inv_uuid",
    "token": "mcis_a1b2c3d4e5f6...",
    "email": "dev@example.com",
    "status": "ACTIVE",
    "expires_at": "2026-08-13T15:00:00Z"
  }
  ```

#### `GET /api/v1/invites/verify/{token}`
- **Auth:** Public
- **Response `200 OK`:**
  ```json
  {
    "valid": true,
    "email": "dev@example.com",
    "expires_at": "2026-08-13T15:00:00Z"
  }
  ```

#### `POST /api/v1/invites/accept`
- **Auth:** Public (Replaces open `/users` registration)
- **Request Body:**
  ```json
  {
    "token": "mcis_a1b2c3d4e5f6...",
    "email": "dev@example.com",
    "password": "UserPassword123!",
    "display_name": "Developer Alex"
  }
  ```
- **Response `201 Created`:** Standard `LoginResponse` (issues JWT & refresh token immediately).

#### `GET /api/v1/invites`
- **Auth:** `require_permission("user:write")`
- **Response `200 OK`:** List of all invitations.

#### `DELETE /api/v1/invites/{invite_id}`
- **Auth:** `require_permission("user:write")`
- **Response `204 No Content`:** Revokes invitation (`status = "REVOKED"`).

---

## 7. Frontend UX Specifications

### 7.1 Setup Wizard Component (`/setup`)
- **Trigger:** Rendered automatically if `GET /api/v1/setup/status` returns `initialized: false`.
- **UI Design:** Clean multi-step or single-card wizard matching the "Blade Hosting" dark theme.
- **Fields:** Owner Email, Display Name, Password, Confirm Password, Access Mode Toggle (`LOCAL` vs `GLOBAL`).
- **Completion:** Submits to `POST /api/v1/setup/bootstrap`, stores returned JWT in `useAuthStore`, and redirects to Dashboard (`/`).

### 7.2 Updated Registration / Accept Invite Page (`/register` & `/invite/:token`)
- If accessed directly via `/register` without a token: Displays a message explaining that registration is by invitation only, with an input field to enter an invite code.
- If accessed via deep link `/invite/:token`: Pre-validates the token via `GET /api/v1/invites/verify/{token}`, locks the email field (if specified in invite), and renders the account creation form.

### 7.3 Instance & Invites Management in Settings (`/settings`)
- **Settings Tab:** "Access & Invitations"
- **Features:**
  - Toggle Access Mode (`LOCAL` / `GLOBAL`).
  - Create Invitation Modal (select target email, expiration, global role, server access).
  - Active Invitations Table (shows token prefix, status, usage, expiration, Revoke action).

---

## 8. Implementation Phases & Batches

```
+-----------------------------------------------------------------------------------+
| BATCH 1: Database Schemas & Infrastructure                                         |
| - Alembic Migration: SystemStateModel (`instance_state`) & InvitationModel        |
| - Domain Aggregates: SystemState & Invitation entities                            |
| - SQL Repositories: SQLSystemStateRepository & SQLInvitationRepository            |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| BATCH 2: Backend Application & API Layer                                          |
| - Application Commands & Handlers: BootstrapInstance, CreateInvite, AcceptInvite |
| - Setup Router (`/api/v1/setup`): status, bootstrap                               |
| - Invites Router (`/api/v1/invites`): CRUD, verify, accept                       |
| - Deprecate/Gate `POST /api/v1/users` (block unauthenticated self-registration)   |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| BATCH 3: Frontend Integration & Setup Wizard                                      |
| - Setup Wizard Page (`SetupPage.tsx` at `/setup`)                                 |
| - Update `AuthGuard` to check instance initialization status                       |
| - Update `RegisterPage.tsx` for token-based invitation acceptance                 |
| - Add Invitations Management UI to `SettingsPage.tsx`                             |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| BATCH 4: Verification, Security Auditing & E2E Testing                            |
| - Integration tests for Bootstrap, Access Mode, Invite lifecycle                  |
| - Security tests (prevent double-bootstrap, expired/revoked invite rejection)    |
| - Full backend test suite pass (1219+ tests)                                      |
+-----------------------------------------------------------------------------------+
```

---

## 9. Verification & Safety Plan

1. **Double-Bootstrap Prevention:** Test that `POST /api/v1/setup/bootstrap` strictly rejects secondary attempts with `409 Conflict` once an Owner exists or `initialized == True`.
2. **Invite Token Security:** Secret tokens must be hashed (`SHA-256`) before database storage; raw tokens are shown only once upon creation.
3. **Open Registration Lockout:** Verify that unauthenticated requests to `POST /api/v1/users` are permanently blocked in favor of `/api/v1/invites/accept`.
4. **Server Membership Automatic Wiring:** Verify that accepting an invite with `server_id` and `server_role` automatically provisions a valid `ServerMembershipModel` row.
5. **Zero Regression:** Ensure all 1219 existing unit & API integration tests continue to pass clean.
