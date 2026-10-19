# Design Spec: Eager System-Protected `main` & Files API Internal-Directory Guard (v3)

- **Spec Identifier**: `SPEC-2026-10-05-MAIN-PROTECTION-AND-FILES-GUARD-01`
- **Revision**: 3 (Scope-Reduced: "Part A-lite")
- **Date**: 2026-10-05
- **Author**: Antigravity (Design Spec Author role)
- **Status**: DRAFT — DESIGN SPEC ONLY (No code changes, no test changes, no commits)
- **Governance Classification**: Lane E (Future Product), Decision Level D2 (Major — Database Schema Change & API Contract Hardening)
- **Scope Baseline**: Derived from `SPEC-2026-10-05-BRANCH-AWARE-FILES-AND-PROTECTED-MAIN-01` (rev 2) following Independent Design Reviews Round 1 (findings F1–F21) and Round 2 (findings N1–N10), scoped down strictly per Owner Decision of 2026-10-05.

---

## 1. Goal

Provide strict lifecycle and identity protections for the default `main` branch and internal configuration directories in ONX Manager without impeding existing commit workflows:

1. **Eager `main` Provisioning (W1)**: Guarantee that every server—whether provisioned via new creation, imported from an archive (.zip), or reconciled from the filesystem—eagerly provisions an initial `main` branch with `head_commit_id=None` and `BranchStatus.CREATED`.
2. **System Protection of `main` (W3)**: Guarantee that `main` cannot be archived, unprotected, or reconfigured via user-facing APIs, application handlers, or domain methods. Provide database-level backstops that prevent setting `main` to `archived` while allowing clean server deletion.
3. **Internal Directory Guard (W6)**: Protect internal control and metadata directories (`.onx`, `.onx-manager`, `.mcsmanager`) from mutation or deletion via the Files API across all 7 endpoints, while preserving read access and omitting internal roots from default directory listings. Close `.env` exposure gaps on directory listing and `mkdir`.
4. **Preserve Existing Commit Flows**: Maintain 100% backward compatibility for direct snapshot commits (`CreateCommitHandler`), live auto-commits (`AutoCommitLiveChangesHandler`), import reviews (`ImportReviewModal.tsx`), and promote flows on `main`. No write restrictions, genesis rules, or client bypass privileges are introduced in this revision.

---

## 2. Current Behavior & Evidence

Every statement below is verified against the codebase as of this session with exact citations:

1. **Lazy Provisioning of `main`**:
   - `backend/app/modules/versioning/application/commands/create_commit.py:119-127`: When a commit is created, if the target branch does not exist, it is lazily created `[FACT]`. If a server is created but no commits have been made, `main` does not exist in `server_branches`.
   - `backend/app/modules/versioning/application/commands/auto_commit_live_changes.py:79-83`: Unlike `create_commit.py`, `auto_commit_live_changes.py` requires the branch to exist and raises `NotFoundError(f"Branch '{command.branch}' not found...")` `[FACT]`.
2. **Headless `main` Support Across Readers & Writers**:
   - `backend/app/modules/versioning/application/queries/get_branch_history.py:59-60`: `if branch.head_commit_id is None: return []` `[FACT]`. Returns an empty list without error.
   - `backend/app/modules/versioning/application/queries/scan_live_changes.py:99-101`: `if commit is None: if source in ("server", "main", ""): return {"changes": [], "auto_commit": None}` `[FACT]`. Returns empty changes without 404 for headless `main`.
   - `backend/app/modules/versioning/application/commands/auto_commit_live_changes.py:110-120`: If `branch.head_commit_id` is `None`, uses an empty `source_tree = Tree(server_type="vanilla", minecraft_version="1.21.1")` and advances to `CreateCommitHandler` `[FACT]`.
   - `backend/app/modules/versioning/application/commands/create_commit.py:166-175`: If `branch.head_commit_id` is `None`, sets `parent_ids=[]` creating the initial root commit, and calls `branch.advance_head(commit.id)` transitioning status to `BranchStatus.ACTIVE` `[FACT]`.
   - `backend/app/modules/versioning/application/commands/create_materialization.py:90-94`: `if branch is None or not branch.head_commit_id: raise NotFoundError(f"Branch '{command.ref}' not found...")` `[FACT]`. Worktree materialization cleanly rejects headless branches.
   - `frontend/src/server_manager/pages/ServerVersioningPage.tsx:494-497`: When `filteredCommits.length === 0`, renders: `"No snapshot commits yet on branch 'main'. Click 'Create Snapshot Commit' above to create your first commit."` `[FACT]`. Degrades cleanly to the empty state.
3. **Existing Protection Policy Mechanics & Dead Fields**:
   - `backend/app/modules/versioning/domain/entities.py:52-60`: `BranchProtectionPolicy` defines `require_test_pass: bool = True`, `allow_direct_commit: bool = False`, `allow_force_bypass: bool = True`, `prevent_deletion: bool = True` `[FACT]`.
   - In `backend/app/`, grep confirms `require_test_pass` and `allow_force_bypass` have **zero** enforcement logic anywhere in backend application handlers or domain logic `[FACT]`. They are dead configuration fields.
   - `backend/app/modules/versioning/domain/entities.py:132-139`: `ServerBranch.can_commit_directly()` returns `policy.allow_direct_commit` when `is_protected=True` `[FACT]`.
   - `backend/app/modules/versioning/application/commands/create_commit.py:130`: `elif branch.is_protected and not branch.can_commit_directly():` `[FACT]`.
   - `backend/app/modules/versioning/application/commands/auto_commit_live_changes.py:85`: `if branch.is_protected and not branch.can_commit_directly(): raise BranchProtectedError(...)` `[FACT]`.
   - If `is_protected=True` and `policy.allow_direct_commit=True`, `can_commit_directly()` evaluates to `True`, allowing existing direct commits and auto-commits to pass without restriction `[FACT]`.
4. **Server Deletion & Orphan Database Rows**:
   - `backend/app/modules/server/application/commands/delete_server.py:153`: Server row is deleted via `await repo.delete(server_id)` `[FACT]`.
   - `backend/app/modules/server/application/commands/delete_server.py:164-167`: Calls `cleanup_server_materializations(sid, self._event_bus)` `[FACT]`.
   - `backend/app/modules/versioning/infrastructure/models.py:27-40`: `ServerBranchModel` has no foreign key constraint to `ServerModel.id` (`servers` table). Server deletion does not delete branch rows `[FACT]`.
   - `backend/data/onx.db`: Direct read-only query confirms 129 orphan branch rows exist in dev DB for server IDs not present in `servers` `[FACT]`.
5. **Files API Choke Point & Gaps**:
   - `backend/app/api/v1/routers/files.py:20`: `SENSITIVE_FILENAMES: frozenset[str] = frozenset({".env"})` `[FACT]`.
   - `backend/app/api/v1/routers/files.py:23-33`: `_assert_not_sensitive(target_path)` checks `target_path.name.lower() in {".env"}` `[FACT]`.
   - `_assert_not_sensitive` is called on 5 endpoints (`GET /content`, `PUT /content`, `DELETE`, `POST /upload`, `GET /download`). It is **omitted** on `GET ""` (`list_files`: lines 75-109) and `POST /mkdir` (lines 234-252) `[FACT]`.
   - No guard exists for `.onx`, `.onx-manager`, or `.mcsmanager`. Any user with `server.{id}.files` permission can delete `.onx-manager/server.json`, triggering Bug 3 server identity loss on subsequent backend restart `[FACT]`.

---

## 3. Proposed Change

### 3.1 W1: Eager Provisioning of `main`

#### Domain Layer
In `backend/app/modules/versioning/domain/entities.py:82`:
- Add `is_system: bool = False` to `ServerBranch` dataclass `[NEW]`.
- System `main` properties upon initial creation:
  - `name = "main"`
  - `status = BranchStatus.CREATED`
  - `head_commit_id = None`
  - `is_system = True`
  - `is_protected = True`
  - `protection_policy = BranchProtectionPolicy(require_test_pass=True, allow_direct_commit=True, allow_force_bypass=True, prevent_deletion=True)` `[FACT]`.

#### Application Layer
1. In `backend/app/modules/versioning/application/commands/create_branch.py:15`:
   - Extend `CreateBranchCommand`:
     ```python
     class CreateBranchCommand(Command):
         server_id: str
         name: str
         head_commit_id: str | None = None
         is_system: bool = False  # [NEW]
         idempotent: bool = False  # [NEW]
     ```
   - In `CreateBranchHandler._execute` (`create_branch.py:65-115`):
     - If `command.idempotent` is `True` and `existing` branch is found:
       Return `CommandResult(success=True, entity_id=existing.id, details={"branch_id": existing.id, "name": existing.name, "already_existed": True})`.
     - When constructing `branch`:
       ```python
       is_sys = command.is_system or (command.name == "main")
       policy = (
           BranchProtectionPolicy(allow_direct_commit=True, prevent_deletion=True)
           if is_sys
           else None
       )
       branch = ServerBranch(
           id=str(uuid.uuid4()),
           server_id=command.server_id,
           name=command.name,
           head_commit_id=command.head_commit_id,
           status=BranchStatus.ACTIVE if command.head_commit_id else BranchStatus.CREATED,
           is_system=is_sys,
           is_protected=is_sys,
           protection_policy=policy,
       )
       ```
2. **Decoupled Event-Driven Wiring (No Layering Violations)**:
   - Review finding F13 established that `server` -> `versioning` direct application imports are forbidden.
   - `backend/app/modules/server/domain/events.py:9`: `ServerCreatedEvent` is already published by `Server.create` in both `CreateServerHandler` (`create_server.py:133`) and `ImportServerHandler` (`import_server.py:133`) via `UnitOfWork` `[FACT]`.
   - In `backend/app/modules/server/application/services/filesystem_reconciliation.py:199-209`:
     Inject optional `event_bus: EventBus | None = None` into `FilesystemReconciliationService.__init__` `[NEW]`.
     In `_handle_import` (`filesystem_reconciliation.py:792`) and `_handle_adopt` (`filesystem_reconciliation.py:1007`), when a new server is saved, publish `ServerCreatedEvent(server_id=ServerId(uid), name=server.name, minecraft_version=str(server.minecraft_version))` via `self._event_bus.publish` `[FACT]`.
   - In `backend/app/main.py:219` and `backend/app/api/v1/routers/servers.py:585`: Pass `event_bus` to `FilesystemReconciliationService(repo, event_bus=event_bus)`.
   - In `backend/app/modules/versioning/application/subscribers.py` [NEW]:
     ```python
     # backend/app/modules/versioning/application/subscribers.py [NEW]
     class ServerCreatedSubscriber(DomainEventSubscriber):  # [NEW]
         def __init__(self, command_bus: CommandBus) -> None:  # [NEW]
             self._command_bus = command_bus

         async def handle(self, event: ServerCreatedEvent) -> None:  # [NEW]
             cmd = CreateBranchCommand(
                 server_id=str(event.server_id),
                 name="main",
                 head_commit_id=None,
                 is_system=True,
                 idempotent=True,
             )
             await self._command_bus.send(cmd)
     ```
   - In `backend/app/registration.py`:
     Register `ServerCreatedSubscriber` for `"ServerCreatedEvent"`:
     `event_bus.subscribe("ServerCreatedEvent", server_created_subscriber)` `[NEW]`.

---

### 3.2 W3: System Protection of `main`

#### Domain Invariants
In `backend/app/modules/versioning/domain/entities.py:108-131`:
```python
def archive(self) -> None:
    if self.is_system or self.name == "main":
        raise BranchProtectedError("System branch 'main' cannot be archived")
    self.status = BranchStatus.ARCHIVED

def unprotect(self) -> None:
    if self.is_system or self.name == "main":
        raise BranchProtectedError("System branch 'main' cannot be unprotected")
    if self.status == BranchStatus.ARCHIVED:
        raise ValueError(f"Cannot unprotect archived branch '{self.name}'")
    self.is_protected = False
    self.protection_policy = None
```

#### Application Handler Invariants
1. `ArchiveBranchHandler` (`backend/app/modules/versioning/application/commands/archive_branch.py:82`):
   ```python
   if branch.is_system or branch.name == "main":
       raise BranchProtectedError("System branch 'main' cannot be archived")
   ```
2. `RemoveBranchProtectionHandler` (`backend/app/modules/versioning/application/commands/branch_protection.py:125`):
   ```python
   if branch.is_system or branch.name == "main":
       raise BranchProtectedError("System branch 'main' cannot be unprotected")
   ```
3. `SetBranchProtectionHandler` (`backend/app/modules/versioning/application/commands/branch_protection.py:57`):
   ```python
   if branch.is_system or branch.name == "main":
       raise BranchProtectedError("System branch 'main' cannot be reconfigured")
   ```
   *Result*: Any attempt to archive, unprotect, or modify the protection policy of `main` immediately raises `BranchProtectedError`, which maps to `HTTP 409 Conflict` (per `backend/app/core/exceptions.py:130, 144`). No administrative bypass permission can override this.

#### Server Deletion Path (No Conflict with Protection)
- In `backend/app/modules/server/application/commands/delete_server.py:164-167`:
  Precedent: `cleanup_server_materializations(sid, self._event_bus)` handles worktree cleanup during server deletion `[FACT]`.
- Define `cleanup_server_branches(server_id: str)` [NEW] in `backend/app/modules/versioning/application/commands/cleanup_branches.py` [NEW]:
  ```python
  # backend/app/modules/versioning/application/commands/cleanup_branches.py [NEW]
  async def cleanup_server_branches(server_id: str) -> None:  # [NEW]
      from app.core.persistence.db import database
      from app.modules.versioning.infrastructure.models import ServerBranchModel
      from sqlalchemy import delete

      async with database.session_factory() as session:
          stmt = delete(ServerBranchModel).where(ServerBranchModel.server_id == server_id)
          await session.execute(stmt)
          await session.commit()
  ```
- In `delete_server.py:168`:
  ```python
  with contextlib.suppress(Exception):
      from app.modules.versioning.application.commands.cleanup_branches import cleanup_server_branches
      await cleanup_server_branches(sid)
  ```
- *Mechanism*: Server deletion performs direct SQL row deletion (`DELETE FROM server_branches WHERE server_id = :sid`), which never calls `branch.archive()` and does not violate the check constraint (row deletion is unrestricted). Server deletion succeeds cleanly.

---

### 3.3 Database Migration `b1e2100000023`

- **Revision ID**: `b1e2100000023` `[NEW]`
- **Down Revision**: `b1e2100000022` `[FACT]` (`backend/alembic/versions/b1e2100000022_add_operation_id_to_server_test_runs.py`)
- **Release Compatibility Bump**: `backend/app/core/persistence/db_revision.py:30` updated from `"b1e2100000022"` to `"b1e2100000023"`.

#### Dialect-Neutral DDL & Migration Code
Following the precedent in `b1e2100000019_stage_g_protected_branches.py:30-47`:
```python
"""add is_system column and main protection check constraint to server_branches

Revision ID: b1e2100000023
Revises: b1e2100000022
Create Date: 2026-10-05
"""

import json
import uuid
from datetime import datetime, UTC
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "b1e2100000023"
down_revision: str | None = "b1e2100000022"
branch_labels = None
depends_on = None

def _branch_columns(inspector) -> set[str]:
    return {c["name"] for c in inspector.get_columns("server_branches")}

def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_cols = _branch_columns(inspector)

    # 1. Schema Alterations (batch mode for SQLite & PostgreSQL compatibility)
    with op.batch_alter_table("server_branches") as batch_op:
        if "is_system" not in existing_cols:
            batch_op.add_column(
                sa.Column(
                    "is_system",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )
        # Dialect-neutral CheckConstraint: evaluated against strings, no boolean=integer expressions
        batch_op.create_check_constraint(
            "ck_server_branch_main_not_archived",
            "NOT (name = 'main' AND status = 'archived')",
        )

    # 2. Idempotent Backfill: Eagerly create missing 'main' branches for live servers ONLY
    # Respects UNIQUE(server_id, name) and avoids orphan server_ids
    servers_without_main = conn.execute(
        sa.text(
            """
            SELECT s.id FROM servers s
            WHERE NOT EXISTS (
                SELECT 1 FROM server_branches sb
                WHERE sb.server_id = s.id AND sb.name = 'main'
            )
            """
        )
    ).fetchall()

    now_iso = datetime.now(UTC).isoformat()
    default_policy = json.dumps({
        "require_test_pass": True,
        "allow_direct_commit": True,
        "allow_force_bypass": True,
        "prevent_deletion": True,
    })

    for row in servers_without_main:
        conn.execute(
            sa.text(
                """
                INSERT INTO server_branches (
                    id, server_id, name, head_commit_id, status,
                    is_protected, protection_policy, is_system, created_at
                ) VALUES (
                    :id, :server_id, 'main', NULL, 'created',
                    1, :policy, 1, :created_at
                )
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "server_id": row[0],
                "policy": default_policy,
                "created_at": now_iso,
            }
        )

    # 3. Upgrade existing live 'main' branches to system-protected
    conn.execute(
        sa.text(
            """
            UPDATE server_branches
            SET is_system = 1, is_protected = 1
            WHERE name = 'main'
              AND server_id IN (SELECT id FROM servers)
            """
        )
    )

def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_cols = _branch_columns(inspector)

    with op.batch_alter_table("server_branches") as batch_op:
        batch_op.drop_constraint("ck_server_branch_main_not_archived", type_="check")
        if "is_system" in existing_cols:
            batch_op.drop_column("is_system")
```

#### PostgreSQL Verification Gate
- CI runs SQLite via `pytest` (`backend-tests.yml`) `[FACT]`.
- Dialect neutrality is ensured by:
  1. Using `sa.false()` for the column default (`server_default=sa.false()`).
  2. Avoiding `is_system = 1` in the SQL `CheckConstraint`. Instead, `NOT (name = 'main' AND status = 'archived')` tests only `VARCHAR` equality across all SQL engines.
  3. Marking full PostgreSQL execution as a **Manual Gate** (`[MANUAL GATE]` in CI checklist).

#### Rollback Behavior
- If migration `b1e2100000023` is applied and backend code is rolled back to `b1e2100000022`:
  - `ServerBranchModel` in older code simply ignores the extra `is_system` column `[FACT]`.
  - The check constraint `ck_server_branch_main_not_archived` remains active in the database, continuing to protect `main` from archiving even under older code.
  - Downgrading via `alembic downgrade -1` cleanly removes the constraint and drops the column.

---

### 3.4 W6: Files API Internal-Directory Guard

#### Choke Point & Normalization
Fold the check directly into `_resolve_server_file_path` (`backend/app/api/v1/routers/files.py:35-72`) `[FACT]`. No parallel jail or duplicate path resolution is created.

```python
INTERNAL_PROTECTED_ROOT_DIRS: frozenset[str] = frozenset({
    ".onx",
    ".onx-manager",
    ".mcsmanager",
})  # [NEW]
```

#### Normalization Procedure:
1. Normalize Windows backslashes: `clean_rel = relative_path.replace("\\", "/").lstrip("/") if relative_path else ""`.
2. Resolve target: `target_path = (resolved_root / clean_rel).resolve()`.
3. Verify jail:
   ```python
   try:
       rel = target_path.relative_to(resolved_root)
   except ValueError:
       raise HTTPException(status_code=403, detail="Path escapes server root directory")
   ```
4. Extract first component:
   ```python
   parts = rel.parts
   first_component = parts[0].lower() if parts and parts[0] != "." else ""
   ```

#### Route Enforcement Matrix (All 7 Endpoints):
| Endpoint | Method | Path | Operation Type | Internal Protected Dir Action | `.env` Action | Admin Bypass? |
|---|---|---|---|---|---|---|
| `list_files` | `GET` | `/api/v1/servers/{id}/files` | Read | Allow listing target; **Omit** internal dirs from root listing | **Omit** from root listing | No |
| `read_file_content` | `GET` | `/api/v1/servers/{id}/files/content` | Read | **Allow** | 403 Forbidden | No |
| `download_file` | `GET` | `/api/v1/servers/{id}/files/download` | Read | **Allow** | 403 Forbidden | No |
| `write_file_content` | `PUT` | `/api/v1/servers/{id}/files/content` | Mutation | **403 Forbidden** | 403 Forbidden | No |
| `delete_file_or_dir` | `DELETE` | `/api/v1/servers/{id}/files` | Mutation | **403 Forbidden** | 403 Forbidden | No |
| `upload_file` | `POST` | `/api/v1/servers/{id}/files/upload` | Mutation | **403 Forbidden** | 403 Forbidden | No |
| `create_directory` | `POST` | `/api/v1/servers/{id}/files/mkdir` | Mutation | **403 Forbidden** | **403 Forbidden** | No |

#### Guard Specifics:
1. **Mutation Denial**:
   In `_resolve_server_file_path`, add parameter `operation: str = "read"`:
   ```python
   if operation in ("write", "delete", "upload", "mkdir"):
       if first_component in INTERNAL_PROTECTED_ROOT_DIRS:
           raise HTTPException(
               status_code=403,
               detail=f"Modification of internal directory '{first_component}' is forbidden",
           )
   ```
2. **Deeply Nested Directories Remain Accessible**:
   - `relative_path = "plugins/my_plugin/.onx"`: `first_component` is `"plugins"`. Not in `INTERNAL_PROTECTED_ROOT_DIRS`. Access allowed.
   - `relative_path = "world/data/.mcsmanager"`: `first_component` is `"world"`. Not in `INTERNAL_PROTECTED_ROOT_DIRS`. Access allowed.
3. **Traversal Forms Blocked**:
   - `config/../.onx` resolves to `.onx` -> `first_component == ".onx"` -> mutation rejected with 403.
   - `./.onx/server.json` resolves to `.onx/server.json` -> `first_component == ".onx"` -> mutation rejected with 403.
   - `.onx/../.onx/config` resolves to `.onx/config` -> `first_component == ".onx"` -> mutation rejected with 403.
4. **`.env` Single Behavior Choice**:
   - In `list_files`: filter out entries where `item.name.lower() == ".env"` (as well as `INTERNAL_PROTECTED_ROOT_DIRS`).
   - In `create_directory` (`mkdir`): call `_assert_not_sensitive(target_path)`. If user calls `POST /mkdir?path=.env`, it raises `HTTP 403 Forbidden`.
   - `FileEntryResponse` (`backend/app/api/v1/schemas/files.py:10-18`) retains its exact existing fields (`name`, `path`, `is_dir`, `size`). No `is_sensitive` field is added.
5. **Accepted-Risk Statement (Read Access to `.onx-manager/server.json`)**:
   - Reading `.onx-manager/server.json` via `GET /content` or `GET /download` returns the server identity document (`{"server_id": "<uuid>", "provider": "<provider>"}`).
   - *Risk Evaluation*: The `server_id` UUID is already public in the URL path (`/api/v1/servers/{server_id}/...`), and the provider badge is public metadata exposed in `GET /api/v1/servers/{server_id}`. No secret keys, passwords, or tokens reside in `.onx-manager/server.json`.
   - *Defense against Bug 3*: Bug 3 occurred because deletion or corruption of `.onx-manager/server.json` caused the backend on restart to misidentify an existing server as an unmanaged third-party directory, minting a new UUID and destroying state. By rejecting all mutations (`write`, `delete`, `upload`, `mkdir`) with HTTP 403, server identity cannot be tampered with or destroyed via the Files API.

---

## 4. Affected Components & Interfaces

### 4.1 Modified Files & Identifiers
- `backend/app/modules/versioning/domain/entities.py`:
  - `ServerBranch.is_system: bool = False` `[NEW]`
  - `ServerBranch.archive()`: add system main guard
  - `ServerBranch.unprotect()`: add system main guard
- `backend/app/modules/versioning/infrastructure/models.py`:
  - `ServerBranchModel.is_system = Column(Boolean, nullable=False, default=False)` `[NEW]`
- `backend/app/modules/versioning/infrastructure/repository.py`:
  - `_branch_to_domain`: map `is_system`
  - `save_branch`: persist `is_system`
- `backend/app/modules/versioning/application/commands/create_branch.py`:
  - `CreateBranchCommand.is_system: bool = False` `[NEW]`
  - `CreateBranchCommand.idempotent: bool = False` `[NEW]`
  - `CreateBranchHandler.handle`: idempotent handling and system protection initialization
- `backend/app/modules/versioning/application/commands/archive_branch.py`:
  - `ArchiveBranchHandler._execute`: reject `branch.is_system or branch.name == "main"` with `BranchProtectedError`
- `backend/app/modules/versioning/application/commands/branch_protection.py`:
  - `RemoveBranchProtectionHandler._execute`: reject `branch.is_system or branch.name == "main"` with `BranchProtectedError`
  - `SetBranchProtectionHandler._execute`: reject `branch.is_system or branch.name == "main"` with `BranchProtectedError`
- `backend/app/modules/server/application/services/filesystem_reconciliation.py`:
  - `FilesystemReconciliationService.__init__`: accept `event_bus: EventBus | None = None`
  - `_handle_import` and `_handle_adopt`: publish `ServerCreatedEvent` via `self._event_bus`
- `backend/app/api/v1/routers/files.py`:
  - `INTERNAL_PROTECTED_ROOT_DIRS` `[NEW]`
  - `_resolve_server_file_path`: add `operation` parameter, perform separator normalization, enforce 403 on internal root mutations
  - `list_files`: filter internal directories and `.env` from root listing
  - `create_directory`: call `_assert_not_sensitive(target_path)` to close `.env` mkdir gap
- `backend/app/core/persistence/db_revision.py`:
  - `RELEASE_MINIMUM_DB_REVISION = "b1e2100000023"`

### 4.2 New Files & Identifiers
- `backend/alembic/versions/b1e2100000023_add_system_branch_protection.py` `[NEW]`: Alembic migration script.
- `backend/app/modules/versioning/application/subscribers.py` `[NEW]`: Contains `ServerCreatedSubscriber` `[NEW]`.
- `backend/app/modules/versioning/application/commands/cleanup_branches.py` `[NEW]`: Contains `cleanup_server_branches(server_id: str)` `[NEW]`.

---

## 5. Failure & Edge Cases

1. **Orphan Branch Rows**:
   - Dev DB holds 129 orphan branch rows from past uncleaned test runs `[FACT]`.
   - Backfill migration uses `WHERE server_id IN (SELECT id FROM servers)`, completely ignoring orphan rows.
2. **Double Server Creation / Import Race**:
   - Handled via `CreateBranchCommand(..., idempotent=True)`. If `main` already exists, returns existing branch ID with `already_existed=True` instead of raising 409 Conflict.
3. **Headless Readers**:
   - If user visits Versioning page on a newly created server with 0 commits, `get_branch_history` returns `[]`, `scan_live_changes` returns `{"changes": [], "auto_commit": None}`, and UI renders empty commits notice. Zero crashes or 404s.
4. **Server Deletion**:
   - When server is deleted, `cleanup_server_branches` issues raw SQL `DELETE FROM server_branches WHERE server_id = :sid`. It does NOT call `archive()` and does NOT trigger the check constraint against `status = 'archived'`.
5. **Windows Path Separators**:
   - Path `.onx\server.json` is normalized to `.onx/server.json` before resolving, ensuring case-insensitive and slash-agnostic 403 blocking on Windows and Linux alike.

---

## 6. Tests & Verification Matrix

All tests must be run sequentially per `.ai/RULES/testing-and-verification.md` (`pytest -v backend/tests/...` without `-n auto`).

### 6.1 Eager Provisioning & Lifecycle Tests
- `test_create_server_eagerly_creates_main`: Create server via `CreateServerHandler`; verify `main` branch exists with `is_system=True`, `is_protected=True`, `status="created"`, `head_commit_id=None`.
- `test_import_server_eagerly_creates_main`: Import server via `ImportServerHandler`; verify `main` branch eagerly exists.
- `test_reconciliation_import_eagerly_creates_main`: Reconcile directory without DB row; verify `ServerCreatedEvent` published and `main` branch created.
- `test_reconciliation_adopt_eagerly_creates_main`: Reconcile directory matching DB row; verify `main` branch created if missing.
- `test_idempotent_create_branch`: Issue duplicate `CreateBranchCommand(..., idempotent=True)`; verify success without 409.

### 6.2 Protection Invariants Tests
- `test_archive_main_branch_forbidden_via_api`: `POST /api/v1/servers/{id}/branches/main/archive` returns `HTTP 409 Conflict` (even with admin permissions).
- `test_unprotect_main_branch_forbidden_via_api`: `DELETE /api/v1/servers/{id}/branches/main/protection` returns `HTTP 409 Conflict`.
- `test_configure_main_branch_protection_forbidden_via_api`: `PUT /api/v1/servers/{id}/branches/main/protection` returns `HTTP 409 Conflict`.
- `test_domain_archive_main_raises`: Directly calling `branch.archive()` on `main` raises `BranchProtectedError`.
- `test_domain_unprotect_main_raises`: Directly calling `branch.unprotect()` on `main` raises `BranchProtectedError`.
- `test_delete_server_cleans_system_main`: Delete server via `DeleteServerHandler`; verify server and its `main` branch are removed from the database without error.

### 6.3 Commit Compatibility Tests (Regression Shield)
- `test_direct_commit_to_system_main_succeeds`: Call `CreateCommitHandler` targeting headless system `main`; verify initial commit is created and status becomes `ACTIVE`.
- `test_auto_commit_live_changes_to_system_main_succeeds`: Call `AutoCommitLiveChangesHandler` on system `main`; verify live changes commit successfully without `BranchProtectedError`.
- `test_import_review_auto_commit_to_system_main_succeeds`: Verify `POST /api/v1/servers/{id}/versioning/import-review/auto-commit` targeting `main` succeeds.

### 6.4 Files API Guard Matrix Tests
- Matrix of 3 directory names (`.onx`, `.onx-manager`, `.mcsmanager`) and case variants (`.ONX`, `.Onx-Manager`) across all 4 mutating verbs:
  - `PUT /api/v1/servers/{id}/files/content?path=.onx/foo` -> `403 Forbidden`
  - `DELETE /api/v1/servers/{id}/files?path=.onx-manager` -> `403 Forbidden`
  - `POST /api/v1/servers/{id}/files/upload?path=.mcsmanager` -> `403 Forbidden`
  - `POST /api/v1/servers/{id}/files/mkdir?path=.onx` -> `403 Forbidden`
- Traversal & normalization tests:
  - `PUT /content?path=config/../.onx/test` -> `403 Forbidden`
  - `POST /mkdir?path=./.onx` -> `403 Forbidden`
  - `PUT /content?path=.onx\test` (Windows slash) -> `403 Forbidden`
- Read operations allowed:
  - `GET /content?path=.onx-manager/server.json` -> `200 OK`
  - `GET /download?path=.onx-manager/server.json` -> `200 OK`
- Directory listing tests:
  - `GET /api/v1/servers/{id}/files` (root) -> results omit `.onx`, `.onx-manager`, `.mcsmanager`, and `.env`.
  - `GET /api/v1/servers/{id}/files?path=.onx` -> returns entries inside `.onx` (read allowed).
- Deeply nested allowed:
  - `PUT /content?path=plugins/my_plugin/.onx/config.json` -> `200 OK`
  - `POST /mkdir?path=world/data/.mcsmanager` -> `201 Created`
- `.env` gap closures:
  - `GET /api/v1/servers/{id}/files` -> `.env` is omitted from root list.
  - `POST /api/v1/servers/{id}/files/mkdir?path=.env` -> `403 Forbidden`.

### 6.5 Migration Tests
- `test_migration_up_and_down`: Execute upgrade to `b1e2100000023` and downgrade back to `b1e2100000022`.
- `test_migration_backfill_idempotent`: Run backfill twice; verify no duplicate `main` rows or constraint violations.
- `test_migration_ignores_orphans`: Verify existing orphan branch rows are not modified.
- `test_check_db_revision_passes`: Run `scripts/check-db-revision` against the new head.

---

## 7. Out of Scope (Explicitly Parked)

The following items were rejected/parked during reviews of Revision 2 and are **strictly excluded** from this design spec:
1. **Restricting Direct Commits to `main`**: No restrictions on direct commits, no genesis rules, no auto-commit exemptions.
2. **Merge-to-Main**: No fast-forward merges, no divergent merges, no merge schemas, no LCA graph algorithms, no merge test-gates, no `MergeCommitsResponse` reshaping.
3. **Branch-Aware Files Page**: No worktree root switching, no branch selector on `ServerFilesPage`, no persistent vs transient folder classification.
4. **Commit-from-Worktree**: No `CommitFromWorktreeCommand`, no worktree commit dialog, no materialization editing promotion to commits.
5. **Materialization Cap & BUG-V04**: No worktree limits in `AppSettings`, no `InsufficientDiskSpaceError`, no stage file cleanup fixes.
6. **Security Batch S1**: Zero overlap with JVM argument validation, `server.properties` parsing, key file permissions, or `permissions.yaml` edits.

---

## 8. Governance Gate Result

- **Lane**: Lane E (Future Product) with Lane A safety characteristics.
- **Decision Level**: D2 (Major) — Schema alteration to `server_branches`, new migration `b1e2100000023`, API security hardening in Files API.
- **Roadmap Sync**: Required upon promotion from Design to Build.
- **CI Quality Gates Verification**: All 6 real quality gates from `scripts/` must pass:
  1. `scripts/check-db-revision`: Passes after bumping `RELEASE_MINIMUM_DB_REVISION = "b1e2100000023"`.
  2. `scripts/check-ruff-baseline`: Clean.
  3. `scripts/check-version-propagation`: Clean.
  4. `scripts/check-route-contract`: Clean (no routes added or removed; existing route signatures unchanged).
  5. `scripts/check-ps1-bom`: Clean.
  6. `scripts/check-stray-db`: Clean.

---

## 9. Review Resolution Mapping Table

| Finding ID | Review Concern | Resolution in this Spec | Spec Section Reference |
|---|---|---|---|
| **F10** | Migration batch mode, dialect neutrality, duplicate inserts on orphan servers | `op.batch_alter_table` used; dialect-neutral `CheckConstraint` on strings; backfill filters `WHERE s.id NOT IN ...` for live servers only. | Section 3.3 |
| **F11** | Files guard matching first component; reads allowed; list filter consistency | Guard inspects `rel.parts[0].lower()`; reads (`GET /content`, `GET /download`, `GET /files?path=...`) allowed; root listing omits internal dirs. | Section 3.4 |
| **F12** | Eager `main` status created with `head=None` | Eager `main` created with `BranchStatus.CREATED` matching `create_branch.py:102`. | Section 3.1 |
| **F13** | Layering violation (`server` -> `versioning`) & duplicated file jail | Decoupled via `EventBus` (`ServerCreatedEvent` -> `ServerCreatedSubscriber`); guard folded directly into `_resolve_server_file_path`. | Sections 3.1 & 3.4 |
| **F19** | Work-item labels D1–D7 colliding with governance D0–D3 | Disambiguated: work items labeled W1, W3, W6. Governance decision level is D2. | Sections 1 & 8 |
| **N4** | Migration CHECK breaks on PostgreSQL (`boolean = integer`) | Checked constraint formulated as `NOT (name = 'main' AND status = 'archived')` (valid SQL on both SQLite and PostgreSQL); column uses `sa.false()`. | Section 3.3 |
| **N9** | Rule Zero violations (unmarked new identifiers) | Every new identifier (`INTERNAL_PROTECTED_ROOT_DIRS`, `cleanup_server_branches`, `ServerCreatedSubscriber`, etc.) explicitly marked `[NEW]` with full signature. | Sections 3 & 4 |
| **N10 (g)** | Inconsistent `.env` behavior on list vs mkdir | Omitted from root `list_files`; rejected with 403 on `mkdir`. No `is_sensitive` field added to `FileEntryResponse`. | Section 3.4 |
| **N10 (h)** | Readable `.onx-manager/server.json` security justification | Documented accepted risk: `server_id` and `provider` are public; read does not leak secrets; write/delete block prevents Bug 3. | Section 3.4 |
| **N10 (i)** | W6 header label drift | Fixed: W6 covers only Files API guard. W7–W10 parked out of scope. | Sections 3.4 & 7 |

---

## 10. UNKNOWN List

1. **PostgreSQL Automated Testing in CI**: CI environment (`backend-tests.yml`) executes SQLite exclusively. Dual-dialect PostgreSQL compatibility is verified by inspection of SQLAlchemy dialect compilation, but live PostgreSQL verification remains a manual gate `[UNKNOWN]`.
2. **Reconciliation Dry-Run Event Publication**: Whether `FilesystemReconciliationService(dry_run=True)` should suppress `ServerCreatedEvent` publication. Current design assumes dry-run makes no database changes and publishes no creation events `[ASSUMPTION]`.

---

## 11. Open Owner Questions (Listed, Not Answered)

The following design decisions are surfaced for owner ruling and are **not** decided by the author:
1. *PostgreSQL CI Pipeline*: Should a PostgreSQL container service be added to `backend-tests.yml` to automate dual-dialect migration verification, or is manual gate verification acceptable for Lane E?
2. *Read Access Policy on Internal Control Dirs*: Should `GET /files?path=.onx` (explicit query into internal directories) remain accessible to holders of `server.{id}.files`, or should explicit read navigation into `.onx` also be restricted to `admin:full`?
3. *Future Merge Pipeline Timing*: When Part B (Merge-to-Main) is un-parked, should it require automated test preflight execution or permit fast-forward merges based solely on manual review?
