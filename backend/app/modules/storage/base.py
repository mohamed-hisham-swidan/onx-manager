from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class StorageFileInfo:
    path: str
    size_bytes: int
    checksum: str
    modified_at: datetime
    is_directory: bool = False


@dataclass(frozen=True)
class StorageResult:
    path: str
    size_bytes: int
    checksum: str
    success: bool = True
    error: str | None = None


class StorageBackend(ABC):
    @abstractmethod
    async def write(self, path: str, data: bytes) -> StorageResult: ...

    @abstractmethod
    async def read(self, path: str) -> bytes: ...

    @abstractmethod
    async def delete(self, path: str) -> bool: ...

    @abstractmethod
    async def exists(self, path: str) -> bool: ...

    @abstractmethod
    async def list_files(self, prefix: str) -> list[StorageFileInfo]: ...

    @abstractmethod
    async def info(self, path: str) -> StorageFileInfo | None: ...

    @abstractmethod
    async def copy(self, source: str, destination: str) -> StorageResult: ...

    async def stream_read(self, path: str, chunk_size: int = 65536) -> AsyncIterator[bytes]:
        data = await self.read(path)
        view = memoryview(data)
        for i in range(0, len(view), chunk_size):
            yield bytes(view[i : i + chunk_size])

    async def stream_write(self, path: str, chunks: AsyncIterator[bytes]) -> StorageResult:
        parts: list[bytes] = []
        async for chunk in chunks:
            parts.append(chunk)
        return await self.write(path, b"".join(parts))
