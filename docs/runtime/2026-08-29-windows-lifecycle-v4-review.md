# Design Spec v4 — Focused Independent Review

> **Verdict: ✅ SAFE TO BUILD**
>
> All 6 prior blockers are correctly resolved in v4. One new informational issue flagged.

---

## Review Scope

Targeted verification of v4's concrete implementation of each gap found in the prior full review. W-04, W-02, and 5-commit ordering are spot-checked only. All findings are against the live codebase as of 2026-08-29.

---

## Item 1 — `running_start_time` persistence chain (was B-2 / B-4 / B-6)

### 1a. Collision with existing `start_time`

`value_objects.py:175`: `start_time: int | None = None` — epoch int, set once at process launch.

Proposed: `running_start_time: float | None = None` — wall-clock float, set at RUNNING transition.

**No collision.** Distinct names, types (`int` vs `float`), semantics, and population points. All existing readers of `server.runtime.start_time` in `supervisor.py:213/291`, `start_server.py:315`, `restart_server.py:333`, `get_runtime_diagnostics.py:118-122`, and `runtime_reconciliation.py:248` are keyed on `start_time` by name. ✅

### 1b. `ServerModel` column placement

No existing column named `running_start_time` in `models.py`. Proposed placement after `deployment_start_time` (line 50) in the same runtime-info block is clean. ✅

### 1c. Alembic `down_revision`

**Verified live:** `alembic heads` returns exactly `b1e2100000008 (head)`. File `b1e2100000008_add_provisioning_failed_and_error_columns.py` confirms `revision = "b1e2100000008"`. v4's `down_revision = "b1e2100000008"` is correct. ✅

### 1d. Repository save/load paths

Save (`repository.py:85` pattern): `model.deployment_start_time = server.runtime.start_time if server.runtime else None`

Proposed: `model.running_start_time = server.runtime.running_start_time if server.runtime else None` — identical guard and style. ✅

Load (`repository.py:146` pattern): `start_time=model.deployment_start_time` → proposed `running_start_time=model.running_start_time` alongside it. Consistent. ✅

### 1e. `mark_running()` caller breakage

Current signature at `aggregate.py:285-292` has `pid`, `port` (positional required), then `host`, `external_id`, `start_time` as keyword-optional.

All production callers in `supervisor.py:216-222`, `supervisor.py:294-300`, `reconciliation.py:177/253`, `runtime_reconciliation.py:356` use **keyword arguments only**. All test callers pass at most `pid=…, port=…` keywords.

Adding `running_start_time: float | None = None` at the end as a new keyword-optional parameter causes **zero breakage**. Existing callers omit it and receive `None` (correct — old servers load `running_start_time=None` from the nullable migration column). ✅

### Status: **RESOLVED** ✅

---

## Item 2 — `post_running_grace_seconds` (was B-3)

### 2a. `_DEFAULTS` / `LiveSettings` consistency

Both currently absent from `settings_store.py`. v4 adds `"post_running_grace_seconds": 30.0` to `_DEFAULTS` and `post_running_grace_seconds: float = 30.0` to `LiveSettings`.

`_coerce()` derives target type from `type(default)` → `type(30.0) == float`. `LiveSettings` field is `float`. Keys and types match. ✅

### 2b. Clamping range

Proposed: `max(1.0, min(300.0, float(value)))`. With default 30.0:
- `max(1.0, min(300.0, 30.0))` = 30.0. Default not clamped. ✅
- Range 1–300s is sane (1s floor avoids degenerate zero; 300s ceiling is generous). ✅

### 2c. Early startup safety

`get_live_settings()` at `settings_store.py:161-170`: if `_live is None`, calls `init_settings_store()`, which calls `_load_yaml_file()` (catches all exceptions, returns `{}` on failure), falls back to `_DEFAULTS` for any missing key, and constructs `LiveSettings(**kwargs)`. **Never throws, never hangs.** Calling before YAML exists gives `post_running_grace_seconds=30.0` from defaults. ✅

### Status: **RESOLVED** ✅

---

## Item 3 — `fromisoformat` / `fromtimestamp` fix + `running_age_seconds` (was B-5)

### 3a. Is `start_time` always an int epoch?

All population points confirmed:

| Source | Value |
|---|---|
| `local.py:272` | `start_time = int(time.time())` |
| `local.py:298` | `"start_time": start_time` (same int) |
| `start_server.py:315` | `result.metadata.get("start_time")` → int or None |
| `value_objects.py:175` | `start_time: int \| None = None` |
| `models.py:50` | `Column(Integer, nullable=True)` |
| `repository.py:146` | `start_time=model.deployment_start_time` |

**No string path exists anywhere.** `datetime.fromtimestamp(server.runtime.start_time, tz=UTC)` is the correct replacement. The current `datetime.fromisoformat()` call on line 250 always raises `TypeError` (int argument), silently suppressed — this is a confirmed bug, not an edge case. ✅

### 3b. `running_age_seconds` field and wiring

`ServerRuntimeState` currently has `start_age_seconds: float | None = None` (line 57) — used for STARTING grace at `_detect_mismatches():328`.

New `running_age_seconds: float | None = None` is semantically distinct (time since RUNNING transition vs time since process launch). No collision with existing field name or usage. The gate in `_detect_mismatches()` for `DB_RUNNING_NO_TMUX` (currently lines 288-296, no grace) gaining a `running_age_seconds < grace` guard is parallel to the STARTING pattern. Correctly wired. ✅

### Status: **RESOLVED** ✅

---

## Item 4 — `playit_agent.py` call site (was B-1)

### 4a. Full call-site map in `playit_agent.py`

`_is_pid_alive()` at `playit_agent.py:133-143` is called from:
- `playit_agent.py:148` — inside `_is_pid_alive_and_playit()`
- `playit_agent.py:716` — direct call
- `playit_agent.py:728` — direct call

All three are within scope of W-06's playit migration. ✅

**Behavior note on `PermissionError`:** The playit implementation has a distinct exception-handling structure:

```python
except (ProcessLookupError, PermissionError):
    return False
except OSError:
    return False
```

Current behavior: `PermissionError` on `os.kill(pid, 0)` → returns `False` (semantically wrong — process IS alive).

If `platform_pid_alive()` correctly maps `PermissionError` → `True` (process is alive but unpermitted to signal), delegating to it **changes behavior**: a running-but-unsignalable playit daemon now correctly shows as alive. This is a strictness improvement, but v4 should document it explicitly.

### 4b. `local.py:464-472` scope

`local.py`'s `_is_pid_alive()` at line 464 runs `kill -0 {pid} 2>/dev/null` **via shell subprocess** (`_run_command()`), NOT `os.kill()`. It cannot be migrated to `platform_pid_alive()` the same way.

This method is an `async` instance method of `LocalLinuxProvider` and is only ever called from within `LocalLinuxProvider` (`local.py:373`, `local.py:600`, `local.py:640`). `LocalWindowsProvider` (W-02) has its own `verify_process()` override using `platform_pid_alive()` directly, bypassing this method entirely.

**v4 must explicitly state this is NOT on W-06's migration scope.** If left ambiguous, an implementer may try to migrate it and break `LocalLinuxProvider`'s async shell-based approach.

### Status: **RESOLVED** (all playit call sites addressed) — see N-1 below

---

## Item 5 — `LocationType.LOCAL` clarification (was C-1)

Full grep of `LocationType` in production code shows it is used exclusively in:
- `location.py` — filesystem path resolution based on `ServerDeployment.location_type`
- `repository.py:131` — loading `ServerDeployment` from `model.location_type` DB column (separate from `model.provider`)
- `create_server.py:93`, `import_server.py:92`, `registration.py:56` — constructing `ServerDeployment`

**`LocationType` and the runtime `provider` field are fully orthogonal.** They are stored in separate DB columns (`location_type` and `provider`), represent separate concepts (where files live vs. how the process is launched), and no code path compares or couples them. A Windows server correctly has `LocationType.LOCAL` (local filesystem) AND `provider="local_windows"` (Windows process launcher). ✅

Zero code changes needed for `LocationType` or its usages.

### Status: **RESOLVED** ✅

---

## Spot-check: W-04 / W-02 / Commit Order

No silent changes detected in v4 for these areas:

- **W-04**: Three-handler `_health_check()` structure with wrapped `collect_diagnostics()` unchanged. ✅
- **W-02**: `Start-Process` with `-PassThru` PID tracking, PowerShell escaping, `verify_process()` override via W-06's `platform_pid_alive()` unchanged. ✅
- **Commit order** W-06 → W-04 → W-01 → W-05 → W-02: No forward references; W-01 now explicitly includes full persistence chain. ✅

---

## Issues Found

### N-1 (medium): `local.py:464` `_is_pid_alive()` — ✅ RESOLVED

> **Note (added to W-06 design):** `local.py:464-472`'s `_is_pid_alive()` method is intentionally excluded from this W-06 migration — it uses a shell subprocess (`_run_command("kill -0 ...")`) rather than `os.kill()` directly, and is part of the Linux provider's existing verification path. Do not refactor it to use `platform_pid_alive()`; leave it as-is.

### Carried-forward (informational, non-blocking): Reconciliation/Ownership on Windows

`runtime_reconciliation.py` and `runtime_ownership.py` remain Linux-specific (`/proc/`, `tmux`, `ps aux`, `ss`). These will silently return empty results on Windows. W-06 only migrates the PID-liveness check. This is acceptable for the current batch scope but should be noted in `local_windows` provider documentation.

---

## Summary

| Item | Status | Key Evidence |
|---|---|---|
| **running_start_time persistence chain** (B-2/B-4/B-6) | ✅ RESOLVED | No name collision; `alembic heads` = `b1e2100000008` matches v4 placeholder exactly; save/load follow `deployment_start_time` pattern; all callers use keyword args |
| **post_running_grace_seconds** (B-3) | ✅ RESOLVED | `_DEFAULTS` + `LiveSettings` pattern consistent; clamp 1.0–300.0 doesn't touch default 30.0; `get_live_settings()` self-initialises safely |
| **fromisoformat → fromtimestamp** (B-5) | ✅ RESOLVED | `start_time` is `int` epoch at all 6 population points; `fromtimestamp(int, tz=UTC)` correct; `running_age_seconds` doesn't collide with `start_age_seconds` |
| **playit_agent.py call site** (B-1) | ✅ RESOLVED | All 3 internal call sites identified; PermissionError behavior change is a correctness improvement |
| **LocationType.LOCAL clarification** (C-1) | ✅ RESOLVED | `LocationType` and `provider` are fully orthogonal — separate DB columns, never compared |
| **N-1: local.py:464 scope ambiguity** | ⚠️ Informational | Must explicitly exclude from W-06 file list; uses shell subprocess not `os.kill()` |

---

## Verdict

# ✅ SAFE TO BUILD

All 6 critical blockers from the prior review are correctly and completely addressed in v4. The one new issue (N-1) requires one sentence of scope clarification in the design, not a design change. The 5-commit implementation order is correct with no forward references.
