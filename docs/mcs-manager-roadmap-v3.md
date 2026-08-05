# MCS Manager — Roadmap v3 (Single Source of Truth)

**Status:** Living planning document — engineering-owned
**Version:** 4.0 · **Last updated:** 2026-08-05
**Baseline:** live FastAPI route introspection (2026-08-05) + `docs/current-state.md` (2026-08-04) + git history

> **This is the only authoritative roadmap.** `docs/roadmap.md` (v0), `mcs-manager-roadmap-v1.md`,
> and `mcs-manager-roadmap-v2.md` are historical reference only. Where they disagree with this
> document, this document wins: every number below was re-verified live on 2026-08-05, not carried
> forward from an earlier snapshot.

**TL;DR:** Phase 1 (Plugins/Marketplace split) is current. Nothing in the phase plan, K‑issue list,
or decision log changed from v2 — this revision exists solely to correct four numbers that drifted
after commit `b1b6dd8` deleted a legacy route (see §0). If you already know v2, skip to §0's table
and then to whatever phase you're working in.

---

## 0. What changed since v2, and why

v2 (2026-08-04) was internally consistent with its own baseline but went stale within 24 hours:
commit `b1b6dd8`, later that same day, deleted a legacy route that both `current-state.md` and v2
§6.1 still counted as unprotected. Live re-verification on 2026-08-05 found four discrepancies:

| Claim | v2 said | Live re-check (2026-08-05) | Resolution |
|---|---|---|---|
| Mutating routes without permission enforcement | 13 | **12** | `b1b6dd8` removed the legacy `POST .../plugins` manual-install route, which v2's matrix still listed as `status: missing`. |
| Sensitive GET routes without permission enforcement | 21 | **23** | v2 used a non-middleware classification (treated 3 auth-gated routes as public-safe, and one public-prefix route as sensitive). This document uses the strict live-middleware count; the classification disagreement itself is unresolved — see D1. |
| "Two deliberately uncommitted files" (`plugins.py`, `test_api_endpoints.py`) | Not part of any committed baseline | **Both are tracked, committed files** (8–9 commits each), each with a small uncommitted working-tree diff on top | Wording corrected — see §2. |
| `contracts/permissions.yaml` version | v1.4, implied settled | **v1.3 is committed HEAD; v1.4 exists only as an uncommitted edit** (adds 3 marketplace rows, still references the deleted route) | Tracked as open — see D2. Not resolved by this document. |

Everything else in v2 — phase structure, phase objectives, the K1–K16 issue list, the decision
log — is unchanged and carried forward.

**How this pass was verified:** live FastAPI route table walked at runtime (`app.routes`, FastAPI
0.139), cross-checked against `grep -rc require_permission` per router file, cross-checked against
`git log` / `git show --stat` / `git diff --stat` for every commit touching `contracts/permissions.yaml`
or a router file since 2026-08-01. Raw command output lives in the 2026-08-05 review session
transcript, not duplicated here.

**Explicitly not re-verified in this pass** (carried forward as-is, flagged inline where they
appear): test pass/fail counts (only `--collect-only` was run), production DB migration state, and
anything else outside the scope of this read-only pass.

---

## 1. How to read this document

The roadmap sequences work in **dependency order** — each phase is gated only on the phases it
actually depends on, not on document order.

**Status legend**

| Symbol | Meaning |
|--------|---------|
| ✅ | Done — re-verified live 2026-08-05 |
| 🔄 | In progress — active now |
| 🔶 | Planned — not started |
| ⛔ | Blocked — gated on an earlier phase |
| ⚠️ | Risk, open question, or unresolved doc/code mismatch |

**Bug classification**

| Class | Meaning |
|-------|---------|
| Must fix | Blocks a phase exit criterion or a security/availability claim |
| Should fix | Real defect; can be deferred within a phase, but must stay scheduled |
| Optional | Quality-of-life; can be dropped with a documented reason |
| Known limitation | Accepted behavior, documented, not scheduled |
| Doc-only | Documentation correction, no code change |
| Future work | Tracked in a later phase's backlog, not current scope |

**Governing product direction**
- **Foundation before capability.** Coherent product structure and reliability come before
  advanced features.
- **Plugins ≠ Marketplace.** Plugins = installed plugins on a selected server. Marketplace =
  global catalog/discovery. Distinct surfaces.
- **Network access is gated on stability.** Tunnel/port-forwarding work doesn't start until
  product, authorization, versioning, and CI are reliable.
- **AI is the final phase**, intentionally deferred.

---

## 2. Phase 0 — Current reality ✅ (re-verified 2026-08-05)

| Item | Count | Verified how |
|---|---|---|
| Backend Python source files | 261 | `find backend/app -name '*.py'` (2026-08-04) |
| Backend test files | 90 | `find backend/tests -name 'test_*.py'` |
| Frontend test files | 41 | `find frontend/src -name '*.test.*'` |
| REST routers | 10 | `ls backend/app/api/v1/routers/*.py`: auth, backups, health, monitoring, plugins, schedules, servers, settings, software, users |
| DDD modules | 9 | `ls backend/app/modules/` |
| Alembic revisions | 16 | `ls backend/alembic/versions/*.py` |
| ADRs | 12 | `ls docs/decisions/*.md` (excl. README) |
| Contract files | 6 | `ls contracts/` |
| Backend tests collected | 1,070 | `pytest --collect-only -q` |
| Backend tests passed/failed | 1,068 / 2 ⚠️ **not re-run 2026-08-05** | carried from `current-state.md` (2026-08-04) |
| Frontend tests | 236 across 41 files | `vitest list` |
| App version (code) | `4.0.0` everywhere | grepped `pyproject.toml`, `package.json`, `main.py`, `config.py`, `package-lock.json`; `7.1.0` appears only as an unrelated semver-range substring and in historical planning docs |
| CI workflows | 1 (frontend only) | `.github/workflows/frontend-ci.yml` — no backend CI |

All counts re-run 2026-08-05 unless flagged.

- **Two files carry uncommitted working-tree changes** (correcting v2's "deliberately uncommitted"
  wording — both are tracked and committed): `backend/app/api/v1/routers/plugins.py` (8 commits,
  latest `b1b6dd8`) and `backend/tests/api/test_api_endpoints.py` (9 commits, latest `b1b6dd8`).
  The pending diff is a `_to_version_response()` helper (+19/−3) and one new test,
  `test_marketplace_versions_returns_files` (+54). Needs a decision — see D3.

---

## 3. Phase 1 — Plugins / Marketplace separation 🔄 CURRENT

**This is the first product/UI priority.**

Marketplace is currently a subsection of the Plugins page (`/plugins/marketplace`, reached via the
Plugins page's Install button). The intended model treats them as two distinct product areas:

| Area | Answers | Scope |
|------|---------|-------|
| **Plugins** | "What plugins does this server have?" | Server-scoped: installed list, state, lifecycle, enable/disable, removal, configuration |
| **Marketplace** | "What plugins can I discover and install?" | Global catalog/discovery/store; server selection happens at install time |

**Current reality**
- Backend: one router, `/api/v1/servers/{server_id}/plugins/*`, handles both plugin management and
  marketplace (search / versions / install). Marketplace provider hardcoded to Modrinth (K16).
- Live route table (verified 2026-08-05): `GET /plugins`, `GET /plugins/{plugin_id}`,
  `DELETE /plugins/{plugin_id}`, `POST /plugins/{plugin_id}/enable`,
  `POST /plugins/{plugin_id}/disable`, `GET /plugins/marketplace/search`,
  `GET /plugins/marketplace/projects/{id}/versions`, `POST /plugins/marketplace/install`. There is
  no standalone install route outside marketplace — the old `POST /plugins` manual-install route
  was removed in `b1b6dd8` (2026-08-04).
- Frontend: `PluginListPage` (server-scoped) and `PluginMarketplacePage` share the `/plugins`
  namespace. Sidebar has no Marketplace entry (K5).

**Workstreams**
1. **Frontend nav restructure (K5).** Give Marketplace its own sidebar entry and top-level route
   (e.g. `/marketplace`) with its own search, project detail, and install flow. Document how the
   two surfaces relate.
2. **Route/namespace clarity.** Decide whether marketplace API routes stay under
   `/servers/{server_id}/plugins/marketplace/*` or move to a marketplace-owned namespace (D4).
3. **Provider abstraction (K16).** Make the catalog provider list inspectable/configurable
   (`MCS_PLUGIN_PROVIDERS`); Modrinth stays the default.
4. **Foundation for future catalog features.** Checksums, version metadata, and dependency info
   already exist in the version-selection model — reuse them.

**Dependencies:** none — backend marketplace already shipped.

**Acceptance criteria**
- Marketplace is independently navigable (own nav entry + route).
- Installing from Marketplace places a verified `.jar` in the selected server's `plugins/`
  directory; the reconciled list reflects it.
- Plugin management reads as server-scoped; Marketplace reads as global.
- Provider list is configuration-driven, Modrinth default.

**Verification:** backend + frontend suites green; manual UX walk; frontend tests for both
navigation surfaces.

---

## 4. Phase 2 — Product foundation & UI stabilization 🔶

**Objective:** make the frontend a first-class, stable surface — consistent loading/error/empty
states and navigation — on top of Phase 1.

**Current reality (frontend)**
- React 19 + Vite + TypeScript 5, TanStack Query, Zustand, TailwindCSS 4.
- Routes (`frontend/src/App.tsx`): `/login`, `/register`, then guarded: `/` (Dashboard),
  `/servers`, `/servers/create`, `/servers/import`, `/servers/:serverId`, `/backups`, `/plugins`,
  `/plugins/marketplace`, `/settings`, `/settings/api-keys`, `*`.
- Sidebar: Dashboard, Servers, Backups, Plugins, Settings — no Marketplace (added in Phase 1).
- Zustand stores: `authStore` (localStorage `mcs_auth`), `uiStore`, `wsStore`.
- WebSocket client is fully implemented (connect/reconnect/ping/message queue), but the backend
  rejects every subscription (K1) and never dispatches events (K2) — a complete client that is
  behaviorally non-functional (fixed in Phase 3).

**Desired state**
- Navigation clearly separates plugin-management from marketplace, and server-scoped from global
  pages.
- Loading/error/empty states are uniform across all pages.
- API state and cache behavior are deterministic (TanStack Query configured once, applied
  consistently).
- WebSocket behavior is documented and either works or is explicitly disabled per surface — no
  "connected but silent" dead end.
- Settings UX reflects what actually persists. Persistence itself lands in Phase 3; Phase 2
  disables/annotates non-persistent controls rather than faking success.
- Permissions UX shows only actions the user may take. Authorization enforcement lands in Phase 4;
  Phase 2 lays the presentation groundwork against `contracts/permissions.yaml`.
- No new design system — apply what already exists, consistently.

**Workstreams**
1. Navigation & IA, building on Phase 1.
2. Shared loading/error/empty primitives, applied repo-wide.
3. API client + TanStack Query configuration audit.
4. Settings page accuracy relative to actual persistence.
5. WebSocket surface honesty (live vs. explicitly disabled).
6. Frontend test coverage for all of the above.

**Dependencies:** Phase 1 (nav restructure baseline).

**Acceptance criteria**
- Every route has defined loading/error/empty behavior.
- Navigation distinguishes server-scoped from global surfaces.
- Frontend tests cover the restructured navigation and state primitives.

**Verification:** frontend suite green; manual walkthrough; route-by-route state review recorded
in `docs/FRONTEND.md`.

---

## 5. Phase 3 — Backend/frontend bug fixing & reliability 🔶

**Objective:** make the existing product actually reliable.

**Dependencies:** none structural — runs in parallel with Phase 2 where the two overlap.

### 5.1 WebSocket delivery — must fix
- **K1:** channel authorization always denies — plural `CHANNEL_PATTERNS` (`servers:read`) vs.
  singular JWT claims (`server:read`) — fail-closed, so no channel ever subscribes. Reconcile to a
  single singular `resource:action` namespace with an `admin:full` passthrough.
- **K2:** `EventDispatcher`/`MetricsBatcher` are never instantiated, so no server-push event ever
  reaches a client. Wire both into the app lifespan via event-bus subscription; stay fail-closed
  during the transition.
- **Secondary WS gaps** (`docs/PERMISSIONS_FUTURE_IDEAS.md` §4): validate `refresh_token`
  payloads, enforce idle timeout, re-check authorization per pushed message.
- **Acceptance:** a client with `server:read` subscribes and receives `state`/`event` frames;
  publishing a domain event reaches subscribers (integration test); fail-closed still holds
  without permission.

### 5.2 Settings persistence — must fix
- **K3:** `PATCH /api/v1/settings` is a stub (`{"success": true, "message": "Settings updated
  (stub)"}`) — nothing persists. Decide the persisted field set (start with what `GET /settings`
  already returns), persist it, apply it at runtime, gate with `settings:write`.
- **Acceptance:** updating a setting persists, is returned by `GET /settings`, and is enforced at
  runtime.

### 5.3 Test suite green — must fix
- **K8:** 2 failing tests (per `current-state.md`, 2026-08-04, ⚠️ not re-run 2026-08-05):
  `test_start_server` (closed-DB rollback in API teardown) and
  `test_metrics_task_requires_collector` (stale expectation vs. graceful warning handler). Fix or
  formally re-baseline.
- **Acceptance:** a fresh `python -m pytest tests/` run passes with 0 failures.

### 5.4 Runtime/system consistency — should fix
- **K9:** production DB is 3 revisions behind head (per `current-state.md`, 2026-08-04, ⚠️ not
  re-verified 2026-08-05); 0 servers in production. Bring to head with a documented upgrade
  procedure.
- **K15:** clean up the repo-root `data/` directory (confirm unused first).
- **K14:** backup save-all completion regex is unverified against a real Purpur server — add a
  live/mocking regression check.

### 5.5 Honest error handling
- Audit HTTP status/error payload consistency; document the contract.

**Acceptance:** WS live, settings persist, tests green, DB at head, error contract documented.

---

## 6. Phase 4 — Authorization / security cleanup 🔶

**Objective:** close the security gaps the audit found, then enforce the model in CI so it can't
regress.

**Dependencies:** Phase 3 (a stable, tested base). Not started while the plugin restructure and
reliability work are open.

### 6.1 Enforce remaining routes — must fix

**Live-verified state (2026-08-05), superseding v2 §6.1 and `current-state.md` K7:**

- **24 routes are gated** by `require_permission` — unchanged from v2: 22 mutating (servers 7,
  backups 4, plugins-delete + marketplace-install 3, users 2, auth/api-keys 2 — the per-module
  breakdown is pending a fresh per-file grep tally, but the 22 total is a direct count from the
  live route table) + 2 read-only marketplace GET routes.
- **12 mutating routes are unprotected**, not 13 — corrected from v2/K7, since `b1b6dd8` removed
  the legacy manual-install route that inflated the earlier count:
  `POST /auth/login`, `POST /auth/logout`, `POST /auth/refresh`,
  `POST /health/evaluate/{server_id}`, `POST /monitoring/alerts`,
  `DELETE /monitoring/alerts/{alert_rule_id}`, `POST /schedules`,
  `DELETE /schedules/{schedule_id}`, `POST /plugins/{plugin_id}/enable` (K4),
  `POST /plugins/{plugin_id}/disable` (K4), `PATCH /settings`, `POST /users`.
  Of these, `login`/`logout`/`refresh` are intentionally public; the other **9** are real gaps.
- **23 sensitive GET routes** are auth-only with no permission check (strict middleware count —
  v2's "21" used a different classification; reconciling the two is an open decision, D1).
- **3 intentionally public routes:** login, refresh, registration (`POST /users` — see §6.2).

**Work:** gate the real gaps (9 mutating routes beyond the 3 intentional public ones, plus the 23
sensitive GETs) with permission strings, and enforce in CI.

### 6.2 Registration bootstrap (`POST /api/v1/users`) — investigate first
- Registration is currently open with no auth — a real Phase 4 gap.
- **Decision procedure (carried from prior session, unchanged):** investigate whether a
  first-user-bootstrap exception is safe and simple (open only while zero users exist, then
  require `user:write`). If the investigation surfaces hidden onboarding dependencies or
  ambiguous "first user" semantics, don't improvise — document the finding in
  `docs/PERMISSIONS_FUTURE_IDEAS.md` and leave the route unchanged. **Not yet investigated.**

### 6.3 Backend CI + route-coverage test — must fix (K6)
- No backend CI exists — only `.github/workflows/frontend-ci.yml`. Add a workflow running
  `pytest`, `ruff`, `pyright`, and a route-coverage test that walks the live FastAPI route table
  and asserts every mutating route carries a permission dependency.
- **Acceptance:** a new mutating route without a permission dependency fails CI;
  `contracts/permissions.yaml` matches the live route table with zero gaps.

### 6.4 WebSocket authorization hardening
- Fold WS channel checks into the same (now singular) permission path.

### 6.5 `GET /metrics` — explicitly deferred
- Public and unauthenticated (K10). Not locked down in this phase — the risk of breaking an
  existing external scraping setup is unknown. Revisit alongside Phase 7.

### 6.6 `contracts/permissions.yaml` stabilization — must resolve before 6.1 starts
- Committed HEAD is v1.3. The working tree has an **uncommitted** v1.4 edit (adds 3 marketplace
  rows, still lists the now-deleted legacy install route under `status: missing`). This document
  doesn't block on resolving that drift, but 6.1 can't proceed correctly until (a) the v1.4 edit
  is committed or discarded, and (b) the phantom deleted-route entry is removed. Tracked as D2 —
  a separate task, not part of this roadmap rewrite.

### 6.7 Security docs must match reality
- `docs/SECURITY.md` currently documents the partial-enforcement gap; 6.1 resolves that caveat.
  Re-verify the whole doc afterward: `httpOnly` vs. localStorage refresh token, API-key SHA-256
  hashing, per-client rate limiting (already confirmed per-`client_ip:path` in
  `current-state.md` §4.6), WS fail-closed behavior.

**Acceptance:** every mutating endpoint checked and CI-enforced; `contracts/permissions.yaml`
complete and internally consistent (single committed version, no phantom routes);
`SECURITY.md` carries no partial-enforcement caveat beyond the explicitly allow-listed public
routes.

---

## 7. Phase 5 — Versioning & state consistency 🔶

**Objective:** one authoritative version, consistent state sources.

- Backend `pyproject.toml` is the canonical version source; runtime, OpenAPI, and the displayed
  product version derive from it. **Already true in practice** (verified 2026-08-05: `4.0.0`
  uniform across `pyproject.toml`, `package.json`, `main.py`, `config.py`) — this phase formalizes
  it with an enforced rule (e.g. a CI check) rather than leaving it an observed accident.
- Frontend displays the backend-provided version; `package.json` becomes build metadata only.
- SemVer conventions are stated explicitly; "v1.0 public release" is decoupled from the internal
  app version.
- A per-release minimum-Alembic-revision rule governs DB compatibility; report/constrain
  production upgrade status against it.
- `.ai` state-file version fields align to the resolved version; docs stop asserting versions the
  code can't justify (the historical `7.1.0` figure should be scoped explicitly to planning-doc
  history, not implied as a current or past code version).

**Acceptance:** changing one source propagates everywhere without further edits; one
document/command answers the version question; no residual `7.1.0`-class orphan versions outside
history and server data.

---

## 8. Phase 6 — Testing / CI / documentation reliability 🔶

**Objective:** make tests and docs trustworthy execution contracts.

- Re-baseline or remove historical-only counts in `STATUS.md`; `current-state.md` (or its v3-era
  successor) remains the single current-state source. Worth noting: this document is itself proof
  that a "verified" snapshot goes stale within a day when the codebase moves fast — Phase 6 should
  define a re-verification cadence, not just take another one-time snapshot.
- Backend CI (built in Phase 4) extends to fail on doc-vs-code drift where feasible.
- Documentation quality rules enforced (implemented/partial/planned/historical labels).
- Remaining duplicate sources of truth removed or redirected.

**Acceptance:** CI green across backend and frontend; any doc claim traces to code; no two docs
contradict on counts.

---

## 9. Phase 7 — Network access / port forwarding 🔶
⛔ Blocked on Phases 1–6.

**Design reference:** `docs/network-access-design.md`.

**Scope:** remote access to **your own single running instance** — not multi-tenant hosting, not
multi-node orchestration.

**Two user-facing modes**
- **A. Tunnel (recommended default).** Abstracts NAT, router config, manual port forwarding,
  dynamic public-IP handling, endpoint changes, DNS sync.
- **B. Manual port forwarding.** Advanced users manage router/firewall/IP/ports themselves.

**Architectural boundaries that must hold**
1. `TunnelProvider` stays separate from `DnsProvider` — never conflate them.
2. Dynamic endpoints — accept endpoints discovered/assigned at runtime.
3. Game and management exposure are independent — separate toggles, separate tunnels, separate
   security postures; never gate them together.
4. Tunnel ≠ authentication — tunnel traffic runs through the exact same auth/authorization stack
   as local traffic.
5. DNS is optional and pluggable.
6. No provider preselection.
7. Provider extensibility uses official APIs only — never browser automation or scraping.

**Hardened defaults in publish mode**
- Rate limiting is already per-client and per-path (confirmed in Phase 0, `current-state.md` §4.6
  — corrects an earlier "process-global" claim).
- Shorter access-token lifetimes, mandatory HTTPS, optional-but-strongly-prompted 2FA.
- RBAC/ABAC enforced everywhere; unauthenticated access is the explicit exception.
- Revisit `GET /metrics` exposure (K10) under this decision.

**Exit criteria:** explicit local/publish choice in the install flow; game and management exposure
independently controllable; tunnel traffic provably subject to the same authz as local traffic;
manual port-forwarding mode documented.

---

## 10. Phase 8 — Dynamic endpoint + DNS architecture 🔶
⛔ Blocked on Phase 7.

**Objective:** make endpoint changes invisible to the user.

```
Tunnel starts → Get endpoint → Store endpoint state → Synchronize DNS
  → Monitor endpoint → Detect endpoint change → Update state → Update DNS
  → Verify → Expose stable hostname to user
```

- **Minecraft access:** `Minecraft → Tunnel → Public endpoint → DNS → Stable hostname`
- **Management access:** `MCS Manager → HTTP/HTTPS tunnel → Public endpoint → DNS → Stable hostname`

Don't assume the same tunnel provider serves both.

**Acceptance:** changing a tunnel endpoint updates stored state and DNS and re-verifies, surfacing
a stable hostname; game and management flows each support their own provider configuration.

---

## 11. Phase 9 — Final stabilization 🔶

Systematic close-out before AI: full security review against `docs/SECURITY.md`,
performance/diagnostic passes, production upgrade verification, remaining should-fix/optional
items. No new capability — harden and verify what exists.

**Acceptance:** documented end-to-end verification of the stable baseline Phase 10 builds on.

---

## 12. Phase 10 — AI features 🔶 (final phase, intentionally deferred)
⛔ Blocked on all prior phases.

**Non-negotiable guardrails, built in from the start:**
1. Agent actions route through the exact same permission layer as normal API calls — no privileged
   bypass path.
2. Explicit user confirmation before any destructive action.
3. Full audit trail of every agent-issued command, attributable to the invoking user.
4. Pipeline: natural-language request → structured plan → execution, with CLI, API, GUI, and Agent
   all calling the same internal services.

**Status:** tracked, not scheduled with a start date.

---

## 13. Deliberately out of scope (tracked, not scheduled)

| Item | Why it's out | Tracked in |
|------|--------------|------------|
| Container plugin isolation (`ContainerPluginRunner` stub) | Requires a stable plugin system + Marketplace first | `FEATURE_IDEAS.md` |
| Metrics retention rollups (1m/1h/1d) | Raw data is fine for live dashboards | `FEATURE_IDEAS.md` |
| Remote agents / multi-node orchestration | Different trust model | `FEATURE_IDEAS.md` |
| Multi-tenant hosting | Isolation, billing, per-tenant limits — materially larger scope | `FEATURE_IDEAS.md` |
| Mobile companion app | Polish, not core | `FEATURE_IDEAS.md` |

---

## 14. Versioning / stability summary

See `docs/VERSIONING.md`. Roadmap commitments, repeated here: backend package metadata is the
single source of truth (already true in practice, per Phase 0); the frontend displays the backend
version; SemVer semantics apply; a DB migration/revision compatibility rule is enforced; `.ai`
state-file version fields stay aligned. Owned by Phase 5.

---

## 15. Decision log — items needing an explicit answer

| # | Question | Status |
|---|----------|--------|
| D1 | Which "sensitive GET route" classification is correct — v2's 21 (excludes 3 middleware-auth-gated routes as not-applicable-public, includes `GET /schedules` as sensitive despite its public-prefix exemption) or this doc's 23 (strict middleware count)? | Open — must resolve before Phase 4 §6.1 GET-route work starts |
| D2 | `contracts/permissions.yaml`: commit the working-tree v1.4 edit, discard it, or redo it cleanly? Also remove the phantom `status: missing` entry for the deleted legacy install route. | Open — separate task, not blocking this roadmap doc |
| D3 | Commit the two files with pending working-tree diffs (`plugins.py`, `test_api_endpoints.py`) as their own commit? | Recommended: yes — complete, tested changes. Carried from v2, still open. |
| D4 | Do marketplace API routes move out of `/servers/{id}/plugins/marketplace/*`? | Open — keep server-taken semantics but decouple the UI; stage any path move for backward compatibility |
| D5 | Should the 2 currently-failing tests be fixed or re-baselined? | Open — investigate `test_start_server` teardown first; `test_metrics_task_requires_collector` looks like a stale assertion |
| D6 | Which settings fields must persist in Phase 3? | Open — start with fields already returned by `GET /settings` |
| D7 | Network scope: single-instance remote access vs. multi-tenant hosting? | Confirmed: single-instance, as scoped in Phase 7 |
| D8 | Tunnel/DNS provider choices | Open — evaluate at implementation time, no preselection |
| D9 | 2FA mandatory or optional in publish mode? | Open — recommendation: optional but strongly prompted at first publish |
| D10 | JWT signing key storage (DB-encrypted vs. secrets file) | Open — match existing secrets-handling convention; `kid`-based rotation regardless |
| D11 | Repo-root `data/` directory cleanup (K15) | Open — remove once confirmed unused |
| D12 | Prod DB upgrade: auto-upgrade on boot vs. refuse-to-start? | Open — recommendation: refuse, with a loud log and a documented upgrade procedure |
| D13 | Registration bootstrap exception (§6.2) — implement or defer to ideas backlog? | Open — investigate first, don't improvise |

---

## 16. Sources

- Live route introspection (2026-08-05) — primary evidence for §2 and §6.1
- `docs/current-state.md` (2026-08-04) — prior snapshot, partially superseded by §0
- `git log` / `git show --stat` / `git diff --stat` (2026-08-05) — commit history correlation for
  the enforcement timeline and file-status claims
- `docs/network-access-design.md` — Phase 7/8 design reference
- `docs/plugins-and-marketplace.md` — current plugin + marketplace implementation
- `docs/STATUS.md` — batch history through Batch 10 (2026-08-03); later batches aren't reflected
  yet and should be added separately
- `contracts/permissions.yaml` — ⚠️ currently inconsistent (v1.3 committed / v1.4 uncommitted),
  see D2
- `docs/PERMISSIONS_FUTURE_IDEAS.md` — WS trace (§4), metrics (§3), registration bootstrap (§5)
- `docs/FEATURE_IDEAS.md` — parking-lot items

---

*Supersedes `mcs-manager-roadmap-v2.md`, `mcs-manager-roadmap-v1.md`, and `docs/roadmap.md`. Phase
status markers here are authoritative for phase state. Every numeric claim in §2 and §6.1 was
re-verified live on 2026-08-05; everything else is carried forward from `current-state.md`
(2026-08-04) or earlier, and flagged inline where it wasn't independently re-checked.*
