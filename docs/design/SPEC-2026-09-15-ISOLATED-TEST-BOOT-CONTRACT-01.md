# Design Spec: Isolated Test Boot Contract & Executable Staging Hardening

**Document Status:** APPROVED WITH CHANGES  
**Governance Classification:** Decision Level D1 (Significant) / Lane A (Release Critical)  
**Governing Authority:** `docs/governance/GOVERNANCE.md` §4–5, §12; `Orchestrator.md §5, §7`  
**Spec Identifier:** `SPEC-2026-09-15-ISOLATED-TEST-BOOT-CONTRACT-01`  
**Review Decision:** Outcome: APPROVED WITH CHANGES (Design Review Decision 2026-09-15)  
**Date:** 2026-09-15  

---

## 1. Context & Problem Statement

Following the initial implementation of the isolated test verification engine (`SPEC-2026-09-15-ISOLATED-TEST-REAL-VERIFICATION-01`), design review and Windows-safety micro-recon revealed three critical operational contract gaps in the test container execution pipeline:

1. **Missing Container Launch Command (CMD):**  
   In `DockerTestExecutionRunner.run_test()`, the test container was launched via `docker run -d ... image` without appending a startup CMD. Because `resolve_docker_image()` returns base JRE images (`eclipse-temurin`), omitting the startup command causes the container to exit immediately or fail to launch the Minecraft server executable.
2. **Un-Staged Server Executable:**  
   While configuration files and mod jars were staged into the test root (`.onx/tests/<test_id>`), the actual server executable (`server.jar` or `run.sh` / `user_jvm_args.txt`) was not copied from the live server directory, leaving the container with no executable to run.
3. **Un-Gated Bot Connection Race:**  
   Verification drivers (Mineflayer / FakePlayer-Next / SmokeTest) were executed immediately upon container launch without confirming that the Minecraft server had completed its boot sequence. Real Minecraft servers take 10–30+ seconds to initialize, causing immediate connection rejections (`ECONNREFUSED`).
4. **Silent `cp` Failure on Non-Reflink Environments (Windows MSYS):**  
   In `test_runner.py:157-163`, `subprocess.run(["cp", "--reflink=auto", ...], check=False)` caught only exceptions. In environments where `cp` is present on `PATH` but lacks `--reflink` support (e.g. MSYS2/Git Bash on Windows), `cp` exits with code 1 without raising a Python exception, causing files to be silently omitted from staging.

---

## 2. Approved Design & Specifications

### 2.1 Step 1: Shared CMD Helper (`build_docker_server_cmd`)
Extract and unify the Docker launch command construction between `DockerProvider` and `DockerTestExecutionRunner`:

- **Location:** `backend/app/modules/server/infrastructure/providers/docker.py`
- **Function Signature:**
  ```python
  def build_docker_server_cmd(
      server_dir: Path | str | None = None,
      startup_command: list[str] | None = None,
      startup_jar: str | None = None,
      jvm_flags: list[str] | None = None,
      memory_min_mb: int = 1024,
      memory_max_mb: int = 2048,
      cpu_cores: int = 0,
      image: str = "",
  ) -> list[str]:
  ```
- **Rules:**
  - Script launches (`run.sh` present in `startup_command` or on disk in `server_dir`) emit `["bash", "/data/run.sh", "nogui"]`.
  - For standard Java execution: emits `["java", *jvm_flags, "-Xms{min}M", "-Xmx{max}M", "-jar", "/data/{jar_name}", "nogui"]` (with `-XX:ActiveProcessorCount` when `cpu_cores > 0`).
  - For `itzg/minecraft-server` images without explicit commands or jars, returns empty list to retain image entrypoint.

### 2.2 Step 2: Executable Staging with Safe Return-Code Checking
In `DockerTestExecutionRunner.run_test()`:

- Stage `run.sh` (and `user_jvm_args.txt`) if present, setting executable permissions (`chmod 0o755`).
- Otherwise, resolve and stage the server jar (`test_deployment.startup_jar`, `server.jar`, or primary `*.jar` from `spec.server_dir`).
- **Return Code Safety Rule:**
  Implement `stage_file_reflink_or_copy(src: Path, dst: Path)`:
  ```python
  def stage_file_reflink_or_copy(src: Path, dst: Path) -> None:
      dst.parent.mkdir(parents=True, exist_ok=True)
      try:
          res = subprocess.run(
              ["cp", "--reflink=auto", str(src), str(dst)],
              capture_output=True,
              check=False,
          )
          if res.returncode != 0 or not dst.exists():
              shutil.copy2(src, dst)
      except Exception:
          shutil.copy2(src, dst)
  ```
  Check `res.returncode != 0` and verify destination existence before falling back to `shutil.copy2`.
- **Follow-up Flag:** Apply this exact safe copy helper to both the new executable staging AND the existing mod-staging loop at `test_runner.py:157-163`, flagging the mod-staging call as a follow-up.

### 2.3 Step 3: Container Launch Policy (OQ-1 Accepted)
- Maintain detached execution: `docker run -d ...`.

### 2.4 Step 4: Boot-Gate via `latest.log` Polling
Before initiating verification drivers in `_execute_verification`:

- **Polling Target:** `<test_dir>/logs/latest.log` for the line marker `"Done ("`.
- **Item A Resolution (FACT-based):** No new `wait_ready` API mechanism is added; filesystem log inspection is the authoritative contract.
- **Item B Resolution (Forge/NeoForge):** Any failure in staging or booting Forge/NeoForge routes through the existing staging failure path.
- **OQ-3 Resolution (Timeout Floor):**
  `boot_timeout = max(bot_cfg.connect_grace_seconds, 120.0)`.
- **Failure Conditions During Boot-Gate:**
  1. Generation of files in `crash-reports/` -> immediately diagnose blamed mod via `PatternCrashAnalyzer` and mark `FAILED`.
  2. Container termination (`docker inspect .State.Running == false`) -> immediately mark `FAILED`.
  3. Expiry of `boot_timeout` without `"Done ("` -> mark `FAILED` with descriptive timeout message.

### 2.5 OQ-2: SmokeTestRunner Timeout Fix
Refactor `SmokeTestRunner.run_smoke_test()` in `backend/app/modules/versioning/infrastructure/bot_drivers.py`:

- Eliminate `_ = timeout_seconds`.
- Implement active polling loop up to `timeout_seconds` checking for:
  1. Crash report creation in `crash-reports/`.
  2. Container termination via `docker inspect`.
  3. Clean `"Done ("` boot string in `logs/latest.log`.
- Return `passed=False` on timeout expiry rather than falsely returning `passed=True`.

---

## 3. Scope Boundaries

- Strictly bounded to the approved spec + the return-code fix.
- No commit, push, or merge per `.ai/RULES/commit-and-safety.md` and `Orchestrator.md §15.7`.
- All quality gates must pass.
