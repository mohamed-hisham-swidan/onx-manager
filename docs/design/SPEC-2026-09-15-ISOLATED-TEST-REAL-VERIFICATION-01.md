# Design Spec: Make Isolated Test Verification Real (Batch)

**Document Status:** DRAFT FOR DESIGN REVIEW  
**Governance Classification:** Decision Level D1 (Significant) / Lane A (Release Critical)  
**Governing Authority:** `docs/governance/GOVERNANCE.md` §4–5, §12; `Orchestrator.md §5`  
**Spec Identifier:** `SPEC-2026-09-15-ISOLATED-TEST-REAL-VERIFICATION-01`  
**Author:** Antigravity (Design Agent)  
**Date:** 2026-09-15  

---

## 1. Goal

Transform the stubbed isolated test runner into a real, automated verification engine that executes real bot clients against copy-on-write (COW) Minecraft containers, persists authentic outcomes to the database, strictly gates commit promotions behind successful verification, guarantees test container player capacity headroom, surfaces live test status and polling in the user interface, and displays clear software/loader badges across server management views.

### Concrete Objectives
1. **Real Subprocess Bot Execution:** Replace simulated sleeps and fabricated results in `_execute_verification` with real asynchronous subprocess execution (Node.js/Mineflayer harness and FakePlayer-Next for Paper), stdout/stderr streaming with capped log capture (64KB), and robust process-tree termination on timeout or cancellation via `platform_kill_process_tree_async`.
2. **Authoritative Outcome Persistence:** Ensure background test execution opens a dedicated database session to persist terminal `TestResult` outcomes (`PASSED`, `FAILED`, `CANCELLED`) to `server_test_runs` using the resilient SQLite busy-retry pattern. Clarify in-memory state as an in-flight execution handle cache only.
3. **Strict Promotion Gating:** Modify `promote_commit.py` to strictly reject promoting any commit whose associated test run has not passed verification (returning HTTP 400 with a descriptive domain error), define an unambiguous matching rule for commit-test association, and provide an audited administrative bypass (`force=True`).
4. **Isolated Test-Container Max-Players Guarantee:** Update `config_writer.py` so test container `server.properties` automatically scales `max-players` to accommodate the configured bot count plus safety headroom, preventing spurious `Server is full` connection rejections without altering production properties.
5. **Loader & Protocol Compatibility Strategy:** Address protocol differences across Minecraft versions (1.16 through 1.21+) and loaders (Paper, Fabric, Forge, NeoForge, Vanilla) with a preflight compatibility matrix and graceful fallback to container boot/sanity verification (Smoke Test) when bot protocol negotiation is unavailable.
6. **Test-Run Visibility & Frontend Polling:** Introduce a dedicated `GET /api/v1/servers/{server_id}/versioning/tests` endpoint with pagination and permission mapping (`server:version:read`), and implement conditional 3-second polling in `ServerVersioningPage.tsx` while active test runs are pending or running.
7. **Software & Loader Badges (F2):** Create a shared `LoaderBadge` component and integrate it into server cards (`ServersPage.tsx`), dashboard lists (`DashboardServerList.tsx`), and the server detail header (`ServerDetailPage.tsx`), mapping server types (`paper`, `purpur`, `fabric`, `forge`, `neoforge`, `vanilla`) to distinct visual styles.

---

## 2. Current Behavior & Root Cause Analysis

### 2.1 Forensic Confirmation of Current Limitations

Forensic analysis of the completed RECON and live codebase reveals that while the COW filesystem cloning (Btrfs/Zfs reflink) and test container startup function correctly, the actual verification pipeline is stubbed and decoupled from persistence and promotion:

```
[User triggers POST /api/v1/servers/{id}/versioning/tests]
  │
  ├─ 1. RunIsolatedTestHandler records ServerTestRun in DB with status = "RUNNING".
  ├─ 2. DockerTestExecutionRunner.run_test() launches container: onx-test-{test_id}.
  ├─ 3. Spawns background task: asyncio.create_task(_execute_verification(...)).
  │      │
  │      ├─ 4. Writes runner.js (Mineflayer) or fakeplayer-next.jar placeholder.
  │      ├─ 5. CRITICAL GAP: Calls await asyncio.sleep(min(duration_s, 1.0)).
  │      ├─ 6. Hardcodes passed = True and connected_bots = bot_cfg.bot_count!
  │      ├─ 7. Calls handle.set_result(result) on an internal asyncio.Future.
  │      └─ 8. CRITICAL GAP: NEVER updates the database row!
  │
[User polls GET /api/v1/servers/{id}/versioning/tests/{test_id}]
  │
  └─ 9. GetTestStatusHandler queries DB → returns status = "RUNNING" forever!

[User triggers POST /api/v1/servers/{id}/versioning/tests/{test_id}/promote]
  │
  ├─ 10. PromoteCommitHandler fetches test_run from DB.
  └─ 11. CRITICAL GAP: Promotes commit immediately without checking test_run.status!
         Even a FAILED, RUNNING, or CANCELLED test run can overwrite production!
```

### 2.2 Detailed Gap Summary

1. **Stubbed Execution (`test_runner.py:266, 291`):**
   - For FakePlayer-Next: Writes a placeholder jar (`PK\x03\x04fakeplayer-next-placeholder`), logs a message, sleeps $\le 1.0\text{s}$, and marks `passed = True`.
   - For Mineflayer: Writes `package.json` and `runner.js`, acquires a pooled sidecar container or falls back to simulation, sleeps $\le 1.0\text{s}$, and marks `passed = True`. No Node.js process is spawned.
2. **Outcome Persistence Gap (`test_runner.py:320-338`):**
   - In the `finally` block of `_execute_verification`, `handle.status` and `handle._completion_future` are updated in memory, and the test is popped from `self._active_runs`.
   - `_execute_verification` has no reference to `VersioningRepository` or the database session factory. It never calls `save_test_run()`. Consequently, `server_test_runs.status` remains `RUNNING` in SQLite indefinitely.
3. **Missing Promotion Gating (`promote_commit.py:91-100`):**
   - `PromoteCommitHandler._execute` fetches the `test_run` row and `commit` row, verifies server ownership, and immediately begins stopping the production server and copying manifest configs, mods, and world directories.
   - It performs zero verification that `test_run.status == TestRunStatus.PASSED`.
4. **Test-Container Max Players Rejection (`config_writer.py:40-60`):**
   - `write_test_server_properties` copies `base_properties` without inspecting `bot_count`. If production has `max-players=20` and the test runs 25 bots, the server rejects connections with `The server is full!`.
5. **No Test Runs List Endpoint (`backend/app/api/v1/routers/versioning.py`):**
   - The API provides `GET /tests/{test_id}` but no `GET /tests` endpoint.
   - `SQLVersioningRepository.list_test_runs(server_id, limit)` already exists in code, but has no CQRS Query, QueryHandler, or HTTP router exposure.
6. **Frontend State Disconnection (`ServerVersioningPage.tsx:20, 60-70`):**
   - `const [testRuns, setTestRuns] = useState<ServerTestRun[]>([])` is initialized to an empty array and never updated from the backend. The UI always displays `"No isolated test runs active or recorded."` unless a test was triggered in that exact local render cycle.
   - No polling mechanism exists to refresh running test runs.
7. **Software/Loader Badge Absent from Server Views:**
   - Server lists (`ServersPage.tsx`), dashboard widgets (`DashboardServerList.tsx`), and detail views (`ServerDetailPage.tsx`) display `minecraft_version` and provider badges, but lack visual distinction for server loaders (`Paper`, `Fabric`, `Forge`, etc.), despite `server_type` already being provided in `ServerResponse`.

---

## 3. Proposed Change

### 3.1 Component 1: Real Bot Subprocess Execution Engine

Refactor `DockerTestExecutionRunner._execute_verification` in `backend/app/modules/versioning/infrastructure/test_runner.py` and enhance `bot_drivers.py` to execute real bot clients.

#### 3.1.1 Mineflayer Execution Driver
- **Process Spawning:** In `MineflayerBotDriver`, execute Node.js via `asyncio.create_subprocess_exec` within the `test_dir / "bots"` directory:
  ```python
  cmd = ["node", "runner.js"]
  env = {
      **os.environ,
      "MC_HOST": container_ip,
      "MC_PORT": str(spec.bot_config.ephemeral_port or 25565),
      "BOT_RUN_ID": spec.test_id[:8],
      "BOT_COUNT": str(spec.bot_config.bot_count),
      "BOT_DURATION_MS": str(int(spec.bot_config.duration_minutes * 60 * 1000)),
      "BOT_STAGGER_MS": str(int(spec.bot_config.join_stagger_seconds * 1000)),
  }
  process = await asyncio.create_subprocess_exec(
      *cmd,
      cwd=str(bot_dir),
      env=env,
      stdout=asyncio.subprocess.PIPE,
      stderr=asyncio.subprocess.STDOUT,
  )
  ```
- **Execution Placement:**
  - `PlacementMode.SIDECAR`: When a pooled runner container is available from `BotRunnerPool`, run inside the sidecar using `docker exec -d ...` or direct bridge network access.
  - `PlacementMode.LOCAL_HOST` (Default fallback): When sidecars are disabled or unavailable, execute `node` directly on the host targeting the test container's Docker bridge IP (`container_ip:25565`).
- **Real-Time Stream Capture & Output Capping:** Read stdout/stderr asynchronously in chunks. Append log lines to an in-memory buffer capped at 64 KB (65,536 bytes). If output exceeds 64 KB, preserve the first 4 KB (startup diagnostics) and the trailing 60 KB, with a clear `[... truncated X bytes ...]` marker.
- **Process Tree Watchdog & Timeout Termination:**
  - Total allowable run time = `duration_minutes * 60 + connect_grace_seconds`.
  - On timeout expiry or `asyncio.CancelledError`:
    Invoke `await platform_kill_process_tree_async(process.pid)` (from `app.core.process_utils`) to terminate the Node process and any spawned child threads cleanly.
  - If the process does not terminate within 5 seconds, invoke `platform_force_kill(process.pid)`.
- **Pass / Fail Determination Criteria:**
  Verification is marked `PASSED` if and only if:
  1. The bot subprocess exits with return code `0`.
  2. Stdout confirms bot connections (e.g. `[BOT-HARNESS] Bot #... spawned successfully`).
  3. No crash reports were generated in `test_dir / "crash-reports"`.
  4. The test server container remained in running status throughout the test duration.

#### 3.1.2 FakePlayer-Next Paper Complementary Driver
- For Paper/Purpur servers selecting `BotTech.FAKEPLAYER_NEXT`:
  1. Copy verified `fakeplayer-next.jar` binary into `test_dir / "plugins"`.
  2. Tail `test_dir / "logs" / "latest.log"` until the Minecraft server emits `Done (X.XXs)!` (up to a 90-second boot timeout).
  3. Execute spawn commands via RCON using the container's RCON CLI or internal client:
     `docker exec <container_name> rcon-cli fp spawn onx-bot-<run_id>-<n>`.
  4. Poll player list via RCON (`list`) at periodic intervals to verify bot persistence throughout the test duration.

---

### 3.2 Component 2: Outcome Persistence & In-Flight State Invariants

#### 3.2.1 Transactional Persistence in Background Tasks
`DockerTestExecutionRunner._execute_verification` must persist final status to SQLite via a fresh database session:

```python
async def _persist_test_run_outcome(
    self,
    test_id: str,
    passed: bool,
    failure_reason: str | None,
    log_output: str,
) -> None:
    from app.core.persistence.db import database
    from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with database.session_factory() as session:
                repo = SQLVersioningRepository(session)
                run = await repo.get_test_run(test_id)
                if run:
                    if passed:
                        run.mark_passed(log_output=log_output)
                    else:
                        run.mark_failed(
                            reason=failure_reason or "Verification failed",
                            log_output=log_output,
                        )
                    await repo.save_test_run(run)
                    await session.commit()
            break
        except Exception as exc:
            is_lock = "locked" in str(exc).lower() or "busy" in str(exc).lower()
            if is_lock and attempt < max_retries - 1:
                await asyncio.sleep(0.05 * (2**attempt))
                continue
            logger.exception("Failed to persist test run outcome for %s: %s", test_id, exc)
            break
```

#### 3.2.2 In-Flight State Architecture
- `self._active_runs: dict[str, TestHandle]` in `DockerTestExecutionRunner` is designated strictly as an **in-flight runtime handle cache** (holding subprocess PIDs, Docker container handles, and cancellation events).
- `_active_runs` is NOT an authoritative record of test history. Once a test completes (or crashes), its terminal outcome is persisted to SQLite, and its entry is removed from `_active_runs`.
- On application restart, any tests found in SQLite with status `RUNNING` or `PENDING` whose Docker containers no longer exist are reconciled to `FAILED` with failure reason: `"Test run aborted due to server restart"`.

---

### 3.3 Component 3: Promote Gating & Bypass Mechanism

#### 3.3.1 Strict Verification Enforcement in `promote_commit.py`
In `backend/app/modules/versioning/application/commands/promote_commit.py`:

```python
# Validation: Verify test run status
test_run = await versioning_repo.get_test_run(command.test_id)
if test_run is None or test_run.server_id != command.server_id:
    raise NotFoundError(f"Test run '{command.test_id}' not found for server '{command.server_id}'")

if not command.force:
    if test_run.status != TestRunStatus.PASSED:
        raise ValidationError(
            f"Cannot promote commit '{test_run.commit_id}': Test run '{test_run.id}' "
            f"has status '{test_run.status.value}'. Only PASSED test runs can be promoted to production."
        )

    # Invalidation check: Ensure no subsequent test run for this commit has failed
    recent_runs = await versioning_repo.list_test_runs(command.server_id, limit=20)
    newer_failing_runs = [
        r for r in recent_runs
        if r.commit_id == test_run.commit_id
        and r.created_at > test_run.created_at
        and r.status == TestRunStatus.FAILED
    ]
    if newer_failing_runs:
        raise ValidationError(
            f"Cannot promote commit '{test_run.commit_id}': A subsequent test run "
            f"('{newer_failing_runs[0].id}') failed for this commit. Re-verify the commit before promoting."
        )
```

#### 3.3.2 Administrative Force Bypass
- Add `force: bool = False` to `PromoteCommitCommand` and `PromoteCommitRequest`.
- Authorization: Requires permission `server:version:promote` (or elevated `server:version:promote:force`).
- Audit Trail: When `force=True`, emit `CommitPromotedEvent(..., forced=True)` and log an entry to `ServerActivityLog` (Phase 4 Feature 4) explicitly documenting the administrative bypass and user ID.

---

### 3.4 Component 4: Test-Container Max-Players Scaling

In `backend/app/modules/versioning/infrastructure/config_writer.py`:
- Update `write_test_server_properties` signature to accept `bot_count: int = 10`.
- Automatically ensure `max-players` is set to at least `bot_count + 5`:
  ```python
  base_max = 20
  if base_properties and "max-players" in base_properties:
      try:
          base_max = int(base_properties["max-players"])
      except (ValueError, TypeError):
          base_max = 20

  required_max = max(base_max, bot_count + 5)
  props["max-players"] = str(required_max)
  ```
- **Strict Isolation Invariant:** This modification applies exclusively to the isolated test directory (`.onx/tests/<test_id>/server.properties`). When `promote_commit.py` promotes the commit, it restores `manifest.configs["server.properties"]` to the production server directory, ensuring production `max-players` is never unintentionally increased.

---

### 3.5 Component 5: Loader & Protocol Compatibility Matrix (B1 Follow-up)

#### 3.5.1 Compatibility Matrix
| Loader / Server Type | Minecraft Version | Recommended Bot Tech | Fallback Strategy |
|---|---|:---:|---|
| **Paper / Purpur** | 1.16 – 1.21.x | `FakePlayer-Next` | Direct console command injection; protocol-agnostic. |
| **Vanilla** | 1.16 – 1.20.4 | `Mineflayer` | Full bot protocol verification. |
| **Vanilla** | 1.20.5 – 1.21+ | `Mineflayer` (w/ 1.21 packet support) | Degraded / Fallback to Smoke Test if handshake fails. |
| **Fabric / Quilt** | 1.16 – 1.20.4 | `Mineflayer` | Full bot protocol verification. |
| **Fabric / Quilt** | 1.20.5 – 1.21+ | `Mineflayer` | Fallback to Smoke Test if handshake rejected. |
| **Forge / NeoForge** | All versions | `Mineflayer` (Offline mode) | Fallback to Smoke Test if custom mod handshake required. |

#### 3.5.2 Graceful Degradation: Smoke Test Verification Mode
If a server's loader or modded handshake cannot be negotiated by bot drivers:
1. The preflight check informs the user that full bot simulation is unsupported for this loader/version combination.
2. The user may opt into **Smoke Test Mode** (Container Boot & World Sanity Verification):
   - Launches isolated test container with COW cloned world.
   - Waits for server to emit `Done (X.XXs)!` in `latest.log`.
   - Monitors container for 60 seconds.
   - Verifies no crash reports are generated in `crash-reports/`.
   - Persists test result with status `PASSED` and diagnostic note: `[VERIFY-MODE: SMOKE_TEST] Container booted and world loaded cleanly. Bot connection skipped.`

---

### 3.6 Component 6: Test-Run Visibility, Query Endpoint & Polling

#### 3.6.1 Backend Query & Endpoint
- Add `GetServerTestRunsQuery(server_id: str, limit: int = 50)` and `GetServerTestRunsHandler` to `backend/app/modules/versioning/application/queries/get_server_test_runs.py`.
- Expose `GET /api/v1/servers/{server_id}/versioning/tests` in `backend/app/api/v1/routers/versioning.py`:
  ```python
  @router.get("/tests", response_model=list[TestRunResponse])
  async def list_test_runs(
      server_id: str,
      query_bus: Annotated[QueryBus, Depends(get_query_bus)],
      _current_user: Annotated[dict, Depends(require_permission("server:version:read"))],
      limit: int = Query(default=50, ge=1, le=100),
  ) -> list[TestRunResponse]:
      data = await query_bus.ask(GetServerTestRunsQuery(server_id=server_id, limit=limit))
      return [TestRunResponse(**item) for item in data]
  ```
- Register permission in `contracts/permissions.yaml`:
  `"GET /api/v1/servers/{server_id}/versioning/tests": {permission: "server:version:read", status: enforced}`

#### 3.6.2 Frontend Polling & State Management
- Add `getServerTestRuns(serverId: string, limit?: number)` to `frontend/src/services/api.ts`.
- In `ServerVersioningPage.tsx`:
  - Fetch test runs on initial mount alongside branches and commits.
  - Implement dynamic polling:
    ```typescript
    const hasActiveRuns = useMemo(
      () => testRuns.some((r) => r.status === "RUNNING" || r.status === "PENDING"),
      [testRuns]
    );

    useEffect(() => {
      if (!hasActiveRuns || !serverId) return;
      const interval = setInterval(async () => {
        try {
          const runs = await api.getServerTestRuns(serverId);
          setTestRuns(runs);
        } catch {
          // Silent catch on background polling error
        }
      }, 3000);
      return () => clearInterval(interval);
    }, [hasActiveRuns, serverId, api]);
    ```
  - Update the "Promote to Live" button in the test runs table to be enabled strictly when `run.status === "PASSED"`.
  - Add a "View Logs" modal to inspect the 64 KB captured test run output.

---

### 3.7 Component 7: Software & Loader Badge (F2 Follow-up)

Extract and standardize `LoaderBadge` into a reusable UI component:  
`frontend/src/components/ui/LoaderBadge.tsx`

#### 3.7.1 Loader Style Registry
```typescript
interface LoaderBadgeProps {
  loader?: string | null;
  className?: string;
  size?: "sm" | "md";
}

const LOADER_STYLES: Record<string, { label: string; icon: IconName; classes: string }> = {
  paper: { label: "Paper", icon: "server", classes: "bg-teal-50 text-teal-700 border-teal-200 dark:bg-teal-950/50 dark:text-teal-300 dark:border-teal-800" },
  purpur: { label: "Purpur", icon: "server", classes: "bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-950/50 dark:text-purple-300 dark:border-purple-800" },
  fabric: { label: "Fabric", icon: "fabric", classes: "bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-950/50 dark:text-sky-300 dark:border-sky-800" },
  forge: { label: "Forge", icon: "forge", classes: "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/50 dark:text-amber-300 dark:border-amber-800" },
  neoforge: { label: "NeoForge", icon: "neoforge", classes: "bg-orange-50 text-orange-700 border-orange-200 dark:bg-orange-950/50 dark:text-orange-300 dark:border-orange-800" },
  vanilla: { label: "Vanilla", icon: "cube", classes: "bg-gray-100 text-gray-700 border-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-700" },
  spigot: { label: "Spigot", icon: "server", classes: "bg-yellow-50 text-yellow-700 border-yellow-200 dark:bg-yellow-950/50 dark:text-yellow-300 dark:border-yellow-800" },
};
```

#### 3.7.2 Placements
1. **`ServersPage.tsx`:** In the server table row, render `<LoaderBadge loader={s.server_type} />` directly adjacent to `{s.minecraft_version}`.
2. **`DashboardServerList.tsx`:** In the server card metadata line, display the loader badge next to the version text.
3. **`ServerDetailPage.tsx`:** In the page header, render `<LoaderBadge loader={server.server_type} />` beside the status badge and provider badge.
4. **`ServerModsPage.tsx`:** Deprecate local unexported `LoaderBadge` and import the shared component.

---

## 4. Affected Components

| Module / File | Change Type | Description |
|---|:---:|---|
| `backend/app/modules/versioning/infrastructure/test_runner.py` | **Modify** | Implement real asynchronous subprocess bot execution, watchdog timeout, process-tree killing, and DB outcome persistence. |
| `backend/app/modules/versioning/infrastructure/bot_drivers.py` | **Modify** | Wire real Node/Mineflayer launch, environment binding, stream log capture, and FakePlayer-Next Paper support. |
| `backend/app/modules/versioning/infrastructure/config_writer.py` | **Modify** | Add `bot_count` parameter and enforce `max-players >= bot_count + 5` for isolated test deployments. |
| `backend/app/modules/versioning/application/commands/promote_commit.py` | **Modify** | Enforce `test_run.status == PASSED` promotion gate, check subsequent failure invalidation, and add `force` bypass. |
| `backend/app/modules/versioning/application/queries/get_server_test_runs.py` | **New** | CQRS query and handler retrieving paginated test runs for a server. |
| `backend/app/api/v1/routers/versioning.py` | **Modify** | Add `GET /api/v1/servers/{server_id}/versioning/tests` endpoint and update `promote` route schema. |
| `backend/app/api/v1/schemas/versioning.py` | **Modify** | Add `force: bool = False` to `PromoteCommitRequest`. |
| `contracts/permissions.yaml` | **Modify** | Register `GET /api/v1/servers/{server_id}/versioning/tests` permission route contract mapping. |
| `frontend/src/components/ui/LoaderBadge.tsx` | **New** | Reusable software/loader badge supporting Paper, Fabric, Forge, NeoForge, Purpur, Vanilla. |
| `frontend/src/services/api.ts` | **Modify** | Add `getServerTestRuns` API client function and support `force` in `promoteTestCommit`. |
| `frontend/src/server_manager/pages/ServerVersioningPage.tsx` | **Modify** | Fetch test runs, implement 3s conditional polling during active tests, and wire logs inspection modal. |
| `frontend/src/server_manager/pages/ServersPage.tsx` | **Modify** | Render `LoaderBadge` alongside Minecraft version in server table rows. |
| `frontend/src/server_manager/components/DashboardServerList.tsx` | **Modify** | Render `LoaderBadge` in server card metadata line. |
| `frontend/src/server_manager/pages/ServerDetailPage.tsx` | **Modify** | Render `LoaderBadge` in header badge group. |

---

## 5. Interfaces & Contracts

### 5.1 New Endpoint: List Server Test Runs
```http
GET /api/v1/servers/{server_id}/versioning/tests?limit=50
Authorization: Bearer <token> (Permission: server:version:read)
```

**Response (200 OK):**
```json
[
  {
    "id": "c1f7a2b9-1234-4567-89ab-cdef01234567",
    "server_id": "srv-abc-123",
    "commit_id": "commit-998877",
    "status": "PASSED",
    "ephemeral_port": 25565,
    "bot_count": 10,
    "duration_minutes": 15,
    "bot_tech": "mineflayer",
    "placement_mode": "sidecar",
    "failure_reason": null,
    "log_output": "[BOT-HARNESS] Starting 10 bots against 172.17.0.4:25565...\n[BOT-HARNESS] Bot #1 (onx-bot-c1f7a2b9-1) spawned successfully!\n...",
    "created_at": "2026-09-15T09:30:00Z"
  }
]
```

### 5.2 Updated Endpoint: Promote Commit
```http
POST /api/v1/servers/{server_id}/versioning/tests/{test_id}/promote
Authorization: Bearer <token> (Permission: server:version:promote)
Content-Type: application/json

{
  "keep_world_changes": false,
  "force": false
}
```

**Error Response (400 Bad Request — Unverified Commit):**
```json
{
  "error": "VALIDATION_ERROR",
  "detail": "Cannot promote commit 'commit-998877': Test run 'c1f7a2b9-1234' has status 'FAILED'. Only PASSED test runs can be promoted to production."
}
```

---

## 6. Failure Cases & Edge Cases

### 6.1 Subprocess Crash or Node Dependency Missing
- **Scenario:** Node.js is not installed on the host or `runner.js` encounters an uncaught exception (e.g. syntax error or missing `mineflayer` module).
- **Handling:** The subprocess exits with a non-zero returncode. `_execute_verification` captures stderr, extracts the error trace, marks `passed = False`, sets `failure_reason = f"Bot runner exited with code {returncode}: {stderr_tail}"`, and persists the status to SQLite.

### 6.2 Watchdog Timeout Expiry
- **Scenario:** Bots hang in connection loops, or the test server becomes unresponsive without crashing.
- **Handling:** An asyncio watchdog timer set to `duration_minutes * 60 + connect_grace_seconds` fires. The runner calls `platform_kill_process_tree_async(process.pid)` to kill Node and its children, sets `failure_reason = f"Test timed out after {duration_minutes} minutes"`, and records `status = FAILED`.

### 6.3 Test Server Container Crashes During Verification
- **Scenario:** Incompatible mod or out-of-memory error causes Minecraft server container to exit while bots are connected.
- **Handling:** `_execute_verification` periodically checks container liveness via `docker inspect`. If the container exits prematurely or creates a file in `crash-reports/`, the `PatternCrashAnalyzer` extracts the blamed mod, sets `failure_reason = f"Crash detected in test run. Blamed mod: {blamed}"`, and terminates the bot runner subprocess immediately.

### 6.4 SQLite Concurrency Lock During Background Persistence
- **Scenario:** Multiple background metrics collectors or server operations execute while `_execute_verification` attempts to record the test outcome.
- **Handling:** Wrap database persistence in the established 3-attempt exponential backoff retry loop (`0.05s * 2^attempt`), preventing SQLite busy/writer starvation from dropping verification results.

### 6.5 Race Condition: Promotion Attempted While Test Still Running
- **Scenario:** Operator clicks promote via direct API call while `test_run.status == "RUNNING"`.
- **Handling:** `PromoteCommitHandler` rejects the request with HTTP 400 (`"Test run status is RUNNING. Wait for completion before promoting."`).

### 6.6 Subsequent Test Failure After Earlier Pass
- **Scenario:** Test run #1 for commit X passes. The user re-runs verification with 20 bots (run #2), and run #2 fails. The user attempts to promote using the `test_id` from run #1.
- **Handling:** `PromoteCommitHandler` inspects test history for commit X. Because a subsequent run failed, the earlier pass is invalidated, and the request is rejected until a new test passes.

---

## 7. Tests & Verification Plan

### 7.1 Backend Unit & Integration Tests
1. **Subprocess Execution & Log Capture:**  
   `backend/tests/unit/versioning/test_real_bot_runner.py`
   - Verify Node subprocess launch with correct environment variables (`MC_HOST`, `MC_PORT`, etc.).
   - Verify stdout/stderr stream capture and capping at 64 KB.
   - Verify clean process-tree termination on cancellation and timeout using `platform_kill_process_tree_async`.
2. **Outcome Persistence:**  
   `backend/tests/integration/versioning/test_test_run_persistence.py`
   - Verify `_execute_verification` persists final status (`PASSED` / `FAILED`) to SQLite.
   - Verify `GET /api/v1/servers/{server_id}/versioning/tests/{test_id}` reflects persisted outcome.
   - Verify `GET /api/v1/servers/{server_id}/versioning/tests` returns paginated test run history.
3. **Promote Gating:**  
   `backend/tests/application/versioning/test_promote_commit_gating.py`
   - Test promotion rejection when test run is `RUNNING` (expect HTTP 400 / `ValidationError`).
   - Test promotion rejection when test run is `FAILED` (expect HTTP 400 / `ValidationError`).
   - Test promotion rejection when a newer test run for the same commit failed.
   - Test promotion success when test run is `PASSED`.
   - Test force bypass with `force=True` on unverified commit and verify audit log emission.
4. **Config Writer Max-Players Scaling:**  
   `backend/tests/unit/versioning/test_config_writer_max_players.py`
   - Verify `write_test_server_properties` sets `max-players >= bot_count + 5`.
   - Verify production `manifest.configs["server.properties"]` remains untouched.

### 7.2 Frontend Unit Tests
1. **Versioning Page Polling & Test History:**  
   `frontend/src/server_manager/pages/ServerVersioningPage.test.tsx`
   - Verify `api.getServerTestRuns` is invoked on initial load.
   - Verify 3-second polling interval is active when a test is `RUNNING` and halts when status becomes `PASSED` or `FAILED`.
   - Verify "Promote to Live" button is disabled/hidden for non-passed tests and active for passed tests.
2. **Loader Badge Component:**  
   `frontend/src/components/ui/LoaderBadge.test.tsx`
   - Verify correct label and color classes for Paper, Purpur, Fabric, Forge, NeoForge, and Vanilla.
3. **Server List & Header Badge Display:**  
   `frontend/src/server_manager/pages/ServersPage.test.tsx`, `ServerDetailPage.test.tsx`
   - Verify `LoaderBadge` renders in server table row and detail page header.

### 7.3 Regression & CI Quality Gates
- Execute all 5 required CI gates + advisory gate:
  `check-db-revision`, `check-ruff-baseline`, `check-version-propagation`, `check-route-contract`, `check-ps1-bom`, `check-stray-db`.
- Ensure backend test suite passes (2,706+ tests) and frontend test suite passes (701+ tests).

---

## 8. Out of Scope

1. **Remote Multi-Node Worker Distribution:** Distributed execution across remote cluster nodes via Celery/Ray remains architectural groundwork (§3.7) and is not implemented in this batch.
2. **Automated Mod Conflict Auto-Patching:** Analyzing crash reports detects and blames offending mods via `PatternCrashAnalyzer`, but does not attempt automated bytecode modification or mod removal.
3. **Bedrock Protocol Verification:** Verification is strictly bounded to Java Edition Minecraft servers. Bedrock server management remains classified under Lane E (Future Product).

---

## 9. Open Questions for Review

The following design decisions require explicit review and owner alignment before proceeding to the Build phase:

### Question 1: Unified Mineflayer Driver vs. Dual Driver (Mineflayer + FakePlayer-Next)
- **Context:** FakePlayer-Next is a Paper/Purpur-only plugin that spawns in-process bots via console commands without network protocol login. Mineflayer connects over TCP as a real Minecraft client, working on Vanilla, Fabric, Forge, and Paper, but requires Node.js and protocol packet updates for new MC releases.
- **Options:**
  - **Option A (Recommended):** Dual Driver. Use `FakePlayer-Next` as the fast, lightweight path for Paper/Purpur servers, and `Mineflayer` for Fabric, Forge, and Vanilla. If a server is Paper, it avoids the Node.js overhead completely.
  - **Option B:** Unified Mineflayer. Use Mineflayer exclusively for all server types. Simplifies codebase to one bot driver, but increases memory overhead and introduces protocol sensitivity on Paper.
- **Recommendation:** Option A (Dual Driver) — matches existing architectural groundwork and delivers lowest resource overhead on Paper servers (the most common production server type).

### Question 2: Commit Promotion Matching Policy
- **Context:** If a commit has multiple test runs over its lifetime, which runs qualify it for promotion?
- **Options:**
  - **Option A (Recommended):** Exact Passed Test ID + Invalidation Guard. The user specifies a `test_id` to promote. That test must be `PASSED`, AND no subsequent test run for that same commit may be `FAILED`.
  - **Option B:** Any Passed Test Ever. If any test run for commit X has passed, the commit is permanently eligible for promotion regardless of subsequent failures.
  - **Option C:** Latest Test Run Only. Only the most recent test run across the entire commit history is considered.
- **Recommendation:** Option A (Exact Passed Test ID + Invalidation Guard) — provides maximum safety against promoting a commit that failed regression testing after an initial pass.

### Question 3: Force Promotion Permission & Role Guard
- **Context:** When an administrator needs to bypass bot testing (e.g. during an urgent hotfix or when bots cannot connect due to custom mod handshakes), what level of authorization is required?
- **Options:**
  - **Option A (Recommended):** Require elevated permission `server:version:promote:force` (restricted to server owners and super-admins) with an explicit mandatory audit log entry.
  - **Option B:** Allow existing `server:version:promote` permission to use `--force`, recording an audit log entry.
- **Recommendation:** Option A — ensures that routine operators cannot silently bypass safety gates.

### Question 4: Fallback Behavior for Unsupported Minecraft Versions (1.20.5+ / 1.21+)
- **Context:** If a Fabric/Forge server runs MC 1.21.1 and Mineflayer protocol packets fail to negotiate:
- **Options:**
  - **Option A (Recommended):** Graceful Degradation to "Smoke Test" (Container Boot & World Sanity). Verify that the container boots, emits `Done!`, and runs crash-free for 60 seconds, recording status as `PASSED (SMOKE_TEST)`.
  - **Option B:** Hard Failure. Mark test run as `FAILED` with an explicit diagnostic: `"Protocol version 1.21.1 not supported by bot driver"`.
- **Recommendation:** Option A — prevents blocking version promotion for newer Minecraft versions while still providing container boot and world integrity verification.

### Question 5: Host Node.js vs. Docker Runner Container for Mineflayer
- **Context:** Mineflayer requires Node.js. Where should `node runner.js` execute?
- **Options:**
  - **Option A (Recommended):** Opportunistic Hybrid. Check if host has `node` and `mineflayer`. If yes, run directly on host (lowest latency and zero container overhead). If no, acquire a pooled runner container (`node:20-alpine`) from `BotRunnerPool`.
  - **Option B:** Strictly Docker Container. Always run Mineflayer inside a Docker sidecar container. Completely isolated, but adds Docker spin-up time and network bridging complexity.
- **Recommendation:** Option A — maximizes performance and reliability across varying host environments.

---

## 10. Governance Gate Check

Per `docs/governance/GOVERNANCE.md` §4–5 and §12:

1. **Lane Assignment:**  
   **Lane A — Release Critical**  
   *Rationale:* Phase 4 (Community Features: Git-Inspired Versioning & Bot Testing) committed isolated test runs and verification as a primary release capability. Leaving test execution stubbed and promotion ungated represents an unverified functional gap and a critical data-integrity risk (unverified commits can silently overwrite live servers).
2. **Decision Level:**  
   **Decision Level D1 (Significant)**  
   *Rationale:* The change touches multiple architectural layers (infrastructure test runner, CQRS commands, persistence repository, API routes, permissions contract, and frontend UI) and introduces a breaking contract constraint on `promote_commit` (rejecting unverified promotions with HTTP 400).
3. **Reversibility:**  
   **Fully Reversible.** No irreversible database schema migrations are introduced (`server_test_runs` already has `status`, `log_output`, and `failure_reason` columns). The promotion gate can be bypassed via `force=True` or reverted by relaxing the status check in `promote_commit.py`.
4. **Launch Gate Impact:**  
   - **Quality Gate 4 (check-route-contract):** Adding `GET /api/v1/servers/{server_id}/versioning/tests` requires updating `contracts/permissions.yaml`.
   - **Quality Gate 1 (check-db-revision):** Unaffected; no new Alembic migration required as existing table schema accommodates all required fields.
   - **Quality Gate 2 (check-ruff-baseline):** Unaffected; all new Python code must satisfy zero-ruff-error policy.
