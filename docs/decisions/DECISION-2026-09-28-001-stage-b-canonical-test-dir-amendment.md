# DECISION-2026-09-28-001 — Stage B Canonical Test Directory Grounding Amendment

Status: Accepted
Lane: Release Improvement / Stabilization (Lane B)
Decision level: D1 (Standard Decision)
Roadmap drift: Controlled Drift (Zero scope creep; aligns design with existing DB/domain ground truth)
Decided by: Architecture & Versioning Engineering Review
Approved by: Mohamed (Lead Reviewer / System Owner)
Date: 2026-09-28
Reference: DECISION-2026-09-27-001, PHASE-5.5-STAGE-B-TEST-RUN-ENGINE-DESIGN.md, GOVERNANCE.md §4

---

## Context

During the independent design review of Phase 5.5 Stage B (Test Run Engine), a blocker was identified in the canonical path derivation specification:
- The approved Stage B Design Spec (`docs/decisions/PHASE-5.5-STAGE-B-TEST-RUN-ENGINE-DESIGN.md` §§4.4.1, 4.4.2) defined `resolve_test_dir(server_id, test_id, servers_root=None)` by reconstructing test directories under `Path(AppSettings().servers_data_dir) / server_id / ".onx" / "tests" / test_id`.
- Furthermore, `TestCleanupPlan.create()` did not accept a `test_dir` parameter, instead silently reconstructing an artificial path using `resolve_test_dir(server_id, test_id)`.

This design contradicted existing database and domain ground truth: in ONX Manager, a server's deployment directory is authoritative in `ServerDeployment.server_dir` (`ServerModel.root_path` + `ServerModel.working_directory`), which can be an arbitrary custom filesystem location, Docker volume mount, or temporary test directory (e.g., `tempfile.TemporaryDirectory()`).

## Evidence

1. **Concrete Failure (FACT):** When running `test_promote_and_rollback.py::test_promote_commit_with_keep_world_changes`, the test failed (`AssertionError: 'old-level-data' == 'new-level-data-from-test'`). The test created test files under `srv_dir / ".onx" / "tests" / "t-world"`, but `PromoteCommitHandler` reconstructed `test_dir` from `AppSettings().servers_data_dir / "srv-1" / ".onx" / "tests" / "t-world"`, completely missing the real test artifacts.
2. **Execution Disconnect (FACT):** In `DockerTestExecutionRunner` (`backend/app/modules/versioning/infrastructure/test_runner.py:407`), test execution materializes under `Path(spec.server_dir) / ".onx" / "tests" / spec.test_id`, where `spec.server_dir` is passed from `server.deployment.server_dir`. However, `discard_test.py`, `promote_commit.py`, `admission.py`, and `prune_test_artifacts.py` attempted to reconstruct `test_dir` using global server root settings.
3. **Governance Mandate (FACT):** Under `docs/governance/GOVERNANCE.md` §4, a decision that affects multiple modules (`server` domain/persistence and `versioning` domain/application/infrastructure layers) and alters a cross-cutting path contract classifies as **D1 — Standard**.

## Decision

Amend the Stage B Test Run Engine Design as follows:

1. **Ground Canonical Test Resolution in Authoritative Server Deployment:**
   - Define `resolve_test_dir(server_dir: Path | str, test_id: str) -> Path` in `backend/app/modules/versioning/domain/paths.py`.
   - The base directory is strictly derived as `(Path(server_dir).resolve() / ".onx" / "tests").resolve()`.
   - Retain separator-safe and prefix-safe traversal escape prevention using `Path.is_relative_to(base_dir)`.
   - Strictly reject path separators (`/`, `\\`), directory climbing (`..`), and non-token characters in `test_id`.

2. **Authoritative Containment Validation in `TestCleanupPlan.create()` (No Fail-Open Inference):**
   - Eliminate all fragile substring checking (no `".onx" in norm and "tests" in norm`).
   - Require an explicit authoritative `server_dir: Path | str` parameter with NO default (`server_dir=None` prohibited) and eliminate all fail-open path inference logic.
   - Require authoritative containment validation: parent hierarchy must be strictly `.onx/tests/<test_id>` with leaf directory matching `test_id`.
   - Reject the tests root itself (`<server>/.onx/tests` or `<server>/.onx/tests/`).
   - Reject cross-server paths (where `test_dir` does not match `resolve_test_dir(server_dir, test_id)`).
   - Reject `..` and separator escapes.
   - Keep invariants tied strictly to the expected `(server_id, test_id)` identity.
   - Preserve `resolve_test_dir(server_dir, test_id)` as the single canonical safe constructor.

3. **Missing Server / NULL `root_path` Safety Behavior:**
   - During background maintenance (`reap_stale_reservations` in `admission.py` and `prune_test_artifacts.py`), if a server row is missing in the database or if `root_path` is NULL/empty:
     * Skip cleanup safely with an explicit warning log.
     * DO NOT guess, reconstruct, or default to `<servers_data_dir>/<server_id>`.

4. **Align All 5 Lifecycle Sites & TestHandle Shape:**
   - Add `server_dir: str` to `TestHandle` (matching `test_runner.py` runtime shape) and populate from `spec.server_dir` in `DockerTestExecutionRunner.run_test()`.
   - `cleanup_test`: Uses `handle.test_dir` and passes `server_dir=handle.server_dir` (or explicit caller `server_dir`) to `TestCleanupPlan.create()`.
   - `discard_test`: Fetches `server.deployment.server_dir`, resolves `test_dir = resolve_test_dir(server_dir, command.test_id)`, creates `handle = TestHandle(..., test_dir=test_dir, server_dir=server_dir)`, and calls `cleanup_test(handle, passed=False, cancelled=True, server_dir=server_dir)`.
   - `promote_commit`: Fetches `server.deployment.server_dir`, resolves `test_dir = resolve_test_dir(server_dir, command.test_id)`, creates `handle = TestHandle(..., test_dir=test_dir, server_dir=server_dir)`, and calls `cleanup_test(handle, passed=True, server_dir=server_dir)`.
   - `reap` (`admission.py`): Queries server deployment paths (`root_path`, `working_directory`), resolves `test_dir = resolve_test_dir(server_dir, test_id)`, and passes `server_dir=server_dir` explicitly to `TestCleanupPlan.create()` (skipping safely if missing/NULL).
   - `prune` (`prune_test_artifacts.py`): Queries server deployment paths, resolves `test_dir = resolve_test_dir(server_dir, run.id)`, and passes `server_dir=server_dir` explicitly to `TestCleanupPlan.create()` (skipping safely if missing/NULL).

## Impact

- **Architecture:** Unifies test directory resolution with domain entity truth (`ServerDeployment`). Eliminates out-of-band path reconstruction.
- **Reliability:** Fixes silent path mismatches during promotion, discard, and pruning. Guarantees that execution, promotion, and teardown operate on identical physical paths.
- **Scope & Contract:** Zero change to external REST contracts, permission contracts, or database schemas. Zero Stage C–G scope expansion.

## Reversibility

High — pure domain and application path resolution alignment.

## Outcome & Approvals

- **Status:** Accepted
- **Decided by:** Architecture & Versioning Engineering Review
- **Approved by:** Mohamed (Lead Reviewer / System Owner)
- **Approval Date:** 2026-09-28 (Explicit Owner Approval granted)
- **Governance Classification:** D1 — Standard Decision (Lane B)
- **Execution:** Approved for implementation.
