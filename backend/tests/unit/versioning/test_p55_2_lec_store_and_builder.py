"""Tests for P5.5-2 LecStore, LecBuilder (5 loaders), and 7-day reference-counted GC."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import AppSettings
from app.core.exceptions import (
    InsufficientStorageError,
    LecMissingError,
    UnsupportedForgeVersionError,
    ValidationError,
)
from app.core.host_state import HostStateLayout, ensure_host_state_layout
from app.core.persistence.base import Base
from app.modules.server.application.services.jar_service import PaperBuildResolution
from app.modules.versioning.domain.lockfile import (
    EnvServer,
    LecRef,
    LoaderRef,
    LockfileFile,
    LockfileV21,
    Origin,
    dump_lockfile,
)
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.lec_builder import (
    QUILT_DEFAULT_MAIN_CLASS,
    VANILLA_MANIFEST_URL,
    LecBuilder,
)
from app.modules.versioning.infrastructure.lec_store import (
    EXPORT_MARKER_NAME,
    FORBIDDEN_LEC_ROOT_FILES,
    LecStore,
)
from app.modules.versioning.infrastructure.models import LoaderEnvCacheEntryModel

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="LEC store/builder uses POSIX-only O_DIRECTORY dir-fd and ArtifactCas",
)


def _make_layout(tmp_path: Path) -> tuple[AppSettings, HostStateLayout]:
    settings = AppSettings(
        host_state_dir=str(tmp_path / "host-state"),
        servers_data_dir=str(tmp_path / "servers"),
    )
    return settings, ensure_host_state_layout(settings)


def _write(path: Path, content: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)


class TestLecBuilderAllLoaders:
    @pytest.mark.asyncio
    async def test_build_quilt_lec_downloads_libraries_mojang_and_writes_unix_args(
        self, tmp_path: Path
    ) -> None:
        settings, layout = _make_layout(tmp_path)
        store = LecStore(layout, settings=settings)

        server_json = {
            "mainClass": QUILT_DEFAULT_MAIN_CLASS,
            "inheritsFrom": "1.20.1",
            "libraries": [
                {
                    "name": "org.quiltmc:quilt-loader:0.25.0",
                    "url": "https://maven.quiltmc.org/repository/release/",
                },
                {
                    "name": "net.fabricmc:intermediary:1.20.1",
                    "url": "https://maven.fabricmc.net/",
                },
            ],
        }
        mojang_manifest = {
            "versions": [
                {"id": "1.20.1", "url": "https://piston-meta.mojang.com/v1/packages/1.20.1.json"}
            ]
        }
        mojang_version = {
            "downloads": {
                "server": {
                    "url": "https://piston-data.mojang.com/v1/objects/abc/server.jar",
                    "sha1": "a" * 40,
                    "size": 11,
                }
            }
        }
        quilt_jar_url = (
            "https://maven.quiltmc.org/repository/release/"
            "libraries/org/quiltmc/quilt-loader/0.25.0/quilt-loader-0.25.0.jar"
        )
        interm_jar_url = (
            "https://maven.fabricmc.net/"
            "libraries/net/fabricmc/intermediary/1.20.1/intermediary-1.20.1.jar"
        )
        responses: dict[str, bytes] = {
            "https://meta.quiltmc.org/v3/versions/loader/1.20.1/0.25.0/server/json": json.dumps(
                server_json
            ).encode("utf-8"),
            quilt_jar_url: b"quilt-jar",
            interm_jar_url: b"interm-jar",
            VANILLA_MANIFEST_URL: json.dumps(mojang_manifest).encode("utf-8"),
            "https://piston-meta.mojang.com/v1/packages/1.20.1.json": json.dumps(
                mojang_version
            ).encode("utf-8"),
            "https://piston-data.mojang.com/v1/objects/abc/server.jar": b"mojang-srv!",
        }

        async def fake_download_bytes(url: str, **_kwargs: object) -> tuple[bytes, None]:
            return responses[url], None

        builder = LecBuilder(layout, store=store, download_bytes=fake_download_bytes)
        res = await builder.ensure_lec("quilt/1.20.1/0.25.0")

        assert res.lec_key == "quilt/1.20.1/0.25.0"
        assert res.java_major == 17
        unix_rel = "libraries/org/quiltmc/quilt-loader/0.25.0/unix_args.txt"
        assert res.unix_args_relpath == unix_rel
        unix_text = (res.entry_dir / unix_rel).read_text(encoding="utf-8")
        assert (
            "-Dfabric.gameJarPath=libraries/net/minecraft/server/1.20.1/server-1.20.1.jar -cp "
            in unix_text
        )
        assert "libraries/org/quiltmc/quilt-loader/0.25.0/quilt-loader-0.25.0.jar:" in unix_text
        assert QUILT_DEFAULT_MAIN_CLASS in unix_text
        assert (
            res.entry_dir / "libraries/net/minecraft/server/1.20.1/server-1.20.1.jar"
        ).read_bytes() == b"mojang-srv!"
        assert store.is_ready("quilt/1.20.1/0.25.0")

    @pytest.mark.asyncio
    async def test_build_quilt_lec_rejects_inherits_mismatch(self, tmp_path: Path) -> None:
        settings, layout = _make_layout(tmp_path)
        store = LecStore(layout, settings=settings)

        async def fake_download_bytes(_url: str, **_kwargs: object) -> tuple[bytes, None]:
            return (
                json.dumps({"inheritsFrom": "1.19.4", "libraries": []}).encode("utf-8"),
                None,
            )

        builder = LecBuilder(layout, store=store, download_bytes=fake_download_bytes)
        with pytest.raises(ValidationError, match="inheritsFrom"):
            await builder.build_quilt_lec("1.20.1", "0.25.0")

    @pytest.mark.asyncio
    async def test_build_forge_lec_purges_forbidden_files_and_checks_range(
        self, tmp_path: Path
    ) -> None:
        settings, layout = _make_layout(tmp_path)
        store = LecStore(layout, settings=settings)

        async def fake_download_bytes(_url: str, **_kwargs: object) -> tuple[bytes, None]:
            return b"PK\x03\x04installer", None

        async def fake_runner(argv: list[str], cwd: str) -> int:
            assert argv == ["java", "-jar", "installer.jar", "--installServer"]
            root = Path(cwd)
            _write(
                root / "libraries/net/minecraftforge/forge/1.20.1-47.4.23/unix_args.txt",
                "-p libraries/forge.jar\n",
            )
            _write(root / "libraries/net/minecraftforge/forge/1.20.1-47.4.23/forge.jar", b"jar")
            for forbidden in FORBIDDEN_LEC_ROOT_FILES:
                _write(root / forbidden, "root-junk")
            return 0

        builder = LecBuilder(
            layout,
            store=store,
            command_runner=fake_runner,
            download_bytes=fake_download_bytes,
        )
        with pytest.raises(UnsupportedForgeVersionError):
            await builder.build_forge_lec("1.20.2", "48.0.0")
        with pytest.raises(UnsupportedForgeVersionError):
            await builder.build_forge_lec("1.16.5", "36.2.42")

        res = await builder.ensure_lec("forge/1.20.1/47.4.23")
        assert res.lec_key == "forge/1.20.1/47.4.23"
        assert res.java_major == 17
        for forbidden in FORBIDDEN_LEC_ROOT_FILES:
            assert not (res.entry_dir / forbidden).exists()
        assert (res.entry_dir / EXPORT_MARKER_NAME).is_file()
        assert store.is_ready("forge/1.20.1/47.4.23")

    @pytest.mark.asyncio
    async def test_build_neoforge_lec_modern_and_1201(self, tmp_path: Path) -> None:
        settings, layout = _make_layout(tmp_path)
        store = LecStore(layout, settings=settings)

        async def fake_download_bytes(_url: str, **_kwargs: object) -> tuple[bytes, None]:
            return b"PK\x03\x04neo", None

        async def fake_runner(_argv: list[str], cwd: str) -> int:
            root = Path(cwd)
            if (root / "installer.jar").exists():
                # Populate whichever layout applies based on existing staging test
                _write(
                    root / "libraries/net/neoforged/neoforge/21.1.92/unix_args.txt",
                    "-cp neo.jar\n",
                )
                _write(
                    root / "libraries/net/minecraftforge/forge/1.20.1-47.1.106/unix_args.txt",
                    "-cp neo1201.jar\n",
                )
                _write(root / "run.sh", "#!/bin/sh\n")
            return 0

        builder = LecBuilder(
            layout,
            store=store,
            command_runner=fake_runner,
            download_bytes=fake_download_bytes,
        )
        modern = await builder.ensure_lec("neoforge/1.21.1/21.1.92")
        assert modern.java_major == 21
        assert modern.unix_args_relpath == "libraries/net/neoforged/neoforge/21.1.92/unix_args.txt"
        assert not (modern.entry_dir / "run.sh").exists()

        legacy = await builder.ensure_lec("neoforge/1.20.1/1.20.1-47.1.106")
        assert legacy.java_major == 17
        assert (
            legacy.unix_args_relpath
            == "libraries/net/minecraftforge/forge/1.20.1-47.1.106/unix_args.txt"
        )

    @pytest.mark.asyncio
    async def test_build_fabric_lec_keeps_libraries_and_fabric_server_only(
        self, tmp_path: Path
    ) -> None:
        settings, layout = _make_layout(tmp_path)
        store = LecStore(layout, settings=settings)
        cas = ArtifactCas(layout.cas)

        async def fake_to_cas(_url: str, active_cas: ArtifactCas, **_kwargs: object) -> str:
            return active_cas.put_bytes(b"PK\x03\x04fabric-launcher")

        async def fake_runner(_argv: list[str], cwd: str) -> int:
            root = Path(cwd)
            _write(root / "libraries/net/fabricmc/fabric-loader/0.16.10/loader.jar", b"lib")
            _write(root / "server.properties", "motd=x\n")
            return 0

        builder = LecBuilder(
            layout,
            store=store,
            cas=cas,
            command_runner=fake_runner,
            download_to_cas=fake_to_cas,
        )
        res = await builder.ensure_lec("fabric/1.21.1/0.16.10/1.0.1")
        assert res.java_major == 21
        assert (res.entry_dir / "libraries/net/fabricmc/fabric-loader/0.16.10/loader.jar").is_file()
        assert (
            res.entry_dir
            / ".fabric/server/fabric-server-mc.1.21.1-loader.0.16.10-launcher.1.0.1.jar"
        ).is_file()
        assert not (res.entry_dir / "eula.txt").exists()
        assert not (res.entry_dir / "server.properties").exists()
        assert not (
            res.entry_dir / "fabric-server-mc.1.21.1-loader.0.16.10-launcher.1.0.1.jar"
        ).exists()

    @pytest.mark.asyncio
    async def test_build_paper_lec_patchonly_snapshots_cache_versions_libraries(
        self, tmp_path: Path
    ) -> None:
        settings, layout = _make_layout(tmp_path)
        store = LecStore(layout, settings=settings)
        cas = ArtifactCas(layout.cas)

        async def fake_to_cas(_url: str, active_cas: ArtifactCas, **_kwargs: object) -> str:
            return active_cas.put_bytes(b"PK\x03\x04paper-clip")

        seen_argvs: list[list[str]] = []

        async def fake_runner(argv: list[str], cwd: str) -> int:
            seen_argvs.append(argv)
            root = Path(cwd)
            _write(root / "cache/mojang_1.21.1.jar", b"mojang")
            _write(root / "versions/1.21.1/paper-1.21.1.jar", b"patched")
            _write(root / "libraries/com/google/guava/guava.jar", b"guava")
            return 0

        resolution = PaperBuildResolution(
            mc_version="1.21.1",
            build_id=133,
            channel="STABLE",
            download_url="https://fill-data.papermc.io/v1/objects/abc/paper-1.21.1-133.jar",
            sha256=None,
            size=None,
            java_min_major=21,
        )
        builder = LecBuilder(
            layout,
            store=store,
            cas=cas,
            command_runner=fake_runner,
            download_to_cas=fake_to_cas,
        )
        with patch(
            "app.modules.versioning.infrastructure.lec_builder.resolve_paper_build",
            return_value=resolution,
        ):
            res = await builder.ensure_lec("paper/1.21.1/133")

        assert seen_argvs == [
            ["java", "-Dpaperclip.patchonly=true", "-jar", "paper-1.21.1-133.jar"]
        ]
        assert res.java_major == 21
        assert (res.entry_dir / "cache/mojang_1.21.1.jar").is_file()
        assert (res.entry_dir / "versions/1.21.1/paper-1.21.1.jar").is_file()
        assert (res.entry_dir / "libraries/com/google/guava/guava.jar").is_file()
        assert not (res.entry_dir / "paper-1.21.1-133.jar").exists()
        assert not (res.entry_dir / "eula.txt").exists()


class TestLecStoreInvariantsAndGc:
    @pytest.mark.asyncio
    async def test_rejects_empty_unix_args_tampering_and_hardlinks(self, tmp_path: Path) -> None:
        settings, layout = _make_layout(tmp_path)
        store = LecStore(layout, settings=settings)

        staging_empty = store.create_staging_dir("forge/1.20.1/47.4.23")
        _write(
            staging_empty / "libraries/net/minecraftforge/forge/1.20.1-47.4.23/unix_args.txt",
            b"",
        )
        with pytest.raises(ValidationError, match="non-empty unix_args"):
            await store.publish_staged_entry(staging_empty, "forge/1.20.1/47.4.23", java_major=17)

        staging_ok = store.create_staging_dir("forge/1.20.1/47.4.23")
        _write(
            staging_ok / "libraries/net/minecraftforge/forge/1.20.1-47.4.23/unix_args.txt",
            "-cp libraries/forge.jar\n",
        )
        await store.publish_staged_entry(staging_ok, "forge/1.20.1/47.4.23", java_major=17)
        meta = store.verify_entry("forge/1.20.1/47.4.23")
        assert meta.file_count == 1

        # Tampering fails manifest verification
        entry = store.entry_dir("forge/1.20.1/47.4.23")
        _write(
            entry / "libraries/net/minecraftforge/forge/1.20.1-47.4.23/unix_args.txt",
            "tampered",
        )
        with pytest.raises(ValidationError, match="manifest hash mismatch"):
            store.verify_entry("forge/1.20.1/47.4.23")

        # Hardlink inside staging is rejected
        staging_hl = store.create_staging_dir("paper/1.21.1/133")
        src_file = tmp_path / "hardlink_src.jar"
        _write(src_file, b"jar")
        target_file = staging_hl / "libraries/org/example/x.jar"
        target_file.parent.mkdir(parents=True, exist_ok=True)
        os.link(src_file, target_file)
        with pytest.raises(ValidationError, match="hardlinked"):
            await store.publish_staged_entry(staging_hl, "paper/1.21.1/133", java_major=21)

    def test_attach_to_target_verifies_nlink_missing_and_disk_headroom(
        self, tmp_path: Path
    ) -> None:
        settings, layout = _make_layout(tmp_path)
        store = LecStore(layout, settings=settings)

        with pytest.raises(LecMissingError) as exc_info:
            store.attach_to_target("paper/1.21.1/999", tmp_path / "dest-missing")
        assert exc_info.value.http_status == 409

        # Populate a valid entry directly via async publish
        import asyncio

        staging = store.create_staging_dir("paper/1.21.1/133")
        _write(staging / "cache/a.jar", b"abc")
        _write(staging / "libraries/b.jar", b"defg")
        asyncio.run(store.publish_staged_entry(staging, "paper/1.21.1/133", java_major=21))

        dest = tmp_path / "export-dest"
        count = store.attach_to_target("paper/1.21.1/133", dest)
        assert count == 2
        assert (dest / "cache/a.jar").stat().st_nlink == 1
        assert (dest / "libraries/b.jar").stat().st_nlink == 1

        with (
            patch(
                "app.modules.versioning.infrastructure.lec_store.shutil.disk_usage",
                return_value=type("_Usage", (), {"free": 1})(),
            ),
            pytest.raises(InsufficientStorageError),
        ):
            store.attach_to_target("paper/1.21.1/133", tmp_path / "dest-full")

    @pytest.mark.asyncio
    async def test_gc_unused_caches_7_day_reference_counted_eviction(
        self, tmp_path: Path
    ) -> None:
        settings, layout = _make_layout(tmp_path)
        store = LecStore(layout, settings=settings)
        cas = ArtifactCas(layout.cas)

        engine = create_async_engine("sqlite+aiosqlite://", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )

        now = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
        old_time = now - timedelta(days=8)
        recent_time = now - timedelta(days=3)

        # Create 4 CAS blobs:
        # 1. ref_host (old, referenced by server_meta lockfile)
        # 2. ref_git (old, referenced by git branch tip)
        # 3. recent_unref (3 days old, unreferenced)
        # 4. stale_unref (8 days old, unreferenced -> MUST BE PRUNED)
        d_host = cas.put_bytes(b"host-referenced-jar")
        d_git = cas.put_bytes(b"git-referenced-jar")
        d_recent = cas.put_bytes(b"recent-unreferenced-jar")
        d_stale = cas.put_bytes(b"stale-unreferenced-jar")

        for digest, ts in (
            (d_host, old_time),
            (d_git, old_time),
            (d_recent, recent_time),
            (d_stale, old_time),
        ):
            epoch = ts.timestamp()
            os.utime(cas.blob_path(digest), (epoch, epoch))

        # Publish 4 LEC entries with corresponding timestamps
        async with session_factory() as session:
            for key, ts in (
                ("paper/1.21.1/100", old_time),
                ("fabric/1.21.1/0.16.10/1.0.1", old_time),
                ("quilt/1.20.1/0.25.0", recent_time),
                ("forge/1.20.1/47.4.23", old_time),
            ):
                st = store.create_staging_dir(key)
                if key.startswith("paper/"):
                    _write(st / "cache/paper.jar", b"p")
                elif key.startswith("fabric/"):
                    _write(st / "libraries/fabric.jar", b"f")
                    _write(st / ".fabric/server/launcher.jar", b"l")
                elif key.startswith("quilt/"):
                    _write(
                        st / "libraries/org/quiltmc/quilt-loader/0.25.0/unix_args.txt",
                        "-cp a\n",
                    )
                else:
                    _write(
                        st / "libraries/net/minecraftforge/forge/1.20.1-47.4.23/unix_args.txt",
                        "-cp b\n",
                    )
                await store.publish_staged_entry(
                    st, key, java_major=21, session=session, completed_at=ts
                )
            await session.commit()

        # Reference 1: host server_meta lockfile references paper/1.21.1/100 + d_host
        host_lock = LockfileV21(
            format=2,
            mc="1.21.1",
            loader=LoaderRef(id="paper", version="100"),
            base_overrides={},
            files=(
                LockfileFile(
                    path="server.jar",
                    sha256=d_host,
                    size=len(b"host-referenced-jar"),
                    optional=False,
                    env_server=EnvServer.REQUIRED,
                    origin=Origin.PAPERMC,
                ),
            ),
            lec=LecRef(key="paper/1.21.1/100"),
        )
        _write(
            layout.server_meta / "srv-1" / "onx-jars.lock.json",
            dump_lockfile(host_lock),
        )

        # Reference 2: Git repo branch tip references fabric/1.21.1/0.16.10/1.0.1 + d_git
        repo_dir = layout.repos / "srv-git"
        repo_dir.mkdir(parents=True)
        subprocess.run(["git", "init", "--initial-branch=main", str(repo_dir)], check=True)
        subprocess.run(
            ["git", "-C", str(repo_dir), "config", "user.email", "test@example.com"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo_dir), "config", "user.name", "Tester"],
            check=True,
        )
        git_lock = LockfileV21(
            format=2,
            mc="1.21.1",
            loader=LoaderRef(id="fabric", version="0.16.10"),
            base_overrides={},
            files=(
                LockfileFile(
                    path="mods/mod.jar",
                    sha256=d_git,
                    size=len(b"git-referenced-jar"),
                    optional=False,
                    env_server=EnvServer.REQUIRED,
                    origin=Origin.MODRINTH,
                ),
            ),
            lec=LecRef(key="fabric/1.21.1/0.16.10/1.0.1"),
        )
        _write(repo_dir / "onx-jars.lock.json", dump_lockfile(git_lock))
        subprocess.run(["git", "-C", str(repo_dir), "add", "onx-jars.lock.json"], check=True)
        subprocess.run(["git", "-C", str(repo_dir), "commit", "-m", "lock"], check=True)

        async with session_factory() as session:
            report = await store.gc_unused_caches(session=session, now=now)
            await session.commit()

            assert report.pruned_lec_keys == ("forge/1.20.1/47.4.23",)
            assert report.pruned_cas_digests == (d_stale,)
            assert report.freed_bytes > 0

            assert store.is_ready("paper/1.21.1/100")
            assert store.is_ready("fabric/1.21.1/0.16.10/1.0.1")
            assert store.is_ready("quilt/1.20.1/0.25.0")
            assert not store.entry_dir("forge/1.20.1/47.4.23").exists()

            assert cas.blob_path(d_host).is_file()
            assert cas.blob_path(d_git).is_file()
            assert cas.blob_path(d_recent).is_file()
            assert not cas.blob_path(d_stale).exists()

            assert await session.get(LoaderEnvCacheEntryModel, "forge/1.20.1/47.4.23") is None
            assert await session.get(LoaderEnvCacheEntryModel, "paper/1.21.1/100") is not None

        await engine.dispose()
