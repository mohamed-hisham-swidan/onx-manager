from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.modules.versioning.domain.paths import resolve_test_dir


@dataclass(frozen=True)
class TestCleanupPlan:
    """Pure domain value object defining cleanup requirements."""

    __test__ = False

    test_id: str
    server_id: str
    test_dir: Path
    container_name: str
    remove_container: bool
    purge_artifacts: bool
    retention_hours: float
    reason: str

    @classmethod
    def create(
        cls,
        server_id: str,
        test_id: str,
        container_name: str,
        test_dir: Path | str,
        server_dir: Path | str,
        passed: bool,
        cancelled: bool = False,
        retention_hours: float = 24.0,
    ) -> TestCleanupPlan:
        """Constructs and validates a pure TestCleanupPlan.

        Enforces authoritative containment validation:
        - Requires explicit authoritative server_dir (no default, no fail-open path inference).
        - Rejects substring checking in favor of exact structural containment.
        - Rejects the tests root itself (<server>/.onx/tests or <server>/.onx/tests/).
        - Rejects cross-server paths (test_dir not matching resolve_test_dir(server_dir, test_id)).
        - Rejects '..' and separator escapes.
        - Keeps invariants tied strictly to expected (server_id, test_id) identity.
        - Preserves resolve_test_dir() as the single canonical safe constructor.
        """
        if not test_id or not str(test_id).strip():
            raise ValueError("test_id cannot be empty")

        test_id_str = str(test_id).strip()
        has_separator = "/" in test_id_str or "\\" in test_id_str
        if has_separator or ".." in test_id_str or Path(test_id_str).name != test_id_str:
            raise ValueError(
                f"Invalid test_id '{test_id}': path separators and traversal tokens are not allowed"
            )

        if not server_dir or not str(server_dir).strip():
            raise ValueError(
                "server_dir cannot be empty; authoritative deployment directory is required"
            )

        resolved_test_dir = Path(test_dir).resolve()

        # 1. Structural containment check (strictly NO substring matching)
        # Canonical layout is strictly: <server_dir>/.onx/tests/<test_id>
        if resolved_test_dir.name in ("tests", ".onx"):
            raise ValueError(
                f"Test directory '{resolved_test_dir}' cannot be tests root or metadata directory"
            )

        if len(resolved_test_dir.parents) < 2:
            raise ValueError(
                f"Path too shallow to be an isolated test directory: '{resolved_test_dir}'"
            )
        tests_dir = resolved_test_dir.parent
        onx_dir = tests_dir.parent
        if tests_dir.name != "tests" or onx_dir.name != ".onx":
            raise ValueError(
                f"Test directory must be directly inside '.onx/tests' container, "
                f"got: '{resolved_test_dir}'"
            )

        # 2. Reject the tests root itself and '..' escapes
        # The leaf folder must strictly match test_id and cannot be the tests root
        if resolved_test_dir == tests_dir or resolved_test_dir.name != test_id_str:
            raise ValueError(
                f"Test directory '{resolved_test_dir}' must match test identity '{test_id_str}' "
                "and cannot be the tests root"
            )

        # 3. Reject cross-server paths & enforce authoritative containment via canonical constructor
        # Fail-open path inference is eliminated; test_dir must strictly match resolve_test_dir
        expected_test_dir = resolve_test_dir(server_dir, test_id_str)
        if resolved_test_dir != expected_test_dir:
            raise ValueError(
                f"Cross-server or mismatching test path detected: provided '{resolved_test_dir}' "
                f"does not match authoritative '{expected_test_dir}' for server '{server_id}'"
            )

        # Retention policy: passed runs purge immediately.
        # Failed or cancelled runs retain directories if retention_hours > 0.
        should_retain = (not passed or cancelled) and retention_hours > 0
        return cls(
            test_id=test_id_str,
            server_id=server_id,
            test_dir=resolved_test_dir,
            container_name=container_name,
            remove_container=True,
            purge_artifacts=not should_retain,
            retention_hours=retention_hours,
            reason=(
                "passed_purge"
                if passed
                else ("cancelled_retention" if cancelled else "failed_retention")
            ),
        )
