from __future__ import annotations

import os
import socket
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.core.event_bus import EventBus
from app.core.exceptions import ProviderError
from app.core.persistence.db import database
from app.modules.exposure.infrastructure.models import ServerRegisteredPortModel
from app.modules.server.application.commands.delete_server import (
    DeleteServerCommand,
    DeleteServerHandler,
)
from app.modules.server.application.commands.start_server import (
    StartServerCommand,
    StartServerHandler,
)
from app.modules.server.domain.aggregate import Server, ServerStatus
from app.modules.server.domain.value_objects import (
    JavaArguments,
    LocationType,
    MemoryAllocation,
    PortNumber,
    RuntimeInfo,
    ServerDeployment,
    ServerMode,
    ServerProperties,
    ServerType,
)
from app.modules.server.infrastructure.models import ServerModel
from app.modules.server.infrastructure.providers.docker import (
    DockerProvider,
    allocate_host_rcon_port,
)
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import MinecraftVersion, ServerId
from app.modules.versioning.infrastructure.models import (
    ServerBranchModel,
    ServerRuntimeModel,
    ServerTestRunModel,
)
from app.modules.versioning.infrastructure.port_allocator import (
    _ALLOCATED_PORTS,
    allocate_port_set,
    parse_docker_published_ports,
    reclaim_dead_port_reservations,
)

pytest_plugins = ["tests.api.test_api_endpoints"]


def _seed_server_dir(base: Path, *, port: int, rcon_password: str) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    (base / "server.jar").write_bytes(b"fake-jar")
    (base / "eula.txt").write_text("eula=true\n", encoding="utf-8")
    (base / "server.properties").write_text(
        f"server-port={port}\n"
        "enable-rcon=true\n"
        "rcon.port=25575\n"
        f"rcon.password={rcon_password}\n",
        encoding="utf-8",
    )
    return base


class TestPortAllocationAndRconIsolation:
    @pytest.mark.asyncio
    async def test_advanced_second_server_allocates_free_rcon_and_commands_route_independently(
        self,
        client: AsyncClient,
        admin_header: dict[str, str],
        tmp_path: Path,
    ) -> None:
        """Starting an Advanced-mode server while 25565/25575 are occupied allocates 25566 + a
        free non-colliding host RCON port, and POST /api/v1/servers/{id}/command routes
        independently to each server's own RCON endpoint.
        """
        srv1_id = "srv-simple-25565"
        srv2_id = "srv-advanced-25566"
        srv1_dir = _seed_server_dir(tmp_path / srv1_id, port=25565, rcon_password="pw_simple_1")
        srv2_dir = _seed_server_dir(tmp_path / srv2_id, port=25566, rcon_password="pw_adv_2")

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            s1 = Server.create(
                server_id=ServerId(srv1_id),
                name="SimpleOne",
                server_type=ServerType.PURPUR,
                minecraft_version=MinecraftVersion.parse("1.21.11"),
                memory=MemoryAllocation(1024, 2048),
                java_args=JavaArguments([]),
                properties=ServerProperties(PortNumber(25565)),
                deployment=ServerDeployment(
                    location_type=LocationType.DOCKER,
                    root_path=str(srv1_dir),
                    working_directory=".",
                    startup_jar="server.jar",
                ),
                runtime=RuntimeInfo(
                    status="running",
                    provider="docker",
                    host="172.17.0.5",
                    port=25565,
                    pid=1001,
                    external_id=f"onx-{srv1_id}",
                ),
                mode=ServerMode.SIMPLE,
            )
            s1._status = ServerStatus.RUNNING
            await repo.save(s1)

            s2 = Server.create(
                server_id=ServerId(srv2_id),
                name="AdvancedTwo",
                server_type=ServerType.PURPUR,
                minecraft_version=MinecraftVersion.parse("1.21.11"),
                memory=MemoryAllocation(1024, 2048),
                java_args=JavaArguments([]),
                properties=ServerProperties(PortNumber(25566)),
                deployment=ServerDeployment(
                    location_type=LocationType.DOCKER,
                    root_path=str(srv2_dir),
                    working_directory=".",
                    startup_jar="server.jar",
                ),
                runtime=RuntimeInfo(provider="docker", port=25565),
                mode=ServerMode.ADVANCED,
            )
            await repo.save(s2)
            # Simulate legacy stale deployment_port=25565 on Server 2
            row2 = await session.get(ServerModel, srv2_id)
            assert row2 is not None
            row2.deployment_port = 25565
            await session.commit()

        provider = DockerProvider()
        captured_creates: list[list[str]] = []
        busy_ports: set[int] = {25565, 25575}

        async def fake_docker_cmd(*args: str, **_kwargs: object) -> tuple[int, str]:
            if args[0] == "ps":
                return (
                    0,
                    f"onx-{srv1_id}\t0.0.0.0:25565->25565/tcp, 127.0.0.1:25575->25575/tcp\n",
                )
            if args[0] == "inspect" and "--format" in args:
                fmt = args[args.index("--format") + 1]
                target = args[-1]
                if "{{json .}}" in fmt:
                    if target == f"onx-{srv1_id}":
                        return (
                            0,
                            '{"NetworkSettings":{"Ports":'
                            '{"25575/tcp":[{"HostIp":"127.0.0.1","HostPort":"25575"}]}}}',
                        )
                    return (1, "")
                return (0, "2002 172.17.0.6")
            if args[0] == "create":
                captured_creates.append(list(args))
                return (0, "cid-srv2")
            if args[0] == "start":
                return (0, "")
            return (0, "")

        with (
            patch.dict(
                os.environ,
                {"MCS_SERVERS_DATA_DIR": str(tmp_path), "ONX_SERVERS_DATA_DIR": str(tmp_path)},
            ),
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", side_effect=fake_docker_cmd),
            patch(
                "app.modules.server.infrastructure.providers.docker.prepare_data_ownership",
                AsyncMock(),
            ),
            patch(
                "app.modules.server.infrastructure.providers.docker.is_loopback_port_free",
                side_effect=lambda p: p not in busy_ports,
            ),
            patch(
                "app.modules.versioning.infrastructure.port_allocator.get_live_docker_published_ports",
                return_value={25565, 25575},
            ),
            patch(
                "app.modules.server.application.commands.start_server._port_is_listening",
                return_value=False,
            ),
            patch(
                "app.modules.server.application.commands.start_server.RuntimeSupervisor.start_for",
                MagicMock(),
            ),
        ):
            handler = StartServerHandler(EventBus(), provider=provider)
            start_res = await handler.handle(StartServerCommand(server_id=srv2_id))

        assert start_res.success is True
        assert start_res.data["port"] == 25566
        assert len(captured_creates) == 1
        published = [
            captured_creates[0][i + 1]
            for i, tok in enumerate(captured_creates[0])
            if tok == "-p"
        ]
        assert "25566:25566" in published
        assert "127.0.0.1:25576:25575" in published
        assert "127.0.0.1:25575:25575" not in published

        # Verify stale deployment_port was automatically healed to 25566
        async with database.session_factory() as session:
            row2 = await session.get(ServerModel, srv2_id)
            assert row2 is not None
            assert row2.port == 25566
            assert row2.deployment_port == 25566
            row2.status = ServerStatus.RUNNING.value
            await session.commit()

        # Verify POST /api/v1/servers/{id}/command routes independently to 25575 vs 25576
        rcon_calls: list[tuple[str, int, str, str]] = []

        def make_fake_rcon(host: str, port: int, password: str, **_kw: object) -> AsyncMock:
            mock_c = AsyncMock()
            mock_c.connect = AsyncMock()
            mock_c.close = AsyncMock()

            async def _send(cmd: str) -> str:
                rcon_calls.append((host, port, password, cmd))
                return f"ok:{port}:{cmd}"

            mock_c.send_command = AsyncMock(side_effect=_send)
            return mock_c

        with (
            patch(
                "app.modules.server.infrastructure.providers.provider_factory.get",
                return_value=provider,
            ),
            patch.object(provider, "_docker_command", side_effect=fake_docker_cmd),
            patch(
                "app.modules.server.infrastructure.providers.docker.AsyncRCONClient",
                side_effect=make_fake_rcon,
            ),
        ):
            r1 = await client.post(
                f"/api/v1/servers/{srv1_id}/command",
                json={"command": "list"},
                headers=admin_header,
            )
            r2 = await client.post(
                f"/api/v1/servers/{srv2_id}/command",
                json={"command": "seed"},
                headers=admin_header,
            )

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert ("127.0.0.1", 25575, "pw_simple_1", "list") in rcon_calls
        assert ("127.0.0.1", 25576, "pw_adv_2", "seed") in rcon_calls

    @pytest.mark.asyncio
    async def test_live_socket_probe_skips_untracked_bound_port_on_loopback(
        self,
    ) -> None:
        """Live OS socket probing skips a port already bound on 127.0.0.1 even if untracked."""
        # Bind an ephemeral port on 127.0.0.1 outside the DB allocator tables
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as bound:
            bound.bind(("127.0.0.1", 0))
            bound.listen(1)
            occupied_port = bound.getsockname()[1]

            # 1. Host RCON allocator must skip the live bound port
            allocated_rcon = allocate_host_rcon_port(
                game_port=25565,
                preferred_rcon_port=occupied_port,
                reserved_ports=set(),
                check_os=True,
            )
            assert allocated_rcon != occupied_port

            # 2. Branch HostPortSet allocator must also skip the live bound port
            if os.name == "posix":
                async with database.session_factory() as session:
                    with patch(
                        "app.modules.versioning.infrastructure.port_allocator.get_live_docker_published_ports",
                        return_value=set(),
                    ):
                        ps = await allocate_port_set(
                            session,
                            start_port=occupied_port,
                            end_port=occupied_port + 20,
                            check_os_ports=True,
                        )
                assert occupied_port not in ps.all_host_ports()
                _ALLOCATED_PORTS.difference_update(ps.all_host_ports())

    @pytest.mark.asyncio
    async def test_dead_port_reservations_reclaimed_on_reconcile_and_delete(
        self,
        tmp_path: Path,
    ) -> None:
        """Dead port reservations from deleted/crashed servers are automatically reclaimed."""
        live_sid = "srv-live-keep"
        del_sid = "srv-to-delete"
        orphan_sid = "srv-already-gone"
        del_dir = _seed_server_dir(tmp_path / del_sid, port=25568, rcon_password="pw_del")
        live_dir = _seed_server_dir(tmp_path / live_sid, port=25567, rcon_password="pw_live")

        # Seed a stale persisted rcon-runtime.json on the crashed live server
        rcon_file = live_dir / ".onx-manager" / "rcon-runtime.json"
        rcon_file.parent.mkdir(parents=True, exist_ok=True)
        rcon_file.write_text('{"rcon_port": 25577}', encoding="utf-8")

        async with database.session_factory() as session:
            session.add(
                ServerModel(
                    id=live_sid,
                    name="LiveCrashed",
                    minecraft_version="1.21.11",
                    status="crashed",
                    port=25567,
                    deployment_port=25565,  # stale mismatch
                    root_path=str(live_dir),
                    working_directory=".",
                    startup_jar="server.jar",
                )
            )
            session.add(
                ServerModel(
                    id=del_sid,
                    name="ToDelete",
                    minecraft_version="1.21.11",
                    status="stopped",
                    port=25568,
                    deployment_port=25568,
                    root_path=str(del_dir),
                    working_directory=".",
                    startup_jar="server.jar",
                )
            )
            # Orphaned rows belonging to a deleted server
            session.add(
                ServerRegisteredPortModel(
                    id="reg-orphan-1",
                    server_id=orphan_sid,
                    service_type="bedrock",
                    protocol="udp",
                    port=19132,
                    name="OrphanBedrock",
                )
            )
            session.add(
                ServerBranchModel(
                    id="br-orphan-1",
                    server_id=orphan_sid,
                    name="feat-orphan",
                    status="active",
                    port_set_json={"game_port": 26100, "rcon_port": 26101},
                )
            )
            session.add(
                ServerRuntimeModel(
                    id="rt-crashed-1",
                    server_id=live_sid,
                    commit_id="c1",
                    status="crashed",
                    port=26102,
                    port_set_json={"game_port": 26102, "rcon_port": 26103},
                )
            )
            session.add(
                ServerTestRunModel(
                    id="tr-orphan-1",
                    server_id=orphan_sid,
                    commit_id="c1",
                    status="FAILED",
                    port_set_json={"game_port": 26104, "rcon_port": 26105},
                )
            )
            # Branch belonging to server we are about to delete
            session.add(
                ServerBranchModel(
                    id="br-del-1",
                    server_id=del_sid,
                    name="feat-del",
                    status="active",
                    port_set_json={"game_port": 26110, "rcon_port": 26111},
                )
            )
            await session.commit()

        _ALLOCATED_PORTS.update({26100, 26101, 26102, 26103, 26104, 26105, 26110, 26111})

        # 1. Startup reclamation cleans orphans, crashed port_sets, stale port & rcon file
        async with database.session_factory() as session:
            summary = await reclaim_dead_port_reservations(session)
            await session.commit()

        assert summary["orphaned_registered_ports"] == 1
        assert summary["orphaned_branches"] == 1
        assert summary["orphaned_test_runs"] == 1
        assert summary["cleared_dead_port_sets"] >= 1
        assert summary["healed_deployment_ports"] == 1
        assert summary["cleared_rcon_files"] == 1
        assert not rcon_file.exists()
        assert {26100, 26101, 26102, 26103, 26104, 26105}.isdisjoint(_ALLOCATED_PORTS)

        async with database.session_factory() as session:
            srv_live = await session.get(ServerModel, live_sid)
            assert srv_live is not None
            assert srv_live.deployment_port == 25567
            rt_crashed = await session.get(ServerRuntimeModel, "rt-crashed-1")
            assert rt_crashed is not None
            assert rt_crashed.port_set_json is None

        # 2. DeleteServerHandler cleans up branches/runtimes/test_runs and releases in-process ports
        mock_factory = MagicMock()
        mock_provider = AsyncMock()
        mock_provider.status = AsyncMock(return_value=MagicMock(value="stopped"))
        mock_provider.destroy = AsyncMock()
        mock_factory.get.return_value = mock_provider

        with patch.dict(
            os.environ,
            {"MCS_SERVERS_DATA_DIR": str(tmp_path), "ONX_SERVERS_DATA_DIR": str(tmp_path)},
        ):
            del_handler = DeleteServerHandler(EventBus(), provider_factory=mock_factory)
            del_res = await del_handler.handle(DeleteServerCommand(server_id=del_sid))

        assert del_res.success is True
        assert {26110, 26111}.isdisjoint(_ALLOCATED_PORTS)
        async with database.session_factory() as session:
            assert await session.get(ServerBranchModel, "br-del-1") is None

    @pytest.mark.asyncio
    async def test_fast_docker_start_error_returned_by_console_endpoint(
        self,
        client: AsyncClient,
        admin_header: dict[str, str],
        tmp_path: Path,
    ) -> None:
        """Fast docker start errors appear untruncated in GET /api/v1/servers/{id}/console."""
        sid = "srv-fast-crash-api"
        srv_dir = _seed_server_dir(tmp_path / sid, port=25566, rcon_password="pw_crash")

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            s = Server.create(
                server_id=ServerId(sid),
                name="FastCrashApi",
                server_type=ServerType.PURPUR,
                minecraft_version=MinecraftVersion.parse("1.21.11"),
                memory=MemoryAllocation(1024, 2048),
                java_args=JavaArguments([]),
                properties=ServerProperties(PortNumber(25566)),
                deployment=ServerDeployment(
                    location_type=LocationType.DOCKER,
                    root_path=str(srv_dir),
                    working_directory=".",
                    startup_jar="server.jar",
                ),
                runtime=RuntimeInfo(provider="docker", port=25565),
                mode=ServerMode.ADVANCED,
            )
            await repo.save(s)
            await session.commit()

        mock_provider = AsyncMock()
        mock_provider.name = "docker"
        mock_provider.prepare_environment = AsyncMock()
        mock_provider.start = AsyncMock(
            side_effect=ProviderError(
                "docker",
                "start",
                "Container start failed: Error response from daemon: "
                "Bind for 127.0.0.1:25575 failed: port is already allocated",
            )
        )

        with patch(
            "app.modules.server.application.commands.start_server._port_is_listening",
            return_value=False,
        ):
            res = await StartServerHandler(EventBus(), provider=mock_provider).handle(
                StartServerCommand(server_id=sid)
            )
        assert res.success is False
        assert res.error_code == "PROVIDER_START_FAILED"

        resp = await client.get(
            f"/api/v1/servers/{sid}/console",
            headers=admin_header,
        )
        assert resp.status_code == 200
        lines = resp.json().get("lines", [])
        expected_err = "Bind for 127.0.0.1:25575 failed: port is already allocated"
        assert any(expected_err in ln for ln in lines)

    def test_parse_docker_published_ports(self) -> None:
        spec = (
            "0.0.0.0:25565->25565/tcp, [::]:25565->25565/tcp, "
            "127.0.0.1:25575->25575/tcp, 8082/tcp, 127.0.0.1:25600-25602->25600-25602/tcp"
        )
        parsed = parse_docker_published_ports(spec)
        assert parsed == {25565, 25575, 25600, 25601, 25602}

    @pytest.mark.asyncio
    async def test_start_clears_stale_crash_logs_and_console_returns_live_logs_only(
        self,
        client: AsyncClient,
        admin_header: dict[str, str],
        tmp_path: Path,
    ) -> None:
        """Starting a previously crashed server clears last_log_lines/last_crash_time and
        GET /api/v1/servers/{id}/console never returns old crash errors while STARTING/RUNNING.
        """
        from app.modules.server.application.logging_utils import persist_crash_evidence
        from app.modules.server.infrastructure.providers.base import (
            DeploymentResult,
            ServerRuntimeStatus,
        )

        sid = "srv-clear-stale-crash"
        srv_dir = _seed_server_dir(tmp_path / sid, port=25569, rcon_password="pw_clear")

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            s = Server.create(
                server_id=ServerId(sid),
                name="StaleCrashClear",
                server_type=ServerType.PURPUR,
                minecraft_version=MinecraftVersion.parse("1.21.11"),
                memory=MemoryAllocation(1024, 2048),
                java_args=JavaArguments([]),
                properties=ServerProperties(PortNumber(25569)),
                deployment=ServerDeployment(
                    location_type=LocationType.DOCKER,
                    root_path=str(srv_dir),
                    working_directory=".",
                    startup_jar="server.jar",
                ),
                runtime=RuntimeInfo(provider="docker", port=25569),
                mode=ServerMode.ADVANCED,
            )
            s.start()
            s.crash(
                exit_code=-1,
                last_log_lines=["[ERROR] docker start failed: stale old bind error"],
            )
            await repo.save(s)
            await persist_crash_evidence(
                session, sid, ["[ERROR] docker start failed: stale old bind error"]
            )
            await session.commit()

        mock_provider = AsyncMock()
        mock_provider.name = "docker"
        mock_provider.prepare_environment = AsyncMock()
        mock_provider.start = AsyncMock(
            return_value=DeploymentResult(
                status=ServerRuntimeStatus.RUNNING,
                address="172.17.0.9",
                port=25569,
                pid=9001,
                metadata={"session_name": f"onx-{sid}", "rcon_port": 25579},
            )
        )
        # Simulate container just started with empty stdout initially
        mock_provider.console = AsyncMock(return_value=[])

        with (
            patch(
                "app.modules.server.application.commands.start_server._port_is_listening",
                return_value=False,
            ),
            patch(
                "app.modules.server.application.commands.start_server.RuntimeSupervisor.start_for",
                MagicMock(),
            ),
            patch(
                "app.modules.server.infrastructure.providers.provider_factory.get",
                return_value=mock_provider,
            ),
        ):
            res = await StartServerHandler(EventBus(), provider=mock_provider).handle(
                StartServerCommand(server_id=sid)
            )
            assert res.success is True

            # Verify DB cleared last_crash_time and runtime status is starting
            async with database.session_factory() as session:
                row = await session.get(ServerModel, sid)
                assert row is not None
                assert row.status == ServerStatus.STARTING.value
                assert row.last_crash_time is None

            # Console endpoint must NOT leak stale crash evidence while STARTING
            resp = await client.get(
                f"/api/v1/servers/{sid}/console",
                headers=admin_header,
            )
            assert resp.status_code == 200
            lines = resp.json().get("lines", [])
            assert lines == []
            assert not any("stale old bind error" in ln for ln in lines)

            # Once live container emits logs, console returns only live logs
            mock_provider.console = AsyncMock(
                return_value=["[12:00:00 INFO]: Starting minecraft server version 1.21.11"]
            )
            resp2 = await client.get(
                f"/api/v1/servers/{sid}/console",
                headers=admin_header,
            )
            assert resp2.status_code == 200
            lines2 = resp2.json().get("lines", [])
            assert lines2 == ["[12:00:00 INFO]: Starting minecraft server version 1.21.11"]
