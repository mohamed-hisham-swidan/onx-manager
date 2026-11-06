from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import tempfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

from app.modules.storage.base import StorageBackend, StorageFileInfo, StorageResult


class LocalStorage(StorageBackend):
    def __init__(self, base_path: str) -> None:
        self._base_path = Path(base_path).resolve()
        self._base_path.mkdir(parents=True, exist_ok=True)

    @property
    def base_path(self) -> Path:
        return self._base_path

    async def write(self, path: str, data: bytes) -> StorageResult:
        full_path = self._resolve(path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{full_path.name}.",
            suffix=".tmp",
            dir=full_path.parent,
        )
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, full_path)
        except Exception:
            if os.path.exists(tmp_path):
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)
            raise
        checksum = hashlib.sha256(data).hexdigest()
        return StorageResult(
            path=str(full_path),
            size_bytes=len(data),
            checksum=checksum,
        )

    async def read(self, path: str) -> bytes:
        full_path = self._resolve(path)
        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {full_path}")
        return full_path.read_bytes()

    async def delete(self, path: str) -> bool:
        full_path = self._resolve(path)
        if not full_path.exists():
            return False
        if full_path.is_dir():
            shutil.rmtree(full_path)
        else:
            full_path.unlink()
        return True

    async def exists(self, path: str) -> bool:
        return self._resolve(path).exists()

    async def list_files(self, prefix: str) -> list[StorageFileInfo]:
        full_path = self._resolve(prefix)
        if not full_path.exists():
            return []

        files: list[StorageFileInfo] = []
        if full_path.is_file():
            info = await self._file_info(full_path)
            if info:
                files.append(info)
        else:
            for p in full_path.rglob("*"):
                if p.is_file():
                    info = await self._file_info(p)
                    if info:
                        files.append(info)
        return files

    async def info(self, path: str) -> StorageFileInfo | None:
        full_path = self._resolve(path)
        if not full_path.exists():
            return None
        return await self._file_info(full_path)

    async def copy(self, source: str, destination: str) -> StorageResult:
        src_path = self._resolve(source)
        dst_path = self._resolve(destination)
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dst_path)
        hasher = hashlib.sha256()
        total_size = 0
        with open(dst_path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                hasher.update(chunk)
                total_size += len(chunk)
        return StorageResult(
            path=str(dst_path),
            size_bytes=total_size,
            checksum=hasher.hexdigest(),
        )

    async def stream_read(self, path: str, chunk_size: int = 65536) -> AsyncIterator[bytes]:
        full_path = self._resolve(path)
        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {full_path}")
        with open(full_path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    async def stream_write(self, path: str, chunks: AsyncIterator[bytes]) -> StorageResult:
        full_path = self._resolve(path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{full_path.name}.",
            suffix=".tmp",
            dir=full_path.parent,
        )
        hasher = hashlib.sha256()
        total_size = 0
        try:
            with os.fdopen(fd, "wb") as f:
                async for chunk in chunks:
                    f.write(chunk)
                    hasher.update(chunk)
                    total_size += len(chunk)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, full_path)
        except Exception:
            if os.path.exists(tmp_path):
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)
            raise
        return StorageResult(
            path=str(full_path),
            size_bytes=total_size,
            checksum=hasher.hexdigest(),
        )

    async def _file_info(self, full_path: Path) -> StorageFileInfo | None:
        if not full_path.exists():
            return None
        stat = full_path.stat()
        rel_path = full_path.resolve().relative_to(self._base_path)
        return StorageFileInfo(
            path=rel_path.as_posix(),
            size_bytes=stat.st_size,
            checksum="",
            modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
            is_directory=full_path.is_dir(),
        )

    def _resolve(self, path: str) -> Path:
        resolved = (self._base_path / path).resolve()
        try:
            is_contained = resolved.is_relative_to(self._base_path)
        except AttributeError:
            try:
                resolved.relative_to(self._base_path)
                is_contained = True
            except ValueError:
                is_contained = False
        if not is_contained:
            raise ValueError(f"Path traversal detected: {path}")
        return resolved
