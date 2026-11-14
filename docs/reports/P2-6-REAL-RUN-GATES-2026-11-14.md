# P2-6 Real-Run In-Phase Gates — Evidence Report — 2026-11-14

**Slice:** P2-6d — Real-Run In-Phase Gates & Evidence
**Worktree:** `/mnt/D/workspace/onx-manager-wt/p2-5-refresh-rollback`
**Branch:** `slice/p2-6d-real-run-gates`
**Base:** `slice/p2-6c2-redteam-remediation` @ `c3a73bf0984f44693c3656ac031c633276f82486`
**Master gate:** `/mnt/D/workspace/onx-manager` @ `e87009b85e8973a7c8b5aeaab8966bc5a68c9d26` (untouched)
**Status:** **FAIL — P2 NOT ACCEPTED.** 6 of 7 gates PASS; **Gate 6 is a real FAIL** (LuckPerms SQL password is not detected by `secret_scanner.py`).

> **Boundary statement:** This batch executed the real-run gates only. **No production code was edited** and **no commit, push, merge, reset, or amend was performed**. The only tracked deliverable is this report. Raw evidence and the three proposals live in the untracked `.ai/orchestration/artifacts/` tree and were never staged. `.ai/STATE.json` was not modified. The master worktree was not touched.

---

## 1. Verdict Summary

| # | Gate | Result | Evidence |
|:-:|:-----|:------:|:---------|
| 1 | D-3 Paper 1.20.4/499 offline boot ×2 with panel hardening | **PASS** | `gate1-offline-boot-1.log`, `gate1-offline-boot-2.log`, `gate1-boot1-exit.txt` (+ supplementary `gate1-offline-boot-1-sigterm-143.log`) |
| 2 | `docker inspect` hardening verification | **PASS** | `gate2-docker-inspect.json`, `gate2-inspect-summary.txt`, `gate2-hardening-check.log` |
| 3 | `kill -9` crash injection + startup recovery + rollback | **PASS** | `gate3-crash-recovery.log`, `gate3-child-refresh.log`, `gate3-recover.log`, `gate3-journal-at-kill.json`, `gate3-summary.json` |
| 4 | Small-FS disk-full run (unprivileged tmpfs) | **PASS** | `gate4-disk-full.log` |
| 5 | Real health gate failure + automatic triad rollback | **PASS** | `gate5-health-rollback.log`, `gate5-summary.json` |
| 6 | DiscordSRV / LuckPerms secret scanner | **FAIL** | `gate6-secret-scanner.log` |
| 7 | Allow-list v2.3 live-tree clean export | **PASS** | `gate7-clean-export.log` |

**Overall:** **FAIL / not accepted** until Gate 6 is fixed, re-run, and reviewed. All other gates passed on real runs; the remaining P2 conditions outside this batch (Windows CI, docs/state sync) are still open.

---

## 2. Environment

| Item | Value |
|:-----|:------|
| Date | 2026-11-14 |
| Host | Linux, Docker `29.9.2`, unprivileged user `1000` |
| Docker image | `eclipse-temurin:17-jre` (`sha256:0b6521287f850ec1c4b31c9074c5a1ae1d67c5922c3fefd21065c7c32e244d4a`) |
| Paper jar | `/tmp/onx-d3/paper-1.20.4-499.jar` |
| Paper SHA-256 (measured) | `cabed3ae77cf55deba7c7d8722bc9cfd5e991201c211665f9265616d9fe5c77b` |
| Vanilla cache seed | `cache/mojang_1.20.4.jar`, SHA-1 `8dd1a28015f51b1803213892b50b7b4fc76e594d` |
| Unprivileged mount | `unshare -U -r -m` + `mount -t tmpfs -o size=10m` verified working (no `sudo`) |

**Hash note:** the build brief lists `cabed3ae77cf55deba7c7d822bc9cfd5e991201c211665f9265616d9fe5c77b` (63 hex chars). The measured jar is `cabed3ae77cf55deba7c7d8722bc9cfd5e991201c211665f9265616d9fe5c77b` (64 hex chars); the brief value appears to contain a transcription typo. The measured value is used throughout this report.

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

**Evidence:** `gate1-offline-boot-1.log`, `gate1-offline-boot-2.log`, `gate1-boot1-exit.txt`, `gate1-offline-boot-1-sigterm-143.log`.

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

### Gate 6 — DiscordSRV / LuckPerms Secret Scanner (**FAIL — real defect**)

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

## 4. P2 Acceptance Conditions (5, 6, 8, 10, 11)

| # | Condition | Status | Basis |
|:-:|:----------|:------:|:------|
| 5 | Clean export fixed 5-step order, no `.git`, no hardlinks, `.onx-complete.json` | **PASS (real-run evidence)** | Gate 7: commit/export separation, CAS materialization, marker, no `.git`, `st_nlink == 1` for every exported file. |
| 6 | D-3 Paper 1.20.4/499 offline gate PASS with archived evidence | **PASS locally / archival pending** | Gate 1: two offline boots, `Done (...)`, clean exit `0`; raw logs archived under the untracked evidence dir. The evidence is on disk but not committed (no commit authorized). |
| 7 | Scanner blocks at repo init, Save & Commit, merge, D7, push, export | **NOT SATISFIED** | Gate 6 FAIL: LuckPerms `data.password` is missed. Blocker for P2 acceptance. |
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
| `git diff --check` | **PASS** — clean. |
| `git status --short` | Only `docs/reports/P2-6-REAL-RUN-GATES-2026-11-14.md` (this report) is new; `.ai/` untouched in the worktree. |

---

## 6. Defect and Required Follow-up

**P2-6d-B1 (BLOCKER): LuckPerms `data.password` is not detected.**

- **File:** `backend/app/modules/versioning/infrastructure/secret_scanner.py`, `_SENSITIVE_KEY_RE` (lines 49–56); normative regex at `docs/design/SPEC-2026-11-09-SIMPLE-ADVANCED-MODES-02.md:846-850`.
- **Behavior:** structured YAML/JSON scanning matches prefixed DB keys (`mysql.password`, `data.mysql-password`) but not a bare `password` leaf under LuckPerms' `data` block; `assert_no_secrets` therefore accepts a config containing a real plaintext MySQL password.
- **Required:** approve the proposed OD-v8.7-16 amendment (`SPEC-AMENDMENTS-proposal.md`), fix the production regex plus add a regression test using a realistic LuckPerms config, and re-run Gate 6. Until then, Gate 6 remains FAIL and P2 acceptance cannot be claimed.
- **Constraint honored:** no production edit was made in this batch; the defect is reported, not patched.

---

## 7. Boundaries and Artifacts

- **No commit / push / merge / reset / amend.** The branch remains at `c3a73bf0984f44693c3656ac031c633276f82486`.
- **Only tracked change:** this report. No production file, test, workflow, or contract was modified.
- **Untouched:** `.ai/STATE.json`, master worktree (`e87009b85e8973a7c8b5aeaab8966bc5a68c9d26`), uncommitted `docs/` on master, `DECISION-2026-11-12-001-p2-planning.md`.
- **Untracked evidence:** `/mnt/D/workspace/onx-manager/.ai/orchestration/artifacts/p2-6d-evidence/` — raw logs, JSON, summaries, and archived gate scripts under `scripts/`.
- **Untracked proposals:** `/mnt/D/workspace/onx-manager/.ai/orchestration/artifacts/p2-6d-docs-proposals/` — `STATE-json-proposal.md`, `DECISION-p2-acceptance-proposal.md`, `SPEC-AMENDMENTS-proposal.md`.
- **Cleanup:** Gate 1 containers were removed; the 10 MiB tmpfs was unmounted by namespace exit; temporary run directories were removed after evidence capture.

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
| `gate6-secret-scanner.log` | Scanner FAIL evidence + probes |
| `gate7-clean-export.log` | Allow-list/CAS/export assertions |
| `scripts/` | Archived gate harness scripts |

---

**Final verdict: FAIL — Gate 6 is a real blocker; P2 acceptance conditions 5/6/8/10 are supported by real-run evidence, condition 7 is not satisfied, and condition 11 remains unverified.**
