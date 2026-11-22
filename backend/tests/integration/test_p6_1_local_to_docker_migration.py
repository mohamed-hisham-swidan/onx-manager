"""P6-1 Migration Evidence Gate.

Covers the Docker-only creation/import boundary, the idempotent Local -> Docker
migration service, the OD-v8.5-6 container hardening contract, and a real Docker
create/start/inspect/stop/restore/destroy round-trip (``@pytest.mark.docker``).
"""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.api.v1.schemas.import_server import ImportServerRequest
from app.api.v1.schemas.server import ServerCreateRequest
from app.core.config import AppSettings
from app.core.event_bus import EventBus
from app.core.identity import IDENTITY
from app.core.persistence.db import database
from app.modules.server.application.commands.create_server import (
    CreateServerCommand,
    CreateServerHandler,
)
from app.modules.server.application.commands.import_server import (
    ImportServerCommand,
    ImportServerHandler,
)
from app.modules.server.application.services.docker_migration import (
    LEGACY_LOCAL_PROVIDERS,
    migrate_all_local_servers_to_docker,
    migrate_server_to_docker,
)
from app.modules.server.domain.value_objects import (
    LaunchConfiguration,
    LocationType,
    ServerDeployment,
    default_provider_for_platform,
)
from app.modules.server.infrastructure.models import ServerModel
from app.modules.server.infrastructure.providers.base import ServerHandle
from app.modules.server.infrastructure.providers.docker import (
    DockerProvider,
    _inspect_hardening_compliance,
)
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId
from app.modules.versioning.infrastructure.branch_runtime_service import (
    build_branch_docker_create_args,
)

BLOCKED_PROVIDERS = ("local", "local_linux", "local_windows")


def _seed_legacy_server(
    root: Path,
    *,
    server_id: str | None = None,
    provider: str = "local",
) -> tuple[str, Path, str]:
    sid = server_id or f"p61-{uuid.uuid4().hex[:8]}"
    server_dir = root / sid
    (server_dir / "world").mkdir(parents=True)
    (server_dir / "world" / "level.dat").write_bytes(b"P6-1-WORLD-MARKER")
    (server_dir / "server.properties").write_text(
        "server-port=29967\nmotd=P6-1\n", encoding="utf-8"
    )
    (server_dir / "onx-jars.lock.json").write_text('{"pinned": true}\n', encoding="utf-8")
    identity_dir = server_dir / IDENTITY.identity_dir_new
    identity_dir.mkdir(parents=True)
    (identity_dir / IDENTITY.identity_file).write_text(
        json.dumps(
            {
                "uid": sid,
                "server_id": sid,
                "provider": provider,
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    return sid, server_dir, provider


def _servers_root() -> Path:
    root = Path(AppSettings().servers_data_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


class TestBlockedLocalCreationAndImport:
    @pytest.mark.parametrize("provider", BLOCKED_PROVIDERS)
    def test_server_create_request_rejects_local_providers(self, provider: str) -> None:
        with pytest.raises(ValidationError):
            ServerCreateRequest(name="blocked", provider=provider)

    @pytest.mark.parametrize("provider", BLOCKED_PROVIDERS)
    def test_import_server_request_rejects_local_providers(self, provider: str) -> None:
        with pytest.raises(ValidationError):
            ImportServerRequest(import_id="0123456789abcdef", name="blocked", provider=provider)

    def test_schema_normalizes_docker_and_empty_provider(self) -> None:
        assert ServerCreateRequest(name="ok", provider=" DOCKER ").provider == "docker"
        assert ServerCreateRequest(name="ok", provider="").provider is None
        assert ImportServerRequest(
            import_id="0123456789abcdef", name="ok", provider="Docker"
        ).provider == "docker"

    @pytest.mark.parametrize("provider", BLOCKED_PROVIDERS)
    @pytest.mark.asyncio
    async def test_create_handler_blocks_local_without_side_effects(
        self, tmp_path: Path, provider: str
    ) -> None:
        handler = CreateServerHandler(EventBus())
        target = tmp_path / f"srv-{provider}"
        result = await handler.handle(
            CreateServerCommand(
                name=f"blocked-{provider}",
                minecraft_version="1.20.4",
                provider=provider,
                install_dir=str(target),
            )
        )

        assert result.success is False
        assert result.error_code == "INVALID_PROVIDER"
        assert "Local runtime providers are deprecated and blocked" in (result.error or "")
        assert not target.exists()
        async with database.session_factory() as session:
            assert await SQLServerRepository(session).list() == []

    @pytest.mark.parametrize("provider", BLOCKED_PROVIDERS)
    @pytest.mark.asyncio
    async def test_import_handler_blocks_local_without_side_effects(
        self, tmp_path: Path, provider: str
    ) -> None:
        source = tmp_path / "source"
        source.mkdir()
        (source / "server.jar").write_bytes(b"PK fake")
        target = tmp_path / "imported"
        handler = ImportServerHandler(EventBus())

        with patch(
            "app.modules.server.application.commands.import_server.resolve_server_dir",
            return_value=str(target),
        ):
            result = await handler.handle(
                ImportServerCommand(
                    name="blocked-import",
                    source_path=str(source),
                    minecraft_version="1.20.4",
                    provider=provider,
                )
            )

        assert result.success is False
        assert result.error_code == "INVALID_PROVIDER"
        assert not target.exists()
        async with database.session_factory() as session:
            assert await SQLServerRepository(session).list() == []

    @pytest.mark.asyncio
    async def test_default_import_stamps_docker_everywhere(self, tmp_path: Path) -> None:
        source = tmp_path / "source-default"
        source.mkdir()
        (source / "server.jar").write_bytes(b"PK fake")
        target = tmp_path / "imported-default"
        handler = ImportServerHandler(EventBus())

        with patch(
            "app.modules.server.application.commands.import_server.resolve_server_dir",
            return_value=str(target),
        ):
            result = await handler.handle(
                ImportServerCommand(
                    name="default-import",
                    source_path=str(source),
                    minecraft_version="1.20.4",
                )
            )

        assert result.success is True
        server_id = result.data["server_id"]
        async with database.session_factory() as session:
            server = await SQLServerRepository(session).get(ServerId(server_id))
        assert server is not None
        assert server.runtime.provider == "docker"
        assert server.deployment is not None
        assert server.deployment.location_type == LocationType.DOCKER

        doc = json.loads(
            (target / IDENTITY.identity_dir_new / IDENTITY.identity_file).read_text(
                encoding="utf-8"
            )
        )
        assert doc["provider"] == "docker"

    def test_default_provider_is_docker_on_all_platforms(self) -> None:
        import sys

        for platform in ("linux", "darwin", "win32"):
            with patch.object(sys, "platform", platform):
                assert default_provider_for_platform() == "docker"


class TestLocalToDockerMigration:
    @pytest.mark.asyncio
    async def test_migration_preserves_data_and_updates_identity(self) -> None:
        root = _servers_root()
        ids_dirs = [
            _seed_legacy_server(root, provider="local"),
            _seed_legacy_server(root, provider="local_windows"),
            _seed_legacy_server(root, provider=""),
        ]

        async with database.session_factory() as session:
            for sid, server_dir, provider in ids_dirs:
                session.add(
                    ServerModel(
                        id=sid,
                        name=f"legacy-{sid}",
                        server_type="vanilla",
                        minecraft_version="1.20.4",
                        provider=provider,
                        location_type="local",
                        deployment_pid=4242,
                        external_id="tmux-legacy",
                        root_path=str(server_dir),
                        primary_world="world",
                        startup_jar="server.jar",
                    )
                )
            await session.commit()

            report = await migrate_all_local_servers_to_docker(session)

        assert report.migrated_count == 3
        assert report.skipped_already_docker == 0
        assert report.errors == ()

        async with database.session_factory() as session:
            for sid, server_dir, _provider in ids_dirs:
                row = await session.get(ServerModel, sid)
                assert row is not None
                assert str(row.provider) == "docker"
                assert str(row.location_type) == LocationType.DOCKER.value
                assert row.deployment_pid is None
                assert row.external_id is None

                # Data files are untouched.
                assert (server_dir / "world" / "level.dat").read_bytes() == b"P6-1-WORLD-MARKER"
                assert (server_dir / "server.properties").is_file()
                assert (server_dir / "onx-jars.lock.json").is_file()

                doc = json.loads(
                    (server_dir / IDENTITY.identity_dir_new / IDENTITY.identity_file).read_text(
                        encoding="utf-8"
                    )
                )
                assert doc["provider"] == "docker"
                assert doc["created_at"] == "2026-01-01T00:00:00+00:00"

            second = await migrate_all_local_servers_to_docker(session)

        assert second.migrated_count == 0
        assert second.skipped_already_docker == 3
        assert second.errors == ()

    @pytest.mark.asyncio
    async def test_per_server_migration_is_idempotent_and_keeps_container_ids(
        self,
    ) -> None:
        root = _servers_root()
        sid, server_dir, _provider = _seed_legacy_server(root, provider="local")

        async with database.session_factory() as session:
            session.add(
                ServerModel(
                    id=sid,
                    name="legacy-single",
                    server_type="vanilla",
                    minecraft_version="1.20.4",
                    provider="local",
                    location_type="local",
                    deployment_pid=4242,
                    external_id="onx-existing-container",
                    root_path=str(server_dir),
                )
            )
            await session.commit()

            record = await migrate_server_to_docker(session, sid)
            assert record is not None
            assert record.identity_updated is True
            assert record.cleared_stale_external_id is False

            row = await session.get(ServerModel, sid)
            assert row is not None
            assert str(row.provider) == "docker"
            assert str(row.location_type) == "docker"
            assert row.deployment_pid is None
            assert str(row.external_id) == "onx-existing-container"

            assert await migrate_server_to_docker(session, sid) is None

    @pytest.mark.asyncio
    async def test_unknown_server_raises_not_found(self) -> None:
        from app.core.exceptions import NotFoundError

        async with database.session_factory() as session:
            with pytest.raises(NotFoundError):
                await migrate_server_to_docker(session, "does-not-exist")

    def test_legacy_provider_set(self) -> None:
        assert frozenset(
            {"", "local", "local_linux", "local_windows"}
        ) == LEGACY_LOCAL_PROVIDERS


class TestOdV856HardeningContract:
    @pytest.mark.asyncio
    async def test_docker_provider_start_emits_hardening_flags(self) -> None:
        provider = DockerProvider()
        server_dir = _servers_root() / "hardening-start"
        server_dir.mkdir()
        deployment = ServerDeployment(
            location_type=LocationType.DOCKER,
            root_path=str(server_dir),
            startup_jar="server.jar",
        )
        config = {
            "image": "eclipse-temurin:21-jre-jammy",
            "port": 25566,
            "container_port": 25566,
            "memory_min_mb": 512,
            "memory_max_mb": 1024,
            "cpu_cores": 2,
        }

        with (
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            mock_docker.side_effect = [
                (1, "No such container"),
                (0, ""),
                (0, ""),
                (0, "1234 \n"),
            ]
            await provider.start(
                server_id="hardening-srv",
                config=config,
                deployment=deployment,
                launch_config=LaunchConfiguration(startup_jar="server.jar"),
            )

        create_args = [c[0] for c in mock_docker.call_args_list if c[0][0] == "create"][0]
        self._assert_hardened(create_args)

    def test_branch_runtime_args_emit_hardening_flags(self) -> None:
        export_root = _servers_root() / "branch-export"
        export_root.mkdir()

        args = build_branch_docker_create_args(
            container_name="onx-branch-test",
            image="eclipse-temurin:21-jre-jammy",
            network="bridge",
            memory_max_mb=1024,
            cpu_cores=2,
            export_root=export_root,
            uid=1000,
            gid=1000,
            server_id="srv-branch",
            branch_name="main",
            runtime_id="rt-1",
            commit_sha="deadbeef",
            cmd=["sleep", "30"],
        )

        self._assert_hardened(args)

    def _assert_hardened(self, args: list[str]) -> None:
        assert "--cap-drop=ALL" in args
        assert "--security-opt=no-new-privileges:true" in args
        assert "--pids-limit=2048" in args
        assert "--user" in args
        user = args[args.index("--user") + 1]
        assert user not in ("", "0", "0:0")
        assert "--memory" in args
        assert "--cpus" in args
        assert args[args.index("--cpus") + 1] == "2"
        assert "--privileged" not in args
        assert "--read-only" not in args

        mounts = [
            args[i + 1]
            for i, token in enumerate(args[:-1])
            if token in ("-v", "--volume")
        ]
        assert len(mounts) == 1
        assert mounts[0].endswith(":/data")
        assert "docker.sock" not in mounts[0]

    def test_inspect_hardening_rejects_privileged_readonly_and_extra_mounts(self) -> None:
        base = {
            "Config": {"User": "1000:1000"},
            "HostConfig": {
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                "PidsLimit": 2048,
                "NetworkMode": "bridge",
                "Privileged": False,
                "ReadonlyRootfs": False,
            },
            "Mounts": [{"Destination": "/data", "Source": "/srv/data"}],
        }
        assert _inspect_hardening_compliance(
            base, expected_user="1000:1000", expected_network="bridge"
        ) == (True, "ok")

        privileged = json.loads(json.dumps(base))
        privileged["HostConfig"]["Privileged"] = True
        ok, reason = _inspect_hardening_compliance(
            privileged, expected_user="1000:1000", expected_network="bridge"
        )
        assert ok is False and "privileged" in reason

        readonly = json.loads(json.dumps(base))
        readonly["HostConfig"]["ReadonlyRootfs"] = True
        ok, reason = _inspect_hardening_compliance(
            readonly, expected_user="1000:1000", expected_network="bridge"
        )
        assert ok is False and "readonly" in reason

        socket_mount = json.loads(json.dumps(base))
        socket_mount["Mounts"].append(
            {"Destination": "/var/run/docker.sock", "Source": "/var/run/docker.sock"}
        )
        ok, reason = _inspect_hardening_compliance(
            socket_mount, expected_user="1000:1000", expected_network="bridge"
        )
        assert ok is False and "docker.sock" in reason

        extra_mount = json.loads(json.dumps(base))
        extra_mount["Mounts"].append({"Destination": "/repo", "Source": "/srv/repo"})
        ok, reason = _inspect_hardening_compliance(
            extra_mount, expected_user="1000:1000", expected_network="bridge"
        )
        assert ok is False and "unexpected mount" in reason


def _cached_roundtrip_image() -> str | None:
    for image in (
        "eclipse-temurin:21-jre-jammy",
        "eclipse-temurin:17-jre-jammy",
        "eclipse-temurin:25-jre",
    ):
        probe = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode == 0:
            return image
    return None


def _docker_inspect(name: str) -> dict:
    completed = subprocess.run(
        ["docker", "inspect", name],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)[0]


@pytest.mark.docker
@pytest.mark.asyncio
async def test_real_docker_local_to_docker_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = DockerProvider()
    if not await provider.ping():
        pytest.skip("Docker daemon is unreachable")

    image = _cached_roundtrip_image()
    if image is None:
        pytest.skip("No cached lightweight Linux image available for the round-trip")

    monkeypatch.setenv("ONX_ALLOW_LEGACY_RUN_SH", "true")
    server_id = f"p61rt-{uuid.uuid4().hex[:8]}"
    server_dir = _servers_root() / server_id
    (server_dir / "world").mkdir(parents=True)
    (server_dir / "world" / "level.dat").write_bytes(b"BEFORE-STOP")
    (server_dir / "server.properties").write_text(
        "server-port=29967\n", encoding="utf-8"
    )
    (server_dir / "run.sh").write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
    (server_dir / "server.jar").write_bytes(b"PK fake")

    container_name = f"{IDENTITY.temp_prefix_new}{server_id}"
    handle = ServerHandle(
        provider="docker",
        server_id=server_id,
        external_id=container_name,
        metadata={"server_dir": str(server_dir)},
    )

    try:
        async with database.session_factory() as session:
            session.add(
                ServerModel(
                    id=server_id,
                    name="round-trip",
                    server_type="vanilla",
                    minecraft_version="1.20.4",
                    provider="local",
                    location_type="local",
                    deployment_pid=4242,
                    external_id="tmux-legacy",
                    root_path=str(server_dir),
                )
            )
            await session.commit()

            record = await migrate_server_to_docker(session, server_id)
            assert record is not None
            row = await session.get(ServerModel, server_id)
            assert row is not None
            assert str(row.provider) == "docker"
            assert str(row.location_type) == "docker"

        deployment = ServerDeployment(
            location_type=LocationType.DOCKER,
            root_path=str(server_dir),
            startup_command="/data/run.sh",
            startup_jar="server.jar",
            primary_world="world",
        )
        config = {
            "image": image,
            "port": 29967,
            "container_port": 29967,
            "memory_min_mb": 256,
            "memory_max_mb": 512,
            "cpu_cores": 1,
        }

        result = await provider.start(
            server_id=server_id,
            config=config,
            deployment=deployment,
            launch_config=LaunchConfiguration(
                startup_command=("bash", "/data/run.sh", "nogui")
            ),
        )
        assert result.status.value == "running"

        info = _docker_inspect(container_name)
        host = info["HostConfig"]
        assert info["Config"]["User"] not in ("", "0", "0:0")
        assert "ALL" in host["CapDrop"]
        assert "no-new-privileges:true" in host["SecurityOpt"]
        assert host["PidsLimit"] == 2048
        assert host["Memory"] > 0
        assert host["NanoCpus"] > 0
        assert host["Privileged"] is False
        assert host["ReadonlyRootfs"] is False

        mounts = info.get("Mounts") or []
        data_mounts = [m for m in mounts if m.get("Destination") == "/data"]
        assert len(data_mounts) == 1
        assert len(mounts) == 1
        assert "docker.sock" not in json.dumps(mounts)

        compliant, reason = _inspect_hardening_compliance(
            info,
            expected_user=str(info["Config"]["User"]),
            expected_network="bridge",
        )
        assert compliant is True, reason

        await provider.stop(handle, force=True)

        # Simulate a world restore/replacement while the container is stopped.
        (server_dir / "world" / "level.dat").write_bytes(b"AFTER-STOP-RESTORE")
        subprocess.run(["docker", "start", container_name], check=True, capture_output=True)
        visible = subprocess.run(
            ["docker", "exec", container_name, "cat", "/data/world/level.dat"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert visible.stdout == "AFTER-STOP-RESTORE"
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            check=False,
            capture_output=True,
        )
