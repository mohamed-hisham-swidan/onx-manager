# RuntimeSupervisor

## Purpose

`RuntimeSupervisor` is a per-server async watchdog that monitors a Minecraft server process after launch. It performs heartbeat-based liveness detection, handles crash diagnosis, and ensures the server's DB state stays consistent with reality.

Defined in `application/supervisor.py`.

## Lifecycle

### Creation

A supervisor is created via the class method `RuntimeSupervisor.start_for(server, provider, handle, repo_get, repo_save, ...)`:

1. Checks the `_instances` class-level dict. If a supervisor is already active for this server ID, returns the existing one.
2. Creates a new instance, sets `_active = True`, stores it in `_instances`.
3. Schedules `supervisor.start()` via `asyncio.ensure_future()`.

### Start

```python
async def start(self) -> None
```

- Clears the `_stop_event`.
- Creates an asyncio task running `_run()` named `supervisor-{server_id}`.

### Run Loop (`_run`)

1. Calls `_verify_startup()`.
2. Enters a `while not _stop_event.is_set()` loop:
   - Increments a health check counter.
   - Calls `_health_check()`.
   - Sleeps for `_health_interval` (default 5s).
3. On `CancelledError`, logs and exits.
4. On unexpected exception, logs with full traceback.
5. In `finally`: sets `_active = False`, removes self from `_instances`.

### Stop

```python
async def stop(self) -> None
```

- Sets `_stop_event` and `_active = False`.
- Cancels the asyncio task and awaits it.
- Removes self from `_instances`.

## Startup Verification (`_verify_startup`)

- Calculates deadline = `_started_at + _startup_timeout` (default 120s).
- Loops until deadline:
  - Calls `provider.wait_ready(server_id, handle, timeout)` — for the local provider, this checks log output for "Done (".
  - If ready: records `_start_duration` (elapsed time), sets `_last_heartbeat`, logs, returns.
  - If not ready: calls `provider.verify_process(handle)`:
    - If process is dead: collects diagnostics, sets `failure_code = STARTUP_TIMEOUT`, calls `_handle_crash()`, returns.
  - Sleeps 2s between iterations.
- If deadline passes but process is still alive: logs and continues (pragmatic fallback).
- If deadline passes and process is dead: collects diagnostics, logs, calls `_handle_crash()`.

## Health Check (`_health_check`)

- Calls `provider.verify_process(handle)`.
- If process is not alive:
  - Calls `provider.status(handle)`.
  - If status is `STOPPED`: sets `_stop_event` (expected stop, not a crash).
  - Otherwise: collects diagnostics, sets `failure_code = RUNTIME_PROCESS_LOST`, calls `_handle_crash()`.
- If process is alive: updates `_last_heartbeat`.

## Crash Detection

A crash is detected in two places:

1. **During startup** — process dies before `wait_ready()` succeeds.
2. **During health check** — `verify_process()` returns `False` and status is not `STOPPED`.

## Crash Handling (`_handle_crash`)

```python
async def _handle_crash(self, diag: RuntimeDiagnostics) -> None
```

1. **Suppression check**: if `_stop_event` is already set (stop was requested), logs and returns without action.
2. **Logging**: calls `log_crash_diagnostics()` with full details (server name, ID, PID, exit code, log lines, failure code/reason).
3. **OS cleanup**: calls `_cleanup_os_resources()` — kills the tmux session using `tmux kill-session`.
4. **Persistence**: fetches the server from the repo, calls `server.crash(exit_code, last_log_lines)`, saves it. If this fails, logs a critical message that crash data will be lost.
5. **Callback**: if `_on_crash` was provided (e.g. for Discord webhook, metrics), calls it with the server ID and diagnostics.
6. **Stop event**: sets `_stop_event` to exit the supervision loop.

## Supervision Loop

```
RUN LOOP
│
├── _verify_startup()
│   ├── poll wait_ready() until deadline
│   ├── if ready → continue to health checks
│   ├── if process dies → _handle_crash() → exit
│   └── if deadline passes but alive → continue
│
├── HEALTH CHECK LOOP (every _health_interval seconds)
│   ├── verify_process()?
│   │   ├── Yes → update _last_heartbeat, sleep
│   │   └── No → status == STOPPED? → set stop event
│   │              └→ else → _handle_crash() → exit
│   └── on exception → log, continue
│
└── Cancelled / stop requested → exit cleanly
```

## Class-Level Registry

```python
_instances: dict[str, RuntimeSupervisor] = {}
```

- `start_for(server, ...)` → creates/stores.
- `stop_for(server_id)` → stops and removes.
- `get_for(server_id)` → lookup.
- `is_supervised(server_id)` → boolean check.

This prevents duplicate supervisors and allows commands to find active supervisors.

## Key Properties

| Property | Description |
|----------|-------------|
| `server_id` | Server UUID string |
| `is_running` | Whether the asyncio task is alive |
| `last_heartbeat` | Unix timestamp of last successful health check |
| `start_duration` | Seconds from start to ready, or `None` |
| `uptime` | Seconds since start_duration was recorded |

## References

- [Runtime Overview](README.md) — how the supervisor fits in the architecture.
- [Server Lifecycle](lifecycle.md) — states affected by supervisor actions.
- [Reconciliation](reconciliation.md) — can repair or stop mismatched supervisors.
- [Recovery Procedures](recovery.md) — what happens after a crash.
