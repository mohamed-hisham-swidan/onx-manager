from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class EntityId:
    value: str

    def __str__(self) -> str:
        return self.value

    def __eq__(self, other: object) -> bool:
        if isinstance(other, type(self)):
            return self.value == other.value
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.value)


class ServerId(EntityId):
    def __init__(self, value: str | None = None) -> None:
        super().__init__(value or uuid.uuid4().hex)


class ServerGroupId(EntityId):
    pass


class BackupJobId(EntityId):
    def __init__(self, value: str | None = None) -> None:
        super().__init__(value or uuid.uuid4().hex)


class PluginId(EntityId):
    def __init__(self, value: str | None = None) -> None:
        super().__init__(value or uuid.uuid4().hex)


class UserId(EntityId):
    pass


class RoleId(EntityId):
    pass


class ApiKeyId(EntityId):
    pass


@dataclass(frozen=True)
class MinecraftVersion:
    major: int
    minor: int
    patch: int = 0

    _pattern: ClassVar[re.Pattern[str]] = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?$")

    def __init__(self, major: int, minor: int, patch: int = 0) -> None:
        object.__setattr__(self, "major", major)
        object.__setattr__(self, "minor", minor)
        object.__setattr__(self, "patch", patch)

    @classmethod
    def parse(cls, version: str) -> MinecraftVersion:
        match = cls._pattern.match(version)
        if not match:
            raise ValueError(f"Invalid Minecraft version format: {version!r}")
        major = int(match.group(1))
        minor = int(match.group(2))
        patch = int(match.group(3)) if match.group(3) else 0
        return cls(major=major, minor=minor, patch=patch)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, MinecraftVersion):
            return (self.major, self.minor, self.patch) == (other.major, other.minor, other.patch)
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.major, self.minor, self.patch))

    def __lt__(self, other: MinecraftVersion) -> bool:
        return (self.major, self.minor, self.patch) < (other.major, other.minor, other.patch)

    def __le__(self, other: MinecraftVersion) -> bool:
        return (self.major, self.minor, self.patch) <= (other.major, other.minor, other.patch)

    def __gt__(self, other: MinecraftVersion) -> bool:
        return (self.major, self.minor, self.patch) > (other.major, other.minor, other.patch)

    def __ge__(self, other: MinecraftVersion) -> bool:
        return (self.major, self.minor, self.patch) >= (other.major, other.minor, other.patch)


@dataclass(frozen=True)
class PluginVersion:
    major: int
    minor: int
    patch: int
    prerelease: str = ""
    build: str = ""

    _pattern: ClassVar[re.Pattern[str]] = re.compile(
        r"^(\d+)\.(\d+)\.(\d+)(?:-([a-zA-Z0-9.]+))?(?:\+([a-zA-Z0-9.]+))?$",
    )

    def __post_init__(self) -> None:
        if self.major < 0:
            raise ValueError("major must be non-negative")
        if self.minor < 0:
            raise ValueError("minor must be non-negative")
        if self.patch < 0:
            raise ValueError("patch must be non-negative")

    @classmethod
    def parse(cls, version: str) -> PluginVersion:
        match = cls._pattern.match(version)
        if not match:
            raise ValueError(f"Invalid semver format: {version!r}")
        return cls(
            major=int(match.group(1)),
            minor=int(match.group(2)),
            patch=int(match.group(3)),
            prerelease=match.group(4) or "",
            build=match.group(5) or "",
        )

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            base += f"-{self.prerelease}"
        if self.build:
            base += f"+{self.build}"
        return base

    def __lt__(self, other: PluginVersion) -> bool:
        if (self.major, self.minor, self.patch) != (other.major, other.minor, other.patch):
            return (self.major, self.minor, self.patch) < (other.major, other.minor, other.patch)
        if self.prerelease and not other.prerelease:
            return True
        if not self.prerelease and other.prerelease:
            return False
        return self.prerelease < other.prerelease

    def __le__(self, other: PluginVersion) -> bool:
        return self == other or self < other

    def __gt__(self, other: PluginVersion) -> bool:
        return not (self <= other)

    def __ge__(self, other: PluginVersion) -> bool:
        return not (self < other)


@dataclass(frozen=True)
class CronExpression:
    expression: str

    _pattern: ClassVar[re.Pattern[str]] = re.compile(
        r"^(\*(?:/[0-9]+)?|[0-9]+(?:-[0-9]+)?(?:/[0-9]+)?(?:,(?:[0-9]+(?:-[0-9]+)?(?:/[0-9]+)?))*) "
        r"(\*(?:/[0-9]+)?|[0-9]+(?:-[0-9]+)?(?:/[0-9]+)?(?:,(?:[0-9]+(?:-[0-9]+)?(?:/[0-9]+)?))*) "
        r"(\*(?:/[0-9]+)?|[0-9]+(?:-[0-9]+)?(?:/[0-9]+)?(?:,(?:[0-9]+(?:-[0-9]+)?(?:/[0-9]+)?))*) "
        r"(\*(?:/[0-9]+)?|[0-9]+(?:-[0-9]+)?(?:/[0-9]+)?(?:,(?:[0-9]+(?:-[0-9]+)?(?:/[0-9]+)?))*) "
        r"(\*(?:/[0-9]+)?|[0-9]+(?:-[0-9]+)?(?:/[0-9]+)?(?:,(?:[0-9]+(?:-[0-9]+)?(?:/[0-9]+)?))*)"
        r"(?: "
        r"(\*(?:/[0-9]+)?|[0-9]+(?:-[0-9]+)?(?:/[0-9]+)?(?:,(?:[0-9]+(?:-[0-9]+)?(?:/[0-9]+)?))*)"
        r")?$",
    )

    def __post_init__(self) -> None:
        if not self._pattern.match(self.expression):
            raise ValueError(f"Invalid cron expression: {self.expression!r}")

    def __str__(self) -> str:
        return self.expression


@dataclass(frozen=True)
class EmailAddress:
    value: str

    _pattern: ClassVar[re.Pattern[str]] = re.compile(
        r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    )

    def __post_init__(self) -> None:
        if not self._pattern.match(self.value):
            raise ValueError(f"Invalid email address: {self.value!r}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Permission:
    resource: str
    action: str

    def __str__(self) -> str:
        return f"{self.resource}:{self.action}"

    @classmethod
    def parse(cls, value: str) -> Permission:
        parts = value.split(":", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid permission format: {value!r}")
        return cls(resource=parts[0], action=parts[1])
