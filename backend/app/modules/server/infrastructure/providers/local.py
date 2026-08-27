from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import socket
import time
import uuid
from typing import Any

from app.core.exceptions import ProviderError
from app.core.identity import IDENTITY
from app.modules.server.domain.diagnostics import RuntimeDiagnostics
from app.modules.server.domain.value_objects import (
    LaunchConfiguration,
    ServerDeployment,
)
from app.modules.server.infrastructure.fs import FileSystem, local_fs
from app.modules.server.infrastructure.providers.base import (
    DeploymentResult,
    ServerHandle,
    ServerProvider,
    ServerRuntimeStatus,
)
from app.modules.server.infrastructure.providers.patterns import detect_failure

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.provider.local")


class LocalLinuxProvider(ServerProvider):
    def __init__(self, fs: FileSystem | None = None) -> None:
        self._fs = fs or local_fs

    @property
    def provider_type(self) -> str:
        return "local"

    def capabilities(self) -> list[str]:
        return ["process", "console", "exec"]

    async def ping(self) -> bool:
        return True

    def _server_label(self, server_id: str, handle: ServerHandle | None = None) -> str:
        name = None
        if handle is not None:
            name = handle.metadata.get("server_name") if hasattr(handle, "metadata") else None
        if name:
            return f'"{name}" ({server_id})'
        return server_id

    async def _verify_port_free(self, port: int, server_id: str) -> None:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", port))
            sock.close()
        except OSError as err:
            raise ProviderError(
                "local",
                "start",
                f"Port {port} is already in use server={server_id}",
            ) from err

    async def _cleanup_stale_tmux(self, session_name: str) -> None:
        if await self._tmux_has_session(session_name):
            logger.info("Cleaning up stale tmux session %s phase=cleanup", session_name)
            await self._run_command(f"tmux kill-session -t {session_name}")

    async def _find_java_processes(self, server_dir: str) -> list[int]:
        returncode, stdout = await self._run_command_with_output(
            f"ps aux | grep java | grep -F '{server_dir}' | grep -v grep | awk '{{print $2}}'",
        )
        if returncode != 0 or not stdout.strip():
            return []
        pids: list[int] = []
        for line in stdout.strip().splitlines():
            pid_str = line.strip()
            if pid_str.isdigit():
                pids.append(int(pid_str))
        return pids

    async def _find_jvms_by_cwd(self, server_dir: str) -> list[int]:
        """Find Java processes whose working directory is ``server_dir``.

        ``ps`` matching on the command line misses JVMs launched from a ``cd``
        wrapper whose ``ps args`` no longer contain the directory path. Match
        the real ``/proc/<pid>/cwd`` instead so a stray JVM holding the world
        ``session.lock`` is found and cleaned up before a fresh start.
        """
        cwd = os.path.realpath(os.path.abspath(server_dir))
        try:
            returncode, stdout = await self._run_command_with_output(
                "ps -e -o pid=,comm= | grep -i java | awk '{{print $1}}'",
            )
        except Exception:
            return []
        if returncode != 0 or not stdout.strip():
            return []
        found: list[int] = []
        for line in stdout.strip().splitlines():
            line = line.strip()
            if not line.isdigit():
                continue
            pid = int(line)
            try:
                if os.path.realpath(f"/proc/{pid}/cwd") == cwd:
                    found.append(pid)
            except (OSError, FileNotFoundError):
                continue
        return found

    async def _kill_processes(self, pids: list[int]) -> None:
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                continue
        await asyncio.sleep(1)
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                continue

    async def start(
        self,
        server_id: str,
        config: dict[str, Any] | None = None,
        deployment: ServerDeployment | None = None,
        launch_config: LaunchConfiguration | None = None,
    ) -> DeploymentResult:
        session_name = f"{IDENTITY.temp_prefix_new}{server_id}"

        if deployment:
            server_dir = deployment.server_directory()
            jar = deployment.startup_jar
        else:
            server_dir = (config or {}).get("server_dir", f"/opt/minecraft/servers/{server_id}")
            jar = (config or {}).get("jar_path", "server.jar")
        server_dir = os.path.expanduser(server_dir)
        self._fs.ensure_dir(server_dir)

        if launch_config:
            cfg = config or {}
            java_exec = launch_config.java_executable
            jvm_flags = " ".join(launch_config.jvm_flags)
            memory_min = cfg.get("memory_min_mb", 1024)
            memory_max = cfg.get("memory_max_mb", 2048)
            port = cfg.get("port", 25565)
            cmd = launch_config.effective_command()
            is_script_launch = cmd.startswith(("bash ", "sh ", "./", "exec ")) or cmd.endswith(
                ".sh"
            )
            if is_script_launch:
                if "nogui" not in cmd and "--nogui" not in cmd:
                    cmd = f"{cmd} nogui"
                jvm_args_file = os.path.join(server_dir, "user_jvm_args.txt")
                if os.path.exists(jvm_args_file) or not os.path.exists(
                    os.path.join(server_dir, jar)
                ):
                    with contextlib.suppress(Exception):
                        self._fs.write_text(
                            jvm_args_file,
                            f"-Xms{memory_min}M\n-Xmx{memory_max}M\n",
                        )
            else:
                if "-Xms" not in cmd and "-Xmx" not in cmd:
                    cmd = f"{cmd} -Xms{memory_min}M -Xmx{memory_max}M"
            if deployment:
                cmd = f"cd {server_dir} && {cmd}"
        else:
            cfg = config or {}
            java_args = cfg.get("java_args", [])
            memory_min = cfg.get("memory_min_mb", 1024)
            memory_max = cfg.get("memory_max_mb", 2048)
            port = cfg.get("port", 25565)
            java_exec = "java"
            jvm_flags = " ".join(java_args) if isinstance(java_args, list) else str(java_args)

            # Auto-detect script execution vs JAR execution for discovered/unconfigured servers
            has_run_script = self._fs.exists(os.path.join(server_dir, "run.sh")) or self._fs.exists(
                os.path.join(server_dir, "run.bat")
            )
            is_script = (
                jar.endswith((".sh", ".bat"))
                or jar.startswith(("bash ", "sh ", "./"))
                or (not self._fs.exists(os.path.join(server_dir, jar)) and has_run_script)
            )
            if is_script:
                script_name = (
                    "run.sh" if self._fs.exists(os.path.join(server_dir, "run.sh")) else jar
                )
                jvm_args_file = os.path.join(server_dir, "user_jvm_args.txt")
                with contextlib.suppress(Exception):
                    self._fs.write_text(
                        jvm_args_file,
                        f"-Xms{memory_min}M\n-Xmx{memory_max}M\n",
                    )
                cmd = f"cd {server_dir} && bash {script_name} nogui"
            else:
                cmd = (
                    f"cd {server_dir} && {java_exec} {jvm_flags} "
                    f"-Xms{memory_min}M -Xmx{memory_max}M "
                    f"-jar {jar} nogui"
                )

        instance_id = uuid.uuid4().hex[:16]
        marker_prefix = f"export {IDENTITY.process_marker_new}=1 {IDENTITY.env_prefix_new}INSTANCE_ID={instance_id}; "
        cmd = f"{marker_prefix}{cmd}"

        server_label = f'"{server_id}"' if server_id else server_id
        logger.info(
            "Phase 1/4: Cleaning up stale tmux and processes — server=%s dir=%s phase=start",
            server_label,
            server_dir,
        )
        await self._cleanup_stale_tmux(session_name)
        orphan_pids = await self._find_java_processes(server_dir)
        orphan_pids.extend(await self._find_jvms_by_cwd(server_dir))
        orphan_pids = list(dict.fromkeys(orphan_pids))
        if orphan_pids:
            logger.info(
                "Phase 1/4: Cleaning %d orphan Java processes — server=%s dir=%s phase=cleanup",
                len(orphan_pids),
                server_label,
                server_dir,
            )
            await self._kill_processes(orphan_pids)
        else:
            logger.info(
                "Phase 1/4: No orphan processes found — server=%s phase=cleanup",
                server_label,
            )

        logger.info(
            "Phase 2/4: Verifying port %d is free — server=%s phase=port_check",
            port,
            server_label,
        )
        await self._verify_port_free(port, server_id)

        logger.info(
            "Phase 3/4: Creating tmux session — server=%s session=%s phase=tmux_create",
            server_label,
            session_name,
        )
        returncode = await self._run_command(
            f"tmux new-session -d -s {session_name} '{cmd}'",
        )
        if returncode != 0:
            raise ProviderError(
                "local",
                "start",
                f"tmux session creation failed server={server_id} session={session_name} dir={server_dir}",
            )

        await asyncio.sleep(1)

        pid = await self._resolve_server_pid(session_name)

        if pid is None:
            await self._run_command(f"tmux kill-session -t {session_name}")
            raise ProviderError(
                "local",
                "start",
                f"Process died immediately after tmux creation server={server_id} session={session_name}",
            )

        start_time = int(time.time())

        logger.info(
            "Phase 4/4: Server process started — server=%s pid=%d start_time=%s port=%d session=%s phase=startup",
            server_label,
            pid,
            start_time,
            port,
            session_name,
        )

        handle = ServerHandle(
            provider="local",
            server_id=server_id,
            external_id=session_name,
            metadata={"server_dir": server_dir, "session_name": session_name, "port": port},
        )

        return DeploymentResult(
            status=ServerRuntimeStatus.RUNNING,
            address="127.0.0.1",
            port=port,
            pid=pid,
            metadata={
                "handle": str(handle),
                "session_name": session_name,
                "start_time": start_time,
                "port": port,
            },
        )

    async def stop(self, handle: ServerHandle, force: bool = False) -> None:
        session_name = handle.external_id
        server_label = f'"{handle.metadata.get("server_name", handle.server_id)}"'

        if not force:
            logger.info(
                "Phase 1/3: Graceful shutdown — server=%s session=%s phase=stop",
                server_label,
                session_name,
            )
            await self.execute_command(handle, "say Server shutting down...")
            await asyncio.sleep(0.5)
            await self.execute_command(handle, "save-all")
            await asyncio.sleep(1)
            await self.execute_command(handle, "stop")
            await asyncio.sleep(3)

        pid = await self._get_tmux_pid(session_name)
        if pid:
            try:
                logger.info(
                    "Phase 2/3: Sending SIGTERM — server=%s pid=%d session=%s phase=stop",
                    server_label,
                    pid,
                    session_name,
                )
                os.kill(pid, signal.SIGTERM)
                await asyncio.sleep(1)
            except ProcessLookupError:
                logger.debug(
                    "SIGTERM — process already exited server=%s pid=%d session=%s phase=stop",
                    server_label,
                    pid,
                    session_name,
                )

            try:
                logger.info(
                    "Phase 2/3: Sending SIGKILL — server=%s pid=%d session=%s phase=stop",
                    server_label,
                    pid,
                    session_name,
                )
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                logger.debug(
                    "SIGKILL — process already exited server=%s pid=%d session=%s phase=stop",
                    server_label,
                    pid,
                    session_name,
                )

        logger.info(
            "Phase 3/3: Cleaning up tmux session — server=%s session=%s phase=stop",
            server_label,
            session_name,
        )
        await self._run_command(f"tmux kill-session -t {session_name}")

    async def status(self, handle: ServerHandle) -> ServerRuntimeStatus:
        session_name = handle.external_id
        try:
            has = await self._tmux_has_session(session_name)
            if not has:
                return ServerRuntimeStatus.STOPPED

            pid = await self._get_tmux_pid(session_name)
            if pid is None:
                return ServerRuntimeStatus.UNKNOWN

            alive = await self._is_pid_alive(pid)
            if not alive:
                return ServerRuntimeStatus.ERROR

            return ServerRuntimeStatus.RUNNING
        except Exception as exc:
            raise ProviderError(
                "local",
                "status",
                f"status check failed session={session_name} handle={handle.external_id}",
            ) from exc

    async def console(self, handle: ServerHandle, tail: int = 100) -> list[str]:
        session_name = handle.external_id
        try:
            returncode, stdout = await self._run_command_with_output(
                f"tmux capture-pane -t {session_name} -p -S -{tail}",
            )
            if returncode != 0:
                raise ProviderError(
                    "local",
                    "console",
                    f"tmux capture-pane failed session={session_name} tail={tail} returncode={returncode}",
                )
            return stdout.splitlines() if stdout else []
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(
                "local",
                "console",
                f"console failed session={session_name} tail={tail}",
            ) from exc

    async def execute_command(self, handle: ServerHandle, command: str) -> str:
        session_name = handle.external_id
        escaped = command.replace("'", "'\\''")
        try:
            returncode, stdout = await self._run_command_with_output(
                f"tmux send-keys -t {session_name} '{escaped}' Enter",
            )
            if returncode != 0:
                raise ProviderError(
                    "local",
                    "execute_command",
                    f"tmux send-keys failed session={session_name} cmd={command[:100]} returncode={returncode}",
                )
            return stdout
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(
                "local",
                "execute_command",
                f"send-keys failed session={session_name} cmd={command[:100]}",
            ) from exc

    async def destroy(self, handle: ServerHandle) -> None:
        await self.stop(handle, force=True)

    async def _tmux_has_session(self, name: str) -> bool:
        try:
            returncode, _ = await self._run_command_with_output(
                f"tmux has-session -t {name} 2>/dev/null",
            )
            return returncode == 0
        except Exception as exc:
            raise ProviderError(
                "local",
                "_tmux_has_session",
                f"tmux has-session failed session={name}",
            ) from exc

    async def _get_tmux_pid(self, session_name: str) -> int | None:
        try:
            returncode, stdout = await self._run_command_with_output(
                f"tmux list-panes -t {session_name} -F '#{{pane_pid}}' 2>/dev/null",
            )
            if returncode != 0 or not stdout:
                return None
            line = stdout.strip().splitlines()[0] if stdout.strip() else ""
            if line.isdigit():
                return int(line)
            return None
        except Exception as exc:
            raise ProviderError(
                "local",
                "_get_tmux_pid",
                f"tmux list-panes failed session={session_name}",
            ) from exc

    async def _is_pid_alive(self, pid: int) -> bool:
        try:
            return await self._run_command(f"kill -0 {pid} 2>/dev/null") == 0
        except Exception:
            logger.warning(
                "kill -0 failed pid=%d phase=_is_pid_alive provider=%s",
                pid,
                self.provider_type,
                exc_info=True,
            )
            return False

    async def _resolve_server_pid(self, session_name: str) -> int | None:
        """Return the PID of the actual JVM (java) process for a session.

        ``tmux pane_pid`` is the wrapper shell (e.g. ``fish``/``bash``) that
        launches the server. The Minecraft server itself runs as a descendant
        ``java`` process. Find the nearest ``java`` descendant so recorded
        PIDs (deployment_pid, metrics sampling) point at the real JVM rather
        than the wrapper shell, which would otherwise report ~0 RAM/CPU.
        """
        pane_pid = await self._get_tmux_pid(session_name)
        if pane_pid is None:
            return None
        descendants = await self._find_java_descendants(pane_pid)
        if descendants:
            return descendants[0]
        return pane_pid

    async def _find_java_descendants(self, root_pid: int, depth: int = 4) -> list[int]:
        found: list[int] = []
        seen: set[int] = set()
        current = [root_pid]
        for _ in range(depth):
            children: list[int] = []
            for pid in current:
                if pid in seen:
                    continue
                seen.add(pid)
                returncode, stdout = await self._run_command_with_output(
                    f"ps -o pid=,ppid=,comm= --ppid {pid} 2>/dev/null",
                )
                if returncode != 0 or not stdout.strip():
                    continue
                for line in stdout.strip().splitlines():
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    child_pid, comm = int(parts[0]), parts[-1]
                    children.append(child_pid)
                    if comm == "java":
                        found.append(child_pid)
            current = children
            if not current:
                break
        return found

    async def _run_command(self, cmd: str) -> int:
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                close_fds=True,
            )
            await proc.wait()
            return proc.returncode if proc.returncode is not None else 0
        except Exception as exc:
            raise ProviderError(
                "local",
                "run_command",
                f"Subprocess shell command failed: {cmd[:200]}",
            ) from exc

    async def _run_command_with_output(self, cmd: str) -> tuple[int, str]:
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                close_fds=True,
            )
            stdout, _ = await proc.communicate()
            return proc.returncode if proc.returncode is not None else 0, stdout.decode(
                "utf-8", errors="replace"
            )
        except Exception as exc:
            raise ProviderError(
                "local",
                "run_command_with_output",
                f"Subprocess shell command failed: {cmd[:200]}",
            ) from exc

    async def wait_ready(
        self,
        server_id: str,
        handle: ServerHandle,
        timeout: float = 60.0,
    ) -> bool:
        session_name = handle.external_id
        label = self._server_label(server_id, handle)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                # Check if tmux session exists before trying to capture console
                has = await self._tmux_has_session(session_name)
                if not has:
                    logger.info(
                        "wait_ready server=%s session=%s session not found or terminated provider=%s",
                        label,
                        session_name,
                        self.provider_type,
                    )
                    return False

                lines = await self.console(handle, tail=50)
                logger.info(
                    "wait_ready server=%s session=%s iter lines=%d has_done=%s provider=%s",
                    label,
                    session_name,
                    len(lines),
                    any("Done (" in line_str for line_str in lines),
                    self.provider_type,
                )
                for line in lines:
                    if "Done (" in line:
                        return True
                pid = await self._get_tmux_pid(session_name)
                if pid is None:
                    logger.info(
                        "wait_ready server=%s session=%s pid is None — pane exited provider=%s",
                        label,
                        session_name,
                        self.provider_type,
                    )
                    return False
                alive = await self._is_pid_alive(pid)
                if not alive:
                    logger.info(
                        "wait_ready server=%s session=%s pid=%d dead provider=%s",
                        label,
                        session_name,
                        pid,
                        self.provider_type,
                    )
                    return False
            except Exception:
                logger.warning(
                    "wait_ready iteration failed server=%s provider=%s session=%s handle=%s phase=wait_ready",
                    label,
                    self.provider_type,
                    session_name,
                    handle.external_id,
                    exc_info=True,
                )
            await asyncio.sleep(2)
        logger.info(
            "wait_ready server=%s session=%s deadline exceeded provider=%s",
            label,
            session_name,
            self.provider_type,
        )
        return False

    async def get_runtime_pid(self, handle: ServerHandle) -> int | None:
        return await self._resolve_server_pid(handle.external_id)

    async def verify_process(self, handle: ServerHandle) -> bool:
        session_name = handle.external_id
        try:
            has = await self._tmux_has_session(session_name)
            if not has:
                return False
            pid = await self._get_tmux_pid(session_name)
            if pid is None:
                return False
            return await self._is_pid_alive(pid)
        except Exception as exc:
            raise ProviderError(
                "local",
                "verify_process",
                f"verify_process failed session={session_name} handle={handle.external_id}",
            ) from exc

    async def collect_diagnostics(
        self,
        handle: ServerHandle,
    ) -> RuntimeDiagnostics:
        session_name = handle.external_id
        server_id = handle.server_id
        label = self._server_label(server_id, handle)
        log_lines: list[str] = []
        exit_code: int | None = None
        pid: int | None = None

        try:
            log_lines = await self.console(handle, tail=300)
        except Exception:
            logger.warning(
                "collect_diagnostics console failed server=%s session=%s handle=%s "
                "phase=collect_diagnostics provider=%s",
                label,
                session_name,
                handle.external_id,
                self.provider_type,
                exc_info=True,
            )

        if not log_lines:
            server_dir = handle.metadata.get("server_dir")
            if server_dir:
                log_file = os.path.join(server_dir, "logs", "latest.log")
                if os.path.isfile(log_file):
                    try:
                        with open(log_file, encoding="utf-8", errors="replace") as f:
                            log_lines = [line.rstrip("\n") for line in f.readlines()[-300:]]
                    except Exception:
                        pass

        try:
            pid = await self._get_tmux_pid(session_name)
        except Exception:
            logger.warning(
                "collect_diagnostics get_pid failed server=%s session=%s handle=%s "
                "phase=collect_diagnostics provider=%s",
                label,
                session_name,
                handle.external_id,
                self.provider_type,
                exc_info=True,
            )

        failure_code, pattern_name = detect_failure(log_lines)
        failure_reason = f"Detected {pattern_name}" if pattern_name else ""

        return RuntimeDiagnostics(
            provider="local",
            runtime_handle=str(handle),
            pid=pid,
            exit_code=exit_code,
            last_log_lines=log_lines,
            failure_code=failure_code,
            failure_reason=failure_reason,
        )


def is_linux() -> bool:
    return os.name == "posix" and os.uname().sysname == "Linux"
