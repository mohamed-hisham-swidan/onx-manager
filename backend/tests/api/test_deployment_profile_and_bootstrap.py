"""Tests for panel deployment_profile, zero-friction secret bootstrap, and SPA static serving."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import ValidationError

from app.api.v1.routers.setup import (
    UpdateAccessModeRequest,
    get_setup_status,
    update_access_mode,
)
from app.core.command_bus import CommandResult
from app.core.config import AppSettings
from app.core.exceptions import MasterKekMissingError, SecurityPermissionError
from app.main import create_app
from app.modules.auth.infrastructure import jwt as jwt_mod
from app.modules.storage.encryption import load_or_create_backup_key
from app.modules.versioning.infrastructure.vault_crypto import (
    ensure_master_kek_file,
    load_master_kek,
)


class TestDeploymentProfileConfig:
    def test_defaults_to_vps_and_reads_onx_and_mcs_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ONX_DEPLOYMENT_PROFILE", raising=False)
        monkeypatch.delenv("MCS_DEPLOYMENT_PROFILE", raising=False)
        assert AppSettings().deployment_profile == "vps"

        monkeypatch.setenv("ONX_DEPLOYMENT_PROFILE", "local")
        assert AppSettings().deployment_profile == "local"

        monkeypatch.setenv("ONX_DEPLOYMENT_PROFILE", "VPS")
        assert AppSettings().deployment_profile == "vps"

        monkeypatch.delenv("ONX_DEPLOYMENT_PROFILE", raising=False)
        monkeypatch.setenv("MCS_DEPLOYMENT_PROFILE", "LOCAL")
        assert AppSettings().deployment_profile == "local"

    def test_rejects_invalid_deployment_profile(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ONX_DEPLOYMENT_PROFILE", "invalid-mode")
        with pytest.raises(ValidationError):
            AppSettings()


class TestSetupRoutesDeploymentProfile:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("profile", ["local", "vps"])
    async def test_setup_status_and_access_mode_expose_deployment_profile(
        self, profile: str
    ) -> None:
        fake_bus = AsyncMock()
        fake_bus.ask.return_value = {
            "initialized": False,
            "access_mode": "LOCAL",
            "user_count": 0,
            "version": "0.1.0",
        }
        fake_bus.send.return_value = CommandResult(
            success=True,
            data={
                "initialized": True,
                "access_mode": "GLOBAL",
                "user_count": 1,
                "version": "0.1.0",
            },
        )
        owner_user: dict[str, Any] = {"roles": ["owner"], "permissions": ["*"]}

        with patch(
            "app.core.config.ConfigFactory.global_settings",
            return_value=AppSettings(deployment_profile=profile, advanced_mode_enabled=True),
        ):
            status_resp = await get_setup_status(query_bus=fake_bus)
            access_resp = await update_access_mode(
                body=UpdateAccessModeRequest(access_mode="GLOBAL"),
                current_user=owner_user,
                command_bus=fake_bus,
            )

        assert status_resp.deployment_profile == profile
        assert status_resp.advanced_mode_enabled is True
        assert access_resp.deployment_profile == profile
        assert access_resp.access_mode == "GLOBAL"


class TestZeroFrictionSecretBootstrap:
    def test_init_jwt_auto_creates_0600_key_on_fresh_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        key_path = tmp_path / "config" / "jwt_private_key.pem"
        monkeypatch.delenv("ONX_JWT_PRIVATE_KEY", raising=False)
        monkeypatch.delenv("MCS_JWT_PRIVATE_KEY", raising=False)

        orig_priv = jwt_mod._private_key
        orig_pub = jwt_mod._public_key
        orig_kid = jwt_mod._key_id
        try:
            settings = AppSettings(jwt_private_key="", jwt_private_key_path=str(key_path))
            jwt_mod.init_jwt_from_settings(settings)

            assert key_path.is_file()
            first_bytes = key_path.read_bytes()
            if os.name == "posix":
                assert (key_path.stat().st_mode & 0o777) == 0o600

            # Reloading must reuse existing key rather than overwriting it
            jwt_mod.init_jwt_from_settings(settings)
            assert key_path.read_bytes() == first_bytes
        finally:
            jwt_mod._private_key = orig_priv
            jwt_mod._public_key = orig_pub
            jwt_mod._key_id = orig_kid

    def test_load_or_create_backup_key_auto_creates_0600(self, tmp_path: Path) -> None:
        key_path = tmp_path / "config" / "backup_encryption_key.bin"
        first = load_or_create_backup_key(str(key_path))
        assert len(first) == 32
        assert key_path.is_file()
        if os.name == "posix":
            assert (key_path.stat().st_mode & 0o777) == 0o600
        assert load_or_create_backup_key(str(key_path)) == first

    @pytest.mark.skipif(os.name != "posix", reason="POSIX 0600 permission check")
    def test_ensure_master_kek_file_bootstraps_and_enforces_0600(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ONX_MASTER_KEK", raising=False)
        monkeypatch.delenv("ONX_MASTER_KEK_FILE", raising=False)
        orig_kek_file = os.environ.get("ONX_MASTER_KEK_FILE")
        kek_path = tmp_path / "config" / "master_kek.key"

        try:
            # Direct vault calls must still fail closed when unconfigured
            with pytest.raises(MasterKekMissingError):
                load_master_kek(AppSettings(master_kek="", master_kek_file=""))

            created = ensure_master_kek_file(
                AppSettings(master_kek="", master_kek_file=str(kek_path))
            )
            assert created == kek_path
            assert kek_path.is_file()
            assert (kek_path.stat().st_mode & 0o777) == 0o600
            assert os.environ.get("ONX_MASTER_KEK_FILE") == str(kek_path.resolve())

            first_material = kek_path.read_text(encoding="ascii")
            loaded = load_master_kek()
            assert len(loaded.key_bytes) == 32

            # Repeated boot preserves existing key material
            ensure_master_kek_file(AppSettings(master_kek="", master_kek_file=str(kek_path)))
            assert kek_path.read_text(encoding="ascii") == first_material

            # Widened permissions fail closed
            os.chmod(kek_path, 0o644)
            with pytest.raises(SecurityPermissionError):
                ensure_master_kek_file(AppSettings(master_kek="", master_kek_file=str(kek_path)))
        finally:
            if kek_path.exists():
                os.chmod(kek_path, 0o600)
            if orig_kek_file is None:
                os.environ.pop("ONX_MASTER_KEK_FILE", None)
            else:
                os.environ["ONX_MASTER_KEK_FILE"] = orig_kek_file

    def test_ensure_master_kek_file_noop_when_env_kek_supplied(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ONX_MASTER_KEK_FILE", raising=False)
        monkeypatch.setenv("ONX_MASTER_KEK", "a5" * 32)
        default_kek = tmp_path / "config" / "master_kek.key"
        res = ensure_master_kek_file(default_path=default_kek)
        assert res is None
        assert not default_kek.exists()


class TestSpaStaticMiddleware:
    @pytest.mark.asyncio
    async def test_serves_spa_assets_and_fallbacks_without_shadowing_api(
        self, tmp_path: Path
    ) -> None:
        dist = tmp_path / "dist"
        assets = dist / "assets"
        assets.mkdir(parents=True)
        (dist / "index.html").write_text("<html><body>ONX_SPA_ROOT</body></html>", encoding="utf-8")
        (assets / "app-123.js").write_text("console.log('onx');", encoding="utf-8")

        app = create_app(static_dir=dist)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            root_resp = await client.get("/")
            assert root_resp.status_code == 200
            assert "ONX_SPA_ROOT" in root_resp.text

            setup_resp = await client.get("/setup")
            assert setup_resp.status_code == 200
            assert "ONX_SPA_ROOT" in setup_resp.text

            deep_resp = await client.get("/servers/srv-1/console")
            assert deep_resp.status_code == 200
            assert "ONX_SPA_ROOT" in deep_resp.text

            js_resp = await client.get("/assets/app-123.js")
            assert js_resp.status_code == 200
            assert "console.log('onx')" in js_resp.text
            assert "immutable" in js_resp.headers.get("cache-control", "")

            missing_asset = await client.get("/assets/missing.js")
            assert missing_asset.status_code == 404

            encoded_traversal = await client.get("/%2e%2e/%2e%2e/etc/passwd")
            assert encoded_traversal.status_code == 404

            with patch(
                "app.modules.server.infrastructure.providers.docker.DockerProvider.ping",
                new=AsyncMock(return_value=False),
            ):
                health = await client.get("/health")
            assert health.status_code == 200
            assert health.json()["status"] == "ok"

            protected = await client.get("/api/v1/servers")
            assert protected.status_code == 401

    @pytest.mark.asyncio
    async def test_spa_rejects_raw_scope_traversal(self, tmp_path: Path) -> None:
        from app.api.v1.middleware.spa_static import SpaStaticMiddleware

        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html>OK</html>", encoding="utf-8")

        async def _unused_app(_scope, _receive, _send) -> None:
            raise AssertionError("Should not fall through on traversal")

        mw = SpaStaticMiddleware(_unused_app, static_dir=dist)
        captured: list[dict[str, Any]] = []

        async def _send(msg: dict[str, Any]) -> None:
            captured.append(msg)

        async def _receive() -> dict[str, Any]:
            return {"type": "http.request", "body": b"", "more_body": False}

        await mw(
            {"type": "http", "method": "GET", "path": "/../../etc/passwd"},
            _receive,
            _send,
        )
        assert captured[0]["status"] == 404

    @pytest.mark.asyncio
    async def test_static_dir_off_disables_spa_serving(self) -> None:
        app = create_app(static_dir="off")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/")
            assert resp.status_code == 401
