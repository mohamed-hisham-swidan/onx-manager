from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.server.application.ownership_verifier import (
    OwnershipResult,
    OwnershipStatus,
)
from app.modules.server.application.runtime_ownership import (
    ConflictReason,
    RuntimeOwnershipManager,
    _find_all_java_pids,
    _find_all_tmux_sessions,
    _find_child_java_pids,
    _find_minecraft_child_pids,
    _get_java_cmdline,
    _get_tmux_pane_pid,
    _is_minecraft_cmdline,
    _is_pid_alive,
    _pid_for_port,
    _port_is_listening,
    _try_kill_tmux_session,
)
from app.modules.server.domain.aggregate import Server, ServerStatus
from app.modules.server.domain.value_objects import (
    JavaArguments,
    MemoryAllocation,
    PortNumber,
    ServerProperties,
    ServerType,
)
from app.modules.shared.value_objects import MinecraftVersion, ServerId


def _make_server(
    sid: str,
    status: ServerStatus,
    with_external_id: bool = True,
    pid: int | None = 100,
    port: int = 25565,
) -> Server:
    s = Server.create(
        server_id=ServerId(sid),
        name=f"Server-{sid}",
        server_type=ServerType.VANILLA,
        minecraft_version=MinecraftVersion.parse("1.21"),
        memory=MemoryAllocation(1024, 2048),
        java_args=JavaArguments(),
        properties=ServerProperties(port=PortNumber(port)),
    )
    s.collect_events()

    if status in (ServerStatus.STARTING, ServerStatus.RUNNING, ServerStatus.STOPPING):
        s.start()
        s.collect_events()
    if status in (ServerStatus.RUNNING, ServerStatus.STOPPING):
        ext_id = f"onx-{sid}" if with_external_id else ""
        s.mark_running(pid=pid or 0, port=port, external_id=ext_id)
        s.collect_events()
    if status == ServerStatus.STOPPING:
        s.stop()
        s.collect_events()
    if status == ServerStatus.CRASHED:
        s.start()
        s.mark_running(pid=0, port=port)
        s.crash(exit_code=1)
        s.collect_events()

    return s


def _verified_ownership(
    pid: int | None = None, servers_data_dir: str | None = None
) -> OwnershipResult:
    return OwnershipResult(
        status=OwnershipStatus.VERIFIED, has_marker=True, detail="marker present"
    )


def _cwd_verified_ownership(
    pid: int | None = None, servers_data_dir: str | None = None
) -> OwnershipResult:
    return OwnershipResult(
        status=OwnershipStatus.VERIFIED,
        has_marker=False,
        cwd="/data/servers/my-server",
        cwd_matches=True,
        detail="cwd matches",
    )


class TestIsMinecraftCmdline:
    def test_matches_jar_pattern(self):
        assert _is_minecraft_cmdline("java -jar server.jar nogui")
        assert _is_minecraft_cmdline("java -Xmx2G -jar paper-1.21.jar nogui")
        assert _is_minecraft_cmdline("java -jar purpur.jar")
        assert _is_minecraft_cmdline("/usr/bin/java -jar fabric-server.jar")

    def test_matches_name_pattern(self):
        assert _is_minecraft_cmdline("java -jar spigot-1.21.jar")
        assert _is_minecraft_cmdline("java -jar forge-1.20.1.jar")
        assert _is_minecraft_cmdline("java -jar bukkit.jar")
        assert _is_minecraft_cmdline("MinecraftServer")

    def test_rejects_non_minecraft(self):
        assert not _is_minecraft_cmdline("java -jar application.jar")
        assert not _is_minecraft_cmdline("python3 server.py")
        assert not _is_minecraft_cmdline("nginx -g daemon off;")
        assert not _is_minecraft_cmdline("")


class TestFindAllTmuxSessions:
    @patch("app.modules.server.application.runtime_ownership.os.popen")
    def test_empty_output(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.read.return_value = ""
        mock_popen.return_value = mock_proc
        assert _find_all_tmux_sessions() == []

    @patch("app.modules.server.application.runtime_ownership.os.popen")
    def test_with_sessions(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.read.return_value = "onx-s1\nonx-s2\nother-session\n"
        mock_popen.return_value = mock_proc
        with patch(
            "app.modules.server.application.runtime_ownership._get_tmux_pane_pid",
            return_value=12345,
        ):
            result = _find_all_tmux_sessions()
        assert len(result) == 3
        assert result[0] == ("onx-s1", 12345)
        assert result[1] == ("onx-s2", 12345)


class TestGetJavaCmdline:
    @patch("builtins.open", new_callable=MagicMock)
    def test_reads_cmdline(self, mock_open):
        mock_file = MagicMock()
        mock_file.__enter__.return_value.read.return_value = b"java\x00-jar\x00server.jar\x00nogui"
        mock_open.return_value = mock_file
        result = _get_java_cmdline(12345)
        assert "java" in result and "server.jar" in result

    @patch("builtins.open", side_effect=FileNotFoundError)
    def test_not_found(self, mock_open):
        assert _get_java_cmdline(99999) == ""


class TestFindAllJavaPids:
    @patch("app.modules.server.application.runtime_ownership.os.popen")
    def test_empty(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.read.return_value = ""
        mock_popen.return_value = mock_proc
        assert _find_all_java_pids() == []

    @patch("app.modules.server.application.runtime_ownership.os.popen")
    def test_with_pids(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.read.return_value = "12345\n67890\n"
        mock_popen.return_value = mock_proc
        result = _find_all_java_pids()
        assert result == [12345, 67890]


class TestFindChildJavaPids:
    @patch("app.modules.server.application.runtime_ownership.os.popen")
    def test_no_children(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.read.return_value = ""
        mock_popen.return_value = mock_proc
        assert _find_child_java_pids(999) == []

    @patch("app.modules.server.application.runtime_ownership.os.popen")
    def test_with_children(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.read.return_value = "200\n"
        mock_popen.return_value = mock_proc

        with patch(
            "app.modules.server.application.runtime_ownership._find_child_java_pids",
            return_value=[300],
        ):
            result = _find_child_java_pids(100)
        assert 200 in result


class TestFindMinecraftChildPids:
    def test_no_matching_children(self):
        with (
            patch(
                "app.modules.server.application.runtime_ownership._find_child_java_pids",
                return_value=[200, 300],
            ),
            patch(
                "app.modules.server.application.runtime_ownership._is_pid_alive",
                side_effect=[True, False],
            ),
        ):
            result = _find_minecraft_child_pids(100)
        assert result == [200]


class TestPortIsListening:
    @patch("app.modules.server.application.runtime_ownership.socket.socket")
    def test_listening(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.connect_ex.return_value = 0
        assert _port_is_listening(25565) is True

    @patch("app.modules.server.application.runtime_ownership.socket.socket")
    def test_not_listening(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.connect_ex.return_value = 1
        assert _port_is_listening(25565) is False


class TestPidForPort:
    @patch("app.modules.server.application.runtime_ownership.os.popen")
    def test_found(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.read.return_value = "12345\n"
        mock_popen.return_value = mock_proc
        assert _pid_for_port(25565) == 12345

    @patch("app.modules.server.application.runtime_ownership.os.popen")
    def test_not_found(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.read.return_value = ""
        mock_popen.return_value = mock_proc
        assert _pid_for_port(25565) is None


class TestIsPidAlive:
    @patch(
        "app.modules.server.application.runtime_ownership.platform_pid_alive",
        return_value=True,
    )
    def test_alive(self, mock_alive):
        assert _is_pid_alive(100) is True

    @patch(
        "app.modules.server.application.runtime_ownership.platform_pid_alive",
        return_value=False,
    )
    def test_dead(self, mock_alive):
        assert _is_pid_alive(100) is False


class TestGetTmuxPanePid:
    @patch("app.modules.server.application.runtime_ownership.subprocess.run")
    def test_found(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="12345\n")
        assert _get_tmux_pane_pid("onx-s1") == 12345
        assert mock_run.call_args.args[0][0] == "tmux"

    @patch("app.modules.server.application.runtime_ownership.subprocess.run")
    def test_not_found(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert _get_tmux_pane_pid("onx-s1") is None


@pytest.mark.asyncio
class TestRuntimeOwnershipManagerDiscover:
    async def test_empty_db_no_os_resources(self):
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.list = AsyncMock(return_value=[])

        manager = RuntimeOwnershipManager(repo)
        with (
            patch(
                "app.modules.server.application.runtime_ownership._find_all_tmux_sessions",
                return_value=[],
            ),
            patch(
                "app.modules.server.application.runtime_ownership._find_all_java_pids",
                return_value=[],
            ),
        ):
            snapshot = await manager.discover_all()

        assert len(snapshot.active_servers) == 0
        assert len(snapshot.orphan_tmux) == 0
        assert len(snapshot.orphan_processes) == 0
        assert snapshot.total_orphans == 0
        assert len(snapshot.conflicts) == 0

    async def test_healthy_running_server(self):
        server = _make_server("s1", ServerStatus.RUNNING)
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.list = AsyncMock(return_value=[server])

        manager = RuntimeOwnershipManager(repo)
        with patch(
            "app.modules.server.application.runtime_ownership._find_all_tmux_sessions",
            return_value=[("onx-s1", 100)],
        ):
            with patch(
                "app.modules.server.application.runtime_ownership._find_all_java_pids",
                return_value=[100],
            ):
                with patch(
                    "app.modules.server.application.runtime_ownership._find_minecraft_child_pids",
                    return_value=[200],
                ):
                    with patch(
                        "app.modules.server.application.runtime_ownership._port_is_listening",
                        return_value=True,
                    ):
                        with patch(
                            "app.modules.server.application.runtime_ownership.RuntimeSupervisor.is_supervised",
                            return_value=True,
                        ):
                            snapshot = await manager.discover_all()

        assert len(snapshot.active_servers) == 1
        assert snapshot.active_servers[0]["server_id"] == "s1"
        assert snapshot.active_servers[0]["minecraft_pid"] == 200
        assert len(snapshot.orphan_tmux) == 0
        assert len(snapshot.orphan_processes) == 0
        assert snapshot.localhost_owner == "s1"

    async def test_stale_db_record(self):
        server = _make_server("s2", ServerStatus.RUNNING)
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.list = AsyncMock(return_value=[server])

        manager = RuntimeOwnershipManager(repo)
        with (
            patch(
                "app.modules.server.application.runtime_ownership._find_all_tmux_sessions",
                return_value=[],
            ),
            patch(
                "app.modules.server.application.runtime_ownership._find_all_java_pids",
                return_value=[],
            ),
        ):
            snapshot = await manager.discover_all()

        assert len(snapshot.active_servers) == 0
        assert len(snapshot.stale_db_records) == 1
        assert snapshot.stale_db_records[0]["server_id"] == "s2"

    async def test_orphan_tmux_session(self):
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.list = AsyncMock(return_value=[])

        manager = RuntimeOwnershipManager(repo)
        with (
            patch(
                "app.modules.server.application.runtime_ownership._find_all_tmux_sessions",
                return_value=[("onx-orphan", 999)],
            ),
            patch(
                "app.modules.server.application.runtime_ownership._find_minecraft_child_pids",
                return_value=[1000],
            ),
            patch(
                "app.modules.server.application.runtime_ownership._find_all_java_pids",
                return_value=[999, 1000],
            ),
        ):
            snapshot = await manager.discover_all()

        assert len(snapshot.orphan_tmux) == 1
        assert snapshot.orphan_tmux[0].identifier == "onx-orphan"
        assert snapshot.orphan_tmux[0].pid == 999
        assert len(snapshot.orphan_processes) == 0
        assert len(snapshot.conflicts) >= 1
        assert any(c.reason == ConflictReason.ORPHAN_TMUX for c in snapshot.conflicts)

    async def test_orphan_java_process(self):
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.list = AsyncMock(return_value=[])

        manager = RuntimeOwnershipManager(repo)
        with (
            patch(
                "app.modules.server.application.runtime_ownership._find_all_tmux_sessions",
                return_value=[],
            ),
            patch(
                "app.modules.server.application.runtime_ownership._find_all_java_pids",
                return_value=[5000],
            ),
            patch(
                "app.modules.server.application.runtime_ownership._get_java_cmdline",
                return_value="java -jar server.jar nogui",
            ),
            patch(
                "app.modules.server.application.runtime_ownership._is_minecraft_cmdline",
                return_value=True,
            ),
        ):
            snapshot = await manager.discover_all()

        assert len(snapshot.orphan_processes) == 1
        assert snapshot.orphan_processes[0].pid == 5000
        assert len(snapshot.conflicts) >= 1
        assert any(c.reason == ConflictReason.ORPHAN_PROCESS for c in snapshot.conflicts)

    async def test_duplicate_port_conflict(self):
        server1 = _make_server("s1", ServerStatus.RUNNING, port=25565)
        server2 = _make_server("s2", ServerStatus.RUNNING, port=25565)
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.list = AsyncMock(return_value=[server1, server2])

        manager = RuntimeOwnershipManager(repo)
        with patch(
            "app.modules.server.application.runtime_ownership._find_all_tmux_sessions",
            return_value=[("onx-s1", 100), ("onx-s2", 200)],
        ):
            with patch(
                "app.modules.server.application.runtime_ownership._find_minecraft_child_pids",
                return_value=[101],
            ):
                with patch(
                    "app.modules.server.application.runtime_ownership._find_all_java_pids",
                    return_value=[100, 200, 101],
                ):
                    with patch(
                        "app.modules.server.application.runtime_ownership._port_is_listening",
                        return_value=True,
                    ):
                        with patch(
                            "app.modules.server.application.runtime_ownership.RuntimeSupervisor.is_supervised",
                            return_value=True,
                        ):
                            snapshot = await manager.discover_all()

        assert len(snapshot.active_servers) == 2
        dup_conflicts = [c for c in snapshot.conflicts if c.reason == ConflictReason.DUPLICATE_PORT]
        assert len(dup_conflicts) == 1
        assert "25565" in dup_conflicts[0].detail


@pytest.mark.asyncio
class TestRuntimeOwnershipManagerClaim:
    async def test_claim_with_no_other_servers(self):
        server = _make_server("s1", ServerStatus.STARTING)
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.list = AsyncMock(return_value=[])
        repo.get = AsyncMock(return_value=server)

        manager = RuntimeOwnershipManager(repo)
        with (
            patch(
                "app.modules.server.application.runtime_ownership._find_all_tmux_sessions",
                return_value=[],
            ),
            patch(
                "app.modules.server.application.runtime_ownership._find_all_java_pids",
                return_value=[],
            ),
            patch(
                "app.modules.server.application.runtime_ownership._port_is_listening",
                return_value=False,
            ),
        ):
            result = await manager.claim_localhost("s1")

        assert result.success is True
        assert result.conflicts_resolved == 0

    async def test_claim_displaces_other_server(self):
        other = _make_server("other", ServerStatus.RUNNING)
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.list = AsyncMock(return_value=[other])
        repo.get = AsyncMock(return_value=other)
        repo.save = AsyncMock()

        manager = RuntimeOwnershipManager(repo)
        with patch(
            "app.modules.server.application.runtime_ownership._find_all_tmux_sessions",
            return_value=[("onx-other", 500)],
        ):
            with patch(
                "app.modules.server.application.runtime_ownership._find_minecraft_child_pids",
                return_value=[501],
            ):
                with patch(
                    "app.modules.server.application.runtime_ownership._find_all_java_pids",
                    return_value=[500, 501],
                ):
                    with patch(
                        "app.modules.server.application.runtime_ownership._port_is_listening",
                        return_value=False,
                    ):
                        with patch(
                            "app.modules.server.application.runtime_ownership._is_pid_alive",
                            return_value=False,
                        ):
                            with patch(
                                "app.modules.server.application.runtime_ownership.RuntimeSupervisor.is_supervised",
                                return_value=True,
                            ):
                                with patch(
                                    "app.modules.server.application.runtime_ownership.RuntimeSupervisor.stop_for",
                                    AsyncMock(),
                                ):
                                    mock_provider = MagicMock()
                                    mock_provider.stop = AsyncMock()
                                    with patch.object(
                                        manager._provider_factory,
                                        "get",
                                        return_value=mock_provider,
                                    ):
                                        result = await manager.claim_localhost("s1")

        assert result.success is True
        assert result.conflicts_resolved > 0
        assert any("other" in a for a in result.actions)
        repo.save.assert_called_once()

    async def test_claim_kills_orphan_tmux(self):
        server = _make_server("s1", ServerStatus.STARTING)
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.list = AsyncMock(return_value=[])
        repo.get = AsyncMock(return_value=server)

        manager = RuntimeOwnershipManager(repo)
        with patch(
            "app.modules.server.application.runtime_ownership._find_all_tmux_sessions",
            return_value=[("onx-orphan", 999)],
        ):
            with patch(
                "app.modules.server.application.runtime_ownership._find_minecraft_child_pids",
                return_value=[],
            ):
                with patch(
                    "app.modules.server.application.runtime_ownership._find_all_java_pids",
                    return_value=[999],
                ):
                    with patch(
                        "app.modules.server.application.runtime_ownership._port_is_listening",
                        return_value=False,
                    ):
                        with patch(
                            "app.modules.server.application.runtime_ownership.verify_ownership",
                            side_effect=_verified_ownership,
                        ):
                            with patch(
                                "app.modules.server.application.runtime_ownership._try_kill_tmux_session",
                                return_value=(True, "killed"),
                            ):
                                result = await manager.claim_localhost("s1")

        assert result.success is True
        assert result.conflicts_resolved >= 1

    async def test_claim_kills_orphan_tmux_with_cwd_only(self):
        server = _make_server("s1", ServerStatus.STARTING)
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.list = AsyncMock(return_value=[])
        repo.get = AsyncMock(return_value=server)

        manager = RuntimeOwnershipManager(repo)
        with patch(
            "app.modules.server.application.runtime_ownership._find_all_tmux_sessions",
            return_value=[("onx-orphan", 999)],
        ):
            with patch(
                "app.modules.server.application.runtime_ownership._find_minecraft_child_pids",
                return_value=[],
            ):
                with patch(
                    "app.modules.server.application.runtime_ownership._find_all_java_pids",
                    return_value=[999],
                ):
                    with patch(
                        "app.modules.server.application.runtime_ownership._port_is_listening",
                        return_value=False,
                    ):
                        with patch(
                            "app.modules.server.application.runtime_ownership.verify_ownership",
                            side_effect=_cwd_verified_ownership,
                        ):
                            with patch(
                                "app.modules.server.application.runtime_ownership._try_kill_tmux_session",
                                return_value=(True, "killed"),
                            ):
                                result = await manager.claim_localhost("s1")

        assert result.success is True
        assert result.conflicts_resolved >= 1
        assert not any("skipped" in w.lower() for w in result.warnings)

    async def test_claim_kills_orphan_process(self):
        server = _make_server("s1", ServerStatus.STARTING)
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.list = AsyncMock(return_value=[])
        repo.get = AsyncMock(return_value=server)

        manager = RuntimeOwnershipManager(repo)
        with patch(
            "app.modules.server.application.runtime_ownership._find_all_tmux_sessions",
            return_value=[],
        ):
            with patch(
                "app.modules.server.application.runtime_ownership._find_all_java_pids",
                return_value=[7777],
            ):
                with patch(
                    "app.modules.server.application.runtime_ownership._get_java_cmdline",
                    return_value="java -jar server.jar",
                ):
                    with patch(
                        "app.modules.server.application.runtime_ownership._is_minecraft_cmdline",
                        return_value=True,
                    ):
                        with patch(
                            "app.modules.server.application.runtime_ownership._port_is_listening",
                            return_value=False,
                        ):
                            with patch(
                                "app.modules.server.application.runtime_ownership.verify_ownership",
                                side_effect=_verified_ownership,
                            ):
                                with patch(
                                    "app.modules.server.application.runtime_ownership._try_kill_process",
                                    return_value=(True, "killed by test mock"),
                                ):
                                    result = await manager.claim_localhost("s1")

        assert result.success is True
        assert result.conflicts_resolved >= 1


@pytest.mark.asyncio
class TestRuntimeOwnershipManagerCleanup:
    async def test_cleanup_orphan_tmux(self):
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.list = AsyncMock(return_value=[])

        manager = RuntimeOwnershipManager(repo)
        with (
            patch(
                "app.modules.server.application.runtime_ownership._find_all_tmux_sessions",
                return_value=[("onx-orphan", 888)],
            ),
            patch(
                "app.modules.server.application.runtime_ownership._find_minecraft_child_pids",
                return_value=[],
            ),
            patch(
                "app.modules.server.application.runtime_ownership._find_all_java_pids",
                return_value=[888],
            ),
            patch(
                "app.modules.server.application.runtime_ownership.verify_ownership",
                side_effect=_verified_ownership,
            ),
            patch(
                "app.modules.server.application.runtime_ownership.os.kill",
            ),
            patch(
                "app.modules.server.application.runtime_ownership.os.popen",
            ),
        ):
            actions = await manager.cleanup_orphans()

        assert len(actions) == 1
        assert actions[0]["type"] == "orphan_tmux"
        assert actions[0]["identifier"] == "onx-orphan"

    async def test_cleanup_orphan_process(self):
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.list = AsyncMock(return_value=[])

        manager = RuntimeOwnershipManager(repo)
        with (
            patch(
                "app.modules.server.application.runtime_ownership._find_all_tmux_sessions",
                return_value=[],
            ),
            patch(
                "app.modules.server.application.runtime_ownership._find_all_java_pids",
                return_value=[6666],
            ),
            patch(
                "app.modules.server.application.runtime_ownership._get_java_cmdline",
                return_value="java -jar server.jar",
            ),
            patch(
                "app.modules.server.application.runtime_ownership._is_minecraft_cmdline",
                return_value=True,
            ),
            patch(
                "app.modules.server.application.runtime_ownership.verify_ownership",
                side_effect=_verified_ownership,
            ),
            patch(
                "app.modules.server.application.runtime_ownership.os.kill",
            ),
        ):
            actions = await manager.cleanup_orphans()

        assert len(actions) == 1
        assert actions[0]["type"] == "orphan_process"

    async def test_cleanup_stale_db_record(self):
        server = _make_server("stale", ServerStatus.RUNNING)
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.list = AsyncMock(return_value=[server])
        repo.get = AsyncMock(return_value=server)
        repo.save = AsyncMock()

        manager = RuntimeOwnershipManager(repo)
        with (
            patch(
                "app.modules.server.application.runtime_ownership._find_all_tmux_sessions",
                return_value=[],
            ),
            patch(
                "app.modules.server.application.runtime_ownership._find_all_java_pids",
                return_value=[],
            ),
        ):
            actions = await manager.cleanup_orphans()

        assert len(actions) == 1
        assert actions[0]["type"] == "stale_db_record"
        assert actions[0]["server_id"] == "stale"
        assert server.status == ServerStatus.CRASHED
        repo.save.assert_called_once()

    async def test_cleanup_no_orphans(self):
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.list = AsyncMock(return_value=[])

        manager = RuntimeOwnershipManager(repo)
        with (
            patch(
                "app.modules.server.application.runtime_ownership._find_all_tmux_sessions",
                return_value=[],
            ),
            patch(
                "app.modules.server.application.runtime_ownership._find_all_java_pids",
                return_value=[],
            ),
        ):
            actions = await manager.cleanup_orphans()

        assert actions == []


@pytest.mark.asyncio
class TestRuntimeOwnershipManagerValidate:
    async def test_healthy_server(self):
        server = _make_server("s1", ServerStatus.RUNNING)
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.get = AsyncMock(return_value=server)

        manager = RuntimeOwnershipManager(repo)
        with patch(
            "app.modules.server.application.runtime_ownership._find_all_tmux_sessions",
            return_value=[("onx-s1", 100)],
        ):
            with patch(
                "app.modules.server.application.runtime_ownership._find_minecraft_child_pids",
                return_value=[200],
            ):
                with patch(
                    "app.modules.server.application.runtime_ownership._is_pid_alive",
                    return_value=True,
                ):
                    with patch(
                        "app.modules.server.application.runtime_ownership._port_is_listening",
                        return_value=True,
                    ):
                        with patch(
                            "app.modules.server.application.runtime_ownership.RuntimeSupervisor.get_for",
                            return_value=MagicMock(is_running=True),
                        ):
                            result = await manager.validate_runtime("s1")

        assert result.healthy is True
        assert result.db_ok is True
        assert result.supervisor_ok is True
        assert result.tmux_ok is True
        assert result.pid_ok is True
        assert result.port_ok is True
        assert result.minecraft_ok is True

    async def test_missing_tmux(self):
        server = _make_server("s2", ServerStatus.RUNNING)
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.get = AsyncMock(return_value=server)

        manager = RuntimeOwnershipManager(repo)
        with (
            patch(
                "app.modules.server.application.runtime_ownership._find_all_tmux_sessions",
                return_value=[],
            ),
            patch(
                "app.modules.server.application.runtime_ownership.RuntimeSupervisor.get_for",
                return_value=MagicMock(is_running=True),
            ),
        ):
            result = await manager.validate_runtime("s2")

        assert result.healthy is False
        assert result.db_ok is True
        assert result.supervisor_ok is True
        assert result.tmux_ok is False
        assert result.pid_ok is False

    async def test_stopped_server(self):
        server = _make_server("s3", ServerStatus.STOPPED)
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.get = AsyncMock(return_value=server)

        manager = RuntimeOwnershipManager(repo)
        result = await manager.validate_runtime("s3")

        assert result.healthy is False
        assert result.db_ok is False


@pytest.mark.asyncio
class TestRuntimeOwnershipManagerIntegration:
    async def test_discover_and_cleanup_cycle(self):
        server = _make_server("live", ServerStatus.RUNNING)
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.list = AsyncMock(return_value=[server])
        repo.get = AsyncMock(return_value=server)
        repo.save = AsyncMock()

        manager = RuntimeOwnershipManager(repo)
        with patch(
            "app.modules.server.application.runtime_ownership._find_all_tmux_sessions",
            return_value=[("onx-live", 100)],
        ):
            with patch(
                "app.modules.server.application.runtime_ownership._find_minecraft_child_pids",
                return_value=[200],
            ):
                with patch(
                    "app.modules.server.application.runtime_ownership._find_all_java_pids",
                    return_value=[100, 200, 9000],
                ):
                    with patch(
                        "app.modules.server.application.runtime_ownership._port_is_listening",
                        return_value=True,
                    ):
                        with patch(
                            "app.modules.server.application.runtime_ownership.RuntimeSupervisor.is_supervised",
                            return_value=True,
                        ):
                            with patch(
                                "app.modules.server.application.runtime_ownership._get_java_cmdline",
                                return_value="java -jar random.jar",
                            ):
                                with patch(
                                    "app.modules.server.application.runtime_ownership._is_minecraft_cmdline",
                                    return_value=False,
                                ):
                                    snapshot = await manager.discover_all()

        assert len(snapshot.active_servers) == 1
        assert len(snapshot.orphan_processes) == 0
        assert snapshot.active_servers[0]["server_id"] == "live"
        assert snapshot.active_servers[0]["minecraft_pid"] == 200


class TestTryKillTmuxSession:
    def test_invokes_subprocess_without_shell_interpolation(self):
        hostile_session = "onx-uuid;rm -rf /;$(reboot)"
        mock_pid = "app.modules.server.application.runtime_ownership._get_tmux_pane_pid"
        with (
            patch(mock_pid, return_value=None),
            patch("subprocess.run") as mock_run,
        ):
            killed, reason = _try_kill_tmux_session(hostile_session)
            assert killed is True
            assert reason == "tmux session removed"
            mock_run.assert_called_once()
            args, kwargs = mock_run.call_args
            assert args[0] == ["tmux", "kill-session", "-t", hostile_session]
            assert kwargs.get("check") is False

    def test_handles_missing_tmux_binary_gracefully(self):
        mock_pid = "app.modules.server.application.runtime_ownership._get_tmux_pane_pid"
        with (
            patch(mock_pid, return_value=None),
            patch("subprocess.run", side_effect=FileNotFoundError("No tmux")),
        ):
            killed, reason = _try_kill_tmux_session("onx-session")
            assert killed is True
            assert reason == "tmux session removed"

