from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from app.modules.versioning.domain.value_objects import Tree
from app.modules.versioning.infrastructure.fs_atomic import atomic_replace_dir


def write_tree_to_dir(
    tree: Tree,
    target_root: str | Path,
    *,
    server_dir: str | Path | None = None,
    verify: bool = True,
) -> None:
    """Materialize a Tree to a target directory atomically without partial writes.

    Plain-file writes only (no reflink, no chmod/exec handling). Writes to a same-parent
    sibling staging directory, atomically swaps into target_root, and verifies all tracked
    files match the Tree specification.
    """
    target_path = Path(target_root).resolve()
    parent = target_path.parent
    parent.mkdir(parents=True, exist_ok=True)

    staging_dir = parent / f".{target_path.name}.staging_{uuid.uuid4().hex}"
    staging_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1. Write configuration files
        configs = tree.configs if hasattr(tree, "configs") and tree.configs else {}
        for rel_path, content in configs.items():
            norm_rel = os.path.normpath(rel_path).replace("\\", "/")
            if norm_rel.startswith("..") or os.path.isabs(rel_path):
                raise ValueError(f"Config path escapes target root: {rel_path}")

            dest_file = staging_dir / norm_rel
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            dest_file.write_text(content, encoding="utf-8")

        # 2. Copy mod files if source server directory is accessible
        s_path = Path(server_dir).resolve() if server_dir else None
        mods = tree.mods if hasattr(tree, "mods") and tree.mods else []
        for m in mods:
            if not isinstance(m, dict):
                continue
            mod_filename = m.get("filename")
            if not mod_filename:
                continue
            norm_mod = os.path.normpath(mod_filename).replace("\\", "/")
            if norm_mod.startswith("..") or os.path.isabs(mod_filename):
                raise ValueError(f"Mod path escapes target root: {mod_filename}")

            if s_path:
                src_file = s_path / norm_mod
                if src_file.is_file():
                    dest_mod = staging_dir / norm_mod
                    dest_mod.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_file, dest_mod)

        # 3. Atomically replace target directory
        atomic_replace_dir(staging_dir, target_path)

        # 4. Post-write verification pass
        if verify:
            for rel_path, content in configs.items():
                norm_rel = os.path.normpath(rel_path).replace("\\", "/")
                verified_file = target_path / norm_rel
                if not verified_file.is_file():
                    raise RuntimeError(
                        f"Post-write verify failed: missing expected file {rel_path}"
                    )
                verified_content = verified_file.read_text(encoding="utf-8")
                if verified_content != content:
                    raise RuntimeError(
                        f"Post-write verify failed: content mismatch for {rel_path}"
                    )

    except Exception:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        if target_path.exists():
            shutil.rmtree(target_path, ignore_errors=True)
        raise
