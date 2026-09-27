from __future__ import annotations

from pathlib import Path

import yaml

from app.modules.operations.domain.events import (
    OperationCancelledEvent,
    OperationCompletedEvent,
    OperationFailedEvent,
    OperationLogEvent,
    OperationStartedEvent,
    OperationStepEvent,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_operation_events_yaml_contract_match() -> None:
    events_file = REPO_ROOT / "contracts" / "events.yaml"
    with open(events_file, encoding="utf-8") as f:
        doc = yaml.safe_load(f)

    events_spec = doc["events"]

    event_mappings = [
        ("operation.started", OperationStartedEvent),
        ("operation.step", OperationStepEvent),
        ("operation.log", OperationLogEvent),
        ("operation.completed", OperationCompletedEvent),
        ("operation.failed", OperationFailedEvent),
        ("operation.cancelled", OperationCancelledEvent),
    ]

    for yaml_key, event_cls in event_mappings:
        assert yaml_key in events_spec, f"Missing {yaml_key} in contracts/events.yaml"
        spec = events_spec[yaml_key]
        assert spec["version"] == 1, f"Expected version 1 for {yaml_key}"

        payload_schema = spec["payload"]
        assert "event_seq" in payload_schema, f"Missing event_seq in {yaml_key} payload"
        assert payload_schema["event_seq"] == "integer"

        # Verify that all required fields in the YAML spec exist on the Pydantic model
        model_fields = event_cls.model_fields
        for field_name in payload_schema:
            assert (
                field_name in model_fields
            ), f"Field '{field_name}' in YAML spec for '{yaml_key}' missing from {event_cls}"


def test_operation_event_instantiation_and_serialization() -> None:
    started = OperationStartedEvent(
        operation_id="op-1",
        event_seq=1,
        type="RUN_TEST",
        target_type="server",
        target_id="srv-1",
        server_id="srv-1",
        actor_id="user-1",
    )
    d = started.model_dump()
    assert d["operation_id"] == "op-1"
    assert d["event_seq"] == 1
    assert d["event_type"] == "OperationStartedEvent"

    step = OperationStepEvent(
        operation_id="op-1",
        event_seq=2,
        server_id="srv-1",
        step_id="MATERIALIZE_STAGING",
        sequence=2,
        status="IN_PROGRESS",
        progress=0.5,
        elapsed_ms=1200,
        safe_to_retry=True,
        context={"detail": "staging files"},
    )
    d_step = step.model_dump()
    assert d_step["step_id"] == "MATERIALIZE_STAGING"
    assert d_step["event_seq"] == 2
    assert d_step["safe_to_retry"] is True

    failed = OperationFailedEvent(
        operation_id="op-1",
        event_seq=3,
        target_type="server",
        target_id="srv-1",
        server_id="srv-1",
        type="RUN_TEST",
        failure_code="OPERATION_TIMEOUT",
        error_message="Timed out",
    )
    d_failed = failed.model_dump()
    assert d_failed["failure_code"] == "OPERATION_TIMEOUT"
    assert d_failed["event_seq"] == 3
