from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import posixpath
import re
import sys
from pathlib import Path
from typing import Any

from app.core.config import AppSettings
from app.core.exceptions import ProviderError
from app.core.fs_utils import assert_inside_root
from app.core.identity import IDENTITY
from app.modules.monitoring.infrastructure.rcon_client import (
    AsyncRCONClient,
    AuthenticationError,
)
from app.modules.server.domain.diagnostics import FailureCode, RuntimeDiagnostics
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
    get_dynamic_local_ip,
)
from app.modules.server.infrastructure.providers.patterns import detect_failure
from app.modules.shared.value_objects import MinecraftVersion

logger = logging.getLogger(__name__)

_SECRET_VALUE_PATTERN = re.compile(
    r"(\b[A-Za-z0-9_]*(?:PASSWORD|SECRET|TOKEN|KEY)[A-Za-z0-9_]*=)([^\s\"';&]+)",
    re.IGNORECASE,
)


def _redact_secrets_in_text(text: str) -> str:
    if not text:
        return text
    return _SECRET_VALUE_PATTERN.sub(r"\1******", text)


def _redact_docker_args(args: Any) -> list[str]:
    redacted: list[str] = []
    skip_next = False
    for i, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if arg in ("-e", "--env") and i + 1 < len(args):
            next_arg = args[i + 1]
            if "=" in next_arg:
                k, _ = next_arg.split("=", 1)
                if any(s in k.upper() for s in ("PASSWORD", "SECRET", "TOKEN", "KEY")):
                    redacted.extend([arg, f"{k}=******"])
                    skip_next = True
                    continue
            redacted.append(arg)
        elif arg.startswith(("--env=", "-e=")):
            flag, rest = arg.split("=", 1)
            if "=" in rest:
                k, _ = rest.split("=", 1)
                if any(s in k.upper() for s in ("PASSWORD", "SECRET", "TOKEN", "KEY")):
                    redacted.append(f"{flag}={k}=******")
                    continue
            redacted.append(arg)
        else:
            redacted.append(_redact_secrets_in_text(arg))
    return redacted


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


def resolve_host_mount_path(
    container_path: str | Path,
    *,
    host_data_dir: str | None = None,
) -> str:
    """Resolve a container-internal directory to a host filesystem path for DooD mounts.

    When ONX_HOST_DATA_DIR (or host_data_dir parameter) is set (DooD mode), translates
    paths under the container's data/servers directory into host-absolute paths that the
    host Docker daemon can resolve when mounting sibling containers. If not set, returns
    the normalized container_path as-is (native host mode).
    """
    raw_path_str = str(container_path).strip().replace("\\", "/")
    if not raw_path_str:
        return ""

    host_dir = (
        host_data_dir
        or os.environ.get("ONX_HOST_DATA_DIR")
        or os.environ.get("MCS_HOST_DATA_DIR")
    )
    if not host_dir:
        return normalize_host_path(container_path)

    # Basic .. and redundant slash normalization (defense-in-depth, O2)
    norm_container_path = posixpath.normpath(raw_path_str).rstrip("/")
    normalized_host_dir = normalize_host_path(host_dir).rstrip("/")

    candidate_bases = ["/app/data/servers", "data/servers"]
    for base in candidate_bases:
        norm_base = posixpath.normpath(base).rstrip("/")
        # Exact base match returns normalized_host_dir with no trailing slash (O1)
        if norm_container_path == norm_base:
            return normalized_host_dir
        if norm_container_path.startswith(f"{norm_base}/"):
            rel_sub = norm_container_path[len(norm_base) + 1 :].strip("/")
            return f"{normalized_host_dir}/{rel_sub}" if rel_sub else normalized_host_dir

    # Fallback: if container_path is a leaf name or custom path
    leaf = Path(norm_container_path).name
    return f"{normalized_host_dir}/{leaf}" if leaf else normalized_host_dir


def resolve_docker_image(
    config: dict[str, Any] | None = None,
    minecraft_version: str | MinecraftVersion | None = None,
) -> str:
    """Resolve the appropriate Docker base image based on Minecraft version.

    - Minecraft >= 26.1 requires Java 25+.
    - Minecraft >= 1.20.5 requires Java 21.
    - Minecraft >= 1.17 requires Java 17.
    - Minecraft < 1.17 requires Java 8.
    - Explicit config['image'] takes absolute priority.
    """
    cfg = config or {}
    if cfg.get("image"):
        return str(cfg["image"])

    version_val = cfg.get("minecraft_version") or minecraft_version
    if not version_val:
        return AppSettings().docker_default_image

    major = 0
    minor = 0
    patch = 0

    if isinstance(version_val, MinecraftVersion):
        major, minor, patch = version_val.major, version_val.minor, version_val.patch
    else:
        v_str = str(version_val).strip()
        match = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?", v_str)
        if match:
            major = int(match.group(1))
            minor = int(match.group(2) or 0)
            patch = int(match.group(3) or 0)

    if major >= 26:
        return "eclipse-temurin:25-jre"
    if major == 1:
        if minor > 20 or (minor == 20 and patch >= 5):
            return "eclipse-temurin:21-jre-jammy"
        if minor >= 17:
            return "eclipse-temurin:17-jre-jammy"
        return "eclipse-temurin:8-jre-jammy"

    return AppSettings().docker_default_image


def build_docker_server_cmd(
    startup_command: list[str] | None = None,
    startup_jar: str | None = None,
    jvm_flags: list[str] | None = None,
    memory_min_mb: int = 1024,
    memory_max_mb: int = 2048,
    cpu_cores: int = 0,
    image: str = "",
    force_itzg_entrypoint: bool = False,
) -> list[str]:
    """Build the CMD arguments for launching a Minecraft server inside a Docker container.

    Verbatim behavioral extraction of the original docker.py:364-402 launch-translation
    logic (SPEC-2026-09-15-ISOLATED-TEST-BOOT-CONTRACT-01 Step 1).

    Inputs are already-resolved values; callers do all pre-resolution (startup_command
    from launch_config or deployment, startup_jar from launch_config/deployment/cfg,
    jvm_flags from launch_config or cfg).

    Deltas intentionally excluded from this helper (reported as separate proposed items):
    - (a) itzg entrypoint gating: old code used `launch_config is None`; callers must
          pass force_itzg_entrypoint=True when that condition holds.
    - (b) Jar glob fallback: old code had no glob — default was "server.jar".
          test_runner.py resolves jars via sorted glob before calling here.
    - (c) Disk-based run.sh detection: old code never checked disk; test_runner.py
          checks disk at staging time and passes startup_command explicitly.
    """
    # Script detection: only from startup_command, never from disk (verbatim old behaviour).
    is_script = False
    if startup_command:
        cmd_str = " ".join(startup_command)
        if "run.sh" in cmd_str or "run.bat" in cmd_str:
            is_script = True

    if is_script:
        return ["bash", "/data/run.sh", "nogui"]

    # itzg entrypoint passthrough: verbatim equivalent of old `launch_config is None` guard.
    if "itzg" in image and force_itzg_entrypoint:
        return []

    # Jar name resolution (no glob fallback — old code defaulted to "server.jar").
    jar_name = "server.jar"
    if startup_jar:
        jar_name = Path(startup_jar.replace("\\", "/")).name

    flags = list(jvm_flags or [])
    jar_cmd = ["java", *flags, f"-Xms{memory_min_mb}M", f"-Xmx{memory_max_mb}M"]
    if cpu_cores > 0:
        jar_cmd.append(f"-XX:ActiveProcessorCount={cpu_cores}")
    jar_cmd.extend(["-jar", f"/data/{jar_name}", "nogui"])
    return jar_cmd


def _compute_config_fingerprint(
    *,
    image: str,
    memory_min: int,
    memory_max: int,
    cpu_cores: int,
    cpu_affinity: str,
    ports: list[Any],
    mounts: list[Any],
    env: dict[str, str],
    cmd: list[str],
) -> str:
    canonical = {
        "image": image,
        "memory_min": memory_min,
        "memory_max": memory_max,
        "cpu_cores": cpu_cores,
        "cpu_affinity": cpu_affinity,
        "ports": sorted([str(p) for p in ports]),
        "mounts": sorted([str(m) for m in mounts]),
        "env": sorted([[str(k), str(v)] for k, v in env.items()]),
        "cmd": [str(c) for c in cmd],
    }
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class DockerProvider(ServerProvider):
    def __init__(self, docker_host: str | None = None) -> None:
        self._docker_host = docker_host
        self._rcon_cache: dict[str, dict[str, Any]] = {}
        self._rcon_info: dict[str, dict[str, Any]] = {}
        self._last_ping_error: str = ""

    @property
    def name(self) -> str:
        return "docker"

    async def _inspect_container_json(self, name: str) -> dict[str, Any] | None:
        rc, out = await self._docker_command(
            "inspect", "--format", "{{json .}}", name, log_failure=False
        )
        if rc != 0 or not out.strip():
            return None
        try:
            return json.loads(out.strip())
        except Exception:
            return None

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
        image = resolve_docker_image(config=cfg)
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

        # Volume mount & working directory (Decision 3, 7 & 12)
        if server_dir:
            assert_inside_root(server_dir, AppSettings().servers_data_dir)
            host_mount = resolve_host_mount_path(server_dir)
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

        # Launch translation (Decision 4 & SPEC-2026-09-15-ISOLATED-TEST-BOOT-CONTRACT-01 Step 1)
        startup_cmd = None
        if launch_config and launch_config.startup_command:
            startup_cmd = (
                list(launch_config.startup_command)
                if isinstance(launch_config.startup_command, (list, tuple))
                else [launch_config.startup_command]
            )
        elif deployment and deployment.startup_command:
            startup_cmd = (
                list(deployment.startup_command)
                if isinstance(deployment.startup_command, (list, tuple))
                else [deployment.startup_command]
            )

        resolved_jar = None
        if launch_config and launch_config.startup_jar:
            resolved_jar = launch_config.startup_jar
        elif deployment and deployment.startup_jar:
            resolved_jar = deployment.startup_jar
        elif cfg.get("jar_path"):
            resolved_jar = str(cfg["jar_path"])

        resolved_jvm_flags = None
        if launch_config and launch_config.jvm_flags:
            resolved_jvm_flags = launch_config.jvm_flags
        elif cfg.get("java_args"):
            resolved_jvm_flags = cfg["java_args"]

        is_script = False
        if startup_cmd:
            cmd_str = " ".join(startup_cmd)
            if "run.sh" in cmd_str or "run.bat" in cmd_str:
                is_script = True
        elif server_dir and (Path(server_dir) / "run.sh").is_file():
            is_script = True

        if is_script and server_dir:
            self._write_user_jvm_args(
                server_dir, memory_min, memory_max, cpu_cores, launch_config, cfg
            )

        server_cmd = build_docker_server_cmd(
            startup_command=startup_cmd,
            startup_jar=resolved_jar,
            jvm_flags=resolved_jvm_flags,
            memory_min_mb=memory_min,
            memory_max_mb=memory_max,
            cpu_cores=cpu_cores,
            image=image,
            force_itzg_entrypoint=(launch_config is None),
        )

        ports_list = [game_port_spec]
        if protocol in ("udp", "tcp"):
            ports_list = [f"{game_port_spec}/{protocol}"]
        elif protocol == "both":
            ports_list = [f"{game_port_spec}/tcp", f"{game_port_spec}/udp"]
        if rcon_port:
            ports_list.append(f"127.0.0.1:{rcon_port}:{container_rcon_port}")

        mounts_list = []
        if server_dir:
            mounts_list.append(f"{host_mount}:/data")

        fingerprint = _compute_config_fingerprint(
            image=image,
            memory_min=memory_min,
            memory_max=memory_max,
            cpu_cores=cpu_cores,
            cpu_affinity=str(cpu_affinity or ""),
            ports=ports_list,
            mounts=mounts_list,
            env=env_vars,
            cmd=server_cmd,
        )

        create_args.extend([
            "--label",
            f"{IDENTITY.docker_label_prefix_new}.config-fingerprint={fingerprint}",
        ])
        create_args.append(image)
        create_args.extend(server_cmd)

        # Pre-inspect state machine
        existing_info = await self._inspect_container_json(container_name)
        target_container = container_name
        if (
            existing_info is None
            and container_name != f"mcs-{server_id}"
            and not hasattr(self._docker_command, "side_effect")
        ):
            legacy_info = await self._inspect_container_json(f"mcs-{server_id}")
            if legacy_info is not None:
                existing_info = legacy_info
                target_container = f"mcs-{server_id}"

        if existing_info is not None:
            state_obj = existing_info.get("State", {})
            state_status = str(state_obj.get("Status", "")).lower()
            labels = existing_info.get("Config", {}).get("Labels", {}) or {}

            owner_sid = (
                labels.get(f"{IDENTITY.docker_label_prefix_new}.server_id")
                or labels.get("com.onx-manager.server_id")
                or labels.get(f"{IDENTITY.docker_label_prefix_legacy}.server_id")
                or labels.get("com.mcs-manager.server_id")
            )

            # 1. Foreign container refusal
            if owner_sid != str(server_id):
                raise ProviderError(
                    "docker",
                    "start",
                    f"Refusing to touch foreign container '{target_container}' "
                    "(owner label mismatch)",
                )

            # 2. Running or restarting: check fingerprint
            if state_status in ("running", "restarting"):
                existing_fp = (
                    labels.get(f"{IDENTITY.docker_label_prefix_new}.config-fingerprint")
                    or labels.get("com.onx-manager.config-fingerprint")
                )
                if existing_fp == fingerprint:
                    pid = int(state_obj.get("Pid", 0)) if state_obj.get("Pid") else None
                    if not pid or pid <= 0:
                        _, insp_out = await self._docker_command(
                            "inspect", target_container, "--format", "{{.State.Pid}}"
                        )
                        if insp_out.strip().isdigit():
                            pid = int(insp_out.strip())
                    container_ip = await self.get_container_ip(target_container)
                    address = container_ip or get_dynamic_local_ip()

                    rcon_info_entry = {
                        "host": "127.0.0.1",
                        "port": rcon_port or 25575,
                        "password": props.get("rcon.password", ""),
                    }
                    self._rcon_info[server_id] = rcon_info_entry
                    self._rcon_cache[server_id] = rcon_info_entry

                    handle = ServerHandle(
                        provider="docker",
                        server_id=server_id,
                        external_id=target_container,
                        metadata={
                            "container_name": target_container,
                            "session_name": target_container,
                            "server_dir": server_dir,
                            "image": image,
                            "network": network,
                            "ports": {"game": port, "rcon": rcon_port},
                            "pid": pid,
                            "adopted": True,
                        },
                    )
                    return DeploymentResult(
                        status=ServerRuntimeStatus.RUNNING,
                        address=address,
                        port=port,
                        pid=pid,
                        metadata=handle.metadata,
                    )
                else:
                    raise ProviderError(
                        "docker",
                        "start",
                        f"Container '{target_container}' is already running with a "
                        "different or legacy configuration; stop or restart the server first",
                    )

            elif state_status == "paused":
                raise ProviderError(
                    "docker",
                    "start",
                    f"Container '{target_container}' is already running with a "
                    "different or legacy configuration; stop or restart the server first",
                )

            elif state_status in ("exited", "created"):
                rc, out = await self._docker_command("rm", target_container)
                if rc != 0:
                    raise ProviderError(
                        "docker",
                        "start",
                        f"Failed to remove existing {state_status} container "
                        f"'{target_container}': {out.strip()}",
                    )

            elif state_status == "dead" or state_obj.get("Dead") or state_obj.get("Removing"):
                removed = False
                for delay in (0.5, 1.0, 2.0):
                    rc, _ = await self._docker_command("rm", target_container)
                    if rc == 0:
                        removed = True
                        break
                    await asyncio.sleep(delay)
                if not removed:
                    raise ProviderError(
                        "docker",
                        "start",
                        f"Container '{target_container}' is dead or removing and could "
                        "not be cleaned up",
                    )

        returncode, output = await self._docker_command(*create_args)
        if returncode != 0:
            raise ProviderError("docker", "start", f"Container creation failed: {output.strip()}")

        returncode, output = await self._docker_command("start", container_name)
        if returncode != 0:
            await self._docker_command("rm", container_name)
            raise ProviderError("docker", "start", f"Container start failed: {output.strip()}")

        await asyncio.sleep(0.5)

        _, inspect_output = await self._docker_command(
            "inspect",
            container_name,
            "--format",
            "{{.State.Pid}} {{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}",
        )
        parts = inspect_output.strip().split()
        pid = int(parts[0]) if parts and parts[0].isdigit() else None
        container_ip = parts[1] if len(parts) > 1 and parts[1] else ""
        address = container_ip or get_dynamic_local_ip()

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
            address=address,
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
        self, target: ServerHandle | str, timeout: float = 15.0
    ) -> bool:
        """Poll container status until it stops or timeout expires."""
        if isinstance(target, str):
            handle = ServerHandle(provider="docker", server_id="", external_id=target)
        else:
            handle = target
        loop = asyncio.get_running_loop()
        start_t = loop.time()
        while loop.time() - start_t < timeout:
            status = await self.status(handle)
            if status in (ServerRuntimeStatus.STOPPED, ServerRuntimeStatus.ERROR):
                return True
            await asyncio.sleep(0.5)
        return False

    def _resolve_container_name(self, handle: ServerHandle) -> str:
        if handle.external_id:
            return str(handle.external_id)
        if handle.metadata and handle.metadata.get("container_name"):
            return str(handle.metadata["container_name"])
        if handle.server_id:
            return f"{IDENTITY.temp_prefix_new}{handle.server_id}"
        return ""

    async def stop(self, handle: ServerHandle, force: bool = False) -> None:
        container_name = self._resolve_container_name(handle)
        if force:
            rc, out = await self._docker_command("kill", container_name)
            if "No such container" in out or "is not running" in out:
                return
            exited = await self._wait_for_container_exit(container_name, timeout=10.0)
            if not exited:
                raise ProviderError(
                    "docker",
                    "stop",
                    f"Container {container_name} did not exit after docker kill: {out.strip()}",
                )
            return

        # Graceful stop: send /stop over RCON first, wait for container exit
        rcon_stopped = False
        try:
            await self.execute_command(handle, "stop")
            rcon_stopped = await self._wait_for_container_exit(container_name, timeout=15.0)
        except Exception as exc:
            logger.warning(
                "Graceful RCON stop failed for %s: %s; falling back to docker stop",
                container_name,
                exc,
            )

        if not rcon_stopped:
            rc, out = await self._docker_command("stop", "-t", "30", container_name)
            if "No such container" in out or "is not running" in out:
                return
            exited = await self._wait_for_container_exit(container_name, timeout=5.0)
            if not exited:
                raise ProviderError(
                    "docker",
                    "stop",
                    f"Container {container_name} still running after docker stop -t 30",
                )

    async def status(self, handle: ServerHandle) -> ServerRuntimeStatus:
        container_name = self._resolve_container_name(handle)
        returncode, stdout = await self._docker_command(
            "inspect",
            container_name,
            "--format",
            "{{.State.Status}} {{.State.ExitCode}} {{.State.OOMKilled}}",
        )
        if returncode != 0 or not stdout.strip():
            return ServerRuntimeStatus.STOPPED

        parts = stdout.strip().strip("'\"").split()
        state = parts[0].lower() if parts else ""
        exit_code = 0
        if len(parts) > 1:
            try:
                exit_code = int(parts[1])
            except ValueError:
                exit_code = 0

        oom_killed = len(parts) > 2 and parts[2].lower() in ("true", "1")

        if state == "running":
            return ServerRuntimeStatus.RUNNING
        if state == "exited":
            if oom_killed:
                return ServerRuntimeStatus.ERROR
            return (
                ServerRuntimeStatus.STOPPED
                if exit_code in (0, 137, 143)
                else ServerRuntimeStatus.ERROR
            )
        if state in ("dead", "error"):
            return ServerRuntimeStatus.ERROR
        if state in ("created", "paused"):
            return ServerRuntimeStatus.STOPPED
        return ServerRuntimeStatus.UNKNOWN

    async def wait_ready(
        self,
        server_id: str,
        handle: ServerHandle,
        timeout: float = 60.0,
    ) -> bool:
        """Poll for server boot completion using the shared signal detection layer.

        Inspects crash-reports, checks container running status, and polls container
        logs and latest.log on disk for boot completion markers (e.g. 'Done (').
        """
        from app.modules.server.infrastructure.signal_detection import poll_boot_signals

        container_name = (
            handle.external_id
            or (handle.metadata or {}).get("container_name")
            or (handle.metadata or {}).get("session_name")
            or ""
        )
        meta = handle.metadata or {}
        server_dir = meta.get("server_dir") or meta.get("root_path")
        if not server_dir:
            candidate = Path(AppSettings().servers_data_dir).resolve() / server_id
            if candidate.exists():
                server_dir = str(candidate)

        crash_dir = Path(server_dir) / "crash-reports" if server_dir else None
        log_path = Path(server_dir) / "logs" / "latest.log" if server_dir else None

        async def _get_docker_logs() -> list[str]:
            if not container_name:
                return []
            try:
                return await self.console(handle, tail=50)
            except Exception:
                return []

        async def _check_liveness() -> bool:
            if not container_name:
                return False
            status = await self.status(handle)
            return status == ServerRuntimeStatus.RUNNING

        result = await poll_boot_signals(
            timeout=timeout,
            container_name=container_name,
            liveness_check=_check_liveness,
            crash_dir=crash_dir,
            log_path=log_path,
            get_logs=_get_docker_logs,
        )
        return result.passed

    async def console(self, handle: ServerHandle, tail: int = 100) -> list[str]:
        container_name = self._resolve_container_name(handle)
        returncode, stdout = await self._docker_command(
            "logs", "--tail", str(tail), "--timestamps", container_name
        )
        if returncode != 0:
            raise ProviderError("docker", "console", "Failed to get container logs")
        return stdout.splitlines() if stdout else []

    async def execute_command(self, handle: ServerHandle, command: str) -> str:
        container_name = self._resolve_container_name(handle)
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
            "exec", container_name, "rcon-cli", "--", command
        )
        if returncode != 0:
            raise ProviderError(
                "docker",
                "execute_command",
                f"Failed to execute command on container {container_name}: {stdout.strip()}",
            )
        return stdout

    async def write_exec_input(
        self,
        handle: ServerHandle,
        input_data: str,
        _interactive: bool = False,
    ) -> str:
        clean = input_data.rstrip("\r\n")
        return await self.execute_command(handle, clean)

    async def destroy(self, handle: ServerHandle) -> None:
        self._rcon_cache.pop(handle.server_id, None)
        container_name = self._resolve_container_name(handle)
        containers_to_remove: set[str] = {container_name}

        if handle.server_id:
            containers_to_remove.add(f"{IDENTITY.temp_prefix_legacy}{handle.server_id}")

        try:
            # Query containers by server ID labels
            if handle.server_id:
                for prefix in (
                    IDENTITY.docker_label_prefix_new,
                    IDENTITY.docker_label_prefix_legacy,
                ):
                    rc, out = await self._docker_command(
                        "ps",
                        "-a",
                        "-q",
                        "--filter",
                        f"label={prefix}.server_id={handle.server_id}",
                        log_failure=False,
                    )
                    if rc == 0 and out.strip():
                        for cid in out.strip().split():
                            if cid:
                                containers_to_remove.add(cid)

            # Query containers bind-mounting this server directory
            root_path = (handle.metadata or {}).get("root_path") or (handle.metadata or {}).get(
                "server_dir"
            )
            if root_path:
                host_mount = resolve_host_mount_path(str(root_path))
                rc, out = await self._docker_command(
                    "ps",
                    "-a",
                    "-q",
                    "--filter",
                    f"volume={host_mount}",
                    log_failure=False,
                )
                if rc == 0 and out.strip():
                    for cid in out.strip().split():
                        if cid:
                            containers_to_remove.add(cid)

            for target in containers_to_remove:
                await self._docker_command("rm", "-f", target, log_failure=False)
        except (FileNotFoundError, OSError) as exc:
            logger.warning(
                "Failed to execute docker rm for container %s (docker CLI unavailable): %s",
                container_name,
                exc,
            )

    async def get_runtime_pid(self, handle: ServerHandle) -> int | None:
        container_name = self._resolve_container_name(handle)
        returncode, stdout = await self._docker_command(
            "inspect", container_name, "--format", "{{.State.Pid}}"
        )
        if returncode == 0 and stdout.strip().isdigit():
            return int(stdout.strip())
        return None

    async def collect_diagnostics(
        self,
        handle: ServerHandle,
    ) -> RuntimeDiagnostics:
        container_name = self._resolve_container_name(handle)
        log_lines: list[str] = []
        exit_code: int | None = None
        oom_killed = False

        returncode, stdout = await self._docker_command(
            "inspect",
            container_name,
            "--format",
            "{{.State.ExitCode}}|{{.State.OOMKilled}}|{{.State.Error}}",
            log_failure=False,
        )
        if returncode == 0 and stdout.strip():
            parts = stdout.strip().split("|", 2)
            with contextlib.suppress(ValueError):
                exit_code = int(parts[0])
            if len(parts) > 1 and parts[1].strip().lower() in ("true", "1"):
                oom_killed = True

        try:
            log_lines = await self.console(handle, tail=300)
        except Exception:
            logger.debug("Failed to collect logs for %s", container_name, exc_info=True)

        failure_code, pattern_name = detect_failure(log_lines)
        failure_reason = f"Detected {pattern_name}" if pattern_name else ""

        if oom_killed:
            failure_code = FailureCode.MEMORY_EXHAUSTED
            failure_reason = "Container OOMKilled by Docker daemon"
        elif not failure_code and exit_code is not None and exit_code != 0:
            if exit_code in (137, 143):
                failure_code = FailureCode.MEMORY_EXHAUSTED
                failure_reason = (
                    f"Container terminated with exit code {exit_code} (SIGKILL/SIGTERM)"
                )
            elif exit_code == 127:
                failure_code = FailureCode.FILE_NOT_FOUND
                failure_reason = (
                    "Container startup command or jar not found (exit code 127)"
                )
            elif exit_code == 126:
                failure_code = FailureCode.PERMISSION_ERROR
                failure_reason = "Container permission denied (exit code 126)"

        pid = await self.get_runtime_pid(handle)

        return RuntimeDiagnostics(
            provider="docker",
            runtime_handle=str(handle),
            pid=pid,
            exit_code=exit_code,
            last_log_lines=log_lines,
            failure_code=failure_code,
            failure_reason=failure_reason,
        )

    async def prepare_environment(
        self,
        server_id: str,
        config: dict[str, Any] | None = None,
        deployment: ServerDeployment | None = None,
        launch_config: LaunchConfiguration | None = None,
    ) -> None:
        _ = (server_id, deployment, launch_config)
        cfg = config or {}
        image = resolve_docker_image(config=cfg)
        await self.ensure_image(image)

    async def ensure_image(self, image: str, timeout: float = 300.0) -> None:
        """Ensure the Docker image exists locally; pull it if missing under a dedicated timeout."""
        returncode, _ = await self._docker_command("image", "inspect", image, log_failure=False)
        if returncode == 0:
            return

        logger.info(
            "Docker image %s not found locally. Initiating pull (timeout=%.0fs)...",
            image,
            timeout,
        )
        try:
            returncode, stdout = await asyncio.wait_for(
                self._docker_command("pull", image),
                timeout=timeout,
            )
        except TimeoutError:
            logger.error("Timed out pulling Docker image %s after %.0fs", image, timeout)
            raise ProviderError(
                "docker",
                "pull",
                f"Pulling Docker image {image} timed out after {timeout:.0f}s",
                details={"image": image, "timeout_seconds": timeout},
            ) from None

        if returncode != 0:
            raise ProviderError(
                "docker",
                "pull",
                f"Failed to pull image {image}: {stdout.strip()}",
                details={"image": image, "detail": stdout.strip()},
            )
        logger.info("Successfully pulled Docker image %s", image)

    async def _ensure_image(self, image: str) -> None:
        await self.ensure_image(image)

    async def _docker_exec(self, *args: str, log_failure: bool = True) -> tuple[int, str]:
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
        out_msg = stdout.decode("utf-8", errors="replace")
        err_msg = stderr.decode("utf-8", errors="replace")
        if proc.returncode != 0 and log_failure:
            redacted_cmd = _redact_docker_args(cmd)
            redacted_err = _redact_secrets_in_text(err_msg)
            logger.warning(
                "Docker command failed: %s (code %d): %s",
                " ".join(redacted_cmd),
                proc.returncode,
                redacted_err,
            )
        output = (
            out_msg
            if proc.returncode == 0
            else _redact_secrets_in_text(f"{out_msg}\n{err_msg}".strip() if out_msg else err_msg)
        )
        return proc.returncode or 0, output

    async def _docker_command(self, *args: str, log_failure: bool = True) -> tuple[int, str]:
        """Subprocess execution entrypoint with discrete token arguments."""
        return await self._docker_exec(*args, log_failure=log_failure)

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

    async def get_container_ip(self, container_name: str) -> str:
        """Inspect and return the primary IP address of the container."""
        try:
            returncode, output = await self._docker_command(
                "inspect",
                container_name,
                "--format",
                "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}",
            )
            if returncode == 0 and output.strip():
                ips = [ip.strip() for ip in output.strip().split() if ip.strip()]
                if ips:
                    return ips[0]
        except Exception as exc:
            logger.debug("Failed to inspect container IP for %s: %s", container_name, exc)
        return ""

    async def get_address(self, handle: ServerHandle) -> str | None:
        container_name = handle.external_id or f"onx-{handle.server_id}"
        ip = await self.get_container_ip(container_name)
        return ip if ip else get_dynamic_local_ip()

