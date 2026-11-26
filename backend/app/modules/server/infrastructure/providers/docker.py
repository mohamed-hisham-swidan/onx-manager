from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import posixpath
import re
import shlex
import socket
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.core.allowlist import validate_canonical_relpath
from app.core.config import AppSettings
from app.core.container_hardening import (
    CAP_DROP_ALL_VALUE,
    NO_NEW_PRIVILEGES_VALUE,
    PIDS_LIMIT,
    data_mount_args,
    hardening_args,
    prepare_data_ownership,
    resolve_non_root_user,
    validate_data_only_mounts,
    validate_docker_image,
    validate_network_mode,
)
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
from app.modules.versioning.infrastructure.java_floor import (
    resolve_java_floor_from_mc_version,
    temurin_docker_image_for_java_major,
)

logger = logging.getLogger(__name__)

RCON_DISABLED_MESSAGE = (
    "RCON is disabled in server.properties. Enable RCON in Settings to run console commands."
)

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
    4. POSIX-absolute paths are preserved as POSIX on every platform (never
       re-anchored to the current Windows drive).
    """
    path_str = str(path).strip()
    if not path_str:
        return ""
    if path_str.startswith("/"):
        return posixpath.normpath(path_str)
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
    *,
    java_major: int | None = None,
) -> str:
    """Resolve the appropriate Docker base image based on Minecraft version.

    - Explicit config['image'] takes absolute priority.
    - An explicit ``java_major`` (or ``config['java_major']``) maps through Temurin.
    - Otherwise the deterministic Minecraft Java floor is used.
    """
    cfg = config or {}
    if cfg.get("image") is not None:
        return validate_docker_image(str(cfg["image"]))

    resolved_major = java_major
    if resolved_major is None and cfg.get("java_major") is not None:
        with contextlib.suppress(TypeError, ValueError):
            resolved_major = int(cfg["java_major"])
    if resolved_major is not None:
        return validate_docker_image(temurin_docker_image_for_java_major(resolved_major))

    version_val = cfg.get("minecraft_version") or minecraft_version
    if not version_val:
        return validate_docker_image(AppSettings().docker_default_image)
    return validate_docker_image(
        temurin_docker_image_for_java_major(
            resolve_java_floor_from_mc_version(version_val)
        )
    )


_UNIX_ARGS_TOKEN_RE = re.compile(
    r"@(?:/)?(?:data/)?(libraries/[A-Za-z0-9._+/-]+/unix_args\.txt)"
)


def extract_unix_args_relpath(
    startup_command: Sequence[str] | None = None,
    *,
    unix_args_relpath: str | None = None,
) -> str | None:
    """Return the canonical ``libraries/.../unix_args.txt`` relpath, if any."""
    if unix_args_relpath is not None:
        rel = validate_canonical_relpath(unix_args_relpath.lstrip("/"))
        if not rel.startswith("libraries/") or not rel.endswith("/unix_args.txt"):
            raise ValueError(f"Invalid unix_args relpath: {unix_args_relpath!r}")
        return rel
    for token in startup_command or ():
        match = _UNIX_ARGS_TOKEN_RE.search(str(token))
        if match:
            rel = validate_canonical_relpath(match.group(1))
            if rel.startswith("libraries/") and rel.endswith("/unix_args.txt"):
                return rel
    return None


def _extract_preserved_loader_flags(lc_flags: Sequence[str]) -> list[str]:
    """Preserve essential loader flags (@argfiles and JVM module opens/exports/adds)."""
    preserved: list[str] = []
    i = 0
    flags_list = list(lc_flags)
    while i < len(flags_list):
        token = str(flags_list[i])
        if token.startswith("@") or token.startswith(
            ("--add-opens=", "--add-exports=", "--add-modules=")
        ):
            preserved.append(token)
        elif token in ("--add-opens", "--add-exports", "--add-modules"):
            preserved.append(token)
            if i + 1 < len(flags_list):
                preserved.append(str(flags_list[i + 1]))
                i += 1
        i += 1
    return preserved


def _resolve_jvm_flags(
    launch_config: LaunchConfiguration | None,
    cfg: dict[str, Any] | None,
) -> list[str] | None:
    """Resolve effective JVM flags, prioritizing explicit user ``java_args`` over launch_config."""
    raw_user = cfg.get("java_args") if cfg else None
    user_args: list[str] = []
    if isinstance(raw_user, str):
        if raw_user.strip():
            with contextlib.suppress(ValueError):
                user_args = [tok for tok in shlex.split(raw_user) if tok]
    elif isinstance(raw_user, (list, tuple)):
        user_args = [str(tok).strip() for tok in raw_user if str(tok).strip()]

    lc_args = list(launch_config.jvm_flags) if launch_config and launch_config.jvm_flags else []

    if user_args:
        preserved = _extract_preserved_loader_flags(lc_args)
        combined: list[str] = []
        seen: set[str] = set()
        for tok in [*preserved, *user_args]:
            if tok not in seen:
                combined.append(tok)
                seen.add(tok)
        return combined
    if lc_args:
        return lc_args
    return None


def build_docker_server_cmd(
    startup_command: list[str] | None = None,
    startup_jar: str | None = None,
    jvm_flags: list[str] | None = None,
    memory_min_mb: int = 1024,
    memory_max_mb: int = 2048,
    cpu_cores: int = 0,
    image: str = "",
    force_itzg_entrypoint: bool = False,
    *,
    unix_args_relpath: str | None = None,
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
    # Priority 1 (Argfile launch — ND-4 / OD-v8.4-9).
    resolved_unix_args = extract_unix_args_relpath(
        startup_command, unix_args_relpath=unix_args_relpath
    )
    if resolved_unix_args is not None:
        return [
            "java",
            "@/data/user_jvm_args.txt",
            f"@/data/{resolved_unix_args}",
            "nogui",
        ]

    # Priority 2 (Legacy run.sh / run.bat token in startup_command).
    # Script detection: only from startup_command, never from disk.
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
    user: str,
    cap_drop: list[str],
    security_opt: list[str],
    pids_limit: int,
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
        # P2-6c2 / H-A1: the hardening contract is part of the identity so a
        # pre-hardening container is never silently adopted.
        "user": str(user),
        "cap_drop": sorted(str(c) for c in cap_drop),
        "security_opt": sorted(str(s) for s in security_opt),
        "pids_limit": int(pids_limit),
    }
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _inspect_hardening_compliance(
    info: dict[str, Any],
    *,
    expected_user: str,
    expected_network: str,
) -> tuple[bool, str]:
    """Return whether a running container satisfies the P2-6b / OD-v8.5-6 contract."""
    config = info.get("Config") or {}
    host = info.get("HostConfig") or {}

    actual_user = str(config.get("User") or "").strip()
    if actual_user != expected_user:
        return False, f"user={actual_user or '<unset>'}"

    cap_drop = {str(cap).upper() for cap in (host.get("CapDrop") or [])}
    if CAP_DROP_ALL_VALUE.upper() not in cap_drop:
        return False, "cap-drop=ALL missing"

    security_opt = {str(opt).lower() for opt in (host.get("SecurityOpt") or [])}
    if NO_NEW_PRIVILEGES_VALUE.lower() not in security_opt:
        return False, "no-new-privileges missing"

    raw_pids = host.get("PidsLimit")
    try:
        pids_limit = int(raw_pids) if raw_pids is not None else -1
    except (TypeError, ValueError):
        pids_limit = -1
    if pids_limit != PIDS_LIMIT:
        return False, f"pids-limit={pids_limit}"

    network_mode = str(host.get("NetworkMode") or "").strip().lower()
    if network_mode == "default":
        network_mode = "bridge"
    if network_mode != expected_network.lower():
        return False, f"network={network_mode or '<unset>'}"

    if host.get("Privileged") is True:
        return False, "privileged=true"

    if host.get("ReadonlyRootfs") is True:
        return False, "readonly-rootfs=true"

    data_mounts = 0
    for mount in info.get("Mounts") or []:
        entry = mount if isinstance(mount, dict) else {}
        destination = str(entry.get("Destination") or "")
        source = str(entry.get("Source") or "")
        if "docker.sock" in destination.lower() or "docker.sock" in source.lower():
            return False, "docker.sock mount"
        if destination != "/data":
            return False, f"unexpected mount={destination or '<unset>'}"
        data_mounts += 1
    if data_mounts > 1:
        return False, f"mount-count={data_mounts}"

    return True, "ok"


_RCON_RUNTIME_RELPATH = ".onx-manager/rcon-runtime.json"
_RCON_PORT_SCAN_START = 25575
_RCON_PORT_SCAN_END = 25675
_RCON_PORT_FALLBACK_END = 26000


def is_loopback_port_free(port: int) -> bool:
    """Return True if TCP ``port`` is unbound on both 127.0.0.1 and 0.0.0.0."""
    for host in ("127.0.0.1", "0.0.0.0"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind((host, port))
        except OSError:
            return False
    return True


def allocate_host_rcon_port(
    *,
    game_port: int = 25565,
    preferred_rcon_port: int = 25575,
    reserved_ports: set[int] | None = None,
    check_os: bool = True,
) -> int:
    """Allocate a non-colliding loopback host RCON port.

    Uses a deterministic offset ``25575 + (game_port - 25565)`` when the server's
    configured container RCON port is the default ``25575`` and its game port is
    not ``25565``, then scans ``25575-25675`` (and up to ``26000``) to skip any
    port already claimed by another server or bound on the host OS.
    """
    reserved = set(reserved_ports or ())
    if preferred_rcon_port == 25575 and game_port != 25565:
        offset_candidate = 25575 + (game_port - 25565)
        start_candidate = offset_candidate if 1024 <= offset_candidate <= 65535 else 25575
    else:
        start_candidate = (
            preferred_rcon_port if 1024 <= preferred_rcon_port <= 65535 else 25575
        )

    candidates: list[int] = [start_candidate]
    seen: set[int] = {start_candidate}
    for port in range(_RCON_PORT_SCAN_START, _RCON_PORT_FALLBACK_END + 1):
        if port not in seen:
            candidates.append(port)
            seen.add(port)

    for candidate in candidates:
        if candidate == game_port or candidate in reserved:
            continue
        if check_os and not is_loopback_port_free(candidate):
            continue
        return candidate

    return start_candidate


def _extract_host_rcon_port_from_inspect(
    info: dict[str, Any] | None,
    container_rcon_port: int = 25575,
) -> int | None:
    """Extract the published host RCON port from ``docker inspect`` JSON."""
    if not isinstance(info, dict):
        return None
    net = info.get("NetworkSettings")
    if not isinstance(net, dict):
        return None
    ports = net.get("Ports")
    if not isinstance(ports, dict):
        return None
    bindings = ports.get(f"{container_rcon_port}/tcp")
    if not isinstance(bindings, list):
        return None
    for entry in bindings:
        if not isinstance(entry, dict):
            continue
        raw_port = entry.get("HostPort")
        if raw_port is None:
            continue
        with contextlib.suppress(TypeError, ValueError):
            parsed = int(raw_port)
            if parsed > 0:
                return parsed
    return None


def _read_persisted_rcon_port(server_dir: str | Path) -> int | None:
    """Read the last allocated host RCON port from ``.onx-manager/rcon-runtime.json``."""
    if not server_dir:
        return None
    target = Path(server_dir) / _RCON_RUNTIME_RELPATH
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        raw = data.get("rcon_port")
        if raw is not None:
            port = int(raw)
            if port > 0:
                return port
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    return None


def _persist_rcon_port(
    server_dir: str | Path,
    *,
    host_rcon_port: int,
    container_rcon_port: int,
) -> None:
    """Persist the allocated host RCON port alongside the server identity dir."""
    if not server_dir:
        return
    base = Path(server_dir)
    if not base.is_dir():
        return
    target = base / _RCON_RUNTIME_RELPATH
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "host": "127.0.0.1",
                "rcon_port": int(host_rcon_port),
                "container_rcon_port": int(container_rcon_port),
            },
            indent=2,
        )
        target.write_text(payload, encoding="utf-8")
    except OSError as exc:
        logger.debug("Could not persist RCON runtime port at %s: %s", target, exc)


def _remove_persisted_rcon_port(server_dir: str | Path) -> None:
    if not server_dir:
        return
    target = Path(server_dir) / _RCON_RUNTIME_RELPATH
    with contextlib.suppress(OSError):
        if target.is_file():
            target.unlink()


class DockerProvider(ServerProvider):
    def __init__(self, docker_host: str | None = None) -> None:
        self._docker_host = docker_host
        self._rcon_cache: dict[str, dict[str, Any]] = {}
        self._rcon_info: dict[str, dict[str, Any]] = {}
        self._last_ping_error: str = ""

    def _active_rcon_ports_excluding(self, server_id: str) -> set[int]:
        """Return host RCON ports currently cached for other managed servers."""
        ports: set[int] = set()
        for source in (self._rcon_cache, self._rcon_info):
            for sid, entry in source.items():
                if sid == server_id or not isinstance(entry, dict):
                    continue
                raw = entry.get("port")
                if raw is not None:
                    with contextlib.suppress(TypeError, ValueError):
                        ports.add(int(raw))
        return ports

    async def _live_docker_published_ports_excluding(self, server_id: str) -> set[int]:
        """Return host ports published by other running Docker containers."""
        from app.modules.versioning.infrastructure.port_allocator import (
            parse_docker_published_ports,
        )

        excluded = {
            f"{IDENTITY.temp_prefix_new}{server_id}",
            f"{IDENTITY.temp_prefix_legacy}{server_id}",
        }
        try:
            rc, out = await self._docker_command(
                "ps", "--format", "{{.Names}}\t{{.Ports}}", log_failure=False
            )
        except Exception:
            return set()
        if rc != 0 or not out:
            return set()
        ports: set[int] = set()
        for line in out.splitlines():
            if "\t" in line:
                name, spec = line.split("\t", 1)
                if name.strip() in excluded:
                    continue
            else:
                spec = line
            ports.update(parse_docker_published_ports(spec))
        return ports

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
        image = resolve_docker_image(
            config=cfg, minecraft_version=cfg.get("minecraft_version")
        )
        container_name = f"{IDENTITY.temp_prefix_new}{server_id}"
        port = int(cfg.get("port", 25565))
        memory_min = int(cfg.get("memory_min_mb", 1024))
        memory_max = int(cfg.get("memory_max_mb", 2048))
        # cpu_cores=0 (default) leaves the container CPU-unconstrained; a positive
        # value emits `--cpus <n>` and the matching ActiveProcessorCount JVM flag.
        cpu_cores = int(cfg.get("cpu_cores") or 0)
        cpu_affinity = cfg.get("cpu_affinity")
        if cpu_cores > 0 or cpu_affinity:
            CpuAllocation.validate(cpu_cores, str(cpu_affinity or ""))

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
            assert_inside_root(server_dir, AppSettings().servers_data_dir)

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

        container_uid, container_gid = resolve_non_root_user()
        create_args = ["create", "--name", container_name]

        # Explicit Docker bridge network model (Decision 6). P2-6c2 / H-3:
        # only bridge, none, and panel-owned onx-* networks are accepted so a
        # config can never share the host or another container's namespace.
        raw_network = cfg.get("network")
        network = validate_network_mode(
            "bridge" if raw_network in (None, "") else str(raw_network)
        )
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

        # Companion UDP/TCP ports (e.g., Simple Voice Chat 24454/udp, Geyser 19132/udp, Dynmap 8123/tcp)
        companion_port_specs: list[str] = []
        for cp in cfg.get("companion_ports") or ():
            if not isinstance(cp, dict):
                continue
            try:
                cp_port = int(cp.get("port") or 0)
            except (TypeError, ValueError):
                continue
            if cp_port <= 0 or cp_port > 65535 or cp_port == port:
                continue
            cp_proto = str(cp.get("protocol") or "tcp").strip().lower()
            cp_bind = f"{host_ip}:{cp_port}:{cp_port}" if host_ip else f"{cp_port}:{cp_port}"
            if cp_proto == "both":
                for p_suffix in ("tcp", "udp"):
                    spec = f"{cp_bind}/{p_suffix}"
                    if spec not in companion_port_specs:
                        companion_port_specs.append(spec)
                        create_args.extend(["-p", spec])
            else:
                p_suffix = "udp" if cp_proto == "udp" else "tcp"
                spec = f"{cp_bind}/{p_suffix}"
                if spec not in companion_port_specs:
                    companion_port_specs.append(spec)
                    create_args.extend(["-p", spec])

        # RCON Port: published EXCLUSIVELY to loopback (127.0.0.1) for security (Decision 6).
        # Cross-check cached RCON ports, live Docker published ports, and OS socket probes
        # so multiple servers never collide on 127.0.0.1:25575.
        rcon_port: int | None = None
        container_rcon_port = 25575
        explicit_rcon_port = cfg.get("rcon_port")
        live_docker_ports: set[int] = set()
        reserved_rcon_ports: set[int] = set()
        rcon_enabled = bool(explicit_rcon_port) or (
            props.get("enable-rcon", "").lower() in ("true", "yes", "1")
        )
        if rcon_enabled:
            live_docker_ports = await self._live_docker_published_ports_excluding(server_id)
            reserved_rcon_ports = self._active_rcon_ports_excluding(server_id) | live_docker_ports

        if explicit_rcon_port:
            with contextlib.suppress(ValueError, TypeError):
                rcon_port = int(explicit_rcon_port)
            if rcon_port is not None and (rcon_port in live_docker_ports or rcon_port == port):
                rcon_port = allocate_host_rcon_port(
                    game_port=port,
                    preferred_rcon_port=rcon_port,
                    reserved_ports=reserved_rcon_ports,
                    check_os=True,
                )
        elif props.get("enable-rcon", "").lower() in ("true", "yes", "1"):
            with contextlib.suppress(ValueError, TypeError):
                container_rcon_port = int(props.get("rcon.port", "25575"))
            rcon_port = allocate_host_rcon_port(
                game_port=port,
                preferred_rcon_port=container_rcon_port,
                reserved_ports=reserved_rcon_ports,
                check_os=True,
            )

        rcon_port_arg_idx: int | None = None
        if rcon_port:
            if cfg.get("container_rcon_port") is not None:
                with contextlib.suppress(ValueError, TypeError):
                    container_rcon_port = int(cfg["container_rcon_port"])
            elif props.get("rcon.port"):
                with contextlib.suppress(ValueError, TypeError):
                    container_rcon_port = int(props["rcon.port"])
            elif explicit_rcon_port:
                container_rcon_port = rcon_port

            create_args.extend(["-p", f"127.0.0.1:{rcon_port}:{container_rcon_port}"])
            rcon_port_arg_idx = len(create_args) - 1

        # Resource limits: proportional JVM off-heap headroom (min 768 MB or 25% of heap)
        # plus 512 MB swap headroom to prevent silent kernel OOM-killer SIGKILLs,
        # and bounded json-file log rotation.
        headroom_mb = max(768, int(memory_max * 0.25))
        container_mem_mb = memory_max + headroom_mb
        container_swap_mb = container_mem_mb + 512
        create_args.extend(
            [
                "--memory",
                f"{container_mem_mb}m",
                "--memory-swap",
                f"{container_swap_mb}m",
                "--log-opt",
                "max-size=20m",
                "--log-opt",
                "max-file=3",
            ]
        )

        # CPU allocation & pinning (Decision 4)
        if cpu_cores > 0:
            create_args.extend(["--cpus", str(cpu_cores)])
        if cpu_affinity:
            create_args.extend(["--cpuset-cpus", str(cpu_affinity)])

        # Volume mount & working directory (Decision 3, 7 & 12). Only one bind
        # mount is allowed, and it must target /data.
        host_mount = ""
        if server_dir:
            host_mount = resolve_host_mount_path(server_dir)
            create_args.extend(data_mount_args(server_dir, mount_source=host_mount))

        # Non-root container identity + hardening (P2-6b).
        create_args.extend(hardening_args(container_uid, container_gid))

        if cfg.get("auto_remove", False):
            create_args.append("--rm")

        # Environment variables
        env_vars: dict[str, str] = dict(cfg.get("env_vars") or {})
        if launch_config and launch_config.environment:
            env_vars.update(launch_config.environment)
        # P2-6c2 / M-3: a user-supplied PUID/PGID must never win over the
        # panel-controlled non-root identity. Strip every case variant here and
        # append the authoritative values last (below).
        for key in [k for k in env_vars if str(k).upper() in ("PUID", "PGID")]:
            env_vars.pop(key, None)
        resolved_jvm_flags = _resolve_jvm_flags(launch_config, cfg)

        if "itzg" in image:
            if "VERSION" not in env_vars and cfg.get("minecraft_version"):
                env_vars["VERSION"] = str(cfg["minecraft_version"])
            if "MEMORY" not in env_vars:
                env_vars["MEMORY"] = f"{memory_max}M"
            if "JVM_XX_OPTS" not in env_vars:
                xx_opts = [f"-Xms{memory_min}M"]
                if launch_config is None and resolved_jvm_flags:
                    for flag in resolved_jvm_flags:
                        if not flag.startswith(("-Xms", "-Xmx", "@")) and flag not in xx_opts:
                            xx_opts.append(flag)
                env_vars["JVM_XX_OPTS"] = " ".join(xx_opts)
            if "EULA" not in env_vars:
                env_vars["EULA"] = "TRUE"
            if "SERVER_PORT" not in env_vars:
                env_vars["SERVER_PORT"] = str(container_port)
            # Panel-controlled and appended last so it cannot be overridden.
            env_vars["PUID"] = str(container_uid)
            env_vars["PGID"] = str(container_gid)
        for k, v in env_vars.items():
            create_args.extend(["-e", f"{k}={v}"])

        # Launch translation (Decision 4 & SPEC-2026-09-15-ISOLATED-TEST-BOOT-CONTRACT-01 Step 1)
        startup_cmd: list[str] | None = None
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

        resolved_unix_args = extract_unix_args_relpath(
            startup_cmd, unix_args_relpath=cfg.get("unix_args_relpath")
        )
        server_type = str(cfg.get("server_type") or "")
        argfile_expected = resolved_unix_args is not None or server_type in (
            "forge",
            "neoforge",
            "quilt",
        )
        if resolved_unix_args is None and server_dir and Path(server_dir).is_dir():
            for pattern in (
                "libraries/net/neoforged/neoforge/*/unix_args.txt",
                "libraries/net/minecraftforge/forge/*/unix_args.txt",
                "libraries/org/quiltmc/quilt-loader/*/unix_args.txt",
            ):
                matches = sorted(Path(server_dir).glob(pattern))
                if matches:
                    resolved_unix_args = matches[0].relative_to(Path(server_dir)).as_posix()
                    argfile_expected = True
                    break

        if resolved_unix_args is None and argfile_expected:
            raise ProviderError(
                "docker",
                "start",
                "Required argfile 'libraries/.../unix_args.txt' is missing",
            )

        if resolved_unix_args is not None and server_dir:
            argfile_path = Path(server_dir) / resolved_unix_args
            if not argfile_path.is_file() or argfile_path.stat().st_size <= 0:
                raise ProviderError(
                    "docker",
                    "start",
                    f"Required argfile '{resolved_unix_args}' is missing or empty",
                )

        is_script = False
        if startup_cmd:
            cmd_str = " ".join(startup_cmd)
            if "run.sh" in cmd_str or "run.bat" in cmd_str:
                is_script = True
        elif server_dir and (Path(server_dir) / "run.sh").is_file():
            is_script = True

        if resolved_unix_args is not None and server_dir:
            self._write_user_jvm_args(
                server_dir, memory_min, memory_max, cpu_cores, launch_config, cfg
            )
        elif is_script:
            if not AppSettings().allow_legacy_run_sh:
                raise ProviderError(
                    "docker",
                    "start",
                    "Legacy run.sh execution is disabled and unix_args.txt is missing",
                )
            if server_dir:
                self._write_user_jvm_args(
                    server_dir, memory_min, memory_max, cpu_cores, launch_config, cfg
                )

        server_cmd = build_docker_server_cmd(
            startup_command=startup_cmd,
            startup_jar=resolved_jar,
            jvm_flags=(
                list(resolved_jvm_flags) if resolved_jvm_flags is not None else None
            ),
            memory_min_mb=memory_min,
            memory_max_mb=memory_max,
            cpu_cores=cpu_cores,
            image=image,
            force_itzg_entrypoint=(launch_config is None),
            unix_args_relpath=resolved_unix_args,
        )

        ports_list = [game_port_spec]
        if protocol in ("udp", "tcp"):
            ports_list = [f"{game_port_spec}/{protocol}"]
        elif protocol == "both":
            ports_list = [f"{game_port_spec}/tcp", f"{game_port_spec}/udp"]
        if rcon_port:
            ports_list.append(f"127.0.0.1:{rcon_port}:{container_rcon_port}")
        ports_list.extend(companion_port_specs)

        mounts_list = []
        if server_dir:
            mounts_list.append(f"{host_mount}:/data")

        def _build_fp(eff_ports: list[str]) -> str:
            return _compute_config_fingerprint(
                image=image,
                memory_min=memory_min,
                memory_max=memory_max,
                cpu_cores=cpu_cores,
                cpu_affinity=str(cpu_affinity or ""),
                ports=eff_ports,
                mounts=mounts_list,
                env=env_vars,
                cmd=server_cmd,
                user=f"{container_uid}:{container_gid}",
                cap_drop=[CAP_DROP_ALL_VALUE],
                security_opt=[NO_NEW_PRIVILEGES_VALUE],
                pids_limit=PIDS_LIMIT,
            )

        fingerprint = _build_fp(ports_list)

        fp_label_arg_idx = len(create_args) + 1
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
                    compliant, reason = _inspect_hardening_compliance(
                        existing_info,
                        expected_user=f"{container_uid}:{container_gid}",
                        expected_network=network,
                    )
                    if not compliant:
                        raise ProviderError(
                            "docker",
                            "start",
                            f"Container '{target_container}' is running without the "
                            f"required hardening contract ({reason}); stop or restart "
                            "the server first",
                        )
                    pid = int(state_obj.get("Pid", 0)) if state_obj.get("Pid") else None
                    if not pid or pid <= 0:
                        _, insp_out = await self._docker_command(
                            "inspect", target_container, "--format", "{{.State.Pid}}"
                        )
                        if insp_out.strip().isdigit():
                            pid = int(insp_out.strip())
                    container_ip = await self.get_container_ip(target_container)
                    address = container_ip or get_dynamic_local_ip()

                    live_rcon_port = (
                        _extract_host_rcon_port_from_inspect(existing_info, container_rcon_port)
                        or rcon_port
                        or container_rcon_port
                    )
                    rcon_info_entry = {
                        "host": "127.0.0.1",
                        "port": live_rcon_port,
                        "container_port": container_rcon_port,
                        "password": props.get("rcon.password", ""),
                        "server_dir": server_dir,
                    }
                    self._rcon_info[server_id] = rcon_info_entry
                    self._rcon_cache[server_id] = rcon_info_entry
                    if server_dir and live_rcon_port:
                        _persist_rcon_port(
                            server_dir,
                            host_rcon_port=live_rcon_port,
                            container_rcon_port=container_rcon_port,
                        )

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
                            "ports": {"game": port, "rcon": live_rcon_port},
                            "rcon_port": live_rcon_port,
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

        # Prepare the /data ownership before the non-root container starts.
        # A failed chown (or root-helper fallback) fails closed.
        if server_dir:
            await prepare_data_ownership(
                server_dir,
                uid=container_uid,
                gid=container_gid,
                image=image,
                mount_source=host_mount,
                run_docker=self._ownership_docker_runner,
            )
        validate_data_only_mounts(create_args, image=image)

        returncode, output = await self._docker_command(*create_args)
        if returncode != 0:
            raise ProviderError("docker", "start", f"Container creation failed: {output.strip()}")

        returncode, output = await self._docker_command("start", container_name)
        if (
            returncode != 0
            and rcon_port is not None
            and rcon_port_arg_idx is not None
            and (
                "port is already allocated" in output.lower()
                or "address already in use" in output.lower()
            )
            and f":{rcon_port}" in output
        ):
            # TOCTOU race on host RCON port: cleanly remove failed container,
            # exclude the colliding port, re-allocate, and retry once.
            await self._docker_command("rm", container_name, log_failure=False)
            reserved_rcon_ports.add(rcon_port)
            retry_rcon = allocate_host_rcon_port(
                game_port=port,
                preferred_rcon_port=rcon_port,
                reserved_ports=reserved_rcon_ports,
                check_os=True,
            )
            if retry_rcon != rcon_port:
                logger.warning(
                    "RCON port %d collided during docker start for %s; retrying with %d",
                    rcon_port,
                    server_id,
                    retry_rcon,
                )
                rcon_port = retry_rcon
                new_rcon_spec = f"127.0.0.1:{rcon_port}:{container_rcon_port}"
                create_args[rcon_port_arg_idx] = new_rcon_spec
                updated_ports = [
                    p for p in ports_list if not p.startswith("127.0.0.1:")
                ] + [new_rcon_spec]
                fingerprint = _build_fp(updated_ports)
                create_args[fp_label_arg_idx] = (
                    f"{IDENTITY.docker_label_prefix_new}.config-fingerprint={fingerprint}"
                )
                rc_c, out_c = await self._docker_command(*create_args)
                if rc_c != 0:
                    raise ProviderError(
                        "docker", "start", f"Container creation failed: {out_c.strip()}"
                    )
                returncode, output = await self._docker_command("start", container_name)

        if returncode != 0:
            container_logs: list[str] = []
            rc_logs, log_out = await self._docker_command(
                "logs", "--tail", "100", container_name, log_failure=False
            )
            if rc_logs == 0 and log_out.strip():
                container_logs = [ln for ln in log_out.splitlines() if ln.strip()]
            await self._docker_command("rm", container_name)
            raise ProviderError(
                "docker",
                "start",
                f"Container start failed: {output.strip()}",
                details={"container_logs": container_logs} if container_logs else None,
            )

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
            eff_rcon_port = rcon_port or container_rcon_port
            if rcon_port:
                _persist_rcon_port(
                    server_dir,
                    host_rcon_port=eff_rcon_port,
                    container_rcon_port=container_rcon_port,
                )
            if rcon_pwd:
                entry = {
                    "host": "127.0.0.1",
                    "port": eff_rcon_port,
                    "container_port": container_rcon_port,
                    "password": rcon_pwd,
                    "server_dir": server_dir,
                }
                self._rcon_cache[server_id] = entry
                self._rcon_info[server_id] = entry
        elif rcon_port and cfg.get("rcon_password"):
            entry = {
                "host": "127.0.0.1",
                "port": rcon_port,
                "container_port": container_rcon_port,
                "password": str(cfg["rcon_password"]),
                "server_dir": server_dir,
            }
            self._rcon_cache[server_id] = entry
            self._rcon_info[server_id] = entry

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
                        container_rcon_port = int(props.get("rcon.port", "25575"))
                    except (ValueError, TypeError):
                        container_rcon_port = 25575
                    host_rcon_port: int | None = None
                    if meta.get("rcon_port") is not None:
                        with contextlib.suppress(TypeError, ValueError):
                            host_rcon_port = int(meta["rcon_port"])
                    if host_rcon_port is None:
                        container_name = self._resolve_container_name(handle)
                        if container_name:
                            inspected = await self._inspect_container_json(container_name)
                            host_rcon_port = _extract_host_rcon_port_from_inspect(
                                inspected, container_rcon_port
                            )
                    if host_rcon_port is None:
                        host_rcon_port = _read_persisted_rcon_port(server_dir)
                    resolved_port = host_rcon_port or container_rcon_port
                    if pwd:
                        in_dood = bool(
                            os.environ.get("ONX_HOST_DATA_DIR")
                            or os.environ.get("MCS_HOST_DATA_DIR")
                            or Path("/.dockerenv").exists()
                        )
                        rcon_host = "127.0.0.1"
                        rcon_connect_port = resolved_port
                        if in_dood:
                            cname = self._resolve_container_name(handle)
                            if cname:
                                cip = await self.get_container_ip(cname)
                                if cip:
                                    rcon_host = cip
                                    rcon_connect_port = container_rcon_port
                        entry = {
                            "host": rcon_host,
                            "port": rcon_connect_port,
                            "container_port": container_rcon_port,
                            "password": pwd,
                            "server_dir": server_dir,
                        }
                        self._rcon_cache[handle.server_id] = entry
                        self._rcon_info[handle.server_id] = entry
                        return (rcon_host, rcon_connect_port, pwd)

        return None

    async def resolve_rcon_endpoint(self, handle: ServerHandle) -> tuple[str, int, str] | None:
        """Public accessor for resolved ``(host, host_rcon_port, password)``."""
        return await self._resolve_rcon_credentials(handle)

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

    def _evict_rcon_state(self, handle: ServerHandle) -> None:
        cached = self._rcon_cache.pop(handle.server_id, None)
        self._rcon_info.pop(handle.server_id, None)
        server_dir = (handle.metadata or {}).get("server_dir") or (
            cached.get("server_dir") if isinstance(cached, dict) else None
        )
        if server_dir:
            _remove_persisted_rcon_port(server_dir)

    async def stop(self, handle: ServerHandle, force: bool = False) -> None:
        container_name = self._resolve_container_name(handle)
        if force:
            rc, out = await self._docker_command("kill", container_name)
            if "No such container" in out or "is not running" in out:
                self._evict_rcon_state(handle)
                return
            exited = await self._wait_for_container_exit(container_name, timeout=10.0)
            if not exited:
                raise ProviderError(
                    "docker",
                    "stop",
                    f"Container {container_name} did not exit after docker kill: {out.strip()}",
                )
            self._evict_rcon_state(handle)
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
                self._evict_rcon_state(handle)
                return
            exited = await self._wait_for_container_exit(container_name, timeout=5.0)
            if not exited:
                raise ProviderError(
                    "docker",
                    "stop",
                    f"Container {container_name} still running after docker stop -t 30",
                )
        self._evict_rcon_state(handle)

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
        from datetime import UTC, datetime, timedelta

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

        # Ignore stale logs/latest.log or crash reports from previous runs before this boot
        boot_cutoff: datetime | None = None
        raw_start = meta.get("start_time")
        if isinstance(raw_start, (int, float)) and raw_start > 0:
            with contextlib.suppress(OSError, OverflowError, ValueError):
                boot_cutoff = datetime.fromtimestamp(float(raw_start), tz=UTC)
        if boot_cutoff is None:
            boot_cutoff = datetime.now(UTC) - timedelta(seconds=5)

        async def _get_docker_logs(_since: datetime | None = None) -> list[str]:
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
            log_since=boot_cutoff,
            get_logs_since=_get_docker_logs,
        )
        return result.passed

    async def console(self, handle: ServerHandle, tail: int = 100) -> list[str]:
        container_name = self._resolve_container_name(handle)
        returncode, output = await self._docker_command(
            "logs", "--tail", str(tail), "--timestamps", container_name
        )
        if returncode != 0:
            raise ProviderError("docker", "console", "Failed to get container logs")
        return output.splitlines() if output else []

    def _rcon_disabled_reason(self, handle: ServerHandle) -> str | None:
        """Return a truthful message when RCON is disabled in server.properties."""
        meta = handle.metadata or {}
        if meta.get("rcon_password"):
            return None
        server_dir = meta.get("server_dir") or meta.get("root_path")
        if not server_dir:
            cached = self._rcon_cache.get(handle.server_id)
            if isinstance(cached, dict):
                server_dir = cached.get("server_dir")
        if not server_dir and handle.server_id:
            candidate = Path(AppSettings().servers_data_dir).resolve() / handle.server_id
            if candidate.is_dir():
                server_dir = str(candidate)
        if not server_dir:
            return None
        props_path = Path(server_dir) / "server.properties"
        if not props_path.is_file():
            return None
        props = self._read_server_properties_file(props_path)
        enabled = props.get("enable-rcon", "").strip().lower() in ("true", "yes", "1")
        if not enabled or not props.get("rcon.password", "").strip():
            return RCON_DISABLED_MESSAGE
        return None

    async def execute_command(self, handle: ServerHandle, command: str) -> str:
        disabled = self._rcon_disabled_reason(handle)
        if disabled:
            raise ProviderError("docker", "execute_command", disabled)
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
                    "RCON command execution failed for %s on %s:%d: %s",
                    handle.server_id,
                    host,
                    port,
                    exc,
                )
                container_alive = False
                with contextlib.suppress(Exception):
                    container_alive = await self.status(handle) == ServerRuntimeStatus.RUNNING
                if container_alive:
                    raise ProviderError(
                        "docker",
                        "execute_command",
                        "Server console is still starting up (RCON is not ready yet). "
                        "Wait for 'Done!' in the logs and try again.",
                    ) from exc
                raise ProviderError(
                    "docker",
                    "execute_command",
                    "Server container is not running or RCON is unavailable.",
                ) from exc

        container_alive = False
        with contextlib.suppress(Exception):
            container_alive = await self.status(handle) == ServerRuntimeStatus.RUNNING
        if container_alive:
            raise ProviderError(
                "docker",
                "execute_command",
                "Server console is still starting up (RCON is not ready yet). "
                "Wait for 'Done!' in the logs and try again.",
            )
        raise ProviderError(
            "docker",
            "execute_command",
            "RCON is not enabled or server container is not running.",
        )

    async def write_exec_input(
        self,
        handle: ServerHandle,
        input_data: str,
        _interactive: bool = False,
    ) -> str:
        clean = input_data.rstrip("\r\n")
        return await self.execute_command(handle, clean)

    async def destroy(self, handle: ServerHandle) -> None:
        cached = self._rcon_cache.pop(handle.server_id, None)
        self._rcon_info.pop(handle.server_id, None)
        server_dir = (handle.metadata or {}).get("server_dir") or (
            cached.get("server_dir") if isinstance(cached, dict) else None
        )
        if server_dir:
            _remove_persisted_rcon_port(server_dir)
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
        image = validate_docker_image(image)
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

    async def _docker_exec(
        self,
        *args: str,
        log_failure: bool = True,
        merge_stderr: bool = False,
        timeout: float | None = 60.0,
    ) -> tuple[int, str]:
        """Execute docker CLI command with tokenized arguments without shell interpolation."""
        cmd = ["docker"]
        if self._docker_host:
            cmd.extend(["-H", self._docker_host])
        cmd.extend(args)

        effective_merge_stderr = merge_stderr or (bool(args) and args[0] == "logs")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT if effective_merge_stderr else asyncio.subprocess.PIPE,
        )
        try:
            if timeout is not None and (not args or args[0] != "pull"):
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            else:
                stdout, stderr = await proc.communicate()
        except TimeoutError:
            with contextlib.suppress(Exception):
                proc.kill()
            with contextlib.suppress(Exception):
                await proc.wait()
            redacted_cmd = _redact_docker_args(cmd)
            logger.warning("Docker command timed out after %.1fs: %s", timeout or 0, " ".join(redacted_cmd))
            return 124, f"Docker command timed out after {timeout:.0f}s"

        out_msg = stdout.decode("utf-8", errors="replace") if stdout else ""
        err_msg = stderr.decode("utf-8", errors="replace") if stderr else ""
        if proc.returncode != 0 and log_failure:
            redacted_cmd = _redact_docker_args(cmd)
            redacted_err = _redact_secrets_in_text(err_msg or out_msg)
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

    async def _ownership_docker_runner(self, args: list[str]) -> tuple[int, str]:
        """Run the short-lived ownership helper through this provider's host."""
        return await self._docker_command(*args)

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

        extra_flags = _resolve_jvm_flags(launch_config, cfg) or []

        for flag in extra_flags:
            if (
                flag not in lines
                and not flag.startswith("@")
                and not any(
                    flag.startswith(p) for p in ("-Xms", "-Xmx", "-XX:ActiveProcessorCount")
                )
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

