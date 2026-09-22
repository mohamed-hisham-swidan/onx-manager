# DECISION-2026-09-17-001 — Stage B (Real Version Control) Scope Authorization

**Date:** 2026-09-17
**Decision Level:** D2 (Major) — per GOVERNANCE.md §4: changes persistence strategy, core contracts, and migration strategy.
**Status:** Approved (Authorized by Mohamed 2026-09-17; Built & Verified in commit `641ea58`)
**Canonical Location:** `docs/decisions/DECISION-2026-09-17-001-stage-b-scope.md`

## Context

Stage A (Domain Reconstruction) closed 2026-09-17, verified: 20/20 new invariant tests, 60/60 versioning suite (40 pre-existing + 20 new), 2753/6/0 full backend suite (zero regressions from the 2733/6/0 baseline), 6/6 CI quality gates, ADRs 0013-0016 filed. Stage B is the next stage of the Enterprise Branch Runtime rebuild (`docs/design/testing-system-refactor/`), adding real persistent version control on top of Stage A's domain model. Design Review of the Stage B spec (2026-09-17) returned CONDITIONAL APPROVAL, with this decision record as one of three required pre-Build items.

## Decision

Authorize Stage B scope as specified in `03-stage-b-real-version-control-design-spec.md` (Design-Reviewed 2026-09-17):

- Multi-parent commit DAG persistence — additive migration per ADR 0014 (a `commit_parents` table or equivalent; legacy `parent_commit_id` column preserved for existing readers; single-parent commits remain a valid degenerate case).
- Persisted Branch lifecycle — a `status` column + migration + repository mapping, closing a gap Design Review found: Stage A's archived-branch invariant is currently unenforceable after a DB round-trip because `BranchStatus` was never persisted.
- New `Tag` entity (name + commit_id, immutable, unique per repository).
- Deterministic Commit/Tree diff.
- Merge commit creation (multiple valid parents, atomic persistence, no automatic conflict-resolution algorithm — underspecified merge semantics are a Build-time Hard Stop, not something to improvise).
- Repository history/ancestor queries with explicit deterministic ordering.
- New API routes for the above (see the spec's Route Contract Plan) with corresponding `contracts/permissions.yaml` entries.

## Alternatives Considered

1. **Defer Stage B entirely, stop at Stage A.** Rejected — Stage A's domain model (Revision, Branch lifecycle, Commit) delivers little standalone value without persisted history and real branching, and the Enterprise Branch Runtime effort was already authorized into Phase 7 scope on 2026-09-16.
2. **Keep BranchStatus domain-only, skip persisting it.** Rejected — Design Review found this leaves the archived-branch invariant unenforceable after any DB round-trip (`create_commit.py:108`'s guard becomes dead code). Shipping Stage B on top of a known-broken invariant was judged worse than the small additive migration required to fix it.
3. **Shell out to real `git` instead of an internal DAG model.** Already decided against in ADR 0013/0014 (domain-model-first, direct DAG persistence) — not reopened by this record.

## Rollback Path

The multi-parent migration is additive: single-parent commits remain valid, and the legacy `parent_commit_id` column is preserved for existing readers per ADR 0014. Pre-merge (i.e., before any merge commits exist in production data), the migration can be reverted with a standard down-migration with no data loss. Once merge commits exist in production data, reversing the migration becomes difficult — this asymmetry is why Design Review classified reversibility as "moderate," not "high." No rollback plan is needed for the `BranchStatus` column addition itself (a simple additive column with a safe default).

## Impact

- **Architecture:** Commit model becomes a true multi-parent DAG.
- **Persistence:** new `commit_parents` (or equivalent) table, new `tags` table, new `status` column on `ServerBranchModel` + Alembic migration.
- **Contracts:** new API routes and `contracts/permissions.yaml` entries; must pass `check-route-contract`.
- **Roadmap:** stays inside the already-authorized testing-system-refactor / Phase 7 objective — no further roadmap reordering beyond what the 2026-09-16 decision already covers.

## Conditions (all required before a Build Prompt is issued)

1. ✅ Design Spec amended to include `BranchStatus` persistence in Affected Components (done, 2026-09-17).
2. This decision record filed and approved — **pending Mohamed's sign-off.**
3. ✅ Route Contract Plan added to the spec — exact path spelling should be spot-checked against existing naming conventions at Build time, but permission mapping is decided.

## Decided by

Drafted by Claude (Orchestrator) from independent Design Review evidence dated 2026-09-17. Requires Mohamed's explicit approval to take effect — this document is a proposal, not yet a ratified decision.
