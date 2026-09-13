# Filesystem Reconciliation

## Purpose

Keeps the database in sync with the actual files on disk. The filesystem is the
single **Source of Truth** — any server directory under `data/servers/` is real,
and any DB record without a matching directory is stale.

Defined in `app/modules/server/application/services/filesystem_reconciliation.py`.

The service is implemented as a class: `FilesystemReconciliationService(repo, fs)`.

## Architecture — Pipeline

The reconciliation is built as a **6-stage pipeline** with strict separation of
concerns. Stages 1–4 are read-only, Stage 5 writes to DB, Stage 6 writes to disk.

```
FilesystemScanner           Stage 1 — list directories only
    ↓
IdentityReader              Stage 2 — read/validate .onx-manager/server.json
    ↓                               (legacy .mcsmanager/ fallback, migrate-on-read)
MinecraftDetector           Stage 3 — scan_server_directory() with ScanCategory
    ↓                            (MINECRAFT_VALID / MINECRAFT_BROKEN /
    ↓                             NOT_MINECRAFT / SCAN_FAILED)
    ↓
ReconciliationPlanner       Stage 4 — matches root_path against DB records;
    ↓                               deterministic scoring for HEAL vs ADOPT;
    ↓                               builds Plan (no I/O)
    ↓
TransactionExecutor         Stage 5 — executes HEAL_IDENTITY, ADOPT, UPDATE,
                                     DELETE (calls provider.destroy first)
    ↓
session.commit()            Called by the caller, commits all DB changes
```

Identity files are written **during** execution (before each DB write), not
after commit. If identity writing fails, the exception prevents the DB write
and the session rolls back. If the DB write fails, the identity file already
exists and is idempotent — the next reconciliation uses the same UID.

## Identity Model

Every server directory under `data/servers/` carries an authoritative identity
file at `.onx-manager/server.json` (written via `identity_writer.py`):

```json
{
  "schema_version": 1,
  "server_id": "<uuid>",
  "provider": "docker"
}
```

Key properties:
- The directory name is **not** the identity — renaming folders is safe
- Stamped authoritatively at server creation and archive import time
- Legacy fallback: if `.onx-manager/server.json` is missing, checks `.mcsmanager/server.json` and migrates on read
- All new writes target `.onx-manager/server.json` exclusively

## Identity States

| State | Meaning |
|-------|---------|
| `VALID` | File exists, JSON valid, has valid server_id UUID and provider |
| `INVALID` | File exists but corrupted / wrong format / bad UUID |
| `MISSING` | No `.onx-manager/server.json` (or `.mcsmanager/server.json`) found |

## Un-Identified Resolution: Adopt vs. Heal

When a directory has `MISSING` identity:

1. The service searches database records for a matching normalized `root_path`.
2. If candidates exist, deterministic scoring selects the best record:
   - `+100` points: Active server (`missing_since is None`)
   - `+50` points: In-flight or live status (`RUNNING`, `STARTING`, `CREATED`)
   - `+25` points: Matching `DOCKER` runtime provider
   - Tie-breaker: Most recent `updated_at` timestamp
3. **If candidate found** $\rightarrow$ `ActionType.HEAL_IDENTITY`:
   - Authoritatively writes `.onx-manager/server.json` with the existing server's UUID and provider.
   - Clears `missing_since` and restores broken status without creating duplicate DB rows or deleting records.
4. **If no candidate found** $\rightarrow$ `ActionType.ADOPT`:
   - Treats directory as a new installation and imports with a newly generated UUID.

## Scan Categories

Each directory falls into one of four scan categories:

| Category | Meaning |
|----------|---------|
| `MINECRAFT_VALID` | Has jar + properties — valid server |
| `MINECRAFT_BROKEN` | Has Minecraft files but missing jar or properties |
| `NOT_MINECRAFT` | No Minecraft files found |
| `SCAN_FAILED` | Filesystem error (unreadable dir, permission denied) |

`SCAN_FAILED` entries are never imported — they're reported and skipped.
`NOT_MINECRAFT` entries are ignored (but still get a UID).
`MINECRAFT_BROKEN` servers are imported with `status = BROKEN`.

Detection reuses `scan_server_directory()` from `import_service.py`.

## Self-Healing Identity

When an identity file is corrupted (bad JSON, wrong schema version, invalid
UID), reconciliation doesn't just report it — it repairs automatically:

1. A new UID is generated
2. The identity file is overwritten
3. The directory is re-scanned
4. If it's a Minecraft server → imported (even if broken)
5. If not a Minecraft server → ignored (with identity file)

This ensures every directory eventually has a valid identity file.

## Two-Pass Deletion

DB servers without a matching FS directory are handled in two passes:

1. **First reconciliation**: `server.mark_missing()` sets `missing_since` timestamp
2. **Second reconciliation** (if still missing): record is deleted

This prevents accidental data loss from transient FS issues (moves, renames).
Servers deployed outside `data/servers/` are skipped entirely.

## Dry Run

`POST /api/v1/servers/refresh?dry_run=true` runs stages 1–4 and returns a
preview of what would happen without touching the DB or filesystem. The
response has the same structure as a real run.

## ReconciliationResult

| Field | Description |
|-------|-------------|
| `imported` | New servers auto-imported from disk |
| `updated` | Existing servers with changed status or deployment |
| `deleted` | DB records deleted (second-pass missing) |
| `missing` | Servers marked with `missing_since` (first-pass) |
| `broken` | Servers found to be broken (no jar / no properties) |
| `unchanged` | Perfect matches (FS ↔ DB in sync) |
| `ignored` | Non-Minecraft directories (still get UID) |
| `invalid_identity` | Dirs with corrupted/unreadable identity files |
| `errors` | Operations that failed |
| `identity_written` | Identity files written during execution (write-ahead) |
| `total_dirs_found` | Number of directories scanned |
| `total_minecraft_dirs` | Number of directories that are valid Minecraft servers |
| `started_at` | ISO 8601 timestamp when reconciliation started |
| `finished_at` | ISO 8601 timestamp when reconciliation finished |
| `duration_ms` | Total elapsed time in milliseconds |

Each list field also has a `total_*` property (e.g. `total_imported`).

## Transaction Model

Identity files are written **during** execution (Stage 5), **before** each DB
write (write-ahead). This ensures:

- If identity file write fails → exception → session rolls back → clean state
- If DB save fails → identity file exists but is idempotent (next reconciliation uses same UID)
- The caller only needs to commit the session after `reconcile()` returns

```
service.reconcile()
  Stage 1–4: read-only
  Stage 5:
    for HEAL_IDENTITY: write .onx-manager/server.json with existing server UUID/provider, clear missing_since
    for IMPORT/ADOPT: write .onx-manager/server.json → save server to DB
    for IGNORE: write .onx-manager/server.json (no DB change)
    for UPDATE/MISSING: DB writes only
    for DELETE: invoke provider.destroy() (name, labels, volume mounts) → delete DB row & directory
    ↓
session.commit()   # Caller commits the DB transaction
```

There is no separate post-commit identity writing step. Identity files are
always written before their corresponding DB operations.

## When It Runs

| Trigger | Where |
|---------|-------|
| Application startup | `main.py` lifespan (after runtime reconciliation) |
| Manual refresh | `POST /api/v1/servers/refresh` (returns full report) |
| Dry run preview | `POST /api/v1/servers/refresh?dry_run=true` |

## Class API

```python
class FilesystemReconciliationService:
    def __init__(
        self,
        repo: ServerRepository,
        fs: FileSystem = local_fs,
        provider_registry: ProviderRegistry | None = None,
    ):
        ...

    async def reconcile(self, dry_run: bool = False) -> ReconciliationResult:
        """Runs all stages. Heals identity in-place for existing servers or adopts new ones."""
```

## References

- [Runtime Overview](README.md) — where reconciliation fits in the runtime system.
- [Reconciliation](reconciliation.md) — runtime state reconciliation (processes, tmux).
- [Provisioning](../architecture/PROVISIONING.md) — how server directories are created and managed.
