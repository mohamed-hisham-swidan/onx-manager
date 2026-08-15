"""Alembic migration test for revision b1e2100000003 (Batch 7.2b).

Validates upgrade and downgrade for the playit and upnp columns on panel_exposure.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.config import Config
from sqlalchemy import Integer, String, create_engine, inspect

from alembic import command

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_ALEMBIC_DIR = _BACKEND_DIR / "alembic"
_MIGRATION_FILE = (
    _ALEMBIC_DIR / "versions" / "b1e2100000003_add_panel_playit_upnp_columns.py"
)

TARGET_REVISION = "b1e2100000003"
PREVIOUS_REVISION = "b1e2100000002"

_EXPECTED_PANEL_EXPOSURE_COLUMNS = {
    "cloudflare_tunnel_id",
    "cloudflare_token_ciphertext",
    "external_port",
    "playit_tunnel_id",
    "upnp_last_result",
    "upnp_last_mapped_at",
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
    spec = importlib.util.spec_from_file_location("migration_7203", _MIGRATION_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _alembic_config(tmp_path) -> tuple[Config, str]:
    db_path = tmp_path / "migration_72b.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    cfg = Config()
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg, str(db_path)


def test_migration_revision_and_down_revision() -> None:
    module = _load_migration_module()
    assert module.revision == TARGET_REVISION
    assert module.down_revision == PREVIOUS_REVISION


def test_upgrade_adds_playit_and_upnp_columns(tmp_path, monkeypatch) -> None:
    cfg, db_path = _alembic_config(tmp_path)
    monkeypatch.setenv("MCS_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

    command.upgrade(cfg, TARGET_REVISION)

    inspector = inspect(create_engine(f"sqlite:///{db_path}"))
    columns = {c["name"]: c for c in inspector.get_columns("panel_exposure")}

    assert set(columns) == _EXPECTED_PANEL_EXPOSURE_COLUMNS

    ext_port = columns["external_port"]
    assert ext_port["nullable"] is True
    assert isinstance(ext_port["type"], Integer)

    playit_id = columns["playit_tunnel_id"]
    assert playit_id["nullable"] is True
    assert isinstance(playit_id["type"], String)
    assert getattr(playit_id["type"], "length", None) == 64

    upnp_res = columns["upnp_last_result"]
    assert upnp_res["nullable"] is True
    assert isinstance(upnp_res["type"], String)
    assert getattr(upnp_res["type"], "length", None) == 32


def test_downgrade_removes_columns(tmp_path, monkeypatch) -> None:
    cfg, db_path = _alembic_config(tmp_path)
    monkeypatch.setenv("MCS_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

    command.upgrade(cfg, TARGET_REVISION)
    command.downgrade(cfg, PREVIOUS_REVISION)

    inspector = inspect(create_engine(f"sqlite:///{db_path}"))
    columns = {c["name"] for c in inspector.get_columns("panel_exposure")}

    assert "external_port" not in columns
    assert "playit_tunnel_id" not in columns
    assert "upnp_last_result" not in columns
    assert "upnp_last_mapped_at" not in columns
    assert "cloudflare_tunnel_id" in columns
    assert "cloudflare_token_ciphertext" in columns
    assert "public_address" in columns
