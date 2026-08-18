# Fast Fixes — Parking List

**Status:** Not implemented — documentation only.
**Purpose:** Small behavioral fixes Mohamed has raised that are deferred. No
code was changed for any item in this document; each entry describes the
desired behavior so it can be picked up directly.
**Last updated:** 2026-08-19

---

## FF-1 — Server name: `server.properties` is the source of truth

**Problem**

The server manager stores the server display name in its own database
(`servers.name`), set at create/import time. If the name is changed directly in
the on-disk server file (`server.properties`), the manager keeps showing the
old DB name — the file and the manager disagree.

**Desired behavior**

- The on-disk `server.properties` (or the deployment's server file) **is the
  source of truth** for the server name.
- When the name in the server file is changed, the manager should reflect the
  change:
  - On read: resolve/derive the display name from the file when present (with
    the DB name as fallback for name-less/legacy servers).
  - On write: editing the server name in the manager should write back to the
    server file, not only the DB.
- Reconciliation/re-sync should pick the change up for both running and stopped
  servers (the file is read-only data; no process restart required).

**Scope notes**

- `server.properties` in the codebase is currently edited via the jar/config
  services (`backend/app/modules/server/application/services/jar_service.py`)
  and read by `filesystem_reconciliation.py` (`_build_ln`) — the name field is
  handled separately from those property-driven props.
- No decision made yet on whether this is a full sync (two-way) or read-only
  derivation; Mohamed to confirm when the fix is picked up.

**Status:** OPEN — not started.

---

## FF-2 — RCON: defer implementation, document intent only

**Problem**

RCON-related work was raised (multi-packet RCON / persistent RCON client
topic). Per Mohamed's instruction, **no implementation and no file changes**
are to be made at this time.

**Desired behavior / record**

- A persistent RCON client base already exists
  (`backend/app/modules/monitoring/infrastructure/rcon_client.py`,
  `AsyncRCONClient` + `PersistentRCONClient`).
- Multi-packet response support remains on the roadmap (see
  `CURRENT_STATE.json` → "Multi-packet RCON (Batch 8.1): DEFERRED").
- When picked up, this should be revisited against the TPS/console contract
  changes from SPEC-TPS-VALIDATION-001 and SPEC-CONSOLE-OVERVIEW-001.

**Status:** DEFERRED — no changes made.

---

## Past fast fix — already implemented (for reference)

### FULL backup tolerates a missing world directory

Resolved 2026-08-19 in `backend/app/services/backup_orchestrator.py`:
`FULL` no longer requires the base `world/` directory to exist, so
seed-regeneration servers (world deleted on disk, regenerated on next start)
can be backed up. Explicit `WORLD`/`NETHER`/`END`/`WORLDS` backups still fail
when that dimension is missing. Covered by
`backend/tests/infrastructure/test_backup_saga.py`.