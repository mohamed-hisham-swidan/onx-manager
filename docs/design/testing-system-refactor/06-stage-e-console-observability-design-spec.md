# Design Spec — Stage E: Console & Observability (Streaming & Unified Telemetry)

**Status:** BUILT & VERIFIED (Commits `41da076` & `0b64ef2`, 2026-09-17/18)
**Roadmap placement:** ONX Manager Phase 7 / Enterprise Branch Runtime (Stage E)  
**Verification:** 2,859 passed / 6 skipped / 0 failed backend, 711 frontend passed across 79 files, 6/6 CI quality gates PASS, route contract preserved at 141/141.

---

## Goal

Activate and unify the real-time observability and interactive control plane across both production servers and ephemeral isolated test containers:
1. **Pressurize the WebSocket console delivery pipeline**: Connect an asynchronous, demand-driven log follower loop to the existing `broadcast_console_lines()` inlet on `server:{server_id}:console` (and test targets), eliminating redundant 3-second HTTP frontend polling.
2. **Interactive bidirectional WS exec/input**: Extend the WebSocket message plane with an `exec_input` protocol supporting interactive command execution and PTY/session semantics across both live servers and ephemeral `onx-test-*` containers, backed by provider capability extensions and unified RBAC.
3. **Migrate metrics collection to unified `docker stats`**: Migrate CPU, RAM, network I/O, and block I/O telemetry in `MetricsCollector` to batch `docker stats` sampling across both live and test containers, while strictly retaining RCON/process inspection for TPS and player counts on live servers.
4. **Implement simple HTTP re-tail on reconnect**: Establish clean client-side re-tail backfill via the existing HTTP console endpoint upon WebSocket reconnection, rejecting cursor/offset complexity.
5. **Formalize correlation and runtime boundaries**: Confirm live-server crash correlation and tiered retention as shipped, defer test-run evidence correlation and domain `Runtime` construction to Stage F, and record the Runtime-trigger resolution note.

---

## Current Behavior

- **WebSocket delivery plane is pressurized but inlet is dry**:
  A complete WebSocket infrastructure is fully shipped in `backend/app/websocket/` (`endpoint.py`, `dispatcher.py`, `handlers.py`, `manager.py`, `serializers.py`, `buffer.py`, `authentication.py`, `authorization.py`, `rate_limiter.py`).
  In `endpoint.py:105-111`, `broadcast_console_lines(server_id, lines)` formats a `console` message and broadcasts it to `server:{server_id}:console`. However, **it has ZERO callers in the entire codebase**. The delivery pipe is pressurized and fully authorized, but no publisher loop feeds lines into it.
- **Provider console and exec are one-shot request/response**:
  In `modules/server/infrastructure/providers/base.py`, `ServerProvider` exposes `console(handle, tail) -> list[str]` and `execute_command(handle, command) -> str`.
  - In `docker.py:673-680`, `console()` executes a one-shot subprocess `docker logs --tail {tail} --timestamps {container_name}`. There is no continuous streaming or follow primitive (`docker logs -f`).
  - In `docker.py:682-724`, `execute_command()` executes a one-shot command over RCON (or fallback `docker exec {container} rcon-cli "{command}"`). It provides no interactive stdin streaming or PTY semantics.
  - In `local.py:450-485`, `console()` runs `tmux capture-pane -t {session} -p -S -{tail}` and `execute_command()` runs `tmux send-keys`.
- **Test containers are completely unobserved**:
  `DockerTestExecutionRunner` (`modules/versioning/infrastructure/test_runner.py:225`) spawns isolated containers named `onx-test-{spec.test_id}`. These containers do not emit metrics to `MetricsCollector`, are not hooked into console streaming, and never accept commands via `execute_command()`.
- **Metrics telemetry relies on host psutil process inspection**:
  `MetricsCollector` (`modules/monitoring/infrastructure/collector.py:243-350`) collects data only for servers registered in the database with status `running`.
  - RAM and CPU are collected via `_collect_process_metrics(pid)` (`collector.py:82-116`) using host `psutil.Process(pid)`. For containerized servers, host PID inspection measures host RSS rather than cgroup limits, fails if PID namespaces diverge, and yields zero network or block I/O.
  - TPS and player counts are queried via persistent RCON connections (`PersistentRCONClient`).
  - Data is saved to `SQLMetricRepository` and broadcast via `MetricCollectedEvent` to `MetricsBatcher` and the WebSocket plane.
- **Frontend relies on 3-second HTTP polling**:
  In `frontend/src/server_manager/components/ServerConsole.tsx:77-81`, the frontend polls `api.getServerConsole(serverId, 200)` every 3,000ms via TanStack Query (`refetchInterval: 3000`). While it mounts `useConsoleStream(serverId)` (`:94`), no lines ever arrive via WebSocket, so the component falls back entirely to polling. The frontend has no reconnect re-tail logic: if the socket drops, it reconnects at transport level (`WSClient.ts`), but `ServerConsole.tsx` does not synchronize or backfill logs.
- **Crash correlation and tiered retention are live-server only**:
  - Live-server crash correlation is fully operational: `LogBasedEvidenceCollector` collects tails and crash reports; `PatternCrashAnalyzer` classifies crashes and blames mods; `EventDispatcher` broadcasts `ServerCrashedEvent` and `CrashClassifiedEvent` over WebSocket.
  - Tiered retention is fully operational: `event_cleanup.py` and `cleanup_task.py` purge raw metrics (2h), 1m rollups (30d), 1h rollups (365d), 1d rollups (3650d), activity logs (90d), logs (30d), and events (90d).
  - Test runs write only raw terminal strings to `server_test_runs`; they have no structured crash analysis or evidence retention.
- **Versioning `Runtime` is unconstructed**:
  Per ADR-0015 and Stage D Design Spec §(e), domain `Runtime` is defined in `versioning/domain/entities.py` but is unconstructed and unpersisted, explicitly handed off to Stage F.

---

## Proposed Change

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            FRONTEND (React 19)                              │
│                                                                             │
│  ┌─────────────────────────┐                ┌────────────────────────────┐  │
│  │    ServerConsole.tsx    │                │      WSClient / Hook       │  │
│  │  - Zero 3s poll when WS │                │  - Auto-reconnect          │  │
│  │  - HTTP re-tail on retry│◄───────────────┤  - onopen / onclose events │  │
│  └────────────┬────────────┘                └─────────────▲──────────────┘  │
└───────────────┼───────────────────────────────────────────┼─────────────────┘
                │ HTTP GET /console                         │ WS Frames
                ▼                                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       BACKEND API & WEBSOCKET LAYER                         │
│                                                                             │
│  ┌─────────────────────────┐                ┌────────────────────────────┐  │
│  │   /servers/{id}/console │                │      /ws Endpoint          │  │
│  │   (HTTP tail backfill)  │                │  - exec_input handler      │  │
│  └─────────────────────────┘                │  - RBAC permission check   │  │
│                                             └─────────────▲──────────────┘  │
│                                                           │                 │
│  ┌────────────────────────────────────────────────────────┴──────────────┐  │
│  │                     ConsoleStreamManager                              │  │
│  │  - Demand-driven: active only when channel subscriber count > 0       │  │
│  │  - Batched flush: 50 lines or 100ms cadence                           │  │
│  │  - Frame slicing & backpressure (64KB/msg, 2,000-line drop buffer)    │  │
│  └──────────────▲─────────────────────────────────────────▲──────────────┘  │
└─────────────────┼─────────────────────────────────────────┼─────────────────┘
                  │                                         │
                  │ docker logs -f                          │ docker stats
                  │ (or tmux capture)                       │ batch subprocess
                  │                                         │
┌─────────────────┴──────────────────┐   ┌──────────────────┴─────────────────┐
│     CONTAINER & PROCESS LOGS       │   │    UNIFIED METRICS COLLECTOR       │
│                                    │   │                                    │
│  • Live Server (onx-*)             │   │  • docker stats batch (all ctns)   │
│  • Test Container (onx-test-*)     │   │    - CPU, RAM, Net I/O, Block I/O  │
│  • Bare-metal tmux session         │   │  • RCON (live servers only)        │
│                                    │   │    - TPS & player count            │
└────────────────────────────────────┘   └────────────────────────────────────┘
```

### (a) The Console Publisher Loop

1. **Demand-Driven Follower Pool (`ConsoleStreamManager`)**:
   - Resides in `backend/app/modules/server/infrastructure/console_stream.py`.
   - Lifecycle is tied to WebSocket channel subscription counts in `ConnectionRegistry`:
     - When `server:{server_id}:console` (or `test:{test_id}:console`) gains its first subscriber ($0 \rightarrow 1$), `ConsoleStreamManager` starts an asynchronous follower task for that target.
     - When the subscriber count drops to 0 ($1 \rightarrow 0$), the follower task is cancelled after a **5-second debounce grace period** (preventing rapid start/stop churn during page navigation or browser reloads).
     - Global shutdown hook registered in `stop_websocket_services()` terminates all active follower tasks cleanly.

2. **Streaming Primitive Selection**:
   - **Docker targets (Live servers and `onx-test-*` containers)**:
     - Uses native asynchronous subprocess streaming:
       `docker logs --follow --timestamps --tail 0 {container_name}`
       spawned via `asyncio.create_subprocess_exec` with `stdout=PIPE`, `stderr=STDOUT`.
     - **Why `--tail 0`**: The initial buffer is always loaded via the HTTP endpoint (`GET /api/v1/servers/{server_id}/console?tail=200`). Starting the stream with `--tail 0` ensures zero duplication between the initial HTTP snapshot and the live WebSocket feed.
   - **Non-Docker targets (`LocalLinuxProvider` tmux sessions)**:
     - For bare-metal servers where `docker logs` is unavailable, `ConsoleStreamManager` uses a lightweight polling loop (250ms interval) querying `provider.console(handle, tail=50)`. It deduplicates lines using a sliding window of recent line hashes (SHA-256 ring buffer of size 200).
   - **Inlet Integration**:
     - The output lines feed directly into the existing `broadcast_console_lines(server_id, lines)` in `app/websocket/endpoint.py`, leaving the existing channel naming (`server:{server_id}:console`) and serialization format (`WSMessage(type="console", ...)`) completely unchanged.

3. **Batching, Cadence & Framing**:
   - Lines read from the stream are accumulated into a buffer and dispatched in batches rather than individual line-by-line WebSocket frames:
     - **Max batch size**: 50 lines.
     - **Max flush latency**: 100ms.
   - This prevents overwhelming the Python event loop and WebSocket client during bursty periods (e.g. server startup or stack traces).

4. **Backpressure and Frame Cap Protection**:
   - `MessageSerializer` strictly enforces `MAX_MESSAGE_SIZE = 256 * 1024` (256KB).
   - If an unconstrained logging loop produces lines faster than the WebSocket transport can drain:
     - Output is partitioned into frames strictly under 64KB.
     - If the internal queue exceeds **2,000 pending lines**, the buffer drops the oldest unbroadcast lines and injects a single synthetic marker line:
       `"[onx-console-stream] WARNING: Output rate exceeded client consumption; dropped N lines."`
     - This guarantees the publisher never crashes with `ValueError("Message exceeds maximum size of 256KB")` and protects backend memory.

---

### (b) WS Exec / Input Protocol & PTY Provider Extension

1. **Protocol Expansion on `/ws`**:
   The existing message types (`ping`, `subscribe`, `unsubscribe`, `refresh_token`) are extended with two new client-to-server messages:
   - **`exec_input`**:
     ```json
     {
       "type": "exec_input",
       "target_type": "server" | "test",
       "target_id": "string",
       "input": "string"
     }
     ```
     `input` represents either a full command string (ending in `\n`) or raw interactive characters.
   - **`exec_resize`** (optional PTY window resize):
     ```json
     {
       "type": "exec_resize",
       "target_type": "server" | "test",
       "target_id": "string",
       "cols": 80,
       "rows": 24
     }
     ```
   Server-to-client responses:
   - Output from execution streams back to the client over the subscribed console channel (`server:{server_id}:console` or `test:{test_id}:console`).
   - If execution fails synchronously, the server emits an `error` frame:
     ```json
     {
       "type": "error",
       "code": "EXEC_FAILED",
       "message": "Target container is not running"
     }
     ```

2. **Provider Extension (ADR-0015 Compliant)**:
   - Per ADR-0015, the existing capability vocabulary (`"process"`, `"console"`, `"exec"`) and signature `execute_command(handle, command) -> str` remain **strictly unchanged**.
   - `ServerProvider` interface is extended additively with an optional interactive execution method:
     ```python
     async def write_exec_input(
         self,
         handle: ServerHandle,
         input_data: str,
         interactive: bool = False,
     ) -> None: ...
     ```
   - **`DockerProvider` Implementation**:
     - For live servers with standard one-shot commands: continues to route through `AsyncRCONClient` with fallback to `docker exec {container} rcon-cli "{command}"`.
     - For interactive/raw input or test containers: writes directly to the container's stdin stream via `docker exec -i {container} rcon-cli` or container stdin.
   - **`LocalLinuxProvider` Implementation**:
     - Routes input to `tmux send-keys -t {session_name}`.

3. **Test-Container Target Handling & RBAC Authorization (Decision 3)**:
   - When `target_type == "test"`:
     1. **Identity Resolution**: `target_id` is resolved as `test_id`. The handler queries `ServerTestRunModel` via `SQLVersioningRepository` to obtain the associated `server_id` and container name (`onx-test-{test_id}`). It verifies that the run status is `RUNNING`.
     2. **Permission Check**: The user's permission set (from JWT claims held in `ChannelAuthorizer`) is validated against:
        `"server.{server_id}.console"` OR `"server:test:execute"` OR `"admin:full"`.
        If none are present, the handler rejects the message with `PERMISSION_DENIED`.
   - When `target_type == "server"`:
     1. **Identity Resolution**: `target_id` is resolved as `server_id`. The handler verifies the server exists and is in `running` status.
     2. **Permission Check**: Validated against `"server.{server_id}.console"` OR `"admin:full"`.

---

### (c) Metrics Collector Source Migration (Decision 1)

1. **Subprocess vs. Docker API**:
   - Polling is performed via **asynchronous subprocess** (`asyncio.create_subprocess_exec` calling `docker stats --no-stream --format "{{json .}}"`).
   - **Rationale**: ONX Manager has no `docker` Python SDK dependency. Every container operation across 38+ existing test suites uses CLI subprocess execution. Introducing `docker-py` would violate the zero-new-dependency invariant.

2. **Cost & Cadence: The Single-Command Batch Pattern**:
   - Calling `docker stats --no-stream` individually for $N$ containers would take $\sim 1\text{s} \times N$, causing severe delays that exceed `metrics_interval_seconds` (10–15s).
   - **The Batch Pattern**: `collector.py` executes **ONE single `docker stats` command** per sweep with no container argument (or with active container names passed in one batch):
     ```bash
     docker stats --no-stream --format "{{json .}}"
     ```
     This queries all active host containers in parallel within a single 1.0–1.2s window.
   - The collector parses the resulting JSON stream into an in-memory map:
     ```python
     dict[container_name, ContainerResourceSample]
     ```
     extracting:
     - CPU percentage (normalized to core count)
     - Memory usage (parsed from `1.45GiB / 4GiB` to `ram_used_mb`)
     - Network I/O (RX/TX MB)
     - Block I/O (Read/Write MB)

3. **Unified Source Merging in `collector.collect()`**:
   - **For Live Servers on Docker**:
     - CPU, RAM, Network I/O, Block I/O: Retrieved from the `docker stats` batch lookup.
     - TPS and Player Count: Queried directly via `PersistentRCONClient` (or process inspection).
     - The two sources are combined into `ServerMetrics` and `MetricPoint`.
   - **For Live Servers on Bare Metal (`local`)**:
     - Falls back to `psutil` process inspection for CPU/RAM + RCON for TPS/players.
   - **For Test Containers (`onx-test-{test_id}`)**:
     - CPU, RAM, Network I/O, Block I/O: Retrieved from the `docker stats` batch entry for `onx-test-{test_id}`.
     - TPS and Player Count: Recorded as `None` and `0` (test runs do not maintain an interactive player session or dedicated RCON server).

4. **Test-Container Metrics Lifecycle & Cadence**:
   - Test containers participate in the global `MetricsCollector.collect_all()` sweep.
   - Ephemeral test metrics are broadcast over WebSocket to `test:{test_id}:metrics` for real-time test monitoring in the UI.
   - To prevent teardown races (when a container exits and is removed by `test_runner.py` while a collection sweep is in-flight), the collector gracefully drops missing container entries with `logger.debug`, never raising errors or blocking the collection of live server metrics.

---

### (d) Reconnect Re-Tail (Decision 2)

1. **Re-tail Mechanism**:
   - Reconnection strictly uses **simple HTTP re-tailing**, rejecting cursors, offsets, or monotonic sequence counters.
   - Flow:
     ```
     Client Disconnects (Transport Drop)
           │
           ▼
     WSClient auto-reconnects with exponential backoff
           │
           ▼
     WS State transitions to CONNECTED (onopen)
           │
           ▼
     Client triggers HTTP Backfill: GET /api/v1/servers/{server_id}/console?tail=200
           │
           ▼
     Client updates local viewport buffer (deduplicating identical tail lines)
           │
           ▼
     Client sends WS Subscribe: {"type": "subscribe", "channels": ["server:{server_id}:console"]}
           │
           ▼
     Live streaming resumes from publisher loop
     ```

2. **Frontend Implementation & Gap Closure**:
   - **Identified Gap**: `ServerConsole.tsx` currently lacks reconnect hooks and instead executes a continuous 3,000ms polling query.
   - **Fix in Stage E**:
     - When WebSocket state is `CONNECTED`, disable TanStack Query's `refetchInterval` (`refetchInterval: false`).
     - Wire an `onStateChange` listener from `useWebSocket`: when state transitions from `RECONNECTING` to `CONNECTED`, trigger `queryClient.invalidateQueries(queryKeys.console.history(serverId))`.
     - Retain the HTTP tail fetch solely for initial component mount, reconnect backfill, and fallback if WebSocket is disabled or permanently disconnected.

---

### (e) Correlation Scope (Live-Server Only)

- **Live Servers**: Fully covered. The existing pipeline (`LogBasedEvidenceCollector` $\rightarrow$ `PatternCrashAnalyzer` $\rightarrow$ `EventDispatcher` broadcasting `CrashClassifiedEvent`/`ServerCrashedEvent` $\rightarrow$ tiered retention cleanup) is affirmed as complete and remains the authoritative correlation system.
- **Test Runs**: **OUT OF SCOPE**. Test-run crash correlation, mod blame analysis, and structured assertion evidence are explicitly deferred to **Stage F (Test Platform)**.
  - *Justification*: In Stage E, test containers are transient runners whose pass/fail status is verified by bot drivers. Building full evidence persistence and crash blaming for test runs requires Stage F's first-class `TestDefinition` and `TestRun` revision-binding model. Stage E does not build a temporary throwaway correlation system for test runs.

---

### (f) Runtime-Trigger Decision Note

> **Decision Note (Binding — Rescoping of Trigger Condition)**:  
> The literal outline trigger for Stage E ("Stage D's `Runtime` entity is live") is formally re-scoped. Per ADR-0015 and Stage D Design Spec §(e), domain `Runtime` entity construction and persistence are deferred to Stage F. Stage E does not gate on `Runtime` construction; its execution attachment points are the live `ServerHandle`, `server_id`, and `onx-test-{test_id}` container identities already present and operational in the codebase.

---

## Affected Components

### Backend Modules & Files
- **NEW** `backend/app/modules/server/infrastructure/console_stream.py`:
  Implements `ConsoleStreamManager` managing demand-driven `docker logs -f` follower tasks, line buffering, and 64KB/2000-line backpressure protection.
- `backend/app/websocket/endpoint.py`:
  Start and stop `ConsoleStreamManager` in `start_websocket_services()` and `stop_websocket_services()`. Connect it to `broadcast_console_lines()`.
- `backend/app/websocket/handlers.py`:
  Add message routing for `exec_input` and `exec_resize`. Integrate permission check and dispatch to provider/runner.
- `backend/app/websocket/authorization.py`:
  Add channel pattern `test:{test_id}:console` requiring `server:read` or `server:test:execute`. Add `"test"` to valid channel prefixes in `validate_channel()`.
- `backend/app/websocket/serializers.py`:
  Add `exec_input` message deserialization and validation.
- `backend/app/modules/server/infrastructure/providers/base.py`:
  Add `write_exec_input()` to `ServerProvider` interface with backward-compatible default fallback.
- `backend/app/modules/server/infrastructure/providers/docker.py`:
  Implement `write_exec_input()` for containerized targets.
- `backend/app/modules/monitoring/infrastructure/collector.py`:
  Implement `_collect_container_metrics_batch()` using `docker stats --no-stream --format "{{json .}}"`. Update `collect()` to merge `docker stats` with RCON metrics. Support `onx-test-*` containers.
- `backend/app/tasks/definitions/metrics_collector.py`:
  Include running test containers in the list of targets passed to `collector.collect_all()`.

### Frontend Components
- `frontend/src/websocket/client.ts` & `frontend/src/hooks/useWebSocket.ts`:
  Expose transport state changes (`CONNECTED`, `RECONNECTING`) and provide helper to send `exec_input`.
- `frontend/src/server_manager/components/ServerConsole.tsx`:
  Disable 3,000ms polling when WebSocket is connected. Implement HTTP re-tail on reconnect.

### Database & Permissions
- **Database**: **ZERO migrations**. No new tables or schema changes.
- **Permissions Contract**: No new entries in `contracts/permissions.yaml`. Reuses existing `server.{id}.console`, `server:read`, and `server:test:execute`.

---

## Interfaces & Contracts

### 1. WebSocket Client-to-Server Messages
```json
// Exec input message
{
  "type": "exec_input",
  "target_type": "server", // or "test"
  "target_id": "srv-abc123", // server_id or test_id
  "input": "say Hello World\n"
}

// Window resize (optional)
{
  "type": "exec_resize",
  "target_type": "server",
  "target_id": "srv-abc123",
  "cols": 120,
  "rows": 40
}
```

### 2. WebSocket Server-to-Client Messages
```json
// Console stream frame (existing format, now pressurized)
{
  "type": "console",
  "server_id": "srv-abc123",
  "lines": [
    "[12:00:00 INFO]: Preparing start region for dimension minecraft:overworld",
    "[12:00:01 INFO]: Time elapsed: 1250 ms"
  ],
  "channel": "server:srv-abc123:console"
}

// Error response on invalid exec
{
  "type": "error",
  "code": "PERMISSION_DENIED",
  "message": "Not authorized to execute commands on this target"
}
```

### 3. Route Contract Verification
- No new HTTP endpoints are introduced.
- Existing routes `GET /api/v1/servers/{server_id}/console` and `POST /api/v1/servers/{server_id}/command` remain identical.
- `scripts/check-route-contract.py` must pass at **141/141 verified routes**.

---

## Failure Cases & Edge Cases

1. **Publisher Loop Crash or Unexpected Subprocess Exit**:
   - If `docker logs --follow` terminates prematurely (e.g. Docker daemon hiccup or container restart), the follower task catches the exit, logs a warning, and if active subscribers remain on the channel, retries with exponential backoff (1s, 2s, 4s up to 10s max).
2. **`docker stats` Subprocess Failure or Missing Container**:
   - If `docker stats` fails or outputs malformed JSON, `collector.py` logs a warning and falls back to `psutil` (for live servers) or skips the cycle without crashing.
   - If an ephemeral test container is destroyed during the ~1s window of `docker stats`, the missing container name is simply ignored in the parsed map.
3. **Exec Session Teardown on WS Disconnect**:
   - If a client closes its WebSocket or loses connectivity while executing commands, the connection handler cleans up the session context in `finally:`. No orphaned stdin processes or open handles remain.
4. **Console Output Flood & Frame Cap Exceeded**:
   - Minecraft plugins dumping endless debug logs can generate thousands of lines per second.
   - The publisher slices frames to stay strictly under 64KB per message (well below the 256KB ceiling).
   - If the queue exceeds 2,000 lines, the stream drops the surplus lines, emits a warning notice, and maintains responsive event loop latency.
5. **Test-Run Metrics Polling Racing with Test Teardown**:
   - `test_runner.py` tears down containers asynchronously in `finally:`. The collector checks container presence before querying or safely catches container-not-found exceptions, preventing race conditions from failing test runs.

---

## Tests & Verification

### Unit & Application Tests
1. **Console Stream Manager (`test_console_stream.py`)**:
   - Verify follower task starts when subscriber count transitions from 0 to 1.
   - Verify follower task cancels when subscriber count drops to 0 after 5s debounce.
   - Verify batching logic (dispatches at 50 lines or 100ms timeout).
   - Verify backpressure dropping when buffer exceeds 2,000 lines and frame size stays <64KB.
2. **WebSocket Exec Protocol (`test_ws_exec.py`)**:
   - Send `exec_input` for live server with `server.{id}.console` permission $\rightarrow$ verified success.
   - Send `exec_input` without permission $\rightarrow$ verify `PERMISSION_DENIED` error frame.
   - Send `exec_input` for `target_type: test` $\rightarrow$ verify parent `server_id` resolution and permission check.
3. **Metrics Source Migration (`test_metrics_docker_stats.py`)**:
   - Mock `docker stats --no-stream` JSON output $\rightarrow$ verify accurate parsing of CPU %, RAM MB, Net I/O, Block I/O.
   - Verify merging of `docker stats` (resources) and RCON (TPS and players).
   - Verify test container metric emission without RCON queries.
   - Verify graceful fallback to `psutil` when `docker stats` is unavailable.
4. **Frontend Console & Re-Tail (`ServerConsole.test.tsx`)**:
   - Verify 3,000ms polling query is disabled when WebSocket status is `CONNECTED`.
   - Verify reconnect event triggers console history invalidation and backfill.

### Regression & Quality Gates
- **Full Backend Test Suite**: Run all tests against the 2,829 passed baseline ($0$ regressions).
- **Quality Gates**: All 6/6 CI gates must PASS:
  `check-db-revision`, `check-ruff-baseline`, `check-version-propagation`, `check-route-contract`, `check-ps1-bom`, `check-stray-db`.

---

## Out of Scope

- **Log Cursor / Since / Offset Machinery**: Explicitly rejected by binding decision 2. Reconnection uses simple HTTP re-tailing.
- **Test-Run Crash Correlation & Evidence Bundles**: Deferred to Stage F (Test Platform).
- **Domain `Runtime` Entity Construction**: Handed off to Stage F per Stage D decision §(e).
- **Multi-Host / Distributed Console Streaming**: Deferred to Stage G (Enterprise Capabilities).
- **Database Schema Changes**: No new tables or migrations are permitted in Stage E.

---

## Governance Gate Check

### Classification
**This design is classified as D2 (Major) under project governance standards**

### Rationale
While Stage E introduces zero database migrations and zero new HTTP routes, it modifies the core telemetry data source for all live Docker servers from host process inspection (`psutil`) to container virtualization inspection (`docker stats`). This alters operational telemetry semantics across the monitoring and alerting system. Additionally, it introduces interactive bidirectional command execution over WebSockets.

### Authorization & Next Steps
**No further escalation to Mohamed is required prior to Build.**
The three binding governance decisions:
1. Unified `docker stats` source migration for live and test containers with RCON/process TPS/players retained on live servers;
2. HTTP re-tail on reconnect without cursor machinery;
3. Interactive exec support for both live servers and `onx-test-*` containers;
were already explicitly authorized in the task charter.

This Design Spec is complete, adheres strictly to project engineering standardsand is ready for **Design Review per project engineering standards**.
