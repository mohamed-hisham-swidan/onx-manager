# Permissions — Future Ideas & Deferred Decisions

**Status:** Not started — backlog / parking-lot document.
**Purpose:** Captures permission-model ideas and decisions explicitly deferred
to Roadmap Phase 4 (Authorization / security cleanup, roadmap §6) or later. This is
**not** a spec and nothing here is committed work.
**Last updated:** 2026-08-04

---

## 1. Why the Phase 1 catalog was left as-is

During the Phase 1 §3.1 authorization coverage audit (2026-08-02, under the
previous roadmap's numbering — equivalent to Phase 4 §6.1 in the restructured
`docs/mcs-manager-roadmap-v2.md`), the decision
was made to **keep the existing `permissions:` / `roles:` catalog untouched** and
fold every currently-unprotected route onto the closest existing `resource:action`
permission (e.g. per-server reads → `server:read`, global cron/config writes →
`settings:write`). No new granular permissions were introduced.

Rationale:

- The audit was read-only; adding new permission names would have implied wiring
  new enforcement, touching code mid-coverage-audit.
- `contracts/permissions.yaml` `route_permissions` now records, for every route,
  a concrete existing permission and a status (`enforced` / `missing` /
  `enforced-external` / `not-applicable-public`).

A full redesign of the permission model belongs to **Phase 4** (Authorization /
security cleanup, roadmap §6), per the roadmap's explicit gating.

---

## 2. Proposal to evaluate in Phase 4 — broader permission tiers

Originally proposed during the audit: simplify the whole permission model toward
broader **tiers** (e.g. `reader` / `owner` / `admin`) instead of fine-grained
`resource:action` strings.

This is recorded **as a proposal to evaluate during the Phase 4 RBAC/ABAC
cleanup (§6)**, not a decision made now. Points to weigh when it's on the
table:

- Fewer distinct permissions means fewer places to get a coverage gap, but loses
  expressiveness (e.g. "can start but not delete a server").
- The roadmap's recommended direction (§6) is namespaced `resource:action` with
  wildcards (`server:*`), plus RBAC for coarse checks and ABAC predicates layered
  on top for ownership. A three-tier model is an alternative that trades
  expressiveness for simplicity.
- Whatever direction wins, `contracts/permissions.yaml` `route_permissions` is the
  ground-truth matrix to re-derive the new model from.

---

## 3. Deferred decision — `GET /metrics` (Prometheus scrape endpoint)

Currently public/unauthenticated (`app/main.py:258-272`; also whitelisted in
`AuthMiddleware._public_routes`, `app/api/v1/middleware/auth.py:12-21`). It
exposes operational gauges (TPS, players, RAM, CPU).

**Deferred, not fixed blindly**, because:

- Locking it down risks breaking any existing external Prometheus scraping setup
  (scrapers usually cannot present a JWT/api-key without extra exporter config).
- The safe design depends on how the app is exposed — revisit alongside
  **Phase 7** (Network Access, roadmap §9.4), where per-client rate
  limiting and hardened session defaults are already mandatory.

Options to evaluate then: keep public behind per-client rate limiting; add a
dedicated read-only scrape token; or require `server:read`-class auth with an
allowlisted scrape identity.

---

## 4. WebSocket `/ws` — channel authorization namespace mismatch (finding)

Traced 2026-08-02. The WS endpoint has a real auth gate, but it is **non-functional**
in practice:

- **Handshake token check exists** before `accept()`:
  `app/websocket/endpoint.py:51-64` — missing/invalid/expired token →
  `WS_1008_POLICY_VIOLATION` (verification in
  `app/modules/auth/infrastructure/jwt.py:203-208`).
- **Per-channel gate exists** at subscribe time:
  `app/websocket/handlers.py:116-131` → `ChannelAuthorizer.can_subscribe`
  (`app/websocket/authorization.py:41-55`).
- **But it always denies.** `CHANNEL_PATTERNS`
  (`app/websocket/authorization.py:3-17`) requires **plural** permission strings
  (`servers:read`, `backups:read`, `plugins:read`, `monitoring:read`, `users:read`,
  `auth:read`, `servers:console`), while real JWT/api-key claims carry **singular**
  REST permissions (`server:read`, …) built via
  `app/modules/auth/application/commands/login.py:48-53` and
  `Permission.__str__` (`app/modules/shared/value_objects.py:205-206`).
  `set() is subset` therefore fails for every real claim set, and `admin:full`
  is not in any required set either. **Result: every `subscribe` is denied
  (fail-closed), so no channel can ever be subscribed.**
- Additional gaps found while tracing (all deferred):
  - Token expiry mid-connection only sends an `auth_expired` advisory and keeps
    the connection + subscriptions open (`handlers.py:52-54`); the dispatcher does
    not re-check authorization per pushed message (`dispatcher.py:40-57`).
  - `refresh_token` accepts any non-empty string with **no signature/expiry
    validation** and extends the stored expiry (`handlers.py:144-152`,
    `authentication.py:41-47`); expiry is set to `now + 3600` regardless of the
    real 900 s access-token TTL (`handlers.py:41`).
  - Idle timeout is defined (`authentication.py:20,60-64`) but never invoked in
    the handler loop (`handlers.py:44-72`).
  - **The dispatcher is never started in production.** `EventDispatcher` and
    `MetricsBatcher` (`app/websocket/dispatcher.py:16,116`) are defined but never
    instantiated anywhere in production code — not in the `main.py` lifespan, not
    in `registration.py`/`init_buses`, and there is no event-bus subscription.
    Verified at runtime (2026-08-02, `ws_prod_eq.py`): after a
    production-equivalent init, publishing `ServerStarted` on the event bus
    reached **zero** subscribers (`bus._subscribers keys: []`) and no event frame
    was pushed — even for a client with a valid plural `servers:read`
    subscription. So even after the namespace reconciliation above, events would
    still never reach connected clients until this wiring is added.

**Deferred to Phase 3/4**: the fix is a namespace reconciliation (and ideally a
shared permission-checking path rather than a second, divergent one) **plus
wiring the `EventDispatcher`/`MetricsBatcher` into the app lifespan**, which are
currently never instantiated. It is currently safe because it fails closed and
nothing is dispatched, but the WS layer must be brought into the Phase 4
permission model (WS delivery work is Phase 3 §5.1).

---

## 5. Deferred decision — first-user registration bootstrap

Investigated 2026-08-02 (task scope included a proposed fix: allow
`POST /api/v1/users` unauthenticated **only** while zero users exist, then require
`user:write`). **Not implemented** — investigation surfaced complexity that made an
improvised fix risky:

- **Documented onboarding relies on open registration:**
  `docs/API.md:471` ("`POST /api/v1/users` is public (registration)"),
  `docs/getting-started.md:55` ("Register an account — click 'Register' and create
  your first user"), and `docs/FRONTEND.md:113` (`/register` → `RegisterPage`).
  Closing registration changes documented user behavior.
- **No implicit-admin mechanism exists.** `User.create`
  (`app/modules/auth/domain/aggregate.py:187-196`) assigns **no roles**, and there
  is no role-seeding path or `RoleModel` bootstrap anywhere in the codebase. The
  proposed "first user becomes an implicit admin" has no foundation to build on —
  it would require designing role assignment from scratch.
- **The gate lives in middleware, not just the route.** The bypass is
  `AuthMiddleware._public_post_only = {"/api/v1/users"}`
  (`app/api/v1/middleware/auth.py:25-27,37-38`). Making it conditional means a DB
  user-count check in the middleware hot path, plus a mirrored conditional
  dependency on the route — two layers that must stay consistent.
- **Tests would need broad changes.** Every test that POSTs `/api/v1/users`
  without auth after a first user exists would flip from 201/409 to 401/403
  (e.g. `backend/tests/api/test_api_endpoints.py` `test_create_duplicate_user`,
  the `created_user` fixture, `test_create_user_and_login`).

**Options to re-evaluate in Phase 4:** a true first-run bootstrap wizard that seeds
an admin (aligns with the Phase 7 installer flow in
`docs/network-access-design.md` §4); or keep open
registration but add an explicit admin-invite/approval flow. Until then,
`POST /api/v1/users` stays public and the risk is documented in
`contracts/permissions.yaml` (`route_permissions` entry).

---

## 6. Change log

- 2026-08-02 — created; recorded §1 (catalog kept as-is), §2 (tier proposal),
  §3 (GET /metrics), §4 (WS namespace mismatch finding), §5 (registration bootstrap).
- 2026-08-02 — §4 updated: added the dispatcher-never-started-in-production
  finding (verified at runtime, `ws_prod_eq.py`) and the required WS lifespan wiring.
