from __future__ import annotations

from pathlib import Path


class Storage:
    def __init__(self, plugin_dir: str) -> None:
        self._plugin_dir = Path(plugin_dir).resolve()
        self._data_dir = self._plugin_dir / "data"
        self._data_dir.mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str) -> Path:
        target = (self._data_dir / path).resolve()
        if not str(target).startswith(str(self._data_dir)):
            raise PermissionError(f"Access denied: {path}")
        return target

    def read(self, path: str) -> bytes:
        target = self._resolve(path)
        if not target.exists():
            raise FileNotFoundError(f"File not found: {path}")
        return target.read_bytes()

    def write(self, path: str, data: bytes) -> None:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def delete(self, path: str) -> None:
        target = self._resolve(path)
        if target.exists():
            target.unlink()

    def exists(self, path: str) -> bool:
        try:
            return self._resolve(path).exists()
        except PermissionError:
            return False

    def list(self, path: str = "") -> list[str]:
        target = self._resolve(path)
        if not target.is_dir():
            return []
        return [str(p.relative_to(self._data_dir)) for p in target.iterdir()]

    def read_text(self, path: str) -> str:
        return self.read(path).decode("utf-8")

    def write_text(self, path: str, text: str) -> None:
        self.write(path, text.encode("utf-8"))
