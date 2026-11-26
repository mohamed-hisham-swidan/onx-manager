"""Hash-only compatibility matrix and transitive dependency BFS (P5.5).

Implements ``build_compatibility_matrix`` strictly via Modrinth hash-only batch
endpoints (``/v2/version_files``, ``/v2/version_files/update``, ``/v2/versions``,
``/v2/projects``). Never calls ``ModrinthProvider.search()`` or guesses by slug
or filename.
"""

from __future__ import annotations

import enum
import hashlib
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, cast

from app.core.allowlist import validate_canonical_relpath
from app.core.exceptions import UntrustedDownloadHostError, UpgradeBlockerError
from app.modules.plugin.application.services.version_selector import (
    _game_version_matches,
    compatible_loaders_for_server,
    loader_tier_index,
    loader_tiers_for_server,
    version_type_rank,
)
from app.modules.plugin.infrastructure.providers.base import (
    PluginFile,
    PluginVersionInfo,
    PluginVersionsPage,
)
from app.modules.plugin.infrastructure.providers.modrinth import (
    ModrinthDependency,
    ModrinthProjectMeta,
    ModrinthProvider,
    ModrinthVersionRecord,
)
from app.modules.versioning.domain.lockfile import LoaderRef, LockfileFile, LockfileV21, Origin
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.download_allowlist import validate_download_url
from app.modules.versioning.infrastructure.modpack_parser import (
    InstallPlan,
    InstallPlanFile,
    InstallPlanOverride,
    ManualDownloadBlocker,
)

MAX_BFS_DEPTH = 8
MAX_BFS_PROJECTS = 500
MODRINTH_BATCH_CHUNK_SIZE = 200

_PLUGIN_LOADERS = frozenset(
    {
        "paper",
        "purpur",
        "spigot",
        "bukkit",
        "folia",
        "velocity",
        "bungeecord",
        "waterfall",
        "minestom",
    }
)


class MatrixStatus(enum.StrEnum):
    """Normative compatibility matrix entry statuses."""

    WARNING_UNRESOLVED_CARRIED = "warning: unresolved_carried"
    BLOCKER_NO_TARGET_BUILD = "blocker: no_target_build"
    BLOCKER_MISSING_DEPENDENCY = "blocker: missing_dependency"
    BLOCKER_MISSING_TRANSITIVE_DEPENDENCY = "blocker: missing_transitive_dependency"
    BLOCKER_INCOMPATIBLE = "blocker: incompatible"
    BLOCKER_UNTRUSTED_HOST = "blocker: untrusted_host"
    BLOCKER_MANUAL_DOWNLOAD_REQUIRED = "blocker: manual_download_required"
    WARNING = "warning"
    ADD = "add"
    REMOVE = "remove"
    CARRIED = "carried"
    UNCHANGED = "unchanged"


BLOCKER_STATUSES: frozenset[MatrixStatus] = frozenset(
    {
        MatrixStatus.BLOCKER_NO_TARGET_BUILD,
        MatrixStatus.BLOCKER_MISSING_DEPENDENCY,
        MatrixStatus.BLOCKER_MISSING_TRANSITIVE_DEPENDENCY,
        MatrixStatus.BLOCKER_INCOMPATIBLE,
        MatrixStatus.BLOCKER_UNTRUSTED_HOST,
        MatrixStatus.BLOCKER_MANUAL_DOWNLOAD_REQUIRED,
    }
)


def _derive_action_label(
    status: MatrixStatus,
    *,
    excluded_by_operator: bool,
    kept_by_operator: bool,
) -> str:
    if excluded_by_operator or status == MatrixStatus.REMOVE:
        return "excluded"
    if kept_by_operator:
        return "kept_current"
    if status in (MatrixStatus.ADD, MatrixStatus.CARRIED):
        return "will_upgrade"
    if status == MatrixStatus.UNCHANGED:
        return "compatible"
    if status == MatrixStatus.WARNING_UNRESOLVED_CARRIED:
        return "unresolved_carried"
    if status == MatrixStatus.BLOCKER_MANUAL_DOWNLOAD_REQUIRED:
        return "manual_upload"
    if status in BLOCKER_STATUSES:
        return "blocker"
    return "warning"


@dataclass(frozen=True)
class MatrixEntry:
    """Single file or dependency row in a compatibility matrix."""

    path: str
    status: MatrixStatus
    origin: str
    source_sha256: str | None = None
    source_sha512: str | None = None
    source_project_id: str | None = None
    source_version_id: str | None = None
    target_sha256: str | None = None
    target_sha512: str | None = None
    target_sha1: str | None = None
    target_size: int | None = None
    target_project_id: str | None = None
    target_version_id: str | None = None
    target_version_number: str | None = None
    target_filename: str | None = None
    download_url: str | None = None
    required_by: tuple[str, ...] = ()
    detail: str = ""
    manual_blocker: ManualDownloadBlocker | None = None
    excluded_by_operator: bool = False
    kept_by_operator: bool = False
    action_label: str = ""

    def __post_init__(self) -> None:
        if not self.action_label:
            object.__setattr__(
                self,
                "action_label",
                _derive_action_label(
                    self.status,
                    excluded_by_operator=self.excluded_by_operator,
                    kept_by_operator=self.kept_by_operator,
                ),
            )

    @property
    def is_blocker(self) -> bool:
        return (
            (self.status in BLOCKER_STATUSES)
            and not self.excluded_by_operator
            and not self.kept_by_operator
            and not (self.manual_blocker is not None and self.manual_blocker.resolved)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "status": str(self.status),
            "origin": self.origin,
            "source_sha256": self.source_sha256,
            "source_sha512": self.source_sha512,
            "source_project_id": self.source_project_id,
            "source_version_id": self.source_version_id,
            "target_sha256": self.target_sha256,
            "target_sha512": self.target_sha512,
            "target_sha1": self.target_sha1,
            "target_size": self.target_size,
            "target_project_id": self.target_project_id,
            "target_version_id": self.target_version_id,
            "target_version_number": self.target_version_number,
            "target_filename": self.target_filename,
            "download_url": self.download_url,
            "required_by": list(self.required_by),
            "detail": self.detail,
            "manual_blocker": (
                self.manual_blocker.to_dict() if self.manual_blocker is not None else None
            ),
            "excluded_by_operator": self.excluded_by_operator,
            "kept_by_operator": self.kept_by_operator,
            "action_label": self.action_label,
            "is_blocker": self.is_blocker,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MatrixEntry:
        raw_blocker = data.get("manual_blocker")
        manual_blocker = None
        if isinstance(raw_blocker, Mapping):
            manual_blocker = ManualDownloadBlocker(
                path=str(raw_blocker.get("path") or ""),
                filename=str(raw_blocker.get("filename") or ""),
                project_id=raw_blocker.get("project_id"),
                file_id=raw_blocker.get("file_id"),
                webpage_url=str(raw_blocker.get("webpage_url") or ""),
                expected_size=raw_blocker.get("expected_size"),
                expected_sha1=raw_blocker.get("expected_sha1"),
                expected_sha512=raw_blocker.get("expected_sha512"),
                required=bool(raw_blocker.get("required", True)),
                reason=str(raw_blocker.get("reason") or "download_url_null"),
                blocker_type=str(raw_blocker.get("blocker_type") or "manual_download_required"),
                resolved=bool(raw_blocker.get("resolved", False)),
                resolved_sha256=raw_blocker.get("resolved_sha256"),
            )
        return cls(
            path=str(data["path"]),
            status=MatrixStatus(str(data["status"])),
            origin=str(data["origin"]),
            source_sha256=data.get("source_sha256"),
            source_sha512=data.get("source_sha512"),
            source_project_id=data.get("source_project_id"),
            source_version_id=data.get("source_version_id"),
            target_sha256=data.get("target_sha256"),
            target_sha512=data.get("target_sha512"),
            target_sha1=data.get("target_sha1"),
            target_size=data.get("target_size"),
            target_project_id=data.get("target_project_id"),
            target_version_id=data.get("target_version_id"),
            target_version_number=data.get("target_version_number"),
            target_filename=data.get("target_filename"),
            download_url=data.get("download_url"),
            required_by=tuple(data.get("required_by") or ()),
            detail=str(data.get("detail") or ""),
            manual_blocker=manual_blocker,
            excluded_by_operator=bool(data.get("excluded_by_operator", False)),
            kept_by_operator=bool(data.get("kept_by_operator", False)),
            action_label=str(data.get("action_label") or ""),
        )


@dataclass(frozen=True)
class CompatibilityMatrix:
    """Deterministic compatibility matrix produced before an upgrade."""

    source_mc: str
    target_mc: str
    source_loader: LoaderRef
    target_loader: LoaderRef
    entries: tuple[MatrixEntry, ...]
    bfs_depth_reached: int = 0
    bfs_projects_resolved: int = 0
    excluded_paths: tuple[str, ...] = ()
    kept_paths: tuple[str, ...] = ()

    @property
    def blockers(self) -> tuple[MatrixEntry, ...]:
        return tuple(entry for entry in self.entries if entry.is_blocker)

    @property
    def warnings(self) -> tuple[MatrixEntry, ...]:
        return tuple(
            entry
            for entry in self.entries
            if entry.status in (MatrixStatus.WARNING, MatrixStatus.WARNING_UNRESOLVED_CARRIED)
            and not entry.excluded_by_operator
        )

    @property
    def has_blockers(self) -> bool:
        return bool(self.blockers)

    def assert_no_blockers(self) -> None:
        if self.has_blockers:
            raise UpgradeBlockerError(
                blockers=[blocker.to_dict() for blocker in self.blockers]
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_mc": self.source_mc,
            "target_mc": self.target_mc,
            "source_loader": {
                "id": self.source_loader.id,
                "version": self.source_loader.version,
            },
            "target_loader": {
                "id": self.target_loader.id,
                "version": self.target_loader.version,
            },
            "entries": [entry.to_dict() for entry in self.entries],
            "bfs_depth_reached": self.bfs_depth_reached,
            "bfs_projects_resolved": self.bfs_projects_resolved,
            "excluded_paths": list(self.excluded_paths),
            "kept_paths": list(self.kept_paths),
            "has_blockers": self.has_blockers,
            "blockers_count": len(self.blockers),
            "warnings_count": len(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CompatibilityMatrix:
        src_loader = data["source_loader"]
        tgt_loader = data["target_loader"]
        return cls(
            source_mc=str(data["source_mc"]),
            target_mc=str(data["target_mc"]),
            source_loader=LoaderRef(
                id=str(src_loader["id"]),
                version=str(src_loader["version"]),
            ),
            target_loader=LoaderRef(
                id=str(tgt_loader["id"]),
                version=str(tgt_loader["version"]),
            ),
            entries=tuple(MatrixEntry.from_dict(item) for item in data.get("entries") or ()),
            bfs_depth_reached=int(data.get("bfs_depth_reached", 0)),
            bfs_projects_resolved=int(data.get("bfs_projects_resolved", 0)),
            excluded_paths=tuple(data.get("excluded_paths") or ()),
            kept_paths=tuple(data.get("kept_paths") or ()),
        )


def _compute_entry_sha512(entry: LockfileFile, cas: ArtifactCas | None) -> str | None:
    if entry.sha512 is not None:
        return entry.sha512
    if cas is not None and cas.has(entry.sha256):
        with cas.open_blob(entry.sha256) as fh:
            return hashlib.sha512(fh.read()).hexdigest()
    return None


def _select_primary_file(record: ModrinthVersionRecord) -> PluginFile | None:
    if not record.files:
        return None
    return next((f for f in record.files if f.primary), record.files[0])


def _validate_url_status(
    url: str | None,
    *,
    extra_allowed_hosts: Iterable[str],
) -> tuple[bool, str]:
    if not url:
        return False, "Missing download URL"
    try:
        validate_download_url(url, extra_allowed_hosts=extra_allowed_hosts)
    except UntrustedDownloadHostError as exc:
        return False, str(exc)
    return True, ""


def _dependency_relpath(loader_id: str, filename: str) -> str:
    clean = filename.lstrip("/").replace("\\", "/")
    folder = "plugins" if loader_id.lower() in _PLUGIN_LOADERS else "mods"
    if clean.startswith(("mods/", "plugins/")):
        return validate_canonical_relpath(clean)
    return validate_canonical_relpath(f"{folder}/{clean}")


def _loaders_compatible_for_target(
    target_loader_id: str,
    candidate_loaders: Iterable[str],
) -> bool:
    allowed = set(compatible_loaders_for_server(target_loader_id))
    return any(str(loader).strip().lower() in allowed for loader in candidate_loaders)


def _mc_version_compatible(target_mc: str, candidate_versions: Iterable[str]) -> bool:
    return any(_game_version_matches(target_mc, str(gv)) for gv in candidate_versions)


def _matches_target_env(
    record: ModrinthVersionRecord,
    *,
    target_mc: str,
    target_loader_id: str,
    version_types: Sequence[str],
    projects_cache: Mapping[str, ModrinthProjectMeta],
) -> bool:
    if not _mc_version_compatible(target_mc, record.game_versions):
        return False
    if not _loaders_compatible_for_target(target_loader_id, record.loaders):
        return False
    if version_types and record.version_type and record.version_type not in version_types:
        return False
    if record.environment == "client_only":
        return False
    if record.environment not in ("server_only", "client_and_server") and record.project_id:
        project = projects_cache.get(record.project_id)
        if project is not None and project.server_side == "unsupported":
            return False
    return True


def _coerce_version_record(
    item: ModrinthVersionRecord | PluginVersionInfo,
) -> ModrinthVersionRecord:
    if isinstance(item, ModrinthVersionRecord):
        return item
    req_pids = getattr(item, "required_dependencies", None)
    effective_required = (
        list(req_pids)
        if isinstance(req_pids, (list, tuple))
        else []
    )
    deps = tuple(
        ModrinthDependency(
            version_id=None,
            project_id=pid,
            file_name=None,
            dependency_type="required",
        )
        for pid in effective_required
        if pid
    )
    return ModrinthVersionRecord(
        version_id=item.version_id,
        project_id=item.project_id,
        name=item.name,
        version_number=item.version_number,
        version_type=getattr(item, "version_type", "release") or "release",
        game_versions=tuple(item.game_versions),
        loaders=tuple(item.loaders),
        environment=None,
        files=tuple(item.files),
        dependencies=deps,
        date_published=item.date_published,
    )


async def _ensure_projects_cached(
    modrinth_client: ModrinthProvider,
    project_ids: Iterable[str],
    cache: dict[str, ModrinthProjectMeta],
) -> None:
    missing = [pid for pid in dict.fromkeys(project_ids) if pid and pid not in cache]
    if not missing:
        return
    fetched = await modrinth_client.get_projects_by_ids(missing)
    cache.update(fetched)


async def _ensure_versions_cached(
    modrinth_client: ModrinthProvider,
    version_ids: Iterable[str],
    cache: dict[str, ModrinthVersionRecord],
) -> None:
    missing = [vid for vid in dict.fromkeys(version_ids) if vid and vid not in cache]
    if not missing:
        return
    fetched = await modrinth_client.get_versions_by_ids(missing)
    cache.update(fetched)


async def _resolve_dependency_version(
    dep: ModrinthDependency,
    *,
    target_mc: str,
    target_loader_id: str,
    version_types: Sequence[str],
    modrinth_client: ModrinthProvider,
    versions_cache: dict[str, ModrinthVersionRecord],
    projects_cache: dict[str, ModrinthProjectMeta],
    project_versions_cache: dict[str, list[ModrinthVersionRecord]],
) -> ModrinthVersionRecord | None:
    if dep.version_id:
        await _ensure_versions_cached(modrinth_client, [dep.version_id], versions_cache)
        ver = versions_cache.get(dep.version_id)
        if ver is None:
            return None
        if ver.environment not in ("server_only", "client_and_server") and ver.project_id:
            await _ensure_projects_cached(modrinth_client, [ver.project_id], projects_cache)
        if not _matches_target_env(
            ver,
            target_mc=target_mc,
            target_loader_id=target_loader_id,
            version_types=version_types,
            projects_cache=projects_cache,
        ):
            return None
        return ver

    if not dep.project_id:
        return None

    await _ensure_projects_cached(modrinth_client, [dep.project_id], projects_cache)
    project_meta = projects_cache.get(dep.project_id)
    if project_meta is not None and project_meta.server_side == "unsupported":
        return None

    if dep.project_id not in project_versions_cache:
        page = await modrinth_client.get_project_versions(dep.project_id)
        raw_items = (
            page.items
            if isinstance(page, PluginVersionsPage)
            else list(cast(Iterable[Any], page))
        )
        matching_ids: list[str] = []
        direct_records: list[ModrinthVersionRecord] = []
        for item in raw_items:
            game_versions = getattr(item, "game_versions", ())
            loaders = getattr(item, "loaders", ())
            if not _mc_version_compatible(target_mc, game_versions):
                continue
            if not _loaders_compatible_for_target(target_loader_id, loaders):
                continue
            if isinstance(item, ModrinthVersionRecord):
                direct_records.append(item)
            elif getattr(item, "version_id", None):
                matching_ids.append(str(item.version_id))

        if matching_ids:
            await _ensure_versions_cached(modrinth_client, matching_ids, versions_cache)
            resolved_records = [
                versions_cache[vid] for vid in matching_ids if vid in versions_cache
            ]
            if not resolved_records:
                resolved_records = [
                    _coerce_version_record(item)
                    for item in raw_items
                    if getattr(item, "version_id", None) in set(matching_ids)
                ]
            direct_records.extend(resolved_records)

        direct_records.sort(key=lambda r: r.date_published or "", reverse=True)
        direct_records.sort(
            key=lambda r: (
                loader_tier_index(target_loader_id, r.loaders),
                -version_type_rank(r.version_type),
            )
        )
        project_versions_cache[dep.project_id] = direct_records

    for candidate in project_versions_cache[dep.project_id]:
        if (
            candidate.environment not in ("server_only", "client_and_server")
            and candidate.project_id
        ):
            await _ensure_projects_cached(
                modrinth_client, [candidate.project_id], projects_cache
            )
        if _matches_target_env(
            candidate,
            target_mc=target_mc,
            target_loader_id=target_loader_id,
            version_types=version_types,
            projects_cache=projects_cache,
        ):
            return candidate
    return None


async def _resolve_project_fallback_version(
    *,
    project_id: str,
    modrinth_client: ModrinthProvider,
    target_mc: str,
    target_loader_id: str,
    version_types: Sequence[str],
    projects_cache: dict[str, ModrinthProjectMeta],
    fallback_versions_cache: dict[str, list[ModrinthVersionRecord]],
) -> ModrinthVersionRecord | None:
    """Fall back to project versions filtered by parent-loader chain and game version."""
    if project_id not in fallback_versions_cache:
        page = await modrinth_client.get_project_versions(project_id)
        raw_items = (
            page.items
            if isinstance(page, PluginVersionsPage)
            else list(cast(Iterable[Any], page))
        )
        fallback_versions_cache[project_id] = [
            _coerce_version_record(item) for item in raw_items
        ]

    loader_chain = compatible_loaders_for_server(target_loader_id)
    loader_rank = {ldr: idx for idx, ldr in enumerate(loader_chain)}
    candidates: list[ModrinthVersionRecord] = []
    for rec in fallback_versions_cache[project_id]:
        if (
            rec.environment not in ("server_only", "client_and_server")
            and rec.project_id
        ):
            await _ensure_projects_cached(modrinth_client, [rec.project_id], projects_cache)
        if not _matches_target_env(
            rec,
            target_mc=target_mc,
            target_loader_id=target_loader_id,
            version_types=version_types,
            projects_cache=projects_cache,
        ):
            continue
        if _select_primary_file(rec) is None:
            continue
        candidates.append(rec)

    if not candidates:
        return None

    def _rank(rec: ModrinthVersionRecord) -> tuple[int, int, int]:
        exact_mc = 0 if target_mc in rec.game_versions else 1
        best_tier = loader_tier_index(target_loader_id, rec.loaders)
        vt_score = -version_type_rank(rec.version_type)
        return (exact_mc, best_tier, vt_score)

    # Prefer exact MC match -> native loader tier -> release > beta > alpha -> newest date_published.
    candidates.sort(key=lambda r: r.date_published or "", reverse=True)
    candidates.sort(key=_rank)
    return candidates[0]


async def build_compatibility_matrix(
    current_lockfile: LockfileV21,
    *,
    target_mc: str,
    target_loader: LoaderRef,
    modrinth_client: ModrinthProvider,
    cas: ArtifactCas | None = None,
    target_install_plan: InstallPlan | None = None,
    excluded_paths: Iterable[str] = (),
    keep_paths: Iterable[str] = (),
    extra_allowed_hosts: Iterable[str] = (),
    version_types: Sequence[str] = ("release",),
    auto_include_dependencies: bool = True,
) -> CompatibilityMatrix:
    """Build the deterministic compatibility matrix using hash-only Modrinth lookups."""
    normalized_excluded: list[str] = []
    for raw_path in excluded_paths:
        normalized_excluded.append(validate_canonical_relpath(raw_path))
    excluded_set = frozenset(normalized_excluded)
    normalized_kept: list[str] = []
    for raw_path in keep_paths:
        normalized_kept.append(validate_canonical_relpath(raw_path))
    kept_set = frozenset(normalized_kept) - excluded_set
    extra_hosts = tuple(extra_allowed_hosts)

    entries_by_path: dict[str, MatrixEntry] = {}
    warning_entries: list[MatrixEntry] = []
    excluded_project_ids: set[str] = set()
    installed_project_ids: set[str] = set()
    active_root_records: list[tuple[str, ModrinthVersionRecord]] = []

    current_by_path: dict[str, LockfileFile] = {f.path: f for f in current_lockfile.files}
    for entry in current_lockfile.files:
        if entry.path in excluded_set:
            if entry.project_id:
                excluded_project_ids.add(entry.project_id)
            entries_by_path[entry.path] = MatrixEntry(
                path=entry.path,
                status=MatrixStatus.REMOVE,
                origin=entry.origin.value,
                source_sha256=entry.sha256,
                source_sha512=_compute_entry_sha512(entry, cas),
                source_project_id=entry.project_id,
                source_version_id=entry.version_id,
                detail="Excluded by operator",
                excluded_by_operator=True,
            )

    # ------------------------------------------------------------------
    # Pack A -> B Short-Circuit (ND-6)
    # ------------------------------------------------------------------
    if target_install_plan is not None:
        current_pack_files = {
            f.path: f
            for f in current_lockfile.files
            if f.origin != Origin.USER and f.path not in excluded_set
        }
        target_plan_files: dict[str, InstallPlanFile] = {
            f.path: f for f in target_install_plan.files
        }
        target_class_a_overrides: dict[str, InstallPlanOverride] = {
            ov.path: ov
            for ov in target_install_plan.overrides
            if ov.classification in ("A-JAR", "A-CAS") and ov.path not in target_plan_files
        }
        unresolved_blockers: dict[str, ManualDownloadBlocker] = {
            b.path: b for b in target_install_plan.manual_blockers if not b.resolved
        }

        for path, blocker in sorted(unresolved_blockers.items()):
            if path in excluded_set:
                entries_by_path[path] = MatrixEntry(
                    path=path,
                    status=MatrixStatus.REMOVE,
                    origin=Origin.CURSEFORGE.value,
                    manual_blocker=blocker,
                    detail="Excluded by operator",
                    excluded_by_operator=True,
                )
                continue
            cur = current_pack_files.get(path)
            entries_by_path[path] = MatrixEntry(
                path=path,
                status=MatrixStatus.BLOCKER_MANUAL_DOWNLOAD_REQUIRED,
                origin=Origin.CURSEFORGE.value,
                source_sha256=cur.sha256 if cur else None,
                source_sha512=_compute_entry_sha512(cur, cas) if cur else None,
                source_project_id=cur.project_id if cur else None,
                source_version_id=cur.version_id if cur else None,
                target_sha512=blocker.expected_sha512,
                target_sha1=blocker.expected_sha1,
                target_size=blocker.expected_size,
                detail=f"Manual download required ({blocker.reason})",
                manual_blocker=blocker,
            )

        all_pack_paths = sorted(
            set(current_pack_files) | set(target_plan_files) | set(target_class_a_overrides)
        )
        for path in all_pack_paths:
            if path in unresolved_blockers:
                continue
            if path in excluded_set:
                if path not in entries_by_path:
                    entries_by_path[path] = MatrixEntry(
                        path=path,
                        status=MatrixStatus.REMOVE,
                        origin=Origin.OVERRIDE.value,
                        detail="Excluded by operator",
                        excluded_by_operator=True,
                    )
                continue

            cur = current_pack_files.get(path)
            plan_file = target_plan_files.get(path)
            override = target_class_a_overrides.get(path)

            if plan_file is not None:
                if plan_file.project_id:
                    installed_project_ids.add(plan_file.project_id)
                download_url = plan_file.downloads[0] if plan_file.downloads else None
                same_hash = False
                if cur is not None:
                    cur_sha512 = _compute_entry_sha512(cur, cas)
                    if (
                        (cur_sha512 and plan_file.sha512 and cur_sha512 == plan_file.sha512)
                        or (cur.sha256 and plan_file.sha256 and cur.sha256 == plan_file.sha256)
                        or (cur.sha1 and plan_file.sha1 and cur.sha1 == plan_file.sha1)
                    ):
                        same_hash = True

                if same_hash and cur is not None:
                    if cur.project_id:
                        installed_project_ids.add(cur.project_id)
                    entries_by_path[path] = MatrixEntry(
                        path=path,
                        status=MatrixStatus.UNCHANGED,
                        origin=plan_file.origin.value,
                        source_sha256=cur.sha256,
                        source_sha512=_compute_entry_sha512(cur, cas),
                        source_project_id=cur.project_id,
                        source_version_id=cur.version_id,
                        target_sha256=plan_file.sha256 or cur.sha256,
                        target_sha512=plan_file.sha512,
                        target_sha1=plan_file.sha1,
                        target_size=plan_file.size,
                        target_project_id=plan_file.project_id,
                        target_version_id=plan_file.version_id,
                        download_url=download_url,
                    )
                    continue

                if download_url is not None:
                    ok, err = _validate_url_status(download_url, extra_allowed_hosts=extra_hosts)
                    if not ok:
                        entries_by_path[path] = MatrixEntry(
                            path=path,
                            status=MatrixStatus.BLOCKER_UNTRUSTED_HOST,
                            origin=plan_file.origin.value,
                            source_sha256=cur.sha256 if cur else None,
                            source_sha512=_compute_entry_sha512(cur, cas) if cur else None,
                            source_project_id=cur.project_id if cur else None,
                            source_version_id=cur.version_id if cur else None,
                            target_sha256=plan_file.sha256,
                            target_sha512=plan_file.sha512,
                            target_sha1=plan_file.sha1,
                            target_size=plan_file.size,
                            target_project_id=plan_file.project_id,
                            target_version_id=plan_file.version_id,
                            download_url=download_url,
                            detail=err,
                        )
                        continue
                elif plan_file.sha256 is None or (
                    cas is not None and not cas.has(plan_file.sha256)
                ):
                    entries_by_path[path] = MatrixEntry(
                        path=path,
                        status=MatrixStatus.BLOCKER_UNTRUSTED_HOST,
                        origin=plan_file.origin.value,
                        source_sha256=cur.sha256 if cur else None,
                        target_project_id=plan_file.project_id,
                        target_version_id=plan_file.version_id,
                        detail="Missing download URL for target pack file",
                    )
                    continue

                entries_by_path[path] = MatrixEntry(
                    path=path,
                    status=MatrixStatus.ADD,
                    origin=plan_file.origin.value,
                    source_sha256=cur.sha256 if cur else None,
                    source_sha512=_compute_entry_sha512(cur, cas) if cur else None,
                    source_project_id=cur.project_id if cur else None,
                    source_version_id=cur.version_id if cur else None,
                    target_sha256=plan_file.sha256,
                    target_sha512=plan_file.sha512,
                    target_sha1=plan_file.sha1,
                    target_size=plan_file.size,
                    target_project_id=plan_file.project_id,
                    target_version_id=plan_file.version_id,
                    download_url=download_url,
                )
                continue

            if override is not None:
                same_hash = cur is not None and (
                    cur.sha256 == override.sha256
                    or _compute_entry_sha512(cur, cas) == override.sha512
                )
                entries_by_path[path] = MatrixEntry(
                    path=path,
                    status=MatrixStatus.UNCHANGED if same_hash else MatrixStatus.ADD,
                    origin=Origin.OVERRIDE.value,
                    source_sha256=cur.sha256 if cur else None,
                    source_sha512=_compute_entry_sha512(cur, cas) if cur else None,
                    target_sha256=override.sha256,
                    target_sha512=override.sha512,
                    target_sha1=override.sha1,
                    target_size=override.size,
                )
                continue

            if cur is not None:
                entries_by_path[path] = MatrixEntry(
                    path=path,
                    status=MatrixStatus.REMOVE,
                    origin=cur.origin.value,
                    source_sha256=cur.sha256,
                    source_sha512=_compute_entry_sha512(cur, cas),
                    source_project_id=cur.project_id,
                    source_version_id=cur.version_id,
                    detail="Removed in target modpack",
                )

    # ------------------------------------------------------------------
    # Hash-Only Modrinth Pipeline (all non-papermc or loose user jars)
    # ------------------------------------------------------------------
    def _is_root_server_jar(relpath: str) -> bool:
        norm = relpath.replace("\\", "/").lstrip("./")
        return "/" not in norm and norm.lower().endswith(".jar")

    candidates: list[LockfileFile] = []
    for entry in current_lockfile.files:
        if entry.path in excluded_set:
            continue
        if _is_root_server_jar(entry.path):
            # Root server core JARs (e.g. server.jar, purpur-*.jar) are replaced
            # by the target loader / LEC build and are never Modrinth addons.
            continue
        if target_install_plan is not None:
            if entry.origin == Origin.USER:
                candidates.append(entry)
        else:
            if entry.origin == Origin.PAPERMC:
                entries_by_path[entry.path] = MatrixEntry(
                    path=entry.path,
                    status=MatrixStatus.UNCHANGED,
                    origin=entry.origin.value,
                    source_sha256=entry.sha256,
                    source_sha512=_compute_entry_sha512(entry, cas),
                    target_sha256=entry.sha256,
                    target_sha512=entry.sha512,
                    target_sha1=entry.sha1,
                    target_size=entry.size,
                    detail="Loader jar handled via LEC",
                )
                continue
            candidates.append(entry)

    sha512_by_path: dict[str, str] = {}
    unique_hashes: list[str] = []
    seen_hashes: set[str] = set()
    for entry in candidates:
        digest512 = _compute_entry_sha512(entry, cas)
        if digest512 is not None:
            sha512_by_path[entry.path] = digest512
            if digest512 not in seen_hashes:
                seen_hashes.add(digest512)
                unique_hashes.append(digest512)

    found_by_hash: dict[str, ModrinthVersionRecord] = {}
    updates_by_hash: dict[str, ModrinthVersionRecord] = {}
    if unique_hashes:
        found_by_hash = await modrinth_client.lookup_version_files_by_hashes(
            unique_hashes, algorithm="sha512"
        )
        tiers = loader_tiers_for_server(target_loader.id) or (
            compatible_loaders_for_server(target_loader.id),
        )
        remaining_hashes = list(unique_hashes)
        allowed_vtypes = {str(vt).strip().lower() for vt in version_types if str(vt).strip()}
        for tier_loaders in tiers:
            if not remaining_hashes or not tier_loaders:
                break
            tier_updates = await modrinth_client.lookup_version_updates_by_hashes(
                remaining_hashes,
                loaders=list(tier_loaders),
                game_versions=[target_mc],
                algorithm="sha512",
                version_types=version_types,
            )
            matched_in_tier: set[str] = set()
            for digest, rec in tier_updates.items():
                if (
                    allowed_vtypes
                    and rec.version_type
                    and rec.version_type.strip().lower() not in allowed_vtypes
                ):
                    continue
                updates_by_hash[digest] = rec
                matched_in_tier.add(digest)
            remaining_hashes = [h for h in remaining_hashes if h not in matched_in_tier]

    projects_cache: dict[str, ModrinthProjectMeta] = {}
    versions_cache: dict[str, ModrinthVersionRecord] = {}
    project_versions_cache: dict[str, list[ModrinthVersionRecord]] = {}
    fallback_versions_cache: dict[str, list[ModrinthVersionRecord]] = {}

    # Pre-check project.server_side when update version.environment is unspecified
    ambiguous_update_pids = [
        rec.project_id
        for rec in updates_by_hash.values()
        if rec.environment not in ("client_only", "server_only", "client_and_server")
        and rec.project_id
    ]
    if ambiguous_update_pids:
        await _ensure_projects_cached(modrinth_client, ambiguous_update_pids, projects_cache)

    for entry in candidates:
        src_sha512 = sha512_by_path.get(entry.path)
        identified = found_by_hash.get(src_sha512) if src_sha512 else None
        target_rec = updates_by_hash.get(src_sha512) if src_sha512 else None

        src_project_id = entry.project_id or (identified.project_id if identified else None)
        src_version_id = entry.version_id or (identified.version_id if identified else None)

        if entry.path in kept_set:
            if src_project_id:
                installed_project_ids.add(src_project_id)
            entries_by_path[entry.path] = MatrixEntry(
                path=entry.path,
                status=MatrixStatus.CARRIED,
                origin=Origin.MODRINTH.value if identified is not None else entry.origin.value,
                source_sha256=entry.sha256,
                source_sha512=src_sha512,
                source_project_id=src_project_id,
                source_version_id=src_version_id,
                target_sha256=entry.sha256,
                target_sha512=src_sha512,
                target_sha1=entry.sha1,
                target_size=entry.size,
                target_project_id=src_project_id,
                target_version_id=src_version_id,
                detail="Kept current JAR on target version by operator choice",
                kept_by_operator=True,
                action_label="kept_current",
            )
            continue

        # Filter client-only targets strictly from Version.environment (OD-v8.4-10)
        if target_rec is not None and target_rec.environment == "client_only":
            target_rec = None
        elif (
            target_rec is not None
            and target_rec.environment not in ("server_only", "client_and_server")
            and target_rec.project_id
        ):
            proj = projects_cache.get(target_rec.project_id)
            if proj is not None and proj.server_side == "unsupported":
                target_rec = None

        if identified is None and entry.origin != Origin.MODRINTH:
            # Paper/SpigotMC/Hangar/user/curseforge-unclassified/override not on Modrinth
            if src_project_id:
                installed_project_ids.add(src_project_id)
            entries_by_path[entry.path] = MatrixEntry(
                path=entry.path,
                status=MatrixStatus.WARNING_UNRESOLVED_CARRIED,
                origin=entry.origin.value,
                source_sha256=entry.sha256,
                source_sha512=src_sha512,
                source_project_id=src_project_id,
                source_version_id=src_version_id,
                target_sha256=entry.sha256,
                target_sha512=src_sha512,
                target_sha1=entry.sha1,
                target_size=entry.size,
                detail="Not found on Modrinth via hash lookup; carried unchanged",
            )
            continue

        if (
            target_rec is None
            and src_project_id
            and (identified is not None or entry.origin == Origin.MODRINTH)
        ):
            target_rec = await _resolve_project_fallback_version(
                project_id=src_project_id,
                modrinth_client=modrinth_client,
                target_mc=target_mc,
                target_loader_id=target_loader.id,
                version_types=version_types,
                projects_cache=projects_cache,
                fallback_versions_cache=fallback_versions_cache,
            )

        if target_rec is None:
            entries_by_path[entry.path] = MatrixEntry(
                path=entry.path,
                status=MatrixStatus.BLOCKER_NO_TARGET_BUILD,
                origin=entry.origin.value,
                source_sha256=entry.sha256,
                source_sha512=src_sha512,
                source_project_id=src_project_id,
                source_version_id=src_version_id,
                detail=(
                    f"No compatible {target_loader.id} build for Minecraft {target_mc}"
                ),
            )
            continue

        primary_file = _select_primary_file(target_rec)
        if primary_file is None:
            entries_by_path[entry.path] = MatrixEntry(
                path=entry.path,
                status=MatrixStatus.BLOCKER_NO_TARGET_BUILD,
                origin=entry.origin.value,
                source_sha256=entry.sha256,
                source_sha512=src_sha512,
                source_project_id=src_project_id,
                source_version_id=src_version_id,
                target_project_id=target_rec.project_id,
                target_version_id=target_rec.version_id,
                detail="Target Modrinth version has no downloadable files",
            )
            continue

        url_ok, url_err = _validate_url_status(
            primary_file.url, extra_allowed_hosts=extra_hosts
        )
        if not url_ok:
            entries_by_path[entry.path] = MatrixEntry(
                path=entry.path,
                status=MatrixStatus.BLOCKER_UNTRUSTED_HOST,
                origin=entry.origin.value,
                source_sha256=entry.sha256,
                source_sha512=src_sha512,
                source_project_id=src_project_id,
                source_version_id=src_version_id,
                target_sha512=primary_file.sha512 or None,
                target_sha1=primary_file.sha1 or None,
                target_size=primary_file.size_bytes,
                target_project_id=target_rec.project_id,
                target_version_id=target_rec.version_id,
                target_version_number=target_rec.version_number,
                download_url=primary_file.url,
                detail=url_err,
            )
            continue

        if target_rec.project_id:
            installed_project_ids.add(target_rec.project_id)
        if src_project_id:
            installed_project_ids.add(src_project_id)

        unchanged = bool(src_sha512 and primary_file.sha512 and primary_file.sha512 == src_sha512)
        entries_by_path[entry.path] = MatrixEntry(
            path=entry.path,
            status=MatrixStatus.UNCHANGED if unchanged else MatrixStatus.CARRIED,
            origin=Origin.MODRINTH.value if identified is not None else entry.origin.value,
            source_sha256=entry.sha256,
            source_sha512=src_sha512,
            source_project_id=src_project_id,
            source_version_id=src_version_id,
            target_sha256=entry.sha256 if unchanged else None,
            target_sha512=primary_file.sha512 or None,
            target_sha1=primary_file.sha1 or None,
            target_size=primary_file.size_bytes,
            target_project_id=target_rec.project_id,
            target_version_id=target_rec.version_id,
            target_version_number=target_rec.version_number,
            target_filename=None if unchanged else (primary_file.filename or None),
            download_url=primary_file.url,
        )
        active_root_records.append((entry.path, target_rec))

    # ------------------------------------------------------------------
    # Transitive Required Dependency BFS (depth <= 8, <= 500 projects)
    # ------------------------------------------------------------------
    bfs_queue: deque[tuple[str, ModrinthDependency, int]] = deque()
    emitted_optional: set[tuple[str, str]] = set()
    added_dep_paths_by_project: dict[str, str] = {}

    for root_path, root_rec in active_root_records:
        for dep in root_rec.dependencies:
            if dep.dependency_type == "incompatible":
                if dep.project_id and dep.project_id in installed_project_ids:
                    cur_entry = entries_by_path[root_path]
                    entries_by_path[root_path] = replace(
                        cur_entry,
                        status=MatrixStatus.BLOCKER_INCOMPATIBLE,
                        detail=f"Incompatible with installed project {dep.project_id}",
                    )
            elif dep.dependency_type == "optional":
                if dep.project_id and dep.project_id not in installed_project_ids:
                    opt_key = (root_path, dep.project_id)
                    if opt_key not in emitted_optional:
                        emitted_optional.add(opt_key)
                        warning_entries.append(
                            MatrixEntry(
                                path=f"{root_path}#optional:{dep.project_id}",
                                status=MatrixStatus.WARNING,
                                origin=Origin.MODRINTH.value,
                                target_project_id=dep.project_id,
                                required_by=(root_path,),
                                detail=f"Optional dependency {dep.project_id} is not installed",
                            )
                        )
            elif dep.dependency_type == "required":
                bfs_queue.append((root_path, dep, 1))

    bfs_depth_reached = 0
    bfs_projects_resolved = 0
    seen_dep_edges: set[tuple[str, str | None, str | None]] = set()

    while bfs_queue:
        root_path, dep, depth = bfs_queue.popleft()
        root_entry = entries_by_path.get(root_path)
        if root_entry is not None and root_entry.is_blocker:
            continue

        if dep.project_id and dep.project_id in installed_project_ids:
            existing_dep_path = added_dep_paths_by_project.get(dep.project_id)
            if existing_dep_path and existing_dep_path in entries_by_path:
                existing_entry = entries_by_path[existing_dep_path]
                if root_path not in existing_entry.required_by:
                    entries_by_path[existing_dep_path] = replace(
                        existing_entry,
                        required_by=(*existing_entry.required_by, root_path),
                    )
            continue

        if depth == 1 and (
            not auto_include_dependencies
            or (dep.project_id is not None and dep.project_id in excluded_project_ids)
        ):
            if root_entry is not None:
                entries_by_path[root_path] = replace(
                    root_entry,
                    status=MatrixStatus.BLOCKER_MISSING_DEPENDENCY,
                    detail=(
                        "Missing required dependency "
                        f"{dep.project_id or dep.version_id or 'unknown'}"
                    ),
                )
            continue

        if depth > MAX_BFS_DEPTH:
            if root_entry is not None:
                entries_by_path[root_path] = replace(
                    root_entry,
                    status=MatrixStatus.BLOCKER_MISSING_TRANSITIVE_DEPENDENCY,
                    detail=f"Transitive dependency depth exceeded MAX_BFS_DEPTH={MAX_BFS_DEPTH}",
                )
            continue

        if bfs_projects_resolved >= MAX_BFS_PROJECTS:
            if root_entry is not None:
                entries_by_path[root_path] = replace(
                    root_entry,
                    status=MatrixStatus.BLOCKER_MISSING_TRANSITIVE_DEPENDENCY,
                    detail=(
                        "Transitive dependency resolution exceeded "
                        f"MAX_BFS_PROJECTS={MAX_BFS_PROJECTS}"
                    ),
                )
            continue

        edge_key = (root_path, dep.project_id, dep.version_id)
        if edge_key in seen_dep_edges:
            continue
        seen_dep_edges.add(edge_key)

        bfs_depth_reached = max(bfs_depth_reached, depth)

        resolved_ver = await _resolve_dependency_version(
            dep,
            target_mc=target_mc,
            target_loader_id=target_loader.id,
            version_types=version_types,
            modrinth_client=modrinth_client,
            versions_cache=versions_cache,
            projects_cache=projects_cache,
            project_versions_cache=project_versions_cache,
        )
        if resolved_ver is None:
            if root_entry is not None:
                entries_by_path[root_path] = replace(
                    root_entry,
                    status=MatrixStatus.BLOCKER_MISSING_TRANSITIVE_DEPENDENCY,
                    detail=(
                        f"No compatible build for required dependency "
                        f"{dep.project_id or dep.version_id or 'unknown'} "
                        f"at depth {depth}"
                    ),
                )
            continue

        primary_file = _select_primary_file(resolved_ver)
        if primary_file is None:
            if root_entry is not None:
                entries_by_path[root_path] = replace(
                    root_entry,
                    status=MatrixStatus.BLOCKER_MISSING_TRANSITIVE_DEPENDENCY,
                    detail=(
                        f"Dependency {resolved_ver.project_id} version "
                        f"{resolved_ver.version_id} has no downloadable files"
                    ),
                )
            continue

        url_ok, url_err = _validate_url_status(
            primary_file.url, extra_allowed_hosts=extra_hosts
        )
        if not url_ok:
            if root_entry is not None:
                entries_by_path[root_path] = replace(
                    root_entry,
                    status=MatrixStatus.BLOCKER_UNTRUSTED_HOST,
                    detail=url_err,
                )
            continue

        dep_relpath = _dependency_relpath(target_loader.id, primary_file.filename)
        if dep_relpath in excluded_set:
            if depth == 1 and root_entry is not None:
                entries_by_path[root_path] = replace(
                    root_entry,
                    status=MatrixStatus.BLOCKER_MISSING_DEPENDENCY,
                    detail=f"Required dependency {dep_relpath} was excluded by operator",
                )
            continue

        bfs_projects_resolved += 1
        if resolved_ver.project_id:
            installed_project_ids.add(resolved_ver.project_id)
            added_dep_paths_by_project[resolved_ver.project_id] = dep_relpath

        existing_at_path = entries_by_path.get(dep_relpath)
        if existing_at_path is None:
            cur_existing = current_by_path.get(dep_relpath)
            entries_by_path[dep_relpath] = MatrixEntry(
                path=dep_relpath,
                status=MatrixStatus.ADD,
                origin=Origin.MODRINTH.value,
                source_sha256=cur_existing.sha256 if cur_existing else None,
                source_sha512=_compute_entry_sha512(cur_existing, cas) if cur_existing else None,
                target_sha512=primary_file.sha512 or None,
                target_sha1=primary_file.sha1 or None,
                target_size=primary_file.size_bytes,
                target_project_id=resolved_ver.project_id,
                target_version_id=resolved_ver.version_id,
                target_version_number=resolved_ver.version_number,
                download_url=primary_file.url,
                required_by=(root_path,),
                detail=f"Auto-added required dependency at depth {depth}",
            )
        else:
            if root_path not in existing_at_path.required_by:
                entries_by_path[dep_relpath] = replace(
                    existing_at_path,
                    required_by=(*existing_at_path.required_by, root_path),
                )

        for child_dep in resolved_ver.dependencies:
            if (
                child_dep.dependency_type == "incompatible"
                and child_dep.project_id
                and child_dep.project_id in installed_project_ids
                and root_entry is not None
            ):
                entries_by_path[root_path] = replace(
                    entries_by_path[root_path],
                    status=MatrixStatus.BLOCKER_INCOMPATIBLE,
                    detail=(
                        f"Dependency {resolved_ver.project_id} is incompatible "
                        f"with {child_dep.project_id}"
                    ),
                )
            elif child_dep.dependency_type == "required":
                bfs_queue.append((root_path, child_dep, depth + 1))

    ordered_entries = tuple(
        sorted(
            [*entries_by_path.values(), *warning_entries],
            key=lambda item: (item.path, str(item.status)),
        )
    )
    return CompatibilityMatrix(
        source_mc=current_lockfile.mc,
        target_mc=target_mc,
        source_loader=current_lockfile.loader,
        target_loader=target_loader,
        entries=ordered_entries,
        bfs_depth_reached=bfs_depth_reached,
        bfs_projects_resolved=bfs_projects_resolved,
        excluded_paths=tuple(sorted(excluded_set)),
        kept_paths=tuple(sorted(kept_set)),
    )


__all__ = [
    "BLOCKER_STATUSES",
    "MAX_BFS_DEPTH",
    "MAX_BFS_PROJECTS",
    "MODRINTH_BATCH_CHUNK_SIZE",
    "CompatibilityMatrix",
    "MatrixEntry",
    "MatrixStatus",
    "build_compatibility_matrix",
]
