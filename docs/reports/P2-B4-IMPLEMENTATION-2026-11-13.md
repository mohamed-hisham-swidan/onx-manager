# P2 B4 Core Substrate Implementation Report — 2026-11-13

**Slice:** P2-1 Core Substrate — batches B4a–B4h.
**Worktree:** `/mnt/D/workspace/onx-manager-wt/p2-b4-core-substrate`
**Branch:** `slice/p2-b4-core-substrate`
**Base:** `47580e40fc28966ac0ca2083ae11fb2acb7203a6` (committed P2 B2+B3 slice).
**Tip after B4g:** `8c9cb73`; this report is the B4h docs commit.
**Status:** IMPLEMENTED_PENDING_FIRST_CI_RUN (local verification complete; no CI run).

> **Boundary statement:** B4 is a slice of P2-1. P2 is not complete. Advanced mode remains
> **disabled by default**; Advanced create is rejected with HTTP 422 while the flag is off, and
> Advanced import is unconditionally rejected with HTTP 409 in this release. Windows runtime and
> Windows CI are not claimed as passed. D-3 is not claimed as passed. Nothing was pushed or merged.

## 1. Scope delivered

### B4a — Host-state contract and layout

- New `backend/app/core/host_state.py`: frozen `HostStateLayout` with root, `server-meta`,
  `class-c-vault`, `quarantine`, `lec`, `cas`, `repos`, `locks`, `journal`, plus
  `host_root` (Docker-daemon-visible string, never a panel path).
- Panel root resolution per D-B4-1/D-B4-13: explicit `ONX_HOST_STATE_DIR`/`MCS_HOST_STATE_DIR`
  else `parent(servers_data_dir)/host-state`; relative explicit paths resolved with `abspath`;
  canonical `realpath` used for containment and creation; the root is rejected if it is a symlink,
  is not absolute after resolution, or falls inside `servers_data_dir`.
- Host-visible root per D-B4-1/D-B4-3: absolute `ONX_HOST_STATE_HOST_DIR`, else lexical
  `parent(host_data_dir)/host-state`, else `None`; lexical normalization only, no panel
  containment or `resolve()`.
- Layout creation with `0700` directories, descriptor-based marker read/write (`O_NOFOLLOW`,
  `fchmod`, typed `HostStateError`), and marker status `mounted`/`unverified`/`absent`.
- D-B4-2: `cas_root` and `quarantine_dir` derive from the single host-state root; no separate keys.
- Config: `host_state_dir` and `host_state_host_dir` on `AppSettings`; `.env.example` documents both.
- `docker-compose.dood.yml`: bind-mounts the host-visible host-state directory at
  `/app/data/host-state`; no server-container mount. The marker reports `verified` when the
  host-visible path matches, otherwise `unverified`.

### B4b — Host lockfile service and private atomic write

- `backend/app/modules/versioning/infrastructure/fs_atomic.py`: `atomic_write_private` — exclusive
  temp in the target directory, `0600`, `fsync` file and parent, atomic `os.replace`, cleanup on
  failure; raises `app.core.allowlist.SymlinkEscapeError` so infrastructure does not import
  application code.
- New `backend/app/modules/versioning/application/lockfile_service.py`: host-only authoritative
  read/write at `server-meta/<server-id>/onx-jars.lock.json`; validates the server segment; rejects
  symlinked parents; writes `0600` and parents `0700` where owned; returns typed
  `LockfileServiceError` for symlink/OS errors; never reads a copy under the server root.
- D-B4-10/D-B4-11: the backup payload never contains the host lockfile, and no `/data`
  informational copy is written.

### B4c — Tree scanner core

- New `backend/app/modules/versioning/infrastructure/server_tree_scanner.py`:
  `scan_server_tree(root, *, max_files=200_000, max_total_bytes=20 GiB,
  dynamic_class_c=frozenset()) -> ScanReport`.
- Canonical relpath validation before classification; symlink/reparse rejection; pruning of
  `libraries`, `versions`, loader caches, `logs`, `crash-reports`, and `cache`; file-count and
  byte limits with explicit `truncated`; casefold collision tracking; deterministic sorted output.
  Adoption ingests only `A-JAR`/`A-CAS` classes, so world/E files are never lockfile entries.
- Unreadable directory, unreadable root, `is_dir`/`is_file` failure, and file `stat` failure are
  hard `ValueError`s, never silent skips (review fix).
- Additive `ScanReport.skipped_dirs` field recorded as an approved additive change.
- D-B4-7: this batch owns the tree scanner only; the secret scanner remains P2-4.

### B4d — Loader identity and baseline adoption

- New `backend/app/modules/versioning/application/loader_ref.py`: derives `LoaderRef` from
  `server_type`, `startup_jar`, and LEC paths; Paper/Purpur jar/build parsing; Fabric/Forge/
  NeoForge loader-version discovery from `libraries/` or the startup jar; Minecraft-version
  fallback; no schema change (D-B4-4).
- New `backend/app/modules/versioning/application/baseline_adoption.py`:
  `ensure_simple_baseline_lockfile(server_id)` — Simple-only; no deployment → `skipped`; truncated
  scan → `ValidationError`; containment check against the host-state root; POSIX preflight;
  per-file `open_safe_path_fd` and staged `0600` temp; CAS ingest via `ArtifactCas.put_file`;
  digest verification; deterministic lockfile with `base_overrides={}`; atomic host-only write
  (D-B4-5); idempotent when a valid lockfile is already present (D-B4-12).
- Cleanup covers every phase: a single outer `finally` removes the staged `.onx-adopt.*.tmp` and
  closes the source fd (review HIGH fix).
- Windows: adoption raises `CasUnsupportedPlatformError` (D-B4-8).
- No `/data` copy and no lockfile in the backup archive (D-B4-10/D-B4-11).

### B4e — Backup pre-flight hook

- `run_backup_task` awaits `ensure_simple_baseline_lockfile(str(server_id))` inside the existing
  `try`, after ID construction and before `saga.execute`.
- Nested `except CasUnsupportedPlatformError` logs
  `adoption_skipped_unsupported_platform` at WARNING and continues the backup (D-B4-8).
- Every other adoption error reaches the existing generic failure path: job marked
  failed/failed_timeout, commit, cancellation cleared, exception re-raised (D-B4-9, POSIX fail
  closed).
- INFO log with status/reason/counts; WARNING per quarantined path only (no contents).
- `backup_orchestrator.py` untouched; no archive/payload change.

### B4f — Advanced feature flag and D-10 import block

- `AppSettings.advanced_mode_enabled: bool = False`; `ONX_`/`MCS_` env parsing via the existing
  dual settings sources.
- `SystemStatusResponse.advanced_mode_enabled: bool = False`; both `GET /api/v1/setup/status` and
  `PUT /api/v1/setup/access-mode` merge the live `ConfigFactory.global_settings()` value, which
  wins over any bus payload value (D-B4-6).
- `CreateServerHandler`: top-of-method gate for `mode="advanced"` when the flag is off →
  `VALIDATION_ERROR` → HTTP 422; flag on keeps existing behaviour; Simple is never gated.
- `ImportServerHandler`: top-of-method **unconditional** block for `mode="advanced"` →
  `CONFLICT` with `details={"mode": "advanced"}` → HTTP 409 (D-10). Documented boundary: the
  `/api/v1/servers/import` route still validates its staging directory before dispatch, so an
  expired staging directory returns 404 before the command-level 409.
- No new route; route/permission contract stays 155/155.

### B4g — Flag-gated Advanced chooser (create only)

- `ServerModeChooser` gains `advancedEnabled?: boolean` (default `false`). When false the UI is
  exactly the previous Simple-only chooser; when true it renders an `Advanced` card with the
  `Preview` badge and the contracted description, selectable styling, and `onChange("advanced")`.
- `ConfigStep` forwards the flag; `CreateServerPage` calls `api.getSetupStatus?.()` once on mount,
  enables the card only for `advanced_mode_enabled === true`, and defaults to false on rejection or
  a missing field; the wizard is never blocked.
- `ImportServerPage.tsx` and its test are untouched and remain Simple-only.
- No new dependency, route, or backend change.

### B4h — Verification-only migration gate and documentation

- No production or test code change (D-B4-14/D-B4-15). This report records the final verification,
  the migration gate, decisions, residuals, and the proposed STATE/current-state delta.
- `docs/current-state.md`, `docs/decisions/*`, `docs/roadmap/*`, `.ai/STATE.json`, and the owner's
  main worktree were not modified.

## 2. Changed files and final hashes

All paths are relative to the worktree root. Hashes are SHA-256 of the committed file contents at
`8c9cb73` (B4g tip); this report is added afterwards by B4h.

| File | Status | SHA-256 |
|---|---|---|
| `.env.example` | modified | `9888843ab366bb17dd7193f4ef874f6c5319a272a88cb861c6648eec9bcca437` |
| `docker-compose.dood.yml` | modified | `0ad5e39b9ac114a73a0b8d47a3caff732507ede8098b4594f9c25491aafb2cf5` |
| `backend/app/core/config.py` | modified | `e937a94da5dfcd4a93abfc78b2cc3144a4e2d9a0412b544b3933a2d220248f12` |
| `backend/app/core/host_state.py` | new | `749cacaa05cb7a11740e6a6ff3bd155056e57ff0ed2004f315d7ca6e3d4726e5` |
| `backend/app/api/v1/routers/setup.py` | modified | `430a845f445f382f41742ad0adb8638ebb9b51a90c80e27c780b4ec4d7291bfe` |
| `backend/app/modules/server/application/commands/create_server.py` | modified | `cb59b6c9e0bd1944c84195424b3a22abf66a94325e0eed9e65752369e44d05e3` |
| `backend/app/modules/server/application/commands/import_server.py` | modified | `7d9c4128228b6721baddb14f8b48809c2bed7cacf47a09c11b37f66e0d326add` |
| `backend/app/modules/versioning/application/baseline_adoption.py` | new | `651a9ddadf6b3cbd12841c8ad6c76541db1abb908ad3ced5e23471b1fcaedcb8` |
| `backend/app/modules/versioning/application/loader_ref.py` | new | `30e029cf31fa718d502bdfb94328c92899c0c15a36ca28a6648a42d6e9e3d486` |
| `backend/app/modules/versioning/application/lockfile_service.py` | new | `123027962ba84176768d02187debb38686b0801841ad181859870637c5b41089` |
| `backend/app/modules/versioning/infrastructure/fs_atomic.py` | modified | `1e32c321219781ec1b744a7e2e2b6c5c078d075eadb76071417bcb231f8ed4a9` |
| `backend/app/modules/versioning/infrastructure/server_tree_scanner.py` | new | `961970e5e4b582def11f17193bf3e0bff1ec744b481919d7226a35f5bda60628` |
| `backend/app/tasks/definitions/backup_task.py` | modified | `14d1c44736a0ded88221e86e3d55c6456c02f0c6aad5e65f31cbc3d11e77292f` |
| `backend/tests/core/test_host_state.py` | new | `f4e4efa4914194a4f37745eae1857be6b22916a4f1cf9adb74249fb3b5621b33` |
| `backend/tests/application/test_lockfile_service.py` | new | `732fe8116149a9fa687a595fd78ee16f7cbde61506d898a1dd7cdbe37f1b0d52` |
| `backend/tests/infrastructure/test_server_tree_scanner.py` | new | `2df2301798eaca3731a5a74159462d85191217d5abd9231197779348ece75300` |
| `backend/tests/infrastructure/test_server_tree_scanner_windows.py` | new | `87efaa424d2a361efe046ee105217787715e50a1f2ee6eabca030401b4fb88ee` |
| `backend/tests/application/test_loader_ref.py` | new | `d48d9c1a5d44c40d58a81f974ba730e6dfb5af20f255cfce41330f2ef36cf668` |
| `backend/tests/application/test_baseline_adoption.py` | new | `ed895300998911e817fe0ba5b3269f6f82045e5488a93d4faf0c444ba6156ade` |
| `backend/tests/tasks/test_backup_baseline_hook.py` | new | `487308ea6cd5e63df0bec84358fa98ea379a2c9f36281613d400803086abe0e2` |
| `backend/tests/api/test_advanced_mode_flag.py` | new | `fc17bdd635aaadacf3dd9034c82d104e6f4b729ee9420de75180a32c00d8040e` |
| `backend/tests/application/test_server_mode_creation.py` | modified | `f4e2db87cace05c49826a7e4b27380f45e1de03b3cbc7d282ddf604b82bfc75f` |
| `frontend/src/types/index.ts` | modified | `08eae139de6b7542e4922f442620d1cac1c7e26ad1679a1339a2bc49fde39eb8` |
| `frontend/src/server_manager/components/wizard/ServerModeChooser.tsx` | modified | `7e3ae6538e7cfd96c8329ef63c89c0f62fd661969abfc3b75295785d3793c8ba` |
| `frontend/src/server_manager/components/wizard/ServerModeChooser.test.tsx` | modified | `e6faa62ac2e1eebfb428c8f8bd9e35b24f7fc1194f35dae31b2b58e18a50794a` |
| `frontend/src/server_manager/components/wizard/ConfigStep.tsx` | modified | `3a5668e4343a83022627c9053e02d328ce4f2e27956805bc5c4b24324a8e4009` |
| `frontend/src/server_manager/pages/CreateServerPage.tsx` | modified | `2cb5cad95240ea2e3b4ef62f66b100daadbffaa8ed81701efd127a1f15e2a85c` |
| `frontend/src/server_manager/pages/CreateServerPage.test.tsx` | modified | `8d4363e20f0cd1a5091390555edec82df5808e79a4a3b50344f92a6775b49c88` |

B4 diff from base: 28 files changed, 4338 insertions, 20 deletions (code/tests/config/frontend; the
B4h report adds one more docs file).

## 3. Verification evidence

### 3.1 Per-batch targeted verification (Manager runs)

| Batch | Command scope | Result |
|---|---|---|
| B4a | `pytest -q tests/core tests/test_config.py` + allow-list matrix | **666 passed, 2 skipped**; matrix `MISMATCHES: 0` |
| B4b | lockfile service + lockfile domain + restore service + stage-C materialization + FX4 hardening + host-state | **276 passed** |
| B4c | `pytest -q tests/infrastructure tests/core` + allow-list matrix | **1604 passed, 3 skipped**; matrix `MISMATCHES: 0` |
| B4d | `pytest -q tests/application tests/domain/test_lockfile_v21.py tests/integration/test_lockfile_cas_roundtrip.py` | **1012 passed** |
| B4e | `pytest -q tests/tasks tests/services` | **66 passed** |
| B4f | `pytest -q tests/api tests/application tests/auth/test_batch2_endpoints_and_commands.py` | **1260 passed**; route contract 155/155 |
| B4g | targeted vitest (Chooser + Create + Import) | **34 passed** (7/19/8) |
| B4g | `npx tsc --noEmit`, `npm run lint`, `npm run build` | exit 0, exit 0, build success |
| B4h | migration gate (below) | **6 passed** |

Focused counts cited during the batch runs: B4a host-state + config subset 111; B4b lockfile
service/domain 176; B4c scanner + matrix 60; B4d loader/adoption/roundtrip 29; B4e hook + task 11;
B4f flag/D-10 suite 31.

### 3.2 Migration / persistence gate (verification only)

- `pytest -q tests/core/test_backup_pinned_migration.py tests/infrastructure/test_backup_pinned_persistence.py`
  → **6 passed**.
- `alembic heads` → exactly one head: `b1e2100000025 (head)`.
- `RELEASE_MINIMUM_DB_REVISION == EXPECTED_ALEMBIC_HEAD == "b1e2100000025"`.
- No Alembic revision was added, and `db_revision.py`, `test_batch4_core_saga.py`, and pinned tests
  were not edited (D-B4-14).

### 3.3 Final full verification

| Suite | Result |
|---|---|
| Full backend `pytest -q` | **4231 passed, 6 skipped, exit 0** (22m 20s) |
| Full frontend `npm run test` | **1205 passed / 132 files** |
| `npx tsc --noEmit` | exit 0 |
| `npm run lint` | exit 0 |
| `npm run build` | success |
| `git diff --check` | clean |
| `git ls-files .ai` | empty (`.ai/` never staged or tracked) |

### 3.4 Six gates

| Gate | Result |
|---|---|
| `check-db-revision` | PASS — schema revision `b1e2100000025` compatible |
| `check-ruff-baseline` | PASS — 486 violations across 21 rules, all at/below baseline |
| `check-version-propagation` | PASS |
| `check-route-contract` | PASS — 155 live routes vs 155 contract entries |
| `check-ps1-bom` | PASS — 5 tracked `.ps1` files verified |
| `check-stray-db` | PASS — no stray SQLite files |

## 4. Approved decisions and dispositions

| Decision | Disposition |
|---|---|
| D-B4-1 | Implemented in `host_state.py`; explicit/env/fallback roots; lexical host root; inside-servers-dir rejection. |
| D-B4-2 | `cas` and `quarantine` derive from the single layout root. |
| D-B4-3 | DooD bind mount added; marker reports `verified`/`unverified`; an invisible host path is `unverified`. |
| D-B4-4 | Loader identity from `server_type`/`startup_jar`/LEC with Minecraft-version fallback; no schema change. |
| D-B4-5 | Adoption writes `base_overrides={}` and the host-only authoritative lockfile. |
| D-B4-6 | Flag default OFF; both setup routes merge live value; create gated 422; import always 409. |
| D-B4-7 | Tree scanner only; secret scanner deferred to P2-4. |
| D-B4-8 | Windows adoption raises `CasUnsupportedPlatformError`; backup hook warns and continues. |
| D-B4-9 | Other adoption failures fail the backup closed on POSIX. |
| D-B4-10 | No lockfile in the backup archive. |
| D-B4-11 | No `/data` informational lockfile copy. |
| D-B4-12 | No adoption lease; deterministic scan + atomic replace. |
| D-B4-13 | Relative `ONX_HOST_STATE_DIR` resolved with `abspath`; tests pin cwd. |
| D-B4-14 | `pinned` verification only; no new revision; head stays `b1e2100000025`. |
| D-B4-15 | Owner docs/STATE untouched; this report contains the proposed delta only. |

## 5. Review record and dispositions

Each batch was reviewed read-only by a different model (GLM-5.3-Flash) from the builder
(Gemini 3.8 Flash High). No review was skipped. Highlights:

- **B4a:** PASS WITH FIXES → PASS → PASS (3 rounds). Fixed leaf-only symlink/chmod checks,
  abspath-vs-realpath containment fail-open, and marker I/O hardening; final LOW on
  `UnicodeDecodeError` typing micro-fixed.
- **B4b:** PASS (3 LOW). `OSError` wrapping fixed in-slice; standalone `server-meta` ancestor mode
  and Windows read symlink-following accepted as residuals.
- **B4c:** PASS WITH FIXES (1 MEDIUM) → PASS. Silent `scandir`/stat failures converted to hard
  errors; directory-level casefold collisions documented as a contract-literal residual.
- **B4d:** PASS WITH FIXES (2 HIGH) → PASS. Staged temp leak on copy-phase errors fixed with a
  single outer `finally`; global `os.name` mutation removed with `_platform_is_posix()`; forge
  parsing simplified; fallback tests added. Final LOW Windows skipif micro-fixed.
- **B4e:** PASS (2 LOW). Added INFO-log and cancelled-branch tests; no production change.
- **B4f:** PASS (3 LOW). Added live-setting-over-payload precedence tests and the create-gate
  no-row assertion. Four `# noqa: B008` annotations in `setup.py` are accepted as targeted-ruff
  churn (baseline 491 → 486).
- **B4g:** PASS — no findings. Reviewer independently reran 34 targeted vitest tests and `tsc`.
- **B4h:** PASS — no findings. Reviewer recomputed all 28 file hashes, confirmed the 28-file diff,
  the exact per-batch counts and six gate results, the migration head, the non-claims, and the
  untouched owner docs/`.ai/STATE.json`.

## 6. Residuals, risks, and non-claims

- **Windows runtime / CI:** not run. Windows Simple-mode adoption is expected to raise
  `CasUnsupportedPlatformError`; the backup hook then continues. Windows scanner tests are
  unit-level only. Windows CI remains pending.
- **Loader identity imprecision:** created Paper/Fabric/Forge/NeoForge servers may fall back to
  the Minecraft version when the jar/loader filename is not parseable; this can cause a spurious
  full refresh on a later upgrade, not a corruption. No schema-backed loader-version column was
  added (D-B4-4).
- **Containment:** adoption compares the lexical `abspath` of the deployment server directory with
  the canonical host-state root; physical symlink resolution of the server root is not part of B4.
- **Directory-level casefold collisions** (`Mods/x.jar` vs `mods/y.jar`) are not detected; the
  scanner detects file-level collisions only.
- **Private domain regex imports:** `loader_ref.py` imports `_LOADER_ID_RE`/`_VERSION_TOKEN_RE`
  from the lockfile domain module; accepted layering residual.
- **Advanced import boundary:** the route's staging-directory validation can return 404 before the
  command-level 409 for an expired staging path; the unconditional import block applies once the
  command is dispatched.
- **B4g dev-only double fetch:** `main.tsx` wraps the app in React `StrictMode`, so development
  builds can call `getSetupStatus` twice per mount. The GET is idempotent and the page follows its
  pre-existing sibling-effect pattern; production and tests call it once. No unmount cancellation
  was added.
- **B4 scope:** B4 does not implement the secret scanner (P2-4), Git/export wiring, quarantine
  GC/retention, or Windows CAS. These remain future slices.
- **No claims:** P2 is not complete; D-3 is not passed; no CI run exists; nothing was pushed or
  merged; no Windows runtime evidence exists.

## 7. Proposed STATE / current-state delta (not applied)

Per D-B4-15 these files were intentionally **not** modified. The owner may apply the following
delta in the main worktree:

- `docs/current-state.md`: change the P2 line from
  “IN PROGRESS — B2+B3 slice IMPLEMENTED_PENDING_FIRST_CI_RUN” to
  “IN PROGRESS — B2+B3+B4 slice IMPLEMENTED_PENDING_FIRST_CI_RUN (2026-11-13)”, and append:
  “B4 (Core Substrate: host-state layout, host lockfile service, tree scanner, loader identity +
  baseline adoption, backup pre-flight hook, Advanced flag backend + D-10 import block, flag-gated
  chooser) implemented as seven local commits `1b25a1b`…`8c9cb73` on
  `slice/p2-b4-core-substrate` based on `47580e4`; B4h adds this report. Targeted and final local
  verification passed; six gates PASS; migration head remains `b1e2100000025`. Advanced mode is
  still OFF by default; import remains blocked. P2 is not complete; Windows CI and D-3 remain
  pending. See `docs/reports/P2-B4-IMPLEMENTATION-2026-11-13.md`.”
- `.ai/STATE.json` (local-only, git-excluded): record the same phase status, branch
  `slice/p2-b4-core-substrate`, base `47580e4`, B4 commits through the B4h docs commit, the final
  backend/frontend counts and six-gate results from this report, and `advanced_mode_enabled=false`.
  Do not cite `.ai/STATE.json` as branch evidence.

## 8. Repository record

- Commits on `slice/p2-b4-core-substrate`:
  `1b25a1b` B4a → `5d6856e` B4b → `890f320` B4c → `bf8ec10` B4d → `4037c6b` B4e →
  `e93c03a` B4f → `8c9cb73` B4g → B4h docs commit.
- Every commit used explicit paths only; no `git add -A`/`git add .`; no push, merge, amend,
  reset --hard, stash, force, branch deletion, or worktree deletion.
- `.ai/` content is excluded and was never staged, tracked, copied into a prompt/report, or cited
  as evidence.
- The owner's main worktree and uncommitted docs were not touched.
