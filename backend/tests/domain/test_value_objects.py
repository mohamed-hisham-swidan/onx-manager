from __future__ import annotations

import pytest

from app.modules.server.domain.value_objects import (
    JavaArguments,
    MemoryAllocation,
    PortNumber,
    ServerProperties,
)
from app.modules.shared.value_objects import (
    BackupJobId,
    CronExpression,
    EmailAddress,
    MinecraftVersion,
    Permission,
    PluginId,
    PluginVersion,
    RoleId,
    ServerGroupId,
    ServerId,
    UserId,
)


class TestEntityId:
    def test_server_id_generates_unique(self) -> None:
        id1 = ServerId()
        id2 = ServerId()
        assert id1 != id2

    def test_server_id_accepts_string(self) -> None:
        sid = ServerId("my-server")
        assert str(sid) == "my-server"

    def test_server_id_equality(self) -> None:
        assert ServerId("a") == ServerId("a")
        assert ServerId("a") != ServerId("b")

    def test_server_id_hashable(self) -> None:
        s = {ServerId("a"), ServerId("a"), ServerId("b")}
        assert len(s) == 2

    def test_server_group_id(self) -> None:
        gid = ServerGroupId("survival")
        assert str(gid) == "survival"

    def test_backup_job_id_generates(self) -> None:
        bid = BackupJobId()
        assert len(str(bid)) > 0

    def test_plugin_id(self) -> None:
        pid = PluginId("essentialsx")
        assert str(pid) == "essentialsx"

    def test_user_id(self) -> None:
        uid = UserId("user-123")
        assert str(uid) == "user-123"

    def test_role_id(self) -> None:
        rid = RoleId("admin")
        assert str(rid) == "admin"


class TestMinecraftVersion:
    def test_parse_full(self) -> None:
        v = MinecraftVersion.parse("1.21.4")
        assert v.major == 1
        assert v.minor == 21
        assert v.patch == 4

    def test_parse_minor_only(self) -> None:
        v = MinecraftVersion.parse("1.21")
        assert v.major == 1
        assert v.minor == 21
        assert v.patch == 0

    def test_parse_invalid(self) -> None:
        with pytest.raises(ValueError):
            MinecraftVersion.parse("abc")

    def test_str(self) -> None:
        assert str(MinecraftVersion(1, 20, 4)) == "1.20.4"

    def test_equality(self) -> None:
        assert MinecraftVersion(1, 20) == MinecraftVersion(1, 20, 0)
        assert MinecraftVersion(1, 20, 4) != MinecraftVersion(1, 20, 3)

    def test_comparison(self) -> None:
        assert MinecraftVersion(1, 20, 4) > MinecraftVersion(1, 20, 3)
        assert MinecraftVersion(1, 20) < MinecraftVersion(1, 21)
        assert MinecraftVersion(1, 20, 4) >= MinecraftVersion(1, 20, 4)
        assert MinecraftVersion(1, 20) <= MinecraftVersion(1, 21)

    def test_hashable(self) -> None:
        v1 = MinecraftVersion(1, 20, 4)
        v2 = MinecraftVersion(1, 20, 4)
        assert hash(v1) == hash(v2)


class TestPluginVersion:
    def test_parse_full(self) -> None:
        v = PluginVersion.parse("1.2.3")
        assert v.major == 1
        assert v.minor == 2
        assert v.patch == 3

    def test_parse_with_prerelease(self) -> None:
        v = PluginVersion.parse("1.2.3-beta.1")
        assert v.prerelease == "beta.1"

    def test_parse_with_build(self) -> None:
        v = PluginVersion.parse("1.2.3+build.42")
        assert v.build == "build.42"

    def test_parse_invalid(self) -> None:
        with pytest.raises(ValueError):
            PluginVersion.parse("abc")

    def test_str(self) -> None:
        assert str(PluginVersion(2, 0, 1)) == "2.0.1"
        assert str(PluginVersion(1, 0, 0, "rc1")) == "1.0.0-rc1"

    def test_comparison(self) -> None:
        assert PluginVersion(2, 0, 0) > PluginVersion(1, 9, 9)
        assert PluginVersion(1, 0, 0, "alpha") < PluginVersion(1, 0, 0)
        assert PluginVersion(1, 0, 0) > PluginVersion(1, 0, 0, "alpha")

    def test_negative_major_raises(self) -> None:
        with pytest.raises(ValueError):
            PluginVersion(-1, 0, 0)


class TestCronExpression:
    def test_valid_expression(self) -> None:
        cron = CronExpression("*/5 * * * *")
        assert str(cron) == "*/5 * * * *"

    def test_valid_with_day_of_week(self) -> None:
        cron = CronExpression("0 9 * * 1-5")
        assert str(cron) == "0 9 * * 1-5"

    def test_valid_complex(self) -> None:
        cron = CronExpression("0 0 1 1,6,12 *")
        assert str(cron) == "0 0 1 1,6,12 *"

    def test_invalid_too_few_fields(self) -> None:
        with pytest.raises(ValueError):
            CronExpression("*/5 * * *")

    def test_invalid_expression(self) -> None:
        with pytest.raises(ValueError):
            CronExpression("not-a-cron")


class TestEmailAddress:
    def test_valid_email(self) -> None:
        email = EmailAddress("user@example.com")
        assert str(email) == "user@example.com"

    def test_invalid_email(self) -> None:
        with pytest.raises(ValueError):
            EmailAddress("not-an-email")

    def test_invalid_without_domain(self) -> None:
        with pytest.raises(ValueError):
            EmailAddress("user@")


class TestPermission:
    def test_create(self) -> None:
        p = Permission(resource="server", action="start")
        assert p.resource == "server"
        assert p.action == "start"

    def test_str(self) -> None:
        assert str(Permission("server", "start")) == "server:start"

    def test_parse(self) -> None:
        p = Permission.parse("server:start")
        assert p.resource == "server"
        assert p.action == "start"

    def test_parse_invalid(self) -> None:
        with pytest.raises(ValueError):
            Permission.parse("invalid")


class TestMemoryAllocation:
    def test_valid(self) -> None:
        m = MemoryAllocation(min_mb=1024, max_mb=2048)
        assert m.min_mb == 1024
        assert m.max_mb == 2048
        assert m.delta_mb == 1024

    def test_min_too_low(self) -> None:
        with pytest.raises(ValueError):
            MemoryAllocation(min_mb=64, max_mb=2048)

    def test_max_less_than_min(self) -> None:
        with pytest.raises(ValueError):
            MemoryAllocation(min_mb=2048, max_mb=1024)

    def test_max_too_high(self) -> None:
        with pytest.raises(ValueError):
            MemoryAllocation(min_mb=1024, max_mb=300000)

    def test_str(self) -> None:
        assert str(MemoryAllocation(1024, 2048)) == "1024-2048M"

    def test_immutable(self) -> None:
        m = MemoryAllocation(1024, 2048)
        with pytest.raises(AttributeError):
            m.min_mb = 512


class TestPortNumber:
    def test_valid(self) -> None:
        p = PortNumber(25565)
        assert str(p) == "25565"

    def test_zero(self) -> None:
        with pytest.raises(ValueError):
            PortNumber(0)

    def test_too_high(self) -> None:
        with pytest.raises(ValueError):
            PortNumber(70000)


class TestJavaArguments:
    def test_valid(self) -> None:
        j = JavaArguments(["-Xmx2G", "-XX:+UseG1GC"])
        assert len(j.args) == 2

    def test_invalid_not_starting_with_dash(self) -> None:
        with pytest.raises(ValueError):
            JavaArguments(["Xmx2G"])

    def test_default_empty(self) -> None:
        j = JavaArguments()
        assert j.args == ()

    def test_as_list(self) -> None:
        j = JavaArguments(["-Xmx2G"])
        assert j.as_list() == ["-Xmx2G"]

    def test_immutable(self) -> None:
        j = JavaArguments(["-Xmx2G"])
        with pytest.raises(AttributeError):
            j.args = ("-Xms1G",)


class TestServerProperties:
    def test_defaults(self) -> None:
        p = ServerProperties(port=PortNumber(25565))
        assert p.motd == "A Minecraft Server"
        assert p.max_players == 20
        assert p.gamemode == "survival"

    def test_invalid_gamemode(self) -> None:
        with pytest.raises(ValueError):
            ServerProperties(port=PortNumber(25565), gamemode="invalid")

    def test_invalid_difficulty(self) -> None:
        with pytest.raises(ValueError):
            ServerProperties(port=PortNumber(25565), difficulty="superhard")

    def test_max_players_out_of_range(self) -> None:
        with pytest.raises(ValueError):
            ServerProperties(port=PortNumber(25565), max_players=1000)

    def test_view_distance_out_of_range(self) -> None:
        with pytest.raises(ValueError):
            ServerProperties(port=PortNumber(25565), view_distance=1)
