from __future__ import annotations

from typing import Any

from app.core.exceptions import NotFoundError
from app.core.query_bus import Query, QueryHandler
from app.modules.server.domain.repository import ServerRepository
from app.modules.versioning.application.git_branch_adapter import git_branch_context
from app.modules.versioning.domain.diff import diff_commits
from app.modules.versioning.domain.repository import VersioningRepository


class DiffCommitsQuery(Query):
    server_id: str
    from_commit_id: str
    to_commit_id: str


class DiffCommitsHandler(QueryHandler[DiffCommitsQuery]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo

    async def handle(self, query: DiffCommitsQuery) -> dict[str, Any]:
        from app.core.persistence.db import database
        from app.modules.server.infrastructure.repository import SQLServerRepository
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        if self._server_repo is not None and self._versioning_repo is not None:
            return await self._execute(query, self._server_repo, self._versioning_repo)

        async with database.session_factory() as session:
            server_repo = SQLServerRepository(session)
            versioning_repo = SQLVersioningRepository(session)
            return await self._execute(query, server_repo, versioning_repo)

    async def _execute(
        self,
        query: DiffCommitsQuery,
        server_repo: ServerRepository,
        versioning_repo: VersioningRepository,
    ) -> dict[str, Any]:
        from app.modules.shared.value_objects import ServerId

        try:
            server = await server_repo.get(ServerId(query.server_id))
        except Exception as exc:
            raise NotFoundError(f"Server '{query.server_id}' not found") from exc

        git_context = git_branch_context(server) if server is not None else None
        if git_context is not None:
            runner = git_context.service.open_runner(str(server.id), git_context.server_root)
            from_sha = runner.run(
                "rev-parse",
                "--verify",
                "--quiet",
                f"{query.from_commit_id}^{{commit}}",
                check=False,
            )
            to_sha = runner.run(
                "rev-parse", "--verify", "--quiet", f"{query.to_commit_id}^{{commit}}", check=False
            )
            if from_sha.returncode == 0 and to_sha.returncode == 0:
                from_resolved = from_sha.stdout.strip()
                to_resolved = to_sha.stdout.strip()

                def _lockfile(sha):
                    r = runner.run("show", f"{sha}:onx-jars.lock.json", check=False)
                    if r.returncode != 0:
                        return None
                    try:
                        import json

                        return json.loads(r.stdout)
                    except Exception:
                        return None

                lf_from = _lockfile(from_resolved)
                lf_to = _lockfile(to_resolved)

                mc_from = lf_from.get("mc") if isinstance(lf_from, dict) else None
                mc_to = lf_to.get("mc") if isinstance(lf_to, dict) else None
                loader_from = (
                    lf_from.get("loader", {}).get("id") if isinstance(lf_from, dict) else None
                )
                loader_to = lf_to.get("loader", {}).get("id") if isinstance(lf_to, dict) else None

                files_from = (
                    {
                        f.get("path"): f
                        for f in (lf_from.get("files", []) if isinstance(lf_from, dict) else [])
                    }
                    if isinstance(lf_from, dict)
                    else {}
                )
                files_to = (
                    {
                        f.get("path"): f
                        for f in (lf_to.get("files", []) if isinstance(lf_to, dict) else [])
                    }
                    if isinstance(lf_to, dict)
                    else {}
                )

                added_mods = sorted(set(files_to) - set(files_from))
                removed_mods = sorted(set(files_from) - set(files_to))
                modified_mods = sorted(
                    p
                    for p in (set(files_from) & set(files_to))
                    if files_from[p].get("sha256") != files_to[p].get("sha256")
                )

                diff_result = runner.run(
                    "diff-tree",
                    "-r",
                    "--no-commit-id",
                    "--name-status",
                    "-z",
                    from_resolved,
                    to_resolved,
                    check=False,
                )
                added: list[str] = []
                removed: list[str] = []
                modified: list[str] = []
                tokens = diff_result.stdout.split("\x00")
                i = 0
                while i < len(tokens):
                    tok = tokens[i]
                    if not tok:
                        i += 1
                        continue
                    if "\t" in tok:
                        status, path = tok.split("\t", 1)
                        if status.startswith("A"):
                            added.append(path)
                        elif status.startswith("D"):
                            removed.append(path)
                        elif status.startswith("M"):
                            modified.append(path)
                        i += 1
                        continue
                    status = tok
                    if status[:1] in ("R", "C"):
                        old_path = tokens[i + 1] if i + 1 < len(tokens) else ""
                        new_path = tokens[i + 2] if i + 2 < len(tokens) else ""
                        if old_path:
                            removed.append(old_path)
                        if new_path:
                            added.append(new_path)
                        i += 3
                        continue
                    path = tokens[i + 1] if i + 1 < len(tokens) else ""
                    if path:
                        if status.startswith("A"):
                            added.append(path)
                        elif status.startswith("D"):
                            removed.append(path)
                        elif status.startswith("M"):
                            modified.append(path)
                    i += 2

                server_type_diff = (
                    {"from": loader_from or "", "to": loader_to or ""}
                    if (loader_from or "") != (loader_to or "")
                    else None
                )
                mc_version_diff = (
                    {"from": mc_from or "", "to": mc_to or ""}
                    if (mc_from or "") != (mc_to or "")
                    else None
                )
                return {
                    "from_commit_id": query.from_commit_id,
                    "to_commit_id": query.to_commit_id,
                    "has_changes": bool(
                        added
                        or removed
                        or modified
                        or added_mods
                        or removed_mods
                        or modified_mods
                        or server_type_diff is not None
                        or mc_version_diff is not None
                    ),
                    "server_type": server_type_diff,
                    "minecraft_version": mc_version_diff,
                    "java_args": {},
                    "configs": {"added": added, "removed": removed, "modified": modified},
                    "env_vars": {},
                    "mods": {
                        "added": added_mods,
                        "removed": removed_mods,
                        "modified": modified_mods,
                    },
                }

        commit_a = await versioning_repo.get_commit(query.from_commit_id)
        if commit_a is None or commit_a.server_id != query.server_id:
            raise NotFoundError(
                f"From commit '{query.from_commit_id}' not found on server '{query.server_id}'"
            )

        commit_b = await versioning_repo.get_commit(query.to_commit_id)
        if commit_b is None or commit_b.server_id != query.server_id:
            raise NotFoundError(
                f"To commit '{query.to_commit_id}' not found on server '{query.server_id}'"
            )

        diff = diff_commits(commit_a, commit_b)
        return diff.to_dict()
