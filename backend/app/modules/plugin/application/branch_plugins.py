"""Branch-scoped plugin and mod management via host CAS and branch ``onx-jars.lock.json``.

In Advanced mode:
- ``main`` is strictly read-only for plugins/mods (fails closed with ``BranchProtectedError``).
- Working branches (``branch != "main"``) read from and write to
  ``<server_root>/.onx/worktrees/<branch>/onx-jars.lock.json`` and ingest JAR
  bytes into the host SHA-256 ``ArtifactCas``. They NEVER read or mutate
  ``<server_root>/plugins/`` or ``main``.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.allowlist import open_safe_path_fd, validate_canonical_relpath
from app.core.event_bus import EventBus
from app.core.exceptions import (
    BranchProtectedError,
    BranchRuntimeActiveError,
    ConflictError,
    CorruptedDownloadError,
    DownloadError,
    DownloadTimeoutError,
    InvalidValueError,
    NotFoundError,
    ProviderError,
    ValidationError,
)
from app.core.host_state import (
    HostStateLayout,
    check_not_symlink_or_reparse,
    resolve_host_state_layout,
)
from app.modules.plugin.application.services.version_selector import select_best_version
from app.modules.plugin.domain.events import (
    PluginDisabledEvent,
    PluginEnabledEvent,
    PluginInstalledEvent,
    PluginUninstalledEvent,
)
from app.modules.plugin.infrastructure.addon_fs import (
    get_addon_dir_name,
    sanitize_addon_filename,
)
from app.modules.plugin.infrastructure.jar_metadata_parser import parse_jar_metadata
from app.modules.plugin.infrastructure.providers import build_plugin_catalog_provider
from app.modules.plugin.infrastructure.providers.base import PluginFile
from app.modules.server.domain.aggregate import Server
from app.modules.versioning.application.lockfile_service import LockfileService
from app.modules.versioning.domain.lockfile import (
    EnvServer,
    LoaderRef,
    LockfileFile,
    LockfileV21,
    Origin,
    dump_lockfile,
    parse_lockfile,
)
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.fs_atomic import atomic_write_private
from app.modules.versioning.infrastructure.git_branches import GitBranchService
from app.modules.versioning.infrastructure.git_repository import (
    LOCKFILE_RELPATH,
    MAIN_BRANCH,
)
from app.modules.versioning.infrastructure.git_runner import GitRunner

_SHA1_RE = re.compile(r"^[0-9a-f]{40}\Z")
_SHA512_RE = re.compile(r"^[0-9a-f]{128}\Z")


def branch_plugin_id(server_id: str, branch_name: str, relpath: str) -> str:
    """Deterministic UUIDv5 identifier for a branch lockfile plugin/mod entry."""
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"branch-plugin:{server_id}:{branch_name}:{relpath}",
        )
    )


def _read_lockfile_bytes(worktree: Path) -> bytes | None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = open_safe_path_fd(str(worktree), LOCKFILE_RELPATH, flags=flags)
    except FileNotFoundError:
        return None
    try:
        chunks: list[bytes] = []
        total = 0
        max_bytes = 16 * 1024 * 1024
        while total < max_bytes:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def resolve_branch_lockfile(
    server_id: str,
    server_root: Path,
    branch_name: str,
    *,
    layout: HostStateLayout | None = None,
    commit_sha: str | None = None,
) -> LockfileV21 | None:
    """Resolve the authoritative lockfile for ``branch_name`` (worktree -> Git ref -> host)."""
    eff_layout = layout or resolve_host_state_layout()
    branch_svc = GitBranchService(eff_layout)
    git_info = branch_svc.get_branch(server_id, server_root, branch_name)
    if git_info is not None and git_info.worktree_path and git_info.worktree_path.is_dir():
        with contextlib.suppress(Exception):
            check_not_symlink_or_reparse(git_info.worktree_path)
            raw_bytes = _read_lockfile_bytes(git_info.worktree_path)
            if raw_bytes is not None:
                return parse_lockfile(raw_bytes)

    ref_candidates = [commit_sha, f"refs/heads/{branch_name}"]
    for ref in ref_candidates:
        if not ref:
            continue
        with contextlib.suppress(Exception):
            repo_dir = eff_layout.repo_dir(server_id)
            runner = GitRunner(
                repo_path=repo_dir / "repo.git",
                config_path=repo_dir / "gitconfig",
            )
            res = runner.run("show", f"{ref}:{LOCKFILE_RELPATH}", check=False)
            if res.returncode == 0 and res.stdout:
                return parse_lockfile(res.stdout.encode("utf-8"))

    return LockfileService(eff_layout).read(server_id)


def sync_lockfile_addons_to_dir(
    server_type: str,
    target_dir: Path,
    lockfile: LockfileV21,
    cas: ArtifactCas,
    *,
    prune: bool = True,
) -> None:
    """Materialize active/disabled addon JARs from ``lockfile`` into ``target_dir``."""
    if not target_dir.is_dir():
        return
    check_not_symlink_or_reparse(target_dir)

    addon_dir_name = get_addon_dir_name(server_type)
    addon_dir = target_dir / addon_dir_name
    addon_dir.mkdir(parents=True, exist_ok=True)
    check_not_symlink_or_reparse(addon_dir)

    desired_filenames: set[str] = set()
    for entry in lockfile.files:
        try:
            relpath = validate_canonical_relpath(entry.path)
        except ValueError:
            continue
        if not relpath.startswith(f"{addon_dir_name}/"):
            continue
        filename = Path(relpath).name
        desired_filenames.add(filename)

        # Always remove toggled counterpart (e.g., Foo.jar vs Foo.jar.disabled)
        if filename.lower().endswith(".jar.disabled"):
            counterpart = addon_dir / filename[:-9]
        elif filename.lower().endswith(".jar"):
            counterpart = addon_dir / f"{filename}.disabled"
        else:
            counterpart = None
        if counterpart is not None and counterpart.is_file() and not counterpart.is_symlink():
            with contextlib.suppress(OSError):
                counterpart.unlink(missing_ok=True)

        if not cas.has(entry.sha256):
            continue
        dest = target_dir / relpath
        if dest.is_symlink():
            continue
        needs_write = True
        if dest.is_file():
            try:
                fd = open_safe_path_fd(str(target_dir), relpath, flags=os.O_RDONLY)
                try:
                    h = hashlib.sha256()
                    while True:
                        chunk = os.read(fd, 65536)
                        if not chunk:
                            break
                        h.update(chunk)
                    needs_write = h.hexdigest() != entry.sha256
                finally:
                    os.close(fd)
            except Exception:
                needs_write = True
        if needs_write:
            with cas.open_blob(entry.sha256) as fh:
                data = fh.read()
            atomic_write_private(dest, data)

    if prune and addon_dir.is_dir():
        for existing in list(addon_dir.iterdir()):
            if existing.is_symlink() or not existing.is_file():
                continue
            low = existing.name.lower()
            if not (low.endswith(".jar") or low.endswith(".jar.disabled")):
                continue
            if existing.name not in desired_filenames:
                with contextlib.suppress(OSError):
                    existing.unlink(missing_ok=True)


def _read_head_lockfile(
    layout: HostStateLayout,
    server_id: str,
    branch_name: str,
) -> LockfileV21 | None:
    try:
        repo_dir = layout.repo_dir(server_id)
        runner = GitRunner(
            repo_path=repo_dir / "repo.git",
            config_path=repo_dir / "gitconfig",
        )
        res = runner.run(
            "show",
            f"refs/heads/{branch_name}:{LOCKFILE_RELPATH}",
            check=False,
        )
        if res.returncode == 0 and res.stdout:
            return parse_lockfile(res.stdout.encode("utf-8"))
    except Exception:
        return None
    return None


def _default_lockfile_for_server(server: Server, layout: HostStateLayout) -> LockfileV21:
    existing = LockfileService(layout).read(str(server.id))
    if existing is not None:
        return existing
    raw_type = (
        server.server_type.value.lower()
        if hasattr(server.server_type, "value")
        else "vanilla"
    )
    valid_loaders = {"paper", "purpur", "fabric", "forge", "neoforge", "quilt"}
    loader_id = raw_type if raw_type in valid_loaders else "paper"
    return LockfileV21(
        format=2,
        mc=str(server.minecraft_version),
        loader=LoaderRef(id=loader_id, version="latest"),
        base_overrides={},
        files=(),
    )


def _resolve_worktree_and_lockfile(
    server: Server,
    branch_name: str,
    *,
    layout: HostStateLayout | None = None,
    require_writable: bool = False,
) -> tuple[HostStateLayout, Path, Path, LockfileV21]:
    eff_layout = layout or resolve_host_state_layout()
    if server.deployment is None or not server.deployment.root_path:
        raise ValidationError("Server root path not configured", field="root_path")
    server_root = Path(server.deployment.root_path)
    branch_svc = GitBranchService(eff_layout)
    git_info = branch_svc.get_branch(str(server.id), server_root, branch_name)
    if git_info is None:
        raise NotFoundError(f"Branch '{branch_name}' not found on server '{server.id}'")

    if require_writable:
        if branch_name == MAIN_BRANCH:
            raise BranchProtectedError(
                "Branch 'main' is protected in Advanced Mode. Switch to or create a working "
                "branch to install, toggle, or remove plugins."
            )
        if git_info.worktree_locked:
            raise BranchRuntimeActiveError(
                f"Cannot modify plugins while branch '{branch_name}' runtime is active "
                f"({git_info.worktree_lock_reason or 'locked'}). Stop the branch container first."
            )

    worktree = git_info.worktree_path
    if worktree is None or not worktree.is_dir():
        raise NotFoundError(
            f"Worktree for branch '{branch_name}' is missing or not materialized"
        )
    check_not_symlink_or_reparse(worktree)

    raw_bytes = _read_lockfile_bytes(worktree)
    if raw_bytes is not None:
        lockfile = parse_lockfile(raw_bytes)
    else:
        head_lf = _read_head_lockfile(eff_layout, str(server.id), branch_name)
        lockfile = (
            head_lf
            if head_lf is not None
            else _default_lockfile_for_server(server, eff_layout)
        )
    return eff_layout, server_root, worktree, lockfile


def _parse_jar_from_cas_or_worktree(
    cas: ArtifactCas,
    worktree: Path,
    relpath: str,
    sha256: str,
):
    if cas.has(sha256):
        with contextlib.suppress(Exception):
            with cas.open_blob(sha256) as fh:
                return parse_jar_metadata(fh.read())
    with contextlib.suppress(Exception):
        fd = open_safe_path_fd(str(worktree), relpath, flags=os.O_RDONLY)
        try:
            chunks: list[bytes] = []
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                chunks.append(chunk)
            return parse_jar_metadata(b"".join(chunks))
        finally:
            os.close(fd)
    return None


def _write_branch_lockfile(worktree: Path, lockfile: LockfileV21) -> None:
    target = worktree / LOCKFILE_RELPATH
    atomic_write_private(target, dump_lockfile(lockfile))


def _uncommitted_jars_in_worktree(
    worktree: Path,
    addon_dir_name: str,
    known_paths: set[str],
) -> list[tuple[str, bytes]]:
    addon_dir = worktree / addon_dir_name
    if not addon_dir.is_dir() or addon_dir.is_symlink():
        return []
    found: list[tuple[str, bytes]] = []
    for entry in sorted(addon_dir.iterdir(), key=lambda p: p.name):
        if entry.is_symlink() or not entry.is_file():
            continue
        low = entry.name.lower()
        if not (low.endswith(".jar") or low.endswith(".jar.disabled")):
            continue
        rel = f"{addon_dir_name}/{entry.name}"
        if rel in known_paths:
            continue
        with contextlib.suppress(Exception):
            fd = open_safe_path_fd(str(worktree), rel, flags=os.O_RDONLY)
            try:
                chunks: list[bytes] = []
                while True:
                    chunk = os.read(fd, 65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
                found.append((rel, b"".join(chunks)))
            finally:
                os.close(fd)
    return found


def list_branch_plugins(
    server: Server,
    branch_name: str,
    *,
    layout: HostStateLayout | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """List plugins/mods from the branch worktree's ``onx-jars.lock.json`` + CAS."""
    eff_layout, _server_root, worktree, lockfile = _resolve_worktree_and_lockfile(
        server, branch_name, layout=layout, require_writable=False
    )
    addon_dir_name = get_addon_dir_name(server.server_type.value)
    head_lf = _read_head_lockfile(eff_layout, str(server.id), branch_name)
    committed_map: dict[str, str] = {}
    if head_lf is not None:
        for hf in head_lf.files:
            committed_map[hf.path] = hf.sha256

    cas = ArtifactCas(eff_layout.cas)
    now = datetime.now(UTC)
    results: list[dict[str, Any]] = []
    known_paths: set[str] = set()
    has_uncommitted = False

    # Detect lockfile deletions compared to HEAD
    worktree_paths = {f.path for f in lockfile.files}
    for hpath in committed_map:
        if hpath.startswith(f"{addon_dir_name}/") and hpath not in worktree_paths:
            has_uncommitted = True
            break

    for entry in lockfile.files:
        known_paths.add(entry.path)
        if not entry.path.startswith(f"{addon_dir_name}/"):
            continue
        filename = Path(entry.path).name
        is_disabled = filename.lower().endswith(".jar.disabled")
        is_committed = committed_map.get(entry.path) == entry.sha256
        if not is_committed:
            has_uncommitted = True

        meta = _parse_jar_from_cas_or_worktree(cas, worktree, entry.path, entry.sha256)
        display_name = (meta.name if meta and meta.name else None) or (
            meta.mod_id if meta and meta.mod_id else None
        ) or filename.removesuffix(".jar.disabled").removesuffix(".jar")
        version = (meta.version if meta and meta.version else None) or "locked"
        description = (meta.description if meta and meta.description else None) or ""
        author = ", ".join(meta.authors) if meta and meta.authors else ""
        loader = (meta.loader if meta and meta.loader else None) or lockfile.loader.id
        mod_id = meta.mod_id if meta else None
        warning = meta.warning if meta else None
        deps = list(meta.dependencies) if meta and meta.dependencies else []

        results.append(
            {
                "plugin_id": branch_plugin_id(str(server.id), branch_name, entry.path),
                "server_id": str(server.id),
                "name": display_name,
                "version": version,
                "description": description,
                "author": author,
                "status": "disabled" if is_disabled else "enabled",
                "dependencies": deps,
                "installed_at": now,
                "updated_at": now,
                "source": (
                    entry.origin.value
                    if hasattr(entry.origin, "value")
                    else str(entry.origin)
                ),
                "filename": filename,
                "pending_deletion": False,
                "pending_deletion_requested_at": None,
                "external_project_id": entry.project_id,
                "external_version_id": entry.version_id,
                "external_url": None,
                "checksum": entry.sha256,
                "icon_url": None,
                "loader": loader,
                "mod_id": mod_id,
                "is_disabled_on_disk": is_disabled,
                "warning": warning,
                "branch_name": branch_name,
                "is_committed": is_committed,
            }
        )

    # Also surface any uncommitted .jar dropped directly in the worktree addon folder
    for rel, raw_bytes in _uncommitted_jars_in_worktree(worktree, addon_dir_name, known_paths):
        has_uncommitted = True
        filename = Path(rel).name
        is_disabled = filename.lower().endswith(".jar.disabled")
        digest = hashlib.sha256(raw_bytes).hexdigest()
        meta = None
        with contextlib.suppress(Exception):
            meta = parse_jar_metadata(raw_bytes)
        display_name = (meta.name if meta and meta.name else None) or (
            meta.mod_id if meta and meta.mod_id else None
        ) or filename.removesuffix(".jar.disabled").removesuffix(".jar")
        results.append(
            {
                "plugin_id": branch_plugin_id(str(server.id), branch_name, rel),
                "server_id": str(server.id),
                "name": display_name,
                "version": (meta.version if meta and meta.version else None) or "uncommitted",
                "description": (meta.description if meta and meta.description else None) or "",
                "author": ", ".join(meta.authors) if meta and meta.authors else "",
                "status": "disabled" if is_disabled else "enabled",
                "dependencies": list(meta.dependencies) if meta and meta.dependencies else [],
                "installed_at": now,
                "updated_at": now,
                "source": "worktree",
                "filename": filename,
                "pending_deletion": False,
                "pending_deletion_requested_at": None,
                "external_project_id": None,
                "external_version_id": None,
                "external_url": None,
                "checksum": digest,
                "icon_url": None,
                "loader": meta.loader if meta else lockfile.loader.id,
                "mod_id": meta.mod_id if meta else None,
                "is_disabled_on_disk": is_disabled,
                "warning": meta.warning if meta else None,
                "branch_name": branch_name,
                "is_committed": False,
            }
        )

    return results, has_uncommitted


async def install_branch_modrinth_plugin(
    *,
    server: Server,
    branch_name: str,
    project_id: str,
    version_id: str | None = None,
    minecraft_version: str | None = None,
    event_bus: EventBus | None = None,
    provider: Any = None,
    layout: HostStateLayout | None = None,
) -> dict[str, Any]:
    """Download Modrinth JAR into CAS and register it in branch ``onx-jars.lock.json``."""
    eff_layout, _server_root, worktree, lockfile = _resolve_worktree_and_lockfile(
        server, branch_name, layout=layout, require_writable=True
    )
    server_type = server.server_type.value
    if server_type == "vanilla":
        raise ValidationError(
            "Vanilla servers do not support plugin installs from a catalog",
            field="server_type",
        )

    eff_provider = provider or build_plugin_catalog_provider()
    mc_ver = minecraft_version or str(server.minecraft_version)
    if version_id:
        try:
            ver = await eff_provider.get_version(version_id)
        except (DownloadError, DownloadTimeoutError) as exc:
            raise ProviderError(eff_provider.name, "fetch-version", str(exc)) from exc
        if ver.project_id != project_id:
            raise ValidationError(
                "Requested version does not belong to this project", field="version_id"
            )
        notice = ""
        notice_kind = ""
    else:
        try:
            page = await eff_provider.get_project_versions(project_id)
        except (DownloadError, DownloadTimeoutError) as exc:
            raise ProviderError(eff_provider.name, "fetch-versions", str(exc)) from exc
        selection = select_best_version(server_type, mc_ver, page.items)
        if selection.selected is None:
            raise ValidationError(
                selection.notice or "No compatible plugin version found", field="version_id"
            )
        ver = selection.selected
        notice = selection.notice
        notice_kind = selection.notice_kind

    plugin_file: PluginFile | None = None
    for f in ver.files:
        if f.primary:
            plugin_file = f
            break
    if plugin_file is None and ver.files:
        plugin_file = ver.files[0]
    if plugin_file is None:
        raise InvalidValueError(
            field="version.files",
            value=ver.version_id,
            reason="version has no downloadable file",
        )

    raw_filename = plugin_file.filename
    if not raw_filename or ".." in raw_filename or "/" in raw_filename or "\\" in raw_filename:
        raise InvalidValueError(
            field="filename", value=raw_filename, reason="Invalid plugin filename"
        )

    addon_dir_name = get_addon_dir_name(server_type)
    target_path = sanitize_addon_filename(raw_filename, worktree / addon_dir_name)
    safe_filename = target_path.name
    relpath = validate_canonical_relpath(f"{addon_dir_name}/{safe_filename}")

    if any(f.path.casefold() == relpath.casefold() for f in lockfile.files):
        raise ConflictError(
            f"A file named '{safe_filename}' already exists on branch '{branch_name}'"
        )

    if not plugin_file.sha1 and not plugin_file.sha512:
        raise CorruptedDownloadError(
            plugin_file.url,
            "catalog supplied neither sha1 nor sha512 checksum for verification",
        )
    content = await eff_provider.download(
        plugin_file.url,
        expected_sha1=plugin_file.sha1 or None,
        expected_sha512=plugin_file.sha512 or None,
    )

    cas = ArtifactCas(eff_layout.cas)
    sha256_digest = cas.put_bytes(content)

    sha1_val = (
        plugin_file.sha1.lower()
        if plugin_file.sha1 and _SHA1_RE.match(plugin_file.sha1.lower())
        else None
    )
    sha512_val = (
        plugin_file.sha512.lower()
        if plugin_file.sha512 and _SHA512_RE.match(plugin_file.sha512.lower())
        else None
    )

    new_entry = LockfileFile(
        path=relpath,
        sha256=sha256_digest,
        size=len(content),
        optional=False,
        env_server=EnvServer.REQUIRED,
        origin=Origin.MODRINTH,
        sha512=sha512_val,
        sha1=sha1_val,
        project_id=project_id,
        version_id=ver.version_id,
    )
    updated_lockfile = replace(lockfile, files=lockfile.files + (new_entry,))
    _write_branch_lockfile(worktree, updated_lockfile)

    meta = None
    with contextlib.suppress(Exception):
        meta = parse_jar_metadata(content)

    pid = branch_plugin_id(str(server.id), branch_name, relpath)
    if event_bus is not None:
        await event_bus.publish(
            PluginInstalledEvent(
                plugin_id=pid,
                server_id=str(server.id),
                version=ver.version_number,
                name=ver.name or project_id,
                file_name=safe_filename,
                source="modrinth",
                branch_name=branch_name,
            )
        )

    return {
        "plugin_id": pid,
        "version": ver.version_number,
        "filename": safe_filename,
        "source": eff_provider.name,
        "notice": notice,
        "notice_kind": notice_kind,
        "loader": (meta.loader if meta else None) or (ver.loaders[0] if ver.loaders else None),
        "mod_id": meta.mod_id if meta else None,
        "warning": meta.warning if meta else None,
        "checksum": sha256_digest,
        "branch_name": branch_name,
        "is_committed": False,
    }


async def upload_branch_addon(
    *,
    server: Server,
    branch_name: str,
    filename: str,
    file_content: bytes,
    event_bus: EventBus | None = None,
    layout: HostStateLayout | None = None,
) -> dict[str, Any]:
    """Ingest uploaded JAR into CAS and register it in branch ``onx-jars.lock.json``."""
    eff_layout, _server_root, worktree, lockfile = _resolve_worktree_and_lockfile(
        server, branch_name, layout=layout, require_writable=True
    )
    addon_dir_name = get_addon_dir_name(server.server_type.value)
    target_path = sanitize_addon_filename(filename, worktree / addon_dir_name)
    safe_filename = target_path.name
    relpath = validate_canonical_relpath(f"{addon_dir_name}/{safe_filename}")

    if any(f.path.casefold() == relpath.casefold() for f in lockfile.files):
        raise ConflictError(
            f"A file named '{safe_filename}' already exists on branch '{branch_name}'"
        )

    meta = parse_jar_metadata(file_content)
    cas = ArtifactCas(eff_layout.cas)
    sha256_digest = cas.put_bytes(file_content)

    new_entry = LockfileFile(
        path=relpath,
        sha256=sha256_digest,
        size=len(file_content),
        optional=False,
        env_server=EnvServer.REQUIRED,
        origin=Origin.USER,
    )
    updated_lockfile = replace(lockfile, files=lockfile.files + (new_entry,))
    _write_branch_lockfile(worktree, updated_lockfile)

    pid = branch_plugin_id(str(server.id), branch_name, relpath)
    mod_name = meta.name or meta.mod_id or target_path.stem
    if event_bus is not None:
        await event_bus.publish(
            PluginInstalledEvent(
                plugin_id=pid,
                server_id=str(server.id),
                version=meta.version or "unknown",
                name=mod_name,
                file_name=safe_filename,
                source="user",
                branch_name=branch_name,
            )
        )

    return {
        "plugin_id": pid,
        "name": mod_name,
        "version": meta.version or "unknown",
        "filename": safe_filename,
        "source": "user",
        "checksum": sha256_digest,
        "loader": meta.loader,
        "mod_id": meta.mod_id,
        "warning": meta.warning,
        "branch_name": branch_name,
        "is_committed": False,
    }


async def remove_branch_plugin(
    *,
    server: Server,
    branch_name: str,
    plugin_identifier: str,
    event_bus: EventBus | None = None,
    layout: HostStateLayout | None = None,
) -> None:
    """Remove a plugin/mod entry from branch ``onx-jars.lock.json`` without touching main or CAS."""
    _eff_layout, _server_root, worktree, lockfile = _resolve_worktree_and_lockfile(
        server, branch_name, layout=layout, require_writable=True
    )
    server_id = str(server.id)
    addon_dir_name = get_addon_dir_name(server.server_type.value)

    remaining: list[LockfileFile] = []
    removed: LockfileFile | None = None
    for entry in lockfile.files:
        bid = branch_plugin_id(server_id, branch_name, entry.path)
        fname = Path(entry.path).name
        targets = (bid, entry.path, fname, entry.project_id or "")
        if removed is None and plugin_identifier in targets:
            removed = entry
            continue
        remaining.append(entry)

    # Also check uncommitted raw files in worktree addon dir
    removed_untracked_rel: str | None = None
    if removed is None:
        tracked = {f.path for f in lockfile.files}
        for rel, _ in _uncommitted_jars_in_worktree(worktree, addon_dir_name, tracked):
            bid = branch_plugin_id(server_id, branch_name, rel)
            if plugin_identifier in (bid, rel, Path(rel).name):
                removed_untracked_rel = rel
                break

    if removed is None and removed_untracked_rel is None:
        raise NotFoundError(f"Plugin '{plugin_identifier}' not found on branch '{branch_name}'")

    target_rel = removed.path if removed is not None else removed_untracked_rel
    if removed is not None:
        updated_lockfile = replace(lockfile, files=tuple(remaining))
        _write_branch_lockfile(worktree, updated_lockfile)

    # Remove any matching jar inside the branch worktree (never in CAS, never in live server root).
    if target_rel:
        candidate = worktree / target_rel
        if candidate.is_file() and not candidate.is_symlink():
            with contextlib.suppress(OSError):
                candidate.unlink(missing_ok=True)

    if event_bus is not None:
        await event_bus.publish(
            PluginUninstalledEvent(
                plugin_id=plugin_identifier,
                server_id=server_id,
                name=Path(target_rel).name if target_rel else plugin_identifier,
                branch_name=branch_name,
            )
        )


async def toggle_branch_plugin(
    *,
    server: Server,
    branch_name: str,
    plugin_identifier: str,
    enabled: bool,
    event_bus: EventBus | None = None,
    layout: HostStateLayout | None = None,
) -> dict[str, Any]:
    """Enable/disable a plugin/mod in the branch ``onx-jars.lock.json`` (.jar <-> .jar.disabled)."""
    _eff_layout, _server_root, worktree, lockfile = _resolve_worktree_and_lockfile(
        server, branch_name, layout=layout, require_writable=True
    )
    server_id = str(server.id)
    new_files: list[LockfileFile] = []
    toggled: LockfileFile | None = None
    updated_entry: LockfileFile | None = None

    for entry in lockfile.files:
        bid = branch_plugin_id(server_id, branch_name, entry.path)
        fname = Path(entry.path).name
        targets = (bid, entry.path, fname, entry.project_id or "")
        if toggled is None and plugin_identifier in targets:
            toggled = entry
            if enabled and entry.path.lower().endswith(".jar.disabled"):
                new_path = entry.path[:-9]
            elif not enabled and entry.path.lower().endswith(".jar"):
                new_path = f"{entry.path}.disabled"
            else:
                new_path = entry.path
            updated_entry = replace(entry, path=new_path)
            new_files.append(updated_entry)
        else:
            new_files.append(entry)

    if toggled is None or updated_entry is None:
        raise NotFoundError(f"Plugin '{plugin_identifier}' not found on branch '{branch_name}'")

    if toggled.path != updated_entry.path:
        _write_branch_lockfile(worktree, replace(lockfile, files=tuple(new_files)))

    if event_bus is not None:
        ev_cls = PluginEnabledEvent if enabled else PluginDisabledEvent
        await event_bus.publish(
            ev_cls(
                plugin_id=branch_plugin_id(server_id, branch_name, updated_entry.path),
                server_id=server_id,
                branch_name=branch_name,
            )
        )

    return {
        "plugin_id": branch_plugin_id(server_id, branch_name, updated_entry.path),
        "enabled": enabled,
        "filename": Path(updated_entry.path).name,
        "branch_name": branch_name,
    }


def sync_main_lockfile_addons_to_server_root(
    server: Server,
    *,
    layout: HostStateLayout | None = None,
    force_prune: bool = False,
) -> None:
    """Sync ``main``'s lockfile and materialize CAS addon JARs to the live server root."""
    if server.deployment is None or not server.deployment.root_path:
        return
    server_root = Path(server.deployment.root_path)
    if not server_root.is_dir():
        return
    check_not_symlink_or_reparse(server_root)

    eff_layout = layout or resolve_host_state_layout()
    head_lf = _read_head_lockfile(eff_layout, str(server.id), MAIN_BRANCH)
    if head_lf is None:
        return

    with contextlib.suppress(Exception):
        LockfileService(eff_layout).write(str(server.id), head_lf)

    status_val = str(getattr(server.status, "value", server.status) or "").lower()
    sync_lockfile_addons_to_dir(
        server.server_type.value,
        server_root,
        head_lf,
        ArtifactCas(eff_layout.cas),
        prune=force_prune or status_val == "stopped",
    )
