"""P2-6b shared container hardening helpers."""

from __future__ import annotations

import asyncio
import errno
from pathlib import Path
from typing import Any

import pytest

from app.core.container_hardening import (
    CAP_DROP_ALL,
    FALLBACK_GID,
    FALLBACK_UID,
    INTERNAL_TEST_NETWORK,
    NO_NEW_PRIVILEGES,
    OWNERSHIP_HELPER_PIDS_LIMIT,
    PIDS_LIMIT,
    ContainerHardeningError,
    data_mount_args,
    ensure_internal_network,
    hardening_args,
    ownership_helper_args,
    prepare_data_ownership,
    resolve_non_root_user,
    validate_data_only_mounts,
    validate_docker_image,
    validate_network_mode,
)
from app.core.exceptions import ValidationError


def test_hardening_args_contain_required_flags() -> None:
    args = hardening_args(1234, 5678)

    assert CAP_DROP_ALL in args
    assert NO_NEW_PRIVILEGES in args
    assert f"--pids-limit={PIDS_LIMIT}" in args
    assert args[args.index("--user") + 1] == "1234:5678"


@pytest.mark.parametrize(
    ("uid", "gid"),
    [
        (0, 0),
        (0, 1000),
        (1000, 0),
        (-1, 1000),
        (1000, -1),
    ],
)
def test_explicit_root_or_negative_ids_fail_closed(uid: int, gid: int) -> None:
    with pytest.raises(ContainerHardeningError):
        resolve_non_root_user(uid, gid)
    with pytest.raises(ContainerHardeningError):
        hardening_args(uid, gid)


def test_partial_or_boolean_ids_fail_closed() -> None:
    with pytest.raises(ContainerHardeningError):
        resolve_non_root_user(1000, None)
    with pytest.raises(ContainerHardeningError):
        resolve_non_root_user(None, 1000)
    with pytest.raises(ContainerHardeningError):
        resolve_non_root_user(True, 1000)  # type: ignore[arg-type]


def test_zero_host_ids_use_non_root_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.core.container_hardening._current_uid", lambda: 0
    )
    monkeypatch.setattr(
        "app.core.container_hardening._current_gid", lambda: 0
    )

    assert resolve_non_root_user() == (FALLBACK_UID, FALLBACK_GID)


def test_valid_host_ids_are_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.core.container_hardening._current_uid", lambda: 1234
    )
    monkeypatch.setattr(
        "app.core.container_hardening._current_gid", lambda: 5678
    )

    assert resolve_non_root_user() == (1234, 5678)


def test_data_mount_args_only_target_data() -> None:
    assert data_mount_args("/srv/data") == [
        "-v",
        "/srv/data:/data",
        "-w",
        "/data",
    ]
    assert data_mount_args("/local/data", mount_source="/host/srv/data") == [
        "-v",
        "/host/srv/data:/data",
        "-w",
        "/data",
    ]


@pytest.mark.parametrize(
    "spec",
    [
        "/srv:/var/lib",
        "/srv:/data/../etc",
        "/:/data",
        "/srv:/data:ro",
        "/srv:",
    ],
)
def test_validate_data_only_mounts_rejects_sibling_or_root(spec: str) -> None:
    with pytest.raises(ContainerHardeningError):
        validate_data_only_mounts(["-v", spec])


def test_validate_data_only_mounts_rejects_multiple_or_mount_flag() -> None:
    with pytest.raises(ContainerHardeningError):
        validate_data_only_mounts(["-v", "/a:/data", "-v", "/b:/data"])
    with pytest.raises(ContainerHardeningError):
        validate_data_only_mounts(["--mount", "type=bind,source=/a,target=/data"])
    with pytest.raises(ContainerHardeningError):
        validate_data_only_mounts(["-v"])


@pytest.mark.asyncio
async def test_prepare_data_ownership_direct_chown_succeeds(
    tmp_path: Path,
) -> None:
    server_dir = tmp_path / "server"
    subdir = server_dir / "world"
    subdir.mkdir(parents=True)
    (server_dir / "server.properties").write_text("motd=x\n", encoding="utf-8")
    (subdir / "level.dat").write_bytes(b"level")

    uid, gid = resolve_non_root_user()
    helper_calls: list[list[str]] = []

    async def fail_helper(args: list[str]) -> tuple[int, str]:
        helper_calls.append(args)
        return 1, "helper must not run"

    await prepare_data_ownership(
        server_dir,
        uid=uid,
        gid=gid,
        image="eclipse-temurin:21-jre",
        run_docker=fail_helper,
    )

    assert helper_calls == []
    assert (server_dir / "server.properties").stat().st_uid == uid
    assert (subdir / "level.dat").stat().st_gid == gid


@pytest.mark.asyncio
async def test_prepare_data_ownership_permission_error_uses_root_helper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    uid, gid = resolve_non_root_user()
    calls: list[list[str]] = []

    def denied(_root: Path, _uid: int, _gid: int) -> None:
        raise PermissionError(errno.EPERM, "operation not permitted")

    async def helper(args: list[str]) -> tuple[int, str]:
        calls.append(args)
        return 0, ""

    monkeypatch.setattr(
        "app.core.container_hardening._chown_tree", denied
    )
    await prepare_data_ownership(
        server_dir,
        uid=uid,
        gid=gid,
        image="itzg/minecraft-server:java21",
        mount_source="/host/data/server",
        run_docker=helper,
    )

    assert len(calls) == 2
    run_args = calls[0]
    helper_name = run_args[run_args.index("--name") + 1]
    assert helper_name.startswith("onx-chown-")
    assert calls[1] == ["rm", "-f", helper_name]
    assert run_args.count("-v") == 1
    assert "/host/data/server:/data" in run_args
    assert run_args[run_args.index("--user") + 1] == "0:0"


@pytest.mark.asyncio
async def test_prepare_data_ownership_helper_failure_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    uid, gid = resolve_non_root_user()

    def denied(_root: Path, _uid: int, _gid: int) -> None:
        raise PermissionError(errno.EACCES, "permission denied")

    async def helper(_args: list[str]) -> tuple[int, str]:
        return 1, "chown: /data: Operation not permitted"

    monkeypatch.setattr(
        "app.core.container_hardening._chown_tree", denied
    )
    with pytest.raises(ContainerHardeningError, match="helper failed"):
        await prepare_data_ownership(
            server_dir,
            uid=uid,
            gid=gid,
            image="alpine:3.20",
            run_docker=helper,
        )


@pytest.mark.asyncio
async def test_prepare_data_ownership_non_permission_error_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    uid, gid = resolve_non_root_user()
    helper_calls: list[Any] = []

    def broken(_root: Path, _uid: int, _gid: int) -> None:
        raise OSError(errno.ENOENT, "missing path")

    async def helper(args: list[str]) -> tuple[int, str]:
        helper_calls.append(args)
        return 0, ""

    monkeypatch.setattr(
        "app.core.container_hardening._chown_tree", broken
    )
    with pytest.raises(ContainerHardeningError, match="ownership"):
        await prepare_data_ownership(
            server_dir,
            uid=uid,
            gid=gid,
            image="alpine:3.20",
            run_docker=helper,
        )
    assert helper_calls == []


@pytest.mark.asyncio
async def test_prepare_data_ownership_missing_directory_fails_closed(
    tmp_path: Path,
) -> None:
    uid, gid = resolve_non_root_user()
    with pytest.raises(ContainerHardeningError, match="missing"):
        await prepare_data_ownership(
            tmp_path / "does-not-exist",
            uid=uid,
            gid=gid,
            image="alpine:3.20",
        )


def test_ownership_helper_fails_closed_on_root_ids() -> None:
    with pytest.raises(ContainerHardeningError):
        ownership_helper_args("/srv/data", 0, 0, "alpine:3.20")


def test_data_mount_source_rejects_host_root() -> None:
    with pytest.raises(ContainerHardeningError):
        data_mount_args("/")


def test_ownership_helper_is_capability_restricted_and_named() -> None:
    args = ownership_helper_args(
        "/host/data/server", 1234, 5678, "itzg/minecraft-server:java21"
    )
    helper_name = args[args.index("--name") + 1]
    assert helper_name.startswith("onx-chown-")
    assert "--cap-drop=ALL" in args
    assert args.count("--cap-add") == 3
    for capability in ("CHOWN", "FOWNER", "DAC_OVERRIDE"):
        assert args[args.index("--cap-add") + 1 :].count(capability) >= 1
    assert "--security-opt=no-new-privileges:true" in args
    assert args[args.index("--network") + 1] == "none"
    assert f"--pids-limit={OWNERSHIP_HELPER_PIDS_LIMIT}" in args
    assert args[args.index("-v") + 1] == "/host/data/server:/data"
    chown_flags = args[args.index("-h") :]
    assert chown_flags[:2] == ["-h", "-R"]
    assert chown_flags[-2:] == ["1234:5678", "/data"]


@pytest.mark.asyncio
async def test_prepare_data_ownership_helper_timeout_removes_named_helper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    uid, gid = resolve_non_root_user()
    calls: list[list[str]] = []

    def denied(_root: Path, _uid: int, _gid: int) -> None:
        raise PermissionError(errno.EPERM, "operation not permitted")

    async def hanging_helper(args: list[str]) -> tuple[int, str]:
        calls.append(args)
        if args[:2] == ["rm", "-f"]:
            return 0, ""
        await asyncio.sleep(3600)
        return 0, ""

    monkeypatch.setattr("app.core.container_hardening._chown_tree", denied)
    monkeypatch.setattr(
        "app.core.container_hardening.OWNERSHIP_HELPER_TIMEOUT_SECONDS", 0.05
    )

    with pytest.raises(ContainerHardeningError, match="timed out"):
        await prepare_data_ownership(
            server_dir,
            uid=uid,
            gid=gid,
            image="alpine:3.20",
            run_docker=hanging_helper,
        )

    helper_name = calls[0][calls[0].index("--name") + 1]
    assert calls[-1] == ["rm", "-f", helper_name]


@pytest.mark.asyncio
async def test_prepare_data_ownership_cancel_removes_named_helper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    uid, gid = resolve_non_root_user()
    calls: list[list[str]] = []
    started = asyncio.Event()

    def denied(_root: Path, _uid: int, _gid: int) -> None:
        raise PermissionError(errno.EPERM, "operation not permitted")

    async def hanging_helper(args: list[str]) -> tuple[int, str]:
        calls.append(args)
        if args[:2] == ["rm", "-f"]:
            return 0, ""
        started.set()
        await asyncio.sleep(3600)
        return 0, ""

    monkeypatch.setattr("app.core.container_hardening._chown_tree", denied)

    task = asyncio.create_task(
        prepare_data_ownership(
            server_dir,
            uid=uid,
            gid=gid,
            image="alpine:3.20",
            run_docker=hanging_helper,
        )
    )
    await asyncio.wait_for(started.wait(), timeout=2.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    helper_name = calls[0][calls[0].index("--name") + 1]
    assert calls[-1] == ["rm", "-f", helper_name]


@pytest.mark.parametrize(
    "source",
    [
        "relative/path",
        "/srv/../etc",
        "/etc",
        "/etc/shadow",
        "/home",
        "/root/data",
        "/var/run/docker.sock",
        "/proc/1",
        "//etc",
        "//proc/1",
        "/",
        "//",
        "/.",
    ],
)
def test_data_mount_rejects_unsafe_host_sources(source: str) -> None:
    with pytest.raises(ContainerHardeningError):
        data_mount_args(source)


@pytest.mark.parametrize(
    "source", ["/srv/data", "/home/panel/servers/srv-1", "/tmp/pytest-data"]
)
def test_data_mount_allows_absolute_panel_paths(source: str) -> None:
    assert data_mount_args(source)[1] == f"{source}:/data"


@pytest.mark.parametrize("image", ["", "   ", "-rm", "img name", "img\tname"])
def test_validate_docker_image_rejects_unsafe_tokens(image: str) -> None:
    with pytest.raises(ValidationError):
        validate_docker_image(image)


def test_validate_docker_image_trims_valid_token() -> None:
    assert validate_docker_image(" itzg/minecraft-server:java21 ") == (
        "itzg/minecraft-server:java21"
    )


@pytest.mark.parametrize("network", ["bridge", "none", "onx-custom-bridge"])
def test_network_mode_allow_list(network: str) -> None:
    assert validate_network_mode(network) == network


@pytest.mark.parametrize(
    "network", ["host", "container:abc123", "mynet", "default", ""]
)
def test_network_mode_rejects_host_container_and_unknown(network: str) -> None:
    with pytest.raises(ValidationError):
        validate_network_mode(network)


@pytest.mark.asyncio
async def test_ensure_internal_network_creates_internal_network() -> None:
    calls: list[list[str]] = []

    async def runner(args: list[str]) -> tuple[int, str]:
        calls.append(args)
        if args[:2] == ["network", "inspect"]:
            return 1, ""
        if args[:2] == ["network", "create"]:
            return 0, ""
        return 0, ""

    assert (
        await ensure_internal_network(run_docker=runner)
        == INTERNAL_TEST_NETWORK
    )
    assert ["network", "create", "--internal", INTERNAL_TEST_NETWORK] in calls


@pytest.mark.asyncio
async def test_ensure_internal_network_failure_fails_closed() -> None:
    async def runner(_args: list[str]) -> tuple[int, str]:
        return 1, "daemon error"

    with pytest.raises(ContainerHardeningError, match="internal Docker network"):
        await ensure_internal_network(run_docker=runner)


def test_config_fingerprint_includes_hardening_inputs() -> None:
    """P2-6c2 / H-A1: the hardening contract is part of container identity."""
    import inspect

    from app.modules.server.infrastructure.providers.docker import (
        _compute_config_fingerprint,
    )

    parameter_names = set(
        inspect.signature(_compute_config_fingerprint).parameters
    )
    assert {"user", "cap_drop", "security_opt", "pids_limit"} <= parameter_names

    common = {
        "image": "eclipse-temurin:21-jre-jammy",
        "memory_min": 1024,
        "memory_max": 2048,
        "cpu_cores": 0,
        "cpu_affinity": "",
        "ports": ["25565:25565"],
        "mounts": ["/srv/data:/data"],
        "env": {},
        "cmd": ["java", "-jar", "server.jar"],
    }
    hardened = _compute_config_fingerprint(
        **common,
        user="1000:1000",
        cap_drop=["ALL"],
        security_opt=["no-new-privileges:true"],
        pids_limit=2048,
    )
    unhardened = _compute_config_fingerprint(
        **common,
        user="0:0",
        cap_drop=[],
        security_opt=[],
        pids_limit=0,
    )
    assert hardened != unhardened
