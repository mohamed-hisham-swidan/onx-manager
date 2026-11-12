"""Allow-list v2.3 implementation."""

from __future__ import annotations

import errno
import os
import posixpath
import re
import stat
import unicodedata
from collections.abc import Set


class SymlinkEscapeError(ValueError):
    """Raised when a path component is a symlink or the target escapes the root."""


def validate_canonical_relpath(path: str) -> str:
    """Step 0 (lexical): mandatory sanitizer before classification, staging,
    lockfile parse, or export.
    """
    if not isinstance(path, str) or not path:
        raise ValueError("Path must be a non-empty string")
    if unicodedata.normalize("NFC", path) != path:
        raise ValueError(f"Path is not Unicode NFC normalized: {path!r}")
    if any(ch in path for ch in ("\x00", "\n", "\r", "\\", ":")):
        raise ValueError(f"Path contains forbidden control or separator characters: {path!r}")
    if path.startswith("/") or path.endswith("/"):
        raise ValueError(f"Path must be relative without leading/trailing slash: {path!r}")
    segments = path.split("/")
    if any(seg in ("", ".", "..") or seg.endswith((" ", ".")) for seg in segments):
        raise ValueError(f"Path contains traversal, empty, or trailing-dot/space segment: {path!r}")
    if posixpath.normpath(path) != path:
        raise ValueError(f"Path is not canonical POSIX form: {path!r}")
    return path


def _reject_windows_reparse(st: os.stat_result) -> None:
    """Reject NTFS junctions/reparse points in addition to POSIX symlinks (Windows hosts)."""
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if getattr(st, "st_file_attributes", 0) & reparse:
        raise SymlinkEscapeError("Windows reparse point/junction rejected")


def _open_root_dir(root_dir: str) -> int:
    """Open root_dir as a directory fd, refusing a symlinked root and verifying its identity."""
    if os.path.islink(root_dir):
        raise SymlinkEscapeError(f"Root itself is a symlink: {root_dir!r}")
    root_real = os.path.realpath(root_dir)
    if not os.path.isdir(root_real):
        raise ValueError(f"Root is not an existing directory: {root_dir!r}")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(root_real, flags)
    try:
        expected = os.stat(root_real)
        st = os.fstat(fd)
        if (st.st_dev, st.st_ino) != (expected.st_dev, expected.st_ino):
            raise SymlinkEscapeError(f"Root directory identity changed during open: {root_dir!r}")
        _reject_windows_reparse(st)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _open_dir_at(dir_fd: int, seg: str, *, create: bool = False) -> int:
    """Open one directory component relative to dir_fd, never following a symlink."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        return os.open(seg, flags, dir_fd=dir_fd)
    except FileNotFoundError:
        if not create:
            raise
        os.mkdir(seg, 0o755, dir_fd=dir_fd)
        try:
            return os.open(seg, flags, dir_fd=dir_fd)
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                raise SymlinkEscapeError(
                    f"Symlink or non-directory component rejected: {seg!r}"
                ) from exc
            raise
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise SymlinkEscapeError(
                f"Symlink or non-directory component rejected: {seg!r}"
            ) from exc
        raise


def open_safe_path_fd(
    root_dir: str,
    rel_path: str,
    *,
    flags: int = os.O_RDONLY,
    mode: int = 0o644,
    allow_create_parents: bool = False,
) -> int:
    """TOCTOU-free open of rel_path under root_dir using descriptor-relative traversal.

    Every hop is os.open(..., O_DIRECTORY | O_NOFOLLOW, dir_fd=...), so replacing an
    intermediate component with a symlink between validation and use cannot redirect the
    open. The caller owns the returned fd.
    """
    rel_path = validate_canonical_relpath(rel_path)
    segments = rel_path.split("/")
    curr_fd = _open_root_dir(root_dir)
    try:
        for seg in segments[:-1]:
            next_fd = _open_dir_at(curr_fd, seg, create=allow_create_parents)
            _reject_windows_reparse(os.fstat(next_fd))
            os.close(curr_fd)
            curr_fd = next_fd
        try:
            return os.open(
                segments[-1],
                flags | getattr(os, "O_NOFOLLOW", 0),
                mode,
                dir_fd=curr_fd,
            )
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise SymlinkEscapeError(f"Final symlink rejected: {rel_path!r}") from exc
            raise
    finally:
        os.close(curr_fd)


def resolve_safe_disk_path(
    root_dir: str, rel_path: str, *, allow_create_parents: bool = False
) -> str:
    """Validate containment with a descriptor-relative walk and return the target path.

    A path string alone can still be raced after return, so callers that mutate must use
    open_safe_path_fd (or pass dir_fd) instead of re-opening the returned string.
    """
    rel_path = validate_canonical_relpath(rel_path)
    root_real = os.path.realpath(root_dir)
    segments = rel_path.split("/")
    fd = _open_root_dir(root_dir)
    try:
        for seg in segments[:-1]:
            try:
                next_fd = _open_dir_at(fd, seg, create=allow_create_parents)
            except FileNotFoundError:
                if not allow_create_parents:
                    break
                raise
            _reject_windows_reparse(os.fstat(next_fd))
            os.close(fd)
            fd = next_fd
    finally:
        os.close(fd)

    target = os.path.join(root_real, *segments)
    target_real = os.path.realpath(target)
    if target_real == root_real or os.path.commonpath([root_real, target_real]) != root_real:
        raise SymlinkEscapeError(f"Path escapes root after resolution: {rel_path!r}")
    return target_real


def open_no_follow(path: str, flags: int = os.O_RDONLY) -> int:
    """Open a resolved file refusing to traverse a final symlink where the OS
    supports O_NOFOLLOW.
    """
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    return os.open(path, flags | nofollow)


HOSTILE_EXECUTABLE_QUARANTINE_REGEX = re.compile(
    r"\A(?:config|defaultconfigs|kubejs|scripts|datapacks|global_packs|patchouli_books"
    r"|schematics|blueprints|structures|structured-config)/.*\."
    r"(?:jar|war|class|so|dll|dylib|exe|sh|bat|cmd|ps1)\Z",
    re.IGNORECASE,
)

CLASS_E_DENYLIST_REGEX = re.compile(
    r"\A(?:"
    r"world(?:_nether|_the_end)?(?:/.*|\Z)"
    r"|\A(?:DIM-1|DIM1)(?:/.*|\Z)"
    r"|(?!\A(?:config|defaultconfigs|plugins|kubejs|datapacks|global_packs|resourcepacks"
    r"|shaderpacks|patchouli_books|scripts|structured-config|blueprints|schematics|structures)/)"
    r"(?:[^/]+/)+(?:dimensions/[^/]+/[^/]+|DIM-1|DIM1|region|entities|poi|advancements|stats|serverconfig)(?:/.*|\Z)"
    r"|logs(?:/.*|\Z)|crash-reports(?:/.*|\Z)|debug(?:/.*|\Z)"
    r"|cache(?:/.*|\Z)|\.cache(?:/.*|\Z)|libraries(?:/.*|\Z)|versions(?:/.*|\Z)"
    r"|\.fabric(?:/.*|\Z)|\.paper-remapped(?:/.*|\Z)|\.mixin\.out(?:/.*|\Z)"
    r"|mods/\.(?:connector|index)(?:/.*|\Z)"
    r"|kubejs/(?:probe|exported|\.cache)(?:/.*|\Z)"
    r"|config/(?:[^/]+/)*cache(?:/.*|\Z)"
    r"|plugins/[^/]+/cache(?:/.*|\Z)"
    r"|plugins/[^/]+/(?:userdata|data|players|playerdata|storage)/(?:[^/]+/)*[^/]+\."
    r"(?:png|jpg|jpeg|webp|gif|bmp|bin|zip|gz|tar|mca|mcr|dat|dat_old|db|sqlite|sqlite3)\Z"
    r"|journeymap(?:/.*|\Z)|Xaero[^/]*(?:/.*|\Z)|local(?:/.*|\Z)"
    r"|version_history\.json\Z|patched_[^/]+\.jar\Z|crafttweaker\.log\Z"
    r"|run\.sh\Z|run\.bat\Z|user_jvm_args\.txt\Z|eula\.txt\Z|\.gitattributes\Z"
    r"|(?!plugins/[^/]+\.jar\Z|mods/(?:[^/]+/)*[^/]+\.jar\Z|(?:shaderpacks|resourcepacks)/(?:[^/]+/)*[^/]+\.jar\Z)(?:[^/]+/)+[^/]+\.jar\Z"
    r"|(?!\A(?:schematics|blueprints|structures)/(?:[^/]+/)*[^/]+\.nbt\Z|\A(?:datapacks|global_packs|kubejs/data)/(?:[^/]+/)*structures/(?:[^/]+/)*[^/]+\.nbt\Z)(?:[^/]+/)*[^/]+\.nbt\Z"
    r"|(?:[^/]+/)*[^/]+\.(?:db|sqlite|sqlite3|db-wal|db-shm|sqlite-wal|sqlite-shm|mv\.db|trace\.db|h2\.db"
    r"|lock|lck|pid|log|gz|tar|mca|mcr|dat|dat_old|class|war|so|dll|dylib|csv|bak)\Z"
    r")"
)

CLASS_A_JAR_REGEX = re.compile(r"\A(?:[^/]+\.jar|plugins/[^/]+\.jar|mods/(?:[^/]+/)*[^/]+\.jar)\Z")

CLASS_A_CAS_BINARY_REGEX = re.compile(
    r"\A(?:"
    r"(?:shaderpacks|resourcepacks)/(?:[^/]+/)*[^/]+\."
    r"(?:zip|jar|png|ogg|bin|mcmeta|json|lang|properties|txt|fsh|vsh|glsl|cfg)"
    r"|kubejs/assets/(?:[^/]+/)*[^/]+\.(?:png|ogg|bin|webp|ttf|otf)"
    r"|patchouli_books/(?:[^/]+/)*[^/]+\.(?:png|ogg|bin)"
    r"|(?:structured-config|blueprints|schematics|structures)/(?:[^/]+/)*[^/]+\."
    r"(?:nbt|schem|schematic|litematic|png|bin|zip)"
    r"|(?:datapacks|global_packs|kubejs/data)/(?:[^/]+/)*structures/(?:[^/]+/)*[^/]+\.nbt"
    r")\Z"
)

CLASS_C_LIVE_STATE_REGEX = re.compile(
    r"\A(?:"
    r"ops\.json|whitelist\.json|banned-players\.json|banned-ips\.json|usercache\.json"
    r"|plugins/Essentials/warps/(?:[^/]+/)*[^/]+\.yml"
    r"|plugins/WorldGuard/worlds/(?:[^/]+/)*regions\.yml"
    r"|plugins/Citizens/saves\.yml"
    r"|plugins/[^/]+/(?:userdata|data|players|playerdata|storage)/(?:[^/]+/)*[^/]+\.(?:yml|yaml|json|txt)"
    r"|plugins/[^/]+/(?:data|players|userdata|database|storage)\.(?:yml|yaml|json|txt)"
    r"|(?:plugins/[^/]+|config)/(?:[^/]+/)*[^/]+\.(?:pem|key|p12|pfx|jks|keystore)"
    r"|voicechat/(?:[^/]+/)*[^/]+\.(?:properties|conf|json|yml)"
    r")\Z"
)

CLASS_B_CONFIG_ALLOWLIST_REGEX = re.compile(
    r"\A(?:"
    r"server\.properties|server-icon\.png|modrinth\.index\.json"
    r"|bukkit\.yml|spigot\.yml|commands\.yml|help\.yml|permissions\.yml|pufferfish\.yml|purpur\.yml"
    r"|(?:config|defaultconfigs)/(?:[^/]+/)*[^/]+\."
    r"(?:toml|json|json5|yml|yaml|properties|conf|cfg|snbt|xml|txt|mcfunction|mcmeta)"
    r"|plugins/[^/]+/(?:[^/]+/)*[^/]+\."
    r"(?:yml|yaml|json|json5|toml|properties|conf|cfg|snbt|xml|txt|lang|sk|dsc|mcfunction|mcmeta)"
    r"|kubejs/(?:startup_scripts|server_scripts|client_scripts)/(?:[^/]+/)*[^/]+\.js"
    r"|kubejs/(?:config|data)/(?:[^/]+/)*[^/]+\.(?:json|json5|yml|yaml|toml|txt|snbt)"
    r"|kubejs/assets/(?:[^/]+/)*[^/]+\.(?:json|lang|mcmeta)"
    r"|scripts/(?:[^/]+/)*[^/]+\.zs"
    r"|(?:datapacks|global_packs)/(?:[^/]+/)*[^/]+\.(?:json|mcmeta|mcfunction|txt|snbt)"
    r"|patchouli_books/(?:[^/]+/)*[^/]+\.json"
    r"|(?:structured-config|blueprints|schematics|structures)/(?:[^/]+/)*[^/]+\.(?:json|json5|yml|yaml|toml|txt|snbt)"
    r")\Z"
)

CLASS_D_PANEL_KEYS = frozenset(
    {
        "server-port",
        "query.port",
        "rcon.port",
        "rcon.password",
        "enable-rcon",
        "enable-query",
        "broadcast-rcon-to-ops",
    }
)
# Plus any key matching prefix "management-server-"


def classify(path: str, *, dynamic_class_c: Set[str] = frozenset()) -> str:
    """Classify a path according to the Allow-list v2.3 9-step evaluation order."""
    try:
        norm_path = validate_canonical_relpath(path)
    except ValueError:
        return "REJECT-PATH"

    if HOSTILE_EXECUTABLE_QUARANTINE_REGEX.match(norm_path):
        return "QUARANTINE"

    if norm_path in dynamic_class_c:
        return "C"

    if norm_path == "onx-jars.lock.json":
        return "A-LOCKFILE"

    if CLASS_E_DENYLIST_REGEX.match(norm_path):
        return "E"

    if CLASS_A_JAR_REGEX.match(norm_path):
        return "A-JAR"

    if CLASS_A_CAS_BINARY_REGEX.match(norm_path):
        return "A-CAS"

    if CLASS_C_LIVE_STATE_REGEX.match(norm_path):
        return "C"

    if CLASS_B_CONFIG_ALLOWLIST_REGEX.match(norm_path):
        return "B"

    return "E"
