# ADR-0016: PersistentDataset Boundary and Non-Mutation Isolation

**Status**: Accepted  
**Date**: 2026-09-17  
**Author**: Stage A Architecture Team  

## Context

Minecraft servers generate substantial mutable runtime state during execution: world region chunks, player inventories, entity data, session locks, and temporary cache files. Mixing this mutable state into version-controlled snapshots creates storage explosion, dirty commits, and corrupt histories.

In Phase 4 Feature 1, isolated test runs solved this by leveraging copy-on-write (COW) reflink snapshots (`BtrfsZfsSnapshotDriver.clone_world`), allowing test containers to mutate worlds freely without touching production data. The Enterprise Branch Runtime requires formalizing this safety boundary into the domain layer.

## Decision

1. **Explicit Entity**:
   - `PersistentDataset` is formalized as an explicit domain entity in `backend/app/modules/versioning/domain/entities.py`.
   - It represents runtime-generated mutable state (such as world saves) that is intentionally excluded from immutable `Tree` snapshots.

2. **Critical Invariant 3 (Non-Mutation Isolation)**:
   - Writes to a `PersistentDataset` MUST NOT silently mutate `Commit`, `Tree`, or `Branch` pointers.
   - Any write path inside a `PersistentDataset` must not resolve into or overwrite the tracked configuration set (`Tree.configs` or `Tree.mods`).
   - Transfer of mutable runtime changes back into versioned state (e.g. promoting world modifications) is always an explicit, reviewable operator action gated by verification (such as `PromoteCommitCommand` with `keep_world_changes=True`).

## Consequences

- Versioned desired state (`Tree` / `Commit`) remains pure, deterministic, and immutable.
- World mutations during runtime or bot testing cannot corrupt version control history or production assets.
- Stage C materialization and Stage F test platform will adhere strictly to these dataset boundary validations.
