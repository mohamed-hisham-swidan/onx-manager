# MCS Manager — Decision Records (D1–D13)

**Part VIII** of the Engineering Blueprint V4. This is the **decision log**: every open decision that
is *not yet* an ADR (the committed decisions live in `docs/decisions/`, ADRs 0001–0012). Each entry
records what the decision is, where it lives, why it's open, and what resolving it depends on — in
ADR-format shape (Context / Options / Path / Consequences), but marked **Open** until decided.

**Last updated:** 2026-08-06

> **Gap disclosure (carried from the V4 source-material note in `00` §0):** the prior V4 roadmap
> referenced a "Volume 10 — Decision Log (D1–D13)" that was not present in the surviving text.
> D1–D6, D9, and D11–D13 are reconstructed **from their references** throughout the surviving
> volumes — each entry below cites the exact text that proves the decision's content. **D7, D8, and
> D10 are never mentioned anywhere in the surviving volumes** and could not be reconstructed at all.
> They are logged below as **open gaps**, not invented. If a future session finds the original
> Volume 10, these three entries should be filled from it and this paragraph removed.

---

## How to use this log

- **A decision is open until** a resolution is recorded here and, where appropriate, a code change +
  test land (Part III §6 ADR process, Part I §9 preservation).
- **Deferred decisions are tracked, not forgotten** — a decision deferred (as several are) stays
  here until resolved.
- **Resolving a decision here** does not delete it; it is marked **Resolved** with the outcome, per
  append-only canon.

---

## 1. D1 — Sensitive GET-route classification 🔶 Open

**Context (from `05` §2.3, carried from v3, live-verified 2026-08-05):** the count of sensitive
`GET` routes that are auth-only but carry no permission check is disputed — "23" by a strict
middleware count vs. an earlier "21" using a different classification.

**Why open:** Phase 4's GET-route gating work can't start correctly until the classification is
settled; gating the wrong set wastes effort either way. Resolution of D1 must precede workstream
"gate the reconciled GET set" (`05` §2.3 step 4).

**Options:** (a) adopt the strict middleware count as canonical; (b) re-derive a single
classification rule; (c) record the discrepancy as a doc fix and gate against the reconciled rule.

**Owner:** Phase 4 (§2.3).

---

## 2. D2 — `contracts/permissions.yaml` version 🔶 Open — hard prerequisite for Phase 4

**Context (from `05` §2.8, carried):** committed HEAD is v1.3; the working tree has an
**uncommitted** v1.4 edit (adds 3 marketplace rows, still lists the now-deleted legacy install route
under `status: missing`).

**Why it's load-bearing:** §2.3's route-gating work can't proceed until (a) the v1.4 edit is
committed or discarded, and (b) the phantom deleted-route entry is removed. Gating against a contract
that may change out from under the work means doing the gating twice.

**Options:** (a) commit v1.4 as-is and remove the phantom entry; (b) discard the uncommitted edit and
regenerate; (c) version-bump discipline going forward (link to Phase 5 versioning rule).

**Owner:** Phase 4, first item in its sequencing (`05` §2.3 step 1, §2.8).

---

## 3. D3 — Pending working-tree diffs against a "done" phase 🔶 Open

**Context (from `04` §1.2, carried from v3 §2, unresolved):** two tracked, committed files carry
uncommitted changes: `backend/app/api/v1/routers/plugins.py` (8 commits, latest `b1b6dd8`) and
`backend/tests/api/test_api_endpoints.py` (9 commits, latest `b1b6dd8`). Pending diff: a
`_to_version_response()` helper and one new test `test_marketplace_versions_returns_files` (+54).

**Why it matters:** an open working-tree diff against a "done" phase (Phase 1) is a
documentation-vs-code mismatch waiting to happen — the exact class of error this blueprint's rewrite
exists to avoid.

**Options:** (a) commit the diff as its own commit per ADR-0010 discipline before Phase 1 closes
(recommended, per `04` §2.6); (b) discard; (c) fold into a Phase 1.5 verification pass.

**Owner:** Phase 1 close-out (`04` §2.6).

---

## 4. D4 — Marketplace route namespace 🔶 Open

**Context (from `04` §2.3, carried):** whether marketplace API routes stay under
`/servers/{id}/plugins/marketplace/*` or move to a marketplace-owned namespace.

**Why it matters now:** a route-namespace decision is required for a clean Phase 1 → Phase 2 handoff;
building new marketplace-adjacent frontend work against a namespace that might move means rework.
K5 (2026-08-06) already introduced a global search endpoint (`GET /marketplace/search`) distinct from
the server-scoped one, sharpening the question.

**Options:** (a) keep routes server-scoped, add global ones where semantics are global; (b) move to a
marketplace-owned namespace and shim compatibility; (c) document a single naming rule.

**Risk:** namespace churn is a breaking change needing a compatibility shim if resolved late (`04`
§2.8).

**Owner:** Phase 1 close-out (`04` §2.6).

---

## 5. D5 — Test re-baselining vs. real bug 🔶 Open

**Context (from `05` §1.5, carried):** 2 failing backend tests (per `current-state.md`, 2026-08-04,
not re-run since): `test_start_server` (closed-DB rollback in API teardown) and
`test_metrics_task_requires_collector` (stale expectation vs. graceful warning handler).

**Why open:** the decision is *which* of the two paths applies to *which* test — fix the underlying
defect vs. formally re-baseline a stale assertion. Guidance in `05` §1.5/§1.10: investigate
`test_start_server`'s teardown first; default to "assume real bug until proven stale" for
`test_metrics_task_requires_collector`.

**Options:** (a) fix both; (b) fix one + re-baseline the other; (c) re-baseline both (risky — could
hide a real defect).

**Owner:** Phase 3, K8 (`05` §1.5). **Resolution required for the "0 failures" acceptance criterion.**

---

## 6. D6 — Settings persisted field set 🔶 Open

**Context (from `05` §1.4, carried):** `PATCH /api/v1/settings` is a stub (`{"success": true,
"message": "Settings updated (stub)"}`) — nothing persists. The decision is the persisted field set:
start with what `GET /settings` already returns.

**Options:** (a) persist exactly the `GET /settings` field set; (b) a curated subset; (c) schema-driven
(generalize). Coupled with Phase 3's `settings:write` gate and Phase 2's "zero silently-no-op
controls" rule (`04` §3.6).

**Owner:** Phase 3, K3 (`05` §1.4).

---

## 7. D7 — [GAP] 🔶 Open — unverifiable from surviving sources

**Status:** This decision number is never mentioned in any surviving V4 volume. It could not be
reconstructed and is **not invented** here. See the gap disclosure at the top of this file.

---

## 8. D8 — [GAP] 🔶 Open — unverifiable from surviving sources

**Status:** Same as D7.

---

## 9. D9 — 2FA in publish mode 🔶 Open

**Context (from `07` §1.5, carried):** Phase 7 hardened defaults include "optional-but-strongly-prompted
2FA (**D9, open**)" alongside shorter access-token lifetimes and mandatory HTTPS.

**Why open:** TOTP (or another standard) needs a decision before Phase 7's publish-mode UX is built;
it affects the auth module (ADR-0005) and the login flow.

**Options:** (a) TOTP via a standard library; (b) WebAuthn/passkeys; (c) defer 2FA entirely and keep
it out of Phase 7 exit criteria (would need re-flagging in `07`).

**Owner:** Phase 7 (`07` §1.5).

---

## 10. D10 — [GAP] 🔶 Open — unverifiable from surviving sources

**Status:** Same as D7/D8.

---

## 11. D11 — Repo-root `data/` cleanup 🔶 Open

**Context (from `05` §1.6, carried):** Phase 3 should-fix K15: clean up the repo-root `data/`
directory — **confirm unused first**.

**Options:** (a) confirm unused and remove; (b) keep but document as legacy; (c) migrate its contents
into the configured `MCS_SERVERS_DATA_DIR` layout.

**Risk:** deleting live data the operator cares about. The "confirm unused first" step is the
decision's guard.

**Owner:** Phase 3, K15 (`05` §1.6).

---

## 12. D12 — DB upgrade policy: auto-upgrade vs. refuse-to-start 🔶 Open

**Context (from `05` §1.6, carried):** production DB is 3 Alembic revisions behind head (K9). The
decision is the standing policy: on startup, if the DB is behind the required revision, **auto-upgrade
on boot** or **refuse to start**. `05` §1.6 states D12 "should be resolved as part of this item, not
left dangling after the migration runs." Phase 5's per-release minimum-revision rule depends on it
(`06` §1.3 #3).

**Options:** (a) auto-upgrade with a logged decision; (b) refuse-to-start until operator acts; (c)
hybrid (auto-upgrade for patch-level, refuse for major).

**Owner:** Phase 3, K9 → Phase 5 (`05` §1.6, `06` §1.3).

---

## 13. D13 — Registration bootstrap (`POST /api/v1/users`) 🔶 Open — highest real-world risk item

**Context (from `05` §2.4, carried):** registration is open with no auth. The decision procedure
(carried, unchanged): investigate whether a **first-user-bootstrap exception** is safe and simple
(open only while zero users exist, then require `user:write`). If the investigation surfaces hidden
onboarding dependencies or ambiguous "first user" semantics, do **not** improvise — document the
finding in `docs/PERMISSIONS_FUTURE_IDEAS.md` and leave the route unchanged. **Not yet
investigated.**

**Why it can't just be deferred:** an unauthenticated user-creation endpoint on a system about to
gain network exposure in Phase 7 is a direct path to full account takeover if left unresolved; it is
an active, growing risk, not a neutral "known limitation." Recommended to be investigated *first*
within Phase 4's sequencing.

**Options:** (a) first-user-bootstrap exception (open only while zero users exist); (b) leave
unchanged + document; (c) registration invite/secret token.

**Guardrail:** the documented fallback (leave unchanged, log finding) is explicitly sanctioned — take
it rather than ship a rushed half-fix (`05` §2.12).

**Owner:** Phase 4, §2.4 — must be resolved before Phase 7.

---

## 14. Resolution log

This section is append-only. As decisions resolve, add a dated entry marking the decision **Resolved**
with the outcome, the code change that implemented it (if any), and the test that proves it.

| Decision | Status | Resolution | Date |
|---|---|---|---|
| — | — | (none yet — all D1–D13 currently open) | — |

---

*Continue to Part IX [`12-working-agreements.md`](./12-working-agreements.md) — the contribution
workflow, commit strategy, and AI-collaboration rules that govern how all of the above gets built.*