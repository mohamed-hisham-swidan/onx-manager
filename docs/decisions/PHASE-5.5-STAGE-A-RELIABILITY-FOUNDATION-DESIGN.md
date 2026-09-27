# Phase 5.5 Stage A — Reliability Foundation Design Specification

Status:
Design baseline / Proposed

Lane:
Release Improvement

Decision Level:
D2 — Major

Roadmap Drift:
Controlled Drift

---

## 1. Goal

The goal of Stage A (Reliability Foundation) is to establish the core operational tracking, transparency, and idempotency foundation for **Phase 5.5: Pre-Beta Reliability, Verification & Safe Change Architecture**.

Prior to this specification, long-running server actions (such as starting, provisioning, backup creation, or test execution) operated through heterogeneous mechanisms with disparate state tracking:
- Server lifecycle commands emitted domain events but had no aggregate representing the end-to-end user-initiated operation.
- Isolated test runs relied on `ServerTestRun` in the `versioning` module.
- Backup jobs relied on `BackupJob` in the `backup` module and `BackupSaga` in services.
- The UI had no uniform mechanism or presentation drawer for multi-step workflows with real-time progression, failure explanations, or cancellation.
- Command idempotency existed in `app.core.idempotency` but was disconnected from production command execution.
- Domain event schemas in `contracts/events.yaml` had no schema validation or compatibility enforcement.

Stage A delivers a unified, cross-cutting operational foundation:
1. An **`Operation` aggregate and service** to model, track, and orchestrate user-visible, multi-step asynchronous actions.
2. An **`OperationStep` model** capturing discrete workflow stages, progression, elapsed execution time, and retry safety.
3. A **versioned event envelope and contract** (`operation.*`) specifying operational events with monotonic sequence numbers and real schema enforcement.
4. An **idempotent lifecycle mechanism** reconciling transport-level command deduplication with domain-level operation deduplication.
5. A **WebSocket projection path** delivering operational progress to authenticated frontend subscribers with reconnect resilience.
6. A responsive **Operation UI drawer and stepper (`OperationDrawer` / `OperationStepper`)** displaying real-time execution progress, structured failure codes, and cancellation/retry controls.

Stage A establishes the infrastructure required by subsequent stages (Stage B Test Run Engine, Stage C Verification Tiers, Stage D Safe Change Pipeline, Stage E Modpack Platform) without implementing any Stage B–G functionality.

---

## 2. Current Behavior

An inspection of the repository reveals the following current state:

1. **Long-Running Server Actions:**
   - Server lifecycle actions (`start`, `stop`, `restart`, `delete`) execute through `ServerOrchestrator` (`backend/app/services/server_orchestrator.py`) or CQRS handlers (`StartServerHandler`, etc.). They emit lifecycle domain events (`ServerStartingEvent`, `ServerStartedEvent`) but do not persist or return an end-to-end operation identifier.
   - Backup creation and restoration execute via `BackupSaga` and persist state in `BackupJob` (`backend/app/modules/backup/domain/aggregate.py`).
   - Versioning tests execute via `RunIsolatedTestCommand` (`backend/app/modules/versioning/application/commands/run_isolated_test.py`) and persist state in `ServerTestRun` (`backend/app/modules/versioning/domain/entities.py`).
   - No common aggregate exists to track workflow progress, elapsed time, current step, cancellation requests, or diagnostic failure codes across these different operational types.

2. **WebSocket Plumbing:**
   - An authenticated WebSocket subsystem exists (`backend/app/websocket/`). It supports connection management (`manager.py`), subscription authorization (`authorization.py`), event dispatching (`dispatcher.py`), message buffering for offline users (`buffer.py`), and rate limiting (`rate_limiter.py`).
   - `WS_DISPATCH_ALLOWLIST` in `dispatcher.py` currently permits exactly 31 domain events across server lifecycle, backup, plugin, exposure, monitoring, and health/crash recovery.
   - Channel patterns (`authorization.py`) enforce access controls for `server:*`, `backup:*`, `plugin:*`, `monitoring:*`, `metrics:*`, `auth:*`, `provision:*`, and `test:*`.
   - The WebSocket infrastructure does not include any `operation:*` channels, prefixes, or event types.

3. **Event Contract Governance:**
   - `contracts/events.yaml` defines a version 1.0 schema envelope and 7 individual events (`server.created`, `server.started`, `server.crashed`, `backup.completed`, `plugin.installed`, `user.login`, `circuit.opened`).
   - The only verification performed on `contracts/events.yaml` is `backend/tests/core/test_contracts_integrity.py:test_events_yaml_integrity_f090`, which asserts that YAML duplicate keys do not exist.
   - There is no automated schema validation between `contracts/events.yaml` and the Pydantic `DomainEvent` classes emitted across the backend.

4. **Idempotency Mechanism:**
   - An idempotency abstraction exists in `backend/app/core/idempotency.py` consisting of `IdempotencyKey`, `IdempotencyStore`, `InMemoryIdempotencyStore`, and `IdempotencyMiddleware`.
   - The middleware provides reservation, waiting on in-flight duplicate commands via `asyncio.Event`, and replaying cached `CommandResult` payloads.
   - Tests verify this behavior in `backend/tests/test_iss002_idempotency_concurrency.py` and `backend/tests/test_idempotency.py`.
   - **Production Wiring Gap:** In `backend/app/registration.py` (lines 318–320), the production `command_bus` only registers `DatabaseBusyRetryMiddleware()`. `IdempotencyMiddleware` is never registered on the production bus; it has only been attached manually in test setups.
   - Furthermore, `InMemoryIdempotencyStore` does not survive backend process restarts.

5. **Frontend UI Primitives:**
   - The frontend (`frontend/src/`) utilizes TanStack Query, Zustand stores, and Tailwind CSS v4.
   - Existing reusable UI components include `StatusBadge` (`frontend/src/components/ui/StatusBadge.tsx`), `LoaderBadge` (`frontend/src/components/ui/LoaderBadge.tsx`), and `toastStore` (`frontend/src/stores/toastStore.ts`).
   - Specialized progress stores exist (e.g., `useProvisionProgressStore` in `frontend/src/stores/provisionProgressStore.ts`), and specialized modals exist (e.g., `TestRunModal`, `TestEvidenceModal`, `ImportReviewModal`).
   - There is no generic slide-over drawer or stepper for operations.

6. **"Phase 5.5 Startup Check" in `scripts/check-db-revision`:**
   - `scripts/check-db-revision:4` contains the docstring: *"This is the CI-side complement to the Phase 5.5 startup check."*
   - This refers to an earlier historical naming collision in `app.core.persistence.db_revision` that checks `RELEASE_MINIMUM_DB_REVISION`. It has no functional connection to the Pre-Beta Reliability Architecture.

---

## 3. RECON Evidence

| ID | Item | Classification | Verification Detail |
|---|---|---|---|
| R-01 | No direct `Operation` aggregate | **FACT** | Inspected `backend/app/`. Found `ServerTestRun` (versioning), `BackupJob` (backup), and `SagaInstance` (core), but no generic `Operation` aggregate or repository. |
| R-02 | WebSocket infrastructure is reusable | **FACT** | Inspected `backend/app/websocket/`. Found robust `ConnectionRegistry`, `EventDispatcher`, `ChannelAuthorizer`, and `OfflineMessageBuffer`. `WS_DISPATCH_ALLOWLIST` and `authorization.py` need additive extension, not replacement. |
| R-03 | Weak event contract enforcement | **FACT** | Inspected `contracts/events.yaml` and `backend/tests/core/test_contracts_integrity.py`. The suite checks duplicate mapping keys only. Schema compatibility between domain events and YAML contracts is not enforced. |
| R-04 | Existing idempotency middleware exists | **FACT** | Inspected `backend/app/core/idempotency.py`. `IdempotencyMiddleware` handles reservations, concurrent wait, and result caching. |
| R-05 | Production CommandBus lacks IdempotencyMiddleware | **FACT** | Inspected `backend/app/registration.py:319`. Only `DatabaseBusyRetryMiddleware()` is added to `command_bus`. `IdempotencyMiddleware` is omitted from production registration. |
| R-06 | `InMemoryIdempotencyStore` is ephemeral | **FACT** | `InMemoryIdempotencyStore` holds in-memory Python dictionaries with TTL eviction. Process restart wipes reservations and results. |
| R-07 | Frontend UI primitives are reusable | **FACT** | Inspected `frontend/src/components/ui/` and `frontend/src/stores/`. `StatusBadge`, `LoaderBadge`, and `toastStore` are mature and ready for reuse in the new drawer/stepper. |
| R-08 | Script naming collision is non-functional | **FACT** | Inspected `scripts/check-db-revision`. The phrase "Phase 5.5 startup check" in line 4 is an unrelated docstring comment in the Alembic revision checking script. |
| R-09 | Historical baseline metrics recorded | **FACT** | `.ai/STATE.json` records 3,058 passed / 6 skipped backend tests, 735 frontend tests across 84 files, 6/6 CI gates, Alembic head `b1e2100000020` as verified on 2026-09-24. These are historical baseline facts, not re-run during this design session. |

---

## 4. Proposed Architecture

### 4.1 Bounded Context & Module Placement

The `Operation` concept is an **Application Orchestration Aggregate**.

It sits between inbound command triggers (REST API, scheduled tasks, background events) and specific domain modules (`server`, `versioning`, `backup`, `health`):

```text
       ┌────────────────────────────────────────────────────────┐
       │                       REST API                         │
       │   POST /api/v1/operations (creates generic operation)  │
       │   GET  /api/v1/operations/{id}                         │
       └───────────────────────────┬────────────────────────────┘
                                   │
                                   ▼
       ┌────────────────────────────────────────────────────────┐
       │                   CommandBus / CQRS                    │
       │  (IdempotencyMiddleware verifies transport deduplication)│
       └───────────────────────────┬────────────────────────────┘
                                   │
                                   ▼
       ┌────────────────────────────────────────────────────────┐
       │              Operation Application Service             │
       │          backend/app/modules/operations/               │
       │   - Creates/loads Operation aggregate                  │
       │   - Verifies domain-level idempotency_key              │
       │   - Dispatches step progression                        │
       │   - Manages cooperative cancellation & timeout         │
       └──────────────┬──────────────────────────┬──────────────┘
                      │                          │
                      ▼                          ▼
       ┌──────────────────────────┐    ┌─────────────────────────┐
       │   Domain Operations      │    │  Operational Events     │
       │  (Server, Versioning,    │    │  (OperationStartedEvent,│
       │   Backup, Health)        │    │   OperationStepEvent,   │
       │  - ServerTestRun         │    │   OperationFailedEvent) │
       │  - BackupJob             │    └────────────┬────────────┘
       │  - Provider Actions      │                 │
       └──────────────────────────┘                 ▼
                                       ┌─────────────────────────┐
                                       │        EventBus         │
                                       └────────────┬────────────┘
                                                    │
                                                    ▼
                                       ┌─────────────────────────┐
                                       │   WebSocket Dispatcher  │
                                       │  channel: operation:*   │
                                       │  channel: server:*      │
                                       └────────────┬────────────┘
                                                    │
                                                    ▼
                                       ┌─────────────────────────┐
                                       │   Frontend UI Drawer    │
                                       │  OperationDrawer /      │
                                       │  OperationStepper       │
                                       └─────────────────────────┘
```

### 4.2 Module Location: `backend/app/modules/operations/`

To maintain clean hexagonal DDD boundaries, the new operations subsystem will reside in `backend/app/modules/operations/`:
- `domain/`:
  - `aggregate.py`: `Operation` aggregate root.
  - `entities.py`: `OperationStep` entity.
  - `enums.py`: `OperationStatus`, `OperationType`, `StepStatus`, `TargetType`.
  - `events.py`: `OperationStartedEvent`, `OperationStepEvent`, `OperationLogEvent`, `OperationCompletedEvent`, `OperationFailedEvent`, `OperationCancelledEvent`.
  - `repository.py`: `OperationRepository` interface.
- `application/`:
  - `commands/`: `CreateOperationCommand`, `CancelOperationCommand`, `RetryOperationCommand`, `RecordStepProgressCommand`.
  - `queries/`: `GetOperationQuery`, `GetActiveOperationForTargetQuery`, `ListOperationsQuery`.
  - `services/`: `OperationService` (lifecycle coordinator) and `OperationExecutor` (supervised task runner).
- `infrastructure/`:
  - `models.py`: `OperationModel`, `OperationStepModel`.
  - `repository.py`: `SQLOperationRepository`.
- `api/v1/`:
  - `routers/operations.py`: REST routes for creating, querying, cancelling, and retrying operations.
  - `schemas/operation.py`: Pydantic request and response schemas.

### 4.3 Operation Creation and Handler Modification Boundaries

In Stage A, operations are created in exactly two ways:
1. **Direct API Creation:** A user or client explicitly calls `POST /api/v1/operations`, which sends `CreateOperationCommand` to `CreateOperationHandler`.
2. **Programmatic Creation in Long-Running Handlers:**
   - **Scope Discipline Rule:** To avoid broad refactoring risk, **exactly ONE existing command handler is modified in Stage A**: `RunIsolatedTestHandler` (`backend/app/modules/versioning/application/commands/run_isolated_test.py`).
   - When `RunIsolatedTestHandler.handle()` executes, it calls `OperationService.create_operation()` with `type="RUN_TEST"`, `target_type="server"`, `target_id=command.server_id`, and initial planned steps (`ADMISSION_CHECK`, `MATERIALIZE_STAGING`, `BOOTSTRAP_VERIFY`, `SYNTHETIC_PLAYER`, `CLEANUP`).
   - All other existing command handlers (`StartServerHandler`, `StopServerHandler`, `CreateBackupHandler`, etc.) remain **completely unmodified** in Stage A.

### 4.4 Execution Substrate and Lifespan Shutdown Behavior

1. **Worker Substrate:**
   - Operation steps execute asynchronously under the supervision of `OperationExecutor` (`backend/app/modules/operations/application/services/executor.py`).
   - `OperationExecutor` maintains an in-memory task registry `_running_tasks: dict[str, asyncio.Task]`.
   - Each operation runs inside a tracked `asyncio.Task` created via `asyncio.create_task()`.
2. **Graceful Lifespan Shutdown:**
   - Integrated directly into the FastAPI lifespan context in `backend/app/main.py:lifespan`.
   - On server shutdown (SIGINT, SIGTERM, or process exit), the lifespan calls `await operation_executor.shutdown(grace_seconds=10.0)`.
   - The executor sets `cancellation_requested = True` for all active operations and signals running tasks.
   - Running tasks are allowed up to 10 seconds to abort gracefully and release container, network, or file staging reservations.
   - Tasks still running after `grace_seconds` receive `task.cancel()`.
   - Before the database connection pool closes, any operation interrupted by shutdown is committed to `operations` as `FAILED` with `failure_code = "SERVER_SHUTDOWN"`.

### 4.5 Relationship to Existing Primitives

`Operation` does **not** duplicate or replace existing subsystem primitives:
- **`ServerTestRun` (`versioning` module):** Continues to own isolated test container execution, ephemeral ports, bot configurations, DAG commit pinning, and mod blame analysis. When a test run is initiated, an `Operation` of type `RUN_TEST` wraps the test run and projects user-visible progress.
- **`BackupJob` (`backup` module):** Continues to own archive integrity, tarball compression, checksum verification, and S3 upload.
- **`SagaOrchestrator` (`app.core.saga`):** Remains an execution pattern for compensating transactions. When an operation requires multi-step rollback across distributed services, a saga can be invoked within an operation step.

---

## 5. Operation Lifecycle

### 5.1 State Machine

An `Operation` transitions through explicit states:

```text
                  ┌──────────────┐
                  │    QUEUED    │
                  └──────┬───────┘
                         │
                         ▼
                  ┌──────────────┐
                  │  PREPARING   │
                  └──────┬───────┘
                         │
                         ▼
                  ┌──────────────┐
         ┌───────►│   RUNNING    ├──────────────┐
         │        └──┬───┬───┬───┘              │
         │           │   │   │                  │
(retry)  │           │   │   └────────────┐     │
         │           ▼   ▼                ▼     ▼
         │   ┌──────────────┐      ┌──────────────────┐
         │   │    FAILED    │      │ CANCEL_REQUESTED │
         │   └──────────────┘      └────────┬─────────┘
         │           ▲                      │ (cleanup completed)
         │           │                      ▼
         │   ┌───────┴──────┐      ┌──────────────────┐
         └───┤  TIMED_OUT   │      │    CANCELLED     │
             └──────────────┘      └──────────────────┘
                     ▲
                     │ (all steps passed)
             ┌───────┴──────┐
             │  COMPLETED   │
             └──────────────┘
```

### 5.2 State Definitions

1. `QUEUED`: The operation has been admitted and persisted. It is awaiting execution resources or worker allocation.
2. `PREPARING`: Preliminary preparation is underway (lock acquisition, staging directory allocation, configuration resolution).
3. `RUNNING`: Operational steps are actively executing.
4. `CANCEL_REQUESTED`: Cancellation has been requested. Current active steps must stop at the next safe boundary, and cleanup must execute.
5. `CANCELLED`: Terminal state. Cleanup has concluded following a cancellation request.
6. `FAILED`: Terminal state. An unrecoverable error occurred, or a mandatory step failed with `safe_to_retry == False`.
7. `TIMED_OUT`: Terminal state. The operation exceeded its allocated `timeout_seconds`.
8. `COMPLETED`: Terminal state. All planned steps have executed successfully, and post-execution cleanup has concluded.

### 5.3 Valid and Invalid Transitions

| Source State | Target State | Permitted? | Condition / Trigger |
|---|---|---|---|
| `QUEUED` | `PREPARING` | Yes | Worker picks up operation. |
| `QUEUED` | `CANCEL_REQUESTED` | Yes | User cancels before execution starts. |
| `QUEUED` | `FAILED` | Yes | Pre-execution failure or startup queue purge. |
| `PREPARING` | `RUNNING` | Yes | Preparation succeeds. |
| `PREPARING` | `CANCEL_REQUESTED` | Yes | User cancels during preparation. |
| `PREPARING` | `FAILED` | Yes | Preparation failure (e.g. lock contention, disk full). |
| `PREPARING` | `TIMED_OUT` | Yes | Preparation exceeded timeout. |
| `RUNNING` | `COMPLETED` | Yes | All steps completed successfully. |
| `RUNNING` | `FAILED` | Yes | Unhandled exception or step failure. |
| `RUNNING` | `TIMED_OUT` | Yes | Execution duration exceeded `timeout_seconds`. |
| `RUNNING` | `CANCEL_REQUESTED` | Yes | Cancellation requested via API. |
| `CANCEL_REQUESTED` | `CANCELLED` | Yes | Cleanup completed. |
| `CANCEL_REQUESTED` | `FAILED` | Yes | Error occurred during cancellation cleanup. |
| `COMPLETED` | *Any* | **No** | Terminal state. |
| `CANCELLED` | *Any* | **No** | Terminal state. |
| `FAILED` | `QUEUED` / `PREPARING` | Yes (Controlled) | Only via explicit `retry()` if `safe_to_retry == True`. |
| `TIMED_OUT` | `QUEUED` / `PREPARING` | Yes (Controlled) | Only via explicit `retry()` if `safe_to_retry == True`. |

Any transition not explicitly permitted above raises an `InvalidStateTransitionError` (domain exception mapping to HTTP 409 Conflict).

### 5.4 Deterministic Timeout-vs-Cancel Precedence (Atomic Lifecycle Writes)

To eliminate race conditions between timeout expiration and cancellation requests, the "first committed transition wins" rule is enforced via **atomic conditional database updates with affected-row checks** on both execution paths:

1. **Cancellation Path (`OperationService.request_cancellation(operation_id)`):**
   Executes an atomic conditional update:
   ```sql
   UPDATE operations
   SET status = 'CANCEL_REQUESTED',
       cancellation_requested = TRUE
   WHERE id = :operation_id
     AND status IN ('QUEUED', 'PREPARING', 'RUNNING');
   ```
   - **Rowcount == 1:** The cancellation transition won the race. The operation commits the state change, signals `asyncio.Task` cooperative cancellation, executes cleanup, and transitions to `CANCELLED`.
   - **Rowcount == 0:** Cancellation lost the race or the operation is already terminal. The service queries the current status: if `TIMED_OUT`, `COMPLETED`, or `FAILED`, it raises `OperationTerminalConflictError` mapping to HTTP 409 Conflict. If already `CANCEL_REQUESTED` or `CANCELLED`, it returns the current status idempotently.

2. **Timeout Path (`OperationExecutor._handle_timeout(operation_id)`):**
   Executes an atomic conditional update:
   ```sql
   UPDATE operations
   SET status = 'TIMED_OUT',
       failure_code = 'OPERATION_TIMEOUT',
       error_message = 'Operation exceeded configured timeout limit',
       finished_at = :now
   WHERE id = :operation_id
     AND status IN ('PREPARING', 'RUNNING')
     AND cancellation_requested = FALSE;
   ```
   - **Rowcount == 1:** The timeout transition won the race. The executor commits the state change, runs timeout compensation/cleanup, and emits `OperationFailedEvent`.
   - **Rowcount == 0:** Timeout lost the race because cancellation committed first (or the operation already completed). The executor checks `cancellation_requested` and current status: timeout yields to cancellation, leaving `CANCEL_REQUESTED` / `CANCELLED` intact without overwriting.

By enforcing the conditional check directly in the SQL `WHERE` clause with an affected-row verification, neither path relies on racy in-memory state or separate read-modify-write transactions.

### 5.5 Startup Restart Recovery and Policy Switch

If the backend process terminates unexpectedly (host crash, SIGKILL, power failure) while operations are stored in the database:
1. On application startup, the `OperationRecoveryReconciler` runs before incoming traffic is served and inspects all non-terminal operations in the `operations` table:
   - **`PREPARING` or `RUNNING` Operations:** These operations had an active process that died mid-execution. Because volatile execution state is lost, they are transitioned to `FAILED` with `failure_code = "PROCESS_TERMINATED"` and `error_message = "Operation execution aborted due to unexpected backend termination"`.
   - **`QUEUED` Operations:** These operations never began execution. They must NOT be marked `PROCESS_TERMINATED`. Their handling is governed by the explicit policy switch `ONX_OPERATION_STARTUP_QUEUE_POLICY` (read from environment variable, default: `"PURGE"`):
     - **Default Policy (`PURGE`):** All operations remaining in `QUEUED` status at startup are transitioned to `FAILED` with `failure_code = "QUEUE_PURGED_ON_RESTART"` and `error_message = "Operation was queued when backend restarted and was purged per default startup policy"`. This provides a deterministic, safe default that prevents unexpected execution of stale commands after an outage or maintenance reboot.
     - **Configured Policy (`RE_DISPATCH`):** When `ONX_OPERATION_STARTUP_QUEUE_POLICY=RE_DISPATCH` is set in the environment, `OperationRecoveryReconciler` leaves the rows in `QUEUED` status and enqueues them into `OperationExecutor` in chronological order of `created_at`.
2. An audit log and domain event are recorded for each reconciled operation.

---

## 6. OperationStep Model

### 6.1 Schema & Attributes

```text
OperationStep
├── id: str (UUIDv4)
├── operation_id: str (UUIDv4, FK -> operations.id)
├── step_id: str (Machine-readable identifier, e.g. "ADMISSION_CHECK")
├── sequence: int (1-based monotonic ordering)
├── status: StepStatus (PENDING, IN_PROGRESS, COMPLETED, FAILED, SKIPPED, CANCELLED)
├── progress: float | None (0.0 to 1.0, or null if indeterminate)
├── elapsed_ms: int (Execution duration in milliseconds)
├── message_key: str | None (i18n translation key, e.g. "operations.steps.materializing")
├── safe_to_retry: bool (Whether failed step can be re-run safely)
├── context: dict[str, Any] (Step-specific metadata, e.g. container_id, bytes_copied)
├── started_at: datetime | None (UTC timestamp)
└── completed_at: datetime | None (UTC timestamp)
```

### 6.2 Persisted vs. Derived Fields

- **Persisted in DB (`operation_steps` table):**
  - `id`, `operation_id`, `step_id`, `sequence`, `status`, `progress`, `elapsed_ms`, `message_key`, `safe_to_retry`, `context`, `started_at`, `completed_at`.
- **Derived in Domain / Frontend:**
  - `is_active`: Derived as `status == StepStatus.IN_PROGRESS`.
  - `current_duration_ms`: If `status == IN_PROGRESS`, dynamically computed as `now() - started_at`; if terminal, equals `elapsed_ms`.
  - `is_terminal`: `status in (COMPLETED, FAILED, SKIPPED, CANCELLED)`.

### 6.3 Call Sites Emitting Step Transitions in Stage A

Stage A wires Operation step transitions strictly to the test run workflow. The exact call sites are:

1. `backend/app/modules/operations/application/services/operation_service.py`: Generic internal API (`start_step()`, `record_step_progress()`, `complete_step()`, `fail_step()`).
2. `backend/app/modules/versioning/application/commands/run_isolated_test.py:154`:
   - Step 1: `ADMISSION_CHECK` — started prior to `admit()`, marked completed once resource earmark commits.
3. `backend/app/modules/versioning/infrastructure/test_runner.py:342`:
   - Step 2: `MATERIALIZE_STAGING` — started before staging materialization, marked completed once tree is written.
4. `backend/app/modules/versioning/infrastructure/test_runner.py:355`:
   - Step 3: `BOOTSTRAP_VERIFY` — started upon container launch, marked completed when server readiness markers appear.
5. `backend/app/modules/versioning/infrastructure/test_runner.py:1176`:
   - Step 4: `SYNTHETIC_PLAYER` — started when bot script executes, emits incremental progress updates (`0.1..1.0`), marked completed upon bot assertions pass.
6. `backend/app/modules/versioning/infrastructure/test_runner.py:324`:
   - Step 5: `CLEANUP` — started during test teardown, marked completed once container and staging directories are pruned.

Zero other existing call sites in `server`, `backup`, or `plugins` emit Operation steps in Stage A.

---

## 7. Idempotency Design

### 7.1 Exact Transport and Router → Command Mapping

1. **Transport Mechanism:**
   - Clients provide the idempotency key via the standard HTTP Header: `Idempotency-Key: <key-string>`.
   - For backwards compatibility with JSON request payloads, the router also accepts an optional body field: `idempotency_key: str | None`.
2. **FastAPI Router Extraction:**
   - In `backend/app/api/v1/routers/operations.py`:
     ```python
     @router.post("/operations", response_model=OperationDetailResponse, status_code=202)
     async def create_operation(
         request: CreateOperationRequest,
         idempotency_header: str | None = Header(None, alias="Idempotency-Key"),
         current_user: User = Depends(require_permission("server:write")),
     ):
         raw_key = idempotency_header or request.idempotency_key
         idem_key = IdempotencyKey(raw_key) if raw_key else None
         command = CreateOperationCommand(
             type=request.type,
             target_type=request.target_type,
             target_id=request.target_id,
             idempotency_key=idem_key,
         )
         result = await command_bus.send(command)
         return result.data
     ```

### 7.2 Dual-Layer Idempotency Ordering and Responsibility

Stage A enforces idempotency through two strictly ordered, non-redundant layers:

```text
Request arrives with Idempotency-Key
               │
               ▼
┌───────────────────────────────────────────────┐
│ Layer 1: Transport Middleware                 │
│ (IdempotencyMiddleware on CommandBus)         │
│ - Checks InMemoryIdempotencyStore             │
│ - Handles fast concurrent bursts (<5s)        │
│ - Synchronizes in-flight via asyncio.Event    │
└──────────────────────┬────────────────────────┘
                       │
       ┌───────────────┴───────────────┐
       ▼ Cache Hit                     ▼ Cache Miss / Evicted
Replay cached CommandResult      Execute Command Handler
(No DB or Handler execution)           │
                                       ▼
┌───────────────────────────────────────────────┐
│ Layer 2: Domain Persistence                   │
│ (SQLOperationRepository & DB Unique Index)    │
│ - Checks operations table for idempotency_key │
│ - Survives backend process restarts           │
│ - Re-attaches client to existing Operation    │
└───────────────────────────────────────────────┘
```

1. **Layer 1: Transport / CommandBus Middleware (`IdempotencyMiddleware`):**
   - **Prerequisite Bugfix:** Registered on the production `CommandBus` in `backend/app/registration.py:319`.
   - **Responsibility:** Intercepts commands inside `command_bus.send(command)` *before* any domain handler runs.
   - **Behavior:**
     - Checks `InMemoryIdempotencyStore`. If key is completed, returns cached `CommandResult` immediately.
     - If key is currently in-flight, awaits result via `asyncio.Event`.
     - Releases reservation on exception or failure.
2. **Layer 2: Domain / Persistence (`operations` table unique constraint):**
   - **Responsibility:** Durable idempotency across backend restarts when `InMemoryIdempotencyStore` has been wiped.
   - **Behavior:**
     - When `CreateOperationHandler` executes, it queries `operations` for `(target_type, target_id, idempotency_key)`.
     - If an active operation exists (`QUEUED`, `PREPARING`, `RUNNING`), it returns the active operation's details (HTTP 200/202). No second task is spawned.
     - If a completed operation exists, it returns the completed operation details.
     - If a failed operation exists, it returns HTTP 409 Conflict (must invoke explicit retry).
     - Concurrent insertions that bypass in-memory locks hit the database unique index `uq_operations_target_idempotency`, where `IntegrityError` is caught and converted to a safe load of the existing row.

---

## 8. Event Envelope and Event Contract

### 8.1 Base Envelope Specification

Every operation event inherits from `app.core.event_bus.DomainEvent` and conforms to the version 1 envelope, including a **strictly monotonic per-operation sequence number (`event_seq`)**:

```json
{
  "event_id": "c1f8a84a-9b7e-4d56-89d1-3e4b7c2a1f09",
  "event_type": "OperationStepEvent",
  "timestamp": 1727280000.123,
  "correlation_id": "req-987654",
  "schema_version": 1,
  "operation_id": "op_550e8400-e29b-41d4-a716-446655440000",
  "event_seq": 3,
  "target_type": "server",
  "server_id": "srv_3f4a9b2c",
  "step_id": "MATERIALIZE_STAGING",
  "sequence": 2,
  "status": "IN_PROGRESS",
  "elapsed_ms": 1204,
  "progress": 0.45,
  "message_key": "operations.steps.materializing",
  "safe_to_retry": true,
  "context": {
    "files_copied": 142,
    "total_bytes": 10485760
  }
}
```

### 8.2 Monotonic Sequence Numbering (`event_seq`)

- Each `Operation` aggregate maintains an integer counter `event_seq: int` initialized to `0`.
- Every domain event emitted by the operation increments `event_seq` by 1:
  - `OperationStartedEvent`: `event_seq = 1`
  - Subsequent step, log, or progress events: `event_seq = 2, 3, 4...`
  - Final terminal event (`OperationCompletedEvent`, `OperationFailedEvent`, `OperationCancelledEvent`): final incremented integer.
- The `event_seq` is persisted on `operations.last_event_seq` to guarantee monotonicity even across step updates.

### 8.3 Canonical Stage A Events

The following domain events are defined in `backend/app/modules/operations/domain/events.py`:

1. `OperationStartedEvent`:
   - Emitted when an operation transitions to `PREPARING` or `RUNNING`.
   - Fields: `operation_id`, `event_seq`, `type`, `target_type`, `target_id`, `server_id`, `actor_id`, `created_at`.
2. `OperationStepEvent`:
   - Emitted whenever a step transitions status or reports progress.
   - Fields: `operation_id`, `event_seq`, `server_id`, `step_id`, `sequence`, `status`, `progress`, `elapsed_ms`, `message_key`, `safe_to_retry`, `context`.
3. `OperationLogEvent`:
   - Emitted to stream discrete log lines or diagnostics associated with the operation.
   - Fields: `operation_id`, `event_seq`, `server_id`, `step_id`, `level`, `message`, `timestamp`.
4. `OperationCompletedEvent`:
   - Emitted when an operation transitions to `COMPLETED`.
   - Fields: `operation_id`, `event_seq`, `target_type`, `target_id`, `server_id`, `type`, `elapsed_ms`, `finished_at`.
5. `OperationFailedEvent`:
   - Emitted when an operation transitions to `FAILED` or `TIMED_OUT`.
   - Fields: `operation_id`, `event_seq`, `target_type`, `target_id`, `server_id`, `type`, `failure_code`, `error_message`, `failed_step_id`, `elapsed_ms`, `finished_at`.
6. `OperationCancelledEvent`:
   - Emitted when an operation transitions to `CANCELLED`.
   - Fields: `operation_id`, `event_seq`, `target_type`, `target_id`, `server_id`, `type`, `elapsed_ms`, `finished_at`.

---

## 9. Event Contract Enforcement

### 9.1 Additions to `contracts/events.yaml`

The following section is added to `contracts/events.yaml`:

```yaml
  operation.started:
    version: 1
    payload:
      operation_id: string
      event_seq: integer
      type: string
      target_type: string
      target_id: string?
      server_id: string?
      actor_id: string?
      created_at: float

  operation.step:
    version: 1
    payload:
      operation_id: string
      event_seq: integer
      server_id: string?
      step_id: string
      sequence: integer
      status: string
      progress: float?
      elapsed_ms: integer
      message_key: string?
      safe_to_retry: boolean
      context: object

  operation.log:
    version: 1
    payload:
      operation_id: string
      event_seq: integer
      server_id: string?
      step_id: string?
      level: string
      message: string
      timestamp: float

  operation.completed:
    version: 1
    payload:
      operation_id: string
      event_seq: integer
      target_type: string
      target_id: string?
      server_id: string?
      type: string
      elapsed_ms: integer
      finished_at: float

  operation.failed:
    version: 1
    payload:
      operation_id: string
      event_seq: integer
      target_type: string
      target_id: string?
      server_id: string?
      type: string
      failure_code: string
      error_message: string
      failed_step_id: string?
      elapsed_ms: integer
      finished_at: float

  operation.cancelled:
    version: 1
    payload:
      operation_id: string
      event_seq: integer
      target_type: string
      target_id: string?
      server_id: string?
      type: string
      elapsed_ms: integer
      finished_at: float
```

### 9.2 Automated Contract Verification

A dedicated automated test suite (`backend/tests/core/test_operation_events_contract.py`) validates that:
1. Every event listed in `contracts/events.yaml` under `operation.*` has a corresponding Pydantic `DomainEvent` class in `backend/app/modules/operations/domain/events.py`.
2. Every field defined in the contract exists on the Python class with compatible typing, nullability, and inclusion of `event_seq`.
3. Every serialized event dictionary validates cleanly against the YAML specification.

### 9.3 Breaking Change Rules

A change to an `operation.*` event contract is classified as **BREAKING** if:
- A field is removed or renamed.
- A field's data type is altered.
- A previously optional field is made mandatory (`nullable=False`).
- An existing enum value for `status` or `type` is removed or modified.

Breaking changes require a D2 Governance decision, a major version bump in `contracts/events.yaml` (e.g. `version: 2`), and an envelope `schema_version` increment. Non-breaking additions require D1 approval.

---

## 10. EventBus / WebSocket Projection

### 10.1 Channel Routing Architecture

Stage A extends `backend/app/websocket/`:

1. **Channel Patterns (`authorization.py`):**
   - Add `"operation:*": {"admin:full"}`.
   - Add `"operation:{operation_id}": {"server:read"}`.
   - Add `"operation"` to `valid_prefixes` in `ChannelAuthorizer.validate_channel()`.
2. **Dispatch Allowlist (`dispatcher.py`):**
   - Add to `WS_DISPATCH_ALLOWLIST`:
     - `OperationStartedEvent`
     - `OperationStepEvent`
     - `OperationLogEvent`
     - `OperationCompletedEvent`
     - `OperationFailedEvent`
     - `OperationCancelledEvent`
3. **Channel Resolution (`dispatcher.py:_resolve_channels()`):**
   - For any operation event:
     - Always route to `operation:{event.operation_id}`.
     - If `event.server_id` is present, also route to `server:{event.server_id}` and `server:*`.

### 10.2 Gap Detection via `event_seq`

When the frontend receives an `operation.*` event frame:
1. It compares `event.event_seq` against the last received `event_seq` for that `operation_id`.
2. If `event.event_seq == last_event_seq + 1`, the event is applied immediately.
3. If `event.event_seq > last_event_seq + 1`, a network event drop is confirmed. The store triggers TanStack Query to refetch `GET /api/v1/operations/{id}` to restore authoritative state.

---

## 11. Persistence / Database Design

### 11.1 Proposed Tables

Stage A introduces two new tables: `operations` and `operation_steps`.

> **Scope Note:** `operation_artifacts` is explicitly **deferred to Stage B**.

#### Table: `operations`

```sql
CREATE TABLE operations (
    id VARCHAR(36) PRIMARY KEY,
    type VARCHAR(64) NOT NULL,
    target_type VARCHAR(32) NOT NULL,
    target_id VARCHAR(36),
    actor_id VARCHAR(36),
    status VARCHAR(32) NOT NULL DEFAULT 'QUEUED',
    idempotency_key VARCHAR(64),
    current_step_id VARCHAR(64),
    last_event_seq INTEGER NOT NULL DEFAULT 0,
    failure_code VARCHAR(64),
    error_message TEXT,
    cancellation_requested BOOLEAN NOT NULL DEFAULT FALSE,
    timeout_seconds INTEGER NOT NULL DEFAULT 600,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP WITH TIME ZONE,
    finished_at TIMESTAMP WITH TIME ZONE,
    metadata_json JSON
);

CREATE INDEX idx_operations_type ON operations(type);
CREATE INDEX idx_operations_status ON operations(status);
CREATE INDEX idx_operations_target ON operations(target_type, target_id);
CREATE INDEX idx_operations_created_at ON operations(created_at);
CREATE UNIQUE INDEX uq_operations_target_idempotency 
    ON operations(target_type, target_id, idempotency_key) 
    WHERE idempotency_key IS NOT NULL;
```

#### Table: `operation_steps`

```sql
CREATE TABLE operation_steps (
    id VARCHAR(36) PRIMARY KEY,
    operation_id VARCHAR(36) NOT NULL REFERENCES operations(id) ON DELETE CASCADE,
    step_id VARCHAR(64) NOT NULL,
    sequence INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    progress FLOAT,
    elapsed_ms INTEGER NOT NULL DEFAULT 0,
    message_key VARCHAR(128),
    safe_to_retry BOOLEAN NOT NULL DEFAULT FALSE,
    context_json JSON,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT uq_operation_step_sequence UNIQUE (operation_id, sequence),
    CONSTRAINT uq_operation_step_id UNIQUE (operation_id, step_id)
);

CREATE INDEX idx_operation_steps_operation ON operation_steps(operation_id);
CREATE INDEX idx_operation_steps_status ON operation_steps(status);
```

### 11.2 Transaction Boundaries

- **Operation Creation:** Insert into `operations` and bulk insert planned `operation_steps` occurs within a single database transaction.
- **Step Transitions:** As each step begins, updates progress, or finishes, a dedicated, brief database transaction updates `operation_steps` and `operations.current_step_id` / `operations.last_event_seq`.
- **Terminal Transition:** Final status update (`COMPLETED`, `FAILED`, `CANCELLED`) and `finished_at` commit in a single transaction.

---

## 12. API and Permission Boundaries

### 12.1 Exact REST Endpoints and Canonical Permissions

All endpoints reside in `backend/app/api/v1/routers/operations.py`. To ensure strict agreement with `scripts/check-route-contract`, each endpoint specifies **exactly one permission string** with zero aliases or alternative wording:

#### 1. `POST /api/v1/operations`
- **Description:** Create and start a new operation (or return existing if idempotency key matches).
- **Permission:** `permission: "server:write"`
- **Input:** `CreateOperationRequest` (type, target_type, target_id, metadata, optional idempotency_key).
- **Output:** `OperationDetailResponse` (HTTP 202 Accepted).
- **Errors:** HTTP 400 (Bad Request), HTTP 409 (Conflict if concurrent mutating operation active on target).

#### 2. `GET /api/v1/operations/{operation_id}`
- **Description:** Retrieve complete operation details, including all steps and current status.
- **Permission:** `permission: "server:read"`
- **Input:** `operation_id: str` (path parameter).
- **Output:** `OperationDetailResponse` (HTTP 200).
- **Errors:** HTTP 404 (Not Found).

#### 3. `GET /api/v1/operations`
- **Description:** List operations with optional filtering.
- **Permission:** `permission: "server:read"`
- **Input Query Params:** `target_type: str | None`, `target_id: str | None`, `status: str | None`, `limit: int = 50`.
- **Output:** `list[OperationSummaryResponse]` (HTTP 200).

#### 4. `POST /api/v1/operations/{operation_id}/cancel`
- **Description:** Request cooperative cancellation of an active operation.
- **Permission:** `permission: "server:write"`
- **Input:** `operation_id: str` (path parameter).
- **Output:** `OperationDetailResponse` (HTTP 202 Accepted, status `CANCEL_REQUESTED` or terminal).
- **Idempotency:** Idempotent. Calling cancel on an already-cancelling or terminal operation returns the current status safely.
- **Errors:** HTTP 404 (Not Found), HTTP 409 (Conflict if operation is in terminal state).

#### 5. `POST /api/v1/operations/{operation_id}/retry`
- **Description:** Retry a failed or timed-out operation from the failed step.
- **Permission:** `permission: "server:write"`
- **Input:** `operation_id: str` (path parameter).
- **Output:** `OperationDetailResponse` (HTTP 202 Accepted).
- **Idempotency:** Safe. Handled by verifying `safe_to_retry` on the failed step.
- **Errors:** HTTP 404 (Not Found), HTTP 409 (Conflict if operation is not failed or step is not marked `safe_to_retry`).

### 12.2 Route Contract Alignment

The 5 routes will be cataloged in `contracts/permissions.yaml` under `route_permissions`:

```yaml
  # operations
  "GET /api/v1/operations": {permission: "server:read", status: enforced}
  "POST /api/v1/operations": {permission: "server:write", status: enforced}
  "GET /api/v1/operations/{operation_id}": {permission: "server:read", status: enforced}
  "POST /api/v1/operations/{operation_id}/cancel": {permission: "server:write", status: enforced}
  "POST /api/v1/operations/{operation_id}/retry": {permission: "server:write", status: enforced}
```

This guarantees `scripts/check-route-contract` passes cleanly, advancing verified route coverage from 150/150 to 155/155.

---

## 13. Frontend Architecture

### 13.1 Component Hierarchy

The operations frontend resides in `frontend/src/operations/`:

```text
frontend/src/operations/
├── components/
│   ├── OperationDrawer.tsx       # Slide-over container with slide-in animation
│   ├── OperationStepper.tsx      # Vertical step progress list with icons
│   ├── OperationFailure.tsx      # Failure banner, error code, and retry button
│   ├── OperationLogs.tsx         # Live log stream viewer
│   └── OperationHeader.tsx       # Title, status badge, target name, close/cancel controls
├── stores/
│   └── operationStore.ts         # Zustand store holding active operation state
├── hooks/
│   ├── useOperation.ts           # React hook for TanStack Query + WS subscription
│   └── useActiveOperations.ts    # Hook for tracking operations per target
└── types.ts                      # TypeScript interfaces matching backend schemas
```

### 13.2 Visual & UX Flow

1. **Trigger:** A user action (e.g. test run) initiates an operation. The API returns `{ "operation_id": "op_123" }`.
2. **Drawer Open:** `useOperationStore.getState().openDrawer("op_123")` activates `OperationDrawer`.
3. **Subscription:** `useOperation("op_123")` subscribes to WebSocket channel `operation:op_123`.
4. **Rendering:**
   - Completed steps render with green checkmark icon (`StatusBadge` styling).
   - In-progress step displays `LoaderBadge` with spinner and live elapsed seconds.
   - Pending steps render with neutral outlined circles.
5. **Failure Presentation:**
   - If an error occurs, `OperationFailure` renders a prominent alert with the machine-readable `failure_code`, error description, and a "Retry" button (if `safe_to_retry == True`).
6. **Cancellation:** "Cancel Operation" button sends `POST /api/v1/operations/{id}/cancel` and disables inputs while cancellation cleanup runs.

### 13.3 Reactive State Management: `operationStore.ts`

```typescript
interface OperationState {
  activeOperations: Map<string, OperationDetail>;
  activeDrawerId: string | null;
  openDrawer: (operationId: string) => void;
  closeDrawer: () => void;
  handleWsEvent: (event: OperationEvent) => void;
}
```

When WebSocket messages arrive via `frontend/src/websocket/handler.ts`, `handleWsEvent` patches the corresponding `OperationDetail`. If an event arrives with `event.event_seq > last_seq + 1`, a missed event gap is detected and the store triggers a TanStack Query refetch to ensure consistent synchronization.

---

## 14. Failure / Timeout / Cancellation Semantics

| Scenario | System Reaction | User Visibility |
|---|---|---|
| **Duplicate Command Submission** | Detected by `IdempotencyMiddleware` (Layer 1) or `operations` table (Layer 2). Existing operation returned. | UI re-attaches to running drawer; no duplicate task spawned. |
| **Backend Process Dies** | Reconciler on startup detects unfinished operations in DB. `RUNNING`/`PREPARING` marked `FAILED` with `PROCESS_TERMINATED`. `QUEUED` handled per `ONX_OPERATION_STARTUP_QUEUE_POLICY` (`PURGE` [default] marked `QUEUE_PURGED_ON_RESTART` or `RE_DISPATCH`). | On next login, running operation shows `FAILED` with code `PROCESS_TERMINATED`. |
| **Database Transaction Rollback** | Step failure rolls back step status; operation marked `FAILED` in a new clean transaction. | Step shows error; database remains consistent. |
| **EventBus Handler Error** | Handler error is trapped and logged; event routed to `dead_letter_queue`. | Operation execution continues; telemetry alerts admins. |
| **WebSocket Disconnects** | Reconnect backoff runs. Upon reconnect, missed events replayed from buffer or refetched via REST. | Brief banner "Reconnecting..."; UI syncs upon reconnect. |
| **Operation Times Out** | Conditional update sets `TIMED_OUT` if cancellation not committed. Compensation cleanup runs. | Step marked failed; failure card shows `OPERATION_TIMEOUT`. |
| **Cancellation Requested** | Conditional update sets `CANCEL_REQUESTED` if not already terminal. Cleanup runs; transitions to `CANCELLED`. | Stepper indicates "Cancelling..."; transitions to `CANCELLED`. |
| **Out-of-Order WS Events** | Frontend compares `event_seq`. Stale events ignored; gap triggers full REST refetch. | Stepper does not regress to earlier steps. |

---

## 15. Concurrency and Race Conditions

### 15.1 Per-Target Concurrency Guard

1. **Live-Server Mutating Operations:**
   - Mutating operations that alter live server state (e.g. `START_SERVER`, `STOP_SERVER`, `RESTART_SERVER`, `DELETE_SERVER`, `BACKUP_RESTORE`, `UPDATE_SERVER`) enforce strict mutual exclusion per server.
   - When creating such an operation for a `server_id`, the handler checks for existing active operations (`status in ('QUEUED', 'PREPARING', 'RUNNING')`). If found, it returns HTTP 409 Conflict (`OperationConcurrencyConflictError`).
2. **Exemption for `RUN_TEST` Operations (Stage D Concurrency Preservation):**
   - Operations of type `RUN_TEST` operate entirely in isolated worktree staging (`.onx/tests/<test_id>`) and ephemeral Docker containers without altering live server binaries, world data, or active ports.
   - Therefore, `RUN_TEST` operations are **explicitly exempt** from the per-server mutual exclusion lock. Multiple test runs targeting the same server are permitted to run concurrently, strictly preserving the Stage D concurrency model where test execution is governed by the global admission gate (`admit()` checking total RAM and CPU core earmarks) rather than a coarse per-server lock.

### 15.2 Database Concurrency on Idempotency

The unique constraint `uq_operations_target_idempotency` guarantees that concurrent API requests cannot write two operations with the same idempotency key.

### 15.3 Step Advancement Race

Only the designated operation worker task calls `complete_step()` and `start_step()`. Step updates are serialized in Python via the operation task loop, avoiding write collisions on `operation_steps`.

---

## 16. Cross-Platform Constraints

To satisfy ONX multi-platform requirements (Local Linux, Local Windows, Docker):
1. **No Unix-Only Process Signals:** Cancellation and timeout rely strictly on Python `asyncio` cancellation, cooperative boolean flags (`cancellation_requested`), and `app.core.process_utils` (which supports Windows `OpenProcess` / `taskkill`). No raw `signal.SIGKILL` or POSIX signal handlers.
2. **Platform-Neutral Paths:** All path representations in operation context payloads must use forward slashes or `pathlib.Path` normalization.
3. **No `/tmp` Assumptions:** Temporary staging directories must use `tempfile.gettempdir()` or the server's configured storage directory.
4. **Monotonic Clocks:** Elapsed time calculations use `time.monotonic()` or timezone-aware UTC timestamps (`datetime.now(UTC)`), ensuring resilience against host clock adjustments or NTP sync jumps.

---

## 17. Security Considerations

1. **Authorization Scoping:**
   - Operations inherit the authorization scope of their target. An operation on server `srv_123` requires `server:read` (for view) or `server:write` (for creation, cancel, and retry).
   - Users cannot view or mutate operations belonging to servers they do not own or manage.
2. **Context Sanitization:**
   - Operation steps and context payloads must **never** store or emit passwords, RCON secrets, private tokens, or encryption keys.
   - The `metadata_json` and `context_json` serializers pass data through a sanitization filter that masks sensitive key names (`password`, `token`, `secret`, `key`).
3. **Rate Limiting:**
   - Operation creation endpoints remain subject to FastAPI `RateLimitMiddleware` to prevent denial-of-service via resource exhaustion.

---

## 18. Tests and Verification

Stage A verification requires targeted testing across all architectural layers:

### 18.1 Unit Tests
- `backend/tests/unit/modules/operations/test_operation_aggregate.py`:
  - Valid state transitions (`QUEUED` -> `PREPARING` -> `RUNNING` -> `COMPLETED`).
  - Strict rejection of invalid state transitions (raising `InvalidStateTransitionError`).
  - Cancellation flag toggling and timeout marking with atomic rowcount precedence.
  - Step progression, sequence ordering, monotonic `event_seq` generation, and elapsed millisecond calculations.
- `backend/tests/unit/modules/operations/test_operation_events.py`:
  - Event instantiation, schema validation, and serialization.
- `backend/tests/unit/modules/operations/test_idempotency_behavior.py`:
  - Deduplication logic when an idempotency key is re-submitted.

### 18.2 Integration Tests
- `backend/tests/integration/modules/operations/test_operation_repository.py`:
  - Database persistence with SQLite in-memory engine.
  - Cascade deletion of `operation_steps` when an `operation` is removed.
  - Verification of unique constraint on `(target_type, target_id, idempotency_key)`.
  - Verification of sequence uniqueness on `(operation_id, sequence)`.
  - Verification of crash recovery: `PREPARING`/`RUNNING` transition to `PROCESS_TERMINATED`, while `QUEUED` are handled per `ONX_OPERATION_STARTUP_QUEUE_POLICY`.
- `backend/tests/integration/modules/operations/test_operations_api.py`:
  - REST route testing for all 5 endpoints (`POST` create, `GET` by id, `GET` list, `POST` cancel, `POST` retry).
  - Permission enforcement against canonical strings (`server:read`, `server:write`).
  - Concurrency testing: verify live mutations conflict while concurrent `RUN_TEST` operations succeed.
  - HTTP 409 Conflict on invalid cancellation or non-retryable retry requests.
- `backend/tests/integration/modules/operations/test_websocket_projection.py`:
  - Publishing operation domain events to `EventBus`.
  - Delivery to subscribed clients on `operation:{id}` and `server:{id}`.
  - Verification of `WS_DISPATCH_ALLOWLIST` filtering.

### 18.3 Contract Verification Tests
- `backend/tests/core/test_operation_events_contract.py`:
  - Automated comparison between `contracts/events.yaml` and `backend/app/modules/operations/domain/events.py`.
  - Verification that required payload fields match exactly, including `event_seq`.

### 18.4 Frontend Tests
- `frontend/src/operations/stores/operationStore.test.ts`:
  - Event reduction and step updates in Zustand store.
  - Verification of gap detection on missed `event_seq`.
- `frontend/src/operations/components/OperationDrawer.test.tsx`:
  - Drawer rendering in `RUNNING`, `FAILED`, and `COMPLETED` states.
  - Correct rendering of step progress and failure error codes.
  - Cancel button click triggering API invocation.
- `frontend/src/operations/components/OperationStepper.test.tsx`:
  - Visual display of pending, active, and completed step icons.

### 18.5 Regression Gates
- Verify that all existing quality gates pass:
  - `scripts/check-db-revision`
  - `scripts/check-ruff-baseline`
  - `scripts/check-version-propagation`
  - `scripts/check-route-contract` (155 routes verified)
  - `scripts/check-ps1-bom`
  - `scripts/check-stray-db`

---

## 19. Affected Components

### Backend Components
- `backend/app/modules/operations/` (New module: domain, application, infrastructure, API).
- `backend/app/modules/versioning/application/commands/run_isolated_test.py` (Only existing command handler modified in Stage A).
- `backend/app/modules/versioning/infrastructure/test_runner.py` (Step transition call sites for test runs).
- `backend/app/registration.py` (Add router, bus registrations; prerequisite bugfix: attach `IdempotencyMiddleware`).
- `backend/app/websocket/authorization.py` (Add `operation` channel pattern and valid prefix).
- `backend/app/websocket/dispatcher.py` (Add operation events to `WS_DISPATCH_ALLOWLIST` and channel routing).
- `backend/alembic/versions/b1e2100000021_stage_a_operations.py` (New migration adding `operations` and `operation_steps`).
- `contracts/events.yaml` (Add `operation.*` schemas with `event_seq`).
- `contracts/permissions.yaml` (Add 5 operations route permissions with `server:read` / `server:write` advancing route contract to 155 routes).

### Frontend Components
- `frontend/src/operations/` (New module: `OperationDrawer`, `OperationStepper`, `OperationFailure`, `operationStore.ts`).
- `frontend/src/websocket/channels.ts` (Add operation channel helper).
- `frontend/src/websocket/handler.ts` (Route operation events to `operationStore`).
- `frontend/src/services/api.ts` (Add operations REST API client methods to the existing API client).

---

## 20. Dependencies

1. **Prerequisite Bugfix:**
   - Registration of `IdempotencyMiddleware` on the production `CommandBus` in `backend/app/registration.py`. This must be tested and confirmed before or alongside Stage A deployment.
2. **Database Migration:**
   - Alembic migration `b1e2100000021_stage_a_operations.py` depends on current head `b1e2100000020_add_server_startup_timeout_seconds.py`.

---

## 21. Migration / Rollout Strategy

1. **Alembic Migration:**
   - Add additive tables `operations` and `operation_steps`.
   - Zero modifications to existing tables (`servers`, `server_test_runs`, `backups`).
   - Reversible via standard `downgrade()`.
2. **Contract Update:**
   - Additive update to `contracts/events.yaml` and `contracts/permissions.yaml`.
   - `scripts/check-route-contract` validates 155 routes.
3. **Deployment Safety:**
   - Completely non-breaking for existing clients. Older UI versions ignore the new WebSocket channels.

---

## 22. Out of Scope

The following items are **strictly excluded** from Stage A and must NOT be implemented in this stage:
- **Stage B Test Run Engine:** Execution runner overhaul, assertion engine, cleanup plans, evidence aggregation bundles.
- **Stage C Verification Tiers:** Bootstrap verification (Tier 1), synthetic player bot verification (Tier 2), ingress/DNS verification (Tier 3), synthetic load profiles (Tier 4), chaos verification (Tier 5).
- **Stage D Safe Change Pipeline:** `ChangeCandidate` aggregate, candidate revision branching, staging materialization, compatibility gating, promotion service, rollback engine.
- **Stage E Modpack Platform:** Modrinth discovery, `.mrpack` parser, secure downloader, dependency graph resolution, modpack installer UI.
- **Stage F/G Hardening:** Chaos injection resilience, broad cross-platform activation matrix.
- **Generic Event-Governance Rewrite:** No rewriting or refactoring of the 31 legacy domain events in `contracts/events.yaml`.
- **Unrelated Frontend/CommandBus Refactors:** No general styling overhaul or unrelated bus rewrites.

---

## 23. Open Questions / Decision Gates

1. **D2 Decision Gate — Storage Backing for CommandBus Idempotency:**
   - *Question:* Should `InMemoryIdempotencyStore` on the CommandBus be upgraded to a SQLite-backed store in Stage A, or should CommandBus transport deduplication remain in-memory while relying on the persistent `operations` table for domain-level idempotency?
   - *Recommendation:* Keep `InMemoryIdempotencyStore` for CommandBus transport deduplication (handling short-window network retries) while relying on the durable `operations` database table for long-lived operational idempotency across server restarts. This avoids adding an extra cache table while guaranteeing full persistence where it matters.

---

## 24. Design Review Checklist

- [x] **Root Cause:** Solves the lack of operational tracking, user visibility, and deduplication for long-running workflows.
- [x] **Scope Discipline:** Strictly bounded to Stage A primitives. Stages B–G are excluded. Only `RunIsolatedTestHandler` is wired in Stage A.
- [x] **Architecture Boundaries:** Clean DDD placement in `backend/app/modules/operations/`; does not displace `ServerTestRun` or `BackupJob`.
- [x] **Existing Utilities Reused:** Reuses `ConnectionRegistry`, `EventDispatcher`, `OfflineMessageBuffer`, `StatusBadge`, `LoaderBadge`, and `toastStore`.
- [x] **Duplication Risk Avoided:** Does not create redundant execution engines; acts as an orchestration umbrella.
- [x] **DB Conventions Followed:** Tables named `operations` and `operation_steps` with explicit indexes and cascading foreign keys.
- [x] **API Contracts Verified:** 5 explicit endpoints designed with exact canonical permissions (`server:read`, `server:write`).
- [x] **Permission Contracts Preserved:** Strictly adheres to single canonical string per route; verified for `scripts/check-route-contract` at 155 routes.
- [x] **Portability Maintained:** Platform-neutral Python async execution, UTC clocks, no POSIX signal assumptions.
- [x] **Failure Handling Detailed:** Covers process crashes, timeouts, cooperative cancellations, and database rollbacks.
- [x] **Test Sufficiency:** Defines unit, integration, contract, and frontend verification suites.

---

## 25. Implementation Order

The implementation of Stage A should proceed in the following safe, incremental order:

1. **Prerequisite Bugfix:**
   - Register `IdempotencyMiddleware` on `command_bus` in `backend/app/registration.py` with integration test verification.
2. **Domain Layer:**
   - Create `backend/app/modules/operations/domain/` (`enums.py`, `entities.py`, `aggregate.py`, `events.py`, `repository.py`).
   - Add unit tests for state machine, `event_seq` generation, and step progression.
3. **Database Migration & Infrastructure:**
   - Create SQLAlchemy models in `backend/app/modules/operations/infrastructure/models.py`.
   - Author Alembic migration `b1e2100000021_stage_a_operations.py`.
   - Implement `SQLOperationRepository`.
   - Add repository integration tests.
4. **Application & Service Layer:**
   - Implement commands, queries, `OperationService`, and `OperationExecutor` (with lifespan shutdown integration).
   - Wire `RunIsolatedTestHandler` and `test_runner.py` step emission call sites (`MATERIALIZE_STAGING`, etc.).
   - Add unit and integration tests for cooperative cancellation, atomic timeout/cancel precedence, and crash recovery.
5. **Event Contract & Enforcement:**
   - Add `operation.*` specifications with `event_seq` to `contracts/events.yaml`.
   - Implement `backend/tests/core/test_operation_events_contract.py`.
6. **WebSocket Projection:**
   - Extend `authorization.py` (channel patterns and valid prefixes).
   - Extend `dispatcher.py` (`WS_DISPATCH_ALLOWLIST` and `_resolve_channels`).
   - Add WebSocket projection integration tests.
7. **REST API & Route Contract:**
   - Create FastAPI router in `backend/app/api/v1/routers/operations.py` (5 routes).
   - Update `contracts/permissions.yaml` with the 5 new endpoints (`server:read` / `server:write`).
   - Run `scripts/check-route-contract` to verify 155 routes pass.
8. **Frontend Implementation:**
   - Create `frontend/src/operations/types.ts` and `operationStore.ts` (with gap detection).
   - Implement `OperationDrawer.tsx`, `OperationStepper.tsx`, and `OperationFailure.tsx`.
   - Wire WebSocket handlers in `frontend/src/websocket/handler.ts`.
   - Add operations API client methods to `frontend/src/services/api.ts`.
   - Add frontend unit tests in Vitest.
9. **Final Quality Verification:**
   - Run all 6 CI quality gate scripts and full test suites to verify zero regressions.
