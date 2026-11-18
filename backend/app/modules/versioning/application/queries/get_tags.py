from __future__ import annotations

from typing import Any

from app.core.exceptions import NotFoundError
from app.core.query_bus import Query, QueryHandler
from app.modules.server.domain.repository import ServerRepository
from app.modules.versioning.application.git_branch_adapter import git_branch_context
from app.modules.versioning.domain.repository import VersioningRepository


class GetServerTagsQuery(Query):
    server_id: str


class GetServerTagsHandler(QueryHandler[GetServerTagsQuery]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo

    async def handle(self, query: GetServerTagsQuery) -> list[dict[str, Any]]:
        from app.core.persistence.db import database
        from app.modules.server.infrastructure.repository import SQLServerRepository
        from app.modules.shared.value_objects import ServerId
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        if self._server_repo is not None and self._versioning_repo is not None:
            server_repo = self._server_repo
            versioning_repo = self._versioning_repo
        else:
            async with database.session_factory() as session:
                server_repo = SQLServerRepository(session)
                versioning_repo = SQLVersioningRepository(session)
                try:
                    await server_repo.get(ServerId(query.server_id))
                except Exception as exc:
                    raise NotFoundError(f"Server '{query.server_id}' not found") from exc
                tags = await versioning_repo.list_tags(query.server_id)
                # git merge if possible
                try:
                    server = await server_repo.get(ServerId(query.server_id))
                except Exception:
                    server = None
                git_context = git_branch_context(server) if server is not None else None
                return self._build_tags(query.server_id, tags, git_context, server)

        try:
            await server_repo.get(ServerId(query.server_id))
        except Exception as exc:
            raise NotFoundError(f"Server '{query.server_id}' not found") from exc
        tags = await versioning_repo.list_tags(query.server_id)
        try:
            server = await server_repo.get(ServerId(query.server_id))
        except Exception:
            server = None
        git_context = git_branch_context(server) if server is not None else None
        return self._build_tags(query.server_id, tags, git_context, server)

    def _build_tags(self, server_id, tags, git_context, server):
        import uuid as _uuid

        out = [
            {
                "id": t.id,
                "server_id": t.server_id,
                "name": t.name,
                "commit_id": t.commit_id,
                "created_at": t.created_at.isoformat(),
            }
            for t in tags
        ]
        seen = {t.name for t in tags}
        if git_context is not None:
            runner = git_context.service.open_runner(str(server.id), git_context.server_root)
            result = runner.run(
                "for-each-ref",
                "refs/tags",
                "--format=%(refname:short)%x1f%(objectname)%x1f%(creatordate:iso8601)",
                check=False,
            )
            for line in result.stdout.splitlines():
                parts = line.split("\x1f")
                if len(parts) < 2:
                    continue
                name = parts[0].strip()
                sha = parts[1].strip()
                created = parts[2].strip() if len(parts) > 2 else ""
                if not name or name in seen:
                    continue
                seen.add(name)
                out.append(
                    {
                        "id": str(_uuid.uuid5(_uuid.NAMESPACE_URL, f"tag:{server_id}:{name}")),
                        "server_id": server_id,
                        "name": name,
                        "commit_id": sha,
                        "created_at": created or "",
                    }
                )
        return out


class GetServerTagQuery(Query):
    server_id: str
    name: str


class GetServerTagHandler(QueryHandler[GetServerTagQuery]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo

    async def handle(self, query: GetServerTagQuery) -> dict[str, Any] | None:
        from app.core.persistence.db import database
        from app.modules.server.infrastructure.repository import SQLServerRepository
        from app.modules.shared.value_objects import ServerId
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        if self._server_repo is not None and self._versioning_repo is not None:
            server_repo = self._server_repo
            versioning_repo = self._versioning_repo
        else:
            async with database.session_factory() as session:
                server_repo = SQLServerRepository(session)
                versioning_repo = SQLVersioningRepository(session)
                try:
                    await server_repo.get(ServerId(query.server_id))
                except Exception as exc:
                    raise NotFoundError(f"Server '{query.server_id}' not found") from exc
                t = await versioning_repo.get_tag(query.server_id, query.name)
                if not t:
                    # try git
                    try:
                        server = await server_repo.get(ServerId(query.server_id))
                    except Exception:
                        server = None
                    git_context = git_branch_context(server) if server is not None else None
                    if git_context is not None:
                        runner = git_context.service.open_runner(
                            str(server.id), git_context.server_root
                        )
                        r = runner.run(
                            "rev-parse",
                            "--verify",
                            "--quiet",
                            f"refs/tags/{query.name}",
                            check=False,
                        )
                        if r.returncode == 0:
                            r2 = runner.run(
                                "rev-parse", f"refs/tags/{query.name}^{{commit}}", check=False
                            )
                            sha = r2.stdout.strip() if r2.returncode == 0 else r.stdout.strip()
                            return {
                                "id": str(
                                    __import__("uuid").uuid5(
                                        __import__("uuid").NAMESPACE_URL,
                                        f"tag:{query.server_id}:{query.name}",
                                    )
                                ),
                                "server_id": query.server_id,
                                "name": query.name,
                                "commit_id": sha,
                                "created_at": "",
                            }
                    return None
                return {
                    "id": t.id,
                    "server_id": t.server_id,
                    "name": t.name,
                    "commit_id": t.commit_id,
                    "created_at": t.created_at.isoformat(),
                }

        try:
            await server_repo.get(ServerId(query.server_id))
        except Exception as exc:
            raise NotFoundError(f"Server '{query.server_id}' not found") from exc
        t = await versioning_repo.get_tag(query.server_id, query.name)
        if t:
            return {
                "id": t.id,
                "server_id": t.server_id,
                "name": t.name,
                "commit_id": t.commit_id,
                "created_at": t.created_at.isoformat(),
            }
        try:
            server = await server_repo.get(ServerId(query.server_id))
        except Exception:
            server = None
        git_context = git_branch_context(server) if server is not None else None
        if git_context is not None and server is not None:
            runner = git_context.service.open_runner(str(server.id), git_context.server_root)
            r = runner.run(
                "rev-parse", "--verify", "--quiet", f"refs/tags/{query.name}", check=False
            )
            if r.returncode == 0:
                r2 = runner.run("rev-parse", f"refs/tags/{query.name}^{{commit}}", check=False)
                sha = r2.stdout.strip() if r2.returncode == 0 else r.stdout.strip()
                return {
                    "id": str(
                        __import__("uuid").uuid5(
                            __import__("uuid").NAMESPACE_URL, f"tag:{query.server_id}:{query.name}"
                        )
                    ),
                    "server_id": query.server_id,
                    "name": query.name,
                    "commit_id": sha,
                    "created_at": "",
                }
        return None
