from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.modules.health.domain.value_objects import IntegrityCheck
from app.modules.health.infrastructure.integrity import (
    FilesystemIntegrityChecker,
    _check_jar,
    _compute_overall,
)


def _make_server_dir(tmp: str, server_id: str) -> Path:
    srvd = Path(tmp) / server_id
    srvd.mkdir(parents=True, exist_ok=True)
    return srvd


class TestFilesystemIntegrityChecker:
    async def test_missing_directory(self):
        checker = FilesystemIntegrityChecker()
        report = await checker.check("nonexistent-server-id")
        assert report.overall_status == "fail"
        assert any(c.check_name == "server_directory" for c in report.checks)

    async def test_healthy_server(self):
        checker = FilesystemIntegrityChecker()
        with tempfile.TemporaryDirectory() as tmp:
            srvd = _make_server_dir(tmp, "srv-healthy")
            (srvd / "server.jar").write_text("fake jar")
            (srvd / "server.properties").write_text(
                "server-port=25565\nlevel-name=world\ngamemode=survival\n"
            )
            (srvd / "eula.txt").write_text("eula=true")
            (srvd / "world").mkdir()
            (srvd / "world" / "level.dat").write_text("binary")

            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(
                    "app.modules.health.infrastructure.integrity._resolve_path",
                    lambda _, root_path=None: srvd,
                )
                report = await checker.check("srv-healthy")

        assert report.overall_status == "pass"

    async def test_missing_server_jar(self):
        checker = FilesystemIntegrityChecker()
        with tempfile.TemporaryDirectory() as tmp:
            srvd = _make_server_dir(tmp, "srv-nojar")
            (srvd / "server.properties").write_text("server-port=25565\n")
            (srvd / "world").mkdir()

            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(
                    "app.modules.health.infrastructure.integrity._resolve_path",
                    lambda _, root_path=None: srvd,
                )
                report = await checker.check("srv-nojar")

        assert report.overall_status == "fail"
        assert any(c.check_name == "server_jar" and c.status == "fail" for c in report.checks)

    async def test_forge_run_sh_layout_passes(self):
        checker = FilesystemIntegrityChecker()
        with tempfile.TemporaryDirectory() as tmp:
            srvd = _make_server_dir(tmp, "srv-forge")
            (srvd / "run.sh").write_text("#!/usr/bin/env bash\n")
            (srvd / "libraries").mkdir()
            (srvd / "server.properties").write_text("server-port=25565\n")

            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(
                    "app.modules.health.infrastructure.integrity._resolve_path",
                    lambda _sid, _root_path=None: srvd,
                )
                report = await checker.check("srv-forge")

        assert report.overall_status != "fail"
        assert any(c.check_name == "server_jar" and c.status == "pass" for c in report.checks)

    async def test_no_jar_and_no_run_sh_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            srvd = _make_server_dir(tmp, "srv-incomplete")
            reports: list[IntegrityCheck] = []
            _check_jar(srvd, reports)
        assert reports[0].status == "fail"
        assert "run.sh" in reports[0].detail

    async def test_quick_scope_skips_disk_check(self):
        checker = FilesystemIntegrityChecker()
        with tempfile.TemporaryDirectory() as tmp:
            srvd = _make_server_dir(tmp, "srv-quick")
            (srvd / "server.jar").write_text("")
            (srvd / "server.properties").write_text("server-port=25565\n")
            (srvd / "world").mkdir()

            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(
                    "app.modules.health.infrastructure.integrity._resolve_path",
                    lambda _, root_path=None: srvd,
                )
                report = await checker.check("srv-quick", scope="quick")

        check_names = [c.check_name for c in report.checks]
        assert "disk_space" not in check_names


class TestComputeOverall:
    def test_pass_when_all_pass(self):
        checks = [
            IntegrityCheck(check_name="a", severity="critical", status="pass"),
            IntegrityCheck(check_name="b", severity="warning", status="pass"),
        ]
        assert _compute_overall(checks) == "pass"

    def test_warn_on_warning(self):
        checks = [
            IntegrityCheck(check_name="a", severity="critical", status="pass"),
            IntegrityCheck(check_name="b", severity="warning", status="warn"),
        ]
        assert _compute_overall(checks) == "warn"

    def test_fail_on_critical_fail(self):
        checks = [
            IntegrityCheck(check_name="a", severity="critical", status="fail"),
            IntegrityCheck(check_name="b", severity="warning", status="pass"),
        ]
        assert _compute_overall(checks) == "fail"
