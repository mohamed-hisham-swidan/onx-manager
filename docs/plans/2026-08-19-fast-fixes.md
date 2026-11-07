# Fast Fixes — Parking List

**Status:** Parking list — FF-1 RESOLVED (2026-08-19), FF-2 DEFERRED (no code changed for it), FF-3 RESOLVED (2026-08-20), FF-4 RESOLVED (2026-08-20), FF-5 RESOLVED (2026-08-20), FF-6 RESOLVED (2026-08-21).
**Purpose:** Small behavioral fixes Mohamed has raised. Each entry describes the
desired behavior so it can be picked up directly.
**Last updated:** 2026-08-21

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

**Status:** RESOLVED 2026-08-19.

**Implemented solution (Read, Write, and Reconciliation Sync):**

1. **Read path:**
   - Added `resolve_display_name(server)` in
     `backend/app/modules/server/application/read_models.py`. It reads the
     on-disk `server.properties` (via `ServerDeployment.properties_path()`),
     returns its `server-name=` value when present and non-empty, and falls back
     to the DB `server.name` otherwise (missing file / no deployment root /
     empty value).
   - Both `ServerReadModel.from_domain` and `ServerDetailReadModel.from_domain`
     now use `resolve_display_name`, so `GET /servers` and `GET /servers/{id}`
     reflect the file immediately — no process restart, works for running and
     stopped servers.
   - Unit tests in `backend/tests/application/test_server_queries.py`
     (`TestResolveDisplayName`).

2. **Write path:**
   - Added `Server.rename(new_name)` to domain aggregate in
     `backend/app/modules/server/domain/aggregate.py`.
   - Added `update_server_properties_key(dest_path, key, value)` in
     `backend/app/modules/server/application/services/jar_service.py` to
     atomically update/insert keys into `server.properties` while preserving
     comments and formatting.
   - Extended `UpdateServerConfigCommand` and handler in
     `backend/app/modules/server/application/commands/update_server_config.py`
     as well as `ServerUpdateRequest` in `schemas/server.py` and `routers/servers.py`
     to support `name` updates and synchronize `server-name=<name>` to the on-disk file.
   - Also updated `create_server.py` to write `server-name` upon server creation.
   - Added `name?: string;` to `ServerUpdateRequest` in frontend `types.ts`.
   - Unit and API tests in `backend/tests/domain/test_server_aggregate.py`,
     `backend/tests/application/test_server_commands.py`, and
     `backend/tests/api/test_api_endpoints.py`.

3. **Reconciliation sync:**
   - Updated `FilesystemReconciliationService` (`_deployment_needs_update` and
     `_handle_update_deployment`) in `backend/app/modules/server/application/services/filesystem_reconciliation.py`
     to detect server name drift between on-disk `server.properties` and the database,
     updating `server.rename(...)` and saving to the DB so `name_search` and DB reads
     stay consistent.
- Updated `scan_server_directory` in `import_service.py` to safely fallback
      to directory name when `server-name=` is empty.
   - Unit tests in `backend/tests/application/test_reconciliation.py` (`TestFilesystemReconciliationNameDrift`).

**Regression guard (2026-08-19, commit `5ec1841`):**

The initial reconciliation sync would rename any legacy/name-less server (no
`server-name=` in `server.properties`) to its folder basename on startup —
violating the "DB name as fallback for name-less/legacy servers" rule. Fixed by:

   - `scan_server_directory` now also returns `server_name_declared: bool`,
     true only when the on-disk file actually declares a non-empty `server-name`.
   - `_deployment_needs_update` / `_handle_update_deployment` only perform the
     name-drift rename when `server_name_declared` is true; otherwise the DB
     name is preserved unchanged.
   - `ScanResult` schema (`schemas/import_server.py`) and frontend
     `ScanResult` (`types.ts`) expose the new field.
   - Regression test
     `test_reconciliation_preserves_db_name_when_no_server_name_declared` in
     `backend/tests/application/test_reconciliation.py`.

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
- Multi-packet response support remains on the roadmap (Multi-packet RCON: DEFERRED).
- When picked up, this should be revisited against the TPS/console contract
  changes from SPEC-TPS-VALIDATION-001 and SPEC-CONSOLE-OVERVIEW-001.

**Status:** DEFERRED — no changes made.

---

## FF-3 — Create Server wizard: version list breaks after changing software

**Problem**

The Create Server wizard fetches versions for the selected software (e.g.
Fabric, Purpur). When the user goes Back and picks a different software, the
version step can stay stuck on "Loading versions..." forever or show stale
results — the newly-selected software's versions never appear.

**Root cause**

`frontend/src/server_manager/pages/CreateServerPage.tsx` stores fetched
versions in `versionsState` keyed by `{serverType, versions, error}`, and
derives `versionsLoading = versionsState.serverType !== data.serverType`.
The fetch `useEffect` had no cancellation guard: if a slow response from the
*previously* selected software resolves *after* the new software's response,
it overwrites `versionsState.serverType` back to the old type. The loading
derivation then evaluates `oldType !== newType === true` permanently, so the
UI renders "Loading versions..." indefinitely and the new software's versions
are never shown (out-of-order/stale-response race).

**Fix (2026-08-20)**

1. Added a `cancelled` flag to the versions `useEffect` whose cleanup runs on
   every dep change (`data.serverType`) and unmount, so stale responses are
   dropped instead of overwriting current state.
2. Selecting a software now also resets `minecraftVersion` to `""`, so a
   version chosen for the previous software can't carry over to a software
   that doesn't support it.

**Regression guard**

Added `shows the NEW software's versions even when a previous fetch resolves
late` in `frontend/src/server_manager/pages/CreateServerPage.test.tsx` —
it switches software while the first fetch is still pending, lets the second
fetch resolve, then resolves the stale first response late and asserts the UI
is NOT stuck on "Loading versions...".

**Status:** RESOLVED 2026-08-20 (frontend changes UNCOMMITTED).

---

## FF-4 — Paper server versions: "No versions available" due to PaperMC API sunset

**Problem**

In the Create Server wizard, picking **Paper** shows "No versions available."
(and Paper download/creation would fail). Fabric, Purpur, Vanilla, Spigot and
Bukkit list versions fine.

**Root cause**

The legacy PaperMC API base `https://api.papermc.io/v2` was **sunset on
2026-07-01** and now returns **HTTP 410 Gone**
(`{"ok":false,"error":"sunset",...}`). `fetch_paper_versions()` treats any
non-200 as empty (→ `[]` → "No versions available."), and `_resolve_paper_url()`
would fail against it too. PaperMC's current API is `https://fill.papermc.io/v3`.

**v2 → v3 contract changes**

| | v2 (sunset) | v3 (`fill.papermc.io`) |
|---|---|---|
| Projects/versions | `GET /v2/projects/paper` → `{"versions": ["1.21", ...]}` | `GET /v3/projects/paper` → `{"versions": {"1.21": ["1.21.11", ...], ...}}` (nested by major family, newest-first) |
| Builds | `GET /v2/projects/paper/versions/{v}/builds` → `{"builds": [...]}`, latest = last element | `GET /v3/projects/paper/versions/{v}/builds` → **JSON array**, newest-first, each `{id, channel, downloads: {"server:default": {url, name, size, checksums}}}` |
| Download URL | constructed `.../downloads/paper-{v}-{build}.jar` | provided directly in `downloads["server:default"]["url"]` (`fill-data.papermc.io/v1/objects/...`) |

**Fix (2026-08-20)**

`backend/app/modules/server/application/services/jar_service.py`:

1. `PAPER_PROJECT_URL = "https://fill.papermc.io/v3/projects/paper"` and
   `PAPER_BUILDS_URL = "https://fill.papermc.io/v3/projects/paper/versions/{version}/builds"`.
2. `fetch_paper_versions()` flattens the nested `versions` groups into a
   deduplicated newest-first list (order already newest-first in v3; no
   `[::-1]` needed).
3. `_resolve_paper_url()` reads the newest build via
   `downloads["server:default"]["url"]` (fallback: first download entry), no
   URL construction.
4. Tests updated to v3 shapes (array builds, nested versions group), incl.
   newest-first order assertion.
5. `docs/architecture/PROVISIONING.md` table updated to
   `fill.papermc.io/v3`.

**Related ordering fix (same batch):**

`fetch_vanilla_versions()` and `fetch_fabric_versions()` dropped their
`[::-1]` reversal. The raw Vanilla/Piston manifest and Fabric meta lists are
already newest-first, so the reversal was making Vanilla and Fabric show
**oldest-first** (1.0 / 1.14 at the top) while Paper/Purpur showed
newest-first — inconsistent UX. All providers now list newest-first;
`test_vanilla_versions` / `test_fabric_versions` assert the order.

**Verification**

Live check against the real API: `fetch_paper_versions()` returned 66
versions (`26.2`, `26.2-rc-2`, `26.1.2`, ...) and
`_resolve_paper_url("26.2")` resolved to a real
`fill-data.papermc.io/v1/objects/<sha256>/paper-26.2-112.jar` URL.
`backend/tests/application/test_jar_service.py`: **30 passed**. No new ruff
violations. Backend `/health` returned
`{"status":"ok","version":"4.0.0","database":"connected"}`.

**Status:** RESOLVED 2026-08-20 (backend changes UNCOMMITTED).

---

## FF-5 — Forge: populate the Create wizard version list

**Problem**

Forge showed "No versions available." in the Create Server wizard —
`fetch_forge_versions()` hardcoded `return []`.

**Fix (2026-08-20)**

Implemented `fetch_forge_versions()` against Forge's official Maven metadata
(`https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml`):

- Parses the `<version>` entries (`<mc>-<build>`, e.g. `1.21.1-52.0.30`).
- Returns the **unique Minecraft versions, newest-first** (sorted via
  `MinecraftVersion`), matching the plain-MC-version model the rest of the
  wizard/backend uses (`minecraft_version` stores e.g. `1.21.1`).
- Live verification: 76 MC versions returned (26.2 → … → 1.16.5 → …).
- Tests added: unique-MC newest-first ordering + HTTP-error → empty.
  `backend/tests/application/test_jar_service.py`: 32 passed.

**Scope decision (Mohamed, updated 2026-08-20)**

The version list (above) ships with FF-5. Auto-install is **NOT** a staged
"smaller" plan — Mohamed confirmed building the **real Forge auto-install** as
an immediately-next feature. It is now **DONE** (see below).

**Forge auto-install — SPEC-FORGE-PROVISIONING-001 (COMPLETED 2026-08-20)**

Modern Forge (≥ 1.17) does not ship a runnable `server.jar` — its installer
must run (`--installServer`, downloads Mojang jars, can take minutes) and the
resulting `run.sh` + `libraries/…` layout does not fit the `java -jar
server.jar` launch model. Implemented as an asynchronous provisioning flow:

- **Status:** new `ServerStatus.PROVISIONING` with
  `CREATED → PROVISIONING → {CREATED/STARTING/BROKEN}` transitions
  (`aggregate.py`); `begin/finish/fail_provisioning()` domain methods.
- **Create flow:** `CreateServerHandler` commits the row in `PROVISIONING`
  then spawns `ForgeProvisioner` as an `asyncio.create_task` (own DB sessions).
- **Resolution:** `resolve_forge_build(mc)` picks the highest **numeric-tuple**
  build from `maven-metadata.xml` (never lexical — `58.0.10` > `58.0.2`);
  raw full version strings preserved (e.g. `1.9-12.16.1.1938-1.9.0`).
- **Legacy (< 1.17):** `download_server_jar` becomes version-aware and
  downloads `forge-{v}-universal.jar` (the plain `forge-{v}.jar` artifact 404s;
  `-universal.jar` live-verified 200).
- **Installer:** `InstallerRunner` port (`domain/installer.py`) +
  `SubprocessInstallerRunner` (`infrastructure/installer.py`);
  `ForgeProvisioner` (disk guard ≥ 4096 MB, `download_installer_jar`,
  `java -jar forge-installer.jar --installServer` (600 s), verifies `run.sh`,
  writes `user_jvm_args.txt`, persists
  `LaunchConfiguration(start_command="bash run.sh")`, `finish_provisioning()`).
- **Integrity:** `_check_jar` accepts the `run.sh` + `libraries/` layout
  (runtime jar lives deep inside `libraries/`, top-level jar check alone
  would wrongly block startup).
- **Reconciliation:** stale `PROVISIONING` after a restart → `BROKEN` +
  directory deletion.
- **Frontend:** `provisioning` status ("Installing" badge), Start disabled.
- **Typed errors:** `ForgeInstallError` / `ForgeInstallTimeoutError` /
  `ForgeInstallFailedError` / `ForgeInsufficientDiskError`.
- Tests: aggregate transitions, forge build resolution, provisioner
  success/fail/timeout/disk, integrity layout + full-suite pass.

**Status:** RESOLVED 2026-08-20 (backend + frontend changes UNCOMMITTED).

**Hard-review bugfix batch (2026-08-20):** an adversarial re-review of the
whole feature found and fixed 6 real defects:

1. **`download_server_jar` re-downloaded every JAR 3×** on success — the
   retry loop lacked `else: break` (the fix had only landed in
   `download_installer_jar`). Fixed; regression test asserts `_do_download`
   is called exactly once.
2. **Forge metadata now also carries Forge's own unified artifact revisions**
   (`26.2-65.x`) that were surfaced as fake "Minecraft" versions in the
   Create-wizard list and could tag a created server as MC 26.2.
   `fetch_forge_versions` + `resolve_forge_build` filter to real MC versions
   (major `== 1`).
3. **`forge-installer.jar` was never removed after a successful install**, so
   the integrity check reported a stray top-level jar warning forever. It is
   now deleted once `run.sh` is verified.
4. **Installer timeout only killed the `sh` shell**, leaving the `java`
   child alive and holding the pipe FDs — the post-kill `communicate()` could
   hang indefinitely. Runner now uses `start_new_session=True`, kills the
   whole process group (`os.killpg`), and bounds the drain to 10 s.
5. **The background install task had no strong reference** and could be
   garbage-collected mid-install. `provision_forge_server` now registers the
   task in a module-level set with a done-callback that discards it and
   retrieves exceptions.
6. **Frontend had no `broken` status** while `fail_provisioning` lands on
   `BROKEN` — added label/color/icon/order + filter.

Verified after fixes: backend full suite **1981 passed / 2 skipped**, frontend
**68 files / 560 tests passed**, ruff clean on all new/changed code (jar_service
lint error count dropped 27 → 26 vs HEAD, zero new), zero new tsc errors.

**Status:** RESOLVED 2026-08-20 (backend + frontend changes UNCOMMITTED).

## Investigation — leaked DB connection warning (SAWarning "non-checked-in connection")

**Reported:** 2026-08-20, live backend log, between `GET /api/v1/software` and
`GET /api/v1/software/forge/versions`.

**Investigation result — REOPENED and REPRODUCED-AND-FIXED 2026-08-21.** The
earlier "clean 0-warnings" conclusion was **wrong**: that repro hit HTTP
403/429 (rate cap 60/min) and never exercised the gated handlers. A decisive
repro (fresh alembic DB, `repro-0001` running row, RS256 owner JWT,
`MCS_RATE_LIMIT_PER_MINUTE=100000`, polling `/servers/{id}`, `/console`,
`/runtime`, `/monitoring/metrics` every 0.3s on uvicorn `:8087`) produced
**194 SAWarnings in 40s**. Per-endpoint bisect: `/runtime` → **+68**, `/monitoring/metrics`
→ +2, `/servers/{id}` and `/console` → +0. The dashboard's runtime-diagnostics
polling is the flood source.

**Root cause:** `GetServerRuntimeDiagnosticsHandler` (`get_runtime_diagnostics.py`)
opened a session with `async with database.session_factory() as session` for
`repo.get(sid)`, then — **after the context manager had closed that session** —
kept using the same `SQLServerRepository` through `RuntimeOwnershipManager.discover_all()`
(`repo.list()`) and `validate_runtime()` (`repo.get(sid)`). In SQLAlchemy 2.0.x,
executing on a **closed** `AsyncSession` does **not** raise: it silently
re-opens the session and **checks out a fresh connection**, and because the
handler never calls `close()` on it again, that connection is stranded until
GC — producing the "GC trying to clean up non-checked-in connection" SAWarning
flood. Confirmed with an instrumented probe: 20 handler calls leaked ~1
connection each (pool exhausted → `TimeoutError`), and the same micro-test
showed `close()` releasing the first connection while a later `discover_all()`
checked out a second one with no further `close()`. `app/main.py` and every
other `RuntimeOwnershipManager` caller use it **inside** their `async with`
block and are not affected; `get_metrics.py` / `get_server_console.py` are
clean.

**Fix (applied):** the ownership phase now gets its **own** session/repo inside
a fresh `async with database.session_factory() as diag_session:`, never
re-using a repo bound to an already-closed session. This is the general rule
going forward: a repo/session pair must not be used after `async with` exit.

**Verification after fix:**
- Instrumented probe: 20 handler calls → **0 SAWarnings**, checkouts==checkins (40/40).
- Live re-soak on `:8087`: **120 `/runtime` polls → 0 SAWarnings**.
- Production `:8000` (uvicorn `--reload`) auto-reloaded the patched module;
  **103 dashboard requests since the reload → 0 new SAWarnings** (254 had
  accumulated before).

**Status:** RESOLVED 2026-08-21 (patch in `get_runtime_diagnostics.py`,
UNCOMMITTED). Unrelated to SPEC-FORGE-PROVISIONING-001.

## FF-6 — Forge modern-vs-legacy chooser in the Create wizard

**Problem**

When choosing Forge in the Create wizard (`CreateServerPage` `VersionStep`),
the version list is a flat mix of modern (≥ 1.17, installer flow) and legacy
(< 1.17, universal-jar flow) Minecraft versions. There is no indication of
which install flow the choice produces.

**Implemented solution (2026-08-21):**

- New helper `frontend/src/server_manager/utils/forgeEdition.ts`:
  - `isModernForgeVersion(v)` — numeric `major > 1 || (major === 1 && minor ≥ 17)`,
    unparseable input defaults to modern (mirrors backend `forge_requires_installer`).
  - `forgeEditionForVersion(v)` → `"modern" | "legacy"`.
  - `FORGE_EDITION_LABELS` — segmented-control labels + flow descriptions.
- `VersionStep` now accepts `serverType`; when `serverType === "forge"` it
  renders a **Modern Forge (1.17+)** / **Legacy Forge (< 1.17)** toggle that
  filters the version grid to the chosen edition (defaults to modern, or the
  selected version's tier when returning to the step) and shows the flow note
  (installer → configures `run.sh`; legacy → downloads `-universal.jar`).
- Review step adds a **Forge Edition** row derived from `data.minecraftVersion`.
- No backend/API change — the server still derives the flow from
  `minecraft_version`; the backend integration test bluebox (30+ tests) is
  unaffected. Given the backend was already green from SPEC-FORGE-PROVISIONING-001,
  no backend test was needed for this frontend-only change.

**Tests:** `forgeEdition.test.ts` (6 tests) + `CreateServerPage.test.tsx`
(4 new chooser tests: toggle renders/default, edition filtering, flow
description, Review-step Forge Edition row).

**Verification:** frontend full suite **69 files / 569 tests passed**, eslint
0 errors on all touched files, zero new `tsc` errors (the 4 pre-existing
tsc-error files unchanged). Backend untouched by this change.

**Status:** RESOLVED 2026-08-21 (frontend changes UNCOMMITTED).

## Past fast fix — already implemented (for reference)

### FULL backup tolerates a missing world directory

Resolved 2026-08-19 in `backend/app/services/backup_orchestrator.py`:
`FULL` no longer requires the base `world/` directory to exist, so
seed-regeneration servers (world deleted on disk, regenerated on next start)
can be backed up. Explicit `WORLD`/`NETHER`/`END`/`WORLDS` backups still fail
when that dimension is missing. Covered by
`backend/tests/infrastructure/test_backup_saga.py`.