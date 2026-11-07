# SPEC-2026-10-19-BRANCH-HEAD-CAS-01 — Branch-Head Atomicity (CAS)

Release Critical track (Release Critical)
Decision level: D1
Status: DRAFT v2
Changelog: v2 applies independent-review changes R1–R9 (see "Change Log (v1 → v2)").

---

## Change Log (v1 → v2)

| Item | Change in v2 | Where |
|---|---|---|
| R1 | `ConflictError` is re-raised before any lock/busy substring test in both retry loops; lock detection is type-gated to `OperationalError` so branch names never participate in the retry decision; new `locked-main` no-retry/409 tests | §Current Behavior/Retry loops; §Proposed Change 3, 4; §Tests |
| R2 | Mandatory two-engine, file-backed SQLite experiment for the losing CAS surface; preferred mapping (including `SQLITE_BUSY_SNAPSHOT`) to `ConflictError` 409 with no rebase; HALT rule | §Proposed Change 2a; §Tests |
| R3 | CAS predicate now excludes `archived`; `created → active` SET retained; fake returns `False` for archived; archived-race test | §Proposed Change 2, 6; §Tests |
| R4 | Full `save_branch` / `head_commit_id` writer audit; chosen fix is to stop writing the head on `save_branch`'s update path; stale-metadata regression test | §Current Behavior/Audit; §Proposed Change 5; §Tests |
| R5 | Reserved spec §3.4:386 (repository raises) explicitly superseded by W8:532–534 (bool + caller raises); CAS-before-`save_commit` flagged as a deliberate deviation from W8:530–532 | §Interfaces & Contracts |
| R6 | Test plan adds real-DB two-engine handler test, second-commit test, merge CAS-loss test, archived-race test, `CREATED → ACTIVE` assertion, no-stale-persist test; `test_stage_b_version_control.py` added to the targeted command; `-k versioning` explicitly rejected | §Tests |
| R7 | Both required import edits in `repository.py` (`update`, `BranchStatus`) are listed; `synchronize_session="fetch"` chosen; stale domain object must never be persisted | §Proposed Change 2; §Affected Components |
| R8 | Mutation checklist rewritten so every mutation maps to a named test | §Tests/Mutation checklist |
| R9 | Line refs corrected; retry-count wording made consistent; false "`sqlalchemy.update` already imported" statement removed; root-cause audit names `branch_protection.py` and `archive_branch.py` | Throughout |

---

## Goal

Make **every branch-head advance** in the versioning module atomic under
concurrency, so that two overlapping commit operations on the same branch
cannot both move `server_branches.head_commit_id` from the same prior value
and leave one of the resulting commits unreachable from the branch pointer.

Deliverable (build phase, not this document): an optimistic compare-and-swap
(CAS) repository primitive
`advance_branch_head_optimistic(branch_id, new_head, expected_head) -> bool`
whose name and match predicate are reserved in
`docs/design/SPEC-2026-10-05-BRANCH-AWARE-FILES-AND-PROTECTED-MAIN-01.md`
§3.4 (`docs/design/SPEC-2026-10-05-BRANCH-AWARE-FILES-AND-PROTECTED-MAIN-01.md:384`)
and Part C §3.2/W8
(`docs/design/SPEC-2026-10-05-BRANCH-AWARE-FILES-AND-PROTECTED-MAIN-01.md:532-534`),
and route `CreateCommitHandler` and `MergeCommitsHandler` through it.

D1 scope decision: F1-1 also closes the **blind head write** in
`SQLVersioningRepository.save_branch`. It is not enough to fix the two commit
handlers while metadata commands can still persist a stale in-memory
`head_commit_id` through the generic update path.

This spec covers exactly batch **F1-1**. It does **not** design or implement
Part A, Part B, or Part C of
`SPEC-2026-10-05-BRANCH-AWARE-FILES-AND-PROTECTED-MAIN-01.md`; it only reuses
the reserved method name/contract so later work can call it.

---

## Current Behavior

### Head-advance sites

`CreateCommitHandler`
(`backend/app/modules/versioning/application/commands/create_commit.py`):

1. Resolves/creates the branch and reads its head
   (`create_commit.py:119-127`). `branch.head_commit_id` is the value read into
   memory.
2. Creates a COW world snapshot and persists it (`create_commit.py:160-171`).
3. Builds the commit with `parent_commit_id=branch.head_commit_id`
   (`create_commit.py:184-194`) and, when a head exists, calls
   `commit.validate_parent(parent_commit)` (`create_commit.py:195-197`).
4. `await versioning_repo.save_commit(commit)` (`create_commit.py:198`).
5. Mutates the in-memory branch and persists it:
   `branch.advance_head(commit_id)` then
   `await versioning_repo.save_branch(branch)` (`create_commit.py:201-202`).

`MergeCommitsHandler`
(`backend/app/modules/versioning/application/commands/merge_commits.py`):

1. Reads the target branch (`merge_commits.py:86-95`).
2. Builds the merge commit (`merge_commits.py:139-149`).
3. `branch.advance_head(new_commit_id)` (`merge_commits.py:152`), then
   `save_commit` + `save_branch` (`merge_commits.py:155-156`).

`SQLVersioningRepository.save_branch`
(`backend/app/modules/versioning/infrastructure/repository.py:70-97`) is a
read-modify-write with no predicate. On the update path it unconditionally
assigns `model.head_commit_id = branch.head_commit_id`
(`repository.py:92`). There is no `WHERE head_commit_id = ...` guard, so the
last writer wins.

Consequence (`[FACT]` at the code level): if two `CreateCommitHandler` calls
both read head `H`, both build commits whose parent is `H`, both
`save_commit`, and both `save_branch`, the second `save_branch` overwrites the
first, and the first commit is no longer referenced by any branch pointer.
The same lost-update path exists through `merge_commits.py:151-156`.

### Branch-head writer / `save_branch` caller audit (R4)

Production callers of `save_branch`:

| Caller | Path | Writes head today? | Legitimate? | F1-1 treatment |
|---|---|---|---|---|
| `create_branch.py:104` | `CreateBranchHandler._execute` | Yes (insert, `head_commit_id=command.head_commit_id`, `create_branch.py:97-104`) | **Yes** — branch creation from a validated parent commit (`create_branch.py:87-93`) | Keep insert path writing the head |
| `create_commit.py:127` | Branch auto-create | Yes (insert, head is `None`) | Yes (creation, not an advance) | Keep insert path |
| `create_commit.py:202` | Commit head advance | Yes (update, blind) | No — this is the defect | Replace with CAS; delete this tail |
| `merge_commits.py:156` | Merge head advance | Yes (update, blind) | No — this is the defect | Replace with CAS; delete this tail |
| `branch_protection.py:68` | `SetBranchProtectionHandler` | Yes (update, blind, but value is stale-read) | **No** — protection is metadata only (`branch.protect(policy)` at `:67`) | Must not write head |
| `branch_protection.py:131` | `RemoveBranchProtectionHandler` | Yes (update, blind, stale-read) | **No** — unprotect is metadata only (`branch.unprotect()` at `:130`) | Must not write head |
| `archive_branch.py:89` | `ArchiveBranchHandler` | Yes (update, blind, stale-read) | **No** — archive changes status only (`branch.archive()` at `:88`) | Must not write head |

Other production writers of `server_branches.head_commit_id`:

| Location | Kind | Notes |
|---|---|---|
| `repository.py:83` | ORM insert assignment | Legitimate creation; keep |
| `repository.py:92` | ORM update assignment | The blind update; removed by R4 |
| `alembic/versions/b1e2100000013_add_server_versioning_tables.py:27` | Schema creation | Column definition only |
| `alembic/versions/b1e2100000015_add_stage_b_versioning_tables.py:42-43` | Data backfill | Updates `status` only, not `head_commit_id` |
| `auto_commit_live_changes.py:110-157` | Read + delegation | Reads the head, then delegates to `CreateCommitHandler` at `:130-142`; no direct write, inherits CAS |
| `revert_import_review.py:165-175` | Delegation | Delegates to `CreateCommitHandler`; no direct write, inherits CAS |
| `create_materialization.py:91-102`, `get_branch_history.py:59-63`, `scan_live_changes.py:90-97` | Reads | No head write |
| API router/schema (`versioning.py:113-120`, `schemas/versioning.py:12,19`) | Command input | Passes `head_commit_id` into `CreateBranchCommand`; no direct DB write |

Test/helper callers of `save_branch` (all seed data unless noted):

| Caller | Kind | Notes |
|---|---|---|
| `tests/api/test_stage_b_versioning_api.py:81,228` | insert | Seeds branches (one with head) |
| `tests/api/test_stage_c_versioning_api.py:102` | insert | Seeds branch with head |
| `tests/api/test_stage_g_branch_protection_api.py:87,123,199` | insert | Seeds branches |
| `tests/application/test_promote_and_rollback.py:75` | fake method | In-memory fake |
| `tests/application/test_promote_and_rollback.py:332` | insert | Seeds branch with head |
| `tests/application/test_promote_commit_gating.py:61` | fake method | In-memory fake |
| `tests/application/test_stage_b_version_control.py:276,335` | insert | Seeds branches with head |
| `tests/application/test_stage_c_materialization_commands.py:116` | insert | Seeds branch with head |
| `tests/application/test_stage_c_materialization_commands.py:220-221` | **update** | Test manually sets `branch.head_commit_id = "c-next"` and calls `save_branch` to advance the head. This is not a production caller; the build must migrate this seed to `advance_branch_head_optimistic(...)` (or an equivalent CAS) because R4 makes the update path metadata-only for the head. |

There is no other raw SQL/ORM writer of `server_branches.head_commit_id` in
`backend/` (`[FACT]`, grep of `ServerBranchModel`, `head_commit_id`,
`server_branches`). The in-memory fakes and domain tests mutate the Python
object only; they are not persistence writers.

Root cause is twofold: (a) the commit/merge handlers use a blind
read-modify-write instead of a predicate; (b) the generic update path in
`save_branch` also writes the head for metadata-only callers, so
`branch_protection.py:68`, `branch_protection.py:131`, and
`archive_branch.py:89` can clobber a head they never intended to change.

### Retry loops (R1)

Both handlers wrap `_execute` in a retry loop that retries **only** when the
exception text contains `"locked"` or `"busy"` (case-insensitive), up to 3
attempts with exponential backoff: `create_commit.py:67-85`,
`merge_commits.py:48-63`. Each attempt uses a fresh
`database.session_factory()` and commits once at the end
(`create_commit.py:78`, `merge_commits.py:56`). This loop exists to absorb
SQLite write-lock contention, not logical conflicts.

Defect: the retry decision is a raw substring test over `str(exc)`. Several
application exceptions interpolate `branch.name`, for example:

- `create_commit.py:129` — archived branch `ConflictError`
- `merge_commits.py:95` — archived branch `ConflictError`
- `merge_commits.py:91-93` — missing branch `NotFoundError`

A branch named `locked-main` therefore makes a logical 409 (or a 404) look like
a transient database lock and causes up to 3 attempts.

### Persistence / SQLite

- `DatabaseEngine.init` sets `PRAGMA journal_mode=WAL`,
  `PRAGMA busy_timeout=30000`, `PRAGMA synchronous=NORMAL`
  (`backend/app/core/persistence/db.py:82-95`) and passes
  `connect_args={"timeout": 30.0, "check_same_thread": False}` (`db.py:54`).
- `AsyncSession` uses `expire_on_commit=False` (`db.py:97-101`); one
  transaction spans the whole handler attempt and is committed once
  (`create_commit.py:70-78`).
- The autouse test fixture creates `sqlite+aiosqlite://` (in-memory), which
  SQLAlchemy binds with `StaticPool` (`backend/tests/conftest.py:47-54`;
  verified this session: `type(engine.pool).__name__ == "StaticPool"`). It
  therefore has **one shared connection** and cannot model two independent
  writers. New concurrency tests must use a file-backed engine with two
  engines/connections.

### Coverage gap (V07)

`create_commit.py:195-197` calls `commit.validate_parent(parent_commit)`, but
no handler-level test proves the call is reached. The only existing ancestor
tests exercise `ServerCommit.validate_parent` directly
(`backend/tests/domain/test_stage_a_domain_invariants.py:306-351`).

### Not needed

- No migration: `server_branches.head_commit_id` is
  `Column(String(36), nullable=True)`
  (`backend/app/modules/versioning/infrastructure/models.py:33`); `status` is
  an existing non-null column (`models.py:34`). The current Alembic head is
  `b1e2100000022` (verified this session via
  `ScriptDirectory.get_current_head()`, 42 revisions). `[FACT]`
- No new dependency: SQLAlchemy is already a dependency.
- Correction to v1: `sqlalchemy.update` is **not** imported at module level in
  `repository.py`; line 3 is `from sqlalchemy import desc, select`. `update`
  must be added. `BranchStatus` is also not imported there; it is currently
  imported locally inside `_branch_to_domain` (`repository.py:569`) and must be
  added to the module-level value-object import for the CAS SET/WHERE.

---

## Proposed Change

### 1. New abstract repository method

Add to `VersioningRepository`
(`backend/app/modules/versioning/domain/repository.py`, branch methods at
lines 21-36) — signature exactly as reserved:

```python
@abstractmethod
async def advance_branch_head_optimistic(
    self, branch_id: str, new_head: str, expected_head: str | None
) -> bool:
    ...
```

Returning `bool` (rather than raising in the repository) is the R5
reconciliation: the repository performs the CAS and reports success; the
application handler decides the user-facing error and retry policy. This keeps
the persistence primitive reusable by the future Part B/C callers named in the
reserved spec.

### 2. SQL implementation (R2, R3, R7)

In `SQLVersioningRepository`
(`backend/app/modules/versioning/infrastructure/repository.py`, next to
`save_branch` at lines 70-97):

```python
async def advance_branch_head_optimistic(
    self, branch_id: str, new_head: str, expected_head: str | None
) -> bool:
    conditions = [
        ServerBranchModel.id == branch_id,
        ServerBranchModel.status != BranchStatus.ARCHIVED.value,
    ]
    if expected_head is None:
        conditions.append(ServerBranchModel.head_commit_id.is_(None))
    else:
        conditions.append(ServerBranchModel.head_commit_id == expected_head)

    stmt = (
        update(ServerBranchModel)
        .where(*conditions)
        .values(head_commit_id=new_head, status=BranchStatus.ACTIVE.value)
        .execution_options(synchronize_session="fetch")
    )
    try:
        result = await self._session.execute(stmt)
        await self._session.flush()
    except OperationalError as exc:
        if _is_sqlite_busy_snapshot(exc):
            return False
        raise
    return result.rowcount == 1
```

Required import edits in this file:

1. `repository.py:3` — `from sqlalchemy import desc, select` becomes
   `from sqlalchemy import desc, select, update`.
2. `repository.py:18-28` — add `BranchStatus` to the
   `app.modules.versioning.domain.value_objects` import block (currently absent
   at module level; only imported locally at `repository.py:569`).
3. Add `from sqlalchemy.exc import OperationalError` (for the R2 mapping).

Notes:

- Predicate is the reserved head predicate plus the R3 archived guard
  (`status != 'archived'`, equivalent to `status IN ('created','active')`).
  The `status` column is non-null (`models.py:34`), so `!=` is safe.
- `status = 'active'` remains in the SET clause so the existing
  `created → active` transition currently done by `ServerBranch.advance_head`
  (`entities.py:111-118`) is preserved. This is a deliberate, documented
  extension of the reserved SET clause; callers must not perform a second
  status write.
- `synchronize_session="fetch"` keeps ORM identity-map instances coherent for
  the bulk `UPDATE`. The **domain** `ServerBranch` object is a separate
  dataclass and remains stale; after a successful CAS the handler must not
  persist that stale object (see §5 and R6f).
- `rowcount == 1` is the success condition; `rowcount == 0` covers missing
  branch, stale head, and archived branch.
- `_is_sqlite_busy_snapshot(exc)` is added only if the R2 experiment observes
  a snapshot-busy `OperationalError`. It must use the robust discriminator
  observed there (expected `sqlite_errorcode == sqlite3.SQLITE_BUSY_SNAPSHOT`
  / `sqlite_errorname == "SQLITE_BUSY_SNAPSHOT"`; extended code 517). If no
  robust discriminator is exposed, **HALT** — do not match on the generic
  `"database is locked"` text, because that would convert ordinary transient
  locks into 409s and disable the existing retry loop.

### 2a. Mandatory SQLite two-engine experiment (R2)

Before implementing the exception mapping, the builder MUST run a file-backed
experiment (kept as a test in
`backend/tests/infrastructure/test_versioning_repository_cas.py`):

1. Create `tmp_path / "cas.sqlite3"` and two **independent** async engines with
   `sqlite+aiosqlite:///{path}`, `connect_args={"timeout": 30.0}`, and the same
   `PRAGMA journal_mode=WAL` / `busy_timeout=30000` / `synchronous=NORMAL`
   hooks as `db.py:82-95`.
2. Create the schema from `Base.metadata`, then seed one branch with a known
   head `H`.
3. Open session A and read the branch (this acquires WAL snapshot `S`).
4. Open session B, execute the raw CAS `UPDATE ... WHERE head = H`, and commit.
5. In session A, execute the same raw CAS with expected head `H`.
6. Record exactly what session A sees: `rowcount == 0` (`False`) or
   `OperationalError`; if `OperationalError`, record the class, message,
   `exc.orig` type, `sqlite_errorcode`, `sqlite_errorname`, and cause chain.

Preferred behavior:

- A losing CAS, including a snapshot-busy loss on the head `UPDATE`, MUST
  surface as `ConflictError` (HTTP 409) and MUST NOT rebase or retry.
- If the losing writer sees `rowcount == 0`: return `False`; handler raises
  `ConflictError`. No extra code.
- If the losing writer sees `OperationalError` with a robust
  `SQLITE_BUSY_SNAPSHOT` discriminator: catch only that code/name in the CAS
  and return `False`; the handler then raises `ConflictError`, and the retry
  loop re-raises it before any lock test (R1).
- Ordinary `SQLITE_BUSY`/lock-timeout errors (not a snapshot-busy CAS loss)
  MUST still be retried by the existing handler loop.

HALT rule: if the experiment shows anything else — e.g. the stale CAS succeeds
(`rowcount == 1`), a silent overwrite, an exception that cannot be reliably
distinguished from ordinary lock contention, or a different error class — the
builder MUST stop and report to the owner. Do not improvise, broaden the catch,
or change the retry policy.

`[UNVERIFIED]` until the experiment is run: under WAL, a read-then-write
upgrade after another writer commits is expected to raise
`SQLITE_BUSY_SNAPSHOT` immediately (the busy handler does not wait for this
case), but this was not reproduced in v1. The experiment decides.

### 3. `CreateCommitHandler` — CAS-first, then save (R1, R5)

In `_execute`, after branch resolution (`create_commit.py:119-158`), capture the
expected head:

```python
expected_head = branch.head_commit_id
```

After `validate_parent` (`create_commit.py:195-197`) and **before**
`save_commit` (`create_commit.py:198`), replace the current
`advance_head` + `save_branch` tail (`create_commit.py:200-202`) with:

```python
updated = await versioning_repo.advance_branch_head_optimistic(
    branch.id, commit_id, expected_head
)
if not updated:
    raise ConflictError(
        f"Concurrent commit detected for branch id '{branch.id}': head moved "
        f"from {expected_head!r} while the commit was being created. "
        "Re-read and retry."
    )
await versioning_repo.save_commit(commit)
```

Order rationale (R5): the CAS is executed before `save_commit` so that a losing
attempt performs no commit write at all (no orphan commit row even in
non-transactional/in-memory repositories). On SQLite the CAS and the `INSERT`
are in the same session transaction and commit together
(`create_commit.py:70-78`, `db.py:97-101`), so a failure after the CAS still
rolls the head advance back. The old `branch.advance_head(...)`/
`save_branch(...)` pair is removed from this path; the stale domain object is
never persisted.

The CAS `ConflictError` message deliberately uses the branch **id**, not
`branch.name`, and contains neither `"locked"` nor `"busy"`. This is defense in
depth; the retry fix below is what makes branch names incapable of influencing
retry decisions. The user-facing 409 remains the existing `ConflictError`
mapping.

#### Retry loop fix (R1)

In `CreateCommitHandler.handle` (`create_commit.py:67-85`) and
`MergeCommitsHandler.handle` (`merge_commits.py:48-63`), re-raise
`ConflictError` **before** any `"locked"`/`"busy"` test, and gate lock
detection to database errors:

```python
from sqlalchemy.exc import OperationalError
...
                except ConflictError:
                    raise
                except Exception as exc:
                    is_lock = isinstance(exc, OperationalError) and (
                        "locked" in str(exc).lower() or "busy" in str(exc).lower()
                    )
                    if is_lock and attempt < max_retries - 1:
                        await asyncio.sleep(0.05 * (2**attempt))
                        continue
                    raise
```

- The `except ConflictError` clause goes immediately before the existing
  `except Exception` at `create_commit.py:80` and `merge_commits.py:58`.
- The `OperationalError` type gate removes **all** branch-name interpolation
  from the retry decision path (this also fixes `NotFoundError` messages that
  interpolate a branch name), not just `ConflictError` messages. The message
  text may keep branch names; the decision no longer reads it for non-DB
  exceptions.
- Add `from sqlalchemy.exc import OperationalError` to both handler modules.
- Transient DB lock behavior is otherwise unchanged (`max_retries = 3`).

### 4. `MergeCommitsHandler` — same treatment (R1, R5)

In `merge_commits.py`, capture `expected_head = branch.head_commit_id` at the
read (`merge_commits.py:86-95`). Replace
`branch.advance_head(new_commit_id)` + `save_commit` + `save_branch`
(`merge_commits.py:151-156`) with the CAS, then `save_commit`:

```python
updated = await versioning_repo.advance_branch_head_optimistic(
    branch.id, new_commit_id, expected_head
)
if not updated:
    raise ConflictError(
        f"Concurrent merge detected for branch id '{branch.id}': head moved "
        f"from {expected_head!r} while the merge was being created."
    )
await versioning_repo.save_commit(commit)
```

Merge does **not** retry or rebase on conflict (parents are explicit;
re-parenting a merge silently would change its meaning). Apply the same R1
retry-loop fix in `merge_commits.py:48-63`.

### 5. Close the blind `save_branch` head write (R4)

Chosen smallest fix: **`save_branch` must not write `head_commit_id` on its
update path**. The insert path keeps writing it, because legitimate branch
creation supplies a validated parent head (`create_branch.py:87-104`) or
`None` (`create_commit.py:121-127`).

```python
        if model is None:
            model = ServerBranchModel(
                id=branch.id,
                server_id=branch.server_id,
                name=branch.name,
                head_commit_id=branch.head_commit_id,   # keep: creation only
                status=status_val,
                is_protected=branch.is_protected,
                protection_policy=policy_data,
                created_at=branch.created_at,
            )
            self._session.add(model)
        else:
            model.name = branch.name
            # head_commit_id is intentionally NOT assigned here
            model.status = status_val
            model.is_protected = branch.is_protected
            model.protection_policy = policy_data
```

Rationale:

- It closes all three stale-read metadata callers at once
  (`branch_protection.py:68`, `branch_protection.py:131`,
  `archive_branch.py:89`) without changing those handlers.
- It preserves the one legitimate update-independent head source: branch
  creation with a parent commit (`create_branch.py:104`, insert).
- It makes a future accidental blind head write through `save_branch`
  impossible; the only update path for the head is the CAS.
- Rejected alternative: a separate `save_branch_metadata` method used by
  protection/archive. It is more code and still leaves `save_branch` able to
  clobber the head if any future caller uses it. If reviewers prefer the
  explicit method, it must have the same head-free update semantics; it does
  not change the CAS contract.

Build-time test migration: `tests/application/test_stage_c_materialization_commands.py:220-221`
currently advances the head by mutating the domain object and calling
`save_branch`. Replace that seed with
`await repo.advance_branch_head_optimistic(branch.id, "c-next", "c-initial")`.
This is a test-seed update, not a production caller.

Residual (out of scope): the update path still writes `status`, so a stale
metadata save from a `created` view could theoretically write `created` after
a CAS set `active`. F1-1's invariant is the head; this status-clobber race is
recorded in Assumptions/Unknowns and is not expanded into this batch.

### 6. In-memory fakes (R3, R5)

Both fakes must implement the new abstract method or the classes become
abstract and every test that instantiates them fails:

- `backend/tests/application/test_promote_and_rollback.py:56-118`
- `backend/tests/application/test_promote_commit_gating.py:42-106`

Prescribed deterministic fake behaviour:

```python
async def advance_branch_head_optimistic(
    self, branch_id: str, new_head: str, expected_head: str | None
) -> bool:
    branch = self.branches.get(branch_id)
    if branch is None:
        return False
    if branch.status == BranchStatus.ARCHIVED:
        return False
    if branch.head_commit_id != expected_head:
        return False
    branch.advance_head(new_head)
    return True
```

Add `BranchStatus` to each fake's value-object imports. Because the fakes store
domain objects by reference, this mutates the canonical object and is fully
deterministic (no I/O, no sleeps). `advance_head` also performs the
`created → active` transition, matching the SQL path.

For the stale-read race test, add a `stale_branch_override` (or a thin wrapper)
so `get_branch_by_name` returns a stale copy while
`advance_branch_head_optimistic` looks up the **canonical** `self.branches`
entry. This makes the fake reject a stale expected head even though the handler
holds a stale view.

---

## Affected Components

| File | Change |
|---|---|
| `backend/app/modules/versioning/domain/repository.py` | Add abstract `advance_branch_head_optimistic` (branch section, lines 21-36) |
| `backend/app/modules/versioning/infrastructure/repository.py` | Add `update` to the SQLAlchemy import (`:3`); add `BranchStatus` to the value-object import (`:18-28`); add `OperationalError`; implement CAS with archived guard and R2 snapshot-busy mapping; remove head assignment from `save_branch`'s update path (`:92`) |
| `backend/app/modules/versioning/application/commands/create_commit.py` | Capture `expected_head`; CAS before `save_commit`; drop `advance_head`/`save_branch` tail (`:200-202`); add `OperationalError` import; R1 retry-loop exception ordering/type gate |
| `backend/app/modules/versioning/application/commands/merge_commits.py` | Same CAS treatment (`:151-156`); add `OperationalError` import; R1 retry-loop exception ordering/type gate |
| `backend/tests/application/test_promote_and_rollback.py` | Fake gains CAS method + `BranchStatus` import; stale override hook |
| `backend/tests/application/test_promote_commit_gating.py` | Fake gains CAS method + `BranchStatus` import |
| `backend/tests/application/test_create_commit_head_cas.py` | NEW — handler race, second commit, V07, status, locked-main, merge, no-stale-persist tests |
| `backend/tests/infrastructure/test_versioning_repository_cas.py` | NEW — SQL CAS, archived race, stale metadata, R2 experiment |
| `backend/tests/application/test_stage_c_materialization_commands.py` | Test-seed migration at `:220-221` from blind `save_branch` head update to CAS |

No API routers, schemas, migrations, or `contracts/permissions.yaml` entries
change. No new error type and no new dependency.

---

## Interfaces & Contracts

### Repository method (application-facing contract)

```python
async def advance_branch_head_optimistic(
    branch_id: str, new_head: str, expected_head: str | None
) -> bool
```

- `True` iff exactly one row matched the predicate and was updated.
- `False` iff zero rows matched (branch missing, head no longer equals
  `expected_head`, `expected_head is None` and the head is no longer NULL, or
  the branch is archived).
- On `True`, `head_commit_id = new_head` and `status = 'active'` are persisted
  in the caller's transaction.
- Never raises `ConflictError` itself; callers map `False` to `ConflictError`.
- A CAS loss that SQLite surfaces as `SQLITE_BUSY_SNAPSHOT` is also reported as
  `False` (R2); it is not retried or rebased.

### Error mapping (unchanged)

`ConflictError` already maps to HTTP 409 via
`backend/app/api/errors.py:134-135` and its registration at
`backend/app/api/errors.py:186`. `CreateCommitHandler` already imports it
(`create_commit.py:10-15`); `MergeCommitsHandler` already imports it
(`merge_commits.py:9`). No new error type.

### Retry contract

- Logical CAS conflict: **bounded retries = 0**, 409, no rebase.
- Snapshot-busy CAS loss: **bounded retries = 0**, 409, no rebase.
- Ordinary SQLite write-lock contention (`OperationalError` with
  `"locked"`/`"busy"`, not a snapshot-busy CAS loss): unchanged handler loop,
  `max_retries = 3` with exponential backoff.
- `ConflictError` (including its `BranchProtectedError` subclass) is always
  re-raised immediately, regardless of branch name.

### Router contract (unchanged)

`POST /servers/{server_id}/versioning/commits` and
`POST /servers/{server_id}/versioning/commits/merge`
(`backend/app/api/v1/routers/versioning.py:237-275`) keep the same request
schemas, response shape, and `server:version:commit` permission dependency
(`versioning.py:242`, `versioning.py:263`). A CAS loss simply surfaces as the
existing `ConflictError` path. `contracts/permissions.yaml` and
`scripts/check-route-contract` are unaffected.

### Contract reconciliation (R5)

- Reserved spec §3.4:384-386 says the repository should raise `ConflictError`
  when `rows affected == 0`. That is **superseded** by W8:532-534, which
  specifies `updated = await advance_branch_head_optimistic(...)` followed by
  the caller raising `ConflictError`. F1-1 follows W8: the repository returns
  `bool`; the handler raises. Reason: the same primitive is reused by future
  Part B/C callers that may need different user-facing messages, and the
  repository stays persistence-focused.
- W8:530-532 orders `save_commit` **before** the CAS. F1-1 deliberately
  deviates: CAS **before** `save_commit`. Justification: a losing attempt must
  not write a commit row at all; a single transaction means a post-CAS failure
  rolls both writes back, and the CAS-first order is also correct for
  non-transactional/in-memory repositories. This deviation is intentional and
  must be preserved unless the owner explicitly changes it.

---

## Failure/Edge Cases

| Case | Behavior |
|---|---|
| Head unchanged between read and CAS | CAS returns `True`; commit saved; branch advanced and `active`. |
| Head moved to a different commit | CAS returns `False`; `ConflictError` (409); no commit row written by the losing attempt; no rebase. |
| Head was NULL and remains NULL | CAS `expected_head=None` matches NULL; first commit succeeds; status becomes `active`. |
| Head was NULL, another writer set it first | CAS `False`; 409. |
| Branch row absent | `rowcount == 0`; `False`; handler raises 409 (the normal read at `create_commit.py:119-127`/`merge_commits.py:87-95` usually prevents this). |
| Branch archived between read and CAS | R3 status predicate excludes it; CAS `False`; status stays `archived`; 409. |
| Branch already archived at read | Existing `ConflictError` at `create_commit.py:128-129`/`merge_commits.py:94-95`; never retried (R1). |
| `ConflictError` with a branch named `locked-main` | Re-raised before the lock test; 409; exactly one attempt. |
| SQLite snapshot-busy on the CAS `UPDATE` | Mapped to `False` if R2 confirms a robust discriminator; 409; no retry/rebase. If the R2 surface is different, HALT. |
| SQLite write-lock contention elsewhere | Existing retry loop (`max_retries = 3`); unchanged. |
| Failure after CAS, before `save_commit` | SQL: same transaction, head advance rolled back. Fakes: not transactional (test-only). |
| Snapshot artifact on a lost CAS | `save_snapshot` runs before the CAS (`create_commit.py:160-171`); the DB row rolls back but the on-disk COW directory is not reclaimed. **Pre-existing**; cleanup is out of scope. |
| Commit `validate_parent` failure (V07) | Raised before the CAS; unchanged. |
| Stale metadata save after a CAS | `save_branch` update path no longer writes `head_commit_id`; head stays at the CAS value. |
| Branch auto-create race | Not changed by F1-1; the unique constraint (`models.py:39`) is the existing guard. Out of scope. |

---

## Tests & Verification

### First failing test (must be red before the fix, deterministic, no threads)

`backend/tests/application/test_create_commit_head_cas.py::test_create_commit_stale_head_raises_conflict_and_leaves_no_orphan`

Interleaves two handlers by "seeding both reads before either write", using the
in-memory fake plus a stale-read override (no threads, no sleeps):

1. Seed a server mock and a shared `InMemoryVersioningRepository` with one
   branch `b` (`head_commit_id=None`).
2. Run handler A on the shared repo (patch `StorageCapabilityProbe` and
   `BtrfsZfsSnapshotDriver.create_snapshot` as in
   `backend/tests/application/test_promote_and_rollback.py:154-166`). Capture
   `commit_a = res.entity_id`; assert shared branch head == `commit_a`.
3. Build a stale view: `stale_branch = copy` of the branch as read in step 1
   (`head_commit_id=None`). Create a repo that shares the canonical dicts but
   returns `stale_branch` from `get_branch_by_name`
   (`stale_branch_override`).
4. Run handler B on the stale-read repo; it reads head `None` and builds a
   second commit `commit_b`.
5. Assert `pytest.raises(ConflictError)`; assert the shared branch head is
   still `commit_a`; assert `commit_b` is absent from the shared commits and
   `commit_a` remains referenced (no orphan).

On current code (no CAS): handler B calls `save_branch`, the fake overwrites
head to `commit_b`, and no `ConflictError` is raised — the test fails with
`DID NOT RAISE ConflictError` (or head == `commit_b`). This is the required
deterministic red.

### Real-DB handler-level CAS test (R6a)

`backend/tests/application/test_create_commit_head_cas.py::test_create_commit_real_db_stale_head_conflict_two_engines`

- Use `tmp_path / "handler-cas.sqlite3"` with **two independent engines** and
  session factories, both configured like `db.py:54,82-95` (WAL,
  `busy_timeout=30000`). Do not use the autouse in-memory fixture: it is
  `StaticPool` with one shared connection (`conftest.py:47-54`).
- Seed the server row and a branch with head `H`.
- Handler B runs with an injected, gated `SQLVersioningRepository`:
  `get_branch_by_name` reads the branch, signals `read_done`, then awaits a
  gate before returning. The subclass overrides `save_snapshot` to a no-op so
  the CAS `UPDATE` is the first write after B's stale read (otherwise the
  snapshot `INSERT` could itself hit snapshot-busy before the CAS).
- Await `read_done`; run handler A to completion on engine A (CAS `H -> A`,
  save commit, commit).
- Release the gate; handler B proceeds with the stale expected head and must
  raise `ConflictError` (`http_status == 409`) either via `False` or via the
  R2 snapshot-busy mapping.
- Assert the branch head is still `A`, exactly one new commit exists, and B's
  commit was not persisted.

### Supporting repository-level CAS tests

`backend/tests/infrastructure/test_versioning_repository_cas.py` (file-backed
`tmp_path`, not the StaticPool fixture):

- `test_advance_branch_head_optimistic_rejects_stale_expected_head`:
  seed head `H`; CAS `H -> A` in session 1 and commit; CAS `H -> B` with the
  stale expected head in session 2 returns `False`; reload head == `A`.
- `test_advance_branch_head_optimistic_matches_null_head`: `expected_head=None`
  succeeds on a NULL head; a second `None` attempt returns `False`.
- `test_advance_branch_head_sets_status_active`: seed `status='created'`;
  successful CAS persists `status='active'`.
- `test_advance_branch_head_rejects_archived_branch`: seed `status='archived'`;
  CAS returns `False`; status stays `archived`.
- `test_archived_race_between_read_and_cas_keeps_archived`: session A reads an
  active branch; session B archives and commits; session A's CAS returns
  `False`; reload status still `archived` and head unchanged.
- `test_stale_metadata_save_does_not_clobber_head`: load stale branch
  (`head=H0`, `status=active`), close; CAS `H0 -> H1` in another session and
  commit; call `save_branch(stale)` in a fresh session; reload head == `H1`
  (not `H0`) and status == `active`.
- `test_file_backed_two_engine_losing_cas_surface`: the mandatory R2
  experiment described in §2a; pin the observed surface (False or
  snapshot-busy `OperationalError`) and fail with a HALT message on any other
  outcome.

### Handler-level test pinning `validate_parent` (V07)

`backend/tests/application/test_create_commit_head_cas.py::test_create_commit_validates_existing_parent`

Set the fake branch `head_commit_id="c-parent"` and make
`get_commit("c-parent")` return a commit with `server_id="srv-OTHER"`. Patch
`StorageCapabilityProbe`/`BtrfsZfsSnapshotDriver.create_snapshot` as needed and
run `CreateCommitHandler`. Assert
`pytest.raises(ValueError, match="Cross-server parent rejected")`. Removing the
`if branch.head_commit_id: ... commit.validate_parent(...)` block
(`create_commit.py:195-197`) makes this test fail.

### Merge CAS-loss test (R6c)

`backend/tests/application/test_create_commit_head_cas.py::test_merge_stale_head_raises_conflict_and_keeps_head`

Use the same stale-read fake pattern for `MergeCommitsHandler`: seed two parent
commits and a branch whose canonical head advances after a stale read; run the
merge against the stale view; assert `ConflictError`, head unchanged, and no
merge commit persisted. Removing the CAS from `merge_commits.py:151-156` makes
this test fail (the stale `save_branch` clobbers the head).

### Archived-race test (R3/R6d)

Covered by
`tests/infrastructure/test_versioning_repository_cas.py::test_archived_race_between_read_and_cas_keeps_archived`
and a fake-level companion
`tests/application/test_create_commit_head_cas.py::test_fake_cas_rejects_archived_branch`.
Dropping the `status != 'archived'` predicate makes the SQL test go red
(status becomes `active` and/or the CAS returns `True`).

### Second commit on a non-NULL head (R6b)

`backend/tests/application/test_create_commit_head_cas.py::test_create_commit_second_commit_on_non_null_head_succeeds`

Seed a branch with a real head `c1`; run `CreateCommitHandler` on the isolated
DB; assert success, `parent_commit_id == c1`, and the reloaded head is the new
commit. If the handler passes `expected_head=None` unconditionally, the CAS
returns `False` and this test goes red.

### `CREATED → ACTIVE` after the first commit (R6e)

`backend/tests/application/test_create_commit_head_cas.py::test_first_commit_transitions_created_to_active`

Seed a `created` branch with a NULL head in the in-memory fake; run
`CreateCommitHandler` against the fake; reload and assert
`status == BranchStatus.ACTIVE`. This is a handler-level behaviour test: the
fake's `advance_branch_head_optimistic` (via `ServerBranch.advance_head`) sets
status to `ACTIVE`, so removing the `status=BranchStatus.ACTIVE.value` SET from
the SQL CAS does **not** make this test go red. Real SQL `status='active'`
coverage is
`backend/tests/infrastructure/test_versioning_repository_cas.py::test_advance_branch_head_sets_status_active`
(`:144`); that is the test the mutation must turn red.

### No stale branch object persisted after a successful CAS (R6f)

`backend/tests/application/test_create_commit_head_cas.py::test_successful_cas_does_not_persist_stale_branch_object`

Wrap/spy `SQLVersioningRepository.save_branch`; run the handler on an existing
branch with a non-NULL head; assert the handler never calls `save_branch` on
the head-advance path, the reloaded head is the new commit, and status is
`active`. Reverting the handler to the blind `save_branch` tail makes the spy
fire (test red).

### `locked-main` no-retry / 409 tests (R1)

- `backend/tests/application/test_create_commit_head_cas.py::test_archived_branch_named_locked_main_is_not_retried`
- `backend/tests/application/test_create_commit_head_cas.py::test_merge_archived_branch_named_locked_main_is_not_retried`

Seed an **archived** branch named `locked-main`; use the DB-backed handler path
(no injected repos) so the retry loop is active; wrap `_execute` with a
call-counting wrapper. Assert exactly 1 attempt and that the raised
`ConflictError.http_status == 409`. On the v1 substring loop, `_execute` runs 3
times or the assertion on attempts fails.

### Mutation checklist (R8)

Each mutation must turn the named test red:

| # | Mutation | Named test that goes red |
|---|---|---|
| 1 | Remove the SQL CAS predicate (`head_commit_id`/`status` WHERE) | `test_advance_branch_head_optimistic_rejects_stale_expected_head` |
| 2 | Revert the handler to blind `advance_head` + `save_branch` | `test_create_commit_stale_head_raises_conflict_and_leaves_no_orphan` |
| 3 | Always pass `expected_head=None` | `test_create_commit_second_commit_on_non_null_head_succeeds` |
| 4 | Skip `commit.validate_parent` | `test_create_commit_validates_existing_parent` |
| 5 | Fake ignores `expected_head` | `test_create_commit_stale_head_raises_conflict_and_leaves_no_orphan` |
| 6 | Drop the `status='active'` SET | `test_advance_branch_head_sets_status_active` |
| 7 | Drop the archived guard | `test_archived_race_between_read_and_cas_keeps_archived` |
| 8 | Revert the retry loop to the v1 substring test (drop `except ConflictError` and the `OperationalError` gate) | `test_archived_branch_named_locked_main_is_not_retried` |
| 9 | Restore `save_branch`'s update-path `head_commit_id` assignment | `test_stale_metadata_save_does_not_clobber_head` |

### Targeted command

`-k versioning` is **not** sufficient: it deselects
`tests/application/test_stage_b_version_control.py` because the module is
`version_control`, not `versioning`. Verified this session with
`python -m pytest --collect-only -q tests -k versioning`: 28 collected /
3206 deselected, and `test_stage_b_version_control.py` is absent. Use explicit
paths:

```
cd backend && python -m pytest -q \
  tests/application/test_create_commit_head_cas.py \
  tests/infrastructure/test_versioning_repository_cas.py \
  tests/application/test_stage_b_version_control.py \
  tests/application/test_stage_c_materialization_commands.py \
  tests/application/test_promote_and_rollback.py \
  tests/application/test_promote_commit_gating.py \
  tests/application/test_stage_g_branch_protection_commands.py \
  tests/domain/test_stage_a_domain_invariants.py \
  tests/integration/test_sqlite_locking_remediation.py
```

Then the versioning suite and, for close-out, the sequential full backend
suite (evidence rule, project engineering policies):

```
cd backend && python -m pytest -q tests -k versioning
cd backend && python -m pytest -q          # sequential; >=15 min timeout
```

### Six quality gates (must stay 6/6)

```
python scripts/check-db-revision
python scripts/check-ruff-baseline
python scripts/check-version-propagation
python scripts/check-route-contract
python scripts/check-ps1-bom
python scripts/check-stray-db
```

(or `scripts/reverify` on Linux/macOS).

### Portability (Windows/Linux)

Expected: **none** at the application level. The change is Python/SQLAlchemy
only; no path handling, shell, encoding, or line-ending surface changes. All
new SQLite tests use `tmp_path` (file-backed) or the isolated in-memory fixture
for single-writer cases, satisfying the `tmp_path` rule. R2 is the only
platform-sensitive behavior: run the two-engine experiment on Windows CI as
well; if the surface differs in a way that cannot be mapped per §2a, HALT and
report rather than guessing.

---

## Out of Scope

- Parts A, B, and C of
  `SPEC-2026-10-05-BRANCH-AWARE-FILES-AND-PROTECTED-MAIN-01.md` (eager `main`,
  system genesis, branch-aware Files API, `CommitFromWorktreeCommand`, the
  `is_system` column/`b1e2100000023` migration, BUG-V04, disk-space checks).
  Only the reserved method name/contract and W8 behavior are reused.
- Automatic retry or rebase of a losing commit or merge.
- Reclaiming the COW snapshot directory created before a lost CAS
  (`create_commit.py:160-171`); this is a pre-existing artifact-leak behavior.
- Any migration or schema change (none required).
- Frontend behavior (a 409 already surfaces through the existing error path).
- The stale-`status` metadata-clobber race described in §5 (head is the F1-1
  invariant; status reconciliation is a separate concern).
- The branch auto-create unique-constraint race (`create_commit.py:119-127` +
  `models.py:39`); not a head-advance path.
- Refactoring the same substring retry pattern in `archive_branch.py`,
  `branch_protection.py`, `create_branch.py`, or `auto_commit_live_changes.py`.
  R1 is scoped to `CreateCommitHandler` and `MergeCommitsHandler`; those other
  handlers are noted as carrying the same pattern for a future batch.
- A new decision record is required for build (D1, GOVERNANCE §4); it is not
  produced by this DRAFT.

---

## Assumptions / Unknowns

- `[FACT]` Alembic head `b1e2100000022`, 42 revisions — verified this session
  via `ScriptDirectory.get_current_head()`.
- `[FACT]` `head_commit_id` is nullable `String(36)` and `status` is non-null
  `String(32)` — `backend/app/modules/versioning/infrastructure/models.py:33-34`.
- `[FACT]` Blind read-modify-write head update — `repository.py:70-97`,
  especially `:92`.
- `[FACT]` CAS reserved name/predicate —
  `docs/design/SPEC-2026-10-05-BRANCH-AWARE-FILES-AND-PROTECTED-MAIN-01.md:384-386`;
  W8 bool/caller-raises shape at `:532-534`.
- `[FACT]` No existing `advance_branch_head_optimistic` implementation in
  `backend/` (grep) — only the reserved spec mentions it.
- `[FACT]` `sqlalchemy.update` is not imported at module level
  (`repository.py:3`), and `BranchStatus` is not imported at module level
  (`repository.py:18-28`; local import at `:569`).
- `[FACT]` Only two concrete fakes subclass `VersioningRepository`
  (`tests/application/test_promote_and_rollback.py:56`,
  `tests/application/test_promote_commit_gating.py:42`).
- `[FACT]` The autouse test DB is in-memory and uses `StaticPool` (one shared
  connection): `backend/tests/conftest.py:47-54`; verified with engine
  inspection this session.
- `[FACT]` SQLite pragmas / timeout — `db.py:54`, `db.py:82-95`.
- `[FACT]` The production `save_branch` callers are exactly those in the R4
  audit table (`grep` this session); `auto_commit_live_changes` and
  `revert_import_review` delegate to `CreateCommitHandler`.
- `[FACT]` `-k versioning` excludes
  `tests/application/test_stage_b_version_control.py` (verified with
  `--collect-only`: 28/3234 collected).
- `[UNVERIFIED]` The losing-writer surface under file-backed SQLite/WAL: may
  be `rowcount == 0` or `OperationalError` (`SQLITE_BUSY_SNAPSHOT`). The R2
  experiment decides; the builder must HALT if it is neither or cannot be
  robustly distinguished from ordinary lock contention.
- `[UNVERIFIED]` Exact exception attributes exposed by aiosqlite/SQLAlchemy for
  `SQLITE_BUSY_SNAPSHOT` (`sqlite_errorcode` / `sqlite_errorname`) on every
  supported Python/SQLite version. The constant is 517 in this session's
  Python 3.14 / SQLite 3.53 (`sqlite3.SQLITE_BUSY_SNAPSHOT`), but whether the
  DBAPI wrapper preserves it on `exc.orig` must be checked by the R2
  experiment; no text-only catch is permitted.
- `[ASSUMPTION]` The reserved `status='active'` addition is acceptable as a
  superset of the reserved SET clause; it preserves the existing
  `created → active` transition and is documented as a deliberate deviation.
- `[ASSUMPTION]` Removing the head assignment from `save_branch`'s update path
  is acceptable because no production caller legitimately advances a head
  through `save_branch` after the CAS migration; only branch creation (insert)
  legitimately sets a head.
- `[UNVERIFIED]` The stale-`status` metadata-clobber race described in §5 is
  not addressed by F1-1. It is recorded here so it is not mistaken for a
  regression of this batch.
- `[UNVERIFIED]` Whether the owner wants any follow-up for the same substring
  retry pattern in `archive_branch.py`, `branch_protection.py`,
  `create_branch.py`, or `auto_commit_live_changes.py`; R1 scope is
  create/merge only.
- Per this task's MODE constraint (exactly one file), project state tracking was
  intentionally **not** updated for this DRAFT; it will be recorded when the
  build phase lands.
