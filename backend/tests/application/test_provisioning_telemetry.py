from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.event_bus import EventBus
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.modules.server.application.commands.create_server import (
    CreateServerCommand,
    CreateServerHandler,
)
from app.modules.server.application.read_models import ServerDetailReadModel
from app.modules.server.application.services.installer_provisioner import InstallerProvisioner
from app.modules.server.application.services.jar_service import _do_download
from app.modules.server.application.services.provisioning_telemetry import (
    PROVISIONING_STEPS,
    ProvisioningTelemetryStore,
)
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.installer import InstallerResult, ProgressLine
from app.modules.server.domain.value_objects import (
    JavaArguments,
    LocationType,
    MemoryAllocation,
    PortNumber,
    ServerDeployment,
    ServerProperties,
    ServerType,
)
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import MinecraftVersion, ServerId


@pytest.fixture(autouse=True)
async def _isolated_db_and_telemetry():
    ProvisioningTelemetryStore.clear_all()
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    database._engine = engine
    database._session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    yield
    ProvisioningTelemetryStore.clear_all()
    await engine.dispose()
    database._engine = None
    database._session_factory = None


class _FakeStreamContent:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    async def read(self, _size: int) -> bytes:
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


class TestDownloadProgressTelemetry:
    @pytest.mark.asyncio
    async def test_do_download_emits_bytes_speed_and_eta_when_content_length_known(
        self, tmp_path: Path
    ) -> None:
        chunk = b"PK\x03\x04" + b"a" * 65532
        resp = MagicMock()
        resp.__aenter__.return_value = resp
        resp.status = 200
        resp.content_length = len(chunk) * 3
        resp.headers = {"Content-Length": str(len(chunk) * 3)}
        resp.content = _FakeStreamContent([chunk, chunk, chunk])

        progress_calls: list[tuple[Any, ...]] = []

        def on_progress(
            filename: str,
            bytes_downloaded: int,
            total_bytes: int | None,
            speed_bps: float | None,
            eta_seconds: float | None,
            file_index: int,
            file_total: int,
        ) -> None:
            progress_calls.append(
                (
                    filename,
                    bytes_downloaded,
                    total_bytes,
                    speed_bps,
                    eta_seconds,
                    file_index,
                    file_total,
                )
            )

        dest = tmp_path / "purpur-1.21.11.jar"
        # Advance monotonic clock by 0.25s between chunks so throttled intermediate updates fire
        clock_values = iter([10.0, 10.25, 10.5, 10.75, 11.0, 11.25])
        with (
            patch("aiohttp.ClientSession.get", return_value=resp),
            patch(
                "app.modules.server.application.services.jar_service.time.monotonic",
                side_effect=lambda: next(clock_values, 11.5),
            ),
        ):
            await _do_download(
                "https://api.purpurmc.org/v2/purpur/1.21.11/latest/download",
                dest=str(dest),
                on_progress=on_progress,
                file_index=1,
                file_total=2,
                display_filename="purpur-1.21.11-2568.jar",
            )

        assert dest.exists()
        assert len(progress_calls) >= 3
        # Initial frame
        assert progress_calls[0][0] == "purpur-1.21.11-2568.jar"
        assert progress_calls[0][1] == 0
        assert progress_calls[0][2] == len(chunk) * 3
        assert progress_calls[0][5] == 1
        assert progress_calls[0][6] == 2
        # Intermediate throttled frame has smoothed speed and positive ETA
        mid = progress_calls[1]
        assert mid[1] == len(chunk)
        assert mid[3] is not None and mid[3] > 0
        assert mid[4] is not None and mid[4] >= 0
        # Final completion frame
        last = progress_calls[-1]
        assert last[1] == len(chunk) * 3
        assert last[2] == len(chunk) * 3
        assert last[4] == 0.0

    @pytest.mark.asyncio
    async def test_do_download_falls_back_gracefully_without_content_length(
        self, tmp_path: Path
    ) -> None:
        chunk = b"x" * 1024
        resp = MagicMock()
        resp.__aenter__.return_value = resp
        resp.status = 200
        resp.content_length = None
        resp.headers = {}
        resp.content = _FakeStreamContent([chunk, chunk])

        progress_calls: list[tuple[Any, ...]] = []
        dest = tmp_path / "chunked.jar"
        with patch("aiohttp.ClientSession.get", return_value=resp):
            await _do_download(
                "https://example.com/chunked.jar",
                dest=str(dest),
                on_progress=lambda *args: progress_calls.append(args),
            )

        assert progress_calls[0][2] is None
        assert progress_calls[0][4] is None
        assert progress_calls[-1][1] == 2048
        assert progress_calls[-1][4] is None


class TestCreateServerProvisioningTelemetry:
    @pytest.mark.asyncio
    async def test_create_server_records_5_steps_activity_and_artifacts(
        self, tmp_path: Path
    ) -> None:
        event_bus = EventBus()
        captured_events: list[Any] = []

        async def _capture(event: Any) -> None:
            captured_events.append(event)

        event_bus.subscribe("ForgeProvisionProgressEvent", SimpleNamespace(handle=_capture))

        server_dir = tmp_path / "srv-purpur"

        async def _fake_download(
            server_id: str,
            server_type: str,
            minecraft_version: str,
            deployment=None,
            fs=None,
        ) -> str:
            del server_id, server_type, minecraft_version, fs
            dest = Path(deployment.jar_path())
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"PK\x03\x04" + b"\x00" * (1024 * 1024))
            return str(dest)

        handler = CreateServerHandler(event_bus)
        cmd = CreateServerCommand(
            name="Purpur Telemetry",
            server_type="purpur",
            minecraft_version="1.21.4",
            port=25566,
        )

        with (
            patch(
                "app.modules.server.application.services.jar_service.resolve_server_dir",
                return_value=str(server_dir),
            ),
            patch(
                "app.modules.server.application.services.jar_service.download_server_jar",
                side_effect=_fake_download,
            ),
        ):
            result = await handler.handle(cmd)

        assert result.success is True
        sid = result.data["server_id"]
        snapshot = result.data["provisioning_progress"]
        assert snapshot["status"] == "completed"
        assert snapshot["percent"] == 100
        assert [s["id"] for s in snapshot["steps"]] == [s[0] for s in PROVISIONING_STEPS]
        assert all(s["status"] == "completed" for s in snapshot["steps"])
        assert len(snapshot["activity"]) >= 4
        assert len(snapshot["artifacts"]) == 3
        assert any("Java 21" in art["value"] for art in snapshot["artifacts"])
        assert any("25566" in art["value"] for art in snapshot["artifacts"])

        # Snapshot is also persisted in store & exposed via ServerDetailReadModel
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            server = await repo.get(ServerId(sid))
            detail = ServerDetailReadModel.from_domain(server)
            assert detail.provisioning_progress is not None
            assert detail.provisioning_progress["status"] == "completed"

        # WS events were emitted with snapshot attached
        assert len(captured_events) >= 1
        assert captured_events[-1].stage == "success"
        assert captured_events[-1].snapshot["status"] == "completed"


class _DummyInstallerProvisioner(InstallerProvisioner):
    @property
    def provider_name(self) -> str:
        return "NeoForge"

    async def _resolve_build(self, minecraft_version: str) -> str | None:
        return f"{minecraft_version}-21.1.72"

    def _installer_url(self, full_version: str) -> str:
        return f"https://example.com/neoforge-{full_version}-installer.jar"

    def _installer_filename(self) -> str:
        return "neoforge-installer.jar"

    def _installer_args(self) -> str:
        return "java -jar neoforge-installer.jar --installServer"

    def _unix_args_relpath(self, minecraft_version: str, full_version: str) -> str:
        del minecraft_version
        return f"libraries/net/neoforged/neoforge/{full_version}/unix_args.txt"


class TestInstallerProvisioningTelemetry:
    @pytest.mark.asyncio
    async def test_installer_provisioner_tracks_steps_and_artifacts(self, tmp_path: Path) -> None:
        sid = ServerId("srv-neo-telemetry")
        server = Server.create(
            server_id=sid,
            name="NeoForge Live",
            server_type=ServerType.NEOFORGE,
            minecraft_version=MinecraftVersion.parse("1.21.1"),
            memory=MemoryAllocation(2048, 4096),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25570)),
            deployment=ServerDeployment(
                location_type=LocationType.LOCAL,
                root_path=str(tmp_path),
                working_directory=".",
                startup_jar="server.jar",
            ),
        )
        server.collect_events()
        server.begin_provisioning()

        async def _run(
            command: str,
            *,
            timeout: float,
            cwd: str | None = None,
        ) -> AsyncGenerator[ProgressLine | InstallerResult, None]:
            del command, timeout, cwd
            yield ProgressLine(
                stage="downloading_libraries",
                percent=40,
                message="Downloading libraries 40%",
                raw_line="",
            )
            yield ProgressLine(
                stage="installing_profile",
                percent=80,
                message="Installing profile 80%",
                raw_line="",
            )
            yield InstallerResult(exit_code=0, output="Success", timed_out=False)

        fs = MagicMock()
        fs.exists.return_value = True
        fs.size.return_value = 4_200_000
        fs.write_text.return_value = None
        fs.delete.return_value = None

        event_bus = EventBus()
        provisioner = _DummyInstallerProvisioner(
            runner=SimpleNamespace(run=_run),
            fs=fs,
            event_bus=event_bus,
        )

        with (
            patch(
                "app.modules.server.application.services.installer_provisioner._load_server",
                AsyncMock(return_value=server),
            ),
            patch(
                "app.modules.server.application.services.installer_provisioner._save_server",
                AsyncMock(),
            ),
            patch(
                "app.modules.server.application.services.installer_provisioner.download_installer_jar",
                AsyncMock(return_value=str(tmp_path / "neoforge-installer.jar")),
            ),
        ):
            await provisioner.provision(str(sid), "1.21.1")

        snap = ProvisioningTelemetryStore.get_snapshot(str(sid))
        assert snap is not None
        assert snap["status"] == "completed"
        assert [s["id"] for s in snap["steps"]] == [s[0] for s in PROVISIONING_STEPS]
        assert all(s["status"] == "completed" for s in snap["steps"])
        assert any("NeoForge 1.21.1-21.1.72" in a["value"] for a in snap["artifacts"])
        assert any("Downloading loader libraries..." in act["message"] for act in snap["activity"])
