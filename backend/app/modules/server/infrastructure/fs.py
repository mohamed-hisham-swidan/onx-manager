from __future__ import annotations

import contextlib
import logging
import os
import shutil
import stat
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.fs_utils import assert_inside_root

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
    def delete_dir(self, path: str, *, root: str | None = None) -> None: ...

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
            if p.exists():
                raise PermissionError(f"File could not be completely removed: {path}")

    @staticmethod
    def _try_docker_root_cleanup(p: Path) -> None:
        docker_bin = shutil.which("docker")
        if not docker_bin:
            return
        candidate_images = (
            "busybox:latest",
            "alpine:latest",
            "python:3.12-alpine",
            "eclipse-temurin:25-jre",
            "eclipse-temurin:21-jre-jammy",
            "eclipse-temurin:17-jre",
        )
        chosen_image: str | None = None
        for img in candidate_images:
            with contextlib.suppress(Exception):
                res = subprocess.run(
                    [docker_bin, "image", "inspect", img],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                    check=False,
                )
                if res.returncode == 0:
                    chosen_image = img
                    break
        if not chosen_image:
            return
        with contextlib.suppress(Exception):
            subprocess.run(
                [
                    docker_bin,
                    "run",
                    "--rm",
                    "-v",
                    f"{p.resolve()}:/target",
                    chosen_image,
                    "sh",
                    "-c",
                    "rm -rf /target/* /target/.[!.]* /target/..?* 2>/dev/null || true",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
            )
            shutil.rmtree(p, ignore_errors=True)

    def delete_dir(self, path: str, *, root: str | None = None) -> None:
        p = Path(path)
        if not p.is_dir():
            return
        if root is not None:
            assert_inside_root(p, root)
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

        if p.exists() and os.name == "posix":
            self._try_docker_root_cleanup(p)

        if p.exists():
            raise PermissionError(f"Directory could not be completely removed: {path}")

    def copy(self, source: str, dest: str) -> None:
        shutil.copy2(source, dest)

    def copy_dir(self, source: str, dest: str) -> None:
        shutil.copytree(
            source,
            dest,
            symlinks=False,
            ignore_dangling_symlinks=True,
            dirs_exist_ok=True,
            ignore=lambda dir_path, names: [
                n for n in names if os.path.islink(os.path.join(dir_path, n))
            ],
        )

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
        orig_mode: int | None = None
        if dest.exists():
            with contextlib.suppress(OSError):
                orig_mode = stat.S_IMODE(dest.stat().st_mode)
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
            if orig_mode is not None:
                with contextlib.suppress(OSError):
                    os.chmod(tmp_path, orig_mode)
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
