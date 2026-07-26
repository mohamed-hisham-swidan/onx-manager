import pytest

from app.core.feature_flags import FeatureFlagRegistry


@pytest.mark.asyncio
class TestFeatureFlagRegistry:
    async def test_flag_defaults_to_disabled(self) -> None:
        registry = FeatureFlagRegistry()
        result = await registry.is_enabled("new-ui", fallback=False)
        assert result is False

    async def test_enable_toggle(self) -> None:
        registry = FeatureFlagRegistry()
        await registry.enable("new-ui")
        assert await registry.is_enabled("new-ui") is True

    async def test_disable_toggle(self) -> None:
        registry = FeatureFlagRegistry()
        await registry.enable("new-ui")
        await registry.disable("new-ui")
        assert await registry.is_enabled("new-ui") is False

    async def test_fallback_when_flag_not_registered(self) -> None:
        registry = FeatureFlagRegistry()
        assert await registry.is_enabled("missing", fallback=True) is True
        assert await registry.is_enabled("missing", fallback=False) is False

    async def test_percentage_rollout(self) -> None:
        registry = FeatureFlagRegistry()
        await registry.enable("rollout")
        await registry.set_percentage("rollout", 100)
        assert await registry.is_enabled("rollout", user_id="user-1") is True

        await registry.set_percentage("rollout", 0)
        assert await registry.is_enabled("rollout", user_id="user-1") is True
        await registry.disable("rollout")
        assert await registry.is_enabled("rollout", user_id="user-1") is False

    async def test_percentage_zero_when_disabled(self) -> None:
        registry = FeatureFlagRegistry()
        await registry.set_percentage("test", 50)
        assert await registry.is_enabled("test") is False

    async def test_user_override(self) -> None:
        registry = FeatureFlagRegistry()
        await registry.enable("feature")
        await registry.set_user_override("feature", "admin", False)

        assert await registry.is_enabled("feature", user_id="admin") is False
        assert await registry.is_enabled("feature", user_id="other") is True

    async def test_list_flags(self) -> None:
        registry = FeatureFlagRegistry()
        await registry.register("flag-a", "First flag")
        await registry.register("flag-b", "Second flag")

        flags = await registry.list_flags()
        assert len(flags) >= 2

    async def test_register_does_not_overwrite(self) -> None:
        registry = FeatureFlagRegistry()
        await registry.register("test", "original")
        await registry.enable("test")
        await registry.register("test", "should-not-overwrite")

        assert await registry.is_enabled("test") is True
