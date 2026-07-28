# Filesystem Reconciliation

## Purpose

Keeps the database in sync with the actual files on disk. The filesystem is the
single **Source of Truth** — any server directory under `data/servers/` is real,
and any DB record without a matching directory is stale.

Defined in `app/modules/server/application/services/filesystem_reconciliation.py`.

## Identity Model

Each server directory carries its identity inside `.mcsmanager/server.json`:

```json
{"server_id": "<32-hex-char-uuid>"}
```

The directory name is **not** the identity. This allows folders to be renamed
without losing the link to the DB record. Dirs without an identity file are
**unowned** — reconciliation adopts them by writing a new identity and importing.

## Algorithm

```
Scan data/servers/ directories
       │
       ▼
For each dir:
  a. Read .mcsmanager/server.json → extract server_id (UID)
  b. Run scan_server_directory() → detect /minecraft? /broken?
       │
       ▼
Query DB for all known servers
       │
       ▼
Build reconciliation plan in memory
       │
       ├── FS dir has UID not in DB → Import (even if broken)
       ├── FS dir has UID in DB     → Update deployment info or Unchanged
       ├── FS dir unowned + minecraft→ Adopt (write identity) + Import
       ├── FS dir unowned + !minecraft→ Ignore
       ├── DB server, no FS dir
       │     ├── First pass  → Mark MISSING (status = missing)
       │     └── Second pass → Delete DB record (was already MISSING)
       └── DB server, matches FS   → Unchanged
       │
       ▼
Execute entire plan in a single session (all-or-nothing)
       │
       ▼
Return ReconciliationResult
```

## ReconciliationResult

The `reconcile()` function returns a full report:

| Field     | Description |
|-----------|-------------|
| imported  | New servers auto-imported from disk |
| updated   | Existing servers with changed deployment info |
| deleted   | DB records deleted (second-pass MISSING) |
| missing   | Servers marked as MISSING (first-pass) |
| broken    | Servers found to be broken (no jar / no properties) |
| unchanged | Perfect matches (FS ↔ DB in sync) |
| ignored   | Non-Minecraft dirs without identity |
| errors    | Operations that failed |

## Broken Servers

A server is considered **broken** when:
- No `.jar` file found in the directory
- No `server.properties` found (or file is empty)

Broken servers are **still imported** with `status = broken`. They appear in
the UI and can be repaired (add the missing files, then run refresh).

## Two-Pass Deletion

DB servers without a matching FS directory are handled in two passes:

1. **First reconciliation**: status → `missing` (record stays in DB)
2. **Second reconciliation** (if still `missing` + no dir): record is deleted

This prevents accidental data loss from transient FS issues.

## When It Runs

| Trigger | Where |
|---------|-------|
| Application startup | `main.py` lifespan (after other reconciliations) |
| Manual refresh | `POST /api/v1/servers/refresh` (returns full report) |

Startup + refresh cover all divergence cases (manual folder deletion, restore
from backup, disk corruption, etc.).

## Scenarios

### User deletes a server folder

```
data/servers/ (MyServer dir removed)

Pass 1: Mark DB record as MISSING
Pass 2: Delete DB record (if still missing)
```

### User copies a new server folder

```
data/servers/NewSMP  (unowned dir)

Reconciliation:
  .mcsmanager/server.json not found → adopt
  scan_server_directory → valid Minecraft server
  Write identity file → Import → Create DB record
```

### User renames a folder

```
OldServer → BestServer

Reconciliation:
  .mcsmanager/server.json still inside → identity unchanged
  Root path updated in deployment → record is Updated, not re-imported
```

### Incomplete server (missing jar)

```
data/servers/BrokenSrv/  (no server.jar)

Reconciliation:
  scan_server_directory succeeds (no jar = broken)
  Imported anyway with status = broken
  Listed in result.broken[] with reason "No server jar detected"
```

## Comparison with Runtime Reconciliation

| Aspect | Runtime Reconciliation | Filesystem Reconciliation |
|--------|----------------------|--------------------------|
| What it checks | OS processes, tmux sessions, PIDs, ports | Server directories on disk |
| Source of Truth | OS process state | Filesystem |
| Action | Fix runtime state (mark RUNNING/CRASHED) | Import/Update/Mark/Delete DB records |
| When | Startup + periodic | Startup + refresh |

## References

- [Runtime Overview](README.md) — where reconciliation fits in the runtime system.
- [Reconciliation](reconciliation.md) — runtime state reconciliation (processes, tmux).
- [Provisioning](../PROVISIONING.md) — how server directories are created and managed.
