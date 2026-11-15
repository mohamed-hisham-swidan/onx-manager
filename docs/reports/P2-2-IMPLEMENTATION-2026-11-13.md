# P2-2 Repo / Branches Implementation Report — 2026-11-13

**Slice:** P2-2 Repo / branches — batches P2-2.1, P2-2.2, P2-2.3, P2-2.3.5, P2-2.4.
**Worktree:** `/mnt/D/workspace/onx-manager-wt/p2-b4-core-substrate`
**Branch:** `slice/p2-b4-core-substrate`
**Base:** `4d25a9f15a9359c7144906bc3b7fb49246e1b089` (P2 B4h report tip).
**Status:** IMPLEMENTED_PENDING_FIRST_CI_RUN — all P2-2 work is **uncommitted** by owner
instruction.

> **Boundary statement:** P2-2 is a slice of P2a, not P2 completion. Advanced mode remains
> **disabled by default**. Advanced create is available only behind the flag and only for
> non-installer server types on POSIX hosts; installer-based Forge/NeoForge creation and all
> Advanced imports remain rejected. Windows runtime and Windows CI are not claimed as passed.
> D-3 is not claimed as passed. Nothing was pushed or merged, and no branch/worktree/history was
> deleted or rewritten.

## 1. Scope delivered

### P2-2.1 — Hardened Git invocation

- New `backend/app/modules/versioning/infrastructure/git_runner.py`: `GitRunner` invokes Git
  without a shell, with absolute validated `repo.git`/`gitconfig` paths, one isolated
  `GIT_CONFIG_GLOBAL` file (`0600`, `safe.directory` only), `GIT_CONFIG_NOSYSTEM=1`, terminal
  prompts disabled, no pager/editor, `LC_ALL=C`, and the exact OD-v8.4-7 hardening overrides
  (`core.hooksPath=/dev/null`, `core.fsmonitor=false`, `protocol.allow=user`,
  `protocol.file.allow=never`, `protocol.ext.allow=never`, and the remaining tuple members).
- Typed Git errors in `backend/app/core/exceptions.py`: `GitError`, `GitConfigurationError`,
  `GitUnsupportedPlatformError`, `GitUnavailableError`, `GitCommandError`, `GitTimeoutError`,
  `GitRefValidationError`, `GitRemoteUrlError`, `GitRepositoryStateError`.
- Branch/ref validation combines `git check-ref-format --branch` with a stricter panel-owned path
  contract; remote URLs are validated for the future push path.

### P2-2.2 — External repository, eager `main`, initial commit

- New `backend/app/modules/versioning/infrastructure/git_repository.py`: bare repository at
  `<host_state>/repos/<server_id>/repo.git`, isolated `gitconfig` beside it, eager `main`
  ref/HEAD, initial commit built with `hash-object`/`update-index`/`write-tree`/`commit-tree`,
  and the `main` worktree at `<server_root>/.onx/worktrees/main`.
- Initial commit contains only: allow-listed Class-B files, the authoritative lockfile
  (`onx-jars.lock.json`), and the panel-generated `.gitattributes`. Class-A jar bytes, Class-C
  data, and Class-E data never enter the index, commit, or worktree. Class-B text is normalized
  to UTF-8/LF; `server.properties` is normalized (comments stripped, Class-D panel keys removed,
  keys sorted, LF endings).
- Containment checks keep repository storage outside the server tree; symlinked roots/parents and
  overlapping paths fail closed. Initialization is idempotent and never rewrites or resets an
  existing repository; an existing repo without `main` fails closed.
- `HostStateLayout.repo_dir()` added; the server-tree scanner now prunes `.onx` so worktrees are
  never re-adopted as server files.

### P2-2.3 — Branch and worktree lifecycle

- New `backend/app/modules/versioning/infrastructure/git_branches.py`: `GitBranchService` with
  Git-authoritative list/create/archive/delete.
  - Create requires an existing local start branch (default `main`), validates the name through
    Git and the panel path contract, creates the ref plus one worktree at
    `.onx/worktrees/<branch>`, and rolls back both on any Git failure.
  - Archive removes the worktree but keeps the Git ref and history.
  - Delete requires the branch to be fully merged into `main`, removes a clean unlocked
    worktree, verifies the ref did not move, then deletes the ref.
  - `main` is never archivable or deletable. Dirty or locked worktrees are refused.
- Adapter `backend/app/modules/versioning/application/git_branch_adapter.py` activates Git-backed
  behavior only when `repo.git` exists; legacy DB-only Advanced servers keep their previous
  lifecycle (D8).

### P2-2.3.5 — Secret scanner at repository initialization

- New `backend/app/modules/versioning/infrastructure/secret_scanner.py`: Structured & Pattern
  Secret Scanner covering private-key headers, Discord bot tokens/webhooks, Slack webhooks,
  GitHub PATs, AWS access keys, sensitive config keys, forbidden key-file extensions, and
  `${ONX_SECRET_*}` placeholders.
- The initial-commit path scans every normalized Class-B byte sequence before any repository
  object is written; findings raise `SecretFileInGitForbiddenError` without exposing secret
  values. A scanner hit leaves no repository and no `main` worktree behind.

### P2-2.4 — Workflow wiring

- New `backend/app/modules/versioning/application/advanced_initialization.py`: Advanced create
  bootstraps the host lockfile, CAS ingest, repository, eager `main`, and the protected `main`
  metadata row. Re-running against an existing repository reuses the authoritative host lockfile
  and performs no re-ingest.
- `CreateServerHandler`: Advanced create is POSIX-only; installer-based Forge/NeoForge creation is
  rejected with `VALIDATION_ERROR`; other types run Advanced initialization after the panel writes
  the initial server files and create a protected `main` row. `MCSError` provisioning failures
  clean up the server directory and propagate as typed errors.
- `CreateBranchHandler` is Git-backed for repository servers: `head_commit_id` is rejected
  (branches start from `main`), ref+worktree creation precedes the DB row, and a DB failure rolls
  the Git branch back.
- `ArchiveBranchHandler` rejects `main`, removes the worktree via Git, then marks the DB row
  archived.
- New `DeleteBranchCommand`/`DeleteBranchHandler` plus `DELETE
  /api/v1/servers/{server_id}/versioning/branches/{name}` (`server:version:commit`). Deletion
  refuses `main`, protected branches, unmerged history, dirty worktrees, and locked worktrees.
- `GetServerBranchesQuery` is Git-authoritative for repository servers: Git refs overlay DB
  metadata, deterministic IDs are synthesized for Git-only refs, DB rows absent from Git are
  omitted, and `head_commit_id`/`worktree_path`/`worktree_locked` are read from Git at request
  time. The legacy DB-only shape is unchanged for D8 servers.
- `BranchResponse` gains additive optional `worktree_path` and `worktree_locked` fields.

## 2. Changed files and final hashes

Paths are relative to the worktree root. Hashes are SHA-256 of the current uncommitted content
(`/tmp/p2-2-batch4/post.txt`).

| File | Status | SHA-256 |
|---|---|---|
| `backend/app/api/v1/routers/versioning.py` | modified | `56074895fb588a0697b86859e920b0e1dd29017c0f7e165515e95eb778dd83ac` |
| `backend/app/api/v1/schemas/versioning.py` | modified | `b20eb3204c8ea92c01b0fd88ba93483321a2d4f52950641c28fb45c3e13e27a4` |
| `backend/app/core/exceptions.py` | modified | `758b78eac572d3a744853eb2ba93d7e443d44424fbda4430678e5c10fda98904` |
| `backend/app/core/host_state.py` | modified | `f96e3394ff8e37dc0f3888c0f51382d3e6d9edb2a132d2da2f357f3127f5a276` |
| `backend/app/modules/server/application/commands/create_server.py` | modified | `eefc3d58324f82eb032fcfd65a24288b8597622f4cc909249068a3b09ba60d47` |
| `backend/app/modules/versioning/application/__init__.py` | modified | `826ee2a6308de4a5a88958a336b53401b06ee135009565b4386d34697b5a203c` |
| `backend/app/modules/versioning/application/advanced_initialization.py` | new | `83b3d52708500aa42a84beaa66ba8d3c0381e08906640252be9f2508dee8590f` |
| `backend/app/modules/versioning/application/baseline_adoption.py` | modified | `f0c3392bc9fcf0c19856521c2eb77cafb7436dcd583c32068310fd0d78e979d0` |
| `backend/app/modules/versioning/application/commands/archive_branch.py` | modified | `04f9e213779de2cb4f7944309b79386fb3545429765c4d69b59b6de9809f77ff` |
| `backend/app/modules/versioning/application/commands/create_branch.py` | modified | `72385f9cf4e93749e1a67262ad23cab28fae689e8c82cdf32833e525cefd906a` |
| `backend/app/modules/versioning/application/commands/delete_branch.py` | new | `61f841ae257eaee809da430c2ef70e7e2625e7596af8ef26b5f59c5d9741d8d2` |
| `backend/app/modules/versioning/application/git_branch_adapter.py` | new | `e58bd590c2cbe18bd37344d23a09446720d64bfbb7009be627bfb87e66c68387` |
| `backend/app/modules/versioning/application/queries/get_server_branches.py` | modified | `b38e7c5e92b767f2eee90b2da292a9649b1952cb73ff26ebe8a089aedaa5d9b1` |
| `backend/app/modules/versioning/domain/repository.py` | modified | `7b1c573238ce6122ce6cc98b21d06bcd93ef6bba13367054c51f8f5ff29bad32` |
| `backend/app/modules/versioning/infrastructure/git_branches.py` | new | `9cf4c6db7b9d6ce0d91053a08d0314840165862b89e501796860a78293a80ecb` |
| `backend/app/modules/versioning/infrastructure/git_repository.py` | new | `18953c2eb80787a7eef37a4a11050fadb11b036e0cfb6b5076d041d16470762f` |
| `backend/app/modules/versioning/infrastructure/git_runner.py` | new | `aaeab7878909f7690533283e98bb2a977696c37d76ee32d21da9d5c5ad1012d6` |
| `backend/app/modules/versioning/infrastructure/repository.py` | modified | `e8dfc002dc32107c0d0f9fbd7919cf2d81f5adeabdaffb5e2a588c3985c05c63` |
| `backend/app/modules/versioning/infrastructure/secret_scanner.py` | new | `358658ab0f6ad1821d0e821d8e4ae56d69d066cdb5bb3aaf697fbf5dc9443943` |
| `backend/app/modules/versioning/infrastructure/server_tree_scanner.py` | modified | `39183bacba33578997a721a0fc4e042787995bc6c6d134157a0fbd12314709e5` |
| `backend/app/registration.py` | modified | `dbdadb004b4bd27f6a794ed6aa11d49f088e644cb0b5b03fd5f5c7b7a7b11b04` |
| `backend/tests/application/test_advanced_initialization.py` | new | `d3804ec453c48fadfacf27aeae97f861bd0eaca7802d871664dbaea472ac0225` |
| `backend/tests/application/test_git_branch_commands.py` | new | `726691ad613602ea46f3fe99434a93e4f0c5d2b54363cd9a9191e0c58bb1ce46` |
| `backend/tests/application/test_server_mode_creation.py` | modified | `59789bacf5d360062d239a1b9868ad41afc98f729472a97a8847111de80c32a5` |
| `backend/tests/core/test_host_state.py` | modified | `a7bb4f568de5245e48962ff2d009f74db937dbeb1b98309b04e3f440b4ffbdc1` |
| `backend/tests/core/test_route_contract.py` | modified | `1b3d84a53f77c7a4879d9a3d5e281b32971b0629ea2f1f677ad9d5c67e272c6f` |
| `backend/tests/infrastructure/test_git_branches.py` | new | `60b4ef8afd16d68984418d88de62ac302031d6f56aa9eca4ecb25578b25200e2` |
| `backend/tests/infrastructure/test_git_repository.py` | new | `c59c92782cdafd540a24739804bdded089ff0b652df22349656f0064563be48f` |
| `backend/tests/infrastructure/test_git_runner.py` | new | `a610be04bd04acab87440e65c9de21e4ff00e4c00281f07b696e662c71f88f8c` |
| `backend/tests/infrastructure/test_secret_scanner.py` | new | `6bc2fc223279aa8b693da49b6e5e007b8eab897f62fc9d5d332e4a66c6a6744d` |
| `backend/tests/infrastructure/test_server_tree_scanner.py` | modified | `473250c74400d278b991e71d52bf137dc9fb60a754c476e37da8545c4480d17a` |
| `contracts/permissions.yaml` | modified | `ad1b20a475972bebe0012c6635763a6b8f501b6246908d12fa63e246c43a7fd9` |

P2-2 diff from `4d25a9f`: 32 code/test/contract files, 4,413 insertions, 40 deletions (19
modified + 13 new). This report adds one more docs file.

## 3. Verification evidence

### 3.1 Targeted verification

| Batch | Command scope | Result |
|---|---|---|
| P2-2.1 | `pytest tests/infrastructure/test_git_runner.py` | **63 passed** |
| P2-2.3 | branch service + branch/baseline/mode regression | **8 new passed**; **143 passed** |
| P2-2.3.5 | `pytest tests/infrastructure/test_secret_scanner.py` + adoption hook | **28 passed** |
| P2-2.4 | new Advanced init + Git branch command tests | **9 passed** |
| P2-2.4 | branch/baseline/mode regression | **38 passed** |
| P2-2.4 | versioning/branch/flag API regression | **27 passed** |
| P2-2 final | combined P2-2 suite (Git runner/repo/branches/scanner, Advanced init, branch commands, mode, baseline, commit/promote, API, host state, tree scanner) | **299 passed** |

### 3.2 Final full verification

| Suite | Result |
|---|---|
| Full backend `pytest -q` | **PASS** — 4,352 passed, 6 skipped in 19:46 |
| `scripts/check-route-contract` | **PASS** — 156 live routes vs 156 contract entries |
| `scripts/check-ruff-baseline` | **PASS** — 486 violations across 21 rules, all at/below baseline |
| `scripts/check-db-revision` | **PASS** — schema revision `b1e2100000025` compatible |
| `scripts/check-version-propagation` | **PASS** |
| `scripts/check-ps1-bom` | **PASS** |
| `scripts/check-stray-db` | **PASS** — no stray SQLite files |
| `git diff --check` | **PASS** |
| Pyright on P2-2 modules | New modules clean; remaining errors are pre-existing (`docker_provider` unbound in `create_server.py`, `res` unbound in legacy branch handlers, SQLAlchemy `Column[...]` false positives in the router/repository) |

No frontend file changed in P2-2; frontend suites are not claimed for this slice.

## 4. Design decisions and dispositions

| Decision | Disposition |
|---|---|
| Repository location | Bare `<host_state>/repos/<server_id>/repo.git` with sibling `gitconfig`; never inside the server tree. |
| Initial commit content | Class-B + `onx-jars.lock.json` + panel `.gitattributes` only; jar bytes/C/E excluded. |
| Git config isolation | Panel-owned global config containing identity + `safe.directory`; system config disabled. |
| Branch name contract | Git validation plus conservative ASCII path segments, length bounds, no `.lock`, no traversal. |
| Archive vs delete | Archive removes the worktree and keeps history; delete requires full merge into `main` and a clean unlocked worktree. |
| `main` protection | No archive, delete, or Git-backed branch creation with that name; DB row created protected at Advanced create. |
| Legacy compatibility | Git behavior activates only when `repo.git` exists; D8 DB-only Advanced servers keep legacy behavior. |
| Branch list authority | Git refs are authoritative; DB is metadata overlay. |
| `head_commit_id` | Git SHA is overlaid at read time because `server_branches.head_commit_id` is `String(36)` and cannot persist a 40-character SHA. |
| Advanced create gates | POSIX only; installer-based Forge/NeoForge rejected until post-provisioning Git init exists. |
| Scanner timing | Repo initialization only in this slice; Save & Commit/merge/export enforcement remains P2-4/P2-3. |

## 5. Residuals, risks, and non-claims

- **Installer-based Forge/NeoForge:** Advanced create is intentionally rejected; the installer
  rewrites server files after provisioning, so Git initialization must run after that flow exists.
- **Windows:** native Git operations raise `GitUnsupportedPlatformError`; Advanced create also
  rejects non-POSIX hosts. Windows support/CI remains pending.
- **Failed-create host-state:** a failure after repository creation can leave an orphan
  `<host_state>/repos/<server_id>` / lockfile. Server-directory cleanup runs, but host-state GC is
  a P2-5 stale-cleanup concern; automatic deletion was avoided to protect existing repositories.
- **Archive DB failure:** if the DB save fails after the worktree is removed, Git keeps the ref and
  the row can appear active without a worktree until the next archive retry.
- **Branch UI:** the branch delete route has no dedicated frontend control in this slice; branch
  Files/Save & Commit UI is P2-4.
- **Scanner coverage:** only repository initialization is wired. Save & Commit, merge, conversion,
  push, and export enforcement remain pending; Advanced write workflows must not be enabled for
  end users before those paths are covered.
- **Repo lease/fencing, crash recovery, stale cleanup, disk-full:** P2-5.
- **`server_branches.head_commit_id`:** schema remains `String(36)`; no migration in P2-2.
- **No claims:** P2 is not complete; D-3 is not passed; no CI run exists; nothing was pushed,
  merged, amended, reset, stashed, or force-updated; no branch or worktree was deleted.

## 6. Proposed STATE / current-state delta (not applied)

Per the owner's instruction, `docs/current-state.md`, `docs/decisions/*`, `docs/roadmap/*`,
`.ai/STATE.json`, and the owner's main worktree were not modified.

- `docs/current-state.md`: change the P2 line to
  “IN PROGRESS — P2a P2-1+P2-2 IMPLEMENTED_PENDING_FIRST_CI_RUN (2026-11-13)”, and append:
  “P2-2 (native external Git repository, eager `main` + initial commit, Git-backed branch
  create/archive/delete/list, per-branch worktrees, scanner at repo init, Advanced create wiring)
  implemented uncommitted on `slice/p2-b4-core-substrate` based on `4d25a9f`; targeted/final local
  verification passed; six gates PASS. Advanced mode remains OFF by default; installer-based
  Forge/NeoForge Advanced create, Advanced import, Windows, Save & Commit scanner coverage, and
  D-3 remain pending. See `docs/reports/P2-2-IMPLEMENTATION-2026-11-13.md`.”
- `.ai/STATE.json` (local-only, git-excluded): record P2-2 status, branch, base, the 31-file
  set, final test counts, gate results, and `advanced_mode_enabled=false`. Do not cite
  `.ai/STATE.json` as branch evidence.
