import os

from app.core.config import AppSettings, ConfigFactory, ServerConfig


class TestAppSettings:
    def test_default_values(self) -> None:
        settings = AppSettings()
        assert settings.app_name == "mcs-manager"
        assert settings.debug is False
        assert settings.log_level == "INFO"
        assert settings.idempotency_ttl_hours == 24

    def test_env_override(self) -> None:
        os.environ["MCS_DATABASE_URL"] = "postgresql+asyncpg://localhost/test"
        settings = AppSettings()
        assert settings.database_url == "postgresql+asyncpg://localhost/test"
        del os.environ["MCS_DATABASE_URL"]

    def test_env_prefix_applied(self) -> None:
        os.environ["MCS_DEBUG"] = "true"
        settings = AppSettings()
        assert settings.debug is True
        del os.environ["MCS_DEBUG"]


class TestServerConfig:
    def test_default_config(self) -> None:
        config = ServerConfig(server_id="srv-1", name="My Server")
        assert config.server_id == "srv-1"
        assert config.name == "My Server"
        assert config.minecraft_version == "1.20.4"
        assert config.memory_min_mb == 1024
        assert config.port == 25565
        assert config.provider == "local"

    def test_frozen_immutable(self) -> None:
        config = ServerConfig(server_id="srv-1", name="test")
        with pytest.raises(AttributeError):
            config.name = "changed"
        config_attr = config.to_dict()
        assert config_attr["name"] == "test"

    def test_to_dict(self) -> None:
        config = ServerConfig(server_id="srv-1", name="test", port=25566)
        d = config.to_dict()
        assert d["server_id"] == "srv-1"
        assert d["port"] == 25566
        assert d["java_args"] == ["-XX:+UseG1GC"]


class TestConfigFactory:
    def test_global_settings(self) -> None:
        settings = ConfigFactory.global_settings()
        assert isinstance(settings, AppSettings)

    def test_for_server_defaults(self) -> None:
        config = ConfigFactory.for_server("test-srv")
        assert config.server_id == "test-srv"
        assert config.name == "test-srv"

    def test_for_server_with_overrides(self) -> None:
        config = ConfigFactory.for_server("test-srv", {"port": 25566, "memory_min_mb": 2048})
        assert config.port == 25566
        assert config.memory_min_mb == 2048

    def test_for_server_partial_override(self) -> None:
        config = ConfigFactory.for_server("test-srv", {"auto_start": True})
        assert config.auto_start is True
        assert config.port == 25565


import pytest
