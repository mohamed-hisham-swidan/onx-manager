# ADR-0017: Branch-Head Compare-and-Swap (CAS) for Versioning

**Status**: Accepted (implementation in working tree; review-fix items open)  
**Date**: 2026-10-20  
**Author**: F1-1 Build/Review Session  
**Decision level**: D1  
**Primary lane**: Lane A (Release Critical)  

## Context

The versioning commit path had a lost-commit race (V01): `CreateCommitHandler`
and `MergeCommitsHandler` read `ServerBranch.head_commit_id`, created a commit
from that value, then advanced the head with a blind read-modify-write. Two
overlapping operations could both start from the same prior head; the second
write silently overwrote the first, leaving one commit unreachable from the
branch pointer.

A second blind writer existed in `SQLVersioningRepository.save_branch`: its
update path unconditionally assigned `head_commit_id`, so a stale in-memory
branch object from a metadata operation could clobber a newer head. Fixing only
the two commit handlers would therefore leave the invariant breakable.

The branch lifecycle requires `CREATED -> ACTIVE` on the first head-advancing
commit and rejects commits to `ARCHIVED` branches.

## Decision

1. Add `advance_branch_head_optimistic(branch_id, new_head, expected_head) -> bool`
   on the versioning repository, implemented as a single conditional SQL
   `UPDATE` on `server_branches.head_commit_id` with an expected-head predicate
   and a status guard (`status != 'archived'`, equivalent to
   `status IN ('created','active')`). The SET clause writes
   `head_commit_id = new_head` and `status = 'active'`; success is
   `rowcount == 1`, otherwise `False`.
2. Route `CreateCommitHandler` and `MergeCommitsHandler` through the CAS,
   raising `ConflictError` (HTTP 409) when the CAS returns `False`; do not
   retry or rebase a logical conflict.
3. Stop `SQLVersioningRepository.save_branch`'s update path from writing
   `head_commit_id`; only branch insertion may set a head. Head advances go
   exclusively through the CAS.
4. In both retry loops, re-raise `ConflictError` before any lock/busy detection,
   and gate lock detection on `OperationalError` type so branch names and
   messages cannot influence retry decisions. Lock-style errors may retry;
   logical CAS conflicts may not.
5. Treat a losing CAS observed as `SQLITE_BUSY_SNAPSHOT` like `False` (409, no
   rebase) if that surface is observed; use `rowcount == 0` when it is the
   observed surface.

## Alternatives Rejected

1. **Blind `save_branch` with retry.** Retrying a blind read-modify-write does
   not detect that another writer moved the head; it can still overwrite the
   newer value. Retry is only safe after a conflict has been detected.
2. **Rely on SQLite locking alone.** Database write serialization prevents
   simultaneous writes but not a stale-read overwrite: the second writer can
   acquire the lock after the first commits and still write an old head. The
   expected-head predicate is required for logical correctness.
3. **Retry or rebase on logical conflict.** Automatically replaying a commit or
   merge against a moved head changes the user's requested operation and can
   create commits with different parents. A 409 requires an explicit
   re-read/retry by the caller.

## Consequences

- Concurrent head advances on one branch can no longer both succeed from the
  same prior head; the loser receives 409 and leaves no reachable-head change.
- Metadata saves cannot clobber the head, because the update path no longer
  writes it.
- The first commit still transitions `CREATED -> ACTIVE`, and archived branches
  are rejected by the CAS guard.
- Callers must handle 409 as a non-retryable logical conflict.
- `_is_sqlite_busy_snapshot` may be unused on environments where the losing
  writer observes `rowcount == 0`; the branch is retained for platforms where
  the snapshot-busy surface appears.

## Open Items

- **MAJOR-1 (open):** `test_first_commit_transitions_created_to_active` uses
  the in-memory fake and cannot detect removal of the SQL `status='active'`
  SET. Real SQL coverage is
  `test_advance_branch_head_sets_status_active`
  (`backend/tests/infrastructure/test_versioning_repository_cas.py:144`).
  Spec mutation mapping corrected to name only the SQL test.
- **MAJOR-2 (resolved by this patch):** STATE entry and this D1 decision record
  were missing; both now exist.
- **MINOR-3 (open, report-only):** `_is_sqlite_busy_snapshot` is dead code in
  this environment because R2 observed `rowcount == 0`.
- **MINOR-4 (open):** Three handler tests use fakes instead of the isolated DB.
- **MINOR-5 (open, UNVERIFIED):** No test drives a real lock through the
  `CreateCommit`/`MergeCommits` retry loops.
- **MINOR-6 (open, report-only):** Stale comment about "if CAS is not yet
  implemented" near `test_versioning_repository_cas.py:320-326`; tests were not
  edited by this docs patch.

## Verification Evidence

- Build/review session reported: targeted set 81 passed; six quality gates
  6/6 PASS; schema revision `b1e2100000022`; HEAD `b4ab65e` with the F1-1 build
  uncommitted in the working tree (commit pending).
- R2 two-engine experiment on Linux/SQLite 3.53 observed
  `outcome_kind=rowcount`, `rowcount=0`; no `SQLITE_BUSY_SNAPSHOT` observed.
- These results were not re-run by this docs-only patch. Windows was **not**
  run, and the snapshot-busy path remains **UNVERIFIED** there.
- Lock-through-handler retry behavior remains **UNVERIFIED** (MINOR-5).

## Links

- Spec: `docs/design/SPEC-2026-10-19-BRANCH-HEAD-CAS-01.md`
- Independent review: 2026-10-20, verdict APPROVE WITH CHANGES (not committed
  as a repository file).
- Related: `docs/decisions/0014-shared-commit-dag-migration-and-branch-lifecycle.md`
  (branch lifecycle), `docs/design/SPEC-2026-10-05-BRANCH-AWARE-FILES-AND-PROTECTED-MAIN-01.md`
  (reserved CAS contract).
