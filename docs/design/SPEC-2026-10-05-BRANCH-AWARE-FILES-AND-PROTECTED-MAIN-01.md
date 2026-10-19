# SPEC-2026-10-05-BRANCH-AWARE-FILES-AND-PROTECTED-MAIN-01 (Revision 2)
# Design Spec: Branch-Aware Files Page + Protected Main + Merge-to-Main

- **Status:** Draft / Revision 2 (Addressing Independent Design Review Findings F1–F21)
- **Date:** 2026-10-05
- **Role:** Design Spec Author (Design Only — no implementation code modified, no commits)
- **Governance Classification:** Lane E (Future Product) / Decision Level: D2 (Major)
- **Baseline Evidence:** RECON findings (Muse Spark 1.3) and Review Findings (F1–F21), re-verified against code.
- **Evidence Labeling Discipline:**
  - `[FACT]`: Verified directly against repository code, tests, or database models.
  - `[ASSUMPTION]`: Inferred system behavior or operational expectation.
  - `[UNKNOWN]`: Unverified or unconfirmed detail requiring owner ruling or live measurement.
  - `[CONFLICT]`: Explicit divergence or policy tension identified for owner resolution.
  - `[NEW]`: Explicitly marks any newly introduced class, function, parameter, route, or schema.

---

## 1. Executive Summary & Governance Gate

### 1.1 Executive Summary
This revised specification formalizes three interrelated capabilities for ONX Manager:
1. **Part A — `main` Provisioning & System Protection (W1–W4, W6)**: Establishes eager `main` creation inside the versioning module as `CREATED` with `head_commit_id=None` across all server lifecycle entrypoints (creation, import, reconciliation) plus an idempotent backfill migration (`b1e2100000023`). Introduces a single-use in-process system genesis path, system-protection immutability (`is_system=True`, non-archivable, non-unprotectable), and an internal directory guard (`.onx`, `.onx-manager`, `.mcsmanager`) across all 7 Files API routes.
2. **Part B — Merge-to-Main (W5)**: Provides safe branch advancement into `main` and all protected branches using a **Fast-Forward-Only** rule to an already-tested commit, verified via a pinned `PASSED` test run. Divergent merges into protected branches are rejected, upholding the Stage-B Hard Stop.
3. **Part C — Branch-Aware Files Page & Commit-from-Worktree (W6–W10)**: Extends the Files API via a parameter root-switch (`source=live|worktree&ref=<mat_id>`) enforcing `TRACKED` path classification and `EDITABLE` mode. Provides `CommitFromWorktreeCommand` with optimistic concurrency (`UPDATE ... WHERE head = :expected`), diff-against-parent manifest construction with zero silent drops, and resolves BUG-V04.

### 1.2 Governance Gate & Hard-Stop Evaluation

| Gate Item | Evaluation | Status |
|---|---|---|
| **Governance Classification** | Lane E (Future Product), Decision Level D2 (Major). Touches core branch lifecycle, Files API routing contract, and database schemas. Does not block v0.1.0 launch gates. | **D2 COVERAGE REQUIRED** |
| **API Contract Impact** | Extends all 7 Files API routes with optional query parameters (`source`, `ref`); adds endpoint `POST /api/v1/servers/{server_id}/versioning/materializations/{mat_id}/commit`. Updates `contracts/permissions.yaml`. | **D2 REQUIRED** |
| **DB Schema Impact** | Migration `b1e2100000023` (down_revision `b1e2100000022`) adds `is_system: bool` and check constraints to `server_branches`. Dual-dialect support (SQLite + PostgreSQL). Bumps `RELEASE_MINIMUM_DB_REVISION`. | **D2 REQUIRED** |
| **Stage-B Hard-Stop Provenance** | The Stage-B Design Spec (`docs/design/testing-system-refactor/03-stage-b-real-version-control-design-spec.md:30`) states: *"NO auto-resolution — Hard Stop"*. Decision `docs/decisions/DECISION-2026-09-17-001:22` authorizes merge commits with caller-supplied manifests on conflict. Fast-forward pointer advancement introduces NO auto-resolution, but because it introduces pointer advancement into protected branches, it requires explicit D2 coverage. | **GOVERNED UNDER D2** |

---

## 2. Review Findings Resolution Table (F1–F21)

| Finding | Severity | Description | Resolution in v2 |
|---|---|---|---|
| **F1** | BLOCKER | Bootstrap deadlock: headless eager main + closed direct commits = no genesis path | **Part A §3.2 (W2)**: System genesis rule permits exactly one parent-less seeding commit on `main` when `head_commit_id IS NULL`, via internal system path (`allow_system_exemption=True`), audit-logged. |
| **F2** | BLOCKER | `is_system_reconciliation` is an unguarded client-settable discriminant | **Part A §3.4 (W4)**: Removed from all request schemas. Replaced by internal-only parameter `allow_system_exemption: bool = False` on `CreateCommitCommand` [NEW param]. Router schemas (`CreateCommitRequest`, `AutoCommitLiveChangesRequest`) strictly omit it. |
| **F3** | BLOCKER | Merge API schema inconsistent and unimplementable | **Part B §3.1–3.2, §5 (W5)**: Normalized to `MergeCommitsRequest` using exact backend fields: `target_branch_name`, `source_commit_id`, and `source_branch_name`. Added `[NEW]` `BranchHeadAdvancedEvent` in `events.py`. |
| **F4** | BLOCKER | Headless-target and already-ancestor cases crash or misbehave | **Part B §3.2 (W5)**: Explicit logic: `target_head IS NULL` -> adopt source head; `source_commit_id` is ancestor of `target_head` -> no-op success returning current head. |
| **F5** | BLOCKER | Commit-from-worktree silently drops mods and uncovered configs | **Part C §3.2 (W8)**: Compiles manifest as a diff against parent manifest with preserve-or-fail-loudly semantics. Parent configs preserved unless deleted/modified; new configs >10 MB fail loudly; jars carried over by reference. |
| **F6** | BLOCKER | Root-switch bypasses ADR-0016 `TRACKED` classification | **Part C §3.1 (W7)**: Worktree mutations in `_resolve_server_file_path` enforce `TRACKED` classification (same as `write_materialized_file.py:97-115`), reject writes to `PERSISTENT`/`GENERATED`/`IGNORED`, update `path_classification`, and block binary/jar uploads. |
| **F7** | MAJOR | Test gate attests wrong commit; referenced infra doesn't exist | **Part B §3.3 (W5)**: Fast-forward only for protected branches ensures the adopted commit is the exact commit tested. Uses existing `versioning_repo.list_test_runs` with newer-FAILED invalidation (mirroring `promote_commit.py:117-145`). |
| **F8** | MAJOR | Dead `find_lca`, missing no-op, unimplementable source branch check | **Part B §3.1–3.2 (W5)**: Dropped `find_lca` (only `is_ancestor` needed for FF). Added no-op case. Added `source_branch_name: str \| None` to request schema with explicit validation. |
| **F9** | MAJOR | Silent protected-target and world-snapshot gaps | **Part B §3.3–3.4 (W5)**: Fast-forward policy uniformly applied to all protected target branches. FF adopts source commit's `world_snapshot_id`. Noted that live worlds are never deployed on merge (governed by promote's `keep_world_changes`). |
| **F10** | MAJOR | Migration needs rework (batch mode, dialect, idempotency) | **Part A §3.1, §5 (W3)**: Migration `b1e2100000023` uses `op.batch_alter_table`, dual-dialect check constraints, bumps `RELEASE_MINIMUM_DB_REVISION`, and uses idempotent `INSERT ... SELECT WHERE EXISTS ... AND NOT EXISTS`. |
| **F11** | MAJOR | D7 guard overbroad, inconsistent, reads-block undecided | **Part A §3.5 (W6)**: Checks first component of resolved relative path (`.onx`, `.onx-manager`, `.mcsmanager`), case-insensitive. Mutations return 403; reads stay allowed; dirs omitted from root listing. `.env` check applied across all 7 verbs. |
| **F12** | MAJOR | `ACTIVE` + `head=None` redefines status semantics | **Part A §3.1 (W1)**: Eager `main` created as `status=BranchStatus.CREATED` with `head_commit_id=None`, matching `create_branch.py:97-103`. Transitions to `ACTIVE` upon genesis commit. |
| **F13** | MAJOR | Layering violation and duplicated relative_to jail | **Part A §3.1, Part C §3.1 (W1, W6)**: Server lifecycle invokes versioning via `CommandBus` (`CreateBranchCommand`) or domain events. All file path resolution, safety guards, and worktree jails are consolidated in `_resolve_server_file_path`. |
| **F14** | MAJOR | Commit-target resolution hand-waving; STALE-vs-advance wrong | **Part C §3.2 (W8)**: Restricts commit-from-worktree strictly to `branch:`-based materializations. Materialization advances baseline (`commit_id = new_commit.id`) and stays `READY` (not `STALE`). |
| **F15** | MAJOR | `world_snapshot_id` and content-persistence silence | **Part C §3.2 (W8)**: Reuses parent commit's `world_snapshot_id`. Jars carried over by reference. Configs stored inline in `manifest.configs`. |
| **F16** | MAJOR | Stale-head 409 has no atomicity | **Part C §3.2, §6 (W8)**: Optimistic concurrency update in repository: `UPDATE server_branches SET head_commit_id = :new_head WHERE id = :id AND head_commit_id = :expected_head`. 0 rows affected raises `ConflictError` (HTTP 409). |
| **F17** | MAJOR | Storage/timeout claims unbacked | **Part C §3.2, §6 (W8, W9)**: Adds explicit `shutil.disk_usage` check raising `InsufficientDiskSpaceError` (HTTP 507) if free space < 1 GB. Adds per-server materialization cap (W9, default 5). Plain-copy latency noted as limitation. |
| **F18** | MINOR | "Verified clean / COMPLIANT" overstates Hard-Stop provenance | **Section 1.2**: Explicitly cited `03-stage-b-real-version-control-design-spec.md:30` and stated FF requires D2 coverage. |
| **F19** | MINOR | Work-item labels D1–D7 collide with governance D0–D3 | Entire document uses **W1–W10** numbering. |
| **F20** | MINOR | BUG-V04 fix underspecified | **Part C §3.3 (W10)**: Clear boundary: `fs_atomic.py` owns its staging swap artifacts in `finally:`; `tree_writer.py` owns only its `.staging_<uid>` dir and removes `shutil.rmtree(target_path)` from `except Exception:`. |
| **F21** | MINOR | Request<->Command mapping drift | Explicit field-by-field mapping defined for all endpoints and commands. |

---

# Part A: `main` Provisioning & System Protection (W1–W4, W6)

## 1. Goal
Ensure every server in ONX Manager always has an immutable, system-protected `main` branch that cannot be deleted, archived, or unprotected, even by administrative users. Provide an explicit, audit-logged genesis path for the first commit on `main`, while closing security and privilege-bypass gaps across branch protection and the Files API.

## 2. Current Behavior
- `[FACT]` `main` is created lazily on the first commit in `backend/app/modules/versioning/application/commands/create_commit.py:33, 119-127`.
- `[FACT]` Server creation (`create_server.py`), import (`import_server.py`), and reconciliation (`filesystem_reconciliation.py`) do not create branch records.
- `[FACT]` `backend/data/onx.db` contains 136 branch rows across 122 server IDs, with 0 protected branches.
- `[FACT]` Branch protection can be bypassed: any holder of `server:version:branch:protect` can invoke `DELETE /api/v1/servers/{id}/versioning/branches/{name}/protection` (`routers/versioning.py:173`), unsetting `is_protected`, and then archive `main` via `POST .../archive` (`archive_branch.py:82-86`).
- `[FACT]` `allow_force_bypass` and `require_test_pass` fields on `BranchProtectionPolicy` are defined and stored but never read or enforced anywhere in `backend/app/`.
- `[FACT]` Internal directories (`.onx`, `.onx-manager`, `.mcsmanager`) are exposed through `GET /files` and can be overwritten or deleted via `PUT /content` and `DELETE /files`, allowing users to corrupt versioning trees or re-trigger Bug 3 (server identity loss).
- `[FACT]` Sensitive file guard (`_assert_not_sensitive` in `files.py:20-33`) is `.env`-only and enforced on 5/7 routes, omitting `list_files` and `mkdir`.

## 3. Proposed Change

### 3.1 W1: Eager `main` Creation Across Lifecycle Paths
- **Decoupled Invocation (Layering Invariant)**:
  `server` module MUST NOT directly import `versioning` module application services (`[FACT]` `delete_server.py:165` is the only historical exception; bidirectional coupling is forbidden).
  - Lifecycle integration: `CreateServerHandler` (`create_server.py`), `ImportServerHandler` (`import_server.py`), and `FilesystemReconciliationService` (`filesystem_reconciliation.py`) will dispatch `CreateBranchCommand(server_id=server_id, name="main", head_commit_id=None)` via `command_bus`.
  - In `CreateBranchHandler` (`backend/app/modules/versioning/application/commands/create_branch.py:97-103`):
    - When `command.name == "main"`:
      If branch exists, return success idempotently.
      If missing, construct:
      ```python
      branch = ServerBranch(
          id=str(uuid.uuid4()),
          server_id=command.server_id,
          name="main",
          head_commit_id=None,
          status=BranchStatus.CREATED, # [FACT] matches create_branch.py:102
          is_system=True,              # [NEW field]
          is_protected=True,
          protection_policy=BranchProtectionPolicy(
              require_test_pass=True,
              allow_direct_commit=False,
              allow_force_bypass=False,
              prevent_deletion=True,
          ),
      )
      ```
- **Alembic Backfill Migration (`b1e2100000023_eager_main_and_system_protection.py`)**:
  - `down_revision = "b1e2100000022"` `[FACT]`
  - Use `op.batch_alter_table("server_branches")` for SQLite compatibility:
    - Add column `is_system` (`Boolean`, default `False`, nullable=False).
    - Add table constraint `CheckConstraint("NOT (name = 'main' AND status = 'archived')", name="ck_server_branch_main_not_archived")`.
    - Add table constraint `CheckConstraint("NOT (is_system = 1 AND is_protected = 0)", name="ck_server_branch_system_protected")`.
  - Idempotent data backfill execution:
    ```sql
    -- Insert main for servers lacking a main branch
    INSERT INTO server_branches (id, server_id, name, head_commit_id, status, is_protected, is_system, created_at)
    SELECT
        lower(hex(randomblob(16))),
        s.id,
        'main',
        NULL,
        'created',
        1,
        1,
        CURRENT_TIMESTAMP
    FROM servers s
    WHERE NOT EXISTS (
        SELECT 1 FROM server_branches sb
        WHERE sb.server_id = s.id AND sb.name = 'main'
    );

    -- Upgrade existing main branches to system-protected
    UPDATE server_branches
    SET is_system = 1, is_protected = 1
    WHERE name = 'main';
    ```
  - Bump `RELEASE_MINIMUM_DB_REVISION = "b1e2100000023"` in `backend/app/core/persistence/db_revision.py:30`.
  - Downgrade note: `downgrade()` drops constraints and column, but requires rolling back code first.

### 3.2 W2: Genesis Seeding Commit Path
- **The Problem**: If `main` is eager with `head_commit_id=None` and direct user commits are blocked, no initial commit could ever be created.
- **Genesis Rule**:
  In `CreateCommitHandler` (`backend/app/modules/versioning/application/commands/create_commit.py:125-158`):
  ```python
  if branch.is_system or branch.name == "main":
      # Check Genesis Exception
      if branch.head_commit_id is None and command.allow_system_exemption:
          # Exactly one parent-less seeding commit is permitted via in-process system call
          is_genesis = True
      else:
          # Strict ban: user direct commits to main are completely forbidden
          raise BranchProtectedError(
              f"Direct commits to system branch '{branch.name}' are forbidden. "
              "Changes must be made on a working branch and merged via fast-forward."
          )
  ```
  - When genesis commit succeeds:
    - Sets `parent_commit_ids = []`
    - Advances `branch.head_commit_id = commit.id`
    - Transitions `branch.status = BranchStatus.ACTIVE`
    - Saves audit log in `ActivityRepository`: `event_type="versioning.main_genesis_created"`, `summary="Initial genesis commit created on main branch"`.
    - Emits `[NEW]` `BranchHeadAdvancedEvent` (defined in §3.1 Part B).

### 3.3 W3: System Protection Immutability
- **Domain Layer (`backend/app/modules/versioning/domain/entities.py:82-145`)**:
  - Add `is_system: bool = False` to `ServerBranch`.
  - `ServerBranch.archive()`:
    ```python
    if self.is_system or self.name == "main":
        raise BranchProtectedError(f"System branch '{self.name}' cannot be archived")
    ```
  - `ServerBranch.unprotect()`:
    ```python
    if self.is_system or self.name == "main":
        raise BranchProtectedError(f"System branch '{self.name}' cannot be unprotected")
    ```
  - `ServerBranch.can_archive()`: Return `False` unconditionally if `self.is_system or self.name == "main"`.
- **Application Handler Layer**:
  - `ArchiveBranchHandler` (`archive_branch.py:82`): Reject if `branch.is_system or branch.name == "main"` with HTTP 409 `BranchProtectedError`.
  - `RemoveBranchProtectionHandler` (`branch_protection.py:125`): Reject if `branch.is_system or branch.name == "main"` with HTTP 409 `BranchProtectedError`.
  - `ConfigureBranchProtectionHandler` (`branch_protection.py:50`): Reject any update attempting to set `prevent_deletion=False` or `allow_direct_commit=True` on `is_system` branch.

### 3.4 W4: Auto-Commit & In-Process Exemption
- **Zero Client-Settable Flag Invariant**:
  - `CreateCommitRequest` (`schemas/versioning.py:28-34`) and `AutoCommitLiveChangesRequest` (`schemas/versioning.py:299-300`) MUST NOT include `is_system_reconciliation` or `allow_system_exemption`.
  - `CreateCommitCommand` (`create_commit.py:30-37`) adds internal-only parameter:
    `allow_system_exemption: bool = False` `[NEW param]`.
  - The HTTP route `POST /api/v1/servers/{server_id}/versioning/commits` in `routers/versioning.py:240-255` ALWAYS sets `allow_system_exemption=False`.
- **AutoCommitLiveChanges Execution**:
  - `AutoCommitLiveChangesCommand` represents automated disk reconciliation.
  - When target branch is `main` (or `is_system`):
    - Handler verifies caller possesses `server:version:commit`.
    - Handler sets `allow_system_exemption=True` on the internal `CreateCommitCommand` it dispatches (`auto_commit_live_changes.py:136`).
    - Writes an audit log to `ActivityRepository`: `event_type="versioning.auto_commit_to_main"`.
  - *Documented Rejected Alternative*: Diverting live changes to a branch named `live-sync/<timestamp>`. Rejected by owner baseline because `ScanLiveChanges` and the live server monitoring baseline rely directly on comparing live disk against `main`. Diverting would cause `main` to drift permanently out of sync with disk reality unless an operator manually merges.

### 3.5 W6: Hardened Internal Directory Guard (Files API)
- Consolidate all path safety and protection checks into `_resolve_server_file_path` in `backend/app/api/v1/routers/files.py:35-72`:
  - Definition:
    ```python
    PROTECTED_FIRST_COMPONENTS: frozenset[str] = frozenset({
        ".onx",
        ".onx-manager",
        ".mcsmanager",
    })
    SENSITIVE_FILENAMES: frozenset[str] = frozenset({".env"})
    ```
  - First-component check on relative path:
    ```python
    # Clean relative path string
    rel_str = str(target_path.relative_to(resolved_root)).replace("\\", "/")
    first_component = rel_str.split("/")[0].lower() if rel_str and rel_str != "." else ""

    if first_component in PROTECTED_FIRST_COMPONENTS:
        if operation in ("write", "delete", "upload", "mkdir"):
            raise HTTPException(
                status_code=403,
                detail=f"Modifying internal directory '{first_component}' is forbidden"
            )
        # Reads (GET /content, GET /download) remain allowed per owner baseline
    ```
  - Filtering in `list_files` (`files.py:75-109`):
    When listing directory at `resolved_root` (`rel_str == ""`), filter out entries where `item.name.lower() in PROTECTED_FIRST_COMPONENTS`. (Omitted from listing, preventing accidental selection or deletion).
  - `.env` Hygiene Closure:
    - In `mkdir` (`files.py:234`): Add `_assert_not_sensitive(target_path)` (prevents creating a directory named `.env`).
    - In `list_files` (`files.py:90`): Hide or mask `.env` from unauthenticated or non-admin requests, or mark `is_sensitive=True`.

## 4. Affected Components
- `backend/app/modules/versioning/domain/entities.py` (`ServerBranch`, `BranchProtectionPolicy`)
- `backend/app/modules/versioning/infrastructure/models.py` (`ServerBranchModel`)
- `backend/app/modules/versioning/application/commands/archive_branch.py`
- `backend/app/modules/versioning/application/commands/branch_protection.py`
- `backend/app/modules/versioning/application/commands/create_commit.py`
- `backend/app/modules/versioning/application/commands/auto_commit_live_changes.py`
- `backend/app/modules/server/application/commands/create_server.py`
- `backend/app/modules/server/application/commands/import_server.py`
- `backend/app/modules/server/application/services/filesystem_reconciliation.py`
- `backend/app/api/v1/routers/files.py`
- Database: Alembic migration `b1e2100000023`

## 5. Interfaces & Contracts
- **Database Schema**:
  ```python
  # In backend/alembic/versions/b1e2100000023_eager_main_and_system_protection.py
  with op.batch_alter_table("server_branches") as batch_op:
      batch_op.add_column(sa.Column("is_system", sa.Boolean(), nullable=False, server_default="0"))
      batch_op.create_check_constraint(
          "ck_server_branch_main_not_archived",
          "NOT (name = 'main' AND status = 'archived')"
      )
      batch_op.create_check_constraint(
          "ck_server_branch_system_protected",
          "NOT (is_system = 1 AND is_protected = 0)"
      )
  ```
- **REST Behavior**:
  - `POST /api/v1/servers/{server_id}/versioning/branches/main/archive` -> HTTP 409 Conflict.
  - `DELETE /api/v1/servers/{server_id}/versioning/branches/main/protection` -> HTTP 409 Conflict.
  - `POST /api/v1/servers/{server_id}/versioning/commits` with `branch_name="main"` -> HTTP 409 Conflict.
  - `DELETE /api/v1/servers/{server_id}/files?path=.onx-manager` -> HTTP 403 Forbidden.
  - `POST /api/v1/servers/{server_id}/files/mkdir?path=.env` -> HTTP 403 Forbidden.

## 6. Failure & Edge Cases
- **Orphan Test Rows in Dev DB**: Migration specifically uses `WHERE EXISTS (SELECT 1 FROM servers s WHERE s.id = ...)` to prevent attaching `main` branches to orphan `server_id`s left by previous tests.
- **Pre-existing Unprotected `main`**: Backfill migration updates `is_system=1`, `is_protected=1` on all existing rows where `name = 'main'`.
- **Windows Case Insensitivity**: All checks use `.lower()` to neutralize bypasses via `.ONX` or `.Onx-Manager`.

## 7. Tests & Verification
- `test_main_branch_genesis_and_subsequent_commit_ban`: Proves genesis succeeds on `head=None` with system exemption; subsequent user direct commits fail with 409 even with bypass permissions.
- `test_system_main_cannot_be_archived_or_unprotected`: Verifies 409 on archive, unprotect, and configure-protection.
- `test_eager_main_creation_across_server_entrypoints`: Tests `CreateServerHandler`, `ImportServerHandler`, and `FilesystemReconciliationService`.
- `test_files_internal_guard_mutation_403_and_read_allow`: Matrix testing all 7 Files routes against `.onx`, `.onx-manager`, and `.mcsmanager`.
- `test_migration_b1e2100000023_idempotency`: Runs migration twice on SQLite and PostgreSQL.

## 8. Out of Scope
- Branch renaming.
- Custom user-created system branches.

---

# Part B: Merge-to-Main (W5)

## 1. Goal
Provide a secure, deterministic merge capability to advance `main` and any protected branch using a **Fast-Forward-Only** rule to an already-tested commit. Divergent histories must be rejected with actionable guidance, preventing untestable synthetic commits on production baselines. Non-protected targets retain explicit-manifest merging with added protection checks.

## 2. Current Behavior
- `[FACT]` `MergeCommitsCommand` exists in `merge_commits.py:18-188`.
- `[FACT]` `merge_commits.py:86-95` verifies target branch exists and is not archived, but NEVER checks `branch.is_protected` or `branch.can_commit_directly()`.
- `[FACT]` `dag.py` implements only `check_cycle` and `traverse_history`. There is NO ancestor check.
- `[FACT]` `merge_commits.py:148` writes `world_snapshot_id = parent_commits[0].world_snapshot_id`, using the caller's arbitrary ordering.
- `[FACT]` In `promote_commit.py:197-202`, world changes are swapped into live `server_dir` ONLY when `command.keep_world_changes` is explicitly True. Merging into a branch in the database does not touch the live filesystem directory.

## 3. Proposed Change

### 3.1 DAG Algorithmic Extension (`backend/app/modules/versioning/domain/dag.py`)
Add single traversal primitive to `dag.py`:
```python
# [NEW function] in backend/app/modules/versioning/domain/dag.py
async def is_ancestor(
    ancestor_id: str,
    descendant_id: str,
    get_parents_func: Callable[[str], Awaitable[list[str]]],
) -> bool:
    """Returns True if ancestor_id is in the ancestry graph of descendant_id."""
    if ancestor_id == descendant_id:
        return True

    visited: set[str] = set()
    queue = deque([descendant_id])

    while queue:
        current = queue.popleft()
        if current == ancestor_id:
            return True
        if current in visited:
            continue
        visited.add(current)

        parents = await get_parents_func(current)
        for p in parents:
            if p not in visited:
                queue.append(p)

    return False
```
*(Note: `find_lca` is explicitly DROPPED per W5 because fast-forward does not perform multi-parent synthesis).*

### 3.2 Fast-Forward-Only Policy for Protected Targets
In `MergeCommitsHandler` (`backend/app/modules/versioning/application/commands/merge_commits.py`):
```python
# [NEW event] in backend/app/modules/versioning/domain/events.py
class BranchHeadAdvancedEvent(DomainEvent):
    server_id: str
    branch_name: str
    branch_id: str
    old_head_commit_id: str | None
    new_head_commit_id: str
    advanced_by: str = "fast_forward"
```

1. **Target Protection Check**:
   Retrieve `target_branch = await versioning_repo.get_branch_by_name(command.server_id, command.target_branch_name)`.
   Check if `target_branch.is_protected` (`[FACT]` `entities.py:94`).
2. **Protected Target Rule Evaluation**:
   If `target_branch.is_protected`:
   - Case 1: **Headless Target** (`target_branch.head_commit_id is None`):
     Adopt source commit:
     Advance `target_branch.head_commit_id = command.source_commit_id`.
     Transition `target_branch.status = BranchStatus.ACTIVE`.
     Emit `BranchHeadAdvancedEvent`.
     Return `CommandResult(success=True, data={"advanced": True, "head_commit_id": command.source_commit_id, "is_fast_forward": True})`.
   - Case 2: **Already Ancestor (No-Op Success)**:
     If `await is_ancestor(command.source_commit_id, target_branch.head_commit_id, get_parents)`:
     Target already contains source. Return success idempotently:
     Return `CommandResult(success=True, data={"advanced": False, "head_commit_id": target_branch.head_commit_id, "is_fast_forward": True, "message": "Branch is already up to date."})`.
   - Case 3: **Linear Fast-Forward**:
     If `await is_ancestor(target_branch.head_commit_id, command.source_commit_id, get_parents)`:
     - Execute **Test Run Safety Gate** (§3.3 below).
     - Execute **Optimistic Concurrency Update** (§3.4 below).
     - Emit `BranchHeadAdvancedEvent`.
     - Return `CommandResult(success=True, data={"advanced": True, "head_commit_id": command.source_commit_id, "is_fast_forward": True})`.
   - Case 4: **Divergent History (Strict Rejection)**:
     If neither is ancestor of the other:
     Raise `ConflictError` (HTTP 409):
     *"Cannot merge into protected branch '{target_branch.name}': history has diverged. Fast-forward merge is required. Please merge '{target_branch.name}' into your feature branch, test the merged result in an isolated test run, and retry."*
3. **Non-Protected Target Path**:
   If `target_branch` is NOT protected, retain existing explicit-manifest merge logic (`merge_commits.py:127-160`), creating a multi-parent commit if caller provides `command.manifest`.

### 3.3 Test Run Verification Gate (Pinned Precedent)
Prior to advancing any protected branch:
1. Verify source branch is not `ARCHIVED` (using `command.source_branch_name` if provided, else resolving branch from commit).
2. If `target_branch.protection_policy.require_test_pass` is True:
   - Query test runs using existing repository method `await versioning_repo.list_test_runs(command.server_id, limit=50)`.
   - Filter runs matching `r.commit_id == command.source_commit_id`.
   - Safety rule matching `promote_commit.py:118-145` `[FACT]`:
     - Assert at least one run has `status == TestRunStatus.PASSED`.
     - Invalidation check: ensure no subsequent test run for this commit has `status == TestRunStatus.FAILED`.
     - If verification fails, raise `ValidationError` (HTTP 400: *"Cannot advance protected branch '{target_branch.name}': commit '{command.source_commit_id}' has not passed test verification or has subsequent failures."*).

### 3.4 Snapshot & Concurrency Semantics
- **World Snapshot Adoption**: The fast-forward pointer move adopts the source commit's `world_snapshot_id`.
  - *Conclusion on live deployment safety*: Live server world files on disk are NOT touched by merge. As verified in `promote_commit.py:197-202` `[FACT]`, live world files are only swapped during server promotion if `command.keep_world_changes` is explicitly specified.
- **Optimistic Concurrency**:
  In `VersioningRepository` (`backend/app/modules/versioning/infrastructure/repository.py`):
  Implement `advance_branch_head_optimistic(branch_id: str, new_head: str, expected_head: str | None) -> bool` `[NEW method]`.
  Executes `UPDATE server_branches SET head_commit_id = :new_head WHERE id = :branch_id AND (head_commit_id = :expected_head OR (:expected_head IS NULL AND head_commit_id IS NULL))`.
  If rows affected == 0: raise `ConflictError` (HTTP 409: *"Concurrent update detected: branch head moved during merge evaluation."*).

## 4. Affected Components
- `backend/app/modules/versioning/domain/dag.py`
- `backend/app/modules/versioning/domain/events.py`
- `backend/app/modules/versioning/application/commands/merge_commits.py`
- `backend/app/modules/versioning/infrastructure/repository.py`
- `backend/app/api/v1/schemas/versioning.py`
- `backend/app/api/v1/routers/versioning.py`

## 5. Interfaces & Contracts
- **Request Schema (`MergeCommitsRequest` in `schemas/versioning.py:60-65`)**:
  ```python
  class MergeCommitsRequest(BaseModel):
      target_branch_name: str = Field(..., min_length=1, max_length=64)
      source_commit_id: str = Field(..., min_length=1, max_length=36)
      source_branch_name: str | None = Field(default=None, max_length=64)
      message: str = Field(default="Merge fast-forward", max_length=500)
      manifest: dict[str, Any] | None = None
  ```
- **Response Schema (`MergeCommitsResponse`)**:
  ```python
  class MergeCommitsResponse(BaseResponse):
      success: bool
      advanced: bool
      head_commit_id: str
      commit_id: str | None = None  # None on fast-forward
      is_fast_forward: bool
      message: str | None = None
  ```

## 6. Failure & Edge Cases
- **No-Op Merge**: Source commit already in target ancestry returns 200 with `advanced=False`.
- **Target Head Moved Concurrently**: Optimistic update fails with 0 rows -> 409 Conflict.
- **Unverified Commit**: Fails with 400 `ValidationError` referencing missing or failed test run.

## 7. Tests & Verification
- Unit test: `test_dag_is_ancestor_linear_and_branching` in `test_dag.py`.
- Integration test: `test_merge_into_protected_main_fast_forward_success`.
- Integration test: `test_merge_into_protected_main_divergent_rejected_409`.
- Integration test: `test_merge_into_protected_main_untested_rejected_400`.
- Integration test: `test_merge_concurrent_head_move_optimistic_conflict_409`.

## 8. Out of Scope
- Automatic 3-way line-level diff/patch engine.
- Synthetic multi-parent merge commits on protected branches.

---

# Part C: Branch-Aware Files & Commit-from-Worktree (W6–W10)

## 1. Goal
Unify file browsing and editing in `ServerFilesPage.tsx` across the live server directory and isolated branch worktrees using a parameter root-switch on the Files API. Enforce ADR-0016 `TRACKED` path classification, provide `CommitFromWorktreeCommand` with diff-against-parent manifest compilation and optimistic concurrency, and fix BUG-V04 in `tree_writer.py`.

## 2. Current Behavior
- `[FACT]` `_resolve_server_file_path()` in `files.py:35-72` resolves strictly against `server.root_path` (live directory).
- `[FACT]` All 7 Files API routes take only `path: str` query parameters.
- `[FACT]` Materialization endpoints (`versioning.py:634-705`) support tree inspection and single-file overwrite, but lack upload, delete, mkdir, and download capabilities.
- `[FACT]` No path exists to commit an edited worktree back to a branch (`commit_from_materialization` does not exist).
- `[FACT]` `tree_writer.py:82-87` contains BUG-V04: an unhandled exception during materialization deletes both staging and target directories.
- `[FACT]` `ManifestBuilder.build_manifest` (`manifest_builder.py:14-118`) captures configs and mod jar hashes, but omits non-whitelisted root files (e.g. `ops.json`) and silently swallows read exceptions.

## 3. Proposed Change

### 3.1 W7: Files API Root-Switch & ADR-0016 Classification
- **Parameter Extension**:
  In `backend/app/api/v1/routers/files.py`:
  Update `_resolve_server_file_path`:
  ```python
  async def _resolve_server_file_path(
      server_id: str,
      relative_path: str,
      query_bus: QueryBus,
      source: Literal["live", "worktree"] = "live",
      ref: str | None = None,
      operation: Literal["read", "write", "delete", "upload", "download", "mkdir", "list"] = "read",
      must_exist: bool = False,
  ) -> tuple[Path, Path, str]:
  ```
  - When `source == "live"`: resolves to `server.root_path` (retaining existing behavior).
  - When `source == "worktree"`:
    - `ref` is the `materialization_id`.
    - Fetch materialization: `materialization = await query_bus.ask(GetMaterializationQuery(server_id=server_id, materialization_id=ref))`.
    - Validate `materialization.status == MaterializationStatus.READY` (`[FACT]` `entities.py:270`).
    - Traversal jail: `resolved_root = Path(materialization.root_path).resolve()`.
    - `clean_rel = relative_path.lstrip("/") if relative_path else ""`.
    - `target_path = (resolved_root / clean_rel).resolve()`.
    - Assert `target_path.relative_to(resolved_root)` else raise HTTP 403 Forbidden.
    - **Mutation Safety & ADR-0016 Classification**:
      If `operation in ("write", "delete", "upload", "mkdir")`:
      - Verify `materialization.mode == MaterializationMode.EDITABLE` (`[FACT]` `entities.py:273`); raise HTTP 409 Conflict if `READONLY`.
      - **Classification Check (mirroring `write_materialized_file.py:97-115` `[FACT]`)**:
        Check `first_segment = clean_rel.split("/")[0] if clean_rel else ""`:
        - If `first_segment in ("world", "world_nether", "world_the_end")`: raise HTTP 403 (`PathClassification.PERSISTENT`).
        - If `first_segment in ("logs", "crash-reports")`: raise HTTP 403 (`PathClassification.GENERATED`).
        - If `first_segment == ".onx"`: raise HTTP 403 (`PathClassification.IGNORED`).
        - If `operation == "upload"` and `target_path.suffix.lower() in (".jar", ".bin", ".exe")`:
          Raise HTTP 400 Bad Request ("Binary and JAR uploads to worktrees are not supported in v1").
      - Keep classification consistent:
        Update `materialization.path_classification[clean_rel] = PathClassification.TRACKED`.
- Update all 7 routes in `files.py`:
  Add query parameters `source: Literal["live", "worktree"] = Query(default="live")` and `ref: str | None = Query(default=None)`.

### 3.2 W8: `CommitFromWorktreeCommand` & Manifest Diff
- Create `backend/app/modules/versioning/application/commands/commit_from_worktree.py` `[NEW file]`:
  ```python
  class CommitFromWorktreeCommand(Command):
      server_id: str
      materialization_id: str
      message: str
      author_id: str | None = None
  ```
- **Handler Execution Steps**:
  1. Retrieve `materialization = await versioning_repo.get_materialization(command.materialization_id)`.
  2. Validate `materialization.status == MaterializationStatus.READY` and `materialization.mode == MaterializationMode.EDITABLE`.
  3. **Target Branch Resolution (`[FACT]` `create_materialization.py:170` formats `revision="branch:{name}@{head}"`)**:
     - Parse branch name from `materialization.revision`:
       `branch_name = materialization.revision.split("@")[0].replace("branch:", "")`.
     - Reject if not `branch:`-based (commit/tag materializations cannot be committed from).
     - Fetch `branch = await versioning_repo.get_branch_by_name(command.server_id, branch_name)`.
     - Target protection check: If `branch.is_system or branch.name == "main"`:
       Raise `BranchProtectedError` (HTTP 409: *"Cannot commit worktree directly to protected branch 'main'. Commit to a feature branch and merge."*).
  4. **Stale Head Check**:
     Assert `branch.head_commit_id == materialization.commit_id`.
     If mismatched: raise `ConflictError` (HTTP 409: *"Branch head has advanced since this workspace was opened. Commit rejected to prevent overwriting concurrent commits."*).
  5. **Disk Space Pre-Check**:
     Check host storage: `shutil.disk_usage(materialization.root_path).free`.
     If `< 1 * 1024 * 1024 * 1024` (1 GB):
     Raise `InsufficientDiskSpaceError` (HTTP 507: *"Insufficient disk space to compile commit manifest."*) `[NEW exception in core/exceptions.py]`.
  6. **Diff-Against-Parent Manifest Compilation**:
     - Retrieve `parent_commit = await versioning_repo.get_commit(materialization.commit_id)`.
     - Start with a copy of `new_configs = dict(parent_commit.manifest.configs)`.
     - Scan `materialization.root_path`:
       - For tracked files in `materialization.path_classification`:
         - If file exists on disk:
           Check size `<= 10 * 1024 * 1024` (10 MB). If larger: raise `ValidationError` ("Config file exceeds 10MB limit").
           Read text with `encoding="utf-8", errors="replace"`.
           Update `new_configs[rel_path] = content`.
         - If file was deleted from worktree:
           Remove `new_configs.pop(rel_path, None)`.
     - Carry over mods and plugins from `parent_commit.manifest.mods` by reference (preserves jars without silent drops).
     - Reuse `parent_commit.world_snapshot_id`.
  7. **Commit & Optimistic Concurrency Update**:
     - Construct `new_commit = ServerCommit(...)`.
     - Save commit: `await versioning_repo.save_commit(new_commit)`.
     - Execute optimistic head advance:
       `updated = await versioning_repo.advance_branch_head_optimistic(branch.id, new_commit.id, materialization.commit_id)`.
       If `not updated`:
       Raise `ConflictError` (HTTP 409: *"Branch head moved concurrently during commit."*).
  8. **Workspace Baseline Update (W8)**:
     - Advance workspace baseline so it remains usable:
       `materialization.commit_id = new_commit.id`
       `materialization.revision = f"branch:{branch.name}@{new_commit.id[:7]}"`
       `materialization.status = MaterializationStatus.READY` (remains READY, not STALE).
       Save materialization.

### 3.3 W10: BUG-V04 Orphan Cleanup Fix
- **Defect Analysis**: In `backend/app/modules/versioning/infrastructure/tree_writer.py:82-87` `[FACT]`:
  The `except Exception:` block calls `shutil.rmtree(target_path, ignore_errors=True)`. If target existed prior to write, or if atomic replace failed, target is wiped out.
- **Fix & Layering Ownership**:
  - `fs_atomic.py:84-88` `[FACT]` owns cleanup of its internal swap artifacts (`.stage_<uid>`, `.old_<uid>`) in its `finally:` block.
  - `tree_writer.py` owns cleanup of its caller-level `staging_dir` ONLY.
  - In `tree_writer.py`:
    ```python
    except Exception:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        # REMOVED: shutil.rmtree(target_path) — target directory must NEVER be wiped on error!
        raise
    ```

### 3.4 W9: Workspaces Lifecycle & Per-Server Cap
- **No Silent Auto-Prune**: Worktrees do not expire on timers; they persist until explicitly deleted via `DELETE /materializations/{mat_id}`.
- **Per-Server Workspace Cap**:
  In `CreateMaterializationHandler` (`create_materialization.py:75`):
  Query active materializations for server. If count of `READY` or `PENDING` worktrees >= 5 (default cap):
  Raise `ConflictError` (HTTP 409: *"Maximum active workspace limit (5) reached for this server. Please remove an unused workspace before opening a new one."*).

### 3.5 Frontend Integration (`ServerFilesPage.tsx`)
- Add context switcher bar to `ServerFilesPage.tsx`:
  - Toggle: `[ Live Server | Branch Workspaces ]`.
  - When "Branch Workspaces" is active:
    - Branch dropdown populated from `api.listBranches(serverId)`.
    - If active READY materialization exists: renders file tree with workspace badge (`[Workspace: {branch} @ {commit_id[:7]}]`) and button: **"Commit Workspace Changes"**.
    - If no workspace exists: renders empty state banner with button: **"Open Branch Workspace"** (`POST .../materializations` with `mode: "editable"`).
  - All file queries append `{ source: "worktree", ref: activeMatId }`.
  - Server process control actions (Console, Terminal, Power) are visibly marked as operating on the live server process only.

## 4. Affected Components
- `backend/app/api/v1/routers/files.py`
- `backend/app/modules/versioning/infrastructure/tree_writer.py`
- `backend/app/modules/versioning/application/commands/commit_from_worktree.py` `[NEW file]`
- `backend/app/modules/versioning/application/commands/create_materialization.py`
- `backend/app/api/v1/routers/versioning.py`
- `frontend/src/services/api.ts`
- `frontend/src/server_manager/pages/ServerFilesPage.tsx`
- `contracts/permissions.yaml`

## 5. Interfaces & Contracts
- **New Endpoint**:
  `POST /api/v1/servers/{server_id}/versioning/materializations/{mat_id}/commit`
  - Body: `{"message": "string"}`
  - Response: `{"commit_id": "string", "branch_name": "string", "parent_commit_id": "string"}`
  - Permission: `server:version:commit`
- **Files API Query Extension**:
  `GET/PUT/DELETE/POST /api/v1/servers/{server_id}/files*?source=live|worktree&ref=mat_id`

## 6. Failure & Edge Cases
- **Concurrent Commits to Branch**: First commit advances head; second commit fails stale-head check or optimistic DB update -> HTTP 409 Conflict.
- **Disk Full During Manifest Compile**: Free disk < 1 GB raises HTTP 507 `InsufficientDiskSpaceError`.
- **Large Config Write**: Uploads > 10 MB fail with 400 `ValidationError` instead of silent truncation.

## 7. Tests & Verification
- Unit test: `test_tree_writer_exception_preserves_target_dir` (proves BUG-V04 fix).
- Unit test: `test_files_api_worktree_tracked_classification_enforcement` (matrix testing PERSISTENT, GENERATED, IGNORED, and TRACKED paths).
- Integration test: `test_commit_from_worktree_optimistic_concurrency_conflict`.
- Integration test: `test_commit_from_worktree_manifest_diff_preserves_configs_and_mods`.
- Frontend test: `ServerFilesPage.test.tsx` verifying workspace mode toggle, workspace creation dialog, and commit modal.

## 8. Out of Scope
- Direct binary/jar uploads inside worktrees (v1 is config/tracked only).
- Worktree edits to server world region files.

---

# Cross-Part Dependencies, Build Order & Rollback

## 1. Build & Dependency Sequence

```text
Part A (W1–W4, W6: main Provisioning, System Protection, Genesis, Files Guard)
  │
  ├──> Part B (W5: Fast-Forward Merge-to-Main, LCA/Ancestor check, Test Gate)
  │
  └──> Part C (W6–W10: Branch-Aware Files, Worktree Root-Switch, Commit-from-Worktree)
```

1. **Part A First**: Parts B and C require `main` to exist authoritatively as a system-protected branch.
2. **Part B & Part C Backend Parallel**: Part B merge advancement and Part C worktree operations can be implemented concurrently in the backend.
3. **Part C Frontend Last**: Wires the complete end-to-end UI loop in `ServerFilesPage.tsx`.

## 2. Rollback Paths
- **Part A Rollback**: Revert migration `b1e2100000023` to drop check constraints and `is_system` column. Safe because existing `name="main"` records remain valid.
- **Part B Rollback**: Revert `merge_commits.py` handler logic. Commit DAG remains intact.
- **Part C Rollback**: Revert query parameters in `files.py` and `ServerFilesPage.tsx`. Live file browsing operates unchanged.

---

# Verification Gates & Test Plan

All three parts must satisfy the repository's 6 canonical CI quality gates before merge (`[FACT]` `testing-and-verification.md:45`, `STATE.json:32`):
1. `scripts/check-db-revision`: Passes against migration `b1e2100000023`.
2. `scripts/check-ruff-baseline`: Clean lint on all new/modified Python files.
3. `scripts/check-version-propagation`: App version integrity maintained.
4. `scripts/check-route-contract`: Contract verification passes with new route `POST .../materializations/{mat_id}/commit` registered in `contracts/permissions.yaml`.
5. `scripts/check-ps1-bom`: No UTF-8 BOM regression on PowerShell scripts.
6. `scripts/check-stray-db`: No stray SQLite databases created in repo root.

### Full Test Execution Requirements
Per `.ai/RULES/testing-and-verification.md:9-20`, milestone verification requires a **sequential** backend run with minimum 15-minute command timeout:
```bash
# Backend sequential verification
cd backend && python -m pytest -q

# Frontend verification
cd frontend && npm run typecheck && npm run lint && npm run test && npm run build
```

---

# Open Owner Decisions Required

The following questions require an explicit policy ruling from Mohamed before implementation begins:

1. **Auto-Commit to `main` vs. Divert Branch (W4 Tension)**:
   - *Option A (Recommended in spec)*: Allow in-process `AutoCommitLiveChangesCommand` to commit directly to `main` as an automated live disk reconciliation action (audit-logged, zero client-settable flags), preserving the live-scan baseline.
   - *Option B*: Strictly forbid ALL automated commits to `main`. Live changes would be diverted to an auto-created branch (e.g. `live-sync/<timestamp>`), requiring manual review and merge. Which policy do you mandate?
2. **Merge World Snapshots Policy (W5 Snapshot Treatment)**:
   - When fast-forwarding `main` to a feature branch commit, the branch pointer adopts the source commit's `world_snapshot_id`. Promoting to the live server does NOT deploy worlds unless `command.keep_world_changes` is True. Do you confirm that adopting the source world snapshot in the branch record while protecting live server disk worlds via promote gating is the desired behavior?
3. **Per-Server Materialization Cap Limit (W9 Workspace Policy)**:
   - The spec proposes a default cap of 5 concurrent active worktrees per server to bound disk consumption on hosts lacking reflink support. Is 5 an acceptable cap, or do you require a different threshold?
