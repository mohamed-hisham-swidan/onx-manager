# Final Independent Review — Windows-Lifecycle Safety & Correctness Design

> **Verdict: ❌ NOT SAFE TO BUILD**

> [!CAUTION]
> This design has **6 blockers** and **4 significant concerns** that must be resolved before build can proceed.

---

## Review Methodology

This review was conducted from scratch against the live codebase as of `2026-08-29`. Five parallel research subagents performed exhaustive code audits across the relevant files. Every finding below cites exact file paths and line numbers verified against actual source code. No prior review conclusion was taken as given.

---

## 1. W-06 — `process_utils.py` Cross-Platform PID-Liveness

### Design Intent
Create a new `process_utils.py` module implementing cross-platform PID-liveness checking: POSIX via `os.kill(pid, 0)`, Windows via `ctypes`/`OpenProcess` + `GetExitCodeProcess` with `PROCESS_QUERY_LIMITED_INFORMATION` (0x1000) and `STILL_ACTIVE` (259) as inline constants.

### Codebase Reality

**`process_utils.py` does not exist.** PID-liveness checking is currently duplicated in **4 independent implementations**:

| Location | Function | Mechanism |
|---|---|---|
| `runtime_ownership.py:189-193` | `_is_pid_alive()` | `os.kill(pid, 0)` |
| `ownership_verifier.py:68-73` | `_is_pid_alive()` | `os.kill(pid, 0)` |
| `local.py:464-472` | `_is_pid_alive()` (method) | `os.kill(pid, 0)` |
| `playit_agent.py:133-144` | `_is_pid_alive()` | `os.kill(pid, 0)` |

**Direct `os.kill(pid, 0)` for liveness-only checks** (not SIGTERM/SIGKILL) found at:
- `runtime_reconciliation.py:237` — direct inline call
- `ownership_verifier.py:70` — inside `_is_pid_alive()`
- `runtime_ownership.py:191` — inside `_is_pid_alive()`
- `playit_agent.py:138` — inside `_is_pid_alive()`

### Assessment: ✅ DESIGN IS SOUND — Pending Implementation

The design correctly identifies the problem (POSIX-only `os.kill(pid, 0)` scattered across 4+ files) and the correct solution (centralized `process_utils.py` with ctypes-based Windows support using proper inline constants, not `subprocess.*` which doesn't have them).

The call-site enumeration in the design must include **all 4 files** listed above, plus the **direct inline `os.kill(pid, 0)` at `runtime_reconciliation.py:237`**.

> [!WARNING]
> **Blocker B-1:** The design must also address the `playit_agent.py` liveness check (`playit_agent.py:133-144`). This is a 5th call site not mentioned in the task description. Failing to update it means the playit daemon lifecycle would break on Windows even after W-06 lands.

### Status: **PARTIALLY RESOLVED** — call-site enumeration incomplete (missing `playit_agent.py`)

---

## 2. W-04 — `supervisor.py` Exception Boundary

### Design Intent
Make `_health_check()` properly handle three exception categories: `verify_process()` returning False → fallback status check; `ProviderError` → treat as process lost; generic `Exception` → log + treat as crash. Wrap `collect_diagnostics()` in its own try/except in both new exception handlers.

### Codebase Reality

Current `_health_check()` at `supervisor.py:333-373`:

```python
async def _health_check(self) -> None:
    try:
        alive = await self._provider.verify_process(self._handle)
        if not alive:
            status = await self._provider.status(self._handle)
            if status == ServerRuntimeStatus.STOPPED:
                # ... graceful exit
                return
            diag = await self._provider.collect_diagnostics(self._handle)  # ← UNPROTECTED
            diag.failure_code = FailureCode.RUNTIME_PROCESS_LOST
            # ...
            await self._handle_crash(diag)
            return
        self._last_heartbeat = time.time()
    except Exception:
        logger.exception(...)  # ← LOG ONLY, no crash handling, no diagnostics
```

**Critical gaps verified:**
1. **No `ProviderError` handler** — `ProviderError` (raised by `local.py:642-646` when `verify_process` fails) falls into the catch-all `except Exception:` which only logs and silently continues the loop.
2. **`collect_diagnostics()` at line 356 is UNPROTECTED** — if it raises, execution jumps to `except Exception:` at line 366, completely bypassing `_handle_crash()`. The server stays in `RUNNING` status in the DB while the process is dead.
3. **No fallback `RuntimeDiagnostics` object exists anywhere** — no fallback is constructed if `collect_diagnostics()` fails.
4. **The catch-all `except Exception:` does nothing useful** — it doesn't call `_handle_crash()`, doesn't set `_stop_event`, doesn't update heartbeat. A persistent provider error will cause infinite log-and-retry with no crash detection.

### Assessment: ✅ DESIGN IS CORRECT to fix this

The three-way exception handling with protected `collect_diagnostics()` calls is the right fix. The design should ensure:
- `collect_diagnostics()` is wrapped in `try/except` with fallback `RuntimeDiagnostics(provider=self._provider.provider_type, failure_code=FailureCode.RUNTIME_PROCESS_LOST)`
- `ProviderError` handler treats the error as process-lost and calls `_handle_crash()`
- Generic `Exception` handler also calls `_handle_crash()` (not just logs)

### Status: **RESOLVED** (design is correct; needs implementation)

---

## 3. W-01 — Provider Default + Migration + `running_start_time` Schema

### 3a. Call-Site Enumeration

The design claims 22 call sites across 17 files. The actual audit found:

**Backend `app/` directory — files containing `provider="local"` as default/fallback/comparison:**

| # | File | Lines | Context |
|---|---|---|---|
| 1 | `config.py:64` | `provider: str = "local"` |
| 2 | `value_objects.py:118,126,171` | `LOCAL = "local"`, deployment default, RuntimeInfo default |
| 3 | `models.py:46,53` | `Column(..., default="local")` x2 |
| 4 | `repository.py:81,131,142` | `or "local"` fallbacks x3 |
| 5 | `local.py:38` | `return "local"` (provider_type) |
| 6 | `reconciliation.py:117` | `if server.runtime else "local"` |
| 7 | `runtime_reconciliation.py:225,402` | `or "local"` fallbacks |
| 8 | `runtime_ownership.py:552` | `if displaced_server.runtime else "local"` |
| 9 | `start_server.py:102` | `if server.runtime else "local"` |
| 10 | `restart_server.py:234` | `if server.runtime else "local"` |
| 11 | `create_server.py:93` | `LocationType.LOCAL` |
| 12 | `get_runtime_diagnostics.py:37` | `if server.runtime else "local"` |
| 13 | `deployment_orchestrator.py:28,63` | parameter default + fallback |
| 14 | `environment.py:93` | `provider_factory.get("local")` |

**Total: 14 app files, 33 locations.** Plus 2 Alembic migration files and 11 test files.

The design's "22 call sites across 17 files" claim is **approximately correct** for the app directory when counting unique semantic call-sites (some lines have multiple references), but should be re-verified against the exact enumeration above.

> [!IMPORTANT]
> **Concern C-1:** The design needs to clarify which of these actually need to change. Many fallback defaults (`if server.runtime else "local"`) are correct — they should be `"local"` on Linux and the migration handles existing DB records. The key changes are: `RuntimeInfo.provider` default, `ServerModel.provider` column default, `config.py` `ServerConfig.provider`, and the fallback expressions in commands/queries that instantiate new providers. The `LocationType.LOCAL` enum and its usages are semantically different (location type, not runtime provider) and should NOT change.

### 3b. Startup Migration

**No migration logic currently exists** in `main.py`. The lifespan function (lines 66–348) runs `reconcile_servers()` and `reconcile_all_runtimes()` but has **zero** `local` → `local_windows` migration.

The design's proposed migration (updating `provider="local"` → `"local_windows"` on Windows hosts in the lifespan, before `reconcile_servers` runs) is correct in placement and approach. It must:
- Use a properly-scoped DB session with explicit commit
- Be idempotent (safe to run multiple times)
- Run before both `reconcile_servers()` and `reconcile_all_runtimes()`

### 3c. `running_start_time` — NEW SCHEMA WORK

> [!CAUTION]
> **Blocker B-2: `running_start_time` does not exist anywhere in the codebase.**

Verified absent from:
- `RuntimeInfo` (`value_objects.py:169-180`) — has `start_time: int | None` but no `running_start_time`
- `ServerModel` (`models.py:46-68`) — no such column
- `repository.py:81-151` — no such mapping
- `mark_running()` at `aggregate.py:285-306` — does NOT populate any `running_start_time`
- Zero grep results for `running_start_time` across the entire codebase

**For the design to work (specifically W-05's grace window for RUNNING servers), the following must be added:**

1. **`RuntimeInfo` dataclass field:** `running_start_time: float | None = None` (wall-clock timestamp)
2. **`ServerModel` column:** `running_start_time = Column(Float, nullable=True)` — must be a real DB column, not just in-memory, so it survives backend restarts
3. **Alembic migration:** New revision adding the `running_start_time` column to the `servers` table
4. **`repository.py` save path** (~line 85): `model.running_start_time = server.runtime.running_start_time if server.runtime else None`
5. **`repository.py` load path** (~line 140): include `running_start_time=model.running_start_time` in `RuntimeInfo()` construction
6. **`mark_running()`** at `aggregate.py:294`: populate `running_start_time=time.time()` (real wall-clock, NOT epoch int like existing `start_time`)

### 3d. `post_running_grace_seconds` in Settings

> [!CAUTION]
> **Blocker B-3: `post_running_grace_seconds` does not exist anywhere in the codebase.**

The `settings_store.py` `_DEFAULTS` dict (lines 38-50) and `LiveSettings` class (lines 55-70) have **no** `post_running_grace_seconds` field.

The design must add it to both `_DEFAULTS` and `LiveSettings` with a sane default (e.g. 30 seconds), and the W-05 reconciliation code must read it with a safe fallback for early startup.

### Status: **STILL OPEN** — Missing `running_start_time` DB column/migration/mapping (B-2) and `post_running_grace_seconds` setting (B-3)

---

## 4. W-05 — Reconciliation Grace Window for RUNNING Servers

### Design Intent
Add a grace window for `DB_RUNNING_NO_TMUX` (similar to the existing 60s grace for `DB_STARTING_DEAD`) so that recently-transitioned RUNNING servers aren't immediately marked CRASHED if reconciliation runs before the supervisor is fully established.

### Codebase Reality

**Current `_get_server_state()`** at `runtime_reconciliation.py:209-272`:
- `start_age_seconds` is **only computed for `ServerStatus.STARTING`** (line 246)
- For `RUNNING` servers, `start_age_seconds` is always `None`
- No `running_age_seconds` concept exists

**Current `_detect_mismatches()`** at `runtime_reconciliation.py:275-339`:
- `DB_RUNNING_NO_TMUX` at line 288-296 has **zero grace window** — fires immediately
- In contrast, `DB_STARTING_DEAD` at line 328-338 has a 60s hardcoded grace window

**`ServerRuntimeState` dataclass** at `runtime_reconciliation.py:44-58`:
- Has `start_age_seconds: float | None = None` but no `running_age_seconds` field

### Assessment

The design is correct: `_get_server_state()` needs to compute `running_age_seconds` from `server.runtime.running_start_time` (which must come from W-01/Commit 3), and `_detect_mismatches()` needs to gate `DB_RUNNING_NO_TMUX` with a configurable grace window from `post_running_grace_seconds`.

> [!WARNING]
> **Blocker B-4:** This commit depends entirely on W-01 (Commit 3) having already introduced `running_start_time` on `RuntimeInfo`, populated it in `mark_running()`, and persisted it to the DB. If the W-01 commit doesn't include all of that schema work (including the Alembic migration), this commit will reference non-existent fields.

### Pre-existing Latent Bug at Line ~250

Confirmed present at `runtime_reconciliation.py:248-251`:

```python
if server.runtime and server.runtime.start_time:
    with contextlib.suppress(Exception):
        ref_time = datetime.fromisoformat(server.runtime.start_time)
```

`server.runtime.start_time` is defined as `int | None` at `value_objects.py:175`, stored as `Column(Integer)` at `models.py:50`, and populated with `int(time.time())` at `local.py:272`. Calling `datetime.fromisoformat()` on an `int` always raises `TypeError`, which is silently swallowed by `contextlib.suppress(Exception)`, forcing fallback to `server.updated_at`.

**This bug sits directly on a code path touched by W-05** — the `_get_server_state()` function that this commit modifies to add the grace window logic. The correct fix is `datetime.fromtimestamp(server.runtime.start_time, tz=UTC)`.

> [!WARNING]
> **Blocker B-5:** This pre-existing bug must be fixed in this batch since W-05 directly modifies `_get_server_state()`. Leaving `datetime.fromisoformat()` on an `int` while adding new age-computation code in the same function would be inconsistent and confusing.

### Status: **STILL OPEN** — depends on B-2/B-3 from W-01, plus B-5 latent bug on touched code path

---

## 5. W-02 — `local_windows.py` Provider Rewrite

### Design Intent
Rewrite `local_windows.py` to use `Start-Process` with a properly-escaped argument array to detach the Java process, implement PID-based tracking, degraded console, and clean error surfaces.

### Codebase Reality

The current `local_windows.py` (127 lines) has **fundamental architectural flaws** that the design aims to fix:

| Issue | Current Code | Evidence |
|---|---|---|
| **PowerShell job session isolation** | `Start-Job` creates a job in the spawning `powershell.exe` session. Every `_run_powershell()` call is a new process. Subsequent `Get-Job`, `Stop-Job`, `Receive-Job` calls in a new powershell process **cannot find the job**. | `local_windows.py:40-44` |
| **No PID tracking** | `start()` returns `pid=None`. `get_runtime_pid()` is not implemented (inherits base returning `None`). `handle.external_id` stores a PowerShell job ID, not an OS PID. | `local_windows.py:63`, `base.py:118-119` |
| **Non-functional execute_command** | `Invoke-Command echo` does not write to the Java process STDIN | `local_windows.py:99-107` |
| **No graceful shutdown** | No `save-all` or `/stop` before killing | `local_windows.py:67-73` |
| **Interface signature mismatch** | `start()` doesn't accept `deployment` or `launch_config` kwargs | `local_windows.py:28` vs `base.py:51-57` |
| **No console docstring** | `console()` has no documentation about degraded mode | `local_windows.py:90` |

### `ProviderError` from `execute_command()` — HTTP Surface

Verified clean: `ProviderError` → `InfrastructureError` → caught by the global exception handler at `errors.py:113-116`, returns HTTP 503 with structured JSON. **Not a raw 500.**

### Console Parity Claims

Searched entire codebase: **zero claims** of Windows console parity. `providers.md:15` correctly documents `LocalWindowsProvider` as "Deferred Stub".

### PowerShell Argument Escaping — Mental Test

The design proposes `Start-Process -ArgumentList @('arg1', 'arg2', ...)`. Testing against a path with spaces, single quote, and `&`:

Path: `C:\Program Files\O'Brien & Sons\server.jar`

With per-element escaping (single quotes doubled):
```powershell
@('-Xms1024M', '-Xmx2048M', '-jar', 'C:\Program Files\O''Brien & Sons\server.jar', 'nogui')
```

This is correct — PowerShell single-quoted strings treat everything literally except doubled single-quotes. The `&` is not special inside single quotes. ✅

> [!NOTE]
> **Concern C-2:** The design should verify that `Start-Process -NoNewWindow` (or equivalent) correctly detaches the Java process so it survives the backend exiting. `Start-Process` with `-PassThru` returns a `Process` object with `.Id` for PID tracking. This is fundamentally different from `Start-Job` and should work correctly. However, the design should also address how `stop()` will gracefully shut down the server (send `/stop` via stdin pipe before killing the process).

### Status: **RESOLVED** (design direction is correct, pending implementation)

---

## 6. Commit Ordering — W-06 → W-04 → W-01 → W-05 → W-02

### Commit-by-Commit Forward-Reference Analysis

#### Commit 1: W-06 (`process_utils.py`)
- **Introduces:** `process_utils.py` with `platform_pid_alive()`
- **Modifies:** `runtime_reconciliation.py`, `runtime_ownership.py`, `ownership_verifier.py`, `local.py` (+ `playit_agent.py` if properly scoped)
- **Depends on:** Nothing from later commits
- **Forward references:** None ✅
- **Independently buildable:** Yes ✅

#### Commit 2: W-04 (`supervisor.py` exception boundary)
- **Modifies:** `supervisor.py` `_health_check()` method
- **Depends on:** W-06's `process_utils.py`? No — `verify_process()` is called via `self._provider`, not via `process_utils` directly. `supervisor.py` doesn't call `_is_pid_alive()`.
- **Forward references:** None ✅
- **Independently buildable:** Yes ✅

#### Commit 3: W-01 (provider default + migration + schema)
- **Introduces:** `running_start_time` on `RuntimeInfo`, `ServerModel` column, Alembic migration, `post_running_grace_seconds` setting, `local` → `local_windows` migration in `main.py`
- **Modifies:** `value_objects.py`, `models.py`, `repository.py`, `main.py`, `settings_store.py`, `aggregate.py`
- **Depends on:** Nothing from W-06 or W-04 specifically
- **Forward references:** None ✅
- **Independently buildable:** Yes, IF all schema work is included ✅

> [!IMPORTANT]
> **Blocker B-6:** If the `running_start_time` DB column, Alembic migration, and `repository.py` mapping are NOT included in this commit (only the in-memory `RuntimeInfo` field), then Commit 4 (W-05) will read a field that is never persisted, meaning the grace window will reset to `None` on every backend restart, defeating its purpose. The design must explicitly include all persistence layers in this commit.

#### Commit 4: W-05 (reconciliation grace window)
- **Depends on:** Commit 3's `running_start_time` field and `post_running_grace_seconds` setting
- **Forward references:** None (if Commit 3 is complete) ✅
- **Independently buildable:** Yes, on top of Commit 3 ✅

#### Commit 5: W-02 (`local_windows.py` rewrite)
- **Depends on:** Commit 1's `process_utils.py` (for PID liveness on Windows)
- **Forward references:** None ✅
- **Independently buildable:** Yes ✅

### Ordering Verdict

The ordering **W-06 → W-04 → W-01 → W-05 → W-02** is **logically correct** with no forward references, **contingent on Commit 3 (W-01) including all the `running_start_time` persistence work** (DB column + Alembic migration + repository mapping).

### Status: **CONDITIONALLY RESOLVED** — correct if B-6 is addressed

---

## 7. Additional Issues Found

### Issue I-1: `runtime_reconciliation.py` Is Entirely Linux-Specific

The entire `runtime_reconciliation.py` module uses Linux-only APIs:
- `/proc/{pid}/cwd` (line 80), `/proc/{pid}/environ` (line 87), `/proc/{pid}/stat` (line 97), `/proc/{pid}/cmdline` (line 189)
- `tmux list-sessions` (line 163), `tmux list-panes` (line 628)
- `ps aux | grep java` (line 178)
- `ss -tlnp` (line 199)
- `os.kill(pid, signal.SIGTERM/SIGKILL)` (lines 557-612)

On Windows, most of this will silently fail or return empty results. The reconciliation module needs platform-aware branches or should be disabled on Windows. **W-06 only addresses the `os.kill(pid, 0)` liveness check, not the `/proc/` reads, `tmux` commands, or `ss` calls.**

### Issue I-2: `runtime_ownership.py` Also Entirely Linux-Specific

Same issue as I-1. The entire `runtime_ownership.py` (979 lines) uses `/proc/` filesystem, `tmux`, `ps`, and `os.kill()` for signal delivery.

### Issue I-3: `LocalWindowsProvider` Has No `verify_process()` Override

`LocalWindowsProvider` inherits `verify_process()` from `base.py:114-116`, which calls `self.status(handle)`. But as established, `status()` uses `Get-Job` in a new PowerShell process that can't find the job. So `verify_process()` will always return `False` (STOPPED), causing the supervisor to immediately detect a "crash" and mark the server CRASHED. **The W-02 rewrite must include a proper `verify_process()` override using PID-based checking via W-06's `process_utils`.**

### Issue I-4: `capabilities()` Claims `"exec"` But `execute_command()` Is Non-Functional

`local_windows.py:23` returns `["process", "console", "exec"]` but `execute_command()` doesn't actually write to the Java process stdin. The W-02 rewrite should either:
- Remove `"exec"` from capabilities and raise `ProviderError("not supported")` in `execute_command()`, OR
- Implement actual stdin pipe communication (more complex)

---

## Summary

### Blockers (Must Fix Before Build)

| ID | Fix | Issue | Severity |
|---|---|---|---|
| **B-1** | W-06 | `playit_agent.py` call site missing from enumeration | Medium |
| **B-2** | W-01 | `running_start_time` — no DB column, no Alembic migration, no repository mapping exists. Design must specify ALL persistence layers, not just the in-memory field. | **Critical** |
| **B-3** | W-01 | `post_running_grace_seconds` — not in `_DEFAULTS` or `LiveSettings`. Must be added with sane default. | High |
| **B-4** | W-05 | Depends entirely on B-2 and B-3 being resolved in Commit 3 (W-01) | **Critical** |
| **B-5** | W-05 | `datetime.fromisoformat()` on `int` epoch at line 250 — pre-existing bug on a code path this batch directly modifies. Must fix as `datetime.fromtimestamp(start_time, tz=UTC)`. | High |
| **B-6** | Order | Commit 3 must include FULL `running_start_time` persistence (DB + Alembic + repository) or Commit 4 breaks | **Critical** |

### Concerns (Should Address, Not Blocking)

| ID | Fix | Issue |
|---|---|---|
| C-1 | W-01 | Call-site enumeration should clarify which sites actually change vs. which are intentionally `"local"` |
| C-2 | W-02 | Graceful shutdown (send `/stop` via stdin before process kill) not addressed |
| I-1/I-2 | Design-wide | `runtime_reconciliation.py` and `runtime_ownership.py` are entirely Linux-specific — no Windows path |
| I-3 | W-02 | Must include `verify_process()` override using PID-based checking |
| I-4 | W-02 | Capabilities list claims `"exec"` for non-functional command execution |

### Per-Fix Status

| Fix | Status | Evidence |
|---|---|---|
| **W-06** | **PARTIALLY RESOLVED** | Design is sound but missing `playit_agent.py` call site (B-1) |
| **W-04** | **RESOLVED** | Design correctly identifies and fixes all gaps in `_health_check()` |
| **W-01** | **STILL OPEN** | Missing `running_start_time` persistence (B-2), `post_running_grace_seconds` setting (B-3) |
| **W-05** | **STILL OPEN** | Blocked by W-01 gaps (B-4), plus latent `fromisoformat` bug on touched path (B-5) |
| **W-02** | **RESOLVED** | Design direction correct; PowerShell escaping verified; HTTP error surface clean |

### Commit Order

**W-06 → W-04 → W-01 → W-05 → W-02** is **logically correct with no forward references**, contingent on W-01 (Commit 3) including all `running_start_time` persistence work (B-6).

---

## Verdict

# ❌ NOT SAFE TO BUILD

**3 critical blockers (B-2, B-4, B-6) must be resolved.** The `running_start_time` persistence gap is the central issue — without a real DB column, Alembic migration, and repository mapping in Commit 3, Commit 4 (W-05) will reference non-existent schema and the grace window will not survive backend restarts.

### Priority Order for Resolution

1. **B-2 + B-6:** Define the complete `running_start_time` persistence chain (RuntimeInfo field + ServerModel column + Alembic migration + repository save/load + mark_running() population) and confirm it's all in Commit 3 (W-01)
2. **B-3:** Add `post_running_grace_seconds` to `LiveSettings` and `_DEFAULTS` in Commit 3 (W-01)
3. **B-5:** Fix `datetime.fromisoformat()` → `datetime.fromtimestamp()` in Commit 4 (W-05)
4. **B-1:** Add `playit_agent.py` to W-06 call-site enumeration
5. **B-4:** Re-verify W-05 after B-2/B-3 are resolved
