# Design Spec — Stage C: Filesystem Model & Materialization Engine

**Status:** Draft — NOT yet Design-Reviewed. Do not build from this directly.
**Prerequisite verified (carried, not re-run):** Stage B CLOSED 2026-09-17 — 2793 passed / 6 skipped / 0 failed backend, 6/6 CI gates, head `b1e2100000015`. Build MUST re-run these baselines fresh at close.
**Source:** Stage C RECON (complete). Prior art is only the 5-line outline at `02-stages-b-through-g-outline.md:15-19`; there is no prior spec and no "runtime-change import review" definition anywhere in the repo — the semantics below are defined here for the first time, constrained by the binding decisions listed under Governance Gate Check.

## Goal

Turn `Materialization` from a domain-only entity (today: constructed only in tests, no persistence, no API, no writer) into a real, persisted filesystem working tree derived from a Stage B `Revision` — with a read-only-by-default branch/revision file browser, an opt-in advanced edit mode, enforced path classification, and an auto-commit-by-default live-change import flow — without touching the test runner's shipped pipeline, the live-dir commit path, or the files router's behavior.

## Current Behavior

- **Materialization** (`backend/app/modules/versioning/domain/entities.py:199-249`) — dataclass with `id`, `commit_id`, `root_path`, `status` (`pending→ready→stale→removed`), `path_classification` map, `stage_path()` traversal containment. **Constructor hard-requires the root to contain `.onx` and `tests`** (`:219-224`). FACT: nothing outside `backend/tests/` ever constructs it (grep-verified); no command, query, route, or table references it.
- **PathClassification** (`domain/value_objects.py:24-36`) — all five values (`TRACKED/PERSISTENT/GENERATED/IGNORED/EPHEMERAL`) exist; only `stage_path()` labeling and `PersistentDataset.validate_write_path()` (`entities.py:328-348`, rejects writes overlapping `Tree.configs`/`Tree.mods`) exercise them.
- **Revision** (Stage B) — pure value object (`from_commit` / `from_branch` / `from_tag`); there is NO resolve service and NO resolve endpoint. Stage C composes existing queries (`get_branch_by_name`, `get_tag`) + `Revision.from_*` + a new materialize step.
- **Only Tree→disk writer in the repo** — inline steps in `DockerTestExecutionRunner.run_test` (`infrastructure/test_runner.py:154-230`): mkdir `.onx/tests/<test_id>`, COW world clone, manifest configs (minus `server.properties`), reflink-or-copy mod jars + executable via module-level `stage_file_reflink_or_copy()` (`:50`), `server.properties` via `write_test_server_properties()` (`config_writer.py:10`, `TestServerDeployment`-only). Mod binaries resolve against the LIVE server dir, not content-addressed storage.
- **Commit path** (`application/commands/create_commit.py`) builds its manifest from the LIVE server dir — disk→manifest, no Materialization intermediary. **Files router** (`backend/app/api/v1/routers/files.py`) serves the live dir directly, bypassing versioning entirely.
- **Atomic-write precedent** — `backend/app/modules/backup/application/restore_service.py:149-197` (`_atomic_replace_file`, `_atomic_replace_dir`: same-dir/parent staging + `os.replace` + rollback, per ADR-0012). Backup-shaped orchestration around them (`perform_safe_restore`) is NOT reusable; the two private functions are the pattern reference but live in the wrong module to import (see Proposed Change (e)).
- **Zero Stage C surface** in `contracts/permissions.yaml`, `routers/versioning.py`, `infrastructure/models.py` (tables: branches, tags, commit_parents, snapshots, commits, test_runs — no materializations), confirmed fresh this session.

## Proposed Change

### (a) Separate root + constructor generalization

- New root: `<server_dir>/.onx/worktrees/<materialization_id>`. `.onx/tests` stays EXCLUSIVELY for the test runner (untouched; RECON decision 2).
- Generalize `Materialization.__post_init__` root rule from "must contain `.onx` AND `tests`" to an **allowlist of managed roots**: path must resolve under `<server_dir>/.onx/tests/` (legacy/test-runner context) OR `<server_dir>/.onx/worktrees/` (Stage C). Keep the `..` rejection and the `stage_path()` absolute/containment checks byte-for-byte. Rationale: minimal relaxation of the isolation invariant — arbitrary roots (e.g. `/tmp`, live dir itself) stay rejected, so every existing root-rejection test keeps passing; only `.onx/worktrees` is newly accepted.
- New domain field `mode: MaterializationMode = MaterializationMode.READONLY` (`READONLY | EDITABLE`, new enum in `value_objects.py`), defaulting to read-only (decision 3). `EDITABLE` is entered only via explicit `SetMaterializationEditMode` on a non-`REMOVED` materialization; entering edit mode never changes `status`. Appending a defaulted field preserves all existing constructor call sites.

### (b) Browser API surface — read-only default, advanced edit opt-in

- **Create:** `CreateMaterialization` command takes `{server_id, revision_type: commit|branch|tag, ref: <id|name>, mode}` → resolves head via existing repo reads → `Revision.from_*` → allocates `.onx/worktrees/<uuid>` → writes Tree files (per (e)) → classifies every path (per (c)) → persists row with `status=READY` only after verify pass (every TRACKED path present; else stays `PENDING` and staging dir is removed — never expose half-written roots).
- **Browse (read-only, `mode` irrelevant):** `GetMaterializations` (list), `GetMaterializationTree` (`tree?path=` → entries `{path, classification, size_bytes, origin: materialized|live-ref}`), `GetMaterializationFile` (`files?path=` → content **only for TRACKED/materialized files**; any other classification returns an explicit `410`-style domain error "not materialized", never live content).
- **Edit (advanced, `EDITABLE` only):** `WriteMaterializedFile {path, content}` — rejected unless `mode==EDITABLE` AND classification is TRACKED AND `PersistentDataset.validate_write_path(path, source_tree)` passes (defense in depth on top of (c)). Writes go ONLY to the worktree root; **no edit operation touches the live dir**. Dirtiness is COMPUTED (diff worktree files vs source Tree at scan time), never stored.
- **Remove:** `RemoveMaterialization` → `mark_removed()` + `rmtree(root, ignore_errors=True)`; row retained for audit. `REMOVED` stays terminal (existing invariant; `Runtime`-binds-removed stays illegal per ADR-0015 — no Runtime wiring in this stage).
- **Staleness is lazy, not event-driven** (no new event wiring, no background jobs): read queries compare `materialization.commit_id` against the source branch's current head; on mismatch they persist `mark_stale()` and report `stale: true`. Deterministic, zero new infrastructure.

### (c) Path classification enforcement (read + edit-mode write)

At materialize time every known path gets exactly one label: `Tree.configs` + `Tree.mods` entries → **TRACKED** (written to worktree); world/save dirs, `server.properties` live overrides, playerdata → **PERSISTENT** (metadata-only entries, `origin: live-ref`, content never served/copied); logs, cache, crash-reports → **GENERATED** (metadata-only); `.onx/**`, lock files → **IGNORED**; tmp/staging → **EPHEMERAL**. Unknown live files are NOT enumerated (browser shows the revision's namespace, not a live-dir listing — this is the §3.3 branch-vs-filesystem distinction made concrete). On edit-mode write: non-TRACKED → explicit rejection naming the classification and ADR-0016; TRACKED → allowed through `validate_write_path`. World data is NEVER in a worktree (it lives in snapshots/PersistentDataset domain) — import review likewise covers Tree-tracked files only.

### (d) Import-review flow — auto-commit by default, approval opt-in after the fact

- **Scan (preview, no side effects):** `ScanLiveChanges {server_id, source: commit_id|branch}` builds a live manifest via the existing `ManifestBuilder.build_manifest` and diffs it against the source commit's Tree with Stage B's deterministic diff. Returns classified per-file changes. Dirty-worktree computation reuses the same comparison (worktree files vs source Tree).
- **Auto-commit (DEFAULT ON per server):** when a scan with changes is triggered (explicit route call in Stage C; automatic triggers are Out of Scope), the handler commits via the EXISTING `CreateCommitCommand` (live-dir manifest — `create_commit.py` unchanged) with `author_id="onx-auto-import"`, message prefix `[auto-import]`, parent = current branch head (plain linear child even if the head moved since the source — wholesale live snapshot, so no 3-way merge and no conflict-resolution algorithm). Each auto-commit inserts a `server_import_reviews` row (`PENDING`).
- **User closes/rejects, or commits manually instead:**
  - `ConfirmImportReview` → `CONFIRMED` (record only; DAG untouched).
  - `DismissImportReview` → `DISMISSED` (record only; live changes stay live, no DAG change).
  - `RevertImportReview` → rewrites the live dir's TRACKED files back to the auto-commit's parent Tree (per-file `_atomic_replace_file`-pattern writes, ADR-0012) + creates a revert commit via `CreateCommitCommand` + marks `REVERTED`. This is the only Stage C path (besides the user's own files-router use) that writes tracked files into the live dir, and it is explicit and audited.
  - **Manual instead:** user runs `ScanLiveChanges` (preview) → then plain `CreateCommitCommand` under their own identity. No review row is created; nothing auto-fires from a preview.
- No mandatory approval gate exists anywhere in this flow: commits land first, review happens after, exactly per decision 1.

### (e) Tree→disk writer — EXPLICIT CHOICE: new Stage C writer; test runner untouched

**Stage C implements its own writer** in a new `infrastructure/tree_writer.py` (`write_tree_to_dir(tree, target_root, *, verify=True)`): plain-file writes (NO reflink assumption — worktrees are portable view copies, not COW clones; NO chmod/exec handling — worktrees contain no executables), staging to a same-parent sibling dir + atomic swap per ADR-0012, post-write verify (presence + `ManifestBuilder.calculate_file_hash` match) before the caller may mark `READY`. It reuses the already module-level `stage_file_reflink_or_copy()` for mod-jar copies where available (import, not copy-paste).

**NOT extracted into a shared primitive, and `test_runner.py:154-230` is NOT migrated to it in this stage.** Justification against the alternative: the runner's inline path is shipped, tested behavior (boot-contract suites) with COW-clone + executable-staging + `TestServerDeployment` semantics a browser writer must NOT inherit (world clone and jar staging in a worktree would drag world data and live-disk dependence into revision views — the exact conflation (c) forbids). Extracting now risks regressing the 2793-suite for zero user-visible gain. Bounded duplication (~60 lines) is the cheaper, reversible option; migration/merge of the two writers is assigned to **Stage F** (which owns the test-platform rework and is the natural owner of runner decomposition). Cross-module reuse of backup's `_atomic_replace_*` is likewise pattern-reference, not import: re-implement the ~30-line pattern in a new versioning-local `infrastructure/fs_atomic.py` (backup↔versioning imports would violate module boundaries — a Design Review §6 fail). **Build-time check (mandatory):** spot-check `app/modules/shared/` and `app/core/` for an existing atomic-write helper; if one exists, use it instead of creating `fs_atomic.py`.

### (f) Coexistence with live-dir paths — no conflict, disjoint roots, explicit bridges

| Path | Root it touches | Change in Stage C |
|---|---|---|
| Files router (direct management) | live `server_dir` | NONE — behavior unchanged |
| `CreateCommitCommand` (manifest build) | reads live `server_dir` | NONE — still the sole commit path (manual + auto-import + revert commits all flow through it) |
| Test runner materialization | `<server_dir>/.onx/tests/<test_id>` | NONE — not decomposed, not reused |
| Browser/edit worktrees | `<server_dir>/.onx/worktrees/<mat_id>` | NEW — reads serve worktree files only; PERSISTENT entries are metadata-only live-refs |
| Import review | live TRACKED files ↔ commit Tree | NEW — `ScanLiveChanges` (read-only compare) + auto/revert commits (via existing command) |

The only bridges between roots are explicit, audited operations (`CreateMaterialization`, auto-commit, `RevertImportReview`). There is no background sync, no live-dir watching, no write-through. The three-way relationship (branch namespace vs live filesystem vs isolated views) is therefore modeled, not conflated.

## Affected Components

- `backend/app/modules/versioning/domain/value_objects.py` — new `MaterializationMode` (`READONLY|EDITABLE`); root-allowlist constants (`.onx/tests`, `.onx/worktrees`).
- `backend/app/modules/versioning/domain/entities.py` — `Materialization`: generalized root rule, new `mode` field (default `READONLY`); new `ImportReview` entity (`PENDING→CONFIRMED|REVERTED|DISMISSED`, terminal).
- `backend/app/modules/versioning/application/commands/` — new `create_materialization.py`, `remove_materialization.py`, `set_materialization_edit_mode.py`, `write_materialized_file.py`, `auto_commit_live_changes.py`, `confirm_import_review.py`, `dismiss_import_review.py`, `revert_import_review.py`.
- `backend/app/modules/versioning/application/queries/` — new `get_materializations.py`, `get_materialization_tree.py`, `get_materialization_file.py`, `scan_live_changes.py`.
- `backend/app/modules/versioning/infrastructure/` — new `tree_writer.py`, `fs_atomic.py` (or shared-helper reuse per Build-time check); `models.py` + `repository.py`: new `ServerMaterializationModel` (`server_materializations`) and `ServerImportReviewModel` (`server_import_reviews`) with mappings; NO changes to existing six models.
- `backend/app/modules/versioning/domain/repository.py` — `VersioningRepository` interface gains materialization/review methods.
- `backend/app/api/v1/routers/versioning.py` + `backend/app/api/v1/schemas/versioning.py` — 11 new endpoints (exact routes in Interfaces & Contracts).
- `contracts/permissions.yaml` — 11 new entries (exact mapping below; required for `check-route-contract`).
- Alembic: new revision `b1e2100000016` (head is `b1e2100000015`), creating both tables; downgrade drops both.
- `backend/app/modules/server/...DeleteServerHandler` — 5-line best-effort hook calling `RemoveMaterialization` for the server's worktrees (only cross-module touch; prevents orphaned worktree dirs on server delete).

## Interfaces & Contracts

Router prefix follows convention: `/api/v1/servers/{server_id}/versioning`. Payloads are JSON; file content up to a 1 MiB cap (larger → `413` with path + size; binary/non-UTF8 → base64 envelope `{encoding:"base64"}` — exact schema at Build, behavior fixed here).

| Route | Permission | Payload / response |
|---|---|---|
| `POST .../materializations` `{revision_type: commit\|branch\|tag, ref: string, mode?: readonly\|editable = readonly}` | `server:version:commit` | `201 {materialization_id, revision: "branch:main@<sha>", mode, status: ready, root}` |
| `GET .../materializations` | `server:version:read` | `[{id, revision, mode, status, stale, created_at}]` |
| `GET .../materializations/{mat_id}/tree?path=` | `server:version:read` | `{entries: [{path, classification, size_bytes, origin}]}` deterministic path-sorted |
| `GET .../materializations/{mat_id}/files?path=` | `server:version:read` | TRACKED content; else explicit not-materialized error |
| `POST .../materializations/{mat_id}/edit-mode` `{enabled: bool}` | `server:version:commit` | `{mode}`; rejected on `REMOVED` |
| `PUT .../materializations/{mat_id}/files` `{path, content}` | `server:version:commit` | EDITABLE+TRACKED only; `{path, bytes_written}` |
| `DELETE .../materializations/{mat_id}` | `server:version:commit` | `{removed: true}` |
| `POST .../import-review/scan` `{source: commit_id\|branch}` | `server:version:read` | `{changes: [{path, change: added\|removed\|modified, classification}], auto_commit: null}` (preview; commits nothing) |
| `POST .../import-review/auto-commit` `{branch}` | `server:version:commit` | scan+commit now; `201 {commit_id, review_id, changes}`; no changes → `{commit_id: null, review_id: null}` |
| `POST .../import-review/{review_id}/confirm` | `server:version:commit` | `{status: confirmed}` |
| `POST .../import-review/{review_id}/dismiss` | `server:version:commit` | `{status: dismissed}` |
| `POST .../import-review/{review_id}/revert` | `server:version:commit` | live TRACKED restore + revert commit; `{status: reverted, revert_commit_id}` |

(Twelve rows: 11 new endpoints + the scan/auto-commit pair counted separately; every row gets a `permissions.yaml` entry before Build or `check-route-contract` fails. No `ServerProvider`/`Runtime`/`DockerProvider` changes.)

## Failure Cases & Edge Cases

- **Concurrent edit + test run:** roots are disjoint (`.onx/worktrees` vs `.onx/tests` vs live) so no filesystem collision is possible by construction. ADR-0016 still applies at the semantic level: an edit-mode write overlapping the source Tree's tracked set is the NORMAL case (that is what editing means) — the boundary it must not cross is writing into PERSISTENT/world paths, enforced by (c) + `validate_write_path`. Test-runner behavior is unchanged including its per-server lock (Stage D/F territory; not re-litigated here).
- **Auto-commit racing branch advance:** parent is always resolved fresh (= current head at commit time); two racing auto-commits serialize on the existing commit path (second becomes a child of the first — both are wholesale live snapshots, so ordering is benign and no merge logic is needed).
- **Revert racing new live changes:** revert captures the pre-restore live manifest into the revert commit's details; if the live dir changed between scan and restore, the handler re-scans and aborts with explicit conflict (never blind-overwrites) — operator retries.
- **Partial writes:** worktree creation and revert-restores stage to a same-parent sibling and atomic-swap (ADR-0012); any failure removes staging and the materialization stays `PENDING` (never listed as `READY`); revert failure leaves live dir untouched (restore-then-commit ordering: live restore first, commit only on restore success).
- **Traversal / escapes:** `stage_path` containment + constructor allowlist + no-symlink output (writer emits regular files only; symlinks in source Trees are rejected entries, not followed); `..`/absolute/`~` rejected with explicit errors; classification keys normalized `os.path.normpath + replace("\\","/")` matching `validate_write_path`.
- **Windows/POSIX:** no reflink/`os.killpg`/`tmux`/`/tmp` assumptions; no chmod in the Stage C writer; temp/staging always sibling-of-target (EXDEV-safe on both); case-sensitivity collisions (e.g. `Mods/` vs `mods/` on Windows) surface as explicit determinism errors at verify time, not silent overwrites.
- **Degenerate inputs:** empty Tree (no tracked files → READY with zero entries, not an error); missing mod binary at materialize (mods resolve against the commit's stored manifest, and any referenced-but-unresolvable artifact is a metadata-only entry with `origin: unavailable`, never a hard fail — the runner's live-disk dependence is exactly what worktrees must not inherit); unknown `mat_id`/review id → `NotFoundError`; cross-server revision refs → rejected at `Revision.from_*` construction (existing behavior).
- **Orphaned worktrees on crash:** `PENDING` rows older than the Build-fixed threshold with no on-disk staging are removed by the delete-server hook path and lazily on list (no scheduler, no background jobs in this stage).

## Tests & Verification

- **New unit tests:** root allowlist (worktrees accepted; `/tmp`, live dir, `..` rejected — existing `.onx/tests` acceptances untouched); `mode` default + edit-mode transitions incl. `REMOVED` rejection; classification labeling incl. unknown-file exclusion; `validate_write_path` on edit writes (TRACKED pass, PERSISTENT/GENERATED reject); lazy staleness (head advance → `STALE` on next read); `fs_atomic`/`tree_writer` round-trips incl. failure-leaves-no-partial-write; review state machine terminality.
- **New integration tests:** materialize from each `Revision` form (commit/branch/tag — composing existing queries, no new resolve service); browse list/tree/file incl. determinism ordering and non-TRACKED content refusal; edit-mode write round-trip + computed-dirty scan; `ScanLiveChanges` preview determinism (same live state → byte-identical output, twice); auto-commit → confirm/dismiss/revert full cycles incl. live-restore content equality with parent Tree and cross-server/dangling-ref rejections.
- **Regression (blocking):** full backend suite against the 2793/6/0 baseline, the versioning suite, the Stage A invariant suite (`test_stage_a_domain_invariants.py`, esp. lifecycle/isolation blocks), and the isolated-test-runner suites (untouched code path must stay green — proves (e)'s non-migration choice held); `check-route-contract` with the 12 new entries; all 6/6 CI gates. Any regression blocks close.
- **Migration check:** upgrade to head + downgrade −1 reversibility for `b1e2100000016` (both tables).

## Out of Scope

- World/save-data materialization, restore-to-live of world data, executable staging in worktrees.
- Test-runner refactor or adoption of `tree_writer.py` (deferred to Stage F, its natural owner).
- Automatic/periodic scan triggers, schedulers, background jobs (Stage D/F territory); filesystem watching / write-through / live-edit sync.
- Frontend UI (API + contracts + persistence only, matching Stage B's boundary).
- 3-way merge or conflict-resolution algorithms (auto-commits are linear wholesale snapshots by design).
- RBAC beyond the permission entries above (Stage G); `ServerProvider`/`Runtime`/`DockerProvider` changes; retained-row pruning policy beyond the delete hook (deferred with note, not silently dropped).

## Governance Gate Check

**This design is D2 per GOVERNANCE.md §4** — it adds persistence strategy (two new tables + `b1e2100000016` migration convention) and new API/permission contract surface (12 `permissions.yaml` entries). **No separate governance escalation is required before Build:** the D2-level choices that would otherwise need it — (1) auto-commit-by-default import review with after-the-fact close/reject/manual-commit, (2) the separate `.onx/worktrees` root, (3) read-only-default with opt-in advanced edit mode — are **already authorized by Mohamed's binding decisions** stated in the task brief. Design Review (§6) is still required (this spec is NOT build authorization), and must verify: root-allowlist minimality, the no-migration-of-test_runner choice in (e), the 12-entry contract table, and that no changeset leaks beyond the listed Affected Components. After Design Review approval, Build may proceed directly.
