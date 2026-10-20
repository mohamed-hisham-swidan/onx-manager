# DESIGN SPEC — F1-2a Atomic Config Writes + fsync / F1-2b Stop Guarantee (Promote)

| Field | Value |
|---|---|
| Lane | A |
| Decision Level | D1 |
| Status | DRAFT |
| Date | 2026-10-20 |
| HEAD | `0a62d45` (`fix(versioning): atomic branch head advance via CAS (F1-1)`) |
| Spec ID | `SPEC-2026-10-20-PROMOTE-ATOMICITY-STOP-GUARD-01` |
| Governance | `docs/governance/GOVERNANCE.md`; `.ai/RULES/core-principles.md`; `.ai/RULES/testing-and-verification.md` |
| Mode | Design only. Exactly one new file was created. No source, test, state or git-write changes. |
| Revision | **v4 (2026-10-20), applies D-O1 (STOPPING re-verification gate), D-F1-2c (reconciliation fail-open fix) and the v3 R1-R8 / option A decisions** |

---

## Revision Log

### v2 (2026-10-20) — Design Review R1-R8

| R-ID | Severity | Section(s) changed | Summary |
|---|---|---|---|
| R1 | MAJOR | F1-2b item 11; Tests (F1-2b); Assumptions | `runtime_verified` is captured from the pre-stop runtime handle at `stop_server.py:67` (aggregate fetched at `:49`, consumed at `:74`) **before** `mark_stopped()` at `:168`; the `:167` rebind must not be used. New confirmed-stop test requires a non-empty `external_id`. |
| R2 | MAJOR | F1-2b items 11-12; Current Behavior; Failure/Edge Cases; Tests (F1-2b) | Fail closed across requests: on `stop_confirmed is False`, `mark_stopped()` is not called and `external_id` is preserved; DB status stays `STOPPING` (not `STOPPED`). New DB-invariant and second-promote tests. **Superseded in part by CV3-2:** the confirmed-still-running case now reverts to `RUNNING`. |
| R3 | MAJOR | F1-2b item 13; Current Behavior; Failure/Edge Cases; Tests (F1-2b) | `ServerStatus.STOPPING` added to the "was running" set at `promote_commit.py:179`; new STOPPING abort test. |
| R4 | MAJOR | Tests (F1-2a, F1-2b); Mutation checklist | Added missing tests: no-handle/empty-`external_id`, temp removal before `os.replace`, post-replace parent-fsync failure, abort writes nothing (checksum), inconsistent-result mutants, real-`tmp_path` integration test. |
| R5 | MINOR | F1-2a items 2/4; Interfaces (semantics); Failure/Edge Cases; Tests (F1-2a) | Failure ordering: close fd before unlink; `replaced` flag prevents unlinking after `os.replace`; post-replace parent-fsync raises without unlinking; `os.close` failure in `finally` never masks the original exception. |
| R6 | MINOR | F1-2b item 13; Failure/Edge Cases | Wrap the `StopServerCommand` send in `try/except Exception`; any exception is "not confirmed" and aborts with `PROMOTE_STOP_NOT_CONFIRMED`. Failure-table row retained. |
| R7 | MINOR | New section: Pre-implementation Requirements | Lists the docs-patch work (decision record `0018`, `.ai/STATE.json` F1-2 item, live runtime verification) explicitly **not created** in this design session. |
| R8 | MINOR | New section: Coupling and Blast Radius; Affected Components; Out of Scope | Records the versioning-application -> server-infrastructure `fs.py` import, accepted with follow-up `F-U-PROMOTE-FS-PROTOCOL-01`, and the full `write_binary_atomic` caller blast radius. |

### v3 (2026-10-20) — citation corrections and owner-approved option A

| R-ID | Severity | Section(s) changed | Summary |
|---|---|---|---|
| CV3-1 | MINOR (citations) | Current Behavior (Stop behavior); F1-2b item 12; Assumption 17; Assumption 18 | **C1:** the first UnitOfWork commit is `stop_server.py:58` (`await uow.commit()`), not `:53`; `:53` is `server.stop(reason=...)`, which only sets in-memory status. **C2:** `ServerStatus.STOPPING` is defined at `aggregate.py:41`; the old `:379-381` citation pointed at the `stop()` method, now cited as `:380-382`. **C3:** the verified line facts in the v2 body are retained unchanged. |
| CV3-2 | MAJOR (design) | F1-2b items 11-12; Current Behavior; Affected Components; Interfaces; Failure/Edge Cases; Tests; Mutation checklist; Assumptions | Replaces the v2 single unconfirmed outcome ("leave `STOPPING`") with three outcomes: (i) confirmed stopped -> `mark_stopped()`; (ii) confirmed still running -> new `STOPPING -> RUNNING` transition via `revert_to_running()`, runtime handle preserved; (iii) unknown -> leave `STOPPING` (O-1). Adds `RUNNING` to the `_SERVER_TRANSITIONS[STOPPING]` entry at `aggregate.py:77`, a `mark_running()` STOPPING guard, and tests/mutation rows. |
| CV3-3 | MAJOR (open) | Failure/Edge Cases; new Open Questions; Pre-implementation Requirements; Assumptions | Records **O-1**: the UNKNOWN outcome is not solved. Compares (a) accept `STOPPING` until a later successful probe, (b) accept `STOPPING` as a re-verify input (widens the `:51-52` gate; owner approval required), and (c) a manual force-stop endpoint. No option is chosen. |

### v4 (2026-10-20) — D-O1 and D-F1-2c

| R-ID | Severity | Section(s) changed | Summary |
|---|---|---|---|
| CV4-1 | MAJOR (design, owner decision) | Goal; Current Behavior (Stop behavior); F1-2b items 12/12a; Failure/Edge Cases; Open Questions; Affected Components; Tests; Mutation checklist; Out of Scope; Assumptions | **D-O1 (option b) applied.** The stop gate at `stop_server.py:51-52` accepts `RUNNING`, `STARTING` and `STOPPING`. A `STOPPING` row skips `server.stop()` at `:53` and the first `repo.save`/`uow.commit` (`:54-58`), because `STOPPING -> STOPPING` is not an allowed transition (`aggregate.py:77`; `_transition_to` rejects it at `aggregate.py:297-304`), and goes straight to provider verification with its existing runtime handle. The v3 three outcomes are unchanged: confirmed stopped -> `mark_stopped()` / `stop_outcome="stopped"`; confirmed still running -> `revert_to_running()` / `stop_outcome="still_running"`; unknown -> stay `STOPPING` / `stop_outcome="unknown"`. A second promote now re-probes instead of failing the old gate. **O-1 is closed as RESOLVED** with the residual risk that a persistent probe failure keeps the server `STOPPING` until a probe succeeds; visibility is required via the result and activity log. No force endpoint, retry, or new timeout. |
| CV4-2 | MAJOR (design, owner decision) | Goal; Current Behavior (reconciliation); new F1-2c; Failure/Edge Cases; Affected Components; Tests; Mutation checklist; Assumptions | **D-F1-2c applied.** The STOPPING branch in `reconciliation.py:274-289` currently calls `mark_stopped()` at `:279` without reading the provider status computed at `:136-141`. New behaviour: provider `STOPPED` -> `mark_stopped()`; provider `RUNNING` -> `revert_to_running()`; unknown or probe error -> leave `STOPPING` and log a warning. Never mark `STOPPED` without a provider `STOPPED`. This is a separately landable F1-2c sub-batch inside the same release batch, with its own three failing tests. Trigger established: startup lifespan only (`main.py:126`), no periodic caller. |
| CV4-3 | MINOR (tests) | Tests; Mutation checklist; Affected Components | Test changes for the widened gate and reconciliation. Replaces the v3 unknown-second-promote test that expected `ServerNotRunningError` with a re-probe test; keeps a guard test that `STOPPED`/`CRASHED`/`CREATED` still raise `ServerNotRunningError`; updates the existing reconciliation STOPPING test and adds the F1-2c RUNNING/unknown/STOPPED cases. Adds mutation rows for "accept `STOPPED`/`CRASHED` in the widened gate" and "mark `STOPPED` in reconciliation without provider confirmation". |

---

## Goal

Make promotion safer in three sub-batches: F1-2a and F1-2b are independent;
F1-2c is separately landable inside the same release batch (it depends on F1-2b's
`revert_to_running()`).

- **F1-2a** — Make each production config write atomic and durable by adding a canonical
  `LocalFileSystem.write_text_atomic` beside `write_binary_atomic`, fixing the existing
  helper's missing `fsync` (file and POSIX parent directory), unchecked short writes, and
  file-descriptor leak on error; then use the helper for every manifest config written by
  promotion.
- **F1-2b** — Fail closed when promotion stopped a running server but cannot prove it
  stopped: abort **before any config, mods or world file is written**, return a stable,
  explicit error, and never silently continue. When the provider confirms the process is
  still running, the stop handler reverts the server to `RUNNING` with its runtime handle
  intact; when the outcome is unknown, the row stays `STOPPING`. Per **D-O1**, a `STOPPING`
  row is also accepted as a re-verification input, so a later promote re-probes it through
  the same three outcomes instead of being rejected by the status gate.
- **F1-2c** — Fix the reconciliation fail-open (**D-F1-2c**): a `STOPPING` row is only
  marked `STOPPED` when the provider actually reports `STOPPED`; a provider `RUNNING` result
  reverts to `RUNNING`, and an unknown/probe-error leaves `STOPPING`. This is a separately
  landable sub-batch inside the same release batch.

All-or-nothing multi-file promotion, Windows open-handle retry, and activity-log commit
ordering are explicitly deferred (see **Out of Scope**).

---

## Current Behavior (with file:line)

### Promotion flow

`PromoteCommitHandler._execute` (`backend/app/modules/versioning/application/commands/promote_commit.py:91`):

1. Fetches server, test run and commit (`:101-115`) and enforces the test-run gate
   (`:117-145`). The handler does **not** touch branch head — no `save_branch`, no
   `advance_branch_head_optimistic`.
2. Optionally writes the force-bypass activity log (`:147-171`). `SQLActivityRepository.save`
   commits its own session (`backend/app/modules/activity/infrastructure/repository.py:44-60`),
   so this row is already durable before any stop or file work.
3. Stops production when the server is `RUNNING`/`STARTING`:
   `await self._command_bus.send(StopServerCommand(...))` and **discards the result**
   (`promote_commit.py:178-181`). There is no success check, no warning check, no re-read,
   and no abort.
4. Writes every manifest config with `Path.write_text` (`promote_commit.py:183-188`). This is
   truncating, non-atomic, and one file at a time; if file 2 of N fails, file 1 is already
   changed and there is no rollback.
5. Swaps `mods` with `_atomic_replace_dir` imported from restore-service
   (`promote_commit.py:11`, use at `:190-194`).
6. Swaps `world`, `world_nether`, `world_the_end` when `keep_world_changes`
   (`promote_commit.py:196-202`).
7. Cleans up the test container (`promote_commit.py:204-215`).
8. Restarts production when it was previously running, again **discarding the
   `StartServerCommand` result** (`promote_commit.py:217-219`).
9. Emits `CommitPromotedEvent` and returns a success result (`promote_commit.py:221-248`).

> **Recon correction:** there is no `backend/app/modules/versioning/application/commands/promote.py`
> at HEAD `0a62d45` (verified by `find`/`rg`). The recon citations `promote.py:196-202` and
> `promote.py:217-219` are the world-swap and restart blocks of `promote_commit.py`.

### Stop behavior

`StopServerHandler.handle` (`backend/app/modules/server/application/commands/stop_server.py:43`):

- Raises `ServerNotRunningError` when the stored status is not `RUNNING`/`STARTING`
  (`:51-52`). At HEAD a `STOPPING` row is therefore rejected. **v4 / D-O1 widens this gate
  to `RUNNING`, `STARTING` and `STOPPING`.** For `RUNNING`/`STARTING` the first UnitOfWork
  is unchanged. For `STOPPING`, the handler must **not** call `server.stop(reason=...)` at
  `:53` (nor the first `repo.save`/`uow.commit` at `:54-58`): `STOPPING -> STOPPING` is not
  an allowed transition (`aggregate.py:77`; `_transition_to` raises `InvalidValueError` at
  `aggregate.py:297-304`). A `STOPPING` server goes straight to provider verification
  (`:67-163`) using the runtime handle on the aggregate fetched at `:49`.
  `CommandBus` converts `ServerNotRunningError` to `CommandResult(success=False, ...)` and
  never raises (`backend/app/core/command_bus.py:105-121`).
- Collects `provider_errors` for graceful-stop timeout (`:88-100`), provider-stop failure
  (`:101-110`), a final provider status that is not `STOPPED` (`:112-133`), and a still-listening
  port (`:137-156`).
- **Swallows a provider status probe exception** with a bare `except Exception: pass`
  (`:134-135`), so a failed verification produces no `provider_errors`.
- Marks the DB row `STOPPED` unconditionally (`:165-173`), regardless of `provider_errors`.
  v3/v4 change this: the second UnitOfWork branches on the three outcomes in item 12
  (`mark_stopped()`, `revert_to_running()`, or no write).
- Returns `CommandResult(success=True, data={...})` even when `provider_errors` is non-empty;
  errors are demoted to `data["warnings"]` (`:183-194`).
- Rebinds `server` from a second UnitOfWork at `:167` and then calls `mark_stopped()` at
  `:168`. `mark_stopped()` clears `external_id` (`aggregate.py:384-393`, specifically
  `:391`), so any `runtime_verified` computed after the rebind is always false. v3 captures
  it at `:74`, before the rebind (R1, item 11).
- The mandatory `server.stop()` at `:53` sets `STOPPING` in memory; the first UnitOfWork
  commits it at `:58` (`await uow.commit()`). This applies only to the `RUNNING`/`STARTING`
  input path. v4 / D-O1 skips `:53` and the first commit for an already-`STOPPING` row. v2
  skipped `mark_stopped()` for every unconfirmed stop, leaving the row at `STOPPING`. v3
  replaces that single outcome with three (item 12): confirmed stopped -> `mark_stopped()`;
  confirmed still running -> `revert_to_running()` (status `RUNNING`, runtime handle
  preserved); unknown -> remain `STOPPING`. `external_id` is preserved in the two
  non-confirmed outcomes.

Consequences (HEAD behavior; v3 fixes the first three by R1/CV3-2):

- `success=True` does **not** mean the process stopped.
- DB `status == STOPPED` does **not** mean the process stopped; `mark_stopped()` is
  unconditional at HEAD (`stop_server.py:168`, `backend/app/modules/server/domain/aggregate.py:384-393`).
- When `server.runtime` is missing or `external_id` is empty, the entire provider/port
  verification block is skipped (`stop_server.py:74`), so there is no evidence at all.
- Marking `STOPPED` on failure is also a **cross-request fail-open**: a later promote sees
  `STOPPED`, skips the stop, and writes files while the process may still be running. v3's
  three outcomes keep the failure visible to the next request (still running -> `RUNNING`;
  unknown -> `STOPPING`).

### Reconciliation STOPPING branch (F1-2c)

`reconcile_servers` is defined at
`backend/app/modules/server/application/reconciliation.py:96`. Its only production caller
is the FastAPI startup lifespan at `backend/app/main.py:126` (the `lifespan` context manager
starts at `main.py:75`); tests call it directly (`backend/tests/application/test_reconciliation.py`).
**Trigger: process startup only, on every backend start.** No periodic, scheduled, or other
caller exists at HEAD `0a62d45` (verified by `rg "reconcile_servers" backend/`).

The provider status is computed once at `reconciliation.py:136-141`: `status` defaults to
`STOPPED`, `provider.status(handle)` is awaited at `:139`, and **any probe exception is
converted to `ServerRuntimeStatus.ERROR` at `:140-141`**. The `STOPPING` branch at
`:274-289` then calls `server.mark_stopped()` unconditionally at `:279` and saves at `:280`
without ever reading `status`. Consequences:

- a server whose provider still reports `RUNNING` is persisted as `STOPPED` (fail-open);
- a probe failure (`ERROR`) or `UNKNOWN` is persisted as `STOPPED`, hiding the unknown;
- this also defeats the D-O1 recovery path: an operator/promote re-probe would see `STOPPED`
  and skip the stop even though the process may still be running.

### Filesystem helper

`LocalFileSystem.write_binary_atomic` (`backend/app/modules/server/infrastructure/fs.py:165-177`):

- Creates a sibling temp file with `tempfile.mkstemp` (`:169`), writes once (`:171`), closes
  (`:172`), and `os.replace`s (`:173`).
- **No `fsync`** of the temp file or of the parent directory.
- **No short-write loop**: the return value of `os.write` is ignored.
- **fd leak on error**: `os.close(fd)` is inside the `try`; if `os.write` raises, the fd is
  never closed (`:170-177`).
- `write_text` is a plain `Path.write_text` (`:72-73`); `rename` is `os.replace` (`:150-151`).

Related, deliberately not consolidated in this batch:

- `versioning/infrastructure/fs_atomic.py:8-32` (`atomic_write_file`) does `fsync` the file
  (`:25`) but not the parent directory; `:35-49` (`atomic_replace_file`) and `:52-89`
  (`atomic_replace_dir`) do no `fsync`.
- `backup/application/restore_service.py:166-197` provides the `_atomic_replace_dir` used by
  promotion; it has no `fsync` and uses fixed temp names.
- `identity_writer.py:50` and `jar_service.py:763,807` already call `write_binary_atomic`, so
  they inherit whatever durability this batch adds.

### Wiring and surface

- Production wiring passes `command_bus` and `event_bus` to `PromoteCommitHandler`
  (`backend/app/registration.py:398-400`). The event-bus-None concern is refuted.
- HTTP surface is `POST /api/v1/servers/{server_id}/versioning/tests/{test_id}/promote`
  (`backend/app/api/v1/routers/versioning.py:370-391`), permission
  `server:version:promote`; force additionally needs `server:version:promote:force`
  (`:379-381`). `check_command_result` maps `CommandResult.error_code` to HTTP status
  (`backend/app/api/errors.py:23-60`).

---

## Proposed Change

### F1-2a — Atomic per-file write + fsync, short-write loop, fd cleanup, promote configs

**Canonical helper (`backend/app/modules/server/infrastructure/fs.py`).**

1. Add `write_text_atomic(self, path: str, content: str, encoding: str = "utf-8") -> None`
   to the `FileSystem` ABC (beside `write_binary_atomic` at `:56`) and to
   `LocalFileSystem`.
2. Reimplement `write_binary_atomic` as a single internal implementation with explicit
   failure ordering (R5):
   - `ensure_dir(parent)`;
   - `mkstemp(dir=parent, suffix=".tmp")` (same filesystem, so `os.replace` is atomic);
   - initialize `replaced = False`;
   - copy the payload through a `memoryview` in a loop:
     `n = os.write(fd, view)`; `InterruptedError` -> retry; `n == 0` or `n < 0` ->
     `OSError("short write")`; advance `view = view[n:]`;
   - `os.fsync(fd)` **before** close and replace;
   - close the fd in a `finally` **before any unlink**; an `os.close` error inside
     `finally` must be suppressed/logged and must **not** mask the original exception;
   - `os.replace(tmp, dest)`, then set `replaced = True`;
   - `fsync` the parent directory on POSIX only, then return;
   - cleanup on failure: if `replaced` is `False`, unlink the temp file **after** the fd
     is closed (Windows cannot unlink an open file); if `replaced` is `True`, never unlink
     the temp path (the destination is already the new file, and the old temp name must
     not be treated as disposable state).
3. `write_text_atomic` encodes with the requested encoding (default UTF-8) and delegates to
   `write_binary_atomic`, so text and binary share exactly one durability path.
4. Cleanup contract (R5): any failure before `os.replace` closes the fd first, then removes
   the temp file, and leaves the destination untouched. A parent-directory `fsync` failure
   happens **after** the replace (`replaced is True`), so the destination already holds the
   new bytes, the temp path is not unlinked, and the error is still raised (no silent
   success).
5. POSIX gate: `if os.name != "posix": return` in the parent-directory sync helper. No new
   dependency and no `sys` import required. Windows gets file `fsync` but no directory
   `fsync`; this is recorded as **UNVERIFIED** (D-D).

**Promotion (`backend/app/modules/versioning/application/commands/promote_commit.py`).**

6. Add an optional constructor dependency `fs: FileSystem | None = None`, defaulting to
   `local_fs`, stored as `self._fs` (same dependency-injection pattern as
   `identity_writer.py:31-50`). Production wiring needs no change.
7. Replace `tgt_file.write_text(content, encoding="utf-8")` (`:188`) with
   `self._fs.write_text_atomic(str(tgt_file), content, encoding="utf-8")`.
8. Wrap the helper call in `try/except OSError` and raise the existing
   `FilesystemOperationError(path, "write", detail)` (`backend/app/core/exceptions.py:293-303`)
   so the failing path is visible. This is an existing error type; no new exception class.
9. Keep the current per-file loop and the current mods/world `_atomic_replace_dir` calls.
   Per-file atomicity does **not** imply multi-file all-or-nothing — that is deferred.

### F1-2b — Stop guarantee and fail-closed promotion

**Stop result contract (`backend/app/modules/server/application/commands/stop_server.py`).**

10. Replace the swallowed status-probe exception (`:134-135`) with
    `provider_errors.append(f"Status check failed: {exc}")` (and a warning log). A provider
    that cannot be queried must not look like a clean stop.
11. **Capture `runtime_verified` before any `mark_stopped()` call (R1).** The capture
    point is **`stop_server.py:67`** (the `provider_errors: list[str] = []` line), after
    the first UnitOfWork has committed and **before** the provider block at `:74` and
    before any `mark_stopped()` call. The `server` aggregate there is the one fetched by
    the first UnitOfWork at `stop_server.py:49`. Assign
    `pre_stop_runtime = server.runtime` at `:67` and derive
    `runtime_verified = pre_stop_runtime is not None and
    bool(pre_stop_runtime.external_id)` from that local; the existing pre-stop guard at
    `:74` (`if server.runtime and server.runtime.external_id:`) is the consumer, not a
    valid late capture site. Do **not** recompute it from the `server` object rebound by
    the second UnitOfWork at `:167`: `mark_stopped()` at `:168` clears `external_id`
    (`backend/app/modules/server/domain/aggregate.py:384-393`), so a post-rebind read is
    always empty and would make every real stop look unconfirmed.
    Expose in `CommandResult.data`:
    - `stop_confirmed: bool` — `True` only for outcome (i) below;
    - `provider_errors: list[str]` — same content as `warnings`, exposed explicitly;
    - `runtime_verified: bool` — the captured flag, for operator diagnosis (no secret data);
    - `stop_outcome: str` — `"stopped"`, `"still_running"` or `"unknown"` (diagnostic;
      promotion does not gate on it);
    - keep `warnings` for backward compatibility (`:183-194`).
12. **Three outcomes after provider verification (v3, owner-approved option A).** During
    the existing provider/port block (`:74-163`), track one positive signal,
    `still_running: bool`, initialized `False`:
    - set it when the provider status probe returns `ServerRuntimeStatus.RUNNING`
      (`:113-122`; today this appends `"Runtime still running after stop"`);
    - set it when `_port_is_listening` reports the port still listening after
      `_wait_for_port_free` (`:140-156`; today this appends
      `"Port <n> still listening after stop"`).
    The port check stays inside the `if server.runtime and server.runtime.external_id:`
    guard at `:74`, so no-handle servers never set `still_running`. Item 10 records probe
    failures in `provider_errors` instead of swallowing them (`:134-135`).

    After the block, branch exactly one of three ways in the second UnitOfWork (`:165-173`):

    - **(i) CONFIRMED STOPPED.** `runtime_verified` is `True`, the provider status was
      `STOPPED`, the port is not listening, and `provider_errors` is empty. Call
      `server.mark_stopped()` as today (`:168`) and commit. `stop_confirmed=True`,
      `stop_outcome="stopped"`.
    - **(ii) CONFIRMED STILL RUNNING.** `runtime_verified` is `True` and `still_running`
      is `True` (provider status `RUNNING` and/or port still listening). Call the **new**
      `server.revert_to_running()` instead of `mark_stopped()`. That method transitions
      `STOPPING -> RUNNING` (the new allowed transition) and leaves `external_id`, `pid`,
      `port`, `host` and the rest of the runtime handle untouched. Do **not** call
      `mark_stopped()`. `provider_errors` is non-empty, so `warnings` is non-empty and
      `stop_confirmed=False`; the command still returns `success=True` (backward
      compatibility) with `stop_outcome="still_running"`. Promotion aborts through its own
      gate (item 13). Do **not** reuse `mark_running()` (`aggregate.py:352-378`): it
      rebuilds the runtime handle and increments `restart_count`, which would lose the
      preserved handle.
    - **(iii) UNKNOWN.** Anything not (i) or (ii): the provider status probe raised or
      timed out (now recorded by item 10), the server was running but had no runtime
      handle/`external_id` so the whole block at `:74` was skipped, or `provider_errors`
      exists without positive `still_running` evidence (for example a graceful stop
      timeout followed by a clean final status). Leave the status at `STOPPING`: do
      **not** call `mark_stopped()` or `revert_to_running()`, skip the status second
      write/commit (guard the `async with UnitOfWork(...)` block at `:165` so it runs only
      for (i)/(ii)); a separate event-only UnitOfWork may still commit the unknown-outcome
      activity event), and keep `external_id`. On the `RUNNING`/`STARTING` path the `STOPPING` value is
      already committed by the first UnitOfWork at `:58`; on the D-O1 re-probe path the
      row was already `STOPPING` and no first write occurred. The command still returns
      `success=True` (backward compatibility) with `stop_confirmed=False`; `warnings` may be
      empty when there is no runtime handle, which is why promotion also checks
      `stop_confirmed` rather than warnings alone. `stop_outcome="unknown"`. **Visibility
      (D-O1, mandatory):** the result must carry `stop_outcome="unknown"`, and the activity
      log must record it. Emit a warning through the existing lifecycle logger/timeline and
      persist a `ServerActivityLog` row by publishing a new `ServerStopUnknownEvent`
      (`backend/app/modules/server/domain/events.py`) with `server_id`, `stop_outcome="unknown"`,
      `runtime_verified`, `warnings` and `provider_errors`; map it in
      `backend/app/modules/activity/application/subscriber.py` to `server.stop_unknown` and
      register it for the activity subscriber in `backend/app/registration.py:300-327`. This
      event-only UnitOfWork changes no server status. Do **not** add a force endpoint, retry,
      or a new timeout. **O-1 is RESOLVED by D-O1** (see Open Questions).

    Precedence: a positive still-running observation wins over a probe failure. If the
    status probe raises but the port is still listening, the outcome is (ii), not (iii).
    On the `RUNNING`/`STARTING` path the persisted `STOPPING` value comes from the first
    UnitOfWork commit at `:58` (`:53` only calls `server.stop()` in memory); on the D-O1
    `STOPPING` path there is no first write and the row is already `STOPPING`.
    "Unchanged" for (iii) therefore means **not advanced to `STOPPED` or `RUNNING`**, never
    the pre-request `RUNNING` value.
    Cross-request behavior (D-O1): after (ii) the row is `RUNNING`, so a later promote sends
    `StopServerCommand` again through the `was_running` check (R3); it either confirms
    cleanly or takes (ii)/(iii) again. After (iii) the row is `STOPPING`; the widened gate
    accepts it (`:51-52`), the handler skips `server.stop()`/the first write (`:53-58`), and
    the next promote **re-probes** with the existing runtime handle, taking (i), (ii) or (iii)
    again. A second promote therefore no longer raises `ServerNotRunningError` for an unknown
    first stop. If the probe keeps failing, the row stays `STOPPING` until a probe succeeds;
    that is the residual risk recorded under O-1, made visible by `stop_outcome="unknown"` in
    the result and by the activity-log entry above.

**12a. Gate widening and the `STOPPING` path (D-O1).** The status gate at `:51-52`
becomes:

```python
if server.status not in (
    ServerStatus.RUNNING,
    ServerStatus.STARTING,
    ServerStatus.STOPPING,
):
    raise ServerNotRunningError(sid)
if server.status is not ServerStatus.STOPPING:
    server.stop(reason=command.reason)
    await repo.save(server)
    for event in server.collect_events():
        uow.add_event(event)
        logger.info("EVENT %s", format_event(event, server_name))
    await uow.commit()
```

The `STOPPING -> STOPPING` transition is **not** allowed: `_SERVER_TRANSITIONS`
(`aggregate.py:77`) contains only `{STOPPED, CRASHED}` at HEAD (plus `RUNNING` after
CV3-2), and `_transition_to` (`aggregate.py:297-304`) raises `InvalidValueError` for a
target absent from the source set. Skipping `server.stop()` is therefore required, not
optional. The enclosing `async with UnitOfWork` still exits normally; its implicit commit
(`unit_of_work.py:52-59`) is a no-op because no changes or events were queued on the
`STOPPING` path. For a `STOPPING` input the handler proceeds directly to the shutdown
timeline/provider block at `:67-163` and then to exactly one of outcomes (i)/(ii)/(iii).
No new `ServerStoppingEvent` is emitted for the re-probe. `STOPPED`, `CRASHED`,
`CREATED`, `PROVISIONING`, `BROKEN`, `RESTORING` and `PROVISIONING_FAILED` still raise
`ServerNotRunningError` at the gate.

**Promotion stop gate (`promote_commit.py`).**

13. Replace the discarded stop call (`:178-181`) with:
    - compute `was_running = server.status in (ServerStatus.RUNNING, ServerStatus.STARTING,
      ServerStatus.STOPPING)` (R3; `:179`);
    - if `was_running` and `self._command_bus is None`: abort (D-A);
    - if `was_running` and there is no runtime handle (`server.runtime is None` or empty
      `external_id`): abort (nothing can be verified);
    - send `stop_result = await self._command_bus.send(StopServerCommand(...))` inside
      `try/except Exception` (R6). Any exception (including a timeout or bus-level failure)
      is treated as **not confirmed** with reason `stop command raised: <exc>` and takes
      the abort path; it must not propagate past the gate.
    - if `not stop_result.success`: abort;
    - read `data = stop_result.data or {}`; abort unless **all** of
      `data.get("stop_confirmed") is True`, `not data.get("warnings")`, and
      `not data.get("provider_errors")` hold. Inconsistent results
      (`stop_confirmed=True` with non-empty warnings/errors, or `stop_confirmed=False`
      with empty lists) therefore still abort (R4e).
    - Outcome (ii) (`stop_confirmed=False`, non-empty warnings) and outcome (iii)
      (`stop_confirmed=False`, possibly empty warnings) both abort here before any write.
      Outcome (ii) has already reverted the row to `RUNNING`, so a subsequent promote
      re-sends the stop.
14. The abort path returns `CommandResult(success=False, ...)` **before** the config loop,
    mods swap, world swap, cleanup and restart. No file is touched.
15. Restart result (`:217-219`) is no longer discarded: record
    `restart_attempted`, `restart_ok`, `restart_error_code`, `restart_error` in
    `CommandResult.details`. Promotion remains `success=True` if the swap already happened;
    a restart failure is reported as a warning, not as an un-applied promotion.

#### Authoritative definition of "stop confirmed" (owner-approved; not re-openable)

**Owner decision: Option 1, hardened. Implement exactly this.** Definition:

> Stop is confirmed iff `StopServerCommand` returned `success=True` **and**
> `data["stop_confirmed"] is True` **and** `data["warnings"]` and `data["provider_errors"]`
> are empty. `stop_confirmed` is true only when the handler actually queried a provider
> runtime handle and all provider/port checks passed. If the server was running but had no
> runtime handle, confirmation is false (fail closed).

Outcomes (ii) and (iii) in item 12 are both non-confirmed: (ii) exposes
`stop_outcome="still_running"` with non-empty warnings and reverts the row to `RUNNING`;
(iii) exposes `stop_outcome="unknown"` and leaves the row at `STOPPING`.

Analysis with code evidence:

| Option | Evidence | Verdict |
|---|---|---|
| (1) `CommandResult.success` + no `provider_errors`/`warnings` | Stop already aggregates the real signals into `provider_errors` (`stop_server.py:67`, `:94-156`) and demotes them to `warnings` while still returning `success=True` (`:183-194`). `CommandBus` never raises (`command_bus.py:105-121`). The only hole is the swallowed probe exception (`:134-135`) and the skipped block when there is no runtime handle (`:74`); both are closed by items 10-13. `mark_stopped()` is additionally gated by the v3 three-outcome branch (item 12). | **Recommended.** Closest to ground truth, already computed in the handler, no layer violation. |
| (2) Re-read DB status and require `STOPPED` | `mark_stopped()` is unconditional (`stop_server.py:165-173`), so the DB value only proves the handler reached the end. Additionally, the promote session uses `expire_on_commit=False` (`backend/app/core/persistence/db.py:100`) and `SQLServerRepository.get` is a plain `session.get` (`backend/app/modules/server/infrastructure/repository.py:35-41`); the first fetch at `promote_commit.py:103` is cached in the identity map, so a second `get` in the same session can return the stale `RUNNING` object. Making it authoritative would require a refresh/new session. | Not authoritative; too weak. |
| (3) Provider status or port-free probe from promote | The status probe already exists in the stop handler (`stop_server.py:112-135`) and port probing at `:137-156`; duplicating it in the versioning application layer would import server infrastructure (`provider_factory`, `ServerHandle`) into `versioning/application`, breaking the hexagonal dependency direction. A port probe alone races with port reuse and is not proof for non-TCP providers. | Reject as the primary definition; keep provider/port checks inside the stop handler where they already live. |

Optional cheap secondary invariant (not a gate): stop may also be considered suspected when
the long-lived promote session's stale status disagrees. Because it is stale by design, do not
gate on it; if the owner wants DB corroboration, it must be a fresh session/refresh and that
is a separate change.

**Exact abort contract.** `PromoteCommitHandler` returns:

```python
CommandResult(
    success=False,
    error_code="PROMOTE_STOP_NOT_CONFIRMED",
    error=(
        f"Promote aborted before writing files: server '{server_id}' was running but "
        f"stop was not confirmed ({reason}). No config, mods, or world files were changed."
    ),
    details={
        "server_id": server_id,
        "test_id": test_id,
        "commit_id": commit.id,
        "stop_attempted": bool,
        "stop_error_code": str | None,
        "stop_outcome": str | None,
        "runtime_verified": bool,
        "warnings": list[str],
        "provider_errors": list[str],
    },
)
```

- `reason` is one of: `no command bus available`, `no runtime handle to verify stop`,
  `stop command failed: <code/error>`, `stop command raised: <exc>` (R6),
  `stop reported warnings/provider errors`, `stop_confirmed was not true`.
- The abort is decision-only: it happens before any config/mods/world write, so a second
  request after a failed stop is still gated (CV3-2 + R3).
- HTTP status: add `"PROMOTE_STOP_NOT_CONFIRMED": 409` to `_ERROR_STATUS_MAP`
  (`backend/app/api/errors.py:23-47`). `check_command_result` (`:50-60`) then returns HTTP
  409 with the same code and message. **No new exception type is introduced**; this is a
  `CommandResult.error_code` handled by the existing generic `MCSError` path.
- No activity log/event is emitted for the aborted promotion. The force-bypass audit row
  (`promote_commit.py:171`) may already be durable because `SQLActivityRepository.save`
  commits immediately; moving it is explicitly out of scope (D-E) and listed as follow-up.

### F1-2c — Reconciliation STOPPING fail-open fix (D-F1-2c)

This is a **separately landable sub-batch inside the same release batch**. It touches only
the reconciliation path (plus its tests) and can be reviewed/committed independently of
F1-2a/F1-2b. It must not be folded into the stop-handler commit.

16. In the `STOPPING` branch of `reconcile_servers`
    (`backend/app/modules/server/application/reconciliation.py:274-289`), stop calling
    `server.mark_stopped()` unconditionally. Branch on the `status` already computed at
    `:136-141`:
    - `status == ServerRuntimeStatus.STOPPED` -> `server.mark_stopped()` and
      `await repo.save(server)` exactly as today; result
      `{"action": "repaired", "new_status": "stopped", "reason": "stale STOPPING state — backend restarted"}`
      (unchanged).
    - `status == ServerRuntimeStatus.RUNNING` -> call the new
      `server.revert_to_running()` (CV3-2 transition `STOPPING -> RUNNING`), then
      `await repo.save(server)`; result
      `{"action": "reverted", "new_status": "running", "reason": "provider reports RUNNING — STOPPING reverted"}`.
      The runtime handle is preserved because `revert_to_running()` does not rebuild it.
    - **Anything else** (`ServerRuntimeStatus.ERROR` from the probe-exception path at
      `:140-141`, `ServerRuntimeStatus.UNKNOWN`, or any future value) -> do **not** call
      `mark_stopped()` or `revert_to_running()`, do **not** save, and log a warning such as
      `Server %s is STOPPING but provider status is %s — leaving STOPPING`. Append a result
      entry with `{"action": "unconfirmed", "new_status": "stopping", "reason": "provider status unknown — left STOPPING"}`
      so the startup log shows the unresolved row. Never mark `STOPPED` without a provider
      `STOPPED`.
17. Do not change `PROVISIONING`, `STARTING`, `RUNNING` or `CRASHED` branches. Do not add a
    retry, a new timeout, a background job, or a periodic reconciliation trigger. The only
    trigger remains the startup lifespan call at `backend/app/main.py:126`.
18. The existing test `test_stopping_server_marked_stopped`
    (`backend/tests/application/test_reconciliation.py:137-151`) uses a bare `MagicMock`
    provider; its `status` call raises, which the code converts to `ERROR`. Under F1-2c it
    would leave the row `STOPPING` and fail. Update it to mock
    `provider.status` -> `ServerRuntimeStatus.STOPPED` (the STOPPED case), and add the three
    tests listed under Tests & Verification (F1-2c).

---

## Affected Components

### F1-2a

| File | Change |
|---|---|
| `backend/app/modules/server/infrastructure/fs.py` | Add `write_text_atomic` to `FileSystem` (`:12-65`, beside `:56`); add implementation; rewrite `write_binary_atomic` (`:165-177`); add POSIX parent-dir fsync helper. |
| `backend/app/modules/versioning/application/commands/promote_commit.py` | Add `fs` constructor dependency; import `FileSystem, local_fs`; replace `Path.write_text` at `:188`; wrap in `FilesystemOperationError`. |
| `backend/tests/infrastructure/test_fs.py` | New helper tests (atomicity, fsync, short write, fd close). |
| `backend/tests/application/test_promote_and_rollback.py` | New promote config-write tests using an injected fake/real filesystem. |

Import edits (F1-2a):

- `promote_commit.py`: add
  `from app.modules.server.infrastructure.fs import FileSystem, local_fs`.
  `FilesystemOperationError` is added to the existing import from
  `app.core.exceptions` (`:8`).
- `fs.py`: no new module import needed if POSIX detection uses `os.name`; `contextlib`,
  `os`, `tempfile`, `Path` are already imported (`:3-9`).
- Tests: `os`, `pytest`, `LocalFileSystem`/`FileSystem` as needed.

### F1-2b

| File | Change |
|---|---|
| `backend/app/modules/versioning/application/commands/promote_commit.py` | Add `STOPPING` to `was_running` (`:179`, R3); replace stop/restart result discards with checks, `try/except` around the stop send (R6), and abort/result reporting (`:178-181`, `:217-219`). Both non-confirmed stop outcomes (still running and unknown) abort before any write. |
| `backend/app/modules/server/application/commands/stop_server.py` | **D-O1 gate widening:** accept `RUNNING`/`STARTING`/`STOPPING` at `:51-52`; for `STOPPING`, skip `server.stop()` at `:53` and the first write/commit at `:54-58` (because `STOPPING -> STOPPING` is rejected), then go straight to provider verification. Capture `runtime_verified` at `:67` (consumed at `:74`) before the `:167` rebind (R1); track `still_running` from the provider status (`:113`) and port check (`:137-156`); record status-probe exceptions as provider errors (`:134-135`); branch (i)/(ii)/(iii) in the second UnitOfWork: `mark_stopped()` (`:168`), `revert_to_running()`, or no status write; add `stop_confirmed`/`stop_outcome`/`runtime_verified`/`provider_errors` to result data (`:183-194`); emit the unknown-outcome warning/activity event. |
| `backend/app/modules/server/domain/aggregate.py` | Add `RUNNING` to the `ServerStatus.STOPPING` entry in `_SERVER_TRANSITIONS` (`:77`); add `revert_to_running()` beside `stop()`/`mark_stopped()` (`:380-393`) that transitions `STOPPING -> RUNNING`, leaves the runtime handle unchanged, and rejects non-`STOPPING` sources; guard `mark_running()` (`:352-378`) against a `STOPPING` source so it cannot be used as the revert path. `STOPPING -> STOPPING` remains disallowed (`:77`, `:297-304`). |
| `backend/app/modules/server/domain/events.py` | Add `ServerStopUnknownEvent` for the D-O1 visibility requirement (fields: `server_id`, `stop_outcome="unknown"`, `runtime_verified`, `warnings`, `provider_errors`). |
| `backend/app/modules/activity/application/subscriber.py` | Map `ServerStopUnknownEvent` to activity `event_type="server.stop_unknown"` with a stable summary (`:57-85` pattern). |
| `backend/app/registration.py` | Register `ServerStopUnknownEvent` in the activity subscriber's `activity_events` list (`:300-327`). |
| `backend/app/api/errors.py` | Add `PROMOTE_STOP_NOT_CONFIRMED: 409` to `_ERROR_STATUS_MAP` (`:23-47`). |
| `backend/tests/application/test_promote_and_rollback.py` | Stop-abort, no-write/checksum, STOPPING, second-attempt (still-running and unknown re-probe), inconsistent-result, cleanup/restart suppression, restart-failure tests. |
| `backend/tests/application/test_server_commands.py` | `stop_confirmed` / no-handle / probe-exception / three-outcome DB-invariant tests; still-running -> `RUNNING` with pid/port/external_id preserved; unknown -> `STOPPING` with `external_id` preserved; `revert_to_running()`/transition tests; widened-gate acceptance of `STOPPING` and guard rejection of `STOPPED`/`CRASHED`/`CREATED`; unknown activity-log record; confirmed-stop test must set a non-empty `external_id`. |
| `backend/tests/infrastructure/test_fs.py` | R4b/R4c/R4f helper tests (temp removal, post-replace fsync, real `tmp_path` integration). |
| `backend/tests/api/test_versioning_api.py` | HTTP 409 contract test for the abort code. |

Import edits (F1-2b): none required beyond F1-2a. `StopServerCommand`,
`StartServerCommand` and `ServerStatus` are already imported in `promote_commit.py:12-14`.
`ServerStopUnknownEvent` must be imported by `stop_server.py` and the activity subscriber.

### F1-2c (separately landable sub-batch)

| File | Change |
|---|---|
| `backend/app/modules/server/application/reconciliation.py` | Replace the unconditional `mark_stopped()` in the `STOPPING` branch (`:274-289`, call at `:279`) with the provider-status switch: `STOPPED` -> `mark_stopped()`; `RUNNING` -> `revert_to_running()`; any other value or `ERROR` -> leave `STOPPING`, log a warning, append an `unconfirmed` result. |
| `backend/tests/application/test_reconciliation.py` | Update `test_stopping_server_marked_stopped` (`:137-151`) to mock provider `STOPPED`; add the three F1-2c tests (RUNNING -> not STOPPED; unknown/ERROR -> not STOPPED; STOPPED -> STOPPED). |

No other production file is touched by F1-2c. It depends on `revert_to_running()` from
F1-2b (CV3-2); if F1-2c lands first, that method must already exist.

### Coupling and blast radius (R8)

`backend/app/modules/versioning/application/commands/promote_commit.py` will import
`app.modules.server.infrastructure.fs` (an application layer importing another module's
infrastructure). This is a real dependency-direction violation. **Owner decision: accept it
for this batch** because there is an existing precedent (`identity_writer.py`,
`jar_service.py`, `filesystem_reconciliation.py` already pass `FileSystem`/`local_fs` across
layers) and because a protocol extraction is larger than this batch. Track it as follow-up
**`F-U-PROMOTE-FS-PROTOCOL-01`** (move the filesystem port to a shared/core location or inject
it at the composition root; do not do it here).

Blast radius of hardening `LocalFileSystem.write_binary_atomic` (all callers inherit fsync,
short-write loop, and failure-ordering changes; each was verified at HEAD `0a62d45`):

| Caller | Line(s) |
|---|---|
| `backend/app/modules/server/application/services/identity_writer.py` | 50 |
| `backend/app/modules/server/application/services/jar_service.py` | 763, 807 |
| `backend/app/modules/server/application/services/filesystem_reconciliation.py` | 1158 |
| `backend/app/modules/plugin/application/commands/install_modrinth_plugin.py` | 163 |
| `backend/app/api/v1/routers/files.py` | 154, 201 |

Tests that mock `write_binary_atomic` (`test_forge_provisioner.py:76`,
`test_installer_provisioner.py:86`, `test_jar_service.py:678,711`) keep the same signature
and should not need changes, but must still pass.

---

## Interfaces & Contracts

### Helper signatures

```python
class FileSystem(ABC):
    @abstractmethod
    def write_text(self, path: str, content: str) -> None: ...          # existing, unchanged

    @abstractmethod
    def write_text_atomic(self, path: str, content: str, encoding: str = "utf-8") -> None: ...

    @abstractmethod
    def write_binary_atomic(self, path: str, content: bytes) -> None: ...  # existing, hardened


class LocalFileSystem(FileSystem):
    def write_text_atomic(self, path: str, content: str, encoding: str = "utf-8") -> None: ...
    def write_binary_atomic(self, path: str, content: bytes) -> None: ...
    def _fsync_parent_dir(self, parent: Path) -> None: ...  # POSIX fsync; no-op elsewhere
```

Semantics:

- Existing callers of `write_binary_atomic` keep the same signature and behavior, plus
  durability and correct error handling.
- `write_text_atomic` creates parent directories (via the binary helper) and replaces the
  destination atomically.
- On pre-replace failure, the fd is closed first, then the temp file is removed (Windows
  cannot unlink an open file), and the destination is unchanged.
- On post-replace parent-fsync failure, `replaced` is already `True`: the new content is in
  place, the temp path is **not** unlinked, and the error is raised. Callers must treat this
  as a durability warning with a completed replacement.
- An `os.close` error in the `finally` block must not mask the original exception.

### Server status transitions (F1-2b)

New allowed transition and named method:

```python
_SERVER_TRANSITIONS[ServerStatus.STOPPING] = {
    ServerStatus.STOPPED,
    ServerStatus.CRASHED,
    ServerStatus.RUNNING,   # new in v3
}

class Server:
    def revert_to_running(self) -> None:
        """STOPPING -> RUNNING; runtime handle untouched. No new domain event."""
        if self._status is not ServerStatus.STOPPING:
            raise InvalidValueError(...)   # already imported at aggregate.py:7
        self._transition_to(ServerStatus.RUNNING)
```

- `revert_to_running()` is the only public method that may move `STOPPING -> RUNNING`;
  `mark_running()` raises `InvalidValueError` when the current status is `STOPPING`.
- It also rejects a non-`STOPPING` source, so it cannot be called from `STOPPED`/`CRASHED`
  where the runtime handle may already be stale.
- It does not emit a new event type (the application layer logs a warning); this avoids
  adding a new event-bus surface.
- `mark_stopped()` remains the only method that clears `external_id` (`:391`).

### Stop command accepted statuses (D-O1)

`StopServerCommand` / `StopServerHandler` input contract:

| Stored status | Gate (`stop_server.py:51-52`) | First UnitOfWork (`:53-58`) | Then |
|---|---|---|---|
| `RUNNING` | accepted | `server.stop()` -> `STOPPING`, save, commit | provider verification -> outcome (i)/(ii)/(iii) |
| `STARTING` | accepted | `server.stop()` -> `STOPPING`, save, commit | provider verification -> outcome (i)/(ii)/(iii) |
| `STOPPING` | **accepted (D-O1)** | **skipped** (`STOPPING -> STOPPING` is not allowed) | provider verification with the existing runtime handle -> outcome (i)/(ii)/(iii) |
| all others (`STOPPED`, `CRASHED`, `CREATED`, `PROVISIONING`, `PROVISIONING_FAILED`, `BROKEN`, `RESTORING`) | rejected | none | `ServerNotRunningError` -> `CommandResult(success=False)` via `CommandBus` |

Outcome (i) is the only path that sets `stop_outcome="stopped"` and calls
`mark_stopped()`. Outcome (ii) sets `stop_outcome="still_running"` and calls
`revert_to_running()` (including for a `STOPPING` input). Outcome (iii) sets
`stop_outcome="unknown"`, leaves the status exactly as it was before the request
(`STOPPING` for both the normal first-stop path after `:58` and the D-O1 re-probe path),
and records the activity event.

### Reconciliation STOPPING outcomes (F1-2c)

`reconcile_servers` (`reconciliation.py:274-289`) uses the provider status from `:136-141`:

| Provider status | Action | Result |
|---|---|---|
| `STOPPED` | `mark_stopped()` + save | `action="repaired"`, `new_status="stopped"` |
| `RUNNING` | `revert_to_running()` + save | `action="reverted"`, `new_status="running"` |
| `ERROR` (probe exception at `:140-141`), `UNKNOWN`, or any other value | no write; warning log | `action="unconfirmed"`, `new_status="stopping"` |

`mark_stopped()` is never called without a provider `STOPPED`.

### Promotion result / error codes

| Situation | Channel | Code | HTTP |
|---|---|---|---|
| Stop not confirmed (all reasons above) | `CommandResult(success=False)` | `PROMOTE_STOP_NOT_CONFIRMED` | 409 |
| Config write failure | existing `FilesystemOperationError` (`INFRASTRUCTURE_ERROR`) | `INFRASTRUCTURE_ERROR` | 503 |
| Restart failure after successful swap | `CommandResult(success=True)` + details (`restart_ok=False`) | n/a (promotion succeeded) | 200 |
| Success | `CommandResult(success=True)` | n/a | 200 |

Existing gating errors (`ValidationError` for test status, `NotFoundError` for missing
entities) are unchanged (`promote_commit.py:102-145`).

### Permission and route impact

- **None.** The route, HTTP method, path, request schema and permission
  (`server:version:promote`, plus force permission) are unchanged
  (`versioning.py:370-391`); `contracts/permissions.yaml` needs no edit.
- No database migration, no new dependency, no new exception class. The only API-adjacent
  addition is an entry in the existing error-code-to-status map.

---

## Failure/Edge Cases

| Case | Behavior |
|---|---|
| Stop command fails (`success=False`, including `SERVER_NOT_RUNNING`) | Abort before any file write; code `PROMOTE_STOP_NOT_CONFIRMED`; no mods/world swap, no test cleanup, no restart. |
| Stop command raises instead of returning a result | `try/except Exception` around the send (R6); treat as not confirmed, abort with reason `stop command raised: <exc>`; no writes. |
| Stop returns `success=True`, provider status `RUNNING` and/or port still listening | Outcome (ii): `revert_to_running()`; DB status `RUNNING`; `external_id`/`pid`/`port` preserved; `stop_confirmed=False`, `stop_outcome="still_running"`, warnings non-empty. Promotion aborts before any file write. |
| Stop returns `success=True` with `provider_errors` but no positive still-running evidence | Outcome (iii): row stays `STOPPING`; `mark_stopped()`/`revert_to_running()` not called; `external_id` preserved; `stop_confirmed=False`, `stop_outcome="unknown"`; activity log records `server.stop_unknown`. Promotion aborts (D-O1 residual risk). |
| `stop_confirmed` missing or `False`, even with empty error lists | Abort before any file write (R4e inconsistent-result mutant). |
| `stop_confirmed=True` but warnings/errors non-empty | Abort before any file write (R4e inconsistent-result mutant); do not trust the boolean alone. |
| `command_bus is None` while server was running | Abort before any file write (fail closed). |
| Server was running but has no runtime handle / empty `external_id` | Outcome (iii): row stays `STOPPING`, `external_id` preserved, `stop_confirmed=False`; promotion aborts before any write (R1/CV3-2/R4a; D-O1 residual risk). |
| Provider status probe raises during stop | Recorded as a provider error (`stop_server.py:134-135`); outcome (iii) unless the port is still listening, in which case outcome (ii) wins by precedence; `stop_confirmed=False`, promotion aborts. |
| Provider status probe raises but the port is still listening | Outcome (ii) by the still-running precedence rule: `revert_to_running()`, status `RUNNING`, runtime preserved; promotion aborts. |
| Unconfirmed stop (still running), then a second promote request | First stop leaves the row `RUNNING` with the runtime handle intact. The second promote sees `RUNNING` in `was_running` (R3) and re-sends the stop. If the provider now confirms `STOPPED`/port free, promotion proceeds; if it is still running, the stop handler takes (ii) again and the second promote aborts with `PROMOTE_STOP_NOT_CONFIRMED` before any write. |
| Unknown stop (`STOPPING`), then a second promote request | **D-O1:** `STOPPING` is accepted by the widened gate (`:51-52`); the handler skips `server.stop()`/the first write (`:53-58`) and re-probes with the existing runtime handle. If the provider now confirms `STOPPED`, the second promote proceeds; if it still reports `RUNNING`, outcome (ii) reverts to `RUNNING`; if the probe is still unknown, outcome (iii) leaves `STOPPING` and the second promote aborts with `PROMOTE_STOP_NOT_CONFIRMED` before any write. No `ServerNotRunningError` for this status. |
| Second promote still cannot confirm (persistent probe failure) | The row remains `STOPPING`; each attempt returns `stop_outcome="unknown"` and records `server.stop_unknown` in the activity log. There is no automatic retry, new timeout, or force endpoint; recovery requires a later successful probe. **Residual risk accepted by D-O1.** |
| Confirmed stop | `mark_stopped()` runs once (R1 uses the captured pre-stop handle, not the post-rebind object); `revert_to_running()` is not called. |
| Helper fails on file 2 of N configs | File 1 remains changed (per-file atomicity only); handler raises `FilesystemOperationError`; test cleanup and restart are not run. All-or-nothing is deferred. |
| Short write (`os.write` returns fewer bytes) | Loop continues until the whole buffer is written; `0`/negative is an `OSError`; fd closed, then temp removed, destination unchanged. |
| `fsync(file)` fails | fd closed, temp removed, destination unchanged, error propagates. |
| `os.replace` fails | `replaced` stays `False`; fd closed, temp removed, destination unchanged; original error propagates. |
| `fsync(parent)` fails (POSIX), after `os.replace` | `replaced is True`; destination already replaced (new bytes); temp path is **not** unlinked; error propagates. Caller sees a failure with a completed replacement. |
| `os.close` fails in `finally` | The close error is suppressed/logged; the original write/replace exception still propagates (R5). |
| Parent-directory fsync unsupported (Windows) | POSIX branch is skipped; file fsync still runs; no error. Windows durability is **UNVERIFIED**. |
| Promote aborts before any write | Config files, mods and world are byte-identical to pre-request state; `_atomic_replace_dir` is not called (checksum assertion, R4d). A force-promote audit row may already exist because `SQLActivityRepository.save` commits (`activity/infrastructure/repository.py:44-60`); see D-E. |
| Restart fails after a successful swap | Promotion stays `success=True`; details report `restart_ok=False`, `restart_error_code`, `restart_error`; the new files remain live. |
| Server DB status says `STOPPED` but runtime was never verified | Not accepted as confirmation; `stop_confirmed` is the gate, not DB status. |
| Reconciliation: `STOPPING` + provider `RUNNING` | `revert_to_running()`; DB `RUNNING`; runtime handle preserved; no `mark_stopped()` (F1-2c). |
| Reconciliation: `STOPPING` + provider `ERROR`/`UNKNOWN` | Leave `STOPPING`, do not save, log a warning, result `action="unconfirmed"`; no `mark_stopped()` (F1-2c). |
| Reconciliation: `STOPPING` + provider `STOPPED` | `mark_stopped()` + save, as before (F1-2c). |

---

## Open Questions

### O-1 — RESOLVED by D-O1: recovery from the UNKNOWN stop outcome

**Status: RESOLVED (owner decision D-O1, 2026-10-20, option b).** This section is retained
for history. Option (b) is implemented in item 12a; the reconciliation fail-open mentioned
under option (a) is fixed separately by F1-2c (D-F1-2c).

The three-outcome design (item 12) leaves outcome (iii) fail-closed: after a provider probe
failure/timeout or a no-runtime-handle stop, the row stays `STOPPING` with the runtime
handle retained. At v3, `STOPPING` was not accepted by `StopServerHandler` (`:51-52`), so
the promote flow could not re-verify it. The owner chose (b): accept `STOPPING` as a
re-verification input. Options considered:

| Option | What changes | Trade-offs | Code evidence |
|---|---|---|---|
| (a) Accept `STOPPING` until a later successful probe | No gate change; rely on a later probe/reconciliation to advance the row | Smallest surface, keeps fail-closed. But there is no automatic re-probe in the stop/promote path today, so the row can stay `STOPPING` indefinitely. The existing reconciliation branch marks `STOPPING -> STOPPED` unconditionally and does **not** check the provider status it computed; using it as the "later successful probe" would be a fail-open unless fixed first. | `stop_server.py:51-52`; `reconciliation.py:136-141,274-289` |
| (b) Accept `STOPPING` as a re-verify input | Widen the stop handler gate at `:51-52` so a `STOPPING` server can be re-stopped/re-probed; **CHOSEN by the owner (D-O1)** | Gives an in-band recovery path through the existing `StopServerCommand` and the promote flow (R3 already includes `STOPPING` in `was_running`). It changes the command's accepted input states; `server.stop()` at `:53` calls `_transition_to(STOPPING)`, and `STOPPING -> STOPPING` is not in the transition table (`:77`), so the handler **must** skip `stop()`/the first write when the row is already `STOPPING` (item 12a) rather than widening the table implicitly. No duplicate `ServerStoppingEvent` is emitted on the re-probe. | `stop_server.py:51-53`; `aggregate.py:77,297-304,380-382`; `promote_commit.py:179-181` |
| (c) Manual force-stop endpoint | New route/permission/command surface for an operator-triggered force stop | Gives an explicit escape hatch without changing the stop command's input contract, but adds API/permission surface (the current stop route is `POST /api/v1/servers/{server_id}/stop` with `server.{id}.power`, no force flag). **Not chosen; still out of scope.** | `servers.py:337-345`; `stop_server.py:51-52` |

**Residual risk (accepted with D-O1).** If the provider probe keeps failing, the server
stays `STOPPING` until a probe succeeds. There is no automatic retry, no new timeout, and no
force endpoint. Visibility is mandatory: the stop result carries `stop_outcome="unknown"`
and the activity log records `server.stop_unknown` (item 12 (iii)). F1-2c removes the other
fail-open path (reconciliation) but does not add a retry.

---

## Tests & Verification

Design-completion note: no test was executed in this design session. Counts in
`.ai/STATE.json` are from 2026-10-04 and are not claimed as current. The builder must write
the failing tests first, observe them fail on HEAD `0a62d45`, then implement.

### Failing tests first (name -> expected failure on current code)

**F1-2a**

| Test | Expected failure on HEAD |
|---|---|
| `test_write_text_atomic_writes_utf8_and_replaces_existing` | `AttributeError` — method does not exist. |
| `test_write_binary_atomic_fsyncs_file_before_replace` | No `fsync` call at all (`fs.py:170-173`). |
| `test_write_binary_atomic_fsyncs_parent_directory_on_posix` | No parent-directory fsync/helper exists. |
| `test_write_binary_atomic_handles_short_writes` | Single unchecked `os.write` truncates content (`fs.py:171`). |
| `test_write_binary_atomic_closes_fd_when_write_fails` | fd is left open; `os.close` is inside the failing `try` (`fs.py:171-172`). |
| `test_write_binary_atomic_leaves_destination_untouched_when_fsync_fails` | No `fsync`, so the replace still happens. |
| `test_write_binary_atomic_removes_temp_file_on_failure_before_replace` (R4b) | Helper may leave the temp file, and closes inside the failing `try`; assert no `*.tmp` sibling remains on a write/fsync failure before `os.replace`. |
| `test_write_binary_atomic_parent_fsync_failure_after_replace_keeps_destination` (R4c) | No parent fsync exists; monkeypatch `os.fsync` to raise only for the directory fd, assert the call raises and the destination still has the new bytes and is not unlinked. |
| `test_write_binary_atomic_close_error_does_not_mask_original` (R5) | No guarded close; monkeypatch `os.close` to raise while `os.write` also raises, assert the original write exception surfaces. |
| `test_write_text_atomic_integration_real_tmp_path` (R4f) | `AttributeError` — method does not exist. Use a real `tmp_path`, `LocalFileSystem`, and monkeypatch only `os.fsync`/`os.replace` if needed; no fake filesystem. |
| `test_promote_uses_atomic_text_writer_for_configs` | Handler never calls the injected fs; uses `Path.write_text` (`:188`). |
| `test_promote_config_write_failure_on_second_file_raises_filesystem_error` | Fake fs is unused; both files are written and success is returned. |

**F1-2b**

| Test | Expected failure on HEAD |
|---|---|
| `test_promote_aborts_before_write_when_stop_result_fails` | Stop result ignored; config is overwritten and success returned (`:180-188`). |
| `test_promote_aborts_when_stop_result_has_warnings` | Warnings ignored; write proceeds. |
| `test_promote_aborts_when_stop_confirmed_is_false` | Field is never consulted. |
| `test_promote_fails_closed_when_running_and_command_bus_is_none` | `if was_running and self._command_bus` is false, so stop is skipped and write proceeds (`:180`). |
| `test_promote_aborts_when_running_server_has_no_runtime_handle` | No such check; write proceeds. |
| `test_promote_does_not_cleanup_or_restart_when_stop_not_confirmed` | Cleanup/restart run only after writes; current code reaches them. |
| `test_promote_aborts_when_status_is_stopping` (R3) | `STOPPING` is not in `was_running` (`:179`), so the stop is skipped and files are written; must abort before any write. |
| `test_promote_abort_does_not_replace_dirs_and_files_are_byte_identical` (R4d) | No abort path exists; `_atomic_replace_dir` runs and configs change. Spy/patch `_atomic_replace_dir` to assert it was not called, and compare checksums of every `mods`/`world*` file before and after. |
| `test_promote_aborts_when_stop_result_has_confirmed_true_and_warnings` (R4e) | Boolean/empty-list consistency is not checked; write proceeds. |
| `test_promote_aborts_when_stop_result_has_confirmed_false_and_empty_errors` (R4e) | `stop_confirmed` is never consulted; write proceeds. |
| `test_promote_aborts_when_stop_command_raises` (R6) | Exception would propagate out of `_execute`; must be caught, reported as not confirmed, and abort before writes. |
| `test_stop_result_marks_not_confirmed_when_provider_stop_fails` | `data["stop_confirmed"]` missing. |
| `test_stop_result_marks_not_confirmed_when_provider_status_probe_raises` | Exception is swallowed (`stop_server.py:134-135`), so even the new key would be absent. |
| `test_stop_result_not_confirmed_without_runtime_handle_or_empty_external_id` (R4a) | Key absent; no explicit no-handle branch exists. Cover both `runtime is None` and `external_id == ""`. |
| `test_stop_result_marks_confirmed_when_running_with_external_id_and_provider_confirms_stopped` (R1) | Key absent. **Requirement:** the existing `_create_test_server(make_running=True)` fixture (`test_server_commands.py:70-102`) calls `mark_running(pid=100, port=25565)` with no `external_id`, so this test must explicitly set a **non-empty** `external_id` (e.g. `server.mark_running(..., external_id="ext-confirmed")` then save) and mock the provider `status` to `STOPPED`; otherwise `runtime_verified` is false. |
| `test_stop_still_running_reverts_to_running_and_preserves_runtime` (CV3-2 ii) | `mark_stopped()` is unconditional (`:168`), so status becomes `STOPPED` and `external_id` is cleared. Assert status is `RUNNING` (not `STOPPED`, not `STOPPING`), `pid`/`port`/`external_id` are unchanged, `stop_confirmed=False`, `stop_outcome="still_running"`, and warnings are non-empty. Drive it with provider status `RUNNING` and with the port still listening as two parametrized cases. |
| `test_stop_unknown_leaves_stopping_and_preserves_external_id` (CV3-2 iii) | `mark_stopped()` is unconditional (`:168`), so status becomes `STOPPED`. Assert status stays `STOPPING`, `external_id` is unchanged, `stop_confirmed=False`, `stop_outcome="unknown"`. Cover (a) provider status probe raising/timing out and (b) no runtime handle / empty `external_id`. |
| `test_stop_probe_raises_but_port_listening_reverts_to_running` (CV3-2 precedence) | New behavior: positive still-running evidence wins; assert `RUNNING` and preserved runtime handle even though the probe raised. |
| `test_revert_to_running_preserves_pid_port_external_id` (CV3-2) | `revert_to_running()` does not exist at HEAD (`AttributeError`). Assert `status == RUNNING`, and `runtime.pid`, `runtime.port`, `runtime.external_id` are exactly the pre-stop values; assert `restart_count` is unchanged. |
| `test_stopping_to_running_allowed_only_via_revert_to_running` (CV3-2) | `STOPPING -> RUNNING` is not allowed at HEAD (`InvalidValueError`). Assert `revert_to_running()` succeeds from `STOPPING`, `mark_running(...)` on a `STOPPING` aggregate raises `InvalidValueError` (the guard), and `revert_to_running()` from `STOPPED` also raises, so the named method is the only public path for this transition. |
| `test_transition_table_allows_stopping_to_running` (CV3-2) | `_SERVER_TRANSITIONS[ServerStatus.STOPPING]` at HEAD is `{STOPPED, CRASHED}` (`aggregate.py:77`); assert it becomes `{STOPPED, CRASHED, RUNNING}` and that `STOPPING -> STOPPING` is still rejected. |
| `test_second_promote_after_still_running_stop_aborts_when_still_running` (CV3-2 ii) | First call marks `STOPPED`, so the second call skips the stop and writes files. Assert the first call leaves `RUNNING`, the second call re-sends the stop, and if the provider still reports `RUNNING`/the port still listens, the second promote returns `PROMOTE_STOP_NOT_CONFIRMED` with no files changed. |
| `test_second_promote_after_still_running_stop_succeeds_when_provider_now_stopped` (CV3-2 ii) | Same setup, but the provider now reports `STOPPED` and the port is free; assert the second promote confirms and proceeds (files written, success). This pins "abort **or** confirm correctly". |
| `test_second_promote_after_unknown_stop_reprobes_and_aborts_when_still_unknown` (D-O1, replaces the v3 gate-rejection test) | HEAD marks `STOPPED` on the first call and rejects `STOPPING` at `:51-52`. Assert the first call leaves `STOPPING`; the second promote sends the stop, the handler **accepts** `STOPPING`, skips `server.stop()`/the first write, re-probes, still cannot confirm (`stop_outcome="unknown"`), and promotion returns `PROMOTE_STOP_NOT_CONFIRMED` with no files changed and **no** `ServerNotRunningError`. |
| `test_second_promote_after_unknown_stop_reprobes_and_proceeds_when_provider_now_stopped` (D-O1) | Same setup; the provider now reports `STOPPED` and the port is free. Assert the second promote re-probes via the accepted `STOPPING` gate, confirms (`stop_outcome="stopped"`), and proceeds (files written, success). |
| `test_stop_handler_accepts_stopping_without_calling_stop` (D-O1) | HEAD raises `ServerNotRunningError` at `:51-52`. Assert `handle()` accepts a `STOPPING` aggregate, does not call `server.stop()` (no new `ServerStoppingEvent`/status write), and reaches provider verification. |
| `test_stop_unknown_records_activity_entry` (D-O1 visibility) | No such event/key at HEAD. Assert outcome (iii) publishes `ServerStopUnknownEvent` / persists a `server.stop_unknown` activity row with `stop_outcome="unknown"`, and the `CommandResult.data` carries the same value. |
| `test_promote_reports_restart_failure_after_swap` | Restart result ignored; no `restart_ok` in details. |
| `test_promote_api_returns_409_when_stop_not_confirmed` | Endpoint returns 200 because the handler ignores the stop result. |

> v3 note: the two v2 tests `test_stop_unconfirmed_preserves_db_status_and_external_id`
> and `test_second_promote_after_unconfirmed_stop_still_aborts` are replaced by the
> outcome-specific rows above (still running vs unknown), plus the explicit gate test.
>
> v4 note (D-O1): the v3 test `test_second_promote_after_unknown_stop_aborts_via_not_running_gate`
> and the v3 guard `test_stop_handler_rejects_stopping_status_explicitly` are removed by
> owner decision. A second promote after an unknown stop now re-probes. The rejection guard
> is narrowed to the statuses that remain outside the widened gate
> (`STOPPED`/`CRASHED`/`CREATED`), below.

Guard tests and required updates:

- `test_promote_commit_workflow` and `test_promote_commit_with_keep_world_changes`
  (`test_promote_and_rollback.py:184-321`) for stopped servers.
- `test_promote_succeeds_when_passed_and_no_newer_failures`
  (`test_promote_commit_gating.py:290-323`).
- **Update** `test_stop_running_server` (`test_server_commands.py:386-396`): its
  `_create_test_server(make_running=True)` fixture sets no `external_id` (`:98`), so under
  the new gate it takes outcome (iii) and the row stays `STOPPING`, failing its current
  `status == "stopped"` assertion. Set a non-empty `external_id`, mock provider `status` to
  `STOPPED`, and ensure the port is free so the test takes outcome (i) and still asserts
  `STOPPED` with `external_id` cleared.
- `test_stop_server_unexpected_runtime_status_logged`
  (`test_server_commands.py:398-434`) keeps passing: provider status `ERROR` is outcome
  (iii), but the test only asserts `success=True` and the log strings, not DB status.
- **Update** `test_stop_command_on_starting_server_succeeds`
  (`test_starting_visible.py:220-233`): its fixture does set an `external_id` (`:87`), but
  the test mocks no provider. Under v3 it must mock provider `status` to `STOPPED` (and
  ensure the port is free) to take outcome (i) and still assert `STOPPED`; otherwise it can
  take outcome (iii) and leave `STOPPING`.
- **Add** `test_stop_handler_rejects_stopped_crashed_created` (parametrized `STOPPED`,
  `CRASHED`, `CREATED`): call `StopServerHandler.handle` (or
  `CommandBus.send(StopServerCommand)`) and assert `ServerNotRunningError` /
  `success=False`. This is the guard for the D-O1 widened gate: only `RUNNING`, `STARTING`
  and `STOPPING` are accepted; it must stay green when the gate is widened.
- `test_restart_server_timeout_marks_stopped_and_returns_details` is unaffected because
  `RestartServerHandler` has its own unconditional stop/mark path (`restart_server.py:92-93`)
  and does not use `StopServerCommand`.

**F1-2c** (separately landable sub-batch)

| Test | Expected failure / baseline on HEAD |
|---|---|
| `test_stopping_with_provider_running_reverts_not_stopped` (F1-2c test 1) | `reconciliation.py:279` calls `mark_stopped()` unconditionally, so the status becomes `STOPPED` even though the provider says `RUNNING`. Assert `status == RUNNING`, `runtime.external_id` preserved, `repo.save` called once, and result `new_status="running"` / `action="reverted"`. |
| `test_stopping_with_provider_unknown_leaves_stopping_not_stopped` (F1-2c test 2) | Same unconditional `mark_stopped()`, so both `ServerRuntimeStatus.ERROR` (probe exception at `:140-141`) and `ServerRuntimeStatus.UNKNOWN` become `STOPPED`. Parametrize both; assert `status == STOPPING`, `repo.save` **not** called, warning logged, result `new_status="stopping"` / `action="unconfirmed"`. |
| `test_stopping_with_provider_stopped_marks_stopped` (F1-2c test 3) | This is the behaviour that must be preserved; on HEAD it passes only because `mark_stopped()` is unconditional. Mock provider `STOPPED` and assert `status == STOPPED`, `external_id` cleared, `repo.save` called once, result `new_status="stopped"` / `action="repaired"`. |

The updated `test_stopping_server_marked_stopped` (`test_reconciliation.py:137-151`) must
mock `provider.status` to `STOPPED`; the head test only supplies a bare `MagicMock`, whose
`status` call raises and is mapped to `ERROR` (`:140-141`), so under F1-2c it would leave
the row `STOPPING`.

### Mutation checklist

| Mutation | Test that must fail |
|---|---|
| Remove `os.fsync(fd)` | `test_write_binary_atomic_fsyncs_file_before_replace` |
| Remove parent-directory fsync | `test_write_binary_atomic_fsyncs_parent_directory_on_posix` |
| Replace the short-write loop with a single `os.write` | `test_write_binary_atomic_handles_short_writes` |
| Remove the `finally: os.close(fd)` | `test_write_binary_atomic_closes_fd_when_write_fails` |
| Move `os.replace` before `fsync` | `test_write_binary_atomic_leaves_destination_untouched_when_fsync_fails` |
| Unlink the temp path after a successful `os.replace` (drop `replaced` flag) | `test_write_binary_atomic_parent_fsync_failure_after_replace_keeps_destination` (R5) |
| Unlink before closing the fd (Windows ordering) | `test_write_binary_atomic_removes_temp_file_on_failure_before_replace` (R4b/R5) |
| Let `os.close` in `finally` replace the original error | `test_write_binary_atomic_close_error_does_not_mask_original` (R5) |
| Revert promote to `Path.write_text` | `test_promote_uses_atomic_text_writer_for_configs` |
| Ignore `stop_result.success` | `test_promote_aborts_before_write_when_stop_result_fails` |
| Treat `warnings` as success | `test_promote_aborts_when_stop_result_has_warnings` |
| Skip the stop when `command_bus is None` | `test_promote_fails_closed_when_running_and_command_bus_is_none` |
| Move the stop check below the config loop | `test_promote_aborts_before_write_when_stop_result_fails` (asserts file unchanged) |
| Re-swallow the provider status exception | `test_stop_result_marks_not_confirmed_when_provider_status_probe_raises` |
| Compute `runtime_verified` from the `:167` rebind instead of the pre-stop capture | `test_stop_result_marks_confirmed_when_running_with_external_id_and_provider_confirms_stopped` (R1) |
| Call `mark_stopped()` unconditionally (remove the confirmation gate) | `test_stop_still_running_reverts_to_running_and_preserves_runtime` and `test_stop_unknown_leaves_stopping_and_preserves_external_id` (CV3-2) |
| Call `revert_to_running()` for every non-confirmed stop, including UNKNOWN (allow `STOPPING -> RUNNING` without provider confirmation) | `test_stop_unknown_leaves_stopping_and_preserves_external_id` (CV3-2 iii) |
| Remove `RUNNING` from the `STOPPING` transition entry | `test_transition_table_allows_stopping_to_running` (CV3-2) |
| Use `mark_running()` instead of `revert_to_running()` for the still-running case | `test_revert_to_running_preserves_pid_port_external_id` (CV3-2) |
| Remove `STOPPING` from `was_running` | `test_promote_aborts_when_status_is_stopping` (R3) |
| Trust `stop_confirmed=True` without checking warnings/errors | `test_promote_aborts_when_stop_result_has_confirmed_true_and_warnings` (R4e) |
| Let stop-send exceptions propagate | `test_promote_aborts_when_stop_command_raises` (R6) |
| Ignore the restart result | `test_promote_reports_restart_failure_after_swap` |
| Accept `STOPPED`/`CRASHED` in the widened gate | `test_stop_handler_rejects_stopped_crashed_created` (D-O1 guard; CV4-3) |
| Call `server.stop()` for a `STOPPING` input (re-run the first write) | `test_stop_handler_accepts_stopping_without_calling_stop` (D-O1) |
| Reject `STOPPING` at the gate again (remove the D-O1 widening) | `test_second_promote_after_unknown_stop_reprobes_and_aborts_when_still_unknown` (D-O1) |
| Drop the unknown-outcome activity event/result key | `test_stop_unknown_records_activity_entry` (D-O1 visibility) |
| Mark `STOPPED` in reconciliation without provider confirmation | `test_stopping_with_provider_running_reverts_not_stopped` and `test_stopping_with_provider_unknown_leaves_stopping_not_stopped` (F1-2c tests 1-2) |
| Revert reconciliation to unconditional `mark_stopped()` in the `STOPPING` branch | `test_stopping_with_provider_running_reverts_not_stopped` and `test_stopping_with_provider_unknown_leaves_stopping_not_stopped` (F1-2c) |

### Targeted command

```bash
cd backend && python -m pytest -q \
  tests/infrastructure/test_fs.py \
  tests/application/test_promote_and_rollback.py \
  tests/application/test_promote_commit_gating.py \
  tests/application/test_server_commands.py \
  tests/application/test_reconciliation.py \
  tests/api/test_versioning_api.py
```

Development runs may use `-n auto`; before claiming the batch is clean, run sequentially
(`python -m pytest -q` from `backend/`) or use the CI run, per
`.ai/RULES/testing-and-verification.md`.

### Six quality gates (expect 6/6 PASS)

```bash
./scripts/check-db-revision
./scripts/check-ruff-baseline
./scripts/check-version-propagation
./scripts/check-route-contract
./scripts/check-ps1-bom
./scripts/check-stray-db
```

- `check-db-revision`: no migration is added.
- `check-route-contract`: no route or permission change; only an internal error-code mapping.
- `check-ruff-baseline`: no new lint violations; do not raise the baseline.
- `check-version-propagation`, `check-ps1-bom`, `check-stray-db`: unaffected; `check-stray-db`
  still matters because tests use `tmp_path`/`tempfile`, never bare relative SQLite paths.

### Portability note

- Parent-directory fsync runs only when `os.name == "posix"`; Windows skips it and still
  fsyncs the file.
- Tests must use `tmp_path`/`tempfile.TemporaryDirectory` and must not assume directory
  fsync works on Windows. Mark Windows behavior **UNVERIFIED** until the Windows workflow
  runs.
- Do not write any recon/test artifact to the repository root or `/tmp` from repository tests.

---

## Pre-implementation Requirements (R7)

These are **not created in this design session** (the only write here is this spec). They are
required in the docs-patch stage before implementation:

1. **Decision record** `docs/decisions/0018-promote-atomicity-stop-guard.md` recording:
   - the owner-approved "stop confirmed" definition (success + `stop_confirmed=True` +
     empty `warnings`/`provider_errors`; a running server with no runtime handle is not
     confirmed);
   - the CV3-2 three-outcome decision: never `mark_stopped()` without provider
     confirmation; still running -> `STOPPING -> RUNNING` via `revert_to_running()` with
     the runtime handle preserved; unknown -> leave `STOPPING`;
   - the new `STOPPING -> RUNNING` transition in `_SERVER_TRANSITIONS` and the
     `mark_running()` STOPPING guard;
   - **D-O1** (owner, 2026-10-20, option b): the stop gate accepts `RUNNING`, `STARTING` and
     `STOPPING`; a `STOPPING` input skips `server.stop()`/the first write because
     `STOPPING -> STOPPING` is not allowed, and goes straight to provider verification;
     a second promote re-probes. Record O-1 as **RESOLVED**, including the residual risk
     (a persistent probe failure keeps the row `STOPPING`; visibility via
     `stop_outcome="unknown"` and the activity log) and that no force endpoint, retry, or
     new timeout is added;
   - **D-F1-2c** (owner, 2026-10-20): the reconciliation `STOPPING` branch must only
     `mark_stopped()` on provider `STOPPED`; provider `RUNNING` -> `revert_to_running()`;
     unknown/probe error -> leave `STOPPING` and log a warning. It is a separately landable
     sub-batch;
   - the R3 decision to include `ServerStatus.STOPPING` in the "was running" set.
2. **`.ai/STATE.json` F1-2 item** for this workstream, with the spec path, the split
   F1-2a/F1-2b/F1-2c scope, D-O1 and D-F1-2c as resolved decisions, and the deferred
   all-or-nothing follow-up.
3. **Live runtime verification** of promote with a running server, per
   `.ai/RULES/testing-and-verification.md` (including (i) confirmed stopped, (ii) still
   running -> `RUNNING` with pid/port/external_id preserved, (iii) unknown -> `STOPPING`,
   the D-O1 `STOPPING` re-probe path, and both second-promote paths: re-send on `RUNNING`,
   re-probe on `STOPPING`). Include a startup reconciliation check for F1-2c: a `STOPPING`
   row with a provider `RUNNING` must end `RUNNING`, not `STOPPED`. Targeted pytest alone
   is not sufficient evidence.

---

## Out of Scope

1. **All-or-nothing multi-file promotion / rollback (D-C, deferred).** Per-file atomicity is
   the deliverable; a failure on file 2 of N can still leave file 1 changed. Follow-up:
   `SPEC-2026-10-20-PROMOTE-ALL-OR-NOTHING-01`.
2. **Windows open-handle retry/backoff (D-D).** Fail fast; no retry loop. Windows
   parent-directory durability remains **UNVERIFIED**.
3. **Activity-log early commit (D-E).** `SQLActivityRepository.save` committing the outer
   session before the file swap, including the force-bypass row at
   `promote_commit.py:171`, is unchanged. Follow-up:
   `F-U-ACTIVITY-LOG-COMMIT-ORDERING-01`.
4. **Consolidation of `versioning/infrastructure/fs_atomic.py` and
   `restore_service._atomic_replace_dir` (D-B).** Report only; no refactor in this batch.
5. **Branch-head changes.** Promotion still does not advance branch head; F1-1 already
   handles branch-head CAS separately.
6. **Permission or route changes.** None proposed.
7. **Config path traversal validation** in the manifest write loop. The manifest is treated
   as trusted in this batch; a separate hardening item may be needed.
8. **Filesystem port extraction (R8).** The versioning application layer importing
   `server/infrastructure/fs.py` is accepted for this batch; extract the port at the
   composition root later under follow-up **`F-U-PROMOTE-FS-PROTOCOL-01`**.
9. **Force-stop endpoint (O-1 option c) and retry/timeout expansion.** Not added. O-1 is
   resolved by D-O1 (option b, in-band `STOPPING` re-probe) and its residual risk is
   recorded in **Open Questions**. F1-2c fixes reconciliation's fail-open but adds no
   automatic retry or periodic trigger.
10. **Persisted activity feed beyond the unknown-outcome entry.** D-O1 requires one
    `server.stop_unknown` activity row for visibility. Broader activity-log redesign,
    reordering, or a generic stop-outcome field is not part of this batch.

---

## Assumptions/Unknowns

| # | Item | Evidence / status |
|---|---|---|
| 1 | There is no `promote.py`; the recon's `promote.py:196-202` and `:217-219` are `promote_commit.py:196-202` and `:217-219`. | Verified by `find backend -name 'promote*.py'` and `rg`. **CONFLICT** with recon label, resolved in this spec. |
| 2 | `CommandBus.send` never raises for handler failures; it converts `MCSError` and generic exceptions into `success=False`. | `command_bus.py:105-121`. |
| 3 | At HEAD, `mark_stopped()` is unconditional, so DB `STOPPED` is not proof of process exit. v3/v4 gate it on the three-outcome branch (CV3-2). | `stop_server.py:165-173`, `aggregate.py:384-393`; changed by item 12. |
| 4 | A re-read of server status in the promote session may be stale because of the identity map and `expire_on_commit=False`. | `db.py:100`, `repository.py:35-41`; **UNVERIFIED** by a runtime probe in this design session. |
| 5 | Provider status-probe failures are currently invisible. | `stop_server.py:134-135`. |
| 6 | The provider/port verification block is skipped entirely when `runtime.external_id` is empty. | `stop_server.py:74`. |
| 7 | `mkstemp` creates the temp file with mode `0600`; the existing helper already replaces the destination with that mode. Permission preservation for configs is not addressed in this batch. | `fs.py:169`; **UNVERIFIED** operational impact. |
| 8 | Windows parent-directory `fsync` is unsupported and is skipped. Windows behavior of the new helper is not tested here. | `os.name` branch; **UNVERIFIED**. |
| 9 | Parent-dir `fsync` failure occurs after `os.replace`, so the file is already changed; this is reported, not rolled back. | Design consequence; all-or-nothing deferred. |
| 10 | The force-bypass audit row can be durable before a stop abort because `SQLActivityRepository.save` commits. | `promote_commit.py:147-171`, `activity/infrastructure/repository.py:44-60`; D-E follow-up. |
| 11 | `server.runtime` is available on the pre-stop aggregate and carries `external_id` for real local/Docker runs. | `start_server.py:347,369`, `local.py:364`; mocked tests may set it to `None`. |
| 12 | Manifest `rel_path` values are trusted; promotion does not validate traversal. | `promote_commit.py:185-188`; out of scope. |
| 13 | No migration, new dependency, new exception type, or permission/route change is required. The new `PROMOTE_STOP_NOT_CONFIRMED` is a `CommandResult.error_code`, not a new exception class. | Verified against `exceptions.py` and `api/errors.py`. |
| 14 | Test counts and gate results in `.ai/STATE.json` are from 2026-10-04 and were not re-run in this design session. | `.ai/STATE.json` `verified_metrics`; **UNVERIFIED** for HEAD `0a62d45`. |
| 15 | `runtime_verified` must come from the pre-stop capture at `stop_server.py:67` (consumed at `:74`), not from the `server` rebound at `:167`; `mark_stopped()` clears `external_id` (`:391`). Neither `runtime_verified` nor `stop_confirmed` exists at HEAD; both are introduced by this spec. | Verified: `stop_server.py:49,67,74,167,168`, `aggregate.py:384-393` (R1); `rg` finds no `runtime_verified`/`stop_confirmed` in `backend/app` or `backend/tests`. |
| 16 | The test fixture `_create_test_server(make_running=True)` (`test_server_commands.py:70-102`) sets no `external_id`; `mark_running(pid=100, port=25565)` at `:98` leaves it empty and `test_stop_running_server` asserts `external_id == ""` at `:396`. A confirmed-stop test must set a non-empty `external_id` explicitly; the existing `test_stop_running_server` must be updated accordingly (see Tests). | Verified at HEAD (R1). |
| 17 | The first UnitOfWork commits `STOPPING` at `stop_server.py:58` (`await uow.commit()`) on the `RUNNING`/`STARTING` path, so "DB status unchanged" means not advanced to `STOPPED`; it cannot mean the pre-request `RUNNING` value. `server.stop()` at `:53` only sets the in-memory status before that commit. D-O1 skips both for a `STOPPING` input (item 12a). | Verified: `stop_server.py:51-58`; resolved in item 12 (R2/CV3-2), extended by D-O1. |
| 18 | `STOPPING` is a valid persisted status (`ServerStatus.STOPPING`, `aggregate.py:41`) and is currently excluded from the promote "was running" set at `promote_commit.py:179`. The `stop()` method itself is at `aggregate.py:380-382`. | Verified (R3, C2). |
| 19 | The three-outcome partition is exhaustive: (ii) requires positive still-running evidence; (i) requires all clean checks; everything else is (iii). A probe failure plus a listening port is (ii) by precedence. | Design rule in item 12; provider status enum has `RUNNING`/`STOPPED`/`ERROR`/`UNKNOWN` (`providers/base.py:16-20`). |
| 20 | At HEAD, reconciliation marks `STOPPING -> STOPPED` without checking the provider status it computed. F1-2c (D-F1-2c) fixes this: only provider `STOPPED` may mark `STOPPED`. | Verified: `reconciliation.py:136-141` computes `status`; `:274-289` calls `mark_stopped()` unconditionally at `:279`. |
| 21 | `mark_running()` is currently called only from `STARTING`/`CRASHED` paths, so rejecting a `STOPPING` source does not break existing callers. | Verified: `reconciliation.py:182,258`, `runtime_reconciliation.py:392`, `supervisor.py:260,343`. |
| 22 | **D-O1:** `STOPPING -> STOPPING` is not an allowed transition at HEAD, so the handler must skip `server.stop()`/the first write for a `STOPPING` input. The widened gate accepts `RUNNING`, `STARTING`, `STOPPING`; `STOPPED`, `CRASHED`, `CREATED` (and the other statuses) still raise `ServerNotRunningError`. | Verified: `_SERVER_TRANSITIONS[STOPPING] == {STOPPED, CRASHED}` at `aggregate.py:77`; `_transition_to` rejects absent targets at `aggregate.py:297-304`; gate at `stop_server.py:51-52`. |
| 23 | The reconciliation trigger is **startup only**: the sole production caller is `backend/app/main.py:126` inside the `lifespan` context manager (`main.py:75`). There is no periodic/scheduled caller at HEAD; tests call `reconcile_servers` directly. | Verified by `rg "reconcile_servers" backend/` at `0a62d45` (only `main.py:126` and tests). |
| 24 | The persisted activity feed is written by `ActivityEventSubscriber`; D-O1 visibility therefore requires a new `ServerStopUnknownEvent` registered in `registration.py` and mapped in `subscriber.py`. The handler has no `ActivityRepository` dependency at HEAD. | Verified: `activity/application/subscriber.py:20-55`; `registration.py:300-327`; `stop_server.py:40-41` (event bus only). |
| 25 | Whether the owner intends the persisted `ServerActivityLog` feed (versus the lifecycle warning log) by "activity log" is **UNVERIFIED**. This spec implements the stronger reading (persisted `server.stop_unknown` row plus a warning); if only logs are intended, the event class/registration is unnecessary. | Design interpretation; flagged for owner/builder confirmation. |

## Binding review deltas (independent review of v4, verdict: READY WITH DELTAS, no blocker)

These deltas override the body of this spec wherever they conflict. The builder must apply all of them. The owner decision that ServerStopUnknownEvent, the activity subscriber mapping and the registration.py edit are OUT of build still stands; body rows for them are ignored.

1. **Concurrency.** Serialize gate -> verify -> commit per `server_id` (class-level `asyncio.Lock` keyed by server id, or a CAS update guarded by `status IN (running, starting, stopping)`). An already-`STOPPED` row is a successful no-op. Add a two-concurrent-stops test. Evidence: `stop_server.py:47-58, :165-173`; `aggregate.py:77, :297-304`.
2. **Promote skip hole.** In `promote_commit.py`, if `server.status` is outside `was_running` but `server.runtime.external_id` is non-empty, fail closed with `PROMOTE_STOP_NOT_CONFIRMED` before any write. Alternatively probe the provider and proceed only on a positive `STOPPED`. Update stopped-server test mocks to `runtime=None` where appropriate. Evidence: `promote_commit.py:179, :183-202`; `restart_server.py:92-93, :313`; `supervisor.py:430`.
3. **Docker false STOPPED.** In `docker.py`, map inspect failure (`returncode != 0` or empty stdout) to `ERROR` or `UNKNOWN`, never `STOPPED`. Make `_wait_for_container_exit` (`docker.py:609-617`) count only `STOPPED` as exited. Add a Docker inspect-failure test. Evidence: `docker.py:643-652`.
4. **Port-only evidence.** `still_running` is set only when the provider status is `RUNNING`. Port-only evidence maps to outcome (iii) unknown, or to outcome (ii) only if the listening PID equals `runtime.pid`. Update the outcome table and tests. Evidence: `stop_server.py:137-156`; spec outcome table (`spec:295-312`).
5. **Force audit row.** Move the force-promote activity save (`promote_commit.py:147-171`) to after the stop gate and successful writes. For an aborted attempt, record a distinct `versioning.force_promote_attempted` row with the abort reason. Correct the spec sentence that says no activity is emitted for an aborted promotion (`spec:480-482`). Evidence: `activity/infrastructure/repository.py:44-60`.
6. **Reconciliation probe timeout.** (Overrides the body's "no new timeout" decision at `spec:510-512`.) Wrap `provider.status` in `asyncio.wait_for(..., timeout=5)` inside `reconciliation.py` at `:136-141`. Map `TimeoutError` to `ERROR`/unknown. Add a slow-probe test. Evidence: `reconciliation.py:136-141`; `main.py:119-126`; `stop_server.py:113`.
7. **Provider-stage failure test.** Model: graceful stop raised or timed out, force stop succeeded, final `provider.status=STOPPED`, port free. Assert `stop_confirmed` is `False` because a warning was recorded. Evidence: `spec:817`.
8. **Probe-exception test.** Assert that data `provider_errors` or `warnings` contains the status-check failure message. Do not assert only that the key is absent. Evidence: `spec:818`.
9. **Port parametrization.** Parametrize (provider `RUNNING`, port free) and (provider `STOPPED`, port listening) so each signal is isolated. Evidence: `spec:821`.
10. **Unlink-before-close mutation.** Monkeypatch `os.close` and `os.unlink` to record call order, and assert close happens before unlink. The current test cannot detect this on POSIX. Evidence: `spec:898`; `fs.py:134`.
11. **`revert_to_running()` runtime status and feed gap.** Inside `revert_to_running()`, set `self._runtime.status = "running"` and keep pid, port, external_id and restart_count unchanged. Do NOT add a new event type without owner approval. Document the activity-feed gap explicitly in the spec. Evidence: `aggregate.py:380-382`; `subscriber.py:75-77`; `stop_server.py:53-58`.
12. **Outcome-gated logs.** Guard the "Server marked stopped" timeline milestone (`stop_server.py:175`) and the info log (`:177-181`) so they fire only for outcome (i). For (ii) and (iii), log the actual `stop_outcome` and warnings. Evidence: `stop_server.py:175-181`.
13. **API semantic change (doc only).** Record in the spec that `POST /servers/{id}/stop` now accepts a `STOPPING` row, and that a still-running outcome returns HTTP 200 with `stop_outcome` set and the row reverted to `RUNNING`. Evidence: `servers.py:337-345`.
