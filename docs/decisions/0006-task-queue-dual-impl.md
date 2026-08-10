# ADR-0006: Task Queue — Dual Implementation, Event Store Chain, DLQ, Metrics Retention

**Status**: Accepted
**Date**: 2026-07-23
**Author**: Architecture Review Board

## Context

Batch 09 added monitoring, scheduled tasks, and the event store infrastructure. Four design decisions were made to balance development convenience, production durability, and operational maintainability.

---

### Decision 1: TaskQueue — Abstract Base with Dual Implementation

The system needs a task queue that works in development without infrastructure dependencies (Redis) but scales to production with proper durability.

**Chosen Approach**: Abstract `TaskQueue` ABC with two implementations:
- **InProcessQueue** (SQLite-backed, default in development) — uses `asyncio.ensure_future` for inline execution
- **ArqQueue** (Redis-backed, production) — uses the Arq worker for durable async task execution

Both share the same interface; the active implementation is selected via configuration.

**Consequences**: The `InProcessQueue` is not durable across process restarts. `ArqQueue.get_status()` and `ArqQueue.get_result()` are stubs because Arq manages state internally within the worker. Batch 10 (Frontend) can use either queue transparently through the shared interface.

**Post-hoc finding (2026-07-29)**: The `Scheduler` and `InProcessQueue` were
defined in Batch 09 but **never wired into production**. They were only
instantiated in test fixtures. The `lifespan()` function in `main.py` did
not create or start them, meaning:
- `integrity_scan_hourly` and `metrics_collect_every_1s` cron jobs never fired
- `run_metrics_collection_task` was never called
- No rows were ever written to `metric_points`

This was fixed by adding the wiring to `main.py` lifespan in commit
`9bef6fa`. If that wiring is ever removed or moved, the same symptoms will
recur — there is no second-chance initialization path.

---

### Decision 2: Event Store — Application-Level Hash Chain over DB Triggers

The event store needs tamper evidence without adding audit-trigger overhead in the database.

**Chosen Approach**: Application-level SHA-256 chain. Each `StoredEvent` stores `prev_hash`, and `EventChain.compute_hash(prev_hash + payload)` produces the next hash. `verify_chain()` walks forward recomputing hashes.

**Consequences**: Slightly more code in Python compared to DB-level enforcement, but more portable across database backends. The audit log in Batch 08 uses a similar cryptographic chain pattern (developed independently — both are valid).

---

### Decision 3: Dead Letter Queue — Store-Then-Replay

Events that fail after exhausting retry attempts must not be lost but also must not block the event pipeline indefinitely.

**Chosen Approach**: After 3 retries, the event is moved to a `dead_letter_events` table. An admin replays events via DLQ commands (`replay` re-publishes to the event bus). Failed events never auto-retry from the DLQ.

**Consequences**: Requires manual intervention for DLQ replay. Prevents infinite retry loops. The Batch 10 admin UI should expose a DLQ viewer with replay and delete actions.

---

### Decision 4: Metrics Retention — Separate Rollup Tables

Metrics are collected every 10 seconds. Raw data cannot be retained indefinitely for performance and storage reasons.

**Chosen Approach**: Four-table retention pipeline:
- `raw_metrics` — 10s resolution, retained 1 hour
- `metrics_1m` — 1-minute rollup, retained 30 days
- `metrics_1h` — 1-hour rollup, retained 1 year
- `metrics_1d` — 1-day rollup, retained forever

Rollup tasks convert data between tiers. A cleanup task deletes raw rows older than 1 hour.

**Consequences**: More tables and more code compared to a single-table TTL approach. Queries against rolled-up data are fast and do not require filtering over large raw datasets. Rollup tasks are pending implementation.
