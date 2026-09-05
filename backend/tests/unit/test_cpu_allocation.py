from __future__ import annotations

import pytest

from app.modules.server.domain.value_objects import CpuAllocation


class TestCpuAllocationConstruction:
    def test_default_values(self) -> None:
        cpu = CpuAllocation()
        assert cpu.cores == 0
        assert cpu.affinity == ""
        assert str(cpu) == "unconstrained"

    def test_valid_positive_cores(self) -> None:
        cpu = CpuAllocation(cores=4)
        assert cpu.cores == 4
        assert cpu.affinity == ""
        assert str(cpu) == "cores=4"

    def test_negative_cores_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="cores must be ≥0"):
            CpuAllocation(cores=-1)

    def test_negative_cores_large_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="cores must be ≥0"):
            CpuAllocation(cores=-99)

    def test_valid_affinity_single_core(self) -> None:
        cpu = CpuAllocation(affinity="0")
        assert cpu.affinity == "0"
        assert str(cpu) == "affinity=0"

    def test_valid_affinity_range(self) -> None:
        cpu = CpuAllocation(affinity="0-3")
        assert cpu.affinity == "0-3"
        assert str(cpu) == "affinity=0-3"

    def test_valid_affinity_comma_separated(self) -> None:
        cpu = CpuAllocation(affinity="0,2,4")
        assert cpu.affinity == "0,2,4"
        assert str(cpu) == "affinity=0,2,4"

    def test_valid_affinity_mixed_ranges_and_singles(self) -> None:
        cpu = CpuAllocation(affinity="0-1,3,5-7")
        assert cpu.affinity == "0-1,3,5-7"
        assert str(cpu) == "affinity=0-1,3,5-7"

    def test_str_representation_both_cores_and_affinity(self) -> None:
        cpu = CpuAllocation(cores=4, affinity="0-3")
        assert str(cpu) == "cores=4 affinity=0-3"

    @pytest.mark.parametrize(
        "invalid_affinity",
        [
            "abc",
            "0-",
            "-1",
            "0-3;",
            "0--3",
            "0,2,",
            ",0,2",
            "0,,2",
            "0 1 2",
            "1-2-3",
        ],
    )
    def test_invalid_affinity_regex_format_raises(self, invalid_affinity: str) -> None:
        with pytest.raises(ValueError, match="Invalid affinity format"):
            CpuAllocation(affinity=invalid_affinity)

    def test_invalid_affinity_inverted_range_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid affinity range: 3-1"):
            CpuAllocation(affinity="3-1")

    def test_invalid_affinity_inverted_range_in_list_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid affinity range: 6-4"):
            CpuAllocation(affinity="0-2,6-4")


class TestCpuAllocationValidationGate:
    def test_validate_valid_unconstrained(self) -> None:
        CpuAllocation.validate(cores=0, affinity="")

    def test_validate_valid_constrained(self) -> None:
        CpuAllocation.validate(cores=8, affinity="0-7")

    def test_validate_negative_cores_raises(self) -> None:
        with pytest.raises(ValueError, match="cores must be ≥0"):
            CpuAllocation.validate(cores=-2, affinity="")

    def test_validate_malformed_affinity_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid affinity format"):
            CpuAllocation.validate(cores=4, affinity="invalid")

    def test_validate_reversed_affinity_range_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid affinity range: 4-2"):
            CpuAllocation.validate(cores=2, affinity="4-2")
