# P2-3 Clean Export + Journaled Directory Swap — Implementation Report — 2026-11-13

**Slice:** P2-3 (P2b start) — clean export of a pinned Git commit; journaled directory swap utilities.
**Worktree:** `/mnt/D/workspace/onx-manager-wt/p2-b4-core-substrate`
**Branch:** `slice/p2-b4-core-substrate`
**Base:** `4d25a9f15a9359c7144906bc3b7fb49246e1b089`
**Status:** IMPLEMENTED_AND_VERIFIED — service and utilities implemented and tested.

> **Boundary statement:** P2-3 delivers the clean-export service and the crash-safe journaled
> directory swap utilities only. No route was added (route count stays 156); no consumer calls the
> service yet — branch/test runtime wiring is P4 (per spec "This service is built in P2; branch/test
> runs consume it in P4"). Refresh/rollback orchestration, lease/fencing, disk-full policy, and the
> unified Refresh Journal DB row remain P2-5/P2-6/P3. Windows remains Simple-only; the service fails
> closed on non-POSIX hosts. Nothing was pushed or merged.

## 1. Scope delivered

### 1.1 `backend/app/modules/versioning/infrastructure/clean_export.py`

`CleanExportService.export()` builds the only container root from a pinned commit in the normative
fixed 5-step order (ND-3, OD-v8.4-2, OD-v8.7-3/13):

1. **Hardened `git archive` extraction.** `git archive --format=tar --no-worktree-attributes <sha>`
   into a sibling staging temp dir; extracted member-by-member with:
   - `validate_canonical_relpath()` on every member name; non-regular members (symlink/hardlink/
     fifo/device) rejected; duplicate paths rejected; per-member 16 MiB cap;
   - reserved paths rejected: `.git`, `libraries/**`, `.fabric/**`, `run.sh`, `run.bat`,
     `user_jvm_args.txt`, and the completion marker itself — the archive can never smuggle loader
     jars or startup scripts into the export;
   - every write target opened through `open_safe_path_fd()` (descriptor-relative
     `O_DIRECTORY|O_NOFOLLOW` containment, no realpath-only checks).
2. **Class-A materialization from the host CAS.** Every `files[].path` and every `base_overrides`
   path is validated; each blob is opened through `ArtifactCas.open_blob()` (integrity-verified),
   size-checked against the lockfile, and written via `open_safe_path_fd()`. A path collision with
   already-extracted content fails closed; a missing mandatory blob aborts the export; a missing
   optional blob is skipped.
3. **LEC attach.** `lockfile.lec.key` is parsed (`parse_lec_key`) and the loader subtree is copied
   with the tree prefix preserved (`libraries/**`, `.fabric/server/**` for Fabric; `cache/**` +
   `versions/**` for Paper/Purpur; `libraries/**` for Forge/NeoForge/Quilt) so the trusted host LEC
   is the authoritative writer of the loader classpath. Forge/NeoForge/Quilt exports assert a
   non-empty `unix_args.txt` at the spec's canonical path.
4. **Optional overlays.** The Class-E Data Template overlay and the Class-C snapshot overlay are
   copied only when the source carries a `.onx-complete.json` marker; every copied path must
   classify as Class E (Data Template) or Class C (snapshot) per the Allow-list v2.3 evaluator;
   symlinks and non-regular files are rejected and the marker itself is never copied.
5. **Class-D injection LAST.** `server.properties` is rewritten from the archived copy with
   Class-D panel keys (`CLASS_D_PANEL_KEYS` + `management-server-*`) stripped, panel keys injected,
   and `white-list=true` + `enforce-whitelist=true` added for joinable test containers; `eula.txt`
   and `user_jvm_args.txt` are written from panel state only; `${ONX_SECRET_*}` placeholders are
   substituted across properties, JVM args, and text-suffixed files, and an unresolved placeholder
   fails the export. `run.sh`/`run.bat` must not exist in the export root.

Copy primitives (steps 1–4 sources): probe-verified reflink on the **exact file descriptors**
(`ioctl(fd, FICLONE, src_fd)` with a size verification and truncation fallback), else a plain
chunked copy under the per-`st_dev` `flock` copy lock after a `required_bytes * 1.10` free-space
reservation (`InsufficientStorageError` on shortfall). Hard links are never created; the final
invariant walk rejects `st_nlink != 1`, symlinks, non-regular files, `.git`, and
`run.sh`/`run.bat`/`ServerStarterJar` names. The export is finalized with a fsynced
`.onx-complete.json` marker (file + parent directory) recording `completed_at`, `file_count`, and
`total_bytes`; any failure removes the partial export tree.

### 1.2 `backend/app/modules/versioning/infrastructure/directory_swap.py`

Crash-safe Journaled Directory Swap utilities (OD-v8.7-2):

- `rename_exchange()`: `renameat2(..., RENAME_EXCHANGE)` via the glibc symbol when present, else the
  `SYS_renameat2` fallback table; unsupported kernels/filesystems return `False` so the caller uses
  the fallback; unexpected errors are raised.
- `swap_directories()`: validates both trees (absolute, symlink-free, same `st_dev`, no
  nesting, `live.prev` free), writes the journaled phases `PREPARED` →
  `SWAPPING_OUT_LIVE` (`live` → `live.prev`) → `SWAPPING_IN_STAGING` (`staging` → `live`) →
  `SWAP_COMPLETED`, each fsynced before the rename it guards; a failed swap-in restores `live.prev`
  and marks `SWAP_ROLLED_BACK`. `RENAME_EXCHANGE` is preferred when supported (single atomic
  syscall); `os.replace` on a non-empty directory is never used. The old tree is left at `staging`
  (exchange) or `live.prev` (fallback) for the caller to verify and remove.
- `DirectorySwapJournal`: fsynced atomic JSON journal (`journal_id, server_id, phase, live_path,
  staging_path, previous_path, previous_main_sha, target_main_sha, pre_upgrade_backup_id,
  class_c_snapshot_id, used_exchange, error, updated_at`).
- `recover_interrupted_swap()`: the OD-v8.7-2 boot-reconciler contract — a crash during
  `SWAPPING_OUT_LIVE`/`SWAPPING_IN_STAGING` with a missing `live` and an existing `live.prev`
  restores the pre-swap tree and marks `SWAP_ROLLED_BACK`; a crash after the staging rename is
  marked `SWAP_COMPLETED`; inconsistent states (both trees present/absent) fail closed.

## 2. Changed files and hashes

Post-edit hashes (`/tmp/p2-3/post.txt`):

| File | Status | SHA-256 |
|---|---|---|
| `backend/app/modules/versioning/infrastructure/clean_export.py` | new | `02a7228d334006ff1cfc176f5381d9c44a63db61ef8e5841427273813a639b99` |
| `backend/app/modules/versioning/infrastructure/directory_swap.py` | new | `b22dd438eebe5cfe1ce28656f5fde7c07f4b0b2e573dd8778b2c5c98c5299322` |
| `backend/tests/infrastructure/test_clean_export.py` | new | `1abfe8ca97e3af230e71f398b472ee740e83a023fa78d0cc78aa0faa6626b861` |
| `backend/tests/infrastructure/test_directory_swap.py` | new | `7e2e2fb24a02bf03e0972d3523d1969199227fa27caab56ea8b6c27fae07141a` |

## 3. Verification

- Targeted P2-3 tests: **33 passed** —
  `tests/infrastructure/test_clean_export.py` (18) and
  `tests/infrastructure/test_directory_swap.py` (15). Coverage includes the full five-step
  composition (archive content, CAS materialization, LEC `cache/versions` and Forge
  `unix_args.txt`, Class-E/Class-C overlays, Class-D injection + secret substitution, marker
  accounting, no `.git`/`run.sh`, no hard links), optional-vs-mandatory CAS entries, invalid
  commit, existing destination, unresolved secrets, overlay marker/classification policy,
  symlink rejection, plain-copy fallback, archive symlink/traversal/reserved-path rejection,
  fallback + exchange swaps, journal phase order, injected rename failure rollback, all recovery
  branches, and journal validation.
- Pyright on the four new files: **0 errors, 0 warnings**.
- Ruff (`ruff check` + `ruff format --check`) on the four new files: clean.
- Gates: `check-db-revision` PASS, `check-version-propagation` PASS, `check-route-contract`
  **156 live routes vs 156 contract entries** PASS, `check-ruff-baseline` PASS (486 violations,
  all at/below baseline), `check-ps1-bom` PASS, `check-stray-db` PASS, `git diff --check` clean.
- Full backend suite (includes the P2-3 tests): **4,414 passed, 6 skipped** (exit 0), run once
  after the last code edit with no concurrent pytest. Evidence: `/tmp/p2-final-verify/pytest.log`.

## 4. Known limits / pending

- No consumer wiring yet: branch/test runtime exports (P4) and refresh flows (P2-5/P3) call this
  service; the destination contract (sibling staging + `swap_directories`) is theirs to drive.
- The export consumes already-scanned Git content and fails closed on unresolved
  `${ONX_SECRET_*}` placeholders; a dedicated scanner pass over overlay inputs is deferred to the
  P2b/P2-6 hardening pass.
- The unified Refresh Journal DB row, lease/fencing heartbeat, and disk-full retry policy are
  P2-5/P2-6 scope; `directory_swap.py` provides only the on-disk journal and swap/recovery.
- Class-C snapshot overlay is disposable by construction (copy-in only, never written back);
  write-back prevention is enforced by the runtime (P4), not by this service.
- Windows is Simple-only; `CleanExportService.export()` raises `StorageCowUnavailableError` on
  non-POSIX hosts and the tests skip there.
