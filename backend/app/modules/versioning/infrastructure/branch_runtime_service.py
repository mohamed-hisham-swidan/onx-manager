from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shlex
import shutil
import uuid
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.container_hardening import (
    data_mount_args,
    hardening_args,
    prepare_data_ownership,
    resolve_non_root_user,
    validate_data_only_mounts,
    validate_docker_image,
    validate_network_mode,
)
from app.core.exceptions import (
    InfrastructureError,
    NotFoundError,
    ServerModeVersioningDisabledError,
    ValidationError,
)
from app.core.host_state import HostStateLayout, check_not_symlink_or_reparse
from app.modules.monitoring.infrastructure.rcon_client import AsyncRCONClient
from app.modules.server.application.services.jar_service import generate_rcon_password
from app.modules.server.infrastructure.models import ServerModel
from app.modules.server.infrastructure.providers.docker import (
    build_docker_server_cmd,
    resolve_docker_image,
    resolve_host_mount_path,
)
from app.modules.versioning.application.lockfile_service import LockfileService
from app.modules.versioning.application.mode_guard import ensure_versioning_allowed
from app.modules.versioning.application.scheduling.admission import (
    RuntimeAdmissionScheduler,
)
from app.modules.versioning.domain.port_sets import HostPortSet
from app.modules.versioning.infrastructure.class_c_snapshot import ClassCSnapshotService
from app.modules.versioning.infrastructure.clean_export import (
    CleanExportRequest,
    CleanExportService,
)
from app.modules.versioning.infrastructure.data_templates import DataTemplateService
from app.modules.versioning.infrastructure.git_branches import GitBranchService
from app.modules.versioning.infrastructure.models import (
    ServerBranchModel,
    ServerDataTemplateModel,
    ServerDynamicClassCModel,
    ServerRuntimeModel,
)
from app.modules.versioning.infrastructure.port_allocator import release_port_set
from app.modules.versioning.infrastructure.runtime_adapters import require_docker_provider
from app.modules.versioning.infrastructure.server_secret_vault import ServerSecretVault

try:
    from app.core.persistence.db import database
except Exception:  # pragma: no cover
    database = None  # type: ignore[assignment]


def sanitize_branch_slug(branch_name: str) -> str:
    text = str(branch_name).lower()
    text = re.sub(r"[^a-z0-9-]+", "-", text)
    text = re.sub(r"-+", "-", text)
    text = text.strip("-")
    if not text:
        text = "branch"
    return text[:32]


def build_branch_container_name(server_id: str, branch_name: str, runtime_id: str) -> str:
    return (
        f"onx-branch-{str(server_id)[:8]}-"
        f"{sanitize_branch_slug(branch_name)}-"
        f"{str(runtime_id)[:8]}"
    )


def build_branch_docker_create_args(*args: Any, **kwargs: Any) -> list[str]:
    # Allow a leading mapping/instance to seed kwargs.
    if args:
        first = args[0]
        if isinstance(first, Mapping):
            merged = dict(first)
            merged.update(kwargs)
            kwargs = merged
            args = args[1:]
        elif hasattr(first, "__dict__") and not isinstance(first, (str, bytes)):
            merged = dict(getattr(first, "__dict__", {}))
            merged.update(kwargs)
            kwargs = merged
            args = args[1:]

    container_name = kwargs.get("container_name") or kwargs.get("name")
    image = kwargs.get("image")
    network = kwargs.get("network", "bridge")
    port_set = kwargs.get("port_set")
    memory_max_mb = kwargs.get("memory_max_mb", kwargs.get("memory_max", 4096))
    cpu_cores = kwargs.get("cpu_cores", kwargs.get("cpus", 2))
    cpu_affinity = str(kwargs.get("cpu_affinity", "") or "")
    jvm_flags = kwargs.get("jvm_flags")
    export_root = kwargs.get("export_root", kwargs.get("export_path"))
    host_mount = kwargs.get("host_mount", kwargs.get("host_mount_path"))
    uid = kwargs.get("uid")
    gid = kwargs.get("gid")
    server_id = kwargs.get("server_id", "")
    branch_name = kwargs.get("branch_name", "")
    runtime_id = kwargs.get("runtime_id", "")
    commit_sha = kwargs.get("commit_sha", "")
    host_ip = kwargs.get("host_ip")
    cmd = kwargs.get("cmd", kwargs.get("command"))
    lockfile = kwargs.get("lockfile")
    startup_jar = kwargs.get("startup_jar", "server.jar")
    memory_min_mb = kwargs.get("memory_min_mb", min(1024, int(memory_max_mb or 4096)))
    secrets = kwargs.get("secrets")

    if image is None:
        image = "itzg/minecraft-server:latest"
    image = validate_docker_image(str(image))
    network = validate_network_mode(str(network))
    uid, gid = resolve_non_root_user(uid, gid)

    if host_mount is None and export_root is not None:
        host_mount = resolve_host_mount_path(str(export_root))

    # Determine cmd (argfile launch for forge/neoforge/quilt).
    loader = None
    unix_args_relpath = None
    if lockfile is not None and getattr(lockfile, "lec", None) is not None:
        try:
            from app.modules.versioning.domain.lockfile import parse_lec_key

            parts = parse_lec_key(lockfile.lec.key)
            loader = parts.loader
            if loader in {"forge", "neoforge", "quilt"}:
                from app.modules.versioning.infrastructure.clean_export import _unix_args_relpath

                unix_args_relpath = _unix_args_relpath(parts)
        except Exception:
            loader = None
    if cmd is None:
        if unix_args_relpath is not None:
            cmd = [
                "java",
                "@/data/user_jvm_args.txt",
                f"@/data/{unix_args_relpath}",
                "nogui",
            ]
        else:
            parsed_jvm_flags = (
                list(jvm_flags)
                if isinstance(jvm_flags, (list, tuple))
                else (
                    shlex.split(str(jvm_flags))
                    if isinstance(jvm_flags, str) and jvm_flags.strip()
                    else None
                )
            )
            cmd = build_docker_server_cmd(
                startup_jar=startup_jar,
                jvm_flags=parsed_jvm_flags,
                memory_min_mb=int(memory_min_mb),
                memory_max_mb=int(memory_max_mb),
                cpu_cores=int(cpu_cores),
                image=image,
                force_itzg_entrypoint=True,
            )

    out: list[str] = ["create", "--name", str(container_name), "--network", network]

    prefix = "com.onx-manager"
    try:
        from app.modules.server.infrastructure import identity as _id

        prefix = getattr(_id, "docker_label_prefix_new", prefix)
    except Exception:
        pass

    labels = [
        f"{prefix}.managed=true",
        f"{prefix}.role=branch-runtime",
        f"{prefix}.server_id={server_id}",
        f"{prefix}.branch_name={branch_name}",
        f"{prefix}.runtime_id={runtime_id}",
        f"{prefix}.commit_sha={commit_sha}",
    ]
    for lab in labels:
        out.extend(["--label", lab])

    if port_set is not None:
        for spec in port_set.to_docker_port_bindings(host_ip=host_ip):
            out.extend(["-p", spec])

    out.extend(
        [
            "--memory",
            f"{int(memory_max_mb) + 512}m",
            "--memory-swap",
            f"{int(memory_max_mb) + 512}m",
            "--cpus",
            str(cpu_cores),
        ]
    )
    if cpu_affinity:
        from app.modules.server.domain.value_objects import CpuAllocation

        CpuAllocation.validate(int(cpu_cores or 0), cpu_affinity)
        out.extend(["--cpuset-cpus", cpu_affinity])

    if export_root is not None:
        out.extend(data_mount_args(export_root, mount_source=host_mount))

    out.extend(hardening_args(uid, gid))

    # Safe env vars.
    if secrets:
        for k, v in secrets.items():
            if str(k).upper() in {"PUID", "PGID"}:
                continue
            out.extend(["-e", f"{k}={v}"])
    if "itzg" in str(image).lower():
        out.extend(["-e", "EULA=TRUE"])

    out.append(image)
    out.extend(list(cmd or []))

    validate_data_only_mounts(out, image=image)
    return out


@contextmanager
def _ephemeral_class_c_overlay(
    layout: HostStateLayout,
    server_id: str,
    runtime_id: str,
    class_c_service: ClassCSnapshotService | None,
) -> Any:
    if class_c_service is None:
        yield None
        return

    active = []
    try:
        active = class_c_service.repository.list_active(server_id)
    except Exception:
        try:
            active = class_c_service.list_active(server_id)
        except Exception:
            active = []
    if not active:
        yield None
        return

    latest = active[0]
    snapshot_id = getattr(latest, "snapshot_id", None)
    parent = layout.quarantine_dir(server_id)
    check_not_symlink_or_reparse(parent) if parent.exists() else None
    parent.mkdir(parents=True, exist_ok=True, mode=0o700) if not parent.exists() else None
    # ensure mode
    if os.name == "posix":
        with contextlib.suppress(OSError):
            os.chmod(parent, 0o700)

    staging_dir = parent / f".onx-class-c-overlay-{str(runtime_id)[:8]}-{uuid.uuid4().hex[:8]}"
    if os.name == "posix":
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(parent, flags)
        try:
            os.mkdir(staging_dir, 0o700)
            os.chmod(staging_dir, 0o700)
        finally:
            os.close(fd)
    else:
        staging_dir.mkdir(parents=True, exist_ok=True)

    try:
        class_c_service.restore_snapshot(server_id, snapshot_id, staging_dir)
        import datetime as _dt

        completed_at = _dt.datetime.now(_dt.UTC).isoformat()
        marker = {
            "completed_at": completed_at,
            "snapshot_id": snapshot_id,
            "ephemeral": True,
        }
        marker_path = staging_dir / ".onx-complete.json"
        fd = os.open(
            marker_path,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            os.write(fd, json.dumps(marker).encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        yield staging_dir
    finally:
        # shred + delete
        if staging_dir.exists() and not staging_dir.is_symlink():
            for dirpath, _dirnames, filenames in os.walk(staging_dir, followlinks=False):
                for filename in filenames:
                    full = Path(dirpath) / filename
                    if full.is_symlink():
                        with contextlib.suppress(OSError):
                            full.unlink(missing_ok=True)
                        continue
                    if not full.is_file():
                        continue
                    try:
                        flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
                        f = os.open(full, flags)
                        try:
                            size = os.fstat(f).st_size
                            remaining = size
                            while remaining > 0:
                                chunk = min(1024 * 1024, remaining)
                                os.write(f, b"\x00" * chunk)
                                remaining -= chunk
                            os.fsync(f)
                        finally:
                            os.close(f)
                        with contextlib.suppress(OSError):
                            full.unlink(missing_ok=True)
                    except FileNotFoundError:
                        pass
                    except Exception:
                        with contextlib.suppress(OSError):
                            full.unlink(missing_ok=True)
            with contextlib.suppress(FileNotFoundError):
                shutil.rmtree(staging_dir, ignore_errors=False)
        elif staging_dir.is_symlink():
            with contextlib.suppress(OSError):
                staging_dir.unlink(missing_ok=True)


def _destroy_export_root(server_root: Path | str, export_path: Path | str) -> None:
    server_root = Path(server_root)
    export_path = Path(export_path)
    if export_path.is_symlink():
        raise ValidationError("Export path must not be a symlink", field="export_path")
    exports_root = server_root / ".onx" / "branch-exports"
    worktrees_root = server_root / ".onx" / "worktrees"
    # containment checks (lexical)
    try:
        export_norm = os.path.normpath(os.path.abspath(export_path))
        exports_norm = os.path.normpath(os.path.abspath(exports_root))
        common = os.path.commonpath([export_norm, exports_norm])
    except ValueError as exc:
        raise ValidationError("Export path containment check failed", field="export_path") from exc
    if common != exports_norm or export_norm == exports_norm:
        raise ValidationError("Export path must be inside branch-exports", field="export_path")
    pass
    if export_norm == os.path.normpath(os.path.abspath(server_root)):
        raise ValidationError("Export path must not be server root", field="export_path")
    try:
        wt_norm = os.path.normpath(os.path.abspath(worktrees_root))
        common_wt = os.path.commonpath([export_norm, wt_norm])
        if common_wt == wt_norm:
            raise ValidationError("Export path must not be inside worktrees", field="export_path")
    except ValueError:
        pass
    if not export_path.exists():
        return
    shutil.rmtree(export_path, ignore_errors=False)


@dataclass
class BranchStartRequest:
    server_id: str
    server_root: str | os.PathLike[str]
    branch_name: str
    server_type: str = "vanilla"
    minecraft_version: str = "1.21.1"
    server_provider: str = "docker"
    server_mode: str = "advanced"
    commit_sha: str | None = None
    data_template_id: str | None = None
    allow_public_test_join: bool = False
    port_set: HostPortSet | None = None
    include_query: bool = False
    plugin_port_names: tuple[str, ...] = ()
    requested_memory_mb: int | None = None
    requested_memory_min_mb: int | None = None
    requested_cpu_cores: int | None = None
    cpu_affinity: str = ""
    max_concurrent_branch_runs: int | None = None
    jvm_args: str = ""
    startup_jar: str = "server.jar"
    image: str | None = None
    host_ip: str | None = None
    uid: int | None = None
    gid: int | None = None
    check_os_ports: bool = True
    lockfile: Any = None
    secrets: Mapping[str, str] | None = None


@dataclass
class BranchStartResult:
    runtime_id: str
    server_id: str
    branch_name: str
    commit_sha: str
    container_name: str
    container_id: str
    port_set: HostPortSet | None
    export_path: str
    data_template_id: str | None
    allow_public_test_join: bool
    memory_max_mb: int
    cpu_cores: int
    uncommitted_changes_warning: bool = False


@dataclass
class BranchStopResult:
    runtime_id: str
    server_id: str
    branch_name: str
    saved_template: Any = None
    exit_code: int | None = None
    oom_killed: bool = False


@dataclass
class BranchDestroyResult:
    runtime_id: str
    server_id: str
    branch_name: str
    container_name: str
    released_ports: bool = True


async def _teardown_branch_exposure_best_effort(server_id: str, branch_name: str) -> None:
    """Stop any branch-scoped tunnel or UPnP mapping on container stop/destroy."""
    with contextlib.suppress(Exception):
        from app.modules.exposure.application.commands import teardown_branch_exposure

        await teardown_branch_exposure(server_id, branch_name)


@dataclass
class SaveTemplateResult:
    template_id: str
    server_id: str
    name: str
    storage_path: str
    source_branch_name: str
    source_commit_sha: str | None
    file_count: int | None = None
    total_bytes: int | None = None


class _BranchContainerStateAdapter:
    def __init__(self, docker_runner: Callable | None, container_name: str) -> None:
        self._runner = docker_runner
        self._name = container_name

    def is_running(self) -> Any:
        async def _check() -> bool:
            if self._runner is None:
                return False
            try:
                rc, out = await self._runner(["inspect", "-f", "{{.State.Running}}", self._name])
                return rc == 0 and str(out).strip().lower() == "true"
            except Exception:
                return False

        return _check()


class _BranchRconQuiesceAdapter:
    def __init__(
        self,
        host: str,
        port: int,
        password: str,
        client_factory: Callable | None,
    ) -> None:
        self._host = host
        self._port = port
        self._password = password
        self._factory = client_factory or AsyncRCONClient

    async def _client(self) -> Any:
        client = self._factory(self._host, self._port, self._password)
        await client.connect()
        return client

    async def save_off(self) -> Any:
        client = await self._client()
        try:
            return await client.send_command("save-off")
        finally:
            await client.close()

    async def save_all_flush(self, timeout: float = 30.0) -> str:  # noqa: ARG002
        client = await self._client()
        try:
            return await client.send_command("save-all flush")
        finally:
            await client.close()

    async def save_on(self) -> Any:
        client = await self._client()
        try:
            return await client.send_command("save-on")
        finally:
            await client.close()


class _ServerSaveOffStore:
    def __init__(self, session_factory: Callable | None) -> None:
        self._sf = session_factory

    async def set_save_off_active(self, server_id: str, active: bool) -> Any:
        if self._sf is None:
            return None
        async with self._sf() as session:
            from sqlalchemy import update

            stmt = (
                update(ServerModel)
                .where(ServerModel.id == server_id)
                .values(rcon_save_off_active=bool(active))
            )
            await session.execute(stmt)
            await session.commit()
        return None


class BranchRuntimeService:
    def __init__(
        self,
        layout: HostStateLayout,
        *,
        session_factory: Any = None,
        engine: Any = None,
        admission_scheduler: Any = None,
        branch_service: GitBranchService | None = None,
        clean_export_service: CleanExportService | None = None,
        class_c_service: ClassCSnapshotService | None = None,
        secret_vault: ServerSecretVault | None = None,
        lockfile_service: LockfileService | None = None,
        data_template_service: DataTemplateService | None = None,
        docker_runner: Callable | None = None,
        rcon_client_factory: Callable | None = None,
    ) -> None:
        self.layout = layout
        self.session_factory = session_factory
        self.engine = engine
        self.admission_scheduler = admission_scheduler or RuntimeAdmissionScheduler(engine=engine)
        self.branch_service = branch_service or GitBranchService(layout)
        self.clean_export_service = clean_export_service or CleanExportService(
            layout, branch_service=self.branch_service
        )
        self.class_c_service = class_c_service or ClassCSnapshotService(layout)
        self.secret_vault = secret_vault or ServerSecretVault(layout)
        self.lockfile_service = lockfile_service or LockfileService(layout)
        self.data_template_service = data_template_service
        self.docker_runner = docker_runner
        if self.docker_runner is None:

            async def _default_runner(args: list[str]) -> tuple[int, str]:
                import asyncio as _a

                proc = await _a.create_subprocess_exec(
                    "docker",
                    *args,
                    stdout=_a.subprocess.PIPE,
                    stderr=_a.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate()
                out = (stdout + stderr).decode("utf-8", errors="replace").strip()
                return proc.returncode or 0, out

            self.docker_runner = _default_runner
        self.rcon_client_factory = rcon_client_factory
        self._rcon_credentials: dict[str, tuple[str, int, str]] = {}

    async def _session(self) -> Any:
        if self.session_factory is None:
            return None
        return self.session_factory()

    async def _reconcile_stale_active_runtimes(
        self,
        server_id: str,
        server_root: str | os.PathLike[str],
    ) -> int:
        """Reap dead/missing Docker branch runtimes before admission checks."""
        if self.session_factory is None or self.docker_runner is None:
            return 0

        from sqlalchemy import select as _select

        active_statuses = ("starting", "running", "stopping")
        async with self.session_factory() as session:
            res = await session.execute(
                _select(ServerRuntimeModel).where(
                    ServerRuntimeModel.server_id == server_id,
                    ServerRuntimeModel.status.in_(active_statuses),
                    ServerRuntimeModel.branch_name.is_not(None),
                    ServerRuntimeModel.branch_name != "main",
                )
            )
            candidates = list(res.scalars().all())

        if not candidates:
            return 0

        import datetime as _dt

        now = _dt.datetime.now(_dt.UTC)
        stale_rows: list[tuple[ServerRuntimeModel, bool]] = []
        for rt in candidates:
            target = str(
                getattr(rt, "container_id", None)
                or (
                    build_branch_container_name(server_id, rt.branch_name, rt.id)
                    if rt.branch_name
                    else ""
                )
            ).strip()
            if not getattr(rt, "container_id", None) and rt.status == "starting":
                started_at = getattr(rt, "started_at", None) or getattr(rt, "created_at", None)
                if started_at is not None:
                    if started_at.tzinfo is None:
                        started_at = started_at.replace(tzinfo=_dt.UTC)
                    if (now - started_at).total_seconds() < 120.0:
                        # In-flight export/create — do not reap live starting runtime.
                        continue
            if not target:
                stale_rows.append((rt, True))
                continue
            try:
                rc, out = await self.docker_runner(
                    ["inspect", "-f", "{{.State.Running}}", target]
                )
            except Exception:
                # If Docker itself is unreachable, do not assume the container is dead.
                continue
            is_running = rc == 0 and str(out).strip().lower() == "true"
            if not is_running:
                stale_rows.append((rt, rc != 0))

        if not stale_rows:
            return 0

        reaped = 0
        async with self.session_factory() as session:
            for stale_rt, _container_missing in stale_rows:
                db_rt = await session.get(ServerRuntimeModel, stale_rt.id)
                if db_rt is None or db_rt.status not in active_statuses:
                    continue
                db_rt.status = "stopped"
                db_rt.stopped_at = now
                reaped += 1

                if db_rt.branch_name:
                    br_res = await session.execute(
                        _select(ServerBranchModel).where(
                            ServerBranchModel.server_id == server_id,
                            ServerBranchModel.name == db_rt.branch_name,
                        )
                    )
                    br_row = br_res.scalars().first()
                    if br_row is not None and (
                        br_row.active_runtime_id == db_rt.id
                        or br_row.runtime_status in active_statuses
                    ):
                        br_row.runtime_status = "stopped"
                        br_row.active_runtime_id = None
            await session.commit()

        for stale_rt, _container_missing in stale_rows:
            if stale_rt.port_set_json:
                with contextlib.suppress(Exception):
                    raw_ps = stale_rt.port_set_json
                    parsed = json.loads(raw_ps) if isinstance(raw_ps, str) else raw_ps
                    if isinstance(parsed, dict):
                        release_port_set(HostPortSet.from_dict(parsed))
            if stale_rt.branch_name:
                with contextlib.suppress(Exception):
                    self.branch_service.unlock_worktree(
                        server_id, server_root, stale_rt.branch_name
                    )

        return reaped

    async def start_branch_runtime(self, request: BranchStartRequest) -> BranchStartResult:
        if os.name != "posix":
            raise ServerModeVersioningDisabledError()
        if str(request.server_mode).lower() == "simple":
            raise ServerModeVersioningDisabledError()
        require_docker_provider(request.server_provider)
        if request.branch_name == "main":
            raise ValidationError(
                "Branch runtime engine only launches non-main branches",
                field="branch_name",
            )

        # Mode guard (fail-closed).
        if self.session_factory is not None:
            async with self.session_factory() as _s:
                await ensure_versioning_allowed(request.server_id, session=_s)

        git_branch = self.branch_service.get_branch(
            request.server_id, request.server_root, request.branch_name
        )
        if git_branch is None:
            raise NotFoundError(f"Branch '{request.branch_name}' not found")
        commit_sha = request.commit_sha or git_branch.sha

        rt_overrides: dict[str, Any] = {}
        if git_branch.worktree_path and git_branch.worktree_path.is_dir():
            from app.modules.server.application.branch_settings import (
                load_branch_runtime_overrides,
            )

            rt_overrides = load_branch_runtime_overrides(git_branch.worktree_path)

        effective_req_memory_max = (
            request.requested_memory_mb
            if request.requested_memory_mb is not None
            else rt_overrides.get("max_memory_mb")
        )
        effective_req_memory_min = (
            rt_overrides.get("min_memory_mb")
            if rt_overrides.get("min_memory_mb") is not None
            else request.requested_memory_min_mb
        )
        effective_req_cpu_cores = (
            request.requested_cpu_cores
            if request.requested_cpu_cores is not None
            else rt_overrides.get("cpu_cores")
        )
        effective_cpu_affinity = (
            rt_overrides.get("cpu_affinity")
            if "cpu_affinity" in rt_overrides
            else request.cpu_affinity
        )
        effective_jvm_args = (
            rt_overrides.get("java_args")
            if "java_args" in rt_overrides
            else request.jvm_args
        )
        effective_jvm_flags = (
            shlex.split(effective_jvm_args)
            if isinstance(effective_jvm_args, str) and effective_jvm_args.strip()
            else None
        )

        lockfile = request.lockfile
        if lockfile is None:
            from app.modules.plugin.application.branch_plugins import resolve_branch_lockfile

            lockfile = resolve_branch_lockfile(
                request.server_id,
                Path(request.server_root),
                request.branch_name,
                layout=self.layout,
                commit_sha=commit_sha,
            )

        secrets = request.secrets
        if secrets is None:
            try:
                secrets = self.secret_vault.load_server_secrets(request.server_id)
            except Exception:
                secrets = {}
        secrets = dict(secrets or {})

        self.clean_export_service.assert_no_unresolved_secrets(
            request.server_id, request.server_root, commit_sha, secrets=secrets
        )

        # validate data template (M4)
        template_dir = None
        if request.data_template_id:
            if self.session_factory is None:
                raise ValidationError(
                    "Database session required to resolve data template",
                    field="data_template_id",
                )
            async with self.session_factory() as session:
                row = await session.get(ServerDataTemplateModel, request.data_template_id)
                if row is None or row.server_id != request.server_id:
                    raise NotFoundError(
                        f"Data template '{request.data_template_id}' not found"
                    )
                if row.status != "ready":
                    raise ValidationError("Data template not ready", field="data_template_id")
                allowed_root = self.layout.data_templates_dir(request.server_id)
                candidate = Path(row.storage_path)
                check_not_symlink_or_reparse(candidate)
                try:
                    allowed_real = os.path.realpath(allowed_root)
                    cand_real = os.path.realpath(candidate)
                    if (
                        os.path.commonpath([allowed_real, cand_real]) != allowed_real
                        or cand_real == allowed_real
                    ):
                        raise ValidationError(
                            "Data template storage path outside server template directory",
                            field="data_template_id",
                        )
                except ValueError as exc:
                    raise ValidationError(
                        "Data template storage path outside server template directory",
                        field="data_template_id",
                    ) from exc
                marker = candidate / ".onx-complete.json"
                if not marker.is_file() or marker.is_symlink():
                    raise ValidationError("Data template marker missing", field="data_template_id")
                template_dir = row.storage_path

        # Check if this branch already has a provisioned stopped container on disk.
        existing_stopped_rt = None
        if self.session_factory is not None:
            async with self.session_factory() as session:
                from sqlalchemy import select as _select

                br_res = await session.execute(
                    _select(ServerBranchModel).where(
                        ServerBranchModel.server_id == request.server_id,
                        ServerBranchModel.name == request.branch_name,
                    )
                )
                br_row = br_res.scalars().first()
                if br_row is not None and br_row.active_runtime_id:
                    cand_rt = await session.get(ServerRuntimeModel, br_row.active_runtime_id)
                    if cand_rt is not None and cand_rt.status == "stopped":
                        existing_stopped_rt = cand_rt
                if existing_stopped_rt is None:
                    rt_res = await session.execute(
                        _select(ServerRuntimeModel)
                        .where(
                            ServerRuntimeModel.server_id == request.server_id,
                            ServerRuntimeModel.branch_name == request.branch_name,
                            ServerRuntimeModel.status == "stopped",
                        )
                        .order_by(ServerRuntimeModel.started_at.desc())
                    )
                    existing_stopped_rt = rt_res.scalars().first()

        if existing_stopped_rt is not None:
            raw_export = str(getattr(existing_stopped_rt, "export_path", None) or "").strip()
            existing_export = Path(raw_export) if raw_export else None
            if (
                request.data_template_id is None
                and existing_export is not None
                and existing_export.is_dir()
            ):
                return await self._resume_stopped_runtime(
                    request=request,
                    runtime=existing_stopped_rt,
                    commit_sha=commit_sha,
                    export_root=existing_export,
                    lockfile=lockfile,
                    secrets=secrets,
                    rt_overrides=rt_overrides,
                )
            # New data_template_id or missing export dir -> destroy stale stopped container.
            with contextlib.suppress(Exception):
                await self.destroy_branch_runtime(
                    request.server_id,
                    request.server_root,
                    request.branch_name,
                    runtime_id=existing_stopped_rt.id,
                    keep_port_assignment=False,
                )

        # dynamic class c
        dynamic_class_c: set[str] = set()
        if self.session_factory is not None:
            async with self.session_factory() as session:
                from sqlalchemy import select as _select

                res = await session.execute(
                    _select(ServerDynamicClassCModel).where(
                        ServerDynamicClassCModel.server_id == request.server_id
                    )
                )
                for r in res.scalars().all():
                    dynamic_class_c.add(r.relpath)

        runtime_id = uuid.uuid4().hex
        export_root = Path(request.server_root) / ".onx" / "branch-exports" / runtime_id
        parent = export_root.parent
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "posix":
            check_not_symlink_or_reparse(parent)

        # Reconcile any dead/missing Docker branch runtimes before admission checks
        # so zombie DB rows never permanently block new branch tests.
        await self._reconcile_stale_active_runtimes(
            request.server_id, request.server_root
        )

        port_set = request.port_set
        allocate = port_set is None

        decision = await self.admission_scheduler.admit_branch_runtime(
            server_id=request.server_id,
            branch_name=request.branch_name,
            commit_sha=commit_sha,
            server_type=request.server_type,
            runtime_id=runtime_id,
            requested_memory_mb=effective_req_memory_max,
            requested_cpu_cores=effective_req_cpu_cores,
            max_concurrent_branch_runs=request.max_concurrent_branch_runs,
            port_set=request.port_set,
            allocate_ports=allocate,
            include_query=request.include_query,
            plugin_port_names=request.plugin_port_names,
            check_os_ports=request.check_os_ports,
            data_template_id=request.data_template_id,
            allow_public_test_join=request.allow_public_test_join,
            export_path=str(export_root),
            persist_runtime=True,
        )
        port_set = decision.port_set
        memory_max_mb = decision.memory_max_mb
        memory_min_mb = (
            min(int(effective_req_memory_min), memory_max_mb)
            if effective_req_memory_min is not None
            else decision.memory_min_mb
        )
        cpu_cores = decision.cpu_cores

        container_name = build_branch_container_name(
            request.server_id, request.branch_name, runtime_id
        )

        try:
            uncommitted_changes_warning = self.branch_service.has_uncommitted_changes(
                request.server_id, request.server_root, request.branch_name
            )
        except Exception:
            uncommitted_changes_warning = False

        locked = False
        newly_allocated = allocate
        try:
            self.branch_service.lock_worktree(
                request.server_id,
                request.server_root,
                request.branch_name,
                reason=f"runtime:{runtime_id}",
            )
            locked = True

            rcon_password = generate_rcon_password()

            with _ephemeral_class_c_overlay(
                self.layout, request.server_id, runtime_id, self.class_c_service
            ) as overlay_dir:
                export_req = CleanExportRequest(
                    server_id=request.server_id,
                    server_root=request.server_root,
                    commit_sha=commit_sha,
                    destination=export_root,
                    lockfile=lockfile,
                    panel_properties=port_set.to_panel_properties(rcon_password),
                    jvm_args=effective_jvm_args,
                    secrets=secrets,
                    data_template_dir=template_dir,
                    class_c_overlay_dir=overlay_dir,
                    dynamic_class_c=frozenset(dynamic_class_c),
                    joinable_test_container=not request.allow_public_test_join,
                    export_id=runtime_id,
                )
                export_task = asyncio.create_task(
                    asyncio.to_thread(self.clean_export_service.export, export_req)
                )
                try:
                    await asyncio.shield(export_task)
                except BaseException:
                    with contextlib.suppress(BaseException):
                        await export_task
                    with contextlib.suppress(Exception):
                        _destroy_export_root(request.server_root, export_root)
                    raise

            image = request.image
            if not image:
                effective_mc = getattr(lockfile, "mc", None) or request.minecraft_version
                image = resolve_docker_image(minecraft_version=effective_mc)
            image = validate_docker_image(image)

            uid, gid = resolve_non_root_user(request.uid, request.gid)
            host_mount = resolve_host_mount_path(str(export_root))

            cmd = None
            if lockfile is not None and getattr(lockfile, "lec", None) is not None:
                try:
                    from app.modules.versioning.domain.lockfile import parse_lec_key
                    from app.modules.versioning.infrastructure.clean_export import (
                        _unix_args_relpath,
                    )

                    parts = parse_lec_key(lockfile.lec.key)
                    if parts.loader in {"forge", "neoforge", "quilt"}:
                        cmd = [
                            "java",
                            "@/data/user_jvm_args.txt",
                            f"@/data/{_unix_args_relpath(parts)}",
                            "nogui",
                        ]
                except Exception:
                    cmd = None
            if cmd is None:
                cmd = build_docker_server_cmd(
                    startup_jar=request.startup_jar,
                    jvm_flags=effective_jvm_flags,
                    memory_min_mb=memory_min_mb,
                    memory_max_mb=memory_max_mb,
                    cpu_cores=cpu_cores,
                    image=image,
                    force_itzg_entrypoint=True,
                )

            create_args = build_branch_docker_create_args(
                container_name=container_name,
                image=image,
                network="bridge",
                port_set=port_set,
                memory_min_mb=memory_min_mb,
                memory_max_mb=memory_max_mb,
                cpu_cores=cpu_cores,
                cpu_affinity=effective_cpu_affinity,
                jvm_flags=effective_jvm_flags,
                export_root=export_root,
                host_mount=host_mount,
                uid=uid,
                gid=gid,
                server_id=request.server_id,
                branch_name=request.branch_name,
                runtime_id=runtime_id,
                commit_sha=commit_sha,
                cmd=cmd,
                host_ip=request.host_ip,
                lockfile=lockfile,
            )

            await prepare_data_ownership(
                export_root,
                uid=uid,
                gid=gid,
                image=image,
                mount_source=host_mount,
                run_docker=self.docker_runner,
            )

            rc, out = await self.docker_runner(create_args)
            if rc != 0:
                raise RuntimeError(f"docker create failed: {out}")
            container_id = str(out).strip()

            rc, out = await self.docker_runner(["start", container_name])
            if rc != 0:
                raise RuntimeError(f"docker start failed: {out}")

            # transition DB
            if self.session_factory is not None:
                async with self.session_factory() as session:
                    rt = await session.get(ServerRuntimeModel, runtime_id)
                    if rt is not None:
                        rt.status = "running"
                        rt.container_id = container_id
                    import sqlalchemy as _sqlalchemy

                    br = await session.execute(
                        _sqlalchemy.select(ServerBranchModel).where(
                            ServerBranchModel.server_id == request.server_id,
                            ServerBranchModel.name == request.branch_name,
                        )
                    )
                    branch_row = br.scalars().first()
                    if branch_row is not None:
                        branch_row.runtime_status = "running"
                    await session.commit()

            self._rcon_credentials[runtime_id] = (
                "127.0.0.1",
                port_set.rcon_port,
                rcon_password,
            )

            return BranchStartResult(
                runtime_id=runtime_id,
                server_id=request.server_id,
                branch_name=request.branch_name,
                commit_sha=commit_sha,
                container_name=container_name,
                container_id=container_id,
                port_set=port_set,
                export_path=str(export_root),
                data_template_id=request.data_template_id,
                allow_public_test_join=request.allow_public_test_join,
                memory_max_mb=memory_max_mb,
                cpu_cores=cpu_cores,
                uncommitted_changes_warning=uncommitted_changes_warning,
            )
        except BaseException:
            # rollback
            with contextlib.suppress(Exception):
                await self.docker_runner(["rm", "-f", container_name])
            with contextlib.suppress(Exception):
                _destroy_export_root(request.server_root, export_root)
            if locked:
                with contextlib.suppress(Exception):
                    self.branch_service.unlock_worktree(
                        request.server_id,
                        request.server_root,
                        request.branch_name,
                        expected_reason=f"runtime:{runtime_id}",
                        ignore_unlocked=True,
                    )
            if newly_allocated and port_set is not None:
                with contextlib.suppress(Exception):
                    release_port_set(port_set)
            if self.session_factory is not None:
                with contextlib.suppress(Exception):
                    async with self.session_factory() as session:
                        rt = await session.get(ServerRuntimeModel, runtime_id)
                        if rt is not None:
                            rt.status = "crashed"
                            import datetime as _dt

                            rt.stopped_at = _dt.datetime.now(_dt.UTC)
                        from sqlalchemy import update as _upd

                        await session.execute(
                            _upd(ServerBranchModel)
                            .where(
                                ServerBranchModel.server_id == request.server_id,
                                ServerBranchModel.name == request.branch_name,
                            )
                            .values(
                                runtime_status="stopped",
                                active_runtime_id=None,
                                active_commit_sha=None,
                                active_data_template_id=None,
                                port_set_json=None,
                            )
                        )
                        await session.commit()
            raise

    async def _resume_stopped_runtime(
        self,
        *,
        request: BranchStartRequest,
        runtime: ServerRuntimeModel,
        commit_sha: str,
        export_root: Path,
        lockfile: Any,
        secrets: Mapping[str, str],
        rt_overrides: dict[str, Any] | None = None,
    ) -> BranchStartResult:
        """Start an existing stopped branch container, syncing worktree Class-A/B updates."""
        if self.session_factory is not None:
            async with self.session_factory() as _s:
                await ensure_versioning_allowed(request.server_id, session=_s)

        runtime_id = runtime.id
        port_set = request.port_set
        if port_set is None and getattr(runtime, "port_set_json", None):
            with contextlib.suppress(Exception):
                port_set = HostPortSet.from_dict(runtime.port_set_json)
        if port_set is None:
            raise ValidationError("Stopped runtime missing port set", field="port_set")

        container_name = build_branch_container_name(
            request.server_id, request.branch_name, runtime_id
        )
        try:
            uncommitted_changes_warning = self.branch_service.has_uncommitted_changes(
                request.server_id, request.server_root, request.branch_name
            )
        except Exception:
            uncommitted_changes_warning = False

        # Re-lock worktree while container is running.
        locked = False
        try:
            self.branch_service.lock_worktree(
                request.server_id,
                request.server_root,
                request.branch_name,
                reason=f"runtime:{runtime_id}",
            )
            locked = True

            if lockfile is not None and export_root.is_dir():
                from app.modules.plugin.application.branch_plugins import (
                    sync_lockfile_addons_to_dir,
                )
                from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas

                sync_lockfile_addons_to_dir(
                    request.server_type,
                    export_root,
                    lockfile,
                    ArtifactCas(self.layout.cas),
                    prune=True,
                )

            rcon_password = self._resolve_rcon_password(runtime) or generate_rcon_password()

            # Check if the previously assigned port_set now collides with any DB,
            # live Docker container, or host OS socket binding.
            port_conflict = False
            if self.session_factory is not None:
                from app.core.exceptions import DuplicatePortSetError
                from app.modules.versioning.infrastructure.port_allocator import (
                    allocate_port_set,
                    validate_port_set_atomic,
                )

                async with self.session_factory() as session:
                    from sqlalchemy import select as _select

                    own_br = (
                        await session.execute(
                            _select(ServerBranchModel).where(
                                ServerBranchModel.server_id == request.server_id,
                                ServerBranchModel.name == request.branch_name,
                            )
                        )
                    ).scalars().first()
                    try:
                        await validate_port_set_atomic(
                            session,
                            port_set,
                            exclude_branch_id=own_br.id if own_br is not None else None,
                            exclude_runtime_id=runtime_id,
                            check_os_ports=request.check_os_ports,
                        )
                    except DuplicatePortSetError:
                        port_conflict = True
                        release_port_set(port_set)
                        port_set = await allocate_port_set(
                            session,
                            include_query=port_set.query_port is not None,
                            plugin_port_names=tuple(port_set.plugin_ports.keys()),
                            check_os_ports=request.check_os_ports,
                        )

            # Start existing container; if absent in Docker or ports collided,
            # cleanly remove the stale container and recreate with free ports.
            container_id = str(getattr(runtime, "container_id", None) or "").strip()
            rc = 1
            out = ""
            if not port_conflict:
                rc, out = await self.docker_runner(["start", container_name])
                if rc != 0 and (
                    "port is already allocated" in out.lower()
                    or "address already in use" in out.lower()
                ):
                    port_conflict = True
                    if self.session_factory is not None:
                        from app.modules.versioning.infrastructure.port_allocator import (
                            allocate_port_set,
                        )

                        release_port_set(port_set)
                        async with self.session_factory() as session:
                            port_set = await allocate_port_set(
                                session,
                                include_query=port_set.query_port is not None,
                                plugin_port_names=tuple(port_set.plugin_ports.keys()),
                                check_os_ports=request.check_os_ports,
                            )

            if port_conflict or rc != 0:
                # Remove any stale stopped container holding the old name/port bindings
                with contextlib.suppress(Exception):
                    await self.docker_runner(["rm", "-f", container_name])
                if port_conflict and export_root.is_dir():
                    from app.modules.server.application.services.jar_service import (
                        update_server_properties_key,
                    )

                    props_path = export_root / "server.properties"
                    if props_path.is_file():
                        for prop_k, prop_v in port_set.to_panel_properties(rcon_password).items():
                            with contextlib.suppress(Exception):
                                update_server_properties_key(str(props_path), prop_k, prop_v)

                effective_mc = getattr(lockfile, "mc", None) or request.minecraft_version
                image = request.image or resolve_docker_image(
                    minecraft_version=effective_mc
                )
                image = validate_docker_image(image)
                uid, gid = resolve_non_root_user(request.uid, request.gid)
                host_mount = resolve_host_mount_path(str(export_root))
                overrides = rt_overrides or {}
                eff_max_mem = (
                    request.requested_memory_mb
                    if request.requested_memory_mb is not None
                    else overrides.get("max_memory_mb")
                )
                eff_min_mem = (
                    overrides.get("min_memory_mb")
                    if overrides.get("min_memory_mb") is not None
                    else request.requested_memory_min_mb
                )
                eff_cores = (
                    request.requested_cpu_cores
                    if request.requested_cpu_cores is not None
                    else overrides.get("cpu_cores")
                )
                eff_aff = (
                    overrides.get("cpu_affinity")
                    if "cpu_affinity" in overrides
                    else request.cpu_affinity
                )
                eff_jvm_str = (
                    overrides.get("java_args")
                    if "java_args" in overrides
                    else request.jvm_args
                )
                eff_jvm_flags = (
                    shlex.split(eff_jvm_str)
                    if isinstance(eff_jvm_str, str) and eff_jvm_str.strip()
                    else None
                )
                memory_max_mb = int(eff_max_mem or 4096)
                memory_min_mb = min(
                    int(eff_min_mem) if eff_min_mem is not None else 1024,
                    memory_max_mb,
                )
                cpu_cores = int(eff_cores if eff_cores is not None else 2)
                cmd = build_docker_server_cmd(
                    startup_jar=request.startup_jar,
                    jvm_flags=eff_jvm_flags,
                    memory_min_mb=memory_min_mb,
                    memory_max_mb=memory_max_mb,
                    cpu_cores=cpu_cores,
                    image=image,
                    force_itzg_entrypoint=True,
                )
                create_args = build_branch_docker_create_args(
                    container_name=container_name,
                    image=image,
                    network="bridge",
                    port_set=port_set,
                    memory_min_mb=memory_min_mb,
                    memory_max_mb=memory_max_mb,
                    cpu_cores=cpu_cores,
                    cpu_affinity=eff_aff,
                    jvm_flags=eff_jvm_flags,
                    export_root=export_root,
                    host_mount=host_mount,
                    uid=uid,
                    gid=gid,
                    server_id=request.server_id,
                    branch_name=request.branch_name,
                    runtime_id=runtime_id,
                    commit_sha=commit_sha,
                    cmd=cmd,
                    host_ip=request.host_ip,
                    lockfile=lockfile,
                )
                rc_c, out_c = await self.docker_runner(create_args)
                if rc_c != 0:
                    raise RuntimeError(f"docker create failed: {out_c}")
                container_id = str(out_c).strip()
                rc_s, out_s = await self.docker_runner(["start", container_name])
                if rc_s != 0:
                    raise RuntimeError(f"docker start failed: {out_s}")

            if self.session_factory is not None:
                async with self.session_factory() as session:
                    import sqlalchemy as _sqlalchemy

                    rt = await session.get(ServerRuntimeModel, runtime_id)
                    if rt is not None:
                        rt.status = "running"
                        rt.commit_id = commit_sha
                        rt.port = port_set.game_port
                        rt.port_set_json = port_set.to_dict()
                        if container_id:
                            rt.container_id = container_id
                        rt.stopped_at = None
                    br = await session.execute(
                        _sqlalchemy.select(ServerBranchModel).where(
                            ServerBranchModel.server_id == request.server_id,
                            ServerBranchModel.name == request.branch_name,
                        )
                    )
                    branch_row = br.scalars().first()
                    if branch_row is not None:
                        branch_row.runtime_status = "running"
                        branch_row.active_runtime_id = runtime_id
                        branch_row.active_commit_sha = commit_sha
                        branch_row.port_set_json = port_set.to_dict()
                    await session.commit()

            self._rcon_credentials[runtime_id] = (
                "127.0.0.1",
                port_set.rcon_port,
                rcon_password,
            )

            return BranchStartResult(
                runtime_id=runtime_id,
                server_id=request.server_id,
                branch_name=request.branch_name,
                commit_sha=commit_sha,
                container_name=container_name,
                container_id=container_id or container_name,
                port_set=port_set,
                export_path=str(export_root),
                data_template_id=getattr(runtime, "data_template_id", None),
                allow_public_test_join=bool(getattr(runtime, "allow_public_test_join", False)),
                memory_max_mb=int(request.requested_memory_mb or 4096),
                cpu_cores=int(request.requested_cpu_cores or 2),
                uncommitted_changes_warning=uncommitted_changes_warning,
            )
        except BaseException:
            if locked:
                with contextlib.suppress(Exception):
                    self.branch_service.unlock_worktree(
                        request.server_id,
                        request.server_root,
                        request.branch_name,
                        expected_reason=f"runtime:{runtime_id}",
                        ignore_unlocked=True,
                    )
            raise

    async def stop_branch_runtime(
        self,
        server_id: str,
        server_root: str | os.PathLike[str],
        branch_name: str,
        *,
        runtime_id: str | None = None,
        timeout_seconds: float = 30.0,
        keep_port_assignment: bool = False,
        save_template_name: str | None = None,
        save_template_description: str = "",
    ) -> BranchStopResult:
        _ = keep_port_assignment
        if os.name != "posix":
            raise ServerModeVersioningDisabledError()

        # load runtime (L4)
        runtime = None
        if runtime_id:
            if self.session_factory is None:
                raise NotFoundError(
                    f"Runtime '{runtime_id}' not found for branch '{branch_name}'"
                )
            async with self.session_factory() as session:
                runtime = await session.get(ServerRuntimeModel, runtime_id)
            if (
                runtime is None
                or runtime.server_id != server_id
                or runtime.branch_name != branch_name
            ):
                raise NotFoundError(
                    f"Runtime '{runtime_id}' not found for branch '{branch_name}'"
                )
        else:
            # use repo if available
            repo = getattr(self, "versioning_repo", None)
            if repo is not None:
                runtime = await repo.get_active_runtime_for_branch(server_id, branch_name)
            elif self.session_factory is not None:
                async with self.session_factory() as session:
                    from sqlalchemy import select as _select

                    res = await session.execute(
                        _select(ServerRuntimeModel).where(
                            ServerRuntimeModel.server_id == server_id,
                            ServerRuntimeModel.branch_name == branch_name,
                            ServerRuntimeModel.status.in_(("starting", "running")),
                        )
                    )
                    runtime = res.scalars().first()
        if runtime is None:
            raise NotFoundError("No active runtime for branch")

        rid = runtime.id
        container_name = build_branch_container_name(server_id, branch_name, rid)

        saved_template = None
        exit_code = None
        oom_killed = False
        try:
            # docker stop
            with contextlib.suppress(Exception):
                await self.docker_runner(
                    ["stop", "-t", str(int(timeout_seconds)), container_name]
                )
            # inspect
            with contextlib.suppress(Exception):
                rc, out = await self.docker_runner(["inspect", container_name])
                try:
                    data = json.loads(out)
                    if isinstance(data, list) and data:
                        state = data[0].get("State", {})
                        exit_code = state.get("ExitCode")
                        oom_killed = bool(state.get("OOMKilled", False))
                except Exception:
                    pass

            if save_template_name:
                saved_template = await self.save_data_template(
                    server_id,
                    branch_name,
                    name=save_template_name,
                    description=save_template_description,
                    runtime_id=rid,
                )
        finally:
            await _teardown_branch_exposure_best_effort(server_id, branch_name)
            with contextlib.suppress(Exception):
                self.branch_service.unlock_worktree(
                    server_id,
                    server_root,
                    branch_name,
                    expected_reason=f"runtime:{rid}",
                    ignore_unlocked=True,
                )
            self._rcon_credentials.pop(rid, None)
            if self.session_factory is not None:
                with contextlib.suppress(Exception):
                    async with self.session_factory() as session:
                        rt = await session.get(ServerRuntimeModel, rid)
                        if rt is not None:
                            rt.status = "stopped"
                            import datetime as _dt

                            rt.stopped_at = _dt.datetime.now(_dt.UTC)
                            rt.exit_code = exit_code
                            rt.oom_killed = oom_killed
                        from sqlalchemy import update as _upd

                        await session.execute(
                            _upd(ServerBranchModel)
                            .where(
                                ServerBranchModel.server_id == server_id,
                                ServerBranchModel.name == branch_name,
                            )
                            .values(
                                runtime_status="stopped",
                                active_runtime_id=rid,
                                active_commit_sha=getattr(runtime, "commit_id", None),
                                active_data_template_id=getattr(
                                    runtime, "data_template_id", None
                                ),
                                port_set_json=runtime.port_set_json,
                            )
                        )
                        await session.commit()

        return BranchStopResult(
            runtime_id=rid,
            server_id=server_id,
            branch_name=branch_name,
            saved_template=saved_template,
            exit_code=exit_code,
            oom_killed=oom_killed,
        )

    async def destroy_branch_runtime(
        self,
        server_id: str,
        server_root: str | os.PathLike[str],
        branch_name: str,
        *,
        runtime_id: str | None = None,
        timeout_seconds: float = 30.0,
        keep_port_assignment: bool = False,
    ) -> BranchDestroyResult:
        """Explicitly stop, remove, and wipe a provisioned branch container & export."""
        if os.name != "posix":
            raise ServerModeVersioningDisabledError()

        runtime = None
        if self.session_factory is not None:
            async with self.session_factory() as session:
                from sqlalchemy import select as _select

                if runtime_id:
                    runtime = await session.get(ServerRuntimeModel, runtime_id)
                else:
                    res = await session.execute(
                        _select(ServerRuntimeModel)
                        .where(
                            ServerRuntimeModel.server_id == server_id,
                            ServerRuntimeModel.branch_name == branch_name,
                            ServerRuntimeModel.status.in_(("starting", "running", "stopped")),
                        )
                        .order_by(ServerRuntimeModel.started_at.desc())
                    )
                    runtime = res.scalars().first()
                    if runtime is None:
                        br_res = await session.execute(
                            _select(ServerBranchModel).where(
                                ServerBranchModel.server_id == server_id,
                                ServerBranchModel.name == branch_name,
                            )
                        )
                        br = br_res.scalars().first()
                        if br is not None and br.active_runtime_id:
                            runtime = await session.get(ServerRuntimeModel, br.active_runtime_id)

        if (
            runtime is None
            or runtime.server_id != server_id
            or runtime.branch_name != branch_name
        ):
            raise NotFoundError(f"No provisioned container for branch '{branch_name}'")

        rid = runtime.id
        port_set = None
        if getattr(runtime, "port_set_json", None):
            try:
                port_set = HostPortSet.from_dict(runtime.port_set_json)
            except Exception:
                port_set = None
        fallback = Path(server_root) / ".onx" / "branch-exports" / rid
        export_path = Path(getattr(runtime, "export_path", None) or fallback)
        container_name = build_branch_container_name(server_id, branch_name, rid)

        try:
            if runtime.status in ("starting", "running"):
                with contextlib.suppress(Exception):
                    await self.docker_runner(
                        ["stop", "-t", str(int(timeout_seconds)), container_name]
                    )
            with contextlib.suppress(Exception):
                await self.docker_runner(["rm", "-f", container_name])
        finally:
            await _teardown_branch_exposure_best_effort(server_id, branch_name)
            with contextlib.suppress(Exception):
                _destroy_export_root(server_root, export_path)
            with contextlib.suppress(Exception):
                self.branch_service.unlock_worktree(
                    server_id,
                    server_root,
                    branch_name,
                    expected_reason=f"runtime:{rid}",
                    ignore_unlocked=True,
                )
            self._rcon_credentials.pop(rid, None)
            if port_set is not None and not keep_port_assignment:
                with contextlib.suppress(Exception):
                    release_port_set(port_set)
            if self.session_factory is not None:
                with contextlib.suppress(Exception):
                    async with self.session_factory() as session:
                        rt = await session.get(ServerRuntimeModel, rid)
                        if rt is not None:
                            rt.status = "terminated"
                            import datetime as _dt

                            if rt.stopped_at is None:
                                rt.stopped_at = _dt.datetime.now(_dt.UTC)
                        from sqlalchemy import update as _upd

                        await session.execute(
                            _upd(ServerBranchModel)
                            .where(
                                ServerBranchModel.server_id == server_id,
                                ServerBranchModel.name == branch_name,
                            )
                            .values(
                                runtime_status="stopped",
                                active_runtime_id=None,
                                active_commit_sha=None,
                                active_data_template_id=None,
                                port_set_json=(
                                    runtime.port_set_json if keep_port_assignment else None
                                ),
                            )
                        )
                        await session.commit()

        return BranchDestroyResult(
            runtime_id=rid,
            server_id=server_id,
            branch_name=branch_name,
            container_name=container_name,
            released_ports=not keep_port_assignment,
        )

    async def save_data_template(
        self,
        server_id: str,
        branch_name: str,
        *,
        name: str,
        description: str = "",
        runtime_id: str | None = None,
        template_id: str | None = None,
    ) -> SaveTemplateResult:
        if os.name != "posix":
            raise ServerModeVersioningDisabledError()
        if not isinstance(name, str) or not name or len(name) > 100:
            raise ValidationError("Invalid template name", field="name")

        # resolve runtime (L4)
        runtime = None
        if runtime_id:
            if self.session_factory is None:
                raise NotFoundError(
                    f"Runtime '{runtime_id}' not found for branch '{branch_name}'"
                )
            async with self.session_factory() as session:
                runtime = await session.get(ServerRuntimeModel, runtime_id)
            if (
                runtime is None
                or runtime.server_id != server_id
                or runtime.branch_name != branch_name
            ):
                raise NotFoundError(
                    f"Runtime '{runtime_id}' not found for branch '{branch_name}'"
                )
        elif self.session_factory is not None:
            async with self.session_factory() as session:
                from sqlalchemy import select as _select

                res = await session.execute(
                    _select(ServerRuntimeModel).where(
                        ServerRuntimeModel.server_id == server_id,
                        ServerRuntimeModel.branch_name == branch_name,
                        ServerRuntimeModel.status.in_(
                            ("starting", "running", "stopped", "terminated")
                        ),
                    )
                )
                runtime = res.scalars().first()
        if runtime is None:
            raise NotFoundError("Runtime not found")
        rid = runtime.id
        export_path = Path(getattr(runtime, "export_path", None) or "")
        if not export_path or not export_path.is_dir():
            raise ValidationError("Export path missing", field="export_path")

        tid = template_id or uuid.uuid4().hex

        port_set = None
        if getattr(runtime, "port_set_json", None):
            try:
                port_set = HostPortSet.from_dict(runtime.port_set_json)
            except Exception:
                port_set = None
        if port_set is None and self.session_factory is not None:  # fallback from branch
                async with self.session_factory() as session:
                    from sqlalchemy import select as _select

                    res = await session.execute(
                        _select(ServerBranchModel).where(
                            ServerBranchModel.server_id == server_id,
                            ServerBranchModel.name == branch_name,
                        )
                    )
                    br = res.scalars().first()
                    if br is not None and br.port_set_json:
                        port_set = HostPortSet.from_dict(br.port_set_json)

        # rcon password
        creds = self._rcon_credentials.get(rid)
        if creds is not None:
            rcon_password = creds[2]
        else:
            rcon_password = None
            props_path = export_path / "server.properties"
            if props_path.is_file():
                try:
                    from app.core.allowlist import open_safe_path_fd

                    fd = open_safe_path_fd(str(export_path), "server.properties", flags=os.O_RDONLY)
                    try:
                        data = os.read(fd, 1024 * 1024)
                    finally:
                        os.close(fd)
                    for line in data.decode("utf-8", errors="replace").splitlines():
                        if line.strip().startswith("rcon.password="):
                            rcon_password = line.split("=", 1)[1].strip()
                            break
                except Exception:
                    rcon_password = ""
            if rcon_password is None:
                rcon_password = ""

        container_name = build_branch_container_name(server_id, branch_name, rid)
        state_adapter = _BranchContainerStateAdapter(self.docker_runner, container_name)
        rcon_adapter = _BranchRconQuiesceAdapter(
            "127.0.0.1",
            port_set.rcon_port if port_set is not None else 25575,
            rcon_password,
            self.rcon_client_factory,
        )
        save_off_store = _ServerSaveOffStore(self.session_factory)

        svc = self.data_template_service
        if svc is None:
            svc = DataTemplateService(self.layout)
        self.data_template_service = svc

        async with self.session_factory() as session:
            storage_path = await svc.clone(
                server_id,
                export_path,
                tid,
                source_commit_sha=getattr(runtime, "commit_id", None),
                source_branch_name=branch_name,
                rcon=rcon_adapter,
                container_state=state_adapter,
                save_off_store=save_off_store,
                db_session=session,
            )
            # ensure row details
            row = await session.get(ServerDataTemplateModel, tid)
            if row is None:
                row = ServerDataTemplateModel(
                    id=tid,
                    server_id=server_id,
                    name=name,
                    description=description,
                    source_branch_name=branch_name,
                    source_commit_sha=getattr(runtime, "commit_id", None),
                    storage_path=str(storage_path),
                    status="ready",
                )
                session.add(row)
            else:
                row.name = name
                row.description = description
                row.source_branch_name = branch_name
                row.source_commit_sha = getattr(runtime, "commit_id", None)
                row.status = "ready"
                row.storage_path = str(storage_path)
            await session.commit()

        file_count = None
        total_bytes = None
        marker_path = Path(storage_path) / ".onx-complete.json"
        if marker_path.is_file():
            try:
                m = json.loads(marker_path.read_text(encoding="utf-8"))
                file_count = m.get("file_count")
                total_bytes = m.get("total_bytes")
            except Exception:
                pass

        return SaveTemplateResult(
            template_id=tid,
            server_id=server_id,
            name=name,
            storage_path=str(storage_path),
            source_branch_name=branch_name,
            source_commit_sha=getattr(runtime, "commit_id", None),
            file_count=file_count,
            total_bytes=total_bytes,
        )

    async def get_branch_runtime_status(
        self,
        server_id: str,
        branch_name: str,
        *,
        server_root: str | os.PathLike[str] | None = None,
    ) -> dict[str, Any]:
        if os.name != "posix":
            raise ServerModeVersioningDisabledError()
        runtime = None
        branch_row = None
        resolved_root = server_root
        if self.session_factory is not None:
            async with self.session_factory() as session:
                from sqlalchemy import select as _select

                res = await session.execute(
                    _select(ServerRuntimeModel)
                    .where(
                        ServerRuntimeModel.server_id == server_id,
                        ServerRuntimeModel.branch_name == branch_name,
                        ServerRuntimeModel.status.in_(("starting", "running")),
                    )
                    .order_by(ServerRuntimeModel.started_at.desc())
                )
                runtime = res.scalars().first()
                res2 = await session.execute(
                    _select(ServerBranchModel).where(
                        ServerBranchModel.server_id == server_id,
                        ServerBranchModel.name == branch_name,
                    )
                )
                branch_row = res2.scalars().first()
                if runtime is None and branch_row is not None and branch_row.active_runtime_id:
                    cand = await session.get(ServerRuntimeModel, branch_row.active_runtime_id)
                    if cand is not None and cand.status in ("starting", "running", "stopped"):
                        runtime = cand
                if resolved_root is None:
                    from app.modules.server.infrastructure.models import ServerModel

                    srv = await session.get(ServerModel, server_id)
                    if srv is not None:
                        resolved_root = getattr(srv, "root_path", None)

        port_set = None
        if runtime is not None and getattr(runtime, "port_set_json", None):
            try:
                port_set = HostPortSet.from_dict(runtime.port_set_json)
            except Exception:
                port_set = None
        if (
            port_set is None
            and branch_row is not None
            and getattr(branch_row, "port_set_json", None)
        ):
            try:
                port_set = HostPortSet.from_dict(branch_row.port_set_json)
            except Exception:
                port_set = None

        container_liveness = None
        if runtime is not None:
            container_name = build_branch_container_name(server_id, branch_name, runtime.id)
            try:
                rc, out = await self.docker_runner(
                    ["inspect", "-f", "{{.State.Running}}", container_name]
                )
                container_liveness = rc == 0 and str(out).strip().lower() == "true"
            except Exception:
                container_liveness = None

        worktree_locked = None
        worktree_lock_reason = None
        if resolved_root:
            try:
                info = self.branch_service.get_branch(server_id, resolved_root, branch_name)
                if info is not None:
                    worktree_locked = bool(info.worktree_locked)
                    worktree_lock_reason = info.worktree_lock_reason
            except Exception:
                worktree_locked = None
                worktree_lock_reason = None

        if runtime is not None:
            status = getattr(runtime, "status", None)
        elif branch_row is not None:
            status = getattr(branch_row, "runtime_status", None)
        else:
            status = None

        active_commit_sha = None
        if runtime is not None:
            active_commit_sha = getattr(runtime, "commit_id", None)
        if active_commit_sha is None and branch_row is not None:
            active_commit_sha = getattr(branch_row, "active_commit_sha", None)

        data_template_id = None
        if runtime is not None:
            data_template_id = getattr(runtime, "data_template_id", None)
        if data_template_id is None and branch_row is not None:
            data_template_id = getattr(branch_row, "active_data_template_id", None)

        allow_public_test_join = False
        if runtime is not None:
            allow_public_test_join = bool(getattr(runtime, "allow_public_test_join", False))

        container_provisioned = bool(
            runtime is not None
            and getattr(runtime, "status", None) in ("starting", "running", "stopped")
        )
        container_name = (
            build_branch_container_name(server_id, branch_name, runtime.id)
            if container_provisioned and runtime is not None
            else None
        )

        return {
            "server_id": server_id,
            "branch_name": branch_name,
            "runtime_status": status,
            "container_provisioned": container_provisioned,
            "container_name": container_name,
            "runtime_id": getattr(runtime, "id", None),
            "active_commit_sha": active_commit_sha,
            "data_template_id": data_template_id,
            "allow_public_test_join": allow_public_test_join,
            "container_liveness": container_liveness,
            "port_set": port_set.to_dict() if port_set is not None else None,
            "worktree_locked": worktree_locked,
            "worktree_lock_reason": worktree_lock_reason,
        }

    async def get_branch_console_logs(
        self,
        server_id: str,
        branch_name: str,
        *,
        tail: int = 200,
    ) -> dict[str, Any]:
        if os.name != "posix":
            raise ServerModeVersioningDisabledError()
        runtime = None
        if self.session_factory is not None:
            async with self.session_factory() as session:
                from sqlalchemy import select as _select

                res = await session.execute(
                    _select(ServerRuntimeModel)
                    .where(
                        ServerRuntimeModel.server_id == server_id,
                        ServerRuntimeModel.branch_name == branch_name,
                        ServerRuntimeModel.status.in_(("starting", "running", "stopped")),
                    )
                    .order_by(ServerRuntimeModel.started_at.desc())
                )
                runtime = res.scalars().first()
                if runtime is None:
                    br_res = await session.execute(
                        _select(ServerBranchModel).where(
                            ServerBranchModel.server_id == server_id,
                            ServerBranchModel.name == branch_name,
                        )
                    )
                    br = br_res.scalars().first()
                    if br is not None and br.active_runtime_id:
                        cand = await session.get(ServerRuntimeModel, br.active_runtime_id)
                        if cand is not None and cand.status in ("starting", "running", "stopped"):
                            runtime = cand
        if runtime is None:
            raise NotFoundError(f"No provisioned runtime for branch '{branch_name}'")
        container_name = build_branch_container_name(server_id, branch_name, runtime.id)
        rc, out = await self.docker_runner(
            ["logs", "--tail", str(tail), container_name]
        )
        if rc != 0:
            raise InfrastructureError(
                f"Failed to read container logs for branch '{branch_name}'"
            )
        return {
            "server_id": server_id,
            "branch_name": branch_name,
            "runtime_id": runtime.id,
            "container_name": container_name,
            "lines": out.splitlines() if out else [],
        }

    async def send_branch_console_command(
        self,
        server_id: str,
        branch_name: str,
        command: str,
    ) -> dict[str, Any]:
        if os.name != "posix":
            raise ServerModeVersioningDisabledError()
        cmd = str(command or "").strip().lstrip("/")
        if not cmd or any(ch in cmd for ch in ("\r", "\n", "\x00")):
            raise ValidationError("Invalid console command", field="command")
        runtime = None
        if self.session_factory is not None:
            async with self.session_factory() as session:
                from sqlalchemy import select as _select

                res = await session.execute(
                    _select(ServerRuntimeModel).where(
                        ServerRuntimeModel.server_id == server_id,
                        ServerRuntimeModel.branch_name == branch_name,
                        ServerRuntimeModel.status.in_(("starting", "running")),
                    )
                )
                runtime = res.scalars().first()
        if runtime is None:
            raise NotFoundError(f"No active runtime for branch '{branch_name}'")

        port_set = None
        if getattr(runtime, "port_set_json", None):
            try:
                port_set = HostPortSet.from_dict(runtime.port_set_json)
            except Exception:
                port_set = None
        rcon_port = port_set.rcon_port if port_set is not None else None
        if rcon_port is None:
            raise ValidationError("RCON port unavailable", field="rcon_port")

        rcon_password = self._resolve_rcon_password(runtime)

        client_factory = self.rcon_client_factory or AsyncRCONClient
        client = client_factory("127.0.0.1", rcon_port, rcon_password)
        output = ""
        try:
            await client.connect()
            output = await client.send_command(cmd)
        except Exception as exc:
            raise InfrastructureError(
                "Failed to dispatch RCON command to branch runtime"
            ) from exc
        finally:
            with contextlib.suppress(Exception):
                await client.close()
        return {
            "server_id": server_id,
            "branch_name": branch_name,
            "runtime_id": runtime.id,
            "command": cmd,
            "output": output,
        }

    def _resolve_rcon_password(self, runtime: Any) -> str:
        rid = getattr(runtime, "id", None)
        if rid is not None:
            creds = self._rcon_credentials.get(rid)
            if creds is not None:
                return creds[2]
        export_path = Path(getattr(runtime, "export_path", None) or "")
        rcon_password = None
        props_path = export_path / "server.properties" if export_path else None
        if props_path is not None and props_path.is_file():
            try:
                from app.core.allowlist import open_safe_path_fd

                fd = open_safe_path_fd(
                    str(export_path), "server.properties", flags=os.O_RDONLY
                )
                try:
                    data = os.read(fd, 1024 * 1024)
                finally:
                    os.close(fd)
                for line in data.decode("utf-8", errors="replace").splitlines():
                    if line.strip().startswith("rcon.password="):
                        rcon_password = line.split("=", 1)[1].strip()
                        break
            except Exception:
                rcon_password = ""
        if rcon_password is None:
            rcon_password = ""
        return rcon_password
