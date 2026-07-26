# Server Lifecycle

## States

The `ServerStatus` enum (`domain/aggregate.py:31`) defines six states:

```
CREATED ──> STARTING ──> RUNNING ──> STOPPING ──> STOPPED
               │            │            │
               └──> CRASHED <┘<──────────┘
```

### CREATED

Initial state after `Server.create()`. The server exists in the database but has no OS resources associated. The only valid transition is to `STARTING`.

### STARTING

Entered via `server.start()` (called by `StartServerHandler`). The provider is launching the process (creating a tmux session, starting a Docker container, etc.) and the `RuntimeSupervisor` is running `_verify_startup()` — polling `provider.wait_ready()` which checks for the "Done (" message in server logs. Valid transitions:

- `RUNNING` — startup verification passed (process ready, port listening).
- `CRASHED` — process died during startup, or startup timeout exceeded (default 120s).

### RUNNING

Entered via `server.mark_running(pid, port, external_id)`. This is called after the provider's `start()` returns successfully. The supervisor runs periodic `_health_check()` calls. Valid transitions:

- `STOPPING` — via `server.stop()` (from `StopServerHandler` or `RestartServerHandler`).
- `CRASHED` — supervisor detects process loss, or reconciliation detects a dead PID/tmux.

### STOPPING

Entered via `server.stop(reason)`. The handler stops the supervisor first, then calls `provider.stop(handle)` (graceful: "say ...", "save-all", "stop"; then SIGTERM/SIGKILL). Valid transitions:

- `STOPPED` — provider confirmed the process is stopped, port released.
- `CRASHED` — if something goes wrong during stop (allowed by the transition map but not used in practice).

### STOPPED

Entered via `server.mark_stopped()`. The server has no OS resources. Valid transitions:

- `STARTING` — can be started again via `StartServerHandler`.

### CRASHED

Entered via `server.crash(exit_code, last_log_lines)`. The supervisor's `_handle_crash()` persists this with diagnostics. Valid transitions:

- `STARTING` — can be restarted.

## Transition Map

Enforced by `_SERVER_TRANSITIONS` (`domain/aggregate.py:40`):

```python
_SERVER_TRANSITIONS = {
    ServerStatus.CREATED:   {ServerStatus.STARTING},
    ServerStatus.STARTING:  {ServerStatus.RUNNING, ServerStatus.CRASHED},
    ServerStatus.RUNNING:   {ServerStatus.STOPPING, ServerStatus.CRASHED},
    ServerStatus.STOPPING:  {ServerStatus.STOPPED, ServerStatus.CRASHED},
    ServerStatus.STOPPED:   {ServerStatus.STARTING},
    ServerStatus.CRASHED:   {ServerStatus.STARTING},
}
```

Any invalid transition raises `InvalidValueError`.

## Command Flow

### Start (`start_server.py`)

1. Check if a supervisor already exists for this server; if so, stop it.
2. Within a `UnitOfWork`: fetch server, call `server.start()`, save, commit.
3. Call `RuntimeOwnershipManager.claim_localhost()` to secure the host.
4. Verify port is free.
5. Call `provider.start()` with deployment and launch config.
6. Within a new `UnitOfWork`: `server.mark_running(pid, port, external_id)`, save, commit.
7. Create `RuntimeSupervisor` via `RuntimeSupervisor.start_for()`.
8. Return success with pid, port, address.

### Stop (`stop_server.py`)

1. Within a `UnitOfWork`: fetch server, call `server.stop(reason)`, save, commit.
2. Stop supervisor via `RuntimeSupervisor.stop_for()`.
3. Call `provider.stop(handle)` (graceful, with 15s timeout; falls back to `force=True`).
4. Verify provider status shows `STOPPED`.
5. Wait for port to be released (up to 5s).
6. Within a `UnitOfWork`: `server.mark_stopped()`, save, commit.

### Restart (`restart_server.py`)

1. Within a `UnitOfWork`: fetch server, call `server.stop("restart")` followed immediately by `server.mark_stopped()`, save, commit.
2. Stop supervisor and provider (same as stop flow).
3. Wait for port release.
4. Within a `UnitOfWork`: `server.start()`, save, commit.
5. Call `RuntimeOwnershipManager.claim_localhost()`.
6. Call `provider.start()`.
7. Within a `UnitOfWork`: `server.mark_running()`, save, commit.
8. Create new `RuntimeSupervisor`.

## Crash Path

When the supervisor detects a crash (either during startup or during a health check):

1. `_handle_crash(diag)` is called with a `RuntimeDiagnostics` object.
2. Logs crash diagnostics via `log_crash_diagnostics()`.
3. Cleans up OS resources (kills tmux session).
4. Fetches the server from the repo, calls `server.crash(exit_code, last_log_lines)`, saves.
5. Calls `on_crash` callback if registered (for external alerting).
6. Sets `_stop_event` to exit the supervision loop.

## References

- [Runtime Overview](README.md)
- [Supervision](supervision.md)
- [Reconciliation](reconciliation.md)
- [Recovery Procedures](recovery.md)
