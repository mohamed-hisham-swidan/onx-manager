# DECISION-2026-09-27-001 — Stage B Test Run Engine (Phase 5.5) Scope Authorization

Status: Accepted
Lane: Release Improvement
Decision level: D2
Roadmap drift: Controlled Drift

## Context

Phase 5.5 (Pre-Beta Reliability) Stage A built the operational foundation
(`Operation` aggregate, `OperationStep`, `operation.*` events, dual-layer
idempotency, WS projection, recovery reconciler) and wired exactly one
producer: `RUN_TEST` test runs
(`docs/decisions/PHASE-5.5-STAGE-A-RELIABILITY-FOUNDATION-DESIGN.md` §§4.3,
6.3). That design explicitly defers to **Stage B Test Run Engine**: execution
runner overhaul, assertion engine, cleanup plans, evidence aggregation bundles
(§22; `operation_artifacts` deferred to Stage B per §11 scope note).

A completed codebase audit (2026-09-27) inventoried the existing versioning/test
machinery against those four items. This record authorizes bounded Stage B
design and implementation scope on that evidence — nothing more.

**Terminology guard:** "Stage B" here means **Phase 5.5 Stage B (Test Run
Engine)**. It is unrelated to the completed Enterprise Branch Runtime Stage B
(Real Version Control, commit DAG, CLOSED 2026-09-17 per ROADMAP_v1.1). The two
must never be conflated in commits, tests, or migration names.

## Evidence

All claims re-verified against code on 2026-09-27 (repo root; `rg` + file
reads). `FACT` = observed; no test counts or metrics are carried forward.

**E-01 — TestDefinition execution gap (FACT).** `TestDefinition`
(`backend/app/modules/versioning/domain/entities.py:470-550`,
`infrastructure/models.py:121-140`, migration `b1e2100000018`, CRUD in
`application/commands/test_definitions.py`, routes in
`api/v1/routers/versioning.py:406-490`) persists `assertion_rules`,
`timeout_seconds`, `join_stagger/connect_grace`, and `server_type` — but no
reader exists in the execution path: the only `assertion_rules` references
outside entity/model/repository/command/schema are the two router
pass-throughs (`versioning.py:434,474`); `test_runner.py`,
`compatibility.py`, `bot_drivers.py`, and `signal_detection.py` never read
them (verified 2026-09-27). `timeout_seconds` is stored, never enforced;
`duration_seconds` converts lossily via `//60` (`run_isolated_test.py:123`).

**E-02 — TestRun lifecycle hardening gap (FACT).** `ServerTestRun`
(`domain/entities.py:599-665`, `infrastructure/models.py:90-118`) has
unguarded terminal transitions (`mark_passed/failed/cancelled` overwrite each
other); the runner is a monolithic 1446-line `DockerTestExecutionRunner`
(`infrastructure/test_runner.py:161-701`) behind a 2-method ABC; execution is
fire-and-forget with no `operation_id` column on the run (in-memory
`TestSpec/TestHandle.operation_id` only); `node_id` is fixed `"local"`;
`expires_at` is never written; list/get serializers drop Stage D/F fields
(`runtime_id`, `test_definition_id`, `evidence_bundle`, `reserved_*`).

**E-03 — Assertion engine gap (FACT).** No declarative engine exists:
`_execute_verification()` (`test_runner.py:703-1041`) branches imperatively
into a single `passed + failure_reason`; evidence assertions are fixed flat
counters (`test_runner.py:1156-1204`). Reusable pure seams exist and are
tested: `resolve_verification_strategy()`, `is_fakeplayer_artifact_usable()`
(`compatibility.py`), `check_plugin_enabled()`, `cap_log_output()`
(`bot_drivers.py`), `poll_boot_signals()` (`signal_detection.py`).

**E-04 — Cleanup plans gap (FACT).** No first-class plan type exists. Policy
is emergent across three `rmtree` sites (`cleanup_test`, lazy
`admission.reap_stale_reservations`, `PruneTestArtifactsHandler`) with two
different path-resolution schemes (handle-absolute vs reconstructed
`<servers_root>/<sid>/.onx/tests/<tid>`), all `ignore_errors=True`, and a
`passed=True` default that silently deletes debug artifacts on misuse.

**E-05 — Evidence aggregation gap (FACT).** Versioning evidence is untyped
`dict` end-to-end (DB JSON → Pydantic `dict` → TS `Record<string,unknown>`).
The frontend modal reads keys the backend never writes
(`assertions.boot_passed` vs backend `boot_gate_passed`;
`crash_analysis.suspected_culprit_mods` vs backend `blamed_mod` — verified
2026-09-27 in `TestEvidenceModal.tsx:83-85,158,177-181` vs
`test_runner.py:273,1169,1198`), so real payloads render fallback while the
unit test passes on a frontend-shaped fixture. A second, unrelated
`EvidenceBundleModel` exists in the health module
(`health/infrastructure/models.py:31-42`) — naming collision, separate store.

**E-06 — What must NOT be reopened (FACT).** Admission/earmarks
(`scheduling/admission.py`, migration `b1e2100000017`), promotion gating +
invalidation guard (`promote_commit.py:118-145`), force-bypass audit,
branch-protection enforcement, and the Stage A `Operation` projection layer
are tested, permissioned, and migration-chained. The per-server execution lock
was deliberately replaced by the global admission gate (Stage D); the
`RUN_TEST` exemption from the mutating-ops lock is intentional
(`operation_service.py:130-144`).

## Options

1. **Authorize bounded Stage B** (chosen): the five items above, reusing all
   E-06 primitives, with the hard boundaries below.
2. **Defer Stage B entirely**: keeps current behavior; cost is that
   `assertion_rules` stays dead config, the modal keeps rendering fallback on
   real payloads, and cleanup stays three divergent deleters.
3. **Authorize a narrower slice** (e.g. evidence keys only): rejected as a
   standalone scope — the modal fix without bundle versioning repeats the
   same silent-miss pattern the codebase audit flagged.

## Decision

Authorize Phase 5.5 Stage B design and implementation, bounded to:

1. **TestDefinition execution:** consume `assertion_rules` (typed schema +
   validator) OR explicitly deprecate it; wire `timeout/stagger/grace`
   through `BotConfigResolver`/`TestSpec`; fix seconds→minutes rounding;
   decide strict-vs-fallback enum policy. Extend entity/model/CRUD — no
   table replacement.
2. **TestRun lifecycle hardening:** guard terminal transitions, add
   `operation_id` linkage, define `expires_at` semantics, fix serializer
   field drops. Keep the `ServerTestRun` aggregate, admission, retention,
   and promote gates — extract inside `DockerTestExecutionRunner` only.
3. **Assertion engine:** per-driver verifiers behind one interface returning
   per-assertion verdicts; reuse E-03 pure functions as the mode/driver
   pre-pass; keep `BotVerificationResult` as legacy adapter; unify the
   `connected_bots`/`bots_spawned_actual` and `driver "none"`/`"smoke_test"`
   duplications first.
4. **Cleanup plans:** parameterize `cleanup_test` + reap + pruner (retention
   source, artifact set); one canonical `test_dir(server_id, test_id)`
   resolver; explicit verdict parameter (no `passed=True` default reliance).
5. **Evidence aggregation:** versioned/validated bundle dict; reconcile
   modal↔backend keys in one direction before enrichment; resolve
   single-`blamed_mod` vs list expectation; unify the three log-tail caps.
   `operation_artifacts` table (deferred to Stage B by Stage A §11) is
   within scope if the design requires it.

**Hard boundaries (violations need a new decision):** no changes to
admission formula/caps or the `RUN_TEST` exemption; no reintroduction of a
per-server execution lock; no change to promotion-gate semantics
(`require_test_pass` wiring needs its own D1 minimum); no second status
machine, executor, or evidence store alongside `Operation`/`ServerTestRun`;
no Stage C–G files; `Operation` remains projection, run/runtime remain truth.

**Design-phase sub-decisions required before implementation touches them:**
breaking `operation.*`/evidence contract change → D2 + version bump;
`operation_artifacts` or any new migration → D2; health-vs-versioning
`EvidenceBundle` unify-or-keep → D1 minimum; `require_test_pass` wiring →
D1 minimum; admission tuning → D1 (lock reversal → D2).

## Why

project governance standards: (1) Not launch-blocking — current runs execute and
promote correctly; this is quality/debt inside the release objective. (2)
Reduces real risk: dead config, silent modal misses, divergent deleters, and
unguarded terminal overwrites are all observed, not hypothetical. (3)
Unblocks Stage C–E consumers of evidence/assertions. (4) User impact is
material (honest test verdicts, working evidence UI, predictable cleanup) but
not release-defining. (5–6) Effort is medium and contained to two modules;
drift cost is bounded by the five items plus boundaries. (7) Reversible (see
below). (8) Deferral keeps every gap listed in E-01–E-05, including a modal
that misrenders real backend payloads.

## Impact

- Product/user: honest assertions, working evidence modal, predictable
  artifact retention; no new product promise, no API promise beyond
  additive bundle keys.
- Stability: fewer silent-miss and disk-fill failure modes; guarded terminal
  states.
- Performance: none expected; no hot-path rewrite.
- Architecture: runner internals decomposed behind interfaces; no new
  subsystem, no second ledger.
- Operations: one canonical test-dir resolver grounded in authoritative server
  deployment directory (amended by DECISION-2026-09-28-001); retention stays
  24h default unless separately decided.

## Effort

Medium: concentrated in `versioning/infrastructure/test_runner.py`,
`bot_drivers.py`/`compatibility.py` consumers, `get_test_evidence.py` +
modal, and the three cleanup sites; plus contract tests. No cross-module
rewrite.

## Reversibility

Easy before any migration ships (pure code, additive keys, feature-flag-free
revert per file). Moderate after `operation_artifacts` or bundle-schema
migration (requires downgrade path, as with `b1e2100000018` precedent).

## Roadmap impact

Controlled Drift (not Major): bounded internals, no launch-promise change,
same release objective. Counter-evidence considered: ROADMAP_v1.1 contains
no Phase 5.5 entry at all — but that is a pre-existing sync gap (Stage A
itself shipped without one), repaired minimally below rather than via a
re-baseline. D2 still mandates synchronization: add the Phase 5.5 section
(Stage A recorded, Stage B Proposed) — no phase reorder, no launch-target
move, drift budget unaffected.

## Verification

Stage B is done when: `assertion_rules` is consumed or removed (no
write-only path); terminal transitions are guarded (regression tests for
overwrite races); modal renders real backend payloads (contract test pinning
backend keys); one test-dir resolver + explicit-verdict teardown (no
`ignore_errors` divergence); bundle has version/validation; full backend +
frontend suites green with 6/6 CI gates (including `check-route-contract`
and ruff baseline); project state tracking updated with fresh numbers only.

## Outcome

Owner approved bounded Stage B scope (Mohamed, 2026-09-27). Stage B design
may proceed within the five authorized items and hard boundaries above;
implementation remains gated on the design-phase sub-decisions listed below.

## Remaining decision blockers

1. ~~Owner approval~~ — resolved: approved 2026-09-27 (this Outcome section).
2. Design-phase sub-decisions listed above must be classified and recorded
   as they arise (breaking contract → D2, migration → D2, others per list).
3. `assertion_rules` consume-vs-deprecate is a design choice, not
   pre-decided here.
