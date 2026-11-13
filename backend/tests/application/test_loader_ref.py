"""Unit tests for loader identity derivation."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.modules.server.domain.aggregate import (
    Server,
    ServerDeployment,
    ServerType,
)
from app.modules.versioning.application.loader_ref import (
    derive_loader_ref,
    derive_loader_ref_from_parts,
)
from app.modules.versioning.domain.lockfile import LoaderRef


class TestDeriveLoaderRefFromParts:
    def test_vanilla_spigot_bukkit(self) -> None:
        ref_v = derive_loader_ref_from_parts(ServerType.VANILLA, "1.20.4")
        assert ref_v == LoaderRef(id="vanilla", version="1.20.4")

        ref_s = derive_loader_ref_from_parts(ServerType.SPIGOT, "1.20.2")
        assert ref_s == LoaderRef(id="spigot", version="1.20.2")

        ref_b = derive_loader_ref_from_parts(ServerType.BUKKIT, "1.19.4")
        assert ref_b == LoaderRef(id="bukkit", version="1.19.4")

    def test_paper_and_purpur_with_startup_jar(self) -> None:
        ref_paper = derive_loader_ref_from_parts(
            ServerType.PAPER,
            "1.20.4",
            startup_jar="paper-1.20.4-499.jar",
        )
        assert ref_paper == LoaderRef(id="paper", version="499")

        ref_purpur = derive_loader_ref_from_parts(
            ServerType.PURPUR,
            "1.20.4",
            startup_jar="purpur-1.20.4-2150.jar",
        )
        assert ref_purpur == LoaderRef(id="purpur", version="2150")

    def test_paper_fallback_when_no_jar_or_no_match(self) -> None:
        ref1 = derive_loader_ref_from_parts(ServerType.PAPER, "1.20.4", startup_jar=None)
        assert ref1 == LoaderRef(id="paper", version="1.20.4")

        ref2 = derive_loader_ref_from_parts(
            ServerType.PAPER, "1.20.4", startup_jar="custom-server.jar"
        )
        assert ref2 == LoaderRef(id="paper", version="1.20.4")

    def test_fabric_from_libraries_directory(self, tmp_path: Path) -> None:
        loader_dir = tmp_path / "libraries" / "net" / "fabricmc" / "fabric-loader"
        (loader_dir / "0.15.11").mkdir(parents=True)
        (loader_dir / "0.14.24").mkdir(parents=True)

        # Sorted first valid version segment: 0.14.24 < 0.15.11
        ref = derive_loader_ref_from_parts(
            ServerType.FABRIC,
            "1.20.4",
            server_root=tmp_path,
        )
        assert ref == LoaderRef(id="fabric", version="0.14.24")

    def test_fabric_jar_fallback(self) -> None:
        ref = derive_loader_ref_from_parts(
            ServerType.FABRIC,
            "1.20.4",
            startup_jar="fabric-server-mc.1.20.4-loader.0.15.11-launcher.1.0.1.jar",
        )
        assert ref == LoaderRef(id="fabric", version="0.15.11")

        ref2 = derive_loader_ref_from_parts(
            ServerType.FABRIC,
            "1.20.4",
            startup_jar="fabric-server-mc.1.20.4-loader.0.15.11.jar",
        )
        assert ref2 == LoaderRef(id="fabric", version="0.15.11")

    def test_forge_from_libraries_directory(self, tmp_path: Path) -> None:
        forge_dir = tmp_path / "libraries" / "net" / "minecraftforge" / "forge"
        (forge_dir / "1.20.1-47.2.0").mkdir(parents=True)

        ref = derive_loader_ref_from_parts(
            ServerType.FORGE,
            "1.20.1",
            server_root=tmp_path,
        )
        assert ref == LoaderRef(id="forge", version="47.2.0")

    def test_forge_directory_without_mc_prefix_accepted_verbatim(self, tmp_path: Path) -> None:
        forge_dir = tmp_path / "libraries" / "net" / "minecraftforge" / "forge"
        (forge_dir / "47.2.0").mkdir(parents=True)

        ref = derive_loader_ref_from_parts(
            ServerType.FORGE,
            "1.20.1",
            server_root=tmp_path,
        )
        assert ref == LoaderRef(id="forge", version="47.2.0")

    def test_forge_fallback_with_no_libraries_directory(self, tmp_path: Path) -> None:
        ref = derive_loader_ref_from_parts(
            ServerType.FORGE,
            "1.20.1",
            server_root=tmp_path,
        )
        assert ref == LoaderRef(id="forge", version="1.20.1")

    def test_neoforge_from_libraries_directory(self, tmp_path: Path) -> None:
        neo_dir = tmp_path / "libraries" / "net" / "neoforged" / "neoforge"
        (neo_dir / "20.4.80-beta").mkdir(parents=True)

        ref = derive_loader_ref_from_parts(
            ServerType.NEOFORGE,
            "1.20.4",
            server_root=tmp_path,
        )
        assert ref == LoaderRef(id="neoforge", version="20.4.80-beta")

    def test_neoforge_fallback_with_no_libraries_directory(self, tmp_path: Path) -> None:
        ref = derive_loader_ref_from_parts(
            ServerType.NEOFORGE,
            "1.20.4",
            server_root=tmp_path,
        )
        assert ref == LoaderRef(id="neoforge", version="1.20.4")

    def test_unreadable_libraries_falls_back(self, tmp_path: Path) -> None:
        lib_dir = tmp_path / "libraries" / "net" / "fabricmc" / "fabric-loader"
        lib_dir.mkdir(parents=True)

        if os.name == "posix" and os.geteuid() != 0:
            os.chmod(lib_dir, 0o000)
            try:
                ref = derive_loader_ref_from_parts(
                    ServerType.FABRIC,
                    "1.20.4",
                    server_root=tmp_path,
                )
                assert ref == LoaderRef(id="fabric", version="1.20.4")
            finally:
                os.chmod(lib_dir, 0o755)
        else:
            ref = derive_loader_ref_from_parts(
                ServerType.FABRIC,
                "1.20.4",
                server_root=tmp_path,
            )
            assert ref == LoaderRef(id="fabric", version="1.20.4")

    def test_unknown_type_warns_and_falls_back_to_vanilla(self) -> None:
        with pytest.warns(UserWarning, match="falling back to vanilla"):
            ref = derive_loader_ref_from_parts("custom_unknown", "1.20.4")  # type: ignore[arg-type]
        assert ref == LoaderRef(id="vanilla", version="1.20.4")

    def test_invalid_version_sanitized_to_valid_token(self) -> None:
        ref = derive_loader_ref_from_parts(
            ServerType.PAPER,
            "bad version with spaces!",
            startup_jar="paper-1.20.4-bad build spaces!.jar",
        )
        assert ref.id == "paper"
        assert ref.version == "1.0"


class TestDeriveLoaderRefAggregate:
    def test_delegates_to_server_attributes(self, tmp_path: Path) -> None:
        deployment = MagicMock(spec=ServerDeployment)
        deployment.startup_jar = "paper-1.20.4-500.jar"
        deployment.server_directory.return_value = str(tmp_path)

        server = MagicMock(spec=Server)
        server.server_type = ServerType.PAPER
        server.minecraft_version = "1.20.4"
        server.deployment = deployment

        ref = derive_loader_ref(server)
        assert ref == LoaderRef(id="paper", version="500")
