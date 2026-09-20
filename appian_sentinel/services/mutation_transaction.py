"""Staged filesystem mutations with all-or-nothing rollback for typed CRUD."""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from types import TracebackType
from typing import Callable, Final, Literal, NamedTuple

_STAGE_DIR: Final[str] = "stage"
_BACKUP_DIR: Final[str] = "backup"


class TransactionError(RuntimeError):
    """Raised when a staged operation cannot be staged or applied."""


class _Operation(NamedTuple):
    kind: Literal["write", "delete"]
    target: Path
    source: Path | None


class _Applied(NamedTuple):
    target: Path
    backup: Path | None
    created_dirs: tuple[Path, ...]


class MutationTransaction:
    """Stage writes and deletes, then apply them as one reversible batch.

    Writes land in a temporary sibling directory of ``root`` so every
    ``os.replace`` stays on one volume and is atomic. Originals are copied or
    moved into the same temporary area, which makes rollback a byte-for-byte
    restore of files and of recursive directory trees.
    """

    def __init__(self, root: Path, *, on_applied: Callable[[Path], None] | None = None) -> None:
        self._root: Path = Path(root).resolve()
        self._on_applied: Callable[[Path], None] | None = on_applied
        self._temp: Path = self._root.parent / f".{self._root.name}.txn-{uuid.uuid4().hex}"
        self._temp.mkdir(parents=True, exist_ok=False)
        self._pending: list[_Operation] = []
        self._applied: list[_Applied] = []
        self._changed: list[Path] = []
        self._sequence: int = 0
        self._closed: bool = False

    @property
    def temp_dir(self) -> Path:
        return self._temp

    @property
    def changed_paths(self) -> list[Path]:
        return list(self._changed)

    def write(self, path: Path, data: bytes) -> None:
        """Stage ``data`` as the new content of ``path``."""
        target = self._resolve(path)
        staged = self._scratch_path(_STAGE_DIR, target)
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(data)
        self._pending.append(_Operation("write", target, staged))

    def delete(self, path: Path) -> None:
        """Stage removal of ``path``; directories are removed recursively."""
        self._pending.append(_Operation("delete", self._resolve(path), None))

    def commit(self) -> list[Path]:
        """Apply every staged operation and return the changed paths."""
        if self._closed:
            raise TransactionError("transaction is already closed")
        try:
            for operation in self._pending:
                self._apply(operation)
                if self._on_applied is not None:
                    self._on_applied(operation.target)
        except BaseException:
            self.rollback()
            raise
        self._pending.clear()
        self._closed = True
        self._cleanup()
        return list(self._changed)

    def rollback(self) -> None:
        """Undo every applied operation, newest first, then drop temp data."""
        if self._closed:
            return
        while self._applied:
            self._restore(self._applied.pop())
        self._pending.clear()
        self._changed.clear()
        self._closed = True
        self._cleanup()

    def __enter__(self) -> MutationTransaction:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False

    def _apply(self, operation: _Operation) -> None:
        target = operation.target
        if operation.kind == "write":
            created = self._ensure_parent(target)
            backup = self._backup(target, move=False)
            source = operation.source
            if source is None:
                raise TransactionError(f"missing staged content for {target}")
            os.replace(source, target)
        else:
            created = ()
            backup = self._backup(target, move=True)
            if backup is None:
                raise TransactionError(f"cannot delete missing path: {target}")
        self._applied.append(_Applied(target, backup, created))
        self._changed.append(target)

    def _restore(self, entry: _Applied) -> None:
        target = entry.target
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        elif target.exists() or target.is_symlink():
            target.unlink()
        if entry.backup is not None:
            os.replace(entry.backup, target)
        for directory in reversed(entry.created_dirs):
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()

    def _backup(self, target: Path, *, move: bool) -> Path | None:
        if not target.exists() and not target.is_symlink():
            return None
        destination = self._scratch_path(_BACKUP_DIR, target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if move:
            os.replace(target, destination)
        elif target.is_dir() and not target.is_symlink():
            shutil.copytree(target, destination, symlinks=True)
        else:
            shutil.copy2(target, destination, follow_symlinks=False)
        return destination

    def _ensure_parent(self, target: Path) -> tuple[Path, ...]:
        missing: list[Path] = []
        parent = target.parent
        while not parent.exists() and parent != parent.parent:
            missing.append(parent)
            parent = parent.parent
        created = tuple(reversed(missing))
        for directory in created:
            directory.mkdir()
        return created

    def _scratch_path(self, area: str, target: Path) -> Path:
        self._sequence += 1
        return self._temp / area / f"{self._sequence:04d}-{target.name}"

    def _resolve(self, path: Path) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self._root / candidate
        candidate = candidate.resolve()
        if candidate != self._root and self._root not in candidate.parents:
            raise TransactionError(f"path escapes transaction root: {candidate}")
        return candidate

    def _cleanup(self) -> None:
        # ponytail: leftover temp dirs after a hard kill need a startup sweep.
        shutil.rmtree(self._temp, ignore_errors=True)
