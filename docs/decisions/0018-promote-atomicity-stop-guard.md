# ADR-0018: Atomic Promote Config Writes and Durability (F1-2a)

**Status**: Accepted (implemented 2026-10-20; local sequential suite + 6/6 gates passed; F1-2b pending; CI/Windows UNVERIFIED)  
**Date**: 2026-10-20  
**Author**: F1-2a Build / Docs Session  
**Decision level**: D1  
**Primary lane**: Lane A (Release Critical)  

## Context

During test environment promotion (`PromoteCommitHandler`), the server configuration
files (such as `server.properties`) were written directly without atomic staging,
fsync durability, or filesystem exception wrapping (V02a). A system crash, power loss,
or abrupt process termination during a promote write could leave critical server
configuration files truncated or corrupt.

Additionally, the underlying filesystem abstraction (`LocalFileSystem.write_binary_atomic`,
FS-1) lacked durability guarantees:
1. It wrote to a temporary file and called `os.replace` without calling `os.fsync` on the
   temporary file descriptor or on the parent directory.
2. It ignored the return value of `os.write`, failing to handle partial/short writes.
3. It leaked open file descriptors if `os.write` raised an exception prior to `os.close`.
4. It provided no atomic text writing helper (`write_text_atomic`), forcing callers to
   resort to non-atomic `Path.write_text` or ad-hoc binary conversions.

A full solution also requires ensuring the target server is safely stopped before
promotion writes occur (the F1-2b stop guard and F1-2c reconciliation fail-open fix).

## Decision

1. **F1-2a: Canonical atomic file write helpers on `FileSystem`.**
   Add `write_text_atomic(path, content, encoding="utf-8")` to the `FileSystem` interface
   and implement it in `LocalFileSystem` by delegating to `write_binary_atomic` after
   encoding. Reimplement `LocalFileSystem.write_binary_atomic` with strict failure ordering:
   - Create sibling temporary file via `tempfile.mkstemp(dir=parent, suffix=".tmp")` on
     the same filesystem (ensuring `os.replace` atomicity).
   - Write payload completely via a `memoryview` loop, handling `InterruptedError` and
     raising `OSError("short write")` on non-positive byte progress.
   - Flush bytes to disk using `os.fsync(fd)` before closing the descriptor and replacing.
   - Ensure the file descriptor is closed in a `finally` block before any `os.unlink`. An
     `os.close` error during cleanup is logged/suppressed so as not to mask the original error.
   - Atomically swap using `os.replace(tmp, dest)`, setting an internal `replaced = True` flag.
   - Synchronize the parent directory via directory descriptor `os.fsync` on POSIX systems
     only (`os.name == "posix"`).
   - On error before replace (`replaced is False`), clean up by unlinking the temporary file.
     Once `replaced is True`, never unlink the temporary path.

2. **Fsync-after-replace semantics (R4c).**
   The parent directory is fsynced after `os.replace` completes. If the directory fsync
   fails, `replaced` is already `True`; the destination file already contains the new bytes,
   so the temp file is not unlinked. The exception is raised to the caller (no silent success),
   causing the promotion request to return an HTTP 503 error even though the new bytes are
   present on disk. This matches the specification's explicit failure ordering.

3. **F1-2 scope: Batch split into F1-2a, F1-2b, and F1-2c.**
   To keep changes reviewable and isolate risk:
   - **F1-2a (this batch):** Atomic per-file config writes, fsync durability, short-write
     handling, file descriptor cleanup, and routing promote config writes through
     `write_text_atomic`.
   - **F1-2b (pending):** Promote stop guard (`stop_confirmed`, `PROMOTE_STOP_NOT_CONFIRMED`,
     revert to `RUNNING` via `_SERVER_TRANSITIONS` `STOPPING -> RUNNING`, D-O1 widened
     stop gate accepting `STOPPING`).
   - **F1-2c (pending):** Startup reconciliation fail-open fix (`reconciliation.py:274-289`
     `STOPPING` branch marking `STOPPED` only when provider confirms `STOPPED`).

4. **D-A: Promote stop precondition (F1-2b requirement).**
   When `was_running` is true, promote must abort if `command_bus is None`.

5. **D-D: Windows open-handle retry/backoff out of scope.**
   Fail fast on OS errors; no open-handle retry or backoff loops. Directory fsync is
   POSIX-only (`os.name == "posix"`). Windows file replacement and directory durability
   remain UNVERIFIED.

6. **D-E: Activity-log early commit ordering deferred.**
   `SQLActivityRepository.save` committing the session before file writes occur is
   preserved in this batch. Decoupling and ordering fixes are deferred to a follow-up.

7. **PromoteCommitHandler config write routing.**
   `PromoteCommitHandler` takes a `FileSystem` dependency and writes every entry in
   `commit.manifest.configs` (`server.properties`, other root configs such as
   `bukkit.yml`/`spigot.yml`/`paper-global.yml`/`purpur.yml`/`eula.txt`, and nested files under
   `config/`) via `write_text_atomic` (`promote_commit.py:188-193`). Any `OSError` during
   writing is caught and re-raised as `FilesystemOperationError` (mapped to HTTP 503 by the
   API layer).

## Alternatives Rejected

1. **Blind non-atomic file writes.**
   Writing directly in place with truncation risks partial files and server corruption if
   interrupted mid-write.
2. **Directory-level atomic swaps for individual config files.**
   Replacing entire server directories for single config updates is unnecessary overhead
   and risks clobbering concurrent runtime files.
3. **Suppressing parent directory fsync errors.**
   Silently ignoring parent directory fsync failures would report false durability to callers
   when the filesystem directory entry is not guaranteed to survive a crash.
4. **All-or-nothing multi-config transactional writes in F1-2a.**
   Full multi-file rollback across N files requires complex staging and rollback mechanisms
   and is deferred to keep F1-2a bounded.

## Consequences

- Configuration file writes during promote are guaranteed atomic and durable on POSIX
  filesystems: incomplete writes cannot persist after a crash.
- Short writes and interrupted system calls (`EINTR`) are reliably handled in a loop.
- File descriptors are always cleaned up in `finally` before unlinking, preventing descriptor
  leaks and Windows file-sharing violations on failure cleanup.
- A failure during parent-directory fsync after replace surfaces as an error (HTTP 503)
  despite the file content having been replaced.
- Multi-file promotions are not yet all-or-nothing: a failure on the second config file leaves
  the first config file modified.
- Stop guard enforcement remains pending (F1-2b).

## Out of Scope

1. **All-or-nothing multi-file promotion / rollback (D-C, deferred).**
   Per-file atomicity is delivered; multi-file rollback across N configs is deferred to
   `SPEC-2026-10-20-PROMOTE-ALL-OR-NOTHING-01` (planned, not yet written).
2. **Windows open-handle retry/backoff (D-D).**
   Fail fast; no retry loop. Windows directory durability remains **UNVERIFIED**.
3. **Activity-log early commit ordering (D-E).**
   Early commit of activity rows before file swap is unchanged; deferred to
   `F-U-ACTIVITY-LOG-COMMIT-ORDERING-01`.
4. **Consolidation of filesystem helpers (D-B).**
   Consolidation of `versioning/infrastructure/fs_atomic.py` and
   `restore_service._atomic_replace_dir` is deferred (report only).
5. **Stop guard and reconciliation fixes (F1-2b, F1-2c).**
   Enforcing `stop_confirmed`, `PROMOTE_STOP_NOT_CONFIRMED`, and reconciliation fixes are
   tracked separately.

## Follow-ups

1. **F1-2b:** Implement promote stop guard with `stop_confirmed` check, D-O1 `STOPPING`
   re-probe handling, and `STOPPING -> RUNNING` aggregate transition.
2. **F1-2c:** Fix reconciliation fail-open in `reconciliation.py:274-289`.
3. **Multi-file atomicity:** Implement transactional staging and rollback for multi-file
   promotion (`SPEC-2026-10-20-PROMOTE-ALL-OR-NOTHING-01` (planned, not yet written)).
4. **Activity log ordering:** Align activity log commit ordering with promotion completion
   (`F-U-ACTIVITY-LOG-COMMIT-ORDERING-01`).
5. **Filesystem consolidation:** Unify duplicate atomic write/replace implementations in
   `fs_atomic.py` and `restore_service.py` into `FileSystem`.

## Open Items

- **Residual risk (UNVERIFIED):** Windows filesystem behavior, file replace semantics under open
  handles, and directory durability have not been verified in a Windows runtime or CI environment.
- **Parent-directory fsync error semantics:** If parent directory fsync fails after `os.replace`,
  the operation raises `FilesystemOperationError` (HTTP 503) even though the new file content is
  already in place.
- **F1-2b pending:** Stop guard enforcement (`stop_confirmed`, `PROMOTE_STOP_NOT_CONFIRMED`)
  is not implemented in this batch.

## Verification Evidence

- **Owner xdist run (2026-10-20):**
  `cd backend && python -m pytest -q -n auto` -> 3256 passed, 6 skipped, 0 failed, 482.85s (collected 3262).
- **Local sequential full suite (2026-10-20):**
  `cd backend && python -m pytest -q` -> 3282 passed, 6 skipped, 0 failed, 1006.55s (collected 3288); frontend 767 passed across 90 files; 6/6 quality gates PASS via `scripts/reverify`.
- **Independent review (2026-10-20):**
  Targeted suite across 5 test files: 75 passed.
  Ruff check clean across all 4 changed files.
  6/6 quality gates PASS (schema revision `b1e2100000022`, ruff baseline 501 violations/21 rules,
  version 0.1.0, route contract 155/155, ps1-bom, stray-db).
  Review verdict: PASS, no BLOCKER/MAJOR.
- **Targeted tests in batch:**
  11 tests added = 9 in test_fs.py (7 general + R4c + R5) + 2 in test_promote_commit_gating.py (regression tests: test_write_text_atomic_writes_utf8_and_replaces_existing, test_write_binary_atomic_parent_fsync_failure_after_replace_keeps_destination, test_write_binary_atomic_close_error_does_not_mask_original, test_promote_uses_atomic_text_writer_for_configs, test_promote_config_write_failure_on_second_file_raises_filesystem_error).
- **UNVERIFIED items:**
  Windows behavior and the CI run are **UNVERIFIED**.

## Links

- Spec: `docs/design/SPEC-2026-10-20-PROMOTE-ATOMICITY-STOP-GUARD-01.md`
- Related Decision: `docs/decisions/0017-branch-head-cas.md`
- Related Decision: `docs/decisions/0012-same-filesystem-staging-for-atomic-swaps.md`
