import os
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.server.application.runtime_reconciliation import (
    MismatchType,
    reconcile_all_runtimes,
    reconcile_orphans,
    reconcile_server_runtime,
)
from app.modules.server.application.supervisor import RuntimeSupervisor
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
from app.modules.server.infrastructure.providers.base import (
    ServerHandle,
    ServerRuntimeStatus,
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
        ext_id = f"mcs-{sid}" if with_external_id else ""
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

        with patch(
            "app.modules.server.application.runtime_reconciliation.provider_factory.get",
            return_value=_mock_provider(verify_process=True, tmux_pid=100),
        ):
            with patch(
                "app.modules.server.application.runtime_reconciliation.os.kill",
                return_value=None,
            ):
                with patch(
                    "app.modules.server.application.runtime_reconciliation.RuntimeSupervisor.get_for",
                    return_value=MagicMock(is_running=True),
                ):
                    outcome = await reconcile_server_runtime(server, repo)

        assert len(outcome.mismatches) == 0
        assert outcome.repaired is False

    async def test_running_no_supervisor(self):
        server = _make_server("s2", ServerStatus.RUNNING)
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.save = AsyncMock()

        with patch(
            "app.modules.server.application.runtime_reconciliation.provider_factory.get",
            return_value=_mock_provider(verify_process=True, tmux_pid=100),
        ):
            with patch(
                "app.modules.server.application.runtime_reconciliation.os.kill",
                return_value=None,
            ):
                with patch(
                    "app.modules.server.application.runtime_reconciliation.RuntimeSupervisor.get_for",
                    return_value=None,
                ):
                    outcome = await reconcile_server_runtime(server, repo)

        assert len(outcome.mismatches) >= 1
        types = [m.mismatch_type for m in outcome.mismatches]
        assert MismatchType.DB_RUNNING_NO_SUPERVISOR in types

    async def test_running_no_tmux(self):
        server = _make_server("s3", ServerStatus.RUNNING)
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.save = AsyncMock()

        with patch(
            "app.modules.server.application.runtime_reconciliation.provider_factory.get",
            return_value=_mock_provider(verify_process=False, tmux_pid=None),
        ):
            with patch(
                "app.modules.server.application.runtime_reconciliation.RuntimeSupervisor.get_for",
                return_value=None,
            ):
                outcome = await reconcile_server_runtime(server, repo)

        assert outcome.repaired is True
        repo.save.assert_called_once()
        assert server.status == ServerStatus.CRASHED

    async def test_tmux_pid_dead(self):
        server = _make_server("s4", ServerStatus.RUNNING)
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.save = AsyncMock()

        with patch(
            "app.modules.server.application.runtime_reconciliation.provider_factory.get",
            return_value=_mock_provider(verify_process=True, tmux_pid=999),
        ):
            with patch(
                "app.modules.server.application.runtime_reconciliation.os.kill",
                side_effect=ProcessLookupError,
            ):
                with patch(
                    "app.modules.server.application.runtime_reconciliation.RuntimeSupervisor.get_for",
                    return_value=MagicMock(is_running=True),
                ):
                    outcome = await reconcile_server_runtime(server, repo)

        assert outcome.repaired is True
        assert server.status == ServerStatus.CRASHED

    async def test_supervisor_no_tmux(self):
        server = _make_server("s5", ServerStatus.RUNNING)
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.save = AsyncMock()

        with patch(
            "app.modules.server.application.runtime_reconciliation.provider_factory.get",
            return_value=_mock_provider(verify_process=False, tmux_pid=None),
        ):
            with patch(
                "app.modules.server.application.runtime_reconciliation.RuntimeSupervisor.get_for",
                return_value=MagicMock(is_running=True),
            ):
                with patch(
                    "app.modules.server.application.runtime_reconciliation.RuntimeSupervisor.stop_for",
                    AsyncMock(),
                ) as mock_stop:
                    outcome = await reconcile_server_runtime(server, repo)

        assert outcome.repaired is True
        mock_stop.assert_awaited_once_with("s5")

    async def test_starting_but_alive(self):
        server = _make_server("s6", ServerStatus.STARTING, pid=None)
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.save = AsyncMock()

        with patch(
            "app.modules.server.application.runtime_reconciliation.provider_factory.get",
            return_value=_mock_provider(verify_process=True, tmux_pid=200),
        ):
            with patch(
                "app.modules.server.application.runtime_reconciliation.os.kill",
                return_value=None,
            ):
                with patch(
                    "app.modules.server.application.runtime_reconciliation._port_is_listening",
                    return_value=True,
                ):
                    with patch(
                        "app.modules.server.application.runtime_reconciliation.RuntimeSupervisor.get_for",
                        return_value=None,
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

        with patch(
            "app.modules.server.application.runtime_reconciliation.provider_factory.get",
            return_value=_mock_provider(verify_process=True, tmux_pid=100),
        ):
            with patch(
                "app.modules.server.application.runtime_reconciliation.os.kill",
                return_value=None,
            ):
                with patch(
                    "app.modules.server.application.runtime_reconciliation.RuntimeSupervisor.get_for",
                    return_value=MagicMock(is_running=True),
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
        repo.get = AsyncMock(side_effect=lambda sid: next(s for s in servers if str(s.id) == str(sid)))
        repo.save = AsyncMock()

        with patch(
            "app.modules.server.application.runtime_reconciliation.provider_factory.get",
            return_value=_mock_provider(verify_process=True, tmux_pid=100),
        ):
            with patch(
                "app.modules.server.application.runtime_reconciliation.os.kill",
                return_value=None,
            ):
                with patch(
                    "app.modules.server.application.runtime_reconciliation.RuntimeSupervisor.get_for",
                    return_value=MagicMock(is_running=True),
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
    async def test_no_orphans(self):
        with patch(
            "app.modules.server.application.runtime_reconciliation._find_all_tmux_sessions",
            return_value=[],
        ):
            with patch(
                "app.modules.server.application.runtime_reconciliation._find_all_java_pids",
                return_value=[],
            ):
                actions = await reconcile_orphans()

        assert actions == []

    async def test_kills_orphan_tmux_system_wide(self):
        with patch(
            "app.modules.server.application.runtime_reconciliation._find_all_tmux_sessions",
            return_value=["mcs-orphan"],
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
                            "app.modules.server.application.runtime_reconciliation._find_all_java_pids",
                            return_value=[],
                        ):
                            actions = await reconcile_orphans(scope="system_wide")

        assert len(actions) == 1
        assert actions[0]["type"] == "orphan_tmux"
        assert actions[0]["session"] == "mcs-orphan"
        mock_kill.assert_any_call(12345, signal.SIGTERM)

    async def test_kills_orphan_tmux_project_owned(self):
        with patch(
            "app.modules.server.application.runtime_reconciliation._find_all_tmux_sessions",
            return_value=["mcs-orphan"],
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
        assert actions[0]["session"] == "mcs-orphan"
        mock_kill.assert_any_call(12345, signal.SIGTERM)

    async def test_skips_non_owned_tmux_in_project_scope(self):
        with patch(
            "app.modules.server.application.runtime_reconciliation._find_all_tmux_sessions",
            return_value=["mcs-untracked"],
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
        with patch(
            "app.modules.server.application.runtime_reconciliation._find_all_tmux_sessions",
            return_value=[],
        ):
            with patch(
                "app.modules.server.application.runtime_reconciliation._find_all_java_pids",
                return_value=[9999, 8888],
            ):
                with patch(
                    "app.modules.server.application.runtime_reconciliation._is_minecraft_java_pid",
                    return_value=True,
                ):
                    with patch(
                        "app.modules.server.application.runtime_reconciliation.os.kill",
                    ) as mock_kill:
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
        mock_repo.list = AsyncMock(side_effect=[
            [server],
            [],
        ])

        with patch(
            "app.modules.server.application.runtime_reconciliation._find_all_tmux_sessions",
            return_value=["mcs-srv-running", "mcs-actual-orphan"],
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
                                "app.modules.server.application.runtime_reconciliation._find_all_java_pids",
                                return_value=[],
                            ):
                                actions = await reconcile_orphans(mock_repo)

        assert len(actions) == 1
        assert actions[0]["session"] == "mcs-actual-orphan"
        mock_kill.assert_any_call(12345, signal.SIGTERM)
        assert mock_repo.list.call_count == 2

    async def test_skips_running_server_tmux_by_external_id(self):
        server = _make_server("srv-custom", ServerStatus.RUNNING)
        server._runtime = RuntimeInfo(
            status="running",
            pid=7777,
            external_id="my-custom-session",
        )

        mock_repo = AsyncMock(spec=ServerRepository)
        mock_repo.list = AsyncMock(side_effect=[
            [server],
            [],
        ])

        with patch(
            "app.modules.server.application.runtime_reconciliation._find_all_tmux_sessions",
            return_value=["my-custom-session", "mcs-actual-orphan-2"],
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
                                "app.modules.server.application.runtime_reconciliation._find_all_java_pids",
                                return_value=[],
                            ):
                                actions = await reconcile_orphans(mock_repo)

        assert len(actions) == 1
        assert actions[0]["session"] == "mcs-actual-orphan-2"
        mock_kill.assert_any_call(9999, signal.SIGTERM)

    async def test_skips_running_server_java_pid(self):
        server = _make_server("srv-java", ServerStatus.RUNNING)
        server._runtime = RuntimeInfo(
            status="running",
            pid=7777,
            external_id="",
        )

        mock_repo = AsyncMock(spec=ServerRepository)
        mock_repo.list = AsyncMock(side_effect=[
            [server],
            [],
        ])

        with patch(
            "app.modules.server.application.runtime_reconciliation._find_all_tmux_sessions",
            return_value=["mcs-srv-java"],
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
        mock_repo.list = AsyncMock(side_effect=[
            [],
            [],
        ])

        with patch(
            "app.modules.server.application.runtime_reconciliation._find_all_tmux_sessions",
            return_value=["mcs-srv-stopped"],
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
                                "app.modules.server.application.runtime_reconciliation._find_all_java_pids",
                                return_value=[],
                            ):
                                actions = await reconcile_orphans(mock_repo)

        assert len(actions) == 1
        assert actions[0]["session"] == "mcs-srv-stopped"
        mock_kill.assert_any_call(5555, signal.SIGTERM)

    async def test_fail_gracefully_on_ownership_check_exception(self):
        with patch(
            "app.modules.server.application.runtime_reconciliation._find_all_tmux_sessions",
            return_value=["mcs-broken-pid"],
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
        with patch(
            "app.modules.server.application.runtime_reconciliation._find_all_tmux_sessions",
            return_value=["mcs-orphan"],
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
                            "app.modules.server.application.runtime_reconciliation._find_all_java_pids",
                            return_value=[],
                        ):
                            actions = await reconcile_orphans(scope="system_wide")

        assert len(actions) == 1
        assert actions[0]["type"] == "orphan_tmux"
        mock_kill.assert_any_call(12345, signal.SIGTERM)  # no ownership check needed

    async def test_audit_log_produced_for_kill_decision(self):
        with patch(
            "app.modules.server.application.runtime_reconciliation._find_all_tmux_sessions",
            return_value=["mcs-orphan"],
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
                    ):
                        with patch(
                            "app.modules.server.application.runtime_reconciliation.os.popen",
                        ):
                            with patch(
                                "app.modules.server.application.runtime_reconciliation._find_all_java_pids",
                                return_value=[],
                            ):
                                with patch(
                                    "app.modules.server.application.runtime_reconciliation.logger.info",
                                ) as mock_log_info:
                                    await reconcile_orphans()
                                    kill_logs = [args for args, _ in mock_log_info.call_args_list if "KILL_DECISION" in str(args)]
                                    assert len(kill_logs) >= 1
                                    assert all("decision=KILL" in str(args) or "decision=SKIP" in str(args) for args in kill_logs)
