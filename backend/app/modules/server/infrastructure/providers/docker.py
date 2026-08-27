from __future__ import annotations

import asyncio
from typing import Any

from app.core.exceptions import ProviderError
from app.core.identity import IDENTITY
from app.modules.server.infrastructure.providers.base import (
    DeploymentResult,
    ServerHandle,
    ServerProvider,
    ServerRuntimeStatus,
)


class DockerProvider(ServerProvider):
    def __init__(self, docker_host: str | None = None) -> None:
        self._docker_host = docker_host

    @property
    def provider_type(self) -> str:
        return "docker"

    def capabilities(self) -> list[str]:
        return ["process", "console", "exec"]

    async def ping(self) -> bool:
        returncode, _ = await self._docker_command("info --format '{{.OSType}}'")
        return returncode == 0

    async def start(self, server_id: str, config: dict[str, Any]) -> DeploymentResult:
        image = config.get("image", "itzg/minecraft-server:latest")
        container_name = f"{IDENTITY.temp_prefix_new}{server_id}"
        port = config.get("port", 25565)
        memory_min = config.get("memory_min_mb", 1024)
        memory_max = config.get("memory_max_mb", 2048)
        world_dir = config.get("world_dir", "")
        version = config.get("minecraft_version", "LATEST")

        await self._ensure_image(image)

        label_flags = [
            f"--label {IDENTITY.docker_label_prefix_new}.managed=true",
            f"--label {IDENTITY.docker_label_prefix_new}.server_id={server_id}",
            f"--label {IDENTITY.docker_label_prefix_new}.runtime=docker",
        ]

        env_flags = [
            f"-e VERSION={version}",
            f"-e MEMORY={memory_max}M",
            f"-e JVM_XX_OPTS='-Xms{memory_min}M'",
        ]

        volume_flags = []
        if world_dir:
            volume_flags.append(f"-v {world_dir}:/data/world")

        port_flag = f"-p {port}:25565"

        rm_flag = "--rm" if config.get("auto_remove", False) else ""

        create_cmd = (
            f"create --name {container_name} "
            f"{' '.join(label_flags)} "
            f"{' '.join(env_flags)} "
            f"{' '.join(volume_flags)} "
            f"{port_flag} "
            f"{rm_flag} "
            f"{image}"
        )

        returncode, _ = await self._docker_command(create_cmd)
        if returncode != 0:
            raise ProviderError("docker", "start", "Container creation failed")

        returncode, _ = await self._docker_command(f"start {container_name}")
        if returncode != 0:
            await self._docker_command(f"rm {container_name}")
            raise ProviderError("docker", "start", "Container start failed")

        await asyncio.sleep(0.5)

        _, inspect_output = await self._docker_command(
            f"inspect {container_name} --format '{{{{.State.Pid}}}}'",
        )
        pid = int(inspect_output.strip()) if inspect_output.strip().isdigit() else None

        handle = ServerHandle(
            provider="docker",
            server_id=server_id,
            external_id=container_name,
            metadata={"image": image},
        )

        return DeploymentResult(
            status=ServerRuntimeStatus.RUNNING,
            address="127.0.0.1",
            port=port,
            pid=pid,
            metadata={"container_name": container_name, "image": image},
        )

    async def stop(self, handle: ServerHandle, force: bool = False) -> None:
        container_name = handle.external_id
        if force:
            await self._docker_command(f"kill {container_name}")
        else:
            await self.execute_command(handle, "stop")
            await asyncio.sleep(2)
            await self._docker_command(f"stop {container_name}")

    async def status(self, handle: ServerHandle) -> ServerRuntimeStatus:
        container_name = handle.external_id
        returncode, stdout = await self._docker_command(
            f"inspect {container_name} --format '{{{{.State.Status}}}}' 2>/dev/null",
        )
        if returncode != 0 or not stdout.strip():
            return ServerRuntimeStatus.STOPPED

        state = stdout.strip()
        if state == "running":
            return ServerRuntimeStatus.RUNNING
        if state in ("exited", "dead"):
            return ServerRuntimeStatus.ERROR
        return ServerRuntimeStatus.UNKNOWN

    async def console(self, handle: ServerHandle, tail: int = 100) -> list[str]:
        container_name = handle.external_id
        returncode, stdout = await self._docker_command(
            f"logs --tail {tail} --timestamps {container_name}",
        )
        if returncode != 0:
            raise ProviderError("docker", "console", "Failed to get container logs")
        return stdout.splitlines() if stdout else []

    async def execute_command(self, handle: ServerHandle, command: str) -> str:
        container_name = handle.external_id
        escaped = command.replace("'", "'\\''")
        returncode, stdout = await self._docker_command(
            f"exec {container_name} rcon-cli '{escaped}'",
        )
        if returncode != 0:
            raise ProviderError("docker", "execute_command", "docker exec failed")
        return stdout

    async def destroy(self, handle: ServerHandle) -> None:
        container_name = handle.external_id
        await self._docker_command(f"rm -f {container_name}")

    async def get_runtime_pid(self, handle: ServerHandle) -> int | None:
        container_name = handle.external_id
        returncode, stdout = await self._docker_command(
            f"inspect {container_name} --format '{{{{.State.Pid}}}}' 2>/dev/null",
        )
        if returncode == 0 and stdout.strip().isdigit():
            return int(stdout.strip())
        return None

    async def _ensure_image(self, image: str) -> None:
        returncode, _ = await self._docker_command(f"image inspect {image} 2>/dev/null")
        if returncode != 0:
            returncode, stdout = await self._docker_command(f"pull {image}")
            if returncode != 0:
                raise ProviderError("docker", "pull", f"Failed to pull image {image}: {stdout}")

    async def _docker_command(self, args: str) -> tuple[int, str]:
        cmd = f"docker {args}"
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        output = stdout.decode("utf-8", errors="replace")
        return proc.returncode or 0, output
