# SPEC-TPS-VALIDATION-001 — TPS Validation Contract Fix

- **Date:** 2026-08-18
- **Phase:** Post-Phase-7 runtime-bug track, Issue 2 (metrics pipeline)
- **Cycle position:** RECON (done) → **DESIGN (this doc)** → independent review → Build → build review → Commit
- **Status:** DRAFT — awaiting independent design review. No code changed.
- **Related:** Issue 1 (SPEC-STARTING-VISIBLE-001) confirmed unrelated (Finding R-4).

---

## 1. Problem Statement

`MetricPoint.__init__` hard-rejects any TPS outside `[0, 20]` with a `ValueError`, aborting
construction of the **entire** metric point (all 4 metrics discarded). Real Purpur/Paper `/tps`
output and third-party TPS plugins can legitimately report tick/second `>20.0` during lag
catch-up. The pipeline is a verbatim regex passthrough (`parse_tps`) — no arithmetic ever
creates the overshoot; the validator assumes a physical ceiling the real source does not honor.

Per affected cycle: DB metric point dropped (chart gap), `MetricCollectedEvent` suppressed
(WS silent), Prometheus gauge pinned to default `20.0`, and up to 5 warnings/sec at the 0.2s cadence.

**Goal:** eliminate false collection failures without masking genuinely broken data.

---

## 2. Findings

### RECON recap (confirmed)
| ID | Finding |
|----|---------|
| R-1 | Raise site: `aggregate.py:24-25` — hard reject, no clamp. |
| R-2 | Path: scheduler direct-exec (0.2s) → `metrics_collector.py:31` → `collector.py:158/202` → `send_command("tps")` → `parse_tps` → `MetricPoint(...)`. |
| R-3 | `parse_tps` (`rcon_client.py:196-224`) verbatim passthrough; fallbacks hardcoded `20.0`. |
| R-4 | Pre-existing: validator from initial commit `ee67851` (2026-07-26); parser last touched `158e5bfe` (2026-08-06). Issue 1 only raised exposure cadence. |
| R-5 | No cascade: `collect()` swallows at `collector.py:247-248`; per-server `collect_one` isolation. |
| R-6 | Same-class (deferred): `cpu_percent` (`aggregate.py:30-31`) hard cap with no epsilon (psutil per-process % can exceed 100 pre-normalization at `collector.py:112-113`). |

### New design-phase findings
| ID | Finding |
|----|---------|
| D-1 | **Validator is load-bearing on the READ path too.** `SQLMetricRepository.get_series` (`repository.py:50-58`) rebuilds `MetricPoint` from stored rows; any stored `>20` would 500 `GET /monitoring/metrics`. So "store >20 uncapped" is not viable, and constructor-clamp + uncapped-store would silently alter values on read. => clamp-at-source, symmetric with validator. |
| D-2 | **No duplicate validation layer.** Router builds dict from passive `MetricPointReadModel` (`routers/monitoring.py:45`; `get_metrics.py:9-22`); no Pydantic bounds. `MetricPoint` is the single enforcement point. |
| D-3 | **No retroaction needed.** Over-20 values were never persisted (always rejected); DB rows are `<=20`. No migration. |
| D-4 | **Existing tests compatible.** `test_monitoring_aggregate.py:25` (`tps=25` raises) and `:29` (`tps=-1` raises) stay valid; `:37` (`cpu_percent=101` raises) stays green only if cpu bundling defers. No test asserts the old message string. |

---

## 3. Design Decision — new TPS contract

### 3.1 Bound semantics
| Input | Behavior |
|-------|----------|
| `NaN` / `±inf` | **Reject** (`ValueError`) — machine garbage. |
| `< 0` | **Reject** (`ValueError`) — broken source stays loud. |
| `0.0 … 20.0` | **Store as-is.** |
| `(20.0 … 20.5]` | **Clamp to 20.0**, store — legit catch-up spike normalized. |
| `> 20.5` | **Reject** (`ValueError`) — 999 / overflow / garbage stays loud. |

**Why 20.5:** real catch-up overshoot is a small % (documented); 20.5 ≈ 2.5% headroom. An
unbounded ceiling would let garbage into charts (violates goal 1); a strict 20 relives today's failure.

**Why clamp (not store) 20.0–20.5:** `/tps` is semantically capped at 20 (perfect). Overshoot
carries no information for consumers; clamping keeps storage canonical and write/read symmetric (D-1).

### 3.2 Change 1 — `parse_tps` (source normalization)
**File:** `backend/app/modules/monitoring/infrastructure/rcon_client.py` (:196-224)

Add private helper `_clamp_tps(value: float) -> float` returning `min(value, 20.0)`. Apply at
all three return sites ("TPS from last", "Overall TPS", `avg/average` fallback).

**Deliberate asymmetry — no negative clamping:** negative TPS is garbage and must reach the
domain garbage-branch to be rejected loudly, not silently become `0.0`. `0.0` stays meaningful (hung server).

### 3.3 Change 2 — `MetricPoint.__init__` (domain validation)
**File:** `backend/app/modules/monitoring/domain/aggregate.py:24-25`

Before:
```python
if tps < 0 or tps > 20:
    raise ValueError(f"TPS must be between 0 and 20, got {tps}")
```
After (with `import math` at module top):
```python
_TPS_MAX = 20.0
_TPS_SANITY_CEILING = 20.5

if not math.isfinite(tps) or tps < 0.0 or tps > _TPS_SANITY_CEILING:
    raise ValueError(f"TPS out of sane range [0, 20.5], got {tps}")
self.tps = min(tps, _TPS_MAX)
```

### 3.4 Deferred (Open Questions §7): cpu_percent (OQ-2), prometheus-pin-on-failure (OQ-3)

---

## 4. Error / Log / Semantics Changes

| Location | Change |
|----------|--------|
| `rcon_client.py` | No new errors; clamp is silent (debug-log optional, not required). |
| `aggregate.py` | Rejection message: `"TPS must be between 0 and 20, got X"` → `"TPS out of sane range [0, 20.5], got X"`. |
| Stored semantics | `tps` always ∈ `[0, 20.0]` (was already, but now clamped instead of rejected). Charts / Prometheus / WS unchanged in format. |

---

## 5. Test Plan

1. `parse_tps("...TPS from last 5s...: 20.1, 20.0, 20.0, 20.0")` → `20.0` (clamped).
2. `parse_tps("...TPS from last 1m...: 20.05, 20.0, 20.0")` → `20.0`.
3. `parse_tps("...TPS from last...: -3.2, ...")` → `-3.2` unchanged (reachable by validator).
4. `parse_tps("...TPS from last...: 19.99, ...")` → `19.99` unchanged.
5. `MetricPoint(tps=20.1)`: **constructs; stored tps == 20.0, no exception** (proof over-20 legit no longer discards the point).
6. `MetricPoint(tps=20.4)` → 20.0; `MetricPoint(tps=19.99)` → 19.99.
7. `MetricPoint(tps=999)` → `ValueError` (garbage rejected).
8. `MetricPoint(tps=-1)` → `ValueError`.
9. `MetricPoint(tps=float("nan"))` and `float("inf")` → `ValueError`.
10. Integration: mock `send_command` returning 20.1 → `collect()` persists `tps=20.0` **and** publishes `MetricCollectedEvent` (full point survives).
11. Read round-trip: `repo.get_series` returns stored value without raising.
12. Garbage-999 integration: `collect()` logs "Metrics collection failed", stores nothing, other servers unaffected (per-server isolation intact).
13. Regression: existing `test_monitoring_aggregate.py` reject-cases (25 / -1) stay green; `cpu_percent=101` case unchanged if OQ-2 defers.
14. Frontend: no code change expected; visual sanity only.

---

## 6. Findings Ledger (this doc)

| ID | State | Detail |
|----|-------|--------|
| R-1..R-6 | confirmed | see §2 (RECON, previously reported). |
| D-1 | new | read-path load-bearing validator → clamp-at-source, not uncapped store. |
| D-2 | new | no API/Pydantic duplicate validation. |
| D-3 | new | no retroactive migration needed (nothing >20 was ever stored). |
| D-4 | new | existing test surface remains valid under new bounds. |

---

## 7. Open Questions

- **OQ-1 (default: clamp to 20.0).** Clamp catch-up spikes to the physical ceiling vs store `(20, 20.5]` uncapped and clamp only on read. Default = clamp at write; uncapped store would silently alter values on read and breaks D-1 symmetry.
- **OQ-2 (default: defer to separate spec).** Bundle the `cpu_percent` same-class fix? Default = defer: (a) not field-observed; (b) changes documented behavior asserted by `test_monitoring_aggregate.py:37`; (c) keeps review blast radius on TPS. Recommend a follow-up one-line spec.
- **OQ-3 (default: defer).** On genuine collection exception, leave Prometheus gauge at last value instead of default `20.0` (`collector.py:247-250`, `metrics_collector.py:56-64`). Default = defer; genuine failures become rare post-fix and this is signal polish only.