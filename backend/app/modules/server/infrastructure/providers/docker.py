from __future__ import annotations

import asyncio
import shlex
from typing import Any

from app.core.exceptions import ProviderError
from app.core.identity import IDENTITY
from app.modules.server.domain.value_objects import (
    LaunchConfiguration,
    ServerDeployment,
)
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

    async def start(
        self,
        server_id: str,
        config: dict[str, Any] | None = None,
        deployment: ServerDeployment | None = None,
        launch_config: LaunchConfiguration | None = None,
    ) -> DeploymentResult:
        _ = (deployment, launch_config)
        cfg = config or {}
        image = cfg.get("image", "itzg/minecraft-server:latest")
        container_name = f"{IDENTITY.temp_prefix_new}{server_id}"
        port = cfg.get("port", 25565)
        memory_min = cfg.get("memory_min_mb", 1024)
        memory_max = cfg.get("memory_max_mb", 2048)
        world_dir = cfg.get("world_dir", "")
        version = cfg.get("minecraft_version", "LATEST")

        await self._ensure_image(image)

        label_flags = [
            f"--label {IDENTITY.docker_label_prefix_new}.managed=true",
            f"--label {IDENTITY.docker_label_prefix_new}.server_id={shlex.quote(server_id)}",
            f"--label {IDENTITY.docker_label_prefix_new}.runtime=docker",
        ]

        env_flags = [
            f"-e VERSION={shlex.quote(str(version))}",
            f"-e MEMORY={shlex.quote(f'{memory_max}M')}",
            f"-e JVM_XX_OPTS={shlex.quote(f'-Xms{memory_min}M')}",
        ]

        volume_flags = []
        if world_dir:
            volume_flags.append(f"-v {shlex.quote(world_dir)}:/data/world")

        port_flag = f"-p {port}:25565"

        rm_flag = "--rm" if cfg.get("auto_remove", False) else ""

        create_cmd = (
            f"create --name {shlex.quote(container_name)} "
            f"{' '.join(label_flags)} "
            f"{' '.join(env_flags)} "
            f"{' '.join(volume_flags)} "
            f"{port_flag} "
            f"{rm_flag} "
            f"{shlex.quote(image)}"
        )

        returncode, _ = await self._docker_command(create_cmd)
        if returncode != 0:
            raise ProviderError("docker", "start", "Container creation failed")

        returncode, _ = await self._docker_command(f"start {shlex.quote(container_name)}")
        if returncode != 0:
            await self._docker_command(f"rm {shlex.quote(container_name)}")
            raise ProviderError("docker", "start", "Container start failed")

        await asyncio.sleep(0.5)

        _, inspect_output = await self._docker_command(
            f"inspect {shlex.quote(container_name)} --format '{{{{.State.Pid}}}}'",
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
            await self._docker_command(f"kill {shlex.quote(container_name)}")
        else:
            await self.execute_command(handle, "stop")
            await asyncio.sleep(2)
            await self._docker_command(f"stop {shlex.quote(container_name)}")

    async def status(self, handle: ServerHandle) -> ServerRuntimeStatus:
        container_name = handle.external_id
        returncode, stdout = await self._docker_command(
            f"inspect {shlex.quote(container_name)} --format '{{{{.State.Status}}}}' 2>/dev/null",
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
            f"logs --tail {tail} --timestamps {shlex.quote(container_name)}",
        )
        if returncode != 0:
            raise ProviderError("docker", "console", "Failed to get container logs")
        return stdout.splitlines() if stdout else []

    async def execute_command(self, handle: ServerHandle, command: str) -> str:
        container_name = handle.external_id
        escaped = command.replace("'", "'\\''")
        returncode, stdout = await self._docker_command(
            f"exec {shlex.quote(container_name)} rcon-cli '{escaped}'",
        )
        if returncode != 0:
            raise ProviderError("docker", "execute_command", "docker exec failed")
        return stdout

    async def destroy(self, handle: ServerHandle) -> None:
        container_name = handle.external_id
        await self._docker_command(f"rm -f {shlex.quote(container_name)}")

    async def get_runtime_pid(self, handle: ServerHandle) -> int | None:
        container_name = handle.external_id
        returncode, stdout = await self._docker_command(
            f"inspect {shlex.quote(container_name)} --format '{{{{.State.Pid}}}}' 2>/dev/null",
        )
        if returncode == 0 and stdout.strip().isdigit():
            return int(stdout.strip())
        return None

    async def _ensure_image(self, image: str) -> None:
        returncode, _ = await self._docker_command(
            f"image inspect {shlex.quote(image)} 2>/dev/null"
        )
        if returncode != 0:
            returncode, stdout = await self._docker_command(f"pull {shlex.quote(image)}")
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
