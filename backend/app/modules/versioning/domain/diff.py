from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.modules.versioning.domain.entities import ServerCommit
from app.modules.versioning.domain.value_objects import Tree


@dataclass(frozen=True)
class DictDiff:
    added: dict[str, str] = field(default_factory=dict)
    removed: dict[str, str] = field(default_factory=dict)
    modified: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.modified)

    def to_dict(self) -> dict[str, Any]:
        return {
            "added": self.added,
            "removed": self.removed,
            "modified": self.modified,
        }


@dataclass(frozen=True)
class ModDiff:
    added: list[dict[str, Any]] = field(default_factory=list)
    removed: list[dict[str, Any]] = field(default_factory=list)
    modified: list[dict[str, Any]] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.modified)

    def to_dict(self) -> dict[str, Any]:
        return {
            "added": self.added,
            "removed": self.removed,
            "modified": self.modified,
        }


@dataclass(frozen=True)
class TreeDiff:
    configs: DictDiff
    env_vars: DictDiff
    mods: ModDiff
    server_type: dict[str, str] | None = None
    minecraft_version: dict[str, str] | None = None
    java_args: dict[str, str] | None = None

    @property
    def has_changes(self) -> bool:
        return bool(
            self.configs.has_changes
            or self.env_vars.has_changes
            or self.mods.has_changes
            or self.server_type is not None
            or self.minecraft_version is not None
            or self.java_args is not None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_changes": self.has_changes,
            "server_type": self.server_type,
            "minecraft_version": self.minecraft_version,
            "java_args": self.java_args,
            "configs": self.configs.to_dict(),
            "env_vars": self.env_vars.to_dict(),
            "mods": self.mods.to_dict(),
        }


@dataclass(frozen=True)
class CommitDiff:
    from_commit_id: str
    to_commit_id: str
    diff: TreeDiff

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_commit_id": self.from_commit_id,
            "to_commit_id": self.to_commit_id,
            **self.diff.to_dict(),
        }


def _diff_string_dicts(a: dict[str, str], b: dict[str, str]) -> DictDiff:
    keys_a = set(a.keys())
    keys_b = set(b.keys())

    added = {k: b[k] for k in sorted(keys_b - keys_a)}
    removed = {k: a[k] for k in sorted(keys_a - keys_b)}
    modified = {
        k: {"old": a[k], "new": b[k]}
        for k in sorted(keys_a & keys_b)
        if a[k] != b[k]
    }
    return DictDiff(added=added, removed=removed, modified=modified)


def _diff_mods(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> ModDiff:
    def _mod_key(m: dict[str, Any]) -> str:
        return str(m.get("filename") or m.get("name") or m.get("mod_id") or "")

    mods_a = {_mod_key(m): m for m in a if _mod_key(m)}
    mods_b = {_mod_key(m): m for m in b if _mod_key(m)}

    keys_a = set(mods_a.keys())
    keys_b = set(mods_b.keys())

    added = [mods_b[k] for k in sorted(keys_b - keys_a)]
    removed = [mods_a[k] for k in sorted(keys_a - keys_b)]
    modified = [
        {"key": k, "old": mods_a[k], "new": mods_b[k]}
        for k in sorted(keys_a & keys_b)
        if mods_a[k] != mods_b[k]
    ]
    return ModDiff(added=added, removed=removed, modified=modified)


def diff_trees(tree_a: Tree, tree_b: Tree) -> TreeDiff:
    """Deterministically diff two Trees."""
    server_type_diff = (
        {"old": tree_a.server_type, "new": tree_b.server_type}
        if tree_a.server_type != tree_b.server_type
        else None
    )
    mc_version_diff = (
        {"old": tree_a.minecraft_version, "new": tree_b.minecraft_version}
        if tree_a.minecraft_version != tree_b.minecraft_version
        else None
    )
    java_args_diff = (
        {"old": tree_a.java_args, "new": tree_b.java_args}
        if tree_a.java_args != tree_b.java_args
        else None
    )

    configs_diff = _diff_string_dicts(tree_a.configs, tree_b.configs)
    env_vars_diff = _diff_string_dicts(tree_a.env_vars, tree_b.env_vars)
    mods_diff = _diff_mods(tree_a.mods, tree_b.mods)

    return TreeDiff(
        server_type=server_type_diff,
        minecraft_version=mc_version_diff,
        java_args=java_args_diff,
        configs=configs_diff,
        env_vars=env_vars_diff,
        mods=mods_diff,
    )


def diff_commits(commit_a: ServerCommit, commit_b: ServerCommit) -> CommitDiff:
    """Deterministically diff two Commits within the same server."""
    if commit_a.server_id != commit_b.server_id:
        raise ValueError(
            f"Cannot diff commits across different servers: "
            f"'{commit_a.server_id}' vs '{commit_b.server_id}'"
        )
    diff = diff_trees(commit_a.tree, commit_b.tree)
    return CommitDiff(
        from_commit_id=commit_a.id,
        to_commit_id=commit_b.id,
        diff=diff,
    )
