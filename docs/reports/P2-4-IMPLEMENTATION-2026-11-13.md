# P2-4 Branch-Aware Files / Native Save & Commit — Implementation Report — 2026-11-13

**Slice:** P2-4 (P2a) — branch-aware Files and native Git Save & Commit.
**Worktree:** `/mnt/D/workspace/onx-manager-wt/p2-b4-core-substrate`
**Branch:** `slice/p2-b4-core-substrate`
**Base:** `4d25a9f15a9359c7144906bc3b7fb49246e1b089` (P2 B4h report tip).
**Status:** IMPLEMENTED_AND_VERIFIED — batches 1, 2, and 3 implemented and verified; included in the
slice commit together with the P2-3 work and both reports.

> **Boundary statement:** P2-4 is a slice of P2a, not P2 completion. Advanced mode remains
> **disabled by default**. Advanced create stays feature-flagged and POSIX-only; Advanced import
> remains rejected with 409; installer-based Forge/NeoForge Advanced create remains rejected;
> Windows remains Simple-only. D-3 is not claimed as passed. Nothing was pushed or merged, and no
> branch/worktree/history was deleted or rewritten. Native Save & Commit does not yet project
> commits into the legacy `server_commits` read models. The clean-export service itself is reported
> separately in `P2-3-IMPLEMENTATION-2026-11-13.md`.

## 1. Scope delivered

### Batch 1 — Branch-aware Files read/write root

- New `backend/app/modules/versioning/application/queries/get_branch_files_root.py`:
  `GetBranchFilesRootQuery` resolves the Files root for a branch.
  - Repository-backed Advanced servers resolve to `<server_root>/.onx/worktrees/<branch>`.
  - `main` resolves to its worktree and is marked read-only.
  - Unknown branches return 404; archived branches return 409.
  - Explicit `branch` on a DB-only Advanced server returns 409.
  - Simple servers and DB-only Advanced servers keep the live server root.
- `backend/app/api/v1/routers/files.py`: every Files operation accepts the optional `branch`
  query parameter; the resolver now yields `(root, target, rel, read_only, git_scoped)`.
  - `main` branch mutations are rejected with 403.
  - Root-level `onx-jars.lock.json` and `.gitattributes` are panel-managed and reject Files
    writes/deletes on every branch; nested same-name files remain ordinary Class-B candidates.
  - `.git` is in `PROTECTED_DIRNAMES`; listings hide it and direct access returns 403.
  - On a Git-scoped branch, only allow-listed Class-B files can be created, written, uploaded,
    or deleted. Class-A/JAR, Class-C, Class-E, and rejected paths return 403 instead of becoming
    untracked or misclassified content. Directory creation/deletion is still allowed.
- `backend/app/modules/versioning/infrastructure/git_branches.py`: branch lookup and
  `open_runner()` expose the existing hardened `GitRunner` to application services.
- `backend/app/modules/versioning/application/git_branch_adapter.py`: context detection hardened
  for legacy server projections that lack mode/deployment attributes.
- Wiring: `GetBranchFilesRootQuery` is registered in
  `backend/app/modules/versioning/application/__init__.py` and `backend/app/registration.py`.

### Batch 2 — Native Git Save & Commit

- New `backend/app/modules/versioning/infrastructure/git_save_commit.py`:
  `GitSaveCommitService.save()` performs the normative Save & Commit pipeline against one
  branch worktree:
  1. Reset the index so previously staged Class-C/E blobs cannot ride along.
  2. Read changed paths from NUL-delimited `git status` with rename detection disabled.
  3. Reject deletion of the authoritative lockfile before any read.
  4. Validate every changed path with `validate_canonical_relpath()` before classification.
  5. Quarantine hostile executables under config roots (read cap 16 MiB), remove them from the
     worktree, and never stage them; quarantine failures are non-blocking warnings.
  6. Ingest Class-A/JAR and Class-A/CAS paths into the host CAS, record/update their lockfile
     entries, and remove the working copy. Deleted Class-A paths drop their lockfile entry.
  7. Normalize Class-B text to UTF-8/LF; `server.properties` strips comments and Class-D keys,
     sorts keys, and uses LF. PNG bytes are not text-normalized.
  8. Reject conflict markers and unparseable JSON/YAML/TOML/properties configs.
  9. Run the Structured & Pattern Secret Scanner before writing normalized bytes or staging.
  10. Enforce Class-B size policy: `server-icon.png` > 1 MiB is rejected; other Class-B files
      > 1 MiB up to 16 MiB are routed to A-CAS; > 16 MiB is rejected.
  11. Reject case-fold collisions across tracked plus changed paths.
  12. Write the canonical lockfile and panel-owned `.gitattributes`, stage only Class-B changes,
      routed-path removals, lockfile, and attributes, then run native `git add -A`/`git commit`.
- The native path keeps the existing route
  `POST /api/v1/servers/{server_id}/versioning/commits` (route count stays 156).
  `CreateCommitHandler` dispatches to native Git only when `repo.git` exists; legacy D8 servers
  keep the previous command behavior.
- Native commits emit `CommitCreatedEvent` and return `engine: "native-git"` with commit id,
  parent id, committed files, CAS-routed paths, quarantined paths, and warnings.
- No `server_branches.head_commit_id` write: Git object ids are 40–64 hex characters while the
  legacy column is `String(36)`. Branch heads are already Git-authoritative at read time.
- `backend/app/api/errors.py`: explicit HTTP mappings for the new Git/secret/size/case errors
  (409/413/422/500/501/503/504) so command-bus results no longer collapse to 400.

### Batch 3 — Branch-aware Files UI and Save & Commit

- New `frontend/src/server_manager/context/ServerBranchContext.tsx`: `ServerBranchContext`
  exposes `{ branch, setBranch, gitBacked }` to every page under `ServerShell`.
- `frontend/src/layouts/ServerShell.tsx`:
  - For Advanced servers it queries `GET /versioning/branches` and treats the server as
    Git-backed only when at least one branch has a non-null `worktree_path` (DB-only Advanced
    branches keep no selector).
  - The header shows a `Branch` selector when Git-backed. Selection is synced into the URL
    `branch` query parameter with `navigate(..., { replace: true })`, so the selected branch
    survives page navigation and deep links; `main` removes the parameter.
  - The selection is persisted per server in `localStorage` under
    `onx.selectedBranch.<serverId>`; a URL `branch` wins over stored state.
  - The provider wraps `<Outlet />`, so Files and other pages read the same active branch.
- `frontend/src/server_manager/pages/ServerFilesPage.tsx`:
  - Resolves `activeBranch` from the URL `branch` parameter or the shell context; branch is
    passed to every Files operation (`list`, `content`, `PUT`, `DELETE`, `upload`, `download`,
    `mkdir`).
  - `main` is rendered read-only: edit/save, upload, new-folder, delete, bulk delete, and
    Save & Commit controls are hidden; a branch banner explains that the saved state cannot be
    edited.
  - On a working branch the page shows a Save & Commit button that opens a commit-message
    modal and posts `{ message, branch_name }` to
    `POST /api/v1/servers/{server_id}/versioning/commits`; the success toast includes the
    short commit id plus CAS-routed/quarantined counts when present, then invalidates Files and
    branch queries.
  - Switching branches closes the editor, clears selection/edit state, and drops stale
    `file`/`edit` query parameters.
- `frontend/src/services/api.ts`: all seven Files methods accept an optional `branch` parameter
  and add it to the query string; `ServerBranch` gains `worktree_path` and `worktree_locked`.
- `frontend/src/services/queryClient.ts`: Files list/content query keys include the branch, and
  branch/commit versioning keys are defined.
- Simple servers ignore the branch UI even if a stray `?branch=` is present; they keep the live
  server root and the existing single-root behavior.

## 2. Changed files and final hashes

Batch 1 post-edit hashes (`/tmp/p2-4-batch1/post.txt`):

| File | Status | SHA-256 |
|---|---|---|
| `backend/app/modules/versioning/infrastructure/git_branches.py` | modified | `12e443fdeb5a89a54e7ec32c66c3dc2d1bedb305e83ad0cd57e1a4978d44f2c7` |
| `backend/app/modules/versioning/application/queries/get_branch_files_root.py` | new | `962757b36d34702a81d825aa5f84d5b31ab6e196748aea0165552fe4e7dcc9db` |
| `backend/app/modules/versioning/application/__init__.py` | modified | `f643cf32419b6cca1f103c420787e578cd55864d07f873838135acb36f607c06` |
| `backend/app/registration.py` | modified | `e1bef39df4234d24b98072f05c947997b4b5a8909cdd359b7b5134999a45404a` |
| `backend/app/api/v1/routers/files.py` | modified | `2dcc583d018410ae1839022e24e2acd2da140948f0952ce8eef8270eab0daf21` |
| `backend/tests/api/test_branch_files_api.py` | new | `1e8896c690ca38eb4f29af43fbcc13d750ad516bca3457a1ded2f547984e3de6` |
| `backend/tests/api/test_fx4_hardening.py` | modified | `c27d7bceb2b7fb0fa1dafc9a580190070b4c12989f26aa3512dfacd9a62bea09` |

Batch 2 post-edit hashes (`/tmp/p2-4-batch2/post.txt`) — current content:

| File | Status | SHA-256 |
|---|---|---|
| `backend/app/modules/versioning/infrastructure/git_save_commit.py` | new | `e0c8eb7496b38bc044f60dcdd3562a14878af201cf46b33f74dbaa06b121062f` |
| `backend/app/modules/versioning/infrastructure/git_branches.py` | modified | `37b5ea55afa4864c431db62f5ed6951841e0184e1abc92c327197137cd8dd26d` |
| `backend/app/modules/versioning/application/commands/create_commit.py` | modified | `954a627284cafbc6b3e019405d38f4502a1720ba672f1edf55d77f72ba66cd74` |
| `backend/app/modules/versioning/application/git_branch_adapter.py` | modified | `7374630f8e6e315ba3ea7ed798a9cfc5c7f85ef51cca815661c6203ded00bc65` |
| `backend/app/api/v1/routers/files.py` | modified | `342891728ab4e8cc99fd8328ac6d8b0342d416059948e1183ddd061e22f05618` |
| `backend/app/api/errors.py` | modified | `709c83ea359ddf8ce7c6b39591373bffcb8c42ac9de81a7d70ba4f595edfcf9e` |
| `backend/tests/infrastructure/test_git_save_commit.py` | new | `da7eb85141d4aba3a21880f69e81fbaca2d693b82414bdcc915de43981487fdf` |
| `backend/tests/api/test_save_commit_api.py` | new | `8ba207e6d9b07bf9b2d917ab338b470c38b1d813b1da1d4f976ff258601a06fb` |
| `backend/tests/api/test_branch_files_api.py` | modified | `f04a008204811136e6a4e22cd336cfbe06e275eb8416d753c3290a9e6076f9a6` |
| `backend/tests/api/test_fx4_hardening.py` | modified | `028080220e5b56b9b7a8c00247170d9204fac373d0e4e694e0d436960556f550` |

Batch 1 hashes for files that batch 2 later touched are superseded by the batch 2 table above.

Batch 3 post-edit hashes (`/tmp/p2-4-batch3/post.txt`):

| File | Status | SHA-256 |
|---|---|---|
| `frontend/src/layouts/ServerShell.tsx` | modified | `70c0a6d30001eb7172255ca7133a4130313f2adc4f56d26cfbbb8f9bc4bb5390` |
| `frontend/src/layouts/ServerShell.test.tsx` | modified | `02a3c87516bdea2ab120dbfa628325bdd087a3499c57cef0a5a5795b62c04122` |
| `frontend/src/server_manager/pages/ServerFilesPage.tsx` | modified | `c26d53f91e1a91403941a2ed0980ae65dc47a083c7938229dd739998bd34992a` |
| `frontend/src/server_manager/pages/ServerFilesPage.test.tsx` | modified | `2083dad685d66ad9196eab5fd8d88e4f2b426937c6eb94887b09fb7fa689f48e` |
| `frontend/src/server_manager/context/ServerBranchContext.tsx` | new | `eb10adb9b44843cd11401de4ed6aabb2eb55c1e5331e894993139677dcf6cc88` |
| `frontend/src/server_manager/types.ts` | modified | `3561972108dd2ce787534969670f5a283b638c79f5f8aba3a51433314c757e30` |
| `frontend/src/services/api.ts` | modified | `54b9c1116a40610de58ab0ff403d90870dc4d9eaaa17c3dd67be62c3a9810825` |
| `frontend/src/services/queryClient.ts` | modified | `9cec1d691f7144d39df946692bb0e5cf89b7a738a33e6df0326f92977f246f5f` |
| `frontend/src/services/api.test.ts` | modified | `65c50c82b9297445e0491bd7ff6adf0473f1bfaad1cc04e858757ac620862c11` |

Final backend/frontend verification hashes are re-captured after the last edit and recorded in
`/tmp/p2-4-batch3/post.txt` and `/tmp/p2-4-final/`.

## 3. Verification

### Batch 1 evidence

- Targeted Files/branch tests: **28 passed** (`tests/api/test_branch_files_api.py`,
  `tests/api/test_fx4_hardening.py`, plus branch-related regression).
- Broad regression: **439 passed**.
- Pyright clean on batch 1 production files.
- Ruff: only pre-existing baseline-class findings.

### Batch 2 evidence (interim)

- Targeted: **34 passed** —
  `tests/infrastructure/test_git_save_commit.py`,
  `tests/api/test_save_commit_api.py`,
  `tests/api/test_branch_files_api.py`,
  `tests/api/test_fx4_hardening.py`.
- Broad regression after batch 2 wiring: **629 passed** (tests/api, Git branch/repository/runner
  suites, route contract, host-state, allow-list matrix). The routed-tracked-file refinement and
  its regression test were added after that run and are covered by the targeted rerun above.
- Pyright on changed production files: no new errors. Pre-existing errors remain in
  `create_commit.py` (`res` unbound, legacy manifest typing) and `errors.py`
  (`CommandResult`/`FastAPI` under `TYPE_CHECKING`).
- `git diff --check`: clean.
- Full backend suite and the complete gate set will be run once at the end of the P2-4 slice.

### Batch 3 evidence

- Targeted frontend tests: **72 passed** —
  `src/layouts/ServerShell.test.tsx` (26),
  `src/server_manager/pages/ServerFilesPage.test.tsx` (20), and
  `src/services/api.test.ts` (26).
- Full frontend suite: **1,212 passed** (`npx vitest run`).
- `npx tsc --noEmit`: clean.
- `npm run lint` (`eslint src/`): clean.
- `npm run build`: successful production build.
- New coverage: selector visibility for Git-backed vs Simple/DB-only Advanced servers, branch
  selection, branch-scoped listing/content read/write, Save & Commit request body, read-only
  `main` controls, and branch query parameters on the API client.

### Final verification

Run once after the last code edit (including the P2-3 modules), with no concurrent pytest:

- Full backend suite: **4,414 passed, 6 skipped** (exit 0) — includes the P2-4 suites
  (`test_branch_files_api.py`, `test_save_commit_api.py`, `test_git_save_commit.py`,
  `test_fx4_hardening.py`), the P2-2 native Git suites, and the new P2-3 suites
  (`test_clean_export.py`, `test_directory_swap.py`).
- Gates: `check-db-revision` PASS; `check-version-propagation` PASS (0.1.0 across pyproject,
  package.json, runtime); `check-route-contract` **156 live routes vs 156 contract entries** PASS;
  `check-ruff-baseline` PASS (486 violations across 21 rules, all at or below baseline);
  `check-ps1-bom` PASS (5 tracked `.ps1` files); `check-stray-db` PASS; `git diff --check` clean.
- Pyright on changed P2-4 production files (`files.py`, `git_save_commit.py`, `git_branches.py`,
  `get_branch_files_root.py`, `create_commit.py`, `git_branch_adapter.py`, `errors.py`): **7
  errors, all pre-existing** and documented in the P2-2 report — `errors.py`
  (`CommandResult`/`FastAPI` under `TYPE_CHECKING`) and `create_commit.py` legacy-branch
  handlers (`res` possibly unbound, `server_dir` optional access, manifest typing).
- Full-suite evidence log: `/tmp/p2-final-verify/pytest.log`; gate logs under `/tmp/p2-gates-*.txt`;
  post-edit hashes for the whole change set in `/tmp/p2-4-final/post.txt`.

## 4. P2a acceptance mapping

D-12 acceptance conditions touched by P2a/P2-4:

| # | Condition | P2a status |
|---|---|---|
| 1 | Advanced create produces external Git repo with eager `main` + initial commit | Met by P2-2 (report `P2-2-IMPLEMENTATION-2026-11-13.md`) |
| 2 | Branch create/delete/list maps 1:1 to Git refs + metadata; `main` non-deletable | Met by P2-2 |
| 3 | Branch Files reads/writes worktree; Save & Commit validates, scans, normalizes, commits | Met by P2-4 batches 1–3 |
| 4 | Simple server gets host baseline lockfile via `ensure_simple_baseline_lockfile()` | Met by P2-1/B4d and the backup pre-flight hook; no create-time duplicate added |
| 7 | Scanner blocks at repo init, Save & Commit, merge, D7, push, export | Partially met: repo init (P2-2), Save & Commit (P2-4); export consumes scanned content and fails closed on unresolved `${ONX_SECRET_*}` (P2-3 report); merge/D7/push remain P2b/P3/P5 |
| 9 | 1 MiB icon cap and 1–16 MiB Class-B → A-CAS routing | Met for Save & Commit (P2-4); other ingestion paths remain P2-5 |
| 12 | Suites, gates, frontend checks, docs/state sync | Frontend and P2-4 suites/gates evidenced here; full-P2 gate pass is P2b/P2-6 |

Conditions 5, 6, 8, 10, and 11 belong to P2b (clean export, D-3, container hardening,
lease/recovery/disk-full, Windows CI) and are not claimed by P2-4.

## 5. Known limits / pending

- Native commits are not projected into legacy `server_commits`/commit-history read models.
- No activity-log write on the native Save & Commit path yet; `CommitCreatedEvent` is emitted.
- Advanced import and installer-based Forge/NeoForge create remain intentionally blocked.
- Windows remains Simple-only.
