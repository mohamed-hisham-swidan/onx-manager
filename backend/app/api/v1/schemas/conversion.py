from __future__ import annotations

from pydantic import BaseModel


class ConvertToAdvancedRequest(BaseModel):
    """Optional request body for Simple -> Advanced conversion."""

    pass


class ConvertToAdvancedResponse(BaseModel):
    server_id: str
    mode: str
    main_commit_sha: str
    backup_id: str | None = None
    class_c_snapshot_id: str | None = None
    lockfile_path: str
    files_count: int = 0
    cas_ingested: int = 0
    worktree_path: str | None = None


class ConvertToSimpleRequest(BaseModel):
    name: str | None = None
    port: int | None = None


class ConvertToSimpleResponse(BaseModel):
    source_server_id: str
    new_server_id: str
    name: str
    mode: str
    root_path: str
    lockfile_path: str
    files_count: int = 0
