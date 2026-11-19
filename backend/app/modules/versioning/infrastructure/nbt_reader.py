"""Pure-Python gzipped big-endian NBT reader for ``level.dat`` verification (P5.5).

Uses only the Python standard library (``gzip``, ``io``, ``os``, ``struct``) with
strict bounds on uncompressed size, nesting depth, and collection lengths so
corrupt or hostile ``level.dat`` payloads fail closed with :class:`NbtParseError`.
"""

from __future__ import annotations

import gzip
import io
import os
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.exceptions import ValidationError

MAX_NBT_UNCOMPRESSED_BYTES = 16 * 1024 * 1024
MAX_NBT_DEPTH = 64
MAX_COLLECTION_LENGTH = 1_000_000

TAG_END = 0
TAG_BYTE = 1
TAG_SHORT = 2
TAG_INT = 3
TAG_LONG = 4
TAG_FLOAT = 5
TAG_DOUBLE = 6
TAG_BYTE_ARRAY = 7
TAG_STRING = 8
TAG_LIST = 9
TAG_COMPOUND = 10
TAG_INT_ARRAY = 11
TAG_LONG_ARRAY = 12

_GZIP_MAGIC = b"\x1f\x8b"
_READ_CHUNK_BYTES = 64 * 1024

_KNOWN_MC_DATA_VERSIONS: dict[str, int] = {
    "1.17.1": 2730,
    "1.18.2": 2975,
    "1.19.2": 3120,
    "1.19.4": 3337,
    "1.20.1": 3465,
    "1.20.2": 3578,
    "1.20.4": 3700,
    "1.20.6": 3839,
    "1.21": 3953,
    "1.21.1": 3955,
    "1.21.3": 4080,
    "1.21.4": 4189,
    "26.1": 4500,
    "26.3": 4600,
}


class NbtParseError(ValidationError):
    """Raised when an NBT payload or ``level.dat`` fails validation."""

    code = "NBT_PARSE_ERROR"

    def __init__(
        self,
        message: str = "Invalid NBT payload",
        *,
        field: str = "level_dat",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, field=field, details=details)
        self.code = "NBT_PARSE_ERROR"


@dataclass(frozen=True)
class LevelDatVersionInfo:
    """Version metadata extracted from a Minecraft ``level.dat`` compound."""

    data_version: int | None
    version_id: str | None
    version_name: str | None
    level_name: str | None


def known_data_version_for_mc(mc_version: str) -> int | None:
    """Return the known minimum ``DataVersion`` for *mc_version*, or ``None``."""
    if not isinstance(mc_version, str):
        return None
    return _KNOWN_MC_DATA_VERSIONS.get(mc_version.strip())


def _decompress_bounded(raw_bytes: bytes) -> bytes:
    if len(raw_bytes) > MAX_NBT_UNCOMPRESSED_BYTES and not raw_bytes.startswith(_GZIP_MAGIC):
        raise NbtParseError(
            f"NBT payload exceeds maximum size of {MAX_NBT_UNCOMPRESSED_BYTES} bytes"
        )
    if not raw_bytes.startswith(_GZIP_MAGIC):
        return raw_bytes

    chunks: list[bytes] = []
    total = 0
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(raw_bytes), mode="rb") as gz:
            while True:
                chunk = gz.read(_READ_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_NBT_UNCOMPRESSED_BYTES:
                    raise NbtParseError(
                        "Decompressed NBT payload exceeds maximum size of "
                        f"{MAX_NBT_UNCOMPRESSED_BYTES} bytes"
                    )
                chunks.append(chunk)
    except NbtParseError:
        raise
    except (gzip.BadGzipFile, EOFError, OSError, zlib.error) as exc:
        raise NbtParseError(f"Failed to decompress gzipped NBT payload: {exc}") from exc
    return b"".join(chunks)


class _NbtReader:
    """Bounded big-endian binary NBT reader."""

    def __init__(self, data: bytes) -> None:
        self._buf = memoryview(data)
        self._pos = 0
        self._len = len(data)

    def _read_exact(self, n: int) -> memoryview:
        if n < 0 or self._pos + n > self._len:
            raise NbtParseError(
                f"Unexpected end of NBT stream at offset {self._pos} (needed {n} bytes)"
            )
        view = self._buf[self._pos : self._pos + n]
        self._pos += n
        return view

    def _unpack(self, fmt: str) -> Any:
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self._read_exact(size))[0]

    def _read_string(self) -> str:
        length = self._unpack(">H")
        raw = bytes(self._read_exact(length))
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise NbtParseError(f"Invalid UTF-8 in NBT string: {exc}") from exc

    def _check_collection_len(self, count: int, kind: str) -> int:
        if count < 0 or count > MAX_COLLECTION_LENGTH:
            raise NbtParseError(
                f"Invalid NBT {kind} length {count} (limit {MAX_COLLECTION_LENGTH})"
            )
        return count

    def read_payload(self, tag_id: int, depth: int) -> Any:
        if tag_id == TAG_BYTE:
            return self._unpack(">b")
        if tag_id == TAG_SHORT:
            return self._unpack(">h")
        if tag_id == TAG_INT:
            return self._unpack(">i")
        if tag_id == TAG_LONG:
            return self._unpack(">q")
        if tag_id == TAG_FLOAT:
            return self._unpack(">f")
        if tag_id == TAG_DOUBLE:
            return self._unpack(">d")
        if tag_id == TAG_BYTE_ARRAY:
            count = self._check_collection_len(self._unpack(">i"), "TAG_Byte_Array")
            return bytes(self._read_exact(count))
        if tag_id == TAG_STRING:
            return self._read_string()
        if tag_id == TAG_LIST:
            if depth >= MAX_NBT_DEPTH:
                raise NbtParseError(f"NBT nesting exceeded MAX_NBT_DEPTH={MAX_NBT_DEPTH}")
            elem_tag = self._unpack(">B")
            if elem_tag > TAG_LONG_ARRAY:
                raise NbtParseError(f"Unknown NBT list element tag id: {elem_tag}")
            count = self._check_collection_len(self._unpack(">i"), "TAG_List")
            if elem_tag == TAG_END and count > 0:
                raise NbtParseError("Non-empty TAG_List cannot have TAG_End elements")
            return [self.read_payload(elem_tag, depth + 1) for _ in range(count)]
        if tag_id == TAG_COMPOUND:
            if depth >= MAX_NBT_DEPTH:
                raise NbtParseError(f"NBT nesting exceeded MAX_NBT_DEPTH={MAX_NBT_DEPTH}")
            result: dict[str, Any] = {}
            while True:
                child_tag = self._unpack(">B")
                if child_tag == TAG_END:
                    break
                if child_tag > TAG_LONG_ARRAY:
                    raise NbtParseError(f"Unknown NBT tag id: {child_tag}")
                name = self._read_string()
                result[name] = self.read_payload(child_tag, depth + 1)
            return result
        if tag_id == TAG_INT_ARRAY:
            count = self._check_collection_len(self._unpack(">i"), "TAG_Int_Array")
            raw = self._read_exact(count * 4)
            return list(struct.unpack(f">{count}i", raw)) if count else []
        if tag_id == TAG_LONG_ARRAY:
            count = self._check_collection_len(self._unpack(">i"), "TAG_Long_Array")
            raw = self._read_exact(count * 8)
            return list(struct.unpack(f">{count}q", raw)) if count else []
        raise NbtParseError(f"Unsupported NBT tag id: {tag_id}")

    def read_root_compound(self) -> dict[str, Any]:
        if self._len == 0:
            raise NbtParseError("Empty NBT payload")
        root_tag = self._unpack(">B")
        if root_tag != TAG_COMPOUND:
            raise NbtParseError(
                f"Expected root TAG_Compound (10), got tag id {root_tag}"
            )
        _root_name = self._read_string()
        payload = self.read_payload(TAG_COMPOUND, depth=0)
        if not isinstance(payload, dict):
            raise NbtParseError("Root NBT tag did not produce a compound dict")
        return payload


def parse_nbt_bytes(raw_bytes: bytes) -> dict[str, Any]:
    """Parse gzipped or uncompressed big-endian NBT bytes into a root dict."""
    if not isinstance(raw_bytes, (bytes, bytearray)):
        raise NbtParseError("NBT payload must be bytes")
    data = _decompress_bounded(bytes(raw_bytes))
    return _NbtReader(data).read_root_compound()


def read_level_dat_version(level_dat_path: str | Path) -> LevelDatVersionInfo:
    """Read ``level.dat`` and extract Minecraft version and ``DataVersion``."""
    path = Path(level_dat_path)
    try:
        st = os.stat(path)
    except OSError as exc:
        raise NbtParseError(f"Cannot access level.dat at '{path}': {exc}") from exc
    if st.st_size > MAX_NBT_UNCOMPRESSED_BYTES:
        raise NbtParseError(
            f"level.dat at '{path}' exceeds maximum file size of "
            f"{MAX_NBT_UNCOMPRESSED_BYTES} bytes"
        )
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise NbtParseError(f"Cannot read level.dat at '{path}': {exc}") from exc

    root = parse_nbt_bytes(raw)
    data_compound = root.get("Data")
    if not isinstance(data_compound, dict):
        data_compound = root

    raw_dv = data_compound.get("DataVersion")
    data_version = (
        raw_dv
        if isinstance(raw_dv, int) and not isinstance(raw_dv, bool)
        else None
    )

    version_id: str | None = None
    version_name: str | None = None
    version_compound = data_compound.get("Version")
    if isinstance(version_compound, dict):
        raw_name = version_compound.get("Name")
        if isinstance(raw_name, str) and raw_name:
            version_name = raw_name
        raw_id = version_compound.get("Id")
        if isinstance(raw_id, str) and raw_id:
            version_id = raw_id
        elif isinstance(raw_id, int) and not isinstance(raw_id, bool):
            version_id = str(raw_id)
        elif version_name is not None:
            version_id = version_name

    raw_level_name = data_compound.get("LevelName")
    level_name = raw_level_name if isinstance(raw_level_name, str) else None

    return LevelDatVersionInfo(
        data_version=data_version,
        version_id=version_id,
        version_name=version_name,
        level_name=level_name,
    )


def verify_level_dat_target(
    level_dat_path: str | Path,
    *,
    expected_min_data_version: int | None = None,
    target_mc: str | None = None,
) -> LevelDatVersionInfo:
    """Verify ``level.dat`` matches the expected target DataVersion or MC version."""
    info = read_level_dat_version(level_dat_path)

    if (
        expected_min_data_version is not None
        and info.data_version is not None
        and info.data_version >= expected_min_data_version
    ):
        return info

    if target_mc is not None and (
        info.version_id == target_mc or info.version_name == target_mc
    ) and (
        expected_min_data_version is None
        or info.data_version is None
        or info.data_version >= expected_min_data_version
    ):
        return info

    if (
        expected_min_data_version is None
        and target_mc is None
        and (info.data_version is not None or info.version_id is not None)
    ):
        return info

    raise NbtParseError(
        "level.dat version mismatch: "
        f"actual DataVersion={info.data_version}, Version.Id={info.version_id!r}, "
        f"expected DataVersion>={expected_min_data_version} or Version.Id=={target_mc!r}",
        details={
            "actual_data_version": info.data_version,
            "actual_version_id": info.version_id,
            "actual_version_name": info.version_name,
            "expected_min_data_version": expected_min_data_version,
            "target_mc": target_mc,
        },
    )


__all__ = [
    "MAX_COLLECTION_LENGTH",
    "MAX_NBT_DEPTH",
    "MAX_NBT_UNCOMPRESSED_BYTES",
    "LevelDatVersionInfo",
    "NbtParseError",
    "known_data_version_for_mc",
    "parse_nbt_bytes",
    "read_level_dat_version",
    "verify_level_dat_target",
]
