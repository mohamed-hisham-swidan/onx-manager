> **STATUS (added by the orchestrator, 2026-11-08):** EXTERNAL RESEARCH INPUT. Written from the owner's outside research, WITHOUT access to the repository. It is NOT canonical, NOT approved, and NOT a decision. Every file path, identifier, table name and "existing component" below is UNVERIFIED until a RECON confirms it against the code. The line "Status: Canonical ..." below belongs to the original author and is void. The body is the original text; only Markdown formatting was repaired (section 7.2 table, arrows).

---

# ONX Manager — Architectural Design Specification (v2.0)

**Document ID:** SPEC-ARCH-V2-UNIFIED-CONTAINER-BRANCHING
**Status:** Canonical Architecture & Design Specification (Includes Decision Record D2)
**Target Codebase:** ONX Manager (v0.1.0+, Python 3.12 / FastAPI Modular Monolith / CQRS + React 19 / TypeScript 5)

## 1. Executive Summary & Architectural Philosophy

ONX Manager is transitioning to a 100% Containerized, Dual-Mode Server Architecture designed to eliminate host-environment drift while hiding the complexity of Git-inspired version control (DAG, commits, worktrees, materialization) behind an intuitive operational workflow.

### Core Architectural Pillars

- **Container-Exclusive Execution (No Local Providers):** Every server and every isolated branch runtime executes strictly inside a container managed by DockerProvider. Host-coupled process runners (LocalLinuxProvider, LocalWindowsProvider, and tmux console fallbacks) are permanently deprecated and removed.
- **Two Distinct Server Modes (Simple vs. Advanced):**
  - **Simple Mode:** A single-container, zero-friction experience for casual, friend-group, and mid-sized servers (up to ~500 players). Files and configurations are edited directly in the unified container filesystem and take effect upon restart. Code/Data separation is only invoked when taking targeted Data-Only Internal Backups.
  - **Advanced Mode:** A multi-container, branch-isolated production environment for large networks and development teams. Separates the immutable Root (main), the active player container (live), and isolated developer environments (Work/Test Branches) with Transparent Auto-Branching (Copy-on-Write UI) so users never accidentally mutate main directly.
- **Strict Code vs. Live Data Separation:** In Advanced Mode (and during targeted backups), ONX Manager enforces a deterministic boundary between Code/Static Configuration (JARs, static YAML/TOML/properties) and Live Runtime Data (worlds, player progression, and dynamic plugin databases/storage inside plugins/ and config/).
- **Two-Tier Backup Architecture:**
  - **Tier 1 — Internal Server Backups (Per-Server Dashboard):** Scoped backups inside the server workspace for Live Data (worlds + plugin databases) or Branch/Main snapshots.
  - **Tier 2 — External Disaster Recovery Backups (Global System Level):** Host-isolated, container-independent vault stored outside the container runtime to survive total Docker or container corruption, supporting both Code-Only and Full (Code + Data) snapshots.
- **Multi-Node Readiness:** All container execution, volume mounts, and synchronization pipelines are abstracted behind node-agnostic interfaces so future community-driven multi-node/distributed clustering can be plugged in without refactoring domain logic.

## 2. Formal Decision Record: DECISION-D2

### Title

Removal of Local Runtime Providers, Introduction of Simple vs. Advanced Server Modes, and Transparent Branch Isolation.

### Context

In the existing codebase (SPECS.md), ServerProvider supports three implementations: LocalLinuxProvider (tmux sessions), LocalWindowsProvider (Win32 process groups + taskkill), and DockerProvider. Additionally, the Enterprise Branch Runtime (Stages A–G in backend/app/modules/versioning/) exposes raw Git-like primitives (CommitDiffModal, MaterializationBrowserModal, ImportReviewModal, AutoCommitLiveChangesCommand, .onx/worktrees/, .onx/tests/) directly to the user.

In practice:

- Maintaining local OS providers alongside Docker creates severe parity bugs, port conflicts, and filesystem permission leaks.
- Exposing raw commits, worktrees, and live-change import scans (POST /import-review/scan) confuses server administrators and mixes continuously mutating live world/plugin state with static configuration history.

### Decision

- **Deprecate and Remove Local Providers:** Delete LocalLinuxProvider and LocalWindowsProvider from backend/app/modules/server/infrastructure/ and strip tmux capture fallbacks from ConsoleStreamManager. DockerProvider becomes the sole authoritative runtime driver.
- **Introduce Server Operational Mode (ServerMode.SIMPLE | ServerMode.ADVANCED):** Persisted on the Server aggregate (servers table via a new Alembic revision following head b1e2100000022).
- **Enforce live vs. main vs. branch Isolation in Advanced Mode:**
  - main is an immutable root container/filesystem inside the container environment that never runs an active game server process.
  - Direct edits to main in the UI automatically and transparently spin up an ephemeral edit/work branch; changes only reach main when the user clicks Save / Merge.
  - live is the dedicated production container where players connect. It pulls updated code/configs from main exclusively on Restart, leaving live world and plugin databases untouched.
- **Retire Live Import Scanning:** Deprecate ImportReview (POST /import-review/scan) and AutoCommitLiveChangesCommand, as live code files are locked during runtime and all configuration mutations flow strictly through Branch → Merge to main → Restart live.

## 3. Mode 1: Simple Server Architecture (ServerMode.SIMPLE)

### 3.1 Target Audience & Operational Model

Designed for personal servers, friend groups, and standard community servers (up to ~500 concurrent players) that do not require staging branches or multi-developer testing pipelines.

### 3.2 Container & Filesystem Topology

- **Single Unified Container:** Runs inside a single Docker container managed by DockerProvider with a unified persistent volume/mount (/data).
- **No Runtime Code/Data Split During Normal Operation:** All files (server.jar, server.properties, plugins/, mods/, world/, world_nether/, world_the_end/) reside together inside the container's /data directory.
- **Direct Modification & Restart Flow:**
  - The administrator edits settings, properties, or uploads plugins directly through ServerFilesPage or the Marketplace (Modrinth catalog provider).
  - Changes are written directly to the files inside the active container mount.
  - The administrator triggers a Restart (RestartServerCommand).
  - The container restarts in place, loading the modified configuration and plugins while retaining all world and player progress.

### 3.3 UI / Frontend Footprint (frontend/src/server_manager/)

- **Visible Pages:** Console (with live WebSocket stream, console-ip-badge, Sparkline telemetry), File Manager (ServerFilesPage), Plugins & Marketplace, Monitoring, Settings, and Internal Backups.
- **Hidden Pages:** ServerVersioningPage.tsx and all 8 versioning modals (BranchProtectionModal, TestDefinitionsModal, TestEvidenceModal, MaterializationBrowserModal, ImportReviewModal, ManageBranchesModal, CreateTagModal, CommitDiffModal) are completely hidden from the navigation sidebar and guarded at the router level.

### 3.4 Backup Behavior in Simple Mode

Although Simple Mode does not separate Code and Data during normal operation, the Data vs. Code Classifier (detailed in Section 5) is invoked when the user navigates to the Internal Backup Page and requests a Data-Only Backup (capturing worlds, player data, and dynamic plugin databases without re-archiving static binaries), or when the user triggers a Full (Code + Data) Backup from the External Backup Page.

## 4. Mode 2: Advanced Server Architecture (ServerMode.ADVANCED)

Advanced Mode transforms a single logical server into an orchestrated, multi-container workspace powered under the hood by the versioning (Stage B–G), server, and operations DDD modules.

```text
┌────────────────────────────────────────────────────────────────────────────┐
│                      ADVANCED SERVER WORKSPACE (ONX)                       │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ 1. ROOT REPOSITORY (`main` Container / Filesystem)                   │  │
│  │    - Stores ONLY Code, Binaries (.jar), and Static Configs           │  │
│  │    - Never runs a live game loop; Direct edits are blocked           │  │
│  │    - Attempting to edit `main` auto-creates a Draft/Work Branch      │  │
│  └──────────────────┬───────────────────────────────────▲───────────────┘  │
│                     │                                   │                  │
│     1. Selective    │ (On Restart ONLY:                 │ 3. Save / Merge  │
│        Code Sync    │  Updates JARs & Configs;          │    (Commits to   │
│                     │  Skips Worlds & Plugin DBs)       │     `main` DAG)  │
│                     ▼                                   │                  │
│  ┌─────────────────────────────────────┐   ┌────────────┴───────────────┐  │
│  │ 2. PRODUCTION RUNTIME (`live`)      │   │ 3. WORK / TEST BRANCHES    │  │
│  │    - Active Player Container        │   │    - Isolated Container(s) │  │
│  │    - Console & Commands: OPEN       │   │    - Multi-Dev File Edits  │  │
│  │    - World & Plugin Data: R/W       │   │    - Runs on Sandbox Data  │  │
│  │    - Server Code & Configs: LOCKED  │   │      or Internal Snapshot  │  │
│  └─────────────────────────────────────┘   └────────────────────────────┘  │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

### 4.1 Component 1: The Root (main Branch / Storage Container)

- **Role:** The authoritative Single Source of Truth for server code, core binaries (server.jar, libraries/), plugin/mod .jar files, and static configuration files.
- **Containerized Storage Isolation:** main lives inside the containerized environment as a dedicated read/write root filesystem/container volume—completely detached from the host OS and never executing an active Minecraft Java process.
- **Strict Immutability & Transparent Auto-Branching (The "Edit-as-Branch" UX):**
  - main is locked against direct in-place mutation (BranchProtectionPolicy: allow_direct_commit=False, prevent_deletion=True).
  - **Seamless UX Trick:** If an administrator opens main in the File Manager or Settings UI and begins editing a file or installing a plugin, ONX Manager does not throw an error. Instead, it transparently forks an implicit working branch (e.g., draft/admin-edit-&lt;timestamp&gt;) in the background.
  - All edits occur inside that isolated branch filesystem. Nothing in main is altered until the administrator clicks Save / Merge, which executes an atomic merge commit into main via fs_atomic.py and tree_writer.py.

### 4.2 Component 2: The Production Container (live Runtime)

- **Role:** The active container where players connect and play (1:1 Runtime entity in server_runtimes).
- **Dashboard Presentation:** Appears in the UI as the primary live control view (with its own Console, Metrics, and World Data controls).
- **Runtime Permissions & Locking Policy:**
  - **Allowed while live is running:** Full interactive WebSocket Console (ConsoleStreamManager, exec_input), RCON/in-game commands (/op, /whitelist, /save-all), viewing live metrics (docker stats), managing world* directories, and triggering Internal Backups.
  - **Locked while live is running:** All server code, .jar binaries, and static plugin/server configurations are Read-Only (Locked) in ServerFilesPage. Administrators cannot hot-edit code in live.
- **The Restart Synchronization Contract (ADR-0015 Alignment):**
  - Merging a branch into main does not touch or interrupt the running live container. live remains pinned to the commit hash it booted with.
  - When the administrator triggers Restart on live:
    - live gracefully stops (stop command → wait for Java exit 0).
    - The synchronization engine pulls the latest commit from main and updates only the Code and Static Configurations in live.
    - All Live State (Worlds, player inventories, and dynamic plugin databases/storage) in live is preserved intact.
    - live boots up on the new commit ID.

### 4.3 Component 3: Work & Test Branches (Work/Test Containers)

- **Role:** Isolated environments where one or multiple developers can modify files, add/remove plugins, write custom scripts, and spin up an isolated test server simultaneously.
- **Unified Work + Test Lifecycle:**
  - A branch is created from main (or auto-created when editing main).
  - **Filesystem Mode:** Multiple developers can collaborate on the branch's files (configs, scripts, plugin JARs) without running a container, consuming zero RAM/CPU.
  - **Active Test Container Mode:** At any moment, developers can click Start Test Server on the branch.
  - **Resource Scheduling:** The request passes through RuntimeAdmissionScheduler (Stage D), which checks host RAM/CPU headroom, assigns a lease in server_admission_lease, allocates an isolated network port, and boots a dedicated container via DockerProvider.
- **Test Container Data Provisioning (Zero Production Risk):**
  - A branch container never mounts the live production world (session.lock and SQLite -wal corruption prevention).
  - **Default Mode (Sandbox Data):** By default, the test container boots with a clean, lightweight default test world and fresh plugin databases so it starts in seconds.
  - **Snapshot Mode (Optional):** Developers can select "Seed Test Data from Internal Backup" to clone a point-in-time Btrfs snapshot or extracted archive of the live server's data into the test container.
  - **Merge Cleanliness:** When testing succeeds (EvidenceBundle / manual review) and the branch is merged into main, only the Code and Static Config changes are committed to main. The disposable test world and test plugin databases are discarded or kept local to the test branch.

## 5. The Code vs. Data Classification Engine

To prevent plugin updates or main → live restarts from wiping player land claims, economy balances, ranks, or NPCs, ONX Manager implements a deterministic Classification & Sync Engine inside backend/app/modules/versioning/infrastructure/.

### 5.1 Three-Category File Taxonomy

| Category | Definition | Included Paths & Patterns | Owned By | Synced main → live on Restart? |
|---|---|---|---|---|
| 1. CODE_AND_STATIC_CONFIG | Immutable binaries, libraries, and admin-authored settings | server.jar, paper-*.jar, fabric-server-launch.jar, libraries/**, versions/**, plugins/*.jar, mods/*.jar, server.properties, bukkit.yml, spigot.yml, commands.yml, config/paper-global.yml, config/paper-world-defaults.yml, static plugins/&lt;Plugin&gt;/config.yml, messages*.yml, lang/** | main & Work Branches | YES (Replaced/Updated from main) |
| 2. LIVE_DATA_STATE | Worlds, player data, runtime databases, and in-game generated plugin state | world/**, world_nether/**, world_the_end/**, ops.json, whitelist.json, banned-players.json, banned-ips.json, usercache.json, forwarding.secret, all *.db, *.sqlite, *.sqlite3, *-wal, *-shm, *-journal, *.mv.db, *.h2.db, and dynamic plugin state paths (see 5.2) | live Container (or Sandbox in Test Branches) | NEVER (Strictly skipped and protected in live) |
| 3. EPHEMERAL_LOGS_CACHE | Runtime logs, crash dumps, and temporary caches | logs/**, crash-reports/**, debug/**, cache/**, .fabric/**, .neoform/**, plugins/WorldEdit/sessions/** | Per-Container Runtime | NEVER (Rotated/Pruned locally) |

### 5.2 Built-in Plugin & Mod State Protection Rules

Because Minecraft plugins mix static configs and live player state inside plugins/&lt;PluginName&gt;/, the classifier enforces a 3-Layer Protection Filter before any file is synced or backed up:

- **Layer 1 — Universal Extension Shield (Always LIVE_DATA_STATE):**
  - Any file anywhere in plugins/, mods/, or config/ matching: *.db, *.sqlite, *.sqlite3, *-wal, *-shm, *-journal, *.mv.db, *.h2.db, *.trace.db, session.lock, level.dat, *.mca, *.mcr.
- **Layer 2 — Universal Directory & Filename Shield (Always LIVE_DATA_STATE):**
  - Any directory inside plugins/&lt;Plugin&gt;/ or config/&lt;Mod&gt;/ named: userdata/, playerdata/, players/, data/, storage/, yaml-storage/, json-storage/, hocon-storage/, toml-storage/, worlds/, regions/, claims/, saves/, warps/, homes/, backups/.
  - Any root plugin directory named plugins/GriefPreventionData/.
  - Any file named: data.yml, data.json, storage.yml, saves.yml, regions.yml, claims.yml, homes.yml, warps.yml, userdata.yml.
- **Layer 3 — Curated Plugin Manifest & Custom Protected Paths:**
  - Handles known Hybrid Files (e.g., plugins/Citizens/saves.yml, plugins/Multiverse-Core/worlds.yml, world*/paper-world.yml, plugins/LuckPerms/yaml-storage/**, plugins/Essentials/userdata/**, plugins/WorldGuard/worlds/**).
  - **User-Extensible Override (.onx/state-policy.yml):** Administrators can mark any custom file or folder in the UI as "Protected Live Data" if a niche or custom-coded plugin writes player data into a non-standard YAML/JSON file.

### 5.3 Exact Synchronization Mechanism (main → live on Restart)

Based on our container storage benchmarks, ONX Manager uses Manifest-Driven Selective Sync at Container Entrypoint/Reconciliation (combining fs_atomic.py with explicit include/exclude rules):

- **Crucial Safety Rule:** rsync --delete is strictly forbidden against the /data root of the live container, as an unmapped exclusion would wipe worlds or plugin databases.
- **How Plugin Deletion Works Safely:** Instead of --delete, ONX Manager tracks a deployment manifest (current-deployment.lock storing the list of .jar and static config files deployed by the previous commit). When updating from Commit A to Commit B on restart:
  - Only files that existed in Commit A's manifest and were explicitly removed in Commit B are deleted from live.
  - All new/modified CODE_AND_STATIC_CONFIG files in Commit B are atomically copied into live.
  - Every path matching LIVE_DATA_STATE is completely untouched.

## 6. Two-Tier Backup Architecture

ONX Manager splits backup operations into two distinct operational tiers to serve both daily administrative rollbacks and catastrophic host recovery, building upon backend/app/modules/backup/ (BackupSaga, AES-256-GCM, local + S3 aioboto3).

```text
┌────────────────────────────────────────────────────────────────────────────┐
│                        TWO-TIER BACKUP ARCHITECTURE                        │
├─────────────────────────────────────┬──────────────────────────────────────┤
│   TIER 1: INTERNAL SERVER BACKUP    │  TIER 2: EXTERNAL DISASTER RECOVERY  │
│   (Inside Per-Server Dashboard)     │  (Global System Page - Outside)      │
├─────────────────────────────────────┼──────────────────────────────────────┤
│ • Scope: Granular & Operational     │ • Scope: Catastrophic / Full System  │
│ • Simple Mode:                      │ • Completely isolated from Docker    │
│   - Back up Live Data (Worlds +     │   volumes & container daemon         │
│     Plugin DBs + server.properties) │ • Stored in external path / S3       │
│ • Advanced Mode:                    │   with AES-256-GCM encryption        │
│   - Option A: Back up `live` Data   │ • Modes (Simple or Advanced):        │
│   - Option B: Back up `main` or     │   - Mode 1: Code-Only Snapshot       │
│     a specific Work Branch (Code)   │   - Mode 2: Full Server (Code+Data)  │
└─────────────────────────────────────┴──────────────────────────────────────┘
```

### 6.1 Tier 1: Internal Server Backup (Per-Server Workspace Page)

Located inside each server's management dashboard (/servers/:id/backups). Designed for fast, frequent operational checkpoints and developer safety.

- **In Simple Mode:**
  - **Live Data Backup:** Captures LIVE_DATA_STATE (Worlds world*, player inventories, ops.json/whitelist.json, and all dynamic plugin databases/folders inside plugins/ and config/) plus core properties (server.properties), omitting heavy static binaries (libraries/, versions/, .jar cache).
- **In Advanced Mode:**
  - **Track 1 — live Data Backup:** Captures the active player state (LIVE_DATA_STATE) from the live container. Can be restored directly to live (when stopped) or used to seed a Work/Test Branch container for realistic staging tests.
  - **Track 2 — Branch / main Code Backup:** Allows the user to take an instant point-in-time snapshot of main or any specific Work/Test Branch (CODE_AND_STATIC_CONFIG only) from inside the server panel before attempting risky refactors.

### 6.2 Tier 2: External Disaster Recovery Backup (Global System Page)

Located on a dedicated top-level Global Backups Page (/system/disaster-recovery), completely outside individual server containers.

- **Isolation Guarantee:** Stored on a dedicated external host mount (e.g., /mnt/external-backups/ or remote S3 bucket via aioboto3) encrypted with AES-256-GCM. Even if the Docker daemon crashes, container volumes are corrupted, or a server workspace is accidentally wiped, External Backups remain 100% intact.
- **Supported Scopes (Available for both Simple and Advanced servers):**
  - **External Code-Only Backup:** Exports the entire server blueprint—in Advanced Mode, this includes the complete main repository, commit DAG (server_commits, server_commit_parents), tags, and all Work/Test Branches without the multi-gigabyte world folders. Ideal for migrating server setups or archiving development milestones.
  - **External Full Backup (Code + Data):** Exports a complete, self-contained disaster recovery bundle containing main, all branches, commit history, AND the complete live world and plugin databases. A single click restores the entire server infrastructure from scratch on a fresh machine.

### 6.3 Crash-Consistent Backup Execution Protocol (BackupSaga)

To prevent corrupted region files (.mca) or broken SQLite Write-Ahead Logs (-wal / -shm) when backing up a running live container, BackupSaga executes the following strict state machine:

1. **Quiesce Game Writes (Step 1):** Send save-off followed by save-all flush to the running container via the RCON / Console input pipe (write_exec_input).
2. **Await Flush Confirmation (Step 2):** Monitor ConsoleStreamManager output for the server's save completion confirmation line (with a deterministic timeout fallback).
3. **Atomic Snapshot / Capture (Step 3):**
   - If the host filesystem is Btrfs: Execute an instant, atomic read-only subvolume snapshot (btrfs subvolume snapshot -r), capturing all world regions and SQLite .db + -wal + -shm files at the exact same millisecond.
   - If the host filesystem is ext4/xfs: Copy the target files (ensuring SQLite .db and its -wal/-shm sidecars are copied together while writes are paused) into a staging archive compressed with zstd / tar.
4. **Resume Game Writes (Step 4 - Compensation Safe):** Immediately execute save-on in the finally / compensation block of BackupSaga so autosaving is always restored even if archiving fails.

**Pre-Deploy Automatic Snapshot:** Whenever an Advanced Server executes a Restart to pull new updates from main, the server is already fully stopped (Java process exited 0). At that exact moment—before copying files from main—ONX Manager takes a Cold Pre-Deploy Snapshot, guaranteeing 100% database consistency for instant rollback if a newly merged plugin crashes on startup.

## 7. Concrete Tooling, Storage Drivers & Codebase Integration Map

Below is the exact breakdown of every tool, library, and ONX Manager module used to build this architecture:

### 7.1 Container & Filesystem Layer

- **Container Engine:** Docker Engine (via DockerProvider async subprocess driver in backend/app/modules/server/infrastructure/docker_provider.py).
- **Image & Java Resolution:** Dynamic Java 8 / 17 / 21 / 25 container images with non-root UID/GID mapping to prevent host permission mismatches.
- **Volume & Mount Strategy:**
  - **Simple Mode:** Single persistent volume/bind mount /data per server container.
  - **Advanced Mode:**
    - main storage mount: /var/lib/onx/servers/&lt;server_id&gt;/main/ (Containerized root repo).
    - live runtime mount: /var/lib/onx/servers/&lt;server_id&gt;/live/ (Active production state + deployed code).
    - branches mounts: /var/lib/onx/servers/&lt;server_id&gt;/branches/&lt;branch_id&gt;/ (Isolated developer workspaces & test container mounts).
- **Storage Acceleration Driver (StorageDriver ABC):**
  - **BtrfsStorageDriver:** Uses btrfs subvolume create and btrfs subvolume snapshot for zero-cost Copy-on-Write branch creation, test data seeding, and instant pre-deploy snapshots.
  - **PosixAtomicStorageDriver (Fallback for ext4/xfs):** Uses fs_atomic.py and tree_writer.py with hardlink trees (cp -al) for immutable code blobs and selective manifest copying.

### 7.2 Backend DDD Module Modifications

| Module | Existing Components (SPECS.md) | Required Engineering Changes |
|---|---|---|
| server | Server aggregate, LocalLinuxProvider, LocalWindowsProvider, DockerProvider, ConsoleStreamManager | 1. Add mode: ServerMode (SIMPLE, ADVANCED) to Server aggregate. 2. Delete LocalLinuxProvider and LocalWindowsProvider. 3. Remove tmux fallback from ConsoleStreamManager. 4. Add file-lock guard in ServerFilesPage API endpoints to block modifying CODE_AND_STATIC_CONFIG paths on a running live container in Advanced Mode. |
| versioning | ServerBranch, Materialization, ImportReview, BranchProtectionPolicy, fs_atomic.py, tree_writer.py, RuntimeAdmissionScheduler | 1. Add DataCodeClassifier service implementing the 3-Layer Plugin/World Separation Rules. 2. Wire Auto-Branching Interceptor: any file write or plugin install targeting main automatically creates/updates an active draft branch. 3. Update RestartServerCommand in Advanced Mode to run the Selective main → live Sync (updating code/configs while skipping LIVE_DATA_STATE). 4. Deprecate ImportReview and AutoCommitLiveChangesCommand. |
| backup | BackupSaga, local + S3 (aioboto3), AES-256-GCM encryption | 1. Split backup commands into CreateInternalBackupCommand (DATA_ONLY or BRANCH_CODE) and CreateExternalDisasterBackupCommand (CODE_ONLY or FULL_SERVER). 2. Integrate save-off → save-all flush → save-on RCON/console sequence into BackupSaga. |

### 7.3 Frontend UI Workflow (frontend/src/)

- **Server Creation Wizard:** User selects Simple Server (1-click setup, standard dashboard) or Advanced Server (initializes main + live + Branching workspace).
- **Mode-Aware Navigation:**
  - If server.mode === 'SIMPLE': Render standard tabs (Console, Files, Plugins, Internal Backups, Monitoring, Settings).
  - If server.mode === 'ADVANCED': Render workspace selector at the top of the server view:
    - **[🟢 Live Server]** (Console open, World files editable, Code/Config files locked with badge: "Locked on Live — Edit in Main/Branch and Restart to apply").
    - **[🔒 Main (Root)]** (Shows current production code. Clicking Edit on any file or installing a plugin displays a subtle banner: "Editing in new branch draft/... — Click Save & Merge when ready").
    - **[🌿 Branches (N)]** (Full developer workspace: edit files collaboratively, click Start Test Container to test on a separate port with Sandbox Data or cloned Internal Backup, view TestEvidenceModal, and click Merge to Main).
- **Dual Backup Views:**
  - **Inside Server (/servers/:id/backups):** Clean Internal Backup UI for scheduling and restoring World/Plugin Data (and main/branch snapshots in Advanced Mode).
  - **Global Sidebar (/backups/external):** Dedicated External Vault UI showing off-container disaster recovery archives (Code-Only vs. Full Code + Data) with encryption status and 1-click full-server reconstruction.

## 8. Multi-Node Readiness (Future Community Extension Contract)

While multi-node clustering (distributing containers across multiple physical machines or sharding worlds across nodes) will be developed later in collaboration with the open-source community, v2.0 guarantees Zero-Refactor Multi-Node Readiness through three strict boundaries:

- **NodeExecutionTarget Abstraction:** DockerProvider and RuntimeAdmissionScheduler communicate via a node_id identifier (defaulting to local-primary in v2.0). No domain entity assumes localhost or hardcoded local file paths outside the provider adapter.
- **Location-Transparent Artifact Sync:** Because main only stores lightweight CODE_AND_STATIC_CONFIG artifacts (typically tens of megabytes without heavy world folders), syncing main to a live or test container on a remote node in the future only requires transferring the compact code bundle over gRPC/HTTP or S3, rather than copying multi-gigabyte world directories over the network.
- **Decoupled External Backup Store:** Because Tier-2 External Backups already support aioboto3 (S3-compatible object storage) with AES-256-GCM encryption, any future node in a cluster can pull or push full disaster recovery snapshots from a shared remote vault without shared host disks.
