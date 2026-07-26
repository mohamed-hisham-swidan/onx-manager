from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.modules.shared.value_objects import PluginVersion


@dataclass
class ResolvedDependency:
    name: str
    version: PluginVersion
    dependencies: list[ResolvedDependency] = field(default_factory=list)


@dataclass
class DependencyConflict:
    name: str
    required_by: list[str]
    message: str


@dataclass
class ResolutionResult:
    success: bool
    resolved: list[ResolvedDependency] = field(default_factory=list)
    conflicts: list[DependencyConflict] = field(default_factory=list)

    @property
    def constraint_chain(self) -> str:
        if not self.conflicts:
            return ""
        parts: list[str] = []
        for c in self.conflicts:
            chain = " -> ".join(c.required_by)
            parts.append(f"{c.name}: {c.message} (required by: {chain})")
        return "; ".join(parts)


class DependencyResolver:
    def __init__(self) -> None:
        self._available: dict[str, list[dict[str, Any]]] = {}

    def register_plugin(self, name: str, version: str, dependencies: list[dict[str, Any]]) -> None:
        if name not in self._available:
            self._available[name] = []
        self._available[name].append({"version": version, "deps": dependencies})

    def register_plugins(self, plugins: list[dict[str, Any]]) -> None:
        for p in plugins:
            self.register_plugin(
                name=p["name"],
                version=p.get("version", "0.0.0"),
                dependencies=p.get("dependencies", []),
            )

    def resolve(
        self,
        name: str,
        version_constraint: str | None = None,
    ) -> ResolutionResult:
        result = ResolutionResult(success=False)
        visited: set[str] = set()
        chain: list[str] = []
        resolved: list[ResolvedDependency] = []

        def resolve_one(current_name: str, constraint: str | None) -> ResolvedDependency | None:
            if current_name in visited:
                result.conflicts.append(
                    DependencyConflict(
                        name=current_name,
                        required_by=list(chain),
                        message="Circular dependency detected",
                    ),
                )
                return None

            versions = self._available.get(current_name)
            if not versions:
                result.conflicts.append(
                    DependencyConflict(
                        name=current_name,
                        required_by=list(chain),
                        message=f"Plugin not found in registry",
                    ),
                )
                return None

            if constraint:
                constraint_version = PluginVersion.parse(constraint)
                matching = [v for v in versions if PluginVersion.parse(v["version"]) >= constraint_version]
                if not matching:
                    result.conflicts.append(
                        DependencyConflict(
                            name=current_name,
                            required_by=list(chain),
                            message=f"No version >= {constraint} found (available: {[v['version'] for v in versions]})",
                        ),
                    )
                    return None
                selected = max(matching, key=lambda v: PluginVersion.parse(v["version"]))
            else:
                selected = max(versions, key=lambda v: PluginVersion.parse(v["version"]))

            visited.add(current_name)
            chain.append(current_name)

            sub_deps: list[ResolvedDependency] = []
            for dep in selected["deps"]:
                dep_name = dep["name"] if isinstance(dep, dict) else dep
                dep_constraint = dep.get("min_version") if isinstance(dep, dict) else None
                sub = resolve_one(dep_name, dep_constraint)
                if sub is None:
                    chain.pop()
                    visited.discard(current_name)
                    return None
                sub_deps.append(sub)

            chain.pop()
            dep = ResolvedDependency(
                name=current_name,
                version=PluginVersion.parse(selected["version"]),
                dependencies=sub_deps,
            )
            return dep

        root = resolve_one(name, version_constraint)
        if root and not result.conflicts:
            result.success = True
            result.resolved = [root]
        return result
