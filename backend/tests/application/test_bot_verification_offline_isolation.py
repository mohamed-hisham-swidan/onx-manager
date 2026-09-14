import os
import tempfile
from pathlib import Path

import pytest

from app.core.exceptions import TestIsolationViolationError
from app.modules.server.domain.value_objects import ServerDeployment
from app.modules.versioning.domain.deployment import TestServerDeployment
from app.modules.versioning.infrastructure.config_writer import write_test_server_properties


def test_write_test_server_properties_enforces_offline_and_insecure_profile() -> None:
    """Requirement (1): Writes online-mode=false and enforce-secure-profile=false
    ONLY under .onx/tests/<test_id>/.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = os.path.join(tmpdir, ".onx", "tests", "test-12345")
        os.makedirs(test_dir, exist_ok=True)
        deployment = TestServerDeployment(test_id="test-12345", test_dir=test_dir)

        # Base properties attempt to enable online-mode and enforce-secure-profile
        base_props = {
            "online-mode": "true",
            "enforce-secure-profile": "true",
            "motd": "Test Server",
            "difficulty": "hard",
        }

        path = write_test_server_properties(deployment, base_properties=base_props)

        assert os.path.exists(path)
        assert path.endswith("server.properties")
        assert ".onx/tests/test-12345" in path.replace("\\", "/")

        with open(path) as f:
            content = f.read()

        # Hard invariant: online-mode and enforce-secure-profile MUST be false
        assert "online-mode=false" in content
        assert "enforce-secure-profile=false" in content
        assert "online-mode=true" not in content
        assert "enforce-secure-profile=true" not in content
        assert "motd=Test Server" in content

        # EULA must also be created
        eula_path = os.path.join(test_dir, "eula.txt")
        assert os.path.exists(eula_path)
        with open(eula_path) as f:
            assert "eula=true" in f.read()


def test_write_test_server_properties_rejects_production_deployment() -> None:
    """Requirement (2): write_test_server_properties rejects production ServerDeployment."""
    prod_deployment = ServerDeployment(
        root_path="/srv/minecraft/prod",
        working_directory=".",
    )

    # 1. Runtime exception check
    with pytest.raises(TestIsolationViolationError) as exc_info:
        # Intentionally passing production ServerDeployment (type violation)
        write_test_server_properties(prod_deployment)  # type: ignore[arg-type]

    assert "TestServerDeployment" in str(exc_info.value)

    # 2. Signature parameter type annotation check (type-checker catchable)
    import typing

    type_hints = typing.get_type_hints(write_test_server_properties)
    assert type_hints["deployment"] is TestServerDeployment
    assert type_hints["deployment"] is not ServerDeployment


def test_test_server_deployment_rejects_non_isolated_path() -> None:
    """Requirement (2b): TestServerDeployment cannot wrap a production directory."""
    with pytest.raises(TestIsolationViolationError):
        TestServerDeployment(test_id="evil", test_dir="/data/servers/production-srv-1")


def test_import_graph_no_test_code_imports_production_config_writer() -> None:
    """Requirement (3): Import-graph assertion that no test-run code path
    imports or invokes UpdateServerConfigCommand.
    """
    versioning_dir = Path(__file__).resolve().parents[2] / "app" / "modules" / "versioning"
    assert versioning_dir.exists(), f"Versioning directory {versioning_dir} not found"

    forbidden_patterns = [
        "UpdateServerConfigCommand",
        "update_server_config",
    ]

    for py_file in versioning_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for pattern in forbidden_patterns:
            assert pattern not in text, (
                f"Safety violation: {py_file} imports or references {pattern}. "
                "Test run code paths must NEVER reach production config writers!"
            )


def test_production_server_properties_byte_identical_after_simulated_test() -> None:
    """Requirement (4): Production server.properties is byte-identical
    before/after a simulated test run.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Setup simulated production server
        prod_dir = os.path.join(tmpdir, "servers", "prod-srv-1")
        os.makedirs(prod_dir, exist_ok=True)
        prod_props_path = os.path.join(prod_dir, "server.properties")

        initial_prod_content = (
            b"online-mode=true\n"
            b"enforce-secure-profile=true\n"
            b"server-port=25565\n"
            b"motd=Production Server - Do Not Corrupt\n"
        )

        with open(prod_props_path, "wb") as f:
            f.write(initial_prod_content)

        # Setup isolated test deployment
        test_dir = os.path.join(tmpdir, ".onx", "tests", "test-sim-999")
        os.makedirs(test_dir, exist_ok=True)
        test_deployment = TestServerDeployment(test_id="test-sim-999", test_dir=test_dir)

        # Execute test properties writing
        write_test_server_properties(
            test_deployment,
            base_properties={
                "server-port": "25566",
                "motd": "Test Server",
            },
        )

        # Verify test directory received offline properties
        test_props_path = os.path.join(test_dir, "server.properties")
        assert os.path.exists(test_props_path)
        with open(test_props_path, encoding="utf-8") as f:
            test_content = f.read()
        assert "online-mode=false" in test_content

        # Verify production properties are 100% byte-identical
        with open(prod_props_path, "rb") as f:
            current_prod_content = f.read()

        assert current_prod_content == initial_prod_content, (
            "Production server.properties was altered during test configuration write!"
        )
