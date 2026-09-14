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
**Revision:** 2026-09-13 — §3.5 finalized per Mohamed's sign-off on all 12 review items (clamps removed in favor of ResourcePreflightProbe sole guard, server-type-aware auto bot_tech selection, configurable defaults throughout, per-server JSON column, and candid self-review). Features 3–5 content unchanged.

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
- Bot-based automated runtime sanity verification of every test run (simulated players walking and jumping in the test server), replacing passive boot probes and human play-tests.
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
│                   ▲                                          ▲                   │
│                   │                       ┌──────────────────┤                   │
│                   └──────────────────┬────┘   ┌──────────────┴──────────────┐    │
│                                      │       │ Bot-Runner Sidecar (pooled) │    │
│                       ┌──────────────┴───────┴─────────────────────────────┐    │
│                       │   Versioning Subsystem                             │    │
│                       │   - Commit Manifests (JSON) - Branch Pointers      │    │
│                       │   - Test Supervisor - BotRunnerPool                │    │
│                       └────────────────────────────────────────────────────┘    │
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
3. **Write Manifest:** Target configs and mod `.jar` files are written into the test directory. The test `server.properties` is written exclusively through the test-only offline-mode writer path defined in §3.5.3 — never through any production config writer.
4. **Launch Test Container:** `IsolatedTestContainerRunner` launches a dedicated container:
   - Image: standard OpenJDK image matching server Java version.
   - Volumes: binds `.onx/tests/<test_id>` to `/data`.
   - Network: bridge mode. Test-container ports remain unmapped; bot runners reach the test server over the bridge network (see §3.5.4), so no ephemeral host-port mapping is required.
   - Sibling container DooD translation: routes paths through `resolve_host_mount_path()` if ONX runs inside Docker.
5. **Bot Verification:** Once the test container is launched, verification proceeds per §3.5 (bot run). There is no separate passive boot-probe phase and no human play-test window.

#### 3.5 Bot-Based Automated Verification (Mohamed Decision, supersedes 2026-09-12 two-phase model)
The rejected "90s automated boot probe + optional 15-minute human play-test" model is fully replaced by the following. The bot run **is** the verification phase: it provides automated runtime sanity checks, detecting boot failure and crashes naturally, because bots fail to connect when the server never becomes ready and the supervisor observes container exit during the run.

##### 3.5.1 Default Verification Behavior
- Every test run executes an **automated bot run with defaults of 10 simulated bots for 15 minutes** (both user-configurable with no numeric ceiling per §3.5.6).
- Bots connect to the offline-mode test server (§3.5.3) using deterministic offline usernames following the naming pattern `onx-bot-{run_id}-{n}` (e.g. `onx-bot-a1b2c3d4-1` … `onx-bot-a1b2c3d4-10`, where `run_id` is the test run identifier and `n` is the 1-indexed bot number), then **walk and jump** continuously for the run duration (waypoint wander; full A* pathfinding is opt-in, not default, for CPU reasons). This guarantees strict per-run account identification and prevents stale session collisions.
- Bot joins are **staggered** (default: 3 seconds between each bot joining, user-configurable via `LiveSettings.bot_join_stagger_seconds`) rather than simultaneous, to respect the server's `connection-throttle` and avoid login-burst false failures.
- The supervising runner records per-bot connect time, disconnects, server log readiness markers, and any `crash-reports/*.txt` appearance. **Pass = automated runtime sanity check passed (all required bots connected within the connect window and the server survived the full duration with no crash reports or unrecoverable disconnects). Fail = any bot unable to connect within the window, any mid-run disconnect the bot cannot recover from, container exit/crash during the run, or a crash-report file appearing.** Failure handling (halt, parse crash log via Feature 5, mark `FAILED`, surface failed-mod list) is unchanged from the prior model.

##### 3.5.2 Bot Technology Selection (Hybrid, per Mohamed Decision 1 & Sign-Off Item 6)
- **Primary: Mineflayer (Node.js, MIT, protocol-level).** Covers MC 1.8→26.1 (including 1.16.x–1.21.11), supports offline auth, runs headless with no GPU, and provides built-in movement physics (`setControlState('forward'/'jump')`). Works on **all** server types (vanilla, Paper, Forge, Fabric, NeoForge). Footprint ≈ 30–50 MB per bot. Caveat carried from RECON: brand-new MC drops lag Mineflayer releases by weeks–months (26.2 unreleased at time of writing), so the driver pins a minimum Mineflayer version per supported MC range and surfaces a clear error for unsupported brand-new protocols.
- **Complementary fast path: fakeplayer-next (Apache-2.0, server-side Paper/Purpur plugin).** Near-zero footprint; walk/jump via plugin commands. **Paper/Purpur-family only** — structurally incapable of verifying vanilla/Forge/Fabric servers, and it bypasses the real network login path, so it never replaces protocol-level verification where fidelity matters.
- **Selection logic (server-type-aware auto-resolution):** `bot_tech` per-run field with values `auto | mineflayer | fakeplayer_next` (default: `auto`, user-configurable). When `bot_tech=auto`, the system dynamically detects the test server's software type:
  - **Paper/Purpur-family servers** (`paper`, `purpur`, `folia`, `pufferfish`) $\rightarrow$ **auto-selects `fakeplayer_next`** (the fast, lightweight path with near-zero memory footprint and instantaneous startup).
  - **Any other server type** (`vanilla`, `forge`, `fabric`, `neoforge`, `spigot`, `bukkit`, etc., where `fakeplayer-next` cannot function) $\rightarrow$ **auto-selects `mineflayer`** (the universal protocol-level client with full protocol coverage).
  - *Rationale:* The priority is **speed-by-default wherever it is safe to do so**, while protocol-level fidelity is guaranteed as the seamless fallback for all server architectures where `fakeplayer-next` cannot function.
  - *Explicit overrides:* Users can still explicitly override `bot_tech`: setting `bot_tech=mineflayer` forces Mineflayer on any server type (including Paper/Purpur); setting `bot_tech=fakeplayer_next` on an unsupported server type (e.g. Forge, Fabric, Vanilla) fails validation immediately and clearly with `UNSUPPORTED_BOT_TECH_FOR_SERVER_TYPE`.
- **Drivers:** `MineflayerBotDriver` (spawns/manages Node Mineflayer processes against a host:port target, exposes uniform `BotRunHandle`: connect-all-staggered, tick-walk/jump, collect per-bot results) and `FakePlayerNextDriver` (installs the plugin jar into the *test directory only*, issues console `/fp` commands via RCON/`docker exec`, collects results through the same `BotRunHandle` interface). Both live in `backend/app/modules/versioning/` per §3.1.

##### 3.5.3 Offline-Mode Isolation Guarantee
- The test server **always** runs with `online-mode=false` **and** `enforce-secure-profile=false` (required on 1.19+; the production writer does not emit this line today) so simulated accounts connect without Mojang auth.
- **Mechanism (chosen): `TestServerDeployment` marker type.** A `TestServerDeployment` dataclass lives in `backend/app/modules/versioning/` and wraps a test-directory root path. The test-only properties writer (`write_test_server_properties()`, also in the versioning module) accepts **only** `TestServerDeployment` — it refuses a production `ServerDeployment` at the type level (no overload accepting it exists). *Justification for marker-type over writer-assertion:* a type boundary makes misuse a static/construct-time impossibility rather than a runtime branch that a future caller can bypass; it also keeps the marker importable without touching production modules.
- **CRITICAL DDD CONSTRAINT:** `TestServerDeployment`, `write_test_server_properties()`, and all bot/pool code live exclusively in the versioning module boundary. They must **not** be added to or imported by the production `ServerProvider` / `DockerProvider` / config-update code paths.
- **CRITICAL SAFETY CONSTRAINT (hard invariant, not a suggestion):** `UpdateServerConfigCommand` and every other production config writer must **never** be reachable from any test-run code path. Test runs write only into `.onx/tests/<test_id>/` via the test-only writer. The load-bearing test `test_bot_verification_offline_isolation.py` (§7) pins this invariant.
- Production `online_mode` values are never read as input to the test writer; the test file hardcodes `online-mode=false` + `enforce-secure-profile=false` regardless of the production setting.

##### 3.5.4 Bot-Runner Placement (Sidecar Default, per Mohamed Decision 3)
- **Default: separate dedicated sidecar container.** Bots run in a bot-runner container attached to the same bridge network as the test MC container, connecting via container address. Test MC ports stay unmapped. This matches the existing RCON loopback-discipline networking posture and isolates bot CPU/RAM from the JVM under test.
- **Opt-in alternative: in-container execution** (bot processes inside the test MC container, e.g. via `docker exec`), selectable **per test run** via `placement_mode: sidecar | in_container` (default: `sidecar`, user-configurable). In-container mode requires a bot-capable image variant and couples failure domains; it exists for constrained hosts that cannot afford a sidecar, not as a recommended path.
- The sidecar image (Node + pinned Mineflayer + driver harness) is versioned and pulled separately from the MC server image; `ensure_image()`-equivalent pre-pull semantics apply to it (see §3.5.5).

##### 3.5.5 BotRunnerPool (New Component, per Mohamed Decision 4 & Sign-Off Item 1)
A `BotRunnerPool` in `backend/app/modules/versioning/`, architecturally separate from `DockerProvider` (per §3.1 — it may invoke Docker CLI primitives but must not wrap or subclass the production provider):
- **Lifecycle:** `acquire(spec) -> PooledRunner` (healthy idle runner matching required bot image/tech, else create on demand) → `release(handle, outcome)` (return to idle on clean run; destroy-and-replace on any unhealthy signal) → periodic `health_check` (container running + harness heartbeat; failures evicted) → `evict` (idle TTL expiry or pool shrink). Pool state is in-memory with structured logging; no DB table required for pool membership (run records already live in `server_test_runs`).
- **Sizing:** default **2 warm idle sidecars + on-demand scale-up to 4 concurrent runners** (both bounds user-configurable via LiveSettings: `bot_pool_idle` default 2, `bot_pool_max` default 4). Rationale: test runs are already serialized per `server_id` (§6 lock), so a small pool covers the realistic concurrency of a self-hosted box.
- **State-reset between runs (no leakage):** pooled containers are treated as **compute-only shells** — bot working state (usernames, per-run scripts, logs) is bind-mounted per run from `.onx/tests/<test_id>/bots/` and unmounted on release; on release the pool executes a reset entrypoint (kill bot processes, clear mount point, verify heartbeat) before the runner returns to idle. If reset fails, the container is destroyed and replaced rather than reused. Per-run bot usernames follow the `onx-bot-{run_id}-{n}` pattern so a stale session can never be mistaken for a current-run bot.
- **Coexistence with placement choice & pool bypass:** pooled runners serve `sidecar` runs only. `in_container` runs bypass the pool entirely (bots execute inside the test MC container). `FakePlayerNextDriver` runs need no runner container at all (plugin executes in the test MC container) and likewise bypass the pool.
  - *(inferred from Mohamed's decisions, confirm)*: When `bot_tech=auto` resolves to `fakeplayer_next` on Paper/Purpur servers, `BotRunnerPool` is bypassed completely since the bot plugin runs inside the test server container itself, requiring zero sidecar containers and allocating zero pool resources for that run.

##### 3.5.6 Config Surface: Layered Bot Count / Duration (per Mohamed Decision 5 & Sign-Off Items 2, 3, 5, 10)
Layering `(a) → (b) → (c)`, later wins, each layer optional except the global default:
- **(a) Global default** — `LiveSettings.bot_verify_defaults: {bot_count: 10, duration_minutes: 15, bot_tech: "auto", placement_mode: "sidecar", join_stagger_seconds: 3, connect_grace_seconds: 60, watchdog_overrun_minutes: 5}` (YAML-overridable, hot-reloadable, following the `post_running_grace_seconds` precedent; all values user-configurable defaults).
- **(b) Per-server override** — stored in a new JSON column `bot_verification_settings` on the `servers` table (nullable, default `null`: `{"bot_count": int | null, "duration_minutes": int | null, "bot_tech": str | null, "placement_mode": str | null}`). A `null` value or omitted key inherits the global default.
- **(c) Per-test-run override** — `RunIsolatedTestCommand` / `server_test_runs` fields `bot_count`, `duration_minutes`, `placement_mode`, `bot_tech`; provided values win.
- **No Numeric Ceilings / Unrestrictive User Control:** There are **no artificial numeric clamps or ceilings** on `bot_count` or `duration_minutes` (the previously proposed 1–20 bots / 1–30 min bounds are removed entirely). The user may set any bot count or duration value without arbitrary restriction. `ResourcePreflightProbe` (§3.5.7) serves as the **sole guard** — it warns and can block only when actual measured RAM and CPU headroom is insufficient for the requested workload, never based on an arbitrary numeric limit.
  - *Rationale:* This directly preserves ONX Manager's core philosophy of remaining **simple and unrestrictive for the user** — the platform advises and protects based on real physical resource constraints rather than imposing artificial arbitrary caps.
  - *Stagger interval:* Bot joins are staggered (default: 3 seconds between joins, user-configurable via `LiveSettings.bot_join_stagger_seconds`; total join stagger is capped so it never consumes more than ~10% of total run duration).

##### 3.5.7 Preflight Resource Check (Sole Guard, per Sign-Off Item 4)
- Before a bot run starts, a **`ResourcePreflightProbe`** (modeled directly on `StorageCapabilityProbe`'s probe → actionable-failure pattern) verifies headroom for the resolved configuration: default floor **4 GB free RAM and 2 free CPU cores for a 10-bot run + test server** (user-configurable via LiveSettings: `bot_resource_floor_mb` default 4096, `bot_resource_floor_cores` default 2, scaling proportionally with configured bot count; modded server types raise the floor), beyond whatever the production server currently consumes.
- **Actionable failure mode:** on insufficient headroom the run is rejected *before* any container starts with error code `BOT_RUN_INSUFFICIENT_RESOURCES` and a message stating required vs available headroom; the rest of the platform (including production servers and non-bot versioning reads) is unaffected. The probe result is recorded on the `server_test_runs` row.

##### 3.5.8 Success / Failure Detection (Bot-Run Equivalent, per Sign-Off Item 8)
- **Pass (Automated Runtime Sanity Check Passed):** required bot count connected (within a connect window scaled to `count × stagger + grace_window`; default grace: 60s, user-configurable via `LiveSettings.bot_connect_grace_seconds`) and the server survived the full duration with no crash-report files and no unrecoverable bot disconnects. This confirms runtime stability and crash-free operation under simulated player load.
- **Fail (same downstream flow as before — halt, Feature 5 crash-log parse, mark `FAILED`, surface failed-mod list):** container exit/crash mid-run; readiness never achieved (bots cannot connect within the window — this is how boot failure manifests, no separate probe needed); `crash-reports/*.txt` appears; JVM fatal exit codes; mod-rejection exceptions in container logs.
- A **run-level watchdog** (default: configured duration + 5-minute overrun cap, user-configurable via `LiveSettings.bot_watchdog_overrun_minutes`) bounds hangs: if a run exceeds its configured duration by more than the overrun cap without completing, the watchdog force-terminates it as stalled/failed, marks the run `FAILED` with reason `BOT_RUN_TIMEOUT`, and releases pooled runners via the unhealthy path.

#### 3.6 Atomic Promotion & Rollback Paths
- **Promote:**
  1. Stop production server gracefully (`StopServerCommand`).
  2. Stage manifest configs/mods in sibling directory; swap into live directory using `_atomic_replace_dir`.
  3. If admin opted to keep world changes made during the bot run, atomically swap the test world into live. Otherwise, preserve existing live world.
  4. Restart production server (`StartServerCommand`).
  5. Delete ephemeral test container and directory.
- **Rollback / Discard:**
  1. Stop and destroy test container `onx-test-<test_id>`; terminate or release its bot-runner sidecar (dedicated sidecars are removed; pooled runners are reset and released to `BotRunnerPool`).
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
  - Domain: `ServerCommit`, `ServerBranch`, `ServerWorldSnapshot`, `ServerTestRun`, `TestRunStatus`, `BotVerificationConfig` (resolved bot_count/duration/placement/bot_tech for a run), `TestServerDeployment` (test-only deployment marker, §3.5.3).
  - Application: `CreateCommitCommand`, `CreateBranchCommand`, `RunIsolatedTestCommand` (extended with `bot_count`, `duration_minutes`, `placement_mode`, `bot_tech` overrides), `PromoteCommitCommand`, `DiscardTestCommand`, `GetCommitHistoryQuery`, `GetTestStatusQuery`.
  - Infrastructure: `SQLVersioningRepository`, `BtrfsZfsSnapshotDriver`, `StorageCapabilityProbe`, `DockerTestExecutionRunner`, `BotRunnerPool`, `MineflayerBotDriver`, `FakePlayerNextDriver`, `ResourcePreflightProbe`, `write_test_server_properties` (test-only properties writer accepting only `TestServerDeployment`).
- **Frontend New Module:** `frontend/src/server_manager/pages/ServerVersioningPage.tsx` and `TestRunModal.tsx` (TestRunModal carries bot count/duration/placement/tech controls with preflight resource-headroom feedback and unrestrictive user inputs without arbitrary numeric upper bounds).

### 5. Interfaces & Contracts
- **Permissions (`contracts/permissions.yaml`):**
  - `server:version:read` — View commit history and branches.
  - `server:version:commit` — Create commits / branches.
  - `server:test:execute` — Trigger and interact with test containers.
  - `server:test:configure` — Change bot verification settings (global/per-server bot count, duration, placement, pool bounds). Explicitly separated from `server:test:execute` so server owners can delegate routine test runs to operators without granting permission to alter cost-driving or resource-intensive configuration.
  - `server:version:promote` — Promote test state to live production.
- **Database Schema (Alembic migrations `add_server_versioning_tables` & `add_bot_verification_settings_to_servers`):**
  - `server_branches`: `(id, server_id, name, head_commit_id, created_at)`
  - `server_commits`: `(id, server_id, branch_id, parent_commit_id, author_id, message, manifest_json, world_snapshot_id, created_at)`
  - `server_world_snapshots`: `(id, server_id, storage_path, size_bytes, created_at)`
  - `server_test_runs`: `(id, server_id, commit_id, node_id, status, ephemeral_port, log_output, failure_reason, created_at, expires_at, bot_count, duration_minutes, placement_mode, bot_tech)`
  - `servers.bot_verification_settings`: New nullable JSON column on the core `servers` table (capturing per-server overrides: `bot_count`, `duration_minutes`, `bot_tech`, `placement_mode`) without requiring auxiliary policy tables.
- **Settings (`LiveSettings`/YAML):** All values are user-configurable defaults:
  - `bot_verify_defaults`: `{bot_count: 10, duration_minutes: 15, bot_tech: "auto", placement_mode: "sidecar"}`
  - `bot_pool_idle`: `2` (warm idle sidecars)
  - `bot_pool_max`: `4` (maximum concurrent sidecars)
  - `bot_pool_acquire_retries`: `2` (retries before declaring acquisition failed)
  - `bot_resource_floor_mb`: `4096` (RAM headroom floor for a 10-bot run)
  - `bot_resource_floor_cores`: `2` (CPU cores headroom floor for a 10-bot run)
  - `bot_join_stagger_seconds`: `3` (seconds between bot joins)
  - `bot_connect_grace_seconds`: `60` (connect grace window)
  - `bot_watchdog_overrun_minutes`: `5` (overrun cap before watchdog termination)

### 6. Failure Cases & Edge Cases
- **Non-Btrfs/ZFS Filesystem:** Detected via `StorageCapabilityProbe` preflight. Returns `412 Precondition Failed`; UI displays clear requirement; live servers unaffected.
- **World-State Divergence on Rollback-After-Live-Update:** If a promoted update runs in production for days and the admin later decides to roll back to a prior commit:
  - System enforces a mandatory choice:
    1. *Config & Mods Only Rollback (Default & Recommended):* Reverts configs and mods to prior commit; keeps current live world intact (prevents destroying player builds).
    2. *Full Rollback (Destructive):* Reverts configs, mods, and world back to the pre-update snapshot. Displays a double-confirmation modal warning of permanent player progress loss, and creates an automatic safety backup before executing.
- **Bot Run Hang or Crash:** run-level watchdog (default: duration + 5-minute overrun cap, user-configurable via `LiveSettings.bot_watchdog_overrun_minutes`) force-stops containers and marks the run `FAILED` with `BOT_RUN_TIMEOUT`. A test MC container that exits mid-run fails the run immediately; logs are captured, `docker rm -f` executes, same `FAILED` + failed-mod flow as before.
- **Unhealthy Pooled Runner at Acquire:** `BotRunnerPool` health-check failures evict the container (destroy + replace); acquisition retries against another pooled or freshly-spun container up to a bounded retry count (default: 2 retries, user-configurable via `LiveSettings.bot_pool_acquire_retries`) before failing the run with `BOT_RUNNER_UNAVAILABLE`. A run never starts on a runner that failed its pre-acquire heartbeat.
- **Resource Preflight Failure:** run rejected before any container starts (`BOT_RUN_INSUFFICIENT_RESOURCES`, required-vs-available message); platform otherwise unaffected.
- **Offline-Mode Write Against Live Deployment:** structurally impossible — `write_test_server_properties()` accepts only `TestServerDeployment`, which cannot reference a production path. If the assertion ever fires (defense in depth), the run aborts pre-start with `TEST_ISOLATION_VIOLATION`, an error is logged with full context, and no container is launched.
- **Concurrent Test Runs:** A Redis/asyncio lock per `server_id` rejects overlapping test runs with `ConflictError("A test run is already active for this server.")`.

### 7. Tests & Verification
- `test_storage_capability_probe.py`: Unit tests verifying reflink detection on supported vs unsupported filesystems.
- `test_versioning_manifest.py`: Unit tests for commit manifest generation, hashing, and parentage.
- `test_btrfs_zfs_snapshot_driver.py`: Reflink cloning mocked and live execution tests.
- `test_isolated_test_runner.py`: Container lifecycle, timeout enforcement, and log scraping, **extended to cover the bot phase** (bot-run start/stop around the container lifecycle, watchdog expiry, per-bot result collection).
- `test_bot_runner_pool.py`: Pool acquire/release/evict/health-check semantics; unhealthy-runner replacement; idle-TTL eviction; state-reset verification (no per-run artifacts survive release).
- `test_bot_verification_offline_isolation.py` (load-bearing for §3.5.3): asserts a test run writes `online-mode=false` + `enforce-secure-profile=false` only under `.onx/tests/<test_id>/`; asserts `write_test_server_properties()` rejects a production `ServerDeployment` (type-level); asserts no test-run code path imports or invokes `UpdateServerConfigCommand` (import-graph assertion); asserts production `server.properties` byte-identical before/after a full simulated run.
- `test_bot_verification_config_layering.py`: Global → per-server → per-run layering precedence; verification that bot_count and duration_minutes have no arbitrary numeric ceilings; unrestrictive high-count/duration acceptance subject solely to ResourcePreflightProbe; invalid bot_tech/placement_mode validation (including fakeplayer_next on non-Paper types); server-type-aware auto bot_tech resolution and pool bypass logic.
- `test_resource_preflight_probe.py`: Sufficient/insufficient headroom paths; `BOT_RUN_INSUFFICIENT_RESOURCES` code and message content; platform-unaffected guarantee.
- `test_promote_and_rollback.py`: Atomic promotion, directory swapping, and rollback isolation (now including bot-runner sidecar release/removal on discard).

### 8. Out of Scope
- Actual remote multi-node clustering or distributed test workers (groundwork abstraction only).
- Human play-test windows (replaced by bot verification; no ephemeral-port admin join flow).
- GPU-accelerated or client-mod bots (Baritone-class tooling requires a game client and is excluded).

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
| **1. Scope & System Complexity** | **PASS WITH CAVEATS** | Feature 1 remains strictly standalone and decoupled from `ServerProvider`, Feature 2 is cleanly merged, and multi-node remains an interface groundwork. However, introducing `BotRunnerPool` alongside two bot drivers (`Mineflayer` Node.js sidecar and `fakeplayer-next` plugin) substantially expands control-plane operational surface. Implementing, monitoring, and debugging a container-pool lifecycle with dynamic driver resolution is non-trivial maintenance overhead for a solo-maintained project. |
| **2. Architecture & DDD Boundaries** | **PASS** | Hexagonal boundaries preserved. Dedicated `versioning` and `activity` modules maintain clear CQRS separation. The `TestServerDeployment` marker type provides compile/type-time enforcement preventing offline-mode mutations from leaking into production config paths. |
| **3. Storage & Resource Floor** | **PASS WITH CAVEATS** | Btrfs/ZFS is an absolute prerequisite enforced by `StorageCapabilityProbe` (hosts on ext4/NTFS cannot use versioning, though regular management remains unaffected). However, operational cost is real and non-zero: the 4 GB RAM / 2 CPU cores resource floor means bot verification will be frequently blocked by `ResourcePreflightProbe` on resource-constrained self-hosted boxes or low-tier VPS instances. |
| **4. Verification Fidelity vs Sanity Scope** | **NEEDS ATTENTION** | A 10-bot / 15-minute synthetic-player run demonstrates boot, network connect, and survival stability under wandering load. However, it is fundamentally an **automated runtime sanity / smoke check**, NOT proof of plugin business logic correctness, redstone integrity, mod balance, or gameplay correctness under real player load. Documentation and UI labels must explicitly present this as "runtime sanity check passed" to avoid misleading administrators into false confidence before promoting updates. |
| **5. Proven Primitives & Container Upkeep** | **PASS WITH CAVEATS** | Reuses proven `restore_service.py` directory swapping and Docker label/volume cleanup primitives. However, pool container upkeep (default 2 idle warm sidecars) imposes continuous baseline memory consumption even when no test runs are active. Idle containers risk memory bloat or stalled heartbeats over prolonged server uptimes if pool eviction and health check intervals are not aggressively tuned. |
| **6. Contracts & Permissions** | **PASS** | Permission granularity is properly safeguarded (`server:test:configure` vs `server:test:execute`), preventing unauthorized resource consumption. Storing per-server overrides in a nullable JSON column on `servers` avoids relational schema proliferation while preserving all 5 CI quality gates. |
| **7. Edge Cases & Resilience** | **PASS** | Edge cases are comprehensively mapped: watchdog overrun timer terminates stalled runs; acquire retries against fresh containers on heartbeat failure; typed markers prevent offline-mode leaks; rollback divergence provides explicit config-only vs full rollback choices. |

---

## Open Decisions for Mohamed's Review & Approval

The following specific recommendations are submitted for Mohamed's explicit sign-off:
1. **Mod Support Scope (Feature 3):** Support BOTH direct custom `.jar` uploads AND unblocked Modrinth catalog search for modded servers; display non-blocking warning badge for client-only mods. *(Recommended)*
2. **Activity Storage (Feature 4):** Persist in a dedicated query-optimized `server_activity_logs` table rather than the cryptographic security `audit_log` hash chain. *(Recommended)*
3. **Log Transport (Feature 5):** WebSocket streaming for live console with HTTP query fallback for initial history and offline fallback to `latest.log`. *(Recommended)*
