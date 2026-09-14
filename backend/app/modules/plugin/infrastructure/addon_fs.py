from __future__ import annotations

import os
from pathlib import Path

from app.core.exceptions import InvalidValueError

MOD_SERVER_TYPES = frozenset({"fabric", "forge", "neoforge", "quilt"})
PLUGIN_SERVER_TYPES = frozenset({"bukkit", "paper", "purpur", "spigot", "folia"})


def get_addon_dir_name(server_type: str | None) -> str:
    """Return the filesystem directory name ('mods' or 'plugins') for a given server type."""
    if server_type and server_type.strip().lower() in MOD_SERVER_TYPES:
        return "mods"
    return "plugins"


def is_mod_server(server_type: str | None) -> bool:
    """Check if the given server type is a modded server (Fabric, Forge, NeoForge, Quilt)."""
    return bool(server_type and server_type.strip().lower() in MOD_SERVER_TYPES)


def sanitize_addon_filename(filename: str, target_dir: Path | str) -> Path:
    """Validate and sanitize an uploaded addon filename to prevent zip-slip / path traversal.

    Ensures the sanitized name stays strictly within target_dir and ends in '.jar'.
    Raises InvalidValueError on path traversal or invalid extension.
    """
    if not filename or not filename.strip():
        raise InvalidValueError(
            field="filename",
            value=filename,
            reason="Addon filename cannot be empty",
        )

    if "\x00" in filename:
        raise InvalidValueError(
            field="filename",
            value=filename,
            reason="Addon filename contains null byte",
        )

    base = os.path.basename(filename.strip().replace("\\", "/"))
    if not base or base in (".", ".."):
        raise InvalidValueError(
            field="filename",
            value=filename,
            reason="Invalid addon filename",
        )

    lower_base = base.lower()
    if not (lower_base.endswith(".jar") or lower_base.endswith(".jar.disabled")):
        raise InvalidValueError(
            field="filename",
            value=filename,
            reason="Addon file must have a .jar extension",
        )

    dir_path = Path(target_dir).resolve()
    target_path = (dir_path / base).resolve()

    if not target_path.is_relative_to(dir_path):
        raise InvalidValueError(
            field="filename",
            value=filename,
            reason="Path traversal detected",
        )

    return target_path


def toggle_addon_file(
    addon_dir: Path | str,
    filename: str,
    enabled: bool,
) -> tuple[Path, bool]:
    """Toggle an addon file on disk between active (.jar) and disabled (.jar.disabled).

    Returns tuple (final_path, actually_renamed).
    Raises FileNotFoundError if neither the enabled nor disabled file exists on disk.
    Raises OSError if renaming fails.
    """
    dir_path = Path(addon_dir).resolve()
    base = os.path.basename(filename)

    if base.lower().endswith(".jar.disabled"):
        active_name = base[:-9]
        disabled_name = base
    elif base.lower().endswith(".jar"):
        active_name = base
        disabled_name = f"{base}.disabled"
    else:
        active_name = f"{base}.jar"
        disabled_name = f"{base}.jar.disabled"

    active_path = dir_path / active_name
    disabled_path = dir_path / disabled_name

    if enabled:
        # Target: active (.jar)
        if active_path.exists():
            return active_path, False
        if disabled_path.exists():
            disabled_path.rename(active_path)
            return active_path, True
        raise FileNotFoundError(
            f"Neither '{disabled_name}' nor '{active_name}' exists in '{dir_path}'"
        )
    else:
        # Target: disabled (.jar.disabled)
        if disabled_path.exists():
            return disabled_path, False
        if active_path.exists():
            active_path.rename(disabled_path)
            return disabled_path, True
        raise FileNotFoundError(
            f"Neither '{active_name}' nor '{disabled_name}' exists in '{dir_path}'"
        )
