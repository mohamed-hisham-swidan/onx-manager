from __future__ import annotations

import json
import os
from typing import Any


class Config:
    def __init__(self, plugin_dir: str) -> None:
        self._plugin_dir = plugin_dir
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        config_path = os.path.join(self._plugin_dir, "config.json")
        if os.path.exists(config_path):
            with open(config_path) as f:
                self._data = json.load(f)

    def get(self, key: str, default: Any = None) -> Any:
        keys = key.split(".")
        value = self._data
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
        return value if value is not None else default

    def set(self, key: str, value: Any) -> None:
        keys = key.split(".")
        target = self._data
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]
        target[keys[-1]] = value

    def save(self) -> None:
        config_path = os.path.join(self._plugin_dir, "config.json")
        with open(config_path, "w") as f:
            json.dump(self._data, f, indent=2)

    @property
    def all(self) -> dict[str, Any]:
        return dict(self._data)
