"""Shared Docker container hardening for every container spawn path (P2-6b).

The helper centralises the security contract used by regular server containers,
installer containers, isolated test containers, and pooled bot runners:

* ``--cap-drop=ALL``
* ``--security-opt=no-new-privileges:true``
* ``--pids-limit=2048``
* ``--user <uid>:<gid>`` with a non-root fallback of ``1000:1000``
* exactly one bind mount, targeting ``/data``, when server data is mounted

It also prepares recursive ``/data`` ownership before a non-root server
container starts. When the panel process cannot ``chown`` the tree directly, a
short-lived named root helper container performs the change with only the
capabilities ``chown`` needs, no network, and a bounded pid count. The helper is
always removed (``docker rm -f``) on completion, timeout, or cancellation. Any
failure fails closed with :class:`ContainerHardeningError`.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import os
import posixpath
import re
import subprocess
import sys
import uuid
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

from app.core.exceptions import ProviderError, ValidationError

CAP_DROP_ALL = "--cap-drop=ALL"
CAP_DROP_ALL_VALUE = "ALL"
NO_NEW_PRIVILEGES = "--security-opt=no-new-privileges:true"
NO_NEW_PRIVILEGES_VALUE = "no-new-privileges:true"
PIDS_LIMIT = 2048
FALLBACK_UID = 1000
FALLBACK_GID = 1000
DATA_TARGET = "/data"

OWNERSHIP_HELPER_PIDS_LIMIT = 64
OWNERSHIP_HELPER_TIMEOUT_SECONDS = 300.0
OWNERSHIP_HELPER_CLEANUP_TIMEOUT_SECONDS = 30.0
OWNERSHIP_HELPER_NAME_PREFIX = "onx-chown-"
OWNERSHIP_HELPER_CAP_ADD = ("CHOWN", "FOWNER", "DAC_OVERRIDE")

INTERNAL_TEST_NETWORK = "onx-test-internal"
ALLOWED_NETWORK_MODES = frozenset({"bridge", "none"})
_NETWORK_NAME_RE = re.compile(r"\Aonx-[a-z0-9][a-z0-9_.-]*\Z")
_IMAGE_TOKEN_RE = re.compile(r"\A[^\s\-][^\s]*\Z")

# Host roots that must never be bind-mounted wholesale into an untrusted
# container. Descendants of the truly sensitive trees are blocked as well;
# panel data living under e.g. ``/home/<user>/...`` remains valid.
_FORBIDDEN_MOUNT_ROOTS = frozenset(
    {
        "/",
        "/bin",
        "/boot",
        "/dev",
        "/etc",
        "/home",
        "/lib",
        "/lib64",
        "/media",
        "/mnt",
        "/opt",
        "/proc",
        "/root",
        "/run",
        "/sbin",
        "/srv",
        "/sys",
        "/usr",
        "/var",
    }
)
_FORBIDDEN_MOUNT_DESCENDANTS = ("/boot", "/dev", "/etc", "/proc", "/root", "/sys")

DockerRunner = Callable[[list[str]], Awaitable[tuple[int, str]]]


class ContainerHardeningError(ProviderError):
    """Raised when a container spawn cannot satisfy the hardening contract."""

    def __init__(self, detail: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__("docker", "container hardening", detail, details=details)
        self.code = "CONTAINER_HARDENING_FAILED"
        self.http_status = 500


def _validate_non_root_ids(uid: int, gid: int) -> None:
    for name, value in (("uid", uid), ("gid", gid)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ContainerHardeningError(
                f"{name} must be an integer",
                details={"field": name, "value": repr(value)},
            )
        if value <= 0:
            raise ContainerHardeningError(
                f"{name} must be a positive non-root id; refusing '{uid}:{gid}'",
                details={"field": name, "uid": uid, "gid": gid},
            )


def _current_uid() -> int:
    getuid = getattr(os, "getuid", None)
    if getuid is None:
        return 0
    return int(getuid())


def _current_gid() -> int:
    getgid = getattr(os, "getgid", None)
    if getgid is None:
        return 0
    return int(getgid())


def resolve_non_root_user(
    uid: int | None = None,
    gid: int | None = None,
) -> tuple[int, int]:
    """Return a validated non-root ``(uid, gid)`` pair.

    Explicit ids must be supplied together and must both be positive. Without
    explicit ids the host uid/gid are used when available and non-root;
    otherwise the configured fallback ``1000:1000`` is used. ``0:0`` is never
    returned and never accepted.
    """
    if uid is not None or gid is not None:
        if uid is None or gid is None:
            raise ContainerHardeningError(
                "uid and gid must be provided together",
                details={"uid": uid, "gid": gid},
            )
        _validate_non_root_ids(uid, gid)
        return uid, gid

    if sys.platform != "win32" and hasattr(os, "getuid") and hasattr(os, "getgid"):
        host_uid, host_gid = _current_uid(), _current_gid()
        if host_uid > 0 and host_gid > 0:
            return host_uid, host_gid
    return FALLBACK_UID, FALLBACK_GID


def hardening_args(
    uid: int | None = None,
    gid: int | None = None,
) -> list[str]:
    """Return the hardening flags, always with a non-root ``--user`` value."""
    resolved_uid, resolved_gid = resolve_non_root_user(uid, gid)
    return [
        CAP_DROP_ALL,
        NO_NEW_PRIVILEGES,
        f"--pids-limit={PIDS_LIMIT}",
        "--user",
        f"{resolved_uid}:{resolved_gid}",
    ]


def validate_docker_image(image: str) -> str:
    """Return a safe single Docker image token or raise ``ValidationError``.

    Rejects empty strings, whitespace (which would split into several argv
    tokens), and leading ``-`` (which Docker would parse as a flag).
    """
    text = image.strip() if isinstance(image, str) else ""
    if not text or not _IMAGE_TOKEN_RE.match(text):
        raise ValidationError(
            "Docker image must be a non-empty single token without leading '-'",
            field="image",
            details={"image": text[:128]},
        )
    return text


def validate_network_mode(network: str) -> str:
    """Return an allow-listed Docker network mode.

    The closed allow-list is ``bridge``, ``none``, and panel-owned networks with
    an ``onx-`` prefix. ``host`` and ``container:<id>`` (host namespace sharing)
    are always rejected, as is any unknown user-supplied network.
    """
    value = str(network or "").strip()
    if not value:
        raise ValidationError(
            "Docker network mode must be a non-empty value", field="network"
        )
    lowered = value.lower()
    if lowered == "host" or lowered.startswith("container:"):
        raise ValidationError(
            f"Docker network mode '{value[:64]}' is forbidden",
            field="network",
        )
    if lowered in ALLOWED_NETWORK_MODES:
        return lowered
    if _NETWORK_NAME_RE.match(lowered):
        return lowered
    raise ValidationError(
        f"Docker network mode '{value[:64]}' is not allow-listed",
        field="network",
    )


def _validate_host_mount_source(source: str) -> str:
    text = source.strip()
    if not text:
        raise ContainerHardeningError("A /data bind mount requires a host source")
    if "\x00" in text or text.startswith("-"):
        raise ContainerHardeningError(
            "Bind mount source contains a forbidden token",
            details={"source": text[:512]},
        )
    normalized = text.replace("\\", "/")
    drive_absolute = bool(re.match(r"\A[A-Za-z]:/", normalized))
    if not (os.path.isabs(normalized) or drive_absolute):
        raise ContainerHardeningError(
            "Bind mount source must be an absolute host path",
            details={"source": text[:512]},
        )
    if ".." in normalized.split("/"):
        raise ContainerHardeningError(
            "Bind mount source must not contain '..' traversal",
            details={"source": text[:512]},
        )
    collapsed = posixpath.normpath(normalized)
    if normalized.startswith("/"):
        # POSIX normpath preserves exactly two leading slashes ("//etc"),
        # which would bypass the root/descendant checks below. Linux treats
        # "//" as "/", so collapse before comparing.
        collapsed = "/" + collapsed.lstrip("/")
    if (
        collapsed in _FORBIDDEN_MOUNT_ROOTS
        or not collapsed.strip("/")
        or re.fullmatch(r"[A-Za-z]:/?", collapsed)
    ):
        raise ContainerHardeningError(
            "Refusing to mount a sensitive host root at /data",
            details={"source": text[:512]},
        )
    for root in _FORBIDDEN_MOUNT_DESCENDANTS:
        if collapsed.startswith(root + "/"):
            raise ContainerHardeningError(
                "Refusing to mount a sensitive host tree at /data",
                details={"source": text[:512]},
            )
    if "docker.sock" in collapsed.lower():
        raise ContainerHardeningError(
            "Refusing to mount the Docker socket",
            details={"source": text[:512]},
        )
    return text


def _validate_data_mount_spec(spec: str) -> str:
    source, separator, target = spec.rpartition(":/data")
    if not separator or target or not source:
        raise ContainerHardeningError(
            "Only a single '<host>:/data' bind mount is allowed",
            details={"mount": spec[:512]},
        )
    return _validate_host_mount_source(source)


def data_mount_args(
    local_source: str | os.PathLike[str],
    *,
    mount_source: str | os.PathLike[str] | None = None,
) -> list[str]:
    """Validate and build the one allowed ``/data`` bind mount."""
    source = str(mount_source if mount_source is not None else local_source).strip()
    _validate_data_mount_spec(f"{source}:{DATA_TARGET}")
    return ["-v", f"{source}:{DATA_TARGET}", "-w", DATA_TARGET]


def validate_data_only_mounts(
    args: Sequence[str], *, image: str | None = None
) -> None:
    """Fail closed when a spawn command mounts anything except one ``/data``.

    When ``image`` is supplied, scanning stops at the image token so container
    command arguments such as ``-v`` are never mistaken for Docker flags.
    """
    mounts = 0
    index = 0
    while index < len(args):
        arg = str(args[index])
        if image is not None and arg == image:
            break
        if arg in ("-v", "--volume"):
            if index + 1 >= len(args):
                raise ContainerHardeningError("Bind mount flag is missing its value")
            mounts += 1
            _validate_data_mount_spec(str(args[index + 1]))
            index += 2
            continue
        if arg.startswith("--volume="):
            mounts += 1
            _validate_data_mount_spec(arg.split("=", 1)[1])
        elif arg == "--mount" or arg.startswith("--mount="):
            raise ContainerHardeningError(
                "Only plain '<host>:/data' bind mounts are allowed; "
                "docker --mount is not supported"
            )
        index += 1
    if mounts > 1:
        raise ContainerHardeningError(
            "Refusing to spawn a container with more than one bind mount",
            details={"mount_count": mounts},
        )


def ownership_helper_args(
    mount_source: str | os.PathLike[str],
    uid: int,
    gid: int,
    image: str,
    *,
    name: str | None = None,
) -> list[str]:
    """Build the short-lived, capability-restricted root helper for ``/data``."""
    _validate_non_root_ids(uid, gid)
    helper_image = validate_docker_image(image)
    source = _validate_data_mount_spec(f"{str(mount_source).strip()}:{DATA_TARGET}")
    helper_name = name or f"{OWNERSHIP_HELPER_NAME_PREFIX}{uuid.uuid4().hex}"
    args = [
        "run",
        "--rm",
        "--name",
        helper_name,
        "--user",
        "0:0",
        CAP_DROP_ALL,
    ]
    for capability in OWNERSHIP_HELPER_CAP_ADD:
        args.extend(["--cap-add", capability])
    args.extend(
        [
            NO_NEW_PRIVILEGES,
            "--network",
            "none",
            f"--pids-limit={OWNERSHIP_HELPER_PIDS_LIMIT}",
            "--entrypoint",
            "chown",
            "-v",
            f"{source}:{DATA_TARGET}",
            helper_image,
            "-h",
            "-R",
            f"{uid}:{gid}",
            DATA_TARGET,
        ]
    )
    return args


def _helper_name_from_args(args: Sequence[str]) -> str:
    try:
        return str(args[args.index("--name") + 1])
    except (ValueError, IndexError) as exc:  # pragma: no cover - internal invariant
        raise ContainerHardeningError(
            "Ownership helper command is missing --name"
        ) from exc


def _chown_tree(root: Path, uid: int, gid: int) -> None:
    os.lchown(root, uid, gid)
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        for name in (*dirnames, *filenames):
            os.lchown(os.path.join(dirpath, name), uid, gid)


def _is_permission_error(exc: OSError) -> bool:
    return isinstance(exc, PermissionError) or exc.errno in (errno.EPERM, errno.EACCES)


async def _default_docker_runner(
    args: list[str], docker_host: str | None = None
) -> tuple[int, str]:
    command = ["docker"]
    if docker_host:
        command.extend(["-H", docker_host])
    command.extend(args)
    proc = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    output = (stdout + stderr).decode("utf-8", errors="replace").strip()
    return proc.returncode or 0, output


async def _subprocess_docker_runner(args: list[str]) -> tuple[int, str]:
    """Run a Docker CLI command without an event-loop-blocking call."""
    completed = await asyncio.to_thread(
        subprocess.run,
        ["docker", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = f"{completed.stdout or ''}{completed.stderr or ''}".strip()
    return completed.returncode or 0, output


async def ensure_internal_network(
    name: str = INTERNAL_TEST_NETWORK,
    *,
    run_docker: DockerRunner | None = None,
) -> str:
    """Create the egress-locked ``--internal`` Docker network when missing.

    Isolated test servers and pooled bot runners share this network so they can
    reach each other while having no route to the LAN or the internet.
    """
    network = validate_network_mode(name)
    if not _NETWORK_NAME_RE.match(network):
        raise ValidationError(
            "Internal test network must be a panel-owned 'onx-' network",
            field="network",
        )
    runner = run_docker or _subprocess_docker_runner
    returncode, _ = await runner(["network", "inspect", network])
    if returncode == 0:
        return network
    returncode, output = await runner(["network", "create", "--internal", network])
    if returncode == 0 or "already exists" in output.lower():
        return network
    raise ContainerHardeningError(
        f"Unable to create internal Docker network '{network}': "
        f"{(output or 'docker network create failed')[:256]}"
    )


async def _remove_ownership_helper(runner: DockerRunner, helper_name: str) -> None:
    """Best-effort ``docker rm -f`` for a helper that may outlive its run."""
    with contextlib.suppress(Exception, asyncio.CancelledError):
        await asyncio.wait_for(
            runner(["rm", "-f", helper_name]),
            timeout=OWNERSHIP_HELPER_CLEANUP_TIMEOUT_SECONDS,
        )


async def prepare_data_ownership(
    root: str | os.PathLike[str],
    *,
    uid: int,
    gid: int,
    image: str,
    mount_source: str | os.PathLike[str] | None = None,
    docker_host: str | None = None,
    run_docker: DockerRunner | None = None,
) -> None:
    """Recursively prepare ``/data`` for the container's non-root uid/gid.

    Direct ``chown`` is attempted first. ``EPERM``/``EACCES`` falls back to a
    short-lived, named root helper container that mounts only this server
    directory at ``/data``. The helper is time-limited to 300 s and is removed
    on success, failure, timeout, and cancellation. Every failure raises
    :class:`ContainerHardeningError`.
    """
    _validate_non_root_ids(uid, gid)
    if sys.platform == "win32":
        # Docker Desktop bind mounts do not expose POSIX ownership to the panel.
        return

    path = Path(root)
    if not path.is_dir():
        raise ContainerHardeningError(
            "Unable to prepare /data ownership: server directory is missing",
            details={"path": str(path)[:512]},
        )

    try:
        await asyncio.to_thread(_chown_tree, path, uid, gid)
        return
    except OSError as exc:
        if not _is_permission_error(exc):
            raise ContainerHardeningError(
                f"Unable to prepare /data ownership: {exc}",
                details={"path": str(path)[:512]},
            ) from exc

    helper_args = ownership_helper_args(mount_source or path, uid, gid, image)
    helper_name = _helper_name_from_args(helper_args)
    if run_docker is None:

        async def default_runner(args: list[str]) -> tuple[int, str]:
            return await _default_docker_runner(args, docker_host)

        runner: DockerRunner = default_runner
    else:
        runner = run_docker

    try:
        try:
            returncode, output = await asyncio.wait_for(
                runner(helper_args),
                timeout=OWNERSHIP_HELPER_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            raise ContainerHardeningError(
                "Root ownership helper timed out after "
                f"{OWNERSHIP_HELPER_TIMEOUT_SECONDS:g}s",
                details={"path": str(path)[:512], "helper": helper_name},
            ) from exc
    finally:
        await _remove_ownership_helper(runner, helper_name)

    if returncode != 0:
        raise ContainerHardeningError(
            "Root ownership helper failed: "
            f"{(output or 'docker run exited non-zero')[:256]}",
            details={"path": str(path)[:512], "exit_code": returncode},
        )


__all__ = [
    "ALLOWED_NETWORK_MODES",
    "CAP_DROP_ALL",
    "CAP_DROP_ALL_VALUE",
    "DATA_TARGET",
    "FALLBACK_GID",
    "FALLBACK_UID",
    "INTERNAL_TEST_NETWORK",
    "NO_NEW_PRIVILEGES",
    "NO_NEW_PRIVILEGES_VALUE",
    "OWNERSHIP_HELPER_CAP_ADD",
    "OWNERSHIP_HELPER_CLEANUP_TIMEOUT_SECONDS",
    "OWNERSHIP_HELPER_NAME_PREFIX",
    "OWNERSHIP_HELPER_PIDS_LIMIT",
    "OWNERSHIP_HELPER_TIMEOUT_SECONDS",
    "PIDS_LIMIT",
    "ContainerHardeningError",
    "data_mount_args",
    "ensure_internal_network",
    "hardening_args",
    "ownership_helper_args",
    "prepare_data_ownership",
    "resolve_non_root_user",
    "validate_data_only_mounts",
    "validate_docker_image",
    "validate_network_mode",
]
