# SPEC-2026-11-09-SIMPLE-ADVANCED-MODES-02

Status: design specification v8.2 (owner-confirmed v5/v6/v7/v8 plus 2026-11-10 owner decisions
OD-1..OD-9), CLOSED and READY FOR BUILD for P1-P5. P6 (D9) remains BLOCKED on a D2 (governance)
decision record plus a superseding ADR before P6. Governance paperwork is waived for P1-P5; it returns
for P6/D9.

Evidence tags: FACT (verified by command this session, cite file:line), ASSUMPTION (inferred, not
verified), UNKNOWN (missing), CONFLICT (two sources disagree), OWNER-STATED (owner decision),
PROTOTYPE-REPORT (external prototype result quoted from the 2026-11-10 prototype report; not
reproducible in this repository; never restated as FACT).

## Revision log v7 -> v8 (owner decisions 2026-11-09)

- OWNER-STATED (D-A/D-B): replaced the v7 tracked-vs-ignored model with five classes (A code,
  B user-edited config, C live-owned state, D panel-owned settings, E never tracked) and an
  explicit allow-list. Code jars move to a sha256 CAS with a Git lockfile; class C syncs to the
  dedicated `live-state` branch; main never receives automatic commits.
- OWNER-STATED (D-C/D-D/D-E): server.properties is tracked minus class-D keys with normalization
  at Save & Commit; plugin config defaults to class B with snapshot comparison at restart; config
  merges are key-level for yml/json/properties/toml, unknown formats live-win, parse failure
  leaves live untouched, and no conflict markers are written to server directories.
- OWNER-STATED (D-F): runs use a clean export of a pinned Git sha with no `.git`; the editing
  worktree is never mounted; `materialization_id` is deleted; run identity is Git sha plus optional
  Data Template.
- OWNER-STATED (D-G): Git never runs against a container-writable directory; nested `.git`,
  filters, and symlinks are stripped; hooks/fsmonitor disabled per command; shell-free argv; refs
  validated; private minimal Git config. Container uid remains UNKNOWN/recon.
- OWNER-STATED (D-H): COW/reflink is not required; probe a real reflink attempt, use reflink on
  success or plain copy plus free-space check; Advanced is not disabled on ext4; Windows remains
  Simple-only.
- OWNER-STATED (D-I/D-J): live refresh is atomic in the stated 7-step order; one DB-lease-backed
  write lock per repository covers add/commit/merge/fetch/push/gc/worktree add-remove; webhooks
  only enqueue.
- OWNER-STATED (D-K): GitHub ships last in Advanced (P5); poll via fetch first; webhook optional;
  HMAC-SHA256 raw body; dedupe by X-GitHub-Delivery with operator redelivery; reject
  non-fast-forward main; add `.gitattributes` and core.filemode; jars never plain GitHub blobs;
  Unknown J narrows to credential choice.
- OWNER-STATED (D-L): a runtime publishes a set of host ports; duplicate-port checks scan every
  published port atomically; in-container server-port/rcon are fixed and panel-owned.
- OWNER-STATED (D-M): phases are recut by user-visible behavior in owner order; Advanced is hidden
  until repo + clean export; live refresh ships only with stop-check + rollback. Phases are now P1
  mode/guard, P2 repo/clean export/Save & Commit/branch Files, P3 merge/live-state/restart refresh,
  P4 branch/test runs/ports/Data Templates, P5 GitHub, P6 Docker-only, P7 backups.
- Added "External review disposition" and "Prototype before build"; external claims are tagged
  ASSUMPTION (external, unverified). No existing FACT citation was changed.

## Revision log v8 -> v8.1 (prototype report merge, 2026-11-10)

- PROTOTYPE-REPORT: merged prototype verification report as normative rules tagged PROTOTYPE-REPORT.
- Allow-list v1 embedded with corrected `$` regex anchors.
- OWNER-STATED (OD-1): `onx-jars.lock.json` kept as the class-A lockfile pointer (evaluation step 2); kept distinct from class-B user config.
- OWNER-STATED (OD-2): plugin binary data (`*.db`, `*.sqlite`, `*.dat` and similar under `plugins/`) is class E; excluded from Git and `live-state`, covered by the existing backup system, and included in optional Data Templates.
- FACT / OWNER-STATED (OD-3): `eula.txt` is generated at export time (class-D-like), not tracked. `write_eula` (`jar_service.py:987-1010`) writes `eula=true`, called from `create_server.py:187`; test deployments write it at `config_writer.py:87-89`; backups already list it in `CONFIG_FILES` at `backup_orchestrator.py:27-34`. The P2 clean export must write it into the exported root.
- OWNER-STATED (OD-4): built-in always-C subtree patterns in Allow-list v1 replace the small manual override list; contents remain an implementation choice; dynamic C reclassification is recorded in a per-server DB registry (not inside the server tree).
- OWNER-STATED (OD-5): introduced PROTOTYPE-REPORT evidence tag; D-B / prototype 3 (real Paper boot, allow-list derivation, 120 MB GitHub push) stay OPEN; ext4 and ZFS reflink behavior stay UNVERIFIED. Embedded report rules are normative text tagged PROTOTYPE-REPORT, never FACT.
- OWNER-STATED (OD-6): `mods/*.jar` and mod configs are out of scope (Lane E); they fall to class E via catch-all. Supporting mod loaders in Advanced mode later will require promoting them to class A/B before enabling Advanced mode so clean export does not boot without mods. Optional modpack support for Simple servers is recorded as a separate Lane E idea.
- OWNER-STATED (OD-7): header updated to closed and ready for build for P1-P5; P6 (D9) remains blocked on a D2 governance decision record plus a superseding ADR.
- No existing FACT citation was changed and no owner decision was altered.

## Revision log v8.1 -> v8.2 (owner decisions 2026-11-10)

- OWNER-STATED (NOD-1/OD-9): `.gitattributes` is panel-generated at commit time (class-D-like), written into the repo by the panel with the D-K eol/filemode rules; it is never taken from the server directory. A `.gitattributes` found in the server tree is class E (catch-all) and is removed by the D-G sanitizer. It is not added to any allow-list regex. `CLASS_B_CONFIG_ALLOWLIST_REGEX` no longer contains `onx-jars.lock.json`; evaluation step 2 classifies it as the class-A lockfile.
- OWNER-STATED (NOD-2): `*.dat` under `plugins/` stays class E (OD-2); text player data is class C and `playerdata` joins the class-C directory list.
- OWNER-STATED (NOD-3): a `.jar` anywhere except root `*.jar` and `plugins/*.jar` is class E; `.class`, `.so`, `.dll`, `.nbt` are class E. Because E is evaluated before C, these are E even inside class-C subtrees.
- OWNER-STATED (NOD-4): `server-icon.png` is class B and is tracked only below the oversized-binary threshold; the threshold remains Unknown I.
- OWNER-STATED (NOD-5): `plugins/*/lib/*.jar` and other nested jars are class E (NOD-3); nested config directories under `config/` are class B.
- OWNER-STATED (NOD-6): `.csv` is class E; `csv` is removed from the class-C file-name alternative and added to the class-E extension list. Any unknown extension is class E (catch-all).
- OWNER-STATED (NOD-7): `server.properties` normalization discards all comments and keeps only sorted `key=value` lines. Real-boot validation remains OPEN.
- No other owner decision, phase order, or FACT citation changed.

## Revision log v6 -> v7 (owner decisions 2026-11-09)

- OWNER-STATED: Local providers (LocalLinux/LocalWindows, tmux) are removed; Docker is the only
  runtime and no server runs without Docker. Windows-hosted servers also run as Docker containers.
  D9 stays staged last (historical: now P6 under v8 D-M); Local-provider unit tests are temporary
  and are deleted with the providers in P6.
- OWNER-STATED: Unknown B resolved. Runtime-generated changes in a branch run/test are deleted
  automatically. The user may explicitly save data as a reusable "Data Template" (stored
  separately from code; metadata in the database; copied with reflink where possible) and start
  any branch/test from it. Exact storage layout is an implementation choice.
- OWNER-STATED: Unknown K resolved. A branch run uses the last committed state only; the UI warns
  about uncommitted changes that are not included.
- OWNER-STATED: Main -> live. Merging into `main` is allowed at any time and does not touch the
  running live container. When the live container is restarted (or stopped and started again),
  tracked code files are replaced from the latest `main`, and live data files are kept. SUPERSEDED
  in mechanism by v8 D-A/D-I: replace only class A/B, never class C/E, and inject class D.
- OWNER-STATED: Unknown E resolved. The branch Files view shows and edits the branch worktree;
  excluded data (`world*`, logs, local DBs) is not part of the worktree. SUPERSEDED in mechanism by
  v8 D-A/D-B: the worktree contains only allow-listed class-A/B files.
- OWNER-STATED: Unknown M direction. Superseded by v8 D-A/D-B/D-C/D-D/D-E: file classes, explicit
  allow-list, `live-state` branch, and key-level config merge replace the v7 tracked-vs-excluded
  proposal and the proposed starting exclusions.
- OWNER-STATED: Unknown N resolved. Promote is removed; "Merge into `main` + live restart refresh"
  replaces it. The safety logic moves over: the live container must be confirmed stopped before its
  files are updated (fail closed on missing/inconclusive confirmation), with an atomic switch and
  rollback. Actual code/route/permission removal is placed in P3 by v8 D-M; affected components
  are listed below.
- OWNER-STATED: Unknown O deferred. Merging into any branch, including `main`, is warning-only (D6).
  The optional strict policy is defined later together with the testing system. The testing system
  evolves separately (stages, UI, later GitHub CI/CD or Discord triggers, multiple containers in
  parallel, stress and chaos-style tests). Tests never block a merge by default.
- OWNER-STATED: Unknown P. Windows users use Simple only; Linux VPS hosts use Advanced. Historical
  wording here required a reflink-capable filesystem. SUPERSEDED by v8 D-H: Advanced is allowed on
  ext4; reflink is optional and uses a real probe with plain-copy fallback. Lane E future note: an
  intermediate mode or a fourth mode for multi-node.
- OWNER-STATED: Conversion (D7). Advanced -> Simple copies `main` into a brand-new Simple server;
  the result has no Git or GitHub relation. This also serves developers who prefer working by hand.
  Simple -> Advanced stays as written; Unknown D remains UNKNOWN unless the owner decides.
- OWNER-STATED: Remove Unknowns B, E, K, M (replaced by resolved pointers), mark O deferred, and
  keep D, G, I, J, L open. Unknown L is PROPOSED (not decided): uncommitted changes stay in each
  branch's own worktree on switch/restart; a merge into a target with uncommitted changes is
  refused until Save & Commit or discard.
- OWNER-STATED: Phase order. CI/Windows backend fixes first, then P1, then P2.

## Revision log v5 -> v6 (owner confirmation 2026-11-09)

- OWNER-STATED: v5 is the current ground truth. The hidden auto-commit per edit (v4 and the earlier
  handoff text) is dropped; commits happen only through the explicit "Save & Commit" action.
  Governance paperwork is set aside for now by the owner.
- Added Unknowns M, N, O, P and the native-Git safety requirements (provisional, S1-S5). Added the
  re-basing note to the P2 Files list.
- No owner-stated decision (D1-D12, Unknowns A/C/F/H) was changed.

## Revision log v4 -> v5

Historical record only. D5-v5's tracked-vs-excluded model, `.gitignore`, and COW driver are
superseded by v8 D-A/D-B/D-H; D2-v5/D4-v5/D10-v5 are amended by v8 D-E/D-F/D-I; D12-v5's GitHub
stage is now P5 (v8 D-M).

- Replaced v4 D2 (database-backed virtual filesystem, manifest trees, hidden commit per edit) with
  D2-v5: Advanced mode uses real Native Git (`git` / `git worktree`) as the versioning engine.
  UI branches are real Git branches; `server_branches` keeps only operational metadata, not a
  custom replica of Git trees or manifests. Edits change the branch working tree and commits are
  created only by the explicit "Save & Commit" action (or GitHub push/pull).
- Replaced v4 D4 with D4-v5: `main` is strictly protected saved state. The Files page/API must not
  allow direct live-root edits on `main`; it is read-only or forces creating/switching to a
  working branch. The production container runs from a copy of `main`, refreshes tracked
  code/configs from `main` on restart, and preserves live world/runtime data.
- Replaced v4 D5 with D5-v5: explicit Git-tracked vs excluded data boundary, including plugin jars
  through standard Git or Git LFS/SHA256 CAS pointer lockfiles, and a mandatory `.gitignore` for
  `world*`, runtime logs, local SQLite/H2 databases, and dynamic player data. Excluded data is
  managed by the Btrfs/ZFS COW driver (`cp --reflink=always`) and the two-tier backup system.
- Replaced v4 D10 (list alternatives, recommend nothing) with D10-v5: commit-from-worktree is
  native `git add` + `git commit`; branch merges use native `git merge` with real three-way merge
  and conflict detection, replacing the manifest-only `MergeCommitsCommand` limitation.
- Promoted v4 D12 GitHub integration from Lane E to core Advanced architecture (D12-v5):
  bi-directional private-repository branch/commit sync via webhook/fetch/push so developers can use
  GitHub alongside the UI "Save & Commit" flow.
- Resolved Unknowns A, C, F, and H (see OPEN QUESTIONS > Resolved by owner) and removed them from
  the unresolved list.
- Removed the v4 P2 hidden-commit behaviour and the v4 D10 alternatives section. P2 replaces the
  custom versioning engine with real Git; P3 adds private GitHub repository sync.
- P1 now records the owner-resolved Simple guard: FastAPI router-level dependency plus an
  application-layer command check raising `ServerModeVersioningDisabledError` (HTTP 409).
- Kept D1, D3, D6, D7, D8, D9, and D11, and kept the provisional items with updated labels.
- Corrected citations found stale during re-verification: `ServerModel` spans
  `models.py:20-78` (not 20-76); `ServerUpdateRequest` `extra="ignore"` is at
  `schemas/server.py:44-45` (not 44-46); the materialization write call is
  `create_materialization.py:173-178` (not 173-174); `tree_writer` plain-file behaviour is
  `tree_writer.py:19-23` (not line 21 alone); provider registration is
  `providers/__init__.py:20-22` (not 20-21).
- Recorded the one remaining CONFLICT: D9 vs ADR-0015. The v4 CONFLICTs D1-vs-global-routes,
  D4-vs-Files-live-root, and D2-vs-Unknown-H are resolved by D2-v5/D4-v5 and Unknown F/H; the
  current code still shows the old behaviour until the phases land.

## Goal

### Owner-stated (v5/v7/v8 ground truth)

The v7 decisions in the revision log above remain owner-stated unless contradicted below. The v8
decisions in the next section supersede where they conflict.

- Simple mode (D1): one general container holds the whole server; plain files; edit then restart;
  versioning does not exist for Simple. The backend must not know about versioning for a Simple
  server: versioning routes, commands, and queries must be unreachable server-side, not only
  hidden in the UI. Owner's reason: leaving it reachable creates many vulnerabilities.
- Advanced mode (D2-v5): one general container holds the whole server. Advanced mode uses real
  Native Git (`git` / `git worktree`) as the versioning engine. Branches in the UI are real Git
  branches, synced 1:1 with a connected Private GitHub Repository when configured, or backed by a
  local native Git repository on the server. The database `server_branches` stores only
  operational metadata tied to each branch (assigned host-port set, runtime status, per-branch
  console, and per-branch activity/change-log section), not a custom replica of Git trees or
  manifests. Editing files or settings of a branch modifies that branch's working tree as
  uncommitted working changes. Commits are not created on every keystroke or file-write; a commit
  happens explicitly when the user clicks "Save & Commit" in the UI, or when commits are
  pushed/pulled from GitHub.
  OWNER-STATED (v8 D-A/D-F): Git tracks class-A code lockfiles and class-B user-edited config;
  runs use a clean export of a pinned Git sha, never the editing worktree.
- D3: Running a branch (or a test) starts a NEW isolated container from the Git state. Each branch
  has its own console and its own section of the change/activity log in the database. Each branch
  container publishes its own set of host ports when created; the owner may choose them, and
  duplicate ports must be prevented (v8 D-L). The user can switch between branches; all pages
  follow the selected branch.
  OWNER-STATED (v8 D-F): every branch/test run uses a clean export of a pinned Git sha with no
  `.git`; the editing worktree is never mounted into a container.
- D4-v5/v8: `main` is strictly protected saved state. The Files page/API must NOT allow direct
  live-root edits on `main` (read-only view for `main` in Files, or forces creating/switching to a
  working branch to edit). The player-facing production container runs from a clean export of the
  pinned `main` sha (D-F). On restart, the atomic refresh replaces class-A/B files from `main`,
  never overwrites class-C/E data, and injects class-D panel settings (D-A/D-I).
- D5-v5: SUPERSEDED by v8 D-A/D-B (five file classes and an explicit allow-list). The old
  tracked-vs-ignored model, mandatory `.gitignore`, and proposed exclusion list are not the
  mechanism. Retained in spirit by v8: a branch starts from code only; a run without a Data
  Template generates a fresh world from the seed, including tests; Data Templates are optional;
  plugin config is class B/C and plugin jars are class A.
- D6: Merging into `main`: default behaviour is a WARNING only; the merge is still allowed; this
  is a configurable setting. The stricter PASSED-test-plus-identical-manifest gate is only an
  optional configurable policy value, not the default.
  OWNER-STATED (v7): warning-only applies to merges into any branch, including `main`; tests never
  block a merge by default. The optional strict policy is deferred (Unknown O).
- D7: Mode conversion is wanted later and should be easy, not in P1. Advanced -> Simple: copy
  `main` into a brand-new Simple server; the old server may be deleted. Simple -> Advanced: the
  Simple server's files become `main`. In P1 there is no in-place flip.
  OWNER-STATED (v7): the Advanced -> Simple result has no Git or GitHub relation and also serves
  developers who prefer working by hand. Simple -> Advanced stays as written; Unknown D remains
  UNKNOWN unless the owner decides.
- D8: All existing servers are test/dummy data and the project has no users; the owner deletes
  them. Therefore there is no migration of existing servers and no deriving mode from existing
  commits.
- D9: All servers are containerized, so Local providers (LocalLinux/LocalWindows, tmux) are
  eventually removed. This conflicts with ADR-0015 and needs a D2 (governance) decision record plus
  a superseding ADR. Staged in P6 (Docker-only) after Advanced core P2-P5; P7 backups follows.
  OWNER-STATED (v7/v8 D-M): Local providers are removed; Docker is the only runtime and no server
  runs without Docker. Windows-hosted servers run as Docker containers too. Local-provider unit
  tests are temporary and are deleted with the providers in P6.
- D10-v5: Because Advanced mode uses real Git and `git worktree`, commit-from-worktree is native
  `git add` + `git commit` triggered by "Save & Commit". Merging branches uses native `git merge`,
  which provides real three-way merge and conflict detection, replacing the custom manifest-only
  `MergeCommitsCommand` limitation.
  OWNER-STATED (v8 D-E): native `git merge` is allowed only for code-class files in the repo;
  config merges are key-level for yml/json/properties/toml, and results are exported only after
  validation.
- D11: The testing system is being reworked separately by the owner: stages (server boots; a bot
  can join from the local network; a bot can join from the external network; an unreachable
  external network gives a warning and does not block; each stage has UI). Out of scope here;
  mention only the interface this spec needs.
- D12-v5: Private GitHub Repository synchronization is promoted from Lane E to core Advanced
  architecture. Bi-directional branch/commit sync via webhook/fetch/push is part of the Advanced
  design, so developers can work from GitHub alongside admins using the UI "Save & Commit" flow.
  OWNER-STATED (v8 D-K/D-M): GitHub sync ships last in Advanced (P5), after repo/merge/live
  refresh/run work; poll via `git fetch` first; webhook is optional.

### Owner-stated v8 (2026-11-09) - file ownership, runs, refresh, GitHub, ports, phases

- OWNER-STATED (2026-11-09, D-A): File ownership is five classes:
  - OWNER-STATED (D-A, class A code): server jar and plugin jars. Stored OUTSIDE Git in a
    content-addressed store keyed by sha256; Git tracks only a lockfile with path, sha256, size,
    and source; the tracked pointer is `onx-jars.lock.json` (class-A lockfile, evaluation step 2;
    it is not a class-B user config). Replaced from `main` on live restart.
  - OWNER-STATED (D-A, class B user-edited config): for example `plugins/<name>/` configs the
    plugin does not rewrite and root `server-icon.png`. In Git; replaced from `main` on restart.
    `server-icon.png` is tracked only below the oversized-binary threshold (Unknown I).
  - OWNER-STATED (D-A, class C live-owned state): `ops.json`, `whitelist.json`, `banned-*.json`
    (Allow-list v1 regex enumerates `banned-players.json` and `banned-ips.json` until prototype 3
    validates the list), `usercache.json`, plugin-rewritten configs/data. Text player data under
    `plugins/*/playerdata/` is class C. `*.dat` under `plugins/` remains class E (OD-2), so binary
    player data is not synced to `live-state`; it is covered by backup and Data Templates. The live
    server owns it. A copy is synced automatically into a dedicated non-main branch `live-state`.
    Restart NEVER overwrites it. `main` never receives automatic commits; Save & Commit remains the
    only commit path to `main`/branches. A developer must merge `live-state` into their branch before
    editing class-C files.
  - OWNER-STATED (D-A, class D panel-owned settings): `server-port`, `rcon.port`, `rcon.password`,
    `query.port`, `enable-rcon`. Outside the repo; injected by the panel at run/export time; never
    tracked.
  - OWNER-STATED (D-A, class E never tracked): `world*`/custom level-name, logs, cache, libraries,
    crash-reports, `.paper-remapped`, DBs, map tiles, and plugin binary data (`*.db`, `*.sqlite`,
    `*.dat` and similar under `plugins/`). They are excluded from Git and live-state, covered by the
    existing backup system, and included in optional Data Templates. Also class E: a `.jar` anywhere
    except root `*.jar` and `plugins/*.jar` (including `plugins/*/lib/*.jar`), `.class`, `.so`,
    `.dll`, `.nbt`, `.csv`, and a `.gitattributes` found in the server tree.
- OWNER-STATED (2026-11-09, D-B): classification is an EXPLICIT ALLOW-LIST: ignore everything by
  default; track only what is explicitly allowed. Allow-list v1 is the normative list in "Allow-list
  v1 (normative)" (PROTOTYPE-REPORT). It was NOT derived from a real Paper boot; deriving and
  validating it against a real booted Paper server remains OPEN (prototype 3). The v7 proposed
  exclusion list is removed as the mechanism.
- OWNER-STATED (2026-11-09, D-C): track `server.properties` minus class-D keys; the panel injects
  those keys. Add NORMALIZATION at Save & Commit: strip the `#Minecraft server properties` header,
  strip the `Properties.store()` timestamp line matching
  `^#\s*(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+\S+\s+\d{4}\s*$`,
  normalize CRLF to LF, remove the five class-D keys (`server-port`, `rcon.port`, `rcon.password`,
  `query.port`, `enable-rcon`), and sort remaining `key=value` lines lexicographically. All comments
  are discarded by normalization; only sorted `key=value` lines are kept (OWNER-STATED NOD-7, 2026-11-10).
  This normalization is PROTOTYPE-REPORT (not yet validated against a real Paper boot).
- OWNER-STATED (2026-11-09, D-D): `plugins/<name>/` defaults to class B. At restart, compare the
  live file to the last synced snapshot; if it differs, treat it as class C (do not overwrite,
  show a warning). The default override list is the built-in always-C path patterns in "Allow-list v1
  (normative)"; its contents remain an implementation choice. Dynamic reclassification is recorded
  in a per-server DB registry (`dynamic-class-c`, not in the server tree; OD-4). Misclassification risk is covered by the P3
  backup-of-replaced-files and rollback.
- OWNER-STATED (2026-11-09, D-E): config merge is KEY-LEVEL for yml/json/properties/toml, never a
  textual `git merge` on live files. Unknown formats: live wins plus warning; unknown format keeps the
  live bytes and emits a structured warning. If parse fails: the live file stays untouched; parse
  failure on either side leaves the live file byte-identical. NEVER write conflict markers into a server
  directory. Save & Commit rejects config files containing conflict markers or failing to parse: the
  pre-commit validator rejects `^(?:<<<<<<<|=======|>>>>>>>)` and per-format parse failures
  (`yaml.safe_load`, `json.loads`, `tomllib.loads`, properties parser). Branch-to-branch merge of
  code-class files may use native `git merge` in the repo, but results are exported only after
  validation.
- OWNER-STATED (2026-11-09, D-F): running (live, branch, test) uses a CLEAN EXPORT of a pinned Git
  sha (`git archive` or equivalent) with NO `.git` entry, as the only container root. The export is
  `git archive --format=tar <sha>` streamed into `tarfile`, link members stripped, path traversal
  rejected, and the result contains zero `.git` entries. The editing worktree is NEVER mounted into a
  container. Delete `materialization_id` as a concept: the single run identity is the Git sha plus an
  optional Data Template id. Update Runtime, EvidenceBundle, test_runner, and promote consumers
  explicitly; do not retire old machinery by omission. A run is code sha + optional Data Template;
  without a template it is a fresh world from the seed (tests too). Template data overlays only class-E
  paths.
- OWNER-STATED (2026-11-09, D-G): Git is never run against a directory the container can write.
  Keep the Git directory outside the server tree. Hardened invocation contract: shell-free argv;
  per-command overrides `-c core.hooksPath=/dev/null -c core.fsmonitor=false -c protocol.file.allow=never -c core.symlinks=false`
  (the Windows `NUL` variant of the hooks path is UNVERIFIED); isolated environment
  `GIT_CONFIG_GLOBAL=<isolated file>`, `GIT_CONFIG_NOSYSTEM=1`, `GIT_TERMINAL_PROMPT=0`; leading-dash
  guard plus `git check-ref-format --branch <ref>`; nested `.git` dirs and `.git` pointer files and
  symlinks removed before `git add`; a `.gitattributes` found in the server tree is class E (catch-all)
  and is removed before `git add`; `.gitattributes` driver lines matching
  `(?:^|\s)(-?(?:filter|diff|merge)\s*=)` scrubbed in place on the panel-generated file. The panel
  generates `.gitattributes` at commit time (class-D-like) with the D-K eol/filemode rules; it is never
  taken from the server directory. Use a private minimal Git config with
  `safe.directory` for the one repo path only. Container user/uid is UNKNOWN: recon DockerProvider
  `--user`. ONX uses eclipse-temurin with its own launch, not the itzg image, so itzg-specific
  points do not apply.
- OWNER-STATED (2026-11-09, D-H): COW is NOT required. Probe with a real reflink attempt on the
  exact source/destination directories. If it succeeds, use reflink; otherwise use plain copy with
  a free-space check. After a failed reflink attempt, delete the partially created destination before
  fallback (`shutil.copytree` otherwise raises `FileExistsError`); before fallback, compute source
  tree size and require `shutil.disk_usage(dst.parent).free >= required`, raising
  `InsufficientStorageError`. ext4 and ZFS reflink behavior remain UNVERIFIED (the report covers
  tmpfs/overlay/xfs only). Advanced is NOT disabled on ext4. Remove the "HTTP 412, no fallback" rule for
  Advanced. The current `StorageCowUnavailableError` behavior is a FACT that must change in the
  phase that implements this. Windows remains Simple-only.
- OWNER-STATED (2026-11-09, D-I): atomic live refresh happens only after the container is
  confirmed stopped (fail closed). Stage the new class-A/B tree in a sibling directory, back up the
  files to be replaced for rollback, then switch via rename/symlink flip. Order: (1) confirm
  stopped, (2) sync the class-C copy into `live-state`, (3) stage, (4) back up, (5) switch,
  (6) start, (7) rollback on failure. Merge into `main` never touches the running live container.
- OWNER-STATED (2026-11-09, D-J): one write lock per repository covers add/commit/merge/fetch/
  push/gc/worktree add-remove. Reuse the existing DB lease pattern (`server_admission_lease`),
  not an in-process lock. Webhook handlers only enqueue. `git worktree lock` any worktree still
  referenced; gc only under the lock.
- OWNER-STATED (2026-11-09, D-K): GitHub is the last stage of Advanced (P5), after core works.
  Poll via `git fetch` FIRST; webhook is optional because the server may sit behind NAT. Webhook:
  verify HMAC-SHA256 on the raw body, dedupe by `X-GitHub-Delivery` but allow operator redelivery.
  Reject non-fast-forward updates to `main`. The panel generates `.gitattributes` at commit time
  (class-D-like; `* text=auto eol=lf` for text configs, `-text` for jars) and sets `core.filemode true`;
  it is never taken from the server directory. Jars never go to GitHub as plain blobs (see
  D-A). Unknown J narrows to credential choice (App vs fine-grained token vs deploy key); Unknown I
  is resolved by D-A.
- OWNER-STATED (2026-11-09, D-L): a runtime publishes a SET of host ports (game, rcon, query,
  plugin ports). Inside the container, `server-port`/rcon are fixed and panel-owned (class D).
  Duplicate-port checks scan every published port atomically.
- OWNER-STATED (2026-11-09, D-M): phases are recut by user-visible behavior, keeping owner order
  (CI/Windows fixes first, outside this spec; then P1, then P2). Advanced is not shown in the UI
  until the repo + clean export work in P2. Live refresh ships ONLY with the stop-check and
  rollback in P3. Each phase is independently shippable and states what the user sees. P2 is repo
  + clean export + Save & Commit + branch-aware Files; P3 is merge + live-state sync + restart
  refresh with rollback; P4 is branch/test runs + ports + Data Templates; P5 is GitHub; P6 is
  Docker-only; P7 is backups.

### Allow-list v1 (normative) - D-B/D-D

- PROTOTYPE-REPORT (D-B/D-D): Evaluation order (first match wins):
  1. **Dynamic Class-C overrides (`D-D`)**: Any path recorded in the per-server DB registry `dynamic-class-c` (from Snapshot Comparison; table schema/shape is an implementation choice per OD-4) -> **Class C**.
  2. **Class-A lockfile pointer (`OD-1`)**: Matching `^onx-jars\.lock\.json$` -> **Class A lockfile** (tracked in Git; points to CAS blobs).
  3. **Class E Hard Denylist**: Matching `CLASS_E_DENYLIST_REGEX` -> **Class E** (never tracked in Git or CAS). Evaluated before Class A/B/C so `cache/*.jar`, `libraries/**/*.jar`, nested jars outside root/`plugins/*.jar`, binary extensions, `.csv`, and plugin binary data are never misclassified.
  4. **Class A Executable Jars**: Matching `CLASS_A_JAR_REGEX` -> **Class A** (stored in sha256 CAS, referenced by lockfile).
  5. **Class C Live-Owned State**: Matching `CLASS_C_LIVE_STATE_REGEX` -> **Class C** (synced to `live-state` branch; never overwritten by `main`).
  6. **Class B User-Edited Config Allow-List**: Matching `CLASS_B_CONFIG_ALLOWLIST_REGEX` -> **Class B** (tracked on `main` and feature branches).
  7. **Default Catch-All**: Any unmatched path -> **Class E** (untracked).

- PROTOTYPE-REPORT (D-B): Concrete regex and key definitions:
```python
CLASS_E_DENYLIST_REGEX = re.compile(
    r"^(?:"
    r"world(?:_nether|_the_end)?(?:/.*|$)"
    r"|logs(?:/.*|$)|crash-reports(?:/.*|$)|cache(?:/.*|$)|libraries(?:/.*|$)|versions(?:/.*|$)"
    r"|\.paper-remapped(?:/.*|$)|\.mixin\.out(?:/.*|$)"
    r"|version_history\.json$|patched_[^/]+\.jar$"
    r"|(?!plugins/[^/]+\.jar$).*/[^/]+\.jar$"
    r"|.*\.(?:db|sqlite|sqlite3|mv\.db|trace\.db|h2\.db|lock|lck|pid|log|gz|tar|zip|mca|mcr|dat|dat_old|class|so|dll|nbt|csv)$"
    r")"
)
CLASS_A_JAR_REGEX = re.compile(r"^(?:[^/]+\.jar|plugins/[^/]+\.jar)$")
CLASS_C_LIVE_STATE_REGEX = re.compile(
    r"^(?:"
    r"ops\.json$|whitelist\.json$|banned-players\.json$|banned-ips\.json$|usercache\.json$"
    r"|plugins/[^/]+/(?:userdata|data|players|playerdata|storage|cache)/.*$"
    r"|plugins/[^/]+/(?:data|players|userdata|database|storage)\.(?:yml|yaml|json|txt)$"
    r")"
)
CLASS_B_CONFIG_ALLOWLIST_REGEX = re.compile(
    r"^(?:"
    r"server\.properties|server-icon\.png"
    r"|bukkit\.yml|spigot\.yml|commands\.yml|help\.yml|permissions\.yml|pufferfish\.yml|purpur\.yml"
    r"|config/(?:[^/]+/)*[^/]+\.(?:yml|yaml|json|toml|properties|conf)"
    r"|plugins/[^/]+/(?:[^/]+/)*[^/]+\.(?:yml|yaml|json|toml|properties|conf|txt|lang)"
    r")$"
)
CLASS_D_PANEL_KEYS = frozenset({"server-port", "rcon.port", "rcon.password", "query.port", "enable-rcon"})
```

- PROTOTYPE-REPORT (D-B/D-D): Classification rules:
  - `plugins/*/{userdata,data,players,playerdata,storage,cache}/**` and `plugins/*/{data,players,userdata,database,storage}.{yml,yaml,json,txt}` are always class C (built-in default override list; contents are an implementation choice per "Owner-permitted implementation choices").
  - The registry that records dynamic C reclassification (`dynamic-class-c`) lives in the per-server DB, never inside the server tree (OD-4).
  - A custom `level-name` world is class E through the default catch-all (the denylist explicitly names only `world`, `world_nether`, `world_the_end`).
  - Precedence order means every `*.db`, `*.sqlite`, `*.dat` under `plugins/` is class E even inside a class-C subtree (OD-2).
  - Text player data under `plugins/*/playerdata/` is class C. `*.dat` under `plugins/` stays class E (OD-2); binary player data is therefore not synced to `live-state`, covered by backup and Data Templates.
  - A `.jar` anywhere except root `*.jar` and `plugins/*.jar` is class E, including `plugins/*/lib/*.jar`; `.class`, `.so`, `.dll`, `.nbt`, and `.csv` are class E.
  - `server-icon.png` is class B, tracked only below the oversized-binary threshold (Unknown I; no number is defined here).
  - Nested config directories under `config/` are class B for `yml`, `yaml`, `json`, `toml`, `properties`, and `conf`.
  - A `.gitattributes` found in the server tree is class E and is removed by the D-G sanitizer; the panel generates the repo `.gitattributes` at commit time (NOD-1).
  - Any unknown extension is class E through the default catch-all.

- PROTOTYPE-REPORT / OWNER-STATED (OD-2 consequence): Plugin binary data (`*.db`, `*.sqlite`, `*.dat` and similar under `plugins/`) is never tracked and never synced to `live-state`; it is covered by the existing backup system and is included in optional Data Templates (D-F overlays class-E paths). This includes binary player data (`*.dat` under `plugins/*/{userdata,players,playerdata}/**`); text player data under `playerdata/` is class C and is synced to `live-state`.

- FACT (creation-time) / OWNER-STATED (OD-3): `eula.txt` is written at creation time by `write_eula` (`backend/app/modules/server/application/services/jar_service.py:987-1010`) which writes `eula=true`, called from `create_server.py:187`; test deployments write it at `backend/app/modules/versioning/infrastructure/config_writer.py:87-89`; backups already list it in `CONFIG_FILES` at `backend/app/services/backup_orchestrator.py:27-34`. Normative: `eula.txt` is panel-generated (class-D-like), never tracked; the P2 clean export must write it into the exported root.

- OWNER-STATED (OD-6): `mods/*.jar` and mod configs are out of scope; they fall to class E via catch-all. Supporting mod loaders (Forge / NeoForge / Fabric) in Advanced mode later will require promoting `mods/*.jar` and their config files to class A/B BEFORE enabling Advanced mode for them, so that Clean Export does not boot without the mods (see Lane E).

### Provisional - assistant recommendation, NOT confirmed by the owner

- ImportReview and AutoCommitLiveChanges stay and are hidden in Simple.
- Two-tier backups are owner-stated; they ship in P7 (v8 D-M).
- `server.properties` normalization is PROTOTYPE-REPORT (not yet validated against a real Paper boot; see D-C and prototype 3).
- Allow-list v1 is normative (PROTOTYPE-REPORT); validation against a real Paper boot remains OPEN (see Allow-list v1 (normative) and prototype 3).
- External claims are ASSUMPTION (external, unverified): GitHub 100 MB push limit, ext4 default on
  Ubuntu/Debian, Git worktree rules, and Paper rewriting configs; see Prototype before build.
- Data Template storage layout is an implementation choice; run identity remains Git sha + optional
  Data Template (D-F).

## External review disposition

- OWNER-STATED (2026-11-09): accepted into spec: external findings 1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
  11, 12, 13, 14, and 16.
- OWNER-STATED (2026-11-09): partially accepted: 15 (the live server is already a copy of `main`;
  used as framing only).
- OWNER-STATED (2026-11-09): rejected/ignored: 17 (moot once runs are clean exports) and the Paper
  `_version` detail (implementation detail).
- External factual claims (GitHub 100 MB push limit, ext4 default on Ubuntu/Debian, Git worktree
  rules, Paper rewriting configs) are ASSUMPTION (external, unverified) until the prototypes pass.

## Prototype before build

- PROTOTYPE-REPORT / OWNER-STATED: Prototype 1 is partially covered: real probe tested on tmpfs,
  overlay, and xfs. ext4 and ZFS reflink behavior remain UNVERIFIED.
- PROTOTYPE-REPORT / OWNER-STATED: Prototype 2 is covered: hostile `.git` directories and submodule
  pointer files, file and directory symlinks, hostile `.gitattributes` driver lines, worktree
  collision and locks, dirty worktree merge guards, and `git archive` clean export were empirically
  verified.
- OWNER-STATED (OD-5): Prototype 3 is NOT covered: no real Paper boot, no allow-list derivation from
  a booted server, and no 120 MB GitHub push were run; it stays OPEN. Config normalization, key-level
  merge, pre-commit validator, and snapshot comparison are embedded as normative text
  (PROTOTYPE-REPORT).

## Current Behavior

- FACT: No `ServerMode` exists (`rg -n '\bServerMode\b' backend/app frontend/src` -> no matches).
- FACT: `servers` has no mode column; columns run from identity through ownership/relationships
  (`backend/app/modules/server/infrastructure/models.py:20-78`).
- FACT: `ServerCreateRequest` has no mode (`backend/app/api/v1/schemas/server.py:11-41`);
  `ServerUpdateRequest` uses `extra="ignore"` (`schemas/server.py:44-45`).
- FACT: Alembic head is `b1e2100000023`
  (`backend/alembic/versions/b1e2100000023_add_server_lifecycle_leases.py:15-16`).
  `RELEASE_MINIMUM_DB_REVISION` and `EXPECTED_ALEMBIC_HEAD` are both pinned to it
  (`backend/app/core/persistence/db_revision.py:30-31`);
  `backend/tests/core/test_batch4_core_saga.py:41` asserts the same value. Gates exist:
  `scripts/check-db-revision`, `scripts/check-route-contract`.
- FACT: The Versions nav item is always rendered (`frontend/src/layouts/ServerShell.tsx:156`),
  with no mode gate.
- FACT: The Files API writes the live server root directly. `write_file_content` resolves from the
  deployment root and calls `local_fs.write_binary_atomic`
  (`backend/app/api/v1/routers/files.py:192-208`); resolution is at `files.py:64-116`. The write
  has no branch parameter, no `main` protection, and no worktree routing.
- FACT: Versioning routes are registered globally on the router and are not gated by server mode
  (`backend/app/api/v1/routers/versioning.py:565-572`, `605-620`, `671-686`, `689-690`).
- FACT: The current versioning engine is not native Git. No `git` executable invocation exists in
  `backend/app` (search for `git` subprocess usage returned no matches; the only `.git` reference
  is a directory check at `backend/app/core/persistence/reconciler.py:101`); materializations are
  plain directories written by `write_tree_to_dir`
  (`backend/app/modules/versioning/application/commands/create_materialization.py:173-178`), and
  `tree_writer` documents and implements plain-file writes with no reflink and no chmod/exec
  handling (`backend/app/modules/versioning/infrastructure/tree_writer.py:19-23`, write at
  `:42`, verify at `:64-77`). So-called worktrees are plain `.onx/worktrees/<uuid>` directories,
  not `git worktree` instances (`backend/app/modules/versioning/domain/value_objects.py:52-53`;
  `create_materialization.py:134-136`).
- FACT: The current versioning state is a custom database DAG and manifest/tree model.
  `server_branches` stores `head_commit_id`, `status`, and protection fields
  (`backend/app/modules/versioning/infrastructure/models.py:27-39`); commits and parent links are
  separate tables (`models.py:54-63`, `:76-88`); materializations are persisted at
  `models.py:183-194`.
- FACT: `server_branches` has no assigned port, runtime status, console, or activity/change-log
  columns (`models.py:27-39`). Runtime port/status live on `server_runtimes`
  (`models.py:145-158`), and the activity log has no branch column
  (`backend/app/modules/activity/infrastructure/models.py:17-29`); branch names appear only inside
  summary text (`backend/app/modules/activity/application/subscriber.py:131-137`).
- FACT: Merge checks only that the target branch is not archived
  (`backend/app/modules/versioning/application/commands/merge_commits.py:100-101`); it does not
  check `BranchProtectionPolicy`. It is also manifest-only: a caller `manifest` is part of the
  command (`merge_commits.py:20-26`), and if parent manifests differ with no caller manifest, the
  command raises "Merge conflict: manifests differ and no resolved manifest was provided"
  (`merge_commits.py:135-145`). There is no three-way tree merge.
- FACT: Direct commit checks branch protection
  (`backend/app/modules/versioning/application/commands/create_commit.py:136-163`), including the
  force-bypass permission path.
- FACT: `require_test_pass` and `allow_force_bypass` are stored
  (`backend/app/modules/versioning/domain/entities.py:57,59`) and exposed in schemas
  (`backend/app/api/v1/schemas/versioning.py:315,321`) but are not read by any enforcement path in
  `backend/app`; only `allow_direct_commit` is read by `can_commit_directly`
  (`entities.py:139`).
- FACT: Promotion enforces a PASSED test run
  (`backend/app/modules/versioning/application/commands/promote_commit.py:147-159`).
- FACT: Test containers are named `onx-test-<test_id>`
  (`backend/app/modules/versioning/infrastructure/test_runner.py:296,641`), run from a commit's
  materialized tree after `materialize -> launch -> verify` (`test_runner.py:401-435`), and mount
  that test directory at `/data` (`test_runner.py:642-684`); one container per run.
- FACT: `world*` is excluded from immutable snapshots (ADR-0016,
  `docs/decisions/0016-persistent-dataset-boundary-and-isolation.md:17`); world cloning uses
  `cp --reflink=always -r`
  (`backend/app/modules/versioning/infrastructure/btrfs_zfs_driver.py:48`); the manifest builder
  scans non-world paths (`manifest_builder.py:53-54`) and captures config extensions plus
  `mods/`/`plugins/` jars (`manifest_builder.py:30`, `:98-113`).
- FACT: The HTTP 412 raise is `StorageCowUnavailableError`
  (`backend/app/core/exceptions.py:318-333`, `http_status=412` at line 333), raised by
  `assert_supports_reflink`
  (`backend/app/modules/versioning/infrastructure/storage_probe.py:95-100`, raise at line 100),
  called at `create_commit.py:120` and `test_runner.py:419`. The `versioning.py:584-592` text is a
  preflight response message, not the raise.
- FACT: `DockerProvider` mounts one directory at `/data`
  (`backend/app/modules/server/infrastructure/providers/docker.py:471-472`).
- FACT: Local providers are registered
  (`backend/app/modules/server/infrastructure/providers/__init__.py:20-22`); ADR-0015 states
  `Runtime` delegates to `ServerProvider` implementations, naming `DockerProvider`,
  `LocalLinuxProvider`, and `LocalWindowsProvider`
  (`docs/decisions/0015-runtime-entity-and-server-provider-relationship.md:16-23`).
- FACT: There is no repository-sync GitHub integration. The only GitHub API use found is plugin
  release metadata download
  (`backend/app/modules/versioning/infrastructure/plugin_artifact.py:29-30`).
- FACT: The repository `.gitignore` excludes database/log artefacts and server data directories
  (`.gitignore:25-31`, `:51`, `:113-117`), but the versioning code does not create or validate a
  per-server Git repository, per-server `.gitignore`, Git remote, or Git LFS/SHA256 CAS pointer
  lockfile.

### Resolved v4 CONFLICTs and remaining CONFLICT

- RESOLVED by D2-v5/D10-v5 and Unknown H: the v4 CONFLICT between "hidden commit per edit" and the
  owner's Working Changes/history requirements. Commits are now explicit via Save & Commit, and
  history operations use native Git.
- RESOLVED by Unknown F: the v4 CONFLICT between D1 (Simple must be server-side unreachable) and
  globally registered versioning routes. The target guard is a router-level dependency plus an
  application-layer command check; current code remains global until P1.
- RESOLVED by D4-v5: the v4 CONFLICT between D4 (`main` is saved state) and P2 (Advanced `main`
  resolved to the live root and was editable in Files). `main` in Files is no longer a live-root
  edit path.
- REMAINING CONFLICT: D9 removes Local providers eventually, but ADR-0015 keeps them as `Runtime`
  providers (`docs/decisions/0015-runtime-entity-and-server-provider-relationship.md:16-23`). D9
  needs a D2 (governance) decision record plus a superseding ADR before P6. Recorded, not resolved
  silently.

## Proposed Change

OWNER-STATED (v8 D-M): phases are cut by user-visible behavior, not internal components. Owner
order: prerequisite CI/Windows fixes first (outside this spec; not specified here), then P1, then
P2. Each phase is independently shippable and states what the user sees. Advanced is not shown in
the UI until the Git repository + clean export work in P2. Live refresh ships only with the
stop-check + rollback in P3.

| Phase | User sees | Core work |
|---|---|---|
| P1 | Simple servers unchanged; Advanced still hidden | mode column, server-side Simple guard |
| P2 | Advanced appears; branch Files; Save & Commit | repo, allow-list, 5 classes, clean export |
| P3 | Merge UI; live-state; restart + rollback | key-level merge, class-C sync, atomic refresh |
| P4 | Branch/test runs; ports; Data Templates | clean-export runs, port set, branch metadata |
| P5 | GitHub connect/fetch; optional webhook | fetch-first sync, HMAC, non-fast-forward main |
| P6 | Docker-only creation; local providers gone | D9 consolidation |
| P7 | Two-tier backup controls | backup tiers |

The v5 design replaces the custom versioning engine with real Git; old code paths are described
above only to show what is being replaced. `materialization_id` is removed (D-F); see the consumer
mapping in P2.

### P1 - Mode column (default simple), creation chooser, server-side Simple guard

- **User sees:** Simple servers behave as today; Advanced is still hidden in the UI (D-M).
- Add a `ServerMode` value object (`simple`, `advanced`) and persist `servers.mode` defaulting to
  `simple`; mode is per server (D1). Set it at creation through `create_server.py` and
  `import_server.py`; there is no in-place change in P1 (D7 conversion comes later).
- Add the creation-time chooser: Simple is shown; Advanced remains hidden until P2 (D-M).
  OWNER-STATED (v8 D-H): Windows users use Simple only; Advanced is not gated on reflink/COW and is
  allowed on ext4. The current `/versioning/preflight` requires an existing `server_id`
  (`versioning.py:565-572`); that legacy preflight is not the Advanced gate.
- Enforce the Simple guard exactly as resolved by the owner (Unknown F): a FastAPI router-level
  dependency on the versioning/Git routers PLUS an application-layer check in the relevant
  commands. Raise `ServerModeVersioningDisabledError` (HTTP 409 Conflict) whenever
  `server.mode == ServerMode.SIMPLE`. The exact route list must be enumerated in P1 and checked by
  `scripts/check-route-contract`; commands must not be reachable by bypassing the router.
- Hide the Versions nav item in Simple as a UI convenience only; the server-side guard is the
  boundary.
- Remove D8-obsolete work: no migration of existing servers and no deriving mode from existing
  commits.
- **Files:** server domain `value_objects.py`, `infrastructure/models.py`,
  `infrastructure/repository.py`, `application/read_models.py`, `create_server.py`,
  `import_server.py`, API schemas/routers, versioning router/dependencies for the guard,
  `frontend/src/layouts/ServerShell.tsx`, frontend types/API client, create/import wizard. New
  Alembic revision after `b1e2100000023`.
- **Migration:** add non-null `mode` with `server_default='simple'`; downgrade drops the column.
  Bump `RELEASE_MINIMUM_DB_REVISION` and `EXPECTED_ALEMBIC_HEAD` (`db_revision.py:30-31`) and
  update `test_batch4_core_saga.py:41`; run the db-revision and route-contract gate scripts
  (`scripts/check-db-revision`, `scripts/check-route-contract`).
- **Rollback:** drop the column and revert the guard/nav gate; only the mode value is at risk.
- **Not built:** branch context, branch-aware Files, real Git engine, clean export, merge changes,
  live refresh, run-from-branch, GitHub sync, conversion.

### P2 - Repo, clean export, Save & Commit, branch-aware Files

- **User sees:** Advanced appears in the creation chooser; an Advanced server opens Files with
  branch selection and Save & Commit. Live refresh and branch/test runs are not built yet.
- Advanced servers get a native Git repository. The Git directory lives outside the server tree
  (D-G). `main` is created eagerly with an initial commit of the allow-listed class-B files and
  class-A lockfiles; it cannot be removed (D4-v5/v8).
- File ownership (D-A/D-B): implement the five classes and the explicit allow-list per "Allow-list v1
  (normative)". Ignore everything by default; track only explicitly allowed paths. Code jars live in
  the sha256 CAS; Git tracks only their lockfile (`onx-jars.lock.json`, path, sha256, size, source).
  Class C is not in branch worktrees; class D is injected; class E is never tracked.
- Allow-list v1 list is normative (PROTOTYPE-REPORT); real-boot validation remains OPEN (prototype 3).
- UI branches are real Git branches (`refs/heads/*`), each in its own `git worktree` under
  `.onx/worktrees/<branch>`. One worktree per active branch; Git objects are shared across
  worktrees. Worktrees referenced by a run are `git worktree lock`ed (D-J).
- Replace the custom database-backed versioning engine: stop writing `server_commits`,
  `server_commit_parents`, manifest trees, and materialization tree replicas as the source of
  history. `server_branches` remains operational metadata. Legacy tables/commands are retired from
  the write path and dropped only in a dedicated migration after the UI no longer reads them; D8
  means no data migration of existing test/dummy servers.
- Header displays `Server | Branch` and a branch selector; all pages follow the selected branch
  (D3). Branch Files covers the branch worktree, which under D-A/D-B is the tracked allow-list
  (class B plus class-A lockfile). Class C/D/E data is not part of the worktree.
- Branch files edit the worktree as uncommitted changes. Save & Commit stages allowed paths and
  runs native `git add` + `git commit` (D2/D10). The staging scope is an implementation choice.
- Save & Commit validation (D-C/D-E): normalize `server.properties` (strip `#Minecraft server properties`
  header and `Properties.store()` timestamp comment, sort keys, remove class-D keys; PROTOTYPE-REPORT,
  not yet validated against a real Paper boot); reject config files that contain conflict markers or
  fail to parse. Never write conflict markers into a server directory.
- Clean export (D-F): build the export service using `git archive` or equivalent of a pinned sha.
  The export has NO `.git`; it is the only container root; the editing worktree is never mounted.
  The export must also write `eula.txt`. This service is built in P2; branch/test runs consume it in P4.
- Delete `materialization_id` as a concept (D-F). Run identity is Git sha + optional Data Template.
  Consumer mapping:
  - `Runtime` (`entities.py:401-409`, `:454-457`): replace `commit_id` +
    `materialization_id` with `code_sha` + optional `data_template_id`; keep rejecting mutable
    branch references.
  - `test_runner.py` (`:401-435`, `:642-684`): replace materialize -> mount with clean export ->
    mount; no `.git`.
  - `promote_commit.py` (`:147-159`): Promote is removed; merge + live refresh replaces it; PASSED
    evidence binds to `code_sha`.
  - EvidenceBundle: exact current fields are UNKNOWN; replacement binds evidence to `code_sha` +
    optional `data_template_id`; add to recon.
  - Materialization tables/repositories (`models.py:183-194`;
    `create_materialization.py:173-178`) and the materialized-file route
    (`write_materialized_file.py:20`, `:85-115`; `versioning.py:689-690`): retire by explicit
    mapping, not omission.
- **Files:** Git engine, CAS/lockfile, allow-list, clean-export service, branch worktrees,
  `server_branches`, `files.py`, Files API schemas, branch context, `ServerShell.tsx`,
  `ServerFilesPage.tsx`, Save & Commit UI, normalization, runtime/evidence schema migration.
- **Migration:** branch↔Git metadata, CAS/lockfile support, explicit retirement of
  `materialization_id` consumers. No existing-server data migration (D8).
- **Rollback:** disable Advanced creation and the new Git engine behind a flag; keep legacy data
  untouched until retirement is verified.
- **Not built:** merge UI, live-state sync, live refresh (P3); branch/test runs, ports, Data
  Templates (P4); GitHub (P5); conversion.

### P3 - Merge, live-state sync, restart refresh with rollback

- **User sees:** merge controls; a `live-state` branch; a restart/refresh action that requires a
  stopped container and offers rollback. GitHub is not built yet.
- Merge rules (D-E/D10): config merge is key-level for yml/json/properties/toml; never textual git
  merge on live files. Unknown formats: live wins + warning. Parse failure: live file untouched.
  Never write conflict markers into a server directory. Branch-to-branch code-class merge may use
  native git merge in the repo; export only after validation.
- Merge policy (D6/v8): merge into any branch including `main` is warning-only by default; tests
  never block; strict policy deferred (O). `main` protection remains (D4).
- Class C sync (D-A/D-D): sync a copy of live-owned state into the non-main `live-state` branch
  automatically. Plugin binary data (`*.db`, `*.sqlite`, `*.dat` and similar under `plugins/`) is class E
  and is not synced to `live-state`. `main` never receives automatic commits. A developer must merge
  `live-state` into their branch before editing class-C files. Restart compares live class-B files to
  the last synced snapshot; differing plugin files become class C (no overwrite, warning). Default
  always-C patterns in Allow-list v1 replace the small manual override list; misclassification is
  covered by backup/rollback.
- Panel-owned settings (D-A/D-C/D-L): inject `server-port`, `rcon.port`, `rcon.password`,
  `query.port`, `enable-rcon` at run/export time; never tracked. `server.properties` is tracked
  minus those keys and normalized at Save & Commit (PROTOTYPE-REPORT, not yet validated against a real
  Paper boot).
- Atomic live refresh (D-I): only after confirmed stopped (fail closed). Order: (1) confirm
  stopped, (2) sync class-C copy into `live-state`, (3) stage class-A/B tree sibling, (4) back up
  files to replace for rollback, (5) switch via rename/symlink flip, (6) start, (7) rollback on
  failure. Merge into `main` never touches running live.
- Class replacement: replace class-A/B from `main`; never overwrite class-C/E; inject class-D.
  Reflink if the real probe succeeds, else plain copy with free-space check (D-H).
- Promote is removed (N); merge + live restart refresh replaces it; code/route/permission removal
  is in this phase.
- `main` protection: eagerly created, non-archivable, non-unprotectable, non-deletable, DB
  backstop; Files read-only/forces branch. Closes `merge_commits.py:100-101` and
  `files.py:192-208`.
- **Files:** key-level merge, live-state sync, snapshot compare, panel injection, atomic refresh,
  rollback, backup of replaced files, Promote removal, `main` protection, API/contracts, frontend
  merge/restart UI.
- **Migration:** live-state branch metadata, refresh journal/rollback records. No existing-server
  data migration (D8).
- **Rollback:** restore backed-up class-A/B files; keep `live-state`; revert merge/protection
  behind a flag.
- **Not built:** branch/test runs, ports, Data Templates (P4); GitHub (P5); custom conflict UI.

### P4 - Branch/test runs, ports, Data Templates

- **User sees:** run branch/test controls; per-branch/test console and activity; a port set per
  runtime; start from a saved Data Template. GitHub is not built yet.
- All runs (live, branch, test) use the clean export of a pinned Git sha (D-F). No `.git` in the
  container root; the editing worktree is never mounted.
- Run identity: code sha + optional Data Template id; `materialization_id` is gone. A branch run
  uses the last committed state only; UI warns about uncommitted changes (K).
- No Data Template = fresh world from seed, including tests. Template data overlays only class-E
  paths. Runtime-generated changes are deleted automatically; the user may explicitly save a Data
  Template (stored separately from code; metadata DB; reflink where possible).
- Ports (D-L): each runtime publishes a set of host ports (game, rcon, query, plugin ports).
  In-container server-port/rcon are fixed and panel-owned class D. Duplicate-port checks scan every
  published port atomically, not just one port.
- Branch operational metadata: assigned port set, runtime status, per-branch console, activity.
  Today `server_branches` lacks columns (`models.py:27-39`); runtime port only on `server_runtimes`
  (`models.py:145-158`); activity has no branch column (`activity/infrastructure/models.py:17-29`).
  Add branch-scoped metadata/indices.
- Worktrees referenced by a run are `git worktree lock`ed (D-J); release/unlock on stop.
- **Files:** Git-to-runtime resolution via clean export, `Runtime`/repository, `DockerProvider`,
  lifecycle/supervisor, API/permissions, frontend run controls, port-set allocation/checks,
  branch-scoped activity/console, Data Template storage, `server_branches` migrations.
- **Migration:** branch operational metadata, port set, Data Template metadata, activity indices.
  `server_runtimes` remains the ledger. No existing-server data migration (D8).
- **Rollback:** disable route/command and stop branch/test containers; `main` unchanged.
- **Not built:** GitHub (P5), multi-node placement, multiple production runtimes per server,
  branch permissions.

### P5 - GitHub sync (last Advanced stage)

- **User sees:** connect a private GitHub repository; fetch/poll sync state; optional webhook.
  Other Git hosts remain out of scope.
- Poll via `git fetch` FIRST; webhook optional (NAT). Webhook: HMAC-SHA256 on raw body; dedupe by
  `X-GitHub-Delivery`; allow operator redelivery. Handlers only enqueue; one repo write lock (D-J).
- Reject non-fast-forward updates to `main`. The panel generates `.gitattributes` at commit time:
  `* text=auto eol=lf` for text configs, `-text` for jars; `core.filemode true`. Jars never go to GitHub
  as plain blobs (D-A).
- Unknown J narrows to credential choice: GitHub App vs fine-grained token vs deploy key. Unknown
  I is resolved by D-A (CAS + lockfile). The 2026-11-10 prototype report does NOT cover GitHub, so the
  100 MB push limit and jar-size handling remain ASSUMPTION (external, unverified).
- **Files:** GitHub remote/auth/webhook, fetch/push, sync commands/queries, connection UI,
  panel-generated `.gitattributes`, contracts.
- **Migration:** remote/connection metadata. No existing-server data migration (D8).
- **Rollback:** disconnect GitHub and disable webhook processing; keep local Git history.
- **Not built:** other Git hosts, interactive conflict UI.

### P6 - Docker-only consolidation

- **User sees:** Docker-only creation; local provider choices gone.
- Stop allowing new local servers (LocalLinux/LocalWindows; tmux fallback), provide a local-to-
  Docker migration path, and delete local provider code only after migration is verified.
  OWNER-STATED (v7/v8 D-M): Docker is the only runtime; no server runs without Docker.
  Windows-hosted servers run as Docker containers too. Local-provider unit tests are temporary and
  are deleted with the providers in P6.
- CONFLICT: D9 removes Local providers eventually, but ADR-0015 keeps them as `Runtime` providers
  (`docs/decisions/0015-runtime-entity-and-server-provider-relationship.md:16-23`). D9 needs a D2
  (governance) decision record plus a superseding ADR before P6. Recorded, not resolved silently.
- **Files:** create/import validation, provider factory/registry, local providers, console-stream
  tmux path, migration tooling, contracts, frontend provider choices.
- **Migration:** per-server data migration plan; no schema change assumed.
- **Rollback:** keep local code/registration until final deletion; gate creation by flag/config.
- **Not built:** local-code deletion before migration evidence, remote/cloud consolidation.

### P7 - Backup tiers (late)

- **User sees:** two-tier backup controls.
- Two-tier backups are owner-stated; split backups into those tiers. Policy details are
  unspecified; start only after P2-P6 are stable. Misclassification risk in D-D is covered by the
  backup and rollback.
- **Files:** backup domain/commands/repositories, provider save/restore hooks, API/contracts,
  frontend.
- **Migration:** TBD at phase start.
- **Rollback:** keep the existing single-tier behavior behind a flag.
- **Not built:** tier policy details, retention rules, cross-tier restore semantics.

## Conversion (later)

- D7: Advanced -> Simple copies `main` into a brand-new Simple server; the old server may be
  deleted. Simple -> Advanced makes the Simple server's files become `main` (under D2-v5 this
  means initializing a real Git repository and committing the allow-list as `main`). OWNER-STATED
  (v8 D-A): class-A code is materialized from the CAS lockfile, class-C stays live-owned, class-D
  is panel-injected, and class-E is never tracked. This is wanted later and should be easy, but is
  NOT in P1. The Advanced -> Simple result has no Git or GitHub relation and also serves developers
  who prefer working by hand. Simple -> Advanced stays as written; Unknown D remains UNKNOWN unless
  the owner decides.
- UNKNOWN (D): whether Simple -> Advanced is in place or through a new server. D7 describes the
  data direction, not the mechanics.

## Future extension points (Lane E, not scope)

- Lane E, capture only: Discord integration, multi-node, and small Rust libraries only for
  MEASURED hot spots (Governance section 7: Baseline -> Profile -> Hypothesis -> Rust PoC ->
  Benchmark -> Integration test -> Cost/complexity review -> Adopt or discard).
- Lane E future note: an intermediate mode or a fourth mode for multi-node (OWNER-STATED v7).
- Private GitHub Repository sync is no longer Lane E; it is core Advanced architecture (D12-v5).
  Native Git makes other remotes technically possible, but other Git hosts/remotes are not in
  scope.
- Lane E (mod loaders, out of scope): Advanced mode does not support Forge/NeoForge/Fabric. `mods/*.jar`
  falls to class E via the catch-all and is never tracked, so a modded Advanced server would Clean-Export
  without its mods. If mod loaders are ever supported in Advanced mode, `mods/*.jar` and their config files
  MUST be promoted to class A/B BEFORE enabling Advanced mode for them.
- Lane E (idea only, not designed): optional modpack support for Simple servers; the owner finds it
  useful, it is outside this spec.
- Keep extension points open; none of these are in scope for P1-P7.

## Affected Components

- Server domain/persistence: mode value object, `servers.mode`, lifecycle, read models,
  create/import.
- File ownership/storage: five classes (A-E), explicit allow-list, allow-list evaluation engine,
  normalization, hardened Git invocation, eula generation at export, sha256 CAS + Git lockfile,
  `server.properties` normalization, class-C `live-state` sync, class-D panel injection.
- Versioning: real Git engine, branches/worktrees, clean export, commits, key-level config merge,
  Save & Commit validation, `main` protection, one repo write lock, Promote removal.
- Runtime/evidence: clean-export container root; run identity `code_sha` + optional
  `data_template_id`; remove `materialization_id`; update Runtime, EvidenceBundle, test_runner,
  promote, materialization tables/repositories, and materialized-file route.
- Files: branch/worktree resolution over the allow-list, `main` read-only protection, Save &
  Commit, no class-C/D/E data in the worktree.
- Providers: `DockerProvider` remains; `LocalLinuxProvider`, `LocalWindowsProvider`, provider
  factory local branches, and their unit tests are removed in P6. Container uid is UNKNOWN/recon.
- Frontend: `ServerShell`, create/import wizard, branch context, Files, Versions, merge/live-state/
  restart UI, branch/test runs, port sets, Data Templates, GitHub connection, Promote removal.
- Contracts: mode, allow-list, clean export, merge policy, live refresh order, repo write lock,
  port set, GitHub sync, Simple guard, Promote route/permission removal.
- Backups: two-tier backup domain/commands/repositories and restore semantics in P7.

## Interfaces & Contracts

- `servers` gains `mode` in create/read responses; mode is creation-only in P1 (D7 conversion is
  later and unspecified).
- The Simple guard is a server-side contract (D1, Unknown F): versioning/Git routes and commands
  must fail with `ServerModeVersioningDisabledError` (HTTP 409) for Simple. Enforcement is a
  FastAPI router-level dependency plus an application-layer check in commands; the exact route
  set is enumerated in P1.
- Files API gains an additive branch selector; `main` is read-only or forces a working branch in
  Advanced (D4-v5). Branch edits target the branch worktree, not the live root. Class-C/D/E files
  are absent; class A is exposed through the CAS lockfile; class B is editable.
- "Save & Commit" is explicit: validate the allow-list, normalize `server.properties`, reject
  conflict markers/unparseable files, update the lockfile, then `git add` + `git commit`. File
  writes and settings changes do not create commits.
- Clean export contract: a pinned sha exports to a container root with no `.git`; the editing
  worktree is never mounted (D-F). Run identity is `code_sha` + optional `data_template_id`;
  `materialization_id` is removed.
- Branch records map 1:1 to real Git branches; `server_branches` carries operational metadata
  (port set, runtime status, console, activity) and not a Git tree replica.
- GitHub sync (P5): connected private repository, fetch-first polling, optional HMAC-SHA256 webhook,
  delivery dedupe, 1:1 branch mapping, visible sync state (D12/D-K).
- Merge: key-level for yml/json/properties/toml; native `git merge` only for code-class in the
  repo; never textual merge on live files. Merge into any branch, including `main`, is warning-only
  by default; tests never block; strict policy deferred (D-E/D6/O).
- Live refresh (D-I): merge into `main` never touches running live; live files update only after a
  confirmed stop, in the seven-step order, with rollback.
- Ownership: five classes and an explicit allow-list; ignore by default; exact list UNKNOWN (D-A/
  D-B). Jars use the sha256 CAS + lockfile, not plain Git blobs.
- Allow-list: the five classes are evaluated in the stated order; unmatched paths are class E;
  `onx-jars.lock.json` is the class-A pointer, not class B; `eula.txt` is generated at export.
- `Runtime` rejects mutable branch references as `commit_id` (`entities.py:401-409`); a run resolves
  a concrete sha first. A worktree referenced by a run is locked (D-J).
- P6 removes local-provider behavior paths and their unit tests; update
  `scripts/check-route-contract` in phase. Docker is the only runtime.

## Failure & Edge Cases

- COW is not required (D-H): probe the exact directories for real reflink support; on success use
  reflink, otherwise plain copy with a free-space check. Advanced is allowed on ext4. Windows is
  Simple-only. The current `StorageCowUnavailableError` HTTP 412/no-fallback rule
  (`exceptions.py:318-333`) must change.
- Simple server: versioning/Git routes and commands must fail server-side with
  `ServerModeVersioningDisabledError` (HTTP 409); current routes are global until P1.
- Direct `main` edit in Advanced: rejected by the Files API/UI (read-only or forced branch switch,
  D4-v5). The exact HTTP status is an implementation choice; 409 is consistent with protected-
  branch behaviour.
- Merge into any branch, including `main`: warning by default and the merge succeeds (D6/v8); tests
  never block a merge by default. The optional strict policy is deferred with the testing system
  (Unknown O).
- Key-level config merge (D-E): parse failure leaves the live file untouched; unknown format falls
  back to live-wins + warning; never write conflict markers into a server directory. Save & Commit
  rejects conflict markers or unparseable files.
- Native Git merge conflict for code-class files: merge stops; conflict must be surfaced. The
  resolver UX (UI, local Git, or GitHub) is out of scope.
- GitHub sync (D-K): non-fast-forward `main` updates are rejected; force-push is denied; webhook
  deliveries are deduped; network/credential failures need retry state. Credential choice is the
  remaining Unknown J.
- Plugin jar: sha256 CAS + lockfile (D-A); GitHub must never receive a plain jar blob. The size
  threshold is UNKNOWN.
- Duplicate ports (D-L): scan every published port atomically at creation; a conflict rejects the
  new runtime.
- Branch run source: uses the last committed state only; the UI warns about uncommitted changes not
  included (K). The `Runtime` pins an immutable sha.
- Uncommitted working-tree changes on branch switch/restart: PROPOSED (not decided, Unknown L):
  stay in each branch's own worktree. A merge into a target with uncommitted changes is refused
  until Save & Commit or discard. UNKNOWN (proposal only).
- Branch run/test runtime changes: deleted automatically; the user may save a reusable Data
  Template and start from it (P4).
- Class-B live change before restart: restart compares live to the last synced snapshot; a
  differing plugin file becomes class C, is not overwritten, and warns (D-D). A small manual
  override list and rollback cover misclassification.
- Live refresh (D-I): missing/inconclusive stop confirmation fails closed; back up files before the
  switch; roll back if start fails.
- Restart sync: replace class-A/B from `main`; never overwrite class-C/E; inject class-D. Reflink
  if available, else plain copy.
- Deleting a branch with an active worktree/runtime: block or stop first; exact behavior UNKNOWN.
- Git itself refuses to check out the same branch in two worktrees; the design must not assume
  otherwise.
- `eula.txt` absent from a container root = export bug (the panel writes it at export time).
- Custom `level-name` is class E via catch-all (the denylist names only `world`, `world_nether`, `world_the_end`).
- Plugin binary data (`*.db`, `*.sqlite`, `*.dat`) is class E even inside class-C subtrees (denylist evaluates before class C).
- `mods/*.jar` is out of scope and class E via default catch-all.
- Existing servers are deleted by the owner (D8); no migration or legacy repair is designed.

## Tests & Verification

Test ideas only; no counts and no CI claims.

- P1: mode default `simple`; creation through `create_server.py`/`import_server.py`; versioning
  routes and commands return `ServerModeVersioningDisabledError` (409) for Simple; db revision
  constants and both gate scripts; nav hidden in Simple; Advanced hidden until P2.
- P2: Advanced gets a real Git repo with `main`; allow-list commits only allowed paths; nested
  `.git`/filters/symlinks stripped; branch create/delete maps to Git; one worktree per branch;
  Save & Commit validates/normalizes and commits; class-A jars resolve from CAS via lockfile;
  class-C/D/E files absent; `materialization_id` consumers updated; clean export has no `.git`.
- Allow-list test matrix (positive + negative): `paper-1.21.1.jar`=A, `plugins/X.jar`=A,
  `plugins/X/lib/foo.jar`=E, `plugins/X/data/foo.jar`=E, `plugins/X/data/foo.class`=E,
  `foo.so`=E, `foo.dll`=E, `foo.nbt`=E, `plugins/X/data/foo.csv`=E, `plugins/X/foo.csv`=E,
  `cache/*.jar`=E, `libraries/**/*.jar`=E, `plugins/X/data/foo.yml`=C,
  `plugins/X/playerdata/abc.yml`=C, `plugins/X/playerdata/abc.dat`=E,
  `plugins/X/userdata/abc.json`=C, `plugins/X/config.yml`=B, `config/paper-global.yml`=B,
  `config/nested/foo.yml`=B, `config/nested/deep/foo.toml`=B, `config/foo.conf`=B,
  `server-icon.png`=B, `.gitattributes`=E, `plugins/X/world.db`=E,
  `server.properties`=B, `onx-jars.lock.json`=A(lockfile; not matched by CLASS_B), `ops.json`=C,
  `ops.json.bak`=E, `plugins/X/storage/cache.dat`=E, `myworld/**`=E, `eula.txt`=E,
  `mods/*.jar`=E, `version_history.json.bak`=E.
- P3: key-level merge for yml/json/properties/toml; parse failure leaves live untouched; no
  conflict markers in server dirs; native Git merge only for code class; class-C sync to
  `live-state`; restart snapshot compare makes changed plugin files class C; live refresh order
  with stop fail-closed and rollback; merge into `main` never touches live; `main` protection;
  Promote removed.
- P4: all runs use a clean export of a pinned sha; no `.git`; worktree lock; run identity
  `code_sha` + optional `data_template_id`; no template = fresh world incl. tests; template
  overlays class-E only; duplicate checks cover every published port; per-branch console/activity.
- P5: GitHub connect/fetch-first; optional webhook HMAC/dedupe/redelivery; non-fast-forward `main`
  rejected; `.gitattributes`/`core.filemode`; jars never plain blobs; 1:1 branch mapping.
- P6: provider conformance for remaining Docker providers; no new local creation; migration
  round-trip; local provider unit tests removed; Docker is the only runtime.
- P7: two-tier backup policy and restore semantics when the owner defines them; the testing system
  never blocks a merge by default and the optional strict policy is deferred.
- Existing files verified present this session: `backend/tests/core/test_batch4_core_saga.py`,
  `backend/tests/infrastructure/test_backup_saga.py`,
  `backend/tests/infrastructure/test_iss011_shutdown_grace.py`,
  `backend/tests/application/test_supervisor.py`,
  `backend/tests/application/test_stale_startup_deadline.py`; gates `scripts/check-db-revision`,
  `scripts/check-route-contract`.

## Out of Scope

- The separate testing-system rework and its stage UI (D11). This spec only needs to expose the
  isolated branch/test run that the separate testing system drives; the stage UI is out of scope.
- The custom database-backed virtual filesystem/manifest-tree versioning engine and its
  manifest-only merge (replaced by D2-v5/D10-v5).
- A custom interactive conflict-resolution UI; native Git three-way detection is in scope, the
  resolver UX is not specified here.
- D12 future ideas beyond the connected private GitHub repository (Lane E), and other Git hosts.
- Backup tier policy details beyond the phase placeholder (P7).
- Removing local providers before a working migration exists (P6).
- Conversion implementation details (D7), including the in-place vs new-server question (D).
- Windows-hosted container prerequisites and CI/Windows fixes; they are a prerequisite outside this
  spec (D-M).
- Any numeric performance or test-count claims.

### Testing system (future, out of scope)

- OWNER-STATED (v7, Unknown O deferred): the testing system evolves separately: stages and UI,
  later GitHub CI/CD or Discord triggers, multiple containers in parallel, and stress and
  chaos-style tests. Tests never block a merge by default; the optional strict policy is defined
  later together with the testing system.

## OPEN QUESTIONS

### Resolved by owner 2026-11-09 (v5/v7/v8)

- Container topology: resolved by D1/D2-v5 for the base server (one general container holds the
  whole server); branch/test runs use a new isolated container per D3.
- Merge-into-`main` gate: resolved by D6 (warning by default; optional configurable policy).
- Mode scope: resolved by D1 (per server, not per node or global).
- Existing servers: resolved by D8 (test/dummy data; owner deletes; no migration, no derive mode).
- Branch ports: resolved by D-L (publish a set of host ports; atomic duplicate scan over all).
- World in branch/test runs: resolved by D-F (no Data Template = fresh world from seed, including
  tests; a template overlays class-E only).
- Advanced -> Simple / Simple -> Advanced: resolved by D7 (later, easy; no in-place flip in P1).
- API for Simple versioning: resolved by D1 and Unknown F (unreachable server-side; router-level
  dependency plus application-layer check; `ServerModeVersioningDisabledError`, HTTP 409).
- Commit-from-worktree: resolved by D2-v5/D10-v5 (working tree + explicit Save & Commit; native
  `git add` + `git commit`).
- Unknown A (file sharing with main): SUPERSEDED by D-H. COW is not required; probe the exact dirs,
  reflink on success, else plain copy with a free-space check.
- Unknown C (`main` -> live sync boundary): SUPERSEDED by D-A/D-I. Replace class-A/B from `main`;
  never overwrite class-C/E; inject class-D; sync class-C into `live-state`; update live only after
  a confirmed stop.
- Unknown F (Simple server-side guard): enforce via a FastAPI router-level dependency on the
  versioning/Git routers PLUS an application-layer check in commands, raising
  `ServerModeVersioningDisabledError` (HTTP 409) whenever `server.mode == ServerMode.SIMPLE`.
- Unknown H (working changes and history): resolved by D2-v5. Editing changes the working tree;
  Save & Commit creates the commit; history/branch operations use native Git instead of hidden
  per-edit commits.
- Unknowns B, E, K, M: resolved 2026-11-09 (see v6 -> v7 and v7 -> v8 revision logs).
- Unknown N (Promote): resolved (Promote is removed; merge + live restart refresh replaces it).
- Unknown P (host/filesystem): SUPERSEDED by D-H. Windows is Simple only; Advanced is allowed on
  ext4; reflink is optional; use the real probe; the current `StorageCowUnavailableError` HTTP 412/
  no-fallback rule must change.
- `eula.txt` generated: resolved (FACT, `write_eula` in `jar_service.py:987-1010` and `config_writer.py:87-89`; backups list it in `CONFIG_FILES`; P2 clean export writes it into exported root).
- D-A..D-M: resolved by the owner on 2026-11-09; see the v8 owner section. Exact allow-list,
  normalization details, container uid, and credential choice remain UNKNOWN/ASSUMPTION there.

### New unknowns (owner has not decided)

- D. Simple -> Advanced: in place, or through a new server. UNKNOWN.
- G. Whether player-joinable non-main branch runtimes exist, concurrent branch-runtime cap,
  resource limits, branch permissions/roles. UNKNOWN.
- I. Oversized binary mechanism is resolved by D-A (sha256 CAS + lockfile); the size threshold is
  UNKNOWN.
- J. GitHub credential choice is UNKNOWN: GitHub App vs fine-grained token vs deploy key. HMAC
  webhook verification, delivery dedupe, and non-fast-forward `main` rejection are resolved (D-K).
- L. Uncommitted working-tree changes on branch switch/restart: PROPOSED (not decided) stay in each
  branch's own worktree; a merge into a target with uncommitted changes is refused until Save &
  Commit or discard. The proposal is UNKNOWN.
- O. DEFERRED 2026-11-09: the optional strict merge policy is defined later with the testing system;
  the default remains warning-only (D6).
- Exact class A/B allow-list: v1 list normative (PROTOTYPE-REPORT); validation against a real Paper boot OPEN (D-B; prototype 3).
- `server.properties` normalization specifics: v1 normalization normative (PROTOTYPE-REPORT); validation against a real Paper boot OPEN (D-C; prototype 3).
- ext4 and ZFS reflink behavior UNVERIFIED (D-H; prototype 1).
- `mods/*.jar` out of scope (Lane E).
- Container uid / `DockerProvider --user` (D-G; recon).
- Published plugin-port set per server (D-L).

### Owner-permitted implementation choices (not unknowns)

- `main` Files UX (D4-v5) may be a read-only view or may force creating/switching to a working
  branch. Both are owner-permitted; choose one in P2.
- Save & Commit may stage all allow-listed working-tree changes or a selected subset.
- Data Template storage layout is an implementation choice (OWNER-STATED v7); its metadata lives in
  the database and data is copied with reflink where possible.
- The manual class-B override list contents (D-D) are an implementation choice within the decision.

## KNOWN GAPS

- Current versioning is a custom database DAG + manifest/materialization engine, not native Git;
  no `git` executable invocation was found in `backend/app`.
- `merge_commits.py:100-101` checks only `archived`; it bypasses branch protection.
- Merge is manifest-only and raises when parent manifests differ with no caller manifest
  (`merge_commits.py:135-145`); there is no three-way tree merge.
- `require_test_pass` and `allow_force_bypass` are stored but unenforced (`entities.py:57,59`;
  `schemas/versioning.py:315,321`). Only promotion checks PASSED
  (`promote_commit.py:147-159`).
- Documentation names a nonexistent `RuntimeAdmissionScheduler`: `docs/current-state.md:13`,
  `docs/architecture/SPECS.md:287`; the real primitive is `admit()`. The ARCH overview records
  this at `docs/design/ARCH-2026-11-08-BRANCH-WORKSPACE-OVERVIEW-01.md:58` and `:536`.
- `main` is not system-protected or eagerly created (`archive_branch.py:82-86`,
  `entities.py:141-145`, `create_commit.py:125-133`).
- No production container-from-branch path; only isolated test containers run from commits.
- No worktree-to-commit path; `ScanLiveChanges`/`AutoCommitLiveChanges` read the live server dir
  (`scan_live_changes.py:108-123`; `auto_commit_live_changes.py:91-107`, `:129-157`).
- The general Files page has no branch source; branch-aware edits exist only through the
  materialization route (`write_materialized_file.py:20`, `:85-115`;
  `versioning.py:689-690`).
- No `ServerMode` and no mode column; `materialization_id` is pinned in runtime/evidence models and
  materialization creates a fresh uuid, with no reuse resolver.
- No five-class ownership/allow-list, sha256 CAS + lockfile, or clean export exists.
- No key-level config merge, class-C `live-state` sync, restart snapshot compare, atomic live
  refresh, backup-of-replaced-files, or rollback exists; the materialization route writes the live
  root.
- No per-repo write lock or worktree lock exists for add/commit/merge/fetch/push/gc/worktree
  add-remove.
- `StorageCowUnavailableError` currently returns HTTP 412 with no fallback
  (`exceptions.py:318-333`), contradicting D-H.
- `server_branches` has no port set, runtime status, console, or activity/change-log columns
  (`models.py:27-39`).
- No GitHub repository sync, webhook, fetch/push, or per-server Git init/allow-list/CAS support was
  found.
- Versioning routes are globally reachable with no mode gate, contradicting D1 until P1 lands.
- D9 conflicts with ADR-0015's retention of Local providers (CONFLICT); a governance D2 record and
  a superseding ADR are required before P6.
- Advanced has no mods/ allow-list (Lane E).
- The P2 clean export must generate eula.txt; today it is written only at create time and in test deployments.
