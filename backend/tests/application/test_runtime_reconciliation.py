import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.server.application.runtime_reconciliation import (
    MismatchType,
    ServerRuntimeState,
    _detect_mismatches,
    _get_server_state,
    reconcile_all_runtimes,
    reconcile_orphans,
    reconcile_server_runtime,
)
from app.modules.server.domain.aggregate import Server, ServerStatus
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.domain.value_objects import (
    JavaArguments,
    MemoryAllocation,
    PortNumber,
    RuntimeInfo,
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


def _mock_provider(verify_process: bool = True, tmux_pid: int | None = 100):
    p = MagicMock()
    p.provider_type = "local"
    p.verify_process = AsyncMock(return_value=verify_process)
    p.get_runtime_pid = AsyncMock(return_value=tmux_pid)
    return p


@pytest.mark.asyncio
class TestReconcileServerRuntime:
    async def test_running_server_healthy(self):
        server = _make_server("s1", ServerStatus.RUNNING)
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.save = AsyncMock()

        with (
            patch(
                "app.modules.server.application.runtime_reconciliation.provider_factory.get",
                return_value=_mock_provider(verify_process=True, tmux_pid=100),
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation.platform_pid_alive",
                return_value=True,
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation.RuntimeSupervisor.get_for",
                return_value=MagicMock(is_running=True),
            ),
        ):
            outcome = await reconcile_server_runtime(server, repo)

        assert len(outcome.mismatches) == 0
        assert outcome.repaired is False

    async def test_running_no_supervisor(self):
        server = _make_server("s2", ServerStatus.RUNNING)
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.save = AsyncMock()

        with (
            patch(
                "app.modules.server.application.runtime_reconciliation.provider_factory.get",
                return_value=_mock_provider(verify_process=True, tmux_pid=100),
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation.os.kill",
                return_value=None,
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation.RuntimeSupervisor.get_for",
                return_value=None,
            ),
        ):
            outcome = await reconcile_server_runtime(server, repo)

        assert len(outcome.mismatches) >= 1
        types = [m.mismatch_type for m in outcome.mismatches]
        assert MismatchType.DB_RUNNING_NO_SUPERVISOR in types

    async def test_running_no_tmux(self):
        server = _make_server("s3", ServerStatus.RUNNING)
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.save = AsyncMock()

        with (
            patch(
                "app.modules.server.application.runtime_reconciliation.provider_factory.get",
                return_value=_mock_provider(verify_process=False, tmux_pid=None),
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation.RuntimeSupervisor.get_for",
                return_value=None,
            ),
        ):
            outcome = await reconcile_server_runtime(server, repo)

        assert outcome.repaired is True
        repo.save.assert_called_once()
        assert server.status == ServerStatus.CRASHED

    async def test_tmux_pid_dead(self):
        server = _make_server("s4", ServerStatus.RUNNING)
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.save = AsyncMock()

        with (
            patch(
                "app.modules.server.application.runtime_reconciliation.provider_factory.get",
                return_value=_mock_provider(verify_process=True, tmux_pid=999),
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation.platform_pid_alive",
                return_value=False,
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation.RuntimeSupervisor.get_for",
                return_value=MagicMock(is_running=True),
            ),
        ):
            outcome = await reconcile_server_runtime(server, repo)

        assert outcome.repaired is True
        assert server.status == ServerStatus.CRASHED

    async def test_supervisor_no_tmux(self):
        server = _make_server("s5", ServerStatus.RUNNING)
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.save = AsyncMock()

        with (
            patch(
                "app.modules.server.application.runtime_reconciliation.provider_factory.get",
                return_value=_mock_provider(verify_process=False, tmux_pid=None),
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation.RuntimeSupervisor.get_for",
                return_value=MagicMock(is_running=True),
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation.RuntimeSupervisor.stop_for",
                AsyncMock(),
            ) as mock_stop,
        ):
            outcome = await reconcile_server_runtime(server, repo)

        assert outcome.repaired is True
        mock_stop.assert_awaited_once_with("s5")

    async def test_starting_but_alive(self):
        server = _make_server("s6", ServerStatus.STARTING, pid=None)
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.save = AsyncMock()

        with (
            patch(
                "app.modules.server.application.runtime_reconciliation.provider_factory.get",
                return_value=_mock_provider(verify_process=True, tmux_pid=200),
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation.platform_pid_alive",
                return_value=True,
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation._port_is_listening",
                return_value=True,
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation.RuntimeSupervisor.get_for",
                return_value=None,
            ),
        ):
            outcome = await reconcile_server_runtime(server, repo)

        assert outcome.repaired is True
        assert server.status == ServerStatus.RUNNING
        assert len(outcome.actions) == 1
        assert "STARTING" in outcome.actions[0]

    async def test_created_server_no_action(self):
        for status in (ServerStatus.CREATED, ServerStatus.STOPPED, ServerStatus.CRASHED):
            server = _make_server(f"s-{status.value}", status)
            repo = MagicMock(spec_set=["get", "list", "save", "delete"])
            repo.save = AsyncMock()

            outcome = await reconcile_server_runtime(server, repo)

            assert len(outcome.mismatches) == 0
            assert outcome.repaired is False
            repo.save.assert_not_called()

    async def test_provider_not_found(self):
        server = _make_server("s9", ServerStatus.RUNNING)
        server._runtime = RuntimeInfo(status="running", provider="nonexistent")
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])

        outcome = await reconcile_server_runtime(server, repo)

        assert outcome.error is not None
        assert "provider" in (outcome.error or "").lower()


@pytest.mark.asyncio
class TestReconcileAllRuntimes:
    async def test_all_healthy(self):
        servers = [
            _make_server("a1", ServerStatus.CREATED),
            _make_server("a2", ServerStatus.STOPPED),
            _make_server("a3", ServerStatus.RUNNING),
        ]
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.list = AsyncMock(return_value=servers)
        repo.save = AsyncMock()

        with (
            patch(
                "app.modules.server.application.runtime_reconciliation.provider_factory.get",
                return_value=_mock_provider(verify_process=True, tmux_pid=100),
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation.platform_pid_alive",
                return_value=True,
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation.RuntimeSupervisor.get_for",
                return_value=MagicMock(is_running=True),
            ),
        ):
            outcomes = await reconcile_all_runtimes(repo)

        assert len(outcomes) == 3
        assert all(o.repaired is False for o in outcomes)
        assert sum(len(o.mismatches) for o in outcomes) == 0

    async def test_specific_servers_only(self):
        servers = [
            _make_server("b1", ServerStatus.RUNNING),
            _make_server("b2", ServerStatus.RUNNING),
        ]
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.get = AsyncMock(
            side_effect=lambda sid: next(s for s in servers if str(s.id) == str(sid))
        )
        repo.save = AsyncMock()

        with (
            patch(
                "app.modules.server.application.runtime_reconciliation.provider_factory.get",
                return_value=_mock_provider(verify_process=True, tmux_pid=100),
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation.os.kill",
                return_value=None,
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation.RuntimeSupervisor.get_for",
                return_value=MagicMock(is_running=True),
            ),
        ):
            outcomes = await reconcile_all_runtimes(repo, server_ids=["b1"])

        assert len(outcomes) == 1
        assert str(outcomes[0].server_id) == "b1"


def _patch_ownership_helpers(
    marker_present: bool = False,
    cwd: str | None = None,
    is_owned: bool | None = None,
):
    """Return a dict of patches for the ownership helper functions.

    When `is_owned` is set, `_is_project_owned_process` is patched directly.
    Otherwise, `_get_process_env` and `_get_process_cwd` are patched individually.
    """
    patches_dict: dict[str, object] = {}

    if is_owned is not None:
        patches_dict["_is_project_owned_process"] = patch(
            "app.modules.server.application.runtime_reconciliation._is_project_owned_process",
            return_value=is_owned,
        )
    else:
        env = {"MCS_MANAGED": "1"} if marker_present else {}
        patches_dict["_get_process_env"] = patch(
            "app.modules.server.application.runtime_reconciliation._get_process_env",
            return_value=env,
        )
        patches_dict["_get_process_cwd"] = patch(
            "app.modules.server.application.runtime_reconciliation._get_process_cwd",
            return_value=cwd,
        )
        patches_dict["_get_process_start_time"] = patch(
            "app.modules.server.application.runtime_reconciliation._get_process_start_time",
            return_value=123456,
        )

    return patches_dict


@pytest.mark.asyncio
class TestReconcileOrphans:
    @pytest.fixture(autouse=True)
    def _hermetic_identity(self):
        from app.core.process_utils import ProcessIdentityCheck

        with patch(
            "app.modules.server.application.runtime_reconciliation.verify_process_identity",
            return_value=ProcessIdentityCheck(verified=True, reason="mocked"),
        ):
            yield

    async def test_no_orphans(self):
        with (
            patch(
                "app.modules.server.application.runtime_reconciliation._find_all_tmux_sessions",
                return_value=[],
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation._find_all_java_pids",
                return_value=[],
            ),
        ):
            actions = await reconcile_orphans()

        assert actions == []

    async def test_kills_orphan_tmux_system_wide(self):
        with (
            patch(
                "app.modules.server.application.runtime_reconciliation._find_all_tmux_sessions",
                return_value=["onx-orphan"],
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation._get_tmux_pid",
                return_value=12345,
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation.os.kill",
            ) as mock_kill,
            patch(
                "app.modules.server.application.runtime_reconciliation.os.popen",
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation.subprocess.run",
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation._find_all_java_pids",
                return_value=[],
            ),
        ):
            actions = await reconcile_orphans(scope="system_wide")

        assert len(actions) == 1
        assert actions[0]["type"] == "orphan_tmux"
        assert actions[0]["session"] == "onx-orphan"
        mock_kill.assert_any_call(12345, signal.SIGTERM)

    async def test_kills_orphan_tmux_project_owned(self):
        with patch(
            "app.modules.server.application.runtime_reconciliation._find_all_tmux_sessions",
            return_value=["onx-orphan"],
        ):
            with patch(
                "app.modules.server.application.runtime_reconciliation._get_tmux_pid",
                return_value=12345,
            ):
                with patch(
                    "app.modules.server.application.runtime_reconciliation.os.kill",
                ) as mock_kill:
                    with patch(
                        "app.modules.server.application.runtime_reconciliation.os.popen",
                    ):
                        with patch(
                            "app.modules.server.application.runtime_reconciliation.subprocess.run",
                        ):
                            with patch(
                                "app.modules.server.application.runtime_reconciliation._find_all_java_pids",
                                return_value=[],
                            ):
                                with patch(
                                    "app.modules.server.application.runtime_reconciliation._is_project_owned_process",
                                    return_value=True,
                                ):
                                    actions = await reconcile_orphans()

        assert len(actions) == 1
        assert actions[0]["type"] == "orphan_tmux"
        assert actions[0]["session"] == "onx-orphan"
        mock_kill.assert_any_call(12345, signal.SIGTERM)

    async def test_skips_non_owned_tmux_in_project_scope(self):
        with patch(
            "app.modules.server.application.runtime_reconciliation._find_all_tmux_sessions",
            return_value=["onx-untracked"],
        ):
            with patch(
                "app.modules.server.application.runtime_reconciliation._get_tmux_pid",
                return_value=99999,
            ):
                with patch(
                    "app.modules.server.application.runtime_reconciliation._is_project_owned_process",
                    return_value=False,
                ):
                    with patch(
                        "app.modules.server.application.runtime_reconciliation.os.kill",
                    ) as mock_kill:
                        with patch(
                            "app.modules.server.application.runtime_reconciliation.os.popen",
                        ):
                            with patch(
                                "app.modules.server.application.runtime_reconciliation._find_all_java_pids",
                                return_value=[],
                            ):
                                actions = await reconcile_orphans()

        assert len(actions) == 1
        assert actions[0]["type"] == "orphan_tmux_skipped"
        assert actions[0]["reason"] == "not-project-owned"
        mock_kill.assert_not_called()

    async def test_kills_orphan_java_pids_system_wide(self):
        with (
            patch(
                "app.modules.server.application.runtime_reconciliation._find_all_tmux_sessions",
                return_value=[],
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation._find_all_java_pids",
                return_value=[9999, 8888],
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation._is_minecraft_java_pid",
                return_value=True,
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation.os.kill",
            ) as mock_kill,
        ):
            actions = await reconcile_orphans(scope="system_wide")

        assert len(actions) == 2
        assert all(a["type"] == "orphan_java" for a in actions)
        killed_pids = {a["pid"] for a in actions}
        assert killed_pids == {9999, 8888}
        mock_kill.assert_any_call(9999, signal.SIGTERM)
        mock_kill.assert_any_call(8888, signal.SIGTERM)

    async def test_skips_non_owned_java_in_project_scope(self):
        with patch(
            "app.modules.server.application.runtime_reconciliation._find_all_tmux_sessions",
            return_value=[],
        ):
            with patch(
                "app.modules.server.application.runtime_reconciliation._find_all_java_pids",
                return_value=[9999],
            ):
                with patch(
                    "app.modules.server.application.runtime_reconciliation._is_minecraft_java_pid",
                    return_value=True,
                ):
                    with patch(
                        "app.modules.server.application.runtime_reconciliation._is_project_owned_process",
                        return_value=False,
                    ):
                        with patch(
                            "app.modules.server.application.runtime_reconciliation.os.kill",
                        ) as mock_kill:
                            actions = await reconcile_orphans()

        assert actions == []
        mock_kill.assert_not_called()

    async def test_kills_orphan_java_pids_project_owned(self):
        with patch(
            "app.modules.server.application.runtime_reconciliation._find_all_tmux_sessions",
            return_value=[],
        ):
            with patch(
                "app.modules.server.application.runtime_reconciliation._find_all_java_pids",
                return_value=[9999],
            ):
                with patch(
                    "app.modules.server.application.runtime_reconciliation._is_minecraft_java_pid",
                    return_value=True,
                ):
                    with patch(
                        "app.modules.server.application.runtime_reconciliation._is_project_owned_process",
                        return_value=True,
                    ):
                        with patch(
                            "app.modules.server.application.runtime_reconciliation.os.kill",
                        ) as mock_kill:
                            actions = await reconcile_orphans()

        assert len(actions) == 1
        assert actions[0]["type"] == "orphan_java"
        assert actions[0]["pid"] == 9999
        mock_kill.assert_any_call(9999, signal.SIGTERM)

    async def test_skips_running_server_tmux(self):
        server = _make_server("srv-running", ServerStatus.RUNNING)
        server._runtime = RuntimeInfo(
            status="running",
            pid=7777,
            external_id="",
        )

        mock_repo = AsyncMock(spec=ServerRepository)
        mock_repo.list = AsyncMock(
            side_effect=[
                [server],
                [],
            ]
        )

        with patch(
            "app.modules.server.application.runtime_reconciliation._find_all_tmux_sessions",
            return_value=["onx-srv-running", "onx-actual-orphan"],
        ):
            with patch(
                "app.modules.server.application.runtime_reconciliation._get_tmux_pid",
                return_value=12345,
            ):
                with patch(
                    "app.modules.server.application.runtime_reconciliation._is_project_owned_process",
                    return_value=True,
                ):
                    with patch(
                        "app.modules.server.application.runtime_reconciliation.os.kill",
                    ) as mock_kill:
                        with patch(
                            "app.modules.server.application.runtime_reconciliation.os.popen",
                        ):
                            with patch(
                                "app.modules.server.application.runtime_reconciliation.subprocess.run",
                            ):
                                with patch(
                                    "app.modules.server.application.runtime_reconciliation._find_all_java_pids",
                                    return_value=[],
                                ):
                                    actions = await reconcile_orphans(mock_repo)

        assert len(actions) == 1
        assert actions[0]["session"] == "onx-actual-orphan"
        mock_kill.assert_any_call(12345, signal.SIGTERM)
        assert mock_repo.list.call_count == 2

    async def test_reconcile_orphans_aborts_when_repository_raises(self):
        mock_repo = AsyncMock(spec=ServerRepository)
        mock_repo.list = AsyncMock(side_effect=RuntimeError("Database query failed"))

        with (
            patch(
                "app.modules.server.application.runtime_reconciliation._find_all_tmux_sessions",
                return_value=["onx-potential-orphan"],
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation._get_tmux_pid",
                return_value=12345,
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation._is_project_owned_process",
                return_value=True,
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation.os.kill",
            ) as mock_kill,
            patch(
                "app.modules.server.application.runtime_reconciliation.platform_force_kill",
            ) as mock_force_kill,
            patch(
                "app.modules.server.application.runtime_reconciliation._find_all_java_pids",
                return_value=[9999],
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation._is_minecraft_java_pid",
                return_value=True,
            ),
        ):
            actions = await reconcile_orphans(mock_repo)

        assert actions == []
        mock_kill.assert_not_called()
        mock_force_kill.assert_not_called()

    async def test_skips_running_server_tmux_by_external_id(self):
        server = _make_server("srv-custom", ServerStatus.RUNNING)
        server._runtime = RuntimeInfo(
            status="running",
            pid=7777,
            external_id="my-custom-session",
        )

        mock_repo = AsyncMock(spec=ServerRepository)
        mock_repo.list = AsyncMock(
            side_effect=[
                [server],
                [],
            ]
        )

        with patch(
            "app.modules.server.application.runtime_reconciliation._find_all_tmux_sessions",
            return_value=["my-custom-session", "onx-actual-orphan-2"],
        ):
            with patch(
                "app.modules.server.application.runtime_reconciliation._get_tmux_pid",
                return_value=9999,
            ):
                with patch(
                    "app.modules.server.application.runtime_reconciliation._is_project_owned_process",
                    return_value=True,
                ):
                    with patch(
                        "app.modules.server.application.runtime_reconciliation.os.kill",
                    ) as mock_kill:
                        with patch(
                            "app.modules.server.application.runtime_reconciliation.os.popen",
                        ):
                            with patch(
                                "app.modules.server.application.runtime_reconciliation.subprocess.run",
                            ):
                                with patch(
                                    "app.modules.server.application.runtime_reconciliation._find_all_java_pids",
                                    return_value=[],
                                ):
                                    actions = await reconcile_orphans(mock_repo)

        assert len(actions) == 1
        assert actions[0]["session"] == "onx-actual-orphan-2"
        mock_kill.assert_any_call(9999, signal.SIGTERM)

    async def test_skips_running_server_java_pid(self):
        server = _make_server("srv-java", ServerStatus.RUNNING)
        server._runtime = RuntimeInfo(
            status="running",
            pid=7777,
            external_id="",
        )

        mock_repo = AsyncMock(spec=ServerRepository)
        mock_repo.list = AsyncMock(
            side_effect=[
                [server],
                [],
            ]
        )

        with patch(
            "app.modules.server.application.runtime_reconciliation._find_all_tmux_sessions",
            return_value=["onx-srv-java"],
        ):
            with patch(
                "app.modules.server.application.runtime_reconciliation._find_all_java_pids",
                return_value=[7777, 9999],
            ):
                with patch(
                    "app.modules.server.application.runtime_reconciliation._is_minecraft_java_pid",
                    return_value=True,
                ):
                    with patch(
                        "app.modules.server.application.runtime_reconciliation._is_project_owned_process",
                        return_value=True,
                    ):
                        with patch(
                            "app.modules.server.application.runtime_reconciliation.os.kill",
                        ) as mock_kill:
                            with patch(
                                "app.modules.server.application.runtime_reconciliation.os.popen",
                            ):
                                actions = await reconcile_orphans(mock_repo)

        assert len(actions) == 1
        assert actions[0]["type"] == "orphan_java"
        assert actions[0]["pid"] == 9999
        mock_kill.assert_any_call(9999, signal.SIGTERM)

    async def test_kills_stopped_server_tmux(self):
        server = _make_server("srv-stopped", ServerStatus.STOPPED)

        mock_repo = AsyncMock(spec=ServerRepository)
        mock_repo.list = AsyncMock(
            side_effect=[
                [],
                [],
            ]
        )

        with patch(
            "app.modules.server.application.runtime_reconciliation._find_all_tmux_sessions",
            return_value=["onx-srv-stopped"],
        ):
            with patch(
                "app.modules.server.application.runtime_reconciliation._get_tmux_pid",
                return_value=5555,
            ):
                with patch(
                    "app.modules.server.application.runtime_reconciliation._is_project_owned_process",
                    return_value=True,
                ):
                    with patch(
                        "app.modules.server.application.runtime_reconciliation.os.kill",
                    ) as mock_kill:
                        with patch(
                            "app.modules.server.application.runtime_reconciliation.os.popen",
                        ):
                            with patch(
                                "app.modules.server.application.runtime_reconciliation.subprocess.run",
                            ):
                                with patch(
                                    "app.modules.server.application.runtime_reconciliation._find_all_java_pids",
                                    return_value=[],
                                ):
                                    actions = await reconcile_orphans(mock_repo)

        assert len(actions) == 1
        assert actions[0]["session"] == "onx-srv-stopped"
        mock_kill.assert_any_call(5555, signal.SIGTERM)

    async def test_fail_gracefully_on_ownership_check_exception(self):
        with patch(
            "app.modules.server.application.runtime_reconciliation._find_all_tmux_sessions",
            return_value=["onx-broken-pid"],
        ):
            with patch(
                "app.modules.server.application.runtime_reconciliation._get_tmux_pid",
                return_value=12345,
            ):
                with patch(
                    "app.modules.server.application.runtime_reconciliation._is_project_owned_process",
                    side_effect=PermissionError("mock permission denied"),
                ):
                    with patch(
                        "app.modules.server.application.runtime_reconciliation.os.kill",
                    ) as mock_kill:
                        with patch(
                            "app.modules.server.application.runtime_reconciliation.os.popen",
                        ):
                            with patch(
                                "app.modules.server.application.runtime_reconciliation._find_all_java_pids",
                                return_value=[],
                            ):
                                actions = await reconcile_orphans()

        assert len(actions) == 1
        assert actions[0]["type"] == "orphan_tmux_skipped"
        assert "error" in actions[0]["reason"]
        mock_kill.assert_not_called()

    async def test_fail_gracefully_on_java_ownership_check_exception(self):
        with patch(
            "app.modules.server.application.runtime_reconciliation._find_all_tmux_sessions",
            return_value=[],
        ):
            with patch(
                "app.modules.server.application.runtime_reconciliation._find_all_java_pids",
                return_value=[4444],
            ):
                with patch(
                    "app.modules.server.application.runtime_reconciliation._is_minecraft_java_pid",
                    return_value=True,
                ):
                    with patch(
                        "app.modules.server.application.runtime_reconciliation._is_project_owned_process",
                        side_effect=PermissionError("mock permission denied"),
                    ):
                        with patch(
                            "app.modules.server.application.runtime_reconciliation.os.kill",
                        ) as mock_kill:
                            actions = await reconcile_orphans()

        assert actions == []
        mock_kill.assert_not_called()

    async def test_system_wide_kills_without_ownership_check(self):
        with (
            patch(
                "app.modules.server.application.runtime_reconciliation._find_all_tmux_sessions",
                return_value=["onx-orphan"],
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation._get_tmux_pid",
                return_value=12345,
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation.os.kill",
            ) as mock_kill,
            patch(
                "app.modules.server.application.runtime_reconciliation.os.popen",
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation.subprocess.run",
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation._find_all_java_pids",
                return_value=[],
            ),
        ):
            actions = await reconcile_orphans(scope="system_wide")

        assert len(actions) == 1
        assert actions[0]["type"] == "orphan_tmux"
        mock_kill.assert_any_call(12345, signal.SIGTERM)  # no ownership check needed

    async def test_audit_log_produced_for_kill_decision(self):
        with (
            patch(
                "app.modules.server.application.runtime_reconciliation._find_all_tmux_sessions",
                return_value=["onx-orphan"],
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation._get_tmux_pid",
                return_value=12345,
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation._is_project_owned_process",
                return_value=True,
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation.os.kill",
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation.os.popen",
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation.subprocess.run",
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation._find_all_java_pids",
                return_value=[],
            ),
            patch(
                "app.modules.server.application.runtime_reconciliation.logger.info",
            ) as mock_log_info,
        ):
            await reconcile_orphans()
            kill_logs = [
                args
                for args, _ in mock_log_info.call_args_list
                if "KILL_DECISION" in str(args)
            ]
            assert len(kill_logs) >= 1
            assert all(
                "decision=KILL" in str(args) or "decision=SKIP" in str(args)
                for args in kill_logs
            )


class TestRuntimeReconciliationGraceWindow:
    def test_scenario_1_fresh_posix_start_no_crash_mismatch(self):
        # 1. Fresh POSIX start (<60s, STARTING): has_tmux=True, pid_alive=True -> no crash mismatch
        state = ServerRuntimeState(
            server_id="s1",
            server_name="S1",
            db_status=ServerStatus.STARTING,
            has_supervisor=False,
            supervisor_running=False,
            has_tmux=True,
            tmux_pid=1001,
            pid_alive=True,
            start_age_seconds=15.0,
        )
        mismatches = _detect_mismatches(state)
        assert len(mismatches) == 1
        assert mismatches[0].mismatch_type == MismatchType.DB_STARTING_ALIVE

    def test_scenario_2_healthy_running_no_mismatches(self):
        # 2. Healthy RUNNING: has_tmux=True, pid_alive=True -> no crash mismatch
        state = ServerRuntimeState(
            server_id="s1",
            server_name="S1",
            db_status=ServerStatus.RUNNING,
            has_supervisor=True,
            supervisor_running=True,
            has_tmux=True,
            tmux_pid=1001,
            pid_alive=True,
            running_age_seconds=100.0,
        )
        mismatches = _detect_mismatches(state)
        assert len(mismatches) == 0

    def test_scenario_3_running_tmux_dead_jvm_alive_no_crash_mismatch(self):
        # 3. RUNNING, tmux dead but JVM still alive: has_tmux=False, pid_alive=True
        # -> SUPERVISOR_NO_TMUX only, no DB_RUNNING_NO_TMUX
        state = ServerRuntimeState(
            server_id="s1",
            server_name="S1",
            db_status=ServerStatus.RUNNING,
            has_supervisor=True,
            supervisor_running=True,
            has_tmux=False,
            tmux_pid=None,
            pid_alive=True,
            running_age_seconds=100.0,
        )
        mismatches = _detect_mismatches(state)
        types = [m.mismatch_type for m in mismatches]
        assert MismatchType.SUPERVISOR_NO_TMUX in types
        assert MismatchType.DB_RUNNING_NO_TMUX not in types

    def test_scenario_4_running_in_grace_tmux_dead_pid_dead_protected(self):
        # 4. RUNNING, just transitioned (<30s via running_start_time), tmux dead, PID dead:
        # running_age_seconds small, in_grace=True -> no DB_RUNNING_NO_TMUX mismatch
        # but SUPERVISOR_NO_TMUX mismatch still fires
        state = ServerRuntimeState(
            server_id="s1",
            server_name="S1",
            db_status=ServerStatus.RUNNING,
            has_supervisor=True,
            supervisor_running=True,
            has_tmux=False,
            tmux_pid=None,
            pid_alive=False,
            running_age_seconds=10.0,  # in grace (< 30.0)
        )
        mismatches = _detect_mismatches(state)
        types = [m.mismatch_type for m in mismatches]
        assert MismatchType.SUPERVISOR_NO_TMUX in types
        assert MismatchType.DB_RUNNING_NO_TMUX not in types

    def test_scenario_5_running_past_grace_tmux_dead_pid_dead_crashes(self):
        # 5. RUNNING, stable (well past grace window), tmux dead, PID dead:
        # in_grace=False -> DB_RUNNING_NO_TMUX mismatch generated
        state = ServerRuntimeState(
            server_id="s1",
            server_name="S1",
            db_status=ServerStatus.RUNNING,
            has_supervisor=True,
            supervisor_running=True,
            has_tmux=False,
            tmux_pid=None,
            pid_alive=False,
            running_age_seconds=45.0,  # past grace (> 30.0)
        )
        mismatches = _detect_mismatches(state)
        types = [m.mismatch_type for m in mismatches]
        assert MismatchType.SUPERVISOR_NO_TMUX in types
        assert MismatchType.DB_RUNNING_NO_TMUX in types

    def test_scenario_6_running_start_time_none_fail_safe_not_in_grace(self):
        # 6. running_start_time is None -> running_age_seconds is None -> in_grace is False
        state = ServerRuntimeState(
            server_id="s1",
            server_name="S1",
            db_status=ServerStatus.RUNNING,
            has_supervisor=True,
            supervisor_running=True,
            has_tmux=False,
            tmux_pid=None,
            pid_alive=False,
            running_age_seconds=None,
        )
        mismatches = _detect_mismatches(state)
        types = [m.mismatch_type for m in mismatches]
        assert MismatchType.SUPERVISOR_NO_TMUX in types
        assert MismatchType.DB_RUNNING_NO_TMUX in types

    def test_scenario_7_custom_post_running_grace_setting_respected(self):
        # 7. Confirm post_running_grace_seconds setting is respected (shifts boundary)
        state = ServerRuntimeState(
            server_id="s1",
            server_name="S1",
            db_status=ServerStatus.RUNNING,
            has_supervisor=True,
            supervisor_running=True,
            has_tmux=False,
            tmux_pid=None,
            pid_alive=False,
            running_age_seconds=40.0,
        )
        # Default 30s grace -> 40s is out of grace
        with patch(
            "app.modules.server.application.runtime_reconciliation._get_post_running_grace_seconds",
            return_value=30.0,
        ):
            mismatches = _detect_mismatches(state)
            types = [m.mismatch_type for m in mismatches]
            assert MismatchType.DB_RUNNING_NO_TMUX in types

        # Custom 50s grace -> 40s is in grace
        with patch(
            "app.modules.server.application.runtime_reconciliation._get_post_running_grace_seconds",
            return_value=50.0,
        ):
            mismatches = _detect_mismatches(state)
            types = [m.mismatch_type for m in mismatches]
            assert MismatchType.DB_RUNNING_NO_TMUX not in types

    @pytest.mark.asyncio
    async def test_scenario_8_get_server_state_computes_start_age_and_running_age(self):
        # 8. Explicitly test datetime.fromtimestamp fix and running_age_seconds computation
        now_ts = 1700000100
        start_ts = 1700000050  # 50 seconds ago

        server_starting = _make_server("s-starting", ServerStatus.STARTING)
        server_starting._runtime = RuntimeInfo(
            status="starting",
            start_time=start_ts,
            running_start_time=None,
        )

        mock_provider = AsyncMock()
        mock_provider.verify_process.return_value = False
        mock_provider.get_runtime_pid.return_value = None

        with patch("app.modules.server.application.runtime_reconciliation.datetime") as mock_dt:
            from datetime import UTC
            from datetime import datetime as real_dt

            mock_dt.fromtimestamp = real_dt.fromtimestamp
            mock_dt.now.return_value = real_dt.fromtimestamp(now_ts, tz=UTC)
            mock_dt.fromisoformat.side_effect = ValueError("Should not be called")

            state_starting = await _get_server_state(server_starting, mock_provider)
            assert state_starting.start_age_seconds == pytest.approx(50.0, 0.1)
            assert state_starting.running_age_seconds is None

        # RUNNING server
        server_running = _make_server("s-running", ServerStatus.RUNNING)
        server_running._runtime = RuntimeInfo(
            status="running",
            start_time=start_ts,
            running_start_time=float(start_ts + 10),
        )

        with patch(
            "app.modules.server.application.runtime_reconciliation.time.time",
            return_value=float(now_ts),
        ):
            state_running = await _get_server_state(server_running, mock_provider)
            assert state_running.running_age_seconds == pytest.approx(40.0, 0.1)
