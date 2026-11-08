"""Core filesystem safety utilities."""

from __future__ import annotations

from pathlib import Path

from app.core.exceptions import PathContainmentError

__all__ = ["assert_inside_root"]


def assert_inside_root(path: str | Path, root: str | Path) -> Path:
    """Ensure ``path`` is a strict descendant of ``root`` and return it resolved.

    Both arguments are resolved first (symlinks followed). The root itself,
    its parents, siblings sharing a name prefix and anything reached through a
    symlink pointing outside are rejected with ``PathContainmentError``.
    """
    resolved_path = Path(path).resolve()
    resolved_root = Path(root).resolve()
    if resolved_path == resolved_root or not resolved_path.is_relative_to(resolved_root):
        raise PathContainmentError(str(path), str(root))
    return resolved_path
