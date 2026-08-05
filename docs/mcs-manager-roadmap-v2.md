# MCS Manager — Roadmap v2 (Planning Baseline → AI)

**Status:** Living planning document — engineering-owned
**Version:** 3.0 (restructured to 10 dependency-ordered phases)
**Last updated:** 2026-08-04
**Baseline:** `docs/current-state.md` (verified 2026-08-04) and `docs/STATUS.md`
(Batch history)

> **This is the only authoritative roadmap.** `docs/roadmap.md` (v0) and
> `docs/mcs-manager-roadmap-v1.md` (v1) are historical documents kept for
> reference only. Where they disagree with this document, this document wins.

---

## 1. Purpose and how to read this document

This roadmap sequences the work to take MCS Manager from its verified current
state to a reliable public product. It is built from the current repository
(see `docs/current-state.md`), not from any earlier roadmap. The order below is a
**dependency order**: each phase is gated only on the finishing of the phases it
depends on, and where repository evidence showed a hard dependency it is called
out explicitly.

Nothing in this document is complete until `docs/current-state.md` says so. Bug
classes are defined below and every known issue in `docs/current-state.md` §5 is
owned by a phase.

### Status legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Done — verified in `docs/current-state.md` |
| 🔄 | In progress — active now |
| 🔶 | Planned — not started |
| ⛔ | Blocked — gated on an earlier phase |
| ⚠️ | Risk or open question requiring a decision |

### Bug classification

| Class | Meaning |
|-------|---------|
| **Must fix** | Blocks a phase exit criterion or a security/availability claim |
| **Should fix** | Real defect; safe to defer within a phase but must be scheduled |
| **Optional** | Quality-of-life; can be dropped with a documented reason |
| **Known limitation** | Accepted behavior; documented, not scheduled |
| **Doc-only** | Documentation correction with no code change |
| **Future work** | Tracked in a later phase's backlog, not current scope |

### Product direction (governing)

- **Modern foundation first.** Coherent product structure and reliability come
  before advanced capability.
- **Plugins and Marketplace are distinct product surfaces.** Plugins = the
  installed plugins on a selected server. Marketplace = global catalog/discovery.
  They are never the same page conceptually.
- **Network access is gated on stability.** Tunnel/port-forwarding work is not
  started while the product, authorization, versioning, and tests/CI are not
  reliable.
- **AI is the final phase and intentionally deferred.** AI does not move earlier
  simply because it is interesting.

---

## 2. Phase 0 — Current reality ✅ (complete)

The accepted baseline described in `docs/current-state.md`. Key facts:

- **10 REST routers**, 9 DDD modules, 16 Alembic revisions, 12 ADRs, 6 contracts.
- **Backend tests:** 1070 collected, 1068 passing, 2 pre-existing environment
  failures. **Frontend tests:** 236 passing across 41 files.
- Server lifecycle, runtime ownership, backups, monitoring, health engine,
  plugin registry, auth, and the Modrinth marketplace backend are implemented.
- Version is uniformly `4.0.0` in code (see `docs/VERSIONING.md`).
- **Two deliberately uncommitted files** exist in the working tree:
  `backend/app/api/v1/routers/plugins.py` and
  `backend/tests/api/test_api_endpoints.py`. They are not part of any committed
  baseline and must remain untouched by this documentation task.

---

## 3. Phase 1 — Plugins / Marketplace separation 🔄 CURRENT

**This is the first product/UI priority.**

The marketplace is currently treated as a subsection of the Plugins page
(frontend route `/plugins/marketplace`, reached via the Plugins Install button).
The intended model treats them as two distinct product areas.

**Current reality**
- Backend: `/api/v1/servers/{server_id}/plugins/*` handles both plugin
  management and the marketplace (search / versions / install) under one router.
  Marketplace provider is hardcoded to Modrinth (K16).
- Frontend: `PluginListPage` (server-scoped; filesystem-reconciled list,
  enable/disable/uninstall) and `PluginMarketplacePage` share the `/plugins`
  namespace. **Sidebar has no Marketplace entry** (K5): 5 items (Dashboard,
  Servers, Backups, Plugins, Settings). Marketplace is reached only from the
  Plugins page's Install button.

**Desired state**

| Area | Answers | Scope |
|------|---------|-------|
| **Plugins** | "What plugins does this server have?" | Server-scoped: installed list, state, lifecycle, enable/disable, removal, configuration where supported, per-installed-plugin metadata |
| **Marketplace** | "What plugins can I discover and install?" | Global catalog/discovery/store, server-selection at install time |

**Workstreams**
1. **Frontend nav restructure (K5).** Give Marketplace a distinct, first-class
   navigation entry (sidebar + top-level route such as `/marketplace`), with its
   own search, project detail, and install flow. Keep server plugin management
   as a separate server-scoped section. Decide and document the navigable
   relationship (e.g. Marketplace links into a selected server's plugin list on
   install; Plugins page links out to Marketplace for discovery).
2. **Route/namespace clarity.** Decide whether marketplace API endpoints remain
   under `/servers/{server_id}/plugins/marketplace/*` (server-taken at install)
   or move to a marketplace-owned namespace. Keep backward compatibility or
   stage the move — see decision log.
3. **Provider abstraction (K16).** Make the catalog provider list inspectable
   and configurable (`MCS_PLUGIN_PROVIDERS`), keeping Modrinth as the default.
   No additional provider is preselected; providers are evaluated when one is
   actually needed (see `docs/network-access-design.md` §provider principles
   for the same discipline applied to plugins).
4. **Foundation for future catalog features.** Marketplace is architected as the
   base for catalog-driven capabilities (verified checksums, version metadata,
   dependency info are already present in the version-selection model).

**Dependencies:** none (backend marketplace already shipped).

**Acceptance criteria**
- Marketplace is independently navigable (its own nav entry and route), not a
  subsection hidden inside plugin management.
- Installing from Marketplace places a verified `.jar` into a selected server's
  `plugins/` directory, and the reconciled list shows it.
- Plugin management is clearly server-scoped; Marketplace is clearly global.
- Provider list is configuration-driven with Modrinth default.

**Verification:** backend + frontend suites green; manual UX walk of both areas;
frontend tests for the two navigation surfaces.

---

## 4. Phase 2 — Product foundation & UI stabilization 🔶

**Objective:** make the frontend a first-class product surface (not an
afterthought) and stabilize the loading/error/empty/state model and navigation,
on top of the Phase 1 restructure.

**Current reality (frontend)** — described accurately in
`docs/FRONTEND.md`; nothing new invented here.

- React 19 + Vite + TypeScript 5, TanStack Query, Zustand, TailwindCSS 4.
- Routes (verified `frontend/src/App.tsx`): `/login`, `/register`, then guarded:
  `/` (Dashboard), `/servers`, `/servers/create`, `/servers/import`,
  `/servers/:serverId`, `/backups`, `/plugins`, `/plugins/marketplace`,
  `/settings`, `/settings/api-keys`, `*`.
- Sidebar (verified `frontend/src/components/layout/Sidebar.tsx`): Dashboard,
  Servers, Backups, Plugins, Settings — **no Marketplace** (Phase 1 adds it).
- Stores (Zustand): `authStore` (localStorage `mcs_auth`), `uiStore`, `wsStore`.
- WebSocket client fully implemented (connect/reconnect/ping/message queue) but
  backend rejects every subscription (K1) and never dispatches events (K2) — so
  WS is behaviorally non-functional despite the client being complete (Phase 3).

**Desired state (target UX — separate from current)**
- Consistent navigation: plugin-management vs marketplace clearly distinct;
  server-scoped vs global pages visually and structurally separate.
- Uniform loading / error / empty states across all pages (each page states
  which pattern it uses).
- Deterministic API state + cache behavior (TanStack Query configured once and
  applied consistently).
- WebSocket behavior is documented and either works or is explicitly disabled per
  surface — no "connected but silent" dead-end (cross-reference Phase 3 K1/K2).
- Settings UX reflects what actually persists (settings persistence is Phase 3;
  Phase 2 defines the UI and disables/annotates non-persistent controls rather
  than faking success).
- Permissions UX: UI surfaces only actions the user may take, based on the
  permissions model (authorization completion is Phase 4; Phase 2 lays the
  presentation groundwork with the model documented in `contracts/permissions.yaml`).
- Responsive behavior and visual consistency with the existing Tailwind/raw
  component approach — **no new design system is invented**; the goal is to
  consistently apply what exists.

**Workstreams** (each with current → desired → acceptance)
1. Navigation & IA (build on Phase 1).
2. Shared state/UX primitives (loading, error, empty) applied repo-wide.
3. API client + TanStack Query configuration audit.
4. Settings page accuracy relative to persistence (disable the stub PATCH path
   in UI until Phase 3; surface only persisted values).
5. WebSocket surface honesty (indicate live-vs-disabled state).
6. Frontend test coverage improvements for the above.

**Dependencies:** Phase 1 (nav restructure baseline).

**Acceptance criteria**
- Every route has defined loading/error/empty behavior; no page silently fakes
  success.
- Navigation distinguishes server-scoped and global surfaces.
- Frontend tests cover the new/restructured navigation and state primitives.

**Verification:** frontend suite green; manual walkthrough; route-by-route state
review recorded in `docs/FRONTEND.md`.

---

## 5. Phase 3 — Backend/frontend bug fixing & reliability 🔶

**Objective:** make the existing product actually reliable — concrete defect
categories, not "fix all bugs."

**Dependencies:** none structural; run in parallel with Phase 2 where surfaced.

### 5.1 WebSocket delivery — **must fix**
- **K1:** channel authorization always denies (plural `CHANNEL_PATTERNS`
  `servers:read` vs singular JWT claims `server:read`) — fail-closed, no channel
  subscribes. Reconcile to a single singular `resource:action` namespace with
  `admin:full` passthrough.
- **K2:** `EventDispatcher` / `MetricsBatcher` never instantiated — no server-push
  events reach clients. Wire into the app lifespan with an event-bus
  subscription; keep fail-closed during transition.
- **Secondary WS gaps** (`docs/PERMISSIONS_FUTURE_IDEAS.md` §4): validate
  `refresh_token` payloads, enforce idle timeout, re-check authorization per
  pushed message.
- **Acceptance:** a client with `server:read` subscribes and receives `state` /
  `event` frames; publishing a domain event reaches subscribers (integration
  test); fail-closed still holds without permission.

### 5.2 Settings persistence — **must fix**
- **K3:** `PATCH /api/v1/settings` is a stub returning a success message; nothing
  persists. Decide the persisted field set (those `GET /settings` already returns
  that are user-facing), persist them, apply at runtime, and gate with
  `settings:write`.
- **Acceptance:** updating a setting persists, is returned by `GET /settings`, and
  is enforced at runtime.

### 5.3 Test suite green — **must fix**
- **K8:** the 2 failing tests — `test_start_server` (closed-DB rollback in API
  teardown) and `test_metrics_task_requires_collector` (stale expectation vs the
  graceful warning handler). Fix or formally re-baseline; assert the chosen
  contract.
- **Acceptance:** `python -m pytest tests/` passes with 0 failures.

### 5.4 Runtime/system consistency — **should fix**
- **K9:** production DB 3 revisions behind head; 0 servers. Bring to head with a
  documented upgrade procedure (see `docs/DATABASE.md` + `docs/VERSIONING.md`).
- **K15:** repo-root `data/` cleanup (verify unused before removing).
- **K14:** backup save-all completion regex unverified against a real Purpur
  server — add a live/mocking regression check.

### 5.5 Honest error handling
- Audit HTTP status/error payload consistency (the 422-vs-500 pattern already
  fixed for email/minecraft_version is the model); document the contract.

**Acceptance:** WS live, settings persist, tests green, DB at head, documented
error contract.

---

## 6. Phase 4 — Authorization / security cleanup 🔶

**Objective:** close the security gaps identified in the audit; enforce the model
in CI so it cannot regress.

**Dependencies:** Phase 3 (a stable, tested base). Not started while the plugin
restructure and reliability work are open.

### 6.1 Enforce remaining routes — **must fix**
- **Current:** 24 routes gated by `require_permission` (22 mutating + 2 read-only
  marketplace; `contracts/permissions.yaml` v1.4). Remaining gaps: 13 mutating
  routes and 21 sensitive GET routes are auth-only with no permission check.
  Plugin `enable`/`disable` carry no `require_permission` (K4). `request.state
  .permissions` is written by `AuthMiddleware` but never read outside gated
  routes.
- **Work:** enumerate the 13 mutating + 21 sensitive GET routes, choose their
  permission strings (already drafted in `contracts/permissions.yaml`), gate
  them, and enforce in CI.

### 6.2 Backend CI + route-coverage test — **must fix (K6)**
- No backend CI — only `.github/workflows/frontend-ci.yml`. Add a workflow that
  runs `pytest`, `ruff`, `pyright`, and a route-coverage test walking the live
  FastAPI route table asserting every mutating route carries a permission
  dependency.
- **Acceptance:** a new mutating route without a permission dependency fails CI;
  `contracts/permissions.yaml` matches the live route table with 0 gaps.

### 6.3 WebSocket authorization hardening
- Fold WS channel checks into the same (now singular) permission path so there is
  one enforcement model, not two divergent ones.

### 6.4 Security docs must match reality
- `docs/SECURITY.md` currently and correctly documents the partial-enforcement
  gap; after 6.1 this caveat is resolved. Re-verify the whole doc (`httpOnly` vs
  localStorage refresh token is already corrected, API-key SHA-256 hashing,
  per-client rate limiting, WS fail-closed).

**Acceptance:** every mutating endpoint checked, CI-enforced, `contracts/
permissions.yaml` complete; SECURITY.md no longer carries a partial-enforcement
caveat beyond explicitly-allowlisted public routes.

---

## 7. Phase 5 — Versioning & state consistency 🔶

**Objective:** establish a single authoritative version and consistent state
sources.

**Design reference:** `docs/VERSIONING.md` (PLANNED). Summary:

- Backend `pyproject.toml` is the canonical version source; runtime, OpenAPI, and
  the displayed product version derive from it.
- Frontend displays the backend-provided version; `package.json` becomes build
  metadata.
- SemVer conventions stated; "v1.0 public release" decoupled from internal app
  version.
- Per-release minimum-Alembic-revision rule for DB compatibility; report/constrain
  prod upgrade status.
- `.ai` state-file version fields align to the resolved version; docs stop
  asserting versions the code can't justify.

**Acceptance:** changing one source propagates without further edits; one
document/command answers the version question; no residual `7.1.0`-class orphan
versions outside history and server data.

---

## 8. Phase 6 — Testing / CI / documentation reliability 🔶

**Objective:** make tests and docs trustworthy execution contracts.

- Re-baseline or remove historical-only counts in `STATUS.md`; `current-state.md`
  is the single current-state source.
- Backend CI (built in Phase 4) extended to fail on doc-vs-code drift where
  feasible (e.g. a test asserting the contract route table matches CI coverage).
- Documentation quality rules enforced (implemented/partial/planned/historical
  labels in `docs/README.md`).
- Remove/redirect remaining duplicate sources of truth; `docs/README.md` is the
  canonical index.

**Acceptance:** CI green across backend+frontend; a doc claim can be traced to
code; no two docs contradict on counts.

---

## 9. Phase 7 — Network Access / Port Forwarding 🔶
⛔ **Blocked on Phases 1–6.** Exposing the app compounds every authorization or
stability gap; this phase starts only after the product, auth, versioning, and
CI are reliable.

**Design reference:** `docs/network-access-design.md` (PLANNED). Read it for the
full architecture; the section below is the roadmap summary.

### 9.1 Scope
Remote access to **your own single running instance** (phone, a friend's house,
on the road). Not multi-tenant hosting, not multi-node orchestration.

### 9.2 Two user-facing modes

**A. Tunnel (recommended default).** For users who do not want to understand
networking. The system abstracts NAT, router configuration, manual port
forwarding, dynamic public-IP handling, endpoint changes, and DNS synchronization
where supported.

**B. Manual port forwarding.** For advanced users. The user manages router
configuration, firewall, public IP, and ports. MCS Manager manages only the
information it can safely manage.

### 9.3 Architectural boundaries (must hold)

1. **TunnelProvider separate from DnsProvider.** Tunnel = makes the service
   reachable from the internet. DNS = provides a stable hostname and maps it to
   the current endpoint. Never conflate them. Conceptual operations:

   - **`TunnelProvider`:** create · start · stop · delete · status · endpoint.
   - **`DnsProvider`:** allocate hostname · create record · update record ·
     delete record · get record · verify record.

2. **Dynamic endpoints.** Tunnels can produce endpoint URLs at runtime
   (`*.trycloudflare.com`-style ephemeral URLs, per-tunnel hostnames). The system
   must accept endpoints discovered/assigned at runtime, not only a static URL.

3. **Independent Game vs Management exposure.** Exposing the Minecraft game port
   vs exposing the MCS Manager management UI are two independent decisions —
   separate toggles, separate tunnels, separate security postures. The game port
   typically needs no auth (Minecraft has none); the management UI always requires
   the full auth stack. Never gate them together.

4. **Tunnel ≠ Authentication.** The tunnel is transport only. Traffic that passes
   a tunnel in front of FastAPI must run through the exact same auth/authorization
   stack as local traffic. No tunnel opens a second unauthenticated surface.
   Recommended: shared secret / mTLS between the tunnel client and the app so a
   compromised provider cannot inject locally-sourced traffic. Boundary:

   ```
   Internet → Network Access → MCS Manager → Authentication → Authorization → Management
   ```

   Minecraft access and management access remain separate security boundaries.

5. **DNS is optional and pluggable.** Not every tunnel needs DNS (ephemeral URLs
   don't). DNS providers are evaluated per deployment; never assume a domain.

6. **No provider preselection.** Candidate providers and the requirements they
   must meet are identified, not chosen, here and in `docs/network-access-design.md`.

7. **Provider extensibility requirement.** Providers must be replaceable. Prefer
   official APIs and supported automation interfaces; never browser automation or
   dashboard scraping. Document provider limitations and free/paid differences.

### 9.4 Hardened defaults in publish mode
- Rate limiting already per-client and per-path (Phase 0/3, verified).
- Shorter access-token lifetimes, mandatory HTTPS, optional-but-strongly-prompted
  2FA.
- RBAC/ABAC enforced everywhere; unauthenticated access is the exception that
  must be explicitly allow-listed.
- Revisit `GET /metrics` exposure (K10) under this decision.

**Exit criteria:** explicit local/publish choice in an install flow; game and
management exposure independently controllable; tunnel traffic provably subject
to the same authz as local traffic; tunnel and DNS are separate provider
interfaces with dynamic endpoint support; manual port-forwarding mode documented.

---

## 10. Phase 8 — Dynamic endpoint + DNS architecture 🔶
⛔ **Blocked on Phase 7.**

**Objective:** make endpoint changes invisible to the user.

**Desired lifecycle (explicit):**

```
Tunnel starts
  → Get endpoint
  → Store endpoint state
  → Synchronize DNS
  → Monitor endpoint
  → Detect endpoint change
  → Update state
  → Update DNS
  → Verify
  → Expose stable hostname to user
```

The user must not manually update their hostname when the underlying endpoint
changes.

### 10.1 Minecraft access
```
Minecraft → Tunnel → Public endpoint → DNS → Stable hostname
```

### 10.2 Management access
```
MCS Manager → HTTP/HTTPS tunnel → Public endpoint → DNS → Stable hostname
```

Do not assume the same tunnel provider must serve both — the architecture allows
separate providers/configuration when appropriate.

**Acceptance:** changing a tunnel endpoint updates stored state and DNS and re-
verifies, surfacing a stable hostname; game and management flows each support
their own provider configuration.

---

## 11. Phase 9 — Final stabilization 🔶

Systematic close-out before AI: full security review vs `docs/SECURITY.md`,
performance/diagnostic passes, production upgrade verification, and the
remaining `should fix` / `optional` items. No new capability; harden and verify.

**Acceptance:** documented end-to-end verification of the stable baseline used by
Phase 10.

---

## 12. Phase 10 — AI features 🔶 (final phase, intentionally deferred)
⛔ **Blocked on all prior phases.**

**This is the last phase by product decision.** AI begins only after:

- frontend foundation is stable (Phases 1–2)
- backend is stable and bugs controlled (Phase 3)
- authorization/security is complete and enforced (Phase 4)
- versioning is fixed (Phase 5)
- tests/CI reliable (Phase 6)
- Network Access is implemented and stable (Phases 7–8)
- security boundaries are understood and hardened (Phase 9)

**Non-negotiable guardrails — built in from the start, not retrofitted:**
1. Agent actions route through the exact same permission layer as normal API
   calls. No privileged bypass path.
2. Explicit user confirmation before any destructive action.
3. Full audit trail of every agent-issued command, attributable to the invoking
   user.
4. Pipeline: natural-language request → structured plan → execution, with CLI,
   API, GUI, and Agent calling the same internal services. A partial demo that
   bypasses structured planning does not satisfy this phase.

**Deferred status:** this phase is tracked but intentionally not scheduled with a
start date. See `docs/network-access-design.md` and `docs/FEATURE_IDEAS.md` for
the roadmap rationale.

---

## 13. Deliberately out of scope (tracked, not scheduled)

| Item | Why it's out | Tracked in |
|------|--------------|------------|
| Container plugin isolation (`ContainerPluginRunner` stub) | Requires the plugin system + Marketplace stable first | `FEATURE_IDEAS.md` |
| Metrics retention rollups (1m/1h/1d) | Raw data is fine for live dashboards; rollups are storage optimization | `FEATURE_IDEAS.md` |
| Remote agents / multi-node orchestration | Different trust model; distinct from single-instance remote access | `FEATURE_IDEAS.md` |
| Multi-tenant hosting | Isolation, billing, per-tenant limits, abuse handling — materially larger scope | `FEATURE_IDEAS.md` |
| Mobile companion app | Polish, not core | `FEATURE_IDEAS.md` |

---

## 14. Versioning / stability summary

See `docs/VERSIONING.md` for the full plan. Key points repeated here because they
are roadmap commitments: single source of truth (backend package metadata),
frontend displays backend version, SemVer semantics, DB migration/revision
compatibility rule, and `.ai` state-file alignment. This is Roadmap Phase 5.

---

## 15. Decision log — items requiring an explicit answer

| # | Question | Recommendation | Status |
|---|----------|----------------|--------|
| 1 | Should the 2 failing tests be fixed or re-baselined? | Fix `test_metrics_task_requires_collector` (stale assertion); investigate `test_start_server` teardown first | Open |
| 2 | Which settings fields must persist in Phase 3? | Start with the fields already returned by `GET /settings` that are user-facing | Open |
| 3 | Do marketplace API routes move out of `/servers/{id}/plugins/marketplace/*`? | Keep server-taken semantics but decouple the UI; stage any path move for backward compatibility | Open |
| 4 | Network scope: single-instance remote access vs multi-tenant hosting? | Single-instance, as scoped in Phase 7 | Confirm |
| 5 | Tunnel / DNS provider choices | Evaluate when implementation starts; no preselection | Open |
| 6 | 2FA mandatory or optional in publish mode? | Optional but strongly prompted at first publish | Open |
| 7 | JWT signing key storage (DB-encrypted vs secrets file) | Match existing secrets-handling convention; `kid`-based rotation regardless | Open |
| 8 | Repo-root `data/` directory cleanup (K15) | Remove once confirmed unused | Open |
| 9 | Prod DB upgrade: auto-upgrade on boot vs refuse-to-start | Refuse with loud log + documented upgrade procedure; revisit per `VERSIONING.md` | Open |
| 10 | Should the 2 uncommitted marketplace files be committed as their own commit? | Yes, they are complete, tested changes | Open |

---

## 16. Sources

- `docs/current-state.md` (verified 2026-08-04) — the factual baseline
- `docs/VERSIONING.md` — versioning strategy (PLANNED)
- `docs/network-access-design.md` — Phase 7/8 design reference
- `docs/plugins-and-marketplace.md` — current plugin + marketplace implementation
- `docs/STATUS.md` — batch history through Batch 10
- `contracts/permissions.yaml` v1.4 — live route→permission coverage matrix
- `docs/PERMISSIONS_FUTURE_IDEAS.md` — WS trace (§4), metrics (§3), registration
  bootstrap (§5)
- `docs/FEATURE_IDEAS.md` — parking-lot items and the 2026-08-04 marketplace
  exception record

---

*Supersedes `docs/mcs-manager-roadmap-v1.md` and `docs/roadmap.md`. Phase status
markers here are authoritative for phase state.*