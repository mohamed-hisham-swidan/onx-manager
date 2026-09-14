from unittest.mock import MagicMock, patch

import pytest

from app.core.exceptions import BotRunInsufficientResourcesError
from app.modules.versioning.infrastructure.resource_probe import (
    ResourcePreflightProbe,
)


def test_calculate_required_resources_scaling() -> None:
    # Vanilla 10 bots (baseline floor)
    ram_10, cores_10 = ResourcePreflightProbe.calculate_required_resources(
        10, server_type="vanilla"
    )
    assert ram_10 == 4096
    assert cores_10 == 2

    # Vanilla 20 bots (10 additional bots * 50MB = 500MB)
    ram_20, cores_20 = ResourcePreflightProbe.calculate_required_resources(
        20, server_type="vanilla"
    )
    assert ram_20 == 4096 + 500
    assert cores_20 == 2

    # Forge 10 bots (baseline 4096 + 2048 modded overhead = 6144MB)
    ram_forge, cores_forge = ResourcePreflightProbe.calculate_required_resources(
        10, server_type="forge"
    )
    assert ram_forge == 4096 + 2048
    assert cores_forge == 2

    # Forge 100 bots (baseline 6144 + 90 * 50 = 6144 + 4500 = 10644MB,
    # additional cores: 90 // 50 = 1 -> 3 cores)
    ram_forge_100, cores_forge_100 = ResourcePreflightProbe.calculate_required_resources(
        100, server_type="forge"
    )
    assert ram_forge_100 == 10644
    assert cores_forge_100 == 3


def test_resource_preflight_probe_sufficient_headroom() -> None:
    mock_vm = MagicMock(available=8 * 1024 * 1024 * 1024)  # 8GB available

    with (
        patch("psutil.virtual_memory", return_value=mock_vm),
        patch("os.cpu_count", return_value=8),
    ):
        res = ResourcePreflightProbe.check_headroom(10, server_type="vanilla")
        assert res.passed is True
        assert res.available_ram_mb == 8192
        assert res.required_ram_mb == 4096
        assert "Sufficient headroom" in res.message

        # assert_sufficient_resources returns the result and does not raise
        checked = ResourcePreflightProbe.assert_sufficient_resources(10, server_type="vanilla")
        assert checked.passed is True


def test_resource_preflight_probe_insufficient_ram_raises_error() -> None:
    mock_vm = MagicMock(available=2 * 1024 * 1024 * 1024)  # 2GB available (need 4GB)

    with (
        patch("psutil.virtual_memory", return_value=mock_vm),
        patch("os.cpu_count", return_value=8),
    ):
        res = ResourcePreflightProbe.check_headroom(10, server_type="vanilla")
        assert res.passed is False
        assert "RAM" in res.message

        with pytest.raises(BotRunInsufficientResourcesError) as exc_info:
            ResourcePreflightProbe.assert_sufficient_resources(10, server_type="vanilla")

        err = exc_info.value
        assert err.code == "BOT_RUN_INSUFFICIENT_RESOURCES"
        assert err.http_status == 422
        assert "RAM" in err.message
        assert err.details["required_ram_mb"] == 4096
        assert err.details["available_ram_mb"] == 2048


def test_resource_preflight_probe_insufficient_cores_raises_error() -> None:
    mock_vm = MagicMock(available=16 * 1024 * 1024 * 1024)  # 16GB available

    with (
        patch("psutil.virtual_memory", return_value=mock_vm),
        patch("os.cpu_count", return_value=1),
    ):
        # 1 core available but need 2 cores
        res = ResourcePreflightProbe.check_headroom(10, server_type="vanilla")
        assert res.passed is False
        assert "Cores" in res.message

        with pytest.raises(BotRunInsufficientResourcesError) as exc_info:
            ResourcePreflightProbe.assert_sufficient_resources(10, server_type="vanilla")

        err = exc_info.value
        assert err.code == "BOT_RUN_INSUFFICIENT_RESOURCES"
        assert err.details["required_cores"] == 2
        assert err.details["available_cores"] == 1
