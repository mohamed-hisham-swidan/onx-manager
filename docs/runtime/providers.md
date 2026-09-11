# Server Provider Architecture & Runtime Drivers

**Status:** Living Reference (Synchronized with live codebase)  
**Provider Interface:** `ServerProvider` (`backend/app/modules/server/infrastructure/providers/base.py`)

---

## 1. Provider Strategy Overview

The server manager abstracts OS process management behind the `ServerProvider` interface:

| Provider Class | Status | Target Environment | Process Isolation Model |
|---|---|---|---|
| **`LocalLinuxProvider`** | **ACTIVE / FUNCTIONAL** | Linux / POSIX Host | `tmux` terminal multiplexer sessions with `MCS_MANAGED=1` environment markers. |
| **`LocalWindowsProvider`** | **ACTIVE / FUNCTIONAL** | Windows Host | Native Win32 detached processes (`CREATE_NEW_PROCESS_GROUP \| DETACHED_PROCESS \| CREATE_NO_WINDOW`) with Win32 process tracking. |
| **`DockerProvider`** | **ACTIVE / FUNCTIONAL** | Docker Daemon | Subprocess driver, bridge networking, loopback RCON, WSL2 support, DooD profile. |
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
- **PID liveness** (`local.py:464-472`, `_is_pid_alive()`): Uses `_run_command("kill -0 {pid} 2>/dev/null")` — a shell subprocess — rather than `os.kill()` directly.

---

## 3. `LocalWindowsProvider` Implementation Details

Location: `backend/app/modules/server/infrastructure/providers/windows.py`

- **Execution Driver:** Launches detached Java/Minecraft process groups with Win32 creation flags:
  `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS | CREATE_NO_WINDOW`.
- **Process Liveness & Tracking:**
  - Uses native Win32 `kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` and `GetExitCodeProcess`.
  - Avoids POSIX signal dependencies.
- **Graceful Teardown & Taskkill Fallback:**
  - First attempts graceful stop command via server standard input / RCON.
  - If process does not terminate within the grace period, executes `taskkill /F /T /PID {pid}` to cleanly terminate the entire process tree without leaving orphaned Java workers.
- **Structured Launch Configuration:**
  - Eliminates `shlex.split` Windows-path corruption by using structured `list[str]` launch configurations.

---

## 4. `DockerProvider` Implementation Details

Location: `backend/app/modules/server/infrastructure/providers/docker.py`

- **Execution Driver:** Launches Minecraft servers inside isolated Docker containers via
  tokenized subprocess calls (`asyncio.create_subprocess_exec`). Backend image packages
  the official standalone static Docker CLI (`docker:27.5.1-cli`).
- **Filesystem & Volume Model:**
  - Mounts entire server directory directly to `/data` (`-v {server_dir}:/data -w /data`).
  - `normalize_host_path` standardizes POSIX and Windows paths (drive letters, forward slashes).
  - Translates user UID/GID on Linux to avoid root permission lockouts on host files.
- **Bridge Network Model & Security:**
  - Containers attach to Docker bridge network (`--network bridge` by default).
  - External game ports published to host interfaces (`-p {port}:{container_port}`).
  - Strict loopback isolation for RCON: published strictly to `127.0.0.1:{rcon_port}` regardless
    of custom game-port bind IP.
- **RCON Transport:**
  - Primary: pure-Python asynchronous `AsyncRCONClient`.
  - Fallback: in-container `docker exec {container} rcon-cli "{cmd}"`.
- **Windows WSL2 Backend Policy:**
  - Enforces Linux container mode under WSL2 backend with actionable diagnostic error messages.
- **Docker-outside-of-Docker (DooD) Support:**
  - Supported via opt-in `docker-compose.dood.yml` profile with host socket mount
    (`/var/run/docker.sock`).
  - `resolve_host_mount_path` translates container-internal `/app/data/servers` paths to
    host-side paths using `ONX_HOST_DATA_DIR` environment variable for sibling mounts.

