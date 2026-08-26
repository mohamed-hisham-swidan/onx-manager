from __future__ import annotations

import logging
import time
from collections import Counter

from app.modules.health.domain.services import HealthCalculatorService
from app.modules.health.domain.value_objects import (
    HealthSignal,
    HealthStatusEnum,
    HealthTrend,
    SignalSeverity,
)

from app.core.identity import IDENTITY

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.health.calculator")

WINDOW_SECONDS: float = 300.0
RECENT_THRESHOLD: float = 60.0
CRITICAL_SCORE: int = 10
WARNING_SCORE: int = 5


SEVERITY_WEIGHT: dict[str, int] = {
    SignalSeverity.INFO.value: 1,
    SignalSeverity.WARNING.value: 3,
    SignalSeverity.CRITICAL.value: 8,
}

STATUS_SCORE_MAP: list[tuple[float, HealthStatusEnum]] = [
    (CRITICAL_SCORE * 2, HealthStatusEnum.BROKEN),
    (CRITICAL_SCORE, HealthStatusEnum.CRITICAL),
    (WARNING_SCORE, HealthStatusEnum.WARNING),
]

NON_SKIPPABLE: dict[HealthStatusEnum, set[HealthStatusEnum]] = {
    HealthStatusEnum.HEALTHY: {HealthStatusEnum.WARNING, HealthStatusEnum.CRITICAL},
    HealthStatusEnum.WARNING: {HealthStatusEnum.CRITICAL, HealthStatusEnum.BROKEN},
}

TREND_DELTA: float = 0.3


class SignalHealthCalculator(HealthCalculatorService):
    async def compute(
        self,
        current_status: HealthStatusEnum,
        signals: list[HealthSignal],
    ) -> tuple[HealthStatusEnum, list[str], float, str]:
        now = time.time()
        window_signals = [s for s in signals if self._in_window(s, now)]
        if not window_signals:
            if current_status in (HealthStatusEnum.PENDING, HealthStatusEnum.UNKNOWN):
                return current_status, [], 0.0, HealthTrend.STABLE.value
            if current_status == HealthStatusEnum.HEALTHY:
                return current_status, ["No recent signals — status preserved"], 0.6, HealthTrend.STABLE.value
            return HealthStatusEnum.UNKNOWN, ["No signals received within window"], 0.3, HealthTrend.DECLINING.value

        severity_counts: Counter[str] = Counter(s.severity.value for s in window_signals)
        score = self._compute_weighted_score(window_signals, now)
        factors = self._build_factors(window_signals, severity_counts)
        raw_status = self._score_to_status(score, severity_counts)
        final_status = self._apply_transition(current_status, raw_status)
        confidence = self._compute_confidence(score, severity_counts)
        trend = self._detect_trend(window_signals, now)

        return final_status, factors, confidence, trend.value

    def _in_window(self, signal: HealthSignal, now: float) -> bool:
        age = now - signal.timestamp.timestamp()
        return 0 <= age <= WINDOW_SECONDS

    def _compute_weighted_score(self, signals: list[HealthSignal], now: float) -> float:
        total = 0.0
        for s in signals:
            base = SEVERITY_WEIGHT.get(s.severity.value, 1)
            age = now - s.timestamp.timestamp()
            if age <= RECENT_THRESHOLD:
                base *= 1.5
            total += base
        return total

    def _score_to_status(
        self, score: float, severity_counts: Counter[str],
    ) -> HealthStatusEnum:
        criticals = severity_counts.get(SignalSeverity.CRITICAL.value, 0)
        warnings = severity_counts.get(SignalSeverity.WARNING.value, 0)
        infos = severity_counts.get(SignalSeverity.INFO.value, 0)

        if criticals >= 3:
            return HealthStatusEnum.BROKEN
        if criticals >= 1 and score >= CRITICAL_SCORE:
            return HealthStatusEnum.CRITICAL
        if warnings >= 2 and score >= WARNING_SCORE:
            return HealthStatusEnum.WARNING
        if criticals >= 1:
            return HealthStatusEnum.CRITICAL
        if warnings >= 1:
            return HealthStatusEnum.WARNING
        return HealthStatusEnum.HEALTHY

    def _apply_transition(
        self, current: HealthStatusEnum, target: HealthStatusEnum,
    ) -> HealthStatusEnum:
        if current == target:
            return target
        if current in NON_SKIPPABLE and target not in NON_SKIPPABLE[current]:
            allowed = list(NON_SKIPPABLE[current])
            return allowed[0] if allowed else target
        return target

    def _compute_confidence(self, score: float, severity_counts: Counter[str]) -> float:
        total = sum(severity_counts.values())
        if total == 0:
            return 0.0
        criticals = severity_counts.get(SignalSeverity.CRITICAL.value, 0)
        base = min(score / 20.0, 0.85)
        bonus = min(criticals * 0.05, 0.14)
        return min(base + bonus, 0.99)

    def _build_factors(self, signals: list[HealthSignal], severity_counts: Counter[str]) -> list[str]:
        factors: list[str] = []
        criticals = severity_counts.get(SignalSeverity.CRITICAL.value, 0)
        warnings = severity_counts.get(SignalSeverity.WARNING.value, 0)

        if criticals > 0:
            for s in signals[:3]:
                if s.severity == SignalSeverity.CRITICAL and s.signal_type and s.value:
                    factors.append(f"Critical: {s.signal_type}={s.value}")
        if warnings > 0 and "warning" not in " ".join(factors).lower():
            factors.append(f"{warnings} warning signal(s) active")
        if criticals == 0 and warnings == 0:
            factors.append("All signals nominal")

        return factors[:5]

    def _detect_trend(self, signals: list[HealthSignal], now: float) -> HealthTrend:
        recent = [s for s in signals if now - s.timestamp.timestamp() <= RECENT_THRESHOLD]
        older = [s for s in signals if now - s.timestamp.timestamp() > RECENT_THRESHOLD]

        if not recent and not older:
            return HealthTrend.STABLE
        if not older:
            return HealthTrend.DECLINING if self._has_negative(recent) else HealthTrend.IMPROVING
        if not recent:
            has_negative_older = self._has_negative(older)
            return HealthTrend.IMPROVING if has_negative_older else HealthTrend.STABLE
        recent_score = self._compute_weighted_score(recent, now)
        older_score = self._compute_weighted_score(older, now)

        if older_score <= SEVERITY_WEIGHT.get(SignalSeverity.INFO.value, 1) + 1:
            if self._has_negative(recent):
                return HealthTrend.DECLINING
            return HealthTrend.STABLE

        if recent_score == 0:
            return HealthTrend.IMPROVING
        ratio = recent_score / older_score
        if ratio < 1 - TREND_DELTA:
            return HealthTrend.IMPROVING
        if ratio > 1 + TREND_DELTA:
            return HealthTrend.DECLINING
        return HealthTrend.STABLE

    @staticmethod
    def _has_negative(signals: list[HealthSignal]) -> bool:
        return any(s.severity in (SignalSeverity.WARNING, SignalSeverity.CRITICAL) for s in signals)

    @staticmethod
    def status_score(status: HealthStatusEnum) -> int:
        order = {
            HealthStatusEnum.HEALTHY: 0,
            HealthStatusEnum.WARNING: 1,
            HealthStatusEnum.CRITICAL: 2,
            HealthStatusEnum.BROKEN: 3,
            HealthStatusEnum.UNKNOWN: 4,
            HealthStatusEnum.PENDING: 5,
        }
        return order.get(status, 99)
