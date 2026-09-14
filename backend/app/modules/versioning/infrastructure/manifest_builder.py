from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from app.modules.versioning.domain.value_objects import CommitManifest, ModReference


class ManifestBuilder:
    """Builds an immutable CommitManifest from a server's on-disk configuration and mods."""

    KNOWN_CONFIG_FILES: frozenset[str] = frozenset(
        {
            "server.properties",
            "bukkit.yml",
            "spigot.yml",
            "paper-global.yml",
            "paper-world-defaults.yml",
            "purpur.yml",
            "eula.txt",
        }
    )

    CONFIG_EXTENSIONS: frozenset[str] = frozenset(
        {".yml", ".yaml", ".json", ".toml", ".properties", ".cfg", ".conf", ".txt", ".ini"}
    )

    MAX_CONFIG_FILE_SIZE: int = 10 * 1024 * 1024  # 10MB safety cap per config file

    @classmethod
    def calculate_file_hash(cls, file_path: str | Path) -> str:
        """Computes SHA-256 hex digest of a file in 64KB chunks."""
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()

    @classmethod
    def build_manifest(
        cls,
        server_dir: str | Path,
        server_type: str = "vanilla",
        minecraft_version: str = "1.21.1",
        env_vars: dict[str, str] | None = None,
        java_args: str = "",
    ) -> CommitManifest:
        """Scans server_dir and compiles a CommitManifest capturing non-world
        configuration and addons.
        """
        s_path = Path(server_dir).resolve()
        configs: dict[str, str] = {}
        mods: list[dict[str, Any]] = []

        st = str(server_type.value if hasattr(server_type, "value") else server_type)
        mv = str(minecraft_version)
        if not s_path.exists():
            return CommitManifest(
                server_type=st,
                minecraft_version=mv,
                configs={},
                mods=[],
                env_vars=env_vars or {},
                java_args=java_args,
            )

        # 1. Capture root known config files
        for filename in cls.KNOWN_CONFIG_FILES:
            cfg_file = s_path / filename
            if cfg_file.is_file():
                try:
                    if cfg_file.stat().st_size <= cls.MAX_CONFIG_FILE_SIZE:
                        configs[filename] = cfg_file.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    pass

        # 2. Capture config/ directory recursively
        config_dir = s_path / "config"
        if config_dir.is_dir():
            for root, _, files in os.walk(config_dir):
                for f in files:
                    full_p = Path(root) / f
                    if full_p.suffix.lower() in cls.CONFIG_EXTENSIONS:
                        try:
                            if full_p.stat().st_size <= cls.MAX_CONFIG_FILE_SIZE:
                                rel_path = full_p.relative_to(s_path).as_posix()
                                configs[rel_path] = full_p.read_text(
                                    encoding="utf-8", errors="replace"
                                )
                        except Exception:
                            pass

        # 3. Capture mods/ and plugins/ addon jars
        addon_dirs = ["mods", "plugins"]
        for ad in addon_dirs:
            p_dir = s_path / ad
            if p_dir.is_dir():
                for entry in p_dir.iterdir():
                    if entry.is_file() and (
                        entry.name.endswith(".jar") or entry.name.endswith(".jar.disabled")
                    ):
                        try:
                            f_hash = cls.calculate_file_hash(entry)
                            ref = ModReference(
                                filename=f"{ad}/{entry.name}",
                                sha256=f_hash,
                            )
                            mods.append(
                                {
                                    "filename": ref.filename,
                                    "sha256": ref.sha256,
                                    "source": "custom",
                                }
                            )
                        except Exception:
                            pass

        # Sort mods and configs deterministically for canonical hashing
        mods.sort(key=lambda m: m["filename"])

        return CommitManifest(
            server_type=st,
            minecraft_version=mv,
            configs=configs,
            mods=mods,
            env_vars=env_vars or {},
            java_args=java_args,
        )
