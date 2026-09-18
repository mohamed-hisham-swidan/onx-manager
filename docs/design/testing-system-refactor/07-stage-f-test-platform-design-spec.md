# Design Spec — Stage F: Test Platform, Crash Correlation & Verification

**Status:** Draft — Ready for Design Review (Orchestrator.md §6)  
**Roadmap placement:** ONX Manager Phase 7 / Enterprise Branch Runtime (Stage F)  
**Source:** Derived from Enterprise Branch Runtime Architecture Report §4 (Test Platform), Stage F RECON, DECISION-2026-09-17-002 (Runtime Attach Model), DECISION-2026-09-17-003 (TestDefinition Domain Aggregate), and binding governance decisions.  
**Baselines carried:** Backend tests: 2,863 passed / 6 skipped / 0 failed (2,869 collected); Frontend tests: 711 passed (79 files); DB revision: `b1e2100000017` (37 revisions); CI quality gates: 6/6 PASS; Route contract: 141/141 verified.

---

## Goal

Transform isolated test execution from an ephemeral, ad-hoc runner script into a first-class, reproducible test platform:
1. **Establish `TestDefinition` as a first-class domain aggregate**: Decouple reusable test requirements ("Smoke Test", "50-Player Modded Load Test", bot counts, assertions, timeouts) from transient run parameters, persisting specifications independently of target commits.
2. **Wire the domain `Runtime` entity via the 1:1 Attach Model**: Bind the domain `Runtime` entity (formalized in Stage A) to physical container and process lifecycles via a dedicated `server_runtimes` table and a `runtime_id` foreign key on `server_test_runs`, without mutating `ServerTestRunModel`'s role as the authoritative test verification record.
3. **Capture container-level failure diagnostics**: Extract Docker container exit codes, `OOMKilled` flags, and process stderr upon non-zero exit or container death, terminating the vulnerability where out-of-memory kills or JVM crashes present as generic timeouts.
4. **Integrate test-run crash correlation and mod blaming**: Connect the proven `LogBasedEvidenceCollector` and `PatternCrashAnalyzer` engines to test runs, automatically analyzing `<test_dir>/crash-reports/` and `<test_dir>/logs/latest.log` upon failure to extract blamed mods and root-cause failure codes.
5. **Persist structured assertions and evidence bundles**: Augment test runs with structured assertion evaluation (boot completed, bots connected, crash-free, clean shutdown) and persist a serialized `EvidenceBundle` on `server_test_runs`.
6. **Implement test artifact retention and automated pruning**: Establish a configurable artifact retention policy that prunes aged test working directories (`.onx/tests/{test_id}`) and orphaned containers while preserving historical run records in the database.

---

## Current Behavior

- **`TestDefinition` is missing as a domain entity**:
  Tests are launched ad-hoc via `POST /api/v1/servers/{server_id}/versioning/tests`. The payload accepts `bot_count`, `duration_minutes`, `bot_tech`, `placement_mode`, and `commit_id`. These parameters are ephemeral: there is no way for an operator to save a standardized test suite (e.g. "Pre-Release Stress Test" or "Lightweight Smoke Test") and execute it across multiple commits or branches.
- **`TestSpec` conflates specification with execution context**:
  `TestSpec` (`backend/app/modules/versioning/infrastructure/test_runner.py:70-81`) is a frozen dataclass residing in the infrastructure layer. It requires a concrete `test_id`, a concrete `ServerCommit`, and an existing host filesystem path (`server_dir`). It cannot exist independently of a specific commit or server directory, making reusable test templates impossible without recreating the parameters on every invocation.
- **Domain `Runtime` is unpersisted and unwired**:
  `Runtime` (`backend/app/modules/versioning/domain/entities.py:318-368`, formalized in Stage A) enforces Safety Invariant 1 (pinning an immutable commit ID). However, per ADR-0015, Stage D §(e), and Stage E §(f), `Runtime` has no database table, no status lifecycle, and is never instantiated during test execution. Test runs currently manage container execution via `ServerTestRunModel` and an in-memory `TestHandle`, completely bypassing the domain `Runtime` entity.
- **Test-run failure diagnosis lacks container-level metrics**:
  When a test container exits prematurely (e.g. killed by Docker daemon due to host OOM, exit code 137, or JVM segmentation fault), `DockerTestExecutionRunner` only detects that RCON commands failed or that the boot gate timed out. It does not inspect `docker inspect` for `State.ExitCode`, `State.OOMKilled`, or container stderr, resulting in uninformative "Verification failed" or "Boot timeout" messages that conceal out-of-memory conditions.
- **Crash correlation is live-server only**:
  Live servers enjoy rich crash analysis: `LogBasedEvidenceCollector` captures logs and stack traces, `PatternCrashAnalyzer` extracts blamed mods, and `EventDispatcher` broadcasts `CrashClassifiedEvent`. For test runs, `test_runner.py` only performs a shallow check for `crash-*.txt` and writes a plain-text string into `failure_reason`. It produces no structured evidence bundle, mod attribution is not stored in a queryable field, and stack traces are lost when test directories are cleaned up.
- **Test directory retention is all-or-nothing**:
  `test_runner.py:651-677` executes `cleanup_test()` in a `finally` block immediately upon test completion, purging the entire test directory (`.onx/tests/{test_id}`). If an operator wants to inspect server logs, mod configs, or crash reports from a failed test run, the files are already destroyed. Conversely, if a cleanup fails due to root-owned file permissions (pre-`--user` parity), leftover files linger indefinitely with no automated pruning task.

---

## Proposed Change

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            DOMAIN & CQRS LAYER                              │
│                                                                             │
│  ┌─────────────────────────┐               ┌─────────────────────────────┐  │
│  │     TestDefinition      │               │     ServerCommit/Revision   │  │
│  │ (Reusable Specification)│               │      (Target Commit)        │  │
│  └────────────┬────────────┘               └──────────────┬──────────────┘  │
│               │                                           │                 │
│               └─────────────────────┬─────────────────────┘                 │
│                                     │ compile                               │
│                                     ▼                                       │
│                        ┌─────────────────────────┐                          │
│                        │        TestSpec         │                          │
│                        │ (Compiled Execution)    │                          │
│                        └────────────┬────────────┘                          │
└─────────────────────────────────────┼───────────────────────────────────────┘
                                      │ admit & launch
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           EXECUTION & RUNTIME LAYER                         │
│                                                                             │
│  ┌─────────────────────────┐               ┌─────────────────────────────┐  │
│  │      ServerTestRun      │◄── 1:1 FK ────┤       domain.Runtime        │  │
│  │ (Verification & Outcome)│               │  (Physical Process/Ctn)     │  │
│  │                         │               │  - container_id, pid, port  │  │
│  │  - passed, failed       │               │  - status (RUNNING, CRASHED)│  │
│  │  - structured assertions│               │  - exit_code, oom_killed    │  │
│  │  - EvidenceBundle (JSON)│               │  - started_at, stopped_at   │  │
│  └────────────▲────────────┘               └──────────────┬──────────────┘  │
│               │                                           │                 │
│               │ populate evidence                         │ inspect state   │
│               │                                           │                 │
│  ┌────────────┴────────────┐               ┌──────────────┴──────────────┐  │
│  │ LogBasedEvidenceCollector│              │     docker inspect probe    │  │
│  │   PatternCrashAnalyzer  │               │   (ExitCode, OOM, stderr)   │  │
│  └─────────────────────────┘               └─────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

### (a) First-Class `TestDefinition` Aggregate

Per **DECISION-2026-09-17-003**, `TestDefinition` is introduced as a new domain aggregate in `backend/app/modules/versioning/domain/entities.py`.

1. **Domain Model**:
   ```python
   @dataclass
   class TestDefinition:
       id: str
       server_id: str
       name: str
       description: str = ""
       server_type: str = "vanilla"  # vanilla, paper, purpur, fabric, forge, neoforge
       bot_technology: BotTech = BotTech.MINEFLAYER
       bot_count: int = 5
       duration_seconds: int = 60
       join_stagger_seconds: float = 1.0
       connect_grace_seconds: int = 20
       placement_mode: PlacementMode = PlacementMode.SIDECAR
       assertion_rules: dict[str, Any] = field(default_factory=dict)
       timeout_seconds: int = 300
       created_at: datetime = field(default_factory=_utcnow)
       updated_at: datetime = field(default_factory=_utcnow)
   ```

2. **Compilation into `TestSpec`**:
   `TestDefinition` acts as a template. When executed against a target `ServerCommit` or `Revision`, a factory method compiles it into an executable `TestSpec`:
   ```python
   def compile_spec(
       self,
       test_id: str,
       commit: ServerCommit,
       server_dir: str,
       worktree_dir: str | None = None,
   ) -> TestSpec:
       bot_cfg = BotVerificationConfig(
           bot_count=self.bot_count,
           duration_minutes=max(1, self.duration_seconds // 60),
           bot_tech=self.bot_technology,
           placement_mode=self.placement_mode,
           join_stagger_seconds=self.join_stagger_seconds,
           connect_grace_seconds=self.connect_grace_seconds,
       )
       return TestSpec(
           test_id=test_id,
           server_id=self.server_id,
           commit=commit,
           server_dir=server_dir,
           bot_config=bot_cfg,
           timeout_seconds=self.timeout_seconds,
           worktree_dir=worktree_dir,
       )
   ```

3. **Persistence**:
   Backed by `server_test_definitions` table in `backend/app/modules/versioning/infrastructure/models.py`.

---

### (b) Domain `Runtime` Entity & 1:1 Attach Model

Per **DECISION-2026-09-17-002**, `Runtime` is wired as a 1:1 execution handle attached to `ServerTestRun`.

1. **Entity Lifecycle State Machine**:
   ```python
   class RuntimeStatus(str, Enum):
       STARTING = "starting"
       RUNNING = "running"
       TERMINATED = "terminated"
       CRASHED = "crashed"
   ```

2. **Domain Entity (`entities.py:318-368`) Extension**:
   ```python
   @dataclass
   class Runtime:
       id: str
       commit_id: str
       materialization_id: str | None = None
       provider_type: str = "docker"
       server_id: str | None = None
       container_id: str | None = None
       pid: int | None = None
       port: int | None = None
       status: RuntimeStatus = RuntimeStatus.STARTING
       exit_code: int | None = None
       oom_killed: bool = False
       started_at: datetime = field(default_factory=_utcnow)
       stopped_at: datetime | None = None
       created_at: datetime = field(default_factory=_utcnow)
   ```
   - **Safety Invariant 1 Preserved**: `Runtime` strictly asserts that `commit_id` is an immutable hex commit ID and cannot bind directly to a mutable branch reference (`branch:*` or `refs/*`).

3. **Persistence Table (`server_runtimes`)**:
   ```sql
   CREATE TABLE server_runtimes (
       id VARCHAR(64) PRIMARY KEY,
       server_id VARCHAR(36) NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
       commit_id VARCHAR(64) NOT NULL REFERENCES server_commits(id),
       materialization_id VARCHAR(64),
       provider_type VARCHAR(32) NOT NULL DEFAULT 'docker',
       container_id VARCHAR(255),
       pid INTEGER,
       port INTEGER,
       status VARCHAR(32) NOT NULL DEFAULT 'starting',
       exit_code INTEGER,
       oom_killed BOOLEAN NOT NULL DEFAULT FALSE,
       started_at TIMESTAMP WITH TIME ZONE NOT NULL,
       stopped_at TIMESTAMP WITH TIME ZONE,
       created_at TIMESTAMP WITH TIME ZONE NOT NULL
   );
   ```

4. **Foreign Key on `server_test_runs`**:
   Add `runtime_id VARCHAR(64) REFERENCES server_runtimes(id) ON DELETE SET NULL` to `server_test_runs`.
   - Existing code querying `server_test_runs` continues to work without disruption.
   - When a test is admitted and launched, a `Runtime` record is inserted in state `STARTING`. Once the container starts, it transitions to `RUNNING` with `container_id` populated. Upon termination, it transitions to `TERMINATED` (or `CRASHED`) with `exit_code`, `oom_killed`, and `stopped_at`.

---

### (c) Container-Level Diagnostics

When a test run fails, terminates prematurely, or times out, the runner must extract concrete OS/container telemetry before tearing down the environment:

1. **Docker Container Inspection**:
   Prior to container removal in `cleanup_test()`, the runner executes:
   ```python
   inspect_proc = await asyncio.to_thread(
       subprocess.run,
       ["docker", "inspect", handle.container_name],
       capture_output=True,
       text=True,
       timeout=10,
   )
   ```
2. **Extracted Metrics**:
   - `State.ExitCode`: Exact integer code (e.g. `137` for SIGKILL, `1` for Java error, `139` for SIGSEGV).
   - `State.OOMKilled`: Boolean flag from the Linux kernel cgroup OOM killer.
   - `State.Error`: Daemon error string if container failed to start.
3. **Container Stderr Extraction**:
   If the container failed during startup or boot gating, capture the tail of container stderr (`docker logs --tail 100 --timestamps {container}`).
4. **Diagnostic Injection**:
   If `OOMKilled` is True, `failure_reason` is explicitly flagged:
   `"Test server container was killed by OOM killer (exit code 137). Earmarked RAM exceeded."`
   If `ExitCode != 0` and no crash report exists:
   `"Test server container terminated unexpectedly with exit code {exit_code}."`

---

### (d) Test-Run Crash Correlation & Mod Blame

Integrate `LogBasedEvidenceCollector` and `PatternCrashAnalyzer` into test verification:

1. **Crash Report Harvesting**:
   Inspect `<test_dir>/crash-reports/` and `<test_dir>/logs/latest.log`.
2. **Blame Analysis**:
   Run `PatternCrashAnalyzer.analyze_crash_content(content)`:
   - Identify `failure_code` (e.g. `MOD_CRASH`, `MISSING_DEPENDENCY`, `VERSION_INCOMPATIBLE`, `OUT_OF_MEMORY`, `CORRUPT_WORLD`).
   - Identify `blamed_mod` (e.g. `jei`, `create`, `sodium`).
   - Extract suspect stack trace lines.
3. **Event Dispatching**:
   Emit `TestRunFailedEvent(test_id, server_id, failure_code, blamed_mod)` to the event bus, enabling WebSocket notifications to update the frontend immediately.

---

### (e) Structured Assertions & Evidence Bundle Schema

Augment `server_test_runs` with an `evidence_bundle` JSON column containing structured diagnostic data:

```json
{
  "test_id": "test-c7b91a2e",
  "server_id": "srv-1234",
  "commit_id": "a1b2c3d4e5f6",
  "runtime": {
    "runtime_id": "rt-8f92a10b",
    "container_name": "onx-test-test-c7b91a2e",
    "exit_code": 0,
    "oom_killed": false,
    "peak_memory_mb": 1840,
    "duration_seconds": 64.2
  },
  "assertions": {
    "container_started": true,
    "boot_gate_passed": true,
    "bots_spawned_target": 5,
    "bots_spawned_actual": 5,
    "crash_reports_found": 0,
    "clean_shutdown": true
  },
  "crash_analysis": {
    "blamed_mod": null,
    "failure_code": null,
    "summary": null,
    "crash_report_path": null
  },
  "log_tail": [
    "[Server thread/INFO]: Done (2.1s)! For help, type 'help'",
    "[FakePlayer] Bot fp_bot_1 joined the game",
    "[FakePlayer] Bot fp_bot_2 joined the game"
  ]
}
```

---

### (f) Artifact Retention & Cleanup Policies

1. **Configurable Retention Windows**:
   - `test_run_retention_days`: Number of days to retain historical test run rows in SQLite (default: `30` days).
   - `test_artifact_retention_hours`: Number of hours to preserve disk artifacts (`.onx/tests/{test_id}`) for failed runs before pruning (default: `24` hours for failed runs, `0` hours / immediate for passed runs).
2. **Retention Policy Logic**:
   - Passed runs: Clean up container and test directory immediately upon completion (current behavior).
   - Failed runs: Retain test directory for `test_artifact_retention_hours` to allow manual debugging, then prune.
   - Database records: Never silently delete; mark `artifacts_purged = True` when disk assets are cleaned.
3. **Lazy-Reap Cleanup Integration**:
   `PruneTestArtifactsCommand` is invoked directly from within `admission.py`'s existing lazy-reap transaction (`reap_stale_reservations`), alongside the cleanup of stale admissions. This scans `.onx/tests/` and prunes disk directories for failed runs older than `test_artifact_retention_hours`, without introducing any new standalone background scheduler or polling loop.

---

## Affected Components

### Backend Modules & Files
- **`backend/app/modules/versioning/domain/entities.py`**:
  - Add `TestDefinition` domain aggregate.
  - Extend `Runtime` with `status: RuntimeStatus`, `container_id`, `pid`, `port`, `exit_code`, `oom_killed`, `started_at`, `stopped_at`.
- **`backend/app/modules/versioning/domain/repository.py` & `infrastructure/repository.py`**:
  - Add `TestDefinitionRepository` methods: `save_test_definition()`, `get_test_definition()`, `list_test_definitions()`, `delete_test_definition()`.
  - Add `RuntimeRepository` methods: `save_runtime()`, `get_runtime()`.
  - Update `save_test_run()` to persist `evidence_bundle` and `runtime_id`.
- **`backend/app/modules/versioning/infrastructure/models.py`**:
  - Add `ServerTestDefinitionModel` (`server_test_definitions`).
  - Add `ServerRuntimeModel` (`server_runtimes`).
  - Update `ServerTestRunModel`: add `runtime_id` (FK to `server_runtimes`), `test_definition_id` (FK to `server_test_definitions`), and `evidence_bundle` (JSON/Text).
- **`backend/app/modules/versioning/infrastructure/test_runner.py`**:
  - Instantiate and manage `Runtime` lifecycle during `run_test()`.
  - In `_execute_verification`: collect container diagnostics (`ExitCode`, `OOMKilled`, stderr) on failure.
  - In `_execute_verification`: run `PatternCrashAnalyzer` on crash reports / logs to populate `crash_analysis` in `evidence_bundle`.
  - Update `_persist_test_outcome`: save `Runtime` state and structured `evidence_bundle`.
  - Update `cleanup_test`: retain failed run directories when `test_artifact_retention_hours > 0`.
- **`backend/app/modules/versioning/application/commands/`**:
  - `CreateTestDefinitionCommand` & handler.
  - `UpdateTestDefinitionCommand` & handler.
  - `DeleteTestDefinitionCommand` & handler.
  - `PruneTestArtifactsCommand` & handler (invoked inside `admission.py`'s lazy reap transaction; zero new background loops).
  - Update `RunIsolatedTestCommand`: accept optional `test_definition_id`.
- **`backend/app/modules/versioning/application/scheduling/admission.py`**:
  - Wire artifact pruning into `reap_stale_reservations` to prune expired test directories alongside stale admission reaping.
- **`backend/app/modules/versioning/application/queries/`**:
  - `GetTestDefinitionQuery` & handler.
  - `ListTestDefinitionsQuery` & handler.
  - `GetTestRunEvidenceQuery` & handler.
- **`backend/app/modules/versioning/presentation/versioning.py`**:
  - REST endpoints for `TestDefinition` CRUD (`/api/v1/servers/{server_id}/versioning/test-definitions`).
  - REST endpoint for test evidence (`/api/v1/servers/{server_id}/versioning/tests/{test_id}/evidence`).
- **Alembic Migration**:
  - **NEW** `backend/alembic/versions/b1e2100000018_stage_f_test_platform.py`:
    - Create `server_runtimes` table.
    - Create `server_test_definitions` table.
    - Add `runtime_id`, `test_definition_id`, `evidence_bundle`, `artifacts_purged` columns to `server_test_runs`.

### Frontend Components (Preparation)
- Update TypeScript types in `frontend/src/server_manager/types/versioning.ts`:
  - Add `TestDefinition` interface.
  - Add `EvidenceBundle`, `RuntimeInfo` to `TestRunReadModel`.
- (UI implementation of Test Definition manager and Evidence Modal can be rendered in subsequent frontend passes).

---

## Interfaces & Contracts

### 1. REST API Endpoints

| Method | Path | Permission | Description |
|---|---|---|---|
| `GET` | `/api/v1/servers/{server_id}/versioning/test-definitions` | `server:version:read` | List all saved test definitions for a server |
| `POST` | `/api/v1/servers/{server_id}/versioning/test-definitions` | `server:test:configure` | Create a new reusable test definition |
| `GET` | `/api/v1/servers/{server_id}/versioning/test-definitions/{id}` | `server:version:read` | Get test definition details |
| `PUT` | `/api/v1/servers/{server_id}/versioning/test-definitions/{id}` | `server:test:configure` | Update an existing test definition |
| `DELETE` | `/api/v1/servers/{server_id}/versioning/test-definitions/{id}` | `server:test:configure` | Delete a test definition |
| `GET` | `/api/v1/servers/{server_id}/versioning/tests/{test_id}/evidence` | `server:version:read` | Retrieve structured evidence bundle for a test run |
| `POST` | `/api/v1/servers/{server_id}/versioning/tests` | `server:test:execute` | (Existing) Run test — extended with optional `test_definition_id` |

*Route Contract Note*: Adding 6 new routes will advance the contract from 141 to 147 routes. All 6 will be added to `contracts/permissions.yaml` with explicit RBAC scopes, keeping `check-route-contract` strictly in sync.

### 2. Pydantic Schemas

```python
class TestDefinitionCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    server_type: str = Field(default="vanilla")
    bot_technology: str = Field(default="mineflayer")
    bot_count: int = Field(default=5, ge=0, le=100)
    duration_seconds: int = Field(default=60, ge=10, le=3600)
    join_stagger_seconds: float = Field(default=1.0, ge=0.0, le=10.0)
    connect_grace_seconds: int = Field(default=20, ge=5, le=120)
    placement_mode: str = Field(default="sidecar")
    assertion_rules: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=300, ge=30, le=7200)

class TestDefinitionResponse(TestDefinitionCreateRequest):
    id: str
    server_id: str
    created_at: datetime
    updated_at: datetime

class EvidenceBundleResponse(BaseModel):
    test_id: str
    server_id: str
    commit_id: str
    runtime: dict[str, Any]
    assertions: dict[str, Any]
    crash_analysis: dict[str, Any]
    log_tail: list[str]
```

---

## Database Migration Specification (`b1e2100000018`)

- **Revision ID**: `b1e2100000018`
- **Revises**: `b1e2100000017`
- **Tables Created**:
  1. `server_runtimes`:
     - `id`: VARCHAR(64) PK
     - `server_id`: VARCHAR(36) NOT NULL FK (`servers.id`)
     - `commit_id`: VARCHAR(64) NOT NULL FK (`server_commits.id`)
     - `materialization_id`: VARCHAR(64)
     - `provider_type`: VARCHAR(32) NOT NULL DEFAULT `'docker'`
     - `container_id`: VARCHAR(255)
     - `pid`: INTEGER
     - `port`: INTEGER
     - `status`: VARCHAR(32) NOT NULL DEFAULT `'starting'`
     - `exit_code`: INTEGER
     - `oom_killed`: BOOLEAN NOT NULL DEFAULT FALSE
     - `started_at`: TIMESTAMP WITH TIME ZONE NOT NULL
     - `stopped_at`: TIMESTAMP WITH TIME ZONE
     - `created_at`: TIMESTAMP WITH TIME ZONE NOT NULL
  2. `server_test_definitions`:
     - `id`: VARCHAR(64) PK
     - `server_id`: VARCHAR(36) NOT NULL FK (`servers.id`)
     - `name`: VARCHAR(100) NOT NULL
     - `description`: VARCHAR(500) NOT NULL DEFAULT `''`
     - `server_type`: VARCHAR(32) NOT NULL DEFAULT `'vanilla'`
     - `bot_technology`: VARCHAR(32) NOT NULL DEFAULT `'mineflayer'`
     - `bot_count`: INTEGER NOT NULL DEFAULT 5
     - `duration_seconds`: INTEGER NOT NULL DEFAULT 60
     - `join_stagger_seconds`: FLOAT NOT NULL DEFAULT 1.0
     - `connect_grace_seconds`: INTEGER NOT NULL DEFAULT 20
     - `placement_mode`: VARCHAR(32) NOT NULL DEFAULT `'sidecar'`
     - `assertion_rules`: JSON / TEXT NOT NULL DEFAULT `'{}'`
     - `timeout_seconds`: INTEGER NOT NULL DEFAULT 300
     - `created_at`: TIMESTAMP WITH TIME ZONE NOT NULL
     - `updated_at`: TIMESTAMP WITH TIME ZONE NOT NULL
- **Columns Added to `server_test_runs`**:
  - `runtime_id`: VARCHAR(64) NULL FK (`server_runtimes.id` ON DELETE SET NULL)
  - `test_definition_id`: VARCHAR(64) NULL FK (`server_test_definitions.id` ON DELETE SET NULL)
  - `evidence_bundle`: JSON / TEXT NULL
  - `artifacts_purged`: BOOLEAN NOT NULL DEFAULT FALSE

---

## Invariants & Constraints

1. **Safety Invariant 1 (Immutable Commit Binding)**:
   Every `Runtime` MUST be pinned to a permanent, immutable `commit_id`. It must reject binding directly to a mutable branch reference (`branch:*` or `refs/*`).
2. **1:1 Attach Boundary (DECISION-2026-09-17-002)**:
   `Runtime` tracks the physical container/process state; `ServerTestRun` tracks the verification result and evidence. Existing queries against `ServerTestRunModel` (admission scheduler, promotion gating, history) remain authoritative and unbroken.
3. **Decoupled Test Specification (DECISION-2026-09-17-003)**:
   `TestDefinition` specifies *what* to run independently of any specific commit. Compiling a `TestDefinition` against a `ServerCommit` yields a `TestSpec`.
4. **Terminal State Immutability**:
   Once a `ServerTestRun` reaches a terminal status (`PASSED`, `FAILED`, `CANCELLED`), neither its status nor its `evidence_bundle` may be modified.
5. **Non-Blocking Cleanup Resilience**:
   Failure during artifact directory deletion or container removal must never mask or flip a test verification outcome from `PASSED` to `FAILED` (or vice-versa).

---

## Test Plan & Verification Gates

### 1. Unit & Domain Tests
- `tests/domain/test_stage_f_test_definition.py`:
  - `TestDefinition` validation (name limits, bot counts, durations).
  - Compilation of `TestDefinition` into `TestSpec` with various commit targets.
- `tests/domain/test_stage_f_runtime.py`:
  - `Runtime` status transitions (`STARTING` $\rightarrow$ `RUNNING` $\rightarrow$ `TERMINATED` / `CRASHED`).
  - Rejection of mutable branch references.
  - Immutability of `commit_id` after initialization.

### 2. Infrastructure & Runner Tests
- `tests/infrastructure/test_stage_f_runner_diagnostics.py`:
  - Test container OOM-killed scenario: mock `docker inspect` with `OOMKilled: True, ExitCode: 137`, verify `failure_reason` identifies OOM.
  - Test container unexpected exit scenario: mock `docker inspect` with `ExitCode: 1`, verify exit code captured.
  - Test crash report analysis: verify `PatternCrashAnalyzer` populates `blamed_mod` and `failure_code` in `evidence_bundle`.
  - Test `Runtime` lifecycle persistence: assert `server_runtimes` row is created, updated, and linked via `runtime_id`.
- `tests/infrastructure/test_stage_f_retention.py`:
  - Verify `PruneTestArtifactsCommand` removes directories older than retention window.
  - Verify passed test directories are pruned immediately while failed runs are retained per policy.
  - Verify database rows are flagged `artifacts_purged=True` without deletion.

### 3. API & Contract Tests
- `tests/api/test_stage_f_test_definitions_api.py`:
  - Full CRUD operations on `/api/v1/servers/{server_id}/versioning/test-definitions`.
  - RBAC verification (`server:test:configure`, `server:version:read`).
  - Test evidence retrieval via `/api/v1/servers/{server_id}/versioning/tests/{test_id}/evidence`.

### 4. CI Quality Gates
- `scripts/check-db-revision`: Pass on `b1e2100000018`.
- `scripts/check-ruff-baseline`: 0 new lint regressions.
- `scripts/check-version-propagation`: 0.1.0 maintained.
- `scripts/check-route-contract`: Pass with 147 routes (141 existing + 6 new).
- `scripts/check-ps1-bom`: Pass across all tracked scripts.
- `scripts/check-stray-db`: Pass with no stray sqlite databases.

---

## Out of Scope (Deferred to Stage G)

1. **Multi-Host Distributed Test Runners**: Distributing test containers across multiple remote physical nodes/hosts (remains Stage G enterprise scheduling).
2. **Multi-Tenant Test Quotas & Billing Limits**: Project-level or organization-level resource quotas (Stage G).
3. **Automated Flaky-Test Retries & Statistical Flake Detection**: Running tests $N$ times to calculate flake percentages (Future/Backlog).
