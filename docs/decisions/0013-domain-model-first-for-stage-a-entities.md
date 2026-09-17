# ADR-0013: Domain-Model-First for Stage A Entities (Revision, Materialization, PersistentDataset)

**Status**: Accepted  
**Date**: 2026-09-17  
**Author**: Stage A Architecture Team  

## Context

The Enterprise Branch Runtime Platform refactor introduces several new concepts to decouple branch pointers, immutable commits, isolated working directories, and execution instances: `Revision`, `Materialization`, `PersistentDataset`, and `Runtime`.

A architectural fork existed between:
1. Creating new database tables, Alembic migrations, and parallel persistence engines for all entities simultaneously with domain definitions.
2. Establishing a domain-model-first foundation within `backend/app/modules/versioning/domain/`, defining explicit identities, value objects, lifecycles, and rejecting invariants first, while retaining existing persistence mechanisms for shipped behavior.

## Decision

We adopt a **domain-model-first** design for the Stage A entities:
- `Revision` is formalized as an immutable value object binding a resolved `commit_id` and resolution source.
- `Materialization` is formalized as a domain entity with lifecycle (`pending` → `ready` → `stale` → `removed`) and filesystem root isolation invariants.
- `PersistentDataset` is formalized as a mutable data abstraction distinct from versioned `Tree` configuration.
- `Runtime` is formalized as an execution instance strictly bound to an immutable `commit_id`.

No parallel persistence engines or new database tables are created in Stage A. Persistence schema additions are deferred to their governing stages (Stage B for version control/tags, Stage C for filesystem materialization metadata, Stage D for runtime admission and scheduling).

## Consequences

- The domain layer explicitly enforces safety invariants (e.g. Runtime cannot bind to a mutable branch; Materialization cannot stage outside its isolated root; writes cannot escape into tracked Tree files).
- Existing database tables (`server_branches`, `server_commits`, `server_test_runs`) remain backward-compatible with zero migration overhead or data risk in Stage A.
- Stages B–G build directly on validated domain models rather than premature database abstractions.
