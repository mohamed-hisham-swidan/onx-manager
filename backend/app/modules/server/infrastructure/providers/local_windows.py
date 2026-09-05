from __future__ import annotations

import asyncio
import contextlib
import ctypes
import logging
import os
import platform
import shlex
import socket
import subprocess
import sys
import time
import uuid
from typing import Any

from app.core.exceptions import ProviderError
from app.core.identity import IDENTITY
from app.core.process_utils import platform_kill_process_tree_async, platform_pid_alive
from app.modules.server.domain.diagnostics import RuntimeDiagnostics
from app.modules.server.domain.value_objects import (
    CpuAllocation,
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

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.provider.local_windows")


def parse_affinity_mask(affinity_str: str) -> int:
    mask = 0
    parts = affinity_str.replace(",", " ").split()
    for part in parts:
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            for core in range(int(start_s), int(end_s) + 1):
                mask |= 1 << core
        else:
            mask |= 1 << int(part)
    return mask


class LocalWindowsProvider(ServerProvider):
    """Local provider implementation for Windows environments."""

    def __init__(self, fs: FileSystem | None = None) -> None:
        self._fs = fs or local_fs
        self._processes: dict[str, subprocess.Popen[Any]] = {}

    @property
    def provider_type(self) -> str:
        return "local_windows"

    def capabilities(self) -> list[str]:
        return ["process", "console", "exec"]

    async def ping(self) -> bool:
        return sys.platform == "win32" or platform.system() == "Windows"

    def _server_label(self, server_id: str, handle: ServerHandle | None = None) -> str:
        name = None
        if handle is not None and hasattr(handle, "metadata") and handle.metadata:
            name = handle.metadata.get("server_name")
        if name:
            return f'"{name}" ({server_id})'
        return server_id

    async def _verify_port_free(self, port: int, server_id: str) -> None:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if sys.platform != "win32":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", port))
            sock.close()
        except OSError as err:
            raise ProviderError(
                "local_windows",
                "start",
                f"Port {port} is already in use server={server_id}",
            ) from err

    async def start(
        self,
        server_id: str,
        config: dict[str, Any] | None = None,
        deployment: ServerDeployment | None = None,
        launch_config: LaunchConfiguration | None = None,
    ) -> DeploymentResult:
        session_name = f"{IDENTITY.temp_prefix_new}{server_id}"
        server_label = f'"{server_id}"' if server_id else server_id

        cfg = config or {}
        cpu_cores = int(cfg.get("cpu_cores") or 0)
        cpu_affinity = str(cfg.get("cpu_affinity") or "").strip()

        # Hard validation gate: raises ProviderError on invalid format
        try:
            CpuAllocation.validate(cpu_cores, cpu_affinity)
        except ValueError as exc:
            raise ProviderError(
                "local_windows",
                "start",
                f"Invalid CPU allocation configuration: {exc}",
            ) from exc

        if deployment:
            server_dir = deployment.server_directory()
            jar = deployment.startup_jar
        else:
            server_dir = cfg.get(
                "server_dir",
                f"C:\\minecraft\\servers\\{server_id}",
            )
            jar = cfg.get("jar_path", "server.jar")

        server_dir = os.path.expanduser(server_dir)
        self._fs.ensure_dir(server_dir)

        if launch_config:
            memory_min = cfg.get("memory_min_mb", 1024)
            memory_max = cfg.get("memory_max_mb", 2048)
            port = cfg.get("port", 25565)
            cmd_list = launch_config.effective_command()
            first_token = cmd_list[0].lower() if cmd_list else ""
            is_script_launch = (
                any(arg.lower().endswith((".bat", ".cmd", ".ps1", ".sh")) for arg in cmd_list)
                or first_token in ("cmd", "cmd.exe", "powershell", "powershell.exe", "bash", "sh")
                or first_token.startswith("./")
            )
            if is_script_launch:
                jvm_args_file = os.path.join(server_dir, "user_jvm_args.txt")
                if os.path.exists(jvm_args_file) or not os.path.exists(
                    os.path.join(server_dir, jar)
                ):
                    with contextlib.suppress(Exception):
                        jvm_content = f"-Xms{memory_min}M\n-Xmx{memory_max}M\n"
                        if cpu_cores > 0:
                            jvm_content += f"-XX:ActiveProcessorCount={cpu_cores}\n"
                        self._fs.write_text(jvm_args_file, jvm_content)
                if (
                    any(arg.lower().endswith(".ps1") for arg in cmd_list)
                    and first_token not in ("powershell", "powershell.exe")
                ):
                    cmd_args = [
                        "powershell.exe",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        *cmd_list,
                    ]
                elif (
                    any(arg.lower().endswith((".bat", ".cmd")) for arg in cmd_list)
                    and first_token not in ("cmd", "cmd.exe")
                ):
                    cmd_args = ["cmd.exe", "/c", *cmd_list]
                elif first_token in ("powershell", "powershell.exe"):
                    if "-executionpolicy" not in [p.lower() for p in cmd_list]:
                        cmd_args = [cmd_list[0], "-ExecutionPolicy", "Bypass", *cmd_list[1:]]
                    else:
                        cmd_args = list(cmd_list)
                else:
                    cmd_args = list(cmd_list)

                if "nogui" not in cmd_args and "--nogui" not in cmd_args:
                    cmd_args.append("nogui")
            else:
                cmd_args = list(cmd_list)
                if not any("-Xms" in a for a in cmd_args):
                    cmd_args.append(f"-Xms{memory_min}M")
                if not any("-Xmx" in a for a in cmd_args):
                    cmd_args.append(f"-Xmx{memory_max}M")
                if cpu_cores > 0 and not any("-XX:ActiveProcessorCount" in a for a in cmd_args):
                    cmd_args.append(f"-XX:ActiveProcessorCount={cpu_cores}")
                if "nogui" not in cmd_args and "--nogui" not in cmd_args:
                    cmd_args.append("nogui")
        else:
            cfg = config or {}
            java_args = cfg.get("java_args", [])
            memory_min = cfg.get("memory_min_mb", 1024)
            memory_max = cfg.get("memory_max_mb", 2048)
            port = cfg.get("port", 25565)
            java_exec = "java"

            has_run_script = (
                self._fs.exists(os.path.join(server_dir, "run.bat"))
                or self._fs.exists(os.path.join(server_dir, "run.cmd"))
                or self._fs.exists(os.path.join(server_dir, "run.ps1"))
            )
            is_script = (
                jar.endswith((".bat", ".cmd", ".ps1"))
                or jar.startswith(("cmd ", "powershell "))
                or (not self._fs.exists(os.path.join(server_dir, jar)) and has_run_script)
            )
            if is_script:
                script_name = (
                    "run.bat"
                    if self._fs.exists(os.path.join(server_dir, "run.bat"))
                    else (
                        "run.cmd"
                        if self._fs.exists(os.path.join(server_dir, "run.cmd"))
                        else (
                            "run.ps1"
                            if self._fs.exists(os.path.join(server_dir, "run.ps1"))
                            else jar
                        )
                    )
                )
                jvm_args_file = os.path.join(server_dir, "user_jvm_args.txt")
                with contextlib.suppress(Exception):
                    jvm_content = f"-Xms{memory_min}M\n-Xmx{memory_max}M\n"
                    if cpu_cores > 0:
                        jvm_content += f"-XX:ActiveProcessorCount={cpu_cores}\n"
                    self._fs.write_text(jvm_args_file, jvm_content)
                if script_name.endswith(".ps1"):
                    cmd_args = [
                        "powershell.exe",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        script_name,
                        "nogui",
                    ]
                elif script_name.endswith((".bat", ".cmd")):
                    cmd_args = ["cmd.exe", "/c", script_name, "nogui"]
                elif script_name.startswith(("powershell ", "powershell.exe ")):
                    parts = shlex.split(script_name)
                    if "-ExecutionPolicy" not in parts and "-executionpolicy" not in [
                        p.lower() for p in parts
                    ]:
                        cmd_args = [parts[0], "-ExecutionPolicy", "Bypass", *parts[1:]]
                    else:
                        cmd_args = parts
                    if "nogui" not in cmd_args and "--nogui" not in cmd_args:
                        cmd_args.append("nogui")
                elif script_name.startswith(("cmd ", "cmd.exe ")):
                    cmd_args = shlex.split(script_name)
                    if "nogui" not in cmd_args and "--nogui" not in cmd_args:
                        cmd_args.append("nogui")
                else:
                    cmd_args = ["cmd.exe", "/c", script_name, "nogui"]
            else:
                if isinstance(java_args, list):
                    flags = [str(a) for a in java_args if str(a).strip()]
                elif isinstance(java_args, str) and java_args.strip():
                    flags = [a for a in java_args.split() if a]
                else:
                    flags = []
                cmd_args = [
                    java_exec,
                    *flags,
                    f"-Xms{memory_min}M",
                    f"-Xmx{memory_max}M",
                ]
                if cpu_cores > 0:
                    cmd_args.append(f"-XX:ActiveProcessorCount={cpu_cores}")
                cmd_args.extend(["-jar", jar, "nogui"])

        instance_id = uuid.uuid4().hex[:16]
        env = {
            **os.environ,
            IDENTITY.process_marker_new: "1",
            f"{IDENTITY.env_prefix_new}INSTANCE_ID": instance_id,
        }

        logger.info(
            "Verifying port %d is free — server=%s phase=port_check",
            port,
            server_label,
        )
        await self._verify_port_free(port, server_id)

        creationflags = 0
        if sys.platform == "win32":
            create_new_process_group = getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
            )
            detached_process = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            creationflags = create_new_process_group | detached_process | create_no_window

        logger.info(
            "Spawning Windows server process — server=%s cmd=%s dir=%s",
            server_label,
            cmd_args,
            server_dir,
        )
        try:
            # We explicitly pass cmd_args as a list without shell=True to ensure Popen.pid
            # refers directly to the spawned process (java.exe for direct launches, or the
            # cmd.exe / powershell.exe wrapper for script launches). When launching scripts via
            # cmd.exe /c script.bat or powershell.exe -File script.ps1 without an internal 'start'
            # command, the wrapper process PID accurately tracks child liveness and stdin.
            proc = subprocess.Popen(
                cmd_args,
                cwd=server_dir,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            pid = proc.pid
            self._processes[server_id] = proc

            if cpu_affinity:
                try:
                    mask = parse_affinity_mask(cpu_affinity)
                    windll = getattr(ctypes, "windll", None)
                    if windll and hasattr(windll, "kernel32"):
                        handle = int(getattr(proc, "_handle", 0) or 0)
                        windll.kernel32.SetProcessAffinityMask(
                            handle,
                            ctypes.c_uint64(mask),
                        )
                except Exception as exc:
                    logger.warning(
                        "Failed to set Windows process affinity mask — "
                        "server=%s affinity=%s error=%s",
                        server_label,
                        cpu_affinity,
                        exc,
                    )
        except Exception as exc:
            raise ProviderError(
                "local_windows",
                "start",
                f"Failed to spawn Windows process server={server_id} cmd={str(cmd_args)[:100]}",
            ) from exc

        await asyncio.sleep(0.5)

        if not platform_pid_alive(pid):
            self._processes.pop(server_id, None)
            raise ProviderError(
                "local_windows",
                "start",
                f"Process died immediately after spawn server={server_id} pid={pid}",
            )

        start_time = int(time.time())

        logger.info(
            "Server process started — server=%s pid=%d start_time=%s port=%d",
            server_label,
            pid,
            start_time,
            port,
        )

        handle = ServerHandle(
            provider="local_windows",
            server_id=server_id,
            external_id=str(pid),
            metadata={
                "server_dir": server_dir,
                "session_name": session_name,
                "port": port,
                "pid": pid,
            },
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
                "pid": pid,
                "server_dir": server_dir,
            },
        )

    async def stop(self, handle: ServerHandle, force: bool = False) -> None:
        pid = await self.get_runtime_pid(handle)
        server_id = handle.server_id
        server_label = self._server_label(server_id, handle)

        if pid is None:
            logger.debug(
                "Stop called with no valid PID server=%s handle=%s",
                server_label,
                handle,
            )
            return

        if not force and platform_pid_alive(pid):
            logger.info("Graceful shutdown for server=%s pid=%d", server_label, pid)
            with contextlib.suppress(Exception):
                await self.execute_command(handle, "say Server shutting down...")
                await asyncio.sleep(0.5)
                await self.execute_command(handle, "save-all")
                await asyncio.sleep(1)
                await self.execute_command(handle, "stop")

            # Wait up to 5 seconds for graceful exit
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if not platform_pid_alive(pid):
                    logger.info(
                        "Server process %d exited gracefully server=%s",
                        pid,
                        server_label,
                    )
                    self._processes.pop(server_id, None)
                    return
                await asyncio.sleep(0.5)

        # Force kill process tree if still alive
        if platform_pid_alive(pid):
            logger.info(
                "Force killing server process tree server=%s pid=%d",
                server_label,
                pid,
            )
            await self._force_kill_process_tree(pid)

        self._processes.pop(server_id, None)

    async def _force_kill_process_tree(self, pid: int) -> None:
        if sys.platform == "win32":
            try:
                proc = await asyncio.create_subprocess_exec(
                    "taskkill",
                    "/F",
                    "/T",
                    "/PID",
                    str(pid),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()
            except Exception as exc:
                logger.warning("taskkill failed for pid=%d: %s", pid, exc)
        else:
            await platform_kill_process_tree_async(pid)

    async def status(self, handle: ServerHandle) -> ServerRuntimeStatus:
        pid = await self.get_runtime_pid(handle)
        if pid is None:
            return ServerRuntimeStatus.STOPPED
        if platform_pid_alive(pid):
            return ServerRuntimeStatus.RUNNING
        return ServerRuntimeStatus.STOPPED

    async def verify_process(self, handle: ServerHandle) -> bool:
        pid = await self.get_runtime_pid(handle)
        if pid is None:
            return False
        return platform_pid_alive(pid)

    async def get_runtime_pid(self, handle: ServerHandle) -> int | None:
        if handle.metadata and "pid" in handle.metadata:
            try:
                return int(handle.metadata["pid"])
            except (ValueError, TypeError):
                pass
        if handle.external_id and handle.external_id.isdigit():
            return int(handle.external_id)
        return None

    async def console(self, handle: ServerHandle, tail: int = 100) -> list[str]:
        server_dir = handle.metadata.get("server_dir")
        if not server_dir and handle.server_id:
            server_dir = f"C:\\minecraft\\servers\\{handle.server_id}"

        log_file = (
            os.path.join(server_dir, "logs", "latest.log")
            if server_dir
            else None
        )
        if log_file and os.path.isfile(log_file):
            try:
                with open(log_file, encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                    return [line.rstrip("\r\n") for line in lines[-tail:]]
            except Exception as exc:
                raise ProviderError(
                    "local_windows",
                    "console",
                    f"Failed to read log file {log_file}: {exc}",
                ) from exc
        return []

    async def execute_command(self, handle: ServerHandle, command: str) -> str:
        server_id = handle.server_id
        proc = self._processes.get(server_id)
        if proc and proc.stdin and not proc.stdin.closed:
            try:
                proc.stdin.write(f"{command}\n".encode())
                proc.stdin.flush()
                return f"Command sent to server {server_id}: {command}"
            except Exception as exc:
                raise ProviderError(
                    "local_windows",
                    "execute_command",
                    f"Failed to write to stdin of process for server={server_id}: {exc}",
                ) from exc

        pid = await self.get_runtime_pid(handle)
        if pid and platform_pid_alive(pid):
            raise ProviderError(
                "local_windows",
                "execute_command",
                f"Console access lost for server {server_id} after daemon restart; "
                f"process PID {pid} is running detached. "
                "Restart the server to regain console access.",
            )

        raise ProviderError(
            "local_windows",
            "execute_command",
            f"Server {server_id} has no interactive stdin available",
        )

    async def wait_ready(
        self,
        server_id: str,
        handle: ServerHandle,
        timeout: float = 60.0,
    ) -> bool:
        pid = await self.get_runtime_pid(handle)
        label = self._server_label(server_id, handle)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if pid and not platform_pid_alive(pid):
                logger.info(
                    "wait_ready server=%s pid=%d dead provider=%s",
                    label,
                    pid,
                    self.provider_type,
                )
                return False
            try:
                lines = await self.console(handle, tail=50)
                for line in lines:
                    if "Done (" in line:
                        return True
            except Exception:
                pass
            await asyncio.sleep(2)
        return False

    async def collect_diagnostics(
        self,
        handle: ServerHandle,
    ) -> RuntimeDiagnostics:
        pid = await self.get_runtime_pid(handle)
        log_lines: list[str] = []
        with contextlib.suppress(Exception):
            log_lines = await self.console(handle, tail=300)

        failure_code, pattern_name = detect_failure(log_lines)
        failure_reason = f"Detected {pattern_name}" if pattern_name else ""

        return RuntimeDiagnostics(
            provider="local_windows",
            runtime_handle=str(handle),
            pid=pid,
            exit_code=None if (pid and platform_pid_alive(pid)) else -1,
            last_log_lines=log_lines,
            failure_code=failure_code,
            failure_reason=failure_reason,
        )

    async def destroy(self, handle: ServerHandle) -> None:
        await self.stop(handle, force=True)


def is_windows() -> bool:
    return sys.platform == "win32"
