# DECISION-2026-11-12-001 — P2 Planning Closure (D-1 … D-12)

**Status:** Accepted by owner — final sign-off recorded 2026-11-12; P2 programme accepted 2026-11-16 (`origin/master` `c49955a`)
**Date:** 2026-11-12 (updated 2026-11-16 for P2 acceptance and D-9 Option B deviation)
**Decision level:** D1 (phase scope and execution programme), with D2-level architecture effects for the native Git engine and host-state layout
**Spec precedence:** `docs/design/SPEC-2026-11-09-SIMPLE-ADVANCED-MODES-02.md` v8.7 is authoritative for P1–P7. This record closes the planning decisions required to start P2 implementation; it does not replace the specification.
**Repository baseline at sign-off:** `master` = `e87009b85e8973a7c8b5aeaab8966bc5a68c9d26`; `origin/master` = `27f538c4ab5685f321ed2245a38d40f4cc9ca215` (superseded at P2 close-out by `origin/master` = `c49955ab02e1c87e34ef02baaf5880602ca58a18`).

> **Execution status:** P2 (`P2-1`…`P2-6g-b`, P2a + P2b) is **COMPLETE and ACCEPTED (2026-11-16)** on `origin/master` (`c49955a`). Linux full backend suite (`4,743 passed, 7 skipped, 0 failed` at `592de67` = `cff8d9c`), `P2-6g-b` smoke (`81 passed`), frontend (`132 files / 1,214 passed` + build), 6/6 gates, and 7/7 real-run gates (including D-3 Paper `1.20.4/499` offline boot) passed. Windows CI Run ID: `UNKNOWN: not recorded` (owner-reported green on `cff8d9c`). Explicit owner deviation from D-9 recorded below (Option B: Windows Simple-only, fail-closed, `allowlist.py` frozen, no Win32 handle/reparse backend).

---

## 1. Context

The P2 planning round reconciled the normative P2 scope (`SPEC…:2160-2168`, `:2212-2306`) against the repository. The T4 card’s B1–B7 list is a substrate/recon slice, not the definition of P2 completion. The owner has now closed D-1 through D-12 and selected the first implementation target: **complete B2 Lockfile Format 2.1 + complete B3 CAS**, beginning with a fresh Recon pass.

---

## 2. Final decisions

### D-1 — Allow-list v2.3 provenance — CLOSED (reaffirmed)

Keep the existing evidence and do not reopen unless contradictory evidence appears:

- Merge commit `4bb8e3766b588ffd3d283a87c24b691e137a8c67`; parents `0fe776c08871d5905eb3d1bfd3a22b8cd421b82d` and `7c3f7a2b63488cf6bf6f8d783039a84606bf50df`.
- `backend/app/core/allowlist.py` SHA-256 **`6b0cf099c779064150f67323fe6b400cd5b3894ad29fefe7e1114136a1541e4c`** (**unchanged / frozen** through P2 close-out merge `c49955ab02e1c87e34ef02baaf5880602ca58a18`).
- `backend/tests/core/test_allowlist_v23_matrix.py` baseline SHA-256 updated per **D-P26-11** (`2026-11-15`):
  - Historical B2/B3 planning baseline (at `4bb8e376`..`f9f324fe`): `74d2046d3f8c0ce40a984fc7a9dc15b73cbde556d0b394ef65be0a9984474472`
  - `P2-6g-c2` (`7737dd6bf68d9f527cac3e43477e27799f3d34eb`): `b080d5b7259a77ab5a0ca35b64fa6a37c3ee7a9136aad313943fbba5acc74c04` (added unconditional `test_validate_canonical_relpath_rejects_trailing_dot_or_space`)
  - `P2-6g-c3` / `origin/master` (`e614305fe44b27ec0aec4726ccb367fccff88217` -> `c49955ab02e1c87e34ef02baaf5880602ca58a18`): **`529d6d8a8cc6b643d1071a4bfbac0f3bdb90881c828f31da437cd409181151dc`** (added `os.name != "posix"` skips on `test_dir_fd_*` under Option B Simple-only Windows scope + distinct parent fix on `test_dir_fd_casefold_swapped_escape`)
- All `110` TSV matrix rows (`MISMATCHES: 0`) remain intact; Linux test run verified (`4743 passed, 7 skipped, 0 failed` at `592de67`, zero skips in `test_allowlist_v23_matrix.py`).

### D-2 — Host-state contract — APPROVED

1. Canonical setting: `ONX_HOST_STATE_DIR`.
2. Resolution precedence:
   - explicit `ONX_HOST_STATE_DIR`;
   - existing configured `host_data_dir` plus `/host-state`;
   - `<data_dir>/host-state`.
   - Verified source mapping: `host_data_dir` is a `pydantic-settings` field (`backend/app/core/config.py:61`) populated through the `ONX_` / `MCS_` prefixes; the Docker provider also reads `ONX_HOST_DATA_DIR` / `MCS_HOST_DATA_DIR` directly (`docker.py:117-120`). Do not assume any other environment variable exists.
3. The resolved path must be absolute. Reject a symlinked root and any location inside `servers_data_dir` or a server root.
4. For Docker-out-of-Docker, introduce a separate host-visible path setting only when the panel path and the Docker-daemon-visible path differ. The setting name must be added deliberately and documented in the implementation batch; no such variable is assumed to exist today. Validate the mapping with a UUID marker file (`.onx-host-state-id`) written identically at both paths. Fail closed on mismatch.
5. Layout: `server-meta/`, `class-c-vault/`, `quarantine/`, `lec/`, `cas/sha256/`, `repos/`, `locks/`, `journal/`.
6. Repository storage remains outside the Minecraft server tree. Branch worktrees remain under the server’s `.onx/worktrees/<branch>` location.
7. Directories `0700`; files `0600`; ownership must match the panel process UID/GID. Never silently `chown`.
8. Tier-1 backup includes server metadata/lockfile and the Class-C vault index/blobs. CAS and LEC are caches, except for user-origin artifacts explicitly required by the normative specification.
9. Probe reflink capability on the actual source and destination directories. On failure, use the approved safe plain-copy fallback with space preflight and per-filesystem copy coordination. Hardlinks are forbidden.
10. Host-state is never mounted into a Minecraft server container. Server containers receive only their isolated `/data`.

### D-3 — Paper offline boot — CONTRACT APPROVED; EXECUTION PENDING

Pinned gate:

| Input | Value |
|---|---|
| Minecraft | `1.20.4` |
| Paper build | `499` |
| Paper jar SHA-256 | `cabed3ae77cf55deba7c7d8722bc9cfd5e991201c211665f9265616d9fe5c77b` |
| Java minimum | `17` |
| Image | `eclipse-temurin:17-jre` |
| amd64 manifest digest | `sha256:ddc89af93fb7f4a851cee6773d4597d5f95f2401d76a955d8eed4acde076548e` |

Rules:

- Disposable export copy only; never boot or mutate the canonical export directly.
- Two boots with `--network none`, interactive stdin, graceful `stop`, exit code `0`.
- Canonical export must remain byte-identical; no root-owned files; no `.git`.
- `1.20.4` is EOL/UNSUPPORTED by Fill v3. The gate demonstrates offline boot compatibility only, not vendor support.
- Do **not** claim PASS until the real gate runs and its logs/evidence are archived.

### D-4 — P2 scope and delivery programme — APPROVED

Four scope buckets:

| Bucket | Contents |
|---|---|
| **A. Core infrastructure** | Allow-list v2.3 wiring, Step-0 safe path, lockfile Format 2.1, CAS, host-state layout, Git engine, 5-step clean export, `.onx-complete.json` + journaled swap, DB migration, feature flag |
| **B. Workflow integration** | Repo init + eager `main`, branch CRUD ↔ Git, worktrees, branch-aware Files, Save & Commit, Simple Step 1 baseline lockfile, legacy read-model projection |
| **C. Security and reliability** | Secret scanner, optional vault extraction, container hardening, 1 MiB/16 MiB routing, case-collision/hostile-executable errors, repo lease/fencing, crash recovery, stale cleanup, disk-full, Windows path layer |
| **D. Acceptance** | Real Paper offline boot, Windows CI, per-directory suites, 6 gates, frontend checks, docs/state sync |

Six delivery cards:

| Card | Scope |
|---|---|
| **P2-1 Core substrate** | Allow-list wiring, safe path, lockfile, CAS, host-state, scanner core, DB migration, feature flag |
| **P2-2 Repo / branches** | Git engine, repo init, eager `main`, branch CRUD, worktree lifecycle |
| **P2-3 Clean export** | 5-step export, CAS/LEC attach, `.onx-complete.json`, journaled swap, recovery |
| **P2-4 Branch Files / Save & Commit** | Branch-aware Files API/UI, Save & Commit, normalization, Simple Step 1, legacy projection |
| **P2-5 Hardening / platform** | Vault (if approved), container flags, 1/16 MiB routing, case/hostile errors, lease/fencing, disk-full, Windows backend |
| **P2-6 Acceptance** | D-3 gate, Windows CI, suites, gates, frontend build, docs/state |

Programme split:

- **P2a:** P2-1 → P2-2 → P2-4.
- **P2b:** P2-3 → P2-5 → P2-6.
- **P2 is complete only after P2b.** P2a alone is not releasable.

**Next implementation target (owner-selected):** complete **B2 Lockfile Format 2.1** and complete **B3 CAS**, starting with a fresh Recon pass. B2 and B3 are defined by the normative spec plus the T4 card rows; the older B1–B7 list is not the definition of P2 completion. Do not expand into B4/B5/B6 unless Recon proves a dependency is unavoidable and records it explicitly.

### D-5 — LEC grammar and attach mapping — APPROVED

Grammar:

- `paper/{mc}/{build}`
- `fabric/{mc}/{loader_version}/{installer_version}`
- `quilt/{mc}/{loader_version}`
- `neoforge/{mc}/{version}`
- `forge/{mc}/{version}`

Validation:

- Validate every segment against the approved character and length constraints.
- Validate Minecraft versions separately.
- Paper build must be numeric.
- Reject traversal, absolute paths, backslashes, NUL/control characters, encoded path tricks, trailing dot/space, malformed segment counts, and unknown loader names.
- Exact key lookup only; no nearest-version fallback.
- Missing keys raise `LecKeyNotFoundError`.
- Lockfile key and completion-marker key must match the validated resolved key.

Attach map:

- Paper: `cache/`, `versions/`, `libraries/`.
- Fabric: `.fabric/server/`, with launcher jar present.
- Quilt/NeoForge/Forge: `libraries/`, with the required non-empty launcher arguments file verified against the normative specification.

Pack overrides must not overwrite protected loader-owned paths.

### D-6 — Dynamic Class-C protected-root guard — APPROVED

Protected set:

- `server.properties`
- `bukkit.yml`
- `spigot.yml`
- `commands.yml`
- `help.yml`
- `permissions.yml`
- `pufferfish.yml`
- `purpur.yml`
- `onx-jars.lock.json`
- `.gitattributes`
- `config/paper-[^/]+\.yml` (i.e. `config/paper-<name>.yml`)

Rules:

- Validate canonical relative paths before registration.
- Reject absolute paths, traversal, backslashes, NUL, and malformed paths.
- Reject registration of protected paths, including case/normalization variants.
- Never allow a dynamic entry to override a protected classification.
- Ignore and log already-stored invalid protected entries where migration compatibility requires it.
- Preserve legitimate dynamic Class-C behavior for non-protected plugin configuration paths.

This narrows the earlier report’s proposed set. Do **not** add `server-icon.png` or `modrinth.index.json` without an explicit normative specification anchor. Do not infer classifications from filenames alone. Add regression rows for case variants and traversal attempts.

### D-7 — Legacy `server_commits` projection — APPROVED

- One-way projection from Git into the legacy read model.
- Freeze direct legacy writes on the new workflow.
- Carry `git_sha` in projection rows.
- Never write backwards from the legacy projection into Git.
- Keep the projection only for compatibility until the planned P3 retirement.

### D-8 — Secret scanner and vault — APPROVED

- Implement the scanner and hard-block behavior in P2.
- Defer encrypted secret-vault extraction and its UI to P3.
- No override or bypass in the UI.
- Never echo the detected secret value in errors.
- Scan before every applicable Git write and before export.
- Cover repo initialization, Save & Commit, and every other P2 commit path.
- Future merge, conversion, and push paths must also require scanning before they become available.
- Export must fail closed on unresolved secret placeholders when no vault exists.
- Do not enable Advanced write workflows before scanner enforcement is active and tested.

### D-9 — Windows path safety — APPROVED (superseded in P2 by Owner Option B Deviation)

- Unix keeps the fd-relative safe-path backend.
- Windows gets a native handle-based/reparse-point-aware backend.
- Windows remains within its explicitly supported product surface.
- Windows CI becomes required for relevant P2 paths on push/pull request, not weekly-only.
- Do not claim Windows support or verification until the required Windows job is green.

> **Owner Decision — Explicit Deviation from D-9 (`P2-6g` Option B, accepted 2026-11-16):**
> - **Windows is Simple-only and fail-closed (`P2-6g` Option B):** Rather than implementing a native Win32 handle/reparse-point backend, production code fails closed on non-POSIX (`os.name != "posix"`) across `require_advanced_mode`, `backend/app/registration.py:325-328`, `ClassCSnapshotService`, and `LiveRefreshService`.
> - **`allowlist.py` remains frozen** at SHA-256 `6b0cf099c779064150f67323fe6b400cd5b3894ad29fefe7e1114136a1541e4c`; **no Win32 handle/reparse backend is implemented**. Any future decision to enable Advanced mode on Windows requires implementing and verifying the native Win32 backend first.
> - **Windows CI trigger (`D-P26-8` / `P2-6g-b`):** `.github/workflows/windows-ci.yml` uses `on: workflow_dispatch: {}` only (temporary single-branch push trigger removed in `43f6dcc`, merged at `c49955a`); adding a path-filtered `pull_request` trigger remains deferred. Windows CI is owner-reported green on `cff8d9c` (`Run ID: UNKNOWN: not recorded`).

### D-10 — Advanced import — APPROVED

- Block `mode=advanced` imports in P2 with HTTP 409.
- Do not create a fresh Advanced repository while silently discarding imported Git history.
- Defer Simple-to-Advanced conversion to the planned P5.5 scope.
- Do not mutate existing servers as a side effect.

### D-11 — `materialization_id` — APPROVED

- P2 uses an additive migration for `code_sha` and optional `data_template_id`.
- Keep nullable legacy `materialization_id` compatibility where required.
- Do not introduce new Advanced-path writes to the legacy field.
- Retire/drop the legacy concept in P3, after compatibility consumers are removed.

### D-12 — P2 completion definition — APPROVED

P2 is complete only when P2a and P2b are complete and all twelve acceptance conditions are evidenced:

1. Advanced create (behind flag) produces an external Git repo with eager `main` and initial commit.
2. Branch create/delete/list maps 1:1 to Git refs plus `server_branches` metadata; `main` is non-deletable.
3. Branch Files reads/writes the branch worktree; Save & Commit validates, scans, normalizes, and commits.
4. Simple server gets a host baseline lockfile via `ensure_simple_baseline_lockfile()`.
5. Clean export uses the fixed 5-step order, contains no `.git`, forbids hardlinks, and writes `.onx-complete.json`.
6. D-3 Paper 1.20.4/499 offline gate PASS with archived evidence.
7. Scanner blocks at repo init, Save & Commit, merge, D7, push, and export.
8. Container hardening flags present: non-root `--user`, `--cap-drop=ALL`, `--no-new-privileges`, `--pids-limit=2048`, only `/data`.
9. 1 MiB icon cap and 1–16 MiB Class-B → `A-CAS` routing implemented.
10. Repo lease/fencing, crash recovery, stale cleanup, and disk-full behavior tested.
11. Windows path-layer CI green for the supported Windows surface.
12. Per-directory suites, 6 gates, frontend typecheck/lint/test/build, and docs/state sync complete.

Passing B1–B7, or completing B2+B3, does **not** mean the entire P2 phase is complete. D-3 must actually pass. Windows CI must actually pass. Scanner enforcement, runtime hardening, recovery, disk-full handling, export correctness, frontend checks, and documentation/state synchronization must be evidenced.

> **P2 Acceptance Closure (2026-11-16, `origin/master` `c49955a`):** All 12 D-12 conditions are closed and P2 (`P2-1`…`P2-6g-b`) is accepted by the owner, subject to the recorded Option B deviation on Condition 11 (`Windows = Simple-only` fail-closed, `allowlist.py` frozen, no Win32 handle/reparse backend; Windows CI owner-reported green on `cff8d9c`, `Run ID: UNKNOWN: not recorded`), Condition 10 SQLite-only live-refresh scope (`D-P26-3`), and Condition 7 P2-path scope (`D-8`: merge/D7/push future). Next workstream: **P3-B3** (starting with Recon).

---

## 3. Consequences

- P2 planning is closed; P2 implementation is authorized to begin with Recon for B2+B3.
- No implementation code is changed by this decision record.
- The next session must preserve the existing Herd tabs and must begin with Recon, not Build.
- No commit, push, merge, branch deletion, worktree deletion, reset, stash, or history rewrite is authorized by this record.
- D-3 and Windows CI remain execution gates, not passed claims.
- The queue and state now point at P2 — complete B2 + B3, with a fresh Recon pass first.

---

## 4. Evidence anchors

| Subject | Anchor |
|---|---|
| P2 scope | `docs/design/SPEC-2026-11-09-SIMPLE-ADVANCED-MODES-02.md:2160-2168`, `:2212-2306` |
| Lockfile Format 2.1 schema | `SPEC…:1344-1387` |
| Host lockfile + adoption | `SPEC…:1662-1674`, `:2233-2236` |
| CAS / no-hardlink / reflink fallback | `SPEC…:919-930`, `:1341-1343`, `:1407-1410` |
| Allow-list Step 0 and regexes | `SPEC…:983-1201`, `:1203-1330` |
| LEC table and attach map | `SPEC…:1517-1570` |
| Scanner | `SPEC…:839-860`, `:2246-2265` |
| T4 card B2/B3 rows | `/home/mohamed/onx-chain/loop-night-2026-11-11/tasks/t4-p2-recon/card.md` §3.4, §5 |

---

## 5. Related artifacts

- Master prompt for the next session: `/home/mohamed/onx-chain/loop-night-2026-11-11/NEXT-SESSION-PROMPT-P2-B2-B3.md`
- Coordination queue: `/home/mohamed/onx-chain/loop-night-2026-11-11/QUEUE.md`
- Current-state snapshot: `docs/current-state.md`
