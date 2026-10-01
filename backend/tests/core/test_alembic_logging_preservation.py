from __future__ import annotations

import logging
from pathlib import Path

from app.core.persistence.reconciler import DatabaseReconciler, ReconcileStatus


def test_alembic_migration_preserves_logging_state(tmp_path: Path) -> None:
    """Verifies in-process Alembic upgrade does not alter logging configuration.

    Regression test for:
    - existing loggers disabled by fileConfig (disable_existing_loggers=True)
    - root handlers replaced/cleared by alembic.ini
    - root log level reset to alembic.ini's level (WARN)
    """
    root_logger = logging.getLogger()
    target_logger = logging.getLogger(
        "app.modules.versioning.application.scheduling.admission"
    )

    # Ensure target logger is active before migration
    target_logger.disabled = False
    assert target_logger.disabled is False

    # Snapshot root logging state
    initial_root_level = root_logger.level
    initial_root_handlers = list(root_logger.handlers)
    initial_target_disabled = target_logger.disabled

    # Execute in-process migration on a fresh temp database through reconciler
    db_file = tmp_path / "test_migration_logging.db"
    reconciler = DatabaseReconciler(db_url=f"sqlite+aiosqlite:///{db_file}")
    result = reconciler.reconcile(auto_upgrade=True)

    assert result.status == ReconcileStatus.RECONCILED, (
        f"Reconciler execution failed: {result.message}"
    )

    # Assert all three logging invariants are preserved
    assert root_logger.handlers == initial_root_handlers, (
        f"Root handlers were modified: before={initial_root_handlers}, after={root_logger.handlers}"
    )
    assert root_logger.level == initial_root_level, (
        f"Root logger level changed: before={initial_root_level}, after={root_logger.level}"
    )
    assert target_logger.disabled == initial_target_disabled, (
        f"Target logger disabled flag changed: before={initial_target_disabled}, "
        f"after={target_logger.disabled}"
    )
