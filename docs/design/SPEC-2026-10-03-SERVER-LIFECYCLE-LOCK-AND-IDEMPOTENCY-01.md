# SPEC-2026-10-03-SERVER-LIFECYCLE-LOCK-AND-IDEMPOTENCY-01 — Per-Server Lifecycle Lock & Idempotent Docker Container Lifecycle (Revision 2)

**Document Status:** Approved with Changes (Revision 2 updated per Design Review)  
**Spec Identifier:** `SPEC-2026-10-03-SERVER-LIFECYCLE-LOCK-AND-IDEMPOTENCY-01`  
**Date:** 2026-10-03 (Revision 2)  
**Classification:** Release Critical track (Release Critical), Decision level D1 (Standard Multi-Module)  
**Governing Authority:** project governance standards**Implementation Slices:** B1 (Lock Middleware, Idempotency, Async `start_for`), B2 (Docker Pre-Inspect, Adoption/Recreation Policy, Bounded Backoff, Restart Explicit Rm, Crash Stop)  
**Build Gate:** B1 is blocked until uncommitted `supervisor.py` changes (`stale-startup-deadline-supervisor-2026-10-02`) are reviewed and committed.

---

## 1. Goal

Eliminate container creation name conflicts (`Conflict. The container name "/onx-<id>" is already in use by container "..."`), destructive race conditions (where an overlapping request's blind `docker rm -f` deletes a concurrent winner's healthy running container), and duplicate runtime processes by:
1. Enforcing **per-server execution serialization** for all lifecycle operations (`start`, `stop`, `restart`, `delete`, and reconciliation repairs).
2. Ensuring **idempotent power commands** via pre-lock status checks (a `start` command on a server already `STARTING` or `RUNNING` succeeds as a no-op).
3. Implementing **inspect-before-create adoption and recreation** in `DockerProvider.start()`, adopting live containers only when the configuration fingerprint matches, and gracefully stopping before recreation otherwise.
4. Making `RuntimeSupervisor.start_for()` async, removing the `__await__` identity shim, and cleanly awaiting previous supervisor shutdown under the lifecycle lock.

### Non-Goals
- Multi-process / distributed cluster HA locking (backend is currently single-process; distributed DB locks are explicitly deferred).
- Changes to container naming scheme (`onx-<server_id>` is retained).
- Automatic boot-time orphan container deletion across all unindexed containers (deferred to avoid accidental reaping during network/daemon recovery).
- Modifying local or Windows provider semantics.

---

## 2. Current Behavior & The Problem

### 2.1 Start Lifecycle Concurrency & Blind `rm -f`
- When `StartServerHandler.handle()` runs:
  - It conditionally executes `await RuntimeSupervisor.stop_for(sid)` if an active supervisor is detected.
  - It runs `await asyncio.wait_for(provider.start(...), timeout=30)`.
  - It calls synchronous `RuntimeSupervisor.start_for(...)`, which launches `_run()` in the background via `asyncio.ensure_future()`.
- **The Defect:** No mutual exclusion exists across command bus requests. If two `start` requests arrive in close succession (e.g. rapid UI double-clicks, concurrent API callers, or background reconciliation alongside a user action):
  - Both requests pass initial checks.
  - Both invoke `DockerProvider.start()`, which builds args and directly runs `docker create --name onx-<id> ...` (line 472).
  - The second request receives `Conflict ... already in use`.
  - Under existing reactive logic (`docker.py:473-475`), the losing request blindly runs `docker rm -f onx-<id>` and retries `docker create`.
  - **Catastrophic Interleaving:** The loser's `docker rm -f` deletes the container that the first request just created and started! Both handlers return success, but Request 1's handle points to a destroyed container, and only Request 2's container remains.
  - If the removal is still in flight daemon-side ("removal in progress"), the second `docker create` also fails, raising `ProviderError("Container creation failed: Conflict...")`.

### 2.2 Stop and Restart Behavior
- `DockerProvider.stop()` executes RCON graceful stop or `docker stop -t 30` / `kill` (lines 622-641). It **never** removes the container, leaving it in `exited` state.
- `RestartServerHandler` performs stop followed by start. Because the container is left behind in `exited` state, **every single Docker restart deterministically triggers the Conflict -> rm -f -> retry path**.
- Post-crash starts also always trigger the Conflict path.

### 2.3 Uncommitted `supervisor.py` Interleaving
- Recent working-tree changes added a temporary `def __await__(self):` identity shim and non-awaited `loop.create_task(existing.stop())` when a supervisor instance is registered with a differing handle.
- Because `existing.stop()` is fire-and-forget, the old supervisor's background teardown runs concurrently with the new supervisor's startup, creating potential conflicts against the same container name.

---

## 3. Proposed Changes & Decisions

### Decision 1: Command-Bus Lifecycle Lock Middleware & Reconcile Acquisition
- **Location:** Command-bus middleware (`ServerLifecycleLockMiddleware`) registered in `backend/app/registration.py` and implemented in `backend/app/modules/server/application/lifecycle_lock.py`.
- **Target Commands:** `StartServerCommand`, `StopServerCommand`, `RestartServerCommand`, `DeleteServerCommand`.
- **Lock Semantics:**
  - Keyed by `str(command.server_id)`.
  - Process-local `asyncio.Lock` instances managed in an internal weakref or keyed dictionary.
  - Non-reentrant.
  - Acquisition timeout: Bounded to 60 seconds (accommodating the 30s start or 15s stop budgets).
  - If lock acquisition times out: returns `CommandResult(success=False, error="Server lifecycle operation in progress", error_code="OPERATION_CONCURRENCY_CONFLICT")` (which maps cleanly to HTTP 409).
- **Execution Under One Acquisition:**
  - `DeleteServerHandler` invokes `StopServerHandler.handle()` directly as an in-process method (not through `command_bus.send`), executing stop within the single outer lock acquisition without re-entrancy deadlock.
  - `RestartServerHandler` executes stop, status check, and start phases within its own `handle()` method (not through `command_bus.send`), executing under the single lock acquisition.
- **Out-of-Bus Acquisition:**
  - In `backend/app/modules/server/application/runtime_reconciliation.py:423`, where `RuntimeSupervisor.stop_for(state.server_id)` is called outside the command bus, wrap the call with explicit lock acquisition (`async with get_server_lifecycle_lock(state.server_id): ...`) to prevent racing with concurrent user actions.

### Decision 2: Status-Check Idempotency (Replacing Deterministic Keys / Headers)
- As approved in Design Review Change #2, Decision 4 (deterministic keys / client headers) is **removed completely**. Deterministic caching risks handing stale failures to subsequent retries within a time window.
- Idempotency is enforced strictly by **Lock + Status Check**:
  - In `StartServerHandler`:
    - After acquiring the lock and loading the server record from the repository:
    - If `server.status in (ServerStatus.RUNNING, ServerStatus.STARTING)` and an active supervisor is healthy, the command immediately returns success:
      `CommandResult(success=True, data={"status": server.status.value, "server_id": sid, "idempotent": True})`.
    - No duplicate container is created, no existing supervisor is reset, and no error is raised.
  - In `StopServerHandler`:
    - Existing contract is preserved: if the server is already `STOPPED`, it returns `ServerNotRunningError(sid)` (HTTP 400).
- **Zero Contract Impact:** No new HTTP headers (`Idempotency-Key`), no route changes, no schema modifications, no D2 governance escalation required.

### Decision 3: Docker Pre-Inspect, Configuration Fingerprint, and Adoption Policy
In `DockerProvider.start()`:
1. **Pre-Create Inspection:**
   - Query Docker daemon for existing containers by exact name (`onx-<server_id>` and legacy `mcs-<server_id>`) and by labels (`com.onx-manager.server_id` and legacy `com.mcs-manager.server_id`).
2. **Container Classification:**
   - **Foreign Container:** Container exists, has no matching ONX/MCS server ID label, and does not match the server ID.
     - *Action:* **Refuse with `ProviderError`**. Under no circumstances execute `docker rm -f` against a foreign container.
   - **Running + Ours (Matching Server ID):**
     - Compute the current **Config Fingerprint** (deterministic SHA256 of image tag, memory min/max, port mappings, command args).
     - Inspect the existing container's label `com.onx-manager.config-fingerprint`.
     - *If Fingerprint Matches:* **Adopt**. Skip `docker create` and `docker rm`. Proceed directly to inspect container PID/IP, verify process, and return `ServerHandle`.
     - *If Fingerprint Does Not Match (or Missing / Legacy Migration):* **Recreate Gracefully**. Await `docker stop -t 15 <name>`, then await `docker rm <name>` (no `-f`), then proceed to `docker create` with the updated spec and fingerprint label.
   - **Exited or Created + Ours:**
     - Container is stopped.
     - *Action:* Await clean `docker rm <name>` (no `-f`), then proceed to `docker create`.
   - **Dead or Removal-in-Progress:**
     - *Action:* Bounded retry with exponential backoff (up to 3 attempts: 0.5s, 1.0s, 2.0s) waiting for Docker daemon to complete teardown. If still unavailable, raise `ProviderError`.
   - **No Existing Container:**
     - Proceed directly to `docker create`.

### Decision 4: Legacy Compatibility
- Recognize both modern and legacy container names and labels:
  - Names: `onx-<server_id>` and `mcs-<server_id>`.
  - Labels: `com.onx-manager.server_id` and `com.mcs-manager.server_id`.
- Containers without the new `config-fingerprint` label are treated as legacy/non-matching: they are gracefully stopped (if running) and cleanly recreated with modern labels.

### Decision 5: Explicit Awaited Removal on Restart
- Plain `stop()` leaves the container in `exited` state so that crash logs, exit codes, and post-mortem diagnostics remain inspectable (`collect_diagnostics`, `FailureCode.MEMORY_EXHAUSTED` checks).
- In `RestartServerHandler`:
  - After the stop phase and status confirmation (`status == ServerRuntimeStatus.STOPPED`), explicitly execute and await `provider.destroy_container(handle)` (or clean `docker rm`) before entering the start phase.
  - This ensures the start phase begins from a clean slate and never exercises the Conflict fallback.

### Decision 6: Async `start_for`, Removal of `__await__`, Clean Teardown Under Lock
- In `backend/app/modules/server/application/supervisor.py`:
  - Remove `def __await__(self):` identity shim.
  - Make `start_for()` async:
    ```python
    @classmethod
    async def start_for(
        cls,
        server: Server,
        handle: ServerHandle,
        provider: ServerProvider,
    ) -> RuntimeSupervisor:
    ```
  - If a supervisor instance already exists:
    - Dead/dying (`not active`, `stop_event.is_set()`, or `task.done()`): pop from `_instances`.
    - Same handle & provider: return existing instance.
    - Differing handle/provider: `await existing.stop(timeout=10.0)` under the held lock, then pop from `_instances`.
  - Instantiate new supervisor, register in `_instances`, and `await supervisor.start()`.
- Update all callers:
  - `start_server.py:377`: `supervisor = await RuntimeSupervisor.start_for(...)`
  - `restart_server.py:392`: `supervisor = await RuntimeSupervisor.start_for(...)`
  - All test suites calling `start_for`.

### Decision 7: Crash Stop for Docker (Deferred Orphan Reaping)
- In `RuntimeSupervisor._handle_crash`:
  - Collect diagnostics first while container is intact.
  - If `provider` is Docker and container status is `RUNNING`:
    - Issue graceful stop: `await self._provider.stop(self._handle, force=False)` with bounded timeout.
    - Never execute `docker rm` here (preserves exited container for post-mortem diagnostics).
- Decision 5b (boot-time sweep of all unindexed Docker containers) is explicitly deferred to protect against deleting valid containers during startup anomalies.

---

## 4. Affected Components

| Component | File Path | Change Description |
|---|---|---|
| Lifecycle Lock | `backend/app/modules/server/application/lifecycle_lock.py` | New lock manager & middleware `ServerLifecycleLockMiddleware` |
| Registration | `backend/app/registration.py` | Register `ServerLifecycleLockMiddleware` on `command_bus` |
| Start Command | `backend/app/modules/server/application/commands/start_server.py` | Idempotent check for `STARTING`/`RUNNING`; `await RuntimeSupervisor.start_for` |
| Restart Command | `backend/app/modules/server/application/commands/restart_server.py` | Explicit clean `rm` after stop; `await RuntimeSupervisor.start_for` |
| Runtime Reconcile | `backend/app/modules/server/application/runtime_reconciliation.py` | Lock acquisition around out-of-bus `RuntimeSupervisor.stop_for` |
| Supervisor | `backend/app/modules/server/application/supervisor.py` | Async `start_for`, remove `__await__`, await `existing.stop(10s)`, crash stop |
| Docker Provider | `backend/app/modules/server/infrastructure/providers/docker.py` | Pre-inspect, config fingerprint, adopt vs stop-and-recreate, backoff, legacy labels |
| Tests | `backend/tests/application/`, `backend/tests/infrastructure/` | Comprehensive fake-runner test suite covering all states and concurrency |

---

## 5. Interfaces & Contracts

1. **HTTP API Contracts:**
   - Unchanged. No routes added or deleted.
   - `contracts/permissions.yaml` is unchanged (`scripts/check-route-contract` passes).
   - Error code `OPERATION_CONCURRENCY_CONFLICT` already maps to HTTP 409 in `backend/app/api/errors.py`.
2. **Command Bus:**
   - Middleware chain signature is standard: `Middleware.__call__(command, next_middleware)`.
3. **RuntimeSupervisor API:**
   - `start_for()` signature changes from synchronous to `async def start_for(...) -> RuntimeSupervisor`.
   - `__await__()` method removed from `RuntimeSupervisor`.

---

## 6. Failure Cases & Edge Cases

1. **Docker Daemon Unavailable / Socket Disconnected:**
   - Pre-inspect catches `FileNotFoundError` or docker CLI error, converting cleanly to `ProviderError` without leaking unhandled exceptions or corrupting lock state.
2. **Lock Held During Provider Timeout:**
   - Lock is acquired in a `try ... finally` block. If `asyncio.wait_for(provider.start(...), timeout=30)` times out, the lock is guaranteed released.
3. **Lock Waiter Budget Exceeded:**
   - Waiters that cannot acquire the lock within 60s return `OPERATION_CONCURRENCY_CONFLICT` (HTTP 409).
4. **Backend Process Restart Mid-Operation:**
   - Locks are in-memory and cleanly cleared. Boot reconciliation detects DB state vs container state and repairs inconsistencies.
5. **Daemon Name Registry Delay ("removal in progress"):**
   - Absorbed by 3-attempt bounded backoff (0.5s, 1.0s, 2.0s) rather than crashing immediately on a single retry.
6. **Foreign Container Squatting Name:**
   - Container has matching name but mismatched or missing server ID label. Provider refuses to touch the container and raises a clear descriptive `ProviderError`.

---

## 7. Tests & Verification Plan

### Test Strategy
Use real `DockerProvider` and command handlers with an injected mock/fake Docker runner (`_docker_command`) simulating daemon name-registry states (`running`, `exited`, `created`, `dead`, `removing`), async removal delays, and label storage.

### Required Test Cases
1. **Concurrent Start Serialization (B1 + B2):**
   - Two concurrent `start()` calls on the same server ID.
   - Lock serializes them; second call sees `STARTING`/`RUNNING` and succeeds idempotently.
   - Exactly one container is created; zero `docker rm -f` executed.
2. **Differing-Handle Supervisor Transition (B1):**
   - Calling `start_for` with a changed handle awaits `existing.stop(timeout=10.0)`, resets instance, and returns fresh supervisor.
3. **Docker Pre-Inspect Adoption (B2):**
   - Existing running container with matching server ID and matching config fingerprint is adopted. No `docker create` or `docker rm` called.
4. **Docker Config Mismatch Recreate (B2):**
   - Existing running container with matching server ID but altered memory/image/port is gracefully stopped (`docker stop -t 15`), removed (`docker rm`), and recreated.
5. **Legacy Container Compatibility (B2):**
   - Existing container with `mcs-` prefix and `com.mcs-manager.server_id` is recognized as ours, stopped, and recreated with modern labels.
6. **Foreign Container Refusal (B2):**
   - Container squatting `onx-<server_id>` with foreign label causes `ProviderError`. Foreign container is never removed or killed.
7. **Name Removal Lag Backoff (B2):**
   - Container in `removal-in-progress` triggers retry backoff and succeeds when status clears.
8. **Crash Stop (B2):**
   - `_handle_crash` on a running docker container issues graceful `stop` (not `rm`).
9. **Mutation Checks:**
   - Revert pre-inspect -> adoption and foreign protection tests fail.
   - Revert lock -> concurrent start test fails.
   - Revert backoff -> removal lag test fails.

### Quality Gates
- Sequential backend test run: `python -m pytest -q` from `backend/` (>=15 min timeout).
- 6/6 CI quality gates: `check-db-revision`, `check-ruff-baseline`, `check-version-propagation`, `check-route-contract`, `check-ps1-bom`, `check-stray-db`.

---

## 8. Out of Scope

- Frontend 409 retry toast / UX redesign.
- Distributed DB locking across multiple backend processes (single-process architecture currently).
- Boot-time sweep of all orphan docker containers (Decision 5b deferred).
- Changes to local, tmux, or Windows providers.
- Changes to `collect_diagnostics` failure code mappings.

---

## 9. Build Plan & Staging

### Slice B1: Concurrency Lock, Idempotency & Async Supervisor
1. Implement `ServerLifecycleLockMiddleware` in `backend/app/modules/server/application/lifecycle_lock.py`.
2. Register middleware on `command_bus` in `backend/app/registration.py`.
3. Add explicit lock acquisition in `runtime_reconciliation.py:423`.
4. Add status check idempotency in `StartServerHandler`.
5. Convert `RuntimeSupervisor.start_for` to `async def`, remove `__await__` shim, and `await existing.stop(timeout=10.0)`. Update callers in `start_server.py`, `restart_server.py`, and test files.
6. Add unit tests for middleware locking, idempotency, and async `start_for`.
7. Verify quality gates.

### Slice B2: Docker Lifecycle Idempotency & Protection
1. Implement pre-inspect, config fingerprint generation/verification, and adoption/recreation policy in `DockerProvider.start()`.
2. Implement bounded backoff for `dead`/`removal-in-progress`.
3. Add explicit awaited `rm` in `RestartServerHandler`.
4. Implement graceful stop in `RuntimeSupervisor._handle_crash` for Docker containers.
5. Add comprehensive unit tests with fake Docker runner.
6. Verify quality gates and sequential test suite.

### Build Gate Prerequisite
> [!IMPORTANT]
> **Slice B1 modifies `backend/app/modules/server/application/supervisor.py`.**  
> `supervisor.py` currently contains uncommitted modifications (`stale-startup-deadline-supervisor-2026-10-02`) and untracked `backend/tests/application/test_stale_startup_deadline.py`.  
> Per `commit-and-safety.md` and the Design Review instructions, **B1 must wait until this uncommitted work is reviewed and committed before editing `supervisor.py`.**
