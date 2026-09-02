# SPEC-FORGE-PROVISIONING-001 — Forge Auto-Install (ONX Manager)

**Status:** Approved · **Date:** 2026-08-20 · **Implementation:** DONE

**Scope:** Forge servers created through `POST /api/v1/servers` are installed
automatically. Legacy Forge (< 1.17) keeps downloading a plain jar
(async-neutral). Modern Forge (≥ 1.17) runs the official installer
(`--installServer`) in a background task. Related UI receives the new
`PROVISIONING` status. Frontend "versions list only" for Forge FF-5 is
unchanged (ships with the version list). Create-wizard Forge chooser
(modern ≥ 1.17 vs legacy < 1.17) added 2026-08-21 (§7).

---

## 1. Goals

1. Zero-manual-install for Forge ≥ 1.17: a server row is created immediately
   (request returns fast), then the installer job completes the server
   directory.
2. Deterministic Forge build resolution from Maven metadata (highest numeric
   build per Minecraft version).
3. Atomic failure: any install failure deletes the half-installed directory and
   marks the server `BROKEN` with a typed error — the DB row never leaks a
   half-installed sword.
4. Startability: once installed, the server routes to the patented
   `run.sh` launch command and passes the integrity/startup guards.

## 2. Mechanism (user-confirmed)

- Data source: `https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml`
  (already used by the versions endpoint; no new external endpoint needed).
  Build resolution compares **numeric tuples** (`58.0.10` > `58.0.2`), never
  lexical. Versions are kept as raw full strings (anomalies like
  `1.9-12.16.1.1938-1.9.0` survive).
- Version split: `forge_requires_installer(version)` == MC ≥ 1.17.
- Artifact URLs (live-verified 404/200 matrix):
  - legacy: `…/forge-{full}-universal.jar` → **200** (plain `forge-{full}.jar` → **404**)
  - modern: `…/forge-{full}-installer.jar` → **200** (`forge-{full}-server.jar` → **404**)
- `SERVER_TYPES_REQUIRING_MANUAL_INSTALL` stays type-keyed; the forge branch in
  `download_server_jar` is version-aware (legacy falls through to the resolver,
  modern no-ops pending the installer task).
- Installer step: `java -jar forge-installer.jar --installServer` in the server
  directory (async, not via tmux), 600 s timeout, exit code ≠ 0 → failure.
- Success contract: installer must produce a top-level `run.sh`; the provisioner
  writes `user_jvm_args.txt` (memory flags) and persists
  `LaunchConfiguration(startup_command="bash run.sh")`.

## 3. Status lifecycle

```
CREATED → PROVISIONING → {CREATED (success), STARTING (user override), BROKEN (failure)}
```

- New enum value `ServerStatus.PROVISIONING = "provisioning"`, transitions
  enforced by the existing `_SERVER_TRANSITIONS` / `_transition_to` guard.
- `begin_provisioning()` / `finish_provisioning()` (→ CREATED) /
  `fail_provisioning()` (→ BROKEN) domain methods.
- Reconciliation: backend restart during an install → stale `PROVISIONING` is
  marked `BROKEN` and its directory deleted (startup reconciliation path).

## 4. Architecture (hexagonal)

- Port: `InstallerRunner.run(command, *, timeout, cwd) -> InstallerResult`
  (`app/modules/server/domain/installer.py`).
- Impl: `SubprocessInstallerRunner` (`asyncio.create_subprocess_shell`, capture,
  timeout kills + drains). Provider-agnostic; the port/impl boundary is the
  Phase 11 Docker switch point. **ForgeProvisioner never invokes tmux/shell
  itself** — only through the injected runner.
- `ForgeProvisioner` (application service):
  1. Disk guard ≥ 4096 MB free (`ForgeInsufficientDiskError`, `FORGE_INSUFFICIENT_DISK`).
  2. `resolve_forge_build(mc)` → full version or `VersionNotFoundError`.
  3. Download installer (same timeout/retry/validation pattern as server jars;
     `download_installer_jar`; retries = 2, backoff 1s/2s; ZIP magic + ≥ 1 MB).
  4. Run installer via port (600 s).
  5. Verify `run.sh`; write `user_jvm_args.txt`.
  6. Persist launch config + `finish_provisioning()` via a **fresh** UoW/session
     (never the create-request UoW). Domain events flow into the app EventBus.
- Trigger: `create_server.py` computes the forge-installer flag, sets
  `PROVISIONING`, commits the row, then spawns `asyncio.create_task(...)` with
  its own session lifecycle. The request returns before any install work.

## 5. Integrity & startup guards

- `_check_jar` (`app/modules/health/infrastructure/integrity.py`) now accepts the
  Forge ≥ 1.17 layout: top-level `run.sh` + `libraries/` → pass. (The runtime
  jar lives deep inside `libraries/`; a top-level-jar-only check would wrongly
  fail `check_startup_readiness`.)
- The launch command path (`bash run.sh`) is exercised as
  `effective_command()`; `nogui`/jvm-flag behaviour confirmed empirically on the
  first real install (documented known-limitation note, non-blocking).

## 6. Failure model (typed errors)

`runtime_exceptions.py`: `ForgeInstallError` base (code `FORGE_INSTALL_FAILED`,
operation `provision`), `ForgeInstallTimeoutError` (`FORGE_INSTALL_TIMEOUT`),
`ForgeInstallFailedError` (carries `exit_code`), `ForgeInsufficientDiskError`
(carries `free_mb`/`required_mb`). All failures → delete dir + `fail_provisioning()`.

## 7. Frontend

- `STATUS_MAP` gains `provisioning` ("Installing"), StatusOverviewCards order +
  icon/color, ServersPage filter + action-slot disable, DashboardServerList and
  ServerDetailPage Start-button disable while `PROVISIONING` (server icon).
- Create wizard (`CreateServerPage.tsx` `VersionStep`): when Software = Forge a
  **Modern (1.17+)** / **Legacy (< 1.17)** segmented toggle appears; it filters
  the version grid to the chosen edition and shows the flow description
  (installer vs `universal.jar`). Funnel logic lives in
  `frontend/src/server_manager/utils/forgeEdition.ts`
  (`isModernForgeVersion` / `forgeEditionForVersion`), mirroring backend
  `forge_requires_installer` (numeric compare, unparseable → modern, ≥ 1.17 →
  installer). Review step shows a "Forge Edition" row.
  The backend create API is unchanged — edition is derived from the chosen
  `minecraft_version` server-side. (2026-08-21)

## 8. Explicitly OUT of scope (documented only)

- No general background-job framework; the installer runs as a single
  `asyncio.create_task` (app has no Celery/queue).
- No JDK-version enforcement; "requires Java 17+" documented, not enforced.
- No `promotions_slim.json`; no auto-start after provisioning.
- Orphaned `java` subprocess if the process restarts mid-install is a known
  limitation (reconciled at next startup by stale-`PROVISIONING` cleanup).

## 9. Tests (all passing)

- Aggregate transitions: `PROVISIONING` edges + invalid-edge guards.
- `jar_service`: `_parse_forge_metadata` (incl. `1.9-12.16.1.1938-1.9.0`),
  `resolve_forge_build` numeric-tuple ordering, `forge_*_url`, version-aware
  legacy universal download, `_resolve_forge_url` + VersionNotFoundError.
- `ForgeProvisioner`: success (launch config + back to CREATED), non-zero exit,
  timeout, insufficient disk, missing `run.sh` → all BROKEN + dir cleanup;
  task-spawn helper.
- Integrity: `run.sh` + `libraries/` passes; no-jar/no-run.sh fails.
- Reconciliation covered by the shared suite (unchanged helpers).

## 10. Documentation

- `docs/architecture/PROVISIONING.md` (Forge section, lifecycle, layout,
  key source files) — updated.
- `docs/plans/2026-08-19-fast-fixes.md` — updated with this run's decisions.
- `.ai/CURRENT_STATE.json` — known_limitations + progress — updated.