<a name="volume-5"></a>
## Volume 5 — Phase 4: Authorization / Security Cleanup 🔶

### 5.1 Objective

Close the security gaps the audit found, then enforce the model in CI so it can't regress. **This
is the single most important phase in this document.** Every other phase either leads into this one
or waits behind it; Volume 9's speculative future work explicitly cannot start until this phase and
Phase 7's network exposure work are both closed, because opening the product to the network on top
of an unresolved authorization gap would turn a contained internal risk into an externally
exploitable one.

### 5.2 Dependencies

Phase 3 (a stable, tested base). **Not started while the plugin restructure and reliability work
are open** — this is a hard gate, not a soft preference, because gating routes correctly requires
the corrected singular permission namespace that Phase 3 §4.3 fixes as part of K1.

### 5.3 Enforce remaining routes — must fix

**Live-verified state (2026-08-05, from v3, superseding v2 §6.1 and `current-state.md` K7):**

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
  Of these, `login`/`logout`/`refresh` are intentionally public; **the other 9 are real gaps** —
  this is the number that matters most in this entire document.
- **23 sensitive GET routes** are auth-only with no permission check (strict middleware count —
  v2's "21" used a different classification; reconciling the two is **D1, still open**).
- **3 intentionally public routes:** login, refresh, registration (`POST /users` — see §5.4).

**Work:** gate the real gaps (9 mutating routes beyond the 3 intentional public ones, plus the 23
sensitive GETs) with permission strings, and enforce in CI.

**Sequencing within this workstream:**
1. Resolve D2 (`contracts/permissions.yaml` version) first — §5.7 below explains why this has to
   go first, not last.
2. Resolve D1 (GET-route classification) before starting the 23-route GET work, since the count
   itself is disputed and gating the wrong set wastes effort either way.
3. Gate the 9 confirmed mutating gaps — these are undisputed, can start immediately after D2.
4. Gate the reconciled GET set once D1 resolves.

### 5.4 Registration bootstrap (`POST /api/v1/users`) — investigate first

Registration is currently open with no auth — a real Phase 4 gap, and arguably the single highest
real-world risk item in this entire roadmap, since an unauthenticated user-creation endpoint on a
system that's about to get network exposure in Phase 7 is a direct path to full account takeover if
left unresolved.

**Decision procedure (carried from prior session, unchanged — D13):** investigate whether a
first-user-bootstrap exception is safe and simple (open only while zero users exist, then require
`user:write`). If the investigation surfaces hidden onboarding dependencies or ambiguous
"first user" semantics, don't improvise — document the finding in `docs/PERMISSIONS_FUTURE_IDEAS.md`
and leave the route unchanged. **Not yet investigated.**

**Why this can't just be deferred:** unlike most items in this roadmap, leaving `POST /users` open
isn't a neutral "known limitation" — it's an active, growing risk the longer the system exists
before Phase 7 exposes it externally. Recommend this specific item gets investigated first within
§5.3's sequencing, ahead of the bulk GET-route work, precisely because it's higher severity than its
alphabetical position in the K-list would suggest.

### 5.5 Backend CI + route-coverage test — must fix (K6)

No backend CI exists — only `.github/workflows/frontend-ci.yml`. Add a workflow running `pytest`,
`ruff`, `pyright`, and a route-coverage test that walks the live FastAPI route table and asserts
every mutating route carries a permission dependency.

**Acceptance:** a new mutating route without a permission dependency fails CI;
`contracts/permissions.yaml` matches the live route table with zero gaps.

This is the item that converts everything else in this volume from a one-time cleanup into a
standing guarantee. Without it, the next new route added to any of the 10 routers can silently
reopen exactly the gap this whole phase closes — which is, not coincidentally, how the 12 (now 9)
gaps identified here came to exist in the first place: nothing was stopping them.

### 5.6 WebSocket authorization hardening

Fold WS channel checks into the same (now singular, per Phase 3 §4.3) permission path. This should
be close to free by this point — Phase 3 already did the namespace reconciliation; this workstream
is primarily about confirming the WS auth path reads from the same contract source
(`contracts/permissions.yaml`) as the REST route-coverage check, rather than maintaining a second,
parallel permission list that can drift from the first.

### 5.7 `GET /metrics` — explicitly deferred

Public and unauthenticated (K10). Not locked down in this phase — the risk of breaking an existing
external scraping setup is unknown. Revisit alongside Phase 7, when network exposure decisions are
being made anyway and this can be decided in that context rather than in isolation.

### 5.8 `contracts/permissions.yaml` stabilization — must resolve before 5.3 starts

Committed HEAD is v1.3. The working tree has an **uncommitted** v1.4 edit (adds 3 marketplace rows,
still lists the now-deleted legacy install route under `status: missing`). §5.3's route-gating work
can't proceed correctly until (a) the v1.4 edit is committed or discarded, and (b) the phantom
deleted-route entry is removed. **This is D2, and it's a hard prerequisite, not a parallel task** —
gating routes against a contract file that might be about to change out from under the work is how
you end up doing the gating work twice.

### 5.9 Security docs must match reality

`docs/SECURITY.md` currently documents the partial-enforcement gap; §5.3 resolves that caveat.
Re-verify the whole doc afterward: `httpOnly` vs. localStorage refresh token, API-key SHA-256
hashing, per-client rate limiting (already confirmed per-`client_ip:path` in `current-state.md`
§4.6), WS fail-closed behavior.

### 5.10 Testing strategy

- Every one of the 9 confirmed mutating gaps gets a permission-denied test (401/403 without the
  right scope) and a permission-granted test, following the pattern already established in Batch 9
  and Batch 10 (`docs/STATUS.md`) for the servers and backups modules.
- The registration bootstrap decision (§5.4), whichever way it resolves, needs a test proving the
  resolved behavior — including a test that a second user cannot be created without `user:write`
  if the bootstrap-exception path is chosen.
- Route-coverage CI test (§5.5) is itself a test artifact and should be the last thing written in
  this phase, once the manual gating work is complete, so it's asserting against a genuinely
  complete state rather than being written first and then patched as gaps are found.

### 5.11 Acceptance criteria (phase-level)

Every mutating endpoint checked and CI-enforced; `contracts/permissions.yaml` complete and
internally consistent (single committed version, no phantom routes); `SECURITY.md` carries no
partial-enforcement caveat beyond the explicitly allow-listed public routes (login, refresh,
and whatever §5.4 decides for registration).

### 5.12 Risks

- **D2 blocking the entire phase's start.** This is called out three times in this volume
  deliberately (§5.3, §5.8, and here) because it's the single most likely way this phase stalls —
  someone starts gating routes against the contract file before its version is settled, and half
  the gating work has to be redone.
- **Registration bootstrap decision made under time pressure.** §5.4's investigation should not be
  rushed just because it's flagged as highest-severity — an incorrectly-designed bootstrap
  exception (e.g., one with ambiguous "first user" semantics in a multi-process startup) could be
  worse than the current fully-open state, because it would look fixed while still being
  exploitable in a race condition. If in doubt, the documented fallback (leave unchanged, log the
  finding) is explicitly sanctioned above — take it rather than ship a rushed half-fix.
- **CI route-coverage check being too strict or too loose.** Too strict (e.g., flagging
  intentionally-public routes) trains developers to add exemption comments carelessly; too loose
  defeats the purpose. The 3-route public allowlist (§5.3) should be the literal exemption list the
  CI check reads from — not a judgment call made by whoever's writing a new route that day.
