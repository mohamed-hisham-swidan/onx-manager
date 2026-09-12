# Design Spec: Phase 4 — Community Feature Build (Feedback Pool)

**Document Status:** DRAFT FOR DESIGN REVIEW  
**Governance Classification:** Decision Level D2 (Major — 5 Community Features, Standalone Subsystem) / Lane B (Release Improvement)  
**Governing Authority:** `docs/governance/GOVERNANCE.md` §4–5, §15–16  
**Preceding Precedents:**  
- [`DECISION-2026-09-10-001`](../decisions/DECISION-2026-09-10-001.md) (Phase 5 Built & Closed Ahead of Phase 4)  
- [`DECISION-2026-09-12-001`](../decisions/DECISION-2026-09-12-001.md) (Redefine Phase 4 Feature 1 as Standalone Git/CI-CD-Inspired Versioning & Test System)  
**Target Delivery:** Phase 4 — Feature Build from Community Feedback Pool (`ROADMAP_v1.1.md`)  
**Author:** Antigravity (Design Agent)  
**Date:** 2026-09-12  

---

## Executive Summary & Architectural Posture

This Design Spec defines the complete implementation architecture for Phase 4 of ONX Manager. It is structured around four locked governance decisions established during RECON:

1. **Feature 1 Redefinition (DECISION-2026-09-12-001):** Feature 1 is redefined as a **standalone git/CI-CD-inspired versioning and isolated-testing subsystem** (branch/commit tracking, copy-on-write world snapshots, isolated test containers, multi-node groundwork). It is architecturally decoupled from the production `ServerProvider` hierarchy (`LocalLinuxProvider`, `LocalWindowsProvider`, `DockerProvider`), ensuring zero regressions to live production server lifecycles.
2. **Feature 2 Merge:** Feature 2 (Test Environment) is fully absorbed into Feature 1. Disposable test instances are realized exclusively through Feature 1's isolated test-container pipeline.
3. **Hard Storage Prerequisite:** The versioning and isolated-testing subsystem requires a copy-on-write (COW) capable filesystem (**Btrfs or ZFS**) on the host path hosting server data. There is no degraded ext4/NTFS fallback for world branching. A preflight capability check enforces this requirement: if Btrfs/ZFS is absent, versioning features are cleanly disabled with an actionable alert, leaving all other platform features fully operational. **Hardlinking world data is strictly prohibited** due to silent cross-instance write-through corruption risks.
4. **Proven Primitives Reuse:** Core filesystem swaps reuse the proven patterns from `restore_service.py` (`_atomic_replace_dir` with same-filesystem sibling staging preventing `EXDEV`, and `_safe_extract_tar` guarding against CVE-2007-4559).

---

## Feature 1 — Git-Inspired Versioning & Isolated-Testing System (incorporating former Feature 2)

### 1. Goal
Provide Minecraft server administrators with a git/CI-CD-inspired version control and isolated testing system:
- Track server configuration and mod setups as immutable, branchable commit manifests.
- Instantaneous, zero-cost copy-on-write (COW) snapshots for mutable world and database state on Btrfs/ZFS.
- Spin up isolated ephemeral Docker test containers to trial updates (server software, mods, configuration) before promoting to production.
- Automated boot verification and optional play-testing window.
- Atomic promotion to production or one-click rollback with zero data loss.
- Lay schema and architectural groundwork for future multi-node execution targets.
- Realize the community update-protection use cases: rollback, proceed, disable broken mods, and structured failure reporting.

### 2. Current Behavior
- Servers are monolithic single directories on disk. Any update directly mutates live files.
- The only rollback mechanism is shutting down the server and extracting a full tar backup via `RestoreBackupCommand`.
- Zero branching, commit history, or isolated trial runs exist.

### 3. Proposed Change

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│                           ONX Manager Control Plane                              │
│                                                                                  │
│   ┌────────────────────────────────┐         ┌───────────────────────────────┐   │
│   │   Production Server (Live)     │         │   Isolated Test Container     │   │
│   │   Provider: Host or Docker     │         │   Target: Ephemeral Docker    │   │
│   │   Dir: /data/servers/srv-1/    │         │   Dir: /data/.tests/test-8f2/ │   │
│   └────────────────────────────────┘         └───────────────────────────────┘   │
│                   │                                          │                   │
│                   ▼                                          ▼                   │
│       ┌───────────────────────┐                  ┌───────────────────────┐       │
│       │  Production World     │                  │  COW Reflink Clone    │       │
│       │  (Btrfs/ZFS Subvol)   │──[reflink clone]►│  (Instant, O(1), COW) │       │
│       └───────────────────────┘                  └───────────────────────┘       │
│                   ▲                                          ▲                   │
│                   │                                          │                   │
│                   └──────────────────┬───────────────────────┘                   │
│                                      │                                           │
│                       ┌─────────────────────────────┐                            │
│                       │   Versioning Subsystem      │                            │
│                       │   - Commit Manifests (JSON) │                            │
│                       │   - Branch Pointers         │                            │
│                       │   - Test Supervisor         │                            │
│                       └─────────────────────────────┘                            │
└──────────────────────────────────────────────────────────────────────────────────┘
```

#### 3.1 Subsystem Architecture & Decoupling
The versioning system lives in an isolated module: `backend/app/modules/versioning/`. It does not wrap, inherit, or modify `ServerProvider`, `LocalLinuxProvider`, `LocalWindowsProvider`, or production `DockerProvider`. Production servers continue to boot and operate via their existing supervisor pipelines.

#### 3.2 Decoupled Versioning Model
- **Config & Mods Manifest (Commit):** All non-world state (`server.properties`, `bukkit.yml`, `spigot.yml`, `paper-global.yml`, `config/**`, and mod references: filename, hash, source) is captured as a serialized JSON manifest stored in the database. Each state change creates a `ServerCommit` record.
- **World & State Data (Snapshot):** World folders (`world`, `world_nether`, `world_the_end`) and internal databases (SQLite/H2) are not stored in git or database blobs. Instead, they are referenced via a `ServerWorldSnapshot` pointing to a local filesystem snapshot path.
- **Branch Concept:** A `ServerBranch` (e.g. `main`, `update-1.21-trial`) points to a `head_commit_id`.

#### 3.3 Storage Requirement & Preflight Capability Check
- **Prerequisite:** Host directory for server data must reside on a Btrfs or ZFS filesystem supporting `reflink` block cloning (`FICLONE` / `cp --reflink=always`).
- **Capability Probe (`StorageCapabilityProbe`):** At startup and before any versioning operation, the probe creates a 4KB temporary file in `.onx/probe/` and executes a reflink clone. If the clone succeeds, `supports_reflink` is marked `True`. If `OSError: [Errno 95] Operation not supported` or `EXDEV` occurs, it is marked `False`.
- **Actionable Failure Mode:** If `supports_reflink` is `False`, the versioning endpoints return HTTP 412 Precondition Failed with error code `STORAGE_COW_UNAVAILABLE`:
  > *"Versioning and isolated testing requires a Btrfs or ZFS filesystem supporting copy-on-write on the server data path. Your server data directory (/data/servers) is on ext4/NTFS. Standard server management remains fully available."*
- **Strict Hardlink Prohibition:** Hardlinks (`os.link`) are strictly forbidden for world files. Because writes to hardlinked files mutate the underlying inode directly, running a test server on hardlinked `.mca` region files would silently corrupt the live production world.

#### 3.4 Isolated Test-Container Execution Pipeline
When a change or update is trialed:
1. **Materialize Test Directory:** The system creates a staged directory: `.onx/tests/<test_id>/` on the same filesystem.
2. **COW World Clone:** The parent commit's world directories are cloned instantaneously via `cp --reflink=always -r <live_world> <test_world>`. Takes < 100ms regardless of world size (zero disk usage until blocks change).
3. **Write Manifest:** Target configs and mod `.jar` files are written into the test directory.
4. **Launch Test Container:** `IsolatedTestContainerRunner` launches a dedicated container:
   - Image: standard OpenJDK image matching server Java version.
   - Volumes: binds `.onx/tests/<test_id>` to `/data`.
   - Network: bridge mode. For automated tests, ports remain unmapped. For play-tests, port 25565 inside the container is mapped to an ephemeral host port (e.g. `25600 + offset`).
   - Sibling container DooD translation: routes paths through `resolve_host_mount_path()` if ONX runs inside Docker.

#### 3.5 Boot Verification & Play-Testing (Resolving RECON's Open Unknown)
**Decision: Two-Phase Verification Workflow:**
- **Phase 1 — Automated Boot & Health Probe (Default, 90s timeout):**
  - Container boots. The supervisor observes container stdout/stderr and monitors for:
    - *Success:* Regex match for server readiness: `Done \([0-9\.]+s\)! For help, type "help"` or successful RCON connection.
    - *Failure:* Process exit before readiness, JVM crash exit codes (137, 1, 143), generation of `crash-reports/*.txt`, or Forge/Fabric mod rejection exceptions.
  - If Phase 1 fails, the container is halted immediately, the crash log is parsed via Feature 5, the test is marked `FAILED`, and the failed-mod list is surfaced to the admin.
- **Phase 2 — Optional Admin Play-Test Window:**
  - If Phase 1 succeeds, the admin can either click **"Promote to Production"** immediately, or click **"Open Play-Test Window"** (keeps the container alive for a configurable 15-minute lease on an ephemeral port like `25665`). This allows the admin to join with a Minecraft client and test chunk rendering or complex plugin behavior before committing to production.

#### 3.6 Atomic Promotion & Rollback Paths
- **Promote:**
  1. Stop production server gracefully (`StopServerCommand`).
  2. Stage manifest configs/mods in sibling directory; swap into live directory using `_atomic_replace_dir`.
  3. If admin opted to keep world changes made during play-test, atomically swap the test world into live. Otherwise, preserve existing live world.
  4. Restart production server (`StartServerCommand`).
  5. Delete ephemeral test container and directory.
- **Rollback / Discard:**
  1. Stop and destroy test container `onx-test-<test_id>`.
  2. Remove ephemeral directory `.onx/tests/<test_id>`.
  3. Production server remains untouched.
- **Disable Mod & Retry:**
  1. If a specific mod failed in test, the admin clicks "Disable Mod & Retry".
  2. Mod is renamed to `<mod>.jar.disabled`.
  3. A new test iteration boots instantly.

#### 3.7 Multi-Node Groundwork
- The database schema includes a `node_id` column (default `"local"`).
- `TestExecutionRunner` defines an abstract interface: `run_test(spec: TestSpec) -> TestHandle`. In Phase 4, the only implementation is `DockerTestExecutionRunner`. In future phases, a `RemoteNodeTestExecutionRunner` can be introduced with zero changes to domain models or schemas.

### 4. Affected Components
- **Backend New Module:** `backend/app/modules/versioning/`
  - Domain: `ServerCommit`, `ServerBranch`, `ServerWorldSnapshot`, `ServerTestRun`, `TestRunStatus`.
  - Application: `CreateCommitCommand`, `CreateBranchCommand`, `RunIsolatedTestCommand`, `PromoteCommitCommand`, `DiscardTestCommand`, `GetCommitHistoryQuery`, `GetTestStatusQuery`.
  - Infrastructure: `SQLVersioningRepository`, `BtrfsZfsSnapshotDriver`, `StorageCapabilityProbe`, `DockerTestExecutionRunner`.
- **Frontend New Module:** `frontend/src/server_manager/pages/ServerVersioningPage.tsx` and `TestRunModal.tsx`.

### 5. Interfaces & Contracts
- **Permissions (`contracts/permissions.yaml`):**
  - `server:version:read` — View commit history and branches.
  - `server:version:commit` — Create commits / branches.
  - `server:test:execute` — Trigger and interact with test containers.
  - `server:version:promote` — Promote test state to live production.
- **Database Schema (Alembic migration `add_server_versioning_tables`):**
  - `server_branches`: `(id, server_id, name, head_commit_id, created_at)`
  - `server_commits`: `(id, server_id, branch_id, parent_commit_id, author_id, message, manifest_json, world_snapshot_id, created_at)`
  - `server_world_snapshots`: `(id, server_id, storage_path, size_bytes, created_at)`
  - `server_test_runs`: `(id, server_id, commit_id, node_id, status, ephemeral_port, log_output, failure_reason, created_at, expires_at)`

### 6. Failure Cases & Edge Cases
- **Non-Btrfs/ZFS Filesystem:** Detected via `StorageCapabilityProbe` preflight. Returns `412 Precondition Failed`; UI displays clear requirement; live servers unaffected.
- **World-State Divergence on Rollback-After-Live-Update:** If a promoted update runs in production for days and the admin later decides to roll back to a prior commit:
  - System enforces a mandatory choice:
    1. *Config & Mods Only Rollback (Default & Recommended):* Reverts configs and mods to prior commit; keeps current live world intact (prevents destroying player builds).
    2. *Full Rollback (Destructive):* Reverts configs, mods, and world back to the pre-update snapshot. Displays a double-confirmation modal warning of permanent player progress loss, and creates an automatic safety backup before executing.
- **Test Container Hang or Crash:** 90-second hard supervisor timeout. If the container crashes or fails to emit ready signal, the runner captures logs, executes `docker rm -f`, and marks the test `FAILED`.
- **Concurrent Test Runs:** A Redis/asyncio lock per `server_id` rejects overlapping test runs with `ConflictError("A test run is already active for this server.")`.

### 7. Tests & Verification
- `test_storage_capability_probe.py`: Unit tests verifying reflink detection on supported vs unsupported filesystems.
- `test_versioning_manifest.py`: Unit tests for commit manifest generation, hashing, and parentage.
- `test_btrfs_zfs_snapshot_driver.py`: Reflink cloning mocked and live execution tests.
- `test_isolated_test_runner.py`: Container lifecycle, timeout enforcement, and log scraping.
- `test_promote_and_rollback.py`: Atomic promotion, directory swapping, and rollback isolation.

### 8. Out of Scope
- Actual remote multi-node clustering or distributed test workers (groundwork abstraction only).
- Global UI redesign beyond the versioning and test pages.

---

## Feature 3 — Custom Mod Support

### 1. Goal
Provide complete mod lifecycle management for Forge, NeoForge, Fabric, and Quilt servers:
- Allow direct user uploads of custom `.jar` files into the server's `mods/` directory.
- Extract comprehensive metadata from `.jar` archives (`mod_id`, `name`, `version`, `loaders`, `dependencies`).
- Real physical enabling and disabling on disk (`.jar` <-> `.jar.disabled`).
- Unblock Modrinth catalog mod search and installations for modded servers.

### 2. Current Behavior
- Panel only recognizes Bukkit plugins in `plugins/`.
- `install_modrinth_plugin.py` line 38 hardcodes `_MANUAL_SERVER_TYPES = {"vanilla", "fabric", "forge", "neoforge"}`, blocking modded servers.
- `reconcile_plugins.py` hardcodes `plugins/` and ignores `mods/`.
- `jar_metadata_parser.py` extracts a version string but discards mod ID, name, loader, and dependencies.
- `ServerModsPage.tsx` is an empty 16-line placeholder.

### 3. Proposed Change

#### 3.1 Metadata Extraction Engine (`JarMetadataParser`)
Extend `jar_metadata_parser.py` to return a typed `ModMetadata` dataclass:
- Probes:
  - Fabric / Quilt: `fabric.mod.json` / `quilt.mod.json` (`id`, `name`, `version`, `depends`, `environment`).
  - Forge / NeoForge: `META-INF/mods.toml` / `META-INF/neoforge.mods.toml` (`modId`, `displayName`, `version`, `dependencies`).
  - Legacy Forge: `mcmod.info`.
  - Bukkit / Paper: `plugin.yml` / `paper-plugin.yml`.

#### 3.2 Target Directory Routing
Dynamic routing based on server software:
- Bukkit, Paper, Purpur, Spigot, Folia -> `<server_dir>/plugins/`
- Fabric, Forge, NeoForge, Quilt -> `<server_dir>/mods/`

#### 3.3 Physical On-Disk Disabling
Minecraft servers scan and boot every `.jar` file present in `mods/`. Setting a database row to `DISABLED` does not stop broken mods from booting.
- **Disabling:** Atomically renames `<server_dir>/mods/<mod>.jar` to `<server_dir>/mods/<mod>.jar.disabled`.
- **Enabling:** Atomically renames `<mod>.jar.disabled` back to `<mod>.jar`.

#### 3.4 Modrinth Catalog Unblocking
Remove `fabric`, `forge`, `neoforge` from `_MANUAL_SERVER_TYPES` in `install_modrinth_plugin.py`. Route downloaded files to `mods/` when the server type is modded.

#### 3.5 Resolution of RECON Open Unknowns
- **Catalog vs Direct Upload Scope:** **Recommendation:** Implement BOTH direct custom `.jar` upload AND Modrinth mod search/download. *Rationale:* Modrinth provider already supports `project_type="mod"`; unblocking the blacklist and routing files to `mods/` is minimal incremental effort that delivers a complete mod manager.
- **Client vs Server Mod Filtering:** **Recommendation:** Non-blocking warning badge in UI. Parse `fabric.mod.json` (`environment: "client"`) or Forge metadata. If a client-only mod is detected (e.g. Sodium, Iris, JEI), display a warning badge ("Client-only mod detected — may fail or be ignored on dedicated server"), but do not hard-block installation.

### 4. Affected Components
- `backend/app/modules/plugin/infrastructure/jar_metadata_parser.py`
- `backend/app/modules/plugin/application/commands/install_modrinth_plugin.py`
- `backend/app/modules/plugin/application/commands/reconcile_plugins.py`
- `backend/app/modules/plugin/application/commands/disable_plugin.py` / `enable_plugin.py`
- `backend/app/modules/plugin/application/commands/upload_mod.py` (New)
- `frontend/src/server_manager/pages/ServerModsPage.tsx` (Complete implementation)

### 5. Interfaces & Contracts
- **Commands:** `UploadModCommand(server_id, filename, file_content)`, `ToggleModStateCommand(server_id, mod_id, enabled)`
- **Permissions:** `plugin:install`, `plugin:delete`
- **DB Schema:** Add columns to `plugins` table: `loader` (VARCHAR 32), `mod_id` (VARCHAR 128), `is_disabled_on_disk` (BOOLEAN default FALSE).

### 6. Failure Cases & Edge Cases
- **Zip Slip / Path Traversal:** Filenames sanitized via `os.path.basename` and checked with `Path.is_relative_to`.
- **Non-JAR / Malicious Payload:** Header checked for ZIP magic bytes (`PK\x03\x04`). Unparseable or corrupt archives rejected with `InvalidJarError`.

### 7. Tests & Verification
- Unit tests parsing actual `fabric.mod.json`, `mods.toml`, `mcmod.info`.
- Tests verifying physical rename on disk (`.jar` -> `.jar.disabled`).
- Tests verifying Modrinth downloads route to `mods/` for Fabric/Forge servers.
- Frontend tests for `ServerModsPage.tsx` table, upload zone, and status toggles.

### 8. Out of Scope
- Runtime hot-reloading of Forge/Fabric mods without JVM restart (Minecraft engine limitation).

---

## Feature 4 — Change History Log

### 1. Goal
Provide a durable, queryable operational audit log capturing all configuration changes, lifecycle transitions, mod/plugin modifications, backup operations, and versioning events across managed servers.

### 2. Current Behavior
- `audit_log` table exists with a SHA-256 tamper-evident hash chain, but is only invoked in `login.py`.
- `UnitOfWork` publishes domain events to `EventBus` in memory, but never stores them.
- Frontend `activityStore.ts` is an in-memory 20-item array cleared on page reload or logout.

### 3. Proposed Change

#### 3.1 Event Persistence Architecture
An asynchronous `ActivityEventSubscriber` subscribes to the global `EventBus` and records domain events into a dedicated database table.
- Subscribed domain events:
  - Lifecycle: `ServerCreatedEvent`, `ServerStartedEvent`, `ServerStoppedEvent`, `ServerCrashedEvent`
  - Configuration: `ServerConfigUpdatedEvent`
  - Mods/Plugins: `PluginInstalledEvent`, `PluginDisabledEvent`, `PluginUninstalledEvent`
  - Backups: `BackupCreatedEvent`, `BackupRestoredEvent`, `BackupDeletedEvent`
  - Versioning/Testing: `CommitCreatedEvent`, `TestRunStartedEvent`, `TestRunCompletedEvent`, `CommitPromotedEvent`

#### 3.2 Resolution of RECON Open Unknowns
- **Event Granularity:** **Recommendation:** Capture both user-initiated API mutations (with actor ID, IP, and summary) AND significant system lifecycle transitions (crashes, recovery runs). Exclude high-frequency background noise (TPS metric polls, websocket heartbeats).
- **Storage Strategy:** **Recommendation:** Create a dedicated `server_activity_logs` table rather than overloading the auth `audit_log` hash chain. *Rationale:* Activity logs require fast paginated queries with composite filtering on `(server_id, timestamp)`, whereas `audit_log` is a sequential cryptographic ledger for security auditing.

#### 3.3 Query & UI Presentation
- Query: `GetServerActivityQuery(server_id, limit, offset, event_type, from_date, to_date)`
- UI: Dedicated "History" tab on the Server Detail page showing an interactive chronological timeline with actor badges, action descriptions, and expandable diffs/details.

### 4. Affected Components
- `backend/app/modules/activity/` (New module):
  - Domain: `ServerActivityLog` entity.
  - Application: `ActivityEventSubscriber`, `GetServerActivityQuery`.
  - Infrastructure: `SQLActivityRepository`, `ServerActivityLogModel`.
- `frontend/src/server_manager/pages/ServerHistoryPage.tsx` or `ActivityTab.tsx`.

### 5. Interfaces & Contracts
- **Permissions:** `server:history:read` in `contracts/permissions.yaml`.
- **Database Schema (Alembic migration `add_server_activity_logs_table`):**
  - `server_activity_logs`: `(id, timestamp, server_id, actor_type, actor_id, event_type, summary, details_json)`
  - Composite Index: `ix_activity_server_timestamp (server_id, timestamp DESC)`.

### 6. Failure Cases & Edge Cases
- **Asynchronous Decoupling:** Event subscriber operates in a decoupled async task; failure to record an activity event never fails the primary business transaction.
- **Database Growth:** Integrated with scheduled `event_cleanup.py` maintenance task with a 90-day retention default.

### 7. Tests & Verification
- Unit tests verifying event subscriber transforms domain events into DB records.
- Query pagination, date-range, and event-type filter tests.
- Retention cleanup tests.
- Frontend history timeline rendering tests.

### 8. Out of Scope
- In-game Minecraft chat or player command logging.

---

## Feature 5 — Better Log / Crash Readability

### 1. Goal
Provide administrators with high-visibility console and crash diagnostics:
- Eliminate the offline console blanking defect so logs and crash data remain readable when a server stops or crashes.
- Real-time severity colorization (INFO, WARN, ERROR, FATAL) and interactive search/filtering.
- Dedicated crash report viewer with automated root-cause analysis (identifying blamed mods or JVM errors) and actionable remediation hints.

### 2. Current Behavior
- `GetServerConsoleQuery` returns `lines = []` whenever server status is not RUNNING or STARTING.
- `evidence_collector.py` reads `logs/latest.log` and `crash-reports/*.txt` on disk, but this data is only consumed internally by health calculators and never exposed to the UI.
- `ServerConsole.tsx` polls HTTP every 3 seconds, displaying raw unformatted green text with no colors or search.

### 3. Proposed Change

#### 3.1 Offline Console Fallback
Update `GetServerConsoleHandler`: if the server runtime is absent or server status is STOPPED, FAILED, or CRASHED, the handler falls back to reading the tail of `<server_dir>/logs/latest.log` from disk (using the file-reading logic in `evidence_collector.py`) rather than returning an empty array.

#### 3.2 Crash Report Inspector & Mod Blaming
- Create query `GetServerCrashReportsQuery(server_id, limit=5)`:
  - Scans `<server_dir>/crash-reports/crash-*.txt`.
  - Passes crash reports to `PatternCrashAnalyzer` (extended with Forge `ModLoadingException` and Fabric `ModResolutionException` patterns).
  - Returns structured `CrashReportSummary`: timestamp, failure code, blamed mod (if identifiable), stack trace snippet, and suggested remediation.

#### 3.3 Resolution of RECON Open Unknowns
- **Transport Mechanism:** **Recommendation:** Use WebSocket streaming (`server:<id>:console` channel, already verified in Phase 5) for live log streaming while running, with HTTP query fallback for initial history and offline reading. Eliminates aggressive 3s HTTP polling.
- **UI Presentation:** **Recommendation:** Inline severity highlighting and search directly in `ServerConsole.tsx`, accompanied by a prominent "Crash Detected" alert banner that opens an inspectable `CrashReportViewerModal` with formatted stack traces and blamed-mod remediation advice.

#### 3.4 Log Colorization & Filtering
In `ServerConsole.tsx`:
- Parse standard Minecraft log levels:
  - `[INFO]` -> Neutral / Sky (`text-sky-300`)
  - `[WARN]` -> Amber (`text-amber-400`)
  - `[ERROR]` / `[FATAL]` -> Red (`text-rose-400 font-semibold`)
- Search input with regex/case-insensitive substring filtering.
- "Follow Log" auto-scroll toggle.

### 4. Affected Components
- `backend/app/modules/server/application/queries/get_server_console.py` (Fallback to disk)
- `backend/app/modules/health/infrastructure/crash_analyzer.py` (Forge/Fabric exception patterns)
- `backend/app/modules/health/application/queries/get_crash_reports.py` (New query)
- `frontend/src/server_manager/components/ServerConsole.tsx` (Coloring, search, auto-scroll)
- `frontend/src/server_manager/components/CrashReportViewerModal.tsx` (New modal)

### 5. Interfaces & Contracts
- **Queries:** `GetServerConsoleQuery` (updated with `fallback_to_disk=True`), `GetServerCrashReportsQuery(server_id)`.
- **Permissions:** `server:read` (no new permission string needed).

### 6. Failure Cases & Edge Cases
- **Missing Log File:** Returns clean empty state ("No log file exists on disk yet") without crashing.
- **Massive Log Files (> 100MB):** Files are read from the end using `file.seek(0, os.SEEK_END)` with a 256KB tail buffer, preventing memory exhaustion.

### 7. Tests & Verification
- Unit tests for `GetServerConsoleHandler` offline fallback reading `latest.log`.
- Pattern analyzer tests matching Forge `ModLoadingException` and extracting the blamed mod name.
- Frontend tests for log level colorization, search filtering, and crash modal.

### 8. Out of Scope
- Modifying Minecraft's internal log4j2 configuration.

---

## Inter-Feature Dependencies & Natural Order

While build-batch planning will be formalized separately, this Design Spec acknowledges the natural dependency flow established during RECON:

```text
┌────────────────────────────────────────────────────────┐
│ Feature 5: Better Log / Crash Readability              │
│ (Provides crash detection & mod-blame diagnostics)     │
└──────────────────────────┬─────────────────────────────┘
                           │ feeds failure diagnostics into
                           ▼
┌────────────────────────────────────────────────────────┐
│ Feature 3: Custom Mod Support                          │
│ (Provides mod parsing, mods/ targeting & disabling)    │
└──────────────────────────┬─────────────────────────────┘
                           │ feeds mod manifests & disable action into
                           ▼
┌────────────────────────────────────────────────────────┐
│ Feature 1: Git-Inspired Versioning & Testing           │
│ (Standalone subsystem, COW snapshots, test containers) │
└──────────────────────────┬─────────────────────────────┘
                           │ emits lifecycle & versioning events into
                           ▼
┌────────────────────────────────────────────────────────┐
│ Feature 4: Change History Log                          │
│ (Captures domain events from all features durably)     │
└────────────────────────────────────────────────────────┘
```

---

## Design Review Self-Application (Orchestrator.md §6 Checklist)

| Criteria | Assessment | Detail |
|---|:---:|---|
| **1. Scope & Boundaries** | **PASS** | Feature 1 is strictly standalone and decoupled from `ServerProvider`. Feature 2 is fully merged. Multi-node is groundwork only. |
| **2. Architecture & DDD** | **PASS** | Hexagonal architecture preserved. Dedicated `versioning` and `activity` modules. All actions route through CQRS. |
| **3. Storage & Prerequisites** | **PASS** | Btrfs/ZFS is a hard prerequisite with automated probe. Actionable failure mode (features disabled, rest of platform unaffected). Hardlinks strictly prohibited. |
| **4. Proven Primitives** | **PASS** | Reuses `restore_service.py`'s `_atomic_replace_dir` and `_safe_extract_tar`. |
| **5. Contracts & Permissions** | **PASS** | All new permissions and endpoints identified for `contracts/permissions.yaml`. 5/5 CI gates protected. |
| **6. Edge Cases Handled** | **PASS** | World divergence on rollback has a clear two-way policy. Test container 90s supervisor timeout. Idempotency on test runs. |
| **7. Unknowns Resolved** | **PASS** | All 4 RECON unknowns resolved with explicit recommendations and justifications. |

---

## Open Decisions for Mohamed's Review & Approval

The following specific recommendations are submitted for Mohamed's explicit sign-off:
1. **Verification Workflow (Feature 1):** Two-phase model — Phase 1 is an automated 90s boot/health probe; Phase 2 is an optional 15-minute admin play-test window on an ephemeral port. *(Recommended)*
2. **Mod Support Scope (Feature 3):** Support BOTH direct custom `.jar` uploads AND unblocked Modrinth catalog search for modded servers; display non-blocking warning badge for client-only mods. *(Recommended)*
3. **Activity Storage (Feature 4):** Persist in a dedicated query-optimized `server_activity_logs` table rather than the cryptographic security `audit_log` hash chain. *(Recommended)*
4. **Log Transport (Feature 5):** WebSocket streaming for live console with HTTP query fallback for initial history and offline fallback to `latest.log`. *(Recommended)*
