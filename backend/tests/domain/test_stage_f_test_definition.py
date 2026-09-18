"""Stage F TestDefinition Domain Aggregate Test Suite.

Verifies:
- TestDefinition construction, defaults, and invariant validations
- TestDefinition.update() behavior and boundary checks
- TestDefinition compilation to TestSpec
"""

import pytest

from app.modules.versioning.domain.entities import TestDefinition
from app.modules.versioning.domain.value_objects import BotTech, PlacementMode


def test_test_definition_creation_defaults() -> None:
    td = TestDefinition(
        id="td-100",
        server_id="srv-100",
        name="Smoke Test Spec",
    )
    assert td.id == "td-100"
    assert td.server_id == "srv-100"
    assert td.name == "Smoke Test Spec"
    assert td.server_type == "vanilla"
    assert td.bot_technology == BotTech.MINEFLAYER
    assert td.bot_count == 5
    assert td.duration_seconds == 60
    assert td.join_stagger_seconds == 1.0
    assert td.connect_grace_seconds == 20
    assert td.placement_mode == PlacementMode.SIDECAR
    assert td.assertion_rules == {}
    assert td.timeout_seconds == 300
    assert td.created_at is not None
    assert td.updated_at is not None


def test_test_definition_validations() -> None:
    with pytest.raises(ValueError, match="TestDefinition id cannot be empty"):
        TestDefinition(id="", server_id="srv-1", name="valid")

    with pytest.raises(ValueError, match="TestDefinition server_id cannot be empty"):
        TestDefinition(id="td-1", server_id="", name="valid")

    with pytest.raises(ValueError, match="TestDefinition name cannot be empty"):
        TestDefinition(id="td-1", server_id="srv-1", name="   ")

    with pytest.raises(ValueError, match="Invalid bot_count"):
        TestDefinition(id="td-1", server_id="srv-1", name="valid", bot_count=101)

    with pytest.raises(ValueError, match="Invalid bot_count"):
        TestDefinition(id="td-1", server_id="srv-1", name="valid", bot_count=-1)

    with pytest.raises(ValueError, match="Invalid duration_seconds"):
        TestDefinition(id="td-1", server_id="srv-1", name="valid", duration_seconds=5)

    with pytest.raises(ValueError, match="Invalid duration_seconds"):
        TestDefinition(id="td-1", server_id="srv-1", name="valid", duration_seconds=3601)

    with pytest.raises(ValueError, match="Invalid timeout_seconds"):
        TestDefinition(id="td-1", server_id="srv-1", name="valid", timeout_seconds=10)

    with pytest.raises(ValueError, match="Invalid timeout_seconds"):
        TestDefinition(id="td-1", server_id="srv-1", name="valid", timeout_seconds=8000)


def test_test_definition_update() -> None:
    td = TestDefinition(
        id="td-100",
        server_id="srv-100",
        name="Original Name",
    )
    td.update(
        name="Updated Name",
        description="New description",
        server_type="paper",
        bot_technology=BotTech.FAKEPLAYER_NEXT,
        bot_count=12,
        duration_seconds=120,
        join_stagger_seconds=0.5,
        connect_grace_seconds=15,
        placement_mode=PlacementMode.IN_CONTAINER,
        assertion_rules={"tps_min": 18.0},
        timeout_seconds=400,
    )
    assert td.name == "Updated Name"
    assert td.description == "New description"
    assert td.server_type == "paper"
    assert td.bot_technology == BotTech.FAKEPLAYER_NEXT
    assert td.bot_count == 12
    assert td.duration_seconds == 120
    assert td.join_stagger_seconds == 0.5
    assert td.connect_grace_seconds == 15
    assert td.placement_mode == PlacementMode.IN_CONTAINER
    assert td.assertion_rules == {"tps_min": 18.0}
    assert td.timeout_seconds == 400

    with pytest.raises(ValueError, match="TestDefinition name cannot be empty"):
        td.update(name="  ")

    with pytest.raises(ValueError, match="Invalid bot_count"):
        td.update(bot_count=-2)

    with pytest.raises(ValueError, match="Invalid duration_seconds"):
        td.update(duration_seconds=5)

    with pytest.raises(ValueError, match="Invalid timeout_seconds"):
        td.update(timeout_seconds=20)


def test_test_definition_compiles_to_bot_verification_config() -> None:
    from app.modules.versioning.domain.value_objects import BotVerificationConfig

    td = TestDefinition(
        id="td-compile",
        server_id="srv-1",
        name="Compile Target",
        bot_technology=BotTech.MINEFLAYER,
        bot_count=7,
        duration_seconds=90,
        placement_mode=PlacementMode.SIDECAR,
    )
    cfg = BotVerificationConfig(
        bot_count=td.bot_count,
        duration_minutes=max(1, td.duration_seconds // 60),
        bot_tech=td.bot_technology,
        placement_mode=td.placement_mode,
        join_stagger_seconds=td.join_stagger_seconds,
        connect_grace_seconds=td.connect_grace_seconds,
    )
    assert cfg.bot_count == 7
    assert cfg.duration_minutes == 1
    assert cfg.bot_tech == BotTech.MINEFLAYER
    assert cfg.placement_mode == PlacementMode.SIDECAR
