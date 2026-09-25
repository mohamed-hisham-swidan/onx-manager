# Design Spec: Unified Starting Monitor

**Document Status:** DOCUMENTED DESIGN, NOT YET IMPLEMENTED — 2026-09-23  
**Spec Identifier:** `SPEC-2026-09-23-UNIFIED-STARTING-MONITOR-01`  
**Date:** 2026-09-23  
**Governing Authority:** `docs/governance/GOVERNANCE.md`; `.ai/pls-agent-ignore-that/Orchestrator.md` §5  

> Design-completion gate note (per `.ai/RULES/documentation-and-state.md`):  
> this is a **documented design, not yet implemented**.

---

## Goal
Give every server-boot path (regular servers of all providers, and
isolated test-run containers) a real, visible, configurable "starting/
booting" phase that gates post-boot interaction (RCON / bot
verification) until boot is actually confirmed — replacing today's mix
of hardcoded timeouts, one provider with no readiness check at all, and
zero frontend visibility into the wait.

## Current Behavior
- Regular servers: STARTING status + deferred RUNNING commit are fully
  built (SPEC-STARTING-VISIBLE-001), but timeouts are hardcoded at 3
  layers (30s spawn / 60s provider wait_ready, local+Windows only / 120s
  supervisor deadline) with zero configurability. DockerProvider has NO
  wait_ready at all — instant-True, confirmed via Phase 0 as never
  implemented, no readiness substitute exists. Frontend shows only a
  static "Starting" badge — no timer, progress, or alert.
- Isolated test runs: real container boot + log-marker polling + crash
  correlation are built; boot-grace floor is 120s in code (spec doc
  still says 60s — stale). `connect_grace_seconds` is global-only.
  Frontend has no distinct "booting" state — boot result only shown
  post-hoc in the evidence modal.
- Both paths independently implement the same conceptual signal triple
  (log-marker poll + liveness probe + crash correlation) with no shared
  code between them.

## Proposed Change
1. **Shared signal-detection layer** (new, DB-free, pure functions):
   extract the log-marker-poll / liveness-probe / crash-correlation
   triple into a shared helper module, based on the test-run path's
   already-proven implementation (`test_runner.py:759-843`) and the
   local-provider pattern (`local.py:652-663`). Both `DockerProvider`
   and `DockerTestExecutionRunner` call into it — no duplicate logic.
2. **DockerProvider.wait_ready implementation** (closes the regular-
   Docker gap): `docker logs --tail` poll for `"Done ("` (verify marker
   consistency across itzg image variants first — Phase 0's flagged
   assumption) + `docker inspect` liveness, using the new shared layer.
3. **Two-tier timeout configuration** — global default + per-server
   override:
   - Two new `LiveSettings` fields as global defaults:
     `server_startup_timeout_seconds` (default 120, matches current
     supervisor behavior) and `test_boot_timeout_seconds` (default 120,
     matches current code floor — also fixes the spec-vs-code drift).
     Both live/no-restart, sharing a clamp range (propose 30–1800s).
   - Per-server override: add a nullable `startup_timeout_seconds`
     field to the Server aggregate/model (mirroring how other
     per-server settings like max-players are already stored on the
     server itself, not in global LiveSettings) — null means "use the
     global default." Confirm at Build whether an equivalent per-run
     override belongs on `TestSpec`/`BotVerificationConfig` for the
     test-run side, or whether per-server is sufficient there too
     (owner asked for "customizable for every server" — test runs are
     tied to a server, so the server-level override should apply to
     both paths uniformly rather than adding a second override axis).
4. **Capped duration + manual-dismiss** (resolves the open-ended-vs-
   safety-alarm tension): the starting-monitor timer is not unbounded —
   it runs to the configured timeout (global default or per-server
   override), then surfaces a persistent warning state rather than
   silently failing or silently continuing forever. The user can
   manually dismiss/extend from the UI at that point rather than the
   system enforcing a hard kill — this preserves the "safety alarm"
   intent without contradicting "not too rigid."
5. **Frontend — Phase A (build now):** a persistent STARTING/booting
   banner (regular server detail/list) and an equivalent booting state
   on the test-run page, each showing an elapsed timer against the
   configured timeout, a manual "check now" button (precedented by
   `ServerExposurePage.tsx`'s Refresh pattern), and a warning treatment
   once elapsed time passes the timeout (distinct from the transient
   toast pattern already in use).
6. **Frontend — Phase B (explicit follow-up, not this build):** audio
   alert — no existing precedent, needs new infra (autoplay-policy
   handling, mute/dismiss), deliberately deferred.
7. **Test-run state model:** add a `BOOTING` (or equivalent) phase to
   `TestRunStatus` distinct from `RUNNING`, so the frontend has a
   signal to attach the timer/banner to (currently only PENDING/RUNNING
   exist) — confirm at Build whether the `ServerTestRun` DB model needs
   a matching column or whether this can be derived from existing
   fields.
8. **Reconcile documentation drift:** update
   SPEC-2026-09-15-ISOLATED-TEST-BOOT-CONTRACT-01's stale "60s floor"
   references to 120s to match code.

## Affected Components
- New shared signal-detection module (location TBD at Build — likely
  under a shared infra path both `server` and `versioning` modules can
  import from)
- `backend/app/modules/server/infrastructure/providers/docker.py`
  (wait_ready implementation)
- `backend/app/core/settings_store.py` (`_DEFAULTS`, `LiveSettings`
  dataclass, `_coerce`, `update_settings`, settings API/UI surface)
- Server aggregate/model + its create/update commands (new nullable
  per-server timeout field) + relevant migration
- `backend/app/modules/versioning/infrastructure/test_runner.py`,
  `bot_drivers.py`, `TestRunStatus` type, `ServerTestRun` model (if a
  column is needed)
- Frontend: `DashboardServerList.tsx`, `ServersPage.tsx`,
  `ServerDetailPage.tsx`, `ServerVersioningPage.tsx`,
  `TestRunModal.tsx`, `TestEvidenceModal.tsx`, `types.ts`,
  `websocket/handler.ts`, `hooks/useServers.ts` (new banner/timer
  component, likely shared between the two surfaces)
- `docs/design/SPEC-2026-09-15-ISOLATED-TEST-BOOT-CONTRACT-01.md`
  (drift fix)

## Interfaces & Contracts
- New `LiveSettings` fields (PATCH-editable, no restart required) —
  additive, no breaking change to existing settings API shape.
- New nullable field on the Server create/update API payload
  (`startup_timeout_seconds`) — additive, optional, backward compatible.
- New `TestRunStatus` value (`BOOTING` or equivalent) — additive enum
  value; frontend TypeScript type and any status-based switch
  statements must be updated to handle it (audit all `TestRunStatus`
  consumers at Build to avoid an unhandled-case gap).
- No changes to `contracts/permissions.yaml` — no new permission gate
  needed for this feature (viewing/dismissing a timer is not a
  privileged action beyond existing server/test-run view permissions).

## Failure Cases & Edge Cases
- Marker-consistency assumption (Phase 0 flag): verify `"Done ("`
  appears across the itzg image variants actually in use before
  relying on it for `DockerProvider.wait_ready` — if inconsistent,
  the shared layer needs a per-image-family marker table, not a single
  hardcoded string.
- Race: manual "check now" / dismiss action arriving concurrently with
  the server transitioning to RUNNING or CRASHED on its own — dismiss
  action must be a no-op (not an error) if the state already changed.
- Clamp enforcement: per-server override must respect the same
  30–1800s clamp as the global default; reject/clamp at the API layer,
  not just the frontend.
- Existing reconciliation arms (`DB_STARTING_ALIVE`/`DB_STARTING_DEAD`,
  60s age gate) must not conflict with the new configurable timeout —
  confirm the reconciliation age-gate is either driven by the same
  setting or intentionally kept independent (it's a crash-recovery
  safety net, not a user-facing timer) — do not silently let two
  different timeout values fight each other.
- Docker `wait_ready` failure mode: if the marker poll never succeeds
  before timeout, must follow the same STARTING→CRASHED/STARTUP_TIMEOUT
  paths already built for the local/Windows providers, not a new
  failure mode.
- Frontend: banner + timer must degrade gracefully if the WS event for
  a status change is missed (reuse the existing 5s polling backstop
  already confirmed present in `useServers.ts`).

## Tests & Verification
- Unit tests for the shared signal-detection layer (marker poll,
  liveness probe, crash correlation) independent of both callers.
- `DockerProvider.wait_ready` test against a mocked container log
  stream (success, timeout, and crash-mid-boot cases).
- Per-server override: create/update tests confirming null falls back
  to global default, non-null overrides it, clamp is enforced.
- `TestRunStatus` BOOTING: regression tests for every consumer switch
  statement found in the Build-time audit.
- Frontend: banner/timer component tests (elapsed-time display, warning
  state past timeout, check-now action, dismiss-is-idempotent behavior).
- Full backend + frontend suites + all 6 CI gates, per Orchestrator.md §9.
- Manual live verification (matches the project's established no-
  trust-unverified-claims culture): start a regular Docker server and
  confirm the new wait_ready actually gates RUNNING on real boot, not
  container-start; run an isolated test against a fresh branch/commit
  with an intentionally-short-looking window and confirm the
  first-boot/download case no longer false-fails.

## Governance Gate Check (per GOVERNANCE.md)
- Lane: D1+ (confirmed by Mohamed) — cross-cutting, touches server
  module, versioning module, and settings/config surface.
- Reversible: yes — additive fields/settings, no destructive migration,
  existing hardcoded-timeout behavior is preserved as the default value
  of the new settings (120s/120s), so behavior is unchanged unless the
  new settings are explicitly changed.

## Out of Scope
- Audio alerts (Phase B, explicit future follow-up).
- Any change to the reconciliation age-gate values themselves (reused
  as-is per Finding A3, unless Design Review decides otherwise).
- ServerConsole.tsx's own STARTING-related elements — unchecked by
  recon, must be audited at Build to avoid a duplicate/conflicting
  timer surface.
- Dev-DB phantom-row cleanup, DB-isolation work — unrelated, tracked
  separately.
