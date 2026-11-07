# ADR-0015: Runtime Domain Entity and ServerProvider Infrastructure Relationship

**Status**: Accepted  
**Date**: 2026-09-17  
**Author**: Stage A Architecture Team  

## Context

The initial Enterprise Branch Runtime design proposal assumed that runtime execution mechanics needed ground-up re-architecture to support containerized isolated execution. However, codebase audit confirmed that Phase 5 (`DockerProvider`) already shipped full container lifecycle management, per-container resource policies, and isolated per-test containers. Furthermore, `ServerProvider` (`backend/app/modules/server/infrastructure/providers/base.py`) already provides an extensible abstraction with `capabilities()` and proven decorator patterns (`CircuitBreakerProviderWrapper`).

The architecture needed to define the precise relationship between the new `Runtime` domain entity and the existing `ServerProvider` infrastructure.

## Decision

1. **Domain Representation**:
   - `Runtime` is defined as a pure domain entity in `backend/app/modules/versioning/domain/entities.py`.
   - Critical Invariant 1: A `Runtime` is pinned to an immutable `commit_id` and a specific `materialization_id`. It must never bind directly to a mutable `branch` reference, and its `commit_id` cannot be altered after instantiation.
   - A `Runtime` cannot reference a `Materialization` that is in `REMOVED` status.

2. **Infrastructure Relationship**:
   - `Runtime` wraps and delegates execution to `ServerProvider` implementations (`DockerProvider`, `LocalLinuxProvider`, `LocalWindowsProvider`).
   - No breaking changes or renaming sweeps are made to `ServerProvider`, its public capabilities vocabulary (`"process"`, `"console"`, `"exec"`), or container execution mechanics.
   - Runtime status is queried directly from the underlying provider rather than maintaining a duplicate parallel lifecycle engine.

3. **Concurrency and Locks**:
   - Per Invariant 2 (closed as option c – defer), the existing per-server execution lock (`_server_locks` + `ConflictError`) in `DockerTestExecutionRunner` remains in force and untouched in Stage A. Concurrency redesign and global admission control are deferred to Stage D/F.

## Consequences

- Domain logic remains clean and testable without importing Docker or process SDKs.
- Existing working container infrastructure is reused completely with zero regression risk.
- Future Stage D scheduling work can build on top of the pinned `Runtime` domain model.
