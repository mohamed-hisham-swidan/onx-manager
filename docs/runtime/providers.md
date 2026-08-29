# Server Provider Architecture & Runtime Drivers

**Status:** Living Reference (Synchronized with live codebase)  
**Provider Interface:** `ServerProvider` (`backend/app/modules/server/infrastructure/providers/base.py`)

---

## 1. Provider Strategy Overview

The server manager abstracts OS process management behind the `ServerProvider` interface:

| Provider Class | Status | Target Environment | Process Isolation Model |
|---|---|---|---|
| **`LocalLinuxProvider`** | **ACTIVE / FUNCTIONAL** | Linux / POSIX Host | `tmux` terminal multiplexer sessions with `MCS_MANAGED=1` environment markers. |
| `LocalWindowsProvider` | *Deferred Stub* | Windows Host | PowerShell Background Jobs (`Start-Job`). |
| `DockerProvider` | *Deferred Stub* | Docker Daemon | Docker Engine API / container execution. |
| `SSHProvider` | *Deferred Stub* | Remote Linux Host | AsyncSSH remote tmux sessions. |
| `CloudProvider` | *Deferred Stub* | Cloud VM Instances | Cloud compute API instance management. |

---

## 2. `LocalLinuxProvider` Implementation Details

Location: `backend/app/modules/server/infrastructure/providers/local.py`

- **Execution Driver:** Launches servers inside isolated tmux sessions named `mcs-{server_id}`.
- **Script & JAR Launch Support:**
  - Standard JARs: `java {jvm_args} -Xms{min}M -Xmx{max}M -jar {jar} nogui`
  - Forge/NeoForge Scripts: Automatically generates `user_jvm_args.txt` and executes `bash run.sh nogui`.
- **Process Marker Tracking:** Injects `export MCS_MANAGED=1 MCS_INSTANCE_ID={uuid};` before server command to allow unambiguous process ownership verification (ADR 0011).
- **Log Recovery:** If tmux capture-pane output is unavailable, falls back to reading the last 300 lines of `logs/latest.log`.
- **PID liveness** (`local.py:464-472`, `_is_pid_alive()`): Uses `_run_command("kill -0 {pid} 2>/dev/null")` — a shell subprocess — rather than `os.kill()` directly. **This method is intentionally excluded from the W-06 cross-platform PID-liveness migration.** Do not refactor it to use `platform_pid_alive()`; it is part of this Linux-only provider's existing verification path and must remain as-is.
