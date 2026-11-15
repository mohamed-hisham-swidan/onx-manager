# P2-6 Real-Run In-Phase Gates — Evidence Report — 2026-11-14

## P2-6e follow-up — 2026-11-15

**Slice:** P2-6d — Real-Run In-Phase Gates & Evidence; P2-6e — Secret-scanner fix & Gate 6 closure
**Worktree:** `/mnt/D/workspace/onx-manager-wt/p2-5-refresh-rollback`
**Branch:** `slice/p2-6e-scanner-sensitive-keys` (P2-6d gates originally on `slice/p2-6d-real-run-gates`)
**Base:** `90b54105c52ffabe0d7ec26e753d39f4e6830e79` (P2-6e); P2-6d base `c3a73bf0984f44693c3656ac031c633276f82486`
**Master gate:** `/mnt/D/workspace/onx-manager` @ `e87009b85e8973a7c8b5aeaab8966bc5a68c9d26` (untouched)
**Status:** **Gate 6 FIXED and re-run PASS (P2-6e, OD-v8.7-16). P2 NOT YET ACCEPTED** — acceptance conditions 11 (Windows CI) and 12 (full suites/docs-state sync) remain open.

> **Boundary statement:** P2-6d executed the real-run gates without production edits. P2-6e applied the owner-approved OD-v8.7-16 spec amendment plus the scanner/test fix; **no commit, push, merge, reset, or amend was performed**. `.ai/STATE.json` and `DECISION-2026-11-12-001-p2-planning.md` were not modified. Raw evidence and the three proposals live in the untracked `.ai/orchestration/artifacts/` tree and were never staged. The master worktree was not touched.

---

## 1. Verdict Summary

| # | Gate | Result | Evidence |
|:-:|:-----|:------:|:---------|
| 1 | D-3 Paper 1.20.4/499 offline boot ×2 with panel hardening | **PASS** | `gate1-offline-boot-1.log`, `gate1-offline-boot-2.log`, `gate1-boot1-exit.txt` (+ supplementary `gate1-offline-boot-1-sigterm-143.log`) |
| 2 | `docker inspect` hardening verification | **PASS** | `gate2-docker-inspect.json`, `gate2-inspect-summary.txt`, `gate2-hardening-check.log` |
| 3 | `kill -9` crash injection + startup recovery + rollback | **PASS** | `gate3-crash-recovery.log`, `gate3-child-refresh.log`, `gate3-recover.log`, `gate3-journal-at-kill.json`, `gate3-summary.json` |
| 4 | Small-FS disk-full run (unprivileged tmpfs) | **PASS** | `gate4-disk-full.log` |
| 5 | Real health gate failure + automatic triad rollback | **PASS** | `gate5-health-rollback.log`, `gate5-summary.json` |
| 6 | DiscordSRV / LuckPerms secret scanner | **PASS (re-run, P2-6e)** | `gate6-rerun-secret-scanner.log`; P2-6d FAIL retained in `gate6-secret-scanner.log` |
| 7 | Allow-list v2.3 live-tree clean export | **PASS** | `gate7-clean-export.log` |

**Overall:** all seven gates now **PASS** after the P2-6e Gate 6 re-run. P2 is still **not accepted**: conditions 11 (Windows CI) and 12 (full suites/docs-state sync) remain open. The original P2-6d result was 6 PASS / 1 FAIL; that FAIL is fixed and re-verified, not erased.

---

## 2. Environment

| Item | Value |
|:-----|:------|
| Date | 2026-11-14 (P2-6d gates); 2026-11-15 (P2-6e Gate 6 re-run) |
| Host | Linux, Docker `29.9.2`, unprivileged user `1000` |
| Docker image | `eclipse-temurin:17-jre` (`sha256:0b6521287f850ec1c4b31c9074c5a1ae1d67c5922c3fefd21065c7c32e244d4a`) |
| Paper jar | `/tmp/onx-d3/paper-1.20.4-499.jar` |
| Paper SHA-256 (measured) | `cabed3ae77cf55deba7c7d8722bc9cfd5e991201c211665f9265616d9fe5c77b` |
| Vanilla cache seed | `cache/mojang_1.20.4.jar`, SHA-1 `8dd1a28015f51b1803213892b50b7b4fc76e594d` |
| Unprivileged mount | `unshare -U -r -m` + `mount -t tmpfs -o size=10m` verified working (no `sudo`) |

**Hash verification:** `scripts/gate1_sha256_verify.py` reads the 64-character SHA-256 pinned in `docs/decisions/DECISION-2026-11-12-001-p2-planning.md`, hashes `/tmp/onx-d3/paper-1.20.4-499.jar`, and prints `MATCH` (64/64 hex characters). Evidence: `.ai/orchestration/artifacts/p2-6e-evidence/gate1-sha256-verify.log`. No truncated hash literal is recorded in this report.

Paperclip needs to download the vanilla Mojang server jar unless it is pre-seeded. Both boots were run with `--network none`, so `cache/mojang_1.20.4.jar` was placed in the data directory before boot. This is the offline D-3 condition and is recorded in the boot logs (`Starting org.bukkit.craftbukkit.Main` / `Done (...)`).

---

## 3. Gate Details

### Gate 1 — D-3 Offline Boot ×2 (PASS)

**Command (representative; Boot 2):**

```bash
docker run -d -i --name p26d-gate1-boot2 \
  --user 1000:1000 --cap-drop=ALL --security-opt=no-new-privileges:true \
  --pids-limit=2048 -m 1024m --cpus 2 --network none \
  -v /tmp/p26d-runs/gate1/data:/data -w /data \
  eclipse-temurin:17-jre \
  java -Xms256M -Xmx768M -jar server.jar nogui
```

Setup before boot: real Paper jar copied to `/data/server.jar`, vanilla cache pre-seeded, `eula=true`, flat world, `online-mode=false`, no RCON/query.

**Observed:**

| Boot | `Done (...)` | Shutdown | Exit |
|:-----|:-------------|:---------|:----:|
| Boot 1 (rerun with stdin `stop`) | `Done (10.474s)! For help, type "help"` | `Stopping the server` → all dimensions saved → `Closing Server` | `0` (`oom=false`) |
| Boot 2 | `Done (9.982s)! For help, type "help"` | all dimensions saved → `Closing Thread Pool` | `0` (`oom=false`) |

Container start → `Done` took ~18–19 s per boot including JVM/Paperclip startup. `docker stop --time 60` on the first attempt produced a clean save but exit code `143` (SIGTERM semantics); that run is retained as supplementary evidence. Both acceptance runs used stdin `stop` and exited `0`.

**SHA-256 verification (P2-6e):** the jar hash matches the 64-character value pinned in the P2 decision record; the automated comparison printed `MATCH` (see `gate1-sha256-verify.log`).

**Evidence:** `gate1-offline-boot-1.log`, `gate1-offline-boot-2.log`, `gate1-boot1-exit.txt`, `gate1-offline-boot-1-sigterm-143.log`, `gate1-sha256-verify.log`.

---

### Gate 2 — `docker inspect` Hardening Verification (PASS)

**Commands:**

```bash
docker inspect p26d-gate1-boot1 > gate2-docker-inspect.json
docker inspect p26d-gate1-boot1 --format \
  '{{json .Config.User}} {{json .HostConfig.CapDrop}} {{json .HostConfig.SecurityOpt}} \
   {{json .HostConfig.PidsLimit}} {{.HostConfig.Memory}} {{.HostConfig.NanoCpus}} \
   {{json .HostConfig.NetworkMode}}'
```

**Observed assertions (`gate2-hardening-check.log`):**

| Check | Observed | Result |
|:------|:---------|:------:|
| `Config.User` non-root | `1000:1000` | PASS |
| `HostConfig.CapDrop` | `["ALL"]` | PASS |
| `HostConfig.SecurityOpt` contains `no-new-privileges:true` | `["no-new-privileges:true"]` | PASS |
| `HostConfig.PidsLimit` | `2048` | PASS |
| `HostConfig.Memory` | `1073741824` (1 GiB) | PASS |
| `HostConfig.NanoCpus` | `2000000000` (2 CPUs) | PASS |
| `HostConfig.NetworkMode` | `none` | PASS |
| Mounts | only `/data` (`/tmp/p26d-runs/gate1/data`) | PASS |
| `docker.sock` mount | none | PASS |

**Evidence:** `gate2-docker-inspect.json`, `gate2-inspect-summary.txt`, `gate2-hardening-check.log`.

---

### Gate 3 — `kill -9` Crash Injection & Recovery (PASS)

**Harness:** real SQLite DB (`DatabaseReconciler` → `refresh.db`), real `RefreshJournalRepository` (DB + fsynced `refresh.json` mirror), real `RepoLeaseManager` (DB token + heartbeat + `flock`), real Git repository (`GitRepositoryService.initialize`), real directory exchange (`swap_directories`), real Class-C snapshot, real full-tree backup/restore, and a real OS subprocess runtime. The refresh itself ran in a child process; the startup reconciler and rollback ran in a second process after `SIGKILL`.

**Command:**

```bash
python /tmp/p26d-runs/gate3_crash_recovery.py
```

**Observed timeline:**

1. Child refresh created the journal and advanced `QUIESCED → BACKED_UP → STAGING → CARRYING → CARRIED → STARTING → VERIFYING_HEALTH`. At the kill point the journal mirror recorded `phase=VERIFYING_HEALTH`, `fencing_token=1`, `used_exchange=true`, `retention_policy=until_health_gate`, retained previous tree, and a pinned backup + Class-C snapshot.
2. Parent sent `SIGKILL`; child return code `-9`. The runtime child process survived as an orphan (verified alive), matching a real crashed worker.
3. Recovery process ran `RefreshStartupReconciler.reconcile_sync()`; the journal moved to `ROLLBACK_REQUIRED` with error `startup recovery found phase VERIFYING_HEALTH; roll back or confirm before starting the server`. The start guard then failed closed with `RefreshRecoveryRequiredError`.
4. `RollbackRefreshCommandHandler` → `LiveRefreshService.rollback` → `TriadRollbackService` restored the retained previous tree, Class-C snapshot, and pinned backup, stopped the orphan runtime, and recorded `ROLLED_BACK`.

**Key checks (all PASS):**

- Reconciler transition: `VERIFYING_HEALTH → ROLLBACK_REQUIRED`.
- Start guard blocks before rollback (`RefreshRecoveryRequiredError`).
- Rollback: `phase=ROLLED_BACK`, `terminal=true`, `used_previous_tree=true`, `restored_class_c=true`, `restored_backup=true`.
- **B-A1 fencing path:** journal row token stayed `1` while the newly acquired repo lease token was `2`; all journal CAS transitions used the journal token, and the new lease token fenced the writer.
- Restored tree: old `server.properties`, old `world/level.dat`, old Class-C `ops.json`; failed-tree complement carried back; no `.staging` / `.prev` / `.rollback*` leftovers; `previous_tree_retained=false`.

**Timing:** refresh start → `VERIFYING_HEALTH` ≈ 3.2 s; kill → `ROLLBACK_REQUIRED` ≈ 2.7 s; rollback → `ROLLED_BACK` ≈ 2.4 s.

**Evidence:** `gate3-crash-recovery.log`, `gate3-child-refresh.log`, `gate3-recover.log`, `gate3-journal-at-kill.json`, `gate3-summary.json`.

> Scope note: the gate target is the journal/lease/reconciler/rollback chain, and those are the production implementations. The runtime and stage-export ports were real OS/filesystem implementations injected at the boundary; the Docker runtime adapter is exercised separately by Gate 1/2.

---

### Gate 4 — Small-FS Disk-Full Run (PASS)

**Command (no `sudo`):**

```bash
unshare -U -r -m bash -c \
  'mount -t tmpfs -o size=10m tmpfs /tmp/p26d-runs/gate4/mnt && \
   cd backend && python /tmp/p26d-runs/gate4_disk_full.py'
```

**Setup:** real `CleanExportService.export` targeting a 10 MiB tmpfs mount (`total_bytes=10485760`). A 12 MiB Class-D panel property forces a write that bypasses the per-file free-space preflight and hits the filesystem limit.

**Observed:**

```
raised InsufficientStorageError: Insufficient storage space
cause=OSError errno=28 strerror=No space left on device
destination_exists=False tmpfs_leftovers=[]
PASS typed InsufficientStorageError
PASS cause errno == ENOSPC
PASS export destination removed
PASS live tree unchanged
PASS no partial export leftovers
RESULT: PASS
```

One harness iteration corrected the `live_before` snapshot to be taken after `GitRepositoryService.initialize` (repo init legitimately creates `.onx/worktrees/main`); no production change was involved.

**Evidence:** `gate4-disk-full.log`.

---

### Gate 5 — Real Health Gate + Triad Rollback (PASS)

**Command:**

```bash
python /tmp/p26d-runs/gate5_health_rollback.py
```

**Setup:** real `LiveRefreshService.refresh` against the real SQLite DB, real Git repo, real directory exchange, real Class-C snapshot, real full-tree backup, and the production `HealthGateEvaluator`. A real OS subprocess was started as the runtime and emitted a fatal crash signature in its boot log (`Encountered an unexpected exception`). The gate therefore fails at the production boot-log step, exercising the same failure path as a real crashed Paper boot.

**Observed:**

```
health passed=False failed_step=boot_log
reason="boot log contains fatal pattern 'encountered an unexpected exception'"
journal phase=ROLLED_BACK terminal=true rolled_back=True token=1
backup=bk-1794688033107 class_c_snapshot=f2d603b1c75e49b293e2355ac88e9a4c
RESULT: PASS
```

All checks passed: health failure at `boot_log`; automatic `rolled_back=true`; journal `ROLLED_BACK`/terminal; previous tree released; Class-C snapshot and pinned backup created and retained; old `server.properties`, `world/level.dat`, and Class-C `ops.json` restored; failed-tree complement carried back; runtime stopped by rollback; no `.staging` / `.prev` / `.rollback*` leftovers; exactly one DB journal row in `ROLLED_BACK`.

**Evidence:** `gate5-health-rollback.log`, `gate5-summary.json`.

---

### Gate 6 — DiscordSRV / LuckPerms Secret Scanner (P2-6d **FAIL** → P2-6e **PASS**)

**Command:**

```bash
cd backend && python /tmp/p26d-runs/gate6_secret_scanner.py
```

**Observed:**

| Case | Findings |
|:-----|:---------|
| DiscordSRV raw | `discord-bot-token`, `discord-webhook`, `sensitive-key:BotToken`, `sensitive-key:WebhookUrl` |
| DiscordSRV `${ONX_SECRET_*}` placeholders | none |
| **LuckPerms raw (`data.password`)** | **none** |
| LuckPerms `${ONX_SECRET_*}` placeholders | none |

`assert_no_secrets` raised `SECRET_FILE_IN_GIT_FORBIDDEN` for DiscordSRV and **did not raise** for the real LuckPerms config. Redaction was verified: no detected secret value appeared in the error message or details. Placeholder substitution produced zero findings for both samples.

**Isolation probes:**

- `mysql.password: probe-secret` → detected as `sensitive-key:mysql.password`.
- `data.mysql-password: probe-secret` → detected as `sensitive-key:data.mysql-password`.
- Real LuckPerms shape `data.password` → **not detected**.

**Root cause:** `_SENSITIVE_KEY_RE` (`backend/app/modules/versioning/infrastructure/secret_scanner.py:49-56`) matches prefixed database keys such as `mysql.password` / `data.mysql-password`, but not a bare `password` leaf nested under LuckPerms' `data` block. The implementation faithfully mirrors the normative OD-v8.7-3 regex (`docs/design/SPEC-2026-11-09-SIMPLE-ADVANCED-MODES-02.md:846-850`), which also omits the `data`/`storage` prefixes; the gap is therefore both a spec-coverage gap and an implementation gap, not an implementation-only divergence. `data.password` passes the scanner and would be committed by Save & Commit / export paths that rely on it.

**Impact:** P2 acceptance condition 7 ("Scanner blocks at repo init, Save & Commit, merge, D7, push, and export") is **not satisfied** for a realistic LuckPerms config. This is a production defect, not a harness issue. Per the batch constraints, no production code was edited; the fix requires Hydrogen approval and a regression test.

**Evidence:** `gate6-secret-scanner.log`.

#### Gate 6 re-run — P2-6e (PASS)

**Fix applied:** owner-approved **OD-v8.7-16** (2026-11-15) amends OD-v8.7-3 item (iii). With `leaf` = final dotted-key segment and `parent` = the segment immediately before it, comparing case-insensitively with `-`/`_` interchangeable, a key is sensitive when (a) `leaf` matches the token/secret regex, (b) `leaf` is exactly `password`/`passwd`/`pwd` at any nesting depth, or (c) `leaf` or `parent`+`leaf` matches the prefixed database regex. `_flatten` now walks mappings and lists/tuples; `.properties` keys/values wrapped in matching quotes are unquoted before analysis; booleans, empty/whitespace-only values, `none`, `changeme`, `password`, `null`, `~`, and `${ONX_SECRET_*}` (case-insensitive) are ignored.

**Changed files:** `docs/design/SPEC-2026-11-09-SIMPLE-ADVANCED-MODES-02.md` (S1–S4), `backend/app/modules/versioning/infrastructure/secret_scanner.py`, `backend/tests/infrastructure/test_secret_scanner.py`.

**Re-run result: PASS** (`gate6-rerun-secret-scanner.log`):

- Real DiscordSRV `config.yml`: `discord-bot-token`, `discord-webhook`, `sensitive-key:BotToken`, `sensitive-key:WebhookUrl`; placeholders clean; redaction clean.
- Real LuckPerms `config.yml`: `sensitive-key:data.password`; `assert_no_secrets` raises; placeholder version clean; error details contain only `kind`/`key`, never the literal value.
- Nested vectors: `data.mongo.password`, `settings.database.password`, `rabbitmq.password`, `nats.password`, YAML list-of-mappings (`accounts[0].password`), `rcon: [{pass: ...}]` (`rcon[0].pass`), `.properties` `db.password`/`storage.password`.
- Bypass probes: key case variants, quoted YAML/TOML/`.properties` keys, space-separated `.properties` keys, YAML anchors/aliases and merge keys, JSON top-level/nested arrays, TOML tables/arrays of tables, whitespace around values — all detected.
- Negative vectors: `password-required: true`, `password-policy: "min length 8"`, `password: ""`, `password: false/true`, `password: changeme`, whitespace-only, quoted `none`/`null`/`~`, `${ONX_SECRET_*}` — no findings.
- Existing prefixed probes `mysql.password` and `data.mysql-password` still detect (no regression).
- Regression suite: `tests/infrastructure/test_secret_scanner.py` — **71 passed**.

**Bypass observations:** no scanner bypass slipped through the tested matrix. One test fixture initially anchored a mapping, which correctly produced the path `data.password.password`; the fixture was corrected to anchor a scalar. `.properties` keys/values wrapped in matching single/double quotes are unquoted; whitespace-only values are treated as empty (no finding), while padded non-placeholder values are detected. Spec-scoped limitation: a sensitive leaf whose value is a container (`password: ["secret"]` or `password: {value: "secret"}`) is not a finding because [S1] requires a non-empty literal; this is recorded for completeness and is not exercised by the real LuckPerms/DiscordSRV configs. Full bypass matrix is in the P2-6e handoff.

**Acceptance Condition 7 re-evaluation: PASS for current P2 scope.** P2 enforces the scanner at repository initialization and Save & Commit, and the Clean Export path carries the OD-v8.5-1 Step 5 placeholder guard that fails closed on unresolved `${ONX_SECRET_*}` values. Per `DECISION-2026-11-12-001` D-8, merge, conversion, and push are future paths and must require the same scan before they become available; they are **not** claimed as exercised here. This batch re-ran Gate 6 for the scanner and did not re-run the export placeholder guard.

---

### Gate 7 — Allow-list v2.3 Live-Tree Clean Export (PASS)

**Command:**

```bash
cd backend && python /tmp/p26d-runs/gate7_clean_export.py
```

**Setup:** realistic Paper tree containing `server.properties`, `bukkit.yml`, `spigot.yml`, `config/paper-global.yml`, `plugins/Example/config.yml`, `plugins/Example.jar`, `server.jar`, `world/level.dat`, `world/session.lock`, `logs/latest.log`, `.env`, a hostile `config/evil.jar`, and an escaping symlink. Real `GitRepositoryService.initialize` + real CAS + real `CleanExportService.export`.

**Observed scan (allow-list v2.3):**

```
by_class: {"A-CAS": 0, "A-JAR": 2, "A-LOCKFILE": 0, "B": 5, "C": 0, "E": 3, "QUARANTINE": 1}
quarantined: ('config/evil.jar',)
skipped_symlinks: ('escape-link',)
skipped_dirs: ('logs',)
```

**Observed assertions (all PASS):**

- Class-B configs committed and exported (`server.properties`, `bukkit.yml`, `spigot.yml`, `config/paper-global.yml`, `plugins/Example/config.yml`).
- `server.jar` and `plugins/Example.jar` are **not** in the Git commit; they are materialized from CAS byte-for-byte into the export.
- `world/level.dat`, `world/session.lock`, `logs/latest.log`, `.env`, and `config/evil.jar` are absent from both the commit and the export.
- `world/` and `logs/` are absent; `.env` is absent; the escaping symlink is rejected by `open_safe_path_fd` (`SymlinkEscapeError`) and absent from the export.
- Export tree contains no symlinks, only regular files/dirs, **no hardlinks**, **no `.git`**, and a `.onx-complete.json` marker.

**Evidence:** `gate7-clean-export.log`.

---

## 4. P2 Acceptance Conditions (5, 6, 7, 8, 10, 11)

| # | Condition | Status | Basis |
|:-:|:----------|:------:|:------|
| 5 | Clean export fixed 5-step order, no `.git`, no hardlinks, `.onx-complete.json` | **PASS (real-run evidence)** | Gate 7: commit/export separation, CAS materialization, marker, no `.git`, `st_nlink == 1` for every exported file. |
| 6 | D-3 Paper 1.20.4/499 offline gate PASS with archived evidence | **PASS locally / archival pending** | Gate 1: two offline boots, `Done (...)`, clean exit `0`; automated SHA-256 `MATCH` against the 64-char decision hash; raw logs archived under the untracked evidence dir. The evidence is on disk but not committed (no commit authorized). |
| 7 | Scanner blocks at repo init, Save & Commit, merge, D7, push, export | **PASS (current P2 scope)** | Gate 6 re-run PASS; repo init + Save & Commit scanning enforced; Clean Export Step 5 placeholder guard per OD-v8.5-1/D-8. Merge/conversion/D7/push are future paths per D-8 and are not claimed as exercised. |
| 8 | Container hardening flags (non-root, `--cap-drop=ALL`, `no-new-privileges`, `--pids-limit=2048`, only `/data`) | **PASS** | Gate 2 raw `docker inspect` + assertions. |
| 10 | Repo lease/fencing, crash recovery, stale cleanup, disk-full behavior tested | **PASS** | Gate 3 (crash + B-A1 fencing + cleanup) and Gate 4 (`ENOSPC` + typed error + no leftovers). |
| 11 | Windows path-layer CI green for the supported Windows surface | **NOT RUN / UNVERIFIED** | Out of scope for this batch; no Windows runner was executed. Remains an open P2 condition. |

Condition 12 (per-directory suites, 6 gates, frontend checks, docs/state sync) is also open: this batch ran the repository gates but did not run the full suites, and `.ai/STATE.json` was intentionally untouched pending the proposal.

---

## 5. Repository Gates

Run in `/mnt/D/workspace/onx-manager-wt/p2-5-refresh-rollback`:

| Gate | Result |
|:-----|:-------|
| `./scripts/check-db-revision` | **PASS** — `Database schema revision 'b1e2100000026' is compatible.` |
| `./scripts/check-route-contract` | **PASS** — `156` live routes vs `156` contract entries. |
| `PATH=/home/mohamed/.local/bin:$PATH ./scripts/check-ruff-baseline` | **PASS** — `483` violations across `21` rules, all at or below baseline. |
| Targeted backend suites (P2-6e) | **PASS** — `121 passed` across scanner, Save & Commit, branch-files, save-commit API, advanced-initialization, clean-export suites. |
| `npx pyright` on changed `.py` files | **PASS** — `0 errors, 0 warnings, 0 informations`. |
| `git diff --check` | **PASS** — clean. |
| `git status --short` | P2-6e tracked changes: spec, scanner, scanner tests, this report; `.ai/` evidence/proposals are untracked; no commit. |

---

## 6. Defect Resolution — P2-6d-B1

**P2-6d-B1 (was BLOCKER, now FIXED): LuckPerms `data.password` was not detected.**

- **Original defect:** structured YAML/JSON scanning matched prefixed DB keys (`mysql.password`, `data.mysql-password`) but not a bare `password` leaf under LuckPerms' `data` block; `assert_no_secrets` accepted a config containing a real plaintext MySQL password.
- **Resolution (P2-6e):** the owner approved OD-v8.7-16; spec edits S1–S4 were applied, `secret_scanner.py` now treats `password`/`passwd`/`pwd` leaves at any nesting depth as sensitive plus the existing prefixed DB keys, `_flatten` walks lists/tuples, and `.properties` matching quotes are stripped before analysis. Placeholder/boolean/empty handling is unchanged in intent.
- **Regression coverage:** `tests/infrastructure/test_secret_scanner.py` — **71 passed**, including every [S3] vector, the bypass matrix, and the redaction assertion.
- **Re-run:** **Gate 6 PASS** (`gate6-rerun-secret-scanner.log`); details contain only `kind`/`key`.
- **Residual:** merge/D7/push paths remain future per D-8 and are not claimed as exercised; conditions 11 (Windows CI) and 12 (full suites/docs-state sync) remain open.

---

## 7. Boundaries and Artifacts

- **No commit / push / merge / reset / amend.** The P2-6e branch HEAD remains `90b54105c52ffabe0d7ec26e753d39f4e6830e79`.
- **P2-6e tracked changes:** `docs/design/SPEC-2026-11-09-SIMPLE-ADVANCED-MODES-02.md`, `backend/app/modules/versioning/infrastructure/secret_scanner.py`, `backend/tests/infrastructure/test_secret_scanner.py`, and this report.
- **Untouched:** `.ai/STATE.json`, master worktree (`e87009b85e8973a7c8b5aeaab8966bc5a68c9d26`), uncommitted `docs/` on master, `DECISION-2026-11-12-001-p2-planning.md`.
- **Untracked evidence:** `/mnt/D/workspace/onx-manager/.ai/orchestration/artifacts/p2-6d-evidence/` (original gates) and `/mnt/D/workspace/onx-manager/.ai/orchestration/artifacts/p2-6e-evidence/` (Gate 6 re-run, Gate 1 SHA-256, runner scripts).
- **Untracked proposals:** `/mnt/D/workspace/onx-manager/.ai/orchestration/artifacts/p2-6d-docs-proposals/` — `STATE-json-proposal.md`, `DECISION-p2-acceptance-proposal.md`, `SPEC-AMENDMENTS-proposal.md` (updated for P2-6e).
- **Cleanup:** P2-6d Gate 1 containers were removed; the 10 MiB tmpfs was unmounted by namespace exit; temporary run directories were removed after evidence capture. P2-6e used no containers.

### Evidence index

| File | Contents |
|:-----|:---------|
| `gate1-offline-boot-1.log` | Boot 1, stdin `stop`, exit 0 |
| `gate1-offline-boot-2.log` | Boot 2, stdin `stop`, exit 0 |
| `gate1-boot1-exit.txt` | Boot 1 container exit status |
| `gate1-offline-boot-1-sigterm-143.log` | Supplementary SIGTERM run (clean save, exit 143) |
| `gate2-docker-inspect.json` | Raw `docker inspect` |
| `gate2-inspect-summary.txt` | Compact hardening values |
| `gate2-hardening-check.log` | PASS/FAIL assertions |
| `gate3-crash-recovery.log` | Parent orchestration + observed journal |
| `gate3-child-refresh.log` | Refresh child output |
| `gate3-recover.log` | Reconciler + rollback assertions |
| `gate3-journal-at-kill.json` | Journal mirror at `SIGKILL` |
| `gate3-summary.json` | Machine-readable gate summary |
| `gate4-disk-full.log` | tmpfs ENOSPC run |
| `gate5-health-rollback.log` | Health gate + automatic rollback |
| `gate5-summary.json` | Machine-readable gate summary |
| `gate6-secret-scanner.log` | P2-6d scanner FAIL evidence + probes |
| `gate7-clean-export.log` | Allow-list/CAS/export assertions |
| `scripts/` | Archived P2-6d gate harness scripts |
| `../p2-6e-evidence/gate6-rerun-secret-scanner.log` | P2-6e Gate 6 re-run (PASS) |
| `../p2-6e-evidence/gate1-sha256-verify.log` | P2-6e automated SHA-256 `MATCH` |
| `../p2-6e-evidence/scripts/` | P2-6e re-run and hash verification runners |

---

**Final verdict: all seven P2-6d gates PASS after the P2-6e Gate 6 re-run (OD-v8.7-16). P2 is NOT yet accepted: conditions 5/6/7/8/10 are supported, condition 11 (Windows CI) remains unverified, and condition 12 (full suites/docs-state sync) remains open.**
