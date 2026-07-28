# Filesystem Reconciliation

## Purpose

Keeps the database in sync with the actual files on disk by treating the
filesystem as the single **Source of Truth**.

Any server directory under `data/servers/` that exists on disk is considered
real. Any DB record whose directory no longer exists on disk is considered
stale.

Defined in `app/modules/server/application/services/filesystem_reconciliation.py`.

## How It Works

```
Scan data/servers/ directories
       │
       ▼
Build set of directory server IDs
       │
       ▼
Read all DB server records
       │
       ▼
Compare
       │
       ├── Folder exists, no DB record → Auto-import
       │     (detect type, version, properties from files)
       │
       └── DB record exists, no folder → Delete DB record
```

### Auto-Import

When a new directory appears in `data/servers/`:

1. `scan_server_directory()` reads `server.properties`, detects server type from
   jar name, extracts version, and discovers worlds/plugins/mods.
2. A new `Server` aggregate is created with the detected values and saved to the
   database.

### Stale Record Cleanup

When a DB server has no matching directory on disk:

1. The directory name is matched by extracting the UUID prefix (32-char hex or
   the last 8 chars of `{slug}-{short_uuid}` format).
2. If no directory matches the server ID, the DB record is deleted.

## When It Runs

| Trigger | Where |
|---------|-------|
| Application startup | `main.py` lifespan (after other reconciliations) |
| Manual refresh | `POST /api/v1/servers/refresh` |

Not run after every create/delete/import because those handlers already update
both filesystem and DB in the same transaction. The reconciliation catches
cases where they diverge (user manually deletes a folder, restore from backup,
disk corruption, etc.).

## Scenarios

### User deletes a server folder

```
data/servers/MyServer-a1b2c3d4  (deleted by user)

Reconciliation runs:
  Folder missing → Delete DB record ✓
```

### User copies a new server folder

```
data/servers/NewSMP  (copied by user)

Reconciliation runs:
  Folder discovered → Auto-import → Create DB record ✓
```

### User renames a folder

```
OldServer → BestServer

Reconciliation runs:
  Old folder missing → Delete old DB record
  New folder discovered → Auto-import new one ✓
```

## Comparison with Runtime Reconciliation

| Aspect | Runtime Reconciliation | Filesystem Reconciliation |
|--------|----------------------|--------------------------|
| What it checks | OS processes, tmux sessions, PIDs, ports | Server directories on disk |
| Source of Truth | OS process state | Filesystem |
| Action | Fix runtime state (mark RUNNING/CRASHED) | Fix DB records (import/delete) |
| When | Startup + periodic | Startup + refresh |
| Defined in | `runtime_reconciliation.py` | `filesystem_reconciliation.py` |

## References

- [Runtime Overview](README.md) — where reconciliation fits in the runtime system.
- [Reconciliation](reconciliation.md) — runtime state reconciliation (processes, tmux).
- [Provisioning](../PROVISIONING.md) — how server directories are created and managed.
