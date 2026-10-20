from __future__ import annotations

import contextlib
import logging
import os
import shutil
import stat
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger(__name__)


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
    def write_text_atomic(self, path: str, content: str, encoding: str = "utf-8") -> None: ...

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

    @staticmethod
    def _force_rm_error_handler(func, path, _exc):
        try:
            if os.path.exists(path):
                os.chmod(path, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
                func(path)
        except Exception:
            pass

    def delete(self, path: str) -> None:
        p = Path(path)
        if p.is_dir():
            self.delete_dir(path)
        elif p.exists():
            try:
                p.unlink()
            except PermissionError:
                try:
                    os.chmod(p, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
                    p.unlink()
                except Exception:
                    pass

    def delete_dir(self, path: str) -> None:
        p = Path(path)
        if not p.is_dir():
            return
        shutil.rmtree(p, onexc=self._force_rm_error_handler)

        if p.exists():
            for root, dirs, files in os.walk(p, topdown=False):
                for fname in files:
                    fpath = os.path.join(root, fname)
                    try:
                        os.chmod(fpath, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
                        os.unlink(fpath)
                    except Exception:
                        pass
                for dname in dirs:
                    dpath = os.path.join(root, dname)
                    try:
                        os.chmod(dpath, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
                        os.rmdir(dpath)
                    except Exception:
                        pass
            try:
                os.chmod(p, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
                os.rmdir(p)
            except Exception:
                pass

        if p.exists():
            raise PermissionError(f"Directory could not be completely removed: {path}")

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

    def write_text_atomic(self, path: str, content: str, encoding: str = "utf-8") -> None:
        self.write_binary_atomic(path, content.encode(encoding))

    def write_binary_atomic(self, path: str, content: bytes) -> None:
        dest = Path(path)
        parent = dest.parent
        self.ensure_dir(str(parent))
        fd, tmp_path = tempfile.mkstemp(dir=str(parent), suffix=".tmp")
        replaced = False
        try:
            try:
                view = memoryview(content)
                while view:
                    try:
                        written = os.write(fd, view)
                    except InterruptedError:
                        continue
                    if written <= 0:
                        raise OSError("short write")
                    view = view[written:]
                os.fsync(fd)
            finally:
                try:
                    os.close(fd)
                except OSError:
                    logger.warning(
                        "Failed to close temporary file descriptor for %s",
                        path,
                        exc_info=True,
                    )
            os.replace(tmp_path, str(dest))
            replaced = True
            self._fsync_parent_dir(parent)
        except BaseException:
            if not replaced:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)
            raise

    def _fsync_parent_dir(self, parent: Path) -> None:
        if os.name != "posix":
            return
        dir_fd = os.open(str(parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    def is_file(self, path: str) -> bool:
        return Path(path).is_file()

    def walk(self, path: str) -> list[str]:
        return [str(p) for p in Path(path).rglob("*") if p.is_file()]


local_fs = LocalFileSystem()
