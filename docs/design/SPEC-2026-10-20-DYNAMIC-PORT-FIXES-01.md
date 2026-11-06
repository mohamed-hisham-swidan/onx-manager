# DESIGN SPEC - Dynamic Backend Port Fixes (Launcher)

| Field | Value |
|---|---|
| Lane | B (Release Improvement) |
| Decision Level | D1 (launcher startup/stop contract; runtime state semantics) |
| Status | PROPOSED (design review of v2 applied; v5 reconciles B2/B3/B4/B8 as implemented; pending independent design review of v5.3) |
| Implementation state | B1-B9 built and contained in origin/master (verified 2026-10-29): B1+B5a+B5b `e7e1707`, B2 `98c3a10`, B2b `3eaa6ec`, B3 `8e27d9c`, B4 `c0a3ad2`, B6a `af50ae0`, B6b `349bb2a`, B7 `86e1328`, B8 `4f649dd`, B9 `d821301` |
| Date | 2026-10-21 |
| HEAD | `5b775e4` (original inspection baseline was origin/master `e67e59a`) |
| Spec ID | `SPEC-2026-10-20-DYNAMIC-PORT-FIXES-01` |
| Governance | `docs/governance/GOVERNANCE.md`; `.ai/RULES/core-principles.md`; `.ai/RULES/scope-and-implementation.md`; `.ai/RULES/testing-and-verification.md` |
| Related | `docs/design/SPEC-2026-10-20-DYNAMIC-BACKEND-PORT-01.md`; `docs/decisions/0019-dynamic-backend-port.md` |
| Mode | Design. This task creates only this file. No code, test, state, ADR, or preflight edits; no git writes. |
| Revision | v5.3 (2026-10-23) |

All line references below originate from the read-only inspection of origin/master `e67e59a`; v5 re-anchors the remaining F1/F4 references to HEAD `5b775e4` (B4 changed only scripts/preflight.py, scripts/preflight.sh, backend/tests/test_preflight.py, so launcher line anchors were unchanged by B4).

---

## Goal

Make the dynamic-port feature safe and correct under real failure conditions:

1. `--stop` must never signal a foreign, unverified, or unknown process, even when `.onx/backend.port` is stale or missing. After handling the active-port listener (never signalling a foreign or unresolved listener), `cmd_stop` independently gates and stops stored `backend.pid` if it is project-owned (`belongs_to_project`), even when the active-port occupant is foreign or unresolved (D-8). Process identity must be revalidated in memory (`psutil.Process.create_time` captured at classification and rechecked right before signaling both listener and supervisor, D-9); `.onx/backend.pid` format on disk remains unchanged. `PortManager.kill_on_port` must take `expected_pid` and `expected_create_time` across all callers (`cmd_stop`, `_handle_own_unhealthy`, F4 reconcile); and `backend.pid` must be cleared only if matching the stopped process (`_clear_backend_pid_if`).
2. Bind-race detection must be deterministic: write the attempt boundary marker FIRST, then capture log identity `(st_dev, st_ino, size)` AFTER the marker; the reader reads from that offset forward without scanning for attempt numbers. If `backend.log` shrinks or is rotated/replaced between attempts, reading resets to 0. External rotation during an attempt while `tee` holds its descriptor is an accepted residual risk.
3. Preferred-port resolution must actually follow `ONX_BACKEND_PORT` > `MCS_BACKEND_PORT` > `.onx/config.json` > `8000`, with warning and fall-through on invalid values in both launcher and preflight. The port range `1024..65535` applies strictly to the preferred port (retaining `1..65535` for active-port reading and bind checks); environment overrides must never be persisted into `.onx/config.json` by `ConfigManager.save()`. Updating `backend_port` via `ConfigManager.update` under an active env override updates `configured_backend_port` only, warns, and leaves the effective override intact.
4. Startup failure reconciliation must cover ALL exit paths (`initial decision is None`, `ensure_python_environment() is None`, `pid is None`, `dead`+bindable, `timeout`, `next_decision is None`, `final exhaustion`, `KeyboardInterrupt` during the attempt/wait section, D-12, OWNER-CONFIRMED 2026-10-23). The launcher verifies port release after kills, reports untracked survivors, and aborts without escalating SIGKILL to surviving descendants (D-10). On Ctrl-C, the launcher reconciles the spawned wrapper PID and matching `backend.pid` metadata exactly like the timeout path, then re-raises `KeyboardInterrupt`. Retries apply ONLY to bind races (D-7/D-3); generic crashes and generic timeouts remain non-retryable. Provenance is determined by an explicit helper returning `VERIFIED` or `UNKNOWN`. Reuse metadata paths (`start_backend` and retry reuse) write a stored PID only if project-owned and consistent with the listener, otherwise writing the ownership-checked supervisor/listener PID.
5. Status and self-test must require both a real listener and a valid panel signature (`check_backend_health`), never reporting a live terminal wrapper with no listener as a running backend. `SelfTestResult` inspection must check `status` (not `ok`), and `SelfTester.run` must be isolated via a testable seam.
6. A non-interactive/EOF or `KeyboardInterrupt` condition in `ask_yes_no` must return `False` across all callers, turning EOF into refusal rather than destructive consent.
7. Regression tests must exercise real failure paths (real ephemeral listeners, real log truncation/rotation, SIGTERM-ignoring descendant fixtures under a wrapper, tmp_path isolation, listener attribution preconditions, `ConfigManager` singleton reset), not mock the behavior they claim to prove, with an explicit narrow exception allowing patching `PortManager.get_pid_by_port` ONLY for the two unresolved-ownership tests.

No new feature, dependency, event type, port-discovery mechanism, or production container behavior is introduced.

---

## Current Behavior (F1/F4/F5 verified at HEAD `5b775e4`; F2/F3/F6 are historical (pre-HEAD) analyses)

### F1 - `cmd_stop` kills a foreign listener named by stale active-port state or stored PID (confirmed)

`cmd_stop` reads `.onx/backend.port`, resolves the listener with `PortManager.get_pid_by_port(active_port)`, derives a supervisor with `_backend_supervisor_pid(...)`, and calls `PIDManager.kill_tree(supervisor)` (`launcher.py:3313-3337 (was 3178-3202)`, specifically `3318-3325 (was 3183-3190)`).

`_backend_supervisor_pid` starts with `best = pid` and only checks `PortManager.belongs_to_project(parent.pid)` while walking upwards (`launcher.py:3007-3029 (was 2873-2895)`, specifically `3021-3024 (was 2887-2890)`). The initial listener PID is never checked. For a foreign listener with a non-project parent, the function returns that foreign PID, and `cmd_stop` signals it.

Furthermore:
- The fallback path (`launcher.py:3326-3332 (was 3191-3197)`) reads `PIDManager.read("backend")` and signals it unconditionally with `PIDManager.kill_tree(pid)` without verifying `PortManager.belongs_to_project(pid)`. If `backend.pid` contains a stale foreign PID, it will be signalled.
- An unresolved listener on the active port (where `get_pid_by_port` returns `None` but the port is open) falls through to the unguarded `backend.pid` fallback.
- `PortManager.kill_on_port` (`launcher.py:1115-1126 (was 1045-1056)`) re-resolves the listener PID freshly without taking or validating an expected PID, creating a blind-kill window if another process binds the port.
- Process identity is not revalidated immediately before signal emission (no check against `psutil.Process.create_time`), exposing the stop path to PID recycling races.

This violates ADR-0019 decision 6: foreign and unknown listeners are never signalled.

### F2 - bind-race log detection is defeated by log truncation and identity changes (RESOLVED: implemented in d357599)

*Historical (pre-B4 / pre-HEAD) analysis at e67e59a; implemented, see commit.*

`TerminalOpener._wrap_command` redirects through `tee` without `-a` (`launcher.py:1267-1271 (was 1197-1201)`), so `tee` truncates `.onx/logs/backend.log` when the terminal starts.

`start_backend` captures the current size before spawning:
- `log_offset = BACKEND_LOG.stat().st_size ...` (`launcher.py:2957`)
- spawn occurs after that (`launcher.py:2958-2966`)

`_read_backend_log_from` then seeks directly to the captured offset (`launcher.py:2944-2970 (was 2830-2838)`). If the new file is shorter than the old offset, `seek(offset)` lands beyond EOF and the read returns empty. A real bind error such as `Address already in use` is therefore never seen, and `_wait_for_backend_attempt` reports `timeout` instead of `bind` (`launcher.py:2978-3004 (was 2846-2870)`). The 3-attempt bind retry never runs.

In addition, a size-only guard is vulnerable to log rotation: if `backend.log` is replaced or rotated with a new file that happens to be larger than `log_offset`, seeking to `log_offset` reads corrupted or mid-stream data from a different file inode. Furthermore, reading from an offset without per-attempt boundary markers risks matching stale `Address already in use` markers from prior runs or earlier attempts in the same session.

The background-process fallback already uses `O_APPEND` (`launcher.py:1422`), so the terminal path is the inconsistency.

### F3 - environment precedence is not implemented in `ConfigManager.load` (RESOLVED: implemented in cf827e8)

*Historical (pre-B4 / pre-HEAD) analysis at e67e59a; implemented, see commit.*

`ConfigManager.load` sets `backend_port` only from `.onx/config.json`, defaulting to `BACKEND_PORT` (`launcher.py:602-641 (was 563-582)`, specifically line 631 is constructor and line 632 assigns `backend_port`). It does not read `ONX_BACKEND_PORT` or `MCS_BACKEND_PORT`.

Those variables are passed only to the Vite child (`launcher.py:1311`). The old spec, ADR-0019, and preflight all state the precedence `ONX_BACKEND_PORT` > `MCS_BACKEND_PORT` > `.onx/config.json` > `8000` (`docs/design/SPEC-2026-10-20-DYNAMIC-BACKEND-PORT-01.md:107`, `docs/decisions/0019-dynamic-backend-port.md:53-54`, `scripts/preflight.sh:45-54`, `scripts/preflight.py:85-90`).

`.ai/STATE.json:159` currently claims this precedence is implemented. That claim was false at `e67e59a` and is true at `cf827e8`.

Crucially, the D-1 rationale in the v1 spec was flawed: **historical (pre-B4 / pre-HEAD)**, `scripts/preflight.py:85-90` (at `e67e59a`) evaluated `os.environ.get("ONX_BACKEND_PORT") or os.environ.get("MCS_BACKEND_PORT")`. When `ONX_BACKEND_PORT` is set to an invalid non-empty string, Python's `or` short-circuits on the truthy string; `_valid_port()` evaluates to `False`, and execution jumps directly to `_read_config_backend_port() or 8000`. It does NOT fall through to `MCS_BACKEND_PORT`. Bash (`scripts/preflight.sh:45-54`) resets an invalid port directly to `8000`. Neither script implements proper fall-through across all tiers.

Adjacent facts for the fix:
- `ConfigManager.save()` writes `cfg.backend_port` back to disk (`launcher.py:643-654 (was 584-595)`) and is called for `--code`/`--swagger` (branches ~3308-3312 and ~3314-3317). Loading an env override directly into `cfg.backend_port` without a persistence distinction leaks the override into `.onx/config.json`.
- `LauncherConfig` (`launcher.py:183-192`) lacks a `configured_backend_port` attribute; adding it without a default breaks callers using keyword instantiation like `LauncherConfig(auto_install_deps=False)`.
- `ConfigManager.update()` (`launcher.py:656-672 (was 597-603)`) mutates `LauncherConfig` attributes dynamically; under an active environment override, updating `backend_port` must update the persistent `configured_backend_port` only, log a warning, and leave the effective environment override intact.

### F4 - failure paths leak or fail to reconcile the spawned attempt (confirmed)

`start_backend` has seven exit and retry paths (`launcher.py:3046-3169`):
- `initial decision is None` (`launcher.py:3047-3058`): when `PortManager.resolve_startup_port` returns `None` (all ports in scan span occupied by foreign/unresolved listeners or project backend could not be stopped), the launcher shows an error and returns `False` without cleaning or reconciling stale metadata.
- `ensure_python_environment()` returns `None` (`launcher.py:3072-3083`): when no Python interpreter is found, the launcher shows an error and returns `False` without clearing stale metadata.
- `pid is None` (`launcher.py:3102-3105`): logs an error and clears the active-port file, but leaves any previous attempt's PID in `backend.pid`.
- `dead` and bindable (`launcher.py:3121-3130`, specifically `3123-3129`): logs a crash, invokes interactive `ErrorHandler.show` with a recursive callback `lambda: start_backend(cfg, python)`, and clears only the active-port file (`3129`). It leaves `backend.pid` pointing at a dead/stale process and introduces unbounded recursive re-entry.
- `timeout` (`launcher.py:3132-3138`): clears only the active-port file and returns failure. It does not terminate the spawned attempt and does not clear `backend.pid`.
- `next_decision is None` (`launcher.py:3154-3155`): breaks from the retry loop when candidate exhaustion occurs, landing at line 3167 without reconciling the failed attempt's PID or process.
- `final exhaustion` (`launcher.py:3140-3141`, `3167-3169`): breaks when `attempt >= MAX_PORT_ATTEMPTS`, clears only the active-port file, and leaves `backend.pid` untouched.
- retry after `bind` or `dead`+occupied (`launcher.py:3140-3165`): resolves the next candidate and spawns again without checking or reconciling the listener or attempt on the failed port.

Reuse metadata paths:
- In `start_backend` (`decision.reuse` at `launcher.py:3061-3066`) and retry reuse (`3156-3164`): lines 3064 and 3159 both compute `actual_pid = stored_pid if stored_pid and PIDManager.is_alive(stored_pid) else _backend_supervisor_pid(listener_pid)`. If `stored_pid` is alive, it is written to `.onx/backend.pid` unconditionally without verifying that `stored_pid` belongs to the project or is consistent with the listener on the reused port.

Process provenance and termination caveats:
- `TerminalOpener.open_backend` is defined at `launcher.py:1349` (`1349-1368`). Terminal launch returns `proc.pid` at line 1417, background fallback returns `proc.pid` at line 1441, and `_open` starts at line 1386 (`1386-1442`). The terminal preference list is at lines 1259-1264 and `_build_cmd` is at lines 1333-1338. For POSIX/Windows terminal emulators, it returns the terminal GUI wrapper PID (e.g., `konsole`, `xterm`). If the terminal emulator daemonizes or connects to an existing daemon (e.g., `gnome-terminal`), child attribution is runtime-dependent and UNKNOWN.
- `PIDManager.kill_tree` (`launcher.py:807-832`, specifically `815-830`) sends `SIGTERM` to descendants in reverse order and `SIGTERM` to the root PID. If the root PID survives after 1 second, it sends `SIGKILL` ONLY to the root PID (`826-830`). If a descendant (e.g., a uvicorn worker) ignores `SIGTERM`, it is not sent `SIGKILL` by `kill_tree` and survives as an untracked orphan adopted by init.
- `kill_tree` guarantees apply only to a proven project-owned root/supervisor and its descendants. After calling `kill_tree`, `start_backend` does not verify whether the port was actually freed via `can_bind` or `get_pid_by_port`, and does not report surviving untracked processes. Escalating `SIGKILL` to surviving descendants without proven project ownership is unsafe; survivors must be reported and startup aborted (D-10).

**F1/F4 live gaps (verified at HEAD `5b775e4`; facts the design must cover):**
1. `start_frontend` (`launcher.py:3186-3193`) calls `kill_on_port` without prompting when `get_pid_by_port` returns `None` — **GAP**: the existing F1/F4 design records frontend lifecycle as out of scope, so this case is not covered.
2. Timeout path (`launcher.py:3132-3138`) does not terminate the attempt or clear `backend.pid`.
3. `TerminalOpener.open_backend` returns the terminal wrapper PID, which is written to `backend.pid` (`launcher.py:3093`, `3106`) and later treated as the backend root (`launcher.py:3007-3029`).

### F5 - status and self-test report a live wrapper as a running backend (confirmed)

`StatusDisplay._collect_service` computes:
`running=alive or (port_open and panel_healthy)` (`launcher.py:2017-2034 (was 1947-1964)`, specifically `2030 (was 1960)`)

For `verify_backend=True`, `panel_healthy` requires a healthy panel signature, but the `alive` disjunct bypasses it. A live `backend.pid` wrapper with no listener therefore reports `running=True`.

`SelfTester.run` has the same shape:
`if be_alive or pa(effective_backend_port):` (`launcher.py:1829 (was 1759)`, `1928-1938 (was 1858-1868)`, specifically `1935 (was 1865)`)

The old spec's failure table already requires "live terminal wrapper with no listener -> clear PID/active metadata" (`docs/design/SPEC-2026-10-20-DYNAMIC-BACKEND-PORT-01.md:380`), but status/self-test still trust wrapper liveness.

### F6 - EOF is treated as `yes` for destructive confirmations (RESOLVED: implemented in f934a50)

*Historical (pre-B4 / pre-HEAD) analysis at e67e59a; implemented, see commit.*

`ask_yes_no` catches `EOFError` and `KeyboardInterrupt` and returns `default` (`launcher.py:464-476 (was 463-475)`, specifically `475-476 (was 474-475)`).

This impacts all three callers in `launcher.py`:
1. `ErrorHandler.show` retry prompt (`launcher.py:2172`): `if retry_cb is not None and ask_yes_no("Retry?", default=True):` -> non-interactive EOF triggers an unintended retry loop.
2. `_handle_own_unhealthy` (`launcher.py:3032-3043`, specifically `3037`): `if not ask_yes_no(f"Stop the project-owned process on port {port}?", default=True):` -> non-interactive EOF returns `True`, treating lack of input as consent to kill.
3. `start_frontend` port collision prompt (`launcher.py:3187`): `if pid and not ask_yes_no(f"Port {cfg.frontend_port} is in use by PID {pid} (unresponsive). Kill it?", default=True):` -> non-interactive EOF authorizes terminating the frontend port occupant.

### F7 - old spec test gaps and false-confidence tests (confirmed)

The old spec lists 25 tests (`docs/design/SPEC-2026-10-20-DYNAMIC-BACKEND-PORT-01.md:431-455`). In `backend/tests/test_launcher_dynamic_port.py`:

| Old spec test | Current status |
|---|---|
| #16 bind race retries next candidate | Not proven with a real log. `test_start_backend_retries_only_on_bind_failure` mocks `_wait_for_backend_attempt` to return `"bind"` (`backend/tests/test_launcher_dynamic_port.py:569-589`, specifically `582`), so it cannot catch F2. (F2 and F6 are now covered by real-log and EOF tests in d357599 and f934a50) |
| #17 retry uses short timeout | Missing. |
| #18 non-bind failure is not retried | Missing. |
| #21 active-port file written on success and cleared on stop | Only the helper lifecycle is tested (`:421-451`); no `start_backend`/`cmd_stop` caller test. |
| #23 frontend env includes backend port | Missing. `open_frontend` is not exercised. |
| #24 status uses active-port file when listener exists | Missing; only the stale-file case is tested (`:597-601`). |

Existing tests also overstate coverage:
- `test_live_wrapper_without_listener_does_not_fake_reuse` (`:310-331`) does not create a live wrapper or a real `backend.pid`; it mocks the classification primitives.
- `test_start_backend_timeout_is_not_retried` (`:591-607`) mocks `_wait_for_backend_attempt`, so it tests the branch, not timeout cleanup.
- `test_status_does_not_report_foreign_port_as_backend_running` (`:609-619`) mocks health/PID lookup and does not cover a live wrapper.

These tests may remain as branch tests, but they do not satisfy the evidence standard for F1/F4/F5. (F2 and F6 are now covered by real-log and EOF tests in d357599 and f934a50)

---

## Proposed Change

### F1 - ownership-gate the stop path and validate process identity

In `cmd_stop`, both the active-port listener branch and the stored `backend.pid` evaluation must be strictly ownership-gated per D-5, D-8, and D-9:

1. **Active-port listener branch:**
   - Read `active_port = PIDManager.read_active_port()`.
   - If `active_port` is present:
     - Resolve `listener_pid = PortManager.get_pid_by_port(active_port)`.
     - If `listener_pid` is present:
       - Check `PortManager.belongs_to_project(listener_pid)`:
         - **If TRUE:** Capture in-memory `psutil` create_time at classification time. Derive supervisor `_backend_supervisor_pid(listener_pid)` (verifying supervisor project ownership and capturing its create_time). Revalidate process identity right before signaling by comparing in-memory create_time. Signal that supervisor tree (`PIDManager.kill_tree`). Verify that the port is actually freed (`can_bind` / `get_pid_by_port`); if free, clear `.onx/backend.port`, and clear `backend.pid` ONLY if it matches the stopped process (`_clear_backend_pid_if`). If untracked descendants survive on the port, report them and abort without escalating SIGKILL (D-10).
         - **If FALSE (foreign listener):** Log a warning naming the PID and port; DO NOT signal `listener_pid` or any parent; clear the stale `.onx/backend.port` file. A foreign listener is never signalled.
         - **If UNRESOLVED (port open, PID is None):** Log a warning stating ownership cannot be established; DO NOT signal any process; clear the stale `.onx/backend.port` file.
     - If the active port is free (no listener): clear the stale `.onx/backend.port` file.

2. **Stored `backend.pid` evaluation (D-8):**
   - After handling the active-port listener (whether stopped, free, foreign, or unresolved), `cmd_stop` independently gates and stops stored `backend.pid` if it is project-owned (`belongs_to_project`), even when the active-port occupant is foreign or unresolved:
     - Read `stored_pid = PIDManager.read("backend")`.
     - If `stored_pid` is alive:
       - **Ownership gate:** Verify `PortManager.belongs_to_project(stored_pid)`. If ownership is NOT proven (foreign or unresolved), log a warning and DO NOT signal it; never signal an unverified PID.
       - **Identity revalidation (D-9):** If project-owned, verify process identity (`create_time` captured in memory) right before calling `PIDManager.kill_tree(stored_pid)`.
       - Clear `backend.pid` ONLY if it matches the stopped process (`_clear_backend_pid_if`).
     - If `stored_pid` is dead: clean the stale file (`PIDManager.cleanup_stale()`).
   - Residual risk: `.onx/backend.pid` format on disk remains unchanged (decimal integer PID). PID reuse across different launcher launches is recorded as an accepted residual risk.

3. **Guarded `kill_on_port` with expected PID and create_time (D-9):**
   - Modify `PortManager.kill_on_port(port: int, expected_pid: int | None = None, expected_create_time: float | None = None) -> bool` (`launcher.py:1115 (was 1045)`):
     - If `expected_pid` is specified, resolve the current listener on `port`; if the listener PID does not match `expected_pid`, abort the kill and return `False`.
     - If `expected_create_time` is specified, verify `psutil.Process(expected_pid).create_time() == expected_create_time` right before signaling; if mismatched, abort and return `False`.
   - Every internal caller (`cmd_stop`, `_handle_own_unhealthy`, and F4 failure reconciliation) passes `expected_pid` and `expected_create_time`.
   - Scope boundaries and residual risks: `start_frontend`'s use of `kill_on_port(cfg.frontend_port)` (`launcher.py:3193 (was 3058)`) and `cmd_stop`'s frontend PID branch (`launcher.py:3326-3332 (was 3181-3197)`) do not pass expected PID/identity; refactoring the frontend lifecycle is out of scope and recorded as an explicit owner-visible residual risk. Acceptance criterion 1 is strictly scoped to the backend stop path.

**O-7 process-identity helper (DECIDED: option (b)).** `launcher.py` must duplicate a minimal identity helper instead of importing the backend package: `_capture_process_create_time(pid) -> float | None` and `_verify_process_identity(pid, expected_create_time) -> bool`, using `psutil.Process.create_time()` with a `0.5` s tolerance and refusing (returning `False`) on mismatch or when `create_time` cannot be read. The helper catches `ImportError` for `psutil` and treats "cannot read" as `capture=None` / `verify=False` (verified fact: `psutil` imports in `launcher.py` are inside functions and guarded at `launcher.py:778`, `946`, `1171`, `3015`). For non-`None` `expected_create_time`, semantics must match `_verify_process_identity` in `backend/app/core/process_utils.py:134`. When `expected_create_time is None`, the helper REFUSES (no proof, no kill; see O-8), an intentional divergence from `_verify_process_identity`. A drift test must run both implementations against a real child process and assert they agree for matching identity, mismatched `create_time`, and dead PID, excluding the `None` case, which is covered by a separate unit test of the launcher helper; tests use `tmp_path`/`monkeypatch` and never touch the real `.onx` directory. `launcher.py` already imports and uses `psutil` inside functions (see O-7 FACT), so no new dependency or fallback is introduced.

### F2 - preserve append semantics, track file identity, and isolate attempt markers

Two options were evaluated for `backend.log`.

**Option A (recommended): `tee -a`, deterministic attempt marker sequencing, and file identity tracking.**

- Change `_wrap_command` to `tee -a` (`launcher.py:1271 (was 1201)`).
- Deterministic sequencing:
  1. Before spawning attempt `attempt`, write the attempt boundary marker line FIRST to `BACKEND_LOG`:  
     `--- ONX LAUNCH ATTEMPT {attempt} ({ts}) [token:{token}] ---\n` (implemented at `launcher.py:2922-2934`; marker line at `2928`; the token comes from `_generate_attempt_token`, `launcher.py:2902-2905`)
  2. Immediately AFTER writing the boundary marker, capture `(st.st_dev, st.st_ino, st.st_size)` of `BACKEND_LOG` as `log_identity`.
  3. Spawn the backend process.
- Signature synchronization (both functions updated together):
  - Pre-fix signatures (old layout `launcher.py:2830-2851 (was at e67e59a)`):
    ```python
    def _read_backend_log_from(offset: int) -> str: ...
    def _wait_for_backend_attempt(port: int, pid: int, timeout: float, log_offset: int) -> str: ...
    ```
  - Implemented synchronized signatures (keyword-only `marker_token`):
    ```python
    def _read_backend_log_from(identity: tuple[int, int, int], *, marker_token: str) -> str: ...
    def _wait_for_backend_attempt(port: int, pid: int, timeout: float, log_identity: tuple[int, int, int], *, marker_token: str) -> str: ...
    ```
- Reading behavior:
  - In `_read_backend_log_from(identity, *, marker_token)`: stat `BACKEND_LOG`.
  - If device or inode changed (`(st.st_dev, st.st_ino) != (saved_dev, saved_ino)`) or if file shrank (`st.st_size < saved_size`), reset the read offset to `0`.
  - On reset, read the whole file and locate the current attempt with `content.rfind(marker_token)` (`launcher.py:2958-2966`); parse only text after that token; return `""` if the token is absent.
  - Otherwise, seek to `saved_size` and read forward to EOF.
  - Because `saved_size` was captured strictly *after* the attempt marker (including its unique token) was written, reading from that offset forward inspects only output emitted by the current attempt; no scanning for attempt numbers or parsing past log markers is required on the normal path (the `rfind(marker_token)` lookup applies only on a reset).
- Rotation claim boundary and residual risk:
  - On POSIX, `tee` holds an open file descriptor to `backend.log`. External log rotation DURING an active attempt is explicitly out of scope and recorded as an accepted residual risk (the launcher will not recover mid-attempt live rotation).
  - The `(st_dev, st_ino, st_size)` identity guard deterministically detects log truncation, file rotation, or inode replacement that occurs BETWEEN attempts (e.g., manual truncation or logrotate firing between attempts), resetting the read offset to 0.
  - **Gap closed by F2b (design); not yet built.**
- Windows compatibility: On Windows `_wrap_command` returns the command unchanged (`launcher.py:1269-1270`); the read-side identity guard is harmless there and helps the fallback path.
- **Known cost recorded:** `.onx/logs/backend.log` grows unbounded across launches because `tee -a` appends continuously. Log rotation / size-retention policies are explicitly out of scope for this fix.

**Option B (not recommended): truncate the log before spawn.**

- Truncate `BACKEND_LOG` immediately before capturing the offset, then set `log_offset = 0`.
- *Why not selected:* It destroys the previous run's log on every launch, which is a severe diagnostic regression for developers debugging crashes. On retries, it either wipes out the failed attempt's evidence or requires complex multi-file management.

### F2b - detect same-inode truncate-then-regrow

**Problem.** The `(st_dev, st_ino, st_size)` guard in `_read_backend_log_from` (`launcher.py:2944-2970`) does not detect a same-inode truncate-then-regrow to a size `>= saved_size`; the reader seeks to the stale `saved_size` and can miss or misread current-attempt output.

**Design.** Immediately after `_write_attempt_marker` (`launcher.py:2922-2935`) succeeds, capture the exact marker line bytes together with `log_identity` in `start_backend` (live call sites: token at `launcher.py:3091`, identity at `3092`, wait at `3110`). `_capture_attempt_marker` verifies that the file tail actually ends with the expected marker line containing the token and returns `None` otherwise, so a failed or partial marker write degrades to the pre-F2b behaviour (identity/size read unchanged). On every `_read_backend_log_from` call, before seeking to `saved_size`, read the bytes in `[saved_size - len(marker_bytes), saved_size)` and compare them with the captured marker bytes. Mismatch or short read -> treat as reset: read the whole file and use `content.rfind(marker_token)` exactly as the existing reset path does (`launcher.py:2960-2966`). No new on-disk state. If the marker write failed (existing fallback path at `launcher.py:2932-2934`), capture returns `None` and behaviour is unchanged.

**Residual risk.** A same-inode regrow that reproduces byte-identical marker bytes immediately before `saved_size` is undetectable by this check; accepted because it requires the exact same marker line at the exact same offset.

**Signature changes (keyword-only).**

```python
# New capture helper (returns None when the marker write failed or is unreadable)
def _capture_attempt_marker(log_file: Path, token: str) -> bytes | None: ...

# Existing live signatures extended with one optional keyword-only argument
def _read_backend_log_from(
    identity: tuple[int, int, int],
    *,
    marker_token: str,
    marker_bytes: bytes | None = None,
) -> str: ...

def _wait_for_backend_attempt(
    port: int,
    pid: int,
    timeout: float,
    log_identity: tuple[int, int, int],
    *,
    marker_token: str,
    marker_bytes: bytes | None = None,
) -> str: ...
```

`_wait_for_backend_attempt` forwards `marker_bytes` to both `_read_backend_log_from` calls (`launcher.py:2991`, `3002`).

**Acceptance criteria.** A same-inode truncate-regrow to a size greater than `saved_size` is detected and reset; normal append after the marker is not reset; a surviving marker region (the intact marker bytes immediately before `saved_size`) is NOT reset.

**Tests.** Patch `launcher.BACKEND_LOG` to `tmp_path`: `test_read_backend_log_from_detects_same_inode_truncate_regrow`, `test_read_backend_log_from_normal_append_not_reset`, `test_read_backend_log_from_intact_marker_not_reset`, and `test_wait_for_backend_attempt_detects_bind_after_truncate_regrow`.

**Test fixtures (deterministic).** For `test_wait_for_backend_attempt_detects_bind_after_truncate_regrow` and the read tests: seed the log with a long prefix; write the attempt marker with the unique token; capture `(st_dev, st_ino, st_size)` and `marker_bytes`; truncate in place (same inode) and regrow to a size `> saved_size` with the copied marker line plus `Address already in use`, so the token survives the regrow and the expected outcome is `"bind"`. If the token is destroyed during the regrow, the expected outcome is `"timeout"` by design; add a separate assertion for that case. Also assert that a surviving marker region is not reset.

### F3 - implement documented precedence, fall-through, and non-persistence

Resolve the preferred port in `ConfigManager.load` in this order:

1. `os.environ.get("ONX_BACKEND_PORT")`
2. `os.environ.get("MCS_BACKEND_PORT")`
3. `.onx/config.json` `backend_port`
4. `8000`

Rules and contracts:
- **Validation and range (D-6):** The range `1024..65535` applies strictly to the PREFERRED port. The range `1..65535` is retained for active-port reading (`.onx/backend.port`), `PortManager.can_bind`, and preflight active-port checks. Reject non-integer values, boolean tokens, and ports `< 1024` or `> 65535`.
- **Warning and fall-through (D-1):** If `ONX_BACKEND_PORT` is set but invalid (e.g., non-integer or outside `1024..65535`), emit a warning naming the variable and invalid value, ignore it, and fall through to `MCS_BACKEND_PORT`. If `MCS_BACKEND_PORT` is invalid, warn and fall through to `.onx/config.json`. If config is invalid, warn and fall through to `8000`. Never abort startup merely because one environment source is malformed.
- **Preflight alignment:** Correct both `scripts/preflight.py` and `scripts/preflight.sh` to implement the same cascading fall-through and warning behavior, eliminating the short-circuit bug in Python and the unconditional jump to 8000 in bash.
- **`LauncherConfig` default:** `LauncherConfig` (`launcher.py:183-192`) gains `configured_backend_port: int = BACKEND_PORT` with a default so that instantiation without keyword arguments (e.g. `LauncherConfig(auto_install_deps=False)`) continues to work without error.
- **`ConfigManager.update()` semantics:** `ConfigManager.update(**kwargs)` (`launcher.py:656-672 (was 597-603)`): if `backend_port` is updated via kwargs, set `cfg.configured_backend_port = value`. If an environment override (`ONX_BACKEND_PORT` or `MCS_BACKEND_PORT`) is active, do NOT alter the effective `cfg.backend_port`, and log a warning indicating that the environment override takes precedence. If no environment override is active, also update `cfg.backend_port = value`.
- **`ConfigManager.save()` non-persistence:** `save()` (`launcher.py:643-654 (was 584-595)`) must persist `cfg.configured_backend_port` into `.onx/config.json` under `"backend_port"`. Environment overrides from `ONX_BACKEND_PORT` or `MCS_BACKEND_PORT` are runtime-only and must NEVER be written to disk when `--code`, `--swagger`, or `save()` is executed. This behavior change is recorded in the docs patch.

### F4 - reconcile every failed attempt across ALL exits

`start_backend` (`launcher.py:3046-3169`) must cleanly reconcile process and metadata state across ALL exit and transition paths:

1. **`initial decision is None` (candidate scan exhausted, lines 3047-3058):**
   - When `PortManager.resolve_startup_port` returns `None`:
   - Clear `.onx/backend.port`.
   - Call `_clear_backend_pid_if(expected_pid=None)` (which is a no-op and never clears `backend.pid`).
   - Log error and return `False`.

2. **`ensure_python_environment()` returns `None` (missing interpreter, lines 3072-3083):**
   - When no Python interpreter is available:
   - Clear `.onx/backend.port`.
   - Call `_clear_backend_pid_if(expected_pid=None)` (no-op).
   - Log error and return `False`.

3. **`pid is None` (terminal launch failure, lines 3102-3105):**
   - Track `previous_attempt_pid` across retry attempts (initialized to `None`).
   - Log error: `"Failed to launch backend terminal"`.
   - Clear `.onx/backend.port`.
   - Clear `.onx/backend.pid` only if it matches `previous_attempt_pid` (`_clear_backend_pid_if(previous_attempt_pid)`). If `previous_attempt_pid is None` (first attempt), `backend.pid` is untouched.
   - Return `False`.

4. **`dead` + bindable (backend crashed during startup, lines 3121-3130):**
   - Remove the interactive `ErrorHandler.show` retry prompt and its recursive callback `lambda: start_backend(cfg, python)` (per D-7: generic crashes are non-retryable per ADR-0019 decision 7; removal eliminates re-entrant recursion).
   - Log error with manual diagnostic instructions (`launcher.py --logs`, direct uvicorn command).
   - Clear `.onx/backend.port`.
   - Clear `.onx/backend.pid` only if it matches this attempt's PID (`_clear_backend_pid_if(attempt_pid)`).
   - Return `False`.

5. **`timeout` (deadline reached without health or bind evidence, lines 3132-3138, D-2 and D-7):**
   - Per D-7: generic timeout is non-retryable.
   - Recheck backend panel health once:
     - If the listener is project-owned and now healthy: adopt it, write `.onx/backend.port`, record `cfg.active_backend_port`, and return `True`.
     - If not healthy: determine provenance using helper `_check_backend_provenance(port, wrapper_pid, spawn_time) -> ProvenanceStatus` returning `VERIFIED` or `UNKNOWN`:
       - `VERIFIED`: returned ONLY if `listener_pid == wrapper_pid`, or `listener_pid` is a descendant of `wrapper_pid` via `psutil` with `create_time >= recorded spawn_time`.
       - `UNKNOWN`: returned if PID cannot be resolved or is not a proven descendant with matching `create_time`.
     - **If project-owned and `VERIFIED`:** Terminate the attempt supervisor/wrapper tree (`PIDManager.kill_tree`). Re-verify the port is freed via `can_bind`/`get_pid_by_port`. If descendants survive, DO NOT escalate SIGKILL (D-10: `kill_tree` guarantees apply only to a proven project-owned root/supervisor and its descendants; blind escalation is prohibited); log an error reporting surviving untracked processes and abort.
     - **If project-owned but `UNKNOWN` (not `VERIFIED`) and unhealthy:** Abort without signalling the listener (D-2); terminate only the launcher-spawned wrapper PID (proven by launcher provenance) if alive.
     - **If listener is foreign or ownership cannot be established:** DO NOT signal the listener. Terminate only the launcher-spawned wrapper PID if alive.
   - Clear `.onx/backend.port`.
   - Clear `.onx/backend.pid` only if it matches this attempt's PID (`_clear_backend_pid_if(attempt_pid)`).
   - Return `False`.

6. **`next_decision is None` (fallback candidate scan exhausted during retry, lines 3154-3155):**
   - Reconcile the previous attempt (terminate wrapper if project-owned; clear matching `backend.pid`).
   - Clear `.onx/backend.port`.
   - Break loop and return `False`.

7. **`final exhaustion` (`attempt >= MAX_PORT_ATTEMPTS`, lines 3140-3141, 3167-3169):**
   - Reconcile the last failed attempt (terminate wrapper if project-owned; clear matching `backend.pid`).
   - Clear `.onx/backend.port`.
   - Log error: `f"Backend failed to start after {MAX_PORT_ATTEMPTS} attempt(s)"`.
   - Return `False`.

8. **Retry reconciliation after `bind` or `dead`+occupied (lines 3140-3165, D-3 and D-7):**
   - Per D-7: D-3 applies ONLY to failures diagnosed as bind races (`outcome == "bind"` or `dead`+occupied). Generic crash and generic timeout stay non-retryable (ADR-0019 decision 7).
   - Before selecting the next port candidate:
     - Check the listener on the attempted port.
     - **Unresolved ownership:** If a listener exists and its ownership CANNOT be resolved -> **ABORT startup immediately** (D-3). Do not retry on another port; duplicate SQLite backends risk database corruption.
     - **Project-owned listener:** Prompt or stop the project-owned listener; if it cannot be stopped or descendants survive, abort startup immediately (D-10).
     - **Conclusively foreign listener:** Do not signal the foreign process; record the port in `tried` set and proceed to the next candidate.
     - **No listener (port freed/bindable):** Safe to proceed to the next candidate.
   - Clear `.onx/backend.pid` if it points at the failed attempt (`_clear_backend_pid_if(attempt_pid)`) before recording the next attempt.

9. **Reuse metadata path reconciliation (lines 3061-3066 and 3156-3164):**
   - When `decision.reuse` is true (initial or retry scan):
   - Never write stored `backend.pid` unless it is project-owned (`PortManager.belongs_to_project(stored_pid)`) AND consistent with the active listener on that port (equal to listener PID or an ancestor supervisor of listener PID).
   - If `stored_pid` is foreign, unverified, or points to an unrelated process: resolve the listener PID, derive the supervisor via `_backend_supervisor_pid(listener_pid)`, verify ownership, and write that verified supervisor PID to `.onx/backend.pid`.
   - Write `.onx/backend.port` and return `True`.

10. **`KeyboardInterrupt` during the attempt/wait section (D-12, OWNER-CONFIRMED 2026-10-23, batch B5):**
   - Wrap the spawn/wait section (live wait loop at `launcher.py:3110`) so Ctrl-C is caught before the launcher exits.
   - Reconcile exactly like the `timeout` path: never trust the wrapper PID as the backend root; use `_check_backend_provenance` to decide; terminate only the proven project-owned attempt/wrapper tree; verify port release; report survivors and abort without SIGKILL escalation (D-2/D-10).
   - Clear `.onx/backend.port` and clear `backend.pid` only if it matches this attempt's PID (`_clear_backend_pid_if(attempt_pid)`).
   - Re-raise `KeyboardInterrupt` after reconciliation.

### F5 - require a real listener and panel signature

For backend status display and self-test, "running" is defined strictly as:

```python
def _backend_is_serving(port: int, timeout: float = 1.0) -> bool:
    """Return True only if the port has an open listener that returns the panel health signature."""
    return PortManager.is_open(port) and check_backend_health(port, timeout=timeout)
```

A live `backend.pid` terminal wrapper alone is NOT evidence of a running backend. Both `StatusDisplay._collect_service` (`launcher.py:2030 (was 1960)`) and `SelfTester.run` (`launcher.py:1935 (was 1865)`) must use this shared predicate.

`SelfTestResult` schema and isolation:
- `SelfTestResult` (`launcher.py:156-160`) defines fields `check: str`, `status: bool`, and `detail: str` (it does NOT define `ok`). Any test inspecting self-test results must assert `result.status`, not `result.ok`.
- `SelfTester.run` must be isolated during testing: specify a small testable seam (such as a helper returning only the backend health check result) or use full patching of external service calls, never executing against the live unisolated machine environment.

### F6 - EOF and KeyboardInterrupt as refusal across all callers (D-4)

Modify the exception handler in `ask_yes_no` (`launcher.py:464-476 (was 463-475)`, specifically `475-476 (was 474-475)`):

```python
except (EOFError, KeyboardInterrupt):
    return False
```

Documented behavior change:
- Interactive empty-string input (`answer == ""`) retains `default`, preserving standard `[Y/n]` prompt behavior for interactive operators.
- Non-interactive EOF (closed stdin, `/dev/null`, piped input) and `KeyboardInterrupt` (Ctrl-C) return `False` unconditionally across all three callers:
  1. `ErrorHandler.show` (`launcher.py:2172`): suppresses unintended retry loops.
  2. `_handle_own_unhealthy` (`launcher.py:3037`): prevents unauthorized termination of an unhealthy project process.
  3. `start_frontend` (`launcher.py:3187`): prevents unauthorized kill of the frontend port occupant.

### F7 - real-path tests and test hardening requirements

Tests in `backend/tests/test_launcher_dynamic_port.py` must adhere to rigorous live-evidence standards:

1. **Preconditions for listener attribution:** In tests asserting stop/kill behavior on real listener subprocesses, assert `PortManager.get_pid_by_port(port) == child.pid`. If host permissions or container environment cannot attribute the PID, skip the test (`pytest.skip("Cannot attribute listener PID on host")`) and record as `UNVERIFIED`; do not assert false pass or fake coverage.
2. **Path isolation:** Patch `launcher.MCS_DIR`, `launcher.PROJECT_ROOT`, and `launcher.BACKEND_LOG` to `tmp_path` across all state, log, stop, and config tests to avoid modifying `.onx/` or repo files.
3. **ConfigManager singleton reset:** In test hygiene / fixtures, reset the `ConfigManager` singleton (`ConfigManager._instance = None` and `ConfigManager._config = None`) between tests to guarantee state isolation across test cases.
4. **Non-preferred selected port:** When testing active-port file writing and propagation, use a non-default selected port (e.g. `8001` or an ephemeral port) to prove the code writes the actual selected port, not the default `8000`.
5. **Short-retry timeout clamping & explicit short timeouts:** Set `cfg.startup_timeout = 30` (or `> 15`) when asserting retry timeouts, proving that retry attempt 2 clamps to `min(15, 30) == 15` rather than reusing the initial timeout. In unit tests for `_wait_for_backend_attempt`, always pass an explicit short timeout (e.g. `0.2s` or `1.0s`) to ensure test suite execution remains fast and predictable.
6. **Separate wrapper from foreign listener:** In foreign-timeout tests, spawn a real foreign listener on `port` AND a separate child process as the launcher's wrapper PID (`open_backend`). Assert that timeout cleanup leaves the foreign listener running while terminating the launcher-spawned wrapper.
7. **Real "cannot stop" fixture shape:** Because `PIDManager.kill_tree` (`launcher.py:826-830`) sends SIGKILL to the root process after 1 second, a root process ignoring SIGTERM will still be killed by SIGKILL. Therefore, the "cannot stop" fixture must be constructed as a SIGTERM-ignoring **descendant** process under a wrapper PID (`signal.signal(signal.SIGTERM, signal.SIG_IGN)`), asserting the tree shape where the root dies but the descendant survives.
8. **Explicit exception to no-mock rule:** For the two unresolved-ownership tests (active stop and retry abort), patching `PortManager.get_pid_by_port` to return `None` while the port is open is permitted ONLY there, recorded as an explicit, narrow exception to the no-mock rule to simulate host unprivileged socket attribution failure.
9. **No fixed ports:** Use ephemeral ports (bind port `0` to discover available port) for real test listeners.
10. **Child process cleanup:** Every test that spawns child subprocesses must clean them up in a `finally:` block.

---

## Affected Components

| File | Planned change | In this task |
|---|---|---|
| `launcher.py` | F1 stop ownership guard; F2 append/offset guard; F3 env precedence and persistence distinction; F4 failure reconciliation; F5 shared health predicate; F6 EOF refusal. | Design only |
| `scripts/preflight.sh` / `scripts/preflight.py` | Align invalid-preferred fallback and `1024..65535` range with F3; no new contract. | Design only |
| `backend/tests/test_launcher_dynamic_port.py` | Add/replace the tests named below. | Design only |
| `.ai/STATE.json` | Correct the false precedence claim and record these defects. Separate docs/state patch. | Not edited |
| `docs/DEVELOPMENT.md` | Replace hard-coded `:8000` guidance with dynamic-port/preflight behavior. Separate docs patch. | Not edited |

No production Docker, nginx, backend API, database, or frontend behavior changes.

---

## Interfaces and Contracts

### Public signatures

No public CLI or module API breakages are introduced.

```python
# Unchanged signatures, updated behavior and contracts
ConfigManager.load() -> LauncherConfig
ConfigManager.update(**kwargs: Any) -> None
ConfigManager.save() -> None
TerminalOpener._wrap_command(cmd_str: str, log_file: Path) -> str
start_backend(cfg: LauncherConfig, python: Path | None = None) -> bool
cmd_stop() -> int
ask_yes_no(question: str, default: bool = False) -> bool

# Synchronized log-reading signatures (updated together)
# Pre-fix:
#   _read_backend_log_from(offset: int) -> str
#   _wait_for_backend_attempt(port: int, pid: int, timeout: float, log_offset: int) -> str
# Implemented (keyword-only marker_token):
_read_backend_log_from(identity: tuple[int, int, int], *, marker_token: str) -> str
_wait_for_backend_attempt(port: int, pid: int, timeout: float, log_identity: tuple[int, int, int], *, marker_token: str) -> str

# Updated signature: expected_pid and expected_create_time guards (D-9)
# Old: PortManager.kill_on_port(port: int) -> bool
PortManager.kill_on_port(port: int, expected_pid: int | None = None, expected_create_time: float | None = None) -> bool
```

### New internal helpers (names are recommendations)

```python
def _clear_backend_pid_if(expected_pid: int | None) -> None: ...
def _check_backend_provenance(port: int, wrapper_pid: int, spawn_time: float) -> ProvenanceStatus: ...
def _owned_listener_pid(port: int) -> int | None: ...
def _reconcile_failed_attempt(port: int, attempt_pid: int | None, *, kill_owned: bool) -> bool: ...
def _backend_is_serving(port: int, timeout: float = 1.0) -> bool: ...
def _stat_file_identity(path: Path) -> tuple[int, int, int]: ...
def _write_attempt_marker(log_file: Path, attempt: int, token: str | None = None) -> str: ...
```

- `_clear_backend_pid_if`: reads `.onx/backend.pid` and unlinks it ONLY if its integer value matches `expected_pid`. If `expected_pid is None`, it NEVER clears the file (no-op), preventing an exit without an attempt from clearing a live backend's PID.
- `_check_backend_provenance`: resolves the listener PID on `port` and inspects process relationship; returns enum `ProvenanceStatus.VERIFIED` ONLY if `listener_pid == wrapper_pid` or `listener_pid` is a descendant of `wrapper_pid` via `psutil` with `create_time >= spawn_time`; otherwise returns `ProvenanceStatus.UNKNOWN`.
- `_owned_listener_pid`: combines `PortManager.get_pid_by_port(port)` with `PortManager.belongs_to_project(pid)`, returning `pid` only when ownership is verified.
- `_reconcile_failed_attempt`: encapsulates D-2, D-3, and D-7 failure handling; verifies port release after termination; reports untracked survivors and aborts without escalating SIGKILL (D-10); and returns whether it is safe to proceed to another port candidate.
- `_backend_is_serving`: shared by `StatusDisplay._collect_service` and `SelfTester.run`; requires both an open port and a valid panel health signature (`check_backend_health`).
- `_stat_file_identity`: returns `(st_dev, st_ino, st_size)` for `BACKEND_LOG` (or `(0, 0, 0)` if missing) to detect rotation, truncation, or inode replacement between attempts.
- `_write_attempt_marker`: writes a distinct boundary line (`--- ONX LAUNCH ATTEMPT {attempt} ({ts}) [token:{token}] ---\n`) carrying a unique per-attempt token to isolate each attempt's log entries before capturing file identity.

### `LauncherConfig` and persistence

```python
@dataclass
class LauncherConfig:
    backend_port: int = BACKEND_PORT                 # effective preferred port after env precedence (1024..65535)
    configured_backend_port: int = BACKEND_PORT      # file/default preferred port; never the env override
    frontend_port: int = FRONTEND_PORT
    open_browser: bool = True
    open_swagger: bool = False
    open_vscode: bool = False
    auto_install_deps: bool = True
    startup_timeout: int = STARTUP_TIMEOUT
    active_backend_port: int | None = None
```

Contract:
- `configured_backend_port` defaults to `BACKEND_PORT` (`8000`), ensuring `LauncherConfig(auto_install_deps=False)` and similar positional/keyword instantiations remain fully backward compatible.
- `ConfigManager.update(**kwargs)`: updating `backend_port` sets `cfg.configured_backend_port = val`; if an environment override (`ONX_BACKEND_PORT` or `MCS_BACKEND_PORT`) is active, logs a warning and does not alter `cfg.backend_port`. If no environment override is active, it also sets `cfg.backend_port = val`.
- `ConfigManager.save()` writes `cfg.configured_backend_port` to `.onx/config.json` under `"backend_port"`, guaranteeing that environment overrides are never persisted to disk.

### `.onx/backend.port`

- Written only after a successful panel health check (`check_backend_health`).
- Format: decimal integer plus trailing newline.
- Validated range (D-6): `1..65535` for active-port reading, `can_bind`, and preflight verification (range `1024..65535` applies strictly to preferred port configuration).
- A runtime hint, not authority: read paths must still prove a live listener and verify the panel health signature.
- Cleared on `--stop`, on failed startup attempts, and during stale metadata cleanup.
- Never used to justify signalling a listener without verified project ownership (`belongs_to_project`).

### `.onx/backend.pid`

- Written at spawn and rewritten after successful health verification.
- Stores the terminal wrapper PID or supervisor PID for the current attempt.
- Format: NO change to the file format on disk (retains decimal integer PID).
- Process identity tracking (D-9): `psutil` `create_time` is captured strictly IN MEMORY at classification time and revalidated right before signaling; PID reuse across separate launcher runs is recorded as an accepted residual risk.
- Cleared on `--stop`, on failed attempts, and when dead.
- Must be cleared with expected-PID validation (`_clear_backend_pid_if`), ensuring a failed attempt does not clear a live backend's metadata. If `expected_pid is None`, `_clear_backend_pid_if` is a no-op and never clears.
- A live PID alone is not proof of a healthy backend (F5).
- Foreign listener PIDs must never be written to this file.
- The stop fallback path must independently verify `PortManager.belongs_to_project` on any PID read from this file before signaling (D-8).

### Environment contract

| Variable | Read by launcher as | Persisted? | Child meaning |
|---|---|---|---|
| `ONX_BACKEND_PORT` | Preferred port, highest precedence (1024..65535) | No | Active backend port for Vite child dev proxy |
| `MCS_BACKEND_PORT` | Preferred port, second precedence (1024..65535) | No | Legacy alias for preferred port |
| `ONX_PANEL_BIND_PORT` | Not a preferred source | No | Active backend port for panel/exposure child env |

---

## Failure and Edge Cases

| Case | Required behavior |
|---|---|
| Stale active-port file + foreign listener | Do not signal foreign listener; log warning with PID/port; clear stale file; independently evaluate and stop project-owned stored `backend.pid` if present (D-8). |
| Stale active-port file + unresolved listener | Do not signal; log warning; clear stale file; independently evaluate and stop project-owned stored `backend.pid` if present (D-8). |
| Stale active-port file + project-owned listener | Revalidate identity (`create_time`); resolve supervisor; signal tree; verify port freed; report survivor and abort if port still held (D-10); clear active/PID metadata if matching. |
| Missing active-port file + project-owned stored PID | Verify `belongs_to_project(stored_pid)`; revalidate identity (`create_time`); terminate tree; clear `backend.pid` if matching. |
| Missing active-port file + foreign/unresolved stored PID | Do not signal; log warning; clean file only if dead via `cleanup_stale`. |
| Stored PID recycled by OS (create_time mismatch) | Identity revalidation (`psutil` `create_time` in memory) fails right before signal; do not signal; log warning (D-9). |
| Log truncated or replaced with new inode between attempts | File identity `(st_dev, st_ino)` change or shrink between attempts detected; read resets to 0; reads forward from saved offset captured after attempt marker. |
| Attempt appends to existing long log | Attempt boundary marker line written first, then identity captured; reads only bytes written for current attempt; stale bind markers from prior runs or earlier attempts are excluded. |
| Log rotation DURING active attempt | Out of scope; POSIX `tee` holds open file descriptor; recorded as accepted residual risk. |
| `initial decision is None` (launcher.py:3047-3058) | Clear active-port file; leave `backend.pid` untouched (`_clear_backend_pid_if(None)` is no-op); return `False`. |
| `ensure_python_environment()` is None (launcher.py:3072-3083) | Clear active-port file; leave `backend.pid` untouched (`_clear_backend_pid_if(None)` is no-op); return `False`. |
| `dead` + port bindable (crash) | Non-retryable per ADR-0019 decision 7 and D-7; log error with manual run/logs instructions; remove interactive ErrorHandler retry; clear matching `backend.pid` and active-port; return `False`. |
| `timeout` + proven attempt (D-2, D-10) | Terminate attempt; report untracked survivors and abort without escalating SIGKILL (D-10); clear matching metadata; return `False`. Generic timeout is non-retryable (D-7). |
| `timeout` + project-owned healthy listener (D-2) | Adopt backend; write `.onx/backend.port`; set `cfg.active_backend_port`; return `True`. |
| `timeout` + foreign or unresolved listener (D-2) | Never signal listener; terminate only launcher-spawned wrapper PID (proven by launcher provenance); clear matching metadata; return `False`. |
| `KeyboardInterrupt` during attempt/wait (D-12, OWNER-CONFIRMED 2026-10-23) | Reconcile the spawned wrapper and matching metadata exactly like the timeout path (D-2/D-10; never trust the wrapper PID as the backend root); clear active-port and matching `backend.pid`; then re-raise `KeyboardInterrupt`. |
| Retry on bind race (D-7/D-3) | Applies ONLY to failures diagnosed as bind races; if occupant is unresolved -> abort immediately; if project-owned -> prompt/stop, abort if survivors remain (D-10); if free or conclusively foreign -> safe to retry on next candidate. |
| `pid is None` on terminal spawn | Log error; clear active-port; clear `backend.pid` only if matching `previous_attempt_pid` (`_clear_backend_pid_if(previous_attempt_pid)`); return `False`. |
| `next_decision is None` (candidate exhaustion) | Reconcile last attempt; clear matching `backend.pid` and active-port; return `False`. |
| `attempt >= MAX_PORT_ATTEMPTS` (final exhaustion) | Reconcile last attempt; clear matching `backend.pid` and active-port; return `False`. |
| Reuse metadata path (`decision.reuse`) | Write stored `backend.pid` only if project-owned and consistent with listener; otherwise write verified supervisor PID. |
| `ONX_BACKEND_PORT` invalid value (D-1) | Warn naming variable and value; ignore source; fall through to `MCS_BACKEND_PORT` (same in launcher, preflight.py, preflight.sh). |
| Preferred port outside 1024..65535 (D-6) | Reject source; warn; fall through to next preference tier. |
| Active port in 1..1023 (D-6) | Valid for `.onx/backend.port`, `PortManager.can_bind`, and preflight active-port reading (1..65535 allowed). |
| Env override followed by `update()` / `save()` / `--swagger` | Persist `cfg.configured_backend_port` to `.onx/config.json`; env override is never written to disk. Under active env override, `update(backend_port=...)` sets `configured_backend_port` only, warns, and leaves effective override intact. |
| EOF / KeyboardInterrupt during prompt (D-4) | Return `False` across all 3 callers (`ErrorHandler`, `_handle_own_unhealthy`, `start_frontend`); do not kill, do not retry. |
| `kill_tree` leaves surviving descendants | Verify port status after kill; do NOT escalate SIGKILL; report untracked survivors and abort (D-10). |
| Log file growth under `tee -a` | Known cost: unbounded growth across launches; log rotation is out of scope. |
| Concurrent launcher invocations | Out of scope; residual risk unchanged. |

---

## Tests and Verification

All tests belong in `backend/tests/test_launcher_dynamic_port.py` unless noted. Tests use `pytest` `tmp_path` for state and logs; no repo-root SQLite or `/tmp` artifacts.

### Required tests and mutations

| Test | What it exercises | Mutation it must catch |
|---|---|---|
| `test_cmd_stop_does_not_signal_foreign_listener_from_active_port` | Start real foreign listener on ephemeral port (cwd outside repo, non-project markers); assert precondition `get_pid_by_port(port) == child.pid`; write stale `.onx/backend.port`; run `cmd_stop`; assert foreign child is alive, `.onx/backend.port` is removed, and independently stored project-owned `backend.pid` is handled if present (merges foreign-listener stop and port-clear verification; duplicate removed). Cleanup child in `finally:`. | Remove/reorder `belongs_to_project(listener_pid)` guard, or signal port occupant unconditionally. Child killed -> failure. |
| `test_cmd_stop_still_stops_project_owned_listener_from_active_port` | Real project listener on ephemeral port (cwd inside `PROJECT_ROOT`); assert precondition `get_pid_by_port(port) == child.pid`; active-port file points at it; run `cmd_stop`; assert child terminated and port freed. Cleanup child. | Over-fix: never signaling port occupant. Child survives -> failure. |
| `test_cmd_stop_foreign_backend_pid_fallback_is_not_signalled` | No active-port file; write foreign child PID to `.onx/backend.pid`; run `cmd_stop`; assert foreign child survives and warning logged. Cleanup child. | Fallback signals stored PID without `belongs_to_project(pid)` check. Foreign child killed -> failure. |
| `test_cmd_stop_unresolved_active_listener_does_not_fall_through_to_kill` | Active port held by listener whose PID cannot be attributed (patch `PortManager.get_pid_by_port` to return `None` as explicit narrow exception to no-mock rule); write foreign child PID to `backend.pid`; run `cmd_stop`; assert foreign child is not signalled. Cleanup child. | Unresolved listener falls through to unguarded `backend.pid` kill. Foreign child killed -> failure. |
| `test_cmd_stop_missing_port_file_stops_owned_backend_pid` | Missing active-port file; write project-owned child PID to `.onx/backend.pid`; run `cmd_stop`; assert child is stopped and `backend.pid` cleared. Cleanup child. | Failing to terminate project-owned backend when port file is absent. Child survives -> failure. |
| `test_cmd_stop_clears_backend_pid_only_if_matching_stopped_process` | Active port stopped; `backend.pid` contains distinct live PID; run `cmd_stop`; assert the distinct PID is still alive AND `backend.pid` is untouched. Cleanup child. | Unconditional `PIDManager.clear("backend")` erasing an unrelated process PID or killing unrelated process. |
| `test_kill_on_port_rejects_mismatched_expected_pid` | Ephemeral port listener with PID A; call `kill_on_port(port, expected_pid=PID_B)`; assert returns `False` and process A survives. Cleanup child. | Blind kill on port ignoring `expected_pid`. Process A killed -> failure. |
| `test_wait_for_backend_attempt_detects_bind_error_when_log_shrank` | Write long initial log; capture identity; truncate/rewrite with short bind-error text and attempt marker; pass short timeout (0.5s); assert `_wait_for_backend_attempt` returns `"bind"`. | Remove shrink / size check. Read returns empty string -> returns `"timeout"`. |
| `test_wait_for_backend_attempt_detects_bind_error_on_inode_replacement` | Capture identity; atomically replace `BACKEND_LOG` with new file (different inode) containing bind marker; pass short timeout (0.5s); assert returns `"bind"`. | Tracking size only without `st_ino`/`st_dev`. Seeks past EOF or misses replacement -> returns `"timeout"`. |
| `test_wait_for_backend_attempt_detects_bind_error_on_rotation_to_larger` | Capture identity; replace `BACKEND_LOG` with a larger file (different inode) whose first bytes lack error; pass short timeout (0.5s); assert returns `"bind"` after attempt marker. | Tracking size only without inode check. Reads from old offset -> misses bind marker. |
| `test_wait_for_backend_attempt_excludes_stale_markers_from_older_attempts` | Prior run/attempt log contains `Address already in use`; new attempt marker written; capture offset that would expose stale text if marker logic were absent; current attempt emits no bind error; pass short timeout (0.5s); assert returns `"timeout"` or `"dead"`, not `"bind"`. | Omitting attempt boundary markers or reading from offset 0 unconditionally. Old bind error triggers false-positive retry. |
| `test_backend_wrapper_uses_append_tee` | Call `_wrap_command` for POSIX path; assert wrapper command string contains `tee -a`. | Wrapper reverts to plain `tee`, truncating log on terminal open. |
| `test_backend_wrapper_appends_to_existing_log` | Run real `tee -a` wrapper command appending to an existing log file with pre-existing text; assert pre-existing text is preserved and new command output is appended. | Truncation of existing log file during command wrapping execution. |
| `test_load_precedence_onx_over_mcs_and_file` | Set `ONX_BACKEND_PORT=8100`, `MCS_BACKEND_PORT=8200`, and config `backend_port=8300`; assert `ConfigManager.load().backend_port == 8100`. | Ignored `ONX_BACKEND_PORT` or wrong priority order. |
| `test_load_precedence_mcs_over_file` | Unset `ONX_BACKEND_PORT`; set `MCS_BACKEND_PORT=8200`, config `8300`; assert `backend_port == 8200`. | Dropping legacy `MCS` alias. |
| `test_load_invalid_env_is_ignored_with_warning` | Set invalid `ONX_BACKEND_PORT="notanint"`, valid `MCS_BACKEND_PORT=8200`; assert warning emitted and `backend_port == 8200`. | Short-circuiting / jumping directly to 8000 or crashing on invalid env. |
| `test_load_rejects_preferred_ports_outside_1024_65535` | Test values `80`, `1023`, `65536`, `-1`; assert warning and fall-through to next preference tier. | Accepting privileged or invalid ports as preferred. |
| `test_load_allows_active_ports_in_1_65535` | Write port `80` to `.onx/backend.port`; assert `PIDManager.read_active_port() == 80`. | Over-restricting active-port file to `1024..65535` (violating D-6). |
| `test_save_does_not_persist_env_override` | Load with `ONX_BACKEND_PORT=8123` and config file `8000`; call `ConfigManager.save()`; reread JSON on disk and assert `backend_port == 8000`. | Saving effective env override `cfg.backend_port` to disk. |
| `test_launcher_config_default_configured_backend_port` | Instantiate `LauncherConfig(auto_install_deps=False)`; assert `configured_backend_port == BACKEND_PORT`. | Missing default causing `TypeError` on keyword instantiation. |
| `test_config_manager_update_sets_configured_backend_port` | Under active env override `ONX_BACKEND_PORT=8123`, call `ConfigManager.update(backend_port=8400)`; assert warning logged, `cfg.configured_backend_port == 8400`, `cfg.backend_port == 8123`, and `save()` writes `8400`. | Update alters effective override or fails to update persistent configured port. |
| `test_start_backend_initial_decision_none_cleans_metadata` | Simulate `PortManager.resolve_startup_port` returning `None`; assert `start_backend` returns `False`, `.onx/backend.port` is cleared, and `backend.pid` is untouched (`_clear_backend_pid_if(None)` is a no-op). | Leaving active port behind or clearing unrelated `backend.pid`. |
| `test_start_backend_python_env_none_cleans_metadata` | Simulate `ensure_python_environment()` returning `None`; assert `start_backend` returns `False`, `.onx/backend.port` is cleared, and `backend.pid` is untouched. | Leaving active port behind or clearing unrelated `backend.pid`. |
| `test_start_backend_reuse_verifies_stored_pid_ownership` | Port candidate is reused (`decision.reuse=True`), but `backend.pid` contains an unrelated foreign PID; assert `start_backend` resolves listener PID, verifies ownership, and writes verified supervisor PID rather than copying the unrelated stored PID. | Unconditionally copying unverified stored PID to `backend.pid` during reuse. |
| `test_timeout_stops_project_owned_attempt_and_clears_matching_backend_pid` | Project-owned listener subprocess; short startup timeout; assert child is terminated, port freed, and metadata cleared. Cleanup child. | Timeout leaves spawned attempt running or leaves `backend.pid` behind. |
| `test_timeout_does_not_signal_foreign_listener_and_stops_wrapper` | Foreign child on `port`; separate child wrapper PID returned by `open_backend`; assert foreign child survives, wrapper is stopped, and metadata cleared. Cleanup children. | Foreign process signalled, or wrapper left leaking. |
| `test_dead_bindable_failure_clears_matching_backend_pid_without_recursive_retry` | Dead attempt PID and bindable port; assert returns `False`, clears `backend.pid`, and does NOT invoke recursive `ErrorHandler.show` retry. | Calling interactive retry or leaving `backend.pid` behind. |
| `test_pid_is_none_cleans_metadata` | Simulate `TerminalOpener.open_backend` returning `None`; assert `start_backend` returns `False` and clears matching metadata only if matching previous attempt PID. | Stale PID left behind from prior attempts. |
| `test_final_exhaustion_cleans_matching_backend_pid` | Drive attempts to `MAX_PORT_ATTEMPTS` exhaustion; assert `backend.pid` matching last attempt is cleared and returns `False`. | Leaving PID in `.onx/backend.pid` upon final exhaustion. |
| `test_next_decision_none_cleans_matching_backend_pid` | Simulate candidate exhaustion during retry (`resolve_startup_port` returns None); assert metadata cleared and returns `False`. | Leaving PID in `.onx/backend.pid` when scan is exhausted. |
| `test_start_backend_retries_on_real_bind_error_in_log` | Integration test: start backend attempt 1 where real log file receives `Address already in use` error; assert `start_backend` detects bind error and retries attempt 2 on next candidate (old spec #16). | Masking bind error as timeout; failing to retry next candidate on real log bind error. |
| `test_retry_aborts_when_previous_owned_listener_cannot_be_stopped` | "Cannot stop" fixture: launch wrapper root process with a child descendant process that ignores `SIGTERM` (`signal.signal(signal.SIGTERM, signal.SIG_IGN)`); `kill_tree` kills wrapper root after 1s via SIGKILL, but descendant survives; assert tree shape and assert startup aborts without spawning a second backend. Cleanup child. | Spawning a second backend while owned descendant listener survives (SQLite integrity hazard). |
| `test_retry_aborts_when_listener_ownership_is_unresolved` | Listener on attempted port cannot be attributed (patch `PortManager.get_pid_by_port` to return `None` as explicit narrow exception to no-mock rule); assert startup aborts immediately (D-3) without retrying. | Retrying on next candidate with unresolved listener on failed port. |
| `test_retry_only_after_previous_foreign_occupant_is_ignored` | First attempt fails against foreign listener; assert retry occurs on next candidate and foreign child survives. Cleanup child. | Signaling foreign occupant or aborting when occupant is conclusively foreign. |
| `test_retry_verifies_port_freed_and_reports_survivors` | Attempt fails, descendant survives `kill_tree`; assert survivor is detected via `get_pid_by_port`, error/warning logged, no SIGKILL escalated to descendants (D-10), and retry aborted. | Escalating SIGKILL to descendants or claiming port freed when descendant survived. |
| `test_retry_attempts_use_short_timeout` | Configure `cfg.startup_timeout = 30`; drive two attempts; assert attempt 1 uses `30s` and attempt 2 uses `15s` (`min(15, 30)`). | Using full 30s for retries, or hardcoding 15s for attempt 1. |
| `test_status_reports_live_wrapper_without_listener_as_not_running` | Write live process PID to `backend.pid` with closed port; call `StatusDisplay._collect_service(..., verify_backend=True)`; assert `running is False`. | Relying on `alive` alone, falsely reporting running. |
| `test_self_tester_run_backend_health_requires_listener` | Isolate `SelfTester.run` via small testable seam (or full mock of external network calls); live wrapper PID in `backend.pid` with closed port; assert `SelfTestResult.status is False` for `"Backend health"`. | SelfTester reports `status is True` based on PID liveness or fails to check `status` field. |
| `test_ask_yes_no_eof_returns_false_even_when_default_true` | Patch `builtins.input` with `EOFError`; call `ask_yes_no("Prompt?", default=True)`; assert `False`. | Returning `default` on EOF, granting unintended consent. |
| `test_handle_own_unhealthy_eof_does_not_call_kill_on_port` | Inject `EOFError` during `_handle_own_unhealthy`; patch `kill_on_port`; assert `kill_on_port` is NOT called and returns `False`. | EOF authorizes killing unhealthy project process. |
| `test_error_handler_eof_does_not_retry` | Inject `EOFError` during `ErrorHandler.show`; assert retry callback is NOT invoked. | EOF triggers recursive retry in error handler. |
| `test_start_frontend_eof_does_not_kill_port` | Inject `EOFError` during frontend port collision; assert port kill is aborted. | EOF triggers frontend port kill. |
| `test_start_backend_writes_non_preferred_active_port_on_health` | Healthy launch on non-default port `8001`; assert `.onx/backend.port` contains `8001` and `cfg.active_backend_port == 8001`. | Hardcoding or writing preferred port instead of actual active port. |
| `test_frontend_env_contains_active_backend_port` | Call `open_frontend(8123)`; patch `TerminalOpener._open` to capture env; assert `extra_env["ONX_BACKEND_PORT"] == "8123"`. | Active port not forwarded to Vite dev server proxy. |
| `test_status_uses_healthy_active_port_file` | Active port `8001` healthy; call `StatusDisplay._collect_service(..., verify_backend=True)`; assert `running is True` and effective port `8001` is reported. | Ignoring valid active-port metadata in status display collection. |
| `test_preflight_resolve_preferred_backend_port` | Call `resolve_preferred_backend_port()` in `scripts/preflight.py` with parameterized env/config inputs; assert exact precedence tier matching and warning on invalid env. | Short-circuiting invalid env or incorrect precedence order. |

### Test hygiene

- **Precondition assertion:** Every test spawning a real listener subprocess must assert `PortManager.get_pid_by_port(port) == child.pid`. If host unprivileged permissions, environment namespaces, or OS differences prevent PID attribution, invoke `pytest.skip("Cannot attribute listener PID on this host")` and record the test as `UNVERIFIED`.
- **tmp_path isolation:** Patch `launcher.MCS_DIR`, `launcher.PROJECT_ROOT`, and `launcher.BACKEND_LOG` to `tmp_path` across all state, stop, log, and config tests. Never modify live repository files or `.onx/` during test runs.
- **ConfigManager singleton reset:** Reset `ConfigManager._instance = None` and `ConfigManager._config = None` in an autouse pytest fixture or setup/teardown block across all tests to prevent configuration leakage between test cases.
- **Explicit exception to no-mock rule:** For the two unresolved-ownership tests (`test_cmd_stop_unresolved_active_listener_does_not_fall_through_to_kill` and `test_retry_aborts_when_listener_ownership_is_unresolved`), patching `PortManager.get_pid_by_port` to return `None` is permitted ONLY there to simulate host socket attribution failure; this is recorded as an explicit, narrow exception to the no-mock rule.
- **Cannot-stop fixture shape:** To test unkillable process handling, spawn a wrapper root process with a child descendant process that ignores `SIGTERM` (`signal.signal(signal.SIGTERM, signal.SIG_IGN)`). This guarantees that when `PIDManager.kill_tree` executes, the wrapper root dies from SIGKILL after 1s, leaving the descendant alive as an untracked survivor, asserting the true tree shape.
- **Explicit short timeouts:** In all tests exercising `_wait_for_backend_attempt`, pass an explicit short timeout (e.g. `0.2s` or `0.5s`) to ensure fast and deterministic test suite execution.
- **SelfTester isolation:** Isolate `SelfTester.run` by specifying a small testable seam (e.g., a function returning only the backend health check result) or full patching of external collaborators, never running unisolated against the live host environment. Assert `SelfTestResult.status`, not `ok`.
- **Ephemeral ports only:** Never bind hardcoded fixed ports (like `8000` or `8001`) in real listener tests; discover an available port dynamically (bind port `0` and retrieve `getsockname()[1]`).
- **No mocks of the function under test:** Do not mock `_read_backend_log_from`, `_wait_for_backend_attempt`, or `start_backend` when testing their respective behaviors. Collaborators (`open_backend`, `input`, `check_backend_health`) may be patched only where the test is specifically evaluating the caller's decision logic.
- **Ownership test integrity:** Do not mock `belongs_to_project`, `get_pid_by_port`, or `kill_tree` in F1 and F4 ownership tests (except for the single unresolved-ownership exception noted above).
- **Deterministic hooks:** Use explicit deterministic seams or hooks (such as controlled log injection or simulated bind collision) to test the retry loop without depending on wall-clock race timings.
- **Child process termination:** Every test creating child processes must terminate and join them in a `finally:` block.
- **Windows compatibility:** Run tests with `os.name == "nt"` guards where socket or attribution APIs differ. If attribution is unsupported on Windows CI, record `UNVERIFIED`.

### Preflight testing and verification

Preflight scripts must be verified alongside the launcher:

1. **Resolver helper:** Add `resolve_preferred_backend_port() -> int` in `scripts/preflight.py` to allow direct unit testing of preflight precedence and fall-through logic.
2. **Verification commands:**
   ```bash
   python scripts/preflight.py
   bash scripts/preflight.sh
   cd backend && python -m pytest -q tests/test_launcher_dynamic_port.py tests/test_launcher_prerequisites.py
   cd backend && python -m pytest -q
   scripts/reverify
   ```
3. **Manual recorded evidence:**
   - **Run #2 verification:** Start backend on fallback port (e.g., `8001`); run `python scripts/preflight.py` and `bash scripts/preflight.sh`; confirm active backend is preserved and not killed.
   - **Invalid env verification:** Run with `ONX_BACKEND_PORT=invalid`; confirm warning is emitted and preflight successfully falls through to `MCS_BACKEND_PORT` or `.onx/config.json`.

---

## Out of Scope

- Concurrent launcher invocations / singleton locking.
- Log rotation and retention policies; known cost: unbounded growth of `.onx/logs/backend.log` under `tee -a` (rotation is deferred to a future logging improvement).
- Live log rotation during an active attempt: `tee` holds an open file descriptor on POSIX; external rotation during an attempt is recorded as an accepted residual risk.
- PID reuse across separate launcher runs (since `.onx/backend.pid` retains decimal integer format without persisting `create_time` to disk) is recorded as an accepted residual risk.
- Frontend readiness/URL constants (`F-PORT-FRONTEND-01`).
- `start_frontend`'s use of `kill_on_port` (`launcher.py:3193 (was 3058)`) without expected PID/create_time and `cmd_stop`'s frontend PID branch (`launcher.py:3326-3332 (was 3181-3197)`) are recorded as explicit owner-visible residual risks, out of scope; acceptance criterion 1 is strictly scoped to the backend stop path.
- Production Docker/nginx/backend API changes.
- Modifying `PortManager.belongs_to_project` heuristic keywords or adding new project markers.
- Modifying the port scan span (`100` ports) or maximum retry count (`3` attempts).
- **Rollback awareness:** satisfied per `.ai/RULES/scope-and-implementation.md` by the per-batch revert notes above (small local, unpushed diffs at HEAD `5b775e4`).
- **Residual risk (D-9 non-atomic window):** an inherent non-atomic window remains between the last `create_time` revalidation and signal emission, including `kill_on_port`'s internal resolve -> verify -> signal sequence; accepted because the `0.5` s `create_time` tolerance makes PID reuse within that window vanishingly unlikely.

---

## Inherited Decisions (OWNER-CONFIRMED 2026-10-22)

These decisions are inherited unchanged from `docs/design/SPEC-2026-10-20-DYNAMIC-BACKEND-PORT-01.md`.

| ID | Question | OWNER-CONFIRMED 2026-10-22 |
|---|---|---|
| **O-1** | Should a fallback port be ephemeral runtime state (`.onx/backend.port`) with the preferred port kept in `.onx/config.json`, or should the chosen port become the new saved preference? | **Ephemeral runtime state.** Preferred is retried on every start. |
| **O-2** | For a project-owned but unhealthy backend (on the preferred port or any scan candidate): prompt-kill (abort on decline), or silently fallback? | **Prompt-kill; never fallback** (A7). This is the one intentional exception to "occupied live process -> another port". |
| **O-3** | Is a 100-port scan span (`preferred+1..preferred+99`) acceptable? | **Yes, 100 ports.** |
| **O-4** | Environment precedence `ONX_BACKEND_PORT` > `MCS_BACKEND_PORT` > `.onx/config.json` > `8000`? | **Approved as written.** |
| **O-5** | If `.onx/backend.port` names a healthy backend on `8001` while lower ports (including `8000`) are foreign-held, should the launcher reuse `8001` or prefer the lowest free port? | **Reuse `8001`.** Do not churn ports or move a healthy backend. |

---

## Decisions (OWNER-CONFIRMED 2026-10-22)

O-1..O-5 and D-1..D-10 are OWNER-CONFIRMED as of 2026-10-22, as is D-11 Option A (invalid configured preferred port, including below 1024, warns and falls back to `8000`). D-12 (KeyboardInterrupt exit path) is OWNER-CONFIRMED as of 2026-10-23. The spec status stays PROPOSED until the independent design review of v5.3 completes.

The following architectural decisions are owner-confirmed unless marked otherwise:

| ID | Topic | OWNER-CONFIRMED 2026-10-22 | Recorded Policy |
|---|---|---|---|
| **D-1** | Invalid env port value | **Warn, ignore, fall through** | If `ONX_BACKEND_PORT` or `MCS_BACKEND_PORT` contains an invalid value (non-integer, out of range `1024..65535`), log a warning naming the variable and invalid token, ignore that source, and fall through to the next source in the chain. Apply identical behavior across `launcher.py`, `scripts/preflight.py`, and `scripts/preflight.sh`. Startup is never aborted solely because an environment variable is malformed. |
| **D-2** | Startup timeout handling | **Proven kill / adopt / abort** | When the startup deadline expires: if the process listening on `port` is proven to be the attempt just spawned by this launcher and is not healthy, terminate it; if a listener on `port` is project-owned and passes panel health verification, adopt it as healthy and return success; if foreign or unverified, do not signal the listener, terminate only the launcher-spawned wrapper PID, and abort. |
| **D-3** | Retry after failed attempt | **Unresolved -> abort; Free -> retry** | Following a failed attempt: if an occupant remains on the port with **unresolved ownership**, startup must **abort immediately** (never spawn another backend that could concurrently access the SQLite database); if no listener remains on the port (`can_bind` succeeds) or the occupant is conclusively foreign, retrying on the next candidate port is safe. |
| **D-4** | Non-interactive EOF & Ctrl-C | **Return `False` for all callers** | In `ask_yes_no`, catching `EOFError` or `KeyboardInterrupt` returns `False` unconditionally for all 3 callers (`launcher.py` `ErrorHandler` retry callback at line 2172, `_handle_own_unhealthy` at line 3037, and `start_frontend` port kill prompt at line 3187). Non-interactive execution is treated strictly as refusal, never authorization to kill or retry. Interactive blank input (`Enter`) continues to return `default`. |
| **D-5** | Stop-path ownership gate | **Gate BOTH active port and stored PID** | `cmd_stop` must verify `PortManager.belongs_to_project` on BOTH the active-port listener PID and any stored PID in `.onx/backend.pid` before signaling. Never signal any PID whose project ownership cannot be proven. An unresolved listener on the active port must not fall through to an unguarded kill. |
| **D-6** | Port validation ranges | **1024..65535 preferred; 1..65535 active/bind** | Apply the range `1024..65535` strictly to the PREFERRED port configuration. Retain `1..65535` for `.onx/backend.port` runtime reading, `PortManager.can_bind`, and preflight active-port checks, ensuring valid system-assigned or privileged ports are not falsely rejected during active inspection. |
| **D-7** | Bind-race retry scope & crash/timeout | **Bind races only; crash/timeout non-retryable** | D-3 applies ONLY to failures diagnosed as bind races (`outcome == "bind"` or `dead`+occupied). Generic crash (`dead`+bindable) and generic timeout stay non-retryable per ADR-0019 decision 7. Removal of the interactive ErrorHandler retry callback in `dead`+bindable is recorded as a direct consequence of this policy. |
| **D-8** | Stop-path independent stored PID handling | **Stop project-owned stored PID unconditionally** | In `cmd_stop`: after handling the active-port listener (never signalling a foreign or unresolved listener), independently gate and stop stored `backend.pid` if it is project-owned (`PortManager.belongs_to_project(stored_pid)`), even when the active-port listener is foreign or unresolved. A foreign or unresolved listener is never signalled. |
| **D-9** | Process identity revalidation & `kill_on_port` | **In-memory create_time check; no PID file format change** | Capture `psutil.Process.create_time` IN MEMORY at classification time and compare it immediately before signalling both the listener and the chosen supervisor. NO change to the `.onx/backend.pid` format on disk (retains decimal integer PID). PID reuse across launches is recorded as an accepted residual risk. `PortManager.kill_on_port` gets `expected_pid` and `expected_create_time`; every internal caller (`cmd_stop`, `_handle_own_unhealthy`, F4 failure reconciliation) passes them. |
| **D-10** | Surviving descendant handling | **Report and abort; no SIGKILL escalation** | No SIGKILL escalation to surviving descendants. If descendants survive termination (due to ignoring SIGTERM), report them and abort startup (no kill). Record that `kill_tree` guarantees apply only to a proven project-owned root/supervisor and its descendants. |
| **D-11** | Legacy/invalid config backend_port | **Strict (Option A)** | A config `backend_port` that is invalid, below `1024` or above `65535` warns and falls back to `8000`, same range as env sources. Owner-Approved (answer date 2026-10-21). |
| **D-12** | KeyboardInterrupt during startup | **OWNER-CONFIRMED 2026-10-23: reconcile then re-raise** | `start_backend` gets an explicit `KeyboardInterrupt` exit path in batch B5: wrap the attempt/wait section so that Ctrl-C reconciles the spawned wrapper PID and matching `backend.pid` metadata exactly like the timeout path (D-2/D-10), never trusting a wrapper PID as the backend root, then re-raises `KeyboardInterrupt`. |

---

## Open Questions

- **O-6 (OPEN, owner decision needed):** should `ConfigManager.update` validate `backend_port` with the same `1024..65535` parser before storing it? At `cf827e8` it does not; no production caller exists outside tests; an invalid stored value is rejected on next load (warn, fall back to `8000`). No change is specified until the owner decides.
- **O-7 (DECIDED 2026-10-22: option (b)):** `launcher.py` is a standalone root script. `backend/app/core/process_utils.py` has `_verify_process_identity` (`backend/app/core/process_utils.py:134`) and kill helpers accepting `expected_create_time` (`:217`, `:302`), but no shared helper is importable by the launcher, and F1 needs process identity checks.
  - **Decision: Option (b) — duplicate a minimal process-identity helper inside `launcher.py`.** Capture `psutil.Process.create_time` at classification and compare it immediately before signalling with a `0.5` s tolerance; refuse (return `False`) on mismatch, when `create_time` cannot be read, and when `expected_create_time is None` (no proof, no kill; O-8). A drift test must run both implementations against a real child process and assert they agree for match, mismatch, and dead PID; the `None` case is excluded from the drift comparison as an intentional divergence (backend returns `True`) and covered by a separate launcher-helper unit test; tests use `tmp_path`/`monkeypatch` and never touch the real `.onx` directory.
  - **FACT (verified 2026-10-22 at HEAD `5b775e4`):** `launcher.py` already imports and uses `psutil` inside functions. `grep -n psutil launcher.py` -> `776`, `778`, `780`, `946`, `947`, `950`, `954`, `958`, `1171`, `1172`, `1173`, `3015`, `3016` (imports at `778`, `946`, `1171`, `3015`; uses in descendant/supervisor/CPU-memory paths). No new dependency is introduced.
  - (a) Import from the backend package: not selected — couples the root launcher to backend layout/import path.
  - (c) Other: not needed.
- **O-8 (DECIDED: option (a), OWNER-CONFIRMED 2026-10-23): `expected_create_time is None` semantics.** Backend `process_utils._verify_process_identity` (`backend/app/core/process_utils.py:134`) returns `True` when `expected_create_time is None`; the launcher helper for F1 REFUSES (no proof, no kill).
  - **Option (a): launcher refuses on `None`.** Pros: keeps "no proof, no kill"; drift test documents this as an intentional divergence and excludes the `None` case. Cons: helper semantics differ; an unknown create_time can leave a project-owned wrapper unstoppable through this path.
  - **Option (b): match `process_utils` exactly.** Pros: one consistent contract; simpler drift test. Cons: signals on `None` without identity proof, contradicting D-9's refuse-when-unreadable rule and the no-proof/no-kill principle.
  - **Decision: Option (a) — the launcher's process-identity helper REFUSES when `expected_create_time is None` (no proof, no kill). The drift test documents this as an intentional divergence from backend `process_utils._verify_process_identity` (which returns `True` on `None`, `backend/app/core/process_utils.py:137-138`) and excludes the `None` case.**

---

## Parent Spec and ADR-0019 Amendments (for D-3 and D-7)

Decisions **D-3** and **D-7** amend the retry behavior previously specified in ADR-0019 and parent spec `SPEC-2026-10-20-DYNAMIC-BACKEND-PORT-01`. These amendments are assigned to batch B9 (docs patch). Their exact affected parent sections are listed below for authoritative reference:

### ADR-0019 (`docs/decisions/0019-dynamic-backend-port.md`)

1. **Lines 68-70 (Decision 6):**
   - *Parent text:* `"Foreign and unknown listeners are never signalled and never reused. A resolved PID that fails ownership markers is foreign even if it returns the panel signature; HEALTHY_UNVERIFIED reuse is limited to unresolvable PIDs, with a warning."`
   - *Amendment under D-3:* An unresolved listener remaining on the attempted port after a failed launch forbids retrying on another candidate port; startup must abort immediately.
2. **Lines 71-73 (Decision 7):**
   - *Parent text:* `"Bounded bind-race retry: at most 3 attempts... Retry only on bind evidence; do not retry a genuine crash or a generic timeout."`
   - *Amendment under D-3 and D-7:* Retrying on the next port candidate is permitted only for failures diagnosed as bind races (`outcome == "bind"` or `dead`+occupied) and only when no listener remains on the attempted port (`can_bind` is true) or the occupant is conclusively proven foreign. If an occupant with unresolved ownership remains on the attempted port, retry is prohibited and startup aborts to protect SQLite data integrity. Generic crashes and timeouts remain non-retryable.

### Parent Spec (`docs/design/SPEC-2026-10-20-DYNAMIC-BACKEND-PORT-01.md`)

1. **Lines 124-134 (Port classification table):**
   - *Parent text:* Port classification table row mapping `PID unresolved` / `Invalid or unavailable` to `UNKNOWN`.
   - *Amendment under D-3:* Confirms that an `UNKNOWN` occupant on an attempted port blocks any subsequent candidate retry and causes startup to abort immediately.
2. **Lines 176-179 (Failure detection rules 2 & 4):**
   - *Parent text:* Rule 2: `"2. New log bytes contain a bind marker... -> bind failure; retry with the next candidate."`; Rule 4: `"4. The wrapper is dead and the selected port is occupied -> bind race; retry."`
   - *Amendment under D-3 and D-7:* If rule 2 or rule 4 diagnoses a bind race, the occupant on the attempted port must be inspected before retrying. If ownership of the occupant is unresolved or a project-owned process survives, the launcher must NOT retry on the next candidate and must abort immediately.

---

## Documentation Corrections (Separate Docs Patch)

These documentation and state updates are separate from the core code build and must be delivered in a dedicated docs/state patch (Batch B9):

1. **`docs/DEVELOPMENT.md`:**
   - **Docker statements stay at `:8000`:** Line 225 (`"Both backend (uvicorn on :8000) and frontend (nginx on :80) are defined in docker-compose.yml"`) and lines 220-228 reside in the "Docker Development" section where fixed port 8000 is intentional. These statements must remain `:8000`.
   - **Local development lines updated:** Update local dev sections (`:63`, `:86`, `:100`, `:119`, `:148`, `:299`, `:303`) to describe dynamic preferred port resolution, runtime active port `.onx/backend.port`, panel-signature health verification, precedence (`ONX_BACKEND_PORT` > `MCS_BACKEND_PORT` > `.onx/config.json` > `8000`), and `ConfigManager.save()` persisting `configured_backend_port`.
2. **`.ai/STATE.json`:**
   - Correct claims regarding stop path foreign-listener safety (recording that ownership gating on both active-port and `backend.pid` fallback was added to close foreign signaling vulnerabilities).
   - Record F1-F7 defect resolutions once verified by CI.
3. **`launcher.py:98-99` dead constants (documentation note only):**
   - `BACKEND_HEALTH_URL` and `SWAGGER_URL` are computed from constant `BACKEND_PORT = 8000` and are not consumed elsewhere in the repository. Document them as dead constants in the docs patch and mark for cleanup; no edits to `launcher.py` in Batch B9.
4. **Parent spec and ADR-0019 amendments:**
   - Deliver the documentation amendments to `docs/decisions/0019-dynamic-backend-port.md` and `docs/design/SPEC-2026-10-20-DYNAMIC-BACKEND-PORT-01.md` as specified in the section above.
5. **Cross-referencing:**
   - Cross-reference this specification (`SPEC-2026-10-20-DYNAMIC-PORT-FIXES-01`) as the definitive bugfix spec amending ADR-0019 and parent spec `SPEC-2026-10-20-DYNAMIC-BACKEND-PORT-01`.

---

## Acceptance Criteria

1. **Stop path foreign process safety (backend):** `cmd_stop` never sends any signal to a foreign, unverified, or unknown process, whether discovered via `.onx/backend.port` or `.onx/backend.pid`; independently evaluates and stops a project-owned `backend.pid` even when the active-port listener is foreign or unresolved (D-8). (Residual risks for frontend stop and `start_frontend` are noted out of scope).
2. **Stop path identity and metadata accuracy:** `cmd_stop` revalidates process identity (`psutil.Process.create_time` captured in memory, D-9) before signaling and clears `.onx/backend.pid` only if it matches the stopped process (`_clear_backend_pid_if`); `.onx/backend.pid` file format on disk remains unchanged.
3. **Stop path project termination:** A project-owned listener on the active port or named by `backend.pid` is cleanly stopped and the port freed.
4. **Log append & file identity tracking:** `backend.log` uses `tee -a`; attempt boundary marker is written first, followed by capturing file identity `(st_dev, st_ino, st_size)`; `_read_backend_log_from` resets offset to 0 on inode change or shrink between attempts, reading forward from the captured offset without scanning for attempt numbers; on a reset the reader locates only the current attempt's unique token via `content.rfind(marker_token)`.
5. **Preferred port precedence & fall-through:** `ConfigManager.load` resolves preferred port following `ONX_BACKEND_PORT` > `MCS_BACKEND_PORT` > `.onx/config.json` > `8000` with warning and fall-through on invalid values in `launcher.py`, `scripts/preflight.py`, and `scripts/preflight.sh`.
6. **Port range separation:** Preferred ports are validated to `1024..65535`; active-port reading, `can_bind`, and preflight active checks accept `1..65535` (D-6).
7. **Config non-persistence:** Environment overrides are never written to `.onx/config.json` by `ConfigManager.save()`; `LauncherConfig.configured_backend_port` defaults to `8000`; updating `backend_port` under an active env override sets `configured_backend_port` only, warns, and leaves the override intact.
8. **Reconciliation of all exits:** All 8 startup exit paths (`initial decision is None`, `ensure_python_environment()` is None, `pid is None`, `dead`+bindable, `timeout`, `next_decision is None`, `final exhaustion`, `KeyboardInterrupt` during attempt/wait per D-12, OWNER-CONFIRMED 2026-10-23) cleanly reconcile process state, eliminate recursive `ErrorHandler.show` retry loops, verify port release, report surviving processes and abort without escalating SIGKILL (D-10), and clear matching metadata (`_clear_backend_pid_if(None)` is a no-op). On `KeyboardInterrupt`, reconciliation runs first and the exception is then re-raised.
9. **SQLite concurrency protection & bind-race retry scope:** Startup retries apply strictly to failures diagnosed as bind races (D-7); retries abort immediately if an unresolved or project-owned listener remains on the attempted port (D-3, D-10); retries occur only when the port is free or occupied by a conclusively foreign process.
10. **Panel health requirement:** Status display and `SelfTester.run` require an open port and valid panel health signature (`check_backend_health`), never reporting a live wrapper alone as running. SelfTester asserts `SelfTestResult.status` and is isolated via a testable seam.
11. **Non-interactive refusal:** `ask_yes_no` returns `False` on `EOFError` and `KeyboardInterrupt` across all 3 callers.
12. **Test hardening and quality gates:** All new and updated unit/integration tests pass sequentially; tests enforce listener attribution preconditions, reset `ConfigManager` singleton between tests, use ephemeral ports, isolate state to `tmp_path`, and verify real subprocess/log behavior without mocks of the function under test (with the narrow exception for unresolved-ownership attribution). All 6 repository quality gates pass.

---

## Build Split (Batches B1 to B9)

Implementation must proceed in strict sequential batches, with test hardening embedded inside each batch:

### Batch B1: F1 - Stop Path Ownership Guards & Process Identity Revalidation
- **Target Files:** `launcher.py` (`cmd_stop`, `PortManager.kill_on_port`, `PIDManager`, `_clear_backend_pid_if`).
- **Scope:**
  - Define `_clear_backend_pid_if(expected_pid: int | None) -> None`: reads `backend.pid` and unlinks it only if matching `expected_pid`; if `expected_pid is None`, it is a no-op and never clears.
  - Add `expected_pid` and `expected_create_time` arguments to `PortManager.kill_on_port(port, expected_pid=None, expected_create_time=None)` (D-9).
  - In `cmd_stop`: ownership-gate active-port listener via `belongs_to_project(listener_pid)`; revalidate process identity (`create_time` in memory, D-9) before signaling; clear `.onx/backend.port`.
  - In `cmd_stop`: independently evaluate stored `backend.pid` fallback path; stop if project-owned (`belongs_to_project`), revalidate `create_time`, skip foreign/unresolved stored PIDs (D-8); clear matching `backend.pid` via `_clear_backend_pid_if`.
- **Tests Added/Updated:**
  - `test_cmd_stop_does_not_signal_foreign_listener_from_active_port` (merges `test_cmd_stop_clears_active_port_after_foreign_listener`, removing duplicate)
  - `test_cmd_stop_still_stops_project_owned_listener_from_active_port`
  - `test_cmd_stop_foreign_backend_pid_fallback_is_not_signalled`
  - `test_cmd_stop_unresolved_active_listener_does_not_fall_through_to_kill`
  - `test_cmd_stop_missing_port_file_stops_owned_backend_pid`
  - `test_cmd_stop_clears_backend_pid_only_if_matching_stopped_process`
  - `test_kill_on_port_rejects_mismatched_expected_pid`
  - `test_process_identity_helper_unit_and_drift` (helper unit cases: match, mismatch, unreadable/dead, and `expected_create_time is None` -> refuse; drift: launcher helper agrees with `backend/app/core/process_utils.py:_verify_process_identity` against a real child for match, mismatch, and dead PID, excluding the `None` case which is covered by the separate unit test; `tmp_path`/`monkeypatch` only, never the real `.onx`)
- **Gate Commands:** `cd backend && python -m pytest -q tests/test_launcher_dynamic_port.py`
- **Acceptance criteria:** AC-1, AC-2, AC-3.
- **Dependencies:** None.
- **Rollback:** Small revertable diff of `launcher.py` (`cmd_stop`, `kill_on_port`, `_clear_backend_pid_if`); revert the commit. Commits are local and unpushed at HEAD `5b775e4`.

### Batch B2: F2 - Log Append Semantics, File Identity Tracking & Attempt Marker Boundary - DONE (d357599)
- **Target Files:** `launcher.py` (`TerminalOpener._wrap_command`, `_read_backend_log_from`, `_wait_for_backend_attempt`, `start_backend`).
- **Scope:**
  - Change `_wrap_command` POSIX pipe to `tee -a`.
  - Implement `_stat_file_identity(path) -> tuple[int, int, int]`.
  - Update `_read_backend_log_from(identity)` and `_wait_for_backend_attempt(port, pid, timeout, log_identity)` signatures together.
  - Emit attempt boundary marker line FIRST before spawn, capture identity AFTER marker, and read from that offset forward.
  - Reset read offset to 0 on inode/device change or shrink between attempts; live rotation during attempt recorded as residual risk.
- **Tests Added/Updated:**
  - `test_backend_wrapper_uses_append_tee`
  - `test_backend_wrapper_appends_to_existing_log`
  - `test_wait_for_backend_attempt_detects_bind_error_when_log_shrank`
  - `test_wait_for_backend_attempt_detects_bind_error_on_inode_replacement`
  - `test_wait_for_backend_attempt_detects_bind_error_on_rotation_to_larger`
  - `test_wait_for_backend_attempt_excludes_stale_markers_from_older_attempts`
- **Gate Commands:** `cd backend && python -m pytest -q tests/test_launcher_dynamic_port.py`
- **Dependencies:** None.

### Batch B2b: F2b - Same-Inode Truncate/Regrow Detection - NOT BUILT
- **Target Files:** `launcher.py` (`_capture_attempt_marker`, `_read_backend_log_from`, `_wait_for_backend_attempt`, `start_backend`).
- **Scope:** Capture the marker line bytes after writing it; compare the bytes immediately before `saved_size` on every read; reset when mismatched or short. No new on-disk state.
- **Acceptance criteria:** AC: F2b acceptance paragraph (about spec line 268).
- **Tests Added/Updated:** `test_read_backend_log_from_detects_same_inode_truncate_regrow`, `test_read_backend_log_from_normal_append_not_reset`, `test_read_backend_log_from_intact_marker_not_reset`, `test_wait_for_backend_attempt_detects_bind_after_truncate_regrow`.
- **Gate Commands:** `cd backend && python -m pytest -q tests/test_launcher_dynamic_port.py`
- **Dependencies:** B2 (already committed d357599).
- **Rollback:** Small revertable diff of `launcher.py` (F2b marker capture and read guard); revert the commit. Commits are local and unpushed at HEAD `5b775e4`.

### Batch B3: F3 Launcher - Preferred Port Precedence, Fall-Through & Non-Persistence - DONE (cf827e8)
- **Target Files:** `launcher.py` (`LauncherConfig`, `ConfigManager.load`, `ConfigManager.update`, `ConfigManager.save`, `TerminalOpener.open_frontend`).
- **Scope:**
  - Add `configured_backend_port: int = BACKEND_PORT` to `LauncherConfig`.
  - Implement precedence in `ConfigManager.load`: `ONX_BACKEND_PORT` > `MCS_BACKEND_PORT` > `.onx/config.json` > `8000` with warning and fall-through on invalid values.
  - Validate preferred port to range `1024..65535` while preserving `1..65535` for active port and bind checks.
  - Update `ConfigManager.update()`: under active env override, set `configured_backend_port` only, warn, and leave effective `backend_port` intact.
  - Update `ConfigManager.save()` to persist `configured_backend_port`, never persisting env overrides.
- **Tests Added/Updated:**
  - `test_load_precedence_onx_over_mcs_and_file`
  - `test_load_precedence_mcs_over_file`
  - `test_load_invalid_env_is_ignored_with_warning`
  - `test_load_rejects_preferred_ports_outside_1024_65535`
  - `test_load_allows_active_ports_in_1_65535`
  - `test_save_does_not_persist_env_override`
  - `test_launcher_config_default_configured_backend_port`
  - `test_config_manager_update_sets_configured_backend_port`
  - `test_frontend_env_contains_active_backend_port`
- **Gate Commands:** `cd backend && python -m pytest -q tests/test_launcher_dynamic_port.py`
- **Dependencies:** None.

**Follow-up to B3:** `scripts/preflight.py` and `preflight.sh` F3 alignment was a separate batch (B4) and is now DONE in 5b775e4 (see Batch B4 below).

### Batch B4: F3 Preflight - Python/Bash Fall-Through Alignment & Resolver Helper - DONE (5b775e4)

Implemented in 5b775e4. Known minor difference: the Bash script reads .onx/config.json line-by-line with sed, so nested or next-line backend_port keys can differ from the Python JSON reader. Review: independent reviewer verdict PASS / SAFE TO COMMIT (121 passed, 1 skipped; Ruff baseline 14 = 14). Not pushed.

- **Target Files:** `scripts/preflight.py`, `scripts/preflight.sh`.
- **Scope:**
  - Add testable `resolve_preferred_backend_port() -> int` in `scripts/preflight.py`.
  - Fix short-circuit in Python preflight: fall through from invalid `ONX_BACKEND_PORT` to `MCS_BACKEND_PORT` to config to 8000 with warnings.
  - Fix bash preflight: fall through from invalid `ONX_BACKEND_PORT` to `MCS_BACKEND_PORT` to config to 8000 with warnings (replacing jump to 8000).
  - Apply range `1024..65535` to preferred port and `1..65535` to active port.
- **Tests Added/Updated:**
  - `test_preflight_resolve_preferred_backend_port`
  - Verification commands and recorded manual evidence (run-#2 preservation and invalid-env fall-through).
- **Gate Commands:** `python scripts/preflight.py && bash scripts/preflight.sh`
- **Dependencies:** B3.

### Batch B5: F4a - Startup Exit Reconciliation & Cleanup (All Exits, Provenance & Reuse)
- **Target Files:** `launcher.py` (`start_backend`, `_check_backend_provenance`, `_handle_own_unhealthy`).
- **Scope:**
  - Implement provenance helper `_check_backend_provenance(port, wrapper_pid, spawn_time) -> ProvenanceStatus` (returning `VERIFIED` or `UNKNOWN`).
  - Pass `expected_pid` and `expected_create_time` from `_handle_own_unhealthy` to `kill_on_port` (D-9).
  - Reconcile `initial decision is None`: clear active port, leave `backend.pid` untouched (`_clear_backend_pid_if(None)` is no-op), return False.
  - Reconcile `ensure_python_environment() is None`: clear active port, leave `backend.pid` untouched, return False.
  - Reconcile `pid is None`: track `previous_attempt_pid`; clear active port; clear `backend.pid` only if matching `previous_attempt_pid`.
  - Reconcile `dead` + bindable: remove recursive `ErrorHandler.show` retry callback; log crash diagnostics; clear matching `backend.pid` and active port; return False.
  - Reconcile `timeout`: adopt healthy project backend, kill proven attempt tree, or terminate wrapper PID and abort; clear matching metadata.
  - Wrap the attempt/wait section (live wait loop at `launcher.py:3110`) for `KeyboardInterrupt` (D-12, OWNER-CONFIRMED 2026-10-23): reconcile the spawned wrapper PID and matching `backend.pid` exactly like the timeout path (proven tree, never wrapper-as-root; D-2/D-10), clear matching metadata, then re-raise `KeyboardInterrupt`.
  - Reconcile `next_decision is None` and `final exhaustion`: clean matching metadata and return False.
  - Reconcile reuse metadata paths (`decision.reuse`): write stored PID only if project-owned and consistent with listener; otherwise write verified supervisor PID.
- **Tests Added/Updated:**
  - `test_start_backend_initial_decision_none_cleans_metadata`
  - `test_start_backend_python_env_none_cleans_metadata`
  - `test_start_backend_reuse_verifies_stored_pid_ownership`
  - `test_start_backend_writes_non_preferred_active_port_on_health`
  - `test_dead_bindable_failure_clears_matching_backend_pid_without_recursive_retry`
  - `test_pid_is_none_cleans_metadata`
  - `test_final_exhaustion_cleans_matching_backend_pid`
  - `test_next_decision_none_cleans_matching_backend_pid`
  - `test_timeout_stops_project_owned_attempt_and_clears_matching_backend_pid`
  - `test_timeout_does_not_signal_foreign_listener_and_stops_wrapper`
  - `test_start_backend_keyboardinterrupt_reconciles_then_reraises` (mutation-resistant; `tmp_path`/`monkeypatch`; never touches real `.onx`; injects `KeyboardInterrupt` during the attempt/wait section and asserts reconciliation of the spawned wrapper and matching `backend.pid` before the exception is re-raised)
- **Gate Commands:** `cd backend && python -m pytest -q tests/test_launcher_dynamic_port.py`
- **Acceptance criteria:** AC-8.
- **Dependencies:** B1.
- **Rollback:** Small revertable diff of `launcher.py` (`start_backend`, provenance/cleanup helpers); revert the commit. Commits are local and unpushed at HEAD `5b775e4`.

### Batch B6a: F4b1 - Startup Retry Reconciliation & Ownership Decision (D-7 / D-3)
- **Target Files:** `launcher.py` (`start_backend`, `_reconcile_failed_attempt`).
- **Scope:**
  - In retry loop: inspect occupant on attempted port before selecting next candidate.
  - Implement D-7 / D-3: retry applies ONLY to failures diagnosed as bind races (`outcome == "bind"` or `dead`+occupied); if listener ownership is UNRESOLVED -> abort startup immediately (never duplicate backend on SQLite); if owned listener cannot be stopped -> abort startup immediately; if free or foreign -> proceed to next candidate.
  - Ensure attempt 2+ uses short timeout `min(15, cfg.startup_timeout)`.
- **Tests Added/Updated:**
  - `test_start_backend_retries_on_real_bind_error_in_log`
  - `test_retry_aborts_when_listener_ownership_is_unresolved`
  - `test_retry_only_after_previous_foreign_occupant_is_ignored`
  - `test_retry_attempts_use_short_timeout`
- **Gate Commands:** `cd backend && python -m pytest -q tests/test_launcher_dynamic_port.py`
- **Acceptance criteria:** AC-9.
- **Dependencies:** B5.
- **Rollback:** Small revertable diff of `launcher.py` (`start_backend` retry loop, `_reconcile_failed_attempt`); revert the commit. Commits are local and unpushed at HEAD `5b775e4`.

### Batch B6b: F4b2 - Post-Kill Port-Freed Verification & Survivor Reporting Without Escalation (D-10)
- **Target Files:** `launcher.py` (`start_backend`, `_reconcile_failed_attempt`).
- **Scope:**
  - Verify port status after calling `kill_tree` via `can_bind` / `get_pid_by_port`.
  - Implement D-10: do NOT escalate SIGKILL to surviving descendants; report surviving untracked processes and abort startup.
- **Tests Added/Updated:**
  - `test_retry_aborts_when_previous_owned_listener_cannot_be_stopped`
  - `test_retry_verifies_port_freed_and_reports_survivors`
- **Gate Commands:** `cd backend && python -m pytest -q tests/test_launcher_dynamic_port.py`
- **Acceptance criteria:** AC-9.
- **Dependencies:** B6a.
- **Rollback:** Small revertable diff of `launcher.py` (`start_backend` post-kill verification, `_reconcile_failed_attempt`); revert the commit. Commits are local and unpushed at HEAD `5b775e4`.

### Batch B7: F5 - Status Display & SelfTester Listener/Panel Signature Gate
- **Target Files:** `launcher.py` (`StatusDisplay._collect_service`, `SelfTester.run`, `_backend_is_serving`).
- **Scope:**
  - Implement shared helper `_backend_is_serving(port: int, timeout: float = 1.0) -> bool`.
  - In `StatusDisplay._collect_service`: require `_backend_is_serving(effective_port)` for `verify_backend=True`; never treat live wrapper PID alone as running.
  - In `SelfTester.run`: require `_backend_is_serving(effective_backend_port)` for "Backend health" test result, inspecting `SelfTestResult.status`. Isolate via small testable seam or full network patching.
- **Tests Added/Updated:**
  - `test_status_reports_live_wrapper_without_listener_as_not_running`
  - `test_self_tester_run_backend_health_requires_listener`
  - `test_status_uses_healthy_active_port_file`
- **Gate Commands:** `cd backend && python -m pytest -q tests/test_launcher_dynamic_port.py`
- **Acceptance criteria:** AC-10.
- **Dependencies:** None.
- **Rollback:** Small revertable diff of `launcher.py` (`StatusDisplay._collect_service`, `SelfTester.run`, `_backend_is_serving`); revert the commit. Commits are local and unpushed at HEAD `5b775e4`.

### Batch B8: F6 - Non-Interactive EOF & KeyboardInterrupt Refusal Contract - DONE (f934a50)
- **Target Files:** `launcher.py` (`ask_yes_no`).
- **Scope:**
  - In `ask_yes_no`: catch `EOFError` and `KeyboardInterrupt` and return `False` unconditionally.
  - Preserve `default` return for interactive blank inputs (`Enter`).
  - Document behavior across all 3 callers (`ErrorHandler.show`, `_handle_own_unhealthy`, `start_frontend`).
- **Tests Added/Updated:**
  - `test_ask_yes_no_eof_returns_false_even_when_default_true`
  - `test_handle_own_unhealthy_eof_does_not_call_kill_on_port`
  - `test_error_handler_eof_does_not_retry`
  - `test_start_frontend_eof_does_not_kill_port`
- **Gate Commands:** `cd backend && python -m pytest -q tests/test_launcher_dynamic_port.py`
- **Dependencies:** None.

### Batch B9: Docs Patch - STATE.json, DEVELOPMENT.md, ADR-0019 & Parent Spec Amendments
- **Target Files:** `.ai/STATE.json`, `docs/DEVELOPMENT.md`, `docs/decisions/0019-dynamic-backend-port.md`, `docs/design/SPEC-2026-10-20-DYNAMIC-BACKEND-PORT-01.md`.
- **Scope:**
  - Dedicated docs-only patch: no code modifications to `launcher.py`.
  - Correct `.ai/STATE.json:159` claims regarding environment precedence and stop path foreign-listener safety.
  - Update `docs/DEVELOPMENT.md` local dev lines while strictly preserving Docker statements at `:8000` (line 225). Record `ConfigManager.save()` persisting `configured_backend_port`.
  - Record dead constants in `launcher.py:98-99` (`BACKEND_HEALTH_URL`, `SWAGGER_URL`) as a documentation note only.
  - Deliver parent spec and ADR-0019 documentation amendments for D-3 and D-7.
  - Cross-reference `SPEC-2026-10-20-DYNAMIC-PORT-FIXES-01`.
- **Tests Added/Updated:** Full quality gates run (`scripts/reverify`).
- **Gate Commands:** `scripts/reverify && cd backend && python -m pytest -q`
- **Dependencies:** all (B1 through B8 complete).
- **Rollback:** Docs-only revert of `.ai/STATE.json`, `docs/DEVELOPMENT.md`, ADR-0019, and the parent spec; revert the docs commit. Commits are local and unpushed at HEAD `5b775e4`.
