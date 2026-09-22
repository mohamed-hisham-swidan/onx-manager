# Design Spec — Stage D: Runtime Control & Scheduling (Admission Overlay) — R2

**Status:** BUILT & VERIFIED (Commit `e77a82c`, 2026-09-17)
**Migration:** `b1e2100000017` (server_admission_leases sentinel row, earmarked reservations)
**Prerequisite verified:** Stages A/B/C CLOSED (Invariant 2 closed-as-defer in Stage A v3 per ADR-0015; per-server lock replaced with DB admission gate).
**Verification:** 2,829 passed / 6 skipped / 0 failed backend, 6/6 CI gates, 0 new routes (141 total).

## Goal

Replace the test runner's boolean per-server lock with a reserving **global admission gate** — bounded concurrent test runs up to a host-level cap with **atomically earmarked** headroom — correct across multiple worker processes on one host, reusing the shipped provider layer and the probe's math, with a minimal additive migration (two reservation columns + one sentinel-lock row), zero new routes, and zero provider rewrites. Concurrency becomes accounted instead of forbidden; everything else stays exactly as it is.

## Current Behavior

- **Sole serializer** (`infrastructure/test_runner.py:129-142`): `DockerTestExecutionRunner` holds `_server_locks: dict[str, asyncio.Lock]` (process-local memory), check-then-acquires per `server_id`, raises `ConflictError("A test run is already active for this server.")` → HTTP 409. Held for the FULL background verification (released in `_execute_verification` finally, `:579-580`; sync failures release at `:301-303`). Per-server, branch-blind. Effective policy: 1 concurrent run per server, unbounded globally.
- **Admission math without admission** (`infrastructure/resource_probe.py:36-147`): floors 4096MB + 2048 modded overhead + 50MB/bot beyond 10; cores floor 2 + 1/50 bots beyond 10; single pre-launch check raising `BotRunInsufficientResourcesError` (422). Reserves nothing (TOCTOU at `test_runner.py:147-152`).
- **No scheduler/pool/ledger anywhere** (all `schedul*` hits are cron machinery). `get_active_test_run_for_server` (interface + SQL impl) has ZERO app-code callers.
- **Execution layer already concurrent-safe**: `onx-test-{test_id}` containers, isolated bridge, unmapped ports, per-container quotas (`docker.py:372-380`). `RunIsolatedTestHandler` performs NO active-run check. Promote guard is per-commit. Frontend surfaces errors generically.
- **Versioning `Runtime`**: specified, test-only, no table, no app imports.
- **Deployment reality (verified this session, corrects an R1 assumption):** R1 assumed single-process deployment. **That assumption is withdrawn** — the app may run multiple uvicorn workers on one host. SQLite is the default backend (WAL, 30s busy timeout); other URLs get pooled engines. Any admission mutex must therefore be a **database mechanism**, never a process-local lock.

## Proposed Change

### (a) Glossary — the five Runtime* concepts, and what Stage D does to each

| # | Concept | Home | Stage D action |
|---|---|---|---|
| 1 | Versioning `Runtime` (immutable commit binding) | `versioning/domain/entities.py:319-368` | **LEAVE ALONE** — not constructed, not persisted; Stage F handoff (see (e)) |
| 2 | `RuntimeInfo` / `RuntimeDiagnostics` (provider health structs) | `server/domain/*`, provider `base.py:140` | **LEAVE ALONE** |
| 3 | `RuntimeSupervisor` (live-server lifecycle registry) | `server/application/supervisor.py` | **LEAVE ALONE** — separate axis |
| 4 | `RuntimeResource` / `runtime_ownership` (tmux/java PID arbitration) | `server/application/runtime_ownership.py` | **LEAVE ALONE** |
| 5 | `TestHandle` / `TestSpec` / `ServerTestRun` (test execution identity) | `versioning/.../test_runner.py`, `entities.py` | **EXTEND** — two stored reservation columns; admission reads PENDING/RUNNING as occupied set; runner lock removed |

No new Runtime-named concept. New code is named `TestRunAdmission` + `AdmittedReservation` (admission vocabulary), plus one `server_admission_lease` sentinel row (lock mechanics, §(b)).

### (b) Admission primitive — DB-serialized reap-read-check-earmark in ONE transaction *(revised R2)*

New `application/scheduling/admission.py`, single entry `admit(server_id, bot_count, server_type) -> AdmittedReservation`, whose **entire reap-read-check-insert sequence runs inside one database transaction holding a cross-process global lock**. The R1 in-memory `_admission_mutex` is **deleted from the design** — it cannot serialize across workers and is therefore not a mitigation of any kind.

**Serialization mechanism (dialect-aware, single-host scope):** a new `server_admission_lease` table holding exactly one sentinel row (`id=1`, enforced by `CHECK (id = 1)`, seeded in the migration's `upgrade()`). Admission opens a transaction and first claims the sentinel: on Postgres-family backends via `SELECT ... FOR UPDATE` on the sentinel row (in-repo precedent: `refresh_token.py:43`, `auth/.../repository.py:212,292`); on SQLite via `BEGIN IMMEDIATE` before the first read (upgrades the connection to RESERVED up front, so a second worker blocks *before* reading rather than reading stale and deadlocking on write — plain deferred-BEGIN would admit the classic SQLite read-write race; the 30s `busy_timeout` pragma already configured in `db.py` bounds the wait). Backend selected at runtime by dialect name (`session.bind.dialect.name`, same branching style `db.py` already uses for `"sqlite" in url`). Both paths serialize the whole sequence globally across all workers on the host sharing one database. **Backends covered:** SQLite (default/dev/CI) and Postgres-compatible URLs (pooled-engine path in `db.py`). No Postgres-only DDL, no advisory-lock functions, no `LOCK TABLE` — nothing SQLite cannot execute. True multi-HOST scheduling (separate hosts, separate DBs) stays Stage G (see Out of Scope); the corrected scope is multi-PROCESS, one host, one database.

**The sequence, under the lock, in order:**

1. **Reap (lazy, no background jobs):** transition PENDING/RUNNING rows older than `stale_run_timeout_hours` (new setting, proposed default 6) to CANCELLED with `failure_reason="stale reservation reaped"`. Their stored earmarks die with them — no separate ledger cleanup exists or is needed.
2. **Read occupied set:** all PENDING/RUNNING rows globally (new `list_active_test_runs()`; per-server getter untouched). Occupied RAM = Σ **stored** `reserved_ram_mb`; occupied cores = Σ **stored** `reserved_cores`. Rows with NULL reservations (only possible for runs created before this migration — see below) fall back to one recomputation via the unchanged `calculate_required_resources`, and are backfilled with the result in the same transaction so the fallback fires at most once per legacy row.
3. **Check two denials:** (i) `len(occupied) >= global_max_concurrent_runs` (new setting, **default 3 per Revision 1** — changeable via the existing settings-store pattern, no ceiling, per project philosophy) → `ConflictError("Global concurrent test-run cap reached …")` (409, existing code); (ii) `Σ earmarked + requested > current psutil headroom` → existing `BotRunInsufficientResourcesError` (422, unchanged).
4. **Earmark (the R2 core change):** compute the request's reservation with the UNCHANGED probe formula, then INSERT the admitted run's PENDING `ServerTestRun` row **with `reserved_ram_mb` / `reserved_cores` written on it**, and commit — all inside the still-held global lock. Only after commit does the handler proceed to `runner.run_test()` (hence to container start). If the runner then fails synchronously, the handler's existing exception path marks the row terminal (releasing the earmark by state transition).

**How this differs from R1's "recompute, store nothing" — precisely:** R1 narrowed the TOCTOU gap but left it open at exactly the point Mohamed identified: two admissions could both pass step 3 against the same live `psutil.available` figure, because an admitted-but-not-yet-started container consumes nothing observable — `available` does not reflect promises. Stored earmarks close it structurally: the second worker blocks on the sentinel until the first commits, then reads an occupied set that **includes the first worker's promise as data**, not as host state. The improvement is not "check later" but "make the promise durable before anyone else can check." A second, smaller fix falls out for free: R1's recompute used *current* settings floors for *old* runs, so a floor change mid-flight silently re-valued existing reservations; stored values are immutable per run and immune to that drift.

**Schema consequence (accepted, minimal):** two nullable INTEGER columns on the existing table — `server_test_runs.reserved_ram_mb`, `server_test_runs.reserved_cores` (NULL = pre-migration row → recompute-and-backfill rule above; all Stage D rows write non-NULL) — plus the one-row `server_admission_lease(id, holder, acquired_at)` table, all in ONE new revision `b1e2100000017` (head is `b1e2100000016`; downgrade drops the table and columns). Nullable columns keep the migration non-breaking for in-flight rows; no data migration beyond sentinel seeding.

### (c) Enforcement site — single checkpoint, confirmed (mechanics updated)

Unchanged from R1 in placement, updated in mechanics: the checkpoint lives in `RunIsolatedTestHandler._execute` immediately before `TestSpec` construction — the sole funnel for all run creation, already session-owning, command-level testable, router/permissions untouched. What changes vs R1 is *inside* the call: `admit()` now owns the PENDING-row insert (with earmarks) inside its locked transaction and returns `(run_id, reservation)`; the handler no longer creates the row separately (two writers would split the atomicity the lock exists to provide). Runner-internal enforcement remains rejected.

### (d) The per-server lock — REMOVED, subsumed, with its test rewritten

Unchanged from R1: `_server_locks`, `_get_server_lock`, the `:138-142` check-then-acquire, and lock threading through `_execute_verification` are **deleted** — a per-server limit of 1 would forbid the same-server branch concurrency this stage exists to enable, and nothing depends on serial execution. The 409 contract is preserved with cap-denial text; headroom denial keeps 422. `test_invariant_2_existing_server_lock_policy_preserved` WILL FAIL and must be rewritten to the new policy (two same-server runs admitted under cap; fourth-global denied; earmark values asserted on rows), old assertion deleted with a comment citing §(d) — Design Review must confirm the rewrite proves new behavior.

### (e) Versioning `Runtime` — explicit choice: REMAINS UNUSED, documented handoff to Stage F

Unchanged from R1. No construction, no persistence, no table; the Stage F handoff note stands (`Runtime.create` binding admitted run ↔ commit + worktree; `Runtime.id` replacing `onx-test-{test_id}` as container-identity key). ADR-0015 needs no amendment.

### (f) Live-server + concurrent-test-run coexistence — PRESERVED UNCHANGED

Unchanged from R1: admission counts only test-run rows; live servers never enter the occupied set; `psutil.available` already reflects live consumption. One R2 clarification: live usage is observed, never earmarked — only test runs hold reservations, so live-server start/stop cannot strand or double-count earmarks.

## Affected Components

- **NEW** `backend/app/modules/versioning/application/scheduling/admission.py` — `admit()`, dialect-aware sentinel claim, stale-reaping, both denials, earmark insert. (Only new app file in Stage D.)
- `backend/app/modules/versioning/application/commands/run_isolated_test.py` — replace row-creation + runner call with `admit()` → `runner.run_test()`; runner-failure path marks the admitted row terminal; settings reads (`global_max_concurrent_runs` default 3, `stale_run_timeout_hours` default 6).
- `backend/app/modules/versioning/domain/repository.py` + `infrastructure/repository.py` — add `list_active_test_runs()` (global PENDING/RUNNING by `created_at`); per-server getter untouched.
- `backend/app/modules/versioning/infrastructure/models.py` — two nullable columns on `ServerTestRunModel` + new `ServerAdmissionLeaseModel` (`server_admission_lease`).
- **NEW migration `b1e2100000017`** (on `b1e2100000016`): add columns (nullable, no backfill required beyond the NULL-fallback rule), create lease table + seed sentinel row (`id=1`); downgrade drops table and columns. Reversibility asserted by `check-db-revision` + upgrade/downgrade-cycle test.
- `backend/app/modules/versioning/infrastructure/test_runner.py` — DELETE lock machinery; preflight call stays as second-line defense.
- Tests: rewrite invariant-2 test; new `tests/application/test_stage_d_admission.py` (see below).
- No router, schema-response, or `permissions.yaml` change.

## Interfaces & Contracts

No new routes, no new permissions, no payload changes — admission enforces inside existing `POST .../versioning/tests` (`server:test:execute`); denials reuse contracted codes (409/422). `check-route-contract` must pass UNCHANGED at 141/141 (explicit regression assertion). Denial details are extended with earmark-aware fields (`occupied`, `cap`, `earmarked_ram_mb`, `required_ram_mb`, `available_ram_mb`) so a future status surface can reuse the shapes. Scheduler-status endpoint remains deferred (no UI consumer).

## Failure Cases & Edge Cases

- **Race for the last slot (two workers, one slot) — now prevented, not disclaimed:** worker B blocks on the sentinel (SQLite `BEGIN IMMEDIATE` queue / Postgres row-lock queue) until worker A commits its earmarked PENDING row; B then reads A's reservation in its occupied set and takes the 409 path. The R1 "cross-process racing is out of contract" note is **REMOVED** — this is in-scope and correct by construction. Residual risk is lock-wait latency under contention, bounded by the 30s SQLite busy timeout; admission bursts beyond that surface as 5xx via existing handlers, never as double-admission (correctness is never traded for liveness here).
- **Crash-during-reservation (phantom earmark):** three windows — (i) crash *inside* the locked transaction → DB rollback, no row, no earmark, lock released by connection teardown; nothing to reap. (ii) crash *after commit, before container start* → PENDING row WITH stored earmark and no live runner → indistinguishable from a real queued run, reaped by the stale rule on the next admission (its earmark dies with the CANCELLED transition; no recompute needed precisely because the value is stored — an R1-recompute design would have had to guess). (iii) crash *mid-run* → RUNNING row reaped identically. Worst case: one phantom occupies one slot up to the stale threshold. Sentinel staleness itself needs no handling (a lock is held only inside a transaction; a dead holder's transaction rolls back on connection loss on both backends).
- **Legacy NULL-reservation rows:** only rows predating `b1e2100000017` can carry NULL; first admission pass touching them recomputes once via the unchanged formula and backfills. If settings floors changed since they were admitted, the backfilled value reflects new floors — a bounded, one-time, documented approximation affecting only pre-upgrade in-flight runs.
- **Floor validity under N-concurrent:** unchanged from R1 — floors need NO recalibration; the earmarked-summation bounds worst case by construction, and R2 strengthens the argument (stored values can't drift). Cap default raised 2→3 per Revision 1; the multiplier stays small and settings-tunable with no ceiling.
- **Cap 0 as drain mode:** preserved (all admissions 409, in-flight runs complete, earmarks release normally).
- **Same-server stampede:** allowed to the global cap; test_id-keyed dirs/containers cannot collide; concurrent live-dir snapshot reads contend on I/O only (speed, not correctness).
- **Admission DB failure:** rollback → no row → runner never invoked → existing 5xx handling; partial earmarks impossible (single transaction).
- **Denial-message compatibility:** cap-denial message is NEW text on the existing 409 code — frontend has no message matching (verified), so no UI breakage.
- **Downgrade with live reservations:** downgrading past `b1e2100000017` drops earmark columns while RUNNING rows exist — accepted and harmless (rows keep their lifecycle; post-downgrade code is pre-Stage-D code that never reads the columns). Stated so Review doesn't have to ask.

## Tests & Verification

- **New unit tests** (`tests/application/test_stage_d_admission.py`): cap enforcement (admit 3, deny 4th, 409 shape with earmark detail fields); earmark persistence (row carries `reserved_ram_mb/cores`; occupied sum uses STORED values — proven by changing floor settings between admission 1 and admission 2 and asserting the sum is unchanged); NULL-fallback (legacy row recomputed once + backfilled); lazy reaping (stale PENDING/RUNNING → CANCELLED with reason, slot freed); drain mode (cap 0); settings defaults.
- **New concurrency tests (the R2 load-bearing set):** K concurrent `admit()` calls admit exactly the free slots (asyncio-level); file-backed SQLite-two-connection contention test proving the second admission observes the first's committed earmark (the cross-"worker" shape — separate connections, one DB file); PG-path covered by code inspection + mocked-dialect unit test ONLY if CI has no Postgres service (state which in the report — no silent pretending).
- **New integration tests:** two same-server different-branch runs simultaneously RUNNING; fourth-global 409; phantom cycle (stale RUNNING inserted directly → next admit reaps + admits); live-server coexistence (admission ignores live state).
- **Rewritten invariant test** per §(d) (reviewer confirms it proves new behavior).
- **Migration check:** upgrade to head + downgrade −1 + re-upgrade for `b1e2100000017` with actual command output (the Stage C close precedent), plus sentinel-row presence assertion post-upgrade.
- **Regression (blocking):** full backend suite vs 2829/6/0 baseline; versioning + runner + probe + promote suites; `check-route-contract` 141/141 UNCHANGED; 6/6 gates.
- **Fresh-run rule:** carried baselines MUST be re-run in-session at Build close.

## Out of Scope

- Per-branch / per-user / per-server granularity (rejected by binding decision 1).
- Queueing / PENDING-and-wait / retries (rejected by binding decision 2).
- **Multi-HOST scheduling** (separate hosts — Stage G; unchanged. Only the single-process assumption was corrected, not the single-host scope.)
- Any provider/supervisor/ownership mechanics or contract change.
- `Runtime` construction/persistence/table (Stage F per (e)).
- Floor-formula recalibration (unneeded per summation argument).
- Scheduler-status routes/UI; full test-platform rework (Stage F); run-lifecycle/verification/promotion changes.

## Governance Gate Check

**This design is D2 (Major) per GOVERNANCE.md §4** — R2 crosses the D1→D2 line that R1 stayed behind: it adds a migration (`b1e2100000017`: two columns + sentinel table) and changes a release-behavior invariant (concurrency policy + invariant-test rewrite). The classification is driven by the migration, not by size — the change remains small, additive, and fully reversible (downgrade drops cleanly; pre-migration rows behave via the NULL rule). **No further governance escalation is required before Build:** all four decisions that would otherwise need it — (1) global host-level granularity, (2) immediate-reject/no-queue, (3) cap default 3 with settings-tunable no-ceiling, (4) multi-process-safe DB serialization with stored RAM earmarks — are **already authorized by Mohamed's binding decisions** (two from the original brief, two from this revision round), and this spec implements exactly those with no silent additions (Rule 5: lock deletion, invariant-test rewrite, and new migration are all declared above). The required record is this spec + Design Review approval (§6); after approval, Build may proceed directly. Design Review must verify: the sentinel mechanism on BOTH backends (SQLite IMMEDIATE path + PG FOR UPDATE path — not just the default one), the earmark atomicity (insert + commit inside the held lock, runner invoked only after), the NULL-fallback rule, the rewritten invariant test proving new behavior, and that no changeset leaks beyond the listed Affected Components.
