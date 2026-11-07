# SPEC-2026-10-02-DOCKER-STATUS-AND-DELETE-HONESTY-01 — Docker Status Crash Visibility & Delete Honesty (Revision 1)

**Document Status:** Proposed (design revision — awaiting owner approval before implementation)  
**Spec Identifier:** `SPEC-2026-10-02-DOCKER-STATUS-AND-DELETE-HONESTY-01`  
**Date:** 2026-10-02 (Revised)  
**Classification:** Release Improvement track (Release Improvement), Decision level D1 (Standard), Roadmap drift: None  
**Parent Decision Record:** `docs/decisions/DECISION-2026-10-02-001-docker-status-137-handling.md`  
**Governing Authority:** project governance standards## 1. Goal

1. **Restore crash visibility** in `DockerProvider.status()` while keeping stop-flow warnings honest (Revision 2: Option Z — OOM-bounded status, no interface change):
   - Guarantee that a daemon-confirmed OOM kill (`OOMKilled=true`) is **never** reported as `STOPPED` to any consumer.
   - Accept explicitly (residual risk R1, §5): an *unconfirmed* kill (exit 137, `OOMKilled=false`, e.g. external `kill -9`) still reads `STOPPED` from `status()` itself; it is caught by `RuntimeSupervisor` via `collect_diagnostics` while the container exists (§4.3), but reads `"stopped"` in the diagnostics endpoint and is missed if the container was removed.
   - Ensure that after an intentional stop request, normal container stop signals (0, 137, 143 with `OOMKilled=false`) do not produce misleading `"still running after stop"` warnings or false-alarm errors.
2. **Improve delete honesty** on filesystem failure without breaking contracts or security hygiene:
   - Retain HTTP 500 (`FILESYSTEM_CLEANUP_FAILED`) when directory removal fails.
   - Provide `leftover_path` in error details justified by the route's permission check (`server:delete`).
   - Remove ready-made shell commands (`sudo rm -rf ...`); do not synthesize shell commands from data.
   - Word the cleanup hint accurately as "may be caused by file permissions or active file locks" rather than asserting the cause.
3. **Record (without designing)** future architectural items:
   - Automatic root-owned cleanup container (DooD socket).
   - `DELETING` / retryable server lifecycle state.
4. **Separate and capture the `itzg` UID/GID permission finding**:
   - Disentangle the test-runner orphan from the itzg permission model.
   - Record the `itzg` UID/GID finding, its migration risks, and promotion gates as its own draft STATE item without designing the fix.

---

## 2. Current Behavior & The Problem

### 2.1 Commit 4893f80 Changes (FACT)
In commit `4893f80`, two changes were introduced to address dev-server triage findings:
1. `backend/app/modules/server/infrastructure/providers/docker.py:666`:
   In `status()`, exited containers with `exit_code in (0, 137, 143)` were mapped to `ServerRuntimeStatus.STOPPED`.
2. `backend/app/modules/server/application/commands/stop_server.py:114`:
   Differentiated `status == ServerRuntimeStatus.RUNNING` (`"still running after stop"`) from other non-stopped statuses (`"stopped with unexpected status"`).

### 2.2 The Conflict: Lost Crash Visibility (FACT / CONFLICT)
- **Exit 137** corresponds to `SIGKILL` (128 + 9). It is produced by:
  - The Linux kernel OOM killer terminating a runaway process.
  - An external operator or host agent executing `kill -9` or `docker kill`.
  - Docker daemon timing out a graceful stop after 30 seconds (`docker stop -t 30`).
- **Existing crash infrastructure:**
  - `backend/app/modules/health/infrastructure/crash_analyzer.py:18-26` maps exit code 137 directly to `FailureCode.MEMORY_EXHAUSTED`.
  - `backend/app/modules/versioning/infrastructure/test_runner.py:1062-1066` treats exit code 137 and `OOMKilled` as memory-exhausted failure evidence.
  - `backend/app/modules/server/infrastructure/providers/docker.py:865-889` (`collect_diagnostics`) inspects `{{.State.OOMKilled}}` and flags exit codes 137 and 143 as `FailureCode.MEMORY_EXHAUSTED`.
- **The Breakdown:**
  - `DockerProvider.status(handle)` only inspects `{{.State.Status}} {{.State.ExitCode}}`.
  - Because `status()` mapped `137` to `ServerRuntimeStatus.STOPPED`, an OOM-killed container or externally killed container running in production currently reports `STOPPED`.
  - In `get_runtime_diagnostics.py:68`: `provider_status` returns `"stopped"`, masking the crash in API diagnostic polling.
  - In `RuntimeSupervisor._health_check` (`supervisor.py:375-397`): if `collect_diagnostics` fails or is skipped, `status == STOPPED` causes the supervisor to log a normal phase transition to `stopped` rather than invoking `_handle_crash`.

### 2.3 Delete Server Flow & Orphan Risk (FACT)
- In `backend/app/modules/server/application/commands/delete_server.py:153-171`:
  The server database record is deleted and committed in UnitOfWork **before** filesystem directory removal (`local_fs.delete_dir(server_dir)`) is attempted.
- If filesystem removal fails (e.g. `PermissionError` due to root-owned container files):
  1. The API returns HTTP 500 (`FILESYSTEM_CLEANUP_FAILED`).
  2. If the user retries `DELETE /api/v1/servers/{server_id}`, the server DB record no longer exists, returning HTTP 404 (`NOT_FOUND`).
  3. The directory on disk (`data/servers/<server-name>`) remains orphaned permanently because no production code cleans orphan directories (`cleanup_orphan_directory` in `reconciliation.py:77` is only invoked in unit tests).

---

## 3. Comparison of Options for (A) Crash Visibility vs Stop Honesty

### 3.1 Option 1 (WITHDRAWN — kept as record, do not implement)

**Withdrawn per Build pre-checks (Revision 2):** (P1) `RuntimeDiagnostics` has no `oom_killed` field
(`domain/diagnostics.py:36-53` — fields are `exit_code`, `signal`, `failure_code`, …), so the
proposed `getattr(diag, "oom_killed", False)` gate is dead code and Path 1A cannot distinguish
OOM kills in the stop flow without an interface change after all; (P2) after `docker stop` the
container *stays* exited with code 143/137, so a reverted `status()` makes every cleanly stopped
server report provider `ERROR` permanently (verified consequence: `get_runtime_diagnostics`
`provider_status` reads `"error"` indefinitely and stop/restart post-checks warn on clean stops).
The stop-flow `collect_diagnostics` coupling is therefore withdrawn: it needs an interface
change, is heavy, and mislabels clean stops. Original text preserved below.

#### Mechanism: How the Stop Flow Obtains Exit Code without Reaching into Docker
`ServerProvider.status()` returns only the `ServerRuntimeStatus` enum. To avoid reaching into Docker from the application layer (`stop_server.py` and `restart_server.py`), there are two concrete interface design paths:

- **Path 1A (Recommended — Uses Existing Polymorphic Provider Method):**
  - `ServerProvider` already defines `async def collect_diagnostics(self, handle: ServerHandle) -> RuntimeDiagnostics` in `base.py:150`.
  - This method is implemented polymorphically across all concrete providers:
    - `DockerProvider.collect_diagnostics` (`docker.py:856`)
    - `LocalHostProvider.collect_diagnostics` (`local.py:721`)
    - `LocalWindowsProvider.collect_diagnostics` (`local_windows.py:556`)
  - `RuntimeDiagnostics` (`domain/diagnostics.py:41`) already contains `exit_code: int | None`.
  - When `status = await provider.status(handle)` returns `ServerRuntimeStatus.ERROR`, `stop_server.py` calls the existing provider abstraction:
    ```python
    status = await asyncio.wait_for(provider.status(handle), timeout=5)
    if status != ServerRuntimeStatus.STOPPED:
        if status == ServerRuntimeStatus.RUNNING:
            logger.warning('Server "%s" still running after stop...', server_name)
            provider_errors.append(f"Runtime still {status.value} after stop")
        else:
            # Query the provider abstraction (no Docker imports or inspect calls)
            diag = await provider.collect_diagnostics(handle)
            if diag and diag.exit_code in (137, 143) and not getattr(diag, "oom_killed", False):
                logger.info('Server "%s" stopped via signal %s (normal stop termination)', server_name, diag.exit_code)
                add_timeline_milestone(None, f"Provider stopped (exit {diag.exit_code})", server_name, sid)
            else:
                logger.warning('Server "%s" stopped with unexpected status...', server_name)
                provider_errors.append(f"Runtime status is {status.value} after stop")
    ```
  - **Interface change across providers:** **None.** Path 1A uses existing methods and domain objects already implemented on all providers.

- **Path 1B (Alternative — Signature Change on `ServerProvider.stop()`):**
  - Change `ServerProvider.stop()` return type from `None` to a `StopResult` dataclass:
    ```python
    @dataclass(frozen=True)
    class StopResult:
        stopped: bool
        exit_code: int | None = None
        signal: int | None = None
    ```
  - **Interface change across providers:** Modifies `base.py:84`, `docker.py:622`, `local.py:504`, `local_windows.py:421`, and all provider test mocks.
  - **Decision level:** D1 (bordering D2 due to cross-provider contract signature change).

#### Honest Re-Grading of Option 1
- **Path 1A Decision Level:** **D1 (Standard)**. It changes behavioral contracts between the provider and application layer across ~8 consumers, but requires **zero signature changes** to `base.py`.
- **Path 1B Decision Level:** **D1 (Standard)**. Higher blast radius due to signature updates across all 3 providers and unit test mocks.
- **Why Path 1A Wins:** Re-uses established hexagonal domain abstraction (`RuntimeDiagnostics`) without interface churn.

---

### 3.2 Option Z (Adopted — Revision 2): OOM Awareness Inside `DockerProvider.status()` Only

- **Concept:** Extend the existing inspect format in `status()` (`docker.py:645-650`) to
  `"{{.State.Status}} {{.State.ExitCode}} {{.State.OOMKilled}}"`. In the `exited` branch only:
  `OOMKilled=true` → `ERROR`; otherwise keep commit `4893f80` mapping (0/137/143 → `STOPPED`,
  other non-zero → `ERROR`). No interface, enum, or `RuntimeDiagnostics` change; `status()`
  stays a single `docker inspect` call (same one `_docker_command`, `docker.py:995-997`).
  Parsing stays backward-compatible: `parts[0]` status, `parts[1]` exit code (existing
  `try/except ValueError` → 0 preserved); new `oom = len(parts) > 2 and
  parts[2].strip().lower() in ("true", "1")` mirrors the identical parse already used for the
  same daemon field in `collect_diagnostics` (`docker.py:876`). All other statuses
  (`running`/`dead`/`error`/`created`/`paused`/unknown) ignore the extra token.
- **Known residual (accepted, was the old rejection reason):** `(exit 137, OOMKilled == false)`
  still reads `STOPPED` from `status()` — external `kill -9` / `docker kill`, or a child
  OOM the daemon did not flag. The Revision 1 rejection is downgraded (not eliminated)
  because the behavior matrix (§5) shows: (a) `RuntimeSupervisor` still catches the
  container-present case via the `collect_diagnostics` OR-clauses in `is_crash`
  (`supervisor.py:378-382`), independent of `== ERROR` (§4.3); (b) reverting instead (Y)
  inflicts permanent `"error"` on every cleanly stopped server (P2), the worse trade.
  Remaining blind spots: the diagnostics endpoint string (§5, S4/S5 under X/Z) and the
  container-removed case — both stated as residual risks R1 with the recommendation.

---

### 3.3 Option 3: Return a Richer Status Object from `status()`

- **Concept:** Change `ServerProvider.status(handle)` to return a structured dataclass `RuntimeStatusDetail` or expand `ServerRuntimeStatus` enum with `OOM_KILLED` and `SIGKILLED`.
- **Impact:** Breaks `ServerProvider.status()` across `base.py`, all 3 concrete providers, domain entities (`RuntimeInfo`), API schemas, and ~8 consumers.
- **Rejection Reason:** High scope drift and unnecessary abstraction when Path 1A resolves the issue with zero signature changes.

---

## 4. Supervisor Behavior & Requested Stops vs Crashes (FACT)

### 4.1 How `RuntimeSupervisor` Distinguishes Requested Stops from Crashes Today
Reading `backend/app/modules/server/application/supervisor.py` reveals the exact lifecycle:

1. **Stop Flow Sequencing (`stop_server.py:70-87`):**
   ```python
   add_timeline_milestone(None, "Stopping supervisor", server_name, sid)
   await RuntimeSupervisor.stop_for(sid)
   add_timeline_milestone(None, "Supervisor stopped", server_name, sid)
   ...
   await asyncio.wait_for(provider.stop(handle), timeout=15)
   ```
   The application layer explicitly calls `RuntimeSupervisor.stop_for(sid)` **before** invoking `provider.stop(handle)`.

2. **Supervisor Stop Handling (`supervisor.py:98-105`):**
   ```python
   async def stop(self, timeout: float = 10.0) -> None:
       self._stop_event.set()
       self._active = False
       ...
       task.cancel()
   ```
   `stop_for()` immediately sets `self._stop_event` and cancels the background monitoring task.

3. **Liveness Check Suppression (`supervisor.py:368-374`):**
   ```python
   async def _health_check(self) -> None:
       alive = await self._provider.verify_process(self._handle)
       if not alive:
           if self._stop_event.is_set():
               return
   ```
   If the container process exits while `_health_check` is running, `self._stop_event.is_set()` **immediately returns**, bypassing crash analysis entirely.

4. **Crash Handler Guard (`supervisor.py:525-533`):**
   ```python
   async def _handle_crash(self, diag: RuntimeDiagnostics) -> None:
       if self._stop_event.is_set():
           logger.info('Server "%s" stop already requested — crash suppressed (%s)', ...)
           return
   ```
   Even if crash processing were somehow entered, `self._stop_event.is_set()` aborts and logs `"stop already requested — crash suppressed"`.

### 4.2 What Happened Before Commit 4893f80?
Before commit `4893f80`, `docker stop` produced exit 143 or 137.
- In `RuntimeSupervisor`: The supervisor was already stopped via `stop_for(sid)` with `_stop_event` set. The supervisor **never** treated `docker stop` as a crash.
- In `stop_server.py:113-121`:
  ```python
  status = await asyncio.wait_for(provider.status(handle), timeout=5)
  if status != ServerRuntimeStatus.STOPPED:
      logger.warning('Server "%s" still running after stop (status=%s server_id=%s)', ...)
      provider_errors.append(f"Runtime still {status.value} after stop")
  ```
  Because `status()` returned `ERROR` on exit 143/137, `stop_server.py` saw `status != STOPPED`. With no check for `RUNNING`, it falsely logged `"still running after stop (status=error)"` and returned a warning in `provider_errors`.

**Conclusion (FACT):** Reverting `status()` to return `ERROR` on exit 143/137 **cannot** make operator-requested stops look like crashes in `RuntimeSupervisor`. The supervisor is shielded by `_stop_event`. The only component that saw the anomaly was `stop_server.py`, which is fixed by Path 1A.

### 4.3 S5 Detection Does Not Depend on `== ERROR` (Revision 2, FACT)

For an external kill while running (exit 137, `OOMKilled=false`, no stop requested), the
container-present path is: `verify_process` False (`base.py:160-161`, `== RUNNING` fails) →
`_stop_event` unset → `status = STOPPED` (X/Z) **plus** `diag = collect_diagnostics` →
`is_crash = status != STOPPED or diag.failure_code is not None or (diag.exit_code not None
and != 0)` (`supervisor.py:378-382`) evaluates TRUE via the second/third clauses, because
`collect_diagnostics` maps exit 137 → `MEMORY_EXHAUSTED` (`docker.py:890-895`). Plainly: S5
detection depends on `== ERROR` **only when diagnostics are unavailable** (container removed,
inspect fails → `STOPPED` + inconclusive diag → `mark_stopped`, `supervisor.py:398-419`).
Likewise the reconciler needs no `== ERROR`: DB-`RUNNING` rows crash on *any* non-`RUNNING`
status (`reconciliation.py:219-250`). The consumers that genuinely need the enum distinction
are the stop/restart post-checks (`!= STOPPED`) and the `provider_status` string
(`get_runtime_diagnostics.py:68`).

---

## 5. Consumer Conditions & Behavior Matrix (X / Y / Z) — Revision 2 (FACT: all conditions quoted from code read this session)

Designs: **X** = current `4893f80` (exited 0/137/143 → `STOPPED`, other non-zero → `ERROR`);
**Y** = revert (exited 0 → `STOPPED`, any non-zero → `ERROR`); **Z** = X plus `OOMKilled=true` →
`ERROR` in the `exited` branch only. Cell flags: ⚠️ = clean stop shows as error; 🔇 = crash
silently missed. Supervisor rows assume `_stop_event` NOT set (requested stops are suppressed
via `_stop_event` in `_health_check`, `supervisor.py:371-373`, and `_handle_crash`,
`supervisor.py:526-532`).

Exact consumer conditions:
- `stop_server.py:114`: `if status != STOPPED:` → `RUNNING`: warn `"still running after stop"` +
  append; else (`ERROR`/`UNKNOWN`): warn `"stopped with unexpected status"` + append (`:114-131`).
- `restart_server.py:125`: `if status != STOPPED:` → append `f"Runtime still {status.value} after stop"` (`:124-126`, no RUNNING distinction).
- `supervisor.py:378-382`: `is_crash = status != STOPPED or diag.failure_code is not None or
  (diag.exit_code not None and != 0)` — detection does NOT depend on `== ERROR` alone (§4.3).
- `reconciliation.py:219-250`: DB `RUNNING` + `status == RUNNING` → confirmed, **else** → `crash()`
  (STOPPED vs ERROR indistinguishable); `STOPPED` DB rows are not stale (`:87-104`) and are skipped.
- `get_runtime_diagnostics.py:68`: `provider_status = status.value` verbatim (`failure_code` output hardcoded `None`, `:146` — `collect_diagnostics` is never consulted here).
- `deployment_orchestrator.py:78`: returns `status` verbatim. `server_orchestrator.py:167`: polls
  `status.value == "running"`. `docker.py:617`: `in (STOPPED, ERROR)`. `docker.py:718` /
  `base.py:161`: `== RUNNING`. These five are identical under X/Y/Z for every scenario below.

| Scenario | X (current) | Y (revert) | Z (adopted) |
|---|---|---|---|
| S1 requested stop, exit 0 | `STOPPED`, milestone "confirmed stopped". Clean | Same as X. Clean | Same as X. Clean |
| S2 requested stop, `docker stop` fallback, exit 143 | `STOPPED`. Clean | `ERROR` → stop/restart warn + `provider_errors`/`stop_errors` entry. ⚠️ | `STOPPED` (OOMKilled=false). Clean |
| S3 stop, 30 s timeout → SIGKILL, exit 137 | `STOPPED`. Clean (the separate "Stop timed out" warning is pre-existing honest behavior, same all designs) | `ERROR` → same false warnings as S2. ⚠️ | `STOPPED`. Clean |
| S4 OOM kill while running (137, OOMKilled=true) | Supervisor: `STOPPED` + diag `MEMORY_EXHAUSTED` (`docker.py:887-889`) → `is_crash` TRUE (detected, correctly attributed). Diagnostics endpoint: `"stopped"`. 🔇 (status string masked) | `ERROR` → detected everywhere | `ERROR` → detected everywhere (incl. endpoint) |
| S5 external kill, 137, OOMKilled=false | Supervisor (container present): `STOPPED` + diag 137 → `MEMORY_EXHAUSTED` (`docker.py:890-895`) → `is_crash` TRUE — detected, misattributed (see task-5 finding, §7.3). Endpoint: `"stopped"`. 🔇 (string only) | `ERROR` → detected, correctly unlabeled | Same as X (accepted residual R1) |
| S5 container already removed (inspect fails) | `STOPPED` (`docker.py:651-652`) + diag inconclusive → `mark_stopped`. 🔇 | `ERROR`… **except** removed container also hits `:651-652` → `STOPPED`. Same miss (FACT: inspect-failure path is design-independent) | Same as X |
| S6 crash, exit 1 | `ERROR` everywhere. Clean | Same. Clean | Same. Clean |
| S7 restart, DB RUNNING, exited 143/137 | Reconciler else-branch → `CRASHED` (exit recorded `-1`, pre-existing coarseness). Same Y/Z | Same | Same |
| S8 restart, DB STOPPED, exited 143 | Row not stale → skipped. Same Y/Z | Same | Same |

Notes: (1) S5-removed row corrects a Revision 1 oversight — no design distinguishes a removed
container, since `:651-652` short-circuits before exit-code mapping. (2) Under X/Z, S4/S5
supervisor detection rides entirely on `collect_diagnostics` succeeding; the endpoint string
and the removed-container case are the accepted R1 residuals. (3) Y's cost (P2) is permanent:
exited 143/137 persists, so every normally stopped server reads `"error"` in
`provider_status` and earns stop/restart warnings indefinitely.

---

## 6. Delete Honesty (Part B — Revised)

### 6.1 Permission Model Analysis (FACT)
- `DELETE /api/v1/servers/{server_id}` is declared in `backend/app/api/v1/routers/servers.py:317-322`:
  ```python
  @router.delete("/{server_id}", status_code=204)
  async def delete_server(
      server_id: str,
      command_bus: CommandBus = Depends(get_command_bus),
      _current_user: dict = Depends(require_permission("server:delete")),
  ) -> None:
  ```
- **Permission Check:** Protected by `require_permission("server:delete")`.
- **Role Assignment:** Per `contracts/permissions.yaml:47` and `bootstrap_instance.py:60`, `server:delete` is an administrative privilege granted only to the `owner` role or instance administrators with wildcard/admin permissions. Viewers and unprivileged users cannot execute this route.
- **Path Disclosure Justification:** Because the caller is an authenticated administrator authorized to delete the server, returning `leftover_path` (e.g. `data/servers/test-1`) does not violate least-privilege or leak information to unauthorized users. It informs the administrator which directory failed removal so they can inspect it on the host.

### 6.2 Shell Command Hygiene & Accurate Wording
- **Command Removal:** The ready-made `manual_command` (`"sudo rm -rf ..."`) is **removed**. API error payloads must not synthesize raw shell commands from server data, avoiding risks of accidental execution or copy-paste accidents.
- **Accurate Wording:** The hint does not assert file permissions as the sole cause. It states the failure "may be caused by file permissions or active file locks".

### 6.3 Exact Error Payload
In `backend/app/modules/server/application/commands/delete_server.py:184-193`:
```python
return CommandResult(
    success=False,
    error=(
        "Server record deleted, but filesystem directory could not be removed: "
        f"{exc}. Manual cleanup required."
    ),
    error_code="FILESYSTEM_CLEANUP_FAILED",
    details={
        "server_id": command.server_id,
        "leftover_path": server_dir,
        "cleanup_hint": (
            f"The server database record was deleted, but the directory '{server_dir}' "
            "could not be removed from disk. This may be caused by file permissions or active file locks. "
            "Inspect and remove the directory on the host to free disk space."
        ),
    },
)
```

### 6.4 Test Specification
In `backend/tests/application/test_server_commands.py` (`test_delete_filesystem_failure_returns_error_result`):
- Assert `result.success is False`.
- Assert `result.error_code == "FILESYSTEM_CLEANUP_FAILED"`.
- Assert `result.details["leftover_path"] == server_dir`.
- Assert `"may be caused by file permissions or active file locks"` in `result.details["cleanup_hint"]`.
- Assert `"manual_command"` is **NOT** present in `result.details`.

---

## 7. Recorded Future Architecture (Part C — Record Only, Do NOT Design)

### 7.1 Automatic Root-Owned Cleanup Container (DooD socket)
- **Concept:** Spawning a short-lived root container via Docker-out-of-Docker socket (`/var/run/docker.sock`) to execute `rm -rf` inside the volume mount upon host `PermissionError`.
- **Classification:** Release Improvement / Tech Debt track, Decision Level **D2 (Major)**.
- **Security Implications:** Mounting host paths into root containers dynamically creates path-traversal, symlink-following, and host filesystem deletion risks. Requires strict containment validation and security audits.
- **Corrected "Why Now?" Evaluation (§16):** **Fails.** The root-owned test orphan cited in triage (`.onx/tests/<uuid>/.paper`) was generated by `test_runner.py` before the `--user` flag was added to non-itzg containers (`docker.py:393`). Now that `--user {uid}:{gid}` is enforced, newly executed test containers run as the host user and do not create root-owned files.
- **Promotion Evidence:** Documented production recurrence of orphaned directories caused by container-created files despite proper UID mapping, or user environments where host sudo access is unavailable.

### 7.2 `DELETING` Lifecycle State Machine
- **Concept:** Introducing a `ServerStatus.DELETING` enum. The DB record remains present in `DELETING` state while filesystem cleanup is attempted; record is only dropped after filesystem removal succeeds. Retries re-attempt filesystem cleanup rather than 404ing.
- **Classification:** Release Improvement track, Decision Level **D1 (Standard)**.
- **"Why Now?" Evaluation (§16):** **Fails.** Requires schema migrations, API contract changes, frontend status badge updates, and lifecycle guards across multiple modules for an edge-case failure mode.
- **Promotion Evidence:** High deletion failure rates in distributed/NFS or Windows file-locking environments where transient locks resolve upon subsequent retries.

### 7.3 Captured Finding (no fix, no design): `collect_diagnostics` Labels Clean Stops MEMORY_EXHAUSTED

- **FACT** (`docker.py:887-895`): when `OOMKilled` is false and no log pattern matched, exit 137/143
  → `failure_code = MEMORY_EXHAUSTED` with reason `"Container terminated with exit code … (SIGKILL/SIGTERM)"`.
  A clean `docker stop` (exit 143, `OOMKilled=false`) therefore reads `MEMORY_EXHAUSTED` if
  diagnostics are ever collected on it.
- **FACT — consumers of `failure_code`:** supervisor `is_crash` clause 2 (`supervisor.py:380`),
  `_handle_crash` logging/persist (`:546`, `server.crash`, `:554-557`, `RUNTIME_PROCESS_LOST`
  fallback when unset at `:385-386`); `crash_analyzer` honors a passed `failure_code`
  (`crash_analyzer.py:192-194`); `server_crashed_handler` → `recovery_orchestrator`
  (auto-restart unless non-recoverable); test-runner failure attribution
  (`test_runner.py:1114-1135`); crash-report/classify APIs. `get_runtime_diagnostics` does
  NOT surface it (hardcoded `None`, `:146`).
- **Blast radius today (FACT):** limited — post-stop flows check `status()`, not diagnostics, and
  supervisor suppresses requested stops via `_stop_event`; the mislabel bites only when
  diagnostics are collected on a normally-stopped container (manual investigation, S5
  misattribution as memory-exhaustion). Proposed lane/level if promoted: **Release Improvement track, D0**
  (one-branch guard: only map 137/143 → `MEMORY_EXHAUSTED` when `OOMKilled` is true or log
  evidence agrees; owner decides).
- **Evidence needed to promote:** one observed case of a cleanly stopped server's persisted
  diagnostic/evidence bundle carrying `MEMORY_EXHAUSTED`, plus a consumer impact (wrong auto-restart
  decision, wrong crash-report classification, or user-visible misdiagnosis).

---

## 8. Itzg Image UID/GID Permission Finding (Part D — Captured Finding)

### 8.1 Empirical Evidence (FACT)
- Live testing of `itzg/minecraft-server:java21` on Linux (Docker 29.7.2) confirmed:
  1. Image scripts (`/image/scripts/start:7-15`) read `UID` and `GID` (`: "${UID:=1000}"`, `: "${GID:=1000}"`).
  2. The image **completely ignores** `PUID` and `PGID`.
  3. When `PUID=1001` was passed, the container ran as `uid=1000 gid=1000`.
  4. When `UID=1001` was passed, the container changed ownership and ran as `uid=1001 gid=1001`.

### 8.2 Migration Risk & Disentanglement from Test Orphans
- **Disentanglement:** The triage orphan was a test-runner artifact (`root:root`), NOT an `itzg` artifact.
- **Migration Risk:** If `docker.py` changes `-e PUID={uid}` to `-e UID={uid}`:
  - On hosts where the backend runs as `uid != 1000`, existing servers created under the old code already have files owned by `1000:1000`.
  - Switching the container to run as `uid != 1000` will cause the container process to fail with `PermissionError` when trying to access its own existing files owned by `1000:1000`.
  - Fixing this requires either an automatic `chown` migration or explicit migration documentation.

### 8.3 Draft STATE Item & Promotion Gates
- **Proposed Classification:** Release Improvement track (Release Improvement), Decision Level **D1 (Standard)** (or D2 if migration tooling is required).
- **Evidence Needed Before Promoting:**
  1. Reproduction on a host where `uid != 1000`.
  2. Audit of existing server directories to measure whether migration tooling (`chown`) is required for existing installations.
- **Draft project state tracking Item:**
  ```json
  {
    "id": "docker-itzg-uid-gid-mapping",
    "summary": "Capture itzg container user mapping finding: itzg/minecraft-server ignores PUID/PGID and only honors UID/GID (defaults to 1000:1000). On hosts where backend uid != 1000, container files are created as 1000:1000. Changing to UID/GID carries migration risk for existing data directories; requires reproduction on host with uid != 1000 and migration assessment before promotion.",
    "status": "OPEN",
    "lane": "Release Improvement",
    "resolved": null
  }
  ```

---

## 9. Tests & Verification Plan

1. **Status OOM-matrix tests (Revision 2 — replaces revert + stop-flow tolerance tests):**
   In `backend/tests/infrastructure/test_docker_provider.py` (mock `_docker_command` inspect
   output as `"exited <code> <oom>"`; `status()` stays one inspect call):
   - `test_docker_status_clean_exit_returns_stopped`: `exited 0 false` → `STOPPED` (existing, keep).
   - `test_docker_status_sigterm_sigkill_without_oom_returns_stopped`: `exited 137 false` and
     `exited 143 false` → `STOPPED` (pins X behavior for clean stops; S2/S3 honesty).
   - `test_docker_status_oomkilled_returns_error`: `exited 137 true` (and `exited 143 true`,
     `exited 0 true` — unreachable in practice, asserted ERROR by construction) → `ERROR`.
   - `test_docker_status_oomkilled_malformed_defaults_false`: `exited 137 bogus` / missing third
     token → falls back to X mapping (`STOPPED`).
   - `test_docker_status_error_exit_returns_error`: `exited 1 false` → `ERROR` (existing, keep).
   - No stop-flow `collect_diagnostics` tolerance tests (withdrawn with Option 1); no consumer-code
     changes, so `stop_server`/`restart_server`/`supervisor` suites run unchanged as regression cover.
2. **Supervisor Crash vs Stop Proof Tests (unchanged — behavior already correct):**
   In `backend/tests/application/test_supervisor.py`:
   - `test_supervisor_unexpected_exit_137_triggers_crash`: `_stop_event` NOT set, `status` `ERROR`
     with exit 137 → `_handle_crash` invoked.
   - `test_supervisor_requested_stop_suppresses_crash_on_exit_137`: after `stop_for()`
     (`_stop_event` set), exit 137 does NOT invoke `_handle_crash`.
   - Add only if missing: container-present S5 case (`status` `STOPPED` + diag exit 137) still
     triggers `_handle_crash` via the `is_crash` OR-diag clauses (pins §4.3).
3. **Delete Honesty Test (unchanged):**
   In `backend/tests/application/test_server_commands.py`:
   - `test_delete_filesystem_failure_returns_error_result`: assert `leftover_path` is present, `cleanup_hint` contains `"may be caused by file permissions or active file locks"`, and `manual_command` is absent.

---

## 10. Out of Scope

- Implementing automatic Docker DooD root cleanup containers.
- Adding a `DELETING` status enum to `ServerStatus` or database migrations.
- Designing the `itzg` UID/GID migration fix.
- Modifying non-Docker providers (`LocalWindowsProvider`, `LocalHostProvider`).
