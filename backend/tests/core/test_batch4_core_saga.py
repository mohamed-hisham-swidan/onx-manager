from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from app.core.config import AppSettings
from app.core.event_bus import DomainEvent, EventBus, EventHandler, Priority
from app.core.saga import (
    SagaOrchestrator,
    SagaStatus,
    SagaStep,
    SagaStepStatus,
)
from app.modules.shared.value_objects import PluginVersion


class TestBatch4AConfigDualEnv:
    """F001: ONX_* env prefix takes precedence over MCS_* prefix."""

    def test_mcs_prefix_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCS_LOG_LEVEL", "DEBUG")
        monkeypatch.delenv("ONX_LOG_LEVEL", raising=False)
        settings = AppSettings()
        assert settings.log_level == "DEBUG"

    def test_onx_prefix_precedence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCS_LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("ONX_LOG_LEVEL", "WARNING")
        settings = AppSettings()
        assert settings.log_level == "WARNING"


class TestBatch4ADbRevision:
    """F004: RELEASE_MINIMUM_DB_REVISION alignment."""

    def test_release_minimum_db_revision_format(self) -> None:
        from app.core.persistence.db_revision import (
            EXPECTED_ALEMBIC_HEAD,
            RELEASE_MINIMUM_DB_REVISION,
        )

        assert RELEASE_MINIMUM_DB_REVISION == EXPECTED_ALEMBIC_HEAD
        assert len(RELEASE_MINIMUM_DB_REVISION) == 13


class TestBatch4AEventBusPriorityTiers:
    """F005: EventBus dispatches priority tiers sequentially.

    Subscribers in the same tier execute concurrently.
    """

    @pytest.mark.asyncio
    async def test_sequential_tiers_execution_order(self) -> None:
        event_bus = EventBus()
        execution_order: list[str] = []

        class SlowCriticalHandler(EventHandler):
            async def handle(self, _event: DomainEvent) -> None:
                await asyncio.sleep(0.05)
                execution_order.append("critical")

        class FastHighHandler(EventHandler):
            async def handle(self, _event: DomainEvent) -> None:
                execution_order.append("high")

        class FastNormalHandler(EventHandler):
            async def handle(self, _event: DomainEvent) -> None:
                execution_order.append("normal")

        class FastLowHandler(EventHandler):
            async def handle(self, _event: DomainEvent) -> None:
                execution_order.append("low")

        event_bus.subscribe("TestTierEvent", FastLowHandler(), priority=Priority.LOW)
        event_bus.subscribe("TestTierEvent", FastNormalHandler(), priority=Priority.NORMAL)
        event_bus.subscribe("TestTierEvent", FastHighHandler(), priority=Priority.HIGH)
        event_bus.subscribe("TestTierEvent", SlowCriticalHandler(), priority=Priority.CRITICAL)

        class CustomEvent(DomainEvent):
            event_type: str = "TestTierEvent"

        await event_bus.publish(CustomEvent())

        assert execution_order == ["critical", "high", "normal", "low"]


class TestBatch4ASagaTimeoutCompensation:
    """F014: Saga timeout triggers compensation for executed steps."""

    @pytest.mark.asyncio
    async def test_timeout_compensates_executed_steps(self) -> None:
        orchestrator = SagaOrchestrator()
        step1_compensated = False

        def forward1() -> None:
            pass

        def compensate1() -> None:
            nonlocal step1_compensated
            step1_compensated = True

        def forward2() -> None:
            pass

        step1 = SagaStep(name="step1", forward=forward1, compensate=compensate1)
        step2 = SagaStep(name="step2", forward=forward2)

        async def slow_forward1() -> None:
            await asyncio.sleep(0.05)

        step1.forward = slow_forward1

        instance = await orchestrator.create_saga(
            "timeout_saga", [step1, step2], timeout_seconds=0.01
        )
        result = await orchestrator.execute(instance.saga_id)

        assert step1_compensated is True
        assert result.status == SagaStatus.COMPENSATED
        assert result.error == "Saga timed out"
        assert result.steps[0].status == SagaStepStatus.COMPENSATED

    @pytest.mark.asyncio
    async def test_immediate_timeout_no_compensation(self) -> None:
        orchestrator = SagaOrchestrator()
        comp = MagicMock()

        step1 = SagaStep(name="step1", forward=MagicMock(), compensate=comp)
        instance = await orchestrator.create_saga("immediate_timeout", [step1], timeout_seconds=0.0)
        await asyncio.sleep(0.01)
        result = await orchestrator.execute(instance.saga_id)

        assert result.status == SagaStatus.FAILED
        assert result.error == "Saga timed out"
        assert not comp.called

    @pytest.mark.asyncio
    async def test_timeout_after_final_step_compensates(self) -> None:
        """If a single or final step execution exceeds timeout, it is compensated."""
        orchestrator = SagaOrchestrator()
        comp = MagicMock()

        async def slow_forward() -> None:
            await asyncio.sleep(0.05)

        step1 = SagaStep(name="step1", forward=slow_forward, compensate=comp)
        instance = await orchestrator.create_saga(
            "single_step_timeout", [step1], timeout_seconds=0.01
        )
        result = await orchestrator.execute(instance.saga_id)

        assert result.status == SagaStatus.COMPENSATED
        assert result.error == "Saga timed out"
        assert comp.called
        assert result.steps[0].status == SagaStepStatus.COMPENSATED



class TestBatch4APluginVersionSemVer:
    """F018: PluginVersion equality and comparisons ignore build metadata per SemVer 2.0.0."""

    def test_equality_ignores_build_metadata(self) -> None:
        v1 = PluginVersion.parse("1.2.3+build.1")
        v2 = PluginVersion.parse("1.2.3+build.2")
        v3 = PluginVersion.parse("1.2.3")

        assert v1 == v2
        assert v1 == v3
        assert (v1 != v2) is False
        assert hash(v1) == hash(v2)
        assert hash(v1) == hash(v3)

    def test_ordering_with_build_metadata(self) -> None:
        v1 = PluginVersion.parse("1.2.3+alpha")
        v2 = PluginVersion.parse("1.2.3+beta")

        assert v1 <= v2
        assert v2 <= v1
        assert v1 >= v2
        assert v2 >= v1
        assert not (v1 < v2)
        assert not (v1 > v2)

    def test_precedence_with_prerelease(self) -> None:
        v_pre = PluginVersion.parse("1.2.3-rc.1+build.1")
        v_pre2 = PluginVersion.parse("1.2.3-rc.1+build.2")
        v_release = PluginVersion.parse("1.2.3+build.3")

        assert v_pre == v_pre2
        assert v_pre < v_release
        assert v_pre <= v_release
        assert v_release > v_pre
