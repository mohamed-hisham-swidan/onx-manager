from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.modules.health.domain.value_objects import (
    HealthSignal,
    HealthStatusEnum,
    HealthTrend,
    SignalSeverity,
)
from app.modules.health.infrastructure.health_calculator import SignalHealthCalculator


pytestmark = pytest.mark.asyncio


def _signal(
    stype: str = "test",
    severity: str = "info",
    value: str = "ok",
    seconds_ago: float = 10.0,
) -> HealthSignal:
    return HealthSignal(
        server_id="srv-1",
        signal_type=stype,
        severity=SignalSeverity(severity),
        value=value,
        timestamp=datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() - seconds_ago,
            tz=timezone.utc,
        ),
    )


class TestSignalHealthCalculator:
    async def test_no_signals_keeps_healthy(self):
        calc = SignalHealthCalculator()
        result = await calc.compute(HealthStatusEnum.HEALTHY, [])
        assert result[0] == HealthStatusEnum.HEALTHY

    async def test_no_signals_pending_stays_pending(self):
        calc = SignalHealthCalculator()
        result = await calc.compute(HealthStatusEnum.PENDING, [])
        assert result[0] == HealthStatusEnum.PENDING

    async def test_no_signals_unknown_becomes_unknown(self):
        calc = SignalHealthCalculator()
        result = await calc.compute(HealthStatusEnum.UNKNOWN, [])
        assert result[0] == HealthStatusEnum.UNKNOWN

    async def test_single_info_signal_stays_healthy(self):
        calc = SignalHealthCalculator()
        result = await calc.compute(HealthStatusEnum.HEALTHY, [_signal(severity="info")])
        assert result[0] == HealthStatusEnum.HEALTHY

    async def test_single_critical_becomes_critical(self):
        calc = SignalHealthCalculator()
        result = await calc.compute(HealthStatusEnum.HEALTHY, [_signal(severity="critical", value="oom")])
        assert result[0] == HealthStatusEnum.CRITICAL
        assert "Critical" in result[1][0]

    async def test_two_warnings_becomes_warning(self):
        calc = SignalHealthCalculator()
        signals = [
            _signal(severity="warning", value="disk 80%"),
            _signal(severity="warning", value="mem 70%"),
        ]
        result = await calc.compute(HealthStatusEnum.HEALTHY, signals)
        assert result[0] == HealthStatusEnum.WARNING

    async def test_warning_then_critical_becomes_critical(self):
        calc = SignalHealthCalculator()
        signals = [
            _signal(severity="warning", value="disk 80%"),
            _signal(severity="critical", value="mem 10%"),
        ]
        result = await calc.compute(HealthStatusEnum.HEALTHY, signals)
        assert result[0] == HealthStatusEnum.CRITICAL

    async def test_no_skip_healthy_to_broken(self):
        calc = SignalHealthCalculator()
        result = await calc.compute(HealthStatusEnum.HEALTHY, [
            _signal(severity="critical", value="unexpected critical", seconds_ago=5),
            _signal(severity="critical", value="another critical", seconds_ago=5),
        ])
        assert result[0] in (HealthStatusEnum.CRITICAL, HealthStatusEnum.WARNING)
        assert result[0] != HealthStatusEnum.BROKEN

    async def test_warning_to_broken_allowed(self):
        calc = SignalHealthCalculator()
        signals = [_signal(severity="critical", value="fatal")] * 5
        result = await calc.compute(HealthStatusEnum.WARNING, signals)
        assert result[0] == HealthStatusEnum.BROKEN

    async def test_signals_outside_window_ignored(self):
        calc = SignalHealthCalculator()
        signals = [
            _signal(severity="critical", value="old oom", seconds_ago=600),
        ]
        result = await calc.compute(HealthStatusEnum.HEALTHY, signals)
        assert result[0] == HealthStatusEnum.HEALTHY

    async def test_old_but_recent_signal_processes(self):
        calc = SignalHealthCalculator()
        signals = [
            _signal(severity="critical", value="recent oom", seconds_ago=30),
        ]
        result = await calc.compute(HealthStatusEnum.HEALTHY, signals)
        assert result[0] == HealthStatusEnum.CRITICAL

    async def test_confidence_increases_with_critical_signals(self):
        calc = SignalHealthCalculator()
        result1 = await calc.compute(HealthStatusEnum.HEALTHY, [_signal(severity="info")])
        result2 = await calc.compute(HealthStatusEnum.HEALTHY, [
            _signal(severity="critical", value="oom", seconds_ago=5),
            _signal(severity="critical", value="port", seconds_ago=5),
        ])
        assert result2[2] > result1[2]

    async def test_factors_includes_critical_signals(self):
        calc = SignalHealthCalculator()
        signals = [
            _signal(stype="memory", severity="critical", value="exhausted"),
            _signal(stype="port", severity="critical", value="conflict"),
        ]
        result = await calc.compute(HealthStatusEnum.HEALTHY, signals)
        factors_text = " ".join(result[1])
        assert "memory" in factors_text.lower() or "port" in factors_text.lower() or "critical" in factors_text.lower()

    async def test_trend_improving(self):
        calc = SignalHealthCalculator()
        signals = [
            _signal(severity="critical", value="old", seconds_ago=200),
            _signal(severity="info", value="new", seconds_ago=10),
        ]
        result = await calc.compute(HealthStatusEnum.CRITICAL, signals)
        assert result[3] == HealthTrend.IMPROVING

    async def test_trend_declining(self):
        calc = SignalHealthCalculator()
        signals = [
            _signal(severity="info", value="old", seconds_ago=200),
            _signal(severity="critical", value="new problem", seconds_ago=10),
        ]
        result = await calc.compute(HealthStatusEnum.WARNING, signals)
        assert result[3] == HealthTrend.DECLINING

    async def test_trend_stable(self):
        calc = SignalHealthCalculator()
        signals = [
            _signal(severity="info", value="one", seconds_ago=200),
            _signal(severity="info", value="two", seconds_ago=100),
        ]
        result = await calc.compute(HealthStatusEnum.HEALTHY, signals)
        assert result[3] == HealthTrend.STABLE

    async def test_status_score_healthy_lowest(self):
        assert SignalHealthCalculator.status_score(HealthStatusEnum.HEALTHY) == 0
        assert SignalHealthCalculator.status_score(HealthStatusEnum.BROKEN) == 3

    async def test_info_signals_do_not_upgrade_status(self):
        calc = SignalHealthCalculator()
        signals = [_signal(severity="info") for _ in range(10)]
        result = await calc.compute(HealthStatusEnum.HEALTHY, signals)
        assert result[0] == HealthStatusEnum.HEALTHY

    async def test_mixed_severity_with_predominant_warnings(self):
        calc = SignalHealthCalculator()
        signals = [
            _signal(severity="warning", value="cpu 90%"),
            _signal(severity="warning", value="disk 85%"),
            _signal(severity="info", value="normal"),
        ]
        result = await calc.compute(HealthStatusEnum.HEALTHY, signals)
        assert result[0] == HealthStatusEnum.WARNING

    async def test_empty_signals_with_warning_current_status(self):
        calc = SignalHealthCalculator()
        result = await calc.compute(HealthStatusEnum.WARNING, [])
        assert result[0] == HealthStatusEnum.UNKNOWN

    async def test_transition_from_critical_to_broken(self):
        calc = SignalHealthCalculator()
        signals = [_signal(severity="critical", value="fatal", seconds_ago=5)] * 4
        result = await calc.compute(HealthStatusEnum.CRITICAL, signals)
        assert result[0] == HealthStatusEnum.BROKEN

    async def test_confidence_does_not_exceed_099(self):
        calc = SignalHealthCalculator()
        signals = [_signal(severity="critical", value="x") for _ in range(50)]
        result = await calc.compute(HealthStatusEnum.HEALTHY, signals)
        assert result[2] <= 0.99
