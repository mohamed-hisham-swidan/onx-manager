# DECISION-2026-09-18-001 — Stage G Protected Branches (Narrowed Scope)

**Date:** 2026-09-18  
**Decision Level:** D2 (Major) — per project governance standards: introduces new branch protection policy invariants, direct-commit and archival rejection rules, administrative bypass permissions, and database migration.  
**Lane:** Standard / Core Versioning  
**Status:** Approved (Authorized by Mohamed 2026-09-18; Built & Verified in commit `ba8b539`)  

---

## Context

Stage G in the initial Enterprise Branch Runtime outline proposed multiple enterprise capabilities (Fine-grained RBAC/ABAC, Persistent Volume Snapshotting, Multi-host/node scheduler groundwork, and Protected Branches). A systematic codebase audit evaluated these four:
1. Fine-grained RBAC/ABAC: Already handled by the existing hierarchical Casbin RBAC engine (`permissions.yaml`).
2. Persistent Volume Snapshotting: Redundant with ONX Manager's existing copy-on-write (`btrfs`/`zfs`) reflink snapshotting engine.
3. Multi-host scheduler: Explicitly deferred as external to ONX Manager's single-host architecture.
4. Protected Branches: Genuine missing capability to prevent accidental direct commits or deletions of production branches.

Mohamed narrowed Stage G scope strictly to Protected Branches with configurable policy.

## Decision

Authorize and implement Protected Branches with configurable policy on `ServerBranch`:

1. **Domain Entity:** `BranchProtectionPolicy` frozen dataclass (`require_test_pass: bool = True`, `allow_direct_commit: bool = False`, `allow_force_bypass: bool = True`, `prevent_deletion: bool = True`) with `to_dict()` and `from_dict()`.
2. **ServerBranch Extensions:** Add `is_protected: bool = False`, `protection_policy: BranchProtectionPolicy | None = None`, and domain lifecycle methods `protect()`, `unprotect()`, `can_commit_directly()`, `can_archive()`.
3. **Exceptions:** `BranchProtectedError(ConflictError)` mapping cleanly to HTTP 409 Conflict.
4. **Command Gating:**
   - `CreateCommitCommand`: Enforces direct commit protection; rejects unverified commits unless `force=True` with `server:version:branch:bypass_protection` permission, recording an audit log entry (`versioning.branch_protection_bypassed`).
   - `AutoCommitLiveChangesCommand` & `ArchiveBranchCommand`: Strictly reject actions targeting protected branches.
   - `promote_commit.py`: Intentionally untouched; continues evaluating test pass/force-bypass requirements.
5. **CQRS & Endpoints:**
   - `SetBranchProtectionCommand` / `RemoveBranchProtectionCommand` / `GetBranchProtectionQuery`.
   - 3 new REST endpoints: `GET /branches/{name}/protection`, `PUT /branches/{name}/protection`, `DELETE /branches/{name}/protection`.
6. **Persistence:** Additive Alembic migration `b1e2100000019` adding `is_protected` (Boolean) and `protection_policy` (JSON) to `server_branches`.
7. **Permissions:** Registered in `contracts/permissions.yaml` advancing route contract to 150/150 routes.

## Decided by

Approved by Mohamed (2026-09-18). Built in commit `ba8b539` and verified green (24 new backend tests, 2,906 total backend tests passing, 6/6 CI gates PASS).
