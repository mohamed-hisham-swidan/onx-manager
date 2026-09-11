from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
from pathlib import Path
from typing import Any

from app.core.config import AppSettings
from app.core.exceptions import ProviderError
from app.core.identity import IDENTITY
from app.modules.monitoring.infrastructure.rcon_client import (
    AsyncRCONClient,
    AuthenticationError,
)
from app.modules.server.domain.value_objects import (
    CpuAllocation,
    LaunchConfiguration,
    ServerDeployment,
)
from app.modules.server.infrastructure.providers.base import (
    DeploymentResult,
    ServerHandle,
    ServerProvider,
    ServerRuntimeStatus,
)

logger = logging.getLogger(__name__)


def normalize_host_path(path: str | Path) -> str:
    """Normalize a host filesystem path for Docker CLI volume mounts and arguments.

    Ensures:
    1. Windows backslashes ('\\') are converted to forward slashes ('/').
    2. Windows drive letters (e.g. 'C:/...' or 'd:/...') preserve forward slashes.
    3. Relative paths are resolved to absolute paths.
    4. POSIX paths are resolved to absolute canonical paths.
    """
    path_str = str(path).strip()
    if not path_str:
        return ""
    if sys.platform == "win32":
        return Path(path_str).resolve().as_posix()
    # On non-Windows platforms (e.g. Linux CI or test suites simulating Windows paths):
    if len(path_str) >= 2 and path_str[1] == ":" and path_str[0].isalpha():
        return path_str.replace("\\", "/")
    return Path(path_str).resolve().as_posix()


class DockerProvider(ServerProvider):
    def __init__(self, docker_host: str | None = None) -> None:
        self._docker_host = docker_host
        self._rcon_cache: dict[str, dict[str, Any]] = {}
        self._last_ping_error: str = ""

    @property
    def last_ping_error(self) -> str:
        """Return the diagnostic error message from the most recent ping() failure."""
        return self._last_ping_error

    def _read_server_properties_file(self, path: Path) -> dict[str, str]:
        """Read Minecraft server.properties into a dictionary."""
        result: dict[str, str] = {}
        if not path.exists():
            return result
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    result[k.strip()] = v.strip()
        except OSError as exc:
            logger.debug("Failed to read server properties at %s: %s", path, exc)
        return result

    @property
    def provider_type(self) -> str:
        return "docker"

    def capabilities(self) -> list[str]:
        return ["process", "console", "exec"]

    async def ping(self) -> bool:
        try:
            returncode, stdout = await self._docker_command("info", "--format", "{{.OSType}}")
        except Exception as exc:
            self._last_ping_error = f"Docker daemon is unreachable: {exc}"
            logger.warning("Docker ping failed: %s", exc)
            return False

        if returncode != 0:
            self._last_ping_error = (
                "Docker daemon is unreachable. Ensure Docker Desktop or dockerd is running."
            )
            logger.warning("Docker ping failed: daemon is unreachable (code %d)", returncode)
            return False

        ostype = stdout.strip().strip("'\"").lower()
        if ostype != "linux":
            self._last_ping_error = (
                f"Docker daemon is running in '{ostype}' containers mode. "
                "ONX Manager requires Docker Desktop with WSL2 backend in Linux containers mode "
                "(switch via Docker Desktop tray menu -> 'Switch to Linux containers...')."
            )
            logger.warning(
                "Docker ping failed: daemon OSType is '%s'. "
                "Linux containers mode via WSL2 is required.",
                ostype,
            )
            return False

        self._last_ping_error = ""
        return True

    async def ping_detailed(self) -> tuple[bool, str]:
        """Verify Docker daemon reachability and return a detailed diagnostic message."""
        ok = await self.ping()
        return ok, self._last_ping_error or "ok"

    async def start(
        self,
        server_id: str,
        config: dict[str, Any] | None = None,
        deployment: ServerDeployment | None = None,
        launch_config: LaunchConfiguration | None = None,
    ) -> DeploymentResult:
        cfg = config or {}
        default_img = AppSettings().docker_default_image
        image = str(cfg.get("image") or default_img)
        container_name = f"{IDENTITY.temp_prefix_new}{server_id}"
        port = int(cfg.get("port", 25565))
        memory_min = int(cfg.get("memory_min_mb", 1024))
        memory_max = int(cfg.get("memory_max_mb", 2048))
        cpu_cores = int(cfg.get("cpu_cores") or 0)
        cpu_affinity = cfg.get("cpu_affinity")
        if cpu_cores > 0 or cpu_affinity:
            CpuAllocation.validate(cpu_cores, cpu_affinity)

        # Whole-directory volume mount contract (Decision 3) & Windows normalization (Decision 7)
        server_dir = ""
        if deployment and deployment.root_path:
            server_dir = deployment.server_directory()
        elif cfg.get("server_dir"):
            server_dir = str(cfg["server_dir"])
        elif cfg.get("world_dir"):
            server_dir = str(cfg["world_dir"])

        if server_dir:
            server_dir = normalize_host_path(server_dir)

        # Read server.properties if available for port & RCON detection
        props: dict[str, str] = {}
        if server_dir:
            props_file = Path(server_dir) / "server.properties"
            if props_file.exists():
                props = self._read_server_properties_file(props_file)

        # Container port resolution (Decision 6)
        container_port = port
        if cfg.get("container_port") is not None:
            with contextlib.suppress(ValueError, TypeError):
                container_port = int(cfg["container_port"])
        elif "server-port" in props:
            with contextlib.suppress(ValueError, TypeError):
                container_port = int(props["server-port"])

        await self._ensure_image(image)

        create_args = ["create", "--name", container_name]

        # Explicit Docker bridge network model (Decision 6)
        network = str(cfg.get("network", "bridge"))
        create_args.extend(["--network", network])

        # Ownership labels
        create_args.extend([
            "--label", f"{IDENTITY.docker_label_prefix_new}.managed=true",
            "--label", f"{IDENTITY.docker_label_prefix_new}.server_id={server_id}",
            "--label", f"{IDENTITY.docker_label_prefix_new}.runtime=docker",
        ])

        # Published ports (Decision 6)
        # Game port: published externally so host exposure tools (playit, cloudflared, UPnP)
        # and direct clients reach the container via host published port.
        host_ip = str(cfg["host_ip"]) if cfg.get("host_ip") else None
        game_port_spec = (
            f"{host_ip}:{port}:{container_port}" if host_ip else f"{port}:{container_port}"
        )
        protocol = str(cfg.get("protocol", "")).lower()
        if protocol in ("udp", "tcp"):
            create_args.extend(["-p", f"{game_port_spec}/{protocol}"])
        elif protocol == "both":
            create_args.extend(["-p", f"{game_port_spec}/tcp", "-p", f"{game_port_spec}/udp"])
        else:
            create_args.extend(["-p", game_port_spec])

        # RCON Port: published EXCLUSIVELY to loopback (127.0.0.1) for security (Decision 6)
        rcon_port: int | None = None
        container_rcon_port = 25575
        if cfg.get("rcon_port"):
            with contextlib.suppress(ValueError, TypeError):
                rcon_port = int(cfg["rcon_port"])
        elif props.get("enable-rcon", "").lower() in ("true", "yes", "1"):
            with contextlib.suppress(ValueError, TypeError):
                rcon_port = int(props.get("rcon.port", "25575"))

        if rcon_port:
            if cfg.get("container_rcon_port") is not None:
                with contextlib.suppress(ValueError, TypeError):
                    container_rcon_port = int(cfg["container_rcon_port"])
            elif props.get("rcon.port"):
                with contextlib.suppress(ValueError, TypeError):
                    container_rcon_port = int(props["rcon.port"])
            else:
                container_rcon_port = rcon_port

            create_args.extend(["-p", f"127.0.0.1:{rcon_port}:{container_rcon_port}"])

        # Resource limits: memory limit with 512MB headroom (Spec §6)
        container_mem_mb = memory_max + 512
        create_args.extend(["--memory", f"{container_mem_mb}m"])

        # CPU allocation & pinning (Decision 4)
        if cpu_cores > 0:
            create_args.extend(["--cpus", str(cpu_cores)])
        if cpu_affinity:
            create_args.extend(["--cpuset-cpus", str(cpu_affinity)])

        # Volume mount & working directory (Decision 3 & 7)
        if server_dir:
            host_mount = server_dir
            create_args.extend(["-v", f"{host_mount}:/data", "-w", "/data"])

        # Linux user permissions to prevent host file permission lockouts (Decision 3)
        if hasattr(os, "getuid") and hasattr(os, "getgid") and sys.platform != "win32":
            uid, gid = os.getuid(), os.getgid()
            if "itzg" in image:
                create_args.extend(["-e", f"PUID={uid}", "-e", f"PGID={gid}"])
            else:
                create_args.extend(["--user", f"{uid}:{gid}"])

        if cfg.get("auto_remove", False):
            create_args.append("--rm")

        # Environment variables
        env_vars: dict[str, str] = dict(cfg.get("env_vars") or {})
        if launch_config and launch_config.environment:
            env_vars.update(launch_config.environment)
        if "itzg" in image:
            if "VERSION" not in env_vars and cfg.get("minecraft_version"):
                env_vars["VERSION"] = str(cfg["minecraft_version"])
            if "MEMORY" not in env_vars:
                env_vars["MEMORY"] = f"{memory_max}M"
            if "JVM_XX_OPTS" not in env_vars:
                env_vars["JVM_XX_OPTS"] = f"-Xms{memory_min}M"
            if "EULA" not in env_vars:
                env_vars["EULA"] = "TRUE"
            if "SERVER_PORT" not in env_vars:
                env_vars["SERVER_PORT"] = str(container_port)
        for k, v in env_vars.items():
            create_args.extend(["-e", f"{k}={v}"])

        create_args.append(image)

        # Launch translation (Decision 4)
        is_script = False
        if launch_config and launch_config.startup_command:
            cmd_str = " ".join(launch_config.startup_command)
            if "run.sh" in cmd_str or "run.bat" in cmd_str:
                is_script = True
        elif deployment and deployment.startup_command:
            if "run.sh" in deployment.startup_command or "run.bat" in deployment.startup_command:
                is_script = True

        if is_script:
            if server_dir:
                self._write_user_jvm_args(
                    server_dir, memory_min, memory_max, cpu_cores, launch_config, cfg
                )
            create_args.extend(["bash", "/data/run.sh", "nogui"])
        else:
            if "itzg" in image and launch_config is None:
                pass  # Use default itzg entrypoint configured via env vars
            else:
                startup_jar = "server.jar"
                if launch_config and launch_config.startup_jar:
                    startup_jar = Path(launch_config.startup_jar.replace("\\", "/")).name
                elif deployment and deployment.startup_jar:
                    startup_jar = Path(deployment.startup_jar.replace("\\", "/")).name
                elif cfg.get("jar_path"):
                    startup_jar = Path(str(cfg["jar_path"]).replace("\\", "/")).name

                jvm_flags: list[str] = []
                if launch_config and launch_config.jvm_flags:
                    jvm_flags.extend(launch_config.jvm_flags)
                elif cfg.get("java_args"):
                    jvm_flags.extend(cfg["java_args"])

                jar_cmd = ["java", *jvm_flags, f"-Xms{memory_min}M", f"-Xmx{memory_max}M"]
                if cpu_cores > 0:
                    jar_cmd.append(f"-XX:ActiveProcessorCount={cpu_cores}")
                jar_cmd.extend(["-jar", f"/data/{startup_jar}", "nogui"])
                create_args.extend(jar_cmd)

        returncode, output = await self._docker_command(*create_args)
        if returncode != 0 and ("Conflict" in output or "already in use" in output):
            await self._docker_command("rm", "-f", container_name)
            returncode, output = await self._docker_command(*create_args)
        if returncode != 0:
            raise ProviderError("docker", "start", f"Container creation failed: {output.strip()}")

        returncode, output = await self._docker_command("start", container_name)
        if returncode != 0:
            await self._docker_command("rm", container_name)
            raise ProviderError("docker", "start", f"Container start failed: {output.strip()}")

        await asyncio.sleep(0.5)

        _, inspect_output = await self._docker_command(
            "inspect", container_name, "--format", "{{.State.Pid}}"
        )
        pid = int(inspect_output.strip()) if inspect_output.strip().isdigit() else None

        handle = ServerHandle(
            provider="docker",
            server_id=server_id,
            external_id=container_name,
            metadata={"image": image},
        )

        if server_dir:
            rcon_pwd = props.get("rcon.password", "")
            if rcon_pwd:
                eff_rcon_port = rcon_port or 25575
                with contextlib.suppress(ValueError, TypeError):
                    eff_rcon_port = int(props.get("rcon.port", str(eff_rcon_port)))
                self._rcon_cache[server_id] = {
                    "host": "127.0.0.1",
                    "port": eff_rcon_port,
                    "password": rcon_pwd,
                    "server_dir": server_dir,
                }
        elif rcon_port and cfg.get("rcon_password"):
            self._rcon_cache[server_id] = {
                "host": "127.0.0.1",
                "port": rcon_port,
                "password": str(cfg["rcon_password"]),
                "server_dir": server_dir,
            }

        return DeploymentResult(
            status=ServerRuntimeStatus.RUNNING,
            address="127.0.0.1",
            port=port,
            pid=pid,
            metadata={
                "handle": str(handle),
                "session_name": container_name,
                "container_name": container_name,
                "image": image,
                "server_dir": server_dir,
                "rcon_port": rcon_port,
                "port": port,
                "container_port": container_port,
                "network": network,
            },
        )

    async def _resolve_rcon_credentials(
        self, handle: ServerHandle
    ) -> tuple[str, int, str] | None:
        """Resolve RCON host, port, and password for a server handle."""
        meta = handle.metadata or {}
        if meta.get("rcon_password"):
            port = int(meta.get("rcon_port", 25575))
            host = str(meta.get("rcon_host", "127.0.0.1"))
            return (host, port, str(meta["rcon_password"]))

        if handle.server_id in self._rcon_cache:
            cached = self._rcon_cache[handle.server_id]
            if cached.get("password"):
                return (
                    str(cached.get("host", "127.0.0.1")),
                    int(cached.get("port", 25575)),
                    str(cached["password"]),
                )

        server_dir = meta.get("server_dir") or self._rcon_cache.get(
            handle.server_id, {}
        ).get("server_dir")
        if not server_dir:
            from app.core.config import AppSettings

            candidate = Path(AppSettings().servers_data_dir).resolve() / handle.server_id
            if candidate.exists():
                server_dir = str(candidate)

        if not server_dir:
            returncode, stdout = await self._docker_command(
                "inspect", handle.external_id, "--format", "{{json .Mounts}}"
            )
            if returncode == 0 and stdout.strip():
                try:
                    import json

                    mounts = json.loads(stdout.strip())
                    for m in mounts:
                        if m.get("Destination") == "/data" and m.get("Source"):
                            server_dir = m["Source"]
                            break
                except Exception:
                    pass

        if server_dir:
            server_dir = normalize_host_path(server_dir)
            props_file = Path(server_dir) / "server.properties"
            if props_file.exists():
                props = self._read_server_properties_file(props_file)
                if props.get("enable-rcon", "").lower() in ("true", "1", "yes"):
                    pwd = props.get("rcon.password", "")
                    try:
                        port = int(props.get("rcon.port", "25575"))
                    except (ValueError, TypeError):
                        port = 25575
                    if pwd:
                        self._rcon_cache[handle.server_id] = {
                            "host": "127.0.0.1",
                            "port": port,
                            "password": pwd,
                            "server_dir": server_dir,
                        }
                        return ("127.0.0.1", port, pwd)

        return None

    async def _wait_for_container_exit(
        self, handle: ServerHandle, timeout: float = 15.0
    ) -> bool:
        """Poll container status until it stops or timeout expires."""
        loop = asyncio.get_running_loop()
        start_t = loop.time()
        while loop.time() - start_t < timeout:
            status = await self.status(handle)
            if status in (ServerRuntimeStatus.STOPPED, ServerRuntimeStatus.ERROR):
                return True
            await asyncio.sleep(0.5)
        return False

    async def stop(self, handle: ServerHandle, force: bool = False) -> None:
        container_name = handle.external_id
        if force:
            await self._docker_command("kill", container_name)
            return

        # Graceful stop: send /stop over RCON first, wait for container exit
        rcon_stopped = False
        try:
            await self.execute_command(handle, "stop")
            rcon_stopped = await self._wait_for_container_exit(handle, timeout=15.0)
        except Exception as exc:
            logger.warning(
                "Graceful RCON stop failed for %s: %s; falling back to docker stop",
                container_name,
                exc,
            )

        if not rcon_stopped:
            await self._docker_command("stop", "-t", "30", container_name)

    async def status(self, handle: ServerHandle) -> ServerRuntimeStatus:
        container_name = handle.external_id
        returncode, stdout = await self._docker_command(
            "inspect", container_name, "--format", "{{.State.Status}}"
        )
        if returncode != 0 or not stdout.strip():
            return ServerRuntimeStatus.STOPPED

        state = stdout.strip().strip("'\"").lower()
        if state == "running":
            return ServerRuntimeStatus.RUNNING
        if state in ("exited", "dead"):
            return ServerRuntimeStatus.ERROR
        return ServerRuntimeStatus.UNKNOWN

    async def console(self, handle: ServerHandle, tail: int = 100) -> list[str]:
        container_name = handle.external_id
        returncode, stdout = await self._docker_command(
            "logs", "--tail", str(tail), "--timestamps", container_name
        )
        if returncode != 0:
            raise ProviderError("docker", "console", "Failed to get container logs")
        return stdout.splitlines() if stdout else []

    async def execute_command(self, handle: ServerHandle, command: str) -> str:
        container_name = handle.external_id
        rcon_creds = await self._resolve_rcon_credentials(handle)
        if rcon_creds:
            host, port, password = rcon_creds
            try:
                client = AsyncRCONClient(
                    host=host, port=port, password=password, timeout=5.0
                )
                await client.connect()
                try:
                    clean_cmd = command.lstrip("/") if command.startswith("/") else command
                    return await client.send_command(clean_cmd)
                finally:
                    await client.close()
            except AuthenticationError as exc:
                logger.error(
                    "RCON authentication failed for server %s (port %d)",
                    handle.server_id,
                    port,
                )
                raise ProviderError(
                    "docker", "execute_command", f"RCON authentication failed: {exc}"
                ) from exc
            except Exception as exc:
                logger.warning(
                    "RCON command execution failed for %s: %s; attempting fallback",
                    handle.server_id,
                    exc,
                )

        # Fallback Method per Spec §5.5: docker exec {container_name} rcon-cli "{command}"
        returncode, stdout = await self._docker_command(
            "exec", container_name, "rcon-cli", command
        )
        if returncode != 0:
            raise ProviderError(
                "docker",
                "execute_command",
                f"Failed to execute command on container {container_name}: {stdout.strip()}",
            )
        return stdout

    async def destroy(self, handle: ServerHandle) -> None:
        self._rcon_cache.pop(handle.server_id, None)
        container_name = handle.external_id or f"{IDENTITY.temp_prefix_new}{handle.server_id}"
        try:
            await self._docker_command("rm", "-f", container_name)
        except (FileNotFoundError, OSError) as exc:
            logger.warning(
                "Failed to execute docker rm for container %s (docker CLI unavailable): %s",
                container_name,
                exc,
            )

    async def get_runtime_pid(self, handle: ServerHandle) -> int | None:
        container_name = handle.external_id
        returncode, stdout = await self._docker_command(
            "inspect", container_name, "--format", "{{.State.Pid}}"
        )
        if returncode == 0 and stdout.strip().isdigit():
            return int(stdout.strip())
        return None

    async def _ensure_image(self, image: str) -> None:
        returncode, _ = await self._docker_command("image", "inspect", image)
        if returncode != 0:
            returncode, stdout = await self._docker_command("pull", image)
            if returncode != 0:
                raise ProviderError("docker", "pull", f"Failed to pull image {image}: {stdout}")

    async def _docker_exec(self, *args: str) -> tuple[int, str]:
        """Execute docker CLI command with tokenized arguments without shell interpolation."""
        cmd = ["docker"]
        if self._docker_host:
            cmd.extend(["-H", self._docker_host])
        cmd.extend(args)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        output = stdout.decode("utf-8", errors="replace")
        if proc.returncode != 0:
            err_msg = stderr.decode("utf-8", errors="replace")
            logger.warning(
                "Docker command failed: %s (code %d): %s",
                " ".join(cmd),
                proc.returncode,
                err_msg,
            )
        return proc.returncode or 0, output

    async def _docker_command(self, *args: str) -> tuple[int, str]:
        """Subprocess execution entrypoint with discrete token arguments."""
        return await self._docker_exec(*args)

    def _write_user_jvm_args(
        self,
        server_dir: str,
        memory_min: int,
        memory_max: int,
        cpu_cores: int,
        launch_config: LaunchConfiguration | None = None,
        cfg: dict[str, Any] | None = None,
    ) -> None:
        """Generate or patch user_jvm_args.txt with memory, CPU, and custom flags."""
        target_path = Path(server_dir) / "user_jvm_args.txt"
        lines = [
            f"-Xms{memory_min}M",
            f"-Xmx{memory_max}M",
        ]
        if cpu_cores > 0:
            lines.append(f"-XX:ActiveProcessorCount={cpu_cores}")

        extra_flags: list[str] = []
        if launch_config and launch_config.jvm_flags:
            extra_flags.extend(launch_config.jvm_flags)
        elif cfg and cfg.get("java_args"):
            extra_flags.extend(cfg["java_args"])

        for flag in extra_flags:
            if flag not in lines and not any(
                flag.startswith(p) for p in ("-Xms", "-Xmx", "-XX:ActiveProcessorCount")
            ):
                lines.append(flag)

        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not write user_jvm_args.txt at %s: %s", target_path, exc)
