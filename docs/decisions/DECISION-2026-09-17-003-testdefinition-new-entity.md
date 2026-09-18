# DECISION-2026-09-17-003 — TestDefinition as a Distinct Domain Aggregate

Status: Approved
Lane: B (Release Improvement)
Decision level: D2 (Major)
Roadmap drift: None — directly matches Stage F's outline mandate

## Context

Stage F's outline (`docs/design/testing-system-refactor/02-stages-b-through-g-outline.md:33-37`) explicitly calls for "Making TestDefinition/TestRun first-class, bound to exact revisions."

A decision was needed on whether `TestDefinition` should be a new domain entity or an extension of the existing `TestSpec` (`backend/app/modules/versioning/infrastructure/test_runner.py:70-81`, an ephemeral Phase 4 execution artifact).

## Evidence

- `TestSpec` is a frozen dataclass living in `infrastructure/test_runner.py` (outside the domain layer) that binds a specific `test_id`, a specific `commit`, and a concrete host filesystem path (`server_dir`). It cannot exist before a commit and target directory exist.
- A `TestDefinition`, per the original Enterprise Branch Runtime report §4, is a reusable specification ("Standard Smoke Test", "50-Player Modded Load Test") declaring what to run, which bot technology to invoke, what assertions to verify, and execution policies. It is executed repeatedly across many revisions, with each execution instantiating a `TestRun`.

## Options

1. **Option (a) — Extend `TestSpec` with persistence and metadata**: Pollutes an ephemeral infrastructure struct with domain concerns (persistence IDs, name/description metadata, assertion rules, and nullable commit/directory fields). Blurs architectural boundaries between domain intent and concrete execution handles.
2. **Option (b) — Introduce a new domain entity `TestDefinition` in `domain/entities.py`**: Clean domain aggregate. `TestSpec` is retained as the ephemeral runtime-compiled execution context (`TestDefinition` + target `Commit`/`Revision` → `TestSpec`).

## Decision

**Option (b) — Introduce `TestDefinition` as a new distinct domain entity.**

`TestDefinition` will be added to `backend/app/modules/versioning/domain/entities.py` as a first-class domain aggregate backed by a new persistence table `server_test_definitions`. `TestSpec` is retained in the infrastructure layer as the compiled execution payload passed to the runner.

## Why

Option (b) keeps the domain layer clean and adheres to hexagonal architecture:
- Preserves `TestSpec`'s single responsibility: a compiled, ephemeral runtime execution payload.
- Provides a proper domain home for reusable, storable test specifications as mandated by Stage F's outline.
- Decouples reusable test requirements from specific commit/filesystem bindings.

## Impact

- **Product/user:** Admins can define and manage reusable, named test configurations across different branches and revisions.
- **Stability:** High; existing ad-hoc test executions relying directly on `TestSpec` remain unaffected.
- **Performance:** Negligible; persists reusable templates in database.
- **Architecture:** Establishes a clean progression: `TestDefinition` (reusable spec) + `Revision` (commit target) → `TestSpec` (compiled run spec) → `Runtime` (container/process handle) → `ServerTestRun` (verified outcome & evidence).
- **Operations:** Additive schema migration adding `server_test_definitions` table and repository methods.

## Effort

M (Medium).

## Reversibility

High — independent new domain aggregate and additive persistence table.

## Roadmap impact

Directly enables Stage F's stated scope (first-class TestDefinition/TestRun, structured assertions/evidence, retention/cleanup).

## Verification

To be confirmed at Stage F Build/Verify:
- Domain aggregate invariant tests pass.
- Repository unit/integration tests for `TestDefinition` pass cleanly.
- Additive database migration applies cleanly forward and backward.

## Outcome

Pending Stage F Build.
