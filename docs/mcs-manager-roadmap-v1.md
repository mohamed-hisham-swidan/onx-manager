# MCS Manager — Roadmap to v1.0

> ⏸️ **LEGACY / SUPERSEDED.** This document is preserved for history only. The
> single authoritative roadmap is **`docs/mcs-manager-roadmap-v2.md`** (4-phase:
> 1 = Stabilization & Completion, 2 = Identity & Auth, 3 = Network Access, 4 = AI).
> Do not use this file as the source of truth for status or sequencing.

**Status:** Living planning document — engineering-owned
**Version:** 2.0 (supersedes personal working draft, rev. 2)
**Last updated:** 2026-08-04
**Baseline:** `STATUS.md`, through Batch 8 (2026-08-01)

---

## 1. Purpose and how to read this document

This roadmap sequences the work required to take MCS Manager from its current state to a public v1.0 release. It is derived from — and stays subordinate to — the verified project state in `STATUS.md`. Nothing in this document counts as complete unless `STATUS.md` says so. Vision documents and stakeholder requests are treated as **inputs to be reconciled against reality**, not commitments that are automatically in scope.

### Status legend

| Symbol | Meaning |
|---|---|
| ✅ | Done — verified in `STATUS.md` |
| 🔄 | In progress — active now |
| 🔶 | Planned — not started |
| ⛔ | Blocked — explicitly gated on an earlier phase |
| ⚠️ | Risk or open question requiring a decision |

### Governing principle

**Security and stability come before new capability.** Every phase from Phase 2 onward is explicitly blocked on Phase 1 closing. This is not a scheduling preference — it reflects that identity and authorization are the actual bottleneck: building RBAC, remote access, or an AI agent layer on top of an incomplete permission model means re-doing that work later under worse conditions (migrations, live users, larger blast radius).

### Documented exception — 2026-08-04

On 2026-08-04, Mohamed made a conscious, explicit decision to begin the plugin
marketplace feature (browse / search / install plugins from Modrinth,
previously logged as deferred in `docs/FEATURE_IDEAS.md` §2) ahead of Phase 1
closing, as a deliberate documented exception to the phase-gating rule above.
This is an intentional exception, not an accidental scope leak. Phase 1's exit
criteria remain open and are unaffected by this decision.

**Extension (same date, same exception — filesystem as source of truth):**
On 2026-08-04, still under the same documented exception and the same feature
area, the plugin system was extended so the filesystem — not the database — is
the source of truth for which plugins exist. This added per-row `filename`
tracking, reconciliation of on-disk `.jar` files against the DB (creating
`detected` rows for files dropped in outside the UI, and pruning rows whose
file was removed directly from disk), and deferred plugin deletion
(pending-deletion flags consumed on the next server start/restart). This is a
direct continuation of the marketplace work — not a new exception.

---

## 2. Current state — Phase 0: Foundation ✅

| Area | State |
|---|---|
| Architecture | FastAPI + React 19 modular monolith; CQRS, DDD, Hexagonal architecture; Event/Command/Query bus; dependency injection |
| Server lifecycle | Create / delete / start / stop / console / logs / version management |
| Runtime Engine | Ownership verification, startup guard, reconciliation, discovery — **one open bug carried into Phase 1** |
| Health Engine | Signal calculator, crash diagnostics, recovery orchestrator |
| Backup pipeline | tar.gz + AES-256-GCM encryption + checksum + verify; delete-before-DB-row ordering fixed in `775a457` |
| Infrastructure | Docker setup; full documentation set (API / ARCHITECTURE / ADRs / DEPLOYMENT / DEVELOPMENT / SECURITY) |
| Test coverage | ~1,132 tests |

Phase 0 is the accepted baseline for everything below. No further detail is needed here — the open item it left behind (runtime discovery bug) is tracked under Phase 1.

---

## 3. Phase 1 — Security & Stability Hardening 🔄 CURRENT

**Nothing in Phase 2 or later starts until every exit criterion below is met.**

### 3.1 Authorization coverage

**Current state**
- 🔄 High-risk endpoints locked down (`33336e0`): delete server, stop server, backup restore/delete, user update/delete, API key create/delete, plugin uninstall.
- 🔶 Remaining endpoints — reads and lower-risk writes — are still unprotected. This gap is already documented in `API.md` and `SECURITY.md`, which is good practice and should stay in place until closed.

**Problem with the current approach:** permission checks are being added endpoint-by-endpoint, which means coverage is only as good as whoever remembers to add the check. That's "safe by omission failing silently" — the worst failure mode for an authz system.

**Recommended solution**
1. **Build the coverage matrix first, before writing more checks.** Enumerate every route (FastAPI's route table can be introspected programmatically) against the required permission, in `contracts/permissions.yaml`. Treat this file as the single source of truth, not documentation of what was already coded.
2. **Move from ad hoc checks to a declarative dependency.** Standardize on a single FastAPI dependency, e.g. `Depends(require_permission("server:delete"))`, attached at route-registration time rather than as a line inside the handler body. This makes the check visible in the route signature and impossible to forget silently — a missing dependency is a diff-visible omission, not a logic bug buried in a function.
3. **Enforce coverage in CI, not in code review.** Add a test that walks the live route table and asserts every mutating route (`POST` / `PUT` / `PATCH` / `DELETE`) carries a permission dependency. Fail the build if a new route ships without one. This converts "someone might forget" into "the pipeline won't let it merge."
4. **Reads are not automatically low-risk.** Before closing this out, explicitly classify every read endpoint as either public-safe or requiring auth (e.g., a server's console log history is a read but is sensitive). Don't default reads to "fine to leave open."

**Exit criteria:** every mutating endpoint has an explicit, CI-enforced permission check; `contracts/permissions.yaml` is complete and matches the live route table; no endpoint is "safe by omission."

---

### 3.2 Rate limiter

**Problem (discovered this session):** `RateLimitMiddleware` tracks a single process-global counter. One client's traffic consumes the budget for every other client on the same endpoint — functionally, any user can rate-limit every other user.

> ⚠️ **Correction (2026-08-04):** this problem statement is **incorrect** — the
> limiter is keyed per `client_ip:path` (`backend/app/api/v1/middleware/rate_limit.py:41-42`, 60 req/min), so it is already per-client. See `docs/current-state.md` §4.

**Recommended solution**
1. **Key the bucket per client, not globally.** Bucket key = API key if the request is authenticated, otherwise client IP, with session ID as a fallback for browser-based sessions behind shared IPs (e.g., NAT).
2. **Algorithm:** token bucket (allows short bursts, smooths sustained load) or sliding-window counter — either is a reasonable choice; token bucket is simpler to reason about and cheaper to implement first.
3. **Storage:** for the current single-instance deployment model, an in-process dict keyed by client with a background TTL-sweep task is sufficient and avoids adding an infrastructure dependency (Redis, etc.) before it's needed. **Flag this as a decision to revisit** if MCS Manager ever needs multi-worker/horizontal scaling — at that point a shared store becomes mandatory, since per-process buckets would silently multiply the effective limit.
4. **Differentiate limit classes.** Auth endpoints (login, token refresh) need much tighter limits than read endpoints; don't apply one blanket number everywhere.
5. **Test the fix directly:** a concurrency test where two simulated clients hit the same endpoint simultaneously and assert that exhausting client A's budget has zero effect on client B.

**Why this can't wait:** once Phase 3 exposes the app to the public internet, a global bucket isn't just an inconvenience between two legitimate users — it becomes a trivial, unauthenticated denial-of-service vector against every user of that instance. This item is upgraded from "nice to have" to a hard Phase 1 exit blocker specifically because of that downstream consequence.

**Exit criteria:** two concurrent legitimate users on the same endpoint cannot affect each other's rate limit; limit classes are documented in `SECURITY.md`.

---

### 3.3 Backup module — open items

Six distinct open items, each with its own investigation/solution path below.

#### 3.3.1 Reconciliation duplicate bug (🔶 not yet root-caused)
**Recommended approach:**
- Add structured, correlation-ID'd logging around every step of the reconciliation pass so a single run can be traced end-to-end.
- Write a targeted reproduction test using two backups with similar or overlapping name/prefix patterns — duplication bugs in reconciliation logic are very commonly a matching/dedup-key issue, not a concurrency issue.
- Check whether the insert path is a plain `INSERT` versus an `UPSERT`/`INSERT ... ON CONFLICT` — if reconciliation can run twice for the same backup (e.g., on service restart mid-scan), a non-idempotent insert alone would explain duplicates without any race condition needed.

#### 3.3.2 "Marked as missing" line (🔶 not yet understood)
**Recommended approach:**
- Locate the log call site and determine whether it's a legitimate state transition (e.g., a backup file was deleted outside the app, correctly detected) versus an incorrect classification.
- Add explicit structured context to the log line itself (backup ID, expected path, what check failed) so the next occurrence is self-diagnosing instead of requiring a fresh investigation.
- Do not close this as "expected behavior" without first confirming the file really is gone on disk — conflating "detection working correctly" with "detection has a bug" here would hide a real defect.

#### 3.3.3 Confirming the delete-order fix isn't regressing
- 🔄 Currently: reviewing `/tmp/phase2_remaining.diff` (`backup_orchestrator.py` + the new DDD backup module) against the delete-before-DB-row ordering fixed in `775a457`.
**Recommended approach:** don't rely on manual diff review alone — add a regression test that asserts the ordering directly (e.g., via a spy/mock on the delete call and the DB write call, asserting call order), so any future refactor of the backup module breaks a test rather than silently reintroducing the bug.

#### 3.3.4 Legacy double-prefixed path fallback (🔶, affects one known row: `1eb2ed72…`)
**Recommended approach:**
- Write a one-time, idempotent migration script that detects the double-prefixed path pattern, normalizes the file to the canonical path, and updates the DB row to match.
- Run it in **dry-run mode first** (log what it would change, touch nothing) before running it for real — this is a data-migration script touching backup files, so the cost of a mistake is high and the cost of a dry-run flag is low.
- Since this affects exactly one known row today, it's reasonable to also add a startup-time check that logs (but doesn't auto-fix) any other rows matching the same pattern, in case there are more than currently known.

#### 3.3.5 `save-all` completion regex unverified against a real Purpur server (⚠️)
**Recommended approach:**
- Stand up a real Purpur server instance (a disposable Docker container is sufficient) in CI or a manual test pass, trigger `save-all`, and confirm the regex matches actual console output — don't validate this against assumed or hand-written sample log lines.
- Add a **fallback heuristic** independent of the regex: if no completion match is observed within a configurable timeout, treat the save as complete-by-timeout with a logged warning, rather than hanging indefinitely if the regex is ever wrong (Purpur log format can change between versions).

#### 3.3.6 Saga step failures lose exception detail (🔶)
Currently: failures surface only as `Failed at step 'save_world'`, with no underlying cause — and this may share a root cause with 3.3.1/3.3.2, since both are ultimately about error/state visibility in the same pipeline.
**Recommended approach:**
- Preserve the exception chain explicitly (`raise SagaStepError(...) from e` in Python preserves `__cause__`), and surface it — don't swallow it at the saga-orchestration layer.
- Capture the underlying traceback in the saga's persisted state (not just the log), so a failure that happened hours ago is still diagnosable after the fact via the API/UI, not only by grepping logs at the time of failure.
- Investigate this alongside 3.3.1 and 3.3.2 rather than separately — if all three turn out to share a root cause in how the backup pipeline propagates and records state, fixing the shared cause is cheaper than three point fixes.

**Exit criteria for §3.3:** all three backup bugs (duplicate reconciliation, "marked as missing," saga error detail) are either closed with a regression test, or explicitly triaged in writing as won't-fix with a documented reason. The legacy-row fallback and `save-all` regex verification are both complete.

---

### 3.4 Phase 1 exit criteria (summary)

Phase 1 is done only when **all** of the following are true:
1. Authorization is fully closed — every mutating endpoint checked, CI-enforced, `contracts/permissions.yaml` complete.
2. The rate limiter is per-client, not process-global, with differentiated limit classes.
3. All three backup bugs are closed or explicitly triaged as won't-fix, with the legacy-row and regex items resolved.
4. `SECURITY.md` no longer contains a "partial enforcement" caveat.

---

## 4. Phase 2 — Identity & Authorization Redesign 🔶
⛔ **Blocked on Phase 1.** Redesigning the permission model while the current one has open holes means building the new system on top of unverified foundations — any gap papered over now becomes a gap baked into the new schema.

### 4.1 RBAC/ABAC redesign

**Current limitation:** permissions are stored as comma-separated text — no structure, no queryability, no way to express group membership or scoped/conditional access.

**Recommended design**
- **Entities:** `Role`, `Permission`, `Group`, `RoleAssignment` (user↔role, optionally scoped to a group).
- **Permission naming:** namespaced `resource:action` strings (e.g., `server:delete`, `backup:restore`), with wildcard support (`server:*`) for admin-style roles — this keeps the format human-readable and greppable in logs/audits, while still being structured enough to query.
- **RBAC vs ABAC split:** use RBAC (role → permission set) for the coarse "can this user category do this action at all" check, and layer ABAC predicates on top for resource-level ownership checks (e.g., "can edit *their own* servers" vs "can edit *any* server") — trying to force ownership logic into pure RBAC roles leads to role explosion (one role per resource-owner combination).
- **Migration path:** write a one-time migration that parses the existing comma-separated permission strings per user and inserts equivalent `RoleAssignment`/`Permission` rows, so no user silently loses access during the cutover. Run this against a copy of production data first, diff old-vs-new effective permissions per user, and only then run it live.

### 4.2 Users / Roles / Permissions / Groups admin panel
Backend (CRUD + assignment APIs, all gated by the new permission model itself — the admin panel is not exempt from its own authz) and frontend (management UI). This is naturally sequenced after §4.1's schema is stable, since the UI is a thin layer over it.

### 4.3 JWT key persistence fix
**Current problem:** the signing key is auto-generated in-process and lost on restart — every restart invalidates every outstanding token, forcing all users to re-authenticate.

**Recommended solution**
- Generate the signing key once, on first boot, and persist it — either as an encrypted value in the database (encrypted with a value from the deployment's existing secrets/config, not stored in plaintext next to the data it protects) or as a file with restricted OS permissions, consistent with how other secrets in the deployment are already handled.
- Support **key rotation** from the start rather than retrofitting it later: include a `kid` (key ID) header on issued tokens, and allow the service to accept tokens signed by either the current or the immediately-previous key during a rotation window, so rotating the key doesn't force an instant mass logout either.

**Exit criteria:** RBAC/ABAC schema replaces comma-separated permissions with no access regressions (verified against the migration diff); admin panel is functional and itself permission-gated; JWT signing key survives restarts and supports rotation without forcing all sessions to invalidate simultaneously.

---

## 5. Phase 3 — Deployment Mode & Remote Access 🔶
⛔ **Blocked on Phase 1 AND Phase 2.** This phase's entire purpose is exposing the application beyond the local network. Every authorization or rate-limit gap that was tolerable as "someone on my Wi-Fi" becomes "anyone on the internet" the moment this phase ships. It does not start before the permission model (Phase 2) is solid.

**Scope note — flag if this assumption is wrong:** this phase covers reaching **your own single running instance** remotely (phone, a friend's house, on the road). It is explicitly **not** multi-tenant hosting for other people's instances, and it is distinct from Phase 6 (Remote Agents / Multi-node), which is about controlling multiple *separate physical machines* from one dashboard. Multi-tenant hosting is a materially larger scope (isolation, billing, per-tenant resource limits, abuse handling) and would need its own dedicated design conversation before any of it is scheduled.

### 5.1 Installer flow
- New install-wizard step, asked explicitly with **no silent default**: *"Local only (this network)"* vs *"Publish (accessible from the internet)."* Forcing an explicit choice (rather than defaulting to either option) avoids both "user didn't realize they were exposed" and "user didn't realize they had to configure something extra to get remote access."
- **Local only** → binds to localhost/LAN interface only, no tunnel, no public exposure. This is today's behavior and requires no new work beyond the wizard step itself.
- **Publish** → triggers the remote-access stack in §5.2–5.3.

### 5.2 Removing the port-forwarding burden

**The actual problem being solved:** without this phase, "publish" means the user manually configures port forwarding, UPnP, a static IP, or dynamic DNS — a real barrier for non-technical users, and a common source of misconfigured, insecure exposure (e.g., forwarding a port and forgetting it's open).

**Options evaluated:**

| Option | Pros | Cons |
|---|---|---|
| Bundled tunnel client (Cloudflare Tunnel–style) | Works behind CGNAT/NAT with zero router config; free tier available; no inbound port ever opened on the user's router | Third-party dependency; requires an account/token for the tunnel provider; adds an external service to the trust chain |
| Self-hosted reverse relay | No third-party dependency; full control | The project would need to operate and secure relay infrastructure itself; real ongoing hosting/ops cost; a bigger initial build |
| UPnP auto port-mapping | No external service at all | Unreliable behind carrier-grade NAT (increasingly common on residential ISPs); routers vary widely in UPnP support/quality; auto-opening ports is itself a mild security smell that needs to be offset by strong auth on the exposed service |
| Dynamic DNS + automated TLS (Let's Encrypt) | Works well for users who already have a domain; standard, well-understood stack | Still requires port forwarding under the hood unless combined with a tunnel; not zero-config for the target "just works" user |

**Recommendation:** ship the **bundled tunnel client as the default, first-class "Publish" path** — it's the only option that reliably works for users behind CGNAT with zero manual router configuration, which is the actual UX goal of this phase. Offer **UPnP as an opt-in fallback** for advanced users who prefer not to depend on a third-party tunnel provider and understand the tradeoff. Offer **DDNS + automated TLS as a manual/advanced path** for users who already own a domain and want to self-manage. A fully self-hosted relay is a reasonable **future stretch goal** once the simpler paths are proven, not a Phase 3 requirement.

**Non-negotiable regardless of which tunnel option is chosen:** the tunnel endpoint must go through the *exact same* authorization stack as every other entry point — it cannot become a second, unauthenticated attack surface. Concretely, this means terminating the tunnel in front of the existing FastAPI auth middleware, not routing tunnel traffic around it, and (recommended) adding a shared secret or mTLS between the tunnel client and the app itself so a compromised tunnel provider can't inject traffic that looks locally-sourced.

### 5.3 Hardened defaults in "Publish" mode
- Rate limiting must already be per-client (Phase 1.2) before this ships — a global bucket facing the public internet is a trivial DoS vector, not a hypothetical one.
- Auto-enable stronger session/auth defaults specifically in publish mode: shorter access-token lifetimes, mandatory HTTPS (refuse to publish over plain HTTP), optional 2FA.
- Phase 2's RBAC/ABAC becomes **mandatory-enforced everywhere** in publish mode — unauthenticated access to *anything* is the exception that must be explicitly allow-listed, not the default.

**Open questions to resolve before this phase is scheduled in detail:**
- Confirm the single-instance-remote-access scope assumption above (vs. multi-tenant hosting, which is out of scope as currently understood).
- Final tunnel/relay decision: bundled third-party tunnel (recommended default) vs. self-hosted relay vs. UPnP-only.
- Whether 2FA is mandatory or optional in Publish mode — recommend starting **optional but strongly prompted** at first publish, revisiting mandatory once adoption data exists.

**Exit criteria:** install wizard requires an explicit local/publish choice; publish mode reliably works behind CGNAT without manual router configuration; tunnel traffic is provably subject to the same authz as local traffic; rate limiting and hardened session defaults are active by default in publish mode.

---

## 6. Phase 4 — Frontend Redesign & Parity 🔶 *(expanded scope)*
⛔ Depends on Phase 2 (permission model — the UI needs a stable backend to wire against) and benefits from Phase 3 being scoped, since the install wizard's local/publish step belongs in this phase's UI work.

- This is a genuine UX/design pass, not a "wire the UI to whatever the backend already has" checklist.
- Wire the frontend to the full backend surface: Health Engine, Discovery, Crash Diagnostics, Backup, and the new admin panel from Phase 2.
- Build the install wizard UI for the local/publish choice (§5.1).
- Specific design direction is intentionally undefined here — bring concrete pain points and/or visual references when this phase actually starts, rather than starting from a blank brief. (The `frontend-design` guidance can inform typography/layout decisions once this phase begins.)

---

## 7. Phase 5 — AI Agent Layer 🔶 *(full feature scope)*
⛔ **Hard-blocked on Phase 2.** This is the highest-leverage, highest-risk phase in the roadmap: an agent that can create servers, manage users, and toggle backups is a new actor with broad reach. Any authorization gap left open by this point becomes agent-exploitable, not just user-facing — and that risk compounds further once Phase 3 makes the agent reachable from the internet rather than just the LAN.

**Non-negotiable guardrails — built in from the start, not retrofitted:**
1. Agent actions route through the *exact same* permission layer as normal API calls. No privileged bypass path, ever — including for "trusted" internal agent calls.
2. Explicit user confirmation is required **before** any destructive action (delete server/user/backup) — a required before-the-fact gate, not an after-the-fact review/undo.
3. Full audit trail of every agent-issued command, attributable to the invoking user (not just "the agent did it").
4. The pipeline is: natural-language request → structured plan → execution — with CLI, API, GUI, and Agent all calling the **same** internal services underneath. "All AI features" means this complete pipeline; a partial demo that bypasses structured planning or shares no code path with the other interfaces does not satisfy this phase.

---

## 8. Phase 6 — Remote Agents / Multi-node 🔶
⛔ Depends on Phase 1's security posture being solid — a remote agent is a new trust boundary, and extending an unproven auth model across a network multiplies its blast radius rather than containing it.

**Distinct from Phase 3:** this phase is about controlling multiple *separate physical machines* from one control plane/dashboard. Phase 3 is remote access to a *single* instance. These should not be conflated in planning or in the eventual UI — they solve different problems and likely need different trust models (Phase 3 trusts "you, from anywhere"; Phase 6 trusts "this control plane, talking to that node").

---

## 9. Phase 7 — Container Plugin Isolation 🔶
- Finish `ContainerPluginRunner`, currently a stub — Docker-based isolation layered on top of the existing subprocess + JSON-RPC isolation, giving plugins a harder sandbox boundary than process isolation alone provides.

---

## 10. Phase 8 — Monitoring Depth 🔶
- Metrics retention rollups (1 minute / 1 hour / 1 day) — currently raw-only, which is fine for live dashboards but not sustainable for long-term storage or historical trend views.
- Historical dashboards, built on top of the rollup data above.

---

## 11. Phase 9 — v1.0 🔶
- Full documentation pass and public release readiness review.
- Cross-reference check across ADRs / `API.md` / `ARCHITECTURE.md` / `DEPLOYMENT.md` to confirm nothing drifted out of sync during Phases 1–8.

---

## 12. Explicit non-goal for right now

No feature work on Phase 2 or later starts while Phase 1 has open items. This document exists specifically to prevent scope from planning conversations (vision documents, feature requests) from leaking into the current security-hardening work. If a request doesn't help close a Phase 1 exit criterion, it belongs in a later phase's backlog, not in this week's work.

---

## 13. Decision log — items requiring an explicit answer before downstream phases can be scoped in detail

| # | Question | Recommendation | Status |
|---|---|---|---|
| 1 | Rate limiter storage: in-process dict vs. shared store (Redis)? | In-process for now (single-instance deployment); revisit if/when multi-worker scaling is planned | Open |
| 2 | Phase 3 scope: single-instance remote access vs. multi-tenant hosting? | Single-instance, as scoped in §5 | Open — confirm |
| 3 | Tunnel/relay approach for Phase 3 | Bundled third-party tunnel (Cloudflare Tunnel–style) as default; UPnP opt-in; DDNS+TLS for domain owners; self-hosted relay as future stretch goal | Open — confirm |
| 4 | 2FA mandatory or optional in Publish mode? | Optional but strongly prompted at first publish; revisit once adoption data exists | Open |
| 5 | JWT signing key storage location (DB, encrypted vs. secrets file) | Match existing secrets-handling convention in the deployment; add `kid`-based rotation regardless of storage choice | Open |

---

## 14. Sources

- `STATUS.md` (Batch 1–8, through 2026-08-01)
- Vision documents shared 2026-08-02 (capability summary + AI-first pitch)
- This session's live findings: global rate-limit bucket, three open backup bugs, port-forwarding/remote-access requirement

---

*This version supersedes the prior personal working draft. It is intended to be repo-committable once the open questions in §13 are answered; until then, treat §5 (Phase 3) and any item marked "Open" as pending confirmation rather than settled decisions.*
