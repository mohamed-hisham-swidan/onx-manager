# Server Provider Architecture & Runtime Drivers

**Status:** Living Reference (Synchronized with live codebase)  
**Provider Interface:** `ServerProvider` (`backend/app/modules/server/infrastructure/providers/base.py`)

---

## 1. Provider Strategy Overview

The server manager abstracts OS process management behind the `ServerProvider` interface:

| Provider Class | Status | Target Environment | Process Isolation Model |
|---|---|---|---|
| **`DockerProvider`** | **ACTIVE / SOLE LOCAL RUNTIME (P6)** | Docker Daemon | Hardened isolated containers (`--cap-drop=ALL`, non-root `--user`, `--pids-limit=2048`), bridge networking, loopback RCON, WSL2 support, DooD profile. |
| `SSHProvider` | *Deferred Stub* | Remote Linux Host | AsyncSSH remote sessions. |
| `CloudProvider` | *Deferred Stub* | Cloud VM Instances | Cloud compute API instance management. |

> **P6 Docker-Only Runtime:** The legacy host-process providers (`LocalLinuxProvider` / tmux and `LocalWindowsProvider`) were removed in P6 (`P6-2`); existing local servers migrate via `P6-1` Docker migration tooling.

---

## 2. `DockerProvider` Implementation Details

Location: `backend/app/modules/server/infrastructure/providers/docker.py`

- **Execution Driver:** Launches Minecraft servers inside isolated Docker containers via
  tokenized subprocess calls (`asyncio.create_subprocess_exec`). Backend image packages
  the official standalone static Docker CLI (`docker:27.5.1-cli`).
- **Filesystem & Volume Model:**
  - Mounts entire server directory directly to `/data` (`-v {server_dir}:/data -w /data`).
  - `normalize_host_path` standardizes POSIX and Windows paths (drive letters, forward slashes).
  - Translates user UID/GID on Linux to avoid root permission lockouts on host files.
- **Bridge Network Model, Security & Dynamic IP Resolution:**
  - Containers attach to Docker bridge network (`--network bridge` by default).
  - External game ports published to host interfaces (`-p {port}:{container_port}`).
  - Strict loopback isolation for RCON: published strictly to `127.0.0.1:{rcon_port}` regardless
    of custom game-port bind IP.
  - Dynamic Container IP: atomically inspects PID and network IP via
    `docker inspect --format='{{.State.Pid}} {{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'`.
    Exposes `get_container_ip()` and `get_address()` for live GUI/console network resolution.
- **Dynamic Java Base Image Selection:**
  - `resolve_docker_image()` dynamically selects `eclipse-temurin` images by Minecraft version:
    Java 25 (>=26.1), Java 21 (1.20.5-1.21.x), Java 17 (1.17-1.20.4), Java 8 (<=1.16.5), with
    override support via `image_override`.
- **Crash Diagnostics & Exit Code Mapping:**
  - `status()` inspects `{{.State.Status}} {{.State.ExitCode}}`, accurately mapping clean container stops (`exited 0`)
    to `ServerRuntimeStatus.STOPPED` (preventing false crash alerts), and non-zero exits to `ServerRuntimeStatus.ERROR`.
  - `collect_diagnostics()` inspects container exit code, OOMKilled flag, and standard error log tails into `EvidenceBundleModel`.
  - Dead container collisions are automatically pruned via `docker rm -f` during startup retries.
- **Broadened Container Destruction & Orphan Prevention:**
  - `destroy()` removes containers matching container name, legacy name, server ID labels (`com.onxmanager.server-id` and legacy `com.mcsmanager.server-id`), and host volume bind mounts (`--filter volume={host_mount}`) to prevent orphaned containers upon server deletion or reconciliation cleanup.
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


