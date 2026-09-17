# ADR-0014: Shared Commit DAG Migration Strategy and Branch Lifecycle State Machine

**Status**: Accepted  
**Date**: 2026-09-17  
**Author**: Stage A Architecture Team  

## Context

ONX Manager shipped with a linear, branch-scoped commit history: `ServerCommit` carries `branch_id: str | None` and `parent_commit_id: str | None` (referencing exactly one parent commit). `ServerBranch` had no status field to represent its lifecycle (`created` → `active` → `archived`).

To support Git-like version control in Stage B (branching from arbitrary historical commits, tags, merges with multiple parents, and DAG ancestry traversal), the platform requires:
1. An explicit lifecycle state machine for branches (`BranchStatus`).
2. A safe, additive migration strategy from the single-parent, branch-scoped model to a shared commit Directed Acyclic Graph (DAG) without breaking existing history or requiring data rewrites.

Per the approved Stage A design specification (`docs/design/testing-system-refactor/01-stage-a-domain-reconstruction-design-spec.md`), this ADR must be written and approved before any Stage B multi-parent work begins.

## Decision

1. **Branch Lifecycle State Machine**:
   - `ServerBranch` adopts an explicit `status: BranchStatus` field with values `CREATED`, `ACTIVE`, `ARCHIVED`.
   - Transitions:
     - `CREATED` upon initialization without a head commit.
     - `CREATED` → `ACTIVE` upon the first head-advancing commit.
     - `ACTIVE` → `ARCHIVED` via explicit operator action only.
   - Invariant: Committing to an `ARCHIVED` branch is strictly rejected.

2. **Commit DAG Migration Strategy**:
   - Single-parent commit chains are recognized as a valid degenerate case of a DAG.
   - Stage A formalizes `ServerCommit` immutability, single-parent validation, and cross-server parent rejection in code.
   - In Stage B, multi-parent support will be introduced additively (e.g. `commit_parents` relationship table or non-breaking array representation) while preserving `parent_commit_id` as primary parent for legacy readers.
   - Historical commits remain unchanged; no rewriting of existing linear commit rows is required.
   - Merge commits in Stage B will explicitly link multiple parents in the same repository/project and enforce cycle-free DAG validation.

## Consequences

- In Stage A, branch lifecycle invariants protect against committing to archived branches.
- Existing single-parent commits continue to work seamlessly without database schema alterations.
- Stage B has an authorized roadmap and design boundary to implement persistent commit ancestry and merge commits without structural conflict.
