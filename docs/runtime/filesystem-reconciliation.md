# Filesystem Reconciliation

## Purpose

Keeps the database in sync with the actual files on disk. The filesystem is the
single **Source of Truth** — any server directory under `data/servers/` is real,
and any DB record without a matching directory is stale.

Defined in `app/modules/server/application/services/filesystem_reconciliation.py`.

## Architecture — Pipeline

The reconciliation is built as a **6-stage pipeline**. Each stage has a single
responsibility and produces structured output for the next stage.

```
Stage 1: scan_filesystem()
    → list[FsEntry]           # Just list directories — no I/O beyond ls

Stage 2: read_identity(entry)
    → IdentityResult          # Read/validate .mcsmanager/server.json

Stage 3: detect_minecraft(entry)
    → ScanOutcome             # scan_server_directory() + broken check

Stage 4: build_plan(entries, identities, scans, db_servers)
    → ReconciliationPlan      # Pure logic — no I/O, no side effects

Stage 5: execute_plan(plan, repo)
    → ReconciliationResult    # Transactional DB writes

Stage 6: write_pending_identities(pending)
    → None                    # Write identity files post-commit
```

## Identity Model

Each server directory carries its identity inside `.mcsmanager/server.json`:

```json
{
  "version": 1,
  "uid": "<32-hex-char-uuid>",
  "created_at": "2026-07-28T12:00:00Z",
  "manager": "mcsmanager",
  "schema": 1
}
```

The directory name is **not** the identity. The file is versioned so the schema
can evolve in the future. Dirs without an identity file are **unowned** —
reconciliation adopts them by assigning a new UID and writing the identity file
**after** the DB transaction commits.

## Identity States

| State | Meaning |
|-------|---------|
| `valid` | File exists, JSON valid, has 32-char UID |
| `invalid` | File exists but corrupted / wrong format / bad UID |
| `missing` | No `.mcsmanager/server.json` found |

Invalid identities are reported in a separate `invalid_identity` result category
and **not** imported automatically — they require manual inspection.

## Broken Servers

A server is considered **broken** when:
- No `.jar` file found in the directory
- No `server.properties` found (or file is empty)

Broken servers are **still imported** with `status = broken`. They appear in
the UI and can be repaired (add the missing files, then run refresh). The
aggregate exposes `mark_broken()` and `mark_repaired()` methods — reconciliation
never mutates private fields directly.

## Two-Pass Deletion

DB servers without a matching FS directory are handled in two passes:

1. **First reconciliation**: `server.mark_missing()` sets `missing_since` timestamp
2. **Second reconciliation** (if still missing): record is deleted

This prevents accidental data loss from transient FS issues. Servers outside
`data/servers/` are skipped entirely.

## ReconciliationResult

| Field | Description |
|-------|-------------|
| `imported` | New servers auto-imported from disk |
| `updated` | Existing servers with changed status or deployment |
| `deleted` | DB records deleted (second-pass missing) |
| `missing` | Servers marked with `missing_since` (first-pass) |
| `broken` | Servers found to be broken (no jar / no properties) |
| `unchanged` | Perfect matches (FS ↔ DB in sync) |
| `ignored` | Non-Minecraft dirs without identity |
| `invalid_identity` | Dirs with corrupted/unreadable identity files |
| `errors` | Operations that failed |

## When It Runs

| Trigger | Where |
|---------|-------|
| Application startup | `main.py` lifespan |
| Manual refresh | `POST /api/v1/servers/refresh` (returns full report) |

## References

- [Runtime Overview](README.md) — where reconciliation fits in the runtime system.
- [Reconciliation](reconciliation.md) — runtime state reconciliation (processes, tmux).
- [Provisioning](../PROVISIONING.md) — how server directories are created and managed.
