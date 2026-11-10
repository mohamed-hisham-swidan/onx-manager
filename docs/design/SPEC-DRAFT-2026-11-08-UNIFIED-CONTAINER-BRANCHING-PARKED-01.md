# SPEC-DRAFT-2026-11-08-UNIFIED-CONTAINER-BRANCHING-PARKED-01

**Status: DRAFT — PARKED. Not authorized. Lane E, Decision level D2 (Major Drift). Blocked until CI is green. Must be re-verified and corrected before any build.**

**Source doc under design:** `docs/design/EXTERNAL-RESEARCH-ARCH-V2-UNIFIED-CONTAINER-BRANCHING.md` — EXTERNAL / UNVERIFIED research; its own header voids the "Status: Canonical" line.

**Inputs:** Two read-only recons against this container-branching objective, all claims re-verified against baseline HEAD.
**Baseline (verified this session):** git HEAD `f27b2027ecdb…` on `master`, working tree clean (`git status -sb`, `git log -1 --oneline`); Alembic head `b1e2100000023` (no child revision references it).
**Verification legend:** every load-bearing statement is tagged FACT (confirmed by command output at the cited file:line), ASSUMPTION (owner-research claim accepted without independent evidence), or UNKNOWN (not determinable from this repo).

---

## Governance

- FACT — This is a proposed architecture change: removal of shipped providers, a new schema field with API surface, a runtime behavior contract (restart sync), an explicit data-engine, and a two-tier backup split. Under `docs/governance/GOVERNANCE.md` (§ Decision hierarchy, § Drift system) this classifies as **D2 — Major Drift** and requires: (1) a DECISION-level record under `docs/decisions/`, (2) roadmap re-baseline with alternatives and rollback paths, (3) explicit drift-budget accounting.
- ASSUMPTION — The whole program is blocked on two prior UNKNOWNS, not engineering: (a) whether the owner actually wants the Simple/Advanced split, (b) whether local providers may be removed at all. Nothing here authorizes Phase 1 implementation.
- FACT — ADR-0015 (`docs/decisions/0015-runtime-entity-and-server-provider-relationship.md:21-22`) states that `Runtime` delegates to `DockerProvider`, `LocalLinuxProvider`, `LocalWindowsProvider` and that "no breaking changes or renaming sweeps are made to `ServerProvider`". Removing local providers directly contradicts an in-force ADR; a superseding ADR is a prerequisite to Phase 6, not a detail.
- FACT — `LocalLinuxProvider` and `LocalWindowsProvider` are live and registered at `backend/app/modules/server/infrastructure/providers/__init__.py:20-22` (`providers/local.py`, `providers/local_windows.py` exist at the cited paths).
- FACT — `docs/current-state.md:13` and `docs/architecture/SPECS.md:287` describe a `RuntimeAdmissionScheduler`; no such identifier exists in `backend/app` (the admission primitive is the function `admit()` at `backend/app/modules/versioning/application/scheduling/admission.py:233`, with the single-row lease table `server_admission_lease` at `backend/app/modules/versioning/infrastructure/models.py:174`; `docs/design/ARCH-2026-11-08-BRANCH-WORKSPACE-OVERVIEW-01.md:58,536` already records this drift). Any new spec must use real names.
- ASSUMPTION — "Blocked until CI is green": the roadmap's standing gate that no structural work starts while quality gates fail.

---

## Goal

Enable a container-first server lifecycle in two modes, without breaking existing data or governance:

- **Simple mode** (ASSUMPTION, owner research): one container, direct file edits, restart applies; versioning hidden.
- **Advanced mode** (ASSUMPTION, owner research): main (immutable code root) / live (production runtime) / work-branches, code-vs-data separation, selective main→live sync on restart, two-tier backups.
- **Single engine cleanup:** remove host-coupled local providers and tmux fallbacks once containers are the only path.

No numeric targets (players, benchmarks) are asserted here; the external research doc's sizing claims were not measured.

---

## Current Behavior

All items below were re-verified at baseline HEAD; file:line evidence is current.

- FACT — Providers: `provider_factory.register(LocalLinuxProvider(fs=local_fs))`, `LocalWindowsProvider()`, `DockerProvider()` at `backend/app/modules/server/infrastructure/providers/__init__.py:20-22`; `SSHProvider`/`CloudProvider` also exist in the same package (`__init__.py:14-18`).
- FACT — DockerProvider already provides the container backbone cited by the research doc: single `/data` mount (`providers/docker.py:472`), Java 8/17/21/25 image resolution (`providers/docker.py:145-186`), PUID/PGID or `--user` mapping (`providers/docker.py:478`).
- FACT — No `ServerMode` identifier exists in `backend/app` or `frontend/src` (`rg '\bServerMode\b'` → no matches).
- FACT — Persistence: `servers.provider` defaults to `""` and `servers.location_type` to `"local"` (`backend/app/modules/server/infrastructure/models.py:49,57`); win32 startup rewrites `provider='local'` → platform default (`backend/app/main.py:105-108` region).
- FACT — Storage COW: capability probe + `StorageCowUnavailableError` live in `backend/app/modules/versioning/infrastructure/storage_probe.py:14,23`; the COW driver is `BtrfsZfsSnapshotDriver` (`btrfs_zfs_driver.py:15`) via `cp --reflink=always` (`:33`), with hardlinking explicitly prohibited (`:20-21`). There is **no** `StorageDriver` ABC, `BtrfsStorageDriver` (subvolume/snapshot), or `PosixAtomicStorageDriver`.
- FACT — Phase-4 spec locks this: Btrfs/ZFS only, HTTP 412 `STORAGE_COW_UNAVAILABLE` otherwise, no ext4/NTFS fallback (`docs/design/PHASE_4_COMMUNITY_FEATURES_DESIGN_SPEC.md:22,83-85`); `docs/decisions/DECISION-2026-09-12-001.md:52` still lists storage-layer COW as an open audit item.
- FACT — Path taxonomy is 5-valued, not 3: `TRACKED/PERSISTENT/GENERATED/IGNORED/EPHEMERAL` (`backend/app/modules/versioning/domain/value_objects.py:61-65`). No `DataCodeClassifier`, no `.onx/state-policy.yml`, no `current-deployment.lock` manifest exist.
- FACT — Versioning is shipped and exposed: `server_commits`/`server_commit_parents` tables exist; ImportReview + AutoCommitLiveChanges are wired at `backend/app/registration.py:191-194,211-212,251-252,424-437`, enforced in `contracts/permissions.yaml:251-255`, and have a frontend modal/pages.
- FACT — Runtime table is test-only: `ServerRuntimeModel` / `server_runtimes` requires a non-null `commit_id` (`backend/app/modules/versioning/infrastructure/models.py:145-152`,FK `server_commits.id`); there is no live-server runtime row today; `node_id` exists only on test runs with default `"local"` (`models.py:96`), not on `servers` (`models.py:20-57`).
- FACT — Branch protection today: enforced at commit time (`create_commit.py:136`, `auto_commit_live_changes.py:85` via `can_commit_directly()`), and merge rejects only archived branches (`merge_commits.py:101`); merge performs **no** protection or test check and requires a caller manifest when parents differ (`merge_commits.py:135-145`).
- FACT — `require_test_pass` and `allow_force_bypass` are stored but enforced nowhere (`versioning/domain/entities.py:57,59` and serialization only). The only test-pass gate is PromoteCommit: a non-`force` promotion requires `TestRunStatus.PASSED` (`promote_commit.py:147-175`, within §"Safety Gating").
- FACT — Files API writes the live root directly with no branch/mode concept: `PUT /content` (`backend/app/api/v1/routers/files.py:191-209`), `DELETE` (`:212`), `POST /upload` (`:236`), `POST /mkdir` (`:323`); no commit calls anywhere in that router.
- FACT — Restart is stop+start on the same mount: waits on/cancels backups, stops (`restart_server.py:139-161`), then `provider.start()` (`:367`) / `RuntimeSupervisor.start_for` (`:485`). It never resolves a commit or reads a "main".
- FACT — Start applies deferred plugin deletions and restore, then `provider.prepare_environment` + `provider.start` (`start_server.py:359-394`). Promotion swaps `mods/` from the test directory (`promote_commit.py:301-309`) but never swaps `plugins/`.
- FACT — Backups today: `BackupSaga` (`backend/app/services/backup_orchestrator.py:93`) issues a single `save-all` (`:194`; regex confirmation around `:67`), no save-off/save-on, no `write_exec_input`; AES-256-GCM (`backend/app/modules/storage/encryption.py:9,75,98`) with local + S3 storage. No internal/external tier split, no `/backups/external` route.

---

## Proposed Change

Each phase is independently shippable, reversible (single migration or feature-flag reversal), and stops short of the next phase if rejected.

**Phase 1 — ServerMode persistence only (no behavior change).**
- Add nullable/additive `mode` column to `servers` via a new Alembic revision following head `b1e2100000023` (FACT: `b1e2100000023_add_server_lifecycle_leases.py` has `down_revision = b1e2100000022` at its `:16`, and no later revision references it — it is head).
- Add `ServerMode` value object. Per ADR-0009 (`docs/decisions/0009-…pydantic-field-validator-for-domain-values.md`), any request schema carrying `mode` needs a matching `@field_validator` plus a handler `ValueError → InvalidValueError` safety net.
- Default for pre-existing rows: **UNKNOWN (owner)**. Rollback: drop column; code reads default.

**Phase 2 — Make branch protection bite on merge.**
- In `merge_commits.py`, where only the archived check exists (`:101`), add protection checks consistent with `create_commit.py:136` (reject unless `can_commit_directly()/bypass+audit`), and honor `require_test_pass`/`allow_force_bypass` if the owner decides they are in force. Rollback: revert handler; no data migration.

**Phase 3 — Selective main→live sync on restart (Advanced only).**
- On restart, after stop and before `provider.start()` (`restart_server.py:139→367` gap), resolve the server's target commit and apply only code/config paths into the live deployment directory, preserving world/plugin-DB paths; record the booted commit. Implementation reuses `fs_atomic.py`/`tree_writer.py` (they exist: `versioning/infrastructure/fs_atomic.py`, `tree_writer.py`) plus a new deployment manifest that records previously deployed jars/static configs so removals can be applied without `rsync --delete` semantics. Rollback: flag off → restart returns to current stop+start behavior.

**Phase 4 — Code/data classifier honoring the existing taxonomy.**
- Keep the 5-value `PathClassification` (`value_objects.py:61-65`); map the research doc's three categories onto it (code ≈ TRACKED; live state ≈ PERSISTENT; logs/cache ≈ GENERATED), never collapsing to 3 values. Extend `manifest_builder.py` capture rules (currently configs by root/extension and `mods/`+`plugins/` jars only — no `*.db`, no `config/*.db` per `manifest_builder.py:29-31` region), keep `write_materialized_file.py` TRACKED-only enforcement, and treat plugin-state shields as PERSISTENT classification, not new categories. User overrides (e.g. the doc's `.onx/state-policy.yml`) are owner-decided, not assumed.

**Phase 5 — Two-tier backups.**
- Wrap or extend `BackupSaga` with Mode-internal (data-only / branch-code) and external-vault (code-only / full) commands; add save-off → save-all → save-on orchestration around the existing single `save-all` (`backup_orchestrator.py:194`). Storage reuses AES-256-GCM + local/S3 (`storage/encryption.py`, backup storage backends). Rollback: keep the one-tier public routes; new routes are additive.

**Phase 6 — Provider removal (LAST, optional, conditional).**
- Prerequisite per Governance: superseding ADR for ADR-0015 (`0015-runtime-entity-and-server-provider-relationship.md:21-22`), plus a DECISION record; deletion is breaking for Windows hosts and any currently-local server.
- Order: stop new local creation (`default_provider_for_platform`, `main.py` win32 migration, `import_server` path) → migrate existing local rows (`servers.provider` default `""` today, `models.py:49`) → move console behavior to Docker-only (`console_stream.py` tmux fallback currently live) → delete `providers/local.py`, `providers/local_windows.py`, prune `providers/__init__.py:20-21`, and `core/process_utils.py` taskkill/PID paths.
- Reversible check: the deletion commit is revertible; the DB backfill keeps a `provider` history.

**Container topology (main/live/branch mounts, `/var/lib/onx/...`):** UNKNOWN — current deployment root is a single `server.deployment.server_directory()` per server and `DockerProvider` mounts that one directory (`docker.py:472`); any main/live directory split is a storage-layout migration the owner must adopt before Phase 3 is built against it. This spec does **not** specify the external doc's hardcoded paths.

**Multi-node node_id:** UNKNOWN — `node_id` exists only on test runs (`models.py:96`); adding it to `servers`/`server_runtimes` is optional Phase 1 rider, owner-decided; `server_runtimes` cannot today host a live runtime row because it demands a `commit_id` FK (`models.py:145-152`).

---

## Affected Components

- **`backend/app/modules/server/`** — domain value objects (`ServerMode`), `infrastructure/models.py` (mode column; optional node_id), `repository.py` (serialize mode), commands `start_server.py`, `restart_server.py` (sync hook, Phase 3), `stop_server.py`, `import_server.py`, `create_server.py` (mode default + validation), `console_stream.py` (tmux fallback removal in Phase 6), `supervisor.py`, `runtime_ownership.py`, `runtime_reconciliation.py`, `filesystem_reconciliation.py`,
- **`backend/app/modules/versioning/`** — `merge_commits.py` (Phase 2 protection), `manifest_builder.py` + potential classifier (Phase 4), `promote_commit.py` (Phase 3 reuses its manifest swap patterns), `scheduling/admission.py` (only if mode gating needs admission changes). FACT — the class `RuntimeAdmissionScheduler` does not exist (`admission.py:233` is the real primitive).
- **`backend/app/services/backup_orchestrator.py` + `modules/backup/`** — Phase 5 command set; `save-all` sequence (`:194`).
- **`backend/app/api/v1/routers/`** — `files.py` (Phase 5/3 optional "locked-while-advanced" policy — currently writes live root directly, `files.py:191-209`), `backups.py`, `versioning.py` (only if ImportReview retirement occurs — NOT assumed here; owner-decided).
- **`backend/app/alembic/versions/`** — one additive revision per phase that touches schema.
- **`contracts/permissions.yaml` + `config.schema.json`** — new/changed rows if routes or the provider enum change.
- **`frontend/src/server_manager/`** — `ConfigStep.tsx` (mode chooser — the picker today is provider-local-vs-docker at `ConfigStep.tsx:113-141`), `ServerShell.tsx` nav (currently always shows Versions, `ServerShell.tsx:156`), `types.ts`, `ServerVersioningPage.tsx`.
- **Tests in `backend/tests/`** — provider suites that cover local providers (`test_local_windows_provider.py`, `test_local_windows_and_process_identity.py`, `test_local_provider_cpu_enforcement.py`, `test_providers.py` mixed cases, `test_windows_lifecycle_w01.py`) are candidates for removal **only in Phase 6**, contingent on the Phase 6 decision.

---

## Interfaces & Contracts

- **DB:** `servers.mode` (new, nullable→backfilled or defaulted by owner decision; Alembic rev following `b1e2100000023`). No rewriting of existing tables; additive only across phases 1–5. Phase 6 backfills/migrates `servers.provider` from local → docker (value decided at Phase 6 time).
- **HTTP:** no existing route removed in Phases 1–5. Phase 5 adds routes only (additive, registered in `contracts/permissions.yaml`). Phase 6 removes local-provider behavior paths; route contract gate (`check-route-contract`) must be re-run — per Phase-0 audit `2,829+` backend tests / 6 CI quality gates currently green.
- **Events/logging:** restart-sync emits structured timeline milestones (mirroring `restart_server.py` existing `add_timeline_milestone` usage); no new event bus channels assumed by this draft.
- **Frontend:** `types.ts` + wizard step + nav conditional on `server.mode` (Phase 1 ships column + type only; Phase 2/3 gate UI hides once real behavior is guaranteed, never before — hiding the Versions nav today would advertise an isolation that does not yet exist in the backend, FACT).

---

## Failure & Edge Cases

- **Restart sync with no commit:** if no target commit exists for a server (a legacy/imported server has never committed — ImportReview/AutoCommit flows are how commits appear today, FACT), Phase 3 must no-op with a clear timeline milestone rather than booting with mixed state.
- **Live data protection:** world/, plugin DBs, `*.db`, `*-wal`, `*-shm` paths must never be touched by the Phase 3 sync; the manifest of previously-deployed jars/static configs limits deletions to files the engine itself deployed (the external doc's "no rsync --delete" rule, adopted as design intent — its benchmarks were not re-verified here, ASSUMPTION).
- **Promote vs. restart duplication:** promote already swaps configs/mods with a rollback journal (`promote_commit.py:239-409`); Phase 3 must not re-implement a divergent mechanism — share the staging/swap helpers, extend to `plugins/` (currently never swapped, FACT) only if owner decides plugin jars are code.
- **Windows hosts:** until Phase 6 lands, the win32 local provider keeps being default-selected (`main.py` startup migration); Phases 1–5 must remain provider-agnostic so nothing breaks on a local server.
- **COW hosts:** phases rely on the existing 412 disable behavior (`storage_probe.py`, locked by `PHASE_4_COMMUNITY_FEATURES_DESIGN_SPEC.md:22,83-85`); no ext4 fallback is proposed regardless of what the external doc says, unless the owner overturns Phase-4 spec (OPEN DECISION).
- **Degragded/Unknown status of CI:** this spec stays parked until CI is green (Status header); if the 6 quality gates re-run with failures (e.g. `check-db-revision` after any new revision), the phase halts before merge.
- **Crash during Phase 3 sync:** use the promote_commit journal pattern (backup dir + rollback), FACT that this pattern exists at `promote_commit.py:372-409`; do not invent a second journal format.

---

## Tests & Verification

- **Phase 1:** new revision passes `alembic upgrade/downgrade` round-trip test; `check-db-revision` gate stays green; API create/update returns `mode` with a validator unit test (schema `ServerCreateRequest` per ADR-0009 pattern); existing server list responses unchanged on `mode=None→Simple default` per owner decision.
- **Phase 2:** unit tests on `merge_commits.py`: protected branch + no bypass → reject; bypass + audit log row present; archived unchanged. Regressions: features flagged in `KNOWN GAPS` below get closed here (see `KNOWN GAPS`).
- **Phase 3:** integration tests with Docker testcontainers mirroring existing stage tests — sync applies jar/property changes; untouched `world/`/`*.db`; deletion of a previously-deployed jar works; no manifest → no-op. Existing `test_iss011_shutdown_grace.py`, `test_supervisor.py`, `test_stale_startup_deadline.py` suites must stay green (they cover stop/restart paths this phase modifies).
- **Phase 4:** unit tests on manifest/classification invariants: world paths always PERSISTENT, `config/**.db` flagged (currently missed), plugin state shields; adversarial fuzzer on path classification.
- **Phase 5:** backup/restore round-trip tests (existing suites around `test_backup_saga.py` extended); save-off/save-all/save-on mocked at provider (`execute_command` fake), mirroring existing provider tests.
- **Phase 6:** every deleted local test converted to its Docker equivalent or dropped with justification; `test_provider_conformance.py` parameter list pruned to remaining providers; Windows CI green without local provider; route-contract/permissions gates updated.
- **Overarching:** per-phase CI must stay green; `docs/current-state.md` + `.ai/STATE.json` updated in the same commit as each phase (documentation gate).

---

## Out of Scope

- Superseding ADR-0015 or writing the DECISION record (this spec is Parked, and it relationships to ADRs are documented under Governance, then handed to governance when unparked).
- Deciding ImportReview/AutoCommit retirement (shipped and enforced today; removal is a breaking change and an OPEN OWNER DECISION below).
- Inventing the external doc's `/var/lib/onx/...` paths, benchmarks, or numeric player targets (none measured here; topology is owner-decided).
- The research doc's `RuntimeAdmissionScheduler` name — the real primitive `admit()` (`admission.py:233`) is what exists; renaming is not in scope.
- Multi-node scheduling, remote-Artifact Sync, gRPC transport — all UNKNOWNS about future requirements; not designed here.
- Any code change, migration, or contract edit under "PARKED" status — none of this draft's "Proposed Change" phases are executable as written.

---

## OPEN OWNER DECISIONS

1. Is the Simple/Advanced split authorized at all? (Unverified owner intent, research doc only.)
2. Where does `mode` persist — `servers.mode` column assumed in Phase 1 — and what is the default for existing rows? (Value of "Simple by default" not decided anywhere.)
3. Are local providers removed at all, kept for Windows, or kept as a bridge? (ADR-0015 currently forbids the removal.)
4. Is the filesystem topology (main/live/branch directory layout) adopted, or does live remain the existing single `server_directory()` mount?
5. Do Non-COW hosts get the Phase-4 hard 412 disable (current spec/behavior) or the external doc's ext4 fallback (contradicts `PHASE_4…:22,83-85`)?
6. Should `merge_commits.py` enforce the stored-but-unenforced `require_test_pass` / `allow_force_bypass`, or does enforcement stay at promote-time only?
7. Is a `node_id` column needed on `servers`/`server_runtimes` now, or deferred with multi-node work (currently `node_id` exists only on test runs, `models.py:96`)?
8. If the backup tier split happens: where does the external vault live (host path vs S3 — both supported by storage backends today)?
9. Is ImportReview / AutoCommitLiveChanges retired, kept, or hidden behind mode? (Breaking API + contract + frontend change.)

---

## KNOWN GAPS FOUND (independent of this design)

- **Merge bypasses branch protection:** `merge_commits.py:101` checks only "not archived"; protection/test policies aren't enforced there (enforcement exists only on direct commit paths: `create_commit.py:136`, `auto_commit_live_changes.py:85`).
- **`require_test_pass` / `allow_force_bypass` stored but never enforced:** only serialized (`versioning/domain/entities.py:57,59` and helpers); a "Save/Merge" through `/commits/merge` skips them even though PromoteCommit does honor PASSED gating (`promote_commit.py:147-175`).
- **`RuntimeAdmissionScheduler` doc drift:** `docs/current-state.md:13` and `docs/architecture/SPECS.md:287` name a class that does not exist; real primitive is `admit()` (`admission.py:233`) and lease table `server_admission_lease` (`models.py:174`). Already recorded in `docs/design/ARCH-2026-11-08-BRANCH-WORKSPACE-OVERVIEW-01.md:58,536` and needs its own doc-correction pass, separate from this design.
