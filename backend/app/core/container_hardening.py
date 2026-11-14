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
short-lived root helper container (``--rm``, mounting only the server directory
at ``/data``) performs the change. Any failure fails closed with
:class:`ContainerHardeningError`.
"""

from __future__ import annotations

import asyncio
import errno
import os
import sys
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

from app.core.exceptions import ProviderError

CAP_DROP_ALL = "--cap-drop=ALL"
NO_NEW_PRIVILEGES = "--security-opt=no-new-privileges:true"
PIDS_LIMIT = 2048
FALLBACK_UID = 1000
FALLBACK_GID = 1000
DATA_TARGET = "/data"

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


def _validate_data_mount_spec(spec: str) -> str:
    source, separator, target = spec.rpartition(":/data")
    if not separator or target or not source:
        raise ContainerHardeningError(
            "Only a single '<host>:/data' bind mount is allowed",
            details={"mount": spec[:512]},
        )
    if source == "/":
        raise ContainerHardeningError(
            "Refusing to mount the host root at /data",
            details={"mount": spec[:512]},
        )
    return source


def data_mount_args(
    local_source: str | os.PathLike[str],
    *,
    mount_source: str | os.PathLike[str] | None = None,
) -> list[str]:
    """Validate and build the one allowed ``/data`` bind mount."""
    source = str(mount_source if mount_source is not None else local_source).strip()
    if not source:
        raise ContainerHardeningError("A /data bind mount requires a host source")
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
) -> list[str]:
    """Build the short-lived root helper that fixes ``/data`` ownership."""
    _validate_non_root_ids(uid, gid)
    source = str(mount_source).strip()
    if not source:
        raise ContainerHardeningError("Ownership helper requires a /data source")
    _validate_data_mount_spec(f"{source}:{DATA_TARGET}")
    return [
        "run",
        "--rm",
        "--user",
        "0:0",
        "--entrypoint",
        "chown",
        "-v",
        f"{source}:{DATA_TARGET}",
        image,
        "-R",
        f"{uid}:{gid}",
        DATA_TARGET,
    ]


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
    short-lived root helper container that mounts only this server directory at
    ``/data``. Every other failure (including a non-zero helper exit) raises
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
    if run_docker is None:

        async def default_runner(args: list[str]) -> tuple[int, str]:
            return await _default_docker_runner(args, docker_host)

        runner: DockerRunner = default_runner
    else:
        runner = run_docker

    returncode, output = await runner(helper_args)
    if returncode != 0:
        raise ContainerHardeningError(
            "Root ownership helper failed: "
            f"{(output or 'docker run exited non-zero')[:256]}",
            details={"path": str(path)[:512], "exit_code": returncode},
        )


__all__ = [
    "CAP_DROP_ALL",
    "DATA_TARGET",
    "FALLBACK_GID",
    "FALLBACK_UID",
    "NO_NEW_PRIVILEGES",
    "PIDS_LIMIT",
    "ContainerHardeningError",
    "data_mount_args",
    "hardening_args",
    "ownership_helper_args",
    "prepare_data_ownership",
    "resolve_non_root_user",
    "validate_data_only_mounts",
]
