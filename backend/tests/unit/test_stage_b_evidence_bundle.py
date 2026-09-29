from __future__ import annotations

from unittest.mock import MagicMock

from app.modules.versioning.infrastructure.test_runner import (
    DockerTestExecutionRunner,
)
from app.modules.versioning.infrastructure.verifiers import (
    AssertionItem,
    AssertionVerdict,
)


def test_evidence_bundle_schema_and_dual_keys() -> None:
    runner = DockerTestExecutionRunner()
    handle = MagicMock()
    handle.test_id = "test-ev-1"
    handle.server_id = "srv-ev"
    handle.commit_id = "commit-abcdef"
    handle.container_name = "onx-test-container"
    handle.operation_id = "op-12345"

    runtime_data = {
        "runtime_id": "rt-123",
        "container_id": "cnt-456",
        "status": "STOPPED",
        "exit_code": 0,
        "oom_killed": False,
    }

    verdict = AssertionVerdict(
        passed=True,
        failure_reason=None,
        assertions=[
            AssertionItem(name="container_started", passed=True),
            AssertionItem(name="boot_gate_passed", passed=True),
        ],
        extra_context={
            "crash_info": {
                "blamed_mod": "mod_a.jar",
                "suspected_culprit_mods": ["mod_a.jar"],
                "summary": "Crash in mod_a",
            }
        },
    )

    log_tail = [f"line {i}" for i in range(150)]  # 150 lines

    bundle = runner._build_evidence_bundle(
        handle=handle,
        runtime_data=runtime_data,
        verdict=verdict,
        log_tail=log_tail,
    )

    # 1. Schema version 1.0
    assert bundle["schema_version"] == "1.0"
    assert bundle["operation_id"] == "op-12345"
    assert bundle["test_id"] == "test-ev-1"

    # 2. Dual keys present in assertions
    assertions = bundle["assertions"]
    assert "boot_passed" in assertions
    assert "boot_gate_passed" in assertions
    assert assertions["boot_passed"] == assertions["boot_gate_passed"]

    # 3. Dual keys present in crash_analysis
    crash = bundle["crash_analysis"]
    assert "blamed_mod" in crash
    assert "suspected_culprit_mods" in crash
    assert crash["blamed_mod"] == "mod_a.jar"
    assert "mod_a.jar" in crash["suspected_culprit_mods"]

    # 4. Log tail capped at 100 lines
    assert len(bundle["log_tail"]) <= 100
    assert bundle["log_tail"][-1] == "line 149"
