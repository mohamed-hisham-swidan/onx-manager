from __future__ import annotations

from pathlib import Path
from typing import Any


class FilesystemSandbox:
    def __init__(self, plugin_dir: str, allowed_paths: list[str] | None = None) -> None:
        self._plugin_dir = Path(plugin_dir).resolve()
        self._allowed_paths = [Path(p).resolve() for p in (allowed_paths or [])]

    def resolve_path(self, path: str) -> Path:
        target = (self._plugin_dir / path).resolve()
        if not str(target).startswith(str(self._plugin_dir)):
            for allowed in self._allowed_paths:
                if str(target).startswith(str(allowed)):
                    return target
            raise PermissionError(f"Path outside sandbox: {path}")
        return target

    def read_file(self, path: str) -> bytes:
        target = self.resolve_path(path)
        if not target.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if not target.is_file():
            raise IsADirectoryError(f"Not a file: {path}")
        return target.read_bytes()

    def write_file(self, path: str, data: bytes) -> None:
        target = self.resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def delete_file(self, path: str) -> None:
        target = self.resolve_path(path)
        if not target.exists():
            raise FileNotFoundError(f"File not found: {path}")
        target.unlink()

    def list_files(self, path: str = ".") -> list[str]:
        target = self.resolve_path(path)
        if not target.is_dir():
            raise NotADirectoryError(f"Not a directory: {path}")
        return [str(p.relative_to(self._plugin_dir)) for p in target.iterdir()]

    def file_exists(self, path: str) -> bool:
        try:
            target = self.resolve_path(path)
            return target.exists()
        except PermissionError:
            return False


class NetworkSandbox:
    def __init__(
        self, allowed_hosts: list[str] | None = None, allowed_ports: list[int] | None = None
    ) -> None:
        self._allowed_hosts = set(allowed_hosts or [])
        self._allowed_ports = set(allowed_ports or [])

    def check_connection(self, host: str, port: int) -> bool:
        if self._allowed_hosts and host not in self._allowed_hosts:
            return False
        if self._allowed_ports and port not in self._allowed_ports:
            return False
        return True

    def check_url(self, url: str) -> bool:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return self.check_connection(host, port)


class Sandbox:
    def __init__(self, plugin_dir: str, permissions: dict[str, Any] | None = None) -> None:
        perms = permissions or {}
        fs_perms = perms.get("filesystem", {})
        net_perms = perms.get("network", {})

        self.filesystem = FilesystemSandbox(
            plugin_dir=plugin_dir,
            allowed_paths=fs_perms.get("paths"),
        )
        self.network = NetworkSandbox(
            allowed_hosts=net_perms.get("hosts"),
            allowed_ports=net_perms.get("ports"),
        )
