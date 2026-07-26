from __future__ import annotations

import asyncio
import os
import tempfile
from typing import Any

from app.core.exceptions import ProviderError
from app.modules.server.infrastructure.providers.base import (
    DeploymentResult,
    ServerHandle,
    ServerProvider,
    ServerRuntimeStatus,
)


class SSHProvider(ServerProvider):
    def __init__(
        self,
        host: str,
        username: str = "root",
        port: int = 22,
        key_path: str | None = None,
        known_hosts: str | None = None,
        keepalive_seconds: int = 30,
    ) -> None:
        self._host = host
        self._username = username
        self._port = port
        self._key_path = key_path or os.path.expanduser("~/.ssh/id_rsa")
        self._known_hosts = known_hosts
        self._keepalive_seconds = keepalive_seconds
        self._connection: Any = None

    @property
    def provider_type(self) -> str:
        return "ssh"

    async def ping(self) -> bool:
        try:
            conn = await self._get_connection()
            result = await conn.run("echo pong", check=False)
            return result.returncode == 0
        except Exception:
            return False

    async def start(self, server_id: str, config: dict[str, Any]) -> DeploymentResult:
        conn = await self._get_connection()
        memory_min = config.get("memory_min_mb", 1024)
        memory_max = config.get("memory_max_mb", 2048)
        port = config.get("port", 25565)
        jar_path = config.get("jar_path", "server.jar")
        server_dir = config.get("server_dir", f"/opt/minecraft/servers/{server_id}")
        java_args = config.get("java_args", [])
        session_name = f"mcs-{server_id}"

        jvm_args = " ".join(java_args) if isinstance(java_args, list) else java_args

        mkdir_result = await conn.run(f"mkdir -p {server_dir}", check=False)
        if mkdir_result.returncode != 0:
            raise ProviderError("ssh", "start", f"Failed to create server dir: {mkdir_result.stderr}")

        start_cmd = (
            f"cd {server_dir} && java {jvm_args} "
            f"-Xms{memory_min}M -Xmx{memory_max}M "
            f"-jar {jar_path} nogui"
        )

        tmux_cmd = (
            f"tmux new-session -d -s {session_name} '{start_cmd}'"
        )

        result = await conn.run(tmux_cmd, check=False)
        if result.returncode != 0:
            raise ProviderError("ssh", "start", f"tmux failed: {result.stderr}")

        await asyncio.sleep(1)

        pid_result = await conn.run(
            f"tmux list-panes -t {session_name} -F '#{{pane_pid}}'",
            check=False,
        )
        pid = int(pid_result.stdout.strip()) if pid_result.stdout.strip().isdigit() else None

        handle = ServerHandle(
            provider="ssh",
            server_id=server_id,
            external_id=f"{self._host}:{session_name}",
            metadata={
                "host": self._host,
                "session_name": session_name,
                "server_dir": server_dir,
            },
        )

        return DeploymentResult(
            status=ServerRuntimeStatus.RUNNING,
            address=self._host,
            port=port,
            pid=pid,
            metadata={"handle": str(handle), "session_name": session_name},
        )

    async def stop(self, handle: ServerHandle, force: bool = False) -> None:
        conn = await self._get_connection()
        session_name = self._parse_session_name(handle)

        if not force:
            await self.execute_command(handle, "say Server shutting down...")
            await asyncio.sleep(0.5)
            await self.execute_command(handle, "save-all")
            await asyncio.sleep(1)
            await self.execute_command(handle, "stop")
            await asyncio.sleep(3)

        if force:
            await conn.run(
                f"tmux send-keys -t {session_name} C-c",
                check=False,
            )

        await conn.run(f"tmux kill-session -t {session_name}", check=False)

    async def status(self, handle: ServerHandle) -> ServerRuntimeStatus:
        conn = await self._get_connection()
        session_name = self._parse_session_name(handle)

        result = await conn.run(
            f"tmux has-session -t {session_name} 2>/dev/null && echo 'exists'",
            check=False,
        )
        if not result.stdout or "exists" not in result.stdout:
            return ServerRuntimeStatus.STOPPED

        pid_result = await conn.run(
            f"tmux list-panes -t {session_name} -F '#{{pane_pid}}'",
            check=False,
        )
        pid_str = pid_result.stdout.strip()
        if not pid_str.isdigit():
            return ServerRuntimeStatus.UNKNOWN

        alive = await conn.run(f"kill -0 {pid_str} 2>/dev/null && echo 'alive'", check=False)
        if "alive" in (alive.stdout or ""):
            return ServerRuntimeStatus.RUNNING
        return ServerRuntimeStatus.ERROR

    async def console(self, handle: ServerHandle, tail: int = 100) -> list[str]:
        conn = await self._get_connection()
        session_name = self._parse_session_name(handle)
        result = await conn.run(
            f"tmux capture-pane -t {session_name} -p -S -{tail}",
            check=False,
        )
        if result.returncode != 0:
            raise ProviderError("ssh", "console", "Failed to capture tmux pane")
        return result.stdout.splitlines() if result.stdout else []

    async def execute_command(self, handle: ServerHandle, command: str) -> str:
        conn = await self._get_connection()
        session_name = self._parse_session_name(handle)
        escaped = command.replace("'", "'\\''")
        result = await conn.run(
            f"tmux send-keys -t {session_name} '{escaped}' Enter",
            check=False,
        )
        if result.returncode != 0:
            raise ProviderError("ssh", "execute_command", f"tmux send-keys failed: {result.stderr}")
        return result.stdout or ""

    async def destroy(self, handle: ServerHandle) -> None:
        await self.stop(handle, force=True)

    async def get_runtime_pid(self, handle: ServerHandle) -> int | None:
        conn = await self._get_connection()
        session_name = self._parse_session_name(handle)
        result = await conn.run(
            f"tmux list-panes -t {session_name} -F '#{{pane_pid}}' 2>/dev/null",
            check=False,
        )
        pid_str = result.stdout.strip()
        if pid_str.isdigit():
            return int(pid_str)
        return None

    async def _get_connection(self) -> Any:
        if self._connection is not None:
            try:
                result = await self._connection.run("echo ping", check=False)
                if result.returncode == 0:
                    return self._connection
            except Exception:
                pass
            try:
                self._connection.close()
            except Exception:
                pass
            self._connection = None

        kwargs: dict[str, Any] = {
            "host": self._host,
            "port": self._port,
            "username": self._username,
            "client_keys": [self._key_path],
            "known_hosts": None,
            "keepalive_interval": self._keepalive_seconds,
        }

        try:
            import asyncssh
        except ImportError:
            raise ProviderError("ssh", "connect", "asyncssh is not installed")

        self._connection = await asyncssh.connect(**kwargs)
        return self._connection

    def _parse_session_name(self, handle: ServerHandle) -> str:
        parts = handle.external_id.split(":", 1)
        if len(parts) > 1:
            return parts[1]
        return handle.external_id

    async def upload_file(
        self,
        handle: ServerHandle,
        local_path: str,
        remote_path: str,
    ) -> None:
        conn = await self._get_connection()
        try:
            await asyncssh.scp(local_path, (conn, remote_path))
        except Exception as e:
            raise ProviderError("ssh", "upload", str(e))

    async def download_file(
        self,
        handle: ServerHandle,
        remote_path: str,
        local_path: str,
    ) -> None:
        conn = await self._get_connection()
        try:
            await asyncssh.scp((conn, remote_path), local_path)
        except Exception as e:
            raise ProviderError("ssh", "download", str(e))
