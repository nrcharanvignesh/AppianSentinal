"""Durable Git-like workspace history. Internal service API, not HTTP."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from difflib import unified_diff
from pathlib import Path
from typing import Any

from appian_sentinel.config import settings
from appian_sentinel.models.object_registry import official_export_directories
from appian_sentinel.models.workspace import FileChangeKind, FileDiff, Revision, StagedEntry

_HISTORY_DIR = ".history"
_SECRET_METADATA_KEYS = frozenset(
    {
        "password",
        "token",
        "secret",
        "pat",
        "api_key",
        "apikey",
        "authorization",
        "ado_pat",
        "litellm_api_key",
        "access_key",
        "private_key",
    }
)
_TRACKED_ROOTS = official_export_directories()
_OBJECT_ROOTS = _TRACKED_ROOTS - {"META-INF", "application"}


class PathEscapeError(ValueError):
    """Relative path resolved outside the configured workspace."""


class RevisionConflictError(RuntimeError):
    """HEAD moved; caller held a stale expected revision."""

    def __init__(self, expected: str, actual: str | None) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"expected revision {expected}, actual {actual}")


class RevisionNotFoundError(KeyError):
    def __init__(self, revision_hash: str) -> None:
        self.revision_hash = revision_hash
        super().__init__(revision_hash)


class WorkspaceHistoryService:
    """Snapshot, stage, commit, diff, and restore under one workspace root."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = (root if root is not None else settings.sentinel_workspace).resolve()
        self._history = self._root / _HISTORY_DIR
        self._blobs = self._history / "blobs"
        self._revisions = self._history / "revisions"
        self._index_path = self._history / "index.json"

    def create_baseline(
        self,
        *,
        actor: str,
        requirement: str,
        message: str = "baseline",
        expected_revision: str | None = None,
    ) -> Revision:
        self._ensure_dirs()
        self._assert_expected(expected_revision)
        if self.head() is not None:
            raise RevisionConflictError(expected_revision or "", self.head())
        files: dict[str, str] = {}
        for path in self._iter_workspace_files():
            rel = self._rel_posix(path)
            files[rel] = self._store_blob(path.read_bytes())
        revision = self._write_revision(
            parent=None,
            is_baseline=True,
            actor=actor,
            requirement=requirement,
            message=message,
            files=files,
        )
        self._save_index(head=revision.hash, baseline=revision.hash, staged=[])
        return revision

    def stage(self, relative_path: str) -> StagedEntry:
        self._ensure_dirs()
        path = self._safe_path(relative_path)
        key = self._norm_key(relative_path)
        head_files = self._head_files()
        if not path.exists():
            if key not in head_files:
                raise FileNotFoundError(key)
            entry = StagedEntry(path=key, blob_hash=None, kind=FileChangeKind.DELETED)
        else:
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"Not a regular file: {key}")
            blob_hash = self._store_blob(path.read_bytes())
            if key not in head_files:
                kind = FileChangeKind.ADDED
            elif head_files[key] == blob_hash:
                index = self._load_index()
                staged = [item for item in index["staged"] if item["path"] != key]
                self._save_index(head=index["head"], baseline=index["baseline"], staged=staged)
                return StagedEntry(path=key, blob_hash=blob_hash, kind=FileChangeKind.MODIFIED)
            else:
                kind = FileChangeKind.MODIFIED
            entry = StagedEntry(path=key, blob_hash=blob_hash, kind=kind)
        index = self._load_index()
        staged = [item for item in index["staged"] if item["path"] != key]
        staged.append(entry.model_dump())
        self._save_index(head=index["head"], baseline=index["baseline"], staged=staged)
        return entry

    def staged_changes(self) -> list[StagedEntry]:
        return [StagedEntry.model_validate(item) for item in self._load_index()["staged"]]

    def working_changes(self) -> list[FileDiff]:
        """Return unstaged workspace changes against HEAD."""
        before = self._head_files()
        current_paths = {
            self._rel_posix(path): path
            for path in self._iter_workspace_files()
        }
        paths = sorted(set(before) | set(current_paths))
        changes: list[FileDiff] = []
        for relative_path in paths:
            before_hash = before.get(relative_path)
            path = current_paths.get(relative_path)
            after_bytes = path.read_bytes() if path is not None else None
            after_hash = hashlib.sha256(after_bytes).hexdigest() if after_bytes is not None else None
            if before_hash == after_hash:
                continue
            kind = (
                FileChangeKind.ADDED
                if before_hash is None
                else FileChangeKind.DELETED
                if after_hash is None
                else FileChangeKind.MODIFIED
            )
            changes.append(
                FileDiff(
                    path=relative_path,
                    kind=kind,
                    unified_diff=_unified_diff(
                        relative_path,
                        self._blob_or_none(before_hash),
                        after_bytes,
                    ),
                    before_hash=before_hash,
                    after_hash=after_hash,
                    object_id=_object_id(relative_path),
                )
            )
        return changes

    def stage_all(self) -> list[StagedEntry]:
        """Stage every tracked working-tree change."""
        for change in self.working_changes():
            self.stage(change.path)
        return self.staged_changes()

    def log(self, limit: int = 50) -> list[Revision]:
        """Return newest-first revision history from HEAD."""
        revisions: list[Revision] = []
        revision_hash = self.head()
        while revision_hash is not None and len(revisions) < limit:
            revision = self.get_revision(revision_hash)
            revisions.append(revision)
            revision_hash = revision.parent
        return revisions

    def baseline(self) -> str | None:
        """Return the baseline revision hash."""
        return self._load_index().get("baseline")

    def commit(
        self,
        *,
        actor: str,
        requirement: str,
        message: str,
        expected_revision: str | None = None,
    ) -> Revision:
        self._ensure_dirs()
        self._assert_expected(expected_revision)
        staged = self.staged_changes()
        if not staged:
            raise ValueError("Nothing staged")
        parent = self.head()
        if parent is None:
            raise ValueError("Workspace has no baseline")
        files = dict(self._head_files())
        for entry in staged:
            if entry.kind is FileChangeKind.DELETED or entry.blob_hash is None:
                files.pop(entry.path, None)
            else:
                files[entry.path] = entry.blob_hash
        revision = self._write_revision(
            parent=parent,
            is_baseline=False,
            actor=actor,
            requirement=requirement,
            message=message,
            files=files,
        )
        index = self._load_index()
        self._save_index(head=revision.hash, baseline=index["baseline"], staged=[])
        return revision

    def restore(
        self,
        revision_hash: str,
        *,
        actor: str,
        requirement: str,
        message: str = "restore",
        expected_revision: str | None = None,
    ) -> Revision:
        self._ensure_dirs()
        self._assert_expected(expected_revision)
        target = self.get_revision(revision_hash)
        parent = self.head()
        if parent is None:
            raise ValueError("Workspace has no baseline")
        current_files = self._head_files()
        for rel in current_files:
            if rel not in target.files:
                path = self._safe_path(rel)
                if path.is_file() and not path.is_symlink():
                    path.unlink()
        for rel, blob_hash in target.files.items():
            dest = self._safe_path(rel)
            dest.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(dest, self._read_blob(blob_hash))
        revision = self._write_revision(
            parent=parent,
            is_baseline=False,
            actor=actor,
            requirement=requirement,
            message=message,
            files=dict(target.files),
        )
        index = self._load_index()
        self._save_index(head=revision.hash, baseline=index["baseline"], staged=[])
        return revision

    def diff(self, from_revision: str, to_revision: str | None = None) -> list[FileDiff]:
        before = self.get_revision(from_revision).files
        after_hash = to_revision if to_revision is not None else self.head()
        if after_hash is None:
            raise ValueError("Workspace has no HEAD")
        after = self.get_revision(after_hash).files
        paths = sorted(set(before) | set(after))
        diffs: list[FileDiff] = []
        for path in paths:
            b_hash = before.get(path)
            a_hash = after.get(path)
            if b_hash == a_hash:
                continue
            if b_hash is None:
                kind = FileChangeKind.ADDED
            elif a_hash is None:
                kind = FileChangeKind.DELETED
            else:
                kind = FileChangeKind.MODIFIED
            diffs.append(
                FileDiff(
                    path=path,
                    kind=kind,
                    unified_diff=_unified_diff(path, self._blob_or_none(b_hash), self._blob_or_none(a_hash)),
                    before_hash=b_hash,
                    after_hash=a_hash,
                    object_id=_object_id(path),
                )
            )
        return diffs

    def head(self) -> str | None:
        return self._load_index().get("head")

    def get_revision(self, revision_hash: str) -> Revision:
        path = self._revisions / f"{revision_hash}.json"
        if not path.is_file():
            raise RevisionNotFoundError(revision_hash)
        return Revision.model_validate_json(path.read_text(encoding="utf-8"))

    def _ensure_dirs(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        self._blobs.mkdir(parents=True, exist_ok=True)
        self._revisions.mkdir(parents=True, exist_ok=True)

    def _assert_expected(self, expected_revision: str | None) -> None:
        if expected_revision is None:
            return
        actual = self.head()
        if actual != expected_revision:
            raise RevisionConflictError(expected_revision, actual)

    def _head_files(self) -> dict[str, str]:
        head = self.head()
        if head is None:
            return {}
        return dict(self.get_revision(head).files)

    def _write_revision(
        self,
        *,
        parent: str | None,
        is_baseline: bool,
        actor: str,
        requirement: str,
        message: str,
        files: dict[str, str],
    ) -> Revision:
        timestamp = datetime.now(timezone.utc)
        tree_hash = _hash_json({"files": dict(sorted(files.items()))})
        payload: dict[str, Any] = {
            "parent": parent,
            "is_baseline": is_baseline,
            "actor": actor,
            "requirement": requirement,
            "timestamp": timestamp.isoformat(),
            "message": message,
            "tree_hash": tree_hash,
            "files": dict(sorted(files.items())),
        }
        payload = _strip_secrets(payload)
        revision_hash = _hash_json(payload)
        payload["hash"] = revision_hash
        dest = self._revisions / f"{revision_hash}.json"
        if dest.exists():
            return Revision.model_validate_json(dest.read_text(encoding="utf-8"))
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        _atomic_write(dest, encoded.encode("ascii"))
        return Revision.model_validate_json(encoded)

    def _store_blob(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        dest = self._blobs / digest
        if not dest.exists():
            _atomic_write(dest, data)
        return digest

    def _read_blob(self, blob_hash: str) -> bytes:
        path = self._blobs / blob_hash
        if not path.is_file():
            raise FileNotFoundError(blob_hash)
        return path.read_bytes()

    def _blob_or_none(self, blob_hash: str | None) -> bytes | None:
        if blob_hash is None:
            return None
        return self._read_blob(blob_hash)

    def _iter_workspace_files(self) -> list[Path]:
        files: list[Path] = []
        if not self._root.exists():
            return files
        for path in self._root.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.relative_to(self._root)
            if rel.parts and rel.parts[0] == _HISTORY_DIR:
                continue
            if not rel.parts or rel.parts[0] not in _TRACKED_ROOTS:
                continue
            files.append(path)
        return files

    def _rel_posix(self, path: Path) -> str:
        return path.relative_to(self._root).as_posix()

    def _norm_key(self, relative_path: str) -> str:
        self._safe_path(relative_path)
        return relative_path.replace("\\", "/").strip("/")

    def _safe_path(self, relative_path: str) -> Path:
        if not relative_path or relative_path.startswith(("/", "\\")):
            raise PathEscapeError(f"Path escapes workspace: {relative_path}")
        posix = relative_path.replace("\\", "/")
        parts = posix.split("/")
        if any(part in ("", ".", "..") for part in parts) or any(":" in part for part in parts):
            raise PathEscapeError(f"Path escapes workspace: {relative_path}")
        candidate = (self._root / Path(*parts)).resolve()
        root = self._root.resolve()
        if not candidate.is_relative_to(root):
            raise PathEscapeError(f"Path escapes workspace: {relative_path}")
        rel = candidate.relative_to(root)
        if rel.parts and rel.parts[0] == _HISTORY_DIR:
            raise PathEscapeError(f"Path escapes workspace: {relative_path}")
        return candidate

    def _load_index(self) -> dict[str, Any]:
        if not self._index_path.is_file():
            return {"head": None, "baseline": None, "staged": []}
        raw = json.loads(self._index_path.read_text(encoding="utf-8"))
        return {
            "head": raw.get("head"),
            "baseline": raw.get("baseline"),
            "staged": list(raw.get("staged") or []),
        }

    def _save_index(self, *, head: str | None, baseline: str | None, staged: list[dict[str, Any]]) -> None:
        payload = {"head": head, "baseline": baseline, "staged": staged}
        encoded = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True)
        _atomic_write(self._index_path, encoded.encode("ascii"))


def _strip_secrets(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if key.lower() in _SECRET_METADATA_KEYS:
            continue
        if isinstance(value, dict):
            cleaned[key] = _strip_secrets(value)
        else:
            cleaned[key] = value
    return cleaned


def _hash_json(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _object_id(path: str) -> str | None:
    parts = path.split("/")
    if len(parts) >= 2 and parts[0] in _OBJECT_ROOTS:
        return Path(parts[-1]).stem
    return None


def _unified_diff(path: str, before: bytes | None, after: bytes | None) -> str:
    before_text = _decode_text(before)
    after_text = _decode_text(after)
    if before_text is None or after_text is None:
        return f"Binary file {path} changed\n"
    return "".join(
        unified_diff(
            before_text,
            after_text,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def _decode_text(data: bytes | None) -> list[str] | None:
    if data is None:
        return []
    try:
        return data.decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        return None


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp_", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
