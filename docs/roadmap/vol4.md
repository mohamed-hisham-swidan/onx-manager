<a name="volume-4"></a>
## Volume 4 — Phase 3: Backend/Frontend Reliability 🔶

### 4.1 Objective

Make the existing product actually reliable. This is the highest-leverage phase in the whole
roadmap: it gates Phase 4 (Security), and Phase 4 is where the project's real open risk lives (9
unauthenticated mutating routes, open registration). Every day Phase 3 is incomplete is a day
Phase 4 can't start.

### 4.2 Dependencies

None structural — runs in parallel with Phase 2 where the two overlap (see Phase 2 §3.9 risk on
scope bleed).

### 4.3 WebSocket delivery — must fix

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
- **Why this matters beyond WS itself:** K1's root cause — plural vs. singular permission-string
  namespace — is the same class of bug that Phase 4 §6.1's route-gating work will hit if it's not
  fixed first. Fixing the namespace once, here, and having Phase 4 build on the corrected
  singular namespace, avoids fixing the same inconsistency twice in two different subsystems.

### 4.4 Settings persistence — must fix

- **K3:** `PATCH /api/v1/settings` is a stub (`{"success": true, "message": "Settings updated
  (stub)"}`) — nothing persists. Decide the persisted field set (start with what `GET /settings`
  already returns — this is D6, Volume 10), persist it, apply it at runtime, gate with
  `settings:write`.
- **Acceptance:** updating a setting persists, is returned by `GET /settings`, and is enforced at
  runtime.
- **Sequencing note:** gating with `settings:write` here means Phase 3 is doing a small piece of
  Phase 4's job (adding a permission check) on one route. That's intentional and fine — it's the
  same pattern Phase 4 will apply everywhere else, and doing it here first gives Phase 4 one
  concrete precedent to follow rather than inventing the pattern from scratch.

### 4.5 Test suite green — must fix

- **K8 / D5:** 2 failing tests (per `current-state.md`, 2026-08-04, ⚠️ not re-run since):
  `test_start_server` (closed-DB rollback in API teardown) and
  `test_metrics_task_requires_collector` (stale expectation vs. graceful warning handler). Fix or
  formally re-baseline — **D5 in Volume 10 is explicitly open on which of these two paths applies
  to which test; investigate `test_start_server`'s teardown first, since
  `test_metrics_task_requires_collector` looks like a stale assertion against since-changed
  behavior rather than a real regression.**
- **Acceptance:** a fresh `python -m pytest tests/` run passes with 0 failures.

### 4.6 Runtime/system consistency — should fix

- **K9:** production DB is 3 revisions behind head (per `current-state.md`, 2026-08-04, ⚠️ not
  re-verified since); 0 servers in production, which lowers the immediate operational risk of this
  gap but doesn't remove the need to close it before Phase 4 or Phase 7 assume a consistent schema.
  Bring to head with a documented upgrade procedure. **D12 (auto-upgrade on boot vs. refuse-to-start)
  should be resolved as part of this item, not left dangling after the migration runs.**
- **K15:** clean up the repo-root `data/` directory (confirm unused first — **D11**).
- **K14:** backup save-all completion regex is unverified against a real Purpur server — add a
  live/mocking regression check. This is the kind of gap that's easy to defer indefinitely because
  it's not blocking anything today; it's listed here as should-fix specifically so it doesn't
  quietly become permanent known-limitation by attrition.

### 4.7 Honest error handling

Audit HTTP status/error payload consistency across all 10 routers; document the contract. This is
foundational for Phase 4's route-coverage CI check (§Volume 5) — a route-coverage test is only as
good as the error contract it's asserting against.

### 4.8 Testing strategy for this phase

- Every K-item above needs its own regression test, not just a manual fix-and-verify — K1/K2
  especially, since a WebSocket auth regression is exactly the kind of bug that's invisible until
  it silently breaks a client in production.
- The route-coverage habit Phase 4 will formalize in CI (§Volume 5, §6.3) should be dry-run
  informally at the end of this phase against whatever gating work §4.4 already did, as a sanity
  check that the pattern generalizes before Phase 4 scales it to the remaining 9 routes.

### 4.9 Acceptance criteria (phase-level)

WS live and delivering events with fail-closed authorization intact; settings persist and are
enforced; test suite is 100% green (0 failures, not just 0 *new* failures); production DB at head
with a documented, decided-upon (D12) upgrade procedure; HTTP error contract documented.

### 4.10 Risks

- **K1/K2 fix touching the same code Phase 2's WebSocket-honesty workstream depends on.** If Phase
  2 and Phase 3 run in parallel as intended, the frontend's "WS surface honesty" work (§3.4
  workstream 5) needs to either wait for K1/K2 or be built against the *current* broken behavior and
  then re-verified once K1/K2 land. Recommend the latter — build the honest-UI state machine now,
  re-test it once real events start flowing.
- **Test re-baselining (D5) papering over a real bug.** If `test_metrics_task_requires_collector`
  turns out to be catching a real regression rather than a stale assertion, re-baselining it would
  hide a genuine defect. The investigation should default to "assume real bug until proven stale,"
  not the reverse.
