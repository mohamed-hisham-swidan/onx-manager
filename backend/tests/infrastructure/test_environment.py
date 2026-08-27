from __future__ import annotations

import pytest

from app.modules.health.infrastructure.environment import (
    HostEnvironmentScanner,
    _check_disk_space,
    _check_memory,
    _get_load_average,
)


class TestHostEnvironmentScanner:
    @pytest.mark.asyncio
    async def test_scan_returns_report(self):
        scanner = HostEnvironmentScanner()
        report = await scanner.scan()

        assert report.timestamp is not None
        assert isinstance(report.available_disk_mb, float)
        assert isinstance(report.available_memory_mb, float)
        assert isinstance(report.java_versions, list)
        assert isinstance(report.prerequisites, dict)

    @pytest.mark.asyncio
    async def test_scan_with_server_id(self):
        scanner = HostEnvironmentScanner()
        report = await scanner.scan(server_id="test-srv")
        assert report is not None


class TestDiskSpace:
    def test_returns_float(self):
        free = _check_disk_space()
        assert isinstance(free, float)
        assert free >= 0


class TestMemory:
    def test_returns_float(self):
        mem = _check_memory()
        assert isinstance(mem, float)


class TestLoadAverage:
    def test_returns_float(self):
        load = _get_load_average()
        assert isinstance(load, float)
        assert load >= 0
