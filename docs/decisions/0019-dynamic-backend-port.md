# ADR-0019: Dynamic Backend Port Selection with Active-Port Reuse

**Status**: Accepted (implemented 2026-10-20; local sequential suite + 6/6 gates passed; CI/Windows UNVERIFIED)  
**Date**: 2026-10-20  
**Author**: Dynamic Port Design Session  
**Decision level**: D1  
**Primary lane**: Lane B (Release Improvement)  
**Roadmap drift**: None  
**Spec**: `docs/design/SPEC-2026-10-20-DYNAMIC-BACKEND-PORT-01.md` (v2)

## Context

ONX Manager's launcher fixes the backend port from configuration and assumes every
consumer uses that same value. On a developer host, port `8000` is frequently held by
an unrelated service. The current fallback behavior is destructive or broken:

- a resolvable occupant is offered for `kill`; declining aborts startup;
- an unresolvable occupant produces a no-op kill and a doomed bind;
- health checks, Vite's proxy, Swagger, status, ReadyScreen, and exposure features all
  read hard-coded or import-time URLs built from `8000`;
- preflight marks a foreign listener on the preferred port as unclean and exits 1, so
  `start.sh` never reaches the launcher;
- preflight protects only the preferred port, so on a second run it can kill a healthy
  backend that is running on a fallback port.

The owner's requirement is to coexist with a foreign listener: leave it untouched and
start the project backend on another port, with all dev consumers agreeing on that port.
The one exception is a project-owned backend, because two backends sharing the SQLite
database are unsafe.

Live evidence at HEAD `14a441f`: port `8000` returned `HTTP 401` with an OAuth
`WWW-Authenticate` header for `/health`; `.onx/logs/backend.log` ended with
`ERROR: [Errno 98] Address already in use`; `.onx/backend.pid` held a live `konsole`
terminal wrapper for the failed launch, which the current code can mistake for a
running backend.

## Options

1. **Keep the fixed port and kill the occupant.** Rejected: destructive on a developer
   host and surprising when the occupant is unrelated.
2. **Always pick another port whenever the preferred port is occupied.** Rejected:
   starting a second backend against the same SQLite database risks corruption and
   duplicate writers; a project-owned listener must be reused or resolved explicitly.
3. **Dynamic port with ownership-aware resolution (adopted).** Leave foreign listeners
   alone, reuse a healthy project backend wherever it is running, scan forward for a
   free port, and never silently duplicate a project-owned backend.
4. **Persist the fallback as the new preferred port.** Rejected by the owner: it hides
   the original conflict and permanently drifts configuration. The chosen port is
   runtime state only.

## Decision

1. **Preferred port precedence:** `ONX_BACKEND_PORT` > `MCS_BACKEND_PORT` >
   `.onx/config.json` `backend_port` > `8000`. Launcher and preflight use the same rule.
2. **Active port is runtime state:** store it in `.onx/backend.port` (legacy
   `.mcs/backend.port` fallback). Never write the fallback into `.onx/config.json`.
   Retry the preferred port on every start.
3. **Classify every candidate** as `FREE`, `OWN_HEALTHY`, `OWN_UNHEALTHY`,
   `HEALTHY_UNVERIFIED`, `FOREIGN`, or `UNKNOWN` using bind probing, exact preflight
   ownership markers, and the panel health signature (`status == "ok"` plus `version`).
4. **Resolution order:**
   - known active port: reuse `OWN_HEALTHY`/`HEALTHY_UNVERIFIED` immediately;
   - preferred port: use/free/reuse, or fallback on `FOREIGN`/`UNKNOWN`;
   - scan `preferred+1 .. preferred+99`: reuse a healthy project backend found there,
     otherwise select the first bindable port.
5. **Own-unhealthy policy:** prompt to stop; abort on decline or failure. Never fall
   back to another port. This applies on the preferred port and every scan candidate.
6. **Foreign and unknown listeners are never signalled and never reused.** A resolved
   PID that fails ownership markers is foreign even if it returns the panel signature;
   `HEALTHY_UNVERIFIED` reuse is limited to unresolvable PIDs, with a warning.
7. **Bounded bind-race retry:** at most 3 attempts. The initial attempt uses
   `startup_timeout` (default 120 s); retries use `min(15 s, startup_timeout)`. Retry
   only on bind evidence; do not retry a genuine crash or a generic timeout.
8. **Propagation:** launch uvicorn with the active port, set `ONX_PANEL_BIND_PORT` for
   the backend child, set `ONX_BACKEND_PORT` for the Vite child, and make status,
   self-test, Swagger, and ReadyScreen read the resolved port.
9. **Preflight active-port protection:** resolve the active port, verify the panel
   signature, and protect it in `check_services`, `check_db_lock`, `scan_orphans`, PID
   synchronization, and the summary. Foreign occupancy of the preferred port is
   reported as foreign, not unclean; `start.sh` must reach the launcher.
10. **Platform rule:** use a real bind probe (`0.0.0.0`, `SO_REUSEADDR` on POSIX only);
    Windows netstat/log differences are covered by the bind probe and short retry
    timeout, and must be verified separately or recorded `UNVERIFIED`.

## Why

- **Safe coexistence:** foreign services are never killed; the backend simply moves.
- **Data integrity:** a live project-owned backend is never duplicated; unhealthy
  instances require an explicit stop.
- **Single source of truth:** the active-port file is written after health succeeds and
  read by preflight and status, so run #2 reuses the existing backend instead of
  churning ports or killing it.
- **Bounded failure:** a 100-port span, 3 attempts, and a 150 s worst-case budget keep
  startup predictable without repeated 120 s waits.
- **Owner-approved defaults:** ephemeral active port, prompt-kill for own-unhealthy,
  100-port span, the stated precedence, and reuse of a healthy active port.

## Impact

- **Product/user:** startup succeeds when `8000` is occupied; the foreign service is
  untouched; a second run reuses the backend already on a fallback port.
- **Stability:** removes the false "Backend already running" path and the doomed bind.
  Preflight no longer kills a healthy fallback backend.
- **Architecture:** launcher and preflight share a contract through files and the health
  signature, not a shared import; no backend API or database migration.
- **Operations:** `.onx/backend.port` becomes runtime metadata. Production containers
  remain fixed at `8000` and are unaffected.
- **Residual risks:** concurrent launchers are still unsolved; ownership heuristics can
  misclassify unusual launch paths; Windows behavior must be verified live.

## Effort

Moderate. One launcher subsystem, two preflight scripts, one Vite config, targeted
tests, and live verification. No backend source change is required for the primary path
because `ONX_PANEL_BIND_PORT` already exists.

## Reversibility

Easy. Revert the launcher, Vite, and preflight changes to restore fixed-port behavior.
`.onx/backend.port` is inert when unused and can be deleted safely.

## Roadmap impact

None. Does not change release scope, milestones, or production deployment.

## Verification

The full matrix is in the spec. Required evidence:

1. New launcher unit tests (classification, run-#2 reuse, scan reuse, own-unhealthy
   policy, retries, timeouts, env propagation, active-port persistence).
2. Backend settings regression for `ONX_PANEL_BIND_PORT`.
3. Existing launcher prerequisites and panel/Cloudflare tests stay green.
4. Sequential full backend suite or CI, plus all six quality gates.
5. Live scenario #1: foreign listener on `8000`, backend starts on `8001`, foreign PID
   unchanged, panel/proxy/exposure/status all use `8001`.
6. Live scenario #2: run again with the backend still on `8001`; preflight preserves it,
   the launcher reuses it, and no second backend appears.
7. Windows: same scenarios through `start.ps1`, or record `UNVERIFIED`.
