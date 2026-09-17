from __future__ import annotations

from abc import ABC, abstractmethod

from app.modules.versioning.domain.entities import (
    ImportReview,
    Materialization,
    ServerBranch,
    ServerCommit,
    ServerTestRun,
    ServerWorldSnapshot,
    Tag,
)


class VersioningRepository(ABC):
    """Abstract repository for versioning aggregates and entities."""

    # Branches
    @abstractmethod
    async def get_branch(self, branch_id: str) -> ServerBranch | None:
        pass

    @abstractmethod
    async def get_branch_by_name(self, server_id: str, name: str) -> ServerBranch | None:
        pass

    @abstractmethod
    async def list_branches(self, server_id: str) -> list[ServerBranch]:
        pass

    @abstractmethod
    async def save_branch(self, branch: ServerBranch) -> ServerBranch:
        pass

    # Commits
    @abstractmethod
    async def get_commit(self, commit_id: str) -> ServerCommit | None:
        pass

    @abstractmethod
    async def list_commits(
        self, server_id: str, branch_id: str | None = None, limit: int = 50
    ) -> list[ServerCommit]:
        pass

    @abstractmethod
    async def save_commit(self, commit: ServerCommit) -> ServerCommit:
        pass

    # World Snapshots
    @abstractmethod
    async def get_snapshot(self, snapshot_id: str) -> ServerWorldSnapshot | None:
        pass

    @abstractmethod
    async def save_snapshot(self, snapshot: ServerWorldSnapshot) -> ServerWorldSnapshot:
        pass

    # Test Runs
    @abstractmethod
    async def get_test_run(self, test_run_id: str) -> ServerTestRun | None:
        pass

    @abstractmethod
    async def get_active_test_run_for_server(self, server_id: str) -> ServerTestRun | None:
        pass

    @abstractmethod
    async def list_test_runs(self, server_id: str, limit: int = 20) -> list[ServerTestRun]:
        pass

    @abstractmethod
    async def save_test_run(self, test_run: ServerTestRun) -> ServerTestRun:
        pass

    # Commit Parents
    async def get_commit_parents(self, commit_id: str) -> list[str]:
        _ = commit_id
        return []

    # Tags
    async def get_tag(self, server_id: str, name: str) -> Tag | None:
        _ = (server_id, name)
        return None

    async def list_tags(self, server_id: str) -> list[Tag]:
        _ = server_id
        return []

    async def save_tag(self, tag: Tag) -> Tag:
        return tag

    # Materializations
    async def get_materialization(self, materialization_id: str) -> Materialization | None:
        _ = materialization_id
        return None

    async def list_materializations(self, server_id: str) -> list[Materialization]:
        _ = server_id
        return []

    async def save_materialization(self, materialization: Materialization) -> Materialization:
        return materialization

    # Import Reviews
    async def get_import_review(self, review_id: str) -> ImportReview | None:
        _ = review_id
        return None

    async def list_import_reviews(self, server_id: str, limit: int = 50) -> list[ImportReview]:
        _ = (server_id, limit)
        return []

    async def save_import_review(self, review: ImportReview) -> ImportReview:
        return review

