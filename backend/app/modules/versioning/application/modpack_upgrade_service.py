"""Modpack install, 1-click upgrade orchestration, and Simple 5-step staging (P5.5).

Covers:
- ``SQLServerUpgradeRepository``: async CRUD over ``server_upgrades``.
- ``SimpleStagingExporter``: Git-free 5-step clean staging into ``<server_root>.staging/``.
- ``ModpackUpgradeService``:
  - ``plan_upgrade`` (Simple baseline adoption + hash-only compatibility matrix)
  - ``resolve_manual_upload`` (CurseForge manual upload verification + matrix re-eval)
  - ``prepare_advanced_upgrade_branch`` (blocker gate, CAS/LEC, ``upgrade/<target>``, 3-way merge)
  - ``start_advanced_upgrade_test`` (disposable ``DataTemplateService`` clone + branch runtime)
  - ``apply_advanced_upgrade_to_live`` (discard test template, quiesce+backup BEFORE merge, gate)
  - ``execute_simple_upgrade`` (blocker gate, baseline lockfile, 3-way merge, Simple 5-step swap)
  - ``confirm_upgrade_and_unpin`` (unpins backup + Class-C snapshot, confirms journal)
  - ``emergency_rollback_upgrade`` (triad rollback + lockfile restore)
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import re
import shutil
import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import delete, select

from app.core.allowlist import (
    SymlinkEscapeError,
    classify,
    open_safe_path_fd,
    validate_canonical_relpath,
)
from app.core.exceptions import (
    ConflictError,
    LecMissingError,
    MergeConflictError,
    NotFoundError,
    ServerModeVersioningDisabledError,
    ValidationError,
)
from app.core.host_state import HostStateLayout, validate_server_segment
from app.modules.plugin.infrastructure.providers.modrinth import ModrinthProvider
from app.modules.server.application.services.jar_service import (
    resolve_paper_build,
)
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.application.baseline_adoption import (
    ensure_simple_baseline_lockfile,
)
from app.modules.versioning.application.lockfile_service import LockfileService
from app.modules.versioning.application.refresh_orchestrator import (
    RETENTION_UNTIL_CONFIRM,
    LiveRefreshRequest,
    LiveRefreshResult,
    LiveRefreshService,
    RollbackResult,
)
from app.modules.versioning.application.upgrade_health_gate import (
    UpgradeHealthGateEvaluator,
)
from app.modules.versioning.application.upgrade_merge import (
    assert_tree_ready_for_upgrade_export,
    merge_upgrade_configs,
)
from app.modules.versioning.domain.lockfile import (
    EnvServer,
    LecRef,
    LoaderRef,
    LockfileFile,
    LockfileV21,
    ModpackRef,
    Origin,
    dump_lockfile,
    parse_lockfile,
)
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.branch_runtime_service import (
    BranchRuntimeService,
    BranchStartRequest,
    BranchStartResult,
)
from app.modules.versioning.infrastructure.clean_export import (
    _FORBIDDEN_EXPORT_NAMES,
    CleanExportRequest,
    CleanExportService,
)
from app.modules.versioning.infrastructure.curseforge_adapter import (
    resolve_manual_download_upload,
)
from app.modules.versioning.infrastructure.data_templates import DataTemplateService
from app.modules.versioning.infrastructure.download_allowlist import (
    VerifiedDownloadResult,
    download_verified_to_cas,
)
from app.modules.versioning.infrastructure.fs_atomic import atomic_write_private
from app.modules.versioning.infrastructure.git_branches import GitBranchService
from app.modules.versioning.infrastructure.git_merge import GitMergeService
from app.modules.versioning.infrastructure.git_repository import validate_server_root
from app.modules.versioning.infrastructure.git_save_commit import GitSaveCommitService
from app.modules.versioning.infrastructure.lec_builder import LecBuilder
from app.modules.versioning.infrastructure.lec_store import LecStore
from app.modules.versioning.infrastructure.models import (
    ServerDataTemplateModel,
    ServerUpgradeModel,
)
from app.modules.versioning.infrastructure.modpack_parser import (
    MAX_CLASS_B_FILE_BYTES,
    InstallPlan,
    InstallPlanFile,
    InstallPlanOverride,
    ManualDownloadBlocker,
)
from app.modules.versioning.infrastructure.refresh_journal import RefreshJournalRecord
from app.modules.versioning.infrastructure.upgrade_matrix import (
    CompatibilityMatrix,
    MatrixStatus,
    build_compatibility_matrix,
)

_TERMINAL_UPGRADE_STATUSES = frozenset({"confirmed", "rolled_back", "failed", "cancelled"})
_SKIP_TREE_DIRS = frozenset({".git", ".onx", ".onx-manager", ".mcsmanager"})


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _sanitize_upgrade_slug(raw: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(raw).strip()).strip("-.")
    return (cleaned or "target")[:64]


def _install_plan_from_dict(data: Mapping[str, Any]) -> InstallPlan:
    files = tuple(
        InstallPlanFile(
            path=str(item["path"]),
            sha1=str(item["sha1"]),
            size=int(item["size"]),
            downloads=tuple(str(u) for u in (item.get("downloads") or ())),
            sha512=item.get("sha512"),
            sha256=item.get("sha256"),
            env_server=str(item.get("env_server") or EnvServer.REQUIRED.value),
            optional=bool(item.get("optional", False)),
            origin=Origin(str(item.get("origin") or Origin.MODRINTH.value)),
            project_id=item.get("project_id"),
            version_id=item.get("version_id"),
            source_layer=str(item.get("source_layer") or "index"),
            curseforge_project_id=item.get("curseforge_project_id"),
            curseforge_file_id=item.get("curseforge_file_id"),
        )
        for item in (data.get("files") or ())
    )
    overrides = tuple(
        InstallPlanOverride(
            path=str(item["path"]),
            archive_path=str(item["archive_path"]),
            source_layer=str(item["source_layer"]),
            classification=str(item["classification"]),
            sha256=str(item["sha256"]),
            sha512=str(item["sha512"]),
            sha1=str(item["sha1"]),
            size=int(item["size"]),
        )
        for item in (data.get("overrides") or ())
    )
    blockers = tuple(
        ManualDownloadBlocker(
            path=str(item["path"]),
            filename=str(item["filename"]),
            project_id=item.get("project_id"),
            file_id=item.get("file_id"),
            webpage_url=str(item.get("webpage_url") or ""),
            expected_size=item.get("expected_size"),
            expected_sha1=item.get("expected_sha1"),
            expected_sha512=item.get("expected_sha512"),
            required=bool(item.get("required", True)),
            reason=str(item.get("reason") or "download_url_null"),
            blocker_type=str(item.get("blocker_type") or "manual_download_required"),
            resolved=bool(item.get("resolved", False)),
            resolved_sha256=item.get("resolved_sha256"),
        )
        for item in (data.get("manual_blockers") or ())
    )
    return InstallPlan(
        source=str(data["source"]),
        project_id=str(data["project_id"]),
        version_id=str(data["version_id"]),
        version_label=str(data["version_label"]),
        index_sha256=str(data["index_sha256"]),
        mc_version=str(data["mc_version"]),
        loader_id=str(data["loader_id"]),
        loader_version=str(data["loader_version"]),
        files=files,
        overrides=overrides,
        manual_blockers=blockers,
        skipped_client_files=tuple(str(p) for p in (data.get("skipped_client_files") or ())),
        skipped_optional_files=tuple(str(p) for p in (data.get("skipped_optional_files") or ())),
        skipped_client_override_jars=tuple(
            str(p) for p in (data.get("skipped_client_override_jars") or ())
        ),
        discarded_paths=tuple(str(p) for p in (data.get("discarded_paths") or ())),
        warnings=tuple(str(w) for w in (data.get("warnings") or ())),
    )


def _write_safe_file(root: Path, relpath: str, data: bytes) -> None:
    norm = validate_canonical_relpath(relpath)
    fd = open_safe_path_fd(
        str(root),
        norm,
        flags=os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        mode=0o644,
        allow_create_parents=True,
    )
    try:
        offset = 0
        view = memoryview(data)
        while offset < len(data):
            written = os.write(fd, view[offset:])
            if written <= 0:
                raise OSError("short write")
            offset += written
    finally:
        os.close(fd)


def _collect_class_b_from_dir(root: Path) -> dict[str, bytes]:
    collected: dict[str, bytes] = {}
    if not root.is_dir() or root.is_symlink():
        return collected
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_TREE_DIRS)
        for filename in sorted(filenames):
            full = Path(dirpath) / filename
            if full.is_symlink():
                continue
            relpath = full.relative_to(root).as_posix()
            if classify(relpath) != "B":
                continue
            try:
                fd = open_safe_path_fd(str(root), relpath, flags=os.O_RDONLY)
            except (OSError, SymlinkEscapeError):
                continue
            try:
                st = os.fstat(fd)
                if st.st_size > MAX_CLASS_B_FILE_BYTES:
                    continue
                data = os.read(fd, MAX_CLASS_B_FILE_BYTES + 1)
            finally:
                os.close(fd)
            if len(data) <= MAX_CLASS_B_FILE_BYTES:
                collected[relpath] = data
    return collected


class SQLServerUpgradeRepository:
    """Async SQLAlchemy repository for ``server_upgrades`` rows."""

    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self._session_factory = session_factory

    async def create(
        self,
        *,
        server_id: str,
        target_mc: str,
        target_loader_id: str,
        target_loader_version: str,
        mode: str = "simple",
        kind: str = "server_upgrade",
        status: str = "planned",
        source_mc: str | None = None,
        source_loader_id: str | None = None,
        source_loader_version: str | None = None,
        target_lec_key: str | None = None,
        upgrade_branch: str | None = None,
        operation_id: str | None = None,
        plan_json: dict[str, Any] | None = None,
        matrix_json: dict[str, Any] | None = None,
        manual_blockers_json: list[dict[str, Any]] | None = None,
        upgrade_id: str | None = None,
    ) -> ServerUpgradeModel:
        now = _utcnow()
        row = ServerUpgradeModel(
            id=upgrade_id or str(uuid.uuid4()),
            server_id=server_id,
            kind=kind,
            mode=mode,
            status=status,
            source_mc=source_mc,
            target_mc=target_mc,
            source_loader_id=source_loader_id,
            source_loader_version=source_loader_version,
            target_loader_id=target_loader_id,
            target_loader_version=target_loader_version,
            target_lec_key=target_lec_key,
            upgrade_branch=upgrade_branch,
            operation_id=operation_id,
            plan_json=plan_json,
            matrix_json=matrix_json,
            manual_blockers_json=manual_blockers_json,
            pinned_until_confirm=False,
            health_gate_passed=False,
            created_at=now,
            updated_at=now,
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def get(self, upgrade_id: str) -> ServerUpgradeModel | None:
        async with self._session_factory() as session:
            return await session.get(ServerUpgradeModel, upgrade_id)

    async def get_active_for_server(self, server_id: str) -> ServerUpgradeModel | None:
        async with self._session_factory() as session:
            res = await session.execute(
                select(ServerUpgradeModel)
                .where(
                    ServerUpgradeModel.server_id == server_id,
                    ~ServerUpgradeModel.status.in_(tuple(_TERMINAL_UPGRADE_STATUSES)),
                )
                .order_by(ServerUpgradeModel.created_at.desc())
            )
            return res.scalars().first()

    async def list_for_server(self, server_id: str) -> list[ServerUpgradeModel]:
        async with self._session_factory() as session:
            res = await session.execute(
                select(ServerUpgradeModel)
                .where(ServerUpgradeModel.server_id == server_id)
                .order_by(ServerUpgradeModel.created_at.desc())
            )
            return list(res.scalars().all())

    async def update_status(
        self,
        upgrade_id: str,
        status: str,
        **fields: Any,
    ) -> ServerUpgradeModel:
        async with self._session_factory() as session:
            row = await session.get(ServerUpgradeModel, upgrade_id)
            if row is None:
                raise NotFoundError(f"Server upgrade '{upgrade_id}' not found")
            writable = cast(Any, row)
            writable.status = status
            writable.updated_at = _utcnow()
            for key, value in fields.items():
                if not hasattr(row, key):
                    raise ValidationError(
                        f"Unknown ServerUpgradeModel field '{key}'", field="field"
                    )
                setattr(writable, key, value)
            await session.commit()
            await session.refresh(row)
            return row


class SimpleStagingExporter:
    """Git-free 5-step Simple Mode clean staging into ``<server_root>.staging/``."""

    def __init__(
        self,
        layout: HostStateLayout,
        *,
        target_lockfile: LockfileV21,
        merged_class_b: Mapping[str, bytes] | None = None,
        deleted_class_b: Iterable[str] = (),
        cas: ArtifactCas | None = None,
        lec_store: LecStore | None = None,
        panel_properties: Mapping[str, str] | None = None,
        jvm_args: str = "",
        secrets: Mapping[str, str] | None = None,
    ) -> None:
        self._layout = layout
        self._target_lockfile = target_lockfile
        self._merged_class_b = dict(merged_class_b or {})
        self._deleted_class_b = frozenset(deleted_class_b)
        self._cas = cas or ArtifactCas(layout.cas)
        self._lec_store = lec_store or LecStore(layout)
        self._panel_properties = dict(panel_properties or {})
        self._jvm_args = jvm_args
        self._secrets = dict(secrets or {})
        self._clean_export = CleanExportService(layout, cas=self._cas)

    def __call__(
        self,
        staging: Path,
        commit_sha: str,
        *,
        export_id: str,
        fencing_verifier: Callable[[], None],
    ) -> None:
        del commit_sha  # Simple mode is Git-free.
        if os.name != "posix":
            raise ServerModeVersioningDisabledError(
                "Staging swap requires a POSIX host"
            )
        destination = self._clean_export._prepare_destination(staging)
        try:
            # Step 2: write merged Class-B files
            for relpath, content in sorted(self._merged_class_b.items()):
                norm = validate_canonical_relpath(relpath)
                if norm in self._deleted_class_b:
                    continue
                if norm.lower() in _FORBIDDEN_EXPORT_NAMES:
                    raise ValidationError(
                        f"Forbidden executable rejected in staging: '{norm}'",
                        field="path",
                    )
                if classify(norm) != "B":
                    raise ValidationError(
                        f"Simple staging Class-B map received non-Class-B path: '{norm}'",
                        field="path",
                    )
                _write_safe_file(destination, norm, content)

            # Informational lockfile copy inside container staging tree
            _write_safe_file(
                destination,
                ".onx-manager/onx-jars.lock.json",
                dump_lockfile(self._target_lockfile),
            )

            # Step 3: materialize Class-A binaries from CAS (st_nlink == 1)
            self._clean_export._materialize_class_a(destination, self._target_lockfile)

            # Step 4: attach target LEC (st_nlink == 1)
            if self._target_lockfile.lec is not None:
                self._lec_store.attach_to_target(
                    self._target_lockfile.lec.key, destination
                )

            # Step 5: inject Class D LAST (eula.txt, user_jvm_args.txt, panel properties, secrets)
            dummy_req = CleanExportRequest(
                server_id="simple-staging",
                server_root=destination.parent,
                commit_sha="0" * 40,
                destination=destination,
                lockfile=self._target_lockfile,
                export_id=export_id,
                panel_properties=self._panel_properties,
                jvm_args=self._jvm_args,
                secrets=self._secrets,
            )
            self._clean_export._inject_class_d(destination, dummy_req)
            file_count, total_bytes = self._clean_export._measure_export(destination)
            fencing_verifier()
            self._clean_export._write_marker(
                destination, file_count, total_bytes, export_id
            )
        except BaseException:
            shutil.rmtree(destination, ignore_errors=True)
            raise


def _default_target_lec_key(
    target_mc: str,
    target_loader: LoaderRef,
    *,
    fabric_installer_version: str = "0.16.10",
) -> str | None:
    loader_id = (target_loader.id or "").strip().lower()
    loader_ver = (target_loader.version or "latest").strip() or "latest"
    mc_ver = (target_mc or "").strip()
    if not mc_ver or not loader_id:
        return None
    if loader_id == "fabric":
        return f"fabric/{mc_ver}/{loader_ver}/{fabric_installer_version}"
    if loader_id in ("purpur", "paper", "forge", "neoforge", "quilt"):
        return f"{loader_id}/{mc_ver}/{loader_ver}"
    return None


def _is_root_jar_path(relpath: str) -> bool:
    norm = relpath.replace("\\", "/").lstrip("./")
    return "/" not in norm and norm.lower().endswith(".jar")


def _build_rollback_diagnostic(upgrade: Any, res: LiveRefreshResult) -> tuple[str, str]:
    step_label = str(getattr(res.health, "failed_step", None) or "HEALTH_GATE_FAILED")
    raw_reason = str(getattr(res.health, "reason", None) or "Health gate failed")
    src_loader = getattr(upgrade, "source_loader_id", None)
    src_mc = getattr(upgrade, "source_mc", None)
    src_label = " ".join(str(p) for p in (src_loader, src_mc) if p).strip()
    suffix = (
        f" Automatically rolled back to {src_label}."
        if src_label
        else " Automatically rolled back."
    )
    diag = f"Health Gate ({step_label}) failed: {raw_reason}.{suffix}"
    return step_label[:64], diag[:512]


class ModpackUpgradeService:
    """Orchestrates P5.5 upgrade planning, branch testing, Simple/Advanced swaps, and pins."""

    def __init__(
        self,
        layout: HostStateLayout,
        session_factory: Callable[[], Any],
        *,
        upgrade_repo: SQLServerUpgradeRepository | None = None,
        cas: ArtifactCas | None = None,
        lockfile_service: LockfileService | None = None,
        modrinth_client: ModrinthProvider | None = None,
        lec_store: LecStore | None = None,
        lec_builder: LecBuilder | None = None,
        git_branch_service: GitBranchService | None = None,
        git_save_service: GitSaveCommitService | None = None,
        git_merge_service: GitMergeService | None = None,
        data_template_service: DataTemplateService | None = None,
        branch_runtime_service: BranchRuntimeService | None = None,
        clean_export_service: CleanExportService | None = None,
        download_to_cas: Callable[
            ..., Awaitable[VerifiedDownloadResult]
        ] = download_verified_to_cas,
    ) -> None:
        self._layout = layout
        self._session_factory = session_factory
        self._upgrade_repo = upgrade_repo or SQLServerUpgradeRepository(session_factory)
        self._cas = cas or ArtifactCas(layout.cas)
        self._lockfile_service = lockfile_service or LockfileService(layout)
        self._modrinth_client = modrinth_client or ModrinthProvider()
        self._lec_store = lec_store or LecStore(layout)
        self._lec_builder = lec_builder
        self._git_branch_service = git_branch_service or GitBranchService(layout)
        self._git_save_service = git_save_service or GitSaveCommitService(layout)
        self._git_merge_service = git_merge_service or GitMergeService(layout)
        self._data_template_service = data_template_service or DataTemplateService(
            layout, db_session=None
        )
        self._branch_runtime_service = branch_runtime_service
        self._clean_export_service = clean_export_service or CleanExportService(
            layout, branch_service=self._git_branch_service, cas=self._cas
        )
        self._download_to_cas = download_to_cas

    def _read_cas_bytes(self, digest: str) -> bytes:
        with self._cas.open_blob(digest) as fh:
            return fh.read()

    async def _require_upgrade(self, upgrade_id: str) -> Any:
        upgrade = await self._upgrade_repo.get(upgrade_id)
        if upgrade is None:
            raise NotFoundError(f"Server upgrade '{upgrade_id}' not found")
        return cast(Any, upgrade)

    def _pre_upgrade_lockfile_backup_path(self, server_id: str, upgrade_id: str) -> Path:
        return (
            self._layout.server_meta_dir(server_id)
            / f"onx-jars.pre-upgrade.{upgrade_id}.lock.json"
        )

    async def _resolve_server_mode(self, server_id: str, mode: str | None) -> str:
        if mode is not None:
            return mode.lower()
        async with self._session_factory() as session:
            row = await session.get(ServerModel, server_id)
            if row is not None and getattr(row, "mode", None):
                return str(row.mode).lower()
        return "simple"

    def _read_main_lockfile(
        self,
        server_id: str,
        server_root: str | Path | None,
    ) -> LockfileV21:
        if server_root is not None:
            branch = self._git_branch_service.get_branch(server_id, server_root, "main")
            if branch is not None and branch.worktree_path is not None:
                lock_path = branch.worktree_path / "onx-jars.lock.json"
                if lock_path.is_file() and not lock_path.is_symlink():
                    return parse_lockfile(lock_path.read_bytes())
            runner = self._git_branch_service.open_runner(
                server_id, validate_server_root(server_root)
            )
            res = runner.run("show", "main:onx-jars.lock.json", check=False)
            if res.returncode == 0 and res.stdout:
                return parse_lockfile(res.stdout.encode("utf-8"))
        host_lf = self._lockfile_service.read(server_id)
        if host_lf is not None:
            return host_lf
        raise NotFoundError(f"Lockfile not found on main for server '{server_id}'")

    async def plan_upgrade(
        self,
        server_id: str,
        *,
        target_mc: str,
        target_loader: LoaderRef,
        mode: str | None = None,
        server_root: str | Path | None = None,
        target_install_plan: InstallPlan | None = None,
        target_lec_key: str | None = None,
        excluded_paths: Iterable[str] = (),
        keep_paths: Iterable[str] = (),
        extra_allowed_hosts: Iterable[str] = (),
        version_types: Sequence[str] = ("release",),
        operation_id: str | None = None,
        ensure_baseline_fn: Callable[[str], Awaitable[Any]] | None = None,
        current_lockfile: LockfileV21 | None = None,
    ) -> tuple[ServerUpgradeModel, CompatibilityMatrix]:
        """Adopt baseline if Simple, build hash-only matrix, and persist ``ServerUpgradeModel``."""
        segment = validate_server_segment(server_id)
        list_fn = getattr(self._upgrade_repo, "list_for_server", None)
        if callable(list_fn):
            existing_rows = await list_fn(segment)
            pinned = next(
                (r for r in existing_rows if str(getattr(r, "status", "")) == "active_pinned"),
                None,
            )
            if pinned is not None:
                raise ConflictError(
                    "An active version change is waiting for confirmation. "
                    "Confirm or roll back the previous upgrade before planning a new one."
                )
        resolved_mode = await self._resolve_server_mode(segment, mode)

        if current_lockfile is None:
            if resolved_mode == "simple":
                if ensure_baseline_fn is not None:
                    await ensure_baseline_fn(segment)
                else:
                    await ensure_simple_baseline_lockfile(segment, reconcile_addons=True)
                current_lockfile = self._lockfile_service.read(segment)
                if current_lockfile is None:
                    raise NotFoundError(
                        f"Authoritative host lockfile missing for Simple server '{segment}'"
                    )
            else:
                current_lockfile = self._read_main_lockfile(segment, server_root)

        matrix = await build_compatibility_matrix(
            current_lockfile,
            target_mc=target_mc,
            target_loader=target_loader,
            modrinth_client=self._modrinth_client,
            cas=self._cas,
            target_install_plan=target_install_plan,
            excluded_paths=excluded_paths,
            keep_paths=keep_paths,
            extra_allowed_hosts=extra_allowed_hosts,
            version_types=version_types,
        )

        blockers = matrix.blockers
        if blockers:
            if all(
                b.status == MatrixStatus.BLOCKER_MANUAL_DOWNLOAD_REQUIRED
                for b in blockers
            ):
                status = "awaiting_manual_uploads"
            else:
                status = "blocked"
        else:
            status = "planned"

        plan_dict = (
            cast(dict[str, Any], target_install_plan.to_dict())
            if target_install_plan is not None
            else None
        )
        manual_blockers_list = (
            [cast(dict[str, Any], b.to_dict()) for b in target_install_plan.manual_blockers]
            if target_install_plan is not None
            else []
        )

        effective_lec_key = target_lec_key or _default_target_lec_key(
            target_mc, target_loader
        )

        row = await self._upgrade_repo.create(
            server_id=segment,
            mode=resolved_mode,
            status=status,
            source_mc=current_lockfile.mc,
            target_mc=target_mc,
            source_loader_id=current_lockfile.loader.id,
            source_loader_version=current_lockfile.loader.version,
            target_loader_id=target_loader.id,
            target_loader_version=target_loader.version,
            target_lec_key=effective_lec_key,
            operation_id=operation_id,
            plan_json=plan_dict,
            matrix_json=matrix.to_dict(),
            manual_blockers_json=manual_blockers_list,
        )
        return row, matrix

    async def resolve_manual_upload(
        self,
        upgrade_id: str,
        *,
        file_id: int | None = None,
        path: str | None = None,
        data: bytes,
        server_root: str | Path | None = None,
        excluded_paths: Iterable[str] | None = None,
        keep_paths: Iterable[str] | None = None,
        extra_allowed_hosts: Iterable[str] = (),
        current_lockfile: LockfileV21 | None = None,
    ) -> ServerUpgradeModel:
        """Verify an operator manual upload, re-evaluate matrix, and clear blockers."""
        upgrade = await self._require_upgrade(upgrade_id)
        if not upgrade.plan_json:
            raise ValidationError(
                "Upgrade has no install plan for manual upload", field="plan_json"
            )

        plan = _install_plan_from_dict(upgrade.plan_json)
        updated_plan, _verified = await resolve_manual_download_upload(
            plan,
            file_id=file_id,
            path=path,
            data=data,
            cas=self._cas,
            modrinth_client=self._modrinth_client,
        )

        if current_lockfile is None:
            if upgrade.mode == "simple":
                current_lockfile = self._lockfile_service.read(upgrade.server_id)
            else:
                current_lockfile = self._read_main_lockfile(upgrade.server_id, server_root)
        if current_lockfile is None:
            raise NotFoundError(
                f"Current lockfile missing for server '{upgrade.server_id}'"
            )

        effective_excluded = (
            tuple(excluded_paths)
            if excluded_paths is not None
            else tuple((upgrade.matrix_json or {}).get("excluded_paths") or ())
        )
        effective_kept = (
            tuple(keep_paths)
            if keep_paths is not None
            else tuple((upgrade.matrix_json or {}).get("kept_paths") or ())
        )
        matrix = await build_compatibility_matrix(
            current_lockfile,
            target_mc=upgrade.target_mc,
            target_loader=LoaderRef(
                id=upgrade.target_loader_id,
                version=upgrade.target_loader_version,
            ),
            modrinth_client=self._modrinth_client,
            cas=self._cas,
            target_install_plan=updated_plan,
            excluded_paths=effective_excluded,
            keep_paths=effective_kept,
            extra_allowed_hosts=extra_allowed_hosts,
        )

        blockers = matrix.blockers
        if blockers:
            if all(
                b.status == MatrixStatus.BLOCKER_MANUAL_DOWNLOAD_REQUIRED
                for b in blockers
            ):
                new_status = "awaiting_manual_uploads"
            else:
                new_status = "blocked"
        else:
            new_status = "planned"

        return await self._upgrade_repo.update_status(
            upgrade_id,
            new_status,
            plan_json=cast(dict[str, Any], updated_plan.to_dict()),
            matrix_json=matrix.to_dict(),
            manual_blockers_json=[
                cast(dict[str, Any], b.to_dict()) for b in updated_plan.manual_blockers
            ],
        )

    async def _ensure_cas_and_lec(
        self,
        matrix: CompatibilityMatrix,
        *,
        current_lockfile: LockfileV21,
        target_lec_key: str | None,
        extra_allowed_hosts: Iterable[str],
        plan: InstallPlan | None = None,
        target_mc: str | None = None,
        target_loader: LoaderRef | None = None,
        on_log: Callable[[str], Awaitable[None]] | None = None,
        on_progress: Callable[[float, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> list[LockfileFile]:
        current_by_path = {f.path: f for f in current_lockfile.files}
        plan_by_path = {f.path: f for f in plan.files} if plan is not None else {}
        target_files: list[LockfileFile] = []

        eff_mc = (target_mc or matrix.target_mc or "").strip()
        eff_loader = target_loader or matrix.target_loader
        loader_id = (eff_loader.id or "").strip().lower()
        core_label = (
            f"{loader_id.capitalize()} {eff_mc}".strip()
            if (loader_id or eff_mc)
            else "Server Core"
        )

        artifacts: list[dict[str, Any]] = []
        artifact_by_key: dict[str, dict[str, Any]] = {}

        def _register_artifact(
            key: str,
            name: str,
            kind: str,
            status: str = "pending",
            progress_pct: int = 0,
            bytes_total: int | None = None,
        ) -> dict[str, Any]:
            item: dict[str, Any] = {
                "name": name,
                "kind": kind,
                "status": status,
                "progress_pct": progress_pct,
            }
            if bytes_total is not None:
                item["bytes_total"] = int(bytes_total)
            artifacts.append(item)
            artifact_by_key[key] = item
            return item

        async def _emit_artifact_progress() -> None:
            if on_progress is None or not artifacts:
                return
            total_pct = sum(int(a.get("progress_pct", 0)) for a in artifacts)
            overall = max(0.0, min(1.0, total_pct / (len(artifacts) * 100.0)))
            with contextlib.suppress(Exception):
                await on_progress(overall, {"artifacts": [dict(a) for a in artifacts]})

        for entry in matrix.entries:
            if entry.excluded_by_operator or entry.status in (
                MatrixStatus.REMOVE,
                MatrixStatus.WARNING,
            ):
                continue
            norm_path = entry.path.replace("\\", "/").lstrip("./")
            if "/" not in norm_path and norm_path.lower().endswith(".jar"):
                continue
            leaf_name = Path(getattr(entry, "target_filename", None) or norm_path).name
            _register_artifact(
                f"addon:{entry.path}",
                leaf_name,
                "addon",
                status="pending",
                progress_pct=0,
                bytes_total=entry.target_size,
            )

        if target_lec_key:
            _register_artifact(
                "lec",
                f"Runtime Cache ({core_label})",
                "server_core",
                status="pending",
                progress_pct=0,
            )

        has_existing_root_jar = any(
            _is_root_jar_path(f.path) for f in current_lockfile.files
        )
        will_materialize_server_jar = bool(eff_mc) and (
            (
                loader_id in ("purpur", "paper")
                and (
                    self._lec_builder is not None
                    or self._download_to_cas is not download_verified_to_cas
                    or has_existing_root_jar
                )
            )
            or (
                loader_id in ("fabric", "vanilla")
                and self._download_to_cas is download_verified_to_cas
                and has_existing_root_jar
            )
        )
        if will_materialize_server_jar:
            _register_artifact(
                "server_core",
                core_label,
                "server_core",
                status="pending",
                progress_pct=0,
            )

        await _emit_artifact_progress()

        download_candidates = [
            e
            for e in matrix.entries
            if not e.excluded_by_operator
            and e.status not in (MatrixStatus.REMOVE, MatrixStatus.WARNING)
            and e.download_url
            and not (e.target_sha256 and self._cas.has(e.target_sha256))
        ]
        if on_log is not None and download_candidates:
            await on_log(
                f"Downloading {len(download_candidates)} target artifact(s)..."
            )

        for entry in matrix.entries:
            if entry.excluded_by_operator or entry.status == MatrixStatus.REMOVE:
                continue
            if entry.status == MatrixStatus.WARNING:
                continue
            norm_path = entry.path.replace("\\", "/").lstrip("./")
            if "/" not in norm_path and norm_path.lower().endswith(".jar"):
                # Root server core JARs (e.g. server.jar) are supplied by the
                # target loader / LEC build and must never be carried unchanged.
                continue

            cur_file = current_by_path.get(entry.path)
            plan_file = plan_by_path.get(entry.path)
            art_item = artifact_by_key.get(f"addon:{entry.path}")

            if (
                entry.status
                in (MatrixStatus.UNCHANGED, MatrixStatus.WARNING_UNRESOLVED_CARRIED)
                or getattr(entry, "kept_by_operator", False)
            ) and cur_file is not None:
                if not self._cas.has(cur_file.sha256):
                    raise ValidationError(
                        f"Current CAS blob missing for '{cur_file.path}'",
                        field="cas",
                    )
                if art_item is not None:
                    art_item["status"] = "cached"
                    art_item["progress_pct"] = 100
                    await _emit_artifact_progress()
                if on_log is not None:
                    await on_log(f"Cached: {Path(cur_file.path).name}")
                target_files.append(cur_file)
                continue

            if entry.download_url:
                if entry.target_sha256 and self._cas.has(entry.target_sha256):
                    blob = await asyncio.to_thread(self._read_cas_bytes, entry.target_sha256)
                    sha256 = entry.target_sha256
                    sha512 = entry.target_sha512 or hashlib.sha512(blob).hexdigest()
                    sha1 = entry.target_sha1 or hashlib.sha1(blob).hexdigest()
                    size = entry.target_size if entry.target_size is not None else len(blob)
                    if art_item is not None:
                        art_item["status"] = "cached"
                        art_item["progress_pct"] = 100
                        await _emit_artifact_progress()
                    if on_log is not None:
                        await on_log(f"Cached: {art_item['name'] if art_item else entry.path}")
                else:
                    if art_item is not None:
                        art_item["status"] = "downloading"
                        art_item["progress_pct"] = 0
                        await _emit_artifact_progress()
                    if on_log is not None:
                        dl_name = art_item["name"] if art_item else entry.path
                        await on_log(f"Downloading {dl_name}...")

                    async def _on_addon_bytes(
                        done: int,
                        total: int | None,
                        _item: dict[str, Any] | None = art_item,
                    ) -> None:
                        if _item is None:
                            return
                        _item["bytes_done"] = int(done)
                        if total and total > 0:
                            _item["bytes_total"] = int(total)
                            _item["progress_pct"] = min(99, max(1, int((done * 100) / total)))
                        await _emit_artifact_progress()

                    try:
                        verified = await self._download_to_cas(
                            entry.download_url,
                            self._cas,
                            expected_size=entry.target_size,
                            expected_sha512=entry.target_sha512,
                            expected_sha1=entry.target_sha1,
                            extra_allowed_hosts=extra_allowed_hosts,
                            on_progress=_on_addon_bytes,
                        )
                    except TypeError:
                        verified = await self._download_to_cas(
                            entry.download_url,
                            self._cas,
                            expected_size=entry.target_size,
                            expected_sha512=entry.target_sha512,
                            expected_sha1=entry.target_sha1,
                            extra_allowed_hosts=extra_allowed_hosts,
                        )
                    sha256 = verified.sha256
                    sha512 = verified.sha512
                    sha1 = verified.sha1
                    size = verified.size
                    if art_item is not None:
                        art_item["status"] = "ready"
                        art_item["progress_pct"] = 100
                        art_item["bytes_done"] = size
                        art_item["bytes_total"] = size
                        await _emit_artifact_progress()
            elif entry.target_sha256 and self._cas.has(entry.target_sha256):
                blob = await asyncio.to_thread(self._read_cas_bytes, entry.target_sha256)
                sha256 = entry.target_sha256
                sha512 = entry.target_sha512 or hashlib.sha512(blob).hexdigest()
                sha1 = entry.target_sha1 or hashlib.sha1(blob).hexdigest()
                size = entry.target_size if entry.target_size is not None else len(blob)
                if art_item is not None:
                    art_item["status"] = "cached"
                    art_item["progress_pct"] = 100
                    await _emit_artifact_progress()
            elif cur_file is not None and self._cas.has(cur_file.sha256):
                sha256 = cur_file.sha256
                sha512 = cur_file.sha512
                sha1 = cur_file.sha1
                size = cur_file.size
                if art_item is not None:
                    art_item["status"] = "cached"
                    art_item["progress_pct"] = 100
                    await _emit_artifact_progress()
            else:
                raise ValidationError(
                    f"Missing CAS artifact and download URL for '{entry.path}'",
                    field="cas",
                )

            origin_val = (
                plan_file.origin
                if plan_file is not None
                else Origin(entry.origin)
            )
            env_server = (
                EnvServer(plan_file.env_server)
                if plan_file is not None
                else (cur_file.env_server if cur_file is not None else EnvServer.REQUIRED)
            )
            optional = (
                plan_file.optional
                if plan_file is not None
                else (cur_file.optional if cur_file is not None else False)
            )
            materialized_path = entry.path
            target_filename = getattr(entry, "target_filename", None)
            if (
                target_filename
                and isinstance(target_filename, str)
                and entry.status == MatrixStatus.CARRIED
                and not getattr(entry, "kept_by_operator", False)
            ):
                safe_leaf = Path(target_filename.replace("\\", "/")).name
                if safe_leaf.lower().endswith(".jar") and "/" in norm_path:
                    parent_dir = norm_path.rsplit("/", 1)[0]
                    materialized_path = f"{parent_dir}/{safe_leaf}"
            target_files.append(
                LockfileFile(
                    path=materialized_path,
                    sha256=sha256,
                    size=size,
                    optional=optional,
                    env_server=env_server,
                    origin=origin_val,
                    sha512=sha512,
                    sha1=sha1,
                    project_id=entry.target_project_id or entry.source_project_id,
                    version_id=entry.target_version_id or entry.source_version_id,
                )
            )

        lec_item = artifact_by_key.get("lec")
        if target_lec_key and not self._lec_store.is_ready(target_lec_key):
            if self._lec_builder is not None:
                if lec_item is not None:
                    lec_item["status"] = "patching"
                    lec_item["progress_pct"] = 25
                    await _emit_artifact_progress()
                if on_log is not None:
                    await on_log(f"Patching runtime cache for {target_lec_key}...")
                try:
                    await self._lec_builder.ensure_lec(target_lec_key, on_log=on_log)
                except TypeError:
                    await self._lec_builder.ensure_lec(target_lec_key)
            if not self._lec_store.is_ready(target_lec_key):
                raise LecMissingError(lec_key=target_lec_key)
            if lec_item is not None:
                lec_item["status"] = "ready"
                lec_item["progress_pct"] = 100
                await _emit_artifact_progress()
        elif target_lec_key:
            if lec_item is not None:
                lec_item["status"] = "cached"
                lec_item["progress_pct"] = 100
                await _emit_artifact_progress()
            if on_log is not None:
                await on_log(f"Loader Environment Cache ready for {target_lec_key}.")

        has_root_server_jar = any(_is_root_jar_path(item.path) for item in target_files)
        should_materialize_server_jar = not has_root_server_jar and will_materialize_server_jar
        core_item = artifact_by_key.get("server_core")
        if should_materialize_server_jar:
            if core_item is not None:
                core_item["status"] = "downloading"
                core_item["progress_pct"] = 0
                await _emit_artifact_progress()
            if on_log is not None:
                await on_log(f"Downloading {core_label} server core JAR...")

            async def _on_core_bytes(done: int, total: int | None) -> None:
                if core_item is None:
                    return
                core_item["bytes_done"] = int(done)
                if total and total > 0:
                    core_item["bytes_total"] = int(total)
                    core_item["progress_pct"] = min(99, max(1, int((done * 100) / total)))
                await _emit_artifact_progress()

            server_jar_entry = await self._ensure_target_server_jar(
                target_mc=eff_mc,
                target_loader=eff_loader,
                extra_allowed_hosts=extra_allowed_hosts,
                on_progress=_on_core_bytes,
            )
            if server_jar_entry is not None:
                target_files.append(server_jar_entry)
                if core_item is not None:
                    core_item["status"] = "ready"
                    core_item["progress_pct"] = 100
                    core_item["bytes_done"] = server_jar_entry.size
                    core_item["bytes_total"] = server_jar_entry.size
                    await _emit_artifact_progress()
        elif core_item is not None:
            core_item["status"] = "cached"
            core_item["progress_pct"] = 100
            await _emit_artifact_progress()

        target_files.sort(key=lambda item: item.path)
        return target_files

    async def _ensure_target_server_jar(
        self,
        *,
        target_mc: str,
        target_loader: LoaderRef,
        extra_allowed_hosts: Iterable[str],
        on_progress: Callable[[int, int | None], Awaitable[None]] | None = None,
    ) -> LockfileFile | None:
        loader_id = (target_loader.id or "").strip().lower()
        loader_ver = (target_loader.version or "latest").strip() or "latest"
        expected_sha256: str | None = None
        expected_size: int | None = None

        if loader_id == "purpur":
            url = (
                f"https://api.purpurmc.org/v2/purpur/"
                f"{target_mc}/{loader_ver}/download"
            )
        elif loader_id == "paper":
            resolution = await resolve_paper_build(target_mc)
            url = resolution.download_url
            expected_sha256 = resolution.sha256
            expected_size = resolution.size
        elif loader_id == "fabric":
            from app.modules.server.application.services.jar_service import (
                _resolve_download_url_async,
            )

            if loader_ver == "latest":
                url = await _resolve_download_url_async("fabric", target_mc)
            else:
                installer_ver = "1.0.1"
                url = (
                    f"https://meta.fabricmc.net/v2/versions/loader/"
                    f"{target_mc}/{loader_ver}/{installer_ver}/server/jar"
                )
        elif loader_id == "vanilla":
            from app.modules.server.application.services.jar_service import (
                _resolve_download_url_async,
            )

            url = await _resolve_download_url_async("vanilla", target_mc)
        else:
            return None

        try:
            verified = await self._download_to_cas(
                url,
                self._cas,
                expected_sha256=expected_sha256,
                expected_size=expected_size,
                extra_allowed_hosts=extra_allowed_hosts,
                on_progress=on_progress,
            )
        except TypeError:
            verified = await self._download_to_cas(
                url,
                self._cas,
                expected_sha256=expected_sha256,
                expected_size=expected_size,
                extra_allowed_hosts=extra_allowed_hosts,
            )
        return LockfileFile(
            path="server.jar",
            sha256=verified.sha256,
            size=verified.size,
            optional=False,
            env_server=EnvServer.REQUIRED,
            origin=Origin.USER,
            sha512=verified.sha512,
            sha1=verified.sha1,
        )

    @staticmethod
    def _build_target_lockfile(
        upgrade: Any,
        *,
        current_lockfile: LockfileV21,
        target_files: list[LockfileFile],
        new_base_overrides: Mapping[str, str],
        plan: InstallPlan | None,
    ) -> LockfileV21:
        lec_ref = (
            LecRef(key=upgrade.target_lec_key)
            if upgrade.target_lec_key
            else current_lockfile.lec
        )
        modpack_ref = (
            ModpackRef(
                source=plan.source,
                project_id=plan.project_id,
                version_id=plan.version_id,
                version_label=plan.version_label,
                index_sha256=plan.index_sha256,
            )
            if plan is not None
            else current_lockfile.modpack
        )
        return LockfileV21(
            format=2,
            mc=upgrade.target_mc,
            loader=LoaderRef(
                id=upgrade.target_loader_id,
                version=upgrade.target_loader_version,
            ),
            base_overrides=dict(new_base_overrides),
            files=tuple(target_files),
            lec=lec_ref,
            modpack=modpack_ref,
        )

    async def prepare_advanced_upgrade_branch(
        self,
        upgrade_id: str,
        *,
        server_root: str | Path,
        target_overrides: Mapping[str, bytes] = {},
        resolved_conflicts: Mapping[str, bytes] = {},
        extra_allowed_hosts: Iterable[str] = (),
        target_slug: str | None = None,
        on_log: Callable[[str], Awaitable[None]] | None = None,
        on_progress: Callable[[float, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> ServerUpgradeModel:
        """Advanced Steps 1-4: gate blockers, materialize CAS/LEC, branch & 3-way merge."""
        upgrade = await self._require_upgrade(upgrade_id)
        if not upgrade.matrix_json:
            raise ValidationError("Upgrade has no compatibility matrix", field="matrix_json")

        matrix = CompatibilityMatrix.from_dict(upgrade.matrix_json)
        matrix.assert_no_blockers()

        plan = _install_plan_from_dict(upgrade.plan_json) if upgrade.plan_json else None
        current_lockfile = self._read_main_lockfile(upgrade.server_id, server_root)

        target_files = await self._ensure_cas_and_lec(
            matrix,
            current_lockfile=current_lockfile,
            target_lec_key=upgrade.target_lec_key,
            extra_allowed_hosts=extra_allowed_hosts,
            plan=plan,
            target_mc=str(upgrade.target_mc),
            target_loader=LoaderRef(
                id=str(upgrade.target_loader_id),
                version=str(upgrade.target_loader_version),
            ),
            on_log=on_log,
            on_progress=on_progress,
        )

        branch_name = upgrade.upgrade_branch
        if not branch_name or "/" in branch_name:
            slug = _sanitize_upgrade_slug(target_slug or upgrade.target_mc).lstrip("._-")
            if not slug:
                slug = "target"
            base_branch = f"upgrade-{slug}"[:63].rstrip("._-")
            branch_name = base_branch
            suffix_idx = 0
            while self._git_branch_service.get_branch(
                upgrade.server_id, server_root, branch_name
            ) is not None or await self._branch_row_exists(upgrade.server_id, branch_name):
                suffix_idx += 1
                short_tag = (
                    re.sub(r"[^a-zA-Z0-9]", "", upgrade.id)[:4]
                    if suffix_idx == 1
                    else str(suffix_idx)
                ) or str(suffix_idx)
                branch_name = f"{base_branch[: 62 - len(short_tag)].rstrip('._-')}-{short_tag}"

        existing_branch = self._git_branch_service.get_branch(
            upgrade.server_id, server_root, branch_name
        )
        if existing_branch is None:
            branch_info = self._git_branch_service.create_branch(
                upgrade.server_id,
                server_root,
                branch_name,
                start_point="main",
            )
        else:
            branch_info = existing_branch

        if branch_info.worktree_path is None:
            raise ConflictError(f"Branch '{branch_name}' has no active worktree")

        main_branch = self._git_branch_service.get_branch(
            upgrade.server_id, server_root, "main"
        )
        ours_source = (
            main_branch.worktree_path
            if main_branch is not None and main_branch.worktree_path is not None
            else branch_info.worktree_path
        )
        ours_files = _collect_class_b_from_dir(ours_source)

        merge_result = merge_upgrade_configs(
            cas=self._cas,
            current_lockfile=current_lockfile,
            ours_files=ours_files,
            theirs_overrides=target_overrides,
            resolved_conflicts=resolved_conflicts,
        )

        worktree = branch_info.worktree_path
        if any(_is_root_jar_path(item.path) for item in target_files):
            for root_entry in list(worktree.iterdir()):
                if (
                    root_entry.is_file()
                    and not root_entry.is_symlink()
                    and root_entry.name.lower().endswith(".jar")
                ):
                    root_entry.unlink()
        for relpath, content in sorted(merge_result.merged_files.items()):
            _write_safe_file(worktree, relpath, content)
        for relpath in merge_result.deleted_files:
            candidate = worktree / relpath
            if candidate.exists() and not candidate.is_symlink():
                candidate.unlink()

        target_lockfile = self._build_target_lockfile(
            upgrade,
            current_lockfile=current_lockfile,
            target_files=target_files,
            new_base_overrides=merge_result.new_base_overrides,
            plan=plan,
        )
        _write_safe_file(worktree, "onx-jars.lock.json", dump_lockfile(target_lockfile))

        if merge_result.status == "needs_resolution":
            return await self._upgrade_repo.update_status(
                upgrade_id,
                "needs_resolution",
                upgrade_branch=branch_name,
            )

        try:
            commit_res = self._git_save_service.save(
                upgrade.server_id,
                server_root,
                branch_name,
                f"Prepare upgrade to {upgrade.target_mc}",
            )
            head_commit_id: str | None = commit_res.commit_id
        except ConflictError as exc:
            if "no changes to commit" not in str(exc).lower():
                raise
            head_commit_id = branch_info.sha

        await self._upsert_server_branch_row(
            server_id=upgrade.server_id,
            branch_name=branch_name,
            head_commit_id=head_commit_id,
        )
        return await self._upgrade_repo.update_status(
            upgrade_id,
            "staging",
            upgrade_branch=branch_name,
            target_main_sha=head_commit_id,
            error_code=None,
            error_message=None,
        )

    async def _branch_row_exists(self, server_id: str, branch_name: str) -> bool:
        session_factory = getattr(self._upgrade_repo, "_session_factory", None)
        if session_factory is None:
            return False
        from sqlalchemy import select

        from app.modules.versioning.infrastructure.models import ServerBranchModel

        async with session_factory() as session:
            stmt = select(ServerBranchModel.id).where(
                ServerBranchModel.server_id == server_id,
                ServerBranchModel.name == branch_name,
            )
            return (await session.execute(stmt)).scalar_one_or_none() is not None

    async def _upsert_server_branch_row(
        self,
        *,
        server_id: str,
        branch_name: str,
        head_commit_id: str | None,
    ) -> None:
        upsert_hook = getattr(self._upgrade_repo, "upsert_branch_row", None)
        if callable(upsert_hook):
            await upsert_hook(server_id, branch_name, head_commit_id)
            return
        session_factory = getattr(self._upgrade_repo, "_session_factory", None)
        if session_factory is None:
            return
        from sqlalchemy import select

        from app.modules.versioning.infrastructure.models import ServerBranchModel

        async with session_factory() as session:
            stmt = select(ServerBranchModel).where(
                ServerBranchModel.server_id == server_id,
                ServerBranchModel.name == branch_name,
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing is None:
                session.add(
                    ServerBranchModel(
                        id=str(uuid.uuid4()),
                        server_id=server_id,
                        name=branch_name,
                        head_commit_id=head_commit_id,
                        status="created",
                        is_protected=False,
                        runtime_status="stopped",
                    )
                )
            else:
                if head_commit_id is not None:
                    existing.head_commit_id = head_commit_id
            await session.commit()

    async def start_advanced_upgrade_test(
        self,
        upgrade_id: str,
        *,
        server_root: str | Path,
        start_request_kwargs: Mapping[str, Any] = {},
    ) -> BranchStartResult:
        """Advanced Steps 5-6: clone disposable Class-E template and start branch test container."""
        upgrade = await self._require_upgrade(upgrade_id)
        if upgrade.status == "needs_resolution":
            raise MergeConflictError(
                "Cannot start upgrade test while config conflicts remain unresolved"
            )
        if not upgrade.upgrade_branch:
            raise ValidationError("Upgrade has no prepared branch", field="upgrade_branch")
        if self._branch_runtime_service is None:
            raise ValidationError(
                "BranchRuntimeService is required to start upgrade test",
                field="branch_runtime_service",
            )

        branch = self._git_branch_service.get_branch(
            upgrade.server_id, server_root, upgrade.upgrade_branch
        )
        if branch is None or branch.worktree_path is None:
            raise NotFoundError(f"Upgrade branch '{upgrade.upgrade_branch}' worktree not found")
        assert_tree_ready_for_upgrade_export(branch.worktree_path)

        template_id = f"upg-{upgrade.id[:8]}-{uuid.uuid4().hex[:6]}"
        async with self._session_factory() as session:
            await self._data_template_service.clone(
                upgrade.server_id,
                server_root,
                template_id,
                source_commit_sha=upgrade.target_main_sha or branch.sha,
                source_branch_name=upgrade.upgrade_branch,
                session=session,
            )
            await session.commit()

        req_kwargs: dict[str, Any] = {
            "server_id": upgrade.server_id,
            "server_root": server_root,
            "branch_name": upgrade.upgrade_branch,
            "server_type": upgrade.target_loader_id,
            "minecraft_version": upgrade.target_mc,
            "server_mode": "advanced",
            "commit_sha": upgrade.target_main_sha or branch.sha,
            "data_template_id": template_id,
            **dict(start_request_kwargs),
        }
        start_res = await self._branch_runtime_service.start_branch_runtime(
            BranchStartRequest(**req_kwargs)
        )
        await self._upgrade_repo.update_status(
            upgrade_id,
            "testing",
            data_template_id=template_id,
        )
        return start_res

    async def _discard_disposable_template(
        self,
        server_id: str,
        server_root: str | Path,
        upgrade: Any,
    ) -> None:
        if self._branch_runtime_service is not None and upgrade.upgrade_branch:
            with contextlib.suppress(NotFoundError, ConflictError):
                await self._branch_runtime_service.stop_branch_runtime(
                    server_id,
                    server_root,
                    upgrade.upgrade_branch,
                )

        if upgrade.data_template_id:
            template_dir = (
                self._layout.data_templates_dir(server_id) / upgrade.data_template_id
            )
            if template_dir.exists() and not template_dir.is_symlink():
                shutil.rmtree(template_dir, ignore_errors=True)
            async with self._session_factory() as session:
                await session.execute(
                    delete(ServerDataTemplateModel).where(
                        ServerDataTemplateModel.id == upgrade.data_template_id
                    )
                )
                await session.commit()
            await self._upgrade_repo.update_status(
                upgrade.id,
                upgrade.status,
                data_template_id=None,
            )

    async def _reclaim_orphaned_until_confirm_journals(
        self,
        server_id: str,
        *,
        refresh_service: LiveRefreshService,
    ) -> None:
        """Reclaim orphaned journals when no active_pinned upgrade owns them."""
        list_fn = getattr(self._upgrade_repo, "list_for_server", None)
        upgrade_rows = await list_fn(server_id) if callable(list_fn) else []
        pinned_rows = [
            r for r in upgrade_rows if str(getattr(r, "status", "")) == "active_pinned"
        ]
        pinned_journal_ids = {
            str(r.journal_id) for r in pinned_rows if getattr(r, "journal_id", None)
        }
        has_active_pinned = bool(pinned_rows)

        journal_repo = refresh_service._repository
        retained_list = [
            r
            for r in await journal_repo.list_retained_previous_trees()
            if r.server_id == server_id
        ]
        active_journal = None
        get_active_fn = getattr(journal_repo, "get_active_for_server", None)
        if callable(get_active_fn):
            active_journal = await get_active_fn(server_id)

        candidates_by_id: dict[str, Any] = {r.journal_id: r for r in retained_list}
        if active_journal is not None and active_journal.journal_id not in candidates_by_id:
            candidates_by_id[active_journal.journal_id] = active_journal

        for record in candidates_by_id.values():
            phase_str = str(getattr(record, "phase", "") or "").upper()
            # Never destroy a ROLLBACK_REQUIRED journal or an active in-flight upgrade!
            if phase_str == "ROLLBACK_REQUIRED":
                continue
            if not getattr(record, "terminal", True) and phase_str not in (
                "READY",
                "CONFIRMED",
                "FAILED_CLEAN",
                "ROLLED_BACK",
            ):
                continue
            if has_active_pinned and (
                not pinned_journal_ids or record.journal_id in pinned_journal_ids
            ):
                # A real active_pinned upgrade still awaits confirmation/rollback.
                continue

            paths_to_check: list[str] = []
            primary = record.staging_path if record.used_exchange else record.previous_path
            if primary:
                paths_to_check.append(primary)
            if record.previous_path and record.previous_path not in paths_to_check:
                paths_to_check.append(record.previous_path)

            for raw_candidate in paths_to_check:
                try:
                    path = refresh_service._orchestrator._path_guard.validate_swap_path(
                        record.server_id,
                        raw_candidate,
                        field="previous_path",
                        live_root=getattr(record, "live_path", None),
                    )
                except ValidationError:
                    continue
                if os.path.lexists(path):
                    if path.is_symlink() or not path.is_dir():
                        raise ValidationError(
                            "Retained previous tree is not a plain directory",
                            field="previous_path",
                            details={"path": str(path)[:256]},
                        )
                    await asyncio.to_thread(shutil.rmtree, path)

            if getattr(record, "previous_tree_retained", False):
                with contextlib.suppress(Exception):
                    await journal_repo.mark_previous_tree_cleaned(record.journal_id)

            if not getattr(record, "terminal", True):
                with contextlib.suppress(Exception):
                    await journal_repo.transition(
                        record.journal_id,
                        fencing_token=record.fencing_token,
                        phase="FAILED_CLEAN",
                        error=getattr(record, "error", None)
                        or "Auto-reclaimed orphaned journal before upgrade",
                    )

            class_c_id = getattr(record, "class_c_snapshot_id", None)
            if class_c_id and hasattr(refresh_service, "_class_c"):
                unpin_fn = getattr(refresh_service._class_c, "unpin_snapshot", None)
                if callable(unpin_fn):
                    with contextlib.suppress(Exception):
                        await asyncio.to_thread(unpin_fn, server_id, class_c_id)

    async def apply_advanced_upgrade_to_live(
        self,
        upgrade_id: str,
        *,
        server_root: str | Path,
        refresh_service: LiveRefreshService,
        health_gate: UpgradeHealthGateEvaluator | None = None,
        deployed_lockfile: LockfileV21 | None = None,
        target_lockfile: LockfileV21 | None = None,
        on_stage: Callable[[str], Awaitable[None]] | None = None,
        on_log: Callable[[str], Awaitable[None]] | None = None,
        export_bytes: int = 1,
        backup_bytes: int = 0,
        class_c_snapshot_bytes: int = 0,
    ) -> LiveRefreshResult:
        """Advanced Steps 8-11: discard test template, quiesce+backup BEFORE merge, gate."""
        upgrade = await self._require_upgrade(upgrade_id)
        if upgrade.status == "needs_resolution":
            raise MergeConflictError(
                "Cannot apply upgrade to live while config conflicts remain unresolved"
            )
        if not upgrade.upgrade_branch:
            raise ValidationError("Upgrade has no prepared branch", field="upgrade_branch")

        branch = self._git_branch_service.get_branch(
            upgrade.server_id, server_root, upgrade.upgrade_branch
        )
        if branch is None or branch.worktree_path is None:
            raise NotFoundError(f"Upgrade branch '{upgrade.upgrade_branch}' worktree not found")
        assert_tree_ready_for_upgrade_export(branch.worktree_path)

        await self._discard_disposable_template(upgrade.server_id, server_root, upgrade)

        main_branch = self._git_branch_service.get_branch(
            upgrade.server_id, server_root, "main"
        )
        if main_branch is None or not main_branch.sha:
            raise NotFoundError(f"Branch 'main' not found for server '{upgrade.server_id}'")
        previous_main_sha = main_branch.sha

        if deployed_lockfile is None:
            deployed_lockfile = self._read_main_lockfile(upgrade.server_id, server_root)
        if target_lockfile is None:
            wt_lock_path = branch.worktree_path / "onx-jars.lock.json"
            if wt_lock_path.is_file() and not wt_lock_path.is_symlink():
                target_lockfile = parse_lockfile(wt_lock_path.read_bytes())

        live_dir = Path(os.path.abspath(str(server_root)))
        staging_dir = live_dir.with_name(f"{live_dir.name}.staging")

        def _merge_upgrade_into_main(_journal: RefreshJournalRecord) -> str:
            merge_res = self._git_merge_service.merge(
                upgrade.server_id,
                server_root,
                "main",
                [previous_main_sha, upgrade.upgrade_branch],
                f"Apply upgrade {upgrade.id} ({upgrade.target_mc})",
            )
            return merge_res.commit_id

        req = LiveRefreshRequest(
            server_id=upgrade.server_id,
            live_dir=live_dir,
            staging_dir=staging_dir,
            export_bytes=export_bytes,
            backup_bytes=backup_bytes,
            class_c_snapshot_bytes=class_c_snapshot_bytes,
            retention_policy=RETENTION_UNTIL_CONFIRM,
            previous_main_sha=previous_main_sha,
            target_main_sha="",
            deployed_lockfile=deployed_lockfile,
            target_lockfile=target_lockfile,
            force_full_upgrade_path=True,
        )
        await self._reclaim_orphaned_until_confirm_journals(
            upgrade.server_id, refresh_service=refresh_service
        )
        if on_log is not None:
            await on_log("Creating pre-upgrade backup & merging upgrade branch into main...")
        res = await refresh_service.refresh(
            req,
            pre_stage_hook=lambda journal: asyncio.to_thread(_merge_upgrade_into_main, journal),
            health_gate=health_gate,
            on_stage=on_stage,
        )

        if res.rolled_back:
            error_code, diag = _build_rollback_diagnostic(upgrade, res)
            await self._upgrade_repo.update_status(
                upgrade_id,
                "rolled_back",
                journal_id=res.journal.journal_id,
                previous_main_sha=previous_main_sha,
                target_main_sha=res.journal.target_main_sha,
                pre_upgrade_backup_id=res.pre_upgrade_backup_id,
                class_c_snapshot_id=res.class_c_snapshot_id,
                pinned_until_confirm=True,
                health_gate_passed=False,
                rolled_back_at=_utcnow(),
                error_code=error_code,
                error_message=diag,
            )
        else:
            await self._upgrade_repo.update_status(
                upgrade_id,
                "active_pinned",
                journal_id=res.journal.journal_id,
                previous_main_sha=previous_main_sha,
                target_main_sha=res.journal.target_main_sha,
                pre_upgrade_backup_id=res.pre_upgrade_backup_id,
                class_c_snapshot_id=res.class_c_snapshot_id,
                pinned_until_confirm=True,
                health_gate_passed=True,
            )
        return res

    async def execute_simple_upgrade(
        self,
        upgrade_id: str,
        *,
        server_root: str | Path,
        refresh_service: LiveRefreshService,
        health_gate: UpgradeHealthGateEvaluator | None = None,
        target_overrides: Mapping[str, bytes] = {},
        resolved_conflicts: Mapping[str, bytes] = {},
        extra_allowed_hosts: Iterable[str] = (),
        panel_properties: Mapping[str, str] = {},
        jvm_args: str = "",
        secrets: Mapping[str, str] = {},
        ensure_baseline_fn: Callable[[str], Awaitable[Any]] | None = None,
        on_stage: Callable[[str], Awaitable[None]] | None = None,
        on_log: Callable[[str], Awaitable[None]] | None = None,
        on_progress: Callable[[float, dict[str, Any]], Awaitable[None]] | None = None,
        export_bytes: int = 1,
        backup_bytes: int = 0,
        class_c_snapshot_bytes: int = 0,
    ) -> LiveRefreshResult:
        """Simple Mode 5-step crash-safe staging swap with authoritative host lockfile."""
        upgrade = await self._require_upgrade(upgrade_id)
        if not upgrade.matrix_json:
            raise ValidationError("Upgrade has no compatibility matrix", field="matrix_json")

        matrix = CompatibilityMatrix.from_dict(upgrade.matrix_json)
        matrix.assert_no_blockers()

        if on_log is not None:
            await on_log("Verifying baseline lockfile...")
        adopter = ensure_baseline_fn or ensure_simple_baseline_lockfile
        await adopter(upgrade.server_id)
        previous_lockfile = await asyncio.to_thread(
            self._lockfile_service.read, upgrade.server_id
        )
        if previous_lockfile is None:
            raise NotFoundError(
                f"Authoritative host lockfile missing for Simple server '{upgrade.server_id}'"
            )

        if not panel_properties:
            from app.modules.versioning.infrastructure.runtime_adapters import (
                _read_panel_properties,
            )

            panel_properties = _read_panel_properties(Path(server_root))

        plan = _install_plan_from_dict(upgrade.plan_json) if upgrade.plan_json else None
        target_files = await self._ensure_cas_and_lec(
            matrix,
            current_lockfile=previous_lockfile,
            target_lec_key=upgrade.target_lec_key,
            extra_allowed_hosts=extra_allowed_hosts,
            plan=plan,
            target_mc=str(upgrade.target_mc),
            target_loader=LoaderRef(
                id=str(upgrade.target_loader_id),
                version=str(upgrade.target_loader_version),
            ),
            on_log=on_log,
            on_progress=on_progress,
        )

        if on_log is not None:
            await on_log("Merging server configurations & saving pre-upgrade lockfile...")
        live_dir = Path(os.path.abspath(str(server_root)))
        ours_files = await asyncio.to_thread(_collect_class_b_from_dir, live_dir)
        merge_result = await asyncio.to_thread(
            merge_upgrade_configs,
            cas=self._cas,
            current_lockfile=previous_lockfile,
            ours_files=ours_files,
            theirs_overrides=target_overrides,
            resolved_conflicts=resolved_conflicts,
        )
        if merge_result.status == "needs_resolution":
            await self._upgrade_repo.update_status(upgrade_id, "needs_resolution")
            raise MergeConflictError(
                conflicts=[c.to_dict() for c in merge_result.conflicts],
                warnings=list(merge_result.warnings),
            )

        target_lockfile = self._build_target_lockfile(
            upgrade,
            current_lockfile=previous_lockfile,
            target_files=target_files,
            new_base_overrides=merge_result.new_base_overrides,
            plan=plan,
        )
        backup_lock_path = self._pre_upgrade_lockfile_backup_path(
            upgrade.server_id, upgrade.id
        )
        backup_lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        await asyncio.to_thread(
            atomic_write_private,
            backup_lock_path,
            dump_lockfile(previous_lockfile),
            mode=0o600,
            fsync_parent=True,
        )

        exporter = SimpleStagingExporter(
            self._layout,
            target_lockfile=target_lockfile,
            merged_class_b=merge_result.merged_files,
            deleted_class_b=merge_result.deleted_files,
            cas=self._cas,
            lec_store=self._lec_store,
            panel_properties=panel_properties,
            jvm_args=jvm_args,
            secrets=secrets,
        )
        staging_dir = live_dir.with_name(f"{live_dir.name}.staging")
        req = LiveRefreshRequest(
            server_id=upgrade.server_id,
            live_dir=live_dir,
            staging_dir=staging_dir,
            export_bytes=export_bytes,
            backup_bytes=backup_bytes,
            class_c_snapshot_bytes=class_c_snapshot_bytes,
            retention_policy=RETENTION_UNTIL_CONFIRM,
            deployed_lockfile=previous_lockfile,
            target_lockfile=target_lockfile,
            force_full_upgrade_path=True,
        )

        try:
            await self._reclaim_orphaned_until_confirm_journals(
                upgrade.server_id, refresh_service=refresh_service
            )
            if on_log is not None:
                await on_log("Creating pre-upgrade backup & Class-C snapshot...")
            res = await refresh_service.refresh(
                req,
                health_gate=health_gate,
                stage_export=exporter,
                on_stage=on_stage,
            )
        except BaseException:
            await asyncio.to_thread(
                self._lockfile_service.write, upgrade.server_id, previous_lockfile
            )
            raise

        if res.rolled_back:
            await asyncio.to_thread(
                self._lockfile_service.write, upgrade.server_id, previous_lockfile
            )
            error_code, diag = _build_rollback_diagnostic(upgrade, res)
            await self._upgrade_repo.update_status(
                upgrade_id,
                "rolled_back",
                journal_id=res.journal.journal_id,
                pre_upgrade_backup_id=res.pre_upgrade_backup_id,
                class_c_snapshot_id=res.class_c_snapshot_id,
                pinned_until_confirm=True,
                health_gate_passed=False,
                rolled_back_at=_utcnow(),
                error_code=error_code,
                error_message=diag,
            )
        else:
            await asyncio.to_thread(
                self._lockfile_service.write, upgrade.server_id, target_lockfile
            )
            await self._upgrade_repo.update_status(
                upgrade_id,
                "active_pinned",
                journal_id=res.journal.journal_id,
                pre_upgrade_backup_id=res.pre_upgrade_backup_id,
                class_c_snapshot_id=res.class_c_snapshot_id,
                pinned_until_confirm=True,
                health_gate_passed=True,
            )
        return res

    async def confirm_upgrade_and_unpin(
        self,
        upgrade_id: str,
        *,
        refresh_service: LiveRefreshService,
    ) -> ServerUpgradeModel:
        """Confirm upgrade, unpinning backup + Class-C snapshot and deleting previous tree."""
        upgrade = await self._require_upgrade(upgrade_id)
        if not upgrade.journal_id:
            raise ValidationError("Upgrade has no refresh journal id", field="journal_id")

        await refresh_service.confirm_upgrade_unpin(
            upgrade.server_id, upgrade.journal_id
        )
        backup_lock_path = self._pre_upgrade_lockfile_backup_path(
            upgrade.server_id, upgrade.id
        )
        if backup_lock_path.exists() and not backup_lock_path.is_symlink():
            with contextlib.suppress(OSError):
                backup_lock_path.unlink()

        return await self._upgrade_repo.update_status(
            upgrade_id,
            "confirmed",
            pinned_until_confirm=False,
            confirmed_at=_utcnow(),
        )

    async def emergency_rollback_upgrade(
        self,
        upgrade_id: str,
        *,
        refresh_service: LiveRefreshService,
        reason: str = "operator emergency rollback",
    ) -> RollbackResult | None:
        """Roll back the full atomic triad, or discard a pre-apply non-terminal upgrade plan."""
        upgrade = await self._require_upgrade(upgrade_id)
        if not upgrade.journal_id:
            if upgrade.status not in ("active_pinned", "confirmed", "rolled_back"):
                await self._upgrade_repo.update_status(
                    upgrade_id,
                    "rolled_back",
                    pinned_until_confirm=False,
                    rolled_back_at=_utcnow(),
                    error_code=None,
                    error_message=reason[:512],
                )
                return None
            raise ValidationError("Upgrade has no refresh journal id", field="journal_id")

        res = await refresh_service.rollback(
            upgrade.server_id,
            upgrade.journal_id,
            reason=reason,
        )
        if upgrade.mode == "simple":
            backup_lock_path = self._pre_upgrade_lockfile_backup_path(
                upgrade.server_id, upgrade.id
            )
            if backup_lock_path.is_file() and not backup_lock_path.is_symlink():
                previous_lockfile = parse_lockfile(backup_lock_path.read_bytes())
                self._lockfile_service.write(upgrade.server_id, previous_lockfile)

        await self._upgrade_repo.update_status(
            upgrade_id,
            "rolled_back",
            rolled_back_at=_utcnow(),
            error_message=reason[:512],
        )
        return res


__all__ = [
    "ModpackUpgradeService",
    "SQLServerUpgradeRepository",
    "SimpleStagingExporter",
]
