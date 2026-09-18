"""Pydantic models for durable Git-like workspace history."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class FileChangeKind(str, Enum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


class FileDiff(BaseModel):
    """Unified diff for one workspace path (file or Appian object XML)."""

    path: str
    kind: FileChangeKind
    unified_diff: str = ""
    before_hash: str | None = None
    after_hash: str | None = None
    object_id: str | None = None


class StagedEntry(BaseModel):
    path: str
    blob_hash: str | None = None
    kind: FileChangeKind


class Revision(BaseModel):
    """Immutable commit metadata. File bytes live in the blob store, not here."""

    model_config = ConfigDict(frozen=True)

    hash: str
    parent: str | None = None
    is_baseline: bool = False
    actor: str
    requirement: str
    timestamp: datetime
    message: str = ""
    tree_hash: str
    files: dict[str, str] = Field(default_factory=dict)
    """Relative posix path -> blob sha256. Never file contents or secrets."""
