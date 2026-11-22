# Runtime System Overview

The runtime system manages Minecraft server lifecycle, supervision, state reconciliation, and resource ownership on the local host. It is composed of three core components that work together in a feedback loop.

## Architecture

```
                   ┌──────────────────────────┐
                   │   RuntimeOwnershipManager  │
                   │  (conflict detection &     │
                   │   resource claiming)       │
                   └──────────┬───────────────┘
                              │ discover/claim
                              v
┌──────────────┐    ┌──────────────────┐    ┌──────────────────┐
│   Commands   │───>│ RuntimeSupervisor │───>│  ServerProvider  │
│ (start/stop/ │    │ (per-server async │    │ (local/docker/   │
│  restart)    │    │  heartbeat loop)  │    │  ssh/cloud)      │
└──────────────┘    └────────┬─────────┘    └──────────────────┘
                    │  crash detection
                    v
                     ┌───────────────────────┐
                     │   ReconciliationEngine │
                     │  (DB ↔ OS state fixer, │
                     │   orphan cleanup)      │
                     └───────────────────────┘
                              │ filesystem drift
                              v
                     ┌──────────────────────────┐
                     │ FilesystemReconciliation │
                     │ (DB ↔ disk sync,         │
                     │  auto-import,            │
                     │  stale record cleanup)    │
                     └──────────────────────────┘
```

## Components

### RuntimeSupervisor

Defined in `runtime/supervision.md`. An async per-server watchdog that:

- Verifies startup within a configurable timeout (default 120s).
- Runs periodic health checks (default every 5s) via `provider.verify_process()`.
- Detects crashes (process lost, tmux session gone) and transitions the server to `CRASHED` state.
- Cleans up OS resources (tmux sessions) on crash.
- Calls an optional `on_crash` callback for external notification.

### Reconciliation Engine

Defined in `runtime/reconciliation.md`. A stateless scanner that:

- Compares each server's DB status against actual OS state (tmux sessions, PIDs, ports).
- Detects mismatches: `DB_RUNNING_NO_SUPERVISOR`, `DB_RUNNING_NO_TMUX`, `DB_STARTING_ALIVE`, `TMUX_PID_DEAD`, `SUPERVISOR_NO_TMUX`.
- Auto-repairs where possible: transitions `STARTING → RUNNING` if the process is alive, marks `CRASHED` if the process is dead but DB says `RUNNING`.
- Cleans orphan OS resources (tmux sessions, Java processes) that have no matching DB record.

### FilesystemReconciliation

Defined in `runtime/filesystem-reconciliation.md`. A directory scanner that:

- Scans `data/servers/` and compares directories against DB records.
- Auto-imports new directories (detects server type, version, properties).
- Deletes stale DB records whose directories no longer exist.
- Runs at startup and on `POST /api/v1/servers/refresh`.

### RuntimeOwnershipManager

Defined in `runtime/ownership.md`. A resource-claiming layer that:

- Discovers all runtime resources: tmux sessions, Java processes, listening ports.
- Detects conflicts: `DUPLICATE_PID`, `DUPLICATE_PORT`, `ORPHAN_TMUX`, `ORPHAN_PROCESS`, `STALE_DB_RECORD`, `STALE_SUPERVISOR`, `PORT_NOT_RELEASED`, `MULTIPLE_SERVERS_ACTIVE`.
- `claim_localhost()` displaces competing servers, kills orphans, frees the port, and marks displaced servers as `CRASHED`.
- `validate_runtime()` checks a single server's full validation chain (DB → supervisor → tmux → PID → port → Minecraft process).
- `cleanup_orphans()` disposes unowned tmux sessions, Java processes, and stale DB records.

## Interaction Flow

1. A **Command** (e.g. `StartServerHandler`) calls `RuntimeOwnershipManager.claim_localhost()` to secure the host before starting.
2. The command calls `provider.start()` via the **ServerProvider** to launch the OS process.
3. A **RuntimeSupervisor** is created via `RuntimeSupervisor.start_for()` — it begins the startup verification and then enters the health-check loop.
4. If the supervisor detects a crash, it calls `server.crash()` on the aggregate and saves it, then cleans up OS resources.
5. **Reconciliation** is run independently (on startup, on a timer, or on demand). It scans all servers, detects mismatches, auto-repairs, and logs outcomes.
6. **Ownership discovery** is used before any start operation to ensure exclusive access to ports and resources.

## Module Structure

```
backend/app/modules/server/
├── application/
│   ├── supervisor.py              # RuntimeSupervisor
│   ├── runtime_reconciliation.py  # Reconciliation engine
│   ├── runtime_ownership.py       # RuntimeOwnershipManager
│   └── commands/
│       ├── start_server.py        # StartServerHandler
│       ├── stop_server.py         # StopServerHandler
│       └── restart_server.py      # RestartServerHandler
├── domain/
│   ├── aggregate.py               # Server aggregate, ServerStatus enum
│   └── diagnostics.py             # FailureCode, RuntimeDiagnostics
└── infrastructure/
    └── providers/                 # ServerProvider implementations
        ├── base.py                # Abstract provider, ProviderFactory
        ├── docker.py              # DockerProvider (sole active local runtime, P6)
        ├── remote.py              # SSHProvider (stub)
        ├── cloud.py               # CloudProvider (abstract + stub)
        └── circuit_breaker_wrapper.py
```

## References

- [Server Lifecycle](lifecycle.md)
- [Supervision](supervision.md)
- [Reconciliation](reconciliation.md)
- [Filesystem Reconciliation](filesystem-reconciliation.md)
- [Ownership](ownership.md)
- [Providers](providers.md)
- [Recovery Procedures](recovery.md)
