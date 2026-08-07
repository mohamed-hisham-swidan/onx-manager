# Recovery Procedures

This document covers runtime failure scenarios and how the system recovers — both automatically and through manual intervention.

## Automatic Recovery

### Server Process Crashes

When `RuntimeSupervisor` detects a crash (see [Supervision](supervision.md#crash-handling-_handle_crash)):

1. **Crash diagnostics** are collected: last 300 log lines, PID, exit code, failure code/reason.
2. **OS resources cleaned**: the tmux session is killed.
3. **DB state updated**: `server.crash()` transitions the aggregate to `CRASHED`, records `last_crash_time`, clears `external_id`.
4. **External callback**: if `on_crash` was registered (e.g. for Discord webhooks or metrics), it fires with the diagnostics.
5. **Supervisor exits**: the supervision loop terminates.

If the crash happens during startup verification, the failure code is `STARTUP_TIMEOUT`. During a health check, it is `RUNTIME_PROCESS_LOST`.

### Reconciliation Auto-Repairs

The [Reconciliation Engine](reconciliation.md) runs on demand (`reconcile_all_runtimes()`) or can be scheduled. It handles:

| Condition | Auto-Repair |
|-----------|-------------|
| DB says `STARTING` but process is actually up | Transitions to `RUNNING` |
| DB says `RUNNING` but no tmux/supervisor exists | Marks `CRASHED` |
| Supervisor running but tmux session gone | Stops the supervisor |
| Tmux pane PID is dead | Marks `CRASHED` |

### Ownership Claims During Start

Every `StartServerHandler` calls `RuntimeOwnershipManager.claim_localhost()` before launching. This:

1. Displaces any other running server (stops supervisor, force-stops provider, kills PID, marks displaced as `CRASHED`).
2. Kills orphan tmux sessions and Minecraft processes.
3. Frees the target port (kills any occupant process).
4. If the claim has warnings, the start still proceeds but warnings are logged.

## Manual Recovery Procedures

### Scenario: Server Crashing on Startup

**Symptoms:** Server transitions to `STARTING` then immediately to `CRASHED`. The supervisor's startup verification keeps failing.

**Steps:**

1. Check the last crash diagnostics:
   ```
   RuntimeSupervisor.get_for(server_id) — inspect last log lines
   ```
2. Check the server's deployment and launch config — verify JAR path, Java version, memory settings.
3. View the console logs via `provider.console(handle, tail=300)`.
4. Fix the config and restart the server.
5. If the issue persists, increase `startup_timeout` (default 120s) or check if the JAR download is corrupted (see [PROVISIONING.md](../architecture/PROVISIONING.md)).

### Scenario: Split-Brain — Two Servers Claiming the Same Resources

**Symptoms:** `RuntimeOwnershipManager.discover_all()` detects `DUPLICATE_PID`, `DUPLICATE_PORT`, or `MULTIPLE_SERVERS_ACTIVE`.

**Steps:**

1. Run ownership discovery manually:
   ```python
   mgr = RuntimeOwnershipManager(repo)
   snapshot = await mgr.discover_all()
   ```
2. Inspect `snapshot.conflicts` and `snapshot.active_servers`.
3. Decide which server should keep ownership.
4. Run `claim_localhost()` for the correct server — this will displace all others and clean up orphans.
5. Run `reconcile_all_runtimes()` to fix any lingering DB/OS mismatches.
6. Verify with `validate_runtime()` on the surviving server.

### Scenario: Stale DB Record — DB Says RUNNING but Nothing Is Running

**Symptoms:** A server is stuck in `RUNNING` status but no OS process exists.

**Steps:**

1. Run reconciliation:
   ```python
   from app.modules.server.application.runtime_reconciliation import reconcile_all_runtimes
   outcomes = await reconcile_all_runtimes(repo)
   ```
   This will detect `DB_RUNNING_NO_TMUX` and mark the server as `CRASHED`.
2. If reconciliation does not help (e.g. mismatches are not auto-repairable), run orphan cleanup:
   ```python
   await mgr.cleanup_orphans()
   ```
   This marks stale records as `CRASHED`.
3. Start the server fresh.

### Scenario: Orphan OS Resources

**Symptoms:** Tmux sessions or Java processes left running with no DB server.

**Steps:**

1. Run `reconcile_orphans()` — this kills orphan tmux sessions and Minecraft processes (after verifying each process is genuinely managed via the `MCS_MANAGED` marker and matching `deployment_start_time`).
2. Or use the ownership manager:
   ```python
   await mgr.cleanup_orphans()
   ```
   This does the same but also marks stale DB records.

### Scenario: Stale Supervisor

**Symptoms:** A server has an active tmux session and DB says `RUNNING`, but no `RuntimeSupervisor` is tracking it.

**Steps:**

1. Check `RuntimeSupervisor.is_supervised(server_id)`.
2. Run reconciliation — it will detect `DB_RUNNING_NO_SUPERVISOR`.
3. Restart the supervisor manually by calling `RuntimeSupervisor.start_for()` with the correct handle, or restart the server.

### Scenario: Port Not Released After Stop

**Symptoms:** After stopping a server, the port is still in use and a new server cannot start.

**Steps:**

1. Identify the occupant: `_pid_for_port(port)`.
2. `claim_localhost()` during the next start will automatically kill the occupant.
3. If the occupant process is stuck, manually `kill -9` it and verify with `_port_is_listening(port)`.
4. If the port is truly free but `claim_localhost()` still fails, increase `_wait_for_port_free()` timeout.

### Scenario: Reconciliation Cannot Repair

If `_auto_repair()` logs a mismatch as not auto-repairable (`auto_repairable=False`), the most common case is `DB_RUNNING_NO_SUPERVISOR` — where the DB says `RUNNING` but no supervisor exists and repair is limited to logging:

1. Manually inspect the server state using `validate_runtime()`.
2. If the server is actually running but lacks a supervisor, create one via `RuntimeSupervisor.start_for()`.
3. If the server is not actually running, manually set the state:
   ```python
   server.crash(exit_code=-1, last_log_lines=["Manual recovery — process not found"])
   await repo.save(server)
   ```

## Diagnostics Reference

### FailureCode Enum (`domain/diagnostics.py`)

| Code | Meaning |
|------|---------|
| `STARTUP_TIMEOUT` | Server did not become ready within timeout |
| `READINESS_PROBE_FAILED` | Provider's wait_ready returned False |
| `RUNTIME_HANDLE_MISSING` | No handle/process reference available |
| `RUNTIME_PROCESS_LOST` | Process died while in RUNNING state |
| `PROVIDER_LAUNCH_FAILED` | Provider.start raised an exception |
| `PROVIDER_STOP_FAILED` | Provider.stop raised an exception |
| `TMUX_SESSION_LOST` | Tmux session disappeared unexpectedly |
| `JAVA_PROCESS_NOT_FOUND` | No Java PID under the tmux pane |
| `PORT_CONFLICT` | Multiple servers on same port |
| `PORT_ALREADY_BOUND` | Port in use at start time |
| `MEMORY_EXHAUSTED` | OOM detected |
| `JAVA_VERSION_MISMATCH` | Wrong Java version |
| `UNKNOWN_RUNTIME_FAILURE` | Catch-all |

## Validation Chain

To check a single server's health at any point:

```python
mgr = RuntimeOwnershipManager(repo)
validation = await mgr.validate_runtime(server_id)
print(validation.chain)
print("Healthy:", validation.healthy)
```

The chain includes: `db`, `supervisor`, `tmux`, `pid`, `port`, `minecraft`. If any link is broken, `healthy` is `False`.

## Summary of Recovery Actions

| Problem | Auto-Fix | Manual Command |
|---------|----------|----------------|
| Process crash | Supervisor → mark CRASHED, clean tmux | Restart server |
| Startup failure | Supervisor → mark CRASHED | Check config/logs, restart |
| DB/OS mismatch | Reconciliation → auto-repair | `reconcile_all_runtimes()` |
| Orphan tmux/process | Reconciliation/cleanup → kill | `reconcile_orphans()` or `cleanup_orphans()` |
| Stale DB record | Reconciliation/cleanup → CRASHED | `cleanup_orphans()` |
| Port conflict | `claim_localhost()` → displace occupant | `claim_localhost(server_id)` |
| Missing supervisor | None (logged only) | `RuntimeSupervisor.start_for()` |
| Split-brain | `claim_localhost()` → displace extras | `discover_all()` → `claim_localhost()` |

## References

- [Runtime Overview](README.md)
- [Server Lifecycle](lifecycle.md) — state transition reference.
- [Supervision](supervision.md) — crash detection and handling details.
- [Reconciliation](reconciliation.md) — auto-repair scenarios.
- [Ownership](ownership.md) — conflict detection and claim flow.
