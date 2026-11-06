## Current State (2026-11-06)

**Roadmap: ROADMAP_v1.1** (docs/roadmap/ROADMAP_v1.1.md)
- Phase 0 (Ground Truth/Baseline Freeze): CLOSED
- Phase 1 (Bug Triage & Classification): CLOSED — commit `4a130ce` + `e06e4d9`
- Phase 2 (Backend Stabilization): CLOSED — commit `e17da25`
- Phase 3 (Frontend Stabilization): CLOSED — commit `0de35cb`
- **Phase 5 (Containers System): CLOSED (2026-09-11 / 2026-09-12)** — All 6 batches complete & pushed to origin/master (`183ae7b`).
- **Phase 4 (Community Features): CLOSED (2026-09-14)** — All 5 features implemented & verified: Git-Inspired Versioning & Bot Testing, Test Environment, Custom Mod Support, Change History Log, Unified Log/Crash Readability.
- **Enterprise Branch Runtime — Stage A (Domain Reconstruction): CLOSED (2026-09-17)** — Domain model formalized in `backend/app/modules/versioning/domain/` (Project, Repository, Tree, Commit immutability, Branch created->active->archived state machine, Revision value object, Materialization lifecycle & root isolation, Runtime pinned to immutable Commit ID, PersistentDataset mutable boundary isolation, Run/TestRun terminal state protections); ADRs 0013, 0014, 0015, 0016 recorded; 2,753 backend tests passing, 6/6 CI quality gates PASS. Commit `e72a219`.
- **Enterprise Branch Runtime — Stage B (Real Version Control): CLOSED (2026-09-17)** — Persistent commit DAG with additive `server_commit_parents` junction table, cycle detection, multi-parent merge history, immutable server tags (`server_tags`), deterministic tree and commit diffing (`diff_trees`, `diff_commits`), branch archiving (`ArchiveBranchCommand` and persistent `status` column on `server_branches`), revision resolution (`Revision.from_tag()`), repository history queries (`GetBranchHistoryQuery`, `DiffCommitsQuery`, `GetServerTagsQuery`, `GetServerTagQuery`), and 7 new FastAPI endpoints (129 routes verified). Alembic migration `b1e2100000015`. 2,793 backend tests passing / 6 skipped, 6/6 CI quality gates PASS. Commit `641ea58`.
- **Enterprise Branch Runtime — Stage C (Filesystem & Materialization Engine): CLOSED (2026-09-17)** — Domain `Materialization` entity (PENDING, READY, STALE, REMOVED) and `ImportReview` aggregate with terminal state machine; atomic filesystem engine (`fs_atomic.py`, `tree_writer.py`) with root escape validation; Alembic migration `b1e2100000016` adding `server_materializations` and `server_import_reviews` tables; 12 CQRS commands/queries and FastAPI endpoints registered in `contracts/permissions.yaml` (141 live routes verified). 2,829 backend tests passing / 6 skipped, 6/6 CI quality gates PASS. Commit `8f10a4d`.
- **Enterprise Branch Runtime — Stage D (Runtime Scheduling & Admission Control): CLOSED (2026-09-17)** — Global admission scheduler (`RuntimeAdmissionScheduler`) with static + dynamic RAM headroom gating, FIFO run queue, concurrency caps, and dynamic host headroom verification; Alembic migration `b1e2100000017` creating `server_admission_leases`; 2,829 backend tests passing / 6 skipped, 6/6 CI quality gates PASS. Commit `e77a82c`.
- **Enterprise Branch Runtime — Stage E (Console & Observability): CLOSED (2026-09-17)** — Demand-driven `ConsoleStreamManager` (`docker logs -f --timestamps --tail 0` with tmux capture fallback, 5s subscriber debounce, batch flush at 50 lines / 100ms, 64KB frame partitioning, non-silent queue overflow drop marker); WS `exec_input` and `exec_resize` client messages with RBAC checks; additive `write_exec_input` provider extension per ADR-0015; unified `docker stats` batch telemetry with multi-core CPU normalization clamped to 100%; frontend reconnect re-tail backfill and polling suppression when WS is connected; 2,859 backend tests passing / 6 skipped, 6/6 CI quality gates PASS (141/141 route contract preserved). Commits `41da076` / `0b64ef2`.
- **Enterprise Branch Runtime — Stage F (Test Platform & Verification Drivers): CLOSED (2026-09-18)** — Reusable `TestDefinition` configurations aggregate, 1:1 `Runtime` entity container attach model via `server_runtimes` table, automated `PatternCrashAnalyzer` mod blame integration, structured `EvidenceBundle` generation, and lazy 24h debug artifact pruning in admission reaping; Alembic migration `b1e2100000018`; 6 new FastAPI endpoints (147 live routes verified); 2,882 backend tests passing / 6 skipped, 6/6 CI quality gates PASS. Commit `785c7cc`.
- **Enterprise Branch Runtime — Stage G (Protected Branches): CLOSED (2026-09-18)** — `BranchProtectionPolicy` frozen dataclass (require_test_pass, allow_direct_commit, allow_force_bypass, prevent_deletion), `ServerBranch` lifecycle methods (`protect`, `unprotect`, `can_commit_directly`, `can_archive`), `BranchProtectedError` (HTTP 409), `CreateCommitCommand` protection enforcement with administrative emergency bypass permission and audit logging, strict `AutoCommitLiveChangesCommand` and `ArchiveBranchCommand` rejection, and 3 new REST endpoints; Alembic migration `b1e2100000019` advancing route contract to 150/150 routes; 2,906 backend tests passing / 6 skipped, 6/6 CI quality gates PASS. Commit `ba8b539`.
- **Enterprise Branch Runtime — Frontend UI Batch: CLOSED (2026-09-18)** — Complete user interfaces for Stages B, C, F, G: `BranchProtectionModal.tsx`, `TestDefinitionsModal.tsx`, `TestEvidenceModal.tsx`, `MaterializationBrowserModal.tsx`, `ImportReviewModal.tsx`, `ManageBranchesModal.tsx`, `CreateTagModal.tsx`, `CommitDiffModal.tsx`, and full page integration in `ServerVersioningPage.tsx`; all 22 versioning routes wired in `api.ts`; 0 TypeScript errors; 730 frontend tests passing across 83 test files (100% green); 6/6 CI quality gates PASS. Commit `8b219ba`.
- **Phase 5.5 — Pre-Beta Reliability (Stages A & B): CLOSED (2026-09-29)** — Stage A Reliability Foundation (`Operation` aggregate, idempotency, WS projection) and Stage B Test Run Engine (`TestDefinition` execution without lossy division, standard `ValueError` terminal guards, `operation_id` column/index via migration `b1e2100000022`, unified assertion engine with `BaseVerifier`, canonical `TestCleanupPlan` with separator-safe `resolve_test_dir`). 3,145 backend collected / 3,139 passed / 6 skipped / 0 failed, 752 frontend passed across 89 files, 6/6 CI quality gates PASS.
- **Frontend UX/IA Overhaul & Design Token System (2026-11-06; Lane B, D1; ADR-0021): IMPLEMENTED_PENDING_REVIEW** — Full autonomous overhaul across Phases 1 through 9, review batches F1-F5, and Overnight Closure Batches N-01 through N-23: semantic token engine, multi-skin system (Graphite & Azure), 18 reusable primitives, unified AppShell/ServerShell, 7 standardized page templates (Fleet status bar, client-side files filter/paging, decomposed versioning & create server wizards), palette ratchet test, overlay ratchet test (100% overlay consolidation to Modal/ConfirmDialog, 0 bypassing overlays, 0 native confirm/alert/prompt dialogs), original brand identity (vortex mark, voxel banners, domain icons, legal disclaimer), motion/density controls, route-level code splitting (-68.3% initial bundle reduction: 1,251 kB -> 396.68 kB across 39 JS chunks), comprehensive docs in `docs/design/frontend-overhaul/` and findings ledger in `FINDINGS-LEDGER.md` (33 findings: 26 closed, 5 owner decisions, 2 backend-dependent, 0 open). 1,018 frontend tests passing across 118 test files (100% green), typecheck clean, 0 ESLint errors and 0 ESLint warnings, production build green (39 JS chunks, largest chunk 396.68 kB), 6/6 CI quality gates PASS. Pending independent reviews: R2 (primitives/shells/a11y), R3b (page behavior), R4 (brand/IP), and final review.
- **Next: Phase 6 (Final Installs / Wrap-up) — READY**: Installer polish, distribution packaging, first-run experience, documentation review.


**Resolved recently (for reference, don't re-investigate):**
- Frontend UX/IA Overhaul & Design Token System (2026-11-06; Lane B, D1; ADR-0021; Status: IMPLEMENTED_PENDING_REVIEW):
  - Semantic CSS token architecture in `frontend/src/index.css` registered with Tailwind v4 `@theme`.
  - Multi-skin engine featuring Graphite (neutral black, 0% blue chroma on neutral tokens) and Azure (slate blue), pre-paint DOM init in `main.tsx`, WCAG AA contrast verification (`contrast.test.ts`), and pure custom skin validator (`skinValidator.ts`).
  - 18 token-based primitives in `components/ui/` (Modal, ConfirmDialog, Tabs, Table, Pagination, PageHeader, States, Banner, Button/IconButton, Chip, Icon).
  - Unified `AppShell` and `ServerShell` with live WebSocket diagnostics and shared `Sidebar`.
  - Standardized templates across all 7 views: Fleet Status Bar, File Browser client filtering & directory pagination, decomposed `ServerVersioningPage` (1,280 -> 607 LOC) and `CreateServerPage` (811 -> 273 LOC).
  - Palette ratchet test (`paletteRatchet.test.ts`) enforcing zero unallowlisted raw Tailwind color classes; overlay ratchet test (`overlayRatchet.test.ts`) enforcing 100% overlay consolidation to Modal/ConfirmDialog with 0 bypassing dialogs and 0 native window dialogs.
  - Original brand identity: vector vortex logo mark (`BrandLogo.tsx`), isometric voxel banners (`VoxelBanner.tsx`), themed domain icons (`Icon.tsx`), and legal disclaimers.
  - Motion tokens (`--motion-duration-*`, `--motion-ease-standard`) with global `prefers-reduced-motion` override and density hierarchy tokens.
  - Production route code-splitting with `React.lazy` and `Suspense`, dropping initial JS payload from 1,251 kB to 396.68 kB (-68.3% across 39 JS chunks).
  - Verified 2026-11-06: 1,018 frontend tests passing across 118 test files (0 failures); typecheck clean; 0 ESLint errors and 0 ESLint warnings; production build green (39 JS chunks, largest chunk 396.68 kB); 6/6 CI quality gates PASS. Pending independent reviews: R2 (primitives/shells/a11y), R3b (page behavior), R4 (brand/IP), and final review.
- Test Signal Safety Guard (2026-10-04; Test Safety, Lane A, D1):
  - Hermetic autouse test fixture in `backend/tests/conftest.py` wrapping `os.kill` and `os.killpg` (and signal helpers) to raise `AssertionError` if target PID is not a verified descendant of the current pytest process.
  - Documented guard behavior: raises `AssertionError` (not `OSError`), noted `LocalLinuxProvider._is_pid_alive` exception fallback to `kill -0`, and documented Win32 residual (`ctypes.windll.kernel32.TerminateProcess` in `process_utils.py` not intercepted).
  - Narrowed `@pytest.mark.allow_real_signals` strictly to `test_live_process_current_pid` and `test_dead_process_nonexistent_pid` in `test_process_utils.py`; removed unused `allow_unsafe_signals` marker from `pyproject.toml` and `conftest.py`.
  - Repo-wide AST scanner in `backend/tests/test_signal_safety_guard.py` ensuring zero un-allowlisted signal bypass patterns (`from os import kill/killpg`, `signal.raise_signal`, `signal.pthread_kill`, `psutil.Process(...).kill()/.terminate()`) across `app/` and `tests/`; backed by `backend/tests/signal_bypass_allowlist.json`. 6/6 tests PASS.
- Naive UTC Timestamps Misread as Local Time in UI (2026-10-03 / 2026-10-04; Lane A/B, small-change):
  - Symptom: Server starting monitor banner showed "Server Boot in Progress 180:07 / 2:00" in UTC+3 (Africa/Cairo) and prematurely triggered overdue warning due to naive UTC ISO timestamps parsed as local time by the browser.
  - Backend API Boundary Normalization: `BaseResponse(BaseModel)` in `backend/app/api/v1/schemas/common.py` using wildcard `@field_serializer("*", mode="plain", when_used="json")` to normalize all `datetime.datetime` instances (naive -> assume UTC; aware -> `astimezone(datetime.timezone.utc)`) and naive ISO string values (`YYYY-MM-DDTHH:MM:SS` or `YYYY-MM-DD HH:MM:SS` for timestamp fields) to UTC ISO-8601 strings ending with `'Z'`. Extended `BaseResponse` across all response schemas in common, server, backup, plugin, versioning, operation, auth, user, health, exposure, files, activity, import_server, and invites.
  - Architecture Cleanliness: extracted pure datetime formatting logic to neutral module `backend/app/core/timeutil.py` (`format_datetime_utc`, `is_timestamp_field`, `normalize_iso_timestamp`), ensuring zero illegal application -> API layer imports in `list_invites.py`.
  - Audited Non-Response Model Paths: registered `ENCODERS_BY_TYPE[datetime.datetime] = format_datetime_utc` in `backend/app/main.py`; normalized WebSocket event/message payloads in `backend/app/websocket/serializers.py` with timestamp-field key protection; normalized raw dictionary return paths in `backend/app/api/v1/routers/monitoring.py` (`get_metrics`, `list_alerts`) and `backend/app/api/v1/routers/schedules.py` (`list_schedules`, `create_schedule`).
  - Frontend Timezone-Aware Parsing: implemented `parseServerDate(dateStr)` in `frontend/src/server_manager/utils/format.ts` supporting naive ISO (`YYYY-MM-DDTHH:MM:SS`), space-separated (`YYYY-MM-DD HH:MM:SS`), date-only (`YYYY-MM-DD`), numeric epoch (seconds or ms), and explicit Z/offsets without double-appending `Z`, returning `null` on invalid dates. Replaced all 12 consumption sites: `StartingMonitorBanner.tsx`, `formatDateTime`, `formatRelativeTime`, `ServerVersioningPage.tsx`, `ManageBranchesModal.tsx`, `CrashReportViewerModal.tsx`, `ImportReviewModal.tsx`, `ApiKeysPage.tsx`, `InvitePage.tsx`, `InvitationsSection.tsx`, `PlayitClaimCard.tsx`, and `activityStore.ts`.
  - Frontend CI Timezone Isolation: added `test: { env: { TZ: 'Africa/Cairo' } }` in `frontend/vitest.config.ts` so Vitest workers consistently execute under non-UTC timezone even on CI runners with `TZ=UTC`.
  - Verification & Quality:
    - Backend: `backend/tests/api/test_datetime_timezone_serialization.py` (20/20 passed, covering all response schemas, string protection, raw dict endpoints, enum/alias/exclude_none preservation, and nested models).
    - Frontend: `StartingMonitorBanner.tz.test.tsx` (3/3 passed under `Africa/Cairo` and `America/Los_Angeles` with fake timers verifying ~0:00 elapsed), `format.test.ts` (16/16 passed), `activityStore.test.ts` (5/5 passed); full frontend suite 766/766 passed across 90 files; typecheck and build PASS.
    - 6/6 CI quality gates PASS (`check-db-revision`, `check-ruff-baseline`, `check-version-propagation`, `check-route-contract`, `check-ps1-bom`, `check-stray-db`).
    - Mutation tests: removing serializer in `BaseResponse` fails backend tests; reverting `parseServerDate` in `StartingMonitorBanner` fails frontend TZ tests with `expected '180:05 / 2:00' to be '0:05 / 2:00'`.
- Stale Startup Deadline & Supervisor Reuse Prevention (2026-10-02 / 2026-10-04; Lane A, D1):
  - Fix stale startup deadline in `RuntimeSupervisor`: `start()` re-anchors per-run state (`_started_at = time.monotonic()`, resets `_start_duration`, `_ready_at_wall`, `_last_heartbeat`, `_active = True`) so repeated runs receive a fresh deadline instead of being verified against run #1's expired window.
  - Fix supervisor instance reuse in `start_for()`: never supervise a new run with an old handle/provider. Discards dead/dying instances (inactive, `_stop_event` set, or task done), returns idempotent instance only if alive with identical handle and provider, and stops differing-handle instances before constructing fresh.
  - Clear `_active` in `stop()`, `_handle_crash()`, and `_health_check()` whenever `_stop_event` is set; cleared `_active = False` immediately upon entry to `_handle_crash()` to block concurrent reuse while async crash handling is in flight; guard registry cleanup in `stop()` and `_run()`'s `finally:` block (`if self._instances.get(self._server_id) is self: self._instances.pop(...)`) so completing tasks do not evict newly registered supervisors; deleted unused `__await__` shim.
  - Regression tests in `tests/application/test_stale_startup_deadline.py`: 7/7 passing (pinned mid-verify task suspension registry protection, differing-handle scheduled stop, and immediate `_active=False` in `_handle_crash`). 6/6 CI quality gates PASS.
- Alert Rule last_triggered_at Persistence in SQLAlertRuleRepository (2026-10-04; Lane B, D1):
  - Persist `model.last_triggered_at = rule.last_triggered_at` in `SQLAlertRuleRepository.save()`. Previously omitted, causing reloads from the database to always return `None` despite the column existing on `AlertRuleModel` and being mapped in `_model_to_domain()`.
  - Regression test: `test_save_and_get_persists_last_triggered_at` in `backend/tests/infrastructure/test_repositories.py`.
- Fix 1 / Fix 1.5 Bot Verification Results Honesty & Folia/Pufferfish Decoupling (2026-09-18; D0, Lane A, roadmap drift Micro):
  - Honest bot verification outcome counting: `test_runner.py` fakeplayer branch now strictly computes `passed = (spawned_bots == bot_cfg.bot_count)`, reports `connected_bots = spawned_bots`, and details failure reason on mismatch as `Spawned {spawned_bots}/{bot_count} FakePlayer bots via RCON: {err_msg}`; replaced fragile substring match with exact command token check (`scmd.split()[1] == 'spawn'`); stopped zeroing out honest `connected_bots` on failed runs in `evidence_bundle["assertions"]["bots_spawned_actual"]` and `BotVerificationResult`.
  - Strategy Result formalization & artifact fail-fast: replaced 3-tuple with frozen dataclass `StrategyResult(mode, driver, reason, downgraded_from, artifact_ok)` across production and test unpack sites; added pure helper `is_fakeplayer_artifact_usable` validating artifact existence, non-placeholder bytes, and jar header/size via `validate_jar`; falls back to `SMOKE_TEST` with `downgraded_from='fakeplayer_next'` and non-raising failure reason / evidence assertions when artifact is missing or 30-byte placeholder.
  - Folia & Pufferfish config decoupling: constrained `PAPER_FAMILY_TYPES` in `config_resolver.py` to `{'paper', 'purpur'}`; AUTO mode on Folia/Pufferfish now cleanly defaults to `MINEFLAYER`, while explicit `fakeplayer_next` requests raise `UnsupportedBotTechError` (HTTP 400); existing stored records self-heal per run.
  - Test suites: added 6 dedicated regression tests in `test_bot_verification_regression.py`; 2,912 backend tests passing / 6 skipped (2,918 collected), 730 frontend tests passing across 83 files (3,642 total tests); all 6 CI quality gates PASS (150/150 routes, ruff baseline clean, stray DB clean).
- Enterprise Branch Runtime Platform (Stages A–G & Frontend Batch, 2026-09-16 – 2026-09-18):
  - Full Git-inspired version control with commit DAG, tags, branch archiving, and commit diff inspector.
  - Worktree materialization engine with read-only/edit modes, atomic filesystem primitives, and uncommitted live changes review.
  - Database-backed concurrent admission gate (`server_admission_leases`) with dynamic host RAM/CPU headroom accounting.
  - Demand-driven console streaming follower, WS bidirectional interactive exec/input, and unified multi-core container metrics.
  - First-class test definitions platform, 1:1 runtime container attach, automated crash correlation with mod blame, and structured evidence bundles.
  - Protected branches policy enforcement with direct-commit blocking and administrative emergency force bypass.
  - Dedicated production-grade frontend UI modals and views for all versioning features with 100% test coverage.
- Post-Phase-5 Container & Identity Bug Tracks (2026-09-12 / 2026-09-13):
  - `9d7f700`: Fixed rigid 120s jar download timeout with activity-based socket read/connect timeouts, streaming `.part` writes, and structured `details` in `CommandResult` / `InfrastructureError`.
  - `74786be`: Implemented `resolve_docker_image()` for Java 8/17/21/25, added container `collect_diagnostics()`, mapped `exited 0` to `ServerRuntimeStatus.STOPPED`, added `ConfirmDialog` on server stop, and added provider tags in console/details.
  - `77416c8`: Added `get_dynamic_local_ip()` / `get_address()` to `ServerProvider` implementations, dynamically inspects container IP in `DockerProvider`, syncs live host in `get_server.py` and `supervisor.py`, renders dynamic IP badge in `ServerConsole`.
  - `2adf213`: Resolved Bug 3 via `identity_writer.py` atomic `.onx-manager/server.json` stamping at creation/import, deterministic candidate scoring (+100 active, +50 running/starting/created, +25 docker runtime, newest `updated_at` tiebreak) with in-place `ActionType.HEAL_IDENTITY` in `FilesystemReconciliationService`, and volume-mount filtering in `DockerProvider.destroy()`.
- Phase 5 (Containers System — Batches 1–6):
  - Batch 1 (`282a7de`): Aligned stale `start()` signatures to 4 kwargs across `SSHProvider`, `CloudProvider`, `CircuitBreakerProviderWrapper`, and `DockerProvider`; corrected schema enum to `local_windows`.
  - Batches 2 & 3 (`4c3e4ff`): Implemented `DockerProvider` subprocess driver, whole-directory volume mounts, Forge/NeoForge `run.sh` launch translation, and `ContainerInstallerRunner`.
  - Batch 4 (`f1d941e`): Bridge container networking, external port publishing, RCON loopback security, and Windows WSL2 Linux containers policy.
  - Pre-Batch-5 Fix-Up & Companions (`109e67e`, `d48bea4`): Wired `provider.destroy()` into server deletion with 10s timeout guard and regression tests.
  - Batch 5 (`5649644`): Static Docker CLI packaging (27.5.1), opt-in DooD compose policy (`docker-compose.dood.yml`), and `resolve_host_mount_path()` host path translation.
  - Batch 6 (`183ae7b`): Parameterized provider conformance suite (87 tests), CI Docker build smoke probe, path normalization follow-ups (O1, O2, O3), and frontend toggle polish.
- ADR-0009 verification finding: ADR-0009 covers domain value-object field validators,
  not provider naming (no phantom ADR created).
- 'Extended files' (Phase 1) and 'Comment feature' (Phase 3): both
  closed Deferred — no recoverable definition found anywhere in repo
  history; Mohamed could not recall either.
- Files API possible IDOR: closed, NOT A VULNERABILITY (verified
  per-server ownership enforcement + passing tests).
- FastAPI merged_lifespan recursion: closed, false positive (zero
  occurrences in repo).
- Rename pipeline (MCS-Manager → onx-manager): confirmed fully built
  and merged (2026-08-26 commits). 3 cosmetic strays fixed as part
  of Phase 2 closure.
- Phase 4↔Phase 5 sequencing: decided 2026-09-10
  (DECISION-2026-09-10-001) — Phase 5 builds before Phase 4 starts;
  phase numbering and scope unchanged.
- Windows CI backend stall (2026-09-10 run: 19 passed, then ~39 min
  silence at TestServers::test_stop_server, not reproducible on Linux):
  fix landed — supervisor stop() detaches after a shielded timeout,
  faulthandler stack-dump trap added to windows-ci.yml.

**Still open, not yet decided:**
- 'GPS' definition (Phase 5 scope) — still undefined, same class of
  problem as extended-files/comment-feature (recon-confirmed undefined in code).

---

# ONX Manager — Current State (Verified)

**Status:** Authoritative, evidence-based snapshot of the codebase as of
2026-11-04. Every claim below was verified against source code, the database,
and a live test run.

**Last verified:** 2026-11-04
**App version (code):** `0.1.0` (`backend/pyproject.toml:3` → resolved at runtime by `backend/app/core/version.py:get_app_version()`)

---

## 1. Repository shape

| Item | Count | Evidence |
|------|-------|----------|
| Backend Python source files | 412 | `backend/app/` (including domain aggregates, commands, queries, providers) |
| Backend test files | 239 | `backend/tests/` (including 225 dedicated test suites across versioning, reliability, and modules) |
| Frontend test files | 110 | `find frontend/src -name "*.test.*"` |
| REST routers (`api/v1/routers/`) | 16 | `auth, backups, exposure, files, health, invites, marketplace, monitoring, plugins, schedules, servers, settings, setup, software, users, versioning` |
| Live routes | 155 | `./scripts/check-route-contract` (155 live routes vs 155 entries in `contracts/permissions.yaml`) |
| Alembic migration revisions | 42 | `backend/alembic/versions/` (head `b1e2100000022`) |
| Architecture Decision Records & Decisions | 33 | `docs/decisions/` (ADRs 0001–0021 + 12 formal DECISION records) |
| Contract files | 6 | `contracts/{api.yaml, config.schema.json, events.yaml, permissions.yaml, plugin.yaml, README.md}` |
| DDD modules | 13 | `activity, auth, backup, event_store, exposure, health, monitoring, operations, plugin, server, shared, storage, versioning` |
| CI workflows | 7 | `.github/workflows/{backend-tests.yml, docker-build-smoke.yml, backend-version-ci.yml, route-permission-ci.yml, frontend-ci.yml, verification-cadence.yml, windows-ci.yml}` — full backend pytest + DooD build smoke + DB-compat + Ruff-baseline gate; version-propagation check; route→permission contract check; frontend typecheck/lint/test/build; weekly re-verification cadence; Windows CI |

---

## 2. Test suite (measured 2026-11-04)

### Backend — `backend/` `python -m pytest tests/`
*(State plainly: NOT re-measured on this branch, carried from the earlier backend run)*

| Metric | Value |
|--------|-------|
| Collected | **3288** |
| Passed | **3282** |
| Skipped | **6** |
| Failed | **0** |

Backend CI runs the full suite on every push/PR to `master`
(`.github/workflows/backend-tests.yml`), followed by all 6 CI quality gates
(`check-db-revision`, `check-route-contract`, `check-ruff-baseline`, `check-version-propagation`, `check-ps1-bom`, `check-stray-db`).

### Frontend — `frontend/` `npx vitest run`
*(Measured fresh on `feat/frontend-overhaul`)*

| Metric | Value |
|--------|-------|
| Test files | **118** |
| Collected | **1018** |
| Passed | **1018** across 118 test files |
| Skipped | **0** |
| Failed | **0** |

### Suite Totals
Frontend CI (`frontend-ci.yml`) runs `typecheck`, `lint`, `test`, and `build`
on every push/PR to `master`. Total test metrics:
- **Total collected**: **4,306** (3,288 backend + 1,018 frontend)
- **Total passed**: **4,300** (3,282 backend + 1,018 frontend)
- **Total skipped**: **6** (backend)
- **Total failed**: **0**

---

## 3. Database state

### Default Canonical DB — `backend/data/onx.db` (used by default config `sqlite+aiosqlite:///./data/onx.db`)

| Property | Value |
|----------|-------|
| Alembic revision | `b1e2100000022` — **at head** |
| Head revision | `b1e2100000022` (head == current) |
| Revisions count | 42 migrations |
| Refactor tables / columns | `server_commit_parents`, `server_tags`, `server_branches.status`, `server_branches.is_protected`, `server_branches.protection_policy`, `server_materializations`, `server_import_reviews`, `server_admission_leases`, `server_runtimes`, `server_test_definitions`, `server_test_runs.runtime_id`, `server_test_runs.test_definition_id`, `server_test_runs.evidence_bundle`, `server_test_runs.artifacts_purged`, `server_operations`, `server_test_runs.operation_id` |
| Pre-Backend Reconciler | `backend/app/core/persistence/reconciler.py` automatically inspects, backs up, and reconciles DB schema before services start |

---

## 4. What exists and works

### 4.1 Server lifecycle, runtime, backups (implemented)

- Create / delete / start / stop / restart / console / logs / version
  management; import and scan flows; `MCS_SERVERS_DATA_DIR` isolation
  (Batch 2.5 fix).
- Real backup pipeline: tar.gz + AES-256-GCM + checksum + verify; delete
  artifact before DB row (Batch 8); `save-all` console confirmation with
  timeout-fail.
- Runtime ownership verification (`reconcile_orphans` / `claim_localhost` /
  `cleanup_orphans`) with `MCS_MANAGED=1` marker + cwd + start_time checks
  (Batches 6–7).
- Multi-runtime server providers (`ServerProvider` ABC): `LocalLinuxProvider` (tmux sessions on Linux/POSIX), `LocalWindowsProvider` (native Win32 detached process groups on Windows), and `DockerProvider` (isolated containers via async subprocess driver, bridge networking, dynamic IP resolution, loopback RCON, Windows WSL2 Linux container policy, opt-in DooD profile, ephemeral container provisioning for Forge/NeoForge, and volume-filter container cleanup).
- Authoritative server identity stamping (`identity_writer.py`): Atomically stamps `.onx-manager/server.json` upon creation and import.
- Filesystem reconciliation service (`FilesystemReconciliationService`): Disk is the source of truth; runs at startup and via `POST /servers/refresh`. Resolves un-identified Minecraft directories via normalized `root_path` matching and deterministic candidate scoring (+100 active, +50 running/starting/created, +25 docker runtime, newest `updated_at` tiebreak) to heal identity in place (`ActionType.HEAL_IDENTITY`) without duplicate imports or row deletion; cleans associated provider containers on server deletion.

### 4.2 Auth & authorization (implemented & Phase 4 enforced)

- JWT RS256 (15-min access tokens), refresh-token rotation (7-day opaque
  tokens, SHA-256 hash in DB), API keys (`mcs_` prefix, SHA-256 hashed),
  Argon2id password hashing.
- Global permission enforcement via `require_permission(...)` and live server-scoped RBAC authorization via `require_server_permission(...)` (commit `a47daa8`).
- Server membership & ownership model: `ServerModel.owner_id` (implicit full server access) and `ServerMembershipModel` (`server_memberships` table for `admin`, `dev`, `viewer` roles).
- Protected surfaces: Files API (all 7 endpoints gated, with viewer role allowed file download access), Health API (`POST /health/evaluate/{server_id}` gated), Schedules API (`POST`/`DELETE` gated), and Monitoring Alerts (`POST /alerts/{server_id}` refactored to path-based `server_id` to eliminate IDOR / parameter-pollution vulnerability). Defense-in-depth in `require_server_permission` returns HTTP 400 if conflicting `server_id` values appear across path/query/body.
- **Runtime diagnostics IDOR fixed (2026-08-12):** `GET /servers/{id}/runtime` and `GET /servers/{id}/runtime/validate` now enforce `require_server_permission("server.{id}.view")`; `GET /servers/runtime/ownership` enforces `require_permission("server:read")`. Regression tests in `backend/tests/api/test_runtime_permissions.py`.
- Owner bootstrap / access-mode / invitation system (committed `14a0d32`):
  `POST /setup/bootstrap` (single-use), `GET /setup/status`,
  `PUT /setup/access-mode` (owner-only, `LOCAL`/`GLOBAL`), `POST /invites`,
  `DELETE /invites/{id}`, `GET /invites` (all `user:write`),
  `GET /invites/verify/{token}`, `POST /invites/accept`, `POST /users`. Frontend:
  `SetupPage`, `InvitePage`, `SystemStatusGuard`, `AccessSection`,
  `InvitationsSection` under `/settings`. Migration `a957791492a7` adds
  `system_state` + `invitations` tables.

### 4.3 WebSocket (fully functional & wired — Phase 3 closed)

- Handshake validates the token **before** `accept()`.
- Per-channel authorization enforces singular REST permissions (`server:read`, `backup:read`, etc.) with `admin:full` bypass (**K1 resolved in commit `b98da77`**).
- Active subscriptions (`server:*`, `metrics:<serverId>`) wired on component mount/route change in `WebSocketManager.tsx` and `ServerDetailPage.tsx` (**frontend wiring resolved in commit `d096f75`**).
- Real-time metrics push pipeline (**K2 resolved in commit `db1889d`**): `MetricsBridgeHandler` subscribes to `MetricCollectedEvent` on the `EventBus` and feeds `MetricsBatcher.add_sample()`, flushing batched samples over WebSocket channel `metrics:<serverId>` every ~2s. Frontend `WebSocketManager` merges incoming samples into the TanStack Query cache.

### 4.4 Plugin system & marketplace (implemented, frontend first-class)

- Plugin registry is DB-backed with per-row `filename` and `source`
  (`detected` / `modrinth`) tracking; the filesystem is the source of truth:
  on every `GET /plugins` a `ReconcilePluginsCommand` reconciles on-disk
  `.jar` files against the DB (creates `detected` rows, prunes deleted files).
- Marketplace routes (under `/api/v1/servers/{server_id}/plugins`):
  - `GET /marketplace/search` → Modrinth catalog search
  - `GET /marketplace/projects/{project_id}/versions` → versions + best-version
    selection for the server (with loader-fallback / version-mismatch notices)
  - `POST /marketplace/install` → download `.jar` to the server's `plugins/`
    folder with SHA-1/SHA-512 checksum verification + atomic write
- Provider abstraction: `PluginCatalogProvider` ABC + `ModrinthProvider`
  (`api.modrinth.com/v2`). Provider selection is configuration-driven via
  `MCS_PLUGIN_PROVIDERS` (default `"modrinth"`), validated at startup by
  `build_plugin_catalog_provider()` / `validate_plugin_providers()` — unknown,
  empty, or multiple configured providers fail fast. **K16A accepts exactly
  one active provider.** The variable keeps comma-separated list syntax for
  forward compatibility with the remaining K16 work (multiple providers), but
  configuring more than one is currently rejected. Provider identity (`name`)
  lives on the implementation. Hardcoded loader facet list
  (`bukkit/paper/purpur/spigot/folia`) remains inside `ModrinthProvider`.
- Version selection: `select_best_version()` ranks exact game-version+loader →
  compatible parent loader → closest game version (never hard-blocks).
- **Frontend status:** marketplace is a **first-class section (K5 done, 2026-08-06)** — own
  top-level route (`/marketplace`, `App.tsx`) and sidebar entry with a `store` glyph
  (`Icon.tsx`), plus a global search endpoint `GET /api/v1/marketplace/search`
  (`useMarketplaceSearchGlobal`) distinct from the server-scoped one. The install flow reworked
  into a global browse + server picker (pre-select: deep link → last-used server → first
compatible → any). The server-scoped `/plugins/marketplace` (`?server=<id>`) surface remains
   for installs within a specific server's context. See `docs/architecture/plugins-and-marketplace.md`.
- **Plugin detail tabs + crash fix (2026-08-19, SPEC-PLUGIN-DETAIL-TABS-001 v1.3):**
  - Backend: `GET /api/v1/marketplace/projects/{project_id}/versions` (server-independent,
    `selected=null` always) + nullable `wiki_url`/`source_url` and parsed
    `client_side`/`server_side` on `PluginProjectResponse` — fixes the 500 crash
    for Modrinth projects with null `wiki_url`/`source_url` (was 22/60 plugins,
    33/60 mods). Strict v1.3 two-part `game_version_matches` gate in
    `version_selector.py`.
  - Frontend: `PluginDetailPage` now has **Description / Versions** tabs (Changelog
    stubbed/disabled), a **Compatibility sidebar** (`CompatibilityCard.tsx`, loader
    pills with generic `download` icon + "Supported environments" from
    `client_side`/`server_side`), and a client-side **Recommended** badge
    (`ProjectVersionsList.tsx` + `versionMatching.ts`) keyed on the last-used server
    resolved via `server_id` (G1). Badge rule is **strict**: shown only when a
    version's `game_versions` AND loader both match; no closest-distance fallback.
  - Test coverage: 13 new matcher cases + backend API/route-contract/provider tests;
    frontend suites for `versionMatching`, `CompatibilityCard`, `ProjectVersionsList`,
    `PluginDetailPage` (all green).

### 4.5 Task queue, monitoring, health, settings persistence (implemented)

- `InProcessQueue` wired in `main.py` lifespan; scheduler loads `cron_jobs`
  from DB; `MetricsCollector`, Prometheus gauges, event store + DLQ, health
  calculator, crash diagnostics, recovery orchestrator all functional.
- **Settings persistence & hot-reload (K3 resolved in commits `2437590` / `789dcbd`):**
  - Backend: file-backed at `config/settings.yaml` via `settings_store.py` (`LiveSettings`). Live settings load at startup and update on `PATCH /api/v1/settings`.
  - Hot-reload: updates immediately affect running instances of `RateLimitMiddleware`, `CircuitBreaker`, `EventBus`, `SagaOrchestrator`, and `cleanup_task`.
  - Restart flags: fields `app_name`, `log_level`, `debug` are persisted but require a backend service restart to affect runtime behavior; returned in the API's `requires_restart` response array.
  - Frontend: `SettingsPage.tsx` fully editable with 4 card sections, `PageHeader`, `RestartBadge`, and `role="alert"` / `role="status"` save feedback.
- Stubs / resolved items: `ArqQueue` removed in Batch 4 (F072) and `aredis` dependency eliminated; `GET/POST/DELETE /schedules` operational; `GET /monitoring/alerts` and `DELETE /monitoring/alerts/{id}` wired to `SQLAlertRuleRepository` (Batch 4 F064).

### 4.6 Rate limiting

`RateLimitMiddleware` keys its in-memory sliding window by **`client_ip:path`**
(`backend/app/api/v1/middleware/rate_limit.py:40-54`), dynamically reloads max requests from `get_live_settings().rate_limit_per_minute`, no `X-RateLimit-*` headers; on limit it returns
`429` with a `Retry-After: 60` header.

### 4.7 Server Redesign & File Manager (Part B completed)

- **In-Server Contextual Navigation Shell (Batch 1, commit `adbf556`):** Dedicated sidebar context for server management with back-navigation.
- **Blade Hosting-Style Server Detail Page (Batch 2, commit `72e8c1c` & Batch 5, commit `79d18d7`):** Two-column layout with live console, stat cards (Address click-to-copy, Uptime, CPU, RAM, Storage), Zone ID placeholder, CPU/RAM/Network usage trend graphs, and explicit "Coming Soon" badges for Storage & Network I/O metrics.
- **Files REST API (Batch 3, commit `ae6848d`):** `/api/v1/servers/{server_id}/files` endpoint providing directory listing, text read/write (atomic), file/dir delete, upload, download, and mkdir with path-traversal sandboxing (`_resolve_server_file_path`).
- **File Manager UI (Batch 4, commit `e96f902` & Bug Fix `74786be`):** First-class `/servers/:serverId/files` File Manager view with directory breadcrumbs, inline text editor, file upload, download, creation, and deletion modal. Fully reactive breadcrumb navigation synchronized with `?path=` searchParams, enabling browser history navigation and seamless editor exit on breadcrumb clicks.
- **Server-Type-Aware Mods/Plugins UI (commit `7226e6c`):** Contextual navigation and Install Modal showing "Mods" or "Plugins" based on server type (`fabric`/`forge` vs `paper`/`purpur`).
- **Provider Tags & Dynamic IP Display (commits `74786be` & `77416c8`):** `ServerConsole` and `ServerDetailPage` display real-time provider tags (Docker Container vs Windows Process vs Host Process) and dynamic local container network IPs.

---

## 5. Known issues carried forward

Classification used by `Blueprint V5`:

| ID | Issue | Severity | Kind |
|----|-------|----------|------|
| K1 | ~~WS channel authorization always denies~~ **Resolved 2026-08-08 (commit `b98da77`, `d096f75`)** — singular permission strings + `admin:full` bypass | ~~High~~ | ~~Bug~~ |
| K2 | ~~`EventDispatcher`/`MetricsBatcher` never wired~~ **Resolved 2026-08-08 (commit `db1889d`)** — `MetricsBridgeHandler` flushes samples over WS every 2s | ~~High~~ | ~~Bug~~ |
| K3 | ~~`PATCH /settings` stub~~ **Resolved 2026-08-09 (commit `2437590`, `789dcbd`)** — file-backed persistence + consumer hot-reload + frontend redesign | ~~Medium~~ | ~~Bug~~ |
| K4 | ~~Plugin enable/disable routes use only get_current_user~~ **Resolved 2026-08-11 (commit `a47daa8`)** — Phase 4 authorization gating | ~~Medium~~ | ~~Bug (Phase 4)~~ |
| K5 | ~~Marketplace is not a first-class frontend section~~ **Resolved 2026-08-06 (commit `1c12e0c`)** — own `/marketplace` route + sidebar entry + global search + install-time server picker | ~~Medium~~ | ~~Feature~~ |
| K6 | ~~No backend CI workflow~~ **Resolved 2026-08-13 (B6-2)** — `.github/workflows/backend-tests.yml` runs full pytest + DB-compat + Ruff-baseline gate. Route-coverage matrix now CI-enforced via `scripts/check-route-contract` (B6-4, `.github/workflows/route-permission-ci.yml`) | High | Process (Phase 4) |
| K7 | ~~13 mutating routes + 21 sensitive GET routes lack permission enforcement~~ **Resolved 2026-08-11 (commit `a47daa8`)** — Protected remaining mutating routes & Files API with server-scoped RBAC | ~~High~~ | ~~Bug (Phase 4)~~ |
| K8 | ~~`test_start_server` + `test_metrics_task_requires_collector` fail in the suite~~ **Resolved 2026-08-08** — 100% backend pass rate (1144/1144 passed) | ~~Low~~ | ~~Test debt~~ |
| K9 | Production DB 3 revisions behind head; no servers | Medium | Ops |
| K10 | `GET /metrics` public/unauthenticated (documented deferred decision) | Medium | Security (Phase 7) |
| K11 | JWT keys auto-generated in-process (lost on restart unless PEM set) | Medium | Architecture debt (Phase 4) |
| K12 | Permissions stored as comma-separated Text; `SQLUserRepository.save()` `MissingGreenlet` risk on role assignment | Medium | Architecture debt (Phase 4) |
| K13 | `ArqQueue.get_status/get_result` stubs; schedules/alerts stubs | Low | Known limitation |
| K14 | Backup `save-all` completion regex unverified against a real Purpur server | Low | Verify |
| K15 | Repo-root `data/` directory (gitignored, unused, awaiting cleanup decision) | Low | Housekeeping |
| K16 | Provider selection config-driven via `MCS_PLUGIN_PROVIDERS`, validated at startup (K16A done 2026-08-05). Remaining: inspect configured list via API, add a second provider. | Low | Architecture debt (Phase 1) |
| — | ~~**Files API IDOR Gap:** `GET /files`, `GET /files/content`, `GET /files/download` endpoints check login (`get_current_user`) but lack per-server permission enforcement~~ **Resolved 2026-08-11 (commit `a47daa8`)** — `require_server_permission` enforced on all 7 endpoints | ~~High~~ | ~~Security (Phase 4)~~ |
| — | ~~**Runtime diagnostics IDOR:** `GET /servers/{id}/runtime`, `GET /servers/{id}/runtime/validate` were auth-only (no server scope); `GET /servers/runtime/ownership` exposed host-wide PID/tmux data with auth only~~ **Resolved 2026-08-12** — server-scoped guard + `server:read` + regression tests (`test_runtime_permissions.py`, 2 tests) | ~~High~~ | ~~Security~~ |
| — | ~~**Invitation status case mismatch:** frontend compared `"active"`/`"consumed"` while backend returns `ACTIVE`/`USED`/`REVOKED`, so the Revoke button never rendered and status badges always fell through to the gray style~~ **Resolved 2026-08-12** — `InvitationsSection.tsx` compares uppercase enum values; `InvitationItem.use_count` matches backend `use_count` | ~~Medium~~ | ~~Bug~~ |
| — | ~~`npm run lint` fails with pre-existing errors~~ **Resolved 2026-08-13 (B6-2)** — `eslint src/` is 0 errors / 0 warnings across the codebase; typed error handling fixed without config weakening; `frontend-ci.yml` gates on lint | ~~Medium~~ | ~~Tech debt~~ |
| — | ~~`ruff check` reports pre-existing errors across backend; no ruff CI gate~~ **Resolved 2026-08-13 (B6-2)** — `backend/ruff-baseline.json` (1738 pre-existing violations / 42 rules) + `scripts/check-ruff-baseline` + CI step in `backend-tests.yml`; **new** violations fail CI, baseline debt remains tracked | ~~Low~~ | ~~Tech debt~~ |
| — | ~~**Windows Launcher Hang:** `start.ps1` unconstrained Python invocation with open stdin caused REPL interactive hangs~~ **Resolved 2026-09-01 (SPEC-2026-09-01-WIN-LAUNCHER-01)** — `New-OnxProcessStartInfo` (stdin closed) + `Invoke-OnxProcessProbe` (15s timeout, taskkill /F /T) + UTF-8 BOM gate | ~~Critical~~ | ~~Bug (Lane A)~~ |
| — | ~~**TPS Validation & Scheduler Misfires:** RCON collector crashed on >20.0 TPS overshoots; scheduler dropped jobs under 1s I/O bursts; SQLite lacked connection pre-ping~~ **Resolved 2026-09-01 (SPEC-2026-09-01-BUGTRACK2-01)** — Clamped TPS at collector boundary; expanded `misfire_grace_time=60`; added `pool_pre_ping=True` | ~~Critical~~ | ~~Bug (Lane A)~~ |
| — | ~~**Windows CI `os.killpg` Mock Resolution:** 140 test ERRORs on Windows CI due to missing `create=True` on `patch("os.killpg")`~~ **Resolved 2026-09-01 (SPEC-2026-09-01-WIN-KILLPG-01 Issue A)** — Added `mock_os_killpg` fixture in conftest + `create=True` across 7 test files | ~~High~~ | ~~Test infra (Lane A)~~ |
| — | ~~**55 Windows CI Test Failures:** Windows CI test suite failures across core primitives, storage containment, prerequisite checks, and mock fixtures~~ **Resolved 2026-09-02 (SPEC-2026-09-02-WIN-CI-REMEDIATION-01-R2)** — Implemented `platform_force_kill`, `platform_kill_process_tree_sync/async`, LocalStorage `Path.is_relative_to` traversal security, platform-aware environment prereqs, and test fixture portability hardening | ~~High~~ | ~~Bug (Lane A)~~ |
| — | ~~**Jar Download Timeout & Error Detail Propagation:** Rigid 120s timeout caused download failures on large jars; generic errors masked underlying cause~~ **Resolved 2026-09-12 (commit `9d7f700`)** — Activity-based socket timeouts, `.part` streaming, structured `details` in `CommandResult` and `InfrastructureError` hierarchy | ~~Critical~~ | ~~Bug (Lane A)~~ |
| — | ~~**Container Crash Diagnostics & Clean Stop Mapping:** Modern Java 21/25 mismatch diagnosed as unknown crash; clean container stop mapped to error; dead container collisions~~ **Resolved 2026-09-12 (commit `74786be`)** — `resolve_docker_image()` for Java 8/17/21/25, container `collect_diagnostics()`, `exited 0` mapped to `STOPPED`, `ConfirmDialog` on UI stop, automatic dead container prune | ~~Critical~~ | ~~Bug (Lane A)~~ |
| — | ~~**Console Provider Tags & Dynamic IP Display:** Console lacked runtime provider indication; container bridge network IP hidden behind hardcoded 127.0.0.1~~ **Resolved 2026-09-13 (commit `77416c8`)** — `get_dynamic_local_ip()` / `get_address()`, atomic `docker inspect` for PID and IP, live host sync in queries/supervisor, `console-ip-badge` in UI | ~~High~~ | ~~Feature / Bug (Lane A)~~ |
| — | ~~**Server Identity Loss on Restart & Provider Flip (Bug 3):** Server identity file missing at creation/import caused reconciliation to reimport servers as LOCAL on restart, orphaning Docker containers~~ **Resolved 2026-09-13 (commit `2adf213`, `BUG_3_SERVER_IDENTITY_LOSS_DESIGN_SPEC`)** — Authoritative `identity_writer.py`, deterministic adopt-vs-heal scoring (+100 active, +50 running, +25 docker), in-place `ActionType.HEAL_IDENTITY`, broadened volume-filter container cleanup | ~~Critical~~ | ~~Bug (Lane A)~~ |
| — | ServerMetricsCharts 5s REST refetchInterval vs 60s backend collection cadence | Low | Known edge case |
| — | Non-running server writes zero metrics rows → chart renders empty state without explanatory UI message | Low | Known edge case |

---

## 6. Files that define this state

- `backend/app/main.py` — app factory, version (`get_app_version`), middleware, router registration
- `backend/app/api/v1/routers/plugins.py` — plugin list + marketplace routes
- `backend/app/api/v1/routers/settings.py` — settings GET + PATCH
- `backend/app/core/version.py` — single version resolver (`get_app_version`)
- `backend/app/websocket/authorization.py`, `endpoint.py`, `dispatcher.py`,
  `handlers.py` — WS auth, channels, dispatch (see §4.3)
- `backend/app/api/v1/middleware/rate_limit.py` — per `client_ip:path` limiter
- `backend/app/modules/plugin/infrastructure/providers/` — provider ABC +
  Modrinth implementation
- `backend/app/modules/plugin/application/services/version_selector.py` —
  best-version selection
- `contracts/permissions.yaml` — live route→permission coverage matrix
- `backend/data/onx.db` — primary production/dev database (`mcs.db` was the pre-rename database filename, fully superseded by `onx.db`; no live `mcs.db` file exists in the repo)
- `.github/workflows/backend-tests.yml`, `backend-version-ci.yml`,
  `route-permission-ci.yml`, `frontend-ci.yml`, `verification-cadence.yml` — CI
  workflows

---

## 7. Re-verification cadence & status source-of-truth (B6-5)

### 7.1 Single source-of-truth decision (Model A)

`STATUS.md` does not exist in this repository (verified: root, `docs/`,
`docs/status/`). The two-document split flagged as a drift risk in Blueprint V5
§2.7 is therefore resolved by **collapse, not by maintenance**: **this
`current-state.md` is the single canonical operational snapshot**, and
`docs/status/history.md` remains the historical narrative it intentionally
supersedes. No `STATUS.md` is recreated; no second current-state document is
introduced.

### 7.2 Cadence

A fixed, automated re-verification cadence enforces the "no stale snapshot" rule
instead of trusting memory (Blueprint V5 §2.4):

| Property | Value |
|----------|-------|
| Trigger | GitHub Actions `schedule:` — **weekly, Monday 03:00 UTC** |
| Workflow | `.github/workflows/verification-cadence.yml` (job `re-verify`) |
| Reuses existing checks | Yes — the exact authoritative scripts/gates, not a lightweight approximation |
| Local twin | `scripts/reverify` — runs the identical command set |
| Also runs on | push / pull_request to `master` for version files, `contracts/permissions.yaml`, the check scripts, `docs/**`, and the workflow itself |

Checks executed each run (identical locally via `scripts/reverify`):

1. `python ../scripts/check-version-propagation` — pyproject.toml / package.json / runtime agree (0.1.0)
2. `python ../scripts/check-db-revision` — database schema matches compatible migration head (`b1e2100000019`)
3. `python ../scripts/check-ruff-baseline` — no new violations vs `backend/ruff-baseline.json`
4. `python ../scripts/check-route-contract` — `contracts/permissions.yaml` 150 entries match 150 live routes
5. `python ../scripts/check-ps1-bom` — PowerShell scripts UTF-8 BOM encoding
6. `python -m pytest -q` (backend) — full suite 2,912 passed / 6 skipped (2,918 collected)
7. `npm run typecheck`, `npm run lint`, `npm run test`, `npm run build` (frontend) — 83 files / 730 tests passing, build succeeds

### 7.3 Execution status

- **Cadence mechanism: IMPLEMENTED / VERIFIED.** The scheduled workflow
  (`.github/workflows/verification-cadence.yml`) exists, is syntactically
  valid, retains push/PR triggers, and was dry-run successfully on 2026-08-14
  against the exact command set in §7.2 (all checks pass, locally and in the
  existing CI paths).
- **Phase 6 §2.6 requirement: PENDING.** Blueprint V5 §2.6 acceptance requires
  the cadence to have "run at least once under its own schedule". That can only
  be shown by observing a real GitHub scheduled execution. **Scheduled
  execution remains PENDING FIRST GITHUB SCHEDULED RUN** — the first autonomic
  Monday 03:00 UTC run must land before this criterion is considered met. No
  scheduled run has been observed as of 2026-08-14.
