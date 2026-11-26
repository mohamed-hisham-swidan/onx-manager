"""Lockfile Format 2.1 domain model, strict parser, and deterministic serializer."""

from __future__ import annotations

import enum
import json
import re
import types
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.core.allowlist import validate_canonical_relpath
from app.core.exceptions import (
    CaseCollisionError,
    LockfileFormatError,
    LockfileInvalidError,
)
from app.modules.shared.value_objects import MinecraftVersion

_SHA256_RE = re.compile(r"^[0-9a-f]{64}\Z")
_SHA512_RE = re.compile(r"^[0-9a-f]{128}\Z")
_SHA1_RE = re.compile(r"^[0-9a-f]{40}\Z")
_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_LOADER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}\Z")
_VERSION_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}\Z")
_LEC_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}\Z")
_PAPER_BUILD_RE = re.compile(r"^[1-9][0-9]*\Z")


def _bounded_text(value: Any, limit: int = 128) -> str:
    s = str(value)
    if len(s) <= limit:
        return s
    return s[: limit - 3] + "..."


def _bounded_repr(value: Any, limit: int = 128) -> str:
    r = repr(value)
    if len(r) <= limit:
        return r
    if r.endswith("'"):
        return r[: limit - 4] + "...'"
    if r.endswith('"'):
        return r[: limit - 4] + '..."'
    return r[: limit - 3] + "..."


def _reject_lone_surrogates(s: Any, field: str) -> None:
    if not isinstance(s, str):
        return
    for c in s:
        if 0xD800 <= ord(c) <= 0xDFFF:
            raise LockfileInvalidError("String contains lone surrogate", field=field)


class EnvServer(enum.StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    UNSUPPORTED = "unsupported"


class Origin(enum.StrEnum):
    MODRINTH = "modrinth"
    CURSEFORGE = "curseforge"
    CURSEFORGE_UNCLASSIFIED = "curseforge-unclassified"
    OVERRIDE = "override"
    PAPERMC = "papermc"
    USER = "user"


@dataclass(frozen=True)
class LoaderRef:
    id: str
    version: str

    def __post_init__(self) -> None:
        if type(self.id) is not str or not _LOADER_ID_RE.match(self.id):
            raise LockfileInvalidError("Invalid loader id", field="loader.id")
        _reject_lone_surrogates(self.id, "loader.id")
        if type(self.version) is not str or not _VERSION_TOKEN_RE.match(self.version):
            raise LockfileInvalidError("Invalid loader version", field="loader.version")
        _reject_lone_surrogates(self.version, "loader.version")


@dataclass(frozen=True)
class LecKeyParts:
    loader: str
    mc: str
    version: str
    installer: str | None = None

    @property
    def loader_version(self) -> str:
        return self.version


def parse_lec_key(key: str) -> LecKeyParts:
    """Parse and strictly validate a Loader Environment Cache (LEC) key per D-5 and R-05."""
    if not isinstance(key, str) or not key:
        raise LockfileInvalidError("LEC key must be a non-empty string", field="lec.key")
    if len(key) > 256:
        raise LockfileInvalidError("LEC key exceeds maximum length of 256", field="lec.key")
    if "%" in key:
        raise LockfileInvalidError("LEC key contains forbidden character '%'", field="lec.key")

    try:
        norm = validate_canonical_relpath(key)
    except ValueError as exc:
        raise LockfileInvalidError(
            "LEC key is not a canonical relative path", field="lec.key"
        ) from exc

    segments = norm.split("/")
    loader = segments[0]
    allowed_loaders = ("paper", "purpur", "fabric", "quilt", "neoforge", "forge")
    if loader not in allowed_loaders:
        raise LockfileInvalidError(
            f"Unknown loader in LEC key: {_bounded_repr(loader)}", field="lec.key"
        )

    if loader == "fabric":
        if len(segments) != 4:
            raise LockfileInvalidError(
                "Fabric LEC key must have exactly 4 segments", field="lec.key"
            )
    elif len(segments) != 3:
        raise LockfileInvalidError(
            f"{loader} LEC key must have exactly 3 segments", field="lec.key"
        )

    for seg in segments:
        if not _LEC_SEGMENT_RE.match(seg):
            raise LockfileInvalidError("Invalid segment in LEC key", field="lec.key")

    mc_seg = segments[1]
    try:
        MinecraftVersion.parse(mc_seg)
    except ValueError as exc:
        raise LockfileInvalidError("Invalid Minecraft version in LEC key", field="lec.key") from exc

    if loader == "paper":
        build_seg = segments[2]
        if not _PAPER_BUILD_RE.match(build_seg):
            raise LockfileInvalidError(
                "Paper build must be a positive integer without leading zeros",
                field="lec.key",
            )
        return LecKeyParts(loader="paper", mc=mc_seg, version=build_seg, installer=None)

    if loader == "fabric":
        return LecKeyParts(
            loader="fabric", mc=mc_seg, version=segments[2], installer=segments[3]
        )

    return LecKeyParts(loader=loader, mc=mc_seg, version=segments[2], installer=None)


@dataclass(frozen=True)
class LecRef:
    key: str

    def __post_init__(self) -> None:
        parse_lec_key(self.key)


@dataclass(frozen=True)
class ModpackRef:
    source: str
    project_id: str
    version_id: str
    version_label: str
    index_sha256: str

    def __post_init__(self) -> None:
        if type(self.source) is not str or not _SAFE_TOKEN_RE.match(self.source):
            raise LockfileInvalidError("Invalid source", field="modpack.source")
        _reject_lone_surrogates(self.source, "modpack.source")
        if (
            type(self.project_id) is not str
            or not (1 <= len(self.project_id) <= 128)
            or any(ord(c) < 32 or ord(c) == 127 for c in self.project_id)
        ):
            raise LockfileInvalidError("Invalid project_id", field="modpack.project_id")
        _reject_lone_surrogates(self.project_id, "modpack.project_id")
        if (
            type(self.version_id) is not str
            or not (1 <= len(self.version_id) <= 128)
            or any(ord(c) < 32 or ord(c) == 127 for c in self.version_id)
        ):
            raise LockfileInvalidError("Invalid version_id", field="modpack.version_id")
        _reject_lone_surrogates(self.version_id, "modpack.version_id")
        if (
            type(self.version_label) is not str
            or not (1 <= len(self.version_label) <= 256)
            or any(ord(c) < 32 or ord(c) == 127 for c in self.version_label)
        ):
            raise LockfileInvalidError("Invalid version_label", field="modpack.version_label")
        _reject_lone_surrogates(self.version_label, "modpack.version_label")
        if type(self.index_sha256) is not str or not _SHA256_RE.match(self.index_sha256):
            raise LockfileInvalidError("Invalid index_sha256 format", field="modpack.index_sha256")


def _validate_relpath(path: str) -> str:
    """Validate canonical POSIX relative path with encoded trick defense."""
    if type(path) is not str or not path:
        raise LockfileInvalidError("Path must be a non-empty string", field="path")
    _reject_lone_surrogates(path, "path")
    try:
        norm = validate_canonical_relpath(path)
    except ValueError:
        raise LockfileInvalidError(f"Invalid path {_bounded_repr(path)}", field="path") from None
    lower = norm.lower()
    for trick in ("%2e", "%2f", "%5c", "%00"):
        if trick in lower:
            raise LockfileInvalidError(
                f"Path contains forbidden encoded sequence: {trick}", field="path"
            )
    return norm


@dataclass(frozen=True)
class LockfileFile:
    path: str
    sha256: str
    size: int
    optional: bool
    env_server: EnvServer
    origin: Origin
    sha512: str | None = None
    sha1: str | None = None
    project_id: str | None = None
    version_id: str | None = None

    def __post_init__(self) -> None:
        _validate_relpath(self.path)

        if type(self.sha256) is not str or not _SHA256_RE.match(self.sha256):
            raise LockfileInvalidError("Invalid sha256 format", field="sha256")

        if type(self.size) is not int or self.size < 0:
            raise LockfileInvalidError("Size must be a non-negative integer", field="size")

        if type(self.optional) is not bool:
            raise LockfileInvalidError("Optional must be a boolean", field="optional")

        if isinstance(self.env_server, str):
            try:
                object.__setattr__(self, "env_server", EnvServer(self.env_server))
            except ValueError:
                raise LockfileInvalidError("Invalid env_server value", field="env_server") from None
        elif not isinstance(self.env_server, EnvServer):
            raise LockfileInvalidError("Invalid env_server type", field="env_server")

        if isinstance(self.origin, str):
            try:
                object.__setattr__(self, "origin", Origin(self.origin))
            except ValueError:
                raise LockfileInvalidError("Invalid origin value", field="origin") from None
        elif not isinstance(self.origin, Origin):
            raise LockfileInvalidError("Invalid origin type", field="origin")

        if self.sha512 is not None and (
            type(self.sha512) is not str or not _SHA512_RE.match(self.sha512)
        ):
            raise LockfileInvalidError("Invalid sha512 format", field="sha512")

        if self.sha1 is not None and (
            type(self.sha1) is not str or not _SHA1_RE.match(self.sha1)
        ):
            raise LockfileInvalidError("Invalid sha1 format", field="sha1")

        if self.project_id is not None:
            if (
                type(self.project_id) is not str
                or not (1 <= len(self.project_id) <= 128)
                or any(ord(c) < 32 or ord(c) == 127 for c in self.project_id)
            ):
                raise LockfileInvalidError("Invalid project_id", field="project_id")
            _reject_lone_surrogates(self.project_id, "project_id")

        if self.version_id is not None:
            if (
                type(self.version_id) is not str
                or not (1 <= len(self.version_id) <= 128)
                or any(ord(c) < 32 or ord(c) == 127 for c in self.version_id)
            ):
                raise LockfileInvalidError("Invalid version_id", field="version_id")
            _reject_lone_surrogates(self.version_id, "version_id")


@dataclass(frozen=True)
class LockfileV21:
    format: int
    mc: str
    loader: LoaderRef
    base_overrides: Mapping[str, str]
    files: tuple[LockfileFile, ...]
    lec: LecRef | None = None
    modpack: ModpackRef | None = None

    def __post_init__(self) -> None:
        if type(self.format) is not int or self.format != 2:
            raise LockfileFormatError(
                f"Unsupported lockfile format: {self.format!r} (expected integer 2)",
                field="format",
            )

        if type(self.mc) is not str or not self.mc:
            raise LockfileInvalidError("mc must be a non-empty string", field="mc")
        if any(ord(c) < 32 or ord(c) == 127 for c in self.mc):
            raise LockfileInvalidError("mc cannot contain control characters", field="mc")
        _reject_lone_surrogates(self.mc, "mc")
        try:
            MinecraftVersion.parse(self.mc)
        except ValueError as exc:
            raise LockfileInvalidError("Invalid Minecraft version format", field="mc") from exc

        if not isinstance(self.loader, LoaderRef):
            raise LockfileInvalidError("Invalid loader", field="loader")

        if not isinstance(self.base_overrides, Mapping):
            raise LockfileInvalidError(
                "base_overrides must be an object", field="base_overrides"
            )

        validated_bo: dict[str, str] = {}
        for k, v in self.base_overrides.items():
            _validate_relpath(k)
            if type(v) is not str or not _SHA256_RE.match(v):
                raise LockfileInvalidError(
                    "Invalid sha256 in base_overrides", field="base_overrides"
                )
            validated_bo[k] = v
        object.__setattr__(self, "base_overrides", types.MappingProxyType(validated_bo))

        if not isinstance(self.files, (tuple, list)):
            raise LockfileInvalidError("files must be a list or tuple", field="files")

        for f in self.files:
            if not isinstance(f, LockfileFile):
                raise LockfileInvalidError("Invalid file entry in files", field="files")
        object.__setattr__(self, "files", tuple(self.files))

        # Check path collisions and casefold collisions
        seen_files: dict[str, str] = {}
        for f in self.files:
            cf = f.path.casefold()
            if cf in seen_files:
                orig = seen_files[cf]
                if orig == f.path:
                    raise LockfileInvalidError(
                        f"Duplicate path in files: {_bounded_repr(orig)}", field="path"
                    )
                raise CaseCollisionError(
                    f"Casefold collision between {_bounded_repr(orig)} and {_bounded_repr(f.path)}",
                    path_a=_bounded_text(orig),
                    path_b=_bounded_text(f.path),
                )
            seen_files[cf] = f.path

        seen_bo: dict[str, str] = {}
        for k in validated_bo:
            cf = k.casefold()
            if cf in seen_files:
                orig = seen_files[cf]
                if orig == k:
                    raise LockfileInvalidError(
                        f"Path exists in both files and base_overrides: {_bounded_repr(orig)}",
                        field="path",
                    )
                raise CaseCollisionError(
                    f"Casefold collision between {_bounded_repr(orig)} and {_bounded_repr(k)}",
                    path_a=_bounded_text(orig),
                    path_b=_bounded_text(k),
                )
            if cf in seen_bo:
                orig = seen_bo[cf]
                if orig == k:
                    raise LockfileInvalidError(
                        f"Duplicate path in base_overrides: {_bounded_repr(orig)}",
                        field="path",
                    )
                raise CaseCollisionError(
                    f"Casefold collision in base_overrides between "
                    f"{_bounded_repr(orig)} and {_bounded_repr(k)}",
                    path_a=_bounded_text(orig),
                    path_b=_bounded_text(k),
                )
            seen_bo[cf] = k

        # Loader/LEC consistency rule (R-07)
        if self.lec is not None:
            if not isinstance(self.lec, LecRef):
                raise LockfileInvalidError("Invalid lec reference", field="lec")
            parts = parse_lec_key(self.lec.key)
            if parts.loader != self.loader.id:
                raise LockfileInvalidError(
                    "Loader id does not match LEC key loader", field="lec.key"
                )
            if parts.mc != self.mc:
                raise LockfileInvalidError(
                    "Minecraft version does not match LEC key mc", field="lec.key"
                )
            if parts.loader == "fabric":
                if parts.loader_version != self.loader.version:
                    raise LockfileInvalidError(
                        "Fabric loader version does not match LEC key loader version",
                        field="lec.key",
                    )
            elif parts.version != self.loader.version:
                raise LockfileInvalidError(
                    "Loader version does not match LEC key version", field="lec.key"
                )

        if self.modpack is not None and not isinstance(self.modpack, ModpackRef):
            raise LockfileInvalidError("Invalid modpack reference", field="modpack")


def parse_lockfile(data: bytes) -> LockfileV21:
    """Strictly parse and validate a Lockfile Format 2.1 document from UTF-8 bytes."""
    if not isinstance(data, (bytes, bytearray)):
        raise LockfileInvalidError("Lockfile data must be bytes")
    if data.startswith(b"\xef\xbb\xbf"):
        raise LockfileInvalidError("BOM is forbidden in lockfile")

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LockfileInvalidError("Lockfile is not valid UTF-8") from exc

    def _reject_duplicate_keys_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        d: dict[str, Any] = {}
        for k, v in pairs:
            if k in d:
                raise LockfileInvalidError(
                    f"Duplicate JSON key: {_bounded_repr(k)}", field=_bounded_text(k)
                )
            d[k] = v
        return d

    def _reject_constant(c: str) -> None:
        raise LockfileInvalidError(f"Forbidden JSON constant: {_bounded_repr(c)}")

    try:
        raw = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys_hook,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise LockfileInvalidError(f"Malformed JSON: {exc.msg}") from exc

    if not isinstance(raw, dict):
        raise LockfileFormatError("Top-level JSON must be an object")

    allowed_top_keys = {"format", "mc", "loader", "lec", "modpack", "base_overrides", "files"}
    extra_keys = set(raw.keys()) - allowed_top_keys
    if extra_keys:
        k = sorted(extra_keys)[0]
        raise LockfileInvalidError(
            f"Unknown top-level key: {_bounded_repr(k)}", field=_bounded_text(k)
        )

    if "format" not in raw:
        raise LockfileFormatError("Missing required key 'format'", field="format")

    raw_format = raw["format"]
    if type(raw_format) is not int or raw_format != 2:
        raise LockfileFormatError(
            f"Unsupported lockfile format: {raw_format!r} (expected integer 2)",
            field="format",
        )

    if "base_overrides" not in raw:
        raise LockfileFormatError(
            "Missing required key 'base_overrides' (legacy Format 2 rejected)",
            field="base_overrides",
        )

    for req in ("mc", "loader", "files"):
        if req not in raw:
            raise LockfileInvalidError(f"Missing required key: {req!r}", field=req)

    raw_mc = raw["mc"]
    if type(raw_mc) is not str or not raw_mc:
        raise LockfileInvalidError("mc must be a non-empty string", field="mc")
    if any(ord(c) < 32 or ord(c) == 127 for c in raw_mc):
        raise LockfileInvalidError("mc cannot contain control characters", field="mc")
    _reject_lone_surrogates(raw_mc, "mc")

    raw_loader = raw["loader"]
    if not isinstance(raw_loader, dict):
        raise LockfileInvalidError("loader must be an object", field="loader")
    loader_extra = set(raw_loader.keys()) - {"id", "version"}
    if loader_extra:
        k = sorted(loader_extra)[0]
        raise LockfileInvalidError(
            f"Unknown key in loader: {_bounded_repr(k)}", field=_bounded_text(f"loader.{k}")
        )
    if "id" not in raw_loader or "version" not in raw_loader:
        raise LockfileInvalidError("loader requires 'id' and 'version'", field="loader")
    if type(raw_loader["id"]) is not str or type(raw_loader["version"]) is not str:
        raise LockfileInvalidError("loader 'id' and 'version' must be strings", field="loader")
    loader_ref = LoaderRef(id=raw_loader["id"], version=raw_loader["version"])

    lec_ref: LecRef | None = None
    if "lec" in raw:
        raw_lec = raw["lec"]
        if not isinstance(raw_lec, dict):
            raise LockfileInvalidError("lec must be an object", field="lec")
        lec_extra = set(raw_lec.keys()) - {"key"}
        if lec_extra:
            k = sorted(lec_extra)[0]
            raise LockfileInvalidError(
                f"Unknown key in lec: {_bounded_repr(k)}", field=_bounded_text(f"lec.{k}")
            )
        if "key" not in raw_lec:
            raise LockfileInvalidError("lec requires 'key'", field="lec.key")
        if type(raw_lec["key"]) is not str:
            raise LockfileInvalidError("lec key must be a string", field="lec.key")
        lec_ref = LecRef(key=raw_lec["key"])

    modpack_ref: ModpackRef | None = None
    if "modpack" in raw:
        raw_modpack = raw["modpack"]
        if not isinstance(raw_modpack, dict):
            raise LockfileInvalidError("modpack must be an object", field="modpack")
        modpack_keys = {"source", "project_id", "version_id", "version_label", "index_sha256"}
        modpack_extra = set(raw_modpack.keys()) - modpack_keys
        if modpack_extra:
            k = sorted(modpack_extra)[0]
            raise LockfileInvalidError(
                f"Unknown key in modpack: {_bounded_repr(k)}", field=_bounded_text(f"modpack.{k}")
            )
        for mk in modpack_keys:
            if mk not in raw_modpack:
                raise LockfileInvalidError(f"modpack requires '{mk}'", field=f"modpack.{mk}")
            if type(raw_modpack[mk]) is not str:
                raise LockfileInvalidError(
                    f"modpack field '{mk}' must be a string", field=f"modpack.{mk}"
                )
        modpack_ref = ModpackRef(
            source=raw_modpack["source"],
            project_id=raw_modpack["project_id"],
            version_id=raw_modpack["version_id"],
            version_label=raw_modpack["version_label"],
            index_sha256=raw_modpack["index_sha256"],
        )

    raw_bo = raw["base_overrides"]
    if not isinstance(raw_bo, dict):
        raise LockfileInvalidError("base_overrides must be an object", field="base_overrides")
    bo_dict: dict[str, str] = {}
    for k, v in raw_bo.items():
        if type(k) is not str or type(v) is not str:
            raise LockfileInvalidError(
                "base_overrides keys and values must be strings", field="base_overrides"
            )
        _validate_relpath(k)
        if not _SHA256_RE.match(v):
            raise LockfileInvalidError(
                "Invalid sha256 in base_overrides", field="base_overrides"
            )
        bo_dict[k] = v

    raw_files = raw["files"]
    if not isinstance(raw_files, list):
        raise LockfileInvalidError("files must be a list", field="files")

    file_required_keys = {"path", "sha256", "size", "optional", "env_server", "origin"}
    file_optional_keys = {"sha512", "sha1", "project_id", "version_id"}
    file_all_keys = file_required_keys | file_optional_keys

    file_entries: list[LockfileFile] = []
    for idx, f in enumerate(raw_files):
        if not isinstance(f, dict):
            raise LockfileInvalidError(f"files[{idx}] must be an object", field=f"files[{idx}]")
        extra_fkeys = set(f.keys()) - file_all_keys
        if extra_fkeys:
            ek = sorted(extra_fkeys)[0]
            raise LockfileInvalidError(
                f"Unknown key in file entry: {_bounded_repr(ek)}",
                field=_bounded_text(f"files[{idx}].{ek}"),
            )
        for rk in file_required_keys:
            if rk not in f:
                raise LockfileInvalidError(
                    f"Missing required file key: {rk!r}", field=f"files[{idx}].{rk}"
                )

        for ok in file_optional_keys:
            if ok in f and f[ok] is None:
                raise LockfileInvalidError(
                    f"Optional field '{ok}' cannot be null", field=f"files[{idx}].{ok}"
                )

        if type(f["path"]) is not str:
            raise LockfileInvalidError("File path must be a string", field="path")
        if type(f["sha256"]) is not str:
            raise LockfileInvalidError("File sha256 must be a string", field="sha256")
        if type(f["size"]) is not int or f["size"] < 0:
            raise LockfileInvalidError("File size must be a non-negative integer", field="size")
        if type(f["optional"]) is not bool:
            raise LockfileInvalidError("File optional must be a boolean", field="optional")
        if type(f["env_server"]) is not str:
            raise LockfileInvalidError("File env_server must be a string", field="env_server")
        if type(f["origin"]) is not str:
            raise LockfileInvalidError("File origin must be a string", field="origin")
        if "sha512" in f and type(f["sha512"]) is not str:
            raise LockfileInvalidError("File sha512 must be a string", field="sha512")
        if "sha1" in f and type(f["sha1"]) is not str:
            raise LockfileInvalidError("File sha1 must be a string", field="sha1")
        if "project_id" in f and type(f["project_id"]) is not str:
            raise LockfileInvalidError("File project_id must be a string", field="project_id")
        if "version_id" in f and type(f["version_id"]) is not str:
            raise LockfileInvalidError("File version_id must be a string", field="version_id")

        file_entries.append(
            LockfileFile(
                path=f["path"],
                sha256=f["sha256"],
                size=f["size"],
                optional=f["optional"],
                env_server=f["env_server"],
                origin=f["origin"],
                sha512=f.get("sha512"),
                sha1=f.get("sha1"),
                project_id=f.get("project_id"),
                version_id=f.get("version_id"),
            )
        )

    return LockfileV21(
        format=raw_format,
        mc=raw_mc,
        loader=loader_ref,
        base_overrides=bo_dict,
        files=tuple(file_entries),
        lec=lec_ref,
        modpack=modpack_ref,
    )


def dump_lockfile(lockfile: LockfileV21) -> bytes:
    """Deterministically serialize a LockfileV21 object to UTF-8 bytes with trailing newline."""
    if not isinstance(lockfile, LockfileV21):
        raise LockfileInvalidError("dump_lockfile requires a LockfileV21 instance")

    doc: dict[str, Any] = {
        "format": lockfile.format,
        "mc": lockfile.mc,
        "loader": {
            "id": lockfile.loader.id,
            "version": lockfile.loader.version,
        },
    }

    if lockfile.lec is not None:
        doc["lec"] = {"key": lockfile.lec.key}

    if lockfile.modpack is not None:
        doc["modpack"] = {
            "source": lockfile.modpack.source,
            "project_id": lockfile.modpack.project_id,
            "version_id": lockfile.modpack.version_id,
            "version_label": lockfile.modpack.version_label,
            "index_sha256": lockfile.modpack.index_sha256,
        }

    # Sort base_overrides keys deterministically
    sorted_bo = {k: lockfile.base_overrides[k] for k in sorted(lockfile.base_overrides.keys())}
    doc["base_overrides"] = sorted_bo

    files_list: list[dict[str, Any]] = []
    for f in lockfile.files:
        f_doc: dict[str, Any] = {
            "path": f.path,
            "sha256": f.sha256,
        }
        if f.sha512 is not None:
            f_doc["sha512"] = f.sha512
        if f.sha1 is not None:
            f_doc["sha1"] = f.sha1
        f_doc["size"] = f.size
        f_doc["optional"] = f.optional
        f_doc["env_server"] = str(
            f.env_server.value if hasattr(f.env_server, "value") else f.env_server
        )
        f_doc["origin"] = str(f.origin.value if hasattr(f.origin, "value") else f.origin)
        if f.project_id is not None:
            f_doc["project_id"] = f.project_id
        if f.version_id is not None:
            f_doc["version_id"] = f.version_id
        files_list.append(f_doc)

    doc["files"] = files_list

    payload = json.dumps(doc, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    return payload.encode("utf-8")
