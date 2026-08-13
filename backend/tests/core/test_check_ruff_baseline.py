from __future__ import annotations

import importlib.machinery
import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
_CHECKER_PATH = _SCRIPTS_DIR / "check-ruff-baseline"


def _load_checker():
    loader = importlib.machinery.SourceFileLoader("check_ruff_baseline", str(_CHECKER_PATH))
    spec = importlib.util.spec_from_loader("check_ruff_baseline", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker():
    return _load_checker()


class TestCompareCounts:
    def test_exact_baseline_passes(self, checker) -> None:
        regressions, fixed, reduced = checker.compare_counts(
            {"E501": 10, "I001": 2}, {"E501": 10, "I001": 2}
        )
        assert regressions == []
        assert fixed == []
        assert reduced == []

    def test_reduced_but_nonzero_passes(self, checker) -> None:
        regressions, fixed, reduced = checker.compare_counts(
            {"E501": 10, "I001": 2}, {"E501": 5, "I001": 2}
        )
        assert regressions == []
        assert fixed == []
        assert reduced == ["E501"]

    def test_rule_completely_eliminated_passes(self, checker) -> None:
        # Regression test: a baseline rule missing from current output must be
        # reported as fixed, never accessed via current[...] (KeyError).
        regressions, fixed, reduced = checker.compare_counts({"I001": 1}, {})
        assert regressions == []
        assert fixed == ["I001"]
        assert reduced == ["I001"]

    def test_multiple_rules_completely_eliminated_passes(self, checker) -> None:
        regressions, fixed, reduced = checker.compare_counts(
            {"E501": 20, "I001": 3, "B008": 7}, {"I001": 3}
        )
        assert regressions == []
        assert fixed == ["B008", "E501"]
        assert reduced == ["B008", "E501"]

    def test_empty_current_all_reduced_passes(self, checker) -> None:
        regressions, fixed, reduced = checker.compare_counts(
            {"E501": 20, "I001": 3}, {}
        )
        assert regressions == []
        assert fixed == ["E501", "I001"]
        assert reduced == ["E501", "I001"]

    def test_new_violation_existing_rule_fails(self, checker) -> None:
        regressions, _fixed, _reduced = checker.compare_counts(
            {"I001": 1}, {"I001": 2}
        )
        assert regressions == ["I001"]

    def test_new_rule_not_in_baseline_fails(self, checker) -> None:
        regressions, _fixed, _reduced = checker.compare_counts(
            {"I001": 1}, {"I001": 1, "X999": 4}
        )
        assert regressions == ["X999"]

    def test_header_of_regression_message_reports_counts(self, checker) -> None:
        regressions, _fixed, _reduced = checker.compare_counts(
            {"I001": 1}, {"I001": 3, "X999": 1}
        )
        assert regressions == ["I001", "X999"]


class TestMainExitCodes:
    @pytest.fixture()
    def run_main(self, checker, tmp_path, monkeypatch):
        def _setup(baseline: dict[str, int], current: dict[str, int]) -> int:
            baseline_file = tmp_path / "ruff-baseline.json"
            baseline_file.write_text(json.dumps(baseline))
            monkeypatch.setattr(checker, "_BASELINE_PATH", baseline_file)
            monkeypatch.setattr(checker, "_current_counts", lambda: current)
            return checker.main()

        return _setup

    def test_exact_baseline_exit_zero(self, run_main) -> None:
        assert run_main({"E501": 10}, {"E501": 10}) == 0

    def test_reduced_nonzero_exit_zero(self, run_main) -> None:
        assert run_main({"E501": 10, "I001": 2}, {"E501": 8}) == 0

    def test_rule_eliminated_exit_zero_no_keyerror(self, run_main) -> None:
        # Critical regression: previously raised KeyError for a fully fixed rule.
        assert run_main({"I001": 1}, {}) == 0

    def test_all_rules_eliminated_exit_zero(self, run_main) -> None:
        assert run_main({"I001": 1, "E501": 5}, {}) == 0

    def test_new_violation_exit_one(self, run_main) -> None:
        assert run_main({"I001": 1}, {"I001": 2}) == 1

    def test_new_rule_exit_one(self, run_main) -> None:
        assert run_main({"I001": 1}, {"I001": 1, "X999": 1}) == 1


class TestRuffExecutionFailure:
    def test_ruff_error_exits_cleanly(self, checker, monkeypatch) -> None:
        class FakeResult:
            returncode = 3
            stdout = ""
            stderr = "ruff: command not found"

        def _run(*_args, **_kwargs) -> FakeResult:
            return FakeResult()

        monkeypatch.setattr(
            checker, "subprocess", type("Fake", (), {"run": _run})()
        )
        with pytest.raises(SystemExit) as exc_info:
            checker._current_counts()
        assert exc_info.value.code == 2

    def test_ruff_nonzero_exit_still_returns_no_violations(self, checker, monkeypatch) -> None:
        class FakeResult:
            returncode = 1
            stdout = "[]"
            stderr = ""

        def _run(*_args, **_kwargs) -> FakeResult:
            return FakeResult()

        monkeypatch.setattr(
            checker, "subprocess", type("Fake", (), {"run": _run})()
        )
        assert checker._current_counts() == {}
