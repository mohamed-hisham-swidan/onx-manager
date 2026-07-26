from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.modules.shared.value_objects import PluginVersion


class FilesystemPermission(BaseModel):
    paths: list[str] = Field(default_factory=list)


class NetworkPermission(BaseModel):
    hosts: list[str] = Field(default_factory=list)
    ports: list[int] = Field(default_factory=list)


class EventPermission(BaseModel):
    subscribe: list[str] = Field(default_factory=list)
    publish: list[str] = Field(default_factory=list)


class PluginPermissions(BaseModel):
    filesystem: FilesystemPermission = Field(default_factory=FilesystemPermission)
    network: NetworkPermission = Field(default_factory=NetworkPermission)
    events: EventPermission = Field(default_factory=EventPermission)


class PluginDependency(BaseModel):
    name: str
    min_version: str = "0.0.0"


class PluginDependencies(BaseModel):
    plugins: list[PluginDependency] = Field(default_factory=list)


class HookDeclaration(BaseModel):
    handler: str
    timeout: int = 30


class PluginManifest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    version: str = Field(..., pattern=r"^\d+\.\d+\.\d+(?:-[a-zA-Z0-9.]+)?(?:\+[a-zA-Z0-9.]+)?$")
    min_app_version: str = Field(default="4.0.0", pattern=r"^\d+\.\d+\.\d+")
    isolation: Literal["subprocess", "container"] = "subprocess"
    permissions: PluginPermissions = Field(default_factory=PluginPermissions)
    hooks: dict[str, HookDeclaration] = Field(default_factory=dict)
    dependencies: PluginDependencies = Field(default_factory=PluginDependencies)

    @field_validator("version")
    @classmethod
    def _validate_version(cls, v: str) -> str:
        PluginVersion.parse(v)
        return v

    def parsed_version(self) -> PluginVersion:
        return PluginVersion.parse(self.version)

    def parsed_min_app_version(self) -> PluginVersion:
        return PluginVersion.parse(self.min_app_version)


class ManifestLoader:
    @staticmethod
    def from_yaml(path: str) -> PluginManifest:
        import yaml

        with open(path, "r") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            raise ValueError("Manifest must be a mapping")

        return PluginManifest(**data)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> PluginManifest:
        return PluginManifest(**data)
