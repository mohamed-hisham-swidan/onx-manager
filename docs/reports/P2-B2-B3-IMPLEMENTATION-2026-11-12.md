# P2 B2+B3 Implementation Report — 2026-11-12

**Slice:** P2 B2 (Lockfile Format 2.1 pure domain) + B3 (SHA-256 artifact CAS).
**Phase worktree:** `/mnt/D/workspace/onx-manager-wt/p2-b2-b3`
**Branch:** `slice/p2-b2-b3`, based on `master@e87009b85e8973a7c8b5aeaab8966bc5a68c9d26`.
**Status:** IMPLEMENTED_PENDING_FIRST_CI_RUN (local verification complete; no CI run).

> **Boundary statement:** B2+B3 is a slice. P2 is not complete. D-3 and Windows CI remain
> execution-pending and are not claimed as passed.

## 1. Scope delivered

### B2 — Lockfile Format 2.1 (`backend/app/modules/versioning/domain/lockfile.py`)

- Frozen value objects: `LoaderRef`, `LecRef`, `ModpackRef`, `LockfileFile`, `LockfileV21`, with
  `EnvServer` and `Origin` string enums.
- `parse_lockfile(bytes) -> LockfileV21`: UTF-8 strict decode, exact Format `2` integer, exact key
  sets at every object level (R-04), required `base_overrides` (rejects legacy Format 1 and legacy
  Format 2 that omitted it), strict lowercase SHA lengths, `size`/`optional` exact types, enums,
  duplicate and casefold-colliding path rejection via `CaseCollisionError`, hostile path rejection
  through `validate_canonical_relpath()` plus encoded-trick rejection (R-09), LEC grammar R-05 and
  loader consistency R-07, bounded metadata strings, lone-surrogate/NUL/CR/LF rejection.
- `dump_lockfile(LockfileV21) -> bytes`: fixed key order, sorted `base_overrides`, declaration order
  for `files[]`, `indent=2`, `ensure_ascii=False`, `allow_nan=False`, single trailing newline (R-10).
  Round-trip stable.
- Pure domain: imports only stdlib plus `app.core.allowlist`, `app.core.exceptions`, and
  `app.modules.shared.value_objects`; no filesystem/config/DB/routes/network.
- `LecKeyNotFoundError` is deliberately not defined here; R-06 records the exact B4 integration
  point instead.

### B3 — SHA-256 CAS (`backend/app/modules/versioning/infrastructure/artifact_cas.py`)

- `ArtifactCas(root)` with injected absolute root, no disk I/O in `__init__` (R-11).
- Layout `sha256/<first2>/<digest>`, staging `<root>/.tmp/*.part`, dirs `0700`, staging `0600`,
  committed/quarantined blobs `0400` (R-01). No `chown`, no hardlinks, no fallback that weakens
  verification.
- `put_bytes` / `put_file`: exclusive temp creation, streaming hash, short-write loop, `fsync` file
  and containing directory, fd-relative `os.replace`, digest re-verification, dedupe of a valid
  existing blob, quarantine-and-replace for a corrupt regular blob, typed fail-closed behavior for
  symlinks, non-regular files, and containment escapes.
- `open_blob` returns a verified `BinaryIO`: opens with `O_NOFOLLOW|O_NONBLOCK`, requires a regular
  file, hashes the fd in chunks, compares, rewinds, and returns the handle (R-12/R-14). `has` is a
  cheap existence check; `blob_path` derives a path but promises no integrity.
- Canonical digest validation `^[0-9a-f]{64}$` for every public operation (R-02).
- Stale `.part` cleanup under `.tmp`; ENOSPC maps to `InsufficientStorageError` (`507`, retryable);
  POSIX-only guard raises `CasUnsupportedPlatformError` on non-POSIX (R-13).
- Error details carry field/reason/path/digest/errno only, never document bytes or metadata values
  (R-18).

### Errors (`backend/app/core/exceptions.py`)

Added exactly the R-15 set: `LockfileFormatError`, `LockfileInvalidError`, `CaseCollisionError`,
`InsufficientStorageError`, `CasError`, `CasInvalidDigestError`, `CasInvalidSourceError`,
`CasBlobNotFoundError`, `CasCorruptionError`, `CasContainmentError`, `CasWriteError`,
`CasUnsupportedPlatformError`. No changes to existing exception classes.

## 2. Changed files and final hashes

| File | Status | SHA-256 |
|---|---|---|
| `backend/app/core/exceptions.py` | modified | `08dd477aabb1ea3789eeafabedaa6bf3d2e30dd1cef5eb31135f81cbcf2eba3b` |
| `backend/app/modules/versioning/domain/lockfile.py` | new | `e0141f53e42aebe56bf0f827255ba1c17badc4e2e4cb0d7236d44129ee9275fe` |
| `backend/app/modules/versioning/infrastructure/artifact_cas.py` | new | `fa2595d44286ee221e01a66ad296d58fb1dd5333434bfe877ae4fbc34ec8bf8f` |
| `backend/tests/domain/test_lockfile_v21.py` | new | `ccf66229e4514669a28c5648f820f1b96456f4fb90f71846ebf5d74d5636e468` |
| `backend/tests/infrastructure/test_artifact_cas.py` | new | `a762772d32c6147fda023224d8bdb7a35da09143f19d6b62e827d2e4c7829306` |
| `backend/tests/integration/test_lockfile_cas_roundtrip.py` | new | `79c68e0e13fbc37eea93ba61268e1ee34b8d2d0e53c69aa52f363c77c4f816cc` |

No other files were part of the implementation. `docs/current-state.md`, this report, and
`.ai/STATE.json` are documentation/state sync only and are not part of the code Touch List.

## 3. Resolution dispositions (R-01…R-18)

| Resolution | Disposition |
|---|---|
| R-01 modes `0400/0700/0600` | Implemented; mode tests cover committed, staging, directories, quarantine. |
| R-02 canonical digest | Implemented; shared validator; uppercase/prefix/traversal rejected as `CasInvalidDigestError`. |
| R-03 lowercase lockfile SHA fields | Implemented; lowercase-only regex for sha256/sha512/sha1/index/base_overrides. |
| R-04 unknown keys rejected | Implemented at top level, loader, lec, modpack, files[]; tested. |
| R-05 LEC grammar | Implemented with exact order, five loaders, Paper build canonical, length cap. |
| R-06 `LecKeyNotFoundError` deferral | Not coded; recorded as B4 (`lockfile_service.py`) integration point. |
| R-07 loader/LEC consistency | Implemented; exact string equality per loader family; Fabric installer independent. |
| R-08 `modpack.source` open token | Implemented as safe token, no invented enum; metadata bounded. |
| R-09 encoded path tricks | Implemented for `files[].path` and `base_overrides` keys; `%2e/%2f/%5c/%00`. |
| R-10 deterministic dump | Implemented; golden minimal document + round-trip tests. |
| R-11 root lifecycle/containment | Implemented; no `__init__` I/O; fd-relative creation; missing-root behavior split. |
| R-12 corruption/quarantine | Implemented; verify-on-read; quarantine timestamp+uuid; symlink/other non-regular fail closed. |
| R-13 POSIX-only | Implemented guard; no Windows claim, no Windows CI change. |
| R-14 verified open_blob | Implemented; fd hash then rewind; caller closes. |
| R-15 exception set/codes | Implemented exactly; HTTP/codes tested. |
| R-16 no config change | Honored; no config/DI/singleton edits. |
| R-17 patch discipline | Honored; six files, targeted tests during build, final verification once. |
| R-18 error secrecy | Implemented; sentinel tests for metadata and error details. |

## 4. Verification

### 4.1 During build (phase backend)

```
pytest tests/domain/test_lockfile_v21.py \
       tests/infrastructure/test_artifact_cas.py \
       tests/integration/test_lockfile_cas_roundtrip.py -q
=> 189 passed (145 domain + 43 infrastructure + 1 integration)
git diff --check => clean
```

Interpreter: `/mnt/D/workspace/onx-manager/backend/.venv/bin/python` (Python 3.12.14). The count rose
from 167 to 189 after the review-correction rows were added.

Build's agent exhausted credits after the final test run and before writing `post.txt`; the
coordinator independently recomputed all six hashes and refreshed `/tmp/p2-b2-b3/post.txt` from the
unchanged tree. Final verification writes its own `post-local.txt` and compares the two.

### 4.2 Final verification (coordinator, once, after Review)

Executed via `/tmp/opencode/p2-b2-b3/verify.sh` on the final tree:

| Check | Result |
|---|---|
| Exact Touch List | **OK** — six files only (the harness's first pass had a cosmetic `M` vs ` M` expected-string bug; corrected check returns `TOUCH_LIST_OK`) |
| HEAD / diff check | `e87009b85e8973a7c8b5aeaab8966bc5a68c9d26`; `git diff --check` clean |
| Post-edit hashes | all six match `/tmp/p2-b2-b3/post.txt` (coordinator-refreshed; see note below) |
| Import purity | `IMPORT_OK` |
| Targeted tests | **189 passed** — 145 domain + 43 infrastructure + 1 integration |
| `tests/domain` | **465 passed** (baseline 320; +145 new) |
| `tests/infrastructure` | **928 passed, 1 skipped** (baseline 885/1; +43 new) |
| `tests/integration` | **44 passed** (baseline 43; +1 new) |
| `tests/core` with metadata shim | **595 passed, 2 skipped, 0 failed**; the two extra collected params are the new production files scanned by `test_no_hardcoded_version_literal_outside_allowed_files` |
| `tests/core` bare | **593 passed, 2 failed, 2 skipped**; both failures are the known `PackageNotFoundError: onx-manager` metadata artifact in `test_version.py`, identical to baseline |
| D-1 matrix | **42 passed**, `MATRIX ROWS: 110`, `MISMATCHES: 0` |
| Six `check-*` gates | **6/6 exit 0** |
| Targeted Ruff | 3 findings, all pre-existing `exceptions.py` baseline debt (N818 ×2, E501) tracked in `ruff-baseline.json`; new B2/B3 code adds zero violations; `check-ruff-baseline` exit 0 |
| Hardlink / forbidden-import scans | no `os.link`, no `chown`, no subprocess/socket/requests/SQLAlchemy/FastAPI/config imports in B2/B3 |

Note: Build's agent exhausted credits after its final test run and before writing `post.txt`. The
coordinator recomputed all six hashes from the unchanged tree and refreshed
`/tmp/p2-b2-b3/post.txt`; the final harness independently recomputed them again and matched.

Baseline to compare against (clean phase worktree):

| Suite | Baseline |
|---|---|
| `tests/domain` | 320 passed |
| `tests/infrastructure` | 885 passed, 1 skipped |
| `tests/integration` | 43 passed |
| `tests/core` (bare) | 591 passed, 2 failed, 2 skipped — both failures are the known `onx-manager` metadata artifact |
| `tests/core` (metadata shim) | 594 passed, 2 skipped; 110 matrix rows; 0 mismatches |
| D-1 allowlist / matrix hashes | `6b0cf099…` / `74d2046d…` |

## 5. Independent review

Reviewer: GLM-5.3-Flash, pane `w1:p7`, read-only. Verdict: **PASS — no BLOCKER, no HIGH**, one
MEDIUM and six LOW findings.

| Finding | Severity | Disposition |
|---|---|---|
| M-1 B2 errors echo unbounded attacker-controlled paths/keys (R-15 truncation) | MEDIUM | **Fixed in-slice** (coordinator reproduced a 200,040-char `CaseCollisionError`): bounded repr/field helper, no chained full-path text, `CaseCollisionError` defensively bounded, regression rows. |
| L-1 `mc="1.20.4\n"` accepted via shared `$` regex | LOW | **Fixed in-slice** inside `lockfile.py` (control-char/lone-surrogate rejection); shared module untouched. |
| L-2 test gaps (base_overrides casefold, SHA bad-format rows, umask-077, golden bytes; Kelvin row mis-specified) | LOW | **Fixed in-slice**: rows added and Kelvin replaced by the NFC-stable U+FB01 ligature pair. |
| L-3 present-but-wrong-type `base_overrides` raises two classes by entry path | LOW | **Fixed in-slice**: both paths raise `LockfileInvalidError`; `LockfileFormatError` remains the missing-key legacy discriminator. |
| L-4 "Ruff clean on touched files" unattainable due to grandfathered N818/E501 in `exceptions.py` | LOW | **Accepted**: `check-ruff-baseline` is the operative gate and passes; no new violations; no code change. |
| L-5 directory-fsync failure after successful `os.replace` reports "Failed committing" | LOW | **Accepted residual**: data integrity is safe and retry dedupes; commit semantics deliberately unchanged. Message accuracy to be improved in a later hardening slice. |
| L-6 `put_file` follows intermediate source symlinks | LOW | **Documented** in `put_file` docstring: final component is no-follow; the caller-supplied source is validated by double hashing. |

Review independently reproduced at the reviewed revision: exact Touch List and six hashes, 167
targeted tests, D-1 matrix (42 passed, 0 mismatches), `check-ruff-baseline` (exit 0),
`git diff --check`, purity/deferral greps, and 26 adversarial probes. Unverified by Review (reserved
for coordinator final verification): full per-directory suites, the remaining five gates,
multi-process concurrency, Windows/non-POSIX runtime, and live remote-FS source mutation.

The M-1/L-1/L-2/L-3 corrections were verified by the coordinator (bounded-error probes, `mc`/error-
class probes, 189 targeted tests, and final verification). An independent Review re-check of the
correction round was not performed; the Review verdict above applies to the pre-correction revision,
and the corrections are narrow and fully covered by the added regression tests.

## 6. Risks and out-of-scope

- B3 is POSIX-only; Windows native support remains P2-5/D-9. No Windows CI run exists.
- Quarantine retention/GC, host-state resolution, LEC lookup, lockfile disk I/O, Git/export wiring,
  and route/DI/config integration belong to B4/B5/B6 and were not implemented.
- `has` is an existence check and does not verify content; integrity consumers must use `open_blob`.
- No `hypothesis` or other dependency was added; property-style coverage uses parametrized tables.
- No commit, push, merge, reset, stash, branch deletion, or worktree deletion was performed.

## 7. Repository state and documentation sync

- Branch `slice/p2-b2-b3` at base `e87009b8…` plus the uncommitted six-file implementation.
- Docs/state sync in the phase worktree: `docs/current-state.md` updated and this report added under
  `docs/reports/`. `.ai/STATE.json` (git-excluded) is updated in the main worktree, where the only
  copy lives; no tracked owner docs in the main worktree were touched.
- The owner's uncommitted main-worktree changes (`docs/current-state.md`,
  `docs/decisions/README.md`, `docs/roadmap/ROADMAP_v1.1.md`, and the untracked decision record)
  remain untouched.
- No commit, push, merge, reset, stash, branch deletion, or worktree deletion was performed.
