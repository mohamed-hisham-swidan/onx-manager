# MCS Manager — Execution Track: Phases 3–4 (Reliability, Security)

**Part V** of the Engineering Blueprint V4. This file covers **Phase 3 (Reliability)** and **Phase 4
(Authorization / Security Cleanup)** — together the highest-leverage work in the roadmap. Phase 3
makes the existing product actually reliable; Phase 4 closes the security gaps an audit found and
then enforces the model in CI so it cannot regress.

**Last updated:** 2026-08-06
**Supersedes:** `mcs-manager-roadmap-v4.md` Volumes 4–5 (now historical baseline). Status indicators
use the roadmap legend: ✅ done, 🔄 in progress, 🔶 planned, ⛔ blocked, ⚠️ risk/open question.
Evidence discipline and definitions of terms are in `04` §0 and Part I.

---

## 1. Phase 3 — Backend/Frontend Reliability 🔶

### 1.1 Objective

Make the existing product actually reliable. This is the highest-leverage phase in the roadmap: it
**gates Phase 4**, and Phase 4 is where the project's real open risk lives (unauthorized mutating
routes, open registration). Every day Phase 3 is incomplete is a day Phase 4 cannot start.

### 1.2 Dependencies

None structural — runs in parallel with Phase 2 where the two overlap (see `04` §3.9 scope-bleed
risk). Phase 3 must **not** be started-for-done before the K-items below pass; "reliable" is a
binary, verified claim (Part I §1, §4).

### 1.3 WebSocket delivery — must fix

- **K1:** channel authorization always denies — plural `CHANNEL_PATTERNS` (e.g. `servers:read`) vs.
  singular JWT claims (e.g. `server:read`) — fail-closed, so no channel ever subscribes. Reconcile to
  a single singular `resource:action` namespace with an `admin:full` passthrough.
- **K2:** `EventDispatcher`/`MetricsBatcher` are never instantiated, so no server-push event ever
  reaches a client. Wire both into the app lifespan via event-bus subscription; stay fail-closed
  during the transition.
- **Secondary WS gaps** (`docs/PERMISSIONS_FUTURE_IDEAS.md` §4): validate `refresh_token` payloads,
  enforce idle timeout, re-check authorization per pushed message.
- **Acceptance:** a client with `server:read` subscribes and receives `state`/`event` frames;
  publishing a domain event reaches subscribers (integration test); fail-closed still holds without
  permission.
- **Why this matters beyond WS:** K1's root cause — plural vs. singular permission-string namespace —
  is the *same class of bug* Phase 4's route-gating will hit. Fixing the namespace once here, and
  having Phase 4 build on the corrected singular namespace, avoids fixing the same inconsistency
  twice in two subsystems.

### 1.4 Settings persistence — must fix

- **K3:** `PATCH /api/v1/settings` is a stub (`{"success": true, "message": "Settings updated (stub)"}`)
  — nothing persists. Decide the persisted field set (start with what `GET /settings` already
  returns — **D6**), persist it, apply it at runtime, gate with `settings:write`.
- **Acceptance:** updating a setting persists, is returned by `GET /settings`, and is enforced at
  runtime.
- **Sequencing note:** gating with `settings:write` here does a small piece of Phase 4's job on one
  route. That's intentional — same pattern Phase 4 applies everywhere, done first as a concrete
  precedent.

### 1.5 Test suite green — must fix

- **K8 / D5:** 2 failing tests (per `current-state.md`, 2026-08-04, ⚠️ not re-run since):
  `test_start_server` (closed-DB rollback in API teardown) and
  `test_metrics_task_requires_collector` (stale expectation vs. graceful warning handler). Fix or
  formally re-baseline — **D5 is explicitly open** on which of the two paths applies to which test;
  investigate `test_start_server`'s teardown first, since `test_metrics_task_requires_collector`
  looks like a stale assertion against since-changed behavior rather than a real regression.
- **Acceptance:** a fresh `python -m pytest tests/` run passes with **0 failures**.

### 1.6 Runtime / system consistency — should fix

- **K9:** production DB is **3 revisions behind head** (per `current-state.md`, 2026-08-04, ⚠️ not
  re-verified); 0 servers in production lowers immediate operational risk but doesn't remove the need
  to close it before Phase 4 or Phase 7 assume a consistent schema. Bring to head with a documented
  upgrade procedure. **D12 (auto-upgrade on boot vs. refuse-to-start) should be resolved as part of
  this item**, not left dangling after the migration runs.
- **K15:** clean up the repo-root `data/` directory (confirm unused first — **D11**).
- **K14:** backup save-all completion regex is unverified against a real Purpur server — add a
  live/mocking regression check. Listed here precisely so it doesn't quietly become permanent
  known-limitation by attrition.

### 1.7 Honest error handling

Audit HTTP status/error-payload consistency across all 11 routers (verified 2026-08-06: the 10
carried from v3 plus the marketplace router added by K5); document the contract. This is
foundational for Phase 4's route-coverage CI check — a route-coverage test is only as good as the
error contract it asserts against.

### 1.8 Testing strategy for this phase

- Every K-item needs its own **regression test**, not just a manual fix-and-verify — K1/K2
  especially (a WS auth regression is invisible until it silently breaks a client in production).
- The route-coverage habit Phase 4 will formalize in CI (§2.5) should be dry-run at the end of this
  phase against whatever gating §1.4 already did, as a sanity check that the pattern generalizes.

### 1.9 Acceptance criteria (phase-level)

WS live and delivering events with fail-closed authorization intact; settings persist and are
enforced; test suite 100% green (0 failures, not just 0 *new* failures); production DB at head with a
documented, decided (D12) upgrade procedure; HTTP error contract documented.

### 1.10 Risks

- **K1/K2 fix touching the code Phase 2's WS-honesty workstream depends on.** If Phase 2 and 3 run
  in parallel, Phase 2's WS surface-honesty work must either wait for K1/K2 or be built against the
  *current* broken behavior and re-verified once K1/K2 land. Recommend the latter.
- **Test re-baselining (D5) papering over a real bug.** If `test_metrics_task_requires_collector`
  is catching a real regression rather than a stale assertion, re-baselining hides a genuine defect.
  Default to "assume real bug until proven stale," not the reverse.

---

## 2. Phase 4 — Authorization / Security Cleanup 🔶

### 2.1 Objective

Close the security gaps the audit found, then enforce the model in CI so it cannot regress. **This
is the single most important phase in the document.** Every other phase either leads into it or waits
behind it. Part IV's speculative future work cannot start until this phase *and* Phase 7's network
exposure close, because opening the product to the network with an unresolved authorization gap turns
a contained internal risk into an externally exploitable one.

### 2.2 Dependencies

Phase 3 (a stable, tested base). **Hard gate, not soft preference** — gating routes correctly
requires the corrected singular permission namespace from Phase 3 §1.3 (K1).

### 2.3 Enforce remaining routes — must fix

**Live-verified state (2026-08-05, from v3, superseding v2 §6.1 and `current-state.md` K7):**

- **24 routes are gated** by `require_permission` — unchanged from earlier: 22 mutating (servers 7,
  backups 4, plugins-delete + marketplace-install 3, users 2, auth/API-keys 2) + 2 read-only
  marketplace GET routes. (Per-module breakdown pending a fresh per-file grep tally; the 22 total is
  a direct count from the live route table.)
- **12 mutating routes are unprotected, not 13** — corrected from earlier, since `b1b6dd8` removed
  the legacy manual-install route:
  `POST /auth/login`, `POST /auth/logout`, `POST /auth/refresh`,
  `POST /health/evaluate/{server_id}`, `POST /monitoring/alerts`,
  `DELETE /monitoring/alerts/{alert_rule_id}`, `POST /schedules`,
  `DELETE /schedules/{schedule_id}`, `POST /plugins/{plugin_id}/enable` (K4),
  `POST /plugins/{plugin_id}/disable` (K4), `PATCH /settings`, `POST /users`.
  Of these, `login`/`logout`/`refresh` are intentionally public; **the other 9 are real gaps** — the
  single number that matters most in the whole document.
- **23 sensitive GET routes** are auth-only with no permission check (strict middleware count — an
  earlier "21" used a different classification; reconciling the two is **D1, still open**).
- **3 intentionally public routes:** login, refresh, registration (`POST /users` — see §2.4).

**Work:** gate the real gaps (9 mutating routes beyond the 3 intentional public ones, plus the 23
sensitive GETs) with permission strings, and enforce in CI.

**Sequencing within this workstream:**
1. Resolve **D2** (`contracts/permissions.yaml` version) first — §2.8 explains why.
2. Resolve **D1** (GET-route classification) before the 23-route GET work — the count itself is
   disputed.
3. Gate the **9 confirmed mutating gaps** — undisputed, can start immediately after D2.
4. Gate the **reconciled GET set** once D1 resolves.

### 2.4 Registration bootstrap (`POST /api/v1/users`) — investigate first

Registration is open with no auth — arguably the single highest real-world risk item in the roadmap:
an unauthenticated user-creation endpoint on a system about to gain network exposure in Phase 7 is a
direct path to account takeover.

**Decision procedure (carried, unchanged — D13):** investigate whether a first-user-bootstrap
exception is safe and simple (open only while zero users exist, then require `user:write`). If the
investigation surfaces hidden onboarding dependencies or ambiguous "first user" semantics, do **not**
improvise — document the finding in `docs/PERMISSIONS_FUTURE_IDEAS.md` and leave the route unchanged.
**Not yet investigated.**

**Why it can't just be deferred:** leaving `POST /users` open isn't a neutral "known limitation" —
it's an active, growing risk the longer the system exists before Phase 7 exposes it. Recommend
investigating this item *first* within §2.3's sequencing, ahead of the bulk GET work, because it is
higher severity than its alphabetical position suggests.

### 2.5 Backend CI + route-coverage test — must fix (K6)

No backend CI exists — only `.github/workflows/frontend-ci.yml`. Add a workflow running `pytest`,
`ruff`, `pyright`, and a route-coverage test that walks the live FastAPI route table and asserts
every mutating route carries a permission dependency.

**Acceptance:** a new mutating route without a permission dependency fails CI;
`contracts/permissions.yaml` matches the live route table with zero gaps.

This converts everything else in the volume from a one-time cleanup into a **standing guarantee**.
Without it, a new route can silently reopen exactly the gap this phase closes — not coincidentally
how the gaps identified here came to exist: nothing was stopping them.

### 2.6 WebSocket authorization hardening

Fold WS channel checks into the same (now singular, per Phase 3 §3.3) permission path. Phase 3 did
the namespace reconciliation; this workstream is primarily about confirming the WS auth path reads
from the same contract source (`contracts/permissions.yaml`) as the REST route-coverage check rather
than maintaining a second, parallel, driftable permission list.

### 2.7 `GET /metrics` — explicitly deferred

Public and unauthenticated (K10). Not locked down here — risk of breaking an existing external
scraping setup is unknown. Revisit alongside Phase 7, when network-exposure decisions are being made
anyway.

### 2.8 `contracts/permissions.yaml` stabilization — must resolve before §2.3 starts

Committed HEAD is v1.3. The working tree has an **uncommitted** v1.4 edit (adds 3 marketplace rows,
still lists the now-deleted legacy install route under `status: missing`). §2.3's gating can't
proceed correctly until (a) the v1.4 edit is committed or discarded, and (b) the phantom
deleted-route entry is removed. **This is D2 — a hard prerequisite, not a parallel task.** Gating
routes against a contract that may change out from under the work is how the work gets done twice.

### 2.9 Security docs must match reality

`docs/SECURITY.md` currently documents the partial-enforcement gap; §2.3 resolves that caveat.
Re-verify the whole doc afterward: `httpOnly` vs. localStorage refresh token, API-key SHA-256
hashing, per-client rate limiting (confirmed per-`client_ip:path` in `current-state.md` §4.6), WS
fail-closed behavior.

### 2.10 Testing strategy

- Every confirmed mutating gap gets a **permission-denied** test (401/403 without the right scope)
  and a **permission-granted** test, following the pattern established in earlier batches for the
  servers and backups modules.
- The registration decision (§2.4), whichever way it resolves, needs a test proving the resolved
  behavior — including a test that a second user cannot be created without `user:write` if the
  bootstrap-exception path is chosen.
- The route-coverage CI test (§2.5) is itself a test artifact and should be written **last**, once
  manual gating is complete, so it asserts against a genuinely complete state.

### 2.11 Acceptance criteria (phase-level)

Every mutating endpoint checked and CI-enforced; `contracts/permissions.yaml` complete and internally
consistent (single committed version, no phantom routes); `SECURITY.md` carries no
partial-enforcement caveat beyond the explicitly allow-listed public routes (login, refresh, and
whatever §2.4 decides for registration).

### 2.12 Risks

- **D2 blocking the phase's start.** Called out three times deliberately (§2.3, §2.8, here) because
  it's the most likely way the phase stalls — gating against an unsettled contract file means half
  the gating work gets redone.
- **A rushed registration decision.** §2.4's investigation should not be rushed because it's
  highest-severity; an incorrectly-designed bootstrap exception (ambiguous "first user" semantics in
  a multi-process startup) could be *worse* than the current open state, because it would look fixed
  while still exploitable in a race. The documented fallback (leave unchanged, log finding) is
  sanctioned — take it rather than ship a rushed half-fix.
- **CI route-coverage too strict or too loose.** Too strict trains developers to add exemption
  comments carelessly; too loose defeats the purpose. The 3-route public allowlist (§2.3) should be
  the literal exemption list the check reads from — not a judgment call made by whoever writes a new
  route that day.

---

*Continue to [`06-phase5-6-versioning-and-testing.md`](./06-phase5-6-versioning-and-testing.md) for
Phases 5 (Versioning & State Consistency) and 6 (Testing / CI / Documentation Reliability) — the
"platform hygiene" that makes the foundation non-regressable.*