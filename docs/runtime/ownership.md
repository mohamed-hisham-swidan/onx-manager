# RuntimeOwnershipManager

## Purpose

`RuntimeOwnershipManager` is the resource-claiming and conflict-detection layer. Before any server starts, it ensures exclusive access to ports, processes, and tmux sessions on the local host. It also detects stale records, orphan resources, and split-brain conditions.

Defined in `application/runtime_ownership.py`.

## Constructor

```python
RuntimeOwnershipManager(repo: ServerRepository, provider_factory: ProviderFactory | None = None)
```

- `repo` — provides access to all server aggregates.
- `provider_factory` — defaults to the module-level singleton from `providers/__init__.py`.

## Methods

### discover_all() → OwnershipSnapshot

Scans all OS resources and cross-references them with DB records. Returns an `OwnershipSnapshot` containing:

- **active_servers** — servers with matching tmux sessions and processes.
- **orphan_tmux** — tmux sessions with no matching DB server.
- **orphan_processes** — Minecraft Java processes not attached to any managed tmux session.
- **stale_db_records** — servers the DB marks as RUNNING/STARTING but have no OS resources.
- **stale_supervisors** — servers with active tmux but no `RuntimeSupervisor` tracking them.
- **conflicts** — list of `ConflictInfo` objects.
- **localhost_owner** — the server ID whose port is currently listening (first found).
- **total_orphans** — count of orphan tmux sessions + orphan processes.

#### Discovery Process

1. Fetches all servers from the DB.
2. Lists all tmux sessions (`tmux list-sessions`) with names matching `mcs-*`.
3. Lists all Java PIDs (`ps aux | grep java`).
4. For each DB server:
   - Matches its session name (`external_id` or `mcs-{sid}`) against tmux sessions.
   - If matched: reads pane PID, finds Minecraft child processes recursively, checks port.
   - Tracks seen PIDs to detect `DUPLICATE_PID`.
   - Tracks port-to-server mapping to detect `DUPLICATE_PORT`.
5. Remaining unmatched tmux sessions → `orphan_tmux`.
6. Remaining Java PIDs that match Minecraft cmdline patterns → `orphan_processes`.
7. DB servers in RUNNING/STARTING with no tmux → `stale_db_records`.
8. Running servers with tmux but no supervisor → `stale_supervisors`.
9. If more than one server is active → adds `MULTIPLE_SERVERS_ACTIVE` conflict.

### claim_localhost(requesting_server_id) → ClaimResult

Claims exclusive localhost ownership for a specific server. This is the most destructive/powerful method — it clears all competing resources.

**Process:**

1. Runs `discover_all()` to get a full snapshot.
2. Identifies other active servers (not the requesting one).
3. For each competing server:
   - Stops its supervisor (`RuntimeSupervisor.stop_for()`).
   - Force-stops its provider (`provider.stop(handle, force=True)`).
   - Waits for port release (up to 3s).
   - Kills the process if still alive.
   - Marks the displaced server as `CRASHED` in the DB.
4. Kills all orphan tmux sessions (`_try_kill_tmux_session()`).
5. Kills all orphan Minecraft processes (`_try_kill_process()`).
6. If the requesting server's port is already listening: kills the occupying process, waits for port release.
7. Returns `ClaimResult.success = True` only if there are zero warnings.

**Warnings are generated when:**
- A displaced server's force-stop failed.
- A port could not be freed.
- An orphan could not be killed.

### validate_runtime(server_id) → ValidationChain

Validates a single server's runtime health along a chain of checks:

| Check | Condition | Failures detected |
|-------|-----------|-------------------|
| `db_ok` | Server status is RUNNING or STARTING | Stale DB state |
| `supervisor_ok` | Supervisor exists and `.is_running` | Missing/dead supervisor |
| `tmux_ok` | Matching tmux session exists | Missing tmux |
| `pid_ok` | Tmux pane PID or Minecraft child PID is alive | Dead process |
| `port_ok` | Server's port is listening | Port not bound |
| `minecraft_ok` | Both port_ok and pid_ok | Minecraft-specific degradation |

Result `.healthy = True` only if all six are OK.

### cleanup_orphans() → list[dict]

Disposes all unowned resources discovered by `discover_all()`:

- Kills orphan tmux sessions.
- Kills orphan Minecraft processes.
- Marks stale DB records as `CRASHED` (with reason "Stale DB record cleaned by orphan cleanup").
- Detects stale supervisors (logs only — does not automatically restart).

> Every kill is gated by `verify_ownership()`: the process must carry the
> `MCS_MANAGED` marker and a `deployment_start_time` matching the DB record.
> Verification compares marker, working directory, process start time, and
> ownership scope (`project_owned` vs `system_wide`); kills are skipped when the
> process cannot be proven to belong to this project.

## Conflict Reasons

Defined in `ConflictReason` enum (`ownership.py:43`):

| Reason | Description | Auto-Resolvable |
|--------|-------------|:---:|
| `DUPLICATE_PORT` | Two servers claim the same port | Yes |
| `DUPLICATE_PID` | Same OS PID appears for multiple servers | Yes |
| `ORPHAN_TMUX` | Tmux session with no DB server | Yes |
| `ORPHAN_PROCESS` | Minecraft process with no managed server | Yes |
| `ORPHAN_PORT` | Port is listening but no server claims it | Yes |
| `STALE_DB_RECORD` | DB says running but no OS resources | Yes |
| `STALE_SUPERVISOR` | Server running but no supervisor tracking it | Yes |
| `MULTIPLE_SERVERS_ACTIVE` | More than one server is running on this host | Yes |
| `PORT_NOT_RELEASED` | Port still occupied after a stop/claim | No |
| `PROCESS_NOT_TERMINATED` | Process not dead after SIGKILL | No |

## Utility Functions

| Function | Purpose |
|----------|---------|
| `_find_all_tmux_sessions()` | Lists all tmux sessions, returns `[(name, pane_pid)]` |
| `_get_tmux_pane_pid(session)` | Gets the pane PID for a tmux session |
| `_find_all_java_pids()` | Lists all Java PIDs on the system |
| `_get_java_cmdline(pid)` | Reads `/proc/{pid}/cmdline` |
| `_is_minecraft_cmdline(cmdline)` | Matches cmdline against known Minecraft jar patterns |
| `_is_pid_alive(pid)` | `kill -0` check |
| `_port_is_listening(port)` | TCP `connect_ex()` on `127.0.0.1:port` |
| `_pid_for_port(port)` | `ss -tlnp` to find which PID owns a port |
| `_find_child_java_pids(pid)` | Recursive child PID discovery via `ps --ppid` |
| `_find_minecraft_child_pids(pid)` | Alive Java children of a tmux pane PID |
| `_wait_for_port_free(port, timeout)` | Polls until port is not listening (default 5s) |
| `_wait_for_pid_dead(pid, timeout)` | Polls until PID is not alive (default 3s) |
| `_try_kill_process(pid)` | SIGTERM → wait → SIGKILL, returns `(success, reason)` |
| `_try_kill_tmux_session(session)` | Kills pane PID + `tmux kill-session`, returns `(success, reason)` |

## Minecraft PID Detection

The manager identifies Minecraft processes by matching `/proc/{pid}/cmdline` against patterns in `MINECRAFT_CMDLINE_PATTERNS` (`ownership.py:25`):

- `-jar` with any of: `server.jar`, `paper`, `purpur`, `fabric`, `forge`, `spigot`, `bukkit`.
- Or base names: `paper*.jar`, `purpur*.jar`, `fabric*.jar`, `forge*.jar`, `spigot*.jar`, `bukkit*.jar`.
- Or cmdline containing both `minecraft` and `server`.

## References

- [Runtime Overview](README.md) — how ownership fits with supervisor and reconciliation.
- [Server Lifecycle](lifecycle.md) — claim is called before every start.
- [Reconciliation](reconciliation.md) — overlaps with orphan detection, focused on repair.
- [Recovery Procedures](recovery.md) — split-brain scenarios and manual recovery.
