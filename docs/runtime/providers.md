# Server Providers

## Pattern

Providers implement the **Strategy pattern** — they abstract OS-level server lifecycle operations behind a common interface. The runtime system never talks directly to tmux, Docker, or SSH; it always goes through `ServerProvider`.

## Abstract Interface

Defined in `infrastructure/providers/base.py`.

### ServerRuntimeStatus

```python
class ServerRuntimeStatus(Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    UNKNOWN = "unknown"
```

### ServerHandle

A frozen dataclass that identifies a running server instance to a provider:

- `provider` — provider type string.
- `server_id` — server UUID.
- `external_id` — provider-specific identifier (tmux session name, container name, job ID).
- `metadata` — arbitrary key-value data.

### DeploymentResult

Returned by `start()`:

- `status`, `address`, `port`, `pid`, `metadata`.

### ServerProvider (ABC)

| Method | Signature | Description |
|--------|-----------|-------------|
| `ping` | `→ bool` | Check if the provider is available. |
| `start` | `(server_id, config, deployment, launch_config) → DeploymentResult` | Launch the server process. |
| `stop` | `(handle, force=False)` | Stop the server. Graceful by default. |
| `status` | `(handle) → ServerRuntimeStatus` | Query runtime status. |
| `console` | `(handle, tail=100) → list[str]` | Fetch recent log lines. |
| `execute_command` | `(handle, command) → str` | Send a command to the server console. |
| `destroy` | `(handle)` | Force-stop and remove all resources. |
| `wait_ready` | `(server_id, handle, timeout) → bool` | Poll until the server is ready. Default returns `True` immediately. |
| `verify_process` | `(handle) → bool` | Check if the OS process is alive. Default calls `status()` and checks for `RUNNING`. |
| `collect_diagnostics` | `(handle) → RuntimeDiagnostics` | Gather crash diagnostics (log lines, PID, failure patterns). |
| `get_runtime_pid` | `(handle) → int or None` | Get the OS PID of the running process. |

### ProviderFactory

A registry that maps provider type strings to `ServerProvider` instances:

```python
factory = ProviderFactory()
factory.register(LocalLinuxProvider())
provider = factory.get("local")  # raises ValueError if not found
```

A module-level singleton `provider_factory` is created in `base.py` and populated in `providers/__init__.py`.

## Available Implementations

### LocalLinuxProvider (`provider_type = "local"`)

- Uses tmux sessions to manage server processes.
- `start()`: cleans stale tmux/processes, verifies port free, creates tmux session, returns PID.
- `stop()`: sends "say/save-all/stop" commands (graceful), then SIGTERM → SIGKILL, kills tmux session.
- `wait_ready()`: polls `console()` for "Done (" in log output.
- `collect_diagnostics()`: fetches last 300 log lines, runs `detect_failure()` from `patterns.py`.
- Platform check: `is_linux()` returns `True` only on POSIX Linux.

#### JVM PID resolution

tmux's pane PID (`tmux display-message -p '#{pane_pid}'`) is the **wrapper shell**
(`fish`/`bash`) spawned by the session, not the Minecraft Java process. Recording
the pane PID as `deployment_pid` yields an almost-empty process (a few MB of RSS)
and near-zero CPU/RAM in metrics, even though the server itself is healthy.

To report the real runtime, `LocalLinuxProvider` resolves the actual JVM PID:

- `_resolve_server_pid(session_name)` — reads the tmux pane PID, then walks the
  child process tree (up to 4 levels deep via `ps -o pid=,ppid=,comm= --ppid`)
  and returns the first descendant whose command name is `java`.
- Falls back to the pane PID if no `java` descendant is found (e.g. a wrapper
  or non-Java launcher).
- `start()` waits ~1s for the JVM to spawn, then records the resolved PID in
  `DeploymentResult.pid`.
- `get_runtime_pid()` resolves the JVM PID the same way, so
  `runtime_reconciliation` liveness checks (`kill(pid, 0)`) test the real process.

Unit tests mock `_get_tmux_pid` with fake PIDs that do not exist as live
processes, so the fallback path keeps them green while the real ps-walk is
covered by live verification.

## Process CPU sampling

`MetricsCollector` caches `psutil.Process` objects keyed by PID so
`cpu_percent()` deltas are computed against the previous sample. Two pitfalls
are handled:

- **Fresh PID** (a server just restarted, so a new JVM PID appears in the
  cache): `psutil.cpu_percent(interval=0)` would return `0.0` for the first
  tick because there is no baseline yet. The first sample instead uses
  `interval=0.1` to block briefly and return a real reading, so the UI never
  shows a misleading 0% right after a restart.
- **Stale cache entry** (PID was reused or the process died): the entry is
  validated via `is_running()` + `create_time()` equality, popped, and
  re-created as a fresh sample.

If `psutil` is unavailable (`_HAS_PSUTIL = False`), process metrics return
zeros and RCON-based metrics continue to work.

### LocalWindowsProvider (`provider_type = "local_windows"`)

- Uses PowerShell background jobs (`Start-Job` / `Stop-Job`).
- `start()`: creates a PowerShell job that runs the Java server command.
- `stop()`: `Stop-Job` (optionally `-Force`), then `Remove-Job`.
- `status()`: checks `(Get-Job).State`.
- Platform check: `is_windows()` returns `True` only on Windows.

### DockerProvider (`provider_type = "docker"`)

- Uses the `itzg/minecraft-server` Docker image (configurable).
- `start()`: pulls image if missing, `docker create` with env/volume/port flags, `docker start`, returns container PID.
- `stop()`: `docker exec rcon-cli 'stop'` (graceful), then `docker stop` / `docker kill`.
- `status()`: `docker inspect` for container state.
- `console()`: `docker logs --tail`.
- `execute_command()`: `docker exec rcon-cli`.

### SSHProvider (`provider_type = "ssh"`)

- Connects to a remote host via `asyncssh`.
- Uses tmux on the remote host (same pattern as `LocalLinuxProvider` but over SSH).
- `start()`: runs `mkdir -p`, creates tmux session remotely, returns PID.
- `status()`: `tmux has-session` and `kill -0` over SSH.
- `external_id` format: `host:session_name`.
- Connection pooling: reuses connections with keepalive, reconnects on failure.

### CloudProvider (`provider_type = "cloud"`)

- Abstract base for cloud VM provisioning (AWS, GCP, Azure, DigitalOcean, Hetzner).
- `provision_vm()` / `deprovision_vm()` / `get_vm_status()` / `list_vms()`.
- `start()` and `stop()` raise `NotImplementedError` — a provisioned VM is assumed and an SSHProvider would be used within it.
- `CloudProviderStub` returns dummy data for development/testing.

### CircuitBreakerProviderWrapper

- A decorator that wraps any `ServerProvider` with a `CircuitBreaker`.
- Default: 5 failures, 30s cooldown.
- Delegates all methods to the wrapped provider through the breaker.

## How to Add a New Provider

1. Create a new file in `infrastructure/providers/`.
2. Subclass `ServerProvider` and implement all abstract methods.
3. Set `provider_type` to a unique string.
4. Register it in `providers/__init__.py`:

```python
from .my_provider import MyProvider
provider_factory.register(MyProvider())
```

5. Add the import and class to `__all__` in `__init__.py`.

The provider will then be available anywhere `provider_factory.get("my_type")` is called — no other code changes required.

## References

- [Runtime Overview](README.md)
- [Server Lifecycle](lifecycle.md) — how providers are used in start/stop flows.
- [Supervision](supervision.md) — how providers supply verify_process and collect_diagnostics.
