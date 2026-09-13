# Reconciliation Engine

## Purpose

The reconciliation engine is a stateless scanner that detects and repairs discrepancies between a server's database state and its actual OS-level runtime state. It handles cases where the supervisor crashed, the OS was restarted, or tmux sessions were killed externally.

Defined in `application/runtime_reconciliation.py`.

## Data Structures

### MismatchType (Enum)

| Value | Meaning |
|-------|---------|
| `DB_RUNNING_NO_SUPERVISOR` | DB says RUNNING but no supervisor is tracking this server |
| `DB_RUNNING_NO_TMUX` | DB says RUNNING but no tmux session and no active supervisor |
| `DB_RUNNING_DEAD_PID` | DB says RUNNING but the stored PID is dead (not currently detected as a separate mismatch — covered by TMUX_PID_DEAD) |
| `DB_STARTING_ALIVE` | DB says STARTING but the process is fully up and port is listening |
| `SUPERVISOR_NO_TMUX` | Supervisor is running but the tmux session is gone |
| `TMUX_PID_DEAD` | Tmux pane PID exists but is not alive |
| `PID_PORT_MISMATCH` | PID associated with the server does not match the PID on the port |
| `PORT_NOT_LISTENING` | Server is RUNNING but port is not listening |
| `ORPHAN_TMUX` | Tmux session exists with no matching server in DB |
| `ORPHAN_PROCESS` | Java/Minecraft process exists with no matching managed server |

### ServerRuntimeState

A dataclass that aggregates the observed state of a single server:

- `db_status` — from the `Server` aggregate.
- `has_supervisor`, `supervisor_running` — from `RuntimeSupervisor._instances`.
- `has_tmux`, `tmux_pid` — from `provider.verify_process()` and `provider.get_runtime_pid()`.
- `pid_alive` — `os.kill(tmux_pid, 0)` check.
- `port_listening` — TCP connect test on the server's port.
- `port`, `runtime_pid`, `external_id` — from the server's `RuntimeInfo`.

## What It Checks

### For RUNNING servers

1. **Supervisor present**: if no supervisor exists, reports `DB_RUNNING_NO_SUPERVISOR` (auto-repairable: logs only, no automatic fix).
2. **Tmux session present**: if no tmux and no supervisor running, reports `DB_RUNNING_NO_TMUX` (auto-repairable: marks CRASHED).
3. **PID alive**: if tmux PID exists but `kill -0` fails, reports `TMUX_PID_DEAD` (auto-repairable: marks CRASHED).
4. **Supervisor but no tmux**: supervisor is running but tmux session is gone, reports `SUPERVISOR_NO_TMUX` (auto-repairable: stops supervisor).

### For STARTING servers

1. **Process is actually up**: if tmux exists, PID is alive, and port is listening, reports `DB_STARTING_ALIVE` (auto-repairable: transitions to RUNNING).

## Auto-Repair Logic

### Transition STARTING → RUNNING

If a server stuck in `STARTING` actually has a running process:

```python
server.mark_running(pid=state.tmux_pid or state.runtime_pid or 0,
                    port=state.port,
                    external_id=state.external_id or f"mcs-{state.server_id}")
```

### Mark CRASHED

If a server in `RUNNING` has no tmux, a dead PID, or both:

```python
server.crash(exit_code=-1,
             last_log_lines=[f"Runtime reconciliation: {m.detail}"])
```

### Stop Orphan Supervisor

If the supervisor is running but the tmux session no longer exists:

```python
await RuntimeSupervisor.stop_for(state.server_id)
```

## Per-Server Reconciliation

```python
async def reconcile_server_runtime(server, repo) → ReconciliationOutcome
```

1. Gets the provider for the server's runtime type.
2. Builds a `ServerRuntimeState` via `_get_server_state()`.
3. Runs `_detect_mismatches()` to produce a list of `MismatchReport`.
4. If mismatches exist, runs `_auto_repair()` to fix auto-repairable ones.
5. Returns a `ReconciliationOutcome` with mismatches, repair status, and actions taken.

## Bulk Reconciliation

```python
async def reconcile_all_runtimes(repo, server_ids=None) → list[ReconciliationOutcome]
```

- If `server_ids` is provided, reconciles only those servers.
- If `None`, reconciles all servers from `repo.list()`.
- Logs summary: total checked, total repaired.

## Orphan Cleanup

```python
async def reconcile_orphans() → list[dict]
```

### Orphan Tmux Sessions

1. Lists all tmux sessions with names starting with `"mcs-"`.
2. For each session, checks if it matches a server in the database.
3. If orphaned: sends `SIGTERM`, waits 0.5s, sends `SIGKILL`, then `tmux kill-session`.

### Orphan Java Processes

1. Lists all Java PIDs via `ps aux | grep java`.
2. Filters to Minecraft-related processes (checks cmdline for `-jar`, `server.jar`, `minecraft`, etc.).
3. For each orphan: sends `SIGTERM`, waits 0.5s, sends `SIGKILL`.

> **Ownership verification**: before any kill, `verify_ownership()` confirms the
> process is genuinely managed by this application — the process must carry the
> `MCS_MANAGED` marker and its `deployment_start_time` must match the DB record.
> Kills are skipped (with a `KILL_DECISION` log) when the marker is missing, the
> working directory mismatches, the start time differs, or the process is marked
> as system-wide rather than project-owned.

## Pre-Backend Database Reconciliation

Location: `backend/app/core/persistence/reconciler.py`

In addition to runtime OS process reconciliation, ONX Manager executes an upfront **Pre-Backend Database Reconciler** before any FastAPI workers or child services start.

### Architectural Principles:
1. **Zero FastAPI Import Dependency**: Operates decoupled from FastAPI routes and services.
2. **Dynamic Alembic Revision Resolution**: Resolves Alembic's latest head migration revision dynamically using Alembic `ScriptDirectory` instead of hardcoding revision numbers.
3. **Direct SQLite WAL Inspection**: Queries `alembic_version` directly with SQLite WAL mode support.
4. **ACID SQLite Backups**: Prior to upgrading populated databases, creates atomic SQLite snapshot backups in `backend/backups/` using `sqlite3.Connection.backup()`.
5. **Atomic Concurrency Guard**: Acquires file lock (`.onx/locks/reconcile.lock`) to prevent concurrent migration attempts.
6. **Classified Readiness States**:
   - `READY`: Database is already at head revision.
   - `RECONCILED`: Database was successfully migrated to head with backup taken.
   - `BLOCKED_UNSAFE`: Database has unknown or conflicting revisions requiring manual intervention.
   - `FAILED`: Migration execution encountered an unrecoverable error.
   - `UNREACHABLE`: Database connection or file permissions error.

## Filesystem Reconciliation & Identity Healing Engine

Location: `backend/app/modules/server/application/services/filesystem_reconciliation.py` and `identity_writer.py`

In addition to process-level and database migration reconciliation, the **Filesystem Reconciliation Service** synchronizes on-disk server installations in `data/servers/` with database records at backend startup and on-demand (`POST /api/v1/servers/refresh`).

### 1. Authoritative Identity Stamping
- Freshly created (`create_server.py`) and imported (`import_server.py`) servers atomically write `.onx-manager/server.json` via `write_server_identity()`.
- Identity payload format:
  ```json
  {
    "schema_version": 1,
    "server_id": "uuid-here",
    "provider": "docker"
  }
  ```
- Uses temporary staging files with atomic `os.replace` to ensure power-failure resilience.

### 2. Legacy Migration & Backward Compatibility
- Reads legacy `.mcsmanager/server.json` if `.onx-manager/server.json` is missing, automatically migrating on read.
- All new writes target `.onx-manager/server.json` exclusively.
- Archive imports actively purge legacy `.mcsmanager` directories from uploaded archives.

### 3. Deterministic Adopt vs. Heal Resolution
When discovering an un-identified server directory (e.g. legacy installation or post-crash recovery):
- Scans existing DB records for a matching normalized `root_path`.
- Applies deterministic candidate scoring:
  - `+100` points: Active server (`missing_since is None`)
  - `+50` points: In-flight/live state (`RUNNING`, `STARTING`, `CREATED`)
  - `+25` points: Matching `DOCKER` runtime provider
  - Tie-breaker: Most recent `updated_at` timestamp
- If a candidate matches, emits `ActionType.HEAL_IDENTITY`:
  - Authoritatively writes `.onx-manager/server.json` using the existing database record's UUID and provider.
  - Clears `missing_since` and restores broken status.
  - Avoids duplicate row creation, provider-badge flips, and database churn.
- If no DB record matches, emits `ActionType.ADOPT` to import the server as a new instance.

### 4. Provider Cleanup on Deletion
- During `ActionType.DELETE` handling (and in `DeleteServerHandler`), invokes `provider.destroy(server_id, root_path)` to clean up containers by name, server ID labels, and host volume bind mounts before removing the database row and files.

## Typical Mismatch Scenarios

| Scenario | Mismatch | Resolution |
|----------|----------|------------|
| Server marked RUNNING but OS was rebooted | `DB_RUNNING_NO_TMUX` | Mark CRASHED |
| Server marked STARTING but already up | `DB_STARTING_ALIVE` | Transition to RUNNING |
| Supervisor lost its tmux session | `SUPERVISOR_NO_TMUX` | Stop supervisor |
| Tmux pane process died | `TMUX_PID_DEAD` | Mark CRASHED |
| Server crashed but DB not updated | `DB_RUNNING_NO_SUPERVISOR` | Logged, no auto-repair |

## References

- [Runtime Overview](README.md) — where reconciliation fits.
- [Server Lifecycle](lifecycle.md) — states that reconciliation transitions between.
- [Supervision](supervision.md) — supervisor/mismatch interaction.
- [Ownership](ownership.md) — also discovers orphans, but reconciliation is the routine fixer.
- [Recovery Procedures](recovery.md) — manual recovery when auto-repair is insufficient.
