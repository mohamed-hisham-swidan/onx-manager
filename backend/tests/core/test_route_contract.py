from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
_CONTRACT = _REPO_ROOT / "contracts" / "permissions.yaml"
_CHECKER_PATH = _SCRIPTS_DIR / "check-route-contract"


def _load_checker():
    loader = importlib.machinery.SourceFileLoader("check_route_contract", str(_CHECKER_PATH))
    spec = importlib.util.spec_from_loader("check_route_contract", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker():
    return _load_checker()


# ── Fixture helpers ─────────────────────────────────────────────────────────


def _fact(**overrides):
    base = {"is_ws": False, "auth": True, "owner": False, "permissions": set()}
    base.update(overrides)
    return base


def _enforced(perm: str | set[str]) -> dict:
    perms = {perm} if isinstance(perm, str) else set(perm)
    return _fact(permissions=perms)


def _public() -> dict:
    return _fact(auth=False)


def _owner_only() -> dict:
    return _fact(owner=True)


def _contract(status: str, permission: str | set[str] | None):
    perms = None
    if permission is not None:
        perms = {permission} if isinstance(permission, str) else set(permission)
    return {"status": status, "permission": perms}


# ── Pure check() — route presence / drift ───────────────────────────────────


class TestRoutePresence:
    def test_live_route_missing_from_contract_fails(self, checker) -> None:
        live = [("GET", "/api/v1/marketplace/search", _enforced("plugin:manage"))]
        contract = {}
        ok, problems = checker.check(live, contract)
        assert ok is False
        assert any("UNCOVERED" in p and "/api/v1/marketplace/search" in p for p in problems)

    def test_contract_route_without_live_route_fails(self, checker) -> None:
        live = []
        contract = {("GET", "/api/v1/marketplace/search"): _contract("enforced", "plugin:manage")}
        ok, problems = checker.check(live, contract)
        assert ok is False
        assert any("STALE" in p and "/api/v1/marketplace/search" in p for p in problems)

    def test_exact_match_passes(self, checker) -> None:
        live = [("GET", "/api/v1/marketplace/search", _enforced("plugin:manage"))]
        contract = {("GET", "/api/v1/marketplace/search"): _contract("enforced", "plugin:manage")}
        ok, problems = checker.check(live, contract)
        assert ok is True
        assert problems == []

    def test_method_mismatch_is_uncovered_and_stale(self, checker) -> None:
        live = [("POST", "/api/v1/servers", _enforced("server:create"))]
        contract = {("GET", "/api/v1/servers"): _contract("enforced", "server:create")}
        ok, problems = checker.check(live, contract)
        assert ok is False
        assert any("UNCOVERED" in p and "POST /api/v1/servers" in p for p in problems)
        assert any("STALE" in p and "GET /api/v1/servers" in p for p in problems)


class TestEnforcedMismatches:
    def test_permission_mismatch_fails(self, checker) -> None:
        live = [("GET", "/api/v1/monitoring/alerts", _enforced("server:read"))]
        contract = {("GET", "/api/v1/monitoring/alerts"): _contract("missing", "settings:read")}
        ok, problems = checker.check(live, contract)
        assert ok is False
        assert any("ENFORCED-LIVE" in p for p in problems)

    def test_enforced_contract_but_live_no_permission_fails(self, checker) -> None:
        live = [("GET", "/api/v1/settings", _fact())]  # auth-only, no permission
        contract = {("GET", "/api/v1/settings"): _contract("enforced", "settings:read")}
        ok, problems = checker.check(live, contract)
        assert ok is False
        assert any("NOT-ENFORCED" in p for p in problems)

    def test_wrong_permission_value_fails(self, checker) -> None:
        live = [("PATCH", "/api/v1/settings", _enforced("settings:write"))]
        contract = {("PATCH", "/api/v1/settings"): _contract("enforced", "settings:read")}
        ok, problems = checker.check(live, contract)
        assert ok is False
        assert any("PERMISSION-MISMATCH" in p for p in problems)

    def test_owner_permission_contract_vs_live_owner_passes(self, checker) -> None:
        live = [("PUT", "/api/v1/setup/access-mode", _owner_only())]
        contract = {("PUT", "/api/v1/setup/access-mode"): _contract("enforced", "owner")}
        ok, problems = checker.check(live, contract)
        assert ok is True

    def test_owner_permission_contract_vs_live_plain_fails(self, checker) -> None:
        live = [("PUT", "/api/v1/setup/access-mode", _enforced("settings:write"))]
        contract = {("PUT", "/api/v1/setup/access-mode"): _contract("enforced", "owner")}
        ok, problems = checker.check(live, contract)
        assert ok is False
        assert any("PERMISSION-MISMATCH" in p for p in problems)


class TestPublicAndAuthOnly:
    def test_public_contract_matches_public_route_passes(self, checker) -> None:
        live = [("GET", "/health", _public())]
        contract = {("GET", "/health"): _contract("not-applicable-public", None)}
        ok, problems = checker.check(live, contract)
        assert ok is True

    def test_public_contract_but_live_enforces_permission_fails(self, checker) -> None:
        live = [("GET", "/health", _enforced("server:read"))]
        contract = {("GET", "/health"): _contract("not-applicable-public", None)}
        ok, problems = checker.check(live, contract)
        assert ok is False
        assert any("ENFORCED-LIVE" in p for p in problems)

    def test_missing_contract_auth_only_live_passes(self, checker) -> None:
        live = [("GET", "/api/v1/servers", _fact())]  # auth-only
        contract = {("GET", "/api/v1/servers"): _contract("missing", "server:read")}
        ok, problems = checker.check(live, contract)
        assert ok is True

    def test_missing_contract_but_live_fully_public_fails(self, checker) -> None:
        live = [("GET", "/api/v1/servers", _public())]
        contract = {("GET", "/api/v1/servers"): _contract("missing", "server:read")}
        ok, problems = checker.check(live, contract)
        assert ok is False
        assert any("PUBLIC-LIVE" in p for p in problems)

    def test_unknown_status_flagged(self, checker) -> None:
        live = [("GET", "/health", _public())]
        contract = {("GET", "/health"): _contract("made-up-status", None)}
        ok, problems = checker.check(live, contract)
        assert ok is False
        assert any("UNKNOWN-STATUS" in p for p in problems)


class TestWebSocket:
    def test_ws_contract_matches_ws_route_passes(self, checker) -> None:
        live = [("WS", "/ws", _fact(is_ws=True))]
        contract = {("WS", "/ws"): _contract("enforced-external", None)}
        ok, problems = checker.check(live, contract)
        assert ok is True

    def test_ws_route_without_enforced_external_contract_fails(self, checker) -> None:
        live = [("WS", "/ws", _fact(is_ws=True))]
        contract = {("WS", "/ws"): _contract("enforced", "user:read")}
        ok, problems = checker.check(live, contract)
        assert ok is False
        assert any("WS" in p for p in problems)

    def test_non_ws_route_claimed_enforced_external_fails(self, checker) -> None:
        live = [("GET", "/ws", _public())]
        contract = {("GET", "/ws"): _contract("enforced-external", None)}
        ok, problems = checker.check(live, contract)
        assert ok is False
        assert any("NOT-WS" in p for p in problems)


# ── parse_contract() ────────────────────────────────────────────────────────


class TestParseContract:
    def test_parses_enforced_entry(self, checker, tmp_path) -> None:
        f = tmp_path / "c.yaml"
        f.write_text(
            "route_permissions:\n"
            '  "POST /api/v1/servers": '
            '{permission: "server:create", status: enforced, note: "x"}\n',
            encoding="utf-8",
        )
        parsed = checker.parse_contract(f)
        assert ("POST", "/api/v1/servers") in parsed
        assert parsed[("POST", "/api/v1/servers")] == {
            "status": "enforced",
            "permission": {"server:create"},
        }

    def test_parses_null_permission(self, checker, tmp_path) -> None:
        f = tmp_path / "c.yaml"
        f.write_text(
            '  "GET /health": {permission: null, status: not-applicable-public}\n',
            encoding="utf-8",
        )
        parsed = checker.parse_contract(f)
        assert parsed[("GET", "/health")]["permission"] is None

    def test_parses_or_permission_set(self, checker, tmp_path) -> None:
        f = tmp_path / "c.yaml"
        f.write_text(
            '  "GET /api/v1/servers/{server_id}/files/download": '
            '{permission: "server.{id}.files OR server.{id}.view", status: enforced}\n',
            encoding="utf-8",
        )
        parsed = checker.parse_contract(f)
        assert parsed[("GET", "/api/v1/servers/{server_id}/files/download")]["permission"] == {
            "server.{id}.files",
            "server.{id}.view",
        }

    def test_ignores_comments_and_non_entries(self, checker, tmp_path) -> None:
        f = tmp_path / "c.yaml"
        f.write_text(
            "# comment\nversion: 1.5\n"
            '  "GET /health": {permission: null, status: not-applicable-public}\n',
            encoding="utf-8",
        )
        parsed = checker.parse_contract(f)
        assert set(parsed) == {("GET", "/health")}


# ── classify_route() against the real dependency structure ──────────────────


class TestClassifyLive:
    def test_require_permission_classified(self, checker) -> None:
        live = checker.collect_live(_create_app())
        facts = {(_m, _p): f for _m, _p, f in live}
        assert facts[("GET", "/api/v1/marketplace/search")]["permissions"] == {"plugin:manage"}
        assert facts[("GET", "/api/v1/marketplace/projects/{project_id}")]["permissions"] == {
            "plugin:manage"
        }
        assert facts[("POST", "/api/v1/servers")]["permissions"] == {"server:create"}

    def test_server_scoped_permission_classified(self, checker) -> None:
        facts = {(_m, _p): f for _m, _p, f in checker.collect_live(_create_app())}
        assert facts[("POST", "/api/v1/servers/{server_id}/start")]["permissions"] == {
            "server.{id}.power"
        }

    def test_owner_route_classified(self, checker) -> None:
        facts = {(_m, _p): f for _m, _p, f in checker.collect_live(_create_app())}
        assert facts[("PUT", "/api/v1/setup/access-mode")]["owner"] is True

    def test_ws_route_classified(self, checker) -> None:
        facts = {(_m, _p): f for _m, _p, f in checker.collect_live(_create_app())}
        assert facts[("WS", "/ws")]["is_ws"] is True


def _create_app():
    import sys as _sys

    backend = _REPO_ROOT / "backend"
    if str(backend) not in _sys.path:
        _sys.path.insert(0, str(backend))
    from app.main import create_app

    return create_app()


# ── Full live check against the committed contract ──────────────────────────


class TestLiveContract:
    def test_committed_contract_matches_live_route_table(self, checker) -> None:
        live = checker.collect_live(_create_app())
        contract = checker.parse_contract(_CONTRACT)
        ok, problems = checker.check(live, contract)
        assert ok is True, "\n".join(problems)
        assert len(live) == len(contract)

    def test_committed_contract_contains_both_marketplace_routes(self, checker) -> None:
        contract = checker.parse_contract(_CONTRACT)
        assert ("GET", "/api/v1/marketplace/search") in contract
        assert ("GET", "/api/v1/marketplace/projects/{project_id}") in contract
        for key in (
            ("GET", "/api/v1/marketplace/search"),
            ("GET", "/api/v1/marketplace/projects/{project_id}"),
        ):
            assert contract[key]["status"] == "enforced"
            assert contract[key]["permission"] == {"plugin:manage"}


# ── main() exit codes ───────────────────────────────────────────────────────


def _synthetic_app():
    """A tiny real FastAPI app exercising the real dependency factories."""
    from fastapi import Depends, FastAPI

    from app.api.deps import get_current_user, require_permission

    app = FastAPI()

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/v1/me")
    def me(_: None = Depends(get_current_user)) -> dict:
        return {"ok": True}

    @app.post("/api/v1/servers")
    def create_server(_: None = Depends(require_permission("server:create"))) -> dict:
        return {"ok": True}

    return app


class TestMain:
    def test_main_exits_zero_on_pass(self, checker, tmp_path, monkeypatch) -> None:
        contract = tmp_path / "c.yaml"
        contract.write_text(
            '  "GET /health": {permission: null, status: not-applicable-public}\n'
            '  "GET /docs": {permission: null, status: not-applicable-public}\n'
            '  "GET /docs/oauth2-redirect": {permission: null, status: not-applicable-public}\n'
            '  "GET /openapi.json": {permission: null, status: not-applicable-public}\n'
            '  "GET /redoc": {permission: null, status: not-applicable-public}\n'
            '  "GET /api/v1/me": {permission: null, status: missing, note: "auth-only"}\n'
            '  "POST /api/v1/servers": {permission: "server:create", status: enforced}\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(checker, "_boot_app", lambda _args: _synthetic_app())
        rc = checker.main(["--contract", str(contract)])
        assert rc == 0

    def test_main_exits_one_on_drift(self, checker, tmp_path, monkeypatch) -> None:
        contract = tmp_path / "c.yaml"
        contract.write_text("# empty contract — every live route is drift\n", encoding="utf-8")
        monkeypatch.setattr(checker, "_boot_app", lambda _args: _synthetic_app())
        rc = checker.main(["--contract", str(contract)])
        assert rc == 1

    def test_actual_ci_invocation_passes(self) -> None:
        result = subprocess.run(
            [sys.executable, str(_CHECKER_PATH)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
        assert "PASS" in result.stdout
        assert "121 live routes vs 121 contract entries" in result.stdout
