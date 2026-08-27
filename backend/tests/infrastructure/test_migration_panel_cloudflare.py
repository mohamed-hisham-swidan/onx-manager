"""Migration/schema test for Batch 7.2a revision ``b1e2100000002``.

Verifies, WITHOUT running the application, that the migration:
  - revises exactly ``b1e2100000001`` (correct ``down_revision``),
  - upgrades ``panel_exposure`` by adding exactly the two new nullable columns
    (``cloudflare_tunnel_id`` String(64), ``cloudflare_token_ciphertext``
    LargeBinary), and
  - introduces no unrelated schema columns,
  - downgrades by removing exactly those two columns.

The full chain is applied to a throwaway sqlite file so the assertions reflect
the real migration execution, not an in-memory metadata guess.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.config import Config
from sqlalchemy import LargeBinary, create_engine, inspect

from alembic import command

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_ALEMBIC_DIR = _BACKEND_DIR / "alembic"
_MIGRATION_FILE = _ALEMBIC_DIR / "versions" / "b1e2100000002_add_panel_cloudflare_columns.py"

_EXPECTED_PANEL_EXPOSURE_COLUMNS = {
    "cloudflare_tunnel_id",
    "cloudflare_token_ciphertext",
    "created_at",
    "desired_state",
    "error_code",
    "error_message",
    "id",
    "method",
    "public_address",
    "status",
    "updated_at",
}


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("migration_7202", _MIGRATION_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _alembic_config(tmp_path) -> tuple[Config, str]:
    db_path = tmp_path / "migration.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    cfg = Config()
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg, str(db_path)


def test_migration_revision_and_down_revision() -> None:
    module = _load_migration_module()
    assert module.revision == "b1e2100000002"
    assert module.down_revision == "b1e2100000001"


def test_upgrade_adds_exactly_two_nullable_columns(tmp_path, monkeypatch) -> None:
    cfg, db_path = _alembic_config(tmp_path)
    monkeypatch.setenv("MCS_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

    command.upgrade(cfg, "b1e2100000002")

    inspector = inspect(create_engine(f"sqlite:///{db_path}"))
    columns = {c["name"]: c for c in inspector.get_columns("panel_exposure")}

    # Exactly the 7.1 base columns plus the two new 7.2a columns — no others.
    assert set(columns) == _EXPECTED_PANEL_EXPOSURE_COLUMNS

    tunnel = columns["cloudflare_tunnel_id"]
    assert tunnel["nullable"] is True
    assert getattr(tunnel["type"], "length", None) == 64

    ciphertext = columns["cloudflare_token_ciphertext"]
    assert ciphertext["nullable"] is True
    assert isinstance(ciphertext["type"], LargeBinary)


def test_downgrade_removes_only_cloudflare_columns(tmp_path, monkeypatch) -> None:
    cfg, db_path = _alembic_config(tmp_path)
    monkeypatch.setenv("MCS_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

    command.upgrade(cfg, "b1e2100000002")
    command.downgrade(cfg, "b1e2100000001")

    inspector = inspect(create_engine(f"sqlite:///{db_path}"))
    columns = {c["name"] for c in inspector.get_columns("panel_exposure")}
    assert "cloudflare_tunnel_id" not in columns
    assert "cloudflare_token_ciphertext" not in columns
    # The 7.1 schema is otherwise untouched.
    assert "public_address" in columns
    assert "error_code" in columns
