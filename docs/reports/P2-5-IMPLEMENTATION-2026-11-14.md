# P2-5 Refresh/Rollback Orchestration, Repo Lease Fencing & Crash Recovery — Implementation Report — 2026-11-14

**Slice:** P2-5 (P2b core) — repository lease fencing, two-tier refresh crash journal, backup pinning & interim Class-C snapshot, upfront disk-full policy & complement carry, 4-step Health Gate & triad rollback, and red-team remediation.
**Worktree:** `/mnt/D/workspace/onx-manager-wt/p2-5-refresh-rollback`
**Branch:** `slice/p2-5-implementation-report` (branched from `slice/p2-5d3-redteam-remediation` @ `0181adaa68721f0724604f172962e2f8a231bf22`)
**Base:** `9091ede62dbcb0642172cc64a976d6f44046a53a` (P2-2/P2-3/P2-4 tip on `slice/p2-b4-core-substrate`)
**Status:** IMPLEMENTED_AND_VERIFIED (unit/integration/gates green; live runtime adapter injection, container hardening, D-3 real-run gates, and Windows CI carried to P2-6).

> **Boundary statement:** P2-5 delivers the backend refresh/rollback orchestration, lease fencing, crash recovery, backup pinning, and disk-full policy under feature/bus boundaries. **Zero new HTTP routes** were added (route count remains `156/156`). **Zero frontend files** were edited. Advanced mode remains **disabled by default**, Windows remains **Simple-only**, and D-3 / container hardening / Windows CI are **not** claimed as executed in P2-5. Nothing was pushed, merged, amended, or reset, and `master` (`e87009b85e8973a7c8b5aeaab8966bc5a68c9d26`) remains untouched.

---

## 1. Scope Delivered by Batch (`9091ede..0181ada`)

| Batch | Branch | Commit SHA | Scope & Key Symbols | Targeted Tests |
| :--- | :--- | :--- | :--- | :--- |
| **`P2-5a`** | `slice/p2-5a-schema-migration` | `07166e4de9e1f86a03e1ebf25a47cba241e2ae19` | Alembic revision `b1e2100000026`; tables `server_repo_leases` (7 cols, `fencing_token`, `previous_tree_retention`) & `refresh_journals` (21 cols, partial unique index `ix_refresh_journals_server_active`); `ServerRepoLeaseModel`, `RefreshJournalModel`; `RELEASE_MINIMUM_DB_REVISION = EXPECTED_ALEMBIC_HEAD = "b1e2100000026"`; `FencingTokenMismatchError(ConflictError)` (409 `FENCING_TOKEN_MISMATCH`). | **32 passed** |
| **`P2-5b`** | `slice/p2-5b-repo-lease-fencing` | `6a219726df2b3fc062e5568f8990d4b5146a7dd5` | `RepoLeaseManager` (`DEFAULT_TTL_SECONDS=30.0`, `HEARTBEAT_INTERVAL_SECONDS=10.0`), `RepoLeaseToken`, `RepoLeaseTimeoutError`, atomic DB-clock acquire/renew/assert/release, OS-thread heartbeat daemon, per-server `flock`, `_assert_repo_lock_order()` (`lifecycle -> repo`), optional `fencing_verifier` on `clean_export.py` and `git_branches.py`. | **47 passed** |
| **`P2-5c`** | `slice/p2-5c-refresh-journal-recovery` | `e56ff0c99499d1968c8e024134d5c96aa57a95df` | Two-tier `RefreshJournalRepository` (DB `refresh_journals` + fsynced `<host_state>/journal/<server_id>/refresh.json`, CAS `WHERE fencing_token = :token AND terminal = false`), `RefreshStartupReconciler` (`validate_swap_path`, `recover_interrupted_swap`, staging sweep, expired `.prev` pruning) wired in `main.py`, `directory_swap.py` (`export_id`, `keep_previous`, `classify_swap_state()`), `clean_export.py` UUID4 `export_id`, `_scan_filesystem()` filtering `*.staging`/`*.prev`/`.onx-*`. | **42 passed** |
| **`P2-5d0`** | `slice/p2-5d0-backup-pin-class-c-snapshot` | `b472228e34ece9997743a55c492e9476fdbeefd3` | `BackupJob.pinned` enforcement (`pin()`/`unpin()`, `set_pinned`, `prune_old_backups` skipping pinned, `DeleteBackupCommand` raising `BackupPinnedError` 409 `BACKUP_PINNED`) & interim `ClassCSnapshotService` (`0o700` dir, `format_version=1`, SHA-256 `manifest.json`, fsynced `.onx-complete.json`, `restore_snapshot`, `unpin_snapshot`, `delete_snapshot`). | **81 passed** |
| **`P2-5d1`** | `slice/p2-5d1-refresh-swap-retention` | `0c4bfd491e503ad585255ea9c60a79ea49a40a65` | `RefreshOrchestrator` (`1.10x` total `statvfs` preflight, `ismount` 409 & same `st_dev` checks, `check_worktree_locks` 409 guard, `parse_retention_policy` [`until_health_gate`, `until_confirm`, `1..168h`], complement carry `CARRYING` -> `CARRIED`, `prepare_prior_previous_tree`, `run_thread_shielded`), `clean_export.py` (`ENOSPC` -> cleanup + 507 `InsufficientStorageError`, POSIX 412 retired, non-POSIX 409 `ServerModeVersioningDisabledError`). | **85 passed** |
| **`P2-5d2`** | `slice/p2-5d2-health-gate-triad-rollback` | `1d6ecc32ae43fc913e18890879552ba9e8865a1d` | `HealthGateEvaluator` + `run_health_gate` (4 steps: process liveness, RCON/ping, error log scan, crash-report absence), `LiveRefreshService` (7-step refresh under `ServerLifecycleLeaseManager -> RepoLeaseManager`, `session.lock` guard, pinned backup+snapshot before `BACKED_UP`, `confirm_upgrade_unpin`), `TriadRollbackService` (fast `.prev` rename + fallback re-export, Class-C snapshot restore, Class-E backup restore, `main` ref reset), `RefreshServerCommand`/`ConfirmUpgradeCommand`/`RollbackRefreshCommand` + handlers, `LOCKED_COMMAND_NAMES` update. | **66 passed** |
| **`P2-5d3`** | `slice/p2-5d3-redteam-remediation` | `0181adaa68721f0724604f172962e2f8a231bf22` | Remediated Sonnet Red-Team findings (`B-1..B-7`, `M-1..M-5`, `L-2`, `L-5`) and GLM Round 1 findings (`F1`, `MINOR 1`) across 16 files (`1,901 insertions, 173 deletions`). See Section 3. | **128 passed** (7-file target) / **161 passed** (all 10 P2-5 suites) |

**Total P2-5 diff (`9091ede..0181ada`):** 34 files changed, `9,984 insertions(+), 97 deletions(-)`.

---

## 2. Tests and Repository Gates

### Targeted & Full Backend Suite
- **All 10 P2-5 test suites (post-`P2-5d3`):** **161 passed** (`test_p25_schema_migration.py`, `test_backup_pinned_migration.py`, `test_batch4_core_saga.py`, `test_repo_lease_fencing.py`, `test_refresh_crash_recovery.py`, `test_directory_swap.py`, `test_backup_pinning_and_class_c_snapshot.py`, `test_disk_full_policy.py`, `test_refresh_stage_and_swap.py`, `test_live_refresh_and_rollback.py`).
- **Full backend pytest run on `1d6ecc32` (`P2-5d2`):** **4,508 passed, 2 failed, 6 skipped, 0 errors** in `1,491.51s`. Both failures were in `tests/test_launcher_dynamic_port.py` (`:600` `test_start_backend_retries_only_on_bind_failure` and `:623` `test_start_backend_timeout_is_not_retried`) caused by an unrelated host listener on port `8001` (PID `218098`).
- **Full backend pytest re-run post-`P2-5d3` (`0181ada`, port `8001` freed):** **4,510 passed, 0 failed, 6 skipped**.

### Repository Gates
- `./scripts/check-db-revision`: **PASS** (`b1e2100000026`).
- `./scripts/check-route-contract`: **PASS** (`156` live routes vs `156` contract entries).
- `./scripts/check-ruff-baseline`: **PASS** (`483` violations across `21` rules <= baseline; 3 pre-existing errors in `backend/app/core/exceptions.py`, 0 new errors).
- `git diff --check`: **PASS** (clean).
- `pyright`: Not installed in the local execution environment during batch execution; audited separately in P2-6 recon (see Section 7).

---

## 3. Sonnet Red-Team Findings & `P2-5d3` Remediations

Sonnet's red-team audit of `9091ede..1d6ecc32` returned `VERDICT: FAIL` with 7 High blockers (`B-1..B-7`), 6 Medium (`M-1..M-6`), and 5 Low (`L-1..L-5`). `P2-5d3` remediated all blockers and targeted Medium/Low findings (`VERDICT: PASS` from GLM Round 2):

- **B-1** (`directory_swap.py`): Fallback swap recovery misclassified rolled-back `SWAPPING_IN_STAGING` as `SWAP_COMPLETED` -> fixed by classifying live + staging present with `.prev` absent as `SWAP_ROLLED_BACK`.
- **B-2** (`refresh_orchestrator.py`, `refresh_recovery.py`): Crash in `CARRYING` stranded entries in `.staging` -> persisted carry plan to disk pre-thread and added `_recover_interrupted_carrying` before cleanup/phase advance.
- **B-3** (`main.py`, `start_server.py`, `restart_server.py`, `exceptions.py`): Unresolved refresh journal failed open -> added `assert_no_unresolved_refresh` first-action guard raising `RefreshRecoveryRequiredError` (409 `REFRESH_RECOVERY_REQUIRED`).
- **B-4** (`repo_lease.py`, `refresh_journal.py`, `refresh_orchestrator.py`): Fencing & lease liveness unchecked during operations; Postgres errors swallowed -> enforced `FencingGuard` + `_lease_context` (`assert_fencing_token` + `is_lost`) and fail-fast check in `RepoLeaseManager` for non-SQLite async factories lacking a sync session factory.
- **B-5** (`refresh_orchestrator.py`, `registration.py`): Production slice unreachable -> added lazy factory registration in `registration.py` (0 new HTTP routes), `Tier1BackupServiceAdapter`, and mandatory `repo_lease`.
- **B-6** (`refresh_orchestrator.py`): Rollback re-export swap failure stranded carried data in `.rollback` -> added `_reexport_previous_tree` inverse plan with `BaseException` restore wrapping `restore_carried_entries`.
- **B-7** (`refresh_recovery.py`, `refresh_orchestrator.py`): DB-only phases stayed non-terminal and `.prev` was deleted before `COMPLETED` -> marked `COMPLETED` before `.prev` deletion, added full non-terminal phase recovery matrix + `CARRYING` in `_compensate`, and synced disk-only journals via `iter_disk_journals()`.
- **M-1** (`refresh_orchestrator.py`, `registration.py`): Pinned backups/snapshots leaked on rollback/failed clean -> added `release_pins()` and `ReleaseRefreshPinsCommand`.
- **M-2** (`refresh_journal.py`, `refresh_recovery.py`): Prune raced rollback -> added `_PRUNE_SAFE_PHASES`, fresh journal re-read, and fencing check in `_prune_previous_trees`.
- **M-3** (`refresh_orchestrator.py`): Empty `export_id` disabled exchange crash recovery -> enforced auto-generated UUID4 `export_id`.
- **M-4** (`restore_service.py`): Class-E restore buffered archive in memory, was non-atomic, and missed custom worlds -> implemented streaming disk-backed restore, 507 headroom pre-check, custom `level-name` support, Class-E JSON restore, and ordered `temp_dir/prev` `ENOSPC` rollback.
- **M-5** (`filesystem_reconciliation.py`): Reconciler treated `*.rollback`/`*.rollback-prev` as phantom servers -> excluded `*.rollback`, `*.rollback-prev`, and active staging/previous dirs from `_scan_filesystem()`.
- **L-2** (`lifecycle_lock.py`): Repo lock order check ran before reentrancy check -> moved `_assert_repo_lock_order()` after reentrancy check.
- **L-5** (`refresh_recovery.py`): `_remove_unfinalized_staging` trusted marker without verifying `export_id` -> verified journal marker `export_id` before staging removal.
- **GLM Round 1 Additions**: `F1` (`prepare_prior_previous_tree` 409 guard on non-terminal retained-tree owners) and `MINOR 1` (`validate_swap_path` in `_compensate`).

---

## 4. Locked Decisions (`D-P25-1` .. `D-P25-13`)

- **D-P25-1**: Separate `server_repo_leases` table (30s TTL, 10s OS-thread heartbeat, monotonic `fencing_token`) ordered strictly after `server_lifecycle_leases`.
- **D-P25-2**: Two-tier crash journal: `RefreshJournal` (`refresh.json` + DB `refresh_journals` CAS `WHERE fencing_token = :tok`) wrapping `DirectorySwapJournal` (`swap.json` + `.onx-complete.json` `export_id`).
- **D-P25-3**: Complement-based runtime carry (`CARRYING` / `CARRIED`) for all live entries not owned by the Class A/B/D export manifest (`world*`, custom worlds, `logs/`, Class C/E, `.onx/`, `.onx-manager/server.json`).
- **D-P25-4**: `RefreshStartupReconciler` runs in `main.py` before `FilesystemReconciliationService`; reconciler skips `*.staging`, `*.prev`, `*.rollback`, `*.rollback-prev`, `.onx-*`.
- **D-P25-5**: Upfront `1.10x` total `statvfs` preflight + `ENOSPC` cleanup raising `InsufficientStorageError` (507); retire POSIX 412 `StorageCowUnavailableError` in `CleanExportService` while keeping the exception class.
- **D-P25-6**: Single Alembic migration `b1e2100000026` in `P2-5a`.
- **D-P25-7**: Dropped `P2-5e` (Docker hardening -> P2-6; 1–16 MiB A-CAS & quarantine shipped in P2-4; Vault UI/extraction -> P3).
- **D-P25-8**: P2-5 exposes application/bus services only; HTTP route count stays `156/156`.
- **D-P25-9**: Interim Class-C snapshot = plain `0700` atomic directory snapshot + SHA-256 manifest (`format_version: 1`, fsynced `.onx-complete.json`) under `host_state.class_c_vault_dir/<snapshot_id>/`, pinned for the rollback window.
- **D-P25-10**: Always carry `.onx/` (including `.onx/worktrees`) across swap; fail closed (409) if any worktree is locked (`git worktree lock`); verified by real-Git worktree survival test.
- **D-P25-11**: Retain `.prev` at least until 4-step Health Gate passes (`previous_tree_retention`: `until_health_gate` default, `until_confirm`, or `1..168h`), using fast rename rollback first.
- **D-P25-12**: Split `P2-5d` into `P2-5d0`, `P2-5d1`, `P2-5d2` (+ `P2-5d3` remediation).
- **D-P25-13**: Build only what fits P2; zero frontend edits in P2-5; track P3 items and `"Coming soon"` UI spots in `P3-COMING-SOON.md`.

---

## 5. Proposed Spec Amendments

Normative spec edits were **not** applied during P2-5; needed amendments are documented under `.ai/orchestration/artifacts/`:
- [p2-5-recon/SPEC-AMENDMENTS.md](file:///mnt/D/workspace/onx-manager/.ai/orchestration/artifacts/p2-5-recon/SPEC-AMENDMENTS.md): old-tree retention window (`SPEC:1625 & 2352-2364`, `D-P25-11`), interim Class-C snapshot format (`SPEC:1681-1705 & D-8`, `D-P25-9`), and two-tier journal + complement carry clarification (`SPEC:1619-1655`).
- [p2-6-recon/SPEC-AMENDMENTS.md](file:///mnt/D/workspace/onx-manager/.ai/orchestration/artifacts/p2-6-recon/SPEC-AMENDMENTS.md): P2-6 adapter contract (`D-P26-1`), container hardening (`D-P26-2`), Windows CI (`D-P26-3`), PostgreSQL scope (`D-P26-4`), and frontend `"Coming soon"` labels (`D-P26-5`).

---

## 6. Boundaries Held

- **Zero new HTTP routes**: `check-route-contract` remains `156/156`.
- **Zero frontend edits**: no files under `frontend/` were modified.
- **`master` untouched**: `/mnt/D/workspace/onx-manager` remains at `e87009b85e8973a7c8b5aeaab8966bc5a68c9d26` with only its 4 pre-existing `docs/` paths.
- **No git history rewrites**: no push, merge, amend, or reset performed; `.ai/` was never staged or committed in any worktree.

---

## 7. KNOWN DEFECTS AND LIMITATIONS CARRIED TO P2-6

1. **`_compensate` `self._path_guard` defect**: In `backend/app/modules/versioning/application/refresh_orchestrator.py:1911,1914`, `LiveRefreshService._compensate` calls `self._path_guard.validate_swap_path(...)`, but `_path_guard` lives on `self._orchestrator`, not `LiveRefreshService` (2 Pyright errors; would raise `AttributeError` if `_compensate` hits that path).
2. **`_raise_mismatch` missing `NoReturn`**: In `backend/app/modules/versioning/infrastructure/refresh_journal.py:796,855`, `_raise_mismatch` is annotated `-> None` instead of `-> NoReturn`, causing Pyright to treat `row` as `Row | None` in `_values_from_model` (2 Pyright errors).
3. **`registration.py` `Command`/`CommandHandler` inheritance issue**: In `backend/app/registration.py:499-511`, `RefreshServerCommand`, `RollbackRefreshCommand`, `ConfirmUpgradeCommand`, `ReleaseRefreshPinsCommand` and their handlers do not inherit from `Command` / `CommandHandler[TCommand]` (8 Pyright errors).
4. **Other Pyright findings**: Auditing 23 P2-5-touched files yielded **221 total errors** across 9 files (`14` files with 0 errors): the `12` P2-5 typing bugs above plus `209` pre-existing/SQLAlchemy/framework baseline errors (`filesystem_reconciliation.py`: 151; `backup/infrastructure/repository.py`: 38; `Result.rowcount` in `repo_lease.py`/`refresh_journal.py`/`lifecycle_lock.py`: 13; `main.py`: 4; `registration.py` middlewares: 2; `db_revision.py`: 1). See `.ai/orchestration/artifacts/p2-6-recon/pyright-p25-summary.md`.
5. **`RefreshServerCommand` fails closed until adapters are injected**: `registration.py` registers lazy factories that fail closed (`ValidationError`) until concrete `ServerRuntimePort` and `stage_export` adapters (`DockerServerRuntimeAdapter` / `CleanExportStageAdapter`) are injected in `P2-6a`.
6. **PostgreSQL live refresh fails closed**: `RepoLeaseManager` and `LiveRefreshService` require a synchronous session factory, which is only derived for SQLite; non-SQLite async factories fail fast with an explicit error (no sync Postgres driver / `sync_session_factory` wired).
7. **SQLite-only test coverage for Postgres paths**: All P2-5 unit and integration tests ran against SQLite; PostgreSQL migration `b1e2100000026` and dialect paths have no live `postgres:16` CI execution yet.
8. **D-3 and Windows CI not executed**: Real Paper `1.20.4` build `499` offline boot + allow-list derivation (D-3), container security hardening flags, and Windows Simple-only / non-POSIX `clean_export` CI were not executed in P2-5 and are carried to `P2-6`.
9. **Carried Red-Team / GLM minor items**: `M-6` (`DeleteServer` cascade / `DeleteBackup` TOCTOU on `pinned`), `L-1`, `L-3`, `L-4`, `MINOR 2` (dedicated M-4 `ENOSPC` / custom `level-name` fault-injection tests), `MINOR 3` (narrow SQLSTATE match in `assert_no_unresolved_refresh`), and `MINOR 4` (`ReleaseRefreshPinsCommand` in `LOCKED_COMMAND_NAMES`).
