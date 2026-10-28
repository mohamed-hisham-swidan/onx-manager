# DESIGN SPEC - Dynamic Backend Port Selection (Launcher)

| Field | Value |
|---|---|
| Lane | B (Release Improvement) |
| Decision Level | D1 (multi-module startup contract; decision record required) |
| Status | IMPLEMENTED (local sequential suite + 6/6 gates + live verification 2026-10-20; CI/Windows pending) |
| Date | 2026-10-20 |
| HEAD | `14a441f` (`docs(design): add F1-2 promote atomicity and stop guard spec (v4 + binding review deltas)`) |
| Spec ID | `SPEC-2026-10-20-DYNAMIC-BACKEND-PORT-01` |
| Governance | `docs/governance/GOVERNANCE.md`; `.ai/RULES/core-principles.md`; `.ai/RULES/scope-and-implementation.md`; `.ai/RULES/testing-and-verification.md` |
| Mode | Design (v2) plus implementation (v3-v4). New files: this spec, `docs/decisions/0019-dynamic-backend-port.md`, `backend/tests/test_launcher_dynamic_port.py`. Modified: `launcher.py`, `scripts/preflight.sh`, `scripts/preflight.py`, `frontend/vite.config.ts`, `.ai/STATE.json`. No git writes. The worktree also carries unrelated uncommitted F1-2a work (see `git status`). |
| Revision | v4 (2026-10-20) |

---

## Revision Log

| Revision | Date | Summary |
|---|---|---|
| v1 | 2026-10-20 | Initial design draft based on a read-only RECON of `launcher.py`, `scripts/preflight.*`, `frontend/vite.config.ts`, and `backend/app/core/config.py`. Records the current live port conflict, the port-resolution design, propagation to Vite and the backend, tests, and open owner decisions. |
| v2 | 2026-10-20 | Applies the hard review. **MAJOR-1:** preflight now resolves and protects the active port in `check_services`, `check_db_lock`, `scan_orphans`, summary, and PID sync; foreign occupancy of the preferred port no longer makes preflight exit 1. **MAJOR-2:** fallback scanning now classifies every occupied candidate (including reuse of a healthy project backend) before spawning. **MAJOR-3/m2:** mutation row and interface cleanup. **M1:** corrected wording - an unresolvable PID skips the prompt, `kill_on_port` becomes a no-op, and startup fails at bind/timeout rather than killing. **M2:** retry failure discrimination no longer depends on wrapper death; per-attempt timeouts are defined. **M3:** explicit bash config parsing strategy. **M4:** preflight health uses the panel signature. **M5:** preference/active env meaning clarified. Minors: exact ownership markers, dirty-tree caveat, run-#2 live test, stop semantics, enum mapping, O-5. One additional conservatism fix: `HEALTHY_UNVERIFIED` is limited to unresolvable PIDs; a resolved non-project PID returning the panel signature is `FOREIGN` and is not reused (avoids proxying to another checkout's database). Owner decisions O-1..O-5 recorded as approved; ADR-0019 created. |
| v3 | 2026-10-20 | Implementation and live verification. Wired `start_backend` to `resolve_startup_port`, added bounded retry/per-attempt timeouts and `ONX_PANEL_BIND_PORT`; propagated the active port to Vite, status, Swagger, and ReadyScreen; added `--stop` supervisor-tree cleanup and active-port clearing. Updated preflight (bash + Windows Python) for config precedence, panel-signature health, active-port protection, ancestor protection, and foreign-not-unclean summaries. Added `exclude_ports` for retries and three start-path tests. Live: backend on 8001 while 8000 is foreign, run-#2 reuse, preflight preservation, stop cleanup, and Vite `/health` proxy verified. Windows remains UNVERIFIED. |
| v4 | 2026-10-20 | Status correctness and final local verification. `--status` now reports the backend as running only when the panel health signature validates; `get_effective_backend_port` trusts `.onx/backend.port` only when that signature is healthy, so a foreign listener on the preferred port is not shown as our backend. Added 2 tests (25 total in `test_launcher_dynamic_port.py`). Evidence: sequential backend suite 3282 passed / 6 skipped / 0 failed (3288 collected, 1006.55s); frontend 767 passed across 90 files; 6/6 quality gates PASS via `scripts/reverify`. CI and Windows remain UNVERIFIED. |
| v5 | 2026-10-28 | Document amendments for D-3, D-7, and D-10 per `SPEC-2026-10-20-DYNAMIC-PORT-FIXES-01`. Record dead constants `BACKEND_HEALTH_URL` and `SWAGGER_URL` in `launcher.py:98-99` marked for cleanup. |

---

## Goal

When the launcher starts and the preferred backend port (`8000` by default) is held by a **live process that does not belong to this project**, the launcher must:

1. leave that process untouched, and
2. start the backend on the next available port,
3. with every development-time consumer using that same port.

The launcher must still clean up genuinely dead/stale project state (dead PID files, orphaned project listeners) and must still reuse an already-running, healthy project backend instead of launching a second instance.

Reuse is not limited to the preferred port. On a second run the healthy backend may be sitting on a fallback port (for example `8001`) while the preferred port `8000` is still foreign-held. The launcher must recognize and reuse `8001` via `.onx/backend.port` (or by classifying the candidate) before scanning for a new port.

### Why fallback rather than kill

The current launcher offers to kill a resolvable occupant, aborts if the operator declines, and proceeds into a doomed bind when the listener PID is unresolvable (`kill_on_port` is a no-op when `get_pid_by_port` returns `None`). On a developer host the occupant is frequently another unrelated service; killing it is destructive and surprising, and failing on it is unnecessary. The requested behavior is to coexist.

### Why not simply "always pick another port when occupied"

Two backend processes sharing the same SQLite database are unsafe. Therefore a live **project-owned** backend is an exception: if it is healthy it is reused; if it is unhealthy the launcher must resolve it (kill with confirmation) or abort, never silently start a duplicate on a different port. See [Port classification](#port-classification) and [Resolution order](#resolution-order).

---

## Non-Goals and Out of Scope

- Docker/container behavior. The container image deliberately binds `8000` internally (`backend/Dockerfile`), nginx proxies to `backend:8000` (`frontend/nginx.conf:1-2`), and Compose publishes a fixed port (`docker-compose.yml`). Host-side Compose port conflicts are not launcher scope.
- Making the production frontend discover the backend port dynamically. The built frontend uses same-origin requests (`frontend/src/services/api.ts:130-136`, `frontend/src/components/WebSocketManager.tsx:85`), so production needs no change.
- Frontend port selection. The launcher's frontend readiness check uses the module constant `FRONTEND_PORT` instead of `cfg.frontend_port` (`launcher.py:2276-2277`), and Vite may auto-increment away from `5173`. That is a separate, pre-existing defect. This spec records it as finding **F-PORT-FRONTEND-01** and does not fix it.
- A launcher singleton lock. Two launchers racing each other is not solved here; it is recorded as a residual risk.
- Changing the backend's bind host. The launcher keeps `--host 0.0.0.0` (`launcher.py:1041-1049`).

---

## Current Behavior (verified at HEAD `14a441f`)

### Startup sequence

1. `start.sh` runs the preflight script when it is executable (`start.sh:122-132`). On Windows, `start.ps1` runs `scripts/preflight.py` best-effort (`start.ps1:532-545`).
2. Preflight resolves the port as `ONX_BACKEND_PORT`, then `MCS_BACKEND_PORT`, else `8000` (`scripts/preflight.sh:30-31`, `scripts/preflight.py:67-68`). It does not read `.onx/config.json`.
3. For an occupied backend port, preflight preserves it only when `GET /health` (or the authenticated `/api/v1/health`) returns HTTP 200 (`scripts/preflight.sh:260-287`, `290-308`; `scripts/preflight.py:436-441`, `515-529`). Otherwise it calls `kill_safe`; a foreign `401` therefore reaches the kill path but is refused by ownership checks.
4. `kill_safe` refuses to kill a process that is not recognized as project-owned (`scripts/preflight.sh:159-180`, `scripts/preflight.py:450-480`). So preflight does **not** kill a foreign listener; it logs a warning and continues.
5. `launcher.start_backend` (`launcher.py:2554-2636`) then decides what to do:
   - stored PID alive **and** port open -> logs "already running" and returns success (`:2555-2558`);
   - port open and health 200 -> adopts the listener PID and returns success (`:2560-2566`);
   - port open otherwise -> when `get_pid_by_port` resolves a PID, prompts to kill it and aborts on refusal; when it returns `None`, the prompt is skipped and `kill_on_port` is a no-op (`:2568-2575`);
   - then launches uvicorn on `cfg.backend_port` (`:2592-2600`) and waits for health.
6. The backend port is never renegotiated and never recorded separately from the configured value.
7. Preflight's summary treats any unrecognized listener on the preferred port as `in use (unclean)` and exits 1 (`scripts/preflight.sh:471-557`), which makes `start.sh` abort before the launcher runs. A fallback design that leaves a foreign listener in place is therefore unreachable on Linux without a summary-semantics change.
8. A healthy backend on a fallback port is not protected by preflight: only the preferred port is scanned for protection (`scripts/preflight.sh:260-308`), while `scan_orphans` (`:377-430`) and `check_db_lock` (`:334-375`) can kill it. This is validated in the [Preflight active-port protection](#preflight-active-port-protection) section.

### Current defects that block any port change

| ID | Fact | Evidence |
|---|---|---|
| C1 | Health URL is frozen from the `8000` constant at import, not from `cfg.backend_port`. A configured non-8000 port already fails the health wait. | `launcher.py:87-91`, `2263-2273` |
| C2 | `start_backend` trusts `backend.pid` liveness plus any listener on the preferred port, without verifying the listener belongs to this project. The stored PID is the terminal wrapper on Linux (`konsole`), not uvicorn. | `launcher.py:2555-2558`, `1032-1051`, `1063-1121` |
| C3 | `PortManager.find_free` exists but is unused, and its exhausted-range fallback returns `start + 1000` without checking that port. | `launcher.py:755-759`; repo-wide grep shows no caller |
| C4 | Vite proxies all dev traffic to a hard-coded `localhost:8000`. | `frontend/vite.config.ts:14-19` |
| C5 | The launcher starts the frontend without any port environment (`env=None`). | `launcher.py:1054-1060`, `1063-1078` |
| C6 | The backend freezes its panel port from settings (`panel_bind_port`, default `8000`; `ONX_PANEL_BIND_PORT`/`MCS_PANEL_BIND_PORT` supported) at lifespan start, regardless of the actual uvicorn `--port`. | `backend/app/main.py:82`; `backend/app/core/config.py:51-52`, `66-80`, `212-257` |
| C7 | Exposure features (Cloudflare ingress, playit, UPnP) read the frozen panel bind, so a backend on another port would still publish `127.0.0.1:8000`. | `backend/app/modules/exposure/application/commands.py:1502`, `1631`, `1772`, `1926` |
| C8 | Browser and Swagger URLs are prebuilt constants. | `launcher.py:89-91`, `2760`, `2769` |
| C9 | `--status` always reads the configured port; it has no knowledge of a fallback port. | `launcher.py:1689-1767` |
| C10 | Preflight and launcher can disagree: preflight reads environment only; the launcher reads `.onx/config.json` and never exports the env. | `scripts/preflight.sh:30-31`; `scripts/preflight.py:67-68`; `launcher.py:548-556` |
| C11 | Preflight summary marks a foreign live listener on the preferred port as `in use (unclean)` and exits 1, aborting `start.sh` before the launcher can fall back. | `scripts/preflight.sh:471-557`; `scripts/preflight.py:671-739`; `start.sh:122-129` |
| C12 | A healthy project backend running on a fallback port is not protected: protection is populated only from the preferred port, and `check_db_lock`/`scan_orphans` then kill the unprotected backend. | `scripts/preflight.sh:290-308`, `334-430`; `scripts/preflight.py:515-529`, `543-616` |

### Live evidence observed this session (FACT)

- Port `8000` was occupied by a live non-project service returning `HTTP 401` with `WWW-Authenticate: Bearer resource_metadata="/.well-known/oauth-protected-resource"` for `/health`.
- `.onx/logs/backend.log` ended with `ERROR: [Errno 98] Address already in use`; uvicorn never started.
- `.onx/backend.pid` contained `644031`, the live `konsole` wrapper for that failed launch. Because of C2, the launcher would report "Backend already running" if port 8000 were open and that wrapper alive, although the real backend is dead.
- The existing project backend is unauthenticated at `/health` (`backend/app/main.py:460-476`), so a `401` is also a reliable signal that the listener is not this backend's health contract under normal conditions.

---

## Design Overview

### Terms

- **Preferred port**: the operator-configured port. Precedence: `ONX_BACKEND_PORT` > `MCS_BACKEND_PORT` > `.onx/config.json` `backend_port` > `8000`. This matches preflight's existing environment names and removes C10.
- **Active port**: the port actually used by the current backend process. It may equal or differ from the preferred port. It is runtime state, not configuration.
- **Project-owned listener**: a process whose command line/executable identifies this repository or this application, using the **exact** preflight definition, not a new one:
  - exclusions first: `playit`, `cloudflared`, `tmux`, `java`, and `_DAEMON_KEYWORDS` (`scripts/preflight.sh:84-127`, `scripts/preflight.py:343-380`);
  - exclusions for anything under `backend/data/servers/`;
  - then any of: project root path in cwd/cmdline, `onx-frontend`, `mcs-frontend`, `onx-manager`, `mcs-manager`, `app.main:app`.
- **Our backend**: a listener that is project-owned and whose `GET /health` returns the panel health JSON (`status == "ok"` and a `version` field). This signature is defined by `backend/app/main.py:460-476`.
- **Dead process**: a PID file whose PID is no longer alive, or a listener that no longer exists. Dead project state is cleaned; the port is then reusable.

### Port classification

`classify_backend_port(port)` is the single classifier used for the active-port file, the preferred port, and every fallback candidate:

1. If `can_bind(port)` succeeds -> `FREE`.
2. Resolve `listener_pid = get_pid_by_port(port)` and probe the panel health signature (2 s on the preferred/active port, 1 s during scanning).
3. Map the evidence to the enum:

| Listener ownership | Panel health signature | Enum |
|---|---|---|
| No listener (bindable) | n/a | `FREE` |
| Project-owned | Valid | `OWN_HEALTHY` |
| Project-owned | Invalid or unavailable | `OWN_UNHEALTHY` |
| Not project-owned, PID resolved | Valid | `FOREIGN` (signature/ownership contradiction; likely another checkout) |
| Not project-owned, PID resolved | Invalid | `FOREIGN` |
| PID unresolved | Valid | `HEALTHY_UNVERIFIED` |
| PID unresolved | Invalid | `UNKNOWN` |

`HEALTHY_UNVERIFIED` is reusable with a warning **only when the PID cannot be resolved**, so ownership cannot be checked; the panel signature is then the only evidence. A resolved PID that fails the ownership markers is treated as `FOREIGN` even if it returns the panel signature: reusing it could silently proxy the frontend to another checkout's database. `FOREIGN` and `UNKNOWN` are never signalled and are never reused.

> **Amendment under D-3 (`SPEC-2026-10-20-DYNAMIC-PORT-FIXES-01`):**
> An `UNKNOWN` occupant (unresolved PID with invalid or unavailable panel signature) remaining on an attempted port blocks any subsequent candidate retry and causes startup to abort immediately. The launcher must never spawn another backend on a subsequent candidate port that could concurrently access the SQLite database while an unresolved occupant remains.

### Resolution order

Evaluation runs once per launcher start, before any spawn:

0. **Known active port.** Read `.onx/backend.port` (legacy fallback `.mcs/backend.port`). If it holds a valid integer, classify that port:
   - `OWN_HEALTHY` or `HEALTHY_UNVERIFIED` -> **reuse immediately**. This is the run-#2 path: preferred `8000` is foreign-held but the healthy backend is on `8001`. Stop resolving.
   - `OWN_UNHEALTHY` -> apply the own-unhealthy policy below. After a confirmed stop, continue resolution.
   - `FREE`, `FOREIGN`, `UNKNOWN` -> the file is stale/irrelevant; log and clear it, then continue.
1. **Preferred port.** Classify it:
   - `FREE` -> use it.
   - `OWN_HEALTHY` / `HEALTHY_UNVERIFIED` -> reuse it (no spawn).
   - `OWN_UNHEALTHY` -> own-unhealthy policy; after a confirmed stop, re-classify and use if free, otherwise abort.
   - `FOREIGN` / `UNKNOWN` -> fallback scan.
2. **Fallback scan** over `preferred + 1 .. preferred + 99`. Every occupied candidate is classified; it is never skipped unconditionally:
   - `FREE` -> select it and spawn.
   - `OWN_HEALTHY` / `HEALTHY_UNVERIFIED` -> **reuse that port; do not spawn**.
   - `OWN_UNHEALTHY` -> own-unhealthy policy; if stopped, the port is now free and is selected; if declined, abort (do not skip to another port).
   - `FOREIGN` / `UNKNOWN` -> continue scanning.
3. No eligible port -> abort with the preferred port, ports tried, and likely holder. Clear runtime metadata.

### Own-unhealthy policy (all states)

Prompt to stop the project-owned listener (existing default: yes). If the operator declines or the process cannot be stopped, abort with an explanation that a second backend would share the SQLite database. If it stops, re-classify and continue. The launcher never spawns while a project-owned listener is alive.

### Fallback selection

- Scan range: `preferred + 1 .. preferred + 99` inclusive (`PORT_SCAN_SPAN = 100`), clamped to `1024..65535`. Unlike the current `find_free` fallback, no port is returned without a successful bind probe.
- Candidate probe: `PortManager.can_bind(port, host="0.0.0.0")` using an actual `socket.bind` probe that mirrors uvicorn's IPv4 bind. On POSIX, set `SO_REUSEADDR` on the probe socket to match uvicorn; do not set reuse flags on Windows.
- Only occupied candidates incur a health probe; the first candidate is normally the only one. A scan full of foreign listeners therefore costs at most 1 s per occupied port, bounded by the 100-port span.
- After a candidate is selected, a TOCTOU race is still possible between the probe and uvicorn's bind. This is handled by the bounded retry below.

### Bounded bind-race retry and per-attempt failures

Total launch attempts: `MAX_PORT_ATTEMPTS = 3` (initial + up to 2 retries).

Failure detection does **not** depend on the wrapper PID dying. On Linux the wrapper is `konsole --hold` (`launcher.py:944`) and survives uvicorn; the existing "Backend process died" branch (`launcher.py:2611-2626`) is therefore not a reliable crash discriminator on Linux.

Each attempt captures the current size of `.onx/logs/backend.log` before spawning and then watches:

1. Health success -> attempt succeeds.
2. New log bytes contain a bind marker (`Address already in use`, `Errno 98`, `WinError 10048`, `Only one usage of each socket address`) -> bind failure; retry with the next candidate.
3. The wrapper is dead **and** the selected port is now bindable -> non-bind failure; do not retry.
4. The wrapper is dead **and** the selected port is occupied -> bind race; retry.
5. Attempt deadline reached with no health and no bind evidence -> generic startup timeout; do not retry, and report timeout rather than claiming a crash.

> **Amendment under D-3 and D-7 (`SPEC-2026-10-20-DYNAMIC-PORT-FIXES-01`):**
> If rule 2 or rule 4 diagnoses a bind race, the occupant on the attempted port must be inspected before retrying. If ownership of the occupant is unresolved (`UNKNOWN`) or a project-owned process survives, the launcher must NOT retry on the next candidate and must abort immediately to protect SQLite database integrity. Retrying on the next candidate port is permitted only when no listener remains on the attempted port (`can_bind` succeeds) or the occupant is conclusively proven foreign. Generic crashes (rule 3) and timeouts (rule 5) remain non-retryable.

Per-attempt timeout budget:

| Attempt | Timeout |
|---|---|
| Initial | `cfg.startup_timeout` (default 120 s) |
| Retry 1 | `min(15 s, cfg.startup_timeout)` |
| Retry 2 | `min(15 s, cfg.startup_timeout)` |

Worst case is 150 s at defaults, not 3 x 120 s. Retries are only entered after a bind diagnosis; a genuine application crash is not retried. On Linux the log is reliable because the terminal wrapper pipes through `tee` (`launcher.py:950-954`); on Windows' terminal path there is no tee, so rules 3-4 provide the discriminator. A failed Linux attempt may leave an extra `konsole --hold` window containing the error; this is accepted and logged.

### Runtime state and persistence

- Preferred port stays in `.onx/config.json` (`launcher.py:548-572`). Fallback ports are **not** written there, so a later start retries the preferred port first.
- New runtime file: `.onx/backend.port`, containing the active port as decimal text. Written only after a successful health check; removed by `--stop`, on a failed startup, and when stale metadata is cleaned.
- Status, self-test, and preflight read `.onx/backend.port` (legacy `.mcs/backend.port` fallback). Preflight never writes or deletes it; the launcher owns it.
- Status and self-test trust the file only if it contains a valid port and a listener/panel signature exists; otherwise they fall back to the configured preferred port.
- `LauncherConfig` gains a non-persisted `active_backend_port: int | None = None` field. `ConfigManager.save()` already writes an explicit key list (`launcher.py:560-572`), so this field is not serialized.
- `start_backend` sets `cfg.active_backend_port`; `cmd_start` uses it for Swagger, `ReadyScreen`, and later consumers.
- `--stop` clears the active-port file. It terminates uvicorn because `PIDManager.kill_tree` explicitly enumerates and signals the recorded PID's descendants (`launcher.py:649-706`), not because the `konsole --hold` wrapper dies. Depending on the run, `backend.pid` holds either the wrapper PID (written at spawn, `launcher.py:2601`) or the listener PID (rewritten after health, `:2632`); both paths terminate the tree.

### Propagation

| Consumer | Change |
|---|---|
| Uvicorn | Launch with the resolved active port (existing `open_backend(..., port, ...)`). |
| Backend panel bind | Add `ONX_PANEL_BIND_PORT=<active>` to the backend environment, alongside the existing `PYTHONPATH` and `ONX_DATABASE_URL` (`launcher.py:2586-2593`). `AppSettings` honors `ONX_PANEL_BIND_PORT` (`backend/app/core/config.py:66-80`), and `init_active_panel_bind()` reads it at lifespan start (`backend/app/main.py:82`). No backend source change is required for the primary path. |
| Vite dev proxy | `frontend/vite.config.ts` reads `process.env.ONX_BACKEND_PORT` (default `8000`) and builds the `http://` and `ws://` targets for `/api`, `/ws`, `/health`, `/docs`, `/openapi.json`. |
| Frontend launch | `open_frontend(backend_port: int)` passes `{"ONX_BACKEND_PORT": str(backend_port)}` to `_open(...)` instead of `None`. |
| Health probes | `check_backend_health(port: int)`; URL built as `http://127.0.0.1:{port}/health` (explicit IPv4 to match the `0.0.0.0` bind; avoids `localhost` resolving to `::1`). |
| Browser/Swagger/ReadyScreen | Use the resolved active port (Swagger) and configured frontend port (browser/ReadyScreen), not module constants. |
| Status/self-test | Prefer the active-port file as described above. |
| Preflight (Linux/Windows) | Resolve preferred with the same precedence, resolve/protect the active port, classify health by the panel signature, and stop treating foreign preferred occupancy as unclean. Full contract in [Preflight active-port protection](#preflight-active-port-protection). |

Environment precedence is evaluated by the launcher and by preflight, both operating in the parent process. `ONX_BACKEND_PORT` therefore means **operator preference** there. The launcher never mutates its own `os.environ`; it passes the **active** port to children through the `Popen` environment only (Vite and, as `ONX_PANEL_BIND_PORT`, the backend). A child seeing `ONX_BACKEND_PORT` is seeing the active value, not necessarily the preference.

### Preflight active-port protection

This section closes MAJOR-1 and C11/C12. Without it, run #1 starts the backend on `8001`, and run #2's preflight kills that healthy backend before the launcher can reuse it.

**Port resolution (both scripts).**

- `PREFERRED_BACKEND_PORT`: `ONX_BACKEND_PORT` > `MCS_BACKEND_PORT` > `.onx/config.json` `backend_port` > `8000`.
- `ACTIVE_BACKEND_PORT`: read `.onx/backend.port`, then legacy `.mcs/backend.port`; accept only a decimal integer in `1..65535`. The value is trusted only when a listener exists on that port; otherwise it is treated as stale and ignored (preflight does not delete it; the launcher owns that file).
- Bash config parsing (M3): no `jq` and no Python dependency. Use a strict single-key extraction on the launcher-written file:

  ```bash
  sed -nE 's/.*"backend_port"[[:space:]]*:[[:space:]]*([0-9]+).*/\1/p' .onx/config.json | tail -n 1
  ```

  Validate the result as an integer in `1..65535`; absent/malformed -> default. `ConfigManager.save()` writes `json.dumps(..., indent=2)` (`launcher.py:560-572`), so the token is stable. This is deliberately not a general JSON parser; it is a one-key reader for a file this project writes. `preflight.py` uses `json.load`.
- `.mcs` legacy paths remain supported exactly as `cleanup_pid_files` already does.

**Health definition (M4).**

Preflight must use the same panel signature as the launcher, not "any 2xx":

- Bash: `curl -fsS --max-time 2 "http://127.0.0.1:${port}/health"`, then require a JSON object with `"status": "ok"` and a `"version"` key (whitespace-tolerant grep). Do not fall back to `/api/v1/health`; that route is authenticated (`backend/app/api/v1/middleware/auth.py:12-27`) and returns 401 without a token.
- Python: `urllib.request` plus `json.loads`, require `status == "ok"` and `"version" in payload`.

Consequences: a foreign service returning 200 is not labeled "healthy backend", and the launcher/preflight verdicts no longer contradict each other.

**`check_services`.**

1. If `ACTIVE_BACKEND_PORT` differs from preferred and has listeners:
   - signature valid -> `protect_family` (protects the listener, its children, and a project-owned parent) and log `Active backend on port <active> (PID ...)`.
   - signature invalid and project-owned -> normal `kill_safe` policy (stale/hung backend; safe to stop).
   - foreign/unknown -> leave untouched (never kill).
2. Preferred port handling is unchanged for project-owned listeners, but the "healthy" branch additionally requires project ownership or the panel signature; a foreign listener is never killed.
3. `FORCE_CLEAN` (`--stop`, `--restart`, `--force`) continues to bypass preservation. That is intended: restart should stop the backend.

**`check_db_lock`.**

- Bash already preserves any PID in `PROTECTED_PIDS` (`scripts/preflight.sh:334-375`); protecting the active port first is sufficient.
- Python must not compare against the preferred port only. It checks whether any SQLite-lock holder is a protected listener on either `PREFERRED_BACKEND_PORT` or `ACTIVE_BACKEND_PORT` with a valid signature, and preserves the lock in that case (`scripts/preflight.py:543-579`).

**`scan_orphans`.**

- In addition to skipping `_protected_pids`, explicitly skip any PID that is listening on `ACTIVE_BACKEND_PORT` or `PREFERRED_BACKEND_PORT` and has a valid panel signature. This is belt-and-braces against ordering regressions and is required by MAJOR-1.
- `scan_orphans` must not classify the active listener as an "inactive/duplicate orphan" merely because it does not hold the preferred port.

**`cleanup_pid_files`.**

- When syncing `backend.pid`, prefer the listener on `ACTIVE_BACKEND_PORT`, then the preferred port. Do not write, delete, or rewrite `backend.port` from preflight.

**Summary and exit code.**

- Preferred backend row:
  - free -> `free`;
  - ours healthy -> `running (healthy)`;
  - foreign or ownership-unknown -> `in use (foreign; launcher will use another port)`, **not unclean**;
  - project-owned unhealthy that could not be stopped -> unclean (via `FAILED_ANY`).
- Active backend row (when different): `running (healthy) on <active>` or `stale`.
- A foreign listener alone must never set `any_unclean`; this is the C11 fix that makes `start.sh` reach the launcher.

### Logging and UX

- Fallback: one warning line, for example `Port 8000 is in use by PID 1234 (foreign process); using 8001 instead.` Include the first 100 characters of the detected command line when available.
- Reuse: `Backend already running and healthy on port 8001 (PID ...)`; when reusing via `.onx/backend.port`, say so explicitly.
- Own-unhealthy abort: state that the listener is project-owned and that starting a second backend would share the SQLite database, then give the manual stop command.
- Retry: `Port 8001 became unavailable during startup; retrying on 8002 (attempt 2/3).`
- `ReadyScreen` shows the actual active backend URL and, when it differs from preferred, a line `Preferred port 8000 unavailable; using 8001`.
- Preflight summary distinguishes `running (healthy)`, `in use (foreign; launcher will use another port)`, and `in use (project-owned, unhealthy)`.
- No new silent behavior: every fallback path logs, and `--status` shows the active port.

---

## Interfaces and Contracts

### New/changed launcher interfaces

```python
class PortState(Enum):
    FREE = auto()
    OWN_HEALTHY = auto()
    OWN_UNHEALTHY = auto()
    HEALTHY_UNVERIFIED = auto()
    FOREIGN = auto()
    UNKNOWN = auto()

@dataclass(frozen=True)
class PortDecision:
    port: int
    reuse: bool
    source: str                 # "known-active" | "preferred" | "scan"

class PortManager:
    @staticmethod
    def can_bind(port: int, host: str = "0.0.0.0") -> bool: ...

    @staticmethod
    def belongs_to_project(pid: int) -> bool: ...

    @staticmethod
    def classify_backend_port(port: int, health_timeout: float = 2.0) -> PortState: ...

    @staticmethod
    def resolve_startup_port(
        preferred: int,
        known_active: int | None,
        on_own_unhealthy: Callable[[int], bool],
    ) -> PortDecision | None:
        """Apply the resolution order. Never signals directly; the callback
        owns the own-unhealthy prompt and returns True only if the port was freed."""

def check_backend_health(port: int) -> bool: ...          # existing name, new parameter; requires panel signature
def backend_health_url(port: int) -> str: ...

def open_frontend(backend_port: int) -> int | None: ...    # new parameter

@dataclass
class LauncherConfig:
    ...
    active_backend_port: int | None = None                 # runtime only
```

Preflight exposes the same resolution inputs without importing launcher (preflight must run before the venv). Its contract is the `.onx/backend.port` file, the `.onx/config.json` one-key read, and the panel health signature described above - not a shared Python module.

`PIDManager` gains helpers for the active-port file, mirroring the existing PID helpers:

```python
PIDManager.write_active_port(port: int) -> None
PIDManager.read_active_port() -> int | None
PIDManager.clear_active_port() -> None
```

### Environment contract (dev only)

| Variable | Set by | Read by | Meaning |
|---|---|---|---|
| `ONX_BACKEND_PORT` | operator | launcher preferred resolution, preflight | Requested (preferred) backend port |
| `ONX_BACKEND_PORT` | launcher, child env only | Vite config in `npm run dev` | Active backend port for the dev proxy |
| `MCS_BACKEND_PORT` | operator | launcher, preflight | Legacy alias for the preferred port |
| `ONX_PANEL_BIND_PORT` | launcher, backend child env only | `AppSettings` / `get_panel_bind()` | Actual backend port for exposure features |

The launcher does not mutate its own environment; the active value is scoped to each child process. If a future consumer reads `ONX_BACKEND_PORT` from the launcher's environment, it sees the operator preference, not the active port.

Production containers keep `MCS_PANEL_BIND_PORT=8000` from `backend/Dockerfile`; the launcher never runs inside the container.

### Runtime file

`.onx/backend.port`:

- Format: decimal integer plus trailing newline.
- Lifetime: written after health success, cleared on stop/failure/stale cleanup.
- Not committed; `.onx/` is already runtime state.

---

## Failure and Edge Cases

| Case | Expected behavior |
|---|---|
| Preferred port free | Use it; no behavior change. |
| Foreign listener on preferred | Fallback, no signal, warning includes PID/cmdline if known. Preflight does not mark this unclean. |
| Foreign listener on a fallback candidate | Continue scanning; never signal it. |
| Healthy project backend on a fallback candidate | Reuse it; no spawn. This is mandatory even when `.onx/backend.port` is missing (MAJOR-2). |
| Healthy project backend named by `.onx/backend.port` | Reuse it immediately; run-#2 path. |
| Project backend on the preferred port | Reuse when healthy; own-unhealthy policy when not. |
| Project backend on a fallback candidate, unhealthy | Own-unhealthy policy; on decline abort rather than skipping to another port. |
| `backend.pid` points to a live terminal wrapper with no listener | Clear PID/active metadata without killing the wrapper; continue resolution. |
| `backend.pid` dead | Remove stale files; continue resolution. |
| Listener PID unresolvable, health 401/foreign | Fallback with ambiguity warning; never kill. |
| Listener PID unresolvable, panel signature valid | `HEALTHY_UNVERIFIED`; reuse with a warning (cannot prove ownership, but the signature is the panel contract). |
| Health 200 with foreign JSON | `FOREIGN`; fallback. |
| Race: candidate taken between probe and bind | Bounded retry (max 3 attempts, total <= 150 s at defaults) using the next candidate. |
| Genuine backend crash (non-bind, wrapper dead and port free) | No port retry; report the failure through the existing error path. |
| Deadline reached with no health and no bind evidence | Generic startup timeout; no port retry; do not claim a crash. |
| All 100 candidates occupied | Abort with actionable message; clear active metadata. |
| Frontend fails after backend succeeded | Preserve current behavior (backend left running); active-port file remains valid; report failure. |
| `--restart` while a foreign process still holds preferred | Stop clears active metadata; start re-resolves and falls back again. |
| Run #2: foreign holds preferred, healthy backend on fallback | Preflight protects the active listener; launcher reuses it; no new process. |
| `--status` with a stale active-port file | Validate listener/signature; else display preferred port. |
| Concurrent launcher invocations | Not solved (no singleton lock). Residual risk. |
| IPv6-only listener on preferred | `can_bind("0.0.0.0", preferred)` detects the conflict where the OS makes IPv4 unavailable; otherwise uvicorn's bind error triggers the bounded retry. |

---

## Affected Components

| File | Change |
|---|---|
| `launcher.py` | Port resolution/ownership/health helpers; `start_backend` decision table; backend/frontend env propagation; active-port persistence; status/self-test/ReadyScreen/Swagger use resolved port; remove reliance on import-time URLs. |
| `frontend/vite.config.ts` | Proxy targets from `process.env.ONX_BACKEND_PORT`, default `8000`. |
| `scripts/preflight.sh` | Preferred-port precedence includes `.onx/config.json`; read and protect `.onx/backend.port` in `check_services`, `check_db_lock`, `scan_orphans`, `cleanup_pid_files`, and summary; panel-signature health; foreign preferred is not unclean. |
| `scripts/preflight.py` | Same contract on Windows, with `json.load` for config and active-port protection in all phases. |
| `backend/app/main.py` / `backend/app/core/config.py` | No primary-path change; `ONX_PANEL_BIND_PORT` already exists. Add a regression test for the env contract. |
| `backend/tests/test_launcher_dynamic_port.py` | New unit tests (see below). |
| `backend/tests/test_launcher_prerequisites.py` | Unchanged; must remain green. |
| `docs/DEVELOPMENT.md` | Implementation follow-up: document fallback behavior and the active-port file. |
| `.ai/STATE.json` | Implementation follow-up only: add a D1 item with status per the ladder. This design session does not edit state. |

### Implementation order

1. Add `PortState`, `PortDecision`, `classify_backend_port`, `resolve_startup_port`, and the `PIDManager` active-port helpers behind tests; do not wire them into startup yet.
2. Rewrite `start_backend` to use `resolve_startup_port`, parameterize health checks by port, and add bounded retry + per-attempt logging. Keep `--stop` behavior, then clear the active-port file.
3. Propagate the active port: backend env (`ONX_PANEL_BIND_PORT`), frontend env (`ONX_BACKEND_PORT`), Vite config, Swagger/ReadyScreen/status.
4. Update `scripts/preflight.sh`, then `scripts/preflight.py`, against the same contract; verify preflight before launcher.
5. Add/adjust tests, run the six gates, then run the live verification scenarios including run #2.
6. Keep `docs/decisions/0019-dynamic-backend-port.md` current, update `docs/DEVELOPMENT.md`, and record the verified state.

---

## Tests

All launcher tests live under `backend/tests/` so the existing suite discovers them (the repository root is added to `sys.path` in `backend/tests/test_launcher_prerequisites.py:7-13`).

### New unit tests: `backend/tests/test_launcher_dynamic_port.py`

Mock `PortManager`/`PIDManager`/health probes; do not bind real ports except in the dedicated probe test.

1. `test_preferred_port_free_uses_preferred`.
2. `test_foreign_live_port_falls_back_and_never_signals` (assert `kill_on_port` is not called).
3. `test_foreign_health_200_wrong_payload_falls_back`.
4. `test_own_healthy_backend_is_reused`.
5. `test_reuse_probes_active_port_with_non_default_preferred` - set preferred to `8123`, mock the listener/health on `8123`; a revert to the constant `8000` URL must fail this test (MAJOR-3).
6. `test_known_active_healthy_reused_when_preferred_foreign` - preferred `8000` foreign, `.onx/backend.port` = `8001` with healthy listener; assert reuse `8001` and no spawn (run #2, MAJOR-2).
7. `test_scan_reuses_healthy_own_candidate` - `.onx/backend.port` absent/stale; preferred foreign; `8001` has an own healthy listener; assert reuse `8001`, not `8002`.
8. `test_scan_unhealthy_own_candidate_prompts_and_does_not_skip` - `8001` own unhealthy; decline -> abort; accept -> use `8001` if freed.
9. `test_own_unhealthy_backend_prompts_and_aborts_on_decline` (preferred port; no fallback).
10. `test_own_unhealthy_backend_uses_preferred_after_confirmed_kill`.
11. `test_stale_pid_file_is_cleared_and_preferred_reused`.
12. `test_live_wrapper_without_listener_does_not_fake_reuse`.
13. `test_unknown_owner_with_non_panel_health_falls_back`.
14. `test_resolved_non_project_pid_with_panel_signature_is_not_reused`.
15. `test_unresolved_pid_with_panel_signature_is_reused_with_warning`.
16. `test_bind_race_retries_next_candidate` (first launch fails; selected port becomes occupied; assert next candidate).
17. `test_bind_retry_uses_short_timeout` (retry uses `min(15, startup_timeout)`).
18. `test_non_bind_failure_is_not_retried` (wrapper dead, port bindable).
19. `test_timeout_without_bind_evidence_is_not_retried` (generic timeout, not "crash").
20. `test_scan_exhaustion_aborts_with_no_unchecked_fallback`.
21. `test_active_port_file_written_on_success_and_cleared_on_stop`.
22. `test_backend_env_includes_panel_bind_port`.
23. `test_frontend_env_includes_backend_port`.
24. `test_status_uses_active_port_file_when_listener_exists`.
25. `test_can_bind_rejects_held_port` (real socket on `127.0.0.1`/`0.0.0.0` ephemeral; no external network).

### Backend config regression

In `backend/tests/infrastructure/test_panel_cloudflare_infra.py` (same pattern as the existing `MCS_PANEL_BIND_PORT` test at `:42-54`), add:

- `test_onx_panel_bind_port_env_override` - assert `get_panel_bind()` returns the `ONX_`-prefixed port.

### Manual/live verification (implementation phase)

1. Occupy `8000` with a live foreign listener (for example a local mock returning `401`), run `./start.sh`, confirm the backend starts on `8001`, and the foreign listener PID is unchanged.
2. Confirm the panel loads through the Vite dev server on its port: login and a WebSocket-backed page both work (Vite proxy uses `8001`).
3. Confirm `./start.sh --status` and the ReadyScreen show `8001`, and `.onx/backend.port` contains `8001`.
4. Confirm exposure target uses `8001` (for example the Cloudflare ingress computation reports `http://127.0.0.1:8001`).
5. **Run #2 (MAJOR-1/MAJOR-2):** leave the backend on `8001` running and the foreign listener on `8000`, run `./start.sh` again. Confirm preflight preserves the `8001` listener (no kill, no exit 1), the launcher reuses `8001`, and no second backend process appears.
6. Stop and restart with `8000` free; confirm the backend returns to `8000` and the active-port file is cleared/rewritten.
7. Repeat with an own healthy backend already running on the preferred port: confirm no second backend process appears.
8. Repeat with a stale PID file: confirm it is cleared and `8000` is used.
9. Occupy a fallback candidate (`8001`) with a healthy own backend while `.onx/backend.port` is missing; confirm the launcher reuses `8001` rather than starting on `8002`.
10. Enter a bind race deliberately (hold the candidate from the moment uvicorn starts); confirm a bounded retry on the next candidate logs the short retry timeout, and a genuine crash is not retried.
11. Windows: execute the same scenarios through `start.ps1`; if not performed, record `UNVERIFIED` rather than claiming parity. The Windows preflight must also protect the active port and must not fail on a foreign preferred listener.

---

## Verification Plan

Development loop:

```bash
cd backend && python -m pytest -q tests/test_launcher_dynamic_port.py tests/test_launcher_prerequisites.py tests/infrastructure/test_panel_cloudflare_infra.py
```

Before claiming the implementation complete:

- Sequential full backend suite (`cd backend && python -m pytest -q`) or the CI run, per `.ai/RULES/testing-and-verification.md`.
- Six quality gates (`scripts/check-*` per `.ai/RULES/testing-and-verification.md`).
- Live verification from the previous section, with the actual observed port, PID, and commands recorded in `.ai/STATE.json`.

Mutation checks (must fail when the fix is reverted):

| Mutation | Expected failing test |
|---|---|
| Remove project-ownership check before reuse | `test_foreign_live_port_falls_back_and_never_signals` |
| Change fallback into `kill_on_port` | `test_foreign_live_port_falls_back_and_never_signals` |
| Reuse a resolved non-project listener that returns the panel signature | `test_resolved_non_project_pid_with_panel_signature_is_not_reused` |
| Remove `ONX_PANEL_BIND_PORT` from the backend env | `test_backend_env_includes_panel_bind_port` |
| Remove `ONX_BACKEND_PORT` from the frontend env | `test_frontend_env_includes_backend_port` |
| Make health URL use the constant `8000` again | `test_reuse_probes_active_port_with_non_default_preferred` (preferred `8123`) |
| Ignore `.onx/backend.port` when it names a healthy backend | `test_known_active_healthy_reused_when_preferred_foreign` |
| Skip occupied scan candidates without classifying them | `test_scan_reuses_healthy_own_candidate` |
| Fall back for a project-owned unhealthy listener | `test_own_unhealthy_backend_prompts_and_aborts_on_decline` / `test_scan_unhealthy_own_candidate_prompts_and_does_not_skip` |
| Use the full 120 s timeout for retries | `test_bind_retry_uses_short_timeout` |
| Return `preferred + 1000` without a bind probe | `test_scan_exhaustion_aborts_with_no_unchecked_fallback` |
| Preflight omits active-port protection | manual run-#2 scenario (no automated bash harness) |
| Preflight marks foreign preferred occupancy unclean | manual `./start.sh` with a foreign listener (start.sh must reach the launcher) |

---

## Assumptions

| ID | Assumption | Status |
|---|---|---|
| A1 | The backend's `/health` JSON contract (`status`, `version`) is stable enough to identify the panel. | FACT at HEAD (`backend/app/main.py:460-476`); may need a dedicated marker if the contract changes. |
| A2 | Preflight's `belongs_to_project` heuristics are the canonical ownership definition. | FACT (read from `scripts/preflight.sh:84-127`, `scripts/preflight.py:343-380`). The launcher must mirror them exactly: daemon exclusions (`playit`, `cloudflared`, `tmux`, `java`, `_DAEMON_KEYWORDS`), server-data exclusions, then project-root/`onx-frontend`/`mcs-frontend`/`onx-manager`/`mcs-manager`/`app.main:app` markers. |
| A3 | Uvicorn binds IPv4 `0.0.0.0` only, so an IPv4 bind probe is the correct availability test. | FACT (`launcher.py:1041-1049`). |
| A4 | Ports `8000-8099` are outside typical ephemeral ranges on supported OSes. | ASSUMPTION; the scan is bounded and reports failure rather than probing arbitrary ports. |
| A5 | `.onx/config.json` is the launcher's only port configuration file. | FACT (`launcher.py:548-572`). |
| A6 | The Windows terminal launch path does not tee logs, so log-based bind detection is unreliable there. | FACT (`launcher.py:950-954`); mitigated by the port-occupancy check. |
| A7 | Two backends sharing the SQLite database is unsafe. | ASSUMPTION derived from the project's existing preflight rationale (`scripts/preflight.sh:1-19`) and single-writer SQLite behavior; drives the "never fallback for own-unhealthy" rule. |

---

## Owner Decisions (resolved 2026-10-20)

| ID | Question | Owner answer |
|---|---|---|
| O-1 | Should a fallback port be ephemeral runtime state (`.onx/backend.port`) with the preferred port kept in `.onx/config.json`, or should the chosen port become the new saved preference? | **Ephemeral runtime state.** Preferred is retried on every start. |
| O-2 | For a project-owned but unhealthy backend (on the preferred port or any scan candidate): prompt-kill (abort on decline), or silently fallback? | **Prompt-kill; never fallback** (A7). This is the one intentional exception to "occupied live process -> another port". |
| O-3 | Is a 100-port scan span (`preferred+1..preferred+99`) acceptable? | **Yes, 100 ports.** |
| O-4 | Environment precedence `ONX_BACKEND_PORT` > `MCS_BACKEND_PORT` > `.onx/config.json` > `8000`? | **Approved as written.** |
| O-5 | If `.onx/backend.port` names a healthy backend on `8001` while lower ports (including `8000`) are foreign-held, should the launcher reuse `8001` or prefer the lowest free port? | **Reuse `8001`.** Do not churn ports or move a healthy backend. |

---

## Reversibility and Rollback

- The change is confined to the launcher, the Vite dev config, and preflight (precedence plus active-port protection/summary semantics). Reverting those files restores the current fixed-port behavior.
- The new `.onx/backend.port` file is inert if the code is reverted; deleting it is safe.
- No database migration, schema change, API contract change, or production container change.
- Risk of user-visible port drift is mitigated by retrying the preferred port on every start.

---

## Risks

| Risk | Mitigation |
|---|---|
| Ownership misdetection starts a second backend on another port, causing SQLite contention. | Conservative ordering: only verified own-healthy or signature-verified listeners are reused; verified own-unhealthy never falls back; unknown-owner health failures fall back but never signal. Log ambiguity. |
| Configuration drift between preflight and launcher. | Single precedence rule implemented in both; launcher sets env explicitly for children; preflight reads the active-port file. |
| Preflight kills the fallback backend on the next run. | Active-port protection in `check_services`, `check_db_lock`, `scan_orphans`, and PID sync; live run-#2 verification required (MAJOR-1). |
| Preflight aborts on a foreign preferred listener. | Summary semantics distinguish foreign from unclean; `start.sh` must reach the launcher. |
| Windows behavior differs (netstat parsing, cmd environment, no tee). | Short retry timeout plus wrapper-death/port-occupancy discriminator; Windows verification is an explicit gate, otherwise recorded `UNVERIFIED`. |
| A fallback port is already stale in documentation or user bookmarks. | ReadyScreen, status, and logs always show the active port; preferred remains the default. |
| `find_free` is reused accidentally with its unchecked fallback. | Replace it with `resolve_startup_port`/`can_bind`; add the exhaustion test. |
| Concurrent launchers. | Out of scope; recorded as residual risk. |

---

## Pre-implementation Requirements

These are required before code lands. Items 1-2 are complete; items 3-6 remain for the implementation session:

1. Decision record `docs/decisions/0019-dynamic-backend-port.md` with the D1 required fields. **Done 2026-10-20.**
2. Owner answers to O-1 through O-5. **Done 2026-10-20; all defaults approved.**
3. `.ai/STATE.json` item added (`dynamic-backend-port-2026-10-20`, status `OPEN`). **Done 2026-10-20; move to implementation status when code lands.**
4. Documentation update in `docs/DEVELOPMENT.md` describing the fallback behavior, `.onx/backend.port`, and preflight active-port protection.
5. F-PORT-FRONTEND-01 captured as a separate finding (frontend readiness/URL constants), not fixed by this batch.
6. Preflight has no automated harness today. The implementation must either add a small testable resolver helper or record the preflight scenarios as manual evidence in `.ai/STATE.json`; it must not claim preflight coverage from launcher unit tests.

---

## Acceptance Criteria

1. A live foreign listener on the preferred port no longer blocks startup and is never signalled; preflight exits 0 and `start.sh` reaches the launcher.
2. The backend starts on the next bindable port, and the health wait, Swagger URL, ReadyScreen, `--status`, and `.onx/backend.port` all agree on that port.
3. The Vite dev proxy for `/api`, `/ws`, `/health`, `/docs`, and `/openapi.json` targets the active port.
4. The backend panel bind (used by Cloudflare/playit/UPnP) reports the active port.
5. A healthy project backend is reused on the preferred port, a fallback port, or the port named by `.onx/backend.port`; no second backend is ever spawned while one is alive.
6. An unhealthy project backend never leads to a second instance (own-unhealthy policy).
7. Preflight protects the active backend across `check_services`, `check_db_lock`, `scan_orphans`, and PID synchronization, including run #2.
8. Dead PID/port state is cleaned and the preferred port is reused when available.
9. Bounded bind-race retry works with the short retry timeout; genuine crashes/timeouts are not retried.
10. New tests pass, the sequential suite or CI run is green, and all six quality gates pass.
11. Live verification evidence is recorded, including the run-#2 scenario; Windows is either verified or explicitly marked `UNVERIFIED`.
12. No production Docker/nginx behavior changes.

---

## Amendments (SPEC-2026-10-20-DYNAMIC-PORT-FIXES-01)

This specification is formally amended by `docs/design/SPEC-2026-10-20-DYNAMIC-PORT-FIXES-01.md`:

1. **D-3 (Unresolved occupant blocks candidate retries; SQLite data safety):**
   Following a failed attempt, if an occupant remains on the attempted port with unresolved ownership (`UNKNOWN`), startup must abort immediately without trying further candidate ports. Spawning another backend on another port while an unresolved process may be accessing the SQLite database risks database corruption and duplicate writers.
2. **D-7 (Bind-race retry scope):**
   Candidate port retries are strictly restricted to failures diagnosed as bind races (`outcome == "bind"` or `dead`+occupied), and only when the attempted port is free (`can_bind` succeeds) or occupied by a conclusively proven foreign process. Generic crashes and generic timeouts are non-retryable.
3. **D-10 (No SIGKILL escalation; report survivors):**
   No SIGKILL escalation is applied to surviving descendants during failure reconciliation or termination. If descendant processes survive SIGTERM, the launcher reports them and aborts startup without kill escalation.
4. **Dead Constants Note (launcher.py:98-99):**
   `BACKEND_HEALTH_URL` and `SWAGGER_URL` in `launcher.py` (lines ~98-99) are computed from the legacy fixed constant `BACKEND_PORT = 8000` and are not consumed elsewhere in the repository. They are documented as dead constants and marked for cleanup in follow-up maintenance (no code edits to `launcher.py` in Batch B9).
