"""Branch-scoped server settings management for Advanced-mode servers.

Contract (OD-v8.8-3):
- Working branches (``branch != "main"``): updates normalized ``server.properties``
  (and optional ``config/onx-runtime.json`` JVM/CPU overrides) inside the branch
  worktree and creates a native Git commit automatically on that branch.
- ``main`` branch: NEVER mutates ``main`` or live ``<server_root>/server.properties``
  directly. Automatically creates or reuses a pending settings branch
  (``settings/main-<timestamp>``) with ``pending_merge_on_restart=True``, commits
  the staged settings there, and auto-merges into ``main`` cleanly when the
  ``main`` server restarts (aborting safely if a merge conflict occurs).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shlex
import time
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.allowlist import CLASS_D_PANEL_KEYS, open_safe_path_fd
from app.core.event_bus import EventBus
from app.core.exceptions import (
    BranchRuntimeActiveError,
    InvalidValueError,
    MergeConflictError,
    NotFoundError,
    ValidationError,
)
from app.core.host_state import (
    HostStateLayout,
    check_not_symlink_or_reparse,
    resolve_host_state_layout,
)
from app.modules.server.application.read_models import is_secret_property_key
from app.modules.server.application.services.jar_service import update_server_properties_key
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.events import ServerConfigChangedEvent
from app.modules.server.domain.value_objects import (
    CpuAllocation,
    JavaArguments,
    MemoryAllocation,
    ServerMode,
)
from app.modules.versioning.domain.events import (
    SettingsBranchAutoMergedOnRestartEvent,
    SettingsBranchCreatedEvent,
    SettingsCommittedEvent,
)
from app.modules.versioning.infrastructure.class_c_snapshot import ClassCSnapshotService
from app.modules.versioning.infrastructure.fs_atomic import atomic_write_private
from app.modules.versioning.infrastructure.git_branches import GitBranchService
from app.modules.versioning.infrastructure.git_merge import GitMergeService
from app.modules.versioning.infrastructure.git_repository import (
    MAIN_BRANCH,
    _normalize_server_properties,
)
from app.modules.versioning.infrastructure.git_runner import GitRunner
from app.modules.versioning.infrastructure.git_save_commit import GitSaveCommitService
from app.modules.versioning.infrastructure.models import ServerBranchModel

_PROP_KEY_MAP = {
    "port": "server-port",
    "max_players": "max-players",
    "spawn_protection": "spawn-protection",
    "enable_command_block": "enable-command-block",
    "online_mode": "online-mode",
    "whitelist": "white-list",
    "view_distance": "view-distance",
    "simulation_distance": "simulation-distance",
}
_RUNTIME_SETTINGS_RELPATH = "config/onx-runtime.json"
_logger = logging.getLogger(__name__)


def load_branch_runtime_overrides(worktree: Path) -> dict[str, Any]:
    """Load and validate ``config/onx-runtime.json`` overrides from a branch worktree."""
    if not worktree.is_dir():
        return {}
    check_not_symlink_or_reparse(worktree)
    rt_text = _read_worktree_text(worktree, _RUNTIME_SETTINGS_RELPATH)
    if not rt_text:
        return {}
    try:
        raw_doc = json.loads(rt_text)
    except Exception as exc:
        _logger.warning("Ignoring invalid %s in %s: %s", _RUNTIME_SETTINGS_RELPATH, worktree, exc)
        return {}
    if not isinstance(raw_doc, dict):
        return {}

    overrides: dict[str, Any] = {}
    raw_min = raw_doc.get("min_memory_mb")
    raw_max = raw_doc.get("max_memory_mb")
    if raw_min is not None or raw_max is not None:
        try:
            eff_min = int(raw_min) if raw_min is not None else 128
            eff_max = int(raw_max) if raw_max is not None else max(eff_min, 128)
            MemoryAllocation(min_mb=eff_min, max_mb=eff_max)
            if raw_min is not None:
                overrides["min_memory_mb"] = eff_min
            if raw_max is not None:
                overrides["max_memory_mb"] = eff_max
        except (TypeError, ValueError) as exc:
            _logger.warning("Ignoring invalid memory override in %s: %s", worktree, exc)

    raw_cores = raw_doc.get("cpu_cores")
    raw_affinity = raw_doc.get("cpu_affinity")
    if raw_cores is not None or raw_affinity is not None:
        try:
            eff_cores = int(raw_cores) if raw_cores is not None else 0
            eff_affinity = str(raw_affinity) if raw_affinity is not None else ""
            CpuAllocation(cores=eff_cores, affinity=eff_affinity)
            if raw_cores is not None:
                overrides["cpu_cores"] = eff_cores
            if raw_affinity is not None:
                overrides["cpu_affinity"] = eff_affinity
        except (TypeError, ValueError) as exc:
            _logger.warning("Ignoring invalid CPU override in %s: %s", worktree, exc)

    raw_java_args = raw_doc.get("java_args")
    if isinstance(raw_java_args, str):
        try:
            tokens = shlex.split(raw_java_args) if raw_java_args.strip() else []
            validated_args = JavaArguments(tokens)
            overrides["java_args"] = str(validated_args)
            overrides["java_args_list"] = validated_args.as_list()
        except (InvalidValueError, ValueError) as exc:
            _logger.warning("Ignoring invalid java_args override in %s: %s", worktree, exc)

    return overrides


def _parse_properties_text(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line or line.startswith(("#", "!")) or "=" not in line:
            continue
        k, _, v = line.partition("=")
        ck = k.strip()
        if is_secret_property_key(ck):
            continue
        parsed[ck] = v.strip()
    return parsed


def _serialize_properties_dict(props: dict[str, str]) -> str:
    lines = [f"{k}={props[k]}" for k in sorted(props.keys())]
    return "\n".join(lines) + ("\n" if lines else "")


def _read_worktree_text(worktree: Path, relpath: str) -> str | None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = open_safe_path_fd(str(worktree), relpath, flags=flags)
    except FileNotFoundError:
        return None
    try:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", errors="replace")
    finally:
        os.close(fd)


async def get_active_pending_settings_branch(
    session: Any,
    server_id: str,
) -> ServerBranchModel | None:
    res = await session.execute(
        select(ServerBranchModel)
        .where(
            ServerBranchModel.server_id == server_id,
            ServerBranchModel.pending_merge_on_restart.is_(True),
            ServerBranchModel.status != "archived",
        )
        .order_by(ServerBranchModel.created_at.desc())
    )
    return res.scalars().first()


def _pending_branch_payload(row: ServerBranchModel | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "branch_name": row.name,
        "head_commit_id": row.head_commit_id,
        "status": row.pending_merge_status or "pending",
        "error_message": row.pending_merge_error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def read_branch_settings_overlay(
    session: Any,
    server: Server,
    branch_name: str | None,
    *,
    layout: HostStateLayout | None = None,
) -> dict[str, Any]:
    """Return branch-scoped settings overrides + pending_settings_branch metadata."""
    eff_layout = layout or resolve_host_state_layout()
    effective_branch = (branch_name or MAIN_BRANCH).strip() or MAIN_BRANCH
    pending_row = await get_active_pending_settings_branch(session, str(server.id))
    pending_info = _pending_branch_payload(pending_row)

    if server.mode != ServerMode.ADVANCED or not server.deployment or not (
        server.deployment.root_path
    ):
        return {
            "branch_name": MAIN_BRANCH,
            "pending_settings_branch": None,
        }

    server_root = Path(os.path.abspath(server.deployment.root_path))
    branch_svc = GitBranchService(eff_layout)
    git_info = branch_svc.get_branch(str(server.id), server_root, effective_branch)
    if git_info is None:
        raise NotFoundError(f"Branch '{effective_branch}' not found on server '{server.id}'")

    # When viewing `main`, if a pending `settings/...` branch exists, surface its staged values.
    read_branch = git_info
    if effective_branch == MAIN_BRANCH and pending_row is not None:
        pending_git = branch_svc.get_branch(str(server.id), server_root, pending_row.name)
        if (
            pending_git is not None
            and pending_git.worktree_path
            and pending_git.worktree_path.is_dir()
        ):
            read_branch = pending_git

    worktree = read_branch.worktree_path
    props_text: str | None = None
    runtime_overrides: dict[str, Any] = {}
    if worktree is not None and worktree.is_dir():
        check_not_symlink_or_reparse(worktree)
        props_text = _read_worktree_text(worktree, "server.properties")
        rt_text = _read_worktree_text(worktree, _RUNTIME_SETTINGS_RELPATH)
        if rt_text:
            with contextlib.suppress(Exception):
                parsed_rt = json.loads(rt_text)
                if isinstance(parsed_rt, dict):
                    runtime_overrides = parsed_rt

    if props_text is None and effective_branch == MAIN_BRANCH:
        live_props = server.deployment.properties_path()
        if Path(live_props).is_file():
            with contextlib.suppress(OSError):
                props_text = Path(live_props).read_text(encoding="utf-8", errors="replace")

    raw_props = _parse_properties_text(props_text) if props_text is not None else {}

    def _as_bool(key: str, default: bool) -> bool:
        val = raw_props.get(key)
        if val is None:
            return default
        return val.strip().lower() in ("true", "1", "yes")

    def _as_int(key: str, default: int) -> int:
        val = raw_props.get(key)
        if val is None:
            return default
        try:
            return int(val.strip())
        except ValueError:
            return default

    overlay: dict[str, Any] = {
        "branch_name": effective_branch,
        "pending_settings_branch": pending_info,
    }
    if raw_props:
        overlay["raw_properties"] = raw_props
        overlay["motd"] = raw_props.get("motd", server.properties.motd)
        overlay["max_players"] = _as_int("max-players", server.properties.max_players)
        overlay["gamemode"] = raw_props.get("gamemode", server.properties.gamemode)
        overlay["difficulty"] = raw_props.get("difficulty", server.properties.difficulty)
        overlay["spawn_protection"] = _as_int(
            "spawn-protection", server.properties.spawn_protection
        )
        overlay["pvp"] = _as_bool("pvp", server.properties.pvp)
        overlay["enable_command_block"] = _as_bool(
            "enable-command-block", server.properties.enable_command_block
        )
        overlay["online_mode"] = _as_bool("online-mode", server.properties.online_mode)
        overlay["whitelist"] = _as_bool("white-list", server.properties.whitelist)
        overlay["view_distance"] = _as_int("view-distance", server.properties.view_distance)
        overlay["simulation_distance"] = _as_int(
            "simulation-distance", server.properties.simulation_distance
        )

    if runtime_overrides:
        if isinstance(runtime_overrides.get("min_memory_mb"), int):
            overlay["min_memory_mb"] = runtime_overrides["min_memory_mb"]
        if isinstance(runtime_overrides.get("max_memory_mb"), int):
            overlay["max_memory_mb"] = runtime_overrides["max_memory_mb"]
        if isinstance(runtime_overrides.get("cpu_cores"), int):
            overlay["cpu_cores"] = runtime_overrides["cpu_cores"]
        if isinstance(runtime_overrides.get("cpu_affinity"), str):
            overlay["cpu_affinity"] = runtime_overrides["cpu_affinity"]
        if isinstance(runtime_overrides.get("java_args"), str):
            overlay["java_args"] = runtime_overrides["java_args"]

    return overlay


async def save_branch_scoped_settings(
    *,
    session: Any,
    server: Server,
    branch_name: str,
    properties: dict[str, Any] | None = None,
    min_memory_mb: int | None = None,
    max_memory_mb: int | None = None,
    cpu_cores: int | None = None,
    cpu_affinity: str | None = None,
    java_args: list[str] | None = None,
    event_bus: EventBus | None = None,
    layout: HostStateLayout | None = None,
) -> dict[str, Any]:
    """Persist branch-scoped settings to working or `settings/...` pending branch."""
    _ = event_bus
    eff_layout = layout or resolve_host_state_layout()
    if server.deployment is None or not server.deployment.root_path:
        raise ValidationError("Server root path not configured", field="root_path")
    server_root = Path(os.path.abspath(server.deployment.root_path))
    effective_branch = (branch_name or MAIN_BRANCH).strip() or MAIN_BRANCH
    branch_svc = GitBranchService(eff_layout)

    # Validate requested branch exists
    req_git = branch_svc.get_branch(str(server.id), server_root, effective_branch)
    if req_git is None:
        raise NotFoundError(f"Branch '{effective_branch}' not found on server '{server.id}'")

    # Validate runtime overrides via domain value objects BEFORE creating/mutating any branch.
    has_runtime_updates = any(
        val is not None
        for val in (min_memory_mb, max_memory_mb, cpu_cores, cpu_affinity, java_args)
    )
    if min_memory_mb is not None or max_memory_mb is not None:
        eff_min = int(min_memory_mb) if min_memory_mb is not None else server.memory.min_mb
        eff_max = int(max_memory_mb) if max_memory_mb is not None else server.memory.max_mb
        try:
            MemoryAllocation(min_mb=eff_min, max_mb=eff_max)
        except ValueError as exc:
            raise ValidationError(str(exc), field="memory") from exc
    if cpu_cores is not None or cpu_affinity is not None:
        eff_cores = int(cpu_cores) if cpu_cores is not None else server.cpu.cores
        eff_affinity = str(cpu_affinity) if cpu_affinity is not None else server.cpu.affinity
        try:
            CpuAllocation(cores=eff_cores, affinity=eff_affinity)
        except ValueError as exc:
            raise ValidationError(str(exc), field="cpu") from exc
    validated_java_args: JavaArguments | None = None
    if java_args is not None:
        validated_java_args = JavaArguments(java_args)

    # Filter out protected Class-D / secret properties upfront and skip empty main branches.
    sanitized_props: dict[str, str] = {}
    if properties:
        for k, v in properties.items():
            file_key = _PROP_KEY_MAP.get(k, k.replace("_", "-"))
            if file_key in CLASS_D_PANEL_KEYS or is_secret_property_key(file_key):
                continue
            sanitized_props[file_key] = str(v).lower() if isinstance(v, bool) else str(v)

    if not sanitized_props and not has_runtime_updates:
        return {
            "target_branch": effective_branch,
            "commit_id": req_git.sha,
            "pending_settings_branch": None,
            "events": [],
        }

    events_to_emit: list[Any] = []
    if effective_branch == MAIN_BRANCH:
        # Auto-branch for main: never mutate main worktree or live directory directly!
        pending_row = await get_active_pending_settings_branch(session, str(server.id))
        target_branch: str | None = pending_row.name if pending_row is not None else None
        target_git = (
            branch_svc.get_branch(str(server.id), server_root, target_branch)
            if target_branch is not None
            else None
        )
        # If no pending branch exists yet, avoid creating one if nothing differs from main worktree.
        if (target_branch is None or target_git is None or target_git.worktree_path is None) and (
            req_git.worktree_path is not None and req_git.worktree_path.is_dir()
        ):
            main_wt = req_git.worktree_path
            main_props_raw = _read_worktree_text(main_wt, "server.properties") or ""
            main_props = _parse_properties_text(main_props_raw)
            props_differ = any(main_props.get(fk) != fv for fk, fv in sanitized_props.items())
            main_rt_text = _read_worktree_text(main_wt, _RUNTIME_SETTINGS_RELPATH)
            main_rt: dict[str, Any] = {}
            if main_rt_text:
                with contextlib.suppress(Exception):
                    parsed_rt = json.loads(main_rt_text)
                    if isinstance(parsed_rt, dict):
                        main_rt = parsed_rt
            rt_differs = (
                (
                    min_memory_mb is not None
                    and main_rt.get("min_memory_mb") != int(min_memory_mb)
                )
                or (
                    max_memory_mb is not None
                    and main_rt.get("max_memory_mb") != int(max_memory_mb)
                )
                or (cpu_cores is not None and main_rt.get("cpu_cores") != int(cpu_cores))
                or (cpu_affinity is not None and main_rt.get("cpu_affinity") != str(cpu_affinity))
                or (
                    validated_java_args is not None
                    and main_rt.get("java_args") != " ".join(validated_java_args.as_list())
                )
            )
            if not props_differ and not rt_differs:
                return {
                    "target_branch": MAIN_BRANCH,
                    "commit_id": req_git.sha,
                    "pending_settings_branch": _pending_branch_payload(pending_row),
                    "events": [],
                }

        if target_branch is None or target_git is None or target_git.worktree_path is None:
            import uuid

            slug = re.sub(r"[^a-z0-9-]+", "-", server.name.lower()).strip("-")[:16] or "srv"
            target_branch = f"settings/{slug}-{int(time.time())}-{uuid.uuid4().hex[:6]}"
            target_git = branch_svc.create_branch(
                str(server.id), server_root, target_branch, start_point=MAIN_BRANCH
            )

            pending_row = ServerBranchModel(
                id=uuid.uuid4().hex,
                server_id=str(server.id),
                name=target_branch,
                head_commit_id=target_git.sha,
                status="active",
                is_protected=False,
                pending_merge_on_restart=True,
                pending_merge_status="pending",
            )
            session.add(pending_row)
            await session.flush()
            events_to_emit.append(
                SettingsBranchCreatedEvent(
                    server_id=str(server.id),
                    branch_name=target_branch,
                    source_branch=MAIN_BRANCH,
                    commit_id=target_git.sha,
                )
            )
        assert pending_row is not None
    else:
        target_branch = effective_branch
        target_git = req_git
        pending_row = None

    if target_git.worktree_locked:
        raise BranchRuntimeActiveError(
            f"Cannot update settings while branch '{target_branch}' container is running "
            f"({target_git.worktree_lock_reason or 'locked'}). Stop the branch container first."
        )
    worktree = target_git.worktree_path
    if worktree is None or not worktree.is_dir():
        raise NotFoundError(f"Worktree for branch '{target_branch}' is missing")
    check_not_symlink_or_reparse(worktree)

    changed_keys: list[str] = []
    if sanitized_props:
        existing_props_text = _read_worktree_text(worktree, "server.properties") or ""
        current_props = _parse_properties_text(existing_props_text)
        # Strip any pre-existing Class-D panel keys as required by D-3/Allowlist
        for dk in list(current_props.keys()):
            if dk in CLASS_D_PANEL_KEYS or is_secret_property_key(dk):
                current_props.pop(dk, None)
        for file_key, str_val in sanitized_props.items():
            current_props[file_key] = str_val
            changed_keys.append(file_key)

        normalized_bytes = _normalize_server_properties(
            _serialize_properties_dict(current_props).encode("utf-8")
        )
        atomic_write_private(worktree / "server.properties", normalized_bytes)

    if has_runtime_updates:
        existing_rt_text = _read_worktree_text(worktree, _RUNTIME_SETTINGS_RELPATH)
        rt_doc: dict[str, Any] = {}
        if existing_rt_text:
            with contextlib.suppress(Exception):
                loaded = json.loads(existing_rt_text)
                if isinstance(loaded, dict):
                    rt_doc = loaded
        if min_memory_mb is not None:
            rt_doc["min_memory_mb"] = int(min_memory_mb)
            changed_keys.append("min_memory_mb")
        if max_memory_mb is not None:
            rt_doc["max_memory_mb"] = int(max_memory_mb)
            changed_keys.append("max_memory_mb")
        if cpu_cores is not None:
            rt_doc["cpu_cores"] = int(cpu_cores)
            changed_keys.append("cpu_cores")
        if cpu_affinity is not None:
            rt_doc["cpu_affinity"] = str(cpu_affinity)
            changed_keys.append("cpu_affinity")
        if validated_java_args is not None:
            rt_doc["java_args"] = " ".join(validated_java_args.as_list())
            changed_keys.append("java_args")
        # Re-validate merged min/max memory & CPU consistency on disk document
        merged_min = int(rt_doc.get("min_memory_mb", server.memory.min_mb))
        merged_max = int(rt_doc.get("max_memory_mb", server.memory.max_mb))
        try:
            MemoryAllocation(min_mb=merged_min, max_mb=merged_max)
        except ValueError as exc:
            raise ValidationError(str(exc), field="memory") from exc
        merged_cores = int(rt_doc.get("cpu_cores", server.cpu.cores))
        merged_aff = str(rt_doc.get("cpu_affinity", server.cpu.affinity))
        try:
            CpuAllocation(cores=merged_cores, affinity=merged_aff)
        except ValueError as exc:
            raise ValidationError(str(exc), field="cpu") from exc
        (worktree / "config").mkdir(parents=True, exist_ok=True)
        atomic_write_private(
            worktree / _RUNTIME_SETTINGS_RELPATH,
            (json.dumps(rt_doc, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )

    commit_msg = (
        f"chore(settings): stage main settings update on {target_branch}"
        if effective_branch == MAIN_BRANCH
        else f"chore(settings): update server settings on {target_branch}"
    )
    save_svc = GitSaveCommitService(eff_layout)
    save_res = save_svc.save(
        str(server.id),
        server_root,
        target_branch,
        commit_msg,
    )

    if pending_row is not None:
        pending_row.head_commit_id = save_res.commit_id
        pending_row.pending_merge_status = "pending"
        pending_row.pending_merge_error = None
    else:
        br_res = await session.execute(
            select(ServerBranchModel).where(
                ServerBranchModel.server_id == str(server.id),
                ServerBranchModel.name == target_branch,
            )
        )
        br_row = br_res.scalars().first()
        if br_row is not None:
            br_row.head_commit_id = save_res.commit_id
    await session.flush()

    events_to_emit.append(
        SettingsCommittedEvent(
            server_id=str(server.id),
            branch_name=target_branch,
            commit_id=save_res.commit_id,
            message=commit_msg,
        )
    )
    from app.modules.shared.value_objects import ServerId as _Sid

    events_to_emit.append(
        ServerConfigChangedEvent(
            server_id=_Sid(str(server.id)),
            changed_keys=changed_keys,
            branch_name=target_branch,
        )
    )

    return {
        "target_branch": target_branch,
        "commit_id": save_res.commit_id,
        "pending_settings_branch": _pending_branch_payload(pending_row),
        "events": events_to_emit,
    }


def _cleanup_settings_branch_dir(
    branch_svc: GitBranchService,
    server_id: str,
    server_root: Path,
    branch_name: str,
) -> None:
    """Force-remove a discarded settings/* worktree, empty parent dir, and Git ref."""
    import shutil

    runner = branch_svc._open_repository(server_id, server_root)
    wt_info = branch_svc.get_branch(server_id, server_root, branch_name)
    if wt_info is not None and wt_info.worktree_path:
        wt_path = Path(wt_info.worktree_path)
        with contextlib.suppress(Exception):
            runner.run("worktree", "remove", str(wt_path), check=False)
        if wt_path.exists():
            shutil.rmtree(wt_path, ignore_errors=True)
        with contextlib.suppress(Exception):
            runner.run("worktree", "prune", check=False)
        with contextlib.suppress(Exception):
            branch_svc._prune_empty_parents(wt_path.parent, server_root / ".onx" / "worktrees")
    with contextlib.suppress(Exception):
        runner.run("update-ref", "-d", f"refs/heads/{branch_name}", check=False)
    with contextlib.suppress(Exception):
        runner.run("branch", "-D", branch_name, check=False)


async def discard_pending_settings_branch(
    session: Any,
    server: Server,
    *,
    layout: HostStateLayout | None = None,
) -> bool:
    """Discard active pending `settings/...` branch for `main` without mutating `main`."""
    pending_row = await get_active_pending_settings_branch(session, str(server.id))
    if pending_row is None:
        return False

    eff_layout = layout or resolve_host_state_layout()
    if server.deployment and server.deployment.root_path:
        with contextlib.suppress(Exception):
            _cleanup_settings_branch_dir(
                GitBranchService(eff_layout),
                str(server.id),
                Path(os.path.abspath(server.deployment.root_path)),
                pending_row.name,
            )
    await session.delete(pending_row)
    await session.flush()
    return True


async def auto_merge_pending_settings_on_restart(
    server_id: str,
    event_bus: EventBus | None = None,
    *,
    layout: HostStateLayout | None = None,
) -> list[dict[str, Any]]:
    """Auto-merge any pending `settings/...` branches into `main` on server restart.

    Must only be invoked after the live server container/process is confirmed STOPPED.
    On MergeConflictError: marks branch `needs_resolution`, leaves live files untouched,
    and re-raises MergeConflictError.
    """
    from app.core.persistence.db import database
    from app.modules.server.infrastructure.repository import SQLServerRepository
    from app.modules.shared.value_objects import ServerId as _Sid

    eff_layout = layout or resolve_host_state_layout()
    applied: list[dict[str, Any]] = []

    async with database.session_factory() as session:
        server = await SQLServerRepository(session).get(_Sid(server_id))
        if (
            server is None
            or server.mode != ServerMode.ADVANCED
            or not server.deployment
            or not server.deployment.root_path
        ):
            return applied

        pending_rows = (
            await session.execute(
                select(ServerBranchModel)
                .where(
                    ServerBranchModel.server_id == server_id,
                    ServerBranchModel.pending_merge_on_restart.is_(True),
                    ServerBranchModel.status != "archived",
                )
                .order_by(ServerBranchModel.created_at.asc())
            )
        ).scalars().all()
        if not pending_rows:
            return applied

        server_root = Path(os.path.abspath(server.deployment.root_path))
        # Pre-merge Class-C safety snapshot per P3 contract
        with contextlib.suppress(Exception):
            ClassCSnapshotService(eff_layout).create_snapshot(server_id, server_root)

        merge_svc = GitMergeService(eff_layout)
        branch_svc = GitBranchService(eff_layout)

        for pending_row in pending_rows:
            try:
                merge_res = merge_svc.merge(
                    server_id=server_id,
                    server_root=server_root,
                    target_branch_name=MAIN_BRANCH,
                    parent_commit_ids=[MAIN_BRANCH, pending_row.name],
                    message=(
                        f"chore(settings): auto-merge {pending_row.name} "
                        f"into main on restart"
                    ),
                )
            except MergeConflictError as exc:
                pending_row.pending_merge_status = "needs_resolution"
                pending_row.pending_merge_error = str(exc)
                await session.commit()
                raise

            # Sync merged `main` server.properties onto live server root preserving Class-D keys
            runner = GitRunner(
                repo_path=eff_layout.repo_dir(server_id) / "repo.git",
                config_path=eff_layout.repo_dir(server_id) / "gitconfig",
            )
            show_props = runner.run(
                "show", f"{merge_res.commit_id}:server.properties", check=False
            )
            if show_props.returncode == 0 and show_props.stdout:
                merged_props = _parse_properties_text(show_props.stdout)
                props_path = server.deployment.properties_path()
                domain_updates: dict[str, Any] = {}
                for file_key, value in merged_props.items():
                    if file_key in CLASS_D_PANEL_KEYS or is_secret_property_key(file_key):
                        continue
                    update_server_properties_key(props_path, file_key, value)
                    if file_key == "motd":
                        domain_updates["motd"] = value
                    elif file_key == "gamemode":
                        domain_updates["gamemode"] = value
                    elif file_key == "difficulty":
                        domain_updates["difficulty"] = value
                    elif file_key == "max-players":
                        with contextlib.suppress(ValueError):
                            domain_updates["max_players"] = int(value)
                    elif file_key == "spawn-protection":
                        with contextlib.suppress(ValueError):
                            domain_updates["spawn_protection"] = int(value)
                    elif file_key == "pvp":
                        domain_updates["pvp"] = value.lower() in ("true", "1", "yes")
                    elif file_key == "enable-command-block":
                        domain_updates["enable_command_block"] = value.lower() in (
                            "true",
                            "1",
                            "yes",
                        )
                    elif file_key == "online-mode":
                        domain_updates["online_mode"] = value.lower() in ("true", "1", "yes")
                    elif file_key == "white-list":
                        domain_updates["whitelist"] = value.lower() in ("true", "1", "yes")
                    elif file_key == "view-distance":
                        with contextlib.suppress(ValueError):
                            domain_updates["view_distance"] = int(value)
                    elif file_key == "simulation-distance":
                        with contextlib.suppress(ValueError):
                            domain_updates["simulation_distance"] = int(value)
                if domain_updates:
                    server.update_properties(**domain_updates)

            # Sync merged runtime overrides (if present) onto ServerModel
            show_rt = runner.run(
                "show", f"{merge_res.commit_id}:{_RUNTIME_SETTINGS_RELPATH}", check=False
            )
            if show_rt.returncode == 0 and show_rt.stdout:
                with contextlib.suppress(Exception):
                    rt_doc = json.loads(show_rt.stdout)
                    if isinstance(rt_doc, dict):
                        from app.modules.server.domain.value_objects import (
                            CpuAllocation,
                            JavaArguments,
                            MemoryAllocation,
                        )

                        if "min_memory_mb" in rt_doc or "max_memory_mb" in rt_doc:
                            server.update_memory(
                                MemoryAllocation(
                                    min_mb=int(rt_doc.get("min_memory_mb", server.memory.min_mb)),
                                    max_mb=int(rt_doc.get("max_memory_mb", server.memory.max_mb)),
                                )
                            )
                        if "cpu_cores" in rt_doc or "cpu_affinity" in rt_doc:
                            server.update_cpu(
                                CpuAllocation(
                                    cores=int(rt_doc.get("cpu_cores", server.cpu.cores)),
                                    affinity=str(rt_doc.get("cpu_affinity", server.cpu.affinity)),
                                )
                            )
                        if "java_args" in rt_doc:
                            server.update_java_args(
                                JavaArguments(str(rt_doc["java_args"]).split())
                            )

            main_row = (
                await session.execute(
                    select(ServerBranchModel).where(
                        ServerBranchModel.server_id == server_id,
                        ServerBranchModel.name == MAIN_BRANCH,
                    )
                )
            ).scalars().first()
            if main_row is not None:
                main_row.head_commit_id = merge_res.commit_id

            with contextlib.suppress(Exception):
                branch_svc.delete_branch(server_id, server_root, pending_row.name)
                settings_parent = server_root / ".onx" / "worktrees" / "settings"
                if settings_parent.exists() and not any(settings_parent.iterdir()):
                    settings_parent.rmdir()
            await session.delete(pending_row)
            applied.append(
                {
                    "source_branch": pending_row.name,
                    "commit_id": merge_res.commit_id,
                }
            )

        await SQLServerRepository(session).save(server)
        await session.commit()

    if event_bus is not None:
        for item in applied:
            await event_bus.publish(
                SettingsBranchAutoMergedOnRestartEvent(
                    server_id=server_id,
                    branch_name=MAIN_BRANCH,
                    source_branch=item["source_branch"],
                    commit_id=item["commit_id"],
                )
            )
    return applied
