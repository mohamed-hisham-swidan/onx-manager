# SPEC-CONSOLE-OVERVIEW-001 — Console Access Address, Port Widget, Icons, Uptime Fix, TPS Honesty

- **Date:** 2026-08-18
- **Phase:** Post-Phase-7 runtime-bug track, Issue 3 (console/detail overview)
- **Cycle position:** RECON (done) → **DESIGN (this doc)** → independent review → Build → build review → Commit
- **Status:** DRAFT — awaiting independent design review. No code changed.
- **Related:** Issue 2 (SPEC-TPS-VALIDATION-001) shipped the TPS clamp; this spec extends its domain model with honest `tps=None`. The TPS-validation files are currently **uncommitted** in the worktree, so both changes must be integrated at build time.

---

## 1. Problem Statement

The server detail page (which hosts the console) has five broken/missing pieces of the
"how do players reach my server / is my server healthy" story:

1. **Address widget is local-only.** `ServerDetailPage.tsx:220` derives the address solely from
   `deployment_host:deployment_port` and shows `"—"` when `deployment_host` is null. It ignores
   the network-exposure subsystem entirely, even though playit.gg / Cloudflare tunnel addresses are
   already loaded on the same page (`useServerExposure`, line 68) and rendered in the "Public
   Exposure" detail row (`:400-407`).
2. **No port widget.** The MC listen port exists (`server.port`) but has no dedicated, copyable widget.
3. **No icons on any overview widget.** The right-column cards (Address, Uptime, CPU, RAM, Storage)
   are bare text; the `Icon` component is not used there.
4. **Uptime does not work.** Two defects: `RuntimeSupervisor.uptime` (`supervisor.py:85-88`) mixes
   `time.monotonic()` (`_started_at`, line 59) with `time.time()` — result is garbage/negative.
   The diagnostics fallback (`get_runtime_diagnostics.py:115`) reads `server.runtime.uptime_seconds`,
   which is **never written** (always `0.0`) → frontend shows `"—"` (`ServerDetailPage.tsx:469`).
5. **TPS is dishonest in both directions.** (a) Before/during start, the UI shows the **stale
   historical** TPS (`currentMetric` = latest of the last 120 DB points, `ServerDetailPage.tsx:207-209`,
   `ServerConsole.tsx:31-35`) regardless of server status. (b) When RCON is disabled/unreachable —
   the default for vanilla — the collector writes fabricated `tps=20.0`
   (`collector.py:122,161`) forever, so real TPS can never appear.

**Goal:** make the overview panel tell the truth: the correct reachable address, a visible port,
icons for every widget, working uptime, and TPS that is either real or explicitly unknown.

---

## 2. Findings

### RECON recap (confirmed)
| ID | Finding |
|----|---------|
| R-1 | Address widget (`ServerDetailPage.tsx:220`, `:449-464`) uses `deployment_host` only; no exposure. |
| R-2 | Exposure data available in-scope: `useServerExposure` (line 68); `exposure.targets[].public_address` holds playit `host:port` (`survival.ply.gg:12345`) or cloudflare hostname. `isExposed` = `desired_state==="ENABLED" && aggregate_status==="ACTIVE"` (`useServerExposure.ts:244`). |
| R-3 | Right-column widgets (`:448-499`) have no icons; `Icon` names today: `server, database, activity, users, copy, bell, folder, file, …` (no `globe/clock/cpu/hard-drive`). |
| R-4 | Uptime bug A: `supervisor.py:59` `_started_at = time.monotonic()` vs `:85-88` `time.time() - (_started_at + _start_duration)` — mixed clocks. |
| R-5 | Uptime bug B: `get_runtime_diagnostics.py:115` falls back to `server.runtime.uptime_seconds`, which nothing ever sets (`value_objects.py:174` default `0.0`; `aggregate.py:228-237,240-251` never pass it). |
| R-6 | TPS-stale: `useServerMetrics` (`useServerMetrics.ts:14-19`) polls `getMetrics(serverId, 120)`; points persist after stop; latest point shown regardless of `status`. |
| R-7 | TPS-fake: `collector.py:122,161` default `tps=20.0`; real values only when `enable-rcon=true` **and** `rcon.password` set (`:182-204`); vanilla `/tps` absent → 20.0 forever. |
| R-8 | WS path: `metrics:<serverId>` batch (`dispatcher.py:217-223`) → `WebSocketManager` merge (`WebSocketManager.tsx:37-49`) → `metrics` query cache. WS data carries the same fake/nullable tps. |

### New design-phase findings
| ID | Finding |
|----|---------|
| D-1 | **TPS nullability is cheap at the domain edge.** `MetricPoint` already clamps (`aggregate.py:15-36`). Making `tps: float \| None = None` and skipping validation when `None` keeps SPEC-TPS-VALIDATION-001 semantics for real values while allowing "unknown". |
| D-2 | **DB must change.** `MetricPointModel.tps = Column(Float, nullable=False)` (`models.py:13`) → `nullable=True`. Needs one alembic migration; existing rows are untouched (values stay). |
| D-3 | **Prometheus gauge must not be fed `None`.** `metrics_collector.py:60-64` calls `update_tps` unconditionally; guard so unknown TPS leaves the gauge at last known (matches OQ-3 spirit of SPEC-TPS-VALIDATION-001). |
| D-4 | **No new API surface.** `GET /monitoring/metrics` returns a plain dict list (`monitoring.py:43-52`); `tps=None` flows through with zero schema changes. WS batch serializer likewise. |
| D-5 | **Player count stays `int`.** Only TPS is made nullable. Players already default `0`; making them nullable too widens the migration/validators for no user-visible win (badge is gated on `running` anyway). |
| D-6 | **Existing tests protect the uptime contract only weakly.** `test_supervisor.py:170-171` asserts `uptime >= 0` — passes even with the mixed-clock bug (garbage can be `>= 0`). A wall-clock vs monotonic regression test is needed. |
| D-7 | **Uptime-after-stop should reset to `0`** (not keep last). `mark_stopped` rebuilds `RuntimeInfo` without `start_time` → diagnostics fallback naturally yields `0` → frontend `"—"`. Correct UX. |
| D-8 | `ServerMetricsCharts` (used inside `ServerShell`) consumes the same `metrics` cache — must tolerate `tps: null` (filter nulls / render no-data). |

---

## 3. Design Decision

### 3.1 Effective Access Address (address widget)

**File (new):** `frontend/src/server_manager/utils/accessAddress.ts`

Pure helper returning the reachable address with its source kind, used by the Address widget:

```ts
export type AddressKind = "playit" | "cloudflare" | "local" | null;

export interface ResolvedAddress {
  address: string | null;
  kind: AddressKind;
}

export function resolveAccessAddress(
  server: { deployment_host: string | null; deployment_port: number | null; port: number },
  exposure: { desired_state: string; aggregate_status: string; targets?: Array<{ public_address: string | null }> } | null | undefined,
): ResolvedAddress
```

Precedence (first match wins):
1. **playit / cloudflare:** `desired_state === "ENABLED"` **and** `aggregate_status === "ACTIVE"` **and** `targets[0]?.public_address` truthy.
   - kind = `exposure.method` (`"playit"` → playit, `"cloudflare_tcp"` → cloudflare).
   - address = `targets[0].public_address` verbatim (playit already includes port; cloudflare is hostname).
2. **local:** `server.deployment_host` truthy → `${host}:${deployment_port ?? port}`.
3. **none:** `{ address: null, kind: null }` → widget renders `"—"`.

Address widget (`ServerDetailPage.tsx:449-464`) uses the helper; keeps the copy button; adds a
`globe` icon. The "Public Exposure" detail row (`:399-416`) is left as-is (already correct).

### 3.2 Server Port widget (new, directly under Address)

**File:** `ServerDetailPage.tsx` — new card between Address (`:464`) and Uptime (`:466`).

- Label: **Server Port**, value: `server.port` (always present on `ServerDetailResponse`, `types.ts:16`).
- `server` icon, copy button (same pattern as Address), `data-testid="server-port-widget"`.
- When the tunnel address is shown, the port widget still shows the **local** MC port (playit/cloudflare
  ports live inside `public_address`); the two widgets are complementary, not duplicated.

### 3.3 Icons on every overview widget

Add 4 new icons to `frontend/src/components/ui/Icon.tsx` (union + `PATHS` entries, lucide-style 24×24):

| New icon | Used by |
|----------|---------|
| `globe`  | Address |
| `clock`  | Uptime |
| `cpu`    | CPU Usage |
| `hard-drive` | Storage Usage |

Reuse existing: `server` (Port), `database` (RAM), `users` (players badge), `activity` (TPS badge).

Update `Icon.test.tsx` to render the 4 new names without throwing.

### 3.4 Uptime fix (backend + frontend display)

**File:** `backend/app/modules/server/application/supervisor.py`

- Add `self._ready_at_wall: float | None = None` (init near line 61).
- In `_verify_startup` where readiness is confirmed (currently `:172-173`, right after
  `self._start_duration = elapsed`), also set `self._ready_at_wall = time.time()`.
- `uptime` property (`:85-88`) becomes:
  ```python
  @property
  def uptime(self) -> float:
      if self._ready_at_wall is not None:
          return max(0.0, time.time() - self._ready_at_wall)
      return 0.0
  ```
  `_started_at` stays monotonic (used by deadline logic at `:160-172`); no other callers depend on `uptime` mixing clocks.

**File:** `backend/app/modules/server/application/queries/get_runtime_diagnostics.py:115`

```python
if supervisor and supervisor.is_running:
    uptime = supervisor.uptime
elif server.runtime and server.runtime.start_time and server.status.value in ("running", "starting"):
    uptime = max(0.0, time.time() - server.runtime.start_time)
else:
    uptime = 0.0
```
- Supervised path: fixed supervisor uptime.
- Unsupervised-but-running fallback: derive live from persisted epoch `start_time` (set at
  `mark_running`, `aggregate.py:240-251`, from provider metadata).
- Stopped/crashed: `0` → frontend `"—"` (matches R-7/D-7).

**Frontend:** `ServerDetailPage.tsx:468-470` unchanged in logic; now receives a real value. No change to `formatUptime` (`:45-55`).

### 3.5 TPS honesty — nullable TPS end-to-end

Make TPS `float | None` from source to UI. When RCON is unavailable, **no value** is recorded
instead of fabricated `20.0`.

**Backend:**

| File | Change |
|------|--------|
| `infrastructure/collector.py:43` | `ServerMetrics.tps: float \| None = None` (players stays `int = 0`). |
| `infrastructure/collector.py:122,161` | `tps = None` (remove `20.0` defaults). |
| `infrastructure/collector.py:202-204` | `if rcon_tps is not None: tps = rcon_tps` (keep players assignment as-is). |
| `infrastructure/collector.py:222-228,236-244` | `MetricPoint(tps=tps, …)` and `MetricCollectedEvent(tps=metric.tps, …)` — types widen to `float \| None`. |
| `infrastructure/collector.py:271-276` | `MetricCollectedEvent.tps: float \| None = None`. |
| `domain/aggregate.py:19-40` | `MetricPoint.__init__` takes `tps: float \| None = None`; **validation block runs only when `tps is not None`**; `self.tps = min(tps, _TPS_MAX)` when not None. Reject cases (NaN/inf/<0/>20.5) unchanged for real values. |
| `infrastructure/models.py:13` | `tps = Column(Float, nullable=True)`. |
| **alembic migration** | New revision `alter metric_points.tps → nullable` (`op.alter_column("metric_points", "tps", existing_type=sa.Float(), nullable=True)`). Existing rows unchanged. |
| `infrastructure/repository.py:17-30` | `record()` passes `point.tps` (None OK once column nullable). |
| `infrastructure/repository.py:49-57` | `get_series()` reconstructs `MetricPoint(tps=model.tps, …)` — None OK per D-1. |
| `tasks/definitions/metrics_collector.py:60-64` | Guard: `if metrics.tps is not None: prometheus.update_tps(...)`. players/cpu/ram unconditional. |

**Frontend:**

| File | Change |
|------|--------|
| `services/api.ts` (`MetricsSnapshot`) | `tps: number \| null`. |
| `components/ServerConsole.tsx` | New optional prop `serverStatus?: string`. `liveTps = serverStatus === "running" ? (tps ?? latestMetric?.tps) : undefined`; same gate for `livePlayers`. Renders `"—"` (already handled) when undefined; null-safe. |
| `pages/ServerDetailPage.tsx:207-209` | Keep `currentMetric`, but gate **all** TPS/players display on `server.status === "running"` **and** `currentMetric?.tps != null`. |
| `pages/ServerDetailPage.tsx:211-213` | `tpsData = (metrics ?? []).map(m => m.tps).filter((t): t is number => t != null)`. |
| `pages/ServerDetailPage.tsx:239-244` | Header TPS/players only when running + non-null. |
| `pages/ServerDetailPage.tsx:288-326` | TPS & Tick Rate card: `currentMetric.tps >= 19.5` etc. only evaluated when running + non-null; else `"—"` (existing ternary handles undefined; add null check). |
| `pages/ServerDetailPage.tsx:256-260` | Pass `serverStatus={server.status}` to `<ServerConsole>`. |
| `components/ServerMetricsCharts.tsx` | Tolerate `tps: null` (filter nulls from chart series; no-data state when empty). |
| `components/WebSocketManager.tsx:37-49` | Merge maps `s.tps` into snapshot — null-safe passthrough (no change required, verify type). |

**Semantics summary:**

| Condition | TPS shown |
|-----------|-----------|
| Server stopped / created / crashed | `"—"` (gated on status, regardless of history) |
| Server starting | `"—"` (no RCON yet) |
| Running + RCON OK | real `/tps` value (clamped per SPEC-TPS-VALIDATION-001) |
| Running + RCON disabled/unreachable | `"—"` (honest unknown, not fake 20.0) |

---

## 4. Error / Log / Semantics Changes

| Location | Change |
|----------|--------|
| `supervisor.py` | `uptime` returns wall-clock elapsed since ready (was mixed-clock garbage). No new errors. |
| `get_runtime_diagnostics.py` | Fallback derives uptime from `start_time` when running-unsupervised; `0` when stopped. |
| `aggregate.py` | `MetricPoint(tps=None)` now constructs; existing rejections unchanged for non-None. No message change. |
| `collector.py` | No new errors; RCON-missing no longer fabricates 20.0 — silently records `None` (same swallow path `:247-248`). |
| Prometheus | Gauge not updated on unknown TPS (stays at last known) — matches deferred OQ-3 of SPEC-TPS-VALIDATION-001. |
| Stored semantics | `metric_points.tps` may be `NULL`; charts/WS read it as unknown. |

---

## 5. Test Plan

### Backend
1. **Supervisor uptime (regression for R-4/D-6):** start supervisor with a fake provider that
   becomes ready instantly; assert `uptime > 0` and `uptime ≈ time.time() - ready_at_wall` within
   tolerance; assert uptime is `0` before readiness is recorded. (`tests/application/test_supervisor.py`)
2. **Diagnostics fallback:** with no supervisor, `server.runtime.start_time` set + status running →
   `uptime_seconds ≈ time.time() - start_time`; status stopped → `uptime_seconds == 0`.
   (`tests/application/test_runtime_diagnostics.py`, new or existing)
3. **Collector — no RCON:** server with `enable-rcon` unset/empty password → `collect()` returns
   `ServerMetrics(tps=None)`; DB row persisted with `tps=NULL`; `MetricCollectedEvent.tps is None`.
4. **Collector — RCON OK:** mocked `send_command` returning 20.1 → `tps == 20.0` (clamped), event published.
5. **Collector — RCON failure:** `send_command` raising → `tps=None`, point still recorded, no crash
   (isolation intact).
6. **Domain:** `MetricPoint(tps=None)` constructs and stores `None`; `MetricPoint(tps=20.5)` → 20.0;
   `MetricPoint(tps=999)` / `-1` / `nan` / `inf` still raise (SPEC-TPS-VALIDATION-001 regression).
7. **Repo round-trip:** `record(None)` + `get_series` returns `tps=None` without raising.
8. **API:** `GET /monitoring/metrics?server_id=…&limit=5` with a NULL row → JSON contains `"tps": null`.
9. **Migration:** `alembic upgrade head` applies; column nullable; existing rows preserved.
10. **Full regression:** `pytest` backend suite green.

### Frontend
11. **`resolveAccessAddress` unit tests:** playit ACTIVE → playit address+kind; cloudflare ACTIVE →
    hostname+kind; ENABLED but not ACTIVE → local; no exposure → local when `deployment_host`; no host
    → `{ null, null }`.
12. **Icon:** new `globe/clock/cpu/hard-drive` render without throwing (`Icon.test.tsx`).
13. **ServerConsole:** when `serverStatus="running"` and `tps=18.2` → badge shows `18.2`; when
    `serverStatus="stopped"` → badge shows `"—"` even if `useServerMetrics` returns tps=20.0;
    players badge hidden when not running.
14. **ServerDetailPage:** address widget shows tunnel address when exposure ACTIVE (playit);
    shows local when not; port widget renders `server.port` with copy; uptime renders formatted
    value when `runtime.uptime_seconds > 0`; TPS card shows `"—"` when stopped despite history.
15. **ServerMetricsCharts:** renders no-data state when all series tps are null; chart filters nulls.
16. **Full regression:** `vitest` frontend suite green.

---

## 6. Findings Ledger (this doc)

| ID | State | Detail |
|----|-------|--------|
| R-1..R-8 | confirmed | see §2 (RECON, previously reported). |
| D-1 | new | TPS nullability is a domain-edge change; clamps preserved for real values. |
| D-2 | new | `metric_points.tps` needs `nullable=True` migration. |
| D-3 | new | Prometheus must skip `update_tps(None)`. |
| D-4 | new | Metrics API + WS batch carry null with no schema change. |
| D-5 | new | Players stays `int`; only TPS nullable. |
| D-6 | new | Existing uptime test is too weak to catch mixed-clock bug. |
| D-7 | new | Uptime resets to 0 after stop via missing `start_time`; correct UX. |
| D-8 | new | `ServerMetricsCharts` must tolerate null TPS. |

---

## 7. Open Questions

- **OQ-1 (default: show TPS only while `running`).** Should TPS also display during `starting`
  (from a previous run's history)? Default = no — starting means no live RCON yet; history is
  stale/misleading (R-6).
- **OQ-2 (default: keep Address widget in the right column).** The request mentioned "console left
  side". The Address widget currently lives in the right overview column of the detail page; moving
  it into the console header would duplicate info and widen the diff. Default = keep location, just
  fix content. (If the user wants it inside the console header, it's a small follow-up.)
- **OQ-3 (default: no player-count nullability).** Make `players` nullable too for full symmetry?
  Default = defer: no observed complaint, wider migration, badge already status-gated (D-5).
- **OQ-4 (default: read-only, no tunnel re-provisioning).** When `desired_state === "ENABLED"` but
  status is `DEGRADED`/`ERROR`, show the last known `public_address`? Default = show only on ACTIVE;
  DEGRADED falls back to local — honest about the current reachability.

---

## 8. Implementation Checklist (for Build)

**Backend**
- [ ] `supervisor.py`: add `_ready_at_wall`; set on ready; rewrite `uptime`.
- [ ] `get_runtime_diagnostics.py`: start_time fallback for uptime.
- [ ] `collector.py`: nullable `ServerMetrics.tps` / `MetricCollectedEvent.tps`; `tps=None` defaults.
- [ ] `aggregate.py`: `MetricPoint(tps: float | None = None)` + gated validation.
- [ ] `models.py`: `tps` column nullable.
- [ ] New alembic migration (nullable tps).
- [ ] `metrics_collector.py`: guard `update_tps` when None.
- [ ] Tests: §5 items 1-10.

**Frontend**
- [ ] `utils/accessAddress.ts` (new) + tests.
- [ ] `Icon.tsx`: add `globe`, `clock`, `cpu`, `hard-drive`; update `Icon.test.tsx`.
- [ ] `ServerDetailPage.tsx`: address widget via helper; Port widget; icons on all overview widgets;
      uptime rendering; TPS/players gating + null-safe cards; pass `serverStatus` to console.
- [ ] `ServerConsole.tsx`: `serverStatus` gate for TPS/players.
- [ ] `ServerMetricsCharts.tsx`: null-TPS tolerance.
- [ ] `services/api.ts`: `MetricsSnapshot.tps: number | null`.
- [ ] Tests: §5 items 11-16.

**Docs/state**
- [ ] Sync `.ai/CURRENT_STATE.json` / `.ai/PROJECT_STATE.json` (SPEC-CONSOLE-OVERVIEW-001).
- [ ] Integrate with uncommitted SPEC-TPS-VALIDATION-001 worktree changes (shared `aggregate.py`/`rcon_client.py`).
