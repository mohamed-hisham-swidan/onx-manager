# DESIGN SPECIFICATION: Playit Process Lifecycle & Orphan Prevention

- **Document ID**: `SPEC-PLAYIT-LIFECYCLE-001`
- **Revision**: `2.0` (Comprehensive Pass Incorporating Dual Independent Reviews)
- **Date**: 2026-08-17
- **Status**: `PROPOSED` (Awaiting Build Approval)
- **Author**: Antigravity Assistant

---

## 1. Executive Summary & Problem Statement

### 1.1 Problem Statement
During local development with `uvicorn --reload` (WatchFiles) and during application restarts/redeployments, previously spawned `playitd` child processes become orphaned in the background. Empirical investigation (`ps aux | grep playit`) revealed multiple concurrent `playitd` processes running on the host under the same user, each bound to a different PID-dependent socket path (`/tmp/mcs_playit_<PID>.sock`) and random temporary secret path (`/tmp/mcs_playit_secret_<random>.secret`).

### 1.2 End-User Symptoms
1. **Perpetual "Waiting for agent..." Poll**: When the user opens the Playit Claim page, the backend initiates a claim exchange (`playit claim exchange <code>`). If a backend restart occurs while the user is confirming the URL in their browser, the active Python process loses attachment to the exchange process. When the user confirms on `playit.gg`, the secret key is printed to the orphaned process and lost. The frontend continues polling `GET /api/v1/exposure/agent` indefinitely.
2. **Resource Exhaustion & Socket Contention**: Multiple lingering `playitd` daemon processes compete for outbound tunnel connections and network resources on the host machine.
3. **Inability to Reconnect After Reload**: Each application restart abandons the running tunnel daemon and attempts to start a duplicate rather than re-attaching or cleanly recycling.

### 1.3 Scope
* **In Scope**:
  * `PlayitAgentSupervisor` lifecycle (`playit_agent.py`): atomic file locking, deterministic paths, socket-probed startup reconciliation, bounded timeouts, and multi-layered shutdown.
  * `CloudflaredSupervisor` (`cloudflared.py`): graceful teardown hook in application lifespan shutdown.
  * Application Lifespan (`backend/app/main.py`): bounded startup orphan reconciliation pass and graceful shutdown teardown hooks.
  * Command Handlers (`commands.py`): `ResetAgentHandler` and `RemoveCredentialsHandler` process teardown in `post_commit`.
  * Permission and Path Hardening: strict error handling for uncreatable or unwriteable runtime directories.
* **Out of Scope**:
  * `PlayitApiClient` (`playit_api.py`) control-plane logic (unaffected).
  * Claim URL generation and regex pattern matching (already verified and committed in `295db1f`).
  * Phase 8 (Dynamic Endpoint & DNS Architecture).

---

## 2. Root Cause Analysis (Verified with Codebase Evidence)

The orphan proliferation is caused by four compounding gaps in the process supervision architecture:

1. **In-Memory-Only Liveness State**:
   * [`playit_agent.py:154-155`](file:///mnt/D/files/server_manger/backend/app/modules/exposure/infrastructure/playit_agent.py#L154-L155): `is_running` evaluates `self._process is not None and self._process.returncode is None`.
   * On every process restart (such as `uvicorn --reload`), the module-level singleton `_GLOBAL_PLAYIT_SUPERVISOR` is initialized fresh with `self._process = None`. The supervisor has zero knowledge of processes running on the OS.
2. **POSIX Session Detachment (`os.setsid`)**:
   * [`playit_agent.py:301-303`](file:///mnt/D/files/server_manger/backend/app/modules/exposure/infrastructure/playit_agent.py#L301-L303): `playitd` is spawned with `preexec_fn=os.setsid`.
   * This detaches the child into an independent session/process group (`SID == child PID`). When Uvicorn terminates the parent Python worker process, the kernel signal does not reach `playitd`. The child is reparented to PID 1 (`init`/`systemd`) and continues running.
3. **Absence of FastAPI Lifespan Shutdown Hooks**:
   * [`backend/app/main.py:253-258`](file:///mnt/D/files/server_manger/backend/app/main.py#L253-L258): Lifespan shutdown stops websockets, scheduler, and metrics collector, but contains **zero teardown calls** for `get_playit_supervisor()` or `get_cloudflared_supervisor()`.
4. **Dynamic Random Paths Preventing Discovery**:
   * [`playit_agent.py:264`](file:///mnt/D/files/server_manger/backend/app/modules/exposure/infrastructure/playit_agent.py#L264): Generates random secret paths (`tempfile.mkstemp(prefix="mcs_playit_secret_", suffix=".secret")`).
   * [`playit_agent.py:286`](file:///mnt/D/files/server_manger/backend/app/modules/exposure/infrastructure/playit_agent.py#L286): Generates PID-coupled socket paths (`/tmp/mcs_playit_{os.getpid()}.sock`).
   * Because every run generates new random names in `/tmp/`, a restarting supervisor has no deterministic location to look for an existing process or socket.
5. **Credential Reset Handlers Omit Teardown**:
   * [`commands.py:1228-1269`](file:///mnt/D/files/server_manger/backend/app/modules/exposure/application/commands.py#L1228-L1269): `ResetAgentHandler` and `RemoveCredentialsHandler` reset database fields but never terminate the running supervisor process.

---

## 3. Design Decisions & Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                             FastAPI Startup                              │
│                                                                          │
│  1. acquire non-blocking flock(data/run/playit/agent.lock)               │
│  2. read data/run/playit/agent.pid -> PID                                │
│  3. verify /proc/{PID}/cmdline == playitd                                │
│  4. probe Unix socket data/run/playit/agent.sock (200ms timeout)         │
│     ├── SUCCESS -> Re-attach in-memory supervisor state                  │
│     └── FAILURE -> Clean terminate (SIGTERM 5s -> SIGKILL), unlink files │
│  5. Bounded timeout: whole reconciliation aborts after 2.0s max          │
└──────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                            On-Demand Spawn                               │
│                                                                          │
│  1. Ensure directory data/run/playit (mode 0700)                         │
│  2. Write data/run/playit/agent.secret (mode 0600)                       │
│  3. Spawn playitd --secret-path ... --socket-path ...                    │
│  4. Write data/run/playit/agent.pid                                      │
└──────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                             Shutdown Hook                                │
│                                                                          │
│  1. FastAPI lifespan context exit (main.py)                              │
│  2. Secondary signal/atexit backstop                                     │
│  3. Send SIGTERM to tracked child PID                                    │
│  4. Await proc.wait() timeout=5.0s -> SIGKILL fallback 3.0s              │
│  5. Unlink PID, secret, socket, and lock files                           │
└──────────────────────────────────────────────────────────────────────────┘
```

### Decision 1: Deterministic Paths, Directory Permissions & Atomic File Locking

* **Deterministic Runtime State Directory**:
  All runtime process artifacts for `playit` are moved out of `/tmp` into a project-managed directory:
  * Directory: `data/run/playit/` (resolved via `Path(AppSettings().servers_data_dir).parent / "run" / "playit"` or `data/run/playit`).
  * Directory Permissions: `0o700` (`rwx------`), created with `parents=True, exist_ok=True`.
* **Standardized File Artifacts**:
  1. `data/run/playit/agent.secret`: Decrypted agent secret (mode `0o600`, `rw-------`).
  2. `data/run/playit/agent.sock`: Unix domain socket for control communication.
  3. `data/run/playit/agent.pid`: ASCII process ID of the running supervisor child.
  4. `data/run/playit/agent.lock`: Lockfile for cross-process mutual exclusion.
* **Atomic OS-Level Mutual Exclusion (`fcntl.flock`)**:
  To prevent TOCTOU races during rapid Uvicorn reloads or overlapping worker processes:
  * The supervisor acquires an exclusive, non-blocking lock (`fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)`) before modifying PID files, checking liveness, or spawning child processes.
  * When a process terminates (even via crash or SIGKILL), the Linux kernel automatically releases all `flock` locks held by the process table entry.

### Decision 2: Bounded Startup Orphan Reconciliation with Dual Verification

On application startup in `main.py:lifespan`:
1. **Bounded Execution Timeout**: The entire reconciliation routine is wrapped in `asyncio.wait_for(..., timeout=2.0)` with top-level `try/except Exception`. It will **never** block application boot or delay readiness.
2. **Dual-Stage Liveness Verification**:
   * **Stage 1 (PID & Cmdline Check)**:
     Read `agent.pid`. Check if process is alive via `os.kill(pid, 0)`. Read `/proc/{pid}/cmdline` (or `psutil`) and verify that the command contains `"playit"` or `"playitd"`. If PID is dead or recycled by an unrelated command $\to$ clean up stale files.
   * **Stage 2 (Socket Control Liveness Probe)**:
     If PID and cmdline match, attempt a Unix domain socket connection to `data/run/playit/agent.sock` with a `200ms` connection timeout.
     * **Probe Success**: The daemon is healthy and actively serving. Re-attach supervisor in-memory state (`self._process = ...`, `self._status = ExposureStatus.ACTIVE`).
     * **Probe Failure**: The daemon is unresponsive or hung. Send `SIGTERM` (5.0s) $\to$ `SIGKILL` (3.0s), unlink stale socket and PID files, and allow on-demand fresh spawn.
3. **No Unsolicited Eager Spawning**:
   Reconciliation only discovers and re-attaches to existing valid daemons or cleans up stale artifacts. It does not spawn a new process if exposure is not currently enabled.

### Decision 3: Multi-Layered Graceful Shutdown (Lifespan + Secondary Backstop)

To ensure reliable termination across both standard production shutdowns and development `uvicorn --reload` cycles:
1. **Primary Hook (ASGI Lifespan)**:
   Add supervisor stops to [`main.py:253-258`](file:///mnt/D/files/server_manger/backend/app/main.py#L253-L258):
   ```python
   await get_playit_supervisor().stop()
   await get_cloudflared_supervisor().stop()
   ```
2. **Secondary Hook (Signal / Atexit Backstop)**:
   Register a lightweight `atexit` and `signal.SIGTERM` handler that sends `SIGTERM` to the PID stored in `data/run/playit/agent.pid` if the process exits abruptly without completing ASGI lifespan teardown.
3. **Graceful Signal Sequence**:
   * Send `SIGTERM` directly to the child PID (`os.kill(pid, signal.SIGTERM)`).
   * Wait up to `5.0s` for clean exit.
   * If process does not exit within `5.0s`, escalate to `SIGKILL` with `3.0s` timeout.
   * Clean up `agent.secret`, `agent.sock`, `agent.pid`, and release `agent.lock`.

### Decision 4: Credential Reset & Removal Handler Teardown

In [`commands.py:1228-1269`](file:///mnt/D/files/server_manger/backend/app/modules/exposure/application/commands.py#L1228-L1269):
* Update `ResetAgentHandler` and `RemoveCredentialsHandler` to append `get_playit_supervisor().stop` to `post_commit`.
* When the instance owner resets or removes credentials, any active daemon or in-flight claim-exchange process is terminated immediately with graceful SIGTERM drain.

### Decision 5: Retention of `os.setsid` with Explicit PID-Targeted Signaling

* `preexec_fn=os.setsid` ([`playit_agent.py:302`](file:///mnt/D/files/server_manger/backend/app/modules/exposure/infrastructure/playit_agent.py#L302)) is **intentionally preserved**.
* Rationale: Detaching the long-running daemon from the parent process group prevents accidental termination when signals are broadcast to the parent group (e.g. terminal signals, CLI subcommands).
* Because Decision 3 targets `os.kill(pid, signal.SIGTERM)` directly at the tracked child PID rather than broadcasting to a process group, `os.setsid` poses zero barrier to clean supervisor teardown.

### Decision 6: Cloudflare Supervisor Alignment

* `CloudflaredSupervisor` ([`cloudflared.py`](file:///mnt/D/files/server_manger/backend/app/modules/exposure/infrastructure/cloudflared.py)) is confirmed to share the same missing lifespan teardown gap.
* Lifespan shutdown in `main.py` will invoke `await get_cloudflared_supervisor().stop()` and iterate over any active server supervisors in `_server_supervisors` to cleanly terminate child tunnels on reload/shutdown.

### Decision 7: Robust Path & Permission Error Handling

* If `data/run/playit/` cannot be created (e.g. read-only filesystem or permissions error):
  * Catch `OSError` / `PermissionError`.
  * Set supervisor status to `ExposureStatus.ERROR`.
  * Set `error_message = "Failed to initialize runtime state directory at data/run/playit: Permission denied"`.
  * Do **not** silently fall back to random `/tmp` paths that reintroduce the orphan defect.

---

## 4. State Machine & Execution Flow

```
+-------------------------------------------------------------------------+
|                              Supervisor State                           |
+-------------------------------------------------------------------------+
                                     │
                    ┌────────────────┴────────────────┐
                    │                                 │
             [Fresh Boot / Restart]            [Claim Required]
                    │                                 │
                    ▼                                 ▼
           Startup Reconciliation              Spawn Claim Exchange
       (flock -> PID -> Socket probe)         (playit claim exchange)
                    │                                 │
         ┌──────────┴──────────┐                      │
         │                     │                      ▼
  [Probe Success]       [Probe Failure]         Capture Secret
         │                     │                (regex stdout)
         ▼                     ▼                      │
     Re-attach            Clean Unlink                ▼
  (is_running=True)     (Spawn on demand)        Restart Daemon
         │                     │             (playitd --secret-path)
         └──────────┬──────────┘                      │
                    │                                 │
                    ▼                                 ▼
                 ACTIVE                            ACTIVE
                    │                                 │
                    └────────────────┬────────────────┘
                                     │
                             [Shutdown / Reset]
                                     │
                                     ▼
                             Graceful Teardown
                         (SIGTERM 5s -> SIGKILL)
                                     │
                                     ▼
                                  STOPPED
                        (PID/Sock/Secret unlinked)
```

---

## 5. Comprehensive Acceptance Criteria & Test Scenarios

| Test Scenario | Description & Setup | Expected Behavior |
|---|---|---|
| **T-PL-01** | **Uvicorn Reload Re-attachment**<br>Start agent $\to$ simulate reload by creating a second supervisor instance against the same runtime directory. | Second supervisor detects lock/PID/socket and re-attaches (`is_running=True`); does **not** call `create_subprocess_exec`. |
| **T-PL-02** | **Graceful Shutdown Cleanup**<br>Start agent $\to$ invoke `supervisor.stop()`. | Sends SIGTERM to child PID; unlinks `agent.pid`, `agent.sock`, `agent.secret`; releases lock. Zero orphans. |
| **T-PL-03** | **Unresponsive Process Socket Probe Failure**<br>Live PID matching `playitd` cmdline but unresponsive socket (or closed socket). | Reconciliation detects socket probe timeout (200ms) $\to$ terminates hung process with SIGTERM/SIGKILL $\to$ unlinks stale files $\to$ ready for fresh spawn. |
| **T-PL-04** | **Stale PID File Cleanup (Dead PID)**<br>PID file contains PID that does not exist in `/proc`. | Reconciliation detects `ProcessLookupError` / `os.kill(pid, 0)` failure $\to$ unlinks stale PID file without crashing $\to$ continues boot. |
| **T-PL-05** | **Recycled PID Collision (Different Process)**<br>PID file contains a PID that is alive, but `/proc/{pid}/cmdline` is `python` or `nginx`. | Reconciliation detects cmdline mismatch $\to$ does **not** signal or attach to the unrelated process $\to$ cleans stale PID file. |
| **T-PL-06** | **Concurrent Startup Lock Contention (TOCTOU)**<br>Two concurrent workers attempt reconciliation simultaneously. | First worker acquires `flock` and completes reconciliation; second worker non-blocking lock wait handles state gracefully without duplicate spawn. |
| **T-PL-07** | **Startup Reconciliation Bounded Timeout**<br>Simulate a hanging filesystem / slow socket connect during startup. | `asyncio.wait_for` triggers at 2.0s $\to$ logs warning $\to$ application startup completes without hanging. |
| **T-PL-08** | **Directory & Permission Failure Handling**<br>Simulate uncreatable/read-only `data/run/playit/` directory. | Catches `PermissionError` $\to$ sets `ExposureStatus.ERROR` with descriptive message $\to$ avoids silent `/tmp` fallback. |
| **T-PL-09** | **Credential Reset Teardown**<br>Invoke `ResetAgentHandler` while supervisor is running. | `agent.reset()` persists to DB $\to$ `supervisor.stop` runs in `post_commit` $\to$ daemon process terminated. |
| **T-PL-10** | **Credential Removal Teardown**<br>Invoke `RemoveCredentialsHandler` while supervisor is running. | `agent.remove_credentials()` persists to DB $\to$ `supervisor.stop` runs in `post_commit` $\to$ daemon process terminated. |
| **T-PL-11** | **Cloudflared Lifespan Teardown**<br>Invoke FastAPI lifespan shutdown with running `CloudflaredSupervisor`. | Both panel singleton and server cloudflared supervisors are stopped. |
| **T-PL-12** | **Same-Process Concurrency Regression Check**<br>Execute `test_concurrent_start_idempotency` with 5 concurrent `gather()` calls. | Passes unmodified with `call_count == 1`. |

---

## 6. Findings Ledger

| ID | Finding | Classification | Resolution Strategy |
|---|---|---|---|
| **F-PL-01** | `is_running` checks only in-memory state. | BUG | Addressed by Decision 2 (Stage 1 PID + Stage 2 Socket probe). |
| **F-PL-02** | `os.setsid` detaches child from parent signal group. | ARCHITECTURE | Preserved per Decision 5; PID-targeted signals used in Decision 3. |
| **F-PL-03** | Missing FastAPI lifespan shutdown hook. | BUG | Addressed by Decision 3 (lifespan hook + atexit backstop). |
| **F-PL-04** | Dynamic random paths (`mkstemp`, `os.getpid()`) prevent discovery. | BUG | Addressed by Decision 1 (deterministic `data/run/playit/` paths). |
| **F-PL-05** | Reset and Remove Credentials handlers omit daemon teardown. | BUG | Addressed by Decision 4 (`post_commit` teardown). |
| **F-PL-06** | Precedent in `reconcile_orphans` (`main.py:107-133`). | ARCHITECTURE | Informs Decision 2 (bounded startup reconciliation). |
| **F-PL-07** | TOCTOU race condition during concurrent worker restart. | RACE CONDITION | Addressed by Decision 1 (`fcntl.flock` atomic file locking). |
| **F-PL-08** | Zombie/hung process false-positive re-attachment. | RELIABILITY | Addressed by Decision 2 (socket liveness probe with 200ms timeout). |
| **F-PL-09** | Unbounded startup reconciliation hanging FastAPI boot. | AVAILABILITY | Addressed by Decision 2 (`asyncio.wait_for(..., timeout=2.0)`). |
| **F-PL-10** | Unhandled directory permission failures. | ERROR HANDLING | Addressed by Decision 7 (`0700` creation and explicit `ERROR` status). |
