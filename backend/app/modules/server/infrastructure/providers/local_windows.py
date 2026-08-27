from __future__ import annotations

import asyncio
import platform
from typing import Any

from app.core.exceptions import ProviderError
from app.core.identity import IDENTITY
from app.modules.server.infrastructure.providers.base import (
    DeploymentResult,
    ServerHandle,
    ServerProvider,
    ServerRuntimeStatus,
)


class LocalWindowsProvider(ServerProvider):
    @property
    def provider_type(self) -> str:
        return "local_windows"

    def capabilities(self) -> list[str]:
        return ["process", "console", "exec"]

    async def ping(self) -> bool:
        return platform.system() == "Windows"

    async def start(self, server_id: str, config: dict[str, Any]) -> DeploymentResult:
        java_args = config.get("java_args", [])
        memory_min = config.get("memory_min_mb", 1024)
        memory_max = config.get("memory_max_mb", 2048)
        port = config.get("port", 25565)
        jar_path = config.get("jar_path", "server.jar")
        server_dir = config.get("server_dir", f"C:\\minecraft\\servers\\{server_id}")

        jvm_args = " ".join(java_args) if isinstance(java_args, list) else java_args
        job_name = f"{IDENTITY.temp_prefix_new}{server_id}"
        cmd = f"java {jvm_args} -Xms{memory_min}M -Xmx{memory_max}M -jar {jar_path} nogui"

        ps_script = (
            f'$job = Start-Job -Name "{job_name}" '
            f'-ScriptBlock {{ cd "{server_dir}"; {cmd} }}; '
            f"Write-Output $job.Id"
        )

        returncode, stdout = await self._run_powershell(ps_script)
        if returncode != 0:
            raise ProviderError("local_windows", "start", "PowerShell job creation failed")

        job_id = stdout.strip()

        handle = ServerHandle(
            provider="local_windows",
            server_id=server_id,
            external_id=job_id,
            metadata={"server_dir": server_dir, "job_name": job_name},
        )

        return DeploymentResult(
            status=ServerRuntimeStatus.RUNNING,
            address="127.0.0.1",
            port=port,
            pid=None,
            metadata={"handle": str(handle), "job_id": job_id},
        )

    async def stop(self, handle: ServerHandle, force: bool = False) -> None:
        job_id = handle.external_id
        cmd = f"Stop-Job -Id {job_id} -Force" if force else f"Stop-Job -Id {job_id}"
        await self._run_powershell(cmd)

        cleanup = f"Remove-Job -Id {job_id} -Force"
        await self._run_powershell(cleanup)

    async def status(self, handle: ServerHandle) -> ServerRuntimeStatus:
        job_id = handle.external_id
        returncode, stdout = await self._run_powershell(
            f"(Get-Job -Id {job_id} -ErrorAction SilentlyContinue).State",
        )
        if returncode != 0 or not stdout.strip():
            return ServerRuntimeStatus.STOPPED

        state = stdout.strip()
        if state == "Running":
            return ServerRuntimeStatus.RUNNING
        if state == "Failed":
            return ServerRuntimeStatus.ERROR
        return ServerRuntimeStatus.STOPPED

    async def console(self, handle: ServerHandle, tail: int = 100) -> list[str]:
        job_id = handle.external_id
        returncode, stdout = await self._run_powershell(
            f"Receive-Job -Id {job_id} -Keep | Select-Object -Last {tail}",
        )
        if returncode != 0:
            raise ProviderError("local_windows", "console", "Failed to get job output")
        return stdout.splitlines() if stdout else []

    async def execute_command(self, handle: ServerHandle, command: str) -> str:
        job_id = handle.external_id
        escaped = command.replace("'", "''")
        returncode, stdout = await self._run_powershell(
            f'Invoke-Command -JobId {job_id} -ScriptBlock {{ echo "{escaped}" }}',
        )
        if returncode != 0:
            raise ProviderError("local_windows", "execute_command", "PowerShell command failed")
        return stdout

    async def destroy(self, handle: ServerHandle) -> None:
        await self.stop(handle, force=True)

    async def _run_powershell(self, script: str) -> tuple[int, str]:
        proc = await asyncio.create_subprocess_exec(
            "powershell",
            "-NoProfile",
            "-Command",
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode or 0, stdout.decode("utf-8", errors="replace")


def is_windows() -> bool:
    return platform.system() == "Windows"
