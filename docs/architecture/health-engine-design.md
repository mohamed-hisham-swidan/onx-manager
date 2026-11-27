# Server Health & Integrity Engine — Architecture Design

> No code, no APIs, no schemas. Responsibilities only.

---

## 1. Executive Summary

The existing codebase supports runtime monitoring, crash detection, and metrics collection — but only reactively. Problems are detected *after* they manifest. The engine inverts this: it validates *before* starting, monitors *continuously* during runtime, classifies *automatically* after crashes, and exposes health as a first-class domain concept.

The design introduces **one new aggregate** (`HealthStatus`), **five value objects**, **four domain services**, **eight events**, and **six subsystems** that integrate naturally into the existing CQRS/DDD/event-driven architecture. Zero infrastructure changes are required — the event bus, task queue, scheduler, WebSocket dispatcher, and provider abstraction all extend cleanly.

**Key architectural decisions:**
- Health is a separate aggregate, not a property of a Server — independent lifecycle, survives restarts, has history
- Validation is additive (accumulates all issues), not fail-fast — gives operators a complete picture
- Discovery is polling-based initially, with an event-driven path for the future
- Crash analysis is a two-phase pipeline: infrastructure collects evidence, domain classifies it
- The health calculation is time-windowed — a single failure doesn't flip a healthy server to broken

**Extension principle:** Every new component plugs into an existing pattern. The supervisor loop extends. The event bus carries new events. The task queue runs new jobs. The provider interface gains new methods.

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     DISCOVERY & REGISTRATION                     │
│  ┌────────────┐    ┌──────────────┐    ┌──────────────────┐     │
│  │ Discovery  │───▶│ Registration │───▶│ Server Created   │     │
│  │ Engine     │    │ Engine       │    │ (domain event)   │     │
│  └────────────┘    └──────────────┘    └──────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                       VALIDATION LAYER                          │
│  ┌──────────────────┐    ┌───────────────┐    ┌───────────┐    │
│  │ Integrity        │───▶│ Environment   │───▶│ Startup   │    │
│  │ Validator        │    │ Scanner       │    │ Guard     │    │
│  └──────────────────┘    └───────────────┘    └───────────┘    │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    RUNTIME MONITORING                           │
│  ┌────────────────┐    ┌───────────────┐    ┌──────────────┐   │
│  │ Runtime        │───▶│ Health        │───▶│ Notification │   │
│  │ Monitor        │    │ Calculator    │    │ Engine       │   │
│  └────────────────┘    └───────────────┘    └──────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                     CRASH & DIAGNOSTICS                         │
│  ┌──────────────┐    ┌───────────────┐    ┌──────────────┐     │
│  │ Evidence     │───▶│ Crash         │───▶│ Diagnostics  │     │
│  │ Collector    │    │ Analyzer      │    │ Repository   │     │
│  └──────────────┘    └───────────────┘    └──────────────┘     │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                   HEALTH PROJECTION                             │
│  ┌──────────────┐    ┌───────────────┐    ┌──────────────┐     │
│  │ Health       │───▶│ Health        │───▶│ Frontend     │     │
│  │ Timeline     │    │ Reports       │    │ Projection   │     │
│  └──────────────┘    └───────────────┘    └──────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Subsystem Breakdown

### 3.1 Discovery Engine

**Purpose:** Detect server directories on the filesystem that are not yet managed by the system.

**Responsibilities:**
- Scan configured server root directories for new folders
- Identify server directories by heuristics (presence of server.jar, world/ directory, server.properties)
- Deduplicate against already-registered servers
- Emit discovery events for new and removed server directories

**Inputs:** List of scan root directories, list of already-registered server identities

**Output:** Set of discovered-but-unregistered server paths with metadata (detected type, detected version, directory size)

**Dependencies:** Filesystem access, ServerRepository (to check for duplicates)

**Events consumed:** (none — autonomous)

**Events produced:** `ServerDiscoveredEvent` (path, detected type, metadata), `ServerVanishedEvent` (previously known directory no longer found)

**When it executes:** Periodically via scheduled task (default: every 60s), or on-demand via command

**Who owns the responsibility:** Application layer — a use case orchestrating filesystem scan + deduplication + event emission. The actual filesystem scanning is infrastructure.

**Communication:** Publishes `ServerDiscoveredEvent` on the event bus. Registration Engine subscribes.

**Failure boundaries:** A single directory that is unreadable or corrupt does not abort the entire scan. Errors are collected per-directory.

**Recovery behavior:** On failure, retry at next scheduled interval. Errors are logged but do not prevent future scans.

---

### 3.2 Registration Engine

**Purpose:** Convert discovered server directories into managed Server aggregates.

**Responsibilities:**
- Consume `ServerDiscoveredEvent` and create a Server aggregate
- Assign a server identity (slug + UUID following existing convention)
- Trigger initial integrity validation
- Persist the new Server aggregate via ServerRepository

**Inputs:** `ServerDiscoveredEvent`

**Output:** Registered Server aggregate, `ServerCreatedEvent`

**Dependencies:** ServerRepository, Integrity Validator (triggered after registration)

**Events consumed:** `ServerDiscoveredEvent`

**Events produced:** `ServerCreatedEvent`, `ServerRegistrationFailedEvent` (if directory is invalid)

**When it executes:** In response to `ServerDiscoveredEvent` — synchronously within the event handler

**Who owns the responsibility:** Application layer — event handler/subscriber

**Communication:** Subscribes to event bus, calls ServerRepository to persist, triggers Integrity Validator via command

**Failure boundaries:** A failed registration does not block subsequent discoveries or registrations.

**Recovery behavior:** If registration fails (invalid directory, DB error), the discovery entry is marked as "failed" and re-attempted on next discovery cycle.

---

### 3.3 Integrity Validator

**Purpose:** Verify that a server's filesystem structure, configuration, and dependencies are complete and internally consistent.

**Responsibilities:**
- Check presence and validity of required files: server.jar, server.properties, eula.txt
- Validate server.properties syntax and known keys
- Check world directory integrity (presence of level.dat, region files)
- Verify plugin/mod dependencies (if applicable)
- Validate Java version required vs. specified
- Check disk space availability
- Produce a structured integrity report with pass/fail/warning per check

**Inputs:** Server identity (for path resolution), validation scope (full vs. quick)

**Output:** `IntegrityReport` — collection of check results (check name, severity, status, details)

**Dependencies:** Filesystem access, ServerRepository (to resolve server path), Environment Scanner (for host capability information needed by some checks)

**Events consumed:** `ServerCreatedEvent` (triggers initial integrity validation), `IntegrityScanRequestedEvent` (on-demand or periodic re-validation)

**Events produced:** `IntegrityCheckPassedEvent`, `IntegrityCheckFailedEvent` (per-check, or aggregated)

**When it executes:** On server registration, on startup, periodically during runtime, on-demand

**Who owns the responsibility:** Domain service (interface), Infrastructure (implementation). The validation rules themselves belong in domain — they express policy. File reading is infrastructure.

**Communication:** Called by application use cases. Publishes results as events.

**Failure boundaries:** A single failed check does not abort checks in progress. All checks run; results are aggregated.

**Recovery behavior:** Transient failures (file temporarily locked, network filesystem latency) produce a "warning" rather than "critical" status. The check is re-run on the next cycle.

---

### 3.4 Environment Scanner

**Purpose:** Probe the host system to determine what capabilities and resources are available for running servers.

**Responsibilities:**
- Detect installed Java runtime (version, vendor, available heap)
- Check available disk space on server root filesystem
- Check available system memory
- Verify provider prerequisites: tmux version, Docker availability, etc.
- Measure system load to determine if new servers can be started
- Produce structured environment report

**Inputs:** Server identity (to determine provider type), or global scope

**Output:** `EnvironmentReport` — host capabilities, resource availability, provider readiness

**Dependencies:** System commands/utilities (java, free, df, tmux, docker), per-provider requirement specifications

**Events consumed:** (none — queried on demand by other subsystems)

**Events produced:** `EnvironmentDegradedEvent` (when resource levels cross a warning threshold)

**When it executes:** Before server startup (pre-flight), periodically during runtime (resource monitoring), on-demand

**Who owns the responsibility:** Infrastructure — this is inherently system-specific. But the *specifications* for what constitutes "enough" resources belong in domain (policy).

**Communication:** Called by the Startup Guard (pre-flight). Results shared via event and stored in EnvironmentReport.

**Failure boundaries:** If a system command fails (e.g., `java` binary not found), that capability is reported as "absent" with an error detail. Individual failures don't block other measurements.

**Recovery behavior:** Periodic re-scan to detect changes (e.g., Java installed after previous failure).

---

### 3.5 Startup Guard

**Purpose:** Prevent server startup when prerequisites are not met. Acts as a gate before the existing `StartServerHandler`.

**Responsibilities:**
- Run Integrity Validator (quick scope) before starting
- Run Environment Scanner to verify host can run the server
- Check that no port conflicts exist beyond what the existing `claim_localhost` handles
- Verify provider is available and ready
- Produce validation result: pass (allow start), warn (allow with logged warning), block (prevent start with reasons)

**Inputs:** Server identity, start request context

**Output:** `StartupValidationResult` — pass/warn/block with list of validation items

**Dependencies:** Integrity Validator, Environment Scanner, Provider (for provider readiness), Port availability check

**Events consumed:** `ServerStartRequestedEvent` (or equivalent command)

**Events produced:** `StartupValidationPassedEvent`, `StartupValidationBlockedEvent` (with reasons)

**When it executes:** As a pipeline step before `provider.start()`, inserted in the existing start command handler

**Who owns the responsibility:** Application layer — a pre-condition check in the start use case

**Communication:** Synchronously called by the command handler. If blocked, the command fails with validation reasons. If passed, the handler proceeds to `provider.start()`.

**Failure boundaries:** The guard either passes or blocks. Blocking does not damage the server; the server remains in CREATED or STOPPED state.

**Recovery behavior:** Blocked start is logged. The operator can either fix the issues or force-start (bypassing the guard) for emergencies.

---

### 3.6 Runtime Monitor

**Purpose:** Continuously observe a running server's health signals beyond simple process aliveness. Extends the existing `RuntimeSupervisor` loop.

**Responsibilities:**
- Monitor process aliveness (existing behavior)
- Track resource usage (CPU, memory, disk I/O via the server process)
- Detect log anomalies in real-time (OOM, watchdog timeout, plugin errors in latest.log)
- Check configured port is still listening
- Emit health signals to the Health Calculator

**Inputs:** Server identity, provider reference, tail of latest.log, process metrics

**Output:** Health signals — structured observations about the server's runtime state

**Dependencies:** Provider (for process access, metrics), Filesystem (for log tailing), Existing RuntimeSupervisor (as extension)

**Events consumed:** (none — autonomous loop)

**Events produced:** `RuntimeHealthSignalEvent` (resource threshold crossed, log anomaly detected, process healthy/unhealthy)

**When it executes:** Continuously at supervisor interval (existing 5s default, configurable)

**Who owns the responsibility:** Application layer — the existing `RuntimeSupervisor` is extended with additional health observation methods

**Communication:** Publishes health signals to event bus. Health Calculator consumes them.

**Failure boundaries:** Failed health observation (can't read log, can't get metrics) produces a degraded signal but does not crash the monitor loop.

**Recovery behavior:** If the log file cannot be read (rotated, deleted), reopen it. If process metrics are unavailable, skip that observation until next cycle.

---

### 3.7 Evidence Collector

**Purpose:** Gather all available evidence after a crash or health degradation. This is the first phase of the crash pipeline.

**Responsibilities:**
- Read the tail of latest.log (last N lines)
- List and read recent crash-reports/* files
- Capture provider crash diagnostics (existing `provider.collect_diagnostics()`)
- Capture system resource state at time of failure (memory, disk)
- Package all evidence into a structured evidence bundle

**Inputs:** Server identity, crash event context (exit code, signal, timestamp)

**Output:** `EvidenceBundle` — structured collection of all evidence artifacts

**Dependencies:** Filesystem (for logs, crash reports), Provider (for `collect_diagnostics()`), System commands (for resource snapshot)

**Events consumed:** `ServerCrashedEvent` (existing), `RuntimeHealthSignalEvent` (if degradation threshold crossed)

**Events produced:** `EvidenceCollectedEvent` (with reference to the evidence bundle)

**When it executes:** Immediately when a crash is detected, or when a health degradation crosses a threshold

**Who owns the responsibility:** Application layer — orchestrates multiple evidence sources

**Communication:** Called by crash handler. Publishes `EvidenceCollectedEvent` to event bus. Crash Analyzer subscribes.

**Failure boundaries:** Partial evidence is better than none. If crash-reports/ is unreadable but latest.log is available, the bundle contains only what could be collected.

**Recovery behavior:** If evidence collection fails entirely (e.g., entire server directory gone), the fact that collection failed is recorded as evidence itself. The crash is still classified as "unknown."

---

### 3.8 Crash Analyzer

**Purpose:** Classify the root cause of a server crash from collected evidence. This is the second phase of the crash pipeline.

**Responsibilities:**
- Parse latest.log for known error patterns: OutOfMemoryError, NullPointerException, Watchdog timeout, Plugin errors
- Parse crash-reports for throwable class and message
- Cross-reference exit code with known meanings
- Match patterns against the existing `FailureCode` enum values
- Determine crash classification: failure code, confidence level, summary, suggested action
- Update the server's crash record with the classification

**Inputs:** `EvidenceBundle` (from Evidence Collector), existing `FailureCode` enum

**Output:** `CrashClassification` — failure code, confidence (0.0–1.0), human-readable summary, suggested action

**Dependencies:** Pattern definitions (what to look for in logs), `FailureCode` enum (already exists)

**Events consumed:** `EvidenceCollectedEvent`

**Events produced:** `CrashClassifiedEvent` (with classification, server identity, evidence reference)

**When it executes:** In response to `EvidenceCollectedEvent`, typically within seconds of a crash

**Who owns the responsibility:** Domain service — pure logic, no I/O. The pattern matching and classification rules are domain policy.

**Communication:** Consumes `EvidenceCollectedEvent`, produces `CrashClassifiedEvent`. The Health Calculator consumes the classification.

**Failure boundaries:** If no pattern matches, the classification is `UNKNOWN` with low confidence. This is a valid classification. The analyzer should never fail to produce an output.

**Recovery behavior:** Classification patterns are updated independently of the analyzer. New patterns are added as domain rules without changing the analyzer's structure.

---

### 3.9 Health Calculator

**Purpose:** Compute the current health status of a server from all available signals. This is a continuous function, not a one-time check.

**Responsibilities:**
- Consume health signals from Runtime Monitor, Integrity Validator, Crash Analyzer
- Maintain a sliding time window of signals (e.g., last 5 minutes)
- Compute aggregate health classification: HEALTHY / WARNING / CRITICAL / BROKEN / UNKNOWN
- Detect state transitions (e.g., HEALTHY → WARNING) and emit events
- Apply decay: older signals have less weight than recent ones

**Inputs:** Health signals (process health, resource metrics, integrity results, crash classifications), time window configuration

**Output:** `HealthStatus` — current classification, contributing factors, trend (improving/stable/declining), confidence

**Dependencies:** Health Repository (to persist and retrieve current status)



**Events consumed:** `RuntimeHealthSignalEvent`, `IntegrityCheckFailedEvent`, `CrashClassifiedEvent`, `StartupValidationBlockedEvent`

**Events produced:** `HealthStatusChangedEvent` (previous classification, new classification, reason, timestamp)

**When it executes:** Continuously — each signal triggers a re-computation. Also runs periodically as a background task to catch stale signals.

**Who owns the responsibility:** Domain service — the health computation rules (how signals combine, thresholds, decay rates) are domain policy.

**Communication:** Consumes events, queries Health Repository, publishes `HealthStatusChangedEvent` on state transitions

**Failure boundaries:** A single bad signal does not flip the status. The time window prevents flapping. If no signals have been received for the configured timeout, status becomes UNKNOWN.

**Recovery behavior:** After a recovery signal (e.g., process healthy again), the calculator transitions back through warning states rather than instantaneously jumping to HEALTHY. A grace period prevents flapping.

---

### 3.10 Health Timeline

**Purpose:** Maintain an append-only history of health state changes for each server. Provides auditability and trend analysis.

**Responsibilities:**
- Record every `HealthStatusChangedEvent` as a timeline entry
- Support queries: all entries for a server, entries in a time range, entries by classification
- Support pruning: archive entries older than a configurable retention period
- Provide cursor-based pagination for frontend consumption

**Inputs:** `HealthStatusChangedEvent`

**Output:** Health timeline entries (queried, not pushed)

**Dependencies:** Health Repository (for persistence)

**Events consumed:** `HealthStatusChangedEvent`



**Events produced:** (none — queried by other subsystems)

**When it executes:** Append on every health status change. Queried on demand.

**Who owns the responsibility:** Application layer — a use case that records and retrieves timeline entries

**Communication:** Called by the Notification Engine (to record before notifying). Queried by the Health Reports subsystem and frontend.

**Failure boundaries:** Failed writes to the timeline do not affect health state or monitoring. They are logged and retried.

**Recovery behavior:** Missed entries are not backfilled. The next status change will be recorded.

---

### 3.11 Health Reports

**Purpose:** Generate periodic or on-demand health summary reports for operators.

**Responsibilities:**
- Aggregate health timeline data into summary reports
- Support report formats: current status summary, daily health summary, crash frequency report, uptime report
- Calculate uptime percentage over a time window
- Calculate crash frequency (crashes per day/week)
- Identify health trends (improving, stable, declining)

**Inputs:** Server identity, time range, report type

**Output:** `HealthReport` — structured report with summary statistics

**Dependencies:** Health Timeline (for source data), Health Repository (for current status)

**Events consumed:** (none — queried on demand)

**Events produced:** `HealthReportGeneratedEvent` (for logging or notification)

**When it executes:** On-demand (operator request) or scheduled (daily summary via cron task)

**Who owns the responsibility:** Application layer — a use case that queries timeline data and computes aggregates

**Communication:** Called via query (CQRS query handler). Result returned synchronously or asynchronously (if report takes time to generate).

**Failure boundaries:** If timeline data is partially unavailable, the report includes only available data and notes the gap.

**Recovery behavior:** Failed report generation is retried. Partial data produces a reduced report, not a failure.

---

### 3.12 Notification Engine

**Purpose:** Route health events to the frontend and any configured external notification channels.

**Responsibilities:**
- Subscribe to all health-related events on the event bus
- Map events to WebSocket channel payloads for the existing EventDispatcher
- Deduplicate rapid notifications (e.g., if health flips HEALTHY→WARNING→HEALTHY within seconds, only notify the final state)
- Rate-limit notifications per server to prevent flood

**Inputs:** Health events: `HealthStatusChangedEvent`, `CrashClassifiedEvent`, `IntegrityCheckFailedEvent`, etc.

**Output:** WebSocket messages on `server:{id}` and `health:{id}` channels

**Dependencies:** Existing `EventDispatcher` (in websocket layer), event bus subscriptions

**Events consumed:** All health-related events listed above

**Events produced:** (none — state changes are forwarded to WebSocket, not re-published as domain events)

**When it executes:** In response to health events

**Who owns the responsibility:** Application layer — a subscriber that transforms domain events into WebSocket messages

**Communication:** Subscribes to event bus, passes transformed payloads to `EventDispatcher`

**Failure boundaries:** Failed WebSocket delivery does not affect the event bus or domain state. The notification is lost, but the next event will trigger a new delivery.

**Recovery behavior:** WebSocket reconnection is handled by the existing infrastructure. No event replay mechanism for missed notifications — the timeline is the source of truth for history.

---

### 3.13 Diagnostics Repository

**Purpose:** Persist and retrieve crash evidence, classifications, and diagnostic snapshots.

**Responsibilities:**
- Store evidence bundles collected during crashes
- Store crash classifications
- Support queries: all diagnostics for a server, diagnostics in a time range, diagnostics by failure code
- Prune old diagnostics per retention policy

**Inputs:** `EvidenceBundle`, `CrashClassification`

**Output:** Stored diagnostics (queried on demand)



**Events consumed:** `EvidenceCollectedEvent`, `CrashClassifiedEvent`

**Events produced:** (none — queried)

**When it executes:** Append on evidence collection and crash classification. Queried on demand by frontend or reports.

**Who owns the responsibility:** Domain — repository interface. Infrastructure — implementation.

**Communication:** Called by Evidence Collector and Crash Analyzer to persist. Queried by frontend projection and Health Reports.

**Failure boundaries:** If persistence fails, the evidence is logged to a fallback location (local file) and the event is retried.

**Recovery behavior:** On DB failure, evidence is written to a fallback file and re-ingested when the DB is available.

---

### 3.14 Frontend Projection

**Purpose:** Provide the frontend with read-optimized views of health data.

**Responsibilities:**
- Maintain a read model for each server's current health status
- Maintain a read model for diagnostics listing
- Provide health timeline data in frontend-friendly shape
- Update read models when health events occur
- No write-back — frontend projection is read-only

**Inputs:** `HealthStatusChangedEvent`, `CrashClassifiedEvent`, `EvidenceCollectedEvent`

**Output:** Read-optimized data structures consumable by REST API responses and WebSocket payloads

**Dependencies:** Health Repository (for persistence queries), Event Bus (for updates)



**Events consumed:** `HealthStatusChangedEvent`, `CrashClassifiedEvent`, `ServerCreatedEvent`, `ServerRemovedEvent`

**Events produced:** (none — no domain events from projection)

**When it executes:** Event-driven — updates on each event. Also queries on demand via REST API.

**Who owns the responsibility:** Infrastructure — the read model is a CQRS query-side concern

**Communication:** Subscribes to events, updates cached/stored projections, serves query requests

**Failure boundaries:** A stale projection serves outdated data but does not affect the domain. The next event corrects it.

**Recovery behavior:** On startup, projections are rebuilt from the Health Repository. Full rebuild is possible on demand.

---

## 4. Lifecycle Flow

### 4.1 Server Discovery → Registration → Validation

```
Filesystem timer tick
        │
        ▼
Discovery Engine scans root directories
        │
        ├── No new directories ──▶ sleep until next tick
        │
        └── New directory found
                │
                ▼
        Determine server type (heuristics)
                │
                ▼
        Check against registered servers
                │
                ├── Already registered ──▶ skip
                │
                └── New ──▶ emit ServerDiscoveredEvent
                                │
                                ▼
                Registration Engine (subscribes)
                        │
                        ▼
                Create Server aggregate
                        │
                        ▼
                Persist via ServerRepository
                        │
                        ▼
                Emit ServerCreatedEvent
                        │
                        ▼
                Integrity Validator (triggered)
                        │
                        ▼
                Run integrity checks (full scope)
                        │
                        ├── All pass ──▶ emit IntegrityCheckPassedEvent
                        │                       │
                        │                       ▼
                        │               Server READY for start
                        │
                        └── Failures ──▶ emit IntegrityCheckFailedEvent
                                          │
                                          ▼
                                  Server REGISTERED but BROKEN
                                    (operator notified)
```

### 4.2 Start Request → Pre-flight → Running

```
Operator requests start (command)
        │
        ▼
Start Command Handler
        │
        ▼
Startup Guard (inserted before existing start logic)
        │
        ├── Run Integrity Validator (quick scope)
        │       │
        │       └── Result
        │
        ├── Run Environment Scanner
        │       │
        │       └── Result
        │
        ├── Check port availability
        │
        ├── BLOCKED ──▶ emit StartupValidationBlockedEvent
        │                   │
        │                   ▼
        │               Command returns failure
        │               (server NOT started)
        │
        └── PASSED ──▶ emit StartupValidationPassedEvent
                            │
                            ▼
                    Existing StartServerHandler proceeds
                            │
                            ▼
                    provider.start()
                            │
                            ▼
                    Runtime Monitor begins (extended supervisor)
                            │
                            ▼
                    Health Calculator receives "starting" signals
                            │
                            ▼
                    HealthStatus becomes PENDING → HEALTHY
```

### 4.3 Runtime → Health Monitoring

```
Runtime Monitor loop (every N seconds)
        │
        ├── Check process alive (existing)
        ├── Check port listening
        ├── Read latest.log tail (new)
        ├── Sample process resource usage (new)
        │
        ▼
        Emit RuntimeHealthSignalEvent
                │
                ▼
        Health Calculator
                │
                ├── Sliding window (last 5 min)
                ├── Weight by recency
                ├── Apply thresholds
                │
                ├── No change ──▶ no event
                │
                └── Status changed ──▶ emit HealthStatusChangedEvent
                                            │
                                            ▼
                                    Health Timeline (record)
                                            │
                                            ▼
                                    Notification Engine
                                            │
                                            ▼
                                    WebSocket → Frontend
```

### 4.4 Crash → Evidence → Classification → Health Update

```
Supervisor detects process loss
        │
        ▼
        provider.collect_diagnostics() (existing)
        │
        ▼
        Server.crash() (existing — records exit_code + last_log_lines)
        │
        ▼
        Emit ServerCrashedEvent (existing)
                │
                ▼
        Crash Handler (new)
                │
                ├── Trigger Evidence Collector
                │       │
                │       ├── Read latest.log tail
                │       ├── Read crash-reports
                │       ├── Capture system state snapshot
                │       └── Collect provider diagnostics
                │               │
                │               ▼
                │       Emit EvidenceCollectedEvent
                │               │
                │               ▼
                │       Crash Analyzer (subscribes)
                │               │
                │               ├── Parse latest.log for patterns
                │               ├── Parse crash-reports
                │               ├── Cross-reference exit code
                │               ├── Match → FailureCode
                │               │
                │               ▼
                │       Emit CrashClassifiedEvent
                │               │
                │               ▼
                │       Health Calculator
                │               │
                │               ▼
                │       HealthStatus → CRITICAL or BROKEN
                │               │
                │               ▼
                │       Emit HealthStatusChangedEvent
                │               │
                │               ▼
                │       Health Timeline records
                │       Notification Engine routes to frontend
                │
                └── (Optionally) Trigger recovery pipeline
```

### 4.5 Recovery Pipeline

```
Crash classified ──▶ Recovery pipeline evaluates
        │
        ├── Can auto-restart?
        │       ├── Rules: crash frequency < N/hour, uptime > M minutes before crash
        │       ├── Yes ──▶ Auto-restart with escalation timer
        │       └── No  ──▶ Notify operator
        │
        ├── Need operator intervention?
        │       └── Escalate with CrashClassification evidence
        │
        └── Log recovery decision
```

---

## 5. Domain Model

### 5.1 New Aggregates

#### HealthStatus

**Rationale for separate aggregate (not a value on Server):**
- Health has an independent lifecycle — it is recalculated every N seconds or on every signal, regardless of server state
- Health survives server restarts — a server that crashes and restarts retains its health trajectory
- Health has its own history (timeline) that is conceptually separate from the server's lifecycle
- Health is computed from multiple sources, not owned exclusively by the Server aggregate

**Identity:** Server ID (one-to-one with Server)

**State:**
- Current classification (HEALTHY / WARNING / CRITICAL / BROKEN / UNKNOWN / PENDING)
- Previous classification (for transition detection)
- Contributing factors (list of active issues with severity)
- Trend direction (improving / stable / declining)
- Last updated timestamp
- Confidence level (0.0–1.0)

**Invariants:**
- Classification must be one of the defined enum values
- Timestamp must be monotonic (cannot go backward)
- At least one contributing factor must be present for non-HEALTHY states
- Trend direction must be consistent with recent classification changes

**Lifecycle:**
- Created when a Server is registered (initial state: PENDING)
- Updated on every re-calculation
- Never deleted — archived with server

#### DiagnosticsReport

**Rationale:** A crash event produces a large amount of evidence and analysis. This data is complex enough to warrant its own aggregate rather than being embedded in the Server aggregate.

**Identity:** UUID

**State:**
- Server identity (the server that crashed)
- Timestamp
- Evidence bundle reference
- Crash classification (failure code, confidence, summary, suggested action)
- Provider diagnostics reference

**Invariants:**
- Must reference a valid Server
- Evidence bundle must not be empty (even if "nothing available")
- Classification must be present (even if UNKNOWN)

**Lifecycle:**
- Created on crash, updated when classification completes
- Retained per retention policy
- Pruned by scheduled task

### 5.2 New Value Objects

#### HealthClassification

An enumeration or algebraic type with states: HEALTHY, WARNING, CRITICAL, BROKEN, UNKNOWN, PENDING.

Each state carries semantics:
- **PENDING:** No health data yet (new server, between validation and first runtime signal)
- **HEALTHY:** All signals nominal
- **WARNING:** Minor issues detected (disk usage high, config drift, non-critical integrity failure)
- **CRITICAL:** Serious issue detected (process unhealthy, port unavailable, crash occurred, resource exhaustion)
- **BROKEN:** Server cannot function (missing critical files, persistent crash loop, environment incapable)
- **UNKNOWN:** No signals received within timeout period (supervisor not running, network partition)

Transitions must pass through intermediate states — HEALTHY→BROKEN must transit through WARNING or CRITICAL first (grace period prevents flapping).

#### CrashClassification

- **FailureCode:** One of the existing FailureCode enum values (31 codes), extended with additional codes if needed
- **Confidence:** Float 0.0–1.0
- **Summary:** Human-readable root cause description
- **SuggestedAction:** What an operator should do to fix
- **EvidenceReferences:** Pointers to log excerpts or crash report files

#### IntegrityReport

- **Checks:** List of individual check results (check name, severity: critical/warning/info, status: pass/fail/error, detail)
- **Overall status:** pass / warn / fail
- **Timestamp**
- **Scope:** full / quick

#### EnvironmentReport

- **Java:** Available versions, vendors, max heap
- **Disk:** Available space on relevant mount points
- **Memory:** Available RAM, swap
- **Provider:** Provider type, prerequisites status (tmux version, Docker)
- **Load:** System load average
- **Timestamp**

#### HealthTrend

- **Direction:** improving / stable / declining
- **WindowStart, WindowEnd:** Time range of analysis
- **Samples:** Number of data points in window
- **Volatility:** How much the status has fluctuated
- **MeanTimeBetweenCrashes:** Computed from timeline

### 5.3 New Domain Services

#### CrashClassifier

**Responsibility:** Accept evidence, classify crash.

**Rules:**
- Pattern matching against known error signatures in log tails and crash reports
- Exit code to FailureCode mapping
- Confidence scoring based on pattern match strength and evidence completeness

**This is a domain service because:**
- It encapsulates classification rules (pure logic)
- It is stateless
- It operates on value objects (EvidenceBundle) and produces value objects (CrashClassification)
- It does not depend on infrastructure

#### HealthCalculatorService

**Responsibility:** Accept health signals, compute health status.

**Rules:**
- Time window weighting (recent signals > old signals)
- Classification thresholds (how many warnings before WARNING? how many criticals before CRITICAL?)
- Transition constraints (no skipping states, grace period for flapping)
- Decay (signal fades over time if not refreshed)

#### IntegrityPolicy

**Responsibility:** Define what constitutes a valid server for each server type.

**Rules:**
- Required files per server type (vanilla, forge, paper, etc.)
- Required configuration keys
- Valid value ranges for configuration
- Plugin/mod dependency rules

#### EnvironmentPolicy

**Responsibility:** Define what environment capabilities are required for each server type and each provider.

**Rules:**
- Minimum Java version per Minecraft version
- Minimum disk space
- Minimum memory
- Required system tools (tmux, docker, screen)
- Maximum concurrent servers per provider type

### 5.4 New Domain Events

| Event | When Fired | Key Payload | Consumed By |
|-------|-----------|-------------|-------------|
| `ServerDiscoveredEvent` | New server directory found by Discovery Engine | Path, metadata | Registration Engine |
| `ServerVanishedEvent` | Previously known server directory no longer exists | Path | Registration Engine (archive server) |
| `IntegrityCheckPassedEvent` | Integrity validation succeeds | Server ID, report | Health Calculator, Notification Engine |
| `IntegrityCheckFailedEvent` | Integrity validation fails | Server ID, report | Health Calculator, Notification Engine |
| `EnvironmentDegradedEvent` | Host resources cross warning threshold | Resource type, value, threshold | Health Calculator, Notification Engine |
| `StartupValidationPassedEvent` | Pre-flight checks pass | Server ID, report | Runtime Monitor (start monitoring) |
| `StartupValidationBlockedEvent` | Pre-flight checks block start | Server ID, report, reasons | Notification Engine (notify operator) |
| `RuntimeHealthSignalEvent` | Runtime Monitor detects a health observation | Server ID, signal type, value, severity | Health Calculator |
| `EvidenceCollectedEvent` | Crash evidence bundle assembled | Server ID, evidence reference | Crash Analyzer, Diagnostics Repository |
| `CrashClassifiedEvent` | Crash root cause determined | Server ID, classification | Health Calculator, Diagnostics Repository, Notification Engine |
| `HealthStatusChangedEvent` | Health Calculator computes a new status | Server ID, previous status, new status, reasons, trend | Health Timeline, Notification Engine, Frontend Projection |
| `HealthReportGeneratedEvent` | Health report completed | Server ID, report type, timestamp | (logging, metrics) |
| `RecoveryTriggeredEvent` | Auto-recovery initiated | Server ID, recovery action, reason | Health Timeline, Notification Engine |
| `RecoveryFailedEvent` | Auto-recovery failed | Server ID, action, failure reason | Notification Engine (escalate) |
| `RecoverySucceededEvent` | Auto-recovery completed | Server ID, action | Health Calculator, Health Timeline |

### 5.5 New Repository Interfaces

#### HealthRepository

**Purpose:** Persist and retrieve health status, timeline entries, and reports.

**Methods (responsibilities only):**
- Save current health status for a server
- Get current health status for a server
- Get current health status for all servers
- Append timeline entry
- Query timeline entries (by server, time range, classification)
- Save crash diagnostics
- Query crash diagnostics (by server, time range, failure code)
- Prune entries older than retention period

#### DiagnosticsRepository

**Purpose:** Persist and retrieve evidence bundles and crash classifications.

**Methods (responsibilities only):**
- Save evidence bundle
- Save crash classification
- Get evidence bundle (by ID)
- Get crash classification (by server, by time range)
- Attach classification to evidence

---

## 6. Event Flow

### 6.1 All Events and Their Paths

```
ServerDiscoveredEvent
  → Registration Engine (create Server aggregate)
  → (no persistence needed — transient)

ServerCreatedEvent (existing, extended)
  → Integrity Validator (trigger validation)
  → Notification Engine (notify frontend of new server)

IntegrityCheckPassedEvent
  → Health Calculator (update health status)
  → Notification Engine (notify frontend)
  → Health Timeline (record)

IntegrityCheckFailedEvent
  → Health Calculator (update health status)
  → Notification Engine (notify frontend)
  → Health Timeline (record)

RuntimeHealthSignalEvent
  → Health Calculator (update health status)
  → (no frontend notification — too frequent, aggregated by Health Calculator)

HealthStatusChangedEvent
  → Health Timeline (record)
  → Notification Engine (notify frontend)
  → Diagnostics Repository (if status is CRITICAL/BROKEN, attach to diagnostics record)

ServerCrashedEvent (existing)
  → Evidence Collector (gather evidence)
  → Health Calculator (update health status)

EvidenceCollectedEvent
  → Crash Analyzer (classify crash)
  → Diagnostics Repository (persist evidence)

CrashClassifiedEvent
  → Health Calculator (update health status)
  → Diagnostics Repository (persist classification)
  → Notification Engine (notify frontend)
  → Recovery Pipeline (evaluate auto-recovery)

StartupValidationBlockedEvent
  → Notification Engine (notify frontend)
  → (server stays in current state)

StartupValidationPassedEvent
  → Runtime Monitor (start extended monitoring)
  → (start command continues to provider.start())
```

### 6.2 Event Bus Integration

All events use the existing `EventBus` with:
- Priority subscriptions (health calculator before notification engine)
- Retry (3 attempts, exponential backoff) for persistence-related subscribers
- Dead letter queue for events that fail after all retries
- Timeout (10s default) for synchronous event handlers

The existing `EventDispatcher` (WebSocket) subscribes to:
- `HealthStatusChangedEvent` → routes to `health:{server_id}` and `health:*` channels
- `CrashClassifiedEvent` → routes to `server:{server_id}` and `diagnostics:*` channels
- `IntegrityCheckFailedEvent` → routes to `server:{server_id}` channel
- `StartupValidationBlockedEvent` → routes to `server:{server_id}` channel
- `ServerCrashedEvent` (existing) → already routed to `server:{server_id}` channel

---

## 7. Responsibility Matrix

| Subsystem | Domain | Application | Infrastructure | Provider | Task System | Monitoring Module | Frontend |
|-----------|--------|-------------|----------------|----------|-------------|-------------------|----------|
| **Discovery** | — | Orchestrate scan + deduplicate + emit event | Filesystem scanner | — | Scheduled trigger | — | — |
| **Registration** | — | Consume event + create aggregate + persist | — | — | — | — | Show new server |
| **Integrity Validator** | Validation rules (what to check, severity) | Trigger validation + collect results | File reader, config parser, Java version detector | — | Periodic re-validation task | — | — |
| **Environment Scanner** | Requirements policy (min Java, min disk, etc.) | Orchestrate scan + compare to policy | System command executors | Provider-specific environment requirements | — | — | — |
| **Startup Guard** | — | Gate before start + emit result | — | Provider readiness check | — | — | Show validation result |
| **Runtime Monitor** | — | Extend supervisor loop + collect observations | Log tail reader, resource sampler | Provider process metrics | — | — | — |
| **Evidence Collector** | — | Orchestrate evidence gathering | Log reader, crash-reports reader, system snapshot | Provider diagnostics (existing) | — | — | — |
| **Crash Analyzer** | Classification rules, pattern matching | — | — | — | — | — | Show classification |
| **Health Calculator** | Health computation rules, thresholds, decay | — | — | — | — | Provide metric time-series as signal source | — |
| **Health Timeline** | — | Record + query timeline entries | — | — | Pruning task | — | Show timeline |
| **Health Reports** | — | Generate reports from timeline | — | — | Scheduled report generation | — | Display reports |
| **Notification Engine** | — | Subscribe + deduplicate + route to WebSocket | — | — | — | — | Display notifications |
| **Diagnostics Repository** | Repository interface | — | DB implementation | — | Retention pruning task | — | Show diagnostics |
| **Frontend Projection** | — | — | Read model maintenance | — | — | — | Consume read model |

---

## 8. Boundary Analysis

### 8.1 Domain Layer — What Belongs Here

**New domain classes reside in `server/domain/`:**
- `HealthStatus` aggregate (or a new `health/` module within domain)
- `HealthClassification` value object
- `CrashClassification` value object
- `IntegrityReport` value object
- `EnvironmentReport` value object
- `HealthTrend` value object
- All new domain events (in `server/domain/events.py` or `health/domain/events.py`)
- `CrashClassifier` domain service (interface)
- `HealthCalculatorService` domain service
- `IntegrityPolicy` domain service
- `EnvironmentPolicy` domain service
- `HealthRepository` interface
- `DiagnosticsRepository` interface

**Design decision — new module vs. extension of existing module:**
- Option A: Place in `server/domain/` — extends existing module naturally, but Server aggregate grows in scope
- Option B: Create `health/` module — cleaner separation, but adds module dependency (health depends on server)
- **Preferred: Option B** — health is a distinct bounded context. It references server by ID but does not depend on Server aggregate internals. This keeps cohesion high and coupling low.

Rationale: If health monitoring is its own bounded context, changes to server lifecycle logic don't affect health logic and vice versa. The `server` module does not import from `health`. The `health` module imports only the Server identity type.

### 8.2 Application Layer — What Belongs Here

All use cases / orchestration:
- `DiscoverServersUseCase` — orchestrate filesystem scan + deduplicate + emit event
- `RegisterServerUseCase` — consume discovery event, create Server aggregate, trigger validation
- `ValidateIntegrityUseCase` — trigger integrity checks, emit events
- `PerformStartupValidationUseCase` — run pre-flight checks, emit result
- `CollectEvidenceUseCase` — orchestrate evidence gathering
- `ComputeHealthUseCase` — receive signals, compute health, emit change event
- `GenerateHealthReportUseCase` — query timeline, compute aggregates, return report
- `QueryHealthTimelineUseCase` — query timeline with filters and pagination
- `ForceStartServerUseCase` — bypass startup guard for emergency operations

Command handlers (existing pattern):
- Existing `StartServerHandler` is extended with pre-flight guard
- New `ForceStartServerHandler` for bypass operations

### 8.3 Infrastructure Layer — What Belongs Here

All I/O and external system access:
- `FilesystemScanner` — walks directories, checks for server indicators
- `SystemCommandExecutor` — runs java, free, df, etc. and parses output
- `LogTailReader` — reads last N lines of a file efficiently
- `CrashReportParser` — reads and parses .txt crash report files
- `HealthRepositoryImpl` — DB persistence of health data
- `DiagnosticsRepositoryImpl` — DB persistence of diagnostics data
- `HealthProjectionUpdater` — maintains frontend read models
- `ProcessResourceSampler` — reads process CPU/memory usage from /proc or equivalent

### 8.4 Provider Layer — What Belongs Here

The existing `ServerProvider` base class and all implementations gain new responsibilities:
- **New base method:** `validate_environment() -> EnvironmentReport` — provider-specific environment check
- **New base method:** `sample_resources() -> ResourceSample` — current process CPU/memory
- **Existing `collect_diagnostics()`** — extended to include more evidence

Each provider implementation knows:
- What system tools it requires (tmux, Docker, etc.)
- What environment minimums it needs
- How to sample its own resource usage

### 8.5 Background Task Layer — What Belongs Here

New task definitions in `tasks/definitions/`:
- `periodic_discovery_scan` — runs Discovery Engine every 60s
- `periodic_integrity_scan` — runs Integrity Validator on all servers every 5min
- `periodic_health_recalculation` — runs Health Calculator on all servers every 30s (catch stale signals)
- `daily_health_report` — generates daily health summary reports
- `prune_old_diagnostics` — removes old evidence and timeline entries per retention policy
- `prune_old_timeline` — removes old timeline entries

### 8.6 Monitoring Module — What Belongs Here

The existing `monitoring/` module contributes:
- `MetricSeries` — health signals can be recorded as metric time-series
- `AlertTriggeredEvent` — if health stays in CRITICAL for N consecutive checks, an alert fires

The monitoring module does NOT own health classification — that is the Health Calculator's responsibility. But health signals can feed into the monitoring module for alerting purposes.

### 8.7 Frontend — What Belongs Here

New frontend views and components:
- Health status indicator per server card
- Health timeline visualization (line chart of status over time)
- Diagnostics viewer (crash reports, evidence, classification)
- Health report display (summary statistics, uptime, crash frequency)
- Validation detail panel (pre-flight results, integrity check results)

---

## 9. Failure Analysis

### 9.1 Failure Modes

| Failure Mode | Effect | Detection | Containment | Recovery |
|-------------|--------|-----------|-------------|----------|
| Discovery Engine fails | No new servers discovered automatically | Missing logs | Isolated — other subsystems unaffected | Retry at next scheduled interval |
| Registration fails | Server not registered (discovered but orphaned) | Error log, retry count | Discovered-but-unregistered entry remains in discovery output | Re-attempt on next discovery cycle |
| Integrity check error | Missing validation data | Signal not received by Health Calculator | Server can still be started (Startup Guard runs own checks) | Next periodic scan retries |
| Environment scanner fails | Missing environment report | Empty environment report | Startup Guard uses conservative defaults | Periodic re-scan |
| Startup Guard blocks start | Server not started | Operator notified in frontend | Server stays in current state (no data loss) | Operator fixes issues and retries, or force-starts |
| Runtime Monitor fails to observe | No health signals emitted | Health status becomes UNKNOWN after timeout | Server continues running unaffected | Next cycle reconnects |
| Evidence Collector fails | Empty evidence bundle | Evidence bundle marked as "collection failed" | Crash still classified as UNKNOWN with low confidence | Manual evidence collection possible |
| Crash Analyzer fails to classify | Classification is UNKNOWN | Low confidence in classification | Server crash recorded, recovery still possible | Pattern update doesn't require code change |
| Health Calculator fails | Health status not updated | Stale health status displayed on frontend | Server state unaffected | Next signal triggers re-computation |
| Health Repository DB unavailable | Health data not persisted | Write errors logged | Health state kept in memory, timeline entries queued | Retry queue on DB recovery, memory state freshest |
| Event Bus failure | Events lost | Event bus internal health check | Events between bus restart are lost | No recovery for lost events; next cycle generates fresh events |
| WebSocket connection lost | Frontend not updated in real-time | Client-side reconnection detected | Frontend falls back to REST polling | Automatic reconnection, full state refresh on reconnect |

### 9.2 Graceful Degradation

| Subsystem Degraded | Frontend Shows | System Behavior |
|-------------------|---------------|-----------------|
| No discovery engine | Only manually registered servers | Registration via UI still works |
| No integrity validation | No validation results | Servers start without validation (less safe but still functional) |
| No environment scanner | No environment data | Startups use "unknown" environment — may fail at provider level |
| No runtime monitor | Health status frozen | Server still runs and is manageable |
| No crash analyzer | Crashes shown as "unclassified" | Evidence still collected, operator can manually review |
| No health calculator | Health status shows last known value | No health transitions, but all other operations work |

### 9.3 Cascading Failure Prevention

- Health Calculator runs as a separate pipeline stage with its own failure boundary — if it fails, supervisors still detect crashes and operators still see crashes as events
- Discovery Engine failure does not affect running servers
- Evidence collection failure does not affect the server's ability to restart
- Diagnostics Repository failure does not affect monitoring or health calculation
- No single subsystem can bring down the entire system

---

## 10. Extension Points

### 10.1 Pluggable Discovery Providers

The Discovery Engine can support multiple discovery methods beyond filesystem scanning:
- File system watcher (inotify/FSEvents — reactive instead of polling)
- Configuration file import (batch from YAML/JSON)
- Kubernetes-style label-based discovery
- Network discovery (remote servers via SSH)

Architecture: Discovery method is a strategy interface injected into the Discovery Engine.

### 10.2 Pluggable Validation Rules

The Integrity Validator's rules are defined per server type. Adding a new server type (e.g., Fabric, Spigot, Bedrock) means:
- Define what files are required
- Define what configuration keys must exist
- Define mod/plugin expectations

Architecture: Rules are specification objects registered by server type. Adding a new type = registering a new set of specifications.

### 10.3 Pluggable Crash Patterns

The Crash Analyzer matches patterns against evidence. New patterns are added without changing the analyzer:
- Each pattern is a specification: evidence type, match condition, FailureCode, suggested action
- Patterns have a priority order (more specific patterns match first)
- External teams can add patterns without changing classifier logic

### 10.4 External Notification Channels

The Notification Engine can be extended to support:
- Email (SMTP)
- Discord/Slack webhooks
- PagerDuty/OpsGenie
- SMS

Architecture: Each channel is a subscriber to the notification event stream, with its own rate-limiting and formatting.

### 10.5 Custom Health Computation Rules

The Health Calculator's rules for combining signals and determining classification can be customized per deployment:
- Threshold adjustments (how many warnings before WARNING?)
- Signal weighting (some signals more important than others)
- Custom classification logic

Architecture: Strategy pattern — default strategy provided, custom strategies pluggable via configuration.

### 10.6 Read Model Projections

The Frontend Projection subsystem can support multiple read models for different consumers:
- Frontend read model (current health + timeline)
- API read model (REST responses for external consumers)
- Metrics read model (Prometheus-compatible health metrics)
- Export read model (JSON/CSV export of health data)

---

## 11. Architectural Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **Health status flapping** (rapid HEALTHY↔WARNING transitions) | Medium | High — operator confusion, alert fatigue | Grace period and state transition constraints in Health Calculator. No direct HEALTHY→BROKEN transitions. |
| **Polling discovery misses servers** (file system scan interval too long) | Low | Medium — servers found late | Configurable scan interval. Manual registration always available as fallback. |
| **Log tail reading is expensive** (large logs, many servers) | Medium | Low — CPU usage at supervisor frequency | Read only last N bytes (not lines) using seek. Cache file size between reads to detect rotation. |
| **Evidence collection on disk-full crash fails** (no space to write evidence) | High | Medium — evidence lost | Collect evidence in memory, write to alternate location, or send over network. |
| **Crash analyzer false positive** (classifies normal log line as crash pattern) | Medium | Medium — wrong FailureCode assigned | Confidence scoring prevents low-confidence classifications from triggering alerts. |
| **Mod/plugin compatibility check is unbounded** (thousands of mods to validate) | High | Low — scope limits | Validation scope parameter: quick (files exist) vs. full (dependency check). Full scope is opt-in. |
| **Health Calculator becomes bottleneck** (thousands of servers, each recalculating on every signal) | Low | High — health updates delayed | Each server's health is computed independently. No cross-server dependencies. Horizontally scalable. |
| **Event bus replay on restart floods downstream** | Low | Medium — notification storm on reconnection | Events are not replayed on restart. Projections rebuild from persisted state. WebSocket reconnection fetches current state via REST. |

---

## 12. Trade-offs

### 12.1 Polling Discovery vs. Event-Driven Discovery

| Aspect | Polling | Event-Driven (inotify/FSEvents) |
|--------|---------|---------------------------------|
| Simplicity | ✅ Simple — scan every N seconds | ❌ Complex — requires platform-specific watchers |
| Responsiveness | ❌ Up to N-second delay | ✅ Instant detection |
| Reliability | ✅ Works everywhere, survives watcher crashes | ❌ Watchers can miss events or lose state |
| Resource usage | ❌ Wastes cycles scanning when nothing changes | ✅ Zero overhead when idle |
| **Winner** | ✅ **Polling for initial implementation** | Event-driven for future optimization |

**Decision:** Start with polling (every 60s) to match the existing architecture's patterns. An event-driven adapter can be plugged in later via the strategy interface without changing the Discovery Engine.

### 12.2 Separate Health Aggregate vs. Embedded on Server

| Aspect | Separate HealthStatus Aggregate | Embedded on Server |
|--------|-------------------------------|-------------------|
| Cohesion | ✅ Health has own lifecycle and persistence | ❌ Server aggregate grows in scope |
| Independence | ✅ Server and health can change independently | ❌ Server aggregate must change when health logic changes |
| Query efficiency | ✅ Health can be queried without loading Server | ❌ Loading Server to check health loads unnecessary data |
| Complexity | ❌ Two aggregates to manage, repository dependency | ✅ Simpler — one aggregate, one repository |
| Consistency | ❌ eventual consistency between Server and Health | ✅ Strong consistency within Server aggregate |
| **Winner** | ✅ **Separate aggregate** | |

**Decision:** HealthStatus is a separate aggregate. Eventual consistency is acceptable — health is computed from signals, not from authoritative server state. If health status is briefly stale, no damage occurs.

### 12.3 Time-Windowed Health vs. Instant Health

| Aspect | Time-Windowed | Instant |
|--------|--------------|---------|
| Stability | ✅ Smooth — single failure doesn't flip status | ❌ Flapping — every transient glitch changes status |
| Responsiveness | ❌ Delay — must wait for window to fill | ✅ Instant — every signal immediately reflected |
| Complexity | ❌ More complex — sliding window, decay | ✅ Simple — latest signal determines status |
| **Winner** | ✅ **Time-windowed** | |

**Decision:** Time-window (last N signals or M minutes) with weighted recency and decaying stale signals. The window size is configurable per deployment. Default: 5-minute window, 10-second signal intervals.

### 12.4 Fail-Fast vs. Additive Validation

| Aspect | Additive (all checks run) | Fail-Fast (stop on first failure) |
|--------|--------------------------|-----------------------------------|
| Completeness | ✅ Complete picture of all issues | ❌ Only first issue reported |
| Latency | ❌ Slower — all checks run | ✅ Fast — stops at first failure |
| Operator usefulness | ✅ Operator sees everything wrong | ❌ Fix first issue, re-run, find next |
| **Winner** | ✅ **Additive for integrity validation** | |

**Decision:** Integrity validation is additive — all checks run, all results reported. This gives operators a complete picture. Startup Guard uses additive validation as well, but reports a SINGLE blocked/passed result based on the most severe issue.

### 12.5 Single Health Module vs. Health Within Server Module

| Aspect | Separate `health/` Module | Extended `server/` Module |
|--------|--------------------------|--------------------------|
| Separation of concerns | ✅ Health and server lifecycle are distinct concerns | ❌ Mixing concerns reduces cohesion |
| Module boundary | ✅ Health doesn't depend on server internals, only identity | ❌ Health code mixed with server startup/stop code |
| Evolvability | ✅ Health can be developed, tested, deployed independently | ❌ Changes to health require changes to server module |
| Complexity | ❌ Cross-module communication via events | ✅ Direct method calls within same module |
| **Winner** | ✅ **Separate `health/` bounded context** | |

**Decision:** New `health/` module at domain level. It references server by identity (string/UUID) but does not import Server aggregate internals. Communication is event-driven across the module boundary.

---

## 13. Future Evolution

### 13.1 Phase 1 — Foundation (estimated: current sprint + 2)

- HealthStatus aggregate + repository
- Health Classification value object + computation rules
- Health Timeline recording
- Notification Engine (WebSocket routing of health events)
- Frontend health status display
- Integration with existing RuntimeSupervisor (extend health check loop)

### 13.2 Phase 2 — Crash Pipeline

- Evidence Collector (log reader, crash report reader)
- Crash Analyzer (pattern matching → FailureCode)
- Diagnostics Repository
- Frontend diagnostics viewer
- Crash classification display

### 13.3 Phase 3 — Pre-Flight

- Integrity Validator (file presence, config validity)
- Environment Scanner (Java, disk, memory, provider prerequisites)
- Startup Guard inserted into existing StartServerHandler
- Frontend validation detail panel

### 13.4 Phase 4 — Discovery

- Discovery Engine (filesystem polling)
- Registration Engine (create Server from discovered directory)
- Automatic server type detection

### 13.5 Phase 5 — Proactive

- Continuous integrity monitoring (periodic re-validation during runtime)
- Configuration drift detection
- Predictive health (detect degradation BEFORE crash)
- Auto-recovery pipeline (smart restart with escalation)

### 13.6 Phase 6 — Intelligence

- Historical trend analysis
- Anomaly detection on resource usage patterns
- Capacity planning recommendations
- Multi-server health correlation (issue affecting many servers detected at fleet level)

---

## Appendix A: Impact on Existing Components

| Existing Component | Impact | Nature of Change |
|-------------------|--------|-----------------|
| `RuntimeSupervisor` | Extended | New health observation methods added to existing loop |
| `ServerProvider` base class | Extended | New `validate_environment()` and `sample_resources()` methods |
| `FailureCode` enum | Extended | May add new codes for integrity/environment failures |
| `ServerCrashedEvent` | Extended | May add optional evidence reference |
| `EventBus` | No change | Already supports new event types |
| `EventDispatcher` (WS) | Extended | Subscribe to new health/diagnostics events |
| `InProcessQueue` | No change | New task definitions use existing queue |
| `Scheduler` | No change | New cron jobs use existing scheduler |
| `StartServerHandler` | Extended | Insert Startup Guard pipeline step |

## Appendix B: Key Decisions Summary

| Decision | Choice | Justification |
|----------|--------|---------------|
| Health aggregate placement | Separate `health/` module | Independence, independent lifecycle, bounded context |
| Discovery mechanism | Polling (Phase 1), event-driven (future) | Simplicity, matches existing patterns, pluggable later |
| Health computation | Time-windowed with decay | Prevents flapping, smooths transient failures |
| Validation mode | Additive (all checks run) | Complete operator picture, no hidden failures |
| Crash analysis | Two-phase (collect → classify) | Separates I/O from logic, makes classification testable |
| Health status granularity | 5 states + UNKNOWN + PENDING | Covers all operational states without over-engineering |
| Recovery pipeline | Smart restart with escalation | Prevents crash loops while enabling automatic recovery |
| Cross-module communication | Event-driven (not direct calls) | Maintains module independence, supports future distribution |
