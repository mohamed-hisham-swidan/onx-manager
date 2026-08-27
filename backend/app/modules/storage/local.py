from __future__ import annotations

import hashlib
import shutil
from datetime import UTC, datetime
from pathlib import Path

from app.modules.storage.base import StorageBackend, StorageFileInfo, StorageResult


class LocalStorage(StorageBackend):
    def __init__(self, base_path: str) -> None:
        self._base_path = Path(base_path)
        self._base_path.mkdir(parents=True, exist_ok=True)

    @property
    def base_path(self) -> Path:
        return self._base_path

    async def write(self, path: str, data: bytes) -> StorageResult:
        full_path = self._resolve(path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(data)
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
        data = dst_path.read_bytes()
        checksum = hashlib.sha256(data).hexdigest()
        return StorageResult(
            path=str(dst_path),
            size_bytes=len(data),
            checksum=checksum,
        )

    async def _file_info(self, full_path: Path) -> StorageFileInfo | None:
        if not full_path.exists():
            return None
        stat = full_path.stat()
        return StorageFileInfo(
            path=str(full_path.relative_to(self._base_path)),
            size_bytes=stat.st_size,
            checksum="",
            modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
            is_directory=full_path.is_dir(),
        )

    def _resolve(self, path: str) -> Path:
        resolved = (self._base_path / path).resolve()
        resolved_str = str(resolved)
        base_str = str(self._base_path.resolve())
        if not resolved_str.startswith(base_str):
            raise ValueError(f"Path traversal detected: {path}")
        return resolved
