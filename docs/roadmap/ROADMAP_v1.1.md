# ONX Manager — Real Engineering Roadmap
## v1.1 — Revised after external review

**Status:** ACTIVE LIVING ROADMAP — Phases 0, 1, 2, 3, 4, 5, and Core Architecture (Enterprise Branch Runtime Stages A–G + Frontend Batch) DONE / CLOSED; Phase 6 (Final Installs / Wrap-up) READY. Each phase is scoped at the level needed to write individual Design Specs per stage.
**Supersedes:** `ROADMAP_v1.md` (2026-09-01 — external review found: no ground-truth baseline phase, a circular dependency between Phase 1 and Phase 2, branding conflated with functional UX, an unrecorded architecture-reorder decision, and looser language than the actual exit criteria implied). This version keeps every fact from v1.0 and fixes those five issues plus several smaller ones below.
**Phase order:** dictated by Mohamed — ground truth first (new in v1.1), then bugs, backend, frontend, community-driven features, containers, core architecture refactor, install/wrap-up, and branding/UI polish **last**.

## Current Release Objective

> Prepare ONX Manager for a safe, verified, cross-platform open-source release — every claim in this roadmap backed by evidence gathered in this session or later, not carried forward from a prior document.

Any task, anywhere in this roadmap, should be explainable as serving this objective, or it doesn't belong in the current release scope.

---

## Phase 0 — Ground Truth / Baseline Freeze *(new in v1.1)*

**Why this phase exists:** v1.0 mixed "figure out what's actually true" with "fix what's broken" inside Phase 1, which is why Phase 1 and Phase 2 ended up needing the same Windows-lifecycle answer — a genuine circular dependency an external review caught. This phase exists solely to establish facts. No fixing happens here.

**Scope — establish and freeze, with evidence, not assumption:**

1. **Full test run, both platforms.** ✅ **VERIFIED (2026-09-02):** Linux CI and Windows CI suites run and verified green. Backend: 2,149 passed, 2 skipped, 0 failed; Frontend: 574 passed, 0 failed; CI quality gates: 5/5 PASS (`check-db-revision`, `check-ruff-baseline`, `check-version-propagation`, `check-route-contract`, `check-ps1-bom`). *(Note: A 6th gate, check-stray-db, was added on 2026-09-15 under commit 2aef9d8; current gate baseline is 6/6 PASS).*
2. **Windows lifecycle ground truth.** ✅ **RESOLVED & VERIFIED (2026-09-02):**
   - *Live code status:* YES, live code. `LocalWindowsProvider` is registered in `provider_factory` (`backend/app/modules/server/infrastructure/providers/__init__.py:20`) and is selected automatically on Windows (`default_provider_for_platform() == "local_windows"`).
   - *Execution mechanism:* Spawns detached processes via `subprocess.Popen` with `creationflags = CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS | CREATE_NO_WINDOW` and `stdin=subprocess.PIPE` (supporting `/stop` and `save-all` graceful console shutdown before killing). It does **NOT** use the Win32 Job Objects API. Process liveness and tree cleanup are managed via `platform_pid_alive()` (`OpenProcess` + `GetExitCodeProcess` with `PROCESS_QUERY_LIMITED_INFORMATION` / `STILL_ACTIVE`) and `taskkill /F /T /PID` in `app.core.process_utils`.
   - *W-01–W-06 status:* All 6 historical design blockers from `docs/runtime/2026-08-29-windows-lifecycle-final-review.md` are resolved in code: W-01 (`running_start_time` DB persistence & `post_running_grace_seconds` setting verified in `test_windows_lifecycle_w01.py`), W-02 (`local_windows.py` provider rewrite verified in `test_local_windows_provider.py`), W-04 (`supervisor.py` exception boundary), W-05 (reconciliation grace window in `runtime_reconciliation.py`), and W-06 (`process_utils.py` cross-platform PID primitives). **Zero W-01–W-06 blockers remain.**
   - *Process survival:* Detached processes spawned with `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS` decouple from the backend process group, allowing managed servers to survive backend shutdown while preserving clean PID tracking upon restart.
3. **`preflight.py` hang ground truth.** ✅ **RESOLVED & VERIFIED (2026-09-01):** Fixed per `SPEC-2026-09-01-WIN-LAUNCHER-01`. Root cause was unconstrained native Python invocations without STDIN lockdown causing REPL interactive hangs. Fixed via `New-OnxProcessStartInfo` shared PSI factory (mandatory `RedirectStandardInput=$true` + `StandardInput.Close()`), `Invoke-OnxProcessProbe` with `taskkill /F /T /PID` tree-kill on timeout, and `Invoke-OnxProcessSupervised`.
4. **Repo/DB state.** ✅ **VERIFIED (2026-09-02, at Phase 0 baseline time):** Alembic head was `b1e2100000009` (29 migrations; current repo head is 43 migrations, `b1e2100000023`). Git state clean on master. The `_archive/` directory at repo root houses pre-reorganization artifacts. **Version documentation drift (CLOSED FINDING):** Documentation previously carried stale `"4.0.0"` references (historical artifact from earlier planning); actual code has been uniformly `0.1.0` across `pyproject.toml`, `package.json`, and runtime `get_app_version()` since commit `bb92fac7` (2026-08-26). All active documentation, test fixtures, and state files were systematically synchronized to `0.1.0` under `SPEC-2026-09-02-CLEANUP-AND-FULL-AUDIT-01`.
5. **Old-roadmap claims spot-check.** ✅ **VERIFIED (2026-09-02):** Workstreams A, B, and C spot-checked and confirmed implemented in code: Workstream A (plugin markdown rendering in `PluginDetailPage.tsx`, 13/13 tests pass), Workstream B (diagnostics leak prevented in `diagnostics.py` and `get_runtime_diagnostics.py`), and Workstream C (Forge / NeoForge provisioners in `forge_provisioner.py` and `neoforge_provisioner.py`).

**Gate:** Phase 0 has an owner and a hard expectation — this is investigation, not a place to live indefinitely. Target: resolved within the time it takes to run the test suites and do the two verification passes (§2, §3 above) — not an open-ended research phase.

**Exit criteria:** The Windows-lifecycle and `preflight.py` questions each have one evidence-backed answer, recorded. This baseline is then **frozen** — Phase 1 classifies against it, Phase 2/3 fix against it; nothing here gets silently re-investigated later without a new decision record.

---

## Phase 1 — Bug Triage & Classification *(re-scoped in v1.1 — diagnosis and routing, not deep fixes)*

**Goal:** every item below reaches a **verified disposition** — fixed (if small and self-contained enough to close right here), or routed to Phase 2/3 with a Lane + Decision Level, or explicitly deferred with a decision record. *(v1.0 said "ALL known bugs, no exceptions" — too strong given the actual exit criteria always allowed deferral/reclassification; this wording matches what the system actually does.)*

Using Phase 0's frozen baseline as input, classify:

| Item | Lane | Likely routing |
|---|---|---|
| Windows lifecycle (whatever Phase 0 found it to actually be) | A (auto-critical) | ✅ Resolved & live — `LocalWindowsProvider` active in `provider_factory`; W-01–W-06 blockers closed; verified in `test_local_windows_provider.py` |
| `preflight.py` hang (whatever Phase 0 found it to actually be) | A (auto-critical) | ✅ Already fixed & verified (`SPEC-2026-09-01-WIN-LAUNCHER-01`) — closed |
| Fresh-clone BOM/encoding hang | A | ✅ Already fixed & verified — closed, no routing needed |
| Python-detection loop hang | A | ✅ Already fixed & verified — closed, no routing needed |
| Bug track 2 (TPS anomaly, scheduler skips, SQLAlchemy pool warnings) | A (auto-critical) | ✅ Already fixed & verified (`SPEC-2026-09-01-BUGTRACK2-01`) — closed |
| Syntax highlighting broken | B | → Phase 3 |
| "Extended files" issue | Deferred — Closed | Closed (2026-09-08) — exhaustive inspection across git history, archives, and code found no recoverable definition; the term was introduced undefined by Mohamed in commit 8b6a0c7 and is no longer recalled. Reopen if the underlying problem is observed again in production use. |
| Comment feature incomplete | B | → Phase 3 |
| Files API possible IDOR | Closed — NOT A VULNERABILITY | Verified 2026-09-08: all 7 file-touching endpoints enforce per-server ownership/membership via require_server_permission before any filesystem access; confirmed by existing passing cross-server and path-traversal tests. |
| ROADMAP.md Workstream A/B/C claims | N/A — this is a documentation/state-integrity check, not a bug | Resolved in Phase 0 §5, not a Phase 1 bug item |
| Rename pipeline final status | N/A — state-verification task | Confirmed built and merged (2026-08-26 commits 51bbc6c/cb6816a/309e5c1/128489c, verified via git merge-base --is-ancestor into master 2026-09-08). 3 cosmetic strays found and fixed same day (UPnP description strings, 2 stdlib logger names, 4 frontend localStorage keys). |
| FastAPI `merged_lifespan` recursion | Closed — false positive | Verified 2026-09-08: zero occurrences of merged_lifespan anywhere in the repo outside this roadmap doc; only a plain lifespan exists in backend/app/main.py. |
| Windows CI first-run failures | A (surfaces real Phase 2 work) | ✅ Already fixed & verified (`SPEC-2026-09-02-WIN-CI-REMEDIATION-01-R2`: 0 failed, 0 errors, green on GitHub Actions) — closed |

**Exit criteria:** every row above has moved from "?" to a routed destination. Nothing is fixed *in* Phase 1 beyond what's trivially self-contained; the deep work happens in Phase 2/3 where it can be scoped properly instead of turning this phase into what the external review correctly called a "bug graveyard."

**Phase 1 status: CLOSED (2026-09-08).** All 13 rows have a routed disposition — 6 closed pre-existing, 2 routed to Phase 3, 1 deferred, 2 closed as not-real, 2 N/A.

---

## Phase 2 — Backend Stabilization

Receives everything routed here from Phase 1. Status of known contents:

- Windows lifecycle real implementation/fix: ✅ Implemented & verified (`LocalWindowsProvider` live in `provider_factory`; W-01–W-06 closed; verified in `test_local_windows_provider.py` and `test_windows_lifecycle_w01.py`).
- `preflight.py` fix: ✅ Fixed & verified (`SPEC-2026-09-01-WIN-LAUNCHER-01`).
- Bug track 2 items: ✅ Fixed & verified (`SPEC-2026-09-01-BUGTRACK2-01`).
- Full backend suite green on **both** Linux and Windows CI: ✅ Verified (2,339 passed, 5 skipped, 0 failed of 2,344 collected; frontend 642/642 across 75 files; `SPEC-2026-09-02-WIN-CI-REMEDIATION-01-R2`).
- Re-verify the 5 CI quality-gate scripts genuinely pass: ✅ Verified (5/5 PASS; expanded to 6/6 PASS on 2026-09-15 with `check-stray-db`).
- Workstream B (diagnostics-leak) re-verification: ✅ Verified in code.
- Files API IDOR: Closed — NOT A VULNERABILITY (verified 2026-09-08: per-server ownership/membership enforced before any filesystem access; cross-server and path-traversal tests pass).
- FastAPI `merged_lifespan` recursion: Closed — false positive (verified 2026-09-08: zero occurrences outside this doc; only a plain lifespan in backend/app/main.py).

**Exit criteria:** all named items verified in code/CI, no unresolved routing from Phase 1.

**Phase 2 status: CLOSED (2026-09-08).** All 8 tracked items verified; Rename pipeline confirmed built (see below); 3 cosmetic rename strays fixed in this pass.

## Phase 3 — Frontend Stabilization *(now also carries functional UX/reliability fixes — see Phase 7 note)*

- ~~Syntax highlighting fix~~ — Verified working (2026-09-08): CodeEditor.tsx correctly handles all 6 claimed languages (JSON/YAML/TOML/properties/shell/plaintext), worst case is an unstyled plaintext fallback with no crashes; 9 dedicated tests + 21/21 re-run pass. The original 'broken' framing was stale — like 'extended files,' it was introduced undefined in commit 8b6a0c7 with no antecedent report. Closed as verified, not a fix.
- ~~Comment feature completion~~ — Closed as Deferred (2026-09-08), same treatment as 'extended files': zero definition recoverable anywhere in the repo (no 'comment' references in frontend/src/server_manager/, no antecedent in the predecessor roadmap, no newer trace). Reopen if the underlying need resurfaces with a concrete definition.
- ~~"Extended files" issue~~ — Closed in Phase 1 (2026-09-08) as Deferred; removed from Phase 3 scope. Reopen here only if the underlying problem resurfaces.
- ~~Workstream A re-verification~~ — Confirmed, no regression (2026-09-08): 13/13 tests, GFM markdown rendering still correct in PluginDetailPage.tsx.
- **Any functional UX or reliability fix discovered along the way lands here, not in Phase 7.** Phase 7 is visual/brand polish only — see the split below.
- ~~Full frontend suite green on both Linux and Windows CI~~ — Confirmed (2026-09-08): 75 files / 642 tests passing; Windows CI green per the Phase-2-closure push (commit e17da25's CI run).

**Exit criteria:** all named items verified in code/tests, no unresolved routing from Phase 1/2.

**Phase 3 status: CLOSED (2026-09-08).** Syntax highlighting and Workstream A confirmed already-working; comment feature closed Deferred (no recoverable definition); full suite green.

## Phase 4 — Feature Build from Community Feedback Pool

**Status:** DONE / CLOSED (2026-09-14) — All 5 Features Built, Verified, and Closed (Feature 1: Git-Inspired Versioning & Isolated-Testing System; Feature 2: Test Environment, merged into F1; Feature 3: Custom Mod Support; Feature 4: Change History Log; Feature 5: Better Log/Crash Readability). Full suite: 3,397 tests (2,697 backend, 700 frontend across 78 test files), 5/5 CI quality gates PASS.
**Design Spec:** [`docs/design/PHASE_4_COMMUNITY_FEATURES_DESIGN_SPEC.md`](../design/PHASE_4_COMMUNITY_FEATURES_DESIGN_SPEC.md) (Approved 2026-09-13)

Features (priority order, from r/admincraft feedback pool, updated per DECISION-2026-09-12-001):

1. Git-inspired versioning & isolated-testing system (redefined via [DECISION-2026-09-12-001](../decisions/DECISION-2026-09-12-001.md) from bounded transparent update system: branch/commit tracking, isolated test containers, multi-node groundwork; incorporates rollback/proceed/disable & failed-mod list). CLOSED (commit 0f2820f).
2. Test environment (temporary test container/server — dual-mode: files-based and container-based enabled by Phase 5 closure). Merged into Feature 1. CLOSED (commit 0f2820f).
3. Custom mod support (user-supplied non-catalog mods, Forge/NeoForge/Fabric/Quilt inspection and targeting). CLOSED (commit 631c05d).
4. Change history log (durable audit and domain-event trail for server lifecycle and configuration changes). CLOSED.
5. Better log/crash readability (structured log streaming, crash report extraction and classification, syntax/severity highlighting). CLOSED (commit 63f2d41).

**Dependency on Phase 5 — RESOLVED & UNBLOCKED (2026-09-12).** Mohamed's decision: the test-environment isolation backend is a **permanent user-facing choice**, not a temporary stand-in — the product ships with both a **files-based mode** and a **container-based mode**, selectable by the user. With Phase 5 complete and verified, the container backend is fully implemented and available natively for feature #2, alongside files-based execution.

**Scope update — ACCEPTED (2026-09-12, DECISION-2026-09-12-001).** Feature 1 redefined as a standalone git/CI-CD-inspired subsystem serving as the product's core differentiator.

**Build-order update — COMPLETED (2026-09-12, DECISION-2026-09-10-001).** Phase 5 (Containers System) executed first across all 6 stages and is now CLOSED. Phase 4 is unblocked to begin its design specs and feature implementations.

## Phase 5 — Containers System

**Status:** CLOSED (2026-09-11) — All 6 Stages Verified and Complete (Stage 1: Signature Alignment & Schema; Stages 2 & 3: Runtime Driver & RCON; Stage 4: Network & Windows WSL2; Stage 5: DooD Policy; Stage 6: Provider Conformance Suite & Polish)  
**Design Spec:** [`docs/design/PHASE_5_CONTAINERS_SYSTEM_DESIGN_SPEC.md`](../design/PHASE_5_CONTAINERS_SYSTEM_DESIGN_SPEC.md) (Approved 2026-09-11)

Scope: replace host-level tmux/process execution with isolated per-server Docker containers across Linux/macOS/Windows. Also covers port-forward library testing — **"GPS" is a blocked item, not committed scope, pending Mohamed's definition of what it refers to (confirmed undefined in code as of 2026-09-10).**

The approved design establishes 12 core architectural decisions:
1. *CLI Subprocess Driver:* Continue CLI-subprocess driver via tokenized `asyncio.create_subprocess_exec` (zero extra dependencies, async-native, avoids shell-injection risks).
2. *In-Place Refactor:* Refactor existing `DockerProvider` in-place rather than rewriting.
3. *Volume Mount Contract:* Whole-directory bind mount (`server_dir` → `/data`) preserving File Manager, Backup, and Diagnostics interoperability.
4. *Launch Translation:* Deterministic dual translation supporting both standard JARs and Forge/NeoForge `run.sh` entrypoints with CPU pinning.
5. *Provisioning Location:* Host-side provisioning default with ephemeral container fallback (`ContainerInstallerRunner`) when host Java is absent.
6. *Network Model:* Bridge container networking with published host ports (`-p`), allowing playit.gg, UPnP, and Cloudflare to attach to `127.0.0.1:{port}` with zero exposure code changes.
7. *Windows Policy:* Windows policy mandating WSL2 backend in Linux Containers mode with forward-slash path normalization and `ping()` health gating.
8. *Signature Alignment:* Align stale 2-kwarg `start()` signatures to the 4-kwarg `ServerProvider` ABC across all providers.
9. *Schema Enum Correction:* Correct config schema enum from `"local_win"` to `"local_windows"`.
10. *Test Conformance:* Two-tiered test plan: 100% mocked unit contract tests in CI, plus explicitly gated live-daemon tests (`@pytest.mark.docker`).
11. *Creation-Time Selection:* Creation-time provider selection in API payload, preflight `ping()` validation gate, and frontend wizard toggle.
12. *DooD Compose Policy:* Docker-outside-of-Docker policy for ONX Compose deployments: native host primary support, with an opt-in profile (`docker-compose.dood.yml`) explicitly documenting host socket privilege escalation risks.

## Core Architecture — Enterprise Branch Runtime Platform (Stages A–G & Frontend UI Batch)

**Status:** DONE / CLOSED (2026-09-18) — Stages A through G backend and the complete 4-stage Frontend UI Batch (Stages B, C, F, G) built, verified, and merged. Full suite: 3,636 tests (2,906 backend, 730 frontend across 83 files), 6/6 CI quality gates PASS (150/150 API routes).
**Design Specs:** [`docs/design/testing-system-refactor/`](../design/testing-system-refactor/) (Specs 01, 03, 04, 05, 06, 07, 08)
**Governing Decision Records:** [`DECISION-2026-09-16-001`](../decisions/DECISION-2026-09-16-001-enterprise-branch-runtime-architecture.md), [`DECISION-2026-09-17-001`](../decisions/DECISION-2026-09-17-001-stage-b-scope.md), [`DECISION-2026-09-17-002`](../decisions/DECISION-2026-09-17-002-runtime-entity-attach-model.md), [`DECISION-2026-09-17-003`](../decisions/DECISION-2026-09-17-003-testdefinition-new-entity.md), [`DECISION-2026-09-18-001`](../decisions/DECISION-2026-09-18-001-stage-g-protected-branches.md), [`DECISION-2026-09-18-002`](../decisions/DECISION-2026-09-18-002-enterprise-versioning-frontend-batch.md).

Scope and delivery summary:
- **Stage A — Domain Reconstruction:** Formalized domain models (`Project`, `Repository`, `Commit`, `Branch`, `Revision`, `Materialization`, `Runtime`, `PersistentDataset`, `Run`), state machines, and ADRs 0013–0016. (Commit `e72a219`)
- **Stage B — Real Version Control:** Commit DAG ancestry (`server_commit_parents`), branch lifecycle status column (`server_branches`), immutable tags (`server_tags`), deterministic diffing, and merge commit support. (Commit `641ea58`, migration `b1e2100000015`)
- **Stage C — Filesystem Model & Materialization Engine:** Atomic tree materialization to `.onx/worktrees/`, `MaterializationMode` (readonly vs editable), and live-change import reviews (`server_materializations`, `server_import_reviews`). (Commit `8f10a4d`, migration `b1e2100000016`)
- **Stage D — Runtime Control & Scheduling:** Database-level admission gate (`server_admission_leases`), multi-worker safety, and earmarked capacity accounting. (Commit `e77a82c`, migration `b1e2100000017`)
- **Stage E — Console & Observability:** Demand-driven WebSocket console log streaming follower, interactive bidirectional WS exec/input, and unified multi-core container metrics. (Commits `41da076` / `0b64ef2`)
- **Stage F — Test Platform & Verification:** Reusable `TestDefinition` profiles, 1:1 `Runtime` container attach, automated `PatternCrashAnalyzer` mod blame, and structured `EvidenceBundle` persistence. (Commit `785c7cc`, migration `b1e2100000018`)
- **Stage G — Protected Branches:** Configurable `BranchProtectionPolicy` on `ServerBranch`, direct-commit rejection with emergency bypass permission, and deletion safeguards. (Commit `ba8b539`, migration `b1e2100000019`)
- **Frontend UI Batch:** Complete user interfaces across Stages B, C, F, and G (`BranchProtectionModal`, `TestDefinitionsModal`, `TestEvidenceModal`, `MaterializationBrowserModal`, `ImportReviewModal`, `ManageBranchesModal`, `CreateTagModal`, `CommitDiffModal`, and page wiring). (Commit `8b219ba`)

## Phase 5.5 — Pre-Beta Reliability (Stages A & B implemented & verified)

**Status:** Stages A & B implemented & verified (historical Phase 5.5 milestone metrics: 3,145 backend collected / 3,139 passed / 6 skipped / 0 failed, 752 frontend passed across 89 files, 6/6 CI gates PASS; Alembic head at completion `b1e2100000022`; current repository head is 43 migrations, `b1e2100000023`).
**Design Specs:** [`docs/decisions/PHASE-5.5-STAGE-A-RELIABILITY-FOUNDATION-DESIGN.md`](../decisions/PHASE-5.5-STAGE-A-RELIABILITY-FOUNDATION-DESIGN.md) (Stage A), [`docs/decisions/PHASE-5.5-STAGE-B-TEST-RUN-ENGINE-DESIGN.md`](../decisions/PHASE-5.5-STAGE-B-TEST-RUN-ENGINE-DESIGN.md) (Stage B)
**Governing Decision Records:** [`DECISION-2026-09-27-001`](../decisions/DECISION-2026-09-27-001-stage-b-test-run-engine.md) (Test Run Engine — Accepted by owner 2026-09-27), [`DECISION-2026-09-28-001`](../decisions/DECISION-2026-09-28-001-stage-b-canonical-test-dir-amendment.md) (Canonical Test Directory Grounding Amendment — Accepted by owner 2026-09-28)

Scope ("Stage B" here is Phase 5.5 Test Run Engine, unrelated to the closed Enterprise Stage B above):
- **Stage A — Reliability Foundation (done):** `Operation` aggregate + steps, `operation.*` events, dual-layer idempotency, WS projection, recovery reconciler; exactly one producer wired (`RUN_TEST`).
- **Stage B — Test Run Engine (done):** TestDefinition execution wired directly into run overrides without lossy integer division, supporting exact `duration_seconds` and `assertion_rules`; TestRun lifecycle hardening with standard `ValueError` terminal guards, `operation_id` column and index via migration `b1e2100000022`, and `expires_at` persistence; unified assertion engine behind `BaseVerifier` (`SmokeTestVerifier`, `FakePlayerVerifier`, `MineflayerVerifier`) preserving legacy driver semantics, disconnect ceilings, and zero-target bot handling; canonical `TestCleanupPlan` engine with authoritative deployment-directory grounding (`resolve_test_dir` separator-safe traversal protection, fail-closed `server_dir` validation across discard, promote, reap, and prune); versioned schema v1 evidence bundle with fallback dual keys. Hard boundaries: admission, promotion gates, and `Operation`-as-projection unchanged; Stage C–G untouched.

## Phase 6 — Final Installs / Wrap-up

**Status:** READY (Unblocked by completion of Phase 4, Phase 5, and Enterprise Branch Runtime Stages A–G + Frontend UI Batch; note that Windows environment verification is UNVERIFIED post-2026-10-01 as recorded in `.ai/STATE.json`; CI and Linux remain verified)
**Scope clarified in v1.1:** this is the *final public-facing* documentation and packaging pass — installer polish, first-run experience, distribution packaging, a last README/CONTRIBUTING review. It is **not** where documentation happens for the first time; docs stay synchronized with decisions and state continuously, throughout every phase above.

## Phase 7 — Visual / Brand Polish *(renamed and narrowed in v1.1)*

Deliberately last, and now scoped tightly to what's actually branding: logo, visual identity, shapes, animation, imagery. **Functional UX fixes and core architecture are explicitly excluded from this phase** — functional fixes land in Phase 3 or the relevant domain stage as soon as they're found, not held until here.

---

## Decision Record — Containers moved from old-roadmap Phase 11 to new Phase 5

```
# DECISION-2026-09-01-001 — Move containerization work forward in release order

Status: Accepted
Lane: Release Improvement (enables Phase 4 feature #2) / Engineering
Decision level: D2 (Major — roadmap drift, architectural)
Roadmap drift: Controlled

## Context
The prior roadmap (old ROADMAP.md)
placed Docker containerization as Phase 11, well after launch-adjacent work.
Mohamed's explicit phase order for the real roadmap places a working
containers system at position 5 of 7, ahead of final install/wrap-up and
branding, and it is also a likely prerequisite for Phase 4's "test
environment" community-requested feature.

## Evidence
- Mohamed's explicit dictated phase order (2026-09-01 session).
- r/admincraft feedback: two independent commenters (Mr_Potatoez,
  notyoursocialworker) specifically requested a temporary/isolated test
  environment before touching production — real container isolation is the
  most credible way to deliver that safely.

## Options considered
1. Keep containers at old Phase 11 position (rejected — blocks the
   highest-leverage community-requested feature from being done safely).
2. Move containers to Phase 5, as scoped here (accepted).

## Decision
Containers work moves to Phase 5 of the new roadmap, per Mohamed's
directive and the Phase 4 dependency evidence above.

## Impact
- Product/user: unlocks a safer path to Phase 4's test-environment feature.
- Architecture: introduces Docker as a new runtime provider alongside
  LocalLinuxProvider/LocalWindowsProvider — real, scoped architectural
  change, hence D2 not D1.
- Operations: adds a new deployment dependency (Docker) not previously
  required.

## Effort
Not yet estimated — pending Phase 5's own Design Spec.

## Reversibility
Moderate — the container provider is additive (existing local providers
keep working), but the Phase 4 feature #2 dependency decision (see Phase 4
above) is coupled to this and would need revisiting if this were reversed.

## Roadmap impact
Major — this document (ROADMAP v1.1) reflects the new position directly.

## Verification
Phase 5's Design Spec + its own exit criteria (not yet written).

## Outcome
Accepted and completed 2026-09-11: Phase 5 (Containers System) successfully implemented, verified, and closed across all 6 build batches per PHASE_5_CONTAINERS_SYSTEM_DESIGN_SPEC.md.
```

## Decision Record — Phase 5 built before Phase 4 (execution order)

```
# DECISION-2026-09-10-001 — Build Phase 5 (Containers) before Phase 4 (Community Features)

Status: Accepted
Lane: Release Improvement / Engineering
Decision level: D1 (Standard — execution order change, no phase renumbering, no scope change)
Roadmap drift: Controlled

## Context
ROADMAP_v1.1's Phase 4 section previously resolved (2026-09-01) that the
Phase 4 test-environment feature (#2 of 5) would ship files-based first,
with a container-based mode added as an additional option once Phase 5
landed — explicitly "not a blocking dependency."

Mohamed has now decided to reverse the *build order* (not the phase
numbering): Phase 5 (Containers System) will be executed before Phase 4
starts, to avoid building the test-environment feature files-based and
then having to refactor/rework it once the container runtime exists.

## Evidence
- Mohamed's explicit directive (2026-09-10 session).
- The dual-mode design already acknowledges containers become the
  eventual default backend for the test-environment feature — the
  2026-09-01 decision accepted rework risk in exchange for an earlier
  Phase 4 start; Mohamed has now judged that trade-off not worth it.

## Options considered
1. Keep the 2026-09-01 resolution: Phase 4 starts now, files-based
   test-environment first, container mode added later (rejected).
2. Build Phase 5 first, then start Phase 4 with the container backend
   already available for feature #2 (accepted).

## Decision
Execute Phase 5 (Containers System) design, build, review, and verification
before starting Phase 4 Design Specs. Phase numbering in
ROADMAP_v1.1 is unchanged; only execution order changes.

## Impact
- Product/user: Phase 4 (highest community-priority features) starts
  later than the 2026-09-01 plan intended.
- Architecture: none beyond what Phase 5 already scoped — Docker as a
  new runtime provider alongside LocalLinuxProvider/LocalWindowsProvider.
- Roadmap: the "Dependency on Phase 5 — RESOLVED (2026-09-01)" note in
  Phase 4 of ROADMAP_v1.1 is superseded by this record for *build order*
  purposes only; the dual-mode *product* decision (both modes ship) is
  unchanged.

## Effort
Not yet estimated — pending Phase 5's Design Spec.

## Reversibility
High — this only reorders execution; no code has been written for
either phase yet.

## Roadmap impact
Minor — record only; no change to phase numbering or scope.

## Verification
Phase 5's findings + Design Spec once produced.

## Outcome
Accepted and completed 2026-09-11: Phase 5 (Containers System) built and closed ahead of Phase 4 as planned; Phase 4 now unblocked with container backend available.
```

---

## Open questions carried into v1.1 (need Mohamed's input)

1. ~~What does "extended files not working properly" refer to?~~ — Resolved 2026-09-08: closed as Deferred without a definition (see Phase 1 table); no longer an open question.
2. What does "GPS" refer to in "state-of-the-art validation of GPS/local mode/global mode"? (Phase 5)
3. `preflight.py`'s real current status — this is now Phase 0's job to resolve with evidence, but if Mohamed already knows the answer, it saves an investigation pass.

---

*Like v1.0, this document is the ordering/scoping layer above individual Design Specs, not a replacement for them.*
