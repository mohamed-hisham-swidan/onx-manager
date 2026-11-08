# SPEC-2026-11-08-SERVER-LIFECYCLE-HARDENING-01: Multi-Worker Server Lifecycle Lock, Fail-Closed Stop & Promote Rollback, Container Adoption, and Process Identity Verification

- **Document ID:** `SPEC-2026-11-08-SERVER-LIFECYCLE-HARDENING-01`
- **Status:** Implemented (Batches 1–4 Complete & Verified 2026-11-07)
- **Date:** 2026-11-08
- **Lane:** 1 — Core Reliability (`docs/governance/GOVERNANCE.md` §3)
- **Supersedes:**
  - `docs/design/SPEC-2026-10-03-SERVER-LIFECYCLE-LOCK-AND-IDEMPOTENCY-01.md` (Approved Rev 2, never implemented; assumed a single-process `asyncio.Lock` and deferred multi-worker DB locking)
  - `docs/design/SPEC-2026-10-20-PROMOTE-ATOMICITY-STOP-GUARD-01.md` §3.2–§3.4 (F1-2b stop-confirmation guard and F1-2c boot reconciliation `STOPPING` fix were never implemented; F1-2a atomic single-file config writes were implemented)

---

## 1. Goal

Harden server lifecycle management across Docker, Linux local, and Windows local runtimes so that:

1. **Multi-worker per-server serialization:** All mutating lifecycle operations for a given `server_id` (`start`, `stop`, `restart`, `delete`, `promote`, `restore`, `retry_provisioning`, and per-server reconciliation repairs) are serialized through a database-backed lease (`server_lifecycle_leases`) using the same atomic acquisition, owner-token, TTL expiry, and cancel-safe release pattern as `server_admission_lease` (`backend/app/modules/versioning/application/scheduling/admission.py:83-123`).
2. **Idempotent start and TOCTOU elimination:** Server status is re-read from the database *inside* the held lock before any supervisor mutation or provider call. Repeated `start` calls on an already `RUNNING` or healthy `STARTING` server return an idempotent success without stopping the active `RuntimeSupervisor` or recreating the runtime. `stop` during `start`, `delete` during `start`, and `delete` during `PROVISIONING` cannot interleave.
3. **Non-destructive Docker container conflict resolution:** `DockerProvider.start()` never runs a blind `docker rm -f` on a name conflict. Existing containers are pre-inspected and handled by state, ownership label (`com.onx-manager.server_id`), and configuration fingerprint (`com.onx-manager.config-fingerprint`): foreign containers are refused, running owned containers with a matching fingerprint are adopted (or fail closed on plain `start` when the fingerprint mismatches), and only `exited`/`created` owned containers are removed with non-force `docker rm`.
4. **Fail-closed `stop_confirmed` contract:** A server is never transitioned to `STOPPED` unless a valid runtime handle exists, `provider.status(handle)` confirms `STOPPED` with no errors or warnings, and the game port is confirmed free. `DockerProvider.stop()` verifies container exit after `docker stop` and `docker kill`. `promote`, `restart`, `delete`, and `restore` abort before mutating files or state if `stop_confirmed` is not `True`. `start` aborts if the game port remains occupied after ownership claim.
5. **Startup timeout, supervisor crash, and reconciliation hardening:** `provider.start()` timeouts clean up any partially spawned container or process before marking `STOPPED`. `RuntimeSupervisor._handle_crash()` stops still-running containers/processes across all providers (not only `tmux`). Failed `STARTING -> RUNNING` database saves are retried with backoff and self-healed on subsequent health checks. Boot reconciliation checks `provider.status(handle)` before resolving `STOPPING` servers.
6. **All-or-nothing promote with rollback and restart:** `PromoteCommitHandler` stages pre-promote backups of target configs, `mods`, and `world*` directories on the same filesystem before mutating the production server directory. Any failure during config, `mods`, or `world*` application rolls back all prior changes to a byte-identical state and restarts the server if it was previously running.
7. **Windows handle PID propagation and cross-platform process identity verification:** `ServerHandle` construction across all lifecycle handlers populates `metadata["pid"]`, `metadata["start_time"]`, and `metadata["server_dir"]` so `LocalWindowsProvider.stop()` and `status()` never silently no-op. Every OS signal or `taskkill` path verifies process identity (`create_time`, command-line signature, and server directory / `ONX_MANAGED=1`) before terminating a process.

---

## 2. Current Behavior

Each claim from the security/reliability review was verified against the current repository working tree. Statements are tagged `FACT`, `ASSUMPTION`, `UNKNOWN`, or `CONFLICT` with exact `file:line` references.

> **Working-Tree Offset Note (`FACT`):** The working tree currently has uncommitted FX-1 containment edits in `backend/app/modules/server/infrastructure/providers/docker.py` (+2 lines near top) and `backend/app/modules/server/application/commands/delete_server.py` (+3 lines near top). Line numbers below reference the current working-tree files.

### 2.1 Claim A — Docker Blind `rm -f`, Missing Lifecycle Lock, and Non-Idempotent Start

- **A.1: Docker create name conflict triggers a blind `docker rm -f` of a possibly healthy container (`CONFIRMED` — `FACT`):**
  - `FACT` (`backend/app/modules/server/infrastructure/providers/docker.py:323,474-477`): `DockerProvider.start()` computes `container_name = self._container_name(server_id)` (`f"onx-{server_id}"`) at `:323` and runs `await self._docker_command(*create_args)` at `:474`. If `returncode != 0 and ("Conflict" in output or "already in use" in output)` (`:475`), it immediately executes `await self._docker_command("rm", "-f", container_name)` (`:476`) and retries `create` (`:477`) without inspecting whether the existing container is `running`, whether it belongs to ONX Manager (`com.onx-manager.server_id`), or whether its configuration matches.
- **A.2: Start handlers have no lock and no idempotent early return (`CONFIRMED` — `FACT`):**
  - `FACT` (`backend/app/modules/server/application/commands/start_server.py:43,51-125,278-286`; `backend/app/registration.py:332-340`; `backend/app/core/idempotency.py:12-16,64-191`): `SPEC-2026-10-03-SERVER-LIFECYCLE-LOCK-AND-IDEMPOTENCY-01` was never implemented (`backend/app/modules/server/application/lifecycle_lock.py` does not exist). `IdempotencyMiddleware` (`idempotency.py:64-191`) keys on `command.idempotency_key`, which defaults to a fresh random UUID per command instance (`start_server.py:43`), and stores keys in an in-process dict (`InMemoryIdempotencyStore` at `idempotency.py:12-16`, registered at `registration.py:332`). It provides zero serialization across concurrent requests or multiple worker processes.
  - `FACT` (`backend/app/modules/server/application/commands/start_server.py:55-61,118-125,278-286`; `backend/app/modules/server/domain/aggregate.py:66-76,328-330`): At the top of `StartServerHandler.handle()`, lines `:55-61` check `RuntimeSupervisor.get_active(sid)` and call `await RuntimeSupervisor.stop_for(sid)` *before* checking the server's database status. At `:119`, `server.start()` enforces `_VALID_TRANSITIONS` (`aggregate.py:66-76`), which only allows `STOPPED -> STARTING` and `CRASHED -> STARTING`.
    - If a server is already `STARTING` or `RUNNING`, a second `StartServerCommand` first kills the active in-process `RuntimeSupervisor` (`:61`) and then raises `InvalidValueError("Cannot transition server from ServerStatus.RUNNING to ServerStatus.STARTING")` (`aggregate.py:297-304`, HTTP 422), leaving the running container/process unsupervised.
    - If two `StartServerCommand` requests arrive while the database row is `STOPPED` (before `:124` `await uow.commit()`), both read `STOPPED`, both commit `STARTING`, and both execute `provider.start()` (`:278-286`), where the second triggers `docker rm -f` (`docker.py:476`) against the container the first request just started.

### 2.2 Claim B — Fail-Open Stop, Unconfirmed Destructive Callers, Promote Without Rollback, and Occupied-Port Continuation

- **B.1: Stop is not fail-closed (`CONFIRMED` — `FACT`):**
  - `FACT` (`backend/app/modules/server/application/commands/stop_server.py:74,85-105,112-135,140-156,165-194`):
    - When `server.runtime` is `None` or `server.runtime.external_id` is empty (`:74`), `StopServerHandler` skips all provider stop and status checks and still calls `server.mark_stopped()` at `:168`.
    - When `provider.status(handle)` returns `ServerRuntimeStatus.RUNNING` after `provider.stop(handle)` (`:114-122`), `StopServerHandler` retries `provider.stop(handle, force=True)` and re-checks `provider.status(handle)` (`:121`). If still `RUNNING`, it appends `"Runtime still running after stop"` to `provider_errors` (`:122`). If `status != ServerRuntimeStatus.STOPPED`, it appends `f"Runtime status is {status.value} after stop"` (`:131`). If `provider.status(handle)` raises an exception, `:134-135` swallows it with `except Exception: pass`.
    - If the game port is still listening after `_wait_for_port_free` (`:140-156`), it appends `f"Port {stop_port} still listening after stop"` (`:156`).
    - Despite non-empty `provider_errors`, lines `:165-170` unconditionally load the server, call `server.mark_stopped()` (`:168`, which clears `self._runtime = self._runtime. with_cleared_external_id()` to `external_id=""` at `aggregate.py:391`), commit `STOPPED` to the DB, and return `CommandResult(success=True, data={"server_id": sid, "status": "stopped", "warnings": provider_errors})` (`:183-194`).
  - `FACT` (`backend/app/modules/server/infrastructure/providers/docker.py:624-644`):
    - In `DockerProvider.stop()`, when `force=True` (`:626-628`), it runs `await self._docker_command("kill", container_name)` and returns immediately without checking `returncode` or waiting for container exit.
    - When `force=False` (`:632-644`), if RCON stop fails or `_wait_for_container_exit(container_name, timeout=15)` returns `False` (`:636-638`), it runs `await self._docker_command("stop", "-t", "30", container_name)` (`:643`) without checking `returncode` or confirming that the container exited.
    - Furthermore, `stop_server.py:87` wraps `self._provider.stop(handle)` in `asyncio.wait_for(..., timeout=_PROVIDER_CALL_TIMEOUT)` where `_PROVIDER_CALL_TIMEOUT = 15` (`:30`), which cancels `DockerProvider.stop()` before its 15s RCON wait + 30s `docker stop -t 30` can complete, forcing fallback to `force=True` (`docker kill` without exit verification).
- **B.2: Promote, delete, and restore proceed after an unconfirmed stop; promote swaps `mods`/`world*` with no rollback (`CONFIRMED` — `FACT`):**
  - `FACT` (`backend/app/modules/versioning/application/commands/promote_commit.py:182-207`):
    - Line `:182` computes `was_running = server.status in (ServerStatus.RUNNING, ServerStatus.STARTING)` (omitting `ServerStatus.STOPPING`).
    - Line `:184` executes `await self._command_bus.send(StopServerCommand(server_id=server.id))` and **discards the returned `CommandResult`**, proceeding directly to config writes (`:188-193`), `mods` replacement (`:196-199`), and `world*` replacement (`:202-207`) even if the server is still running and writing to `world/` or holding file locks on `mods/*.jar`.
    - While single-file config writes use `write_text_atomic` (`:191`) and single-directory swaps use `_atomic_replace_dir` (`backend/app/modules/backup/application/restore_service.py:170-207`), `_atomic_replace_dir` moves `src` out of `test_dir` (`shutil.move(str(src), str(temp_stage))` at `restore_service.py:192`) and deletes `old_path` in `finally` (`shutil.rmtree(old_path, ignore_errors=True)` at `restore_service.py:205-206`). If config $k$ of $N$ fails, or `mods` swap succeeds and `world_nether` swap fails, earlier mutations cannot be rolled back and `server_dir` is left in a corrupt split-commit state without restarting the server.
  - `FACT` (`backend/app/modules/server/application/commands/delete_server.py:95-180`):
    - Lines `:95-106` invoke `stop_handler.handle(StopServerCommand(server_id=command.server_id, force=True))`, ignore its return value, catch and log any exception (`:105-106`), catch and log `provider.destroy(handle)` errors (`:113-139`), delete the DB row (`:155`), and delete `server_dir` (`:174`) while the container or JVM may still be running.
  - `FACT` (`backend/app/modules/backup/application/commands/restore_backup.py:24-26,71-117`; `backend/app/modules/server/application/commands/start_server.py:206-210`; `backend/app/modules/server/application/commands/restart_server.py:184-188`):
    - Because a failed `StopServerCommand` still marks the server `STOPPED` in the DB (`stop_server.py:168`), a subsequent `RestoreBackupCommand` sees `server.status.value == "stopped"` (not in `_NON_IDLE_STATUSES` at `restore_backup.py:24-26`) and runs `perform_safe_restore` (`:113`) directly on the live server directory.
    - When a restore is deferred (`pending_restore_backup_id`), `consume_pending_restore` runs in `restart_server.py:184-188` and `start_server.py:206-210` even when `stop_errors` occurred (`restart_server.py:172-178`) or the port is still occupied (`start_server.py:179-200`).
- **B.3: `restart_server.py` and `start_server.py` continue despite stop errors or an occupied port (`CONFIRMED` — `FACT`):**
  - `FACT` (`backend/app/modules/server/application/commands/restart_server.py:92-98,121-188`): `RestartServerHandler` transitions the server to `STOPPING` and immediately `STOPPED` in the DB (`:92-98`) *before* stopping the supervisor or provider. At `:172-178`, when `stop_errors` is non-empty (`"Runtime still running after stop"`, `"Port ... still listening after stop"`, or stop timeout), it only logs a warning and continues into `consume_pending_restore` (`:184`), `consume_pending_plugin_deletions` (`:214`), `server.start()` (`:244`), and `provider.start()` (`:296`).
  - `FACT` (`backend/app/modules/server/application/commands/start_server.py:179-200`): After `claim_localhost`, `StartServerHandler` checks `if _port_is_listening(port):` (`:179`), logs `logger.error("Port %d still occupied after ownership claim ...")` (`:187-193`), and continues into `consume_pending_restore` (`:206`) and `provider.start()` (`:279`).

### 2.3 Claim C — Lifecycle Interleavings (TOCTOU)

- **C.1: Stop during an in-flight Start (`CONFIRMED` — `FACT`):**
  - `FACT` (`backend/app/modules/server/application/commands/start_server.py:119-125,278-388`; `backend/app/modules/server/application/commands/stop_server.py:47-58,74,165-173`; `backend/app/modules/server/domain/aggregate.py:332-350`):
    - `StartServerHandler` commits `ServerStatus.STARTING` at `start_server.py:124` while `server.runtime` is `None` or has `external_id=""` (because `record_runtime_starting` is not called until `:343`, after `provider.start()` finishes at `:279`).
    - A concurrent `StopServerHandler` reads `ServerStatus.STARTING` (`stop_server.py:51`), transitions the DB row to `STOPPING` (`:53`), skips `provider.stop()` because `external_id` is empty (`:74`), and commits `ServerStatus.STOPPED` (`:168`).
    - Meanwhile, `StartServerHandler` completes `provider.start()` (`:279`), calls `server.record_runtime_starting(...)` at `:343` (which mutates `self._runtime` without checking `self._status` at `aggregate.py:332-350`), and spawns `RuntimeSupervisor` (`:377`) for a server whose DB status is `STOPPED` (or transitions it to `RUNNING` in `supervisor.py:259` after the user already received a `stopped` response).
- **C.2: Delete during an in-flight Start (`CONFIRMED` — `FACT`):**
  - `FACT` (`backend/app/modules/server/application/commands/delete_server.py:58-180`; `backend/app/modules/server/application/commands/start_server.py:278-355`):
    - `DeleteServerHandler` runs without any lifecycle lock, reads `STARTING` before `external_id` is recorded, deletes the DB row (`:155`) and `server_dir` (`:174`), while `StartServerHandler` is inside `provider.start()` (`:279`). When `StartServerHandler` reaches `repo.get` at `:342`, `ServerNotFoundError` is raised and the newly started Docker container or JVM process is orphaned on the host.
- **C.3: Delete during `PROVISIONING` (`CONFIRMED` — `FACT`):**
  - `FACT` (`backend/app/modules/server/application/commands/delete_server.py:95-106`; `backend/app/modules/server/application/services/installer_provisioner.py:180-300`; `backend/app/modules/server/application/services/forge_provisioner.py:26-49`; `backend/app/modules/server/application/services/neoforge_provisioner.py:22-45`):
    - `DeleteServerHandler` (`:95`) only checks `if server_status in (ServerStatus.RUNNING, ServerStatus.STARTING):`. When `server_status == ServerStatus.PROVISIONING`, `provision_forge_server` / `provision_neoforge_server` runs an installer JVM subprocess for up to 1800s (`installer_provisioner.py:34,218-235`) in an untracked background task (`_background_tasks: set[asyncio.Task]` at `forge_provisioner.py:26`, not indexed by `server_id`). `DeleteServerHandler` deletes the DB row and `server_dir` while the installer subprocess continues writing files into `server_dir`.

### 2.4 Claim D — Start Timeout Orphans, Supervisor Crash Cleanup, Boot Reconciliation `STOPPING`, and Swallowed `STARTING -> RUNNING` Save

- **D.1: `provider.start()` `TimeoutError` leaves a live container/JVM (`CONFIRMED` — `FACT`):**
  - `FACT` (`backend/app/modules/server/application/commands/start_server.py:278-312`; `backend/app/modules/server/application/commands/restart_server.py:295-328`): When `asyncio.wait_for(self._provider.start(...), timeout=30)` raises `TimeoutError`, the underlying `docker create` + `docker start`, `tmux new-session`, or `subprocess.Popen` may have already spawned the container or process just before cancellation. Both handlers transition the DB row to `STOPPED` (`start_server.py:298`, `restart_server.py:313`) without invoking `provider.stop()` or `provider.destroy()`, leaving a live, untracked container/JVM holding the port and world lock.
- **D.2: Crash handling never stops a still-running container (`CONFIRMED` — `FACT`):**
  - `FACT` (`backend/app/modules/server/application/supervisor.py:449-548,549-611`): When `RuntimeSupervisor._health_check()` encounters repeated `ProviderError`s or an unexpected exception (`:449-506`), or when `_verify_startup()` fails (`:282,307,378`), it invokes `await self._handle_crash(reason=...)` (`:549`). `_handle_crash()` calls `await self._cleanup_os_resources()` (`:577`), which (`supervisor.py:507-548`) **only** runs `tmux has-session -t onx-<sid>` and `tmux kill-session -t onx-<sid>`. It never calls `self._provider.stop(self._handle, ...)` for `DockerProvider` or `LocalWindowsProvider`, marking the server `CRASHED` in the DB (`:593`) while the Docker container or Windows JVM remains running.
- **D.3: Boot reconciliation marks `STOPPING` servers `STOPPED` without asking the provider (`CONFIRMED` — `FACT`):**
  - `FACT` (`backend/app/modules/server/application/reconciliation.py:136-141,274-289`): `reconcile_servers()` queries `status = await provider.status(handle)` at `:136-141` (mapping exceptions to `ServerRuntimeStatus.ERROR`), but the `elif server.status == ServerStatus.STOPPING:` branch at `:274-289` completely ignores `status` and unconditionally executes `server.mark_stopped()` (`:279`) and `await repo.save(server)` (`:280`).
- **D.4: A failed `STARTING -> RUNNING` save is swallowed and never retried (`CONFIRMED` — `FACT`):**
  - `FACT` (`backend/app/modules/server/application/supervisor.py:233-277,316-363,382-448`): In `RuntimeSupervisor._verify_startup()`, both the `if ready:` path (`:233-277`) and the deadline-elapsed `if alive:` path (`:316-363`) wrap `server.mark_running(...)` and `await self._repo_save(server)` in a `try ... except Exception:` block that logs `Failed to transition server ... to RUNNING` (`:271-276`, `:357-362`) and returns from `_verify_startup()` (`:277`, `:363`). `_run()` (`:168-174`) then enters `_health_check()` (`:382-448`), which only checks `verify_process` and updates `self._last_heartbeat` (`:448`)—never retrying the `STARTING -> RUNNING` persistence. The server remains permanently stuck in `STARTING` in the DB while running healthy.

### 2.5 Claim E — Windows Missing Handle PID and Unverified Kill Paths

- **E.1: Windows `stop`/`restart` build a `ServerHandle` without `pid`, so `LocalWindowsProvider.stop` is a silent no-op (`CONFIRMED` — `FACT`):**
  - `FACT` (`backend/app/modules/server/infrastructure/providers/local_windows.py:106,380-393,395-406,459-481`; `backend/app/modules/server/application/commands/start_server.py:339-349`; `backend/app/modules/server/application/commands/stop_server.py:77-82`; `backend/app/modules/server/application/commands/restart_server.py:114-119,356-366`):
    1. `LocalWindowsProvider.start()` (`local_windows.py:380-393`) returns `DeploymentResult` with `metadata={"handle": str(handle), "session_name": session_name, "start_time": start_time, "port": port, "pid": pid, "server_dir": server_dir}`, where `session_name = f"onx-{server_id}"` (`:106`).
    2. `StartServerHandler` (`start_server.py:339-349`) and `RestartServerHandler` (`restart_server.py:356-366`) store `external_id = result.metadata.get("session_name", "")` (`"onx-<server_id>"`, non-numeric) and `pid = result.metadata.get("pid")` on `server.runtime`.
    3. `StopServerHandler` (`stop_server.py:77-82`) and `RestartServerHandler` (`restart_server.py:114-119`) construct `ServerHandle(server_id=..., external_id=server.runtime.external_id, provider_name=..., metadata={"server_name": server_name})` **without `"pid"` in `metadata`**. (The exact same omission exists in `delete_server.py:87-92`, `reconciliation.py:130-134`, `runtime_reconciliation.py:238-244`, `runtime_ownership.py:565-570`, `servers.py:442-446`, and `backup_orchestrator.py:188-192`.)
    4. `LocalWindowsProvider.get_runtime_pid(handle)` (`local_windows.py:473-481`) checks `if handle.metadata and "pid" in handle.metadata:` (`False`) and `if handle.external_id and handle.external_id.isdigit():` (`False` for `"onx-<server_id>"`), returning `None`.
    5. Consequently, `LocalWindowsProvider.stop(handle)` (`local_windows.py:396-406`) receives `pid = None`, logs `"Stop called with no valid PID"`, and returns as a **silent no-op**. Worse, `LocalWindowsProvider.status(handle)` (`local_windows.py:459-465`) also receives `pid = None` and returns `ServerRuntimeStatus.STOPPED` (`:462`), causing `StopServerHandler` (`stop_server.py:113`) to falsely believe the Windows process stopped!
- **E.2: Kill paths verify only `pid` liveness (`PARTIAL` — `FACT` with exact per-call-site breakdown):**
  - **Paths that verify only PID liveness or zero identity (CONFIRMED — `FACT`):**
    1. `backend/app/modules/server/infrastructure/providers/local_windows.py:408,431,441-457`: `LocalWindowsProvider.stop()` checks only `platform_pid_alive(pid)` (`:408,431`) and `_force_kill_process_tree(pid)` (`:441-455`) runs `taskkill /F /T /PID <pid>` directly on `sys.platform == "win32"` without checking `create_time`, command line, or server directory (bypassing `platform_kill_process_tree_async` at `:457`, which is only reached on non-Windows).
    2. `backend/app/modules/server/infrastructure/providers/local.py:398-450`: `LocalLinuxProvider.stop()` sends `os.kill(pid, signal.SIGTERM)` (`:407`) and `os.kill(pid, signal.SIGKILL)` (`:442`) after checking only `_is_pid_alive(pid)`.
    3. `backend/app/modules/server/application/runtime_ownership.py:588-590`: In `claim_localhost()` competing-server displacement, `if spid and _is_pid_alive(spid): killed, reason = _try_kill_process(spid)` sends `SIGTERM`/`SIGKILL` (`_try_kill_process` at `:264-284`) checking only `_is_pid_alive(spid)`.
    4. `backend/app/modules/server/application/runtime_ownership.py:687-700`: In `claim_localhost()` port-occupant fallback, `port_pid = _pid_for_port(requesting_port)` -> `_try_kill_process(port_pid)` kills **whatever OS process is listening on `requesting_port`** with zero ownership, `create_time`, command-line, or working-directory verification.
    5. `backend/app/modules/server/application/runtime_reconciliation.py:595-603,649-655`: When `scope == "system_wide"`, `reconcile_orphans()` bypasses `_is_project_owned_process` (`:533,612`) and executes `os.kill(pid, signal.SIGTERM)` followed by `platform_force_kill(pid)` (`backend/app/core/process_utils.py:73-112`, raw `TerminateProcess` / `SIGKILL` with no identity check). Even when `scope == "project_owned"`, `_is_project_owned_process()` (`runtime_reconciliation.py:140-153`) reads `/proc/{pid}/environ` and `/proc/{pid}/cwd` (Linux-only `/proc`, always returning `False` on Windows) and never verifies `create_time` before killing at `:597,650`.
  - **Paths that perform partial ownership checks (why `PARTIAL` — `FACT`):**
    - `backend/app/modules/server/application/runtime_ownership.py:627-685,751-850` call `verify_ownership(orphan.pid, servers_data_dir=...)` (`backend/app/modules/server/application/ownership_verifier.py:83-142`) when `scope == "project_owned"`. However:
      1. None of the four call sites (`runtime_ownership.py:627,661,755,817`) pass `stored_start_time`, so `stored_start_time` is always `None` and `create_time` is never checked (`ownership_verifier.py:130`).
      2. `ownership_verifier.py:33-66` inspects `/proc/{pid}/environ` and `/proc/{pid}/cwd` only (broken on Windows) and does not verify the command line or specific server directory.
      3. When `cleanup_orphans(scope="system_wide")` is called (`runtime_ownership.py:754,816`), `verify_ownership` is skipped completely.

---

## 3. Proposed Change

### 3.1 Per-Server Multi-Worker DB-Backed Lifecycle Lock

#### 3.1.1 Database Schema (`server_lifecycle_leases`)
Add a dedicated table `server_lifecycle_leases` via Alembic migration `b1e2100000023_add_server_lifecycle_leases.py` (chaining from current head `b1e2100000022` in `backend/app/core/persistence/db_revision.py:30`), following the exact pattern of `server_admission_lease` (`backend/app/modules/versioning/infrastructure/models.py:166-181`, `backend/app/modules/versioning/application/scheduling/admission.py:83-123`):

| Column | Type | Constraints | Purpose |
|--------|------|-------------|---------|
| `server_id` | `String(36)` | `PRIMARY KEY` | Target server UUID being locked |
| `holder` | `String(128)` | `NULLABLE` | Diagnostic descriptor (`"<CommandName>:<worker_pid>"`) |
| `owner_token` | `String(64)` | `NULLABLE` | Per-acquisition UUIDv4 token preventing stale-owner release |
| `acquired_at` | `DateTime(timezone=True)` | `NULLABLE` | UTC timestamp when lease was acquired |
| `expires_at` | `DateTime(timezone=True)` | `NULLABLE` | UTC timestamp after which an unrenewed lease is stealable |
| `updated_at` | `DateTime(timezone=True)` | `NOT NULL` | UTC timestamp of last acquire, heartbeat renewal, or release |

#### 3.1.2 Atomic Acquisition, Heartbeat Renewal, Waiter Policy, and Cancel-Safe Release
Implement `ServerLifecycleLeaseManager` and `ServerLifecycleLockMiddleware` in `backend/app/modules/server/application/lifecycle_lock.py`:

1. **Dialect-aware atomic acquisition (`try_acquire`):**
   - **SQLite (`dialect == "sqlite"`):** Execute `BEGIN IMMEDIATE` on a dedicated short-lived `AsyncSession` (independent of the handler's UoW transaction so lease visibility is immediate across processes), `INSERT OR IGNORE INTO server_lifecycle_leases (server_id, updated_at) VALUES (:sid, :now)`, then `SELECT holder, owner_token, expires_at FROM server_lifecycle_leases WHERE server_id = :sid`.
   - **PostgreSQL / Other (`dialect != "sqlite"`):** Execute `INSERT INTO server_lifecycle_leases (server_id, updated_at) VALUES (:sid, :now) ON CONFLICT (server_id) DO NOTHING`, then `SELECT holder, owner_token, expires_at FROM server_lifecycle_leases WHERE server_id = :sid FOR UPDATE`.
   - **Grant condition:** If `owner_token IS NULL` or `expires_at < now`, update the row with `owner_token = new_token`, `holder = holder`, `acquired_at = now`, `expires_at = now + timedelta(seconds=lease_ttl_seconds)`, `updated_at = now`, commit, and return `LeaseToken(server_id=sid, owner_token=new_token)`. Otherwise commit/rollback and return `None`.
2. **Lease TTL and background renewal (`lease_ttl_seconds = 90.0`, `heartbeat_interval_seconds = 25.0`):**
   - While a lease is held inside the `async with lifecycle_lease.acquire(server_id, holder=..., wait_timeout=...)` context manager, a lightweight background `asyncio.Task` renews `expires_at = now + 90s` every `25s` using `UPDATE server_lifecycle_leases SET expires_at = :new_exp, updated_at = :now WHERE server_id = :sid AND owner_token = :token`.
   - If the worker process crashes (`SIGKILL`, power loss), the lease automatically expires after at most 90s so the server is never permanently wedged.
3. **Waiter policy and timeout:**
   - **Interactive / Command Bus callers (`wait_timeout = 60.0s`):** Poll `try_acquire` with bounded jittered exponential backoff (`0.1s -> 0.25s -> 0.5s` cap, `±20%` jitter) up to `wait_timeout = 60.0s`.
   - **Timeout outcome:** Raise `ServerLifecycleLockTimeoutError(server_id, holder)` in the lease manager; `ServerLifecycleLockMiddleware` catches it and returns `CommandResult(success=False, error="Another lifecycle operation is already in progress for this server", error_code="OPERATION_CONCURRENCY_CONFLICT")`, which maps to HTTP `409 Conflict` (`backend/app/api/errors.py:42`).
   - **Non-blocking background callers (`wait_timeout = 0.0s`):** Reconciliation loops call `try_acquire(..., wait_timeout=0.0)`. If the server is currently locked by an active command, reconciliation logs at `DEBUG`/`INFO` and skips that server for the current pass.
4. **Same-task reentrancy via `contextvars.ContextVar`:**
   - Store `_held_leases: ContextVar[dict[str, str]]` mapping `server_id -> owner_token` in the current async task context.
   - When a command holding the lease for `server_id` dispatches a nested command for the same `server_id` (e.g., `PromoteCommitHandler` sending `StopServerCommand` and `StartServerCommand`, or `DeleteServerHandler` calling `StopServerHandler`), `acquire()` detects the matching `owner_token` in `_held_leases`, verifies the lease row is still owned by `owner_token` (renewing `expires_at`), and yields a reentrant child scope that does **not** release the DB lease on exit.
5. **Safe release on cancel/exception:**
   - In the outer `finally` block, stop the heartbeat task and execute release inside `asyncio.shield(...)` using a fresh DB session:
     ```sql
     UPDATE server_lifecycle_leases
     SET holder = NULL, owner_token = NULL, acquired_at = NULL, expires_at = NULL, updated_at = :now
     WHERE server_id = :sid AND owner_token = :token
     ```
   - Filtering by `AND owner_token = :token` guarantees that if a worker stalled longer than `lease_ttl_seconds` and another worker stole the expired lease, the late worker cannot clear the new owner's lease.

#### 3.1.3 Complete Lifecycle Entry Points Inventory & Lock Policy

Every entry point that reads or mutates server runtime/lifecycle state is classified below:

| # | Entry Point | File & Line | Goes Through Per-Server DB Lock? | Mechanism & Waiter Policy |
|---|-------------|-------------|----------------------------------|---------------------------|
| 1 | `StartServerCommand` / `StartServerHandler` | `backend/app/modules/server/application/commands/start_server.py:51` | **YES** | `ServerLifecycleLockMiddleware` (`wait_timeout=60s`). |
| 2 | `StopServerCommand` / `StopServerHandler` | `backend/app/modules/server/application/commands/stop_server.py:43` | **YES** | `ServerLifecycleLockMiddleware` (`wait_timeout=60s`) + direct lock check in `StopServerHandler.handle()` (reentrant when called inside `DeleteServerHandler` or `PromoteCommitHandler`). |
| 3 | `RestartServerCommand` / `RestartServerHandler` | `backend/app/modules/server/application/commands/restart_server.py:56` | **YES** | `ServerLifecycleLockMiddleware` (`wait_timeout=60s`). |
| 4 | `DeleteServerCommand` / `DeleteServerHandler` | `backend/app/modules/server/application/commands/delete_server.py:53` | **YES** | `ServerLifecycleLockMiddleware` (`wait_timeout=60s`). |
| 5 | `PromoteCommitCommand` / `PromoteCommitHandler` | `backend/app/modules/versioning/application/commands/promote_commit.py:54` | **YES** | `ServerLifecycleLockMiddleware` (`wait_timeout=60s`) holds lease across stop -> stage/swap/rollback -> cleanup -> restart; nested `StopServerCommand` and `StartServerCommand` reuse the lease via `ContextVar` reentrancy. |
| 6 | `RestoreBackupCommand` / `RestoreBackupHandler` | `backend/app/modules/backup/application/commands/restore_backup.py:38` | **YES** | `RestoreBackupCommand` carries `backup_id` (not `server_id`). `RestoreBackupHandler` resolves `backup.server_id` first (`:47-63`), then acquires `lifecycle_lease.acquire(backup.server_id, wait_timeout=60.0)` before reading `server.status`, setting `pending_restore_backup_id`, or transitioning to `RESTORING` and running `perform_safe_restore`. |
| 7 | `consume_pending_restore` | `backend/app/modules/backup/application/restore_service.py:209` | **YES (Inherited)** | Invoked inside `StartServerHandler` (`start_server.py:206`) and `RestartServerHandler` (`restart_server.py:184`) while the caller already holds the per-server DB lease. |
| 8 | `RetryProvisioningCommand` / `RetryProvisioningHandler` | `backend/app/modules/server/application/commands/retry_provisioning.py:27` | **YES** | `ServerLifecycleLockMiddleware` (`wait_timeout=60s`) serializes `PROVISIONING_FAILED -> PROVISIONING` transition and task spawn against concurrent `delete` or `retry_provisioning`. |
| 9 | `CreateServerCommand` & `InstallerProvisioner` (`ForgeProvisioner` / `NeoForgeProvisioner`) | `backend/app/modules/server/application/commands/create_server.py:65`; `installer_provisioner.py:180` | **Hybrid (Registry + Terminal Lock)** | `CreateServerHandler` creates a new `server_id`. `InstallerProvisioner` does **not** hold the mutex for 1800s (which would block `DeleteServerCommand`); instead it registers `(task, subprocess)` in `ProvisioningRegistry` by `server_id` and acquires the per-server DB lock (`wait_timeout=15s`) when committing `finish_provisioning()` / `fail_provisioning()`, aborting if the server was deleted. `DeleteServerHandler` (under the DB lock) cancels and awaits any active provisioner for `server_id` before deleting. |
| 10 | `CreateBackupCommand`, `BackupSaga`, & Scheduled `run_backup_task` | `backend/app/services/backup_orchestrator.py:103`; `backend/app/tasks/definitions/backup_task.py:19` | **NO (Coordinated via `_active_backups`)** | Backups read disk / send RCON `save-off`/`save-on` without changing `ServerStatus`. Holding the lifecycle lock during multi-minute archive compression would block emergency `stop`. Instead, `BackupSaga` registers in `_active_backups`, which `RestartServerHandler` already awaits (`restart_server.py:60-85`). |
| 11 | Isolated Test-Boot Containers (`RunIsolatedTestCommand`, `DockerTestExecutionRunner`, `DiscardTestCommand`) | `backend/app/modules/versioning/application/commands/run_isolated_test.py:42`; `test_runner.py:168` | **NO (Uses `server_admission_lease`)** | Isolated tests boot `onx-test-<test_id>` on an isolated test directory (`test_dir`) gated by the global `server_admission_lease` (`admission.py:233`). They never mutate the production container or `server_dir` until `PromoteCommitCommand` (Entry Point #5, which **does** acquire the per-server lifecycle lock). |
| 12 | `Scheduler` (`run_metrics_collection`, `run_backup_task`) | `backend/app/tasks/scheduler.py:33`; `backend/app/main.py:282-283` | **NO (Read-only / Backup)** | Current scheduled jobs only collect metrics and trigger backups. Any future scheduled power action must dispatch `StartServerCommand`/`StopServerCommand`/`RestartServerCommand` through `CommandBus`, automatically acquiring the DB lock. |
| 13 | Auto-Restart / Crash Recovery (`HandleServerCrashHandler`, `RecoveryOrchestrator`) | `backend/app/modules/health/application/event_handlers/server_crashed_handler.py:20`; `recovery_orchestrator.py:36` | **YES (On Execution)** | `RecoveryOrchestrator.trigger()` only emits `RecoveryTriggeredEvent`. Any recovery subscriber that executes a restart **must** dispatch `StartServerCommand` or `RestartServerCommand` through `CommandBus` (acquiring the DB lock), never calling `provider.start()` directly. |
| 14 | `RuntimeSupervisor` (`_verify_startup`, `_health_check`, `_handle_crash`) | `backend/app/modules/server/application/supervisor.py:204,382,549` | **Coordinated (`try_acquire` / Status Guard)** | The long-running poll loop does not hold the lock across sleeps. Before `_verify_startup` commits `RUNNING`, it checks `not self._stop_event.is_set()` and re-verifies in the UoW that `server.status == ServerStatus.STARTING` and no conflicting command has superseded it. In `_handle_crash`, if `self._stop_event.is_set()` is `True`, it aborts immediately; otherwise it stops any still-running runtime and transitions to `CRASHED` only if `server.status in (ServerStatus.STARTING, ServerStatus.RUNNING)`. |
| 15 | Boot & On-Demand Reconciliation (`reconcile_servers`, `reconcile_all_runtimes`, `FilesystemReconciliationService.reconcile`) | `reconciliation.py:96`; `runtime_reconciliation.py:464`; `filesystem_reconciliation.py:215,917` | **YES (`wait_timeout=0s` try-lock per server)** | Each per-server repair/mutation (`reconcile_servers` per-server body, `reconcile_server_runtime`, and `_handle_delete_missing`) calls `try_acquire(server_id, wait_timeout=0.0)`. If locked by an in-flight command, reconciliation skips that server. |
| 16 | `RuntimeOwnershipRegistry.claim_localhost` competing server displacement | `backend/app/modules/server/application/runtime_ownership.py:550-608` | **YES (`wait_timeout=5s` try-lock on displaced `sid`)** | When `claim_localhost` (called by `StartServerHandler` for server $A$) displaces a competing server $B$ (`sid != requesting_server_id`), it acquires the DB lease for server $B$ (`wait_timeout=5.0s`) before stopping $B$ and marking $B$ `STOPPED` in the DB. If $B$'s lease is held, `claim_localhost` refuses displacement rather than racing with $B$'s in-flight lifecycle operation. |

---

### 3.2 Status Re-Check Inside Lock, Idempotent Start, and Interleaving Prevention

1. **`StartServerHandler` status re-check and idempotent early return (`start_server.py:51-125`):**
   - Remove the pre-status `RuntimeSupervisor.stop_for(sid)` call at `start_server.py:55-61`.
   - Inside the held `server_lifecycle_leases` lock, load `server` from `uow.servers.get(ServerId(sid))` and inspect `server.status`:
     - **`ServerStatus.RUNNING`:** Build `ServerHandle` (including `pid`, `start_time`, `port`, `server_dir` in `metadata`) and check `await self._provider.status(handle)`.
       - If `ServerRuntimeStatus.RUNNING`: ensure an active `RuntimeSupervisor` exists (spawning/re-attaching one if missing in this worker) and return `CommandResult(success=True, data={"server_id": sid, "status": "running", "idempotent": True})`.
       - If `ServerRuntimeStatus.STOPPED` or `ERROR` (stale DB status after an unmonitored exit): stop any stale local supervisor, transition `server` to `STOPPED` (`server.mark_stopped()`), and continue with a fresh start inside the same held lock.
     - **`ServerStatus.STARTING`:** If `server.runtime` has a non-empty `external_id` and `await self._provider.status(handle) == ServerRuntimeStatus.RUNNING`, return `CommandResult(success=True, data={"server_id": sid, "status": "starting", "idempotent": True})`. Otherwise (stale `STARTING` row left by a crashed worker whose lease expired), clean up any partial runtime (`provider.stop(handle, force=True)`), transition `server.mark_stopped()`, and proceed with a clean start.
     - **`ServerStatus.PROVISIONING`, `ServerStatus.RESTORING`, `ServerStatus.STOPPING`:** Return `CommandResult(success=False, error=f"Cannot start server while in '{server.status.value}' state", error_code="SERVER_BUSY")` (HTTP 409).
     - **`ServerStatus.PROVISIONING_FAILED`, `ServerStatus.BROKEN`:** Return `CommandResult(success=False, error=f"Cannot start server in '{server.status.value}' state", error_code="INVALID_SERVER_STATE")` (HTTP 422).
     - **`ServerStatus.STOPPED`, `ServerStatus.CRASHED`:** Stop any stale in-process `RuntimeSupervisor.stop_for(sid)`, transition `server.start()` (`-> STARTING`), commit UoW, and proceed.
2. **Pre-supervisor status verification (`start_server.py:341-377`, `aggregate.py:332-350`):**
   - In `Server.record_runtime_starting()` (`aggregate.py:332-350`), require `self._status == ServerStatus.STARTING` (raising `InvalidValueError` if the status was changed).
   - Because `StartServerHandler` holds the per-server DB lock across `provider.start()` through `record_runtime_starting()` and `RuntimeSupervisor.start()`, no concurrent `StopServerHandler` or `DeleteServerHandler` can mutate the server row in between.
3. **`DeleteServerHandler` during `PROVISIONING` (`delete_server.py:95-106`, `installer_provisioner.py:180-300`):**
   - Add an in-process registry `ProvisioningRegistry` in `installer_provisioner.py` tracking active `asyncio.Task` and `asyncio.subprocess.Process` instances keyed by `server_id`.
   - When `DeleteServerHandler` (under the per-server DB lock) sees `server.status == ServerStatus.PROVISIONING`:
     - Invoke `await ProvisioningRegistry.cancel_and_wait(sid, timeout=15.0)` to cancel the task, terminate the verified installer subprocess tree, and await process exit.
     - Also scan for any OS-level installer process whose working directory is inside `server_dir` (in case provisioning was started by another worker process) and terminate it via verified identity check (`§3.6`). If an active installer process inside `server_dir` cannot be confirmed terminated, abort deletion with `error_code="DELETE_PROVISIONING_ACTIVE"` (HTTP 409) before deleting the DB row or `server_dir`.
   - When `InstallerProvisioner.provision()` finishes or fails, it acquires `lifecycle_lease.acquire(sid, wait_timeout=15.0)`, re-loads `server = await uow.servers.get(ServerId(sid))`, and if `server is None` (already deleted), exits cleanly without saving.

---

### 3.3 Docker Pre-Inspect Policy by Container State & Config Fingerprint

Replace the blind `Conflict -> docker rm -f` block in `DockerProvider.start()` (`backend/app/modules/server/infrastructure/providers/docker.py:474-477`) with a deterministic pre-inspect and config-fingerprint state machine.

#### 3.3.1 Configuration Fingerprint Label (`com.onx-manager.config-fingerprint`)
Compute a deterministic SHA-256 hex digest `_compute_config_fingerprint(...)` over a canonical JSON payload (` json.dumps(payload, sort_keys=True, separators=(",", ":"))`) containing:
- `image`: resolved container image (`eclipse-temurin:<java_version>-jre` or custom image)
- `memory_min_mb`, `memory_max_mb`
- `cpu_cores`, `cpu_affinity`
- `ports`: sorted list of `(host_port, container_port, protocol)` mappings (game port + RCON port + extra ports)
- `mounts`: sorted list of `(source_path, target_path, mode)` bind mounts
- `env`: sorted list of non-ephemeral environment key/values affecting runtime (`EULA`, `JVM_OPTS`, `ONX_MANAGED`)
- `cmd`: resolved container entrypoint/command vector (`java ... -jar ... nogui`)

Attach `--label com.onx-manager.config-fingerprint=<sha256>` alongside existing labels (`com.onx-manager.managed=true`, `com.onx-manager.server_id=<server_id>`, `com.onx-manager.server_name=<name>`) on every `docker create`.

#### 3.3.2 Pre-Inspect State Machine in `DockerProvider.start()`
Before running `docker create`, inspect any existing container matching `onx-<server_id>` (and legacy `mcs-<server_id>`) via `docker inspect --format '{{json .}}' <name>`:

| Existing Container State | Ownership Label (`com.onx-manager.server_id` / `com.mcs-manager.server_id`) | Config Fingerprint (`com.onx-manager.config-fingerprint`) | Required Action |
|--------------------------|-----------------------------------------------------------------------------|-----------------------------------------------------------|-----------------|
| **Does not exist** | N/A | N/A | Proceed with `docker create` + `docker start`. |
| **Any state (`running`, `exited`, `created`, `paused`, etc.)** | **Missing or != `str(server_id)` (Foreign container)** | Any | **REFUSE (Fail Closed):** Raise `ProviderError(f"Refusing to touch foreign container '{container_name}' (owner label mismatch)")`. Never stop or remove. |
| **`running` or `restarting`** | **Matches `str(server_id)` (Ours)** | **Matches desired fingerprint** | **ADOPT:** Do not `rm` or `create`. Inspect container PID and IP, re-initialize `_rcon_Info[server_id]`, verify health/running status, and return `DeploymentResult` with `"adopted": True` in `metadata`. |
| **`running`, `restarting`, or `paused`** | **Matches `str(server_id)` (Ours)** | **Missing or mismatches desired fingerprint** | **FAIL CLOSED on `start`:** Raise `ProviderError(f"Container '{container_name}' is already running with a different or legacy configuration; stop or restart the server first")`. **Never `docker rm -f` a running container.** (In `RestartServerHandler`, the container is stopped and confirmed `exited` via `DockerProvider.stop()` *before* `DockerProvider.start()` is called, so it enters the `exited` row below.) |
| **`exited` or `created`** | **Matches `str(server_id)` (Ours)** | Any | **REMOVE & RECREATE:** Run `docker rm <container_name>` (**without `-f`**). Verify `returncode == 0`, then run `docker create` + `docker start`. |
| **`dead` or removal in progress** | **Matches `str(server_id)` (Ours)** | Any | **BOUNDED RETRY THEN FAIL CLOSED:** Retry `docker rm <container_name>` (no `-f`) with backoff (`0.5s`, `1.0s`, `2.0s`). If removal still fails, raise `ProviderError`. |

If `docker create` still encounters a race condition `Conflict` after pre-inspect (e.g., an external actor created the container millisecond-later), **do not** run `docker rm -f`; re-run the pre-inspect state machine at most once, and if still conflicting, raise `ProviderError`.

---

### 3.4 Precise `stop_confirmed` Contract, Fail-Closed Callers, and Timeout/Crash/Reconcile Fixes

#### 3.4.1 `DockerProvider.stop()` Exit Verification and Timeout Alignment
In `backend/app/modules/server/infrastructure/providers/docker.py:624-644`:
1. **`force=False` path:**
   - Attempt graceful RCON `stop` and `await self._wait_for_container_exit(container_name, timeout=15)` (`:634-638`).
   - If still running, execute `rc, out, err = await self._docker_command("stop", "-t", "30", container_name)`.
   - Verify container exit via `await self._wait_for_container_exit(container_name, timeout=5)`.
   - If the container does not exist (`No such container`), return cleanly. If it is still running after `docker stop -t 30`, raise `ProviderError(f"Container {container_name} still running after docker stop -t 30")`.
2. **`force=True` path:**
   - Execute `rc, out, err = await self._docker_command("kill", container_name)`.
   - If `No such container`, return cleanly.
   - Verify container exit via `await self._wait_for_container_exit(container_name, timeout=10)`.
   - If still running or `rc != 0` (when container exists), raise `ProviderError(f"Container {container_name} did not exit after docker kill: {err or out}")`.
3. **Timeout alignment in `StopServerHandler` and `RestartServerHandler`:**
   - Increase `_GRACEFUL_STOP_TIMEOUT` in `stop_server.py:30` and `restart_server.py:38` from `15` seconds to `50` seconds (covering 15s RCON wait + 30s `docker stop -t 30` + 5s exit check) and `_FORCE_STOP_TIMEOUT` to `15` seconds so the handler never prematurely cancels `DockerProvider.stop(handle, force=False)` at 15s.

#### 3.4.2 The `stop_confirmed` Contract (`stop_server.py`)
Define `is_stop_confirmed(result: CommandResult) -> bool` in `backend/app/modules/server/application/commands/stop_server.py` and enforce the exact invariant:

```python
stop_confirmed = (
    has_runtime_handle                     # server.runtime is not None and bool(server.runtime.external_id)
    and runtime_status_confirmed_stopped   # provider.status(handle) returned ServerRuntimeStatus.STOPPED
    and port_confirmed_free                # _wait_for_port_free(port) returned True (when port > 0)
    and len(provider_errors) == 0          # zero stop/force-stop/status/port errors
    and len(warnings) == 0                 # zero warnings
)
```

1. **No handle -> never confirmed:** If `server.runtime is None` or `not server.runtime.external_id` (and for `local_windows`, `server.runtime.pid is None`), `has_runtime_handle` is `False`, `provider_errors.append("Cannot verify stop: server has no runtime handle")`, and `stop_confirmed` is `False`.
2. **No swallowed status exceptions:** In `stop_server.py:134-135`, replace `except Exception: pass` with `except Exception as exc: provider_errors.append(f"Provider status check failed after stop: {exc}")`.
3. **Status transitions on stop outcome (never call `mark_stopped()` unless `stop_confirmed is True`):**
   - **Case 1 — `stop_confirmed is True`:**
     - Call `server.mark_stopped()` (which transitions `STOPPING -> STOPPED`, clears `external_id`, and emits `ServerStoppedEvent`), commit UoW, and return:
       `CommandResult(success=True, data={"server_id": sid, "status": "stopped", "stop_confirmed": True, "warnings": [], "provider_errors": []})`.
   - **Case 2 — `stop_confirmed is False` and runtime is confirmed still running (`last_status == ServerRuntimeStatus.RUNNING` or `_port_is_listening(stop_port)` is `True`):**
     - Call `server.revert_to_running()` on the aggregate (`STOPPING -> RUNNING`, preserving `server.runtime.external_id`, `pid`, `port`, and `start_time` untouched), commit UoW, re-ensure `RuntimeSupervisor` is active so the running server is not left unmonitored, and return:
       `CommandResult(success=False, error="; ".join(provider_errors), error_code="SERVER_STOP_FAILED", data={"server_id": sid, "status": "running", "stop_confirmed": False, "warnings": provider_errors, "provider_errors": provider_errors})`.
   - **Case 3 — `stop_confirmed is False` and runtime state is unknown (`last_status in (None, ServerRuntimeStatus.ERROR, ServerRuntimeStatus.UNKNOWN)` or missing handle):**
     - Keep `server.status == ServerStatus.STOPPING` (do **not** clear `server.runtime.external_id` or `pid`), record `ServerStopUnknownEvent` (`server.stop_unknown`) via `server.mark_stop_unknown(reason="; ".join(provider_errors))`, commit UoW, and return:
       `CommandResult(success=False, error="; ".join(provider_errors), error_code="SERVER_STOP_UNCONFIRMED", data={"server_id": sid, "status": "stopping", "stop_confirmed": False, "warnings": provider_errors, "provider_errors": provider_errors})`.
   - **Re-entry from `STOPPING`:** Update `StopServerHandler` (`stop_server.py:51`) to accept `ServerStatus.STOPPING` in addition to `RUNNING` and `STARTING`. When already `STOPPING`, skip `server.stop()` (avoiding invalid `STOPPING -> STOPPING` transition) and proceed directly to provider stop and verification using the preserved `server.runtime`.

#### 3.4.3 Fail-Closed Callers (`promote`, `restart`, `start`, `delete`, `restore`)
1. **`PromoteCommitHandler` (`promote_commit.py:181-207`):**
   - Change `:182` to `was_active = server.status in (ServerStatus.RUNNING, ServerStatus.STARTING, ServerStatus.STOPPING)` and `was_running = server.status in (ServerStatus.RUNNING, ServerStatus.STARTING)`.
   - When `was_active` is `True`, capture `stop_result = await self._command_bus.send(StopServerCommand(server_id=server.id))` and evaluate `is_stop_confirmed(stop_result)`.
   - If `not is_stop_confirmed(stop_result)`, **abort immediately before touching any config, `mods`, or `world*` file**, leave the test server intact for retry, and return `CommandResult(success=False, error="Cannot promote: production server could not be confirmed stopped", error_code="PROMOTE_STOP_NOT_CONFIRMED", details={"stop_result": stop_result.data})`.
2. **`RestartServerHandler` (`restart_server.py:92-188`):**
   - Remove the premature `server.mark_stopped()` at `:95` before provider stop (only transition `server.stop()` -> `STOPPING` when currently `RUNNING`/`STARTING`).
   - Run the same verified stop check (`has_runtime_handle`, `provider.status(handle) == STOPPED`, port free, zero `stop_errors`).
   - If `stop_confirmed` is `False`, revert to `RUNNING` (if still running) or leave `STOPPING` (if unknown), and return `CommandResult(success=False, error=..., error_code="RESTART_STOP_FAILED")` **before** `consume_pending_restore` (`:184`), `consume_pending_plugin_deletions` (`:214`), or `server.start()` (`:244`).
   - Only after `stop_confirmed` is `True`: transition `server.mark_stopped()`, and for `DockerProvider` remove the stopped container via non-force `docker rm` so `provider.start()` creates a fresh container with updated settings.
3. **`StartServerHandler` (`start_server.py:179-210`):**
   - If `_port_is_listening(port)` is still `True` after `claim_localhost` (`:179`), **do not continue** into `consume_pending_restore` (`:206`) or `provider.start()` (`:279`). Transition `server.mark_stopped()`, commit UoW, and return `CommandResult(success=False, error=f"Port {port} is still occupied; refusing to start server", error_code="PORT_OCCUPIED")` (HTTP 409).
4. **`DeleteServerHandler` (`delete_server.py:85-180`):**
   - When `server.status in (ServerStatus.RUNNING, ServerStatus.STARTING, ServerStatus.STOPPING)`: invoke `stop_result = await stop_handler.handle(StopServerCommand(server_id=command.server_id, force=True))`.
   - Then invoke `await self._provider.destroy(handle)` (when `handle` exists) and verify via `provider.status(handle)` and `_port_is_listening(port)` that the runtime is actually gone.
   - If the container or process is still running after both `StopServerCommand(force=True)` and `provider.destroy(handle)`, **abort deletion before deleting the DB row or `server_dir`**, returning `CommandResult(success=False, error="Cannot delete server: runtime process/container could not be stopped", error_code="DELETE_STOP_NOT_CONFIRMED")` (HTTP 409).
5. **`RestoreBackupHandler` (`restore_backup.py:71-117`):**
   - Inside the held per-server DB lifecycle lock (`§3.1.3` #6), even if `server.status == ServerStatus.STOPPED`, check whether `server.runtime` has a live process/container or `_port_is_listening(server.port.value)` is `True` for this server. If the server is not genuinely stopped, either defer the restore (`pending_restore_backup_id`) when `defer_if_running` applies or return `CommandResult(success=False, error="Server runtime is still active; cannot perform live disk restore", error_code="RESTORE_SERVER_ACTIVE")` (HTTP 409).

#### 3.4.4 `provider.start()` Timeout Cleanup, Supervisor Crash Stop, `STARTING -> RUNNING` Retry, and Boot Reconciliation `STOPPING`
1. **`provider.start()` `TimeoutError` cleanup (`start_server.py:278-312`, `restart_server.py:295-328`):**
   - When `asyncio.wait_for(self._provider.start(...), timeout=30)` raises `TimeoutError` (or any exception after spawn may have begun):
     - Construct a cleanup `ServerHandle(server_id=ServerId(sid), external_id=f"onx-{sid}", provider_name=self._provider.name, metadata={"server_dir": str(server_dir), "port": port})`.
     - Execute `await self._provider.stop(cleanup_handle, force=True)` and `await self._provider.destroy(cleanup_handle)` inside a shielded cleanup block (`timeout=15s`).
     - Re-check `await self._provider.status(cleanup_handle)` and `_port_is_listening(port)`. Only call `server.mark_stopped()` if the runtime is confirmed not running; if a rogue container/process is still alive after forced cleanup, transition `server.crash(reason="Start timed out and runtime cleanup failed")` so the server is never falsely marked `STOPPED` while running.
2. **`RuntimeSupervisor._handle_crash()` stops still-running containers/processes (`supervisor.py:507-580`):**
   - In `_handle_crash()`, after collecting diagnostics (`_collect_crash_diagnostics`), invoke `await self._stop_runtime_on_crash()` before `_cleanup_os_resources()`:
     - Query `await self._provider.status(self._handle)` (or `self._provider.verify_process(self._handle)`).
     - If the runtime is still `RUNNING` (or status check raises an error), call `await asyncio.wait_for(self._provider.stop(self._handle, force=False), timeout=20.0)`, falling back to `await asyncio.wait_for(self._provider.stop(self._handle, force=True), timeout=10.0)` so Docker containers and Windows/Linux local processes are terminated before marking `CRASHED`.
3. **`RuntimeSupervisor` `STARTING -> RUNNING` save retry and self-heal (`supervisor.py:233-277,316-363,382-448`):**
   - Extract `async def _persist_running_transition(self, ready_reason: str) -> bool` with 3 attempts (`0.5s`, `1.0s`, `2.0s` backoff). Inside the UoW, verify `server.status == ServerStatus.STARTING` before calling `server.mark_running(...)`.
   - Track `self._running_persisted: bool = False` on `RuntimeSupervisor`. If all 3 attempts in `_verify_startup()` fail due to a transient DB lock/error, `_verify_startup()` logs a warning and enters `_health_check()` with `self._running_persisted = False`.
   - On each subsequent healthy tick of `_health_check()` (`supervisor.py:390-448`), if `not self._running_persisted`, call `await self._persist_running_transition("health_check_self_heal")` until it succeeds (or stops if the server is no longer `STARTING`).
4. **Boot reconciliation `STOPPING` verification (`reconciliation.py:274-289`):**
   - In `reconcile_servers()`, replace the unconditional `server.mark_stopped()` in the `elif server.status == ServerStatus.STOPPING:` branch with:
     - If `status == ServerRuntimeStatus.STOPPED` (and `bool(server.runtime and server.runtime.external_id)`): call `server.mark_stopped()` and `await repo.save(server)`.
     - If `status == ServerRuntimeStatus.RUNNING`: call `server.revert_to_running()`, `await repo.save(server)`, and re-attach `RuntimeSupervisor` (`reconciled_running += 1`).
     - If `status in (ServerRuntimeStatus.ERROR, ServerRuntimeStatus.UNKNOWN)` or `not (server.runtime and server.runtime.external_id)`: leave `server.status == ServerStatus.STOPPING` untouched and log a `WARNING` for operator visibility.

---

### 3.5 Promote All-or-Nothing with Rollback and Restart

Redesign Step 4 of `PromoteCommitHandler.handle()` (`backend/app/modules/versioning/application/commands/promote_commit.py:181-252`) so that production file mutations are atomic (all-or-nothing) with full rollback and automatic restart:

1. **Non-destructive staging and backup snapshot before mutation:**
   - Create a sibling transaction staging directory on the same filesystem as `server_dir`:
     `tx_root = server_dir.parent / f".onx-promote-tx-{server.id}-{uuid.uuid4().hex[:8]}"` with subdirectories `tx_root / "backup"` and `tx_root / "staged"`.
   - **Pre-validate and stage all incoming artifacts in `tx_root / "staged"` before touching `server_dir`:**
     - Validate every `cfg_entry.path` in `manifest.configs` is relative and resolves inside `server_dir` (`assert_inside_root`). Render the new content into `tx_root / "staged" / "configs" / cfg_entry.path`.
     - If `(test_dir / "mods").is_dir()`, copy/hardlink `test_dir / "mods"` into `tx_root / "staged" / "mods"` (instead of destructively moving `test_dir / "mods"` via `_atomic_replace_dir`, so `test_dir` remains intact if promote fails).
     - If `command.keep_world_changes` is `True`, for each `world_dir` matching `test_dir.glob("world*")`, copy/hardlink into `tx_root / "staged" / "worlds" / world_dir.name`.
2. **Transactional apply with rollback journal:**
   - Maintain an ordered `applied_journal: list[Callable[[], None]]` of rollback actions:
     - **Configs:** For each `cfg_entry.path`, if `server_dir / cfg_entry.path` exists, copy it (preserving metadata) to `tx_root / "backup" / "configs" / cfg_entry.path`; otherwise record that it did not exist prior to promote. Then atomically replace `server_dir / cfg_entry.path` via `write_text_atomic`. Append a rollback entry that restores the backup file (or unlinks the newly created file).
     - **`mods` directory:** Move existing `server_dir / "mods"` (if present) to `tx_root / "backup" / "mods"`, and `os.replace(tx_root / "staged" / "mods", server_dir / "mods")`. Append a rollback entry that moves `server_dir / "mods"` back out and `os.replace(tx_root / "backup" / "mods", server_dir / "mods")`.
     - **`world*` directories (when `keep_world_changes=True`):** For each staged `world_name`, move existing `server_dir / world_name` (if present) to `tx_root / "backup" / "worlds" / world_name`, and `os.replace(tx_root / "staged" / "worlds" / world_name, server_dir / world_name)`. Append a rollback entry that restores `tx_root / "backup" / "worlds" / world_name`.
3. **Failure rollback and automatic restart:**
   - If any exception occurs during staging or apply:
     - Execute `applied_journal` in **reverse order** (`reversed(applied_journal)`), restoring every modified config file, `mods`, and `world*` directory from `tx_root / "backup"` to a byte-identical pre-promote state.
     - Remove `tx_root` (only if all rollback steps succeeded; if a rollback step itself fails, preserve `tx_root / "backup"` on disk and log its path at `CRITICAL`).
     - Do **not** clean up `test_server` (so the user's isolated test environment is preserved).
     - If `was_running` is `True` and rollback succeeded, send `StartServerCommand(server_id=server.id)` (reusing the held per-server lifecycle lease) so the production server is brought back online on its original pre-promote state.
     - Return `CommandResult(success=False, error=f"Promote failed and was rolled back: {exc}", error_code="PROMOTE_SWAP_ROLLED_BACK", details={"rolled_back": rollback_ok, "restart_attempted": was_running, "restart_ok": restart_ok})`.
4. **Success commit and restart reporting:**
   - Once all config, `mods`, and `world*` swaps succeed:
     - Remove `tx_root` (`shutil.rmtree(tx_root, ignore_errors=True)`).
     - Run `await self._test_runner.cleanup_test(test_server, ...)` and mark `test_server` promoted in the DB (`promote_commit.py:210-231`).
     - If `was_running` is `True`, execute `start_res = await self._command_bus.send(StartServerCommand(server_id=server.id))` and include `"restart_attempted": True`, `"restart_ok": start_res.success`, `"restart_error_code": start_res.error_code`, `"restart_error": start_res.error` in `CommandResult.details`.

---

### 3.6 Windows Handle PID Propagation & Cross-Platform Process Identity Verification

#### 3.6.1 Canonical `ServerHandle` Construction Helper (`build_server_handle`)
Add a single canonical helper `build_server_handle(server: Server, provider_name: str, server_dir: Path | str | None = None) -> ServerHandle` on `Server` (or `backend/app/modules/server/domain/value_objects.py`) and use it at **every** `ServerHandle` construction site (`stop_server.py:77-82`, `restart_server.py:114-119`, `start_server.py:51`, `delete_server.py:87-92`, `reconciliation.py:130-134`, `runtime_reconciliation.py:238-244`, `runtime_ownership.py:565-570`, `servers.py:442-446`, `backup_orchestrator.py:188-192`):

```python
metadata = {
    "server_name": str(server.name),
    "pid": server.runtime.pid if server.runtime else None,
    "start_time": server.runtime.start_time if server.runtime else None,
    "port": (server.runtime.port if server.runtime and server.runtime.port else server.port.value),
    "server_dir": str(server_dir) if server_dir else None,
}
```

Additionally, in `LocalWindowsProvider.start()` (`backend/app/modules/server/infrastructure/providers/local_windows.py:235,380-393`):
- Record `start_time = int(psutil.Process(pid).create_time())` (falling back to `int(time.time())` if `psutil` raises `NoSuchProcess`/`AccessDenied`) so `server.runtime.start_time` matches `psutil.Process(pid).create_time()` within `<= 2.0s` on Windows.
- In `LocalWindowsProvider.get_runtime_pid(handle)` (`local_windows.py:473-481`), check `handle.metadata.get("pid")` (converting `int` if truthy) first, and fall back to `handle.external_id.isdigit()`.

#### 3.6.2 Cross-Platform Process Identity Verifier (`verify_process_identity`)
Implement `verify_process_identity` in `backend/app/core/process_utils.py` and wire `backend/app/modules/server/application/ownership_verifier.py` to use `psutil.Process(pid)` on both Windows and Linux (with `/proc/{pid}` fallback on POSIX):

```python
@dataclass(frozen=True)
class ProcessIdentityCheck:
    verified: bool
    reason: str
    create_time: float | None = None
    cmdline: tuple[str, ...] = ()
    cwd: str | None = None
```

`verify_process_identity(pid, *, expected_create_time=None, expected_server_dir=None, servers_data_dir=None, allow_wrapper_shell=False) -> ProcessIdentityCheck` enforces **all three checks** before any signal or `taskkill`:

1. **Create-time check (`create_time`):**
   - Read `proc.create_time()` via `psutil.Process(pid)`.
   - If `expected_create_time is not None` and `expected_create_time > 0`: require `abs(proc.create_time() - float(expected_create_time)) <= 5.0` (5-second tolerance to account for integer truncation between `time.time()` and `psutil.Process.create_time()`). If it differs by more than `5.0s`, return `ProcessIdentityCheck(verified=False, reason="create_time_mismatch")` (PID reuse!).
2. **Command-line check (`cmdline`):**
   - Read `proc.cmdline()`. Require that the command line matches either a Java/Minecraft server invocation (`java`/`javaw` + `.jar`/`@libraries`/`net.minecraft`/`cpw.mods`/`neoforged`/`fabric-server`) or, when `allow_wrapper_shell=True`, the known ONX wrapper script (`run.bat`, `run.sh`, `start.sh`, `user_jvm_args.txt`) or child tree containing a verified Java process. Never match arbitrary system processes (e.g., `postgres`, `python`, `nginx`, `explorer.exe`).
3. **Server directory / environment check (`cwd` / path / `ONX_MANAGED=1`):**
   - Read `proc.cwd()` (via `psutil.Process(pid).cwd()`, with `/proc/{pid}/cwd` fallback on Linux) and `proc.environ()` (when accessible).
   - When `expected_server_dir` is provided: require that `Path(proc.cwd()).resolve()` is equal to or inside `Path(expected_server_dir).resolve()`, **or** one of the command-line paths resolves inside `expected_server_dir`, **or** `proc.environ().get("ONX_MANAGED") == "1"` with matching `ONX_SERVER_ID`.
   - When scanning orphans across all servers (`servers_data_dir` provided, `expected_server_dir=None`): require that `cwd` or a command-line path resolves inside `Path(servers_data_dir).resolve()` or `proc.environ().get("ONX_MANAGED") == "1"`.

#### 3.6.3 Mandatory Identity Check at Every Kill / Signal Site
1. **`LocalWindowsProvider.stop()` and `_force_kill_process_tree()` (`local_windows.py:395-457`):**
   - Before sending graceful `"stop\n"` / `terminate()` (`:410-436`) and before running `taskkill /F /T /PID <pid>` (`:441-457`), call `verify_process_identity(pid, expected_create_time=handle.metadata.get("start_time"), expected_server_dir=handle.metadata.get("server_dir"), allow_wrapper_shell=True)`.
   - If `not check.verified`:
     - If the process does not exist (`reason == "no_such_process"`), treat as already exited.
     - If the PID belongs to an unrelated process (`create_time_mismatch`, `cmdline_mismatch`, `server_dir_mismatch`), log `WARNING` and **do not call `terminate()` or `taskkill`**; if `create_time_mismatch` proves the original server PID exited and was reused by an unrelated process, treat the original server PID as exited, otherwise raise `ProviderError(f"Refusing to kill unverified PID {pid}: {check.reason}")`.
2. **`LocalLinuxProvider.stop()` (`local.py:398-450`):**
   - Before `os.kill(pid, signal.SIGTERM)` (`:407`) and `os.kill(pid, signal.SIGKILL)` (`:442`), call `verify_process_identity(pid, expected_create_time=handle.metadata.get("start_time"), expected_server_dir=handle.metadata.get("server_dir"), allow_wrapper_shell=True)`. Refuse to signal on identity mismatch.
3. **`RuntimeOwnershipRegistry` (`runtime_ownership.py:264-284,588-590,627-685,687-700,751-850`):**
   - Pass `stored_start_time=rec.start_time` and `expected_server_dir=server_dir` at all `verify_ownership` call sites (`:588,627,661,755,817`).
   - At `:588-590` (competing server displacement), verify identity of `spid` with `expected_create_time=srec.start_time` and `expected_server_dir` before calling `_try_kill_process(spid)`.
   - At `:687-700` (port-occupant fallback), **never** blindly kill `port_pid = _pid_for_port(requesting_port)`. Call `verify_process_identity(port_pid, servers_data_dir=self._servers_data_dir)`. If `not check.verified` (e.g., an external non-ONX process is listening on `requesting_port`), **refuse to kill `port_pid`** and leave the port occupied so `StartServerHandler` fails closed with `PORT_OCCUPIED` (`§3.4.3`).
   - Even when `cleanup_orphans(scope="system_wide")` is invoked (`:754,816`), still require `verify_process_identity` to confirm `_is_minecraft_cmdline` and `servers_data_dir` containment before sending `SIGTERM`/`SIGKILL`.
4. **`runtime_reconciliation.py` (`reconcile_orphans` at `:530-660`):**
   - Replace Linux-only `/proc` reads in `_is_project_owned_process` (`:140-153`) with cross-platform `verify_process_identity(pid, servers_data_dir=servers_data_dir)`.
   - Re-verify `verify_process_identity(pid, expected_create_time=proc_info.create_time, servers_data_dir=servers_data_dir)` immediately before `os.kill(pid, signal.SIGTERM)` (`:597`) and before `platform_force_kill(pid)` (`:650`).

---

## 4. Affected Components

| Component / Layer | File Path | Nature of Change |
|-------------------|-----------|------------------|
| **Alembic Migration** | `backend/alembic/versions/b1e2100000023_add_server_lifecycle_leases.py` *(new)* | Create `server_lifecycle_leases` table (`server_id` PK, `holder`, `owner_token`, `acquired_at`, `expires_at`, `updated_at`). |
| **DB Revision Constant** | `backend/app/core/persistence/db_revision.py` | Update `EXPECTED_ALEMBIC_HEAD` to `"b1e2100000023"`. |
| **Server Infrastructure Models** | `backend/app/modules/server/infrastructure/models.py` | Add `ServerLifecycleLeaseModel` ORM mapping for `server_lifecycle_leases`. |
| **Lifecycle Lease & Middleware** | `backend/app/modules/server/application/lifecycle_lock.py` *(new)* | `ServerLifecycleLeaseManager` (atomic DB acquire, heartbeat renewal, jittered waiter polling, `ContextVar` reentrancy, shielded owner-token release) + `ServerLifecycleLockMiddleware`. |
| **DI & Command Bus Registration** | `backend/app/registration.py` | Register `ServerLifecycleLeaseManager` singleton and wire `ServerLifecycleLockMiddleware` into `CommandBus`. |
| **Server Aggregate & Events** | `backend/app/modules/server/domain/aggregate.py`, `backend/app/modules/server/domain/events.py`, `backend/app/modules/server/domain/value_objects.py` | Add `Server.revert_to_running()`, `Server.mark_stop_unknown()`, `ServerStopUnknownEvent`, `record_runtime_starting` status guard, and `build_server_handle()` helper. |
| **Start Server Handler** | `backend/app/modules/server/application/commands/start_server.py` | Status re-check inside DB lock; idempotent early return for `RUNNING`/`STARTING`; fail-closed on occupied port; cleanup container/process on `provider.start()` `TimeoutError`; populate full `ServerHandle` metadata. |
| **Stop Server Handler** | `backend/app/modules/server/application/commands/stop_server.py` | Enforce `stop_confirmed` contract (`is_stop_confirmed`); align timeout with Docker stop (`50s`); never call `mark_stopped()` on unconfirmed stop; transition to `RUNNING` or `STOPPING`; accept `STOPPING` on re-entry; populate `ServerHandle` metadata. |
| **Restart Server Handler** | `backend/app/modules/server/application/commands/restart_server.py` | Remove premature `mark_stopped()`; gate `consume_pending_restore`, plugin deletion, and `server.start()` on confirmed stop; clean up on `provider.start()` timeout; populate `ServerHandle` metadata. |
| **Delete Server Handler & Provisioners** | `backend/app/modules/server/application/commands/delete_server.py`, `backend/app/modules/server/application/services/installer_provisioner.py`, `forge_provisioner.py`, `neoforge_provisioner.py`, `retry_provisioning.py` | Add `ProvisioningRegistry` per `server_id`; cancel/await provisioner on delete during `PROVISIONING`; acquire DB lock on provisioning completion; fail-closed delete if runtime stop/destroy is unconfirmed. |
| **Docker Provider** | `backend/app/modules/server/infrastructure/providers/docker.py` | Add `com.onx-manager.config-fingerprint` label; replace blind `docker rm -f` with pre-inspect state machine (foreign -> refuse, running+match -> adopt, running+mismatch -> fail closed, exited/created -> non-force `docker rm`); verify container exit in `DockerProvider.stop()`. |
| **Promote Commit Handler** | `backend/app/modules/versioning/application/commands/promote_commit.py` | Include `STOPPING` in active check; gate promote on `is_stop_confirmed(stop_result)`; implement staging + backup journal with full rollback on config/`mods`/`world*` error and automatic restart. |
| **Backup Restore Handler & Service** | `backend/app/modules/backup/application/commands/restore_backup.py`, `backend/app/modules/backup/application/restore_service.py` | Acquire per-server DB lifecycle lock for `backup.server_id` in `RestoreBackupHandler`; verify runtime/port idle before live disk restore. |
| **Runtime Supervisor** | `backend/app/modules/server/application/supervisor.py` | Stop still-running runtime via `self._provider.stop()` in `_handle_crash()` for all providers; retry `STARTING -> RUNNING` DB save with backoff and self-heal in `_health_check()`. |
| **Reconciliation Services** | `backend/app/modules/server/application/reconciliation.py`, `runtime_reconciliation.py`, `services/filesystem_reconciliation.py` | Check `provider.status(handle)` for `STOPPING` servers on boot; use non-blocking `try_acquire(wait_timeout=0)` per server; use cross-platform `verify_process_identity` before orphan kills. |
| **Windows & Linux Local Providers & Process Identity** | `backend/app/modules/server/infrastructure/providers/local_windows.py`, `local.py`, `backend/app/core/process_utils.py`, `backend/app/modules/server/application/ownership_verifier.py`, `runtime_ownership.py` | Fix Windows `ServerHandle` `pid`/`start_time` propagation; implement cross-platform `verify_process_identity` (`create_time` + `cmdline` + `server_dir`); enforce before every `os.kill`, `TerminateProcess`, and `taskkill`. |

---

## 5. Interfaces & Contracts

### 5.1 `ServerLifecycleLeaseManager` & `ServerLifecycleLockMiddleware` (`lifecycle_lock.py`)

```python
@dataclass(frozen=True)
class LeaseToken:
    server_id: str
    owner_token: str
    holder: str
    reentrant: bool = False


class ServerLifecycleLockTimeoutError(Exception):
    def __init__(self, server_id: str, holder: str | None = None) -> None:
        self.server_id = server_id
        self.holder = holder
        super().__init__(f"Timed out waiting for lifecycle lease on server {server_id}")


class ServerLifecycleLeaseManager:
    DEFAULT_TTL_SECONDS: float = 90.0
    DEFAULT_WAIT_TIMEOUT_SECONDS: float = 60.0
    HEARTBEAT_INTERVAL_SECONDS: float = 25.0

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None: ...

    async def try_acquire(
        self,
        server_id: str,
        *,
        holder: str,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ) -> LeaseToken | None:
        """Atomically acquire an unheld or expired lease row for `server_id`."""

    async def release(self, token: LeaseToken) -> bool:
        """Release lease row iff `server_id` and `owner_token` match (no-op if `token.reentrant`)."""

    @asynccontextmanager
    async def acquire(
        self,
        server_id: str,
        *,
        holder: str,
        wait_timeout: float = DEFAULT_WAIT_TIMEOUT_SECONDS,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ) -> AsyncIterator[LeaseToken]:
        """Acquire per-server lease with jittered polling, ContextVar reentrancy, and heartbeat renewal."""
```

Commands automatically locked by `ServerLifecycleLockMiddleware`:
- `StartServerCommand`, `StopServerCommand`, `RestartServerCommand`, `DeleteServerCommand`, `PromoteCommitCommand`, `RetryProvisioningCommand` (all carry `.server_id: str`).
- `RestoreBackupCommand` acquires `lease_manager.acquire(backup.server_id, holder="RestoreBackupCommand", wait_timeout=60.0)` inside `RestoreBackupHandler.handle()` immediately after resolving `backup`.

### 5.2 `stop_confirmed` Helper & Payload Contract (`stop_server.py`)

```python
def is_stop_confirmed(result: CommandResult | None) -> bool:
    """Return True iff StopServerCommand succeeded with verified runtime & port stop and zero warnings/errors."""
    if result is None or not result.success or not isinstance(result.data, dict):
        return False
    return (
        result.data.get("stop_confirmed") is True
        and not result.data.get("warnings")
        and not result.data.get("provider_errors")
    )
```

`StopServerCommand` `CommandResult.data` schema:
```python
{
    "server_id": str,
    "status": Literal["stopped", "running", "stopping"],
    "stop_confirmed": bool,
    "runtime_verified": bool,
    "port_verified": bool,
    "warnings": list[str],
    "provider_errors": list[str],
}
```

### 5.3 Error Codes & HTTP Status Mapping (`backend/app/api/errors.py`)

| `error_code` | HTTP Status | Trigger Condition |
|--------------|-------------|-------------------|
| `OPERATION_CONCURRENCY_CONFLICT` | `409 Conflict` | Per-server DB lifecycle lease wait timeout (`60s`) exceeded. |
| `SERVER_BUSY` | `409 Conflict` | `start` requested while server is `PROVISIONING`, `RESTORING`, or `STOPPING`. |
| `PORT_OCCUPIED` | `409 Conflict` | Game port remains listening after `claim_localhost` during `start`. |
| `SERVER_STOP_FAILED` | `409 Conflict` | `stop` failed and runtime is confirmed still `RUNNING` (reverted to `RUNNING`). |
| `SERVER_STOP_UNCONFIRMED` | `409 Conflict` | `stop` could not verify runtime exit (no handle or provider `ERROR`; remains `STOPPING`). |
| `RESTART_STOP_FAILED` | `409 Conflict` | `restart` stop phase failed or was unconfirmed; start phase aborted. |
| `PROMOTE_STOP_NOT_CONFIRMED` | `409 Conflict` | `promote` aborted before file swap because `is_stop_confirmed(stop_result)` is `False`. |
| `PROMOTE_SWAP_ROLLED_BACK` | `500 Internal Server Error` | `promote` file/dir swap failed; production directory rolled back to pre-promote state. |
| `DELETE_STOP_NOT_CONFIRMED` | `409 Conflict` | `delete` could not confirm runtime/provisioner termination; DB row and files preserved. |
| `RESTORE_SERVER_ACTIVE` | `409 Conflict` | Immediate backup restore requested while server runtime/port is still active. |

### 5.4 Process Identity Verification Contract (`backend/app/core/process_utils.py`)

```python
def verify_process_identity(
    pid: int,
    *,
    expected_create_time: int | float | None = None,
    expected_server_dir: str | Path | None = None,
    servers_data_dir: str | Path | None = None,
    allow_wrapper_shell: bool = False,
    create_time_tolerance_seconds: float = 5.0,
) -> ProcessIdentityCheck:
    """Verify (1) process create_time, (2) Java/Minecraft/wrapper cmdline, and (3) server_dir/ONX_MANAGED before any kill."""
```

---

## 6. Failure & Edge Cases

1. **Worker process crashes (`SIGKILL` / OOM) while holding `server_lifecycle_leases`:**
   - The lease row's `expires_at` (`acquired_at + 90s`, renewed every `25s` while alive) lapses within at most 90 seconds. The next command on any worker atomically steals the expired lease row (`expires_at < now`), re-reads the server's DB and provider state inside the lock, and recovers cleanly.
2. **Stalled worker wakes up after its lease expired and was stolen by Worker B:**
   - Worker A's `release()` executes `WHERE server_id = :sid AND owner_token = :token_A`. Because Worker B overwrote `owner_token = :token_B`, Worker A's `UPDATE` affects 0 rows and Worker B's lease remains intact.
3. **Nested commands (`PromoteCommitHandler` -> `StopServerCommand` / `StartServerCommand`):**
   - `ContextVar` reentrancy detects that the current task already holds `owner_token` for `server_id`, renews `expires_at`, and runs the nested handler without self-deadlock or premature release.
4. **Stop called on a `STARTING` server before `provider.start()` finishes:**
   - Because `StartServerHandler` holds the per-server DB lease across the entire startup sequence (`STARTING` commit -> `provider.start()` -> `record_runtime_starting()` -> `RuntimeSupervisor.start()`), a concurrent `StopServerCommand` queues on the DB lease until `StartServerHandler` has recorded `external_id` and `pid`, then stops the runtime cleanly with a valid `ServerHandle`.
5. **PID reuse on Windows or Linux after a server crashes:**
   - If server PID `1234` (started at `t = 1700000000`) crashes and the OS assigns PID `1234` to an unrelated process at `t = 1700000600`, `verify_process_identity` detects `abs(create_time - 1700000000) > 5.0` (as well as `cmdline` and `cwd` mismatch), refuses to signal or `taskkill` PID `1234`, and treats the original server process as already exited.
6. **External non-ONX service occupying the configured server port:**
   - During `StartServerHandler`, `claim_localhost` runs `verify_process_identity` on the port occupant PID (`_pid_for_port(port)`), sees that it is not an ONX-managed Minecraft process, refuses to kill it, and `StartServerHandler` aborts with `error_code="PORT_OCCUPIED"` before `consume_pending_restore` or `provider.start()`.
7. **Disk full (`ENOSPC`) or permission error midway through `PromoteCommitHandler` swap:**
   - `PromoteCommitHandler` catches the error, executes `applied_journal` in reverse order to restore all already-written configs and `os.replace` `tx_root / "backup" / "mods"` and `world*` back into `server_dir`, preserves `test_dir`, and if `was_running` is `True`, dispatches `StartServerCommand` so the production server resumes on its uncorrupted pre-promote state.

---

## 7. Tests & Verification

All verification runs via pytest (`PYTHONPATH=backend poetry run pytest ...`).

1. **Multi-Worker DB Lease & Reentrancy Tests (`backend/tests/application/test_lifecycle_lock.py`):**
   - Concurrent `acquire(server_id)` calls across separate DB sessions serialize in FIFO/polling order; second caller blocks until first releases.
   - Expired lease (`expires_at < now`) is atomically stolen by the next caller; late `release()` by the stale owner token is a no-op and does not release the new owner's lease.
   - Acquisition timeout returns `CommandResult(success=False, error_code="OPERATION_CONCURRENCY_CONFLICT")`.
   - Same-task reentrancy (`PromoteCommitHandler` -> `StopServerCommand` -> `StartServerCommand`) succeeds without deadlock and releases the lease only when the outer scope exits.
   - Task cancellation (`asyncio.CancelledError`) and unhandled exceptions inside the handler always release the lease row.
2. **Idempotent Start, Port Guard, Timeout Cleanup, & Delete Interleaving Tests (`backend/tests/application/test_server_commands.py`):**
   - Calling `StartServerHandler` when `server.status == RUNNING` and `provider.status() == RUNNING` returns `success=True, data["idempotent"]=True` without calling `RuntimeSupervisor.stop_for` or `provider.start`.
   - Calling `StartServerHandler` when `_port_is_listening(port)` remains `True` after `claim_localhost` aborts with `PORT_OCCUPIED` before `consume_pending_restore` or `provider.start`.
   - `provider.start()` raising `TimeoutError` in `StartServerHandler` and `RestartServerHandler` invokes `provider.stop(cleanup_handle, force=True)` and `provider.destroy(cleanup_handle)`.
   - `DeleteServerHandler` during `PROVISIONING` cancels the registered provisioner task/process before deleting; `DeleteServerHandler` aborts with `DELETE_STOP_NOT_CONFIRMED` if the runtime remains running after stop + destroy.
3. **Docker Pre-Inspect, Config Fingerprint, & Stop Exit Confirmation Tests (`backend/tests/infrastructure/test_docker_provider.py`):**
   - Existing `running` container with foreign/missing `com.onx-manager.server_id` label -> raises `ProviderError`, never calls `docker rm` or `docker stop`.
   - Existing `running` container with matching `server_id` and matching `com.onx-manager.config-fingerprint` -> adopted without `docker create` or `docker rm`.
   - Existing `running` container with matching `server_id` and mismatched/missing fingerprint -> raises `ProviderError` on `start`, never runs `docker rm -f`.
   - Existing `exited` or `created` container with matching `server_id` -> runs `docker rm <name>` (without `-f`), then `docker create` + `docker start`.
   - `DockerProvider.stop(force=False)` and `DockerProvider.stop(force=True)` call `_wait_for_container_exit` and raise `ProviderError` if the container remains running.
4. **Fail-Closed `stop_confirmed`, Supervisor Crash Stop, `STARTING -> RUNNING` Retry, & Boot Reconciliation Tests (`backend/tests/application/test_stop_confirmation_and_supervisor.py`):**
   - `StopServerHandler` with `provider.status() == RUNNING` transitions `STOPPING -> RUNNING` (`revert_to_running`), preserves `external_id`/`pid`, and returns `success=False, error_code="SERVER_STOP_FAILED"`.
   - `StopServerHandler` with missing handle or `provider.status()` raising `ProviderError` leaves status `STOPPING`, emits `ServerStopUnknownEvent`, and returns `success=False, error_code="SERVER_STOP_UNCONFIRMED"`.
   - `RestartServerHandler` aborts before `consume_pending_restore` and `server.start()` when stop is not confirmed.
   - `RuntimeSupervisor._handle_crash()` invokes `provider.stop()` when a Docker or Windows runtime is still running at crash time.
   - `RuntimeSupervisor._verify_startup()` retries a failed `STARTING -> RUNNING` save and `_health_check()` self-heals the transition if startup retries exhausted.
   - `reconcile_servers()` checks `provider.status(handle)` for `STOPPING` servers: `RUNNING -> RUNNING`, `STOPPED -> STOPPED`, `ERROR -> STOPPING`.
5. **Promote All-or-Nothing Rollback & Restart Tests (`backend/tests/modules/versioning/test_promote_commit_atomicity.py`):**
   - `PromoteCommitHandler` aborts with `PROMOTE_STOP_NOT_CONFIRMED` before writing any config or swapping `mods`/`world*` when `StopServerCommand` fails or returns warnings.
   - Simulated failure on the 2nd of 3 config writes, or during `mods` swap, or during `world_nether` swap rolls back all earlier config writes and directory swaps so `server_dir` is byte-identical to pre-promote state, preserves `test_dir`, and restarts the server when `was_running=True`.
6. **Windows Handle PID & Process Identity Verification Tests (`backend/tests/infrastructure/test_local_windows_and_process_identity.py`):**
   - `StopServerHandler` and `RestartServerHandler` pass `metadata["pid"]`, `metadata["start_time"]`, and `metadata["server_dir"]` in `ServerHandle`; `LocalWindowsProvider.stop()` and `status()` resolve the PID and terminate the process.
   - `verify_process_identity` rejects PIDs with mismatched `create_time`, non-Java/Minecraft `cmdline`, or `cwd` outside `expected_server_dir`/`servers_data_dir`.
   - `LocalWindowsProvider._force_kill_process_tree`, `LocalLinuxProvider.stop`, `runtime_ownership.py` (`claim_localhost` displacement, port-occupant check, `cleanup_orphans`), and `runtime_reconciliation.py` (`reconcile_orphans`) refuse to kill unverified PIDs.

---

## 8. Out of Scope

- Distributed lock backends requiring external infrastructure not already in the stack (e.g., Redis/Redlock or etcd); the database-backed `server_lifecycle_leases` table covers both SQLite and PostgreSQL deployments.
- Multi-host cluster scheduling across separate physical machines (all workers manage the same host/Docker daemon or shared database).
- Refactoring dead legacy saga classes (`DeploymentSaga`, `RestartSaga` in `backend/app/services/server_orchestrator.py`) that are not wired into production routers or `registration.py`.
- Changing isolated test-server admission capacity rules (`server_admission_lease` in `backend/app/modules/versioning/application/scheduling/admission.py`).

---

## 9. BUILD SPLIT

> **Prerequisite — Dirty Working-Tree Check:** Before running any builder batch, note that `backend/app/modules/server/infrastructure/providers/docker.py`, `backend/app/modules/server/application/commands/delete_server.py`, `backend/app/modules/server/application/services/filesystem_reconciliation.py`, `backend/app/api/v1/routers/files.py`, `backend/app/core/exceptions.py`, `backend/app/modules/server/infrastructure/fs.py`, `backend/app/modules/versioning/application/commands/remove_materialization.py`, `backend/app/modules/versioning/domain/entities.py`, and `backend/tests/application/test_server_commands.py` / `backend/tests/infrastructure/test_docker_provider.py` currently have uncommitted FX-1 containment edits in the working tree. Resolve or commit the FX-1 changes first, or apply each batch cleanly on top of them without reverting FX-1 lines.

The implementation is split into **4 batches** ordered by risk (highest-risk concurrency lock, idempotent start, and Docker destructive conflict first), each sized for a single builder job under 25 minutes:

### Batch 1 — DB-Backed Lifecycle Lease, Idempotent Start, and Docker Container Pre-Inspect & Adoption (Highest Risk)
- **Touches Windows-only code:** **No**
- **Scope:**
  1. Create Alembic migration `b1e2100000023_add_server_lifecycle_leases.py`, update `EXPECTED_ALEMBIC_HEAD` in `db_revision.py`, and add `ServerLifecycleLeaseModel` in `server/infrastructure/models.py`.
  2. Implement `ServerLifecycleLeaseManager` and `ServerLifecycleLockMiddleware` in `backend/app/modules/server/application/lifecycle_lock.py` (atomic DB acquisition for SQLite/Postgres, `90s` TTL with `25s` heartbeat renewal, `60s` jittered waiter polling, `ContextVar` reentrancy, shielded owner-token release) and wire into `backend/app/registration.py` and `backend/app/api/errors.py`.
  3. Add `build_server_handle()` helper and `record_runtime_starting` status guard in `backend/app/modules/server/domain/aggregate.py` / `value_objects.py`.
  4. Update `StartServerHandler` (`start_server.py`) for status re-check inside the lock, idempotent early return on `RUNNING`/`STARTING`, fail-closed port-occupied check (`PORT_OCCUPIED`), and `provider.start()` `TimeoutError` container/process cleanup.
  5. Replace blind `docker rm -f` in `DockerProvider.start()` (`docker.py`) with config-fingerprint label (`com.onx-manager.config-fingerprint`) and pre-inspect state machine (foreign -> refuse, running+match -> adopt, running+mismatch -> fail closed, exited/created -> non-force `docker rm`).
- **Exact Files:**
  - `backend/alembic/versions/b1e2100000023_add_server_lifecycle_leases.py` *(new)*
  - `backend/app/core/persistence/db_revision.py`
  - `backend/app/modules/server/infrastructure/models.py`
  - `backend/app/modules/server/application/lifecycle_lock.py` *(new)*
  - `backend/app/registration.py`
  - `backend/app/api/errors.py`
  - `backend/app/modules/server/domain/aggregate.py`
  - `backend/app/modules/server/domain/value_objects.py`
  - `backend/app/modules/server/application/commands/start_server.py`
  - `backend/app/modules/server/infrastructure/providers/docker.py`
- **Tests to Add / Update:**
  - `backend/tests/application/test_lifecycle_lock.py` *(new)*: multi-session serialization, TTL expiry & steal, stale-token release safety, waiter timeout (`OPERATION_CONCURRENCY_CONFLICT`), `ContextVar` reentrancy, cancel/exception release.
  - `backend/tests/application/test_server_commands.py`: idempotent `start` on `RUNNING`/`STARTING`, `PORT_OCCUPIED` abort before `consume_pending_restore`/`provider.start`, `provider.start()` `TimeoutError` cleanup.
  - `backend/tests/infrastructure/test_docker_provider.py`: foreign container refusal, running container adoption on matching fingerprint, running container fail-closed on mismatched fingerprint (never `docker rm -f`), `exited`/`created` non-force `docker rm` + recreate.

### Batch 2 — Fail-Closed `stop_confirmed`, Restart/Delete/Provisioning Guards, Supervisor Crash Stop & Retry, and Boot Reconciliation
- **Touches Windows-only code:** **No**
- **Scope:**
  1. Harden `DockerProvider.stop()` (`docker.py`) to verify container exit via `_wait_for_container_exit` after `docker stop -t 30` and `docker kill`, raising `ProviderError` if still running.
  2. Implement `is_stop_confirmed()` and fail-closed `StopServerHandler` (`stop_server.py`): `50s` graceful timeout, require handle + `STOPPED` status + free port + zero errors/warnings, transition to `revert_to_running()` or `mark_stop_unknown()` (`ServerStopUnknownEvent`) on failure, and accept `STOPPING` on re-entry.
  3. Update `RestartServerHandler` (`restart_server.py`) to gate `consume_pending_restore`, plugin deletions, and `server.start()` on confirmed stop, remove premature `mark_stopped()`, clean up on `provider.start()` timeout, and remove exited Docker container before start.
  4. Add `ProvisioningRegistry` in `installer_provisioner.py` (`forge_provisioner.py`, `neoforge_provisioner.py`, `retry_provisioning.py`) and update `DeleteServerHandler` (`delete_server.py`) to cancel/await active provisioning and fail closed (`DELETE_STOP_NOT_CONFIRMED`) if runtime stop/destroy is unconfirmed.
  5. Update `RuntimeSupervisor` (`supervisor.py`) so `_handle_crash()` calls `self._provider.stop()` on still-running runtimes across all providers, and `_verify_startup()` / `_health_check()` retry and self-heal `STARTING -> RUNNING` DB saves.
  6. Fix `reconcile_servers()` (`reconciliation.py`) and `filesystem_reconciliation.py` to check `provider.status(handle)` for `STOPPING` servers and use non-blocking `try_acquire(wait_timeout=0)` per server.
- **Exact Files:**
  - `backend/app/modules/server/domain/events.py`
  - `backend/app/modules/server/domain/aggregate.py`
  - `backend/app/modules/server/infrastructure/providers/docker.py`
  - `backend/app/modules/server/application/commands/stop_server.py`
  - `backend/app/modules/server/application/commands/restart_server.py`
  - `backend/app/modules/server/application/commands/delete_server.py`
  - `backend/app/modules/server/application/commands/retry_provisioning.py`
  - `backend/app/modules/server/application/services/installer_provisioner.py`
  - `backend/app/modules/server/application/services/forge_provisioner.py`
  - `backend/app/modules/server/application/services/neoforge_provisioner.py`
  - `backend/app/modules/server/application/supervisor.py`
  - `backend/app/modules/server/application/reconciliation.py`
  - `backend/app/modules/server/application/services/filesystem_reconciliation.py`
- **Tests to Add / Update:**
  - `backend/tests/application/test_stop_confirmation_and_supervisor.py` *(new)*: `StopServerHandler` `revert_to_running` vs `mark_stop_unknown`, re-entry from `STOPPING`, `RestartServerHandler` abort on unconfirmed stop, `DeleteServerHandler` during `PROVISIONING` and abort on unconfirmed stop, `RuntimeSupervisor._handle_crash` calling `provider.stop()`, `STARTING -> RUNNING` save retry and `_health_check` self-heal, `reconcile_servers` `STOPPING` state table.
  - `backend/tests/infrastructure/test_docker_provider.py`: `DockerProvider.stop` exit confirmation and `ProviderError` when container fails to exit.

### Batch 3 — Promote All-or-Nothing Staging, Rollback Journal, Restart Reporting, and Restore Lock Guard
- **Touches Windows-only code:** **No**
- **Scope:**
  1. Update `PromoteCommitHandler` (`promote_commit.py`) to include `ServerStatus.STOPPING` in `was_active`, check `is_stop_confirmed(stop_result)`, and abort with `PROMOTE_STOP_NOT_CONFIRMED` before any file mutation if stop is unconfirmed.
  2. Implement sibling transaction staging (`tx_root / "staged"` and `tx_root / "backup"`) and `applied_journal` rollback in `PromoteCommitHandler` so any config, `mods`, or `world*` swap failure restores `server_dir` to a byte-identical pre-promote state, preserves `test_dir`, and restarts the production server if `was_running=True`.
  3. Record `restart_attempted`, `restart_ok`, `restart_error_code`, and `restart_error` in `PromoteCommitCommand` `CommandResult.details`.
  4. Update `RestoreBackupHandler` (`restore_backup.py`) to acquire the per-server DB lifecycle lease for `backup.server_id` and verify runtime/port idleness before executing `perform_safe_restore`.
- **Exact Files:**
  - `backend/app/modules/versioning/application/commands/promote_commit.py`
  - `backend/app/modules/backup/application/commands/restore_backup.py`
  - `backend/app/modules/backup/application/restore_service.py`
- **Tests to Add / Update:**
  - `backend/tests/modules/versioning/test_promote_commit_atomicity.py` *(new)*: promote abort when stop fails or returns warnings (`PROMOTE_STOP_NOT_CONFIRMED`); mid-flight failure on config $k$ of $N$, `mods`, and `world_nether` rolling back all prior mutations to byte-identical state; `test_dir` preservation on rollback; automatic production restart after rollback and after successful promote; `RestoreBackupHandler` lock acquisition and active-runtime guard.

### Batch 4 — Windows Handle PID Fix and Cross-Platform Process Identity Verification
- **Touches Windows-only code:** **Yes** (`backend/app/modules/server/infrastructure/providers/local_windows.py` and Windows `taskkill` / `TerminateProcess` paths in `backend/app/core/process_utils.py`)
- **Scope:**
  1. Implement `verify_process_identity()` in `backend/app/core/process_utils.py` and update `backend/app/modules/server/application/ownership_verifier.py` to use `psutil.Process(pid)` cross-platform (verifying `create_time` within tolerance, Java/Minecraft/wrapper `cmdline`, and `cwd`/path inside `expected_server_dir` or `servers_data_dir`).
  2. Update `LocalWindowsProvider` (`local_windows.py`) to record `psutil.Process(pid).create_time()` on start, resolve `pid` from `handle.metadata["pid"]`, and verify process identity via `verify_process_identity()` before `terminate()` and before `taskkill /F /T /PID`.
  3. Update `LocalLinuxProvider.stop()` (`local.py`) to verify process identity before `SIGTERM`/`SIGKILL`.
  4. Update `RuntimeOwnershipRegistry` (`runtime_ownership.py`) and `runtime_reconciliation.py` to pass `stored_start_time` and `expected_server_dir` at all kill sites, acquire a `5s` try-lock before displacing a competing `sid` in `claim_localhost`, refuse to kill unverified port occupants in `claim_localhost`, and enforce `verify_process_identity` before orphan termination in both `project_owned` and `system_wide` scopes.
  5. Ensure remaining `ServerHandle` construction sites (`servers.py`, `backup_orchestrator.py`, `runtime_ownership.py`, `runtime_reconciliation.py`) use `build_server_handle()` with `pid`, `start_time`, `port`, and `server_dir`.
- **Exact Files:**
  - `backend/app/core/process_utils.py`
  - `backend/app/modules/server/application/ownership_verifier.py`
  - `backend/app/modules/server/infrastructure/providers/local_windows.py` *(Windows-specific provider)*
  - `backend/app/modules/server/infrastructure/providers/local.py`
  - `backend/app/modules/server/application/runtime_ownership.py`
  - `backend/app/modules/server/application/runtime_reconciliation.py`
  - `backend/app/api/v1/routers/servers.py`
  - `backend/app/services/backup_orchestrator.py`
- **Tests to Add / Update:**
  - `backend/tests/infrastructure/test_local_windows_and_process_identity.py` *(new)*: `ServerHandle` metadata `pid` round-trip through `StartServerHandler` -> `StopServerHandler` / `RestartServerHandler` for `LocalWindowsProvider`; `verify_process_identity` unit tests for `create_time` mismatch (PID reuse), `cmdline` mismatch, and `server_dir` mismatch; `LocalWindowsProvider._force_kill_process_tree`, `LocalLinuxProvider.stop`, `claim_localhost` port-occupant check, and `reconcile_orphans` refusing to kill unverified processes.
