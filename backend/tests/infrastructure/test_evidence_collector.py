from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from app.modules.health.infrastructure.evidence_collector import LogBasedEvidenceCollector

pytestmark = pytest.mark.asyncio


class TestLogBasedEvidenceCollector:
    async def test_collect_returns_bundle_with_evidence_id(self):
        collector = LogBasedEvidenceCollector()
        bundle = await collector.collect("srv-1", "/nonexistent")
        assert bundle.server_id == "srv-1"
        assert bundle.evidence_id
        assert len(bundle.evidence_id) == 32

    async def test_collect_missing_directory_returns_error(self):
        collector = LogBasedEvidenceCollector()
        bundle = await collector.collect("srv-1", "/tmp/does-not-exist-12345")
        assert "Server directory not found" in " ".join(bundle.collection_errors)

    async def test_reads_latest_log_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            srv_dir = Path(tmp)
            log_dir = srv_dir / "logs"
            log_dir.mkdir()
            (log_dir / "latest.log").write_text("line1\nline2\nline3\n")

            collector = LogBasedEvidenceCollector()
            bundle = await collector.collect("srv-1", str(srv_dir))

            assert bundle.latest_log_tail == ["line1", "line2", "line3"]

    async def test_respects_max_log_lines(self):
        collector = LogBasedEvidenceCollector()
        with tempfile.TemporaryDirectory() as tmp:
            srv_dir = Path(tmp)
            log_dir = srv_dir / "logs"
            log_dir.mkdir()
            lines = [f"line{i}" for i in range(250)]
            (log_dir / "latest.log").write_text("\n".join(lines))

            bundle = await collector.collect("srv-1", str(srv_dir))

        assert len(bundle.latest_log_tail) == collector.MAX_LOG_LINES

    async def test_reads_crash_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            srv_dir = Path(tmp)
            crash_dir = srv_dir / "crash-reports"
            crash_dir.mkdir()
            (crash_dir / "crash-2025-01-01.txt").write_text("OutOfMemoryError")

            collector = LogBasedEvidenceCollector()
            bundle = await collector.collect("srv-1", str(srv_dir))

        assert len(bundle.crash_reports) == 1
        assert bundle.crash_reports[0]["filename"] == "crash-2025-01-01.txt"
        assert "OutOfMemoryError" in bundle.crash_reports[0]["content"]

    async def test_ignores_non_txt_in_crash_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            srv_dir = Path(tmp)
            crash_dir = srv_dir / "crash-reports"
            crash_dir.mkdir()
            (crash_dir / "crash.log").write_text("data")
            (crash_dir / "hs_err_pid123.log").write_text("data")

            collector = LogBasedEvidenceCollector()
            bundle = await collector.collect("srv-1", str(srv_dir))

        assert len(bundle.crash_reports) == 0

    async def test_reads_provider_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            srv_dir = Path(tmp)
            diag = {"failure_code": "MEMORY_EXHAUSTED", "exit_code": 137}
            (srv_dir / ".provider-diagnostics.json").write_text(json.dumps(diag))

            collector = LogBasedEvidenceCollector()
            bundle = await collector.collect("srv-1", str(srv_dir))

        assert bundle.provider_diagnostics is not None
        assert bundle.provider_diagnostics["failure_code"] == "MEMORY_EXHAUSTED"

    async def test_empty_server_dir_produces_minimal_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            collector = LogBasedEvidenceCollector()
            bundle = await collector.collect("srv-1", str(tmp))

        assert bundle.latest_log_tail == []
        assert bundle.crash_reports == []
        assert bundle.collection_errors == []

    async def test_system_snapshot_contains_disk_info(self, tmp_path: Path):
        collector = LogBasedEvidenceCollector()
        bundle = await collector.collect("srv-1", str(tmp_path))
        snapshot = bundle.system_snapshot

        assert "disk_total_gb" in snapshot
        assert "disk_free_gb" in snapshot
        assert "captured_at" in snapshot

    async def test_crash_reports_respects_max_count(self):
        collector = LogBasedEvidenceCollector()
        with tempfile.TemporaryDirectory() as tmp:
            srv_dir = Path(tmp)
            crash_dir = srv_dir / "crash-reports"
            crash_dir.mkdir()
            for i in range(10):
                (crash_dir / f"crash-{i}.txt").write_text(f"crash {i}")

            bundle = await collector.collect("srv-1", str(srv_dir))

        assert len(bundle.crash_reports) == collector.MAX_CRASH_REPORTS

    async def test_captures_host_environment_via_scanner(self, tmp_path: Path):
        collector = LogBasedEvidenceCollector()
        bundle = await collector.collect("srv-1", str(tmp_path))
        snapshot = bundle.system_snapshot

        assert "host_environment" in snapshot

    async def test_missing_log_dir_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            collector = LogBasedEvidenceCollector()
            bundle = await collector.collect("srv-1", str(tmp))

        assert bundle.latest_log_tail == []
