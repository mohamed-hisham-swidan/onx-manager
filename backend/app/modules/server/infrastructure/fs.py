from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path


class FileSystem(ABC):
    @abstractmethod
    def ensure_dir(self, path: str) -> None: ...

    @abstractmethod
    def write_text(self, path: str, content: str) -> None: ...

    @abstractmethod
    def read_text(self, path: str) -> str: ...

    @abstractmethod
    def exists(self, path: str) -> bool: ...

    @abstractmethod
    def list_dir(self, path: str) -> list[Path]: ...

    @abstractmethod
    def size(self, path: str) -> int: ...

    @abstractmethod
    def delete(self, path: str) -> None: ...

    @abstractmethod
    def delete_dir(self, path: str) -> None: ...

    @abstractmethod
    def copy(self, source: str, dest: str) -> None: ...

    @abstractmethod
    def copy_dir(self, source: str, dest: str) -> None: ...

    @abstractmethod
    def chmod(self, path: str, mode: int) -> None: ...

    @abstractmethod
    def is_dir(self, path: str) -> bool: ...

    @abstractmethod
    def read_binary(self, path: str) -> bytes: ...

    @abstractmethod
    def write_binary(self, path: str, content: bytes) -> None: ...

    @abstractmethod
    def write_binary_atomic(self, path: str, content: bytes) -> None: ...

    @abstractmethod
    def rename(self, source: str, dest: str) -> None: ...

    @abstractmethod
    def is_file(self, path: str) -> bool: ...

    @abstractmethod
    def walk(self, path: str) -> list[str]: ...


class LocalFileSystem(FileSystem):
    def ensure_dir(self, path: str) -> None:
        Path(path).mkdir(parents=True, exist_ok=True)

    def write_text(self, path: str, content: str) -> None:
        Path(path).write_text(content)

    def read_text(self, path: str) -> str:
        return Path(path).read_text(errors="replace")

    def exists(self, path: str) -> bool:
        return Path(path).exists()

    def list_dir(self, path: str) -> list[Path]:
        p = Path(path)
        if not p.is_dir():
            return []
        return sorted(p.iterdir())

    def size(self, path: str) -> int:
        return Path(path).stat().st_size

    def delete(self, path: str) -> None:
        p = Path(path)
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()

    def delete_dir(self, path: str) -> None:
        p = Path(path)
        if p.is_dir():
            shutil.rmtree(p)

    def copy(self, source: str, dest: str) -> None:
        shutil.copy2(source, dest)

    def copy_dir(self, source: str, dest: str) -> None:
        shutil.copytree(source, dest, symlinks=False, dirs_exist_ok=True)

    def rename(self, source: str, dest: str) -> None:
        os.replace(source, dest)

    def chmod(self, path: str, mode: int) -> None:
        os.chmod(path, mode)

    def is_dir(self, path: str) -> bool:
        return Path(path).is_dir()

    def read_binary(self, path: str) -> bytes:
        return Path(path).read_bytes()

    def write_binary(self, path: str, content: bytes) -> None:
        Path(path).write_bytes(content)

    def write_binary_atomic(self, path: str, content: bytes) -> None:
        dest = Path(path)
        parent = dest.parent
        self.ensure_dir(str(parent))
        fd, tmp_path = tempfile.mkstemp(dir=str(parent), suffix=".tmp")
        try:
            os.write(fd, content)
            os.close(fd)
            os.replace(tmp_path, str(dest))
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise

    def is_file(self, path: str) -> bool:
        return Path(path).is_file()

    def walk(self, path: str) -> list[str]:
        return [str(p) for p in Path(path).rglob("*") if p.is_file()]


local_fs = LocalFileSystem()
