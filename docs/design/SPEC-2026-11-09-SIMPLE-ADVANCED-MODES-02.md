# SPEC-2026-11-09-SIMPLE-ADVANCED-MODES-02

Status: design specification **v8.7** (owner-confirmed v5/v6/v7/v8 plus 2026-11-10 decisions
OD-1..OD-9, 2026-11-11 decisions ND-1..ND-9, 2026-11-11 Red-Team hardening decisions
OD-v8.4-1..OD-v8.4-11, second Red-Team remediation decisions OD-v8.5-1..OD-v8.5-8,
2026-11-11 final closure decisions OD-v8.6-1..OD-v8.6-8, and 2026-11-11 Red-Team Round 3
remediation decisions OD-v8.7-1..OD-v8.7-15 covering findings R1-R18), CLOSED, DESIGN-COMPLETE,
and READY FOR BUILD across all phases P1-P7 (including P5.5 and D7 conversion). Zero open unknowns
and zero design blockers remain inside this specification. The normative classifier is
**Allow-list v2.3**.
**Release verification:** release of each phase is gated on its in-phase verification suite; the
former pre-build prototypes are mandatory in-phase integration gates that must pass before each
phase closes (see "Prototype before build" and "Tests & Verification"). The executable suite is
**110 matrix rows + `dir_fd` symlink check + cross-loader health-regex check**, all required to
report `MISMATCHES: 0`. **Build order:**
`P1 -> P2 -> P3 -> P4 -> (P5 and P5.5 in either order) -> P6 -> P7`. **Strict phase dependency:**
`P5.5` executes AFTER `P2`, `P3`, and `P4` are complete (P2: CAS, Lockfile Format 2.1, Allow-list
v2.3, LEC/Clean Export hooks, pinned-backup column, `ensure_simple_baseline_lockfile`; P3: encrypted
Class-C vault, 3-way/key-level merge engine, Refresh Journal, native-Git UI cutover; P4: isolated
branch test runs, joinable port sets, ephemeral Class-C overlay, quiescent Data Templates; P5.5:
`.mrpack`/CurseForge installer, loader provisioners incl. Paper LEC, batch Modrinth compatibility
matrix, 1-Click Safe Upgrade wizard on top of P2+P3+P4). `P6` (D9, Docker-only) is UNBLOCKED by
OD-v8.6-1: this specification supersedes ADR-0015's retention of the local providers, and no
separate D2/ADR paperwork is required. `P7` (two-tier backups) is fully specified by OD-v8.6-2 and
hardened by OD-v8.7-7. Governance paperwork is waived for P1-P7.

Evidence tags: FACT (verified by command this session, cite file:line), ASSUMPTION (inferred, not
verified), UNKNOWN (missing), CONFLICT (two sources disagree), OWNER-STATED (owner decision),
PROTOTYPE-REPORT (external prototype result quoted from the 2026-11-10 prototype report; not
reproducible in this repository; never restated as FACT).

## Revision log v8.6 -> v8.7 (owner decisions 2026-11-11 — Red-Team Round 3 Remediation R1–R18)

A sandbox Red-Team audit executed the v8.6 regexes, POSIX directory-swap behavior, `O_NOFOLLOW`
symlink races, and loader log formats and found 18 concrete defects. v8.7 applies all of them and
promotes the classifier to **Allow-list v2.3**. Nothing here reopens a phase; every fix is a
surgical strengthening of an already READY contract.

- OWNER-STATED (OD-v8.7-1, fixes R1): the Health Gate readiness regex becomes
  `r"^.*?\bINFO\b.*?: Done \([0-9.,]+s\)! For help, type [\"']help[\"']"`, matched against the new
  container's live stdout since `container_started_at` and reusing/extending
  `signal_detection.py:22`, so Paper, Vanilla, Fabric, Forge, and NeoForge all match. An explicit
  `health_gate_boot_timeout_seconds: int = 300` (configurable up to `900`) bounds the whole gate and
  triggers triad rollback on timeout.
- OWNER-STATED (OD-v8.7-2, fixes R2): `os.replace(staging_dir, live_dir)` is forbidden for a
  non-empty live directory (`ENOTEMPTY`). All swap sites use the **Crash-Safe Journaled Directory
  Swap**: `renameat2(..., RENAME_EXCHANGE)` where supported, otherwise journaled
  `live -> live.prev` then `staging -> live` with fsynced phases `SWAPPING_OUT_LIVE`,
  `SWAPPING_IN_STAGING`, `SWAP_COMPLETED`, and startup reconciler recovery from `live.prev`.
- OWNER-STATED (OD-v8.7-3, fixes R3): the secret guard becomes a Structured & Pattern Secret
  Scanner covering private-key headers, Discord bot tokens, Discord/Slack webhook URLs, GitHub PATs,
  and AWS keys, plus sensitive YAML/JSON/TOML/Properties keys with non-placeholder values. A
  `SecretFileInGitForbiddenError` offers **"Extract Secret to Panel Vault"**, replacing the literal
  with `${ONX_SECRET_<KEY_NAME>}` (encrypted Class D) and substituting it back at Clean Export Step 5.
  It blocks commits, D7 conversion commits, and pushes.
- OWNER-STATED (OD-v8.7-4, fixes R4, Allow-list v2.3): world-subfolder denylist alternatives are
  anchored behind a negative lookahead excluding `config/`, `defaultconfigs/`, `plugins/`, `kubejs/`,
  `datapacks/`, `global_packs/`, `resourcepacks/`, `shaderpacks/`, `patchouli_books/`, `scripts/`,
  `structured-config/`, `blueprints/`, `schematics/`, `structures/`; root `DIM-1`/`DIM1` stay E. The
  `.nbt` exemption and CAS match extend to `(datapacks|global_packs|kubejs/data)/**/structures/**`.
  Six regression paths are added to the matrix.
- OWNER-STATED (OD-v8.7-5, fixes R5/R15): Simple mode's authoritative lockfile lives on the host at
  `<host_state_dir>/server-meta/<server_id>/onx-jars.lock.json`, never inside container-writable
  `/data`; the `/data/.onx-manager/` copy is informational only and never trusted.
  `ensure_simple_baseline_lockfile(server_id)` ships in **P2** and auto-adopts any Simple server that
  lacks the host lockfile before backup/install/upgrade/D7.
- OWNER-STATED (OD-v8.7-6, fixes R6): Step 0 gains `open_safe_path_fd` and descriptor-relative
  traversal (`os.open(..., O_DIRECTORY|O_NOFOLLOW, dir_fd=...)`, `os.mkdir(..., dir_fd=...)`,
  `(st_dev, st_ino)` root verification, Windows reparse-point rejection), removing the TOCTOU window
  between the `lstat` walk and the actual open.
- OWNER-STATED (OD-v8.7-7, fixes R7/R8): Class C moves to a dedicated AES-256-GCM
  `<host_state_dir>/class-c-vault/<server_id>/` and never enters the shared public-jar CAS. The
  CAS/LEC GC roots now include all branches, all Simple host lockfiles, all 5 unpinned + all pinned
  Tier-1 snapshots, all retained Tier-2 archives, in-flight operations, and a 24-hour creation grace.
  Tier-2 archives are **mandatorily** chunked-AEAD encrypted when they contain Class C or go to S3,
  with a `ONX_MASTER_KEK`-wrapped per-archive DEK, 64 KiB AES-256-GCM chunks, and a final-chunk tag.
- OWNER-STATED (OD-v8.7-8, fixes R9): non-reflink live clone becomes two-pass (online pre-copy with
  `save-on`, then quiesced delta sync), the `save-off` window is hard-capped at **60 seconds** with
  `rcon_save_off_active` persisted and startup `save-on` recovery, and the storage copy lock plus
  `required_bytes * 1.10` reservation are scoped per target `st_dev`.
- OWNER-STATED (OD-v8.7-9, fixes R10): `base_overrides[relpath]` advances to `T` **per file** only
  when that file merged cleanly or was operator-resolved; a live-wins/parse-failure fallback keeps the
  previous `B` hash so drift stays visible.
- OWNER-STATED (OD-v8.7-10, fixes R11/R12): `BackupModel.pinned` and
  `ensure_simple_baseline_lockfile` move to P2/P3 so P3 rollback has pinning immediately; the
  creation-wizard Advanced option stays feature-flagged in P2 and is enabled for end users in P3 when
  Merge + Live Restart Refresh land together; legacy read models keep working until P3's atomic
  native-Git UI cutover. D7 `Simple -> Advanced` is copy-first: **copy** Class-A jars into CAS, keep
  the originals in `<server_root>` until Git/`main`/Clean Export verification passes, and only then
  optionally swap via OD-v8.7-2. A failed D7 leaves `<server_root>` 100% intact.
- OWNER-STATED (OD-v8.7-11, fixes R13): Paper joins LEC as `paper/{mc}/{build}`. A host-side
  `java -Dpaperclip.patchonly=true -jar paper-{mc}-{build}.jar` pre-warms `cache/**`, `versions/**`,
  and `libraries/**`; Clean Export Step 3 attaches them, so Paper boots offline like every other loader.
- OWNER-STATED (OD-v8.7-12, fixes R14): hostile executables are a **hard abort** only during
  `.mrpack`/CurseForge archive import; during worktree scan / Save & Commit / D7 they are moved to
  `<host_state_dir>/quarantine/<server_id>/`, excluded from `git add`, and reported as a
  high-severity banner so a container process cannot DoS legitimate commits.
- OWNER-STATED (OD-v8.7-13, fixes R16): joinable branch/test containers overlay an ephemeral
  disposable copy of the latest Class-C snapshot and inject `white-list=true` +
  `enforce-whitelist=true` by default; Class-C mutations in the test container are discarded and
  never write back.
- OWNER-STATED (OD-v8.7-14, fixes R17): every `D-I` live refresh compares `(mc, loader.id,
  loader.version)` against the deployed live lockfile and promotes to the Full Upgrade Refresh Path
  (pinned Class-E backup + Class-C snapshot + 4-step Health Gate) whenever `mc`/loader changes. P5.5
  quiesces, stops live, and takes the pinned backup **before** merging `upgrade/<target>` into `main`.
- OWNER-STATED (OD-v8.7-15, fixes R18 and minor edge cases): a Class-B config file above 1 MiB up to
  16 MiB is auto-routed to `A-CAS` (lockfile-tracked) instead of failing; only `> 16 MiB` (or
  `server-icon.png > 1 MiB`) raises `OversizedGitTrackedFileError`. The Java floor table becomes
  contiguous (`1.18`-`1.20.4` -> 17). `SET_MERGEABLE_ARRAY_KEYS` starts as
  `frozenset({("config/paper-global.yml", "MidTickChunkTasks.worlds"), ("spigot.yml", "commands.silent-commandblock-console-worlds")})`.
  Default `--pids-limit` rises to **2048** (per-server configurable) and the exported `/data` tree is
  chowned to the target non-root `uid:gid`. The zip ratio check applies only when
  `uncompressed > 16 MiB` (hard 4 GiB total and 100,000-entry caps stay). `KNOWN GAPS` records
  `RuntimeAdmissionScheduler` as FACT.
- Superseded in mechanism by v8.7: the v8.6 single-regex health gate (OD-v8.7-1);
  `os.replace` directory swaps (OD-v8.7-2); PEM-only secret scanning (OD-v8.7-3); Allow-list v2.2
  (OD-v8.7-4); the `/data`-resident Simple lockfile and P5.5-only baseline adoption (OD-v8.7-5);
  the `lstat`-then-open containment walk (OD-v8.7-6); shared-CAS Class C, partial GC roots, and
  optional single-nonce Tier-2 encryption (OD-v8.7-7); the full-copy-under-`save-off` clone and
  host-wide copy lock (OD-v8.7-8); blanket `base_overrides` promotion (OD-v8.7-9); the P5.5-pinned
  column and move-based D7 (OD-v8.7-10); "Paper has no LEC" (OD-v8.7-11); the quarantine hard abort
  on Save & Commit (OD-v8.7-12); Class-C-free test exports (OD-v8.7-13); version-bump bypass and
  merge-before-backup (OD-v8.7-14); and the 1 MiB hard reject, `1.18`-`1.20.1` Java row,
  `.properties` set-merge keys, `--pids-limit=512`, and 64-ratio-on-small-file rules (OD-v8.7-15).

## Revision log v8.5 -> v8.6 (owner decisions 2026-11-11 — Complete Closure of All Unknowns, P6 Unblocked, P7 & D7 Specified)

v8.5 was design-complete for `P1-P5.5` but still carried a governance block on `P6`, a placeholder
`P7`, an undesigned conversion mechanic, and a set of "owner has not decided" items. v8.6 closes ALL of
them. After this revision there are **zero UNKNOWN, PROPOSED, BLOCKED, or placeholder items** in the
active specification; the only deferred item is the external D11 testing-system rework and its
optional strict merge gate (Unknown O), which is explicitly out of scope.

- OWNER-STATED (OD-v8.6-1, unblocks P6/D9): governance paperwork for `P6` is WAIVED. This
  specification is the authoritative superseding record over `ADR-0015`'s retention of
  `LocalLinuxProvider` and `LocalWindowsProvider`; no separate D2 decision record or ADR is required.
  `P6` is `DESIGN-COMPLETE and READY FOR BUILD` after `P5`/`P5.5`, and the `BLOCKED`/`CONFLICT`
  status is removed from the header, phase table, `P6`, the CONFLICT register, and `KNOWN GAPS`.
- OWNER-STATED (OD-v8.6-2, fully specifies P7): **two-tier backups.**
  - **Tier 1 — Fast Operational Snapshots (local host tier):** Class E (`world*` + plugin binary
    DBs) + Class C snapshot (`ops.json`, `whitelist.json`, keys, live plugin data) + current
    `onx-jars.lock.json` and Class B config state. Mechanism: quiescent live clone (`save-off`,
    `save-all flush` via RCON, or a stopped container), `reflink` where supported or plain copy under
    the host-wide storage copy lock, finalized with a fsynced `.onx-complete.json`. Retention: keep
    the last **5** unpinned Tier-1 snapshots per server (FIFO pruning when the 6th succeeds);
    `pinned = True` snapshots (e.g. P5.5 pre-upgrade rollback) do NOT count toward the cap and are
    never auto-pruned until explicitly unpinned. Restore: atomic stop -> 3-part triad swap
    (Class A/B + Class C + Class E) -> start.
  - **Tier 2 — Portable Disaster-Recovery Archives (cold/external tier):** self-contained archive
    (`.tar.zst` or `.tar.gz`, optionally AES-256-GCM encrypted through the existing
    `modules/storage/` backends, stored locally or uploaded to S3) containing Class E, Class C,
    Class B, `onx-jars.lock.json`, and an optional `include_cas_jars: bool = False` toggle (default
    keeps the archive lightweight and re-hydrates public jars on restore; `origin: "user"` jars are
    bundled). Retention: configurable per server, default **7 daily + 4 weekly**; `pinned = True`
    archives are exempt. Cross-tier restore: extract into a verified staging directory, populate any
    bundled CAS blobs, validate every path through `resolve_safe_disk_path()`, then execute the same
    atomic triad switch as Tier 1.
- OWNER-STATED (OD-v8.6-3, resolves Unknown D / specifies D7): **Simple -> Advanced is strictly
  IN-PLACE** on the same `server_id` (UUID, ports, backups, history preserved): (1) confirm the
  container is `STOPPED`; (2) take an automatic Tier-1 backup + Class-C snapshot; (3) scan
  `<server_root>` through **Allow-list v2.2**, move Class-A jars/binaries into the host SHA-256 CAS
  and write `onx-jars.lock.json` (Format 2.1), initialize the external native Git repository (D-G),
  create the initial `main` commit (`onx-jars.lock.json`, normalized Class-B configs,
  panel-generated `.gitattributes`), create the `main` worktree, and flip
  `server.mode = ServerMode.ADVANCED`. **Advanced -> Simple creates a BRAND-NEW Simple server**:
  Clean Export of `main` + copy live Class C and Class E (reflink or copy) + write
  `.onx-manager/onx-jars.lock.json` into the new root with zero Git/GitHub association; the original
  Advanced server is untouched until the operator deletes it.
- OWNER-STATED (OD-v8.6-4, resolves Unknown G): non-main branch containers publish a dedicated Host
  Port Set (`D-L`) and ARE joinable by players/testers so gameplay can be verified before merge.
  Concurrency: maximum **1** active non-main branch/test container per server by default
  (configurable up to `max_concurrent_branch_runs = 3`), always gated by the global
  `RuntimeAdmissionScheduler` host RAM/CPU headroom check. Resources: minimum **2048 MB** RAM per
  branch/test container (**1024 MB** minimum for lightweight proxy/vanilla tests), defaulting to the
  server's configured memory limit or **4096 MB** if unspecified, with `--pids-limit=512`. Branch
  permissions reuse server RBAC: `server.versioning.manage` for branch create/merge/delete/run and
  `server.files.write` for branch worktree edits.
- OWNER-STATED (OD-v8.6-5, resolves Unknown I): the maximum size for `server-icon.png` and any single
  Git-tracked **Class B** file is strictly **1 MiB (1,048,576 bytes)**. Anything larger is rejected at
  `Save & Commit` and during `.mrpack` Class-B staging with
  `OversizedGitTrackedFileError (max 1 MiB)`; large binary assets belong in Class A CAS or Class E.
- OWNER-STATED (OD-v8.6-6, resolves Unknown J): the `P5` credential is a **GitHub fine-grained
  Personal Access Token** (`Contents: Read and Write`, `Metadata: Read-only`, scoped to the single
  target private repository) over HTTPS, OR a per-server **Ed25519 SSH Deploy Key** with write access
  over `ssh://git@github.com/<owner>/<repo>.git`. No multi-tenant GitHub App is required. Credentials
  are encrypted at rest with AES-256-GCM (`modules/storage/`) and injected through a transient
  `GIT_ASKPASS` helper or `GIT_SSH_COMMAND`, never embedded in `.git/config` URLs.
- OWNER-STATED (OD-v8.6-7, resolves Unknown L): each branch has its own isolated
  `git worktree` under `.onx/worktrees/<branch>`, so switching branches preserves that branch's
  uncommitted edits. Merging into or from a branch with uncommitted worktree changes is strictly
  refused (`HTTP 409 DirtyWorktreeError`) until **Save & Commit** or **Discard Uncommitted Changes**.
  Deleting a branch with an active running container is refused (`HTTP 409 BranchRuntimeActiveError`)
  until the container is stopped.
- OWNER-STATED (OD-v8.6-8, locks all remaining P5.5 operational constants):
  1. **Legacy Forge Java floor:** `1.17.1` -> Java **16** (runs on `eclipse-temurin:17-jre`);
     `1.18.x`-`1.20.1` -> Java **17**; `1.20.5`-`1.21.11` -> Java **21**; `26.1+` -> Java **25**;
     resolved deterministically from Mojang `version_manifest_v2.json ->
     javaVersion.majorVersion`, mapped to Temurin `8`, `17`, `21`, or `25`.
  2. **LEC/CAS eviction:** reference-counted against every active server's `onx-jars.lock.json`
     (all branches and pinned snapshots). Unreferenced LEC trees and CAS blobs older than **7 days**
     are pruned only on explicit admin action (**"Clean Unused Cache"**) or the weekly maintenance
     task, under the host-wide storage lock.
  3. **Class-C snapshot retention:** keep the last **10** unpinned Class-C snapshots per server;
     `pinned = True` snapshots (an active upgrade rollback window) are never pruned until unpinned.
  4. **`SET_MERGEABLE_ARRAY_KEYS` default set:** exactly
     `("server.properties", "initial-enabled-packs")` and
     `("server.properties", "initial-disabled-packs")`. Every other scalar array in every format uses
     strict order-preserving sequence comparison (OD-v8.5-7).
  5. **Modrinth batch chunking/rate limit:** chunk SHA-512 arrays at **200 hashes per request** for
     `POST /v2/version_files` and `POST /v2/version_files/update`; honor `X-Ratelimit-Remaining` /
     `X-Ratelimit-Reset` with exponential backoff on `HTTP 429`.
  6. **`install_optional_server_files`:** stored per server at
     `onx-jars.lock.json -> modpack.install_optional_server_files` (default `true`), toggled by a
     checkbox in the Modpack Install Wizard.
  7. **Pinned upgrade rollback window:** indefinite until **"Confirm Upgrade & Unpin Rollback
     Backup"**, with a UI reminder badge after **72 hours** of healthy uptime.
- Superseded in mechanism by v8.6: the `P6` governance block (OD-v8.6-1); the P7 placeholder
  (OD-v8.6-2); "Simple -> Advanced mechanics UNKNOWN" (OD-v8.6-3); branch concurrency/resource/
  permission unknowns (OD-v8.6-4); "oversized threshold UNKNOWN" (OD-v8.6-5); "GitHub credential
  Unknown J" (OD-v8.6-6); "dirty worktree PROPOSED/Unknown L" (OD-v8.6-7); and the seven open P5.5
  operational constants (OD-v8.6-8).
- Out of scope and still deferred: the separate D11 testing-system rework and its optional strict
  merge gate (Unknown O). Nothing else is deferred.

## Revision log v8.4 -> v8.5 (owner decisions 2026-11-11 — Second Red-Team Remediation & Final Contract Lockdown)

A second independent Red-Team audit re-tested v8.4, including live execution of the Allow-list v2.1
regexes in Python. It found 8 defects (`OD-v8.5-1` .. `OD-v8.5-8`). Each is applied below and in every
active normative section; historical revision logs keep their original text. Allow-list v2.1 is
superseded by **Allow-list v2.2**.

- OWNER-STATED (OD-v8.5-1, P0 security; SUPERSEDES OD-v8.4-3 for `.pem` and `voicechat/` in Class B):
  cryptographic key material and voicechat secrets MOVE from Class B to Class C. v8.4 classified
  `plugins/floodgate/key.pem`, `plugins/**/*.pem`, and `voicechat/voicechat-server.properties` as
  Class B, which is committed to Git and pushed to GitHub in P5 — permanently leaking live
  authentication keys and voice-chat server secrets into commit history. In Allow-list v2.2: `pem` is
  removed from the `CLASS_B_CONFIG_ALLOWLIST_REGEX` `plugins/` extension list, and the
  `|voicechat/...` alternative is removed from `CLASS_B_CONFIG_ALLOWLIST_REGEX`. `CLASS_C_LIVE_STATE_REGEX`
  gains `(?:plugins/[^/]+|config)/(?:[^/]+/)*[^/]+\.(?:pem|key|p12|pfx|jks|keystore)` and
  `voicechat/(?:[^/]+/)*[^/]+\.(?:properties|conf|json|yml)`. Class C is never committed and never
  pushed (OD-v8.4-1), is never overwritten or deleted on live refresh/restart (D-I), and is preserved
  in the host-only Out-of-Band Class-C Snapshot Store, so this satisfies survival AND secrecy
  simultaneously. A **pre-commit secret/private-key guard** is added to the D-E `Save & Commit`
  validator: staged Class-B text files are scanned for PEM headers
  `-----BEGIN [A-Z0-9 ]*KEY-----` and any `.pem`/`.key`/`.p12`/`.pfx`/`.jks`/`.keystore` extension is
  rejected with `SecretFileInGitForbiddenError`.
- OWNER-STATED (OD-v8.5-2, P1 regex bug): the E-denylist nested-jar negative lookahead only exempted
  single-level `shaderpacks/[^/]+\.jar\Z|resourcepacks/[^/]+\.jar\Z`, so
  `shaderpacks/sub/Iris.jar` and `resourcepacks/sub/deep/Pack.jar` were captured by
  `CLASS_E_DENYLIST_REGEX` at Step 4 before reaching `CLASS_A_CAS_BINARY_REGEX` at Step 6, and were
  wrongly classified Class E. The lookahead alternative is now
  `(?:shaderpacks|resourcepacks)/(?:[^/]+/)*[^/]+\.jar\Z`, matching the nested-jar CAS regex exactly,
  so nested jars under those roots fall through to Class `A-CAS`.
- OWNER-STATED (OD-v8.5-3, P1 rollback integrity; amends ND-6/D-I and the Simple-mode pipeline):
  rollback is an **atomic triad**, never a jar-only revert. Automatic rollback on Health Gate failure
  and manual Emergency Rollback both restore, from the Refresh Journal: (1) Class A + Class B — re-export
  `previous_main_sha` (Advanced) or restore the previous Simple staging root; (2) Class C — restore the
  exact `class_c_snapshot_id` captured immediately before the refresh/upgrade; (3) Class E — restore the
  pinned `pre_upgrade_backup_id` world/runtime snapshot. A plugin that migrated `userdata/`,
  `regions.yml`, or `saves.yml` before failing therefore cannot be left with post-upgrade state under a
  pre-upgrade jar. The `class_c_snapshot_id` artifact stays pinned for the whole emergency-rollback
  window, alongside `pre_upgrade_backup_id`, until the operator explicitly clicks **"Confirm Upgrade &
  Unpin Rollback Backup"**.
- OWNER-STATED (OD-v8.5-4, P1 Simple-mode contract): Simple mode is explicitly Git-free end to end. A
  Simple server has no `.git` and no worktrees; `/versioning/*` stays blocked with
  `HTTP 409 ServerModeVersioningDisabledError` (D1). Its source of truth for modpacks, loader
  provisioning (LEC), and 1-Click Safe Upgrades is `<server_root>/.onx-manager/onx-jars.lock.json`
  (Format 2.1: installed Class-A CAS binaries, `lec.key`, `modpack` metadata, and
  `base_overrides: dict[relpath, sha256]` into the host CAS). Refresh/upgrade uses a **5-step
  Git-free staging pipeline** into the sibling `<server_root>.staging/`: (1) quiesce the container and
  snapshot Class E (`pre_upgrade_backup_id`) + Class C (`class_c_snapshot_id`) + write the on-disk
  Refresh Journal; (2) 3-way merge each Class-B file using ancestor B from
  `onx-jars.lock.json -> base_overrides` in the CAS, current O from the live root, and target T from the
  new pack, writing the merged tree and updated lockfile into `<server_root>.staging/`; (3) materialize
  Class-A binaries from CAS and attach the LEC via reflink or plain copy (never hardlink); (4) inject
  Class D LAST (`eula.txt`, `user_jvm_args.txt`, Class-D `server.properties` keys; assert no `run.sh`);
  (5) preserve/move live Class E and Class C into the staged root (world data keeps its inode), atomically
  swap with `os.replace`, start the container, run the 4-step Health Gate, and on failure restore the
  previous root + `class_c_snapshot_id` + `pre_upgrade_backup_id` as one atomic triad.
- OWNER-STATED (OD-v8.5-5, P1 filesystem security): path safety splits into two functions with distinct
  contracts. `validate_canonical_relpath(path: str) -> str` is pure lexical (NFC, no NUL/newline/CR/
  backslash/colon, no absolute/empty/`.`/`..`/trailing-dot-or-space segment, canonical POSIX, case-fold
  collision rejection) and is used at Step 0 of classification and schema validation; it takes no
  `export_root`. `resolve_safe_disk_path(root_dir, rel_path, *, allow_create_parents=False)` is
  MANDATORY for every filesystem read, write, copy, delete, or archive extraction that touches a
  worktree, staging tree, export root, or server directory: it validates the relpath, realpaths and
  asserts `root_dir`, walks each segment with `os.lstat()` and raises `SymlinkEscapeError` on
  `stat.S_ISLNK`, opens/creates with `os.O_NOFOLLOW` where supported, and asserts the final realpath is
  strictly inside the real root. An `os.path.realpath` check alone leaves a TOCTOU window; the
  per-segment `lstat` walk plus `O_NOFOLLOW` closes it.
- OWNER-STATED (OD-v8.5-6, P1 container hardening): `Container uid` is no longer UNKNOWN, and an
  explicit Docker security contract is normative for `DockerProvider`. FACT: today `docker.py` builds
  `create_args` at `:412`; `--network` at `:416`; `--label` ownership labels at `:419-423`; published
  ports at `:434-460`; `--memory` at `:464`; `--cpus`/`--cpuset-cpus` at `:468-470`; a single
  `-v <host>:/data -w /data` mount at `:475`; and `--user uid:gid` at `:483` for non-itzg images
  (itzg images instead get `PUID`/`PGID` env at `:480-481`). There is no `--cap-drop`,
  `--security-opt`, `--pids-limit`, `--privileged`, `--read-only`, or `docker.sock` anywhere in
  `backend/app` (0 matches). The normative contract: (1) every server/branch/test container runs
  non-root (`--user uid:gid`, default host panel `os.getuid():os.getgid()` if non-zero else
  `1000:1000`, never `0:0`, matching `/data` ownership); (2) always pass
  `--security-opt=no-new-privileges:true` and `--cap-drop=ALL`; (3) never mount
  `/var/run/docker.sock`, the host Git repo, the host SHA-256 CAS, or the host LEC — only the isolated
  exported `/data` bind mount; (4) always enforce `--memory`, `--cpus`, and `--pids-limit=512`
  (configurable per server).
- OWNER-STATED (OD-v8.5-7, P1 merge correctness; SUPERSEDES OD-v8.4-10 for scalar arrays): arrays of
  scalars in `.json`, `.yml/.yaml`, and `.toml` are **ordered atomic sequences** by default
  (`O == B -> T`; `T == B -> O`; `O == T -> O`; else conflict at that key path). Set-merge
  (`O + (T - B) - (B - T)`) is applied only when the `(file_relpath, dotted_key)` pair is listed in the
  curated `SET_MERGEABLE_ARRAY_KEYS` allow-list. Unknown arrays are never set-merged, so priority
  chains, rule evaluation order, MOTD lines, and load-order lists are not silently reordered and
  duplicates are not silently dropped.
- OWNER-STATED (OD-v8.5-8, P1 phase readiness; supersedes "P5.5 READY FOR BUILD after P2"): the header,
  Phase Table, and P5.5 state design-complete + release-gated, with a **strict dependency order**.
  `P5.5` executes AFTER `P2`, `P3`, and `P4` (P2: CAS, Lockfile Format 2.1, Allow-list v2.2, LEC/Clean
  Export hooks; P3: Class-C Snapshot Store, 3-way/key-level merge engine, Refresh Journal; P4: isolated
  branch test runs, Port Sets, quiescent Data Templates; P5.5: `.mrpack`/CurseForge installer, loader
  provisioners, batch Modrinth compatibility matrix, 1-Click Safe Upgrade wizard). `P5` and `P5.5` may
  be built in either order once `P4` lands. `P1-P5.5` are DESIGN-COMPLETE; production release gating
  requires the phase verification suites (the former open pre-build prototypes become mandatory
  in-phase integration gates).
- Allow-list v2.2 is the normative classifier (`### Allow-list v2.2 (normative)`); all v8.5 sections
  reference it. It embeds both `validate_canonical_relpath` and `resolve_safe_disk_path`.
- Lockfile schema is unchanged at **Format 2.1** (OD-v8.4-6); Simple mode now formally depends on it
  (OD-v8.5-4). `SET_MERGEABLE_ARRAY_KEYS` is versioned with the merge engine, not the lockfile.
- Superseded in mechanism by these decisions: `plugins/**/*.pem` and `voicechat/**` in Class B
  (OD-v8.5-1); the single-level `shaderpacks`/`resourcepacks` jar lookahead (OD-v8.5-2); jar-only
  rollback (OD-v8.5-3); implicit Simple-mode export/merge (OD-v8.5-4); optional `export_root`
  containment and realpath-only validation (OD-v8.5-5); UNKNOWN container uid and implicit sandboxing
  (OD-v8.5-6); unordered scalar arrays (OD-v8.5-7); "P5.5 after P2" (OD-v8.5-8).

## Revision log v8.3 -> v8.4 (owner decisions 2026-11-11 — Red-Team Security & Architectural Hardening)

- OWNER-STATED (OD-v8.4-1, supersedes D-A/D-I and P3 regarding `live-state`): the `live-state` Git
  branch is ELIMINATED. Class C never enters Git: there is no `refs/heads/live-state`, no
  `git merge` of Class C, and no Class-C data in `main` or any feature branch (so banned-IP and
  player PII can never be pushed to GitHub in P5). Class C is snapshotted out of band into a
  host-managed Class-C Snapshot Store indexed in the database by
  `(server_id, snapshot_id, created_at, manifest_sha256)` with blobs in the SHA-256 CAS, and is
  viewed/edited/restored through a Live State Files mode that targets the live server files
  (with `save-all`/RCON reload or a stopped server), never a worktree. `main` and feature branches
  contain only `onx-jars.lock.json` and Class B files plus the panel-generated `.gitattributes`.
- OWNER-STATED (OD-v8.4-2, supersedes the ND-3 attach order and the hardlink fallback): hardlinks
  are FORBIDDEN when materializing CAS blobs, LEC trees, or Data Templates into an export root,
  because a shared inode lets any container or malicious mod rewrite host-cached loader files
  (`unix_args.txt`, loader jars) for every server and branch container. Permitted attachment is a
  probe-verified reflink (`cp --reflink=always`) or a plain copy under a host-wide storage copy
  lock with `free >= required_bytes * 1.10` (else `InsufficientStorageError`), after deleting any
  partial destination. A persisted LEC entry contains ONLY `libraries/**` or `.fabric/server/**`;
  builder-root `run.sh`, `run.bat`, `user_jvm_args.txt`, `eula.txt`, installer artifacts, and the
  root `server.jar` are deleted before snapshotting. Clean Export is a fixed 5-step order:
  (1) member-by-member `git archive` extraction, (2) CAS materialization, (3) LEC attach,
  (4) optional Class-E Data Template overlay, (5) Class D injection LAST.
- OWNER-STATED (OD-v8.4-3, supersedes Allow-list v2): mandatory Step 0
  `validate_canonical_relpath()` (NFC; no NUL/newline/CR/backslash/colon; no absolute, empty,
  `.`/`..`, or trailing-dot/space segments; canonical POSIX form; realpath containment; case-fold
  collision rejection) runs before any classification, lockfile parse, staging, or export.
  Allow-list v2.1 adds the Step-1 `HOSTILE_EXECUTABLE_QUARANTINE_REGEX` for executables inside
  `config/`, `defaultconfigs/`, `kubejs/`, `scripts/`, `datapacks/`, `global_packs/`,
  `patchouli_books/`, `schematics/`, `blueprints/`, `structures/`, and `structured-config/`;
  replaces every `$` with `\Z`; adds real plugin paths (`plugins/Skript/**/*.sk`,
  `plugins/Denizen/**/*.dsc`, `plugins/floodgate/key.pem`, `voicechat/**`); promotes
  `schematics|blueprints|structures/*.nbt` to CAS; fixes `plugins/*/cache/**` and plugin binary
  data to Class E; and keeps 7 explicit class-D keys plus the `management-server-*` prefix.
  Executable pack scripts trigger a mandatory UI Executable Script Review Warning.
- OWNER-STATED (OD-v8.4-4, amends D-D): restart snapshot comparison uses the canonical parsed AST,
  never raw bytes. `server.properties`, `bukkit.yml`, `spigot.yml`, `pufferfish.yml`, `purpur.yml`,
  `commands.yml`, `help.yml`, `permissions.yml`, and `config/paper-*.yml` are never auto-promoted to
  `dynamic-class-c`. A dynamic-C file returns to Class B when its canonical structure matches
  `main`, or when the operator clicks "Reset to Class B (Track from main)".
- OWNER-STATED (OD-v8.4-5, amends D-I/D-J/ND-6): world clones are quiescent (`save-off`,
  `save-all flush` + confirmation, clone, `save-on` in a mandatory `finally`; fail closed and
  require a stopped container when RCON cannot confirm within 30s). Long operations run
  asynchronously (new `modules/operations/`), land in a target directory only after a fsynced
  `.onx-complete.json` marker (file and parent directory), and renew their DB lease heartbeat every
  10s with a monotonically increasing fencing token. One unified crash-safe Refresh Journal
  (`journal_id, server_id, phase, previous_main_sha, target_main_sha, pre_upgrade_backup_id,
  class_c_snapshot_id`) covers refresh and upgrade; staged trees switch by atomic
  `os.replace`/rename, never unlink + symlink, and the live `world*` keeps its inode.
- OWNER-STATED (OD-v8.4-6): the clean base-pack override set (B) is persisted in the CAS and
  recorded in `onx-jars.lock.json` as `base_overrides{path: sha256}`, so Simple (no Git history) and
  Advanced both have a deterministic 3-way ancestor. `base_overrides` is replaced when an upgrade
  to T succeeds. This is lockfile Format 2.1.
- OWNER-STATED (OD-v8.4-7, amends D-G): every git invocation passes
  `-c core.hooksPath=/dev/null -c core.fsmonitor=false -c protocol.allow=user
  -c protocol.file.allow=never -c protocol.ext.allow=never -c core.symlinks=false
  -c core.attributesFile=/dev/null -c filter.lfs.smudge= -c filter.lfs.process=
  -c filter.lfs.clean=` before the subcommand. Remote URLs must match
  `https://github.com/<owner>/<repo>(.git)?` or `ssh://git@github.com/<owner>/<repo>(.git)?` and
  may never contain `ext::`, `fd::`, `file::`, userinfo, or newlines. `git archive` always uses
  `--no-worktree-attributes` and the Step-1 member loop; the panel `.gitattributes` scrubber also
  strips `working-tree-encoding` and `export-subst`.
- OWNER-STATED (OD-v8.4-8): the download host allow-list is validated on the initial URL and after
  every redirect (max 5 hops) and adds `maven.quiltmc.org`, `meta.quiltmc.org`,
  `fill.papermc.io`, `fill-data.papermc.io`, `piston-meta.mojang.com`, `piston-data.mojang.com`,
  `libraries.minecraft.net`, plus the GitHub release redirect hosts
  (`release-assets.githubusercontent.com`, `objects.githubusercontent.com`,
  `github-releases.githubusercontent.com`) only on a redirect from
  `github.com/<org>/<repo>/releases/download/`. Jars arriving via `overrides/mods/**`,
  `server-overrides/mods/**`, `overrides/plugins/**`, or `server-overrides/plugins/**` are
  SHA-512-queried and dropped (`skipped_client_override_jar`) when Modrinth reports
  `environment == "client_only"`. CurseForge never ships an embedded key: a missing
  `curseforge_api_key` is `CurseForgeApiKeyMissingError`, and `downloadUrl: null` / CDN 401/403 is
  `blocker: manual_download_required` (never a silent skip), cleared by an operator drag-and-drop
  upload that is hash/size verified.
- OWNER-STATED (OD-v8.4-9): Quilt uses `GET .../loader/{mc}/{loader}/server/json` (the `/server/jar`
  endpoint is 404), downloads its `libraries[]` and the Mojang `server.jar` for `inheritsFrom`, and
  generates `libraries/org/quiltmc/quilt-loader/{loader}/unix_args.txt`; launch is the argfile
  command. Forge is supported only for `1.17.1 <= mc <= 1.20.1` (`UnsupportedForgeVersionError`
  otherwise). Paper Fill v3 resolves version groups, reads the full `/builds` list, filters
  `channel == "STABLE"`, and uses BETA/ALPHA only when `allow_experimental_paper_builds=True`.
  LEC build asserts a non-empty `unix_args.txt` before writing `.onx-complete.json`.
- OWNER-STATED (OD-v8.4-10): upgrade lookups are hash-only (never slug matching); `environment`
  (not `server_side`) is read on Version objects; a BFS over `dependency_type == "required"`
  dependencies (depth <= 8, <= 500 projects) resolves transitive requirements; `unresolved`
  becomes the non-blocking `warning: unresolved_carried` (Paper/SpigotMC/Hangar plugins stay in the
  plan and are tested in the isolated branch container), and only real incompatibilities block.
  Merge codecs: structured key-level for `.json`, `.yml/.yaml`, `.toml`, `.properties`; set-aware
  scalar arrays preserving O order; object arrays matched by `id|name|modid|Id` and recursively
  merged; textual diff3 for `.json5`, `.snbt`, `.cfg`, `.conf`, `.js`, `.zs`, `.sk`, `.dsc`,
  `.mcfunction`, `.txt`.
- OWNER-STATED (OD-v8.4-11): the Health Gate is race-free and 4-step: (1) process-scoped stdout
  from `container_started_at` matching `^\[[^\]]*INFO\]: Done \([0-9.]+s\)! For help, type "help"`,
  (2) TCP accept plus RCON `save-all flush` and `level.dat` mtime >= start, (3) gzipped big-endian
  NBT `Data["DataVersion"] >= expected` (or `Version.Id == target_mc`), (4) optional dimension smoke
  check. `BackupModel.pinned` ships in P5.5 (not P7); the pre-upgrade backup stays pinned AFTER the
  gate passes because chunk migration is lazy, and the UI shows "Upgrade Active — Pre-Upgrade
  Rollback Snapshot is Pinned" with Confirm & Unpin and Emergency Rollback.
- Lockfile schema: **Format 2.1** = Format 2 plus `base_overrides` (OD-v8.4-6). Format 2 and
  Format 1 remain unsupported and are never silently upgraded.
- Superseded in mechanism by these decisions: the `live-state` Git branch (OD-v8.4-1), the hardlink
  LEC/CAS attach and LEC-last order (OD-v8.4-2), Allow-list v2 (OD-v8.4-3), raw-byte D-D comparison
  (OD-v8.4-4), the v8.3 pinned backup/Health Gate (OD-v8.4-5/OD-v8.4-11), the 5-key class-D set
  (OD-v8.4-3), and `mods/*.jar` in Class E (already superseded by ND-1, now explicit in
  Allow-list v2.1). All historical logs below keep their original text with annotations.

## Revision log v7 -> v8 (owner decisions 2026-11-09)

- OWNER-STATED (D-A/D-B): replaced the v7 tracked-vs-ignored model with five classes (A code,
  B user-edited config, C live-owned state, D panel-owned settings, E never tracked) and an
  explicit allow-list. Code jars move to a sha256 CAS with a Git lockfile; class C syncs to the
  dedicated `live-state` branch; main never receives automatic commits.
  [SUPERSEDED in mechanism by v8.4 OD-v8.4-1: Class C never enters Git; out-of-band snapshot store.]
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
  [SUPERSEDED in mechanism by v8.4 OD-v8.4-1: the P3 `live-state` branch is replaced by the
  out-of-band Class-C Snapshot Store plus a Live State Files mode; Class C never enters Git.]
- Added "External review disposition" and "Prototype before build"; external claims are tagged
  ASSUMPTION (external, unverified). No existing FACT citation was changed.

## Revision log v8 -> v8.1 (prototype report merge, 2026-11-10)

- PROTOTYPE-REPORT: merged prototype verification report as normative rules tagged PROTOTYPE-REPORT.
- Allow-list v1 embedded with corrected `$` regex anchors.
- OWNER-STATED (OD-1): `onx-jars.lock.json` kept as the class-A lockfile pointer (evaluation step 2); kept distinct from class-B user config.
- OWNER-STATED (OD-2): plugin binary data (`*.db`, `*.sqlite`, `*.dat` and similar under `plugins/`) is class E; excluded from Git and `live-state`, covered by the existing backup system, and included in optional Data Templates.
  [SUPERSEDED in mechanism by v8.4 OD-v8.4-1: the `live-state` branch no longer exists; binary plugin data stays class E and is covered by the Class-C Snapshot Store and backups.]
- FACT / OWNER-STATED (OD-3): `eula.txt` is generated at export time (class-D-like), not tracked. `write_eula` (`jar_service.py:987-1010`) writes `eula=true`, called from `create_server.py:187`; test deployments write it at `config_writer.py:87-89`; backups already list it in `CONFIG_FILES` at `backup_orchestrator.py:27-34`. The P2 clean export must write it into the exported root.
- OWNER-STATED (OD-4): built-in always-C subtree patterns in Allow-list v1 replace the small manual override list; contents remain an implementation choice; dynamic C reclassification is recorded in a per-server DB registry (not inside the server tree).
- OWNER-STATED (OD-5): introduced PROTOTYPE-REPORT evidence tag; D-B / prototype 3 (real Paper boot, allow-list derivation, 120 MB GitHub push) stay OPEN; ext4 and ZFS reflink behavior stay UNVERIFIED. Embedded report rules are normative text tagged PROTOTYPE-REPORT, never FACT.
- OWNER-STATED (OD-6): `mods/*.jar` and mod configs are out of scope (Lane E); they fall to class E via catch-all. Supporting mod loaders in Advanced mode later will require promoting them to class A/B before enabling Advanced mode so clean export does not boot without mods. Optional modpack support for Simple servers is recorded as a separate Lane E idea.
  [SUPERSEDED in mechanism by v8.4 OD-v8.4-3 (and by ND-1): `mods/**/*.jar` is class A, mod configs are class B, and mod loaders/modpacks are core architecture in both modes.]
- OWNER-STATED (OD-7): header updated to closed and ready for build for P1-P5; P6 (D9) remains blocked on a D2 governance decision record plus a superseding ADR.
- No existing FACT citation was changed and no owner decision was altered.

## Revision log v8.1 -> v8.2 (owner decisions 2026-11-10)

- OWNER-STATED (NOD-1/OD-9): `.gitattributes` is panel-generated at commit time (class-D-like), written into the repo by the panel with the D-K eol/filemode rules; it is never taken from the server directory. A `.gitattributes` found in the server tree is class E (catch-all) and is removed by the D-G sanitizer. It is not added to any allow-list regex. `CLASS_B_CONFIG_ALLOWLIST_REGEX` no longer contains `onx-jars.lock.json`; evaluation step 2 classifies it as the class-A lockfile.
- OWNER-STATED (NOD-2): `*.dat` under `plugins/` stays class E (OD-2); text player data is class C and `playerdata` joins the class-C directory list.
- OWNER-STATED (NOD-3): a `.jar` anywhere except root `*.jar` and `plugins/*.jar` is class E; `.class`, `.so`, `.dll`, `.nbt` are class E. Because E is evaluated before C, these are E even inside class-C subtrees.
  [SUPERSEDED in mechanism by v8.4 OD-v8.4-3: Allow-list v2.1 promotes `mods/**/*.jar` to class A, `schematics|blueprints|structures/*.nbt` to CAS, and quarantines hostile executables under config roots.]
- OWNER-STATED (NOD-4): `server-icon.png` is class B and is tracked only below the oversized-binary threshold; the threshold remains Unknown I.
- OWNER-STATED (NOD-5): `plugins/*/lib/*.jar` and other nested jars are class E (NOD-3); nested config directories under `config/` are class B.
- OWNER-STATED (NOD-6): `.csv` is class E; `csv` is removed from the class-C file-name alternative and added to the class-E extension list. Any unknown extension is class E (catch-all).
- OWNER-STATED (NOD-7): `server.properties` normalization discards all comments and keeps only sorted `key=value` lines. Real-boot validation remains OPEN.
- No other owner decision, phase order, or FACT citation changed.

## Revision log v8.2 -> v8.3 (owner decisions 2026-11-11 - modpacks, LEC, Allow-list v2, 1-Click Safe Upgrade)

- OWNER-STATED (ND-1, supersedes OD-6): mod loaders (Fabric, Quilt, NeoForge, Forge) and `.mrpack`
  modpacks are core architecture for BOTH modes, not Lane E. `mods/**/*.jar` is promoted from
  class E/catch-all to class A (CAS + lockfile); mod configs and pack scripts are class B. The
  OD-6 "mods are out of scope" rule and the Lane E mod-loader note are retired.
- OWNER-STATED (ND-2): `onx-jars.lock.json` becomes **Format 2** (format, mc, loader, lec, modpack
  block, files[] with sha256/sha512/sha1/size/optional/env_server/origin/project_id/version_id).
  Format 1 lockfiles are not migrated; existing servers are deleted (D8).
- OWNER-STATED (ND-3): introduce the **Loader Environment Cache (LEC)**. A Clean Export is
  `git archive` + CAS materialization + class-D injection + optional class-E Data Template + a LEC
  tree attached by reflink/hardlink/copy. A Clean Export MUST boot offline (no Maven, Modrinth, or
  Mojang access at container start).
  [SUPERSEDED in mechanism by v8.4 OD-v8.4-2: hardlink is forbidden, LEC is attached third and
  class D is injected last in the fixed 5-step Clean Export order.]
- OWNER-STATED (ND-4): NeoForge and legacy Forge (<= 1.20.1) launch from the exported root as
  `java @user_jvm_args.txt @libraries/.../unix_args.txt nogui`; `run.sh`, `run.bat`, and
  `ServerStarterJar` are never executed. `user_jvm_args.txt` is panel-generated (class-D-like) from
  panel memory/JVM settings. The LEC tree is attached LAST and `.mrpack` overrides may never write
  `libraries/**` or `.fabric/**`.
  [SUPERSEDED in mechanism by v8.4 OD-v8.4-2: the LEC is attached at Step 3 and class D is injected
  LAST at Step 5, so `run.sh`/`run.bat`/`eula.txt`/`user_jvm_args.txt` can never be clobbered.]
- OWNER-STATED (ND-5): `.mrpack` (Modrinth Index `formatVersion` 1) is the normative pack format;
  dedicated-server filtering uses `env.server`, override precedence is `files[]` -> `overrides/` ->
  `server-overrides/` (never `client-overrides/`), with the quarantine, path, and download-host
  allow-lists in the new normative section. CurseForge zips are an adapter into the same
  `InstallPlan`, not a second store.
- OWNER-STATED (ND-6): add the deterministic 1-Click Safe Upgrade engine (Modrinth batch
  `/v2/version_files` and `/v2/version_files/update`, compatibility-matrix blockers, 3-way config and
  script merge, disposable Data Template branch test, one-way `level.dat` `DataVersion` safety,
  pinned pre-upgrade backup, Health Gate).
- OWNER-STATED (ND-7): Allow-list v1 -> **Allow-list v2**: class A jars include `mods/**/*.jar`;
  non-classpath pack binaries (`shaderpacks/**`, `resourcepacks/**`, `kubejs/assets/**`,
  `patchouli_books/**`, `structured-config/**`, `blueprints/**`, `schematics/**`) go to CAS;
  `kubejs/**`, `defaultconfigs/**`, `scripts/**`, `datapacks/**` are class B; Paper 26.1+
  `world/dimensions/**` and world sub-trees are class E; hostile `.jar`/`.class` outside the
  classpath roots is quarantined.
- OWNER-STATED (ND-8): the Java floor is resolved from Mojang `javaVersion.majorVersion` or Paper
  Fill v3 (`version.java.version.minimum`), never from Fabric's `launcherMeta.min_java_version`.
- OWNER-STATED (ND-9, class-D keys): the panel-owned `server.properties` key set is extended with
  `enable-query`, `broadcast-rcon-to-ops`, and `management-server-*` in addition to the five v8 keys.
  [SUPERSEDED in mechanism by v8.4 OD-v8.4-3: the authoritative set is the 7 explicit keys
  (`server-port`, `query.port`, `rcon.port`, `rcon.password`, `enable-rcon`, `enable-query`,
  `broadcast-rcon-to-ops`) plus the `management-server-*` prefix, never a "five v8 keys" model.]
- No other existing owner decision, phase order, or FACT citation is changed; P1-P5 stay closed and
  P6 (D9) stays blocked exactly as recorded.

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
  allow-list, Class-C isolation, and key-level config merge replace the v7 tracked-vs-excluded
  proposal and the proposed starting exclusions. [The former Class-C Git branch mechanism is
  SUPERSEDED in mechanism by v8.4 OD-v8.4-1.]
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
- D7 (mechanics resolved by OD-v8.6-3): Mode conversion is wanted later and should be easy, not
  in P1. **Advanced -> Simple** copies `main` into a brand-new Simple server (the original remains
  untouched until the operator deletes it). **Simple -> Advanced is strictly IN-PLACE** on the same
  `server_id`, preserving UUID, ports, backups, and history. In P1 there is no in-place flip.
  OWNER-STATED (v7): the Advanced -> Simple result has no Git or GitHub relation and also serves
  developers who prefer working by hand.
- D8: All existing servers are test/dummy data and the project has no users; the owner deletes
  them. Therefore there is no migration of existing servers and no deriving mode from existing
  commits.
- D9 (unblocked by OD-v8.6-1): All servers are containerized, so Local providers
  (LocalLinux/LocalWindows, tmux) are removed in `P6` (Docker-only). `ADR-0015`'s retention of the
  local providers is superseded directly by this specification (v8.6); no separate D2 decision
  record or ADR is required. `P6` runs after `P5`/`P5.5`; `P7` backups follow.
  OWNER-STATED (v7/v8 D-M): Local providers are removed; Docker is the only runtime and no server
  runs without Docker. Windows-hosted servers run as Docker containers too. Local-provider unit
  tests are temporary and are deleted with the providers in P6.
- D10-v5: Because Advanced mode uses real Git and `git worktree`, commit-from-worktree is native
  `git add` + `git commit` triggered by "Save & Commit". Merging branches uses native `git merge`,
  which provides real three-way merge and conflict detection, replacing the custom manifest-only
  `MergeCommitsCommand` limitation.
  OWNER-STATED (v8 D-E, codecs pinned by OD-v8.4-10): native `git merge` is allowed only for
  code-class files in the repo; config merges are STRUCTURED KEY-LEVEL only for formats with
  lossless parsers (`.json` via `json`, `.yml/.yaml` via PyYAML safe AST, `.toml` via `tomllib` +
  `tomli_w`, `.properties` via the canonical key=value parser); `.json5`, `.snbt`, `.cfg`, `.conf`,
  `.js`, `.zs`, `.sk`, `.dsc`, `.mcfunction`, and `.txt` use line-based 3-way `diff3` (never lossy
  JSON conversion, which corrupts SNBT type suffixes and JSON5 literals); results are exported only
  after validation.
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
  - OWNER-STATED (D-A, class A code): executable jars stored OUTSIDE Git in a content-addressed
    store keyed by sha256; Git tracks only a lockfile with path, sha256, size, and source; the
    tracked pointer is `onx-jars.lock.json` (class-A lockfile, evaluation step 3; it is not a
    class-B user config). Class A covers the root server jar, `plugins/*.jar`, `mods/**/*.jar`, and
    the non-classpath pack CAS binaries `shaderpacks/**`, `resourcepacks/**`, `kubejs/assets/**`,
    `patchouli_books/**`, `schematics/**`, `blueprints/**`, `structures/**`, and
    `(datapacks|global_packs|kubejs/data)/**/structures/**/*.nbt` (OD-v8.4-3/OD-v8.7-4).
    Replaced from `main` on live restart.
  - OWNER-STATED (D-A, class B user-edited config): for example `plugins/<name>/` configs the
    plugin does not rewrite and root `server-icon.png`. In Git; replaced from `main` on restart.
    `server-icon.png` is tracked only below the 1 MiB cap (OD-v8.6-5); any other valid Class-B text
    file above 1 MiB up to 16 MiB is routed to `A-CAS` instead (OD-v8.7-15).
  - OWNER-STATED (D-A, class C live-owned state): `ops.json`, `whitelist.json`,
    `banned-players.json`, `banned-ips.json`, `usercache.json`, plugin-rewritten configs/data, and —
    since OD-v8.5-1 — all cryptographic key/keystore material
    (`plugins/*/(**)/*.{pem,key,p12,pfx,jks,keystore}`,
    `config/(**)/*.{pem,key,p12,pfx,jks,keystore}`) and voicechat server secrets
    (`voicechat/(**)/*.{properties,conf,json,yml}`). These were Class B in v8.4 and leaked into Git
    history; they are Class C now so they are never committed and never pushed while still surviving
    refresh/restart.
    Text player data under `plugins/*/playerdata/` is class C. `*.dat` under `plugins/` remains
    class E (OD-2). The live server owns Class C.
    **Class C NEVER enters Git** (OD-v8.4-1): there is no dedicated Class-C Git branch of any name,
    no Class-C ref, and no `git merge` of Class C files, so player PII (`banned-ips.json`,
    `usercache.json`, `playerdata`) can never reach a feature branch, `main`, or the GitHub remote
    in P5. Instead the panel snapshots live Class C into a **dedicated encrypted Class-C vault**
    outside Git (`<host_state_dir>/class-c-vault/<server_id>/`, AES-256-GCM, OD-v8.7-7; never the
    shared Class-A jar CAS), indexed in the database by
    `(server_id, snapshot_id, created_at, manifest_sha256)` before any
    live refresh, restart, or upgrade swap, and on demand. Operators view, edit, or restore Class C
    through a dedicated **Live State Files** view/mode in the Files UI/API that targets the live
    Class-C files directly (with `save-all`/RCON reload, or a stopped server, as appropriate),
    never through a worktree. Restart NEVER overwrites Class C. `main` never receives automatic
    commits; Save & Commit remains the only commit path to `main`/branches.
  - OWNER-STATED (D-A, class D panel-owned settings): the 7 explicit `server.properties` keys
    `server-port`, `query.port`, `rcon.port`, `rcon.password`, `enable-rcon`, `enable-query`, and
    `broadcast-rcon-to-ops`, plus every key with the `management-server-` prefix. Outside the repo;
    injected by the panel at run/export time as the authoritative final writer; never tracked.
    `eula.txt` and `user_jvm_args.txt` are also panel-generated at export time and never tracked.
  - OWNER-STATED (D-A, class E never tracked): `world*`/custom level-name, logs, cache, libraries,
    crash-reports, `.paper-remapped`, DBs, map tiles, and plugin binary data (`*.db`, `*.sqlite`,
    `*.dat` and similar under `plugins/`). They are excluded from Git, covered by the existing
    backup system, included in optional Data Templates, and never enter a Git branch. Also class E: a `.jar` outside the classpath roots
    (`plugins/*.jar`, `mods/**/*.jar`) and the CAS roots (including `plugins/*/lib/*.jar`),
    `.class`, `.so`, `.dll`, `.nbt` outside the schematic and datapack-structure roots (`schematics/`,
    `blueprints/`, `structures/`, `(datapacks|global_packs|kubejs/data)/**/structures/`), `.csv`, and
    a `.gitattributes` found in the server tree.
- OWNER-STATED (2026-11-09, D-B, v2.3 by OD-v8.7-4): classification is an EXPLICIT ALLOW-LIST:
  ignore everything by default; track only what is explicitly allowed. **Allow-list v2.3** is the
  normative list in "Allow-list v2.3 (normative)" (PROTOTYPE-REPORT). Every path first passes Step 0
  `validate_canonical_relpath()` and `open_safe_path_fd()` (OD-v8.4-3/OD-v8.7-6), and every filesystem
  touch under a root is resolved through `resolve_safe_disk_path()` (OD-v8.5-5). It was NOT derived
  from a real Paper boot; that
  derivation/validation is the in-phase P2 real-boot release gate (prototype 3), not an open design
  question. The v7 proposed exclusion list is removed as the mechanism.
- OWNER-STATED (2026-11-11, OD-v8.5-1/OD-v8.5-6, extended by OD-v8.7-3): two cross-cutting
  guarantees apply to both modes. (a) **Secrets never reach Git:** cryptographic keys and voicechat
  secrets are Class C, and the Save & Commit / push validator runs the Structured & Pattern Secret
  Scanner (OD-v8.7-3), raising `SecretFileInGitForbiddenError` for key headers, token signatures, and
  sensitive config keys, with a 1-click "Extract Secret to Panel Vault" substitution. (b) **Containers
  are hardened:** every server, branch, and test container runs non-root
  (`--user uid:gid`, never `0:0`), with `--security-opt=no-new-privileges:true`,
  `--cap-drop=ALL`, `--memory`, `--cpus`, and `--pids-limit=2048`, and mounts only its isolated
  `/data` directory — never `/var/run/docker.sock`, the host Git repo, the CAS, or the LEC.
- OWNER-STATED (2026-11-09, D-C): track `server.properties` minus class-D keys; the panel injects
  those keys. Add NORMALIZATION at Save & Commit: strip the `#Minecraft server properties` header,
  strip the `Properties.store()` timestamp line matching
  `^#\s*(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+\S+\s+\d{4}\s*$`,
  normalize CRLF to LF, remove the 7 class-D keys (`server-port`, `query.port`, `rcon.port`,
  `rcon.password`, `enable-rcon`, `enable-query`, `broadcast-rcon-to-ops`) plus the
  `management-server-*` prefix keys, and sort remaining `key=value` lines lexicographically. All
  comments are discarded by normalization; only sorted `key=value` lines are kept (OWNER-STATED
  NOD-7, 2026-11-10). This normalization is PROTOTYPE-REPORT (not yet validated against a real
  Paper boot).
- OWNER-STATED (2026-11-09, D-D, amended by OD-v8.4-4): `plugins/<name>/` defaults to class B. At
  restart, compare the **canonical parsed AST** of the live file to the last synced snapshot
  (parsed JSON/YAML/TOML/properties structure, ignoring comments, timestamps, and whitespace), never
  raw bytes; if the canonical structure differs, treat it as class C (do not overwrite, show a
  warning). `server.properties`, `bukkit.yml`, `spigot.yml`, `pufferfish.yml`, `purpur.yml`,
  `commands.yml`, `help.yml`, `permissions.yml`, and `config/paper-*.yml` are EXEMPT from automatic
  `dynamic-class-c` promotion and always stay class B with key-level merge (D-E), because
  Minecraft/Paper rewrite them on every boot. `dynamic-class-c` is not a sticky trap: the path
  returns to class B automatically when its canonical structure matches `main` on a later restart,
  or when the operator clicks **"Reset to Class B (Track from main)"** in the UI. Built-in runtime
  state files (`plugins/Essentials/warps/*.yml`, `plugins/WorldGuard/worlds/*/regions.yml`,
  `plugins/Citizens/saves.yml`) are named directly in `CLASS_C_LIVE_STATE_REGEX` and never rely on
  dynamic detection. The built-in always-C patterns live in "Allow-list v2.3 (normative)"; dynamic
  reclassification is recorded in a per-server DB registry (`dynamic-class-c`, never in the server
  tree; OD-4). Misclassification risk is covered by the P3 backup-of-replaced-files and rollback.
- OWNER-STATED (2026-11-09, D-E, precision pinned by OD-v8.4-10 and amended by OD-v8.5-1/OD-v8.5-7):
  config merge is STRUCTURED
  KEY-LEVEL for `.json`, `.yml/.yaml`, `.toml`, and `.properties`, never a textual `git merge` on live
  files; `.json5`, `.snbt`, `.cfg`, `.conf`, `.js`, `.zs`, `.sk`, `.dsc`, `.mcfunction`, and `.txt`
  use line-based 3-way `diff3` (lossy JSON conversion is forbidden: it corrupts SNBT type suffixes and
  JSON5 literals). **Scalar arrays are ordered atomic sequences by default** (OD-v8.5-7, supersedes the
  OD-v8.4-10 set rule): if `O == B` take `T`; if `T == B` keep `O`; if `O == T` keep `O`; otherwise
  flag a conflict at that key path for operator resolution. Order is preserved and duplicates are
  never silently dropped, so priority chains, rule evaluation order, MOTD lines, and load-order lists
  survive. Set merge (`O + (T - B) - (B - T)`) applies ONLY when `(file_relpath, dotted_key)` is in the
  curated `SET_MERGEABLE_ARRAY_KEYS` allow-list, whose default membership is exactly
  `frozenset({("config/paper-global.yml", "MidTickChunkTasks.worlds"), ("spigot.yml", "commands.silent-commandblock-console-worlds")})`
  (OD-v8.7-15, replacing the invalid `.properties` string keys of OD-v8.6-8); the set may be extended
  per plugin schema. Unknown arrays are never
  set-merged. Object arrays
  match by `id|name|modid|Id` and recurse. Unknown formats: live wins plus warning; unknown format
  keeps the live bytes and emits a structured warning. If parse fails: the live file stays untouched;
  parse failure on either side leaves the live file byte-identical. NEVER write conflict markers into a
  server directory. Save &
  Commit rejects config files containing conflict markers or failing to parse: the pre-commit
  validator rejects `^(?:<<<<<<<|=======|>>>>>>>)` and per-format parse failures (`yaml.safe_load`,
  `json.loads`, `tomllib.loads`, properties parser). **Structured & Pattern Secret Scanner**
  (OD-v8.5-1, expanded by OD-v8.7-3): the same validator scans every staged Class-B text file, every
  D7 conversion commit, and every push, and raises `SecretFileInGitForbiddenError` when:
  (i) it matches `-----BEGIN [A-Z0-9 ]*KEY-----`;
  (ii) it matches Discord bot tokens (`[MN][A-Za-z\d]{23,}\.[\w-]{6}\.[\w-]{27,}`), Discord/Slack
  webhook URLs (`https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]+`), GitHub
  PATs (`gh[pousr]_[A-Za-z0-9_]{36,}` or `github_pat_[A-Za-z0-9_]{22,}`), or AWS access keys
  (`AKIA[0-9A-Z]{16}`);
  (iii) a parsed YAML/JSON/TOML/Properties key whose final segment matches
  `(?i)^(?:bot[-_]?token|auth[-_]?token|access[-_]?token|refresh[-_]?token|client[-_]?secret|api[-_]?key|secret[-_]?key|private[-_]?key|webhook[-_]?url|(?:mysql|mariadb|postgres|database|db|redis|rcon|smtp)[-_.]?(?:password|pass|pwd))$`
  has a non-empty, non-placeholder literal value (not `""`, `"none"`, `"changeme"`, `"password"`, or
  `${ONX_SECRET_*}`), or the staged path ends in `.pem`, `.key`, `.p12`, `.pfx`, `.jks`, or
  `.keystore`. Such files must be classified Class C or use the substitution below, never committed.
  **Secret substitution (OD-v8.7-3):** the error response offers "Extract Secret to Panel Vault",
  which replaces the literal with `${ONX_SECRET_<KEY_NAME>}`, stores the value in the per-server
  AES-256-GCM Class-D secret store, and substitutes it back into the exported Class-B file at Clean
  Export Step 5. Branch-to-branch merge of code-class files may use
  native `git merge` in the repo, but results are exported only after validation.
- OWNER-STATED (2026-11-09, D-F, amended by OD-v8.4-2): running (live, branch, test) uses a CLEAN
  EXPORT of a pinned Git sha as the only container root; the export contains no `.git` entry. The
  editing worktree is NEVER mounted into a container. Delete `materialization_id` as a concept: the
  single run identity is the Git sha plus an optional Data Template id. Update Runtime,
  EvidenceBundle, test_runner, and promote consumers explicitly; do not retire old machinery by
  omission. A run is code sha + optional Data Template; without a template it is a fresh world from
  the seed (tests too). Template data overlays only class-E paths.
  The export order is FIXED at 5 steps (OD-v8.4-2):
  1. **Git archive (class B + lockfile):** hardened
     `git archive --format=tar --no-worktree-attributes <sha>`, extracted by an explicit Python
     `tarfile` member-by-member loop, NEVER `extractall()`. Reject any member for which
     `not member.isfile()` (so `SYMTYPE`, `LNKTYPE`, `FIFOTYPE`, `CHRTYPE`, `BLKTYPE` are rejected;
     directories are created with a safe `mkdir`), pass `member.name` through
     `validate_canonical_relpath()` and resolve the write target with `resolve_safe_disk_path()`,
     and reject `.git` entries, `libraries/**`, `.fabric/**`,
     `run.sh`, `run.bat`, and `user_jvm_args.txt`.
  2. **Class A materialization:** parse `onx-jars.lock.json` (Format 2.1), run every `files[].path`
     and every `base_overrides` path through `validate_canonical_relpath()`, resolve each destination
     with `open_safe_path_fd(export_root, path)` / `resolve_safe_disk_path(export_root, path)`
     (descriptor-relative `O_DIRECTORY|O_NOFOLLOW` containment, OD-v8.5-5/OD-v8.7-6), and materialize
     each blob from the SHA-256 CAS.
  3. **LEC attach:** if `lockfile.lec.key` is present, copy the LEC subtree to `export_root/libraries`
     or `export_root/.fabric/server`. Because Step 1 and `.mrpack` overrides deny `libraries/**` and
     `.fabric/**`, and Step 3 rewrites those subtrees from the trusted host LEC, no pack or branch
     can smuggle jars onto the loader classpath.
  4. **Optional Class-E Data Template overlay:** only Class-E paths, only from a template carrying
     the `COMPLETE` marker.
  5. **Class D injection LAST (authoritative final writer):** write `eula.txt` (`eula=true`, only if
     accepted), write `user_jvm_args.txt` from panel memory/JVM config only, inject the 7 class-D
     keys plus `management-server-*` into `server.properties`, and assert that `run.sh` and
     `run.bat` do not exist in the export root.
  Steps 1-4 attach by **probe-verified reflink or plain copy only**; hardlinks are FORBIDDEN
  (OD-v8.4-2, D-H).
- OWNER-STATED (2026-11-09, D-G, amended by OD-v8.4-7): Git is never run against a directory the
  container can write. Keep the Git directory outside the server tree. Hardened invocation contract:
  shell-free argv; these EXACT per-command overrides before the subcommand:
  `-c core.hooksPath=/dev/null -c core.fsmonitor=false -c protocol.allow=user
  -c protocol.file.allow=never -c protocol.ext.allow=never -c core.symlinks=false
  -c core.attributesFile=/dev/null -c filter.lfs.smudge= -c filter.lfs.process= -c filter.lfs.clean=`
  (the Windows `NUL` variant of the hooks path is UNVERIFIED); isolated environment
  `GIT_CONFIG_GLOBAL=<isolated file>`, `GIT_CONFIG_NOSYSTEM=1`, `GIT_TERMINAL_PROMPT=0`;
  leading-dash guard plus `git check-ref-format --branch <ref>`; nested `.git` dirs and `.git`
  pointer files and symlinks removed before `git add`; a `.gitattributes` found in the server tree
  is class E (catch-all) and is removed before `git add`; `.gitattributes` driver lines matching
  `(?:^|\s)(-?(?:filter|diff|merge|textconv|working-tree-encoding|export-subst)\s*=)` scrubbed in
  place on the panel-generated file. Remote URLs must match
  `https://github.com/<owner>/<repo>(.git)?` or `ssh://git@github.com/<owner>/<repo>(.git)?` and
  are rejected when they contain `ext::`, `fd::`, `file::`, userinfo, or newlines. `git archive`
  always uses `--no-worktree-attributes` plus the Step-1 member loop (D-F). The panel generates
  `.gitattributes` at commit time (class-D-like) with the D-K eol/filemode rules; it is never taken
  from the server directory. Use a private minimal Git config with `safe.directory` for the one
  repo path only. **Container identity is resolved** (OD-v8.5-6): FACT `docker.py:483` already passes
  `--user f"{uid}:{gid}"` for non-itzg images (itzg images instead get `PUID`/`PGID` env at
  `:480-481`); the normative contract adds `--security-opt=no-new-privileges:true`,
  `--cap-drop=ALL`, `--pids-limit=2048`, and forbids `0:0`, `--privileged`, and any
  `docker.sock`/Git-repo/CAS/LEC mount (see "Container security contract"). ONX uses
  eclipse-temurin with its own launch, not the itzg image, so itzg-specific points do not apply.
  FACT: `create_args` begins at `docker.py:412`, `--network` at `:416`, labels at `:419-423`, ports at
  `:434-460`, `--memory` at `:464`, `--cpus`/`--cpuset-cpus` at `:468-470`, the single
  `-v <host>:/data -w /data` mount at `:475`, and `--user` at `:483`; no `--cap-drop`,
  `--security-opt`, `--pids-limit`, `--privileged`, `--read-only`, or `docker.sock` exists anywhere in
  `backend/app` (0 matches).
- OWNER-STATED (2026-11-09, D-H, amended by OD-v8.4-2): COW is NOT required, but hardlinks are
  FORBIDDEN for CAS blobs, LEC trees, and Data Templates (a shared inode lets a container or
  malicious mod rewrite host-cached loader files for every server on the host). Probe with a real
  reflink attempt on the exact source/destination directories. If it succeeds, use reflink;
  otherwise use plain copy under a HOST-WIDE STORAGE COPY LOCK. After a failed reflink attempt,
  delete the partially created destination before fallback (`shutil.copytree` otherwise raises
  `FileExistsError`); before fallback, compute source tree size and require
  `shutil.disk_usage(dst.parent).free >= required_bytes * 1.10`, raising
  `InsufficientStorageError`. ext4 and ZFS reflink behavior remain UNVERIFIED (the report covers
  tmpfs/overlay/xfs only). Advanced is NOT disabled on ext4. Remove the "HTTP 412, no fallback" rule
  for Advanced. The current `StorageCowUnavailableError` behavior is a FACT that must change in the
  phase that implements this. Windows remains Simple-only.
- OWNER-STATED (2026-11-09, D-I, amended by OD-v8.4-1 and OD-v8.4-5): atomic live refresh happens
  only after the container is confirmed stopped (fail closed). Before stopping or refreshing,
  snapshot live Class C into the encrypted Class-C vault (OD-v8.7-7) and persist the unified
  crash-safe **Refresh Journal** on disk and in the DB with
  `(journal_id, server_id, phase, previous_main_sha, target_main_sha, pre_upgrade_backup_id,
  class_c_snapshot_id)`. Then (1) confirm stopped, (2) stage the new class-A/B tree in a sibling
  directory, (3) back up the files to be replaced for rollback, (4) switch by the **Crash-Safe
  Journaled Directory Swap** (`RENAME_EXCHANGE`, else fsynced `SWAPPING_OUT_LIVE` ->
  `SWAPPING_IN_STAGING` -> `SWAP_COMPLETED`; never `os.replace` on a non-empty directory, OD-v8.7-2)
  while keeping the live `world*` directory on its
  stable inode, (5) start, (6) roll back on failure. **Rollback is an atomic triad** (OD-v8.5-3):
  restore Class A + Class B from `previous_main_sha`, restore Class C from the exact
  `class_c_snapshot_id` captured before the refresh, and restore Class E from the pinned
  `pre_upgrade_backup_id` — all three, never a jar-only revert, so a plugin that migrated
  `userdata/`, `regions.yml`, or `saves.yml` before failing cannot pair an old jar with new state.
  Both `class_c_snapshot_id` and `pre_upgrade_backup_id` stay pinned until the operator explicitly
  clicks **"Confirm Upgrade & Unpin Rollback Backup"**. Merge into `main` never touches the running
  live container. Never create a Class-C Git branch or sync Class C into Git.
- OWNER-STATED (2026-11-09, D-J, amended by OD-v8.4-5): one write lock per repository covers
  add/commit/merge/fetch/push/gc/worktree add-remove. Reuse the existing DB lease pattern
  (`server_admission_lease`), not an in-process lock. Long-running operations (`git gc`, `git fetch`,
  large plain-copy fallback) renew their DB lease heartbeat every 10 seconds while the worker is
  alive, with a monotonically increasing fencing token so an expired lease cannot let a second
  worker corrupt `packed-refs` or staging directories. Long operations run asynchronously under
  `modules/operations/` and only become valid when a fsynced `.onx-complete.json`
  (`{"completed_at", "total_bytes", "file_count"}`) exists in the target directory; startup
  reconciliation deletes any target lacking that marker. Webhook handlers only enqueue.
  `git worktree lock` any worktree still referenced; gc only under the lock.
- OWNER-STATED (2026-11-09, D-K): GitHub is the last stage of Advanced (P5), after core works.
  Poll via `git fetch` FIRST; webhook is optional because the server may sit behind NAT. Webhook:
  verify HMAC-SHA256 on the raw body, dedupe by `X-GitHub-Delivery` but allow operator redelivery.
  Reject non-fast-forward updates to `main`. The panel generates `.gitattributes` at commit time
  (class-D-like; `* text=auto eol=lf` for text configs, `-text` for jars) and sets `core.filemode true`;
  it is never taken from the server directory. Jars never go to GitHub as plain blobs (see
  D-A). GitHub credentials are resolved by OD-v8.6-6 (fine-grained PAT or Ed25519 deploy key,
  AES-256-GCM at rest, injected via `GIT_ASKPASS`/`GIT_SSH_COMMAND`); the size cap is resolved by
  OD-v8.6-5/OD-v8.7-15 (1 MiB icon cap; other Class-B files above 1 MiB up to 16 MiB go to `A-CAS`).
- OWNER-STATED (2026-11-09, D-L): a runtime publishes a SET of host ports (game, rcon, query,
  plugin ports). Inside the container, `server-port`/rcon are fixed and panel-owned (class D).
  Duplicate-port checks scan every published port atomically.
- OWNER-STATED (2026-11-09, D-M, amended by OD-v8.4-1 and OD-v8.5-8): phases are recut by
  user-visible
  behavior, keeping owner order (CI/Windows fixes first, outside this spec; then P1, then P2).
  Advanced is not shown in the UI until the repo + clean export work in P2. Live refresh ships ONLY
  with the stop-check and rollback in P3. Each phase is independently shippable and states what the
  user sees. P2 is repo + clean export (5-step, Allow-list v2.3, Format 2.1) + Save & Commit +
  branch-aware Files; P3 is merge + the encrypted Class-C vault and Live State Files mode
  (NO Class-C Git branch) + restart refresh with triad rollback and the Refresh Journal; P4 is
  branch/test runs + ports + Data Templates (quiescent clone); P5 is GitHub (hardened git, URL
  validation); P5.5 is modpacks + LEC + 1-Click Safe Upgrade and runs AFTER P2, P3, and P4 (P5 may be
  built before or after P5.5); P6 is Docker-only; P7 is backups.

### Allow-list v2.3 (normative) - D-B/D-D/OD-v8.5-1..5/OD-v8.7-4/OD-v8.7-6

- OWNER-STATED (OD-v8.4-3, extended by OD-v8.5-5 and OD-v8.7-6, supersedes Allow-list v2/v2.1/v2.2):
  every path passes **Step 0** before any classification, lockfile parse, staging, or export. Step 0
  is split into functions with distinct contracts:
  - `validate_canonical_relpath(path)` is **pure lexical**: NFC, no NUL/LF/CR/backslash/colon, no
    absolute/empty/`.`/`..`/trailing-dot-or-space segment, canonical POSIX form, plus case-fold
    collision rejection at tree/lockfile level. It takes **no** `export_root` and performs no
    filesystem access.
  - `resolve_safe_disk_path(root_dir, rel_path, *, allow_create_parents=False)` validates the relpath
    and walks every parent with a **descriptor-relative** `os.open(..., O_DIRECTORY | O_NOFOLLOW,
    dir_fd=...)` hop, so a component swapped for a symlink after validation cannot redirect the
    operation. It returns the resolved path string and raises `SymlinkEscapeError`.
  - `open_safe_path_fd(root_dir, rel_path, *, flags, mode, allow_create_parents=False)` is
    **MANDATORY** for the actual mutation (open/create/write) of every filesystem read, write, copy,
    delete, or archive extraction under a worktree, staging tree, export root, or server directory:
    it opens the root with `O_DIRECTORY|O_NOFOLLOW`, verifies `(st_dev, st_ino)`, hops each segment
    with `O_DIRECTORY|O_NOFOLLOW` (creating missing parents with `os.mkdir(..., dir_fd=...)`), and
    opens the final file with `O_NOFOLLOW`, all relative to the held descriptors. The v8.4 realpath
    check and the v8.5 `lstat`-then-open walk both left a TOCTOU window; descriptor-relative traversal
    closes it. On Windows, `os.lstat(cur).st_file_attributes &
    stat.FILE_ATTRIBUTE_REPARSE_POINT` rejects junctions as well as symlinks at every segment. The
    exact normative implementation:
```python
import errno
import os
import posixpath
import re
import stat
import unicodedata

class SymlinkEscapeError(ValueError):
    """Raised when a path component is a symlink or the target escapes the root."""


def validate_canonical_relpath(path: str) -> str:
    """Step 0 (lexical): mandatory sanitizer before classification, staging, lockfile parse, or export."""
    if not isinstance(path, str) or not path:
        raise ValueError("Path must be a non-empty string")
    if unicodedata.normalize("NFC", path) != path:
        raise ValueError(f"Path is not Unicode NFC normalized: {path!r}")
    if any(ch in path for ch in ("\x00", "\n", "\r", "\\", ":")):
        raise ValueError(f"Path contains forbidden control or separator characters: {path!r}")
    if path.startswith("/") or path.endswith("/"):
        raise ValueError(f"Path must be relative without leading/trailing slash: {path!r}")
    segments = path.split("/")
    if any(seg in ("", ".", "..") or seg.endswith((" ", ".")) for seg in segments):
        raise ValueError(f"Path contains traversal, empty, or trailing-dot/space segment: {path!r}")
    if posixpath.normpath(path) != path:
        raise ValueError(f"Path is not canonical POSIX form: {path!r}")
    return path


def _reject_windows_reparse(st: os.stat_result) -> None:
    """Reject NTFS junctions/reparse points in addition to POSIX symlinks (Windows hosts)."""
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if getattr(st, "st_file_attributes", 0) & reparse:
        raise SymlinkEscapeError("Windows reparse point/junction rejected")


def _open_root_dir(root_dir: str) -> int:
    """Open root_dir as a directory fd, refusing a symlinked root and verifying its identity."""
    if os.path.islink(root_dir):
        raise SymlinkEscapeError(f"Root itself is a symlink: {root_dir!r}")
    root_real = os.path.realpath(root_dir)
    if not os.path.isdir(root_real):
        raise ValueError(f"Root is not an existing directory: {root_dir!r}")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(root_real, flags)
    try:
        expected = os.stat(root_real)
        st = os.fstat(fd)
        if (st.st_dev, st.st_ino) != (expected.st_dev, expected.st_ino):
            raise SymlinkEscapeError(f"Root directory identity changed during open: {root_dir!r}")
        _reject_windows_reparse(st)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _open_dir_at(dir_fd: int, seg: str, *, create: bool = False) -> int:
    """Open one directory component relative to dir_fd, never following a symlink."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        return os.open(seg, flags, dir_fd=dir_fd)
    except FileNotFoundError:
        if not create:
            raise
        os.mkdir(seg, 0o755, dir_fd=dir_fd)
        try:
            return os.open(seg, flags, dir_fd=dir_fd)
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                raise SymlinkEscapeError(
                    f"Symlink or non-directory component rejected: {seg!r}"
                ) from exc
            raise
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise SymlinkEscapeError(f"Symlink or non-directory component rejected: {seg!r}") from exc
        raise


def open_safe_path_fd(
    root_dir: str,
    rel_path: str,
    *,
    flags: int = os.O_RDONLY,
    mode: int = 0o644,
    allow_create_parents: bool = False,
) -> int:
    """TOCTOU-free open of rel_path under root_dir using descriptor-relative traversal.

    Every hop is os.open(..., O_DIRECTORY | O_NOFOLLOW, dir_fd=...), so replacing an
    intermediate component with a symlink between validation and use cannot redirect the
    open. The caller owns the returned fd.
    """
    rel_path = validate_canonical_relpath(rel_path)
    segments = rel_path.split("/")
    curr_fd = _open_root_dir(root_dir)
    try:
        for seg in segments[:-1]:
            next_fd = _open_dir_at(curr_fd, seg, create=allow_create_parents)
            _reject_windows_reparse(os.fstat(next_fd))
            os.close(curr_fd)
            curr_fd = next_fd
        try:
            return os.open(
                segments[-1],
                flags | getattr(os, "O_NOFOLLOW", 0),
                mode,
                dir_fd=curr_fd,
            )
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise SymlinkEscapeError(
                    f"Final symlink rejected: {rel_path!r}"
                ) from exc
            raise
    finally:
        os.close(curr_fd)


def resolve_safe_disk_path(
    root_dir: str, rel_path: str, *, allow_create_parents: bool = False
) -> str:
    """Validate containment with a descriptor-relative walk and return the target path.

    A path string alone can still be raced after return, so callers that mutate must use
    open_safe_path_fd (or pass dir_fd) instead of re-opening the returned string.
    """
    rel_path = validate_canonical_relpath(rel_path)
    root_real = os.path.realpath(root_dir)
    segments = rel_path.split("/")
    fd = _open_root_dir(root_dir)
    try:
        for seg in segments[:-1]:
            try:
                next_fd = _open_dir_at(fd, seg, create=allow_create_parents)
            except FileNotFoundError:
                if not allow_create_parents:
                    break
                raise
            _reject_windows_reparse(os.fstat(next_fd))
            os.close(fd)
            fd = next_fd
    finally:
        os.close(fd)

    target = os.path.join(root_real, *segments)
    target_real = os.path.realpath(target)
    if target_real == root_real or os.path.commonpath([root_real, target_real]) != root_real:
        raise SymlinkEscapeError(f"Path escapes root after resolution: {rel_path!r}")
    return target_real


def open_no_follow(path: str, flags: int = os.O_RDONLY) -> int:
    """Open a resolved file refusing to traverse a final symlink where the OS supports O_NOFOLLOW."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    return os.open(path, flags | nofollow)
```
  Step 0 rejects `..`, `.`, empty segments, absolute paths, trailing slashes, trailing dot/space
  segments, backslashes, colons, NUL/CR/LF, and non-NFC names. When validating a directory tree or
  `onx-jars.lock.json`, also reject case-folding collisions: if two distinct paths share the same
  `path.casefold()`, reject the commit/lockfile with `CaseCollisionError` (protects Windows Simple
  volumes and cross-platform Git). `resolve_safe_disk_path` is called at every read/write/copy/delete/
  archive-extraction site described anywhere in this specification; the lexical
  `validate_canonical_relpath` alone is never sufficient for touching disk.

- PROTOTYPE-REPORT (D-B/D-D) / OWNER-STATED (ND-7) / OWNER-STATED (OD-v8.4-3): Evaluation order
  (first match wins; every step runs only after Step 0 succeeds):
  0. **Step 0 - Canonicalization**: `validate_canonical_relpath(path)` -> if it raises `ValueError`,
     REJECT / QUARANTINE immediately; the path is never classified as A, B, or C.
  1. **Hostile Executable Quarantine (`HOSTILE_EXECUTABLE_QUARANTINE_REGEX`)**: any executable
     (`.jar`, `.war`, `.class`, `.so`, `.dll`, `.dylib`, `.exe`, `.sh`, `.bat`, `.cmd`, `.ps1`)
     anywhere inside `config/`, `defaultconfigs/`, `kubejs/`, `scripts/`, `datapacks/`,
     `global_packs/`, `patchouli_books/`, `schematics/`, `blueprints/`, `structures/`, or
     `structured-config/` -> QUARANTINE. During `.mrpack`/CurseForge archive import this is a hard
     abort (`HostileExecutableError`); during worktree scan / Save & Commit / D7 the file is moved to
     `<host_state_dir>/quarantine/<server_id>/`, excluded from `git add`, and surfaced as a
     high-severity banner instead of blocking the commit (OD-v8.7-12).
  2. **Dynamic Class-C overrides (D-D / OD-v8.4-4)**: any path in the per-server DB registry
     `dynamic-class-c`, excluding the protected Class-B root configs, -> **Class C**.
  3. **Class-A lockfile pointer (OD-1)**: matching `\Aonx-jars\.lock\.json\Z` (exact root file only;
     `plugins/X/onx-jars.lock.json` is rejected or treated as a normal file) -> **Class A lockfile**.
  4. **Class E hard denylist (`CLASS_E_DENYLIST_REGEX`)** -> **Class E** (never tracked in Git or
     CAS). Evaluated before Class A/B/C so `cache/*.jar`, `libraries/**/*.jar`, `.fabric/**`,
     nested jars outside the classpath roots, binary extensions, `.csv`, generated KubeJS/CraftTweaker
     artifacts, world sub-trees, and plugin binary data are never misclassified.
  5. **Class A executable jars (`CLASS_A_JAR_REGEX`)** -> **Class A** (sha256 CAS + lockfile,
     classpath). Classpath roots are root `*.jar`, `plugins/*.jar`, and `mods/**/*.jar` (ND-1).
  6. **Class A non-classpath CAS binaries (`CLASS_A_CAS_BINARY_REGEX`)** -> **Class A** (CAS only,
     never Git blobs, not on the classpath).
  7. **Class C live-owned state (`CLASS_C_LIVE_STATE_REGEX`)** -> **Class C** (encrypted Class-C
     vault; never a Git branch; never overwritten by `main`).
  8. **Class B user-edited configs & scripts (`CLASS_B_CONFIG_ALLOWLIST_REGEX`)** -> **Class B**
     (tracked on `main` and feature branches).
  9. **Default catch-all**: any unmatched path -> **Class E** (untracked).

- PROTOTYPE-REPORT (D-B) / OWNER-STATED (ND-7) / OWNER-STATED (OD-v8.4-3) / OWNER-STATED
  (OD-v8.5-1/2/OD-v8.7-4): Concrete regex and key definitions (Allow-list v2.3; every `$` replaced with `\Z`):
```python
HOSTILE_EXECUTABLE_QUARANTINE_REGEX = re.compile(
    r"\A(?:config|defaultconfigs|kubejs|scripts|datapacks|global_packs|patchouli_books"
    r"|schematics|blueprints|structures|structured-config)/.*\."
    r"(?:jar|war|class|so|dll|dylib|exe|sh|bat|cmd|ps1)\Z",
    re.IGNORECASE,
)

CLASS_E_DENYLIST_REGEX = re.compile(
    r"\A(?:"
    r"world(?:_nether|_the_end)?(?:/.*|\Z)"
    r"|\A(?:DIM-1|DIM1)(?:/.*|\Z)"
    r"|(?!\A(?:config|defaultconfigs|plugins|kubejs|datapacks|global_packs|resourcepacks"
    r"|shaderpacks|patchouli_books|scripts|structured-config|blueprints|schematics|structures)/)"
    r"(?:[^/]+/)+(?:dimensions/[^/]+/[^/]+|DIM-1|DIM1|region|entities|poi|advancements|stats|serverconfig)(?:/.*|\Z)"
    r"|logs(?:/.*|\Z)|crash-reports(?:/.*|\Z)|debug(?:/.*|\Z)"
    r"|cache(?:/.*|\Z)|\.cache(?:/.*|\Z)|libraries(?:/.*|\Z)|versions(?:/.*|\Z)"
    r"|\.fabric(?:/.*|\Z)|\.paper-remapped(?:/.*|\Z)|\.mixin\.out(?:/.*|\Z)"
    r"|mods/\.(?:connector|index)(?:/.*|\Z)"
    r"|kubejs/(?:probe|exported|\.cache)(?:/.*|\Z)"
    r"|config/(?:[^/]+/)*cache(?:/.*|\Z)"
    r"|plugins/[^/]+/cache(?:/.*|\Z)"
    r"|plugins/[^/]+/(?:userdata|data|players|playerdata|storage)/(?:[^/]+/)*[^/]+\."
    r"(?:png|jpg|jpeg|webp|gif|bmp|bin|zip|gz|tar|mca|mcr|dat|dat_old|db|sqlite|sqlite3)\Z"
    r"|journeymap(?:/.*|\Z)|Xaero[^/]*(?:/.*|\Z)|local(?:/.*|\Z)"
    r"|version_history\.json\Z|patched_[^/]+\.jar\Z|crafttweaker\.log\Z"
    r"|run\.sh\Z|run\.bat\Z|user_jvm_args\.txt\Z|eula\.txt\Z|\.gitattributes\Z"
    r"|(?!plugins/[^/]+\.jar\Z|mods/(?:[^/]+/)*[^/]+\.jar\Z|(?:shaderpacks|resourcepacks)/(?:[^/]+/)*[^/]+\.jar\Z)(?:[^/]+/)+[^/]+\.jar\Z"
    r"|(?!\A(?:schematics|blueprints|structures)/(?:[^/]+/)*[^/]+\.nbt\Z|\A(?:datapacks|global_packs|kubejs/data)/(?:[^/]+/)*structures/(?:[^/]+/)*[^/]+\.nbt\Z)(?:[^/]+/)*[^/]+\.nbt\Z"
    r"|(?:[^/]+/)*[^/]+\.(?:db|sqlite|sqlite3|db-wal|db-shm|sqlite-wal|sqlite-shm|mv\.db|trace\.db|h2\.db"
    r"|lock|lck|pid|log|gz|tar|mca|mcr|dat|dat_old|class|war|so|dll|dylib|csv|bak)\Z"
    r")"
)

CLASS_A_JAR_REGEX = re.compile(
    r"\A(?:[^/]+\.jar|plugins/[^/]+\.jar|mods/(?:[^/]+/)*[^/]+\.jar)\Z"
)

CLASS_A_CAS_BINARY_REGEX = re.compile(
    r"\A(?:"
    r"(?:shaderpacks|resourcepacks)/(?:[^/]+/)*[^/]+\."
    r"(?:zip|jar|png|ogg|bin|mcmeta|json|lang|properties|txt|fsh|vsh|glsl|cfg)"
    r"|kubejs/assets/(?:[^/]+/)*[^/]+\.(?:png|ogg|bin|webp|ttf|otf)"
    r"|patchouli_books/(?:[^/]+/)*[^/]+\.(?:png|ogg|bin)"
    r"|(?:structured-config|blueprints|schematics|structures)/(?:[^/]+/)*[^/]+\."
    r"(?:nbt|schem|schematic|litematic|png|bin|zip)"
    r"|(?:datapacks|global_packs|kubejs/data)/(?:[^/]+/)*structures/(?:[^/]+/)*[^/]+\.nbt"
    r")\Z"
)

CLASS_C_LIVE_STATE_REGEX = re.compile(
    r"\A(?:"
    r"ops\.json|whitelist\.json|banned-players\.json|banned-ips\.json|usercache\.json"
    r"|plugins/Essentials/warps/(?:[^/]+/)*[^/]+\.yml"
    r"|plugins/WorldGuard/worlds/(?:[^/]+/)*regions\.yml"
    r"|plugins/Citizens/saves\.yml"
    r"|plugins/[^/]+/(?:userdata|data|players|playerdata|storage)/(?:[^/]+/)*[^/]+\.(?:yml|yaml|json|txt)"
    r"|plugins/[^/]+/(?:data|players|userdata|database|storage)\.(?:yml|yaml|json|txt)"
    r"|(?:plugins/[^/]+|config)/(?:[^/]+/)*[^/]+\.(?:pem|key|p12|pfx|jks|keystore)"
    r"|voicechat/(?:[^/]+/)*[^/]+\.(?:properties|conf|json|yml)"
    r")\Z"
)

CLASS_B_CONFIG_ALLOWLIST_REGEX = re.compile(
    r"\A(?:"
    r"server\.properties|server-icon\.png|modrinth\.index\.json"
    r"|bukkit\.yml|spigot\.yml|commands\.yml|help\.yml|permissions\.yml|pufferfish\.yml|purpur\.yml"
    r"|(?:config|defaultconfigs)/(?:[^/]+/)*[^/]+\."
    r"(?:toml|json|json5|yml|yaml|properties|conf|cfg|snbt|xml|txt|mcfunction|mcmeta)"
    r"|plugins/[^/]+/(?:[^/]+/)*[^/]+\."
    r"(?:yml|yaml|json|json5|toml|properties|conf|cfg|snbt|xml|txt|lang|sk|dsc|mcfunction|mcmeta)"
    r"|kubejs/(?:startup_scripts|server_scripts|client_scripts)/(?:[^/]+/)*[^/]+\.js"
    r"|kubejs/(?:config|data)/(?:[^/]+/)*[^/]+\.(?:json|json5|yml|yaml|toml|txt|snbt)"
    r"|kubejs/assets/(?:[^/]+/)*[^/]+\.(?:json|lang|mcmeta)"
    r"|scripts/(?:[^/]+/)*[^/]+\.zs"
    r"|(?:datapacks|global_packs)/(?:[^/]+/)*[^/]+\.(?:json|mcmeta|mcfunction|txt|snbt)"
    r"|patchouli_books/(?:[^/]+/)*[^/]+\.json"
    r"|(?:structured-config|blueprints|schematics|structures)/(?:[^/]+/)*[^/]+\.(?:json|json5|yml|yaml|toml|txt|snbt)"
    r")\Z"
)

CLASS_D_PANEL_KEYS = frozenset({
    "server-port",
    "query.port",
    "rcon.port",
    "rcon.password",
    "enable-rcon",
    "enable-query",
    "broadcast-rcon-to-ops",
})
# Plus any key matching prefix "management-server-"
```

- OWNER-STATED (OD-v8.4-3): **Executable Script Review Warning.** Because `kubejs/**/*.js`,
  `scripts/**/*.zs`, `plugins/Skript/**/*.sk`, `plugins/Denizen/**/*.dsc`, and `**/*.mcfunction`
  execute server-side code by design, any `.mrpack` import, upgrade, or Git fetch that adds or
  modifies files matching those patterns MUST show an explicit Executable Script Review Warning in
  the UI listing the changed script paths before the operator confirms.

- PROTOTYPE-REPORT (D-B/D-D) / OWNER-STATED (ND-7) / OWNER-STATED (OD-v8.4-3): Classification rules:
  - `plugins/*/{userdata,data,players,playerdata,storage}/**` and `plugins/*/{data,players,userdata,database,storage}.{yml,yaml,json,txt}` are always class C (built-in default override list; contents are an implementation choice per "Owner-permitted implementation choices"), except for binary extensions, which Step 4 sends to class E.
  - `plugins/Essentials/warps/**/*.yml`, `plugins/WorldGuard/worlds/**/regions.yml`, and `plugins/Citizens/saves.yml` are named directly in `CLASS_C_LIVE_STATE_REGEX` and never rely on dynamic detection.
  - The registry that records dynamic C reclassification (`dynamic-class-c`) lives in the per-server DB, never inside the server tree (OD-4). It is reversible per OD-v8.4-4.
  - A custom `level-name` world is class E through the denylist's `world` alternatives only when literally named `world`; any other level is caught by the v2.3 anchored per-subtree alternatives (`region/`, `DIM-1`, `dimensions/`, `serverconfig/`, etc.), which never fire under `config/`, `plugins/`, `kubejs/`, `datapacks/`, or the other excluded roots (OD-v8.7-4), and by the default catch-all. Live `world/serverconfig/**` stays class E and is never overwritten from a test container on merge.
  - Precedence order means every `*.db`, `*.sqlite`, `*.dat`, `*.db-wal`, and `*.db-shm` under `plugins/` is class E even inside a class-C subtree (OD-2).
  - Text player data under `plugins/*/playerdata/` is class C. `*.dat` under `plugins/` stays class E (OD-2); binary player data is therefore never in the Class-C vault as a Git artefact, and is covered by backups and Data Templates.
  - Classpath jars (class A) are root `*.jar`, `plugins/*.jar`, and `mods/**/*.jar`. A `.jar` anywhere else (including `plugins/*/lib/*.jar`, `config/**`, `kubejs/**`, `scripts/**`, `defaultconfigs/**`) is class E, and when found under a hostile-executable root it is quarantined and rejected by the pack installer so it can never enter a classpath. `.class`, `.war`, `.so`, `.dll`, `.csv` are class E; `.nbt` is CAS under `schematics/`, `blueprints/`, `structures/`, and `(datapacks|global_packs|kubejs/data)/**/structures/`, and class E everywhere else (OD-v8.7-4).
  - `mods/.connector/**` and `mods/.index/**` are class E even though they live under `mods/` (loader connector/index caches are regenerable).
  - `server-icon.png` is class B tracked only up to **1 MiB**; a larger icon is rejected with `OversizedGitTrackedFileError (max 1 MiB)` (OD-v8.6-5/OD-v8.7-15). Any other valid Class-B text/config file above 1 MiB (up to 16 MiB) is routed to `A-CAS` and tracked by SHA-256 in the lockfile with a UI notice; only files `> 16 MiB` raise `OversizedGitTrackedFileError (max 16 MiB)` (OD-v8.7-15).
  - Nested config directories under `config/` are class B for `toml`, `json`, `json5`, `yml`, `yaml`, `properties`, `conf`, `cfg`, `snbt`, `xml`, `txt`, `mcfunction`, and `mcmeta`; `config/**/cache/**` is class E.
  - `defaultconfigs/**` is class B (NeoForge seeds `world/serverconfig/**` from it).
  - `kubejs/{startup_scripts,server_scripts,client_scripts}/**/*.js`, `kubejs/{config,data}/**`, `scripts/**/*.zs`, `datapacks/**`, `global_packs/**`, `patchouli_books/**/*.json`, `plugins/**/*.sk`, and `plugins/**/*.dsc` are class B (textual or key-level merge per the merge table).
  - **Cryptographic keys and voicechat secrets are class C, never class B** (OD-v8.5-1): `plugins/*/(**)/*.{pem,key,p12,pfx,jks,keystore}`, `config/(**)/*.{pem,key,p12,pfx,jks,keystore}`, and `voicechat/(**)/*.{properties,conf,json,yml}` are named directly in `CLASS_C_LIVE_STATE_REGEX`. They are never committed and never pushed, yet survive refresh/restart and are preserved in the dedicated encrypted Class-C vault (OD-v8.7-7). They are therefore never passed to the `Save & Commit` or 3-way merge path.
  - Non-classpath pack binaries (`shaderpacks/**`, `resourcepacks/**`, `kubejs/assets/**` binary, `patchouli_books/**` binary, `structured-config/**`, `blueprints/**`, `schematics/**`, `structures/**`) are class A CAS content, never Git blobs. `.zip` and `.jar` inside `shaderpacks/` or `resourcepacks/` are CAS **at any nesting depth** (OD-v8.5-2); the E-denylist lookahead mirrors the nested CAS pattern exactly so Step 4 never captures them.
  - `libraries/**`, `.fabric/**`, and `versions/**` are always class E (regenerable loader caches). The LEC tree is attached at Clean Export Step 3 from the host cache, never from Git.
  - `run.sh`, `run.bat`, `user_jvm_args.txt`, `eula.txt`, and `.gitattributes` are always class E in the server tree; the panel regenerates the first four at export (class D) and generates the repo `.gitattributes` at commit time (NOD-1).
  - Any unknown extension is class E through the default catch-all.

- PROTOTYPE-REPORT / OWNER-STATED (OD-2 consequence): Plugin binary data (`*.db`, `*.sqlite`, `*.dat` and similar under `plugins/`) is never tracked and never stored as Git content; it is covered by the existing backup system and is included in optional Data Templates (D-F overlays class-E paths). This includes binary player data (`*.dat` under `plugins/*/{userdata,players,playerdata}/**`); text player data under `playerdata/` is class C and lives in the encrypted Class-C vault.

- FACT (creation-time) / OWNER-STATED (OD-3): `eula.txt` is written at creation time by `write_eula` (`backend/app/modules/server/application/services/jar_service.py:987-1010`) which writes `eula=true`, called from `create_server.py:187`; test deployments write it at `backend/app/modules/versioning/infrastructure/config_writer.py:87-89`; backups already list it in `CONFIG_FILES` at `backend/app/services/backup_orchestrator.py:26-33`. Normative: `eula.txt` is panel-generated (class-D-like), never tracked; the P2 clean export must write it into the exported root.

- OWNER-STATED (ND-1, supersedes OD-6): `mods/**/*.jar` and mod configs are IN scope. Mod loaders (Fabric, Quilt, NeoForge, Forge) and `.mrpack` modpacks work in both Simple and Advanced modes; class A jars live in the CAS and are referenced by lockfile Format 2.1, so a Clean Export always boots with its mods. The former OD-6 "mods fall to class E" rule and the Lane E "mod loaders out of scope" note are retired by this decision.

- FACT (2026-11-11, v8.3 recon): today `mods/` is scanned only as a plugin add-on directory (`backend/app/modules/plugin/application/commands/reconcile_plugins.py:42-47`, `:75`; install target `backend/app/modules/plugin/application/commands/install_modrinth_plugin.py:125-129`), and the versioning manifest builder already hashes `mods/` and `plugins/` jars (`backend/app/modules/versioning/infrastructure/manifest_builder.py:98-113`). No `.mrpack`, `modrinth.index.json`, `kubejs`, `defaultconfigs`, `shaderpacks`, `resourcepacks`, or `datapacks` handling exists in `backend/app` (case-insensitive search: 0 matches).

## Modpack Engine, Loader Provisioning (LEC), and 1-Click Safe Upgrade (v8.5 normative)

- OWNER-STATED (ND-1..ND-9, 2026-11-11; hardened by OD-v8.4-1..OD-v8.4-11 and
  OD-v8.5-1..OD-v8.5-8, 2026-11-11): this
  section is normative for both Simple and Advanced modes. Where it contradicts OD-6, the Lane E
  mod-loader note, or any v8.3 mechanism superseded below, this section wins. Simple mode's Git-free
  pipeline and the container security contract below apply to every step here.

### Invariants

- OWNER-STATED (ND-3): **Zero binary bloat in Git.** Git never stores `libraries/**`, `.fabric/**`,
  `world*`, `*.jar`, or pack binary assets. Class A content lives only in the host-level SHA-256 CAS
  and is referenced from `onx-jars.lock.json`.
- OWNER-STATED (ND-2, extended by OD-v8.4-6): **Lockfile Format 2.1** is the single pointer file:
```json
{
  "format": 2,
  "mc": "26.3",
  "loader": { "id": "neoforge", "version": "26.3.0.102" },
  "lec": { "key": "neoforge/26.3/26.3.0.102" },
  "modpack": {
    "source": "modrinth",
    "project_id": "aabbccdd",
    "version_id": "IIJJKKLL",
    "version_label": "1.4.2",
    "index_sha256": "<64 hex>"
  },
  "base_overrides": {
    "config/fancymenu/options.txt": "<64 hex sha256 in CAS>",
    "kubejs/server_scripts/recipes.js": "<64 hex sha256 in CAS>"
  },
  "files": [
    {
      "path": "mods/example.jar",
      "sha256": "<64 hex>",
      "sha512": "<128 hex>",
      "sha1": "<40 hex>",
      "size": 1797522,
      "optional": false,
      "env_server": "required",
      "origin": "modrinth",
      "project_id": "P7dR8mSH",
      "version_id": "998R2rNP"
    }
  ]
}
```
  `origin` is one of `modrinth`, `curseforge`, `curseforge-unclassified`, `override`, `papermc`,
  `user`. `env_server` is one of `required`, `optional`, `unsupported`. `base_overrides` maps every
  Class-B file shipped by the pack's `overrides/` + `server-overrides/` layers to its SHA-256 blob in
  the CAS; it is the deterministic 3-way ancestor B for BOTH modes because Simple has no Git history
  (OD-v8.4-6). The lockfile itself is class A (evaluation step 3), never class B. Format 1 and
  Format 2 lockfiles are not migrated and never silently upgraded (D8). In Simple mode the same
  Format 2.1 document lives on the host at
  `<host_state_dir>/server-meta/<server_id>/onx-jars.lock.json` (OD-v8.5-4/OD-v8.7-5), with a
  non-authoritative informational copy at `<server_root>/.onx-manager/onx-jars.lock.json`; in
  Advanced mode it is tracked at the repo root.
- OWNER-STATED (ND-3, supersedes the v8.3 composition by OD-v8.4-2): **Clean Export composition is a
  fixed 5-step order.** (1) `git archive --format=tar --no-worktree-attributes <sha>` extracted
  member-by-member; (2) Class A materialization from the CAS; (3) LEC attach (`libraries/**` or
  `.fabric/server/**`); (4) optional Class-E Data Template overlay; (5) Class D injected LAST as the
  authoritative final writer (`server.properties` panel keys, `eula.txt`, generated
  `user_jvm_args.txt`). The export contains no `.git`. All materialization uses a probe-verified
  reflink or a plain copy; **hardlinks are FORBIDDEN**. In Simple mode (no Git) steps (1) is replaced
  by reading the live Class-B files plus the authoritative host `onx-jars.lock.json`; steps (2)-(5) are
  unchanged and the result is built in `<server_root>.staging/` before the crash-safe swap (OD-v8.5-4/OD-v8.7-2).
- OWNER-STATED (ND-3): **Offline boot invariant.** A Clean Export MUST boot without reaching Maven,
  Modrinth, or Mojang at container start. Any loader file needed at boot must be inside the LEC
  tree or the CAS materialization.
- OWNER-STATED (ND-4, extended by OD-v8.4-9): **Container launch** for NeoForge/Forge/Quilt is
  `java @user_jvm_args.txt @libraries/.../unix_args.txt nogui` (NeoForge
  `libraries/net/neoforged/neoforge/{ver}/unix_args.txt`, Forge
  `libraries/net/minecraftforge/forge/{mc}-{forge}/unix_args.txt`, Quilt
  `libraries/org/quiltmc/quilt-loader/{loader}/unix_args.txt`). The working directory is the
  exported instance root. `run.sh`, `run.bat`, and `ServerStarterJar` are never executed and never
  exported.
- OWNER-STATED (OD-v8.4-2): **Attachment mechanisms.** Only (a) `cp --reflink=always` verified by a
  real probe on the exact source/destination paths, deleting any partial destination before
  fallback, or (b) `shutil.copytree`/`copy2` under a per-target-`st_dev` **storage copy lock** after
  `shutil.disk_usage(dst.parent).free >= required_bytes * 1.10` (else `InsufficientStorageError`).
  A hardlink shares the inode, so one container or malicious mod could append
  `-javaagent:/data/pwn.jar` to a host-cached `unix_args.txt` and poison every server on the host;
  it is therefore never permitted.

### `.mrpack` (Modrinth Index v1) server installation

- OWNER-STATED (ND-5): the archive is a ZIP with UTF-8 `modrinth.index.json` at its root.
  `formatVersion` MUST equal `1` (hard fail otherwise); `game` MUST equal `"minecraft"`;
  `dependencies` MUST contain `minecraft` and **at most one** loader key from `fabric-loader`,
  `quilt-loader`, `forge`, `neoforge`. Two loader keys = hard fail.
- OWNER-STATED (ND-5/OD-v8.4-9): `dependencies.forge` with `minecraft >= 1.20.2` = hard fail
  (Forge ends at `1.20.1-47.4.29`; NeoForge takes over), and `dependencies.forge` with
  `minecraft < 1.17.1` = hard fail with `UnsupportedForgeVersionError` at validation time (those
  installers do not generate `unix_args.txt`).
- OWNER-STATED (ND-5): each `files[]` entry carries `path` (instance-relative POSIX path),
  `hashes.sha1` (40 hex), `hashes.sha512` (128 hex, mandatory before computing our SHA-256),
  `downloads[]` (ordered URLs), `fileSize` (exact byte length), and optional `env`
  (`{"client": ..., "server": ...}` with values `required | optional | unsupported`; a missing
  `env` object defaults every member to `required`).
- OWNER-STATED (ND-5): dedicated-server filter:
  - `env.server == "unsupported"` -> do not download, do not place, do not store in CAS (client-only
    mods such as Sodium/Iris/ModMenu must never reach the server root or its classpath).
  - `env.server == "required"` or missing -> install.
  - `env.server == "optional"` -> install iff `install_optional_server_files` is true (default
    `true`); record `"optional": true` in the lockfile.
  - Do NOT re-query Modrinth `project.server_side` to override an explicit `env` during pack
    installs; the pack author's decision is authoritative.
- OWNER-STATED (ND-5, hardened by OD-v8.4-8): override precedence on a dedicated server, lowest to
  highest:
  1. filtered `files[]` from `modrinth.index.json` (downloaded to CAS, materialized at `path`);
  2. `overrides/**`;
  3. `server-overrides/**` (replaces the same relative path from `overrides/` or the index).
  `client-overrides/**` is NEVER applied on a server. A `.jar` present in both the index and an
  override layer stays class A; the lockfile hashes the post-override bytes.
  **Mandatory override-jar environment filter:** any `.jar` arriving via `overrides/mods/**`,
  `server-overrides/mods/**`, `overrides/plugins/**`, or `server-overrides/plugins/**` MUST have its
  SHA-512 computed and queried against `POST https://api.modrinth.com/v2/version_files`. If Modrinth
  returns a version with `environment == "client_only"` (or a subsequent project lookup shows
  `server_side == "unsupported"`), the jar is excluded from installation and the CAS and logged as
  `skipped_client_override_jar`.
- OWNER-STATED (ND-5, hardened by OD-v8.4-3 and OD-v8.5-5): **archive quarantine.** Run
  `validate_canonical_relpath()` (Step 0) on `modrinth.index.json` paths and every archive member,
  and resolve every extraction destination through `open_safe_path_fd()` (descriptor-relative
  `O_DIRECTORY|O_NOFOLLOW` hops, `SymlinkEscapeError`) so a symlinked staging component cannot
  redirect a write.
  Reject the archive if any entry or `files[].path` is not a relative POSIX path, is not Unicode
  NFC, contains NUL, `\`, or `:`, is absolute, contains `.`/`..`/empty segments, ends with a dot or
  space segment, is a symlink (`external_attr >> 16 & 0xF000 == 0xA000`) or any other non-regular
  member, has a compression ratio `uncompressed / compressed > 64` **only when that entry's
  `uncompressed` size exceeds 16 MiB** (legitimate repetitive JSON/SNBT under 16 MiB routinely
  exceed 100:1), or `compressed == 0` with
  `uncompressed > 16 MiB`, pushes total uncompressed size above 4 GiB, pushes the entry count above
  100,000, or creates a casefold collision (two distinct paths with the same `path.casefold()` ->
  `CaseCollisionError`). Hard-deny `.git/`, `.fabric/`, `libraries/`, `versions/`, and `logs/`
  prefixes even when syntactically valid.
- OWNER-STATED (ND-5, expanded by OD-v8.4-8): **download host allow-list**, checked on the initial
  URL AND after every HTTP redirect hop (max 5 hops). Parse with `urllib.parse.urlsplit`; require
  `scheme == "https"`, `username is None`, `password is None`, and a hostname (IDNA ASCII normalized,
  IPv4/IPv6 literals rejected) in:

```
cdn.modrinth.com
edge.forgecdn.net
mediafilez.forgecdn.net
media.forgecdn.net
maven.fabricmc.net
meta.fabricmc.net
maven.quiltmc.org
meta.quiltmc.org
maven.neoforged.net
maven.minecraftforge.net
fill.papermc.io
fill-data.papermc.io
piston-meta.mojang.com
piston-data.mojang.com
libraries.minecraft.net
github.com                            (ONLY when path matches ^/[^/]+/[^/]+/releases/download/[^/]+/[^/]+$)
release-assets.githubusercontent.com  (ONLY on redirect from github.com/<org>/<repo>/releases/download/)
objects.githubusercontent.com         (ONLY on redirect from github.com/<org>/<repo>/releases/download/)
github-releases.githubusercontent.com  (ONLY on redirect from github.com/<org>/<repo>/releases/download/)
```

  A redirect to an IP literal or an unlisted host is a hard fail unless an admin configured a
  per-server allow-list.
- OWNER-STATED (ND-5/ND-7, hardened by OD-v8.4-3): **hostile binary quarantine.** Any archive member
  matching the hostile-executable set (`.jar`, `.war`, `.class`, `.so`, `.dll`, `.dylib`, `.exe`,
  `.sh`, `.bat`, `.cmd`, `.ps1`) is class A only when its path is under `mods/`, `plugins/`, or is a
  root jar; a jar hidden inside `config/`, `kubejs/`, `scripts/`, `defaultconfigs/`, or any other
  hostile-executable root is rejected with `HostileExecutableError` (installer) or classified class E
  (existing tree), so it can never enter a classpath.
- OWNER-STATED (ND-5, hardened by OD-v8.4-8): a CurseForge zip (`manifest.json` with
  `files[{projectID, fileID, required}]` plus `overrides`) is adapted into the same internal
  `InstallPlan`; `manifest.json` is discarded. **ONX never ships an embedded CurseForge API key**:
  importing a CurseForge modpack requires the admin to configure `curseforge_api_key` in panel
  settings, otherwise the import is rejected with `CurseForgeApiKeyMissingError`. Because CurseForge
  lacks hashes and `env.server`, after hashing each download the installer calls Modrinth
  `POST /v2/version_files` by SHA-512; a file Modrinth reports as `environment=client_only` or
  `server_side=unsupported` is dropped with `skipped_client_override_jar`. Unknown hashes stay
  installed with `origin: "curseforge-unclassified"` so the upgrade matrix flags them.
  When `POST https://api.curseforge.com/v1/mods/files` returns `downloadUrl: null` (or the CDN
  returns 401/403), the file is NOT silently skipped and does NOT crash the parser: it is recorded
  in the `InstallPlan`/`UpgradeMatrix` as `blocker: manual_download_required` with the exact
  filename, CurseForge webpage link, and expected size/hash. The UI lets the operator drag-and-drop
  that jar into the wizard; the panel verifies hash and size, stores it in the CAS, and clears the
  blocker.

### Loader provisioning, Java floor, and the Loader Environment Cache (LEC)

- OWNER-STATED (ND-8, exact mapping locked by OD-v8.6-8 and made contiguous by OD-v8.7-15): the Java
  floor comes from Mojang version
  metadata (`javaVersion.majorVersion`) or Paper Fill v3
  (`GET https://fill.papermc.io/v3/projects/paper/versions/{mc}` ->
  `version.java.version.minimum`; e.g. Java 25 for MC 26.3, Java 21 for 1.21.1/1.21.4). Fabric's
  `launcherMeta.min_java_version` is NOT trusted (it reports `8` for modern versions). The legacy
  Forge variants are fixed: `1.17.1` -> Java 16 (runs on `eclipse-temurin:17-jre`), `1.18`-`1.20.4`
  -> Java 17 (`eclipse-temurin:17-jre`), `1.20.5`-`1.21.11` -> Java 21 (`eclipse-temurin:21-jre`),
  `26.1+` -> Java 25 (`eclipse-temurin:25-jre`); the major is mapped to Temurin `8`, `17`, `21`, or
  `25`.
- OWNER-STATED (OD-v8.7-11, fixing R13): **Paper uses LEC.** Provisioning pre-warms an isolated
  builder directory with `java -Dpaperclip.patchonly=true -jar paper-{mc}-{build}.jar`, which
  downloads and verifies the Mojang jar and populates `cache/**`, `versions/**`, and `libraries/**`
  without starting the game. Those trees are snapshotted under LEC key `paper/{mc}/{build}` (recorded
  as `lec.key` in the lockfile) and re-attached at Clean Export Step 3, so a Paper server boots
  completely offline.
- OWNER-STATED (ND-3, amended by OD-v8.4-9 and OD-v8.7-11): shared loader table:

| Loader | Artifact fetched once | LEC key | Launch |
|---|---|---|---|
| Fabric | `meta.fabricmc.net/v2/versions/loader/{mc}/{loader}/{installer}/server/jar` (single executable server launcher, `Main-Class: net.fabricmc.installer.ServerLauncher`) | `fabric/{mc}/{loader}/{installer}` | launcher jar; runtime files under `.fabric/server/**` |
| Quilt | `GET https://meta.quiltmc.org/v3/versions/loader/{mc}/{loader}/server/json` (`mainClass: org.quiltmc.loader.impl.launch.knot.KnotServer`, `inheritsFrom`, `libraries[]`); the `/server/jar` endpoint is 404 | `quilt/{mc}/{loader}` | generated argfile |
| NeoForge | `maven.neoforged.net/.../neoforge-{ver}-installer.jar`, run once with `--installServer` in an isolated builder dir | `neoforge/{mc}/{neoforge_ver}` | `java @user_jvm_args.txt @libraries/net/neoforged/neoforge/{ver}/unix_args.txt nogui` |
| Forge (1.17.1 - 1.20.1) | `maven.minecraftforge.net/.../forge-{ver}-installer.jar`, run once with `--installServer` | `forge/{mc}/{forge_ver}` | `java @user_jvm_args.txt @libraries/net/minecraftforge/forge/{mc}-{forge}/unix_args.txt nogui` |
| Paper (Fill v3) | version-group resolution + full `GET https://fill.papermc.io/v3/projects/paper/versions/{mc}/builds` list, filter `channel == "STABLE"`; pre-warm with `java -Dpaperclip.patchonly=true -jar paper-{mc}-{build}.jar` | `paper/{mc}/{build}` (`cache/**`, `versions/**`, `libraries/**`) | `java -jar paper-{mc}-{build}.jar nogui` |

- OWNER-STATED (ND-3): the Fabric/Quilt launcher jar is the sole class A Fabric/Quilt jar in the
  lockfile. The installer `--installServer` invocation generates `libraries/**` (containing the
  processed Minecraft server jar and the platform `unix_args.txt`); that tree is snapshotted into the
  host LEC under the key above and never committed to Git.
- OWNER-STATED (OD-v8.4-2): **strict LEC payload boundary.** A persisted LEC entry
  (`neoforge/{mc}/{ver}`, `forge/{mc}/{ver}`, `quilt/{mc}/{ver}`, or `fabric/{mc}/{loader}/{installer}`)
  MUST contain ONLY the isolated directory subtree `libraries/**` (NeoForge/Forge/Quilt) or
  `.fabric/server/**` (Fabric). During LEC build, all builder-root files (`run.sh`, `run.bat`,
  `user_jvm_args.txt`, `eula.txt`, `installer.jar`, `installer.jar.log`, and the root `server.jar`
  ServerStarterJar) MUST be deleted before snapshotting.
- OWNER-STATED (ND-3/ND-4, amended by OD-v8.4-9): pre-warm a LEC entry by running the
  installer/launcher once in an isolated builder directory (with `eula=true`, no user mods), then
  snapshot it. Export attaches the LEC tree at Step 3, refusing any override that targets
  `libraries/**` or `.fabric/**`, and injects class D at Step 5 so `run.sh`/`run.bat`/`eula.txt`/
  `user_jvm_args.txt` cannot be clobbered. `unix_args.txt` inside `libraries/` is therefore
  panel-controlled and cannot be substituted by a pack. The LEC build MUST assert that the target
  `unix_args.txt` exists and is non-empty before writing `.onx-complete.json`.
- OWNER-STATED (OD-v8.4-9): **Quilt LEC provisioning.** Fetch the `server/json` document, download
  each entry in `libraries[]` from its Maven URL (default `https://maven.quiltmc.org/repository/release/`
  or `https://libraries.minecraft.net/`) into `libraries/<maven_path>`, and download the official
  Mojang `server.jar` for `inheritsFrom` to
  `libraries/net/minecraft/server/{mc}/server-{mc}.jar` (verifying SHA-1/SHA-256 from
  `version_manifest_v2.json`). Generate a deterministic
  `libraries/org/quiltmc/quilt-loader/{loader}/unix_args.txt` containing
  `-Dfabric.gameJarPath=libraries/net/minecraft/server/{mc}/server-{mc}.jar -cp <colon-joined
  relative library paths> org.quiltmc.loader.impl.launch.knot.KnotServer`.
- OWNER-STATED (OD-v8.4-9): **Forge supported range.** Forge is supported strictly for
  `1.17.1 <= mc <= 1.20.1` (latest `1.20.1-47.4.29`), where `--installServer` produces
  `libraries/net/minecraftforge/forge/{mc}-{forge}/unix_args.txt`. Any pack or server creation
  request with `mc < 1.17.1` or `mc >= 1.20.2` is rejected at validation time with
  `UnsupportedForgeVersionError` (below 1.17.1 there is no argfile support; 1.20.2+ is NeoForge).
- OWNER-STATED (OD-v8.4-9): **Paper Fill v3 resolution.** Query
  `GET https://fill.papermc.io/v3/projects/paper` to resolve version groups (if `{mc}` is `26.1` and
  absent from `versions`, pick the highest matching `26.1.x` in the `26.1` group). Then query the
  full `GET https://fill.papermc.io/v3/projects/paper/versions/{resolved_mc}/builds` list (NOT
  `/builds/latest`), filter `channel == "STABLE"`, and select the highest build id; BETA/ALPHA are
  used only when `allow_experimental_paper_builds=True` is explicitly passed.
- OWNER-STATED (ND-4): `user_jvm_args.txt` is generated at Clean Export time from panel memory/JVM
  settings (`-Xmx`, `-Xms`, extra flags). Any `user_jvm_args.txt`, `run.sh`, or `run.bat` shipped by
  a modpack is ignored and discarded.
- OWNER-STATED (ND-3, amended by OD-v8.4-2 and OD-v8.6-8): the LEC storage root and key layout are
  implementation choices; the eviction policy is fixed by OD-v8.6-8 (reference-counted against every
  active lockfile, unreferenced entries older than 7 days pruned only by "Clean Unused Cache" or the
  weekly maintenance task). The attach preference is NOT a choice: reflink or plain copy only, never
  hardlink.

### `world/serverconfig` vs `defaultconfigs`

- OWNER-STATED (ND-7): NeoForge server configs inside `world/serverconfig/**` override `config/**`
  and are seeded from `defaultconfigs/**` only when a world is first created. Live
  `world/serverconfig/**` is class E inside the world; it is never overwritten from a test container
  on merge, and it is never tracked.

### Quiescent clone, asynchronous operations, and the unified Refresh Journal

- OWNER-STATED (OD-v8.4-5, hardened by OD-v8.7-8): **quiescent live clone.**
  - **Reflink path:** send RCON `save-off`; send RCON `save-all flush` and wait up to 30s for the
    server response confirming the save completed; verify no active file modifications are in flight;
    then execute the reflink; and in a mandatory `finally:` block always send RCON `save-on`.
    **Fail closed:** if RCON is disabled, unreachable, or `save-all flush` does not confirm within
    30s, the backend MUST refuse to hot-clone and require stopping the container (confirming STOPPED
    and `session.lock` released) before cloning.
  - **Two-pass delta clone (non-reflink filesystems, running server):** (Pass 1, `save-on` active)
    copy `world*` to the staging template while the server keeps running; (Pass 2, quiesced) persist
    `rcon_save_off_active = True` in the server's DB state, send `save-off` + `save-all flush`, and
    sync only files whose `(st_mtime_ns, st_size)` changed since Pass 1 plus deletions. The
    `save-off` window is hard-capped at **60 seconds**; if Pass 2 exceeds it, abort the hot clone,
    immediately send `save-on`, clear the flag, and require a stopped-container clone.
  - **Startup recovery:** the `main.py` lifespan reconciler queries every server with
    `rcon_save_off_active == True` (or an interrupted clone journal), sends RCON `save-on`, and clears
    the flag, so a panel crash can never leave a world with saving disabled.
  - **Per-device copy lock:** the storage copy lock and the `required_bytes * 1.10` free-space
    reservation are scoped by the target filesystem `os.stat(dst).st_dev`, so copying on one disk
    never serializes an unrelated disk.
- OWNER-STATED (OD-v8.7-2, fixes R2): **Crash-Safe Journaled Directory Swap.** Never call
  `os.replace(staging_dir, live_dir)` when `live_dir` is an existing non-empty directory
  (`ENOTEMPTY`). Use one of:
  1. **Exchange (preferred, Linux):** where the filesystem/kernel supports
     `renameat2(..., RENAME_EXCHANGE)` (`SYS_renameat2`, flag `2`), call
     `renameat2(AT_FDCWD, staging_dir, AT_FDCWD, live_dir, RENAME_EXCHANGE)` for a single-syscall
     atomic exchange, verify the new live tree, then remove the old tree now at `staging_dir`.
  2. **Journaled 2-step rename (fallback):** ensure `<live_dir>.prev` does not exist; write
     `phase = "SWAPPING_OUT_LIVE"` to the Refresh Journal and `os.fsync()`; `os.rename(live_dir,
     f"{live_dir}.prev")`; write `phase = "SWAPPING_IN_STAGING"` + `os.fsync()`; `os.rename(staging_dir,
     live_dir)`; write `phase = "SWAP_COMPLETED"` + `os.fsync()`. Each rename is an atomic metadata
     operation, so the tree is never partially visible.
  3. **Boot reconciler recovery:** if the host crashes while `phase` is `SWAPPING_OUT_LIVE` or
     `SWAPPING_IN_STAGING`, `live_dir` is missing, and `<live_dir>.prev` exists, startup
     reconciliation renames `<live_dir>.prev -> live_dir`, restoring a consistent pre-swap state;
     afterwards the journal phase is marked `SWAP_ROLLED_BACK`.
- OWNER-STATED (OD-v8.4-5): **async operation + COMPLETE marker.** All Data Template clones,
  `.mrpack` installs, and version upgrades run as asynchronous background operations via the new
  `modules/operations/` package, never blocking an HTTP handler. A target directory (LEC entry, Data
  Template, or Backup snapshot) is invalid until a `.onx-complete.json` marker
  (`{"completed_at": "...", "total_bytes": 12345, "file_count": 42}`) is written and `os.fsync()`ed
  on both the file and the parent directory. Startup reconciliation deletes any target directory
  lacking `.onx-complete.json`.
- OWNER-STATED (OD-v8.4-5): **lease renewal (heartbeat).** Long-running repository or storage
  operations (`git gc`, `git fetch`, large plain-copy fallback) MUST actively renew their DB lease
  heartbeat every 10 seconds while the worker task is alive, using a monotonically increasing
  fencing token so an expired lease cannot allow a second worker to corrupt `packed-refs` or staging
  directories.
- OWNER-STATED (OD-v8.4-5): **unified crash-safe Refresh Journal** (merges the former D-I and ND-6
  mechanisms into one state machine). Before touching `main` or stopping live for an upgrade or
  refresh, persist an on-disk and DB journal row with
  `(journal_id, server_id, phase, previous_main_sha, target_main_sha, pre_upgrade_backup_id,
  class_c_snapshot_id)`. Staged trees switch through the Crash-Safe Journaled Directory Swap above
  (never unlink + symlink) while the live `world*` directory keeps its stable inode. Always take the
  pinned pre-upgrade backup (with live confirmed STOPPED) before starting the new server jar on the
  live world.

### Simple mode Git-free lockfile, staging, and crash-safe swap (OD-v8.5-4/OD-v8.7-5/OD-v8.7-2)

- OWNER-STATED (OD-v8.5-4): **Simple mode is Git-free end to end.** A Simple server has no `.git`
  repository and no `git worktree`s; every `/versioning/*` route stays blocked with
  `HTTP 409 ServerModeVersioningDisabledError` (D1). References to Clean Export and 3-way merge below
  therefore resolve to the Git-free pipeline in this subsection, not to `git archive`.
- OWNER-STATED (OD-v8.7-5, fixes R5/R15): **host-owned authoritative lockfile.** For Simple Mode the
  authoritative `onx-jars.lock.json` is stored **outside `/data`** at
  `<host_state_dir>/server-meta/<server_id>/onx-jars.lock.json`, in a panel-only directory never
  mounted into the container. A read-only informational copy may be written to
  `/data/.onx-manager/onx-jars.lock.json`, but the backend **never reads or trusts** the `/data` copy
  for `files[]`, `lec.key`, `base_overrides`, or `modpack` metadata, so a malicious mod/script inside
  `/data` cannot tamper with the authoritative record.
- OWNER-STATED (OD-v8.7-5, fixes R5/R15): **automatic baseline adoption, built in P2.**
  `ensure_simple_baseline_lockfile(server_id)` runs before any backup, modpack install, upgrade, or
  D7 conversion on a Simple server whose host lockfile is missing: it scans `<server_root>` through
  Allow-list v2.3, copies discovered Class-A jars/binaries into the SHA-256 CAS, and writes the
  authoritative Format 2.1 lockfile on the host. Simple servers created in P1 are therefore adopted
  automatically instead of failing until P5.5.
- OWNER-STATED (OD-v8.5-4, host path by OD-v8.7-5): **Simple Mode source of truth.** For `.mrpack`
  installation, loader provisioning (LEC), and 1-Click Safe Upgrades the backend maintains the host
  lockfile above — Lockfile **Format 2.1** tracking installed Class-A CAS binaries, `lec.key`,
  `modpack` metadata, and `base_overrides: dict[relpath, sha256]` pointing at the unmodified base-pack
  Class-B blobs in the host CAS. `.onx-manager/**` in the server tree is panel-owned metadata (never
  hand-edited, never returned in Files), and every write passes `open_safe_path_fd()`.
- OWNER-STATED (OD-v8.5-4, swap by OD-v8.7-2, ancestor rule by OD-v8.7-9): **5-step staging and
  crash-safe swap (no Git involved).**
  1. **Quiesce & snapshot:** stop the container (confirm `STOPPED`, `session.lock` absent), take a
     pinned `pre_upgrade_backup_id` of Class E (`world*`) and a pinned `class_c_snapshot_id` of
     Class C, and write the on-disk Refresh Journal.
  2. **3-way config merge into `<server_root>.staging/`:** for each Class-B file read ancestor B from
     the host lockfile `base_overrides` in the CAS, current O from the live `<server_root>`, and
     target T from the new pack/update; write the merged Class-B tree and the updated lockfile into
     the sibling staging root. **Per-file ancestor advancement (OD-v8.7-9):** advance
     `base_overrides[relpath]` to `T[relpath].sha256` only when T was cleanly merged (or
     operator-resolved); if the file fell back to live-wins/parse-failure, keep the previous
     `B[relpath]` hash.
  3. **Materialize Class A + attach LEC:** materialize all Class-A binaries from the host CAS and
     attach the LEC (`libraries/**`, `.fabric/server/**`, or Paper `cache/**`+`versions/**`) into
     `<server_root>.staging/` via reflink or plain copy only (hardlinks FORBIDDEN, OD-v8.4-2).
  4. **Inject Class D LAST:** write `eula.txt`, panel-generated `user_jvm_args.txt`, the Class-D
     `server.properties` keys, and substitute any `${ONX_SECRET_<KEY_NAME>}` values (OD-v8.7-3) into
     the staged root, and assert no `run.sh`/`run.bat` exists.
  5. **Preserve Class E/C and swap:** preserve the live Class-E (`world*`) and live Class-C files into
     the staged root (world data keeps its same-filesystem volume/inode; no re-copy), perform the
     **Crash-Safe Journaled Directory Swap** between `<server_root>` and `<server_root>.staging`
     (OD-v8.7-2: `RENAME_EXCHANGE` or journaled 2-step rename — never `os.replace` on a non-empty
     directory), start the container, and run the 4-step Health Gate with its boot timeout. On gate
     failure, restore the previous root + `class_c_snapshot_id` + `pre_upgrade_backup_id` as one triad
     (OD-v8.5-3).
- OWNER-STATED (OD-v8.5-4, hardened by OD-v8.7-6): the staging root, the previous root, and
  `.onx-manager/` are accessed only through `open_safe_path_fd()`/`resolve_safe_disk_path()`; a
  staging root left without a fsynced `.onx-complete.json` marker is deleted by startup
  reconciliation.

### Container security contract (OD-v8.5-6)

- OWNER-STATED (OD-v8.5-6): **normative for `DockerProvider`; every server, branch, and test
  container.**
  1. **Non-root execution:** always pass `--user uid:gid` (defaulting to the host panel
     `os.getuid():os.getgid()` when non-zero, else dedicated unprivileged `1000:1000`), never `0:0`,
     matching ownership of the exported `/data` directory. Before `docker create`/`start`, recursively
     `chown` the exported `/data` tree to the target `uid:gid` so the non-root container can write.
     FACT: `docker.py:483` already does this for non-itzg images, and `:480-481` sets `PUID`/`PGID`
     for itzg images.
  2. **Privilege and capability dropping:** always pass
     `--security-opt=no-new-privileges:true` and `--cap-drop=ALL`. FACT: neither exists today (0
     matches in `backend/app`).
  3. **Mount and socket isolation:** never mount `/var/run/docker.sock`, the host Git repository, the
     host SHA-256 CAS, or the host LEC store into any container. The container receives ONLY its
     isolated exported `/data` directory as a bind mount. FACT: `docker.py:475` already mounts exactly
     one `-v <host>:/data -w /data`; there is no `docker.sock` mount anywhere in `backend/app`.
  4. **Resource and fork-bomb limits:** always enforce `--memory`, `--cpus`, and `--pids-limit=2048`
     (configurable per server) so a runaway KubeJS script or mod cannot exhaust host PIDs or RAM.
     FACT: `--memory` at `docker.py:464` and `--cpus`/`--cpuset-cpus` at `:468-470` exist today;
     `--pids-limit` does not (0 matches).
- OWNER-STATED (OD-v8.5-6): `--privileged` and `--read-only` are never used (0 matches in
  `backend/app` today); a future `--read-only` root filesystem would require explicit writable `/data`
  and tmpfs exceptions and is not part of this contract.

### Deterministic 1-Click Safe Upgrade (no AI, no model calls)

- OWNER-STATED (ND-6, hardened by OD-v8.4-10): **batch identification is hash-only.** One call to
  `POST https://api.modrinth.com/v2/version_files` with
  `{"hashes": ["<sha512>", ...], "algorithm": "sha512"}` identifies unknown/CurseForge jars. One
  call to `POST https://api.modrinth.com/v2/version_files/update` with the same hashes plus
  `"loaders": ["<loader>"]`, `"game_versions": ["<target_mc>"]`,
  `"version_types": ["release"]` resolves target builds. Upgrade lookups MUST use SHA-512 hashes or
  an exact `project_id` already recorded in `onx-jars.lock.json`; they NEVER guess by filename or
  slug. Both endpoints are additive to the existing Modrinth client, which today issues GET requests
  only.
- OWNER-STATED (ND-6): **pack short-circuit.** When upgrading a modpack version A -> B, diff the two
  `modrinth.index.json` manifests (after the dedicated-server filter) for authoritative
  add/remove/update; use `/version_files/update` only for loose jars with `origin: "user"`.
- OWNER-STATED (OD-v8.4-10): **environment on Version objects.** Upgrade filtering reads
  `version.environment == "client_only"` on Version responses; only when fetching `/v2/projects`
  metadata may the engine consult `project.server_side == "unsupported"`. The v8.3 rule that read
  `server_side` on Version objects is retired.
- OWNER-STATED (OD-v8.4-10): **transitive dependency BFS.** After `/v2/version_files/update`
  returns candidate target versions, walk `dependencies[]` where `dependency_type == "required"`
  breadth-first (max depth 8, max 500 resolved projects total). If a dependency specifies a concrete
  `version_id`, fetch that exact version via `GET /v2/version?ids=[...]` and verify its
  `game_versions` and `loaders` match the target. If `version_id` is null, resolve the newest
  compatible release of `project_id` for `(target_loader, target_mc)`. If any required transitive
  dependency has no compatible build, mark the root mod `blocker: missing_transitive_dependency`.
- OWNER-STATED (ND-6, amended by OD-v8.4-10): **compatibility matrix** classification, produced
  before any write:

| Class | Rule |
|---|---|
| `warning: unresolved_carried` | origin not on Modrinth (Paper/SpigotMC/Hangar plugin, `user`, `curseforge-unclassified`) and the hash is absent from `/version_files`; keep the current jar in the upgrade branch/staging directory and test it in the isolated branch container. NOT a blocker. |
| `blocker: no_target_build` | `/version_files/update` omits a KNOWN Modrinth project's hash for the target (loader, game_version) |
| `blocker: missing_dependency` | target version requires a `dependency_type == "required"` project absent from the post-upgrade set |
| `blocker: missing_transitive_dependency` | a required transitive dependency (BFS, depth <= 8, <= 500 projects) has no compatible build |
| `blocker: incompatible` | the target marks an installed project `dependency_type == "incompatible"` |
| `blocker: untrusted_host` | primary file URL host is not in the download allow-list |
| `blocker: manual_download_required` | CurseForge `downloadUrl: null` or CDN 401/403; cleared by operator drag-and-drop upload |
| `warning` | optional dependency missing |
| `add` / `remove` / `carried` / `unchanged` | user-origin jar added / removed / kept / sha512 identical |

  Only confirmed incompatibilities block. Any blocker aborts before an upgrade branch or staging
  directory is written, unless the operator unchecks/disables the blocking entry or uploads a
  manual replacement in the Upgrade Wizard. `warning: unresolved_carried` never blocks a test run.
- OWNER-STATED (OD-v8.4-6): **3-way merge inputs.** B = the pack's clean override for the path,
  read from `lockfile.base_overrides[path]` in the CAS (works in Simple, which has no Git history);
  O = the current class-B file; T = the target pack's override. On a successful upgrade to T,
  `base_overrides` is replaced with T's unmodified override hashes.
- OWNER-STATED (ND-6, made precise by OD-v8.4-10): **merge codecs.**

| File types | Merge |
|---|---|
| `.json` (json), `.yml`/`.yaml` (PyYAML safe AST), `.toml` (tomllib + tomli_w), `.properties` (canonical key=value parser) | structured key-level recursion; objects/tables recurse; scalar takes T when O == B, keeps O when T == B, keeps when O == T, otherwise flag the key |
| arrays of scalars in the structured formats | **ordered atomic sequence by default** (OD-v8.5-7): take T when O == B, keep O when T == B, keep when O == T, otherwise flag a conflict at that key path; order is preserved and duplicate elements are not dropped. Set merge (`O + (T - B) - (B - T)`) applies ONLY when `(file_relpath, dotted_key)` is in the curated `SET_MERGEABLE_ARRAY_KEYS` allow-list (default `("config/paper-global.yml", "MidTickChunkTasks.worlds")`, `("spigot.yml", "commands.silent-commandblock-console-worlds")`) |
| arrays of objects | match by primary key `id`, else `name`, else `modid`, else `Id`; when the same key exists in B, O, and T, recursively key-merge the object fields |
| `.json5`, `.snbt`, `.cfg`, `.conf`, `.js`, `.zs`, `.sk`, `.dsc`, `.mcfunction`, `.txt` | line-based textual 3-way `diff3` (never lossy JSON conversion: SNBT type suffixes like `1b`/`2.0f`/`[I;1,2]` and JSON5 unquoted keys/hex numbers would be corrupted) |

  An unresolved conflict sets the branch state to `needs_resolution`; Clean Export is refused until
  every conflict is resolved and no conflict markers remain anywhere in the tree.
- OWNER-STATED (OD-v8.5-7, default set replaced by OD-v8.7-15): **`SET_MERGEABLE_ARRAY_KEYS`** is the only
  place set semantics are allowed.
  It is a curated, versioned allow-list of `(file_relpath, dotted_key)` pairs; the normative default
  set is exactly
  `frozenset({("config/paper-global.yml", "MidTickChunkTasks.worlds"), ("spigot.yml", "commands.silent-commandblock-console-worlds")})`.
  The v8.6 default named `.properties` string values, which are never YAML/JSON arrays, so set merge
  could never fire; the v8.7 default names real YAML list keys and may be extended per plugin schema.
  Any array not listed is treated as an
  ordered atomic sequence, so adding a priority is a conflict to resolve, never a silent reorder.
- OWNER-STATED (ND-6): **one-way world upgrade safety.** `DataVersion` and `Data.Version.Id` in
  `level.dat`, Anvil `.mca` chunk migration (DataFixerUpper), and the Paper 26.1+ dimension layout
  (`world/dimensions/<ns>/<dim>/{region,entities,poi,data}` and `world/players/`) are strictly
  one-way and lazy: only loaded chunks migrate, so Nether `DIM-1` and End `DIM1` chunks may migrate
  hours later when a player enters them. Therefore a test of an upgrade must run against a
  disposable Data Template clone (quiescent clone of a stopped or RCON-flushed world; reflink or copy
  fallback with a free-space check) and a merge NEVER copies the test container's mutated world back
  to live.
- OWNER-STATED (ND-6, amended by OD-v8.4-1 and OD-v8.4-5): **Advanced Mode sequence
  (PackUpgrade / ServerVersionUpgrade):**
  1. run the compatibility matrix (hash-only, BFS dependencies), resolve blockers;
  2. create isolated branch `upgrade/<target>` from `main`;
  3. download and verify new class A binaries into CAS and build the target LEC
     (`<loader>/<mc>/<ver>`) when absent, asserting a non-empty `unix_args.txt` before
     `.onx-complete.json`;
  4. apply the 3-way merge (B from `base_overrides`, structured/diff3 codecs) and write the updated
     lockfile Format 2.1 on `upgrade/<target>`;
  5. quiescently clone live class E (`world*`) into a disposable Data Template;
  6. start an isolated branch test container from the Clean Export (5-step) of `upgrade/<target>` +
     that template, on a separate host port set;
  7. user tests in-game and inspects the console;
  8. on "Merge Upgrade to main & Refresh Live": verify no unresolved conflicts remain; merge
     `upgrade/<target>` -> `main` (lockfile + class B only; **Class C never enters Git**; never the
     live world);
  9. snapshot live Class C into the encrypted Class-C vault as a PINNED
     `class_c_snapshot_id`, persist the Refresh Journal,
     stop live (fail closed) + fsync, take a PINNED pre-upgrade backup of live class E and class A/B;
     destroy the test container and delete its mutated template;
  10. Clean-Export `main` (5-step, class D last), mount/attach the existing live class E world under
      it, start live;
  11. enforce the **4-step race-free Health Gate** below. On gate failure or operator Emergency
      Rollback: stop, restore the **atomic rollback triad** (OD-v8.5-3) — previous `main` export
      (Class A + B from `previous_main_sha`), `class_c_snapshot_id` (Class C), and the pinned
      `pre_upgrade_backup_id` (Class E) — restart, and report. On success, leave both the pre-upgrade
      backup and the Class-C snapshot pinned (see below) until **"Confirm Upgrade & Unpin Rollback
      Backup"**.
- OWNER-STATED (OD-v8.4-11, regex/timeout amended by OD-v8.7-1): **race-free Health Gate (4 steps).**
  (1) Subscribe strictly to the NEW container instance's live stdout stream starting from
  `container_started_at` (never read `logs/latest.log` from disk, which may still hold yesterday's
  `Done (` line) and wait for
  `r"^.*?\bINFO\b.*?: Done \([0-9.,]+s\)! For help, type [\"']help[\"']"`. The leading
  `.*?\bINFO\b.*?:` accepts Paper `[HH:MM:SS INFO]:`, Vanilla/Fabric
  `[HH:MM:SS] [Server thread/INFO]:`, NeoForge
  `[HH:MM:SS] [ServerMain/INFO] [minecraft/DedicatedServer]:`, and legacy Forge
  `[HH:MM:SS] [Server thread/INFO] [minecraft/DedicatedServer]:`; the trailing quote class accepts
  both `"help"` and `'help'`, and `[0-9.,]+` accepts locale comma decimals. Reuse and extend the
  readiness pipeline in `backend/app/modules/server/infrastructure/signal_detection.py:22`.
  (2) Verify the game port accepts TCP
  connections, then connect via `PersistentRCONClient` and issue `save-all flush`; wait until RCON
  returns the save confirmation AND `os.stat(level_dat_path).st_mtime >= container_started_at`,
  retrying every 500ms up to 15s while a `level.dat_new` -> `level.dat` rename is in flight. (3) Open
  `level.dat` with `gzip.open()`, parse the big-endian binary NBT compound `Data`, and verify
  `Data["DataVersion"] >= expected_target_data_version` (or `Data["Version"]["Id"] == target_mc`).
  (4) Optionally smoke-check dimensions. Paper does not flush `level.dat` immediately on `Done (`, so
  the steps 2-3 ordering is mandatory.
  **Boot timeout (OD-v8.7-1):** the whole gate is bounded by
  `health_gate_boot_timeout_seconds: int = 300` (default 5 minutes, configurable up to `900` for heavy
  modpacks). If the regex + TCP + RCON flush + `level.dat` checks do not all succeed within the
  timeout, the gate fails and triggers the automatic triad rollback. A timeout is never retried
  in-place.
- OWNER-STATED (OD-v8.4-11, extended by OD-v8.5-3, moved into P2/P3 by OD-v8.7-10): **pinned backup
  lifecycle.** `BackupModel.pinned: bool = False` ships in **P2** (schema) and is consumed by P3's
  triad rollback, not deferred to P5.5. The pre-upgrade backup stays `pinned = True` (immune to
  retention pruning and
  auto-deletion) even AFTER the Health Gate passes, because chunk migration is lazy. The
  `class_c_snapshot_id` artifact is pinned for the same window, so Emergency Rollback can restore the
  Class-C triad member. Automatic
  rollback happens ONLY if Health Gate steps 1-3 fail; once it passes, the server stays up and the UI
  shows a persistent banner: "Upgrade Active - Pre-Upgrade Rollback Snapshot is Pinned.
  [Confirm Upgrade & Unpin Rollback Backup] | [Emergency Rollback to Pre-Upgrade World]".
- OWNER-STATED (ND-6, amended by OD-v8.4-1/5 and OD-v8.5-4): **Simple Mode (1-Click Backup & Swap):**
  the Git-free 5-step pipeline in "Simple mode Git-free lockfile, staging, and crash-safe swap"
  (OD-v8.5-4): same matrix, same BFS, same `base_overrides`-based 3-way merge into
  `<server_root>.staging/` (CAS + LEC + merged class B + class D last); snapshot live Class C; persist
  the journal; stop live -> pinned
  pre-upgrade backup -> crash-safe journaled swap of binaries/configs around the stable live `world*` directory ->
  start -> race-free Health Gate -> 1-click rollback of the full triad (code from the previous root,
  Class C from `class_c_snapshot_id`, Class E from `pre_upgrade_backup_id`) on failure.

- FACT (2026-11-11, v8.3 recon - what exists today): Fabric is already fetched as the single
  server launcher jar (`backend/app/modules/server/application/services/jar_service.py:944-960`).
  Modern Forge/NeoForge already run `java -jar <loader>-installer.jar --installServer`
  (`backend/app/modules/server/application/services/installer_provisioner.py:306-393`;
  `forge_provisioner.py:84-88`; `neoforge_provisioner.py:80-84`), then persist a detected
  `run.sh`/`run.bat` startup command (`installer_provisioner.py:154-182`) and launch it as
  `["bash", "run.sh", "nogui"]`. `user_jvm_args.txt` is written by the provisioner with only
  `-Xms/-Xmx` (`installer_provisioner.py:407-412`) and by the Docker provider with `-Xms/-Xmx`,
  optional `-XX:ActiveProcessorCount`, and configured extra JVM flags (`docker.py:1275-1308`). The
  Docker CMD builder emits
  `["bash", "/data/run.sh", "nogui"]` when the startup command mentions `run.sh`/`run.bat`, else
  `["java", *flags, "-Xms..", "-Xmx..", "-jar", "/data/<jar>", "nogui"]`
  (`docker.py:194-245`). No `unix_args.txt` reference exists anywhere in the repository, so the
  argfile launch in ND-4 is new work. The Docker image is chosen by MC version only
  (`docker.py:148-191`), not by a resolved Java floor. Quilt is not a `ServerType`
  (`backend/app/modules/server/domain/value_objects.py:188-214`).

### Recon notes folded into the v8.6/v8.7 decisions

- ImportReview and AutoCommitLiveChanges stay and are hidden in Simple.
- Two-tier backups are owner-stated; they ship in P7 (v8 D-M), are fully specified by OD-v8.6-2, and are hardened by OD-v8.7-7.
- `server.properties` normalization is PROTOTYPE-REPORT; its real-Paper-boot validation is the P2 in-phase gate (D-C and prototype 3).
- Allow-list v2.3 is normative (PROTOTYPE-REPORT/ND-7/OD-v8.4-3/OD-v8.7-4); real-Paper-boot validation is the P2 in-phase gate (see Allow-list v2.3 (normative) and prototype 3).
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
  a booted server, and no 120 MB GitHub push were run; it is an in-phase P2 release gate. Config
  normalization, key-level merge, pre-commit validator, and snapshot comparison are embedded as
  normative text (PROTOTYPE-REPORT).
- OWNER-STATED (ND-1..ND-9): Prototype 4 is NOT run. No real `.mrpack` was installed, no LEC entry
  was pre-warmed, no NeoForge/Forge argfile launch (`@user_jvm_args.txt @libraries/.../unix_args.txt`)
  was executed, no offline-boot export was started with the network disabled, and no
  `level.dat` `DataVersion` upgrade or Health Gate rollback was exercised. The 2026 loader/API facts
  in this spec (Fabric Meta server-jar endpoint, `.fabric/server/**` layout, NeoForge Maven paths,
  Paper Fill v3, `.mrpack` v1 fields, Modrinth batch endpoints) are OWNER-STATED / PROTOTYPE-REPORT,
  not verified in this repository. Prototype 4 is the in-phase release gate for P5.5, not a pre-build
  design blocker.
- OWNER-STATED (OD-v8.4-1..OD-v8.4-11): Prototype 5 (red-team hardening) is NOT run and is NOT
  empirically verified. Not executed in this repository: `validate_canonical_relpath` against a real
  mixed-encoding filesystem, the hostile-executable quarantine against a real pack, the no-hardlink
  reflink/copy path under the per-`st_dev` copy lock, the hardened git flags against a hostile
  `.gitattributes` (`export-subst`, `working-tree-encoding`) and `ext::` remote, the expanded
  redirect host allow-list against live GitHub release redirects, the override-jar SHA-512
  environment filter, the CurseForge `downloadUrl: null` blocker and drag-and-drop unblock, Quilt
  `server/json` provisioning, the Forge `1.17.1..1.20.1` rejection path, Paper Fill v3 version
  groups, the dependency BFS, the quiescent `save-off`/`save-all flush` clone, the 10s lease
  heartbeat with fencing token, or the 4-step Health Gate on a real Paper boot. All of it is
  OWNER-STATED / PROTOTYPE-REPORT until a Prototype 5 run exists; Prototype 5 is the in-phase release
  gate for the hardened phases, not a pre-build design blocker.
- OWNER-STATED (OD-v8.5-1..OD-v8.5-8): Prototype 6 (second red-team remediation) is NOT run against
  a live server tree. Executed in the v8.7 session directly against the code and regexes extracted
  from this file: the Allow-list v2.3 **110-row** matrix (`MISMATCHES: 0`), the `open_safe_path_fd` /
  `resolve_safe_disk_path` `dir_fd` walk against symlinked parents and normal files, and the
  cross-loader Health Gate regex against Paper/Vanilla-Fabric/NeoForge/legacy-Forge lines plus fake
  chat lines. Still unexecuted here: the same matrix on a live server tree, the container
  `--cap-drop=ALL`/`--security-opt`/`--pids-limit=2048` flags against a real run, ordered-array merge
  conflict handling, the rollback triad on a real plugin data migration, the secret scanner against a
  real DiscordSRV/LuckPerms install, or the Simple-mode 5-step staging swap. These remain
  OWNER-STATED / PROTOTYPE-REPORT and are enforced as in-phase integration
  gates before each phase closes.
- OWNER-STATED (OD-v8.7-1..OD-v8.7-15): the Round 3 red-team fixes are verified at the specification
  level only. The 18 findings are closed in the contract; the executable checks listed under
  "Tests & Verification" are the in-phase gates that prove the implementations.
- OWNER-STATED (OD-v8.5-8, extended by v8.6): **design status vs. release verification.** The former
  "Prototype X is a prerequisite before P5.5 shipping" framing is superseded: `P1-P7` (including
  `P5.5` and `D7`) are DESIGN-COMPLETE and READY FOR BUILD, and each phase must pass its own
  integration gate (the prototype items above, re-run in-phase) before that phase closes for release.
  `P5.5` specifically executes AFTER `P2`, `P3`, and `P4` are complete; `P5` and `P5.5` may be built in
  either order once `P4` lands; `P6` follows and `P7` closes the sequence.

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
- FACT (2026-11-11 v8.5 recon, container flags): `create_args` starts at
  `backend/app/modules/server/infrastructure/providers/docker.py:412`; `--network` at `:416`;
  ownership `--label`s at `:419-423`; published ports at `:434-460`; `--memory` at `:464`;
  `--cpus`/`--cpuset-cpus` at `:468-470`; a single `-v <host>:/data -w /data` bind mount at `:475`;
  `PUID`/`PGID` env for itzg images at `:480-481`; `--user f"{uid}:{gid}"` for non-itzg images at
  `:483`. A repo-wide search of `backend/app` finds no `--cap-drop`, `--security-opt`,
  `--pids-limit`, `--privileged`, `--read-only`, or `docker.sock` (0 matches), so the OD-v8.5-6
  hardening flags are new work.
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

#### Current Behavior - v8.3 modpack/loader recon (2026-11-11)

- FACT: `ServerType` enumerates `vanilla`, `paper`, `purpur`, `fabric`, `forge`, `neoforge`,
  `spigot`, `bukkit`; there is no `quilt`
  (`backend/app/modules/server/domain/value_objects.py:188-214`), while the plugin layer already
  treats `quilt` as a mod server type (`backend/app/modules/plugin/infrastructure/addon_fs.py:8-16`)
  and Modrinth facets include it (`.../providers/modrinth.py:35-39`).
- FACT: Fabric is already downloaded as the single executable server launcher jar
  (`backend/app/modules/server/application/services/jar_service.py:944-960`), matching the ND-3
  artifact; it is written to `<server_dir>/server.jar` and launched with `-jar`
  (`.../domain/value_objects.py:319-322`), not via `.fabric/server/**`.
- FACT: Forge/NeoForge >= 1.17 are installer-based. `create_server.py` marks the server
  `PROVISIONING` (`create_server.py:107-117`, `:168-169`), the request path downloads nothing for
  them (`jar_service.py:704-731`), and a background task runs
  `java -jar <loader>-installer.jar --installServer` in the server directory
  (`installer_provisioner.py:306-393`; commands at `forge_provisioner.py:84-88`,
  `neoforge_provisioner.py:80-84`).
- FACT: After install, the provisioner detects `run.sh`/`run.bat` and persists
  `["bash", "run.sh", "nogui"]` as the startup command (`installer_provisioner.py:154-182`,
  `:389-391`), so ONX currently depends on the loader-generated shell wrapper.
- FACT: No `unix_args.txt` appears anywhere in the repository (repo-wide search: 0 matches), and no
  production code passes `@user_jvm_args.txt` on a command line (the literal exists only in a test
  fixture, `backend/tests/monitoring/test_batch3_monitoring_health.py:131`). The provisioner writes
  it with `-Xms/-Xmx` only (`installer_provisioner.py:407-412`); the Docker provider adds optional
  `-XX:ActiveProcessorCount` and configured extra JVM flags (`docker.py:1275-1308`).
- FACT: The Docker CMD builder emits `["bash", "/data/run.sh", "nogui"]` when the startup command
  mentions `run.sh`/`run.bat`, otherwise
  `["java", *flags, "-Xms..", "-Xmx..", "-jar", "/data/<jar>", "nogui"]`, and mounts exactly one
  directory at `/data` with `-w /data`
  (`backend/app/modules/server/infrastructure/providers/docker.py:194-245`, `:472-475`).
- FACT: The container image is chosen from the Minecraft version alone, not from a resolved Java
  floor: `eclipse-temurin:25-jre` for major >= 26, `21-jre-jammy`, `17-jre-jammy`, `8-jre-jammy`
  (`docker.py:148-191`). No `javaVersion`/`min_java_version` handling exists in `backend/app`.
- FACT: The Modrinth client issues GET requests only (`.../providers/modrinth.py:23`, `:89`, `:125`,
  `:168`, `:225`, `:291`); `POST /v2/version_files` and `POST /v2/version_files/update` do not exist
  (repo-wide search for `version_files`: 0 matches). Download verification is sha1 and/or sha512 with
  an https + `*.modrinth.com` host guard (`modrinth.py:187-196`, `:242-262`), and catalog installs
  refuse files with no checksum (`install_modrinth_plugin.py:161-176`).
- FACT: CurseForge has no backend provider: the registry holds only Modrinth
  (`.../providers/__init__.py:24`, `:62-64`) and `plugin_providers` defaults to `"modrinth"`
  (`backend/app/core/config.py:44`); the frontend shows a "Coming Soon" state
  (`frontend/src/server_manager/pages/PluginDetailPage.tsx:193-206`).
- FACT: There is no `.mrpack`, `modrinth.index.json`, `shaderpacks`, `resourcepacks`, `kubejs`,
  `defaultconfigs`, or `datapacks` handling in `backend/app` (case-insensitive searches: 0 matches).
  `mods/` is used only as a plugin add-on directory (`reconcile_plugins.py:42-47`, `:75`).
- FACT: Backups archive whole world/dimension folders plus `plugins/` and six config files into
  `tar.gz` and then encrypt them (`backend/app/services/backup_orchestrator.py:26-33`,
  `:453-495`); there is no backup **pin** concept and no retention pruning path
  (`backend/app/modules/backup/infrastructure/models.py:8-31`,
  `backend/app/modules/backup/domain/aggregate.py:161-179`).
- FACT: `level.dat` is only checked for existence
  (`backend/app/modules/health/infrastructure/integrity.py:233-275`); `DataVersion`, NBT parsing,
  and Anvil region handling do not exist in `backend/app` (search: 0 matches). Boot readiness is a
  literal substring match on `"Done ("`
  (`backend/app/modules/server/infrastructure/signal_detection.py:22`), with no port-accepting or
  `DataVersion` gate.
- FACT: No OS-aware free-port allocator exists: `/available-port` scans DB port values starting at
  25565 (`backend/app/api/v1/routers/servers.py:71-81`), and providers bind-check the chosen port
  (`local.py:65-76`, `start_server.py:280-307`).

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
- RESOLVED by OD-v8.6-1: the v8.5 `CONFLICT` over D9/`ADR-0015` no longer blocks anything. This
  specification is the authoritative superseding record over ADR-0015's retention of the local
  providers; `P6` is unblocked and runs as a normal phase (no D2 record, no separate ADR).

## Proposed Change

OWNER-STATED (v8 D-M): phases are cut by user-visible behavior, not internal components. Owner
order: prerequisite CI/Windows fixes first (outside this spec; not specified here), then P1, then
P2. Each phase is independently shippable and states what the user sees. Advanced is not shown in
the UI until the Git repository + clean export work in P2. Live refresh ships only with the
stop-check + rollback in P3.

**All phases are `DESIGN-COMPLETE and READY FOR BUILD` as of v8.7.** Build order is
`P1 -> P2 -> P3 -> P4 -> (P5 and P5.5 in either order) -> P6 -> P7`. Each phase is release-gated on
its in-phase verification suite, not on any open design question.

| Phase | Status | User sees | Core work |
|---|---|---|---|
| P1 | READY | Simple servers unchanged; Advanced still hidden | mode column, server-side Simple guard |
| P2 | READY (after P1) | Advanced behind a feature flag; branch Files; Save & Commit | repo, Allow-list v2.3 + Step-0 `open_safe_path_fd` + `resolve_safe_disk_path`, lockfile Format 2.1, 5 classes, 5-step clean export, structured secret scanner, 1 MiB icon / 16 MiB Class-B routing, hardened container flags, `pinned` column + `ensure_simple_baseline_lockfile` |
| P3 | READY (after P2) | Merge UI; Class-C vault + Live State Files; restart + crash-safe rollback; Advanced enabled for end users | ordered-array/key-level/AST merge, encrypted Class-C vault, Refresh Journal, journaled directory swap, rollback triad, dirty-worktree guard, native-Git UI cutover |
| P4 | READY (after P3) | Branch/test runs; ports; Data Templates | clean-export runs, joinable branch port sets, concurrency caps + resource floors, quiescent template clone |
| P5 | READY (after P4) | GitHub connect/fetch; optional webhook | hardened git flags, URL validation, fetch-first sync, HMAC, non-fast-forward main, fine-grained PAT / Ed25519 deploy key |
| P5.5 | READY (after P2+P3+P4) | Install/import a modpack; loader picker; 1-Click Upgrade wizard with Health Gate | `.mrpack` engine, LEC incl. Paper `paper/{mc}/{build}`, Allow-list v2.3 runtime, BFS matrix, 3-way merge + `SET_MERGEABLE_ARRAY_KEYS`, per-file `base_overrides`, Simple-mode host lockfile + crash-safe staging, backup-before-merge, race-free Health Gate, triad rollback |
| P6 | READY (after P5/P5.5) | Docker-only creation; local providers gone | D9 consolidation; supersedes ADR-0015 (OD-v8.6-1) |
| P7 | READY (after P6) | Two-tier backup controls | Tier 1 local snapshots + Tier 2 portable archives, retention, cross-tier restore (OD-v8.6-2) |
| D7 conversion | READY (after P2/P3) | Simple <-> Advanced conversion | Simple -> Advanced in place; Advanced -> Simple to a new server (OD-v8.6-3) |

**Phase dependency order (OD-v8.5-8).** `P5.5` executes AFTER `P2`, `P3`, and `P4` are complete: P2
supplies the CAS, lockfile Format 2.1, Allow-list v2.3, and LEC/Clean Export hooks; P3 supplies the
encrypted Class-C vault, the 3-way/ordered-array merge engine, the Refresh Journal, and the rollback
triad; P4 supplies isolated branch test runs, Port Sets, and quiescent Data Templates. `P5` (GitHub
sync) and `P5.5` may be built in either order once `P4` lands. This supersedes the v8.4 header claim
"P5.5 READY FOR BUILD after P2".

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

- **User sees:** Advanced appears in the creation chooser behind a feature flag (enabled for end
  users in P3 once Merge + Live Restart Refresh exist); an Advanced server opens Files with
  branch selection and Save & Commit. Live refresh and branch/test runs are not built yet.
- Advanced servers get a native Git repository. The Git directory lives outside the server tree
  (D-G). `main` is created eagerly with an initial commit of the allow-listed class-B files and
  class-A lockfiles; it cannot be removed (D4-v5/v8).
- File ownership (D-A/D-B, hardened by OD-v8.4-3, OD-v8.5-1/5, and OD-v8.7-4/6): implement the five
  classes and the explicit allow-list per "Allow-list v2.3 (normative)". Run
  `validate_canonical_relpath()` (Step 0) before any classification, lockfile parse, staging, or
  export; route every filesystem read/write/copy/delete/archive extraction through
  `open_safe_path_fd()` (descriptor-relative `O_DIRECTORY|O_NOFOLLOW` hops, Windows reparse-point
  rejection) and/or `resolve_safe_disk_path()`; reject case-fold collisions with
  `CaseCollisionError`; reject hostile executables under config roots with
  `HostileExecutableError` on import (quarantine instead of blocking on Save & Commit, OD-v8.7-12).
  Ignore everything by default; track only explicitly allowed paths. Code
  jars live in the sha256 CAS; Git tracks only their lockfile (`onx-jars.lock.json`, Format 2.1 per
  ND-2/OD-v8.4-6: `format`/`mc`/`loader`/`lec`/`modpack`/`base_overrides`/`files[]`), never the jar
  bytes. Class C never enters a worktree; class D is injected; class E is never tracked. Cryptographic
  keys and voicechat secrets are Class C by OD-v8.5-1 and never reach the worktree or a commit.
- **P2 phase-dependency additions (OD-v8.7-10, fixes R11):** ship the `BackupModel.pinned` column
  migration and `ensure_simple_baseline_lockfile()` in P2, so P3's triad rollback has pinning and
  Simple servers have a host lockfile immediately. Keep the legacy versioning read models working
  until P3 swaps the UI to native Git endpoints; P2 does not half-remove them.
- Allow-list v2.3 is normative (PROTOTYPE-REPORT/ND-7/OD-v8.4-3/OD-v8.7-4); real-boot validation is
  the in-phase P2 release gate (D-B/prototype 3), not a pre-build unknown.
- Lockfile Format 2.1 (ND-2/OD-v8.4-6) and the class-A CAS binaries (ND-7) ship with the allow-list;
  the LEC tree is attached at Step 3 of the export (ND-3) including the NeoForge/Forge/Quilt
  `unix_args.txt` argfile launch (ND-4/OD-v8.4-9) and Paper `cache/**`+`versions/**`
  (OD-v8.7-11).
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
- Save & Commit validation (D-C/D-E, extended by OD-v8.7-3): normalize `server.properties` (strip
  `#Minecraft server properties` header and `Properties.store()` timestamp comment, sort keys, remove
  class-D keys; PROTOTYPE-REPORT, not yet validated against a real Paper boot); reject config files
  that contain conflict markers or fail to parse. Run the **Structured & Pattern Secret Scanner**
  (OD-v8.7-3) over every staged Class-B file: private-key headers, Discord/Slack webhook URLs, Discord
  bot tokens, GitHub PATs, AWS keys, and non-placeholder sensitive config values all raise
  `SecretFileInGitForbiddenError`; the UI offers "Extract Secret to Panel Vault" to substitute
  `${ONX_SECRET_<KEY_NAME>}`. Reject any staged `.pem`/`.key`/`.p12`/`.pfx`/`.jks`/`.keystore` path.
  Never write conflict markers into a server directory.
- Clean export (D-F, OD-v8.4-2, OD-v8.7-3/13): build the export service using the FIXED 5-step order:
  (1) hardened `git archive --format=tar --no-worktree-attributes <sha>` extracted member-by-member
  through `validate_canonical_relpath()` with non-regular members rejected and each write target
  opened via `open_safe_path_fd()`; (2) CAS materialization of class A with `open_safe_path_fd`
  containment (no realpath-only check); (3) LEC attach (`libraries/**`, `.fabric/server/**`, or Paper
  `cache/**`+`versions/**`); (4) optional class-E Data Template overlay, plus for branch/test
  containers an ephemeral disposable Class-C snapshot overlay (OD-v8.7-13); (5) class D injected LAST
  (`server.properties` panel keys incl. `white-list=true`/`enforce-whitelist=true` for joinable test
  containers, `eula.txt`, generated `user_jvm_args.txt`, `${ONX_SECRET_*}` substitution, assert no
  `run.sh`/`run.bat`). Steps 1-4 use
  probe-verified reflink or plain copy under the per-`st_dev` copy lock; hardlinks are forbidden. The
  export has NO `.git`; it is the only container root; the editing worktree is never mounted. This
  service is built in P2; branch/test runs consume it in P4.
- Container hardening ships in P2 with the run path (OD-v8.5-6): `--user uid:gid` (never `0:0`),
  `--security-opt=no-new-privileges:true`, `--cap-drop=ALL`, `--pids-limit=2048`, and the existing
  `--memory`/`--cpus`; only `/data` is mounted (no `docker.sock`, repo, CAS, or LEC). FACT baseline is
  in "Container security contract".
- Delete `materialization_id` as a concept (D-F). Run identity is Git sha + optional Data Template.
  Consumer mapping:
  - `Runtime` (`entities.py:401-409`, `:454-457`): replace `commit_id` +
    `materialization_id` with `code_sha` + optional `data_template_id`; keep rejecting mutable
    branch references.
  - `test_runner.py` (`:401-435`, `:642-684`): replace materialize -> mount with clean export ->
    mount; no `.git`.
  - `promote_commit.py` (`:147-159`): Promote is removed; merge + live refresh replaces it; PASSED
    evidence binds to `code_sha`.
  - EvidenceBundle: the replacement binds evidence to `code_sha` +
    optional `data_template_id`; the exact legacy field list is captured by a P2 code recon before
    the migration is written (recon task, not a design question).
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
- **Not built:** merge UI, Class-C snapshot/Live State Files, live refresh (P3); branch/test runs,
  ports, Data Templates (P4); GitHub (P5); conversion.

### P3 - Merge, Class-C snapshot store, restart refresh with rollback

- **User sees:** merge controls; a Live State Files view that reads/edits live Class-C files and can
  restore a previous Class-C snapshot; a restart/refresh action that requires a stopped container and
  offers rollback. GitHub is not built yet. There is no Class-C Git branch in the UI or in Git.
- **P3 cutover (OD-v8.7-10, fixes R11):** enable the Advanced creation option for end users only in
  P3, in the same release that ships Merge + Live Restart Refresh, so an Advanced server is never
  stranded without a deploy-to-live path. Swap the Versioning UI from legacy read models to native Git
  endpoints in one atomic phase transition. The `BackupModel.pinned` column already exists from P2.
- **Class-C vault (OD-v8.7-7, fixes R7):** the snapshot store writes to the dedicated encrypted
  `<host_state_dir>/class-c-vault/<server_id>/` (AES-256-GCM), never to the shared Class-A jar CAS.
  The DB index remains `(server_id, snapshot_id, created_at, manifest_sha256)`, and the vault is a GC
  root for its blobs.
- Merge rules (D-E/D10/OD-v8.4-10/OD-v8.5-7): config merge is structured key-level for `.json`,
  `.yml/.yaml`, `.toml`, and `.properties` (scalar arrays are **ordered atomic sequences** by default;
  set merge only for `(file_relpath, dotted_key)` pairs in `SET_MERGEABLE_ARRAY_KEYS`; object arrays
  matched by `id|name|modid|Id`);
  `.json5`, `.snbt`, `.cfg`, `.conf`, `.js`, `.zs`, `.sk`, `.dsc`, `.mcfunction`, and `.txt` use
  textual 3-way `diff3`; never textual git merge on live files. Unknown formats: live wins + warning.
  Parse failure: live file untouched. Never write conflict markers into a server directory.
  Branch-to-branch code-class merge may use native git merge in the repo; export only after
  validation.
- Merge policy (D6/v8): merge into any branch including `main` is warning-only by default; tests
  never block; strict policy deferred (O). `main` protection remains (D4).
- Class C ownership (D-A/D-D, OD-v8.4-1): **Class C never enters Git.** There is no dedicated
  Class-C Git branch and no `git merge` of Class C. The panel snapshots live Class C into the
  encrypted Class-C vault (`<host_state_dir>/class-c-vault/<server_id>/`, AES-256-GCM, OD-v8.7-7;
  DB-indexed by `(server_id, snapshot_id, created_at, manifest_sha256)`) before any
  refresh/restart/upgrade swap and on demand. A dedicated Live State Files view/API reads and edits
  the live Class-C files (requiring `save-all`/RCON reload or a stopped server) and restores a
  chosen snapshot; it never targets a worktree. Plugin binary data (`*.db`, `*.sqlite`, `*.dat` and
  similar under `plugins/`) is class E and is covered by backups, not by the Class-C store. `main`
  never receives automatic commits.
- Dynamic class C (D-D/OD-v8.4-4): restart comparison uses the **canonical parsed AST** (never raw
  bytes). `server.properties`, `bukkit.yml`, `spigot.yml`, `pufferfish.yml`, `purpur.yml`,
  `commands.yml`, `help.yml`, `permissions.yml`, and `config/paper-*.yml` are never auto-promoted and
  always stay class B with key-level merge. A `dynamic-class-c` path returns to class B automatically
  when its canonical structure matches `main`, or when the operator clicks "Reset to Class B (Track
  from main)". Built-in always-C files are named directly in `CLASS_C_LIVE_STATE_REGEX`.
- Panel-owned settings (D-A/D-C/D-L, OD-v8.4-3): inject the 7 keys (`server-port`, `query.port`,
  `rcon.port`, `rcon.password`, `enable-rcon`, `enable-query`, `broadcast-rcon-to-ops`) plus
  `management-server-*` at run/export time as the authoritative final writer; never tracked.
  `server.properties` is tracked minus those keys and normalized at Save & Commit (PROTOTYPE-REPORT,
  not yet validated against a real Paper boot).
- Atomic live refresh (D-I/OD-v8.4-5): only after confirmed stopped (fail closed). Persist the
  unified Refresh Journal (`journal_id, server_id, phase, previous_main_sha, target_main_sha,
  pre_upgrade_backup_id, class_c_snapshot_id`) on disk and in the DB BEFORE touching `main` or
  stopping live. Order: (1) confirm stopped, (2) snapshot live Class C out of band, (3) stage the
  class-A/B tree sibling, (4) back up files to replace for rollback, (5) switch by the Crash-Safe
  Journaled Directory Swap (never `os.replace` on a non-empty directory, OD-v8.7-2) keeping the live
  `world*` inode, (6) start,
  (7) rollback on failure. **Rollback is the atomic triad** (OD-v8.5-3): previous `main` export
  (Class A + B) + `class_c_snapshot_id` (Class C) + `pre_upgrade_backup_id` (Class E). Merge into
  `main` never touches running live.
- Class replacement: replace class-A/B from `main`; never overwrite class-C/E; inject class-D.
  Probe-verified reflink or plain copy under the per-`st_dev` copy lock; hardlinks forbidden (D-H,
  OD-v8.4-2).
- Promote is removed (N); merge + live restart refresh replaces it; code/route/permission removal
  is in this phase.
- `main` protection: eagerly created, non-archivable, non-unprotectable, non-deletable, DB
  backstop; Files read-only/forces branch. Closes `merge_commits.py:100-101` and
  `files.py:192-208`.
- **Files:** key-level/AST merge with `SET_MERGEABLE_ARRAY_KEYS`, encrypted Class-C vault,
  Live State Files API/UI, snapshot compare, panel injection, atomic refresh, Refresh Journal,
  rollback triad, backup of replaced files, Promote removal, `main` protection, API/contracts,
  frontend merge/restart UI.
- **Migration:** Class-C snapshot store tables (or reuse of an existing snapshot table, owner's
  choice), refresh journal/rollback records. No Class-C Git branch metadata is created. No
  existing-server data migration (D8).
- **Rollback:** restore the atomic triad — backed-up class-A/B files (previous `main`), the
  pre-refresh `class_c_snapshot_id`, and the pinned `pre_upgrade_backup_id`; keep the
  Refresh Journal record; revert merge/protection behind a flag.
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
- Data Template cloning (OD-v8.4-5, hardened by OD-v8.7-8): any clone from a running container's
  `world*` is quiescent — reflink path uses `save-off` -> `save-all flush` within 30s -> clone ->
  `save-on` in a mandatory `finally`; non-reflink uses the two-pass delta clone with the hard 60s
  `save-off` cap and startup `save-on` recovery. If RCON cannot confirm, the panel refuses the hot
  clone and requires a stopped container. Clones and pack installs run asynchronously under
  `modules/operations/` and are invalid until a fsynced `.onx-complete.json` marker exists; startup
  reconciliation deletes targets lacking it. The copy lock is per target `st_dev`.
- Ports (D-L, joinability and limits fixed by OD-v8.6-4): each runtime publishes a set of host ports
  (game, rcon, query, plugin ports). In-container server-port/rcon are fixed and panel-owned class D.
  Duplicate-port checks scan every published port atomically, not just one port. Non-main branch
  containers ARE joinable by players/testers on their own port set, so gameplay can be verified
  in-game before merging to `main`.
- Joinable test exports (OD-v8.7-13, fixes R16): a branch/test container's export also overlays an
  **ephemeral, disposable copy of the latest Class-C snapshot** (`ops.json`, `whitelist.json`,
  `banned-*.json`, and Class-C plugin keys/data) and injects `white-list=true` +
  `enforce-whitelist=true` by default, unless the operator explicitly enables "Allow Public Test
  Join". Mutations to Class-C files inside the test container are discarded on destroy and never
  write back to the live vault.
- Branch concurrency and resources (OD-v8.6-4): at most **1** active non-main branch/test container
  per server by default (configurable up to `max_concurrent_branch_runs = 3`), always gated by the
  global `RuntimeAdmissionScheduler` host RAM/CPU headroom check. Each branch/test container requires
  at least **2048 MB** RAM (**1024 MB** minimum for lightweight proxy/vanilla tests) and defaults to
  the server's configured memory limit, or **4096 MB** if unspecified; `--pids-limit=2048` always
  applies. Creation beyond the cap is refused with a 409 and a clear "stop an active branch run"
  message.
- Branch permissions (OD-v8.6-4): reuse server RBAC — `server.versioning.manage` for branch
  create/merge/delete/run, `server.files.write` for branch worktree edits. No new permission model.
- Container hardening applies to every branch and test container (OD-v8.5-6): non-root
  `--user uid:gid`, `--security-opt=no-new-privileges:true`, `--cap-drop=ALL`, `--pids-limit=2048`,
  `--memory`, `--cpus`, and only the exported `/data` mount. Untrusted mod/KubeJS code therefore
  cannot gain privileges, reach the host daemon, or fork-bomb the host.
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
- Hardened git invocation (OD-v8.4-7): every subprocess passes
  `-c core.hooksPath=/dev/null -c core.fsmonitor=false -c protocol.allow=user
  -c protocol.file.allow=never -c protocol.ext.allow=never -c core.symlinks=false
  -c core.attributesFile=/dev/null -c filter.lfs.smudge= -c filter.lfs.process= -c filter.lfs.clean=`
  before the subcommand. Remote URLs are validated before spawning git: only
  `https://github.com/<owner>/<repo>(.git)?` and `ssh://git@github.com/<owner>/<repo>(.git)?` are
  allowed; `ext::`, `fd::`, `file::`, userinfo, and newlines are rejected. `git archive` uses
  `--no-worktree-attributes`; the panel scrubber strips `working-tree-encoding` and `export-subst`
  in addition to `filter`/`diff`/`merge`/`textconv`.
- Reject non-fast-forward updates to `main`. The panel generates `.gitattributes` at commit time:
  `* text=auto eol=lf` for text configs, `-text` for jars; `core.filemode true`. Jars never go to GitHub
  as plain blobs (D-A).
- Credentials (OD-v8.6-6): a GitHub fine-grained Personal Access Token (`Contents: Read and Write`,
  `Metadata: Read-only`, scoped to the single target private repository) over HTTPS, OR a per-server
  Ed25519 SSH deploy key with write access over `ssh://git@github.com/<owner>/<repo>.git`. No
  multi-tenant GitHub App is required. Credentials are encrypted at rest with AES-256-GCM through
  `modules/storage/` and injected via a transient `GIT_ASKPASS` helper script (`GIT_ASKPASS`) or
  `GIT_SSH_COMMAND`; they are never embedded in `.git/config` remote URLs, command lines, or logs.
  Rotation replaces the stored secret only; the remote URL stays credential-free.
- The 2026-11-10 prototype report does NOT cover GitHub, so the 100 MB push limit and jar-size handling
  remain ASSUMPTION (external, unverified); jars never travel as plain blobs (D-A + CAS).
- **Files:** GitHub remote/auth/webhook, fetch/push, sync commands/queries, connection UI,
  panel-generated `.gitattributes`, contracts.
- **Migration:** remote/connection metadata. No existing-server data migration (D8).
- **Rollback:** disconnect GitHub and disable webhook processing; keep local Git history.
- **Not built:** other Git hosts, interactive conflict UI.

### P5.5 - Modpacks, Loader Environment Cache, and 1-Click Safe Upgrade

- **User sees:** both modes can install or import a Modrinth `.mrpack` (or a CurseForge zip, adapted);
  the wizard shows the loader, Minecraft version, and a compatibility list before anything is written.
  A "1-Click Upgrade" wizard runs the compatibility matrix, tests the target on a disposable copy of
  the world, then merges and refreshes live behind a Health Gate with an explicit Rollback.
- **Phase dependency (OD-v8.5-8, updated by OD-v8.7-10):** P5.5 executes AFTER P2, P3, and P4 are
  complete and builds the installer/provisioner/matrix/wizard on top of their CAS, lockfile
  Format 2.1, Allow-list v2.3, Class-C vault, merge engine, Refresh Journal, isolated test runs,
  Port Sets, and Data Templates. `P5` and `P5.5` may be built in either order once `P4` lands; phase
  order after P5.5 is unchanged and P6/P7 numbering and the D9 caveat are unaffected.
- Backend work: `.mrpack` reader/validator, `InstallPlan`, dedicated-server filter, override layers
  with the SHA-512 `environment == "client_only"` drop, CurseForge adapter with
  `CurseForgeApiKeyMissingError` and `blocker: manual_download_required` drag-and-drop unblock, LEC
  store + pre-warm builder (strict `libraries/**` / `.fabric/server/**` payload, builder-root
  cleanup), Java-floor resolver, argfile launch (NeoForge/Forge/Quilt), lockfile Format 2.1
  read/write including `base_overrides` CAS storage, hash-only batch Modrinth client, dependency BFS
  (depth <= 8, <= 500), compatibility matrix with `warning: unresolved_carried`, 3-way merge with
  structured/diff3 codecs plus ordered-array default and `SET_MERGEABLE_ARRAY_KEYS`, upgrade branch
  orchestration, per-file `base_overrides` advancement (OD-v8.7-9), `BackupModel.pinned`
  (already shipped in P2), `level.dat` gzipped big-endian NBT `DataVersion` reader, the 4-step
  race-free Health Gate with `health_gate_boot_timeout_seconds`, and the triad rollback (Class A/B +
  `class_c_snapshot_id` + `pre_upgrade_backup_id`).
- Loader provisioning: extend `ServerType` with Quilt (`/server/json` + generated `unix_args.txt`)
  and keep Fabric/Forge/NeoForge; Forge is restricted to `1.17.1 <= mc <= 1.20.1`
  (`UnsupportedForgeVersionError`); replace the persisted `bash run.sh nogui` startup command with
  the argfile launch for modern loaders; keep the single executable Fabric launcher jar. Paper Fill
  v3 resolves version groups and reads the full `/builds` list for a STABLE build.
  **Paper LEC (OD-v8.7-11, fixes R13):** pre-warm `paper/{mc}/{build}` on the host with
  `java -Dpaperclip.patchonly=true -jar paper-{mc}-{build}.jar`, snapshotting `cache/**`,
  `versions/**`, and `libraries/**`; Clean Export Step 3 attaches them so Paper boots fully offline.
- Simple mode gets the same pack install and the Git-free 5-step staging swap (OD-v8.5-4) using the
  **host** `<host_state_dir>/server-meta/<server_id>/onx-jars.lock.json` (OD-v8.7-5) and
  `base_overrides` as the 3-way ancestor; it does not get Git branches, so its upgrade is
  staging-dir based, its Class C is snapshotted out of band, and its rollback restores the full triad
  (code + `class_c_snapshot_id` + world).
- **Quiesce & backup BEFORE merging to `main` (OD-v8.7-14, fixes R17):** in the "Merge to `main` &
  Refresh Live" sequence, record `previous_main_sha` in the Refresh Journal, stop the live container,
  and take the pinned `pre_upgrade_backup_id` and `class_c_snapshot_id` **before** fast-forwarding or
  merging `upgrade/<target>` into `main`. A version-bump refresh from any source (manual branch merge,
  GitHub push) is promoted to this same Full Upgrade Refresh Path whenever `(mc, loader.id,
  loader.version)` differs from the deployed live lockfile.
- **Files:** `jar_service.py`, `installer_provisioner.py`, `forge_provisioner.py`,
  `neoforge_provisioner.py`, new modpack/LEC/upgrade services, new `modules/operations/` async
  worker package, `PersistentRCONClient` for the flush/Health Gate, `providers/docker.py` CMD
  builder and security flags, server domain `value_objects.py`/`installer.py`, plugin provider
  `modrinth.py` (POST
  endpoints, hash-only), versioning clean-export/merge services, backup pinning
  (`backup/infrastructure/models.py`), health gate + NBT reader, API routers/schemas/contracts,
  frontend install wizard + upgrade wizard + mods/pack pages.
- **Migration:** lockfile Format 2.1 (new files only, D8), LEC metadata, backup `pinned`
  column/flag migration, Class-C snapshot store tables. No data migration of existing servers (D8).
- **Rollback:** keep the old `run.sh` startup path behind a flag while the argfile launch is verified;
  an upgrade can always be rolled back to the atomic triad (previous code + `class_c_snapshot_id` +
  pinned `pre_upgrade_backup_id`); disable pack install by flag.
- **Not built:** other pack formats (Technic, ATLauncher, MultiMC), client-pack distribution, a public
  pack browser, automated CurseForge API key onboarding.

### P6 - Docker-only consolidation (READY — OD-v8.6-1)

- **Status:** `DESIGN-COMPLETE and READY FOR BUILD` after `P5`/`P5.5`. The former D2/ADR blocker is
  removed by OD-v8.6-1.
- **User sees:** Docker-only creation; local provider choices gone.
- Stop allowing new local servers (LocalLinux/LocalWindows; tmux fallback), provide a local-to-
  Docker migration path, and delete local provider code only after migration is verified.
  OWNER-STATED (v7/v8 D-M): Docker is the only runtime; no server runs without Docker.
  Windows-hosted servers run as Docker containers too. Local-provider unit tests are temporary and
  are deleted with the providers in P6.
- Governance (OD-v8.6-1): this specification is the authoritative superseding record over
  `ADR-0015`'s retention of the local providers
  (`docs/decisions/0015-runtime-entity-and-server-provider-relationship.md:16-23`). No D2 decision
  record and no separate ADR are required; governance paperwork is waived exactly as it was for
  P1-P5.5. `ADR-0015` is marked superseded-by-this-specification at phase start.
- Enforce the OD-v8.5-6 container security contract on the single remaining runtime: non-root
  `--user uid:gid` (never `0:0`), `--security-opt=no-new-privileges:true`, `--cap-drop=ALL`,
  `--pids-limit=2048`, `--memory`, `--cpus`, and only the isolated `/data` bind mount. Removing local
  providers must not weaken these flags. The enforcement migration adds the missing flags to
  `providers/docker.py` (recon: only `--network`, labels, ports, `--memory`, `--cpus`, `/data`
  mount, PUID/PGID and `--user` exist today at `:412-483`; `--cap-drop`, `--security-opt`,
  `--pids-limit`, `--privileged`, `--read-only` and any docker-socket mount are absent).
- **Migration evidence gate:** a server counts as migrated only when it is created, started, stopped
  and restored as a Docker container with all hardening flags present; local code is deleted only
  after every non-test local server has this evidence (D8: current servers are test/dummy data, so
  in practice the gate is the test suite plus one real container round-trip).
- **Files:** create/import validation, provider factory/registry, local providers, console-stream
  tmux path, migration tooling, contracts, frontend provider choices, `providers/docker.py` flags.
- **Migration:** per-server data migration plan; no schema change assumed. Add
  `--cap-drop=ALL`, `--security-opt=no-new-privileges:true`, `--pids-limit=2048` to the container
  arg builder.
- **Rollback:** keep local code/registration until final deletion; gate creation by flag/config.
- **Not built:** local-code deletion before migration evidence, remote/cloud consolidation.

### P7 - Two-tier backups (READY — OD-v8.6-2)

- **Status:** `DESIGN-COMPLETE and READY FOR BUILD` after `P6`. Fully specified by OD-v8.6-2.
- **User sees:** two independent backup controls per server — fast local operational snapshots and
  portable disaster-recovery archives — each with its own retention and restore path.
- **Tier 1 — Fast Operational Snapshots (local host tier):**
  - **Scope:** Class E (`world*` plus plugin binary DBs) + a Class-C snapshot (`ops.json`,
    `whitelist.json`, keys, live plugin data) + the current `onx-jars.lock.json` and Class B config
    state. This is the same triad used by rollback, so a Tier-1 restore is a code+state+world swap.
  - **Mechanism:** quiescent clone — reflink path uses `save-off` + `save-all flush` via RCON (or a
    stopped container); non-reflink running servers use the two-pass delta clone with a hard 60s
    `save-off` cap and startup `save-on` recovery (OD-v8.7-8). Copies run under the **per-`st_dev`**
    storage copy lock (D-H). The snapshot is finalized with a fsynced `.onx-complete.json` marker
    written last; an incomplete marker means the snapshot is invalid and is discarded.
  - **Retention:** keep the last **5** unpinned Tier-1 snapshots per server, FIFO-pruned when the
    6th succeeds. Snapshots with `pinned = True` (e.g. the P5.5 pre-upgrade rollback snapshot) are
    excluded from the cap of 5 and are never auto-pruned until the operator explicitly unpins them.
    Both the 5 unpinned and all pinned snapshots are GC roots (OD-v8.7-7).
  - **Restore semantics:** atomic stop -> 3-part triad swap (Class A/B + Class C + Class E) -> start,
    reusing the P3 rollback triad and the Crash-Safe Journaled Directory Swap (OD-v8.7-2). A failed
    swap rolls back to the pre-restore triad.
- **Tier 2 — Portable Disaster-Recovery Archives (cold/external tier):**
  - **Scope:** a full self-contained archive (`.tar.zst` preferred, `.tar.gz` supported) containing
    Class E, Class C, Class B, `onx-jars.lock.json`, and an optional
    `include_cas_jars: bool = False` toggle. The default stays lightweight (lockfile only, public
    jars re-hydrated from Modrinth/CAS on restore); when enabled, `origin: "user"` jars are bundled
    because they cannot be re-downloaded.
  - **Storage/encryption (OD-v8.7-7, fixes R8):** written locally or uploaded to S3 through the
    existing `modules/storage/` backends. Encryption is **MANDATORY** whenever the archive contains
    Class C (`key.pem`, `ops.json`, etc.) or is uploaded to an external backend (S3). It uses
    envelope encryption: the host holds `ONX_MASTER_KEK` (env or auto-generated `0600`, checked by
    `backend/app/core/security_files.py`); each archive gets a fresh 256-bit DEK, the stream is
    encrypted in **64 KiB AES-256-GCM chunks** with a chunk-sequence nonce and a final-chunk
    authentication tag (truncation-resistant; no 64 GiB single-nonce limit), and the `KEK`-wrapped
    DEK is stored in the archive header. Local archives without Class C may stay unencrypted only
    when the operator explicitly opts out.
  - **Retention:** configurable per server, default **7 daily + 4 weekly**. `pinned = True`
    archives are exempt from pruning, and all retained local archives are GC roots (OD-v8.7-7).
  - **Cross-tier restore semantics:** extract into a verified staging directory, populate any
    bundled CAS blobs (verify SHA-256 before insertion), validate every path through
    `open_safe_path_fd()`/`resolve_safe_disk_path()`, then execute the same crash-safe triad switch
    as Tier 1. A corrupt, truncated, or path-escaping archive is rejected before anything live is
    touched.
- **Files:** backup domain/commands/repositories, `backup/infrastructure/models.py` (`pinned` column
  added in P2), provider save/restore hooks, storage backends, API/contracts, frontend.
- **Migration:** reuse the existing backup table with a `tier` discriminator plus the `pinned`
  column from P2; no data migration of existing servers (D8). Existing single-tier rows are
  classified as Tier 1.
- **Rollback:** keep the existing single-tier behavior behind a flag until both tiers are verified.
- **Not built:** remote/offsite scheduling beyond S3, backup-to-another-ONX-instance, deduplicated
  incremental archives.

## Conversion (later — specified by OD-v8.6-3)

- D7 data direction (v8 D-A): class-A code is materialized from the CAS lockfile, class-C stays
  live-owned and is snapshotted out of band (never Git), class-D is panel-injected, and class-E is
  never tracked. Conversion is wanted later and should be easy, but is NOT in P1. The
  Advanced -> Simple result has no Git or GitHub relation and also serves developers who prefer
  working by hand.
- **Simple -> Advanced is strictly IN-PLACE** on the same `server_id`, preserving the UUID, assigned
  ports, backups, and history (OD-v8.6-3, copy-first by OD-v8.7-10):
  1. Confirm the container is `STOPPED` (refuse otherwise with `HTTP 409`).
  2. Run `ensure_simple_baseline_lockfile()` (OD-v8.7-5) and take an automatic Tier-1 backup +
     Class-C snapshot (the same triad used by rollback).
  3. Scan `<server_root>` through **Allow-list v2.3**: **copy** (reflink or plain copy — never
     move/delete) Class-A jars/binaries into the host SHA-256 CAS and write the authoritative
     host `onx-jars.lock.json` in **Format 2.1**; initialize the external native Git repository (D-G)
     and create the initial commit on `main` containing `onx-jars.lock.json`, the Class-B configs
     with `server.properties` normalized, and the panel-generated `.gitattributes`. The initial
     commit also runs the Structured & Pattern Secret Scanner (OD-v8.7-3) and blocks on any secret.
  4. Create the `main` worktree, run a Clean Export of the new `main` to a scratch root, verify it
     starts, and only then flip `server.mode = ServerMode.ADVANCED`. The original Class-A jars stay
     in `<server_root>` until this verification passes; a later optional swap uses the Crash-Safe
     Journaled Directory Swap (OD-v8.7-2).
  If any step fails, the server stays Simple, the original `<server_root>` is 100% intact with all
  its jars, and the pre-conversion triad is restored.
- **Advanced -> Simple creates a BRAND-NEW Simple server** (as already decided in D7): perform a
  Clean Export of `main`, copy live Class C and Class E (`reflink` or copy under the per-`st_dev`
  storage lock), and write the authoritative host
  `<host_state_dir>/server-meta/<new_server_id>/onx-jars.lock.json` (OD-v8.7-5) with an informational
  `/data/.onx-manager/` copy — zero Git/GitHub association. The original Advanced server remains
  untouched until the operator deletes it.
- Both directions require `server.versioning.manage`; they are reversible only by running the
  opposite conversion, never by mutating `server.mode` directly.

## Future extension points (Lane E, not scope)

- Lane E, capture only: Discord integration, multi-node, and small Rust libraries only for
  MEASURED hot spots (Governance section 7: Baseline -> Profile -> Hypothesis -> Rust PoC ->
  Benchmark -> Integration test -> Cost/complexity review -> Adopt or discard).
- Lane E future note: an intermediate mode or a fourth mode for multi-node (OWNER-STATED v7).
- Private GitHub Repository sync is no longer Lane E; it is core Advanced architecture (D12-v5).
  Native Git makes other remotes technically possible, but other Git hosts/remotes are not in
  scope.
- MOD LOADERS AND MODPACKS ARE NO LONGER LANE E (ND-1, 2026-11-11): Fabric, Quilt, NeoForge, Forge,
  `mods/**/*.jar`, and `.mrpack` modpacks are core architecture for both modes and are specified in
  "Modpack Engine, Loader Provisioning (LEC), and 1-Click Safe Upgrade (v8.5 normative)". They are
  built in P5.5.
- Lane E (idea only, not designed): a public modpack browser beyond Modrinth/CurseForge import, and
  server-side distribution of client packs; the owner finds them useful, they are outside this spec.
- Keep extension points open; none of these are in scope for P1-P7.

## Affected Components

- Server domain/persistence: mode value object, `servers.mode`, lifecycle, read models,
  create/import.
- File ownership/storage: five classes (A-E), explicit Allow-list v2.3, Step-0 lexical
  canonicalizer (`validate_canonical_relpath`) plus descriptor-relative containment
  (`open_safe_path_fd`) and `resolve_safe_disk_path`, hostile-executable quarantine (hard abort on
  import, non-blocking on Save & Commit), Structured & Pattern Secret Scanner
  (`SecretFileInGitForbiddenError` + `${ONX_SECRET_*}` substitution), allow-list evaluation engine,
  normalization, hardened Git invocation, eula generation at export, sha256 CAS + Git lockfile,
  `server.properties` normalization, encrypted Class-C vault, class-D panel injection.
- Versioning: real Git engine, branches/worktrees, 5-step clean export, commits, structured/diff3
  config merge with ordered scalar arrays and `SET_MERGEABLE_ARRAY_KEYS`, canonical-AST snapshot
  comparison, Save & Commit validation, `main` protection, one
  repo write lock, Refresh Journal, Promote removal.
- Runtime/evidence: clean-export container root; run identity `code_sha` + optional
  `data_template_id`; remove `materialization_id`; update Runtime, EvidenceBundle, test_runner,
  promote, materialization tables/repositories, and materialized-file route; new
  `modules/operations/` async worker with lease heartbeat/fencing.
- Files: branch/worktree resolution over the allow-list, `main` read-only protection, Save &
  Commit, Live State Files view for Class C, no class-C/D/E data in the worktree.
- Providers: `DockerProvider` remains; `LocalLinuxProvider`, `LocalWindowsProvider`, provider
  factory local branches, and their unit tests are removed in P6. Container identity is resolved by
  OD-v8.5-6: non-root `--user uid:gid` (default host uid when non-zero, else `1000:1000`, never
  `0:0`), `--security-opt=no-new-privileges:true`, `--cap-drop=ALL`, `--pids-limit=2048`, and only the
  isolated `/data` mount (`docker.py:475`, `:483` are today's baseline).
- Frontend: `ServerShell`, create/import wizard, branch context, Files, Versions, merge/Class-C
  snapshot/restart UI, branch/test runs, port sets, Data Templates, GitHub connection, Promote
  removal, Executable Script Review Warning, and the pinned-rollback banner with
  "Confirm Upgrade & Unpin Rollback Backup".
- Contracts: mode, Allow-list v2.3, clean export, merge policy, live refresh order, Refresh
  Journal, repo write lock, port set, GitHub sync + credentials, Simple guard, Promote
  route/permission removal, rollback triad, Simple-mode host lockfile + crash-safe staging, branch
  concurrency/resource floors (`--pids-limit=2048`), 1 MiB icon / 16 MiB Class-B routing, structured
  secret scanner, dirty-worktree/branch-runtime guards, two-tier encrypted backup, copy-first D7
  conversion, cross-loader Health Gate regex + boot timeout.
- Backups (P7/OD-v8.6-2, hardened by OD-v8.7-7): Tier-1 local operational snapshots (Class E + Class
  C + lockfile + Class B, two-pass quiescent clone with a 60 s `save-off` cap, `.onx-complete.json`
  marker, 5 unpinned retention) and Tier-2 portable DR archives (`.tar.zst`/`.tar.gz`, **mandatory**
  64 KiB chunked AES-256-GCM envelope encryption when they contain Class C or go to S3,
  `include_cas_jars` default false, 7 daily + 4 weekly), with `BackupModel.pinned` (shipped in P2), a
  `tier` discriminator, complete GC roots, and crash-safe triad restore for both tiers.
- Modpack engine (P5.5): `.mrpack` reader/validator (`modrinth.index.json`), dedicated-server
  `env.server` filter, override layering + SHA-512 `environment == "client_only"` drop, CurseForge
  adapter (API key, `manual_download_required`), `InstallPlan`, Format 2.1 lockfile read/write with
  `base_overrides`, class-A CAS binaries, hostile-binary quarantine, expanded download-host
  allow-list with redirect validation.
- Loaders/LEC (P5.5): Quilt `ServerType` via `server/json`, Java-floor resolver (`1.17.1` -> 16,
  `1.18`-`1.20.4` -> 17, `1.20.5`-`1.21.11` -> 21, `26.1+` -> 25), LEC store + pre-warm builder with
  the strict `libraries/**`/`.fabric/server/**` payload, argfile launch for NeoForge/Forge/Quilt,
  Forge `1.17.1..1.20.1` gate, Paper Fill v3 version groups, **Paper LEC** `paper/{mc}/{build}` via
  `java -Dpaperclip.patchonly=true` (`cache/**`, `versions/**`, `libraries/**`), generated
  `user_jvm_args.txt`, offline-boot clean export.
- Upgrade engine (P5.5): hash-only Modrinth batch client, dependency BFS, compatibility matrix with
  `warning: unresolved_carried`, 3-way config/script merge (ordered arrays + `SET_MERGEABLE_ARRAY_KEYS`),
  `upgrade/<target>` orchestration,
  two-pass quiescent world clone, per-file `base_overrides` advancement, pinned pre-upgrade backup +
  pinned Class-C vault snapshot taken BEFORE merging to `main`, gzipped big-endian NBT
  `DataVersion` reader, 4-step race-free Health Gate (`health_gate_boot_timeout_seconds`), triad
  rollback, Simple-mode authoritative host `onx-jars.lock.json` + 5-step crash-safe staging swap.

## Interfaces & Contracts

- `servers` gains `mode` in create/read responses; mode is set at creation, and later changed only
  through the specified conversion flow (D7/OD-v8.6-3), never by direct mutation.
- The Simple guard is a server-side contract (D1, Unknown F resolution): versioning/Git routes and
  commands must fail with `ServerModeVersioningDisabledError` (HTTP 409) for Simple. Enforcement is a
  FastAPI router-level dependency plus an application-layer check in commands; the exact route
  set is enumerated in P1.
- Files API gains an additive branch selector; `main` is read-only or forces a working branch in
  Advanced (D4-v5). Branch edits target the branch worktree, not the live root. Class-C/D/E files
  are absent; class A is exposed through the CAS lockfile; class B is editable. Class C is exposed
  only through the Live State Files view that targets the live files (OD-v8.4-1).
- "Save & Commit" is explicit: run Step 0 `validate_canonical_relpath()`/`open_safe_path_fd()` on
  every path, check
  casefold collisions, validate Allow-list v2.3, normalize `server.properties`, move any hostile
  executable under config roots to quarantine (banner, non-blocking, OD-v8.7-12), run the Structured
  & Pattern Secret Scanner and reject secrets (`SecretFileInGitForbiddenError`), reject
  conflict markers/unparseable files, update the lockfile,
  then `git add` + `git commit`. File writes and settings changes do not create commits.
- Filesystem contract (OD-v8.5-5, hardened by OD-v8.7-6): `validate_canonical_relpath()` is lexical
  only; every read/write/copy/delete/archive-extraction under a worktree, staging tree, export root,
  or server root goes through `open_safe_path_fd()` (descriptor-relative `O_DIRECTORY|O_NOFOLLOW`
  hops, `(st_dev, st_ino)` root check, Windows reparse-point rejection) and/or
  `resolve_safe_disk_path()`, raising `SymlinkEscapeError` on any symlink component.
- Clean export contract: a pinned sha exports in the fixed 5-step order to a container root with no
  `.git`; the editing worktree is never mounted; hardlinks are never created (D-F/OD-v8.4-2). Run
  identity is `code_sha` + optional `data_template_id`; `materialization_id` is removed.
- Simple-mode contract (OD-v8.5-4/OD-v8.7-5): no `.git`/worktrees; `/versioning/*` is 409; source of
  truth is the host-only `<host_state_dir>/server-meta/<server_id>/onx-jars.lock.json` (the `/data`
  copy is informational and never trusted); upgrades use the 5-step crash-safe staging swap and
  `ensure_simple_baseline_lockfile()` auto-adopts servers that lack it.
- Branch records map 1:1 to real Git branches; `server_branches` carries operational metadata
  (port set, runtime status, console, activity) and not a Git tree replica. There is no Class-C
  branch row.
- GitHub sync (P5): connected private repository, fetch-first polling, optional HMAC-SHA256 webhook,
  delivery dedupe, 1:1 branch mapping, visible sync state (D12/D-K), hardened git flags and a strict
  remote-URL regex (OD-v8.4-7). Credentials are a fine-grained PAT or Ed25519 deploy key, stored
  AES-256-GCM-encrypted and injected via `GIT_ASKPASS`/`GIT_SSH_COMMAND` (OD-v8.6-6).
- Merge guards (OD-v8.6-7): a merge into or from a branch whose worktree has uncommitted changes is
  refused with `HTTP 409 DirtyWorktreeError`; deleting a branch with a running container is refused
  with `HTTP 409 BranchRuntimeActiveError`.
- Class-B size contract (OD-v8.6-5/OD-v8.7-15): `server-icon.png` is capped at **1 MiB
  (1,048,576 bytes)**; any other valid Class-B text/config file from 1 MiB to 16 MiB is routed to
  `A-CAS` and tracked by SHA-256; only `server-icon.png > 1 MiB` and any file `> 16 MiB` raise
  `OversizedGitTrackedFileError` at Save & Commit and at `.mrpack` Class-B staging.
- Branch runtime contract (OD-v8.6-4/OD-v8.7-13): non-main branch containers publish their own Host
  Port Set and are player-joinable; at most 1 active branch run per server by default (up to
  `max_concurrent_branch_runs = 3`) behind `RuntimeAdmissionScheduler` (FACT: `SPECS.md` Stage D,
  alongside `admit()`), with >= 2048 MB RAM (>= 1024 MB for lightweight proxy/vanilla), default
  server memory or 4096 MB, and `--pids-limit=2048`. Exports overlay an ephemeral Class-C snapshot and
  default `white-list=true`/`enforce-whitelist=true`.
- Merge: structured key-level for json/yaml/toml/properties (scalar arrays are ordered atomic
  sequences by default; set merge only for `SET_MERGEABLE_ARRAY_KEYS`; object arrays);
  diff3 for json5/snbt/cfg/conf/js/zs/sk/dsc/mcfunction/txt; native `git merge` only for code-class
  in the repo; never textual merge on live files. Merge into any branch, including `main`, is
  warning-only by default; tests never block; strict policy deferred (D-E/D6/O).
- Live refresh (D-I/OD-v8.4-5/OD-v8.5-3/OD-v8.7-2/14): merge into `main` never touches running live;
  live files update only after a confirmed stop, after a Class-C vault snapshot and Refresh Journal
  row, in the fixed order, with the Crash-Safe Journaled Directory Swap and the atomic triad rollback
  (Class A/B + `class_c_snapshot_id` + `pre_upgrade_backup_id`). Any `(mc, loader.id, loader.version)`
  change promotes the refresh to the Full Upgrade Refresh Path.
- Ownership: five classes and an explicit allow-list; ignore by default; the normative list is
  Allow-list v2.3 (ND-7/OD-v8.4-3/OD-v8.5-1..5/OD-v8.7-4), with real-boot validation as the in-phase P2 release
  gate (D-B). Jars and
  pack binaries use the sha256 CAS + lockfile Format 2.1, not plain Git blobs. Cryptographic keys and
  voicechat secrets are Class C, never tracked.
- Allow-list: Step 0 canonicalization, the five classes plus the CAS-binary class are evaluated in
  the stated order; unmatched paths are class E; `onx-jars.lock.json` is the class-A pointer, not
  class B; `eula.txt` and `user_jvm_args.txt` are generated at export.
- `onx-jars.lock.json` Format 2.1 (with `base_overrides`) is the only supported format; a lockfile
  without `format: 2` and `base_overrides` is a Save & Commit error and a clean-export error, never
  silently upgraded; Format 1/2 lockfiles are rejected.
- `Runtime` rejects mutable branch references as `commit_id` (`entities.py:401-409`); a run resolves
  a concrete sha first. A worktree referenced by a run is locked (D-J).
- Modpack install contract (P5.5): an upload/import of `.mrpack` yields an `InstallPlan` before any
  write; lockfile Format 2.1 is the only record of class-A content plus `base_overrides`;
  `env.server == "unsupported"` files never enter CAS; `client-overrides/**` is never applied on a
  server; override jars reporting `environment == "client_only"` are dropped; a compatibility-matrix
  blocker aborts the upgrade before a branch or staging directory exists.
- Loader launch contract (P5.5/OD-v8.7-11): NeoForge/Forge/Quilt containers start with the argfile
  command and the exported root as working directory; Paper starts from `paper-{mc}-{build}.jar` with
  its pre-warmed `cache/**`/`versions/**`/`libraries/**` attached;
  `run.sh`/`run.bat`/`ServerStarterJar` are never executed;
  the LEC tree is attached at Step 3 and class D is injected at Step 5; `libraries/**` and
  `.fabric/**` are immutable for packs.
- Upgrade contract (P5.5/OD-v8.7-1): an upgrade is "done" only when the 4-step Health Gate passes
  within `health_gate_boot_timeout_seconds` (process stdout matching
  `^.*?\bINFO\b.*?: Done \([0-9.,]+s\)! For help, type [\"']help[\"']`, TCP + RCON `save-all flush` with fresh `level.dat` mtime, gzipped big-endian NBT
  `DataVersion >= target`); otherwise the atomic triad (previous code + `class_c_snapshot_id` +
  pinned `pre_upgrade_backup_id`) is restored and live restarts on
  the previous export. Both artifacts stay pinned after success until the operator clicks
  "Confirm Upgrade & Unpin Rollback Backup".
- Container contract (OD-v8.5-6): every container is created with a non-root `--user uid:gid`
  (never `0:0`), `--security-opt=no-new-privileges:true`, `--cap-drop=ALL`, `--memory`, `--cpus`,
  `--pids-limit=2048`, and exactly one `/data` bind mount; no `docker.sock`, Git repo, CAS, or LEC
  mount.
- P6 removes local-provider behavior paths and their unit tests; update
  `scripts/check-route-contract` in phase. Docker is the only runtime. This specification supersedes
  ADR-0015's retention of the local providers (OD-v8.6-1), so P6 has no governance prerequisite.
- Backup contract (P7/OD-v8.6-2, hardened by OD-v8.7-7): Tier 1 keeps the last 5 unpinned local
  operational snapshots per server (pinned exempt, FIFO pruning) and every pinned snapshot is a GC
  root; Tier 2 keeps 7 daily + 4 weekly portable archives (pinned exempt, all retained archives are
  GC roots). Tier 2 archives may be `.tar.zst` or `.tar.gz`, are **mandatorily** 64 KiB
  chunked-AES-256-GCM envelope-encrypted when they contain Class C or go to S3 (`ONX_MASTER_KEK`-wrapped
  DEK, final-chunk tag), and
  default to `include_cas_jars = False`. Both restore through the crash-safe triad; Tier 2 extracts into
  a verified staging directory and validates every path with `open_safe_path_fd()` first.
- Conversion contract (D7/OD-v8.6-3): `Simple -> Advanced` is in-place on the same `server_id` and
  requires a STOPPED container plus an automatic Tier-1 + Class-C snapshot before the Allow-list v2.3
  scan, copy-into-CAS, host lockfile write, Git init/commit, `main` worktree, Clean Export
  verification, and mode flip (OD-v8.7-10). `Advanced -> Simple`
  creates a new server from a Clean Export plus copied Class C/E and
  authoritative host `onx-jars.lock.json` (plus an informational `/data` copy), with no Git/GitHub
  association, leaving the original untouched.
  Both require `server.versioning.manage`.

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
- GitHub sync (D-K, OD-v8.6-6): non-fast-forward `main` updates are rejected; force-push is denied;
  webhook deliveries are deduped; network/credential failures need retry state. Credentials are a
  fine-grained PAT (`Contents: Read and Write`, `Metadata: Read-only`) or an Ed25519 deploy key,
  encrypted at rest with AES-256-GCM and injected via `GIT_ASKPASS`/`GIT_SSH_COMMAND`; a missing,
  revoked, or under-scoped credential fails the sync with a clear reconnect prompt and never falls
  back to an unauthenticated push.
- Plugin jar: sha256 CAS + lockfile (D-A); GitHub must never receive a plain jar blob. The icon cap
  is **1 MiB**, and any other Class-B file from 1 MiB to 16 MiB is routed to `A-CAS` (OD-v8.6-5/OD-v8.7-15).
- Duplicate ports (D-L): scan every published port atomically at creation; a conflict rejects the
  new runtime.
- Branch run source: uses the last committed state only; the UI warns about uncommitted changes not
  included (K). The `Runtime` pins an immutable sha.
- Uncommitted working-tree changes (OD-v8.6-7): each active branch has its own isolated
  `git worktree` under `.onx/worktrees/<branch>`, so switching the selected branch in the UI leaves
  that branch's uncommitted edits intact. Merging into or from a branch with uncommitted worktree
  changes is strictly refused (`HTTP 409 DirtyWorktreeError`) until the operator clicks
  **Save & Commit** or **Discard Uncommitted Changes**.
- Branch run/test runtime changes: deleted automatically; the user may save a reusable Data
  Template and start from it (P4).
- Class-B live change before restart (OD-v8.4-4): restart compares the canonical parsed AST, not raw
  bytes; a genuinely differing plugin file becomes class C, is not overwritten, and warns (D-D).
  `server.properties`, `bukkit.yml`, `spigot.yml`, `pufferfish.yml`, `purpur.yml`, `commands.yml`,
  `help.yml`, `permissions.yml`, and `config/paper-*.yml` are never auto-promoted. A dynamic-C path
  returns to Class B automatically when its canonical structure matches `main`, or via the UI
  "Reset to Class B (Track from main)" button.
- Live refresh (D-I/OD-v8.4-5/OD-v8.5-3): missing/inconclusive stop confirmation fails closed; snapshot
  live Class C out of band and persist the Refresh Journal before the switch; back up files before the
  switch; roll back the full triad if start fails.
- Restart sync: replace class-A/B from `main`; never overwrite class-C/E; inject class-D last.
  Probe-verified reflink, else plain copy under the per-`st_dev` copy lock; hardlinks forbidden.
- Deleting a branch with an active running container: refused with `HTTP 409
  BranchRuntimeActiveError` until the container is stopped (OD-v8.6-7).
- Git itself refuses to check out the same branch in two worktrees; the design must not assume
  otherwise.
- `eula.txt` absent from a container root = export bug (the panel writes it at export time).
- Custom `level-name` is class E via the anchored per-subtree alternatives (`region/`, `entities/`,
  `poi/`, `advancements/`, `stats/`, `serverconfig/`, `DIM-1`, `DIM1`, `dimensions/...`) and the
  default catch-all; those alternatives never fire under `config/`, `plugins/`, `kubejs/`,
  `datapacks/`, or the other excluded roots (OD-v8.7-4).
- Plugin binary data (`*.db`, `*.sqlite`, `*.dat`) is class E even inside class-C subtrees (denylist evaluates before class C).
- `mods/**/*.jar` is class A (ND-1). A `.jar` outside the classpath roots (`config/`, `kubejs/`,
  `scripts/`, `defaultconfigs/`) is class E and is rejected/quarantined at install time so it can
  never enter a classpath.
- Pack install (ND-5): a `formatVersion` other than `1`, a non-`minecraft` game, two loader keys, or
  `forge` with `minecraft >= 1.20.2` is a hard fail with no partial write. A rejected archive leaves
  the server root untouched (staging only).
- Pack install (ND-5/OD-v8.7-15): zip-slip, symlink entries, `..`/absolute paths, forbidden prefixes
  (`.git/`, `.fabric/`, `libraries/`, `versions/`, `logs/`), oversized totals, or a compression ratio
  above 64 on an entry larger than 16 MiB abort the import; nothing is extracted. The hard 4 GiB
  total-uncompressed and 100,000-entry caps remain unconditional.
- Pack install (ND-5/OD-v8.4-8): a download that redirects to an IP literal, a host outside the
  allow-list, or a GitHub redirect host reached from anywhere other than a
  `github.com/<org>/<repo>/releases/download/` URL fails that file; more than 5 redirect hops is a
  failure; a failed required file fails the whole plan. An optional file that fails is recorded as
  skipped with a warning.
- Attachment (OD-v8.4-2): an attempt to attach a CAS blob, LEC tree, or Data Template by hardlink is
  a programming error and must be rejected in code; a failed reflink probe leaves no partial
  destination behind (deleted before fallback), and a free-space check below
  `required_bytes * 1.10` raises `InsufficientStorageError`.
- Async operation (OD-v8.4-5): a target directory that lacks a fsynced `.onx-complete.json` marker
  is invalid and is deleted by startup reconciliation; an expired lease cannot let a second worker
  write because the fencing token must still match.
- Pack install (ND-5): `env.server == "unsupported"` files are never downloaded or written, so a
  client-only mod cannot crash the server; a pack that relies on one server-side is reported as a
  pack bug, not silently installed.
- Pack install (ND-5): two loader keys or a missing loader key is a hard fail; a `.mrpack` with an
  unknown hash algorithm is a hard fail (sha1 and sha512 are required).
- LEC (ND-3/ND-4, OD-v8.4-2): a missing LEC entry for the target loader/mc/version fails the export
  with a "LEC missing" error rather than letting the container reach Maven at boot; the operator can
  re-run the pre-warm builder. A LEC entry whose payload contains anything outside
  `libraries/**`/`.fabric/server/**` (or lacks `.onx-complete.json`) is invalid and is rebuilt.
- LEC (ND-3, OD-v8.4-2): a `.mrpack` override targeting `libraries/**` or `.fabric/**` is rejected
  before export, because the LEC tree is attached at Step 3 from the trusted host cache and class D
  is injected last, so the loader classpath stays panel-controlled.
- Argfile launch (ND-4): a missing or empty `unix_args.txt` in the attached LEC tree is an
  export/launch error; ONX never falls back to executing the loader-generated `run.sh`.
- Forge range (OD-v8.4-9): `forge` with `mc < 1.17.1` or `mc >= 1.20.2` is rejected at validation
  time with `UnsupportedForgeVersionError`; nothing is downloaded or written.
- Pack/CurseForge (OD-v8.4-8): a missing `curseforge_api_key` rejects the import with
  `CurseForgeApiKeyMissingError`; a `downloadUrl: null` or CDN 401/403 records
  `blocker: manual_download_required` and never crashes the parser; an operator drag-and-drop upload
  that fails hash/size verification does not clear the blocker.
- Path safety (OD-v8.4-3): any path with `..`, `.`, empty segments, `\`, `:`, NUL/CR/LF, non-NFC,
  an absolute form, or a trailing dot/space segment is rejected at Step 0 and is never classified as
  A/B/C; two paths differing only by casefold raise `CaseCollisionError`. A hostile executable under
  `config/`, `kubejs/`, `scripts/`, `defaultconfigs/`, or another hostile-executable root raises
  `HostileExecutableError` and aborts an archive import; on a worktree scan, Save & Commit, or D7 it is
  moved to `<host_state_dir>/quarantine/<server_id>/`, excluded from `git add`, and shown as a banner
  without blocking legitimate commits (OD-v8.7-12).
- Path safety (OD-v8.5-5, hardened by OD-v8.7-6): any symlink component between a trusted root and a
  target — including a symlinked root itself — raises `SymlinkEscapeError`;
  `open_safe_path_fd`/`resolve_safe_disk_path` hop each segment with `os.open(... O_DIRECTORY |
  O_NOFOLLOW, dir_fd=...)`, so swapping a directory for a symlink between validation and use cannot
  redirect a write/delete/copy outside the root. `O_NOFOLLOW` refuses a symlinked final file, and
  Windows reparse points/junctions are rejected at every segment.
- Secret leakage (OD-v8.5-1, expanded by OD-v8.7-3): the Structured & Pattern Secret Scanner raises
  `SecretFileInGitForbiddenError` and blocks commit/D7/push for a private-key header, a Discord bot
  token, a Discord/Slack webhook URL, a GitHub PAT, an AWS access key, a non-placeholder sensitive
  config value (bot/auth/access/refresh token, client/secret/api/private key, webhook URL, or
  mysql/mariadb/postgres/database/db/redis/rcon/smtp password), or a staged
  `.pem`/`.key`/`.p12`/`.pfx`/`.jks`/`.keystore` path. The UI can replace the literal with
  `${ONX_SECRET_<KEY_NAME>}` (encrypted Class D, substituted at Clean Export Step 5).
- Key material (OD-v8.5-1): `plugins/**/*.{pem,key,p12,pfx,jks,keystore}` and
  `config/**/*.{pem,key,p12,pfx,jks,keystore}` and `voicechat/**/*.{properties,conf,json,yml}` are
  Class C — never committed, never pushed, never overwritten on refresh, preserved in the AES-256-GCM
  Class-C vault. A path that looks like a key but is not under `plugins/*`, `config/`, or
  `voicechat/` falls to the default catch-all (Class E), not to Git.
- Nested pack jars (OD-v8.5-2): `shaderpacks/**/*.jar` and `resourcepacks/**/*.jar` at any depth are
  Class A CAS, never Class E; the E-denylist lookahead mirrors the nested CAS pattern, so a deeper
  path such as `shaderpacks/sub/Iris.jar` cannot be captured by Step 4.
- Container hardening (OD-v8.5-6): a container request that resolves to `--user 0:0`, omits
  `--cap-drop=ALL`/`--security-opt=no-new-privileges:true`, omits `--pids-limit`, or binds anything
  other than the exported `/data` directory is rejected before `docker create`; a `docker.sock`, Git
  repo, CAS, or LEC mount is a programming error. Resource limits below the per-server minimums are
  rejected.
- Quiescent clone (OD-v8.4-5, hardened by OD-v8.7-8): an RCON `save-all flush` that does not confirm
  within 30s (or RCON disabled/unreachable) refuses the hot clone and requires a stopped container
  with `session.lock` released; `save-on` is always sent in `finally`. A non-reflink two-pass delta
  sync that exceeds the hard 60s `save-off` cap aborts the hot clone, sends `save-on` immediately, and
  requires a stopped-container clone; startup reconciliation clears any `rcon_save_off_active` flag.
- Upgrade (ND-6, OD-v8.4-10): any matrix blocker aborts before writing `upgrade/<target>` or a
  staging directory; `warning: unresolved_carried` does NOT abort (the jar is carried and tested).
- Upgrade (ND-6): an unresolved 3-way conflict sets `needs_resolution` and refuses Clean Export; a
  conflict marker anywhere in the tree is a hard error.
- Upgrade (ND-6, OD-v8.4-11/OD-v8.5-3/OD-v8.7-1): a Health Gate failure (container exited, no
  process-scoped `Done (`, RCON flush/mtime failure, `DataVersion < target`, or exceeding
  `health_gate_boot_timeout_seconds`) stops the container and restores the
  atomic triad (previous code + `class_c_snapshot_id` + pinned `pre_upgrade_backup_id`); live never
  keeps a half-upgraded world or post-upgrade Class C under a pre-upgrade jar.
- Upgrade (OD-v8.5-3): a rollback that restores only the jar is a defect; if `class_c_snapshot_id` or
  `pre_upgrade_backup_id` cannot be restored, the server stays STOPPED and the operator is told which
  member failed — never a partial restore marked successful.
- Upgrade (OD-v8.5-7): an order-dependent scalar array (priority chain, load order, MOTD lines) whose
  O and T both differ from B is a conflict, not an automatic set union; duplicates are preserved as
  data. Only `SET_MERGEABLE_ARRAY_KEYS` pairs are set-merged.
- Upgrade (ND-6): the test container's mutated world is disposable and is deleted; it is never copied
  back into live, because world upgrade is one-way and lazy.
- Upgrade (ND-6, OD-v8.4-10): `curseforge-unclassified` and non-Modrinth Paper jars are surfaced as
  `warning: unresolved_carried`, not dropped and not blocked.
- Simple mode upgrade (ND-6/OD-v8.5-4): a failed swap restores the previous `<server_root>` (not
  `.staging/`), the `class_c_snapshot_id`, and the `pre_upgrade_backup_id`; the
  live world directory is never replaced by the staging copy. A staging root lacking
  `.onx-complete.json`, or a host `onx-jars.lock.json` lacking `format: 2` + `base_overrides`,
  is invalid and blocks the swap.
- Existing servers are deleted by the owner (D8); no migration or legacy repair is designed.

## Tests & Verification

Test ideas only; no CI claims. Exception: the allow-list v2.3 matrix below is executable — it was
extracted from this file and run this session with **110 rows** and 0 mismatches, alongside a
`dir_fd` symlink-containment check and a cross-loader Health Gate regex check.

- P1: mode default `simple`; creation through `create_server.py`/`import_server.py`; versioning
  routes and commands return `ServerModeVersioningDisabledError` (409) for Simple; db revision
  constants and both gate scripts; nav hidden in Simple; Advanced hidden in P1 and exposed only
  behind the P2 feature flag, enabled for end users in P3.
- P2: Advanced gets a real Git repo with `main`; allow-list commits only allowed paths; nested
  `.git`/filters/symlinks stripped; branch create/delete maps to Git; one worktree per branch;
  Save & Commit validates/normalizes and commits; class-A jars resolve from CAS via lockfile;
  class-C/D/E files absent; `materialization_id` consumers updated; clean export has no `.git`;
  every write goes through `open_safe_path_fd`/`resolve_safe_disk_path`; a staged PEM/key/token or
  sensitive config value raises `SecretFileInGitForbiddenError`; created containers carry non-root `--user`,
  `--cap-drop=ALL`, `--security-opt=no-new-privileges:true`, `--pids-limit=2048`, and only `/data`.
- Allow-list v2.3 executable matrix (110 rows, 0 mismatches required). Assertions are on the
  `validate_canonical_relpath`, `open_safe_path_fd`, and `resolve_safe_disk_path` functions and the
  CLASS_*_REGEX definitions extracted directly from "Allow-list v2.3 (normative)". `REJECT-PATH` means Step 0 raised `ValueError`; `QUARANTINE` means
  `HOSTILE_EXECUTABLE_QUARANTINE_REGEX` matched; `A-LOCKFILE` means the exact lockfile pattern.
  Any row that flips class is a regression test failure.

```tsv
path	expected
mods/foo/../../../outside.jar	REJECT-PATH
mods/../../etc/cron.d/pwn.jar	REJECT-PATH
config/../../../etc/cron.d/evil.yml	REJECT-PATH
kubejs/server_scripts/../../../../tmp/pwn.js	REJECT-PATH
datapacks/../../../../tmp/tick.mcfunction	REJECT-PATH
plugins/Essentials/../../../../tmp/pwn.yml	REJECT-PATH
plugins/foo.jar\n	REJECT-PATH
mods\foo.jar	REJECT-PATH
mods/./foo.jar	REJECT-PATH
/etc/passwd	REJECT-PATH
plugins//foo.jar	REJECT-PATH
plugins/foo.jar 	REJECT-PATH
plugins/foo.jar.	REJECT-PATH
config/foo:bar.yml	REJECT-PATH
config/foo\x00.yml	REJECT-PATH
config/evil.jar	QUARANTINE
config/nested/evil.class	QUARANTINE
defaultconfigs/evil.jar	QUARANTINE
kubejs/assets/evil.jar	QUARANTINE
kubejs/server_scripts/evil.jar	QUARANTINE
scripts/evil.jar	QUARANTINE
datapacks/pack/evil.jar	QUARANTINE
patchouli_books/book/evil.jar	QUARANTINE
schematics/evil.jar	QUARANTINE
config/exploit.sh	QUARANTINE
onx-jars.lock.json	A-LOCKFILE
plugins/X/lib/foo.jar	E
plugins/X/data/foo.jar	E
plugins/X/data/foo.class	E
foo.so	E
foo.dll	E
foo.nbt	E
plugins/X/data/foo.csv	E
cache/mojang_1.21.1.jar	E
libraries/net/neoforged/neoforge/26.3.0.102/neoforge.jar	E
.fabric/server/fabric-loader.jar	E
plugins/X/playerdata/abc.dat	E
plugins/X/world.db	E
plugins/X/world.db-wal	E
plugins/X/world.db-shm	E
plugins/X/cache/temp.yml	E
plugins/JourneyMap/data/world/tile.png	E
world/level.dat	E
world/serverconfig/forge-server.toml	E
world/dimensions/minecraft/the_nether/region/r.0.0.mca	E
DIM-1/region/r.0.0.mca	E
myworld/region/r.0.0.mca	E
kubejs/probe/probe-results.json	E
kubejs/exported/tags.json	E
mods/.index/sodium.pw.toml	E
eula.txt	E
user_jvm_args.txt	E
run.sh	E
.gitattributes	E
ops.json.bak	E
paper-26.3-248.jar	A-JAR
plugins/EssentialsX.jar	A-JAR
mods/create.jar	A-JAR
mods/sub/addon.jar	A-JAR
shaderpacks/Complementary.zip	A-CAS
shaderpacks/IrisShader.jar	A-CAS
resourcepacks/OfficialPack.zip	A-CAS
resourcepacks/ModResources/pack.mcmeta	A-CAS
kubejs/assets/custom/textures/item/ruby.png	A-CAS
patchouli_books/guide/en_us/icon.png	A-CAS
schematics/house.nbt	A-CAS
schematics/castle.schem	A-CAS
blueprints/factory.nbt	A-CAS
ops.json	C
whitelist.json	C
plugins/X/data/foo.yml	C
plugins/X/playerdata/abc.yml	C
plugins/X/userdata/abc.json	C
plugins/Essentials/warps/spawn.yml	C
plugins/WorldGuard/worlds/world/regions.yml	C
plugins/Citizens/saves.yml	C
server.properties	B
server-icon.png	B
modrinth.index.json	B
config/paper-global.yml	B
config/nested/deep/foo.toml	B
defaultconfigs/ftbchunks-world.snbt	B
plugins/X/config.yml	B
plugins/Skript/scripts/main.sk	B
plugins/Denizen/scripts/quest.dsc	B
plugins/floodgate/key.pem	C
config/ssl/server.key	C
config/ssl/keystore.p12	C
plugins/Geyser-Skin/jks/client.jks	C
plugins/Essentials/config/key.pem	C
voicechat/voicechat-server.properties	C
voicechat/simple-voice-chat/voicechat-server.properties	C
shaderpacks/sub/Iris.jar	A-CAS
shaderpacks/sub/Iris.zip	A-CAS
resourcepacks/sub/deep/Pack.jar	A-CAS
resourcepacks/sub/deep/Pack.zip	A-CAS
kubejs/server_scripts/recipes.js	B
kubejs/assets/custom/lang/en_us.json	B
scripts/recipes.zs	B
datapacks/custom/data/minecraft/tags/function/load.json	B
datapacks/x/data/x/advancements/root.json	B
kubejs/data/x/advancements/q.json	B
kubejs/data/x/structures/house.nbt	A-CAS
datapacks/x/data/x/structures/tower.nbt	A-CAS
plugins/PlayerStats/stats/config.yml	B
config/somemod/stats/limits.toml	B
world/advancements/0000-0000.json	E
world/stats/0000-0000.json	E
custom_world/region/r.0.0.mca	E
custom_world/advancements/0000-0000.json	E
```

  - v8.2 regression rows retained and still asserted: `plugins/X/storage/cache.dat`=E,
    `version_history.json.bak`=E, `plugins/X/playerdata/abc.dat`=E, `mods/.connector/x.jar`=E,
    `versions/26.3/x.jar`=E, `world/players/steve.dat`=E,
    `config/mymod/cache/x.json`=E, `XaeroWaypoints/x.txt`=E, `logs/kubejs-server.log`=E,
    `crafttweaker.log`=E, `journeymap/x.json`=E, `local/x.txt`=E, `debug/x.json`=E,
    `config/x.toml.bak`=E, `forgottenrelics/defaultconfigs/x.toml`=E.
  - v8.5 regression rows retained and still asserted: `plugins/floodgate/key.pem`=C,
    `config/ssl/server.key`=C, `config/ssl/keystore.p12`=C, `plugins/Geyser-Skin/jks/client.jks`=C,
    `plugins/Essentials/config/key.pem`=C, `voicechat/voicechat-server.properties`=C,
    `voicechat/simple-voice-chat/voicechat-server.properties`=C, `shaderpacks/sub/Iris.jar`=A-CAS,
    `shaderpacks/sub/Iris.zip`=A-CAS, `resourcepacks/sub/deep/Pack.jar`=A-CAS,
    `resourcepacks/sub/deep/Pack.zip`=A-CAS.
  - Invariants asserted directly: CLASS_E must NOT match `plugins/X.jar`, `mods/X.jar`, or a root
    `server.jar`; CLASS_B must NOT match `onx-jars.lock.json`; CLASS_C must NOT match
    `ops.json.bak`; CLASS_A_JAR must NOT match `config/evil.jar`; CLASS_B must NOT match
    `kubejs/probe/x.json`; CLASS_E must NOT match `schematics/*.nbt`; CLASS_E must NOT match
    `shaderpacks/*.jar` at any depth (`shaderpacks/sub/Iris.jar`, `resourcepacks/sub/deep/Pack.jar`);
    CLASS_B must NOT match any `*.pem`/`*.key`/`*.p12`/`*.jks` under `plugins/` or `config/`, nor any
    `voicechat/**` secret; CLASS_C must match all of them.
  - Path-containment tests (OD-v8.5-5/OD-v8.7-6): `resolve_safe_disk_path` returns the target for a
    clean relative path; `open_safe_path_fd` opens the same normal file; each raises
    `SymlinkEscapeError` when a middle directory component is a symlink, when
    the root itself is a symlink, when `open_safe_path_fd` sees a symlinked final file (`O_NOFOLLOW`), when the root
    `(st_dev, st_ino)` changes, and when a casefold-swapped path escapes the root;
    `allow_create_parents=True` creates missing parents via `dir_fd` and still rejects a symlinked
    component.
  - Secret-guard tests (OD-v8.5-1, expanded by OD-v8.7-3): a staged `config/x.yml` containing
    `-----BEGIN RSA PRIVATE KEY-----`, a Discord bot token, a Discord/Slack webhook URL, a GitHub
    PAT, an AWS `AKIA...` key, or `bot-token: "MTA..."` raises `SecretFileInGitForbiddenError`; a
    placeholder value (`""`, `none`, `changeme`, `password`, `${ONX_SECRET_X}`) does not; a staged
    `plugins/floodgate/key.pem` raises it on extension alone; a staged `voicechat/...properties`
    never reaches the staging path because it is Class C. "Extract Secret to Panel Vault" rewrites
    the value to `${ONX_SECRET_<KEY_NAME>}` and Clean Export Step 5 substitutes the stored secret.
  - Cross-loader Health Gate tests (OD-v8.7-1): the regex matches Paper
    `[12:00:00 INFO]: Done (5.123s)! For help, type "help"`, Vanilla/Fabric
    `[12:00:00] [Server thread/INFO]: Done (5s)! For help, type "help"`, NeoForge
    `[12:00:00] [ServerMain/INFO] [minecraft/DedicatedServer]: Done (5,5s)! For help, type "help"`,
    and legacy Forge `[12:00:00] [Server thread/INFO] [minecraft/DedicatedServer]: Done (5.0s)! For
    help, type "help"`; it rejects chat such as `[Server thread/INFO]: <Player> Done (1.0s)!` (no
    colon-delimited `Done` line) and a line without `INFO`. A gate that exceeds
    `health_gate_boot_timeout_seconds` fails and rolls back the triad.
  - `dir_fd` containment tests (OD-v8.7-6): `open_safe_path_fd` opens a normal relative file; raises
    `SymlinkEscapeError` when a parent component is a symlink, when the root is a symlink, when the
    root inode changes between `stat` and `open`, and when the final component is a symlink;
    `allow_create_parents=True` creates missing parents through `os.mkdir(..., dir_fd=...)` and still
    refuses a symlinked component; `resolve_safe_disk_path` returns the same target for a clean path.
  - v8.7 regression rows: the 10 rows appended to the matrix cover
    `datapacks/**/advancements/**` -> B, `kubejs/data/**/advancements/**` -> B,
    `(kubejs/data|datapacks)/**/structures/*.nbt` -> A-CAS, `plugins/*/stats/*.yml` -> B,
    `config/**/stats/*.toml` -> B, and `world|custom_world` `advancements/`,`stats/`,`region/` -> E.
  - v8.7 mechanism tests: Crash-Safe Journaled Directory Swap performs `RENAME_EXCHANGE` where
    supported and otherwise the journaled 2-step rename, and startup reconciliation restores
    `live.prev` after a crash at `SWAPPING_OUT_LIVE`/`SWAPPING_IN_STAGING`; the Class-C vault is
    AES-256-GCM-encrypted and never writes into the shared jar CAS; GC marks blobs referenced by all
    branches, all Simple host lockfiles, all 5 unpinned + all pinned Tier-1 snapshots, all retained
    Tier-2 archives, and in-flight ops; Tier-2 encryption is mandatory and chunked; a non-reflink
    clone runs two passes, exceeds 60s -> abort + `save-on`, and startup clears `rcon_save_off_active`;
    `base_overrides` advances only for cleanly merged files; Paper LEC boots offline; hostile files
    are quarantined on Save & Commit but abort archive import; branch/test exports overlay Class C and
    default to whitelist enforcement; an `(mc, loader)` change promotes to the Full Upgrade Refresh;
    a Class-B file of 2 MiB is `A-CAS` while 17 MiB or an over-1-MiB icon raises
    `OversizedGitTrackedFileError`; the zip ratio is ignored below 16 MiB; and containers run with
    `--pids-limit=2048` plus a `/data` chown to the target `uid:gid`.
- P3: structured key-level merge (ordered scalar arrays by default, `SET_MERGEABLE_ARRAY_KEYS` only
  for curated pairs, object arrays) and diff3 merge; parse failure
  leaves live untouched; no conflict markers in server dirs; native Git merge only for code class;
  Class-C snapshot into the encrypted vault with no Git branch created (assert
  assert no Class-C branch ref exists); canonical-AST restart compare makes changed plugin files class C
  but never `server.properties`/`paper-*.yml`/`spigot.yml`; "Reset to Class B (Track from main)"
  clears a dynamic-C entry; live refresh order with Class-C snapshot, Refresh Journal row, stop
  fail-closed, journaled directory swap, and the atomic triad rollback (code + `class_c_snapshot_id` +
  `pre_upgrade_backup_id`); merge into `main` never touches live; `main`
  protection; Promote removed.
- P4: all runs use a clean export of a pinned sha; no `.git`; worktree lock; run identity
  `code_sha` + optional `data_template_id`; no template = fresh world incl. tests; template
  overlays class-E only; duplicate checks cover every published port; per-branch console/activity;
  Data Template clone is quiescent (`save-off`, `save-all flush`, clone, `save-on` in `finally`) and
  an unconfirmed flush requires a stopped container; target dirs without `.onx-complete.json` are
  deleted by reconciliation; long operations renew the 10s lease heartbeat with a fencing token.
- P5: GitHub connect/fetch-first; optional webhook HMAC/dedupe/redelivery; non-fast-forward `main`
  rejected; `.gitattributes`/`core.filemode`; jars never plain blobs; 1:1 branch mapping; every git
  call carries the hardened flags (`protocol.ext.allow=never`, `core.attributesFile=/dev/null`, LFS
  filters empty); `ext::`/`file::`/userinfo/newline remotes rejected; `git archive` uses
  `--no-worktree-attributes` and the member loop rejects symlinks and `.git` entries.
- P5.5: `.mrpack` happy path (index v1 -> InstallPlan -> CAS -> materialize) and hard-fail matrix
  (`formatVersion != 1`, non-`minecraft` game, zero or two loader keys, `forge` + `minecraft >=
  1.20.2`, `forge` + `minecraft < 1.17.1` -> `UnsupportedForgeVersionError`);
  `env.server=unsupported` never downloaded/stored; `env.server=optional` installed only when the
  flag is true and recorded `"optional": true`; override precedence `files[]` < `overrides/` <
  `server-overrides/` with `client-overrides/` never applied; an override jar whose SHA-512 maps to
  `environment == "client_only"` is dropped as `skipped_client_override_jar`; zip-slip/symlink/
  ratio/size/entry-count/casefold-collision rejection leaves the server root untouched; Step-0
  rejection and hostile-executable quarantine (see the 110-row matrix); expanded download-host
  allow-list enforced on the initial URL and every redirect, with GitHub release hosts allowed only
  on `releases/download/` redirects; `libraries/**` and `.fabric/**` override targets rejected.
  CurseForge: missing key -> `CurseForgeApiKeyMissingError`; `downloadUrl: null` ->
  `blocker: manual_download_required` cleared only by a hash/size-verified drag-and-drop upload;
  unclassified hashes adapted into the same plan. Lockfile Format 2.1 round-trip: `format`, `mc`,
  `loader`, `lec.key`, `modpack` block, `base_overrides` path->sha256 map, `files[]` fields, `origin`
  enum; a non-2.1 lockfile is refused by Save & Commit and by clean export; `base_overrides` advances
  **per file** only on a clean merge/operator resolution (OD-v8.7-9). LEC: missing entry fails export
  with "LEC missing" (no Maven
  at boot); pre-warm builds `fabric/{mc}/{loader}/{installer}`, `neoforge/{mc}/{ver}`,
  `quilt/{mc}/{ver}` from `/server/json` with a generated non-empty `unix_args.txt`, and
  `paper/{mc}/{build}` via `-Dpaperclip.patchonly=true` with `cache/**`+`versions/**`+`libraries/**`
  (OD-v8.7-11); the LEC payload
  contains only `libraries/**`/`.fabric/server/**`/Paper cache trees and no builder-root files;
  offline boot with the network disabled succeeds. Launch: NeoForge/Forge/Quilt container CMD is
  `java @user_jvm_args.txt @libraries/.../unix_args.txt nogui` with the exported root as working
  directory; `run.sh` is never executed or present; a missing `unix_args.txt` fails the launch.
  Java floor: resolved from Mojang `javaVersion.majorVersion` / Fill v3, not Fabric
  `min_java_version`; Paper Fill v3 resolves version groups and picks the highest STABLE build from
  the full `/builds` list, using BETA/ALPHA only with `allow_experimental_paper_builds=True`.
  Upgrade engine: hash-only `/v2/version_files` + `/v2/version_files/update` (slug lookup asserted
  absent); `version.environment` read instead of `server_side`; dependency BFS depth <= 8 and
  <= 500 projects, concrete `version_id` validated, missing transitive dependency ->
  `blocker: missing_transitive_dependency`; each matrix class (`warning: unresolved_carried`, the
  blockers, `warning`, `add`/`remove`/`carried`/`unchanged`) covered; a Paper/SpigotMC jar omitted by
  Modrinth is carried and does NOT block; pack A->B diff short-circuit; every blocker aborts before
  a branch/staging dir exists; 3-way merge from `base_overrides` B (ordered scalar arrays by default,
  `SET_MERGEABLE_ARRAY_KEYS` set merge only, object-array
  key rules and diff3 for json5/snbt/cfg/conf/js/zs/sk/dsc/mcfunction/txt) with
  `needs_resolution` and export refusal while conflict markers remain; upgrade branch test runs on a
  quiescent disposable world clone and the mutated clone is deleted; live refresh snapshots Class C
  and takes a pinned pre-upgrade backup + pinned `class_c_snapshot_id`; the 4-step Health Gate passes
  and fails (process stdout matching the cross-loader `Done ([0-9.,]+s)! For help, type "help"`
  regex, RCON flush + `level.dat` mtime, gzipped big-endian NBT `DataVersion`, optional dimension
  smoke, and the `health_gate_boot_timeout_seconds` budget); failure restores the atomic triad
  (previous code + `class_c_snapshot_id` +
  `pre_upgrade_backup_id`); both artifacts remain pinned
  AFTER success until "Confirm Upgrade & Unpin Rollback Backup"; Simple-mode authoritative host
  `onx-jars.lock.json` 5-step crash-safe staging swap rolls back the same triad.
- P6 (OD-v8.6-1): provider conformance for remaining Docker providers; no new local creation;
  migration round-trip; local provider unit tests removed; Docker is the only runtime; ADR-0015 is
  marked superseded. Container hardening (OD-v8.5-6) is asserted on every created container: non-root
  uid, `--cap-drop=ALL`, `--security-opt=no-new-privileges:true`, `--pids-limit=2048`, `--memory`,
  `--cpus`, and exactly one `/data` mount with no `docker.sock`/Git/CAS/LEC bind.
- P7 (OD-v8.6-2): Tier-1 snapshot is created under a simulated quiescent save, carries a fsynced
  `.onx-complete.json`, and prunes FIFO at the 6th success while `pinned=True` survives; Tier-2
  archive round-trips as `.tar.zst` and `.tar.gz`, defaults to `include_cas_jars=False`, bundles
  `origin: "user"` jars when enabled, and restores through a staging directory after
  `open_safe_path_fd` validation; a path-escaping or corrupt archive is rejected without
  touching live; both tier restores perform the crash-safe triad and roll back on failure; the 7 daily +
  4 weekly retention and pinned exemption hold; a Class-C-bearing archive is chunked-AEAD encrypted
  and a wrong/truncated final tag is rejected.
- v8.6 conversion/guard tests: Simple -> Advanced runs in place on the same `server_id` only when
  STOPPED, takes the automatic snapshot before the Allow-list v2.3 scan, copies (never moves) jars
  into the CAS, writes the host Format 2.1 lockfile, and
  creates `main`; a failed step restores the pre-conversion triad, leaves `<server_root>` intact, and
  keeps the server Simple.
  Advanced -> Simple creates a new server with copied Class C/E and a lockfile but no `.git`, leaving
  the original untouched. A Class-B file > 1 MiB raises `OversizedGitTrackedFileError`; merging with a
  dirty worktree returns `HTTP 409 DirtyWorktreeError`; deleting a branch with a running container
  returns `HTTP 409 BranchRuntimeActiveError`; branch-run cap/resource floors and the
  `max_concurrent_branch_runs = 3` ceiling are enforced; a second active branch run is refused with a
  409. GitHub sync asserts PAT and deploy-key injection via `GIT_ASKPASS`/`GIT_SSH_COMMAND`, no
  credential in `.git/config` or logs, and AES-256-GCM storage. Defaults assert the two
  `SET_MERGEABLE_ARRAY_KEYS` pairs only, Class-C retention 10, LEC/CAS 7-day unreferenced pruning,
  Modrinth 200-hash chunking, and `install_optional_server_files = true`.
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
- Backup retention mechanics beyond the two-tier policy fixed by OD-v8.6-2 (scheduling, S3 lifecycle
  rules, and offsite replication topology beyond the stated defaults).
- Removing local providers before a working Docker migration exists (P6), though P6 itself is
  unblocked and scheduled.
- Additional conversion modes beyond D7 (there is no third mode; the conversion mechanics are
  fixed by OD-v8.6-3).
- Windows-hosted container prerequisites and CI/Windows fixes; they are a prerequisite outside this
  spec (D-M).
- Any numeric performance or test-count claims.
- Client-side pack distribution, a public modpack browser, other pack formats (Technic, ATLauncher,
  MultiMC/Prism), and automated CurseForge API-key onboarding (P5.5 "Not built").
- Offensive security work: no penetration test, fuzzing harness, red-team exploit reproduction, or
  container-escape proof is part of this spec. The v8.4 and v8.5 decisions are design-level hardening
  only; Prototype 5 and Prototype 6 remain in-phase release gates, not pre-build blockers.

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
- Unknown C (`main` -> live sync boundary): SUPERSEDED by D-A/D-I/OD-v8.4-1. Replace class-A/B from
  `main`; never overwrite class-C/E; inject class-D; snapshot class-C out of band (never a Git
  branch); update live only after a confirmed stop.
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
- D-A..D-M: resolved by the owner on 2026-11-09; see the v8 owner section. At that time the exact
  allow-list and normalization details were assumption-level; they were later fixed by Allow-list
  v2.2 (ND-7/OD-v8.4-3), container uid is resolved by OD-v8.5-6 (non-root `--user`, never `0:0`), and
  credential choice is resolved by OD-v8.6-6.

### Resolved by owner 2026-11-11 (v8.3, ND-1..ND-9)

- Mod loaders / modpacks: resolved by ND-1 (Fabric, Quilt, NeoForge, Forge and `.mrpack` are core in
  both modes; OD-6 retired). `mods/**/*.jar` is class A.
- Lockfile: resolved by ND-2 and extended by OD-v8.4-6 (Format 2.1 with `base_overrides` is the only
  supported format; Format 1/2 are not migrated, D8).
- Loader runtimes: resolved by ND-3/ND-4 and corrected by OD-v8.4-2/OD-v8.4-9 (LEC + offline-boot
  Clean Export; argfile launch; no `run.sh`; LEC payload limited to `libraries/**` or
  `.fabric/server/**`). LEC storage root and eviction were later locked by OD-v8.6-8.
- Pack format: resolved by ND-5 and hardened by OD-v8.4-8 (`.mrpack` v1 normative; `env.server`
  filter; `files[]` -> `overrides/` -> `server-overrides/`; CurseForge is an adapter, not a second
  store).
- Upgrade mechanics: resolved by ND-6 and hardened by OD-v8.4-10/OD-v8.4-11 (deterministic hash-only
  matrix, 3-way merge, disposable Data Template, one-way `DataVersion` safety, pinned pre-upgrade
  backup, 4-step Health Gate). The batch API rate-limit policy was later fixed by OD-v8.6-8
  (200 hashes per request, `X-Ratelimit-*` backoff).
- Allow-list: resolved by ND-7 and superseded in mechanism by OD-v8.4-3 (Allow-list v2.2).
- Java floor source: resolved by ND-8 (Mojang metadata / Paper Fill v3, not Fabric
  `min_java_version`). The legacy-Forge floor was later locked by OD-v8.6-8.
- Class-D key set: resolved by ND-9 and superseded in mechanism by OD-v8.4-3 (7 explicit keys plus
  the `management-server-*` prefix).

### Resolved by owner 2026-11-11 (v8.4, OD-v8.4-1..OD-v8.4-11)

- Class-C storage: resolved by OD-v8.4-1. There is no Class-C Git branch; class-C lives in an
  out-of-band snapshot store (DB-indexed, blobs in the CAS) and is edited via Live State Files.
- Attachment mechanism: resolved by OD-v8.4-2/D-H. Hardlinks are forbidden; reflink or plain copy
  under the host-wide copy lock. Clean Export order is fixed at 5 steps, class D last.
- Path safety and allow-list: resolved by OD-v8.4-3. `validate_canonical_relpath` Step 0,
  hostile-executable quarantine, Allow-list v2.2, 7 class-D keys + `management-server-*` prefix.
- Snapshot comparison: resolved by OD-v8.4-4. Canonical AST comparison; core boot-rewritten configs
  are never auto-promoted; auto-recovery plus a UI reset.
- World cloning / journalling: resolved by OD-v8.4-5. Quiescent clone, async `modules/operations/`,
  fsynced `.onx-complete.json`, 10s lease heartbeat with fencing, unified Refresh Journal, atomic
  `os.replace` swaps.
- 3-way ancestor: resolved by OD-v8.4-6. `base_overrides` in the CAS + lockfile Format 2.1.
- Git hardening: resolved by OD-v8.4-7. Fixed `-c` flag set, remote-URL regex,
  `--no-worktree-attributes`, `export-subst`/`working-tree-encoding` scrubbing.
- Downloads / CurseForge: resolved by OD-v8.4-8. Expanded post-redirect host allow-list, override-jar
  environment filter, no embedded CurseForge key, `manual_download_required` blocker with
  drag-and-drop unblock.
- Loaders: resolved by OD-v8.4-9. Quilt `/server/json` + generated `unix_args.txt`; Forge
  `1.17.1..1.20.1`; Paper Fill v3 version groups + STABLE `/builds` selection.
- Upgrade lookup: resolved by OD-v8.4-10. Hash-only lookups, `environment` not `server_side`,
  dependency BFS (depth <= 8, <= 500), `warning: unresolved_carried`, codec split.
- Health Gate / backup pin: resolved by OD-v8.4-11. 4-step race-free gate; `BackupModel.pinned`
  ships in P5.5 and stays pinned after success.

### Resolved by owner 2026-11-11 (v8.5, OD-v8.5-1..OD-v8.5-8)

- Secrets in Git: resolved by OD-v8.5-1. Cryptographic keys and voicechat secrets are Class C; the
  Save & Commit validator raises `SecretFileInGitForbiddenError` on PEM headers or key extensions.
- Nested pack jars: resolved by OD-v8.5-2. `shaderpacks/**`/`resourcepacks/**` jars at any depth are
  Class A CAS; the E-denylist lookahead mirrors the nested pattern.
- Rollback completeness: resolved by OD-v8.5-3. Rollback is an atomic triad (Class A/B from
  `previous_main_sha`, Class C from `class_c_snapshot_id`, Class E from `pre_upgrade_backup_id`);
  both pinned artifacts survive until "Confirm Upgrade & Unpin Rollback Backup".
- Simple mode: resolved by OD-v8.5-4. Explicitly Git-free; `.onx-manager/onx-jars.lock.json` plus a
  5-step staging/atomic-swap pipeline.
- Filesystem containment: resolved by OD-v8.5-5. Lexical `validate_canonical_relpath` plus mandatory
  `resolve_safe_disk_path` (`lstat` walk, `SymlinkEscapeError`, `O_NOFOLLOW`, final containment).
- Container security: resolved by OD-v8.5-6. Non-root UID, `no-new-privileges`, `--cap-drop=ALL`,
  `/data`-only mount, `--pids-limit=512`; FACT baseline at `docker.py:412-483`.
- Scalar arrays: resolved by OD-v8.5-7. Ordered atomic sequences by default; set merge only for
  `SET_MERGEABLE_ARRAY_KEYS`.
- Phase ordering: resolved by OD-v8.5-8, extended to all phases by OD-v8.6-1/2. P1-P5.5 were
  design-complete at v8.5; v8.6 closes P6/P7/D7 as well. P5.5 after P2/P3/P4; release gated
  by in-phase integration suites rather than pre-build prototypes.

### Resolved by owner 2026-11-11 (v8.6 — Final Closure)

- Unknown D (mode conversion mechanics): resolved by OD-v8.6-3, revised by OD-v8.7-10. `Simple ->
  Advanced` is strictly in-place on the same `server_id` (stop -> `ensure_simple_baseline_lockfile` +
  automatic Tier-1 + Class-C snapshot -> Allow-list v2.3 **copy**-into-CAS + Format 2.1 host lockfile
  + native Git init/commit + `main` worktree -> Clean Export verification -> flip mode), with the
  original jars left in `<server_root>` until verification passes; `Advanced -> Simple` creates a
  brand-new Simple server (Clean Export + copy Class C/E + write the authoritative host
  `onx-jars.lock.json`) and leaves the original untouched.
- Unknown G (branch runtimes/concurrency/resources/permissions): resolved by OD-v8.6-4. Non-main
  branch containers are joinable on their own Host Port Set; default cap is 1 active branch run per
  server (configurable to `max_concurrent_branch_runs = 3`) behind `RuntimeAdmissionScheduler`;
  minimum 2048 MB RAM (1024 MB for lightweight proxy/vanilla), default server memory or 4096 MB,
  `--pids-limit=512` (raised to `2048` by OD-v8.7-15); permissions are `server.versioning.manage` and `server.files.write`.
- Unknown I (oversized binary threshold): resolved by OD-v8.6-5, revised by OD-v8.7-15. A Git-tracked
  Class-B file, including `server-icon.png`, is capped at **1 MiB (1,048,576 bytes)**. A valid
  Class-B text/config file above 1 MiB up to 16 MiB is routed to `A-CAS`; only `server-icon.png >
  1 MiB` and any file `> 16 MiB` raise `OversizedGitTrackedFileError`.
- Unknown J (GitHub credentials): resolved by OD-v8.6-6. Fine-grained PAT (`Contents: Read and Write`,
  `Metadata: Read-only`) or Ed25519 SSH deploy key, with no multi-tenant App requirement; secrets are
  AES-256-GCM encrypted at rest and injected via `GIT_ASKPASS`/`GIT_SSH_COMMAND`, never in
  `.git/config` URLs.
- Unknown L (uncommitted worktree changes): resolved by OD-v8.6-7. Per-branch worktrees keep their own
  uncommitted edits; merge with a dirty worktree is refused (`HTTP 409 DirtyWorktreeError`); deleting
  a branch with a running container is refused (`HTTP 409 BranchRuntimeActiveError`).
- P6 governance block (D9 vs ADR-0015): resolved by OD-v8.6-1. This specification supersedes
  ADR-0015's retention of the local providers; no D2 decision record or separate ADR is required and
  P6 is ready to build after P5/P5.5.
- P7 backup policy (tiers, retention, restore): resolved by OD-v8.6-2, hardened by OD-v8.7-7. Tier 1
  keeps 5 unpinned local operational snapshots (pinned exempt); Tier 2 keeps 7 daily + 4 weekly
  portable archives; both restore through the crash-safe triad, and Tier 2 always extracts through
  `open_safe_path_fd()` first. Tier-2 archives containing Class C or uploaded to S3 are mandatorily
  chunked-AEAD encrypted.
- P5.5 operational constants: resolved by OD-v8.6-8, revised by OD-v8.7-15.
  - Legacy Forge Java floor: `1.17.1` -> Java 16, `1.18`-`1.20.4` -> Java 17, `1.20.5`-`1.21.11` ->
    Java 21, `26.1+` -> Java 25, resolved from Mojang `version_manifest_v2.json -> javaVersion`.
  - LEC/CAS eviction is reference-counted against every active lockfile **and every GC root of
    OD-v8.7-7** (all branches, all Simple host lockfiles, 5 unpinned + all pinned Tier-1, all
    retained Tier-2, in-flight ops, 24 h grace); otherwise unreferenced entries older
    than 7 days are pruned only by "Clean Unused Cache" or the weekly maintenance task.
  - Class-C snapshots keep the last 10 unpinned; pinned snapshots are never auto-pruned, and all of
    them are GC roots.
  - `SET_MERGEABLE_ARRAY_KEYS` default is exactly
    `frozenset({("config/paper-global.yml", "MidTickChunkTasks.worlds"), ("spigot.yml", "commands.silent-commandblock-console-worlds")})`.
  - Modrinth batch chunking is 200 hashes per request, honoring `X-Ratelimit-*` with `HTTP 429`
    backoff.
  - `install_optional_server_files` is stored per server in the lockfile and defaults to `true`.
  - The pinned upgrade rollback window is indefinite until "Confirm Upgrade & Unpin Rollback Backup",
    with a reminder badge after 72 hours of healthy uptime.
- Class A/B allow-list and `server.properties` normalization: v2.3/v1 are normative (v2.3 by
  OD-v8.7-4); real-boot validation is the in-phase P2 release gate (D-B/D-C), not an open design question.
- Reflink behavior on ext4/ZFS: the mechanism is decided (probe, then reflink or plain copy under the
  per-`st_dev` copy lock, never hardlink); the probe result is measured during the P2 in-phase gate
  (D-H), not a design unknown.
- Class-C vault retention: resolved by OD-v8.6-8 (10 unpinned), stored AES-256-GCM-encrypted at
  `<host_state_dir>/class-c-vault/<server_id>/` (OD-v8.7-7) with complete GC-root marking.
- Storage copy-lock implementation: per target filesystem `st_dev` (OD-v8.7-8); CurseForge key
  provisioning UX; third-party redirect host set; published plugin-port set per server:
  implementation/deployment choices owned by the implementing phase, with the behavior contract
  already fixed above.
- Emergency-rollback window length: resolved by OD-v8.6-8 (indefinite until explicitly unpinned).

### Resolved by owner 2026-11-11 (v8.7 — Red-Team Round 3 Remediation)

- R1 (cross-loader Health Gate): resolved by OD-v8.7-1. `^.*?\bINFO\b.*?: Done \([0-9.,]+s\)! For
  help, type ["']help["']` plus `health_gate_boot_timeout_seconds = 300` (up to 900).
- R2 (non-empty directory swap): resolved by OD-v8.7-2. `os.replace` is banned; `RENAME_EXCHANGE` or
  journaled 2-step rename with `live.prev` reconciler recovery.
- R3 (secrets in Class-B configs): resolved by OD-v8.7-3. Structured & Pattern Secret Scanner blocks
  commit/D7/push; "Extract Secret to Panel Vault" substitutes `${ONX_SECRET_<KEY_NAME>}`.
- R4 (world-subfolder denylist over-matching): resolved by OD-v8.7-4. Allow-list v2.3 adds the
  negative lookahead and the `(datapacks|global_packs|kubejs/data)/**/structures/**` `.nbt` roots.
- R5/R15 (tamperable Simple lockfile): resolved by OD-v8.7-5. Host-owned
  `<host_state_dir>/server-meta/<server_id>/onx-jars.lock.json` plus P2
  `ensure_simple_baseline_lockfile`.
- R6 (TOCTOU between `lstat` and `open`): resolved by OD-v8.7-6. `open_safe_path_fd` uses
  descriptor-relative `O_DIRECTORY|O_NOFOLLOW` hops and Windows reparse-point rejection.
- R7/R8 (shared-CAS Class C, incomplete GC roots, optional single-nonce Tier-2 crypto): resolved by
  OD-v8.7-7. Dedicated encrypted Class-C vault, complete GC root set, mandatory 64 KiB chunked AEAD.
- R9 (`save-off` freeze, stuck flag, host-wide lock): resolved by OD-v8.7-8. Two-pass delta clone,
  60 s cap, startup `save-on`, per-`st_dev` lock.
- R10 (`base_overrides` blanket promotion): resolved by OD-v8.7-9. Per-file advancement only on a
  clean merge/operator resolution.
- R11/R12 (phase dependency and move-based D7): resolved by OD-v8.7-10. Pinning/baseline in P2, Advanced
  enabled in P3, copy-first D7.
- R13 (Paper offline boot): resolved by OD-v8.7-11. Paper joins LEC as `paper/{mc}/{build}` with
  `paperclip.patchonly`.
- R14 (quarantine DoS on Save & Commit): resolved by OD-v8.7-12. Hard abort only on archive import;
  quarantine + banner on worktree scan/Save & Commit/D7.
- R16 (Class-C-free test containers): resolved by OD-v8.7-13. Ephemeral Class-C overlay and default
  whitelist enforcement.
- R17 (version-bump bypass, merge-before-backup): resolved by OD-v8.7-14. Automatic Full Upgrade
  Refresh promotion and backup-before-merge.
- R18 + minor edge cases: resolved by OD-v8.7-15. 1-16 MiB Class-B -> `A-CAS`, contiguous Java floor,
  real `SET_MERGEABLE_ARRAY_KEYS`, `--pids-limit=2048` + `/data` chown, zip-ratio exception,
  `RuntimeAdmissionScheduler` recorded as FACT.

### New unknowns (owner has not decided)

None. All architectural, security, storage, mode-conversion, and phase-policy questions for P1–P7 are
resolved as of v8.7 (including the Round 3 findings R1–R18). Only external out-of-scope systems (the
separate D11 testing-system rework and
its optional strict merge gate Unknown O) remain deferred outside this specification.

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
- `RuntimeAdmissionScheduler` citation reconciled (OD-v8.6-4, closed by OD-v8.7-15): `SPECS.md:286`
  records `RuntimeAdmissionScheduler` as the **Stage D** global admission scheduler (static + dynamic
  RAM/CPU headroom gating, FIFO run queue, concurrency caps, `server_admission_lease` serialization)
  alongside the implemented `admit()` primitive
  (`backend/app/modules/versioning/application/scheduling/admission.py:233`). It is a specified
  contract for P4, not a nonexistent name; the earlier `docs/current-state.md:13` phrasing is the
  only stale wording.
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
- No structured/AST config merge, encrypted Class-C vault, canonical-AST restart snapshot
  compare, atomic live refresh, Refresh Journal, backup-of-replaced-files, or rollback exists; the
  materialization route writes the live root.
- No `validate_canonical_relpath` Step-0 sanitizer, no casefold-collision guard, and no
  hostile-executable quarantine exists anywhere in `backend/app`; the current allow-list checks are
  regex-only.
- No `resolve_safe_disk_path`/`open_safe_path_fd` (descriptor-relative `O_DIRECTORY|O_NOFOLLOW`
  traversal, `SymlinkEscapeError`) and no `SecretFileInGitForbiddenError` guard exist anywhere in
  `backend/app` (0 matches); path handling today is realpath/string based.
- No ordered-array-vs-set-merge distinction and no `SET_MERGEABLE_ARRAY_KEYS` table exist; there is
  no structured merge engine at all yet.
- No Simple-mode **host** `<host_state_dir>/server-meta/<server_id>/onx-jars.lock.json` (only the
  in-`/data` `.onx-manager` copy exists), no `<server_root>.staging/` pipeline, and no
  crash-safe triad rollback exist; Simple has no upgrade path today.
- `docker.py` has no `--cap-drop`, `--security-opt`, or `--pids-limit` (0 matches in `backend/app`),
  and `Container uid` defaults are not centrally enforced; `--user` exists only at
  `docker.py:483` for non-itzg images.
- No per-`st_dev` storage copy lock and no hardlink guard exist; no code path distinguishes reflink
  from plain copy for CAS/LEC/Data Template materialization.
- No `modules/operations/` async worker package, no `.onx-complete.json` marker, and no lease
  heartbeat/fencing token for long storage or Git operations.
- No `base_overrides` storage and no lockfile Format 2.1 reader/writer exist.
- No Class-C snapshot table and no Live State Files route exist; the Files API has no live
  class-C path.
- No per-repo write lock or worktree lock exists for add/commit/merge/fetch/push/gc/worktree
  add-remove.
- `StorageCowUnavailableError` currently returns HTTP 412 with no fallback
  (`exceptions.py:318-333`), contradicting D-H.
- `server_branches` has no port set, runtime status, console, or activity/change-log columns
  (`models.py:27-39`).
- No GitHub repository sync, webhook, fetch/push, or per-server Git init/allow-list/CAS support was
  found.
- Versioning routes are globally reachable with no mode gate, contradicting D1 until P1 lands.
- Local providers still exist in code (P6 removes them); ADR-0015 is superseded by this
  specification (OD-v8.6-1), so the remaining work is code and migration, not governance.
- Mod loaders are PARTIALLY present, not absent (v8.3 recon): Fabric/Forge/NeoForge exist as
  `ServerType`s and are provisioned, but Quilt is missing from `ServerType`
  (`backend/app/modules/server/domain/value_objects.py:188-214`) while the plugin layer already
  accepts it (`.../plugin/infrastructure/addon_fs.py:8-16`).
- No `.mrpack`/`modrinth.index.json` reader, `InstallPlan`, `env.server` filter, override layering,
  or CurseForge adapter exists in `backend/app` (0 search matches).
- No LEC store, pre-warm builder, or offline-boot export exists; `libraries/**` and `.fabric/**` are
  produced inside the server directory today and classified class E.
- Launch depends on loader-generated shell wrappers: `run.sh`/`run.bat` are detected and persisted as
  `["bash", "run.sh", "nogui"]` (`installer_provisioner.py:154-182`), and no `unix_args.txt` exists
  anywhere in the repo (0 matches). The ND-4 argfile launch is new work.
- `user_jvm_args.txt` is written by the provisioner with `-Xms/-Xmx` only
  (`installer_provisioner.py:407-412`) and by Docker with CPU/flags added (`docker.py:1275-1308`);
  neither path generates it from panel JVM settings at export time.
- No Java-floor resolution: the Docker image is chosen from the Minecraft version alone
  (`docker.py:148-191`); `javaVersion`/`minor_version`/`min_java_version` handling is absent.
- The Modrinth client is GET-only (`modrinth.py:23`, `:89`, `:125`, `:168`, `:225`, `:291`); batch
  `POST /v2/version_files` and `POST /v2/version_files/update` do not exist (0 matches). No
  CurseForge provider is registered.
- No compatibility matrix, batch hash identification, 3-way config/script merge, `upgrade/<target>`
  branch orchestration, or upgrade wizard exists.
- No backup pin: `BackupJob` has no pin column/flag and there is no retention pruning
  (`backend/app/modules/backup/infrastructure/models.py:8-31`,
  `backend/app/modules/backup/domain/aggregate.py:161-179`). No `tier` discriminator, no 5/10/7+4
  retention counters, and no portable `.tar.zst` archive path exist, so P7 builds them.
- No `DirtyWorktreeError`/`BranchRuntimeActiveError` guards and no `OversizedGitTrackedFileError`
  1 MiB cap exist yet; merge/delete paths do not inspect worktree dirtiness or running containers.
- No credential vault wiring for GitHub exists: there is no AES-256-GCM secret store integration for
  PAT/deploy keys and no `GIT_ASKPASS`/`GIT_SSH_COMMAND` injection path.
- No D7 conversion flow exists: `servers.mode` has no conversion service, no in-place
  Simple -> Advanced migration, and no Advanced -> Simple new-server builder.
- No `level.dat` `DataVersion`/NBT reader; integrity checks existence only
  (`backend/app/modules/health/infrastructure/integrity.py:233-275`). Boot readiness is a literal
  `"Done ("` substring match (`signal_detection.py:22`), with no port-accepting or DataVersion gate.
- No OS-aware free-port allocator for an isolated port set: `/available-port` scans DB values from
  25565 (`backend/app/api/v1/routers/servers.py:71-81`).
- The P2 clean export must generate eula.txt; today it is written only at create time and in test deployments.
