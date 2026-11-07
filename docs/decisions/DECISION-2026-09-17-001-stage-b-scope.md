# DECISION-2026-09-17-001 — Stage B (Real Version Control) Scope Authorization

**Date:** 2026-09-17  
**Decision Level:** D2 (Major) — per project governance standards: changes persistence strategy, core contracts, and migration strategy.  
**Lane:** Release Improvement (per project governance standards) — planned platform refactor under the Enterprise Branch Runtime effort.  
**Status:** Approved (Authorized by Mohamed 2026-09-17; Built & Verified in commit `641ea58`)  

---

## Context

Stage A (Domain Reconstruction) closed 2026-09-17, verified: 20/20 new invariant tests, 60/60 versioning suite (40 pre-existing + 20 new), 2753/6/0 full backend suite (zero regressions from the 2733/6/0 baseline), 6/6 CI quality gates, ADRs 0013-0016 filed. Stage B is the next stage of the Enterprise Branch Runtime rebuild (`docs/design/testing-system-refactor/`), adding real persistent version control on top of Stage A's domain model. Design Review of the Stage B spec (2026-09-17) returned CONDITIONAL APPROVAL, with this decision record as one of three required pre-Build items.

## Decision

Authorize Stage B scope as specified in `03-stage-b-real-version-control-design-spec.md`:

- Multi-parent commit DAG persistence — additive migration per ADR 0014 (a `server_commit_parents` junction table; legacy `parent_commit_id` column preserved for existing readers; single-parent commits remain a valid degenerate case).
- Persisted Branch lifecycle — a `status` column + migration + repository mapping (`BranchStatus.ACTIVE` vs `BranchStatus.ARCHIVED`), closing a gap Design Review found: Stage A's archived-branch invariant was unenforced after a DB round-trip because `BranchStatus` was previously domain-only.
- New `ServerTag` entity (name + commit_id, immutable, unique per server repository).
- Deterministic Commit/Tree diff (`diff_trees`, `diff_commits`).
- Merge commit creation (`MergeCommitsCommand` with multiple valid parents, atomic persistence, conflict detection on divergent manifests without explicit resolution).
- Repository history/ancestor queries (`GetBranchHistoryQuery`, `traverse_history`, `check_cycle`) with explicit topological ordering.
- 7 new API routes with corresponding `contracts/permissions.yaml` entries advancing live routes from 121 to 129.

## Alternatives Considered

1. **Defer Stage B entirely, stop at Stage A.** Rejected — Stage A's domain model (Revision, Branch lifecycle, Commit) delivers little standalone value without persisted history and real branching.
2. **Keep BranchStatus domain-only, skip persisting it.** Rejected — Design Review found this leaves the archived-branch invariant unenforceable after any DB round-trip.
3. **Shell out to real `git` instead of an internal DAG model.** Already decided against in ADR 0013/0014 (domain-model-first, direct DAG persistence).

## Rollback Path

The multi-parent migration is additive: single-parent commits remain valid, and the legacy `parent_commit_id` column is preserved for existing readers per ADR 0014. Reversible via standard downgrade `b1e2100000015 -> b1e2100000014`.

## Decided by

Approved by Mohamed (2026-09-17). Built in commit `641ea58` and verified green.
