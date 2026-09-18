# DECISION-2026-09-17-002 — Runtime Entity Attach Model for Test Execution

Status: Approved
Lane: B (Release Improvement)
Decision level: D2 (Major)
Roadmap drift: Controlled — scopes Stage F's Runtime work, does not expand it

## Context

The domain `Runtime` entity (`backend/app/modules/versioning/domain/entities.py:318-368`, formalized in Stage A) is currently unwired — it has no status field, no container/process binding, no database table, and is never instantiated during test execution. Test runs currently execute entirely through `ServerTestRunModel` + an in-memory `TestHandle`, bypassing `Runtime`.

A decision was needed on whether `Runtime` should REPLACE `ServerTestRunModel` as the execution record of truth, or ATTACH to it as a 1:1 execution handle.

## Evidence

A full code trace of every `ServerTestRunModel` read and write site across the repository:
- `backend/app/modules/versioning/presentation/versioning.py` API routes (`GET /api/v1/servers/{id}/versioning/tests`, `POST /api/v1/servers/{id}/versioning/tests`)
- `backend/app/modules/versioning/application/commands/promote_commit.py` (gates commit promotion on PASSED test outcome)
- `backend/app/modules/versioning/infrastructure/admission.py` (concurrency/RAM/core resource earmarks)
- `backend/app/modules/server/infrastructure/metrics_collector.py:57` (running container ID lookups)
- `backend/app/api/v1/endpoints/ws/handlers.py:229` (RBAC resolution for `exec_input` and `exec_resize`)
- `frontend/src/server_manager/pages/ServerVersioningPage.tsx` (frontend test history rendering)

A "Replace" approach touches all of the above systems and breaks established contracts; an "Attach" approach touches none of them.

## Options

1. **Option (a) — Replace `ServerTestRunModel` with `Runtime`**: XL effort. Breaks existing API contracts, requires frontend changes across test history tables, rewrites promotion gating in `promote_commit.py`, alters admission scheduler queries, and conflates ephemeral process/container execution lifecycle with permanent test verification results.
2. **Option (b) — Attach `Runtime` as a 1:1 execution handle**: M effort. Introduce a new `server_runtimes` table and a `runtime_id` FK on `server_test_runs`. Zero breakage to existing API contracts, zero changes to frontend, zero disruption to promotion gating.

## Decision

**Option (b) — Attach `Runtime` as a 1:1 execution handle.**

`Runtime` will be wired to physical container/process state via a dedicated `server_runtimes` persistence table, referenced by an additive `runtime_id` foreign key on `server_test_runs`.

## Why

Option (b) keeps Stage F bounded to test-platform deliverables without forcing an expansive rewrite of Stage D's admission scheduler or Phase 4's promotion gating:
- `Runtime` models physical container/process lifecycle (`container_id`, `pid`, `status`, `port`, `exit_code`).
- `ServerTestRun` remains the authoritative test verification record (`outcome`, `assertions`, `evidence`).
- Clean separation of concerns between process management and test assertion results.

## Impact

- **Product/user:** Zero user-facing breakage or workflow disruption; provides robust process/container lifecycle tracking for test runs.
- **Stability:** High; existing test execution paths and promotion gating remain completely stable.
- **Performance:** Negligible; 1:1 relationship with indexed FK.
- **Architecture:** Cleanly decouples physical execution state (`Runtime`) from verification semantics (`ServerTestRun`).
- **Operations:** Additive schema migration to create `server_runtimes` and add `runtime_id` nullable FK to `server_test_runs`.

## Effort

M (Medium).

## Reversibility

High — additive foreign key, non-breaking for all existing readers and writers of `server_test_runs`.

## Roadmap impact

None beyond Stage F's own scope; unblocks Stage F's Runtime wiring work without expanding scope.

## Verification

To be confirmed at Stage F Build/Verify:
- New migration applies cleanly forward and backward.
- Existing versioning, admission, and observability test suites show zero regressions.

## Outcome

Pending Stage F Build.
