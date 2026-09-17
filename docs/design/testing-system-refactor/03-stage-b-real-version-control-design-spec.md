# Design Spec — Stage B: Real Version Control

**Status:** Design-Reviewed (2026-09-17) — CONDITIONAL APPROVAL pending `DECISION-2026-09-17-001` sign-off. Do not build until that decision record is approved.
**Prerequisite verified:** Stage A CLOSED 2026-09-17 — 20/20 new invariant tests pass, 60/60 versioning suite, 2753/6/0 full backend suite (zero regressions from the 2733/6/0 baseline), 6/6 CI gates, ADRs 0013-0016 written.

---

## Goal

Add persistent, Git-like version control on top of the Stage A domain model: commit ancestry as a real DAG, multi-parent merge commits, branching from arbitrary historical commits, immutable tags, deterministic diffs, and history queries — **extending** Stage A's entities, not replacing them.

## Current Behavior (verified against the Stage A completion report, 2026-09-17)

- **Commit** — immutable snapshot referencing a Tree + single parent, with validation rejecting dangling/cross-server parents. Multi-parent support does **not** exist — Stage A's own Out-of-Scope confirmation states this explicitly.
- **Branch** — named mutable pointer, lifecycle `CREATED → ACTIVE → ARCHIVED`, rejects commits to archived branches. Per the original Sept-16 RECON (pre-Stage-A), `CreateBranchCommand` already accepted an arbitrary `head_commit_id` at the command layer — **this must be reconfirmed post-Stage-A**, not assumed, since `create_branch.py` was modified during Stage A build ("validated head commit existence and initialized `BranchStatus.ACTIVE` if commit supplied else `BranchStatus.CREATED`").
- **Revision** — immutable value object binding resolved `commit_id` + resolution source **already exists** as a Stage A deliverable. Stage B may only need to add tag-name and branch-name resolution forms on top of it, not rebuild it.
- **ADR 0014** (`shared-commit-dag-migration-and-branch-lifecycle.md`) already exists and was written as part of Stage A — it should already contain the DAG migration strategy rationale. **Design Review must read this ADR's actual text** before approving this spec's "Proposed Change" below, since this spec was drafted from a summary of Stage A's report, not from ADR 0014 itself.
- **Tag** — no entity or table exists.
- **Diff** — no comparison logic exists.
- **Merge** — not possible; Stage A enforces single-parent as an explicit invariant.

## Proposed Change

- Extend `Commit` to support multiple parents (merge commits), per whatever migration strategy ADR 0014 actually specifies.
- Confirm or extend `create_branch(name, from_commit=<explicit commit id>)` — this may already be shipped; do not duplicate it.
- Add a `Tag` entity: `name` + `commit_id`, immutable, unique per repository, explicit conflict rejection on duplicate names.
- Add deterministic Tree/Commit diff: additions, removals, modifications, deterministic ordering, explicit invalid-reference errors.
- Add merge commit creation: multiple valid parent references, a valid result Tree, DAG integrity preserved, atomic persistence. **No automatic conflict-resolution algorithm** — if merge semantics are underspecified for a given case, that's a Hard Stop for Build, not something to improvise.
- Add repository history/ancestor queries with explicit, deterministic ordering (never raw DB row order).

## Affected Components

- `backend/app/modules/versioning/domain/entities.py`, `value_objects.py` — `Commit` (multi-parent), new `Tag`.
- `backend/app/modules/versioning/application/commands/` — `create_branch.py` (confirm/extend), new `create_tag.py`, new `merge_commits.py` (naming TBD by Design Review).
- `backend/app/modules/versioning/application/queries/` — new `diff_commits.py`, `get_ancestors.py` / `get_branch_history.py`.
- `backend/app/modules/versioning/infrastructure/models.py`, `repository.py` — schema migration for multi-parent references (junction table or parent-list column, per ADR 0014) and a new tags table.
- **`BranchStatus` persistence (added per Design Review, 2026-09-17 — closes a real gap, not optional polish):** Stage A implemented branch lifecycle domain-only. `ServerBranchModel` has no status column; `_branch_to_domain` (`repository.py:204`) *derives* status (`ACTIVE` if `head_commit_id` else `CREATED`) and can never return `ARCHIVED`; `save_branch` (`repository.py:54-69`) does not persist status; no archive command exists anywhere. Consequence: `create_commit.py:108`'s archived-branch rejection is dead code after any DB round-trip. This stage must add: a `status` column on `ServerBranchModel`, an Alembic migration, `save_branch`/`_branch_to_domain` mapping updates, and a round-trip test proving `ARCHIVED` survives reload and still rejects commits.
- ADR 0014 already covers the rationale — no new technical ADR needed for the migration approach itself (confirmed by Design Review against the ADR's actual text). The Stage B *scope* decision is documented separately in `DECISION-2026-09-17-001` (D2 record).

## Interfaces & Contracts

**Route Contract Plan (per Design Review pre-Build item 3 — permission mapping decided now; exact path spelling may still be adjusted at Build time to match existing naming conventions, which should be spot-checked before Build):**

| Capability | Proposed route (server-scoped, matching existing `/servers/{server_id}/...` convention) | Permission |
|---|---|---|
| Branch from arbitrary commit | Already shipped via `create_branch.py` (`head_commit_id` param) — no new route | Existing `branch:create` |
| Create tag | `POST /servers/{server_id}/tags` | New `tag:create` |
| List/resolve tag | `GET /servers/{server_id}/tags`, `GET /servers/{server_id}/tags/{name}` | New `tag:read` |
| Diff two commits | `GET /servers/{server_id}/commits/diff?from={id}&to={id}` | New `commit:diff` (read-level) |
| Create merge commit | `POST /servers/{server_id}/commits/merge` | New `commit:merge` |
| Branch/commit history | `GET /servers/{server_id}/branches/{name}/history` | New `branch:read` (may reuse existing read permission — confirm at Build) |
| Archive/reactivate branch | `POST /servers/{server_id}/branches/{name}/archive` (new — currently no archive command exists anywhere) | New `branch:archive` |

Every new route above must get a `contracts/permissions.yaml` entry before Build, so `check-route-contract` passes. No changes to `ServerProvider`, `Runtime`, or `DockerProvider` — Stage B stays domain + persistence + API only. The per-server execution lock stays exactly as Stage A left it (deferred to Stage D/F).

## Failure Cases & Edge Cases

- Existing single-parent commits must migrate into the multi-parent-capable schema as a degenerate 1-parent case — additive, not a breaking rewrite.
- Cycle prevention: a commit must never (transitively) be its own ancestor.
- Cross-repository/cross-project parent references rejected explicitly.
- Merge commits with underspecified conflict semantics → explicit stop/escalation, never a guessed automatic resolution.
- Tag name collisions rejected explicitly, never silently overwritten.

## Tests & Verification

- New rejecting tests: dangling parent, self-parent, cross-project parent, duplicate parent, cycle, tag conflict, diff determinism.
- Confirm (don't rebuild) that Stage A's `Revision` already handles "moving a branch after resolution doesn't change the resolved commit" — write a test only if one doesn't already exist from Stage A.
- Full regression: the versioning suite (currently 60/60: 40 pre-existing + 20 Stage A invariant tests) plus Stage B's own new suite must stay green.
- **Baseline to protect:** 2753 passed / 6 skipped / 0 failed (Stage A's verified post-change state). Any regression against this blocks close.

## Out of Scope (this stage)

- Filesystem materialization work (Stage C).
- Scheduler / resource pool (Stage D) — Invariant 2's lock stays exactly as Stage A left it.
- Observability / console streaming (Stage E).
- Full test-platform rework (Stage F).
- Enterprise RBAC / branch protection (Stage G).
- Full Git-protocol compatibility; automatic merge-conflict resolution.

## Governance / Design Review Status

**Design Review complete (2026-09-17): CONDITIONAL APPROVAL.** Reviewed against fresh code reads (not carried-over claims). Findings:
- Item 1 (arbitrary-commit branching) — CONFIRMED already shipped in `create_branch.py`; Build must reuse it, not duplicate it.
- Item 2 (ADR 0014 match) — MATCHES on migration strategy, with one real gap found and now folded into Affected Components above: `BranchStatus` was never persisted, making the archived-branch invariant unenforceable after a DB round-trip.
- Item 3 (D2 classification) — CONFIRMED. Documented in `DECISION-2026-09-17-001`.

**Remaining before a Build Prompt may be issued:**
1. ✅ Done — `BranchStatus` persistence added to Affected Components (above).
2. `DECISION-2026-09-17-001` filed — pending Mohamed's sign-off.
3. ✅ Done — Route Contract Plan added above; exact path spelling should still be spot-checked against existing naming conventions at Build time.

Once Mohamed signs off on the decision record, this spec is Build-ready.
