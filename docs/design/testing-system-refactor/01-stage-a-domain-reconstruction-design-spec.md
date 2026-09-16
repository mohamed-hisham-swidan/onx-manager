# Design Spec — Stage A: Domain Reconstruction (Enterprise Branch Runtime)

**Revision:** v2 — RECON-verified 2026-09-16 (Nemotron/Muse Spark, full report on file). Current Behavior and Affected Components corrected against live code. One open design question flagged for Mohamed below (Invariant 2 vs. an existing shipped lock).

**Scope:** Domain-layer entities, state machines, invariants, and ADRs only. No version-control engine changes beyond what's already shipped, no filesystem materialization, no containerization, no UI. This is the foundation Stages B-G build on.

---

## Goal

Establish authoritative domain entities and invariants for the "versioned desired-state → isolated runtime" model, **extending** ONX Manager's already-shipped branch/commit/test-environment implementation rather than replacing an "ad-hoc" one — RECON found the existing code is more mature than the source report assumed.

## Current Behavior (RECON-verified 2026-09-16)

- **Branch/commit model — FACT.** `ServerBranch` is already a mutable named ref (`head_commit_id`, `backend/app/modules/versioning/domain/entities.py:23`, unique per server). `ServerCommit.parent_commit_id: str | None` (`entities.py:43`) permits exactly **one** parent — no multi-parent/merge representation exists anywhere in domain, model, or repository layers. `CreateBranchCommand` already accepts an arbitrary `head_commit_id` (branch-from-any-commit is possible at the command layer today), but `CreateCommitHandler` always parents the new commit to `branch.head_commit_id` and every commit carries a `branch_id` — so history is branch-scoped and linear, not a shared DAG. `ServerBranch` has no status field — the proposed created → active → archived state machine does not exist yet.
- **Test-environment pipeline — CORRECTED.** The spec previously assumed "files-based mode now, container-based mode added later." This is false: `DockerTestExecutionRunner` (`backend/app/modules/versioning/infrastructure/test_runner.py:118-303`) is the **only** test-execution implementation in the repo. Files-based mode was never built — superseded by `DECISION-2026-09-10-001`, which built Phase 5 (Containers) before Phase 4. One `run_test()` call already performs revision resolution → materialization → container launch → async verification as a single pipeline, with no Revision/Materialization/Runtime/Run domain separation. **A hidden one-active-run-per-server lock already exists** (`_server_locks` + `ConflictError`, `test_runner.py:128-140`) — this directly conflicts with this spec's proposed Invariant 2 (see "Open Design Question" below). `ServerTestRun` already binds `commit_id` + terminal `PASSED/FAILED/CANCELLED` status + evidence (log output, failure reason), and promotion is strictly gated on `PASSED` (`promote_commit.py:117-171`) — substantial overlap with the proposed Run/TestRun split.
- **Phase 5 DockerProvider — FACT, shipped.** Full container lifecycle (create/start/stop/status/console/exec/destroy), multiple simultaneous runtimes (one container per server + isolated per-test containers), and per-container resource policy (memory min/max, CPU count/pinning) are already live (`backend/app/modules/server/infrastructure/providers/docker.py:202-990`). What's genuinely missing is a global scheduler / resource pool / admission policy — not container mechanics.
- **ServerProvider / `capabilities()` — FACT, confirmed exactly as assumed.** `base.py:59-156`; `capabilities()` is a concrete default method (`:91-112`) with a documented extension contract. A delegating-wrapper precedent already exists (`CircuitBreakerProviderWrapper`). This is the one prior assumption in this spec that needed no correction.

## Proposed Change

Define the following as explicit domain entities/aggregates, **extending** `backend/app/modules/versioning/domain/` (the project's real hexagonal-DDD module, not a new tree):

| Entity | Definition | Relationship to shipped code |
|---|---|---|
| `Project` | Logical Minecraft environment (root aggregate). | New. |
| `Repository` | Owns commit history for a Project. | Formalizes the existing `ServerBranch`/`ServerCommit` relationship — no new persistence engine. |
| `Commit` | Immutable desired-state snapshot, referencing a Tree and parent commit(s). | **Extends** `ServerCommit` — see Open Design Question below on single-parent → multi-parent. |
| `Branch` | Mutable reference to a Commit. | **Extends** `ServerBranch` — add the created → active → archived state machine (does not exist today). |
| `Revision` | A resolved, specific commit. | New concept; formalizes what commit resolution already does implicitly in `run_isolated_test.py`. |
| `Materialization` | Concrete filesystem working tree from a Revision, with path classification. | Formalizes the materialization step already inside `test_runner.py:154-230` — decompose, don't rebuild. |
| `Runtime` | Execution instance bound to exactly one immutable commit ID; wraps `ServerProvider`. | **No contract change needed** — RECON confirmed clean fit. |
| `PersistentDataset` | Runtime-generated mutable state excluded from versioning. | New; formalizes the COW world-clone step already in the test pipeline. |
| `Run` / `TestRun` | Execution of a Revision; TestRun adds assertions/evidence. | **Substantial overlap** with `ServerTestRun`/`TestSpec`/`TestHandle`/`TestServerDeployment` (`domain/deployment.py:8-31`) — this stage should extend those, not introduce parallel entities. |

**ADRs required (revised scope):**
1. Why domain-model-first for the *new* entities (Revision/Materialization/PersistentDataset) rather than a parallel persistence engine — the Commit/Branch/DAG question is covered by ADR #2 instead.
2. **Corrected scope:** migrating the existing single-parent, branch-scoped commit chain to a shared DAG (multi-parent support) + adding the Branch lifecycle state machine — framed as **extending a real, shipped model**, not replacing an ad-hoc one.
3. Relationship between the new `Runtime` entity and `ServerProvider` — confirmed extension, no contract change (RECON verified).
4. `PersistentDataset` boundary rules, informed by the existing COW world-clone/reflink behavior already in `test_runner.py`.

**Invariants:**
1. A `Runtime` always resolves to exactly one immutable `Commit` ID. *(No conflict with shipped code.)*
2. **OPEN — see below.** A `Branch` can have zero, one, or many concurrent `Runtime` instances — but a hidden one-active-run-per-server lock already exists in the shipped test pipeline (`test_runner.py:128-140`). This spec cannot silently assume the invariant holds; it must be explicitly resolved.
3. Writes to a `PersistentDataset` never silently mutate a `Commit` or `Branch`. *(No conflict — promotion is already explicit and gated in `promote_commit.py`.)*

### ⚠ Open Design Question — Invariant 2 vs. the shipped per-server lock

RECON confirms `test_runner.py` already enforces one active test run per server via `_server_locks` + `ConflictError`. This spec's Invariant 2 assumes no such lock exists at the domain layer. Three ways forward, not yet decided:
- **(a)** Lift the lock as part of this rebuild, so multiple concurrent Runtimes per Branch become genuinely possible (matches the source report's vision, but changes existing behavior and needs its own concurrency/resource-contention analysis).
- **(b)** Keep the lock, and rewrite Invariant 2 to explicitly scope "no *domain-layer* lock" while acknowledging a documented, intentional per-server execution limit stays in place for now.
- **(c)** Defer the decision — build Stage A's entities without touching the lock, revisit when Stage F (Test Platform, where the lock actually lives) gets its own Design Spec.

## Affected Components (RECON-corrected — real paths, not placeholders)

- **Extend, don't create a parallel tree:** `backend/app/modules/versioning/domain/` (`entities.py`, `value_objects.py`, `deployment.py`, `repository.py`, `events.py`) — add Revision/Materialization/Runtime/PersistentDataset here. RECON explicitly flagged that the spec's original placeholder paths (`backend/app/domain/versioning/` etc.) would have caused a builder to create a parallel `backend/app/domain/` tree duplicating the project's real `modules/<module>/domain/` convention — exactly the duplication failure mode this spec is meant to avoid.
- `backend/app/modules/versioning/application/commands/` — `create_branch.py`, `create_commit.py`, `run_isolated_test.py`, `promote_commit.py`, `discard_test.py` (extend/reconcile existing commands).
- `backend/app/modules/versioning/infrastructure/` — `models.py`, `repository.py`, `test_runner.py` (contains the pipeline to decompose into the new entities).
- `backend/app/modules/server/infrastructure/providers/` — `base.py` (`ServerProvider`), unchanged contract, extension point only.
- ADRs go in the existing `docs/decisions/` (14 records already there, e.g. `DECISION-2026-09-10-001`) — not a new folder.
- Invariant/contract tests go in `backend/tests/domain/` and `backend/tests/application/` (naming convention `test_*_invariants.py`) — the repo has no `tests/architecture/` directory and none should be invented.

## Interfaces & Contracts

- No REST/API route changes in this stage.
- No `contracts/permissions.yaml` changes.
- `ServerProvider`'s public capability vocabulary (`"process"`/`"console"`/`"exec"`) must be preserved or extended, never renamed — it's a live branching contract for existing callers.

## Failure Cases & Edge Cases

- Existing `ServerCommit`/`ServerBranch` rows must migrate cleanly into the DAG-capable model (single-parent chains are a valid degenerate case of a DAG, so this should be additive, not a breaking migration — confirm during Build).
- A `Runtime` outliving its `Materialization` — must be an explicit illegal state, not a crash.
- Branch pointer moves while Runtimes are active — already-running Runtimes keep their originally-resolved commit ID (Invariant 1); nothing changes retroactively underneath them.
- Whatever Invariant 2 resolution is chosen above must have an explicit test proving the *chosen* behavior (lock present or absent), not just the domain model's happy path.

## Tests & Verification

- A contract test per invariant, each proving the domain layer **rejects** the violation.
- **Pre-change baseline (RECON-verified 2026-09-16, freshly executed, not reused):** backend `2733 passed / 6 skipped / 0 failed` (2739 collected); frontend `79 files / 711 passed / 0 failed`. Matches `STATE.json`'s recorded verified metrics. Any regression against this baseline blocks close.
- No live server/container tests required for the *new* domain entities (Revision/Materialization/PersistentDataset) — but decomposing `test_runner.py` touches shipped, tested behavior, so the existing `test_isolated_test_runner.py` and related suites must stay green throughout, not just at the end.
- Note: the project's 5-minute full-suite timeout policy (`.ai/RULES/testing-and-verification.md`) was insufficient for this session's backend run (8m12s actual) — budget accordingly for Build/Review verification runs, or flag this to Mohamed as a policy calibration item.

## Out of Scope (this stage)

- A real multi-parent DAG *persistence* implementation beyond the domain model itself (may fold into this stage or Stage B — TBD once ADR #2 is written).
- Filesystem materialization implementation beyond decomposing what already exists in `test_runner.py` (Stage C).
- Any change to `DockerProvider` container mechanics — confirmed shipped and out of scope.
- Any UI/frontend work.
- RBAC/ABAC, multi-host scheduler, resource pools, audit logging (Stage G).
- Adopting OCI/containerd/cgroup v2/OpenTelemetry as concrete dependencies — moot for Stage D beyond what Phase 5 already shipped; revisit only if a real scheduler/admission-policy need emerges.

## RECON Status

**Complete (2026-09-16).** Items 1, 2, and 5 of the original "Recon Required" checklist required corrections (now applied above). Item 4 (ServerProvider fit) required no correction. Item 3 (DockerProvider overlap) narrowed Stage D's real remaining scope. One design decision remains open (Invariant 2, above) — this blocks Design Review sign-off until Mohamed decides (a)/(b)/(c). The August "Executor Runtime" precedent cited as this spec's motivating pattern could not be independently confirmed from repo evidence (no artifact found) — it remains valid as external/chat history, just not verifiable from the codebase itself.
