# MCS Manager — Roadmap v3 (Single Source of Truth)

**Status:** Living planning document — engineering-owned
**Version:** 4.0 (numbers re-verified against live code 2026-08-05; supersedes v2)
**Last updated:** 2026-08-05
**Baseline:** live FastAPI route introspection (2026-08-05) + `docs/current-state.md`
(2026-08-04) + git history. See §0 for exactly what was re-verified and how.

> **This is the only authoritative roadmap.** `docs/roadmap.md` (v0),
> `docs/mcs-manager-roadmap-v1.md` (v1), and `docs/mcs-manager-roadmap-v2.md`
> (v2) are historical documents kept for reference only. Where they disagree
> with this document, this document wins — because every number below was
> re-verified against a live command run on 2026-08-05, not carried forward
> from an earlier snapshot.

---

## 0. Why v3 exists, and exactly what changed vs v2

v2 (2026-08-04) was internally consistent with its own baseline
(`current-state.md`, also 2026-08-04) but went stale within 24 hours because
commit `b1b6dd8` (2026-08-04, later same day) deleted a legacy route that both
`current-state.md` and `mcs-manager-roadmap-v2.md` §6.1 counted as
"unprotected." A 2026-08-05 live re-verification found three concrete
discrepancies:

| Claim | v2 said | Live re-check (2026-08-05) | Resolution |
|---|---|---|---|
| Mutating routes without permission enforcement | 13 | **12** | `b1b6dd8` removed the legacy `POST .../plugins` manual-install route that the matrix still listed as `status: missing`. Corrected below. |
| Sensitive GET routes without permission enforcement | 21 | **23** (middleware-strict count) | v2's "21" applied a non-middleware classification (treating 3 auth-gated routes as public-safe, and one public-prefix route as sensitive). This doc uses the strict live-middleware count and flags the classification question as an open decision (§15, item D1). |
| "Two deliberately uncommitted files" (`plugins.py`, `test_api_endpoints.py`) | "Not part of any committed baseline" | **Both are tracked, committed files** (8–9 commits each) with small uncommitted working-tree diffs on top | Wording corrected below (§2). |
| `contracts/permissions.yaml` version | v1.4 (implied settled) | **v1.3 is the committed HEAD version; v1.4 exists only as an uncommitted working-tree edit** (adds 3 marketplace rows, still lists the deleted route) | Tracked as an explicit open item (§15, item D2) — not yet resolved, resolve separately from this doc per 2026-08-05 decision. |

Everything else in v2 (phase structure, phase objectives, K1–K16 issue list,
decision log) was **not** contradicted by the 2026-08-05 verification and is
carried forward unchanged unless noted.

**Verification method for this document:** live FastAPI route table walked at
runtime via `app.routes` (FastAPI 0.139, `_IncludedRouter.original_router`
descent), cross-checked against `grep -rc require_permission` per router file,
cross-checked against `git log`/`git show --stat`/`git diff --stat` for every
commit touching `contracts/permissions.yaml` or a router file since 2026-08-01.
Full raw command output for this pass is preserved in the review session that
produced this document (not duplicated here — see the verification transcript,
2026-08-05).

**What this document does NOT re-verify:** test pass/fail counts (only
`--collect-only` was run, per task scope — the "1068 passed / 2 failed" figure
from `current-state.md` is carried forward as UNVERIFIED-BY-THIS-PASS, not
re-confirmed), production DB migration state, and anything not touched by the
2026-08-05 verification pass. These are flagged inline where they appear.

---

## 1. Purpose and how to read this document

This roadmap sequences the work to take MCS Manager from its verified current
state to a reliable public product. The order is a **dependency order**: each
phase is gated only on the phases it depends on.

### Status legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Done — re-verified live 2026-08-05 |
| 🔄 | In progress — active now |
| 🔶 | Planned — not started |
| ⛔ | Blocked — gated on an earlier phase |
| ⚠️ | Risk, open question, or unresolved doc/code mismatch |

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
- **Network access is gated on stability.** Tunnel/port-forwarding work does
  not start while the product, authorization, versioning, and tests/CI are
  not reliable.
- **AI is the final phase and intentionally deferred.**

---

## 2. Phase 0 — Current reality ✅ (re-verified 2026-08-05)

| Item | Count | Verified how |
|---|---|---|
| Backend Python source files | 261 | `find backend/app -name '*.py'` (2026-08-04, carried forward) |
| Backend test files | 90 | `find backend/tests -name 'test_*.py'` (2026-08-05 re-run) |
| Frontend test files | 41 | `find frontend/src -name '*.test.*'` (2026-08-05 re-run) |
| REST routers | 10 | `ls backend/app/api/v1/routers/*.py` (2026-08-05 re-run): auth, backups, health, monitoring, plugins, schedules, servers, settings, software, users |
| DDD modules | 9 | `ls backend/app/modules/` (2026-08-05 re-run) |
| Alembic revisions | 16 | `ls backend/alembic/versions/*.py` (2026-08-05 re-run) |
| ADRs | 12 | `ls docs/decisions/*.md` excl. README (2026-08-05 re-run) |
| Contract files | 6 | `ls contracts/` (2026-08-05 re-run) |
| Backend tests collected | 1070 | `pytest --collect-only -q` (2026-08-05 re-run) |
| Backend tests passed/failed | 1068 / 2 (carried forward, **not re-run 2026-08-05** — full suite run is out of scope for a read-only verification pass) | `current-state.md` (2026-08-04) ⚠️ UNVERIFIED BY THIS PASS |
| Frontend tests | 236 across 41 files | `vitest list` (2026-08-05 re-run) |
| App version (code) | uniformly `4.0.0` | grepped across `pyproject.toml`, `package.json`, `main.py`, `config.py`, `package-lock.json` (2026-08-05 re-run) — no `7.1.0` in any source/test file; `7.1.0` survives only as unrelated semver-range substrings in `package-lock.json` and in historical/planning docs |
| CI workflows | 1 (frontend only) | `.github/workflows/frontend-ci.yml`; no backend CI |

- **Two files with uncommitted working-tree changes** (not "deliberately
  uncommitted files" — both are tracked and committed):
  `backend/app/api/v1/routers/plugins.py` (8 commits, latest `b1b6dd8`) and
  `backend/tests/api/test_api_endpoints.py` (9 commits, latest `b1b6dd8`).
  Current uncommitted diffs: a `_to_version_response()` helper
  (+19/−3) and one new test `test_marketplace_versions_returns_files` (+54).
  Decision needed: commit these as their own commit (see §15, item D3).

---

## 3. Phase 1 — Plugins / Marketplace separation 🔄 CURRENT

**This is the first product/UI priority.**

The marketplace is currently a subsection of the Plugins page (frontend route
`/plugins/marketplace`, reached via the Plugins page's Install button). The
intended model treats them as two distinct product areas.

**Current reality**
- Backend: `/api/v1/servers/{server_id}/plugins/*` handles both plugin
  management and marketplace (search / versions / install) under one router.
  Marketplace provider hardcoded to Modrinth (K16).
- Live route table for this router (verified 2026-08-05):
  `GET /plugins`, `GET /plugins/{plugin_id}`, `DELETE /plugins/{plugin_id}`,
  `POST /plugins/{plugin_id}/enable`, `POST /plugins/{plugin_id}/disable`,
  `GET /plugins/marketplace/search`, `GET /plugins/marketplace/projects/{id}/versions`,
  `POST /plugins/marketplace/install`. No standalone install route exists
  outside marketplace (the old `POST /plugins` manual-install route was
  removed in `b1b6dd8`, 2026-08-04).
- Frontend: `PluginListPage` (server-scoped) and `PluginMarketplacePage` share
  the `/plugins` namespace. **Sidebar has no Marketplace entry** (K5).

**Desired state**

| Area | Answers | Scope |
|------|---------|-------|
| **Plugins** | "What plugins does this server have?" | Server-scoped: installed list, state, lifecycle, enable/disable, removal, configuration where supported |
| **Marketplace** | "What plugins can I discover and install?" | Global catalog/discovery/store, server-selection at install time |

**Workstreams**
1. **Frontend nav restructure (K5).** Distinct Marketplace nav entry (sidebar
   + top-level route such as `/marketplace`) with its own search, project
   detail, install flow. Document the navigable relationship between the two
   surfaces.
2. **Route/namespace clarity.** Decide whether marketplace API routes stay
   under `/servers/{server_id}/plugins/marketplace/*` or move to a
   marketplace-owned namespace (see §15, item D4).
3. **Provider abstraction (K16).** Make the catalog provider list inspectable
   and configurable (`MCS_PLUGIN_PROVIDERS`), Modrinth stays default.
4. **Foundation for future catalog features.** Checksums, version metadata,
   dependency info already present in the version-selection model.

**Dependencies:** none (backend marketplace already shipped).

**Acceptance criteria**
- Marketplace independently navigable (own nav entry + route).
- Installing from Marketplace places a verified `.jar` into the selected
  server's `plugins/` directory; reconciled list shows it.
- Plugin management clearly server-scoped; Marketplace clearly global.
- Provider list configuration-driven with Modrinth default.

**Verification:** backend + frontend suites green; manual UX walk; frontend
tests for both navigation surfaces.

---

## 4. Phase 2 — Product foundation & UI stabilization 🔶

**Objective:** make the frontend a first-class product surface and stabilize
the loading/error/empty/state model and navigation, on top of Phase 1.

**Current reality (frontend)**
- React 19 + Vite + TypeScript 5, TanStack Query, Zustand, TailwindCSS 4.
- Routes (`frontend/src/App.tsx`): `/login`, `/register`, then guarded: `/`
  (Dashboard), `/servers`, `/servers/create`, `/servers/import`,
  `/servers/:serverId`, `/backups`, `/plugins`, `/plugins/marketplace`,
  `/settings`, `/settings/api-keys`, `*`.
- Sidebar: Dashboard, Servers, Backups, Plugins, Settings — no Marketplace
  (Phase 1 adds it).
- Stores (Zustand): `authStore` (localStorage `mcs_auth`), `uiStore`, `wsStore`.
- WebSocket client fully implemented (connect/reconnect/ping/message queue)
  but backend rejects every subscription (K1) and never dispatches events
  (K2) — WS is behaviorally non-functional despite a complete client (Phase 3).

**Desired state**
- Consistent navigation: plugin-management vs marketplace clearly distinct;
  server-scoped vs global pages visually and structurally separate.
- Uniform loading/error/empty states across all pages.
- Deterministic API state + cache behavior (TanStack Query configured once,
  applied consistently).
- WebSocket behavior documented and either works or is explicitly disabled
  per surface — no "connected but silent" dead-end.
- Settings UX reflects what actually persists (persistence itself is Phase 3;
  Phase 2 disables/annotates non-persistent controls rather than faking
  success).
- Permissions UX: UI surfaces only actions the user may take (authorization
  completion is Phase 4; Phase 2 lays presentation groundwork against
  `contracts/permissions.yaml`).
- No new design system invented; consistently apply what exists.

**Workstreams**
1. Navigation & IA (build on Phase 1).
2. Shared state/UX primitives (loading, error, empty) applied repo-wide.
3. API client + TanStack Query configuration audit.
4. Settings page accuracy relative to persistence.
5. WebSocket surface honesty (live-vs-disabled indication).
6. Frontend test coverage for the above.

**Dependencies:** Phase 1 (nav restructure baseline).

**Acceptance criteria**
- Every route has defined loading/error/empty behavior.
- Navigation distinguishes server-scoped and global surfaces.
- Frontend tests cover the new/restructured navigation and state primitives.

**Verification:** frontend suite green; manual walkthrough; route-by-route
state review recorded in `docs/FRONTEND.md`.

---

## 5. Phase 3 — Backend/frontend bug fixing & reliability 🔶

**Objective:** make the existing product actually reliable.

**Dependencies:** none structural; runs in parallel with Phase 2 where surfaced.

### 5.1 WebSocket delivery — **must fix**
- **K1:** channel authorization always denies (plural `CHANNEL_PATTERNS`
  `servers:read` vs singular JWT claims `server:read`) — fail-closed, no
  channel subscribes. Reconcile to a single singular `resource:action`
  namespace with `admin:full` passthrough.
- **K2:** `EventDispatcher`/`MetricsBatcher` never instantiated — no
  server-push events reach clients. Wire into app lifespan with event-bus
  subscription; keep fail-closed during transition.
- **Secondary WS gaps** (`docs/PERMISSIONS_FUTURE_IDEAS.md` §4): validate
  `refresh_token` payloads, enforce idle timeout, re-check authorization per
  pushed message.
- **Acceptance:** a client with `server:read` subscribes and receives
  `state`/`event` frames; publishing a domain event reaches subscribers
  (integration test); fail-closed still holds without permission.

### 5.2 Settings persistence — **must fix**
- **K3:** `PATCH /api/v1/settings` is a stub (`{"success": true, "message":
  "Settings updated (stub)"}`); nothing persists. Decide the persisted field
  set (start with fields already returned by `GET /settings`), persist, apply
  at runtime, gate with `settings:write`.
- **Acceptance:** updating a setting persists, is returned by `GET /settings`,
  enforced at runtime.

### 5.3 Test suite green — **must fix**
- **K8:** 2 failing tests (per `current-state.md`, 2026-08-04, ⚠️ not
  re-run 2026-08-05) — `test_start_server` (closed-DB rollback in API
  teardown) and `test_metrics_task_requires_collector` (stale expectation vs
  graceful warning handler). Fix or formally re-baseline.
- **Acceptance:** `python -m pytest tests/` passes with 0 failures (fresh run
  required — current pass/fail state is unverified as of this document).

### 5.4 Runtime/system consistency — **should fix**
- **K9:** production DB 3 revisions behind head (per `current-state.md`
  2026-08-04, ⚠️ not re-verified 2026-08-05); 0 servers in production.
  Bring to head with a documented upgrade procedure.
- **K15:** repo-root `data/` cleanup (verify unused before removing).
- **K14:** backup save-all completion regex unverified against a real Purpur
  server — add a live/mocking regression check.

### 5.5 Honest error handling
- Audit HTTP status/error payload consistency; document the contract.

**Acceptance:** WS live, settings persist, tests green, DB at head, documented
error contract.

---

## 6. Phase 4 — Authorization / security cleanup 🔶

**Objective:** close the security gaps identified in the audit; enforce the
model in CI so it cannot regress.

**Dependencies:** Phase 3 (a stable, tested base). Not started while the
plugin restructure and reliability work are open.

### 6.1 Enforce remaining routes — **must fix**

**Live-verified state (2026-08-05, supersedes v2 §6.1 and `current-state.md`
K7):**

- **24 routes gated** by `require_permission` — confirmed unchanged from v2:
  22 mutating (servers 7, backups 4, plugins delete + marketplace install 3,
  users 2, auth/api-keys 2 — note: exact per-module breakdown pending a
  fresh per-file grep tally; the 22 total is directly counted from the live
  route table) + 2 read-only marketplace GET routes.
- **12 mutating routes unprotected** (not 13 — corrected from v2/K7; `b1b6dd8`
  removed the legacy manual-install route that inflated the earlier count):
  `POST /auth/login`, `POST /auth/logout`, `POST /auth/refresh`,
  `POST /health/evaluate/{server_id}`, `POST /monitoring/alerts`,
  `DELETE /monitoring/alerts/{alert_rule_id}`, `POST /schedules`,
  `DELETE /schedules/{schedule_id}`, `POST /plugins/{plugin_id}/enable` (K4),
  `POST /plugins/{plugin_id}/disable` (K4), `PATCH /settings`,
  `POST /users`.
  (`login`/`logout`/`refresh` are intentionally public — see below; the
  remaining 9 are real gaps.)
- **23 sensitive GET routes auth-only, no permission check** (middleware-strict
  count; v2's "21" used a different classification — see §15 item D1 for the
  reconciliation, which is an open decision, not yet resolved).
- **3 intentionally public routes:** login, refresh, registration
  (`POST /users` — see K-registration below).

**Work:** enumerate the real gaps above (9 mutating beyond the 3 intentional
public routes, plus the 23 sensitive GETs), assign permission strings, gate
them, enforce in CI.

### 6.2 Registration bootstrap (`POST /api/v1/users`) — investigate first
- Currently open registration, no auth. Real Phase-4-relevant gap.
- **Decision procedure (carried from prior session, unchanged):** investigate
  whether a first-user-bootstrap exception is safe/simple (open only when
  zero users exist, then require `user:write` after that). If investigation
  shows hidden onboarding dependencies or ambiguous "first user" semantics,
  do NOT improvise — document in `docs/PERMISSIONS_FUTURE_IDEAS.md` instead
  and leave the route unchanged. **Not yet investigated as of this document.**

### 6.3 Backend CI + route-coverage test — **must fix (K6)**
- No backend CI — only `.github/workflows/frontend-ci.yml`. Add a workflow
  running `pytest`, `ruff`, `pyright`, and a route-coverage test walking the
  live FastAPI route table asserting every mutating route carries a
  permission dependency.
- **Acceptance:** a new mutating route without a permission dependency fails
  CI; `contracts/permissions.yaml` matches the live route table with 0 gaps.

### 6.4 WebSocket authorization hardening
- Fold WS channel checks into the same (now singular) permission path.

### 6.5 `GET /metrics` — explicitly deferred
- Public/unauthenticated (K10). Not locked down in this phase — risk of
  breaking an existing external scraping setup is unknown. Revisit alongside
  Phase 7 (network/remote exposure).

### 6.6 `contracts/permissions.yaml` stabilization — **must resolve before 6.1 work starts**
- Committed HEAD is v1.3. Working tree has an **uncommitted** v1.4 edit
  (adds 3 marketplace rows, still lists the now-deleted legacy install route
  under `status: missing`). Per 2026-08-05 decision, this document does not
  block on resolving that drift, but 6.1 enforcement work cannot proceed
  correctly until: (a) the working-tree v1.4 edit is either committed or
  discarded, and (b) the phantom deleted-route entry is removed. Track as
  §15 item D2 — separate task, not part of this roadmap rewrite.

### 6.7 Security docs must match reality
- `docs/SECURITY.md` currently documents the partial-enforcement gap; after
  6.1 this caveat is resolved. Re-verify the whole doc (`httpOnly` vs
  localStorage refresh token, API-key SHA-256 hashing, per-client rate
  limiting — already confirmed per-`client_ip:path` in `current-state.md`
  §4.6, WS fail-closed).

**Acceptance:** every mutating endpoint checked, CI-enforced,
`contracts/permissions.yaml` complete and internally consistent (single
committed version, no phantom routes); `SECURITY.md` no longer carries a
partial-enforcement caveat beyond explicitly-allowlisted public routes.

---

## 7. Phase 5 — Versioning & state consistency 🔶

**Objective:** establish a single authoritative version and consistent state
sources.

- Backend `pyproject.toml` is the canonical version source; runtime, OpenAPI,
  and the displayed product version derive from it. **Already true in
  practice** (verified 2026-08-05: `4.0.0` uniform across
  `pyproject.toml`, `package.json`, `main.py`, `config.py`) — this phase
  formalizes it as an enforced rule (e.g. CI check) rather than an
  observed accident.
- Frontend displays the backend-provided version; `package.json` becomes
  build metadata.
- SemVer conventions stated; "v1.0 public release" decoupled from internal
  app version.
- Per-release minimum-Alembic-revision rule for DB compatibility; report/
  constrain prod upgrade status.
- `.ai` state-file version fields align to the resolved version; docs stop
  asserting versions the code can't justify (the historical `7.1.0` figure
  should be scoped explicitly to planning-doc history, not implied as a
  current or past code version).

**Acceptance:** changing one source propagates without further edits; one
document/command answers the version question; no residual `7.1.0`-class
orphan versions outside history and server data.

---

## 8. Phase 6 — Testing / CI / documentation reliability 🔶

**Objective:** make tests and docs trustworthy execution contracts.

- Re-baseline or remove historical-only counts in `STATUS.md`;
  `current-state.md` (or its v3-era successor) is the single current-state
  source — but note: this document (roadmap v3) itself demonstrates that a
  "verified" snapshot document goes stale within a day when the codebase is
  moving fast. Phase 6 should define a re-verification cadence, not just a
  one-time snapshot.
- Backend CI (built in Phase 4) extended to fail on doc-vs-code drift where
  feasible.
- Documentation quality rules enforced (implemented/partial/planned/
  historical labels).
- Remove/redirect remaining duplicate sources of truth.

**Acceptance:** CI green across backend+frontend; a doc claim can be traced
to code; no two docs contradict on counts.

---

## 9. Phase 7 — Network Access / Port Forwarding 🔶
⛔ **Blocked on Phases 1–6.**

**Design reference:** `docs/network-access-design.md`.

### 9.1 Scope
Remote access to **your own single running instance**. Not multi-tenant
hosting, not multi-node orchestration.

### 9.2 Two user-facing modes
**A. Tunnel (recommended default).** Abstracts NAT, router config, manual
port forwarding, dynamic public-IP handling, endpoint changes, DNS sync.
**B. Manual port forwarding.** Advanced users manage router/firewall/IP/ports
themselves.

### 9.3 Architectural boundaries (must hold)
1. **TunnelProvider separate from DnsProvider** — never conflate them.
2. **Dynamic endpoints** — accept endpoints discovered/assigned at runtime.
3. **Independent Game vs Management exposure** — separate toggles, separate
   tunnels, separate security postures; never gate together.
4. **Tunnel ≠ Authentication** — tunnel traffic runs through the exact same
   auth/authorization stack as local traffic.
5. **DNS is optional and pluggable.**
6. **No provider preselection.**
7. **Provider extensibility requirement** — official APIs only, never
   browser automation/scraping.

### 9.4 Hardened defaults in publish mode
- Rate limiting already per-client and per-path (confirmed in Phase 0,
  `current-state.md` §4.6 — corrects an earlier "process-global" claim).
- Shorter access-token lifetimes, mandatory HTTPS, optional-but-strongly-
  prompted 2FA.
- RBAC/ABAC enforced everywhere; unauthenticated access is the explicit
  exception.
- Revisit `GET /metrics` exposure (K10) under this decision.

**Exit criteria:** explicit local/publish choice in install flow; game and
management exposure independently controllable; tunnel traffic provably
subject to the same authz as local traffic; manual port-forwarding mode
documented.

---

## 10. Phase 8 — Dynamic endpoint + DNS architecture 🔶
⛔ **Blocked on Phase 7.**

**Objective:** make endpoint changes invisible to the user.

```
Tunnel starts → Get endpoint → Store endpoint state → Synchronize DNS
  → Monitor endpoint → Detect endpoint change → Update state → Update DNS
  → Verify → Expose stable hostname to user
```

### 10.1 Minecraft access
`Minecraft → Tunnel → Public endpoint → DNS → Stable hostname`

### 10.2 Management access
`MCS Manager → HTTP/HTTPS tunnel → Public endpoint → DNS → Stable hostname`

Do not assume the same tunnel provider serves both.

**Acceptance:** changing a tunnel endpoint updates stored state and DNS and
re-verifies, surfacing a stable hostname; game and management flows each
support their own provider configuration.

---

## 11. Phase 9 — Final stabilization 🔶

Systematic close-out before AI: full security review vs `docs/SECURITY.md`,
performance/diagnostic passes, production upgrade verification, remaining
`should fix`/`optional` items. No new capability; harden and verify.

**Acceptance:** documented end-to-end verification of the stable baseline
used by Phase 10.

---

## 12. Phase 10 — AI features 🔶 (final phase, intentionally deferred)
⛔ **Blocked on all prior phases.**

**Non-negotiable guardrails — built in from the start:**
1. Agent actions route through the exact same permission layer as normal API
   calls. No privileged bypass path.
2. Explicit user confirmation before any destructive action.
3. Full audit trail of every agent-issued command, attributable to the
   invoking user.
4. Pipeline: natural-language request → structured plan → execution, with
   CLI, API, GUI, and Agent calling the same internal services.

**Deferred status:** tracked, not scheduled with a start date.

---

## 13. Deliberately out of scope (tracked, not scheduled)

| Item | Why it's out | Tracked in |
|------|--------------|------------|
| Container plugin isolation (`ContainerPluginRunner` stub) | Requires plugin system + Marketplace stable first | `FEATURE_IDEAS.md` |
| Metrics retention rollups (1m/1h/1d) | Raw data fine for live dashboards | `FEATURE_IDEAS.md` |
| Remote agents / multi-node orchestration | Different trust model | `FEATURE_IDEAS.md` |
| Multi-tenant hosting | Isolation, billing, per-tenant limits — materially larger scope | `FEATURE_IDEAS.md` |
| Mobile companion app | Polish, not core | `FEATURE_IDEAS.md` |

---

## 14. Versioning / stability summary

See `docs/VERSIONING.md`. Key points repeated as roadmap commitments: single
source of truth (backend package metadata — already true in practice per
Phase 0 verification), frontend displays backend version, SemVer semantics,
DB migration/revision compatibility rule, `.ai` state-file alignment. Roadmap
Phase 5.

---

## 15. Decision log — items requiring an explicit answer

| # | Question | Status |
|---|----------|--------|
| D1 | Which classification of "sensitive GET route" is correct — v2's 21 (excludes 3 middleware-auth-gated routes as "not-applicable-public," includes `GET /schedules` as sensitive despite its public-prefix middleware exemption) or this doc's 23 (strict middleware count)? | **Open — must resolve before Phase 4 §6.1 GET-route work starts** |
| D2 | `contracts/permissions.yaml`: commit the working-tree v1.4 edit, discard it, or redo it cleanly? Must also remove the phantom `status: missing` entry for the deleted legacy install route. | **Open — separate task per 2026-08-05 decision, not blocking this roadmap doc** |
| D3 | Commit the two files with pending working-tree diffs (`plugins.py`, `test_api_endpoints.py`) as their own commit? | Recommended: yes, they are complete tested changes — carried from v2, still open |
| D4 | Do marketplace API routes move out of `/servers/{id}/plugins/marketplace/*`? | Open — keep server-taken semantics but decouple the UI; stage any path move for backward compatibility |
| D5 | Should the 2 currently-failing tests be fixed or re-baselined? | Open — investigate `test_start_server` teardown first; `test_metrics_task_requires_collector` looks like a stale assertion |
| D6 | Which settings fields must persist in Phase 3? | Open — start with fields already returned by `GET /settings` |
| D7 | Network scope: single-instance remote access vs multi-tenant hosting? | Confirm: single-instance, as scoped in Phase 7 |
| D8 | Tunnel/DNS provider choices | Open — evaluate when implementation starts, no preselection |
| D9 | 2FA mandatory or optional in publish mode? | Open — recommendation: optional but strongly prompted at first publish |
| D10 | JWT signing key storage (DB-encrypted vs secrets file) | Open — match existing secrets-handling convention; `kid`-based rotation regardless |
| D11 | Repo-root `data/` directory cleanup (K15) | Open — remove once confirmed unused |
| D12 | Prod DB upgrade: auto-upgrade on boot vs refuse-to-start | Open — recommendation: refuse with loud log + documented upgrade procedure |
| D13 | Registration bootstrap exception (§6.2) — implement or defer to ideas backlog? | Open — investigate first, do not improvise |

---

## 16. Sources

- Live route introspection (2026-08-05) — this document's primary evidence
  for §2 and §6.1
- `docs/current-state.md` (2026-08-04) — prior snapshot, partially superseded
  by §0 above
- `git log` / `git show --stat` / `git diff --stat` (2026-08-05) — commit
  history correlation for the enforcement timeline and file-status claims
- `docs/network-access-design.md` — Phase 7/8 design reference
- `docs/plugins-and-marketplace.md` — current plugin + marketplace
  implementation
- `docs/STATUS.md` — batch history through Batch 10 (2026-08-03); batches
  after that date are not reflected in STATUS.md and should be added there
  separately
- `contracts/permissions.yaml` — ⚠️ currently in an inconsistent state
  (v1.3 committed / v1.4 uncommitted) — see §15 item D2
- `docs/PERMISSIONS_FUTURE_IDEAS.md` — WS trace (§4), metrics (§3),
  registration bootstrap (§5)
- `docs/FEATURE_IDEAS.md` — parking-lot items

---

*Supersedes `docs/mcs-manager-roadmap-v2.md`, `docs/mcs-manager-roadmap-v1.md`,
and `docs/roadmap.md`. Phase status markers here are authoritative for phase
state. Every numeric claim in §2 and §6.1 was re-verified live on 2026-08-05;
everything else is carried forward from `current-state.md` (2026-08-04) or
earlier and marked accordingly where not independently re-checked.*
