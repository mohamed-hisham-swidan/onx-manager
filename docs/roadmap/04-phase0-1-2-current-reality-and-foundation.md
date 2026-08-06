# MCS Manager — Execution Track: Phases 0–2 (Current Reality, Structure, Foundation)

**Part V** of the Engineering Blueprint V4 — the actual phase plan. This file covers **Phase 0
(current reality)**, **Phase 1 (Plugins/Marketplace separation)**, and **Phase 2 (Product Foundation &
UI stabilization)**. It is the first execution-track file a contributor reads, and it is where the
"current reality" each later phase is checked against lives.

**Last updated:** 2026-08-06
**Supersedes:** `mcs-manager-roadmap-v4.md` Volumes 1–3 (now historical baseline). Status indicators
below use the roadmap legend: ✅ done, 🔄 in progress, 🔶 planned, ⛔ blocked, ⚠️ risk/open question.

---

## 0. How the execution track works

### 0.1 Status legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Done — verified, with citation |
| 🔄 | In progress — active now |
| 🔶 | Planned — not started |
| ⛔ | Blocked — gated on an earlier phase |
| ⚠️ | Risk, open question, or unresolved doc/code mismatch |

### 0.2 Bug classification

| Class | Meaning |
|-------|---------|
| Must fix | Blocks a phase exit criterion or a security/availability claim |
| Should fix | Real defect; can be deferred within a phase, but must stay scheduled |
| Optional | Quality-of-life; can be dropped with a documented reason |
| Known limitation | Accepted behavior, documented, not scheduled |
| Doc-only | Documentation correction, no code change |
| Future work | Tracked in a later phase's backlog, not current scope |

### 0.3 Evidence discipline (the governing rule for this track)

Every count or claim in the execution-track files is one of three things, and is labeled as such:

1. **Carried** from a prior verified source (marked "carried from v3" or with batch/date) — *not
   re-verified by this revision.* If an acceptance check depends on a carried number, the check must
   re-verify it live before claiming done.
2. **Verified** — checked against source, tests, or the filesystem during this revision.
3. **New** — this document's own analysis, marked as such.

The reason this rule is load-bearing: commit `b1b6dd8` (2026-08-04) made the v3 roadmap stale within
24 hours of its verification date. A snapshot is never "the truth"; it is the truth *as of a moment*.
Part I, `01-engineering-principles.md` §1, states this fully; here it is stated as the operating rule
of every phase below. Re-verification cadence is itself a Phase 6 deliverable (`06`), not assumed.

### 0.4 Governing product direction (carried from V4, unchanged)

- **Foundation before capability.** Structure and reliability come before advanced features.
- **Plugins ≠ Marketplace.** Plugins = installed plugins on a selected server. Marketplace = global
  catalog/discovery. Distinct surfaces.
- **Network access is gated on stability.** Tunnel/port-forwarding work doesn't start until product,
  authorization, versioning, and CI are reliable.
- **AI is the final phase**, intentionally deferred.
- **Speculative infrastructure is not roadmap.** Ideas without a committed decision are tracked in
  Part IV (`09`, `10`) and never merged into the phase plan until they clear the decision record.

### 0.5 Track view (informational only — phases remain the unit of execution)

Phases are the unit of execution; tracks are a reading aid so independent work can proceed in
parallel without colliding, and to clarify that neither can *close out* before its declared
dependency does.

| Track | Phases | Note |
|---|---|---|
| Product/UI | 1, 2 | Sequential — Phase 2 depends on Phase 1's nav baseline |
| Reliability | 3 | Gates Phase 4 |
| Security | 4 | Gates Phase 7 |
| Platform hygiene | 5, 6 | Can run partially parallel to 3/4 where scope doesn't overlap |
| Network | 7, 8 | Sequential, both blocked on 1–6 |
| Close-out | 9 | Blocked on 1–8 |
| AI | 10 | Blocked on everything |

This table changes no acceptance criterion or dependency stated in the phase files — those are
authoritative.

---

## 1. Phase 0 — Current Reality ✅

*Carried from v3 §2, live-verified 2026-08-05, unless flagged in §1.1's "since v3" table. This phase
intentionally does not re-run every check — restating v3's numbers without re-verification would be
exactly the mistake the rewrite exists to correct. Its role is to be the ground truth every later
phase is checked against.*

### 1.1 Codebase shape

| Item | Count | Verified how |
|---|---|---|
| Backend Python source files | 261 | `find backend/app -name '*.py'` (2026-08-04) |
| Backend test files | 90 | `find backend/tests -name 'test_*.py'` |
| Frontend test files | 41 | `find frontend/src -name '*.test.*'` |
| REST routers | 11 ✅ | `backend/app/api/v1/routers/` (verified 2026-08-06): auth, backups, health, **marketplace**, monitoring, plugins, schedules, servers, settings, software, users (marketplace added by K5) |
| DDD modules | 9 | `backend/app/modules/` |
| Alembic revisions | 16 | `backend/alembic/versions/*.py` |
| ADRs | 12 | `docs/decisions/*.md` (excl. README) |
| Contract files | 6 | `contracts/` |
| Backend tests collected | 1,070 | `pytest --collect-only -q` |
| Backend tests passed/failed | 1,068 / 2 ⚠️ **not re-run 2026-08-05, not re-run here** | carried from `current-state.md` (2026-08-04) via v3 |
| Frontend tests | 236 across 41 files | `vitest list` |
| App version (code) | `4.0.0` everywhere | grepped; `7.1.0` appears only as an unrelated semver-range substring and in historical planning docs |
| CI workflows | 1 (frontend only) | `.github/workflows/frontend-ci.yml` — no backend CI (K6) |

**Since v3 (from `docs/STATUS.md` uncommitted batch entries, 2026-08-05 → 2026-08-06):**

| Item | Change | Source |
|---|---|---|
| Backend tests collected | 1,070 → **1,084** | Batch K16A (2026-08-05): plugin catalog provider tests |
| Marketplace frontend | First-class — own `/marketplace` route, sidebar entry, global search endpoint | K5 (2026-08-06), STATUS.md |
| Plugin catalog providers | Configuration-driven via `MCS_PLUGIN_PROVIDERS`, fail-fast validated at startup | K16A (2026-08-05), STATUS.md |

The two batches above post-date v3's 2026-08-05 snapshot. This blueprint treats K5 and K16A as done
(§Volume 2 ⇐ §2 of this file) on the strength of the STATUS.md batch entries — a *lower* verification
bar than v3's live route introspection. **Flagged, not hidden**, and Phase 2's first workstream
confirmed followup (§2.6).

### 1.2 Outstanding file-state item (carried from v3 §2, unresolved)

Two tracked, committed files carry uncommitted working-tree changes: `.../routers/plugins.py` (8
commits, latest `b1b6dd8`) and `.../tests/api/test_api_endpoints.py` (9 commits, latest `b1b6dd8`).
Pending diff: a `_to_version_response()` helper (+/−) and one new test
`test_marketplace_versions_returns_files` (+54). **D3, open** ($ref Part VIII `11`).

### 1.3 What Phase 0 establishes

Phase 0 has no deliverables of its own; it is the baseline every later phase's "current reality" is
checked against. If a later acceptance criterion depends on a Phase 0 number that hasn't been
re-verified since 2026-08-05, that check must re-verify it before claiming done. This is stated
explicitly because it is exactly the failure mode that produced v2 → v3 → V4.

---

## 2. Phase 1 — Plugins / Marketplace Separation 🔄 NEARING CLOSE

### 2.1 Objective

Split **"what plugins does this server have"** (server-scoped, lifecycle-oriented) from **"what
plugins can I discover and install"** (global catalog, discovery-oriented) into genuinely distinct
product surfaces — not one page with a sub-tab. This is the canonical application of Part I §5
(*small, correct surfaces*).

### 2.2 Current reality

| Area | Answers | Scope |
|------|---------|-------|
| **Plugins** | "What plugins does this server have?" | Server-scoped: installed list, state, lifecycle, enable/disable, removal, configuration |
| **Marketplace** | "What plugins can I discover and install?" | Global catalog/store; server selection happens at install time |

- Backend historically: one router, `/api/v1/servers/{server_id}/plugins/*`, handling both plugin
  management and marketplace (search/versions/install). Provider selection configuration-driven via
  `MCS_PLUGIN_PROVIDERS` (default `modrinth`), validated fail-fast at startup (K16A).
- Live route table (v3, verified 2026-08-05): `GET /plugins`, `GET /plugins/{id}`,
  `DELETE /plugins/{plugin_id}`, `POST /plugins/{id}/enable`, `POST /plugins/{id}/disable`,
  `GET /plugins/marketplace/search`, `GET /plugins/marketplace/projects/{id}/versions`,
  `POST /plugins/marketplace/install`. No standalone install route outside marketplace — the old
  `POST /plugins` manual-install route was removed in `b1b6dd8`.
- **Per K5 (2026-08-06):** Marketplace now has its own top-level route (`/marketplace`), sidebar
  entry, and a global search endpoint (`GET /marketplace/search`) distinct from the server-scoped
  one. The install flow was reworked with a server picker (server selection happens at install
  time), pre-selecting by deep link → last-used server → first compatible → any server.

### 2.3 Workstreams

1. **Frontend nav restructure (K5).** ✅ Done per STATUS.md 2026-08-06 — own sidebar entry, own
   route, own search, install flow with server picker. **Not yet independently re-verified by live
   route/component introspection.** A short verification pass is recommended at the start of Phase 2
   rather than trusting the batch note alone (§2.6).
2. **Route/namespace clarity.** Decide whether marketplace API routes stay under
   `/servers/{id}/plugins/marketplace/*` or move to a marketplace-owned namespace. **Open — D4.**
3. **Provider abstraction (K16).** ✅ K16A done (2026-08-05): configuration-driven, validated
   fail-fast at startup on unknown/empty/multiple providers. K16A accepts exactly one active
   provider; the comma-separated syntax remains for the remaining K16 scope (inspect configured list
   via API; add a second provider). Remaining K16 work is **not Phase 1 exit scope** — it's backlog
   for whenever a second provider is needed.
4. **Foundation for future catalog features.** Checksums, version metadata, and dependency info
   already exist in the version-selection model — reuse rather than rebuild.

### 2.4 Dependencies

None — backend marketplace already shipped before this phase started.

### 2.5 Acceptance criteria

| Criterion | Status |
|---|---|
| Marketplace independently navigable (own nav entry + route) | ✅ Met per K5 (2026-08-06) |
| Installing from Marketplace places a verified `.jar` in the selected server's `plugins/`; reconciled list reflects it | 🔶 Not explicitly confirmed — verify in §2.6 |
| Plugin management reads server-scoped; Marketplace reads global | ✅ Met per K5 — separate search endpoints |
| Provider list configuration-driven, Modrinth default | ✅ Met per K16A (2026-08-05) |
| D4 (route namespace) resolved | 🔶 Open |

### 2.6 What's actually left before this phase can close

Phase 1 is close to done but not formally closed. Three concrete items:

1. **Independent verification of K5/K16A.** Both logged done in STATUS.md's batch narrative, which
   per its own header is not the source of truth for current counts. A short pass — hit the routes,
   confirm the sidebar entry renders, confirm install actually writes the `.jar` to the right server
   directory — closes "logged done" → "verified done" the way v3 closed it for Phase 0.
2. **D4.** The route-namespace decision blocks a clean Phase 1 → Phase 2 handoff for new
   marketplace-adjacent frontend work.
3. **D3.** The two files with pending diffs (§1.2) should be committed as their own commit before
   Phase 1 is called closed — an open diff against a "done" phase is a doc-vs-code mismatch
   waiting to happen.

### 2.7 Testing

Backend + frontend suites green (1,084 backend, 236+ frontend); manual UX walk of both nav surfaces;
frontend tests for both server-scoped and global marketplace search paths.

### 2.8 Risks

- **Route namespace churn (D4).** If marketplace routes move after other code depends on the
  current path, that's a breaking change needing a shim. Resolving D4 now, before Phase 2 builds more
  surface against the current path, is cheaper than resolving it later.
- **Silent scope creep into K16 remainder.** Multi-provider support is real work with its own
  testing surface. It must not quietly become a Phase 1 blocker — it's explicit backlog, not exit
  criteria.

---

## 3. Phase 2 — Product Foundation & UI Stabilization 🔶

### 3.1 Objective

Make the frontend a first-class, stable surface — consistent loading/error/empty states and
navigation — on top of Phase 1's nav baseline. Honesty and consistency in the UI layer, **not new
features**.

### 3.2 Current reality (frontend)

- React 19 + Vite + TypeScript 5, TanStack Query, Zustand, TailwindCSS 4.
- Routes (`frontend/src/App.tsx`): `/login`, `/register`, then guarded: `/`, `/servers`,
  `/servers/create`, `/servers/import`, `/servers/:serverId`, `/backups`, `/plugins`,
  `/plugins/marketplace`, `/settings`, `/settings/api-keys`, `*`. **Per K5, `/marketplace` as a
  top-level route should now appear here — this list is carried from v3 §4 and has not been
  re-confirmed against current `App.tsx` since K5 landed. First task of this phase: refresh it.**
- Sidebar: Dashboard, Servers, Backups, Plugins, Settings — **plus Marketplace, per K5.** Same
  caveat.
- Zustand stores: `authStore` (localStorage `mcs_auth`), `uiStore`, `wsStore`.
- WebSocket client is fully implemented (connect/reconnect/ping/message queue), but the backend
  rejects every subscription (K1) and never dispatches events (K2) — a complete client that is
  behaviorally non-functional. **This is a Phase 3 fix, not Phase 2.** Phase 2's job here is to make
  that brokenness honest in the UI (not silently "connected"), not to fix the underlying bug.

### 3.3 Desired state

- Navigation clearly separates plugin-management from marketplace, and server-scoped from global.
- Loading/error/empty states uniform across all pages.
- API state and cache behavior deterministic (TanStack Query configured once, applied consistently).
- WebSocket behavior documented and either works or is explicitly disabled per surface.
- Settings UX reflects what actually persists. Persistence lands in Phase 3; Phase 2 disables /
  annotates non-persistent controls rather than faking success.
- Permissions UX shows only actions the user may take. Enforcement lands in Phase 4; Phase 2 lays
  the presentation groundwork against `contracts/permissions.yaml` (which has an open version
  question, D2). Phase 2 builds against whichever version is committed at the time and flags if D2
  resolves mid-phase.
- No new design system — apply consistently what already exists.

### 3.4 Workstreams

1. **Navigation & IA**, on Phase 1's restructure, including the post-K5 refresh in §3.2.
2. **Shared loading/error/empty primitives**, applied repo-wide — one set of components, not
   per-page reinvention.
3. **API client + TanStack Query configuration audit** — one query-client config; consistent
   staleTime; cacheTime; retry policy across queries rather than ad hoc per-hook settings.
4. **Settings page accuracy** relative to actual persistence — every control either persists or is
   visibly disabled/labeled non-functional. No control silently no-ops.
5. **WebSocket surface honesty** — live vs. explicitly disabled, surfaced in the UI, not hidden
   behind a client that "looks" connected while the backend fail-closes every subscription (K1).
6. **Frontend test coverage** for the above.

### 3.5 Dependencies

Phase 1 (nav restructure). Given §2.6, this phase's first workstream item should confirm Phase 1's
actual current state (route list, sidebar) rather than assume the v3 snapshot is still accurate — it
is already one batch (K5) out of date.

### 3.6 Acceptance criteria

- Every route has defined loading/error/empty behavior.
- Navigation distinguishes server-scoped from global surfaces.
- Frontend tests cover the restructured navigation and state primitives.
- Settings page has zero controls that silently no-op.
- WebSocket surface has zero "shows connected, does nothing" states.

### 3.7 Verification

Frontend suite green; manual walkthrough; route-by-route state review recorded in
`docs/FRONTEND.md` (a v3-carried commitment — the review must actually get written into that file,
not just performed).

### 3.8 Explicit non-goals

- Fixing K1/K2 (WebSocket backend) — Phase 3.
- Implementing settings persistence — Phase 3.
- Enforcing permissions server-side — Phase 4.
- A new visual design system — out of scope entirely; apply what exists.

### 3.9 Risks

- **Building permission-aware UI against an unstable contract.** `contracts/permissions.yaml` has an
  open version question (D2). Presentation groundwork should read permission strings from the
  contract at build/runtime rather than hardcode a list D2 could invalidate.
- **Scope bleed into Phase 3.** The WebSocket and Settings workstreams sit at the boundary with
  Phase 3's must-fix items. Discipline is required to keep Phase 2 to "make the current state honest
  in the UI" without starting to fix backend causes — that's real, valuable work, but it's
  Phase 3's, and starting it here blurs both phases' acceptance criteria.

---

*Continue to [`05-phase3-4-reliability-and-security.md`](./05-phase3-4-reliability-and-security.md) for
Phases 3 (Reliability) and 4 (Security) — the highest-leverage work in the roadmap.*