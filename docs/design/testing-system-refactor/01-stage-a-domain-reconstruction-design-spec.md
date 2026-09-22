# Design Spec — Stage A: Domain Reconstruction (Enterprise Branch Runtime)

**Status:** BUILT & VERIFIED (Commit `e72a219`, 2026-09-17)
**Revision:** v3 — cleaned for agent clarity (2026-09-17)
- Invariant 2 closed (option c – defer)
- Added Old→New mapping table
- Added concrete Acceptance Criteria
- Language tightened to "formalize & extend"
- Verified: 20/20 new domain tests passing, 2,753/6/0 backend, 6/6 CI gates PASS, ADRs 0013–0016 written.

**Scope:** Domain-layer entities, state machines, invariants, and ADRs only. No version-control engine changes beyond what's already shipped, no filesystem materialization, no containerization, no UI. This is the foundation Stages B-G build on.

---

## Goal

Establish authoritative domain entities and invariants for the "versioned desired-state → isolated runtime" model, **formalizing and extending** ONX Manager's already-shipped branch/commit/test-environment implementation — RECON found the existing code is more mature than the source report assumed.

## Current Behavior (RECON-verified 2026-09-16)

- **Branch/commit model — FACT.** `ServerBranch` is already a mutable named ref (`head_commit_id`, `backend/app/modules/versioning/domain/entities.py:23`, unique per server). `ServerCommit.parent_commit_id: str | None` (`entities.py:43`) permits exactly **one** parent — no multi-parent/merge representation exists anywhere in domain, model, or repository layers. `CreateBranchCommand` already accepts an arbitrary `head_commit_id` (branch-from-any-commit is possible at the command layer today), but `CreateCommitHandler` always parents the new commit to `branch.head_commit_id` and every commit carries a `branch_id` — so history is branch-scoped and linear, not a shared DAG. `ServerBranch` has no status field — the proposed created → active → archived state machine does not exist yet.
- **Test-environment pipeline — CORRECTED.** The spec previously assumed "files-based mode now, container-based mode added later." This is false: `DockerTestExecutionRunner` (`backend/app/modules/versioning/infrastructure/test_runner.py:118-303`) is the **only** test-execution implementation in the repo. Files-based mode was never built — superseded by `DECISION-2026-09-10-001`, which built Phase 5 (Containers) before Phase 4. One `run_test()` call already performs revision resolution → materialization → container launch → async verification as a single pipeline, with no Revision/Materialization/Runtime/Run domain separation. **A one-active-run-per-server lock already exists** (`_server_locks` + `ConflictError`, `test_runner.py:128-140`) and **remains in force for this stage** (see Invariant 2). `ServerTestRun` already binds `commit_id` + terminal `PASSED/FAILED/CANCELLED` status + evidence (log output, failure reason), and promotion is strictly gated on `PASSED` (`promote_commit.py:117-171`) — substantial overlap with the proposed Run/TestRun split.
- **Phase 5 DockerProvider — FACT, shipped.** Full container lifecycle (create/start/stop/status/console/exec/destroy), multiple simultaneous runtimes (one container per server + isolated per-test containers), and per-container resource policy (memory min/max, CPU count/pinning) are already live (`backend/app/modules/server/infrastructure/providers/docker.py:202-990`). What's genuinely missing is a global scheduler / resource pool / admission policy — not container mechanics.
- **ServerProvider / `capabilities()` — FACT, confirmed exactly as assumed.** `base.py:59-156`; `capabilities()` is a concrete default method (`:91-112`) with a documented extension contract. A delegating-wrapper precedent already exists (`CircuitBreakerProviderWrapper`). This is the one prior assumption in this spec that needed no correction.

## Proposed Change

Define the following as explicit domain entities/aggregates, **extending** `backend/app/modules/versioning/domain/` (the project's real hexagonal-DDD module, not a new tree):

### Old → New mapping

| Existing concept / entity | New / Extended entity | Action |
|---|---|---|
| `ServerCommit` | `Commit` | Extend |
| `ServerBranch` | `Branch` | Extend + add state machine |
| (implicit revision resolution in `run_isolated_test.py`) | `Revision` | New formal entity |
| materialization steps in `test_runner.py:154-230` | `Materialization` | Formalize / decompose |
| `ServerProvider`-backed execution | `Runtime` | Wrap / formalize |
| COW world clone | `PersistentDataset` | Formalize |
| `ServerTestRun` / `TestSpec` / `TestHandle` / `TestServerDeployment` | `Run` / `TestRun` | Extend (do not duplicate) |

### Entity definitions

| Entity | Definition | Relationship to shipped code |
|---|---|---|
| `Project` | Logical Minecraft environment (root aggregate). **Stage A scope: maps 1:1 to the existing `Server` aggregate (`Project.id` = `server_id`).** Richer multi-server project grouping is explicitly out of scope. | New thin wrapper; no new hierarchy. |
| `Repository` | Owns commit history for a Project. | Formalizes the existing `ServerBranch`/`ServerCommit` relationship — no new persistence engine. |
| `Tree` | The set of tracked file blobs for a Commit. | Formalizes the existing `CommitManifest` (configs / mods / env_vars / java_args). No new capture format in Stage A. |
| `Commit` | Immutable desired-state snapshot, referencing a `Tree` and parent commit(s). | **Extends** `ServerCommit`. Single-parent only in Stage A (see Out of Scope). |
| `Branch` | Mutable reference to a `Commit`. | **Extends** `ServerBranch` — add the created → active → archived state machine (does not exist today). |
| `Revision` | A resolved, specific commit. | New concept; formalizes what commit resolution already does implicitly in `run_isolated_test.py`. |
| `Materialization` | Concrete filesystem working tree from a `Revision`, with path classification. | Formalizes the materialization step already inside `test_runner.py:154-230` — decompose, do not reimplement. |
| `Runtime` | Execution instance bound to exactly one immutable commit ID; wraps `ServerProvider`. | **No contract change needed** — RECON confirmed clean fit. |
| `PersistentDataset` | Runtime-generated mutable state excluded from versioning. | New; formalizes the COW world-clone step already in the test pipeline. |
| `Run` / `TestRun` | Execution of a Revision; TestRun adds assertions/evidence. | **Substantial overlap** with `ServerTestRun`/`TestSpec`/`TestHandle`/`TestServerDeployment` (`domain/deployment.py:8-31`) — this stage extends those, not parallel entities. |

### State machines (with triggers)

- `Branch`: `created` → `active` → `archived`. `created` on `CreateBranch`; → `active` on the first commit advancing the head (or explicit activate); → `archived` only via explicit operator action. `archived` is terminal for commits (see Acceptance Criteria). No automatic transitions.
- `Materialization`: `pending` → `ready` → `stale` → `removed`. → `ready` after all staged files verify present; → `stale` when its source Revision is superseded or on explicit invalidate; → `removed` on cleanup. A `Runtime` referencing a `removed` Materialization is an explicit illegal state.

**ADRs required:**
1. Why domain-model-first for the *new* entities (Revision/Materialization/PersistentDataset) rather than a parallel persistence engine — the Commit/Branch/DAG question is covered by ADR #2 instead.
2. Migrating the existing single-parent, branch-scoped commit chain to a shared DAG (multi-parent support) + adding the Branch lifecycle state machine — framed as **extending the real, shipped model**. **ADR #2 must be written and approved before any multi-parent work begins.**
3. Relationship between the new `Runtime` entity and `ServerProvider` — confirmed extension, no contract change (RECON verified).
4. `PersistentDataset` boundary rules, informed by the existing COW world-clone/reflink behavior already in `test_runner.py`.

**Invariants:**
1. A `Runtime` always resolves to exactly one immutable `Commit` ID — never a mutable `Branch` reference directly. *(No conflict with shipped code.)*
2. **CLOSED (option c — defer).** Stage A makes **no** domain-layer claim about concurrent Runtimes. The existing per-server execution lock in `DockerTestExecutionRunner` (`_server_locks` + `ConflictError`, `test_runner.py:128-140`) **remains in force** and is untouched by this stage. Concurrency policy is deferred to Stage D (scheduler) / Stage F (test platform), where the lock actually lives.
3. Writes to a `PersistentDataset` never silently mutate a `Commit` or `Branch` — importing runtime-generated changes back into version control is always an explicit, reviewable operation. *(No conflict — promotion is already explicit and gated in `promote_commit.py`.)*

## Acceptance Criteria

Every criterion below must hold in the built domain layer, each backed by a rejecting test (see Tests & Verification).

- **Branch.** Required fields: `id`, `server_id`, `name`, `head_commit_id` (nullable), `status` (`created`/`active`/`archived`). Name unique per server (preserve `uq_server_branch_name`). Transitions: `created`→`active` on first head-advancing commit; `active`→`archived` via explicit archive only. **Reject:** `CreateCommit` targeting an `archived` branch; duplicate branch name per server; null `server_id`.
- **Commit.** Required fields: `id`, `server_id`, `message`, `manifest`/`Tree`, `branch_id`, `parent_commit_id` (nullable for genesis), `author_id` (nullable). Commits immutable after save (no update path — repository exposes save-new only). **Reject:** dangling `parent_commit_id` (parent must exist); cross-server parent (`parent.server_id != commit.server_id`); any mutation of a saved commit.
- **Revision.** Immutable value object binding `commit_id` + resolution source (branch name + head at resolve time, or explicit commit ID). Branch-name resolution must verify the branch belongs to the same server. **Reject:** resolving a branch of another server; resolving a nonexistent commit; retroactive change of an already-resolved Revision when the branch pointer moves.
- **Materialization.** Required fields: `id`, `revision`/`commit_id`, root path, path-classification map (tracked / persistent / generated / ignored / ephemeral), `status`. Root path must satisfy the same isolation rule as `TestServerDeployment` (under an isolated `.onx/tests`-style root — reject traversal escapes). Transitions per the state machine above. **Reject:** use of a `removed` Materialization; staging a path outside the allowed root.
- **Runtime.** Required fields: `id`, immutable `commit_id`, `materialization_id`, `provider_type`. Binds a commit ID, never a branch reference; keeps its originally-resolved commit for its lifetime. Lifecycle state is read from the provider (no parallel lifecycle engine). **Reject:** constructing a Runtime from a branch name; changing `commit_id` after creation; referencing a `removed` Materialization.
- **PersistentDataset.** Required fields: `id`, owning runtime/commit reference, dataset root, classification. Dataset paths are excluded from `Tree` diffs by construction. **Reject:** any write path resolving into the tracked set; any silent mutation of a `Commit` or `Branch` through dataset writes.
- **Run / TestRun.** Extends `ServerTestRun`: required `commit_id` binding, terminal states `PASSED`/`FAILED`/`CANCELLED` preserved. `TestRun` adds assertions + evidence fields (`log_output`, `failure_reason` preserved). Existing promotion gate preserved: only `PASSED` promotable. **Reject:** promotion of a non-`PASSED` run (already enforced — keep green); terminal-state regression (e.g. `PASSED`→`RUNNING`).

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
- The per-server lock stays in force (Invariant 2, closed) — its presence must have an explicit test proving the lock behavior, alongside the per-invariant rejecting tests.

## Tests & Verification

- A contract test per invariant, each proving the domain layer **rejects** the violation.
- A test per Acceptance Criteria bullet above (transitions, required fields, rejected illegal states).
- **Pre-change baseline (RECON-verified 2026-09-16, freshly executed, not reused):** backend `2733 passed / 6 skipped / 0 failed` (2739 collected); frontend `79 files / 711 passed / 0 failed`. Matches `STATE.json`'s recorded verified metrics. Any regression against this baseline blocks close.
- No live server/container tests required for the *new* domain entities (Revision/Materialization/PersistentDataset) — but decomposing `test_runner.py` touches shipped, tested behavior, so the existing `test_isolated_test_runner.py` and related suites must stay green throughout, not just at the end.
- Note: the project's 5-minute full-suite timeout policy (`.ai/RULES/testing-and-verification.md`) was insufficient for the RECON backend run (8m12s actual) — budget accordingly for Build/Review verification runs, or flag this to Mohamed as a policy calibration item.

## Out of Scope (this stage)

- **No persistence-engine change for multi-parent DAG in Stage A.** The domain model stays single-parent; multi-parent persistence is Stage B territory, gated on ADR #2 being written and approved first.
- Filesystem materialization implementation beyond decomposing what already exists in `test_runner.py` (Stage C).
- Any change to `DockerProvider` container mechanics — confirmed shipped and out of scope.
- Any change to the per-server execution lock (deferred to Stage D/F per closed Invariant 2).
- Any UI/frontend work.
- RBAC/ABAC, multi-host scheduler, resource pools, audit logging (Stage G).
- Adopting OCI/containerd/cgroup v2/OpenTelemetry as concrete dependencies — moot for Stage D beyond what Phase 5 already shipped; revisit only if a real scheduler/admission-policy need emerges.

## RECON Status

**Complete (2026-09-16).** All checklist items verified with file/line evidence; corrections applied in v2. **Design Review returned APPROVED WITH CHANGES (2026-09-16):** Invariant 2 closed via option (c) in v3; reviewer items C1 (`Project`↔`Server` 1:1), C2 (`Tree` formalizes `CommitManifest`), C3 (state-machine triggers + events) resolved in the tables above. The August "Executor Runtime" precedent cited as this spec's motivating pattern could not be independently confirmed from repo evidence (no artifact found) — it remains valid as external/chat history, just not verifiable from the codebase itself.
